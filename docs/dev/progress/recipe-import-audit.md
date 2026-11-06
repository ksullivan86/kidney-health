Status: complete

# Broader audit: recipe import drafts

PR: https://github.com/ksullivan86/kidney-health/pull/146
Base main `bf35adb`; branch `fix/recipe-import-draft-lifecycle`.
Separate from shopping PR #144 and device lifecycle PR #145.
The user's other session reviews and merges. No PR was merged or auto-merge enabled.

## Confirmed and fixed

- An older capability/parse response could reset a reopened form and discard its new typing.
- A pending parse blocked the new opening; its late error could overwrite that opening's button state.
- A completed save could close the newer sheet and invoke its callback rather than the original one.
- Editing a review while Save waited could enable its button again.
- Searching two ingredient rows used one global counter and discarded one row's valid results.
- An abandoned ingredient search could show an error over the current choice.

Each opening now owns its state and callback. Late reads affect only their own opening.
An issued save still completes and refreshes its original caller, while the newer form stays
intact. Fields and Back stay disabled during Save; failure restores the same checked draft.
Each ingredient search has its own sequence and checks that its input is still mounted.
No parsing, amount calculation, warnings, nutrition, API, schema or configuration changed.

## Validation

- Full pytest: **7,333 passed, 2 skipped**, with only the two existing handbook-source warnings.
- Real-script Node regressions: **14/14**; the original code fails **11**, with 3 existing normal paths passing.
- New Chromium walk `recipe_import_late_replies.py`: **20/20** at 375 light and 1280 dark.
  It holds real local parse/search/save responses, verifies the original callback and new typing,
  and checks that the recipe exists exactly once in the real server's saved meals.
- Existing `lists_recipes.py` browser walk: **42/42**, including the demo.
- All Node test files, parity vectors, Ruff, generated handbook check, strict MkDocs build and whitespace checks pass.
- CodeQL, lint, handbook, JS parity and iOS CI checks passed on the functional commit.
- Published source trees are checked against the tested local tree.

## Handoff

Review with PR #145 for the broader audit; each branch is independently based on main.
Combine their CHANGELOG Unreleased entries when merging. Do not merge, deploy or bump the
version in this session. The pinned base-image vulnerability scan blocker is documented in
PR #144 and the device audit note; no image pins were changed here.

Commands:

    python -m pytest
    node --test tests/js/recipe_import_context.test.mjs
    node --test tests/js/*.test.mjs
    node tests/js/run_vectors.mjs
    python3 tools/e2e/recipe_import_late_replies.py
    python3 tools/e2e/lists_recipes.py

Worktree: `/workspace/work/recipe-audit-src`; logs: `/workspace/work/recipe-audit/`.
The environment's app Python is `/workspace/kidney-health/.venv/bin/python`; system Python
has Playwright. The browser runs used the installed Chromium and a fresh local DATA_DIR.
