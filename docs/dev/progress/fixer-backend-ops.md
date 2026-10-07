# fixer-backend-ops progress

Status: in progress (started 2026-10-07)

Role: fix the v0.3.0 review findings in the backend/ops half of the tree (Python under app/,
migrations, tests except tests/js, scripts except build_preview, deploy/, .github). Ports 8600-8619.
Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/fixer-backend-ops/

## Findings (C = confirmed, L = low)

| # | Finding | State |
|---|---|---|
| C1 | vision: photo bodies read before consent/slot/quota (memory) | done |
| C2 | targets E-1/E-3 calorie note contradicts target | todo |
| C3 | insights day.hypo.logged without portion | todo |
| C4 | AI guard low_* claims judged against half the room | todo |
| C5 | AI shown free text blocklist misses shot/skip/delay/pen/pill/extra | todo |
| C6 | insights all_good with unknown K/Na counted as 0 | todo |
| C7 | OFF prepared-only: serving_g is dry weight | todo |
| C8 | log: unknown K/P counted as 0 with no indicator | todo |
| C9 | OFF potassium ceiling drops salt substitutes | todo |
| C10 | OFF per-100 mL drinks without serving not fluid | todo |
| C11 | curated foods: raw eggs suggested | todo |
| C12 | X-KDL-Version header + shell/API check | todo |
| L1 | AI retention purge only with AI traffic | todo |
| L2 | IDN AI base URL refused | todo |
| L3 | K-2 'relaxed one step' when ladder == relaxed; N-1 age-70 cut-off | todo |
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

## Decisions

## Commands
