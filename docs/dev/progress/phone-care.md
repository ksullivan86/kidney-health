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

## Done
* Server (verified: `pytest tests/test_app_gateway.py`): ALLOWED +6 routes; `sharing.care_team_summary`; about `care_team`.
  Tests: pinned list, never-list (`/api/me/shares`, `/api/shared`, writing notes), notes read/412/428/delete, suggestions
  accept/decline, not-yours 404 with the other person's token, about's care_team. NOT YET COMMITTED: app_gateway.py and
  test_app_gateway.py hold phone-devices' uncommitted hunks too (wait, then commit only mine).
* Swift allow-list + idSegments (`{food_id}`, `{note_id}`, `{suggestion_id}`), ServerAPITests.swift (commit d35ce51). The pin in
  tests/test_ios_app.py is written but NOT YET COMMITTED (other agents' hunks in the file).
* Phone JS (commit 1befe81): js/mock/server_care.js, care.js `mineRoute`, server_api.js `careTeam`, views: sharing.js
  `deviceBlock`/`deviceLine`, settings.js `renderCare` device branch (committed by phone-extras in 01aa262 with its own change),
  profile.js card only when paired, notes.js plain error in the app, suggestions.js `waiting`. base.css: #set-care no longer
  forced hidden. index.html and sw.js script lines NOT YET COMMITTED (other agents' hunks).
* Tests: tests/js/server_care.mjs (stand-in + --relay), tests/test_server_care_phone.py (real server relay, passes),
  tests/test_care_team_ui.py (addedText waiting, deviceLine), tests/js/server_services.mjs (readAbout careTeam: null).

## Next
* Commit shared hunks when free: app_gateway.py, test_app_gateway.py, test_ios_app.py, index.html, sw.js.
* e2e walk in tools/e2e/device_mode.py; openapi regen; docs (push.md, handbook care team, ARCHITECTURE, CHANGELOG).

## Python
`PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python`
