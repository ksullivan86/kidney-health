Status: complete

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

* Design note `docs/dev/research/23-multi-day-planning.md` (9c4d39f).
* 1-2. Engine `plan_days`, routes `POST /api/guidance/plan-days` and `POST /api/log/clear-planned`, models, OpenAPI, tests
  `tests/guidance/test_plan_days.py`, `tests/guidance/test_plan_days_api.py` (f02db7e).
* 3. JS twin `planDays`, vectors in `tests/data/guidance_vectors.json` (d8d2c52).
* 4. Mock routes in `js/mock/guidance.js` and `js/mock/log.js`; `tests/test_plan_days_demo.py` checks the server's 400 texts
  for both routes, the answer shape (keys by path, merged over list items, since the demo log differs from the server's) and
  that clearing keeps eaten food and a planned low treatment. The demo test plans 30 days after today because the demo's sample
  log covers today-N to today+3 (`js/mock/seed.js`).

* 5. Screens: `js/views/plandays.js` (new; in index.html after guidance.js and in sw.js), button `#btn-plan-days`
  "Plan several days…" on the Plan tab. It fills `#sheet-guidance` (kind `plan-days`) with the plan sheet's parts, exported
  as `KH.guidance.plan`. `dayAfter` in guidance.js now reads `projected_unknown` ("≥", "not listed"). "Not for me" in the
  preview re-plans (`KH.views.planDays.replan`). `confirm.inline` takes `tone: 'primary'` (core.js) for Add to plan.
  plan.js exports `shoppingText`, `copyShopping(text, box)`, `weekStartPref`. Static tests `tests/test_plan_days_ui.py`.
  Checked: all `tests/*_ui.py`, `test_frontend_shell.py`, `test_pwa_routes.py`, `test_vendor.py`, `node --test`.
  Decisions: "Clear planned days…" is a link in the body, not a third foot button (375 px); each day is a `<details>` (first
  day with meals open) so a 14-day preview stays short; the client_ids are made once per plan so pressing Add again after a
  part failed adds only the rest; after Undo new ids are made.

* 6. Chromium walk `tools/e2e/plandays.py` (listed in `tools/e2e/README.md` and `tests/test_e2e_tools.py`): 24 of 24 pass,
  `cd tools/e2e && python3 plandays.py --port 8231 --out <scratch>/e2e` (system python3, ~1 min; `--no-demo` skips the build).
  Note: `inner_text` reads nothing inside a closed `<details>`; the walk opens the day first.

* 7. Docs: ARCHITECTURE.md (module line, Plan tab, `clear-planned` under the log routes, `plan-days` row and `PlanDays`
  shape, the frontend "Plan several days" item), `docs/guidance.md` (feature row, "Several days at once"), handbook
  `handbook/docs/app/planning-and-menus.md` ("Plan several days", a "went wrong" item; cites ARCH and NOTE06, no new
  sources.yml id so no handbook rebuild), CHANGELOG "## Unreleased" (both sections). OpenAPI `--check` is clean (regenerated
  in f02db7e). Also fixed: `tests/guidance/test_parity_vectors.py` now expects `plan_days` (it failed since d8d2c52), and
  `# noqa: F811` on the `real` fixture tests in `tests/guidance/test_plan_days_api.py` (ruff, as test_recipe_fit.py does).

## Final checks (all pass)

`tests/guidance`, `tests/test_planning.py`, `tests/test_plan_days_demo.py`, `tests/test_plan_days_ui.py`, every
`tests/*_ui.py`, `test_frontend_shell.py`, `test_pwa_routes.py`, `test_vendor.py`, `test_handbook_content.py`,
`test_learn_links.py`, `test_auth_coverage.py`, `test_isolation*.py`, `test_log_if_match.py`, `test_menu_plan.py`,
`test_openapi_snapshot.py`, `test_e2e_tools.py`; `node --test tests/js/*.test.mjs` (166); `node tests/js/run_vectors.mjs`;
`gen_guidance_vectors.py --check`; `gen_openapi.py --check`; `ruff check .`; `tools/e2e/plandays.py` 24/24.

## Open questions for the owner (note 23 §10)

14 or 28 days; the 2-day repeat rule (same breakfast every day?); separate dialysis-day targets; Clear planned days takes
every planned food or only what the plan added; the snack by default; skip a meal whose time has passed today.

## Commands

```
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
BT=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/mdp/bt
$PY -m pytest -q -p no:cacheprovider --basetemp $BT tests/guidance tests/test_planning.py
$PY tests/data/gen_guidance_vectors.py --check && node tests/js/run_vectors.mjs
$PY scripts/gen_openapi.py --check
```
