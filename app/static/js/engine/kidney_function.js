/* Kidney Diet Log — lab analytes, unit conversion and kidney function: the browser twin of
   app/units.py (analytes, accepted units, conversion, plausibility, the echo shown before saving)
   and app/kidney_function.py (CKD-EPI 2021/2012 eGFR, G and A categories, age from a birth month,
   and the kidney-function card of GET /api/labs/kidney-function).

   The server is authoritative. This copy powers the "1.94 mmol/L = 6.0 mg/dL" echo while a person
   types a result, and the demo/preview API (js/mock/labs.js). Every number, unit and message here
   is the server's, word for word.

   Parity: tests/data/kidney_function_vectors.json is generated from the Python modules
   (tests/data/gen_kidney_function_vectors.py; pytest checks it is current) and replayed here by
   `node tests/js/run_vectors.mjs`. Change both sides together and regenerate the vectors.

   Plain script: needs js/engine/rules.js first (Python-compatible rounding and formatting); runs in
   the page (window.KH.kidney) and under Node with the same bare-global shim as rules.js. No DOM. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const { halfUp, pyRound, pyG } = KH.rules;

  // ---------------------------------------------------------------------------
  // Python helpers (repr of a str, f"{x:.Nf}", date arithmetic)
  // ---------------------------------------------------------------------------
  // repr() of a str, as an f-string {unit!r} prints it.
  function pyStrRepr(s) {
    s = String(s);
    const q = s.includes("'") && !s.includes('"') ? '"' : "'";
    let body = s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
    if (q === "'") body = body.replace(/'/g, "\\'");
    return q + body + q;
  }
  // f"{x:.Nf}" for a value already rounded to at most N decimals (ties cannot occur): Python's
  // correctly rounded round(x, N), then JavaScript's fixed notation of that double.
  function fixed(x, n) { return pyRound(Number(x), n).toFixed(n); }
  // A YYYY-MM-DD string as a day number (days since 1970-01-01, UTC; no time zone involved).
  function dayNumber(iso) {
    const [y, m, d] = String(iso).split('-').map(Number);
    const t = new Date(Date.UTC(2000, m - 1, d));
    t.setUTCFullYear(y); // Date.UTC maps years 0–99 to 1900–1999
    return Math.round(t.getTime() / 86400000);
  }
  function isoFromDayNumber(n) { return new Date(n * 86400000).toISOString().slice(0, 10); }
  function daysInMonth(y, m) {
    const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
    return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
  }
  // date.fromisoformat for YYYY-MM-DD: the day number, or the ValueError message Python raises.
  function parseIsoDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso));
    if (!m) return { error: `Invalid isoformat string: ${pyStrRepr(iso)}` };
    const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3]);
    if (y < 1) return { error: `year ${y} is out of range` };
    if (mo < 1 || mo > 12) return { error: 'month must be in 1..12' };
    if (d < 1 || d > daysInMonth(y, mo)) return { error: 'day is out of range for month' };
    return { day: dayNumber(iso) };
  }

  // ---------------------------------------------------------------------------
  // Analytes and units (app/units.py)
  // ---------------------------------------------------------------------------
  const ID = { mul: 1, div: 1, add: 0 };
  // key, label, canonical unit, accepted units -> conversion to canonical, plausible range
  // (canonical), freshness window (days), shown decimals, SI default unit.
  const ANALYTE_LIST = [
    { key: 'potassium', label: 'Potassium', canonical_unit: 'mmol/L', units: { 'mmol/L': ID, 'mEq/L': ID }, plausible: [1.5, 9.0], fresh_days: 90, decimals: 1, si_unit: 'mmol/L' },
    { key: 'phosphate', label: 'Phosphate', canonical_unit: 'mg/dL', units: { 'mg/dL': ID, 'mmol/L': { mul: 1, div: 0.3229, add: 0 } }, plausible: [0.5, 20.0], fresh_days: 90, decimals: 1, si_unit: 'mmol/L' },
    { key: 'albumin', label: 'Albumin (blood)', canonical_unit: 'g/dL', units: { 'g/dL': ID, 'g/L': { mul: 0.1, div: 1, add: 0 } }, plausible: [0.5, 6.5], fresh_days: 180, decimals: 1, si_unit: 'g/L' },
    { key: 'bicarbonate', label: 'Bicarbonate (CO2)', canonical_unit: 'mmol/L', units: { 'mmol/L': ID, 'mEq/L': ID }, plausible: [5.0, 50.0], fresh_days: 180, decimals: 1, si_unit: 'mmol/L' },
    { key: 'uacr', label: 'Urine albumin-to-creatinine ratio', canonical_unit: 'mg/g', units: { 'mg/g': ID, 'mg/mmol': { mul: 1, div: 0.113, add: 0 } }, plausible: [0.0, 50000.0], fresh_days: 365, decimals: 1, si_unit: 'mg/mmol' },
    { key: 'creatinine', label: 'Creatinine (blood)', canonical_unit: 'mg/dL', units: { 'mg/dL': ID, 'µmol/L': { mul: 1, div: 88.4, add: 0 } }, plausible: [0.1, 25.0], fresh_days: 365, decimals: 2, si_unit: 'µmol/L' },
    { key: 'cystatin_c', label: 'Cystatin C', canonical_unit: 'mg/L', units: { 'mg/L': ID }, plausible: [0.2, 10.0], fresh_days: 365, decimals: 2, si_unit: 'mg/L' },
    { key: 'egfr', label: 'eGFR (reported by the lab)', canonical_unit: 'mL/min/1.73 m²', units: { 'mL/min/1.73 m²': ID }, plausible: [1.0, 200.0], fresh_days: 365, decimals: 0, si_unit: 'mL/min/1.73 m²' },
    { key: 'a1c', label: 'HbA1c', canonical_unit: '%', units: { '%': ID, 'mmol/mol': { mul: 1, div: 10.929, add: 2.15 } }, plausible: [3.0, 20.0], fresh_days: 365, decimals: 1, si_unit: 'mmol/mol' },
  ];
  const ANALYTES = Object.fromEntries(ANALYTE_LIST.map((a) => [a.key, a]));
  const ANALYTE_KEYS = ANALYTE_LIST.map((a) => a.key);
  const UNIT_SYSTEMS = ['us', 'si'];
  const CONFIGURABLE_FRESHNESS = ['potassium', 'phosphate', 'albumin', 'bicarbonate'];

  class UnitError extends Error {}

  function applyConversion(c, value) {
    let out = Number(value);
    if (c.mul !== 1) out *= c.mul;
    if (c.div !== 1) out /= c.div;
    if (c.add !== 0) out += c.add;
    return out;
  }
  function normaliseUnit(unit) {
    let text = String(unit).trim().replace(/μ/g, 'µ').replace(/ /g, '').toLowerCase(); // Greek mu -> micro sign
    if (text.startsWith('umol') || text.startsWith('mcmol')) text = `µmol${text.slice(text.indexOf('mol') + 3)}`;
    return text.replace(/²/g, '2');
  }
  function analyteDef(analyte) {
    const a = Object.prototype.hasOwnProperty.call(ANALYTES, analyte) ? ANALYTES[analyte] : null;
    if (!a) throw new UnitError(`unknown analyte ${pyStrRepr(analyte)}; use one of: ${ANALYTE_KEYS.join(', ')}`);
    return a;
  }
  // The display spelling of `unit` for `analyte` ("umol/l" -> "µmol/L"); throws UnitError.
  function canonicalUnitName(analyte, unit) {
    const a = analyteDef(analyte);
    const wanted = normaliseUnit(unit);
    for (const name of Object.keys(a.units)) if (normaliseUnit(name) === wanted) return name;
    throw new UnitError(`unit ${pyStrRepr(unit)} is not accepted for ${a.key}; use one of: ${Object.keys(a.units).join(', ')}`);
  }
  function toCanonical(analyte, value, unit) {
    const a = analyteDef(analyte);
    const name = canonicalUnitName(analyte, unit);
    const v = Number(value);
    if (!Number.isFinite(v)) throw new UnitError(`${a.label} must be a finite number`);
    return applyConversion(a.units[name], v);
  }
  // The canonical value rounded half-up to the analyte's shown decimals.
  function displayValue(analyte, value) { return halfUp(Number(value), analyteDef(analyte).decimals); }
  // "6.0", "1.20", "58": the canonical value as the app shows it.
  function formatValue(analyte, value) { return fixed(displayValue(analyte, value), analyteDef(analyte).decimals); }
  function fmtPlain(v) { return Number.isFinite(v) ? pyG(v) : String(v); }
  function pyFloatText(v) { return Number.isNaN(v) ? 'nan' : v > 0 ? 'inf' : '-inf'; }
  function checkPlausible(analyte, canonicalValue, entered = null) {
    const a = analyteDef(analyte);
    const [lo, hi] = a.plausible;
    const v = Number(canonicalValue);
    if (!Number.isFinite(v) || displayValue(analyte, v) < lo || displayValue(analyte, v) > hi) {
      const shown = Number.isFinite(v) ? `${formatValue(analyte, v)} ${a.canonical_unit}` : pyFloatText(v);
      const what = entered ? `${entered} (${shown})` : shown;
      throw new UnitError(`${a.label} ${what} is outside the plausible range ${fmtPlain(lo)}–${fmtPlain(hi)} ${a.canonical_unit}; check the number and the unit`);
    }
  }
  // Validate and convert one entered result (units.convert): {analyte, value (canonical), unit,
  // entered_value, entered_unit (display spelling), display ("1.94 mmol/L = 6.0 mg/dL")}.
  function convert(analyte, value, unit) {
    const a = analyteDef(analyte);
    const enteredUnit = canonicalUnitName(analyte, unit);
    const entered = Number(value);
    if (!Number.isFinite(entered) || entered < 0) throw new UnitError(`${a.label} must be a non-negative number`);
    const canonical = applyConversion(a.units[enteredUnit], entered);
    checkPlausible(analyte, canonical, enteredUnit === a.canonical_unit ? null : `${pyG(entered)} ${enteredUnit}`);
    const shown = `${formatValue(analyte, canonical)} ${a.canonical_unit}`;
    const display = enteredUnit === a.canonical_unit ? shown : `${pyG(entered)} ${enteredUnit} = ${shown}`;
    return { analyte: a.key, value: canonical, unit: a.canonical_unit, entered_value: entered, entered_unit: enteredUnit, display };
  }
  // The unit picker's default for user.units.labs ("us": the canonical unit; "si": SI).
  function defaultUnit(analyte, system = 'us') { const a = analyteDef(analyte); return system === 'si' ? a.si_unit : a.canonical_unit; }
  // Freshness window in days (overrides from the targets.lab_fresh_days.* settings).
  function freshDays(analyte, overrides = null) {
    const a = analyteDef(analyte);
    if (overrides && Object.prototype.hasOwnProperty.call(overrides, analyte) && overrides[analyte] != null) return Math.trunc(Number(overrides[analyte]));
    return a.fresh_days;
  }
  // units.unit_table(): the analyte table as plain data.
  function unitTable() {
    return ANALYTE_LIST.map((a) => ({ key: a.key, label: a.label, canonical_unit: a.canonical_unit,
      units: Object.fromEntries(Object.entries(a.units).map(([n, c]) => [n, { mul: c.mul, div: c.div, add: c.add }])),
      plausible: [...a.plausible], fresh_days: a.fresh_days, decimals: a.decimals, si_unit: a.si_unit }));
  }
  // labs.row_to_lab: the API shape of a stored result (value rounded to the shown decimals).
  function rowToLab(row) {
    const a = analyteDef(row.analyte);
    const enteredValue = Number(row.entered_value);
    const enteredUnit = row.entered_unit;
    const shown = `${formatValue(a.key, row.value)} ${a.canonical_unit}`;
    const display = enteredUnit === a.canonical_unit ? shown : `${pyG(enteredValue)} ${enteredUnit} = ${shown}`;
    return { id: row.id, analyte: a.key, label: a.label, value: displayValue(a.key, row.value), unit: a.canonical_unit,
      entered_value: enteredValue, entered_unit: enteredUnit, display, taken_on: row.taken_on, note: row.note || '', created_at: row.created_at };
  }

  // ---------------------------------------------------------------------------
  // eGFR and categories (app/kidney_function.py)
  // ---------------------------------------------------------------------------
  const SEXES = ['female', 'male', 'unspecified'];
  const KIDNEY_ANALYTES = ['egfr', 'creatinine', 'cystatin_c'];
  const METHOD_LABELS = {
    lab: 'reported by your lab',
    ckd_epi_2021_cr_cys: 'CKD-EPI 2021, creatinine and cystatin C',
    ckd_epi_2021_cr: 'CKD-EPI 2021, creatinine',
    ckd_epi_2012_cys: 'CKD-EPI 2012, cystatin C',
  };
  const METHOD_ORDER = ['lab', 'ckd_epi_2021_cr_cys', 'ckd_epi_2021_cr', 'ckd_epi_2012_cys'];
  const G_CATEGORIES = [[90, 'G1'], [60, 'G2'], [45, 'G3a'], [30, 'G3b'], [15, 'G4'], [0, 'G5']];
  const STAGE_FOR_CATEGORY = { G1: '1', G2: '2', G3a: '3a', G3b: '3b', G4: '4', G5: '5' };
  const ALBUMINURIA_LIMITS = { 'mg/g': [30.0, 300.0], 'mg/mmol': [3.0, 30.0] };
  const ALBUMINURIA_LABELS = { A1: 'normal to mildly increased', A2: 'moderately increased', A3: 'severely increased' };

  // Messages of GET /api/labs/kidney-function (G-1 is note 05 §4.5 word for word).
  const TEXT = {
    G1: 'Your eGFR on {date} is {e} mL/min/1.73 m² ({method}), which is stage {G}{T}{range_note}. Your profile says stage {stage}. '
      + 'One result does not change a stage — kidney disease stages need results over 3 months (KDIGO 2024). Talk to your nephrologist before changing it.',
    RANGE_NOTE: ' (female formula {ef}, male formula {em})',
    SEX_SPLIT: 'Your eGFR on {date} is {lo}–{hi} mL/min/1.73 m² ({method}): the female formula gives {ef} (stage {Gf}{T}) and the male formula {em} '
      + '(stage {Gm}{T}). Because they point to different stages, the app does not suggest one. Choose the sex your lab uses for your eGFR in your profile, '
      + 'or ask your nephrologist. Your profile says stage {stage}.',
    NO_RESULT: 'No creatinine, cystatin C or eGFR result from the last {days} days is saved. Add one from your latest blood test to see which stage it suggests.',
    DIALYSIS: 'Kidney function is not estimated on dialysis: eGFR equations do not apply once dialysis has started. Your profile stage stays as it is.',
    PREGNANCY: 'Kidney function is not estimated during pregnancy or breastfeeding: the eGFR equations were not developed for pregnancy. Ask your kidney team.',
    UNDER_18: 'Kidney function is not estimated for people under 18: children need different eGFR equations (KDIGO 2024). Ask your child\'s kidney team.',
    NEEDS_AGE: 'Add your birth month to estimate kidney function from your {analyte} result: the equations use age. Or add the eGFR your lab reported.',
  };
  // str.format with named fields (values already formatted as text or integers).
  function fmt(template, values) { return template.replace(/\{(\w+)\}/g, (_, k) => String(values[k])); }

  class KidneyFunctionError extends Error {}
  function check(age, sex, levels) {
    if (sex !== 'female' && sex !== 'male') throw new KidneyFunctionError("sex must be 'female' or 'male' (compute both for 'unspecified')");
    if (typeof age !== 'number' || !Number.isInteger(age) || age < 18 || age > 130) throw new KidneyFunctionError('the equations are for adults: age must be a whole number of years from 18');
    for (const [name, value] of levels) if (!Number.isFinite(Number(value)) || Number(value) <= 0) throw new KidneyFunctionError(`${name} must be a positive number`);
  }
  // CKD-EPI 2021 creatinine (mL/min/1.73 m², unrounded).
  function egfrCr(creatinine, age, sex) {
    check(age, sex, [['creatinine', creatinine]]);
    const female = sex === 'female';
    const kappa = female ? 0.7 : 0.9;
    const alpha = female ? -0.241 : -0.302;
    const ratio = Number(creatinine) / kappa;
    const value = 142.0 * Math.min(ratio, 1.0) ** alpha * Math.max(ratio, 1.0) ** -1.200 * 0.9938 ** age;
    return female ? value * 1.012 : value;
  }
  // CKD-EPI 2021 creatinine–cystatin C.
  function egfrCrCys(creatinine, cystatin, age, sex) {
    check(age, sex, [['creatinine', creatinine], ['cystatin_c', cystatin]]);
    const female = sex === 'female';
    const kappa = female ? 0.7 : 0.9;
    const alpha = female ? -0.219 : -0.144;
    const ratio = Number(creatinine) / kappa;
    const cys = Number(cystatin) / 0.8;
    const value = 135.0 * Math.min(ratio, 1.0) ** alpha * Math.max(ratio, 1.0) ** -0.544 * Math.min(cys, 1.0) ** -0.323
      * Math.max(cys, 1.0) ** -0.778 * 0.9961 ** age;
    return female ? value * 0.963 : value;
  }
  // CKD-EPI 2012 cystatin C.
  function egfrCys(cystatin, age, sex) {
    check(age, sex, [['cystatin_c', cystatin]]);
    const cys = Number(cystatin) / 0.8;
    const value = 133.0 * Math.min(cys, 1.0) ** -0.499 * Math.max(cys, 1.0) ** -1.328 * 0.996 ** age;
    return sex === 'female' ? value * 0.932 : value;
  }
  function roundEgfr(value) { return halfUp(Number(value), 0); }
  // "G1" … "G5", judged on the integer the eGFR is shown as (59.5 -> 60 -> G2).
  function gfrCategory(egfr) {
    const shown = roundEgfr(egfr);
    for (const [lower, category] of G_CATEGORIES) if (shown >= lower) return category;
    return 'G5';
  }
  // A1/A2/A3 for a UACR in the unit it was entered in, judged on the shown value (one decimal).
  function albuminuriaCategory(value, unit) {
    const name = canonicalUnitName('uacr', unit);
    const [low, high] = ALBUMINURIA_LIMITS[name];
    const shown = halfUp(Number(value), 1);
    if (!Number.isFinite(shown) || shown < 0) throw new UnitError('uacr must be a non-negative number');
    if (shown < low) return 'A1';
    if (shown > high) return 'A3';
    return 'A2';
  }

  // One stored result as the rules read it (LabRow.from_mapping).
  function labRow(row) {
    const a = analyteDef(String(row.analyte));
    return { id: Math.trunc(Number(row.id || 0)), analyte: String(row.analyte), value: Number(row.value), taken_on: String(row.taken_on),
      entered_value: Number(row.entered_value != null ? row.entered_value : row.value), entered_unit: String(row.entered_unit || a.canonical_unit) };
  }
  // A result counts when it is at most `days` days old (a date after `today` counts as fresh).
  function isFresh(takenOn, today, days) {
    if (days == null) return false;
    return dayNumber(today) - dayNumber(takenOn) <= Math.trunc(Number(days));
  }
  // The newest result: latest taken_on, then the highest id.
  function newest(rows) {
    let best = null;
    for (const r of rows) if (best === null || r.taken_on > best.taken_on || (r.taken_on === best.taken_on && r.id > best.id)) best = r;
    return best;
  }
  // Completed years from the first (or, with lastDay, the last) day of birthMonth to today.
  function ageOn(birthMonth, today, { lastDay = false } = {}) {
    if (!birthMonth) return null;
    const [year, month] = String(birthMonth).split('-').map(Number);
    const bornDay = lastDay ? daysInMonth(year, month) : 1;
    const [ty, tm, td] = String(today).split('-').map(Number);
    return ty - year - ((tm < month || (tm === month && td < bornDay)) ? 1 : 0);
  }

  function compute(method, cr, cys, age, sex) {
    if (method === 'ckd_epi_2021_cr_cys') return egfrCrCys(cr.value, cys.value, age, sex);
    if (method === 'ckd_epi_2021_cr') return egfrCr(cr.value, age, sex);
    return egfrCys(cys.value, age, sex);
  }

  // kidney_function.assess: the card {egfr, albuminuria, profile_stage, mode, message}.
  function assess({ labs, today, ckd_stage: ckdStage, dialysis = 'none', transplant = false, birth_month: birthMonth = null,
    sex = 'unspecified', pregnant_or_breastfeeding: pregnant = false }) {
    if (!SEXES.includes(sex)) throw new KidneyFunctionError(`sex must be one of ${SEXES.join(', ')}`);
    const rows = labs.map(labRow);
    const mode = dialysis === 'hemodialysis' || dialysis === 'peritoneal' ? dialysis : transplant ? 'transplant' : 'ckd';
    const suffix = mode === 'transplant' ? 'T' : '';
    const out = { egfr: null, albuminuria: null, profile_stage: ckdStage, mode, message: '' };

    const uacr = newest(rows.filter((r) => r.analyte === 'uacr' && isFresh(r.taken_on, today, freshDays('uacr'))));
    if (uacr !== null) {
      const category = albuminuriaCategory(uacr.entered_value, uacr.entered_unit);
      out.albuminuria = { value_mg_g: displayValue('uacr', uacr.value), category, label: ALBUMINURIA_LABELS[category],
        entered_value: uacr.entered_value, entered_unit: uacr.entered_unit, taken_on: uacr.taken_on };
    }
    const window = freshDays('creatinine');
    if (mode === 'hemodialysis' || mode === 'peritoneal') { out.message = TEXT.DIALYSIS; return out; }
    if (pregnant) { out.message = TEXT.PREGNANCY; return out; }
    if (birthMonth && (ageOn(birthMonth, today, { lastDay: true }) || 0) < 18) { out.message = TEXT.UNDER_18; return out; }
    const age = ageOn(birthMonth, today);

    const fresh = rows.filter((r) => KIDNEY_ANALYTES.includes(r.analyte) && isFresh(r.taken_on, today, freshDays(r.analyte)));
    if (!fresh.length) { out.message = fmt(TEXT.NO_RESULT, { days: window }); return out; }

    const byDate = new Map();
    for (const r of fresh) {
      if (!byDate.has(r.taken_on)) byDate.set(r.taken_on, {});
      const slot = byDate.get(r.taken_on);
      if (!slot[r.analyte] || r.id > slot[r.analyte].id) slot[r.analyte] = r;
    }
    let chosen = null;
    let needsAge = null;
    for (const day of [...byDate.keys()].sort().reverse()) {
      const slot = byDate.get(day);
      const available = [];
      if (slot.egfr) available.push('lab');
      if (age !== null) {
        if (slot.creatinine && slot.cystatin_c) available.push('ckd_epi_2021_cr_cys');
        if (slot.creatinine) available.push('ckd_epi_2021_cr');
        if (slot.cystatin_c) available.push('ckd_epi_2012_cys');
      } else if (needsAge === null && (slot.creatinine || slot.cystatin_c)) {
        needsAge = slot.creatinine ? 'creatinine' : 'cystatin C';
      }
      if (available.length) {
        const method = available.reduce((a, b) => (METHOD_ORDER.indexOf(b) < METHOD_ORDER.indexOf(a) ? b : a));
        chosen = [day, method, slot];
        break;
      }
    }
    if (chosen === null) { out.message = fmt(TEXT.NEEDS_AGE, { analyte: needsAge || 'creatinine' }); return out; }

    const [day, method, slot] = chosen;
    const label = METHOD_LABELS[method];
    const result = { value: null, method, method_label: label, category: null, suggested_stage: null, matches_profile: null,
      female: null, male: null, taken_on: day };
    out.egfr = result;
    let category;
    if (method === 'lab') {
      result.value = roundEgfr(slot.egfr.value);
      category = gfrCategory(result.value);
    } else if (sex === 'female' || sex === 'male') {
      result.value = roundEgfr(compute(method, slot.creatinine, slot.cystatin_c, age || 0, sex));
      category = gfrCategory(result.value);
    } else {
      const ef = roundEgfr(compute(method, slot.creatinine, slot.cystatin_c, age || 0, 'female'));
      const em = roundEgfr(compute(method, slot.creatinine, slot.cystatin_c, age || 0, 'male'));
      result.female = ef; result.male = em;
      const gf = gfrCategory(ef), gm = gfrCategory(em);
      if (gf !== gm) {
        out.message = fmt(TEXT.SEX_SPLIT, { date: day, lo: Math.min(ef, em), hi: Math.max(ef, em), method: label, ef, em, Gf: gf, Gm: gm, T: suffix, stage: ckdStage });
        return out;
      }
      category = gf;
    }
    const stage = STAGE_FOR_CATEGORY[category];
    result.category = category + suffix;
    result.suggested_stage = stage;
    result.matches_profile = stage === ckdStage;
    let shown, rangeNote;
    if (result.value !== null) { shown = String(result.value); rangeNote = ''; } else {
      const [lo, hi] = [result.female, result.male].sort((a, b) => a - b);
      shown = lo === hi ? String(lo) : `${lo}–${hi}`;
      rangeNote = fmt(TEXT.RANGE_NOTE, { ef: result.female, em: result.male });
    }
    out.message = fmt(TEXT.G1, { date: day, e: shown, method: label, G: category, T: suffix, range_note: rangeNote, stage: ckdStage });
    return out;
  }

  KH.kidney = {
    // units
    ANALYTES, ANALYTE_KEYS, ANALYTE_LIST, UNIT_SYSTEMS, CONFIGURABLE_FRESHNESS, UnitError, analyteDef, canonicalUnitName, normaliseUnit,
    toCanonical, displayValue, formatValue, checkPlausible, convert, defaultUnit, freshDays, unitTable, rowToLab,
    // kidney function
    SEXES, KIDNEY_ANALYTES, METHOD_LABELS, METHOD_ORDER, G_CATEGORIES, STAGE_FOR_CATEGORY, ALBUMINURIA_LIMITS, ALBUMINURIA_LABELS, TEXT,
    KidneyFunctionError, egfrCr, egfrCrCys, egfrCys, roundEgfr, gfrCategory, albuminuriaCategory, labRow, isFresh, newest, ageOn, assess,
    // helpers shared with js/engine/targets.js
    pyStrRepr, fixed, dayNumber, isoFromDayNumber, parseIsoDate, fmt,
  };
})(typeof window !== 'undefined' ? window : globalThis);
