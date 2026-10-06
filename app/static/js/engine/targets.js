/* Kidney Diet Log — suggested targets: the browser twin of app/nutrients.py dosing_weight and
   suggest_targets (numbers and notes word for word). Used by the demo/preview API
   (js/mock/profile.js); the installed app always asks the server. Personalised targets
   (age, sex, labs, eGFR) extend this file in M2 together with js/engine/kidney_function.js.

   Plain script: needs js/engine/rules.js first; runs in the page (window.KH.targets) and
   under Node with the same bare-global shim as rules.js. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const { CKD_STAGES, DIALYSIS_MODES, DIABETES_TYPES, halfUp, pyRound, pyG, pyRepr } = KH.rules;

  const POTASSIUM_NOTE = 'Only restrict potassium if your blood potassium is high; your care team sets the number.';

  // nutrients.dosing_weight: ideal body weight at the edge of the healthy BMI band (18.5–25).
  function dosingWeight(weightKg, heightCm) {
    const w = Number(weightKg);
    if (heightCm == null || !Number.isFinite(Number(heightCm)) || Number(heightCm) <= 0) return [w, 'actual'];
    const hm = Number(heightCm) / 100;
    const bmi = w / (hm * hm);
    const eps = 1e-9;
    if (bmi > 25 + eps) return [halfUp(25 * hm * hm, 1), 'ideal_bmi_25'];
    if (bmi < 18.5 - eps) return [halfUp(18.5 * hm * hm, 1), 'ideal_bmi_18.5'];
    return [w, 'actual'];
  }
  // nutrients.suggest_targets, notes word for word.
  function suggestTargets(weightKg, stage, dialysis = 'none', diabetes = 'type1', heightCm = null) {
    if (weightKg == null || !Number.isFinite(Number(weightKg)) || Number(weightKg) <= 0) throw new Error('weight_kg must be a positive number');
    if (heightCm != null && (!Number.isFinite(Number(heightCm)) || Number(heightCm) <= 0)) throw new Error('height_cm must be a positive number');
    if (!CKD_STAGES.includes(stage)) throw new Error(`ckd_stage must be one of ${CKD_STAGES.join(', ')}`);
    if (!DIALYSIS_MODES.includes(dialysis)) throw new Error(`dialysis must be one of ${DIALYSIS_MODES.join(', ')}`);
    if (!DIABETES_TYPES.includes(diabetes)) throw new Error(`diabetes must be one of ${DIABETES_TYPES.join(', ')}`);
    const actual = Number(weightKg);
    const [w, basis] = dosingWeight(actual, heightCm);
    const onDialysis = dialysis !== 'none';
    const notes = [];
    if (basis === 'actual' && heightCm == null) {
      notes.push(`Weight basis: guidelines give calories and protein per kg of ideal body weight; without a saved height the actual weight (${pyG(actual)} kg) is used. Add your height if you are over- or under-weight.`);
    } else if (basis === 'actual') {
      notes.push(`Weight basis: ${pyG(actual)} kg is within the healthy BMI range for ${pyG(Number(heightCm))} cm, so it is used as the ideal body weight.`);
    } else {
      notes.push(`Weight basis: calories and protein are per kg of ideal body weight; for ${pyG(Number(heightCm))} cm that is taken as ${pyG(w)} kg (BMI ${basis === 'ideal_bmi_25' ? '25' : '18.5'}), not the actual ${pyG(actual)} kg (KDOQI 2020).`);
    }
    const calories = pyRound(30 * w);
    notes.push(`Calories: 30 kcal/kg × ${pyG(w)} kg ideal body weight = ${calories} kcal (KDOQI 2020 3.0.1 range 25–35 kcal/kg).`);
    let pMin, pMax;
    if (onDialysis) {
      [pMin, pMax] = [1.0, 1.2];
      notes.push(`Protein: ${pyRepr(pMin)}–${pyRepr(pMax)} g/kg ideal body weight for ${dialysis} (KDOQI 2020 3.1.2/3.1.4); losses during dialysis mean more protein is needed, not less.`);
    } else if (stage === '1' || stage === '2') {
      [pMin, pMax] = [0.8, 1.0];
      notes.push(`Protein: ${pyRepr(pMin)}–${pyRepr(pMax)} g/kg ideal body weight for CKD stage ${stage}; guidelines only ask to avoid high intakes (> 1.3 g/kg) this early.`);
    } else {
      [pMin, pMax] = [0.6, 0.8];
      const source = diabetes !== 'none' ? 'non-dialysis CKD 3–5 with diabetes (KDOQI 2020 3.1.3)'
        : 'non-dialysis CKD 3–5 (KDOQI 2020 3.1.1 gives 0.55–0.6; KDIGO 2024 3.3.1.1 gives 0.8)';
      notes.push(`Protein: ${pyRepr(pMin)}–${pyRepr(pMax)} g/kg ideal body weight for ${source}; below 0.6 risks wasting and hypoglycaemia; guidelines recommend 0.8 and advise avoiding more than 1.3 g/kg (KDIGO 2024).`);
    }
    const protein = { min: pyRound(pMin * w), max: pyRound(pMax * w) };
    const K_MG = { hemodialysis: 2500, peritoneal: 3500, 1: 4000, 2: 4000, '3a': 4000, '3b': 3500, 4: 3000, 5: 2500 };
    let potassium;
    if (onDialysis) {
      potassium = K_MG[dialysis];
      notes.push(`Potassium: ${potassium} mg/day is a common ${dialysis} starting point. ${POTASSIUM_NOTE}`);
    } else {
      potassium = K_MG[stage];
      if (stage === '1' || stage === '2') notes.push(`Potassium: ${potassium} mg/day is informational only; stages 1–2 usually need no restriction. ${POTASSIUM_NOTE}`);
      else notes.push(`Potassium: ${potassium} mg/day is the starting point for stage ${stage}; medicines (ACE inhibitors, ARBs, potassium binders) change it. ${POTASSIUM_NOTE}`);
    }
    const phosphorus = onDialysis ? 1000 : stage === '5' ? 900 : 1000;
    notes.push(`Phosphorus: ${phosphorus} mg/day (guideline range 800–1000 mg); avoiding phosphate additives matters more than the total because additive phosphorus is almost fully absorbed.`);
    notes.push('Sodium: 2000 mg/day (KDIGO < 2000 mg, KDOQI < 2300 mg).');
    const fluid = { none: null, hemodialysis: 1500, peritoneal: 2000 }[dialysis];
    if (dialysis === 'hemodialysis') notes.push('Fluid: 1000 mL plus your 24-hour urine volume; 1500 mL assumes about 500 mL of urine. Ask your dialysis unit for your personal allowance.');
    else if (dialysis === 'peritoneal') notes.push('Fluid: about 2000 mL/day on peritoneal dialysis, individualised to residual kidney function. Also subtract the glucose absorbed from dialysate (often 400+ kcal/day) from the calorie goal.');
    else notes.push('Fluid: no routine limit without dialysis (left untracked) unless your care team sets one.');
    const carbs = pyRound((calories * 0.45) / 4);
    const carbsPerMeal = Math.max(15, pyRound(carbs / 4 / 5) * 5);
    if (diabetes === 'none') notes.push(`Carbohydrate: 45 % of calories ÷ 4 kcal/g = ${carbs} g/day.`);
    else notes.push(`Carbohydrate: 45 % of calories ÷ 4 kcal/g = ${carbs} g/day, about ${carbsPerMeal} g per meal for carb counting; your insulin-to-carb ratio decides the real per-meal number.`);
    notes.push('Calcium: 1000 mg/day total including calcium-based phosphate binders.');
    notes.push('These are starting points only — confirm every target with your nephrologist and renal dietitian.');
    const targets = { calories_kcal: calories, protein_g: protein, carbs_g: carbs, carbs_per_meal_g: carbsPerMeal, sodium_mg: 2000,
      potassium_mg: potassium, phosphorus_mg: phosphorus, calcium_mg: 1000, fluid_ml: fluid };
    return { targets, notes };
  }

  KH.targets = { POTASSIUM_NOTE, dosingWeight, suggestTargets };
})(typeof window !== 'undefined' ? window : globalThis);
