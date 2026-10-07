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
| C3 | insights day.hypo.logged without portion | todo |
| C4 | AI guard low_* claims judged against half the room | todo |
| C5 | AI shown free text blocklist misses shot/skip/delay/pen/pill/extra | todo |
| C6 | insights all_good with unknown K/Na counted as 0 | todo |
| C7 | OFF prepared-only: serving_g is dry weight | todo |
| C8 | log: unknown K/P counted as 0 with no indicator | server done; UI = frontend fixer |
| C9 | OFF potassium ceiling drops salt substitutes | todo |
| C10 | OFF per-100 mL drinks without serving not fluid | todo |
| C11 | curated foods: raw eggs suggested | todo |
| C12 | X-KDL-Version header + shell/API check | todo |
| L1 | AI retention purge only with AI traffic | todo |
| L2 | IDN AI base URL refused | todo |
| L3 | K-2 'relaxed one step' when ladder == relaxed; N-1 age-70 cut-off | done |
| L4 | check_meal lets AI ideas create a new day 'over' | todo |
| L5 | G7 hypo pre-filter phrasings | todo |
| L6 | OFF per-serving label without quantity stored as per 100 g | todo |
| L7 | additives: 'phosphorus' word flagged as additive | todo |
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

## Decisions

## Commands
