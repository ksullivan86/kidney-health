Status: in progress

# Clinician accounts with notes, phase 1 (design note 37)

Branch `clinician-notes` (from origin/main fed556c + cherry-pick of 525fbad, the design note). Schema step **36** (step 35 is
the Web Push reminders helper's; do not touch app/reminders*, app/ai lab features). No push, no PR, no version bump.

## Plan (sub-steps)
1. Migration m036 + sharing.py switch/preset + settings `care_notes.enabled` (CARE_NOTES_ENABLED)
2. app/care_notes.py routes, audit actions, export, data_import skip, hourly view rows
3. Server tests (tests/test_care_notes.py, isolation, migration both orders)
4. Screens: Notes list, Today card, Visit prep line, Write a note, Care team role/switch
5. Demo twin (mock/care.js) + vectors + Node tests
6. Chromium walk tools/e2e/clinician_notes.py
7. Docs, OpenAPI, settings vectors, handbook
8. Full suite

## Done
- Step 1-2 (server): app/migrations/m036_care_notes.py (+ m035_reserved.py placeholder), app/sharing.py (FOOD_SWITCHES,
  SWITCHES += may_note, PRESETS clinician, notes_enabled, care_noter, hourly views via shares.view_hours, last_viewed_area,
  `notes` flag in GET /api/me/shares and /api/shared), app/care_notes.py (8 routes, export_rows), settings `care_notes.enabled`
  (CARE_NOTES_ENABLED; registry + js/engine/settings.js + admin group), audit actions (USER_VISIBLE), export key, import skip.
- Step 3: tests/test_care_notes.py (33 pass); isolation matrix entry; WRITE_CHECKS/READ_CHECKS in test_care_team.py.
- Step 4 (screens): js/views/notes.js (Notes view #notes, Today card, Visit line, #sheet-note, noteButton), index.html, core.js VIEWS,
  sw.js, visit.js + trends.js (Write a note; may_note kept on openShared), today.js (todayCard), sharing.js (Clinician role and
  hint, "Write notes for me" switch, Notes button on Care teams you are on, "Notes from your Care team" button, lastLooked area,
  invite question), settings.js activity labels, css/visit.css. Node: tests/js/notes_ui.test.mjs, tests/js/care_notes_demo.test.mjs;
  pytest wrapper tests/test_care_notes_ui.py.
- Step 5 (part): js/mock/care.js (Dee the Clinician with one unread note; Ana's share has may_note; every note route; KH.mock.care.notes),
  care vectors (gen_care_vectors.py: care_notes section), run_vectors.mjs careVectors replays it; settings + import vectors regenerated.
  Checked: pytest sharing/care/export/isolation/import/settings sets pass; node tests/js/run_vectors.mjs all pass.

- Step 6: tools/e2e/clinician_notes.py (port 8118): 26 passed, 0 failed (2026-11-12). In HARNESSES and tools/e2e/README.md.

- Step 7 (docs): ARCHITECTURE (file list, steps 35/36, ownership row, /api/me/notes rows, GET /api/me/shares, new section "Notes from
  the Care team"), docs/accounts.md, docs/privacy.md, docs/deployment.md + deploy/.env.example + compose.yaml (CARE_NOTES_ENABLED),
  docs/test-the-full-app.md, handbook settings-and-keys + reports-for-your-team + sources.yml NOTE37 (build_handbook regenerated),
  CHANGELOG Unreleased, ROADMAP (phase 1 built, phases 2a-2d), note 37 status. OpenAPI regenerated (+ openapi_doc CONFLICT/RATE_LIMITED).

## Decisions
- Step 35 is held by an empty `m035_reserved.py` because the runner refuses gaps. INTEGRATOR: delete it when merging
  `m035_reminders.py` (discover() refuses two step-35 files, so it cannot slip through). Step 36 does not touch step 35's tables;
  test_care_notes.test_step_36_runs_on_a_database_at_step_34_or_35 runs it after 34 and after 35.
- Hourly view rows need state the audit log cannot hold (audit `at` is wall time, rows are never updated): added
  `shares.view_hours` (JSON {hour, areas, last}) in step 36, like `helper_changes` of step 31. Not in the note's SQL.
- Daily note limit is counted from `care_note.written` audit rows (details carry `at` on the app clock), so withdrawing does not
  reset it.
- Choosing Clinician / may_note while `care_notes.enabled` is off is 400 "Notes are turned off on this server…".
- Note day: up to 365 days back, and up to tomorrow UTC (authors ahead of UTC).
- If-Match is required (428) on the person's read and the author's edit; optional on the author's withdraw.

## Commands
PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
