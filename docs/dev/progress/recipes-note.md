Status: in progress

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

## In progress / next

* Write the note (sections 1 to 15), then the ROADMAP line, then run the checks below.

## Checks to run (no network)

```
cd <worktree>
python scripts/build_handbook.py --check
python -m pytest -q tests/test_docs*.py tests/test_handbook*.py tests/test_vectors_readme.py   # whatever matches
git diff --check
```
