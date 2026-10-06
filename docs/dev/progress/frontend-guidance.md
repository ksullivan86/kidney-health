Status: in progress

# frontend-guidance (M2/M3): guidance UI, demo twin, mock routes

Role prompt: note 06 §4.16 UI with §4.9 messages; API in ARCHITECTURE "M2 API: guidance" (app/guidance/).
Twin `app/static/js/engine/guidance/*.js` matching `tests/data/guidance_vectors.json` exactly; `js/mock/guidance.js`
(+ POST /api/log/batch, purpose/client_id); perf in Chromium with 4x CPU throttle vs note 06 §4.12 budget;
parity.py / sandbox.py / regress.py; Chromium walks 375x812 + 1280x800, light + dark. Ports 8360-8369.
Scratch: $S = /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/frontend-guidance/
Do not edit Python under app/. WIP commits end with " [skip ci]".

## Plan
1. JS twin engine js/engine/guidance/{rules,messages,budget,score,fits,swaps,planner,insights,hypo}.js — DONE
2. settings.js: the 4 guidance keys + 'object'/'list' validation (GuidancePreferences) — DONE
3. Mock: js/mock/guidance.js (all /api/guidance routes with the server's validation), log purpose/client_id/batch,
   meals meal_hint, export food_preferences? (demo has no export) — NEXT
4. UI: js/views/guidance.js + css/guidance.css: What fits now (Add + Today), swap disclosure in the entry sheet,
   hypo card, "Used to treat a low" checkbox + purpose, plan sheet (Plan + Today), insights (Today + Trends),
   Not for me (row menu + Settings list), guidance prefs in Settings, offline message.
5. e2e: parity.py section, sandbox, regress, Chromium walks, 4x throttle perf; docs; ARCHITECTURE module list.

## Done (and how verified)
* Step 1: 9 plain scripts mirroring app/guidance one to one (KH.guidanceEngine; R, M, T, budget, score, fits, swaps,
  planner, insights, hypo). `node tests/js/run_vectors.mjs`: "guidance vectors: 45 checks passed (43 cases)".
  Mutations caught (USAGE_WEIGHT K 3.01 → 17/45 fail; MMOL_LOW 3.3 → 1 fail). Fuzz: $S/fuzz/gen.py (random days,
  history, saved meals, combos, prefs, tunables over all 395 foods + odd custom foods) → 1,850 cases bit-for-bit equal
  incl. sign of zero (`node tests/js/run_vectors.mjs --guidance $S/fuzz/casesN.json`); prefilter: 4,075 texts equal.
  run_vectors.mjs gained a guidance section and `--guidance FILE`; comparison keeps the sign of zero.
* rules.js roundValue: integer units now return +0 like Python's int() (found by the fuzz; -0.3 mg → 0).
* Step 2: settings.js guidance keys pass their registry/validation/precedence vectors; a 'object' + 'list' type
  validates like pydantic (field order, then "Extra inputs are not permitted" per unknown key, "; " joined).

## Handoffs / findings for other owners
* app/guidance/score.py:499 `max(0.0, dev) ** 2`: glibc pow differs from x*x by 1 ulp in ~0.08 % of inputs
  (measured), so the server's own result can depend on the C library; the twin uses x*x. Suggest `d = max(0.0, dev); d * d`.
* settings.js still lacks ai.* (9 keys) and food.* (4 keys) registry entries (AI and barcode roles): run_vectors
  settings section fails on them only.

## Decisions
* Engine namespace KH.guidanceEngine (KH.guidance is the view helper namespace).
* Files mirror the Python modules (state/vectors folded into rules.js, topics into messages.js).

## Commands
    node tests/js/run_vectors.mjs
    python3 $S/fuzz/gen.py SEED N $S/fuzz/casesSEED.json && node tests/js/run_vectors.mjs --guidance $S/fuzz/casesSEED.json
    python3 -m pytest -q
