# Renal nutrition research brief: CKD diet for an adult with type 1 diabetes

**Status:** research document for the kidney-health tracker. Compiled 2026-10-05 from primary guideline texts (KDOQI 2020, KDIGO 2024, KDIGO 2022 Diabetes-in-CKD, KDIGO 2017 CKD-MBD, KDOQI 2003 Bone), the ADA Standards of Care, NIDDK, the National Kidney Foundation (NKF), the American Kidney Fund (AKF), the FDA, and peer-reviewed papers. Every number below is tied to a numbered reference in the [References](#references) section.

> **Superseded in part by design note 05 (v0.3; banner added 2026-10-07).** Where this note and
> [`docs/dev/research/05-personalized-targets.md`](../dev/research/05-personalized-targets.md) differ, the app
> follows note 05: **protein with diabetes at G3a–G5 is 0.8 g/kg** (a floor as well as the target: ADA 2026
> Rec 11.3, KDIGO 2022 Rec 3.1.1, KDIGO 2024 Rec 3.3.1.1; KDOQI 2020's 0.6 g/kg is for close supervision only,
> note 05 F4 and fact-check H1); **KDOQI 2020 statement numbers are the published guideline's** (3.0.1–3.0.4
> protein, 3.1.1 energy; this note first used the 2019 public-review draft's, note 05 F1); and grams per kg use a
> **reference weight** (the person's weight, moved toward the healthy BMI range when outside it, note 05 §3.1 and §4.3),
> not "ideal body weight": KDOQI 2020 leaves the choice of weight to the care team (1.1.6). The rows below are
> corrected; `tests/test_research_notes.py` keeps the old wording out.

> **This is not medical advice and is not a substitute for the person's nephrologist and renal dietitian.** Targets for potassium, phosphorus, protein, fluid and calories are *individualized* from the person's own labs (serum potassium, phosphate, bicarbonate, albumin, HbA1c), residual urine output, dialysis prescription, medications (RAS inhibitors, MRAs, SGLT2 inhibitors, binders, potassium binders, insulin) and nutritional status. KDIGO 2024 explicitly says to "use renal dietitians or accredited nutrition providers to educate people with CKD about dietary adaptations regarding sodium, phosphorus, potassium, and protein intake, tailored to their individual needs" (Practice Point 3.3.2) [2]. The numbers here are *starting points* for the tracker's thresholds that the care team should overwrite.

---

## 0. How to read this document

- **CKD stages** (KDIGO GFR categories): G3a = eGFR 45–59, G3b = 30–44, G4 = 15–29, G5 = <15 mL/min/1.73 m². "5D" = stage 5 on dialysis (HD = hemodialysis, PD = peritoneal dialysis) [2].
- **Evidence grades**: KDOQI/KDIGO use 1 (strong "we recommend") or 2 (weak "we suggest") plus quality A–D; "OPINION" or "Practice Point" = expert consensus without graded evidence [1][2]. ADA uses A/B/C/E [8].
- **Diet guidelines do not differ between stages 3a and 3b**, and mostly not between 3 and 4 either. The guidelines set *one* range for "CKD 3–5 not on dialysis" and a second for dialysis. What changes with stage is **how likely a restriction is to be triggered** by labs: hyperkalemia prevalence rises from ~8.8 % at G3/A1 to ~34 % at G5/A3 in people with diabetes [2], and phosphate retention becomes common in stage 4–5. Stage-specific numbers in Section 2 and the JSON are therefore *program defaults that tighten as stage advances*, not separate guideline recommendations.
- **Type 1 diabetes changes three things**: (a) the protein target is more liberal than for non-diabetic CKD (0.8 g/kg: ADA, KDIGO; KDOQI's 0.6–0.8 under close supervision, vs 0.55–0.60) because very-low-protein diets worsen glycaemic control and risk hypoglycaemia [1][3]; (b) hypoglycaemia treatment should *prefer* low-potassium carbohydrate (glucose tablets, apple/cranberry juice rather than orange juice) but is **never delayed or under-dosed because of potassium** [5][27] (Section 2.9); (c) on PD, the dextrose dialysate adds ~400+ kcal/day of absorbed glucose that must be counted [25].

---

## 1. Why potassium, phosphorus, sodium, protein and fluid are restricted, and what happens if they are not

| Nutrient | Why the failing kidney can't cope | What happens when intake exceeds capacity | Key sources |
|---|---|---|---|
| **Potassium (K)** | ~90 % of dietary K is excreted by the kidney; as GFR falls, serum K rises. Risk is amplified by RAS inhibitors, MRAs, constipation, acidosis and hyperglycaemia [2]. | **Hyperkalaemia** (serum K > 5.0–5.5 mmol/L): disturbed cardiac conduction → arrhythmia and sudden cardiac death; U-shaped relation between serum K and all-cause mortality; also associated with worse kidney prognosis [2]. KDIGO 2024 treats K ≥ 6.5 mmol/L as needing emergency assessment [2]. In people with diabetes, adjusted hyperkalaemia prevalence is 8.8 % at G3/A1 rising to 34.4 % at G5/A3 [2]. | [2] KDIGO 2024 §3.11; [1] KDOQI 6.4 |
| **Phosphorus (P)** | Phosphate is cleared by filtration; retention starts in stage 3–4 and is only partly removed by dialysis (HD and PD both remove it inefficiently) [22][25]. | **Hyperphosphataemia** (normal 2.5–4.5 mg/dL [21]) drives secondary hyperparathyroidism and renal osteodystrophy (calcium pulled from bone), **vascular and soft-tissue calcification**, cardiovascular events and mortality [12]. NKF: "dangerous calcium deposits in your blood vessels, lungs, eyes and heart" [20]. Each tertile increase in dietary P intake raised death hazard in HD patients (fully adjusted HR 2.37 highest vs lowest tertile) [14]. | [12] Kalantar-Zadeh 2010; [14] Noori 2010; [11] KDIGO 2017 CKD-MBD |
| **Sodium (Na)** | Sodium retention → extracellular volume expansion. | **Hypertension**, **oedema**, proteinuria, thirst (which breaks fluid limits on dialysis), interdialytic weight gain. KDOQI: limiting Na "to reduce blood pressure and improve volume control" (1B), to reduce proteinuria (2A), and to help reach dry weight on dialysis [1]. KDIGO: < 2 g/day (2C) [2][3]. | [1] KDOQI 6.5; [2] KDIGO 3.3.2.1 |
| **Protein** | Protein metabolism generates urea and other **uraemic toxins** and raises intraglomerular pressure (hyperfiltration → glomerulosclerosis) [2]. | Excess protein (> 1.3 g/kg/day) is associated with faster eGFR decline, albuminuria and CV mortality [2][8]. Too *little* protein causes protein-energy wasting, which is the stronger mortality signal on dialysis and in diabetics, hence the floors below [1][3]. | [2] KDIGO 3.3.1; [1] KDOQI 3.1 |
| **Fluid** | Once urine output falls (late stage 5 / dialysis), ingested water has nowhere to go between treatments. | **Fluid overload**: swelling, hypertension, pulmonary oedema/shortness of breath, heart failure, lung infections, less effective dialysis [19][24]. Relative interdialytic weight gain > 3.5 % of body weight is independently associated with all-cause and CV death [28]. | [19] AKF; [24] NKF HD; [28] Cabrera 2015 |

Related: **metabolic acidosis** (serum bicarbonate < 18–22 mmol/L) accelerates CKD and raises serum K; KDIGO 2024 suggests avoiding bicarbonate < 18 mmol/L (Practice Point 3.10.1) and notes that plant-dominant diets lower net acid production [2]; KDOQI 2020 suggests fruit/vegetables (2C) or bicarbonate (1C) and maintaining bicarbonate 24–26 mmol/L (OPINION) [1].

---

## 2. Daily targets by CKD stage and dialysis status

### 2.1 Summary table (adult, per kg of reference weight; see 2.2–2.9 for sources and caveats)

| Nutrient | CKD 3a–4, not on dialysis | CKD 5, not on dialysis | Hemodialysis (5D-HD) | Peritoneal dialysis (5D-PD) |
|---|---|---|---|---|
| **Protein** (g/kg/day) | **With diabetes: 0.8** (KDIGO 2024 3.3.1.1, 2C; KDIGO 2022 Diabetes 3.1.1, 2C; ADA 2025 Rec 11.8 = 2026 Rec 11.3, A) [2][3][8][9]; KDOQI 3.0.2 allows 0.6–0.8 under close supervision (OPINION) [1]. Non-diabetic: 0.55–0.60 (KDOQI 3.0.1, 1A) [1]. Avoid > 1.3 [2]. | Same as 3a–4 [1][2] | **1.0–1.2** (KDOQI 3.0.3, 1C; 3.0.4 with diabetes, OPINION — consider higher if hypo-/hyperglycaemia) [1]; ADA 11.8 (B) [8]; KDIGO 2022 PP 3.1.2 [3] | **1.0–1.2** (KDOQI 3.0.3, OPINION on PD); KDIGO 2022: "particularly peritoneal dialysis" 1.0–1.2 [1][3]; many programs use the upper end |
| **Energy** (kcal/kg/day) | **25–35** (KDOQI 3.1.1, 1C) [1] | 25–35 [1] | 25–35 [1] | 25–35 **minus** dialysate dextrose calories (~400+ kcal/day absorbed) [1][25] |
| **Sodium** (mg/day) | **< 2,000** (KDIGO 2024 3.3.2.1, 2C; KDIGO 2022 3.1.2, 2C) [2][3]; **< 2,300** (KDOQI 6.5.1, 1B; NIDDK; ADA) [1][4][8] | < 2,000–2,300 [1][2] | < 2,000–2,300 (NKF HD: < 2,300) [1][24] | < 2,000–2,300 by guideline [1][3]; PD programs often liberalise to 3,000–4,000 because PD removes Na well [25] |
| **Potassium** (mg/day) | **No fixed restriction unless serum K is high**; adjust to keep serum K normal (KDOQI 6.4.1, OPINION) [1]; KDIGO: limit *bioavailable* K (processed foods) if history of hyperkalaemia (PP 3.11.5.2) [2]. Typical restricted diet when needed: **2,000–3,000** [26][29] | 2,000–3,000 when hyperkalaemic [26][29] | **2,000–3,000** typical; none for frequent home HD [24][26][29] | **3,000–4,000** ("liberal") typical [25] |
| **Phosphorus** (mg/day) | Adjust to keep serum phosphate normal (KDOQI 6.3.1, 1B); consider source bioavailability (6.3.2) [1]. **800–1,000** when serum P > 4.6 mg/dL (KDOQI 2003 Guideline 4.1, OPINION) [10]; emphasis on **additive avoidance** over total [1][11] | 800–1,000 when P > 5.5 mg/dL (KDOQI 2003, EVIDENCE) [10] | 800–1,000, "adjusted for protein needs" [10][22]; binders with meals [20] | 800–1,000 adjusted for protein; binders with meals [10][25] |
| **Calcium** (mg/day, total incl. diet + supplements + Ca-based binders) | **800–1,000** for CKD 3–4 not on active vitamin D (KDOQI 6.2.1, 2B) [1] | Adjust to avoid hypercalcaemia (KDOQI 6.2.2, OPINION) [1]; older ceiling: ≤ 2,000 total, ≤ 1,500 from binders (KDOQI 2003 5.5) [10]; KDIGO 2017: restrict Ca-based binder dose (4.1.6, 2B) [11] | As CKD 5 | As CKD 5 |
| **Fluid** (mL/day) | **No routine limit**; AKF: restriction only if prescribed [19]. KDOQI 2020 has no fluid statement [1] | Individualised (oedema, hyponatraemia) [19] | **~1,000 mL + 24-h urine volume** (DaVita) [23]; AKF: 32 oz (~950 mL) + urine [19]; NKF: 1–2 L depending on urine [24] | **2–3 L** typical, individualised to residual function and ultrafiltration [25] |

For a **70 kg** adult: protein 56 g/day (0.8) non-dialysis with diabetes (42–56 g, 0.6–0.8, without), 70–84 g/day (1.0–1.2) on dialysis; energy 1,750–2,450 kcal/day (25–35 kcal/kg). KDIGO's own table gives 56 g/day at 0.8 g/kg for 70 kg [2].

### 2.2 Protein, in detail

- **KDOQI 2020** (final publication, AJKD 2020;76(3 Suppl 1):S1–S107) [1]:
  - 3.0.1 Non-diabetic CKD 3–5, metabolically stable: low-protein 0.55–0.60 g/kg body weight/day, *or* very-low-protein 0.28–0.43 g/kg + ketoacid analogues, to reduce ESKD/death (1A) and improve QoL (2C in the published guideline; the 2019 public-review draft said 1C).
  - 3.0.3 Maintenance HD (1C) and PD (OPINION): 1.0–1.2 g/kg body weight/day.
  - 3.0.2 CKD 3–5 **with diabetes**: **0.6–0.8 g/kg body weight/day** under close clinical supervision "to maintain a stable nutritional status and optimize glycemic control" (OPINION). (The 2019 public-review draft said 0.8–0.9; the published guideline and the ISRNM commentary give 0.6–0.8 [1][13].)
  - 3.0.4 HD/PD **with diabetes**: 1.0–1.2 g/kg; "for patients at risk of hyper and/or hypoglycemia, higher levels of dietary protein intake may need to be considered to maintain glycemic control" (OPINION).
  - 3.1.1 Energy 25–35 kcal/kg body weight/day for CKD 1–5D (1C).
  - 1.1.6 The weight used (ideal, usual, current, adjusted or BMI-based) is left to clinical judgement (OPINION).
- **KDIGO 2024 CKD** [2]: Rec 3.3.1.1 "maintaining a protein intake of 0.8 g/kg body weight/d in adults with CKD G3–G5 (2C)"; PP 3.3.1.1 avoid > 1.3 g/kg; PP 3.3.1.2 very-low-protein 0.3–0.4 g/kg + ketoanalogues only under close supervision; PP 3.3.1.3 do not prescribe low/very-low protein in metabolically unstable people; PP 3.3.1.5 consider higher protein in frail/sarcopenic older adults.
- **KDIGO 2022 Diabetes in CKD** [3]: Rec 3.1.1 0.8 g/kg/day for diabetes + CKD not on dialysis (2C); PP 3.1.2 HD "and particularly peritoneal dialysis" 1.0–1.2 g/kg/day. Rationale: limiting protein below 0.8 in a person with diabetes who is also limiting carbohydrate, fat and alcohol "may dramatically decrease caloric content of the diet" and cause unwanted weight loss.
- **ADA Standards of Care, Section 11** (2025 Rec 11.8 and 2026 Rec 11.3 — renumbered, identical wording — both verified verbatim at PMC) [8][9]: "protein intake should be 0.8 g/kg body weight per day, as for the general population" (A); "For individuals on dialysis, protein intake of 1.0–1.2 g/kg/day should be considered, since protein energy wasting is a major problem for some individuals on dialysis" (B). ADA's stated reason for not going below 0.8 g/kg is that doing so "does not alter blood glucose levels, cardiovascular risk measures, or the course of GFR decline" [9]. Higher intakes (> 20 % of calories or > 1.3 g/kg/day) associated with albuminuria, faster eGFR loss and CV mortality [8].
- **Reconciling for a T1D patient**: the three bodies agree on an upper bound of 0.8 g/kg (non-dialysis) and 1.0–1.2 (dialysis). KDOQI alone allows going down to 0.6 under dietitian supervision. The tracker suggests **0.8 g/kg/day** with diabetes (ADA says not to go below it; KDOQI's 0.6 is for close dietitian supervision), and **1.0–1.2** on dialysis, per kg of a reference weight that moves toward the healthy BMI range when the person is over- or under-weight (note 05 §4.3; KDOQI 1.1.6 leaves the weight to the care team) [1][9].

### 2.3 Sodium

- KDIGO 2024 Rec 3.3.2.1: "< 2 g of sodium per day (or < 90 mmol of sodium per day, or < 5 g of sodium chloride per day) in people with CKD (2C)"; not appropriate for sodium-wasting nephropathy (PP 3.3.2.1) [2]. Identical wording in KDIGO 2022 Diabetes Rec 3.1.2 [3].
- KDOQI 2020 6.5.1: < 100 mmol/day (< 2.3 g) for CKD 3–5 (1B), dialysis (1C), transplant (1C); 6.5.2 to reduce proteinuria (2A); 6.5.3 for volume control/dry weight (2B) [1].
- NIDDK: "no more than 2,300 mg" and often stricter in CKD [4]. NKF HD: < 2,300 mg [24]. ADA: < 2,300 mg may help BP [8].
- Many dialysis programs use **2,000 mg**; PD programs sometimes allow 3,000–4,000 mg because PD removes sodium efficiently [25]. **Program default: 2,000 mg/day.**

### 2.4 Potassium

- Guidelines deliberately give **no mg number**. KDOQI 2020 6.4.1: adjust dietary K "to maintain serum potassium within the normal range" (OPINION); 6.4.2: in hyperkalaemia, "consider lowering dietary potassium intake as a therapeutic strategy" (OPINION); 6.4.3: base intake on individual needs (2D) [1]. KDIGO 2024 PP 3.11.5.1–2: individualised dietary + pharmacologic approach; "limit the intake of foods rich in *bioavailable* potassium (e.g., processed foods)" for people with a history of hyperkalaemia [2]. ADA: "individualization of dietary potassium may be necessary" [8].
- Where a restriction is prescribed, dietitian practice is **2,000–3,000 mg/day** (DaVita; UF/IFAS "for those on dialysis") [26][29] for CKD 4–5 and HD, and **3,000–4,000 mg/day** for PD [25]. People on frequent home HD usually need no restriction [24].
- KDIGO 2024 Figure 33 (from Picard 2021): K absorption ~50–60 % from plant foods, 70–90 % from animal foods, ~90 % from potassium salts/additives in processed foods; plant fibre and carbohydrate shift K intracellularly, so whole plant foods raise serum K less than their label value suggests [2][30].
- Dietary K correlates only weakly with serum K; a vegetarian RCT in eGFR < 30 did not raise serum K [16][17]. Over-restricting fruit and vegetables worsens acidosis, constipation (which itself raises K) and CV risk [2][30].
- **Program default**: a *ceiling that triggers review* rather than a prescription: 4,000 (3a) → 3,500 (3b) → 3,000 (4) → 2,500 (5 and HD) → 3,500 (PD). The dietitian should replace these with the person's actual order once serum K is known.
- These ceilings sit inside the published stage-based ranges tabulated in the AKF potassium handout [52]: K/DOQI 2004 (hypertension in CKD) > 4,000 mg/day for G1–G2 and **2,000–4,000 mg/day for G3a–G4**; Kalantar-Zadeh & Fouque (NEJM 2017) 4,700 mg if eGFR > 30 and **< 3,000 mg for CKD 4–5**; expert opinion **2,700–3,000 mg for HD, 3,000–4,000 mg for PD, < 3,000 mg with hyperkalaemia**; and AKF's own patient rule: when a restriction is prescribed, "aim for a daily potassium goal of 2,500 mg and no more than 3,000 mg per day" [52].

### 2.5 Phosphorus

- KDOQI 2020 6.3.1: adjust dietary P to keep serum phosphate normal (1B); 6.3.2: consider bioavailability of sources (animal, vegetable, additives) (OPINION) [1]. KDIGO 2017 CKD-MBD 4.1.2: lower elevated phosphate toward normal (2C); 4.1.8: limit dietary phosphate for hyperphosphataemia and "consider phosphate source (e.g., animal, vegetable, additives)" (2D/not graded) [11].
- The classic number comes from **KDOQI 2003 Bone Metabolism Guideline 4.1**: "Dietary phosphorus should be restricted to **800 to 1,000 mg/day** (adjusted for dietary protein needs) when the serum phosphorus levels are elevated > 4.6 mg/dL at Stages 3 and 4 (OPINION) and > 5.5 mg/dL in those with kidney failure (Stage 5) (EVIDENCE)"; 4.2 also when PTH is above target [10]. DaVita and most US programs still use 800–1,000 mg [22]. Normal serum phosphate 2.5–4.5 mg/dL [21].
- Because a 1.2 g/kg protein diet unavoidably brings ~1,000+ mg of natural P, the modern emphasis is **additive avoidance and P-to-protein ratio** (Section 3) rather than total mg [12][14][15]. Binders (calcium- or non-calcium-based, or tenapanor) are taken *with* meals when diet alone is insufficient [20].
- **Program default**: 1,000 mg/day (stages 3a–4, HD, PD), 900 mg (stage 5 pre-dialysis), with a separate hard flag on any food containing a "phos" additive.

### 2.6 Calcium

- KDOQI 2020 6.2.1: CKD 3–4 not on active vitamin D analogues: total elemental calcium **800–1,000 mg/day** including diet, supplements and calcium-based binders (2B); 6.2.2: CKD 5D, adjust to avoid hypercalcaemia considering vitamin D analogues and calcimimetics (OPINION) [1].
- KDOQI 2003 5.5: binder calcium ≤ 1,500 mg/day and total elemental calcium ≤ 2,000 mg/day (OPINION) [10]; KDIGO 2017 4.1.6: restrict the dose of calcium-based binders in G3a–G5D (2B) [11].
- **Program default**: 1,000 mg/day total (count binder calcium), flag > 1,500.

### 2.7 Fluid

- Non-dialysis CKD: no routine restriction; AKF says stages 3–5 may be restricted individually by the doctor/dietitian [19]. KDOQI 2020 contains no fluid statement [1].
- HD: DaVita: "32 ounces or 1000 ml each day" base, plus the measured 24-h urine volume (e.g. 500 mL urine → 1,500 mL/day); 1,000 mL ≈ 1 kg daily weight gain [23]. AKF: 32 oz + urine output, re-measure urine every 3 months [19]. NKF: "one to two liters or more per day" depending on urine; none for most home HD [24]. Common clinic rule-of-thumb: 1,000–1,500 mL + urine output.
- PD: 2–3 L/day typical, varies with residual function and PD modality [25].
- Fluid counts anything liquid at room temperature: ice, soup, gelatin, ice cream, popsicles, gravy, protein drinks [19][24]. Sodium drives thirst, so Na control is the main fluid-control tool [23].

### 2.8 Energy

- KDOQI 3.1.1: **25–35 kcal/kg body weight/day** based on age, sex, activity, body composition, weight goals, CKD stage and inflammation (1C) [1]. PLADO uses 30–35 kcal/kg [16]. On PD, subtract absorbed dextrose (often 400+ kcal/day) [25]. **Default: 30 kcal/kg.**

### 2.9 Type 1 diabetes specifics

- Glycaemic target individualised, HbA1c < 6.5 % to < 8.0 % (KDIGO 2022 Rec 2.2.1); HbA1c becomes unreliable in G4–G5 and on dialysis, so CGM metrics (time in range, time below range, GMI) are preferred (PP 2.1.2–2.1.4) [3]. Hypoglycaemia risk rises as eGFR falls (reduced renal gluconeogenesis and insulin clearance), so insulin doses often need reduction and A1C goals may be loosened [8].
- Hypoglycaemia rescue (15 g carbohydrate) on a renal diet: glucose tablets (4 × 4 g), glucose gel, ½ cup apple/grape/cranberry/pineapple juice, ½ cup regular clear soda (ginger ale, Sprite, 7-Up — *not* cola), 3 hard candies, 1 Tbsp honey, 7 saltines, 1 slice white bread. **Prefer** these over orange juice (potassium), colas (phosphate additives) and chocolate (fat slows absorption) [27]. NIDDK: for diabetics with low blood sugar, apple, grape or cranberry juice are the kidney-friendly choices [4]. Potassium per ½ cup (USDA SR Legacy): **orange juice 248 mg** (raw; ~220 mg from concentrate), apple juice 125 mg, grape juice 132 mg, cranberry juice cocktail 18 mg [51]. (A hospital-medicine abstract that quotes 150 mg for orange juice [31] understates the USDA value by ~40 % and must not be used for the tracker.)
- **Safety rule — the potassium budget never overrides hypoglycaemia treatment.** A low (< 70 mg/dL) is treated *immediately* with 15 g of fast carbohydrate, rechecked at 15 minutes and repeated if still low (ADA Rec 6.15, B) [8][9]. If the only fast carbohydrate within reach is orange juice, regular cola or milk, use it: one 4-oz portion adds ~250 mg potassium, which is a logging note, not a reason to delay. Never treat a low with less than 15 g, and never with "sugar-free" products, because of potassium or phosphorus. Glucagon (preferably a ready-to-use nasal or auto-injector preparation) should be prescribed to everyone on insulin and is the treatment for level 3 hypoglycaemia (ADA Rec 6.16, A) [8][9]. Severe hypoglycaemia is an immediate emergency (seizure, coma, death); a single potassium-rich rescue drink in a person with CKD is not. The tracker should therefore *log* hypo treatments against the potassium budget but never *block* or warn against them.
- Carbohydrate counting continues as usual; the renal-diet substitutions (white bread/rice/pasta for whole grain; low-K fruit) are often *lower* in fibre and higher glycaemic index, so insulin-to-carb ratios may need re-tuning with the diabetes team [3][16].

---

## 3. Phosphorus bioavailability and reading labels

### 3.1 Absorption by source

| Source | Form | Typical absorption | Notes | Sources |
|---|---|---|---|---|
| Plant (legumes, nuts, seeds, whole grains) | Organic, largely **phytate-bound** | **~20–50 %** (ranges 6 % for sesame seeds to ~40–50 %) | Humans lack phytase; fermentation/leavening frees some P. Lower acid load, more fibre. | [12][13][15] |
| Animal (meat, poultry, fish, eggs, dairy) | Organic (phospholipids, nucleic acids, casein) | **~40–60 %** | Varies with vitamin D receptor activation. Dairy and processed cheese are the densest. | [12][13] |
| Inorganic additives (phosphoric acid, sodium/potassium/calcium phosphates, pyro-/poly-/hexametaphosphates) | Inorganic salts, not protein-bound | **~90–100 % (digestibility)**; urinary-balance studies suggest somewhat less, but still the most absorbable fraction | Not required on US Nutrition Facts; nutrient databases under-count it. Adds **~600 mg/day** in a high-additive vs low-additive diet [18]; estimates run 500–1,000 mg/day in Western diets. | [12][13][15][18] |

- KDOQI 2020 6.3.2 and KDIGO 2017 4.1.8 both make source consideration an explicit part of the prescription [1][11].
- **Phosphorus-to-protein ratio**: Noori/Kalantar-Zadeh recommend foods with **< 10 mg P per g protein**; fresh egg white is < 2 mg/g (whole egg ~16 mg/g) [13]. In 224 HD patients, death HR by P:protein ratio category (< 12, 12–< 14, 14–< 16, ≥ 16 mg/g) was 1.13, 1.00 (ref), 1.80, 1.99, and highest vs lowest P-intake tertile HR 2.37 [14]. Egg whites, skinless poultry and fresh fish are efficient protein for the 1.0–1.2 g/kg dialysis target; processed cheese, colas and "enhanced" meats are the worst offenders [12][13].

### 3.2 Spotting additives on labels ("PHOS" rule)

Phosphorus content is **not** required on the US label; scan the **ingredient list** for anything containing "phos" [4][5][20]:

`phosphoric acid`, `monosodium phosphate`, `disodium phosphate`, `trisodium phosphate`, `sodium hexametaphosphate`, `sodium tripolyphosphate`, `tetrasodium pyrophosphate`, `sodium acid pyrophosphate`, `dicalcium phosphate`, `tricalcium phosphate`, `monocalcium phosphate`, `calcium phosphate`, `potassium phosphate`, `dipotassium phosphate`, `aluminum phosphate`, `pyrophosphate`, `polyphosphate`, `hexametaphosphate`, `phosphate` (generic) [4][5][20][22].

Typical carriers: dark colas, flavoured/enhanced ("self-basting", "injected", "marinated") chicken, pork and turkey, deli meats, hot dogs, processed and spreadable cheese, non-dairy creamers, instant puddings, cake mixes and baking powder, frozen entrées, fast food, bottled coffee/tea drinks, "fortified" cereals [4][20][22]. A tracker should treat *any* "phos" ingredient as a high-phosphorus flag regardless of the mg figure in the database.

---

## 4. Potassium leaching, portion control, and hidden salt

### 4.1 Leaching / double-boiling technique

**Classic leaching protocol (NKF; UF/IFAS FS287)** for potatoes, sweet potatoes, carrots, beets, rutabaga, winter squash [5][29]:
1. Peel and place in cold water so the pieces don't darken.
2. Slice **1/8 inch (3 mm) thick** (or small dice).
3. Rinse in warm water for a few seconds.
4. Soak **≥ 2 hours** in warm unsalted water, **10 parts water : 1 part vegetable**. (Longer soaks or a water change help marginally.)
5. Rinse again under warm water.
6. Cook in **5 parts fresh unsalted water : 1 part vegetable**; **discard the cooking water**.
For frozen greens and mushrooms: thaw, drain, rinse, soak 2 h at 10:1, rinse, cook at 5:1 [29].

**What the evidence says it removes**:
- Bethke & Jansky 2008 (J Food Sci): soaking alone did **not** significantly lower K; **boiling 1-cm cubes removed ~50 %**, **boiling shredded potato ~75 %**; soaking before boiling added nothing beyond boiling. Recommendation for kidney patients: "boil small pieces" [6][7].
- Double-boiling (boil, drain, re-boil in fresh water) removes **about half** the K in 20–30 minutes, as effective as the 2-hour soak [32]. KDIGO 2024 cites that soaking foods 5–10 minutes in previously boiled water "can effectively reduce the potassium by half for some foods" [2].
- Leaching does **not** remove all potassium (and also strips some P, Mg, vitamin C); leached high-K vegetables still count toward the day's total and should be limited in frequency [5][29]. For a tracker: apply a **0.5 multiplier** to the K value of boiled/leached small-cut root vegetables, never to baked, roasted, microwaved or fried ones (which lose nothing) [6].

### 4.2 Portion-size control

- NKF: high-potassium = **≥ 200 mg per serving**; "a large amount of a low-phosphorus food can turn into a high-phosphorus food" [5][20]. AKF: low-K < 150, medium 151–250, high > 250 mg/serving [26]. The practical renal-diet rule is ½-cup servings of fruit/vegetables, 2–3 oz cooked meat (NIDDK) [4], and no more than one high-K item per meal.
- Hidden potassium: salt substitutes (KCl), "low-sodium" products using KCl, acesulfame-K sweetener, electrolyte drinks, "green" powders [5][24][33]. Processed-food potassium salts are ~90 % absorbed [2][30].

### 4.3 Hidden salt

- Americans average ~3,400 mg Na/day; **> 70 % comes from packaged and prepared/restaurant food**, not the salt shaker (FDA) [34]. CDC's top sources: deli-meat sandwiches, pizza, burritos/tacos, soups, savoury snacks, poultry, pasta dishes, burgers, egg dishes (~40 % of intake) [34].
- AHA "Salty Six": breads/rolls (up to ~230 mg per slice; a pita ~300 mg, a bagel ~500 mg), cold cuts and cured meats (2 oz can be half a day's allowance), pizza, poultry (brine-injected), canned soup, sandwiches [35][36].
- Cheese: most hard cheeses carry 150–450 mg Na per ounce plus 100–200 mg P; processed cheese adds phosphate additives [20][26].
- Restaurant meals frequently contain 1,000–3,000 mg Na in one plate, exceeding the full daily limit [35]. NKF: pick made-to-order restaurants, call ahead, avoid casseroles/mixed dishes (high Na and P) [20].
- Label rules: **low sodium ≤ 140 mg/serving**, very low ≤ 35 mg, sodium-free < 5 mg, reduced = ≥ 25 % less (FDA) [34][37]; **≤ 5 % DV = low, ≥ 20 % DV (≥ 460 mg) = high** [4][34]; NKF: aim for ≤ 240 mg Na/serving and "sodium less than calories" per serving; AKF snacks ≤ 140 mg [5][38].

---

## 5. Other CKD diet points

- **Acid load and plant-dominant eating.** Fruits and vegetables lower net endogenous acid production; KDOQI 6.1.1 suggests them to slow eGFR decline (2C) and 3.3.2 to lower weight, BP and NEAP (2C) [1]. Goraya et al. showed 3 years of fruit/vegetable alkali therapy preserved GFR and lowered BP better than bicarbonate tablets [17]. KDIGO 2024 PP 3.3.1: "higher consumption of plant-based foods compared to animal-based foods and a lower consumption of ultraprocessed foods" [2]. The **PLADO** pattern: 0.6–0.8 g protein/kg, > 50 % plant protein, Na < 3 g, **fibre ≥ 25–30 g/day**, 30–35 kcal/kg; plant P is phytate-bound, plant K is less absorbed and fibre speeds gut transit [16]. Monitor B12 on long-term vegan patterns [16].
- **Fibre.** 25–30 g/day (PLADO) [16]; higher fibre lowers serum K via faster transit and reduces uraemic toxin generation [2][16]. Renal-diet swaps (white bread, white rice) cut fibre, so add low-K high-fibre foods (berries, apples, cauliflower, green beans, oats in moderation).
- **Calories.** 25–35 kcal/kg [1]; inadequate energy makes any protein target useless (protein is burned for fuel). Diabetics must not let the renal diet become hypocaloric [3].
- **Star fruit (carambola)** must be **completely avoided** at every CKD stage: it contains caramboxin (a phenylalanine-like excitatory neurotoxin that activates glutamate NMDA/AMPA receptors and blocks GABA inhibition) and oxalate; the toxin is renally cleared, so in CKD it causes intractable hiccups, vomiting, confusion, seizures, coma and death; hemodialysis is the only treatment [39][40].
- **Salt substitutes** (NoSalt, Nu-Salt, Lite Salt, "half salt", many "low-sodium" soups/sauces) are **potassium chloride** and can precipitate hyperkalaemia; KCl in food is far more absorbable than K in whole foods. NKF, AKF, AAKP and the Academy jointly opposed the FDA proposal to allow KCl in standardised foods for this reason [5][33]. NIDDK: avoid salt substitutes if potassium is high [4]. Use herbs, spices, lemon, vinegar, Mrs Dash-type salt-free blends instead.
- **Herbal/dietary supplements.** NKF lists as especially risky in kidney disease: alfalfa, aloe vera (oral), aristolochia, arnica, astragalus, bearberry/uva ursi, cat's claw, chaparral, comfrey, creatine, goldenrod, horsetail, licorice root, nettle, St John's wort, yohimbe; AKF adds barberry, java tea, Oregon grape root, parsley root, apium graveolens, ruta graveolens, pennyroyal, huperzine [41][42]. "Electrolyte support", "superfood green" powders, kelp/seaweed, noni, dandelion, turmeric, papaya and seed-based products can carry hidden K and P; many multivitamins contain phosphorus and magnesium [41]. Rule: no supplement without the nephrologist's sign-off; renal-specific vitamins only.
- **OTC laxatives, enemas and antacids.** *Phosphate*: FDA (2014) warns that OTC **sodium phosphate** oral laxatives and enemas (Fleet and generics) can cause acute phosphate nephropathy, dangerous hyperphosphataemia and death, especially in kidney disease, age > 55, dehydration, or with diuretics/ACEi/ARB/NSAIDs; never more than one dose in 24 h and best avoided entirely in CKD [43]. *Magnesium*: milk of magnesia, magnesium citrate, Mylanta/Maalox-type Mg antacids and Epsom salts accumulate in CKD and cause life-threatening hypermagnesaemia; avoid [44][45]. *Aluminium* antacids and *Alka-Seltzer*-type (high sodium) products are also unsuitable. Safer constipation options are usually polyethylene glycol, senna, docusate or lactulose as approved by the care team.

---

## 6. Per-serving classification thresholds used by renal dietitians

These are *per serving* (usually ½ cup, 1 medium fruit, 1 oz cheese, 3 oz meat) and are the practical rules a logging app can implement. They are convention, not guideline recommendations, and programs differ; the table shows the main published schemes.

| Nutrient | Very low | Low | Medium | High | Very high | Source / scheme |
|---|---|---|---|---|---|---|
| **Potassium** | — | **< 100 mg** | 100–200 mg | 201–300 mg | **> 300 mg** | NKF scheme as summarised by DaVita [26] |
| Potassium | — | **< 150 mg** | 151–250 mg | **> 250 mg** | — | AKF phosphorus/potassium guide (★ = ≥ 250 mg K) [26][46] |
| Potassium | — | ≤ 200 mg "look for" | — | **≥ 200 mg = high** | — | NKF label guide and K diet page [5][38] |
| **Phosphorus** | — | **≤ 100 mg** | 101–199 mg | **≥ 200 mg** | — | AKF Phosphorus Food Guide [46]; some handouts use < 50 / 50–150 / > 150 mg |
| Phosphorus | — | any "phos" additive = **flag as high** regardless of mg | | | | NKF, NIDDK [4][5][20] |
| Phosphorus (P:protein) | — | **< 10 mg/g** desirable | 10–< 14 mg/g | ≥ 14–16 mg/g (higher mortality) | | Noori 2010 [13][14] |
| **Sodium** | sodium-free < 5 mg; very low ≤ 35 mg | **≤ 140 mg** (FDA "low"; ≤ 5 % DV ≈ ≤ 115 mg) | 141–400 mg (NKF "≤ 240 mg and less than calories") | **≥ 460 mg (≥ 20 % DV)** | ≥ 600 mg/meal item | FDA [34][37]; NKF [38]; AKF [19] |
| **Per meal** | | | | K > 600–700 mg or Na > 600 mg per meal = review | | AKF Kidney Kitchen; Satellite Healthcare [47] |

Suggested tracker logic: classify each logged food on all three nutrients; show a green/amber/red chip; count high-K and high-P servings per day (most programs allow ≤ 1–2 "high" servings/day when restricted); flag any "phos" or "potassium chloride" ingredient string as red regardless of mg; apply the 0.5 leaching multiplier only when the user marks the item as boiled/double-boiled small-cut.

---

## 7. Machine-readable starting targets (70 kg adult)

Assumptions: reference weight 70 kg; type 1 diabetes; metabolically stable; no sodium-wasting nephropathy; serum potassium and phosphate not yet known (so potassium/phosphorus values are *review ceilings that tighten with stage*, per Sections 2.4–2.5, not prescriptions). Protein is g per kg of reference weight per day — multiply by 70 for grams (with diabetes the app uses 0.8 for both bounds at G3a–G5: note 05 P-2d). `fluid_ml` is `null` where guidelines set no routine limit; for hemodialysis the 1,000 mL base must have the person's 24-hour urine volume **added**. `calcium_mg` is total elemental calcium including supplements and calcium-based binders. Dialysis entries exist only for stage 5 because dialysis is by definition kidney failure; if the person is on dialysis use the matching dialysis entry regardless of the stage label. Sources per field: protein [1][2][3][8]; sodium [1][2][3]; potassium [1][2][25][26][29]; phosphorus [1][10][11][22]; calcium [1][10][11]; fluid [19][23][24][25]; calories [1].

```json targets_by_stage
[
  {
    "stage": "3a",
    "dialysis": "none",
    "potassium_mg": 4000,
    "phosphorus_mg": 1000,
    "sodium_mg": 2000,
    "protein_g_per_kg_min": 0.6,
    "protein_g_per_kg_max": 0.8,
    "fluid_ml": null,
    "calories_kcal_per_kg": 30,
    "calcium_mg": 1000
  },
  {
    "stage": "3b",
    "dialysis": "none",
    "potassium_mg": 3500,
    "phosphorus_mg": 1000,
    "sodium_mg": 2000,
    "protein_g_per_kg_min": 0.6,
    "protein_g_per_kg_max": 0.8,
    "fluid_ml": null,
    "calories_kcal_per_kg": 30,
    "calcium_mg": 1000
  },
  {
    "stage": "4",
    "dialysis": "none",
    "potassium_mg": 3000,
    "phosphorus_mg": 1000,
    "sodium_mg": 2000,
    "protein_g_per_kg_min": 0.6,
    "protein_g_per_kg_max": 0.8,
    "fluid_ml": null,
    "calories_kcal_per_kg": 30,
    "calcium_mg": 1000
  },
  {
    "stage": "5",
    "dialysis": "none",
    "potassium_mg": 2500,
    "phosphorus_mg": 900,
    "sodium_mg": 2000,
    "protein_g_per_kg_min": 0.6,
    "protein_g_per_kg_max": 0.8,
    "fluid_ml": null,
    "calories_kcal_per_kg": 30,
    "calcium_mg": 1000
  },
  {
    "stage": "5",
    "dialysis": "hemodialysis",
    "potassium_mg": 2500,
    "phosphorus_mg": 1000,
    "sodium_mg": 2000,
    "protein_g_per_kg_min": 1.0,
    "protein_g_per_kg_max": 1.2,
    "fluid_ml": 1000,
    "calories_kcal_per_kg": 30,
    "calcium_mg": 1000
  },
  {
    "stage": "5",
    "dialysis": "peritoneal",
    "potassium_mg": 3500,
    "phosphorus_mg": 1000,
    "sodium_mg": 2000,
    "protein_g_per_kg_min": 1.0,
    "protein_g_per_kg_max": 1.2,
    "fluid_ml": 2000,
    "calories_kcal_per_kg": 30,
    "calcium_mg": 1000
  }
]
```

Field notes for the application:
- `potassium_mg`: if the latest serum K is ≤ 5.0 mmol/L and the person is not on a RAS inhibitor/MRA, the care team may remove the ceiling entirely (KDOQI 6.4.1; KDIGO PP 3.11.5.2). If serum K is > 5.0–5.5, use 2,000–3,000 mg (AKF: aim 2,500, no more than 3,000) [1][2][26][29][52].
- `phosphorus_mg`: if serum phosphate is in range (2.5–4.5 mg/dL) and no binder is prescribed, the total is informational; the additive flag stays on [1][10][21].
- `fluid_ml` (hemodialysis): effective daily allowance = 1,000 mL + 24-h urine volume (re-measured every ~3 months) [19][23].
- `calories_kcal_per_kg` (peritoneal): subtract dextrose absorbed from dialysate (often 400+ kcal/day) from food allowance [25].
- Protein grams for 70 kg: 42–56 g/day (non-dialysis), 70–84 g/day (dialysis) [1][2].

---

## References

1. Ikizler TA, Burrowes JD, Byham-Gray LD, et al. **KDOQI Clinical Practice Guideline for Nutrition in CKD: 2020 Update.** Am J Kidney Dis. 2020;76(3 Suppl 1):S1–S107. Statement text first checked against the NKF public-review copy (https://www.kidney.org/sites/default/files/Nutrition_GL%2BSubmission_101719_Public_Review_Copy.pdf) and the ISRNM commentary [13]; the statement numbers above are the published guideline's (3.0.1–3.0.4 protein, 3.1.1 energy), which renumbered the draft's 3.1.x (design note 05 F1); the diabetic protein range (0.6–0.8 g/kg) is as published in the final guideline. Press summary: https://www.kidney.org/news/national-kidney-foundation-releases-clinical-practice-guidelines-nutrition
2. KDIGO CKD Work Group. **KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of Chronic Kidney Disease.** Kidney Int. 2024;105(4S):S117–S314. Full text: https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf (Recs 3.3.1.1, 3.3.2.1; PPs 3.3.1, 3.3.2, 3.3.1.1–3.3.1.5, 3.10.1, 3.11.5.1–2; Table 24, Figures 19–20, 30, 33).
3. KDIGO Diabetes Work Group. **KDIGO 2022 Clinical Practice Guideline for Diabetes Management in Chronic Kidney Disease.** Kidney Int. 2022;102(5S):S1–S127. https://kdigo.org/wp-content/uploads/2023/12/KDIGO-2022-Diabetes-Guideline.pdf (Recs 2.2.1, 3.1.1, 3.1.2; PPs 2.1.2–2.1.4, 3.1.1–3.1.5).
4. NIDDK. **Healthy Eating for Adults with Chronic Kidney Disease.** https://www.niddk.nih.gov/health-information/kidney-disease/chronic-kidney-disease-ckd/eating-nutrition
5. National Kidney Foundation. **Potassium and Your CKD Diet** (leaching steps; ≥ 200 mg/serving = high). https://www.kidney.org/kidney-topics/potassium-your-ckd-diet
6. Bethke PC, Jansky SH. **The effects of boiling and leaching on the content of potassium and other minerals in potatoes.** J Food Sci. 2008;73(5):H80–85. doi:10.1111/j.1750-3841.2008.00782.x. https://pubmed.ncbi.nlm.nih.gov/18576999/
7. USDA-ARS / ScienceDaily summary of ref 6. https://www.sciencedaily.com/releases/2008/06/080602153636.htm
8. American Diabetes Association Professional Practice Committee. **11. Chronic Kidney Disease and Risk Management: Standards of Care in Diabetes—2025.** Diabetes Care. 2025;48(Suppl 1). PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC11635029 (Rec 11.8 protein 0.8 g/kg [A]; dialysis 1.0–1.2 g/kg [B]; Na < 2,300 mg; individualised K).
9. American Diabetes Association Professional Practice Committee. **11. Chronic Kidney Disease and Risk Management: Standards of Care in Diabetes—2026.** Diabetes Care. 2026;49(Suppl 1):S246–S260. doi:10.2337/dc26-S011. Full text (verified 2026-10-05): https://pmc.ncbi.nlm.nih.gov/articles/PMC12690176 — Rec 11.3 protein 0.8 g/kg (A), dialysis 1.0–1.2 g/kg (B); Rec 11.5 BP < 130/80 mmHg, systolic < 120 where safely attainable (A); sodium < 2,300 mg; individualised potassium. (The 2025 edition numbered the protein statement 11.8.) Summary of Revisions: https://pmc.ncbi.nlm.nih.gov/articles/PMC12690167. Press release: https://diabetes.org/newsroom/press-releases/american-diabetes-association-releases-standards-care-diabetes-2026
10. National Kidney Foundation. **K/DOQI Clinical Practice Guidelines for Bone Metabolism and Disease in Chronic Kidney Disease (2003).** Am J Kidney Dis. 2003;42(4 Suppl 3). Guidelines 4.1–4.3, 5.5. https://www.kidney.org/sites/default/files/docs/boneguidelines.pdf
11. KDIGO CKD-MBD Update Work Group. **KDIGO 2017 Clinical Practice Guideline Update for the Diagnosis, Evaluation, Prevention, and Treatment of CKD-MBD.** Kidney Int Suppl. 2017;7(1):1–59. Recs 4.1.2, 4.1.6, 4.1.8. https://pmc.ncbi.nlm.nih.gov/articles/PMC6340919 ; https://kdigo.org/wp-content/uploads/2018/04/KDIGO-CKD-MBD-Update-Recs-to-Implement-final.pdf
12. Kalantar-Zadeh K, Gutekunst L, Mehrotra R, et al. **Understanding sources of dietary phosphorus in the treatment of patients with chronic kidney disease.** Clin J Am Soc Nephrol. 2010;5(3):519–530. doi:10.2215/CJN.06080809. https://pubmed.ncbi.nlm.nih.gov/20093346/
13. Noori N, Sims JJ, Kopple JD, et al. **Organic and inorganic dietary phosphorus and its management in chronic kidney disease.** Iran J Kidney Dis. 2010;4(2):89–100 (animal P 40–60 % absorbed; additives up to 100 %; P:protein ratio < 10 mg/g; egg white < 2 mg/g). https://pubmed.ncbi.nlm.nih.gov/20404416/ — and ISRNM commentary on KDOQI 2020: https://pmc.ncbi.nlm.nih.gov/articles/PMC9303594
14. Noori N, Kalantar-Zadeh K, Kovesdy CP, et al. **Association of dietary phosphorus intake and phosphorus to protein ratio with mortality in hemodialysis patients.** Clin J Am Soc Nephrol. 2010;5(4):683–692. https://pmc.ncbi.nlm.nih.gov/articles/PMC2849686
15. St-Jules DE, Jagannathan R, Gutekunst L, Kalantar-Zadeh K, Sevick MA. **Examining the proportion of dietary phosphorus from plants, animals, and food additives excreted in urine.** J Ren Nutr. 2017;27(2):78–83. doi:10.1053/j.jrn.2016.09.003 (bioavailability 6 % sesame → ~100 % additives; additives may be incompletely absorbed in balance studies). https://escholarship.org/uc/item/0nd4b0xx
16. Kalantar-Zadeh K, Joshi S, Schlueter R, et al. **Plant-Dominant Low-Protein Diet for Conservative Management of Chronic Kidney Disease (PLADO).** Nutrients. 2020;12(7):1931. https://pmc.ncbi.nlm.nih.gov/articles/PMC7400005/
17. Review of dietary acid load in CKD including Goraya et al. fruit/vegetable vs bicarbonate trials and the Garneata vegetarian RCT. https://pmc.ncbi.nlm.nih.gov/articles/PMC9964049
18. Review of phosphate additives in the Western diet (high-additive diet +606 ± 125 mg P/day). https://pmc.ncbi.nlm.nih.gov/articles/PMC6419782/ ; DaVita, Phosphate Additives and the Kidney Diet: https://www.davita.com/diet-nutrition/articles/phosphate-additives-and-the-kidney-diet/
19. American Kidney Fund, Kidney Kitchen. **Fluids** (32 oz + urine output; what counts as fluid; overload symptoms). https://kitchen.kidneyfund.org/fluids/ ; **Sodium** (snacks ≤ 140 mg). https://kitchen.kidneyfund.org/sodium/
20. National Kidney Foundation. **Phosphorus and Your CKD Diet** (additive names; foods to limit; binders/tenapanor). https://www.kidney.org/kidney-topics/phosphorus-and-your-ckd-diet ; handout "If you need to limit phosphorus": https://www.kidney.org/sites/default/files/if_you_need_to_limit_phosphorus.pdf
21. NKF normal serum phosphorus 2.5–4.5 mg/dL — see ref 20.
22. DaVita. **Phosphorus Update / Phosphate additives** (800–1,000 mg/day typical target). https://www.davita.com/diet-nutrition/kidney-diet-tips/thought-dark-colas-bad-news/
23. DaVita. **Hemodialysis and fluid intake: How much to drink?** (1,000 mL + 24-h urine). https://www.davita.com/diet-nutrition/kidney-diet-tips/hemodialysis-and-fluid-intake-how-much-to-drink/
24. National Kidney Foundation. **Hemodialysis and Your Diet** (Na < 2,300 mg; fluid 1–2 L; K individualised; acesulfame-K). https://www.kidney.org/kidney-topics/hemodialysis-and-your-diet
25. DaVita. **Peritoneal dialysis diet considerations** (K 3,000–4,000 mg; Na 3,000–4,000 mg; fluid 2–3 L; 400+ kcal from dextrose). https://www.davita.com/diet-nutrition/kidney-diet-tips/peritoneal-dialysis-diet-considerations/ ; NKF Nutrition and Peritoneal Dialysis: https://www.kidney.org/kidney-topics/nutrition-and-peritoneal-dialysis
26. DaVita. **How to determine if a food is high or low potassium** (NKF and AKF per-serving schemes; 2,000–3,000 mg/day restricted diet). https://www.davita.com/diet-nutrition/kidney-diet-tips/how-to-determine-if-a-food-is-high-or-low-potassium
27. DaVita. **Kidney-friendly foods to correct hypoglycemia.** https://www.davita.com/diet-nutrition/kidney-diet-tips/kidney-friendly-foods-to-correct-hypoglycemia/
28. Cabrera C, Brunelli SM, Rosenbaum D, et al. **A retrospective, longitudinal study estimating the association between interdialytic weight gain and cardiovascular events and death in hemodialysis patients.** BMC Nephrol. 2015;16:113. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4510887/
29. University of Florida IFAS Extension. **Chronic Kidney Disease: Potassium and Your Diet (FS287)** (leaching protocol; dialysis 2,000–3,000 mg/day). https://ask.ifas.ufl.edu/publication/FS287
30. Picard K, Griffiths M, Mager DR, Richard C. **Handouts for low-potassium diets disproportionately restrict fruits and vegetables.** J Ren Nutr. 2021;31(2):210–214 (source of KDIGO Figure 33 absorption rates). doi:10.1053/j.jrn.2020.07.001
31. Society of Hospital Medicine abstract, "'Orange' you glad for cranberry juice" (quotes K: orange juice 150 mg, apple 125 mg, cranberry 0 mg per 118 mL). **Caution:** the orange-juice figure is wrong by USDA data (248 mg per ½ cup raw, FDC 169098); kept only as the source of the QI-project idea, not for numbers. https://shmabstracts.org/abstract/orange-you-glad-for-cranberry-juiceimproving-management-of-hypoglycemia-in-patients-with-chronic-kidney-disease-or-end-stage-renal-disease/
32. DaVita. **Making lower potassium potatoes / Low potassium potatoes: no soaking required** (double-boil ≈ 50 % removal in 20–30 min). https://www.davita.com/diet-nutrition/kidney-diet-tips/making-lower-potassium-potatoes ; https://blogs.davita.com/kidney-diet-tips/low-potassium-potatoes-for-your-kidney-diet-no-soaking-required
33. AAKP / NKF / Academy of Nutrition and Dietetics letter opposing FDA potassium-chloride salt substitutes in standardized foods (2023). https://aakp.org/re-fda-proposal-to-permit-salt-substitutes-to-reduce-sodium-in-standardized-foods/ ; STAT coverage: https://www.statnews.com/2023/08/15/patient-advocates-warn-fda-proposal-on-salt-intake-kidney-disease/
34. U.S. FDA. **Sodium in Your Diet** (3,400 mg average; > 70 % from packaged/prepared food; 5 %/20 % DV; claim definitions; CDC top sources). https://www.fda.gov/food/nutrition-education-resources-materials/sodium-your-diet
35. American Heart Association **"Salty Six"** as summarised by University of Utah Health (pita ~300 mg, bagel ~500 mg) and Harvard Health (bread up to 230 mg/slice; 2 oz processed meat ≈ half the daily allowance; restaurant meals often 1,000–3,000 mg). https://healthcare.utah.edu/healthfeed/2018/01/salty-six-foods-surprising-amounts-of-sodium ; https://www.health.harvard.edu/heart-health/watch-out-for-the-salty-six
36. Medical News Today summary of AHA Salty Six. https://www.medicalnewstoday.com/articles/252566
37. FDA nutrient content claim definitions (sodium free < 5 mg; very low ≤ 35 mg; low ≤ 140 mg; reduced ≥ 25 % less). https://www.ncbi.nlm.nih.gov/books/NBK209851/
38. National Kidney Foundation. **Your Guide to the New and Improved Nutrition Facts Label** (≤ 240 mg Na/serving; ≤ 200 mg K/serving; "phos" additives; KCl warning). https://www.kidney.org/kidney-topics/your-guide-to-new-and-improved-nutrition-facts-label
39. de Oliveira ES, de Aguiar AS. **Why eating star fruit is prohibited for patients with chronic kidney disease?** J Bras Nefrol. 2015;37(2):241–247. https://pubmed.ncbi.nlm.nih.gov/26154645/
40. Star fruit (caramboxin) intoxication in kidney disease — case series/review (symptom grading; hemodialysis treatment). https://pmc.ncbi.nlm.nih.gov/articles/PMC7735120
41. National Kidney Foundation. **Herbal Supplements and Kidney Disease.** https://www.kidney.org/kidney-topics/herbal-supplements-and-kidney-disease
42. American Kidney Fund. **Herbal supplements and chronic kidney disease.** https://www.kidneyfund.org/treatments/medicines-kidney-disease/herbal-supplements-and-chronic-kidney-disease-ckd
43. U.S. FDA Drug Safety Communication (Jan 8, 2014). **FDA warns of possible harm from exceeding recommended dose of over-the-counter sodium phosphate products to treat constipation.** https://www.fda.gov/drugs/drug-safety-and-availability/fda-drug-safety-communication-fda-warns-possible-harm-exceeding-recommended-dose-over-counter-sodium ; NKF Oral Sodium Phosphate Safety Alerts: https://kidney.org/node/25590
44. **Severe symptomatic hypermagnesemia associated with over-the-counter laxatives in a patient with renal failure.** Case Rep Nephrol. 2014. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3914018/
45. StatPearls. **Hypermagnesemia** (CKD as principal risk; Mg antacids/laxatives). https://www.ncbi.nlm.nih.gov/books/NBK549811/
46. American Kidney Fund, Kidney Kitchen. **Phosphorus Food Guide** (low ≤ 100 mg; medium 101–199 mg; high ≥ 200 mg per serving; ★ ≥ 250 mg K). https://kitchen.kidneyfund.org/wp-content/uploads/2021/08/Phosphorus-Guide.pdf
47. Per-meal rules of thumb (replaces a University of Michigan handout whose URL has redirected to the medical school's home page since 2026-10-05, design note 06 F1): American Kidney Fund, Kidney Kitchen, **Where do I find meal plans for low potassium?** (C. Feibig, RD), "600-700mg of potassium per meal and 100-200mg per snack for a daily goal of 1800 – 2200mg", https://kitchen.kidneyfund.org/?p=86324 ; Satellite Healthcare, **Food labels**, sodium "less than 600 mg per meal and less than 200 mg for a snack", https://www.satellitehealthcare.com/living-with-dialysis/eating-smart/food-labels (both accessed 2026-10-05).
48. NSW Agency for Clinical Innovation, **Haemodialysis diet specification** (menu-item cut-offs incl. < 300 mg phosphate per hot main dish). https://aci.health.nsw.gov.au/projects/diet-specifications/adult/renal/haemodialysis
49. American Kidney Fund, Kidney Kitchen. **Double-cook potatoes (video tip).** https://kitchen.kidneyfund.org/guides-and-videos/tip-double-cook-potatoes-cc/
50. KDIGO hyperkalaemia epidemiology source: Kovesdy CP, et al. Serum potassium and adverse outcomes across the range of kidney function: a CKD Prognosis Consortium meta-analysis. Eur Heart J. 2018;39:1535–1542 (cited in [2]).
51. USDA FoodData Central, **SR Legacy (April 2018)**, nutrient 1092 (potassium): Orange juice, raw (FDC 169098) 200 mg/100 g → 248 mg per ½ cup (124 g); Apple juice, unsweetened (173933) 101 mg/100 g → 125 mg; Grape juice, unsweetened (173042) 104 mg/100 g → 132 mg; Cranberry juice cocktail (171903) 14 mg/100 g → 18 mg. https://fdc.nal.usda.gov/download-datasets (values recomputed from the CSV release during fact-checking).
52. American Kidney Fund. **Potassium and kidney disease** (professional slide handout, PDF). Reproduces the dietary-potassium table from Kalantar-Zadeh & Fouque, N Engl J Med 2017 (K/DOQI 2004: G1–G2 > 4.0 g/d, G3a–G4 2.0–4.0 g/d; NEJM 2017: eGFR > 30 4.7 g/d, CKD 4–5 < 3 g/d; expert opinion: HD 2.7–3.0, PD 3.0–4.0, hyperkalaemia < 3.0 g/d) and states "aim for a daily potassium goal of 2,500 mg and no more than 3,000 mg per day" when restriction is prescribed; ≥ 250 mg/serving = high. https://www.kidneyfund.org/sites/default/files/media/documents/potassium-and-kidney-disease_0.pdf
