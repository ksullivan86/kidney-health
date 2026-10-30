Status: complete

# planning-round-2: the owner's answers to note 23 §10 (2026-10-30)

Branch: the worktree branch `worktree-agent-a2107be7cab2fa508` (local commits only, no push, no PR). Base: 08b1d05 (0.12.0).

## Decisions

* The plan sheet's "Where ideas come from" holds only three switches (saved meals, meals I often have, starter meals). All
  three are the rules engine. The several-days plan sends nothing to AI today. `PLAN_DAYS_AI_MAX` is registered (default 31)
  and is the cap for a plan whose ideas come from AI, which does not exist yet (note 23 §11 phase 3). The sheet now says
  "Nothing is sent to AI."
* Caps are instance settings with env locks: `guidance.plan_days_max` (`PLAN_DAYS_MAX`, 60, 1–90) and
  `guidance.plan_days_ai_max` (`PLAN_DAYS_AI_MAX`, 31, 1–90, never above the plain cap in `limits`). The request model allows
  up to 90; the route answers 400 over the setting. `clear-planned` follows the same cap.
* Remembered choices live in the person's `guidance` settings object (no schema change): `plan_repeat_meals`, `plan_snack`,
  `repeat_ok_foods`, `repeat_ok_meals`. The marks have their own routes (`/api/guidance/repeat-ok`, 404 when not yours);
  only the person's own foods and saved meals are ever read from the lists.
* Engine: a meal in `repeat_meals` skips the 2-day rule and the plan's food rotation for that meal. A food marked OK to repeat
  never counts in the rotation; a meal made only of such foods, or a saved meal marked OK to repeat, may come back the next
  day. The real "eaten the 2 days before" term is unchanged, so day 1 still equals "Plan a day…".
* `snack` (engine default None = old behaviour; route default the person's `plan_snack`, false). `skip_first_day`: meals not
  planned on the first day. The screen decides it from the browser's clock (08:00, 12:30, 15:30, 18:30; >2 h past skipped,
  ≤2 h asked).
* Dialysis days: one set of targets (sources checked: KDOQI 2020, KDIGO 2024, DaVita, AKF, JBDS 2022; none gives separate
  daily K, P or sodium targets for dialysis days; the interval is per-day target × days).
* The AI field `repeat_ok` goes into every meal prompt (ideas, rerank, swap, plan) as meal names, candidate ids and saved
  meal refs only. Recipes, describe-a-meal, photos and Ask do not get it.

## Done

1. Note 23 §12 records the owner's decisions (1995dec).
2. Settings, JS settings twin, settings vectors, `.env.example`, compose, quadlet, the admin settings group (500f183).
3. Engine and twin: `day_slots`/`daySlots`, `plan_days(repeat_meals, snack, skip_first_day)`, `Prefs.repeat_ok_*`; 9 new
   vector cases; RULES_VERSION 2026-10-30.2; 7 new engine tests (dba565c).
4. API, demo routes, OpenAPI (c33dd73).
5. AI field, PROMPT_VERSION 2026-10-30.1, snapshots and fingerprint.
6. UI: plandays.js, guidance.js (`savePrefs` reads the object fresh first), core.js inline confirm `cancelText`/`onCancel`,
   Settings → Meal guidance block, CSS, static tests; bench and perf test for 60 days.
7. Chromium walk `tools/e2e/plandays.py`: 46 of 46 pass (port 8247, with the demo).
8. Docs: ARCHITECTURE.md, docs/guidance.md, docs/deployment.md, docs/ai.md, handbook planning page, CHANGELOG Unreleased,
   note 23 §2, §4, §5, §9, §12. Import vectors regenerated (rules_version).

## Evidence that the new tests fail on the old code

The 0.12.0 tree (`git archive 08b1d05`) with the new test files copied in:
`tests/guidance/test_plan_days.py` 8 failed, `test_plan_days_api.py` 5, `test_perf_guidance.py` 3, `test_parity_vectors.py`
3, `tests/test_plan_days_ui.py` 9, `test_plan_days_demo.py` 2, `test_guidance_ui.py` 1, `test_ai_prompts.py` 5,
`test_isolation_v03.py` errors at setup (the old server refuses the new fields). `node tests/js/run_vectors.mjs`: 46 of 762
settings checks and 112 of 153 guidance checks fail on the old twins. The new Chromium walk stops at its first new step on the
old app (`#g-days-30` does not exist).

## Speed

Engine (laptop, x86): 60 days ~1.8 s with 395 foods, ~2.9 s with 2,000; 90 days ~2.6 s / ~4.0 s; linear, ~30 ms a day.
Twin (node): 60 days ~1 s. Shopping list for 60 days: 35 to 40 lines.

## Left for the owner

* A live AI evaluation for PROMPT_VERSION 2026-10-30.1 (`scripts/ai_eval.py`); CI never runs it.
* Whether to build AI for several days (phase 3); `PLAN_DAYS_AI_MAX` waits for it.

## Commands

```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
BT=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/pl2/bt
$PY -m pytest -q -p no:cacheprovider --basetemp $BT tests/guidance tests/test_plan_days_ui.py tests/test_plan_days_demo.py
$PY tests/data/gen_guidance_vectors.py --check && node tests/js/run_vectors.mjs
$PY scripts/gen_openapi.py --check
cd tools/e2e && python3 plandays.py --port 8247 --out <scratch>/e2e
```
