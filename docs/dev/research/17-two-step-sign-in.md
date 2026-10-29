# 17 · Two-step sign-in with codes from an authenticator app (TOTP)

| | |
|---|---|
| Status | Accepted, 2026-10-28. The owner asked for it ("do the TOTP sign-in codes"); the choices below are the defaults this note took, listed in §9 so they can be changed. Built 2026-10-28, the server and the screens together. The schema step is **22**. |
| Scope | A person with a password can turn on **two-step sign-in**. After the password, sign-in asks for a 6-digit code from an authenticator app (for example Aegis, 2FAS, Google Authenticator, Microsoft Authenticator, 1Password, Bitwarden). Ten single-use **recovery codes** cover a lost phone. An admin, or the command line, can remove it for a person who has lost both. |
| Out of scope | Passkeys (WebAuthn), codes by SMS or email, requiring two-step sign-in for everyone or for admins, "remember this device for 30 days". All "Later", §10. |
| Builds on | `app/auth/routes.py` (sign-in, reset links), `app/auth/me.py`, `app/auth/admin_api.py`, `app/auth/throttle.py`, `app/crypto.py` (`Keyring.seal`), `app/admin.py`; note 07 (accounts) and its §3.1 table of second factors. |
| Sources | RFC 4226 (HOTP), RFC 6238 (TOTP) and their test vectors; the Key Uri Format that authenticator apps read (`otpauth://totp/...`, from the Google Authenticator project wiki); OWASP Multifactor Authentication Cheat Sheet; NIST SP 800-63B-4 §3.1.4 (single-factor OTP) and §3.2.2 (rate limiting). |

## 1. Why

The app holds health records behind one password. A reused or guessed password is the most likely way in, and the ROADMAP calls a
second factor the biggest security gain left (note 07 §8 risk R3). Codes from an authenticator app work on every phone, need no
network and no third company, and need nothing from the server but a stored secret.

## 2. How it works for a person

1. **Settings → Account → Two-step sign-in → Turn on** (asks for the password again, as other account changes do).
2. The screen shows a QR code, the same secret as text, and on a phone a link that opens the authenticator app. The person adds it
   and types the 6-digit code the app shows. That proves the app has the secret; nothing changes until then.
3. The screen shows **ten recovery codes**, once, with Copy and Download. Each works once, in place of a code.
4. Other devices are signed out. From now on, sign-in asks for the code after the password.

**Lost phone**: sign in with a recovery code, then turn two-step sign-in off and on again with the new phone. **No phone and no
recovery codes**: an admin removes it (Server administration → People), or the server's operator runs
`python -m app.admin remove-two-step USERNAME`. Then the person signs in with the password alone and can turn it on again.

## 3. The codes (`app/auth/totp.py`, standard library only)

* RFC 6238 with the defaults every authenticator app supports: HMAC-SHA-1, 6 digits, 30-second steps, Unix time from 0. A new
  dependency (`pyotp`) is not needed: the algorithm is about 20 lines and is tested against the RFC's own vectors.
* The secret is 20 random bytes (160 bits, RFC 4226 §4), shown as 32 base32 characters.
* A code is accepted for the step before, the current step and the step after (about ±30 seconds of clock difference), and **each
  code works once**: the server keeps the last step used and refuses that step or any earlier one.
* Recovery codes: 10 codes of 10 characters from a 32-letter alphabet without look-alike letters (50 bits each), shown as
  `xxxxx-xxxxx`. Only their SHA-256 is stored. Dashes, spaces and letter case are ignored when one is typed. A new set replaces the old.

## 4. Storage (schema step 22)

```sql
CREATE TABLE IF NOT EXISTS totp_factors (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  secret_enc BLOB NOT NULL,   -- Keyring.seal(purpose="totp", owner=user_id)
  key_id TEXT,
  created_at TEXT NOT NULL,
  enabled_at TEXT,            -- NULL while the person has not typed the first code
  last_step INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS totp_recovery_codes (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash BLOB NOT NULL,
  used_at TEXT
);
```

* The secret is sealed like the stored API keys, so a copy of the database alone does not give the codes. It is re-encrypted by
  `rotate-secret-key` (`crypto.ENCRYPTED_COLUMNS`). If `SECRET_KEY` is lost, codes can no longer be checked; recovery codes still work
  (they are hashes) and an admin can remove the factor.
* Not in the data export (a credential, like sessions and tokens). Deleting the account deletes both tables' rows (cascade).

## 5. Sign-in

`POST /api/auth/login` takes an optional `code`. The password is checked first, exactly as now (one hash per attempt, the same
throttles). Then, for a person with two-step sign-in on:

| Request | Answer |
|---|---|
| password wrong (with or without a code) | the same `401 "Username or password is incorrect"` as now |
| password right, no `code` | `401 {"detail": "Enter the 6-digit code from your authenticator app.", "totp_required": true, "field": "code"}`. Not counted as a failure: the client asks for the code and sends the password again with it. |
| password right, wrong code | `401 {"detail": "That code is not right. …", "totp_required": true, "field": "code"}`, **counted as a failed sign-in** (the same per-name, per-device and per-address counters as a wrong password, so guessing codes is as slow as guessing passwords, and 100 failures lock the account) |
| password right, a recovery code | signed in; the code is used up; `notice` says how many are left |
| password right, right code | signed in |

The `401` for a missing code tells the client that the password was right. That cannot be avoided by any two-step scheme; the
code still has to be guessed, at the speed above.

**Reset links** (an admin's, or the person's own account-setup link) still set the password, but do not sign in a person with
two-step sign-in on: the answer is `{"user": null, "totp_required": true}`, and the person signs in with the new password and a code.
Otherwise anyone holding a reset link would skip the second step.

**Re-auth** (`POST /api/auth/reauth`) stays password only: it is asked of a person who is already signed in with both steps.

Proxy and `none` modes: the sign-in proxy does sign-in, so every route here answers `404` and the login field is ignored.

## 6. Routes

| Route | Who | Does |
|---|---|---|
| `GET /api/me/totp` | user | `{available, enabled, enabled_at, recovery_codes_left}`. `available` is false outside local mode or for a proxy account. |
| `POST /api/me/totp/setup` | user *(re-auth)* | A new secret, kept as "not on yet": `{secret, uri, issuer, account}`. The only time the secret leaves the server. `409` if already on. |
| `POST /api/me/totp/enable` | user *(re-auth)* | `{code}`: turns it on if the code is right for the pending secret. Answers `{recovery_codes: [10], signed_out: n}` and signs out the person's other sessions. `400` wrong code (`field: code`), `409` nothing pending or already on; 10 tries in 15 minutes (`totp_enable`). |
| `POST /api/me/totp/recovery-codes` | user *(re-auth)* | A new set of 10, the old set void. `409` when off. |
| `DELETE /api/me/totp` | user *(re-auth)* | Turns it off and removes the recovery codes. `204`. |
| `DELETE /api/admin/users/{id}/totp` | admin *(re-auth)* | The same for another person (lost phone and codes). `{removed: bool}`; `404` unknown id. |

`GET /api/admin/users` gains `two_step: bool` per person. Audit actions (all shown in the person's own activity): `totp.enabled`,
`totp.disabled` (`via`: `self`, `admin` or `cli`), `totp.recovery_codes_renewed`, `totp.recovery_code_used` (with how many are left),
and `login.failed` with `via: "code"`.

Assistant and device tokens are not touched by any of this: each is its own credential, already limited to one scope.

## 7. The screens

* Sign-in: after a `totp_required` answer the form shows one more field, "Code from your authenticator app", with
  `autocomplete="one-time-code"` and `inputmode="numeric"`, and a line "Lost your phone? Type a recovery code instead."
* Settings → Account: a "Two-step sign-in" block (on or off, codes left, Turn on, New recovery codes, Turn off).
* The QR code is drawn in the browser from a vendored QR library (`app/static/vendor/`, with its hash): the secret never goes to
  another site, and no image is fetched.
* Server administration → People: "Two-step: on" and **Remove two-step sign-in**.
* The demo answers the `/api/me/totp` routes as "not available in the demo".

## 8. Tests

RFC 4226 and RFC 6238 vectors; the window and replay rule; recovery codes (format, single use, typed with dashes or spaces); every row
of §5, including the counted failure and the lock at 100; reset links; the routes of §6 with re-auth, `404` in proxy and none mode and
not-yours; the sealed secret (moved row does not decrypt, key rotation); the CLI; the migration; auth coverage and the OpenAPI document.

## 9. Choices taken (the owner can change any of them)

1. Built on the standard library, no `pyotp`.
2. Optional for each person. Nobody is made to use it.
3. Turning it on signs out the person's other devices.
4. Turning it off needs only the password again, not a code (as GitHub does): a person who lost their phone and is still signed in
   can turn it off and on again.
5. Reset links do not sign in a person with two-step sign-in on (§5).
6. An admin can remove another person's two-step sign-in. An admin can already reset that person's password, so this adds no power,
   and it is audited.

## 10. Later

* ~~`AUTH_REQUIRE_TWO_STEP_ADMINS=true`: admins must turn it on.~~ Built 2026-10-29 as the setting `auth.require_two_step_admins`
  (env `AUTH_REQUIRE_TWO_STEP_ADMINS`, off by default): `require_admin` answers `403 {"two_step_required": true}` to a local admin
  without it in `AUTH_MODE=local`; the admin turning it on must have it on (`409`); `GET /api/me/totp` says `required`.
* Passkeys (WebAuthn) as a second factor or instead of the password (note 07 §3.1); then the password minimum can drop to 8.
* "Trust this device for 30 days".
