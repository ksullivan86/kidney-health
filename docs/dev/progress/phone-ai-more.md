Status: in progress

# phone-ai-more: more on the iPhone's own AI (owner, 2026-11-25)

Base: release branch claude/adoring-sagan-th5swr (reset --keep). Steps: 1 plate/label photos on the iPhone model (iOS 27);
2 meal ideas + AI recipes twins, routed to own key and iPhone model; 3 a simple Ask without the server (or why not).

## Decisions
* iOS 27 image input is a guess (no macOS here). It is compiled only with the Swift flag KH_ONDEVICE_IMAGES, which the
  project does not set; a CI probe step builds with it (continue-on-error) so a wrong guess never breaks the build.

* Coordinator (9c52473): build_preview.py may import only app.ai.prompts; anything needing schemas/config goes through the
  committed app/ai/own_key_prompts.json (scripts/gen_own_key_prompts.py). next_meal/recipes own-key entries carry the schema with
  "__CANDIDATE_IDS__" where the server puts its id list; OwnAI.swift puts the page's ids in (schema and prompt-mode line).
* ai-prompts.json now: system, systems {meal, recipe (steps off, [[CONDITION]] kept)}, conditions (all 105 condition_text
  wordings: the app only inserts one of these), tasks {template, system, image} for 6 tasks.
* Plate "to the plan": the web plate flow already has Eaten / Planned (default Planned) and saves log entries for the day shown;
  the phone uses the same view and POST /api/log/batch, so it works the same. It never makes a saved meal (server neither).

## Done
* Step 1 (photos on the iPhone model): OnDeviceVision.swift (flag), OnDeviceAI.swift (6 tasks, Generable shapes), CI probe,
  js/mock/ai.js photoOnDevice + aiStatus photos, PHOTO_NEEDS text, tests/js/phone_ai_more.mjs (24 checks),
  tests/test_phone_ai_more.py, test updates (ai_device_vectors, ios_app, phone_own_key, server_ask_phone), PhoneTests.

## Next
* Step 2: js/engine/aimeal.js twins (candidates_for_ai ideas, validate_ai_items, judge_ideas, next_meal_context, recipe_candidates,
  recipe_context, judge_recipes steps off) + vectors in gen_guidance_vectors.py; routes in js/mock/ai.js.
  test_ai_device_vectors::test_the_device_ai_never_offers_more_than_its_tasks fails until the mock asks next_meal/recipes.

## Commands
node tests/js/run_vectors.mjs; node tests/js/own_key.mjs
