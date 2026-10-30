Status: complete

# Care team (design note 25)

Branch: worktree-agent-a0c4dba93435a1585, fast-forwarded to next-8 (897538c, has the AI naming change) before starting.

## Done
- Design note `docs/dev/research/25-care-team.md` (decisions: saved meals not in this version; helper may change/remove any
  planned entry except a low treatment; Care helper adds food log; invite answers the same whether the name exists).

- Server: `app/migrations/m027_care_team.py`; `app/sharing.py` (roles, user name invites, role change, `care_helper`
  dependency, helper routes under `/api/shared/{id}/`: foods, plan/shopping, log POST/batch/PUT/DELETE, clear-planned,
  guidance/plan-days with saved meals forced off); `app/log.py` (`added_by` on entries, not in version/export);
  `app/audit.py` care.* actions; setting label/help (`app/settings_registry.py`, `js/engine/settings.js`); OpenAPI
  regenerated (`app/openapi_doc.py` 409/429 lists). Vectors: settings + import regenerated; `node tests/js/run_vectors.mjs` passes.
- Tests: `tests/test_care_team.py` (new), `test_sharing.py`, `test_sharing_security.py`, `test_isolation_v03.py` updated. They
  pass with test_log_if_match, test_export_delete, test_data_import, test_auth_coverage, test_planning, test_openapi*.
- Seen, not mine: `tests/test_settings_ui.py::test_the_assistant_card_waits...` expects the old "Assistant access" title
  (the AI naming WIP renamed it to "Outside AI apps"). Fix the test's string at the end.
- Note: do not pass `-p no:logging` to pytest (caplog tests then error).

- UI: Settings → Care team section `#set-care` (index.html, settings.js renderCare/openSection, sharing.js rewritten for
  roles, invites, role select, Leave, Plan meals); Profile card `#profile-care`; Today "Added by"; Plan tab "Planning for"
  (`js/views/careplan.js`, plan.js hands over via `KH.carePlan.onShow()`); CSS in plan.css. Activity labels for care.*.
- Demo: `js/mock/care.js` (sample Care team; Ana's days as a swapped world), old sharing-off routes removed from mock/auth.js.
- Tests: `tests/test_care_team_ui.py` (+ `tests/js/care_demo.mjs`), test_sharing_ui.py and sharing_list_loading.test.mjs
  updated; test_settings_ui.py's stale "Assistant access" title fixed to "Outside AI apps". All pass.

- e2e: `tools/e2e/sharing.py` extended (invites, same answer, Kim plans Ana's day, Added by, demo). Run with system
  `python3` (it has Playwright): `python3 tools/e2e/sharing.py --port 8196 --out <scratch>/e2e-sharing` → 61 passed, 0 failed.
- Docs: docs/accounts.md (## Care team, old anchor kept), handbook settings-and-keys (#sharing anchor kept), caregivers,
  planning-and-menus, sources.yml NOTE25 (+ generated includes), ARCHITECTURE.md (module, step 27, routes, Care team section),
  deployment.md, ROADMAP.md, CHANGELOG Unreleased, try-it-for-ckd.md (the demo changed).

- Full pytest (2026-10-30): everything passes except 7 tests that still expect the wording from before the AI naming change
  (test_ask_ui.py x5, test_device_tokens.py::test_the_switches_are_independent,
  test_mcp_write.py::test_a_read_only_token_cannot_save_and_nothing_is_saved: "Assistant access", "Ask conversations" and
  similar). They belong to the AI naming work and are unrelated to the Care team. Ruff, OpenAPI `--check`, settings and import
  vectors `--check` and `node tests/js/run_vectors.mjs` pass.

## Left for later (design note 25 §10)
Per-permission switches, a Caregiver role who logs eaten food, letting a Care helper use saved meals, the person approving
changes, and a clinician role with notes.: Settings → Care team section (`js/views/sharing.js`), Profile link, Today "Added by", Plan "Planning for" (`js/views/careplan.js`).
4. Mock twin (sample Care team), Node UI tests.
5. e2e `tools/e2e/sharing.py` extended.
6. Docs (accounts.md, handbook caregivers + app pages, ARCHITECTURE.md, CHANGELOG).
7. Full pytest.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python
$PY -m pytest -q -p no:cacheprovider --basetemp=<scratch>/bt tests/test_care_team.py tests/test_sharing*.py
