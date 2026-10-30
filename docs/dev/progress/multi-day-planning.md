Status: in progress

# multi-day-planning: plan 1 to 14 days at once (design note 23)

Owner's request: "for the planning it should be able to plan the whole day - week or longer". Branch: the worktree branch
`worktree-agent-aad6ee6b75c20c8b3` (local commits only, no push, no PR).

## Decisions

* Route `POST /api/guidance/plan-days` (computes only) and `POST /api/log/clear-planned` (writes: planned entries only, never eaten,
  never a planned low treatment). Writing the plan uses the existing `POST /api/log/batch` in chunks of 40.
* Cap 14 days (`R.PLAN_DAYS_MAX`); reasons in note 23 §2.
* Engine in `app/guidance/planner.py` (`plan_days`), twin in `js/engine/guidance/planner.js` (`planDays`). Day 1 equals `plan_day`
  for that date: the variety rules only look at earlier days of the same plan.
* Per day: ctx with `date`, that day's logged entries, `history` = real history + the earlier plan days (eaten, planned and the
  plan's items) so the phosphorus week and the dialysis interval see them. Habit (`habit_stats`) is computed once at the first
  day; per day only `prev2` is merged with the earlier plan days. `TodayStats.recent` (new, default empty) adds
  `PLAN_RECENT_FOOD_PENALTY` per day in `score_meal`.
* Repeat rule: a meal with the same food set in the same slot on either of the `PLAN_REPEAT_DAYS` (2) days before is dropped from
  the options unless nothing else fits (then `repeated: true`).

## Done

* Design note `docs/dev/research/23-multi-day-planning.md`.

## Next

1. Engine + unit tests. 2. Routes + models + OpenAPI + API tests. 3. JS twin + vectors. 4. Mock routes. 5. Screens + UI tests.
6. Chromium walk (`tools/e2e/`). 7. Docs, handbook, CHANGELOG.

## Commands

```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
BT=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/mdp/bt
$PY -m pytest -q -p no:cacheprovider --basetemp $BT tests/guidance tests/test_planning.py
$PY tests/data/gen_guidance_vectors.py --check && node tests/js/run_vectors.mjs
$PY scripts/gen_openapi.py --check
```
