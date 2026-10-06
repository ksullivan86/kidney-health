Status: in progress

# targets (M2): personalised targets, labs, eGFR

Spec: docs/dev/research/05-personalized-targets.md (§4.2–§4.9, §5, §7, §10 overrides) + ARCHITECTURE.md v0.3
(item 10: 0.8 g/kg protein floor with diabetes at G3a–G5 without dialysis). Ports 8300–8309.
Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/targets/

## Plan (sub-steps)
1. m004_targets_labs.py (user_profiles columns + lab_results) + version-agnostic migration tests
2. app/units.py, app/kidney_function.py (+ tests U1–U7, E1–E10)
3. app/target_rules.py + app/targets.py (+ tests TV01–TV23, properties)
4. nutrients.suggest_targets / dosing_weight wrapper + §5.3 test changes + targets_by_stage.json
5. models + profile fields + GET suggested-targets (rules/derived/missing_inputs/alerts, 422 refusals)
6. app/labs.py router + main.py include + settings keys §4.9
7. export/delete (account.py minimal), API tests (isolation, auth), migration from populated v3
8. parity vectors tests/data/targets_vectors.json + kidney_function_vectors.json (+ generators, staleness test)
9. docs/targets-and-labs.md, ARCHITECTURE "M2 API: targets and labs"

## Done
* Step 1: app/migrations/m004_targets_labs.py (user_profiles columns + lab_results, FK cascade) and
  tests/test_migration_m004.py (populated v3 → v4, idempotent, partial, cascade, fresh = upgraded).
  Made tests/test_migrations.py and tests/test_migration_v3.py version-agnostic (db.SCHEMA_VERSION)
  so m005–m007 need no edits there. Verified: pytest tests/test_migration*.py tests/test_api.py.

## Decisions
* `activity` column is nullable (NULL = not chosen): §4.9 `targets.default_activity` and §4.6
  `missing_inputs: ["activity"]` need "not chosen" to be distinguishable; spec SQL said NOT NULL DEFAULT.
* Profile columns go on `user_profiles` (contract table "Database migrations"), not the frozen `profile`.

## Next
