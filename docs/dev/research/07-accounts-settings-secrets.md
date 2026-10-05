# 07 · Accounts, settings and secrets (multi-user)

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. |
| Date researched | 2026-10-05 |
| Scope | Turning the single-user app into a small multi-user, self-hosted app: authentication (local accounts, trusted reverse-proxy headers, OIDC later), first-run admin setup, invites, roles, per-user data scoping and the migration of existing data, the settings model (instance vs user, precedence, locks), admin-shared vs user-private API keys with quotas, encrypting secrets at rest, the audit log, data export, account deletion and backups |
| Out of scope | Container hardening, CSP and proxy-header handling (note [01](01-rootless-and-security.md)), the PWA and offline queue (note [02](02-ios-pwa.md)), barcode sources (note [03](03-barcode-and-photo.md)), AI provider behaviour (note [04](04-optional-ai.md)), target maths (note [05](05-personalized-targets.md)), meal guidance (note [06](06-meal-guidance.md)). This note defines the account, settings and secret plumbing those notes plug into. |
| Supersedes | Note 01 §5.1: `argon2-cffi` is **not** needed (`cryptography` already does Argon2id). Note 01 §5.5: `SECRET_KEY` does **not** sign sessions (sessions are opaque server-side tokens); it only encrypts stored secrets. Note 04 R4 "Fernet via `SECRET_KEY`" stays, using the shared helper defined here (§4.12). |
| Re-verify | Library versions every release; NIST SP 800-63B and the OWASP cheat sheets yearly. See [§7](#7-how-to-re-verify). |

Versions current on 2026-10-05 (PyPI JSON, upload dates in brackets): **cryptography 50.0.2**
[2026-09-30] (Apache-2.0 OR BSD-3-Clause; wheels bundle **OpenSSL 4.0.3**), **FastAPI 0.142.2**
[2026-09-30] (MIT), **Starlette 1.7.0** [2026-09-23] (BSD-3-Clause), uvicorn 0.54.0, pydantic 2.13.5,
httpx 0.28.1, cffi 2.1.1 (MIT-0), pycparser 3.0. Considered and **not** chosen: argon2-cffi 25.1.0
[2025-06-03] with argon2-cffi-bindings 26.1.0, pwdlib 0.3.1, fastapi-users 15.0.5 (maintenance mode),
passlib 1.7.4 [2020-10-08], bcrypt 5.0.0, itsdangerous 2.2.0, slowapi 0.1.10, limits 5.8.0. For
v0.4: Authlib 1.8.0 (BSD-3-Clause), joserfc 1.7.5 (BSD-3-Clause), webauthn 3.0.1 (BSD-3-Clause).

---

## 0. Decisions at a glance

1. **Built-in local accounts are the default** (`AUTH_MODE=local`): username + password, an opaque
   session token in an `HttpOnly; SameSite=Lax` cookie (`__Host-` and `Secure` over HTTPS), stored
   server-side as a SHA-256 hash. **Trusted reverse-proxy header auth** (`AUTH_MODE=proxy`) for
   Authelia, Authentik or `tailscale serve`. **OIDC and passkeys in v0.4.** HTTP Basic
   (`APP_PASSWORD`) is retired; `AUTH_MODE=none` keeps a no-login single-user mode for LAN setups
   that opt in explicitly.
2. **One new runtime dependency: `cryptography==50.0.2`.** It does both jobs: Argon2id password
   hashes (PHC strings, `derive_phc_encoded`, since 45.0.0) and Fernet encryption of stored API keys.
   Measured: Argon2id at OWASP's m=19 MiB, t=2, p=1 takes **26 ms** per hash and releases the GIL.
3. **Password policy per NIST SP 800-63B-4 §3.1.1.2**: at least 15 characters (password is the
   only factor), up to 128 allowed (NIST: at least 64), NFC-normalised, no composition rules, no expiry, a
   blocklist, paste and password managers allowed, a show-password toggle.
4. **CSRF**: `SameSite=Lax` + the `Sec-Fetch-Site`/`Origin` check from note 01 + a required
   `X-Requested-With: kidney-health` header on every unsafe `/api` request. No CORS, ever.
5. **Throttling**: progressive per-username delays (5 free failures, then 30 s doubling, capped at
   15 min), per-IP blocks, a 2-slot hashing semaphore, a dummy hash for unknown users, and the NIST
   hard stop at 100 consecutive failures.
6. **First run**: a one-time **setup code printed to the logs** (or `ADMIN_PASSWORD_FILE` for
   GitOps, or `python -m app.admin create-admin`). **Invite links** by default; open registration
   is opt-in.
7. **Roles**: `admin` and `user`. Admin ≠ data access: there is no UI to read another person's log,
   and no impersonation.
8. **Every personal table gets `user_id`** through `ALTER TABLE … ADD COLUMN` (nullable, because
   SQLite forbids a non-NULL default on an added `REFERENCES` column), is back-filled to user 1
   (the first admin), and is guarded by `BEFORE INSERT/UPDATE` triggers. Prototyped and passing.
9. **Settings**: a code registry of keys; precedence **env (locked) > user value (where allowed) >
   instance value > default**; two tables, `instance_settings` and `user_settings`.
10. **Secrets**: write-only API (`{"set": true, "last4": "…"}`), Fernet under HKDF-derived keys from
    `SECRET_KEY`, the owner and purpose sealed inside the ciphertext, rotation with `MultiFernet`.
    Credential resolution: **own key → shared key (if the admin allows it and the daily quota
    remains) → none**. A failing own key never falls back to the shared one.
11. **Audit log** of admin and security events (append-only trigger, no secret values, 365-day
    retention). **Export** (`.zip` with JSON + CSV) and **account deletion** with re-authentication.
    An automatic **pre-migration backup** before schema v3.

---

## 1. Context

### 1.1 The ask

From the owner's request:

> "a nice settings menu would be ideal, if some settings can be made universal like the ability for
> admin share an open ai key or the usda api key and the option for the user to set these private
> keys in their own settings"

> "lets think about this in terms of security … this project will likely eventually be open to the
> public to hopefully use and improve so keep that in mind and make sure everything is documented"

So v0.3 needs: accounts, an admin, a settings menu, keys the admin shares and keys each user keeps
private, and a design that a stranger running it on the internet cannot easily get wrong.

### 1.2 What exists today (v0.2), read from the repository

| Area | Today (file) | Gap for multi-user |
|---|---|---|
| Auth | `BasicAuthMiddleware` in `app/main.py`: one shared `APP_PASSWORD`, any username, constant-time compare, `/healthz` exempt | No identities, no logout, no throttling, credentials on every request, a poor fit for an installed iOS app (note 02 F12) |
| Profile | `profile` table with `id INTEGER PRIMARY KEY CHECK (id = 1)` (`app/db.py`) | The `CHECK` cannot be dropped with `ALTER TABLE`; one row only |
| Foods | `foods` has no owner; `custom` and `usda` rows are global; `PUT` is allowed on `usda` rows | One user's custom food would be visible to and editable by everyone |
| Log, saved meals | `log_entries`, `meal_templates` have no user column | Everything is one person's |
| Settings | Env only: `DATA_DIR`, `USDA_API_KEY`, `APP_PASSWORD`, `FOODS_JSON` (`app/config.py`) | Nothing an admin or user can change at runtime; no per-user keys |
| Migrations | `meta.schema_version` + ordered `ADD COLUMN` steps (`app/db.py`); "never drop or rename columns" (ARCHITECTURE.md) | Schema v3 must follow the same rule |
| Frontend | One `request()` wrapper in `app/static/app.js` using `fetch()` with the default mode and `credentials: 'same-origin'` | The single place to add the CSRF header and 401/re-auth handling |
| Process model | One uvicorn process (note 01 `CMD`, no `--workers`) and one replica (SQLite) | In-memory rate limiters are sound; document "do not add workers" |

### 1.3 What sibling notes require from this one

* **01 (security)**: asset A4 (credentials, sessions, `SECRET_KEY`), threat rows 10 (CSRF),
  13 (another user reads data or keys), 16 (keys leak), 18 (stolen phone), 19 (backups). `*_FILE`
  secrets; `TRUSTED_PROXIES` and `TRUSTED_PROXY_USER_HEADER` honoured only from trusted peers;
  `ALLOW_INSECURE_HTTP` true in single-user mode and false in multi-user mode; `app/admin.py` CLI.
* **02 (PWA)**: cookie sessions with an in-app login page; on logout send
  `Clear-Site-Data: "cache", "storage"` after warning about unsynced entries; `log_entries.client_id`
  unique per `(user_id, client_id)`.
* **03 (barcode)**: `barcode_cache` instance-wide; `off` food rows shared but visible to a user only
  after that user scanned or logged them; a user-private USDA key overrides the shared one.
* **04 (AI)**: `ai_providers` (shared or user-owned, `api_key_enc`), `ai_usage`, `ai_audit`;
  `AI_ALLOW_USER_KEYS`, `AI_SHARED_DAILY_LIMIT`; never fall back from a failing private provider to
  the shared one; `GET/PUT /api/me/ai` rendered by the settings UI.
* **05 (targets)**: new per-user profile fields (`birth_month`, `sex`, `activity`, …) and a
  `lab_results` table keyed by `user_id`.
* **06 (guidance)**: per-user guidance preferences (an object) and admin `GUIDANCE_ENABLED`.

---

## 2. Findings

### F1. NIST SP 800-63B-4 password rules (final, published 2025-07-31 / announced 2025-08-01)

Source: [SP 800-63B-4 §3.1.1.2](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/),
[CSRC announcement](https://csrc.nist.gov/pubs/sp/800/63/4/final). Quoted requirements:

* "Verifiers and CSPs **SHALL** require passwords that are used as a single-factor authentication
  mechanism to be a minimum of **15** characters in length." With MFA, "a minimum of eight".
* "**SHOULD** permit a maximum password length of at least 64 characters."
* "**SHOULD** accept all printing ASCII characters and the space character" and "**SHOULD** accept
  Unicode characters … Each Unicode code point **SHALL** be counted as a single character."
* "the verifier **SHOULD** apply the normalization process … Normalization Form Canonical
  Composition (NFC)."
* "**SHALL NOT** impose other composition rules."
* "**SHALL** compare the prospective secret against a blocklist that contains known commonly used,
  expected, or compromised passwords. The entire password **SHALL** be subject to comparison, not
  substrings." The blocklist "**SHOULD** be of sufficient size to prevent subscribers from choosing
  passwords that attackers are likely to guess before reaching the attempt limit."
* "**SHALL NOT** require subscribers to change passwords periodically. However, verifiers **SHALL**
  force a change if there is evidence that the authenticator has been compromised."
* No hints available to an unauthenticated claimant; no knowledge-based questions.
* "**SHALL** verify the entire submitted password (e.g., not truncate it)."
* "**SHALL** allow the use of password managers and autofill"; "**SHOULD** permit … paste"; "**SHOULD**
  offer an option to display the password".
* "Passwords **SHALL** be salted and hashed using a suitable password hashing scheme"; salt ≥ 32
  bits; "**SHOULD** perform an additional iteration of a keyed hashing … using a secret key known only
  to the verifier" (a pepper).
* §3.2.2 rate limiting: "**SHALL** limit consecutive failed authentication attempts … to no more than
  **100** by disabling that authenticator", which must then be re-bound. Suggested mitigations: bot
  challenges, increasing waits, risk-based checks. "When the subscriber successfully authenticates,
  the verifier **SHOULD** disregard any previous failed attempts."

Sessions ([§5.1](https://pages.nist.gov/800-63-4/sp800-63b/session/),
[AAL §2](https://pages.nist.gov/800-63-4/sp800-63b/aal/)): session secrets ≥ 64 bits from an
approved RBG; cookies "**SHALL** be tagged to be accessible only on secure (i.e., HTTPS) sessions",
"**SHOULD** be … HttpOnly", "**SHOULD** have the `__Host-` prefix and set `Path=/`", "**SHOULD** set
`SameSite=Lax` or `SameSite=Strict`", not in Local Storage; erased on logout. Password-only login is
**AAL1**: "a definite reauthentication overall timeout **SHALL** be established, which **SHOULD** be
no more than **30 days** at AAL1. An inactivity timeout **MAY** be applied." (AAL2: 24 h / 1 h idle.)

### F2. OWASP guidance

* [Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html):
  Argon2id first, with equivalent rows m=47104 t=1, **m=19456 t=2**, m=12288 t=3, m=9216 t=4,
  m=7168 t=5 (all p=1). scrypt second: N=2^17 r=8 p=1 (128 MiB), N=2^16 p=2, N=2^15 p=3,
  **N=2^14 r=8 p=5 (16 MiB)**, N=2^13 p=10. bcrypt: work factor ≥ 10, 72-byte input limit. Upgrade
  work factors at the next successful login.
* [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html):
  ≥ 64 bits of entropy; `Secure`, `HttpOnly`, `SameSite`, `__Host-`; renew the ID after login and
  privilege change; server-side invalidation on logout; an "identifier and secret verifier split",
  storing only a SHA-256 of the verifier; `Clear-Site-Data` on logout; idle timeouts of "2–5 minutes
  for high-value" and "15–30 minutes for low-risk" applications.
* [Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html):
  generic errors ("Login failed; Invalid user ID or password"), equal timing for unknown users,
  lockout counters "associated with the account itself" rather than the IP, exponential back-off,
  current password required to change it, re-authentication for sensitive features.
* [CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html):
  Fetch Metadata is a lightweight, reliable way to block cross-site requests, and "a fallback to
  standard origin verification headers is a mandatory requirement"; custom request headers rely on
  CORS preflight and need no server state; `SameSite` is defence in depth only; keep GET free of
  state changes; login CSRF exists.

### F3. Password hashing measured (this research container)

Intel Xeon 2.1 GHz, x86_64, Python 3.11.15, cryptography 50.0.2 wheel (OpenSSL 4.0.3), argon2-cffi
25.1.0. Script: `scratchpad/research/bench.py`.

| Scheme and parameters | Time per hash | Memory | Notes |
|---|---|---|---|
| **cryptography `Argon2id`, m=19456 t=2 p=1** | **26 ms** (verify 23 ms) | 19 MiB | PHC string; releases the GIL (a spinning thread kept running) |
| cryptography `Argon2id`, m=47104 t=1 p=1 | 50 ms | 46 MiB | |
| cryptography `Argon2id`, m=65536 t=3 p=1 | 157 ms | 64 MiB | |
| argon2-cffi, same three settings | 21 / 47 / 147 ms | same | Its default `PasswordHasher()` is RFC 9106 low-memory: t=3, m=65536, p=4 |
| stdlib `hashlib.scrypt` N=2^14 r=8 p=5 | 183 ms | 16 MiB | Own encoding needed |
| stdlib `hashlib.scrypt` N=2^17 r=8 p=1 | 397 ms | 128 MiB | **Fails with the default `maxmem`** ("memory limit exceeded"); needs `maxmem≥129 MiB` |

Interoperability: hashes from `Argon2id.derive_phc_encoded()` verify with argon2-cffi and the
reverse also holds (`$argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>`). `verify_phc_encoded()` raises
`InvalidKey` for a wrong password **and** for a malformed string. `derive_phc_encoded` and
`verify_phc_encoded` were added in cryptography 45.0.0, the class in 44.0.0; it raises
`UnsupportedAlgorithm` when the linked OpenSSL lacks Argon2 (OpenSSL < 3.2), which only happens when
cryptography is built from source against an old system OpenSSL
([docs](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/)).

Wheel coverage: cryptography 50.0.2 ships abi3 wheels for manylinux x86_64, aarch64, armv7l and
ppc64le and musllinux x86_64/aarch64. argon2-cffi-bindings 26.1.0 has **no armv7 wheel**. The image
is amd64 + arm64 (`.github/workflows/ci.yml`), so both would work there, but choosing cryptography
alone removes two packages and one platform gap.

Library landscape:
* **FastAPI's own tutorial now uses `pwdlib[argon2]`** and verifies against a dummy hash for unknown
  users "preventing timing attacks that could be used to enumerate existing usernames"
  ([tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)). pwdlib is a thin
  wrapper (Beta) over argon2-cffi.
* **fastapi-users** README: "This project is now in maintenance mode … no new features." Its DB
  adapters are SQLAlchemy and Beanie; this project uses raw `sqlite3`.
* **passlib**'s last release is 1.7.4 from October 2020.

### F4. CSRF for a same-origin JSON API

* Filippo Valsorda's algorithm (2025-08-13, implemented as Go 1.25 `CrossOriginProtection`,
  [article](https://words.filippo.io/csrf/)): allow GET/HEAD/OPTIONS; allow trusted origins; if
  `Sec-Fetch-Site` is present allow only `same-origin` or `none`; if neither header is present, allow
  (pre-2020 browsers); otherwise compare `Origin` with `Host`. **`Sec-Fetch-Site` is sent only to
  trustworthy origins (HTTPS or localhost)**, so a plain `http://192.168.1.10:8000` gets no Fetch
  Metadata and relies on the `Origin` comparison.
* Browser support ([MDN BCD](https://github.com/mdn/browser-compat-data)): `Sec-Fetch-Site` Chrome
  76, Firefox 90, Safari/iOS **16.4**.
* `Origin` on same-origin requests ([Fetch §3.2 "append a request `Origin` header"](https://fetch.spec.whatwg.org/#append-a-request-origin-header)):
  for a non-GET/HEAD request whose mode is **not** `cors`, a `no-referrer` policy turns the `Origin`
  into `null`. Note 01 sends `Referrer-Policy: no-referrer`. `fetch()` defaults to mode `cors`, so the
  app's `request()` wrapper sends the real origin. **Never set `mode: 'same-origin'` and never post
  HTML forms**, or the HTTP-LAN fallback would see `Origin: null` and refuse the request.
* **SameSite is "same-site", not "same-origin".** Homelabs often put many apps under one registrable
  domain (`grafana.home.example`, `kidney.home.example`). A compromised sibling app is same-site,
  so a `Lax` cookie is still sent on its POSTs. `Sec-Fetch-Site: same-site` (not `same-origin`) and
  the custom header catch it.
* Custom header: any header outside the CORS-safelisted set (`Accept`, `Accept-Language`,
  `Content-Language`, `Content-Type` with limited values) forces a preflight. The app has no
  `CORSMiddleware`, so the preflight fails and the real request is never sent.

### F5. Cookies and logout headers

* [MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie):
  `__Host-` requires `Secure`, a secure page, no `Domain`, `Path=/`. "Insecure sites (`http:`)
  cannot set cookies with the `Secure` attribute", except `localhost`. With `SameSite` unset some
  browsers use a permissive "Lax-by-default" that still sends cookies on POSTs within two minutes, so
  **always set it explicitly**. `Max-Age` wins over `Expires`. Newer `__Http-`/`__Host-Http-`
  prefixes exist but `__Host-` is enough.
* `Clear-Site-Data` (MDN BCD): Chrome 61, Firefox 63, **Safari/iOS 17**; secure contexts only;
  `"cache"` from Chrome 127.
* iOS Home Screen apps keep their own cookie jar (note 02 F12): people sign in once **inside** the
  installed app, and a 30-day absolute session means a monthly sign-in.

### F6. Trusted reverse-proxy header auth

* **Authelia** ([trusted header SSO](https://www.authelia.com/integration/trusted-header-sso/introduction/)):
  `Remote-User`, `Remote-Groups`, `Remote-Name`, `Remote-Email`. "your proxy must ensure only
  Authelia is setting these headers"; the app must trust them **only from the proxy's address**.
  Caddy: `forward_auth authelia:9091 { uri /api/authz/forward-auth; copy_headers Remote-User
  Remote-Groups Remote-Email Remote-Name }`; "only include the specific IP address ranges of the
  trusted proxies" ([Caddy guide](https://www.authelia.com/integration/proxies/caddy/)). Authelia
  points to OIDC as the more standard alternative.
* **authentik** ([proxy provider](https://docs.goauthentik.io/add-secure-apps/providers/proxy/)):
  `X-authentik-username`, `X-authentik-groups` (pipe-separated), `X-authentik-email`,
  `X-authentik-name`, `X-authentik-uid`.
* **tailscale serve** ([KB 1312](https://tailscale.com/kb/1312/serve)): `Tailscale-User-Login`,
  `Tailscale-User-Name`, `Tailscale-User-Profile-Pic`; not set for tagged devices or Funnel; serve
  **strips** client-supplied copies.
* The danger is entirely in the network path: if the app port is reachable by anything other than
  the proxy (note 01 threat row 7), a forged `Remote-User: admin` is a full takeover. Note 01's
  `PeerCaptureMiddleware` and `TRUSTED_PROXIES` are the control.

### F7. OIDC (for v0.4)

Authlib 1.8.0's Starlette client keeps `state`/`nonce` in `request.session`, which requires
Starlette's `SessionMiddleware` and therefore `itsdangerous`
([Authlib Starlette client](https://docs.authlib.org/en/v1.5.1/client/starlette.html)); it also pulls
joserfc and cryptography. The alternative is ~300 lines of Authorization Code + PKCE with `httpx`
and `joserfc` for ID-token validation, with state kept in a short-lived DB row. Self-hosted IdPs that
speak OIDC: Authelia, authentik, Keycloak, Kanidm, Pocket ID.

### F8. FastAPI and Starlette changes that affect this design

* **Starlette 1.0.0 (2026-03-22)** removed `on_startup`/`on_shutdown`, `on_event`,
  `@app.middleware()`, `@app.route()` and `@app.exception_handler()` from Starlette itself
  ([release notes](https://github.com/Kludex/starlette/blob/main/docs/release-notes.md)). The app
  already uses `lifespan` and `add_middleware`. **1.6.0** added `max_body_size` to `Starlette` and
  routes (an alternative to note 01's `BodyLimitMiddleware`). **1.7.0** fixed background tasks under
  `BaseHTTPMiddleware` and warns that `starlette.testclient` with `httpx` is deprecated in favour of
  `httpx2`.
* **FastAPI 0.121.0** added dependency scopes (`Depends(..., scope="request")` for `yield`
  dependencies). **0.122.0**: security classes return **401** (not 403) when credentials are
  missing. **0.137.0 (breaking)**: `router.routes` is now a **tree** of `_IncludedRouter` objects;
  "any logic that depended on iterating on `router.routes` directly would be affected". Verified: an
  `app.routes` walk finds no `APIRoute`s once routers are included, so an auth-coverage test must use
  `app.openapi()` plus real requests (§4.10). **0.142.0** made `opentelemetry-api` a hard dependency
  ([release notes](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/release-notes.md)).
* Verified with FastAPI 0.142.2: a router-level `dependencies=[Depends(current_user)]` plus an
  endpoint parameter `user: CurrentUser` resolves `current_user` **once per request** (dependency
  cache), and an unauthenticated POST with an invalid body returns **401, not 400**, because
  dependencies are solved before the body is validated.

### F9. Encrypting stored API keys

* What it protects: a leaked `kidney.db` or backup **without** the key. What it does not: an attacker
  who runs code in the container (note 01 accepted residual risk), or an admin.
* `cryptography` Fernet: AES-128-CBC + HMAC-SHA256, random IV, a timestamp, URL-safe tokens;
  `MultiFernet([new, old]).rotate(token)` re-encrypts under the first key. No associated data.
  `AESGCM`: AES-256-GCM AEAD with associated data, but nonce handling, the envelope format and
  rotation would be the project's own code. The standard library has **no** authenticated cipher.
* Prototype (`scratchpad/research/proto.py`): HKDF-SHA256 derives a Fernet key per `SECRET_KEY`
  line; a 64-byte secret encrypts and decrypts in ~19 µs; a sealed envelope is 164 bytes; after
  `rotate()` the old key alone fails and the new key alone succeeds.
* Ciphertext swapping: without associated data, someone with **write** access to the DB could copy
  the shared key's ciphertext into their own row. Sealing `{purpose, owner}` inside the plaintext and
  checking them on decrypt closes that at no cost (§4.12). (DB write access already allows worse,
  so this is hygiene, not a boundary.)

### F10. SQLite constraints for the migration

[ALTER TABLE](https://www.sqlite.org/lang_altertable.html): an added column may not be PRIMARY KEY or
UNIQUE; "If a NOT NULL constraint is specified, then the column must have a default value other than
NULL"; "**If foreign key constraints are enabled and a column with a REFERENCES clause is added, the
column must have a default value of NULL**" (`app/db.py` turns `foreign_keys` on for every
connection); an added CHECK is tested against existing rows. Other changes need the 12-step rebuild
(`foreign_keys=OFF`, new table, copy, drop, rename, `foreign_key_check`). Hence: a nullable
`user_id … REFERENCES users(id) ON DELETE CASCADE`, a back-fill, and triggers that reject NULL.

Prototype result (SQLite 3.45.1): migration with `foreign_keys=ON` succeeded, `foreign_key_check`
was empty, an insert without `user_id` was refused by the trigger, a second shared `usda` secret was
refused by a unique expression index, a `user`-scoped secret without owner was refused by a CHECK,
`UPDATE audit_log` was refused, and `DELETE FROM users WHERE id = 1` cascaded to that user's log
entries, custom foods and profile while user 2's entries survived. With `AUTOINCREMENT`, a deleted
user's id is **not reused**.

[PRAGMA secure_delete](https://www.sqlite.org/pragma.html#pragma_secure_delete): `ON` zeroes deleted
content; `FAST` zeroes it only when that costs no extra I/O, "purging all old content from b-tree
pages, but leaving forensic traces on freelist pages". `VACUUM` removes the rest.

### F11. Breached-password lists

* The UK NCSC top-100k list (from Have I Been Pwned, via [SecLists](https://github.com/danielmiessler/SecLists),
  MIT, `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`, 835 KB). Counted after NFC
  and casefold: **46,483** entries of ≥ 8 characters (148 KB gzipped), **9,126** of ≥ 10, **1,197**
  of ≥ 12, and only **329** of ≥ 15 (`1q2w3e4r5t6y7u8i9o0p`, `123456789123456789`, `qazwsxedcrfvtgb`…).
  With a 15-character minimum the list matters little; it matters if an admin lowers the minimum.
* [HIBP Pwned Passwords range API](https://haveibeenpwned.com/API/v3#PwnedPasswords):
  `GET https://api.pwnedpasswords.com/range/{first 5 SHA-1 hex}`, no key, no rate limit,
  `Add-Padding: true` returns 800–1,000 rows with padding rows at count 0, no licensing or
  attribution requirement. It is an outbound request, so it must be off by default (README promise).

### F12. Provider limits relevant to quotas

* api.data.gov (USDA FDC): **1,000 requests per hour per key**, across all api.data.gov APIs;
  `X-RateLimit-Limit` / `X-RateLimit-Remaining` on every response; `DEMO_KEY` 30/h and 50/day per
  IP ([manual](https://api.data.gov/docs/developer-manual/)). A shared key is shared by every user.
* Open Food Facts: no key, 15 product requests/min/IP (note 03). AI: tokens cost money (note 04).

### F13. Privacy law, briefly

GDPR does not apply to "a purely personal or household activity" (Art. 2(2)(c)), which covers a
family server. An instance offered to other people is different: health data is a special category
(Art. 9) and people have rights of access (Art. 15), erasure (Art. 17) and portability (Art. 20)
([Regulation (EU) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj)). Export and deletion are
cheap to build now and make the public project usable by small clinics or support groups later. This
note is not legal advice; `docs/privacy.md` should say so.

---

## 3. Options compared

### 3.1 How people sign in

| Option | LAN / offline | Internet exposure | Homelab effort | Extra deps | Multi-user | Verdict |
|---|---|---|---|---|---|---|
| HTTP Basic, one shared `APP_PASSWORD` (today) | yes | weak: no throttling, no logout, credentials sent on every request | trivial | none | no | **Retire** (one-time import as the admin password) |
| **Built-in local accounts, cookie sessions** | yes | good with HTTPS, throttling, NIST policy | low | `cryptography` | yes | **Default** (`AUTH_MODE=local`) |
| **Trusted proxy header** (Authelia, authentik, tailscale serve) | needs the proxy | as strong as the IdP (MFA, passkeys) if `TRUSTED_PROXIES` is right; a takeover if wrong | medium | none | yes | **Supported** (`AUTH_MODE=proxy`) |
| OIDC (Authelia, authentik, Keycloak, Kanidm, Pocket ID) | needs the IdP | strong | medium–high | Authlib + joserfc + itsdangerous, or own code | yes | **v0.4** |
| Passkeys (WebAuthn) built in | needs HTTPS | strongest, phishing-resistant | low for users | webauthn 3.0.1 | yes | **v0.4** (then an 8-character minimum is allowed: MFA) |
| No auth | yes | none | none | none | no | Only as explicit `AUTH_MODE=none` |

### 3.2 Password hashing

| Option | New packages | OWASP rank | Measured | Verdict |
|---|---|---|---|---|
| **`cryptography` Argon2id, m=19456 t=2 p=1** | none (cryptography is needed for secrets anyway) | 1st | 26 ms, 19 MiB | **Choose** |
| argon2-cffi 25.1.0 | argon2-cffi, argon2-cffi-bindings (no armv7 wheel) | 1st | 21 ms | Good, but redundant |
| pwdlib 0.3.1 `[argon2]` | pwdlib + the two above | 1st | same | Wrapper; Beta |
| stdlib `hashlib.scrypt` N=2^14 r=8 p=5 | none | 2nd | 183 ms, 16 MiB | **Fallback only** (`PASSWORD_HASH=scrypt`) |
| bcrypt 5.0.0 | bcrypt | legacy | – | 72-byte limit |
| passlib 1.7.4 | passlib | – | – | Unmaintained since 2020 |

Pepper (NIST "SHOULD"): **not in v0.3.** By default `SECRET_KEY` sits in `/data/secret.key` on the
same volume as the database, so a pepper protects little, while losing the key would lock **every**
account out. Without a pepper, losing `SECRET_KEY` only costs re-entering API keys. Revisit with an
opt-in `PASSWORD_PEPPER_FILE` once the docs push operators to keep keys outside the data volume.

### 3.3 Session mechanism

| Option | Revocation | Needs a key | Notes | Verdict |
|---|---|---|---|---|
| **Opaque token, server-side row, SHA-256 of the verifier stored** | instant, per device | no | Sessions list, "sign out other devices", one indexed lookup per request | **Choose** |
| Starlette `SessionMiddleware` (itsdangerous signed cookie) | none per session | yes | Contents readable (signed, not encrypted); a leaked key forges any session | Reject |
| JWT access + refresh | needs a denylist anyway | yes | Built for third-party APIs; complexity without benefit | Reject |

### 3.4 CSRF defence

| Layer | Covers | Gap | Verdict |
|---|---|---|---|
| `SameSite=Lax` cookie | cross-site POSTs in modern browsers | same-site sibling apps; legacy browsers | **Yes**, defence in depth |
| `Sec-Fetch-Site` + `Origin` fallback (note 01 `CsrfMiddleware`) | everything on HTTPS; `Origin` on HTTP | `Origin: null` if a form or `mode:'same-origin'` is used | **Yes** |
| Required custom header `X-Requested-With: kidney-health` | forces a preflight that fails (no CORS); works on plain HTTP; blocks login CSRF from forms | needs every client call to add it (one wrapper) | **Yes** |
| Synchronizer token | everything | state and plumbing in vanilla JS | Not needed |
| Double-submit cookie | | JS-readable cookie, subdomain cookie tossing | Reject |

### 3.5 Storing API keys

| Option | Deps | DB/backup leak exposes keys? | Rotation | Verdict |
|---|---|---|---|---|
| Plaintext in SQLite (common in homelab apps) | none | yes | n/a | Reject for multi-user |
| Plaintext in a separate `/data/secrets.json` | none | if the volume leaks | manual | Weak |
| Home-made stdlib cipher (HMAC keystream + tag) | none | no, if correct | own code | Reject: unreviewed crypto |
| **Fernet (`cryptography`), HKDF-derived keys, context sealed inside** | cryptography | no | `MultiFernet.rotate` | **Choose** |
| AES-256-GCM with associated data | cryptography | no | own envelope code | Acceptable; more code for no real gain here |
| External KMS / Vault | external | no | yes | Out of scope for homelabs |

### 3.6 Where to enforce identity in FastAPI

| Pattern | Pros | Cons | Verdict |
|---|---|---|---|
| Pure ASGI middleware enforcing auth | covers static files too | path allow-lists, no DI, invisible to OpenAPI, harder to test per route | Use middleware only for transport concerns (note 01: peer, proxy headers, body size, CSRF, headers) |
| `BaseHTTPMiddleware` | simple API | history of contextvar/streaming/background-task issues; overhead | Avoid |
| Starlette `AuthenticationMiddleware` + `@requires` | built in | not idiomatic with FastAPI dependencies | No |
| **Router-level `dependencies=[Depends(current_user)]` + typed `CurrentUser` / `AdminUser` parameters** | explicit, cached per request, overridable in tests, works with sync `sqlite3` | must not forget a router | **Choose**, plus a behavioural coverage test |
| Per-endpoint dependency only | | easy to forget | No |

### 3.7 Scoping data per user

| Option | Fits the migration rule | Isolation | Verdict |
|---|---|---|---|
| **`ADD COLUMN user_id` + back-fill + triggers + composite indexes** | yes ("never drop or rename") | app-level, tested | **Choose** |
| 12-step table rebuild for `NOT NULL` | breaks the ADD-COLUMN-only contract | same | No |
| One SQLite file per user | n/a | strongest; delete = remove file | N× migrations, shared foods duplicated, admin features harder. Revisit for v1.0 |
| `TEMP VIEW`s per connection filtered by user | yes | defence in depth | Complexity; no |

### 3.8 Creating the first admin

| Option | Risk | Verdict |
|---|---|---|
| First visitor becomes admin | a race on any exposed instance | Reject |
| **One-time setup code in the logs** (like Jenkins' `initialAdminPassword`) | needs `podman logs` / `kubectl logs`; logs may be shipped | **Default** (60-minute TTL, regenerated per start) |
| **`ADMIN_USERNAME` + `ADMIN_PASSWORD_FILE`** | file secret | **Supported** (GitOps, Kubernetes) |
| **`python -m app.admin create-admin`** (password on stdin) | exec access = owner already | **Supported** |

### 3.9 Registration

| Mode | Use | Verdict |
|---|---|---|
| **`invite`** | admin creates a single-use link (7 days) | **Default** |
| `closed` | admin creates accounts; people set their password through a one-time link | Supported |
| `open` | anyone who reaches the page can register | Opt-in; HTTPS required; 3 registrations per IP per hour |

### 3.10 Settings storage

| Option | Verdict |
|---|---|
| Env only (today) | Keeps working as a **lock** for GitOps; not enough alone |
| **Code registry + `instance_settings` / `user_settings` key-value rows + env locks** | **Choose** |
| One JSON blob per user | Only for object-valued keys (`guidance`, `ai`) inside the key-value table |

---

## 4. Recommendation

### 4.1 In one paragraph

Accounts live in SQLite. A person signs in with a username and a ≥ 15-character password hashed with
Argon2id (`cryptography`), gets an opaque 256-bit session token in an `HttpOnly; SameSite=Lax` cookie
that is `__Host-` and `Secure` over HTTPS, and keeps it for up to 30 days (14 days idle). Sensitive
actions need the password again within 10 minutes. Every `/api` route except a short public list
requires a signed-in user through router-level FastAPI dependencies; admin routes require
`role = 'admin'`. Every personal row carries `user_id`, every query filters by it, and tests prove
that two users never see each other's rows. Settings come from a registry with env locks; API keys
are write-only, encrypted with Fernet under keys derived from `SECRET_KEY`, and resolved per request
as own → shared (if allowed and within quota) → none. Admin and security events go to an append-only
audit log. Each person can export everything and delete their account. Proxy-header auth is an
alternative mode; OIDC and passkeys follow in v0.4.

### 4.2 Dependencies

`requirements.in` (note 01 locks it with hashes):

```
cryptography==50.0.2      # Apache-2.0 OR BSD-3-Clause. Argon2id passwords + Fernet secrets. Pulls cffi 2.1.1 (MIT-0), pycparser 3.0 (BSD-3-Clause)
```

Nothing else for this note. Explicitly **not** added: argon2-cffi, pwdlib, passlib, bcrypt,
fastapi-users, itsdangerous, slowapi/limits, PyJWT, Authlib (v0.4 decision). Everything else uses the
standard library: `secrets`, `hashlib`, `hmac`, `unicodedata`, `zipfile`, `csv`, `json`, `gzip`,
`ipaddress`, `threading`.

### 4.3 Configuration keys (environment)

Every secret also accepts `<KEY>_FILE` (note 01 rule: setting both is a startup error).

| Key | Default | Purpose |
|---|---|---|
| `AUTH_MODE` | `local` | `local`: accounts with passwords. `proxy`: identity from `TRUSTED_PROXY_USER_HEADER` (local passwords only via the break-glass CLI). `none`: no login, everything is user 1 (admin); a red banner says so; invites disabled. |
| `ADMIN_USERNAME` | `admin` | Username for an admin created from env or from a legacy `APP_PASSWORD`. |
| `ADMIN_PASSWORD[_FILE]` | unset | **First run only**: creates the admin without the setup code. Ignored with a warning once an admin exists. |
| `APP_PASSWORD[_FILE]` | unset | **Deprecated.** On the first v0.3 start with no admin, becomes user 1's password (`must_change_password=1` if it fails the policy). HTTP Basic is no longer accepted. |
| `SETUP_CODE_TTL_MINUTES` | `60` | Lifetime of the logged setup code. |
| `SESSION_IDLE_DAYS` | `14` | 1–30. |
| `SESSION_MAX_DAYS` | `30` | 1–30 (NIST AAL1 ≤ 30 days). |
| `REAUTH_MINUTES` | `10` | Window after a password re-entry in which sensitive actions are allowed. |
| `PASSWORD_MIN_LENGTH` | `15` | 8–64. Below 15 logs "below the NIST SP 800-63B-4 single-factor minimum". |
| `PASSWORD_BREACH_CHECK` | `false` | `true` adds the HIBP k-anonymity check (egress to `api.pwnedpasswords.com`; fail-open on network errors). |
| `PASSWORD_HASH` | `argon2id` | `scrypt` only for builds where Argon2id is unavailable (startup self-test says so). |
| `LOGIN_IP_MAX_FAILURES` | `20` | Failed logins per client IP per 10 minutes before a 10-minute block. |
| `TRUSTED_PROXIES`, `TRUSTED_PROXY_USER_HEADER` | note 01 | Unchanged. `AUTH_MODE=proxy` requires the header and **refuses to start** if `TRUSTED_PROXIES` contains `0.0.0.0/0` or `::/0`. |
| `TRUSTED_PROXY_GROUPS_HEADER` | unset | `Remote-Groups`, `X-authentik-groups`; split on a comma or a pipe character. |
| `TRUSTED_PROXY_NAME_HEADER` | unset | Display name (`Remote-Name`, `X-authentik-name`, `Tailscale-User-Name`). |
| `TRUSTED_PROXY_ADMIN_GROUP` | unset | Members are admins; role synced on each request (changes audited). |
| `PROXY_AUTO_CREATE_USERS` | `false` | Create an account on first sight of a new proxy identity; otherwise the admin pre-creates it. |
| `PROXY_LOGOUT_URL` | unset | Where "Sign out" goes in proxy mode (for example `https://auth.example.com/logout`). |
| `SECRET_KEY[_FILE]` | auto `/data/secret.key` (0600) | Note 01. **One key per line; the first is current**, the others are only for decryption during rotation. Each line ≥ 32 characters. |
| `ALLOW_INSECURE_HTTP` | note 01 | True while only one active account exists; false as soon as there are two. When false, login, setup and registration over non-loopback plain HTTP answer 400 "HTTPS required" with a link to `docs/https.md`. |

Any **instance setting** (§4.11) can also be locked from env (`REGISTRATION_MODE`, `OFF_ENABLED`,
`AI_ENABLED`, `USDA_SHARED_DAILY_LIMIT`, `AUDIT_RETENTION_DAYS`, …).

### 4.4 Data model: schema v3

New migration step `(3, "v0.3 accounts, per-user data, settings, secrets, audit", _migrate_v3)` in
`app/db.py`. Before it runs, `init_db()` writes **`/data/kidney.db.pre-v3.bak`** with the SQLite
backup API (once; skipped if the file exists) and logs its path. The step runs in one transaction,
then `PRAGMA foreign_key_check` must return no rows. Fresh databases get the new tables and the
nullable `user_id`/`owner_user_id` columns inline from `SCHEMA`, and then run `_migrate_v3` like
every other database (their stored version starts at 0), which adds the indexes, triggers and user 1.
So the two paths never diverge.

```sql
-- Identities ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,             -- AUTOINCREMENT: ids of deleted users are never reused
  username TEXT NOT NULL,                           -- as typed (display)
  username_norm TEXT NOT NULL UNIQUE,               -- NFKC + casefold; local accounts: [a-z0-9._@+-]{3,64}
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending_setup','active','disabled','locked')),
  auth_source TEXT NOT NULL DEFAULT 'local' CHECK (auth_source IN ('local','proxy','oidc')),
  external_subject TEXT,                            -- proxy username or OIDC sub
  password_hash TEXT,                               -- PHC string; NULL = no local password
  password_changed_at TEXT,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  can_use_shared INTEGER NOT NULL DEFAULT 1,        -- admin switch: may this person use shared keys?
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS users_external ON users(auth_source, external_subject)
  WHERE external_subject IS NOT NULL;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,                              -- public selector: 16 random bytes, hex
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  verifier_hash BLOB NOT NULL,                      -- SHA-256 of the 32-byte verifier
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  reauth_at TEXT,                                   -- last password re-entry ("sudo" window)
  user_agent TEXT,                                  -- first 200 chars, for the device list
  ip_prefix TEXT                                    -- IPv4 /24 or IPv6 /48, for the device list
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS auth_tokens (           -- setup codes, invites, password-reset links
  id TEXT PRIMARY KEY,
  purpose TEXT NOT NULL CHECK (purpose IN ('setup','invite','reset')),
  verifier_hash BLOB NOT NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- reset: whose; invite: NULL
  role TEXT CHECK (role IN ('admin','user')),                 -- invite: role to grant
  note TEXT,                                                  -- invite: "for Mum"
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT
);

CREATE TABLE IF NOT EXISTS login_failures (        -- keyed by name, whether or not the account exists
  -- HMAC-SHA256(HKDF(SECRET_KEY, "kidney-health/v1/login-failures"), username_norm), never the
  -- typed name: people type passwords into the username field, and this table is in every backup.
  -- (Corrected in the security review: a plaintext key contradicted §4.5.)
  name_mac BLOB PRIMARY KEY,
  consecutive INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT, last_failure_at TEXT NOT NULL
) WITHOUT ROWID;

-- Settings and secrets -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS instance_settings (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL, updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL, value_json TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS secrets (                -- non-AI provider credentials (AI keys: ai_providers, note 04)
  id INTEGER PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('shared','user')),
  owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,                           -- registry slug: 'usda', later others
  ciphertext BLOB NOT NULL,                         -- Fernet token of the sealed envelope (§4.12)
  key_id TEXT NOT NULL,                             -- which SECRET_KEY line encrypted it
  hints_json TEXT NOT NULL DEFAULT '{}',            -- {"api_key": "9xQz"}: last 4 chars per field, only if field ≥ 20 chars
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  CHECK ((scope = 'shared') = (owner_user_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS secrets_one_per_owner ON secrets(provider, ifnull(owner_user_id, 0));
CREATE TABLE IF NOT EXISTS usage_daily (            -- non-AI provider calls (AI: ai_usage, note 04)
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL, key_scope TEXT NOT NULL CHECK (key_scope IN ('shared','own')),
  day TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, provider, key_scope, day)
) WITHOUT ROWID;

-- Audit ----------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor_user_id INTEGER,                            -- no FK: rows outlive deleted users; NULL = system/CLI
  ip_prefix TEXT,
  action TEXT NOT NULL,                             -- e.g. 'user.invited' (§4.13)
  target_type TEXT, target_id TEXT,
  details_json TEXT NOT NULL DEFAULT '{}'           -- never secrets, never health data
);
CREATE INDEX IF NOT EXISTS audit_at ON audit_log(at);
CREATE TRIGGER IF NOT EXISTS audit_log_append_only BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- Per-user profile (replaces the single-row `profile`) ------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '', weight_kg REAL, height_cm REAL,
  ckd_stage TEXT NOT NULL DEFAULT '3b', dialysis TEXT NOT NULL DEFAULT 'none',
  diabetes TEXT NOT NULL DEFAULT 'type1', warn_fraction REAL NOT NULL DEFAULT 0.8,
  targets_json TEXT NOT NULL DEFAULT '{}', dialysis_days_json TEXT NOT NULL DEFAULT '[]',
  week_start TEXT NOT NULL DEFAULT 'monday',
  -- + note 05 §4.2 fields (birth_month, sex, activity, …) added by that note's step
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL   -- note 01 threat row 20
);
CREATE TABLE IF NOT EXISTS user_food_links (        -- shared usda/off rows this person imported or scanned
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, food_id)
) WITHOUT ROWID;
```

**Ordering gotcha.** `migrate()` runs `SCHEMA` *before* the steps. Any index or trigger that names a
new column (`log_user_date`, the `user_required` triggers, `foods_owner`) must therefore live in
`_migrate_v3`, **never in `SCHEMA`**: on a v0.2 database `CREATE INDEX … ON log_entries(user_id, date)` would fail with "no
such column" before the step that adds the column has run.

`_migrate_v3(conn)` then does, in order:

1. `INSERT INTO users (id, username, username_norm, role, status, …) VALUES (1, :ADMIN_USERNAME,
   :norm, 'admin', 'pending_setup', …)` if `users` is empty. (If `APP_PASSWORD` is set, store its
   hash and set `status='active'`.)
2. `add_column_if_missing(conn, "log_entries", "user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")`;
   the same for `meal_templates.user_id`, and `foods.owner_user_id` (NULL = shared).
3. Back-fill: `UPDATE log_entries SET user_id = 1 WHERE user_id IS NULL`; same for
   `meal_templates`; `UPDATE foods SET owner_user_id = 1 WHERE source = 'custom' AND owner_user_id IS NULL`;
   `INSERT OR IGNORE INTO user_food_links SELECT 1, id, :now FROM foods WHERE source IN ('usda','off')`.
4. `INSERT OR IGNORE INTO user_profiles (user_id, name, …, updated_at) SELECT 1, name, …, updated_at
   FROM profile WHERE id = 1`. The old `profile` table stays (never dropped) and is never read again.
5. Indexes: `log_user_date ON log_entries(user_id, date)`, `meal_templates_user ON
   meal_templates(user_id, name)`, `foods_owner ON foods(owner_user_id) WHERE owner_user_id IS NOT NULL`.
6. For `log_entries` and `meal_templates`, two triggers each:
   ```sql
   CREATE TRIGGER IF NOT EXISTS log_entries_user_required_ins BEFORE INSERT ON log_entries
     WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'log_entries.user_id is required'); END;
   CREATE TRIGGER IF NOT EXISTS log_entries_user_required_upd BEFORE UPDATE OF user_id ON log_entries
     WHEN NEW.user_id IS NULL BEGIN SELECT RAISE(ABORT, 'log_entries.user_id is required'); END;
   ```

Scoping table (the rule every query follows):

| Table | Scope | Rule |
|---|---|---|
| `user_profiles`, `user_settings`, `log_entries`, `meal_templates`, `user_food_links`, `usage_daily`, `sessions`, `lab_results` (05), `ai_usage`, `ai_audit` (04) | `user_id` | Only the owner reads or writes. Admins have **no** API to read them. |
| `foods` | `owner_user_id` | `builtin` (NULL) visible to all. `custom` visible to the owner. Shared `usda`/`off` rows (NULL owner) visible when a `user_food_links` row exists. `builtin`, `usda` and `off` rows are read-only for everyone (edit = copy). |
| `secrets`, `ai_providers` (04) | `owner_user_id` NULL = shared | Shared: admins write, nobody reads plaintext through the API, the server uses it. User: owner writes, nobody reads plaintext through the API. |
| `instance_settings`, `audit_log` | instance | Admin only (users see their own security events in `audit_log`). |
| `barcode_cache`, `meta` | instance | Not personal. |
| `profile` | legacy | Frozen copy from v0.2. Not read. |

Visible-foods predicate (one helper, used by search, `GET /api/foods/{id}`, logging, saved meals and
guidance):

```sql
f.hidden = 0 AND (
  f.source = 'builtin'
  OR f.owner_user_id = :uid
  OR EXISTS (SELECT 1 FROM user_food_links l WHERE l.user_id = :uid AND l.food_id = f.id))
```

`POST /api/foods/usda/import` reuses an existing shared `usda` row for that `fdc_id` and only adds a
link. `POST /api/log`, `/api/meals` and `/apply` return **404** for a food that is not visible.

### 4.5 Flows

**First run.** If no `active` admin exists:

* `ADMIN_PASSWORD[_FILE]` set → user 1 becomes `active` with that password (policy checked; a
  failing password aborts start-up with a clear message). Logged: `admin "<name>" created from ADMIN_PASSWORD_FILE`.
* Otherwise a setup code is generated (10 random bytes → base32 → `XXXX-XXXX-XXXX-XXXX`, 80 bits),
  stored as an `auth_tokens` row (`purpose='setup'`, hashed, `SETUP_CODE_TTL_MINUTES`), and logged at
  WARNING:
  `FIRST-RUN SETUP: open https://<this server>/#/setup and enter the code 7KQ2-M9XD-PL4R-T6WN (valid 60 min; restart or run "python -m app.admin setup-code" for a new one)`.
* Until setup completes, every `/api` route except `/api/auth/status` and `/api/auth/setup` answers
  `503 {"detail": "Setup required", "setup_required": true}`; the UI shows the setup screen.
* `POST /api/auth/setup {code, username, display_name?, password}` claims user 1 (keeps its id, so the
  migrated data is theirs), signs them in and writes `setup.completed` to the audit log.

**Sign-in (local).** `POST /api/auth/login {username, password}` → normalise the name; check
`login_failures` and the per-IP limiter (§4.9); load the user or verify against `DUMMY_HASH`;
on success: reset counters, rehash if parameters changed (`needs_rehash`), create a session (new id —
never reuse a pre-login cookie), set the cookie, `audit login.succeeded`, return `{"user": Me}`.
A failure is audited as `login.failed` **only when the account exists** (target = user id); typed
usernames of unknown accounts are never stored, since people sometimes type a password there. On failure: 401
`{"detail": "Username or password is incorrect"}`, or 429 with `Retry-After` while delayed.

**Re-authentication.** `POST /api/auth/reauth {password}` sets `sessions.reauth_at`. Endpoints that
need it answer `403 {"detail": "Please enter your password again", "reauth_required": true}`; the
frontend asks for the password and retries once. Required for: changing password, setting or removing
any key, export, account deletion, every `/api/admin/*` write, and revoking other sessions.

**Sign-out.** `POST /api/auth/logout` deletes the session row, expires the cookie, and sends
`Clear-Site-Data: "cache", "storage"` (note 02; the client warns about unsynced entries first). In
proxy mode the response also carries `{"redirect": PROXY_LOGOUT_URL}`.

**Invites.** Admin → `POST /api/admin/invites {role, note?, ttl_days?}` returns
`{"url": "https://host/#/invite/<id>.<verifier>", "expires_at"}` **once**. The token is in the URL
**fragment**, which browsers never send to the server, so it stays out of proxy logs and `Referer`.
The page posts it: `POST /api/auth/register {token, username, display_name?, password}`. Single use,
hashed at rest, revocable (`DELETE /api/admin/invites/{id}`). No email in v0.3; the admin shares the
link however they like.

**Password reset.** No self-service (no SMTP in v0.3). Admin → `POST /api/admin/users/{id}/reset-link`
(24 h, single use, fragment token) or CLI `python -m app.admin reset-password <username>`. Completing a
reset revokes all of that user's sessions and clears a `locked` status.

**Proxy mode.** For each request, if `scope["state"]["peer"]` (note 01) is in `TRUSTED_PROXIES` and
the header is present: normalise (strip, NFC, ≤ 255 chars), look up `users(auth_source='proxy',
external_subject=…)`; if missing, create it when `PROXY_AUTO_CREATE_USERS=true`, else answer
`403 {"detail": "Your account is not enabled here. Ask the admin to add <name>."}`. If
`TRUSTED_PROXY_ADMIN_GROUP` is set, sync `role` from the groups header. No app session cookie is
needed. Initial setup in proxy mode still uses the setup code, and links the proxy identity to user 1.
A header from an untrusted peer is ignored and counted (shown in Admin → About as "identity headers
ignored from untrusted peers: N", which catches a wrong `TRUSTED_PROXIES`).

**`AUTH_MODE=none`.** Every request is user 1. Registration, invites and the users page are hidden.
The UI shows "No sign-in: anyone who can open this page can see and change this data." Intended for
local development, the static preview, and a single person on a trusted LAN who prefers v0.2
behaviour.

### 4.6 Passwords: `app/auth/passwords.py` and `app/auth/policy.py`

```python
import os, re, threading, unicodedata
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

ARGON2 = {"memory_cost": 19456, "iterations": 2, "lanes": 1}   # OWASP row 2: 19 MiB, t=2, p=1 (26 ms measured)
_GATE = threading.BoundedSemaphore(2)                          # ≤ 2 hashes in flight: ≤ 38 MiB, no memory DoS
_PHC = re.compile(r"^\$argon2id\$v=19\$m=(\d+),t=(\d+),p=(\d+)\$")

class HashBusy(Exception): ...                                  # → 503 + Retry-After: 1

def _bytes(pw: str) -> bytes:
    return unicodedata.normalize("NFC", pw).encode("utf-8")    # NIST: NFC; policy caps length first

def hash_password(pw: str) -> str:
    if not _GATE.acquire(timeout=5): raise HashBusy
    try: return Argon2id(salt=os.urandom(16), length=32, **ARGON2).derive_phc_encoded(_bytes(pw))
    finally: _GATE.release()

def verify_password(pw: str, stored: str | None) -> bool:
    if not _GATE.acquire(timeout=5): raise HashBusy
    try:
        if stored and stored.startswith("$argon2id$"):
            try: Argon2id.verify_phc_encoded(_bytes(pw), stored); return True
            except InvalidKey: return False
        if stored and stored.startswith("$scrypt$"):
            return _verify_scrypt(_bytes(pw), stored)          # fallback format, see below
        return False
    finally: _GATE.release()

def needs_rehash(stored: str) -> bool:
    m = _PHC.match(stored)
    return m is None or tuple(map(int, m.groups())) != (ARGON2["memory_cost"], ARGON2["iterations"], ARGON2["lanes"])

DUMMY_HASH = hash_password("not-a-real-password-used-for-timing")   # verify unknown users against this
```

* Start-up self-test: hash and verify one password; on `UnsupportedAlgorithm` exit with
  "This build of cryptography lacks Argon2id (needs OpenSSL ≥ 3.2; PyPI wheels bundle it). Install the
  wheel or set PASSWORD_HASH=scrypt."
* scrypt fallback (only with `PASSWORD_HASH=scrypt`): `hashlib.scrypt(pw, salt=16 random bytes,
  n=2**14, r=8, p=5, maxmem=32*1024*1024, dklen=32)`, stored as
  `$scrypt$ln=14,r=8,p=5$<b64 salt>$<b64 hash>`. Successful logins rehash to Argon2id when it becomes
  available.

Policy (`validate_new_password(pw, *, username, display_name) -> list[str]` returns messages):

1. Normalise to NFC; length = code points. `< PASSWORD_MIN_LENGTH` → "Use at least 15 characters.
   A short sentence or three or four unrelated words works well."; `> 128` → "Use at most 128 characters."
2. No composition rules, no expiry, no hints, no security questions.
3. Blocklist on the **whole** password, casefolded: `app/data/password-blocklist.txt.gz` (the NCSC
   top-100k entries with ≥ 8 characters, 46,483 lines, ~148 KB; built by
   `scripts/build_password_blocklist.py`, which records the source URL and SHA-256), plus context words:
   the username, the display name, `kidneyhealth`, `kidney health`, `kidney-health`, and the instance
   name. Also refuse one repeated character and straight runs of a keyboard row or the alphabet/digits
   (`123456789012345`, `qwertyuiopasdfg`).
4. If `PASSWORD_BREACH_CHECK=true`: SHA-1 the password, `GET https://api.pwnedpasswords.com/range/<5>`
   with `Add-Padding: true` and a 3 s timeout; refuse if the suffix has a count > 0. Network errors
   are ignored (logged at INFO).
5. Changing a password needs the current one (OWASP) and revokes the person's **other** sessions.
6. Admin action "Require a new password" sets `must_change_password=1` (NIST "evidence of
   compromise"); the UI then allows only the change-password screen.

Frontend fields: `autocomplete="username"` / `"current-password"` / `"new-password"`, a "Show"
toggle, paste allowed, `passwordrules="minlength: 15; maxlength: 128;"` on new-password fields
(Safari uses it when suggesting a strong password).

### 4.7 Sessions and cookies: `app/auth/sessions.py`

* Create: `sid = secrets.token_hex(16)`, `verifier = secrets.token_urlsafe(32)`; store
  `sha256(verifier)`; cookie value `f"{sid}.{verifier}"`.
* Cookie: over HTTPS (effective scheme after note 01's proxy handling) name **`__Host-kh_session`**,
  `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=<SESSION_MAX_DAYS in seconds>`, no `Domain`. Over
  plain HTTP (only when allowed, §4.3) name `kh_session`, same attributes without `Secure`.
* Validate: split on the first `.`, load by `sid`, `hmac.compare_digest(sha256(verifier),
  verifier_hash)`, check `expires_at` (absolute) and `last_seen_at + SESSION_IDLE_DAYS`, check the
  user is `active`. Update `last_seen_at` at most every 5 minutes (fewer writes).
* Rotate on login, on password change and on role change. Delete expired rows at start-up and hourly.
* "Signed-in devices": `GET /api/me/sessions` lists `{id, created_at, last_seen_at, user_agent,
  ip_prefix, current}`; `DELETE /api/me/sessions/{id}`; `POST /api/me/sessions/revoke-others`.
* Why 30 days / 14 idle rather than OWASP's 15–30-minute idle: password-only login is NIST AAL1
  (≤ 30 days), people log meals several times a day on a locked personal phone, and the risky
  actions are behind the 10-minute re-authentication. Admins can revoke any user's sessions.

### 4.8 CSRF and request checks (extends note 01 `CsrfMiddleware`)

For `POST`, `PUT`, `PATCH`, `DELETE` under `/api/`:

1. If `Sec-Fetch-Site` is present and not `same-origin` → 403 `{"detail": "Cross-site request refused"}`.
2. Else if `Origin` is present and its scheme/host/port differ from the request's effective origin
   (or it is `null`) → 403.
3. **New:** if `X-Requested-With` is not exactly `kidney-health` → 403
   `{"detail": "Missing X-Requested-With header"}`. Applies to the login, setup, register and reauth
   endpoints too (login CSRF).
4. Never register `CORSMiddleware`; never answer `OPTIONS` with `Access-Control-Allow-*`.

Frontend (`app/static/app.js` `request()`): add `'X-Requested-With': 'kidney-health'` to every call;
keep `fetch()`'s default mode (do **not** set `mode: 'same-origin'`, F4); on 401 show the sign-in
screen and keep the current view; on 403 with `reauth_required` show the password prompt and retry
once. Multipart uploads (note 03) add the header too.

### 4.9 Throttling and lockout: `app/auth/throttle.py`

| Layer | Rule | Store |
|---|---|---|
| Per username (exists or not) | Failures 1–5: no delay. From the 6th: `locked_until = now + min(15 min, 30 s × 2^(n−6))`. While delayed: 429 without checking the password. Success resets. A valid device cookie for that account bypasses this layer (§9 N3). | `login_failures`, keyed by `name_mac` (rows idle for 24 h are pruned; table capped at 10,000 rows. **Eviction never removes a row that is delayed or has ≥ 5 failures**; when only such rows remain, a new name is answered with the delay instead of evicting. Corrected in the security review: "oldest first" let an attacker flush a victim's counter with 10,000 junk names) |
| NIST hard stop | At 100 consecutive failures on an existing account: `status='locked'`, all sessions revoked, `audit user.locked`; only an admin reset link (or the CLI) unlocks | `users.status` |
| Per client IP | `LOGIN_IP_MAX_FAILURES` (20) failures in 10 min → 10-min block for login, setup, register, reset and reauth | in memory (one process) |
| Global | 60 login attempts per minute for the whole instance | in memory |
| Hashing | `_GATE` semaphore: 2 concurrent; waiting > 5 s → 503 | in memory |
| Registration (`open` mode) | 3 per IP per hour | in memory |

Messages are identical for unknown and known usernames, and unknown usernames run a dummy verify so
the timing matches. The client IP is the one note 01's trusted-proxy handling produced.

### 4.10 Authorisation and scoping in FastAPI: `app/auth/deps.py`

```python
from typing import Annotated
from fastapi import Depends, HTTPException, Request

def current_user(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> User:
    s = request.app.state.settings
    if s.auth_mode == "none":
        user = load_user(conn, 1)
    elif s.auth_mode == "proxy":
        user = user_from_trusted_header(request, conn, s)       # peer must be in TRUSTED_PROXIES
    else:
        user = user_from_session_cookie(request, conn, s)       # §4.7
    if user is None or user.status != "active":
        raise HTTPException(401, "Sign in required")
    return user

CurrentUser = Annotated[User, Depends(current_user)]

def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only")
    return user

AdminUser = Annotated[User, Depends(require_admin)]

class ReauthRequired(Exception): ...   # handler → 403 {"detail": "Please enter your password again", "reauth_required": true}

def require_recent_auth(user: CurrentUser, request: Request, conn=Depends(get_db)) -> User:
    if not session_reauth_is_recent(request, conn, minutes=request.app.state.settings.reauth_minutes):
        raise ReauthRequired()        # not HTTPException(detail=dict): that would nest "detail" and break the contract shape
    return user
```

Rules:

* Every router declares `dependencies=[Depends(current_user)]` (admin routers `require_admin`), and
  every handler that touches data also takes `user: CurrentUser` and passes `user.id` **explicitly**
  into the query helpers (`log.day_summary(conn, user.id, date)`). No context variables, no globals:
  pure functions stay testable.
* Not found and not yours are the same: **404**, never 403, so ids cannot be probed.
* Public routes (the only ones without `current_user`): `GET /healthz`, `GET /api/auth/status`,
  `POST /api/auth/{login,setup,register,reset}`, plus static files, the manifest and icons
  (note 02 R6). `index.html` carries no data.
* **Coverage test** (`tests/test_auth_coverage.py`, works with FastAPI ≥ 0.137 route trees):

  ```python
  PUBLIC = {("get", "/api/auth/status"), ("post", "/api/auth/login"), ("post", "/api/auth/setup"),
            ("post", "/api/auth/register"), ("post", "/api/auth/reset")}

  def test_every_api_route_requires_auth(anon_client, app):
      for path, ops in app.openapi()["paths"].items():
          if not path.startswith("/api/"):
              continue
          url = re.sub(r"\{[^}]+\}", "1", path)
          for method in ops:
              if (method, path) in PUBLIC:
                  continue
              r = anon_client.request(method.upper(), url, json={},
                                      headers={"X-Requested-With": "kidney-health"})
              assert r.status_code == 401, (method, path, r.status_code)
  ```

  Prototyped: it catches an unprotected router and passes protected ones even with an invalid body.
* **Two-user isolation matrix** (`tests/test_isolation.py`): user A creates one of everything (entry,
  custom food, saved meal, lab, key, setting); user B gets 404 on every id-bearing route (GET, PUT,
  DELETE, apply, copy), never sees A's rows in lists, summaries, shopping, search, export, guidance;
  B's USDA import of the same `fdc_id` links the shared row without exposing A's link.

### 4.11 Settings: `app/settings_registry.py` and `app/settings_store.py`

```python
@dataclass(frozen=True)
class SettingDef:
    key: str                                   # dotted, e.g. "providers.usda.daily_limit_per_user"
    model: type                                # pydantic-validated type: bool, int, Literal[...], a BaseModel
    default: Any
    scope: Literal["instance", "user", "user_default"]   # user_default: admin default, user may override
    env: str | None = None                     # env var that LOCKS it
    label: str = ""
    help: str = ""
```

Initial registry (other notes add their keys here rather than inventing new stores):

| Key | Scope | Default | Env lock | Owner |
|---|---|---|---|---|
| `instance.name` | instance | `Kidney Health` | `INSTANCE_NAME` | this note |
| `registration.mode` | instance | `invite` | `REGISTRATION_MODE` | this note |
| `registration.invite_ttl_days` | instance | `7` | – | this note |
| `audit.retention_days` | instance | `365` | `AUDIT_RETENTION_DAYS` | this note |
| `providers.usda.shared_enabled` | instance | `true` (effective only if a shared key exists) | – | this note |
| `providers.usda.user_keys_allowed` | instance | `true` | – | this note |
| `providers.usda.daily_limit_per_user` | instance | `200` (0 = unlimited) | `USDA_SHARED_DAILY_LIMIT` | this note |
| `food.off_enabled`, `food.off_contact`, … | instance | note 03 R10 | `OFF_ENABLED`, `OFF_CONTACT` | 03 |
| `ai.enabled`, `ai.user_keys_allowed`, `ai.allow_user_base_url`, `ai.shared_daily_limit` | instance | note 04 R4 | `AI_ENABLED`, `AI_ALLOW_USER_KEYS`, `AI_ALLOW_USER_BASE_URL`, `AI_SHARED_DAILY_LIMIT` | 04 |
| `guidance.enabled` | instance | `true` | `GUIDANCE_ENABLED` | 06 |
| `ui.theme` | user_default | `system` | – | this note |
| `food.off_consent` | user | `false` | – | 03 |
| `ai` (object: opt_in, provider, share_age_sex, preferences, consents, …) | user | note 04 R4 | – | 04 |
| `guidance` (object: enabled, carb_tolerance_g, hypo_dose_g, …) | user | note 06 §4.14 | – | 06 |

Precedence (`effective(key, user_id)`):

1. `env` set → that value, `source="env"`, **locked** (UI read-only: "Set by the server (`OFF_ENABLED`)").
2. `scope` is `user` or `user_default` and the person has a row → their value, `source="user"`.
3. `instance_settings` row → that value, `source="instance"`.
4. The registry default, `source="default"`.

Values are validated with the key's Pydantic type on write **and** on read (a bad stored value falls
back to the default with a warning, so a hand-edited DB cannot crash a request). Settings are cached
in memory per process and invalidated on write.

API:

* `GET /api/me/settings` → `{"settings": {key: {"value", "source", "editable"}}}` for user-visible keys.
* `PATCH /api/me/settings` `{key: value | null}` (null = back to inherited) → same shape.
* `GET /api/admin/settings` → instance keys with `locked_by_env`; `PATCH /api/admin/settings` (re-auth;
  audited with old and new values for non-secret keys).

### 4.12 Secrets: `app/crypto.py`, `app/credentials.py`

Key material (`app/crypto.py`):

```python
import base64, hashlib, json
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

def _derive(master: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"kidney-health/v1/secrets").derive(master)

class Keyring:
    def __init__(self, lines: list[str]):                      # SECRET_KEY[_FILE], one key per line
        masters = [l.strip().encode() for l in lines if l.strip() and not l.lstrip().startswith("#")]
        if not masters or any(len(m) < 32 for m in masters):
            raise SystemExit("SECRET_KEY: each line must be at least 32 characters")
        derived = [_derive(m) for m in masters]
        self.ids = [hashlib.sha256(d).hexdigest()[:8] for d in derived]   # non-secret key ids
        self.current_id = self.ids[0]
        self.fernet = MultiFernet([Fernet(base64.urlsafe_b64encode(d)) for d in derived])

    def seal(self, *, purpose: str, owner: int | None, fields: dict[str, str]) -> tuple[bytes, str]:
        env = {"v": 1, "purpose": purpose, "owner": owner, "fields": fields}
        return self.fernet.encrypt(json.dumps(env, separators=(",", ":")).encode()), self.current_id

    def unseal(self, token: bytes, *, purpose: str, owner: int | None) -> dict[str, str]:
        env = json.loads(self.fernet.decrypt(token))           # InvalidToken if tampered or unknown key
        if env.get("v") != 1 or env.get("purpose") != purpose or env.get("owner") != owner:
            raise InvalidToken                                  # ciphertext moved to another row
        return env["fields"]
```

* `purpose` is `"secret:usda"` for the `secrets` table and `"ai_provider:<id>"` for note 04's
  `ai_providers.api_key_enc`; `owner` is `owner_user_id` (NULL for shared).
* Auto-generated key: when neither `SECRET_KEY` nor `SECRET_KEY_FILE` is set, create
  `/data/secret.key` with `os.open(path, O_WRONLY|O_CREAT|O_EXCL, 0o600)` and
  `secrets.token_urlsafe(32)`, and warn: "Back up /data/secret.key separately from kidney.db; without
  it stored API keys cannot be decrypted (passwords and health data are not affected)."
* **Rotation.** Auto-generated file: `python -m app.admin rotate-secret-key` prepends a new line,
  re-encrypts every `secrets.ciphertext` and `ai_providers.api_key_enc` with `MultiFernet.rotate()`,
  updates `key_id`, then removes the old line. Mounted `SECRET_KEY_FILE` (read-only): the operator
  adds a new first line, restarts, runs `python -m app.admin reencrypt`, removes the old line,
  restarts. Admin → About shows "N secrets still use an older key".
* A row that fails to decrypt (lost key) is reported as `{"set": true, "status": "unreadable"}` and
  the UI asks for the key again; it never crashes a request.

Write-only API (`app/credentials.py` + routes):

* `GET /api/me/keys` →
  ```json
  {"providers": [{"provider": "usda", "label": "USDA FoodData Central",
     "own": {"set": true, "last4": "9xQz", "updated_at": "2026-10-03T09:12:00Z"},
     "shared": {"available": true, "remaining_today": 187},
     "user_keys_allowed": true,
     "effective": "own"}]}
  ```
* `PUT /api/me/keys/{provider}` `{"api_key": "…", "test": true}` (re-auth) → the same item. Validation:
  8–512 printable ASCII characters, no whitespace. With `test`, one cheap upstream call (USDA:
  `GET /fdc/v1/foods/search?query=apple&pageSize=1` with `X-Api-Key`) and the result
  `{"test": "ok" | "rejected" | "unreachable"}`. The key is never echoed.
* `DELETE /api/me/keys/{provider}` (re-auth) → 204.
* Admin: `GET /api/admin/keys`, `PUT/DELETE /api/admin/keys/{provider}` for shared keys. An env key
  shows `{"set": true, "source": "env", "locked": true}` and cannot be changed or removed.
* Response models have **no** field that could hold a key; a test sets keys, then greps every JSON
  response and every captured log line for the plaintext.

Resolution (`resolve(conn, user, provider) -> Credential | Unavailable`), used by USDA lookups and,
with note 04's tables, by AI:

1. If `user_keys_allowed` and the person has an own key → **own** (counted in `usage_daily` with
   `key_scope='own'`, no limit).
2. Else if a shared key exists (env or DB), `shared_enabled`, `users.can_use_shared = 1`, and the
   atomic quota take succeeds → **shared**:
   ```sql
   INSERT INTO usage_daily (user_id, provider, key_scope, day, requests) VALUES (?, ?, 'shared', ?, 1)
   ON CONFLICT (user_id, provider, key_scope, day) DO UPDATE SET requests = requests + 1
   WHERE usage_daily.requests < :limit;      -- cursor.rowcount == 0  →  quota exhausted (verified)
   ```
3. Else `Unavailable(reason)` with `not_configured`, `not_allowed` or `quota_exhausted`, which the UI
   turns into "Add your own key in Settings → Food data" or "Today's shared lookups are used up".

A rejected **own** key (401/403 upstream) is reported as such and **never** retried with the shared
key (note 04). For USDA the server also keeps a process-wide guard below the 1,000/hour key limit,
reading `X-RateLimit-Remaining` and answering 429 when it drops under 50.

### 4.13 Audit log: `app/audit.py`

`audit(conn, actor_id, action, target_type=None, target_id=None, **details)` inside the same
transaction as the change. Actions:

`setup.completed`, `login.succeeded`, `login.failed` (existing accounts only), `user.locked`,
`user.invited`, `invite.revoked`, `user.registered`, `user.created_by_proxy`, `user.role_changed`,
`user.disabled`, `user.enabled`, `user.deleted`, `user.reset_link_issued`, `user.password_changed`,
`user.must_change_password`, `sessions.revoked`, `settings.changed` (key, old, new — non-secret keys
only), `secret.set` / `secret.removed` (provider and scope, **never** the value or last4),
`ai_provider.changed`, `export.created`, `account.deleted`, `secret_key.rotated`, `backup.created`
(CLI).

* Admins: `GET /api/admin/audit?before=<id>&limit=50`. Users: `GET /api/me/activity` (their own
  login, session, password, key and export events).
* No updates (trigger). Retention: delete rows older than `audit.retention_days` at start-up and daily.
* Deleted users appear as "deleted user #5" (no name stored in audit rows, so nothing needs scrubbing).

### 4.14 Export and account deletion

* `GET /api/me/export.zip` (re-auth; 10 per hour) streams a `zipfile` with:
  * `export.json`: `{"format": "kidney-health-export", "version": 1, "exported_at", "app_version",
    "user": {username, display_name, created_at}, "profile", "settings" (non-secret), "log_entries",
    "custom_foods", "linked_foods" (ids + names), "meal_templates", "lab_results", "ai_audit",
    "activity"}`;
  * `log.csv` (the existing export columns plus `status` and `source`), `foods.csv`, `meals.csv`,
    `labs.csv`;
  * `README.txt` explaining the files and that no keys or passwords are included.
  Headers: `Content-Disposition: attachment; filename="kidney-health-<username>-<date>.zip"`,
  `Cache-Control: no-store`. `GET /api/log/export.csv` stays (scoped) for the dietitian.
* Import of `export.json` into another instance: v0.4 (`POST /api/me/import`), designed against this
  format now.
* `DELETE /api/me` `{"password": "…", "confirm": "DELETE"}` (re-auth): refused with 409 for the last
  active admin ("Make someone else an admin first"). Otherwise, in one transaction, `audit
  account.deleted` then `DELETE FROM users WHERE id = ?` (cascades, prototyped), then
  `PRAGMA wal_checkpoint(TRUNCATE)`. Every connection sets **`PRAGMA secure_delete = FAST`** (zeroes
  deleted b-tree content at no extra I/O). `python -m app.admin vacuum` removes freelist traces.
  The UI first offers the export and lists what will be deleted; it says that existing backups still
  contain the data until they expire.
* Admin deletion of another user: `DELETE /api/admin/users/{id}` with the same cascade, re-auth, and
  a typed confirmation of the username.

### 4.15 Backups and restore

Builds on note 01's `python -m app.admin backup FILE|-` (SQLite backup API, no shell needed):

* A backup contains every person's health data, password hashes, session verifier hashes, encrypted
  keys and the audit log. Encrypt it (restic, borg or age), keep it `0600`.
* **`SECRET_KEY` is not in a `python -m app.admin backup` copy.** It **is** in any volume-level
  backup (restic or borg of the volume directory, a Longhorn or Velero snapshot of the PVC, `podman
  volume export`) whenever it was auto-generated as `/data/secret.key`, and then the encrypted keys
  in that backup are readable. Every shipped deploy profile therefore mounts `SECRET_KEY_FILE` from
  the engine's secret store, outside `/data`, and Admin → About warns while the key lives on the
  data volume. Back the key up separately. Restoring without it loses only stored API keys.
  (Corrected in the security review: the earlier text said "not in the backup (by design)"
  without that condition.)
* `python -m app.admin restore-check FILE` (note 01) additionally reports the schema version, user
  count and secrets readable with the current key. `--revoke-sessions` clears `sessions` after a
  restore.
* The automatic `kidney.db.pre-v3.bak` is the rollback path. **Rolling back to v0.2 after a second
  person has signed up would merge everyone's log in the v0.2 UI**; restore the pre-v3 backup instead.
* Per-person export is for portability, not a backup.

### 4.16 HTTP API summary (contract additions for `ARCHITECTURE.md`)

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /api/auth/status` | public | `{setup_required, auth_mode, registration, insecure_http, password_min_length, user: Me or null, logout_url}` |
| `POST /api/auth/setup` | public + setup code | Claim user 1 |
| `POST /api/auth/login` · `/logout` · `/reauth` | public / user / user | §4.5 |
| `POST /api/auth/register` | public + invite token (or open mode) | New account |
| `POST /api/auth/reset` | public + reset token | Set a new password |
| `GET/PATCH /api/me` | user | `Me = {id, username, display_name, role, auth_source, must_change_password, created_at}`; PATCH: display_name |
| `POST /api/me/password` | user + re-auth | `{current_password, new_password}` |
| `GET /api/me/sessions` · `DELETE /api/me/sessions/{id}` · `POST /api/me/sessions/revoke-others` | user (+ re-auth for revoke-others) | Devices |
| `GET/PATCH /api/me/settings` | user | §4.11 |
| `GET /api/me/keys` · `PUT/DELETE /api/me/keys/{provider}` | user (+ re-auth for writes) | §4.12 |
| `GET/PUT /api/me/ai`, `POST /api/me/ai/probe` | user | Note 04 fields, stored via §4.11/§4.12 |
| `GET /api/me/usage` | user | Today and 30 days, per provider and scope |
| `GET /api/me/activity` | user | Own security events |
| `GET /api/me/export.zip` · `DELETE /api/me` | user + re-auth | §4.14 |
| `GET/POST /api/admin/users` · `PATCH/DELETE /api/admin/users/{id}` | admin (+ re-auth for writes) | role, status, `can_use_shared`, `must_change_password`; POST in `closed` mode returns a setup link |
| `POST /api/admin/users/{id}/reset-link` · `POST /api/admin/users/{id}/revoke-sessions` | admin + re-auth | |
| `GET/POST /api/admin/invites` · `DELETE /api/admin/invites/{id}` | admin (+ re-auth for writes) | |
| `GET/PATCH /api/admin/settings` | admin (+ re-auth) | |
| `GET /api/admin/keys` · `PUT/DELETE /api/admin/keys/{provider}` | admin + re-auth | Shared keys |
| `/api/admin/ai-providers…` | admin | Note 04 |
| `GET /api/admin/usage?days=30` | admin | Per user and provider counts only |
| `GET /api/admin/audit` | admin | |
| `GET /api/admin/about` | admin | Version, schema, auth mode, secret-key source and rotation status, HTTPS status, ignored identity headers, last backup seen |

Existing routes keep their paths (`/api/profile`, `/api/log`, `/api/foods`, …) and now act on the
signed-in person. Changes: `PUT /api/foods/{id}` on a `usda`/`off` row answers 409 (copy first), and
foods not visible to the person answer 404.

### 4.17 The settings menu (UI behaviour; frontend owner)

A new **Settings** view (gear icon). The existing Profile view stays as it is, for body data and
targets.

```
Settings
├─ Account            name · username · Change password · Signed-in devices · Your data (Export · Delete account)
├─ Food data          USDA key (own) · shared-key status and today's remaining lookups · Barcode lookups (note 03)
├─ AI ideas           note 04 (opt-in, provider, consent)
├─ Meal guidance      note 06
├─ This device        note 02 R10 (install, offline, storage)
├─ Admin (admins)     Users & invites · Sign-in & registration · Shared keys & providers · Usage · Activity · About this server
└─ About & privacy    what is stored, who can see it ("the person who runs this server can technically read all data"), disclaimers, licences
```

Key widget, the same everywhere: when set, "Set · ends in 9xQz · updated 3 Oct" with **Replace** and
**Remove**; when replacing, an empty `<input type="password" autocomplete="off" spellcheck="false">`
(never pre-filled), **Test**, **Save**. When locked by env: "Set by the server" and no buttons. Shared
status line for users: "Using the shared key from your admin (187 of 200 lookups left today)" or "Ask
your admin to share a key, or add your own".

Sign-in, setup, invite and reset screens are part of `index.html` (hash routes `#/login`, `#/setup`,
`#/invite/<token>`, `#/reset/<token>`), keyboard and screen-reader friendly, with errors in an
`aria-live` region. A plain-HTTP banner (note 01/02) explains why inviting others needs HTTPS.

### 4.18 File layout (new or changed)

```
app/auth/__init__.py
app/auth/passwords.py        Argon2id via cryptography, scrypt fallback, DUMMY_HASH, semaphore
app/auth/policy.py           NIST policy, blocklist loader, HIBP (optional)
app/auth/sessions.py         create/validate/rotate/revoke, cookie helpers
app/auth/throttle.py         per-username delays (SQLite), per-IP and global limiters (memory)
app/auth/deps.py             current_user, CurrentUser, require_admin, AdminUser, require_recent_auth
app/auth/proxy.py            trusted-header identity (uses note 01 peer + TRUSTED_PROXIES)
app/auth/routes.py           /api/auth/*
app/me.py                    /api/me/* (profile of the account, sessions, settings, keys, usage, export, delete)
app/admin_api.py             /api/admin/* (users, invites, settings, keys, usage, audit, about)
app/admin.py                 CLI (note 01) + create-admin, setup-code, reset-password, list-users,
                             disable-user, revoke-sessions, reencrypt, rotate-secret-key, export-user, vacuum
app/crypto.py                Keyring, seal/unseal, secret-key file bootstrap
app/credentials.py           provider registry, resolve(), quota take, USDA test call
app/settings_registry.py     SettingDef list (other notes append)
app/settings_store.py        effective(), read/write, cache
app/audit.py                 audit(), retention
app/export.py                zip/JSON/CSV export
app/data/password-blocklist.txt.gz
app/db.py                    schema v3 (§4.4), pre-migration backup, secure_delete=FAST, triggers
app/config.py                new env keys (§4.3), *_FILE loader (note 01)
app/main.py                  remove BasicAuthMiddleware; register routers; setup gate; start-up self-tests
app/foods.py, log.py, meals.py, profile.py   take user: CurrentUser; pass user.id; visibility helper
app/static/app.js            X-Requested-With header, 401/reauth handling, login/setup/invite/reset, Settings view
app/static/index.html, style.css
scripts/build_password_blocklist.py
tests/conftest.py            app factory per test, users A/B/admin, signed-in clients
tests/test_auth.py           setup, login, logout, lockout, reauth, invites, reset, proxy mode, none mode
tests/test_auth_coverage.py  §4.10 behavioural coverage
tests/test_isolation.py      two-user matrix
tests/test_passwords.py      policy, hashing, rehash, scrypt fallback, timing parity (loose)
tests/test_settings.py       precedence, env locks, validation
tests/test_secrets.py        write-only, seal binding, rotation, unreadable rows, quota
tests/test_migrations.py     + v0.2 → v3 (and v0.1 → v3) with data; pre-v3 backup; foreign_key_check
tests/test_export_delete.py  zip contents, no secrets, cascade, last-admin rule
docs/accounts.md             operator guide: modes, first run, invites, proxy examples (Caddy+Authelia, authentik, tailscale serve), rotation, recovery
docs/privacy.md              what is stored, who can see it, export/delete, backups, not legal advice
```

### 4.19 Contract and documentation changes

* `ARCHITECTURE.md`: remove "multi-user accounts" from non-goals; add the auth contract (§4.5–§4.10),
  the data model (§4.4), the API (§4.16), "every personal query is scoped by user_id", "builtin, usda
  and off foods are read-only", and the `X-Requested-With` requirement.
* `README.md`: configuration table (§4.3), first-run instructions, the `APP_PASSWORD` deprecation.
* `docs/deployment.md`: first run (`podman logs kidney-health | grep FIRST-RUN`), `ADMIN_PASSWORD_FILE`
  examples for Quadlet, compose and Kubernetes, `SECRET_KEY` backup, proxy mode per topology.
* `docs/network-allowlist.md`: `api.pwnedpasswords.com` (only with `PASSWORD_BREACH_CHECK=true`).
* Release notes for v0.3: Basic auth removed; the first start migrates data to user 1 and prints a
  setup code unless `APP_PASSWORD` or `ADMIN_PASSWORD_FILE` is set; `kidney.db.pre-v3.bak` is created.

---

## 5. Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | Proxy mode with a wrong `TRUSTED_PROXIES`, or the app port reachable around the proxy: a forged `Remote-User: admin` takes over | Medium / High | Refuse to start on `0.0.0.0/0`/`::/0`; publish on 127.0.0.1 (note 01); count and show ignored identity headers; per-topology docs; proxy mode stays opt-in |
| R2 | A missed `user_id` filter leaks one person's data to another | Medium / High | Router-level deps; explicit `user_id` parameters; behavioural coverage test; two-user isolation matrix; 404 for "not yours"; review checklist in `CONTRIBUTING.md` |
| R3 | The 15-character minimum frustrates patients, so admins lower it | Medium / Medium | Clear guidance text, password-manager autofill and `passwordrules`, blocklist still applies at 8+, passkeys in v0.4 make 8 compliant |
| R4 | Lockout as denial of service by someone who knows a username | Low / Medium | Delays, not hard locks, capped at 15 min; per-IP blocks; the 100-failure stop needs about a day of sustained guessing and is audited; admin reset link |
| R5 | Lost `SECRET_KEY` | Medium / Low | Only stored API keys are lost (no pepper by design); About page warning; docs; "unreadable" rows prompt re-entry |
| R6 | Migration v3 fails halfway or corrupts data | Low / High | Automatic `kidney.db.pre-v3.bak`; one transaction; `foreign_key_check`; tests from real v0.1 and v0.2 fixtures |
| R7 | Rollback to v0.2 after a second person joined mixes data | Low / High | Release notes; restore the pre-v3 backup instead |
| R8 | `cryptography` built from source against OpenSSL < 3.2 lacks Argon2id | Low / Medium | Start-up self-test with a clear message; `PASSWORD_HASH=scrypt` fallback; PyPI wheels bundle OpenSSL 4.0.3 |
| R9 | Plain-HTTP LAN: no `Secure` cookie, no Fetch Metadata, no `Clear-Site-Data`; the session can be sniffed | High (common setup) / Medium | Allowed only while one account exists or with `ALLOW_INSECURE_HTTP=true`; custom header + `Origin` checks still work; banner; HTTPS docs (note 02) |
| R10 | People assume the admin cannot see their data | Medium / Medium | Plain disclosure on register and About pages; no admin UI for health data; no impersonation |
| R11 | Shared keys overspent (USDA hourly limit, OpenAI cost) | Medium / Medium | Per-user daily limits, per-user `can_use_shared`, usage page, process-wide USDA guard, note 04 AI limits |
| R12 | Setup code shipped to a central log store | Low / Medium | One-time, 60-min TTL, regenerated per start; `ADMIN_PASSWORD_FILE` or CLI as alternatives |
| R13 | A lost phone keeps a 30-day session | Medium / Medium | Device list and remote sign-out; admin revoke; 14-day idle; re-auth for sensitive actions; note 02 logout clearing |
| R14 | FastAPI/Starlette internals keep moving (0.137 route tree, 0.142 OpenTelemetry dependency, `httpx2` test client) | High / Low | Behavioural tests instead of route walking; lock-file pins with Dependabot (note 01); watch release notes |
| R15 | Audit log grows or holds personal data | Low / Low | Retention setting; ids only, no names, no values of secrets or health data |
| R16 | Backups hold everyone's data indefinitely | Medium / Medium | Encrypt, rotate, document in `docs/privacy.md` that deletion does not reach old backups |

---

## 6. Implementation checklist

Each item ends with *done when* in italics. Phases are ordered; each one leaves `python -m pytest`
green.

**Phase 0: contract and dependency**

- [ ] Update `ARCHITECTURE.md` per §4.19 before writing code. *Reviewed in a PR on its own.*
- [ ] Add `cryptography==50.0.2` to `requirements.in`, re-lock with hashes (note 01). *The image builds for amd64 and arm64.*
- [ ] `app/crypto.py` (Keyring, seal/unseal, key-file bootstrap) with tests: round trip, purpose/owner mismatch → `InvalidToken`, rotation with two lines, file created `0600` and never overwritten. *`tests/test_secrets.py` green.*
- [ ] `app/auth/passwords.py` + `policy.py` + `scripts/build_password_blocklist.py` (download, NFC+casefold, keep ≥ 8 chars, gzip, record SHA-256). *Hash/verify/needs_rehash tests; policy tests for 14/15/128/129 code points, NFC equivalence (`é` composed vs decomposed), blocklist hit, username as password, repeated character.*

**Phase 1: schema v3**

- [ ] `_migrate_v3` per §4.4, pre-migration backup, `PRAGMA secure_delete = FAST` in `connect()`. *Migration tests from v0.1 and v0.2 databases with data: rows owned by user 1, `user_profiles` row copied, `foreign_key_check` empty, triggers refuse NULL `user_id`, `.pre-v3.bak` exists once.*
- [ ] Fresh-database `SCHEMA` produces the same tables, columns, indexes and triggers as a migrated one. *A test compares `sqlite_master` of both, ignoring order.*

**Phase 2: sign-in**

- [ ] `app/auth/sessions.py`, `throttle.py`, `deps.py`, `routes.py`; remove `BasicAuthMiddleware`; setup gate (503) and setup code logging; `ADMIN_PASSWORD_FILE` and `APP_PASSWORD` import. *Tests: setup with a wrong/expired/used code fails; login sets `__Host-kh_session` with `Secure; HttpOnly; SameSite=Lax; Path=/` behind an https proxy and `kh_session` without `Secure` on http; logout deletes the row and sends `Clear-Site-Data`; idle and absolute expiry; rotation on login.*
- [ ] Throttling. *Tests (with a fake clock): 6th failure delayed, delays double and cap at 15 min, identical responses for unknown users, 100th failure locks, per-IP block after 20, success resets.*
- [ ] CSRF header in note 01's `CsrfMiddleware`. *Tests: unsafe request without `X-Requested-With` → 403; `Sec-Fetch-Site: same-site` → 403; `Origin` mismatch → 403; same-origin `fetch`-like request → passes.*
- [ ] Frontend: header in `request()`, 401 → sign-in screen, re-auth prompt, setup/login/invite/reset screens, `autocomplete` and `passwordrules`. *Playwright: first run end to end at 375×812 and 1280×800, light and dark; no console CSP errors.*
- [ ] Update the static preview (`scripts/build_preview.py`, MockApi) to answer `/api/auth/status` with `auth_mode: "none"`. *Preview build test green.*

**Phase 3: scoping**

- [ ] Every router gets `dependencies=[Depends(current_user)]`; every handler passes `user.id`; the visible-foods predicate; `usda`/`off` rows read-only; USDA import links. *`tests/test_auth_coverage.py` and `tests/test_isolation.py` green; the existing 192 tests pass with a signed-in client fixture.*

**Phase 4: settings and secrets**

- [ ] `settings_registry.py`, `settings_store.py`, `/api/me/settings`, `/api/admin/settings`; notes 03, 04 and 06 register their keys here. *Precedence tests: env lock beats user and instance; null resets; invalid stored value falls back with a warning.*
- [ ] `secrets` table, `/api/me/keys`, `/api/admin/keys`, `credentials.resolve()`, quota UPSERT, USDA wired to `resolve()` (replaces the env-only key), USDA hourly guard. *Tests: plaintext never in any response or log; own beats shared; shared disabled/`can_use_shared=0`/quota exhausted give the three reasons; a rejected own key does not fall back.*
- [ ] Note 04's `ai_providers.api_key_enc` uses `Keyring.seal(purpose="ai_provider:<id>")`. *Note 04 tests use the shared helper.*
- [ ] `app.admin rotate-secret-key` and `reencrypt`. *Test: rotate, then decrypt with only the new key.*

**Phase 5: admin**

- [ ] Users and invites (`/api/admin/users`, `/invites`, reset links, revoke sessions, last-admin rule), registration modes, `ALLOW_INSECURE_HTTP` rule for a second account. *Tests: invite single use and expiry; fragment-only token; demoting or deleting the last admin → 409; second account over plain HTTP refused unless allowed.*
- [ ] `app/audit.py`, every action in §4.13, retention, `/api/admin/audit`, `/api/me/activity`. *Tests: each admin write leaves one row; `UPDATE audit_log` fails; no secret values in `details_json`.*
- [ ] Usage page and About page (secret-key source, rotation status, ignored identity headers, HTTPS). *Rendered in Playwright.*

**Phase 6: export, deletion, backups, docs**

- [ ] `/api/me/export.zip`, `DELETE /api/me`, admin delete, `vacuum`, `export-user`. *Tests: zip contains the five files, JSON validates against the documented shape, no key material; deletion cascades and the other user's data is untouched.*
- [ ] `docs/accounts.md`, `docs/privacy.md`, README, deployment and allowlist updates, release notes. *A new contributor can follow `docs/accounts.md` from an empty volume to two users with HTTPS.*

**Phase 7: proxy mode**

- [ ] `app/auth/proxy.py`, groups → role sync, auto-create switch, logout URL, start-up refusal for wide `TRUSTED_PROXIES`. *Tests: header from a trusted peer signs in; the same header from an untrusted peer is ignored and counted; role follows the admin group; documented Caddy + Authelia, authentik and `tailscale serve` examples tried once by hand.*

**Later (v0.4)**

- [ ] OIDC (decide Authlib 1.8.0 + itsdangerous vs own PKCE code), passkeys (webauthn 3.0.1) as a second factor or passwordless, optional SMTP for self-service reset, read-only sharing with a caregiver or dietitian (`shares(owner_user_id, grantee_user_id, scope, created_at, revoked_at)` and a `Principal(user, acting_for)` dependency), import of `export.json`.

---

## 7. How to re-verify

```bash
# Library versions, licences and upload dates
for p in cryptography fastapi starlette argon2-cffi pwdlib fastapi-users authlib webauthn; do
  curl -s https://pypi.org/pypi/$p/json | python3 -c 'import json,sys; d=json.load(sys.stdin); i=d["info"]; v=i["version"]; print(i["name"], v, min(f["upload_time"] for f in d["releases"][v]), i.get("license_expression") or i.get("license"))'
done

# Argon2id in the installed cryptography, and its OpenSSL
python -c 'from cryptography.hazmat.primitives.kdf.argon2 import Argon2id; import os; print(Argon2id(salt=os.urandom(16), length=32, iterations=2, lanes=1, memory_cost=19456).derive_phc_encoded(b"x"))'
python -c 'from cryptography.hazmat.backends.openssl.backend import backend; print(backend.openssl_version_text())'

# FastAPI route-tree and dependency behaviour: run tests/test_auth_coverage.py after every FastAPI bump
# Browser support (Sec-Fetch-Site, Clear-Site-Data): mdn/browser-compat-data http/headers/*.json
# NIST: https://pages.nist.gov/800-63-4/sp800-63b/authenticators/ (§3.1.1.2, §3.2.2), .../session/, .../aal/
# OWASP: Password Storage, Session Management, Authentication, CSRF cheat sheets (parameters change)
# Blocklist source: SecLists Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt (SHA-256 in the build script)
```

Prototype scripts used for the measurements and SQL checks (scratch, not committed):
`bench.py` (hash timings, interop, GIL), `proto.py` (password module, Fernet rotation, migration,
cascade), `depstest.py`/`depstest2.py` (FastAPI dependency caching and the coverage test).

---

## 8. Sources

* NIST SP 800-63B-4: [Authenticators §3.1.1.2, §3.2.2](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/) ·
  [Session management §5](https://pages.nist.gov/800-63-4/sp800-63b/session/) ·
  [AALs](https://pages.nist.gov/800-63-4/sp800-63b/aal/) ·
  [Final publication](https://csrc.nist.gov/pubs/sp/800/63/4/final)
* OWASP cheat sheets: [Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) ·
  [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) ·
  [Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) ·
  [CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
* Filippo Valsorda, [Cross-Site Request Forgery](https://words.filippo.io/csrf/) (2025-08-13; Go 1.25 `CrossOriginProtection`)
* WHATWG Fetch, [append a request `Origin` header](https://fetch.spec.whatwg.org/#append-a-request-origin-header) and CORS-safelisted request-headers
* MDN: [Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie) ·
  [browser-compat-data](https://github.com/mdn/browser-compat-data) (`Sec-Fetch-Site`, `Clear-Site-Data`)
* cryptography: [Key derivation functions (Argon2id, Scrypt, HKDF)](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/) ·
  [Fernet / MultiFernet](https://cryptography.io/en/latest/fernet/) · [PyPI](https://pypi.org/project/cryptography/)
* PyPI: [argon2-cffi](https://pypi.org/project/argon2-cffi/) · [argon2-cffi-bindings](https://pypi.org/project/argon2-cffi-bindings/) ·
  [pwdlib](https://pypi.org/project/pwdlib/) · [fastapi-users](https://pypi.org/project/fastapi-users/) ·
  [passlib](https://pypi.org/project/passlib/) · [Authlib](https://pypi.org/project/Authlib/) ·
  [webauthn](https://pypi.org/project/webauthn/) · [FastAPI](https://pypi.org/project/fastapi/) · [Starlette](https://pypi.org/project/starlette/)
* FastAPI: [OAuth2 + JWT tutorial (pwdlib, dummy hash)](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) ·
  [release notes](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/release-notes.md) (0.121, 0.122, 0.137, 0.142)
* Starlette: [release notes](https://github.com/Kludex/starlette/blob/main/docs/release-notes.md) (1.0.0, 1.6.0, 1.7.0)
* SQLite: [ALTER TABLE](https://www.sqlite.org/lang_altertable.html) · [PRAGMA secure_delete, foreign_keys, foreign_key_check](https://www.sqlite.org/pragma.html) ·
  [UPSERT](https://www.sqlite.org/lang_upsert.html)
* Authelia: [Trusted header SSO](https://www.authelia.com/integration/trusted-header-sso/introduction/) ·
  [Caddy integration](https://www.authelia.com/integration/proxies/caddy/)
* authentik: [Proxy provider headers](https://docs.goauthentik.io/add-secure-apps/providers/proxy/)
* Tailscale: [Serve identity headers](https://tailscale.com/kb/1312/serve)
* Authlib: [Starlette OAuth client](https://docs.authlib.org/en/v1.5.1/client/starlette.html)
* Have I Been Pwned: [Pwned Passwords range API](https://haveibeenpwned.com/API/v3#PwnedPasswords) ·
  SecLists: [repository (MIT)](https://github.com/danielmiessler/SecLists)
* api.data.gov: [Developer manual, rate limits](https://api.data.gov/docs/developer-manual/)
* GDPR: [Regulation (EU) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj) (Art. 2(2)(c), 9, 15, 17, 20)
* Sibling notes: [01](01-rootless-and-security.md) · [02](02-ios-pwa.md) · [03](03-barcode-and-photo.md) ·
  [04](04-optional-ai.md) · [05](05-personalized-targets.md) · [06](06-meal-guidance.md)

---

## 9. Security review (2026-10-05)

Reviewed together with notes [01](01-rootless-and-security.md), [03](03-barcode-and-photo.md) and
[04](04-optional-ai.md), against today's `app/main.py`, `app/foods.py` and `app/log.py`. The core
choices hold up: opaque split-token sessions, Argon2id with a dummy hash, write-only keys with
sealed context, router-level dependencies plus behavioural tests, 404 for "not yours", and the
custom-header CSRF layer. The required changes below close concrete bypasses.

### 9.1 Corrected in place

| Where | Was | Now |
|---|---|---|
| §4.4 `login_failures` | Primary key `username_norm`, the typed name in plaintext, for unknown names too. That contradicts §4.5 ("typed usernames of unknown accounts are never stored, since people sometimes type a password there"), and the table is in every backup. | Keyed by `name_mac` = HMAC-SHA256 under an HKDF-derived key. |
| §4.9 per-username row | "table capped at 10,000 rows, oldest first" | Eviction never removes a delayed row or one with ≥ 5 failures; otherwise an attacker flushes the victim's counter with 10,000 junk names and resets the delay. |
| §4.15 backups | "`SECRET_KEY` is not in the backup (by design)" | True only for `app.admin backup`. A volume-level backup contains an auto-generated `/data/secret.key`; shipped profiles mount `SECRET_KEY_FILE`. |

### 9.2 Findings and required changes

| ID | Severity | Finding | Required change |
|---|---|---|---|
| N1 | **High** | **DNS rebinding bypasses every CSRF layer** (note 01 §10 S1): the rebinding page is same-origin, so `Origin`, `Sec-Fetch-Site` and `X-Requested-With` all pass. Cookie mode limits it to unauthenticated routes (login guessing from inside the LAN, setup codes); `AUTH_MODE=none` and proxy mode lose everything. | Host allowlist from note 01 S1 before any auth logic. `AUTH_MODE=none` logs a WARNING at start-up if `ALLOWED_HOSTS` contains names and no `PUBLIC_URL` is set. |
| N2 | **High** | **Proxy mode trusts whatever the engine reports as the peer** (note 01 §10 S2): under pasta, every process on the host; under slirp4netns or rootless Docker, every client. Also: a local session cookie issued before a switch to proxy mode, `/api/auth/login` still answering in proxy mode (a password path around the IdP's MFA), and proxy usernames that collide with local ones. | `AUTH_MODE=proxy` requires `TRUSTED_PROXY_SECRET_FILE` (note 01 S2). In proxy mode `POST /api/auth/{login,register,reset,reauth}` answer 404, session cookies are ignored, and all `sessions` rows are deleted when the mode changes (stored in `meta.auth_mode`). Proxy identities never link to local accounts by name: if `username_norm` collides, answer 403 and audit `proxy.username_conflict`. Without `TRUSTED_PROXY_ADMIN_GROUP`, proxy-created users are always `user`. |
| N3 | **High** | **Lock-out as denial of service.** (a) When every client shares one peer address (N2), `LOGIN_IP_MAX_FAILURES=20` lets one attacker block login for everyone, and the instance-wide 60/min cap does the same anywhere. (b) Anyone who knows the admin's username (`ADMIN_USERNAME` defaults to `admin`) reaches the NIST 100-failure stop in about a day (≈ 90 attempts at the 15-minute cap), after which only the CLI recovers the only admin. | (a) Skip the per-IP layer when the client address is a configured proxy or gateway without a trusted `X-Forwarded-For` (log once). The global cap queues for up to 5 s instead of rejecting. (b) **Device cookies** ([OWASP](https://community.owasp.org/Slow_Down_Online_Guessing_Attacks_with_Device_Cookies)): after a successful login set `__Host-kh_device` (or `kh_device` on HTTP) = `user_id.nonce.HMAC(HKDF(SECRET_KEY, "device"), user_id‖nonce)`, `Max-Age` 1 year, `HttpOnly; SameSite=Strict`. A login for user U with a valid device cookie for U skips U's username delay and does not count toward the 100-failure stop; it has its own counter (10 failures → that device cookie is void). (c) `ADMIN_USERNAME` has no default: required with `ADMIN_PASSWORD_FILE`, chosen on the setup screen otherwise. |
| N4 | **High** | **Secrets echoed in validation errors.** Today's `_validation_error_handler` (`app/main.py`) returns each error's `input`. With v0.3 that sends a password back (a 129-character password at `/api/auth/login`), an API key (a key with a space at `PUT /api/me/keys/usda`) and setup codes, and any future logging of 400s writes them to disk. | Fields `password`, `current_password`, `new_password`, `api_key`, `token`, `code` are `SecretStr`. The handler drops `input` and `ctx` when the `loc` ends in one of those names, and for every path under `/api/auth/`, `/api/me/password`, `/api/me/keys`, `/api/me/ai`, `/api/admin/keys` and `/api/admin/ai-providers`. A logging `Filter` replaces every loaded secret value and any `Bearer \S+` with `[redacted]`; the `httpx`, `httpx2`, `httpcore` and `h11` loggers are pinned to WARNING whatever `LOG_LEVEL` says. Test: post known secrets to every such route with invalid bodies; neither the responses nor captured logs contain them. |
| N5 | **High** | **Cross-user leaks beyond the visible-foods predicate.** (1) `search_foods()` orders empty-query results by `MAX(created_at)` over **all** `log_entries` (`app/foods.py`, the `LEFT JOIN (SELECT food_id, MAX(created_at) … FROM log_entries GROUP BY food_id)`), so user B's list order shows what A ate recently. (2) `DELETE /api/foods/{id}` sets `hidden = 1` on a referenced food and deletes an unreferenced one outright; on a shared `usda`/`off` row that hides it from everyone, or deletes it and cascades away every other user's `user_food_links` row. (3) Note 03's GTIN lookup could return another user's custom food with the same barcode. (4) `DELETE /api/me/sessions/{id}` by selector. (5) Guidance `recents`/`often` (note 04). (6) The offline outbox (note 02 R5) replayed after a user switch writes A's entries into B's account. (7) A custom food inserted without `owner_user_id`. (8) The auth-coverage test reads `app.openapi()`, which omits routes declared with `include_in_schema=False`. | (1) The subquery gets `WHERE user_id = :uid`. (2) For shared rows, DELETE removes only the caller's `user_food_links` row (404 if none); `hidden` applies to `custom` rows; `food_is_referenced()` counts only the owner's entries and templates. (3) GTIN query: `(f.source = 'custom' AND f.owner_user_id = :uid) OR f.source IN ('off', 'usda')`. (4) `WHERE id = ? AND user_id = ?` on every session operation. (5) Guidance reads only the caller's log. (6) Replay only outbox items whose `user_id` equals the signed-in user's id; the server ignores any `user_id` in a body. (7) `BEFORE INSERT/UPDATE` trigger: `source = 'custom'` requires `owner_user_id IS NOT NULL`. (8) A grep test forbids `include_in_schema=False` under `app/` for `/api` routes (or the coverage test walks the router tree). Add (1)–(6) to `tests/test_isolation.py`. |
| N6 | Medium | **Cookie tossing and shared ports.** Cookies are isolated by neither scheme nor port ([RFC 6265 §8.5–8.6](https://www.rfc-editor.org/rfc/rfc6265#section-8.5)). Any plain-HTTP page on the same host (another homelab app on `:3000`, or a LAN attacker answering a plain-HTTP request) can set `kh_session=<attacker's session>`; if the HTTPS app reads that name, the victim logs meals into the attacker's account. On plain HTTP every service on that host or IP also receives the victim's `kh_session`. | Over HTTPS read **only** `__Host-kh_session`; over HTTP read only `kh_session`; logout expires both. `docs/accounts.md`: give the app its own hostname, and do not run other services on the same host name or IP over plain HTTP. |
| N7 | Medium | **Re-auth brute force with a stolen cookie.** `/api/auth/reauth` is limited only per IP. | Re-auth failures count toward the account's username delay; 5 consecutive failures revoke that session (audit `session.revoked_reauth`). |
| N8 | Medium | **`must_change_password` is enforced only by the UI.** | While set, every route except `GET /api/auth/status`, `POST /api/me/password` and `POST /api/auth/logout` answers `403 {"detail": "Choose a new password first", "password_change_required": true}`. |
| N9 | Medium | **Timing.** A user with `password_hash NULL` (proxy-created) returns from `verify_password()` without hashing; status checks (`locked`, `disabled`) placed before the verify are visible as fast answers. | Every local login runs exactly one Argon2id verify (the user's hash, or `DUMMY_HASH` when the user is unknown, has no local password, or is disabled or locked) before any status-dependent branch, then returns the same generic 401. The setup code is compared as `sha256` of the normalised code (uppercase, dashes removed) with `hmac.compare_digest`. |
| N10 | Medium | **Resource isolation for reads.** `SameSite=Lax` sends the cookie on same-site requests, so a compromised sibling app (`grafana.home.example`) can trigger `GET /api/me/export.zip`, spend shared USDA quota through `GET /api/foods/usda/search`, or probe responses by timing. | For every `/api/*` request, whatever the method: reject `Sec-Fetch-Site: cross-site` and `same-site` with 403 (HTTPS only; the header is absent on plain HTTP). Top-level navigations to `/` stay allowed. |
| N11 | Medium | **Backups and erasure.** `kidney.db.pre-v3.bak` keeps every v0.2 meal indefinitely; deleting the account does not reach it. | Delete it automatically 30 days after a successful migration (or `python -m app.admin purge-pre-v3-backup`); Admin → About shows that it exists; `docs/privacy.md` says so. |
| N12 | Low | **"No impersonation" is a UI property.** An admin can issue a reset link for any account and sign in as that person. | Say so on About & privacy. Completing an admin-issued reset revokes sessions (already) and shows "Your password was reset by an admin on …" at the next sign-in; the event is in `/api/me/activity`. |
| N13 | Low | **Rate limits are scattered across notes.** | One registry in `app/ratelimit.py`: login, setup, register, reset, reauth (§4.9 plus N3, N7); `PUT /api/me/keys/*` with `test` 10/h per user (key-checking oracle); AI probes 5/h per user (note 04 A5); `GET /api/me/export.zip` 10/h; `POST /api/foods/barcode` 60/h per user plus the server bucket (note 03); USDA and AI daily quotas. All in memory, single process. |

### 9.3 Checks that passed

* Fetch's `Origin` rule (F4) is right: a same-origin `fetch()` in its default `cors` mode sends the
  real origin even with `Referrer-Policy: no-referrer`; `mode: 'same-origin'` would send `null`.
* `Sec-Fetch-Site` is only sent to potentially trustworthy URLs
  ([Fetch Metadata](https://www.w3.org/TR/fetch-metadata/)), so the custom header is what protects
  plain-HTTP LAN setups.
* Split-token sessions with a hashed verifier, rotation on login, role and password change,
  fragment-only invite tokens, and the sealed `{purpose, owner}` envelope are sound.

### 9.4 Implementation checklist additions

- [ ] `login_failures.name_mac`, eviction rule, device cookies, per-IP skip for gateway addresses, `ADMIN_USERNAME` without default (N3, §9.1).
- [ ] Validation-handler redaction, `SecretStr`, log redaction filter, pinned HTTP-client loggers (N4).
- [ ] Isolation fixes (1)–(8) of N5, each with a two-user test.
- [ ] Cookie-name rule per scheme (N6); reauth counter (N7); server-side `must_change_password` (N8); uniform verify path (N9); resource isolation for `/api/*` (N10).
- [ ] Proxy-mode hardening: secret required, auth endpoints 404, sessions purged on mode change, collision rule (N2).
- [ ] Pre-v3 backup expiry (N11); About & privacy wording (N12); `app/ratelimit.py` (N13).

### 9.5 Sources checked for this review

[RFC 6265 §8.5–8.6](https://www.rfc-editor.org/rfc/rfc6265#section-8.5) ·
[OWASP device cookies](https://community.owasp.org/Slow_Down_Online_Guessing_Attacks_with_Device_Cookies) ·
[Fetch Metadata](https://www.w3.org/TR/fetch-metadata/) ·
[uvicorn `proxy_headers.py`](https://github.com/encode/uvicorn/blob/master/uvicorn/middleware/proxy_headers.py) ·
[passt(1)](https://passt.top/passt/plain/passt.1) ·
[CVE-2021-20199](https://nvd.nist.gov/vuln/detail/CVE-2021-20199) ·
repository code: `app/main.py` (`_validation_error_handler`), `app/foods.py` (`search_foods`, `delete_food`), `app/log.py` (CSV writer).
