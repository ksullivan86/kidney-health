Status: complete

# guidance (M2): rule-based meal guidance, log batch + client_id, m005

Role prompt: note 06 §4.1–§4.15 (package `app/guidance/`), §6 vectors, §7 checklist, §4.12 perf
budget + `scripts/bench_guidance.py`; note 04 R2/G7 Layer-0 duties; m005 (purpose, meal_hint, food
preferences, client_id + unique index); `POST /api/log/batch`; §4.14 settings keys; topics → /learn
slugs (note 08 §4.10); AI hook only; GuidanceContext reads targets through one function; parity
vectors `tests/data/guidance_vectors.json` (+ generator + staleness test); `docs/guidance.md`;
ARCHITECTURE "M2 API: guidance". Ports 8310-8319. Scratch:
/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/guidance/

## Decisions (and why)

* m005 = purpose + client_id (+ partial unique index per person) + meal_hint + `food_preferences`
  table ("Not for me", FK cascade on user and food) + `meta.foods_rev` bumped by **triggers** on
  `foods` and `user_food_links` (every write path invalidates the vector cache without editing
  app/foods.py). No backfill of `purpose` (never guess health data). Note 06's `guidance_json`
  profile column is superseded by note 07's registry key `guidance`.
* Settings: one registry (note 07): instance `guidance.enabled` (env GUIDANCE_ENABLED),
  `guidance.pool_per_role`, `guidance.beam_width`; user object `guidance` {enabled,
  carb_tolerance_g, hypo_dose_g, exclude_categories, show_plan_builder, show_insights, ai_enrich}.
* Guidance response models live in `app/guidance/models.py`; only log models go into `app/models.py`.
* Spec reconciliations (listed for readers in docs/guidance.md "Decisions where the specification
  was ambiguous"): portion option ¾/½; swap mode follows purpose; meal check carb rule = food filter;
  one food never tips the day (day_left); plan new_alerts only "over"; TV-P1 8.2 g; apply entries
  purpose "none"; from-log skips hypo entries; **hypo portions** round up to whole items for a
  one-item serving ("1 tablet") and may take up to HYPO_PORTION_MAX = 10 servings (the shipped
  4 g glucose tablet was dropped at 15 g under the 3-serving cap); **plan why** says "close to"
  only within the carb tolerance, else "N g under/over". RULES_VERSION 2026-10-06.1.

## Done (all committed; see `git log --oneline | grep guidance`)

* Pure engine, m005 + migration tests, log purpose/client_id/batch, meal_hint, settings keys,
  context/vectors/api/models/not-for-me, router, export of food_preferences, §6 vector/property/
  oracle/wording/topic/AI-bridge/data tests, perf work + bench + perf tests, parity vectors +
  generator + staleness test, docs/guidance.md (generated rules table), ARCHITECTURE section,
  ROADMAP, Containerfiles ship data/combos.json, diet-guide [47] citation, handbook app/guidance.md.
* Live smoke on port 8310 (stopped): login, profile, batch 201 / replay 200, next-meal, plan,
  hypo-options, anonymous 401, Cache-Control no-store. Found and fixed: hypo options left out the
  4 g glucose tablet; plan "why" said "close to" outside the tolerance.

## Handoffs (not this role's files)

* `app/static/js/engine/settings.js` lacks the `guidance` keys (JS twin parity tests
  test_settings_vectors JS cases fail until the frontend role adds them; same for targets keys).
* handbook `sources.yml` DG47 (dead UMich link) is still cited by 14 recipe pages (handbook owner).
* UI for guidance (frontend builder), AI modes (ai role), Raspberry Pi 4 p95 (release gate, unmeasured).

## Commands

    python3 -m pytest tests/guidance -q
    python3 -m pytest -q   # full suite
    python3 tests/data/gen_guidance_vectors.py && python3 scripts/guidance_rules_doc.py
    python3 scripts/bench_guidance.py --runs 20 --copies 1,5
