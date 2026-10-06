Status: in progress

# guidance (M2): rule-based meal guidance, log batch + client_id, m005

Role prompt: note 06 §4.1–§4.15 (package `app/guidance/`), §6 vectors, §7 checklist, §4.12 perf
budget + `scripts/bench_guidance.py`; note 04 R2/G7 Layer-0 duties; m005 (purpose, meal_hint, food
preferences, client_id + unique index); `POST /api/log/batch`; §4.14 settings keys; topics → /learn
slugs (note 08 §4.10); AI hook only; GuidanceContext reads targets through one function; parity
vectors `tests/data/guidance_vectors.json` (+ generator + staleness test); `docs/guidance.md`;
ARCHITECTURE "M2 API: guidance". Ports 8310-8319. Scratch:
/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/guidance/

## Decisions (and why)

* m005 waits for m004 (`discover()` refuses gaps). m004 landed in 2a45df4, so m005 can go in.
* `ingredient`: a real flag in `data/foods.json` (curated_foods.py + regenerate), not a hard-coded
  fdc_id list in the engine (one source of truth). Role overrides (`role` on foods.json items, e.g.
  coleslaw → veg_fruit) are read by the guidance context from the configured foods.json by fdc_id
  (avoids a foods.py/schema change while barcode-vision edits foods.py).
* Settings: note 07 wins (one registry): instance `guidance.enabled` (env GUIDANCE_ENABLED),
  `guidance.pool_per_role` (GUIDANCE_POOL_PER_ROLE), `guidance.beam_width` (GUIDANCE_BEAM_WIDTH);
  user object `guidance` {enabled, carb_tolerance_g, hypo_dose_g, exclude_categories,
  show_plan_builder, show_insights, ai_enrich}. "Not for me" foods are rows of a
  `food_preferences` table (m005; FK cascades with user and food; one-request add/remove).
* Guidance response models live in `app/guidance/models.py` (package-owned) instead of the shared
  `app/models.py`; only the log models (purpose, client_id, LogBatch) go into `app/models.py`.
* Spec reconciliations (all vectors reproduce):
  - TV-F3 food 13 = −0.58 needs the fixture's history entries to be food 13 (P 1,100, protein 49).
  - TV-P1 protein shows 8.2 g (the table's blueberries 0.5 g protein); the spec's "8.1 g" came from
    0.4 g; score 10.71 matches 0.5.
  - Portion option (TV-S2 picks ½ though ¾ fits the room): ¾ only when it removes every trigger
    (within room and no longer "high"), else ½ when it fits the room (halves the amount).
  - Swap mode follows the purpose: hypo when the entry/request purpose is hypo; a request for a
    hypo_treatment food without purpose defaults to hypo (as POST /api/log does), `purpose=none`
    forces normal (TV-S6's apple juice is that case).
  - Wording: grams one decimal only below 10 g (rule wins over the example "13.5 g protein").
  - Plan `new_alerts` lists only new "over" alerts (spec example is [] while protein/carbs reach
    "caution").
* Unknown carbs block a food/meal while a carb goal is set (`unknown:carbs_g`); unknown K/P/Na as spec.
* Hypo options/swaps: portion = ceil to ¼ of dose/carbs; dropped (never shrunk) if > 3 servings needed.

## Done

* Pure engine: rules, state, budget, score, fits, swaps, planner, insights, messages, topics,
  ai_bridge. Smoke-checked against TV-B1–B5, TV-F3–F8, TV-S1–S6, TV-P1, TV-I1 by hand (scripts in
  the session; tests next).

## Next

1. tests/guidance: §6 vectors + §6.7 properties (pure).
2. m005 + migration test; log.py batch/purpose/client_id; meals meal_hint; context.py; api.py;
   guidance models; settings; main.py; API tests (auth, isolation, batch).
3. foods.json ingredient/role, data/combos.json; vectors json + generator; bench + perf test;
   docs/guidance.md, ARCHITECTURE, ROADMAP; diet-guide dead citation (after targets commits).
4. nutrients.TARGET_KEYS + carbs_per_snack_g (targets agent is editing nutrients.py: add after
   their commit).

## Commands

    python3 -m pytest tests/guidance -q
