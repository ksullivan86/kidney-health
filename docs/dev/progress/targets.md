Status: in progress

# targets (M2): personalised targets, labs, eGFR

Spec: docs/dev/research/05-personalized-targets.md (§4.2–§4.9, §5, §7, §10 overrides) + ARCHITECTURE.md v0.3
(item 10: 0.8 g/kg protein floor with diabetes at G3a–G5 without dialysis). Ports 8300–8309.
Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/targets/

## Plan (sub-steps)
1. m004_targets_labs.py (user_profiles columns + lab_results) + version-agnostic migration tests — DONE
2. app/units.py, app/kidney_function.py (+ tests U1–U7, E1–E10) — DONE
3. app/target_rules.py + app/targets.py (+ tests TV01–TV23, properties) — DONE
4. nutrients.suggest_targets / dosing_weight wrapper + §5.3 test changes + targets_by_stage.json — DONE
5. models + profile fields + GET suggested-targets (rules/derived/missing_inputs/alerts, 422 refusals) — DONE
6. app/labs.py router + main.py include + settings keys §4.9 (+ regenerate settings_vectors.json) — DONE
7. export/delete (account.py minimal), API tests (isolation, auth), migration from populated v3 — DONE
8. parity vectors tests/data/targets_vectors.json + kidney_function_vectors.json (+ generators, staleness test)
9. docs/targets-and-labs.md, ARCHITECTURE "M2 API: targets and labs", docs/ROADMAP.md, live smoke on 8300

## Done (and how verified)
* Step 1: app/migrations/m004_targets_labs.py; tests/test_migration_m004.py (populated v3 → v4, idempotent,
  partial, cascade, fresh = upgraded). tests/test_migrations.py, test_migration_v3.py and (this attempt)
  test_admin_cli.py made version-agnostic (db.SCHEMA_VERSION) so later steps need no edits there.
* Steps 2–4: app/units.py (reviewed: plausibility judged on the shown value, messages name the entered unit),
  app/kidney_function.py (CKD-EPI 2021 cr / cr-cys, 2012 cys, G/A categories, assess() card),
  app/target_rules.py (catalogue, numbers, note texts), app/targets.py (Inputs, reference_weight, eer_kcal,
  suggest, suggest_from_records, fresh_labs, OutOfScope), nutrients.suggest_targets/dosing_weight wrappers,
  targets_by_stage.json (C1 citations, C1b 0.8 rows), §5.3 test changes in test_nutrients.py and test_api.py.
  Tests: tests/test_units.py, tests/test_kidney_function.py, tests/test_targets.py (all 23 spec vectors from
  tests/data/personal_target_vectors.json = §5.1 JSON verbatim, C2 properties over 1500 seeded profiles, every
  threshold edge). `python3 -m pytest tests/test_targets.py tests/test_units.py tests/test_kidney_function.py
  tests/test_nutrients.py tests/test_api.py` green; full suite green at the step-1 baseline.

## Decisions (and why)
* `activity` column is nullable (NULL = not chosen): §4.9 `targets.default_activity` and §4.6
  `missing_inputs: ["activity"]` need "not chosen" to be distinguishable; spec SQL said NOT NULL DEFAULT.
* Profile columns go on `user_profiles` (contract table "Database migrations"), not the frozen `profile`.
* Everything judged on the shown value (one decimal; eGFR integer; BMI one decimal; weight-loss % one decimal),
  as the spec does for labs, so a note never contradicts its own number.
* eGFR source choice: newest date first, then lab eGFR > cr-cys (same day) > cr > cys (§4.3 "same day … otherwise
  whichever is newer"). No age → formulas unavailable, an older lab eGFR may still be used.
* Calcium at age 18 uses the IOM 2011 14–18 row (1300/3000): the 19–50 row would be wrong for an 18-year-old.
* L-BIC22 and L-BIC18 both apply below 18 (fruit/veg + 6.1.2 sentence, then the PP 3.10.1 sentence).
* Lab rules off (`targets.lab_rules_enabled=false`): labs ignored for targets, risk and notes; K-0/PH-0 say "this
  server does not change it for blood test results"; the K ≥ 6.0 alert stays (safety).
* Project wording added where the spec's text could not be used as is (all marked in target_rules.py):
  E-4.floor, E-4 insulin sentence only with diabetes, E-PD.missing (PD without dialysate kcal: v0.2 had this hint),
  PH-2.none (transplant G1–G3b), K-0/PH-0 labs-off variants, kidney-function messages other than G-1.
* Lab dates up to one day after the server's date count as fresh (time zones); see labs API for validation.

* Steps 5–7: models.py (Sex/Activity/Analyte, ProfileUpdate fields with ""→null, validate_birth_month,
  validate_past_date with one day of time-zone slack, Profile fields, SuggestedRange/AppliedRule/SafetyAlert,
  LabCreate/LabResult/LabCreated/LabList/KidneyFunction), profile.py (fields, reset-to-default on null, suggestion
  via targets.suggest_from_records + settings + newest labs, 422 `{"detail", "code"}`), app/labs.py (POST/GET/DELETE,
  kidney-function), main.py (1 import + 1 include_router), settings_registry.py (§4.9 keys), account.py
  (lab_results + labs.csv with the canonical unit), tests/test_targets_api.py (58 tests: fields, validation,
  suggestion, refusals, labs, alerts, settings C6, two-person isolation, anonymous 401, export, deletion).
  tests/data/settings_vectors.json regenerated (gen_settings_vectors.py).

## Handoff to the frontend builder (app/static is not mine)
`node tests/js/run_vectors.mjs` (and so tests/test_rules_vectors.py::test_js_engine_matches_vectors and
tests/test_settings_ui.py::test_engine_registry_lists_every_server_key) fail until app/static/js/engine/settings.js
DEFS gains the seven keys below (sorted by key: the targets.* ones after registration.mode, user.units.labs last):

    { key: 'targets.default_activity', type: 'choice', options: ['inactive', 'low_active', 'active', 'very_active'], default: 'inactive', scope: 'instance', env: null, label: "Activity level used until a person chooses theirs", help: "Used for the calorie estimate (2023 Dietary Reference Intakes)." },
    { key: 'targets.lab_fresh_days.albumin', type: 'int', min: 1, max: 365, default: 180, scope: 'instance', env: null, label: "An albumin result counts for (days)", help: "" },
    { key: 'targets.lab_fresh_days.bicarbonate', type: 'int', min: 1, max: 365, default: 180, scope: 'instance', env: null, label: "A bicarbonate result counts for (days)", help: "" },
    { key: 'targets.lab_fresh_days.phosphate', type: 'int', min: 1, max: 365, default: 90, scope: 'instance', env: null, label: "A phosphate result counts for (days)", help: "" },
    { key: 'targets.lab_fresh_days.potassium', type: 'int', min: 1, max: 365, default: 90, scope: 'instance', env: null, label: "A potassium result counts for (days)", help: "" },
    { key: 'targets.lab_rules_enabled', type: 'bool', default: true, scope: 'instance', env: null, label: "Let lab results change suggested targets", help: "Off: potassium and phosphorus suggestions use the stage defaults and lab notes are left out. The warning for a very high potassium result is always shown. Keep it off on public demo servers until a clinician has reviewed the lab rules." },
    { key: 'user.units.labs', type: 'choice', options: ['us', 'si'], default: 'us', scope: 'user_default', env: null, label: "Units for lab results", help: "us: mg/dL (creatinine, phosphate), g/dL (albumin), mg/g (urine albumin), % (HbA1c). si: µmol/L, mmol/L, g/L, mg/mmol, mmol/mol. Only the unit offered first changes; any unit can still be entered." },

* Step 8: tests/data/gen_targets_vectors.py → targets_vectors.json (TV01–TV23 + 110 edge cases + 120 seeded random
  + 64 v0.2-wrapper cases, tables; rules as catalogue keys to keep ~1 MB), gen_kidney_function_vectors.py →
  kidney_function_vectors.json (unit table, conversions incl. refusals, eGFR, categories, ages, 24 cards),
  tests/test_targets_vectors.py (staleness + coverage). `python3 tests/data/gen_*_vectors.py --check`.
* Step 9: docs/targets-and-labs.md, docs/ROADMAP.md (C10, C11/§8, EKFC, MHDE, SARC-F/FRAIL), ARCHITECTURE.md
  (v0.2 "Suggested targets" rewritten to the v0.3 rules; "M2 API: targets and labs" appended), docs/privacy.md
  (new optional health data listed).

## Not mine, flagged for others
* Handbook (handbook owner / M3): handbook/docs/app/targets-and-warnings.md ("Suggested targets", "Personalized
  targets (coming in v0.3)") and app/first-setup.md line ~68 still say "coming in v0.3" / "today's app shows
  0.6–0.8"; the numbers there already match this implementation, only the tense needs flipping.
* README "How targets and warnings work" (note 05 C9) and CHANGELOG (M3 integration).
* docs/diet-guide.md becomes a handbook pointer (handbook integration task); no test needed a number change.

## Next
Live smoke on port 8300 (uvicorn, curl), full `python -m pytest`, mark complete.

## Commands
* `python3 -m pytest -q -p no:cacheprovider tests/test_targets.py tests/test_units.py tests/test_kidney_function.py tests/test_nutrients.py`
* `ruff check --line-length 140 app/targets.py app/target_rules.py app/kidney_function.py app/units.py`
