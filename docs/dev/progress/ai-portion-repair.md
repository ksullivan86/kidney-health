Status: complete

# ai-portion-repair: AI meal ideas that are a little too big are made smaller, not dropped

Task: the owner nearly always sees "The AI ideas did not fit your targets today, so these are the app's own." The live run
(2026-10-29) showed `high_portion_too_large` as the top drop reason (23 of 118 ideas). Two parts: (1) the app lowers a
too-large portion in quarters and keeps the idea; (2) each candidate sent to the AI carries `max_quarters`.

Worktree: `/home/user/kidney-health/.claude/worktrees/agent-a0f680c60c2411e99`, branch `worktree-agent-a0f680c60c2411e99`,
`next-batch` merged in at the start. Local commits only, never push.

## Decisions

* The result key is `portions_lowered`, not `repaired`: the AI activity row's verdict already has `repaired` (the client's JSON
  repair turn, a bool set in `app/ai/routes.py _verdict_of` after the judge), and the golden `expect.repaired` means that too.
* Only these first reasons are repaired: `high_portion_too_large`, `would_exceed:<k>`, `too_many_carbs`,
  `quarters_out_of_range` above 12 quarters (clamped to 12 first). Before repairing, every item is checked for a reason a
  smaller portion must not fix (avoid_ckd, low treatment, ingredient, alcohol, unknown value while the day is not ok,
  unknown carbs, a "high" portion of a nutrient that is not ok today at the proposed amount). If one is found, the idea is
  dropped with check_meal's original reason, as before.
* Lowering: one quarter at a time, never below 1 quarter, never a low treatment, never raised. The item lowered is the
  biggest contributor to the reason (for high_portion_too_large: the largest "high" item over one serving). The full
  check_meal runs again at the end; still failing means dropped with the original reason.
* Rerank, swap and plan pick refs from lists the rules already passed; they only drop unknown or duplicate refs. No portion
  cause there.

## Done

1. Code (verified: 1979 passed in tests/test_ai_*.py, tests/guidance/, test_guidance_ui, test_recipes_ai_ui; node vectors
   exit 0; ruff clean):
   * `app/guidance/ai_bridge.py`: `LOWERABLE`, `_not_for_lowering`, `_to_lower`, `lower_to_fit`, `max_quarters`;
     `validate_ai_items` repairs and returns `portions_lowered`; `candidates_for_ai` foods carry `max_quarters`.
   * `app/ai/guard.py`: `PORTION_LOWERED_TEXT` / `PORTIONS_LOWERED_TEXT`, `portion_note` on a shown idea,
     `portions_lowered` in the verdict (indexes mapped back to the model's).
   * `app/ai/routes.py`: the activity row keeps `portions_lowered`.
   * `app/ai/prompts.py`: `max_quarters` in `candidate_block` (only when the bridge has it, so recipes are unchanged), rule 5,
     PROMPT_VERSION `2026-10-29.1`; snapshots and fingerprint recorded (the fingerprint now includes the two new texts).
   * `app/static/js/views/ai.js`: the sentence under the idea's items.
   * `scripts/ai_eval.py`: `ideas_lowered`, `lowered_reasons`.
   * Tests: new `tests/test_ai_portion_repair.py`; updated `tests/guidance/test_ai_bridge.py`, `tests/test_ai_guard.py`,
     `tests/test_ai_prompts.py`, `tests/test_ai_routes.py`, `tests/test_ai_eval_script.py`; golden harness keys
     `portions_lowered`, `portions_lowered_include`, `shown_quarters_at_most`; 6 golden cases now expect a lowered idea
     (`rules-large-portion-of-good-food-dropped` renamed `...-lowered`), 2 new cases.
   * No JS twin: the demo has no AI (js/mock/ai.js answers 404), and nothing in tests/data covers the bridge.

2. Docs (verified: the doc tests, `pytest -k "doc or changelog or handbook or readme or architecture or plain or words"`,
   941 passed): docs/ai.md (meal ideas row, G4, what is sent, "did not fit" row, the live run note for 2026-10-29.1),
   ARCHITECTURE.md (ai_bridge hook, AiAnswer, Idea), handbook/docs/app/ai.md (the warning bullet and the "did not fit"
   line, which also now quotes the real message), CHANGELOG.md (one line for people using the app, one for people who run a
   server).

3. Full `python -m pytest`: everything passes except one test that already fails on `next-batch`:
   `tests/test_deploy.py::test_self_hosting_pages_link_to_commands_instead_of_copying_them[backups.md]` (the
   `podman exec` line from dd88a39, not touched here). 53 setup errors in test_lab_photo, test_learn_offline,
   test_log_if_match and test_mcp came from the shared `/tmp/pytest-of-root` used by other agents at the same time; rerun
   with `--basetemp` in the scratchpad they all pass.

## Findings outside the meal ideas

* Rerank, swap and plan cannot drop for a portion: they pick refs or option indexes from lists the rules already passed
  (or, for plan, the planner rebuilds the day). Nothing changed there.
* AI recipes drop `share_too_large` (more than 3 servings of a food in one serving) before `fit_recipe` runs, although
  `fit_recipe` can already lower `portion_out_of_range`. One drop of 118 in the live run; left as is.

## Old vs new (tests/test_ai_portion_repair.py, rice 4 quarters + a 170 mg potassium food 6 quarters)

* Before: `{"status": "dropped_all", "message": "The AI ideas did not fit your targets today, so these are the app's own.",
  "dropped": [{"index": 0, "reason": "high_portion_too_large"}]}`
* After: status ok, the food at 4 quarters, `portions_lowered: [{index 0, high_portion_too_large, 6 -> 4}]`,
  `portion_note` "The app made a portion smaller so the meal fits your targets."

## Commands

    PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
    $PY -m pytest -q tests/test_ai_golden.py tests/test_ai_prompts.py tests/test_ai_routes.py tests/guidance/ tests/test_ai_guard.py tests/test_ai_eval_script.py
    node tests/js/run_vectors.mjs
    /root/.local/bin/ruff check
