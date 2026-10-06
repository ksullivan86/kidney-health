# Fact-check of the three renal-diet research drafts

**Scope.** Adversarial review (2026-10-05) of `docs/research/ckd-diet.md`, `docs/research/t1d-and-ckd.md` and `docs/research/food-lists.md` for wrong numbers, wrong attributions, contradictions between the files, unsafe or missing advice, and unsourced claims. Every HIGH and MEDIUM issue below has been corrected in the draft files; LOW issues were also fixed where the fix was cheap, otherwise they are annotated in place.

> Reminder carried over from all three drafts: none of this is medical advice or a substitute for the person's nephrologist, endocrinologist/diabetes team and renal dietitian. Targets are individualised from the person's own labs and prescriptions.

## 1. What was checked and how

**Nutrient values (USDA FoodData Central).** The USDA API `DEMO_KEY` was rate-limited from this host (`OVER_RATE_LIMIT` on every call), so the exact dataset the drafts cite — **SR Legacy, April 2018 CSV release** (`FoodData_Central_sr_legacy_food_csv_2018-04.zip`, 7,793 foods) — was downloaded from fdc.nal.usda.gov and queried locally, which has no rate limit and is the primary source.

* `food-lists.md`: **all 263 table rows** in Sections A–C were recomputed from `food_nutrient.csv` using the FDC ID and gram weight given in Appendix 1. K, P and Na matched within 4 mg or 5 %; carbohydrate and protein within 0.6 g or 10 %. **0 mismatches.**
* `t1d-and-ckd.md`: **75 values** across the grain, fruit, hypoglycaemia, dairy and sample-day tables were recomputed (FDC 168878, 169704, 169737, 168910, 174924, 172688, 173905, 171657, 174648, 173884, 170250, 175057, 173242, 171695, 171688, 171711, 167762, 167755, 173946, 171722, 174683, 169124, 169126, 169930, 169936, 169949, 169105, 167765, 171719, 173944, 169097, 169092, 169655, 169640, 167990, 173205, 174846, 174852, 173933, 173042, 169098, 170872, 167587, 171265, 171267, 171269, 171942, 174832, 171255, 170853, 170886, 173424, 171890, 172470, 171496, 171009, 169248, 168409, 171477, 169141, 170397, 173418, 168421). All matched except the two items listed below (cantaloupe cup weight; tortilla entry choice). The sample-day meal and day totals were re-summed and are arithmetically correct (K 1,620 / P 711 / Na 903 / protein 64 g / carb 179 g).
* `ckd-diet.md`: the only per-serving nutrient figures it contains are the juice potassium values in §2.9, which were wrong (see H-4).

**Guideline statements checked against primary text (≥ 8 required; 24 done).**

| # | Statement | Source consulted | Result |
|---|---|---|---|
| 1 | KDIGO 2024 Rec 3.3.1.1 protein 0.8 g/kg/d, G3–G5 (2C) | KDIGO 2024 PDF, p. S117ff (downloaded, text-extracted) | Verified verbatim |
| 2 | KDIGO 2024 PP 3.3.1.1 avoid > 1.3 g/kg/d | same | Verified |
| 3 | KDIGO 2024 Rec 3.3.2.1 sodium < 2 g (< 90 mmol, < 5 g NaCl) (2C) | same | Verified |
| 4 | KDIGO 2024 PP 3.11.5.1–3.11.5.2 (individualised approach; limit foods rich in *bioavailable* potassium, e.g. processed foods) | same | Verified verbatim |
| 5 | KDIGO 2024 hyperkalaemia prevalence 8.8 % (G3/A1) → 34.4 % (G5/A3) with diabetes | same (text and Figure 30) | Verified |
| 6 | KDIGO 2024 Figure 33 potassium absorption 50–60 % plant / 70–90 % animal / 90 % processed (from Picard 2021) | same (Figure 33) | Verified |
| 7 | KDIGO 2024 "soaking foods for 5–10 minutes in previously boiled water can effectively reduce the potassium by half for some foods" | same | Verified |
| 8 | KDIGO 2024 PP 3.10.1 bicarbonate < 18 mmol/L; K ≥ 6.5 mmol/L = severe, immediate action | same | Verified |
| 9 | KDIGO 2022 Rec 3.1.1 protein 0.8 g/kg (2C); PP 3.1.2 HD "and particularly PD" 1.0–1.2 g/kg; Rec 3.1.2 sodium < 2 g (2C); Rec 2.2.1 HbA1c < 6.5 % to < 8.0 %; PP 2.1.2 HbA1c "low reliability" on dialysis; PP 3.1.1 diet pattern; "dramatically decrease caloric content" | KDIGO 2022 PDF (downloaded, text-extracted) | All verified verbatim |
| 10 | KDOQI 2020 statement numbering and grades: 3.0.1 (25–35 kcal/kg, 1C), 3.1.1 (0.55–0.60 / 0.28–0.43 + KA; 1A), 3.1.2 (1.0–1.2; HD 1C, PD OPINION), 3.1.4, 3.3.2 (2C), 6.1.1 (2C), 6.1.2 (1C), 6.1.3 (24–26 mmol/L OPINION), 6.2.1 (800–1,000 mg Ca, 2B), 6.2.2, 6.3.1 (1B), 6.3.2, 6.4.1, 6.4.2, 6.4.3 (2D), 6.5.1 (1B/1C/1C), 6.5.2 (2A), 6.5.3 (2B); phosphorus absorption animal 40–60 %, plant 20–50 % | NKF public-review PDF of KDOQI 2020 (AJKD full text returned HTTP 403); ISRNM commentary PMC9303594; published-grade check via secondary (ERA/Fouque) | All verified except: 3.1.3 diabetes protein is 0.8–0.9 in the *draft* and 0.6–0.8 in the *published* guideline (drafts already say this correctly); 3.1.1 QoL grade is **2C** in the published version (draft 1C) — fixed |
| 11 | ADA 2025 Rec 11.8 protein 0.8 g/kg (A), dialysis 1.0–1.2 (B); Rec 11.3 BP < 130/80 | PMC11635029 | Verified verbatim |
| 12 | ADA 2026 Sec 11 Rec 11.3 protein (A) / dialysis 1.0–1.2 (B); Rec 11.5 BP < 130/80, SBP < 120; "does not alter blood glucose levels…"; A1C less reliable, glycated albumin/fructosamine; RDN MNT sentence | PMC12690176 (full text **is** available — both drafts said it was pay-walled / not in PMC) | Verified; citations corrected |
| 13 | ADA 2026 Rec 6.15 glucose preferred, 15 g, 5–10 g for AID users, recheck 15 min, avoid high-fat/protein (B); Rec 6.16 glucagon (A); 6.3b–c CGM goals; hypoglycaemia levels 1–3; 6.11 awareness screening | PMC12690178 | Verified verbatim |
| 14 | ADA 2026 Recs 5.18–5.20, 5.22, 5.24 (14 g fibre/1,000 kcal), 5.27–5.28 | PMC12690188 | Verified |
| 15 | NIDDK: "If you have kidney disease, don't drink orange juice because it has a lot of potassium. Apple, grape, or cranberry juice are good options."; 15–20 g list | niddk.nih.gov | Verified verbatim |
| 16 | NKF: ≥ 200 mg/serving = high potassium; leaching steps (⅛ in, ≥ 2 h, 10:1, change water every 4 h, cook 5:1); salt substitutes listed as high-K | kidney.org/kidney-topics/potassium-your-ckd-diet | Verified |
| 17 | NKF carbohydrate counting: 15 g/serving; 3–6 servings per meal, 1–3 per snack | kidney.org | Verified |
| 18 | DaVita potassium schemes (NKF < 100 / 100–200 / 201–300 / > 300; AKF < 150 / 151–250 / > 250) and 2,000–3,000 mg/day restricted diet | davita.com | Verified |
| 19 | AKF: "aim for a daily potassium goal of 2,500 mg and no more than 3,000 mg per day"; ≥ 250 mg = high; NEJM 2017 / K-DOQI 2004 stage table | AKF handout PDF (text-extracted) | Verified; now cited in `ckd-diet.md` to support the stage ladder |
| 20 | DaVita PD: K 3,000–4,000; Na 3,000–4,000; fluid 2–3 L; "400 or more calories a day from the dialysate"; DaVita HD fluid 1,000 mL + 24-h urine, 1 kg/day | davita.com | Verified |
| 21 | Bethke & Jansky 2008: leaching alone no effect; boiling cubes −50 %, shredded −75 %; leaching before boiling adds nothing; "boil small pieces" | Europe PMC abstract (PMID 18576999) + ScienceDaily | Verified |
| 22 | Cabrera 2015: relative IDWG > 3.5 % body weight independently associated with all outcomes | PMC4510887 | Verified |
| 23 | Noori 2010 CJASN: 224 HD patients; HR 2.37 highest vs lowest P tertile; P:protein HRs 1.13 / 1.00 / 1.80 / 1.99; Noori 2010 IJKD: animal P 40–60 %, additives up to 100 %, ratio < 10 mg/g, egg white < 2 mg/g | PMC2849686; Europe PMC abstract PMID 20404416 | Verified |
| 24 | FDA: 3,400 mg average; > 70 % from packaged/prepared food; 5 %/20 % DV; claim definitions; Morton Lite Salt 290 mg Na / 350 mg K per ¼ tsp with physician warning; UF/IFAS 2,000–3,000 mg on dialysis; caramboxin mechanism | fda.gov; mortonsalt.com; ask.ifas.ufl.edu; de Oliveira 2015 / Wikipedia-cited pharmacology | Verified (caramboxin wording corrected) |

## 2. Issues found

Severity: **HIGH** = unsafe, missing safety advice, or a wrong number in a safety-relevant place; **MEDIUM** = wrong number/attribution or cross-file contradiction that would change what the app shows; **LOW** = attribution/grade/wording precision.

### HIGH (4)

| # | File | Quote | Problem | Correct value / source | Status |
|---|---|---|---|---|---|
| H-1 | `ckd-diet.md` §0 and §2.9 | "hypoglycaemia treatment must use low-potassium carbohydrate (not orange juice)"; "**Avoid orange juice (potassium), colas (phosphate additives)…**" | Stated as an absolute. Nothing said that a low must never be delayed or under-dosed because of potassium/phosphorus, or that glucagon is the treatment for level 3. An app built from this could warn against or block a rescue drink. | ADA 2026 Rec 6.15 (glucose preferred, 15 g, recheck 15 min; B) and 6.16 (glucagon for everyone on insulin; A), PMC12690178. A 4-oz orange juice is ~250 mg K (USDA) — a logging note, not a danger; untreated level 2–3 hypoglycaemia is an emergency. | Fixed: "prefer" wording; new **Safety rule** bullet in §2.9 incl. glucagon and "log, never block" instruction for the tracker |
| H-2 | `t1d-and-ckd.md` §2 | "The rule of 15 does not change." (then a ranking that marks orange juice, milk, banana **Avoid**) | Same omission: no explicit statement that potassium never delays treatment; "Avoid" labels could be read as prohibitions. | As H-1. | Fixed: new paragraph "**Potassium never delays treatment**" before the ranking table |
| H-3 | `food-lists.md` §0, A intro, C5 | "…never orange juice or cola [6][7]" | Same omission; "never" is unsafe wording for a rescue situation. | As H-1. | Fixed: §0 row, "Safety first" box in List A, C5 rewritten to "prefer … but if orange juice or cola is what is within reach, drink the 4 oz now" |
| H-4 | `ckd-diet.md` §2.9 | "Potassium: orange juice ~150 mg/½ cup vs apple ~125 mg vs cranberry ~0 mg [31]" | Wrong number from a hospital-medicine QI abstract; understates orange-juice potassium by ~40 % and contradicts the other two files (248 mg). | USDA SR Legacy: orange juice raw (FDC 169098) 200 mg/100 g → **248 mg per ½ cup**; apple juice (173933) 125 mg; grape juice (173042) 132 mg; cranberry juice cocktail (171903) 18 mg. | Fixed; ref 31 annotated as unreliable for numbers; new ref 51 |

### MEDIUM (10)

| # | File | Quote | Problem | Correct value / source | Status |
|---|---|---|---|---|---|
| M-1 | `t1d-and-ckd.md` table row "Phosphorus" and §1 point 1 | "plant phosphorus is <50% absorbed, animal ~70%"; "(<50%, versus ~70% from meat and ~100% from additives)" | Animal-source absorption overstated; contradicts `ckd-diet.md` and `food-lists.md` (40–60 %). | KDOQI 2020 text: "animal-based phosphate is absorbed in the GI tract by 40-60%, the absorption of plant-based phosphorus is lower (20-50%)"; Noori 2010 / Kalantar-Zadeh 2010: 40–60 % animal, up to 100 % additives. | Fixed in both places (~20–50 % plant, ~40–60 % animal, ~90–100 % additives) |
| M-2 | `t1d-and-ckd.md` §7 notes | "KDOQI/NEJM energy guidance is 30–35 kcal/kg/day (≈2,200–2,800 kcal for 75–80 kg) [13][4]" | Misattribution: KDOQI 2020 Statement 3.0.1 is **25–35** kcal/kg IBW/day (1C); 30–35 is the Kalantar-Zadeh & Fouque NEJM 2017 table. | KDOQI 2020 3.0.1 (public-review PDF p. 32; same in published text); AKF handout reproducing NEJM 2017. | Fixed; kcal range corrected to ≈1,900–2,800 |
| M-3 | `t1d-and-ckd.md` §7 assumptions | "potassium under ~2,000 mg, phosphorus under ~800 mg" for G3b–G4 | Contradicts the shared program defaults in `ckd-diet.md` (K ceiling 3,500 at G3b / 3,000 at G4; P 1,000) and the ranges the same file cites (2,000–3,000; AKF 2,500–3,000). | AKF handout (2,500, ≤ 3,000); KDOQI 2003 800–1,000 mg P; `ckd-diet.md` §7 JSON. | Fixed: assumptions now reference the shared targets and present the day as fitting even the strictest common prescription; headroom sentence corrected |
| M-4 | `t1d-and-ckd.md` table row "Protein" | "ADA warns not to go below 0.8 g/kg because of malnutrition risk" | Misattribution of the reason. ADA's reason is lack of benefit; the caloric-deficit/weight-loss argument is KDIGO 2022's. | ADA 2026 §11: "consuming protein below the recommended daily allowance of 0.8 g/kg/day is not recommended, because it does not alter blood glucose levels, cardiovascular risk measures, or the course of GFR decline" (PMC12690176); KDIGO 2022 §3.1 rationale. | Fixed |
| M-5a | `t1d-and-ckd.md` §2 table and §5 | "Di Iorio et al. measured 62 mg in 12 oz Coca-Cola Classic"; "Di Iorio et al. measured 27 mg … 41–68 mg in Diet Pepsi …" | Wrong attribution: Di Iorio 2012 is a review whose beverage table states "Kalantar-Zadeh et al reports …"; the measurements trace to Murphy-Gutekunst (J Ren Nutr 2005) via Kalantar-Zadeh CJASN 2010. | Di Iorio et al., Nutr Diet Suppl 2012 (Dove Press full text); Kalantar-Zadeh et al., CJASN 2010;5:519–530. | Fixed in text and ref 25 |
| M-5b | `food-lists.md` ref 19 and C2 | "Wickham E. … J Ren Nutr 2014 … measured values" | Same numbers attributed to a different paper than `t1d-and-ckd.md`; the primary compilation is Murphy-Gutekunst 2005 / Kalantar-Zadeh 2010. | As M-5a. | Fixed (ref 19 rewritten; Wickham kept as a later compilation) |
| M-6 | `t1d-and-ckd.md` grain table vs `food-lists.md` B3 | "Flour tortilla, 6 in … K 42, P 40, Na 153" vs "Flour tortilla 1 (6 in) … K 60, P 99, Na 353" | Cross-file contradiction: same food, 2.3× different sodium and 2.5× different phosphorus. Both are USDA but different entries and weights: t1d used FDC 173242 ("flour, without added calcium", 32 g); food-lists used FDC 175037 ("flour, refrigerated", 48 g). Neither was labelled. | SR Legacy per 100 g: 173242 — P 124, Na 478; 175037 — P 206, Na 736; 167535 (shelf stable) — P 213, Na 742. | Fixed: both rows now name the entry and weight and cross-reference each other; label-reading caveat added |
| M-7 | `food-lists.md` C1 heading | "### C1. High potassium (≥ 251 mg at a normal serving)" | Heading contradicts its own rows: orange (237), plantain (198), dark chocolate 1 oz (203), milk chocolate (164), cocoa (82) are listed under it. | NKF ≥ 200 mg = high; AKF ≥ 251 mg = high; concentrated sources judged at realistic portions. | Fixed: heading now states both rules and the "realistic portion" criterion |
| M-8 | `ckd-diet.md` §2.4 / §7 | Stage ladder "4,000 (3a) → 3,500 (3b) → 3,000 (4) → 2,500 (5 and HD) → 3,500 (PD)" | Claim without a primary source — cited only DaVita and UF/IFAS blog-level material. (The numbers themselves turned out to be consistent with published stage ranges, so the JSON did **not** need to change.) | AKF handout reproducing K/DOQI 2004 (G3a–G4 2.0–4.0 g/d), Kalantar-Zadeh & Fouque NEJM 2017 (CKD 4–5 < 3 g/d), expert opinion HD 2.7–3.0 / PD 3.0–4.0 g/d, AKF 2,500–3,000 mg goal. | Fixed: supporting paragraph and ref 52 added; field note updated |
| M-9 | `t1d-and-ckd.md` | (no mention of star fruit anywhere) | Missing safety advice in the diabetes-specific file; star fruit is marketed as a low-sugar fruit and is lethal in CKD. | de Oliveira & Aguiar, J Bras Nefrol 2015; NKF starfruit page (already cited in the other two files). | Fixed: bullet added to §5 |
| M-10 | `ckd-diet.md` refs 8–9, §2.2; `food-lists.md` §G | "2026 edition … was pay-walled during this review"; "ADA 2026 Section 11 full text was not yet deposited in PubMed Central" | Factually wrong at review time: PMC12690176 has the full 2026 Section 11. The two files also cite different recommendation numbers for the same statement (2025 "11.8" vs 2026 "11.3") without saying they are the same text renumbered. | PMC12690176 (Rec 11.3, 11.5); PMC11635029 (2025 Rec 11.8). | Fixed in both files |

### LOW (8)

| # | File | Quote | Problem | Correct value / source | Status |
|---|---|---|---|---|---|
| L-1 | `ckd-diet.md` §2.2 | "reduce ESKD/death (1A) and improve QoL (1C)" | QoL grade is 2C in the published KDOQI 2020; 1C was the 2019 public-review draft. | KDOQI 2020 3.1.1 (published); ERA/Fouque summary. | Fixed |
| L-2 | `ckd-diet.md` §5 | "caramboxin (a GABA-system neurotoxin)" | Incomplete/misleading mechanism: caramboxin is a glutamate (NMDA/AMPA) receptor agonist that also antagonises GABA inhibition. | Garcia-Cairasco et al. 2013; de Oliveira 2015 (PMID 26154645). | Fixed |
| L-3 | `t1d-and-ckd.md` fruit table | "cantaloupe, 1 cup … **427**" | Uses 160 g for a cup; `food-lists.md` and AKF use USDA's 156 g "1 cup, diced" → 417 mg. Minor cross-file inconsistency. | USDA 169092: 267 mg K/100 g × 156 g = 417 mg. | Fixed |
| L-4 | `food-lists.md` C1 | "Nu-Salt 530 mg [per ¼ tsp]" | Retailer label gives 530 mg per labelled serving (~1 g); ¼-tsp equivalence not verified. Morton Lite Salt (350 mg K + 290 mg Na per ¼ tsp) was missing from the row. | Nu-Salt listing (heb.com); Morton Lite Salt label. | Fixed (range 350–640; Na column 0–290) |
| L-5 | `food-lists.md` B2 leaching box | "…double-boiling … performs about as well as the long soak [2]" | The equivalence claim is from Bethke & Jansky / DaVita, not KDIGO [2]. | Bethke & Jansky 2008 (PMID 18576999). | Fixed (attribution split) |
| L-6 | `t1d-and-ckd.md` §5 | "One ounce of processed cheese was estimated to raise serum phosphorus by about 0.07 mg/dL in the Healio summary" | Secondary trade-press source; not verifiable against a primary paper during this review. | — | Left in place; flagged here as unverified |
| L-7 | `ckd-diet.md` ref 31 | SHM abstract retained as a reference | Its potassium figure is wrong (see H-4). | USDA (ref 51). | Annotated |
| L-8 | `t1d-and-ckd.md` §4 | NKF milk-alternative brand values (Oatly 390 mg K / 270 mg P etc.) | Could not be re-verified (kidney.org page not fetched); brand formulations change. | NKF Milk Alternatives page [28]. | Left; drafts already say "read the label" |

## 3. Things that were checked and found correct (no change)

* All 263 `food-lists.md` nutrient rows and 73 of 75 `t1d-and-ckd.md` nutrient values (see §1).
* `targets_by_stage` JSON in `ckd-diet.md`: protein 0.6–0.8 (KDOQI 3.1.3) / 1.0–1.2 on dialysis; sodium 2,000; potassium ceilings within K/DOQI 2004, NEJM 2017 and AKF ranges; phosphorus 900–1,000 within KDOQI 2003's 800–1,000; calcium 1,000 (KDOQI 6.2.1 800–1,000); HD fluid 1,000 mL + urine (DaVita/AKF); PD fluid 2,000 within 2–3 L; 30 kcal/kg within 25–35. **No numeric changes required.**
* Per-serving classification thresholds agree across the three files (NKF ≥ 200 mg high; AKF ≤ 150 / 151–250 / ≥ 251; AKF P ≤ 100 / 101–199 / ≥ 200; FDA Na ≤ 140 low, ≥ 460 high).
* Daily restricted-potassium range 2,000–3,000 mg agrees across files and with DaVita, UF/IFAS and AKF (2,500–3,000).
* Salt-substitute, star-fruit (two files), dialysis-protein and sugar-alcohol advice present and consistent with NKF/NIDDK/ADA.
* Phosphorus absorption (plant 20–50 %, animal 40–60 %, additives 90–100 %) and potassium absorption (50–60 / 70–90 / 90 %) now agree across all three files with KDOQI 2020 and KDIGO 2024.

## 4. Counts

* HIGH: 4 (all fixed)
* MEDIUM: 10 (all fixed)
* LOW: 8 (6 fixed, 2 annotated)

## 5. v0.3 addendum: the potassium-additive rule (2026-10-06)

**Rule** (ARCHITECTURE.md v0.3 item 9; design note 03 R5; code `app/nutrients.py`
`food_warnings`, twin `app/static/js/engine/rules.js`): a food flagged `potassium_additive` (an
ingredient list or additive code naming a bulk potassium salt: E508 potassium chloride, E326 lactate,
E332 citrates, E261 acetates, E340 / E450(v) / E451(ii) / E452(ii) phosphates, E501 carbonates, …;
`app/additives.py`) gets a **medium** potassium warning, "Contains a potassium additive; potassium not
listed", when its potassium value is unknown. When the label lists potassium, the normal per-serving
thresholds apply. The flag never produces a high warning on its own. Trace uses (sorbate, benzoate,
acesulfame K, iodide, …) give a note only.

| # | Statement the rule relies on | Source consulted (2026-10-06) | Result |
|---|---|---|---|
| 25 | Meat, poultry and fish products that list a potassium additive contain far more potassium: median **900 mg/100 g (750–1,100)** against 325 mg (260–470) for products without one and 420 mg (270–450) for additive-free references; potassium additives were listed on 9 % of 76 products | Parpia AS et al. *J Ren Nutr* 2018;28:83–90, doi:10.1053/j.jrn.2017.08.013 (PMID 29146137), abstract via Europe PMC | Verified |
| 26 | Enhanced raw meat and poultry: additive-free products all < 387 mg K/100 g; 5 of 25 enhanced products ≥ 692 mg, **maximum 930 mg/100 g**; **8 of 25 enhanced products did not list the additives** | Sherman RA, Mehta O. *CJASN* 2009;4:1370–1373, doi:10.2215/CJN.02830409 (PMID 19628683), abstract | Verified |
| 27 | Potassium additives are more bioavailable than potassium in whole foods, and their use in processed foods is growing | Picard K. *J Ren Nutr* 2019;29:350–353, doi:10.1053/j.jrn.2018.10.003 (PMID 30579674), abstract | Verified (narrative review) |
| 28 | Absorption of potassium from processed foods / additives about 90 % | KDIGO 2024 Figure 33 (row 6 of §1 above, from Picard 2021) | Verified earlier (row 6) |

**Why medium and not high when the value is unknown.** Note 03 R5 proposed `high`; the contract
(v0.3 item 9) chose `medium` until a renal dietitian reviews it: an additive's dose varies widely
(Sherman: 5 of 25 enhanced products were at least 692 mg/100 g, the rest lower), and an unknown value
already shows as "Potassium: not listed" next to the food. **Open decision for the owner and a renal
dietitian:** whether "unknown + additive" should be `high`. The handbook lists the rule for clinical
review (`handbook/docs/reference/about.md`); the decision is tracked in `docs/ROADMAP.md`.

**Absence is not proof.** Sherman found 8 of 25 enhanced products without the additive on the label,
so the app never treats a missing additive as "no added potassium" (`docs/barcode-and-photos.md`).
