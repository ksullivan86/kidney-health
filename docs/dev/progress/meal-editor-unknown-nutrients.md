Status: complete

Base: main 84330f3; refreshed all branches, Claude bbc9629 has no editor-preview changes.
Own branch fix/meal-editor-unknown-nutrients; no PR/deployment.

Further audit: saved-meal list and Fit sheet fixes do not cover the New/Edit saved meal preview.
renderMealTotals uses `(it.per[key] || 0)` and prints exact numbers, so opening a saved meal that
correctly says "not listed" in Plan shows 0 in the editor. Track missing counts for the actual
edited ingredients and scale only known amounts by Makes. Keep known zero and empty-editor zero.

Fix: count missing values across the current edited ingredients, distinguish none/partial/known-zero,
and divide only known totals by Makes. Reuse the compact unknown-value style, with missing counts
in tooltip and accessible text. Removing ingredients recalculates completeness.

Validation: 8 Node cases pass (5 failed on main). Focused pytest: 638 passed, existing unused-source
warning only. Chromium reliability: 25 passed, including editor missing/partial values, Makes,
phone-sheet overflow, failed save preserving note/Makes, unchanged stored meal after failure,
and successful retry of the same meal. Report /tmp/kidney-meal-editor-verified-20261029/report.json.
Node parity vectors, Ruff, JavaScript syntax, demo build and git diff --check pass.

Ready on fix/meal-editor-unknown-nutrients for Claude to review/cherry-pick. No PR/deployment.
Main's independent full-suite log remains
/tmp/kidney-current-main-full-suite.log (84330f3, separate worktree).
