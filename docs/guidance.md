# Meal guidance: what fits now, swap ideas, plan the day, insights

This page explains the app's **rule-based meal guidance**: what each feature does, the rules and
numbers behind it and where they come from, and what it never does. It is written for the people who
run and maintain the app and for anyone who wants to check the reasoning. The patient handbook explains
the same features in plain words (`/learn/app/guidance/`).

The normative specification is [design note 06](dev/research/06-meal-guidance.md) (§4, test vectors
§6); the hypoglycaemia duties come from [note 04](dev/research/04-optional-ai.md) R2 and G7; the API is
in [ARCHITECTURE.md](../ARCHITECTURE.md), "M2 API: guidance". The code is the package `app/guidance/`
(pure modules plus `context.py` and `api.py`, the only ones that touch SQLite or FastAPI).

> **Arithmetic on the care team's targets, not medical advice.** Guidance works without any AI, on a
> Raspberry Pi, offline on a LAN. It compares foods with the targets the person saved (the same ones
> the Today screen shows) and says so on every answer: *"Suggestions compare foods with the targets
> your care team set. They are not medical advice."* The per-meal caps and score weights are dietitian
> rules of thumb and design choices, not graded guideline statements; they shape suggestions and
> **never create a warning or an alert**. Every rule below lists its source or says that it is a design
> choice. The rules have **not yet been reviewed by a renal dietitian or a diabetes educator**; until
> they have, treat the weights as the project's own judgement.

## What guidance never does

* **Never doses.** No insulin, units, ratios, correction factors or medicines in any text (a wording
  lint over every template and every generated message enforces it, `tests/guidance/test_messages.py`).
  Carbohydrate is shown in grams only. Swaps keep the carbohydrate the same so the person's own
  arithmetic still applies; a smaller-portion option says "The carbs change, so count the new amount."
* **Never gets in the way of treating a low.** Low-treatment foods (`hypo_treatment`, e.g. glucose
  tablets, apple juice) are never offered as meal suggestions and never planned into meals, but they
  are never warned against, limited, delayed or shrunk either. An entry marked "Used to treat a low"
  (`purpose = "hypo"`) counts toward potassium, phosphorus, sodium and fluid (the person really had
  it) and never toward a meal's carbohydrate or the carb insights. The only "swap" for a low treatment
  is *for the next low*: another low treatment with **at least** the person's own treatment amount
  (rounded up to ¼ serving, or to whole items such as tablets, never down) and less potassium. The low-treatment options and the
  "Treating a low" card are available even when an admin or the person switches guidance off.
* **Never weakens a warning.** A food with a "high" warning for a nutrient that is already at caution
  or over today is not suggested; unknown potassium, phosphorus or sodium values are never treated as
  0 (they cost points, and block a food while that nutrient is not ok today).
* **Never tips a day over.** A suggested food never takes potassium, sodium or fluid from "not over"
  to "over" for the day (on top of the per-meal room); a planned day that would go over is cut back
  (see "Plan the rest of my day").
* **Never suggests alcohol.** With insulin, alcohol can cause lows hours later (ADA *Standards of Care
  in Diabetes—2026*, Section 5, Recs 5.18–5.19), so a food flagged `alcohol` (the curated beers, wines and
  spirits; Open Food Facts `en:alcoholic-beverages`; USDA records with ethanol; any custom food the person
  flags) is never in What fits, a swap, a built plan, the energy note, a usual meal or an AI idea. It can
  still be searched for and logged, and a meal the person saved keeps it.
* **Never says "safe".** No "safe", "bad", "cheat", "unlimited", "don't worry"; every "high" or "low"
  comes with its number (CDC Clear Communication Index items 15–16).
* **Never writes on its own.** Every guidance request computes only; "Use this plan" sends the plan
  to `POST /api/log/batch` as *planned* entries when the person taps it.
* **Never shares.** Every query takes the signed-in person's id; nothing about one person reaches
  another person's suggestions, plans or insights. Insights and low-treatment options are never sent
  to an AI provider.

## The features

| Feature | Where (UI, frontend builder) | Endpoint |
|---|---|---|
| **What fits now**: foods and saved/usual meals that fit the next meal, with a reason each | Top of the Add view after choosing a meal; "What fits" under a meal in Today | `GET /api/guidance/next-meal` |
| **Swap ideas**: lower-potassium/phosphorus/sodium alternatives with the same carbs | Entry sheet, "Lower-… ideas" under a warning | `GET /api/guidance/swaps` |
| **For your next low**: lower-potassium low treatments and the "Treating a low" card | Entry sheet with "Used to treat a low" ticked | `GET /api/guidance/swaps?purpose=hypo` |
| **Treating a low**: the card and the person's low treatments at their dose, with "Log it" | Today's Meal ideas card (people with diabetes), even with guidance off; offline from the browser twin of the card | `GET /api/guidance/hypo-options` |
| **Plan the rest of my day**: one option per open meal, "Show another", "Use this plan" | Today's Meal ideas card; Plan → "Plan a day…" | `POST /api/guidance/plan-day`, then `POST /api/log/batch` |
| **Insights**: end of day and weekly, in plain language with numbers | Today (a past day, or once breakfast, lunch and dinner are eaten or after 19:00), Trends (the chosen days ending yesterday) | `GET /api/guidance/insights/day`, `/insights/period` |
| **Not for me**: foods never suggested again (still searchable and loggable) | "⋯" menu of a suggestion; Settings → Meal guidance lists them | `PUT/DELETE /api/guidance/not-for-me/{food_id}` |
| **The rules**: every number below, its basis, the handbook pages | Docs, contributors | `GET /api/guidance/rules` |

When the profile has no numeric potassium, phosphorus or sodium target and no meal carbohydrate goal,
every guidance answer is `{"status": "no_targets", "message": "Set your targets in Profile first; …"}`.

The screens are described for people in the handbook (`handbook/docs/app/guidance.md`) and for
contributors in ARCHITECTURE.md, "M2 API: guidance" → "Frontend". The app (`js/views/guidance.js`)
shows the server's texts word for word and keeps the last answer of each kind in memory for the
offline message; nothing is written to browser storage.

## The room left for a meal

Guidance first works out how much potassium, phosphorus, sodium and fluid are left for the meal
(`budget.py`, note 06 §4.4):

* **Open slots**: the meal itself, every later main meal with no entries, and the snack slot (all
  snacks of the day together) if it has none. A slot that already has planned entries is not open: its
  plan is part of the day's projection. Earlier empty meals count as skipped.
* **Allowance today**: the daily target for potassium, sodium and fluid. On hemodialysis with dialysis
  days set, also `(target × days in the interval − eaten since the last session) / days left`, whichever
  is lower. Phosphorus is judged on the weekly average (KDOQI 2020), so its allowance is
  `target × (n + 1) − phosphorus of the n logged days among the previous 6`, kept between 0.8 and 1.2 ×
  the target: a heavy weekend never starves a day (protein needs phosphorus), unlogged days are ignored.
* **Room** = `max(0, min(cap − already in the meal, share))`, where `share` is the remaining allowance
  split over the open slots by weight (0.30 per main meal, 0.15 for the snack slot) and `cap` is 0.30 of
  the daily target per main meal and 0.15 for the snack slot (fluid has no cap).
* **Why 0.30?** The American Kidney Fund's dietitians suggest 600–700 mg potassium per meal and
  100–200 mg per snack at 1,800–2,200 mg a day, and < 700 mg per meal on dialysis; Satellite Healthcare
  < 600 mg sodium per meal and < 200 mg per snack. A fraction of the person's own target reproduces
  600 mg at 2,000 mg and scales with whatever the care team set (a fixed 600 mg would be wrong for a
  4,000 mg review ceiling). No guideline gives a per-meal number; phosphorus uses the same structure
  by analogy.
* **Carbohydrate** (type 1 or 2 diabetes with a meal goal): the gap to the meal's goal
  (`carbs_per_meal_g`; the snack slot: `carbs_per_snack_g`, else half the meal goal rounded to 5 g, at
  least 15 g), ± the person's tolerance (default 10 g: in children on intensive insulin a dose for 60 g
  covered 50–70 g meals; a 20 g error mattered — Smart et al. 2009/2012). Carbs of low treatments are
  shown separately (`hypo_excluded_g`).
* **Protein**: the aim for the meal is its share of what is left of the day's range (middle and
  minimum), so the day lands inside the range without under-shooting the minimum.

## What fits now

`fits.py` (§4.5). For every eligible food (not hidden, not `avoid_ckd`, not a low treatment, not an
`ingredient` such as flour or oil, not an `alcohol` drink, not a diabetes supply, not "Not for me", not an
excluded category)
at 1, ½, 1½ or 2 servings (drinks and extras 1 or ½):

1. **Hard filters**, the first failure is the reason code shown with `?explain=true`:
   `would_exceed:<nutrient>` (above the room plus a negligible amount — 50 mg potassium or sodium,
   30 mg phosphorus, 30 mL fluid — or above what is left of the day's own target for potassium, sodium
   or fluid), `unknown:<nutrient>` (unknown while that nutrient is not ok today), `too_many_carbs`,
   `high_warning:<nutrient>`.
2. **Score**: a base (protein foods by phosphorus and potassium per gram of protein — ≤ 10 mg/g good,
   ≥ 16 mg/g phosphorus poor (Noori 2010: hazard ratio 1.99 at ≥ 16 mg/g on hemodialysis) — because 36 of
   38 meat and fish portions are "red" per serving and would otherwise never be suggested; other foods
   by renal rating: green +3, yellow +1, red −3), habit and variety, a quadratic cost for using up each
   room, a bonus for filling the carb gap with starch, fruit or vegetables (never sweets or drinks),
   the food group the meal is missing, the protein aim, the meal slot the person usually eats it in,
   and penalties for several high-potassium portions in one meal or day (AKF/UW: avoid several
   high-potassium foods a day). Rounded to 2 decimals before any comparison.
3. **Selection**: best portion per food, sorted by score, then less potassium, phosphorus, sodium,
   name and id; at most 3 per group (2 extras), 2 per category, 11 in all; nothing below a score of 0.
4. Each food carries `fit_text` ("Fits: 45 g carbs · 55 mg potassium · …"), up to two reasons and one
   caution ("Low in potassium (55 mg)", "Brings dinner to 45 of your 60 g carbs", …) and links to the
   handbook pages behind them.
5. **Saved and usual meals that fit**: saved meals for this slot (or without a slot, for main meals) and
   "usual meals" mined from the last 60 days (2–6 foods eaten together in this slot on at least 2 dates),
   tried at full, ¾ and ½ size; the first size that passes the meal check is kept, with a note such as
   "Fits at half size (25 g carbs, 35 g under your 60 g goal): this week's phosphorus leaves 167 mg for
   dinner."
6. **Tips** (at most 2) from a maintainer-written table: potassium leaching when potassium is at caution,
   phosphate additives when this week's phosphorus is, hidden sodium, fluid on dialysis, an extra protein
   portion on dialysis, free foods when the meal's carbs are done.

## Swap ideas

`swaps.py` (§4.6). For a food and amount (before or after logging):

* **Mode**: `hypo` when the entry or request is a low treatment (a `hypo_treatment` food defaults to it,
  as when logging; `purpose=none` treats it as food), `avoid` for an `avoid_ckd` food, else `normal`.
* **Triggers** (normal): potassium, phosphorus or sodium above the per-serving "high" or above the meal's
  room, a phosphate additive, fluid above the fluid room. No trigger: no swaps (`reason: "no_warning"`).
* **Match** the person's arithmetic: carbohydrate when the food has ≥ 10 g (within max(5 g, 10 %)),
  else protein from 3 g (within max(3 g, 15 %)), else one serving. In low-treatment mode always
  carbohydrate, at least the person's treatment amount, rounded **up**; a candidate that would need more
  than 3 servings is dropped, never shrunk.
* **Accept** a candidate of the same category or role only if every trigger is at least 25 % lower, it
  has no phosphate additive when that was a trigger, and it creates no new problem (no other nutrient
  over the room where the original was lower, no unknown value while that nutrient is not ok, no new
  "high" portion). Low treatments are candidates for drinks only (orange juice → apple juice) and the
  only candidates in low-treatment mode.
* **Rank** by the weighted reduction, renal rating, same category and name family, fitting the meal,
  habit, minus processed foods and carb difference; at most 5.
* **Fallbacks**: a smaller portion of the same food (¾ when it clears every trigger, else ½ when it fits
  the room; none for a phosphate additive, none for a low treatment) and tips (leaching for potatoes,
  sweet potatoes, yams, carrots, beets and winter squash; additives; the low-treatment card).

## Treating a low

`GET /api/guidance/hypo-options` lists the person's low-treatment foods at the amount that treats a low
(`hypo_dose_g`, default 15 g, the rule of 15 — ADA 2026 Rec 6.15; 5–10 g is typical on automated insulin
delivery, which is why it is a personal setting "from my diabetes team"), lowest potassium first, then
phosphorus and fluid, **never filtered by any budget**, with the rule-based card of the diet guide §4 and
the handbook page `t1d/treating-a-low`. The same card is what `app/ai/` must show **instead of calling
an AI** when free text may describe a low (`app.guidance.hypo.prefilter`: "low", "hypo", "shaky",
"sweaty", "glucose < 70", a reading under 70 mg/dL or 3.9 mmol/L, …; "low-fat", "low sodium" and similar
food words are not read as a low). The classifier errs toward showing the card.

## Plan the rest of my day

`planner.py` (§4.7). Slots are filled in order breakfast, lunch, dinner, snack; each slot's room is
worked out with the items already placed in earlier slots. Options per slot, all passing the same
`check_meal()` (room + negligible for potassium, phosphorus, sodium and fluid; carbohydrate at most the
tolerance above the gap — a meal with ≤ 5 g of carbs always passes; no `avoid_ckd` food; portions ¼–3
servings; built meals and AI ideas never hold a low treatment, an ingredient or an alcoholic drink):

1. saved meals for the slot, 2. usual meals, 3. starter combos from `data/combos.json` (the four meals
of the diet guide's §6 sample day, mapped to builtin foods by USDA id; offered only when every food
exists), 4. a meal **built** by beam search (protein → starch → vegetable or fruit; one item for the
snack slot; width 16 over the 6 best foods per role from a pool of 200 pre-ranked foods; a final
carbohydrate fine-tune of the starch in ¼ servings). Against an exhaustive search over the same
candidates on 40 seeded random days the beam is at most 0.5 points worse (`tests/guidance/test_planner.py`).

The best familiar option (1–3) wins when it scores at least the best built option minus 3 points:
people keep meals they know. "Show another" (`variant` 1–4) skips that many built options. Then:

* **Whole-day check**: if the plan makes potassium, sodium or fluid newly *over* for the day, ¼ serving is
  taken off the built item contributing most, up to 6 times; otherwise the slot is marked `partial` with
  a sentence saying so.
* **Protein top-up**: below the day's protein minimum, the latest built main meal's protein item grows by
  ½ serving while its meal check still passes (at most 2 steps, then the previous meal).
* **Energy note**: below 80 % of the calorie goal, the plan names up to 3 energy-dense, low-mineral foods
  (olive oil, unsalted butter, …) and the diet guide's advice to close the gap with fat or measured
  starch, not more meat — restriction alone drives protein-energy wasting.

## Insights

`insights.py` (§4.8), from **eaten** entries only (planned ones are counted in `planned_excluded`).
At most 6, ordered warning > attention > info > good, then potassium, phosphorus, sodium, fluid, protein,
carbohydrate; at most one "good", always last. End of day: potassium/sodium/fluid over or at caution
(with the two biggest sources), phosphorus over (information: it is judged weekly), meals off the carb
goal, all meals within it, low treatments logged (and a lower-potassium choice when one exists), several
high-potassium portions, phosphate additives, protein below the minimum on dialysis or above the maximum
otherwise, unknown values, between dialysis sessions, eating too little. Period (default the 7 days
ending yesterday, at most 92, at least 3 logged days): coverage, weekly averages over target with their
main sources, days over a daily limit (and "Mostly at the weekend."), one meal giving most of the
potassium or sodium, carb consistency per meal, repeated low treatments ("Your diabetes team may want to
know."), additive foods, change against the previous period, and "stayed within your limit".

## Settings

| Key | Scope | Default | Meaning |
|---|---|---|---|
| `guidance.enabled` | instance (env `GUIDANCE_ENABLED`) | `true` | Off: guidance answers `{"status": "disabled"}` (low-treatment options and the rules stay available) |
| `guidance.pool_per_role` | instance (env `GUIDANCE_POOL_PER_ROLE`) | 200 (20–2000) | Plan builder pool; 120 is faster on a small server |
| `guidance.beam_width` | instance (env `GUIDANCE_BEAM_WIDTH`) | 16 (1–64) | Plan builder search width |
| `guidance` | user | object below | The person's own choices |

The `guidance` object: `enabled` (true), `carb_tolerance_g` (10, 5–20), `hypo_dose_g` (15, 5–30),
`exclude_categories` (food categories never suggested, ≤ 50), `show_plan_builder` (true), `show_insights`
(true), `ai_enrich` (false; read by the optional AI layer, note 04). "Not for me" foods are separate rows
(`food_preferences`, ≤ 500 per person) so a deleted food disappears from the list by itself; they are
part of the account export (`export.json` → `food_preferences`).

## Data the engine reads

* The person's **profile** exactly as the Today screen reads it (`app.profile.get_profile`): targets,
  `warn_fraction`, dialysis mode and days, diabetes type, and when the profile was last saved. Every
  next-meal and plan answer returns them as `targets: {values, profile_updated_at}` (note 06 R10), and the
  app shows them under the room line of What fits now and in the plan sheet: "Using the targets in your
  profile, saved Oct 3, 2026, 2:15 PM: potassium 3,000 mg · … · carbs per meal 60 g. Check them in
  Profile" (`targetsUsed()` in `js/views/guidance.js`; a `{min, max}` target with min = max reads "about X",
  a min-only one "at least X").
* **Foods** the person may use, as vectors cached per database and `meta.foods_rev` (bumped by database
  triggers on every food or link write, schema step 5); curated `role` overrides and the `ingredient`
  flag come from `data/foods.json`.
* The day's entries (eaten and planned, with `purpose`), eaten history of the last 14 and 60 days, saved
  meals (with `meal_hint`) and the starter combos.

Schema step 5 (`app/migrations/m005_guidance_log.py`) adds `log_entries.purpose`, `log_entries.client_id`
(with a per-person unique index for the offline outbox), `meal_templates.meal_hint`, `food_preferences`
and the `foods_rev` triggers. Old entries keep `purpose` empty: the upgrade does not guess which were
low treatments.

## Optional AI (the contract)

The AI layer (`app/ai/`, note 04) may only re-rank and explain the engine's own candidates. It builds its
context **only** from `ai_bridge.candidates_for_ai(ctx, meal, mode)` (up to 40 foods, at least 6 per
group, each with numbers, rating and reason codes; custom and Open Food Facts names marked untrusted; no
low treatments) and checks every idea **only** with `ai_bridge.validate_ai_items()` (the same
`check_meal()`; foods must be candidates, 1–12 quarter servings, at most 5 items and 3 ideas) or
`validate_ai_plan()` (re-runs the whole-day check). It registers its availability with
`ai_bridge.register_ai_status()`, which `next-meal` reports as `ai: {available, provider_label}`; a failing
provider is logged and reported as unavailable, so guidance always answers.

## Decisions where the specification was ambiguous

* **Smaller-portion option** (TV-S2 picks ½ although ¾ fits the room): ¾ only when it clears every
  trigger, else ½ when it fits the room.
* **Swap mode follows the purpose**, not the food: apple juice logged with a meal is food (TV-S6).
* **The meal check's carbohydrate rule** equals the food filter's (a meal of ≤ 5 g carbs always passes),
  so a free food can follow a meal that is already at its carb goal.
* **One suggested food never tips the day over** (§6.7 property): the hard filter also compares with what
  is left of the day's own target for potassium, sodium and fluid.
* **Plan `new_alerts`** lists only new "over" alerts; reaching "caution" is what a plan is for.
* **Fixture TV-P1** shows 8.2 g protein (the table's blueberries carry 0.5 g); the note's 8.1 g used 0.4 g.
* **`apply` entries carry `purpose: "none"`**: a planned meal is never a low treatment, even when a saved
  meal holds apple juice.
* **"From log"** leaves low-treatment entries out of the saved meal and sets its `meal_hint`.
* **Low-treatment portions** (§4.6 says `ceil_to_quarter(dose / carbs per serving)` within the 3-serving
  cap): a food whose serving is one counted item ("1 tablet (4 g)", `HYPO_WHOLE_UNITS`) is rounded up to
  whole items, and a low treatment may take up to `HYPO_PORTION_MAX` (10) servings. Otherwise the shipped
  "Glucose tablet (4 g carb)" would be left out at the default 15 g (3 tablets give 12 g) and offered as
  "2½ tablets" at 10 g. The
  portion still never gives less than the dose.
* **Alcoholic drinks** (integration review, v0.3.0; rules version 2026-10-07.1): note 06 did not exclude
  them, so the 80-proof spirits (no carbohydrate, no potassium) ranked as an "extra" and an energy-dense
  idea. They are now excluded like ingredients; usual meals leave the drink out and keep the rest.
* **Plan "why" lines** say "close to your goal" only within the person's carb tolerance, otherwise
  "17 g carbs, 13 g under your 30 g snack goal" (§4.15's string covered only the first case).

## Performance

Budget (§4.12): p95 < 200 ms per guidance request on a Raspberry Pi 4 (4 GB) with 2,000 foods, 60 days of
history and 100 saved meals; engine time on the x86 CI runner: what-fits ≤ 25 ms, swaps ≤ 5 ms, plan-day
≤ 40 ms, insights ≤ 15 ms. `tests/guidance/test_perf_guidance.py` asserts evaluation counts (what-fits
≤ 4 × eligible foods, plan-day ≤ 8,000 food and ≤ 1,500 meal evaluations) and generous wall-clock bounds;
`python3 scripts/bench_guidance.py` prints p50/p95 for each endpoint (from SQLite, as a request runs) and
for the engine alone.

Measured on 2026-10-06 (Intel Xeon @ 2.10 GHz cloud VM, CPython 3.11.15, 20 runs, p50 / p95 ms):

| Foods | next-meal | swaps | plan-day | insights/day | engine: what-fits | engine: swaps | engine: plan-day |
|---|---|---|---|---|---|---|---|
| 395 (real) | 21 / 26 | 6.2 / 7.0 | 33 / 35 | 3.9 / 4.4 | 7.7 / 9.0 | 1.1 / 1.3 | 20 / 22 |
| 1,975 (5 copies) | 28 / 30 | 6.2 / 6.5 | 38 / 42 | 2.6 / 2.9 | 19.6 / 20.6 | 2.5 / 2.6 | 28.8 / 30.0 |

**Release gate:** run `python3 scripts/bench_guidance.py --max-p95 200` on a Raspberry Pi 4 and a Pi 5
with the image's Python and record the tables here; if a Pi 4 p95 is above 200 ms, lower
`GUIDANCE_POOL_PER_ROLE` (120 cuts plan-day by about 30 %) and say so here. The Pi figures are an
estimate (4–6× this VM) until then.

**The demo / preview mode** answers the same routes in the browser (`js/mock/guidance.js` over the
JavaScript twin `js/engine/guidance/*.js`), so there the person's own device does the work.
`python3 tools/e2e/guidance_perf.py` times it in headless Chromium with the CPU slowed down 4× (a
mid-range phone) and fails above the same 200 ms p95. Measured on 2026-10-06 (Chromium 141 on the VM
above, 30 runs, p50 / p95 ms; the first call of a page also builds the food vectors):

| Data | next-meal | swaps | plan-day (4 slots) | insights/day | insights/period | hypo-options | first call (max) |
|---|---|---|---|---|---|---|---|
| demo as shipped (395 foods) | 8.0 / 10.3 | 2.8 / 5.6 | 26.5 / 36.9 | 1.0 / 1.9 | 1.3 / 2.2 | 0.8 / 2.2 | 99 |
| 1,975 foods, 60 days, 100 saved meals | 14.4 / 23.2 | 4.7 / 6.6 | 40.6 / 52.0 | 2.2 / 3.3 | 3.3 / 5.4 | 3.8 / 5.8 | 120 |

## Changing a rule

1. Change the number in `app/guidance/rules.py` (with its basis in `RULE_DOCS`) and bump `RULES_VERSION`.
2. Regenerate and review: `python3 tests/data/gen_guidance_vectors.py` (demo-mode parity vectors; then
   update the JavaScript twin until `node tests/js/run_vectors.mjs` agrees) and
   `python3 scripts/guidance_rules_doc.py` (the table below).
3. Update the golden vectors in `tests/guidance/` that the change moves, saying why in the pull request,
   and cite the evidence (or call it a design choice).

## Every number

Generated from `app/guidance/rules.py` (the same data as `GET /api/guidance/rules`) by
`python3 scripts/guidance_rules_doc.py`; `tests/guidance/test_docs.py` fails when it is stale.

<!-- rules-table:start -->
Rules version **2026-10-07.1** (hash `8514c677136c30ea`).

| Name | Value | Basis |
|---|---|---|
| `MEAL_WEIGHT` | `{"breakfast": 0.3, "lunch": 0.3, "dinner": 0.3, "snack": 0.15}` | Share of the day's remaining room per open slot; reproduces AKF's 600 mg per meal at 2,000 mg (F1) |
| `MEAL_CAP_FRACTION` | `{"breakfast": 0.3, "lunch": 0.3, "dinner": 0.3, "snack": 0.15}` | Per-meal cap as a fraction of the day's target: 0.30 per main meal, 0.15 for all snacks (F1; phosphorus by analogy, F2) |
| `CAP_KEYS` | `["potassium_mg", "phosphorus_mg", "sodium_mg"]` | Nutrients with a per-meal cap (fluid has a day allowance only) |
| `NEGLIGIBLE` | `{"potassium_mg": 50.0, "sodium_mg": 50.0, "phosphorus_mg": 30.0, "fluid_ml": 30.0, "carbs_g": 5.0}` | Amounts that never count against a room; carbs: a "free" food has ≤ 5 g (UW Food Choice Lists, F4) |
| `USAGE_WEIGHT` | `{"potassium_mg": 3.0, "sodium_mg": 2.0, "phosphorus_mg": 2.0, "fluid_ml": 2.0}` | How much using up each room costs in a score; potassium acts fastest (diet guide §2) |
| `USAGE_WEIGHT_P_NOT_OK` | `3.0` | Phosphorus weight while this week's phosphorus is not ok |
| `PORTIONS_MAIN` | `[1.0, 0.5, 1.5, 2.0]` | Portions tried for protein, mixed, starch and vegetable/fruit foods (servings) |
| `PORTIONS_SIDE` | `[1.0, 0.5]` | Portions tried for drinks and extras: never two root beers (F10) |
| `PORTIONS_BUILD` | `[1.0, 0.5]` | Portions tried when ranking plan-day candidates |
| `PORTIONS_BUILD_PROTEIN` | `[1.0, 0.5, 1.5]` | Portions tried for plan-day protein candidates |
| `WEEK_LOOKBACK_DAYS` | `6` | Previous days that balance week-judged phosphorus (§3.3) |
| `WEEK_CLAMP` | `[0.8, 1.2]` | Phosphorus allowance today, as a fraction of the daily target, never outside this range (§3.3) |
| `CARB_TOLERANCE_G` | `10` | Grams either side of the meal carb goal that count as on target (Smart 2009/2012, F4); a personal setting |
| `CARB_TOLERANCE_RANGE` | `[5, 20]` | Allowed range of the personal carb tolerance (g) |
| `SNACK_CARB_GOAL` | `targets.carbs_per_snack_g, else max(15, 5 × round(carbs_per_meal_g / 2 / 5))` | Carb goal of the snack slot (NKF: 1–3 carb choices per snack, F4) |
| `SNACK_CARB_MIN_G` | `15` | Smallest snack carb goal: one carb choice |
| `HYPO_DOSE_G` | `15` | Carbs that treat a low (rule of 15, ADA 2026 Rec 6.15, F5); a personal setting from the diabetes team |
| `HYPO_DOSE_RANGE` | `[5, 30]` | Allowed range of the personal low-treatment amount (g; 5–10 g on automated insulin delivery) |
| `HIGH_K_ENTRY_MG` | `200.0` | A "high-potassium portion" (the app's per-serving high); AKF/UW: not several in one day |
| `PROTEIN_ROLE_MIN_G` | `7.0` | A protein portion has at least this much protein (NKF: 7 g = 1 oz of meat, F3) |
| `STARCH_ROLE_MIN_CARBS_G` | `15.0` | A starch has at least one carb choice |
| `P_PER_G_PROTEIN` | `[10.0, 16.0]` | Phosphorus per gram of protein: good at or below, poor at or above (Noori 2010, F2) |
| `K_PER_G_PROTEIN` | `[10.0, 20.0]` | Potassium per gram of protein: good at or below, poor at or above (design choice: chicken breast 8, ground chicken 29) |
| `PROTEIN_AIM_FLOOR_G` | `5.0` | Smallest protein aim used in a score (avoids dividing by tiny aims) |
| `MIN_SHOW_SCORE` | `0.0` | Foods scoring below this are not shown as "fits" |
| `GROUP_LIMITS` | `{"protein": 3, "starch": 3, "veg_fruit": 3, "extra": 2}` | At most this many suggestions per group |
| `CATEGORY_LIMIT` | `2` | At most this many suggestions per food category |
| `DEFAULT_LIMIT` | `11` | Suggestions returned by default |
| `MAX_LIMIT` | `20` | Most suggestions a request may ask for |
| `BEAM_WIDTH` | `16` | Partial meals kept at each step of the plan builder (admin: GUIDANCE_BEAM_WIDTH; §3.4) |
| `BEAM_WIDTH_RANGE` | `[1, 64]` | Allowed range of the beam width |
| `PER_ROLE` | `6` | Best candidates per role the plan builder combines |
| `POOL_PER_ROLE` | `200` | Foods per role pre-ranked for the plan builder (admin: GUIDANCE_POOL_PER_ROLE; F8) |
| `POOL_PER_ROLE_RANGE` | `[20, 2000]` | Allowed range of the pool size |
| `FAMILIAR_MARGIN` | `3.0` | A saved, usual or starter meal wins if it scores at least the best built meal minus this |
| `SLOT_HABIT_BONUS` | `1.0` | Bonus for a food eaten in this meal slot on enough recent days (F10: no pasta at breakfast) |
| `SLOT_HABIT_MIN_DAYS` | `2` | Days in the last 14 a food must have been eaten in the slot for the bonus |
| `OFTEN_MIN_DAYS` | `2` | Days in the last 14 for "You often have this" |
| `HISTORY_DAYS` | `14` | Days of history for habit, variety and the phosphorus week |
| `USUAL_HISTORY_DAYS` | `60` | Days of history mined for usual meals |
| `USUAL_MIN_ITEMS` | `2` | Fewest foods in a usual meal |
| `USUAL_MAX_ITEMS` | `6` | Most foods in a usual meal |
| `USUAL_MIN_DATES` | `2` | A usual meal was eaten on at least this many dates |
| `SWAP_MIN_REDUCTION` | `0.25` | A swap lowers every nutrient that triggered it by at least this fraction |
| `SWAP_CARB_MATCH` | `[5.0, 0.1]` | A swap's carbs stay within max(min_g, fraction × original): the insulin arithmetic stays the same (F4) |
| `SWAP_PROTEIN_MATCH` | `[3.0, 0.15]` | A swap matched on protein stays within max(min_g, fraction × original) |
| `SWAP_MATCH_CARBS_MIN_G` | `10.0` | Swaps match carbs when the original has at least this much |
| `SWAP_MATCH_PROTEIN_MIN_G` | `3.0` | Otherwise they match protein when the original has at least this much |
| `SWAP_MAX` | `5` | Swap ideas returned |
| `SWAP_AI_MAX` | `15` | Rule swaps handed to the optional AI layer |
| `PORTION_RANGE` | `[0.25, 3.0]` | Every planned or swapped portion is between these servings |
| `PORTION_MIN` | `0.25` | Smallest portion (servings) |
| `PORTION_MAX` | `3.0` | Largest portion (servings) |
| `PORTION_OPTION_FRACTIONS` | `[0.75, 0.5]` | Smaller-portion fallbacks of a swap request (¾, then ½) |
| `HYPO_PORTION_MAX` | `10.0` | Largest low-treatment portion (servings): enough single 4 g glucose tablets for the 30 g maximum dose; never fewer carbs than the dose |
| `HYPO_WHOLE_UNITS` | `["tablet", "piece", "candy", "candies", "sweet", "lozenge", "gummy", "gummies", "chew", "pastille", "mint", "jelly bean", "cube", "sachet", "packet"]` | A serving of one of these items ("1 tablet") is counted out whole for a low, rounded up |
| `HYPO_SWAP_TRIGGER_MG` | `0.0` | In low-treatment mode the only trigger is potassium above this |
| `HYPO_INSIGHT_K_MG` | `50.0` | A low treatment above this potassium makes the insight name a lower-potassium choice |
| `HYPO_BEST_MAX_K_MG` | `20.0` | … when one of the person's low treatments has at most this much |
| `INSIGHT_MAX` | `6` | Insights returned |
| `SOURCE_MIN_SHARE` | `0.1` | A food is named as a source when it gave at least this share |
| `SOURCE_MAX` | `3` | Sources listed per insight |
| `MIN_LOGGED_DAYS` | `3` | Logged days needed for period insights |
| `PERIOD_DEFAULT_DAYS` | `7` | Default insight period (the days ending yesterday) |
| `PERIOD_MAX_DAYS` | `92` | Longest insight period |
| `PERIOD_CHANGE_MIN` | `0.15` | A change against the previous period is reported from this fraction |
| `MEAL_SHARE_MIN` | `0.45` | One meal slot giving at least this share of potassium or sodium is reported |
| `PERIOD_HYPO_MIN` | `3` | Low treatments in a period from which the diabetes team may want to know |
| `SAVED_MEAL_SCALES` | `[1.0, 0.75, 0.5]` | Sizes a saved, usual or starter meal is tried at |
| `SAVED_MEALS_MAX` | `3` | Fitting saved and usual meals returned |
| `AI_FOODS_MAX` | `40` | Candidate foods handed to the optional AI layer (note 04 R2) |
| `AI_FOODS_PER_GROUP_MIN` | `6` | … at least this many per group when available |
| `AI_MEALS_MAX` | `5` | Saved or usual meals handed to the AI layer |
| `AI_PLAN_OPTIONS_MAX` | `5` | Options per slot the AI layer may pick from |
| `AI_QUARTERS_RANGE` | `[1, 12]` | An AI idea's portion in quarter servings (note 04 V3) |
| `ENERGY_NOTE_FRACTION` | `0.8` | A plan below this share of the calorie goal gets the energy note (R2: under-eating) |
| `ENERGY_LOW_INSIGHT_FRACTION` | `0.7` | A logged day below this share of the calorie goal gets the eating-enough insight |
| `ENERGY_DENSE_MIN_KCAL` | `50.0` | An energy-dense, low-mineral food has at least this many kcal per serving |
| `ENERGY_DENSE_MAX` | `{"potassium_mg": 50.0, "phosphorus_mg": 30.0, "sodium_mg": 50.0, "carbs_g": 5.0}` | … and at most these minerals and carbs per serving |
| `ENERGY_NOTE_FOODS` | `3` | Energy-dense foods named in the note |
| `PROTEIN_TOPUP_STEP` | `0.5` | Servings added to a built meal's protein item when the day is below its protein minimum |
| `PROTEIN_TOPUP_STEPS` | `2` | Most top-up steps per meal |
| `REPAIR_STEP` | `0.25` | Servings taken off a built item when the plan would make a day-judged nutrient newly over |
| `REPAIR_STEPS` | `6` | Most repair steps before the slot is marked partial |
| `VARIANT_MAX` | `4` | Most "Show another plan" variants |
| `UNKNOWN_PENALTY` | `1.5` | Score cost of each unknown potassium, phosphorus or sodium value (unknown is never 0, note 03) |
| `FREE_FOOD_CARBS_G` | `5.0` | A food with at most this many carbs is free once the meal's carbs are done |
| `HIGH_GI_PENALTY_MIN_CARBS_G` | `15.0` | High-glycaemic foods cost a point from one carb choice |
| `FILLS_CARBS_MIN_G` | `15.0` | "Brings the meal to … carbs" needs at least one carb choice |
| `LOW_K_REASON_MG` | `100.0` | "Low in potassium" at or below this portion amount |
| `LOW_P_REASON_MG` | `50.0` | "Low in phosphorus" at or below this portion amount |
| `MAX_NAME_CHARS` | `60` | Food names in sentences are cut to this length (custom names are untrusted text) |
| `RENAL_MEDIUM` | `{"potassium_mg": 101.0, "phosphorus_mg": 101.0, "sodium_mg": 141.0}` | Per-portion "medium" thresholds of the renal rating (the app's warnings, ARCHITECTURE) |
| `RENAL_HIGH` | `{"potassium_mg": 200.0, "phosphorus_mg": 150.0, "sodium_mg": 400.0}` | Per-portion "high" thresholds (above this, rounded to whole mg) |
<!-- rules-table:end -->

## Sources

The full list with quotes and access dates is note 06 §10. The ones behind the numbers above:
American Kidney Fund Kidney Kitchen, "Where do I find meal plans for low potassium?" and "Can I use
artificial sweeteners?" (per-meal potassium); Satellite Healthcare, "Food labels" (per-meal sodium);
Kalantar-Zadeh et al., CJASN 2010, and Noori et al., IJKD 2010 and CJASN 2010 (phosphorus per gram of
protein); National Kidney Foundation, "If you need to limit protein" (7 g = 1 oz); Mamerow et al., J Nutr
2014 (spreading protein); ADA *Standards of Care in Diabetes—2026*, Sections 5 (Recs 5.18, 5.19 alcohol; 5.27,
5.28) and 6
(Recs 6.15, 6.16); Smart et al., Diabet Med 2009 and 2012 (carbohydrate precision); UW Medicine *Food
Choice Lists* (free foods ≤ 5 g); CDC *Clear Communication Index* (numbers in text); the diet guide
(`docs/diet-guide.md`) for the low-treatment table, leaching and the sample day.
