/* Kidney Diet Log — meal guidance, part 1 of 9: constants, rounding, names, roles and food vectors.
   The browser twin of app/guidance/rules.py, vectors.py and state.py (note 06 §4.1–§4.3).

   The guidance engine runs on the server; this twin (js/engine/guidance/*.js) powers the demo/preview
   API (js/mock/guidance.js), where there is no server. Every number, rule and sentence is the
   server's: the files mirror the Python modules one to one (rules, messages + topics, budget, score,
   fits, swaps, planner, insights, hypo) and keep their function and field names (snake_case data
   fields as in the JSON, camelCase functions), so a change on one side is easy to find on the other.

   Parity: tests/data/guidance_vectors.json is generated from the Python engine
   (tests/data/gen_guidance_vectors.py; pytest checks it is current) and replayed here by
   `node tests/js/run_vectors.mjs`. Floating point is kept bit for bit: the same operations in the same
   order (Python's `x ** 2` is not used by the server except once, see score.js), scores rounded with
   Math.round semantics, display numbers with the app's half-up rounding (KH.rules.halfUp).

   Plain script (no imports): needs js/engine/rules.js first; sets window.KH.guidanceEngine (and runs
   under Node with the same bare-global shim as rules.js). No DOM. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});
  const GE = KH.guidanceEngine || (KH.guidanceEngine = {});
  const { NUTRIENT_KEYS } = KH.rules;

  const RULES_VERSION = '2026-10-06.1';
  // rules.rules_hash() of this RULES_VERSION (sha256 over the sorted JSON of the rules table, first 16 hex
  // digits). The runner checks it against the vectors and tests/test_guidance_ui.py against the server.
  const RULES_HASH = '6ef4fb557606f4e1';

  const MAIN_MEALS = ['breakfast', 'lunch', 'dinner'];
  const SNACK = 'snack';
  const SLOT_ORDER = ['breakfast', 'lunch', 'dinner', 'snack'];
  const K = 'potassium_mg', P = 'phosphorus_mg', NA = 'sodium_mg', FLUID = 'fluid_ml', CARBS = 'carbs_g',
    PROTEIN = 'protein_g', KCAL = 'calories_kcal';

  const MEAL_WEIGHT = { breakfast: 0.30, lunch: 0.30, dinner: 0.30, snack: 0.15 };
  const MEAL_CAP_FRACTION = { breakfast: 0.30, lunch: 0.30, dinner: 0.30, snack: 0.15 };
  const ROOM_KEYS = [K, P, NA, FLUID];
  const CAP_KEYS = [K, P, NA];
  const RENAL_KEYS = [K, P, NA];
  const DAY_JUDGED = [K, NA, FLUID];
  const INTERDIALYTIC_KEYS = [K, NA, FLUID];
  const NEGLIGIBLE = { [K]: 50.0, [NA]: 50.0, [P]: 30.0, [FLUID]: 30.0, [CARBS]: 5.0 };
  const USAGE_WEIGHT = { [K]: 3.0, [NA]: 2.0, [P]: 2.0, [FLUID]: 2.0 };
  const USAGE_WEIGHT_P_NOT_OK = 3.0;
  const PORTIONS_MAIN = [1.0, 0.5, 1.5, 2.0];
  const PORTIONS_SIDE = [1.0, 0.5];
  const PORTIONS_BUILD = [1.0, 0.5];
  const PORTIONS_BUILD_PROTEIN = [1.0, 0.5, 1.5];
  const WEEK_LOOKBACK_DAYS = 6;
  const WEEK_CLAMP = [0.8, 1.2];
  const CARB_TOLERANCE_G = 10;
  const CARB_TOLERANCE_RANGE = [5, 20];
  const SNACK_CARB_MIN_G = 15;
  const HYPO_DOSE_G = 15;
  const HYPO_DOSE_RANGE = [5, 30];
  const HIGH_K_ENTRY_MG = 200.0;
  const PROTEIN_ROLE_MIN_G = 7.0;
  const STARCH_ROLE_MIN_CARBS_G = 15.0;
  const P_PER_G_PROTEIN = [10.0, 16.0];
  const K_PER_G_PROTEIN = [10.0, 20.0];
  const PROTEIN_AIM_FLOOR_G = 5.0;
  const MIN_SHOW_SCORE = 0.0;
  const GROUP_LIMITS = { protein: 3, starch: 3, veg_fruit: 3, extra: 2 };
  const CATEGORY_LIMIT = 2;
  const DEFAULT_LIMIT = 11;
  const MAX_LIMIT = 20;
  const BEAM_WIDTH = 16;
  const BEAM_WIDTH_RANGE = [1, 64];
  const PER_ROLE = 6;
  const POOL_PER_ROLE = 200;
  const POOL_PER_ROLE_RANGE = [20, 2000];
  const FAMILIAR_MARGIN = 3.0;
  const SLOT_HABIT_BONUS = 1.0;
  const SLOT_HABIT_MIN_DAYS = 2;
  const OFTEN_MIN_DAYS = 2;
  const HISTORY_DAYS = 14;
  const USUAL_HISTORY_DAYS = 60;
  const USUAL_MIN_ITEMS = 2, USUAL_MAX_ITEMS = 6, USUAL_MIN_DATES = 2;
  const SWAP_MIN_REDUCTION = 0.25;
  const SWAP_CARB_MATCH = [5.0, 0.10];
  const SWAP_PROTEIN_MATCH = [3.0, 0.15];
  const SWAP_MATCH_CARBS_MIN_G = 10.0;
  const SWAP_MATCH_PROTEIN_MIN_G = 3.0;
  const SWAP_MAX = 5;
  const SWAP_AI_MAX = 15;
  const PORTION_MIN = 0.25, PORTION_MAX = 3.0;
  const PORTION_OPTION_FRACTIONS = [0.75, 0.5];
  const HYPO_PORTION_MAX = 10.0;
  const HYPO_WHOLE_UNITS = ['tablet', 'piece', 'candy', 'candies', 'sweet', 'lozenge', 'gummy', 'gummies',
    'chew', 'pastille', 'mint', 'jelly bean', 'cube', 'sachet', 'packet'];
  const HYPO_SWAP_TRIGGER_MG = 0.0;
  const HYPO_INSIGHT_K_MG = 50.0;
  const HYPO_BEST_MAX_K_MG = 20.0;
  const INSIGHT_MAX = 6;
  const SOURCE_MIN_SHARE = 0.10;
  const SOURCE_MAX = 3;
  const MIN_LOGGED_DAYS = 3;
  const PERIOD_DEFAULT_DAYS = 7;
  const PERIOD_MAX_DAYS = 92;
  const PERIOD_CHANGE_MIN = 0.15;
  const MEAL_SHARE_MIN = 0.45;
  const PERIOD_HYPO_MIN = 3;
  const SAVED_MEAL_SCALES = [1.0, 0.75, 0.5];
  const SAVED_MEALS_MAX = 3;
  const AI_FOODS_MAX = 40;
  const AI_FOODS_PER_GROUP_MIN = 6;
  const AI_MEALS_MAX = 5;
  const AI_PLAN_OPTIONS_MAX = 5;
  const AI_QUARTERS_RANGE = [1, 12];
  const ENERGY_NOTE_FRACTION = 0.8;
  const ENERGY_LOW_INSIGHT_FRACTION = 0.7;
  const ENERGY_DENSE_MIN_KCAL = 50.0;
  const ENERGY_DENSE_MAX = { [K]: 50.0, [P]: 30.0, [NA]: 50.0, [CARBS]: 5.0 };
  const ENERGY_NOTE_FOODS = 3;
  const PROTEIN_TOPUP_STEP = 0.5;
  const PROTEIN_TOPUP_STEPS = 2;
  const REPAIR_STEP = 0.25;
  const REPAIR_STEPS = 6;
  const VARIANT_MAX = 4;
  const UNKNOWN_PENALTY = 1.5;
  const FREE_FOOD_CARBS_G = 5.0;
  const HIGH_GI_PENALTY_MIN_CARBS_G = 15.0;
  const FILLS_CARBS_MIN_G = 15.0;
  const LOW_K_REASON_MG = 100.0;
  const LOW_P_REASON_MG = 50.0;
  const MAX_NAME_CHARS = 60;
  const RENAL_MEDIUM = { [K]: 101.0, [P]: 101.0, [NA]: 141.0 };
  const RENAL_HIGH = { [K]: 200.0, [P]: 150.0, [NA]: 400.0 };

  const ROLES = ['protein', 'mixed', 'starch', 'veg_fruit', 'drink', 'extra'];
  const GROUP_OF_ROLE = { protein: 'protein', mixed: 'protein', starch: 'starch', veg_fruit: 'veg_fruit', drink: 'extra', extra: 'extra' };
  const GROUPS = ['protein', 'starch', 'veg_fruit', 'extra'];
  const GROUP_LABEL = { protein: 'protein', starch: 'starch', veg_fruit: 'vegetable or fruit', extra: 'extra' };
  const CARB_FILL_ROLES = new Set(['starch', 'mixed', 'veg_fruit']);
  const PROTEIN_ROLES = new Set(['protein', 'mixed']);
  const STARCH_ROLES = new Set(['starch', 'mixed']);
  const MAIN_PORTION_ROLES = new Set(['protein', 'mixed', 'starch', 'veg_fruit']);
  const MAIN_ROLE_STEPS = ['protein', 'starch', 'veg_fruit'];
  const SNACK_ROLES = ['veg_fruit', 'starch', 'extra', 'drink'];
  const INGREDIENT_FLAG = 'ingredient';
  const SUPPLIES_CATEGORY = 'Diabetes supplies';
  const BEVERAGES = 'Beverages';
  const VEGETABLES = 'Vegetables';
  const LEACHING_STEMS = ['potato', 'sweet potato', 'yam', 'carrot', 'beet', 'squash'];
  const SEVERITY_ORDER = { warning: 0, attention: 1, info: 2, good: 3 };
  const NUTRIENT_PRIORITY = { [K]: 0, [P]: 1, [NA]: 2, [FLUID]: 3, [PROTEIN]: 4, [CARBS]: 5 };
  // js_round(v) > H  ⇔  v ≥ H + 0.5, and js_round(v) ≥ M  ⇔  v ≥ M − 0.5 (rules.RENAL_*_CUT).
  const RENAL_HIGH_CUT = { [K]: 200.5, [P]: 150.5, [NA]: 400.5 };
  const RENAL_MEDIUM_CUT = { [K]: 100.5, [P]: 100.5, [NA]: 140.5 };

  // -------------------------------------------------------------------------
  // Rounding (rules.js_round / round_to / round_score / round_to_quarter / ceil_to_step)
  // -------------------------------------------------------------------------
  // Python's math.floor returns an int, so js_round never yields -0.0: `+ 0` turns a -0 floor into 0.
  function jsRound(value) {
    const f = Math.floor(value);
    return value - f >= 0.5 ? f + 1.0 : f + 0;
  }
  function roundTo(value, places) {
    const factor = 10.0 ** places;
    return jsRound(value * factor) / factor;
  }
  function roundScore(value) { return roundTo(value, 2); }
  function roundToQuarter(value) { return jsRound(value * 4.0) / 4.0; }
  function ceilToStep(value, step) {
    const units = value / step;
    const nearest = jsRound(units);
    if (Math.abs(units - nearest) < 1e-9) return nearest * step;
    return (Math.ceil(units) + 0) * step; // math.ceil is an int too
  }
  function clamp(value, lo, hi) { return value < lo ? lo : value > hi ? hi : value; }

  // -------------------------------------------------------------------------
  // Python string semantics: str.casefold() and code-point ordering
  // -------------------------------------------------------------------------
  // casefold = lower case plus Unicode full case folding for the characters food names can carry
  // (ß, final sigma, Latin ligatures); toLowerCase covers the rest the same way Python's lower() does.
  const FULL_FOLD = { 'ß': 'ss', 'ẞ': 'ss', 'ς': 'σ', 'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬅ': 'st', 'ﬆ': 'st',
    'ŉ': 'ʼn', 'ǰ': 'ǰ', 'ẖ': 'ẖ', 'ẗ': 'ẗ', 'ẘ': 'ẘ', 'ẙ': 'ẙ', 'ẚ': 'aʾ', 'ſ': 's', 'ι': 'ι', 'ϐ': 'β', 'ϑ': 'θ', 'ϕ': 'φ',
    'ϖ': 'π', 'ϰ': 'κ', 'ϱ': 'ρ', 'ϵ': 'ε', 'ẛ': 'ṡ', 'ﬓ': 'մն', 'ﬔ': 'մե', 'ﬕ': 'մի', 'ﬖ': 'վն', 'ﬗ': 'մխ', 'և': 'եւ' };
  const FOLD_RE = new RegExp(`[${Object.keys(FULL_FOLD).join('')}]`, 'gu');
  const foldCache = new Map();
  function casefold(text) {
    const s = String(text == null ? '' : text);
    let out = foldCache.get(s);
    if (out === undefined) {
      out = s.toLowerCase();
      if (/[^\u0000-\u007f]/.test(out)) out = out.replace(FOLD_RE, (ch) => FULL_FOLD[ch]);
      if (foldCache.size > 20000) foldCache.clear();
      foldCache.set(s, out);
    }
    return out;
  }
  // Python compares str by code point; JS `<` by UTF-16 unit. They differ only between a surrogate
  // (U+D800–DFFF, i.e. a character above U+FFFF) and a unit from U+E000 up.
  function cmpStr(a, b) {
    if (a === b) return 0;
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) {
      const x = a.charCodeAt(i), y = b.charCodeAt(i);
      if (x === y) continue;
      const sx = x >= 0xd800 && x <= 0xdfff, sy = y >= 0xd800 && y <= 0xdfff;
      if (sx !== sy) return sx ? (y >= 0xe000 ? 1 : -1) : (x >= 0xe000 ? -1 : 1);
      return x < y ? -1 : 1;
    }
    return a.length - b.length;
  }
  // Python tuple ordering over numbers, strings and nested arrays.
  function cmp(a, b) {
    if (typeof a === 'number') return a < b ? -1 : a > b ? 1 : 0;
    if (typeof a === 'string') return cmpStr(a, b);
    if (Array.isArray(a)) {
      const n = Math.min(a.length, b.length);
      for (let i = 0; i < n; i++) {
        const c = cmp(a[i], b[i]);
        if (c) return c;
      }
      return a.length - b.length;
    }
    if (a == null && b == null) return 0;
    throw new TypeError(`cannot compare ${typeof a}`);
  }
  // sorted(items, key=keyFn): stable, keys computed once.
  function sortBy(items, keyFn) {
    const decorated = items.map((item, i) => [keyFn(item), i, item]);
    decorated.sort((x, y) => cmp(x[0], y[0]) || x[1] - y[1]);
    return decorated.map((d) => d[2]);
  }
  // max()/min() with a key: the first element with the largest/smallest key.
  function maxBy(items, keyFn) {
    let best = null, bestKey = null;
    for (const item of items) { const k = keyFn(item); if (bestKey === null || cmp(k, bestKey) > 0) { best = item; bestKey = k; } }
    return best;
  }
  function minBy(items, keyFn) {
    let best = null, bestKey = null;
    for (const item of items) { const k = keyFn(item); if (bestKey === null || cmp(k, bestKey) < 0) { best = item; bestKey = k; } }
    return best;
  }
  // Python's built-in sum() over floats on 3.11 (left to right from 0; the server's vectors use it).
  function pySum(values) { let s = 0; for (const v of values) s += v; return s; }

  // Python's str.isalnum() for one code point (letters and numbers of any script).
  const ALNUM = /^[\p{L}\p{N}]$/u;
  function familyOf(name) {
    let word = '';
    for (const ch of casefold(String(name == null ? '' : name).trim())) {
      if (ALNUM.test(ch)) word += ch;
      else if (word) break;
    }
    return word;
  }

  // ISO dates (YYYY-MM-DD) without time zones: the engine's own calendar maths.
  function parseIso(s) { const [y, m, d] = String(s).split('-').map(Number); return Date.UTC(y, m - 1, d); }
  function isoOf(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function addDays(s, n) { return isoOf(parseIso(s) + n * 86400000); }
  function daysBetween(a, b) { return Math.round((parseIso(b) - parseIso(a)) / 86400000); }
  function weekday(s) { return (new Date(parseIso(s)).getUTCDay() + 6) % 7; } // 0 = Monday … 6 = Sunday

  // -------------------------------------------------------------------------
  // Roles, eligibility helpers, targets
  // -------------------------------------------------------------------------
  function roleOf(category, carbs, protein, override = null) {
    if (ROLES.includes(override)) return override;
    const cat = category || '';
    const c = carbs || 0.0;
    const pr = protein || 0.0;
    if (cat === 'Meat, Poultry & Eggs' || cat === 'Fish & Seafood') return 'protein';
    if (cat === 'Prepared & Fast Food' && pr >= PROTEIN_ROLE_MIN_G && c >= STARCH_ROLE_MIN_CARBS_G) return 'mixed';
    if ((cat === 'Dairy & Alternatives' || cat === 'Legumes, Nuts & Seeds' || cat === 'Prepared & Fast Food') && pr >= PROTEIN_ROLE_MIN_G) return 'protein';
    if (cat === 'Grains & Breads') return 'starch';
    if ((cat === VEGETABLES || cat === 'Legumes, Nuts & Seeds' || cat === 'Prepared & Fast Food') && c >= STARCH_ROLE_MIN_CARBS_G) return 'starch';
    if (cat === VEGETABLES || cat === 'Fruits') return 'veg_fruit';
    if (cat === BEVERAGES) return 'drink';
    return 'extra';
  }
  function groupOf(role) { return GROUP_OF_ROLE[role] || 'extra'; }
  function portionsFor(role) { return MAIN_PORTION_ROLES.has(role) ? PORTIONS_MAIN : PORTIONS_SIDE; }
  function textHasAny(text, stems) { const folded = casefold(text || ''); return stems.some((s) => folded.includes(s)); }

  function isDict(v) { return v != null && typeof v === 'object' && !Array.isArray(v); }
  function targetMax(target) {
    if (target == null || typeof target === 'boolean') return null;
    const hi = isDict(target) ? target.max : target;
    if (hi == null || typeof hi === 'boolean') return hi === true ? 1 : hi === false ? null : null;
    const value = typeof hi === 'number' ? hi : typeof hi === 'string' && hi.trim() !== '' ? Number(hi) : NaN;
    if (!Number.isFinite(value) || value <= 0) return null;
    return value;
  }
  function targetMin(target) {
    if (!isDict(target)) return null;
    const lo = target.min;
    if (lo == null || typeof lo === 'boolean') return null;
    const value = typeof lo === 'number' ? lo : typeof lo === 'string' && lo.trim() !== '' ? Number(lo) : NaN;
    if (!Number.isFinite(value) || value < 0) return null;
    return value;
  }

  // "1 tablet (4 g)", "1 glucose tablet", "1 piece": one serving is one item counted out whole for a low.
  const UNITS_ALT = [...HYPO_WHOLE_UNITS].sort((a, b) => b.length - a.length).map((u) => u.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const WHOLE_UNIT = new RegExp(`^\\s*(?:1|one)\\s+(?:[a-z-]+\\s+)?(?:${UNITS_ALT})s?(?![\\p{L}\\p{N}_])`, 'iu');
  function isWholeUnitServing(servingDesc) { return !!servingDesc && WHOLE_UNIT.test(servingDesc); }
  function hypoPortionStep(servingDesc) { return isWholeUnitServing(servingDesc) ? 1.0 : 0.25; }

  // -------------------------------------------------------------------------
  // Food vectors (vectors.py)
  // -------------------------------------------------------------------------
  function renalLevel(k, p, na, additive) {
    if (additive) return 'red';
    if ((k != null && k >= RENAL_HIGH_CUT[K]) || (p != null && p >= RENAL_HIGH_CUT[P]) || (na != null && na >= RENAL_HIGH_CUT[NA])) return 'red';
    if ((k != null && k >= RENAL_MEDIUM_CUT[K]) || (p != null && p >= RENAL_MEDIUM_CUT[P]) || (na != null && na >= RENAL_MEDIUM_CUT[NA])) return 'yellow';
    return 'green';
  }
  function isHigh(key, value) { return value != null && value >= RENAL_HIGH_CUT[key]; }
  function proteinQuality(proteinG, potassiumMg, phosphorusMg) {
    const out = { p_per_g: null, k_per_g: null, p_grade: null, k_grade: null };
    if (proteinG == null || proteinG < PROTEIN_ROLE_MIN_G) return out;
    if (phosphorusMg != null) {
      const ratio = phosphorusMg / proteinG;
      out.p_per_g = ratio;
      out.p_grade = ratio <= P_PER_G_PROTEIN[0] ? 'good' : ratio >= P_PER_G_PROTEIN[1] ? 'poor' : 'fair';
    }
    if (potassiumMg != null) {
      const ratio = potassiumMg / proteinG;
      out.k_per_g = ratio;
      out.k_grade = ratio <= K_PER_G_PROTEIN[0] ? 'good' : ratio >= K_PER_G_PROTEIN[1] ? 'poor' : 'fair';
    }
    return out;
  }
  // vectors.make_food: one food as the engine sees it (per-serving floats, null = unknown, never 0).
  function makeFood({ id, name, category = null, serving_desc, serving_g, nutrients, flags = [], source = 'builtin', fdc_id = null,
    kidney_notes = null, hidden = false, role = null }) {
    const values = {};
    for (const key of NUTRIENT_KEYS) {
      const v = nutrients ? nutrients[key] : null;
      values[key] = v == null ? null : Number(v);
    }
    const flagSet = new Set((flags || []).map(String));
    const carbs = values.carbs_g, protein = values.protein_g;
    const r = roleOf(category, carbs, protein, role);
    const additive = flagSet.has('phosphate_additive');
    return {
      id: Number(id), name: String(name), category, source, fdc_id, serving_desc: String(serving_desc), serving_g: Number(serving_g),
      flags: flagSet, kidney_notes, hidden: !!hidden, nutrients: values, role: r, group: groupOf(r), family: familyOf(name),
      name_fold: casefold(name), carbs, protein, k: values[K], p: values[P], na: values[NA], fluid: values[FLUID], kcal: values[KCAL],
      additive, processed: flagSet.has('processed'), high_gi: flagSet.has('high_gi'), hypo: flagSet.has('hypo_treatment'),
      avoid: flagSet.has('avoid_ckd'), ingredient: flagSet.has(INGREDIENT_FLAG), supplies: category === SUPPLIES_CATEGORY,
      beverage: category === BEVERAGES, level1: renalLevel(values[K], values[P], values[NA], additive),
    };
  }

  // -------------------------------------------------------------------------
  // State (state.py): day entries, history entries, the context
  // -------------------------------------------------------------------------
  function dayEntry({ id = null, meal, status, food, name = null, servings, nutrients, purpose = null }) {
    return { id, meal, status, food_id: food.id, name: name == null ? food.name : name, servings: Number(servings), nutrients,
      purpose, hypo: purpose === 'hypo', role: food.role, group: groupOf(food.role), family: food.family, category: food.category, flags: food.flags };
  }
  function historyEntry({ date, meal, food_id, name, servings, nutrients, purpose = null, flags = new Set() }) {
    return { date, meal, food_id, name, servings: Number(servings), nutrients, purpose, hypo: purpose === 'hypo',
      flags: flags instanceof Set ? flags : new Set(flags || []) };
  }
  function scaledValues(food, servings) {
    const out = {};
    for (const key of Object.keys(food.nutrients)) { const v = food.nutrients[key]; out[key] = v == null ? null : v * servings; }
    return out;
  }
  function virtualEntry(food, meal, servings) {
    return dayEntry({ id: null, meal, status: 'planned', food, servings, nutrients: scaledValues(food, servings), purpose: null });
  }
  // GuidanceContext: { date, profile, prefs, foods (Map id → food), day, history, history60, saved_meals, combos, tunables }.
  function makeContext({ date, profile, prefs = {}, foods, day = [], history = [], history60 = null, saved_meals = [], combos = [], tunables = {} }) {
    return {
      date,
      profile: { targets: profile.targets || {}, warn_fraction: profile.warn_fraction == null ? 0.8 : Number(profile.warn_fraction),
        dialysis: profile.dialysis || 'none', dialysis_days: [...(profile.dialysis_days || [])], diabetes: profile.diabetes || 'type1',
        targets_updated_at: profile.targets_updated_at == null ? null : profile.targets_updated_at },
      prefs: { carb_tolerance_g: Number(prefs.carb_tolerance_g == null ? CARB_TOLERANCE_G : prefs.carb_tolerance_g),
        hypo_dose_g: Number(prefs.hypo_dose_g == null ? HYPO_DOSE_G : prefs.hypo_dose_g),
        exclude_food_ids: new Set((prefs.exclude_food_ids || []).map(Number)), exclude_categories: new Set(prefs.exclude_categories || []) },
      foods,
      day,
      history,
      history60: history60 == null ? history : history60,
      saved_meals,
      combos,
      tunables: { pool_per_role: tunables.pool_per_role == null ? POOL_PER_ROLE : Number(tunables.pool_per_role),
        beam_width: tunables.beam_width == null ? BEAM_WIDTH : Number(tunables.beam_width) },
    };
  }
  function withDay(ctx, day) { return { ...ctx, day }; }

  // -------------------------------------------------------------------------
  // The rules table (GET /api/guidance/rules): every number with the reason it has that value
  // -------------------------------------------------------------------------
  const RULE_DOCS = [
    ['MEAL_WEIGHT', "Share of the day's remaining room per open slot; reproduces AKF's 600 mg per meal at 2,000 mg (F1)"],
    ['MEAL_CAP_FRACTION', "Per-meal cap as a fraction of the day's target: 0.30 per main meal, 0.15 for all snacks (F1; phosphorus by analogy, F2)"],
    ['CAP_KEYS', 'Nutrients with a per-meal cap (fluid has a day allowance only)'],
    ['NEGLIGIBLE', 'Amounts that never count against a room; carbs: a "free" food has ≤ 5 g (UW Food Choice Lists, F4)'],
    ['USAGE_WEIGHT', 'How much using up each room costs in a score; potassium acts fastest (diet guide §2)'],
    ['USAGE_WEIGHT_P_NOT_OK', "Phosphorus weight while this week's phosphorus is not ok"],
    ['PORTIONS_MAIN', 'Portions tried for protein, mixed, starch and vegetable/fruit foods (servings)'],
    ['PORTIONS_SIDE', 'Portions tried for drinks and extras: never two root beers (F10)'],
    ['PORTIONS_BUILD', 'Portions tried when ranking plan-day candidates'],
    ['PORTIONS_BUILD_PROTEIN', 'Portions tried for plan-day protein candidates'],
    ['WEEK_LOOKBACK_DAYS', 'Previous days that balance week-judged phosphorus (§3.3)'],
    ['WEEK_CLAMP', 'Phosphorus allowance today, as a fraction of the daily target, never outside this range (§3.3)'],
    ['CARB_TOLERANCE_G', 'Grams either side of the meal carb goal that count as on target (Smart 2009/2012, F4); a personal setting'],
    ['CARB_TOLERANCE_RANGE', 'Allowed range of the personal carb tolerance (g)'],
    ['SNACK_CARB_GOAL', 'Carb goal of the snack slot (NKF: 1–3 carb choices per snack, F4)'],
    ['SNACK_CARB_MIN_G', 'Smallest snack carb goal: one carb choice'],
    ['HYPO_DOSE_G', 'Carbs that treat a low (rule of 15, ADA 2026 Rec 6.15, F5); a personal setting from the diabetes team'],
    ['HYPO_DOSE_RANGE', 'Allowed range of the personal low-treatment amount (g; 5–10 g on automated insulin delivery)'],
    ['HIGH_K_ENTRY_MG', 'A "high-potassium portion" (the app\'s per-serving high); AKF/UW: not several in one day'],
    ['PROTEIN_ROLE_MIN_G', 'A protein portion has at least this much protein (NKF: 7 g = 1 oz of meat, F3)'],
    ['STARCH_ROLE_MIN_CARBS_G', 'A starch has at least one carb choice'],
    ['P_PER_G_PROTEIN', 'Phosphorus per gram of protein: good at or below, poor at or above (Noori 2010, F2)'],
    ['K_PER_G_PROTEIN', 'Potassium per gram of protein: good at or below, poor at or above (design choice: chicken breast 8, ground chicken 29)'],
    ['PROTEIN_AIM_FLOOR_G', 'Smallest protein aim used in a score (avoids dividing by tiny aims)'],
    ['MIN_SHOW_SCORE', 'Foods scoring below this are not shown as "fits"'],
    ['GROUP_LIMITS', 'At most this many suggestions per group'],
    ['CATEGORY_LIMIT', 'At most this many suggestions per food category'],
    ['DEFAULT_LIMIT', 'Suggestions returned by default'],
    ['MAX_LIMIT', 'Most suggestions a request may ask for'],
    ['BEAM_WIDTH', 'Partial meals kept at each step of the plan builder (admin: GUIDANCE_BEAM_WIDTH; §3.4)'],
    ['BEAM_WIDTH_RANGE', 'Allowed range of the beam width'],
    ['PER_ROLE', 'Best candidates per role the plan builder combines'],
    ['POOL_PER_ROLE', 'Foods per role pre-ranked for the plan builder (admin: GUIDANCE_POOL_PER_ROLE; F8)'],
    ['POOL_PER_ROLE_RANGE', 'Allowed range of the pool size'],
    ['FAMILIAR_MARGIN', 'A saved, usual or starter meal wins if it scores at least the best built meal minus this'],
    ['SLOT_HABIT_BONUS', 'Bonus for a food eaten in this meal slot on enough recent days (F10: no pasta at breakfast)'],
    ['SLOT_HABIT_MIN_DAYS', 'Days in the last 14 a food must have been eaten in the slot for the bonus'],
    ['OFTEN_MIN_DAYS', 'Days in the last 14 for "You often have this"'],
    ['HISTORY_DAYS', 'Days of history for habit, variety and the phosphorus week'],
    ['USUAL_HISTORY_DAYS', 'Days of history mined for usual meals'],
    ['USUAL_MIN_ITEMS', 'Fewest foods in a usual meal'],
    ['USUAL_MAX_ITEMS', 'Most foods in a usual meal'],
    ['USUAL_MIN_DATES', 'A usual meal was eaten on at least this many dates'],
    ['SWAP_MIN_REDUCTION', 'A swap lowers every nutrient that triggered it by at least this fraction'],
    ['SWAP_CARB_MATCH', "A swap's carbs stay within max(min_g, fraction × original): the insulin arithmetic stays the same (F4)"],
    ['SWAP_PROTEIN_MATCH', 'A swap matched on protein stays within max(min_g, fraction × original)'],
    ['SWAP_MATCH_CARBS_MIN_G', 'Swaps match carbs when the original has at least this much'],
    ['SWAP_MATCH_PROTEIN_MIN_G', 'Otherwise they match protein when the original has at least this much'],
    ['SWAP_MAX', 'Swap ideas returned'],
    ['SWAP_AI_MAX', 'Rule swaps handed to the optional AI layer'],
    ['PORTION_RANGE', 'Every planned or swapped portion is between these servings'],
    ['PORTION_MIN', 'Smallest portion (servings)'],
    ['PORTION_MAX', 'Largest portion (servings)'],
    ['PORTION_OPTION_FRACTIONS', 'Smaller-portion fallbacks of a swap request (¾, then ½)'],
    ['HYPO_PORTION_MAX', 'Largest low-treatment portion (servings): enough single 4 g glucose tablets for the 30 g maximum dose; never fewer carbs than the dose'],
    ['HYPO_WHOLE_UNITS', 'A serving of one of these items ("1 tablet") is counted out whole for a low, rounded up'],
    ['HYPO_SWAP_TRIGGER_MG', 'In low-treatment mode the only trigger is potassium above this'],
    ['HYPO_INSIGHT_K_MG', 'A low treatment above this potassium makes the insight name a lower-potassium choice'],
    ['HYPO_BEST_MAX_K_MG', "… when one of the person's low treatments has at most this much"],
    ['INSIGHT_MAX', 'Insights returned'],
    ['SOURCE_MIN_SHARE', 'A food is named as a source when it gave at least this share'],
    ['SOURCE_MAX', 'Sources listed per insight'],
    ['MIN_LOGGED_DAYS', 'Logged days needed for period insights'],
    ['PERIOD_DEFAULT_DAYS', 'Default insight period (the days ending yesterday)'],
    ['PERIOD_MAX_DAYS', 'Longest insight period'],
    ['PERIOD_CHANGE_MIN', 'A change against the previous period is reported from this fraction'],
    ['MEAL_SHARE_MIN', 'One meal slot giving at least this share of potassium or sodium is reported'],
    ['PERIOD_HYPO_MIN', 'Low treatments in a period from which the diabetes team may want to know'],
    ['SAVED_MEAL_SCALES', 'Sizes a saved, usual or starter meal is tried at'],
    ['SAVED_MEALS_MAX', 'Fitting saved and usual meals returned'],
    ['AI_FOODS_MAX', 'Candidate foods handed to the optional AI layer (note 04 R2)'],
    ['AI_FOODS_PER_GROUP_MIN', '… at least this many per group when available'],
    ['AI_MEALS_MAX', 'Saved or usual meals handed to the AI layer'],
    ['AI_PLAN_OPTIONS_MAX', 'Options per slot the AI layer may pick from'],
    ['AI_QUARTERS_RANGE', "An AI idea's portion in quarter servings (note 04 V3)"],
    ['ENERGY_NOTE_FRACTION', 'A plan below this share of the calorie goal gets the energy note (R2: under-eating)'],
    ['ENERGY_LOW_INSIGHT_FRACTION', 'A logged day below this share of the calorie goal gets the eating-enough insight'],
    ['ENERGY_DENSE_MIN_KCAL', 'An energy-dense, low-mineral food has at least this many kcal per serving'],
    ['ENERGY_DENSE_MAX', '… and at most these minerals and carbs per serving'],
    ['ENERGY_NOTE_FOODS', 'Energy-dense foods named in the note'],
    ['PROTEIN_TOPUP_STEP', "Servings added to a built meal's protein item when the day is below its protein minimum"],
    ['PROTEIN_TOPUP_STEPS', 'Most top-up steps per meal'],
    ['REPAIR_STEP', 'Servings taken off a built item when the plan would make a day-judged nutrient newly over'],
    ['REPAIR_STEPS', 'Most repair steps before the slot is marked partial'],
    ['VARIANT_MAX', 'Most "Show another plan" variants'],
    ['UNKNOWN_PENALTY', 'Score cost of each unknown potassium, phosphorus or sodium value (unknown is never 0, note 03)'],
    ['FREE_FOOD_CARBS_G', "A food with at most this many carbs is free once the meal's carbs are done"],
    ['HIGH_GI_PENALTY_MIN_CARBS_G', 'High-glycaemic foods cost a point from one carb choice'],
    ['FILLS_CARBS_MIN_G', '"Brings the meal to … carbs" needs at least one carb choice'],
    ['LOW_K_REASON_MG', '"Low in potassium" at or below this portion amount'],
    ['LOW_P_REASON_MG', '"Low in phosphorus" at or below this portion amount'],
    ['MAX_NAME_CHARS', 'Food names in sentences are cut to this length (custom names are untrusted text)'],
    ['RENAL_MEDIUM', 'Per-portion "medium" thresholds of the renal rating (the app\'s warnings, ARCHITECTURE)'],
    ['RENAL_HIGH', 'Per-portion "high" thresholds (above this, rounded to whole mg)'],
  ];
  const CONSTANTS = {
    MEAL_WEIGHT, MEAL_CAP_FRACTION, CAP_KEYS, NEGLIGIBLE, USAGE_WEIGHT, USAGE_WEIGHT_P_NOT_OK, PORTIONS_MAIN, PORTIONS_SIDE,
    PORTIONS_BUILD, PORTIONS_BUILD_PROTEIN, WEEK_LOOKBACK_DAYS, WEEK_CLAMP, CARB_TOLERANCE_G, CARB_TOLERANCE_RANGE,
    SNACK_CARB_GOAL: 'targets.carbs_per_snack_g, else max(15, 5 × round(carbs_per_meal_g / 2 / 5))', SNACK_CARB_MIN_G, HYPO_DOSE_G,
    HYPO_DOSE_RANGE, HIGH_K_ENTRY_MG, PROTEIN_ROLE_MIN_G, STARCH_ROLE_MIN_CARBS_G, P_PER_G_PROTEIN, K_PER_G_PROTEIN,
    PROTEIN_AIM_FLOOR_G, MIN_SHOW_SCORE, GROUP_LIMITS, CATEGORY_LIMIT, DEFAULT_LIMIT, MAX_LIMIT, BEAM_WIDTH, BEAM_WIDTH_RANGE,
    PER_ROLE, POOL_PER_ROLE, POOL_PER_ROLE_RANGE, FAMILIAR_MARGIN, SLOT_HABIT_BONUS, SLOT_HABIT_MIN_DAYS, OFTEN_MIN_DAYS,
    HISTORY_DAYS, USUAL_HISTORY_DAYS, USUAL_MIN_ITEMS, USUAL_MAX_ITEMS, USUAL_MIN_DATES, SWAP_MIN_REDUCTION, SWAP_CARB_MATCH,
    SWAP_PROTEIN_MATCH, SWAP_MATCH_CARBS_MIN_G, SWAP_MATCH_PROTEIN_MIN_G, SWAP_MAX, SWAP_AI_MAX, PORTION_RANGE: [PORTION_MIN, PORTION_MAX],
    PORTION_MIN, PORTION_MAX, PORTION_OPTION_FRACTIONS, HYPO_PORTION_MAX, HYPO_WHOLE_UNITS, HYPO_SWAP_TRIGGER_MG, HYPO_INSIGHT_K_MG,
    HYPO_BEST_MAX_K_MG, INSIGHT_MAX, SOURCE_MIN_SHARE, SOURCE_MAX, MIN_LOGGED_DAYS, PERIOD_DEFAULT_DAYS, PERIOD_MAX_DAYS,
    PERIOD_CHANGE_MIN, MEAL_SHARE_MIN, PERIOD_HYPO_MIN, SAVED_MEAL_SCALES, SAVED_MEALS_MAX, AI_FOODS_MAX, AI_FOODS_PER_GROUP_MIN,
    AI_MEALS_MAX, AI_PLAN_OPTIONS_MAX, AI_QUARTERS_RANGE, ENERGY_NOTE_FRACTION, ENERGY_LOW_INSIGHT_FRACTION, ENERGY_DENSE_MIN_KCAL,
    ENERGY_DENSE_MAX, ENERGY_NOTE_FOODS, PROTEIN_TOPUP_STEP, PROTEIN_TOPUP_STEPS, REPAIR_STEP, REPAIR_STEPS, VARIANT_MAX,
    UNKNOWN_PENALTY, FREE_FOOD_CARBS_G, HIGH_GI_PENALTY_MIN_CARBS_G, FILLS_CARBS_MIN_G, LOW_K_REASON_MG, LOW_P_REASON_MG,
    MAX_NAME_CHARS, RENAL_MEDIUM, RENAL_HIGH,
  };
  function plain(v) { return JSON.parse(JSON.stringify(v)); }
  function rulesTable() { return Object.fromEntries(RULE_DOCS.map(([name]) => [name, plain(CONSTANTS[name])])); }
  function ruleNotes() { return Object.fromEntries(RULE_DOCS); }

  GE.R = {
    RULES_VERSION, RULES_HASH, MAIN_MEALS, SNACK, SLOT_ORDER, K, P, NA, FLUID, CARBS, PROTEIN, KCAL,
    ...CONSTANTS, ROOM_KEYS, RENAL_KEYS, DAY_JUDGED, INTERDIALYTIC_KEYS, ROLES, GROUP_OF_ROLE, GROUPS, GROUP_LABEL,
    CARB_FILL_ROLES, PROTEIN_ROLES, STARCH_ROLES, MAIN_PORTION_ROLES, MAIN_ROLE_STEPS, SNACK_ROLES, INGREDIENT_FLAG,
    SUPPLIES_CATEGORY, BEVERAGES, VEGETABLES, LEACHING_STEMS, SEVERITY_ORDER, NUTRIENT_PRIORITY, RENAL_HIGH_CUT, RENAL_MEDIUM_CUT,
    RULE_DOCS,
    jsRound, roundTo, roundScore, roundToQuarter, ceilToStep, clamp, casefold, cmpStr, cmp, sortBy, maxBy, minBy, pySum,
    familyOf, addDays, daysBetween, weekday, roleOf, groupOf, portionsFor, textHasAny, isDict, targetMax, targetMin,
    isWholeUnitServing, hypoPortionStep, renalLevel, isHigh, proteinQuality, makeFood, dayEntry, historyEntry, scaledValues,
    virtualEntry, makeContext, withDay, rulesTable, ruleNotes,
  };
})(typeof window !== 'undefined' ? window : globalThis);
