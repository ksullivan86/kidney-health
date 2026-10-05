# 05 · Personalised daily targets: age, sex, body weight, labs and treatment

| | |
|---|---|
| Status | Decision note, proposed for v0.3. No application code has been changed. Adversarial clinical fact-check applied 2026-10-05: 1 high, 6 medium, 15 low findings, all fixed or flagged in place; see [§10](#10-fact-check). |
| Date researched | 2026-10-05 |
| Scope | Which personal factors should change the **suggested** daily targets (energy, protein, carbohydrate, fibre, sodium, potassium, phosphorus, calcium, fluid) for adults with CKD G1–G5, hemodialysis (HD), peritoneal dialysis (PD) or a kidney transplant, with or without type 1 diabetes. Exact inputs, formulas, decision table, note texts, rule catalogue with sources and grades, eGFR (CKD-EPI 2021) and albuminuria categories, lab unit conversion, test vectors. |
| Out of scope | Insulin dosing, glycaemic targets, pregnancy and breastfeeding, people under 18 (all refused, F14 and §4.4), the AI layer (it may *explain* these rules but never changes a number, §6), the multi-user and settings storage model (sibling notes own it; this note only names the fields and keys it needs). |
| Re-verify | KDIGO 2026 Diabetes-in-CKD final text (draft only as of today), ADA Standards 2027 (Dec 2026), any KDOQI nutrition update, NASEM DRI revisions. See [§8](#8-how-to-re-verify). |

**Marking used in this note.** Evidence grades are quoted exactly as the source gives them: KDIGO and
KDOQI `1` = recommend, `2` = suggest, `A`–`D` = certainty, `OPINION` = KDOQI expert opinion,
*PP* = KDIGO practice point (ungraded expert judgement); ADA `A`/`B`/`C`/`E`; ESPEN `A`/`B`/`0`/`GPP`.
NASEM Dietary Reference Intakes (DRIs) are reference values and have no grade. Anything that is
this project's own choice is marked **[OPINION]**. A guideline grade on a range does not make the
app's pick of a number inside that range evidence-based.

---

## 1. Context

### 1.1 The ask

> "also for the suggested levels idk if age or sex should have any affect on this? if so they should
> be factors (along with anything else)"

The wider v0.3 brief says insights must work **without AI**, the project will be public, and every
rule must be documented so another person or AI can pick it up.

### 1.2 What exists today (v0.2), read from the repository

* `app/nutrients.py::suggest_targets(weight_kg, ckd_stage, dialysis, diabetes, height_cm=None)`
  returns `{"targets", "notes"}`. Inputs are weight, optional height, stage `1`–`5`, dialysis
  `none|hemodialysis|peritoneal` and diabetes `none|type1|type2`. There is **no** age, sex, activity,
  lab, transplant or pregnancy input.
* `dosing_weight()` clamps the weight to the healthy BMI band (BMI 25 weight if above, BMI 18.5
  weight if below) and calls the result "ideal body weight". The notes cite "KDOQI 2020 3.0.1"
  for 25–35 kcal/kg and "3.1.1–3.1.4" for protein.
* Fixed numbers: 30 kcal/kg, carbohydrate 45 % of energy, sodium 2000 mg, calcium 1000 mg, a
  potassium ladder by stage, phosphorus 1000 (900 at G5), fluid only on dialysis. They match
  `docs/research/targets_by_stage.json`, and `tests/test_nutrients.py` compares the two row by row.
* `app/static/app.js` has a **JavaScript mirror** of `dosingWeight()` and `suggestTargets()` for
  the preview/demo build ("notes word for word"). Any change must be made in both places.
* `fiber_g` is a registered nutrient but no target is suggested for it.
* Targets are never auto-saved. The person presses **Save profile** after review.

### 1.3 Constraints that shape the answer

* Rules are **pure functions** with no I/O, deterministic and testable. That is the "without AI"
  requirement.
* Every suggestion is a *starting point* that the care team overwrites. The app must never look
  like it prescribes.
* v0.3 becomes multi-user. Age, sex and labs are health data (note 01 asset A1), so collect the
  minimum: birth **month**, not birth date.

---

## 2. Findings

### F1. The app cites the 2019 *draft* of KDOQI 2020, not the published guideline

The repository cites the October 2019 public-review draft (`kidney.org/.../Public_Review_Copy.pdf`).
The published guideline (AJKD 2020;76(3 Suppl 1):S1–S107) differs in three ways that matter here.
All three were checked against the typeset AJKD PDF:

| | Public-review draft (Oct 2019) | **Published AJKD 2020** |
|---|---|---|
| Statement numbers | 3.0.1 energy; 3.1.1–3.1.4 protein | **3.0.1–3.0.4 protein; 3.1.1 energy** |
| Weight basis | "kg **ideal** body weight" in 3.0.1, 3.1.1–3.1.4 | "**kg body weight**" everywhere; the weight is left to clinical judgement (1.1.6, OPINION) |
| Diabetes, CKD 3–5 | 3.1.3: 0.8–0.9 g/kg (OPINION) | **3.0.2: 0.6–0.8 g/kg** "under close clinical supervision" (OPINION) |

The published text says: *"Because the body weight suggested (whether IBW, BMI, usual or current, or
adjusted) depends on clinician judgment related to the patient's health goals (Guideline Statement
1.1.6), the specific weight formula used for prescription should be personalized to the patient."*
The app's numbers (0.6–0.8) are already the published ones (but see F4 and fact-check H1: for diabetes the v0.3 floor becomes 0.8). Only the **statement numbers** and the
claim that KDOQI *requires* ideal body weight are wrong. v0.3 must fix the note texts, the JSON
notes, `ARCHITECTURE.md` and `docs/diet-guide.md` §7–§8 (checklist C1).

### F2. Body weight: what KDOQI actually offers, and why sex does not need to enter it

* **KDOQI 2020 1.1.6 (OPINION):** clinicians choose the weight. Options include actual weight,
  weight history, serial weights, and adjustments for oedema, ascites and polycystic organs.
* **KDOQI 2020 Table 5, "Measuring body weight"**, lists:
  * **Hamwi IBW**: women 45.36 kg for the first 5 ft plus 2.27 kg per inch; men 48.08 kg plus
    2.72 kg per inch; ±10 % for frame. The table's "5'0" (127 cm)" is a typo for **152.4 cm**.
    KDOQI's caution: Hamwi *"has no scientific data to support its use"*.
  * **Desirable BW, "based on body mass index"**.
  * **Adjusted BW** (Karkeck) = IBW + 0.25 × (actual − IBW). It rests on the theory that 25 % of
    excess weight is metabolically active. Caution: *"not validated for use in CKD and may either
    over- or underestimate energy and protein requirements."*
  * **KDOQI 2000 adjusted oedema-free BW**: if weight is < 95 % or > 115 % of standard BW, use
    oedema-free BW + 0.25 × (standard BW − oedema-free BW). For an obese person this keeps 75 % of
    the excess, which is very different from Karkeck's 25 % (example in §3.1).
  * **Oedema-free BW**, which equals dry weight on dialysis.
* Other KDOQI points:
  * Use WHO BMI categories, with lower cut-offs possible for Asian populations.
  * BMI < 18 kg/m² alone is enough to establish protein-energy wasting (PEW) (1.1.11, OPINION).
  * Overweight or obesity predicts **lower** mortality on maintenance HD, while underweight and
    morbid obesity predict higher mortality (1.1.8, 2B). Obesity may raise mortality in dialysis
    patients **younger than 65**.
  * On dialysis, Table 5 calls oedema-free weight *"analogous to estimated dry weight"*, so the
    app asks for the post-dialysis (dry) weight. (KDOQI's own "postdialysis" wording is about
    bioimpedance, not weighing.)
* **Sex-specific IBW formulas give different BMIs at the same height.** Hamwi, Devine and Robinson
  imply BMI about 20–24.5 for men and 19–22 for women, and they drift at short and tall heights (table in
  §3.1). Peterson et al. (AJCN 2016) showed this and proposed defining target weight directly from
  BMI, *"which avoids the overestimation and underestimation problems at the upper and lower ends
  of the height spectrum"*. A BMI-based reference weight is listed by KDOQI (Desirable BW), is
  sex-neutral, and also works when sex is not given.

### F3. Energy: age, sex and activity do matter, and there is a validated equation

* **KDOQI 2020 3.1.1:** in CKD 1–5D (**1C**) and post-transplant (OPINION), when metabolically
  stable, energy is *"25–35 kcal/kg body weight per day based on age, sex, level of physical
  activity, body composition, weight status goals, CKD stage, and concurrent illness or presence of
  inflammation"*. The rationale adds that 30–35 kcal/kg keeps neutral nitrogen balance, and that
  needs in earlier CKD *"may not be substantially different than for healthy adults"*.
* **KDOQI 1.4.2 (2C):** for CKD 5D without indirect calorimetry, disease-specific equations (for
  example MHDE) may estimate *resting* energy expenditure. MHDE needs CRP, creatinine and HbA1c, and
  a 2022 analysis found current dialysis equations imprecise ([PMC8979515](https://pmc.ncbi.nlm.nih.gov/articles/PMC8979515/)).
* **NASEM 2023 DRIs for Energy** give total energy expenditure (TEE) equations derived from doubly
  labelled water, by sex, age, height, weight and four physical activity level (PAL) categories.
  Table S-1, adults 19+, kcal/day, age in years, height in cm, weight in kg:

  | PAL category | Men | Women |
  |---|---|---|
  | Inactive | 753.07 − 10.83·age + 6.50·ht + 14.10·wt | 584.90 − 7.01·age + 5.72·ht + 11.71·wt |
  | Low active | 581.47 − 10.83·age + 8.30·ht + 14.94·wt | 575.77 − 7.01·age + 6.60·ht + 12.14·wt |
  | Active | 1004.82 − 10.83·age + 6.52·ht + 15.91·wt | 710.25 − 7.01·age + 6.54·ht + 12.34·wt |
  | Very active | −517.88 − 10.83·age + 15.61·ht + 19.11·wt | 511.83 − 7.01·age + 9.07·ht + 12.56·wt |

  * Error: RMSE 339 kcal/day for men and 246 kcal/day for women.
  * Adult PAL ranges: inactive 1.0–<1.53; low active 1.53–<1.68; active 1.68–<1.85; very active
    1.85–<2.50.
  * Table 7-1 gives everyday examples. Inactive is daily living only (which already includes about
    30 min of walking and 90 min of light household activity). Low active adds 60–80 min of
    walking at 3–4 mph. Active adds 30–50 min of walking plus about 85 min of cycling and doubles
    tennis. Very active adds more than 2 h of vigorous activity (cycling, jogging, tennis).
  * The 2023 DRI population is now *"the general population, including those with overweight,
    obesity, and chronic diseases"*.
* **ESPEN 2022 geriatrics R1 (Grade B):** about 30 kcal/kg for older persons, individually
  adjusted. The commentary gives 27–30 kcal/kg as the minimum for ill older people and 32–38 for
  underweight older people (BMI ≤ 21).
* **KDOQI 2000** (secondary source): 35 kcal/kg under 60 years, 30–35 kcal/kg at 60 and over, for
  advanced CKD and dialysis. KDOQI 2020 replaced this with the 25–35 range.

### F4. Protein: age and frailty matter; sex does not (per kg)

| Source | Statement | Grade |
|---|---|---|
| KDOQI 2020 3.0.1 | CKD 3–5, metabolically stable, no diabetes: 0.55–0.60 g/kg, or 0.28–0.43 plus keto-analogues, under close supervision | 1A (ESKD/death) |
| KDOQI 2020 3.0.2 | CKD 3–5 **with diabetes**: 0.6–0.8 g/kg under close supervision | OPINION |
| KDOQI 2020 3.0.3 | Dialysis, metabolically stable, no diabetes: 1.0–1.2 g/kg, graded **1C on HD** and **OPINION on PD** within the same statement | 1C (HD) / OPINION (PD) |
| KDOQI 2020 3.0.4 | Dialysis **with diabetes**: 1.0–1.2 g/kg; higher if at risk of hyper- or hypoglycaemia | OPINION |
| KDOQI 2020 definition | "Metabolically stable" = no active inflammation or infection, no hospitalisation within 2 weeks, no poorly controlled diabetes, no consumptive disease, **no antibiotics or immunosuppressive medications**, no significant short-term weight loss | – |
| KDIGO 2024 Rec 3.3.1.1 | 0.8 g/kg/day in adults with CKD G3–G5 | 2C |
| KDIGO 2024 PP 3.3.1.1 / 3.3.1.3 | Avoid > 1.3 g/kg if at risk of progression / no low-protein diet if metabolically unstable | PP |
| **KDIGO 2024 PP 3.3.1.5** | *"In older adults with underlying conditions such as frailty and sarcopenia, consider higher protein and calorie dietary targets."* The rationale says geriatric guidelines give 1.0–1.2 g/kg, which *"may be appropriate in some people with stable or slowly progressing CKD"*, while protein restriction *"may be appropriate in older adults whose primary clinical challenge is CKD with significant progression"* | PP |
| KDIGO 2022 Rec 3.1.1 / PP 3.1.2 | Diabetes and CKD not on dialysis: 0.8 g/kg (2C). HD, *"particularly peritoneal dialysis"*: 1.0–1.2 (PP) | 2C / PP |
| ADA 2026 Rec 11.3 | *"For people with CKD stage G3 or higher, protein intake should be 0.8 g/kg body weight per day, as for the general population"* (A); on dialysis 1.0–1.2 *"should be considered"* (B). The section text adds: *"In people with CKD and diabetes, consuming protein below the recommended daily allowance of 0.8 g/kg/day is not recommended"* | A / B |
| ADA 2026 Rec 13.11a (older adults) | *"Recommend healthful eating with adequate protein intake (at least 0.8 g/kg body weight/day) for older adults with diabetes to maintain and potentially higher, individualized amounts to regain lean body mass and function"* | B |
| ESPEN 2022 R2 | Older persons: **≥ 1.0 g/kg/day** | B |
| PROT-AGE 2013 | Over 65: 1.0–1.2 g/kg; 1.2–1.5 with acute or chronic disease; *exception:* eGFR < 30 not on dialysis *"may need to limit protein intake"* | consensus |
| KDOQI 2000 (secondary) | HD 1.2 g/kg; PD 1.2–1.3 g/kg | – |
| CARI 2010, transplant (via two reviews) | About 1.4 g/kg for the first 4 weeks after transplant; long term about 0.75 (women) to 0.8 (men) g/kg; *"There are currently no agreed guidelines"* (Transplant Int 2025) | – |

**Trap for contributors.** The *Dietary Guidelines for Americans 2025–2030* (released 2026-01-07)
recommend 1.2–1.6 g protein/kg/day for the general public. **This must not be applied to CKD.**
KDIGO PP 3.3.1.1 says to avoid more than 1.3 g/kg when CKD is at risk of progression.

**Diabetes and the 0.6 g/kg floor (fact-check finding H1).** Only KDOQI 2020 3.0.2 goes below
0.8 g/kg for diabetes, as OPINION and only *"under close clinical supervision"* in people who are
"metabolically stable", a definition that excludes *"poorly controlled diabetes"*. KDIGO 2022 Rec
3.1.1 (2C), KDIGO 2024 Rec 3.3.1.1 (2C) and ADA 2026 Rec 11.3 (A) all say 0.8 g/kg, and ADA says
going below it is *"not recommended"* with diabetes. The app cannot see supervision or glycaemic
stability, so its unsupervised default for diabetes at G3–G5 is **0.8 g/kg** (§4.3, P-2). Lower
numbers stay possible as care-team targets entered by hand.

The ADA 2026 Section 13 text (PMC12690186) was re-fetched during the fact-check: the older-adult
protein statement is **Rec 13.11a, grade B** (quoted above).

### F5. Sodium: no age or sex effect

KDIGO 2024 Rec 3.3.2.1 (2C) gives < 2 g/day for people with CKD. KDOQI 2020 6.5.1 gives < 2.3 g
(1B for CKD 3–5, 1C for 5D and post-transplant). NASEM 2019 sets the adult sodium Adequate Intake
(AI) at 1500 mg and the Chronic Disease Risk Reduction intake (CDRR) at "reduce if above 2300 mg"
for **every** adult age and sex group. The only exceptions are clinical: sodium-wasting
nephropathy (KDIGO PP 3.3.2.1), extreme heat and malnutrition. Those stay notes, not inputs.

### F6. Potassium: the lab decides; sex only changes a healthy-population AI that does not apply

* **KDOQI 2020 6.4.1 (OPINION):** adjust dietary potassium to keep serum potassium normal.
  **6.4.2 (2D):** with hyper- or hypokalaemia, base intake on individual needs.
* **KDIGO 2024 PP 3.11.5.2:** limit foods rich in *bioavailable* potassium (processed foods) for G3–G5
  with a **history** of hyperkalaemia, or when hyperkalaemia risk is a concern.
* KDIGO 2024 defines hyperkalaemia prevalence at **> 5.0 mmol/L**. Figure 32 lists actions at
  **> 5.5** (first line: assess dietary potassium, dietitian referral). Table 28 (from UK Kidney
  Association / Think Kidneys) calls **6.0–6.4 moderate** (repeat within 24 h, hospital if unwell)
  and **≥ 6.5 severe** (immediate action).
* KDIGO 2024 Table 24 shows mean serum potassium differs by 0.2 mmol/L or less between sexes and
  age groups (< 65, ≥ 65) at the same eGFR. **Thresholds do not need an age or sex term.**
* **NASEM 2019:** potassium AI is 3400 mg (men) and 2600 mg (women), unchanged with age. DRIs are
  *"for the apparently healthy population"*. The AI is an adequacy floor for healthy kidneys, not
  a ceiling for CKD. **Rejected as a target.**
* The v0.2 ladder (4000 → 3500 → 3000 → 2500; PD 3500) sits inside K/DOQI 2004 (2–4 g at G3–G4),
  Kalantar-Zadeh & Fouque NEJM 2017 (< 3 g at CKD 4–5) and AKF ("aim for 2,500, no more than
  3,000"). See `docs/research/ckd-diet.md` §2.4 and fact-check M-8.

### F7. Phosphorus: the lab decides; no age or sex effect

* **KDOQI 2020 6.3.1 (1B):** in CKD 3–5D, adjust phosphorus to keep serum phosphate normal.
  **6.3.2 (OPINION):** consider bioavailability. **6.3.3 (OPINION):** post-transplant with
  hypophosphataemia, consider *high* phosphorus intake.
* **KDOQI 2003 4.1:** 800–1000 mg when phosphate is above 4.6 mg/dL (stages 3–4, OPINION) or above
  5.5 (stage 5, EVIDENCE).
* **KDIGO 2017:** 4.1.2 lower elevated phosphate *toward* normal (2C); 4.1.8 limit dietary phosphate
  in hyperphosphataemia (2D).
* Normal adult range: 2.5–4.5 mg/dL (0.81–1.45 mmol/L).

### F8. Calcium: age and sex matter only where kidney function is near normal

* **KDOQI 2020 6.2.1 (2B):** CKD 3–4 not on active vitamin D: **800–1000 mg/day total** including
  binders, for neutral balance. **6.2.2 (OPINION):** CKD 5D, adjust to avoid hypercalcaemia,
  considering vitamin D analogues and calcimimetics. Neither statement varies by age or sex. These
  CKD-specific numbers **override** the general recommended daily allowance (RDA), which would
  otherwise raise older women to 1200 mg.
* **NASEM 2011:**

  | Group | RDA | Upper limit (UL) |
  |---|---|---|
  | Everyone 19–50 | 1000 | 2500 |
  | Men 51–70 | 1000 | 2000 |
  | Women 51–70 | 1200 | 2000 |
  | Everyone 71+ | 1200 | 2000 |

  This applies at G1–G2 and to a transplant with graft function in that range, where no CKD
  calcium statement exists. KDOQI 5.0.1 (OPINION) also says to aim for the RDA for micronutrients.

### F9. Fluid: dialysis drives it; age only adds a "don't under-drink" note

* HD: 1000 mL plus 24-hour urine is the dialysis-unit convention (DaVita, AKF, already cited). It
  is not a graded statement.
* PD: individualised to urine output and ultrafiltration (UF). No graded number exists.
* Not on dialysis: no routine limit.
* **ESPEN 2022 R61 (Grade B):** older women at least 1.6 L and older men at least 2.0 L of drinks a
  day *"unless there is a clinical condition that requires a different approach"*. This is a
  sex-specific statement, but it belongs in a **note** for people not on dialysis. A fluid floor
  would be wrong in heart failure or oedema. ESPEN's own commentary says *"specific clinical
  situations, namely heart, and renal failure may need a restriction of fluid intake"*, so the
  note is shown only at G1–G3b (native kidney or graft), not at G4–G5 (fact-check M1).

### F10. Fibre and carbohydrate

* **ADA 2026 Rec 5.24 (B):** *"Emphasize minimally processed, nutrient-dense, high-fiber sources
  of carbohydrate (at least 14 g fiber per 1,000 kcal)"*, verified verbatim in PMC12690188. This
  is the same basis as the IOM 2005 fibre AI. Age and sex act only through energy.
* Carbohydrate: no guideline sets a percentage. ADA individualises it. The 45 % default and the
  per-meal split stay unchanged **[OPINION, v0.2]**. Age and sex act only through energy.
* KDIGO 2022 PP 3.1.1 and KDIGO 2024 PP 3.3.1 favour plant-forward, fibre-rich diets with less
  ultra-processed food.

### F11. Labs that should, and should not, change targets

| Lab | Effect | Evidence |
|---|---|---|
| Serum potassium | Changes the potassium ceiling (F6) | KDOQI 6.4.x; KDIGO 3.11 |
| Serum phosphate | Changes the phosphorus target (F7) | KDOQI 6.3.x; KDIGO 2017 |
| Serum albumin < 3.8 g/dL | Raises the nutrition-risk flag: protein and energy go to the higher end. Ask about nutrition assessment and supplements | ISRNM 2008 PEW criterion; KDOQI 1.2.1 says never interpret alone (OPINION); 1.2.2 predicts outcomes on HD (1A); 4.1.1 oral supplements if at risk (2D) |
| Bicarbonate < 22 / < 18 mmol/L | **Note only**: fruit and vegetables lower acid load; drug treatment is the team's choice | KDOQI 6.1.1 (2C), 6.1.2 (1C), 6.1.3 aim 24–26 (OPINION); KDIGO PP 3.10.1 (< 18). BiCARB (age 60+, < 22) found no benefit from tablets |
| UACR | **Note only**: category A1–A3; with A3 and low albumin, protein may be lost in urine | KDIGO 2024 Table 3 |
| HbA1c, CGM | **No target change.** A1c is less reliable in G4–G5 and on dialysis | KDIGO 2022 PP 2.1.2; ADA 2026 Sec 6/11 |
| Creatinine, cystatin C, eGFR | **Suggest** a G stage only; never change the saved stage | KDIGO 2024 Rec 1.2.4.1 (1D) |

### F12. Malnutrition, frailty and weight-loss thresholds

* **GLIM 2019** phenotypic criteria (re-checked by the fact-check against secondary reproductions
  of GLIM Table 1; primary PDF not fetched):
  * Low BMI: < 20 under 70 years, < 22 at 70 and over. Asian cut-offs are < 18.5 and < 20.
  * Unintended weight loss: > 5 % within 6 months, or > 10 % beyond 6 months.
  * GLIM *diagnosis* also needs an etiologic criterion, so the app treats these as a **risk** flag,
    not a diagnosis.
* **ISRNM 2008 PEW** (re-checked against the criteria table reproduced in PMC4222262): albumin
  < 3.8 g/dL (bromocresol green method); BMI < 23; unintended weight loss 5 % in 3 months or 10 %
  in 6 months. Many labs measure albumin by bromocresol purple, which reads lower in CKD, so the
  3.8 cut-off over-flags on those assays; the L-ALB note says to ask the team (fact-check L13).
* KDOQI 1.1.11: BMI < 18 alone establishes PEW.
* Frailty and sarcopenia screens (SARC-F, FRAIL) are a later option. v0.3 uses a checkbox.

### F13. eGFR and staging

* **KDIGO 2024:** Rec 1.2.4.1 says use a validated equation (1D). PP 1.2.4.1 says use the same
  equation within a region. PP 1.2.4.2 says avoid race. Rec 1.2.2.1 says use eGFRcr-cys when
  eGFRcr is less accurate and the decision matters (1C).
* Validated adult equations (KDIGO Table 14): CKD-EPI 2021 creatinine, CKD-EPI 2021
  creatinine-cystatin, CKD-EPI 2012 cystatin, EKFC (needs regional Q values), and regional
  variants.
* **CKD-EPI 2021, creatinine** (Inker, NEJM 2021; NKF):
  `eGFR = 142 × min(Scr/κ,1)^α × max(Scr/κ,1)^−1.200 × 0.9938^age × 1.012 [female]`, where
  κ = 0.7 (F) / 0.9 (M) and α = −0.241 (F) / −0.302 (M). Scr in mg/dL, IDMS-standardised.
* **CKD-EPI 2021, creatinine-cystatin C:**
  `135 × min(Scr/κ,1)^α × max(Scr/κ,1)^−0.544 × min(Scys/0.8,1)^−0.323 × max(Scys/0.8,1)^−0.778 × 0.9961^age × 0.963 [female]`,
  where κ is as above and α = −0.219 (F) / −0.144 (M).
* **CKD-EPI 2012, cystatin C:**
  `133 × min(Scys/0.8,1)^−0.499 × max(Scys/0.8,1)^−1.328 × 0.996^age × 0.932 [female]`.
* All three require **age ≥ 18 and a sex**, and NKF specifies standardised assays (IDMS-traceable
  creatinine; standardised cystatin C). KDIGO 2024 discusses transgender and gender-diverse
  people under its sex and gender considerations. None of the three was developed for pregnancy,
  so the app does not compute or suggest a stage while `pregnant_or_breastfeeding` is set
  **[OPINION]** (fact-check L14).
* Categories: G1 ≥ 90, G2 60–89, G3a 45–59, G3b 30–44, G4 15–29, G5 < 15. G1–G2 are CKD only with a
  damage marker such as ACR ≥ 30 mg/g. Chronicity means 3 months or more; *"Do not assume
  chronicity based upon a single abnormal level"* (PP 1.1.3.2).
* Albuminuria (KDIGO Table 3):

  | Category | mg/g | mg/mmol |
  |---|---|---|
  | A1 | < 30 | < 3 |
  | A2 | 30–300 | 3–30 |
  | A3 | > 300 | > 30 |

  Conversion: mg/g × 0.113 = mg/mmol. KDIGO Table 17 advises reporting ACR to one decimal place
  in either unit (its body text says whole numbers for mg/g); the app keeps one decimal.
* KDIGO conversion factors:
  * creatinine mg/dL × 88.4 = µmol/L (KDIGO's PDF prints "mmol/l", a lost µ);
  * phosphate mg/dL × 0.3229 = mmol/L;
  * calcium mg/dL × 0.2495 = mmol/L.

### F14. Out of scope by evidence

* **Pregnancy:** KDIGO 2024 says fertility and pregnancy were outside its scope. NASEM 2023 uses
  separate pregnancy energy equations with tissue-deposition terms. Protein, calcium and fluid
  needs all change, and CKD in pregnancy is specialist care. **Refuse.**
* **Under 18:** KDIGO 2024 PP 3.3.1.4 says do not restrict protein in children, and targets should
  sit at the upper end of normal for growth. PP 3.3.2.2 gives age-based sodium for children.
  Children also need different eGFR equations (PP 1.2.4.3). **Refuse.**
* **Early transplant:** CARI says about 1.4 g/kg protein for 4 weeks. Steroid doses, phosphate
  wasting and potassium all change fast. KDOQI's "metabolically stable" excludes people taking
  immunosuppressants. **Refuse for the first 12 weeks [OPINION on the cut-off]**; manual targets
  remain possible.

### F15. Regulatory boundary (not legal advice)

The FDA's *Policy for Device Software Functions and Mobile Medical Applications* (2022) allows two
things under enforcement discretion. One is software that helps patients **self-manage** a disease
*"without providing specific treatment or treatment suggestions"*. The other is software doing
**simple calculations routinely used in clinical practice**. Software that does
**patient-specific analysis** and gives **patient-specific treatment recommendations** is a device
function. In the EU, MDR Annex VIII Rule 11 classes software that informs therapeutic decisions as
IIa or higher (MDCG 2019-11).

Lab-driven target changes and urgent alerts move the app toward that boundary. The design
therefore:
* keeps every output a labelled "starting point to review with your care team";
* shows the rule and source for every number;
* never saves without the user;
* lets an instance admin switch lab-driven rules off (§4.9).

### F16. Summary: what each factor changes

| Factor ↓ / target → | Energy | Protein | Carbs | Fibre | Na | K | P | Ca | Fluid |
|---|---|---|---|---|---|---|---|---|---|
| **Age** | yes (EER) | yes (≥ 65) | via energy | via energy | no | no | no | G1–G2 / Tx only (RDA) | note ≥ 65 (G1–G3b, not on dialysis) |
| **Sex** | yes (EER) | no (per kg) | via energy | via energy | no | no (AI rejected) | no | G1–G2 / Tx only (RDA) | note ≥ 65, G1–G3b (1.6 / 2.0 L) |
| **Height + weight** | yes (reference weight) | yes | via energy | via energy | no | no | no | no | no |
| **Activity** | yes (PAL) | no | via energy | via energy | no | no | no | no | no |
| **Diabetes (type 1 or 2)** | – | G3–G5 not on dialysis: 0.8 g/kg, never below (ADA 11.3, KDIGO) | per-meal split | – | – | – | – | – | – |
| **Frailty / malnutrition** | floor 30 kcal/kg | higher range | via energy | via energy | no | no | no | no | no |
| **Serum K** | – | – | – | – | – | **yes** | – | – | – |
| **Serum phosphate** | – | – | – | – | – | – | **yes** | – | – |
| **Albumin** | via risk flag | via risk flag | – | – | – | – | – | – | – |
| **Bicarbonate, UACR, A1c/CGM** | notes only | | | | | | | | |
| **Urine output, PD UF** | – | – | – | – | – | – | – | – | **yes** (dialysis) |
| **PD dialysate glucose** | **yes** (subtract) | – | via energy | via energy | – | – | – | – | – |
| **Transplant** | as non-dialysis | 0.8–1.0 (≥ 65 or risk: 1.0–1.2 at graft G1–G2 only) | | | | lab | not limited unless high (graft G1–G3b); ladder at graft G4–G5 | per graft stage | none |
| **Pregnancy, age < 18, Tx < 12 weeks** | refuse | | | | | | | | |

---

## 3. Options compared

### 3.1 Reference ("dosing") weight

Example: a 170 cm person weighing 100 kg (BMI 34.6). v0.2 gives 72.3 kg.

| Option | 100 kg @ 170 cm → | Sex needed | Continuous | Evidence | Verdict |
|---|---|---|---|---|---|
| A. Actual weight always | 100 | no | yes | KDOQI final wording "kg body weight" | Over-feeds protein in obesity |
| B. v0.2 clamp to BMI 25 / 18.5 | 72.3 | no | yes | Desirable BW (Table 5) | Too aggressive for BMI 25–35; calls itself "ideal" (F1) |
| C. Hamwi/Devine/Robinson + Karkeck | M 75.2, F 70.8 | yes | yes | Table 5; "no scientific data" | Sex-dependent BMI drift; fails for unspecified sex |
| D. KDOQI 2000 oedema-free adjustment, both sides | 93.1 | no | no (95 %/115 % trigger) | Table 5 | Keeps 75 % of excess; discontinuous |
| **E. BMI-band reference: Karkeck above BMI 25, KDOQI 2000 below BMI 18.5** | **79.2** | **no** | **yes** | Table 5 formulas on KDOQI's BMI-based desirable BW | **Chosen [OPINION]** |

IBW formula drift by height, for context. Values are kg (implied BMI), rounded half-up to 0.1 like the
app (Hamwi below 5 ft extrapolated linearly).

| Height | Hamwi M | Hamwi F | Devine M | Devine F | Robinson M | Robinson F | BMI 18.5 | BMI 25 |
|---|---|---|---|---|---|---|---|---|
| 150 cm | 45.5 (20.2) | 43.2 (19.2) | 47.8 (21.3) | 43.3 (19.3) | 50.2 (22.3) | 47.4 (21.1) | 41.6 | 56.3 |
| 160 cm | 56.2 (22.0) | 52.2 (20.4) | 56.9 (22.2) | 52.4 (20.5) | 57.7 (22.5) | 54.1 (21.1) | 47.4 | 64.0 |
| 170 cm | 66.9 (23.2) | 61.1 (21.1) | 65.9 (22.8) | 61.4 (21.3) | 65.2 (22.5) | 60.8 (21.0) | 53.5 | 72.3 |
| 180 cm | 77.6 (24.0) | 70.0 (21.6) | 75.0 (23.1) | 70.5 (21.8) | 72.6 (22.4) | 67.5 (20.8) | 59.9 | 81.0 |
| 190 cm | 88.3 (24.5) | 79.0 (21.9) | 84.0 (23.3) | 79.5 (22.0) | 80.1 (22.2) | 74.2 (20.5) | 66.8 | 90.3 |

### 3.2 Energy method

| Option | Age/sex/activity | CKD evidence | Inputs | Verdict |
|---|---|---|---|---|
| A. Fixed 30 kcal/kg (v0.2) | none | KDOQI 3.1.1 range (1C) | weight | Keep as **fallback** when age or height is missing |
| B. KDOQI 2000 age rule (35 / 30–35) | age only | superseded | age | Reject |
| C. Mifflin-St Jeor × activity factor | yes | over- or under-estimates in CKD (KDOQI 1.4 rationale) | + sex | Reject |
| D. MHDE (HD only) | partly | 1.4.2 (2C); imprecise | CRP, creatinine, A1c | Reject for v0.3 (lab-heavy, REE only) |
| **E. NASEM 2023 EER on reference weight, clamped to 25–35 kcal/kg** | **yes** | DRI includes chronic disease; KDOQI range kept | age, sex, height, activity | **Chosen [OPINION: combining the two]** |

### 3.3 Potassium

| Option | Verdict |
|---|---|
| A. Stage ladder only (v0.2) | Keep as the default **when no recent lab** exists |
| B. Labs only (no limit unless high) | Unsafe without a recent lab; hides the ladder the dietitian reviews |
| C. Sex-specific AI (3400/2600) as minimum | Reject: healthy-population adequacy value (F6) |
| **D. Ladder + lab modifiers: relax one step when K is normal (unless there is a history), tighten above 5.0 / 5.5 / 6.0, no limit when low** | **Chosen [OPINION on the numbers; direction per KDOQI 6.4.1 and KDIGO PP 3.11.5.2]** |

### 3.4 Older adults' protein

| Option | Verdict |
|---|---|
| A. No change | Ignores KDIGO PP 3.3.1.5 and ADA 2026 Rec 13.11a |
| B. 1.0–1.2 g/kg for everyone ≥ 65 (ESPEN, PROT-AGE) | Too high at G4–G5 (PROT-AGE's own exception) |
| **C. ≥ 65 or nutrition risk: not on dialysis G3–G5 (native or graft) → 0.8–1.0; G1–G2 (native or graft) → 1.0–1.2; dialysis + risk → 1.2–1.3** | **Chosen [OPINION]** (graft-stage split added by fact-check M2) |

### 3.5 eGFR

| Option | Verdict |
|---|---|
| **Use the lab-reported eGFR when entered** (the lab knows its region's equation, PP 1.2.4.1) | **Chosen** |
| **Otherwise CKD-EPI 2021 (cr, cr-cys) and CKD-EPI 2012 (cys)** | **Chosen** (US/NKF-ASN standard; no regional Q values needed) |
| EKFC | Later option (needs Q values by region) |
| CKD-EPI 2009 with race | Reject (KDIGO PP 1.2.4.2) |

---

## 4. Recommendation

### 4.1 The answer in one paragraph

* **Age and sex should change energy**, through NASEM 2023 EER kept inside KDOQI's 25–35 kcal/kg.
* **Age should change protein** for people 65 and over, and so should frailty or malnutrition risk
  at any age.
* **Age and sex should change calcium only at G1–G2 and after transplant**, where general RDAs
  apply.
* **Age and sex should not change** sodium, potassium, phosphorus, carbohydrate (except through
  energy), fluid on dialysis, or the reference weight. The reference weight stays sex-neutral and
  BMI-based.
* **Labs matter more than demographics** for potassium and phosphorus.
* **Pregnancy, age under 18 and the first 12 weeks after transplant are refused.**
* **Diabetes sets a protein floor:** at G3–G5 without dialysis the suggestion never goes below
  0.8 g/kg (ADA 2026 Rec 11.3, A; KDIGO 2022 and 2024). Lower amounts are for care teams to
  prescribe under supervision, not for the app to suggest (fact-check H1).
* Without the new inputs, the output equals v0.2 except for four things:
  * the softer weight adjustment above BMI 25 and below 18.5 (and, below BMI 20, the
    nutrition-risk rules);
  * protein for diabetes at G3a–G5 without dialysis: 0.8 g/kg (v0.2: 0.6–0.8);
  * a new fibre goal;
  * calories rounded to 10 kcal.

### 4.2 Inputs

Profile fields, added to whichever table holds the per-user profile in v0.3:

| Field | Type / values | Default | Validation | Used by |
|---|---|---|---|---|
| `birth_month` | `"YYYY-MM"` | null | year in [today − 120, today]; month 01–12 | age → EER, protein ≥ 65, calcium RDA, GLIM BMI, eGFR, refusal < 18 |
| `sex` | `female` \| `male` \| `unspecified` | `unspecified` | enum | EER, calcium RDA, eGFR, fluid note. Label: "Sex used in medical formulas"; help text below |
| `activity` | `inactive` \| `low_active` \| `active` \| `very_active` | `inactive` **[OPINION]** | enum | EER |
| `transplant_date` | `"YYYY-MM-DD"` | null | not in future | mode = transplant when `dialysis == "none"` |
| `frail_or_sarcopenic` | bool | false | – | nutrition risk |
| `weight_6_months_ago_kg` | number | null | 20–400 | weight-loss % (GLIM) |
| `pregnant_or_breastfeeding` | bool | false | – | refusal |
| `hyperkalemia_history` | bool ("I have had high potassium or take a potassium binder") | false | – | K rule K-2h |
| `urine_output_ml` | number (24 h) | null | 0–5000 | HD/PD fluid |
| `pd_uf_ml` | number (net UF / 24 h) | null | 0–4000 | PD fluid |
| `pd_dialysate_kcal` | number | null | 0–1000 | PD energy (E-4) |

Existing fields keep their meaning:
* `weight_kg` is relabelled **"dry (post-dialysis) weight"** when dialysis is set.
* `ckd_stage` is the **graft** stage after transplant.

Help text for `sex`: *"Used only for formulas (kidney function, energy, calcium). Choose the sex
your lab uses for your eGFR. If you take gender-affirming hormones, ask your clinician which to use.
'Prefer not to say' uses an average and shows ranges."*

Age is completed years from the first day of `birth_month` to "today" in the server's time zone.
Pure functions take `today` as a parameter so tests are deterministic. **Exception for the
under-18 refusal (S-2):** age is counted from the **last** day of `birth_month`, so anyone who
might still be 17 is refused (fact-check M5; vector TV23). Using the first day would let a
17-year-old born late in the month through for up to 30 days.

Labs go in a new `lab_results` table:

| Analyte key | Canonical unit | Accepted units → canonical | Plausible range (reject outside) | Fresh for **[OPINION]** |
|---|---|---|---|---|
| `potassium` | mmol/L | mEq/L × 1 | 1.5–9.0 | 90 days |
| `phosphate` | mg/dL | mmol/L ÷ 0.3229 | 0.5–20 | 90 days |
| `albumin` | g/dL | g/L × 0.1 | 0.5–6.5 | 180 days |
| `bicarbonate` | mmol/L | mEq/L × 1 | 5–50 | 180 days |
| `uacr` | mg/g | mg/mmol ÷ 0.113 | 0–50000 | 365 days |
| `creatinine` | mg/dL | µmol/L ÷ 88.4 | 0.1–25 | 365 days |
| `cystatin_c` | mg/L | – | 0.2–10 | 365 days |
| `egfr` (lab-reported) | mL/min/1.73 m² | – | 1–200 | 365 days |
| `a1c` | % (NGSP) | mmol/mol: % = mmol/mol ÷ 10.929 + 2.15 | 3–20 | not used for targets |

* Store `value` in the canonical unit, plus `entered_value` and `entered_unit` for display.
* Always show the converted value back before saving. For example, "1.94 mmol/L = 6.0 mg/dL".
* Categorise on the displayed value, as `threshold_level` already does:
  * potassium, phosphate, albumin, bicarbonate and UACR rounded to 1 decimal;
  * UACR in the unit it was entered in (mg/g or mg/mmol thresholds, §5.2 U5);
  * eGFR rounded to an integer.

### 4.3 Formulas

All rounding is **decimal half-up** (the existing `_half_up`). v0.2 used Python `round()`, which
rounds halves to even; the difference shows only at exact .5.

```text
# Mode
mode = dialysis                     if dialysis in {hemodialysis, peritoneal}
     = "transplant"                 elif transplant_date is set
     = "ckd"                        otherwise

# Reference weight (sex-neutral; KDOQI 2020 Table 5 formulas on BMI-based desirable weight) [OPINION]
h = height_cm / 100;  BMI = w / h²;  W18.5 = 18.5 h²;  W25 = 25 h²
ref = W25 + 0.25 × (w − W25)        if BMI > 25      basis "adjusted_above_bmi25"   (Karkeck)
    = w + 0.25 × (W18.5 − w)        if BMI < 18.5    basis "adjusted_below_bmi18_5" (KDOQI 2000)
    = w                             otherwise        basis "actual"
    = w                             if no height     basis "actual_no_height"
ref rounded to 0.1 kg. A 1e-9 tolerance keeps exactly BMI 25 / 18.5 "actual" (as in v0.2).

# Nutrition risk (any one of these) [OPINION: used as a risk flag, not a diagnosis]
low_bmi      : BMI < 22 if age ≥ 70, else BMI < 20                         (GLIM 2019)
weight_loss  : (weight_6_months_ago − w) / weight_6_months_ago × 100 > 5   (GLIM 2019)
low_albumin  : albumin (fresh) < 3.8 g/dL                                  (ISRNM 2008)
frailty      : frail_or_sarcopenic                                          (KDIGO PP 3.3.1.5)

# Energy
if age known and height known:
    EER = NASEM 2023 Table S-1 (sex, activity, age, height_cm, ref)
          sex "unspecified" → mean of the male and female equations
    kcal_per_kg = clamp(EER / ref, 25, 35)                                  (KDOQI 3.1.1, 1C range)
else:
    kcal_per_kg = 30                                                        (v0.2 fallback)
if nutrition_risk: kcal_per_kg = max(kcal_per_kg, 30)                       (ESPEN R1; KDOQI 30–35)
total = kcal_per_kg × ref
food  = max(total − pd_dialysate_kcal, 20 × ref)  if mode == peritoneal and pd_dialysate_kcal
      = total                                     otherwise
calories_kcal = food rounded to the nearest 10

# Protein (g/kg × ref, each bound rounded half-up to an integer)
base:  dialysis 1.0–1.2 | transplant 0.8–1.0 | ckd G1–G2 0.8–1.0
       ckd G3a–G5: diabetes (type1|type2) 0.8–0.8   (P-2d; never below 0.8: ADA 11.3 A, KDIGO 2022/2024 2C)
                   no diabetes            0.6–0.8   (P-2n; < 0.8 only "under close clinical supervision")
older = age ≥ 65
dialysis   and nutrition_risk                     → 1.2–1.3
transplant and (older or risk) and graft G1–G2    → 1.0–1.2
transplant and (older or risk) and graft G3a–G5   → unchanged 0.8–1.0 (PROT-AGE eGFR < 30 exception)
ckd G1–G2  and (older or risk)                    → 1.0–1.2
ckd G3a–G5 and (older or risk)                    → 0.8–1.0
(dialysis and older only → unchanged)

# Carbohydrate and fibre (from food calories)
carbs_g          = round(calories_kcal × 0.45 / 4)                          (unchanged)
carbs_per_meal_g = max(15, round_to_5(carbs_g / 4))                         (unchanged)
fiber_g          = {"min": round(14 × calories_kcal / 1000)}               (ADA 2026 5.24, B)

# Sodium
sodium_mg = 2000 for everyone

# Potassium: ladder L and one-step-relaxed R
L = {G1: 4000, G2: 4000, G3a: 4000, G3b: 3500, G4: 3000, G5: 2500, HD: 2500, PD: 3500}   (v0.2)
R = {G1: 4000, G2: 4000, G3a: 4000, G3b: 4000, G4: 3500, G5: 3000, HD: 3000, PD: 4000}
(transplant uses the graft stage's row)

# Phosphorus defaults D
D = {G1–G4: 1000, G5: 900, HD/PD: 1000}
transplant with graft G1–G3b and no fresh phosphate → null (PH-T); graft G4–G5 → D by graft stage (PH-0)

# Calcium
mode ckd or transplant, stage G1–G2, age known:
    {"min": RDA(age, sex), "max": UL(age)}   (NASEM 2011; sex unspecified → the higher RDA)
otherwise:
    1000

# Fluid
HD : 1000 + urine_output_ml, rounded to 50,   if urine known; else 1500
PD : urine_output_ml + pd_uf_ml, rounded to 50, if both known; else 2000
otherwise: null; note F-0o (drink at least 1.6 / 2.0 L) only if age ≥ 65 and stage (native or graft)
           is G1–G3b, else F-0
```

eGFR:

```text
eGFRcr      = 142 · min(Scr/κ,1)^α · max(Scr/κ,1)^−1.200 · 0.9938^age · (1.012 if female)
              κ: F 0.7, M 0.9    α: F −0.241, M −0.302
eGFRcr-cys  = 135 · min(Scr/κ,1)^α · max(Scr/κ,1)^−0.544 · min(Scys/0.8,1)^−0.323
              · max(Scys/0.8,1)^−0.778 · 0.9961^age · (0.963 if female)
              κ: F 0.7, M 0.9    α: F −0.219, M −0.144
eGFRcys     = 133 · min(Scys/0.8,1)^−0.499 · max(Scys/0.8,1)^−1.328 · 0.996^age · (0.932 if female)
```

Use the creatinine and cystatin C pair taken on the same day; otherwise use whichever is newer.

Order of preference:
1. A fresh lab-reported `egfr`.
2. eGFRcr-cys.
3. eGFRcr.
4. eGFRcys.

Round to an integer and map to G1–G5. Then:
* With `sex == unspecified`, compute both female and male values and report the range. Suggest a
  category only if both map to the same one.
* Never compute eGFR for `mode in {hemodialysis, peritoneal}`.
* Never compute eGFR or suggest a stage while `pregnant_or_breastfeeding` is set (the equations
  were not developed for pregnancy) **[OPINION]**.
* Append "T" to the category for transplant.
* Never change `ckd_stage` automatically.

### 4.4 Decision table and rule catalogue

Every applied rule is returned as `{"id", "source", "grade", "opinion"}`, so the UI can show
"Why this number?".

| ID | Condition | Effect | Source | Grade | Opinion? |
|---|---|---|---|---|---|
| S-1 | `pregnant_or_breastfeeding` | 422 `out_of_scope_pregnancy` | KDIGO 2024 (scope); NASEM 2023 pregnancy EER | – | refusal is project policy |
| S-2 | age < 18, counted from the **last** day of `birth_month` | 422 `out_of_scope_under_18` | KDIGO 2024 PP 3.3.1.4, 3.3.2.2, 1.2.4.3 | PP | conservative age: OPINION |
| S-3 | transplant and fewer than 84 days since `transplant_date` | 422 `out_of_scope_early_transplant` | CARI 2010 (1.4 g/kg, 4 weeks); KDOQI "metabolically stable" | – | **12 weeks: OPINION** |
| W-1/W-2 | BMI 18.5–25 / no height | ref = actual | KDOQI 2020 1.1.6 | OPINION | – |
| W-3 | BMI > 25 | ref = W25 + 0.25 × excess | KDOQI 2020 Table 5 (Karkeck) | caution: not validated in CKD | **OPINION** |
| W-4 | BMI < 18.5 | ref = w + 0.25 × (W18.5 − w) | KDOQI 2020 Table 5 (KDOQI 2000) | – | **OPINION** |
| N-1 | any risk reason | flag; drives E-3, P-5, P-6 | GLIM 2019; ISRNM 2008; KDIGO PP 3.3.1.5 | consensus / PP | **OPINION** (risk, not diagnosis) |
| E-1 | age and height known | EER / ref clamped to 25–35 | NASEM 2023 Table S-1; KDOQI 2020 3.1.1 | DRI; 1C (range) | **OPINION** (combination) |
| E-2 | otherwise | 30 kcal/kg | KDOQI 2020 3.1.1 | 1C (range) | midpoint: OPINION |
| E-3 | risk and kcal/kg < 30 | raise to 30 | ESPEN 2022 R1; KDOQI 3.1.1 rationale | B | **OPINION** for CKD |
| E-4 | PD with dialysate kcal | subtract; floor 20 kcal/kg | Grodstein 1981; EBPG/ESPEN via Fantuzzi 2022 | – | floor: **OPINION** |
| P-1 | ckd G1–G2 | 0.8–1.0 | RDA 0.8; KDIGO PP 3.3.1.1 (< 1.3) | PP | 1.0 ceiling: OPINION |
| P-2 | ckd G3a–G5 | diabetes: **0.8–0.8** (note P-2d); no diabetes: 0.6–0.8 (note P-2n) | Diabetes: ADA 2026 11.3, KDIGO 2022 3.1.1, KDIGO 2024 3.3.1.1 (KDOQI 3.0.2's 0.6 needs close supervision). No diabetes: KDOQI 3.0.1, KDIGO 3.3.1.1, PP 3.3.1.3 | A / 2C / 2C; 1A (supervised) / 2C / PP | P-2n lower bound: OPINION, for C10 review |
| P-3 | HD or PD | 1.0–1.2 | KDOQI 3.0.3 (no diabetes), 3.0.4 (diabetes); KDIGO 2022 PP 3.1.2; ADA 11.3 | 3.0.3: 1C (HD) / OPINION (PD); 3.0.4: OPINION; PP; B | – |
| P-5 | (age ≥ 65 or risk), not on dialysis | native G3–G5 0.8–1.0; native or graft G1–G2 1.0–1.2; graft G3a–G5 not applied (stays P-7) | KDIGO PP 3.3.1.5 + rationale; ADA 2026 Rec 13.11a; ESPEN R2; PROT-AGE (incl. eGFR < 30 exception) | PP / B / B / consensus | **OPINION** (numbers) |
| P-6 | dialysis and risk | 1.2–1.3 | KDOQI 2000; KDOQI 2020 3.0.4 | – / OPINION | **OPINION** |
| P-7 | transplant | 0.8–1.0 | CARI 2010; KDOQI "metabolically stable" definition | – | **OPINION** |
| K-0 | no fresh potassium | L | v0.2 ladder (K/DOQI 2004, NEJM 2017, AKF) | – | **OPINION** (ladder) |
| K-1 | K < 3.5 | null (no limit) | KDOQI 6.4.2 | 2D | threshold: lab convention |
| K-2 | 3.5 ≤ K ≤ 5.0, no history | R | KDOQI 6.4.1; KDIGO PP 3.11.5.2 | OPINION / PP | **OPINION** (one step) |
| K-2h | 3.5 ≤ K ≤ 5.0 with history | L | KDIGO PP 3.11.5.2 | PP | – |
| K-3 | 5.0 < K ≤ 5.5 | min(L, 3000) | KDIGO CKD-PC definition (> 5.0); AKF ≤ 3000 | – | **OPINION** |
| K-4 | 5.5 < K < 6.0 | min(L, 2500) | KDIGO Figure 32; AKF "aim 2,500" | – | **OPINION** |
| K-5 | K ≥ 6.0 | min(L, 2000) + alert `urgent` (6.0–6.4: repeat within 24 h, hospital if unwell) or `emergency` (≥ 6.5) | KDIGO 2024 Table 28 | – | 2000: **OPINION** |
| PH-0 | no fresh phosphate | D | KDOQI 2003 4.1 (800–1000) | OPINION / EVIDENCE | v0.2 pick: OPINION |
| PH-T | transplant with graft G1–G3b, no phosphate (graft G4–G5 → PH-0) | null | KDOQI 6.3.3 | OPINION | graft-stage cut: OPINION |
| PH-1 | phosphate < 2.5 mg/dL | null | KDOQI 6.3.3 (transplant) | OPINION | – |
| PH-2 | 2.5–4.5 | 1000 (transplant with graft G1–G3b: null) | KDOQI 6.3.1 | 1B | **OPINION** (1000) |
| PH-3 | > 4.5 | 800 | KDOQI 6.3.1; KDOQI 2003 4.1; KDIGO 2017 4.1.2, 4.1.8 | 1B / OPINION–EVIDENCE / 2C / 2D | low end: OPINION |
| NA-1 | always | 2000 | KDIGO 2024 3.3.2.1; KDOQI 6.5.1 | 2C; 1B/1C | – |
| CA-0 | G1–G2, age unknown | 1000 | NASEM 2011 (19–50 RDA) | – | – |
| CA-1 | G3a–G4 | 1000 (max) | KDOQI 6.2.1 (not taking active vitamin D) | 2B | – |
| CA-2 | G5 / 5D | 1000 (max) | KDOQI 6.2.2 (5D only; no KDOQI statement covers G5 without dialysis) | OPINION | G5 non-dialysis: OPINION |
| CA-3 | G1–G2 (ckd or transplant), age known | {RDA, UL} | NASEM 2011 | DRI | – |
| F-0 / F-0o | not on dialysis (o = age ≥ 65 **and** native or graft stage G1–G3b) | null (+ 1.6 / 2.0 L note) | ESPEN 2022 R61 and its commentary (renal and heart failure may need restriction) | B | G1–G3b cut: OPINION |
| F-1 / F-2 | HD | 1500 / 1000 + urine | DaVita, AKF convention | – | **OPINION** |
| F-3 / F-4 | PD | 2000 / urine + UF | individualised | – | **OPINION** |
| C-1 | always | 45 % / 4 / per meal | ADA (individualise) | – | **OPINION** (v0.2) |
| FB-1 | always | ≥ 14 g/1000 kcal | ADA 2026 5.24; IOM 2005 | B | – |
| L-ALB | albumin < 3.8 | note (and N-1) | KDOQI 1.2.1, 1.2.2, 4.1.1 | OPINION / 1A / 2D | – |
| L-BIC22 / L-BIC18 | bicarbonate < 22 / < 18 | note; the fruit-and-vegetable sentence only at G1–G4 without dialysis (6.1.1 scope) | KDOQI 6.1.1 (CKD 1–4), 6.1.2–6.1.3 (CKD 3–5D); KDIGO PP 3.10.1 | 2C / 1C / OPINION / PP | – |
| L-UACR-A1..A3 | UACR fresh | note | KDIGO 2024 Table 3 | definition | – |
| L-A1C | A1c entered | note "no change" | KDIGO 2022 PP 2.1.2 | PP | – |
| G-1 | creatinine, cystatin or eGFR fresh | stage *suggestion* | KDIGO Rec 1.2.4.1, Rec 1.2.2.1, PP 1.2.4.2, PP 1.1.3.2 | 1D / 1C / PP | – |

Rules apply in this order: S → W → N → E → P → K → PH → NA → CA → F → C → FB → L. Notes come out
in the same order.

### 4.5 Note texts

The developer copies these strings. Placeholders use Python `str.format`.
* kg values use `{:g}`. kcal, mg, mL and g are integers.
* `{date}` is ISO `YYYY-MM-DD`.
* `POTASSIUM_NOTE` is unchanged: *"Only restrict potassium if your blood potassium is high; your
  care team sets the number."*
* Every potassium note ends with `POTASSIUM_NOTE`, keeping the v0.2 contract.

```text
W-1  Weight basis: {w:g} kg is in the healthy BMI range (BMI {bmi:.1f}) for {h:g} cm, so your actual weight is used for calories and protein.
W-2  Weight basis: without a saved height your actual weight ({w:g} kg) is used. Add your height so the app can adjust for a weight above or below the healthy range.
W-3  Weight basis: at BMI {bmi:.1f}, calories and protein use an adjusted weight of {ref:g} kg: the weight at BMI 25 for {h:g} cm ({w25:g} kg) plus a quarter of the weight above it. Guidelines leave the choice of weight to your care team (KDOQI 2020 1.1.6); this is the app's default.
W-4  Weight basis: at BMI {bmi:.1f}, calories and protein use {ref:g} kg: your weight moved a quarter of the way toward the healthy range ({w185:g} kg at BMI 18.5), as in KDOQI's adjusted body weight. Gaining weight safely is a job for your renal dietitian.
W-D  (appended to W-* on dialysis) Enter your dry weight, measured after a dialysis session.
N-1  Nutrition risk: {reasons}. The app moves protein and calories to the higher end. Ask your renal dietitian for a nutrition assessment and whether oral nutrition supplements would help (KDOQI 2020 4.1.1).
     reasons, joined with "; ":
       low_bmi      → "BMI {bmi:.1f} is below {thr:g}"
       weight_loss  → "you have lost {pct:.1f} % of your weight in 6 months"
       low_albumin  → "blood albumin {alb:.1f} g/dL is below 3.8"
       frailty      → "frailty or low muscle mass is marked in your profile"
E-1  Calories: {kcal} kcal/day, the energy estimate for your age, sex, height, {ref:g} kg and activity ("{activity_label}") from the 2023 Dietary Reference Intakes ({kpk:.1f} kcal/kg), kept inside the kidney guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1).
     + if clamped:            " The estimate was {raw:.1f} kcal/kg, so it was set to {edge} kcal/kg."
     + if sex unspecified:    " Sex is not set, so the average of the female and male equations is used."
E-2  Calories: 30 kcal/kg × {ref:g} kg = {kcal} kcal/day, the middle of the guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1). Add your birth month, sex, height and activity for a personal estimate.
E-3  Calories were raised to 30 kcal/kg because of the nutrition risk above (ESPEN 2022; KDOQI 2020: 30–35 kcal/kg keeps protein balance).
E-4  Peritoneal dialysis: {pdk} kcal/day absorbed from dialysis fluid was subtracted, so food calories are {kcal} of {total} kcal. That glucose also needs insulin; your diabetes team plans for it.
P-1  Protein: {min}–{max} g/day (0.8–1.0 g/kg × {ref:g} kg). At stages 1–2 guidelines only ask you to avoid more than 1.3 g/kg (KDIGO 2024).
P-2d Protein: about {max} g/day (0.8 g/kg × {ref:g} kg) for CKD stages 3–5 with diabetes (KDIGO 2022 Rec 3.1.1; KDIGO 2024 Rec 3.3.1.1; ADA 2026 Rec 11.3). With diabetes, eating less than 0.8 g/kg is not recommended (ADA 2026): it risks muscle loss and low blood sugar. A lower amount (KDOQI 2020 3.0.2: 0.6–0.8) is only for people under close supervision by their care team. Avoid more than 1.3 g/kg (KDIGO 2024).
P-2n Protein: {min}–{max} g/day (0.6–0.8 g/kg × {ref:g} kg) for CKD stages 3–5. KDIGO 2024 Rec 3.3.1.1 suggests 0.8 g/kg. Going below 0.8 (KDOQI 2020 3.0.1: 0.55–0.6) needs close supervision by your care team, and is not for anyone who is unwell, in hospital recently or losing weight (KDIGO 2024 PP 3.3.1.3). Avoid more than 1.3 g/kg (KDIGO 2024).
P-3  Protein: {min}–{max} g/day (1.0–1.2 g/kg × {ref:g} kg) on {mode_label} (KDOQI 2020 3.0.3/3.0.4). Dialysis removes protein, so more is needed, not less.
P-5a Protein raised to {lo}–{hi} g/kg ({min}–{max} g/day) because {why}: in older adults and people at risk of malnutrition, losing muscle is often the bigger danger (KDIGO 2024 PP 3.3.1.5; ADA 2026 Rec 13.11a: at least 0.8 g/kg). If your kidney function is falling fast, your team may still prefer a lower range.
     why → "you are 65 or older" | "of the nutrition risk above" | "you are 65 or older and at nutrition risk"
P-6  Protein raised to 1.2–1.3 g/kg ({min}–{max} g/day) because of the nutrition risk above (KDOQI 2000: 1.2 on hemodialysis, 1.2–1.3 on peritoneal dialysis).
P-7  Protein: {min}–{max} g/day (0.8–1.0 g/kg × {ref:g} kg) for a working kidney transplant. No guideline sets a long-term number; low-protein diets are not used with anti-rejection medicines.
     + if age ≥ 65 or nutrition risk and graft stage 3a–5: " It is not raised further for age because your transplant's function is at stage {stage}; ask your team."
K-0  Potassium: {k_mg} mg/day is a review ceiling for {stage_label}, not a prescription; no blood potassium from the last 90 days is saved. {POTASSIUM_NOTE}
K-1  Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is low, so no potassium limit is set. Ask your care team whether to eat more potassium-rich foods or take a supplement (KDOQI 2020 6.4.2). {POTASSIUM_NOTE}
K-2  Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, so the review ceiling is relaxed one step to {k_mg} mg/day. While it stays normal there is no need to cut fruit and vegetables (KDOQI 2020 6.4.1; KDIGO 2024). {POTASSIUM_NOTE}
K-2h Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, but you have had high potassium before or take a potassium binder, so the ceiling stays at {k_mg} mg/day; processed foods with potassium additives matter most (KDIGO 2024 PP 3.11.5.2). {POTASSIUM_NOTE}
K-3  Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is above normal (over 5.0), so the ceiling is {k_mg} mg/day. Check processed foods with potassium additives, salt substitutes and large portions first; your team may also review medicines (KDIGO 2024 Figure 32). {POTASSIUM_NOTE}
K-4  Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is high (over 5.5), so the ceiling is {k_mg} mg/day. Tell your care team; they may change medicines or start a potassium binder. {POTASSIUM_NOTE}
K-5  Potassium: {k:.1f} mmol/L on {date} is dangerously high. {urgency} The ceiling is set to {k_mg} mg/day until your team gives you a number. {POTASSIUM_NOTE}
     urgency (6.0–6.4) → "Contact your care team today: this result should be repeated within 24 hours, and if you feel unwell (weakness, palpitations or an irregular pulse) get urgent medical care now (KDIGO 2024 Table 28)."
     urgency (≥ 6.5)   → "Get urgent medical care now, especially with weakness, palpitations or an irregular pulse (KDIGO 2024 Table 28)."
PH-0 Phosphorus: {p_mg} mg/day (guideline range 800–1000 mg when phosphate runs high); no phosphate result from the last 90 days is saved. Avoiding phosphate additives matters more than the total because additive phosphorus is almost fully absorbed.
PH-T Phosphorus: not limited after a kidney transplant unless your phosphate is high; low phosphate is common in the first months (KDOQI 2020 6.3.3). (Graft stage 4–5 uses PH-0 instead.)
PH-1 Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is low, so no phosphorus limit is set. Ask your team whether to eat more phosphorus or take a supplement (KDOQI 2020 6.3.3).
PH-2 Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is normal; {p_mg_or_none} is a review ceiling. Keep avoiding phosphate additives (KDOQI 2020 6.3.1–6.3.2).
PH-3 Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is above normal (over 4.5), so the target is 800 mg/day, the low end of the 800–1000 mg range (KDOQI 2003; KDIGO 2017). Cut phosphate additives first and take binders with meals as prescribed. On dialysis keep protein up by choosing foods with little phosphorus per gram of protein (egg whites, fresh meat and fish).
NA-1 Sodium: 2000 mg/day for every adult with CKD, whatever the age or sex (KDIGO 2024; KDOQI 2020 6.5.1: under 2300 mg).
CA-0 Calcium: 1000 mg/day. Add your birth month and sex for the amount recommended for your age.
CA-1 Calcium: at most 1000 mg/day in total, counting calcium-based binders and supplements (KDOQI 2020 6.2.1: 800–1000 mg at stages 3–4 when not taking active vitamin D such as calcitriol). At these stages it does not change with age or sex.
CA-2 Calcium: 1000 mg/day in total as a starting point; at stage 5 and on dialysis your team adjusts it to avoid high calcium, counting binders and vitamin D medicines (KDOQI 2020 6.2.2 covers dialysis; for stage 5 without dialysis this is the app's default).
CA-3 Calcium: {rda}–{ul} mg/day: the general recommendation for your age and sex ({rda} mg) up to the safe upper limit ({ul} mg) (Dietary Reference Intakes 2011).
F-0  Fluid: no limit without dialysis unless your care team sets one.
F-0o Fluid: no limit without dialysis unless your care team sets one. Thirst fades with age: unless your team limits fluid, or you have heart failure or swelling, aim for at least {floor} of drinks a day (ESPEN 2022).
     floor → female "1.6 L" | male "2.0 L" | unspecified "1.6 L (women) or 2.0 L (men)"
F-1  Fluid: 1000 mL plus your 24-hour urine volume; 1500 mL assumes about 500 mL of urine. Enter your urine volume or ask your dialysis unit for your allowance.
F-2  Fluid: 1000 mL + your {u} mL of urine = {fluid} mL/day, the usual hemodialysis allowance; your unit may set a different number.
F-3  Fluid: about 2000 mL/day on peritoneal dialysis. Enter your daily urine volume and ultrafiltration for a personal number.
F-4  Fluid: urine {u} mL + ultrafiltration {uf} mL = {fluid} mL/day, about what your body removes each day. Check it with your PD nurse.
C-1  (unchanged v0.2 carbohydrate notes)
FB-1 Fibre: at least {fib} g/day (14 g per 1000 kcal, ADA 2026). When potassium is limited, get it from low-potassium fruit, vegetables and grains.
L-ALB Low albumin can also come from inflammation or protein lost in urine, not only from diet (KDOQI 2020 1.2.1). Labs measure albumin in different ways; ask your team whether this result counts as low for your lab.
L-BIC22 Bicarbonate {b:.1f} mmol/L is below 22: acid builds up as kidneys fail. {fv}Your team may prescribe bicarbonate (KDOQI 2020 6.1.2).
     fv (not on dialysis, stage 1–4) → "More fruit and vegetables lower the acid load (KDOQI 2020 6.1.1){k_caveat}. "
     fv (stage 5 or dialysis)         → "" (6.1.1 covers CKD 1–4 only; at stage 5 and on dialysis extra fruit and vegetables also add potassium)
     k_caveat (fresh K > 5.0) → " (your potassium is high, so ask your team first)"
L-BIC18 Bicarbonate {b:.1f} mmol/L is below 18. KDIGO 2024 says treatment should be considered at this level (practice point 3.10.1); tell your care team.
L-UACR Urine albumin {uacr:.1f} {unit} (as entered) is category {cat} ({cat_label}). It does not change food targets but is a reason to keep sodium low (KDOQI 2020 6.5.2).
     + if A3 and low albumin: " With low blood albumin this can mean protein is lost in urine; your team may set protein differently."
L-A1C A1c and CGM readings do not change these food targets; in advanced CKD A1c is less reliable (KDIGO 2022 PP 2.1.2).
END  These are starting points only — confirm every target with your nephrologist and renal dietitian.

Refusals (422, detail = {"code", "message"}):
out_of_scope_pregnancy        Targets are not suggested during pregnancy or breastfeeding: needs for energy, protein, calcium and fluid change, and kidney disease in pregnancy needs specialist care. Ask your kidney and maternity teams for targets; you can still enter them by hand.
out_of_scope_under_18         Targets are not suggested for people under 18: children need more protein and energy to grow, and kidney guidelines for children are different. Ask your child's kidney team; you can still enter targets by hand.
out_of_scope_early_transplant Your kidney transplant was less than 12 weeks ago. In the first weeks your transplant team sets a recovery diet, usually higher in protein, so the app does not suggest targets yet. You can still enter targets by hand.

eGFR suggestion (GET /api/labs/kidney-function):
G-1  Your eGFR on {date} is {e} mL/min/1.73 m² ({method}), which is stage {G}{T}{range_note}. Your profile says stage {stage}. One result does not change a stage — kidney disease stages need results over 3 months (KDIGO 2024). Talk to your nephrologist before changing it.
     method → "reported by your lab" | "CKD-EPI 2021, creatinine and cystatin C" | "CKD-EPI 2021, creatinine" | "CKD-EPI 2012, cystatin C"
     range_note (sex unspecified) → " (female formula {ef}, male formula {em})"
```

### 4.6 API and data model

* `PUT /api/profile` accepts the new fields (§4.2). Empty or `null` clears them. Same merge
  semantics as today.
* `GET /api/profile/suggested-targets`:
  * still `400` without a weight;
  * `422 {"detail": {"code", "message"}}` for S-1, S-2 and S-3;
  * otherwise:

```json
{
  "targets": {"calories_kcal": 2280, "protein_g": {"min": 56, "max": 56}, "carbs_g": 257,
              "carbs_per_meal_g": 65, "fiber_g": {"min": 32}, "sodium_mg": 2000,
              "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null},
  "notes": ["Weight basis: …", "Calories: …", "…"],
  "rules": [{"id": "E-1", "source": "NASEM 2023 DRI Energy Table S-1; KDOQI 2020 3.1.1",
             "grade": "DRI; 1C (range)", "opinion": true}],
  "derived": {"mode": "ckd", "age": 55, "sex": "male", "bmi": 22.9, "reference_weight_kg": 70.0,
              "weight_basis": "actual", "eer_kcal": 2282, "kcal_per_kg": 32.6,
              "nutrition_risk": [], "labs_used": {"potassium": null, "phosphate": null}},
  "missing_inputs": ["activity"],
  "alerts": []
}
```

  `rules`, `derived`, `missing_inputs` and `alerts` are **additive**. Old clients keep working.
  `missing_inputs` drives "Add your birth month for personal calories" prompts.
* `POST /api/labs` takes `{analyte, value, unit, taken_on, note?}`.
  * Returns the stored row with the converted value.
  * Returns `alerts` when potassium is 6.0 or more, the same urgent and emergency texts as K-5.
    This is a safety message shown even if the user never opens Suggest.
  * `422` for an unknown unit, an implausible value or a future date.
* `GET /api/labs?analyte=&limit=` and `DELETE /api/labs/{id}`.
* `GET /api/labs/kidney-function` returns `{egfr: {value, method, category, female, male} | null,
  albuminuria: {value_mg_g, category} | null, profile_stage, message}`.
* SQLite migration (one ordered step in `app/db.py`):

```sql
ALTER TABLE profile ADD COLUMN birth_month TEXT;                     -- 'YYYY-MM'
ALTER TABLE profile ADD COLUMN sex TEXT NOT NULL DEFAULT 'unspecified';
ALTER TABLE profile ADD COLUMN activity TEXT NOT NULL DEFAULT 'inactive';
ALTER TABLE profile ADD COLUMN transplant_date TEXT;
ALTER TABLE profile ADD COLUMN frail_or_sarcopenic INTEGER NOT NULL DEFAULT 0;
ALTER TABLE profile ADD COLUMN weight_6_months_ago_kg REAL;
ALTER TABLE profile ADD COLUMN pregnant_or_breastfeeding INTEGER NOT NULL DEFAULT 0;
ALTER TABLE profile ADD COLUMN hyperkalemia_history INTEGER NOT NULL DEFAULT 0;
ALTER TABLE profile ADD COLUMN urine_output_ml REAL;
ALTER TABLE profile ADD COLUMN pd_uf_ml REAL;
ALTER TABLE profile ADD COLUMN pd_dialysate_kcal REAL;
CREATE TABLE IF NOT EXISTS lab_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,              -- per the multi-user note; 1 until then
  analyte TEXT NOT NULL,                 -- potassium|phosphate|albumin|bicarbonate|uacr|creatinine|cystatin_c|egfr|a1c
  value REAL NOT NULL,                   -- canonical unit (§4.2)
  entered_value REAL NOT NULL,
  entered_unit TEXT NOT NULL,
  taken_on TEXT NOT NULL,                -- YYYY-MM-DD
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lab_results_lookup ON lab_results(user_id, analyte, taken_on DESC, id DESC);
```

* Enum checks live in Pydantic (`Sex`, `Activity`, `Analyte`), as for the existing columns.
* `fiber_g` targets are min-only `Range`s. `daily_status` already returns them with
  `fraction: null`. Period summaries skip them (`summary_target` needs a max). The UI must show
  min-only goals as "X of ≥ Y g", never as "over" (§4.8).
* Lab results are part of the CSV and backup scope, and of the "delete my data" scope in the
  multi-user note.

### 4.7 File layout (new or changed)

```text
app/targets.py              NEW, pure: Inputs dataclass, reference_weight(), nutrition_risk(), eer_kcal(),
                            suggest(inputs, today) -> Suggestion; OutOfScope exception; rule catalogue import
app/target_rules.py         NEW, data only: RULES {id: {source, grade, opinion, url}}, ladders L/R/D,
                            NASEM EER coefficients, calcium RDA/UL table, freshness windows, note templates
app/kidney_function.py      NEW, pure: egfr_cr(), egfr_cr_cys(), egfr_cys(), gfr_category(), albuminuria_category()
app/units.py                NEW, pure: CANONICAL, to_canonical(analyte, value, unit), plausibility limits
app/labs.py                 NEW router: /api/labs, /api/labs/kidney-function
app/nutrients.py            suggest_targets() becomes a thin wrapper: builds Inputs from the v0.2 arguments
                            (so existing callers and the JSON test keep working); dosing_weight() delegates to
                            targets.reference_weight() and keeps returning (weight, basis) with the new basis names
app/profile.py              reads the new columns; passes the fresh labs and today's date to targets.suggest()
app/models.py               Sex, Activity, Analyte literals; ProfileUpdate/Profile fields; LabCreate/LabResult;
                            SuggestedTargets gains rules/derived/missing_inputs/alerts
app/db.py                   one ordered migration (§4.6)
app/static/app.js           mirror of targets.suggest + kidney_function (preview build parity), profile fields,
                            labs view, "Why this number?" disclosure, min-only goal rendering, urgent alert banner
tests/data/personal_target_vectors.json   NEW: the vectors of §5, shared by pytest and the JS parity check
tests/test_targets.py       NEW: vectors, rule ordering, rounding edges, refusal codes
tests/test_kidney_function.py NEW: eGFR vectors, category edges, unspecified-sex ranges
tests/test_units.py         NEW: conversions and plausibility
tests/test_labs_api.py      NEW: CRUD, conversion echo, potassium alert, freshness
docs/research/targets_by_stage.json       unchanged numbers; fix KDOQI statement numbers in "note" texts (C1)
docs/diet-guide.md          §2 and §7: personalisation explained for patients; §8 sources added
ARCHITECTURE.md             "Suggested targets" section rewritten to this spec
```

### 4.8 UI

* **Profile → "About you"** (all optional):
  * birth month;
  * sex used in formulas, with help text;
  * activity: four radio choices with the NASEM Table 7-1 descriptions in plain words;
  * "frailty or low muscle mass (as told by your care team)";
  * weight 6 months ago;
  * "pregnant or breastfeeding";
  * "I have had high potassium / I take a potassium binder".
* The "dry weight" label and the urine, UF and dialysate fields appear only for the matching
  dialysis mode. The transplant date appears when dialysis is "none".
* **Labs view:** add a result with a unit picker. Show the converted value before saving and a
  history list per analyte. A red banner appears for potassium of 6.0 or more. An eGFR card shows
  the G and A category and the "talk to your nephrologist" text.
* **Suggest targets:**
  * show a diff against the saved targets ("Potassium 3500 → 4000 because your potassium is
    normal");
  * a "Why this number?" disclosure lists the rules with source, grade and an **"expert opinion"**
    badge where `opinion` is true;
  * nothing is saved until **Save profile**, as today;
  * when a new lab would change a suggestion, show a dismissible "Review suggested targets" prompt.
    Never auto-apply.
* Min-only goals (fibre) render as progress toward a goal with no "over" state. Calcium
  `{min, max}` uses the existing range rendering.
* A protein range whose `min` equals its `max` (P-2d) renders as "about X g/day", not "X–X g".

### 4.9 Settings keys (for the settings note)

| Key | Scope | Default | Effect |
|---|---|---|---|
| `targets.lab_rules_enabled` | instance (admin) | `true` | `false` makes K-*/PH-* use the K-0/PH-0 defaults and suppresses lab notes, but **keeps** the potassium safety alert on lab entry |
| `targets.lab_fresh_days.potassium` / `.phosphate` / `.albumin` / `.bicarbonate` | instance | 90 / 90 / 180 / 180 | freshness windows |
| `targets.default_activity` | instance | `inactive` | default when the user has not chosen |
| `user.units.labs` | user | `us` | default unit pickers: `us` (mg/dL) or `si` (mmol/L, µmol/L, g/L) |

---

## 5. Test vectors

All vectors use **today = 2026-10-05**, diabetes `type1`, dialysis `none`, sex `unspecified` and
activity `inactive` unless stated. Expected values come from a reference implementation of §4.3
(scratch file, not committed), and were hand-checked for TV02, TV03, TV07 and E1. The fact-check
(§10) re-implemented §4.3 independently from the text: all 20 original vectors and E1–E10
reproduced exactly; after its fixes TV01, TV02, TV04, TV05, TV13, TV16, TV18 and TV19 changed
(bold cells) and TV21–TV23 were added.

### 5.1 Targets

"Rules" is the ordered list of rule IDs. `–` means `null` (not tracked).

| ID | Inputs | kcal | protein g | carbs g (per meal) | fibre g | Na | K | P | Ca | fluid mL | ref kg (basis) | rules |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TV01 | 70 kg, G3b (v0.2 call) | 2100 | **56–56** | 236 (60) | ≥29 | 2000 | 3500 | 1000 | 1000 | – | 70 (actual_no_height) | W-2 E-2 P-2 K-0 PH-0 NA-1 CA-1 F-0 C-1 FB-1 |
| TV02 | 70 kg, G3b, 175 cm, born 1971-03, male | 2280 | **56–56** | 257 (65) | ≥32 | 2000 | 3500 | 1000 | 1000 | – | 70 (actual) | W-1 E-1 P-2 K-0 PH-0 NA-1 CA-1 F-0 C-1 FB-1 |
| TV03 | 62 kg, G3b, 160 cm, born 1954-06, female, low_active | 1880 | 50–62 | 212 (55) | ≥26 | 2000 | 3500 | 1000 | 1000 | – | 62 (actual) | W-1 E-1 P-2 P-5 K-0 PH-0 NA-1 CA-1 F-0o C-1 FB-1 |
| TV04 | 95 kg, G4, 165 cm, born 1981-01, female, K 5.3 | 2090 | **60–60** | 235 (60) | ≥29 | 2000 | 3000 | 1000 | 1000 | – | 74.8 (adjusted_above_bmi25) | W-3 E-1 P-2 K-3 PH-0 NA-1 CA-1 F-0 C-1 FB-1 |
| TV05 | 52 kg, G4, 170 cm, born 1946-02, male, frail | 1730 | 42–52 | 195 (50) | ≥24 | 2000 | 3000 | 1000 | 1000 | – | 52.4 (adjusted_below_bmi18_5) | W-4 N-1 E-1 P-2 P-5 K-0 PH-0 NA-1 CA-1 **F-0** C-1 FB-1 |
| TV06 | 85 kg, HD, 180 cm, born 1966-09, male, urine 300, K 5.8, PO4 6.1 | 2430 | 82–98 | 273 (70) | ≥34 | 2000 | 2500 | 800 | 1000 | 1300 | 82 (adjusted_above_bmi25) | W-3 E-1 P-3 K-4 PH-3 NA-1 CA-2 F-2 C-1 FB-1 |
| TV07 | 60 kg, PD, 158 cm, born 1976-05, female, urine 800, UF 900, dialysate 350 kcal, K 3.2 | 1490 | 60–72 | 168 (40) | ≥21 | 2000 | – | 1000 | 1000 | 1700 | 60 (actual) | W-1 E-1 E-4 P-3 K-1 PH-0 NA-1 CA-2 F-4 C-1 FB-1 |
| TV08 | 80 kg, G2 graft, 178 cm, born 1986-04, male, transplant 2024-09-15, PO4 2.2 | 2600 | 64–79 | 293 (75) | ≥36 | 2000 | 4000 | – | 1000–2500 | – | 79.4 (adjusted_above_bmi25) | W-3 E-1 P-7 K-0 PH-1 NA-1 CA-3 F-0 C-1 FB-1 |
| TV09 | 80 kg, G3a graft, 178 cm, born 1986-04, male, transplant 2026-08-24 (42 days) | **422 `out_of_scope_early_transplant`** | | | | | | | | | | |
| TV10 | 60 kg, G3a, 165 cm, born 1994-01, female, pregnant | **422 `out_of_scope_pregnancy`** | | | | | | | | | | |
| TV11 | 55 kg, G3a, 165 cm, born 2009-01 (17), male | **422 `out_of_scope_under_18`** | | | | | | | | | | |
| TV12 | 58 kg, G2, no diabetes, 158 cm, born 1958-03, female, K 4.4 | 1690 | 58–70 | 190 (50) | ≥24 | 2000 | 4000 | 1000 | 1200–2000 | – | 58 (actual) | W-1 E-1 P-1 P-5 K-2 PH-0 NA-1 CA-3 F-0o C-1 FB-1 |
| TV13 | 68 kg, G5 (no dialysis), 172 cm, born 1968-07, male, K 4.6, PO4 4.0 | 2200 | **54–54** | 248 (60) | ≥31 | 2000 | 3000 | 1000 | 1000 | – | 68 (actual) | W-1 E-1 P-2 K-2 PH-2 NA-1 CA-2 F-0 C-1 FB-1 |
| TV14 | 70 kg, G3a, 168 cm, born 1976-10, sex unspecified, active, albumin 3.4 | 2450 | 56–70 | 276 (70) | ≥34 | 2000 | 4000 | 1000 | 1000 | – | 70 (actual) | W-1 N-1 E-1 P-2 P-5 K-0 PH-0 NA-1 CA-1 F-0 C-1 FB-1 L-ALB |
| TV15 | 78 kg, HD, 176 cm, born 1961-11, male, potassium history, K 4.7 | 2300 | 78–93 | 259 (65) | ≥32 | 2000 | 2500 | 1000 | 1000 | 1500 | 77.6 (adjusted_above_bmi25) | W-3 E-1 P-3 K-2h PH-0 NA-1 CA-2 F-1 C-1 FB-1 |
| TV16 | 70 kg, G4, 170 cm, born 1961-05, female, K 6.3 | 1920 | 56–70 | 216 (55) | ≥27 | 2000 | 2000 | 1000 | 1000 | – | 70 (actual) | W-1 E-1 P-2 P-5 K-5 PH-0 NA-1 CA-1 **F-0** C-1 FB-1 + alert `urgent` |
| TV17 | 74 kg, G3b, 178 cm, born 1966-01, male, weight 6 months ago 80 (−7.5 %) | 2300 | 59–74 | 259 (65) | ≥32 | 2000 | 3500 | 1000 | 1000 | – | 74 (actual) | W-1 N-1 E-1 P-2 P-5 K-0 PH-0 NA-1 CA-1 F-0 C-1 FB-1 |
| TV18 | 76 kg, G3b, 172 cm, born 1971-08, female, K 4.8, HCO3 19.0, UACR 450 | 2060 | **60–60** | 232 (60) | ≥29 | 2000 | 4000 | 1000 | 1000 | – | 74.5 (adjusted_above_bmi25) | W-3 E-1 P-2 K-2 PH-0 NA-1 CA-1 F-0 C-1 FB-1 L-BIC22 L-UACR-A3 |
| TV19 | 82 kg, G4, 181 cm (BMI 25.03: edge), K 4.9, no age or sex | 2460 | **66–66** | 277 (70) | ≥34 | 2000 | 3500 | 1000 | 1000 | – | 81.9 (adjusted_above_bmi25) | W-3 E-2 P-2 K-2 PH-0 NA-1 CA-1 F-0 C-1 FB-1 |
| TV20 | 66 kg, HD, 165 cm, born 1956-02, female, anuric (urine 0), K 4.5, albumin 3.5 | 1980 | 79–86 | 223 (55) | ≥28 | 2000 | 3000 | 1000 | 1000 | 1000 | 66 (actual) | W-1 N-1 E-1 E-3 P-3 P-6 K-2 PH-0 NA-1 CA-2 F-2 C-1 FB-1 L-ALB |
| TV21 | 70 kg, G4 graft, 170 cm, born 1955-03 (71), male, transplant 2018-05-01 | 2080 | 56–70 | 234 (60) | ≥29 | 2000 | 3000 | 1000 | 1000 | – | 70 (actual) | W-1 E-1 P-7 K-0 PH-0 NA-1 CA-1 F-0 C-1 FB-1 (fact-check M2, L10, M1) |
| TV22 | 60 kg, G5 (no dialysis), 160 cm, born 1966-04, female, K 4.4, HCO3 20.5 | 1780 | 48–48 | 200 (50) | ≥25 | 2000 | 3000 | 900 | 1000 | – | 60 (actual) | W-1 E-1 P-2 K-2 PH-0 NA-1 CA-2 F-0 C-1 FB-1 L-BIC22 (stage-5 text variant, fact-check M4) |
| TV23 | 60 kg, G3a, 170 cm, born 2008-10 (18 by first-of-month, 17 by last-of-month), male | **422 `out_of_scope_under_18`** (fact-check M5) | | | | | | | | | | |

Intermediate values for debugging, as EER kcal → kcal/kg raw → used:

| Vector | EER kcal | raw kcal/kg | used kcal/kg | Other |
|---|---|---|---|---|
| TV02 | 2282 | 32.60 | 32.60 | |
| TV03 | 1880 | 30.32 | 30.32 | |
| TV04 | 2089 | 27.93 | 27.93 | |
| TV05 | 1731 | 33.03 | 33.03 | |
| TV06 | 2429 | 29.63 | 29.63 | |
| TV07 | 1841 | 30.68 | 30.68 | then −350 |
| TV08 | 2596 | 32.70 | 32.70 | |
| TV12 | 1691 | 29.16 | 29.16 | |
| TV13 | 2202 | 32.38 | 32.38 | |
| TV14 | 2497 | 35.68 | **35** | mean of male 2672 and female 2322 |
| TV15 | 2298 | 29.61 | 29.61 | |
| TV16 | 1921 | 27.45 | 27.45 | |
| TV17 | 2304 | 31.13 | 31.13 | |
| TV18 | 2056 | 27.59 | 27.59 | |
| TV20 | 1811 | 27.44 | **30** | E-3 floor |
| TV21 | 2076 | 29.66 | 29.66 | |
| TV22 | 1782 | 29.70 | 29.70 | |

Reference-weight checks:

| Vector | Calculation |
|---|---|
| TV04 | W25 = 25 × 1.65² = 68.06, 68.06 + 0.25 × 26.94 = 74.8 |
| TV05 | W18.5 = 53.47, 52 + 0.25 × 1.47 = 52.4 |
| TV19 | W25 = 81.90, 81.90 + 0.25 × 0.10 = 81.9 |

Machine-readable copy for `tests/data/personal_target_vectors.json`. `input` lists only non-default
fields; field names follow §4.2, with labs flattened (`potassium` in mmol/L, `phosphate` in mg/dL,
`albumin` in g/dL, `bicarbonate` in mmol/L, `uacr` in mg/g), all fresh on `today`.

```json
{"today": "2026-10-05", "vectors": [
  {"id": "TV01", "input": {"weight_kg": 70, "ckd_stage": "3b"}, "expect": {"targets": {"calories_kcal": 2100, "protein_g": {"min": 56, "max": 56}, "carbs_g": 236, "carbs_per_meal_g": 60, "fiber_g": {"min": 29}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 70.0, "weight_basis": "actual_no_height", "age": null, "nutrition_risk": [], "rules": ["W-2", "E-2", "P-2", "K-0", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV02", "input": {"weight_kg": 70, "ckd_stage": "3b", "height_cm": 175, "birth_month": "1971-03", "sex": "male"}, "expect": {"targets": {"calories_kcal": 2280, "protein_g": {"min": 56, "max": 56}, "carbs_g": 257, "carbs_per_meal_g": 65, "fiber_g": {"min": 32}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 70.0, "weight_basis": "actual", "age": 55, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-2", "K-0", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV03", "input": {"weight_kg": 62, "ckd_stage": "3b", "height_cm": 160, "birth_month": "1954-06", "sex": "female", "activity": "low_active"}, "expect": {"targets": {"calories_kcal": 1880, "protein_g": {"min": 50, "max": 62}, "carbs_g": 212, "carbs_per_meal_g": 55, "fiber_g": {"min": 26}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 62.0, "weight_basis": "actual", "age": 72, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-2", "P-5", "K-0", "PH-0", "NA-1", "CA-1", "F-0o", "C-1", "FB-1"]}},
  {"id": "TV04", "input": {"weight_kg": 95, "ckd_stage": "4", "height_cm": 165, "birth_month": "1981-01", "sex": "female", "potassium": 5.3}, "expect": {"targets": {"calories_kcal": 2090, "protein_g": {"min": 60, "max": 60}, "carbs_g": 235, "carbs_per_meal_g": 60, "fiber_g": {"min": 29}, "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 74.8, "weight_basis": "adjusted_above_bmi25", "age": 45, "nutrition_risk": [], "rules": ["W-3", "E-1", "P-2", "K-3", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV05", "input": {"weight_kg": 52, "ckd_stage": "4", "height_cm": 170, "birth_month": "1946-02", "sex": "male", "frail_or_sarcopenic": true}, "expect": {"targets": {"calories_kcal": 1730, "protein_g": {"min": 42, "max": 52}, "carbs_g": 195, "carbs_per_meal_g": 50, "fiber_g": {"min": 24}, "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 52.4, "weight_basis": "adjusted_below_bmi18_5", "age": 80, "nutrition_risk": ["low_bmi", "frailty"], "rules": ["W-4", "N-1", "E-1", "P-2", "P-5", "K-0", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV06", "input": {"weight_kg": 85, "ckd_stage": "5", "dialysis": "hemodialysis", "height_cm": 180, "birth_month": "1966-09", "sex": "male", "urine_output_ml": 300, "potassium": 5.8, "phosphate": 6.1}, "expect": {"targets": {"calories_kcal": 2430, "protein_g": {"min": 82, "max": 98}, "carbs_g": 273, "carbs_per_meal_g": 70, "fiber_g": {"min": 34}, "sodium_mg": 2000, "potassium_mg": 2500, "phosphorus_mg": 800, "calcium_mg": 1000, "fluid_ml": 1300}, "reference_weight_kg": 82.0, "weight_basis": "adjusted_above_bmi25", "age": 60, "nutrition_risk": [], "rules": ["W-3", "E-1", "P-3", "K-4", "PH-3", "NA-1", "CA-2", "F-2", "C-1", "FB-1"]}},
  {"id": "TV07", "input": {"weight_kg": 60, "ckd_stage": "5", "dialysis": "peritoneal", "height_cm": 158, "birth_month": "1976-05", "sex": "female", "urine_output_ml": 800, "pd_uf_ml": 900, "pd_dialysate_kcal": 350, "potassium": 3.2}, "expect": {"targets": {"calories_kcal": 1490, "protein_g": {"min": 60, "max": 72}, "carbs_g": 168, "carbs_per_meal_g": 40, "fiber_g": {"min": 21}, "sodium_mg": 2000, "potassium_mg": null, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": 1700}, "reference_weight_kg": 60.0, "weight_basis": "actual", "age": 50, "nutrition_risk": [], "rules": ["W-1", "E-1", "E-4", "P-3", "K-1", "PH-0", "NA-1", "CA-2", "F-4", "C-1", "FB-1"]}},
  {"id": "TV08", "input": {"weight_kg": 80, "ckd_stage": "2", "height_cm": 178, "birth_month": "1986-04", "sex": "male", "transplant_date": "2024-09-15", "phosphate": 2.2}, "expect": {"targets": {"calories_kcal": 2600, "protein_g": {"min": 64, "max": 79}, "carbs_g": 293, "carbs_per_meal_g": 75, "fiber_g": {"min": 36}, "sodium_mg": 2000, "potassium_mg": 4000, "phosphorus_mg": null, "calcium_mg": {"min": 1000, "max": 2500}, "fluid_ml": null}, "reference_weight_kg": 79.4, "weight_basis": "adjusted_above_bmi25", "age": 40, "nutrition_risk": [], "rules": ["W-3", "E-1", "P-7", "K-0", "PH-1", "NA-1", "CA-3", "F-0", "C-1", "FB-1"]}},
  {"id": "TV09", "input": {"weight_kg": 80, "ckd_stage": "3a", "height_cm": 178, "birth_month": "1986-04", "sex": "male", "transplant_date": "2026-08-24"}, "expect": {"error": "out_of_scope_early_transplant"}},
  {"id": "TV10", "input": {"weight_kg": 60, "ckd_stage": "3a", "height_cm": 165, "birth_month": "1994-01", "sex": "female", "pregnant_or_breastfeeding": true}, "expect": {"error": "out_of_scope_pregnancy"}},
  {"id": "TV11", "input": {"weight_kg": 55, "ckd_stage": "3a", "height_cm": 165, "birth_month": "2009-01", "sex": "male"}, "expect": {"error": "out_of_scope_under_18"}},
  {"id": "TV12", "input": {"weight_kg": 58, "ckd_stage": "2", "diabetes": "none", "height_cm": 158, "birth_month": "1958-03", "sex": "female", "potassium": 4.4}, "expect": {"targets": {"calories_kcal": 1690, "protein_g": {"min": 58, "max": 70}, "carbs_g": 190, "carbs_per_meal_g": 50, "fiber_g": {"min": 24}, "sodium_mg": 2000, "potassium_mg": 4000, "phosphorus_mg": 1000, "calcium_mg": {"min": 1200, "max": 2000}, "fluid_ml": null}, "reference_weight_kg": 58.0, "weight_basis": "actual", "age": 68, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-1", "P-5", "K-2", "PH-0", "NA-1", "CA-3", "F-0o", "C-1", "FB-1"]}},
  {"id": "TV13", "input": {"weight_kg": 68, "ckd_stage": "5", "height_cm": 172, "birth_month": "1968-07", "sex": "male", "potassium": 4.6, "phosphate": 4.0}, "expect": {"targets": {"calories_kcal": 2200, "protein_g": {"min": 54, "max": 54}, "carbs_g": 248, "carbs_per_meal_g": 60, "fiber_g": {"min": 31}, "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 68.0, "weight_basis": "actual", "age": 58, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-2", "K-2", "PH-2", "NA-1", "CA-2", "F-0", "C-1", "FB-1"]}},
  {"id": "TV14", "input": {"weight_kg": 70, "ckd_stage": "3a", "height_cm": 168, "birth_month": "1976-10", "activity": "active", "albumin": 3.4}, "expect": {"targets": {"calories_kcal": 2450, "protein_g": {"min": 56, "max": 70}, "carbs_g": 276, "carbs_per_meal_g": 70, "fiber_g": {"min": 34}, "sodium_mg": 2000, "potassium_mg": 4000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 70.0, "weight_basis": "actual", "age": 50, "nutrition_risk": ["low_albumin"], "rules": ["W-1", "N-1", "E-1", "P-2", "P-5", "K-0", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1", "L-ALB"]}},
  {"id": "TV15", "input": {"weight_kg": 78, "ckd_stage": "5", "dialysis": "hemodialysis", "height_cm": 176, "birth_month": "1961-11", "sex": "male", "hyperkalemia_history": true, "potassium": 4.7}, "expect": {"targets": {"calories_kcal": 2300, "protein_g": {"min": 78, "max": 93}, "carbs_g": 259, "carbs_per_meal_g": 65, "fiber_g": {"min": 32}, "sodium_mg": 2000, "potassium_mg": 2500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": 1500}, "reference_weight_kg": 77.6, "weight_basis": "adjusted_above_bmi25", "age": 64, "nutrition_risk": [], "rules": ["W-3", "E-1", "P-3", "K-2h", "PH-0", "NA-1", "CA-2", "F-1", "C-1", "FB-1"]}},
  {"id": "TV16", "input": {"weight_kg": 70, "ckd_stage": "4", "height_cm": 170, "birth_month": "1961-05", "sex": "female", "potassium": 6.3}, "expect": {"targets": {"calories_kcal": 1920, "protein_g": {"min": 56, "max": 70}, "carbs_g": 216, "carbs_per_meal_g": 55, "fiber_g": {"min": 27}, "sodium_mg": 2000, "potassium_mg": 2000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 70.0, "weight_basis": "actual", "age": 65, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-2", "P-5", "K-5", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"], "alerts": [{"level": "urgent", "code": "potassium_very_high"}]}},
  {"id": "TV17", "input": {"weight_kg": 74, "ckd_stage": "3b", "height_cm": 178, "birth_month": "1966-01", "sex": "male", "weight_6_months_ago_kg": 80}, "expect": {"targets": {"calories_kcal": 2300, "protein_g": {"min": 59, "max": 74}, "carbs_g": 259, "carbs_per_meal_g": 65, "fiber_g": {"min": 32}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 74.0, "weight_basis": "actual", "age": 60, "nutrition_risk": ["weight_loss"], "rules": ["W-1", "N-1", "E-1", "P-2", "P-5", "K-0", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV18", "input": {"weight_kg": 76, "ckd_stage": "3b", "height_cm": 172, "birth_month": "1971-08", "sex": "female", "potassium": 4.8, "bicarbonate": 19.0, "uacr": 450}, "expect": {"targets": {"calories_kcal": 2060, "protein_g": {"min": 60, "max": 60}, "carbs_g": 232, "carbs_per_meal_g": 60, "fiber_g": {"min": 29}, "sodium_mg": 2000, "potassium_mg": 4000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 74.5, "weight_basis": "adjusted_above_bmi25", "age": 55, "nutrition_risk": [], "rules": ["W-3", "E-1", "P-2", "K-2", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1", "L-BIC22", "L-UACR-A3"]}},
  {"id": "TV19", "input": {"weight_kg": 82, "ckd_stage": "4", "height_cm": 181, "potassium": 4.9}, "expect": {"targets": {"calories_kcal": 2460, "protein_g": {"min": 66, "max": 66}, "carbs_g": 277, "carbs_per_meal_g": 70, "fiber_g": {"min": 34}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 81.9, "weight_basis": "adjusted_above_bmi25", "age": null, "nutrition_risk": [], "rules": ["W-3", "E-2", "P-2", "K-2", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV20", "input": {"weight_kg": 66, "ckd_stage": "5", "dialysis": "hemodialysis", "height_cm": 165, "birth_month": "1956-02", "sex": "female", "urine_output_ml": 0, "potassium": 4.5, "albumin": 3.5}, "expect": {"targets": {"calories_kcal": 1980, "protein_g": {"min": 79, "max": 86}, "carbs_g": 223, "carbs_per_meal_g": 55, "fiber_g": {"min": 28}, "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": 1000}, "reference_weight_kg": 66.0, "weight_basis": "actual", "age": 70, "nutrition_risk": ["low_albumin"], "rules": ["W-1", "N-1", "E-1", "E-3", "P-3", "P-6", "K-2", "PH-0", "NA-1", "CA-2", "F-2", "C-1", "FB-1", "L-ALB"]}},
  {"id": "TV21", "input": {"weight_kg": 70, "ckd_stage": "4", "height_cm": 170, "birth_month": "1955-03", "sex": "male", "transplant_date": "2018-05-01"}, "expect": {"targets": {"calories_kcal": 2080, "protein_g": {"min": 56, "max": 70}, "carbs_g": 234, "carbs_per_meal_g": 60, "fiber_g": {"min": 29}, "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 70.0, "weight_basis": "actual", "age": 71, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-7", "K-0", "PH-0", "NA-1", "CA-1", "F-0", "C-1", "FB-1"]}},
  {"id": "TV22", "input": {"weight_kg": 60, "ckd_stage": "5", "height_cm": 160, "birth_month": "1966-04", "sex": "female", "potassium": 4.4, "bicarbonate": 20.5}, "expect": {"targets": {"calories_kcal": 1780, "protein_g": {"min": 48, "max": 48}, "carbs_g": 200, "carbs_per_meal_g": 50, "fiber_g": {"min": 25}, "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 900, "calcium_mg": 1000, "fluid_ml": null}, "reference_weight_kg": 60.0, "weight_basis": "actual", "age": 60, "nutrition_risk": [], "rules": ["W-1", "E-1", "P-2", "K-2", "PH-0", "NA-1", "CA-2", "F-0", "C-1", "FB-1", "L-BIC22"]}},
  {"id": "TV23", "input": {"weight_kg": 60, "ckd_stage": "3a", "height_cm": 170, "birth_month": "2008-10", "sex": "male"}, "expect": {"error": "out_of_scope_under_18"}}
]}
```

### 5.2 eGFR, categories and conversions

The unrounded value is to 3 decimals. Assert the rounded integer and category, and the unrounded
value to ±0.01.

| ID | Equation | Inputs | eGFR (unrounded) | Rounded | Category |
|---|---|---|---|---|---|
| E1 | CKD-EPI 2021 cr | female 50 y, Scr 1.2 mg/dL | 55.147 | 55 | G3a |
| E2 | CKD-EPI 2021 cr | male 50 y, Scr 1.2 | 73.674 | 74 | G2 |
| E3 | CKD-EPI 2021 cr | male 70 y, Scr 2.0 | 35.243 | 35 | G3b |
| E4 | CKD-EPI 2021 cr | female 65 y, Scr **106 µmol/L** (= 1.1991 mg/dL) | 50.280 | 50 | G3a |
| E5 | CKD-EPI 2021 cr | female 30 y, Scr 0.6 (below κ: α branch) | 123.758 | 124 | G1 |
| E6 | CKD-EPI 2021 cr-cys | male 60 y, Scr 1.5, Scys 1.6 mg/L | 47.165 | 47 | G3a |
| E7 | CKD-EPI 2012 cys | female 40 y, Scys 1.2 | 61.630 | 62 | G2 |
| E8/E9 | CKD-EPI 2021 cr, **sex unspecified** | 60 y, Scr 1.1 | F 57.525 / M 76.851 | 58 / 77 | G3a / G2 → **no suggestion**, show range |
| E10 | CKD-EPI 2021 cr | female 75 y, Scr 4.8 | 8.944 | 9 | G5 |

| Conversion / edge | Input | Expected |
|---|---|---|
| U1 | creatinine 106 µmol/L | 1.199 mg/dL |
| U2 | phosphate 1.94 mmol/L | 6.008 mg/dL (shown 6.0) |
| U3 | albumin 34 g/L | 3.4 g/dL |
| U4 | UACR 25 mg/mmol | stored 221.2 mg/g; category from the entered unit: 25 mg/mmol → A2 |
| U5 | UACR 3.0 mg/mmol | stored 26.5 mg/g, but category **A2** (3.0 mg/mmol is A2 on the mg/mmol scale; converting first would wrongly give A1) |
| U6 | A1c 53 mmol/mol | 7.0 % |
| U7 | UACR edges, mg/g, 1-decimal display | 29.9 → A1; 29.96 → 30.0 → A2; 300.0 → A2; 300.04 → A2; 300.05 → 300.1 → A3 |

U5 is a deliberate trap. KDIGO's mg/mmol and mg/g columns are **approximately** equivalent
(3 mg/mmol ≈ 26.5 mg/g by the 0.113 factor). Implement `albuminuria_category(value, unit)` with
each unit's own thresholds: < 3 / 3–30 / > 30 for mg/mmol, < 30 / 30–300 / > 300 for mg/g. Do not
convert before categorising.

### 5.3 Existing v0.2 tests whose expectations change

| Test | Old | New |
|---|---|---|
| `test_suggest_targets_non_dialysis_stage_3b_70kg` (type1) | protein 42–56, no `fiber_g` | **protein 56–56**; add `"fiber_g": {"min": 29}` |
| `test_suggest_targets_stage_4_protein_range` (70 kg, default type1) | 42–56 | **56–56** |
| `test_dosing_weight_…` (100 kg @ 170) | `(72.3, "ideal_bmi_25")` | `(79.2, "adjusted_above_bmi25")` |
| `test_dosing_weight_…` (45 kg @ 170) | `(53.5, "ideal_bmi_18.5")` | `(47.1, "adjusted_below_bmi18_5")` |
| `test_dosing_weight_…` (72.25 kg @ 170) | `(72.25, "actual")` | `(72.3, "actual")` (ref now rounded to 0.1) |
| `test_suggest_targets_use_ideal_body_weight_…`, 100 kg @ 170, G4 type1 | 2169 kcal, protein 43–58 | **2380 kcal, protein 63–63** |
| same, 100 kg without height | 3000 kcal, protein 60–80 | 3000 kcal, **protein 80–80** |
| same, 45 kg | 1605 kcal, protein 32–43 | **1410 kcal, protein 38–47** (BMI 15.6 → nutrition risk → P-5) |
| same | note contains "ideal body weight" | note contains "adjusted weight" / "Weight basis" |
| `test_protein_note_…` | "KDOQI 2020 3.1.3", "3.1.1" | diabetic note: **"KDOQI 2020 3.0.2"**, **"ADA 2026 Rec 11.3"**, "not recommended"; non-diabetic: **"3.0.1"**, "KDIGO 2024 Rec 3.3.1.1", still `{"min": 42, "max": 56}` |
| `tests/test_api.py::test_suggested_targets_from_profile` (70 kg, 3b) | 42–56 | **56–56** |
| `tests/test_api.py::test_suggested_targets_use_the_saved_height…` | 2169, 43–58, "ideal body weight"; no height 60–80 | 2380, **63–63**, "adjusted weight"; no height **80–80** |
| `test_suggest_targets_match_research_json` | JSON rows 3a, 3b, 4, 5 have `protein_g_per_kg_min` 0.6 | change those four rows to **0.8** (the test calls the default `type1`); calories unchanged because 30 × 70 = 2100 is already a multiple of 10 |

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| **Targets read as prescriptions** (safety; F15 regulatory) | "Starting point" wording on every note; rule, source and "expert opinion" badge visible; nothing saved without the user; admin switch `targets.lab_rules_enabled`; README and handbook disclaimers unchanged |
| **Wrong lab unit** (6.1 mmol/L phosphate entered as mg/dL → missed high) | Mandatory unit picker; plausibility ranges; converted value echoed before save; per-user unit default |
| **Stale labs** drive targets | Freshness windows (90/180/365 days); notes print the result date; stale → K-0/PH-0 defaults |
| **Relaxing potassium when K is normal**, then K rises (RAAS inhibitors, progression) | One step only; history flag keeps the ladder; 90-day freshness; K-3/K-4 tighten at > 5.0/5.5; KDIGO Table 28 alert on entry. The HD step (2500 → 3000) is flagged for the C10 reviewer (fact-check L15) |
| **Protein restriction without supervision** (malnutrition, hypoglycaemia in type 1 diabetes) | Diabetes at G3–G5: 0.8 g/kg floor (P-2d). No diabetes: 0.6 lower bound kept with explicit "close supervision" wording (P-2n) and listed for C10 review. Older or at-risk people move up (P-5). Dialysis never restricts (P-3, P-6) |
| **Fluid floor where fluid should be limited** (advanced CKD, heart failure) | F-0o only at G1–G3b; text excludes heart failure and swelling; no floor on dialysis |
| **Albumin assay differences** (bromocresol purple reads lower) | L-ALB note tells the person to ask whether the result counts as low for their lab |
| EER not validated in CKD or dialysis (KDOQI 1.4.2 prefers disease-specific REE equations on dialysis) | Clamp to KDOQI 25–35; nutrition-risk floor; notes say "estimate"; MHDE kept as a later option |
| The reference-weight formula is an opinion (KDOQI 1.1.6) | Documented basis in the first note; care team overrides; JS/Python parity tests stop drift |
| "Unspecified" sex or a gender-affirming-therapy user gets misleading eGFR | Show both formulas and refuse a category when they disagree; help text defers to the clinician |
| Age and sex are extra personal data | Birth **month**, not date; optional; covered by note 01's encryption, backup and deletion scope |
| AI layer contradicts the numbers | The AI may explain `rules`/`notes` only. Targets come solely from `app/targets.py`; the AI prompt receives `derived` and `rules` read-only (AI-guidance note) |
| Sources move (ADA yearly, KDIGO 2026 diabetes update pending) | §8 re-verify list; the rule catalogue keeps the source string in one place (`app/target_rules.py`) |
| PD dialysate kcal entered wrongly | 0–1000 limit; food floor 20 kcal/kg ref; note shows the subtraction |
| GLIM and ISRNM thresholds checked against secondary reproductions, not the primary PDFs | Marked in F12; read the primary tables before release (§8) |

---

## 7. Implementation checklist

**C1. Fix citations** (no behaviour change, ship first):
* In `app/nutrients.py` notes, `app/static/app.js` mirror notes, `docs/research/targets_by_stage.json`
  `note` fields, `ARCHITECTURE.md` and `docs/diet-guide.md` §2/§7/§8:
  * KDOQI energy 3.0.1 → **3.1.1**;
  * protein 3.1.1 → **3.0.1**, 3.1.2 → **3.0.3**, 3.1.3 → **3.0.2**, 3.1.4 → **3.0.4**;
  * reword "per kg of ideal body weight (KDOQI)" to "per kg of a reference weight; KDOQI leaves the
    choice to the care team (1.1.6)".
* Replace the public-review-draft URL with the AJKD DOI (keep the draft as "draft" if cited).
* Update `tests/test_nutrients.py::test_protein_note…`.

**C1b. Diabetes protein floor (safety, ship with C1; fact-check H1):**
* `PROTEIN_G_PER_KG["none_ckd3plus"]` becomes `(0.8, 0.8)` when `diabetes != "none"`; keep
  `(0.6, 0.8)` for `diabetes == "none"`. Same change in the `app.js` mirror.
* `docs/research/targets_by_stage.json` rows 3a, 3b, 4, 5: `protein_g_per_kg_min` 0.6 → 0.8 and
  their `note` texts; `ARCHITECTURE.md` "Suggested targets" table; `docs/diet-guide.md` protein
  sections (ADA 2026 Rec 11.3 wording).
* Apply the protein rows of §5.3; render min = max as "about X g/day" (§4.8).

**C2. Pure modules** (one commit with tests):
* `app/units.py` (+ `tests/test_units.py`, U1–U7).
* `app/kidney_function.py` (+ `tests/test_kidney_function.py`, E1–E10, category edges, unspecified
  sex).
* `app/target_rules.py`, holding all numbers, coefficients, templates and the rule catalogue
  (§4.4, §4.5).
* `app/targets.py` implementing §4.3 exactly, with `today` injected.
* `tests/data/personal_target_vectors.json` (§5.1 JSON).
* `tests/test_targets.py`: every vector, plus property tests:
  * continuity at BMI 18.5 and 25 (Δref < 0.1 kg for Δweight 0.01 kg);
  * kcal/kg always within [25, 35] before the PD subtraction;
  * the potassium note is present in every potassium note;
  * the rule order is S → … → L;
  * with `diabetes != "none"` and no dialysis, `protein_g.min ≥ round(0.8 × ref)` for every stage
    and age (H1);
  * F-0o never appears at stage 4–5 (M1); P-5 never raises a graft at G3a–G5 (M2);
  * a birth month whose 18th birthday could still be ahead in that month is refused (M5).

**C3. Wrapper:**
* `nutrients.suggest_targets()` builds `targets.Inputs` from its v0.2 arguments and returns
  `{"targets", "notes"}`.
* `dosing_weight()` delegates to `targets.reference_weight()`.
* Apply the §5.3 test changes. `pytest` stays green.

**C4. Data model:**
* Migration in `app/db.py` (§4.6), plus `tests/test_migrations.py`: a v0.2 database upgrades in
  place, defaults are correct, and `lab_results` is created.
* Pydantic literals and fields in `app/models.py`.
* `ProfileUpdate` validation (§4.2 ranges, `birth_month` regex `^\d{4}-(0[1-9]|1[0-2])$`, not in
  the future, age ≤ 120).

**C5. API:**
* `app/profile.py` gathers fresh labs (`max(taken_on)` per analyte within the window) and calls
  `targets.suggest()`.
* Map `OutOfScope` to 422 `{"detail": {"code", "message"}}`.
* Add `rules`, `derived`, `missing_inputs` and `alerts` to `SuggestedTargets`.
* New `app/labs.py` router (CRUD, kidney-function, potassium alert on POST), registered in
  `app/main.py`.
* `tests/test_labs_api.py`.

**C6. Settings:** read `targets.*` keys (§4.9) via the settings store from the settings note. Add a
test that `lab_rules_enabled=false` falls back to K-0/PH-0 but still returns the potassium alert on
lab entry.

**C7. Frontend (`app/static/`):**
* Profile "About you" fields with conditional dialysis and transplant fields.
* Labs view with a unit picker and conversion echo.
* eGFR card.
* "Why this number?" disclosure with opinion badges.
* Diff view on Suggest.
* Min-only goal rendering (fibre).
* Urgent potassium banner.
* Accessible: labels, `aria-describedby` for help texts, no colour-only status.

**C8. JS mirror parity:**
* Port `targets.suggest`, `reference_weight`, EER, eGFR and unit conversion to `app.js`.
* Extend the preview parity harness to run `tests/data/personal_target_vectors.json` through both
  implementations and compare targets, rules and notes byte for byte.
* `node --check`; `tests/test_preview_build.py`.

**C9. Docs:**
* `ARCHITECTURE.md`: replace "Suggested targets" with §4.3–§4.6 and the rule catalogue.
* `docs/diet-guide.md`: a patient-facing "How your targets are personalised" section (age, sex,
  activity, weight, labs) and sources.
* README "How targets and warnings work" paragraph.
* Patient handbook (sibling note): link to this rule catalogue.

**C10. Safety review before release:**
* Have a renal dietitian or nephrologist review §4.4 rows marked **[OPINION]** and the K-5 alert
  wording, and decide the open fact-check items: the P-2n 0.6 g/kg lower bound without diabetes
  (M6) and the one-step potassium relaxation on hemodialysis (L15).
* Record the reviewer and date in this note's header.
* Until then, ship with `targets.lab_rules_enabled=false` on public demo instances.

**C11. Re-verify** the items in §8 and update the "Re-verify" row.

---

## 8. How to re-verify

| Item | Check | Where |
|---|---|---|
| KDIGO 2026 Diabetes-in-CKD | Final published? Did Chapter 3 (nutrition: protein 0.8, sodium < 2 g) change? Public review closed 2026-04-13; scope named Chapters 1, 2 and 4 | kdigo.org/guidelines/diabetes-ckd |
| ADA Standards 2027 | Sections 5 (fibre 5.24), 11 (protein 11.3), 13 (older-adult protein wording and number) | diabetesjournals.org/care, supplement 1 |
| ADA 2026 Section 13 verbatim | **Done 2026-10-05:** Rec 13.11a, grade B (§10). Re-check only when ADA 2027 is out | pmc.ncbi.nlm.nih.gov/articles/PMC12690186 |
| KDOQI nutrition | Any update after 2020 or an erratum (Table 5's "127 cm") | ajkd.org |
| NASEM DRIs | Energy (2023) and sodium/potassium (2019) still current; calcium (2011) review status | nationalacademies.org/read/… (the old nap.nationalacademies.org/read links now 301-redirect) |
| CKD-EPI / EKFC | Has NKF-ASN or KDIGO changed the recommended US equation? | kidney.org CKD-EPI pages |
| GLIM and ISRNM thresholds | Checked against secondary reproductions on 2026-10-05 (§10); read the primary tables once before release | Clin Nutr 2019; Kidney Int 2008; PMC4222262 (ISRNM table) |
| Hyperkalaemia thresholds | UK Kidney Association hyperkalaemia guideline revision (source of KDIGO Table 28) | ukkidney.org |
| FDA / EU MDR | Any change to the device-software policy or MDCG 2019-11 | fda.gov; health.ec.europa.eu |

---

## 9. Sources

Guidelines and reference values:

1. Ikizler TA, Burrowes JD, Byham-Gray LD, et al. **KDOQI Clinical Practice Guideline for Nutrition in CKD: 2020 Update.** *Am J Kidney Dis* 2020;76(3 Suppl 1):S1–S107. https://doi.org/10.1053/j.ajkd.2020.05.006 — read from the typeset AJKD PDF at https://www.nefrologialombardia.it/public/ckeditor/data/linee-guida-2020-nutrizione-nella-malattia-renale-cronica.pdf. Statements 1.1.6–1.1.11, 1.2.1–1.2.2, 1.4.1–1.4.2, 3.0.1–3.0.4, 3.1.1, 4.1.1, 5.0.1, 6.1.1–6.5.3; Table 5; "metabolically stable" definition. Public-review draft (Oct 2019, differs, F1): https://www.kidney.org/sites/default/files/Nutrition_GL%2BSubmission_101719_Public_Review_Copy.pdf
2. KDIGO. **2024 Clinical Practice Guideline for the Evaluation and Management of CKD.** *Kidney Int* 2024;105(4S):S117–S314. https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf — Recs 1.2.2.1, 1.2.4.1, 3.3.1.1, 3.3.2.1; PPs 1.1.3.2, 1.2.4.1–3, 3.3.1.1–3.3.1.5, 3.3.2.1–2, 3.10.1–2, 3.11.5.1–2; Tables 3, 14, 23, 24, 28; Figure 32; conversion factors; sex, gender and older-adult considerations.
3. KDIGO. **2022 Clinical Practice Guideline for Diabetes Management in CKD.** *Kidney Int* 2022;102(5S):S1–S127. https://kdigo.org/wp-content/uploads/2023/12/KDIGO-2022-Diabetes-Guideline.pdf — Rec 3.1.1, PP 3.1.2, Rec 3.1.2, PP 2.1.2. 2026 update draft notice: https://kdigo.org/kdigo-2026-diabetes-and-ckd-guideline-draft-available-for-public-review/
4. American Diabetes Association. **Standards of Care in Diabetes—2026**, *Diabetes Care* 2026;49(Suppl 1):
   * Section 5: https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188 — Rec 5.24 fibre (B), verified verbatim 2026-10-05.
   * Section 11: https://pmc.ncbi.nlm.nih.gov/articles/PMC12690176 — Rec 11.3 (A/B) and "below … 0.8 g/kg/day is not recommended", re-verified verbatim 2026-10-05.
   * Section 13, Older Adults: https://pmc.ncbi.nlm.nih.gov/articles/PMC12690186 — Rec 13.11a (B), protein at least 0.8 g/kg, verified verbatim 2026-10-05.
5. National Academies of Sciences, Engineering, and Medicine. **Dietary Reference Intakes for Energy** (2023). https://doi.org/10.17226/26818 — Table S-1/S-3 (https://www.nationalacademies.org/read/26818/chapter/2), Table 7-1 and PAL ranges (https://www.nationalacademies.org/read/26818/chapter/9).
6. NASEM. **Dietary Reference Intakes for Sodium and Potassium** (2019). https://www.nationalacademies.org/read/25353/chapter/2 — Tables S-1, S-2; "apparently healthy population".
7. Institute of Medicine. **Dietary Reference Intakes for Calcium and Vitamin D** (2011). https://www.nationalacademies.org/read/13050/chapter/2 — Table S-1.
8. Volkert D, et al. **ESPEN practical guideline: Clinical nutrition and hydration in geriatrics.** *Clin Nutr* 2022;41:958–989. https://doi.org/10.1016/j.clnu.2022.01.024 (accepted manuscript: https://ueaeprints.uea.ac.uk/83181/) — R1, R2, R61.
9. Bauer J, et al. **Evidence-based recommendations for optimal dietary protein intake in older people (PROT-AGE).** *J Am Med Dir Assoc* 2013;14:542–559. https://doi.org/10.1016/j.jamda.2013.05.021
10. Cederholm T, et al. **GLIM criteria for the diagnosis of malnutrition.** *Clin Nutr* 2019;38:1–9. https://doi.org/10.1016/j.clnu.2018.08.002
11. Fouque D, et al. **A proposed nomenclature and diagnostic criteria for protein-energy wasting in acute and chronic kidney disease (ISRNM).** *Kidney Int* 2008;73:391–398. https://doi.org/10.1038/sj.ki.5002585 ; Ikizler TA, et al. ISRNM consensus on PEW prevention and treatment. *Kidney Int* 2013;84:1096–1107 (PMID 23698226). Criteria table as reproduced in https://pmc.ncbi.nlm.nih.gov/articles/PMC4222262/table/T1
12. Kopple JD. **K/DOQI Clinical Practice Guidelines for Nutrition in Chronic Renal Failure** (2000). *Am J Kidney Dis* 2000;35(6 Suppl 2):S1–S140 (PMID 10895784) — energy by age and dialysis protein via secondary summary (https://www.qxmd.com/r/11158865); adjusted oedema-free BW via KDOQI 2020 Table 5.
13. National Kidney Foundation. **K/DOQI Bone Metabolism and Disease in CKD (2003)**, Guideline 4.1. https://www.kidney.org/sites/default/files/docs/boneguidelines.pdf ; KDIGO **2017 CKD-MBD Update**, Recs 4.1.2, 4.1.8. https://pmc.ncbi.nlm.nih.gov/articles/PMC6340919

eGFR:

14. Inker LA, et al. **New creatinine- and cystatin C–based equations to estimate GFR without race.** *N Engl J Med* 2021;385:1737–1749. https://doi.org/10.1056/NEJMoa2102953 ; NKF equation pages: https://www.kidney.org/ckd-epi-creatinine-equation-2021-0 , https://www.kidney.org/professionals/ckd-epi-creatinine-cystatin-equation-2021 , https://www.kidney.org/professionals/ckd-epi-cystatin-c-equation-2012 (Inker LA, et al. *N Engl J Med* 2012;367:20–29).

Body weight, energy and transplant:

15. Peterson CM, et al. **Universal equation for estimating ideal body weight and body weight at any BMI.** *Am J Clin Nutr* 2016;103:1197–1203. https://pmc.ncbi.nlm.nih.gov/articles/PMC4841935/
16. Current methods for developing predictive energy equations in maintenance dialysis are imprecise. https://pmc.ncbi.nlm.nih.gov/articles/PMC8979515/
17. Chadban S, et al. **The CARI guidelines. Protein requirement in adult kidney transplant recipients.** *Nephrology* 2010;15(Suppl 1):S68–S71. https://doi.org/10.1111/j.1440-1797.2010.01238.x — via reviews: Nutrition Trends in Kidney Transplant Recipients (*Front Med*), https://pmc.ncbi.nlm.nih.gov/articles/PMC6220714/ ; Dietary Guidelines Post Kidney Transplant (*Transpl Int* 2025), https://pmc.ncbi.nlm.nih.gov/articles/PMC12004285/
18. Grodstein GP, Blumenkrantz MJ, Kopple JD, et al. **Glucose absorption during continuous ambulatory peritoneal dialysis.** *Kidney Int* 1981;19:564–567 — formula Y = 11.3·X − 10.9 g/L (X = mean dialysate glucose g/dL, CAPD only, 3.7 kcal/g), via Fantuzzi AL, et al. *G Clin Nefrol Dial* 2022;34:14–21. https://doi.org/10.33393/gcnd.2022.2365

Potassium context:

19. Already in the repository (`docs/research/ckd-diet.md` refs 52 and others): American Kidney Fund potassium handout (K/DOQI 2004 stage ranges, NEJM 2017, "aim for 2,500, no more than 3,000"); Kalantar-Zadeh K, Fouque D. *N Engl J Med* 2017;377:1765–1776.

Contributor trap:

20. **Dietary Guidelines for Americans 2025–2030** (released 2026-01-07), protein 1.2–1.6 g/kg for the general public — summary: https://www.mofo.com/resources/insights/260108-new-u-s-dietary-guidelines-released

Regulatory:

21. U.S. FDA. **Policy for Device Software Functions and Mobile Medical Applications** (2022). https://www.fda.gov/regulatory-information/search-fda-guidance-documents/policy-device-software-functions-and-mobile-medical-applications ; "Step 7" summary: https://www.fda.gov/medical-devices/digital-health-center-excellence/step-7-does-device-software-functions-dsf-and-mobile-medical-applications-mma-guidance-apply ; MDCG 2019-11 (EU MDR Rule 11): https://health.ec.europa.eu/system/files/2020-09/md_mdcg_2019_11_guidance_qualification_classification_software_en_0.pdf

---

## 10. Fact-check

Done 2026-10-05 by an adversarial clinical fact-check. The reviewer assumed every rule was wrong
until a primary source confirmed it, and recomputed every number in Python from the text of this
note alone, without reading the author's scratch implementation.

### 10.1 Method

* **Independent re-implementation** of §4.3 (reference weight, nutrition risk, EER, protein,
  potassium, phosphorus, calcium, fluid, carbohydrate, fibre, lab notes, refusals), run against
  the §5.1 JSON. Result before fixes: **20 of 20 vectors matched on every field** (targets,
  reference weight, basis, age, risk reasons, rule order, alerts).
* **eGFR re-implementation** from the NKF equation pages. E1–E10 matched to ±0.001. Sanity check:
  a 50-year-old man with Scr 1.0 mg/dL gives 91.7 mL/min/1.73 m².
* **Conversions recomputed** from molar masses: creatinine 113.12 g/mol gives 88.40 µmol/L per
  mg/dL and 0.1131 mg/mmol per mg/g; phosphorus 30.97 g/mol gives 0.3229; calcium 40.08 g/mol gives
  0.2495. Potassium and bicarbonate mmol/L = mEq/L (monovalent); albumin g/dL × 10 = g/L; A1c
  NGSP % = IFCC/10.929 + 2.15. U1–U7 all matched.
* **Primary texts read:**
  * KDOQI 2020 typeset AJKD PDF, and the October 2019 public-review draft, downloaded to confirm F1;
  * KDIGO 2024 full PDF;
  * NKF CKD-EPI pages;
  * NASEM 2023 Energy, chapters 2 and 7;
  * NASEM 2019 sodium/potassium and IOM 2011 calcium DRI tables;
  * ESPEN 2022 geriatrics accepted manuscript;
  * ADA 2026 Sections 5, 11 and 13 (PMC);
  * CARI via the two cited reviews.
  * GLIM and ISRNM thresholds were checked against secondary reproductions (PMC4222262 table and
    search results); the primary PDFs were not fetched.

### 10.2 Confirmed without change

* CKD-EPI 2021 creatinine:
  * constant 142;
  * κ 0.7 (F) / 0.9 (M);
  * α −0.241 (F) / −0.302 (M);
  * −1.200 exponent on max(Scr/κ, 1);
  * age factor 0.9938^age;
  * female multiplier ×1.012.
* CKD-EPI 2021 creatinine–cystatin C:
  * constant 135;
  * α −0.219 (F) / −0.144 (M);
  * exponents −0.544 (max creatinine term), −0.323 (min cystatin term), −0.778 (max cystatin term);
  * age factor 0.9961^age;
  * female multiplier ×0.963.
* CKD-EPI 2012 cystatin C: 133, −0.499, −1.328, 0.996^age, ×0.932.
* KDIGO 2024:
  * G and A category limits, including the mg/mmol column;
  * conversion factors (the PDF does print "mmol/l" for creatinine, a lost µ);
  * Rec 3.3.1.1 (2C) and PPs 3.3.1.1–3.3.1.5;
  * Rec 3.3.2.1 (2C) and PPs 3.3.2.1–3.3.2.2;
  * PP 3.10.1 (< 18 mmol/L) and PPs 3.11.5.1–3.11.5.2;
  * Recs 1.2.2.1 (1C) and 1.2.4.1 (1D), and PPs 1.2.4.1–3 and 1.1.3.2;
  * Table 24 (K differs ≤ 0.2 mmol/L by sex and age);
  * Table 28 (6.0–6.4 moderate, ≥ 6.5 severe);
  * Figure 32 (> 5.5);
  * the fertility and pregnancy scope statement;
  * the 1.0–1.2 g/kg geriatric rationale.
* KDOQI 2020:
  * statement numbers, wording and grades of 1.1.6, 1.1.8 (2B), 1.1.11, 1.2.1, 1.2.2 (1A),
    1.4.2 (2C), 3.0.1 (1A/2C), 3.0.2 (OPINION), 3.1.1 (1C), 4.1.1 (2D), 5.0.1, 6.1.1 (2C),
    6.1.2 (1C), 6.1.3, 6.2.1 (2B), 6.2.2, **6.3.1 (1B)**, 6.3.2, 6.3.3, 6.4.1, 6.4.2 (2D),
    6.5.1 (1B/1C/1C) and 6.5.2 (2A);
  * the "metabolically stable" definition, including antibiotics and immunosuppressants;
  * Table 5 formulas and cautions, including the "5'0" (127 cm)" typo.
* KDOQI 2019 draft (F1): energy 3.0.1; protein 3.1.1–3.1.4; diabetes 3.1.3 "0.8 – 0.9 g/kg ideal
  body weight"; "ideal" body weight throughout.
* NASEM 2023 Table S-1:
  * all 16 coefficients;
  * RMSE 339 (men) and 246 (women) kcal/day;
  * PAL limits 1.53, 1.68, 1.85 and 2.50 (Table 7-10's footnote prints 1.69, a NASEM
    inconsistency that does not matter here);
  * the "including … chronic diseases" population wording.
* NASEM 2019 potassium AI 3400 / 2600 mg and sodium AI 1500 mg / CDRR 2300 mg for all adults,
  "apparently healthy population".
* IOM 2011 calcium RDA and UL by age and sex.
* ESPEN 2022 (all grade B):
  * R1, 30 kcal/kg;
  * R2, at least 1 g/kg;
  * R61, 1.6 L for women and 2.0 L for men;
  * the commentary figures 27–30 kcal/kg (ill) and 32–38 kcal/kg (BMI ≤ 21).
* ADA 2026 Rec 5.24 (B).
* CARI: about 1.4 g/kg for 4 weeks; 0.75 / 0.8 g/kg long term.
* DGA 2025–2030 (1.2–1.6 g/kg, released 2026-01-07).
* KDIGO 2026 diabetes guideline: still a draft (public review closed 2026-04-13).
* Hamwi, Devine, Robinson and Karkeck values in §3.1, and option values 72.3, 75.2, 70.8, 93.1 and
  79.2.

### 10.3 Findings and changes

Severity: **High** means it could plausibly harm a user of the target population (adults with CKD
and type 1 diabetes). **Medium** is a safety gap or guideline conflict in a narrower group.
**Low** is a citation, wording, rounding or consistency error.

| # | Sev. | Finding | Change made in this note | Source |
|---|---|---|---|---|
| H1 | **High** | P-2 suggested **0.6–0.8 g/kg for diabetes** at G3a–G5 without dialysis. Only KDOQI 3.0.2 (OPINION) goes below 0.8, and only "under close clinical supervision" in metabolically stable people, which excludes "poorly controlled diabetes". The app cannot verify either. ADA 2026 Rec 11.3 (A) says 0.8 g/kg and that going below it "is not recommended" with diabetes; KDIGO 2022 Rec 3.1.1 (2C) and KDIGO 2024 Rec 3.3.1.1 (2C) say 0.8. The danger is protein-energy wasting, plus hypoglycaemia with insulin. | P-2d is now **0.8–0.8 g/kg**. Changed: F4, §4.1, §4.3, §4.4, the P-2d text, the §4.6 example, the §4.8 "about X g" rendering, TV01/02/04/13/18/19, the §5.3 test table, and checklist C1b (including `targets_by_stage.json`) | PMC12690176 (ADA §11); KDIGO 2022 and 2024 PDFs; KDOQI 2020 3.0.2 and the "metabolically stable" text |
| M1 | Medium | F-0o advised **drinking at least 1.6 / 2.0 L** to everyone aged 65 or over not on dialysis, including G4–G5. ESPEN's own commentary says "heart, and renal failure may need a restriction of fluid intake", and at G4–G5 free-water excretion is limited (hyponatraemia, overload). | F-0o now applies only at native or graft G1–G3b; the text excludes heart failure and swelling. TV05 and TV16 now give F-0. Changed: F9, F16, §4.3, §4.4 | ESPEN 2022 R61 and its commentary |
| M2 | Medium | P-5 raised **transplant** protein to 1.0–1.2 g/kg for anyone 65 or over or at risk, **whatever the graft stage**. That is above the native-kidney G3–G5 rule (0.8–1.0), against PROT-AGE's eGFR < 30 exception, and contradicts option B's own rejection ("too high at G4–G5"). | The raise applies only at graft G1–G2; at graft G3a–G5 P-7 (0.8–1.0) stays, with an added sentence. New vector TV21. Changed: §3.4, F16, §4.3, §4.4, P-7 text | PROT-AGE 2013; KDIGO 2024 PP 3.3.1.5 rationale |
| M3 | Medium | The K-5 text for **6.0–6.4 mmol/L** said only "contact your care team today". KDIGO Table 28 says to repeat within 24 h, or to assess and treat **in hospital** if clinically unwell. | The urgency text now gives the 24 h repeat and "if you feel unwell … get urgent medical care now"; the catalogue row is updated | KDIGO 2024 Table 28 |
| M4 | Medium | L-BIC22 told everyone to eat **more fruit and vegetables** for low bicarbonate. KDOQI 6.1.1 covers CKD 1–4 only, and at G5 or on dialysis this conflicts with the potassium ceiling; the `k_caveat` fired only when K > 5.0. | The fruit-and-vegetable sentence now appears only at G1–G4 without dialysis; G5 and dialysis get the bicarbonate sentence alone. New vector TV22 | KDOQI 2020 6.1.1–6.1.3 |
| M5 | Medium | The **under-18 refusal leaked**. Age counted from the *first* day of the birth month calls a person born 2008-10-20 "18" on 2026-10-05, so a 17-year-old got adult targets. | S-2 now counts age from the *last* day of the birth month. New vector TV23. Changed: §4.2, §4.4 | KDIGO 2024 PP 3.3.1.4 (children); project refusal policy |
| M6 | Medium | P-2n (no diabetes) keeps a **0.6 g/kg lower bound** that KDOQI 3.0.1 (1A) and KDIGO PP 3.3.1.2 tie to close supervision; KDIGO PP 3.3.1.3 forbids it when metabolically unstable. | Numbers unchanged (they are inside KDOQI 3.0.1); the P-2n text now names supervision and the PP 3.3.1.3 exclusions. Listed as an open decision in C10 | KDOQI 2020 3.0.1; KDIGO 2024 PP 3.3.1.2–3 |
| L1 | Low | F4 implied that 3.0.3 = HD and 3.0.4 = PD. In fact 3.0.3 is dialysis without diabetes (1C on HD, OPINION on PD) and 3.0.4 is dialysis with diabetes (OPINION). | F4 row split; P-3 catalogue grades corrected | KDOQI 2020 text |
| L2 | Low | The ADA Section 13 protein statement was unverified, with no number or grade. | Now cited as **Rec 13.11a, grade B**, verbatim, in F4, P-5, P-5a, §8 and §9 | PMC12690186 |
| L3 | Low | The BMI-25 column of the IBW table used round-half-even (56.2, 72.2, 90.2), against the note's half-up rule and its own "72.3". | Now 56.3, 72.3 and 90.3; the rounding is stated | Recomputed |
| L4 | Low | "Hamwi/Devine/Robinson imply BMI 21–24 for men"; the table shows 20.2–24.5. | Now "about 20–24.5" | Recomputed |
| L5 | Low | NASEM "active" was described as "about 1½ h of moderate exercise". Table 7-1 gives 30–50 min of walking plus 45 min of moderate cycling and 40 min of doubles tennis (the text calls it about 85 min of vigorous activity). | F3 rewritten from Table 7-1 | NASEM 2023 ch. 7 |
| L6 | Low | Fibre Rec 5.24 was cited "via Guideline Central summary". | Verified verbatim in PMC; citation updated | PMC12690188 |
| L7 | Low | L-BIC18 said "KDIGO 2024 suggests treatment". PP 3.10.1 is an ungraded practice point ("consider"), and "suggest" is KDIGO's word for grade-2 recommendations. | Text now says "says treatment should be considered (practice point 3.10.1)" | KDIGO 2024 |
| L8 | Low | L-UACR always printed "mg/g", even when the result was entered and categorised in mg/mmol. | Text prints the entered unit | §4.2 rule |
| L9 | Low | CA-1 omitted 6.2.1's condition "not taking active vitamin D analogs". CA-2 cited 6.2.2 (CKD 5D) for G5 without dialysis, which no KDOQI statement covers. | Both texts and catalogue rows qualified | KDOQI 2020 6.2.1–6.2.2 |
| L10 | Low | PH-T gave **no phosphorus limit** to a transplant recipient at **graft G4–G5** with no lab; native G4–G5 gets the ladder. KDOQI 6.3.3 is about post-transplant *hypo*phosphataemia. | PH-T applies only at graft G1–G3b; graft G4–G5 uses PH-0 (TV21) | KDOQI 2020 6.3.3 |
| L11 | Low | `nap.nationalacademies.org/read/...` links now 301-redirect to `www.nationalacademies.org/read/...`. | Links updated in §9 and §8 | HTTP check |
| L12 | Low | "On dialysis, weigh after the session" was attributed to KDOQI. KDOQI's "postdialysis" wording is about bioimpedance; Table 5 equates oedema-free weight with estimated dry weight. | F2 reworded | KDOQI 2020 Table 5, 1.1 text |
| L13 | Low | ISRNM's albumin < 3.8 g/dL uses bromocresol green; bromocresol purple reads lower in CKD, so the cut-off over-flags. | F12, L-ALB text and the risk table now say so | ISRNM 2008 table |
| L14 | Low | eGFR was computed and a stage suggested even in pregnancy, for which the equations were not developed. Standardised assays were not mentioned. | §4.3 guard **[OPINION]**; assay sentence added to F13 | NKF equation pages |
| L15 | Low | K-2 relaxes the HD ceiling from 2500 to 3000 mg on one normal pre-dialysis K. 3000 is still within AKF's "no more than 3,000", but dialysis carries the highest hyperkalaemia risk. | No number changed; flagged for the C10 clinical reviewer | AKF; KDIGO 2024 PP 3.11.5.2 |

**Totals: 1 high, 6 medium, 15 low.** Vectors changed: TV01, TV02, TV04, TV05, TV13, TV16, TV18 and
TV19. Vectors added: TV21 (older transplant recipient with graft G4), TV22 (low bicarbonate at G5)
and TV23 (under-18 edge). After the fixes the fact-check implementation reproduces the §5.1 JSON
exactly.

### 10.4 Checked and judged safe as written

* **No protein restriction on dialysis.** Dialysis stays at 1.0–1.2 g/kg, or 1.2–1.3 g/kg with
  nutrition risk.
* **No restriction for frail or older people.**
  * Native G3–G5 now runs from 0.8 to 1.0 g/kg; G1–G2 from 1.0 to 1.2 g/kg.
  * Energy has a floor of 30 kcal/kg with nutrition risk.
* **No potassium restriction when potassium is low.** K < 3.5 gives no limit.
* **Potassium ceilings without a high result are labelled.** Ceilings applied without a high K are
  called "review ceilings" and carry POTASSIUM_NOTE.
* **No fluid limit without dialysis.**
* **Pregnancy, under-18 and early-transplant refusals are in place**, now with the conservative
  age rule.
* **No age or sex term for K, P or Na.** This is supported by KDIGO Table 24 and the NASEM DRI
  scope.
* **Sex-unspecified eGFR shows both values** and refuses a category when they disagree.
* **The KDIGO U5 trap is handled.** The mg/mmol and mg/g columns are only approximately
  equivalent.
