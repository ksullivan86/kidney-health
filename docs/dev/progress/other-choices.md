# Progress: "Show other foods", "Other ideas", "Other recipes" (the owner, 2026-10-29)

Status: built and checked; waiting to open a PR until the reliability PR merges. The work is on the local branch
`other-choices` (one commit on top of the reliability commit). Merge it into `claude/adoring-sagan-th5swr` after that PR merges.

## Done (verified)

* `GET /api/guidance/next-meal?exclude=1,2,3` (≤ 60 ids, 400 otherwise): `parse_exclude` in `app/guidance/api.py`,
  `what_fits(exclude=)` in `fits.py`; twin `whatFits(..., exclude)` + mock `parseExclude`; vector case "OTHER …".
* `POST /api/ai/next-meal` `exclude_food_ids` (ideas only, 400 in other modes) → `candidates_for_ai(exclude=)`;
  `POST /api/ai/recipes` `exclude_food_ids` → `recipe_candidates(exclude=)` (ingredients stay).
* Screens: What fits "Show other foods" + "Back to the first choices" (`guidance.js otherFoods`); AI ideas "Other ideas";
  AI recipes "Other recipes" / "Another way" (`ai.js`).
* Tests: test_api_guidance (2), test_ai_routes (1), test_ai_recipes (1), test_other_choices_ui (2); vectors pass;
  openapi.json regenerated. Chromium scratch check (server and demo): new foods, no overlap, focus kept, back works.
* Docs: CHANGELOG, ARCHITECTURE API rows, docs/guidance.md, docs/ai.md, handbook guidance/ai/planning pages.
