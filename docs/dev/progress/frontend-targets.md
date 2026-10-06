Status: in progress

# frontend-targets (M2): UI, demo twins and mock routes for personalised targets and labs

Spec: docs/dev/research/05-personalized-targets.md §4.8 (UI), §4.5 (note texts), §4.2 (inputs), §7 C7/C8;
API: ARCHITECTURE.md "M2 API: targets and labs"; backend: app/targets.py, app/target_rules.py,
app/kidney_function.py, app/units.py, app/labs.py, app/profile.py (not mine, read only).
Ports 8350–8359. Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/frontend-targets/

## Plan (sub-steps)
1. js/engine/settings.js: the 7 new registry keys (handoff in docs/dev/progress/targets.md) — DONE
2. JS twins: js/engine/targets.js (rewrite to app/targets.py), js/engine/kidney_function.js (units + eGFR + card);
   tests/js/run_vectors.mjs replays targets_vectors.json and kidney_function_vectors.json — DONE
3. Mock routes: js/mock/profile.js (new fields, validation, 422 refusals, settings-driven suggestion), js/mock/labs.js
   (POST/GET/DELETE /api/labs, GET /api/labs/kidney-function), export zip gets labs
4. Profile UI: "About you" fields, conditional dialysis/transplant fields, suggestion diff, "Why this number?",
   refusal states, missing-input prompts, about-X protein, fibre min-only rendering
5. Labs view (js/views/labs.js + css/labs.css): entry with unit picker and echo, history per analyte, eGFR card,
   potassium banner, "Review suggested targets" prompt
6. e2e: tools/e2e/parity.py routes, preview build + sandbox.py + regress.py, Chromium walks 375/1280 light/dark
7. Docs: ARCHITECTURE frontend module list, docs/targets-and-labs.md (UI), handbook page if needed; final pytest

## Done (and how verified)
* Step 1 (commit fcb8621): settings.js DEFS has the 7 keys; `node tests/js/run_vectors.mjs` settings section now fails only on
  the 4 guidance keys (`guidance`, `guidance.*`), which belong to the guidance frontend role (see guidance.md handoff).
* Step 2: js/engine/kidney_function.js (KH.kidney: analytes, units, convert/echo, plausibility, CKD-EPI, G/A categories,
  ageOn, assess card, rowToLab) and js/engine/targets.js rewritten as the twin of app/targets.py (KH.targets: suggest,
  suggestFromRecords, inputsFromRecords, freshLabs, potassiumAlert, referenceWeight, eerKcal, v0.2 wrapper suggestTargets,
  tables). Rule catalogue/notes/refusals generated from app/target_rules.py into the JS literal (script in scratch).
  run_vectors.mjs: "targets vectors: 1859 checks passed", "kidney function vectors: 140 checks passed"; a mutation
  (POTASSIUM_LOW 3.4) made 6 checks fail. index.html loads kidney_function.js before targets.js; sw.js SHELL_URLS and
  tests/test_frontend_shell.py (engine order assertion) updated.

## Decisions (and why)
* halfUp with negative places (calories to 10 kcal) lives in targets.js (`halfUpTo`): rules.js's halfUp builds
  `e-${places}` which is invalid for places < 0, and rules.js is being edited by the barcode role at the same time.

## Commands
* `node tests/js/run_vectors.mjs`
* `python3 -m pytest -q -p no:cacheprovider tests/test_rules_vectors.py tests/test_settings_ui.py tests/test_targets_vectors.py`
