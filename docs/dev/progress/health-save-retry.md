Status: complete

Base: main 84330f3, refreshed all branches before starting. Claude bbc9629 does not change the
weight/BP/lab save flows. Own branch test/health-save-retry; no PR/deployment.

The reliability roadmap still needs explicit failed-server-save and successful-retry checks for
weight, BP and Labs. Existing body.py covers weight offline but cancels rather than retrying;
its normal BP saves and journey.py's normal lab saves do not exercise a 500 followed by retry.
Add an isolated local-server browser walk. Compare sent bodies and stored row counts, keeping
the entered fields. Only change production code if a real failure is found.

Validation: 30 browser checks pass at 375px/light and 1280px/dark. Each of the three forms keeps
its entered fields after a 500, stores nothing on failure, accepts retry (201), sends identical
request bodies across both attempts, and stores exactly one row. No production bug found in these
flows and no app code changed. Report /tmp/kidney-health-save-retry-verified-20261029/report.json.
The first harness run omitted required body-list start/end query parameters; corrected the test
readback and reran all cases. E2E-tool pytest: 35 passed. Ruff and git diff --check pass.

Full main verification also finished: 6533 passed, 2 skipped, existing warning only; see
current-main-validation.md. The isolated validation worktree was clean and has been removed;
its full log remains in /tmp. Ready on test/health-save-retry for Claude. No PR/deployment.
