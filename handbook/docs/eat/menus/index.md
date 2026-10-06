---
title: Sample menus
description: Seven-day sample menus for each stage and treatment, built from the app's own food list and checked against the app's starting targets.
slug: menus
audience: [patient, caregiver]
applies_to: [G1-G2, G3a, G3b, G4, G5, HD, HHD, PD, Tx]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-05
fact_checked: 2026-10-05
sources: [A26-5, K24, A26-11, Q20, FDC, K22, DG19a, K09TX, FDAgrapefruit, FSTEMPS]
---

# Sample menus

## In short

Each menu is a full week of meals for one stage or treatment, built only from foods in the app's
food list and checked by a script against the app's starting targets for a 70 kg adult with type 1
diabetes. Every meal shows carbohydrate, protein, potassium, phosphorus, sodium and fluid, so you can
see where the numbers come from and swap foods with your dietitian. They are examples, not
prescriptions.

--8<-- "includes/starting-points.md"

## The menus

--8<-- "docs/eat/menus/_overview.md"

Each menu has a matching [grocery list](../grocery-lists.md). For single dishes with the same kind of
numbers, see the [recipes](../recipes/index.md).

## How to use a menu

- [ ] **Pick the menu for your stage or treatment**, and check its numbers against the targets your
      team gave you.
- [ ] **Scale for your weight.** The menus are for 70 kg. Protein changes with your reference weight:
      about ½ oz of meat at lunch and dinner for every 5 kg before dialysis, about ¾ oz on dialysis.
- [ ] **Keep carbohydrate steady.** Main meals stay at about the same carbohydrate every day
      (about 55 g, or 50 g on peritoneal dialysis) so a fixed insulin plan or ratio works the same way
      ([ADA 2026 §5][A26-5]). Your own amount comes from your diabetes team.
- [ ] **Swap like for like** using the swap list on each menu page and the [food lists](../food-lists.md).
- [ ] **Treat lows first.** Rescue foods sit on top of any menu ([Treating a low](../../t1d/treating-a-low.md)).
- [ ] **Log it:** every food is in the app under the same name; save a day as a meal or copy it.

## How the menus were built

- Targets: the app's starting targets ([Eating well](../index.md#your-numbers)) for a 70 kg, 170 cm
  adult with type 1 diabetes: protein 0.8 g/kg before dialysis and 1.0–1.2 g/kg on dialysis
  ([KDIGO 2024][K24]; [ADA 2026 §11][A26-11]; [KDOQI 2020][Q20]); potassium, phosphorus, sodium and
  fluid at or under the stage's ceiling; energy within 25–35 kcal/kg ([KDOQI 2020][Q20]); on
  peritoneal dialysis, food energy reduced for the calories in the dialysis fluid.
- Stages 1–2 and after a transplant: protein 0.8–1.0 g/kg (56–70 g), sodium under 2,000 mg, and no
  potassium or phosphorus ceiling, because those are limited only when blood tests run high
  ([KDIGO 2024][K24]). The stage 1–2 week also has at least 14 g of fibre per 1,000 kcal
  ([ADA 2026 §5][A26-5]). The transplant week follows KDIGO's advice of a healthy diet
  ([KDIGO 2009][K09TX]), leaves out grapefruit and its relatives ([FDA][FDAgrapefruit]) and cooks every
  meat, fish and egg to a safe temperature ([FoodSafety.gov][FSTEMPS]).
- Carbohydrate at each main meal within 5 g of the menu's amount; snacks 10–30 g.
- No foods with phosphate additives, no star fruit, and no hypo-treatment foods (rescue foods stay
  separate).
- Every number is from USDA FoodData Central through the app's food list ([FDC][FDC]). The data and the
  checks live in `handbook/data/menus.yml` and `scripts/build_handbook.py`; run
  `python scripts/build_handbook.py --totals` to see every day's totals.

## The original sample day

The diet guide that came before this handbook had one worked day for stage 3b–4 with type 1 diabetes,
not on dialysis, for an 80 kg adult: protein about 0.8 g/kg (64 g), carbohydrate about 45 g at meals
and about 15 g at snacks, potassium under 2,500 mg, phosphorus under 800 mg, sodium under 2,000 mg.
Day 1 of the [stage 3 menu](g3.md) is built from it.

??? example "The original sample day (80 kg): Carb g, Protein g, K mg, P mg, Na mg"

    | Meal | Food | Carb | Prot | K | P | Na |
    |---|---|---|---|---|---|---|
    | **Breakfast** (~46 g carb) | Cream of Wheat, cooked without salt, ¾ cup | 20 | 2.7 | 30 | 28 | 11 |
    | | Blueberries, ½ cup | 11 | 0.5 | 57 | 9 | 1 |
    | | Egg, hard-boiled, 1 large | 1 | 6.3 | 63 | 86 | 62 |
    | | White toast, 1 slice, with 1 pat unsalted butter | 14 | 2.6 | 38 | 29 | 143 |
    | | Coffee, 8 oz, with 1 tbsp half-and-half | 1 | 0.8 | 136 | 21 | 14 |
    | | *Breakfast total* | **46** | **13** | **324** | **174** | **231** |
    | **Snack** (~17 g) | Applesauce, unsweetened, ½ cup + unsalted peanut butter, 1 tbsp | **17** | **4** | **180** | **60** | **5** |
    | **Lunch** (~46 g) | White bread, 2 slices | 29 | 5.1 | 73 | 57 | 284 |
    | | Roast turkey breast (home-roasted, not deli), 1.5 oz | 0 | 13.0 | 107 | 99 | 43 |
    | | Mayonnaise, 1 tbsp | 0 | 0.1 | 3 | 3 | 89 |
    | | Iceberg lettuce, 1 cup + cucumber, ½ cup | 4 | 0.9 | 178 | 26 | 8 |
    | | Pineapple canned in juice, ⅓ cup | 13 | 0.3 | 101 | 5 | 1 |
    | | *Lunch total* | **46** | **20** | **462** | **191** | **425** |
    | **Snack** (~14 g) | Saltines, unsalted tops, 6 + cream cheese, 1 tbsp | **14** | **3** | **42** | **34** | **183** |
    | **Dinner** (~42 g) | Chicken breast, roasted, 2 oz | 0 | 17.7 | 146 | 130 | 42 |
    | | White rice, cooked, ⅔ cup | 30 | 2.8 | 37 | 45 | 1 |
    | | Green beans, boiled, 1 cup | 10 | 2.4 | 182 | 36 | 1 |
    | | Cauliflower, boiled, ½ cup, with 1 tbsp olive oil | 3 | 1.1 | 88 | 20 | 9 |
    | | *Dinner total* | **42** | **24** | **453** | **231** | **54** |
    | **Evening snack** (~14 g) | Peaches canned in juice, ½ cup | **14** | **1** | **159** | **21** | **5** |
    | **DAY** | | **179 g** | **64 g** | **1,620 mg** | **711 mg** | **903 mg** |

    Also: fibre about 17 g, energy about 1,470 kcal, phosphorus almost entirely natural (no additives).

What to notice ([KDOQI 2020][Q20]; [KDIGO 2022][K22]; [AKF][DG19a]):

- **It was deliberately light on calories.** 25–35 kcal/kg is about 1,900–2,800 kcal for 75–80 kg;
  that day was about 400–530 kcal under the floor. Close the gap with fat (olive oil, butter, mayonnaise,
  a second tablespoon of peanut butter) or more measured starch covered by insulin, **not with more
  meat**, which would push protein and phosphorus up. The new menus do this and stay at or above
  1,750 kcal for 70 kg, except on peritoneal dialysis, where the dialysis fluid adds calories
  ([Eating enough](../eating-enough.md)).
- There was about 1,100 mg of sodium headroom and 900–1,400 mg of potassium headroom for seasoning and
  a second vegetable, depending on the ceiling in use.
- **Hypo treatments sit on top:** two 15 g lows treated with glucose tablets add 0 mg potassium; with
  apple juice about 250 mg; with orange juice about 500 mg. The app logs them as foods.
- To fit a smaller person, shrink the meat (1 oz turkey, 1½ oz chicken): about 9 g protein and 65 mg
  phosphorus less.
- If blood potassium is normal and the dietitian agrees, oatmeal instead of Cream of Wheat (about
  +125 mg potassium, +140 mg phosphorus and +2.7 g fibre per cup) is a fair trade for glucose
  control; the log makes the cost visible.
- **On dialysis that day would be wrong:** protein must rise to 1.0–1.2 g/kg (75–95 g for 75–80 kg),
  fluid is limited (coffee, soda and canned-fruit juice all count), and the unit's labs set potassium
  and phosphorus.

!!! tip "Changing one food"
    Each menu page ends with a list of swaps that keep the day's numbers close. For a whole dish with
    its numbers worked out, use a [recipe](../recipes/index.md) in place of a menu meal with about the
    same carbohydrate, and log it in the app to see the new day's totals.

## Sources

- [USDA FoodData Central (SR Legacy)][FDC]: every value.
- [KDOQI 2020 nutrition guideline][Q20]: energy (3.1.1) and protein (3.0.1–3.0.4).
- [KDIGO 2024 CKD guideline][K24]: protein (Rec 3.3.1.1) and sodium (Rec 3.3.2.1).
- [KDIGO 2022 diabetes in CKD guideline][K22]; [KDIGO 2009 transplant recipient guideline][K09TX] (Rec 26).
- [FDA: grapefruit juice and some drugs don't mix][FDAgrapefruit]; [FoodSafety.gov: safe minimum internal temperatures][FSTEMPS].
- [ADA Standards of Care 2026, section 5][A26-5] (consistent carbohydrate) and [section 11][A26-11] (protein).
- [AKF Kidney Kitchen: fluids][DG19a].
