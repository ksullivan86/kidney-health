/* Kidney Diet Log — single-page UI. Vanilla ES2020, no dependencies.
   Talks only to same-origin /api/... (see ARCHITECTURE.md). Append ?mock=1 to the URL
   to run against the in-page mock API (no backend needed). */
(() => {
  'use strict';

  // ---------------------------------------------------------------------------
  // Registry (mirrors app/nutrients.py; keys are the contract)
  // ---------------------------------------------------------------------------
  const NUTRIENTS = [
    { key: 'calories_kcal', label: 'Calories', short: 'kcal', unit: 'kcal' },
    { key: 'protein_g', label: 'Protein', short: 'Protein', unit: 'g' },
    { key: 'fat_g', label: 'Fat', short: 'Fat', unit: 'g' },
    { key: 'sat_fat_g', label: 'Saturated fat', short: 'Sat fat', unit: 'g' },
    { key: 'carbs_g', label: 'Carbohydrate', short: 'Carbs', unit: 'g' },
    { key: 'fiber_g', label: 'Fiber', short: 'Fiber', unit: 'g' },
    { key: 'sugar_g', label: 'Sugars', short: 'Sugars', unit: 'g' },
    { key: 'sodium_mg', label: 'Sodium', short: 'Na', unit: 'mg' },
    { key: 'potassium_mg', label: 'Potassium', short: 'K', unit: 'mg' },
    { key: 'phosphorus_mg', label: 'Phosphorus', short: 'P', unit: 'mg' },
    { key: 'calcium_mg', label: 'Calcium', short: 'Ca', unit: 'mg' },
    { key: 'fluid_ml', label: 'Fluid', short: 'Fluid', unit: 'mL' },
  ];
  const NUT = Object.fromEntries(NUTRIENTS.map((n) => [n.key, n]));
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
  const ROLE = { calories_kcal: 'goal', protein_g: 'range', carbs_g: 'track', sodium_mg: 'limit', potassium_mg: 'limit',
    phosphorus_mg: 'limit', calcium_mg: 'info', fluid_ml: 'limit' };
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

  // Per-serving thresholds from the contract (used for live previews; the server is authoritative).
  const THRESHOLDS = [
    { key: 'potassium_mg', name: 'potassium', medium: 101, high: 200 },
    { key: 'phosphorus_mg', name: 'phosphorus', medium: 101, high: 150 },
    { key: 'sodium_mg', name: 'sodium', medium: 141, high: 400 },
    { key: 'carbs_g', name: 'carbohydrate', medium: 15, high: 30 },
    { key: 'protein_g', name: 'protein', medium: 15, high: 25 },
  ];

  const MOCK = /[?&]mock=1(?:&|$)/.test(location.search);
  const MOCK_HD = MOCK && /[?&]hd=1(?:&|$)/.test(location.search); // mock profile on hemodialysis (Mon/Wed/Fri)
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
  // Warnings evaluator (client copy of the contract table, for live previews)
  // ---------------------------------------------------------------------------
  function carbChoices(g) { return Math.max(1, Math.round(g / 15)); }
  function evaluateWarnings(nutrients, flags = [], kidneyNotes = '', perServing = true) {
    const out = [];
    const suffix = perServing ? ' per serving' : ' in this entry';
    const fl = new Set(flags || []);
    const hypo = fl.has('hypo_treatment'); // fast carbohydrate is the point: no carbohydrate warning
    if (fl.has('avoid_ckd')) {
      out.push({ nutrient: 'avoid_ckd', level: 'high', value: null, flag: 'avoid_ckd', message: kidneyNotes || 'Not recommended for people with kidney disease' });
    }
    for (const t of THRESHOLDS) {
      if (t.key === 'carbs_g' && hypo) continue;
      const raw = nutrients[t.key];
      const v = raw == null || Number.isNaN(Number(raw)) ? null : roundVal(Number(raw), t.key);
      let level = v == null ? null : v > t.high ? 'high' : v >= t.medium ? 'medium' : null;
      let flag = null;
      if (t.key === 'phosphorus_mg' && fl.has('phosphate_additive')) { level = 'high'; flag = 'phosphate_additive'; }
      else if (t.key === 'carbs_g' && fl.has('high_gi') && v > 0) { level = v >= 15 ? 'high' : 'medium'; flag = 'high_gi'; } // GI upgrades only from one carb choice (ARCHITECTURE.md)
      if (!level) continue;
      const amount = v == null ? null : fmtWithUnit(v, t.key);
      let message;
      if (flag === 'phosphate_additive') message = amount ? `Contains phosphate additives (almost fully absorbed): ${amount} phosphorus${suffix}` : 'Contains phosphate additives (almost fully absorbed)';
      else if (flag === 'high_gi') message = `High glycaemic index: ${amount} fast-acting carbohydrate${suffix}`;
      else if (t.key === 'carbs_g') {
        const choices = `${carbChoices(v)} carb ${carbChoices(v) === 1 ? 'choice' : 'choices'}`;
        message = level === 'high' ? `High carbohydrate: ${amount}${suffix} (${choices})` : `${choices}: ${amount} carbohydrate${suffix}`;
      } else if (t.key === 'protein_g' && level === 'high') message = `Large protein portion: ${amount}${suffix}`;
      else message = `${level === 'high' ? 'High' : 'Moderate'} ${t.name}: ${amount}${suffix}`;
      out.push({ nutrient: t.key, level, value: v, flag, message });
    }
    const order = { high: 0, medium: 1 };
    out.sort((a, b) => order[a.level] - order[b.level]);
    return out;
  }
  function ratingFromWarnings(warnings) {
    if (warnings.some((w) => w.level === 'high')) return 'red';
    if (warnings.some((w) => w.level === 'medium')) return 'yellow';
    return 'green';
  }

  // ---------------------------------------------------------------------------
  // Mock API (same contract, sample data) — enabled with ?mock=1
  // ---------------------------------------------------------------------------
  class MockApi {
    constructor() {
      const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
      this.nowIso = nowIso;
      const F = (name, category, serving_desc, serving_g, n, flags = [], kidney_notes = null, brand = null) => ({
        name, brand, category, source: 'builtin', fdc_id: 100000 + this._foods.length, serving_desc, serving_g,
        nutrients: {
          calories_kcal: n[0], protein_g: n[1], fat_g: n[2], sat_fat_g: n[3], carbs_g: n[4], fiber_g: n[5], sugar_g: n[6],
          sodium_mg: n[7], potassium_mg: n[8], phosphorus_mg: n[9], calcium_mg: n[10], fluid_ml: n[11],
        },
        flags, kidney_notes, hidden: false,
      });
      this._foods = [];
      const add = (f) => { f.id = this._foods.length + 1; f.created_at = f.updated_at = nowIso(); this._foods.push(f); };
      add(F('Banana, raw', 'Fruits', '1 medium (118 g)', 118, [105, 1.29, 0.39, 0.13, 26.95, 3.1, 14.43, 1, 422, 26, 6, 0], [],
        'High potassium; a renal dietitian usually suggests apples, berries or grapes instead.'));
      add(F('Apple, raw, with skin', 'Fruits', '1 medium (182 g)', 182, [95, 0.47, 0.31, 0.05, 25.13, 4.4, 18.91, 2, 195, 20, 11, 0], ['low_potassium_fruit']));
      add(F('Blueberries, raw', 'Fruits', '1 cup (148 g)', 148, [84, 1.1, 0.49, 0.04, 21.45, 3.6, 14.74, 1, 114, 18, 9, 0], ['low_potassium_fruit']));
      add(F('Star fruit (carambola), raw', 'Fruits', '1 medium (91 g)', 91, [28, 0.95, 0.3, 0.02, 6.1, 2.5, 3.62, 2, 121, 11, 3, 0], ['avoid_ckd'],
        'Star fruit contains caramboxin, a neurotoxin that failing kidneys cannot clear. Avoid completely.'));
      add(F('Bread, white, commercially prepared', 'Grains & Breads', '1 slice (25 g)', 25, [67, 1.91, 0.82, 0.2, 12.65, 0.6, 1.4, 170, 25, 25, 38, 0], ['high_gi']));
      add(F('Rice, white, long-grain, cooked', 'Grains & Breads', '1 cup (158 g)', 158, [205, 4.25, 0.44, 0.12, 44.51, 0.6, 0.08, 2, 55, 68, 16, 0], ['high_gi']));
      add(F('Oatmeal, cooked with water', 'Grains & Breads', '1 cup (234 g)', 234, [166, 5.94, 3.56, 0.73, 28.08, 4, 0.63, 9, 164, 180, 21, 0]));
      add(F('Egg, whole, hard-boiled', 'Meat, Poultry & Eggs', '1 large (50 g)', 50, [78, 6.29, 5.3, 1.63, 0.56, 0, 0.56, 62, 63, 86, 25, 0]));
      add(F('Chicken breast, roasted, skinless', 'Meat, Poultry & Eggs', '3 oz (85 g)', 85, [140, 26.37, 3.04, 0.86, 0, 0, 0, 63, 218, 194, 13, 0]));
      add(F('Salmon, Atlantic, farmed, cooked', 'Fish & Seafood', '3 oz (85 g)', 85, [175, 18.79, 10.5, 2.13, 0, 0, 0, 52, 326, 214, 13, 0]));
      add(F('Milk, reduced fat (2%)', 'Dairy & Alternatives', '1 cup (244 g)', 244, [122, 8.05, 4.83, 3.07, 11.71, 0, 12.35, 115, 342, 224, 293, 244], ['counts_as_fluid']));
      add(F('Cheese, cheddar', 'Dairy & Alternatives', '1 oz (28 g)', 28, [114, 7.06, 9.4, 5.98, 0.36, 0, 0.15, 176, 28, 145, 204, 0]));
      add(F('Cheese, pasteurized process, American', 'Dairy & Alternatives', '1 slice (21 g)', 21, [70, 3.6, 5.6, 3.4, 1.6, 0, 1.2, 290, 38, 140, 120, 0], ['phosphate_additive', 'processed'],
        'Processed cheese usually contains phosphate emulsifiers; natural cheese in a small portion is a better choice.'));
      add(F('Potato, baked, flesh and skin', 'Vegetables', '1 medium (173 g)', 173, [161, 4.33, 0.22, 0.06, 36.59, 3.8, 2.03, 17, 926, 121, 26, 0], [],
        'Very high potassium. Peeling, dicing and boiling in plenty of water (leaching) removes a large share.'));
      add(F('Green beans, cooked, boiled', 'Vegetables', '1 cup (125 g)', 125, [44, 2.36, 0.35, 0.08, 9.86, 4, 4.54, 1, 183, 36, 55, 0]));
      add(F('Carrots, raw', 'Vegetables', '1 medium (61 g)', 61, [25, 0.57, 0.15, 0.02, 5.84, 1.7, 2.89, 42, 195, 21, 20, 0]));
      add(F('Peanut butter, smooth', 'Legumes, Nuts & Seeds', '2 tbsp (32 g)', 32, [188, 7.1, 16.1, 3.3, 7.7, 1.9, 2.6, 136, 208, 107, 14, 0]));
      add(F('Cola, regular', 'Beverages', '12 fl oz (368 g)', 368, [140, 0, 0, 0, 39, 0, 39, 15, 7, 41, 7, 330], ['phosphate_additive', 'high_gi', 'counts_as_fluid'],
        'Dark colas get their color from phosphoric acid, an additive phosphorus source. Clear sodas or water are better.'));
      add(F('Coffee, brewed', 'Beverages', '1 cup (237 g)', 237, [2, 0.28, 0.05, 0, 0, 0, 0, 5, 116, 7, 5, 237], ['counts_as_fluid']));
      add(F('Water, tap', 'Beverages', '1 cup (237 g)', 237, [0, 0, 0, 0, 0, 0, 0, 5, 0, 0, 7, 237], ['counts_as_fluid']));
      add(F('Glucose tablets', 'Diabetes supplies', '4 tablets (16 g)', 16, [60, 0, 0, 0, 16, 0, 16, 0, 0, 0, 0, 0], ['hypo_treatment', 'high_gi'],
        'Hypo treatment of choice: 15 g fast carbohydrate with no potassium or phosphorus.'));
      add(F('Hamburger, single patty, plain', 'Prepared & Fast Food', '1 sandwich (110 g)', 110, [254, 12.3, 9.8, 3.7, 30.3, 1.1, 6, 497, 194, 102, 110, 0], ['processed']));
      add(F('Rice cakes, plain', 'Sweets & Snacks', '2 cakes (18 g)', 18, [70, 1.5, 0.5, 0.1, 14.7, 0.8, 0.2, 58, 52, 65, 2, 0], ['high_gi']));
      add(F('Mayonnaise', 'Condiments & Sauces', '1 tbsp (14 g)', 14, [94, 0.13, 10.3, 1.6, 0.1, 0, 0.1, 88, 3, 4, 1, 0]));
      this._categories = ['Fruits', 'Vegetables', 'Grains & Breads', 'Dairy & Alternatives', 'Meat, Poultry & Eggs', 'Fish & Seafood',
        'Legumes, Nuts & Seeds', 'Beverages', 'Sweets & Snacks', 'Condiments & Sauces', 'Prepared & Fast Food', 'Diabetes supplies'];

      this._profile = {
        id: 1, name: 'Sam', weight_kg: 70, height_cm: 172, ckd_stage: MOCK_HD ? '5' : '3b', dialysis: MOCK_HD ? 'hemodialysis' : 'none', diabetes: 'type1', warn_fraction: 0.8,
        dialysis_days: MOCK_HD ? [0, 2, 4] : [],
        week_start: 'monday',
        targets: { calories_kcal: 2100, protein_g: MOCK_HD ? { min: 70, max: 84 } : { min: 42, max: 56 }, carbs_g: 236, carbs_per_meal_g: 60, sodium_mg: 2000,
          potassium_mg: 2500, phosphorus_mg: 900, calcium_mg: 1000, fluid_ml: MOCK_HD ? 1500 : null },
        updated_at: nowIso(),
      };

      // Sample log: today is hand-picked; earlier days are generated deterministically.
      this._entries = [];
      this._nextEntryId = 1;
      const byName = (n) => this._foods.find((f) => f.name.startsWith(n));
      const today = todayStr();
      const put = (date, meal, name, servings, note, status) => this._createEntry(byName(name), { date, meal, servings, note, status });
      put(today, 'breakfast', 'Oatmeal', 1);
      put(today, 'breakfast', 'Milk', 0.5);
      put(today, 'breakfast', 'Blueberries', 0.5);
      put(today, 'breakfast', 'Coffee', 1);
      put(today, 'lunch', 'Chicken', 1);
      put(today, 'lunch', 'Rice', 1, 'small bowl');
      put(today, 'lunch', 'Green beans', 1);
      put(today, 'dinner', 'Salmon', 1);
      put(today, 'dinner', 'Potato', 1, null, 'planned');
      put(today, 'dinner', 'Carrots', 1, null, 'planned');
      put(today, 'snack', 'Apple', 1);
      put(today, 'snack', 'Rice cakes', 1, 'evening', 'planned');
      // Planned days ahead
      const t1 = addDays(today, 1), t2 = addDays(today, 2), t3 = addDays(today, 3);
      for (const [m, n, sv] of [['breakfast', 'Egg', 1], ['breakfast', 'Bread', 2], ['breakfast', 'Coffee', 1],
        ['lunch', 'Chicken', 1], ['lunch', 'Rice', 1], ['lunch', 'Carrots', 1], ['dinner', 'Salmon', 1], ['dinner', 'Green beans', 1], ['snack', 'Blueberries', 0.5]]) {
        put(t1, m, n, sv, null, 'planned');
      }
      for (const [m, n, sv] of [['breakfast', 'Oatmeal', 1], ['breakfast', 'Blueberries', 0.5], ['lunch', 'Hamburger', 1], ['lunch', 'Cola', 1], ['dinner', 'Chicken', 1], ['dinner', 'Potato', 1]]) {
        put(t2, m, n, sv, null, 'planned');
      }
      for (const [m, n, sv] of [['breakfast', 'Egg', 2], ['breakfast', 'Apple', 1], ['dinner', 'Salmon', 1], ['dinner', 'Rice', 1]]) {
        put(t3, m, n, sv, null, 'planned');
      }
      // Saved meals (templates)
      this._templates = [];
      this._nextTemplateId = 1;
      const tpl = (name, note, items) => {
        const t = { id: this._nextTemplateId++, name, note, items: items.map(([n, sv]) => ({ food_id: byName(n).id, servings: sv })), created_at: nowIso(), updated_at: nowIso() };
        this._templates.push(t);
      };
      tpl('Usual breakfast', 'Weekday default', [['Oatmeal', 1], ['Blueberries', 0.5], ['Coffee', 1]]);
      tpl('Chicken & rice lunch', null, [['Chicken', 1], ['Rice', 1], ['Green beans', 1]]);
      tpl('Hypo kit', '15 g fast carbs, no potassium', [['Glucose', 1]]);
      let seed = 7;
      const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
      const plan = {
        breakfast: ['Egg', 'Bread', 'Blueberries', 'Coffee', 'Oatmeal', 'Milk'],
        lunch: ['Chicken', 'Rice', 'Green beans', 'Carrots', 'Bread', 'Apple'],
        dinner: ['Salmon', 'Rice', 'Green beans', 'Potato', 'Chicken', 'Carrots'],
        snack: ['Apple', 'Rice cakes', 'Peanut', 'Cheese, cheddar', 'Glucose', 'Water'],
      };
      for (let i = 1; i <= 30; i++) {
        const date = addDays(today, -i);
        if (rnd() < 0.08) continue; // an empty day now and then
        for (const meal of Object.keys(plan)) {
          const picks = plan[meal].filter(() => rnd() < (meal === 'snack' ? 0.3 : 0.45));
          for (const p of picks) put(date, meal, p, Math.round((0.5 + rnd() * 0.75) * 4) / 4);
        }
        if (rnd() < 0.2) put(date, 'dinner', 'Hamburger', 1);
        if (rnd() < 0.15) put(date, 'snack', 'Cola', 1);
      }
    }

    _foodView(f) {
      const warnings = evaluateWarnings(f.nutrients, f.flags, f.kidney_notes, true);
      return { ...structuredClone(f), warnings, kidney_rating: ratingFromWarnings(warnings) };
    }
    _createEntry(food, { date, meal, servings = 1, grams = null, note = null, status = 'eaten' }) {
      let sv = Number(servings) || 1;
      if (grams != null && grams !== '' && food.serving_g) sv = Number(grams) / food.serving_g;
      const e = { id: this._nextEntryId++, date, meal, food_id: food.id, food_name: food.name, servings: Math.round(sv * 1000) / 1000,
        grams: grams != null && grams !== '' ? Number(grams) : null, note: note || null, status: status === 'planned' ? 'planned' : 'eaten',
        created_at: this.nowIso(), updated_at: this.nowIso() };
      this._snapshot(e, food);
      this._entries.push(e);
      return e;
    }
    _snapshot(e, food) {
      e.nutrients = {};
      for (const n of NUTRIENTS) {
        const v = food.nutrients[n.key];
        e.nutrients[n.key] = v == null ? null : roundVal(v * e.servings, n.key);
      }
      e.warnings = evaluateWarnings(e.nutrients, food.flags, food.kidney_notes, false);
      e.kidney_rating = ratingFromWarnings(e.warnings);
    }
    _sum(entries) {
      const t = Object.fromEntries(NUTRIENTS.map((n) => [n.key, 0]));
      for (const e of entries) for (const n of NUTRIENTS) t[n.key] += e.nutrients[n.key] || 0;
      for (const n of NUTRIENTS) t[n.key] = roundVal(t[n.key], n.key);
      return t;
    }
    _targetOf(key) {
      const tg = this._profile.targets[key];
      if (tg == null || !NUT[key]) return { target: null, min: undefined };
      const target = typeof tg === 'object' ? tg.max : tg;
      const min = typeof tg === 'object' ? tg.min : undefined;
      return { target: target == null ? null : target, min };
    }
    _status(totals, projected = false) {
      const st = {};
      const alerts = [];
      const wf = this._profile.warn_fraction;
      for (const key of Object.keys(this._profile.targets)) {
        const { target, min } = this._targetOf(key);
        if (target == null) continue;
        const value = totals[key] || 0;
        const fraction = Math.round((value / target) * 1000) / 1000;
        const level = fraction > 1 ? 'over' : fraction >= wf ? 'caution' : 'ok';
        st[key] = { value, target, fraction, level };
        if (min != null) st[key].min = min;
        if (level !== 'ok') {
          const limitWord = key === 'calories_kcal' ? 'goal' : key === 'protein_g' ? 'maximum' : 'limit';
          const nums = `(${fmtNum(value, key)} / ${fmtNum(target, key)} ${NUT[key].unit})`;
          alerts.push({ level, nutrient: key, message: projected
            ? `If you eat what's planned, ${NUT[key].label.toLowerCase()} reaches ${pct(fraction)} % of today's ${limitWord} ${nums}`
            : `${NUT[key].label} is at ${pct(fraction)} % of today's ${limitWord} ${nums}` });
        }
      }
      return { status: st, alerts };
    }
    _dayEntries(date) {
      const order = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 };
      const sOrder = { eaten: 0, planned: 1 };
      return this._entries.filter((e) => e.date === date)
        .sort((a, b) => order[a.meal] - order[b.meal] || sOrder[a.status] - sOrder[b.status] || a.created_at.localeCompare(b.created_at) || a.id - b.id);
    }
    _day(date) {
      const entries = this._dayEntries(date);
      const eaten = entries.filter((e) => e.status === 'eaten');
      const planned = entries.filter((e) => e.status === 'planned');
      const totals = this._sum(eaten);
      const planned_totals = this._sum(planned);
      const projected_totals = this._sum(entries);
      const meals = Object.fromEntries(MEALS.map((m) => [m.key, this._sum(eaten.filter((e) => e.meal === m.key))]));
      const planned_meals = Object.fromEntries(MEALS.map((m) => [m.key, this._sum(planned.filter((e) => e.meal === m.key))]));
      const { status, alerts } = this._status(totals);
      const proj = this._status(projected_totals, true);
      return { date, entries: structuredClone(entries), totals, planned_totals, projected_totals, targets: structuredClone(this._profile.targets),
        status, projected_status: proj.status, meals, planned_meals, alerts, projected_alerts: planned.length ? proj.alerts : [],
        counts: { eaten: eaten.length, planned: planned.length } };
    }
    _rangeItem(date) {
      const d = this._day(date);
      return { date, totals: d.totals, planned_totals: d.planned_totals, projected_totals: d.projected_totals, status: d.status, projected_status: d.projected_status, counts: d.counts };
    }
    // Eaten totals per day for days with at least one eaten entry (a present key is a logged day).
    _loggedTotals(start, end) {
      const out = {};
      for (let d = start; d <= end; d = addDays(d, 1)) {
        const eaten = this._entries.filter((e) => e.date === d && e.status === 'eaten');
        if (eaten.length) out[d] = this._sum(eaten);
      }
      return out;
    }
    _level(fraction) {
      if (fraction == null) return null;
      return fraction > 1 ? 'over' : fraction >= this._profile.warn_fraction ? 'caution' : 'ok';
    }
    _summary(start, end) {
      const days = daysBetween(start, end) + 1;
      if (days < 1) { const e = new Error('end must not be before start'); e.status = 400; e.detail = e.message; throw e; }
      if (days > 366) { const e = new Error('A summary covers at most 366 days'); e.status = 400; e.detail = e.message; throw e; }
      const prevEnd = addDays(start, -1), prevStart = addDays(start, -days);
      const totals = this._loggedTotals(prevStart, end);
      const cur = Object.keys(totals).filter((d) => d >= start && d <= end).sort();
      const prev = Object.keys(totals).filter((d) => d >= prevStart && d <= prevEnd);
      const avg = (vals) => (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null);
      const nutrients = {};
      for (const n of NUTRIENTS) {
        const { target } = this._targetOf(n.key);
        if (target == null) continue;
        const vals = cur.map((d) => [d, totals[d][n.key] || 0]);
        const total = vals.reduce((a, [, v]) => a + v, 0);
        const average = avg(vals.map(([, v]) => v));
        const fraction = average == null ? null : Math.round((average / target) * 100) / 100;
        const previous_average = avg(prev.map((d) => totals[d][n.key] || 0));
        const change_pct = average != null && previous_average ? Math.round(((average - previous_average) / previous_average) * 1000) / 10 : null;
        const maxDay = vals.length ? vals.reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
        nutrients[n.key] = { role: ROLE[n.key] || 'info', target: roundVal(target, n.key), total: roundVal(total, n.key),
          average: average == null ? null : roundVal(average, n.key), fraction, level: this._level(fraction),
          days_over: vals.filter(([, v]) => v > target).length, max_day: maxDay ? { date: maxDay[0], value: roundVal(maxDay[1], n.key) } : null,
          previous_average: previous_average == null ? null : roundVal(previous_average, n.key), change_pct, assessment: ASSESSMENT[n.key] || 'weekly_average' };
      }
      let interdialytic = null;
      const notes = [
        'Potassium, sodium and fluid are judged day by day: a day well over the limit is a risk on its own, and a low day does not make up for a high one.',
        'Phosphorus and protein are judged on the weekly average: blood phosphate and nutritional status reflect weeks of intake, so one high day matters less than a high average.',
        'Carbohydrate is counted per meal and per day for insulin; the weekly average is informational.',
      ];
      const dd = this._profile.dialysis_days || [];
      if (this._profile.dialysis === 'hemodialysis' && dd.length) {
        let since = end;
        for (let back = 0; back < 14; back++) { const c = addDays(end, -back); if (dd.includes(weekdayMon(c))) { since = c; break; } }
        let next = addDays(end, 1);
        for (let ahead = 1; ahead <= 7; ahead++) { const c = addDays(end, ahead); if (dd.includes(weekdayMon(c))) { next = c; break; } }
        const span = daysBetween(since, end) + 1;
        const nut = {};
        for (const key of INTERDIALYTIC_KEYS) {
          const { target } = this._targetOf(key);
          if (target == null) continue;
          let total = 0;
          for (let d = since; d <= end; d = addDays(d, 1)) total += totals[d] ? totals[d][key] || 0 : 0;
          const limit = target * span;
          const fraction = Math.round((total / limit) * 100) / 100;
          nut[key] = { total: roundVal(total, key), limit: roundVal(limit, key), fraction, level: this._level(fraction) };
        }
        interdialytic = { since, days: span, next, nutrients: nut };
        notes.push('Between hemodialysis sessions potassium, sodium and fluid accumulate until the next session, so they are also totalled since the last dialysis day (the long weekend gap is the one to watch).');
      } else if (this._profile.dialysis === 'hemodialysis') {
        notes.push('Set your dialysis days in Profile to see totals since the last session.');
      }
      return { start, end, days, logged_days: cur.length, nutrients, interdialytic, notes };
    }
    _templateView(t) {
      const items = t.items.map((it) => {
        const f = this._foods.find((x) => x.id === it.food_id) || { name: 'Deleted food', serving_desc: '', nutrients: {}, flags: [], kidney_notes: '', hidden: true };
        const nutrients = Object.fromEntries(NUTRIENTS.map((n) => [n.key, f.nutrients[n.key] == null ? null : roundVal(f.nutrients[n.key] * it.servings, n.key)]));
        const warnings = evaluateWarnings(nutrients, f.flags, f.kidney_notes, false);
        return { food_id: it.food_id, food_name: f.name, servings: it.servings, serving_desc: f.serving_desc, nutrients, kidney_rating: ratingFromWarnings(warnings), hidden: !!f.hidden };
      });
      const totals = Object.fromEntries(NUTRIENTS.map((n) => [n.key, 0]));
      for (const it of items) for (const n of NUTRIENTS) totals[n.key] += it.nutrients[n.key] || 0;
      for (const n of NUTRIENTS) totals[n.key] = roundVal(totals[n.key], n.key);
      const rank = { green: 0, yellow: 1, red: 2 };
      const kidney_rating = items.reduce((w, it) => (rank[it.kidney_rating] > rank[w] ? it.kidney_rating : w), 'green');
      return { id: t.id, name: t.name, note: t.note || null, items, totals, kidney_rating, created_at: t.created_at, updated_at: t.updated_at };
    }
    _templateItems(body, fail) {
      const items = Array.isArray(body.items) ? body.items : [];
      if (!items.length) fail(400, 'A saved meal needs at least one food');
      return items.map((it) => {
        const f = this._foods.find((x) => x.id === Number(it.food_id));
        if (!f) fail(404, `Food ${it.food_id} not found`);
        const sv = Number(it.servings);
        if (!(sv > 0)) fail(400, 'servings must be more than 0');
        return { food_id: f.id, servings: Math.round(sv * 1000) / 1000 };
      });
    }
    _shopping(start, end) {
      const byFood = new Map();
      for (const e of this._entries) {
        if (e.status !== 'planned' || e.date < start || e.date > end) continue;
        const f = this._foods.find((x) => x.id === e.food_id);
        const it = byFood.get(e.food_id) || { food_id: e.food_id, food_name: e.food_name, serving_desc: f ? f.serving_desc : '', servings: 0, grams: 0, _days: new Set(), _g: f ? f.serving_g : 0 };
        it.servings += e.servings;
        it._days.add(e.date);
        byFood.set(e.food_id, it);
      }
      return [...byFood.values()].map((it) => ({ food_id: it.food_id, food_name: it.food_name, serving_desc: it.serving_desc,
        servings: Math.round(it.servings * 100) / 100, grams: Math.round(it.servings * it._g * 10) / 10, days: it._days.size }))
        .sort((a, b) => a.food_name.localeCompare(b.food_name));
    }
    _suggest() {
      const p = this._profile;
      if (!p.weight_kg) { const err = new Error('Weight is required to suggest targets'); err.status = 400; err.detail = err.message; throw err; }
      const w = p.weight_kg;
      const dial = p.dialysis !== 'none';
      const stage = p.ckd_stage;
      const cal = Math.round(30 * w);
      const carbs = Math.round((cal * 0.45) / 4);
      const early = stage === '1' || stage === '2';
      const protein = dial ? { min: Math.round(1.0 * w), max: Math.round(1.2 * w) } : early ? { min: Math.round(0.8 * w), max: Math.round(1.0 * w) } : { min: Math.round(0.6 * w), max: Math.round(0.8 * w) };
      const K_BY_STAGE = { 1: 4000, 2: 4000, '3a': 4000, '3b': 3500, 4: 3000, 5: 2500 };
      const potassium = p.dialysis === 'hemodialysis' ? 2500 : p.dialysis === 'peritoneal' ? 3500 : K_BY_STAGE[stage];
      const phosphorus = !dial && stage === '5' ? 900 : 1000;
      const fluid = p.dialysis === 'hemodialysis' ? 1500 : p.dialysis === 'peritoneal' ? 2000 : null;
      const targets = { calories_kcal: cal, protein_g: protein, carbs_g: carbs, carbs_per_meal_g: Math.round(carbs / 4 / 5) * 5,
        sodium_mg: 2000, potassium_mg: potassium, phosphorus_mg: phosphorus, calcium_mg: 1000, fluid_ml: fluid };
      const notes = [
        dial ? `Protein 1.0–1.2 g/kg for dialysis (${protein.min}–${protein.max} g at ${w} kg).`
             : early ? `Protein 0.8–1.0 g/kg for CKD stage ${stage} (${protein.min}–${protein.max} g at ${w} kg).`
             : `Protein 0.6–0.8 g/kg for non-dialysis CKD with diabetes (${protein.min}–${protein.max} g at ${w} kg).`,
        `Calories 30 kcal/kg (${cal} kcal); carbohydrate 45 % of calories (${carbs} g/day).`,
        `Potassium ${potassium} mg/day is the starting point for ${dial ? p.dialysis : 'stage ' + stage}. Only restrict potassium if your blood potassium is high; your care team sets the number.`,
        `Phosphorus ${phosphorus} mg/day; additive phosphorus counts fully.`,
        'Sodium 2000 mg/day (KDOQI: under 2300 mg).',
        fluid ? `Fluid ${fluid} mL/day as a default for ${p.dialysis}; your unit sets the real number from urine output.` : 'No fluid limit suggested without dialysis.',
        'These are starting points. Discuss them with your nephrologist or renal dietitian.',
      ];
      return { targets, notes };
    }
    _csv(start, end) {
      const cols = ['id', 'date', 'meal', 'food_name', 'servings', 'grams', 'note', 'status', ...NUTRIENTS.map((n) => n.key)];
      const esc = (v) => { const str = v == null ? '' : String(v); return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str; };
      const rows = this._entries.filter((e) => e.date >= start && e.date <= end)
        .sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id)
        .map((e) => cols.map((c) => esc(c in e ? e[c] : e.nutrients[c])).join(','));
      return [cols.join(','), ...rows].join('\n') + '\n';
    }

    async request(method, path, body) {
      await new Promise((r) => setTimeout(r, 60));
      const url = new URL(path, 'http://mock.local');
      const p = url.pathname;
      const q = url.searchParams;
      const fail = (status, detail) => { const e = new Error(detail); e.status = status; e.detail = detail; throw e; };
      let m;

      if (p === '/api/profile' && method === 'GET') return structuredClone(this._profile);
      if (p === '/api/profile' && method === 'PUT') {
        const allowed = ['name', 'weight_kg', 'height_cm', 'ckd_stage', 'dialysis', 'diabetes', 'warn_fraction', 'targets', 'dialysis_days', 'week_start'];
        for (const k of allowed) if (k in body) this._profile[k] = structuredClone(body[k]);
        if (this._profile.dialysis !== 'hemodialysis') this._profile.dialysis_days = [];
        this._profile.dialysis_days = [...new Set((this._profile.dialysis_days || []).map(Number).filter((d) => d >= 0 && d <= 6))].sort();
        this._profile.updated_at = this.nowIso();
        return structuredClone(this._profile);
      }
      if (p === '/api/profile/suggested-targets') return this._suggest();

      if (p === '/api/foods/categories') return { categories: [...this._categories] };
      if (p === '/api/foods/usda/search') fail(503, 'USDA_API_KEY not configured');
      if (p === '/api/foods/usda/import') fail(503, 'USDA_API_KEY not configured');
      if (p === '/api/foods' && method === 'GET') {
        const text = (q.get('q') || '').trim().toLowerCase();
        const cat = q.get('category');
        const src = q.get('source');
        const limit = Number(q.get('limit') || 25);
        let list = this._foods.filter((f) => !f.hidden && (!cat || f.category === cat) && (!src || f.source === src));
        if (text) {
          const words = text.split(/\s+/);
          list = list.filter((f) => words.every((w) => (f.name + ' ' + (f.brand || '')).toLowerCase().includes(w)));
          list.sort((a, b) => {
            const ap = a.name.toLowerCase().startsWith(text) ? 0 : 1;
            const bp = b.name.toLowerCase().startsWith(text) ? 0 : 1;
            return ap - bp || a.name.localeCompare(b.name);
          });
        } else {
          const last = {};
          for (const e of this._entries) {
            const stamp = e.date + e.created_at;
            if (!last[e.food_id] || stamp > last[e.food_id]) last[e.food_id] = stamp;
          }
          list.sort((a, b) => {
            const la = last[a.id] || '', lb = last[b.id] || '';
            return lb > la ? 1 : lb < la ? -1 : a.name.localeCompare(b.name);
          });
        }
        return { foods: list.slice(0, limit).map((f) => this._foodView(f)) };
      }
      if (p === '/api/foods' && method === 'POST') {
        const f = { id: this._foods.length + 1, name: body.name, brand: body.brand || null, category: body.category || null, source: 'custom', fdc_id: null,
          serving_desc: body.serving_desc || '1 serving', serving_g: Number(body.serving_g) || 100,
          nutrients: Object.fromEntries(NUTRIENTS.map((n) => [n.key, body.nutrients && body.nutrients[n.key] != null ? Number(body.nutrients[n.key]) : null])),
          flags: body.flags || [], kidney_notes: body.kidney_notes || null, hidden: false, created_at: this.nowIso(), updated_at: this.nowIso() };
        this._foods.push(f);
        return this._foodView(f);
      }
      if ((m = p.match(/^\/api\/foods\/(\d+)$/))) {
        const f = this._foods.find((x) => x.id === Number(m[1]));
        if (!f) fail(404, 'Food not found');
        if (method === 'GET') return this._foodView(f);
        if (method === 'DELETE') {
          if (f.source === 'builtin') fail(409, 'Built-in foods cannot be deleted');
          if (this._entries.some((e) => e.food_id === f.id)) f.hidden = true; else this._foods.splice(this._foods.indexOf(f), 1);
          return null;
        }
      }

      if (p === '/api/log' && method === 'GET') return this._day(q.get('date') || todayStr());
      if (p === '/api/log' && method === 'POST') {
        const food = this._foods.find((x) => x.id === Number(body.food_id));
        if (!food) fail(404, 'Food not found');
        return structuredClone(this._createEntry(food, body));
      }
      if (p === '/api/log/quick' && method === 'POST') {
        const food = await this.request('POST', '/api/foods', { name: body.name, serving_desc: body.serving_desc, serving_g: body.serving_g,
          nutrients: body.nutrients, flags: body.flags, category: body.category });
        const f = this._foods.find((x) => x.id === food.id);
        return structuredClone(this._createEntry(f, { date: body.date, meal: body.meal, servings: body.servings, status: body.status }));
      }
      if (p === '/api/log/mark-eaten' && method === 'POST') {
        let n = 0;
        for (const e of this._entries) {
          if (e.date === body.date && e.status === 'planned' && (!body.meal || e.meal === body.meal)) { e.status = 'eaten'; e.updated_at = this.nowIso(); n++; }
        }
        return { updated: n };
      }
      if (p === '/api/log/copy-day' && method === 'POST') {
        if (!body.from_date || !body.to_date) fail(400, 'from_date and to_date are required');
        if (body.from_date === body.to_date) fail(400, 'from_date and to_date must differ');
        const meals = Array.isArray(body.meals) && body.meals.length ? body.meals : MEALS.map((x) => x.key);
        const include = body.include || 'all';
        const status = body.status === 'eaten' ? 'eaten' : 'planned';
        const created = [];
        for (const e of this._dayEntries(body.from_date)) {
          if (!meals.includes(e.meal)) continue;
          if (include !== 'all' && e.status !== include) continue;
          const food = this._foods.find((x) => x.id === e.food_id);
          if (!food) continue;
          created.push(structuredClone(this._createEntry(food, { date: body.to_date, meal: e.meal, servings: e.servings, grams: e.grams, note: e.note, status })));
        }
        return { created: created.length, entries: created };
      }
      if (p === '/api/log/range') {
        const start = q.get('start'), end = q.get('end');
        const days = [];
        for (let d = start; d <= end; d = addDays(d, 1)) {
          days.push(this._rangeItem(d));
          if (days.length > 400) break;
        }
        return { days };
      }
      if (p === '/api/log/summary') {
        const end = q.get('end') || todayStr();
        const start = q.get('start') || addDays(end, -6);
        return this._summary(start, end);
      }
      if (p === '/api/log/export.csv') return this._csv(q.get('start'), q.get('end'));
      if ((m = p.match(/^\/api\/log\/(\d+)$/))) {
        const e = this._entries.find((x) => x.id === Number(m[1]));
        if (!e) fail(404, 'Entry not found');
        if (method === 'DELETE') { this._entries.splice(this._entries.indexOf(e), 1); return null; }
        if (method === 'PUT') {
          const food = this._foods.find((x) => x.id === e.food_id);
          for (const k of ['meal', 'note', 'date']) if (k in body) e[k] = body[k];
          if ('status' in body) e.status = body.status === 'planned' ? 'planned' : 'eaten';
          if ('grams' in body && body.grams != null && body.grams !== '') { e.grams = Number(body.grams); e.servings = Math.round((e.grams / food.serving_g) * 1000) / 1000; }
          else if ('servings' in body && body.servings != null) { e.servings = Number(body.servings); if ('grams' in body) e.grams = body.grams == null ? null : Number(body.grams); }
          e.updated_at = this.nowIso();
          this._snapshot(e, food);
          return structuredClone(e);
        }
      }

      // Saved meals
      if (p === '/api/meals' && method === 'GET') {
        return { meals: [...this._templates].sort((a, b) => a.name.localeCompare(b.name)).map((t) => this._templateView(t)) };
      }
      if (p === '/api/meals' && method === 'POST') {
        if (!body.name || !String(body.name).trim()) fail(400, 'name is required');
        const items = this._templateItems(body, fail);
        const t = { id: this._nextTemplateId++, name: String(body.name).trim(), note: body.note || null, items, created_at: this.nowIso(), updated_at: this.nowIso() };
        this._templates.push(t);
        return this._templateView(t);
      }
      if (p === '/api/meals/from-log' && method === 'POST') {
        if (!body.name || !String(body.name).trim()) fail(400, 'name is required');
        const entries = this._dayEntries(body.date).filter((e) => e.meal === body.meal);
        if (!entries.length) fail(400, `No entries for ${body.meal} on ${body.date}`);
        const t = { id: this._nextTemplateId++, name: String(body.name).trim(), note: body.note || null,
          items: entries.map((e) => ({ food_id: e.food_id, servings: e.servings })), created_at: this.nowIso(), updated_at: this.nowIso() };
        this._templates.push(t);
        return this._templateView(t);
      }
      if ((m = p.match(/^\/api\/meals\/(\d+)(\/apply)?$/))) {
        const t = this._templates.find((x) => x.id === Number(m[1]));
        if (!t) fail(404, 'Saved meal not found');
        if (m[2] && method === 'POST') {
          if (!body.date || !body.meal) fail(400, 'date and meal are required');
          const scale = body.scale == null ? 1 : Number(body.scale);
          if (!(scale > 0)) fail(400, 'scale must be more than 0');
          const status = body.status === 'eaten' ? 'eaten' : 'planned';
          const entries = [];
          for (const it of t.items) {
            const food = this._foods.find((x) => x.id === it.food_id);
            if (!food) continue;
            entries.push(structuredClone(this._createEntry(food, { date: body.date, meal: body.meal, servings: it.servings * scale, status })));
          }
          return { entries };
        }
        if (method === 'GET') return this._templateView(t);
        if (method === 'PUT') {
          if (!body.name || !String(body.name).trim()) fail(400, 'name is required');
          t.items = this._templateItems(body, fail);
          t.name = String(body.name).trim(); t.note = body.note || null; t.updated_at = this.nowIso();
          return this._templateView(t);
        }
        if (method === 'DELETE') { this._templates.splice(this._templates.indexOf(t), 1); return null; }
      }
      if (p === '/api/plan/shopping') {
        const end = q.get('end') || addDays(todayStr(), 6);
        const start = q.get('start') || todayStr();
        return { items: this._shopping(start, end) };
      }
      fail(404, `Mock: no route for ${method} ${p}`);
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // API layer
  // ---------------------------------------------------------------------------
  const mock = MOCK ? new MockApi() : null;

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
    if (res.status === 204) return null;
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
  function effectiveTheme() {
    const t = root.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function applyTheme(mode) {
    if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode); else root.removeAttribute('data-theme');
    try { if (mode === 'auto') localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, mode); } catch (e) { /* storage unavailable */ }
    const eff = effectiveTheme();
    const btn = $('#theme-toggle');
    btn.setAttribute('aria-label', eff === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    const sel = $('#pf-theme'); if (sel) sel.value = mode;
    $$('meta[name="theme-color"]').forEach((mtag) => mtag.setAttribute('content', eff === 'dark' ? '#111417' : '#f4f5f7'));
  }
  $('#theme-toggle').addEventListener('click', () => applyTheme(effectiveTheme() === 'dark' ? 'light' : 'dark'));
  $('#pf-theme').addEventListener('change', (e) => applyTheme(e.target.value));
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyTheme(storedTheme()));
  }

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
    if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}${location.search ? '' : ''}`);
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
      const eatenLevel = Object.fromEntries((day.alerts || []).map((a) => [a.nutrient, a.level]));
      const shown = (day.projected_alerts || []).filter((a) => eatenLevel[a.nutrient] !== a.level);
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
    const levelWord = (lv) => (lv === 'over' && hasMin ? 'Over max' : lv === 'over' && key === 'calories_kcal' ? 'Over goal' : lv === 'caution' && key === 'calories_kcal' ? 'Near goal' : LEVEL_TEXT[lv]);
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
    const foot = [`${p} % of ${hasMin ? 'maximum' : key === 'calories_kcal' ? 'goal' : 'limit'}`];
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
  function setupDialog(dlg) {
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
    $$('[data-close]', dlg).forEach((b) => b.addEventListener('click', () => dlg.close()));
    dlg.addEventListener('close', () => {
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

  function scaledNutrients(perServing, servings) {
    const out = {};
    for (const n of NUTRIENTS) {
      const v = perServing ? perServing[n.key] : null;
      out[n.key] = v == null ? null : roundVal(v * servings, n.key);
    }
    return out;
  }
  function previewServings() {
    // When the weight was typed last, preview with the servings the server will store
    // (grams / serving_g to 3 decimals), not the 2-decimal number shown in the servings box,
    // so the numbers read before saving are the numbers seen after saving.
    const g = Number(entryGrams.value);
    if (sheet.lastEdited === 'grams' && sheet.food && sheet.food.serving_g && Number.isFinite(g) && g > 0) {
      return Math.round((g / sheet.food.serving_g) * 1000) / 1000;
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

  entryForm.addEventListener('submit', async (e) => {
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
  $('#entry-delete').addEventListener('click', async () => {
    if (!sheet.entry || sheet.busy) return;
    if (!window.confirm(`Delete ${sheet.entry.food_name} from ${MEAL_LABEL[sheet.entry.meal].toLowerCase()}?`)) return;
    sheet.busy = true;
    try {
      await api.deleteEntry(sheet.entry.id);
      entryDlg.close();
      toast('Entry deleted', 'ok');
      loadDay();
    } catch (err) { toastError(err); }
    finally { sheet.busy = false; }
  });
  $('#entry-delete-food').addEventListener('click', async () => {
    const f = sheet.food;
    if (!f || sheet.busy) return;
    if (!window.confirm(`Delete the food "${f.name}" from your database? Logged entries keep their numbers.`)) return;
    sheet.busy = true;
    try {
      await api.deleteFood(f.id);
      entryDlg.close();
      toast('Food deleted', 'ok');
      runSearch();
    } catch (err) { toastError(err); }
    finally { sheet.busy = false; }
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
  quickForm.addEventListener('submit', async (e) => {
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
  const USDA_DISABLED_MSG = 'USDA search is not enabled on this server. Set USDA_API_KEY to enable it (free key at api.data.gov).';
  $('#btn-usda').addEventListener('click', (e) => {
    clear(usdaResults); usdaStatus.textContent = '';
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
    exportLink.setAttribute('download', `kidney-log_${start}_${end}.csv`);
    if (mock) {
      exportLink.href = '#';
      exportLink.onclick = async (e) => {
        e.preventDefault();
        const csv = await mock.request('GET', api.exportUrl(start, end));
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = h('a', { href: url, download: `kidney-log_${start}_${end}.csv` });
        document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      };
    } else { exportLink.href = api.exportUrl(start, end); exportLink.onclick = null; }
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
      hit.addEventListener('pointerenter', show); hit.addEventListener('pointerleave', hide);
      hit.addEventListener('focus', show); hit.addEventListener('blur', hide);
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
    return svg;
  }
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
  profileForm.addEventListener('submit', async (e) => {
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
    btn.disabled = true;
    try {
      state.profile = await api.saveProfile(body);
      renderProfile();
      state.dayLoadedFor = null; state.trends = null; state.summary = null; state.plan = null; state.planStart = null; state.shopping = null;
      toast('Profile saved', 'ok');
    } catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  });
  $('#btn-suggest').addEventListener('click', async () => {
    const btn = $('#btn-suggest');
    // The endpoint computes from the *saved* profile; check the form first so the person is
    // told what to do in plain words instead of seeing the server's 400 (finding: raw field name).
    const weight = numOrNull($('#pf-weight').value);
    const height = numOrNull($('#pf-height').value);
    const saved = state.profile || {};
    if (weight == null) { toast('Enter your weight (kg) first; the suggestions are per kg of body weight', 'error'); $('#pf-weight').focus(); return; }
    if (saved.weight_kg == null || Number(saved.weight_kg) !== weight || (saved.height_cm ?? null) !== height) {
      toast('Save profile first so the suggestion uses your weight and height', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    btn.disabled = true;
    try {
      const res = await api.suggested();
      fillTargets(res.targets || {});
      const notes = $('#suggest-notes');
      clear(notes);
      notes.append(h('div', { class: 'notes-title' }, 'Suggested starting points filled in below (not saved yet). Discuss with your care team, then press Save profile.'));
      if (res.notes && res.notes.length) notes.append(h('ul', {}, res.notes.map((t) => h('li', {}, t))));
      notes.hidden = false;
      toast('Targets suggested; review and save', 'ok');
    } catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  });

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
        h('button', { class: 'link-btn danger-link', type: 'button', onclick: () => deleteSavedMeal(t) }, 'Delete')));
      savedMealsEl.append(li);
    }
  }
  async function deleteSavedMeal(t) {
    if (!window.confirm(`Delete the saved meal "${t.name}"? Logged entries are not affected.`)) return false;
    try {
      await api.deleteMeal(t.id);
      toast('Saved meal deleted', 'ok');
      await loadMeals(true);
      renderSavedMeals();
      return true;
    } catch (err) { toastError(err); return false; }
  }

  // ---- Shopping list (checks live only in localStorage) --------------------
  function shopKey(start) { return `${SHOP_KEY}:${start}`; }
  function loadChecks(start) {
    try { const v = JSON.parse(localStorage.getItem(shopKey(start)) || '[]'); return new Set(Array.isArray(v) ? v : []); } catch (e) { return new Set(); }
  }
  function saveChecks(start, set) {
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
  $('#copy-form').addEventListener('submit', async (e) => {
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
  $('#apply-form').addEventListener('submit', async (e) => {
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
  $('#savemeal-form').addEventListener('submit', async (e) => {
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
  $('#meal-form').addEventListener('submit', async (e) => {
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
  $('#meal-delete').addEventListener('click', async () => {
    if (mealEd.id == null) return;
    const t = (state.meals || []).find((x) => x.id === mealEd.id) || { id: mealEd.id, name: $('#meal-name').value };
    if (await deleteSavedMeal(t)) mealDlg.close();
  });

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  async function init() {
    applyTheme(storedTheme());
    dateInput.value = state.date;
    if (MOCK) {
      document.title = 'Kidney Diet Log (mock)';
      $('.brand-name').textContent = 'Kidney Diet Log · mock';
    }
    try { await loadProfile(); } catch (e) { toastError(e); }
    const initial = location.hash.replace('#', '');
    showView(VIEWS.includes(initial) ? initial : 'today');
  }
  init();
})();
