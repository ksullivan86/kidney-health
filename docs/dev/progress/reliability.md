# Progress: reliability fixes from the 2026-10-29 code review

Status: code, tests and docs done; waiting to open the PR until #115 (shared Trends, same branch) merges.

## Done (verified)

* Today: a failed day load clears the old day and shows "could not be loaded" + Retry (`today.js renderUnavailable`).
* Saved meals: "not listed" / "≥" on Plan cards (`plan.js renderSavedMeals`) and Add shortcuts (`add.js`).
* Fitted recipe: `fittedBody` caps `servings_made` at 100 and scales the amounts instead (`plan.js`).
* `tools/e2e/reliability.py` (port 8097): 10/10 on the fix; on the old views all 5 checks/steps fail (each step runs on its own).
* `tests/test_reliability_ui.py` static checks; `reliability.py` added to `tests/test_e2e_tools.py`.
* Docs: CHANGELOG (Unreleased, for people), ROADMAP "First: daily logging you can trust" + the assistant line no longer reads as
  "recipes not built", ARCHITECTURE (recipe cap, saved-meal unknowns, new section), handbook logging + planning pages, e2e README.

## Next

* Open the PR after #115 merges; then ROADMAP item 1 (failed saves, slow loads on other screens) and item 2 (recipe previews,
  guidance totals).

## Reproduce

    python3 tools/e2e/reliability.py
    python -m pytest -q tests/test_reliability_ui.py tests/test_e2e_tools.py
