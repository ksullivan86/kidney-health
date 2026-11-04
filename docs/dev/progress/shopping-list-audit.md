Status: in progress

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
handbook generated-file check and strict MkDocs build pass. Full pytest is running.

Next: finish pytest, run the existing service browser walks, publish the PR and leave it open.

Environment: app's Python is `.venv/bin/python`; system `python3` has Playwright.
Shell socket operations need the command's network permission, even for TestClient's
local event loop. Without it, the first API fixture hangs. Restarted full pytest with that
permission; the guidance API subset passes (51 tests). Use connected GitHub tools to
publish changes. Check logs under `/workspace/work/shopping-audit/`.
