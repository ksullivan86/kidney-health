# Progress: unknown values in meal totals (roadmap "First", item 2)

Status: built and checked; local branch `unknown-totals` (on top of `other-choices`). Open its PR after the
"Show other foods" PR merges.

* `unknown` next to `totals` on FamiliarMeal, PlanMeal, Closest (`unknown_json` in fits.py, `unknownJson` twin) and AI ideas
  (`validate_ai_items`, guard). Vectors: two UNKNOWN cases via a new per-case `food_overrides` in both replayers.
* Screens: guidance `keyNumber(s)` (chips, meal sheet, plan), AI `nutrientLine(..., unknown)`, Plan's "Add a saved meal" sheet.
* Tests: test_api_guidance (unknown on saved meal + plan), test_ai_bridge (idea unknown), test_unknown_totals_ui.
* Left (ROADMAP): swap ideas and the Fit to my targets sheet.
