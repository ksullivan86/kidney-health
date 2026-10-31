Status: in progress

# Full Care team (design note 29, release 0.18 work)

Branch: worktree-agent-a39dd5dde408ee2a1, fast-forwarded to next-8 (4c139f2, 0.17.0) before starting.

## Done
- Design note `docs/dev/research/29-full-care-team.md` with the Decisions section.
- Migration `app/migrations/m031_care_team_full.py` + `tests/test_migration_m031.py` (passes; old shares keep meaning).
- Server: `app/sharing.py` (switches, roles as presets incl. caregiver/custom, PUT /switches, care_helper / care_planner /
  care_food_search / care_saved_meals / care_suggester dependencies, eaten logging, low-treatment 403, own-eaten-only 403,
  saved meals list/apply, plan-days with saved meals when switched on, expire_suggestions in expire()),
  `app/care_suggestions.py` (send/sent/list/accept/decline, fit, export_rows), `app/meals.py` (apply_template with added_by),
  `app/audit.py` (care.switches_changed, care.food_logged, suggestion.*), export key `care_suggestions` (app/account.py),
  import skips it (app/data_import.py + mock import.js + settings.js IMPORT_NEVER_SENT), openapi_doc 409/429 lists,
  test_accounts insert sets may_plan.
- Tests: `tests/test_care_team_full.py` (new, 33 tests), test_care_team.py / test_sharing_security / test_isolation_v03 /
  test_export_delete updated; import vectors regenerated (`gen_import_vectors.py --check` ok); `node tests/js/run_vectors.mjs` ok.
  Verified: test_care_team*, test_sharing*, test_isolation_v03, test_export_delete, test_test_accounts, test_auth_coverage,
  test_activity, test_data_import*, test_import_vectors all pass.

## Next
3. OpenAPI regen (scripts/gen_openapi.py, then --check); new care_vectors.json (role_of + note checks) replayed by run_vectors.
4. UI: sharing.js switches, careplan.js (eaten, saved meals, suggest), Plan "Suggestions for you", activity labels.
5. Demo twin js/mock/care.js; Node tests; e2e tools/e2e/sharing.py.
6. Docs: ARCHITECTURE, docs/accounts.md, handbook, test-the-full-app, CHANGELOG Unreleased.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -q -p no:cacheprovider --basetemp=<scratch>/bt tests/test_care_team*.py tests/test_sharing*.py
