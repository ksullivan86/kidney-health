Status: in progress (2026-11-26)

# phone-care: Care team notes and suggestions on the iPhone app, through the paired server

Owner, 2026-11-26: "Should the phone show care team notes?" "yes". Anything the web app does with a server should be in the app.

## Plan
1. Server: gateway `ALLOWED` gains `GET /api/me/notes`, `POST /api/me/notes/{note_id}/read`, `DELETE /api/me/notes/{note_id}`,
   `GET /api/me/suggestions`, `POST /api/me/suggestions/{suggestion_id}/accept|decline`. `/api/me/shares` and `/api/shared`
   stay never (share links). The read-only Settings summary comes from `GET /push/v1/about` → `care_team`
   (`sharing.care_team_summary`: enabled, notes, team [{name, role, areas}], on [{name, role}]). Tests in test_app_gateway.py.
2. Swift allow-list: the six routes; `{note_id}` and `{suggestion_id}` placeholders (digits, as `{food_id}`). Pins in
   test_ios_app.py and ServerAPITests.swift.
3. Phone JS: `js/mock/server_care.js` (device only). care.js's `/api/me/notes*` and `/api/me/suggestions*` routes ask it first:
   paired → the server (no cache of note text; offline → 503 "cannot be reached"), not paired → the phone's own (as before).
   Accept needs sync both ways on (the entries come down through the change feed; a sync runs after). `GET /api/device/care-team`
   for Settings. Settings → Care team shown read-only when paired, hidden otherwise.
4. Node tests, e2e walk, docs (push.md, handbook care team page, ARCHITECTURE, CHANGELOG Unreleased).

## Done (all committed and pushed unless said)
* Server: ALLOWED +6 routes, `sharing.care_team_summary`, about `care_team` (da92815); tests in tests/test_app_gateway.py
  (pinned list, never-list, notes read/412/428/delete, suggestions, not-yours 404, about). One hunk is still uncommitted: the
  never-list additions in `test_the_allow_list_is_pinned` share a hunk with phone-devices' lines (commit when they have).
* Swift allow-list + idSegments, ServerAPITests.swift (d35ce51); pin in tests/test_ios_app.py (da92815).
* Phone JS (1befe81): js/mock/server_care.js, care.js `mineRoute`, server_api.js `careTeam`, sharing.js `deviceBlock`,
  settings.js `renderCare` (in phone-extras' 01aa262), profile.js card, notes.js, suggestions.js `waiting`, base.css.
  index.html / sw.js script lines (da92815).
* Tests: tests/js/server_care.mjs, tests/test_server_care_phone.py (real server relay), tests/test_care_team_ui.py,
  tests/js/server_services.mjs; e2e `care_walk` in tools/e2e/device_mode.py (b591b65; all PASS with
  `$PY scratchpad/care_only.py <out> care_walk`).
* Docs: docs/push.md, docs/api/openapi.json, handbook install.md + settings-and-keys.md, CHANGELOG Unreleased, ARCHITECTURE.
* Commit trick used for shared files with other agents' hunks: filter my hunks into a patch, `git apply --cached`, commit with an
  otherwise empty index (checked first).

## Next
* Full `python -m pytest -q`; e2e device_mode full run; mark complete.
* Seen, not mine: tests/js/server_sync.mjs fails on a 'reminders' bridge request (phone-reminders).

## Python
`PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python`
