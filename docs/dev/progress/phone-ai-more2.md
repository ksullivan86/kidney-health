Status: in progress

# phone-ai-more2: AI order, AI swaps and AI day plans on the iPhone (owner, 2026-11-26)

What these are (server): POST /api/ai/next-meal modes `rerank` ("AI order" toggle over What fits), `swap` ("Ask AI to pick"
under the rule swaps) and `plan` ("Let AI choose" in the plan sheet). app/ai/features.prepare_next_meal, guard.judge_rerank /
judge_swap / judge_plan, ai_bridge.candidates_for_ai (swaps, plan options) and validate_ai_plan, schemas RerankAnswer /
SwapAnswer / PlanAnswer, prompts.swap_extra / plan_extra. The gateway already allows POST /api/ai/next-meal (all modes).

## Plan
1. JS twins in app/static/js/engine/aimeal.js: candidatesForAi with mode/swap/plan, swapExtra, planExtra, nextMealContext with
   extra, judgeRerank/judgeSwap/judgePlan, validateAiPlan, checkRerank/checkSwap/checkPlan (V2). Vectors in
   tests/data/gen_ai_meal_vectors.py → ai_meal_vectors.json; node tests/js/run_vectors.mjs.
2. js/mock/ai.js: mealIdeasHere for all modes (swap by this phone's entry or food; a low → treating_a_low card, never sent).
3. Own key: gen_own_key_prompts.py tasks rerank/swap/plan (system "meal", condition, no ids); OwnAI.swift.
4. iPhone model: build_preview AI_DEVICE_TASKS + OnDeviceAI.swift @Generable RerankReply/SwapReply/PlanReply.
5. Guidance "AI order" bar on the phone: mock guidance next-meal `ai` block from the phone's AI status.
6. Tests (pytest pins, node), docs (note 39 §6.6, ARCHITECTURE, handbook, CHANGELOG).

## Decisions
* Swap and day plan never go to the server from the phone: the request names this phone's entry/food ids, and the server's plan
  answer names its saved meals by its own ids (apply_saved endpoint). They run on the own key or the iPhone's model only.
* AI order goes to the server first (as meal ideas); its answer names foods by the server's id only, so the server adds
  `name` to each order/rest row (guard.judge_rerank) and the phone maps them by name (serverApi.localize).

* The iPhone's model: swap and plan candidates may be trimmed to none (the server never trims them; the answer is a pick among
  SWAPS / PLAN); judged with the full bridge as the server does. AI order trims like ideas (at least one) and is judged with the
  trimmed bridge, as the server.
* Own-key schemas for rerank/swap/plan list no refs (rerank_schema([])) and plan_schema(MEAL_SLOTS, AI_PLAN_OPTIONS_MAX-1); the
  page drops refs it did not send. No "ids" key is sent for these tasks (OwnAI.swift refuses one).
* Swap/plan buttons: GET /api/ai/status in device mode has `swap_plan` {available, label, stays}; the guidance view names that
  AI and hides the buttons when the phone has none (paired server only). What fits' `ai` block in device mode comes from
  KH.mock.aiGuidance (so the AI order bar and the AI ideas disclosure show on the phone).

## Done
* Step 1 (5e8da9d): twins + 40 new vectors (71 cases), run_vectors.mjs passes; guard.judge_rerank rows carry `name`.
* Step 2 (8ffcdb8, 7e117ee): mock/ai.js all modes, mock/guidance.js ai block, views/guidance.js labels; tests/js/phone_ai_more2.mjs
  (73 checks); phone_ai_more.mjs no longer expects 503 not_on_phone.
* Step 3-4 (d5d4556): gen_own_key_prompts.py + own_key_prompts.json, build_preview AI_DEVICE_TASKS, OwnAI.swift, OnDeviceAI.swift;
  tests/test_phone_ai_more2.py; pins updated in test_ai_device_vectors, test_ios_app (my hunk only), test_phone_own_key.

## Next
* e2e walk (tools/e2e/device_mode.py) if practical; docs (note 39 §6.6, ARCHITECTURE Device mode, handbook app/ai.md,
  CHANGELOG Unreleased); full pytest.

## Commands
Python with deps: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv-new/bin/python
node tests/js/phone_ai_more2.mjs; node tests/js/phone_ai_more.mjs; node tests/js/run_vectors.mjs; python tests/data/gen_ai_meal_vectors.py --check; python scripts/gen_own_key_prompts.py --check
