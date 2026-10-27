Status: complete

# recipes-note: design note 16, "Recipes that fit your targets"

Task: write `docs/dev/research/16-recipes-that-fit.md` (a design note, no code), add one line to `docs/ROADMAP.md`
(the owner's ideas), keep this note up to date. Worktree: branch `wip/recipes-note`, based on main 56869a4.
Local commits only: no push, no PR.

## Done

* Read CLAUDE.md, notes 13 and 15 (models for structure), `app/meals.py`, the meal models, `app/ai/chat_save.py`,
  `app/mcp/tools.py` (`save_recipe`), `app/guidance/` (budget, fits, swaps, score `check_meal`, rules, vectors, state,
  context, ai_bridge), `app/ai/` (features, guard, schemas, prompts, routing, routes, chat checks), `docs/ai.md`,
  `docs/ROADMAP.md`, the handbook leaching and recipe pages, the vector README.
* There is no `docs/dev/research/README.md`, so there is no index line to add. `docs/README.md` lists notes 01 to 10 only.

## Findings that change the owner's choices (all in the note, section 3)

1. `servings_made` and `source_url` are not columns today. `save_recipe` writes "Makes N servings." into the note and
   keeps the ingredients for the whole pot. A schema step 20 is needed.
2. `MealTemplate.totals` counts an unknown value as 0 today. A recipe needs per-serving figures with `unknown` counts.
3. "What fits now" offers a saved recipe at pot size (scales 1, 3/4, 1/2 of the whole), and `check_meal` refuses an item over
   3 servings, so a saved 4-serving recipe almost never shows. Fixed by dividing by `servings_made`.
4. `check_meal` kind `ai` refuses the `ingredient` flag (flour, oil, salt) and any item outside 1/4 to 3 servings. A recipe
   needs a new kind `recipe`; it is judged on one serving's share of each ingredient.
5. `find_swaps` cannot be called on a share as it is (portion bounds 1/4 to 3, "serving" match gives 1.0). Its core is
   reused with recipe bounds.
6. Free text from the model is against G10/A2 for the meal features. Steps need a new guardrail (G18) and an admin switch,
   off until the owner's live run, as the ROADMAP says free text returns "only behind the golden-set gates".
7. docs/ai.md says "ingredient lists" are never sent. That means a food's printed list; a recipe's foods are food ids and
   names, like the saved meals meal ideas already send. Reword the row.
8. The commit trailer: the system reminder for this session says "Claude Sonnet 5.5"; the task text says "Claude Opus 5.5".
   I used the reminder's lines (it is accurate for this model) and said so in the report.

## Done at the end

* `docs/dev/research/16-recipes-that-fit.md` written (15 sections, about 530 lines): status table, problem, what exists
  (R1 to R13), where the code departs from the owner's choices, options, the recipe's data, data flow, API, the AI call
  (data sent, candidate list, schema, checks, title, steps checks G18), the fitting engine (kind `recipe`, pseudocode, bounds,
  change lines), screens, safety cases, tests and measuring, phases with token costs, risks, decisions (16).
* One line added to `docs/ROADMAP.md` in "Ideas from the owner".
* No index line for the note: `docs/dev/research/README.md` does not exist, and `docs/README.md` lists notes 01 to 10 only,
  so adding 16 alone would be odd. Left for whoever indexes 11 to 16.
* A check on the fixture of `tests/guidance/fixtures.py` showed the problem in R4: a recipe that fits one dinner (365 mg
  potassium, 750 mg of room) is refused at pot size for 4 (1,460 mg), and a 0.04-serving item gives `portion_out_of_range`.

## Checks run (all green, no network)

```
python scripts/build_handbook.py --check          # handbook generated files are up to date
python -m pytest -q tests/test_handbook_content.py tests/test_handbook_serving.py tests/test_learn_links.py \
    tests/test_vectors_readme.py tests/guidance/test_docs.py        # all passed (one old warning about unused sources)
git diff --cached --check
```
There is no `tests/test_docs*.py`. Every path in the note exists, except the new files it proposes.

## If you continue

Nothing is left in this task. The decisions are in section 15 of the note; the owner answers them before phase 0 starts.
