# Type 1 diabetes on top of a renal diet

Research notes behind `docs/diet-guide.md`. Written 2026-10-05 from the sources listed at the end; numbers in brackets are reference numbers.

> **Superseded in part by design note 05 (v0.3; banner added 2026-10-07).** Where this note and
> [`docs/dev/research/05-personalized-targets.md`](../dev/research/05-personalized-targets.md) differ, the app
> follows note 05: **protein with diabetes at G3a–G5 is 0.8 g/kg** (a floor as well as the target: ADA 2026
> Rec 11.3, KDIGO 2022 Rec 3.1.1, KDIGO 2024 Rec 3.3.1.1; KDOQI 2020's 0.6 g/kg is for close supervision only,
> note 05 F4 and fact-check H1); **KDOQI 2020 statement numbers are the published guideline's** (3.0.1–3.0.4
> protein, 3.1.1 energy; this note first used the 2019 public-review draft's, note 05 F1); and grams per kg use a
> **reference weight** (the person's weight, moved toward the healthy BMI range when outside it, note 05 §3.1 and §4.3),
> not "ideal body weight": KDOQI 2020 leaves the choice of weight to the care team (1.1.6). The rows below are
> corrected; `tests/test_research_notes.py` keeps the old wording out.

> **Who this is for and what it is not.** These notes are for one adult with chronic kidney disease (CKD, roughly stage G3b–G4, not on dialysis) who also has type 1 diabetes (T1D) and uses insulin. They are a reading guide for conversations with the person's **nephrologist, endocrinologist/diabetes team and renal dietitian** – not a replacement for them. Every guideline cited here says the same thing: targets for protein, potassium, phosphorus, sodium and fluid are individualised from the person's own lab results, and insulin doses are set by the prescriber [1][2][3][4][6]. Where guidance changes with CKD stage or dialysis, this is called out.

## The numbers the guidelines actually give

| Nutrient | Non-dialysis CKD G3–G5 | With diabetes | On dialysis | Source |
|---|---|---|---|---|
| Protein | 0.8 g/kg/day (KDIGO 2024, 2C; ADA 2026 Rec 11.3, grade A); avoid >1.3 g/kg/day | KDOQI 2020 3.0.2: 0.6–0.8 g/kg/day for CKD 3–5 with diabetes under close supervision (opinion); KDIGO 2022 and ADA: 0.8 g/kg/day; ADA says not to go below 0.8 g/kg because doing so "does not alter blood glucose levels, cardiovascular risk measures, or the course of GFR decline"; KDIGO 2022 adds that it risks a caloric deficit and weight loss in someone also limiting carbohydrate | 1.0–1.2 g/kg/day (KDIGO 2022 PP 3.1.2; ADA 11.3 grade B) | [1][2][3][5][6] |
| Sodium | <2 g sodium/day (= <90 mmol, <5 g salt) – KDIGO 2024 Rec 3.3.2.1 (2C) | same (KDIGO 2022 Rec 3.1.2, 2C); ADA 2026: <2,300 mg/day "as clinically appropriate" | <2,300 mg/day (NKF hemodialysis diet) | [1][2][3][5][19] |
| Potassium | No fixed number. KDOQI: adjust intake to keep serum potassium normal. KDIGO 2024 PP 3.11.5.2: limit foods rich in *bioavailable* potassium (e.g. processed foods) if there is a history of hyperkalaemia | ADA: "individualization of potassium intake may be necessary". Insulin deficiency itself raises potassium (section 5) | If told to restrict: AKF says aim 2,500 mg and no more than 3,000 mg/day; DaVita quotes 2,000–3,000 mg/day | [1][3][4][13][14] |
| Phosphorus | No fixed number; adjust intake to keep serum phosphate normal (2.5–4.5 mg/dL). Avoid phosphate **additives**, which are absorbed ~90–100%; plant phosphorus is ~20–50% absorbed, animal ~40–60% (KDOQI 2020 text; Kalantar-Zadeh 2010) | same | Historically <800–1,000 mg/day; binders if diet is not enough | [4][13][15][16] |
| Fluid | Usually **not** restricted in G1–G3; may be limited in G4–G5 – ask the care team | same | Typically 1–2 L/day in-centre HD; AKF: 32 oz + urine output | [17][18][19] |
| Carbohydrate | Not a renal target; set by the diabetes plan. NKF: 1 serving = 15 g; typically 3–6 servings per meal, 1–3 per snack, individualised | consistent carbohydrate at fixed insulin doses (ADA Rec 5.28); carb counting for MDI/pump (ADA Rec 5.27) | same | [7][8] |
| Fibre | ADA: at least 14 g per 1,000 kcal | same | same | [8] |

---

## 1. How type 1 diabetes changes the renal diet

**Insulin still follows carbohydrate.** Nothing about CKD changes the fact that a person with T1D doses rapid-acting insulin against grams of carbohydrate. The ADA 2026 Standards keep carbohydrate counting as the core skill for anyone on multiple daily injections or a pump (Rec 5.27) and tell people on *fixed* insulin doses to keep "consistent patterns of carbohydrate intake with respect to time and amount" (Rec 5.28, grade B) [8]. The National Kidney Foundation's CKD-specific carb-counting page uses the same arithmetic – 15 g = 1 serving, 30 g = 2, 45 g = 3 – and suggests 3–6 servings at meals and 1–3 at snacks, adjusted by the dietitian [7].

**The practical collision.** Renal-diet swaps tend to move carbohydrate toward refined choices: white rice instead of brown, white bread instead of whole wheat, Cream of Wheat instead of oatmeal, canned fruit instead of a banana or orange, no potatoes, beans or tomatoes. Those swaps lower potassium and phosphorus but raise glycaemic load and cut fibre. USDA SR Legacy values per serving [20]:

| Grain (cooked) | Carb g | Fibre g | Protein g | K mg | P mg | Na mg |
|---|---|---|---|---|---|---|
| White rice, 1 cup | 45 | 0.6 | 4.3 | 55 | 68 | 2 |
| Brown rice, 1 cup | 52 | 3.2 | 5.5 | 174 | 208 | 8 |
| White pasta, 1 cup | 38 | 2.2 | 7.2 | 55 | 72 | 1 |
| Whole-wheat pasta, 1 cup | 35 | 4.6 | 7.0 | 112 | 149 | 5 |
| White bread, 1 slice | 14 | 0.8 | 2.6 | 37 | 28 | 142 |
| Whole-wheat bread, 1 slice | 14 | 1.9 | 4.0 | 81 | 68 | 146 |
| Oatmeal, 1 cup | 28 | 4.0 | 5.9 | 164 | 180 | 9 |
| Cream of Wheat, 1 cup | 26 | 1.3 | 3.6 | 40 | 38 | 15 |
| Corn flakes, 1 cup | 25 | 0.8 | 1.7 | 30 | 9 | 160 |
| Cheerios, 1 cup | 20 | 2.8 | 3.5 | 177 | 100 | 139 |
| Brown-rice cakes, 2 | 15 | 0.8 | 1.5 | 52 | 65 | 5 |
| Saltines (unsalted tops), 6 | 13 | 0.5 | 1.7 | 23 | 19 | 138 |
| Flour tortilla, 6 in (32 g; USDA "without added calcium" entry) | 18 | 1.1 | 2.8 | 42 | 40 | 153 |

*Tortilla caveat:* USDA's refrigerated and shelf-stable flour-tortilla entries (the ones used in `food-lists.md`) carry ~210 mg P and ~740 mg Na per 100 g from phosphate leavening and salt — about 100 mg P and 350 mg Na for a 48-g tortilla — so brands differ four-fold; read the label. A corn tortilla (11 mg Na) sidesteps the problem.

How to handle it:

1. **Whole grains are no longer automatically off the renal diet.** The phosphorus in whole grains is bound as phytate, which humans cannot digest, so its bioavailability is low (~20–50%, versus ~40–60% from meat and ~90–100% from additives; KDOQI 2020 and Kalantar-Zadeh 2010) [4][15][21]. KDIGO 2022 explicitly tells people with diabetes and CKD to eat a diet "high in vegetables, fruits, whole grains, fiber, legumes, plant-based proteins… and lower in processed meats, refined carbohydrates, and sweetened beverages" (PP 3.1.1) [2], and KDIGO 2024 repeats the plant-forward, less-ultra-processed message (PP 3.3.1) [1]. The real potassium/phosphorus budget decision is between the dietitian and the labs: brown rice costs about 120 mg K and 140 mg P more per cup than white; whole-wheat bread about 45 mg K and 40 mg P more per slice. If serum potassium and phosphate are in range, a whole-grain serving or two a day is a reasonable trade for fibre and flatter glucose.
2. **Portion the starch, do not just swap it.** A meal built around 2/3 cup white rice (30 g carb) plus a non-starchy low-potassium vegetable and a measured protein portion keeps the carbohydrate count where the insulin ratio expects it.
3. **Pair carbohydrate with the meal's allowed protein and fat** (egg, poultry, olive oil, a tablespoon of peanut butter). This is standard T1D practice to slow the glucose rise; the renal constraint is only that the protein portion is sized to the daily protein target (section 7 shows this).
4. **Get fibre from low-potassium produce**: berries, apples/applesauce, green beans, cauliflower, cabbage, cucumber, peppers, zucchini, onions (NKF's low-potassium produce list) [22].
5. **Fruit: choose by potassium, dose by carbohydrate.** USDA values per typical renal serving [20]:

| Fruit (serving) | Carb g | Fibre g | K mg | P mg |
|---|---|---|---|---|
| Applesauce, unsweetened, ½ cup | 14 | 1.3 | 90 | 6 |
| Apple, 1 cup chopped | 17 | 3.0 | 134 | 14 |
| Apple, 1 medium (3 in) | 25 | 4.4 | 195 | 20 |
| Blueberries, ½ cup | 11 | 1.8 | 57 | 9 |
| Strawberries, ½ cup halves | 6 | 1.5 | 116 | 18 |
| Raspberries, ½ cup | 7 | 4.0 | 94 | 18 |
| Blackberries, ½ cup | 7 | 3.8 | 117 | 16 |
| Cranberries, raw, ½ cup | 6 | 1.8 | 40 | 6 |
| Grapes, ½ cup (~15) | 14 | 0.7 | 145 | 15 |
| Pineapple, raw, ½ cup chunks | 11 | 1.2 | 90 | 7 |
| Pineapple, canned in juice, ½ cup | 20 | 1.0 | 152 | 8 |
| Peaches, canned in juice, ½ cup | 14 | 1.6 | 159 | 21 |
| Pears, canned in juice, ½ cup | 16 | 2.0 | 119 | 15 |
| Plum, 1 | 8 | 0.9 | 104 | 11 |
| Tangerine, 1 medium | 12 | 1.6 | 146 | 18 |
| Watermelon, 1 cup diced | 11 | 0.6 | 170 | 17 |
| Cherries, ½ cup | 12 | 1.6 | 171 | 16 |
| *Compare:* banana, small | 23 | 2.6 | **362** | 22 |
| *Compare:* orange, medium | 15 | 3.1 | **237** | 18 |
| *Compare:* cantaloupe, 1 cup diced (156 g) | 13 | 1.4 | **417** | 23 |

NKF's rule of thumb is that a food with 200 mg or more potassium per serving is "high potassium" (AKF uses 250 mg) and that "a large serving of low-potassium food can turn into a high-potassium food" [14][22][23]. Berries and applesauce are the best value: low potassium **and** low carbohydrate per cup, so a 15 g snack is a full half-cup to a cup rather than a few grapes.

---

## 2. Treating hypoglycaemia without blowing the potassium budget

**The rule of 15 does not change.** ADA 2026 Rec 6.15 (grade B): glucose is the preferred treatment for a conscious person with glucose <70 mg/dL; "15 g carbohydrates should be ingested" (5–10 g for people using automated insulin delivery), recheck in 15 minutes and repeat if still low; "avoid using foods or beverages high in fat and/or protein for initial treatment" [9]. Hypoglycaemia levels: level 1 <70 and ≥54 mg/dL; level 2 <54 mg/dL; level 3 = altered mental or physical status needing assistance [9][10]. Glucagon should be prescribed for everyone on insulin, preferably a preparation that does not need reconstitution (Rec 6.16, grade A) [9][10]. NIDDK adds: if the next meal is more than an hour away, follow with a snack [11].

NIDDK's standard 15–20 g list is: four glucose tablets or one tube of glucose gel; ½ cup (4 oz) fruit juice; ½ can (4–6 oz) regular soda; 1 tablespoon sugar, honey or corn syrup – and it adds, verbatim, "If you have kidney disease, don't drink orange juice because it has a lot of potassium" [11]. UC Davis's handout adds hard candies, jellybeans or gumdrops "see food label for how many", and 8 oz of milk [12] – milk is a poor choice in CKD (see below).

**Potassium never delays treatment.** The ranking below is about *which* 15 g to reach for when there is a choice. If the only fast carbohydrate within reach is orange juice, regular cola or milk, use it, recheck in 15 minutes, and log it: one 4-oz orange juice is ~250 mg potassium, which a day's budget can absorb, whereas untreated level 2–3 hypoglycaemia is a medical emergency. Do not under-dose (less than 15 g) and do not reach for "sugar-free" sweets because of potassium or phosphorus. Level 3 hypoglycaemia (needing another person's help) is treated with glucagon and emergency services, not with food [9][10]. The food log should record hypo treatments against the potassium budget but must never warn against or block them.

**Kidney-friendly ranking** (USDA SR Legacy per stated portion [20]; brand labels vary, so read them):

| 15 g option | Carb g | K mg | P mg | Notes |
|---|---|---|---|---|
| Glucose tablets, 4 × 4 g (e.g. Dex4) | 16 | ~0 | 0 | Fastest, no potassium or phosphorus, sodium-free; Dex4 lists 4 g dextrose per tablet, dose 4 tablets [24] |
| Glucose gel, 1 tube | 15 | ~0 | 0 | Same advantages; good for the bedside |
| Table sugar, 1 tbsp (3 tsp) | 13 | 0 | 0 | Cheap and clean; 4 tsp ≈ 17 g |
| Honey, 1 tbsp | 17 | 11 | 1 | Fine; not for infants |
| Hard candy, ~5 small pieces (3 g each) | 15 | 1 | 0 | Check label; "sugar-free" candy does **not** work (section 5) |
| Lemon-lime soda or ginger ale, 4 fl oz | 11–13 | 1 | 0 | No phosphoric acid (USDA lists 0 mg P) |
| Regular cola, 4 fl oz | 13 | 6 | ~11 | Contains phosphoric acid – a 12 oz can is ~33 mg P by USDA; direct analyses compiled by Kalantar-Zadeh et al. (CJASN 2010) and reproduced by Di Iorio et al. give ~62 mg in 12 oz Coca-Cola Classic [25]. Small and occasional is tolerable; clear soda is the better habit |
| Apple juice, ½ cup (120 mL) | 14 | **125** | 9 | Acceptable |
| Grape juice, ½ cup (120 mL) | 19 | **132** | 18 | Acceptable; slightly more carb |
| Orange juice, ½ cup (120 mL) | 13 | **248** | 21 | **Avoid** – double the potassium of apple juice for the same carb [11] |
| Milk 1%, 1 cup | 12 | **366** | **232** | **Avoid** for hypos: high K and P, and protein/fat slow absorption |
| Banana, small | 23 | **362** | 22 | **Avoid** |
| Milk chocolate bar, 1.55 oz | 26 | 164 | 92 | **Avoid**: fat slows glucose, plus K and P |

Two kidney-specific habits: keep glucose tablets or gel as the default treatment (zero potassium, zero phosphorus, exact dosing), and keep juice portions to 4 oz measured, not "a glass". Over a day with two or three lows, the difference between orange juice and glucose tablets is several hundred milligrams of potassium.

---

## 3. Insulin, hypoglycaemia and declining kidney function

*This section is background for the person and family; dose changes are for the prescriber.*

- **Insulin lasts longer when the kidneys fail.** The kidney clears a large share of injected insulin and performs about 20% of the body's gluconeogenesis; both fall as eGFR falls. The ADA/KDIGO consensus report states insulin doses "may need to be decreased in comparison with earlier stages of CKD due to reduced insulin clearance and other changes in metabolism with advanced CKD" and calls advanced CKD "a risk factor for hypoglycemia" [3]. Pecoits-Filho et al. list "decreased renal gluconeogenesis, deranged metabolic pathways (including altered metabolism of medications) and decreased insulin clearance" as the mechanisms, note that a restricted renal diet "reduces hepatic gluconeogenesis", and cite older clinician guidance of roughly a 25% total-dose reduction at GFR 10–50 mL/min and 50% below 10 mL/min; in that review glargine and detemir requirements were ~27–30% lower when GFR was <60, while degludec did not need adjustment [26]. These are prescriber decisions driven by CGM data, not something to do at home.
- **Counter-regulation is blunted.** Diabetic cardiovascular autonomic neuropathy, present in about two-thirds of people with advanced CKD in the series quoted by Pecoits-Filho, produces "hyporesponsiveness to hypoglycemia" [26]. ADA 2026 asks clinicians to screen at least annually for impaired hypoglycaemia awareness, which "dramatically increases the risk for level 3 hypoglycemia" (Rec 6.11) [9]. ADA's hypoglycaemia guidance lists kidney disease among the risks to assess at every visit [10].
- **Monitoring.** ADA recommends CGM for anyone on insulin or at high risk of hypoglycaemia [10]; KDIGO 2022 says daily CGM or self-monitoring "may help prevent hypoglycemia" when hypoglycaemia-prone drugs (insulin) are used (PP 2.1.4) [2]. ADA 2026 CGM goals: time in range 70–180 mg/dL >70%; time <70 mg/dL <4% (or <1% for older or high-risk adults); time <54 mg/dL <1% (Recs 6.3b–c) [9].
- **A1c becomes unreliable.** KDIGO 2022 PP 2.1.2: "Accuracy and precision of HbA1c measurement declines with advanced CKD (G4–G5), particularly among patients treated by dialysis, in whom HbA1c measurements have low reliability" [2]. ADA 2026 Section 11: "A1C levels are also less reliable at advanced CKD stages. Therefore, glycated albumin and fructosamine, which reflect average glycemia over a shorter time (15–30 days), are helpful" [5]; Section 6 lists anaemia, transfusion, erythropoiesis-stimulating drugs and kidney failure as factors that distort A1c and says to use SMBG, CGM "and/or the use of glycated serum protein assays" instead [9]. The mechanisms run both ways: CKD anaemia and shortened red-cell life, ESA/iron therapy and transfusion push A1c **down**; carbamylated haemoglobin from uraemia can push it **up** [26][27]. KDIGO 2022 recommends an individualised HbA1c target between <6.5% and <8.0% (Rec 2.2.1, 1C) and says CGM metrics such as time in range and time in hypoglycaemia "may be considered as alternatives to HbA1c" (PP 2.2.2), with the CGM-derived glucose management indicator (GMI) usable when A1c and finger-stick glucose disagree (PP 2.1.3) [2].

**Why this matters for the food log:** the log should record meals, carbohydrate and the CGM pattern around them; the clinic will be looking at time-in-range, not A1c, and will adjust insulin from that.

---

## 4. Dairy, milk and alternatives

Cow's milk is one of the hardest foods to fit: a cup carries both a carbohydrate serving and a large dose of potassium and phosphorus, and the phosphorus is the well-absorbed animal kind [15].

| Per 1 cup (8 oz) | Carb g | Protein g | K mg | P mg | Source |
|---|---|---|---|---|---|
| Whole milk | 12 | 7.7 | 322 | 205 | USDA [20] |
| 2% milk | 12 | 8.1 | 342 | 224 | USDA |
| 1% milk | 12 | 8.2 | 366 | 232 | USDA; DaVita quotes the same figures |
| Skim milk | 12 | 8.3 | 382 | 247 | USDA |
| Rice milk (Rice Dream Enriched Original) | ~23 | 0 | 30 | 150 | NKF table [28]; USDA generic unsweetened rice milk: 65 mg K, 134 mg P |
| Almond milk (Almond Breeze Original) | ~8 | 1 | 170 | 20 | NKF [28]; USDA generic unsweetened: 176 mg K, 24 mg P |
| Cashew milk (Elmhurst unsweetened) | – | 10 | 145 | n/a* | NKF [28] |
| Coconut milk beverage (Silk unsweetened) | ~1 | 0 | 310 | n/a* | NKF [28] |
| Soy milk (Silk Original) | ~9 | 8 | 380 | 220 | NKF [28] |
| Oat milk (Oatly Original) | ~16 | 3 | 390 | 270* | NKF [28] – *contains added phosphates |
| Half-and-half, 2 tbsp | 1 | 0.9 | 40 | 28 | USDA |

\*NKF marks these as containing added phosphates, which count as fully absorbed and may need a binder if one is prescribed [28].

Guidance:

- NKF's own position is that "most people with CKD or kidney transplant do not have to limit milk alternatives due to potassium or phosphorus unless directed by their kidney dietitian"; on haemodialysis it depends on the labs, and peritoneal dialysis patients may use higher-potassium options if they are phosphate-free [28]. The usual dietitian heuristic (DaVita): pick an "original/unsweetened" product with **no phosphate additive** and **under 200 mg potassium per 8 oz** [29].
- **Rice milk** is the lowest-potassium option but it is essentially a carbohydrate drink (~22 g per cup) with almost no protein; treat it as a starch serving when counting carbs. **Unsweetened almond milk** is the low-carb, low-phosphorus option (3–8 g carb, 20–24 mg P). **Oat milk** is the trap: as many carbs as cow's milk plus phosphate additives and ~390 mg K [28].
- **Sweetened and flavoured** versions add 10–20 g sugar per cup and often add potassium or phosphate salts; read the ingredient list for anything containing "phos" (phosphoric acid, dipotassium phosphate, tricalcium phosphate, sodium hexametaphosphate…) [16][30].
- **Creamers.** DaVita's review found dipotassium phosphate in Coffee Mate liquid and powder, International Delight (all varieties) and Silk soy creamer, and potassium citrate in Starbucks non-dairy and Silk almond creamers; one single-serve portion is small, but several per day add up. Additive-free options named include Coffee Mate Natural Bliss (dairy and almond/cashew versions) and Silk dairy-free half-and-half. Plain half-and-half or ½ cup or less of milk is also fine; black coffee itself has ~116 mg K per 8 oz [30].
- **Cheese.** Hard and processed cheeses are the phosphorus problem, not fresh ones: per ounce, cream cheese 32 mg P, ricotta (¼ cup) 49 mg, goat 72 mg, mozzarella 105 mg, Swiss 159 mg; **processed American cheese, cheese sauces and spray cheese are made with phosphate emulsifiers** – look for "phos" on the label [31]. USDA lists processed American at ~180 mg P and ~470 mg sodium per ounce [20]. Yogurt: ~145 mg P and 235 mg K per 100 g plain low-fat; a 6 oz pot is a full carb serving (12 g) plus 245 mg P [20].

---

## 5. "Sugar-free", "diabetic" and "lite" products

- **Sugar alcohols (polyols: sorbitol, xylitol, maltitol, mannitol, erythritol, isomalt, lactitol).** They are carbohydrate: the USDA entry for sorbitol "dietetic" hard candy shows 98.6 g carbohydrate per 100 g, essentially the same as regular hard candy [20]. For insulin dosing the usual teaching is to subtract **half** the grams of sugar alcohol from total carbohydrate (erythritol is often fully subtracted because it is not metabolised); Medtronic's patient guidance states the half rule and warns the result "might vary for each individual so keep a close eye on your blood glucose" [32]. ADA 2026 Rec 5.22 allows non-nutritive sweeteners in moderation as a replacement for sugar-sweetened products [8]. GI side effects set the practical ceiling: diarrhoea above roughly 50 g/day sorbitol or 20 g/day mannitol [33]. **A sugar-free candy will not treat a low** – use glucose.
- **"Diabetic" cookies, bars and shakes** frequently combine sugar alcohols with milk protein, nuts, chocolate and phosphate or potassium additives; the Nutrition Facts panel is not required to list phosphorus, so the ingredient list ("phos", "potassium") is the only clue [16][30].
- **Diet colas** still contain **phosphoric acid**; the measured values compiled by Kalantar-Zadeh et al. (2010) and reproduced by Di Iorio et al. are ~27 mg P per 12 oz for diet cola and 41–68 mg for Diet Pepsi, versus ~11 mg for Fanta [25]. Clear diet sodas (lemon-lime, ginger ale) are phosphate-free by USDA data [20]. Also check flavoured waters, bottled iced teas, sports drinks (Gatorade ~36 mg/12 oz [25]) and powdered drink mixes, which DaVita lists as unexpected phosphate sources [16].
- **Processed cheese, cheese sauces, pancake/biscuit mixes, deli meats, "enhanced" poultry** carry inorganic phosphate additives that are absorbed almost completely [15][16][31]. One ounce of processed cheese was estimated to raise serum phosphorus by about 0.07 mg/dL in the Healio summary of additive studies [34].
- **"Lite" salt and salt substitutes are potassium chloride.** Morton Lite Salt lists "Salt, Potassium Chloride…" and delivers **290 mg sodium and 350 mg potassium per ¼ teaspoon**; the label states it "should not be used by persons on a sodium or potassium restricted diet unless approved by a physician" [35]. NKF lists "salt substitutes / lite salt" among high-potassium foods [23]; the hyporeninaemic-hypoaldosteronism review for diabetic kidney disease recommends "a low-potassium diet with specific counseling against the use of potassium-containing salt substitutes" [36]; and DaVita warns to avoid "low sodium foods that contain potassium chloride" (many reduced-sodium soups, broths and deli meats) [14]. KDIGO 2024 frames this as limiting foods rich in *bioavailable* potassium – additives and processed foods – rather than fruit and vegetables [1].
- **Why potassium is a diabetes issue too.** Insulin drives potassium into cells; "the lack of insulin predisposes one to hyperkalemia" and hyperglycaemia pulls potassium into the extracellular fluid, while diabetic nephropathy is the most common cause of hyporeninaemic hypoaldosteronism [36]. ACE inhibitors, ARBs and finerenone – the drugs that protect diabetic kidneys – all raise potassium [3][36]. So a run of high glucose readings, a missed basal dose, or a new RAAS/MRA prescription are all reasons to be stricter about dietary potassium that week and to expect a lab check.
- **Star fruit (carambola) is not a "low-sugar diabetic fruit" for this person.** It contains caramboxin, a neurotoxin cleared only by the kidney; in CKD a single fruit or glass of juice can cause intractable hiccups, confusion, seizures and death. Never eat it or its juice at any CKD stage (details and sources in `ckd-diet.md` §5 and `food-lists.md` C4).

---

## 6. Sodium, blood pressure, cardiovascular risk, alcohol and fluid

- **Sodium.** KDIGO 2024 (and KDIGO 2022 for diabetes) suggest <2 g sodium/day (<90 mmol, <5 g salt) in CKD (2C) [1][2]. ADA 2026 counsels <2,300 mg/day "as clinically appropriate" and notes the best way to get there is limiting processed foods (Rec 5.20); in the CKD section it says "restriction of dietary sodium (to <2,300 mg/day) may be useful to manage blood pressure" and that "medical nutrition therapy by a registered dietitian nutritionist is highly successful in achieving the sodium and protein intake goals" [5][8]. For the log: bread, deli turkey, crackers, cheese, mayonnaise and canned soup are where the sodium is; in the sample day below, two slices of bread and a tablespoon of mayonnaise are 370 mg on their own.
- **Blood pressure.** ADA 2026 Rec 11.5 (grade A): on-treatment goal <130/80 mmHg, with a systolic goal <120 mmHg where tolerated [5]; ADA/KDIGO: the low-sodium diet exists "largely to control BP and reduce cardiovascular risk" [3]. Nephrology nurse-practitioner Kathryn Wells (NKF podcast): "where salt is, water is" – sodium drives thirst and fluid retention [18].
- **Cardiovascular risk.** The 2026 Standards reposition cardiovascular and kidney protection as co-equal with glucose control: SGLT2 inhibitors (eGFR ≥20), GLP-1 receptor agonists and finerenone (eGFR ≥25) carry grade A recommendations in CKD [5]; KDIGO 2024 recommends statins for adults ≥50 with eGFR <60 and a plant-based "Mediterranean-style" diet alongside lipid therapy [1]. For diet that means the heart-healthy pattern (unsaturated fats, plant protein, little processed meat) is the same pattern the kidney guidelines ask for.
- **Alcohol.** ADA 2026: no more than 1 drink/day for women and 2 for men (Rec 5.18) and specific counselling on **delayed hypoglycaemia** with insulin (Rec 5.19) [8]. DaVita's CKD guidance: moderate drinking "may be okay" for people not on dialysis but only after checking with the nephrologist or renal dietitian; on dialysis it must fit inside the fluid allowance; with diabetes drink only with food because "alcohol on an empty stomach can cause blood sugar levels to drop" [37]. Beer and wine also carry phosphorus (beer 110–280 mg/L, red wine ~300 mg/L in Di Iorio's compilation) and beer has carbohydrate [25].
- **Fluid.** There is no fluid restriction in the guidelines for G1–G3. AKF: in stages 3–5 "you may need to limit the amount of fluid you consume. Ask your doctor and dietitian" [17]. Wells: "it's pretty rare for me to have to do that in clinic until we are at the point of starting dialysis" [18]. On in-centre haemodialysis the restriction is typically 1–2 L/day (NKF) or "32 ounces plus the volume equal to the amount you urinate in 24 hours" (AKF), and anything liquid at room temperature counts – ice, soup, gelatin, ice cream [17][19]. Swelling, breathlessness lying flat or climbing stairs are the warning signs to report [17].

---

## 7. A worked sample day (CKD G3b–G4 + T1D, not on dialysis)

Assumptions: ~75–80 kg adult, protein target 0.8 g/kg (≈60–64 g/day), carbohydrate ~45 g at meals and ~15 g at snacks (adjust to the person's insulin plan), potassium under ~2,500–3,000 mg (the AKF goal when a restriction is prescribed [13]; the project's review ceilings in `docs/research/ckd-diet.md` are 3,500 mg at G3b and 3,000 mg at G4, so this day is built to fit even the strictest common prescription), phosphorus under ~800–1,000 mg (the KDOQI 2003 range; `ckd-diet.md` default 1,000 mg), sodium under ~2,000 mg, no fluid restriction. All values are USDA SR Legacy [20], computed from gram weights; brands will differ, so the log should use label values when available. Nutrient columns: **Carb g | Protein g | K mg | P mg | Na mg**.

**Breakfast** – ~46 g carb

| Food | Carb | Prot | K | P | Na |
|---|---|---|---|---|---|
| Cream of Wheat, cooked without salt, ¾ cup | 20 | 2.7 | 30 | 28 | 11 |
| Blueberries, ½ cup | 11 | 0.5 | 57 | 9 | 1 |
| Egg, hard-boiled, 1 large | 1 | 6.3 | 63 | 86 | 62 |
| White toast, 1 slice | 14 | 2.6 | 37 | 28 | 142 |
| Unsalted butter, 1 pat | 0 | 0 | 1 | 1 | 1 |
| Coffee, 8 fl oz | 0 | 0.3 | 116 | 7 | 5 |
| Half-and-half, 1 tbsp | 1 | 0.5 | 20 | 14 | 9 |
| **Meal** | **46** | **13** | **324** | **174** | **231** |

**Morning snack** – ~17 g carb: unsweetened applesauce ½ cup + unsalted peanut butter 1 tbsp → 17 | 4 | 180 | 60 | 5

**Lunch** – ~46 g carb

| Food | Carb | Prot | K | P | Na |
|---|---|---|---|---|---|
| White bread, 2 slices | 29 | 5.1 | 73 | 57 | 284 |
| Roast turkey breast (not deli, no added solution), 1.5 oz | 0 | 13.0 | 107 | 99 | 43 |
| Mayonnaise, 1 tbsp | 0 | 0.1 | 3 | 3 | 89 |
| Iceberg lettuce, 1 cup shredded | 2 | 0.6 | 102 | 14 | 7 |
| Cucumber, ½ cup slices | 2 | 0.3 | 76 | 12 | 1 |
| Pineapple canned in juice, ⅓ cup | 13 | 0.3 | 101 | 5 | 1 |
| **Meal** | **46** | **20** | **462** | **191** | **425** |

**Afternoon snack** – ~14 g carb: 6 unsalted-top saltines + 1 tbsp cream cheese → 14 | 3 | 42 | 34 | 183

**Dinner** – ~42 g carb

| Food | Carb | Prot | K | P | Na |
|---|---|---|---|---|---|
| Chicken breast, roasted, 2 oz | 0 | 17.7 | 146 | 130 | 42 |
| White rice, cooked, ⅔ cup | 30 | 2.8 | 37 | 45 | 1 |
| Green beans, boiled, 1 cup | 10 | 2.4 | 182 | 36 | 1 |
| Cauliflower, boiled, ½ cup | 3 | 1.1 | 88 | 20 | 9 |
| Olive oil, 1 tbsp | 0 | 0 | 0 | 0 | 0 |
| **Meal** | **42** | **24** | **453** | **231** | **54** |

**Evening snack** – ~14 g carb: peaches canned in juice, ½ cup → 14 | 1 | 159 | 21 | 5

**Day totals:** carbohydrate **179 g** (five carb-counting events of 14–46 g), protein **64 g** (0.8 g/kg for 80 kg), potassium **1,620 mg**, phosphorus **711 mg** (almost all of it natural, none from additives), sodium **903 mg**, fibre 17 g, energy ~1,470 kcal.

Notes on the day:

- **It is deliberately light on calories.** KDOQI 2020 energy guidance is 25–35 kcal/kg body weight/day (Statement 3.1.1, 1C; ≈1,900–2,800 kcal for 75–80 kg) [4]; the Kalantar-Zadeh & Fouque NEJM 2017 table reproduced by AKF uses 30–35 kcal/kg [13]. At ~1,470 kcal this day is 400–500 kcal under even the KDOQI floor. The gap should be closed with fats (another tablespoon of olive oil, butter, mayonnaise, a second tablespoon of peanut butter) or more measured starch covered by insulin – not with more meat, which would push protein and phosphorus up. The sodium headroom (~1,100 mg) and potassium headroom (~900–1,400 mg, depending on the prescribed ceiling) also leave room for seasoning and a second vegetable.
- **To fit a smaller person, or a lower amount your care team prescribes and supervises (KDOQI 3.0.2: 0.6–0.8 g/kg)**, shrink the meat portions (1 oz turkey, 1.5 oz chicken) – that alone removes ~12 g protein and ~90 mg phosphorus.
- **Hypo treatment is on top of this.** Two 15 g lows treated with glucose tablets add 0 mg potassium; treated with 4 oz apple juice they add ~250 mg; with 4 oz orange juice ~500 mg – which is why the app should log hypo treatments as foods.
- **If serum potassium is normal and the dietitian agrees**, swapping the Cream of Wheat for oatmeal (+134 mg K, +142 mg P, +2.7 g fibre per cup) or the white rice for brown is a defensible trade for glucose control; the log makes the cost visible.
- **On dialysis this day would be wrong**: protein would need to rise to 1.0–1.2 g/kg (75–95 g), fluid would be capped (coffee, soda and canned-fruit liquid all count), and potassium and phosphorus limits would come from the dialysis unit's labs [2][5][17][19].

---

## Sources

1. KDIGO. *KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of Chronic Kidney Disease.* Kidney Int 2024;105(4S):S117–S314. Recs 3.3.1.1 (protein 0.8 g/kg, 2C), 3.3.2.1 (sodium <2 g, 2C); PP 3.3.1 (diet pattern), 3.3.2 (renal dietitians), 3.11.5.1–2 (hyperkalaemia and bioavailable potassium), 3.15.1.x (statins). https://kdigo.org/guidelines/ckd-evaluation-and-management/
2. KDIGO. *KDIGO 2022 Clinical Practice Guideline for Diabetes Management in Chronic Kidney Disease.* Kidney Int 2022;102(5S):S1–S127. Rec 2.1.1, PP 2.1.2–2.1.4, Rec 2.2.1, PP 2.2.2, PP 3.1.1–3.1.2, Rec 3.1.1–3.1.2. https://kdigo.org/wp-content/uploads/2023/12/KDIGO-2022-Diabetes-Guideline.pdf
3. de Boer IH, Khunti K, Sadusky T, et al. *Diabetes Management in Chronic Kidney Disease: A Consensus Report by the ADA and KDIGO.* Diabetes Care 2022;45(12):3075–3090. https://pmc.ncbi.nlm.nih.gov/articles/PMC9870667
4. Ikizler TA, Burrowes JD, Byham-Gray LD, et al. *KDOQI Clinical Practice Guideline for Nutrition in CKD: 2020 Update.* Am J Kidney Dis 2020;76(3 Suppl 1):S1–S107. https://doi.org/10.1053/j.ajkd.2020.05.006 – protein 0.6–0.8 g/kg/day for CKD 3–5 with diabetes, 1.0–1.2 g/kg/day on dialysis, electrolytes adjusted to serum levels, as reproduced in the ISRNM endorsement: Kistler BM et al., J Ren Nutr 2021, https://pmc.ncbi.nlm.nih.gov/articles/PMC8045140
5. American Diabetes Association Professional Practice Committee. *11. Chronic Kidney Disease and Risk Management: Standards of Care in Diabetes—2026.* Diabetes Care 2026;49(Suppl 1):S246–S260. Recs 11.3 (protein, sodium, potassium), 11.4 (glycaemia), 11.5 (BP), 11.7–11.8 (SGLT2i, GLP-1 RA, nsMRA). https://pmc.ncbi.nlm.nih.gov/articles/PMC12690176
6. National Kidney Foundation. *National Kidney Foundation, Academy of Nutrition and Dietetics Release KDOQI Clinical Practice Guidelines on Nutrition* (press release, 2020). https://www.kidney.org/news/national-kidney-foundation-releases-clinical-practice-guidelines-nutrition
7. National Kidney Foundation. *Carbohydrate Counting with Chronic Kidney Disease.* https://www.kidney.org/kidney-topics/carbohydrate-counting-chronic-kidney-disease
8. American Diabetes Association Professional Practice Committee. *5. Facilitating Positive Health Behaviors and Well-being to Improve Health Outcomes: Standards of Care in Diabetes—2026.* Diabetes Care 2026;49(Suppl 1):S89–S131. Recs 5.10, 5.18–5.20, 5.22, 5.24, 5.27–5.28. https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188
9. American Diabetes Association Professional Practice Committee. *6. Glycemic Goals, Hypoglycemia, and Hyperglycemic Crises: Standards of Care in Diabetes—2026.* Diabetes Care 2026;49(Suppl 1):S132–S149. Recs 6.3b–c, 6.11, 6.15, 6.16; Table 6.4. https://pmc.ncbi.nlm.nih.gov/articles/PMC12690178
10. American Diabetes Association. *Hypoglycemia* (Guidelines InSIGHT infographic based on Standards of Care 2025). https://professional.diabetes.org/sites/dpro/files/2025-05/hypoglycemia-hcp-5-27-25.pdf
11. NIDDK. *Low Blood Glucose (Hypoglycemia).* https://www.niddk.nih.gov/health-information/diabetes/overview/preventing-problems/low-blood-glucose-hypoglycemia
12. UC Davis Health. *Diabetes: Hypoglycemia* (patient handout). https://health.ucdavis.edu/media-resources/health-education/documents/pdfs/diabeteshypoglycemia.pdf
13. American Kidney Fund. *Potassium and kidney disease* (handout; includes the Kalantar-Zadeh & Fouque, N Engl J Med 2017 dietary-approach table). https://www.kidneyfund.org/sites/default/files/media/documents/potassium-and-kidney-disease_0.pdf
14. DaVita Kidney Diet Tips. *High potassium foods to limit on the kidney diet.* https://www.davita.com/diet-nutrition/kidney-diet-tips/high-potassium-foods-to-limit-on-the-kidney-diet
15. DaVita Kidney Diet Tips. *What's the scoop on whole grains?* https://www.davita.com/diet-nutrition/kidney-diet-tips/whats-scoop-whole-grains/
16. DaVita Kidney Diet Tips. *Phosphorus update: and you thought dark colas were bad news.* https://www.davita.com/diet-nutrition/kidney-diet-tips/thought-dark-colas-bad-news/
17. American Kidney Fund, Kidney Kitchen. *Fluids* and *Kidney disease stages 3, 4 and 5 (not on dialysis).* https://kitchen.kidneyfund.org/fluids/ ; https://kitchen.kidneyfund.org/eating-healthy-with-kidney-disease/kidney-disease-stages-3-4-5-not-on-dialysis/
18. National Kidney Foundation. *Hot Topics in Kidney Health, episode 1x28* (transcript; Kathryn Wells, NP). https://www.kidney.org/content/transcript-hot-topics-kidney-health-episode-1x28
19. National Kidney Foundation. *Hemodialysis and Your Diet.* https://www.kidney.org/kidney-topics/hemodialysis-and-your-diet
20. USDA Agricultural Research Service. *FoodData Central, SR Legacy (April 2018 release).* https://fdc.nal.usda.gov/download-datasets – values computed from the CSV release using USDA portion weights.
21. Moe SM, Zidehsarai MP, Chambers MA, et al.; and Noori N et al. on phytate-bound phosphorus; summarised in *Whole grains in the renal diet—is it time to reevaluate their role?* Blood Purif 2014 (PubMed 24496192) and *Plant-based whole-grain foods for CKD: the phytate-phosphorus conundrum* (PubMed 34192744).
22. National Kidney Foundation. *40 Low Potassium Fruits and Vegetables to Add to Your Grocery List.* https://www.kidney.org/news-stories/40-low-potassium-fruits-and-vegetables-to-add-to-your-grocery-list
23. National Kidney Foundation. *Potassium and Your CKD Diet.* https://www.kidney.org/atoz/content/potassium
24. American Diabetes Association Consumer Guide. *Dex4 Tablets* (4 g per tablet; dose 4 tablets). https://consumerguide.diabetes.org/products/dex4-tablets
25. Di Iorio B, Di Micco L, Torraca S, Sirico ML. *Phosphorus, beverages, and chronic kidney disease.* Nutrition and Dietary Supplements 2012;4:55–59. https://www.dovepress.com/article/download/11303 — a review; its beverage table reproduces measured values from Kalantar-Zadeh K et al., Clin J Am Soc Nephrol 2010;5:519–530 (in turn from Murphy-Gutekunst L, J Ren Nutr 2005): Coca-Cola Classic ~62 mg/12 oz (172 mg/L), diet cola ~27 mg, Gatorade ~36 mg. Di Iorio did not measure these themselves.
26. Pecoits-Filho R, Abensur H, Betônico CCR, et al. *Interactions between kidney disease and diabetes: dangerous liaisons.* Diabetol Metab Syndr 2016;8:50. https://pmc.ncbi.nlm.nih.gov/articles/PMC4964290/
27. diaTribe. *Your A1C May Not Be Reliable If You Have Chronic Kidney Disease.* https://diatribe.org/understanding-diabetes/your-a1c-may-not-be-reliable-if-you-have-chronic-kidney-disease
28. National Kidney Foundation. *Milk Alternatives.* https://www.kidney.org/kidney-topics/milk-alternatives
29. DaVita Kidney Diet Tips. *Lower potassium and phosphorus dairy alternatives* and *Choosing the best milk substitute.* https://www.davita.com/diet-nutrition/kidney-diet-tips/dairy-alternatives/
30. DaVita Kidney Diet Tips. *Food Facts Friday: Coffee Creamers.* https://www.davita.com/diet-nutrition/kidney-diet-tips/food-facts-friday-coffee-creamers
31. National Kidney Foundation. *Low-Phosphorus Cheese.* https://www.kidney.org/kidney-topics/low-phosphorus-cheese
32. Medtronic MiniMed. *Net carbs vs. total carbs: what counts?* https://www.minimed.com/en-us/loop-blog/net-carbs-vs-total-carbs-counts
33. University of Illinois Extension. *Sugar Alcohols and Diabetes.* https://extension.illinois.edu/diabetes/sugar-alcohols-and-diabetes
34. Healio Nephrology. *Foods with added phosphate cause spike in blood levels* (2018). https://www.healio.com/news/nephrology/20180227/foods-with-added-phosphate-cause-spike-in-blood-ev
35. Morton Salt. *Morton Lite Salt* (label: ingredients, 290 mg sodium / 350 mg potassium per ¼ tsp, physician warning). https://www.mortonsalt.com/home-product/morton-lite-salt/
36. Sousa AGP, Cabral JVS, El-Feghaly WB, et al. *Hyporeninemic hypoaldosteronism and diabetes mellitus: pathophysiology assumptions, clinical aspects and implications for management.* World J Diabetes 2016;7(5):101–111. https://www.wjgnet.com/1948-9358/full/v7/i5/101.htm
37. DaVita. *Alcohol and Chronic Kidney Disease.* https://www.davita.com/diet-nutrition/articles/alcohol-and-chronic-kidney-disease/
