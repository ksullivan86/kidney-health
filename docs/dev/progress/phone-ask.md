# phone-ask: Ask and meal photos on the iPhone app

Status: in progress

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
  not_opted_in, server_off); ask.js and views/ai.js word them.

## Done
* app/static/js/mock/ai.js (chat route, reasons, trust), mock/server_api.js (foodHere), views/ask.js (device texts, trust
  line, no Undo on server saves), views/ai.js (status carries phone, photo line on Add), app/ai/chat_save.py + routes.py
  docstring, tests/test_ai_chat_save.py matrix row.
* tests/js/server_ask.mjs (28 checks), tests/js/ask_phone.test.mjs (9 tests) pass. server_services, server_changes,
  device_mode, run_vectors still pass.

## Next
* pytest wrapper + static checks (tests/test_server_ask_phone.py), real-gateway chat pytest, e2e case, docs, CHANGELOG.

## Commands
node tests/js/server_ask.mjs; node --test tests/js/ask_phone.test.mjs; node tests/js/run_vectors.mjs
