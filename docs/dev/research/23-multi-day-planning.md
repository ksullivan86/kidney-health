# 23 · Planning several days at once

| | |
|---|---|
| Status | Proposed, 2026-10-30. Phase 1 (the rules engine plans 1 to 14 days from the Plan tab) is built. The owner asked: "for the planning it should be able to plan the whole day - week or longer". The choices in §10 are defaults the owner can change. |
| Scope | One request plans every open meal of a run of days, each day against its own room; the person checks the preview, adds it as planned food in one go and can take it off again. A shopping list for the same days. |
| Out of scope | Insulin or medication of any kind. New targets for dialysis days (the profile has one set of daily targets). Buying food. AI planning whole days. |
| Builds on | Note 06 §4.7 (`plan-day`: slots, room, familiar meals, beam search, repair, protein top-up, energy note), note 09 (preferences), note 16 (recipes are planned one serving at a time), note 22 (the shopping list), the Running high rules (planned days count from today on). |

## 1. What "plan the whole day" means today

**Plan → Plan a day…** (and **Plan the rest of my day** on Today) already plans a whole day: on a day with nothing logged it fills
breakfast, lunch, dinner and the snack, and any meal can be ticked. On today it fills only the meals with nothing logged yet,
which is what the title says. So one whole day works. What does not exist is more than one day: a week means opening the sheet
seven times, and each day is planned without knowing the others, so the same dinner can come back every night.

## 2. The range

* **1 to 14 days**, starting on any day (today by default; the first day of the week shown when another week is open).
* Quick choices: **Rest of this week** (to the last day of the week, using the profile's week start, Monday or Sunday),
  **7 days** and **14 days**; or any number from 1 to 14.
* **Why 14 and not 28.** Targets change: a blood test or a clinic visit can lower a potassium or fluid limit, and a plan made
  against the old number keeps it. Two weeks is about as far ahead as fresh food keeps and as most people shop. A 14-day plan is
  already about 170 planned foods to read through before adding. The cross-day rules (the phosphorus week and the dialysis
  interval) look back at most 7 days, so 14 days covers two full rounds of both. Asking again after two weeks uses the new
  targets and what was really eaten. 28 is an open question for the owner (§10).
* The server refuses more than 14 days (400), so a stale or hand-made request cannot ask for more.

## 3. Each day's own targets

* **One set of targets.** The profile has one set of daily targets, the same every day. The app has no separate numbers for
  dialysis days, so the plan does not invent any. Each day is marked "Dialysis day" where the profile says so.
* **The day's own food first.** Each day starts from what is already logged on it, eaten and planned. A meal with food in it is
  not planned again (as for one day), unless the person ticks it.
* **Days are planned in order and see each other.** Day 2's room counts day 1's plan where a rule looks back:
  * phosphorus is judged on the week's average (note 06 §4.4), so the days earlier in the plan count as logged days with what is
    planned on them;
  * on hemodialysis with dialysis days set, potassium, sodium and fluid share the interval between sessions; the days earlier in
    the plan count toward it with what is planned on them.
  This is how Running high already treats a plan: from today on, a day stands for what is eaten and planned on it.
* **Habits stay as of the first day.** "You often have this", usual meals, likes and "planned but not eaten" come from the log
  before the first day and do not change across the plan. A planned food is never counted as eaten, and the plan never feeds the
  habit term.

## 4. Variety across days

Two rules, both only between days of the same plan, so day 1 is exactly what **Plan a day…** gives for that day:

1. **No meal twice in a row.** A meal with the same foods (any amount) is not planned for the same meal on either of the 2 days
   before. When nothing else fits that meal, it may repeat; the screen then says "Same as a day before: nothing else fits."
2. **Foods rotate.** A food on either of the 2 days before (logged or in the plan) ranks lower, 0.5 per day, both when the foods
   are picked and when whole meals are compared. That is the same weight the ranking already gives a food eaten the day before.

"Not for me" foods and "Never suggest" groups are never planned, as for one day. "Less often" foods rank lower. A saved meal or a
usual meal can still come back after two days.

## 5. How it lands

* **Preview first.** Each day shows its meals (the foods, the meal totals and where the meal came from) and the day's totals with
  the plan. A value a food does not list shows as **not listed**, a total that misses some as **≥**, never as 0.
* **Add to plan** asks first: "Add 84 planned foods to 7 days, Fri 30 Oct to Thu 5 Nov? Nothing is marked as eaten." Then the
  foods go in through the existing `POST /api/log/batch` as **planned** entries (`purpose: "none"`), at most 40 a request, each
  with its own `client_id`, so a retry after a lost answer adds nothing twice.
* **Undo** right after adding takes off exactly the foods it added.
* **Clear planned days** asks first, then takes every planned food off the days in the range: a new
  `POST /api/log/clear-planned {start, end, ids?}`. Eaten food is never touched. Planned low treatments stay.
* Planned food counts only in the planned and projected totals, never as eaten, as today.

## 6. The shopping list for the range

The preview lists every food the plan adds, summed over the days, with how many days it is on (the shape of
`GET /api/plan/shopping`), with **Copy list** and **Share list** as on the Plan tab (note 22 part A). The Plan tab's list still
covers the week shown.

## 7. Lows

* A plan never holds a low treatment (built meals refuse them; every planned entry is `purpose: "none"`).
* Planning never touches a low already logged, and clearing leaves planned low treatments in place.
* Nothing here blocks, delays or warns against treating a low. The "Treating a low" card works as before, on every day.

## 8. AI

The rules engine plans every day. AI is not part of phase 1. Later, the optional AI may only pick among the options the engine
offers for one meal of one day (as "Let AI choose" does today) or suggest ideas for one meal, each checked by the same meal check
(note 04, note 06 §4.13); an idea that does not fit is dropped or made smaller, never added unchecked. AI never plans doses, never
sees more than one day's room at a time and never writes: the person adds the plan.

## 9. The route

`POST /api/guidance/plan-days` `{start, days (1-14), meals?, use_saved_meals?, use_usual?, use_starters?, variant?}` computes only,
like `plan-day`, and answers `{status, rules_version, start, end, variant, days: [{date, dialysis_day, meals, protein_topup,
day_after, energy_note}], apply: {endpoint, entries}, shopping: {items}, notes, targets}`. Every query is scoped to the signed-in
person; a food or entry that is not theirs is 404. The browser twin in the demo gives the same answer (parity vectors).

## 10. Open questions for the owner

1. **Is 14 days enough, or should it be 28?** 28 means about 340 planned foods and a plan that can outlast a change of targets.
2. **Is "not the same meal on either of the 2 days before" right?** Some people like the same breakfast every day. Options: keep
   it, make it 1 day, or let breakfast repeat.
3. **Does your care team give you different targets on dialysis days** (fluid, for example)? The app has one set today.
4. **Should Clear planned days take off only what the plan added**, or every planned food on those days, as now?
5. **Should the snack be planned by default** on every day, as for one day?
6. **Should the plan skip a meal whose time has passed** on today (breakfast at 3 pm)? Today it fills every empty meal.

## 11. Phases

1. **Built:** the engine across days with variety, the route, the demo twin, the Plan tab sheet with preview, Add to plan, Undo,
   Clear planned days and the range's shopping list.
2. Edit the preview: swap one meal or drop a day before adding; "Show another" for one day only.
3. Optional AI for one meal of one day, checked as now (§8).
