Status: in progress (full pytest run pending)

# phone-own-key: the person's own AI key on the iPhone app (owner, 2026-11-25)

Base: `git reset --keep worktree-agent-a140ec927b7fd74a2` (release branch + Ask on the phone). Avoid profile.js, settings
registry, gateway BODY_KEYS, ServerAPI.swift settings keys (helper `height-units` edits those).
Coordinator clarification (2026-11-25): it must work with no server ever paired; screens must read right with no server.

## Decisions
* Providers: only the server's `user_allowed` presets (app/ai/presets.py): OpenAI (api.openai.com/v1), OpenRouter
  (openrouter.ai/api/v1), Nous Portal (inference-api.nousresearch.com/v1). All speak OpenAI Chat Completions, so the app has one
  wire format. Hosts and quirks are fixed in Swift (OwnAI.swift); tests/test_phone_own_key.py checks they equal presets.py.
  The person enters the model (OpenAI prefilled with the preset default; the others have none).
* The app builds the request from ai-prompts.json `own_key` (system prompt, json_schema/prompt templates, schema) so the page can
  only name a task and hand its data; the app refuses any task not on its list and photos unless the switch is on.
* Order (js/mock/ai.js): server (D2, unchanged) → own key (describe; photos with switch) → iPhone's model → no AI. device_only
  skips both. Own key moves on only for offline/not_available; key_refused → 502, rate_limited → 429.
* Consent: the web consent sheet (409 consent_required, provider_id -1, purpose text/photos), kept in api._aiOwnConsent.
  The sheet says "this iPhone sends" and shows the own-key line instead of the privacy filter line.
* Name/birth: the phone has no privacy filter twin; the data for these tasks has no name or birth field, and identityIn refuses to
  send text holding the profile's name (or a word of it ≥3 letters) or birth month forms (→ iPhone's model, or 503 identity).
* Ask stays server-only (its tools read the log on the server); Ask tab text says so with the own key named.
* Meal ideas and recipes NOT on the own key: candidates_for_ai / judge_ideas / recipes have no page twin (large). Left for later.

## Done (verified)
* scripts/build_preview.py own_key_prompts(); aijudge.js: extractJson, checkLabel, labelDraft, checkPlate, judgePlate (+ vectors
  extract_json/label/plate in tests/data/ai_device_vectors.json, run_vectors.mjs replay).
* js/mock/ai.js own-key section; views/ai.js (consent text, where list, own key part, photo texts); views/ask.js text.
* iOS: OwnAI.swift, Keychain ownAIKey, FoodServices bridge kinds, KeysView section, ContentView footer, PhoneTests case.
* Tests: tests/js/own_key.mjs (59 checks), tests/test_phone_own_key.py (5), test_ai_device_vectors/test_server_ask_phone/
  ask_phone.test.mjs updated; tools/e2e/device_mode.py own_key_walk (104 passed in total).
* Docs: note 39 §6.5, ARCHITECTURE Device mode, handbook app/install.md + app/ai.md, docs/privacy.md, CHANGELOG 0.25.0 Added.

## Commands
node tests/js/own_key.mjs; node tests/js/run_vectors.mjs; node --test tests/js/ask_phone.test.mjs
python -m pytest -q tests/test_phone_own_key.py tests/test_ai_device_vectors.py tests/test_ios_app.py tests/test_server_ask_phone.py tests/test_server_services_phone.py
python tools/e2e/device_mode.py; ruff check <changed py files>
Swift is not compiled here (no macOS); the CI ios-app job builds it.
