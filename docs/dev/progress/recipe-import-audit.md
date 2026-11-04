Status: in progress

# Broader audit: recipe import drafts

Base main `bf35adb`; branch `fix/recipe-import-draft-lifecycle`, separate from the device
lifecycle changes and PR #144. The user's other session reviews and merges; do not merge.

Recipe import shares mutable state across openings. Status/parse replies can replace a
new draft, and a late save closes the current sheet and calls its newer callback. Ingredient
search uses one global counter, so searching two independent ingredient rows drops one
row's answer.

Confirmed: the original script fails 11 of the 14 controlled-promise cases; normal parse
failure/retry, save failure/retry and current search failure already worked. All 14 now pass.
Each opening has its own state; late reads are dropped, save callbacks are captured, fields
freeze during Save, and each ingredient search has a separate sequence and mounted-input guard.
Updated ARCHITECTURE, recipe-import guide, planning handbook and CHANGELOG.
Browser: `recipe_import_late_replies.py` passes 20 checks at 375 light and 1280 dark,
holding real local parse/search/save responses. It verifies the meal is saved once, the
new sheet stays open, and only the original callback runs. The existing lists/recipes
walk passes 42/42. Ruff, Node tests, vectors and strict handbook build pass.
Focused pytest: 702 passed with one static-source expectation needing the new busy label;
updated that assertion. Full pytest is running. Next: finish checks and publish the PR.
