# fixer-backend-ops progress

Status: in progress (started 2026-10-07)

Role: fix the v0.3.0 review findings in the backend/ops half of the tree (Python under app/,
migrations, tests except tests/js, scripts except build_preview, deploy/, .github). Ports 8600-8619.
Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/fixer-backend-ops/

## Findings (C = confirmed, L = low)

| # | Finding | State |
|---|---|---|
| C1 | vision: photo bodies read before consent/slot/quota (memory) | done |
| C2 | targets E-1/E-3 calorie note contradicts target | done |
| C3 | insights day.hypo.logged without portion | done |
| C4 | AI guard low_* claims judged against half the room | done |
| C5 | AI shown free text blocklist misses shot/skip/delay/pen/pill/extra | done |
| C6 | insights all_good with unknown K/Na counted as 0 | done |
| C7 | OFF prepared-only: serving_g is dry weight | done |
| C8 | log: unknown K/P counted as 0 with no indicator | server done; UI = frontend fixer |
| C9 | OFF potassium ceiling drops salt substitutes | done |
| C10 | OFF per-100 mL drinks without serving not fluid | done |
| C11 | curated foods: raw eggs suggested | done |
| C12 | X-KDL-Version header + shell/API check | done |
| L1 | AI retention purge only with AI traffic | todo |
| L2 | IDN AI base URL refused | todo |
| L3 | K-2 'relaxed one step' when ladder == relaxed; N-1 age-70 cut-off | done |
| L4 | check_meal lets AI ideas create a new day 'over' | todo |
| L5 | G7 hypo pre-filter phrasings | todo |
| L6 | OFF per-serving label without quantity stored as per 100 g | done |
| L7 | additives: 'phosphorus' word flagged as additive | done |
| L8 | label photo serving_desc/serving_g not marked from photo | todo |
| L9 | 'Server name' help text vs signed-in title | todo |
| L10 | new accounts default to stage 3b / type 1 | todo |
| L11 | first-run log line https://<this server> | todo |
| L12 | ISO dates in server texts | todo |
| L13 | AI 10-minute result cache | todo |
| L14 | CLI export-user / disable-user | todo |

## Done (and how verified)

* **C1** `app/vision.py`, `app/imagecheck.py`, `app/ai/routes.py` (`ai_slot`, `check_consent`, `run_call(slot_held=)`):
  order is switches → headers 415/413 → photo consent 409 → person+server slot 429 → body (one buffer,
  60 s deadline → 408 `upload_timeout`) → call in the same slot; tool check moved inside the slot for all
  calls; probe takes quota inside the slot (a busy probe spends none). check_jpeg slices memoryviews and
  joins once. Tests: `tests/test_vision_api.py` raw-ASGI tests (bytes pulled = 0 on 429/409, 408, truncated).
  Real server (uvicorn --limit-concurrency 64, FakeAi, 64 concurrent 3.9 MB JPEGs from one person):
  HEAD VmHWM 113→394 MB (consent) and 113→753 MB (no consent); now 113→191 MB and 113→128 MB.
  Script: scratch `memrepro.py <repo> <port> photos|none`.

* **C8 (server half)** unknown counts: see Handoffs. `tests/test_unknown_values.py` (pure + API: day, meal,
  status, planned/projected, range, summary, interdialytic); pinned-shape tests updated (`test_api`, `test_periods`,
  `test_planning`).
* **C2 + L3** `app/target_rules.py` (`E-1.estimate`, E-3 with `{kcal}`/`{ref}`, `K-2.top`, `N-1.low_bmi.older`),
  `app/targets.py`, JS twin `app/static/js/engine/targets.js` (smallest change outside my area, needed for
  parity), vectors regenerated (`python3 tests/data/gen_targets_vectors.py`; `node tests/js/run_vectors.mjs`
  1859 targets checks). Tests: TV20 case, property "exactly one note starts with Calories: and states the target
  (or E-4's total)" over 1500 random profiles, K-2 parametrized by stage, GLIM age-70 wording.

* **C3 + C6** `app/guidance/insights.py` + twin `js/engine/guidance/insights.js`: better low treatment prints
  "(5 × 1 tablet, 20 g carbs)" and `numbers.better_servings`; `_unknown`/`_unknown_note`: day.all_good and
  period.all_good skip nutrients with unknown values, new `period.unknown` info insight, `period.change.*` skipped
  when either period misses values. 4 new vector cases (`gen_guidance_vectors.py`), tests in
  `tests/guidance/test_insights.py` (doses 15/20/30 with and without gel/shot, unknown day/period/change).

* **C4 + C5** `app/ai/guard.py`: `low_*` true only when every portion ≤ engine threshold (`LOW_PORTION_MG`) and
  ≤ ½ room; REASON_TEXT prints `{k}`/`{p}`/`{na}` (sentence(codes, meal, items)); BLOCKLIST adds §9 A2 terms
  (shot, pen, skip/delay forms, pills/meds/prescri*, binder brands, extra/more/double as advice, "is fine/ok/safe");
  "extra virgin", "penne", "Skippy", "glucose tablets" pass. PROMPT_VERSION 2026-10-07.1 (fingerprint recorded with
  `KH_UPDATE_SNAPSHOTS=1 python -m pytest tests/test_ai_prompts.py`). 3 golden cases added; tests in test_ai_guard.
  Not verifiable here: a live evaluation (scripts/ai_eval.py) — no provider in this environment (ROADMAP item).

* **C7, C9, C10, L6, L7** `app/off.py` (`is_liquid`, DRY_TAGS verified against the OFF categories taxonomy,
  ceilings K 60 g / P 32 g per 100 g with the stoichiometry in the comment, "as sold, prepared" serving text,
  `serving_weight_unknown` → no_nutrition), `app/foods.py` (`weight_known`, `WEIGHT_UNKNOWN_DETAIL`), `app/log.py`
  (resolve_servings 400; copy-day/PUT keep servings), `app/guidance/api.py` (swaps by grams 400), `app/barcode.py`
  (404 text NO_SERVING_WEIGHT), `app/additives.py` + JS twin (element word skipped unless "acid"), JS `off.js`
  messages, DEMO_PRODUCTS block regenerated. Tests: test_off_mapping (5 salts warn high, ceilings, 6 liquid cases,
  3.5 per-100 mL, per-serving without weight 3.4 + 3.5), test_barcode_api (Kraft grams 400 on POST/PUT/batch/swaps,
  servings 50 g carbs, copy-day/edit keep servings, synthetic 404), test_additives (+8 cases), barcode vectors.

* **C12** `app/pwa.py` `ApiVersionMiddleware` (X-KDL-Version = shell hash on every /api answer); smallest client
  change (outside my area): `sw.js` answers 'VERSION', `js/pwa.js` `versionSeen` (+ asks the controller at
  register and on controllerchange), `js/core.js` passes the header. Tests: test_pwa_routes (header on 200/401/
  404/400/unknown, not on shell; Node vm harness for versionSeen). Real Chromium check (scratch
  `version_check.py <scratch> <port>`): server A → page on cached shell → server B → one KH.api call → toast →
  Reload → shell B; negative control with HEAD's client code: no toast within 20 s.

* **C11** `scripts/curated_foods.py`: "Egg white, raw" → "Egg white" (+ cooking note; values per egg, same raw or
  cooked), "Egg, whole, raw" gets `ingredient` (+ note) so guidance never suggests it; `data/foods.json` rebuilt
  offline (`python3 scripts/build_food_db.py --version 2026-10-07.2`, cached SR zip; diff = those two rows);
  guidance + rules vectors regenerated; demo `js/mock/foods.js`, `tools/e2e/parity.py`, handbook menus.yml
  comments/notes and the generated menus, grocery lists and recipe (`scripts/build_handbook.py`) follow the name.
  Tests: `tests/guidance/test_food_safety.py` (what-fits all meals + plan, stage 4 and HD, on the real list),
  test_data ingredient count. `test_planner` beam test: the spec bound (max ≤ 0.5 on 40 seeded days) holds
  (0.43); its extra median assertion moved 0.02 → 0.08 because the breakfast sample is drawn from eligible foods;
  measured on 160 seeds: median 0.07 (HEAD) / 0.10 (now), max 0.81 (HEAD) / 0.52 (now). Median bound set to
  0.1 with the measurement in a comment. Observation for the owner: at HEAD the beam is up to 0.81 below the
  oracle on a larger sample (ROADMAP already lists the MILP measurement, note 06 §3.1 C).

## Handoffs (to fixer-frontend-docs)

* **C8 server shape (done, in ARCHITECTURE.md "M2 API: barcode" → "Foods and log changes", last bullet):**
  `DaySummary += unknown, planned_unknown, projected_unknown` (`{nutrient: entries}`, only nutrients with a
  count), `meal_unknown` / `planned_meal_unknown` (`{meal: {nutrient: n}}`, all four meals present);
  every `status`/`projected_status` item has `unknown: n` (0 when complete; level unchanged);
  `/api/log/range` days gain `unknown`, `planned_unknown`, `projected_unknown`; `PeriodSummary.nutrients[k]`
  gains `unknown_entries`, `unknown_days`; interdialytic nutrients gain `unknown_entries`.
  Python: `app/nutrients.py` `count_unknown`, `merge_unknown`, `mark_unknown`; `app/log.py`
  `day_figures`, `eaten_day_unknown`; `app/periods.py`. Tests: `tests/test_unknown_values.py`.
  Still yours: the UI (today.js meal footers / rows / bars, trends), `js/mock/log.js` (+ summary/range),
  `rules.js` addTotals twin if you want one, handbook `app/logging.md:60`, `targets-and-warnings.md:42`.

* **C7 UI (yours):** a food whose `quality` has `prepared_values` (or `serving_weight_unknown`) takes servings
  only: hide the grams field and the "1 serving = N g" hint in the entry sheet (add.js:168), and make
  `js/mock/log.js` answer grams for it with 400 `WEIGHT_UNKNOWN_DETAIL` (app/foods.py) for parity.
* **docs/barcode-and-photos.md (yours):** mapping rules changed: potassium ≤ 60 g / phosphorus ≤ 32 g per 100 g,
  liquids (per 100 mL / beverages, not powders) count as fluid, prepared-only = servings only, per-serving
  without weight = enter from the label; additive scan ignores the bare element word "phosphorus".

## Decisions

* C7: chose "servings only" over "store serving_g only when prepared_per == serving": the Kraft fixture says
  `nutrition_data_prepared_per: 100g` although its values come from the per-serving label, so the flag cannot
  tell the dry and prepared bases apart; disabling grams is right for both.
* L6: chose `no_nutrition` (enter from the label) over keeping the values with a placeholder 100 g weight: the
  placeholder would leak into the shopping list, guidance portions, AI prompts and CSV; the live OFF server
  already drops such sets (rare).

## Commands
