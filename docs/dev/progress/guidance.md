Status: in progress

# guidance (M2): rule-based meal guidance, log batch + client_id, m005

Role prompt: note 06 §4.1–§4.15 (package `app/guidance/`), §6 vectors, §7 checklist, §4.12 perf
budget + `scripts/bench_guidance.py`; note 04 R2/G7 Layer-0 duties; m005 (purpose, meal_hint, food
preferences, client_id + unique index); `POST /api/log/batch`; §4.14 settings keys; topics → /learn
slugs (note 08 §4.10); AI hook only; GuidanceContext reads targets through one function; parity
vectors `tests/data/guidance_vectors.json` (+ generator + staleness test); `docs/guidance.md`;
ARCHITECTURE "M2 API: guidance". Ports 8310-8319. Scratch:
/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/guidance/
Attempt 3 (this one) resumed from commit 908c00d; attempts 1–2 wrote the pure engine.

## Decisions (and why)

* m005 = purpose + client_id (+ partial unique index per person) + meal_hint + `food_preferences`
  table ("Not for me", FK cascade on user and food) + `meta.foods_rev` bumped by **triggers** on
  `foods` and `user_food_links` (every write path, incl. barcode/USDA code I do not own, invalidates
  the vector cache; no edit of app/foods.py needed). No backfill of `purpose` (never guess health
  data). `guidance_json` profile column of note 06 is superseded by note 07's registry key `guidance`.
* `ingredient`: a real flag in `data/foods.json` (curated_foods.py + regenerate). Role overrides
  (`role` on foods.json items, coleslaw → veg_fruit) are read by the guidance context from the
  configured foods.json by fdc_id.
* Settings: note 07 wins (one registry): instance `guidance.enabled` (env GUIDANCE_ENABLED),
  `guidance.pool_per_role` (GUIDANCE_POOL_PER_ROLE), `guidance.beam_width` (GUIDANCE_BEAM_WIDTH);
  user object `guidance` {enabled, carb_tolerance_g, hypo_dose_g, exclude_categories,
  show_plan_builder, show_insights, ai_enrich}. "Not for me" foods are `food_preferences` rows.
* Guidance response models live in `app/guidance/models.py` (package-owned) instead of the shared
  `app/models.py`; only the log models (purpose, client_id, LogBatch) go into `app/models.py`.
* Spec reconciliations (all vectors reproduce):
  - TV-F3 food 13 = −0.58 needs the fixture's history entries to be food 13 (P 1,100, protein 49).
  - TV-P1 protein shows 8.2 g (the table's blueberries 0.5 g protein); the spec's "8.1 g" came from
    0.4 g; score 10.71 matches 0.5.
  - Portion option (TV-S2 picks ½ though ¾ fits the room): ¾ only when it removes every trigger
    (within room and no longer "high"), else ½ when it fits the room.
  - Swap mode follows the purpose: hypo when the entry/request purpose is hypo; a request for a
    hypo_treatment food without purpose defaults to hypo (as POST /api/log does), `purpose=none`
    forces normal (TV-S6's apple juice is that case).
  - Wording: grams one decimal only below 10 g (rule wins over the example "13.5 g protein").
  - Plan `new_alerts` lists only new "over" alerts.
* Unknown carbs block a food/meal while a carb goal is set (`unknown:carbs_g`).
* Hypo options/swaps: portion = ceil to ¼ of dose/carbs; dropped (never shrunk) if > 3 servings needed.

## Done

* Pure engine (rules, state, budget, score, fits, swaps, planner, insights, messages, topics,
  ai_bridge, hypo); tests test_budget/test_fits/test_swaps (52 pass). Commit 908c00d.
* m005 + tests/guidance/test_migration_m005.py (populated v4 upgrade, idempotent, client_id
  uniqueness per person, cascades, foods_rev triggers). Commit 7c42ea3.

## Next

1. log.py: purpose/client_id on POST /api/log, /quick, PUT; POST /api/log/batch; models; meals.py
   meal_hint (from-log sets it, CRUD accepts it); tests.
2. vectors.py (FoodVec/build_vectors/protein_quality per §4.1 layout), avoid-mode pool = same
   category, hypo card example dose-aware.
3. context.py (VectorCache keyed (foods_rev, user_id); targets via profile.get_profile, the Today
   screen's source), api.py, guidance/models.py, settings keys, main.py; API tests (auth coverage,
   isolation, no_targets, explain, 400s, not-for-me).
4. Remaining pure tests: vectors/renal property, score, planner (TV-P1..P7 + beam oracle), insights
   (TV-I1..I5), messages lint, topics (pages exist), ai_bridge, hypo prefilter, determinism.
5. data/combos.json (review) + test; tests/data/guidance_vectors.json + generator + staleness test;
   scripts/bench_guidance.py + test_perf_guidance.py; docs/guidance.md (+ rules table drift test);
   ARCHITECTURE "M2 API: guidance"; ROADMAP; diet-guide dead UMich citation.

## Commands

    python3 -m pytest tests/guidance -q
    python3 -m pytest -q   # full suite
