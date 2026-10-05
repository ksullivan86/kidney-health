/* Kidney Diet Log — single-page UI. Vanilla ES2020, no dependencies.
   Talks only to same-origin /api/... (see ARCHITECTURE.md). Append ?mock=1 to the URL to run
   against the in-page demo API (no backend needed); scripts/build_preview.py builds a
   self-contained preview page that sets window.KDL_PREVIEW and embeds data/foods.json. */
(() => {
  'use strict';

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
  const KEY_NUMBERS = ['carbs_g', 'protein_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg'];
  const ROW_NUMBERS = ['carbs_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg'];
  const STATUS_ORDER = ['carbs_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'fluid_ml', 'calories_kcal', 'calcium_mg'];
  const TREND_ORDER = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'carbs_g', 'fluid_ml', 'calories_kcal', 'calcium_mg'];
  const PLAN_CHIPS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'carbs_g', 'fluid_ml'];
  const STRIP_KEYS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g'];
  const INTERDIALYTIC_KEYS = ['potassium_mg', 'sodium_mg', 'fluid_ml'];
  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']; // 0 = Monday, as in the contract
  const WEEKDAYS_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  // How each nutrient is judged over a period (mirrors app/periods.py; the server's value wins when present).
  const ASSESSMENT = { potassium_mg: 'daily', sodium_mg: 'daily', fluid_ml: 'daily', carbs_g: 'daily',
    phosphorus_mg: 'weekly_average', protein_g: 'weekly_average', calories_kcal: 'weekly_average', calcium_mg: 'weekly_average' };
  const MEALS = [
    { key: 'breakfast', label: 'Breakfast' },
    { key: 'lunch', label: 'Lunch' },
    { key: 'dinner', label: 'Dinner' },
    { key: 'snack', label: 'Snack' },
  ];
  const MEAL_LABEL = Object.fromEntries(MEALS.map((m) => [m.key, m.label]));
  const FLAGS = [
    { key: 'phosphate_additive', label: 'Phosphate additives', hint: 'Ingredient list has "phos" (e.g. sodium phosphate); nearly fully absorbed', kind: 'warn' },
    { key: 'high_gi', label: 'High glycemic index', hint: 'Raises blood glucose quickly', kind: 'warn' },
    { key: 'counts_as_fluid', label: 'Counts as fluid', hint: 'Liquid at room temperature', kind: '' },
    { key: 'avoid_ckd', label: 'Avoid with CKD', hint: 'e.g. star fruit', kind: 'warn' },
    { key: 'hypo_treatment', label: 'Hypo treatment', hint: 'Fast carbs, low potassium', kind: 'good' },
    { key: 'low_potassium_fruit', label: 'Low-potassium fruit', hint: '', kind: 'good' },
    { key: 'processed', label: 'Processed', hint: 'Usually higher sodium / additives', kind: '' },
  ];
  const FLAG = Object.fromEntries(FLAGS.map((f) => [f.key, f]));
  const RATING_LABEL = {
    green: 'Green: generally kidney-friendly',
    yellow: 'Yellow: moderate, watch the portion',
    red: 'Red: high, needs careful consideration',
  };
  const LEVEL_TEXT = { ok: 'OK', caution: 'Near limit', over: 'Over limit' };
  const LEVEL_RATING = { ok: 'green', caution: 'yellow', over: 'red', medium: 'yellow', high: 'red' };

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

  // Demo mode runs an in-page copy of the server (no backend): `?mock=1` while developing, or
  // window.KDL_PREVIEW === true in the self-contained preview built by scripts/build_preview.py
  // (the preview's host does not pass a query string to the page).
  const PREVIEW = window.KDL_PREVIEW === true;
  const QUERY = (() => { try { return String(location.search || ''); } catch (e) { return ''; } })();
  const MOCK = PREVIEW || /[?&]mock=1(?:&|$)/.test(QUERY);
  const MOCK_HD = MOCK && /[?&]hd=1(?:&|$)/.test(QUERY); // demo profile on hemodialysis (Mon/Wed/Fri)
  const THEME_KEY = 'kdl-theme';
  const SHOP_KEY = 'kdl-shop'; // shopping-list checkboxes live only in this browser
  const SVG_NS = 'http://www.w3.org/2000/svg';

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function setAttrs(el, attrs) {
    if (!attrs) return el;
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    return el;
  }
  function appendChildren(el, children) {
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  function h(tag, attrs, ...children) {
    return appendChildren(setAttrs(document.createElement(tag), attrs), children);
  }
  function s(tag, attrs, ...children) {
    return appendChildren(setAttrs(document.createElementNS(SVG_NS, tag), attrs), children);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

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

  function localISO(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  function todayStr() { return localISO(new Date()); }
  function parseDate(str) { const [y, m, d] = str.split('-').map(Number); return new Date(y, m - 1, d); }
  function addDays(str, n) { const d = parseDate(str); d.setDate(d.getDate() + n); return localISO(d); }
  function fmtDateLong(str) {
    const d = parseDate(str);
    const t = todayStr();
    if (str === t) return `Today, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    if (str === addDays(t, -1)) return `Yesterday, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    if (str === addDays(t, 1)) return `Tomorrow, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
  }
  function fmtDateShort(str) {
    return parseDate(str).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }
  function fmtMonthDay(str) { return parseDate(str).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); }
  function fmtRange(start, end) { return `${fmtMonthDay(start)} – ${fmtMonthDay(end)}`; }
  function weekdayMon(str) { return (parseDate(str).getDay() + 6) % 7; } // 0 = Monday … 6 = Sunday
  function weekStartOf(str, weekStart) {
    const back = weekStart === 'sunday' ? parseDate(str).getDay() : weekdayMon(str);
    return addDays(str, -back);
  }
  function daysBetween(a, b) { return Math.round((parseDate(b) - parseDate(a)) / 86400000); }
  function defaultStatusFor(date) { return date > todayStr() ? 'planned' : 'eaten'; }
  function fmtChange(pct) {
    if (pct == null || !Number.isFinite(Number(pct))) return null;
    const n = Math.round(Number(pct) * 10) / 10;
    if (Math.abs(n) < 0.05) return 'no change';
    return `${n > 0 ? '+' : '−'}${Math.abs(n).toLocaleString('en-US', { maximumFractionDigits: 1 })} %`;
  }
  function defaultMealForNow() {
    const hr = new Date().getHours();
    if (hr < 10) return 'breakfast';
    if (hr < 14) return 'lunch';
    if (hr < 17) return 'snack';
    if (hr < 21) return 'dinner';
    return 'snack';
  }
  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }
  function qs(params) {
    const u = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== '') u.set(k, v);
    return u.toString();
  }
  function numOrNull(v) {
    if (v == null) return null;
    const str = String(v).trim();
    if (str === '') return null;
    const n = Number(str);
    return Number.isFinite(n) ? n : null;
  }

  // ---------------------------------------------------------------------------
  // Icons
  // ---------------------------------------------------------------------------
  function ratingIcon(ratingOrLevel, opts = {}) {
    const r = LEVEL_RATING[ratingOrLevel] || ratingOrLevel || 'green';
    const label = opts.label || RATING_LABEL[r];
    const svg = s('svg', { class: `rating ${r}`, viewBox: '0 0 24 24', focusable: 'false' });
    if (opts.decorative) svg.setAttribute('aria-hidden', 'true');
    else { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label); svg.append(s('title', {}, label)); }
    if (r === 'green') {
      svg.append(s('circle', { class: 'shape', cx: 12, cy: 12, r: 11 }));
      svg.append(s('path', { class: 'glyph', d: 'M6.8 12.6l1.7-1.7 2.6 2.6 5.4-5.4 1.7 1.7-7.1 7.1z' }));
    } else if (r === 'yellow') {
      svg.append(s('path', { class: 'shape', d: 'M12 2.2 23 21.5H1z' }));
      svg.append(s('rect', { class: 'glyph', x: 10.9, y: 9, width: 2.2, height: 6.2, rx: 1 }));
      svg.append(s('circle', { class: 'glyph', cx: 12, cy: 18.2, r: 1.35 }));
    } else {
      svg.append(s('path', { class: 'shape', d: 'M7.6 1.5h8.8l6.1 6.1v8.8l-6.1 6.1H7.6l-6.1-6.1V7.6z' }));
      svg.append(s('rect', { class: 'glyph', x: 10.9, y: 6, width: 2.2, height: 7.5, rx: 1 }));
      svg.append(s('circle', { class: 'glyph', cx: 12, cy: 16.8, r: 1.45 }));
    }
    return svg;
  }
  function levelPill(level, text) {
    return h('span', { class: `pill level-${level}` }, ratingIcon(level, { decorative: true }), text || LEVEL_TEXT[level] || level);
  }
  function plusIcon() {
    return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { d: 'M12 5v14M5 12h14', stroke: 'currentColor', 'stroke-width': 2.2, 'stroke-linecap': 'round' }));
  }

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
  // nutrients.round_value: mg and mL to integers, everything else (kcal included) to 1 decimal.
  function roundValue(key, v) {
    if (v == null) return null;
    v = Number(v);
    if (!Number.isFinite(v)) return null;
    return isIntUnit(key) ? halfUp(v, 0) : halfUp(v, 1);
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
  // Demo API: an in-page copy of the FastAPI server (app/foods.py, log.py, meals.py,
  // profile.py, nutrients.py, periods.py) over in-memory tables. Same routes, same numbers,
  // same texts; nothing is persisted. On only with ?mock=1 or in the preview build.
  // ---------------------------------------------------------------------------
  const MEAL_KEYS = MEALS.map((m) => m.key);
  const MEAL_RANK = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 };
  const FOOD_CATEGORIES = ['Fruits', 'Vegetables', 'Grains & Breads', 'Dairy & Alternatives', 'Meat, Poultry & Eggs', 'Fish & Seafood',
    'Legumes, Nuts & Seeds', 'Beverages', 'Sweets & Snacks', 'Condiments & Sauces', 'Prepared & Fast Food', 'Diabetes supplies'];
  const CKD_STAGES = ['1', '2', '3a', '3b', '4', '5'];
  const DIALYSIS_MODES = ['none', 'hemodialysis', 'peritoneal'];
  const DIABETES_TYPES = ['none', 'type1', 'type2'];
  const TARGET_KEYS = [...NUTRIENT_KEYS, 'carbs_per_meal_g'];
  const ROLE_WORD = { limit: 'limit', range: 'maximum', info: 'maximum', goal: 'goal', track: 'goal' };
  const MAX_SEARCH_QUERY_CHARS = 200;
  const MAX_SEARCH_WORDS = 10;
  const MAX_RANGE_DAYS = 366;
  const MAX_INTERDIALYTIC_DAYS = 7;
  const POTASSIUM_NOTE = 'Only restrict potassium if your blood potassium is high; your care team sets the number.';
  const NOTE_DAILY = 'Potassium, sodium and fluid are judged day by day: a day well over the limit is a risk on its own, '
    + 'and a low day does not bank against a high one.';
  const NOTE_WEEKLY = 'Phosphorus and protein are judged on the weekly average: blood phosphate and nutritional status '
    + 'reflect weeks of intake, so an average above target matters more than one high day.';
  const NOTE_CARBS = 'Carbohydrate is counted per meal and per day for insulin; its weekly average is informational.';
  const NOTE_INTERDIALYTIC = 'Between hemodialysis sessions potassium, sodium and fluid accumulate until the next session; '
    + "the 'since last dialysis' totals cover the current interval (the long weekend gap is the one to watch).";
  const NOTE_NO_DIALYSIS_DAYS = 'Set your dialysis days in the profile to see potassium, sodium and fluid totals since your last session.';
  const NOTE_CAPPED = `No dialysis day fell within the last ${MAX_INTERDIALYTIC_DAYS} days, so the interval is capped at ${MAX_INTERDIALYTIC_DAYS} days.`;
  const CSV_COLUMNS = ['id', 'date', 'meal', 'status', 'food_id', 'food_name', 'servings', 'grams', 'note', ...NUTRIENT_KEYS, 'created_at', 'updated_at'];

  class ApiError extends Error {
    constructor(status, detail) { super(detail); this.status = status; this.detail = detail; }
  }
  function fail(status, detail) { throw new ApiError(status, detail); }
  function failFields(errors) { fail(400, errors.join('; ') || 'invalid request'); }

  // ---- pure rules (nutrients.py / periods.py) ----
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

  // ---- request validation (the server's pydantic models, flattened like main.py does) ----
  // Pydantic collects every field's errors in the model's field order before failing, and main.py
  // joins them with "; ". Literal fields compare the raw value (str_strip_whitespace only applies
  // to str fields), and number fields run in lax mode: true/false count as 1/0 and strings parse.
  function validDate(v) {
    if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return 'date must be formatted YYYY-MM-DD';
    const [y, m, d] = v.split('-').map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d));
    if (y < 1 || dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return 'date is not a valid calendar date';
    return null;
  }
  const PY_SPECIAL_FLOAT = /^[+-]?(?:inf|infinity|nan)$/i;
  function specialFloat(t) { return /nan/i.test(t) ? NaN : t[0] === '-' ? -Infinity : Infinity; }
  // pydantic-core float from str: Rust's f64 grammar after trimming; on failure it retries with
  // the underscores removed unless one leads, trails or doubles. undefined = unable to parse.
  const RUST_FLOAT = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
  function pydanticFloat(s) {
    const t = s.trim();
    if (PY_SPECIAL_FLOAT.test(t)) return specialFloat(t);
    if (RUST_FLOAT.test(t)) return Number(t);
    if (t && !t.startsWith('_') && !t.endsWith('_') && !t.includes('__')) {
      const u = t.replace(/_/g, '');
      if (RUST_FLOAT.test(u)) return Number(u);
    }
    return undefined;
  }
  // pydantic-core int from str: trimmed digits (single underscores between them), optional
  // sign, and a decimal part only when it is all zeros ("5.00" is 5, "5." and "1e2" are not).
  function pydanticInt(s) {
    const t = s.trim();
    if (!/^[+-]?\d(?:_?\d)*(?:\.0+)?$/.test(t)) return undefined;
    return Number(t.replace(/_/g, '').replace(/\.0+$/, ''));
  }
  // Python float(str): PEP 515 underscores only between digits; inf/nan words. undefined = ValueError.
  const PY_FLOAT = /^[+-]?(?:(?:\d(?:_?\d)*)?\.\d(?:_?\d)*|\d(?:_?\d)*\.?)(?:[eE][+-]?\d(?:_?\d)*)?$/;
  function pyFloatStr(s) {
    const t = s.trim();
    if (PY_SPECIAL_FLOAT.test(t)) return specialFloat(t);
    return PY_FLOAT.test(t) ? Number(t.replace(/_/g, '')) : undefined;
  }
  // float(v) for a JSON value that is not a bool: undefined when Python raises.
  function pyFloat(v) {
    if (typeof v === 'number') return v;
    if (typeof v === 'string') return pyFloatStr(v);
    return undefined;
  }
  // repr() of a str, as an f-string {raw!r} prints it.
  function pyStrRepr(s) {
    const q = s.includes("'") && !s.includes('"') ? '"' : "'";
    let body = s.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t');
    if (q === "'") body = body.replace(/'/g, "\\'");
    return q + body + q;
  }
  function isDict(v) { return v != null && typeof v === 'object' && !Array.isArray(v); }
  const MAX_ID_TEXT = '9223372036854775807'; // 2**63 - 1, which a JS number cannot hold exactly
  class Check {
    // A request body model. A missing (null) body or one that is not an object fails at once,
    // as FastAPI does; nested models (saved-meal items, ranges) pass { nested: true }.
    constructor(body, { nested = false } = {}) {
      if (!nested) {
        if (body == null) failFields(['Field required']);
        if (!isDict(body)) failFields(['Input should be a valid dictionary or object to extract fields from']);
      }
      this.body = isDict(body) ? body : {}; this.errors = []; this.out = {};
    }
    has(k) { return Object.prototype.hasOwnProperty.call(this.body, k); }
    err(loc, msg) { this.errors.push(loc ? `${loc}: ${msg}` : msg); }
    str(k, { required = false, def, min = 0, max = Infinity, nullable = true, emptyToNull = false } = {}) {
      if (!this.has(k)) { if (required) this.err(k, 'Field required'); else if (def !== undefined) this.out[k] = def; return; }
      let v = this.body[k];
      if (v == null) { if (!nullable) this.err(k, 'Input should be a valid string'); else this.out[k] = null; return; }
      if (typeof v !== 'string') { this.err(k, 'Input should be a valid string'); return; }
      v = v.trim();
      if (v.length < min) { this.err(k, `String should have at least ${min} character${min === 1 ? '' : 's'}`); return; }
      if (v.length > max) { this.err(k, `String should have at most ${max} characters`); return; }
      this.out[k] = emptyToNull && !v ? null : v;
    }
    // A str field with the validate_date after-validator (required: `str`, else `str | None`).
    date(k, { required = true } = {}) {
      if (!this.has(k)) { if (required) this.err(k, 'Field required'); return; }
      const v = this.body[k];
      if (v == null && !required) { this.out[k] = null; return; }
      if (typeof v !== 'string') { this.err(k, 'Input should be a valid string'); return; }
      const s = v.trim();
      const e = validDate(s);
      if (e) this.err(k, e); else this.out[k] = s;
    }
    choice(k, options, { required = false, def, nullable = false } = {}) {
      if (!this.has(k)) { if (required) this.err(k, 'Field required'); else if (def !== undefined) this.out[k] = def; return; }
      const v = this.body[k];
      if (v == null && nullable) { this.out[k] = null; return; }
      if (!options.includes(v)) { this.err(k, choiceMessage(options)); return; }
      this.out[k] = v;
    }
    // float (or int with int: true) in lax mode; maxId: the SQLite id ceiling (le=2**63-1).
    num(k, { required = false, def, gt = null, ge = null, le = null, nullable = true, int = false, maxId = false } = {}) {
      if (!this.has(k)) { if (required) this.err(k, 'Field required'); else if (def !== undefined) this.out[k] = def; return; }
      const v = this.body[k];
      const kind = int ? 'integer' : 'number';
      if (v == null) { if (nullable && !required) this.out[k] = null; else this.err(k, `Input should be a valid ${kind}`); return; }
      let n;
      if (typeof v === 'boolean') n = v ? 1 : 0;
      else if (typeof v === 'number') n = v;
      else if (typeof v === 'string') {
        n = int ? pydanticInt(v) : pydanticFloat(v);
        if (n === undefined) { this.err(k, `Input should be a valid ${kind}, unable to parse string as ${int ? 'an integer' : 'a number'}`); return; }
      } else { this.err(k, `Input should be a valid ${kind}`); return; }
      if (!Number.isFinite(n)) { this.err(k, 'Input should be a finite number'); return; }
      if (int && !Number.isInteger(n)) { this.err(k, 'Input should be a valid integer, got a number with a fractional part'); return; }
      if (gt != null && !(n > gt)) { this.err(k, `Input should be greater than ${gt}`); return; }
      if (ge != null && !(n >= ge)) { this.err(k, `Input should be greater than or equal to ${ge}`); return; }
      if (le != null && !(n <= le)) { this.err(k, `Input should be less than or equal to ${le}`); return; }
      if (maxId && n >= 2 ** 63) { this.err(k, `Input should be less than or equal to ${MAX_ID_TEXT}`); return; }
      this.out[k] = n;
    }
    // `dict[str, Any] = Field(default_factory=dict)` + validate_nutrients.
    nutrients(k = 'nutrients') {
      if (!this.has(k)) { this.out[k] = {}; return; }
      const v = this.body[k];
      if (!isDict(v)) { this.err(k, 'Input should be a valid dictionary'); return; }
      const n = this.errors.length;
      const out = validateNutrients(v, this.errors);
      if (this.errors.length === n) this.out[k] = out;
    }
    // `list[str] = Field(default_factory=list)` + validate_flags (items are stripped first).
    flags(k = 'flags') {
      if (!this.has(k)) { this.out[k] = []; return; }
      const v = this.body[k];
      if (!Array.isArray(v)) { this.err(k, 'Input should be a valid list'); return; }
      const n = this.errors.length;
      v.forEach((x, i) => { if (typeof x !== 'string') this.err(`${k}.${i}`, 'Input should be a valid string'); });
      if (this.errors.length !== n) return;
      const out = validateFlags(v.map((x) => x.trim()), this.errors);
      if (this.errors.length === n) this.out[k] = out;
    }
    // `dict[str, Any] | None` + validate_targets (null leaves the targets alone).
    targets(k = 'targets') {
      if (!this.has(k)) return;
      const v = this.body[k];
      if (v == null) { this.out[k] = null; return; }
      if (!isDict(v)) { this.err(k, 'Input should be a valid dictionary'); return; }
      const n = this.errors.length;
      const out = validateTargets(v, this.errors);
      if (this.errors.length === n) this.out[k] = out;
    }
    // `list[Any] | None` + periods.normalise_dialysis_days (null clears the list).
    dialysisDays(k = 'dialysis_days') {
      if (!this.has(k)) return;
      const raw = this.body[k];
      if (raw == null) { this.out[k] = []; return; }
      if (!Array.isArray(raw)) { this.err(k, 'Input should be a valid list'); return; }
      const days = new Set();
      for (const d of raw) {
        if (typeof d !== 'number' || !Number.isInteger(d)) { this.err(k, 'dialysis_days must be whole numbers 0 (Monday) to 6 (Sunday)'); return; }
        if (d < 0 || d > 6) { this.err(k, 'dialysis_days must be between 0 (Monday) and 6 (Sunday)'); return; }
        days.add(d);
      }
      this.out[k] = [...days].sort((a, b) => a - b);
    }
    // `list[Literal[...]] | None`: one error per invalid item, then the model's own check.
    choiceList(k, options, { nonEmpty = null } = {}) {
      if (!this.has(k)) return;
      const raw = this.body[k];
      if (raw == null) { this.out[k] = null; return; }
      if (!Array.isArray(raw)) { this.err(k, 'Input should be a valid list'); return; }
      const n = this.errors.length;
      raw.forEach((x, i) => { if (!options.includes(x)) this.err(`${k}.${i}`, choiceMessage(options)); });
      if (this.errors.length !== n) return;
      if (!raw.length && nonEmpty) { this.err(k, nonEmpty); return; }
      this.out[k] = [...new Set(raw)];
    }
    // `list[Model] = Field(min_length=1)`; build(itemCheck) runs the item model's field checks.
    models(k, build, { minLength = 0 } = {}) {
      if (!this.has(k)) { this.err(k, 'Field required'); return; }
      const raw = this.body[k];
      if (!Array.isArray(raw)) { this.err(k, 'Input should be a valid list'); return; }
      const n = this.errors.length;
      const out = raw.map((it, i) => {
        if (!isDict(it)) { this.err(`${k}.${i}`, 'Input should be a valid dictionary or object to extract fields from'); return null; }
        const ic = new Check(it, { nested: true });
        build(ic);
        for (const e of ic.errors) this.errors.push(`${k}.${i}.${e}`);
        return ic.out;
      });
      if (this.errors.length !== n) return;
      if (raw.length < minLength) { this.err(k, `List should have at least ${minLength} item${minLength === 1 ? '' : 's'} after validation, not ${raw.length}`); return; }
      this.out[k] = out;
    }
    done() { if (this.errors.length) failFields(this.errors); return this.out; }
  }
  function choiceMessage(options) {
    const opts = options.map((o) => `'${o}'`);
    return `Input should be ${opts.length > 1 ? `${opts.slice(0, -1).join(', ')} or ${opts[opts.length - 1]}` : opts[0]}`;
  }
  // models.validate_nutrients (raises at the first bad key, so one message at most).
  function validateNutrients(values, errors) {
    if (values == null) return {};
    if (!isDict(values)) { errors.push('nutrients: Input should be a valid dictionary'); return {}; }
    const unknown = Object.keys(values).filter((k) => !NUTRIENT_KEYS.includes(k)).sort();
    if (unknown.length) { errors.push(`nutrients: unknown nutrient key(s): ${unknown.join(', ')}`); return {}; }
    const out = {};
    for (const [key, v] of Object.entries(values)) {
      if (v == null || v === '') { out[key] = null; continue; }
      const num = typeof v === 'boolean' ? undefined : pyFloat(v);
      if (num === undefined) { errors.push(`nutrients: ${key} must be a number`); return {}; }
      if (!Number.isFinite(num) || num < 0) { errors.push(`nutrients: ${key} must be a non-negative number`); return {}; }
      if (num > 1e6) { errors.push(`nutrients: ${key} must be at most 1e+06`); return {}; }
      out[key] = num;
    }
    return out;
  }
  // models.validate_flags (expects strings already stripped, as pydantic hands them over).
  function validateFlags(flags, errors) {
    if (flags == null) return [];
    if (!Array.isArray(flags)) { errors.push('flags: Input should be a valid list'); return []; }
    const out = [];
    for (const raw of flags) {
      if (typeof raw !== 'string') { errors.push('flags: flags must be strings'); return []; }
      const flag = raw.trim().toLowerCase();
      if (!flag) continue;
      if (!/^[a-z0-9_]{1,40}$/.test(flag)) { errors.push(`flags: invalid flag ${pyStrRepr(raw)}; use lowercase letters, digits and underscores`); return []; }
      if (!out.includes(flag)) out.push(flag);
    }
    return out;
  }
  // models.validate_targets: raises at the first bad key; a {min,max} object is a Range model,
  // whose own field errors surface as "targets.min: ..." / "targets.<extra>: ...".
  function validateTargets(targets, errors) {
    if (targets == null) return null;
    if (!isDict(targets)) { errors.push('targets: Input should be a valid dictionary'); return null; }
    const unknown = Object.keys(targets).filter((k) => !TARGET_KEYS.includes(k)).sort();
    if (unknown.length) { errors.push(`targets: unknown target key(s): ${unknown.join(', ')}`); return null; }
    const out = {};
    for (const [key, v] of Object.entries(targets)) {
      if (v == null) { out[key] = null; continue; }
      if (isDict(v)) {
        const rc = new Check(v, { nested: true });
        rc.num('min', { ge: 0, le: 1000000 });
        rc.num('max', { ge: 0, le: 1000000 });
        for (const extra of Object.keys(v)) if (extra !== 'min' && extra !== 'max') rc.err(extra, 'Extra inputs are not permitted');
        if (rc.errors.length) { errors.push(...rc.errors.map((e) => `targets.${e}`)); return null; }
        const lo = rc.out.min ?? null, hi = rc.out.max ?? null;
        if (lo == null && hi == null) { errors.push('targets: a range needs min and/or max'); return null; }
        if (lo != null && hi != null && lo > hi) { errors.push('targets: min must not exceed max'); return null; }
        out[key] = { min: lo, max: hi };
        continue;
      }
      const num = typeof v === 'boolean' ? undefined : pyFloat(v);
      if (num === undefined) { errors.push(`targets: ${key} target must be a number, a {min,max} object or null`); return null; }
      if (!Number.isFinite(num)) { errors.push(`targets: ${key} target must be a finite number`); return null; }
      if (num < 0) { errors.push(`targets: ${key} target must not be negative`); return null; }
      if (num > 1e6) { errors.push(`targets: ${key} target must be at most 1e+06`); return null; }
      out[key] = num;
    }
    return out;
  }
  // foods._parse_builtin_item
  function parseBuiltinItem(item) {
    const name = String((item && item.name) || '').trim();
    if (!name) throw new Error('missing name');
    const sg = item.serving_g == null || typeof item.serving_g === 'boolean' ? NaN : Number(item.serving_g);
    if (Number.isNaN(sg)) throw new Error(`${name}: serving_g must be a number`);
    if (sg <= 0) throw new Error(`${name}: serving_g must be positive`);
    let fdc = item.fdc_id;
    if (fdc != null) {
      fdc = Math.trunc(Number(fdc));
      if (!Number.isFinite(fdc)) throw new Error(`${name}: fdc_id must be an integer`);
    }
    const raw = item.nutrients && typeof item.nutrients === 'object' && !Array.isArray(item.nutrients) ? item.nutrients : item;
    const nutrients = {};
    for (const key of NUTRIENT_KEYS) {
      const v = raw[key];
      if (v == null) { nutrients[key] = null; continue; }
      const n = Number(v);
      if (Number.isNaN(n)) throw new Error(`${name}: ${key} must be a number`);
      nutrients[key] = n;
    }
    const flags = item.flags || [];
    if (!Array.isArray(flags)) throw new Error(`${name}: flags must be a list`);
    return { name, brand: item.brand || null, category: item.category || null, fdc_id: fdc == null ? null : fdc,
      serving_desc: String(item.serving_desc || `${pyG(sg)} g`), serving_g: sg, nutrients, flags: flags.map(String),
      kidney_notes: item.kidney_notes || null };
  }
  // SQLite LOWER() / COLLATE NOCASE fold ASCII letters only.
  function asciiLower(s) { return String(s).replace(/[A-Z]+/g, (m) => m.toLowerCase()); }
  function nocaseCompare(a, b) { const x = asciiLower(a), y = asciiLower(b); return x < y ? -1 : x > y ? 1 : 0; }
  // foods.search_rank
  function searchRank(name, brand, query, words) {
    const n = name.toLowerCase();
    if (n.startsWith(query)) return 0;
    if (words.length && n.split(/[^a-z0-9]+/).some((tok) => tok && tok.startsWith(words[0]))) return 1;
    if (brand && brand.toLowerCase().startsWith(query)) return 2;
    return 3;
  }
  function csvCell(v) {
    if (v == null) return '';
    const s = String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  // The 24 hand-typed foods used by ?mock=1 when no database is embedded in the page.
  function fallbackFoods() {
    const F = (name, category, serving_desc, serving_g, n, flags = [], kidney_notes = null) => ({ name, category, serving_desc, serving_g,
      nutrients: { calories_kcal: n[0], protein_g: n[1], fat_g: n[2], sat_fat_g: n[3], carbs_g: n[4], fiber_g: n[5], sugar_g: n[6],
        sodium_mg: n[7], potassium_mg: n[8], phosphorus_mg: n[9], calcium_mg: n[10], fluid_ml: n[11] }, flags, kidney_notes });
    const foods = [
      F('Banana, raw', 'Fruits', '1 medium (118 g)', 118, [105, 1.29, 0.39, 0.13, 26.95, 3.1, 14.43, 1, 422, 26, 6, 0], [],
        'High potassium; a renal dietitian usually suggests apples, berries or grapes instead.'),
      F('Apple, raw, with skin', 'Fruits', '1 medium (182 g)', 182, [95, 0.47, 0.31, 0.05, 25.13, 4.4, 18.91, 2, 195, 20, 11, 0], ['low_potassium_fruit']),
      F('Blueberries, raw', 'Fruits', '1/2 cup (74 g)', 74, [42, 0.55, 0.25, 0.02, 10.7, 1.8, 7.4, 1, 57, 9, 4, 0], ['low_potassium_fruit']),
      F('Star fruit (carambola), raw', 'Fruits', '1 medium (91 g)', 91, [28, 0.95, 0.3, 0.02, 6.1, 2.5, 3.62, 2, 121, 11, 3, 0], ['avoid_ckd'],
        'Star fruit contains caramboxin, a neurotoxin that failing kidneys cannot clear. Avoid completely.'),
      F('Bread, white', 'Grains & Breads', '1 slice (29 g)', 29, [77, 2.6, 1, 0.2, 14.3, 0.7, 1.6, 142, 37, 28, 44, 0], ['high_gi']),
      F('Rice, white, long-grain, cooked', 'Grains & Breads', '1 cup (158 g)', 158, [205, 4.25, 0.44, 0.12, 44.51, 0.6, 0.08, 2, 55, 68, 16, 0]),
      F('Oatmeal, cooked with water', 'Grains & Breads', '1 cup (234 g)', 234, [166, 5.94, 3.56, 0.73, 28.08, 4, 0.63, 9, 164, 180, 21, 0]),
      F('Egg white, raw', 'Meat, Poultry & Eggs', '1 large (33 g)', 33, [17, 3.6, 0.1, 0, 0.2, 0, 0.2, 55, 54, 5, 2, 0]),
      F('Chicken breast, roasted, skinless', 'Meat, Poultry & Eggs', '1/2 breast (86 g)', 86, [142, 26.7, 3.1, 0.9, 0, 0, 0, 64, 220, 196, 13, 0]),
      F('Cod, Atlantic, cooked', 'Fish & Seafood', '3 oz (85 g)', 85, [89, 19.4, 0.7, 0.1, 0, 0, 0, 66, 207, 117, 12, 0]),
      F('Milk, 2% reduced fat', 'Dairy & Alternatives', '1 cup (244 g)', 244, [122, 8.05, 4.83, 3.07, 11.71, 0, 12.35, 115, 342, 224, 293, 244], ['counts_as_fluid']),
      F('Cheese, American, processed', 'Dairy & Alternatives', '1 slice, 1 oz (28 g)', 28, [102, 5.1, 8.6, 5, 1.3, 0, 0.6, 468, 37, 179, 168, 0], ['phosphate_additive', 'processed'],
        'Processed cheese usually contains phosphate emulsifiers; natural cheese in a small portion is a better choice.'),
      F('Potato, baked, with skin', 'Vegetables', '1 medium (173 g)', 173, [161, 4.33, 0.22, 0.06, 36.59, 3.8, 2.03, 17, 926, 121, 26, 0], [],
        'Very high potassium. Peeling, dicing and boiling in plenty of water (leaching) removes a large share.'),
      F('Green beans, boiled', 'Vegetables', '1/2 cup (63 g)', 63, [22, 1.2, 0.2, 0, 5, 2, 1, 1, 92, 18, 28, 0]),
      F('Cauliflower, boiled', 'Vegetables', '1/2 cup (62 g)', 62, [14, 1.1, 0.3, 0, 2.5, 1.4, 1.3, 9, 88, 20, 10, 0]),
      F('Deli turkey breast, sliced', 'Meat, Poultry & Eggs', '2 oz (57 g)', 57, [62, 8.4, 1.2, 0.3, 1.3, 0, 1, 512, 211, 142, 4, 0], ['phosphate_additive', 'processed']),
      F('Cola, regular', 'Beverages', '1 can, 12 fl oz (370 g)', 370, [155, 0, 0.9, 0, 38.3, 0, 33.9, 11, 18, 33, 7, 333], ['phosphate_additive', 'high_gi', 'counts_as_fluid', 'processed'],
        'Dark colas get their color from phosphoric acid, an additive phosphorus source. Clear sodas or water are better.'),
      F('Coffee, brewed', 'Beverages', '1 cup, 8 fl oz (237 g)', 237, [2, 0.28, 0.05, 0, 0, 0, 0, 5, 116, 7, 5, 237], ['counts_as_fluid']),
      F('Water, tap', 'Beverages', '1 cup, 8 fl oz (237 g)', 237, [0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 7, 237], ['counts_as_fluid']),
      F('Glucose tablet (4 g carb)', 'Diabetes supplies', '1 tablet (4 g)', 4, [15, 0, 0, 0, 4, 0, 4, 0, 0, 0, 0, 0], ['hypo_treatment', 'high_gi']),
      F('Cheeseburger, fast food, with condiments', 'Prepared & Fast Food', '1 sandwich (127 g)', 127, [313, 17.1, 14, 6.3, 32.3, 1.5, 6.6, 798, 234, 180, 117, 0], ['phosphate_additive', 'processed']),
      F('Rice cakes, plain, unsalted', 'Grains & Breads', '2 cakes (18 g)', 18, [70, 1.5, 0.5, 0.1, 14.7, 0.8, 0.2, 5, 52, 65, 2, 0]),
      F('Mayonnaise', 'Condiments & Sauces', '1 tbsp (14 g)', 14, [94, 0.13, 10.3, 1.6, 0.1, 0, 0.1, 88, 3, 4, 1, 0]),
      F('Strawberries, raw', 'Fruits', '1/2 cup, halves (76 g)', 76, [24, 0.5, 0.2, 0, 5.8, 1.5, 3.7, 1, 116, 18, 12, 0], ['low_potassium_fruit']),
    ];
    return { version: 'mock-fallback', source: 'hand-typed sample (app.js)', foods: foods.map((f, i) => ({ fdc_id: 100001 + i, ...f })) };
  }

  class MockApi {
    constructor({ foodsData = null, hemodialysis = false } = {}) {
      this._lastUs = 0;
      this._foods = []; this._foodById = new Map(); this._nextFoodId = 1;
      this._entries = []; this._nextEntryId = 1;
      this._templates = []; this._nextTemplateId = 1;
      this.foodsSource = foodsData ? 'embedded' : 'fallback';
      this._profile = { id: 1, name: '', weight_kg: null, height_cm: null, ckd_stage: '3b', dialysis: 'none', diabetes: 'type1', warn_fraction: 0.8,
        dialysis_days: [], week_start: 'monday', targets: {}, updated_at: this._stamp() };
      this._importBuiltin(foodsData || fallbackFoods());
      seedSampleData(this, { hemodialysis });
    }

    // utcnow(): ISO-8601 UTC with microseconds, strictly increasing within the page.
    _stamp(date = null) {
      let us = (date ? date.getTime() : Date.now()) * 1000;
      if (!date) { if (us <= this._lastUs) us = this._lastUs + 1; this._lastUs = us; }
      const ms = Math.floor(us / 1000);
      return `${new Date(ms).toISOString().slice(0, 19)}.${String(ms % 1000).padStart(3, '0')}${String(us % 1000).padStart(3, '0')}Z`;
    }

    // ---- foods (app/foods.py) ----
    _importBuiltin(data) {
      if (!data || typeof data !== 'object' || !Array.isArray(data.foods)) return;
      const byFdc = new Map(), byName = new Map();
      for (const item of data.foods) {
        let parsed;
        try { parsed = parseBuiltinItem(item); } catch (e) { continue; }
        const existing = parsed.fdc_id != null ? byFdc.get(parsed.fdc_id) : byName.get(parsed.name.toLowerCase());
        if (existing != null) { this._updateFood(existing, { ...parsed, hidden: false }); continue; }
        const id = this._insertFood({ source: 'builtin', ...parsed });
        if (parsed.fdc_id != null) byFdc.set(parsed.fdc_id, id); else byName.set(parsed.name.toLowerCase(), id);
      }
      this.foodsVersion = data.version ? String(data.version) : null;
    }
    _normaliseFluid(nutrients, flags, servingG) {
      const out = Object.fromEntries(NUTRIENT_KEYS.map((k) => [k, nutrients[k] == null ? null : Number(nutrients[k])]));
      if (flags.includes('counts_as_fluid')) { if (out.fluid_ml == null) out.fluid_ml = Number(servingG); }
      else out.fluid_ml = 0;
      return out;
    }
    // foods.stored_food_values: a food row keeps what the API shows (serving_g to 1 decimal,
    // mg/mL whole, the rest to 1 decimal), so scaling the shown values gives the entry's numbers.
    _storedFoodValues(nutrients, flags, servingG) {
      const serving = pyRound(Number(servingG), 1);
      return [serving, roundNutrients(this._normaliseFluid(nutrients, flags, serving))];
    }
    _insertFood({ name, serving_desc, serving_g, nutrients, source = 'custom', brand = null, category = null, fdc_id = null, flags = [], kidney_notes = null, hidden = false }) {
      const now = this._stamp();
      const [servingG, values] = this._storedFoodValues(nutrients, flags, serving_g);
      const row = { id: this._nextFoodId++, name, brand, category, source, fdc_id, serving_desc, serving_g: servingG,
        nutrients: values, flags: [...flags], kidney_notes, hidden: !!hidden, created_at: now, updated_at: now };
      this._foods.push(row);
      this._foodById.set(row.id, row);
      return row.id;
    }
    _updateFood(id, { name, serving_desc, serving_g, nutrients, brand = null, category = null, flags = [], kidney_notes = null, hidden = null, fdc_id }) {
      const row = this._foodById.get(id);
      const [servingG, values] = this._storedFoodValues(nutrients, flags, serving_g);
      Object.assign(row, { name, brand, category, serving_desc, serving_g: servingG, nutrients: values,
        flags: [...flags], kidney_notes, updated_at: this._stamp() });
      if (hidden != null) row.hidden = !!hidden;
      if (fdc_id !== undefined) row.fdc_id = fdc_id;
    }
    _food(id) { return this._foodById.get(Number(id)) || null; }
    _foodOr404(id) { const f = this._food(id); if (!f) fail(404, `food ${id} not found`); return f; }
    _foodView(row) {
      const warnings = evaluateWarnings(row.nutrients, row.flags, row.kidney_notes, 'per serving');
      return { id: row.id, name: row.name, brand: row.brand, category: row.category, source: row.source, fdc_id: row.fdc_id,
        serving_desc: row.serving_desc, serving_g: pyRound(row.serving_g, 1), nutrients: roundNutrients(row.nutrients), flags: [...row.flags],
        kidney_notes: row.kidney_notes, hidden: row.hidden, warnings, kidney_rating: ratingFromWarnings(warnings) };
    }
    _foodReferenced(id) {
      return this._entries.some((e) => e.food_id === id) || this._templates.some((t) => t.items.some((it) => it.food_id === id));
    }
    _searchFoods(q, category, source, limit) {
      const query = String(q || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
      const words = query ? query.split(' ').slice(0, MAX_SEARCH_WORDS) : [];
      const last = new Map(); // food_id -> MAX(created_at) of its log entries
      for (const e of this._entries) { const l = last.get(e.food_id); if (l == null || e.created_at > l) last.set(e.food_id, e.created_at); }
      let rows = this._foods.filter((f) => !f.hidden && (!category || f.category === category) && (!source || f.source === source)
        && words.every((w) => asciiLower(f.name).includes(w) || asciiLower(f.brand || '').includes(w)));
      rows.sort((a, b) => {
        const la = last.get(a.id), lb = last.get(b.id);
        if ((la == null) !== (lb == null)) return la == null ? 1 : -1;
        if (la != null && la !== lb) return la > lb ? -1 : 1;
        return nocaseCompare(a.name, b.name) || a.id - b.id;
      });
      if (words.length) rows.sort((a, b) => searchRank(a.name, a.brand, query, words) - searchRank(b.name, b.brand, query, words));
      return rows.slice(0, limit).map((f) => this._foodView(f));
    }
    _foodBody(body) {
      const c = new Check(body);
      c.str('name', { required: true, min: 1, max: 200, nullable: false });
      c.str('brand', { max: 200, def: null, emptyToNull: true });
      c.str('category', { max: 100, def: null, emptyToNull: true });
      c.str('serving_desc', { required: true, min: 1, max: 200, nullable: false });
      c.num('serving_g', { required: true, ge: 0.1, le: 100000, nullable: false });
      c.nutrients();
      c.flags();
      c.str('kidney_notes', { max: 1000, def: null, emptyToNull: true });
      return c.done();
    }

    // ---- profile (app/profile.py) ----
    _profileView() {
      const p = this._profile;
      const targets = {};
      for (const [k, v] of Object.entries(p.targets)) targets[k] = v && typeof v === 'object' ? { min: v.min, max: v.max } : v;
      return { id: 1, name: p.name, weight_kg: p.weight_kg, height_cm: p.height_cm, ckd_stage: p.ckd_stage, dialysis: p.dialysis, diabetes: p.diabetes,
        warn_fraction: p.warn_fraction, dialysis_days: [...p.dialysis_days], week_start: p.week_start === 'sunday' ? 'sunday' : 'monday', targets, updated_at: p.updated_at };
    }
    _updateProfile(body) {
      const c = new Check(body);
      c.str('name', { max: 100 });
      c.num('weight_kg', { gt: 0, le: 500 });
      c.num('height_cm', { gt: 0, le: 300 });
      c.choice('ckd_stage', CKD_STAGES, { nullable: true });
      c.choice('dialysis', DIALYSIS_MODES, { nullable: true });
      c.choice('diabetes', DIABETES_TYPES, { nullable: true });
      c.num('warn_fraction', { gt: 0, le: 1 });
      c.targets();
      c.dialysisDays();
      c.choice('week_start', ['monday', 'sunday'], { nullable: true });
      const data = c.done();
      const p = this._profile;
      for (const col of ['weight_kg', 'height_cm']) if (col in data) p[col] = data[col];
      for (const col of ['name', 'ckd_stage', 'dialysis', 'diabetes', 'warn_fraction', 'week_start']) if (col in data && data[col] != null) p[col] = data[col];
      if (data.targets != null) p.targets = { ...p.targets, ...data.targets };
      if ('dialysis_days' in data) p.dialysis_days = data.dialysis_days || [];
      p.updated_at = this._stamp();
      return this._profileView();
    }
    _suggested() {
      const p = this._profile;
      if (p.weight_kg == null) fail(400, 'Save your weight in the profile first; the suggestions are per kg of body weight');
      try { return suggestTargets(p.weight_kg, p.ckd_stage, p.dialysis, p.diabetes, p.height_cm); } catch (e) { return fail(400, e.message); }
    }

    // ---- log (app/log.py) ----
    _insertEntry({ date, meal, food, servings, grams = null, note = null, status = 'eaten', createdAt = null }) {
      const now = createdAt || this._stamp();
      const row = { id: this._nextEntryId++, date, meal, food_id: food.id, food_name: food.name, servings: Number(servings),
        grams: grams == null ? null : Number(grams), note: note == null ? null : note, status,
        nutrients: scaleNutrients(food.nutrients, Number(servings)), created_at: now, updated_at: now };
      this._entries.push(row);
      return row;
    }
    _entry(id) { return this._entries.find((e) => e.id === Number(id)) || null; }
    _entryView(row) {
      const food = this._food(row.food_id) || { flags: [], kidney_notes: null };
      const warnings = evaluateWarnings(row.nutrients, food.flags, food.kidney_notes, 'in this entry');
      return { id: row.id, date: row.date, meal: row.meal, food_id: row.food_id, food_name: row.food_name, servings: pyRound(row.servings, 3),
        grams: row.grams == null ? null : pyRound(row.grams, 1), note: row.note, status: row.status, nutrients: roundNutrients(row.nutrients),
        warnings, kidney_rating: ratingFromWarnings(warnings), created_at: row.created_at, updated_at: row.updated_at };
    }
    // fetch_entries: ORDER BY date, meal, status (eaten first), created_at, id
    _fetchEntries({ start = null, end = null, status = null, meal = null } = {}) {
      return this._entries.filter((e) => (!start || e.date >= start) && (!end || e.date <= end) && (!status || e.status === status) && (!meal || e.meal === meal))
        .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)
          || (MEAL_RANK[a.meal] ?? 3) - (MEAL_RANK[b.meal] ?? 3)
          || (a.status === 'eaten' ? 0 : 1) - (b.status === 'eaten' ? 0 : 1)
          || (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0)
          || a.id - b.id);
    }
    _dayFigures(rows) {
      const p = this._profile;
      const eaten = emptyTotals(), planned = emptyTotals();
      const meals = Object.fromEntries(MEAL_KEYS.map((m) => [m, emptyTotals()]));
      const plannedMeals = Object.fromEntries(MEAL_KEYS.map((m) => [m, emptyTotals()]));
      const counts = { eaten: 0, planned: 0 };
      for (const row of rows) {
        if (row.status === 'planned') { addTotals(planned, row.nutrients); addTotals(plannedMeals[row.meal] || (plannedMeals[row.meal] = emptyTotals()), row.nutrients); counts.planned += 1; }
        else { addTotals(eaten, row.nutrients); addTotals(meals[row.meal] || (meals[row.meal] = emptyTotals()), row.nutrients); counts.eaten += 1; }
      }
      const projected = addTotals({ ...eaten }, planned);
      const status = dailyStatus(eaten, p.targets, p.warn_fraction);
      const projectedStatus = dailyStatus(projected, p.targets, p.warn_fraction);
      const alerts = [...buildAlerts(status), ...mealCarbAlerts(meals, p.targets.carbs_per_meal_g)];
      let projectedAlerts = [];
      if (counts.planned) {
        const projectedMeals = Object.fromEntries(Object.keys(meals).map((m) => [m, addTotals({ ...meals[m] }, plannedMeals[m] || {})]));
        projectedAlerts = [...buildAlerts(projectedStatus, true), ...mealCarbAlerts(projectedMeals, p.targets.carbs_per_meal_g, true)];
      }
      return { totals: roundNutrients(eaten), planned_totals: roundNutrients(planned), projected_totals: roundNutrients(projected),
        status, projected_status: projectedStatus,
        meals: Object.fromEntries(Object.entries(meals).map(([m, v]) => [m, roundNutrients(v)])),
        planned_meals: Object.fromEntries(Object.entries(plannedMeals).map(([m, v]) => [m, roundNutrients(v)])),
        alerts, projected_alerts: projectedAlerts, counts };
    }
    _day(date) {
      const rows = this._fetchEntries({ start: date, end: date });
      const f = this._dayFigures(rows);
      return { date, entries: rows.map((r) => this._entryView(r)), totals: f.totals, planned_totals: f.planned_totals, projected_totals: f.projected_totals,
        targets: this._profileView().targets, status: f.status, projected_status: f.projected_status, meals: f.meals, planned_meals: f.planned_meals,
        alerts: f.alerts, projected_alerts: f.projected_alerts, counts: f.counts };
    }
    _dateParam(value, name) {
      if (value == null || value === '') fail(400, `${name} is required (YYYY-MM-DD)`);
      const e = validDate(value);
      if (e) fail(400, `${name}: ${e}`);
      return value;
    }
    _checkRange(start, end) {
      if (end < start) fail(400, 'end must not be before start');
      if (daysBetween(start, end) >= MAX_RANGE_DAYS) fail(400, `range too large (max ${MAX_RANGE_DAYS} days)`);
    }
    _range(start, end) {
      start = this._dateParam(start, 'start'); end = this._dateParam(end, 'end');
      this._checkRange(start, end);
      const byDate = new Map();
      for (const row of this._fetchEntries({ start, end })) { if (!byDate.has(row.date)) byDate.set(row.date, []); byDate.get(row.date).push(row); }
      const days = [];
      for (let d = start; d <= end; d = addDays(d, 1)) {
        const f = this._dayFigures(byDate.get(d) || []);
        days.push({ date: d, totals: f.totals, planned_totals: f.planned_totals, projected_totals: f.projected_totals, status: f.status,
          projected_status: f.projected_status, counts: f.counts });
      }
      return { days };
    }
    // eaten_day_totals: SQL SUM per date (only days with an eaten entry are present)
    _eatenDayTotals(start, end) {
      const groups = new Map();
      for (const e of [...this._entries].sort((a, b) => a.id - b.id)) {
        if (e.status !== 'eaten' || e.date < start || e.date > end) continue;
        if (!groups.has(e.date)) groups.set(e.date, []);
        groups.get(e.date).push(e);
      }
      const out = {};
      for (const [date, rows] of groups) out[date] = Object.fromEntries(NUTRIENT_KEYS.map((k) => [k, Number(sqliteSum(rows.map((r) => r.nutrients[k])) || 0)]));
      return out;
    }
    _summary(start, end) {
      const span = 6;
      let s, e;
      if (start == null && end == null) { e = todayStr(); s = addDays(e, -span); }
      else if (end == null) { s = this._dateParam(start, 'start'); e = addDays(s, span); }
      else if (start == null) { e = this._dateParam(end, 'end'); s = addDays(e, -span); }
      else { s = this._dateParam(start, 'start'); e = this._dateParam(end, 'end'); }
      this._checkRange(s, e);
      const p = this._profile;
      const targets = p.targets, wf = p.warn_fraction;
      let interval = null;
      if (p.dialysis === 'hemodialysis') interval = this._interdialyticInterval(e, p.dialysis_days);
      const days = daysBetween(s, e) + 1;
      let fetchFrom = addDays(s, -days);
      if (interval && interval.since < fetchFrom) fetchFrom = interval.since;
      const dayTotals = this._eatenDayTotals(fetchFrom, e);
      const val = (d, key) => { const v = Number((dayTotals[d] || {})[key] || 0); return Number.isFinite(v) ? v : 0; };
      const avg = (vals) => (vals.length ? pyFsum(vals) / vals.length : null);
      const current = [], previous = [];
      for (let d = s; d <= e; d = addDays(d, 1)) if (dayTotals[d]) current.push(d);
      for (let d = addDays(s, -days); d <= addDays(s, -1); d = addDays(d, 1)) if (dayTotals[d]) previous.push(d);
      const nutrients = {};
      for (const key of NUTRIENT_KEYS) {
        const target = summaryTarget(targets[key]);
        if (target == null) continue;
        const values = current.map((d) => [d, val(d, key)]);
        const total = values.length ? pyFsum(values.map((x) => x[1])) : 0;
        const average = avg(values.map((x) => x[1]));
        const fraction = average == null ? null : pyRound(average / target, 2);
        let maxDay = null;
        for (const v of values) if (!maxDay || v[1] > maxDay[1]) maxDay = v;
        const previousAverage = avg(previous.map((d) => val(d, key)));
        const changePct = average != null && previousAverage ? pyRound(((average - previousAverage) / previousAverage) * 100, 1) : null;
        nutrients[key] = { role: NUT[key].role, target: roundValue(key, target), total: roundValue(key, total),
          average: average == null ? null : roundValue(key, average), fraction, level: statusLevel(fraction, wf),
          days_over: values.filter((x) => x[1] > target).length,
          max_day: maxDay ? { date: maxDay[0], value: roundValue(key, maxDay[1]) } : null,
          previous_average: previousAverage == null ? null : roundValue(key, previousAverage), change_pct: changePct,
          assessment: ASSESSMENT[key] || 'weekly_average' };
      }
      let interdialytic = null;
      if (interval) {
        const nut = {};
        for (const key of INTERDIALYTIC_KEYS) {
          const target = summaryTarget(targets[key]);
          if (target == null) continue;
          const window = [];
          for (let d = interval.since; d <= interval.end; d = addDays(d, 1)) window.push(val(d, key));
          const total = pyFsum(window);
          const limit = target * interval.days;
          const fraction = pyRound(total / limit, 2);
          nut[key] = { total: roundValue(key, total), limit: roundValue(key, limit), fraction, level: statusLevel(fraction, wf) };
        }
        interdialytic = { since: interval.since, days: interval.days, next: interval.next, nutrients: nut };
      }
      const notes = [NOTE_DAILY, NOTE_WEEKLY, NOTE_CARBS];
      if (p.dialysis === 'hemodialysis') {
        if (interval) { notes.push(NOTE_INTERDIALYTIC); if (interval.capped) notes.push(NOTE_CAPPED); }
        else if (!(p.dialysis_days || []).length) notes.push(NOTE_NO_DIALYSIS_DAYS);
      }
      return { start: s, end: e, days, logged_days: current.length, nutrients, interdialytic, notes };
    }
    _interdialyticInterval(end, dialysisDays) {
      const weekdays = new Set((dialysisDays || []).map(Number).filter((d) => d >= 0 && d <= 6));
      if (!weekdays.size) return null;
      let since = null;
      for (let back = 0; back < MAX_INTERDIALYTIC_DAYS; back++) { const c = addDays(end, -back); if (weekdays.has(weekdayMon(c))) { since = c; break; } }
      const capped = since == null;
      if (since == null) since = addDays(end, -(MAX_INTERDIALYTIC_DAYS - 1));
      let next = null;
      for (let ahead = 1; ahead < 8; ahead++) { const c = addDays(end, ahead); if (weekdays.has(weekdayMon(c))) { next = c; break; } }
      return { since, end, days: daysBetween(since, end) + 1, next, capped };
    }
    _csv(start, end) {
      const s = start ? this._dateParam(start, 'start') : null;
      const e = end ? this._dateParam(end, 'end') : null;
      if (s && e && e < s) fail(400, 'end must not be before start');
      const lines = [CSV_COLUMNS.join(',')];
      for (const row of this._fetchEntries({ start: s, end: e })) {
        const values = [row.id, row.date, row.meal, row.status, row.food_id, row.food_name, pyRepr(pyRound(row.servings, 3)),
          row.grams == null ? null : pyRepr(pyRound(row.grams, 1)), row.note,
          ...NUTRIENT_KEYS.map((k) => { const v = roundValue(k, row.nutrients[k]); return v == null ? null : isIntUnit(k) ? String(v) : pyRepr(v); }),
          row.created_at, row.updated_at];
        lines.push(values.map(csvCell).join(','));
      }
      return `${lines.join('\r\n')}\r\n`;
    }
    _logBody(body, { update = false } = {}) {
      const c = new Check(body);
      if (update) { c.date('date', { required: false }); c.choice('meal', MEAL_KEYS, { nullable: true }); }
      else { c.date('date'); c.choice('meal', MEAL_KEYS, { required: true }); c.num('food_id', { required: true, ge: 1, int: true, nullable: false, maxId: true }); }
      c.num('servings', { gt: 0, le: 1000 });
      c.num('grams', { gt: 0, le: 100000 });
      c.str('note', { max: 500 });
      if (update) c.choice('status', ['eaten', 'planned'], { nullable: true }); else c.choice('status', ['eaten', 'planned'], { def: 'eaten' });
      return c.done();
    }

    // ---- saved meals (app/meals.py) ----
    _templateView(t) {
      const items = [];
      const totals = emptyTotals();
      for (const it of t.items) {
        const food = this._food(it.food_id);
        if (!food) {
          items.push({ food_id: it.food_id, food_name: 'Deleted food', servings: pyRound(it.servings, 3), serving_desc: 'unknown',
            nutrients: roundNutrients({}), kidney_rating: 'green', hidden: true });
          continue;
        }
        const scaled = scaleNutrients(food.nutrients, it.servings);
        const warnings = evaluateWarnings(scaled, food.flags, food.kidney_notes, 'in this meal');
        addTotals(totals, scaled);
        items.push({ food_id: food.id, food_name: food.name, servings: pyRound(it.servings, 3), serving_desc: food.serving_desc,
          nutrients: roundNutrients(scaled), kidney_rating: ratingFromWarnings(warnings), hidden: food.hidden });
      }
      const rank = { green: 0, yellow: 1, red: 2 };
      let worst = 'green';
      for (const it of items) if (rank[it.kidney_rating] > rank[worst]) worst = it.kidney_rating;
      return { id: t.id, name: t.name, note: t.note, items, totals: roundNutrients(totals), kidney_rating: worst, created_at: t.created_at, updated_at: t.updated_at };
    }
    _templateBody(body) {
      const c = new Check(body);
      c.str('name', { required: true, min: 1, max: 200, nullable: false });
      c.str('note', { max: 1000, def: null, emptyToNull: true });
      c.models('items', (ic) => {
        ic.num('food_id', { required: true, ge: 1, int: true, nullable: false, maxId: true });
        ic.num('servings', { required: true, gt: 0, le: 1000, nullable: false });
      }, { minLength: 1 });
      return c.done();
    }
    _insertTemplate({ name, note, items, createdAt = null }) {
      const now = createdAt || this._stamp();
      const t = { id: this._nextTemplateId++, name, note: note == null ? null : note, items: items.map((it) => ({ food_id: Number(it.food_id), servings: Number(it.servings) })),
        created_at: now, updated_at: now };
      this._templates.push(t);
      return t;
    }
    _template(id) { const t = this._templates.find((x) => x.id === Number(id)); if (!t) fail(404, `saved meal ${id} not found`); return t; }
    _shopping(start, end) {
      start = this._dateParam(start, 'start'); end = this._dateParam(end, 'end');
      this._checkRange(start, end);
      const groups = new Map();
      for (const e of [...this._entries].sort((a, b) => a.id - b.id)) {
        if (e.status !== 'planned' || e.date < start || e.date > end) continue;
        if (!groups.has(e.food_id)) groups.set(e.food_id, []);
        groups.get(e.food_id).push(e);
      }
      const items = [];
      for (const [foodId, rows] of groups) {
        const food = this._food(foodId);
        const servings = Number(sqliteSum(rows.map((r) => r.servings)));
        items.push({ food_id: foodId, food_name: food.name, serving_desc: food.serving_desc, servings: pyRound(servings, 3),
          grams: pyRound(servings * Number(food.serving_g), 1), days: new Set(rows.map((r) => r.date)).size });
      }
      items.sort((a, b) => nocaseCompare(a.food_name, b.food_name) || a.food_id - b.food_id);
      return { items };
    }

    // ---- router ----
    async request(method, path, body) {
      await new Promise((r) => setTimeout(r, 40));
      const res = this.handle(method, path, body);
      return typeof res === 'string' || res == null ? res : JSON.parse(JSON.stringify(res)); // what the wire would carry
    }
    handle(method, path, body) {
      const url = new URL(path, 'http://demo.invalid');
      const p = url.pathname;
      const q = url.searchParams;
      const qp = (k) => { const all = q.getAll(k); return all.length ? all[all.length - 1] : null; }; // Starlette: the last value wins
      let m;

      if (p === '/healthz') return { status: 'ok', foods: this._foods.filter((f) => !f.hidden).length };
      // profile
      if (p === '/api/profile' && method === 'GET') return this._profileView();
      if (p === '/api/profile' && method === 'PUT') return this._updateProfile(body);
      if (p === '/api/profile/suggested-targets' && method === 'GET') return this._suggested();

      // foods
      if (p === '/api/foods' && method === 'GET') {
        const errors = [];
        const text = qp('q') || '';
        for (const [k, max] of [['q', MAX_SEARCH_QUERY_CHARS], ['category', 100], ['source', 20]]) {
          if ((qp(k) || '').length > max) errors.push(`${k}: String should have at most ${max} characters`);
        }
        let limit = 25;
        if (qp('limit') != null) {
          limit = pydanticInt(qp('limit'));
          if (limit === undefined) errors.push('limit: Input should be a valid integer, unable to parse string as an integer');
          else if (limit < 1) errors.push('limit: Input should be greater than or equal to 1');
          else if (limit > 200) errors.push('limit: Input should be less than or equal to 200');
        }
        if (errors.length) failFields(errors);
        return { foods: this._searchFoods(text, qp('category'), qp('source'), limit) };
      }
      if (p === '/api/foods' && method === 'POST') {
        const b = this._foodBody(body);
        return this._foodView(this._food(this._insertFood({ ...b, source: 'custom' })));
      }
      if (p === '/api/foods/categories' && method === 'GET') {
        const extras = [...new Set(this._foods.filter((f) => !f.hidden && f.category).map((f) => f.category))].filter((c) => !FOOD_CATEGORIES.includes(c)).sort();
        return { categories: [...FOOD_CATEGORIES, ...extras] };
      }
      if (p === '/api/foods/usda/search' && method === 'GET') {
        if ((qp('q') || '').length > 200) failFields(['q: String should have at most 200 characters']);
        fail(503, 'USDA_API_KEY not configured');
      }
      if (p === '/api/foods/usda/import' && method === 'POST') {
        const c = new Check(body); // UsdaImport
        c.num('fdc_id', { required: true, gt: 0, int: true, nullable: false, maxId: true });
        c.done();
        fail(503, 'USDA_API_KEY not configured');
      }
      if ((m = p.match(/^\/api\/foods\/(\d+)\/copy$/)) && method === 'POST') {
        const row = this._foodOr404(m[1]);
        return this._foodView(this._food(this._insertFood({ source: 'custom', fdc_id: row.fdc_id, name: row.name, brand: row.brand, category: row.category,
          serving_desc: row.serving_desc, serving_g: row.serving_g, nutrients: { ...row.nutrients }, flags: row.flags, kidney_notes: row.kidney_notes })));
      }
      if ((m = p.match(/^\/api\/foods\/(\d+)$/))) {
        const b = method === 'PUT' ? this._foodBody(body) : null; // the body is validated before the lookup
        const row = this._foodOr404(m[1]);
        if (method === 'GET') return this._foodView(row);
        if (method === 'PUT') {
          if (row.source === 'builtin') fail(409, 'Builtin foods cannot be edited; make an editable copy with POST /api/foods/{id}/copy');
          this._updateFood(row.id, b);
          return this._foodView(row);
        }
        if (method === 'DELETE') {
          if (row.source === 'builtin') fail(409, 'Builtin foods cannot be deleted');
          if (this._foodReferenced(row.id)) { row.hidden = true; row.updated_at = this._stamp(); }
          else { this._foods.splice(this._foods.indexOf(row), 1); this._foodById.delete(row.id); }
          return null;
        }
      }

      // log
      if (p === '/api/log' && method === 'GET') {
        const date = qp('date');
        return this._day(date ? this._dateParam(date, 'date') : todayStr());
      }
      if (p === '/api/log' && method === 'POST') {
        const b = this._logBody(body);
        const food = this._foodOr404(b.food_id);
        const [servings, grams] = b.grams != null ? [b.grams / food.serving_g, b.grams] : [b.servings != null ? b.servings : 1, null];
        return this._entryView(this._insertEntry({ date: b.date, meal: b.meal, food, servings, grams, note: b.note ?? null, status: b.status }));
      }
      if (p === '/api/log/range' && method === 'GET') return this._range(qp('start'), qp('end'));
      if (p === '/api/log/summary' && method === 'GET') return this._summary(qp('start'), qp('end'));
      if (p === '/api/log/export.csv' && method === 'GET') return this._csv(qp('start'), qp('end'));
      if (p === '/api/log/quick' && method === 'POST') {
        const c = new Check(body);
        c.date('date'); c.choice('meal', MEAL_KEYS, { required: true });
        c.str('name', { required: true, min: 1, max: 200, nullable: false });
        c.str('serving_desc', { def: '1 serving', min: 1, max: 200, nullable: false });
        c.num('serving_g', { def: 100, ge: 0.1, le: 100000, nullable: false });
        c.nutrients();
        c.num('servings', { def: 1, gt: 0, le: 1000, nullable: false });
        c.flags();
        c.str('note', { max: 500, def: null });
        c.choice('status', ['eaten', 'planned'], { def: 'eaten' });
        const b = c.done();
        const food = this._food(this._insertFood({ source: 'custom', name: b.name, serving_desc: b.serving_desc, serving_g: b.serving_g, nutrients: b.nutrients, flags: b.flags }));
        return this._entryView(this._insertEntry({ date: b.date, meal: b.meal, food, servings: b.servings, grams: null, note: b.note, status: b.status }));
      }
      if (p === '/api/log/mark-eaten' && method === 'POST') {
        const c = new Check(body);
        c.date('date'); c.choice('meal', MEAL_KEYS, { nullable: true });
        const b = c.done();
        const now = this._stamp();
        let n = 0;
        for (const e of this._entries) {
          if (e.date === b.date && e.status === 'planned' && (!b.meal || e.meal === b.meal)) { e.status = 'eaten'; e.updated_at = now; n += 1; }
        }
        return { updated: n };
      }
      if (p === '/api/log/copy-day' && method === 'POST') {
        const c = new Check(body);
        c.date('from_date'); c.date('to_date');
        c.choiceList('meals', MEAL_KEYS, { nonEmpty: 'meals must not be empty; omit it to copy every meal' });
        c.choice('include', ['all', 'eaten', 'planned'], { def: 'all' });
        c.choice('status', ['eaten', 'planned'], { def: 'planned' });
        const b = c.done();
        const meals = b.meals || null;
        if (b.from_date === b.to_date) failFields(['from_date and to_date must differ']);
        let rows = this._fetchEntries({ start: b.from_date, end: b.from_date, status: b.include === 'all' ? null : b.include });
        if (meals) rows = rows.filter((r) => meals.includes(r.meal));
        if (!rows.length) fail(400, `no ${b.include === 'all' ? 'entries' : `${b.include} entries`} on ${b.from_date} to copy`);
        const created = [];
        for (const row of rows) {
          const food = this._food(row.food_id);
          if (!food) continue;
          const [servings, grams] = row.grams != null ? [row.grams / food.serving_g, row.grams] : [row.servings, null];
          created.push(this._insertEntry({ date: b.to_date, meal: row.meal, food, servings, grams, note: row.note, status: b.status }));
        }
        const entries = created.map((r) => this._entryView(r));
        return { created: entries.length, entries };
      }
      if ((m = p.match(/^\/api\/log\/(\d+)$/))) {
        const data = method === 'PUT' ? this._logBody(body, { update: true }) : null;
        const row = this._entry(m[1]);
        if (!row) fail(404, `log entry ${m[1]} not found`);
        if (method === 'DELETE') { this._entries.splice(this._entries.indexOf(row), 1); return null; }
        if (method === 'PUT') {
          const food = this._food(row.food_id);
          if (!food) fail(404, "the entry's food no longer exists");
          const date = data.date || row.date;
          const meal = data.meal || row.meal;
          const status = data.status || row.status;
          const note = 'note' in data ? data.note : row.note;
          let servings = row.servings, grams = row.grams;
          if (data.grams != null) [servings, grams] = [data.grams / food.serving_g, data.grams];
          else if (data.servings != null) [servings, grams] = [data.servings, null];
          else if ('grams' in data) grams = null;
          else if (grams != null) servings = grams / food.serving_g; // weight-based entry follows the food's serving size
          Object.assign(row, { date, meal, status, food_name: food.name, servings, grams, note, nutrients: scaleNutrients(food.nutrients, servings), updated_at: this._stamp() });
          return this._entryView(row);
        }
      }

      // saved meals
      if (p === '/api/meals' && method === 'GET') {
        return { meals: [...this._templates].sort((a, b) => nocaseCompare(a.name, b.name) || a.id - b.id).map((t) => this._templateView(t)) };
      }
      if (p === '/api/meals' && method === 'POST') {
        const b = this._templateBody(body);
        for (const it of b.items) this._foodOr404(it.food_id);
        return this._templateView(this._insertTemplate(b));
      }
      if (p === '/api/meals/from-log' && method === 'POST') {
        const c = new Check(body);
        c.date('date'); c.choice('meal', MEAL_KEYS, { required: true });
        c.str('name', { required: true, min: 1, max: 200, nullable: false });
        c.str('note', { max: 1000, def: null, emptyToNull: true });
        const b = c.done();
        const rows = this._fetchEntries({ start: b.date, end: b.date, meal: b.meal });
        if (!rows.length) fail(400, `nothing logged for ${b.meal} on ${b.date}`);
        return this._templateView(this._insertTemplate({ name: b.name, note: b.note, items: rows.map((r) => ({ food_id: r.food_id, servings: r.servings })) }));
      }
      if ((m = p.match(/^\/api\/meals\/(\d+)\/apply$/)) && method === 'POST') {
        const c = new Check(body);
        c.date('date'); c.choice('meal', MEAL_KEYS, { required: true });
        c.choice('status', ['eaten', 'planned'], { def: 'planned' });
        c.num('scale', { def: 1, gt: 0, le: 100, nullable: false });
        const b = c.done();
        const t = this._template(m[1]);
        if (!t.items.length) fail(400, 'this saved meal has no items');
        const created = [];
        for (const it of t.items) {
          const food = this._food(it.food_id);
          if (!food) fail(404, `food ${it.food_id} used by this saved meal no longer exists; edit the meal first`);
          created.push(this._insertEntry({ date: b.date, meal: b.meal, food, servings: it.servings * b.scale, grams: null, note: null, status: b.status }));
        }
        return { entries: created.map((r) => this._entryView(r)) };
      }
      if ((m = p.match(/^\/api\/meals\/(\d+)$/))) {
        const b = method === 'PUT' ? this._templateBody(body) : null;
        const t = this._template(m[1]);
        if (method === 'GET') return this._templateView(t);
        if (method === 'PUT') {
          for (const it of b.items) this._foodOr404(it.food_id);
          Object.assign(t, { name: b.name, note: b.note, items: b.items.map((it) => ({ food_id: Number(it.food_id), servings: Number(it.servings) })), updated_at: this._stamp() });
          return this._templateView(t);
        }
        if (method === 'DELETE') { this._templates.splice(this._templates.indexOf(t), 1); return null; }
      }
      if (p === '/api/plan/shopping' && method === 'GET') return this._shopping(qp('start'), qp('end'));
      fail(404, 'Not Found');
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Sample data for the demo: "Sam", CKD stage 4, type 1 diabetes, 70 kg, 170 cm. About 30
  // days of renal-diet meals built from real foods in the database, a few higher days, two
  // hypo treatments, three empty days, today partly eaten with dinner planned, three days
  // ahead planned and three saved meals. Fixed seed: the same plan on every load.
  // ---------------------------------------------------------------------------
  function seedSampleData(api, { hemodialysis = false } = {}) {
    let seed = 0x5eed2610;
    const rnd = () => { // mulberry32
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const pick = (list) => list[Math.floor(rnd() * list.length)];
    // Foods by USDA FDC id, with a name fallback for the 24-food ?mock=1 list.
    const FOODS = {
      apple: [171688, /^apple, raw/i], blueberries: [171711, /^blueberries/i], strawberries: [167762, /^strawberries/i], grapes: [174683, /^grapes/i],
      applesauce: [171695, /^applesauce/i], pineapple: [169126, /^pineapple, canned/i], pears: [169936, /^pears, canned/i],
      rice: [168878, /^rice, white/i], bread: [174924, /^bread, white/i], pasta: [169737, /^pasta, cooked/i], creamOfWheat: [171657, /^cream of wheat/i],
      englishMuffin: [175063, /^english muffin, plain/i], riceCakes: [170250, /^rice cakes/i], riceMilk: [171942, /^rice milk/i],
      saltines: [172746, /^saltine/i], popcorn: [167959, /^popcorn, air/i], vanillaWafers: [174974, /^vanilla wafers/i], sugarCookies: [174971, /^cookies, sugar/i],
      chicken: [171477, /^chicken breast, roasted/i], turkey: [171496, /^turkey breast, roasted/i], cod: [171956, /^cod/i], eggWhite: [172183, /^egg white/i],
      greenBeans: [169141, /^green beans/i], cauliflower: [170397, /^cauliflower, boiled/i], cabbage: [169976, /^cabbage, boiled/i], cucumber: [168409, /^cucumber/i],
      lettuce: [169248, /^lettuce, iceberg/i], redPepper: [170108, /^bell pepper, red/i], onion: [170000, /^onion, raw/i], carrots: [170394, /^carrots, boiled/i],
      butter: [173430, /^butter, unsalted/i], creamCheese: [173418, /^cream cheese/i], oliveOil: [171413, /^olive oil/i], mayonnaise: [171009, /^mayonnaise/i],
      jam: [169641, /^jam/i], brownSugar: [168833, /^sugar, brown/i], salt: [173468, /^salt, table/i],
      coffee: [171890, /^coffee, brewed/i], water: [173647, /^water, tap/i], tea: [173227, /^tea, black/i],
      banana: [173944, /^banana/i], potato: [170093, /^potato, baked/i], deliTurkey: [172941, /^deli turkey/i], cola: [174852, /^cola, regular/i],
      orangeJuice: [169098, /^orange juice/i], cheeseburger: [170691, /^cheeseburger/i], fries: [170698, /^french fries, fast food/i], soup: [172909, /^soup, chicken noodle/i], pretzels: [167555, /^pretzels/i],
      glucose: [-10, /^glucose tablet/i],
    };
    const food = (key) => {
      const [fdc, re] = FOODS[key];
      return api._foods.find((f) => f.source === 'builtin' && f.fdc_id === fdc) || api._foods.find((f) => re.test(f.name)) || null;
    };
    const today = todayStr();
    const now = Date.now();
    const at = (date, hhmm) => { const d = parseDate(date); d.setHours(Math.floor(hhmm), Math.round((hhmm % 1) * 100), 0, 0); return d.getTime(); };
    const TIMES = { breakfast: 7.45, lunch: 12.3, dinner: 18.4, snack: 15.3 };
    const items = []; // [time, date, meal, key, servings, status, note]
    const add = (date, meal, list, { status = 'eaten', when = null, note = null } = {}) => {
      list.forEach(([key, servings, itemNote], i) => items.push([(when || at(date, TIMES[meal])) + i * 60000 + items.length, date, meal, key, servings, status, itemNote || (i === 0 ? note : null)]));
    };
    // A CKD stage 4 renal plate: small protein portions, white rice / pasta / bread, low-potassium
    // fruit and vegetables, unsalted butter and oil for energy, a pinch of salt when cooking.
    const BREAKFASTS = [
      [['eggWhite', 2], ['bread', 2], ['butter', 1], ['jam', 1], ['blueberries', 1], ['coffee', 1]],
      [['creamOfWheat', 1], ['riceMilk', 0.5], ['brownSugar', 1], ['strawberries', 1], ['coffee', 1]],
      [['englishMuffin', 1], ['creamCheese', 1], ['jam', 1], ['applesauce', 1], ['tea', 1]],
      [['eggWhite', 3], ['bread', 2], ['butter', 1], ['pears', 1], ['coffee', 1]],
    ];
    const LUNCHES = [
      [['chicken', 0.5], ['rice', 1], ['greenBeans', 1], ['oliveOil', 1], ['salt', 0.25], ['water', 1]],
      [['bread', 2], ['turkey', 0.5], ['mayonnaise', 1], ['lettuce', 0.5], ['cucumber', 1], ['apple', 1], ['water', 1]],
      [['pasta', 1], ['chicken', 0.5], ['redPepper', 1], ['onion', 0.5], ['oliveOil', 1], ['salt', 0.25], ['water', 1]],
    ];
    const DINNERS = [
      [['cod', 0.75], ['rice', 1], ['cauliflower', 2], ['butter', 1], ['salt', 0.5], ['water', 1]],
      [['chicken', 0.75], ['pasta', 1], ['cabbage', 1], ['oliveOil', 1], ['salt', 0.25], ['water', 1]],
      [['turkey', 0.75], ['rice', 1], ['greenBeans', 1], ['carrots', 1], ['butter', 1], ['salt', 0.25]],
      [['eggWhite', 3], ['bread', 1], ['cauliflower', 2], ['redPepper', 1], ['oliveOil', 1], ['salt', 0.5]],
    ];
    const SNACKS = [[['apple', 1]], [['riceCakes', 1], ['jam', 1]], [['grapes', 1]], [['pineapple', 1]], [['vanillaWafers', 1]],
      [['popcorn', 1]], [['sugarCookies', 1], ['coffee', 1]], [['saltines', 1], ['pears', 1]]];
    // Days (counted back from today) that differ from the usual plan.
    const EMPTY = new Set([9, 16, 23]);
    const SPECIAL = {
      2: { lunch: [['bread', 2], ['deliTurkey', 1.5], ['mayonnaise', 1], ['lettuce', 0.5], ['apple', 1], ['water', 1]],
        dinner: [['soup', 1], ['saltines', 1], ['chicken', 0.5], ['cucumber', 1], ['water', 1]] },
      4: { hypo: 'Hypo 3.5 mmol/L before dinner; 5.8 after 15 minutes' },
      5: { lunch: [['cheeseburger', 1], ['cola', 1, 'lunch out']] },
      7: { breakfast: [['banana', 1], ['creamOfWheat', 1], ['riceMilk', 0.5], ['coffee', 1]],
        dinner: [['chicken', 0.75], ['potato', 1], ['butter', 1], ['greenBeans', 1], ['water', 1]] },
      11: { dinner: [['cod', 0.75], ['potato', 1], ['butter', 1], ['cauliflower', 2], ['water', 1]] },
      13: { dinner: [['cheeseburger', 1], ['fries', 1], ['cola', 1, 'takeaway']], hypo: 'Hypo 3.7 mmol/L mid-morning; 5.4 after 15 minutes' },
      18: { lunch: [['bread', 2], ['deliTurkey', 1.5], ['mayonnaise', 1], ['lettuce', 0.5], ['water', 1]], snack: [['cola', 1], ['pretzels', 1]] },
      21: { breakfast: [['banana', 1], ['bread', 2], ['butter', 1], ['orangeJuice', 1], ['coffee', 1]],
        dinner: [['turkey', 0.75], ['potato', 1.5, 'big one'], ['butter', 1], ['cabbage', 1], ['water', 1]] },
      26: { lunch: [['cheeseburger', 1], ['water', 1]] },
      28: { lunch: [['bread', 2], ['deliTurkey', 1], ['mayonnaise', 1], ['cucumber', 1], ['water', 1]], snack: [['banana', 1]] },
    };
    for (let back = 30; back >= 1; back--) {
      const date = addDays(today, -back);
      const breakfast = pick(BREAKFASTS), lunch = pick(LUNCHES), dinner = pick(DINNERS);
      const snackCount = rnd() < 0.4 ? 2 : 1;
      const snacks = []; for (let i = 0; i < snackCount; i++) snacks.push(...pick(SNACKS));
      const extraWater = rnd() < 0.5;
      if (EMPTY.has(back)) continue;
      const sp = SPECIAL[back] || {};
      add(date, 'breakfast', sp.breakfast || breakfast);
      add(date, 'lunch', sp.lunch || lunch);
      add(date, 'dinner', sp.dinner || dinner);
      add(date, 'snack', sp.snack || snacks);
      if (extraWater) add(date, 'snack', [['water', 1]], { when: at(date, 20.15) });
      if (sp.hypo) add(date, 'snack', [['glucose', 4]], { when: at(date, back === 4 ? 17.5 : 10.4), note: sp.hypo });
    }
    // Today: breakfast and a bigger lunch eaten, an afternoon snack; dinner and an evening snack planned.
    add(today, 'breakfast', BREAKFASTS[0]);
    add(today, 'lunch', [['chicken', 1], ['rice', 1], ['greenBeans', 1], ['oliveOil', 1], ['water', 1]]);
    add(today, 'snack', [['apple', 1], ['water', 1]]);
    const planNight = at(addDays(today, -1), 20.3);
    add(today, 'dinner', [['cod', 0.75], ['rice', 1], ['cauliflower', 2], ['butter', 1], ['strawberries', 1], ['water', 1]], { status: 'planned', when: planNight });
    add(today, 'snack', [['riceCakes', 1, 'evening'], ['jam', 1]], { status: 'planned', when: planNight + 600000 });
    // Three days ahead, planned this morning.
    const planMorning = at(today, 7.15);
    const ahead = [
      { breakfast: BREAKFASTS[1], lunch: LUNCHES[0], dinner: DINNERS[2], snack: [['grapes', 1]] },
      { breakfast: BREAKFASTS[0], lunch: LUNCHES[1], dinner: DINNERS[1], snack: [['vanillaWafers', 1]] },
      { breakfast: BREAKFASTS[3], dinner: DINNERS[0] },
    ];
    ahead.forEach((plan, i) => {
      const date = addDays(today, i + 1);
      for (const meal of MEAL_KEYS) if (plan[meal]) add(date, meal, plan[meal], { status: 'planned', when: planMorning + (i * 4 + MEAL_KEYS.indexOf(meal)) * 120000 });
    });
    // Insert in time order (ids follow created_at, as on the server); nothing is stamped in the future.
    items.sort((a, b) => a[0] - b[0]);
    let last = 0;
    const cap = now - 5 * 60000;
    for (const [time, date, meal, key, servings, status, note] of items) {
      const f = food(key);
      if (!f) continue;
      const t = Math.max(Math.min(time, cap), last + 1);
      last = t;
      api._insertEntry({ date, meal, food: f, servings, grams: null, note, status, createdAt: api._stamp(new Date(t)) });
    }
    // Saved meals.
    const tplAt = api._stamp(new Date(at(addDays(today, -20), 21)));
    const tpl = (name, note, list) => {
      const its = list.map(([key, servings]) => { const f = food(key); return f ? { food_id: f.id, servings } : null; }).filter(Boolean);
      if (its.length) api._insertTemplate({ name, note, items: its, createdAt: tplAt });
    };
    tpl('Usual breakfast', 'Weekday default', BREAKFASTS[0]);
    tpl('Chicken & rice lunch', null, [['chicken', 0.5], ['rice', 1], ['greenBeans', 1], ['oliveOil', 1], ['water', 1]]);
    tpl('Hypo kit: glucose tablets', '4 tablets = 16 g fast carbohydrate with no potassium. Recheck in 15 minutes.', [['glucose', 4]]);
    // Profile: targets are what the suggestion gives for this person.
    const profile = hemodialysis
      ? { name: 'Sam', weight_kg: 70, height_cm: 170, ckd_stage: '5', dialysis: 'hemodialysis', diabetes: 'type1', warn_fraction: 0.8, dialysis_days: [0, 2, 4], week_start: 'monday' }
      : { name: 'Sam', weight_kg: 70, height_cm: 170, ckd_stage: '4', dialysis: 'none', diabetes: 'type1', warn_fraction: 0.8, dialysis_days: [], week_start: 'monday' };
    api._updateProfile(profile);
    api._updateProfile({ targets: api._suggested().targets });
  }

  // ---------------------------------------------------------------------------
  // API layer
  // ---------------------------------------------------------------------------
  // The preview build embeds data/foods.json in a JSON script element with id "kdl-foods".
  function embeddedFoods() {
    const el = document.getElementById('kdl-foods');
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }
  const mock = MOCK ? new MockApi({ foodsData: embeddedFoods(), hemodialysis: MOCK_HD }) : null;
  if (mock) { // hooks for verification scripts; absent in the installed app
    window.__kdlMock = mock;
    window.__kdlEvaluateWarnings = evaluateWarnings;
  }

  function errorDetail(data, res) {
    const d = data && data.detail;
    if (Array.isArray(d)) return d.map((x) => (x && x.msg ? `${(x.loc || []).slice(-1)[0] || ''}: ${x.msg}` : JSON.stringify(x))).join('; ');
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object') return JSON.stringify(d);
    return res ? `${res.status} ${res.statusText || 'error'}` : 'Request failed';
  }
  async function request(method, path, body) {
    if (mock) return mock.request(method, path, body);
    let res;
    try {
      res = await fetch(path, {
        method,
        headers: body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: 'same-origin',
      });
    } catch (e) {
      const err = new Error('Cannot reach the server. Check your connection.');
      err.status = 0; err.detail = err.message; throw err;
    }
    // Read even an empty 204 body: an unread one is reported as net::ERR_ABORTED in DevTools.
    if (res.status === 204) { try { await res.text(); } catch (e) { /* nothing to read */ } return null; }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text.slice(0, 200) }; }
    if (!res.ok) {
      const err = new Error(errorDetail(data, res));
      err.status = res.status; err.detail = err.message; err.data = data;
      throw err;
    }
    return data;
  }
  const api = {
    profile: () => request('GET', '/api/profile'),
    saveProfile: (b) => request('PUT', '/api/profile', b),
    suggested: () => request('GET', '/api/profile/suggested-targets'),
    foods: (params) => request('GET', '/api/foods?' + qs(params)),
    categories: () => request('GET', '/api/foods/categories'),
    food: (id) => request('GET', `/api/foods/${id}`),
    deleteFood: (id) => request('DELETE', `/api/foods/${id}`),
    usdaSearch: (q) => request('GET', '/api/foods/usda/search?' + qs({ q })),
    usdaImport: (fdc_id) => request('POST', '/api/foods/usda/import', { fdc_id }),
    day: (date) => request('GET', '/api/log?' + qs({ date })),
    addEntry: (b) => request('POST', '/api/log', b),
    updateEntry: (id, b) => request('PUT', `/api/log/${id}`, b),
    deleteEntry: (id) => request('DELETE', `/api/log/${id}`),
    quick: (b) => request('POST', '/api/log/quick', b),
    range: (start, end) => request('GET', '/api/log/range?' + qs({ start, end })),
    summary: (start, end) => request('GET', '/api/log/summary?' + qs({ start, end })),
    markEaten: (b) => request('POST', '/api/log/mark-eaten', b),
    copyDay: (b) => request('POST', '/api/log/copy-day', b),
    exportUrl: (start, end) => '/api/log/export.csv?' + qs({ start, end }),
    meals: () => request('GET', '/api/meals'),
    createMeal: (b) => request('POST', '/api/meals', b),
    updateMeal: (id, b) => request('PUT', `/api/meals/${id}`, b),
    deleteMeal: (id) => request('DELETE', `/api/meals/${id}`),
    mealFromLog: (b) => request('POST', '/api/meals/from-log', b),
    applyMeal: (id, b) => request('POST', `/api/meals/${id}/apply`, b),
    shopping: (start, end) => request('GET', '/api/plan/shopping?' + qs({ start, end })),
  };

  // ---------------------------------------------------------------------------
  // State & toast
  // ---------------------------------------------------------------------------
  const state = {
    view: 'today',
    date: todayStr(),
    profile: null,
    day: null,
    dayLoadedFor: null,
    categories: [],
    category: '',
    query: '',
    trendsDays: 14,
    trends: null,
    summary: null,
    addMealHint: null,
    addStatusHint: null,
    lastFocus: null,
    meals: null,          // saved meals cache (MealTemplate[])
    planStart: null,      // first day of the visible Plan week
    plan: null,           // { start, end, days: [...] }
    shopping: null,       // { start, end, items: [...] }
    targetsStale: null,   // { from, to } profiles: stage/dialysis changed since the targets were set
  };

  const toastEl = $('#toast');
  let toastTimer = null;
  function toast(message, type = '') {
    toastEl.textContent = message;
    toastEl.className = `toast show ${type}`.trim();
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), type === 'error' ? 6000 : 3200);
  }
  function toastError(err) {
    console.error(err);
    toast(err && (err.detail || err.message) ? String(err.detail || err.message) : 'Something went wrong', 'error');
  }

  // ---------------------------------------------------------------------------
  // Theme
  // ---------------------------------------------------------------------------
  const root = document.documentElement;
  function storedTheme() { try { return localStorage.getItem(THEME_KEY) || 'auto'; } catch (e) { return 'auto'; } }
  // A page that embeds this one (the preview's host) may set data-theme itself; with no stored
  // choice of ours, "Match device" keeps that value instead of removing it.
  const HOST_THEME = (() => {
    const t = root.getAttribute('data-theme');
    return storedTheme() === 'auto' && (t === 'light' || t === 'dark') ? t : null;
  })();
  function effectiveTheme() {
    const t = root.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function syncThemeControls(mode) {
    const eff = effectiveTheme();
    $('#theme-toggle').setAttribute('aria-label', eff === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    const sel = $('#pf-theme'); if (sel && mode) sel.value = mode;
    $$('meta[name="theme-color"]').forEach((mtag) => mtag.setAttribute('content', eff === 'dark' ? '#111417' : '#f4f5f7'));
  }
  function applyTheme(mode) {
    if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
    else if (HOST_THEME) root.setAttribute('data-theme', HOST_THEME);
    else root.removeAttribute('data-theme');
    try { if (mode === 'auto') localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, mode); } catch (e) { /* storage unavailable */ }
    syncThemeControls(mode);
  }
  $('#theme-toggle').addEventListener('click', () => applyTheme(effectiveTheme() === 'dark' ? 'light' : 'dark'));
  $('#pf-theme').addEventListener('change', (e) => applyTheme(e.target.value));
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onScheme = () => syncThemeControls(null);
    if (mq.addEventListener) mq.addEventListener('change', onScheme); else if (mq.addListener) mq.addListener(onScheme);
  }
  // Keep the toggle's label right when the host switches data-theme while the page is open.
  if (window.MutationObserver) new MutationObserver(() => syncThemeControls(null)).observe(root, { attributes: true, attributeFilter: ['data-theme'] });

  // ---------------------------------------------------------------------------
  // Tabs / views
  // ---------------------------------------------------------------------------
  const VIEWS = ['today', 'add', 'plan', 'trends', 'profile'];
  function showView(name, { focusTab = false } = {}) {
    if (!VIEWS.includes(name)) name = 'today';
    state.view = name;
    for (const v of VIEWS) {
      const panel = $(`#view-${v}`);
      const tab = $(`#tab-${v}`);
      const active = v === name;
      panel.hidden = !active;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    }
    if (focusTab) $(`#tab-${name}`).focus();
    try { if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`); } catch (e) { /* sandboxed frame: the view still switches */ }
    window.scrollTo({ top: 0 });
    if (name === 'today') loadDay();
    else if (name === 'add') initAdd();
    else if (name === 'plan') loadPlan();
    else if (name === 'trends') loadTrends();
    else if (name === 'profile') loadProfile().then(renderProfile).catch(toastError);
  }
  // Open a given date in the Today view (used by the Plan grid and the week strip).
  function openDay(date) {
    state.date = date;
    showView('today');
  }
  $$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => showView(tab.dataset.view));
    tab.addEventListener('keydown', (e) => {
      const i = VIEWS.indexOf(tab.dataset.view);
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const next = VIEWS[(i + (e.key === 'ArrowRight' ? 1 : VIEWS.length - 1)) % VIEWS.length];
        showView(next, { focusTab: true });
      } else if (e.key === 'Home') { e.preventDefault(); showView(VIEWS[0], { focusTab: true }); }
      else if (e.key === 'End') { e.preventDefault(); showView(VIEWS[VIEWS.length - 1], { focusTab: true }); }
    });
  });
  window.addEventListener('hashchange', () => {
    const name = location.hash.replace('#', '');
    if (VIEWS.includes(name) && name !== state.view) showView(name);
  });

  // ---------------------------------------------------------------------------
  // Profile loading (shared)
  // ---------------------------------------------------------------------------
  async function loadProfile(force = false) {
    if (state.profile && !force) return state.profile;
    state.profile = await api.profile();
    return state.profile;
  }

  // ---------------------------------------------------------------------------
  // TODAY view
  // ---------------------------------------------------------------------------
  const dateInput = $('#date-input');
  const dateLabel = $('#date-label');
  const alertsEl = $('#alerts');
  const statusBarsEl = $('#status-bars');
  const mealsEl = $('#meals');
  const totalsAllEl = $('#totals-all');
  const backToToday = $('#date-today');

  function setDate(d) {
    state.date = d;
    dateInput.value = d;
    dateLabel.textContent = fmtDateLong(d);
    backToToday.hidden = d === todayStr();
    loadDay();
  }
  $('#date-prev').addEventListener('click', () => setDate(addDays(state.date, -1)));
  $('#date-next').addEventListener('click', () => setDate(addDays(state.date, 1)));
  backToToday.addEventListener('click', () => setDate(todayStr()));
  dateInput.addEventListener('change', () => { if (/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) setDate(dateInput.value); });

  let dayRequest = 0;
  async function loadDay() {
    const reqId = ++dayRequest;
    dateInput.value = state.date;
    dateLabel.textContent = fmtDateLong(state.date);
    backToToday.hidden = state.date === todayStr();
    if (state.dayLoadedFor !== state.date) mealsEl.style.opacity = '0.6';
    loadWeekStrip();
    try {
      const day = await api.day(state.date);
      if (reqId !== dayRequest) return;
      state.day = day;
      state.dayLoadedFor = state.date;
      renderToday();
    } catch (e) {
      if (reqId === dayRequest) toastError(e);
    } finally {
      mealsEl.style.opacity = '';
    }
  }

  function isPlanned(e) { return e.status === 'planned'; }

  function renderToday() {
    const day = state.day;
    if (!day) return;
    const counts = day.counts || { eaten: (day.entries || []).filter((e) => !isPlanned(e)).length, planned: (day.entries || []).filter(isPlanned).length };
    // Alerts (eaten)
    clear(alertsEl);
    for (const a of day.alerts || []) {
      const lvl = a.level === 'over' ? 'over' : 'caution';
      alertsEl.append(h('div', { class: `alert level-${lvl}` },
        ratingIcon(lvl, { label: lvl === 'over' ? 'Over limit' : 'Near limit' }),
        h('div', {}, h('b', {}, lvl === 'over' ? 'Over limit. ' : 'Near limit. '), a.message)));
    }
    // Projected alerts: only worth showing when something is planned and the level differs from the eaten alert.
    const projEl = $('#projected-alerts');
    clear(projEl);
    if (counts.planned > 0) {
      // A day alert and a per-meal carbohydrate alert share the nutrient key; the meal tells them apart.
      const alertKey = (a) => `${a.nutrient}|${a.meal || ''}`;
      const eatenLevel = Object.fromEntries((day.alerts || []).map((a) => [alertKey(a), a.level]));
      const shown = (day.projected_alerts || []).filter((a) => eatenLevel[alertKey(a)] !== a.level);
      if (shown.length) {
        projEl.append(h('div', { class: 'alerts-title' }, dashedIcon(), 'If you eat what\'s planned…'));
        for (const a of shown) {
          const lvl = a.level === 'over' ? 'over' : 'caution';
          // The heading already says "If you eat what's planned"; do not read the phrase twice per line.
          const text = String(a.message || '').replace(/^If you eat what's planned,\s*/i, '');
          const message = text ? text.charAt(0).toUpperCase() + text.slice(1) : a.message;
          projEl.append(h('div', { class: `alert projected level-${lvl}` },
            ratingIcon(lvl, { label: lvl === 'over' ? 'Projected over limit' : 'Projected near limit' }),
            h('div', {}, h('b', {}, lvl === 'over' ? 'Projected over. ' : 'Projected near limit. '), message)));
        }
      }
    }
    // Status bars
    clear(statusBarsEl);
    const keys = Object.keys(day.status || {}).sort((a, b) => STATUS_ORDER.indexOf(a) - STATUS_ORDER.indexOf(b));
    if (!keys.length) {
      statusBarsEl.append(h('p', { class: 'empty-state' }, 'No targets set yet. ',
        h('button', { class: 'link-btn', type: 'button', onclick: () => showView('profile') }, 'Set your weight and targets in Profile')));
    }
    for (const key of keys) statusBarsEl.append(statusBar(key, day.status[key], counts.planned > 0 && day.projected_status ? day.projected_status[key] : null));
    const statusSub = $('#status-heading').nextElementSibling;
    if (statusSub) statusSub.textContent = counts.planned > 0 ? 'eaten / target · lighter part = planned' : 'running total / target';

    // Meals
    clear(mealsEl);
    const perMeal = day.targets && typeof day.targets.carbs_per_meal_g === 'number' ? day.targets.carbs_per_meal_g : null;
    const wf = (state.profile && state.profile.warn_fraction) || 0.8;
    for (const meal of MEALS) {
      const entries = (day.entries || []).filter((e) => e.meal === meal.key);
      const eatenEntries = entries.filter((e) => !isPlanned(e));
      const plannedEntries = entries.filter(isPlanned);
      const mt = (day.meals && day.meals[meal.key]) || null;
      const pmt = (day.planned_meals && day.planned_meals[meal.key]) || null;
      const carbs = mt ? mt.carbs_g || 0 : eatenEntries.reduce((a, e) => a + (e.nutrients.carbs_g || 0), 0);
      const plannedCarbs = pmt ? pmt.carbs_g || 0 : plannedEntries.reduce((a, e) => a + (e.nutrients.carbs_g || 0), 0);
      const over = perMeal != null && carbs > perMeal;
      const near = perMeal != null && !over && carbs >= perMeal * wf;
      const carbsEl = h('span', { class: `meal-carbs${over ? ' over' : ''}`, 'aria-label': `Carbohydrate eaten ${fmtNum(carbs, 'carbs_g')} grams${perMeal != null ? ` of ${perMeal} gram meal target` : ''}` },
        over ? ratingIcon('over', { label: 'Over meal carbohydrate target' }) : near ? ratingIcon('caution', { label: 'Near meal carbohydrate target' }) : null,
        `Carbs: ${fmtNum(carbs, 'carbs_g')} g`,
        perMeal != null ? h('span', { class: 'of' }, ` of ${perMeal} g`) : null);
      const headRight = h('div', { class: 'meal-head-right' }, carbsEl);
      if (plannedEntries.length) {
        const projOver = perMeal != null && carbs + plannedCarbs > perMeal;
        headRight.append(h('span', { class: `meal-planned-carbs${projOver ? ' over' : ''}`, 'aria-label': `Planned: ${fmtNum(plannedCarbs, 'carbs_g')} more grams of carbohydrate` },
          `Planned: +${fmtNum(plannedCarbs, 'carbs_g')} g carbs`, projOver ? ` (${fmtNum(carbs + plannedCarbs, 'carbs_g')} g total)` : ''));
      }
      const card = h('section', { class: 'card meal', 'aria-labelledby': `meal-h-${meal.key}` },
        h('div', { class: 'meal-head' }, h('h2', { class: 'meal-name', id: `meal-h-${meal.key}` }, meal.label), headRight));
      if (!entries.length) {
        card.append(h('p', { class: 'empty-state' }, 'Nothing logged.'));
      } else {
        const ul = h('ul', { class: 'list' });
        for (const e of entries) ul.append(isPlanned(e) ? h('li', { class: 'entry-planned' }, entryRow(e), eatenButton(e)) : h('li', {}, entryRow(e)));
        card.append(ul);
      }
      const foot = h('div', { class: 'meal-foot' });
      if (mt && eatenEntries.length) {
        foot.append(h('span', { class: 'tabular meal-sum' }, `Protein ${fmtNum(mt.protein_g, 'protein_g')} g · K ${fmtNum(mt.potassium_mg, 'potassium_mg')} · P ${fmtNum(mt.phosphorus_mg, 'phosphorus_mg')} · Na ${fmtNum(mt.sodium_mg, 'sodium_mg')} mg`));
      }
      if (pmt && plannedEntries.length) {
        foot.append(h('span', { class: 'tabular meal-sum planned' }, `Planned: +${fmtNum(pmt.protein_g, 'protein_g')} g protein · K +${fmtNum(pmt.potassium_mg, 'potassium_mg')} · P +${fmtNum(pmt.phosphorus_mg, 'phosphorus_mg')} · Na +${fmtNum(pmt.sodium_mg, 'sodium_mg')} mg`));
      }
      card.append(foot);
      const actions = h('div', { class: 'meal-actions' });
      actions.append(h('button', { class: 'link-btn meal-add', type: 'button', onclick: () => { state.addMealHint = meal.key; state.addStatusHint = null; showView('add'); $('#food-search').focus(); } },
        plusIcon(), `Add to ${meal.label.toLowerCase()}`));
      actions.append(h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openApplySheet({ date: day.date, meal: meal.key, trigger: ev.currentTarget }) }, 'Add saved meal'));
      if (plannedEntries.length) {
        actions.append(h('button', { class: 'link-btn', type: 'button', onclick: (ev) => markAllEaten(day.date, meal.key, ev.currentTarget) },
          checkIcon(), plannedEntries.length === 1 ? 'Mark eaten' : 'Mark all eaten'));
      }
      if (entries.length) {
        actions.append(h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openSaveMealSheet(day.date, meal.key, entries, ev.currentTarget) }, 'Save as meal'));
      }
      card.append(actions);
      mealsEl.append(card);
    }
    // All totals
    clear(totalsAllEl);
    for (const n of NUTRIENTS) {
      const eatenV = day.totals ? day.totals[n.key] : null;
      const projV = day.projected_totals ? day.projected_totals[n.key] : null;
      totalsAllEl.append(h('div', { class: 'ng' }, h('span', {}, n.label), h('b', {}, fmtWithUnit(eatenV, n.key),
        counts.planned > 0 && projV != null && projV !== eatenV ? h('span', { class: 'ng-proj' }, ` → ${fmtNum(projV, n.key)}`) : null)));
    }
    $('#totals-details > summary').textContent = counts.planned > 0 ? 'All nutrient totals for the day (eaten → projected)' : 'All nutrient totals for the day';
  }

  function dashedIcon() {
    return s('svg', { class: 'rating dashed', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('circle', { cx: 12, cy: 12, r: 9.5, fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'stroke-dasharray': '3.5 3' }));
  }
  function checkIcon() {
    return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { d: 'M5 12.5l4.5 4.5L19 7.5', fill: 'none', stroke: 'currentColor', 'stroke-width': 2.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
  }

  function statusBar(key, st, pst) {
    const n = NUT[key] || { label: key, unit: '' };
    const level = st.level || 'ok';
    const p = pct(st.fraction);
    const hasMin = st.min != null;
    const targetText = hasMin ? `${fmtNum(st.min, key)}–${fmtNum(st.target, key)}` : fmtNum(st.target, key);
    // Same word as the server's alerts: goal (calories, carbohydrate), maximum (ranges, info), limit.
    const isGoal = n.role === 'goal' || n.role === 'track';
    const levelWord = (lv) => (lv === 'over' && hasMin ? 'Over max' : lv === 'over' && isGoal ? 'Over goal' : lv === 'caution' && isGoal ? 'Near goal' : LEVEL_TEXT[lv]);
    const levelText = levelWord(level);
    const hasProj = pst && pst.value != null && pst.value > (st.value || 0);
    const pp = hasProj ? pct(pst.fraction) : p;
    const projLevel = hasProj ? pst.level || 'ok' : level;
    const wrap = h('div', { class: `stat level-${level}${hasMin ? ' has-min' : ''}${hasProj ? ' has-proj' : ''}` },
      h('div', { class: 'stat-label' }, n.label, levelPill(level, levelText)),
      h('div', { class: 'stat-value' }, h('b', {}, fmtNum(st.value, key)), ` / ${targetText} ${n.unit}`,
        hasProj ? h('span', { class: `stat-proj-value level-${projLevel}` }, ` → ${fmtNum(pst.value, key)}`) : null));
    const ariaProj = hasProj ? `, projected ${fmtNum(pst.value, key)} ${n.unit} (${pp} percent, ${levelWord(projLevel)}) with planned foods` : '';
    const track = h('div', { class: 'stat-track', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': st.target, 'aria-valuenow': st.value,
      'aria-label': `${n.label}: ${fmtNum(st.value, key)} of ${targetText} ${n.unit}, ${p} percent, ${levelText}${ariaProj}` });
    if (hasProj) {
      const left = Math.max(0, Math.min(100, p)), right = Math.max(0, Math.min(100, pp));
      track.append(h('div', { class: `stat-fill-proj level-${projLevel}`, style: `left:${left}%;width:${Math.max(0, right - left)}%` }));
      track.append(h('div', { class: `stat-proj-marker level-${projLevel}`, style: `left:${right}%`, title: `Projected ${fmtNum(pst.value, key)} ${n.unit}` }));
    }
    track.append(h('div', { class: `stat-fill${st.value ? '' : ' empty'}`, style: `width:${Math.max(0, Math.min(100, p))}%` }));
    if (hasMin && st.target) track.append(h('div', { class: 'stat-min', style: `left:${Math.min(100, (st.min / st.target) * 100).toFixed(1)}%`, title: `Minimum ${fmtNum(st.min, key)} ${n.unit}` }));
    wrap.append(track);
    const foot = [`${p} % of ${hasMin ? 'maximum' : ROLE_WORD[n.role] || 'limit'}`];
    if (hasMin && st.value < st.min) foot.push(`below the ${fmtNum(st.min, key)} ${n.unit} minimum so far`);
    if (st.fraction > 1) foot.push(`${fmtNum(st.value - st.target, key)} ${n.unit} over`);
    else foot.push(`${fmtNum(st.target - st.value, key)} ${n.unit} left`);
    if (hasProj) foot.push(`${pp} % with planned`);
    wrap.append(h('div', { class: 'stat-foot' }, foot.join(' · ')));
    return wrap;
  }

  function entryRow(e) {
    const planned = isPlanned(e);
    const amount = e.grams != null ? `${fmtNum(e.grams, 'fluid_ml')} g (${fmtServings(e.servings)})` : fmtServings(e.servings);
    const nums = h('div', { class: 'row-nums' });
    for (const k of ROW_NUMBERS) {
      nums.append(h('span', { class: 'n' }, `${NUT[k].short} `, h('b', {}, fmtNum(e.nutrients[k], k)), ` ${NUT[k].unit}`));
    }
    const btn = h('button', { class: `row-btn${planned ? ' planned' : ''}`, type: 'button', 'aria-label': `Edit ${planned ? 'planned ' : ''}${e.food_name}, ${amount}` },
      ratingIcon(e.kidney_rating),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, e.food_name, planned ? h('span', { class: 'badge planned' }, 'planned') : null),
        h('div', { class: 'row-sub' }, h('span', { class: 'entry-servings' }, amount), e.note ? h('span', { class: 'entry-note' }, ` · ${e.note}`) : null)),
      nums);
    btn.addEventListener('click', () => openEntrySheet('edit', { entry: e, trigger: btn }));
    return btn;
  }
  function eatenButton(e) {
    const b = h('button', { class: 'btn secondary eaten-btn', type: 'button', 'aria-label': `Mark ${e.food_name} as eaten` }, checkIcon(), 'Eaten');
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        await api.updateEntry(e.id, { status: 'eaten' });
        toast(`${e.food_name} marked as eaten`, 'ok');
        await loadDay();
      } catch (err) { toastError(err); b.disabled = false; }
    });
    return b;
  }
  async function markAllEaten(date, meal, btn) {
    if (btn) btn.disabled = true;
    try {
      const res = await api.markEaten(meal ? { date, meal } : { date });
      const n = res && typeof res.updated === 'number' ? res.updated : 0;
      toast(n ? `${n} ${n === 1 ? 'entry' : 'entries'} marked as eaten` : 'Nothing was planned', 'ok');
      await loadDay();
    } catch (err) { toastError(err); if (btn) btn.disabled = false; }
  }

  // ---- "Last 7 days" strip -------------------------------------------------
  const weekStripEl = $('#week-strip');
  const weekStripBody = $('#week-strip-body');
  let stripRequest = 0;
  $('#week-strip-trends').addEventListener('click', () => showView('trends'));
  async function loadWeekStrip() {
    const reqId = ++stripRequest;
    const end = state.date;
    const start = addDays(end, -6);
    $('#week-strip-heading').textContent = end === todayStr() ? 'Last 7 days' : `7 days to ${fmtMonthDay(end)}`;
    try {
      const sum = await api.summary(start, end);
      if (reqId !== stripRequest) return;
      renderWeekStrip(sum);
    } catch (e) {
      if (reqId !== stripRequest) return;
      clear(weekStripBody);
      weekStripBody.append(h('p', { class: 'empty-state' }, `Weekly summary unavailable (${e.detail || e.message}).`));
    }
  }
  function renderWeekStrip(sum) {
    clear(weekStripBody);
    const nutrients = sum.nutrients || {};
    const keys = STRIP_KEYS.filter((k) => nutrients[k]);
    $('#week-strip-sub').textContent = sum.logged_days ? `average per logged day · ${sum.logged_days} of ${sum.days} days logged` : 'no days logged yet';
    if (!keys.length) {
      weekStripBody.append(h('p', { class: 'empty-state' }, 'Set targets in Profile to see weekly averages.'));
    } else {
      const grid = h('div', { class: 'strip-grid' });
      for (const key of keys) {
        const nt = nutrients[key];
        const n = NUT[key];
        const level = nt.level || 'ok';
        const frac = nt.fraction != null ? Math.max(0, Math.min(1, nt.fraction)) : 0;
        const avgText = nt.average == null ? '—' : fmtNum(nt.average, key);
        const cell = h('div', { class: `strip-cell level-${level}`, role: 'group', 'aria-label': `${n.label}: average ${avgText} of ${fmtNum(nt.target, key)} ${n.unit} per day${nt.level ? `, ${LEVEL_TEXT[nt.level]}` : ''}${nt.days_over ? `, ${nt.days_over} days over` : ''}` },
          h('div', { class: 'strip-label' }, n.label, nt.assessment === 'weekly_average' ? h('span', { class: 'strip-tag', title: 'Judged on the weekly average' }, 'avg') : null),
          h('div', { class: 'strip-value' }, h('b', {}, avgText), h('span', { class: 'muted' }, ` / ${fmtNum(nt.target, key)} ${n.unit}`)),
          h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(frac * 100)}%` })),
          h('div', { class: 'strip-foot' }, nt.average == null ? 'no data' : `${pct(nt.fraction)} %${nt.days_over ? ` · ${nt.days_over} ${nt.days_over === 1 ? 'day' : 'days'} over` : ''}`));
        grid.append(cell);
      }
      weekStripBody.append(grid);
    }
    const inter = sum.interdialytic;
    if (inter && inter.nutrients && Object.keys(inter.nutrients).length) {
      weekStripBody.append(interdialyticBlock(inter, true));
    }
  }
  function interdialyticBlock(inter, compact) {
    const wrap = h('div', { class: `interdialytic${compact ? ' compact' : ''}`, role: 'group', 'aria-labelledby': compact ? 'inter-h-compact' : 'inter-h' });
    const since = fmtDateShort(inter.since), next = inter.next ? fmtDateShort(inter.next) : null;
    wrap.append(h('div', { class: 'inter-head' },
      h('h3', { class: 'inter-title', id: compact ? 'inter-h-compact' : 'inter-h' }, 'Since last dialysis'),
      h('span', { class: 'muted small' }, `${since} · ${inter.days} ${inter.days === 1 ? 'day' : 'days'}${next ? ` · next ${next}` : ''}`)));
    const list = h('div', { class: 'inter-list' });
    for (const key of INTERDIALYTIC_KEYS) {
      const it = inter.nutrients[key];
      if (!it) continue;
      const n = NUT[key];
      const level = it.level || 'ok';
      list.append(h('div', { class: `inter-row level-${level}` },
        h('span', { class: 'inter-label' }, n.label),
        h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(Math.max(0, Math.min(1, it.fraction || 0)) * 100)}%` })),
        h('span', { class: 'inter-nums tabular' }, h('b', {}, fmtNum(it.total, key)), ` / ${fmtNum(it.limit, key)} ${n.unit}`),
        levelPill(level, `${pct(it.fraction)} %`)));
    }
    // Fluid matters most between sessions; without a fluid target the server leaves it out, so
    // say it is not tracked and lead to the target instead of silently dropping the row.
    if (!inter.nutrients.fluid_ml) {
      const go = h('button', { type: 'button', class: 'link-btn' }, 'Set a fluid limit');
      go.addEventListener('click', () => {
        showView('profile');
        loadProfile().then(() => { const f = $('#tg-fluid_ml'); f.scrollIntoView({ block: 'center' }); f.focus({ preventScroll: true }); }).catch(() => {});
      });
      list.append(h('div', { class: 'inter-row untracked' },
        h('span', { class: 'inter-label' }, 'Fluid'),
        h('span', { class: 'inter-note' }, 'Not tracked: no daily fluid limit set'), go));
    }
    wrap.append(list);
    if (!compact) wrap.append(h('p', { class: 'hint' }, 'Limit = daily target × days since the last session. Intake on a dialysis day counts toward the next session.'));
    return wrap;
  }

  // ---------------------------------------------------------------------------
  // ADD view
  // ---------------------------------------------------------------------------
  const searchInput = $('#food-search');
  const chipsEl = $('#category-chips');
  const resultsEl = $('#food-results');
  const resultsHeading = $('#results-heading');
  const resultsCount = $('#results-count');
  let addInitialized = false;
  let searchRequest = 0;

  async function initAdd() {
    if (!addInitialized) {
      addInitialized = true;
      try {
        const res = await api.categories();
        state.categories = res.categories || [];
      } catch (e) { toastError(e); }
      renderChips();
    }
    runSearch();
    loadMeals().then(renderSavedShortcuts).catch(() => renderSavedShortcuts());
  }
  // Saved meals cache shared by Add, Today and Plan.
  async function loadMeals(force = false) {
    if (state.meals && !force) return state.meals;
    const res = await api.meals();
    state.meals = res.meals || [];
    return state.meals;
  }
  $('#saved-shortcuts-manage').addEventListener('click', () => showView('plan'));
  function renderSavedShortcuts() {
    const wrap = $('#saved-shortcuts');
    const list = clear($('#saved-shortcuts-list'));
    const meals = state.meals || [];
    wrap.hidden = !meals.length;
    for (const t of meals) {
      // The list item wraps the button: a role="listitem" on the <button> itself would hide its
      // button role from screen readers (ARIA in HTML forbids that combination).
      const b = h('button', { class: 'meal-chip', type: 'button',
        'aria-label': `Add saved meal ${t.name}: ${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'}, ${fmtNum(t.totals.carbs_g, 'carbs_g')} g carbs` },
        ratingIcon(t.kidney_rating, { decorative: true }),
        h('span', { class: 'meal-chip-main' }, h('span', { class: 'meal-chip-name' }, t.name),
          h('span', { class: 'meal-chip-sub' }, `${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'} · ${fmtNum(t.totals.carbs_g, 'carbs_g')} g carbs · K ${fmtNum(t.totals.potassium_mg, 'potassium_mg')}`)));
      b.addEventListener('click', () => openApplySheet({ mealId: t.id, date: state.date, meal: state.addMealHint || defaultMealForNow(), status: state.addStatusHint, trigger: b }));
      list.append(h('div', { class: 'meal-chip-item', role: 'listitem' }, b));
    }
  }
  function renderChips() {
    clear(chipsEl);
    const mk = (label, value) => {
      const b = h('button', { class: 'chip', type: 'button', 'aria-pressed': state.category === value ? 'true' : 'false' }, label);
      b.addEventListener('click', () => { state.category = value; renderChips(); runSearch(); });
      return b;
    };
    chipsEl.append(mk('All', ''));
    for (const c of state.categories) chipsEl.append(mk(c, c));
  }
  async function runSearch() {
    const reqId = ++searchRequest;
    const q = searchInput.value.trim();
    state.query = q;
    try {
      const res = await api.foods({ q, category: state.category, limit: 25 });
      if (reqId !== searchRequest) return;
      renderResults(res.foods || []);
    } catch (e) { if (reqId === searchRequest) toastError(e); }
  }
  searchInput.addEventListener('input', debounce(runSearch, 250));
  searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); runSearch(); } });

  function renderResults(foods) {
    clear(resultsEl);
    const browsing = !state.query && !state.category;
    resultsHeading.textContent = browsing ? 'Recent foods' : state.query ? `Results for “${state.query}”` : state.category;
    resultsCount.textContent = foods.length ? `${foods.length}${foods.length >= 25 ? '+' : ''} ${foods.length === 1 ? 'food' : 'foods'}` : '';
    if (!foods.length) {
      resultsEl.append(h('li', { class: 'empty-state' }, 'No foods match. Try fewer words, use Quick add, or search USDA.'));
      return;
    }
    for (const f of foods) resultsEl.append(h('li', {}, foodRow(f)));
  }
  function foodRow(f) {
    const nums = h('div', { class: 'row-nums' });
    for (const k of ROW_NUMBERS) nums.append(h('span', { class: 'n' }, `${NUT[k].short} `, h('b', {}, fmtNum(f.nutrients[k], k)), ` ${NUT[k].unit}`));
    const btn = h('button', { class: 'row-btn', type: 'button' },
      ratingIcon(f.kidney_rating),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, f.name, f.brand ? h('span', { class: 'row-sub' }, ` (${f.brand})`) : null,
          f.source && f.source !== 'builtin' ? h('span', { class: 'food-source' }, f.source) : null),
        h('div', { class: 'row-sub' }, f.serving_desc, f.flags && f.flags.includes('hypo_treatment') ? ' · hypo treatment' : '')),
      nums);
    btn.addEventListener('click', () => openEntrySheet('add', { food: f, trigger: btn }));
    return btn;
  }

  // ---------------------------------------------------------------------------
  // Dialog helpers
  // ---------------------------------------------------------------------------
  // Forms run their handler from the submit button's click (Enter in a field clicks the default
  // button too): a sandboxed frame without allow-forms never fires "submit", so the app does not
  // depend on it. The handler's preventDefault() stops the native submission either way.
  function onSubmit(form, handler) {
    form.addEventListener('submit', handler);
    $$('button[type="submit"]', form).forEach((b) => b.addEventListener('click', handler));
  }

  // ---------------------------------------------------------------------------
  // In-page confirmation. window.confirm() is never shown in a home-screen web app or a
  // sandboxed frame, so destructive actions ask inside the page: the confirm row takes the
  // place of `host` (a sheet footer or an actions row), names what will be deleted, and gets
  // focus on its confirm button; Cancel or Escape puts the host back and refocuses the trigger.
  // ---------------------------------------------------------------------------
  let confirmSeq = 0;
  function dismissConfirm(host, refocus = false) {
    if (host && host._confirmRow) host._confirmRow._close(refocus);
  }
  function inlineConfirm(host, trigger, { message, confirmText = 'Delete', onConfirm }) {
    dismissConfirm(host);
    const msgId = `confirm-msg-${++confirmSeq}`;
    const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Cancel');
    const ok = h('button', { class: 'btn danger-solid', type: 'button' }, confirmText);
    const row = h('div', { class: `confirm-row${host.classList.contains('sheet-foot') ? ' sheet-foot' : ''}`, role: 'group', 'aria-labelledby': msgId },
      h('p', { class: 'confirm-msg', id: msgId }, message),
      h('div', { class: 'confirm-actions' }, cancel, ok));
    const close = (refocus) => {
      if (host._confirmRow !== row) return;
      host._confirmRow = null;
      row.remove();
      host.hidden = false;
      if (refocus && trigger && document.contains(trigger) && !trigger.hidden) { try { trigger.focus(); } catch (e) { /* ignore */ } }
    };
    row._close = close;
    host._confirmRow = row;
    host.hidden = true;
    host.after(row);
    cancel.addEventListener('click', () => close(true));
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
    });
    ok.addEventListener('click', async () => {
      ok.disabled = true; cancel.disabled = true;
      let done = false;
      try { done = (await onConfirm()) !== false; } catch (err) { toastError(err); }
      if (done) close(false);
      else if (host._confirmRow === row) { ok.disabled = false; cancel.disabled = false; ok.focus(); }
    });
    setTimeout(() => { if (document.contains(ok)) ok.focus(); }, 0);
    return row;
  }

  function setupDialog(dlg) {
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
    $$('[data-close]', dlg).forEach((b) => b.addEventListener('click', () => dlg.close()));
    dlg.addEventListener('close', () => {
      $$('.sheet-foot', dlg).forEach((foot) => dismissConfirm(foot));
      const f = dlg._returnFocus;
      dlg._returnFocus = null;
      if (f && document.contains(f)) { try { f.focus(); } catch (e) { /* ignore */ } }
    });
  }
  function openDialog(dlg, trigger, focusEl) {
    dlg._returnFocus = trigger || document.activeElement;
    if (typeof dlg.showModal === 'function') { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute('open', '');
    const target = focusEl || $('input, select, button:not([data-close])', dlg);
    if (target) setTimeout(() => target.focus({ preventScroll: true }), 30);
    $('.sheet-body', dlg).scrollTop = 0;
  }
  function renderWarnings(container, warnings, { emptyText } = {}) {
    clear(container);
    if (!warnings.length) {
      container.append(h('div', { class: 'warning level-ok' }, ratingIcon('ok', { label: 'No warnings' }),
        h('div', {}, h('span', { class: 'w-level' }, 'No warnings. '), emptyText || 'Nothing in this amount crosses a per-serving threshold.')));
      return;
    }
    for (const w of warnings) {
      const lvl = w.level === 'high' ? 'over' : 'caution';
      container.append(h('div', { class: `warning level-${lvl}` }, ratingIcon(lvl, { label: w.level === 'high' ? 'High' : 'Moderate' }),
        h('div', {}, h('span', { class: 'w-level' }, w.level === 'high' ? 'High. ' : 'Moderate. '), w.message)));
    }
  }

  // ---------------------------------------------------------------------------
  // ENTRY sheet (add + edit)
  // ---------------------------------------------------------------------------
  const entryDlg = $('#sheet-entry');
  const entryForm = $('#entry-form');
  const entryServings = $('#entry-servings');
  const entryGrams = $('#entry-grams');
  const entryNote = $('#entry-note');
  const entryDate = $('#entry-date');
  const sheet = { mode: 'add', food: null, entry: null, perServing: null, lastEdited: 'servings', amountTouched: false, busy: false };
  setupDialog(entryDlg);

  function perServingFromEntry(entry) {
    const out = {};
    for (const n of NUTRIENTS) {
      const v = entry.nutrients ? entry.nutrients[n.key] : null;
      out[n.key] = v == null || !entry.servings ? v : v / entry.servings;
    }
    return out;
  }
  function selectedMeal(groupEl) { const r = $('input:checked', groupEl); return r ? r.value : defaultMealForNow(); }
  function setMeal(groupEl, meal) { const r = $(`input[value="${meal}"]`, groupEl); if (r) r.checked = true; }
  function selectedStatus(groupEl) { const r = $('input:checked', groupEl); return r && r.value === 'planned' ? 'planned' : 'eaten'; }
  function setStatus(groupEl, status) { const r = $(`input[value="${status === 'planned' ? 'planned' : 'eaten'}"]`, groupEl); if (r) r.checked = true; }
  function updateStatusHint() {
    const st = selectedStatus($('#entry-status'));
    const date = sheet.mode === 'edit' && entryDate.value ? entryDate.value : state.date;
    const when = date === todayStr() ? 'today' : date > todayStr() ? 'that day' : 'this day';
    $('#entry-status-hint').textContent = st === 'planned'
      ? `Planned foods count toward the projected total for ${when}, not the eaten total. Tap "Eaten" later.`
      : `Counts toward the eaten total for ${when}.`;
  }
  function updateEntryCta() {
    // Planning a food must not read like eating it: title and primary button follow the status.
    if (sheet.mode !== 'add') return;
    const planned = selectedStatus($('#entry-status')) === 'planned';
    const meal = MEAL_LABEL[selectedMeal($('#entry-meal'))] || 'meal';
    $('#sheet-entry-title').textContent = planned ? 'Plan food' : 'Add food';
    $('#entry-save').textContent = planned ? `Plan for ${meal.toLowerCase()}` : `Add to ${meal.toLowerCase()}`;
  }
  $('#entry-status').addEventListener('change', () => { updateStatusHint(); updateEntryCta(); updatePreview(); });
  $('#entry-meal').addEventListener('change', updateEntryCta);
  entryDate.addEventListener('change', updateStatusHint);

  async function openEntrySheet(mode, { food, entry, meal, trigger }) {
    sheet.mode = mode; sheet.food = food || null; sheet.entry = entry || null;
    sheet.lastEdited = 'servings'; sheet.amountTouched = false; sheet.busy = false;
    entryDlg.dataset.mode = mode;
    $('#sheet-entry-title').textContent = mode === 'add' ? 'Add food' : 'Edit entry';
    $('#entry-save').textContent = mode === 'add' ? 'Add to meal' : 'Save changes';
    const name = food ? food.name : entry.food_name;
    sheet.perServing = food ? food.nutrients : perServingFromEntry(entry);
    renderSheetFood();
    setMeal($('#entry-meal'), entry ? entry.meal : meal || state.addMealHint || defaultMealForNow());
    setStatus($('#entry-status'), entry ? entry.status || 'eaten' : state.addStatusHint || defaultStatusFor(state.date));
    state.addMealHint = null; state.addStatusHint = null;
    updateStatusHint();
    updateEntryCta();
    entryServings.value = entry ? String(Math.round(entry.servings * 1000) / 1000) : '1';
    entryGrams.value = entry && entry.grams != null ? String(Math.round(entry.grams)) : '';
    entryNote.value = entry && entry.note ? entry.note : '';
    entryDate.value = entry ? entry.date : state.date;
    entryGrams.disabled = !food;
    $('#entry-grams-hint').textContent = food ? `1 serving = ${fmtNum(food.serving_g, 'fluid_ml')} g` : 'Loading serving size…';
    $('#entry-delete-food').hidden = !(mode === 'add' && food && food.source !== 'builtin');
    if (food && !entryGrams.value) syncGramsFromServings();
    updatePreview();
    openDialog(entryDlg, trigger, entryServings);
    if (!food && entry) {
      try {
        const f = await api.food(entry.food_id);
        if (sheet.entry !== entry) return;
        sheet.food = f;
        sheet.perServing = f.nutrients;
        entryGrams.disabled = false;
        $('#entry-grams-hint').textContent = `1 serving = ${fmtNum(f.serving_g, 'fluid_ml')} g`;
        if (!entryGrams.value) syncGramsFromServings();
        renderSheetFood();
        updatePreview();
      } catch (e) {
        $('#entry-grams-hint').textContent = 'Serving size unavailable';
        $('#sheet-entry-food').textContent = name;
      }
    }
  }
  function renderSheetFood() {
    const f = sheet.food;
    const name = f ? f.name : sheet.entry.food_name;
    const sub = $('#sheet-entry-food');
    clear(sub);
    const rating = f ? f.kidney_rating : sheet.entry.kidney_rating;
    sub.append(h('span', { class: 'sheet-food-name' }, name), f && f.brand ? ` (${f.brand})` : '', f ? ` · ${f.serving_desc}` : '', ' ', levelPill(rating, rating === 'red' ? 'High concern' : rating === 'yellow' ? 'Moderate' : 'Kidney-friendly'));
    $('#entry-serving-desc').textContent = f ? `1 serving = ${f.serving_desc}` : '';
    const chips = clear($('#sheet-entry-flags'));
    for (const fl of (f && f.flags) || []) {
      const def = FLAG[fl];
      chips.append(h('span', { class: `flag-chip ${def ? def.kind : ''}` }, def ? def.label : fl));
    }
    const notes = $('#sheet-entry-notes');
    notes.hidden = !(f && f.kidney_notes);
    notes.textContent = f && f.kidney_notes ? f.kidney_notes : '';
  }
  function servingsValue() { const v = Number(entryServings.value); return Number.isFinite(v) && v >= 0 ? v : 0; }
  function syncGramsFromServings() {
    if (sheet.food && sheet.food.serving_g) entryGrams.value = String(Math.round(servingsValue() * sheet.food.serving_g));
  }
  function syncServingsFromGrams() {
    const g = Number(entryGrams.value);
    if (sheet.food && sheet.food.serving_g && Number.isFinite(g) && g >= 0) entryServings.value = String(Math.round((g / sheet.food.serving_g) * 100) / 100);
  }
  entryServings.addEventListener('input', () => { sheet.lastEdited = 'servings'; sheet.amountTouched = true; syncGramsFromServings(); updatePreview(); });
  entryGrams.addEventListener('input', () => { sheet.lastEdited = 'grams'; sheet.amountTouched = true; syncServingsFromGrams(); updatePreview(); });
  $$('.step-btn', entryDlg).forEach((b) => b.addEventListener('click', () => {
    const next = Math.max(0, Math.round((servingsValue() + Number(b.dataset.step)) * 100) / 100);
    entryServings.value = String(next);
    sheet.lastEdited = 'servings'; sheet.amountTouched = true;
    syncGramsFromServings(); updatePreview();
  }));
  $('#entry-meal').addEventListener('change', updatePreview);

  // Unrounded, like the server's entry snapshot (food × servings); the display rounds and the
  // warnings evaluator rounds exactly as app/nutrients.py does.
  function scaledNutrients(perServing, servings) {
    const out = {};
    for (const n of NUTRIENTS) {
      const v = perServing ? perServing[n.key] : null;
      out[n.key] = v == null ? null : Number(v) * servings;
    }
    return out;
  }
  function previewServings() {
    // When the weight was typed last, preview with the exact ratio the server scales the entry by
    // (grams / serving_g, unrounded; only the entry's displayed `servings` is rounded to 3
    // decimals), not the 2-decimal number shown in the servings box, so the numbers read before
    // saving are the numbers seen after saving.
    const g = Number(entryGrams.value);
    if (sheet.lastEdited === 'grams' && sheet.food && sheet.food.serving_g && Number.isFinite(g) && g > 0) {
      return g / sheet.food.serving_g;
    }
    return servingsValue();
  }
  function updatePreview() {
    const sv = previewServings();
    const scaled = scaledNutrients(sheet.perServing, sv);
    $('#entry-preview-amount').textContent = `${fmtServings(sv)}${entryGrams.value ? ` · ${entryGrams.value} g` : ''}`;
    const key = clear($('#entry-preview-key'));
    for (const k of KEY_NUMBERS) {
      key.append(h('div', { class: 'kn' }, h('span', { class: 'kn-v' }, fmtNum(scaled[k], k)), h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    }
    const all = clear($('#entry-preview-all'));
    for (const n of NUTRIENTS) all.append(h('div', { class: 'ng' }, h('span', {}, n.label), h('b', {}, fmtWithUnit(scaled[n.key], n.key))));

    // Warnings: the server's per-serving warnings for exactly one serving, else re-evaluated for this amount.
    const f = sheet.food;
    let warnings;
    if (sv === 1 && f && Array.isArray(f.warnings)) warnings = f.warnings;
    else warnings = evaluateWarnings(scaled, f ? f.flags : [], f ? f.kidney_notes : '', false);
    const box = $('#entry-warnings');
    renderWarnings(box, warnings);
    // Day impact: where would today's running totals land after this entry?
    const impact = dayImpact(scaled, selectedMeal($('#entry-meal')));
    if (impact.length) {
      const list = h('div', { class: 'warnings impact' });
      for (const it of impact) {
        list.append(h('div', { class: `warning level-${it.level}` }, ratingIcon(it.level, { label: LEVEL_TEXT[it.level] }),
          h('div', {}, h('span', { class: 'w-level' }, `${it.level === 'over' ? 'Day total over. ' : 'Day total near limit. '}`), it.message)));
      }
      box.append(list);
    }
  }
  function dayImpact(scaled, meal) {
    const day = state.day;
    if (!day || state.dayLoadedFor !== (sheet.entry ? sheet.entry.date : state.date)) return [];
    return impactOn(day, scaled, meal, { editing: sheet.mode === 'edit' ? sheet.entry : null, status: selectedStatus($('#entry-status')) });
  }
  // Where would the day's totals land after adding `scaled` to `meal`? For a planned entry the base is the
  // projected total (eaten + planned); for an eaten entry it is the eaten total. `editing` is subtracted first.
  function impactOn(day, scaled, meal, { editing = null, status = 'eaten' } = {}) {
    const out = [];
    const wf = (state.profile && state.profile.warn_fraction) || 0.8;
    const planned = status === 'planned' && day.projected_status;
    const statusMap = planned ? day.projected_status : day.status || {};
    const suffix = planned ? ' with everything planned' : '';
    const editVal = (key) => {
      if (!editing || !editing.nutrients) return 0;
      if (planned || !isPlanned(editing)) return editing.nutrients[key] || 0; // projected totals include every entry; eaten totals only eaten ones
      return 0;
    };
    for (const [key, st] of Object.entries(statusMap)) {
      if (!NUT[key] || !st.target) continue;
      const base = (st.value || 0) - editVal(key);
      const projected = base + (scaled[key] || 0);
      const fraction = projected / st.target;
      if (fraction < wf) continue;
      const level = fraction > 1 ? 'over' : 'caution';
      const contribution = (scaled[key] || 0) / st.target;
      // Only worth saying when this food changes the level or adds a meaningful share (>= 5 %) of the target.
      if (st.level === level && contribution < 0.05) continue;
      if (!(scaled[key] > 0)) continue;
      out.push({ level, message: `${NUT[key].label} would reach ${fmtNum(projected, key)} / ${fmtNum(st.target, key)} ${NUT[key].unit} (${pct(fraction)} %)${suffix}` });
    }
    const perMeal = day.targets && typeof day.targets.carbs_per_meal_g === 'number' ? day.targets.carbs_per_meal_g : null;
    if (perMeal && day.meals && day.meals[meal]) {
      let mealBase = day.meals[meal].carbs_g || 0;
      if (planned && day.planned_meals && day.planned_meals[meal]) mealBase += day.planned_meals[meal].carbs_g || 0;
      const base = mealBase - (editing && editing.meal === meal ? editVal('carbs_g') : 0);
      const projected = base + (scaled.carbs_g || 0);
      const fraction = projected / perMeal;
      if (fraction >= wf && scaled.carbs_g > 0) {
        out.push({ level: fraction > 1 ? 'over' : 'caution', message: `${MEAL_LABEL[meal]} carbohydrate would be ${fmtNum(projected, 'carbs_g')} / ${perMeal} g (${pct(fraction)} %)${suffix}` });
      }
    }
    return out;
  }

  onSubmit(entryForm, async (e) => {
    e.preventDefault();
    if (sheet.busy) return;
    const sv = servingsValue();
    if (!(sv > 0)) { toast('Servings must be more than 0', 'error'); entryServings.focus(); return; }
    if (sv > 1000) { toast('Servings must be 1000 or fewer', 'error'); entryServings.focus(); return; }
    const meal = selectedMeal($('#entry-meal'));
    const status = selectedStatus($('#entry-status'));
    const note = entryNote.value.trim() || null;
    const grams = sheet.lastEdited === 'grams' && entryGrams.value !== '' ? Number(entryGrams.value) : null;
    if (grams != null && !(grams > 0 && grams <= 100000)) { toast('Grams must be between 1 and 100,000', 'error'); entryGrams.focus(); return; }
    sheet.busy = true;
    const saveBtn = $('#entry-save');
    saveBtn.disabled = true;
    try {
      if (sheet.mode === 'add') {
        const body = { date: state.date, meal, food_id: sheet.food.id, servings: sv, note, status };
        if (grams != null) body.grams = grams;
        const created = await api.addEntry(body);
        entryDlg.close();
        const when = state.date !== todayStr() ? `, ${fmtDateLong(state.date)}` : '';
        toast(`${status === 'planned' ? 'Planned' : 'Added'} ${created.food_name || sheet.food.name} ${status === 'planned' ? 'for' : 'to'} ${MEAL_LABEL[meal].toLowerCase()}${when}`, 'ok');
        state.dayLoadedFor = null;
        showView('today');
      } else {
        const body = { meal, note, status };
        if (entryDate.value && /^\d{4}-\d{2}-\d{2}$/.test(entryDate.value)) body.date = entryDate.value;
        if (sheet.amountTouched) { body.servings = sv; body.grams = grams; }
        await api.updateEntry(sheet.entry.id, body);
        entryDlg.close();
        toast('Entry updated', 'ok');
        if (body.date && body.date !== state.date) setDate(body.date); else loadDay();
      }
    } catch (err) { toastError(err); }
    finally { sheet.busy = false; saveBtn.disabled = false; }
  });
  $('#entry-delete').addEventListener('click', (ev) => {
    const entry = sheet.entry;
    if (!entry || sheet.busy) return;
    inlineConfirm($('.sheet-foot', entryDlg), ev.currentTarget, {
      message: `Delete ${entry.food_name} from ${MEAL_LABEL[entry.meal].toLowerCase()}${entry.date !== todayStr() ? ` on ${fmtDateLong(entry.date)}` : ''}?`,
      confirmText: 'Delete entry',
      onConfirm: async () => {
        sheet.busy = true;
        try {
          await api.deleteEntry(entry.id);
          entryDlg.close();
          toast('Entry deleted', 'ok');
          loadDay();
          return true;
        } catch (err) { toastError(err); return false; }
        finally { sheet.busy = false; }
      },
    });
  });
  $('#entry-delete-food').addEventListener('click', (ev) => {
    const f = sheet.food;
    if (!f || sheet.busy) return;
    inlineConfirm($('.sheet-foot', entryDlg), ev.currentTarget, {
      message: `Delete the food "${f.name}" from your database? Logged entries keep their numbers.`,
      confirmText: 'Delete food',
      onConfirm: async () => {
        sheet.busy = true;
        try {
          await api.deleteFood(f.id);
          entryDlg.close();
          toast('Food deleted', 'ok');
          runSearch();
          return true;
        } catch (err) { toastError(err); return false; }
        finally { sheet.busy = false; }
      },
    });
  });

  // ---------------------------------------------------------------------------
  // QUICK ADD sheet
  // ---------------------------------------------------------------------------
  const quickDlg = $('#sheet-quick');
  const quickForm = $('#quick-form');
  setupDialog(quickDlg);
  (function buildQuickForm() {
    const grid = $('#quick-nutrients');
    for (const n of NUTRIENTS) {
      const id = `qn-${n.key}`;
      grid.append(h('div', { class: 'field' },
        h('label', { for: id }, `${n.label} (${n.unit})`),
        h('input', { id, type: 'number', inputmode: 'decimal', min: 0, step: n.unit === 'g' ? 0.1 : 1, 'data-nutrient': n.key, placeholder: '0' })));
    }
    const flags = $('#quick-flags');
    for (const f of FLAGS) {
      const id = `qf-${f.key}`;
      flags.append(h('label', { class: 'check', for: id },
        h('input', { type: 'checkbox', id, 'data-flag': f.key }),
        h('span', { class: 'check-text' }, f.label, f.hint ? h('span', { class: 'hint' }, f.hint) : null)));
    }
    quickForm.addEventListener('input', updateQuickPreview);
  })();
  function quickNutrients() {
    const out = {};
    for (const inp of $$('#quick-nutrients input')) { const v = numOrNull(inp.value); if (v != null) out[inp.dataset.nutrient] = v; }
    return out;
  }
  function quickFlags() { return $$('#quick-flags input:checked').map((i) => i.dataset.flag); }
  function updateQuickPreview() {
    const sv = Number($('#q-servings').value) || 1;
    const per = quickNutrients();
    const flags = quickFlags();
    if (flags.includes('counts_as_fluid') && per.fluid_ml == null && $('#q-serving-g').value) per.fluid_ml = Number($('#q-serving-g').value);
    const scaled = scaledNutrients(per, sv);
    const warnings = evaluateWarnings(scaled, flags, '', false);
    renderWarnings($('#quick-warnings'), warnings, { emptyText: 'Enter the label values to see per-serving warnings.' });
  }
  $('#btn-quick').addEventListener('click', (e) => {
    quickForm.reset();
    $('#q-serving-desc').value = '1 serving';
    $('#q-serving-g').value = '100';
    $('#q-servings').value = '1';
    setMeal($('#quick-meal'), state.addMealHint || defaultMealForNow());
    setStatus($('#quick-status'), state.addStatusHint || defaultStatusFor(state.date));
    updateQuickPreview();
    openDialog(quickDlg, e.currentTarget, $('#q-name'));
  });
  let quickBusy = false;
  onSubmit(quickForm, async (e) => {
    e.preventDefault();
    if (quickBusy) return;
    const name = $('#q-name').value.trim();
    if (!name) { toast('Give the food a name', 'error'); $('#q-name').focus(); return; }
    const nutrients = quickNutrients();
    if (!Object.keys(nutrients).length) { toast('Enter at least one nutrient value', 'error'); return; }
    const flags = quickFlags();
    const servingG = numOrNull($('#q-serving-g').value) || 100;
    if (flags.includes('counts_as_fluid') && nutrients.fluid_ml == null) nutrients.fluid_ml = servingG;
    const body = { date: state.date, meal: selectedMeal($('#quick-meal')), name, serving_desc: $('#q-serving-desc').value.trim() || '1 serving',
      serving_g: servingG, nutrients, servings: Number($('#q-servings').value) || 1, flags, status: selectedStatus($('#quick-status')) };
    quickBusy = true; $('#quick-save').disabled = true;
    try {
      const created = await api.quick(body);
      quickDlg.close();
      const when = state.date !== todayStr() ? `, ${fmtDateLong(state.date)}` : '';
      toast(`${body.status === 'planned' ? 'Planned' : 'Logged'} ${created.food_name || name} ${body.status === 'planned' ? 'for' : 'to'} ${MEAL_LABEL[body.meal].toLowerCase()}${when}`, 'ok');
      state.dayLoadedFor = null;
      showView('today');
    } catch (err) { toastError(err); }
    finally { quickBusy = false; $('#quick-save').disabled = false; }
  });

  // ---------------------------------------------------------------------------
  // USDA sheet
  // ---------------------------------------------------------------------------
  const usdaDlg = $('#sheet-usda');
  const usdaForm = $('#usda-form');
  const usdaStatus = $('#usda-status');
  const usdaResults = $('#usda-results');
  setupDialog(usdaDlg);
  const USDA_DISABLED_MSG = MOCK
    ? 'USDA search needs the installed app with a USDA API key (free at api.data.gov); the server looks foods up for you. This preview has no server, so use the built-in list or Quick add.'
    : 'USDA search is not enabled on this server. Set USDA_API_KEY to enable it (free key at api.data.gov).';
  $('#btn-usda').addEventListener('click', (e) => {
    clear(usdaResults);
    usdaStatus.textContent = MOCK ? USDA_DISABLED_MSG : '';
    openDialog(usdaDlg, e.currentTarget, $('#usda-q'));
  });
  async function usdaSearch() {
    const q = $('#usda-q').value.trim();
    if (!q) { $('#usda-q').focus(); return; }
    usdaStatus.textContent = 'Searching USDA FoodData Central…';
    clear(usdaResults);
    try {
      const res = await api.usdaSearch(q);
      const foods = res.foods || [];
      usdaStatus.textContent = foods.length ? `${foods.length} results. Tap one to import it.` : 'No results from USDA.';
      for (const f of foods) {
        const btn = h('button', { class: 'row-btn', type: 'button' },
          s('svg', { class: 'rating', viewBox: '0 0 24 24', 'aria-hidden': 'true' }, s('path', { d: 'M12 4v16M4 12h16', stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round', opacity: 0.6 })),
          h('div', { class: 'row-main' },
            h('div', { class: 'row-title' }, f.description),
            h('div', { class: 'row-sub' }, [f.brand, f.category, f.data_type].filter(Boolean).join(' · '))),
          h('span', { class: 'muted small' }, 'Import'));
        btn.addEventListener('click', () => usdaImport(f, btn));
        usdaResults.append(h('li', {}, btn));
      }
    } catch (err) {
      usdaStatus.textContent = err.status === 503 ? USDA_DISABLED_MSG : `USDA search failed: ${err.detail || err.message}`;
    }
  }
  async function usdaImport(f, btn) {
    btn.disabled = true;
    usdaStatus.textContent = `Importing “${f.description}”…`;
    try {
      const food = await api.usdaImport(f.fdc_id);
      usdaDlg.close();
      toast(`Imported ${food.name}`, 'ok');
      openEntrySheet('add', { food, trigger: $('#btn-usda') });
    } catch (err) {
      usdaStatus.textContent = err.status === 503 ? USDA_DISABLED_MSG : `Import failed: ${err.detail || err.message}`;
      btn.disabled = false;
    }
  }
  $('#usda-go').addEventListener('click', usdaSearch);
  usdaForm.addEventListener('submit', (e) => { e.preventDefault(); usdaSearch(); });
  $('#usda-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); usdaSearch(); } });

  // ---------------------------------------------------------------------------
  // TRENDS view
  // ---------------------------------------------------------------------------
  const chartsEl = $('#charts');
  const chartTip = $('#chart-tip');
  let trendsRequest = 0;
  $$('.segmented .seg[data-days]').forEach((b) => b.addEventListener('click', () => {
    state.trendsDays = Number(b.dataset.days);
    $$('.segmented .seg[data-days]').forEach((x) => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    loadTrends();
  }));
  async function loadTrends() {
    const reqId = ++trendsRequest;
    const end = todayStr();
    const start = addDays(end, -(state.trendsDays - 1));
    $('#trends-title').textContent = `Last ${state.trendsDays} days`;
    $('#trends-range').textContent = `${fmtDateShort(start)} – ${fmtDateShort(end)}`;
    const exportLink = $('#export-csv');
    if (mock) {
      // The demo cannot download (the preview's frame blocks it): show the CSV in a sheet instead.
      exportLink.removeAttribute('download');
      exportLink.setAttribute('href', '#export');
      exportLink.setAttribute('role', 'button');
      exportLink.setAttribute('aria-haspopup', 'dialog');
      exportLink.onclick = (e) => { e.preventDefault(); openCsvSheet(start, end, exportLink); };
      exportLink.onkeydown = (e) => { if (e.key === ' ') { e.preventDefault(); openCsvSheet(start, end, exportLink); } };
    } else {
      exportLink.setAttribute('download', `kidney-log_${start}_${end}.csv`);
      exportLink.href = api.exportUrl(start, end);
      exportLink.onclick = null;
    }
    chartsEl.style.opacity = state.trends ? '0.6' : '';
    try {
      const [res, sum] = await Promise.all([
        api.range(start, end),
        api.summary(start, end).then((v) => ({ ok: v })).catch((e) => ({ err: e })),
      ]);
      if (reqId !== trendsRequest) return;
      state.trends = { start, end, days: res.days || [] };
      state.summary = sum.ok || null;
      renderTrends();
      renderPeriodSummary(sum.ok, sum.err);
    } catch (e) { if (reqId === trendsRequest) toastError(e); }
    finally { chartsEl.style.opacity = ''; }
  }
  // ---- CSV sheet (demo only): the text to copy, since the preview cannot download files ----
  const csvDlg = $('#sheet-csv');
  setupDialog(csvDlg);
  async function openCsvSheet(start, end, trigger) {
    let csv;
    try { csv = await mock.request('GET', api.exportUrl(start, end)); } catch (err) { toastError(err); return; }
    const rows = Math.max(0, csv.split('\r\n').filter(Boolean).length - 1);
    $('#sheet-csv-sub').textContent = `${fmtRange(start, end)} · ${rows} ${rows === 1 ? 'entry' : 'entries'} · kidney-log_${start}_${end}.csv`;
    $('#csv-text').value = csv;
    $('#csv-status').textContent = '';
    openDialog(csvDlg, trigger, $('#csv-copy'));
  }
  $('#csv-copy').addEventListener('click', () => {
    const ta = $('#csv-text');
    const status = $('#csv-status');
    const selectAll = () => {
      ta.focus();
      ta.select();
      try { ta.setSelectionRange(0, ta.value.length); } catch (e) { /* ignore */ }
      let copied = false;
      try { copied = !!(document.execCommand && document.execCommand('copy')); } catch (e) { copied = false; }
      status.textContent = copied ? 'CSV copied to the clipboard.'
        : 'Copying is blocked here, so the text is selected: press Ctrl+C (⌘C on a Mac), or long-press it and choose Copy.';
    };
    // A frame without clipboard-write would reject (and log an error); skip straight to selecting.
    const policy = document.permissionsPolicy || document.featurePolicy;
    let allowed = true;
    try { allowed = !policy || typeof policy.allowsFeature !== 'function' || policy.allowsFeature('clipboard-write'); } catch (e) { allowed = true; }
    try {
      if (allowed && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(ta.value).then(() => { status.textContent = 'CSV copied to the clipboard.'; }, selectAll);
      } else selectAll();
    } catch (e) { selectAll(); }
  });
  function renderPeriodSummary(sum, err) {
    const body = clear($('#period-body'));
    const inter = clear($('#period-interdialytic'));
    inter.hidden = true;
    const notes = clear($('#period-notes'));
    if (err || !sum) {
      $('#period-sub').textContent = '';
      body.append(h('p', { class: 'empty-state' }, `Period summary unavailable${err ? ` (${err.detail || err.message})` : ''}.`));
      return;
    }
    $('#period-sub').textContent = `${fmtRange(sum.start, sum.end)} · ${sum.logged_days} of ${sum.days} days logged`;
    const keys = Object.keys(sum.nutrients || {}).filter((k) => NUT[k]).sort((a, b) => TREND_ORDER.indexOf(a) - TREND_ORDER.indexOf(b));
    if (!keys.length) {
      body.append(h('p', { class: 'empty-state' }, 'No targets set yet. Set targets in Profile to see a summary.'));
      return;
    }
    const grid = h('div', { class: 'period-grid' });
    for (const key of keys) {
      const nt = sum.nutrients[key];
      const n = NUT[key];
      const weekly = (nt.assessment || ASSESSMENT[key]) === 'weekly_average';
      // The tag names the period actually averaged: "weekly average" only for a 7-day range.
      const avgTag = sum.days === 7 ? 'weekly average' : `${sum.days}-day average`;
      const avgTitle = sum.days === 7 ? 'Judged on the weekly average' : `Judged on the ${sum.days}-day average`;
      const level = nt.level || 'ok';
      const avgText = nt.average == null ? '—' : fmtNum(nt.average, key);
      const change = fmtChange(nt.change_pct);
      const dir = nt.change_pct == null ? '' : nt.change_pct > 0.05 ? 'up' : nt.change_pct < -0.05 ? 'down' : 'flat';
      // For limits a rise is bad news; for calories/protein it is neutral.
      const tone = nt.role === 'limit' ? (dir === 'up' ? 'bad' : dir === 'down' ? 'good' : '') : '';
      const row = h('div', { class: `period-row level-${level}`, role: 'group',
        'aria-label': `${n.label}: average ${avgText} of ${fmtNum(nt.target, key)} ${n.unit} per day${nt.level ? `, ${LEVEL_TEXT[nt.level]}` : ''}, ${nt.days_over} days over${change ? `, ${change} versus the previous period` : ''}` });
      row.append(h('div', { class: 'period-top' },
        h('div', { class: 'period-name' }, n.label,
          h('span', { class: `strip-tag ${weekly ? 'weekly' : 'daily'}`, title: weekly ? avgTitle : 'Judged day by day' }, weekly ? avgTag : 'day by day')),
        nt.level ? levelPill(nt.level, LEVEL_TEXT[nt.level]) : h('span', { class: 'muted small' }, 'no data')));
      row.append(h('div', { class: 'period-nums tabular' }, h('b', {}, avgText), h('span', { class: 'muted' }, ` / ${fmtNum(nt.target, key)} ${n.unit} per day`)));
      row.append(h('div', { class: 'strip-track' }, h('div', { class: 'strip-fill', style: `width:${Math.round(Math.max(0, Math.min(1, nt.fraction || 0)) * 100)}%` })));
      const facts = [];
      if (nt.average != null) facts.push(`${pct(nt.fraction)} % of ${nt.role === 'goal' ? 'goal' : 'target'}`);
      facts.push(`${nt.days_over} ${nt.days_over === 1 ? 'day' : 'days'} over`);
      if (nt.max_day) facts.push(`highest ${fmtMonthDay(nt.max_day.date)}: ${fmtNum(nt.max_day.value, key)}`);
      const foot = h('div', { class: 'period-foot' }, facts.join(' · '));
      if (change) foot.append(h('span', { class: `period-change ${tone}` }, `${change} vs previous ${sum.days} days`));
      else if (nt.average != null) foot.append(h('span', { class: 'period-change' }, `no data in the previous ${sum.days} days`));
      row.append(foot);
      grid.append(row);
    }
    body.append(grid);
    if (sum.interdialytic && sum.interdialytic.nutrients && Object.keys(sum.interdialytic.nutrients).length) {
      inter.hidden = false;
      inter.append(interdialyticBlock(sum.interdialytic, false));
    }
    for (const t of sum.notes || []) notes.append(h('li', {}, t));
  }
  function hasData(day) { return !!(day.totals && Object.values(day.totals).some((v) => v)); }
  function renderTrends() {
    const t = state.trends;
    if (!t) return;
    clear(chartsEl);
    const keys = new Set();
    for (const d of t.days) for (const k of Object.keys(d.status || {})) if (NUT[k]) keys.add(k);
    const ordered = [...keys].sort((a, b) => TREND_ORDER.indexOf(a) - TREND_ORDER.indexOf(b));
    if (!ordered.length) {
      chartsEl.append(h('p', { class: 'card empty-state' }, 'No targets set yet. Set targets in Profile to see trends.'));
      return;
    }
    const width = Math.max(240, Math.floor((chartsEl.clientWidth - (chartsEl.clientWidth >= 700 ? 12 : 0)) / (chartsEl.clientWidth >= 700 ? 2 : 1)) - 34);
    for (const key of ordered) chartsEl.append(chartCard(key, t.days, width));
  }
  function chartCard(key, days, width) {
    const n = NUT[key];
    const points = days.map((d) => {
      const st = (d.status && d.status[key]) || {};
      return { date: d.date, value: d.totals ? d.totals[key] || 0 : 0, level: st.level || 'ok', target: st.target, min: st.min, has: hasData(d) };
    });
    const last = [...points].reverse().find((p) => p.target != null) || {};
    const target = last.target;
    const min = last.min;
    const withData = points.filter((p) => p.has);
    const avg = withData.length ? withData.reduce((a, p) => a + p.value, 0) / withData.length : null;
    const overDays = withData.filter((p) => p.level === 'over').length;
    const card = h('section', { class: 'card chart-card', 'aria-labelledby': `chart-h-${key}` });
    card.append(h('div', { class: 'card-head' }, h('h3', { class: 'card-title', id: `chart-h-${key}` }, `${n.label} (${n.unit})`),
      h('span', { class: 'muted small tabular' }, target != null ? `target ${min != null ? `${fmtNum(min, key)}–` : ''}${fmtNum(target, key)}` : 'no target')));
    card.append(h('div', { class: 'chart-sub' },
      h('span', {}, avg != null ? `Average ${fmtNum(avg, key)} ${n.unit}` : 'No entries in this range'),
      withData.length ? h('span', {}, `${overDays} ${overDays === 1 ? 'day' : 'days'} over`) : null));
    card.append(barChart(key, points, target, min, width));
    // Table twin (values reachable without hover)
    const table = h('table', { class: 'data-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Date'), h('th', { class: 'num' }, n.unit), h('th', { class: 'num' }, '% of target'), h('th', {}, 'Level'))));
    const tb = h('tbody');
    for (const p of points) {
      tb.append(h('tr', {},
        h('td', {}, fmtDateShort(p.date)),
        h('td', { class: 'num' }, p.has ? fmtNum(p.value, key) : '—'),
        h('td', { class: 'num' }, p.has && target ? `${pct(p.value / target)} %` : '—'),
        h('td', {}, p.has ? h('span', { class: `lvl level-${p.level}` }, h('i', { class: 'swatch' }), LEVEL_TEXT[p.level]) : h('span', { class: 'muted' }, 'no entries'))));
    }
    table.append(tb);
    card.append(h('details', { class: 'inline-details' }, h('summary', {}, 'Show as table'), table));
    return card;
  }
  function barChart(key, points, target, min, width) {
    // Across a month boundary the day numbers restart at 1, so a second label line names the
    // month under the first labelled bar of each month (padB grows to make room for it).
    const spansMonths = new Set(points.map((p) => p.date.slice(0, 7))).size > 1;
    const padL = 46, padR = 10, padT = 14, padB = spansMonths ? 34 : 22, H = 128 + padB;
    const W = Math.max(220, width);
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const maxV = Math.max(target || 0, ...points.map((p) => p.value), 1);
    const yMax = target ? Math.max(target * 1.25, maxV * 1.05) : maxV * 1.1;
    const y = (v) => padT + plotH - (v / yMax) * plotH;
    const slot = plotW / points.length;
    const barW = Math.min(24, Math.max(3, slot - 4));
    const svg = s('svg', { class: 'chart-svg', viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group',
      'aria-label': `${NUT[key].label} per day for the last ${points.length} days${target ? `, target ${fmtNum(target, key)} ${NUT[key].unit}` : ''}` });
    // baseline + y labels
    svg.append(s('line', { class: 'axis', x1: padL, x2: W - padR, y1: y(0) + 0.5, y2: y(0) + 0.5 }));
    svg.append(s('text', { x: padL - 6, y: y(0) + 3, 'text-anchor': 'end' }, '0'));
    if (target) {
      svg.append(s('line', { class: 'target', x1: padL, x2: W - padR, y1: y(target), y2: y(target) }));
      svg.append(s('text', { x: padL - 6, y: y(target) + 3.5, 'text-anchor': 'end' }, fmtNum(target, key)));
      if (min != null) {
        svg.append(s('line', { class: 'target-min', x1: padL, x2: W - padR, y1: y(min), y2: y(min) }));
        svg.append(s('text', { x: padL - 6, y: y(min) + 3.5, 'text-anchor': 'end' }, fmtNum(min, key)));
      }
    }
    const labelEvery = slot >= 22 ? 1 : slot >= 12 ? 2 : slot >= 8 ? 3 : 5;
    let lastLabelledMonth = null;
    const cells = [];
    points.forEach((p, i) => {
      const x0 = padL + i * slot;
      const bx = x0 + (slot - barW) / 2;
      const bar = p.has ? roundedBar(bx, y(p.value), barW, y(0) - y(p.value), 4) : s('line', { class: 'nodata', x1: bx + 1, x2: bx + barW - 1, y1: y(0) - 1, y2: y(0) - 1 });
      bar.setAttribute('class', p.has ? `bar level-${p.level}` : 'nodata');
      const text = p.has ? `${fmtDateShort(p.date)}: ${fmtNum(p.value, key)} ${NUT[key].unit}${target ? ` (${pct(p.value / target)} % of target), ${LEVEL_TEXT[p.level]}` : ''}` : `${fmtDateShort(p.date)}: no entries`;
      const hit = s('rect', { class: 'hit', x: x0, y: padT - 4, width: slot, height: plotH + 4, rx: 4, tabindex: 0, role: 'img', 'aria-label': text });
      hit.append(s('title', {}, text));
      const show = () => { bar.style.opacity = '0.7'; showTip(hit, text, p); };
      const hide = () => { bar.style.opacity = ''; hideTip(); };
      // A mouse hovers each bar; touch and pen are handled for the whole chart below.
      hit.addEventListener('pointerenter', (ev) => { if (ev.pointerType === 'mouse') show(); });
      hit.addEventListener('pointerleave', (ev) => { if (ev.pointerType === 'mouse') hide(); });
      hit.addEventListener('focus', show); hit.addEventListener('blur', hide);
      cells.push({ bar, hit, text, p });
      svg.append(bar, hit);
      if ((points.length - 1 - i) % labelEvery === 0) {
        const d = parseDate(p.date);
        const labelY = spansMonths ? H - 18 : H - 6;
        svg.append(s('text', { x: x0 + slot / 2, y: labelY, 'text-anchor': 'middle' }, String(d.getDate())));
        const month = p.date.slice(0, 7);
        if (spansMonths && month !== lastLabelledMonth) {
          lastLabelledMonth = month;
          svg.append(s('text', { class: 'month', x: x0 + slot / 2, y: H - 6, 'text-anchor': 'middle' }, d.toLocaleDateString('en-US', { month: 'short' })));
        }
      }
    });
    // Touch and pen: press anywhere on the chart and slide sideways to read each day. At 30 days
    // a phone gives each bar about 8 px, too narrow to tap one reliably. The value stays shown
    // until the next tap elsewhere or a scroll.
    let active = -1;
    const release = () => { if (active >= 0) cells[active].bar.style.opacity = ''; active = -1; hideTip(); };
    const activate = (i) => {
      if (i === active) return;
      if (active >= 0) cells[active].bar.style.opacity = '';
      active = i;
      const c = cells[i];
      c.bar.style.opacity = '0.7';
      showTip(c.hit, c.text, c.p);
      touchTip = { svg, release };
    };
    const indexAt = (ev) => {
      const r = svg.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / (r.width || 1)) * W;
      return Math.max(0, Math.min(points.length - 1, Math.floor((x - padL) / slot)));
    };
    svg.addEventListener('pointerdown', (ev) => { if (ev.pointerType !== 'mouse') activate(indexAt(ev)); });
    svg.addEventListener('pointermove', (ev) => { if (ev.pointerType !== 'mouse' && active >= 0 && ev.buttons) activate(indexAt(ev)); });
    return svg;
  }
  let touchTip = null; // { svg, release } of the chart whose value a touch is showing
  function releaseTouchTip(ev) {
    if (!touchTip || (ev && ev.type === 'pointerdown' && touchTip.svg.contains(ev.target))) return;
    const t = touchTip;
    touchTip = null;
    t.release();
  }
  document.addEventListener('pointerdown', releaseTouchTip, true);
  window.addEventListener('scroll', () => releaseTouchTip(), { passive: true });
  function roundedBar(x, yTop, w, hgt, r) {
    if (hgt <= r || w <= 2 * r) return s('rect', { x, y: yTop, width: w, height: Math.max(hgt, 1), rx: Math.min(r, hgt / 2) });
    const d = `M${x},${yTop + hgt} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + w - r} Q${x + w},${yTop} ${x + w},${yTop + r} V${yTop + hgt} Z`;
    return s('path', { d });
  }
  function showTip(anchor, text, p) {
    clear(chartTip);
    const [datePart, rest] = text.split(': ');
    chartTip.append(h('div', {}, h('b', {}, rest || datePart)), rest ? h('div', { class: 'small' }, datePart) : null);
    chartTip.hidden = false;
    const r = anchor.getBoundingClientRect();
    const tw = chartTip.offsetWidth, th = chartTip.offsetHeight;
    let left = r.left + r.width / 2 - tw / 2;
    left = Math.max(8, Math.min(window.innerWidth - tw - 8, left));
    let top = r.top - th - 8;
    if (top < 8) top = r.bottom + 8;
    chartTip.style.left = `${left}px`; chartTip.style.top = `${top}px`;
    void p;
  }
  function hideTip() { chartTip.hidden = true; }
  let resizeRaf = 0;
  window.addEventListener('resize', () => {
    if (state.view !== 'trends' || !state.trends) return;
    cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(renderTrends);
  });

  // ---------------------------------------------------------------------------
  // PROFILE view
  // ---------------------------------------------------------------------------
  const profileForm = $('#profile-form');
  (function buildDialysisDays() {
    const box = $('#pf-dialysis-days');
    WEEKDAYS.forEach((d, i) => {
      box.append(h('label', { class: 'wd-check', for: `pf-dd-${i}` },
        h('input', { type: 'checkbox', id: `pf-dd-${i}`, value: i, 'data-weekday': i }),
        h('span', {}, h('span', { class: 'sr-only' }, WEEKDAYS_LONG[i]), h('span', { 'aria-hidden': 'true' }, d))));
    });
  })();
  function syncDialysisDaysVisibility() { $('#pf-dialysis-days-field').hidden = $('#pf-dialysis').value !== 'hemodialysis'; }
  $('#pf-dialysis').addEventListener('change', syncDialysisDaysVisibility);
  function selectedDialysisDays() { return $$('#pf-dialysis-days input:checked').map((c) => Number(c.dataset.weekday)).sort(); }
  function renderProfile() {
    const p = state.profile;
    if (!p) return;
    $('#pf-name').value = p.name || '';
    $('#pf-weight').value = p.weight_kg ?? '';
    $('#pf-height').value = p.height_cm ?? '';
    $('#pf-stage').value = p.ckd_stage || '3b';
    $('#pf-dialysis').value = p.dialysis || 'none';
    $('#pf-diabetes').value = p.diabetes || 'type1';
    $('#pf-warn').value = Math.round((p.warn_fraction ?? 0.8) * 100);
    $('#pf-week-start').value = p.week_start === 'sunday' ? 'sunday' : 'monday';
    const dd = new Set((p.dialysis_days || []).map(Number));
    $$('#pf-dialysis-days input').forEach((c) => { c.checked = dd.has(Number(c.dataset.weekday)); });
    syncDialysisDaysVisibility();
    fillTargets(p.targets || {});
    $('#pf-theme').value = storedTheme();
    $('#suggest-notes').hidden = true;
    renderTargetsStale();
    // A fresh database already has a profile row (with a creation timestamp); only call it
    // "saved" once the person has actually stored something.
    const hasContent = p.weight_kg != null || p.height_cm != null || !!p.name || Object.values(p.targets || {}).some((v) => v != null);
    $('#profile-saved').textContent = p.updated_at && hasContent ? `Last saved ${new Date(p.updated_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}` : '';
  }
  function fillTargets(targets) {
    for (const inp of $$('input[data-target]')) {
      const v = targets[inp.dataset.target];
      inp.value = typeof v === 'number' ? v : v && typeof v === 'object' && v.max != null ? v.max : '';
    }
    const pr = targets.protein_g;
    $('#tg-protein_min').value = pr && typeof pr === 'object' && pr.min != null ? pr.min : '';
    $('#tg-protein_max').value = pr == null ? '' : typeof pr === 'object' ? (pr.max ?? '') : pr;
  }
  function readTargets() {
    const targets = {};
    for (const inp of $$('input[data-target]')) targets[inp.dataset.target] = numOrNull(inp.value);
    const pmin = numOrNull($('#tg-protein_min').value), pmax = numOrNull($('#tg-protein_max').value);
    if (pmin == null && pmax == null) targets.protein_g = null;
    else if (pmin == null) targets.protein_g = pmax;
    else if (pmax == null) { const err = new Error('Protein needs a maximum when a minimum is set'); err.detail = err.message; throw err; }
    else if (pmin > pmax) { const err = new Error('Protein minimum must not exceed the maximum'); err.detail = err.message; throw err; }
    else targets.protein_g = { min: pmin, max: pmax };
    return targets;
  }
  onSubmit(profileForm, async (e) => {
    e.preventDefault();
    let targets;
    try { targets = readTargets(); } catch (err) { toastError(err); $('#tg-protein_max').focus(); return; }
    const warnPct = numOrNull($('#pf-warn').value);
    const body = {
      name: $('#pf-name').value.trim(),
      weight_kg: numOrNull($('#pf-weight').value),
      height_cm: numOrNull($('#pf-height').value),
      ckd_stage: $('#pf-stage').value,
      dialysis: $('#pf-dialysis').value,
      diabetes: $('#pf-diabetes').value,
      warn_fraction: warnPct != null ? Math.min(1, Math.max(0.5, warnPct / 100)) : 0.8,
      targets,
      dialysis_days: $('#pf-dialysis').value === 'hemodialysis' ? selectedDialysisDays() : [],
      week_start: $('#pf-week-start').value === 'sunday' ? 'sunday' : 'monday',
    };
    const btn = $('#btn-save-profile');
    const before = state.profile;
    btn.disabled = true;
    try {
      state.profile = await api.saveProfile(body);
      // Targets are not recomputed when the stage or dialysis changes (they may come from the
      // care team); say so until the targets are saved again or the notice is dismissed, and
      // offer the suggestion for the new setting to review.
      const now = state.profile;
      if (before && (before.ckd_stage !== now.ckd_stage || before.dialysis !== now.dialysis)) {
        state.targetsStale = { from: state.targetsStale ? state.targetsStale.from : before, to: now };
        if (state.targetsStale.from.ckd_stage === now.ckd_stage && state.targetsStale.from.dialysis === now.dialysis) state.targetsStale = null; // changed back
      } else if (state.targetsStale && before && JSON.stringify(before.targets) !== JSON.stringify(now.targets)) state.targetsStale = null;
      else if (state.targetsStale) state.targetsStale.to = now;
      renderProfile();
      state.dayLoadedFor = null; state.trends = null; state.summary = null; state.plan = null; state.planStart = null; state.shopping = null;
      toast('Profile saved', 'ok');
    } catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  });
  function settingText(p) {
    const mode = { hemodialysis: 'on hemodialysis', peritoneal: 'on peritoneal dialysis' }[p.dialysis] || 'without dialysis';
    return `CKD stage ${p.ckd_stage} ${mode}`;
  }
  function renderTargetsStale() {
    const st = state.targetsStale;
    $('#targets-stale').hidden = !st;
    if (st) {
      $('#targets-stale-msg').textContent = `You changed from ${settingText(st.from)} to ${settingText(st.to)}. Your daily targets below have not changed. `
        + 'Suggested starting points depend on stage and dialysis: review them for the new setting, or keep the targets your care team gave you.';
    }
  }
  $('#targets-stale-keep').addEventListener('click', () => { state.targetsStale = null; renderTargetsStale(); $('#btn-suggest').focus(); });
  $('#targets-stale-suggest').addEventListener('click', () => suggestTargetsIntoForm({ fromNotice: true }));
  $('#btn-suggest').addEventListener('click', () => suggestTargetsIntoForm());
  async function suggestTargetsIntoForm({ fromNotice = false } = {}) {
    const btn = fromNotice ? $('#targets-stale-suggest') : $('#btn-suggest');
    // The endpoint computes from the *saved* profile; check the form first so the person is
    // told what to do in plain words instead of seeing the server's 400 (finding: raw field name),
    // and is not handed numbers for a stage or dialysis setting the form no longer shows.
    const weight = numOrNull($('#pf-weight').value);
    const height = numOrNull($('#pf-height').value);
    const saved = state.profile || {};
    if (weight == null) { toast('Enter your weight (kg) first; the suggestions are per kg of body weight', 'error'); $('#pf-weight').focus(); return; }
    if (saved.weight_kg == null || Number(saved.weight_kg) !== weight || (saved.height_cm ?? null) !== height) {
      toast('Save profile first so the suggestion uses your weight and height', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    if ($('#pf-stage').value !== saved.ckd_stage || $('#pf-dialysis').value !== saved.dialysis || $('#pf-diabetes').value !== saved.diabetes) {
      toast('Save profile first so the suggestion uses your stage and dialysis setting', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    btn.disabled = true;
    try {
      const res = await api.suggested();
      fillTargets(res.targets || {});
      const notes = $('#suggest-notes');
      clear(notes);
      notes.append(h('div', { class: 'notes-title' }, `Suggested starting points for ${settingText(saved)} filled in below (not saved yet). Discuss with your care team, then press Save profile.`));
      if (res.notes && res.notes.length) notes.append(h('ul', {}, res.notes.map((t) => h('li', {}, t))));
      notes.hidden = false;
      state.targetsStale = null; // the suggestion for the saved setting is in the form now
      renderTargetsStale();
      if (fromNotice) notes.focus();
      toast('Targets suggested; review and save', 'ok');
    } catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  }

  // ---------------------------------------------------------------------------
  // PLAN view: 7-day grid, saved meals, shopping list
  // ---------------------------------------------------------------------------
  const planGridEl = $('#plan-grid');
  const savedMealsEl = $('#saved-meals');
  const shoppingEl = $('#shopping-list');
  let planRequest = 0;

  function closeIcon() {
    return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { d: 'M6 6l12 12M18 6L6 18', stroke: 'currentColor', 'stroke-width': 2.2, 'stroke-linecap': 'round' }));
  }
  function fmtTimes(n) { return `${(Math.round(n * 100) / 100).toLocaleString('en-US', { maximumFractionDigits: 2 })}×`; }
  function weekStartPref() { return state.profile && state.profile.week_start === 'sunday' ? 'sunday' : 'monday'; }
  function currentWeekStart() { return weekStartOf(todayStr(), weekStartPref()); }
  function ensurePlanStart() {
    if (!state.planStart) state.planStart = currentWeekStart();
    return state.planStart;
  }
  // After the log changed on `date`, refresh whatever view is showing and drop caches.
  function afterLogChange(date, { goToDay = false } = {}) {
    state.dayLoadedFor = null; state.trends = null; state.summary = null;
    if (goToDay) { state.date = date; showView('today'); return; }
    if (state.view === 'plan') loadPlan();
    else if (state.view === 'today') { if (date && date !== state.date) setDate(date); else loadDay(); }
    else if (state.view === 'trends') loadTrends();
  }

  $('#week-prev').addEventListener('click', () => { state.planStart = addDays(ensurePlanStart(), -7); loadPlan(); });
  $('#week-next').addEventListener('click', () => { state.planStart = addDays(ensurePlanStart(), 7); loadPlan(); });
  $('#week-this').addEventListener('click', () => { state.planStart = currentWeekStart(); loadPlan(); });
  $('#btn-copy-day').addEventListener('click', (e) => openCopySheet({ from: state.date || todayStr(), trigger: e.currentTarget }));
  $('#btn-new-meal').addEventListener('click', (e) => openMealEditor(null, e.currentTarget));

  async function loadPlan() {
    const reqId = ++planRequest;
    try { await loadProfile(); } catch (e) { toastError(e); }
    const start = ensurePlanStart();
    const end = addDays(start, 6);
    const thisWeek = currentWeekStart();
    $('#week-label').textContent = start === thisWeek ? 'This week' : start === addDays(thisWeek, 7) ? 'Next week' : start === addDays(thisWeek, -7) ? 'Last week' : `Week of ${fmtMonthDay(start)}`;
    $('#week-range').textContent = fmtRange(start, end);
    $('#week-this').hidden = start === thisWeek;
    planGridEl.style.opacity = state.plan ? '0.6' : '';
    const [rangeRes, mealsRes, shopRes] = await Promise.allSettled([api.range(start, end), loadMeals(true), api.shopping(start, end)]);
    if (reqId !== planRequest) return;
    planGridEl.style.opacity = '';
    if (rangeRes.status === 'fulfilled') { state.plan = { start, end, days: rangeRes.value.days || [] }; renderPlanGrid(); }
    else { toastError(rangeRes.reason); clear(planGridEl); planGridEl.append(h('p', { class: 'card empty-state' }, 'Could not load this week.')); }
    if (mealsRes.status === 'fulfilled') renderSavedMeals(); else toastError(mealsRes.reason);
    if (shopRes.status === 'fulfilled') { state.shopping = { start, end, items: shopRes.value.items || [] }; renderShopping(); }
    else toastError(shopRes.reason);
  }

  function renderPlanGrid() {
    const plan = state.plan;
    if (!plan) return;
    clear(planGridEl);
    const today = todayStr();
    const prof = state.profile || {};
    const dd = prof.dialysis === 'hemodialysis' ? (prof.dialysis_days || []).map(Number) : [];
    const byDate = Object.fromEntries(plan.days.map((d) => [d.date, d]));
    for (let i = 0; i < 7; i++) {
      const date = addDays(plan.start, i);
      const d = byDate[date] || { date, totals: {}, planned_totals: {}, projected_totals: {}, status: {}, projected_status: {}, counts: { eaten: 0, planned: 0 } };
      const counts = d.counts || { eaten: 0, planned: 0 };
      const isToday = date === today, isPast = date < today;
      const dial = dd.includes(weekdayMon(date));
      const card = h('article', { class: `plan-day${isToday ? ' today' : ''}${isPast ? ' past' : ''}${dial ? ' dialysis' : ''}`, role: 'listitem' });
      const open = h('button', { class: 'plan-day-open', type: 'button',
        'aria-label': `${fmtDateLong(date)}${dial ? ', dialysis day' : ''}: ${counts.eaten} eaten, ${counts.planned} planned. Open in Today` });
      open.append(h('div', { class: 'plan-day-head' },
        h('div', { class: 'plan-day-date' }, h('span', { class: 'plan-wd' }, WEEKDAYS[weekdayMon(date)]), h('span', { class: 'plan-dnum' }, String(parseDate(date).getDate()))),
        h('div', { class: 'plan-day-badges' },
          isToday ? h('span', { class: 'badge today' }, 'Today') : null,
          dial ? h('span', { class: 'badge dialysis', title: 'Dialysis day' }, 'Dialysis') : null)));
      const chips = h('div', { class: 'plan-chips' });
      const pst = d.projected_status || d.status || {};
      const totals = d.projected_totals || d.totals || {};
      const hasEntries = counts.eaten + counts.planned > 0;
      let any = false;
      for (const key of PLAN_CHIPS) {
        const st = pst[key];
        if (!st || !hasEntries) continue;
        any = true;
        const n = NUT[key];
        const val = st.value != null ? st.value : totals[key] || 0;
        chips.append(h('span', { class: `plan-chip level-${st.level || 'ok'}`, role: 'img',
          title: `${n.label}: projected ${fmtNum(val, key)} of ${fmtNum(st.target, key)} ${n.unit} (${pct(st.fraction)} %)`,
          'aria-label': `${n.label} ${fmtNum(val, key)} of ${fmtNum(st.target, key)} ${n.unit}, ${LEVEL_TEXT[st.level || 'ok']}` },
          h('i', { class: 'swatch', 'aria-hidden': 'true' }), h('span', { class: 'plan-chip-k' }, n.short), h('b', {}, fmtNum(val, key))));
      }
      if (!any) chips.append(h('span', { class: 'muted small plan-empty' }, hasEntries ? 'No targets set' : isPast ? 'Nothing logged' : 'Nothing planned yet'));
      open.append(chips);
      const cnt = h('div', { class: 'plan-counts' });
      if (counts.eaten) cnt.append(h('span', { class: 'count eaten' }, checkIcon(), `${counts.eaten} eaten`));
      if (counts.planned) cnt.append(h('span', { class: 'count planned' }, dashedIcon(), `${counts.planned} planned`));
      if (hasEntries) open.append(cnt);
      open.addEventListener('click', () => openDay(date));
      card.append(open);
      card.append(h('div', { class: 'plan-day-foot' },
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openApplySheet({ date, meal: isToday ? defaultMealForNow() : 'breakfast', status: defaultStatusFor(date), trigger: ev.currentTarget }) }, plusIcon(), 'Saved meal'),
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openCopySheet({ from: date, trigger: ev.currentTarget }) }, 'Copy…')));
      planGridEl.append(card);
    }
  }

  // ---- Saved meals list ----------------------------------------------------
  function renderSavedMeals() {
    clear(savedMealsEl);
    const meals = state.meals || [];
    if (!meals.length) {
      savedMealsEl.append(h('li', { class: 'empty-state' }, 'No saved meals yet. Create one here, or use "Save as meal" under a meal in Today.'));
      return;
    }
    for (const t of meals) {
      const li = h('li', { class: 'saved-meal' });
      const nums = h('div', { class: 'row-nums' });
      for (const k of ROW_NUMBERS) nums.append(h('span', { class: 'n' }, `${NUT[k].short} `, h('b', {}, fmtNum(t.totals[k], k)), ` ${NUT[k].unit}`));
      li.append(h('div', { class: 'saved-meal-main' },
        ratingIcon(t.kidney_rating),
        h('div', { class: 'row-main' },
          h('div', { class: 'row-title' }, t.name),
          h('div', { class: 'row-sub' }, t.items.map((it) => `${fmtTimes(it.servings)} ${it.food_name}${it.hidden ? ' (hidden food)' : ''}`).join(', ')),
          t.note ? h('div', { class: 'entry-note' }, t.note) : null,
          nums)));
      li.append(h('div', { class: 'saved-meal-actions' },
        h('button', { class: 'btn secondary', type: 'button', onclick: (ev) => openApplySheet({ mealId: t.id, trigger: ev.currentTarget }) }, plusIcon(), 'Add to a day'),
        h('button', { class: 'link-btn', type: 'button', onclick: (ev) => openMealEditor(t, ev.currentTarget) }, 'Edit'),
        h('button', { class: 'link-btn danger-link', type: 'button', 'aria-label': `Delete saved meal ${t.name}`,
          onclick: (ev) => confirmDeleteSavedMeal(t, ev.currentTarget.parentElement, ev.currentTarget) }, 'Delete')));
      savedMealsEl.append(li);
    }
  }
  async function deleteSavedMeal(t) {
    try {
      await api.deleteMeal(t.id);
      toast(`Saved meal "${t.name}" deleted`, 'ok');
      await loadMeals(true);
      renderSavedMeals();
      return true;
    } catch (err) { toastError(err); return false; }
  }
  function confirmDeleteSavedMeal(t, host, trigger, after) {
    inlineConfirm(host, trigger, {
      message: `Delete the saved meal "${t.name}"? Logged entries are not affected.`,
      confirmText: 'Delete meal',
      onConfirm: async () => {
        const ok = await deleteSavedMeal(t);
        if (ok) { if (after) after(); else $('#btn-new-meal').focus(); }
        return ok;
      },
    });
  }

  // ---- Shopping list (checks live only in localStorage) --------------------
  function shopKey(start) { return `${SHOP_KEY}:${start}`; }
  // Ticks live in memory for the session (keyed by week start) and are mirrored to localStorage
  // when it works, so they survive view reloads even where storage is blocked (sandboxed frame).
  const memChecks = new Map();
  function loadChecks(start) {
    if (!memChecks.has(start)) {
      let stored = [];
      try { const v = JSON.parse(localStorage.getItem(shopKey(start)) || '[]'); if (Array.isArray(v)) stored = v; } catch (e) { /* storage unavailable */ }
      memChecks.set(start, stored);
    }
    return new Set(memChecks.get(start));
  }
  function saveChecks(start, set) {
    memChecks.set(start, [...set]);
    try { if (set.size) localStorage.setItem(shopKey(start), JSON.stringify([...set])); else localStorage.removeItem(shopKey(start)); } catch (e) { /* storage unavailable */ }
  }
  $('#shopping-clear').addEventListener('click', () => { if (state.shopping) { saveChecks(state.shopping.start, new Set()); renderShopping(); } });
  function renderShopping() {
    const sh = state.shopping;
    if (!sh) return;
    clear(shoppingEl);
    const checks = loadChecks(sh.start);
    const items = sh.items || [];
    $('#shopping-sub').textContent = items.length ? `${items.length} ${items.length === 1 ? 'food' : 'foods'} · ${fmtRange(sh.start, sh.end)}` : fmtRange(sh.start, sh.end);
    $('#shopping-clear').hidden = !items.length || !checks.size;
    if (!items.length) {
      shoppingEl.append(h('li', { class: 'empty-state' }, 'Nothing planned this week yet. Plan foods on a day, or add a saved meal, to build the list.'));
      return;
    }
    for (const it of items) {
      const id = `shop-${sh.start}-${it.food_id}`;
      const checked = checks.has(it.food_id);
      const cb = h('input', { type: 'checkbox', id, checked: checked || null });
      const li = h('li', { class: `shop-item${checked ? ' done' : ''}` },
        h('label', { class: 'check shop-check', for: id }, cb,
          h('span', { class: 'check-text' },
            h('span', { class: 'shop-name' }, it.food_name),
            h('span', { class: 'hint' }, `${fmtServings(it.servings)}${it.serving_desc ? ` of ${it.serving_desc}` : ''}${it.grams ? ` · ${fmtNum(it.grams, 'fluid_ml')} g` : ''} · ${it.days} ${it.days === 1 ? 'day' : 'days'}`))));
      cb.addEventListener('change', () => {
        if (cb.checked) checks.add(it.food_id); else checks.delete(it.food_id);
        saveChecks(sh.start, checks);
        li.classList.toggle('done', cb.checked);
        $('#shopping-clear').hidden = !checks.size;
      });
      shoppingEl.append(li);
    }
  }

  // ---- Copy day sheet -------------------------------------------------------
  const copyDlg = $('#sheet-copy');
  setupDialog(copyDlg);
  let copyBusy = false;
  function openCopySheet({ from, to, trigger } = {}) {
    const f = from || state.date || todayStr();
    $('#copy-from').value = f;
    $('#copy-to').value = to || addDays(f, 1);
    $$('#copy-meals input').forEach((c) => { c.checked = true; });
    $('#copy-include').value = 'all';
    setStatus($('#copy-status'), 'planned');
    updateCopySummary();
    openDialog(copyDlg, trigger, $('#copy-to'));
  }
  function updateCopySummary() {
    const f = $('#copy-from').value, t = $('#copy-to').value;
    const el = $('#copy-summary');
    if (!f || !t) { el.textContent = ''; return; }
    el.textContent = f === t ? 'Choose two different days.' : `${fmtDateLong(f)} → ${fmtDateLong(t)}`;
  }
  $('#copy-from').addEventListener('change', updateCopySummary);
  $('#copy-to').addEventListener('change', updateCopySummary);
  onSubmit($('#copy-form'), async (e) => {
    e.preventDefault();
    if (copyBusy) return;
    const from_date = $('#copy-from').value, to_date = $('#copy-to').value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from_date) || !/^\d{4}-\d{2}-\d{2}$/.test(to_date)) { toast('Pick both dates', 'error'); return; }
    if (from_date === to_date) { toast('Choose two different days', 'error'); $('#copy-to').focus(); return; }
    const meals = $$('#copy-meals input:checked').map((c) => c.value);
    if (!meals.length) { toast('Pick at least one meal', 'error'); return; }
    const body = { from_date, to_date, include: $('#copy-include').value, status: selectedStatus($('#copy-status')) };
    if (meals.length < MEALS.length) body.meals = meals;
    copyBusy = true; $('#copy-save').disabled = true;
    try {
      const res = await api.copyDay(body);
      copyDlg.close();
      const n = res && typeof res.created === 'number' ? res.created : (res && res.entries ? res.entries.length : 0);
      toast(n ? `Copied ${n} ${n === 1 ? 'entry' : 'entries'} to ${fmtDateLong(to_date)} as ${body.status}` : 'Nothing to copy from that day', n ? 'ok' : '');
      if (n) afterLogChange(to_date);
    } catch (err) { toastError(err); }
    finally { copyBusy = false; $('#copy-save').disabled = false; }
  });

  // ---- Apply saved meal sheet ----------------------------------------------
  const applyDlg = $('#sheet-apply');
  setupDialog(applyDlg);
  let applyBusy = false;
  let applyStatusTouched = false; // until the person picks a status, it follows the chosen date (past/today → eaten, future → planned)
  $('#apply-status').addEventListener('change', () => { applyStatusTouched = true; });
  $('#apply-date').addEventListener('input', () => {
    const d = $('#apply-date').value;
    if (!applyStatusTouched && /^\d{4}-\d{2}-\d{2}$/.test(d)) setStatus($('#apply-status'), defaultStatusFor(d));
  });
  async function openApplySheet({ mealId, date, meal, status, trigger } = {}) {
    try { await loadMeals(); } catch (e) { toastError(e); return; }
    const meals = state.meals || [];
    if (!meals.length) {
      toast('No saved meals yet. Create one in Plan, or use "Save as meal" under a meal in Today.');
      return;
    }
    const sel = $('#apply-meal-id');
    clear(sel);
    for (const t of meals) sel.append(h('option', { value: t.id }, `${t.name} (${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'})`));
    const chosen = meals.find((t) => t.id === Number(mealId)) || meals[0];
    sel.value = String(chosen.id);
    const d = date || state.date || todayStr();
    $('#apply-date').value = d;
    $('#apply-scale').value = '1';
    setMeal($('#apply-meal'), meal || defaultMealForNow());
    setStatus($('#apply-status'), status || defaultStatusFor(d));
    applyStatusTouched = !!status;
    updateApplyPreview();
    openDialog(applyDlg, trigger, mealId ? $('#apply-date') : sel);
  }
  function applyTemplate() { return (state.meals || []).find((t) => t.id === Number($('#apply-meal-id').value)) || null; }
  function updateApplyPreview() {
    const t = applyTemplate();
    const items = clear($('#apply-items'));
    const key = clear($('#apply-preview-key'));
    const box = clear($('#apply-warnings'));
    if (!t) return;
    const scale = Number($('#apply-scale').value) > 0 ? Number($('#apply-scale').value) : 1;
    $('#sheet-apply-title').textContent = `Add “${t.name}”`;
    $('#sheet-apply-sub').textContent = t.note ? t.note : 'Logs every food in the saved meal onto one day.';
    $('#apply-preview-amount').textContent = scale === 1 ? `${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'}` : `${t.items.length} foods × ${scale}`;
    for (const it of t.items) {
      items.append(h('li', {}, ratingIcon(it.kidney_rating, { decorative: true }),
        h('span', { class: 'ci-name' }, it.food_name, it.hidden ? h('span', { class: 'food-source' }, 'hidden') : null),
        h('span', { class: 'ci-amt muted' }, fmtServings(it.servings * scale))));
    }
    const scaled = scaledNutrients(t.totals, scale);
    for (const k of KEY_NUMBERS) key.append(h('div', { class: 'kn' }, h('span', { class: 'kn-v' }, fmtNum(scaled[k], k)), h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    const date = $('#apply-date').value;
    if (state.day && state.dayLoadedFor === date) {
      const impact = impactOn(state.day, scaled, selectedMeal($('#apply-meal')), { status: selectedStatus($('#apply-status')) });
      for (const it of impact) {
        box.append(h('div', { class: `warning level-${it.level}` }, ratingIcon(it.level, { label: LEVEL_TEXT[it.level] }),
          h('div', {}, h('span', { class: 'w-level' }, it.level === 'over' ? 'Day total over. ' : 'Day total near limit. '), it.message)));
      }
    }
  }
  $('#apply-form').addEventListener('input', updateApplyPreview);
  $('#apply-form').addEventListener('change', updateApplyPreview);
  onSubmit($('#apply-form'), async (e) => {
    e.preventDefault();
    if (applyBusy) return;
    const t = applyTemplate();
    if (!t) return;
    const date = $('#apply-date').value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { toast('Pick a date', 'error'); $('#apply-date').focus(); return; }
    const scale = Number($('#apply-scale').value);
    if (!(scale > 0)) { toast('Scale must be more than 0', 'error'); $('#apply-scale').focus(); return; }
    const body = { date, meal: selectedMeal($('#apply-meal')), status: selectedStatus($('#apply-status')) };
    if (scale !== 1) body.scale = scale;
    applyBusy = true; $('#apply-save').disabled = true;
    try {
      const res = await api.applyMeal(t.id, body);
      applyDlg.close();
      const n = res && res.entries ? res.entries.length : t.items.length;
      toast(`${body.status === 'planned' ? 'Planned' : 'Added'} ${t.name} (${n} ${n === 1 ? 'food' : 'foods'}) for ${MEAL_LABEL[body.meal].toLowerCase()}, ${fmtDateLong(date)}`, 'ok');
      afterLogChange(date, { goToDay: state.view === 'add' });
    } catch (err) { toastError(err); }
    finally { applyBusy = false; $('#apply-save').disabled = false; }
  });

  // ---- Save a logged meal as a template ------------------------------------
  const saveMealDlg = $('#sheet-savemeal');
  setupDialog(saveMealDlg);
  const saveMealState = { date: null, meal: null, busy: false };
  function openSaveMealSheet(date, meal, entries, trigger) {
    saveMealState.date = date; saveMealState.meal = meal;
    $('#savemeal-name').value = '';
    $('#savemeal-note').value = '';
    $('#sheet-savemeal-sub').textContent = `${MEAL_LABEL[meal]} on ${fmtDateLong(date)} · ${entries.length} ${entries.length === 1 ? 'food' : 'foods'}`;
    const ul = clear($('#savemeal-items'));
    for (const e of entries) {
      ul.append(h('li', {}, ratingIcon(e.kidney_rating, { decorative: true }),
        h('span', { class: 'ci-name' }, e.food_name, isPlanned(e) ? h('span', { class: 'badge planned' }, 'planned') : null),
        h('span', { class: 'ci-amt muted' }, fmtServings(e.servings))));
    }
    openDialog(saveMealDlg, trigger, $('#savemeal-name'));
  }
  onSubmit($('#savemeal-form'), async (e) => {
    e.preventDefault();
    if (saveMealState.busy) return;
    const name = $('#savemeal-name').value.trim();
    if (!name) { toast('Give the meal a name', 'error'); $('#savemeal-name').focus(); return; }
    saveMealState.busy = true; $('#savemeal-save').disabled = true;
    try {
      const t = await api.mealFromLog({ date: saveMealState.date, meal: saveMealState.meal, name, note: $('#savemeal-note').value.trim() || null });
      saveMealDlg.close();
      state.meals = null;
      toast(`Saved “${t.name}” (${t.items.length} ${t.items.length === 1 ? 'food' : 'foods'}). Find it under Plan.`, 'ok');
    } catch (err) { toastError(err); }
    finally { saveMealState.busy = false; $('#savemeal-save').disabled = false; }
  });

  // ---- Saved meal editor (create / edit) -----------------------------------
  const mealDlg = $('#sheet-meal');
  setupDialog(mealDlg);
  const mealEd = { id: null, items: [], busy: false, search: 0 };
  function perServingOfItem(it) {
    const out = {};
    for (const n of NUTRIENTS) { const v = it.nutrients ? it.nutrients[n.key] : null; out[n.key] = v == null || !it.servings ? v : v / it.servings; }
    return out;
  }
  function openMealEditor(t, trigger) {
    mealEd.id = t ? t.id : null;
    mealEd.items = t ? t.items.map((it) => ({ food_id: it.food_id, food_name: it.food_name, serving_desc: it.serving_desc, servings: it.servings,
      per: perServingOfItem(it), kidney_rating: it.kidney_rating, hidden: !!it.hidden })) : [];
    $('#sheet-meal-title').textContent = t ? 'Edit saved meal' : 'New saved meal';
    $('#meal-name').value = t ? t.name : '';
    $('#meal-note').value = t && t.note ? t.note : '';
    $('#meal-delete').hidden = !t;
    $('#meal-search').value = '';
    clear($('#meal-search-results'));
    renderMealItems();
    openDialog(mealDlg, trigger, $('#meal-name'));
  }
  function renderMealItems() {
    const ul = clear($('#meal-items'));
    if (!mealEd.items.length) ul.append(h('li', { class: 'empty-state' }, 'No foods yet. Search below to add some.'));
    mealEd.items.forEach((it, idx) => {
      const inp = h('input', { type: 'number', inputmode: 'decimal', min: 0.25, step: 0.25, value: String(it.servings), 'aria-label': `Servings of ${it.food_name}` });
      inp.addEventListener('input', () => { const v = Number(inp.value); if (v > 0) { it.servings = v; renderMealTotals(); } });
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });
      const rm = h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Remove ${it.food_name}` }, closeIcon());
      rm.addEventListener('click', () => { mealEd.items.splice(idx, 1); renderMealItems(); });
      ul.append(h('li', { class: 'meal-item' }, ratingIcon(it.kidney_rating, { decorative: true }),
        h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, it.food_name, it.hidden ? h('span', { class: 'food-source' }, 'hidden') : null), h('div', { class: 'row-sub' }, it.serving_desc || '')),
        h('div', { class: 'meal-item-sv' }, inp, h('span', { class: 'muted small' }, 'srv')),
        rm));
    });
    renderMealTotals();
  }
  function renderMealTotals() {
    const totals = Object.fromEntries(NUTRIENTS.map((n) => [n.key, 0]));
    for (const it of mealEd.items) for (const n of NUTRIENTS) totals[n.key] += (it.per[n.key] || 0) * it.servings;
    const key = clear($('#meal-preview-key'));
    for (const k of KEY_NUMBERS) key.append(h('div', { class: 'kn' }, h('span', { class: 'kn-v' }, fmtNum(totals[k], k)), h('span', { class: 'kn-u' }, NUT[k].unit), h('span', { class: 'kn-l' }, NUT[k].short)));
    $('#meal-preview-count').textContent = `${mealEd.items.length} ${mealEd.items.length === 1 ? 'food' : 'foods'}`;
  }
  async function runMealSearch() {
    const q = $('#meal-search').value.trim();
    const reqId = ++mealEd.search;
    const ul = $('#meal-search-results');
    if (!q) { clear(ul); return; }
    try {
      const res = await api.foods({ q, limit: 8 });
      if (reqId !== mealEd.search) return;
      clear(ul);
      const foods = res.foods || [];
      if (!foods.length) ul.append(h('li', { class: 'empty-state' }, 'No foods match.'));
      for (const f of foods) {
        const b = h('button', { class: 'row-btn compact', type: 'button' }, ratingIcon(f.kidney_rating, { decorative: true }),
          h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, f.name), h('div', { class: 'row-sub' }, f.serving_desc)),
          h('span', { class: 'add-word' }, plusIcon(), 'Add'));
        b.addEventListener('click', () => {
          const existing = mealEd.items.find((it) => it.food_id === f.id);
          if (existing) existing.servings = Math.round((existing.servings + 1) * 100) / 100;
          else mealEd.items.push({ food_id: f.id, food_name: f.name, serving_desc: f.serving_desc, servings: 1, per: f.nutrients, kidney_rating: f.kidney_rating, hidden: false });
          renderMealItems();
          $('#meal-search').value = '';
          clear(ul);
          $('#meal-search').focus();
        });
        ul.append(h('li', {}, b));
      }
    } catch (err) { if (reqId === mealEd.search) toastError(err); }
  }
  $('#meal-search').addEventListener('input', debounce(runMealSearch, 200));
  $('#meal-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); runMealSearch(); } });
  onSubmit($('#meal-form'), async (e) => {
    e.preventDefault();
    if (mealEd.busy) return;
    const name = $('#meal-name').value.trim();
    if (!name) { toast('Give the meal a name', 'error'); $('#meal-name').focus(); return; }
    if (!mealEd.items.length) { toast('Add at least one food', 'error'); $('#meal-search').focus(); return; }
    const body = { name, note: $('#meal-note').value.trim() || null, items: mealEd.items.map((it) => ({ food_id: it.food_id, servings: it.servings })) };
    mealEd.busy = true; $('#meal-save').disabled = true;
    try {
      const t = mealEd.id != null ? await api.updateMeal(mealEd.id, body) : await api.createMeal(body);
      mealDlg.close();
      toast(`Saved “${t.name}”`, 'ok');
      await loadMeals(true);
      renderSavedMeals();
      if (state.view === 'add') renderSavedShortcuts();
    } catch (err) { toastError(err); }
    finally { mealEd.busy = false; $('#meal-save').disabled = false; }
  });
  $('#meal-delete').addEventListener('click', (ev) => {
    if (mealEd.id == null) return;
    const t = (state.meals || []).find((x) => x.id === mealEd.id) || { id: mealEd.id, name: $('#meal-name').value };
    confirmDeleteSavedMeal(t, $('.sheet-foot', mealDlg), ev.currentTarget, () => { mealDlg.close(); $('#btn-new-meal').focus(); });
  });

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  async function init() {
    applyTheme(storedTheme());
    dateInput.value = state.date;
    if (MOCK) {
      document.title = 'Kidney Diet Log';
      const pill = $('#brand-pill');
      pill.textContent = PREVIEW ? 'Preview' : 'Demo';
      pill.hidden = false;
      const banner = $('#preview-banner');
      banner.hidden = false; // dismissing it lasts until the page reloads (nothing is stored)
      $('#preview-banner-close').addEventListener('click', () => {
        banner.hidden = true;
        const tab = $('.tab[aria-selected="true"]');
        if (tab) tab.focus();
      });
    }
    try { await loadProfile(); } catch (e) { toastError(e); }
    const initial = location.hash.replace('#', '');
    showView(VIEWS.includes(initial) ? initial : 'today');
  }
  init();
})();
