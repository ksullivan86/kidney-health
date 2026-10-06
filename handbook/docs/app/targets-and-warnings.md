---
title: Targets and warnings
description: How the app rates each food, judges your day and week, suggests starting targets, and totals the gap between dialysis sessions.
slug: targets-and-warnings
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-05
sources: [ARCH, DG5, DG20, DG12, DG15, DG34, Q20, DG28a, DG53, NOTE05]
---

# Targets and warnings

The app shows the same rules this handbook explains. Its targets are **starting points to discuss with
your care team**; your team's numbers always win ([architecture contract][ARCH]).

## Warnings on each food

Every food and log entry gets `medium` or `high` warnings per serving:

| Nutrient | Medium | High | Why |
|---|---|---|---|
| Potassium | 101–200 mg | over 200 mg | NKF's 200 mg "high" line ([NKF][DG5]) |
| Phosphorus | 101–150 mg | over 150 mg, **or any food with a phosphate additive** | additive phosphorus is almost fully absorbed and under-counted in databases ([NKF][DG20]; [Kalantar-Zadeh 2010][DG12]; [St-Jules 2017][DG15]) |
| Sodium | 141–400 mg | over 400 mg | FDA "low sodium" is 140 mg or less ([FDA][DG34]) |
| Carbohydrate | 15–30 g (1–2 carb choices) | over 30 g, or a high-glycaemic food with 15 g or more | type 1 carb counting |
| Protein | 15–25 g | over 25 g | a large portion for a limited intake |

- The high-glycaemic flag only raises a warning to "high" from one carb choice (15 g) up, so a
  tablespoon of ketchup or one slice of white bread is not red for glycaemic index alone.
- **Star fruit** always rates high, with a note explaining why.
- **Hypo treatments** (glucose tablets, measured juice) get **no carbohydrate warning**: fast
  carbohydrate is the point of treating a low. Their potassium, phosphorus and sodium warnings still
  show, so the lowest-potassium rescue can be chosen. Low treatments are never blocked or warned
  against ([Treating a low](../t1d/treating-a-low.md)).
- The colour: **red** if any warning is high, **yellow** if any is medium, otherwise **green**.

## Your day

For each nutrient with a target the app shows **ok** below 80 % of the target (you can change the
80 % in your profile), **caution** from 80 % to 100 %, and **over** above 100 %, plus an "if you eat
what's planned" projection from planned entries. Hypo treatments are logged like any food and never
blocked or warned against.

## Day or week?

- **Potassium, sodium, fluid and carbohydrate** are judged **per day**.
- **Phosphorus, protein, calories and calcium** are judged on the **weekly average**, compared with the
  previous period ([KDOQI 2020][Q20]).
- With hemodialysis days set, potassium, sodium and fluid are also totalled **since the last session**
  against your per-day target × days, so the long weekend gap is visible ([Cabrera 2015][DG28a];
  [Foley 2011][DG53]). See [Dialysis days](../eat/dialysis-days.md).

## Suggested targets

"Suggest targets" in your profile fills in starting values from the same table as
[Eating well](../eat/index.md#your-numbers), labelled "discuss with your care team":

- **Weight basis:** "per kg" means per kg of a reference weight. With a saved height the app uses your
  weight when your BMI is in the healthy range and adjusts it towards that range when it is not;
  without a height it uses your weight as entered. The first note always says which weight it used
  ([design note 05][NOTE05]).
- **Sodium** 2,000 mg and **calcium** 1,000 mg at every stage.
- **Potassium** review ceilings 4,000 mg (stages 1–3a), 3,500 (3b), 3,000 (4), 2,500 (5 and
  hemodialysis) and 3,500 (peritoneal dialysis), always with the note *"Only restrict potassium if
  your blood potassium is high; your care team sets the number."*
- **Phosphorus** 1,000 mg (stages 1–4 and both dialysis types), 900 mg at stage 5 before dialysis.
- **Protein** 0.8–1.0 g/kg at stages 1–2; **0.8 g/kg at stages 3–5 with diabetes** ("about X g/day");
  1.0–1.2 g/kg on dialysis ([design note 05][NOTE05]).
- **Energy** 30 kcal/kg, with **carbohydrate** at 45 % of calories, split per meal.
- **Fluid** not tracked before dialysis; 1,500 mL on hemodialysis (1,000 mL plus an assumed 500 mL of
  urine) and 2,000 mL on peritoneal dialysis.

!!! info "Still to write (after the v0.3 app features land)"
    - [ ] Personalised targets from age, sex, activity and labs (design note 05) and which details do not
          change targets.
    - [ ] Screenshots of the warnings, the day view and the period summary (local images only).

## Sources

- [Project architecture contract][ARCH]: nutrient registry, thresholds, daily status, suggested targets.
- [Design note 05][NOTE05]: personalised targets (v0.3).
- [NKF: potassium][DG5]; [NKF: phosphorus][DG20]; [FDA: sodium in your diet][DG34].
- [Kalantar-Zadeh 2010][DG12]; [St-Jules 2017][DG15].
- [KDOQI 2020 nutrition guideline][Q20]; [Cabrera 2015][DG28a]; [Foley 2011][DG53].
