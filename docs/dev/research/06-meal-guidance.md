# 06 · Rule-based meal guidance ("what fits now", swaps, plan my day, insights) with optional AI

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. |
| Date researched | 2026-10-05 |
| Scope | The deterministic guidance engine that runs with AI switched off: per-meal budgets, ranking foods and saved meals for the next meal, lower-potassium/phosphorus/sodium swaps with the same carbohydrate, a meal-plan builder for the rest of the day, end-of-day and weekly insights in plain language, explanation strings, API shapes, data-model changes, performance budget on a Raspberry Pi, test vectors, and the contract that lets an optional AI re-rank and explain (never decide). |
| Out of scope | The AI provider layer, prompts, SSRF policy and guardrail pipeline ([`04-optional-ai.md`](04-optional-ai.md) owns them; this note defines what the rules engine hands to it and how AI output is re-validated). Accounts and the settings UI (the settings/multi-user note owns them; this note lists only the guidance settings). Handbook content (the handbook note owns the pages; this note proposes the topic slugs it links to). How age, sex and other factors change the targets (the target-personalisation note; the engine only consumes targets). Camera, barcode and photo entry ([`03-barcode-and-photo.md`](03-barcode-and-photo.md)). |
| Supersedes | The "Layer 0" sketch in [`04-optional-ai.md`](04-optional-ai.md) §4 R2 (`app/guidance.py`, weights, the swap endpoint's parameters). Where the two differ, this note wins; 04's AI sections (R3–R14) are unchanged. |
| Re-verify | The per-meal rules of thumb (AKF Kidney Kitchen, Satellite Healthcare) yearly; ADA *Standards of Care* every January; the performance numbers on real Raspberry Pi hardware before release and after each Python upgrade. See [§9](#9-how-to-re-verify). |

The numbers in §2 F8, §4 and §6 come from a throw-away reference prototype run against the real
`data/foods.json` (395 foods) and a 5× synthetic copy (1,975 foods) on 2026-10-05, except the vectors
marked *hand-computed* (TV-B6, TV-S4, the TV-P4 forced top-up and the insight vectors, which were
computed by hand or with small scripts). The prototype lived only in the session scratchpad; once merged, the tests in
`tests/guidance/` are the source of truth.

---

## 1. Context

### 1.1 The ask

> "some kind of guidance would be ideal while planning or picking your next meal. if this can use my
> hermes agent or local ollama or just an open ai key that would be nice or if these insights can be
> done without AI... ideally it could be done without AI and then if wanted enabled to use AI."

And, from the same request: a patient handbook to link to, a public open-source release ("make sure
everything is documented and able for other sessions AIs/humans to pickup and improve"), multi-user
settings, and personalised targets. So the guidance must:

1. **Work with no AI at all**, on a Raspberry Pi, offline on a LAN.
2. Be **deterministic, explainable and testable**: every suggestion carries the numbers and the
   reason, and the same inputs always give the same output.
3. **Never weaken a warning** the app already gives, and **never get in the way of treating a low**.
4. Use only data the app has: the food DB (395 builtin + custom + USDA/Open Food Facts imports), saved
   meals, the day's eaten and planned entries, recent history and the care-team targets.
5. Let an optional AI **re-rank and explain** the engine's own candidates, with every AI-proposed food
   re-validated by the same rules.

### 1.2 What exists today (v0.2) that the engine builds on

* `app/nutrients.py` (pure): the nutrient registry, per-serving thresholds (`THRESHOLDS`: K 101/200 mg,
  P 101/150 mg, Na 141/400 mg, carbs 15/30 g, protein 15/25 g), `food_warnings()`, `kidney_rating()`,
  `daily_status()`, projected alerts, `meal_carb_alerts()` and `suggest_targets()`. Targets include
  `carbs_per_meal_g` (default `round5(daily carbs / 4)`, minimum 15).
* Judgement periods (ARCHITECTURE "Why periods matter"): potassium, sodium, fluid and carbohydrate
  **per day**; phosphorus, protein, calories and calcium on the **weekly average**; on hemodialysis K, Na
  and fluid also **since the last session** (`app/periods.py::interdialytic_interval`).
* `app/log.py::day_figures()` already computes eaten, planned and projected totals per meal.
* Saved meals (`meal_templates`, `items_json` of `{food_id, servings}`) and `POST /api/meals/{id}/apply`.
* Flags: `phosphate_additive`, `high_gi`, `counts_as_fluid`, `avoid_ckd`, `hypo_treatment`,
  `low_potassium_fruit`, `processed`. `hypo_treatment` switches off the carbohydrate warning; the
  diet guide says hypo treatments are **logged against the potassium budget but never warned against
  or blocked** (`docs/research/ckd-diet.md` §3, `docs/research/food-lists.md`).
* There is **no** link between a log entry and "this was a hypo treatment": orange juice drunk for a
  low and orange juice at breakfast look the same. The engine needs that distinction (§4.11).
* `ARCHITECTURE.md` non-goals: insulin dose calculation and medical advice. They stay non-goals.

### 1.3 Constraints from the sibling notes

* [`01-rootless-and-security.md`](01-rootless-and-security.md): AI output never triggers writes; keys
  never reach the browser; the browser only talks to the app (`connect-src 'self'`).
* [`02-ios-pwa.md`](02-ios-pwa.md): the PWA caches only the static shell; API responses are `no-store`
  and the offline outbox carries a `client_id` per log entry. Guidance therefore runs **on the server**
  and the UI shows the last result it fetched when offline.
* [`03-barcode-and-photo.md`](03-barcode-and-photo.md): Open Food Facts and label-read foods often have
  **no potassium or phosphorus value** (stored as `null`, never 0). The engine must treat unknown as
  unknown.
* [`04-optional-ai.md`](04-optional-ai.md): the AI layer receives "Layer 0" output only, picks from a
  candidate enum, and its ideas go through the V1–V9 validator. This note defines Layer 0 precisely and
  gives 04 a single function to re-validate with (§4.13).

---

## 2. Findings

### F1. Per-meal potassium and sodium: dietitian rules of thumb exist, all scale to ~30 % of the day

| Source | Rule | Daily context |
|---|---|---|
| American Kidney Fund, Kidney Kitchen, "Where do I find meal plans for low potassium?" (C. Feibig, RD) [1] | "600-700mg of potassium per meal and 100-200mg per snack"; avoid days with several high-potassium foods; if one meal is higher, cut snacks or other meals | 1,800–2,200 mg/day |
| American Kidney Fund, Kidney Kitchen, "Can I use artificial sweeteners?" (M. Chesney, RD) [2] | "under 2,100mg per day or <700mg per meal, less if you are going to have a snack" | stage 5 on dialysis |
| Satellite Healthcare (dialysis provider), "Food labels" [3] | sodium: "less than 600 mg per meal and less than 200 mg for a snack"; potassium < 250 mg per serving | 2,000–3,000 mg K/day |
| UW Medicine, *Healthy Eating* (KEEP class, clinician review 05/2015) [4] | high-potassium foods (250–500 mg per ½ cup): "Choose 1 each day"; medium (150–250): 2; low (20–150): 3 | sodium ≤ 2,000 mg/day |
| AKF "Beyond Bananas" handout (July 2026) [5] | high > 250 mg, low ≤ 150 mg per serving; "Foods low in potassium can become high potassium foods if a larger portion is eaten" | — |
| DaVita, "How to determine if a food is high or low potassium" [6] | high-potassium foods fit "as long as you manage other foods you would eat in the same day" | 2,000–3,000 mg/day |

**What follows for the engine.** At a 2,000 mg daily target, 600 mg per main meal is 30 %, and 100–200 mg
per snack is 5–10 %. Expressing the cap as a **fraction of the person's own target** (0.30 per main
meal, 0.15 for the whole snack slot, which in this app aggregates every snack of the day) reproduces
600 mg at 2,000 mg, gives 750 mg at the app's 2,500 mg hemodialysis starting point (close to AKF's
"< 700") and scales with whatever the care team sets. A fixed mg cap would be wrong for someone at
stage 3a with a 4,000 mg review ceiling.

**These are rules of thumb, not graded guideline statements.** No guideline (KDOQI 2020, KDIGO 2024)
gives a per-meal number. The engine therefore uses the caps as *soft structure* (a food that does not
fit is not suggested) and never as a new warning or alert.

**Dead link in the repo.** `docs/diet-guide.md` source [47] and `docs/research/ckd-diet.md` [47] cite a
University of Michigan PDF (`medicine.umich.edu/.../Holewinski.pdf`) for "≤ 600 mg Na or K per meal".
On 2026-10-05 it answers **301 → `https://medschool.umich.edu/`** (the document is gone). Replace it
with [1] and [3].

### F2. Phosphorus: no per-meal rule; judge by source and by phosphorus per gram of protein

* Phosphorus is judged on the multi-day average (KDOQI 2020; app ARCHITECTURE). No per-meal mg rule was
  found from a renal organisation; the engine applies the same 0.30 / 0.15 structure **by analogy**,
  labelled as such.
* Bioavailability differs by source: about 40–60 % of animal phosphorus is absorbed, plant (phytate)
  phosphorus less, and up to 100 % of inorganic additive phosphorus (processed cheese, colas)
  (Kalantar-Zadeh et al., CJASN 2010 [7]; Noori et al., IJKD 2010 [8]). The app already turns any
  `phosphate_additive` food red; the engine additionally **prefers additive-free foods** in ranking.
* **Phosphorus-to-protein ratio** is the useful quality signal for protein foods: on average about
  15 mg P per g protein [7]; Noori et al. recommend < 10 mg/g, with fresh egg white < 2 mg/g [8]. In
  maintenance hemodialysis patients, death hazard ratios across ratios < 12, 12–<14, 14–<16 and ≥ 16 mg/g were
  1.13, 1.00 (reference), 1.80 and **1.99** (Noori et al., CJASN 2010 [9]).
* **Consequence found in the prototype:** 36 of the 38 three-ounce meat, poultry and fish servings in
  the DB are "red" under the per-serving thresholds (K > 200, P > 150 or Na > 400 mg, or an additive;
  `docs/research/food-lists.md` A4 calls this "unavoidable").
  A naive score that subtracts points for red then only ever suggests egg whites. Protein foods must
  be judged **per gram of protein** (P:protein ≤ 10 good, ≥ 16 poor; K:protein ≤ 10 good, ≥ 20 poor),
  with sodium and additives still judged absolutely.

### F3. Protein: a daily range, a minimum that matters, and a case for spreading it

* Targets are a range: 0.6–0.8 g/kg ideal body weight at CKD 3–5 with diabetes, 1.0–1.2 g/kg on
  dialysis (KDOQI 2020 3.1.2–3.1.4; ADA 2026 Rec 11.3; already encoded in `suggest_targets()`). Below
  0.6 g/kg risks wasting and hypoglycaemia (diet guide §2).
* One protein portion: "Each 7 grams of protein = 1 oz of meat, poultry or fish" (NKF, *If you need to
  limit protein* [10]). The engine uses **≥ 7 g protein per portion** to classify a food as a protein
  food.
* Spreading protein evenly: in healthy adults, about 30 g at each of three meals gave 25 % higher 24-h
  muscle protein synthesis than a 10/16/63 g skew (Mamerow et al., J Nutr 2014 [11]). Not CKD-specific;
  the engine adopts an **even spread as a soft aim**, not a rule.
* On dialysis the binding constraint is the **minimum** (protein needs go up); before dialysis it is
  the **maximum**, but falling below the minimum is also harmful. The prototype showed that a
  symmetric "close to the middle" penalty under-shoots the minimum (34 g against a 42 g minimum for a
  70 kg person at stage 4); a **linear shortfall term** against the minimum fixed it (final prototype:
  46.8 g, inside 42–56 g).

### F4. Carbohydrate for type 1 diabetes: consistency per meal, ±10 g is tolerable, never dose

* ADA *Standards of Care 2026*, Section 5 [12]:
  * Rec 5.27: "Provide education on the glycemic impact of carbohydrate, fat, and protein tailored to an
    individual's needs, insulin plan, and preferences for care to optimize mealtime insulin dosing."
  * Rec 5.28: "Counsel people using fixed insulin doses about consistent patterns of carbohydrate
    intake with respect to time and amount while considering the insulin action time, as it can result
    in improved glycemia and reduce the risk for hypoglycemia." (B)
  * High-fat and/or high-protein mixed meals can cause delayed hyperglycaemia; insulin changes for them
    are a clinical decision.
* Precision: in 31 children and adolescents on intensive insulin therapy, a dose calculated for 60 g
  covered meals of 50–70 g with no difference in postprandial glucose (Smart et al., Diabet Med 2009
  [13]); a 20-g variation did change postprandial glycaemia (Smart et al., Diabet Med 2012), with 31 % of
  children hypoglycaemic 2–3 h after a 20-g overestimate (as summarised in [14]). **The engine's default
  carbohydrate tolerance is ±10 g per meal**, adjustable 5–20 g by the person (their diabetes team
  decides).
* NKF: 15 g = 1 carbohydrate serving, 3–6 per meal and 1–3 per snack (diet guide [7]). The engine's
  default snack-slot goal is half the meal goal, at least 15 g.
* "Free" foods have "no more than 5 grams carbohydrate and 20 calories per serving" (UW Medicine *Food
  Choice Lists*, 10/2021 [15]). The engine treats **≤ 5 g carbohydrate as negligible** for the meal
  carbohydrate check.
* **Swaps must keep the carbohydrate the same** (within the tolerance) so the person's own insulin
  arithmetic still applies; the explanation says so in grams and never mentions insulin.

### F5. Hypoglycaemia treatment is exempt from everything except honest logging

* Rule of 15: 15 g fast carbohydrate, recheck at 15 minutes, repeat (ADA 2026 Rec 6.15; 5–10 g on an
  automated insulin delivery system; diet guide §4 and [9] there). Never under-dose, never "sugar-free".
* Diet-guide policy: hypo treatments are logged against potassium but **never blocked or warned
  against**; glucose tablets are the first choice when there is a choice; "one rescue portion is a
  budgeting note".
* So: hypo-treatment foods are never meal suggestions; hypo-treatment entries do not count in the
  meal carbohydrate check, do not trigger "too many carbs" insights, and never get "swap ideas" that
  reduce the dose. They do count toward K, P, Na and fluid (the person really consumed them), and the
  only swap offered is "for your next low, X gives the same carbs with less potassium", at ≥ the
  person's hypo dose (default 15 g).

### F6. Plain-language numbers

CDC *Clear Communication Index* user guide [16]: item 15, "use numbers most often used by non-experts,
such as whole numbers"; item 16, "always explain what the numbers mean" and "avoid using qualitative
descriptors, such as high and low ... by themselves". The Federal Plain Language Guidelines moved to
digital.gov in 2025 [17]. Consequences: whole numbers (mg and mL as integers, grams to one decimal only
below 10 g), "4 of 7 days" rather than 57 %, every "high" paired with the number and the target, and
active voice.

### F7. Algorithms and libraries

* Choosing foods under several nutrient limits is a multi-dimensional knapsack (the classic "diet
  problem"), NP-hard in general but tiny here: a meal has 1–5 items chosen from a few hundred foods per
  role, with a handful of portion sizes.
* Exact solvers on PyPI, checked 2026-10-05 via the PyPI JSON API:

  | Package | Version (date) | Licence | Notes |
  |---|---|---|---|
  | `PuLP` | 4.0.0 (2026-09-25) | MIT | modelling layer; bundles CBC |
  | `ortools` | 9.15.6755 (2026-01-14) | Apache-2.0 | CP-SAT; large native wheel |
  | `scipy` | 1.18.1 (2026-08-21) | BSD-3-Clause | `scipy.optimize.milp` uses HiGHS; pulls `numpy` 2.5.3 |
  | `highspy` | 1.15.1 (2026-07-02) | MIT | HiGHS directly |

  All add tens of MB of native code to an image that is otherwise pure Python, need aarch64 wheels, and
  produce an optimum that is hard to explain ("why rice and not pasta?"). The problem size does not need
  them: a beam search over the top few candidates per role finds plans the prototype could not improve
  on by hand, in milliseconds (F8).

### F8. Performance measured with the reference prototype

Machine: cloud VM, Intel Xeon @ 2.1 GHz, CPython 3.11.15, one thread. Median of 7–21 runs, ms.

| Foods in DB | Build food vectors (cacheable) | What fits now | Swap ideas | Plan 4 meals (pool 200) | Plan 4 meals (pool 120) |
|---|---|---|---|---|---|
| 395 (real) | 0.8 | 3.2 | 0.3 | 15.5 | 16.0 |
| 1,975 (5× synthetic) | 4.0 | 17.7 | 1.2 | 29.0 | 20.5 |

(What-fits and plan-day with cached vectors; plan-day with beam width 16.) Evaluations per request:
what-fits ≈ 3.3 × eligible foods (6,074 food scores at 1,835 eligible); plan-day for 4 meals 6,653 food
scores and 836 meal scores at pool 200. The two biggest wins found while profiling were caching the per-food vectors
(one third of plan-day time) and evaluating only the roles a meal needs (40 % fewer evaluations).

**Raspberry Pi.** Raspberry Pi Ltd states the Pi 5 (Cortex-A76, 2.4 GHz) is "over twice as fast" as the
Pi 4 [18]. No trustworthy CPython-on-Pi-4 versus this VM figure was found, so this note **assumes the
Pi 4 is 4–6× slower single-threaded** and sets the x86 budget accordingly (§4.12): what-fits ~70–105 ms
and plan-day ~115–175 ms (pool 200) or ~80–125 ms (pool 120) at 2,000 foods on a Pi 4. That is inside the 200 ms budget, but it is an
estimate: `scripts/bench_guidance.py` (§4.12) must be run on a real Pi 4 before release.

### F9. The data the engine works with (this repo, 2026-10-05)

* 395 builtin foods. Per serving: potassium median 137 mg (p90 365), phosphorus median 50 mg (p90 222),
  sodium median 70 mg (p90 522), carbohydrate median 10.4 g (p90 35.4).
* Flags: `processed` 137, `high_gi` 67, `counts_as_fluid` 62, `phosphate_additive` 45,
  `low_potassium_fruit` 16, `hypo_treatment` 13, `avoid_ckd` 3.
* Builtin nulls only in sugar, fibre and saturated fat; **custom, label and Open Food Facts foods often
  have null K/P** (note 03).
* Roles from the rule in §4.3: protein 82, mixed dishes 21, starch 58, vegetable/fruit 80, drink 35,
  extra 119.
* **Ingredients that must never be suggested on their own** are in the DB: flour, table salt, baking
  powder, black pepper, vinegars, oils, brown sugar, margarine, butter. The prototype suggested "flour,
  all-purpose ×2" as a lunch starch and as a swap for a baked potato. A new curated flag `ingredient`
  fixes it (§4.11).

### F10. What went wrong in the naive prototype (kept here so nobody repeats it)

| Symptom | Cause | Fix adopted |
|---|---|---|
| Root beer ×1.5 and marshmallows ×2 ranked top for dinner | "fills the carb gap" bonus applied to sweets and drinks | Carb-fill bonus only for starch, mixed and veg/fruit roles; −1 for `high_gi` at ≥ 15 g; drinks and extras only at ½ or 1 serving |
| Rice with 45 g carbs rated red and pushed down | per-serving carbohydrate warning counted in the rating | Guidance uses a **renal rating** (K, P, Na, avoid, additive only); carbohydrate is handled by the meal goal |
| Only egg whites suggested as protein | every meat portion is red under per-serving K/P thresholds | Protein foods judged per gram of protein (F2) |
| Plan under the protein minimum (34 g vs 42 g) | symmetric penalty around the middle of the range | Linear shortfall term against the minimum (§4.7) |
| Dialysis plan at 54 g against a 70 g minimum | phosphorus usage penalty outweighed protein | Dialysis: linear shortfall weight 6 against the middle of the range |
| Saved "Usual dinner" planned as the snack | saved meals had no meal slot | `meal_templates.meal_hint` (§4.11) |
| Baked potato swaps were corn and peas only | same-category search stopped after 3 hits | Search same category **and** same role in other categories, bonus for same category |
| Processed cheese swapped for butter and cream | low-carb, low-protein foods matched "by serving" | Match by protein from 3 g; same-family bonus (first word of the name) |
| Orange juice swap could not find apple or cranberry juice | `hypo_treatment` foods excluded everywhere | Allowed as swaps for beverages; hypo mode swaps only within hypo foods |
| Same rice at breakfast, lunch and dinner | variety looked only at exact food ids eaten before the request | Plan-time variety includes foods already placed in earlier slots and the same name family |
| A built lunch with no starch (0 of 70 g carbs) scored 7 points below the best combination | the capped carb penalty was flat below −20 g, and starch portions were only ½ or 1 | Carb penalty quadratic then linear (no plateau); a carbohydrate-targeted portion per candidate; beam width 16. Against exhaustive search over the same candidates on 40 random meals the beam is now never more than 0.43 points worse (median 0) |
| Pasta at breakfast | roles know nothing about meal customs | Saved and usual meals first, a per-slot habit bonus; curated `typical_meals` tags deferred to v0.4 |

---

## 3. Options compared

### 3.1 Algorithm family

| Option | Works offline, no AI | Explainable | Quality | Speed on Pi | New deps | Verdict |
|---|---|---|---|---|---|---|
| A. Static "good foods" lists (green-rated foods) | Yes | Yes | Poor: ignores today's budget, carbs and protein | Trivial | None | Only as the empty-day fallback text |
| **B. Weighted rules: hard filters + additive score + greedy/beam meal builder** | Yes | **Yes: every term has a reason string** | Good (F10 fixes) | 3–29 ms x86 (F8) | **None** | **Chosen** |
| C. Exact MILP per meal/day (PuLP 4.0.0, OR-Tools 9.15, SciPy 1.18.1 + HiGHS) | Yes | Weak ("the optimum") | Optimal for the stated objective, which is itself a heuristic | 10–200 ms + solver start | 30–60 MB native wheels | Rejected for v0.3; could be an offline experiment to measure B's gap |
| D. Learned ranking (collaborative filtering, embeddings) | Needs training data | Poor | Unknown; single-user DBs have no data | — | numpy et al. | Rejected |
| E. LLM chooses foods and numbers | No | Poor | Unreliable K/P/Na numbers (04 F7) | Seconds | Provider | Rejected (04 §3.1 C) |

### 3.2 Per-meal cap for K, P, Na

| Option | Pro | Con | Verdict |
|---|---|---|---|
| Fixed 600 or 700 mg per meal | Matches handouts literally | Wrong for 3,500–4,000 mg review ceilings and for 1,500 mg restrictions | No |
| **Fraction of the person's daily target: 0.30 per main meal, 0.15 for the snack slot** | Reproduces 600 mg at 2,000 mg (F1); scales with the care team's target | Phosphorus by analogy only | **Chosen** |
| No per-meal cap, only "fair share of what is left" | Simplest | Lets a light day end in a 1,500 mg dinner | No; caps also prevent dumping |

### 3.3 Budgeting week-judged phosphorus

| Option | Behaviour | Verdict |
|---|---|---|
| Daily target only | Ignores that phosphorus is judged weekly; a high Monday changes nothing | No |
| Remaining weekly total, unclamped (04 R2 sketch) | One high-phosphorus weekend leaves ~0 for days; unlogged days count as 0 and inflate the room | No |
| **Allowance = target × (n + 1) − sum of the n logged days among the previous 6, clamped to 0.8–1.2 × target** | Balances the week gently, never starves a day (protein needs phosphorus), ignores unlogged days | **Chosen** |

### 3.4 Plan builder search

| Option | Quality | Cost per meal at 2,000 foods | Verdict |
|---|---|---|---|
| Pure greedy (best protein, then best starch, then best veg) | Dead-ends: the starch that fits after a big protein may not exist | Lowest | No |
| Exhaustive over top-k per role (k = 6, 3–4 portions each, roles skippable) | Best for the candidate set | ~2,000–3,000 meal evaluations per main meal | Too slow for the Pi budget; used as the test oracle |
| **Beam search, width 16, top 6 per role, portions {best, ½, 1, carbohydrate-targeted}, then carbohydrate fine-tune on the starch in ¼ servings** | ≤ 0.43 points below exhaustive on 40 random meals (median 0); width 8 was up to 0.85 below | ~250 meal evaluations per main meal (836 for a 4-meal day) | **Chosen** |
| MILP | Optimal | Solver dependency | No (3.1 C) |

### 3.5 Where the engine runs

| Option | Verdict |
|---|---|
| **Server, pure Python package `app/guidance/`** | **Chosen**: one implementation, unit-testable, uses the DB directly, same code validates AI output |
| Client JavaScript (works offline) | Rejected: duplicates every rule in a second language (the v0.2 preview build already shows the parity cost); the PWA shows the last fetched guidance offline instead |

### 3.6 What the optional AI may do

| Option | Verdict |
|---|---|
| AI writes meals and numbers | Rejected (04 §3.1 C) |
| **AI re-ranks and explains the engine's candidates, may combine candidates into ideas; every item re-validated by `guidance.check_meal()`** | **Chosen** (consistent with 04 §3.1 B) |
| AI rewrites insights | Deferred to v0.4: insight numbers are the product; v0.3 insights are rule-only |

---

## 4. Recommendation

### 4.1 Overview and file layout

A pure, deterministic engine in a new package. Only `context.py` and `api.py` touch the database or
FastAPI; everything else is pure functions over plain data, like `app/nutrients.py`.

```
app/guidance/
  __init__.py
  rules.py        constants (RULES, RULES_VERSION = "2026-10-05.1"), roles, eligibility        (pure)
  budget.py       open_slots(), week_allowance(), interdialytic_allowance(), meal_room()       (pure)
  vectors.py      FoodVec, build_vectors(), renal_level(), protein_quality()                  (pure)
  score.py        score_food(), score_meal(), check_meal()                                      (pure)
  fits.py         what_fits(), fitting_saved_meals()                                            (pure)
  swaps.py        find_swaps(), portion_option(), hypo_options()                                (pure)
  planner.py      plan_day(), build_meal() (beam search), usual_combos(), energy_note()         (pure)
  insights.py     day_insights(), period_insights(), sources(), short_name()                    (pure)
  messages.py     every user-facing template, number and portion formatting                     (pure)
  topics.py       TOPIC_PAGES (handbook slugs) and the TIPS table                                (pure data)
  ai_bridge.py    candidates_for_ai(), validate_ai_items()  (used by app/ai/, note 04)           (pure)
  context.py      GuidanceContext loader (SQL), VectorCache                                      (I/O)
  api.py          APIRouter(prefix="/api/guidance")                                              (I/O)
data/combos.json  starter combos (curated; diet-guide §6 sample day meals)
docs/guidance.md  how the guidance works, for users and contributors (generated from this note)
scripts/bench_guidance.py   timing on real hardware (Raspberry Pi)
tests/guidance/   fixtures.py, test_budget.py, test_vectors.py, test_score.py, test_fits.py,
                  test_swaps.py, test_planner.py, test_insights.py, test_messages.py,
                  test_api_guidance.py, test_perf_guidance.py, test_ai_bridge.py
```

### 4.2 Inputs: `GuidanceContext`

`context.load(conn, user_id, date)` returns a frozen dataclass; every query is scoped to `user_id`
(the multi-user note's `current_user` dependency):

| Field | Query | Size |
|---|---|---|
| `profile` | targets, `warn_fraction`, dialysis mode and days, diabetes, guidance settings (§4.14) | 1 row |
| `day` | all entries of `date` (eaten and planned) with snapshot nutrients, `purpose`, food flags and role | ≤ ~40 |
| `history` | eaten entries of `date − 13 … date − 1` (habit, variety, week allowance) | ≤ ~700 |
| `history60` | eaten entries of `date − 60 … date − 1`, only for usual-combo mining in plan-day | ≤ ~3,000 |
| `saved_meals` | user's templates with resolved items | ≤ ~100 |
| `vectors` | `VectorCache.get(user_id, foods_rev)`: builtin vectors shared, user's custom foods appended | 400–2,000 |

`VectorCache` is a process-wide dict keyed by `(foods_rev, user_id)`; `meta.foods_rev` is an integer
bumped by every food insert, update, hide, delete and builtin import. Memory: ~200 bytes × foods.

If the profile has **no numeric potassium, phosphorus or sodium target and no `carbs_per_meal_g`**,
every guidance endpoint answers 200 with `{"status": "no_targets", "message": "Set your targets in
Settings first; guidance compares foods with the targets your care team gave you."}`.

### 4.3 Constants, roles and eligibility (`rules.py`)

All numbers live in one `RULES` mapping, are returned by `GET /api/guidance/rules` (for the docs page
and for contributors), and are versioned by `RULES_VERSION`. Changing any of them requires updating the
golden test vectors in the same PR.

| Name | Value | Basis |
|---|---|---|
| `MEAL_WEIGHT` / `MEAL_CAP_FRACTION` | breakfast, lunch, dinner 0.30; snack slot 0.15 | F1 |
| `CAP_KEYS` | potassium, phosphorus, sodium (fluid has no per-meal cap) | F1, F2 |
| `NEGLIGIBLE` | K 50 mg, Na 50 mg, P 30 mg, fluid 30 mL, carbs 5 g | "free food" ≤ 5 g (F4); amounts below the app's "medium" thresholds |
| `USAGE_WEIGHT` | K 3, Na 2, P 2 (+1 when phosphorus is not `ok` this week), fluid 2 | K acts fastest (diet guide §2) |
| `PORTIONS_MAIN` | 1, ½, 1½, 2 servings (protein, starch, veg/fruit, mixed) | |
| `PORTIONS_SIDE` | 1, ½ (drinks, extras) | F10 |
| `WEEK_LOOKBACK_DAYS`, `WEEK_CLAMP` | 6; 0.8–1.2 × target | §3.3 |
| `CARB_TOLERANCE_G` | 10 (user setting 5–20) | F4 |
| `SNACK_CARB_GOAL` | `targets.carbs_per_snack_g`, else `max(15, 5 × round(carbs_per_meal_g / 2 / 5))` | F4 |
| `HYPO_DOSE_G` | 15 (user setting 5–30, "from your diabetes team") | F5 |
| `HIGH_K_ENTRY_MG` | 200 (the app's per-serving "high") | F1 |
| `PROTEIN_ROLE_MIN_G` | 7 | F3 |
| `STARCH_ROLE_MIN_CARBS_G` | 15 (one carbohydrate choice) | F4 |
| `P_PER_G_PROTEIN` | good ≤ 10, poor ≥ 16 | F2 |
| `K_PER_G_PROTEIN` | good ≤ 10, poor ≥ 20 | design choice; chicken breast 8, ground chicken 29 |
| `PROTEIN_AIM_FLOOR_G` | 5 | avoids division by tiny aims |
| `MIN_SHOW_SCORE` | 0 | negative-scoring foods are not "fits" |
| `GROUP_LIMITS` | protein 3, starch 3, veg_fruit 3, extra 2; ≤ 2 per category; ≤ 11 total | |
| `BEAM_WIDTH`, `PER_ROLE`, `POOL_PER_ROLE`, `FAMILIAR_MARGIN` | 16, 6, 200 (env `GUIDANCE_POOL_PER_ROLE`), 3.0 | F8, §3.4 |
| `SLOT_HABIT_BONUS` | +1 when the food was eaten in this meal slot on ≥ 2 of the last 14 days | F10 |
| `SWAP_MIN_REDUCTION` | 25 % lower on every triggering nutrient | |
| `SWAP_CARB_MATCH` / `SWAP_PROTEIN_MATCH` | ± max(5 g, 10 %) / ± max(3 g, 15 %), portions in ¼ servings 0.25–3 | F4 |
| `INSIGHT_MAX`, `SOURCE_MIN_SHARE`, `MIN_LOGGED_DAYS` | 6, 10 %, 3 | |

**Role** (`vectors.role_of(food)`): the curated `role` override from `foods.json` if present, else

1. `Meat, Poultry & Eggs`, `Fish & Seafood` → `protein`;
2. `Prepared & Fast Food` with protein ≥ 7 g **and** carbohydrate ≥ 15 g → `mixed` (counts as protein
   and starch);
3. `Dairy & Alternatives`, `Legumes, Nuts & Seeds`, `Prepared & Fast Food` with protein ≥ 7 g → `protein`;
4. `Grains & Breads` → `starch`;
5. `Vegetables`, `Legumes, Nuts & Seeds`, `Prepared & Fast Food` with carbohydrate ≥ 15 g → `starch`
   (potatoes, corn, peas, lima beans);
6. `Vegetables`, `Fruits` → `veg_fruit`;
7. `Beverages` → `drink`; everything else → `extra`.

The **group** shown in the UI: protein (protein, mixed), starch, veg_fruit, extra (drink, extra).

**Eligible for meal suggestions** (what-fits, plan-day): not hidden; not `avoid_ckd`; not
`hypo_treatment`; not `ingredient`; category is not `Diabetes supplies`; not in the user's exclusions
(§4.14). **Eligible for swaps**: same, except `hypo_treatment` foods are allowed when the original food
is a beverage, and hypo mode (§4.6) uses *only* hypo-treatment foods, `Diabetes supplies` included.

**Renal level** (`renal_level(k, p, na, additive)`), the guidance version of the rating: evaluate K
(101/200), P (101/150) and Na (141/400) on the integer-rounded portion amounts; any above "high" → red,
any at "medium" → yellow; `phosphate_additive` → red. Carbohydrate and protein warnings are not part
of it (F10). It must agree with `nutrients.threshold_level()` for every builtin food at every portion
(property test), but is written without `Decimal` for speed.

### 4.4 Budget: the room left for one meal (`budget.py`)

Notation: `T_k` the daily target (max side), `proj_k` the day's projected total (eaten + planned,
**including** hypo-treatment entries and virtual entries placed by the plan builder), `used_k(m)` the
projected amount already in meal `m`.

**Open slots** `O(m)`: `m` itself; every later main meal (breakfast < lunch < dinner) with **no entries
at all**; and the snack slot if it has no entries. When `m` is the snack slot: the snack slot and every
main meal with no entries. A slot that already has planned entries is not open (its plan is in `proj`).
Earlier empty main meals are treated as skipped.

**Allowance today** `A_k`:

* Day-judged K, Na, fluid: `A_k = T_k`. On hemodialysis with dialysis days set, also
  `A_k = min(T_k, (T_k × D − eaten_since_before_today) / days_left)` where the interval is
  `periods.interdialytic_interval(date)`, `D` = days from the last session (inclusive) to the next
  session (exclusive), `eaten_since_before_today` = eaten total from the last session to yesterday, and
  `days_left` = days from today to the next session (≥ 1).
* Week-judged phosphorus: `A_P = clamp(T_P × (n + 1) − S_P, 0.8 T_P, 1.2 T_P)` where `n` is the number
  of logged days (≥ 1 eaten entry) among the previous 6 days and `S_P` their eaten phosphorus.
* `level_k` = `over` if `proj_k / A_k > 1`, `caution` if ≥ `warn_fraction`, else `ok`.

**Room** for nutrient `k ∈ {K, P, Na, fluid}` with a numeric target:

```
remaining_k = A_k − proj_k
share_k     = max(0, remaining_k) × w(m) / Σ_{o ∈ O(m)} w(o)            # w = MEAL_WEIGHT
cap_k       = MEAL_CAP_FRACTION(m) × T_k        (K, P, Na);   +∞ for fluid
room_k      = max(0, min(cap_k − used_k(m), share_k))
```

A nutrient without a numeric target has `room = +∞` and plays no part.

**Carbohydrate** (only when diabetes ≠ `none` and `carbs_per_meal_g` is set): `goal(m)` =
`carbs_per_meal_g` for main meals, `SNACK_CARB_GOAL` for the snack slot; `in_meal` = carbohydrate of
non-hypo entries in `m`; `gap = goal − in_meal`; `tol = CARB_TOLERANCE_G`. Hypo carbohydrate in the
meal is reported separately (`hypo_excluded_g`).

**Protein** (when a protein target exists): `mid = (min + max) / 2` (or the single bound),
`aim = max(0, mid − proj_protein) × w(m)/Σw(O)`, `aim_min = max(0, min − proj_protein) × w(m)/Σw(O)`.

**Meal composition**: which groups `m` already has (non-hypo entries), the number of entries in `m` and
in the day with potassium > 200 mg (non-hypo).

### 4.5 (a) "What fits now" (`fits.py`)

For every eligible food `f` and portion `q` (`PORTIONS_MAIN` or `PORTIONS_SIDE` by role), with
amounts `a_k = q × f_k`:

**Hard filters**, in this order; the first failure is the reason code (`"why_not"` in debug output):

1. `would_exceed:<k>`: `a_k > room_k + NEGLIGIBLE_k` for K, P, Na, fluid.
2. `unknown:<k>`: `f_k` is null and `level_k ≠ ok` (with `level_k = ok`, unknown costs −1.5 instead).
3. `too_many_carbs`: `a_carbs > NEGLIGIBLE_carbs` and `a_carbs > max(gap, 0) + tol`.
4. `high_warning:<k>`: the portion is above the "high" threshold for K, P or Na (or is
   `phosphate_additive` for P) while `level_k ≠ ok`.

**Score** (rounded to 2 decimals before sorting):

```
S =  base                                     # see below
   + static(f)                                # habit and variety, see below
   − 1.5 × (number of unknown K/P/Na values)
   − 0.5 × |q − 1|                            # prefer the standard serving
   − Σ_k USAGE_WEIGHT_k × (a_k / max(room_k, NEGLIGIBLE_k))²   for K, P, Na, fluid with a target
   + 2 × min(a_carbs, gap) / gap   if gap > tol and role ∈ {starch, mixed, veg_fruit}
   + 1                             if gap ≤ tol and a_carbs ≤ 5          # a free food when carbs are done
   − 1                             if high_gi and a_carbs ≥ 15
   + 1.5  if role ∈ {protein, mixed} and the meal has no protein yet
   + 1.5  if role ∈ {starch, mixed} and the meal has no starch and gap > 15
   + 1.0  if role = veg_fruit and the meal has no vegetable or fruit
   + 1.5 × min(a_protein, A) / A − min(2, ((a_protein − A)/A)²)[if a_protein > A]
                                     if role ∈ {protein, mixed};  A = max(aim, 5)
   + 1  if eaten in this meal slot on ≥ 2 of the last 14 days                  # SLOT_HABIT_BONUS
   − 2  if a_K > 200 and the meal already has a > 200 mg potassium entry
   − 1  if a_K > 200 and the day already has ≥ 2 such entries         # AKF/UW: not several high-K foods a day
```

`base`:

* **Protein foods** (role protein or mixed with `a_protein ≥ 7`): `1 + (+1 if P/protein ≤ 10, −1.5 if
  ≥ 16) + (+0.5 if K/protein ≤ 10, −1 if ≥ 20) − 3 if a_Na > 400 − 3 if phosphate_additive`.
* **All other foods**: renal level green +3, yellow +1, red −3.

`static(f)` (computed once per request in the vectors): `−2` if `phosphate_additive`; `−0.5` if
`processed`; `+ min(1.5, 0.5 × distinct days eaten in the last 14)`; `+0.5` if in a saved meal; `−1.5`
if already eaten or planned today; `−0.5 ×` the number of the previous 2 days it was eaten; `−0.75` if
another food of the same family (first word of the name, case-folded) is already in today's log.

**Best portion per food**: the portion with the highest score; ties → lower potassium, then
phosphorus, then sodium amount.

**Ordering and tie-breakers** across foods: score ↓, potassium amount ↑, phosphorus ↑, sodium ↑,
`casefold(name)` ↑, food id ↑. **Selection**: walk the sorted list, stop at the first score <
`MIN_SHOW_SCORE`, skip a food when its group or category limit is reached, stop at the limit (default 11).
The UI shows the result in groups ("Protein", "Starch", "Vegetables and fruit", "Extras").

**Reasons** (≤ 2 positive + ≤ 1 caution per food), in priority order: `adds_missing_group`,
`fills_carbs`, `low_potassium` (portion ≤ 100 mg), `low_phosphorus` (≤ 50 mg), `protein_quality`
(P/protein ≤ 10), `you_eat_often` (≥ 2 days in 14), `free_food`, `half_portion` (½ chosen because 1
failed a hard filter); caution: `unknown:<k>`. Texts are in §4.9.

**Saved meals that fit** (`fitting_saved_meals`): templates whose `meal_hint` equals `m` (or is null and
`m` is a main meal), tried at scale 1, ¾, ½; the first scale that passes `check_meal()` is kept and
scored with `score_meal()` minus `1 × (1 − scale)`; sorted by score, then name; at most 3 returned.
Templates containing an `avoid_ckd` item are never returned. "Usual meals" mined from history (§4.7)
are returned the same way with `source: "usual"`.

**Tips** come from `topics.TIPS`, a table of `(condition → text, handbook slug)` evaluated on the day
state, at most 2: e.g. potassium `caution`/`over` → potassium-leaching; phosphorus not `ok` this week →
phosphate-additives; sodium `caution` → hidden sodium; fluid `caution` on dialysis → fluid tips;
dialysis and protein below the day's minimum → "add a protein portion"; meal carbohydrate already at the
goal → free foods. Tip texts are maintainer-written and reviewed against `docs/diet-guide.md`.

### 4.6 (b) "Swap ideas" (`swaps.py`)

Input: a food and an amount for a meal on a date (before saving), or an existing entry. Modes:

* `normal`;
* `hypo` when the entry's `purpose` is `hypo` or the request says `purpose=hypo` or the food is
  `hypo_treatment`;
* `avoid` when the food is `avoid_ckd` (every same-category food is a candidate; the trigger is the
  flag).

**Triggers** (normal mode) for K, P, Na: the portion is above the per-serving "high" threshold, or above
`room_k + NEGLIGIBLE_k`; P is also triggered by `phosphate_additive`. Fluid triggers when it exceeds the
fluid room. No trigger → `{"swaps": [], "reason": "no_warning"}`. In hypo mode the only trigger is
potassium > 0.

**Matching dimension** keeps the person's arithmetic the same:

* carbohydrate when the original has ≥ 10 g; in hypo mode always carbohydrate, with the target
  `max(original carbs, HYPO_DOSE_G)` and portions rounded **up** to the next ¼ serving (never under-treat);
* otherwise protein when the original has ≥ 3 g;
* otherwise one serving.

Portion `q = round_to_quarter(target / candidate_per_serving)`, clamped to 0.25–3; the candidate is
dropped when the matched amount misses by more than `SWAP_CARB_MATCH` or `SWAP_PROTEIN_MATCH`.

**Pool**: same category **or** same role (normal mode); hypo-treatment foods only (hypo mode).
**Accept** a candidate only if every triggering nutrient is at least 25 % lower; it has no
`phosphate_additive` when that was a trigger; and no other nutrient goes above its room where the
original was lower (a swap must not create a new problem; fluid included).

**Score**: `Σ_{k∈triggers} USAGE_WEIGHT_k × (orig_k − new_k)/orig_k` + renal level (green 1.5, yellow
0.5, red −1.5) + 1 same category + 1 same family + 1 if the portion fits the meal room +
`min(1, max(0, static(f)))` − 1 if `processed` − `0.1 × |carb difference in g|`. Ties: potassium ↑, name ↑, id ↑. At most
5 swaps.

**Fallbacks**, always computed:

* `portion_option`: the largest of ¾ and ½ of the original amount that clears every trigger and fits
  the room, with the explicit note that carbohydrate changes ("count the new amount"). A
  `phosphate_additive` trigger cannot be cleared by a smaller portion, so such foods get none.
* tips: leaching for potatoes, sweet potatoes, yams, carrots, beets and winter squash (name match,
  `Vegetables`), additives for `phosphate_additive`, the hypo card in hypo mode.

**Hypo options** (`GET /api/guidance/hypo-options`): the person's hypo-treatment foods at the dose
portion (`ceil_to_quarter(HYPO_DOSE_G / carbs per serving)`), ranked by potassium ↑, phosphorus ↑,
fluid ↑ (when fluid is targeted), name ↑. Never filtered by any budget. Never sent to AI (04 G7).

### 4.7 (c) "Plan the rest of my day" (`planner.py`)

Input: date, slots (default: every slot with no entries), options. Slots are filled in order
breakfast, lunch, dinner, snack. For slot `i`, the room is computed with `O = slots[i:]` (later
requested slots keep their share) and with the items already placed in earlier slots added to the day
as virtual planned entries.

**Options per slot**, all checked by the same `check_meal()`:

1. **Saved meals** with matching `meal_hint`, scale 1, ¾, ½ (as §4.5).
2. **Usual meals** mined from `history60`: group eaten entries by `(date, meal)` into a set of
   `(food_id, servings rounded to ¼)`; keep sets of 2–6 items seen on ≥ 2 different dates for this meal
   slot; name them "Your usual lunch: chicken, rice, green beans".
3. **Starter combos** from `data/combos.json` (curated, reviewed; v0.3 ships the four meals of the
   diet-guide §6 sample day), only when every referenced builtin food exists.
4. **Built meal**: beam search.
   * Role sequence: main meals `protein → starch → veg_fruit`; snack slot one item from
     `veg_fruit | starch | extra | drink`.
   * Candidates per role: the `PER_ROLE` (6) best foods by `score_food` (portions 1, ½ and, for
     protein, 1½), drawn from the `POOL_PER_ROLE` (200) foods of that role pre-ranked statically
     (renal level at one serving, then `static`, then potassium per serving).
   * Portions tried per candidate: its best single-food portion, ½, 1, and the carbohydrate-targeted
     portion `round_to_quarter((gap − carbs so far) / carbs per serving)` (0.25–3) when more than `tol`
     grams are still missing.
   * Beam width 16, ordered by `score_meal` of the partial meal (the empty meal is scored too, so
     skipping a role is a real option); each step may skip the role; a `mixed` item fills the starch
     step.
   * After the last role, fine-tune the starch portion over ¼ to 3 servings to bring carbohydrate
     closest to the goal.

**Meal check** (`check_meal(items, room)`, the single gate used by plan-day, saved meals and AI):
totals of K, P, Na, fluid ≤ `room + NEGLIGIBLE`; carbohydrate `total − gap ≤ tol`; no `avoid_ckd`
item; portion of each item 0.25–3 servings; and, for built meals and AI ideas only, no
`hypo_treatment` or `ingredient` item (the person's own saved and usual meals may contain apple juice
at breakfast or butter on toast).

**Meal score** (`score_meal`):

```
S = 10
  − Σ_k USAGE_WEIGHT_k × (total_k / max(room_k, NEGLIGIBLE_k))²          # K, P, Na, fluid with a target
  − 2 × h(|total_carbs − gap| / tol),  h(d) = d² for d ≤ 2, else 4 + 4 (d − 2)   # carbohydrate consistency, no plateau
  − protein term
  − 2 per "poor" item     # protein item: P/protein ≥ 16 or K/protein ≥ 20 or Na > 400 mg; other: renal red
  − 1 per phosphate_additive item
  − 1 per item already eaten or planned today; − 0.75 per item whose name family is already in today
  + 1 if any protein or mixed item;  + 0.5 if any veg_fruit item
  − (1 − scale)            for scaled saved meals
protein term, A = max(aim, 5), dev = (total_protein − A) / A:
  dialysis:     6 × max(0, −dev) + 0.5 × min(2, max(0, dev)²)
  not dialysis: 4 × max(0, (A_min − total_protein) / A_min) + 1.5 × min(2, dev²),  A_min = max(aim_min, 5)
```

**Choice**: the best familiar option (saved, usual, starter) wins if its score is at least the best
built score minus `FAMILIAR_MARGIN` (3.0): people keep meals they know. Ties: familiar before built,
then score, then lower potassium. `variant = n` (0–4) skips the first `n` built options so "Show me
another plan" is deterministic.

**Whole-day check and repair.** Run `daily_status()` on the projected day after the plan. If a
day-judged nutrient (potassium, sodium, fluid) becomes `over` that was not `over` before, reduce the
built item contributing most to it by ¼ serving (or remove it) and re-check, at most 6 times;
otherwise mark that slot `status: "partial"` with the reason. Phosphorus and protein are week-judged
and already budgeted through the week allowance, so they are not repaired. A slot with no feasible
option returns `status: "no_fit"`, the room numbers and the closest built meal at its best scale as
`closest`.

**Protein top-up.** If the projected day protein is below the minimum (on dialysis or not), increase
the protein item of the latest built main meal by ½ serving while `check_meal()` still passes (at most
2 steps, then the previous built meal). An earlier prototype weight set ended a hemodialysis day at
69.5 g against a 70 g minimum (TV-P4).

**Energy note.** When a calorie goal exists and the projected day is below 80 % of it, add
`energy_note` with up to 3 "energy-dense, low-mineral" foods (≥ 50 kcal per serving, K ≤ 50 mg,
P ≤ 30 mg, Na ≤ 50 mg, carbohydrate ≤ 5 g: oils, unsalted butter, cream cheese; `ingredient` foods are
allowed here because they are added to other food) and the diet-guide §6 advice to close the gap with
fat or measured starch, not more meat. This guards against the
restriction-only failure mode (protein-energy wasting).

Nothing is written. "Use this plan" sends the items to `POST /api/log/batch` (§4.10) with
`status: "planned"`; a saved-meal option may instead call the existing `POST /api/meals/{id}/apply`
with its scale.

### 4.8 (d) Insights (`insights.py`)

Rule-only in v0.3. Each insight: `{id, severity, nutrient, message, numbers, sources, handbook}`.
Severity order: `warning` > `attention` > `info` > `good`; then nutrient priority K, P, Na, fluid,
protein, carbohydrate, other. At most `INSIGHT_MAX` (6) returned; at most one `good`, always last.
Only **eaten** entries count; planned entries are reported as `planned_excluded: n`.

**End of day** (`GET /api/guidance/insights/day?date=`):

| id | Condition | Severity | Template (placeholders from §4.9) | Handbook |
|---|---|---|---|---|
| `day.<k>.over` (K, Na, fluid) | total > target | warning | "{Label} was {v} {u} today, {pct} % of your {t} {u} limit. Most came from {s1} ({p1} %) and {s2} ({p2} %)." | potassium / sodium / fluid |
| `day.<k>.caution` | `warn_fraction` ≤ fraction ≤ 1 | attention | "{Label} reached {pct} % of your limit ({v} of {t} {u})." | same |
| `day.phosphorus.over` | total > target | info | "Phosphorus was {v} mg today, above your {t} mg target. It is judged on the weekly average, so lighter days around it balance it out." | phosphorus |
| `day.carbs.meal_off` | diabetes ≠ none; a main meal's non-hypo carbs outside goal ± tol | info | "{Meal1} had {c1} g and {meal2} {c2} g of carbs, more than {tol} g above your usual {goal} g." (or "below") | carb-counting |
| `day.carbs.consistent` | ≥ 2 main meals logged, all within goal ± tol | good | "All {n} meals were within {tol} g of your {goal} g carb goal." | — |
| `day.hypo.logged` | ≥ 1 entry with `purpose = hypo` | info | "You logged {n} low-glucose treatment(s) ({c} g carbs, {k} mg potassium). They are not counted in the meal carb check." + "{Best} would treat the same low with {k2} mg potassium." when a hypo entry had > 50 mg K and the person has a hypo food ≤ 20 mg K | treating-a-low |
| `day.high_k.count` | ≥ 2 non-hypo entries > 200 mg K | attention if K ≥ caution, else info | "You had {n} high-potassium portions today: {names}." | potassium |
| `day.additives` | ≥ 1 `phosphate_additive` entry | info | "{n} food(s) today had phosphate additives: {names}. Additive phosphorus is almost fully absorbed." | phosphate-additives |
| `day.protein.low` | dialysis and total < min | attention | "Protein was {v} g, below your {min} g minimum. On dialysis your body needs more protein, not less." | protein |
| `day.protein.high` | not dialysis and total > max | info | "Protein was {v} g, above your {max} g maximum. Protein is judged on the weekly average." | protein |
| `day.unknown` | eaten entries with null K, P or Na | info | "{n} food(s) had no {nutrient} value, so today's total may be low." | label-reading |
| `day.interdialytic` | hemodialysis; interval K or fluid ≥ caution | attention (warning if over) | "Since dialysis on {weekday}, potassium adds up to {v} mg of {limit} mg for {days} days." | dialysis-days |
| `day.energy.low` | calorie goal; ≥ 3 meals logged; total < 70 % | info | "Calories were {v} kcal, {pct} % of your {t} kcal goal. Eating too little can cause muscle loss; fats such as olive oil add calories without potassium or phosphorus." | eating-enough |
| `day.all_good` | no warning or attention; ≥ 1 eaten entry | good | "{Tracked list} all stayed within your targets today." | — |

**Period** (`GET /api/guidance/insights/period?start=&end=`, default the 7 days ending yesterday; max
92 days; needs ≥ `MIN_LOGGED_DAYS` logged days, else one info insight "Log at least 3 days to see
weekly insights."):

| id | Condition | Severity | Template |
|---|---|---|---|
| `period.coverage` | logged < days | info | "You logged {n} of {d} days; averages use logged days only." |
| `period.<k>.average_over` (P, protein max, calories over) | average > target | attention | "{Label} averaged {avg} {u} a day on the {n} days you logged, above your {t} {u} target. It was above target on {d} of {n} days; the main sources were {s1} and {s2}." |
| `period.protein.average_low` | dialysis, average < min | attention | "Protein averaged {avg} g a day, below your {min} g minimum." |
| `period.<k>.days_over` (K, Na, fluid) | days over ≥ 2 | attention (warning if ≥ half of logged days) | "{Label} was over your limit on {d} of {n} days ({weekdays}). The main sources were {s1} and {s2}." + " Mostly at the weekend." when every over-day is Saturday or Sunday |
| `period.meal_share` | one meal slot ≥ 45 % of the period's K or Na | info | "{Meal} gave {p} % of your {nutrient} this week." |
| `period.carbs.consistency` | diabetes ≠ none | info / good | "{Meal} carbs were within {tol} g of your {goal} g goal on {x} of {n} days." + for the least consistent meal: "{Meal} varied more ({min}–{max} g)." |
| `period.hypo.count` | ≥ 3 hypo entries | info | "You logged {n} low-glucose treatments this week. Your diabetes team may want to know." |
| `period.additives` | additive foods on ≥ 2 days | info | "Phosphate-additive foods were eaten on {d} of {n} days: {name} ({x} times), …" |
| `period.change` | K or P average changed ≥ 15 % vs the previous period with ≥ 3 logged days | info / good | "Potassium averaged {p} % less than the week before." |
| `period.all_good` | no attention or warning | good | "Potassium stayed within your limit on all {n} days you logged." (per tracked nutrient, merged) |

**Source attribution** (`sources(entries, key)`): sum the nutrient per food (food id, falling back to
the snapshot name), share = sum / total; keep foods with share ≥ 10 %, at most 3, ordered by share ↓
then name; the text names the first 2. `short_name(name)`: the text before the first comma,
lower-cased ("Cheese, cheddar" → "cheese"), unless another listed source has the same head, then the
full name lower-cased. Custom food names are used as typed (untrusted text: rendered with
`textContent`, truncated to 60 characters).

### 4.9 Explanation strings (`messages.py`)

Rules for every string (F6): plain English; whole numbers (mg and mL integers with thousands separators,
grams to one decimal below 10 g, else whole); every qualitative word paired with a number and, where
there is one, the target; active voice; no "safe", "bad", "cheat", "failed", "unlimited", "don't
worry"; never insulin, units, ratios, doses, medicines or lab values (04 G2/G3); nutrient names spelled
out ("potassium", not "K") for screen readers. Portions: `{fraction} × {serving_desc}` with ¼ ½ ¾ glyphs
("1½ × ½ cup (79 g)"), plus grams when known.

| Code | Template | Example (fixture §6) |
|---|---|---|
| `fit_text` | "Fits: {carbs} g carbs · {K} mg potassium · {P} mg phosphorus · {Na} mg sodium" (tracked only; carbs first when diabetes ≠ none) | "Fits: 45 g carbs · 55 mg potassium · 70 mg phosphorus · 0 mg sodium" |
| `adds_missing_group` | "Adds the {group} this {meal} is missing" | "Adds the protein this dinner is missing" |
| `fills_carbs` | "Brings {meal} to {after} of your {goal} g carbs" | "Brings dinner to 45 of your 60 g carbs" |
| `low_potassium` | "Low in potassium ({K} mg)" | "Low in potassium (55 mg)" |
| `low_phosphorus` | "Low in phosphorus ({P} mg)" | |
| `protein_quality` | "{protein} g protein with little phosphorus ({ratio} mg per g)" | "13.5 g protein with little phosphorus (7 mg per g)" |
| `you_eat_often` | "You often have this" | |
| `free_food` | "Almost no carbs ({carbs} g)" | |
| `half_portion` | "A half portion fits; a full one would use more {nutrient} than is left for {meal}" | |
| `unknown` | "{Nutrient} is not listed for this food; check the label" | |
| `room_line` | "Left for {meal}: {K} mg potassium · {P} mg phosphorus · {Na} mg sodium · {gap} g carbs to reach {goal} g" | "Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g" |
| `swap_carbs` | "{name} ({portion}): about the same carbs ({c_new} g vs {c_old} g) and {dK} mg less potassium" (list each trigger) | "Rice, white, cooked (¾ × 1 cup): about the same carbs (34 g vs 37 g) and 884 mg less potassium" |
| `swap_protein` | "{name} ({portion}): about the same protein ({p_new} g vs {p_old} g), {dP} mg less phosphorus and {dNa} mg less sodium" | |
| `swap_hypo` | "For your next low: {name} ({portion}) gives {c} g carbs with {K} mg potassium" | "For your next low: Glucose tablets, 4 (1 × 4 tablets) gives 16 g carbs with 0 mg potassium" |
| `portion_option` | "{Fraction} portion: {carbs} g carbs and {K} mg potassium. The carbs change, so count the new amount." | "Half portion: 19 g carbs and 463 mg potassium. The carbs change, so count the new amount." |
| `plan_why_carbs` | "{carbs} g carbs, close to your {goal} g {meal} goal" | "59 g carbs, close to your 60 g dinner goal" |
| `plan_why_room` | "Uses {K} of the {room} mg potassium left for {meal}" | "Uses 179 of the 750 mg potassium left for dinner" |
| `no_fit` | "Nothing in your foods fits {meal} within today's {nutrient} room ({room} {u} left). {closest}" | |
| `disclaimer` | "Suggestions compare foods with the targets your care team set. They are not medical advice." | |

### 4.10 API (`app/guidance/api.py`, prefix `/api/guidance`)

All routes require a signed-in user (multi-user note), are sync `def` (pure Python plus SQLite), and
return `Cache-Control: no-store`. Validation errors follow the app's 400 shape. Every response carries
`rules_version`; `?explain=true` adds per-food score components and `why_not` codes (for contributors
and the docs page; never shown by default).

| Method & path | Query / body | Returns |
|---|---|---|
| `GET /api/guidance/next-meal` | `date`, `meal`, `limit` (1–20, default 11) | What fits now (§4.5) |
| `GET /api/guidance/swaps` | `date`, `meal`, and either `food_id` + (`servings` or `grams`) or `entry_id`; optional `purpose=hypo` | Swap ideas (§4.6) |
| `GET /api/guidance/hypo-options` | — | Hypo options (§4.6) |
| `POST /api/guidance/plan-day` | `{date, meals?: [Meal], use_saved_meals?: true, use_usual?: true, use_starters?: true, variant?: 0}` | Plan (§4.7); computes only, writes nothing |
| `GET /api/guidance/insights/day` | `date` | Day insights (§4.8) |
| `GET /api/guidance/insights/period` | `start`, `end` | Period insights |
| `GET /api/guidance/rules` | — | `RULES`, `RULES_VERSION`, `TOPIC_PAGES` |
| `POST /api/log/batch` (in `app/log.py`) | `{entries: [{date, meal, food_id, servings? \| grams?, status?, note?, client_id?}]}`, 1–40 items | `{entries: [Entry]}` 201; one transaction; each item validated exactly as `POST /api/log` |

Plan-day is a `POST` because it takes an options body; it still writes nothing.

**`GET /api/guidance/next-meal?date=2026-10-05&meal=dinner`** on the §6 fixture:

```json
{
  "status": "ok", "rules_version": "2026-10-05.1", "date": "2026-10-05", "meal": "dinner",
  "open_meals": ["dinner", "snack"],
  "room": {
    "potassium_mg":  {"room": 750, "cap": 750, "share": 800, "in_meal": 0, "remaining_today": 1200,
                      "allowance_today": 2500, "level": "ok", "basis": "day"},
    "phosphorus_mg": {"room": 167, "cap": 300, "share": 167, "in_meal": 0, "remaining_today": 250,
                      "allowance_today": 800, "level": "ok", "basis": "week_average"},
    "sodium_mg":     {"room": 600, "cap": 600, "share": 600, "in_meal": 0, "remaining_today": 900,
                      "allowance_today": 2000, "level": "ok", "basis": "day"},
    "fluid_ml": null,
    "carbs_g":   {"goal": 60, "in_meal": 0, "gap": 60, "tolerance": 10, "hypo_excluded_g": 0},
    "protein_g": {"aim": 9.3, "aim_min": 4.7}
  },
  "room_text": "Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g",
  "meal_has": {"protein": false, "starch": false, "veg_fruit": false},
  "foods": [
    {"food_id": 1, "name": "Rice, white, cooked", "group": "starch", "servings": 1,
     "serving_desc": "1 cup (158 g)", "grams": 158, "portion_text": "1 × 1 cup (158 g)",
     "nutrients": {"carbs_g": 45, "protein_g": 4, "potassium_mg": 55, "phosphorus_mg": 70, "sodium_mg": 0, "...": "all 12 keys"},
     "warnings": [{"nutrient": "carbs_g", "level": "high", "value": 45, "message": "High carbohydrate: 45 g in this portion (3 carb choices)"}],
     "renal_rating": "green", "score": 6.13,
     "fit_text": "Fits: 45 g carbs · 55 mg potassium · 70 mg phosphorus · 0 mg sodium",
     "reasons": [{"code": "adds_missing_group", "text": "Adds the starch this dinner is missing"},
                 {"code": "fills_carbs", "text": "Brings dinner to 45 of your 60 g carbs"}],
     "handbook": [{"slug": "carb-counting", "title": "Carb counting with renal swaps", "url": "/learn/eat/carb-counting/"}]},
    {"food_id": 4, "name": "Egg white, cooked", "group": "protein", "servings": 1, "score": 5.04, "...": "..."},
    {"food_id": 3, "name": "Chicken breast, roasted", "group": "protein", "servings": 0.5, "score": 4.80,
     "reasons": [{"code": "adds_missing_group", "text": "Adds the protein this dinner is missing"},
                 {"code": "protein_quality", "text": "13.5 g protein with little phosphorus (7 mg per g)"}], "...": "..."},
    {"food_id": 5, "name": "Green beans, boiled", "group": "veg_fruit", "servings": 1, "score": 4.59, "...": "..."},
    {"food_id": 7, "name": "Blueberries", "group": "veg_fruit", "servings": 1, "score": 4.34, "...": "..."},
    {"food_id": 11, "name": "Orange juice", "group": "extra", "servings": 0.5, "score": 0.66, "...": "..."}
  ],
  "saved_meals": [
    {"template_id": 1, "name": "Usual dinner", "source": "saved", "scale": 0.5, "score": -11.41,
     "totals": {"carbs_g": 25, "protein_g": 16, "potassium_mg": 183, "phosphorus_mg": 143, "sodium_mg": 33},
     "note": "Fits at half size (25 g carbs, 35 g under your 60 g goal): this week's phosphorus leaves 167 mg for dinner."}
  ],
  "tips": [],
  "notes": ["Suggestions compare foods with the targets your care team set. They are not medical advice."],
  "ai": {"available": false, "provider_label": null}
}
```

**`GET /api/guidance/swaps?date=2026-10-05&meal=dinner&food_id=2&servings=1`**:

```json
{
  "status": "ok", "rules_version": "2026-10-05.1", "mode": "normal",
  "food": {"food_id": 2, "name": "Potato, baked", "servings": 1,
           "nutrients": {"carbs_g": 37, "potassium_mg": 925, "phosphorus_mg": 120, "sodium_mg": 15, "...": "..."}},
  "triggers": [{"nutrient": "potassium_mg", "reasons": ["high_per_portion", "over_meal_room"], "value": 925, "room": 750}],
  "match": "carbs",
  "swaps": [
    {"food_id": 1, "name": "Rice, white, cooked", "servings": 0.75, "portion_text": "¾ × 1 cup (158 g)", "grams": 118.5,
     "same_category": false, "fits_meal": true, "renal_rating": "green", "score": 5.54,
     "nutrients": {"carbs_g": 33.8, "potassium_mg": 41, "phosphorus_mg": 53, "sodium_mg": 0, "...": "..."},
     "deltas": {"carbs_g": -3.3, "potassium_mg": -884, "phosphorus_mg": -68, "sodium_mg": -15},
     "text": "Rice, white, cooked (¾ × 1 cup): about the same carbs (34 g vs 37 g) and 884 mg less potassium"}
  ],
  "portion_option": {"servings": 0.5, "fits_meal": true,
                     "nutrients": {"carbs_g": 18.5, "potassium_mg": 463, "...": "..."},
                     "text": "Half portion: 19 g carbs and 463 mg potassium. The carbs change, so count the new amount."},
  "tips": [{"code": "leaching", "handbook": "potassium-leaching",
            "text": "Peeling, cutting small and boiling in plenty of water removes some of the potassium from potatoes."}],
  "widened": true
}
```

**`POST /api/guidance/plan-day`** `{"date": "2026-10-05"}` on the fixture (breakfast eaten, lunch
planned → slots dinner and snack):

```json
{
  "status": "ok", "rules_version": "2026-10-05.1", "date": "2026-10-05",
  "meals": [
    {"meal": "dinner", "status": "ok", "source": "built", "name": null, "score": 10.71,
     "items": [{"food_id": 4, "name": "Egg white, cooked", "servings": 1, "...": "..."},
               {"food_id": 1, "name": "Rice, white, cooked", "servings": 1, "...": "..."},
               {"food_id": 7, "name": "Blueberries", "servings": 1.25, "...": "..."}],
     "totals": {"carbs_g": 58.8, "protein_g": 8.1, "potassium_mg": 179, "phosphorus_mg": 88, "sodium_mg": 55},
     "why": ["59 g carbs, close to your 60 g dinner goal", "Uses 179 of the 750 mg potassium left for dinner"]},
    {"meal": "snack", "status": "ok", "source": "built", "score": 6.49,
     "items": [{"food_id": 1, "name": "Rice, white, cooked", "servings": 0.75, "...": "..."}],
     "totals": {"carbs_g": 33.8, "protein_g": 3, "potassium_mg": 41, "phosphorus_mg": 53, "sodium_mg": 0}}
  ],
  "day_after": {"projected_totals": {"potassium_mg": 1520, "phosphorus_mg": 690, "sodium_mg": 1155, "protein_g": 46.1, "...": "..."},
                "projected_status": {"potassium_mg": {"value": 1520, "target": 2500, "fraction": 0.61, "level": "ok"}, "...": "..."},
                "new_alerts": []},
  "energy_note": null,
  "apply": {"endpoint": "/api/log/batch",
            "entries": [{"date": "2026-10-05", "meal": "dinner", "food_id": 4, "servings": 1, "status": "planned"}, "..."]},
  "notes": ["Suggestions compare foods with the targets your care team set. They are not medical advice."]
}
```

(`energy_note` is null because it is computed only when the day's entries and the planned items carry
calorie values, and the fixture's synthetic foods have none.)

**`GET /api/guidance/insights/period?start=2026-09-28&end=2026-10-04`** (§6 TV-I2) returns, among
others:

```json
{"id": "period.phosphorus_mg.average_over", "severity": "attention", "nutrient": "phosphorus_mg",
 "message": "Phosphorus averaged 1,018 mg a day on the 7 days you logged, above your 1,000 mg target. It was above target on 4 of 7 days; the main sources were milk and cheese.",
 "numbers": {"average": 1018, "target": 1000, "days_above": 4, "logged_days": 7},
 "sources": [{"short_name": "milk", "value": 1624, "share_pct": 23},
             {"short_name": "cheese", "value": 1524, "share_pct": 21},
             {"short_name": "chicken breast", "value": 1372, "share_pct": 19}],
 "handbook": [{"slug": "phosphorus", "title": "Phosphorus and the weekly average", "url": "/learn/eat/phosphorus/"}]}
```

Pydantic models go in `app/models.py` (`GuidanceRoom`, `GuidanceFood`, `NextMealResponse`, `SwapResponse`,
`PlanDayRequest`, `PlanDayResponse`, `Insight`, `InsightsResponse`, `LogBatch`), with the app's numeric
bounds; ARCHITECTURE.md gains a "v0.3 guidance" section that copies these shapes.

### 4.11 Data model changes (ordered migrations in `app/db.py`)

| Change | Why |
|---|---|
| `log_entries.purpose TEXT NULL` (`'hypo'` or null). Set to `'hypo'` by default when the food is `hypo_treatment` (the entry sheet shows a pre-ticked "Used to treat a low" box the person can untick, and can tick for any food, e.g. orange juice). `POST /api/log`, `/quick`, `/batch` and `PUT` accept `purpose`; `Entry` returns it. | F5: hypo entries excluded from meal carbs, insights and swaps |
| `meal_templates.meal_hint TEXT NULL` (a `Meal`). `POST /api/meals/from-log` sets it to the source meal; the editor offers it. | F10 |
| Per-user `guidance_json TEXT NOT NULL DEFAULT '{}'` on the profile row (§4.14) | settings |
| Targets accept an optional `carbs_per_snack_g` (`TARGET_KEYS`) | F4 |
| `meta.foods_rev` integer, bumped on every food write and builtin import | vector cache |
| `foods.json` items: optional `role` override; new flag `ingredient` (set in `scripts/curated_foods.py` for flour, table salt, baking powder, black pepper, both vinegars, olive and canola oil, brown sugar, margarine, salted and unsalted butter); `tests/test_food_db.py` validates both | F9, F10 |
| `data/combos.json`: `{"version", "combos": [{"id", "name", "meal", "items": [{"fdc_id", "servings"}], "source": "diet-guide §6"}]}` | starter combos |
| Index `log_entries(user_id, date)` (if the multi-user note has not added it) | history queries |

Never drop or rename columns (ARCHITECTURE migration rule).

### 4.12 Performance design and budget

* **Budget:** p95 < 200 ms per guidance request on a Raspberry Pi 4 (4 GB, aarch64, the image's
  CPython) with 2,000 foods, 60 days of history and 100 saved meals. On the x86 CI runner that means
  **what-fits ≤ 25 ms, swaps ≤ 5 ms, plan-day (4 slots) ≤ 40 ms, insights ≤ 15 ms** at 2,000 foods.
* **How:** vector cache (§4.2); a pre-computed `static` term per food; the hot path uses plain floats
  and integer rounding, never `Decimal`, `food_warnings()` or message formatting (those run only for the
  ≤ 20 foods returned); plan-day pools of 200 per role and role-filtered passes; full warnings and
  texts built once for the returned items.
* **Tunables** (admin env): `GUIDANCE_POOL_PER_ROLE` (default 200; 120 cuts plan-day by ~30 % at
  2,000 foods), `GUIDANCE_BEAM_WIDTH` (16; 8 is ~15 % faster and up to 0.85 points worse than exhaustive).
* **Determinism:** scores rounded to 2 decimals; every sort has a full tie-break key ending in the
  food id; no randomness; `variant` is an explicit parameter.
* **Tests:** `test_perf_guidance.py` builds a 2,000-food synthetic DB (5 perturbed copies of
  `foods.json`) and asserts (a) evaluation counts (hardware-independent: what-fits ≤ 4 × eligible
  foods, plan-day ≤ 8,000 food evaluations and ≤ 1,500 meal evaluations; the prototype needed 6,653
  and 836 at 1,975 foods) and (b) a generous wall-clock bound (what-fits < 100 ms, plan-day < 150 ms)
  so a regression is caught without flaky CI.
* **`scripts/bench_guidance.py`:** prints p50/p95 for each endpoint function over 50 runs at 400 and
  2,000 foods; the release checklist records the Pi 4 and Pi 5 numbers in `docs/guidance.md`.

### 4.13 Optional AI enrichment (contract with note 04)

The AI never sees the database and never decides what fits. `ai_bridge.py` provides the only two
functions `app/ai/` may use:

* **`candidates_for_ai(ctx, meal, mode)`**: the rule result for that meal, trimmed for the prompt: up to
  40 foods (the what-fits ranking without the display limit, at least 6 per group when available),
  each as `{ref, food_id, name, group, portion (servings), per_portion {carbs, K, P, Na, fluid,
  protein}, renal_rating, fit_text, reasons[codes]}`; up to 5 fitting saved or usual meals; the room;
  the day's levels; allowed handbook slugs. For `swap` mode the rule swaps (≤ 15 that passed); for
  `plan` mode the ≤ 5 best options per slot. Custom/Open Food Facts names are marked untrusted (04 R8).
* **`validate_ai_items(ctx, meal, items)`**: for each AI idea `[{food_id, quarters}]`: `food_id` must be
  in the candidate set; `1 ≤ quarters ≤ 12`; then exactly `check_meal()` and `score_meal()` from §4.7
  on the current room. Failing ideas are dropped with the reason code (`would_exceed:<k>`,
  `too_many_carbs`, `not_a_candidate`, …), as 04 V3–V5 require.

Modes (04's `POST /api/ai/next-meal` gains `rerank` and `plan`; its `swap` mode now picks among the rule swaps instead of proposing new foods):

| Mode | AI returns | Server does | Shown as |
|---|---|---|---|
| `rerank` | `{"order": [ref, …] (≤ 12), "why": {ref: text}}` | keeps only refs from the candidate set; final order = AI order for mentioned refs, then rule order; numbers, warnings, `fit_text` always from the rules; `why` through 04 V6 | "AI order · {provider}" toggle over the same list |
| `ideas` | ≤ 3 combos of ≤ 5 `{food_id, quarters}` (04 R8 schema) | `validate_ai_items()`; drops failures | "AI ideas, checked against your targets" |
| `swap` | `{"pick": [ref, …] (≤ 3), "why": {...}}` over the rule swaps | as rerank | under the rule swaps |
| `plan` | one option index per slot + why | re-runs the whole-day check (§4.7) on the chosen options | "AI's pick" badge on rule options |

Fallback: any failure, timeout or zero surviving items → the rule result unchanged plus one note
("The AI ideas did not fit your targets today, so these are the app's own."). Insights and hypo options
are never sent to AI in v0.3. The AI result is cached per `(user, date, meal, rules hash)` for 10 minutes
so re-rendering does not re-call the provider.

### 4.14 Settings

User (private, in `guidance_json`; the settings note renders them):

| Key | Default | Range | Label |
|---|---|---|---|
| `enabled` | `true` | bool | "Show meal guidance" |
| `carb_tolerance_g` | 10 | 5–20 | "How close to my meal carb goal counts as on target" (help: "ask your diabetes team") |
| `hypo_dose_g` | 15 | 5–30 | "Carbs I take to treat a low (from my diabetes team)" |
| `exclude_food_ids` | `[]` | ≤ 500 ids | filled by "Not for me" on any suggestion |
| `exclude_categories` | `[]` | category names | "Never suggest" |
| `show_plan_builder` | `true` | bool | |
| `show_insights` | `true` | bool | |
| `ai_enrich` | `false` | bool | owned by note 04 (opt-in) |

Admin (env): `GUIDANCE_ENABLED` (default `true`), `GUIDANCE_POOL_PER_ROLE` (200), `GUIDANCE_BEAM_WIDTH` (16).
Vegetarian/pescatarian patterns need per-food diet tags and are deferred to v0.4.

### 4.15 Handbook topics (`topics.py`)

Proposed slugs (the handbook note owns the final list; one mapping table here keeps rules, insights and
AI citing the same pages): `potassium`, `potassium-leaching`, `phosphorus`, `phosphate-additives`,
`sodium`, `fluid`, `protein`, `eating-enough`, `carb-counting`, `treating-a-low`, `dialysis-days`,
`label-reading`, `eating-out`, `portions`. Each entry: `{slug, title, url: "/learn/<path>/"}` (paths: note 08 §4.10).
A test fails if a slug used in `TIPS` or an insight template has no entry.

### 4.16 UI (frontend owner; behaviour only)

* **Add view, meal chosen:** a "What fits now" panel above search: the `room_text` line, then groups;
  each row shows name, portion, `fit_text`, one reason, the renal dot and "Add"/"Plan". "Not for me" in
  a row menu. Saved/usual meals that fit as chips.
* **Entry sheet:** when the warnings block shows a K, P or Na warning (or room overflow), a "Lower-…
  ideas" disclosure fetches `/swaps`; for a hypo entry, the "For your next low" card instead.
* **Today:** "Plan the rest of my day" button → plan preview sheet → "Use this plan" (batch) or
  "Show another" (`variant + 1`). End-of-day insight cards (the client decides when: all main meals
  logged or after 19:00 local).
* **Trends:** period insights above the charts.
* Lists use `role="list"`; every number is in the text, not only in colour; `textContent` only.
* Offline: show the last fetched guidance with its time, or "Guidance needs a connection to your
  server".

---

## 5. Risks

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | Suggestions read as medical advice or as "safe" | Medium / High | Wording rules (§4.9), disclaimer on every response, targets attributed to the care team, no insulin or medicine language (04 G2/G3), "fits your targets" never "safe" |
| R2 | Restriction-focused ranking drives under-eating (protein-energy wasting) | Medium / High | Protein minimum shortfall terms, energy note, `day.energy.low` and protein insights (§4.7, §4.8) |
| R3 | Hypoglycaemia handled wrongly (suggested as food, warned against, under-dosed) | Low / Critical | Hypo foods never meal suggestions; `purpose = hypo` exempts entries; swaps only up to ≥ dose; no AI path (04 G7); tests TV-S4, TV-I1 |
| R4 | Unknown or wrong nutrient data (custom, Open Food Facts, SR Legacy approximations, additive under-counting) | High / Medium | Unknown never treated as 0; unknown blocked when the day's level is not ok; additive penalty; `day.unknown` insight; label-reading tips |
| R5 | A swap changes carbohydrate and the person's insulin arithmetic | Medium / High | Carb matching ± max(5 g, 10 %); explicit "count the new amount" on portion options; ADA 5.27 fat/protein caveat in the handbook page, not in app text |
| R6 | Weights become opaque or drift | Medium / Medium | One `RULES` table with `RULES_VERSION`, `?explain=true`, golden vectors updated in the same PR, `docs/guidance.md` generated from the table |
| R7 | Too slow on a Pi 4 | Medium / Medium | Caches and pools (§4.12); measured budget gate; tunables; F8 estimate must be confirmed on hardware |
| R8 | Monotonous or annoying suggestions | Medium / Low | Variety and family penalties, "Not for me", `variant`, familiar-meal margin |
| R9 | Cross-user leakage in a multi-user instance | Low / High | Every query scoped by `user_id`; vector cache keyed by user; AI context single-user (04 G14); API tests with two users |
| R10 | Wrong targets amplified by guidance | Medium / High | Guidance shows which targets it used and when they were saved; `no_targets` status; suggested targets remain "discuss with your care team" |
| R11 | Per-meal caps and weights are rules of thumb, not graded evidence | Certain / Low | Stated as such in F1 and `docs/guidance.md`; caps only shape suggestions, never create alerts |
| R12 | Dialysis-day eating patterns not modelled beyond the interdialytic allowance | Medium / Low | Allowance from the interval (§4.4); dialysis-days handbook page; revisit in v0.4 |
| R13 | Regulatory classification of patient-facing guidance | Low / High | Stays a logging aid doing arithmetic on care-team targets; no diagnosis or dosing; see 04 F12 |

---

## 6. Test vectors

### 6.1 Fixture (`tests/guidance/fixtures.py`)

Targets: K 2,500 mg, P 1,000 mg, Na 2,000 mg, protein `{min 42, max 56}`, carbs 236 g,
`carbs_per_meal_g` 60, fluid null, calories 2,100, calcium 1,000; `warn_fraction` 0.8; no dialysis;
type 1; tolerance 10 g. Date 2026-10-05 (Monday).

| id | Name | Category | Serving | Carbs g | Protein g | K mg | P mg | Na mg | Fluid mL | Flags |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Rice, white, cooked | Grains & Breads | 1 cup (158 g) | 45 | 4 | 55 | 70 | 0 | 0 | |
| 2 | Potato, baked | Vegetables | 1 medium (173 g) | 37 | 4 | 925 | 120 | 15 | 0 | |
| 3 | Chicken breast, roasted | Meat, Poultry & Eggs | 3 oz (85 g) | 0 | 27 | 220 | 195 | 65 | 0 | |
| 4 | Egg white, cooked | Meat, Poultry & Eggs | 1 large (33 g) | 0 | 3.6 | 55 | 5 | 55 | 0 | |
| 5 | Green beans, boiled | Vegetables | ½ cup (63 g) | 5 | 1 | 90 | 20 | 0 | 0 | |
| 6 | Banana | Fruits | 1 medium (118 g) | 27 | 1 | 420 | 25 | 0 | 0 | |
| 7 | Blueberries | Fruits | ½ cup (74 g) | 11 | 0.5 | 55 | 10 | 0 | 0 | low_potassium_fruit |
| 8 | Cheese, processed | Dairy & Alternatives | 1 slice (28 g) | 1 | 5 | 35 | 180 | 470 | 0 | phosphate_additive, processed |
| 9 | Star fruit | Fruits | 1 medium (91 g) | 6 | 0 | 120 | 11 | 0 | 0 | avoid_ckd |
| 10 | Glucose tablets, 4 | Diabetes supplies | 4 tablets (16 g) | 16 | 0 | 0 | 0 | 0 | 0 | hypo_treatment, high_gi |
| 11 | Orange juice | Beverages | ½ cup (124 g) | 13 | 1 | 250 | 20 | 0 | 110 | high_gi, counts_as_fluid |
| 12 | Apple juice | Beverages | ½ cup (124 g) | 14 | 0 | 125 | 9 | 0 | 110 | hypo_treatment, high_gi, counts_as_fluid |
| 13 | Breakfast block (test) | Prepared & Fast Food | 1 serving | 55 | 15 | 600 | 250 | 500 | 0 | |
| 14 | Lunch block (test) | Prepared & Fast Food | 1 serving | 60 | 20 | 700 | 300 | 600 | 0 | |

Day: food 13 eaten at breakfast; food 14 **planned** at lunch. History: on 2026-10-04, 10-03, 10-01 and
09-29 one eaten entry each with 1,100 mg phosphorus and 49 g protein (4 logged days of the previous
6). Saved meal 1 "Usual dinner" (`meal_hint` dinner): food 3 × 1, food 1 × 1, food 5 × 1.

### 6.2 Budget

| id | Input | Expected |
|---|---|---|
| TV-B1 | phosphorus allowance | `n = 4`, `S = 4,400`, raw `1,000 × 5 − 4,400 = 600` → clamp → **800** |
| TV-B2 | same with 0 logged days / 6 logged days of 900 mg | **1,000** / raw 1,600 → **1,200** |
| TV-B3 | `open_slots(dinner)`, `open_slots(snack)` | `[dinner, snack]` (lunch is planned, so not open); `[snack, dinner]` |
| TV-B4 | room for dinner | K: remaining 1,200, share 800, cap 750 → **750**; Na: remaining 900, share 600, cap 600 → **600**; P: remaining 800 − 550 = 250, share **166.7**, cap 300 → **166.7**; carbs gap **60**, tol 10; protein aim (49 − 35) × ⅔ = **9.33**, aim_min (42 − 35) × ⅔ = **4.67**; all levels `ok` |
| TV-B5 | room for snack | K min(375, 400) = **375**; Na **300**; P **83.3**; carbs goal **30**; aim **4.67** |
| TV-B6 (hand-computed) | hemodialysis Mon/Wed/Fri, date Sunday 2026-10-04, K target 2,500, eaten Fri + Sat 5,800 mg | `D = 3`, limit 7,500, `days_left = 1` → allowance **1,700** (< 2,500) |
| TV-B7 | an entry with `purpose = hypo` (food 10, 16 g) added to dinner | dinner `in_meal` carbs **0**, `hypo_excluded_g` **16**; K/P/Na/fluid totals still include it |

### 6.3 What fits now (dinner)

| id | Expected |
|---|---|
| TV-F1 | Not eligible: 9 (`avoid_ckd`), 10 (`Diabetes supplies`, hypo), 12 (hypo) |
| TV-F2 | Hard filters: food 2 at 1 serving → `would_exceed:potassium_mg` (925 > 750 + 50); at ½ passes (462.5) |
| TV-F3 | Scores (2 decimals): rice ×1 **6.13**; egg white ×1 **5.04**; chicken ×½ **4.80**; green beans ×1 **4.59**; blueberries ×1 **4.34**; orange juice ×½ **0.66**; banana best ×½ −3.05, potato ×½ −3.53, processed cheese ×½ −6.64, blocks 13/14 ×½ −0.58 / −0.03 (not shown: below `MIN_SHOW_SCORE`). Rice, chicken and green beans include +0.5 for being in saved meal 1. |
| TV-F4 | Returned order: 1, 4, 3, 5, 7, 11 |
| TV-F5 | Hand check of rice: `3 (green) + 0.5 (saved) − 3(55/750)² − 2(70/166.7)² + 2·45/60 + 1.5 (missing starch) = 3 + 0.5 − 0.016 − 0.353 + 1.5 + 1.5 = 6.13` |
| TV-F6 | Hand check of chicken ×½ (13.5 g protein, 110 K, 97.5 P, 32.5 Na): base `1 + 1 (P/protein 7.2) + 0.5 (K/protein 8.1) = 2.5`; + 0.5 saved; − 0.25 portion; usage − 0.065 − 0.684 − 0.006; + 1.5 missing protein; + 1.5 × min(13.5, 9.33)/9.33 = + 1.5; − ((13.5 − 9.33)/9.33)² = − 0.199 → **4.80** |
| TV-F7 | Saved meal 1: scale 1 fails (P 285 > 196.7), ¾ fails (P 213.75), **½ passes**: K 182.5, P 142.5, Na 32.5, carbs 25, protein 16; meal score **−11.41** (35 g short of the carb goal: `h(3.5) = 10`, × 2 = 20); still listed, with its note |
| TV-F8 | Same request with `exclude_food_ids = [1]`: rice absent and the starch group empty, because the only other starch (potato ×½, −3.53) is below `MIN_SHOW_SCORE` |

### 6.4 Swaps

| id | Request | Expected |
|---|---|---|
| TV-S1 | banana × 1, dinner | triggers K (420 > 200, high); match carbs (27 g); **blueberries × 2.5** (27.5 g, 137.5 mg K), same category, fits, score **4.47** |
| TV-S2 | potato × 1, dinner | trigger K; match carbs (37 g); **rice × ¾** (33.75 g, 41.25 mg K), other category (same role) → `widened: true`, score **5.54** (includes +0.5 habit from the saved meal); `portion_option` ½ (18.5 g, 462.5 mg K); leaching tip |
| TV-S3 | processed cheese × 1 | triggers P (additive and 180 > 150) and Na (470 > 400); match protein (5 g); **no swaps** in the fixture; portion option none (additive remains); additives tip |
| TV-S4 (hand-computed) | orange juice × 1 with `purpose=hypo` | hypo mode; target `max(13, 15) = 15` g, rounded up; **glucose tablets × 1** (16 g, 0 mg K) first, apple juice × 1.25 (17.5 g, 156 mg K) second (apple juice ×1 at 14 g is below the dose and is rounded up); text `swap_hypo` |
| TV-S5 | orange juice × 1, normal | trigger K (250 > 200); **apple juice × 1** (14 g, 125 mg K; hypo foods allowed for beverages), score **3.9** |
| TV-S6 | rice × 1, apple juice × 1 | no trigger → `reason: "no_warning"` |
| TV-S7 | real DB (`data/foods.json`), profile `suggest_targets(70, "4")`, day: breakfast eaten 2 × "Bread, white", 1 × "Egg, scrambled", 1 × "Orange juice"; lunch eaten 1 × "Chicken breast, roasted, skinless", 1 × "Pasta, cooked", 1 × "Green beans, boiled"; request "Potato, baked, with skin" × 1 at dinner | prototype top 5: couscous ×1, pasta ×1, grits ×1, white rice ×¾, cream of wheat ×1½; all `Grains & Breads`, 33–40 g carbs, ≤ 91 mg K; **no** `ingredient` food (flour was first before the flag existed) |
| TV-S8 | real DB, same day, "Cheese, American, processed" × 1 | match protein; top 2 are natural cheeses (mozzarella part skim ×¾, cheddar ×¾); none `phosphate_additive` |

### 6.5 Plan

| id | Request | Expected |
|---|---|---|
| TV-P1 | fixture, default slots | slots `[dinner, snack]`; dinner = egg white ×1 + rice ×1 + blueberries ×1¼ (58.75 g carbs, 8.1 g protein, 178.75 K, 87.5 P, 55 Na), score **10.71**; snack = rice ×¾ (33.75 g, 41.25 K, 52.5 P), score **6.49** (the fixture's food list is tiny, hence rice twice) |
| TV-P2 | fixture with saved meal 1, profile hemodialysis, K 2,500, protein `{70, 84}`, fluid 1,500, empty day | breakfast chicken ×½ + rice ×1¼ + green beans ×½ (19.0 g protein); lunch chicken ×½ + rice ×1¼ + blueberries ×½ (18.8 g); dinner = **saved "Usual dinner" at full size** (familiar-margin rule: 3.94 vs the best built option; 32 g protein, 285 mg P against a 300 mg room); snack rice ×¾; day protein 72.8 g (≥ 70); no K, Na or fluid `over` |
| TV-P3 | real DB, `suggest_targets(70, "4")`, empty day, no saved meals | every main meal within 60 ± 10 g carbs (prototype: 60.0, 61.0, 60.8; snack 27.4); day protein between 42 and 56 g (prototype: 46.8 g; K 613, P 462, Na 110 mg); prototype plan: egg white ×½ + pasta ×1½ + green beans ×½; chicken breast ×½ + white rice ×1¼ + blueberries ×½; hard-boiled egg ×½ + grits ×1½ + raspberries ×½; couscous ×¾; no `ingredient` food |
| TV-P4 | real DB, `suggest_targets(70, "5", "hemodialysis")` (protein 70–84, K 2,500, fluid 1,500), empty day, no saved meals | day protein ≥ 70 g (final prototype: 73.9 g without needing the top-up; an earlier weight set ended at 69.5 g, which is why the top-up step exists); no new `over` alert; test also forces the top-up by setting the minimum to 80 g and asserts a protein item grew by ½ serving |
| TV-P5 | saved meal with `meal_hint` dinner and an empty snack slot | the saved meal is never placed in the snack slot |
| TV-P6 | `variant` 0 vs 1 | different built dinner; same input → byte-identical JSON on repeat |
| TV-P7 | a slot with K room 0 (`level over`) | only foods with ≤ 50 mg K per portion appear; if none: `status: "no_fit"` with `closest` |

### 6.6 Insights

| id | Input | Expected message |
|---|---|---|
| TV-I1 | Day: OJ 1 cup (500 K, 26 g) + white bread ×2 (74 K, 28.6 g) at breakfast; banana (420), rice (55, 45 g), chicken (220) at lunch; baked potato (925, 37 g), chicken (220), green beans (90, 5 g), rice (55, 45 g) at dinner; glucose tablets (0 K, 16 g) and OJ ½ cup (250 K, 13 g) both `purpose = hypo` at snack. K target 2,500. | `day.potassium_mg.over`: "Potassium was 2,809 mg today, 112 % of your 2,500 mg limit. Most came from potato (33 %) and orange juice (27 %)." · `day.carbs.meal_off`: "Lunch had 72 g and dinner 87 g of carbs, more than 10 g above your usual 60 g." (breakfast 54.6 g is within) · `day.hypo.logged`: "You logged 2 low-glucose treatments (29 g carbs, 250 mg potassium). They are not counted in the meal carb check. Glucose tablets, 4 would treat the same low with 0 mg potassium." · `day.high_k.count`: "You had 5 high-potassium portions today: orange juice, banana, chicken breast (2) and potato." |
| TV-I2 | 7 days 2026-09-28 … 10-04, P target 1,000; daily base foods (rice 68, chicken breast 196, white bread 56, scrambled egg 101, green beans 18, apple 20, pasta 72, milk 1 % 232 = 763 mg) plus cheddar 381 mg and cola 66 mg on Mon, Wed, Fri, Sat | `period.phosphorus_mg.average_over`: "Phosphorus averaged 1,018 mg a day on the 7 days you logged, above your 1,000 mg target. It was above target on 4 of 7 days; the main sources were milk and cheese." · sources milk 1,624 (23 %), cheese 1,524 (21 %), chicken breast 1,372 (19 %) · `period.additives` (cola flagged): "Phosphate-additive foods were eaten on 4 of 7 days: cola (4 times)." |
| TV-I3 | 2 logged days in the period | single info insight "Log at least 3 days to see weekly insights." |
| TV-I4 | `short_name` with "Cheese, cheddar" and "Cheese, Swiss" both listed | "cheese, cheddar" and "cheese, swiss" (full names because the heads clash) |
| TV-I5 | No eaten entries, only planned | no insights except `planned_excluded: n` note |

### 6.7 Properties (hypothesis or table-driven)

* Every returned what-fits food, swap and plan item satisfies `check_meal()` against the room used.
* No `avoid_ckd`, `ingredient` or (outside hypo mode) `hypo_treatment` food is ever returned.
* Adding any returned what-fits food never creates a new `over` in `daily_status()` for K, Na or fluid.
* `renal_level()` equals the rating from `food_warnings()` restricted to K/P/Na/avoid for all 395
  builtin foods × portions {¼ … 3}.
* Output is identical across two runs and across `PYTHONHASHSEED` values.
* Beam versus exhaustive oracle: on 40 seeded random days (stage 3b/4/5 and hemodialysis, 0–3 random
  breakfast items), the built lunch and dinner score at most 0.5 below an exhaustive search over the
  same top-6 candidates per role and the same portion set (prototype: max 0.43, median 0).
* Every message passes the wording lint (no digits-free "high"/"low" without a number, no banned words
  from §4.9 and 04 V6).

---

## 7. Implementation checklist

**Data (food-db owner)**

- [ ] Add flag `ingredient` to `nutrients.FLAGS`, set it in `scripts/curated_foods.py` for the 12 foods
      in §4.11, regenerate `data/foods.json` (`--version 2026-10-05.3` or the day's next), extend
      `tests/test_food_db.py`.
- [ ] Optional `role` override in curated foods (start with coleslaw → `veg_fruit`); validate values.
- [ ] `data/combos.json` with the four diet-guide §6 sample-day meals (map each food to its `fdc_id`;
      never guess ids), plus a test that every referenced id exists.
- [ ] Replace the dead UMich citation [47] in `docs/diet-guide.md` and `docs/research/ckd-diet.md` with
      AKF Kidney Kitchen [1] and Satellite Healthcare [3].

**Engine (backend owner), pure modules first**

- [ ] `app/guidance/rules.py` with `RULES`, `RULES_VERSION`, `role_of()`, eligibility helpers.
- [ ] `budget.py`: `open_slots`, `week_allowance`, `interdialytic_allowance` (reuse
      `periods.interdialytic_interval`), `meal_room`; tests TV-B1…B7.
- [ ] `vectors.py`: `FoodVec` (slots), `build_vectors`, `renal_level`; property test against
      `food_warnings()`.
- [ ] `score.py`: `score_food`, `score_meal`, `check_meal`; tests TV-F3, TV-F5, TV-F6, TV-F7.
- [ ] `fits.py`, `swaps.py` (incl. hypo mode and `hypo_options`), `planner.py` (beam search, usual
      combos, starters, repair, energy note), `insights.py`, `messages.py`, `topics.py`; tests §6.3–6.7.
- [ ] `ai_bridge.py`: `candidates_for_ai`, `validate_ai_items` (shares `check_meal`); tests with
      hand-written "AI" payloads including a non-candidate id, quarters 0 and 13, and an idea that
      exceeds potassium.

**Storage and API (backend owner)**

- [ ] Migrations: `log_entries.purpose`, `meal_templates.meal_hint`, `guidance_json`,
      `carbs_per_snack_g` in `TARGET_KEYS`, `meta.foods_rev` bumps in `app/foods.py`; migration tests
      from a v0.2 database.
- [ ] `context.py` with `VectorCache`; `api.py` routes of §4.10; models in `app/models.py`;
      `POST /api/log/batch` (atomic, ≤ 40, `client_id` honoured as in note 02).
- [ ] `purpose` accepted and returned by the log endpoints; `from-log` sets `meal_hint`.
- [ ] API tests: two users never see each other's foods, meals or history in guidance; `no_targets`
      status; validation 400s; `?explain=true`.
- [ ] `test_perf_guidance.py` (§4.12) and `scripts/bench_guidance.py`.

**UI (frontend owner)**

- [ ] What-fits panel, swap disclosure, hypo card, plan preview with "Use this plan" and "Show
      another", insight cards on Today and Trends, "Not for me", guidance settings (§4.14),
      offline message. Playwright at 375 × 812 and 1280 × 800, light and dark.
- [ ] Entry sheet: "Used to treat a low" checkbox (pre-ticked for hypo foods).

**AI (with note 04)**

- [ ] Add `rerank`, `swap` and `plan` modes to `POST /api/ai/next-meal`; build context only from
      `candidates_for_ai`; validate only with `validate_ai_items`; golden-set cases for each mode.

**Docs**

- [ ] `docs/guidance.md`: what each feature does, the formulas and the `RULES` table (generated from
      `GET /api/guidance/rules` by a small script so it cannot drift), the evidence level of each rule
      (F1–F6), how to propose a weight change.
- [ ] ARCHITECTURE.md "v0.3 guidance" section (endpoints, shapes, data-model changes); README feature
      list; handbook topic slugs agreed with the handbook note.
- [ ] Release gate: run `scripts/bench_guidance.py` on a Raspberry Pi 4 and a Pi 5, record p95 in
      `docs/guidance.md`; if a Pi 4 p95 exceeds 200 ms, lower `GUIDANCE_POOL_PER_ROLE` and document it.

---

## 8. Open questions for the owner

1. Is ±10 g the right default carbohydrate tolerance, or does the diabetes team use a different
   number (it is a per-person setting either way)?
2. Should hypo-treatment entries default to `purpose = hypo` for every `hypo_treatment` food (current
   proposal), or only when logged from a dedicated "Treat a low" button?
3. Starter combos: are the diet-guide sample-day meals acceptable as defaults, or should the instance
   ship with none?

---

## 9. How to re-verify

* **Per-meal rules of thumb:** reload [1], [2], [3] and [5]; if a page changes its numbers, update F1
  and consider whether `MEAL_CAP_FRACTION` still reproduces them.
* **ADA Standards of Care:** each January check Section 5 (Recs 5.27/5.28 numbering and text) and
  Section 6 (Rec 6.15) and update F4/F5 and the diet guide.
* **KDOQI/KDIGO:** on any update to protein ranges or potassium/phosphorus statements, re-run
  `tests/test_nutrients.py` and the TV-P3/P4 plans.
* **Performance:** rerun `scripts/bench_guidance.py` on Pi 4 and Pi 5 after each CPython minor upgrade
  in the image and after any change to `score.py` or `planner.py`.
* **Solver landscape (only if §3.1 C is reconsidered):** `curl -s https://pypi.org/pypi/<pkg>/json` for
  PuLP, ortools, scipy and highspy.
* **Dead links:** `curl -sI` every URL in §10 yearly.

---

## 10. Sources

1. American Kidney Fund, Kidney Kitchen. **Where do I find meal plans for low potassium?** Ask a
   dietitian (Carolyn Feibig, MS, RD, LD, CCTD). https://kitchen.kidneyfund.org/?p=86324 — "600-700mg of
   potassium per meal and 100-200mg per snack for a daily goal of 1800 – 2200mg"; avoid multiple
   high-potassium foods in a day. Accessed 2026-10-05.
2. American Kidney Fund, Kidney Kitchen. **Can I use artificial sweeteners?** Ask a dietitian (Maura
   Chesney, RD, LDN). https://kitchen.kidneyfund.org/?p=86181 — stage 5 on dialysis "under 2,100mg per day
   or <700mg per meal, less if you are going to have a snack". Accessed 2026-10-05.
3. Satellite Healthcare. **Food labels** (Living with dialysis · Eating smart).
   https://www.satellitehealthcare.com/living-with-dialysis/eating-smart/food-labels — sodium "less than
   600 mg per meal and less than 200 mg for a snack"; potassium < 250 mg per serving, 2,000–3,000 mg/day.
   Accessed 2026-10-05.
4. UW Medicine Patient Education. **Healthy Eating: Eat well and eat smart** (KEEP class 08; published
   2004/2011/2015, clinician review 05/2015).
   https://healthonline.washington.edu/sites/default/files/record_pdfs/KEEP-08-Healthy-Eating.pdf — high
   (250–500 mg) choose 1 a day, medium 2, low 3; sodium ≤ 2,000 mg/day.
5. American Kidney Fund. **Keep your potassium in check: Low vs. high-potassium foods** (Beyond Bananas,
   July 2026). https://kitchen.kidneyfund.org/wp-content/uploads/2026/08/3.-BB_low_high_potassium_0726.pdf
6. DaVita (S. Colman, RDN, CDCES). **How to determine if a food is high or low potassium.**
   https://www.davita.com/diet-nutrition/kidney-diet-tips/how-to-determine-if-a-food-is-high-or-low-potassium/
7. Kalantar-Zadeh K, Gutekunst L, Mehrotra R, et al. **Understanding sources of dietary phosphorus in the
   treatment of patients with chronic kidney disease.** Clin J Am Soc Nephrol 2010;5(3):519–530.
   https://pubmed.ncbi.nlm.nih.gov/20093346/
8. Noori N, et al. **Organic and inorganic dietary phosphorus and its
   management in chronic kidney disease.** Iran J Kidney Dis 2010;4(2):89–100.
   https://pubmed.ncbi.nlm.nih.gov/20404416/ — phosphorus-to-protein ratio < 10 mg/g; egg white < 2 mg/g.
9. Noori N, Kalantar-Zadeh K, Kovesdy CP, et al. **Association of dietary phosphorus intake and
   phosphorus to protein ratio with mortality in hemodialysis patients.** Clin J Am Soc Nephrol
   2010;5(4):683–692. https://pmc.ncbi.nlm.nih.gov/articles/PMC2849686 — HR 1.13 / 1.00 / 1.80 / 1.99
   across < 12, 12–< 14, 14–< 16, ≥ 16 mg/g.
10. National Kidney Foundation. **If you need to limit protein** (patient handout).
    https://www.kidney.org/sites/default/files/02-10-0413_ABB_Protein.pdf — "Each 7 grams of protein =
    1 oz of meat, poultry or fish".
11. Mamerow MM, Mettler JA, English KL, et al. **Dietary protein distribution positively influences 24-h
    muscle protein synthesis in healthy adults.** J Nutr 2014;144(6):876–880. doi:10.3945/jn.113.185280.
    https://pmc.ncbi.nlm.nih.gov/articles/PMC4018950
12. American Diabetes Association. **5. Facilitating Positive Health Behaviors and Well-being to Improve
    Health Outcomes: Standards of Care in Diabetes—2026.** Diabetes Care 2026;49(Suppl 1):S89–S131.
    doi:10.2337/dc26-S005. https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188 — Recs 5.27, 5.28; high-fat
    and high-protein mixed meals. Section 6 (Rec 6.15, hypoglycaemia treatment):
    https://pmc.ncbi.nlm.nih.gov/articles/PMC12690178 (cited via `docs/diet-guide.md` [9]).
13. Smart CE, Ross K, Edge JA, et al. **Children and adolescents on intensive insulin therapy maintain
    postprandial glycaemic control without precise carbohydrate counting.** Diabet Med 2009;26(3):279–285.
    And Smart CE, King BR, McElduff P, Collins CE. **In children using intensive insulin therapy, a 20-g
    variation in carbohydrate amount significantly impacts on postprandial glycaemia.** Diabet Med
    2012;29:21–24.
14. Diabetes Care for Children & Young People (DiabetesontheNet). **Dietary management** (review
    summarising Smart 2009/2012). https://diabetesonthenet.com/diabetes-care-children-young-people/dietary-management/
15. UW Medicine Patient Education. **Food Choice Lists for carbohydrate counting** (clinician review
    10/2021). https://healthonline.washington.edu/sites/default/files/record_pdfs/Food-Choice-Lists_10-2021_a11y.pdf
    — 1 choice = 15 g carbohydrate; a "free" food has "no more than 5 grams carbohydrate and 20 calories
    per serving".
16. Centers for Disease Control and Prevention. **CDC Clear Communication Index: User Guide** (May 2013),
    items 15–16. https://stacks.cdc.gov/view/cdc/21459
17. Digital.gov (GSA). **Federal Plain Language Guidelines.**
    https://digital.gov/resources/federal-plain-language-guidelines
18. Raspberry Pi Ltd. **Introducing: Raspberry Pi 5!** (2023-09-28). https://www.raspberrypi.com/news/introducing-raspberry-pi-5/
    — Cortex-A76 at 2.4 GHz, "over twice as fast as its predecessor".
19. PyPI JSON API, checked 2026-10-05: https://pypi.org/project/PuLP/ (4.0.0, MIT),
    https://pypi.org/project/ortools/ (9.15.6755, Apache-2.0), https://pypi.org/project/scipy/ (1.18.1,
    BSD-3-Clause), https://pypi.org/project/highspy/ (1.15.1, MIT), https://pypi.org/project/numpy/ (2.5.3).
20. Repository sources used throughout: `docs/diet-guide.md` (§2 periods, §4 carb counting and hypo
    treatment, §6 sample day, sources [1]–[55] including KDOQI 2020, KDIGO 2024, ADA 2026 Sections 6 and
    11), `docs/research/ckd-diet.md`, `docs/research/food-lists.md`, `ARCHITECTURE.md`, and sibling notes
    [`01`](01-rootless-and-security.md)–[`04`](04-optional-ai.md).
