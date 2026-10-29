# 18 · Passkeys: sign in with a fingerprint, face or device PIN

| | |
|---|---|
| Status | Accepted, 2026-10-29. The owner asked for it ("start passkeys") after two-step sign-in (note 17). The choices below are the defaults this note took, listed in §9 so they can be changed. Built 2026-10-29, the server and the screens together. The schema step is **23**. |
| Scope | A person with a password can add **passkeys** (up to 10) and then sign in with one: the phone or computer asks for a fingerprint, face or device PIN, and no password or code is typed. Settings lists, renames and removes them; an admin, or the command line, can remove them all for an account. |
| Out of scope | Accounts without a password, passkeys for re-authentication, passkeys in the autofill list of the username field ("conditional UI"), checking which company made an authenticator (attestation). All "Later", §10. |
| Builds on | Note 17 (two-step sign-in), `app/auth/routes.py` (sign-in, throttles), `app/auth/me.py`, `app/auth/admin_api.py`, `app/admin.py`, `app/crypto.py`. |
| Sources | W3C Web Authentication Level 3 (§7.1 registration and §7.2 authentication steps for a Relying Party, §6.1 authenticator data, §16 test vectors); RFC 8949 (CBOR); RFC 9052/9053 (COSE keys and algorithms); FIDO Alliance passkey guidance on discoverable credentials and user verification; NIST SP 800-63B-4 (a passkey with user verification is a multi-factor authenticator). |

## 1. Why

A passkey cannot be phished, guessed or reused from a leak: the private key never leaves the person's device, and the browser only
offers it to this server's address. It is also easier than a password and a code, which matters for people who are unwell, tired or
have trouble typing. NIST counts a passkey that checks a fingerprint, face or PIN as two factors at once.

## 2. How it works for a person

1. **Settings → Account → Passkeys → Add a passkey** (asks for the password again, like other account changes). The phone or computer
   asks to save a passkey for this server. The person can name it ("Phone", "Laptop").
2. At sign-in, **Sign in with a passkey**. The device asks for the fingerprint, face or PIN, and the person is in. No username, no
   password, no code.
3. The password still works as before, with the two-step code if that is on. Passkeys are an extra way in, not a replacement.

**Lost device:** sign in another way (password and code, or another passkey) and remove that passkey in Settings. An admin can remove
all of an account's passkeys (Server administration → People), and so can `python -m app.admin remove-passkeys USERNAME`.

## 3. The checks (`app/auth/webauthn.py`, built on `cryptography` only)

A new dependency is not needed. `webauthn` 3.0.1 pulls in four more packages (`cbor2`, `pyOpenSSL`, `pyasn1`, `pyasn1-modules`) for
attestation formats this server does not use. What is left is the Relying Party steps of WebAuthn §7.1 and §7.2, a small CBOR reader
(definite lengths only, the types WebAuthn uses) and the COSE key types browsers make: ES256, ES384, ES512, RS256 and EdDSA (Ed25519).
They are tested against the W3C test vectors (`tests/data/webauthn_w3c_vectors.json`) and a real browser's virtual authenticator.

Registration (§7.1) checks: `type` is `webauthn.create`; the challenge is the one this server issued for this person, unused and less
than 5 minutes old; the origin is this server's; `crossOrigin` is not true and there is no `topOrigin` (the page is not inside another
site's frame); the RP ID hash is this server's; the user-present and **user-verified** flags are set; there is attested credential data
with a supported key; the credential ID is at most 1,023 bytes and not already registered. Attestation is not checked: the server asks for
`attestation: "none"`, accepts any format, and stores nothing from the statement.

Sign-in (§7.2) checks: `type` is `webauthn.get`; the challenge as above (not tied to a person); the origin, frame and RP ID hash as above;
user present and user verified; the credential ID is a stored passkey of an active account; the user handle, when sent, matches; the
signature over `authenticatorData || SHA-256(clientDataJSON)` verifies with the stored key; and the signature counter, when both the
stored and the new value are not zero, went up (a counter that does not is a sign of a cloned key: refused and audited).

The RP ID is the host of `PUBLIC_URL` when it is set, else the host this request came to. The accepted origin is `PUBLIC_URL`'s origin,
or the request's own. Browsers allow passkeys only over HTTPS, and on `localhost`.

## 4. Storage (schema step 23)

```sql
CREATE TABLE IF NOT EXISTS passkeys (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  credential_id BLOB NOT NULL UNIQUE,
  public_key BLOB NOT NULL,       -- the COSE key as the authenticator sent it
  alg INTEGER NOT NULL,
  user_handle BLOB NOT NULL,      -- random, 32 bytes, the same for all of one person's passkeys
  sign_count INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL,
  backed_up INTEGER NOT NULL DEFAULT 0,   -- the BS flag: synced to the person's cloud keychain
  created_at TEXT NOT NULL,
  last_used_at TEXT
);
```

A public key is not a secret, so nothing is sealed. Not in the export (a credential). Deleting the account deletes the rows. Challenges
live in memory for 5 minutes (at most 10,000 at once), like the rate limits: a restart only means asking again.

## 5. Routes

| Route | Who | Does |
|---|---|---|
| `GET /api/me/passkeys` | user | `{available, passkeys: [{id, name, created_at, last_used_at, backed_up}], max: 10}` |
| `POST /api/me/passkeys/options` | user *(re-auth)* | Creation options for `navigator.credentials.create`: a challenge, this RP, the person's user handle, the supported algorithms, `residentKey: "required"`, `userVerification: "required"`, `attestation: "none"`, and the person's existing passkeys as `excludeCredentials`. `409` at 10. |
| `POST /api/me/passkeys` | user *(re-auth)* | `{challenge_id, name?, credential}` → `201` the new item. `400` when a check fails (in plain words), `409` at 10 or already registered. |
| `PATCH /api/me/passkeys/{id}` | user | `{name}` → the item. `404` if not yours. |
| `DELETE /api/me/passkeys/{id}` | user *(re-auth)* | `204`. `404` if not yours. |
| `POST /api/auth/passkey/options` | public | Request options for `navigator.credentials.get`: a challenge, this RP ID, `userVerification: "required"`, no `allowCredentials` (the device offers its passkeys for this server). |
| `POST /api/auth/passkey` | public | `{challenge_id, credential}` → `{user, notice}` and a session, as a password sign-in. A failed check is the generic `401 "That passkey did not work. Try again, or sign in with your password."` and counts against the address like a wrong password. |
| `DELETE /api/admin/users/{id}/passkeys` | admin *(re-auth)* | `{removed: n}`. |

The admin's people list gains `passkeys: n`. Audit: `passkey.added`, `passkey.removed` (`via` self, admin or cli; `count`),
`login.succeeded` and `login.failed` with `via: "passkey"`, `passkey.counter_went_back`. All are in the person's own activity. Proxy
and `none` modes: every route answers `404`.

A passkey sign-in is not asked for the two-step code: the device already checked a fingerprint, face or PIN. "Admins must use two-step
sign-in" (note 17 §10) still asks for the code setup, because the password still opens the account without a passkey.

## 6. The screens

* Sign-in: **Sign in with a passkey** under the password form, shown when the browser supports passkeys and the page is secure.
* Settings → Account → **Passkeys**: the list (name, added, last used, "synced" when backed up), **Add a passkey**, **Rename**, **Remove**.
* Server administration → People: "Passkeys: n" and **Remove passkeys**.
* The demo says it has no passkeys.

## 7. Tests

The W3C vectors through registration and sign-in (and the refused ones: cross-origin, top origin, no user verification); a software
authenticator in the tests (P-256 and Ed25519 keys from `cryptography`, CBOR written by the test) for every check of §3 one at a time;
the routes with re-auth, not-yours `404`, the limit of 10, the counter, a disabled account, the throttle, proxy and none mode; the
migration; Chromium with a virtual authenticator (`WebAuthn.addVirtualAuthenticator`) adding a passkey and signing in with it.

## 8. Risks

* A hand-written verifier: kept to the RP steps of the spec, tested against the spec's own vectors and a browser, no parsing of
  attestation certificates.
* A synced passkey (iCloud Keychain, Google Password Manager) is as safe as that cloud account. That is the person's choice; the list
  says "synced".

## 9. Choices taken (the owner can change any of them)

1. Built on `cryptography`, no `webauthn` package.
2. Passkeys are an extra way in; the password stays.
3. A passkey sign-in skips the two-step code (user verification is required).
4. At most 10 passkeys a person.
5. Attestation is not checked.

## 10. Later

* Passkeys for re-authentication, so a person who signs in with one never types the password.
* Passkeys in the username field's autofill ("conditional UI").
* Accounts with passkeys only; then "Admins must use two-step sign-in" could accept a passkey.
