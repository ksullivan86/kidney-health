Status: fix published; full-suite verification in progress

# Password reset email audit

Branch: `audit/password-reset-review`, based on main `01f5298` (0.23.0 plus container updates).
Worktree: `/workspace/work/password-reset-audit-src`.
PR: https://github.com/ksullivan86/kidney-health/pull/175 (draft; do not merge).

## Checked

- Refreshed main on 2026-11-11. Release #170 already fixes both older handoff follow-ups:
  Ask's overlapping retry and the shared `sessions.is_live` rule. Do not report them as open bugs.
- Read repository instructions, relevant architecture/auth code, design note 34, and the original email tests.

## In progress

- Confirmed: `/api/auth/forgot` reads its target before taking the write lock, so a concurrent address
  removal/change, password change or disable can finish before the token is inserted. That leaves a
  new live reset token outside the other request's revocation. Deletion instead causes a foreign-key 500.
- `tests/test_reset_email_concurrency.py` holds the first target read while another real request
  commits or waits for the lock. Corrected baseline: **5 failures, 2 passes** on unchanged main;
  failures are four live-token assertions and the deletion 500. The first harness run had a wrong
  `/api/me` response key and is not reproduction evidence.
- Fix: use the existing auth `begin_immediate` helper before reading the target, roll back the
  no-target path, and commit before scheduling SMTP as before.
- **58 focused checks pass**, including all 7 new overlap cases, existing email routes/UI checks,
  Ask trust lifecycle regressions and the shared session-time rule. Ruff, JS parity, OpenAPI and
  generated handbook checks pass. The docs and changelog explain revocation of in-progress requests.
- **754 expanded auth/isolation/export/migration/handbook checks pass**, with two existing citation warnings.
  Strict handbook build passes. Combined with the focused run, 812 checks pass.
- Full local pytest is still running (`exec` session 28444, log below). CI run
  https://github.com/ksullivan86/kidney-health/actions/runs/43101071193 has all three Python suites still in progress;
  lint, parity, handbook, Swift, iOS and workflow-security jobs passed at the last check. Do not call full verification green yet.
  Logs: `/workspace/work/password-reset-{baseline,focused,expanded,full,parity,handbook}.log`.

## Reproduce

```sh
TMPDIR=/workspace/work/pytest-scratch /workspace/kidney-health/.venv/bin/python -m pytest tests/test_reset_email_concurrency.py tests/test_reset_email.py tests/test_reset_email_ui.py tests/test_session_is_live.py tests/test_ask_trust_lifecycle.py -o addopts='' -q
node tests/js/run_vectors.mjs
```

The new test file alone reproduces 5 failures / 2 passes against main `01f5298`.
The full suite is running from this worktree with `python -m pytest -o addopts='' -q`.

## Resume / limits

- Keep progress and regression evidence here; push a reviewable PR, never merge it.
- Use `/workspace/kidney-health/.venv/bin/python` and `TMPDIR=/workspace/work/pytest-scratch`.
- Git/network and local socket tests need an approved command outside this environment's sandbox.
- Latest documentation handoff is PR #168; check its live state before changing it.
- The separate resumed menu-plan fix is PR #176, branch `audit/menu-plan-editor-lifecycle`, worktree
  `/workspace/work/menu-plan-audit-src`. Its own progress note records verification; do not combine the branches.
