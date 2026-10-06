Status: in progress

# frontend-targets (M2): UI, demo twins and mock routes for personalised targets and labs

Spec: docs/dev/research/05-personalized-targets.md §4.8 (UI), §4.5 (note texts), §4.2 (inputs), §7 C7/C8;
API: ARCHITECTURE.md "M2 API: targets and labs"; backend: app/targets.py, app/target_rules.py,
app/kidney_function.py, app/units.py, app/labs.py, app/profile.py (not mine, read only).
Ports 8350–8359. Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/frontend-targets/

## Plan (sub-steps)
1. js/engine/settings.js: the 7 new registry keys (handoff in docs/dev/progress/targets.md) — next
2. JS twins: js/engine/targets.js (rewrite to app/targets.py), js/engine/kidney_function.js (units + eGFR + card);
   tests/js/run_vectors.mjs replays targets_vectors.json and kidney_function_vectors.json
3. Mock routes: js/mock/profile.js (new fields, validation, 422 refusals, settings-driven suggestion), js/mock/labs.js
   (POST/GET/DELETE /api/labs, GET /api/labs/kidney-function), export zip gets labs
4. Profile UI: "About you" fields, conditional dialysis/transplant fields, suggestion diff, "Why this number?",
   refusal states, missing-input prompts, about-X protein, fibre min-only rendering
5. Labs view (js/views/labs.js + css/labs.css): entry with unit picker and echo, history per analyte, eGFR card,
   potassium banner, "Review suggested targets" prompt
6. e2e: tools/e2e/parity.py routes, preview build + sandbox.py + regress.py, Chromium walks 375/1280 light/dark
7. Docs: ARCHITECTURE frontend module list, docs/targets-and-labs.md (UI), handbook page if needed; final pytest

## Done (and how verified)
(nothing yet)

## Decisions (and why)

## Commands
* `node tests/js/run_vectors.mjs`
* `python3 -m pytest -q -p no:cacheprovider tests/test_rules_vectors.py tests/test_settings_ui.py tests/test_targets_vectors.py`
