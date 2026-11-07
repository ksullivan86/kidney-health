# Progress: password reset by email (role: password-reset-email)

Status: complete (merged into 0.23.0 by the integrator)

Branch: worktree-agent-a2f49c0ffcd44efdb (origin/main + origin/claude/adoring-sagan-th5swr, fast-forwarded). Do not push, no PR,
no version bump.

## Done (and how it was checked)
1. Schema step 34 `app/migrations/m034_reset_email.py`: `users.email`, `users.email_confirmed_at`, unique index on confirmed
   addresses, `email_tokens`. `tests/test_migration_m034.py`.
2. Config `app/config.py` `EmailEnv` (EMAIL_ENABLED, SMTP_HOST/PORT/SECURITY/USERNAME/PASSWORD_FILE/FROM/TIMEOUT_S) with start-up
   refusals. `tests/test_reset_email.py::test_start_up_*`.
3. `app/mail.py`: address check, three letters, `Mailer.send` (deadline) and `send_later`.
4. `app/auth/email_api.py`: `/api/me/email` GET/PUT/DELETE, `/api/auth/email/confirm`, `/api/auth/forgot`, `/api/admin/email/test`;
   `/api/auth/status.email_reset`; admin users `email_confirmed`, `reset_link.via`; about `email`; reset `via: email_link`; export.
   Daily purge of old confirmation links.
5. UI: sign-in Forgot button + `forgot` screen + `#/confirm-email/<token>`; Settings email block; admin about row + test button.
6. Demo twin `js/mock/auth.js` (+ export.js); vectors `tests/data/email_vectors.json` (`gen_email_vectors.py`), run_vectors group.
7. Docs: note 34, accounts, deployment, security, network-allowlist, deploy templates (compose, .env, quadlet, k8s), handbook
   (settings-and-keys, configuration, users-and-keys, privacy, first-setup, index; NOTE34 source), ARCHITECTURE, CHANGELOG, ROADMAP.
8. Chromium walk `tools/e2e/reset_email.py`: 25 PASS.

## Commands
- `python -m pytest -q -p no:cacheprovider -o addopts="" tests/test_reset_email.py tests/test_reset_email_ui.py tests/test_migration_m034.py`
- `node tests/js/run_vectors.mjs`, `node --test tests/js/*.test.mjs`, `ruff check .`, `python scripts/gen_openapi.py --check`,
  `python scripts/build_handbook.py --check`, `python tests/data/gen_email_vectors.py --check`
- `cd tools/e2e && python reset_email.py`

## Decisions
- Confirmation tokens live in their own table `email_tokens` (auth_tokens.purpose has a CHECK that only allows setup/invite/reset).
  Each token is bound to the address it was sent to.
- Unique index covers confirmed addresses only, so nobody can block another person's address by typing it unconfirmed.
- Forgot: per-IP limit answers 429; the per-name limit is silent (same 202) and counts any typed name.
- Forgot sends in the background (does not wait for SMTP), so the answer time does not depend on the account.
- Removing an address needs no re-auth (the brief asked re-auth only for set/change).
- The demo confirms an address at once (it sends nothing) and says so.
- Test email failure answers 502 with a plain reason.

## Next
- Full suite result; then mark complete.
