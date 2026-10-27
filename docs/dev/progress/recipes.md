Status: phase 0 built, waiting for CI

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

## Next: phase 1 (engine)

§9 of the note: `check_meal` kind `recipe` (§9.2), split the swap core (§9.4), `fit_recipe` in `app/guidance/recipes.py` (§9.3:
lower amounts with floor ½ and never a protein ingredient, at most 2 swaps, a smaller serving ¾ then ½, give back), the messages,
`POST /api/guidance/fit-recipe` (§7), `RULES_VERSION`, `docs/guidance.md`, tests.

## Reproduce

    python -m pytest -q tests/test_migration_m021.py tests/test_recipes_api.py tests/guidance/test_api_guidance.py -k "recipe or m021"
    node tests/js/run_vectors.mjs
