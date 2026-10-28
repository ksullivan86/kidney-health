Status: in progress (2026-10-28): part A (server) being built.

# Two-step sign-in (design note 17)

## Plan

* Part A (server, one PR): `app/auth/totp.py` (RFC 6238, recovery codes), schema step 22 (`m022_totp.py`), sign-in with `code`,
  reset links, `/api/me/totp*`, `DELETE /api/admin/users/{id}/totp`, `two_step` in the admin list, audit actions,
  `crypto.ENCRYPTED_COLUMNS`, CLI `remove-two-step`, tests, OpenAPI, ARCHITECTURE, docs/security.md, CHANGELOG.
* Part B (screens, second PR): sign-in code field, Settings block with QR (vendored QR library), admin People, demo mock, handbook,
  Chromium checks.

## Done

* Part A code (verified: `tests/test_totp.py` 29 tests, `tests/test_migration_m022.py` 3, plus the auth, admin CLI, migrations,
  OpenAPI and security test files):
  * `app/auth/totp.py` (RFC 4226/6238, recovery codes, storage helpers), `app/migrations/m022_totp.py`.
  * Sign-in: `LoginBody.code`, `_second_step` in `app/auth/routes.py` (no code: 401 not counted; wrong: `_login_failed(via="code")`);
    reset links answer `{"user": null, "totp_required": true}` when it is on.
  * `app/auth/totp_api.py` (`/api/me/totp`, `/setup`, `/enable` with limit `totp_enable` 10 per 15 min, `/recovery-codes`, DELETE).
  * `DELETE /api/admin/users/{id}/totp`, `two_step` in the admin list; CLI `remove-two-step`; audit actions `totp.*`;
    `crypto.ENCRYPTED_COLUMNS`; OpenAPI lists (`CONFLICT`, `RATE_LIMITED`) and `docs/api/openapi.json` regenerated.

## Next

* Part A docs: ARCHITECTURE (accounts section, route table, schema step 22, audit actions), docs/security.md, CHANGELOG, ROADMAP,
  self-hosting handbook page for the CLI. Then full pytest, PR.
* Part B as planned.

## Reproduce

```bash
python -m pytest -q tests/test_totp.py tests/test_migration_m022.py
```
