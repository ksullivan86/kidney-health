# 09 · Learn my food preferences (a preference profile, signals learned from the log, changes proposed from Ask)

| | |
|---|---|
| Status | Decided 2026-10-21 (§8). **All three parts are built** (§7): A (server and engine), B (screens) and C (the optional AI and Ask). |
| Date researched | 2026-10-21, against `main` at `1e512b5` |
| Scope | What the person can tell the app about taste (likes, "less often", food groups), what the app may learn from the log by its own code, how both change the ranking in meal guidance, what the optional AI is told, how Ask can propose a change, storage, API, settings, export/import/delete, the browser twin and tests. |
| Out of scope | Diet patterns that need per-food tags (vegetarian, pescatarian: ROADMAP "Meal guidance", note 06 §4.14), allergies (§4.10), cuisine data for built-in foods, the MCP server's tools for external assistants (a later step with its own token scope), the per-meal caps and score weights of note 06 (unchanged). |
| Builds on | [`06-meal-guidance.md`](06-meal-guidance.md) (§4.3 eligibility, §4.5 score, §4.7 familiar meals), [`04-optional-ai.md`](04-optional-ai.md) (untrusted data, consent, the guard), ARCHITECTURE "Saving from the chat". Where this note and note 06 differ on preferences, this note wins. |
| Re-verify | The file and line references in §1.2 against the code when the build starts (they move); the performance figures of §4.11 with `scripts/bench_guidance.py` after the build. This note adds no clinical number: its weights rank foods that already passed every kidney and carbohydrate check. |

---

## 1. Context

### 1.1 The ask

> "I want the same, ask for meal prep where the meals fall withing tunable guidelines, the ability for the Ai/app
> to learn your meal preferences and design and or choose recipes by just chatting with your device could be very
> helpful." (owner, 2026-10-15; added to the ROADMAP the same day as "Learn my food preferences")

"Meals within tunable guidelines" and "design or choose recipes by chatting" exist: targets and tolerances (note 05,
v0.3.1), the plan builder (note 06), saved meals, and Ask with `save_recipe` (ARCHITECTURE "Saving from the chat"). The
missing part is the first half of the sentence: suggestions that get better at what this person actually eats and
likes, without being told every time, and that the person can see, correct and switch off.

### 1.2 What exists today that already learns or filters

Facts from the code on 2026-10-21 (the build re-checks the line numbers).

| What | Where | Behaviour |
|---|---|---|
| Habit term | `score.static_term` | `+min(1.5, 0.5 × distinct days eaten in the last 14)`, `+0.5` for a food in any saved meal; variety penalties `-1.5` already today, `-0.5` per day of the previous 2, `-0.75` same family today |
| Slot habit | `Scorer.slot_habit` | `+1.0` (`SLOT_HABIT_BONUS`) for a food eaten in this meal slot on ≥ 2 of the last 14 days ("no pasta at breakfast") |
| "You often have this" | `fits.reasons_for` | a reason shown at ≥ 2 days in 14; also the `often` bit of AI candidates, checked by the guard |
| Usual meals | `fits.usual_meals_for` | the same 2–6 foods in the same slot on ≥ 2 dates of the last 60 days; offered like saved meals |
| Familiar meals win | `planner._familiar_options` | a saved, usual or starter meal beats a built one within `FAMILIAR_MARGIN = 3.0` |
| "Not for me" | table `food_preferences` (step 5), `PUT/DELETE /api/guidance/not-for-me/{food_id}`, `fits.ineligible_reason` | the food is never a suggestion (still searchable and loggable); at most 500 |
| "Never suggest these kinds of food" | setting `guidance.exclude_categories` | a whole category is never a suggestion |
| AI preferences text | setting `ai.preferences` (≤ 200 characters) | sent as untrusted data to meal ideas and Ask only, behind the AI opt-in and per-host consent |
| Recent foods | `foods.search_foods` | search orders the person's own recent foods first |

All of it reads only `status = 'eaten'` rows and skips low treatments (`purpose = 'hypo'`). Three facts matter for
the design:

1. **"Not for me" already reaches the Treating a low options list.** `swaps.hypo_options` and `insights.best_hypo_food`
   leave out "Not for me" foods (and `hypo_options` also excluded categories), pinned by `tests/guidance/test_swaps.py`.
   The card itself (`messages.treating_a_low_card`, `hypo.prefilter`) reads no preference. See §4.9 and §8 Q1.
2. **"Not for me" filters single foods only.** A usual meal or a starter meal that contains a "Not for me" food is still
   offered; so is a saved meal. Nothing documents that as intended.
3. **Nothing records where an entry came from or what was shown.** No column or audit row says an entry came from What
   fits now, a swap or a plan, and guidance routes write nothing except the "Not for me" list. A planned entry left
   `planned` on a past date is the only trace of a plan not eaten; a deleted planned entry leaves none.

Also: foods have a free-text `category` (12 canonical names in `foods.CATEGORIES`; 395 built-in foods), no cuisine and
no diet tag. "Meat, Poultry & Eggs" puts eggs with meat, and "Prepared & Fast Food" mixes both, so a vegetarian
pattern cannot be built from categories honestly (§4.10).

### 1.3 Constraints

From CLAUDE.md, ARCHITECTURE and notes 04 and 06:

* **Kidney limits first.** Every suggestion passes the hard filters of note 06 §4.5 (`would_exceed`, `unknown` on a
  not-ok day, `too_many_carbs`, `high_warning`) and the meal gate `check_meal`. Preferences may only reorder what
  passed.
* **Lows are rule-based and never blocked.** Nothing may block, delay or warn against treating a low; the Treating a
  low card is not ranked by taste.
* **Numbers never come from a model**, and the model learns nothing: every learned signal is computed by the app's
  code from the log, shown with its reason, and reproducible.
* **Least trust.** Off-by-default for anything that sends data out; everything per person (`user.id`, not-yours is
  404); the person can see, correct, export and delete it.
* **Parity.** The guidance engine has a browser twin checked by `tests/data/guidance_vectors.json`; any new engine
  input goes into the generator, `run_vectors.mjs` and `GE.makeContext`.
* **Performance.** p95 < 200 ms per guidance request on a Raspberry Pi 4 with 2,000 foods (note 06 §4.12); per-food
  work is cached in `Scorer.static`.

---

## 2. Findings

### F1. The habit term already "learns", but nobody can see or correct it

The engine already rewards foods eaten often and in the right slot, and mines usual meals. A person cannot see why a
food keeps coming back, cannot say "I ate it because there was nothing else", and cannot say "more of this" or "less
of this" without the all-or-nothing "Not for me". The cheapest real gain is to make the existing signals visible and
correctable and to add explicit, graded feedback, not a new learning system.

### F2. Explicit feedback beats inferred feedback at this scale

One person's log holds tens of foods a week. Inferring dislike from "shown but not chosen" needs impressions (what was
shown, when, and what was picked), which the app does not store, which are noisy (a person skips a good suggestion
because they already cooked), and which are behavioural data the app does not otherwise keep. The recommender
literature treats implicit signals as low-confidence evidence that needs volume to become useful (Hu, Koren and
Volinsky 2008). With one person's data, two buttons ("More like this", "Less often") next to the existing "Not for me"
give a clearer signal than any amount of inference. **Decision: no impression tracking** (§3.2).

### F3. One learned negative signal is cheap and honest: planned but not eaten

A planned entry that stays `planned` after its date has passed is already in the database. A food that is planned
again and again but rarely eaten is a fair "you skip this" hint. A person who never uses "mark eaten" would make every
planned entry look skipped, so an entry counts as skipped only on a date and meal where the person logged something
else they ate: they were logging that day and chose another food (§4.4, refined in part A).

### F4. A bounded term added after the hard filters cannot make a food fit

`Scorer.evaluate` returns at the first failed hard filter before any score is computed, so a term added to the score
can reorder only foods and portions that passed. For foods outside the protein roles, the base term separates renal
levels by 2.0 (green 3.0, yellow 1.0) and 4.0 (yellow vs red −3.0); protein foods are graded by phosphorus and
potassium per gram of protein instead. A like bonus capped at +1.0 (the size of the existing slot-habit bonus) cannot
by itself lift a yellow food over an otherwise equal green one.

### F5. Food groups are coarse but useful for "less often"

The 12 categories are good enough for "fewer sweets and snacks" or "I like fish" as a soft nudge, and the person
already uses them for "Never suggest". They are not good enough for diet patterns (§1.2).

### F6. Ask already has the confirm-before-save pattern

`chat_save.propose` validates a save call with the tool's own model, writes nothing, and returns a card; the page,
not the model, posts the card's payload to the normal route, and Undo deletes exactly what was written. A preference
change fits the same pattern. Unlike a log entry, a preference silently shapes every later suggestion, so it should
always be confirmed, whatever the trust setting (§4.8).

---

## 3. Options compared

### 3.1 Where preferences live

| Option | For | Against |
|---|---|---|
| **A. Extend `food_preferences`** with more values (`like`, `less`, `neutral` next to `not_for_me`) and group preferences in the `guidance` setting | One row per person and food makes the states exclusive by construction; export, import, isolation tests and the demo already handle the table and the setting | One migration step for two bookkeeping columns |
| B. A new `taste_profile` table | Free shape | Two places for one fact ("Not for me" and "dislike" could disagree); more export/import code |
| C. Free text only (`ai.preferences`) | Exists | Reaches only the AI; the rules engine cannot use it |

**Chosen: A.**

### 3.2 What the app learns

| Option | For | Against |
|---|---|---|
| **A. Existing habit signals made visible, plus "planned but not eaten"**, all computed per request from the log | No new data kept; reproducible; easy to explain and switch off | Learns slowly |
| B. Impressions: store what was shown and what was picked | Learns "passed over" | New behavioural data, noisy (F2), storage and retention rules, more parity surface |
| C. Let the AI summarise taste from the log | Fluent | Sends the log to a model, not reproducible, violates "the model learns nothing" |

**Chosen: A.** B can be reconsidered after live use with a separate note; C is ruled out.

### 3.3 How preferences act on ranking

| Option | For | Against |
|---|---|---|
| **A. A bounded per-food term in `Scorer.evaluate` and a bounded mean in `score_meal`**, after the hard filters | Cannot make a food fit (F4); one precomputed number per food; twin-friendly | Weights are a judgement (§8 Q4) |
| B. Filters (hide disliked foods) | Simple | "Not for me" already does this; a filter for "less often" removes choice |
| C. Re-rank the final list only | Simple | Does not reach the plan builder's beam search, where most meals are made |

**Chosen: A.**

---

## 4. Recommendation

### 4.1 Overview

1. **A preference profile** (Settings → Meal guidance → "Your food preferences"): per food *Like*, *Less often*, *Not for
   me*; per food group *Like* and *Less often* next to the existing *Never suggest*; and the existing AI text, moved to
   this screen (same storage, `ai.preferences`).
2. **Learned from your log**, computed by the app's code each time, shown with a reason, never stored as a fact: "eaten
   on 6 of the last 14 days", "usually at breakfast", "a usual lunch", "planned 4 times in 30 days, eaten once". Each item
   has *Keep* (becomes an explicit Like) and *Stop using this* (stores `neutral`, which switches the learned signals off
   for that food). A switch, *Learn from my log*, turns all learned signals off.
3. **Ranking only.** A bounded term after the hard filters (§4.5). No limit, warning or the Treating a low card ever
   reads a preference (§4.9).
4. **Ask can propose a change** ("I don't really like salmon") as a card the person confirms (§4.8).
5. **The optional AI** gets the explicit likes and dislikes, by name, under the existing consent (§4.7).

### 4.2 Data model (schema step 17)

`food_preferences` (step 5) keeps its key `(user_id, food_id)` and `ON DELETE CASCADE` from both `users` and `foods`.
The `preference` column, validated by the API (no `CHECK`, as today), takes:

| Value | Meaning | Effect |
|---|---|---|
| `like` | "More like this" | `+1.0` (§4.5) |
| `less` | "Less often" | `-2.0` |
| `not_for_me` | unchanged | never a suggestion (§1.2) |
| `neutral` | "Stop using what you learned about this food" | learned terms for this food are 0 (habit history, slot habit, "often", planned-not-eaten) |

`m017_food_preference_source.py` (append-only, `ATOMIC`, idempotent with `add_column_if_missing`): add `source TEXT`
(`person` or `ask`; backfill `person`) and `updated_at TEXT` (backfill `created_at`). `MAX_FOOD_PREFERENCES = 1000`
rows per person in total (the 500 cap stays for `not_for_me` alone so existing messages stay true).

`GuidancePreferences` (the `guidance` user setting, `extra="forbid"`) gains:

| Field | Type | Default | Note |
|---|---|---|---|
| `learn_from_log` | bool | `true` | today's behaviour; off removes every learned term (§4.4) |
| `like_categories` | list of `CategoryName`, ≤ 50, unique | `[]` | `+0.5` |
| `less_categories` | list of `CategoryName`, ≤ 50, unique | `[]` | `-1.0` |
| `hidden_usual_meals` | list of usual-meal keys, ≤ 50, unique | `[]` | *Not this meal* on a learned usual meal; the key is the slot and the sorted `(food_id, servings to ¼)` set that `usual_meals_for` already builds |

A category may be in at most one of `like_categories`, `less_categories` and `exclude_categories` (validator; 422
otherwise). The `guidance` key is already in `IMPORTED_SETTINGS`, so the new fields travel with an import that
replaces the profile; the browser defs (`engine/settings.js`) and `tests/data/settings_vectors.json` get the fields.

### 4.3 What counts as an explicit preference

Only a person's own action: a button in What fits now, a swap or the plan sheet (the "⋯" menu that already holds
"Not for me" gets *More like this* and *Less often*), the profile screen, *Keep* on a learned item, or a confirmed Ask
card (`source = 'ask'`). Logging a food is not a like; marking it eaten is not a like.

### 4.4 Learned signals

Computed in `context.load` from data the engine already reads, plus one query, only when `learn_from_log` is on:

| Signal | Source | Rule | Effect |
|---|---|---|---|
| Eaten often | 14-day history (exists) | unchanged | habit term and "You often have this", unchanged |
| Slot habit | 14-day history (exists) | unchanged | `+1.0` in that slot, unchanged |
| Usual meals | 60-day history (exists) | unchanged, minus §4.6 | offered as today |
| **Planned but not eaten** (new) | `log_entries` with `status = 'planned'` on a past date in `[today − 30, today − 1]` (`ctx.planned30`), and the `eaten`, non-hypo rows of the same window | A food is *skipped on a date* when an entry of it is still `planned` on that date and, on the same date and meal slot, at least one `eaten` non-hypo entry of a **different** food exists. A food is "planned but not eaten" when it was skipped on ≥ 2 distinct dates **and** was eaten (any meal, not a hypo treatment) on fewer than half of the distinct dates it was planned. There is no condition on the rest of the person's log. | `-0.5` |

*Refined in part A.* The first draft switched the signal on only for a person who marked ≥ 50 % of all their planned
entries as eaten. That depends on the person's habits elsewhere and lets one unrelated week switch a food's signal on or
off. The skipped-on-a-date rule looks at the entry itself: the slot has an eaten entry of another food, so the person was
logging that day and passed over the planned food. It is computed in the pure engine (`score.skip_stats`, with the JS
twin `skipStats`) from `planned30` and the eaten rows, so server and browser agree.

The new input is one more indexed read (`log_user_date`) of the `planned` rows of the 30 days before today (a few dozen
rows at most); the eaten rows of that window are read (`eaten30`) only when the 60-day history is not loaded anyway.
`learn_from_log = false` sets the habit term's history part, the slot
habit, "often", usual meals and planned-not-eaten to zero or empty for every food. The variety penalties (already
today, previous two days, same family) are not preferences and stay.

`GET /api/guidance/learned` (§4.10) returns the signals with plain reasons so the person sees exactly what the ranking
uses. No learned signal is stored. For a food, *Keep* stores `like` and *Stop using this* stores `neutral`; for a usual
meal, *Save as a meal* opens the existing save-meal sheet and *Not this meal* adds its key to `hidden_usual_meals`.

### 4.5 Ranking

Per food, computed once per request into a `dict[int, float]` held by `HabitStats` (the hot path stays plain floats,
§4.11):

```
pref(f) = clamp(P_food(f) + P_group(f) + L(f), -2.5, +1.0)

P_food:  like +1.0 · less -2.0 · neutral 0 · none 0      (not_for_me never reaches the scorer)
P_group: category in like_categories +0.5 · in less_categories -1.0
L:       planned-but-not-eaten -0.5 (only with learn_from_log, never for a neutral food)
```

* `Scorer.evaluate` adds `pref(f)` after the hard filters. It depends only on the food, so it is cached with the static
  term, and the `explain` output reports it as its own component, `preference`.
  A food that fails a filter fails it whatever its preference (property P2, §6).
* `score_meal` adds `clamp(mean(pref(f) for the meal's items), -1.5, +1.0)`, so a usual or saved meal full of "Less
  often" foods ranks lower and a liked one higher, still within `FAMILIAR_MARGIN`.
* What fits now gets one positive reason, `you_like` ("You said you like this"), ranked after the kidney reasons and
  before `you_eat_often`. A `less` food that still shows gets no extra caution: it is lower, not wrong.
* Swaps rank with the same term; the swap's kidney test is unchanged.
* `RULES_VERSION` changes, the vectors are regenerated, and `score.js` and `fits.js` gain the same term.

Why these sizes: `+1.0` equals the slot-habit bonus and is half the green-to-yellow gap of the base term (F4); `-2.0`
for *Less often* makes a disliked green food rank like an otherwise equal yellow one, which is the meaning of "less
often but not never"; the lower clamp `-2.5` keeps a food that is both `less` and in a `less` group from vanishing,
because that is what "Not for me" is for.

### 4.6 Familiar meals and "Not for me"

A usual meal or a starter meal that contains a `not_for_me` food, or a food of a "Never suggest" category, is no longer
offered (closes §1.2 fact 2). A saved meal is still offered: the person built it, and editing it is the fix. This is a
behaviour change for existing users and goes in the CHANGELOG.

### 4.7 The optional AI

* **Person block.** `prompts.person_block` gains `likes` and `less_often`: up to 10 food or group names each, explicit
  preferences only (never learned signals), each cleaned and capped at 60 characters like other names, inside the
  existing `<data>` block as untrusted data. Same gates as the text today (`ai.enabled`, opt-in, the feature route,
  per-host consent for `text` or `chat`); the dry run shows them. Not sent to describe-a-meal, photos or lab reports.
* **Candidates.** The meal-ideas candidate block gains a `liked` bit next to `often`; the guard rejects a "you said you
  like this" claim for a candidate without it, as it does for `often` today.
* **Version.** `PROMPT_VERSION` changes; golden cases cover a liked candidate, a `less_often` name that must not be
  recommended first, and a preference name that contains instructions (must be ignored). The owner's live run of
  `scripts/ai_eval.py --chat` follows, as for every prompt change.

### 4.8 Ask: proposing a preference change

* A new save tool, `set_food_preference {food_id? | category?, preference: like | less | not_for_me | clear}`, in
  `SAVE_TOOLS`. Exactly one of `food_id` (a food the person may use, from a `search_foods` result) and `category` (one of
  the person's categories). It counts toward `MAX_SAVES`.
* **Always a card**, whatever the trust setting: "Remember this for your suggestions? Salmon: less often." with
  *Remember* and *Cancel*. The page sends the normal route (§4.10) with `source = 'ask'`; *Undo* restores the previous
  value. `chat_save.effective_trust` is not consulted for this tool.
* Prompt rule 10 names the tool and says when to use it (only when the person states a taste in this conversation;
  never infer it from what they log or ask about). The model never sees the learned signals.
* Not for the MCP server in this step: external assistants need their own token scope for it (later).

### 4.9 What preferences never touch

* `hypo.prefilter`, `messages.treating_a_low_card` and Ask's rule-based `safety_check`.
* `swaps.hypo_options` and `insights.best_hypo_food`: `like`, `less`, `neutral`, group likes and dislikes and learned
  signals are never read there. The existing "Not for me" and "Never suggest" exclusions stay as they are until the
  owner decides §8 Q1.
* Targets, warnings, alerts, the day's totals, insights' wording and the carbohydrate checks.
* Allergies (§4.10).

A test asserts that `hypo_options` and the card are identical with and without any soft preference (P4, §6).

### 4.10 API, UI and wording

Routes, all under `/api/guidance` with `current_user`, scoped by `user.id`, not-yours 404:

| Route | Body / response |
|---|---|
| `GET /preferences` | `{rules_version, limit, foods: [{food_id, name, category, preference, source, created_at, updated_at}], groups: {like, less, never}, learn_from_log}` |
| `PUT /preferences/{food_id}` | `{preference}` → the row; 404 when `fetch_user_food` says no; 409 at the limit; idempotent |
| `DELETE /preferences/{food_id}` | 204, or 404 when there is none |
| `GET /learned` | `{items: [{food_id, name, kind: often | slot | usual_meal | planned_not_eaten, reason, effect: more | less}], learn_from_log}`; meals are listed by their usual-meal name |
| `GET/PUT/DELETE /not-for-me…` | kept as aliases that read or write `preference = 'not_for_me'`, so the demo and older pages keep working |

Group preferences are written through `PATCH /api/me/settings` with the whole `guidance` object, as today.

UI (behaviour; the front-end owner decides the layout):

* Settings → Meal guidance → **Your food preferences**: lists *Likes*, *Less often*, *Not for me* and *Learned from
  your log*, each row with its reason and the actions of §4.4; the group checkboxes; the AI text field (moved here,
  same setting); the *Learn from my log* switch with one line: "Off: suggestions use only your limits and variety, not
  what you usually eat."
* The "⋯" menu of a suggestion: *More like this*, *Less often*, *Not for me* (existing).
* Wording: "Less often and Not for me are about taste. They are not an allergy filter: the app cannot tell whether a
  food contains an allergen, so check labels." The app never says it "knows" a preference it learned; it says what it
  saw ("planned 4 times, eaten once").

### 4.11 Export, import, delete, isolation and performance

* **Export.** `export.json` → `food_preferences` already carries `{food_id, name, preference, created_at}`; it gains
  `source` and `updated_at`. The `guidance` setting carries the new fields. Learned signals are not exported (they are
  recomputed from the exported log). The README of the zip names `food_preferences`.
* **Import.** `ImportFoodPreference.preference` widens to the four values; `source` and `updated_at` optional; the caps
  of §4.2. Demo twin `mock/import.js` and `tests/data/import_vectors.json` follow.
* **Delete.** Cascade, as today. `tests/test_isolation_v03.py` `MATRIX` gains the new routes; a test proves one
  person's preferences never change another person's suggestions.
* **Performance.** One extra indexed query and one dict of at most 1,000 entries per request; `pref(f)` is folded into
  the cached static term, so the hot path gains one addition. Re-run `scripts/bench_guidance.py` and
  `tools/e2e/guidance_perf.py`; the budget of note 06 §4.12 is unchanged.

### 4.12 The browser twin and the demo

`engine/guidance/score.js` (`staticTerm`, `evaluate`, `scoreMeal`), `fits.js` (`reasonsFor`, `usualMealsFor`, combos),
`rules.js` (`makeContext`: `prefs.food_pref`, `prefs.like_categories`, `prefs.less_categories`, `prefs.learn_from_log`,
`prefs.hidden_usual_meals`, `planned30`, `eaten30`; `score.js` `prefTerms`, `skipStats`), `mock/guidance.js` (the in-memory preference map and the 30-day planned and eaten rows), `mock/export.js`,
`mock/import.js`. `gen_guidance_vectors.py` gains cases for every property of §6; `run_vectors.mjs` `contextFrom` reads
the new inputs.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| A preference outweighs kidney fit | Added after the hard filters; bounded at +1.0 up and −2.5 down; P2 and P3 |
| A filter bubble: the same liked foods every day | The variety penalties stay (−1.5 if already eaten today, −0.5 per day of the previous two, −0.75 for the same family) and the like bonus is capped at +1.0, so a liked food still loses ground on the days after it was eaten |
| A wrong learned signal (the person plans but never marks eaten) | An entry counts as skipped only on a date and meal where an eaten entry of another food exists, on ≥ 2 dates, and the food is eaten on fewer than half of the dates it was planned; the term is only -0.5; every learned item shows its reason and can be stopped |
| A model writes a preference from a misread message | Always a card (§4.8); the model never sees learned signals |
| Injection through a liked food's name in a prompt | The existing cleaning, escaping and untrusted `<data>` block; a golden case |
| "Less often" read as an allergy filter | The wording of §4.10; the app never uses the word allergy for a preference |
| Parity drift between Python and the browser | Vectors for every property; CI's JS job |
| A behaviour change surprises a current user (§4.6) | CHANGELOG line; the change only hides meals that contain a food the person already excluded |

---

## 6. Test vectors and properties

The generator (`tests/data/gen_guidance_vectors.py`) produces the exact numbers once the term exists; this note fixes
the properties they must satisfy.

* **P1, no preferences, no change.** With no stored preference, no group preference, `learn_from_log = true` and no
  planned-but-not-eaten history, every existing vector's output is unchanged except `rules_version` and the cases where a
  usual or starter meal holds an excluded food (§4.6).
* **P2, filters unchanged.** For every food and portion of the fixture, `evaluate(...).why_not` is identical with and
  without any preference.
* **P3, bounded.** For every scored evaluation, `-2.5 ≤ score_with − score_without ≤ +1.0`; for every meal score,
  `-1.5 ≤ Δ ≤ +1.0`.
* **P4, lows untouched.** `hypo_options`, `prefilter` and the card are identical for any combination of `like`, `less`,
  `neutral`, group likes and dislikes, learned signals and `learn_from_log`.
* **P5, neutral.** A `neutral` food has habit history 0, no slot habit, no "often" reason and no planned-not-eaten term.
* **P6, switch off.** `learn_from_log = false`: no usual meals, no habit history term, no slot habit, no "often", no
  planned-not-eaten; the saved-meal bonus and the variety penalties unchanged. A key in `hidden_usual_meals` removes
  exactly that usual meal and no other.
* **P7, familiar meals.** A usual or starter meal containing a `not_for_me` food or a food of a "Never suggest" category
  is never offered; a saved meal still is.
* **P8, Ask.** `set_food_preference` returns a pending card under `ask`, `conversation` and `always`; nothing is written
  until the page sends the route.
* **TV-PREF-1 (hand-computed).** Two foods identical except the base term (green 3.0, yellow 1.0): a `like` on the yellow
  food gives 2.0 + rest vs 3.0 + rest, so the green food still ranks first.
* **TV-PREF-2 (hand-computed).** A green food that is `less` and in a `less` group: −2.0 − 1.0 = −3.0, clamped to −2.5.

---

## 7. Implementation checklist

Three pull requests, each green and merged before the next:

**Part A, server and engine (about 1–1.5M tokens).** m017 and its test; `GuidancePreferences` fields and validator;
`context.load` (preference map, planned counts); `HabitStats` and `Scorer` term; `score_meal`; `reasons_for`
(`you_like`); familiar-meal filter (§4.6); routes and aliases; export, import and the zip README; isolation matrix;
vectors, `RULES_VERSION`, the JS twins and the demo mock; `docs/guidance.md`, ARCHITECTURE (migration table, guidance
API, export), `docs/privacy.md`, CHANGELOG.

*Built (2026-10-21).* Notes for parts B and C: the planned-but-not-eaten rule is the refined one of §4.4; invalid values
and bodies return 400 like the rest of the settings API (not 422), including a group in two lists; `GET /preferences` and
`GET /learned` are not gated by `guidance.enabled`; `you_like` is the last of the reasons, so with the two-reason cap it
shows mainly when no kidney reason competes (the screens can show the preference itself next to a food); the AI bridge
keeps `you_like` out of the candidates' `reasons` and passes a separate `liked` bit that `app/ai` does not read yet (part C
decides); `context.explicit_preferences(conn, user_id)` is the helper part C reads; the low-treatment options, their card
and their swaps never read a like, a "less often" or a learned signal, only "Not for me" and "Never suggest" with the floor
of §8 Q1; the pool pre-rank of the planner includes the preference term so a liked food can enter the day plan.

**Part B, the screens (about 0.5–1M).** The profile section, the learned list, the "⋯" menu items, the switch and the
wording of §4.10; Chromium checks at 375 and 1280 px in light and dark; the handbook's app page.

*Built (2026-10-21).* Notes for part C and the integrator: the screens are in `js/views/guidance.js` (`rowMenu`, `prefsSection`),
the AI text field in `js/views/ai.js` (`KH.ai.preferencesField()`; Settings → AI ideas keeps one line that points to the new
place), `js/views/plan.js` (`openMealEditor(t, trigger, draft)` for "Save as a meal") and `css/guidance.css`; the demo needed no
change. Decisions: **Keep** on a food the app *lowered* (`effect: less`, planned but not eaten) stores `less`, not `like` (a
"Keep" that turned a skipped food into a like would say the opposite of what the item says); a kept food shows "Kept: …" and no
buttons (a `neutral` would replace its like); the "⋯" menu reads the state from `GET /preferences` when it opens (there is no
route for one food) and a like or a "less often" does not reload the list it came from, only *Not for me* does; the menu is on a
suggestion, a normal swap row, a plan item and a Settings row, never on a Treating a low row; a usual meal's foods for
"Save as a meal" are rebuilt from its key (the learned item carries nothing else) and the saved-meal editor opens as a new
meal, nothing is saved until the person presses *Save meal*; the sentence of §4.10 is shown once, in Settings, and the menu says
nothing about allergies; preferences are saved online only (the outbox's own refusal message, nothing queued). For part C: a
preference Ask writes with `source = "ask"` shows in these lists as "added in Ask" and is changed or removed like any other;
after a card writes one, `KH.guidance.forgetAnswers()` is enough to make the next list load fresh (the "⋯" menu always reads
the server when it opens). `tools/e2e/prefs.py` walks all of it (real server and demo).

**Part C, AI and Ask (about 1–1.5M).** Person block and candidate bit with guard; `set_food_preference` with its card,
Undo and tests (`tests/test_ai_chat_save.py`); prompt rule 10; `PROMPT_VERSION`; golden cases; ARCHITECTURE "Saving
from the chat"; `docs/ai.md`, `docs/assistant.md`.

*Built (2026-10-21).* `PROMPT_VERSION` is `2026-10-21.1`; the owner's live `python scripts/ai_eval.py --chat` for it is still
to do (the four `chat-taste-*` questions and `taste_first_violations` are new in it). What differs from, or adds to, §4.7 and
§4.8:

* The three lists (`likes`, `less_often`, `not_for_me`) are always keys of the `person` object, null when empty (the block's
  convention), and sit behind exactly the gates of the person block: `routes._person` is called by meal ideas and Ask only.
* The `liked` bit is the person's own Like (`food id in habit.pref.liked`). Part A set it from "`you_like` is among the
  two reasons a card shows", so a liked food with two kidney reasons read as not liked; fixed in `ai_bridge` (the `often` bit
  has the same two-reason limit and was left as it is).
* Beyond rejecting a false `you_like` claim, the guard drops an AI idea that uses a Not for me food or a never-suggest group
  (`guard.person_excluded`), because the foods of a saved meal are candidate ids even when the person said no to one of them.
  "A `less_often` food is not the first idea" cannot be enforced (the app does not order the model's ideas): it is in the
  prompt, recorded in a golden case and measured by the live script. A food marked `less` (-2.0) usually scores below
  `MIN_SHOW_SCORE` and is not a candidate at all; a `less` group (-1.0) still is.
* `set_food_preference` lives in `app/ai/chat_preference.py`, not in `app/mcp/tools.py`, so the MCP server cannot list or
  call it for any token scope (a test pins that). `clear` over a `neutral` row is "nothing to forget" (a `neutral` row is the
  "stop learning" switch, not a taste). The page re-reads the current state when Remember is pressed, and Undo restores that.
* Ask's taste card is applied by the page through `PUT`/`DELETE /api/guidance/preferences/{food_id}` or the whole `guidance`
  setting; the API calls are in `js/core.js` (`api.foodPreferences`, `setFoodPreference`, `clearFoodPreference`), not in
  `views/ai.js` (part B edits it).

---

## 8. Decisions (owner, 2026-10-21)

The owner accepted every recommendation of the proposal ("go with your recommendations"):

* **Q1. "Not for me" and the Treating a low options: a floor.** The person's exclusions still apply, but when they
  would leave no option, `hypo_options` returns the full list with the note `shown_despite_exclusions` ("Shown
  although you marked them Not for me."). The card is unchanged. Built in part A.
* **Q2. Ask always asks** before a preference change, whatever the trust setting (§4.8). Part C.
* **Q3. Explicit likes and dislikes go to the AI** under the existing consent; learned signals never do (§4.7). Part C.
* **Q4. The weights of §4.5**, built as written (+1.0 like, −2.0 less often, +0.5 / −1.0 per group, −0.5 planned but not
  eaten, clamps −2.5 … +1.0 per food and −1.5 … +1.0 per meal); revisit after a month of real use.
* **Q5. Planned but not eaten is in part A.** Built with a refined rule: the proposal's "≥ 50 % of planned entries
  marked eaten" cannot be computed (marking eaten only changes `status`), so a food counts as skipped on a date only
  when something else was eaten in that meal (§4.4).
* **Q6. Diet patterns stay a separate ROADMAP item** (per-food tags first).

---

## 9. How to re-verify

* Before the build: re-read the functions named in §1.2 (`score.static_term`, `Scorer.evaluate`, `score_meal`,
  `fits.ineligible_reason`, `fits.usual_meals_for`, `planner._familiar_options`, `swaps.hypo_options`,
  `insights.best_hypo_food`, `chat_save.propose`, `data_import.ImportFoodPreference`) and update this note if they moved.
* After part A: `python -m pytest`, `node tests/js/run_vectors.mjs`, `python3 scripts/bench_guidance.py --max-p95 200`,
  `python3 tools/e2e/guidance_perf.py`.
* After part C: `tests/test_ai_golden.py` and the owner's live `python scripts/ai_eval.py --chat`.

---

## 10. Sources

* This repository: `app/guidance/` (`score.py`, `fits.py`, `planner.py`, `swaps.py`, `insights.py`, `hypo.py`,
  `context.py`, `state.py`, `rules.py`), `app/ai/` (`prompts.py`, `chat.py`, `chat_save.py`, `guard.py`, `routes.py`),
  `app/settings_registry.py`, `app/data_import.py`, `app/account.py`, `app/migrations/`, `data/foods.json`, ARCHITECTURE.md,
  notes 04 and 06 (read 2026-10-21).
* Y. Hu, Y. Koren, C. Volinsky, "Collaborative Filtering for Implicit Feedback Datasets", *IEEE ICDM* 2008, 263–272
  (implicit signals as low-confidence evidence). Background for F2 only; no number in this note comes from it.
