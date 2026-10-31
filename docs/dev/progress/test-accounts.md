Status: in progress (2026-10-31)

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

(nothing yet)

## Decisions

(added as they are made)

## Commands

* `PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
* `$PY -m pytest -p no:cacheprovider --basetemp=<scratchpad>/pt-ta tests/test_test_accounts.py` (delete the basetemp after)
* `$PY tests/data/gen_settings_vectors.py --check`, `node tests/js/run_vectors.mjs`, `$PY scripts/gen_openapi.py --check`
