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
(none yet)

## Python
`PY=/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python`
