Status: complete

# phone-ask: Ask and meal photos on the iPhone app

## Decisions
* Ask on the phone runs only on the paired server's AI, only with a token both ways and while two-way sync is active
  (`M.serverChanges.active()`); the iPhone's own model has no chat. Voice stays off.
* One source of truth for saves: the phone always sends `trust: "ask"`; the server (app/ai/chat_save.effective_trust) now gives
  "ask" whatever is stored when the page asks for it, so it writes nothing and answers with a card. Save on the card goes through
  the phone's own routes with the card's foods mapped to phone ids (`M.serverApi.foodHere`) and the server's client_id kept; step 4
  sync sends the row up once. A food not on the phone -> question, no card. An older server that still saved: card without Undo,
  "Saved on your server…", `serverSync.soon()`.
* Before a chat, waiting phone rows are sent first (max 5 s) so the assistant reads the same log.
* GET /api/me/ai → phone.ask / phone.photos give a reason (not_paired, not_both_ways, offline, device_only, not_synced,
  not_opted_in, server_off); ask.js and views/ai.js word them. The Ask tab is always shown on the phone.
* Plate photo was already wired through the server; the Add screen now says where it comes from when it is not offered.

## Done (all verified)
* Code: app/static/js/mock/ai.js, mock/server_api.js (foodHere), views/ask.js, views/ai.js, app/ai/chat_save.py, app/ai/routes.py
  (docstring).
* Tests: tests/js/server_ask.mjs (28 fake checks, plus --relay against the real server), tests/js/ask_phone.test.mjs (9),
  tests/test_server_ask_phone.py (5, incl. the real chat through the real gateway with a fake AI and trust "always"),
  tests/test_ask_ui.py and tests/test_ai_chat_save.py updated, tools/e2e/device_mode.py (no_server_ask + ask_walk): 94 passed.
* Docs: handbook app/install.md, ARCHITECTURE Device mode, note 39 (status + §6.4), docs/ai.md, CHANGELOG 0.25.0 Added.

## Commands
node tests/js/server_ask.mjs; node --test tests/js/ask_phone.test.mjs; node tests/js/run_vectors.mjs
python -m pytest -q tests/test_server_ask_phone.py tests/test_ask_ui.py tests/test_ai_chat_save.py tests/test_server_services_phone.py
python tools/e2e/device_mode.py
