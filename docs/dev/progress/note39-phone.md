Status: in progress (code and tests done; e2e, docs left)

# note39-phone: the phone side of design note 39 (steps 1, 3, 4)

Role: `note39-phone`. Branch: `worktree-agent-a1f6012ad3f84dd14` (fast-forwarded to c7337a6, which has note 39).
Commit own paths only, trailers per the prompt. No push, no PR. Do not edit app/*.py or app/migrations.
Venv: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python; ruff: /root/.local/bin/ruff

## Done
- Step 1 (server_sync.js): a sent row keeps `v` (entry: the server's entry version; other kinds `b:` + FNV-1a of the body sent)
  and `d: 1` when deleted on the phone after sending; status() has changedSince / deletedSince; Settings says so.
  Test: tests/js/server_sync.mjs block 12.
- Bridge `serverApi` (ServerSync.swift) with the allow-list in KidneyHealthCore/ServerAPI.swift (+ ServerAPITests.swift);
  URLSessionTransport.send(method,...), a 180 s session for the gateway; PhoneTests case.
- Token kind from GET /push/v1/about: SyncModel.tokenKind (defaults key "serverOffers"), ContentView line, KeysView line.
- Page: js/mock/server_api.js (about cache, call, failWith, localize, base64); foods.js USDA via server (503/offline → phone key);
  barcode.js via server (its consent question; offline → phone's OFF if on, else "when your server can be reached").
- AI (ai.js): choice rule; viaServer moves on only on unreachable/503/404; /api/device/ai-choice (Use only this iPhone's AI);
  merged /api/ai/status; consent, next-meal, recipes, photos (label, plate, lab report) through the server; lab text only via
  the lab route or the iPhone; Ask (chat) kept off on the phone (server-side saves + server ids until two-way sync).
- views/ai.js: photos go to the mock in DEVICE; Settings → AI features lists where each feature runs + the switch.
- views/settings.js: Token row, add-only hint, "Using your server's food services" line.
- Tests: tests/js/server_services.mjs (63 checks) via tests/test_server_services_phone.py; test_ios_app.py allow-list test.

## Checks that pass
node tests/js/server_sync.mjs; node tests/js/server_services.mjs; node tests/js/device_mode.mjs; node tests/js/run_vectors.mjs;
pytest tests/test_ai_ui.py tests/test_ask_ui.py tests/test_device_ui.py tests/test_ios_app.py tests/test_lab_photo_ui.py
tests/test_ai_device_vectors.py tests/test_device_mode.py tests/test_server_sync_phone.py tests/test_server_services_phone.py

- e2e: tools/e2e/device_mode.py both_ways_walk (63 passed with the two existing walks).
- Docs: ARCHITECTURE "Device mode" (step 1 in the queue, a new bullet for steps 3 and 4, tests), handbook app/install.md
  ("With a token both ways"; NOTE39 in handbook/sources.yml, then scripts/build_handbook.py), CHANGELOG Unreleased, note 39 status.
- ServerAPI keeps the query percent-encoded as the page sent it.

## Next
- Full `python -m pytest` run (in progress at the time of writing); then the hand-off report.

## Left for later (not in steps 1, 3, 4 as built)
- Ask (chat) through the server: off on the phone until step 6 (server-side saves, server row ids).
- Voice (transcribe), withdrawing consent, the AI activity list: not on the allow-list.
- Recipe import from a page, Instacart, Grocy etc. (step 9).
- The token's end date and reminder on the phone (§5.1) need the server to say the date (about or check); not built.

## Decisions
- `about` shape is not fixed by the note: read leniently (top level or `features`: usda_search/usda, barcodes/barcode, ai.routes).
- 404 from an AI route also moves on (a server with AI off answers 404 as if not registered); never a safety answer.
- Allow-list adds PUT /api/me/settings (body only food.off_consent: the server's OFF consent question) and PATCH /api/me/ai
  (body only opt_in), both limited in the app by key.
