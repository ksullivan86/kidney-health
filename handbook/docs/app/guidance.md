---
title: Meal guidance
description: "\"What fits now\", swap ideas, \"Plan the rest of my day\" and insights: what each one does, how the rules decide, and what they never do."
slug: guidance
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE06, NOTE04, ARCH, AKF-meal, A26-5, A26-6, DG12, Q20, FDC]
---

# Meal guidance

!!! note "Switched on by default"
    Meal guidance is on unless your admin switched it off for the server; you can hide it for yourself in
    **Settings → Meal guidance**. The **Treating a low** card stays either way.

Meal guidance answers "what can I still eat today?" from your own targets, what you have already eaten
and planned, and the foods you usually have. It uses fixed, written rules, **not AI**, so it works
without the internet and gives the same answer every time ([design note 06][NOTE06]).

## The four parts

| Part | Where | What you get |
|---|---|---|
| **What fits now** | the top of **Add**, after you pick a meal there; or **What fits** under a meal in **Today** | Up to 11 foods, grouped as protein, starch, vegetables and fruit, and extras (the best two of each group first, **Show more** for the rest), each with a portion that fits, the numbers, and one reason ("Low in potassium (55 mg)"). **Add** and **Plan** open the food sheet with that portion filled in. Saved meals and meals you often have that fit appear as chips. |
| **Swap ideas** | the food sheet, under a potassium, phosphorus or sodium warning: open **Lower-potassium ideas** (or lower-phosphorus, lower-sodium) | Up to 5 foods with **about the same carbohydrate** (or protein) and at least 25 % less of the problem nutrient, plus a smaller-portion option. **Use this instead** puts the other food in the sheet; **Use this amount** sets the smaller portion. |
| **Plan the rest of my day** | the **Meal ideas** card in **Today**, or **Plan a day…** in **Plan** | A suggested plan for the meals you have not logged yet (tick other meals to plan them anyway), built from your saved meals, your usual meals and the food list, with how the day would end up. **Use this plan** adds it as planned food; **Show another** gives a different one (5 options). |
| **Insights** | **Today** once breakfast, lunch and dinner are logged or after 7 pm (and for any past day); **Trends** for the days you choose there | Short notes with numbers, such as "Potassium was over your limit on 2 of 7 days (Sat, Sun). The main sources were potatoes and orange juice." |

Nothing is saved until you tap a button, and everything you add goes through the same warnings as any
other food ([architecture contract][ARCH]).

To stop a food from coming up, open **⋯** next to it and choose **Not for me**. It stays in search, and
**Settings → Meal guidance** lists it with **Suggest again**.

## How the rules decide

**1. Room left for this meal.** For potassium, sodium and fluid the app takes your daily target, takes
away what is eaten and planned, and shares the rest over the meals still open. For potassium,
phosphorus and sodium, one main meal never gets more than 30 % of the daily target (all snacks together
15 %); fluid has no per-meal cap. Dietitians use a similar rule of thumb: about 600–700 mg of potassium
per meal on a 1,800–2,200 mg day ([AKF Kidney Kitchen][AKF-meal]). It is a rule of thumb, not a
guideline number, so the app uses it only to choose ideas, never to warn you
([design note 06][NOTE06]).

**2. Phosphorus and protein use the week.** Phosphorus and protein are judged on the weekly average
([KDOQI 2020][Q20]), so the room for phosphorus comes from your last 6 days plus today, kept between 80 %
and 120 % of a normal day.

**3. Carbohydrate stays near your meal goal.** A food or plan must keep the meal within **10 g** of your
meal carbohydrate goal. If you take fixed insulin doses, consistent carbohydrate helps your glucose
([ADA 2026][A26-5], Rec 5.28). You can set the 10 g between 5 and 20 g; ask your diabetes team.

**4. Protein foods are judged per gram of protein.** Almost every meat is "red" by the per-serving
rules. So for protein foods the app looks at how much phosphorus and potassium comes with each gram of
protein, and prefers foods without phosphate additives, whose phosphorus is almost fully absorbed
([Kalantar-Zadeh 2010][DG12]).

**5. Familiar first.** Foods you eat often and your saved meals score higher, so suggestions look like
your own meals.

### What it never does

- It never suggests star fruit, foods with an "avoid" flag, or anything you marked **Not for me**.
- It never suggests **alcoholic drinks** (beer, wine, spirits, or any food flagged **Alcoholic drink**):
  with insulin, alcohol can cause a low hours later ([ADA 2026][A26-5], Recs 5.18–5.19). A saved meal of
  yours keeps its drink, and you can still log one yourself.
- It never offers glucose tablets or juice as a **meal**, and it never limits, delays or "swaps down" a
  low treatment.
- It never mentions insulin, units, ratios, doses, medicines or lab values. Carbohydrate is always in
  grams ([design note 06][NOTE06]).
- It never calls a food "safe" or "unlimited", and it never removes a warning.

## Low treatments

Treat a low first, with 15 g of fast carbohydrate when your glucose is under 70 mg/dL (3.9 mmol/L),
and log it afterwards ([Treating a low](../t1d/treating-a-low.md)). If your profile says you have
diabetes, **Today** has a **Treating a low** button: it shows what to do and your own low-treatment
foods at your dose, lowest potassium first, each with **Log it**. It works even with meal guidance
switched off, and without a connection it still shows what to do. When you log a low treatment, keep
**Used to treat a low** ticked (in the food sheet, under the food's numbers; it is ticked for you for glucose tablets, glucose gel and the other
low-treatment foods; you can tick it for any food you used, and untick it when, say, apple juice was
part of a meal). Low treatments count toward
potassium, phosphorus, sodium and fluid (you really had them) but are left out of the meal
carbohydrate check, and guidance never suggests a smaller dose. While the box is ticked the food sheet shows
the numbers as plain information, never as a warning, and Today marks the entry **treated a low**. If a
treatment had a lot of potassium, **For your next low** in the food sheet (and the day's insights) may add:
"For your next low: Glucose gel (1 tube) gives 15 g carbs with 0 mg potassium."
The suggested amount is never below your low-treatment dose (default 15 g, which you can set from 5 to
30 g as your diabetes team advises) ([ADA 2026][A26-6], section 6; [Treating a low](../t1d/treating-a-low.md)).
Tablets and other single pieces are counted out whole, rounded up: with 4 g glucose tablets and a 15 g
dose that is 4 tablets (16 g).

## Example

Stage 4: potassium 3,000 mg, sodium 2,000 mg, phosphorus 1,000 mg (an average week so far), 60 g of
carbohydrate per meal. Before dinner you have eaten 1,800 mg potassium, 550 mg phosphorus and 1,100 mg
sodium, and nothing is planned. Dinner and the snack slot are still open, so dinner gets two thirds of
what is left, and no more than 30 % of a day:

> **Left for dinner:** 800 mg potassium · 300 mg phosphorus · 600 mg sodium · 60 g carbs to reach 60 g
>
> Using the targets in your profile, saved Oct 3, 2026, 2:15 PM: potassium 3,000 mg · phosphorus
> 1,000 mg · sodium 2,000 mg · carbs per meal 60 g. **Check them in Profile**

If a food you logged today does not list potassium (or another of these values), the line says
**at most** for it and adds "Some foods logged today do not list potassium, so there may be less room":
the app cannot count what the label does not give.

The second line, also shown with every plan, says which targets the suggestions used and when you last
saved them. If a number is old or wrong, fix it in **Profile** first: guidance follows your targets
exactly, so a wrong target gives wrong suggestions.

You tap a baked potato with skin (1 medium: 37 g carbohydrate, 926 mg potassium). The sheet warns about
potassium and offers swaps such as:

> **Rice, white, long-grain, cooked (¾ × 1 cup):** about the same carbs (33 g vs 37 g) and 885 mg less potassium

Because the carbohydrate is about the same, your usual meal plan still fits. You can take the swap,
or keep the potato on another day and leach potatoes when you do
([Potassium leaching](../eat/potassium-leaching.md)). Food values: [USDA FoodData Central][FDC].

## Settings

In **Settings → Meal guidance**:

| Setting | Default | What it does |
|---|---|---|
| Show meal guidance | on | hides every part when off (**Treating a low** stays) |
| Show "Plan the rest of my day" | on | hides the plan builder when off |
| Show insights on Today and Trends | on | hides the insight notes when off |
| How close to my meal carb goal counts as on target | 10 g | 5–20 g; ask your diabetes team |
| Carbs I take to treat a low | 15 g | 5–30 g, from your diabetes team; sizes the low-treatment options |
| Never suggest these kinds of food | none | food categories to leave out, for example Fish & Seafood |
| Let AI re-order and explain suggestions | off | shown when your server offers AI; see below |
| "Not for me" foods | none | single foods (up to 500), added from any suggestion; they stay searchable and loggable; **Suggest again** removes one |

## What to do

- [ ] Set your targets first: guidance is only as good as your numbers ([First setup](first-setup.md)).
- [ ] Log what you have eaten before asking "what fits now".
- [ ] Save meals you like, so they come up as ideas.
- [ ] Read the reason under each idea, and check portions against your plate.

## If something goes wrong

- **"Nothing in your foods fits dinner within today's potassium room."** The day is nearly full. The app
  shows the closest meal and the numbers left. Choose a small, low-potassium meal and check
  [Potassium](../eat/potassium.md).
- **The same foods keep coming up.** Mark them **Not for me**, or save new meals you like.
- **"Guidance needs a connection to your server."** Guidance runs on the server. While the app stays
  open it shows the last ideas it fetched, with their time ("Saved at 6:40 PM"); nothing is kept after
  you close it, because the ideas are about your health.

## Optional AI ideas

If your admin allows it and you opt in, AI can re-rank the app's own ideas and pick between them. AI
only chooses from foods the rules already allowed, and every idea is checked again by the same rules
before you see it ([Optional AI](ai.md); [design note 04][NOTE04]).

- **AI ideas, checked against your targets** appears at the end of **What fits now** once AI ideas are on
  in **Settings → AI ideas**.
- With **Let AI re-order and explain suggestions** ticked in **Settings → Meal guidance**, you also get
  **AI order** (the same foods in the AI's order, each with its reason; tap again for the app's order),
  **Ask AI to pick** under swap ideas, and **Let AI choose** in the plan, which marks the meals it chose
  **AI's pick**. Each has **What will be sent?**, which shows the exact request before anything leaves the
  server, and each says how many AI picks the app's rules left out and why. Low treatments are never sent
  to AI.

## Related pages

- [Planning meals](planning-and-menus.md) · [Targets and warnings](targets-and-warnings.md) · [Optional AI](ai.md)
- [Potassium](../eat/potassium.md) · [Carb counting](../eat/carb-counting.md) · [Dialysis days](../eat/dialysis-days.md)

## Sources

- [Design note 06: rule-based meal guidance][NOTE06]: rules, numbers, wording; [design note 04][NOTE04]: AI on top.
- [Project architecture contract][ARCH]: warnings and the log API.
- [AKF Kidney Kitchen: potassium per meal][AKF-meal].
- [KDOQI 2020 nutrition guideline][Q20]; [ADA Standards of Care 2026, sections 5 and 6][A26-5] ([section 6][A26-6]).
- [Kalantar-Zadeh 2010][DG12]: phosphorus from additives.
- [USDA FoodData Central][FDC]: food values in the example.
