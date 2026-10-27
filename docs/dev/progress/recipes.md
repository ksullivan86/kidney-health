Status: phases 0 and 1 merged (#94); phase 2 built, in a PR

# recipes: note 16, "Recipes that fit your targets"

The owner's decisions are recorded at the end of `docs/dev/research/16-recipes-that-fit.md` (§15). Build order: phases 0 to 2 (the
fit without AI, one release), then phase 3 (AI recipes). The schema step is 21, because 0.6.0 used 20.

## Phase 0: groundwork (done, one PR)

* `app/migrations/m021_recipes.py`: `meal_templates.servings_made`, `steps_json`, `source_url`; back-fill only from the exact sentence
  `save_recipe` wrote (`parse_recipe_note`, which keeps its own copy of the sentence). Tests: `tests/test_migration_m021.py`.
* `app/models.py`: `MealTemplateCreate` takes the three fields; `MealTemplate` gives them plus `per_serving` and `unknown`.
  `check_source_url`, `MAX_RECIPE_SERVINGS` and `SOURCE_URL_MAX` moved here from `app/mcp/tools.py`.
* `app/meals.py`: insert and PUT (left out keeps, null clears), `per_serving` (null when no item lists a nutrient), `unknown`.
* `app/mcp/tools.py` `save_recipe` and `app/ai/chat_save.py` (Ask's confirm card payload) write the columns, no more note sentence.
* `app/data_import.py`: `ImportMeal` takes the fields (and ignores `per_serving`, `unknown`).
* What fits now: `app/guidance/context.load_saved_meals` divides items by `servings_made`; the twin in `js/mock/guidance.js` too.
* Demo twins: `js/mock/meals.js` (fields, checks, per_serving, unknown; `M.checkSourceUrl`), `js/mock/import.js`.
* `docs/api/openapi.json` regenerated (`python scripts/gen_openapi.py`).
* Docs: ARCHITECTURE (step 21 row, MealTemplate, save_recipe), CHANGELOG Unreleased, `docs/assistant.md`, `docs/guidance.md`,
  handbook `app/planning-and-menus.md`.
* Tests: `tests/test_recipes_api.py` (18), a What fits now case in `tests/guidance/test_api_guidance.py`, updated
  `tests/test_mcp_write.py` and `tests/test_ai_chat_save.py`.

Checks run here: the files above, plus data import, import vectors, export, OpenAPI snapshot, preview build, planning, guidance,
MCP write and Ask save. The full suite runs in CI.

## Not in phase 0 (on purpose)

* The screen still shows a back-filled note "Makes 4 servings." and has no fields for servings, steps or link: phase 2 (editor).
* No `fit-recipe` route and no `check_meal` kind `recipe`: phase 1.

## Phase 1: engine (built, local tests pass)

* `check_meal` kind `recipe` (`app/guidance/score.py`): no lower bound on a share, top bound 3, allows low treatments, ingredients
  and alcohol (like `saved`), refuses a "high" share of a not-ok nutrient and more than 1 serving of a "high" food (like `ai`).
* `app/guidance/recipes.py`: `day_room`, `room_for`, `fit_recipe` (lower, swap, smaller serving, give back), `recipe_swap`.
  **Deviation from §9.4:** instead of splitting `swaps.py`, `recipe_swap` reuses `swaps._eligible_swap` and the swap constants and
  works on pot amounts itself. `find_swaps` and its vectors stay untouched. Ranking is simpler than the swap engine's (same
  category, the person's preferences, processed last, then lower value, name, id).
* Change lines in `app/guidance/messages.py` (`recipe_*`, `RECIPE_NOTES`), checked against `BANNED_PATTERN` in the tests.
* `POST /api/guidance/fit-recipe` (`app/guidance/api.py`, models in `app/guidance/models.py`).
* Six `RECIPE_*` numbers in `rules.py` and the twin `engine/guidance/rules.js` (with `RULES_HASH`), `RULES_VERSION` 2026-10-27.1,
  guidance and import vectors regenerated, rules table in `docs/guidance.md` regenerated, OpenAPI regenerated.
* Docs: ARCHITECTURE route row, `docs/guidance.md` "Recipes that fit", CHANGELOG.
* Tests: `tests/guidance/test_recipe_fit.py` (22).

## Phase 2: twin, vectors and screens (built)

* `engine/guidance/recipes.js` (loaded after hypo.js; in sw.js and both test lists), `check_meal` kind `recipe` in score.js,
  the recipe texts in messages.js. 11 `fit_recipe` vectors (`recipe_cases()` in the generator), every status covered; Node replays them.
* Demo route `POST /api/guidance/fit-recipe` in `js/mock/guidance.js` (validation, gate, no_targets, unavailable, the twin).
* Screens in `js/views/plan.js` + `index.html` (`#sheet-fit`, editor fields) + `css/plan.css`. Checked in Chromium on the built demo
  at 375 and 1280, light and dark: the sheet, every target, Save "(fitted)", Replace with the carbohydrate confirm, Undo; no errors.
* Handbook `app/planning-and-menus.md` ("Recipes", "Fit to my targets"), `handbook/REVIEW.md` (decision 16), CHANGELOG, ARCHITECTURE.
* Tests: `tests/test_recipes_ui.py`; `test_parity_vectors.py` expects `fit_recipe` with all four statuses.

## Then: phase 3 (AI recipes)

## Old phase 2 plan

* `app/static/js/engine/guidance/recipes.js` (twin of recipes.py) and the `check_meal` kind `recipe` in the JS score twin;
  vectors for fit_recipe in `tests/data/guidance_vectors.json` (generator `tests/data/gen_guidance_vectors.py`); the demo route
  in `js/mock/guidance.js`.
* Screens: the recipe editor (servings, steps, link; hide a note equal to the old sentence), the fit sheet (before/after, change
  lines, Save as "<name> (fitted)", Replace with confirm + Undo), handbook page, e2e.
* `handbook/REVIEW.md`: the floor, the protein rule and the order on the dietitian review list (decision 16).

## Old: phase 1 plan

§9 of the note: `check_meal` kind `recipe` (§9.2), split the swap core (§9.4), `fit_recipe` in `app/guidance/recipes.py` (§9.3:
lower amounts with floor ½ and never a protein ingredient, at most 2 swaps, a smaller serving ¾ then ½, give back), the messages,
`POST /api/guidance/fit-recipe` (§7), `RULES_VERSION`, `docs/guidance.md`, tests.

## Reproduce

    python -m pytest -q tests/test_migration_m021.py tests/test_recipes_api.py tests/guidance/test_api_guidance.py -k "recipe or m021"
    node tests/js/run_vectors.mjs
