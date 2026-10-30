Status: in progress

# planning-round-2: the owner's answers to note 23 §10 (2026-10-30)

Branch: the worktree branch `worktree-agent-a2107be7cab2fa508` (local commits only, no push, no PR). Base: 08b1d05 (0.12.0).

## Decisions

* The plan sheet's "Where ideas come from" holds only three switches (saved meals, meals I often have, starter meals). All
  three are the rules engine. The several-days plan sends nothing to AI today. `PLAN_DAYS_AI_MAX` is registered (default 31)
  and is the cap for a plan whose ideas come from AI, which does not exist yet (note 23 §11 phase 3).
* Caps are instance settings with env locks: `guidance.plan_days_max` (`PLAN_DAYS_MAX`, 60, 1–90) and
  `guidance.plan_days_ai_max` (`PLAN_DAYS_AI_MAX`, 31, 1–90). The request model allows up to 90; the route answers 400 over
  the setting. `clear-planned` follows the same cap.
* Remembered choices live in the person's `guidance` settings object (no schema change): `plan_repeat_meals`, `plan_snack`,
  `repeat_ok_foods`, `repeat_ok_meals`.
* Engine: a meal in `repeat_meals` skips the 2-day rule and the plan's food rotation for that meal. A food marked OK to repeat
  never counts in the rotation; a meal made only of such foods, or a saved meal marked OK to repeat, may come back the next
  day. The real "eaten the 2 days before" term is unchanged, so day 1 still equals "Plan a day…".
* `snack` (default false): the snack is planned only when asked. `skip_first_day`: meals not planned on the first day.
* Dialysis days: one set of targets (sources checked: KDOQI, KDIGO 2024, DaVita, AKF, JBDS; none gives separate daily
  K, P or sodium targets for dialysis days; the interval is per-day target × days).

## Done

1. Note 23 §12 records the owner's decisions (1995dec).
2. Settings `guidance.plan_days_max` / `guidance.plan_days_ai_max`, the four `guidance` object fields, the JS settings twin,
   settings vectors, `.env.example`, compose, quadlet, the admin settings group (500f183). Checked: tests/test_settings*.py,
   test_compose_env.py, test_deploy.py, run_vectors.
3. Engine: `planner.day_slots`, `plan_days(repeat_meals, snack, skip_first_day)`, `Prefs.repeat_ok_food_ids/meal_ids`;
   twin `daySlots`, `planDays`; 9 new vector cases (`DAYS …`); RULES_VERSION 2026-10-30.2 (PLAN_DAYS_MAX 60,
   PLAN_DAYS_AI_MAX 31, PLAN_DAYS_CEILING 90 in the rules table); docs/guidance.md rules table regenerated; 7 new tests in
   tests/guidance/test_plan_days.py. `snack=None` keeps the old slots, so the old vectors did not change.

4. API: `PlanDaysRequest` (days ≤ 90, `repeat_meals`, `snack`, `skip_first_day`), 400 over `guidance.plan_days_max`,
   `limits` and `choices` in the answer; `clear-planned` follows the setting, `CLEAR_PLANNED_MAX_IDS` 2500;
   `GET /api/guidance/repeat-ok`, `PUT|DELETE /api/guidance/repeat-ok/{foods|meals}/{id}` (404 not yours, 409 full);
   demo twin routes; OpenAPI regenerated (c33dd73). The demo's meal lists now say only "at most 4 items" for a list of 5 or
   more, as pydantic-core does.
5. AI: `repeat_ok` block `{meals, food_ids, saved_meals}` in every meal prompt (ideas, rerank, swap, plan), rule 10,
   PROMPT_VERSION 2026-10-30.1, snapshots and fingerprint updated with KH_UPDATE_SNAPSHOTS=1. No guard change.
6. UI: plandays.js rewritten (quick 7/14/30/60 hidden above the cap, Start tomorrow, snack checkbox, meals that may repeat,
   OK-to-repeat list and toggles, past-meal skip and "Plan it anyway?" with core.js `cancelText`/`onCancel`, reset text,
   Undo text, batch progress); guidance.js: `savePrefs`, `prefValue` exported, rowMenu/planMeal `repeat` option, Settings →
   Meal guidance "Plan several days" block; CSS; static tests in tests/test_plan_days_ui.py and test_guidance_ui.py.
   Bench: `plan-days (60 days)` in scripts/bench_guidance.py and tests/guidance/test_perf_guidance.py. Twin: 60 days ~1 s.

## Next

1. Note 23 decisions. 2. Settings. 3. Engine + twin + vectors. 4. API. 5. AI field. 6. UI + mock. 7. e2e. 8. Docs.

## Commands

```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
BT=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/pl2/bt
$PY -m pytest -q -p no:cacheprovider --basetemp $BT tests/guidance
$PY tests/data/gen_guidance_vectors.py --check && node tests/js/run_vectors.mjs
```
