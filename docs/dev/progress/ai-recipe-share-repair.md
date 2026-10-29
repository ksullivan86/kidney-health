Status: in progress

# ai-recipe-share-repair: an AI recipe whose only problem is a too-big share is fitted, not dropped

Task: `app/ai/recipes.py judge_recipes` dropped a recipe with more than 3 servings of a food in one serving
(`share_too_large`) before `fit_recipe` ran, although the fit lowers `portion_out_of_range`. 1 of 118 drops in the owner's
live run of 2026-10-29. Make it go through the fit, keep every other drop.

Worktree: `/home/user/kidney-health/.claude/worktrees/agent-a42d956fd34b0a30f`, branch `worktree-agent-a42d956fd34b0a30f`,
fast-forwarded to 501b87e (PR #123) at the start. Local commits only, never push.

## Decisions

* The too-big check moved after the eligibility checks, so a too-big share never hides another reason (avoid, low
  treatment, alcohol, supplies, Not for me, excluded group, salt, not a candidate, quarters out of range).
* `fit_recipe` is the one gate. A recipe the fit cannot fix is dropped as `share_too_large` when the closest version still
  has a share above 3, else as before (`would_exceed:<k>`).
* Names follow the meal ideas: `portions_lowered` (answer: `{index, reason: "share_too_large", changes}`; card: the
  changes), `portion_note` on the card. A change is `{food_id, from_servings, to_servings}` in servings of the food in one
  serving of the recipe; `to_servings` is 0 when the fit swapped the food out.
* Texts `PORTION_LOWERED_TEXT` / `PORTIONS_LOWERED_TEXT` live in `app/ai/recipes.py`. They are not in the prompt
  fingerprint and the prompt did not change, so PROMPT_VERSION stays `2026-10-29.1`.
* Found on the way: a swap for a too-big share (a protein food is never lowered, so it is swapped) said "because X does not
  list a value the app needs today". Fixed in `app/guidance/messages.py` and its JS twin: "because one serving held more of
  X than the app allows." Two new `fit_recipe` vectors; the stew vector's text changed too.
* `ideas_lowered` in `scripts/ai_eval.py` now counts meal ideas only; `recipes_lowered` counts recipes.

## Done

1. Code and tests (before: the new route test failed with `dropped_all` / `share_too_large`; after: all pass):
   `app/ai/recipes.py`, `app/guidance/messages.py`, `app/static/js/engine/guidance/messages.js`, `app/static/js/views/ai.js`
   (note above "What the app changed"), `app/ai/routes.py` (comment), `scripts/ai_eval.py`, `tests/test_ai_recipes.py`,
   new `tests/test_ai_recipe_share_repair.py`, `tests/test_recipes_ai_ui.py`, `tests/test_ai_eval_script.py`,
   `tests/test_ai_golden.py` + new golden case `recipes-share-too-big-lowered`, `tests/data/gen_guidance_vectors.py` +
   regenerated `tests/data/guidance_vectors.json`.

## Next

2. Docs: docs/ai.md, ARCHITECTURE.md, handbook/docs/app/ai.md (+ planning-and-menus.md), CHANGELOG.
3. Run the checks below, commit.

## Commands

    PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
    BT=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/share-repair/bt
    $PY -m pytest -q -p no:cacheprovider --basetemp=$BT tests/test_ai_*.py tests/guidance tests/test_recipe*.py
    node --test tests/js/*.test.mjs; node tests/js/run_vectors.mjs
    $PY scripts/gen_openapi.py --check; /root/.local/bin/ruff check
