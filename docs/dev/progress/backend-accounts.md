Status: complete

# backend-core accounts (M1)

Scope: note 07 §0, §4.4–§4.10, §4.12–§4.17, §6 (v0.3 phases), §9 review items, and the identity items
of note 01 §10. Ports used for live checks: 8120–8129.

## Done (verified)

* `app/migrations/m003_accounts.py` (from the previous attempt, reviewed, unchanged): schema v3,
  user 1 placeholder (`pending_setup`, `username_norm='#setup'`), owner columns + back-fill +
  NULL-blocking triggers, `kidney.db.pre-v3.bak`. Tests: `tests/test_migration_v3.py`.
* `app/auth/` package: `clock`, `models` (User), `passwords` (Argon2id/scrypt, gate, dummy hash),
  `policy` (+ `password-blocklist.txt.gz`, built by `scripts/build_password_blocklist.py`),
  `sessions`, `throttle`, `tokens`, `ratelimit`, `errors`, `context`, `accounts`, `proxy`, `deps`,
  `bootstrap`, `housekeeping`, `routes` (/api/auth), `me` (/api/me), `admin_api` (/api/admin),
  `schemas`. `app/account.py` (export zip, delete). `app/admin.py` account commands.
* Scoping in `foods.py`, `log.py`, `meals.py`, `profile.py` (user_profiles), USDA via
  `credentials.resolve()`, CSV formula escaping, `/healthz` counts builtin foods only.
* `app/main.py`: Basic auth removed; `auth.install()`; bootstrap in lifespan; version 0.3.0.dev0.
* Tests: `test_auth.py`, `test_auth_coverage.py`, `test_auth_modes.py`, `test_isolation.py`,
  `test_passwords.py`, `test_settings_api.py`, `test_export_delete.py`, `test_migration_v3.py`,
  CLI tests in `test_admin_cli.py`; existing tests moved to signed-in fixtures (`conftest.py`).
* Docs: `ARCHITECTURE.md` "M1 API", `docs/accounts.md`, `docs/privacy.md`.
* Live check: uvicorn on 127.0.0.1:8121, setup code from the log, setup, foods, log, invite,
  export.zip, logout (Clear-Site-Data, both cookies expired), CLI list-users. Server stopped.

## Reproduce

```
python -m pytest -q            # whole suite, no network
node tests/js/run_vectors.mjs  # rules parity (unchanged by this work)
python -m pyflakes app/auth app/account.py
```

## Decisions

See the final report of the run; the main ones are also in `ARCHITECTURE.md` "M1 API":
blocklist size (10,000 most common NCSC entries ≥ 8 chars, stored in `app/auth/`), `APP_PASSWORD`
import uses `ADMIN_USERNAME` or `admin`, proxy role sync leaves the role alone when the groups header
is absent, export path is `/api/me/export.zip` (note 07), invites refused in `closed` mode,
`POST /api/admin/users` creates a `pending_setup` account with a setup link.

## Follow-ups for other owners

* Frontend: sign-in/setup/invite/reset/settings screens; mock twin of `/api/auth/status`
  (`auth_mode: "none"`) and of the new 409 for `PUT /api/foods/{id}` on `usda` rows.
* M2: register `food.off_enabled` (setup accepts `off_enabled`), use `app.auth.ratelimit` for
  `ai_probe`/`barcode`, `foods.access_clause()` for GTIN lookups, `lab_results`/`ai_audit` are
  picked up by the export automatically when they have a `user_id` column.
