/* Kidney Diet Log — personalised suggested targets: the browser twin of app/targets.py with the data
   of app/target_rules.py (note 05 §4.3–§4.6). Every number, rule, source and note text is the
   server's, word for word; all rounding is decimal half-up like app.nutrients._half_up.

   The installed app always asks the server (GET /api/profile/suggested-targets). This copy powers
   the demo/preview API (js/mock/profile.js, js/mock/labs.js) and lets the Labs view say before
   saving whether a new result would change a suggestion.

   Parity: tests/data/targets_vectors.json is generated from the Python rules
   (tests/data/gen_targets_vectors.py; pytest checks it is current) and replayed here by
   `node tests/js/run_vectors.mjs`, including the tables below. When a guideline changes, change
   app/target_rules.py, regenerate the vectors, then update this file until the runner passes.

   Plain script: needs js/engine/rules.js and js/engine/kidney_function.js first; runs in the page
   (window.KH.targets) and under Node with the same bare-global shim as rules.js. No DOM. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const { CKD_STAGES, DIALYSIS_MODES, DIABETES_TYPES, halfUp, pyG } = KH.rules;
  const K = KH.kidney;

  function rule(source, grade, url, opinionNote = null) {
    return { source, grade, opinion: opinionNote !== null, opinion_note: opinionNote, url };
  }

  // Sources (note 05 §9)
  const URL_ADA_2026_S11 = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12690176';
  const URL_ADA_2026_S5 = 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12690188';
  const URL_AKF_POTASSIUM = 'https://www.kidneyfund.org/living-kidney-disease/healthy-eating-activity/kidney-friendly-eating-plan/potassium';
  const URL_CARI_2010 = 'https://doi.org/10.1111/j.1440-1797.2010.01238.x';
  const URL_DAVITA_FLUID = 'https://www.davita.com/diet-nutrition/articles/basics/fluid-management-for-dialysis-patients';
  const URL_ESPEN_2022 = 'https://doi.org/10.1016/j.clnu.2022.01.024';
  const URL_FANTUZZI_2022 = 'https://doi.org/10.33393/gcnd.2022.2365';
  const URL_GLIM_2019 = 'https://doi.org/10.1016/j.clnu.2018.08.002';
  const URL_INKER_2021 = 'https://doi.org/10.1056/NEJMoa2102953';
  const URL_IOM_2011_CALCIUM = 'https://www.nationalacademies.org/read/13050/chapter/2';
  const URL_KDIGO_2022 = 'https://kdigo.org/wp-content/uploads/2023/12/KDIGO-2022-Diabetes-Guideline.pdf';
  const URL_KDIGO_2024 = 'https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf';
  const URL_KDOQI_2003_BONE = 'https://www.kidney.org/sites/default/files/docs/boneguidelines.pdf';
  const URL_KDOQI_2020 = 'https://doi.org/10.1053/j.ajkd.2020.05.006';
  const URL_NASEM_2023_ENERGY = 'https://doi.org/10.17226/26818';

  const RULES = {
    'S-1': rule('KDIGO 2024 (pregnancy outside its scope); NASEM 2023 pregnancy energy equations', '–', URL_KDIGO_2024, 'refusal is project policy'),
    'S-2': rule('KDIGO 2024 PP 3.3.1.4, PP 3.3.2.2, PP 1.2.4.3', 'PP', URL_KDIGO_2024, 'age counted from the last day of the birth month'),
    'S-3': rule('CARI 2010 (about 1.4 g/kg for 4 weeks); KDOQI 2020 "metabolically stable" definition', '–', URL_CARI_2010, 'the 12-week cut-off'),
    'W-1': rule('KDOQI 2020 1.1.6', 'OPINION', URL_KDOQI_2020),
    'W-2': rule('KDOQI 2020 1.1.6', 'OPINION', URL_KDOQI_2020),
    'W-3': rule('KDOQI 2020 Table 5 (adjusted body weight, Karkeck)', '– (not validated in CKD)', URL_KDOQI_2020, 'using it above BMI 25'),
    'W-4': rule('KDOQI 2020 Table 5 (KDOQI 2000 adjusted oedema-free body weight)', '–', URL_KDOQI_2020, 'using it below BMI 18.5'),
    'N-1': rule('GLIM 2019; ISRNM 2008; KDIGO 2024 PP 3.3.1.5', 'consensus / PP', URL_GLIM_2019, 'used as a risk flag, not a diagnosis'),
    'E-1': rule('NASEM 2023 DRI Energy Table S-1; KDOQI 2020 3.1.1', 'DRI; 1C (range)', URL_NASEM_2023_ENERGY, 'combining the energy equation with the kidney range'),
    'E-2': rule('KDOQI 2020 3.1.1', '1C (range)', URL_KDOQI_2020, '30 kcal/kg, the middle of the range'),
    'E-3': rule('ESPEN 2022 R1; KDOQI 2020 3.1.1 rationale', 'B', URL_ESPEN_2022, 'applying the 30 kcal/kg floor in CKD'),
    'E-4': rule('Grodstein 1981; EBPG and ESPEN via Fantuzzi 2022', '–', URL_FANTUZZI_2022, 'the 20 kcal/kg floor'),
    'P-1': rule('RDA 0.8 g/kg; KDIGO 2024 PP 3.3.1.1 (avoid more than 1.3 g/kg)', 'PP', URL_KDIGO_2024, 'the 1.0 g/kg ceiling'),
    'P-2d': rule("ADA 2026 Rec 11.3; KDIGO 2022 Rec 3.1.1; KDIGO 2024 Rec 3.3.1.1 (KDOQI 2020 3.0.2's 0.6 g/kg needs close supervision)", 'A / 2C / 2C', URL_ADA_2026_S11),
    'P-2n': rule('KDOQI 2020 3.0.1; KDIGO 2024 Rec 3.3.1.1, PP 3.3.1.3', '1A (supervised) / 2C / PP', URL_KDOQI_2020, 'the 0.6 g/kg lower bound (listed for clinical review)'),
    'P-3': rule('KDOQI 2020 3.0.3 (no diabetes), 3.0.4 (diabetes); KDIGO 2022 PP 3.1.2; ADA 2026 Rec 11.3', '3.0.3: 1C (HD) / OPINION (PD); 3.0.4: OPINION; PP; B', URL_KDOQI_2020),
    'P-5': rule('KDIGO 2024 PP 3.3.1.5 and rationale; ADA 2026 Rec 13.11a; ESPEN 2022 R2; PROT-AGE 2013 (incl. its eGFR < 30 exception)', 'PP / B / B / consensus', URL_KDIGO_2024, 'the numbers'),
    'P-6': rule('KDOQI 2000; KDOQI 2020 3.0.4', '– / OPINION', URL_KDOQI_2020, '1.2–1.3 g/kg with nutrition risk'),
    'P-7': rule('CARI 2010; KDOQI 2020 "metabolically stable" definition', '–', URL_CARI_2010, '0.8–1.0 g/kg'),
    'K-0': rule('v0.2 ladder (K/DOQI 2004; Kalantar-Zadeh & Fouque, NEJM 2017; AKF)', '–', URL_AKF_POTASSIUM, 'the ladder'),
    'K-1': rule('KDOQI 2020 6.4.2', '2D', URL_KDOQI_2020),
    'K-2': rule('KDOQI 2020 6.4.1; KDIGO 2024 PP 3.11.5.2', 'OPINION / PP', URL_KDOQI_2020, 'relaxing by one step'),
    'K-2h': rule('KDIGO 2024 PP 3.11.5.2', 'PP', URL_KDIGO_2024),
    'K-3': rule('KDIGO 2024 (CKD-PC definition, over 5.0 mmol/L); AKF (no more than 3000 mg)', '–', URL_KDIGO_2024, '3000 mg'),
    'K-4': rule('KDIGO 2024 Figure 32; AKF (aim for 2500 mg)', '–', URL_KDIGO_2024, '2500 mg'),
    'K-5': rule('KDIGO 2024 Table 28', '–', URL_KDIGO_2024, '2000 mg'),
    'PH-0': rule('KDOQI 2003 Guideline 4.1 (800–1000 mg)', 'OPINION / EVIDENCE', URL_KDOQI_2003_BONE, 'the number picked in the range'),
    'PH-T': rule('KDOQI 2020 6.3.3', 'OPINION', URL_KDOQI_2020, 'the graft-stage cut'),
    'PH-1': rule('KDOQI 2020 6.3.3 (transplant)', 'OPINION', URL_KDOQI_2020),
    'PH-2': rule('KDOQI 2020 6.3.1', '1B', URL_KDOQI_2020, '1000 mg'),
    'PH-3': rule('KDOQI 2020 6.3.1; KDOQI 2003 4.1; KDIGO 2017 4.1.2, 4.1.8', '1B / OPINION–EVIDENCE / 2C / 2D', URL_KDOQI_2020, 'the low end of the range'),
    'NA-1': rule('KDIGO 2024 Rec 3.3.2.1; KDOQI 2020 6.5.1', '2C; 1B/1C', URL_KDIGO_2024),
    'CA-0': rule('IOM (NASEM) 2011 Dietary Reference Intakes, RDA for ages 19–50', 'DRI', URL_IOM_2011_CALCIUM),
    'CA-1': rule('KDOQI 2020 6.2.1 (not taking active vitamin D)', '2B', URL_KDOQI_2020),
    'CA-2': rule('KDOQI 2020 6.2.2 (CKD 5D; no KDOQI statement covers stage 5 without dialysis)', 'OPINION', URL_KDOQI_2020, 'stage 5 without dialysis'),
    'CA-3': rule('IOM (NASEM) 2011 Dietary Reference Intakes, Table S-1', 'DRI', URL_IOM_2011_CALCIUM),
    'F-0': rule('ESPEN 2022 R61 and its commentary', 'B', URL_ESPEN_2022, 'the stage G1–G3b cut'),
    'F-0o': rule('ESPEN 2022 R61 and its commentary', 'B', URL_ESPEN_2022, 'the stage G1–G3b cut'),
    'F-1': rule('Dialysis-unit convention (DaVita, AKF)', '–', URL_DAVITA_FLUID, 'the convention'),
    'F-2': rule('Dialysis-unit convention (DaVita, AKF)', '–', URL_DAVITA_FLUID, 'the convention'),
    'F-3': rule('Individualised (no graded number)', '–', URL_KDOQI_2020, '2000 mL'),
    'F-4': rule('Individualised (no graded number)', '–', URL_KDOQI_2020, 'urine plus ultrafiltration'),
    'C-1': rule('ADA (individualise carbohydrate)', '–', URL_ADA_2026_S5, '45 % of calories (v0.2)'),
    'FB-1': rule('ADA 2026 Rec 5.24; IOM 2005', 'B', URL_ADA_2026_S5),
    'L-ALB': rule('KDOQI 2020 1.2.1, 1.2.2, 4.1.1', 'OPINION / 1A / 2D', URL_KDOQI_2020),
    'L-BIC22': rule('KDOQI 2020 6.1.1 (CKD 1–4), 6.1.2–6.1.3 (CKD 3–5D)', '2C / 1C / OPINION', URL_KDOQI_2020),
    'L-BIC18': rule('KDIGO 2024 PP 3.10.1', 'PP', URL_KDIGO_2024),
    'L-UACR-A1': rule('KDIGO 2024 Table 3; KDOQI 2020 6.5.2', 'definition', URL_KDIGO_2024),
    'L-UACR-A2': rule('KDIGO 2024 Table 3; KDOQI 2020 6.5.2', 'definition', URL_KDIGO_2024),
    'L-UACR-A3': rule('KDIGO 2024 Table 3; KDOQI 2020 6.5.2', 'definition', URL_KDIGO_2024),
    'L-A1C': rule('KDIGO 2022 PP 2.1.2', 'PP', URL_KDIGO_2022),
    'G-1': rule('KDIGO 2024 Rec 1.2.4.1, Rec 1.2.2.1, PP 1.2.4.2, PP 1.1.3.2; CKD-EPI 2021 (Inker 2021)', '1D / 1C / PP', URL_INKER_2021),
  };
  const NOTES = {
    'W-1': 'Weight basis: {w:g} kg is in the healthy BMI range (BMI {bmi:.1f}) for {h:g} cm, so your actual weight is used for calories and protein.',
    'W-2': 'Weight basis: without a saved height your actual weight ({w:g} kg) is used. Add your height so the app can adjust for a weight above or below the healthy range.',
    'W-3': "Weight basis: at BMI {bmi:.1f}, calories and protein use an adjusted weight of {ref:g} kg: the weight at BMI 25 for {h:g} cm ({w25:g} kg) plus a quarter of the weight above it. Guidelines leave the choice of weight to your care team (KDOQI 2020 1.1.6); this is the app's default.",
    'W-4': "Weight basis: at BMI {bmi:.1f}, calories and protein use {ref:g} kg: your weight moved a quarter of the way toward the healthy range ({w185:g} kg at BMI 18.5), as in KDOQI's adjusted body weight. Gaining weight safely is a job for your renal dietitian.",
    'W-D': ' Enter your dry weight, measured after a dialysis session.',
    'N-1': 'Nutrition risk: {reasons}. The app moves protein and calories to the higher end. Ask your renal dietitian for a nutrition assessment and whether oral nutrition supplements would help (KDOQI 2020 4.1.1).',
    'N-1.low_bmi': 'BMI {bmi:.1f} is below {thr:g}',
    'N-1.low_bmi.older': 'BMI {bmi:.1f} is below {thr:g}, the low-weight cut-off from age 70 (GLIM 2019)',
    'N-1.weight_loss': 'you have lost {pct:.1f} % of your weight in 6 months',
    'N-1.low_albumin': 'blood albumin {alb:.1f} g/dL is below 3.8',
    'N-1.frailty': 'frailty or low muscle mass is marked in your profile',
    'E-1': 'Calories: {kcal} kcal/day, the energy estimate for your age, sex, height, {ref:g} kg and activity ("{activity_label}") from the 2023 Dietary Reference Intakes ({kpk:.1f} kcal/kg), kept inside the kidney guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1).',
    'E-1.estimate': 'Energy estimate: {kcal} kcal/day for your age, sex, height, {ref:g} kg and activity ("{activity_label}") from the 2023 Dietary Reference Intakes ({kpk:.1f} kcal/kg), kept inside the kidney guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1). The calories suggested are in the next note.',
    'E-1.clamped': ' The estimate was {raw:.1f} kcal/kg, so it was set to {edge} kcal/kg.',
    'E-1.unspecified': ' Sex is not set, so the average of the female and male equations is used.',
    'E-2': 'Calories: 30 kcal/kg × {ref:g} kg = {kcal} kcal/day, the middle of the guideline range of 25–35 kcal/kg (KDOQI 2020 3.1.1). Add your birth month, sex, height and activity for a personal estimate.',
    'E-3': 'Calories: {kcal} kcal/day, raised to 30 kcal/kg × {ref:g} kg because of the nutrition risk above (ESPEN 2022; KDOQI 2020: 30–35 kcal/kg keeps protein balance).',
    'E-4': 'Peritoneal dialysis: {pdk} kcal/day absorbed from dialysis fluid was subtracted, so food calories are {kcal} of {total} kcal.',
    'E-4.floor': 'Peritoneal dialysis: about {pdk} kcal/day is absorbed from dialysis fluid, but food calories are kept at 20 kcal/kg × {ref:g} kg, so they are {kcal} of {total} kcal. Ask your renal dietitian about this.',
    'E-4.insulin': ' That glucose also needs insulin; your diabetes team plans for it.',
    'E-PD.missing': ' On peritoneal dialysis, add the calories your body absorbs from the dialysis fluid (ask your PD nurse) so the app can subtract them from food calories.',
    'P-1': 'Protein: {min}–{max} g/day (0.8–1.0 g/kg × {ref:g} kg). At stages 1–2 guidelines only ask you to avoid more than 1.3 g/kg (KDIGO 2024).',
    'P-2d': 'Protein: about {max} g/day (0.8 g/kg × {ref:g} kg) for CKD stages 3–5 with diabetes (KDIGO 2022 Rec 3.1.1; KDIGO 2024 Rec 3.3.1.1; ADA 2026 Rec 11.3). With diabetes, eating less than 0.8 g/kg is not recommended (ADA 2026): it risks muscle loss and low blood sugar. A lower amount (KDOQI 2020 3.0.2: 0.6–0.8) is only for people under close supervision by their care team. Avoid more than 1.3 g/kg (KDIGO 2024).',
    'P-2n': 'Protein: {min}–{max} g/day (0.6–0.8 g/kg × {ref:g} kg) for CKD stages 3–5. KDIGO 2024 Rec 3.3.1.1 suggests 0.8 g/kg. Going below 0.8 (KDOQI 2020 3.0.1: 0.55–0.6) needs close supervision by your care team, and is not for anyone who is unwell, in hospital recently or losing weight (KDIGO 2024 PP 3.3.1.3). Avoid more than 1.3 g/kg (KDIGO 2024).',
    'P-3': 'Protein: {min}–{max} g/day (1.0–1.2 g/kg × {ref:g} kg) on {mode_label} (KDOQI 2020 3.0.3/3.0.4). Dialysis removes protein, so more is needed, not less.',
    'P-5a': 'Protein raised to {lo}–{hi} g/kg ({min}–{max} g/day) because {why}: in older adults and people at risk of malnutrition, losing muscle is often the bigger danger (KDIGO 2024 PP 3.3.1.5; ADA 2026 Rec 13.11a: at least 0.8 g/kg). If your kidney function is falling fast, your team may still prefer a lower range.',
    'P-5a.older': 'you are 65 or older',
    'P-5a.risk': 'of the nutrition risk above',
    'P-5a.both': 'you are 65 or older and at nutrition risk',
    'P-6': 'Protein raised to 1.2–1.3 g/kg ({min}–{max} g/day) because of the nutrition risk above (KDOQI 2000: 1.2 on hemodialysis, 1.2–1.3 on peritoneal dialysis).',
    'P-7': 'Protein: {min}–{max} g/day (0.8–1.0 g/kg × {ref:g} kg) for a working kidney transplant. No guideline sets a long-term number; low-protein diets are not used with anti-rejection medicines.',
    'P-7.graft': " It is not raised further for age because your transplant's function is at stage {stage}; ask your team.",
    'K-0': 'Potassium: {k_mg} mg/day is a review ceiling for {stage_label}, not a prescription; no blood potassium from the last {days} days is saved. {potassium_note}',
    'K-0.labs_off': 'Potassium: {k_mg} mg/day is a review ceiling for {stage_label}, not a prescription; this server does not change it for blood test results. {potassium_note}',
    'K-1': 'Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is low, so no potassium limit is set. Ask your care team whether to eat more potassium-rich foods or take a supplement (KDOQI 2020 6.4.2). {potassium_note}',
    'K-2': 'Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, so the review ceiling is relaxed one step to {k_mg} mg/day. While it stays normal there is no need to cut fruit and vegetables (KDOQI 2020 6.4.1; KDIGO 2024). {potassium_note}',
    'K-2.top': 'Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, so the review ceiling stays at {k_mg} mg/day, already the highest step for {stage_label}. While it stays normal there is no need to cut fruit and vegetables (KDOQI 2020 6.4.1; KDIGO 2024). {potassium_note}',
    'K-2h': 'Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is normal, but you have had high potassium before or take a potassium binder, so the ceiling stays at {k_mg} mg/day; processed foods with potassium additives matter most (KDIGO 2024 PP 3.11.5.2). {potassium_note}',
    'K-3': 'Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is above normal (over 5.0), so the ceiling is {k_mg} mg/day. Check processed foods with potassium additives, salt substitutes and large portions first; your team may also review medicines (KDIGO 2024 Figure 32). {potassium_note}',
    'K-4': 'Potassium: your blood potassium ({k:.1f} mmol/L on {date}) is high (over 5.5), so the ceiling is {k_mg} mg/day. Tell your care team; they may change medicines or start a potassium binder. {potassium_note}',
    'K-5': 'Potassium: {k:.1f} mmol/L on {date} is dangerously high. {urgency} The ceiling is set to {k_mg} mg/day until your team gives you a number. {potassium_note}',
    'K-5.urgent': 'Contact your care team today: this result should be repeated within 24 hours, and if you feel unwell (weakness, palpitations or an irregular pulse) get urgent medical care now (KDIGO 2024 Table 28).',
    'K-5.emergency': 'Get urgent medical care now, especially with weakness, palpitations or an irregular pulse (KDIGO 2024 Table 28).',
    'K-5.alert': 'Potassium {k:.1f} mmol/L on {date} is dangerously high. {urgency}',
    'PH-0': 'Phosphorus: {p_mg} mg/day (guideline range 800–1000 mg when phosphate runs high); no phosphate result from the last {days} days is saved. Avoiding phosphate additives matters more than the total because additive phosphorus is almost fully absorbed.',
    'PH-0.labs_off': 'Phosphorus: {p_mg} mg/day (guideline range 800–1000 mg when phosphate runs high); this server does not change it for blood test results. Avoiding phosphate additives matters more than the total because additive phosphorus is almost fully absorbed.',
    'PH-T': 'Phosphorus: not limited after a kidney transplant unless your phosphate is high; low phosphate is common in the first months (KDOQI 2020 6.3.3).',
    'PH-1': 'Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is low, so no phosphorus limit is set. Ask your team whether to eat more phosphorus or take a supplement (KDOQI 2020 6.3.3).',
    'PH-2': 'Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is normal; {p_mg_or_none} is a review ceiling. Keep avoiding phosphate additives (KDOQI 2020 6.3.1–6.3.2).',
    'PH-2.none': 'Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is normal, so no phosphorus limit is set after a kidney transplant. Keep avoiding phosphate additives (KDOQI 2020 6.3.1–6.3.2).',
    'PH-3': 'Phosphorus: your phosphate ({p:.1f} mg/dL on {date}) is above normal (over 4.5), so the target is 800 mg/day, the low end of the 800–1000 mg range (KDOQI 2003; KDIGO 2017). Cut phosphate additives first and take binders with meals as prescribed. On dialysis keep protein up by choosing foods with little phosphorus per gram of protein (egg whites, fresh meat and fish).',
    'NA-1': 'Sodium: 2000 mg/day for every adult with CKD, whatever the age or sex (KDIGO 2024; KDOQI 2020 6.5.1: under 2300 mg).',
    'CA-0': 'Calcium: 1000 mg/day. Add your birth month and sex for the amount recommended for your age.',
    'CA-1': 'Calcium: at most 1000 mg/day in total, counting calcium-based binders and supplements (KDOQI 2020 6.2.1: 800–1000 mg at stages 3–4 when not taking active vitamin D such as calcitriol). At these stages it does not change with age or sex.',
    'CA-2': "Calcium: 1000 mg/day in total as a starting point; at stage 5 and on dialysis your team adjusts it to avoid high calcium, counting binders and vitamin D medicines (KDOQI 2020 6.2.2 covers dialysis; for stage 5 without dialysis this is the app's default).",
    'CA-3': 'Calcium: {rda}–{ul} mg/day: the general recommendation for your age and sex ({rda} mg) up to the safe upper limit ({ul} mg) (Dietary Reference Intakes 2011).',
    'F-0': 'Fluid: no limit without dialysis unless your care team sets one.',
    'F-0o': 'Fluid: no limit without dialysis unless your care team sets one. Thirst fades with age: unless your team limits fluid, or you have heart failure or swelling, aim for at least {floor} of drinks a day (ESPEN 2022).',
    'F-1': 'Fluid: 1000 mL plus your 24-hour urine volume; 1500 mL assumes about 500 mL of urine. Enter your urine volume or ask your dialysis unit for your allowance.',
    'F-2': 'Fluid: 1000 mL + your {u} mL of urine = {fluid} mL/day, the usual hemodialysis allowance; your unit may set a different number.',
    'F-3': 'Fluid: about 2000 mL/day on peritoneal dialysis. Enter your daily urine volume and ultrafiltration for a personal number.',
    'F-4': 'Fluid: urine {u} mL + ultrafiltration {uf} mL = {fluid} mL/day, about what your body removes each day. Check it with your PD nurse.',
    'C-1': 'Carbohydrate: 45 % of calories ÷ 4 kcal/g = {carbs} g/day.',
    'C-1.diabetes': 'Carbohydrate: 45 % of calories ÷ 4 kcal/g = {carbs} g/day, about {per_meal} g per meal for carb counting; your insulin-to-carb ratio decides the real per-meal number.',
    'FB-1': 'Fibre: at least {fib} g/day (14 g per 1000 kcal, ADA 2026). When potassium is limited, get it from low-potassium fruit, vegetables and grains.',
    'L-ALB': 'Low albumin can also come from inflammation or protein lost in urine, not only from diet (KDOQI 2020 1.2.1). Labs measure albumin in different ways; ask your team whether this result counts as low for your lab.',
    'L-BIC22': 'Bicarbonate {b:.1f} mmol/L is below 22: acid builds up as kidneys fail. {fv}Your team may prescribe bicarbonate (KDOQI 2020 6.1.2).',
    'L-BIC22.fv': 'More fruit and vegetables lower the acid load (KDOQI 2020 6.1.1){k_caveat}. ',
    'L-BIC22.k_caveat': ' (your potassium is high, so ask your team first)',
    'L-BIC18': 'Bicarbonate {b:.1f} mmol/L is below 18. KDIGO 2024 says treatment should be considered at this level (practice point 3.10.1); tell your care team.',
    'L-UACR': 'Urine albumin {uacr:.1f} {unit} (as entered) is category {cat} ({cat_label}). It does not change food targets but is a reason to keep sodium low (KDOQI 2020 6.5.2).',
    'L-UACR.a3_low_albumin': ' With low blood albumin this can mean protein is lost in urine; your team may set protein differently.',
    'L-A1C': 'A1c and CGM readings do not change these food targets; in advanced CKD A1c is less reliable (KDIGO 2022 PP 2.1.2).',
    END: 'These are starting points only — confirm every target with your nephrologist and renal dietitian.',
  };
  const REFUSALS = {
    out_of_scope_pregnancy: { rule: 'S-1', message: 'Targets are not suggested during pregnancy or breastfeeding: needs for energy, protein, calcium and fluid change, and kidney disease in pregnancy needs specialist care. Ask your kidney and maternity teams for targets; you can still enter them by hand.' },
    out_of_scope_under_18: { rule: 'S-2', message: "Targets are not suggested for people under 18: children need more protein and energy to grow, and kidney guidelines for children are different. Ask your child's kidney team; you can still enter targets by hand." },
    out_of_scope_early_transplant: { rule: 'S-3', message: 'Your kidney transplant was less than 12 weeks ago. In the first weeks your transplant team sets a recovery diet, usually higher in protein, so the app does not suggest targets yet. You can still enter targets by hand.' },
  };

  const RULE_ORDER = ['S', 'W', 'N', 'E', 'P', 'K', 'PH', 'NA', 'CA', 'F', 'C', 'FB', 'L'];

  // -------------------------------------------------------------------------
  // Numbers (note 05 §4.3; app/target_rules.py)
  // -------------------------------------------------------------------------
  const MODES = ['ckd', 'transplant', 'hemodialysis', 'peritoneal'];
  const EARLY_STAGES = ['1', '2']; // G1–G2
  const STAGES_TO_3B = ['1', '2', '3a', '3b']; // G1–G3b (F-0o, PH-T)
  const STAGES_1_TO_4 = ['1', '2', '3a', '3b', '4']; // KDOQI 6.1.1 scope (L-BIC22 fruit sentence)
  const ADULT_AGE = 18;
  const OLDER_AGE = 65; // P-5, F-0o
  const GLIM_OLDER_AGE = 70; // low-BMI threshold switches from 20 to 22
  const EARLY_TRANSPLANT_DAYS = 84; // 12 weeks (S-3, OPINION)
  const BMI_LOW = 18.5;
  const BMI_HIGH = 25.0;
  const BMI_EPS = 1e-9;
  const ADJUST_FRACTION = 0.25;
  const LOW_BMI = { under_70: 20.0, from_70: 22.0 }; // GLIM 2019
  const WEIGHT_LOSS_PCT = 5.0; // GLIM 2019
  const LOW_ALBUMIN_G_DL = 3.8; // ISRNM 2008
  const KCAL_PER_KG_MIN = 25.0; // KDOQI 2020 3.1.1
  const KCAL_PER_KG_MAX = 35.0;
  const KCAL_PER_KG_DEFAULT = 30.0; // E-2
  const KCAL_PER_KG_RISK_FLOOR = 30.0; // E-3
  const PD_FOOD_FLOOR_KCAL_PER_KG = 20.0; // E-4
  // NASEM 2023 DRI for Energy, Table S-1 (adults): kcal/day = intercept + age·years + height·cm + weight·kg.
  const EER_COEFFICIENTS = {
    male: { inactive: [753.07, -10.83, 6.50, 14.10], low_active: [581.47, -10.83, 8.30, 14.94],
      active: [1004.82, -10.83, 6.52, 15.91], very_active: [-517.88, -10.83, 15.61, 19.11] },
    female: { inactive: [584.90, -7.01, 5.72, 11.71], low_active: [575.77, -7.01, 6.60, 12.14],
      active: [710.25, -7.01, 6.54, 12.34], very_active: [511.83, -7.01, 9.07, 12.56] },
  };
  const ACTIVITIES = ['inactive', 'low_active', 'active', 'very_active'];
  const ACTIVITY_LABELS = { inactive: 'inactive', low_active: 'low active', active: 'active', very_active: 'very active' };
  const SEXES = ['female', 'male', 'unspecified'];
  const PROTEIN_G_PER_KG = {
    dialysis: [1.0, 1.2], transplant: [0.8, 1.0], early: [0.8, 1.0], late_diabetes: [0.8, 0.8], late_no_diabetes: [0.6, 0.8],
    older_early: [1.0, 1.2], older_late: [0.8, 1.0], dialysis_risk: [1.2, 1.3],
  };
  const POTASSIUM_LADDER = { 1: 4000, 2: 4000, '3a': 4000, '3b': 3500, 4: 3000, 5: 2500, hemodialysis: 2500, peritoneal: 3500 };
  const POTASSIUM_RELAXED = { 1: 4000, 2: 4000, '3a': 4000, '3b': 4000, 4: 3500, 5: 3000, hemodialysis: 3000, peritoneal: 4000 };
  const POTASSIUM_LOW = 3.5;
  const POTASSIUM_NORMAL_MAX = 5.0;
  const POTASSIUM_HIGH_MAX = 5.5;
  const POTASSIUM_VERY_HIGH = 6.0;
  const POTASSIUM_EMERGENCY = 6.5;
  const POTASSIUM_CAPS = { 'K-3': 3000, 'K-4': 2500, 'K-5': 2000 };
  const PHOSPHORUS_DEFAULT = { 1: 1000, 2: 1000, '3a': 1000, '3b': 1000, 4: 1000, 5: 900, hemodialysis: 1000, peritoneal: 1000 };
  const PHOSPHATE_LOW = 2.5;
  const PHOSPHATE_HIGH = 4.5;
  const PHOSPHORUS_NORMAL_MG = 1000;
  const PHOSPHORUS_HIGH_MG = 800;
  const SODIUM_MG = 2000;
  const CALCIUM_MG = 1000;
  const CALCIUM_DRI = [
    { min_age: 14, max_age: 18, female: 1300, male: 1300, ul: 3000 },
    { min_age: 19, max_age: 50, female: 1000, male: 1000, ul: 2500 },
    { min_age: 51, max_age: 70, female: 1200, male: 1000, ul: 2000 },
    { min_age: 71, max_age: 200, female: 1200, male: 1200, ul: 2000 },
  ];
  const FLUID_HD_BASE_ML = 1000;
  const FLUID_HD_DEFAULT_ML = 1500;
  const FLUID_PD_DEFAULT_ML = 2000;
  const FLUID_STEP_ML = 50;
  const FLUID_FLOOR_TEXT = { female: '1.6 L', male: '2.0 L', unspecified: '1.6 L (women) or 2.0 L (men)' };
  const CARB_FRACTION = 0.45;
  const CARBS_PER_MEAL_MIN_G = 15;
  const CARBS_PER_MEAL_STEP_G = 5;
  const FIBER_G_PER_1000_KCAL = 14;
  const BICARBONATE_LOW = 22.0;
  const BICARBONATE_VERY_LOW = 18.0;
  const POTASSIUM_NOTE = 'Only restrict potassium if your blood potassium is high; your care team sets the number.';
  const ALERT_CODE_POTASSIUM = 'potassium_very_high';
  const MISSING_INPUT_ORDER = ['height_cm', 'birth_month', 'sex', 'activity', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal'];
  const TARGET_LABS = ['potassium', 'phosphate', 'albumin', 'bicarbonate', 'uacr', 'a1c'];
  const DEFAULT_FRESH_DAYS = Object.fromEntries(K.CONFIGURABLE_FRESHNESS.map((a) => [a, K.ANALYTES[a].fresh_days]));
  const MAX_AGE = 120;

  // -------------------------------------------------------------------------
  // Python formatting: str.format with {name}, {name:g} and {name:.Nf}
  // -------------------------------------------------------------------------
  function pyFormat(template, values) {
    return template.replace(/\{(\w+)(?::(g|\.(\d+)f))?\}/g, (whole, name, spec, decimals) => {
      if (!Object.prototype.hasOwnProperty.call(values, name)) throw new Error(`format: no value for {${name}}`);
      const v = values[name];
      if (spec === 'g') return pyG(v);
      if (decimals !== undefined) return K.fixed(v, Number(decimals));
      return String(v);
    });
  }
  // nutrients._half_up for any (also negative) number of places: Decimal(repr(x)).quantize(10**-places, ROUND_HALF_UP).
  function halfUpTo(x, places) {
    if (places >= 0) return halfUp(x, places);
    x = Number(x);
    if (!Number.isFinite(x)) return x;
    let s = String(Math.abs(x));
    let exp = 0;
    const ei = s.indexOf('e');
    if (ei >= 0) { exp = Number(s.slice(ei + 1)); s = s.slice(0, ei); }
    const di = s.indexOf('.');
    const digits = di >= 0 ? s.slice(0, di) + s.slice(di + 1) : s;
    if (di >= 0) exp -= s.length - di - 1;
    const drop = -places - exp;
    if (drop <= 0) return x;
    let keep = 0n, first = 0;
    if (drop <= digits.length) {
      keep = BigInt(digits.slice(0, digits.length - drop) || '0');
      first = digits.charCodeAt(digits.length - drop) - 48;
    }
    if (first >= 5) keep += 1n;
    const r = Number(`${keep}e${-places}`);
    return x < 0 ? -r : r;
  }
  const toInt = (v) => halfUp(Number(v), 0); // _int
  const roundStep = (v, step) => halfUp(Number(v) / step, 0) * step; // _round_step
  const calories = (v) => halfUpTo(Number(v), -1); // _calories: nearest 10 kcal
  const has = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);

  // -------------------------------------------------------------------------
  // Formulas
  // -------------------------------------------------------------------------
  class OutOfScope extends Error {
    constructor(code) { super(REFUSALS[code].message); this.code = code; this.rule = REFUSALS[code].rule; }
  }
  class InvalidInput extends Error {}

  // Sex-neutral reference weight (KDOQI 2020 Table 5 formulas on the BMI-based weight) [OPINION].
  function referenceWeight(weightKg, heightCm) {
    const w = Number(weightKg);
    if (!Number.isFinite(w) || w <= 0) throw new InvalidInput('weight_kg must be a positive number');
    if (heightCm == null) return { weight_kg: halfUp(w, 1), basis: 'actual_no_height', bmi: null, w25: null, w18_5: null };
    const hCm = Number(heightCm);
    if (!Number.isFinite(hCm) || hCm <= 0) throw new InvalidInput('height_cm must be a positive number');
    const h = hCm / 100.0;
    const h2 = h * h;
    const bmi = w / h2;
    const w25 = BMI_HIGH * h2;
    const w185 = BMI_LOW * h2;
    let ref, basis;
    if (bmi > BMI_HIGH + BMI_EPS) { ref = w25 + ADJUST_FRACTION * (w - w25); basis = 'adjusted_above_bmi25'; }
    else if (bmi < BMI_LOW - BMI_EPS) { ref = w + ADJUST_FRACTION * (w185 - w); basis = 'adjusted_below_bmi18_5'; }
    else { ref = w; basis = 'actual'; }
    return { weight_kg: halfUp(ref, 1), basis, bmi, w25, w18_5: w185 };
  }
  // NASEM 2023 estimated energy requirement, kcal/day, unrounded ("unspecified": mean of both equations).
  function eerKcal(sex, activity, age, heightCm, weightKg) {
    if (!ACTIVITIES.includes(activity)) throw new InvalidInput(`activity must be one of ${ACTIVITIES.join(', ')}`);
    if (sex === 'unspecified') return (eerKcal('female', activity, age, heightCm, weightKg) + eerKcal('male', activity, age, heightCm, weightKg)) / 2;
    if (sex !== 'female' && sex !== 'male') throw new InvalidInput(`sex must be one of ${SEXES.join(', ')}`);
    const [intercept, a, h, w] = EER_COEFFICIENTS[sex][activity];
    return intercept + a * age + h * Number(heightCm) + w * Number(weightKg);
  }
  function modeOf(dialysis, transplantDate) {
    if (dialysis === 'hemodialysis' || dialysis === 'peritoneal') return dialysis;
    return transplantDate ? 'transplant' : 'ckd';
  }
  function labDisplay(analyte, lab) { return lab == null ? null : K.displayValue(analyte, lab.value); }
  // The newest result of each target lab, kept only while it is fresh.
  function freshLabs(rows, today, freshDays = null) {
    const windows = { ...DEFAULT_FRESH_DAYS, ...(freshDays || {}) };
    const parsed = rows.map(K.labRow);
    const out = {};
    for (const analyte of TARGET_LABS) {
      const latest = K.newest(parsed.filter((r) => r.analyte === analyte));
      if (latest === null) continue;
      if (K.isFresh(latest.taken_on, today, K.freshDays(analyte, windows))) {
        out[analyte] = { value: latest.value, taken_on: latest.taken_on, entered_value: latest.entered_value, entered_unit: latest.entered_unit };
      }
    }
    return out;
  }
  function calciumDri(age, sex) {
    for (const row of CALCIUM_DRI) {
      if (row.min_age <= age && age <= row.max_age) return [sex === 'unspecified' ? Math.max(row.female, row.male) : row[sex], row.ul];
    }
    throw new InvalidInput(`no calcium reference value for age ${age}`);
  }
  function potassiumAlertLevel(kShown) { return kShown >= POTASSIUM_EMERGENCY ? 'emergency' : 'urgent'; }
  // The safety alert for a potassium of 6.0 mmol/L or more (shown value), else null.
  function potassiumAlert(potassium) {
    if (potassium == null) return null;
    const k = K.displayValue('potassium', potassium.value);
    if (k < POTASSIUM_VERY_HIGH) return null;
    const level = potassiumAlertLevel(k);
    return { level, code: ALERT_CODE_POTASSIUM, analyte: 'potassium', value: k, taken_on: potassium.taken_on,
      message: pyFormat(NOTES['K-5.alert'], { k, date: potassium.taken_on, urgency: NOTES[`K-5.${level}`] }) };
  }
  function missingInputs(inputs, mode) {
    const missing = {
      height_cm: inputs.height_cm == null,
      birth_month: inputs.birth_month == null,
      sex: inputs.sex === 'unspecified',
      activity: inputs.activity == null,
      urine_output_ml: (mode === 'hemodialysis' || mode === 'peritoneal') && inputs.urine_output_ml == null,
      pd_uf_ml: mode === 'peritoneal' && inputs.pd_uf_ml == null,
      pd_dialysate_kcal: mode === 'peritoneal' && inputs.pd_dialysate_kcal == null,
    };
    return MISSING_INPUT_ORDER.filter((name) => missing[name]);
  }

  // -------------------------------------------------------------------------
  // Inputs (targets.Inputs) and their validation
  // -------------------------------------------------------------------------
  const INPUT_DEFAULTS = {
    dialysis: 'none', diabetes: 'type1', height_cm: null, birth_month: null, sex: 'unspecified', activity: null, transplant_date: null,
    frail_or_sarcopenic: false, weight_6_months_ago_kg: null, pregnant_or_breastfeeding: false, hyperkalemia_history: false,
    urine_output_ml: null, pd_uf_ml: null, pd_dialysate_kcal: null,
  };
  function makeInputs(values) {
    return { ...INPUT_DEFAULTS, labs: {}, lab_rules_enabled: true, default_activity: 'inactive', fresh_days: { ...DEFAULT_FRESH_DAYS }, ...values };
  }
  function finite(v) { return typeof v !== 'boolean' && v !== null && v !== '' && Number.isFinite(Number(v)); }
  function validateInputs(inputs, today) {
    const w = inputs.weight_kg;
    if (w == null || typeof w === 'boolean' || !finite(w) || Number(w) <= 0) throw new InvalidInput('weight_kg must be a positive number');
    if (inputs.height_cm != null && (!finite(inputs.height_cm) || Number(inputs.height_cm) <= 0)) throw new InvalidInput('height_cm must be a positive number');
    if (!CKD_STAGES.includes(inputs.ckd_stage)) throw new InvalidInput(`ckd_stage must be one of ${CKD_STAGES.join(', ')}`);
    if (!DIALYSIS_MODES.includes(inputs.dialysis)) throw new InvalidInput(`dialysis must be one of ${DIALYSIS_MODES.join(', ')}`);
    if (!DIABETES_TYPES.includes(inputs.diabetes)) throw new InvalidInput(`diabetes must be one of ${DIABETES_TYPES.join(', ')}`);
    if (!SEXES.includes(inputs.sex)) throw new InvalidInput(`sex must be one of ${SEXES.join(', ')}`);
    for (const [name, value] of [['activity', inputs.activity], ['default_activity', inputs.default_activity]]) {
      if (value != null && !ACTIVITIES.includes(value)) throw new InvalidInput(`${name} must be one of ${ACTIVITIES.join(', ')}`);
    }
    if (inputs.birth_month != null) {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(inputs.birth_month)) throw new InvalidInput('birth_month must be formatted YYYY-MM');
      if (inputs.birth_month > today.slice(0, 7)) throw new InvalidInput('birth_month must not be in the future');
      if ((K.ageOn(inputs.birth_month, today) || 0) > MAX_AGE) throw new InvalidInput(`birth_month must be within the last ${MAX_AGE} years`);
    }
    if (inputs.transplant_date != null) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(inputs.transplant_date)) throw new InvalidInput('transplant_date must be formatted YYYY-MM-DD');
      const parsed = K.parseIsoDate(inputs.transplant_date);
      if (parsed.error) throw new InvalidInput(parsed.error);
    }
    for (const name of ['weight_6_months_ago_kg', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal']) {
      const value = inputs[name];
      if (value != null && (!finite(value) || Number(value) < 0)) throw new InvalidInput(`${name} must be a non-negative number`);
    }
  }
  function stageLabel(mode, stage) {
    if (mode === 'hemodialysis') return 'hemodialysis';
    if (mode === 'peritoneal') return 'peritoneal dialysis';
    if (mode === 'transplant') return `a kidney transplant at stage ${stage}`;
    return `stage ${stage}`;
  }

  // -------------------------------------------------------------------------
  // The rules (targets.suggest)
  // -------------------------------------------------------------------------
  // suggest(inputs, today) -> {targets, notes, rules, derived, missing_inputs, alerts};
  // throws OutOfScope (the 422 refusals) or InvalidInput (the 400 for an unusable profile).
  function suggest(inputs, today) {
    validateInputs(inputs, today);
    const mode = modeOf(inputs.dialysis, inputs.transplant_date);
    const stage = inputs.ckd_stage;
    const onDialysis = mode === 'hemodialysis' || mode === 'peritoneal';
    const ladderKey = onDialysis ? mode : stage;
    const hasDiabetes = inputs.diabetes !== 'none';
    const age = K.ageOn(inputs.birth_month, today);

    // S: refusals, before any number.
    if (inputs.pregnant_or_breastfeeding) throw new OutOfScope('out_of_scope_pregnancy');
    if (inputs.birth_month != null && (K.ageOn(inputs.birth_month, today, { lastDay: true }) || 0) < ADULT_AGE) throw new OutOfScope('out_of_scope_under_18');
    if (mode === 'transplant' && K.dayNumber(today) - K.dayNumber(inputs.transplant_date) < EARLY_TRANSPLANT_DAYS) throw new OutOfScope('out_of_scope_early_transplant');

    const rules = [];
    const notes = [];
    const apply = (ruleId, note = null, catalogueId = null) => {
      rules.push({ id: ruleId, ...RULES[catalogueId || ruleId] });
      if (note) notes.push(note);
    };
    const labsOn = !!inputs.lab_rules_enabled;
    const lab = {}, shown = {};
    for (const a of TARGET_LABS) { lab[a] = labsOn && has(inputs.labs, a) ? inputs.labs[a] : null; shown[a] = labDisplay(a, lab[a]); }
    const windows = { ...DEFAULT_FRESH_DAYS, ...(inputs.fresh_days || {}) };

    // W: reference weight.
    const actual = Number(inputs.weight_kg);
    const rw = referenceWeight(actual, inputs.height_cm);
    const ref = rw.weight_kg;
    const bmiShown = rw.bmi === null ? null : halfUp(rw.bmi, 1);
    const h = inputs.height_cm == null ? null : Number(inputs.height_cm);
    let wId, wNote;
    if (rw.basis === 'actual_no_height') { wId = 'W-2'; wNote = pyFormat(NOTES['W-2'], { w: actual }); }
    else if (rw.basis === 'actual') { wId = 'W-1'; wNote = pyFormat(NOTES['W-1'], { w: actual, bmi: bmiShown, h }); }
    else if (rw.basis === 'adjusted_above_bmi25') { wId = 'W-3'; wNote = pyFormat(NOTES['W-3'], { bmi: bmiShown, ref, h, w25: halfUp(rw.w25 || 0, 1) }); }
    else { wId = 'W-4'; wNote = pyFormat(NOTES['W-4'], { bmi: bmiShown, ref, w185: halfUp(rw.w18_5 || 0, 1) }); }
    if (onDialysis) wNote += NOTES['W-D'];
    apply(wId, wNote);

    // N: nutrition risk (a flag, not a diagnosis).
    const risk = [];
    const reasons = [];
    if (bmiShown !== null) {
      const threshold = age !== null && age >= GLIM_OLDER_AGE ? LOW_BMI.from_70 : LOW_BMI.under_70;
      if (bmiShown < threshold) {
        risk.push('low_bmi');
        reasons.push(pyFormat(NOTES[threshold === LOW_BMI.from_70 ? 'N-1.low_bmi.older' : 'N-1.low_bmi'], { bmi: bmiShown, thr: threshold }));
      }
    }
    if (inputs.weight_6_months_ago_kg != null && Number(inputs.weight_6_months_ago_kg) > 0) {
      const before = Number(inputs.weight_6_months_ago_kg);
      const pct = halfUp((before - actual) / before * 100.0, 1);
      if (pct > WEIGHT_LOSS_PCT) { risk.push('weight_loss'); reasons.push(pyFormat(NOTES['N-1.weight_loss'], { pct })); }
    }
    if (shown.albumin !== null && shown.albumin < LOW_ALBUMIN_G_DL) { risk.push('low_albumin'); reasons.push(pyFormat(NOTES['N-1.low_albumin'], { alb: shown.albumin })); }
    if (inputs.frail_or_sarcopenic) { risk.push('frailty'); reasons.push(NOTES['N-1.frailty']); }
    if (risk.length) apply('N-1', pyFormat(NOTES['N-1'], { reasons: reasons.join('; ') }));

    // E: energy.
    const activity = inputs.activity || inputs.default_activity;
    let eer = null, eerPerKg = null, kpk, eId, note;
    if (age !== null && h !== null) {
      eer = eerKcal(inputs.sex, activity, age, h, ref);
      eerPerKg = eer / ref;
      kpk = Math.min(Math.max(eerPerKg, KCAL_PER_KG_MIN), KCAL_PER_KG_MAX);
      const raised = risk.length > 0 && kpk < KCAL_PER_KG_RISK_FLOOR; // E-3 follows: this is only the estimate
      note = pyFormat(NOTES[raised ? 'E-1.estimate' : 'E-1'], { kcal: calories(kpk * ref), ref, activity_label: ACTIVITY_LABELS[activity], kpk: halfUp(kpk, 1) });
      if (kpk !== eerPerKg) note += pyFormat(NOTES['E-1.clamped'], { raw: halfUp(eerPerKg, 1), edge: pyG(kpk) });
      if (inputs.sex === 'unspecified') note += NOTES['E-1.unspecified'];
      eId = 'E-1';
    } else {
      kpk = KCAL_PER_KG_DEFAULT;
      eId = 'E-2';
      note = pyFormat(NOTES['E-2'], { ref, kcal: calories(kpk * ref) });
    }
    if (mode === 'peritoneal' && inputs.pd_dialysate_kcal == null) note += NOTES['E-PD.missing'];
    apply(eId, note);
    if (risk.length && kpk < KCAL_PER_KG_RISK_FLOOR) {
      kpk = KCAL_PER_KG_RISK_FLOOR;
      apply('E-3', pyFormat(NOTES['E-3'], { kcal: calories(kpk * ref), ref }));
    }
    const total = kpk * ref;
    let food = total;
    const pdk = inputs.pd_dialysate_kcal;
    if (mode === 'peritoneal' && pdk) {
      const floor = PD_FOOD_FLOOR_KCAL_PER_KG * ref;
      food = Math.max(total - Number(pdk), floor);
      const key = total - Number(pdk) >= floor ? 'E-4' : 'E-4.floor';
      let n = pyFormat(NOTES[key], { pdk: toInt(Number(pdk)), kcal: calories(food), total: calories(total), ref });
      if (hasDiabetes) n += NOTES['E-4.insulin'];
      apply('E-4', n);
    }
    const kcal = calories(food);

    // P: protein (g/kg × reference weight, each bound rounded half-up).
    const older = age !== null && age >= OLDER_AGE;
    const early = EARLY_STAGES.includes(stage);
    const grams = (perKg) => ({ min: toInt(perKg[0] * ref), max: toInt(perKg[1] * ref) });
    let perKg, g;
    if (onDialysis) {
      perKg = PROTEIN_G_PER_KG.dialysis; g = grams(perKg);
      apply('P-3', pyFormat(NOTES['P-3'], { min: g.min, max: g.max, ref, mode_label: stageLabel(mode, stage) }));
    } else if (mode === 'transplant') {
      perKg = PROTEIN_G_PER_KG.transplant; g = grams(perKg);
      let n = pyFormat(NOTES['P-7'], { min: g.min, max: g.max, ref });
      if ((older || risk.length) && !early) n += pyFormat(NOTES['P-7.graft'], { stage });
      apply('P-7', n);
    } else if (early) {
      perKg = PROTEIN_G_PER_KG.early; g = grams(perKg);
      apply('P-1', pyFormat(NOTES['P-1'], { min: g.min, max: g.max, ref }));
    } else if (hasDiabetes) {
      perKg = PROTEIN_G_PER_KG.late_diabetes; g = grams(perKg);
      apply('P-2', pyFormat(NOTES['P-2d'], { max: g.max, ref }), 'P-2d');
    } else {
      perKg = PROTEIN_G_PER_KG.late_no_diabetes; g = grams(perKg);
      apply('P-2', pyFormat(NOTES['P-2n'], { min: g.min, max: g.max, ref }), 'P-2n');
    }
    if (onDialysis) {
      if (risk.length) {
        perKg = PROTEIN_G_PER_KG.dialysis_risk; g = grams(perKg);
        apply('P-6', pyFormat(NOTES['P-6'], { min: g.min, max: g.max }));
      }
    } else if ((older || risk.length) && (early || mode === 'ckd')) {
      perKg = PROTEIN_G_PER_KG[early ? 'older_early' : 'older_late']; g = grams(perKg);
      const why = NOTES[older && risk.length ? 'P-5a.both' : older ? 'P-5a.older' : 'P-5a.risk'];
      apply('P-5', pyFormat(NOTES['P-5a'], { lo: K.fixed(perKg[0], 1), hi: K.fixed(perKg[1], 1), min: g.min, max: g.max, why }));
    }
    const protein = g;

    // K: potassium (ladder L, relaxed R, caps; labs judged on the shown value).
    const ladder = POTASSIUM_LADDER[ladderKey];
    const sLabel = stageLabel(mode, stage);
    const k = shown.potassium;
    const kLab = lab.potassium;
    const alerts = [];
    let potassium;
    const kv = (extra) => ({ k, date: kLab && kLab.taken_on, potassium_note: POTASSIUM_NOTE, ...extra });
    if (k === null || kLab === null) {
      potassium = ladder;
      if (labsOn) apply('K-0', pyFormat(NOTES['K-0'], { k_mg: ladder, stage_label: sLabel, days: windows.potassium, potassium_note: POTASSIUM_NOTE }));
      else apply('K-0', pyFormat(NOTES['K-0.labs_off'], { k_mg: ladder, stage_label: sLabel, potassium_note: POTASSIUM_NOTE }));
    } else if (k < POTASSIUM_LOW) {
      potassium = null;
      apply('K-1', pyFormat(NOTES['K-1'], kv({})));
    } else if (k <= POTASSIUM_NORMAL_MAX) {
      if (inputs.hyperkalemia_history) { potassium = ladder; apply('K-2h', pyFormat(NOTES['K-2h'], kv({ k_mg: potassium }))); }
      else {
        potassium = POTASSIUM_RELAXED[ladderKey];
        // Stages 1–3a: the relaxed step is the ladder, so nothing was relaxed.
        if (potassium === ladder) apply('K-2', pyFormat(NOTES['K-2.top'], kv({ k_mg: potassium, stage_label: sLabel })));
        else apply('K-2', pyFormat(NOTES['K-2'], kv({ k_mg: potassium })));
      }
    } else if (k <= POTASSIUM_HIGH_MAX) {
      potassium = Math.min(ladder, POTASSIUM_CAPS['K-3']);
      apply('K-3', pyFormat(NOTES['K-3'], kv({ k_mg: potassium })));
    } else if (k < POTASSIUM_VERY_HIGH) {
      potassium = Math.min(ladder, POTASSIUM_CAPS['K-4']);
      apply('K-4', pyFormat(NOTES['K-4'], kv({ k_mg: potassium })));
    } else {
      potassium = Math.min(ladder, POTASSIUM_CAPS['K-5']);
      const urgency = NOTES[`K-5.${potassiumAlertLevel(k)}`];
      apply('K-5', pyFormat(NOTES['K-5'], kv({ urgency, k_mg: potassium })));
    }
    // The safety alert does not depend on targets.lab_rules_enabled (note 05 §4.9).
    const alert = potassiumAlert(has(inputs.labs, 'potassium') ? inputs.labs.potassium : null);
    if (alert !== null) alerts.push(alert);

    // PH: phosphorus.
    const p = shown.phosphate;
    const pLab = lab.phosphate;
    const graftEarly = mode === 'transplant' && STAGES_TO_3B.includes(stage);
    let phosphorus;
    if (p === null || pLab === null) {
      if (graftEarly) { phosphorus = null; apply('PH-T', NOTES['PH-T']); }
      else {
        phosphorus = PHOSPHORUS_DEFAULT[ladderKey];
        if (labsOn) apply('PH-0', pyFormat(NOTES['PH-0'], { p_mg: phosphorus, days: windows.phosphate }));
        else apply('PH-0', pyFormat(NOTES['PH-0.labs_off'], { p_mg: phosphorus }));
      }
    } else if (p < PHOSPHATE_LOW) {
      phosphorus = null;
      apply('PH-1', pyFormat(NOTES['PH-1'], { p, date: pLab.taken_on }));
    } else if (p <= PHOSPHATE_HIGH) {
      if (graftEarly) { phosphorus = null; apply('PH-2', pyFormat(NOTES['PH-2.none'], { p, date: pLab.taken_on })); }
      else { phosphorus = PHOSPHORUS_NORMAL_MG; apply('PH-2', pyFormat(NOTES['PH-2'], { p, date: pLab.taken_on, p_mg_or_none: `${phosphorus} mg/day` })); }
    } else {
      phosphorus = PHOSPHORUS_HIGH_MG;
      apply('PH-3', pyFormat(NOTES['PH-3'], { p, date: pLab.taken_on }));
    }

    // NA: sodium.
    apply('NA-1', NOTES['NA-1']);

    // CA: calcium.
    let calcium;
    if (!onDialysis && early) {
      if (age === null) { calcium = CALCIUM_MG; apply('CA-0', NOTES['CA-0']); }
      else { const [rda, ul] = calciumDri(age, inputs.sex); calcium = { min: rda, max: ul }; apply('CA-3', pyFormat(NOTES['CA-3'], { rda, ul })); }
    } else if (!onDialysis && stage !== '5') { calcium = CALCIUM_MG; apply('CA-1', NOTES['CA-1']); }
    else { calcium = CALCIUM_MG; apply('CA-2', NOTES['CA-2']); }

    // F: fluid.
    let fluid;
    if (mode === 'hemodialysis') {
      if (inputs.urine_output_ml != null) {
        const u = Number(inputs.urine_output_ml);
        fluid = roundStep(FLUID_HD_BASE_ML + u, FLUID_STEP_ML);
        apply('F-2', pyFormat(NOTES['F-2'], { u: toInt(u), fluid }));
      } else { fluid = FLUID_HD_DEFAULT_ML; apply('F-1', NOTES['F-1']); }
    } else if (mode === 'peritoneal') {
      if (inputs.urine_output_ml != null && inputs.pd_uf_ml != null) {
        const u = Number(inputs.urine_output_ml), uf = Number(inputs.pd_uf_ml);
        fluid = roundStep(u + uf, FLUID_STEP_ML);
        apply('F-4', pyFormat(NOTES['F-4'], { u: toInt(u), uf: toInt(uf), fluid }));
      } else { fluid = FLUID_PD_DEFAULT_ML; apply('F-3', NOTES['F-3']); }
    } else {
      fluid = null;
      if (older && STAGES_TO_3B.includes(stage)) apply('F-0o', pyFormat(NOTES['F-0o'], { floor: FLUID_FLOOR_TEXT[inputs.sex] }));
      else apply('F-0', NOTES['F-0']);
    }

    // C: carbohydrate (v0.2 notes), FB: fibre — both from the food calories.
    const carbs = toInt(kcal * CARB_FRACTION / 4.0);
    const perMeal = Math.max(CARBS_PER_MEAL_MIN_G, roundStep(carbs / 4.0, CARBS_PER_MEAL_STEP_G));
    if (hasDiabetes) apply('C-1', pyFormat(NOTES['C-1.diabetes'], { carbs, per_meal: perMeal }));
    else apply('C-1', pyFormat(NOTES['C-1'], { carbs }));
    const fiber = toInt(FIBER_G_PER_1000_KCAL * kcal / 1000.0);
    apply('FB-1', pyFormat(NOTES['FB-1'], { fib: fiber }));

    // L: lab notes (only when lab rules are on).
    if (shown.albumin !== null && shown.albumin < LOW_ALBUMIN_G_DL) apply('L-ALB', NOTES['L-ALB']);
    const bic = shown.bicarbonate;
    if (bic !== null && bic < BICARBONATE_LOW) {
      let fv = '';
      if (!onDialysis && STAGES_1_TO_4.includes(stage)) {
        const kCaveat = k !== null && k > POTASSIUM_NORMAL_MAX ? NOTES['L-BIC22.k_caveat'] : '';
        fv = pyFormat(NOTES['L-BIC22.fv'], { k_caveat: kCaveat });
      }
      apply('L-BIC22', pyFormat(NOTES['L-BIC22'], { b: bic, fv }));
      if (bic < BICARBONATE_VERY_LOW) apply('L-BIC18', pyFormat(NOTES['L-BIC18'], { b: bic }));
    }
    const uacr = lab.uacr;
    if (uacr !== null) {
      const enteredValue = uacr.entered_value != null ? uacr.entered_value : uacr.value;
      const enteredUnit = uacr.entered_unit || K.analyteDef('uacr').canonical_unit;
      const cat = K.albuminuriaCategory(enteredValue, enteredUnit);
      let n = pyFormat(NOTES['L-UACR'], { uacr: halfUp(enteredValue, 1), unit: K.canonicalUnitName('uacr', enteredUnit), cat, cat_label: K.ALBUMINURIA_LABELS[cat] });
      if (cat === 'A3' && shown.albumin !== null && shown.albumin < LOW_ALBUMIN_G_DL) n += NOTES['L-UACR.a3_low_albumin'];
      apply(`L-UACR-${cat}`, n);
    }
    if (lab.a1c !== null) apply('L-A1C', NOTES['L-A1C']);
    notes.push(NOTES.END);

    const targets = { calories_kcal: kcal, protein_g: protein, carbs_g: carbs, carbs_per_meal_g: perMeal, fiber_g: { min: fiber },
      sodium_mg: SODIUM_MG, potassium_mg: potassium, phosphorus_mg: phosphorus, calcium_mg: calcium, fluid_ml: fluid };
    const labsUsed = {};
    for (const a of TARGET_LABS) labsUsed[a] = lab[a] === null ? null : { value: shown[a], unit: K.analyteDef(a).canonical_unit, taken_on: lab[a].taken_on };
    const derived = {
      mode, age, sex: inputs.sex, activity, bmi: bmiShown, reference_weight_kg: ref, weight_basis: rw.basis,
      eer_kcal: eer === null ? null : toInt(eer), eer_kcal_per_kg: eerPerKg === null ? null : halfUp(eerPerKg, 1),
      kcal_per_kg: halfUp(kpk, 1), nutrition_risk: risk, labs_used: labsUsed, lab_rules_enabled: labsOn,
    };
    return { targets, notes, rules, derived, missing_inputs: missingInputs(inputs, mode), alerts };
  }

  // -------------------------------------------------------------------------
  // From stored records (GET /api/profile/suggested-targets and the parity vectors)
  // -------------------------------------------------------------------------
  const PROFILE_FIELDS = ['weight_kg', 'ckd_stage', 'dialysis', 'diabetes', 'height_cm', 'birth_month', 'sex', 'activity', 'transplant_date',
    'frail_or_sarcopenic', 'weight_6_months_ago_kg', 'pregnant_or_breastfeeding', 'hyperkalemia_history', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal'];
  const BOOL_FIELDS = ['frail_or_sarcopenic', 'pregnant_or_breastfeeding', 'hyperkalemia_history'];
  // settings: {lab_rules_enabled, default_activity, fresh_days} (the instance settings of note 05 §4.9).
  function inputsFromRecords(profile, labs, today, { lab_rules_enabled: labRulesEnabled = true, default_activity: defaultActivity = 'inactive', fresh_days: freshDaysSetting = null } = {}) {
    const values = {};
    for (const name of PROFILE_FIELDS) {
      if (has(profile, name) && profile[name] != null) values[name] = BOOL_FIELDS.includes(name) ? Boolean(profile[name]) : profile[name];
    }
    const windows = { ...DEFAULT_FRESH_DAYS, ...(freshDaysSetting || {}) };
    return makeInputs({ ...values, labs: freshLabs(labs, today, windows), lab_rules_enabled: Boolean(labRulesEnabled), default_activity: defaultActivity, fresh_days: windows });
  }
  function suggestFromRecords(profile, labs, today, settings = {}) {
    return suggest(inputsFromRecords(profile, labs, today, settings), today);
  }
  // nutrients.suggest_targets: the v0.2 signature, without the v0.3 inputs -> {targets, notes}.
  function suggestTargets(weightKg, stage, dialysis = 'none', diabetes = 'type1', heightCm = null) {
    const today = new Date().toISOString().slice(0, 10); // no birth month, transplant date or labs: the date does not matter
    const result = suggest(makeInputs({ weight_kg: weightKg, ckd_stage: stage, dialysis, diabetes, height_cm: heightCm }), today);
    return { targets: result.targets, notes: result.notes };
  }
  // nutrients.dosing_weight: [reference weight, basis].
  function dosingWeight(weightKg, heightCm) { const r = referenceWeight(weightKg, heightCm); return [r.weight_kg, r.basis]; }

  // The tables as plain data (compared with tests/data/targets_vectors.json "tables").
  function tables() {
    return {
      rules: RULES, rule_order: RULE_ORDER, notes: NOTES, potassium_note: POTASSIUM_NOTE, refusals: REFUSALS,
      eer_coefficients: EER_COEFFICIENTS, activities: ACTIVITIES, activity_labels: ACTIVITY_LABELS, protein_g_per_kg: PROTEIN_G_PER_KG,
      potassium_ladder: POTASSIUM_LADDER, potassium_relaxed: POTASSIUM_RELAXED, potassium_caps: POTASSIUM_CAPS,
      phosphorus_default: PHOSPHORUS_DEFAULT, calcium_dri: CALCIUM_DRI, fluid_floor_text: FLUID_FLOOR_TEXT, target_labs: TARGET_LABS,
      default_fresh_days: DEFAULT_FRESH_DAYS, missing_input_order: MISSING_INPUT_ORDER,
    };
  }

  KH.targets = {
    RULES, RULE_ORDER, NOTES, REFUSALS, POTASSIUM_NOTE, MODES, ACTIVITIES, ACTIVITY_LABELS, SEXES, TARGET_LABS, DEFAULT_FRESH_DAYS,
    POTASSIUM_VERY_HIGH, MISSING_INPUT_ORDER, PROFILE_FIELDS,
    OutOfScope, InvalidInput, referenceWeight, eerKcal, modeOf, freshLabs, calciumDri, potassiumAlert, potassiumAlertLevel, missingInputs,
    makeInputs, validateInputs, suggest, inputsFromRecords, suggestFromRecords, suggestTargets, dosingWeight, tables, pyFormat, halfUpTo,
  };
})(typeof window !== 'undefined' ? window : globalThis);
