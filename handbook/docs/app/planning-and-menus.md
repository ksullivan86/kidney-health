---
title: Planning meals and using the menus
description: "Plan meals ahead, plan several days at once, reuse saved meals, copy a day, make a shopping list, and put the handbook's sample menus into the app."
slug: planning-and-menus
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-30
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
| Put it on a day | **Plan** → the meal → **Add to a day**: pick the date, the meal, Planned or Eaten, and how much to add; the sheet shows what it does to that day first |
| Add it while logging | **Today** → **Add saved meal**, or tap it in the shortcuts on **Add** |
| Change or delete it | **Plan** → **Saved meals** → **Edit** or **Delete** |

Each saved meal shows its total carbohydrate and potassium, and the worst rating of its foods.
After a save or import, an older request will not bring back an out-of-date saved-meal list.
The preview while creating or editing a meal says **not listed** for a missing nutrient amount and
**≥** for a partial amount. Changing **Makes** divides the known amounts between the servings.

### Recipes

A recipe is a saved meal that makes more than one serving. Put the amounts for the whole pot in the foods, and the number of
servings in **Makes**. You can also keep the cooking steps and a link to where the recipe came from. The app never opens the
link. Ask or a connected assistant can save a recipe for you too.

The list shows a recipe's numbers for one serving, and **What fits now** offers it one serving at a time.
**Add to a day** asks for **Servings to add**, starting at 1. Enter 2 for two recipe servings, or 0.5 for half a serving.
The preview shows the amounts you will add. Plain saved meals still use Scale: 1 is the meal as saved.

### Fit to my targets

**Plan** → a saved meal → **Fit to my targets** checks one serving against the room you have for a meal today, or against
what is left today. If it does not fit, the app tries these in order and stops at the first that works:

1. Less of one food at a time, never below half the recipe's amount. It never takes away protein this way.
2. Swap a food for a similar one with less of what is over (at most 2 swaps). A food you use to treat a low is never
   changed.
3. A smaller serving: ¾, then ½.

Every change is listed with the app's figures. If a food in the recipe does not list a value, the numbers count only the
other foods, so they say "at least" or "≥" and the row is grey, not green. A value no food lists says "not listed".
Nothing changes until you choose:

* **Save as a new recipe** keeps your recipe and adds "<name> (fitted)". A smaller serving is saved as more servings from
  the same pot, so one saved serving is the size that fits. A recipe makes at most 100 servings: when more would be needed,
  the amounts are made smaller instead and it still makes 100.
* **Replace this recipe** asks first and shows the carbohydrate per serving before and after. You can undo it.

Undo belongs to the recipe you replaced. Opening another recipe while a save finishes will not
give it the first recipe's Undo. Changing the fit target clears an older Replace question.

Cooking, soaking and draining are not counted, and seasonings that are not in your food list are not counted. The app says
so under every result.

### Recipes from AI (optional)

If your server has the optional AI and you turned it on, **Plan** shows **Suggest recipes with AI**, and the Fit to my targets
sheet shows **Rework with AI**. Pick the meal, the kind of dish and how many servings, and tap **Ask AI for recipes**.

* The AI may use only foods the app's rules chose, and gives the amount of each for the whole pot. The app works out every
  number from your food list.
* The app then fits each recipe the same way as Fit to my targets, and lists what it changed. A recipe that still does not
  fit is not shown. If the AI put more than 3 servings of a food in one serving, the app makes it smaller and you see
  **"The app made a portion smaller so the recipe fits your targets."** If it swapped that food for another one instead, it
  says **"The app changed a food so the recipe fits your targets."**
* The title is made by the app from the main foods, such as "Rice and chicken breast stir-fry". A recipe it reworked keeps
  your name with "(reworked)". Your recipe's name, note, steps and link are never sent.
* **Save recipe** adds it to your saved meals. **Add to plan** adds one serving to the meal. Nothing is saved until you tap.
* **Other recipes** (or **Another way** when reworking) asks again without the main foods already shown. Oil, flour and the
  like can still be used. Each ask counts as one AI call.
* Cooking steps from AI appear only if your admin turned them on. The app removes any step about medicines, a low,
  nutrients or amounts. The rest are marked "Steps written by AI. The app checked them for medicine talk and nutrient claims,
  not for cooking times or food safety. Check them before you cook."

See [Optional AI](ai.md) for what is sent and where.

## Copy a day

**Plan** → **Copy…** copies one day's entries onto another day. Choose which meals, and whether to copy
everything, only what was eaten, or only what was planned. The copies arrive as **Planned**, with
numbers worked out again from the foods. A good habit: copy a day that went well onto a day next week.

## Plan several days

**Plan → Plan several days…** plans up to 14 days at once from your own foods
([architecture contract][ARCH]; [design note 06][NOTE06]).

1. Choose the **First day** and how many **Days**, or tap **Rest of this week**, **7 days** or **14 days**.
2. The app plans every meal that has nothing logged yet. Tick meals if you want only those, on every day.
3. Check the preview. Each day shows its meals and what the day adds up to with the plan. A food that does
   not list a value shows **not listed**, and a total that misses some shows **≥**. It is never shown as 0.
4. Below the days is a **shopping list** for those days, with **Copy list** and **Share list**.
5. Tap **Add to plan**. The app asks first, then adds the foods as **planned**. Nothing is marked as eaten.

Each day is planned against your own targets, with the food you already logged that day. The days are
planned in order and see each other: phosphorus counts on the week's average, and on hemodialysis the days
between sessions add up. The same meal is not planned two days in a row unless nothing else fits; the
preview then says "Same as a day before: nothing else fits."

The app has one set of daily targets, the same on every day. Dialysis days are marked in the preview. If
your care team gives you other limits for those days, check them against the preview.

**Undo**, right after adding, takes off exactly what was added. **Clear planned days…** takes every
planned food off the days you chose. It never takes off food you ate, or a planned low treatment.

Two weeks is the most because targets can change after a blood test or a clinic visit. Plan again after
that, so the plan uses your new targets.

## Shopping list

**Plan** → **Shopping list** adds up every **planned** food in the week you are looking at: how many
servings, how many grams, and on how many days. Tick items as you shop. The ticks stay on this device
only; **Clear checks** removes them.

**Share list** (on a phone) and **Copy list** send what is not ticked yet as plain text, one food a line, to any list app:
Reminders, Google Keep, Bring!, or a family list app such as KitchenOwl or Grocy. Nothing is sent anywhere until you choose
where it goes. Where the browser does not allow copying, the list appears as text to select and copy yourself.

## Using the handbook's sample menus

The handbook has 7-day sample menus for each stage, built with the same targets and the same food list as
the app ([Sample menus](../eat/menus/index.md); [design note 08][NOTE08]). Every food on a menu is a
builtin food, with the **same name** in the app, and amounts are given in household measures and grams
([USDA FoodData Central][FDC]).

The quickest way is the link under each day on a menu page: **Add this day to my plan**. The app opens
(and asks you to sign in first if you are signed out). It lists the day's foods with its own numbers and shows
what the day adds up to with anything you have already planned. Choose the date, untick any food you do not
want, and press **Add to plan**. The foods go in as **planned**, so you can mark each one eaten later. Nothing
is saved until you press **Add to plan**, and the link only names foods from the app's own list and how many
servings: the app works out every number itself. If the link does not open your app, for example on another
device, use the steps below.

To put a menu day into your plan by hand:

- [ ] Open the menu for your stage, for example [Stage 3](../eat/menus/g3.md).
- [ ] On **Add**, choose the day, search each food by its name, and enter the **grams** from the menu.
      Choose **Planned**.
- [ ] After the first meal, use **Save as meal** so next time it is one tap.
- [ ] Repeat for the other meals, then **Copy…** the day to other days you want it.
- [ ] Open **Shopping list** for the week, and compare it with the menu's
      [grocery list](../eat/grocery-lists.md).

The menus are built for a 70 kg example adult. Scale the protein foods and starches to your own targets,
and ask your dietitian which days suit you.

!!! tip "Let the app plan the rest of the day"
    **Plan → Plan a day…** (or **Plan the rest of my day** on **Today**) builds the remaining meals from
    your saved meals, your usual meals and the food list, within the day's room for potassium,
    phosphorus, sodium and carbohydrate. **Show another** gives a different option; you review it and tap
    **Use this plan**, which adds the meals as planned food. Nothing is saved before that
    ([Meal guidance](guidance.md); [design note 06][NOTE06]).

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
- **I added a plan by mistake.** Tap **Undo** in the sheet, or use **Plan several days… → Clear planned days…**
  for those days. Food you ate and planned low treatments stay.
- **A saved meal shows a hidden food.** You deleted that food; the meal still works with the stored
  numbers.

## Related pages

- [Logging food](logging.md) · [Meal guidance](guidance.md) · [Reports for your care team](reports-for-your-team.md)
- [Sample menus](../eat/menus/index.md) · [Grocery lists](../eat/grocery-lists.md) · [Recipes](../eat/recipes/index.md) ·
  [Carb counting](../eat/carb-counting.md)

## Sources

- [Project architecture contract][ARCH], v0.2: planned entries, saved meals, copy day, shopping list; planning several days.
- [Design note 08][NOTE08]: the sample menus; [design note 06][NOTE06]: the plan builder (v0.3).
- [USDA FoodData Central][FDC]: the food list behind the app and the menus.
- [KDOQI 2020 nutrition guideline][Q20]; [ADA Standards of Care 2026, section 5][A26-5], Rec 5.28.
