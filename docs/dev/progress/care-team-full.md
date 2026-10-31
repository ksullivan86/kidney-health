Status: in progress (all built and checked; the full suite is the last step)

# Full Care team (design note 29, release 0.18 work)

Branch: worktree-agent-a39dd5dde408ee2a1, fast-forwarded to next-8 (4c139f2, 0.17.0) before starting. No version bump, no
CHANGELOG release heading (only "Unreleased").

## Done (and how it was checked)
- Design note `docs/dev/research/29-full-care-team.md`, with the Decisions section for the owner.
- Migration `app/migrations/m031_care_team_full.py` (switch columns on shares and care_invites, role mapped once; table
  `care_suggestions`) + `tests/test_migration_m031.py`.
- Server: `app/sharing.py` (SWITCHES, PRESETS, role_of, PUT /switches, care_helper / care_planner / care_food_search /
  care_saved_meals / care_suggester, eaten logging, low treatment 403, own-eaten-only 403, saved meals list/apply, plan-days with
  saved meals when switched on, expire_suggestions), `app/care_suggestions.py` (send, sent, list, accept, decline, fit, export rows),
  `meals.apply_template`, audit actions, export key `care_suggestions` (import skips it), openapi_doc 409/429, test_accounts insert
  sets may_plan. OpenAPI regenerated (`scripts/gen_openapi.py --check` ok).
- Tests: `tests/test_care_team_full.py` (32), updates to test_care_team, test_sharing_security, test_sharing_ui, test_care_team_ui,
  test_isolation_v03 (care_suggestions in MATRIX), test_export_delete, test_demo_local_ui (via tools/e2e/demo_local.py EXPORT_KEYS).
- Parity: `tests/data/care_vectors.json` from `tests/data/gen_care_vectors.py` (roles, limits, sentences, note check) replayed by
  `node tests/js/run_vectors.mjs` against `KH.mock.care`; import vectors regenerated; demo twin `js/mock/care.js` answers every new
  route (`tests/js/care_demo.mjs`).
- Screens: Settings → Care team switches (`js/views/sharing.js`), helping someone (`js/views/careplan.js`), suggestions for you
  on the Plan tab (`js/views/suggestions.js`, `#plan-suggestions`), activity labels, CSS for narrow screens.
- Chromium: `python3 tools/e2e/sharing.py --port 8199 --out <scratch>/e2e-sharing` → 89 passed, 0 failed. (The older step
  "Sam opens the link" timed out twice in about ten runs waiting for `#sheet-share[open]`; it passed on rerun.)
- Docs: ARCHITECTURE.md (files, step 31, /api/me routes, "The full Care team" section, ownership row, v0.18 work note),
  docs/accounts.md, handbook (settings-and-keys, planning-and-menus, caregivers, sources NOTE29), docs/test-the-full-app.md step 11,
  docs/try-it-for-ckd.md, ROADMAP, notes 21 and 25 status lines, CHANGELOG Unreleased.

## Next
- Full pytest run, then mark complete.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -p no:cacheprovider --basetemp=<scratch>/bt tests/test_care_team*.py tests/test_sharing*.py tests/test_migration_m031.py
$PY tests/data/gen_care_vectors.py --check; $PY tests/data/gen_import_vectors.py --check; $PY scripts/gen_openapi.py --check
node tests/js/run_vectors.mjs; node tests/js/care_demo.mjs
python3 tools/e2e/sharing.py --port 8199 --out <scratch>/e2e-sharing
