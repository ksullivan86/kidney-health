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
5. models + profile fields + GET suggested-targets (rules/derived/missing_inputs/alerts, 422 refusals)
6. app/labs.py router + main.py include + settings keys §4.9 (+ regenerate settings_vectors.json)
7. export/delete (account.py minimal), API tests (isolation, auth), migration from populated v3
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

## Next
Step 5: models.py (Sex, Activity, Analyte literals, ProfileUpdate fields with "" → null, Profile fields,
LabCreate/LabResult, SuggestedTargets additive keys), profile.py (row_to_profile new fields, PUT merge with
NOT NULL reset-to-default on null, suggested-targets via targets.suggest_from_records + settings + labs, 422
`{"detail": message, "code": code}` per ARCHITECTURE error shape).

## Commands
* `python3 -m pytest -q -p no:cacheprovider tests/test_targets.py tests/test_units.py tests/test_kidney_function.py tests/test_nutrients.py`
* `ruff check --line-length 140 app/targets.py app/target_rules.py app/kidney_function.py app/units.py`
