Status: complete

# Progress: unknown values in swaps and the fit sheet (ROADMAP item 2, second part)


Branch `worktree-agent-aec7bcc7cd9e8f4d1` (local only, never pushed). Continues the WIP commits cbf83f0 and a66660f.

## Done
* Merged `claude/adoring-sagan-th5swr` (PR 119 head); conflicts in ARCHITECTURE.md, docs/accounts.md, handbook
  settings-and-keys.md and tools/e2e/reliability.py were only additions from that branch, taken as they are (f62c30c).

* Old vs new: a copy of the tree with the 9 feature files from 2165c19 (before the WIP) fails 13 of the 107 tests below
  (and 8 of 132 JS vector checks); this tree passes 107 of 107 (`-o addopts=""` prints the count).
* Docs: ARCHITECTURE.md (guidance meals paragraph), docs/guidance.md (swaps, recipes that fit, treating a low), handbook
  app/guidance.md and app/planning-and-menus.md, CHANGELOG Unreleased, ROADMAP item 2 marked done. Docs tests: 677 passed.

* Reconciled with two branches from the owner's other assistant (coordinator's request):
  * `origin/fix/meal-editor-unknown-nutrients` fe69c16 (New/Edit saved-meal preview): no overlap with this work, cherry-picked
    as is (a47144e, author kept); only the ROADMAP line was merged by hand. Its Node test: 8 pass.
  * `origin/fix/recipe-fit-unknown-nutrients` 3a3ff1d (Fit sheet rows, plan.js only): cherry-picked (c144922, author kept)
    with plan.js kept from this work (server and twin change lines, grey row, words in the note). Its Node test was adapted
    to `fitNumber` and caught a gap here: the unit was only at the end ("≥ 80 → not listed"); each side now has its unit.
    Partial zero reads "≥ 0 mg" (as the meal editor and Plan's saved-meal sheet do), not "not listed". Its Chromium walk is
    kept next to the meal editor walk. Adapted test: old plan.js crashes (no fitNumber), WIP plan.js 2 of 8 fail, now 8 of 8.
  * Docs: their paragraphs merged into ours so each thing is said once.
* `/usr/bin/python3 tools/e2e/reliability.py` (Playwright is in the system Python, not the venv): 28 passed, 0 failed.

* Full pytest on the final tree (before the CHANGELOG-only commit 59258a7): 6547 passed, 2 skipped, 0 failed (28 min).

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY tests/data/gen_guidance_vectors.py --check; node tests/js/run_vectors.mjs
$PY -m pytest -q tests/test_unknown_swaps_fit_ui.py tests/guidance/ tests/test_unknown_totals_ui.py tests/test_guidance_ui.py
