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

## Done

## Commands
node tests/js/run_vectors.mjs; python tests/data/gen_ai_meal_vectors.py --check; python scripts/gen_own_key_prompts.py --check
