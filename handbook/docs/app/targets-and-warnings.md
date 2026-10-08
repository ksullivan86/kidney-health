---
title: Targets and warnings
description: How the app rates each food, judges your day and week, suggests starting targets, and totals the gap between dialysis sessions.
slug: targets-and-warnings
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [ARCH, DG5, DG20, DG12, DG15, DG34, Q20, DG28a, DG53, NOTE05, K24, A26-5, A26-11, FDC, MEDLINE-K]
---

# Targets and warnings

The app shows the same rules this handbook explains. Its targets are **starting points to discuss with
your care team**; your team's numbers always win ([architecture contract][ARCH]).

## Warnings on each food

Every food and log entry gets `medium` or `high` warnings per serving:

| Nutrient | Medium | High | Why |
|---|---|---|---|
| Potassium | 101–200 mg | over 200 mg | NKF calls a food with 200 mg or more per serving "high" ([NKF][DG5]); a food with exactly 200 mg shows yellow in the app |
| Phosphorus | 101–150 mg | over 150 mg, **or any food with a phosphate additive** | additive phosphorus is almost fully absorbed and under-counted in databases ([NKF][DG20]; [Kalantar-Zadeh 2010][DG12]; [St-Jules 2017][DG15]) |
| Sodium | 141–400 mg | over 400 mg | FDA "low sodium" is 140 mg or less ([FDA][DG34]) |
| Carbohydrate | 15–30 g (1–2 carb choices) | over 30 g, or a high-glycemic food with 15 g or more | type 1 carb counting |
| Protein | 15–25 g | over 25 g | a large portion for a limited intake |

- The high-glycemic flag only raises a warning to "high" from one carb choice (15 g) up, so a
  tablespoon of ketchup or one slice of white bread is not red for glycemic index alone.
- **Star fruit** and potassium-chloride **salt substitutes** always rate high, with a note explaining why.
- **Potassium additives:** a packaged food whose ingredients list a potassium additive, such as
  potassium chloride or potassium lactate, but whose label gives no potassium number gets a **medium**
  potassium warning: "contains a potassium additive; potassium not listed". When the label lists
  potassium, the normal thresholds apply. The app finds these additives in the ingredient list of a
  scanned food or one you typed in with **Quick add**. This rule is marked for review by a renal
  dietitian ([architecture contract][ARCH], v0.3 item 9; [Barcodes and label photos](barcode-and-photo.md)).
- A missing value is never treated as 0: a food from a label or a barcode that does not list potassium or
  phosphorus says "not listed", and every total it is part of is shown as a lower bound ("≥ 55 mg",
  "+ 1 not listed") with **Not complete** instead of **OK**, because the true total may be higher. A total
  that is already near or over the limit keeps its warning: a missing value can only add to it.
- **Hypo treatments** (glucose tablets, measured juice) get **no carbohydrate warning**: fast
  carbohydrate is the point of treating a low. Their potassium, phosphorus and sodium warnings still
  show, so the lowest-potassium rescue can be chosen. Low treatments are never blocked or warned
  against ([Treating a low](../t1d/treating-a-low.md)).
- The color: **red** if any warning is high, **yellow** if any is medium, otherwise **green**.

## Your day

For each nutrient with a target the app shows **ok** below 80 % of the target (you can change the
80 % in your profile), **caution** from 80 % to 100 %, and **over** above 100 %, plus an "if you eat
what's planned" projection from planned entries. A target with the same minimum and maximum, such as
protein "about 56 g", is a target, not a limit: it reads **Near target** or **Above target**. Hypo
treatments are logged like any food and never blocked or warned against.

**How close counts as on target.** Two settings decide when a number counts as "over":

- **A meal's carbohydrate** shows as over only when it is more than your carbohydrate tolerance above
  the meal's goal. The tolerance is **10 g** unless you change it (5–20 g) in **Settings → Meal
  guidance**, the same number the meal suggestions use. Ask your diabetes team: if you take fixed insulin
  doses, consistent carbohydrate helps your glucose ([ADA 2026][A26-5], Rec 5.28). A 65 g dinner against a
  60 g goal is on target; a 75 g dinner says "more than 10 g over the per-meal goal".
- **Carbohydrate you ate to treat a low** is left out of the meal's goal, so treating a low never makes a
  meal "over". It still counts in your day's totals, and an alert that shows anyway says how much it left
  out ("not counting 15 g used to treat a low").
- **An "about" target** (protein "about 56 g") is over as soon as you pass it, unless you set
  **Profile → "About" targets: on target up to (% above)**, from 0 to 10 %. With 5 %, 58 g of protein
  reads **Near target** ("2 g above, within your tolerance") and 59 g reads **Above target**. No
  guideline gives this number, so the app starts at 0 and leaves it to you and your dietitian. Limits
  such as potassium and sodium never get a tolerance.

## Day or week?

- **Potassium, sodium, fluid and carbohydrate** are judged **per day**.
- **Phosphorus, protein, calories and calcium** are judged on the **weekly average**, compared with the
  previous period ([KDOQI 2020][Q20]).
- With hemodialysis days set, potassium, sodium and fluid are also totaled **since the last session**
  against your per-day target × days, so the long weekend gap is visible ([Cabrera 2015][DG28a];
  [Foley 2011][DG53]). See [Dialysis days](../eat/dialysis-days.md).

## Suggested targets

"Suggest targets" in your profile fills in starting values from the same table as
[Eating well](../eat/index.md#your-numbers), labeled "discuss with your care team":

- **Weight basis:** "per kg" means per kg of a reference weight. With a saved height the app uses your
  weight when your BMI is in the healthy range and adjusts it towards that range when it is not;
  without a height it uses your weight as entered. The first note always says which weight it used
  ([design note 05][NOTE05]).
- **Sodium** 2,000 mg and **calcium** 1,000 mg at every stage.
- **Potassium** review ceilings 4,000 mg (stages 1–3a), 3,500 (3b), 3,000 (4), 2,500 (5 and
  hemodialysis) and 3,500 (peritoneal dialysis), always with the note *"Only restrict potassium if
  your blood potassium is high; your care team sets the number."*
- **Phosphorus** 1,000 mg (stages 1–4 and both dialysis types), 900 mg at stage 5 before dialysis.
- **Protein** 0.8–1.0 g/kg at stages 1–2; 1.0–1.2 g/kg on dialysis. At stages 3–5 before dialysis,
  with diabetes it suggests 0.8 g/kg ("about X g/day") and never less, because guidelines advise against
  going below 0.8 g/kg with diabetes ([ADA 2026][A26-11], Rec 11.3; [KDIGO 2024][K24], Rec 3.3.1.1;
  [design note 05][NOTE05]). Without diabetes it shows 0.6–0.8 g/kg; going below 0.8 is only for people
  their team supervises closely.
- **Energy** 30 kcal/kg until you add your age, sex, height and activity (below), with **carbohydrate**
  at 45 % of calories, split per meal. The 45 % is the app's
  default: there is no ideal share for everyone, so your diabetes team sets yours ([ADA 2026][A26-5], Rec 5.13).
- **Fluid** not tracked before dialysis; 1,500 mL on hemodialysis (1,000 mL plus an assumed 500 mL of
  urine) and 2,000 mL on peritoneal dialysis.

## Personalized targets

Optional details in **Profile → About you** and your results in **Lab results** (Profile → Blood and urine
tests) make "Suggest targets" start from you rather than from a 70 kg example ([design note 05][NOTE05]).
Which detail changes which target is listed in [First setup](first-setup.md#which-details-change-your-targets).
Under each suggested number, **Why this number?** shows the rule, its source and grade, and an **Expert
opinion** badge where part of the rule is the app's own choice; nothing is saved until you tap
**Save profile**. The app shows what would change compared with your saved targets, and after a new lab
result it offers **Review suggested targets** without changing anything by itself.

**Blood potassium** (a result from the last 90 days) moves the potassium review ceiling. "Default" is
the stage number above, for example 3,000 mg at stage 4. Potassium is the same number in both unit
systems (mmol/L = mEq/L).

| Your blood potassium | Suggested potassium |
|---|---|
| below 3.5 | no limit |
| 3.5–5.0 | one step higher than the default (stage 4: 3,500 mg); the default if you ticked "I have had high potassium" |
| 5.1–5.5 | the default, but no more than 3,000 mg |
| 5.6–5.9 | no more than 2,500 mg |
| 6.0 or more | no more than 2,000 mg, **and an urgent alert** (see below) |

**Blood phosphate** (last 90 days) sets phosphorus:

=== "US units"

    | Your blood phosphate | Suggested phosphorus |
    |---|---|
    | below 2.5 mg/dL | no limit |
    | 2.5–4.5 mg/dL | 1,000 mg |
    | above 4.5 mg/dL | 800 mg |

=== "International"

    | Your blood phosphate | Suggested phosphorus |
    |---|---|
    | 0.79 mmol/L or below | no limit |
    | 0.80–1.46 mmol/L | 1,000 mg |
    | 1.47 mmol/L or above | 800 mg |

    The app turns a result in mmol/L into mg/dL and rounds it to one decimal before it compares, so
    the edges sit where the rounded value crosses 2.5 and 4.5 mg/dL: 0.80 mmol/L is 2.48 mg/dL, shown
    as 2.5, and 1.46 mmol/L is 4.52 mg/dL, shown as 4.5. The Labs screen shows the converted value
    while you type ("Will be saved as …").

Other details that change the suggestion:

- **Calories** use your age, sex, height and activity, kept inside KDOQI's 25–35 kcal per kg, and are
  rounded to 10 kcal ([KDOQI 2020][Q20], 3.1.1). Without age and height the app keeps 30 kcal/kg.
- **Protein** goes up, not down, from age 65 or with signs of poor nutrition (albumin below 3.8 g/dL
  (38 g/L), weight loss over 5 % in 6 months, a low BMI, or frailty): 0.8–1.0 g/kg at stages 3–5 before dialysis, 1.0–1.2 g/kg at stages
  1–2, and 1.2–1.3 g/kg on dialysis with nutrition risk ([design note 05][NOTE05]).
- **Fluid** on hemodialysis is 1,000 mL plus your 24-hour urine output; on peritoneal dialysis, urine
  output plus the fluid your exchanges remove.
- **Fiber** gets a goal of at least 14 g per 1,000 kcal ([ADA 2026][A26-5], Rec 5.24).
- No starting targets during pregnancy or breastfeeding, under age 18, or in the first 12 weeks after a
  transplant.

## Examples

What the app shows for some builtin foods, per serving ([USDA FoodData Central][FDC]):

| Food and serving | Potassium | Phosphorus | Sodium | Carbs | Rating and why |
|---|---|---|---|---|---|
| Banana, 1 medium (118 g) | 422 mg | 26 mg | 1 mg | 27 g | **red**: potassium over 200 mg |
| White rice, cooked, 1 cup (158 g) | 55 mg | 68 mg | 2 mg | 45 g | **red**: carbohydrate over 30 g (fine for kidneys; count it for insulin) |
| White bread, 1 slice (29 g) | 37 mg | 28 mg | 142 mg | 14 g | **yellow**: sodium 141–400 mg, quick-acting carbohydrate |
| Cola, regular, 12 fl oz can | 18 mg | 33 mg | 11 mg | 38 g | **red**: phosphate additive, and over 30 g carbohydrate |
| Apple juice, ½ cup, logged as a low treatment | 125 mg | 9 mg | 5 mg | 14 g | **yellow**: potassium only; no carbohydrate warning |
| Glucose gel, 1 tube | 0 mg | 0 mg | 0 mg | 15 g | **green**: no potassium at all, like glucose tablets |

A red rating is not a ban. It tells you to check the portion and the rest of your day. Rice is red only
because of its carbohydrate, which you count for insulin; for your kidneys it is a low-potassium choice.

## Get help now if…

!!! danger "Call 911 (or your local emergency number)"
    Your lab potassium is **6.5 mmol/L or more** ([KDIGO 2024][K24], Table 28), or you have chest pain,
    fainting, a very slow, weak or irregular pulse, or sudden severe weakness, especially if your
    potassium has been high ([MedlinePlus][MEDLINE-K]).

!!! warning "Call your care team today"
    A potassium of **6.0–6.4 mmol/L**: if you feel unwell, go to hospital **now** to be checked and
    treated; if you feel well, call your team today for a repeat test within 24 hours
    ([KDIGO 2024][K24], Table 28). The app's day status is about food, not blood levels; a "green" day
    does not mean your blood potassium is safe. Full list: [Get help now](../get-help-now.md).

## Related pages

- [First setup](first-setup.md) · [Logging food](logging.md) · [Reports for your care team](reports-for-your-team.md)
- [Potassium](../eat/potassium.md) · [Phosphorus](../eat/phosphorus.md) · [Dialysis days](../eat/dialysis-days.md) ·
  [Blood potassium](../labs/blood-potassium.md) · [Treating a low](../t1d/treating-a-low.md)

## Sources

- [Project architecture contract][ARCH]: nutrient registry, thresholds, daily status, suggested targets.
- [Design note 05][NOTE05]: personalized targets (v0.3).
- [NKF: potassium][DG5]; [NKF: phosphorus][DG20]; [FDA: sodium in your diet][DG34].
- [Kalantar-Zadeh 2010][DG12]; [St-Jules 2017][DG15].
- [KDOQI 2020 nutrition guideline][Q20]; [Cabrera 2015][DG28a]; [Foley 2011][DG53].
- [KDIGO 2024 CKD guideline][K24], Table 28 (action levels for high potassium) and Rec 3.3.1.1 (protein);
  [MedlinePlus: high potassium level][MEDLINE-K] (warning signs).
- [ADA Standards of Care 2026, section 11][A26-11], Rec 11.3 (protein with diabetes and CKD).
- [ADA Standards of Care 2026, section 5][A26-5], Rec 5.13 (no ideal carbohydrate share), Rec 5.24 (fiber) and
  Rec 5.28 (consistent carbohydrate with fixed insulin doses).
- [USDA FoodData Central][FDC]: the food values in the examples.
