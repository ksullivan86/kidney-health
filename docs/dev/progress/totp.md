Status: in progress (2026-10-29): "Admins must use two-step sign-in" (auth.require_two_step_admins) built; full pytest, then PR.

# Two-step sign-in (design note 17)

## Plan

* Server: `app/auth/totp.py` (RFC 6238, recovery codes), schema step 22 (`m022_totp.py`), sign-in with `code`,
  reset links, `/api/me/totp*`, `DELETE /api/admin/users/{id}/totp`, `two_step` in the admin list, audit actions,
  `crypto.ENCRYPTED_COLUMNS`, CLI `remove-two-step`, tests, OpenAPI, ARCHITECTURE, docs/security.md, CHANGELOG.
* Screens (same PR): sign-in code field, Settings block with QR (vendored QR library), admin People, demo mock, handbook,
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

* Screens (one PR with the server, so the docs never name a missing button): `js/views/two_step.js` (Settings block; QR code from the
  vendored `qrcode-generator` 2.0.4 ES module, a new `qrcode` group in `scripts/vendor_barcode.py`), the login code field and reset-link
  handling in `js/views/auth.js` and `index.html`, the People badge and removal in `js/views/settings.js`, demo answers in
  `js/mock/auth.js`, CSS in `css/settings.css`. Verified: `tools/e2e/two_step.py` 36 checks (decodes the drawn QR with the vendored
  barcode reader), `tests/test_two_step_ui.py`, `tests/test_vendor.py`.
* Docs: ARCHITECTURE, docs/accounts.md, docs/security.md, handbook settings-and-keys + self-hosting pages, NOTE17 source, CHANGELOG,
  ROADMAP, tools/e2e/README.md.

## Next

* Full pytest, then the PR; merge when green if the owner asks.

## Reproduce

```bash
python -m pytest -q tests/test_totp.py tests/test_migration_m022.py tests/test_two_step_ui.py tests/test_vendor.py
python tools/e2e/two_step.py
```
