# 16 · Recipes that fit your targets (suggest, create and change a recipe; the app does the numbers)

| | |
|---|---|
| Status | Accepted, 2026-10-27. The owner's decisions are recorded under §15. Phases 0 to 2 (the fit without AI) are built first, then phase 3. The schema step is **21**: 0.6.0 used 20. |
| Date researched | 2026-10-27, against `main` at `56869a4` (v0.5.0) |
| Scope | A recipe is a saved meal with a count of servings, optional cooking steps and an optional source link. (1) **Fit to my targets**: the app's own engine checks one serving against the room in a meal, or against what is left today. If it does not fit, the engine lowers amounts, swaps a food or suggests a smaller serving, and lists every change in plain words. It needs no AI. (2) **AI recipes**, optional: the AI proposes a new recipe, or a reworked one, from foods the rules chose. The app works out every number, runs the same fit and says what it changed. (3) The data, API, screens, tests and phases for both. |
| Out of scope | Importing a recipe from a web page, the handbook's recipes as starters, and Ask or MCP tools that call the engine (all three are "Later", §13); a week of meals or meal prep; cooking losses, leaching and any other effect of cooking on the numbers; allergen checks; recipe photos; scaling a recipe to a new count of servings other than by editing "Makes"; insulin, medicines and glucose in any form. |
| Builds on | `app/meals.py` and the meal models, `app/mcp/tools.py` (`save_recipe`), `app/ai/chat_save.py`, `app/guidance/` (`budget.py`, `score.py` `check_meal`, `swaps.py`, `fits.py`, `ai_bridge.py`, `rules.py`), `app/ai/` (`features.py`, `guard.py`, `schemas.py`, `prompts.py`, `routing.py`, `chat.py`), `docs/ai.md` (G1 to G17), `docs/guidance.md`, note 04 (§9 A2), note 06, note 09, note 14 (the reuse map), the ROADMAP item "Recipe pages in `check_meal`". |
| Re-verify | (a) A live run on the owner's local model: does an 8-to-12 food answer with steps stay schema-valid, how many recipes survive the rules, how many steps the checks drop (§12). (b) The 12 handbook recipes, entered as saved recipes from their gram weights, give the page's per-serving numbers; where they differ, the cause is the herbs and spices that have no food row. (c) On the owner's own data: how many recipes saved by Ask or MCP carry a note that matches the backfill pattern of §5.1. (d) The fit sheet and the editor at phone width on an iPhone. |

---

## 1. Context

The owner asked (2026-10-27): "Recipes: suggest recipes, and create or change a recipe to fit my targets. The AI proposes. The app works out the nutrients from its own food database, checks them against my targets, adjusts portions or swaps foods, and says what it changed. AI-made numbers are never shown as fact."

Two jobs are in that sentence, and they should not depend on each other.

* **Fit.** Take a recipe the person already has and make it fit one meal. The rules, the room in a meal and the swap engine already exist. Nothing here needs a model.
* **Propose.** Let a model suggest a recipe or rework one. The model picks food ids from a list the rules made and amounts in quarter servings, as it does for meal ideas. The app then does the same fit.

Today a person can save a meal, and Ask or an MCP token can save a "recipe" (§2). Neither can say whether one serving fits.

## 2. What exists

| # | Fact | Where |
|---|---|---|
| R1 | A saved meal is a row of `meal_templates`: `name`, `note`, `items_json` (`[{food_id, servings}]`), `meal_hint`, two timestamps. Routes: `GET/POST /api/meals`, `GET/PUT/DELETE /api/meals/{id}`, `POST /api/meals/from-log`, `POST /api/meals/{id}/apply` (with a `scale`). All need `current_user`, every query has `user_id`, and someone else's meal is 404. A saved meal has no count of servings and no steps. | `app/meals.py`, `m002_planning.py`, `m005_guidance_log.py` |
| R2 | The only "recipe" today is the `save_recipe` tool that Ask and an MCP token (scope `assistant:log`) can call. It saves a meal whose items are the amounts for the **whole pot**. The count of servings and the source link live only in the note, as the text "Makes 4 servings. Source: https://…". | `app/mcp/tools.py` (`save_recipe`, `recipe_note`), `app/ai/chat_save.py`, ARCHITECTURE "save_recipe" |
| R3 | A saved meal's `totals` add the ingredients and count an unknown value as 0. Today's screen and the MCP tools carry a count of what is not listed (`unknown`, `not_listed_by`); `MealTemplate` has none. | `app/meals.py` (`row_to_template`), `app/nutrients.py` (`add_totals`, `count_unknown`) |
| R4 | "What fits now" offers a saved meal at 1, ¾ or ½ of **all** its items (`best_scale`, `SAVED_MEAL_SCALES`), and `check_meal` refuses any item outside ¼ to 3 servings. A saved 4-serving recipe is judged as one meal of pot size and usually fails. On the fixture of `tests/guidance/fixtures.py` (note 06 §6.1), chicken, rice and green beans fit one dinner at 365 mg potassium against 750 mg of room, but the same pot for 4 is refused at 1,460 mg (`would_exceed:potassium_mg`), and a 0.04-serving item is refused as `portion_out_of_range`. | `app/guidance/fits.py`, `score.py`, `context.py` (`SavedMeal`) |
| R5 | `check_meal` is the one gate. Kinds: `built`, `ai`, `saved`, `usual`, `starter`. Every kind: totals within the room plus the negligible amount; unknown values only while the day's level is ok; carbohydrate at most the gap plus the tolerance; no `avoid_ckd` food; each item ¼ to 3 servings. Every kind but `built` also stays within what is left of the day's own target (potassium, sodium, fluid). `built` and `ai` also refuse a low treatment, a food flagged `ingredient` (flour, oil, salt), alcohol and a "high" portion of a nutrient that is not ok today. `ai` also refuses more than 1 serving of a "high" food. | `app/guidance/score.py` |
| R6 | The swap engine lowers every trigger nutrient by at least 25 %, keeps carbohydrate within ±max(5 g, 10 %) (or protein within ±max(3 g, 15 %)), stays in the same category or role, and offers no low treatment (unless the food it replaces is a drink), no `ingredient`, no alcohol, no supply, no "Not for me" food and no food of a never-suggest group. It ranks with the person's preferences. Its fallback is a smaller portion (¾, then ½). | `app/guidance/swaps.py` |
| R7 | Meal ideas: the rules make a list of up to 40 candidate foods; the schema gives `food_id` as an `enum` of their ids and `quarters` 1 to 12; at most 5 foods and 3 ideas; `validate_ai_items` runs `check_meal` kind `ai`; the title and the sentence a person reads are written by the app from a `theme` and `reason_codes`; a claim that is not true of the recomputed numbers is removed and counted (G4, G5, G10, A2). | `app/guidance/ai_bridge.py`, `app/ai/guard.py`, `app/ai/schemas.py` |
| R8 | Ask is the only feature where the model writes free text for the person. Its answer is checked in code (G15): a low or an emergency is answered by the app first; no insulin or medicine talk (`dose_reason`); no number with a nutrient or energy unit that a tool did not return; no links; at most 1,200 characters. | `app/ai/chat.py` |
| R9 | Routing: five features, each `local`, `cloud`, `off` or `any` (default `local`); `photos`, `meal_ideas` and `describe` also `local_then_cloud`. Meal ideas and describe share the consent "Meal data" (purpose `text`). Lab reports stay on the local AI. The browser never talks to a provider. | `app/ai/routing.py`, `docs/ai.md` |
| R10 | `docs/ai.md` lists "ingredient lists" as never sent. It means the printed ingredient text of a food (packaging text is an injection source, note 04 §9.2). Saved meals sent to meal ideas already carry their food ids and names. | `docs/ai.md`, `app/ai/prompts.py` (`next_meal_context`) |
| R11 | The handbook has 12 recipes. Their ingredients are `fdc_id` and grams in `handbook/data/recipes.yml`, and `scripts/build_handbook.py` works out the per-serving numbers from the app's food list and checks them (sodium at most 600 mg; "lower potassium" at most 600 mg). A few seasonings that the list lacks keep their per-100 g values in that file, and each page says how much potassium they add. The built-in list has 395 foods, 13 flagged `ingredient`, and no thyme, parsley, oregano, basil or cinnamon. The leaching page gives sourced estimates; no number in the app uses them. | `handbook/data/recipes.yml`, `scripts/build_handbook.py`, `data/foods.json`, `handbook/docs/eat/potassium-leaching.md` |
| R12 | The demo and the preview run the guidance engine as JavaScript twins checked by `tests/data/guidance_vectors.json`. Every `/api/ai/*` route answers 404 there, so the demo is the "AI off" case. | `app/static/js/engine/guidance/`, `js/mock/ai.js` |
| R13 | Export and import carry saved meals, and so do the demo's twins. A new field must be added in all of them. | `app/account.py`, `app/data_import.py`, `js/mock/export.js`, `js/mock/import.js` |

## 3. Where the code agrees with the choices and where it does not

| Owner's choice | What the code shows | What this note does |
|---|---|---|
| 1. The core needs no AI. | Agrees. The room, `check_meal` and the swap engine are pure, and the demo has no AI at all (R12). | Phases 0 to 2 ship the whole fit with no AI. |
| 2. A recipe is a saved meal plus `servings_made` and steps. | Agrees on reuse. But `servings_made` is **not a column** (R2), unknown values are counted as 0 in a saved meal's totals (R3), and a saved recipe is misjudged by "What fits now" (R4). | One schema step for three columns; per-serving figures with a count of what is not listed; "What fits now" divides by the servings (§5). |
| 3. The AI proposal has the shape of meal ideas. | Agrees, with two changes. The candidate list for ideas ranks foods at their best **full** portion, which drops soy sauce, oil or a spice that is fine in a share. And `validate_ai_items` allows 5 foods and ¼ to 3 servings, and `check_meal` kind `ai` refuses the `ingredient` flag, so no recipe could pass. | A candidate list made for recipes, and `validate_ai_recipe` (§8). |
| 3. Steps are the one free text. | Disagrees with G10 and A2 (no free text from the meal features) and with the ROADMAP, which lets model-written text return "only behind the golden-set gates". The checks of G15 can be reused. | Steps ship with a new guardrail G18 and an admin switch that starts **off** until the owner's live run (§8.7). |
| 3. The title is a template or a short checked string. | A free title is the easiest place to hide a claim ("a kidney-safe stew"). | Template (§8.6). |
| 4. The engine uses `check_meal` with the rules of meal ideas. | Needs a **new kind, `recipe`**. It judges one serving's share of each ingredient, allows the `ingredient` flag, and drops the ¼-to-3 rule for a share (a spoon of oil in 4 servings is 0.04 servings). Unknown values come back as a set, so the result must carry them (§9.2). | Kind `recipe`. |
| 4. Order: lower amounts, then swap, then a smaller serving. | Agrees with the swap engine's own order (swap, then a smaller portion). Two changes: step 1 never lowers a protein ingredient, because that silently cuts protein; and the swap engine cannot be called on a share as it is (its bounds and its "one serving" match). | Protein is swapped or the serving is made smaller instead; the swap core gets recipe bounds (§9.3). |
| 5. Nothing is saved without Save; a fitted copy is new. | Agrees. "Replace" is a `PUT`, which overwrites. | Replace asks first, shows carbohydrate before and after, and offers Undo (§10). |
| 6. Routing and consent. | Agrees. | Add `local_then_cloud` to the new feature; reword the "ingredient lists" row (R10); name recipes in the consent wording (§8.1). `docs/ai.md` already has a heading "Recipes" for provider setups: the new section is "Recipes that fit". |
| 7. Later: web import, Ask and MCP tools. | Agrees. The handbook's 12 vetted recipes are a safer first source than the web. | Handbook link first (§13). |

## 4. Options

| Option | What it is | Verdict |
|---|---|---|
| A. Fit only | The engine and the screens. No model. | Phases 0 to 2. Useful alone, and the base of B. |
| **B. Fit, then AI proposals checked by the same fit** | A adds a model that proposes food ids and quarters; the app recomputes, fits and labels. | **Recommended.** Phase 3. |
| C. The model writes a whole recipe as text and the app reads the names and amounts back | Like "describe a meal". | No. The model would choose units and names, the app would guess the match, and every guess is a number the person did not check. |
| D. The model calls the fit as a tool in the Ask loop | Ask and MCP get a `fit_recipe` tool. | Later (§13). It needs Ask's consent and loop, and it is not needed for the one-shot "suggest". |
| E. Import from a web page or from the handbook | schema.org `Recipe`, or the handbook's own recipes through a link. | Later, on the same engine (§13). |

## 5. Design: the recipe

### 5.1 What is stored

Schema step 21 (`app/migrations/m021_recipes.py`, append-only) adds three nullable columns to `meal_templates`:

| Column | Meaning |
|---|---|
| `servings_made` REAL | How many servings the items make. Greater than 0 and at most 100 (as `RecipeArgs.servings`). `NULL` is a plain saved meal: the whole meal is one serving, as today. |
| `steps_json` TEXT | A list of strings. A person may type up to 20 steps of up to 500 characters. An AI step is at most 200 characters, at most 8 steps (G18). Shown with `textContent`. |
| `source_url` TEXT | An `http` or `https` link kept as text and never fetched (the rules of `check_source_url`, at most 900 characters). |

* **Backfill.** For a row whose note is exactly `Makes N serving(s).`, with or without ` Source: <link>` (the sentence `recipe_note` writes), the step sets `servings_made` and `source_url`. It leaves the note alone, and the screen hides a note equal to that sentence. Any other note leaves the columns `NULL`. The step is idempotent and tested on both kinds of row.
* **Routes.** `MealTemplateCreate` gets the three fields, optional. A `PUT` that leaves one out keeps the stored value, as it does for `meal_hint`; `null` clears it. `MealTemplate` returns them.
* **Ask and MCP.** `save_recipe` writes the columns and stops writing the sentence. A note the person types is kept.
* **No numbers are stored.** The row holds food ids and amounts. Every figure is worked out on read from the food rows, so a corrected food corrects its recipes, as it does for saved meals.

### 5.2 Per-serving numbers and unknown values

Words used below. The **pot amount** of a food is its servings in the whole recipe. A **share** is the pot amount divided by `servings_made`: what one serving holds.

* `per_serving[key]` is the sum over the ingredients of the food row times the pot amount, divided by `servings_made`.
* `unknown[key]` is how many ingredients do not list that nutrient. A nutrient that **no** ingredient lists is `null`, never 0. If some list it, the figure is a lower bound, and the screen says "at least 410 mg (1 food not listed)". The helpers `KH.ui.atLeast` and `unknownOf` already do this for Today.
* `totals` (the whole pot) stays as it is for older clients.
* Two lines are fixed text under every recipe: "Numbers are for the foods as they are listed. Cooking, soaking or draining can change what ends up on the plate, and the app does not count that." And: "Seasonings that are not in your food list are not counted." Leaching is never a number the app uses (R11).

### 5.3 What changes for what exists

* **What fits now** reads a recipe per serving: the items of a saved meal with `servings_made` are divided by it before `best_scale`. This also repairs the case in R4 for recipes saved today.
* **Add to plan** uses the ordinary `POST /api/meals/{id}/apply` with `scale = serving fraction ÷ servings_made`. It logs one entry per ingredient, as saved meals do, and marks nothing as a low treatment.
* **Export and import** carry the three fields. The import test and the demo twins change with them (R13).

## 6. Data flow

```
Fit (no AI)
  person ─ POST /api/guidance/fit-recipe {meal_id | draft, target} ─▶ server
     loads the person's context (profile, targets, log, preferences, foods) as What fits now does
     room ← meal_room(...)  or  day_room(...)
     fit_recipe(recipe, room, context)          pure; nothing is written
  ◀─ {status, before, after, fitted, changes, still_over}
  person presses Save ─ POST /api/meals {fitted body} ─▶ the ordinary route; every rule runs again

AI recipe (optional)
  person ─ POST /api/ai/recipes {mode, meal, dish, makes}  (?dry_run=true shows the request) ─▶ server
     gates: AI on, the person opted in, route "recipes", consent "Meal data", daily quota
     candidates ← recipe_candidates(context)    the rules; low treatments and "Not for me" never
     request ← prompt + data block + schema (food_id is an enum of the candidate ids)
     ─▶ provider (local, or the cloud one if routed) ─▶ answer
     check the answer: schema; ids are candidates; bounds; person's exclusions
     recompute: shares and per-serving figures from the food rows
     fit_recipe(...)                            the same engine; changes are listed
     title from a template; claims checked; steps checked (G18)
  ◀─ cards; each carries the exact body for POST /api/meals
  person presses Save ─ POST /api/meals ─▶ the ordinary route
```

The browser talks only to the app. A recipe is written only by the person's tap, through the route that saved meals use.

## 7. API

Every route needs `current_user`, reads and writes only that person's rows, and answers 404 for a recipe or food that is not theirs (or does not exist). No new secret is read or written. A new field is an additive change, so `API_VERSION` does not move. The OpenAPI document is regenerated (`python scripts/gen_openapi.py`).

| Route | Change | Notes |
|---|---|---|
| `GET/POST /api/meals`, `GET/PUT/DELETE /api/meals/{id}` | New optional fields `servings_made`, `steps`, `source_url` in; the same, `per_serving` and `unknown` out. | Foods that are not the person's: 404, as today. |
| `POST /api/guidance/fit-recipe` | **New.** Reads, never writes. | Lives in the guidance router, so it has the same answers `{"status":"no_targets"}` and `{"status":"disabled"}`, and the same `rules_version`. |
| `POST /api/ai/recipes` | **New.** `?dry_run=true` returns the exact request. | Same gates as `POST /api/ai/next-meal`. |
| `GET /api/ai/status`, `GET /api/me/ai` | `routes.recipes`, `features.recipes`. | |
| `PUT /api/admin/ai-routing`, settings | `ai.route.recipes` (`AI_ROUTE_RECIPES`), `ai.recipe_steps` (admin, default off). | Listed in `app/settings_registry.py`, `app/ai/routing.py`, the settings twin `engine/settings.js` and `tests/data/settings_vectors.json`. |
| `GET /api/meta` | New capability `ai_recipes`, read from `features.recipes`. | The demo's `js/mock/meta.js` says false. |

**`POST /api/guidance/fit-recipe`**

```json
{
  "meal_id": 12,
  "target": {"kind": "meal", "meal": "dinner", "date": "2026-10-27"}
}
```

* Either `meal_id`, or a draft: `"items": [{"food_id": 7, "servings": 2}], "servings_made": 4`. Not both. A draft names foods the person can see (404 otherwise).
* `target.kind` is `meal` or `day`. For `meal`, `meal` and `date` are optional: the default is the next open meal today (`open_slots`). For `day`, one serving is checked against what is left today.
* Answer:

```json
{
  "status": "fits | fits_after_changes | fits_smaller_serving | does_not_fit",
  "rules_version": "2026-10-27.1",
  "target": {"kind": "meal", "meal": "dinner", "date": "2026-10-27"},
  "servings_made": 4,
  "before": {"per_serving": {"potassium_mg": 640, "carbs_g": 52.0, "...": null},
             "unknown": {"phosphorus_mg": 1},
             "checks": [{"nutrient": "potassium_mg", "used": 640, "room": 410, "ok": false}]},
  "after":  {"per_serving": {"potassium_mg": 405}, "unknown": {"phosphorus_mg": 1}, "checks": [{"nutrient": "potassium_mg", "used": 405, "room": 410, "ok": true}]},
  "fitted": {"items": [{"food_id": 7, "name": "Potato, boiled", "servings": 2, "serving_desc": "1 cup (156 g)", "portion_text": "2 × 1 cup (156 g)"}],
             "serving_fraction": 1, "log_scale": 0.25},
  "changes": [{"code": "lowered", "food_id": 7, "from": 4, "to": 2, "because": "potassium_mg", "text": "Used 2 × 1 cup (156 g) of potatoes instead of 4 × 1 cup (156 g), …"}],
  "still_over": [],
  "notes": ["Numbers are for the foods as they are listed. …"]
}
```

* `fitted` is `null` and `closest` (same shape as `fitted`, with its own `after`) is given when the status is `does_not_fit`. The screen shows `closest` and `still_over`, with no Save button on it.
* `log_scale` is the `scale` for `POST /api/meals/{id}/apply` once the fitted recipe is saved.
* `changes[].text` comes from maintainer templates in `app/guidance/messages.py` and is tested against `BANNED_PATTERN`, like every guidance text.

## 8. The AI call

### 8.1 Gates and routing

* New feature key **`recipes`**, route setting `ai.route.recipes` (`AI_ROUTE_RECIPES`): `local`, `cloud`, `off`, `any` or `local_then_cloud`. **Default `local`.** With no local AI the feature is off until an admin pins it. `off` answers `503` with the reason `feature_off`, as the others do.
* Consent purpose `text`, shown as "Meal data". Consent is kept per person, provider and purpose, so a person who agreed to Meal data on a host is not asked again for recipes on it. Reworking a recipe sends its foods and amounts, so the consent wording gains one line about recipes and `POLICY_VERSION` (`app/ai/presets.py`) moves: everyone is asked once more, which is the least-trust choice (decision 8). A feature that moves to another host asks again (R9).
* `local_then_cloud` is allowed. A long answer with steps is the kind of reply a small model gets wrong, and the cloud AI is asked only when the local answer fails the schema or the rules, and only for a person who agreed to that host. The dry run shows both requests, as for meal ideas.
* One request is one call, counted against the daily limit. A cloud retry counts too.
* The AI activity list keeps the request and the raw answer for the retention period, as for the other meal features. It holds what was sent and nothing more; the steps in it are masked in the display like any model text.
* The call goes through the same SSRF-checked transport as every other AI call, and the browser never talks to a provider. The lab-report rule is not touched: nothing in this feature reads a lab value, a name or a date of birth.

### 8.2 What is sent, byte for byte

The data block is the one meal ideas send (`next_meal_context`), with the recipe parts below. "What will be sent?" shows it before anything leaves.

| Sent | Detail |
|---|---|
| `person` | CKD stage, dialysis, diabetes type (a stage or type not chosen yet goes as `null`); the person's preferences text (at most 200 characters, only if written); the names of the foods and groups they marked Like, Less often and Not for me (at most 10 of each, 60 characters a name); an age band and sex only with "Share my age band and sex". |
| `targets` | The care team's targets; without diabetes, no per-meal carbohydrate goal. |
| `today`, `week_avg`, `meal`, `meals_left`, `meal_budget` | Today's eaten and planned totals and status levels; 7-day averages of phosphorus and protein; the meal; the room for it. |
| `candidates` | Up to 48 foods (§8.3): `id`, `ref`, `name` (cleaned, at most 80 characters), `source`, `category`, `group`, `serving`, per-serving numbers for **one serving**, `rating`, `warnings`, `flags`, `often`, `liked`. |
| `recipe_request` | `mode` (`suggest` or `change`); for `suggest`, `dish` (from the fixed list) and `makes` (1, 2, 4 or 6). |
| `recipe` (mode `change` only) | `{ref: "r1", makes, ingredients: [{id, quarters}], findings: [{nutrient, per_serving, room, level}]}`. The ingredients' foods are also in `candidates`, so their names go that way, as the foods of a saved meal do for meal ideas. The findings are the app's own `before.checks`. |
| **Never** | The person's name, user name, e-mail, account number, date of birth, birth month or exact age, weight or height, any lab value, any date, any log note, **the recipe's name, note, steps and source link**, other people's data, and anything the app learned from the log. |

### 8.3 The candidate list for recipes (`recipe_candidates`)

* Eligible: not hidden, not `avoid_ckd`, not a low treatment, no alcohol, no diabetes supply, not "Not for me", not in a never-suggest group. Unlike meal ideas, a food flagged `ingredient` **is** eligible: a recipe needs oil and flour. A short maintainers' list of foods the AI never adds (table salt; any salt substitute, which is a potassium salt) is kept in code and grown from the golden set.
* Ranked like "What fits now", but at **¼, ½ and 1 serving** instead of the best full portion (`RECIPE_PORTIONS`), so a food that is fine in a share is not dropped. At least 6 per group and at least 4 flagged `ingredient`, 48 in all (`AI_RECIPE_FOODS_MAX`). The prompt-budget trimming that meal ideas use applies; `context_too_small` is the same 503.
* Mode `change`: the recipe's own foods are added, so the model can keep them.
* The built-in list lacks many herbs (R11). Whatever the person has added or imported is in their list and so can be offered.

### 8.4 The answer schema

The wire schema follows `app/ai/schemas.py`: the strict subset of keywords, a root object, every property required, `food_id` an `enum` built per request. It is a hint; every answer is checked again with `extra="forbid"` models.

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["status", "refusal", "recipes"],
  "properties": {
    "status":  {"type": "string", "enum": ["ok", "refused"]},
    "refusal": {"type": "string", "enum": ["none", "outside_scope", "no_fit"]},
    "recipes": {
      "type": "array", "minItems": 0, "maxItems": 2,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["dish", "theme", "ingredients", "steps", "reason_codes"],
        "properties": {
          "dish": {"type": "string", "enum": ["soup", "stew", "bowl", "stir_fry", "bake", "salad", "sandwich",
                                              "pasta", "rice_dish", "egg_dish", "porridge", "snack", "drink"]},
          "theme": {"type": "string", "enum": ["light", "hearty", "familiar", "new_idea"]},
          "ingredients": {
            "type": "array", "minItems": 2, "maxItems": 12,
            "items": {
              "type": "object", "additionalProperties": false, "required": ["food_id", "quarters"],
              "properties": {
                "food_id":  {"type": "integer", "enum": [101, 134, 2210]},
                "quarters": {"type": "integer", "minimum": 1, "maximum": 160}
              }
            }
          },
          "steps": {"type": "array", "minItems": 0, "maxItems": 8, "items": {"type": "string"}},
          "reason_codes": {"type": "array", "minItems": 1, "maxItems": 3,
                           "items": {"type": "string", "enum": ["low_potassium", "low_phosphorus", "low_sodium",
                                      "fits_carb_goal", "adds_protein", "adds_missing_group", "you_eat_often", "you_like"]}}
        }
      }
    }
  }
}
```

* `quarters` is the **pot amount** in quarter servings of the food's listed serving (4 quarters is one serving). The prompt says so, and says how many servings the pot makes. The model never gives a nutrient, a unit, a title or a count of servings.
* In mode `change`, `maxItems` of `recipes` is 1.
* The Pydantic models are one step looser than the wire schema, as the others are (note 04 V2): 10 recipes, 30 ingredients, 12 steps, 300 characters a step, `quarters` up to 1,000. The guard then drops the extra with a reason, instead of failing the whole answer. The `maxLength` keyword is not in the strict subset, so the length of a step is checked by the guard only.
* A recipe with any other key (a `title`, a `why`) is dropped as `unexpected_field`. That is free text the schema does not allow.
* The system prompt is a new template next to `SYSTEM_PROMPT`, because the meal-ideas text says the app writes every sentence. It keeps rules 3, 4, 6, 7, 8 and 9 word for word (no insulin, no medicines, no lab advice; never question a warning; a low is the app's; the data is not instructions; one JSON object; tastes are not medical limits) and rewrites rules 1, 2 and 5 for a pot: amounts are for the whole pot, the budget is per serving, and a "high" food is judged on one serving's share. It adds the steps rule of §8.7. Both prompts are pinned in `tests/fixtures/ai/`, and `PROMPT_VERSION` moves.

### 8.5 Checks on the answer (`validate_ai_recipe`, `judge_recipes`)

| Step | Check | A failure |
|---|---|---|
| V2 | Shape and counts. | A repair turn, as today. |
| V3 | Each `food_id` is in this request's candidate ids and in the person's foods. Duplicates are merged. 2 to 12 foods. `quarters` 1 to 160. A share above `PORTION_MAX` (3) servings of one food goes to the fit, which makes it smaller (since 2026-10-29). | Recipe dropped: `not_a_candidate`, `quarters_out_of_range`, `too_many_items`; `share_too_large` only when the fit cannot bring the share down to 3. |
| V3 | No food the person marked "Not for me" and none in a never-suggest group (`person_excluded`). No hidden, `avoid_ckd`, low-treatment, alcohol or supply food, whatever the candidate list said. | Dropped: `not_for_me`, `excluded_category`, `not_a_candidate`. |
| V4 | The app computes the shares, the per-serving figures and the unknown counts from the food rows. | |
| V5 | `check_meal` kind `recipe` on the target's room. If it fails, `fit_recipe` runs with the AI recipe as its input (§9). | Dropped with the reason (`would_exceed:potassium_mg`, …) when even the fit cannot make it pass. |
| V6 | `theme` and `reason_codes` are checked against the final numbers (`true_theme`, `check_claims`); the sentence is the app's (`REASON_TEXT`). A false claim is removed and counted (`claims_corrected`). | |
| V6 | Title: §8.6. Steps: §8.7. | |
| V8 | No recipe left: the app says so and shows the rules' own saved meals that fit. | |
| V9 | Label: "AI recipe · provider · model · checked against your targets · not medical advice". | |

In mode `change` the card lists what differs from the person's recipe: foods added, foods removed and amounts changed. The app works this out by comparing the two ingredient lists, and adds its own fit changes after them. The model gives no account of what it changed, because that would be free text about the numbers.

When the fit **swaps** an ingredient of an AI recipe, the AI's steps are discarded. They would describe a food that is no longer there. The card says "Steps removed because the app changed the foods." Lowering an amount or a smaller serving leaves the steps, because steps carry no amounts.

### 8.6 The title

A **template**, not a model string. The title is the short names of the one or two foods with the most grams (pot amount times `serving_g`) that are not flagged `ingredient`, from the food rows (`short_names` of `fits.py`), plus the word for the `dish`: "Chicken and rice soup", "Pork and cabbage stir-fry". The word list is fixed in `messages.py`. Why: a free title can carry a claim ("kidney-safe"), a name or a link, and each of those would need its own check; a template carries none. The cost is a plainer name, and the person can rename it in the editor (their own words, their own text). A fitted copy is named "<name> (fitted)", and a recipe the AI reworked "<name> (reworked)"; the person's name for the recipe is added by the app and is not sent.

### 8.7 The steps (G18)

Steps are the one free text. They are off unless the admin switch `ai.recipe_steps` is on, and it starts **off**: the ROADMAP lets model-written text return only behind the golden-set gates, so the owner turns it on after a live run (`steps_unsafe_shown` must be 0, §12). With the switch off, `steps` has `maxItems: 0` in the schema, the prompt does not ask for steps, and the card shows the foods and the numbers only.

Each step passes these checks in order, in code (`app/ai/recipe_steps.py`, reusing `guard.fold`, `guard.blocked`, `chat.dose_reason` and the link patterns of `chat.py`). A step that fails is **removed and counted**, with its reason code (`steps_dropped`), and the rest stay. The first 8 survivors are kept.

| # | Check | Reason code | Passes | Fails |
|---|---|---|---|---|
| 1 | Clean: NFKC, control and format characters out, white space collapsed, at most 200 characters, not empty. | `empty`, `too_long` | "Chop the onion and the carrot small." | A step of 240 characters. A step that is only "…". |
| 2 | No link, e-mail address, markup or code characters (`< > { } [ ] \ ` \|`). | `link`, `markup` | "Serve with the rice." | "See https://example.com/recipe", "Use the `pan`" |
| 3 | No insulin or medicine talk: `dose_reason` (insulin, doses, medicine and binder names, skipping or changing a medicine) and the names blocklist, after folding look-alike letters and invisible characters. | `dose:*`, `blocklist:*` | "Simmer for 20 minutes." | "Have your insulin ready", "Take your binder with this", insulin with a zero-width space inside it (U+200B), "dose" with a Cyrillic "о" |
| 4 | **No mention of a low** at all (`_LOW_CONTEXT` alone, stricter than Ask, where it must also restrict something). A recipe step has no reason to speak about one, and the app's own cards cover it. | `low` | "Let it cool for 5 minutes." | "If you feel shaky, treat the low first.", "Skip this if your sugar is low." |
| 5 | **No number with a nutrient or energy unit** (`chat.quantities`: mg, g, ml, l, kcal, calories, kJ, %). Amounts belong to the ingredient list, which the app wrote. No amounts by spoon or cup either. Times, temperatures and counts are fine. | `quantity`, `amount` | "Bake at 180 C (350 F) for 25 minutes.", "Crack 2 eggs into a bowl." | "Add 200 g of flour", "Stir in 30 mg …", "Add 2 cups of broth", "Add ½ tsp pepper" |
| 6 | **No nutrient word and no claim that cooking changes a nutrient**: potassium, phosph*, sodium, mineral(s), electrolyte(s), nutrient(s), vitamin(s), calorie(s), carb(s), carbohydrate(s), protein, fibre/fiber, glycaemic; and the claim words leach*, detox*, flush*, purif*, "kidney-friendly", "renal-friendly", "good for your kidneys", "healthy", "healthier", "harmful", "toxic". | `nutrient_word`, `claim` | "Soak the dried beans overnight." (a method, no claim) | "Boil twice to remove potassium", "This lowers the sodium by half", "Double-boiling makes it kidney-friendly" |
| 7 | No allergen or diet claim the app cannot check: allerg*, gluten-free, dairy-free, nut-free, vegan, vegetarian, halal, kosher. | `diet_claim` | "Fry the egg." | "This is gluten-free." |
| 8 | **Nothing added that the list does not show.** A salt substitute or potassium salt (never allowed), or one of the heavy kitchen items on a short maintainers' list (soy sauce, stock cube, bouillon, seasoning mix, baking powder, …), unless a food of the ingredient list has that word in its name. | `unlisted_food` | "Season with pepper." | "Stir in a salt substitute", "Add a stock cube" when no food in the list is one |

The lists live in code and grow from the golden set. A false positive costs one step, which is counted and visible. A false negative is the case to avoid, so the lists lean to dropping.

What the checks cannot do:

* They cannot tell whether a time or a temperature is right. A step can say "cook the chicken for 2 minutes". Times and temperatures are allowed (steps without them are of little use), so every card with steps says: "Steps written by AI. The app checked them for medicine talk and nutrient claims, not for cooking times or food safety. Check them before you cook."
* They cannot see a food that is named in a way no list has (check 8 is a short list, not a food dictionary). A later check can compare food words with the food list (§13).
* A person's own steps are the person's text and go through none of this. They are stored and shown with `textContent`, and never sent to an AI.

### 8.8 What the person reads on an AI recipe card

The title (template), the label (G13), the theme, the sentence the app wrote, the foods with the pot amounts, "Makes N servings", the per-serving figures from the food rows with the unknown counts, the fit line and its changes, the steps with their own label, the two fixed lines of §5.2, and the buttons of §10. The text of the model appears nowhere else.

## 9. The fitting engine (`app/guidance/recipes.py`, pure)

### 9.1 Inputs and targets

Input: the recipe (`[(food, pot amount)]`, `servings_made`), the person's `GuidanceContext`, and a target.

* **`meal`** (default: the next open meal today). The room is `meal_room(ctx, meal)`, the same room "What fits now" uses: the fair share of what is left, capped at 0.30 of the daily target for a main meal and 0.15 for the snack slot, with the carbohydrate goal for that meal.
* **`day`**. One serving against what is left today. The room is `day_room(ctx)`: for each tracked nutrient, `max(0, allowance − projected)` with no per-meal cap and no fair share; phosphorus on its weekly allowance. There is no carbohydrate check, because the carbohydrate goal belongs to a meal. A recipe for the week's lunches is the case this is for.

`servings_made` of `NULL` reads as 1. A recipe with a food that is gone answers `unavailable` ("edit the recipe first"), as apply does.

### 9.2 The check: `check_meal` kind `recipe`

The input is the **shares** (`pot amount ÷ servings_made × serving fraction`). Compared with the existing kinds:

| Rule | `ai` (meal ideas) | `recipe` |
|---|---|---|
| Totals within room plus the negligible amount, and within what is left of the day | yes | yes |
| Unknown values only while the day's level is ok; carbohydrate at most gap plus tolerance; no `avoid_ckd` | yes | yes |
| Each item ¼ to 3 servings | yes | **no**: a share may be small. The pot has its own bounds (§9.4). |
| Refuses the `ingredient` flag | yes | **no** |
| Refuses low treatments and alcohol | yes | **no** for a person's own recipe (they built it; `saved` is the same). An AI recipe cannot hold one anyway: V3 refuses it. |
| A "high" share of a nutrient that is not ok today | refused | refused |
| More than 1 serving of a "high" food | refused | refused (judged on the share) |

`meal_totals` counts an unknown value as 0 but returns the set of nutrients it missed. `fit_recipe` returns that set as `unknown` in `before` and `after`, so "fits" always comes with "at least" where something is not listed.

### 9.3 The algorithm

```
fit_recipe(ctx, recipe, target):
    room  ← room_for(ctx, target)
    n     ← recipe.servings_made or 1
    items ← [ (food, amount) ]                       # pot amounts, in servings of each food
    def ok(items, f = 1):  return check_meal(shares(items, n, f), room, kind="recipe").ok
    before ← figures(items)
    if ok(items): return result("fits", before)

    # ---- 1. lower amounts -------------------------------------------------------
    steps ← 0
    while not ok(items) and steps < RECIPE_MAX_LOWER_STEPS:
        k ← the nutrient or rule named by check_meal's reason          # e.g. potassium_mg, too_many_carbs
        c ← the ingredient with the largest share of k that
              lists a value for k, is not protein-role, is not a low-treatment food,
              and is above its floor        # floor = max(¼, ceil_to_step(RECIPE_FLOOR × original, ¼))
        if c is none: break
        while amount[c] > floor[c] and steps < RECIPE_MAX_LOWER_STEPS and check still fails for k:
            amount[c] ← step_down(amount[c])                           # one quarter step
            steps ← steps + 1
        # the next pass picks the next-largest contributor, or the next failing rule

    # ---- 2. swap ------------------------------------------------------------------
    swaps ← 0
    while not ok(items) and swaps < RECIPE_MAX_SWAPS:
        k ← as above
        c ← the largest contributor to k that is not low-treatment and not already swapped   # any role
        s ← best recipe swap for c                                     # §9.4
        if s is none: break
        replace c by s at s.amount;  swaps ← swaps + 1

    # ---- 3. a smaller serving -----------------------------------------------------
    f ← 1
    if not ok(items):
        for g in (¾, ½):
            if ok(items, g): f ← g; break

    if ok(items, f):
        give_back(items, f)           # undo lowering steps, last first, one quarter at a time, while it still fits
        return result("fits_smaller_serving" if f < 1 else "fits_after_changes", before, items, f)
    return result("does_not_fit", before, closest = items at ½, still_over = failing checks)
```

* `step_down(q) = (ceil(4q − 1e-9) − 1) / 4`: from 1.5 to 1.25, from 0.33 to 0.25.
* A pass changes one ingredient at a time, largest contributor first, so the change list stays short ("half the potatoes"), not a little off everything.
* The reasons map to moves: `would_exceed:k` and `high_warning:k` and `high_portion_too_large` (lower or swap the foods whose share is high); `too_many_carbs` (lower or swap the largest carbohydrate sources); `unknown:k` (swap only, since lowering cannot make a value known); `avoid_ckd` (swap only). The loop stops at the first quarter step that passes, so carbohydrate never falls further than one step past the goal. `check_meal` has an upper limit for carbohydrate and no lower one, so the engine never adds food to reach a goal.
* **Why protein is not lowered in step 1.** Lowering a chicken breast by half halves the protein with no warning, and a person on dialysis needs it. A swap keeps protein within the swap engine's own tolerance, and a smaller serving is a choice the person sees. The result always shows protein before and after.
* **Why low treatments are fixed.** The engine never lowers, removes or swaps out a food flagged as a low treatment, and never swaps one in. A recipe with a juice that is the cause says it does not fit, and the person edits it.
* **Give back.** If step 2 or 3 fixed the problem, earlier lowering may have been more than needed. The last-lowered ingredient is raised one quarter at a time while the recipe still fits. Swaps are not undone.
* **Order, in one line:** lower, then swap, then a smaller serving, and stop at the first that fits. It is the order of the swap engine (swap, then a smaller portion), with lowering added in front because it keeps the dish.

### 9.4 Step 2 reuses the swap engine, with two changes

`find_swaps` cannot be called on a share as it stands. Its portion bounds are ¼ to 3 servings, and a match on "serving" gives 1.0. So the core of `swaps.py` is split out (`swap_candidates`) and called with:

* the **trigger** judged on the ingredient's share, as `triggers_for` does for a portion, but only for nutrient `k`;
* the **match** (carbohydrate, protein or one-for-one) taken on the pot amount; a one-for-one match gives the same pot amount, not 1.0;
* portion bounds `¼ … RECIPE_POT_MAX_SERVINGS (40)` for the pot amount, with the share still at most 3;
* the swap engine's own eligibility (same category or role, no `ingredient`, alcohol, supply, "Not for me", never-suggest group), the 25 % reduction, the carbohydrate or protein match, the "no new problem" tests and the ranking with the person's preferences; and **never a low treatment**, even when the original is a drink.

`ingredient` foods are therefore lowered but not swapped. Salt can be lowered, to its floor.

### 9.5 Bounds

All are design choices. There are no new clinical numbers: the room, the caps, the carbohydrate tolerance and the "high" limits are the existing ones, with the sources they have in `docs/guidance.md`. The bounds go into `rules.py`, `RULE_DOCS` and `docs/guidance.md`, and `RULES_VERSION` moves.

| Constant | Value | Meaning |
|---|---|---|
| `RECIPE_FLOOR` | ½ | The least an ingredient is lowered to: `max(¼, ceil_to_step(½ × original, ¼))`. |
| step | ¼ | One lowering step (`REPAIR_STEP`). |
| `RECIPE_MAX_LOWER_STEPS` | 24 | Quarter steps in all. |
| `RECIPE_MAX_SWAPS` | 2 | Swaps in one fit. |
| Serving fractions | ¾, ½ | `SAVED_MEAL_SCALES` without 1. |
| `RECIPE_MAX_ITEMS` | 30 | As `save_recipe`. |
| `RECIPE_POT_MAX_SERVINGS` | 40 | Pot amount of one food. |
| Share | at most `PORTION_MAX` (3) | One serving never holds more than 3 servings of one food. |
| `AI_RECIPE_FOODS_MAX`, `RECIPE_PORTIONS` | 48; ¼, ½, 1 | Candidate foods; the portions they are ranked at. |
| `AI_RECIPES_MAX`, ingredients, steps | 2; 2 to 12; 8 × 200 characters | One answer. |
| `makes` | 1, 2, 4, 6 | The person's pick for a suggestion. |

### 9.6 The change lines

Every change becomes one line, written from templates in `messages.py` with the app's own figures and the food's own serving text (`portion_text`). Each line ends with "(app figures)". Examples:

* "Used 2 × 1 cup (156 g) of potatoes instead of 4 × 1 cup (156 g), to keep potassium within this dinner's room. Potassium per serving: 640 → 405 mg (app figures)." For a recipe that makes one serving the same line reads "Used ½ × 1 cup … instead of 1 × 1 cup …".
* "Swapped chicken thigh for chicken breast, 4 × 3 oz (85 g) in the pot, to keep phosphorus within this dinner's room. Phosphorus per serving: 310 → 230 mg; protein 27 → 28 g (app figures)."
* "Have ¾ of a serving: a full serving would use 520 mg of potassium against 410 mg of room; ¾ uses 390 mg (app figures)."
* "This recipe does not fit dinner after lowering amounts, a swap and a ½ serving. Still over: potassium 520 mg against 410 mg of room (app figures)."

Carbohydrate per serving is added to a line when it changes. It is a number in grams and nothing more: no carb choices, no ratio, nothing about insulin.

### 9.7 Determinism and the twin

No clock, no randomness. Every sort ends in the food id. The engine is a Python module and a JavaScript twin (`app/static/js/engine/guidance/recipes.js`, loaded with the nine others), checked by vectors (§12). The demo route `POST /api/guidance/fit-recipe` in `js/mock/guidance.js` calls the twin.

## 10. Screens (phone first)

They live where saved meals live: **Plan**. No new tab.

* **The list.** "Saved meals" becomes "Saved meals and recipes". A recipe shows "Makes 4" and its per-serving potassium, phosphorus, sodium and carbohydrate, with "at least" where something is not listed. Row actions: Add to plan, **Fit to my targets**, Edit, Delete. Buttons are 44 px high.
* **The editor** (the existing sheet) gets: Makes (servings), a steps list (add, remove, move; up to 20), a source link field, and a live per-serving panel. The amounts are the whole pot.
* **The fit sheet.** A bottom sheet.
  * A target choice: "Next open meal: dinner" (default), another meal, or "One serving against today".
  * A status line: "Fits as it is", "Fits after changes", "Fits at ¾ of a serving" or "Does not fit".
  * "What changed": the lines of §9.6, in order.
  * A table of Before, After and Room for potassium, phosphorus, sodium, fluid and carbohydrate, with unknown values as "not listed" or "at least". At 480 px and below it becomes one card per nutrient.
  * Buttons: **Save as new recipe** (the default; named "<name> (fitted)"), **Replace "<name>"** (second, after a confirm sheet that shows carbohydrate before and after; an Undo toast keeps the old body in the page and puts it back with `PUT`), **Add to plan** (one serving at the fitted size) and Cancel. For `does_not_fit` there is the closest result, what is still over, and a link to the handbook page of the nutrient; no Save.
* **AI recipes** (shown only when the server offers them to the person). A button "Suggest recipes" in Plan, which opens a sheet with the meal, the kind of dish (the fixed list) and how many servings; and a button "Rework with AI" in the fit sheet. Results are cards (§8.8) with **Save recipe**, **Add to plan** and Dismiss, and the usual "What will be sent?" link. If the AI's recipe needed the app's changes, they are listed on the card in the same words as a fit.
* Every figure and every name goes in with `textContent`. No inline script, and no file or font from outside the app.
* **When AI is off** (the admin, the person, the route, no consent yet): the AI buttons are not shown. Everything above still works. Settings → AI ideas lists a line "Recipes" with where it runs, or why it does not, like the other features. The demo and preview are always in this state. If the server cannot be reached, the fit says "Fitting needs a connection to your server", as guidance does; the demo's twin answers on the device.
* Handbook: a new page under "Using the app" (recipes, makes, steps and fitting), the AI page, the configuration table (`AI_ROUTE_RECIPES`) and an entry in `handbook/REVIEW.md` for the dietitian: the floor, the protein rule and the order are design choices to review.

## 11. Safety cases

| Case | How it is held |
|---|---|
| **A recipe never makes treating a low harder.** | No fit text, step, prompt or screen of this feature mentions a low. The engine never lowers, removes or swaps a low-treatment food, and never swaps one in. AI candidates exclude them (G7) and V3 checks again. Apply logs no entry as a low treatment and blocks nothing. The room is computed as today: low treatments still count for potassium, phosphorus, sodium and fluid and never for a meal's carbohydrate. A recipe is never a reason to wait, skip or delay. |
| **Nothing is advice about insulin.** | The schema has no field for it. The prompt keeps rules 3 and 6 word for word. Steps pass `dose_reason` and the names blocklist, and any mention of a low is dropped. All fit templates pass `BANNED_PATTERN`. Carbohydrate is grams only. |
| **A fit changes carbohydrate.** | The change line, the Before/After table and the replace confirm all show the old and new grams. A fitted copy has its own name. Replace needs a confirm and has Undo. Swaps already keep carbohydrate within the swap engine's tolerance. |
| **AI-made numbers are never shown as fact.** | The only numbers in an answer are `quarters`. Every nutrient figure comes from the food rows. Times and temperatures in steps are labelled as unchecked. The title is a template. |
| **Unknown stays unknown.** | `null` is kept in `per_serving`; "at least" is shown; the AI never fills a value; a fit can pass with an unknown only while the day's level is ok. |
| **The person's choices hold.** | "Not for me" foods and never-suggest groups are not candidates, are dropped by V3 and are not swapped in. A person's own recipe keeps its foods. |
| **No claim about cooking or allergens.** | Check 6 and 7 of §8.7; the fixed lines of §5.2; the app says it cannot check an allergen, as everywhere. |
| **Food the list does not show is not counted.** | A fixed line; check 8 for salt substitutes and heavy items; the person can add a food. |
| **No AI write.** | The server never saves an AI recipe. Save is the person's tap on `POST /api/meals`. Ask's trust setting does not apply (this is not Ask). |
| **Privacy.** | §8.2, shown by the dry run and pinned by a snapshot test. No name, date of birth, lab, note or weight. The recipe's own name, note and steps never leave. |

## 12. Tests, vectors and measuring

All run with `python -m pytest` and no network. New tests carry the `safety` marker where they pin a row of §11.

* **Migration** (`tests/test_migration_m021.py`): columns added; backfill only for the exact sentence; a changed note stays `NULL`; idempotent; foreign keys unaffected.
* **Meals** (`tests/test_meals_recipes.py`): the new fields in, out and on `PUT` (kept when left out, cleared on `null`); limits (steps, characters, servings); someone else's meal and food are 404; export and import carry them; `save_recipe` writes the columns; per-serving figures; `null` stays `null` and `unknown` counts; What fits now offers a 4-serving recipe at serving size.
* **Engine** (`tests/guidance/test_recipes.py`): as is; lowering order and floor; protein not lowered; swap respects category, preferences, "Not for me", no low treatment; smaller serving; no fit leaves `fitted` null; both targets; `servings_made` null; unknown values; determinism (same input twice, ids as tie-break); bounds (24 steps, 2 swaps); property tests over the built-in foods: a `fits*` result always passes `check_meal` kind `recipe`; no ingredient is below its floor or off the quarter grid; no low-treatment food is added, lowered or removed; every text passes `BANNED_PATTERN`.
* **Route** (`tests/guidance/test_api_recipes.py`): auth; scoped by user; 404; `no_targets` and `disabled`; no row is written (row counts equal before and after).
* **Vectors.** `tests/data/gen_guidance_vectors.py` gets `fit_recipe` cases: fits, lowered, swapped, smaller serving, does not fit, unknown, day target, null servings. `tests/js/run_vectors.mjs` replays them against the twin; `tests/guidance/test_parity_vectors.py` checks the file; `tests/data/README.md` says ten files in `engine/guidance/`, and `tests/test_vectors_readme.py` keeps it in step with the files. Never edit the file by hand.
* **AI** (`tests/test_ai_recipes.py`, `tests/test_ai_recipe_steps.py`): the request body is the dry run, byte for byte, and has none of the fields in "Never"; routing, consent, quota, `off`, `local_then_cloud`; the schema enum; every drop reason of §8.5; the title is a template even if the model sends one; a swap discards the steps; `claims_corrected`; the table of §8.7 as a parametrised pass/fail list, with evasions (zero-width characters, bidi controls, Cyrillic look-alikes, "dose" in other cases, "1/2 tsp", "½ cup"); `ai.recipe_steps` off drops all steps.
* **Golden set** (`tests/ai_golden/`, category `recipes`): at least 14 cases: a good recipe; unknown id; low treatment; "Not for me"; quarters 0 and 161; 13 ingredients; a step about insulin; a step with a link; a step with a quantity; a step with a nutrient claim; steps after a swap; a hemodialysis fluid case; a kidney-only profile; an injection in a food name; a refusal; no fit; the cloud fallback. `docs/ai.md` updates its case count.
* **Measuring** (`scripts/ai_eval.py`, manual): `recipe_schema_valid_rate`; `recipes_with_survivor_rate` (cases where at least one recipe survived); `recipe_survival_rate`; `recipes_unchanged_rate` (survived with no change by the app) and mean changes per recipe; `steps_dropped_rate`; **`steps_unsafe_shown`**, which must be 0 (the script has its own independent checker of the §8.7 rules, as `chat_unsafe_text_shown` has); `recipe_latency_ms`. Proposed gates for a model to be called recommended for recipes: 95 % schema-valid (as now), a surviving recipe in 70 % of cases, `steps_unsafe_shown` 0, p95 at most 60 s local and 30 s cloud. Attach the JSON to the pull request.
* **Browser** (`tools/e2e/`): the fit sheet and the editor at 390 px and 1,024 px; no CSP report; nothing requested but the app's own files.
* **Docs checks:** `python scripts/build_handbook.py --check`; the docs and vector tests.

## 13. Phases, costs and what comes later

Rough, for one agent working directly (±50 %), in the units of the ROADMAP.

| Phase | What | Tokens |
|---|---|---|
| 0 | **Groundwork.** Step 21, the three fields in the models, routes, export, import and demo twins; per-serving figures with unknown counts; What fits now per serving; `save_recipe` writes the columns; docs. | 1–1.5M |
| 1 | **Engine.** `check_meal` kind `recipe`; the swap core split; `fit_recipe`; messages; the route; rules, `RULES_VERSION` and `docs/guidance.md`; the tests above. | 1.5–2M |
| 2 | **Twin, vectors and screens.** `recipes.js`, vectors, the demo route; the list, the editor and the fit sheet; handbook page; ARCHITECTURE; e2e. **Release point: recipes that fit, without AI.** | 2–3M |
| 3 | **AI recipes.** The feature key in the settings registry, `routing.py`, the status and meta answers, the admin table, `deploy/compose.yaml`, the settings twin and the handbook's configuration table; candidates; prompt; schema; `validate_ai_recipe`; titles; the steps checks and the switch; golden cases; the eval additions; the cards; `docs/ai.md` (G18, the "Recipes that fit" section, the reworded row); `PROMPT_VERSION`. Then the owner's live run. | 3–4M |
| 4 | **Later, small.** The handbook's recipes through a link; an Ask and MCP `fit_recipe` read tool. | 1–1.5M |
| 5 | **Later, its own note.** Import from a web page. | 2–3M |

Phases 0 to 3 are about 7.5 to 10.5M tokens.

**Later.**

* **Handbook recipes first.** A link on each handbook recipe page, like the menu link of note 08 (`#plan-menu?items=…`): `#recipe?items=…&makes=4`, with built-in food references and servings only (the builder already has the foods and grams). Every number is already vetted and every food is built in, so it is a safer source than the web. A seasoning the app's list lacks is shown as not counted. The link is read as strictly as the menu link, and the person confirms before anything is saved.
* **Import from a web page.** schema.org `Recipe` data, as the ROADMAP says. The ingredient lines become foods the way "describe a meal" does, the person confirms each match, and the page's own nutrition panel is ignored because it usually omits potassium and phosphorus. Web fetching stays in the chat client; the app does not fetch pages. It uses this engine unchanged.
* **Ask and MCP.** A read-only `fit_recipe` tool (scope `assistant:read`, Ask's consent). The model could then ask whether a recipe fits and tell the person in words, with the app's figures under the answer.
* **A food-word check** for steps, comparing the words of a step with the food list, to replace the short list of check 8.

## 14. Risks

| Risk | Answer |
|---|---|
| A small local model writes poor recipes or invalid JSON. | The fit can still rescue a near miss; `local_then_cloud` is allowed; the gates of §12; suggestions are optional. |
| A step gives unsafe cooking advice (a time or a temperature). | The switch starts off; the label on every card; the live run before it is turned on; the person's own judgement. This is the one risk the checks cannot remove. |
| A step names a food that is not in the list, so its sodium or potassium is not counted. | Check 8, the fixed line, the instruction in the prompt; later the food-word check. |
| A fitted recipe changes carbohydrate and a person doses from the old figure. | §11: a new name, both figures in view, a confirm and Undo on Replace. |
| Herbs and spices have no food row. | The fixed line. The person adds a food, or imports one from USDA. A flat allowance like the handbook's would be a made-up number, so it is not used. |
| The fit gives a different dish than the person expects. | Every change is listed and nothing is saved unless the person presses Save. The floor is ½. |
| The twin drifts from the server. | The vectors, replayed in both pytest and Node. |
| One log entry per ingredient fills Today. | It is how saved meals behave now. A "log a recipe as one entry" idea is not part of this note. |
| The prompt is too large for a small context. | The trimming and `context_too_small` that meal ideas have. |

## 15. Decisions for the owner

The recommended choice comes first in each.

1. **Release the no-AI fit first** (phases 0 to 2), then the AI (phase 3), or build both together?
2. **Three new columns** (`servings_made`, `steps_json`, `source_url`) in schema step 21, with the exact-sentence backfill, or keep the count in the note text? (Recommended: columns. The text cannot be divided safely.)
3. **Repair "What fits now" for saved recipes** in phase 0, or leave it? (Recommended: repair; it is a bug today.)
4. **A new `check_meal` kind `recipe`** with the differences of §9.2, or reuse `ai` and `saved` and bend the inputs? (Recommended: the new kind.)
5. **The order**: lower amounts (floor ½, never a protein ingredient), swap (at most 2), smaller serving (¾, ½), then give back what was not needed. Or a smaller serving before a swap, as saved meals do today?
6. **Targets**: the next open meal, and "one serving against today" with no per-meal cap? (Recommended: both.)
7. **Save**: a fitted copy as a new recipe named "<name> (fitted)" by default, and Replace only with a confirm, before and after carbohydrate and Undo?
8. **Routing**: a feature `recipes`, default `local`, with `local_then_cloud` allowed, under the "Meal data" consent, with the consent wording naming recipes (so `POLICY_VERSION` moves and everyone is asked once more)?
9. **Steps from the AI**: allowed, behind `ai.recipe_steps` (admin, **off** until your live run), with the checks of §8.7 and a label? Or no steps at all? Or steps from a fixed list of cooking actions that the app words?
10. **Times and temperatures** in AI steps: allowed with the label "not checked for food safety"? Or none? (Recommended: allowed.)
11. **Title**: a template from the food names and a dish word, with a rename? (Recommended.)
12. **The recipe's own name, note, steps and link are never sent** to the AI, and the AI's steps are dropped when the app swaps a food?
13. **Order of later work**: the handbook link, then Ask and MCP `fit_recipe`, then web import?
14. **Live-run gates** for calling a model recommended for recipes: 95 % schema-valid, a surviving recipe in 70 % of cases, `steps_unsafe_shown` 0, p95 at most 60 s local and 30 s cloud?
15. **Wording**: change the "ingredient lists" row of `docs/ai.md` to "a food's printed ingredient text", and name the new section "Recipes that fit"?
16. **Review**: send the floor (½), the protein rule and the order to the dietitian review list in `handbook/REVIEW.md` with phase 2? They are design choices, not clinical numbers, but they decide what a person's dinner looks like.

### The owner's decisions (2026-10-27)

1. Release the fit without AI first (phases 0 to 2), then AI recipes (phase 3).
2. Three columns with the exact-sentence backfill, in schema step 21.
3. Repair "What fits now" for saved recipes in phase 0.
4. A new `check_meal` kind `recipe`, as in §9.2.
5. The order as proposed: lower amounts (floor ½, never a protein ingredient), swap (at most 2), a smaller serving (¾, ½), then give back
   what was not needed.
6. Both targets: the next open meal, and one serving against today.
7. Save a fitted copy as "<name> (fitted)" by default. Replace only with a confirm showing carbohydrate before and after, and Undo.
8. Feature `recipes`, default `local`, `local_then_cloud` allowed, under the Meal data consent. The consent wording names recipes, so
   `POLICY_VERSION` moves. The owner's server will set it to `cloud`, the same chain as meal ideas.
9. AI steps allowed behind `ai.recipe_steps`, off until a live run. The owner does that run on the cloud chain.
10. Times and temperatures allowed, with the label "not checked for food safety".
11. A title from the template, with rename.
12. The recipe's own name, note, steps and link are never sent, and the AI's steps are dropped when the app swaps a food.
13. Later work in this order: the handbook link, then Ask and MCP `fit_recipe`, then web import.
14. The live-run gates as proposed.
15. Yes to the wording change and the section name.
16. The floor, the protein rule and the order go on the dietitian review list in `handbook/REVIEW.md` with phase 2.
