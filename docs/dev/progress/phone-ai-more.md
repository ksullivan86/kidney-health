Status: complete

# phone-ai-more: more on the iPhone's own AI (owner, 2026-11-25)

Base: release branch claude/adoring-sagan-th5swr (reset --keep, then ff to 9c52473 for the coordinator's own-key prompts change).
Steps: 1 plate/label photos on the iPhone model (iOS 27); 2 meal ideas + AI recipes on own key and iPhone model; 3 Ask (left
server-only, reason below).

## Decisions
* iOS 27 image input is a guess (no macOS). Assumed API: `CGImage` conforms to `PromptRepresentable`, so
  `Prompt { message; image }` + `session.respond(to: Prompt, generating: T.self)` (only that line is new; Prompt builder and
  respond(to:generating:) are iOS 26 API). It lives in OnDeviceVision.swift under `#if canImport(FoundationModels) &&
  KH_ONDEVICE_IMAGES` + `if #available(iOS 27.0, *)`. The project does not set the flag; CI ios-app first runs
  build-for-testing with the flag and, if it compiles, tests with it (notice), else builds without (warning). Turn on for good by
  adding KH_ONDEVICE_IMAGES to SWIFT_ACTIVE_COMPILATION_CONDITIONS once the probe passes.
* Coordinator (9c52473): build_preview.py may import only app.ai.prompts; schemas/config go through committed
  app/ai/own_key_prompts.json (scripts/gen_own_key_prompts.py). next_meal/recipes own-key entries hold "__CANDIDATE_IDS__" where
  the server puts its id list; OwnAI.swift fills in the page's whole-number ids (schema + prompt-mode schema line).
* ai-prompts.json: system, systems {meal, recipe (steps off, [[CONDITION]] kept)}, conditions (all 105 condition_text wordings; the
  app inserts only one of these), tasks {template, system, image} for parse_meal, read_lab_report_text, read_label, plate,
  next_meal, recipes.
* Meal ideas: mode "ideas" only on the phone (rerank/swap/plan → 503 not_on_phone). Recipes: suggest and change, steps off.
* Data budget: own key 80,000 chars (cloud budget 32,768 tokens; never reached), iPhone 5,000 chars (~8 candidates), trimmed
  lowest-ranked first like features.prepare_next_meal / recipes.prepare_recipes. Pinned by test_phone_ai_more budget test.
* Plate "to the plan": the plate flow already has Eaten / Planned (default Planned) for the day on screen; same on the phone
  (POST /api/log/batch to the mock). It never makes a saved meal (server neither).
* Step 3 Ask: not built. Server chat = free text + server-side tools (log, foods, saves) + chat.py answer checks; no twin; a small
  local model writing free text about the person's numbers without those checks is not safe. Ask tab text says it needs the
  server "because it reads your log there and checks every answer".

## Done (verified)
* Step 1: OnDeviceVision.swift, OnDeviceAI.swift (6 tasks, @Generable shapes of plate/label/ideas/recipes), CI probe,
  js/mock/ai.js photoOnDevice + aiStatus.photos, PHOTO_NEEDS text.
* Step 2: app/static/js/engine/aimeal.js (twins), tests/data/gen_ai_meal_vectors.py → ai_meal_vectors.json (31 cases, replayed in
  run_vectors.mjs "ai meal"), js/mock/ai.js mealIdeasHere/recipesHere/onPhone/askPhoneAi, OwnAI.swift next_meal/recipes with
  condition + ids, index.html + sw.js list aimeal.js.
* Tests: tests/js/phone_ai_more.mjs (71 checks), tests/test_phone_ai_more.py (6), updates to own_key.mjs, device_mode.mjs,
  server_services.mjs, ask_phone.test.mjs, test_ai_device_vectors, test_ios_app, test_phone_own_key, test_server_ask_phone;
  PhoneTests.swift (2 cases); tools/e2e/device_mode.py phone_ai_walk (114 passed in total).
* Docs: note 39 §6.6 + status line, ARCHITECTURE Device mode, handbook app/install.md + app/ai.md, docs/privacy.md, CHANGELOG.

## Full run (2026-11-25)
All passed apart from two, both fixed and rerun: tests/data/README.md needed the key list for ai_meal_vectors.json, and
test_ai_privacy_filter.py still expected the line from before the own key (phone-own-key a5f1bc4 added `&& !consent.own_key`).

## Commands
node tests/js/phone_ai_more.mjs; node tests/js/own_key.mjs; node tests/js/device_mode.mjs; node tests/js/server_services.mjs
node tests/js/run_vectors.mjs; node --test tests/js/ask_phone.test.mjs
python tests/data/gen_ai_meal_vectors.py [--check]; python scripts/gen_own_key_prompts.py [--check]
python -m pytest -q tests/test_phone_ai_more.py tests/test_phone_own_key.py tests/test_ai_device_vectors.py tests/test_ios_app.py
python tools/e2e/device_mode.py
