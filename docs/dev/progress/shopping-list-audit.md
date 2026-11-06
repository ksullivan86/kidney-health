Status: complete

# Shopping list audit continuation

Base: main `bf35adb` (0.22.0), confirmed against GitHub. Branch: `fix/shopping-list-request-context`.
Read the prior security and screen reliability audits; their fixes are already on main.
Scope this pass: list-sync and Instacart shopping sheets. Create a PR; do not merge or deploy.

Code review found unguarded preview responses in both sheets: opening week B while A loads
can show A's foods under B's dates. Send completions can also act on a reopened sheet;
Instacart resets its busy flag on open, allowing a second send while the first is pending.
Status reads can unhide a shopping button after an empty week hides it.

Done: 20 Node cases on the real view scripts. Baseline: 5 pass, 15 fail. Fixed: 20 pass.
Both sheets now guard previews and send completions by opening; the send lock survives
reopening and checkbox changes. Shopping buttons discard status replies for older renders.
Updated ARCHITECTURE, CHANGELOG, docs for both services and the planning handbook.

Chromium: `tools/e2e/shopping_late_replies.py`, 30 checks passed at 375 light and 1280 dark.
Actual browser requests carry the current week's dates and ids; held replies never go to
another service. Node parity vectors and all 26 Node test files pass. Ruff is clean;
handbook generated-file check and strict MkDocs build pass.

Final verification:
- Full pytest: 7,332 passed, 2 skipped; the sole failure was the checkout missing the
  upgrade harness's historical commit `9ef9151`. Fetched its full SHA from GitHub;
  `tests/test_e2e_tools.py::test_upgrade_starting_points_exist` then passed.
  No source change was needed. All 7,333 tests therefore passed across that run and rerun.
- Existing Chromium walks: Instacart 25/25; list sync and recipes 42/42.
- New Chromium walk: 30/30; Node regressions 20/20; all 26 Node test files and parity pass.
- Ruff, handbook generated-file check, strict handbook build, diff whitespace check pass.
- The published commit's tree matches the tested local tree exactly.

The PR branch is published for the owner's other session. Do not merge, enable auto-merge,
bump the version or deploy. No API, schema, clinical rule or demo-engine change.

Continue the audit in a separate branch. This pass covers shopping-sheet request ordering;
it is not a claim that the whole app is free of bugs. The earlier security audit's owner
decisions in `security-review-recent.md` are still available for the other session.

Environment: app's Python is `.venv/bin/python`; system `python3` has Playwright.
Shell socket operations need the command's network permission, even for TestClient's
local event loop. Without it, the first API fixture hangs. Restarted full pytest with that
permission; the guidance API subset passes (51 tests). Use connected GitHub tools to
publish changes. Check logs under `/workspace/work/shopping-audit/`.

Reproduce:

    .venv/bin/python -m pytest
    node --test tests/js/shopping_list_context.test.mjs
    node --test tests/js/*.test.mjs
    node tests/js/run_vectors.mjs
    python3 tools/e2e/shopping_late_replies.py
    python3 tools/e2e/instacart.py
    python3 tools/e2e/lists_recipes.py
