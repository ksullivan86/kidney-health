Status: complete (2026-10-31)

# Test accounts (`tester`, `tester-helper`), Send feedback, Reset

Owner's ask and agreed design: docs/dev/progress/0.14-plan.md ("Test account: build after the Care team"). Migration step 28.
Branch: this helper's worktree branch (commit locally, no push; the owner merges). Started from `next-8`.

## Plan

1. m028 (users.is_test_account, feedback table, never-admin trigger); User.is_test_account; Me.test_account.
2. Settings `test_accounts.enabled` (TEST_ACCOUNT_ENABLED), `test_accounts.ai` (TEST_ACCOUNT_AI); env-only
   TEST_ACCOUNT_PASSWORD_FILE (TEST_ACCOUNT_PASSWORD refused). JS registry twin + settings vectors.
3. app/test_accounts.py: sync (make / enable / disable), reset, seed (port of mock/seed.js), guards.
4. app/feedback.py: /api/feedback (testers), /api/admin/feedback (+ CSV), /api/admin/test-accounts (+ reset).
5. Hooks: start-up, first-run setup, admin settings change, People (never admin), OIDC groups, Care team, AI, own password.
6. CLI `reset-test-accounts`. 7. Tests. 8. UI (feedback.js, header button, sheet, admin parts). 9. OpenAPI. 10. Docs.

## Done

1. Server side (commit "server side"): m028, settings + JS twin + vectors, app/test_accounts.py (sync/reset/seed port),
   app/feedback.py, hooks (start-up, setup, settings PATCH, People, OIDC groups, Care team, AI, own password, TOTP, delete me),
   CLI `reset-test-accounts`. tests/test_test_accounts.py 26 pass; isolation matrix has `feedback`; OpenAPI regenerated.
   Ran: test_care_team, test_sharing(_security), test_oidc, test_ai_routes, test_ai_routing, test_totp, test_export_delete,
   test_admin_page, test_auth_hardening (383 passed); auth coverage, migrations, admin CLI, settings, compose env, meta, auth.
2. UI: js/views/feedback.js (sheet + admin parts), header button (data-test-only), sheet markup in index.html, sw.js, CSS,
   settings.js (group, badge, admin parts, who line, activity labels), auth.js. tests/test_test_accounts_ui.py; admin_frame
   node test updated; tools/e2e/test_accounts.py 34/34 PASS (system python3, port 8094).

3. Docs: note 26, docs/accounts.md (Test accounts + CLI), docs/deployment.md row, deploy/.env.example, compose, quadlet,
   k8s examples (password as a secret file), handbook self-hosting/users-and-keys (+ NOTE26 source, rebuilt sources pages),
   ARCHITECTURE.md (step 28 row, section, CLI), CHANGELOG Unreleased, docs/test-the-full-app.md, README + docs/README links.
   Checked: handbook content, compose env, deploy, research notes tests; ruff; OpenAPI and settings vectors --check.

4. Full run: `python -m pytest` 6891 passed, 2 skipped (26 min, no network). `node tests/js/run_vectors.mjs` and
   `node --test tests/js/*.test.mjs` (172) pass; ruff clean; OpenAPI and settings vectors `--check` pass;
   `python3 tools/e2e/test_accounts.py` 34/34.

## For the owner to decide

* Display names Sam and Jo; the helper sees all four areas. Easy to change in app/test_accounts.py (DISPLAY, HELPER_AREAS).
* Feedback limits (2,000 characters, 20 an hour, 50 a day, 5,000 kept).
* docs/dev/progress/0.14-plan.md still lists the test account as a plan; not edited here (shared file).

## Decisions

* Display names: tester is "Sam" (as the demo), tester-helper is "Jo". The helper sees all four areas as a Care helper.
* Password: only TEST_ACCOUNT_PASSWORD_FILE (TEST_ACCOUNT_PASSWORD stops the start, like OIDC_CLIENT_SECRET). Read when the
  accounts are made, at start-up and on Reset, so a changed file applies after a restart. Checked against the policy for
  both names. A missing or weak file: nothing made, the reason logged and shown in Server administration → Test accounts.
* Only with AUTH_MODE=local, and only after the first admin exists (start-up, first-run setup and the settings PATCH sync).
* Reset deletes both users (cascade) and makes them again: new ids. Feedback rows keep the text username (user_id SET NULL),
  so the admin keeps them; the fresh account sees none. One activity row `test_accounts.reset`.
* Shared account protections: no password change, no two-step sign-in, no delete-my-account, no admin reset link or
  "must change password" for a test account. Locked or disabled ones are enabled again at start-up while the switch is on.
* AI: `test_accounts.ai` off makes every AI resolve "disabled" for a test account and /api/ai/* 404 (ai_on_for).
* Care team: test and real accounts never meet: invite by name answers as for an unknown name, links are the generic 404,
  rows filtered from both lists, the share check 404s. Sharing must be on (SHARING_ENABLED) for the Care team part.
* Feedback limits: 2,000 characters a box, 20 an hour (rate limit), 50 a day per account, 5,000 kept (then 409; admins
  "Delete done"). The server adds the app version (FastAPI app version) and the time.
* Demo: feedback.js is data-preview="omit"; with ?mock=1 the admin parts and the Test accounts settings group are hidden.

## Commands

* `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
* `$PY -m pytest -p no:cacheprovider --basetemp=<scratchpad>/pt-ta tests/test_test_accounts.py` (delete the basetemp after)
* `$PY tests/data/gen_settings_vectors.py --check`, `node tests/js/run_vectors.mjs`, `$PY scripts/gen_openapi.py --check`
