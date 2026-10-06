/* Kidney Diet Log — rules engine: the browser twin of app/nutrients.py (nutrient registry,
   per-serving warnings, kidney ratings, Python-compatible rounding and number formatting,
   daily status and alerts). The server is authoritative; this copy powers live previews,
   the demo/preview API (js/mock/*) and, later, offline estimates.

   Parity: tests/data/rules_vectors.json is generated from the Python functions
   (tests/data/gen_rules_vectors.py) and checked here by `node tests/js/run_vectors.mjs`.
   Change both sides together and regenerate the vectors.

   Plain script, no imports: in the page it sets window.KH.rules; under Node the test runner
   evaluates it with a bare global object, which `root` falls back to (the "tiny shim"). It
   must not touch the DOM. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});

  // ---------------------------------------------------------------------------
  // Registry (mirrors app/nutrients.py; keys are the contract)
  // ---------------------------------------------------------------------------
  const NUTRIENTS = [
    { key: 'calories_kcal', label: 'Calories', short: 'kcal', unit: 'kcal', role: 'goal' },
    { key: 'protein_g', label: 'Protein', short: 'Protein', unit: 'g', role: 'range' },
    { key: 'fat_g', label: 'Fat', short: 'Fat', unit: 'g', role: 'info' },
    { key: 'sat_fat_g', label: 'Saturated fat', short: 'Sat fat', unit: 'g', role: 'info' },
    { key: 'carbs_g', label: 'Carbohydrate', short: 'Carbs', unit: 'g', role: 'track' },
    { key: 'fiber_g', label: 'Fiber', short: 'Fiber', unit: 'g', role: 'info' },
    { key: 'sugar_g', label: 'Sugars', short: 'Sugars', unit: 'g', role: 'info' },
    { key: 'sodium_mg', label: 'Sodium', short: 'Na', unit: 'mg', role: 'limit' },
    { key: 'potassium_mg', label: 'Potassium', short: 'K', unit: 'mg', role: 'limit' },
    { key: 'phosphorus_mg', label: 'Phosphorus', short: 'P', unit: 'mg', role: 'limit' },
    { key: 'calcium_mg', label: 'Calcium', short: 'Ca', unit: 'mg', role: 'info' },
    { key: 'fluid_ml', label: 'Fluid', short: 'Fluid', unit: 'mL', role: 'limit' },
  ];
  const NUT = Object.fromEntries(NUTRIENTS.map((n) => [n.key, n]));
  const NUTRIENT_KEYS = NUTRIENTS.map((n) => n.key);
  const TARGET_KEYS = [...NUTRIENT_KEYS, 'carbs_per_meal_g', 'carbs_per_snack_g']; // twin of nutrients.TARGET_KEYS
  const MEALS = [
    { key: 'breakfast', label: 'Breakfast' },
    { key: 'lunch', label: 'Lunch' },
    { key: 'dinner', label: 'Dinner' },
    { key: 'snack', label: 'Snack' },
  ];
  const MEAL_KEYS = MEALS.map((m) => m.key);
  const MEAL_LABEL = Object.fromEntries(MEALS.map((m) => [m.key, m.label]));
  const CKD_STAGES = ['1', '2', '3a', '3b', '4', '5'];
  const DIALYSIS_MODES = ['none', 'hemodialysis', 'peritoneal'];
  const DIABETES_TYPES = ['none', 'type1', 'type2'];
  const FLAGS = [
    { key: 'phosphate_additive', label: 'Phosphate additives', hint: 'Ingredient list has "phos" (e.g. sodium phosphate); nearly fully absorbed', kind: 'warn' },
    { key: 'potassium_additive', label: 'Potassium additives', hint: 'Ingredient list has a potassium salt (e.g. potassium chloride, potassium lactate); about 90 % absorbed', kind: 'warn' },
    { key: 'high_gi', label: 'High glycemic index', hint: 'Raises blood glucose quickly', kind: 'warn' },
    { key: 'counts_as_fluid', label: 'Counts as fluid', hint: 'Liquid at room temperature', kind: '' },
    { key: 'avoid_ckd', label: 'Avoid with CKD', hint: 'e.g. star fruit', kind: 'warn' },
    { key: 'hypo_treatment', label: 'Hypo treatment', hint: 'Fast carbs, low potassium', kind: 'good' },
    { key: 'low_potassium_fruit', label: 'Low-potassium fruit', hint: '', kind: 'good' },
    { key: 'processed', label: 'Processed', hint: 'Usually higher sodium / additives', kind: '' },
    { key: 'ingredient', label: 'Ingredient', hint: 'Only added to other food (flour, oil); never suggested on its own', kind: '' },
  ];
  const FLAG = Object.fromEntries(FLAGS.map((f) => [f.key, f]));
  // How each nutrient is judged over a period (mirrors app/periods.py; the server's value wins when present).
  const ASSESSMENT = { potassium_mg: 'daily', sodium_mg: 'daily', fluid_ml: 'daily', carbs_g: 'daily',
    phosphorus_mg: 'weekly_average', protein_g: 'weekly_average', calories_kcal: 'weekly_average', calcium_mg: 'weekly_average' };
  const ROLE_WORD = { limit: 'limit', range: 'maximum', info: 'maximum', goal: 'goal', track: 'goal' };

  // Per-serving thresholds and the order warnings are reported in (mirror app/nutrients.py
  // THRESHOLDS / WARNING_ORDER: renal priorities first, then protein, then carbohydrate).
  const THRESHOLDS = {
    potassium_mg: { medium: 101, high: 200 },
    phosphorus_mg: { medium: 101, high: 150 },
    sodium_mg: { medium: 141, high: 400 },
    carbs_g: { medium: 15, high: 30 },
    protein_g: { medium: 15, high: 25 },
  };
  const WARNING_ORDER = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'carbs_g'];
  const HIGH_GI_MIN_CARBS_G = 15; // high_gi upgrades carbohydrate to "high" only from one carb choice
  // ARCHITECTURE.md v0.3 item 9 (mirror of nutrients.POTASSIUM_ADDITIVE_MESSAGE): medium when potassium is unknown.
  const POTASSIUM_ADDITIVE_MESSAGE = 'Contains a potassium additive; potassium not listed';

  // ---------------------------------------------------------------------------
  // Display formatting (what the UI prints; the server already rounded its numbers)
  // ---------------------------------------------------------------------------
  function isInt(key) { const u = NUT[key] && NUT[key].unit; return u === 'mg' || u === 'kcal' || u === 'mL'; }
  function roundVal(v, key) { return isInt(key) ? Math.round(v) : Math.round(v * 10) / 10; }
  function fmtNum(v, key) {
    if (v == null || Number.isNaN(Number(v))) return '–';
    const r = roundVal(Number(v), key);
    return r.toLocaleString('en-US', { maximumFractionDigits: isInt(key) ? 0 : 1 });
  }
  function fmtWithUnit(v, key) { return `${fmtNum(v, key)} ${NUT[key].unit}`; }
  function fmtServings(n) {
    const r = Math.round(n * 100) / 100;
    return `${r.toLocaleString('en-US', { maximumFractionDigits: 2 })} ${r === 1 ? 'serving' : 'servings'}`;
  }
  function pct(fraction) { return Math.round((fraction || 0) * 100); }

  // ---------------------------------------------------------------------------
  // Python-compatible numbers. The server (app/*.py) rounds with Decimal half-up on the
  // shortest repr (round_value), with Python's round() (correctly rounded, ties to even) and
  // prints with format(x, 'g') / repr(x); these copies make the client print the same text.
  // ---------------------------------------------------------------------------
  // Python round(x, nd) on a float.
  function pyRound(x, nd = 0) {
    x = Number(x);
    if (!Number.isFinite(x) || x === 0) return x;
    if (nd === 0) {
      const f = Math.floor(x);
      if (x - f === 0.5) return f % 2 === 0 ? f : f + 1; // exact tie: to even
      return Math.round(x);
    }
    const p = 10 ** nd;
    const y = x * p;
    const f = Math.floor(y), d = y - f;
    // Far from a tie the scaled product decides; near one, look at the exact binary value.
    if (Math.abs(y) < 1e12 && Math.abs(d - 0.5) > 1e-9 * Math.max(1, Math.abs(y))) return (d < 0.5 ? f : f + 1) / p;
    const ax = Math.abs(x);
    if (ax >= 1e21) return x;
    const s = ax.toFixed(100); // exact decimal expansion of the double
    const dot = s.indexOf('.');
    const keep = s.slice(0, dot) + s.slice(dot + 1, dot + 1 + nd);
    const rest = s.slice(dot + 1 + nd);
    let k = BigInt(keep);
    const first = rest.charCodeAt(0) - 48;
    if (first > 5 || (first === 5 && (/[1-9]/.test(rest.slice(1)) || k % 2n === 1n))) k += 1n;
    const r = Number(`${k}e-${nd}`);
    return x < 0 ? -r : r;
  }
  // nutrients._half_up: Decimal(repr(x)).quantize(10**-places, ROUND_HALF_UP).
  function halfUp(x, places) {
    x = Number(x);
    if (!Number.isFinite(x)) return x;
    let s = String(Math.abs(x)); // the shortest round-trip digits, as Python's repr
    let exp = 0;
    const ei = s.indexOf('e');
    if (ei >= 0) { exp = Number(s.slice(ei + 1)); s = s.slice(0, ei); }
    const di = s.indexOf('.');
    const digits = di >= 0 ? s.slice(0, di) + s.slice(di + 1) : s;
    if (di >= 0) exp -= s.length - di - 1; // |x| = digits × 10^exp
    const drop = -places - exp;
    if (drop <= 0) return x;
    let keep = 0n, first = 0;
    if (drop <= digits.length) {
      keep = BigInt(digits.slice(0, digits.length - drop) || '0');
      first = digits.charCodeAt(digits.length - drop) - 48;
    }
    if (first >= 5) keep += 1n;
    const r = Number(`${keep}e-${places}`);
    return x < 0 ? -r : r;
  }
  const INT_UNITS = new Set(['mg', 'mL']);
  function isIntUnit(key) { const n = NUT[key]; return !!n && INT_UNITS.has(n.unit); }
  // nutrients.round_value: mg and mL to integers, everything else (kcal included) to 1 decimal. The integer
  // branch is Python's int(), which has no negative zero (-0.3 mg is 0, while -0.04 g stays -0.0).
  function roundValue(key, v) {
    if (v == null) return null;
    v = Number(v);
    if (!Number.isFinite(v)) return null;
    return isIntUnit(key) ? halfUp(v, 0) + 0 : halfUp(v, 1);
  }
  function roundNutrients(values) {
    const out = {};
    for (const key of NUTRIENT_KEYS) out[key] = roundValue(key, values ? values[key] : null);
    return out;
  }
  // Exact decimal digits of |x| (x finite, 0 < |x| < 1e21): [digits, scientific exponent].
  function exactDigits(ax) {
    const s = ax.toFixed(100);
    const dot = s.indexOf('.');
    const all = s.slice(0, dot) + s.slice(dot + 1);
    const i0 = all.search(/[1-9]/);
    return [all.slice(i0).replace(/0+$/, '') || '0', dot - 1 - i0];
  }
  // format(x, 'g'): 6 significant digits (ties to even), trailing zeros dropped.
  function pyG(x) {
    x = Number(x);
    if (Number.isNaN(x)) return 'nan';
    if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
    if (x === 0) return Object.is(x, -0) ? '-0' : '0';
    const ax = Math.abs(x);
    let sig, e;
    if (ax < 1e21) {
      const [digits, e0] = exactDigits(ax);
      e = e0;
      let k = BigInt(digits.slice(0, 6).padEnd(6, '0'));
      const rest = digits.slice(6);
      const first = rest ? rest.charCodeAt(0) - 48 : 0;
      if (first > 5 || (first === 5 && (/[1-9]/.test(rest.slice(1)) || k % 2n === 1n))) k += 1n;
      if (k === 1000000n) { k = 100000n; e += 1; }
      sig = String(k);
    } else {
      const [m, ex] = ax.toExponential(5).split('e');
      sig = m.replace('.', ''); e = Number(ex);
    }
    let out;
    if (e < -4 || e >= 6) {
      const frac = sig.slice(1).replace(/0+$/, '');
      out = `${sig[0]}${frac ? `.${frac}` : ''}e${e < 0 ? '-' : '+'}${String(Math.abs(e)).padStart(2, '0')}`;
    } else if (e >= 0) {
      const frac = sig.slice(e + 1).replace(/0+$/, '');
      out = sig.slice(0, e + 1) + (frac ? `.${frac}` : '');
    } else {
      out = `0.${'0'.repeat(-e - 1)}${sig.replace(/0+$/, '')}`;
    }
    return (x < 0 ? '-' : '') + out;
  }
  // repr(float): shortest round-trip digits, exponent form below 1e-4 and from 1e16.
  function pyRepr(x) {
    x = Number(x);
    if (Number.isNaN(x)) return 'nan';
    if (!Number.isFinite(x)) return x > 0 ? 'inf' : '-inf';
    if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
    const [m, ex] = Math.abs(x).toExponential().split('e');
    const e = Number(ex);
    const digits = m.replace('.', '');
    let out;
    if (e < -4 || e >= 16) out = `${digits[0]}${digits.length > 1 ? `.${digits.slice(1)}` : ''}e${e < 0 ? '-' : '+'}${String(Math.abs(e)).padStart(2, '0')}`;
    else if (e >= 0) out = `${digits.slice(0, e + 1).padEnd(e + 1, '0')}.${digits.slice(e + 1) || '0'}`;
    else out = `0.${'0'.repeat(-e - 1)}${digits}`;
    return (x < 0 ? '-' : '') + out;
  }
  // nutrients._fmt: "2125", "40", "40.5" ("?" when unknown).
  function pyFmt(key, value) {
    if (value == null) return '?';
    const r = roundValue(key, value);
    return isIntUnit(key) ? String(r) : pyG(r);
  }
  // math.fsum (the server's period sums): Shewchuk partials, then CPython's correctly rounded
  // (half-even) collapse. Values are finite here (non-finite day totals count as 0).
  function pyFsum(values) {
    const partials = [];
    for (const v of values) {
      let x = Number(v);
      let i = 0;
      for (let j = 0; j < partials.length; j++) {
        let y = partials[j];
        if (Math.abs(x) < Math.abs(y)) [x, y] = [y, x];
        const hi = x + y;
        const lo = y - (hi - x);
        if (lo) partials[i++] = lo;
        x = hi;
      }
      partials.length = i;
      partials.push(x);
    }
    let n = partials.length;
    if (!n) return 0;
    let hi = partials[--n], lo = 0;
    while (n > 0) {
      const x = hi, y = partials[--n];
      hi = x + y;
      lo = y - (hi - x);
      if (lo) break;
    }
    if (n > 0 && ((lo < 0 && partials[n - 1] < 0) || (lo > 0 && partials[n - 1] > 0))) {
      const y = lo * 2, x = hi + y;
      if (y === x - hi) hi = x;
    }
    return hi;
  }
  // SQLite SUM() over REAL values (3.43+: Kahan-Babuska-Neumaier); null when every value is NULL.
  function sqliteSum(values) {
    let s = 0, err = 0, n = 0;
    for (const v of values) {
      if (v == null) continue;
      const x = Number(v);
      n += 1;
      const t = s + x;
      if (Math.abs(s) > Math.abs(x)) err += (s - t) + x; else err += (x - t) + s;
      s = t;
    }
    if (!n) return null;
    return Number.isFinite(err) ? s + err : s;
  }

  // ---------------------------------------------------------------------------
  // Warnings evaluator: a copy of app/nutrients.py food_warnings (the server is authoritative).
  // Used for live previews in the app and by the demo API. `scope` is "per serving",
  // "in this entry" or "in this meal" (true / false are accepted for the first two).
  // ---------------------------------------------------------------------------
  function thresholdLevel(key, value) {
    const th = THRESHOLDS[key];
    if (!th || value == null) return null;
    const shown = roundValue(key, value);
    if (shown == null) return null;
    if (shown > th.high) return 'high';
    if (shown >= th.medium) return 'medium';
    return null;
  }
  function carbChoicesText(grams) {
    const choices = Math.max(1, pyRound(grams / 15));
    return `${choices} carb choice${choices === 1 ? '' : 's'}`;
  }
  function warningMessage(key, level, value, flag, scope) {
    const label = NUT[key].label.toLowerCase();
    const amount = value != null ? `${pyFmt(key, value)} ${NUT[key].unit}` : null;
    if (flag === 'phosphate_additive') {
      const base = 'Contains phosphate additives (almost fully absorbed)';
      return amount ? `${base}: ${amount} phosphorus ${scope}` : base;
    }
    if (flag === 'high_gi') return `High glycaemic index: ${amount} fast-acting carbohydrate ${scope}`;
    if (flag === 'potassium_additive') return POTASSIUM_ADDITIVE_MESSAGE;
    if (key === 'carbs_g') {
      if (level === 'high') return `High carbohydrate: ${amount} ${scope} (${carbChoicesText(value || 0)})`;
      return `${carbChoicesText(value || 0)}: ${amount} carbohydrate ${scope}`;
    }
    if (key === 'protein_g' && level === 'high') return `Large protein portion: ${amount} ${scope}`;
    return `${level === 'high' ? 'High' : 'Moderate'} ${label}: ${amount} ${scope}`;
  }
  function evaluateWarnings(nutrients, flags = [], kidneyNotes = '', scope = 'per serving') {
    if (scope === true) scope = 'per serving';
    else if (scope === false) scope = 'in this entry';
    const fl = new Set(flags || []);
    const hypo = fl.has('hypo_treatment'); // fast carbohydrate is the point of treating a low
    const out = [];
    if (fl.has('avoid_ckd')) {
      out.push({ nutrient: 'avoid_ckd', level: 'high', value: null, flag: 'avoid_ckd',
        message: String(kidneyNotes || '').trim() || 'Not recommended for people with kidney disease' });
    }
    for (const key of WARNING_ORDER) {
      if (key === 'carbs_g' && hypo) continue;
      const raw = nutrients ? nutrients[key] : null;
      const value = raw == null ? null : Number(raw);
      let level = thresholdLevel(key, value);
      let flag = null;
      if (key === 'phosphorus_mg' && fl.has('phosphate_additive')) { level = 'high'; flag = 'phosphate_additive'; }
      else if (key === 'potassium_mg' && fl.has('potassium_additive') && roundValue(key, value) == null) {
        level = 'medium'; flag = 'potassium_additive'; // potassium not listed: medium; listed: normal thresholds
      }
      else if (key === 'carbs_g' && fl.has('high_gi') && (value || 0) > 0) {
        // Glycaemic index matters once there is a carb choice to spike on (glycaemic load).
        level = (roundValue(key, value) || 0) >= HIGH_GI_MIN_CARBS_G ? 'high' : 'medium';
        flag = 'high_gi';
      }
      if (level == null) continue;
      out.push({ nutrient: key, level, value: roundValue(key, value), flag, message: warningMessage(key, level, value, flag, scope) });
    }
    out.sort((a, b) => (a.level === 'high' ? 0 : 1) - (b.level === 'high' ? 0 : 1)); // stable: avoid_ckd stays first
    return out;
  }
  function ratingFromWarnings(warnings) {
    if (warnings.some((w) => w.level === 'high')) return 'red';
    if (warnings.some((w) => w.level === 'medium')) return 'yellow';
    return 'green';
  }

  // ---------------------------------------------------------------------------
  // Totals, daily status and alerts (nutrients.py)
  // ---------------------------------------------------------------------------
  function emptyTotals() { return Object.fromEntries(NUTRIENT_KEYS.map((k) => [k, 0])); }
  function addTotals(acc, values) {
    for (const key of NUTRIENT_KEYS) {
      const v = values ? values[key] : null;
      if (v != null) acc[key] = (acc[key] || 0) + Number(v);
    }
    return acc;
  }
  function scaleNutrients(values, factor) {
    return Object.fromEntries(NUTRIENT_KEYS.map((k) => [k, values[k] == null ? null : Number(values[k]) * factor]));
  }
  function targetBounds(t) {
    if (t == null) return [null, null];
    if (typeof t === 'object') return [t.min == null ? null : Number(t.min), t.max == null ? null : Number(t.max)];
    return [null, Number(t)];
  }
  function statusLevel(fraction, wf) {
    if (fraction == null || Number.isNaN(fraction)) return 'ok';
    if (fraction > 1) return 'over';
    if (fraction >= wf) return 'caution';
    return 'ok';
  }
  function dailyStatus(totals, targets, wf) {
    const status = {};
    for (const key of NUTRIENT_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(targets, key)) continue;
      let [lo, hi] = targetBounds(targets[key]);
      if (lo != null && !Number.isFinite(lo)) lo = null;
      if (hi != null && !Number.isFinite(hi)) hi = null;
      if (lo == null && hi == null) continue;
      const value = Number(totals[key] || 0);
      let fraction = hi ? value / hi : null;
      const level = statusLevel(fraction, wf); // judged on the raw fraction
      if (fraction != null && !Number.isFinite(fraction)) fraction = null;
      status[key] = { value: roundValue(key, value), target: hi ? roundValue(key, hi) : null, min: lo != null ? roundValue(key, lo) : null,
        fraction: fraction == null ? null : pyRound(fraction, 2), level };
    }
    return status;
  }
  function finiteFraction(item) {
    const f = item.fraction;
    return f == null || !Number.isFinite(Number(f)) ? null : Number(f);
  }
  function buildAlerts(status, projected = false) {
    const alerts = [];
    for (const [key, item] of Object.entries(status)) {
      const fraction = finiteFraction(item);
      if ((item.level !== 'caution' && item.level !== 'over') || fraction == null) continue;
      const n = NUT[key];
      const p = pyRound(fraction * 100);
      const word = ROLE_WORD[n.role] || 'goal';
      const value = pyFmt(key, item.value), target = pyFmt(key, item.target);
      let message;
      if (projected) message = `If you eat what's planned, ${n.label.toLowerCase()} reaches ${p} % of today's ${word} (${value} / ${target} ${n.unit})`;
      else if (item.level === 'caution') message = `${n.label} is at ${p} % of today's ${word} (${value} / ${target} ${n.unit})`;
      else message = `${n.label} is over today's ${word}: ${value} / ${target} ${n.unit} (${p} %)`;
      alerts.push({ level: item.level, nutrient: key, meal: null, message });
    }
    alerts.sort((a, b) => (a.level === 'over' ? 0 : 1) - (b.level === 'over' ? 0 : 1));
    return alerts;
  }
  function mealCarbAlerts(meals, perMealTarget, projected = false) {
    const [, hi] = targetBounds(perMealTarget);
    if (!hi) return [];
    const alerts = [];
    for (const meal of MEAL_KEYS) {
      const carbs = Number((meals[meal] || {}).carbs_g || 0);
      if (carbs > hi) {
        alerts.push({ level: 'over', nutrient: 'carbs_g', meal, message: projected
          ? `If you eat what's planned, ${meal} carbohydrate reaches ${pyFmt('carbs_g', carbs)} / ${pyFmt('carbs_g', hi)} g (over the per-meal goal)`
          : `${meal.charAt(0).toUpperCase()}${meal.slice(1)} carbohydrate is over the per-meal goal: ${pyFmt('carbs_g', carbs)} / ${pyFmt('carbs_g', hi)} g` });
      }
    }
    return alerts;
  }
  function summaryTarget(t) {
    const [, hi] = targetBounds(t);
    return hi != null && Number.isFinite(hi) && hi > 0 ? hi : null;
  }

  KH.rules = {
    // registry
    NUTRIENTS, NUT, NUTRIENT_KEYS, TARGET_KEYS, MEALS, MEAL_KEYS, MEAL_LABEL, CKD_STAGES, DIALYSIS_MODES, DIABETES_TYPES,
    FLAGS, FLAG, ASSESSMENT, ROLE_WORD, THRESHOLDS, WARNING_ORDER, HIGH_GI_MIN_CARBS_G, POTASSIUM_ADDITIVE_MESSAGE,
    // display formatting
    isInt, roundVal, fmtNum, fmtWithUnit, fmtServings, pct,
    // Python-compatible numbers
    pyRound, halfUp, isIntUnit, roundValue, roundNutrients, pyG, pyRepr, pyFmt, pyFsum, sqliteSum,
    // warnings and ratings
    thresholdLevel, carbChoicesText, warningMessage, evaluateWarnings, ratingFromWarnings,
    // totals, daily status, alerts
    emptyTotals, addTotals, scaleNutrients, targetBounds, statusLevel, dailyStatus, finiteFraction, buildAlerts, mealCarbAlerts, summaryTarget,
  };
})(typeof window !== 'undefined' ? window : globalThis);
