---
title: Planning meals and using the menus
description: "Plan meals ahead, reuse saved meals, copy a day, make a shopping list, and put the handbook's sample menus into the app."
slug: planning-and-menus
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [ARCH, NOTE06, NOTE08, FDC, Q20, A26-5]
---

# Planning meals and using the menus

Planning means logging food **before** you eat it, marked **Planned**. The app then shows what your day
or week will look like "if you eat what's planned", so you can swap a food while there is still time
([architecture contract][ARCH]).

## Why plan

- **Carbohydrate stays steady.** If you take fixed insulin doses, eating a similar amount of
  carbohydrate at similar times helps your glucose and lowers the risk of lows ([ADA 2026][A26-5],
  Rec 5.28). That is easier when the meal is decided ahead.
- **Potassium, sodium and fluid count per day.** A plan shows a high day before it happens.
- **Phosphorus and protein count on the weekly average.** The week view shows the whole picture
  ([KDOQI 2020][Q20]; [Targets and warnings](targets-and-warnings.md)).

## Plan a meal

1. On **Add**, pick a future day (or today) and a food.
2. In the sheet, choose **Planned**. The sheet title changes to "Plan food" and the button to
   "Plan for dinner" (or your meal).
3. Save. On **Today** the entry has a dashed outline and a "planned" badge.

What changes on **Today**:

- Each nutrient bar shows the eaten total, plus a lighter part for what is planned.
- Under the eaten alerts you see, in gray, lines such as "If you eat what's planned, potassium reaches
  104 % of today's limit (2,600 / 2,500 mg)".
- Each meal shows "Planned: +32 g carbs" separately from what you have eaten.

When you eat it, tap **Eaten** on the entry, or **Mark all eaten** for the meal. Change the amount first
if you ate more or less.

## The week: Plan

**Plan** shows 7 days from your chosen week start (side by side on a computer, as cards on a phone). Each
day shows projected potassium, phosphorus, sodium, protein, carbohydrate and fluid (when you have a fluid
target), colored by how close they are to your targets, and how many items are planned or eaten.

- Tap a day to open it on **Today**.
- **Last week** / **Next week** move through the weeks.
- On hemodialysis, your dialysis days are marked.

## Saved meals

A saved meal is a list of foods and amounts you eat often, such as "Usual breakfast".

| To… | Do this |
|---|---|
| Save a meal you just logged | **Today** → the meal's **Save as meal** |
| Build one from scratch | **Plan** → **Saved meals** → **New saved meal**, then search and add foods |
| Put it on a day | **Plan** → the meal → **Add to a day**: pick the date, the meal, Planned or Eaten, and a scale (0.5 for half, 2 for double); the sheet shows what it does to that day first |
| Add it while logging | **Today** → **Add saved meal**, or tap it in the shortcuts on **Add** |
| Change or delete it | **Plan** → **Saved meals** → **Edit** or **Delete** |

Each saved meal shows its total carbohydrate and potassium, and the worst rating of its foods.

## Copy a day

**Plan** → **Copy…** copies one day's entries onto another day. Choose which meals, and whether to copy
everything, only what was eaten, or only what was planned. The copies arrive as **Planned**, with
numbers worked out again from the foods. A good habit: copy a day that went well onto a day next week.

## Shopping list

**Plan** → **Shopping list** adds up every **planned** food in the week you are looking at: how many
servings, how many grams, and on how many days. Tick items as you shop. The ticks stay on this device
only; **Clear checks** removes them.

## Using the handbook's sample menus

The handbook has 7-day sample menus for each stage, built with the same targets and the same food list as
the app ([Sample menus](../eat/menus/index.md); [design note 08][NOTE08]). Every food on a menu is a
builtin food, with the **same name** in the app, and amounts are given in household measures and grams
([USDA FoodData Central][FDC]).

To put a menu day into your plan:

- [ ] Open the menu for your stage, for example [Stage 3](../eat/menus/g3.md).
- [ ] On **Add**, choose the day, search each food by its name, and enter the **grams** from the menu.
      Choose **Planned**.
- [ ] After the first meal, use **Save as meal** so next time it is one tap.
- [ ] Repeat for the other meals, then **Copy…** the day to other days you want it.
- [ ] Open **Shopping list** for the week, and compare it with the menu's
      [grocery list](../eat/grocery-lists.md).

The menus are built for a 70 kg example adult. Scale the protein foods and starches to your own targets,
and ask your dietitian which days suit you.

!!! tip "Coming in v0.3"
    **Plan the rest of my day** builds the remaining meals from your saved meals, your usual meals and
    the food list, within today's room for potassium, phosphorus, sodium and carbohydrate. You review it
    and tap **Use this plan**; nothing is saved before that ([Meal guidance](guidance.md);
    [design note 06][NOTE06]).

## Example: a dialysis week

Your sessions are Monday, Wednesday and Friday. On Sunday evening:

1. Copy last Tuesday (a good day) onto this Tuesday and Thursday.
2. Add your "Dialysis-day lunch" saved meal to Monday, Wednesday and Friday.
3. Check Saturday and Sunday on **Plan**: before the long gap, potassium, sodium and fluid add up across
   both days ([Dialysis days](../eat/dialysis-days.md)).
4. Open the shopping list and go.

## If something goes wrong

- **Planned food is counted as eaten.** It is not: eaten totals and alerts use eaten entries only; the
  gray "if you eat what's planned" line and the lighter bar show the plan.
- **The shopping list is empty.** It lists **planned** entries only, for the week on screen.
- **A saved meal shows a hidden food.** You deleted that food; the meal still works with the stored
  numbers.

## Related pages

- [Logging food](logging.md) · [Meal guidance](guidance.md) · [Reports for your care team](reports-for-your-team.md)
- [Sample menus](../eat/menus/index.md) · [Grocery lists](../eat/grocery-lists.md) · [Recipes](../eat/recipes/index.md) ·
  [Carb counting](../eat/carb-counting.md)

## Sources

- [Project architecture contract][ARCH], v0.2: planned entries, saved meals, copy day, shopping list.
- [Design note 08][NOTE08]: the sample menus; [design note 06][NOTE06]: the plan builder (v0.3).
- [USDA FoodData Central][FDC]: the food list behind the app and the menus.
- [KDOQI 2020 nutrition guideline][Q20]; [ADA Standards of Care 2026, section 5][A26-5], Rec 5.28.
