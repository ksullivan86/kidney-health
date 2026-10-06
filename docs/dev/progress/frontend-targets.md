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
   (POST/GET/DELETE /api/labs, GET /api/labs/kidney-function) — DONE (the demo has no export zip at all)
4. Profile UI: "About you" fields, conditional dialysis/transplant fields, suggestion diff, "Why this number?",
   refusal states, missing-input prompts, about-X protein, fibre min-only rendering — DONE (first pass, walked)
5. Labs view (js/views/labs.js + css/labs.css): entry with unit picker and echo, history per analyte, eGFR card,
   potassium banner, "Review suggested targets" prompt — DONE (first pass, walked)
6. e2e: tools/e2e/parity.py routes, preview build + sandbox.py + regress.py, Chromium walks 375/1280 light/dark
7. Docs: ARCHITECTURE frontend module list, docs/targets-and-labs.md (UI), handbook page if needed; final pytest
   — docs DONE (ARCHITECTURE module list + "Frontend (M2 targets)" + parity paragraph; docs/targets-and-labs.md
   "In the app" + maintainer pointers; handbook app/first-setup.md, app/targets-and-warnings.md, app/index.md: the
   targets/labs parts no longer say "coming in v0.3"; strict mkdocs build, build_handbook --check, link test with
   HANDBOOK_BUILT_SITE all pass). Other features' "coming in v0.3" notes are left to their owners / M3.

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

* Step 3: js/mock/profile.js (v0.3 fields + pydantic-exact validation incl. blank→null, lax bools, past-date and
  birth-month checks; suggestion via KH.targets.suggestFromRecords with the person's newest labs and the targets.*
  settings; 422 {detail, code}), js/mock/labs.js (POST with LabCreate order + extra=forbid + conversion errors, GET with
  analyte/limit validation, DELETE incl. non-numeric id 400, kidney-function from the last 365 days; rows scoped by user
  id), seed.js gives Sam a birth month, activity and lab history (and the HD demo urine + labs), core.js KH.api gains
  labs/addLab/deleteLab/kidneyFunction. Server messages probed first with $S/probe.py (cases1/2.json).
  tools/e2e/parity.py: section 11 (11a profile fields, 11b labs, 11c suggestions over 16 profiles x 4 lab sets + the
  targets.* settings), `--sections`, error `code` compared (high severity), demo reset clears labs.
  `python3 tools/e2e/parity.py --port 8352 --static-port 8353 --out $S/parity --sections 0,11`: 696/696 checks,
  24,481 leaves; a mutated 422 code made 12 checks fail.

* Steps 4–5 (first pass): index.html Profile rewritten (About you / Kidneys and diabetes / Blood and urine tests /
  Daily targets with fibre goal and calcium range, review + refusal notices, form error alert), #view-labs added;
  js/views/profile.js rewritten, js/views/labs.js (KH.labs helpers + view), css/labs.css, profile.css additions,
  today.js goal-only (fibre) and "about X" (protein min=max) bars, core.js KH.forms field-error helpers + VIEWS 'labs'
  + STATUS_ORDER fiber_g, settings.js lab-units preference + admin "Personalised targets and lab results" group.
  Walk script $S/walk.py (server and ?mock=1, 375x812 light and 1280x800 dark): zero console errors, CSP violations,
  failed requests, horizontal scroll; screenshots in $S/walk/ reviewed (fixed: bold radio/check text, sex select
  truncation, triple error message, long change list on first suggestion).

* Step 6 (part): tools/e2e/regress.py profile section updated to the v0.3 numbers (0.8 g/kg floor, fibre goal,
  range/goal editor) plus 2b about-you round and 2c lab flow (echo, POST, what-it-changed, kidney card, K 6.3 banner,
  delete, review prompt); `--only 375-light --port 8355`: every check PASS except the static `node run_vectors`
  (guidance keys, not mine). tools/e2e/sandbox.py walks the explained suggestion and the Labs view, sweeps #labs:
  20 walks/3 sweeps/probes, only issue left was in-sentence buttons (fixed: missing-input prompt is now buttons).
  tests/test_targets_ui.py (8 static tests: labelled v0.3 controls, choices = server enums, conditional fields,
  range/goal editor, labs analytes/learn pages, demo routes for every labs/profile route, mock field lists = models,
  admin settings group).

## Decisions (and why)
* Labs is a view without a tab (#labs, like Settings), opened from Profile's "Blood and urine tests" card, the
  suggestion's links and the potassium banner: six tabs do not fit 375 px with the guidance work also adding UI.
* The UI shows the suggestion grouped by target: each applied rule's note is paired with the rule by position
  (every rule emits exactly one note, the last note is END; checked: notes.length === rules.length + 1, else the
  notes are not paired). The change list's "Why:" is the deciding rule's first sentence (server text, not new copy).
* Refusals (pregnancy, under 18, < 12 weeks after a transplant) are recognised with the parity-tested twin before
  asking the server, so no request is made that can only return 422 (no console noise); the server still refuses.
  Likewise the lab form runs the twin's conversion/plausibility check before POST (same message as the server).
* Potassium banner: the server's alert right after a POST; otherwise the newest potassium while it is within the
  default 90-day window (twin potassiumAlert). An admin-shortened window is not visible to non-admins, so the banner
  may stay up longer than the suggestion's alert (safety-leaning).
* UI label "Fiber" (registry spelling) although the server's notes say "Fibre".
* halfUp with negative places (calories to 10 kcal) lives in targets.js (`halfUpTo`): rules.js's halfUp builds
  `e-${places}` which is invalid for places < 0, and rules.js is being edited by the barcode role at the same time.

## Commands
* `node tests/js/run_vectors.mjs`
* `python3 -m pytest -q -p no:cacheprovider tests/test_rules_vectors.py tests/test_settings_ui.py tests/test_targets_vectors.py`
