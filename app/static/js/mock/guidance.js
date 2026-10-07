/* Kidney Diet Log — demo API: meal guidance (twin of app/guidance/api.py and context.py over the browser
   twin of the engine, js/engine/guidance/*.js).

   Routes (ARCHITECTURE.md "M2 API: guidance"): GET /api/guidance/next-meal, /swaps, /hypo-options,
   /insights/day, /insights/period, /rules, /not-for-me; POST /plan-day; PUT and DELETE
   /not-for-me/{food_id}. Query and body validation give the server's 400 texts (FastAPI query
   parameters in signature order, then the route's own checks); the answers are serialised like the
   server's response models (optional fields present as null). The demo person's context is loaded the
   way app/guidance/context.py loads it: the day's entries in log order, eaten history of the previous
   14 and 60 days, saved meals by name, the starter combos of data/combos.json (a copy below; pytest
   checks it), the "Not for me" foods and the guidance settings. AI is never available in the demo.

   Parity: tools/e2e/parity.py section 12 compares every route with a real server. */
(() => {
  'use strict';
  const KH = window.KH;
  const GE = KH.guidanceEngine;
  const R = GE.R;
  const { MEAL_KEYS } = KH.rules;
  const { todayStr } = KH.util;
  const M = KH.mock;
  const { route, MockApi, Check, fail, failFields, validDate, pydanticInt, pydanticFloat, nocaseCompare, MEAL_RANK } = M;

  const MAX_NOT_FOR_ME = 500;
  const MAX_ID = 9223372036854775807n;
  const MAX_ID_TEXT = '9223372036854775807';
  const DISABLED_BY_USER = 'Meal guidance is switched off in your settings.';
  const PLAN_OFF = 'The plan builder is switched off in your settings.';
  const INSIGHTS_OFF = 'Insights are switched off in your settings.';
  const TARGET_KEYS_SHOWN = [R.K, R.P, R.NA, R.FLUID, R.PROTEIN, R.CARBS, 'carbs_per_meal_g', 'carbs_per_snack_g', R.KCAL];
  const MEAL_CHOICE = "Input should be 'breakfast', 'lunch', 'dinner' or 'snack'";

  // data/combos.json (starter meals: diet-guide §6 sample day), items as [fdc_id, servings].
  // tests/test_guidance_ui.py fails when this copy and the file differ.
  const COMBOS = [
    { id: 'sample-day-breakfast', name: 'Sample-day breakfast: cream of wheat, blueberries, egg, toast and coffee', meal: 'breakfast',
      source: 'diet-guide §6', items: [[171657, 0.75], [171711, 1], [173424, 1], [174924, 1], [173430, 0.25], [171890, 1], [171255, 1]] },
    { id: 'sample-day-snack', name: 'Sample-day snack: applesauce and peanut butter', meal: 'snack', source: 'diet-guide §6',
      items: [[171695, 1], [174266, 0.5]] },
    { id: 'sample-day-lunch', name: 'Sample-day lunch: turkey sandwich, salad and pineapple', meal: 'lunch', source: 'diet-guide §6',
      items: [[174924, 2], [171496, 0.5], [171009, 1], [169248, 1], [168409, 1], [169126, 0.67]] },
    { id: 'sample-day-dinner', name: 'Sample-day dinner: chicken, rice, green beans and cauliflower', meal: 'dinner', source: 'diet-guide §6',
      items: [[171477, 0.66], [168878, 0.67], [169141, 2], [170397, 1], [171413, 1]] },
  ];

  // ---- query parameters (FastAPI + pydantic lax mode, as the server parses them) ------------------
  const BOOL_TRUE = ['1', 'on', 't', 'true', 'y', 'yes'];
  const BOOL_FALSE = ['0', 'off', 'f', 'false', 'n', 'no'];
  class Query {
    constructor(qp) { this.qp = qp; this.errors = []; this.out = {}; }
    err(name, msg) { this.errors.push(`${name}: ${msg}`); }
    meal(name, { required = false } = {}) {
      const v = this.qp(name);
      if (v == null) { if (required) this.err(name, 'Field required'); else this.out[name] = null; return; }
      if (!MEAL_KEYS.includes(v)) this.err(name, MEAL_CHOICE); else this.out[name] = v;
    }
    choice(name, options) {
      const v = this.qp(name);
      if (v == null) { this.out[name] = null; return; }
      if (!options.includes(v)) this.err(name, M.choiceMessage(options)); else this.out[name] = v;
    }
    int(name, { def = null, ge = null, le = null, id = false } = {}) {
      const v = this.qp(name);
      if (v == null) { this.out[name] = def; return; }
      const n = pydanticInt(v);
      if (n === undefined) { this.err(name, 'Input should be a valid integer, unable to parse string as an integer'); return; }
      if (ge != null && n < ge) { this.err(name, `Input should be greater than or equal to ${ge}`); return; }
      if (id && bigOf(v) > MAX_ID) { this.err(name, `Input should be less than or equal to ${MAX_ID_TEXT}`); return; }
      if (le != null && n > le) { this.err(name, `Input should be less than or equal to ${le}`); return; }
      this.out[name] = n;
    }
    num(name, { gt = null, le = null } = {}) {
      const v = this.qp(name);
      if (v == null) { this.out[name] = null; return; }
      const n = pydanticFloat(v);
      if (n === undefined) { this.err(name, 'Input should be a valid number, unable to parse string as a number'); return; }
      if (!Number.isFinite(n)) { this.err(name, 'Input should be a finite number'); return; }
      if (gt != null && !(n > gt)) { this.err(name, `Input should be greater than ${gt}`); return; }
      if (le != null && !(n <= le)) { this.err(name, `Input should be less than or equal to ${le}`); return; }
      this.out[name] = n;
    }
    bool(name, def = false) {
      const v = this.qp(name);
      if (v == null) { this.out[name] = def; return; }
      const low = v.trim().toLowerCase();
      if (BOOL_TRUE.includes(low)) this.out[name] = true;
      else if (BOOL_FALSE.includes(low)) this.out[name] = false;
      else this.err(name, 'Input should be a valid boolean, unable to interpret input');
    }
    str(name) { this.out[name] = this.qp(name); }
    done() { if (this.errors.length) failFields(this.errors); return this.out; }
  }
  // Python int() of a pydantic integer string, exactly (ids beyond 2**53 included).
  function bigOf(text) {
    const t = String(text).trim().replace(/_/g, '').replace(/\.0+$/, '');
    try { return BigInt(t); } catch (e) { return 0n; }
  }
  // app.guidance.api.parse_day: empty → today; else validate_date with the parameter's name.
  function parseDay(value, name = 'date') {
    if (value == null || value === '') return todayStr();
    const e = validDate(value);
    if (e) fail(400, `${name}: ${e}`);
    return value;
  }

  // ---- response models: optional fields the server always sends (as null) --------------------------
  function withNulls(obj, keys) { for (const k of keys) if (!(k in obj)) obj[k] = null; return obj; }
  function statusModel(status) {
    const out = {};
    for (const [k, v] of Object.entries(status)) out[k] = { value: v.value, target: v.target, min: v.min === undefined ? null : v.min, fraction: v.fraction, level: v.level, unknown: v.unknown || 0 };
    return out;
  }
  function planModel(result) {
    withNulls(result, ['explain']);
    for (const meal of result.meals) withNulls(meal, ['message', 'closest', 'apply_saved']);
    result.day_after.projected_status = statusModel(result.day_after.projected_status);
    result.day_after.new_alerts = result.day_after.new_alerts.map((a) => ({ level: a.level, nutrient: a.nutrient, meal: null, message: a.message }));
    return result;
  }

  Object.assign(MockApi.prototype, {
    _guidanceSetting(key) { return this._effectiveSetting(key, this._currentUser().id).value; },
    _foodPreferences() { if (!this._notForMe) this._notForMe = new Map(); return this._notForMe; },
    // The engine's food vectors, rebuilt only when a food changed (the server keys its cache by meta.foods_rev).
    _guidanceFoods() {
      let latest = '';
      for (const f of this._foods) if (f.updated_at > latest) latest = f.updated_at;
      const rev = `${this._foods.length}|${latest}`;
      if (this._guidanceVectors && this._guidanceVectors.rev === rev) return this._guidanceVectors.foods;
      const roles = this._builtinRoles || new Map();
      const foods = new Map();
      for (const f of this._foods) {
        const role = f.source === 'builtin' && f.fdc_id != null ? roles.get(f.fdc_id) || null : null;
        foods.set(f.id, GE.makeFood({ id: f.id, name: f.name, category: f.category, serving_desc: f.serving_desc, serving_g: f.serving_g,
          nutrients: f.nutrients, flags: f.flags, source: f.source, fdc_id: f.fdc_id, kidney_notes: f.kidney_notes, hidden: f.hidden, role }));
      }
      this._guidanceVectors = { rev, foods };
      return foods;
    },
    // app.guidance.context: the entries of start…end in log order (date, meal, created_at, id).
    _guidanceRows(start, end, eatenOnly) {
      return this._entries.filter((e) => e.date >= start && e.date <= end && (!eatenOnly || e.status === 'eaten'))
        .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0) || (MEAL_RANK[a.meal] ?? 3) - (MEAL_RANK[b.meal] ?? 3)
          || (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0) || a.id - b.id);
    },
    _guidanceHistory(foods, start, end) {
      return this._guidanceRows(start, end, true).map((e) => GE.historyEntry({ date: e.date, meal: e.meal, food_id: e.food_id, name: e.food_name,
        servings: e.servings, nutrients: { ...e.nutrients }, purpose: e.purpose || null, flags: (foods.get(e.food_id) || { flags: new Set() }).flags }));
    },
    _guidanceProfile() {
      const p = this._profileView();
      let warn = Number(p.warn_fraction);
      if (!Number.isFinite(warn) || !(warn > 0 && warn <= 1)) warn = 0.8;
      return { targets: { ...(p.targets || {}) }, warn_fraction: warn, dialysis: p.dialysis || 'none', dialysis_days: [...(p.dialysis_days || [])],
        diabetes: p.diabetes || 'none', targets_updated_at: p.updated_at || null };
    },
    _guidancePrefs() {
      const s = this._guidanceSetting('guidance') || {};
      return { carb_tolerance_g: Number(s.carb_tolerance_g == null ? R.CARB_TOLERANCE_G : s.carb_tolerance_g),
        hypo_dose_g: Number(s.hypo_dose_g == null ? R.HYPO_DOSE_G : s.hypo_dose_g),
        exclude_food_ids: [...this._foodPreferences().keys()], exclude_categories: [...(s.exclude_categories || [])] };
    },
    // context.load(conn, user_id, day, options)
    _guidanceContext(day, { history = true, history60 = true, savedMeals = true, combos = true } = {}) {
      const foods = this._guidanceFoods();
      const entries = this._guidanceRows(day, day, false).map((e) => GE.dayEntry({ id: e.id, meal: e.meal, status: e.status, food: foods.get(e.food_id),
        name: e.food_name, servings: e.servings, nutrients: { ...e.nutrients }, purpose: e.purpose || null }));
      let hist = [], hist60 = [];
      if (history || history60) {
        const span = history60 ? R.USUAL_HISTORY_DAYS : R.HISTORY_DAYS;
        const all = this._guidanceHistory(foods, R.addDays(day, -span), R.addDays(day, -1));
        const start14 = R.addDays(day, -R.HISTORY_DAYS);
        hist = history ? all.filter((h) => h.date >= start14) : [];
        hist60 = history60 ? all : [];
      }
      const saved = !savedMeals ? [] : [...this._templates].sort((a, b) => nocaseCompare(a.name, b.name) || a.id - b.id)
        .map((t) => ({ id: t.id, name: t.name, meal_hint: R.SLOT_ORDER.includes(t.meal_hint) ? t.meal_hint : null,
          items: t.items.map((it) => [Number(it.food_id), Number(it.servings)]) }));
      let starters = [];
      if (combos) {
        const byFdc = new Map();
        for (const f of foods.values()) if (f.source === 'builtin' && f.fdc_id != null) byFdc.set(f.fdc_id, f.id);
        starters = COMBOS.filter((c) => c.items.every(([fdc]) => byFdc.has(fdc)))
          .map((c) => ({ id: c.id, name: c.name, meal: c.meal, source: c.source, items: c.items.map(([fdc, q]) => [byFdc.get(fdc), Number(q)]) }));
      }
      return GE.makeContext({ date: day, profile: this._guidanceProfile(), prefs: this._guidancePrefs(), foods, day: entries, history: hist,
        history60: hist60, saved_meals: saved, combos: starters,
        tunables: { pool_per_role: this._effectiveSetting('guidance.pool_per_role', null).value, beam_width: this._effectiveSetting('guidance.beam_width', null).value } });
    },
    // api.gate: the server switch first, then the person's own switches.
    _guidanceGate(feature = null) {
      if (!this._effectiveSetting('guidance.enabled', null).value) return this._guidanceUnavailable('disabled', GE.M.DISABLED);
      const s = this._guidanceSetting('guidance') || {};
      if (s.enabled === false) return this._guidanceUnavailable('disabled', DISABLED_BY_USER);
      if (feature === 'plan' && s.show_plan_builder === false) return this._guidanceUnavailable('disabled', PLAN_OFF);
      if (feature === 'insights' && s.show_insights === false) return this._guidanceUnavailable('disabled', INSIGHTS_OFF);
      return null;
    },
    _guidanceUnavailable(status, message) { return { status, rules_version: R.RULES_VERSION, message }; },
    _guidanceHasTargets(profile) { return [R.K, R.P, R.NA, 'carbs_per_meal_g'].some((k) => R.targetMax(profile.targets[k]) != null); },
    _guidanceTargets(ctx) {
      const values = {};
      for (const k of TARGET_KEYS_SHOWN) if (ctx.profile.targets[k] != null) values[k] = ctx.profile.targets[k];
      return { values, profile_updated_at: ctx.profile.targets_updated_at };
    },
    _notForMeList() {
      const rows = [];
      for (const [foodId, createdAt] of this._foodPreferences()) {
        const f = this._food(foodId);
        if (f) rows.push({ food_id: foodId, name: f.name, category: f.category, created_at: createdAt });
      }
      rows.sort((a, b) => nocaseCompare(a.name, b.name) || a.food_id - b.food_id);
      return { rules_version: R.RULES_VERSION, foods: rows, limit: MAX_NOT_FOR_ME };
    },
  });

  // ---- routes ----------------------------------------------------------------------------------
  route('GET', '/api/guidance/next-meal', function ({ qp }) {
    this._currentUser();
    const q = new Query(qp);
    q.meal('meal', { required: true }); q.str('date'); q.int('limit', { def: R.DEFAULT_LIMIT, ge: 1, le: R.MAX_LIMIT }); q.bool('explain');
    const a = q.done();
    const day = parseDay(a.date);
    const off = this._guidanceGate();
    if (off) return off;
    const ctx = this._guidanceContext(day);
    if (!this._guidanceHasTargets(ctx.profile)) return this._guidanceUnavailable('no_targets', GE.M.NO_TARGETS);
    const result = GE.whatFits(ctx, a.meal, a.limit, a.explain);
    for (const food of result.foods) withNulls(food, ['explain']);
    result.ai = { available: false, provider_label: null };
    result.targets = this._guidanceTargets(ctx);
    return withNulls(result, ['explain']);
  });

  route('GET', '/api/guidance/swaps', function ({ qp }) {
    this._currentUser();
    const q = new Query(qp);
    q.str('date'); q.meal('meal'); q.int('food_id', { ge: 1, id: true }); q.num('servings', { gt: 0, le: 1000 }); q.num('grams', { gt: 0, le: 100000 });
    q.int('entry_id', { ge: 1, id: true }); q.choice('purpose', ['hypo', 'none']); q.bool('explain');
    const a = q.done();
    if ((a.food_id == null) === (a.entry_id == null)) fail(400, 'give either food_id (with servings or grams) or entry_id');
    const off = this._guidanceGate();
    if (off) return off;
    let day, slot, fid, amount, wanted;
    if (a.entry_id != null) {
      const row = this._entry(a.entry_id);
      if (!row) fail(404, `log entry ${a.entry_id} not found`);
      [day, slot, fid, amount] = [row.date, row.meal, row.food_id, Number(row.servings)];
      wanted = a.purpose || (row.purpose === 'hypo' ? 'hypo' : 'none');
    } else {
      if (a.meal == null) fail(400, 'meal is required with food_id');
      [day, slot, fid, amount, wanted] = [parseDay(a.date), a.meal, a.food_id, 1.0, a.purpose];
    }
    let ctx = this._guidanceContext(day, { history60: false, savedMeals: true, combos: false });
    const food = ctx.foods.get(fid);
    if (food == null) fail(404, `food ${fid} not found`);
    if (a.entry_id == null) {
      if (a.grams != null) {
        const row = this._food(fid); // guidance.api.swaps: grams only when the serving weight describes the values
        if (row && !KH.off.weightKnown(row)) fail(400, KH.off.WEIGHT_UNKNOWN_DETAIL);
        amount = food.serving_g > 0 ? a.grams / food.serving_g : 1.0;
      }
      else if (a.servings != null) amount = a.servings;
      if (wanted == null) wanted = food.hypo ? 'hypo' : 'none';
    }
    if (!this._guidanceHasTargets(ctx.profile)) return this._guidanceUnavailable('no_targets', GE.M.NO_TARGETS);
    if (a.entry_id != null) ctx = R.withDay(ctx, ctx.day.filter((e) => e.id !== a.entry_id));
    const result = GE.findSwaps(ctx, slot, food, amount, wanted, R.SWAP_MAX, a.explain);
    if (a.entry_id != null) result.entry_id = a.entry_id;
    return withNulls(result, ['reason', 'card', 'entry_id', 'explain']);
  });

  route('GET', '/api/guidance/hypo-options', function () {
    this._currentUser();
    return GE.hypoOptions(this._guidanceContext(todayStr(), { history: false, history60: false, savedMeals: false, combos: false }));
  });

  route('POST', '/api/guidance/plan-day', function ({ body }) {
    this._currentUser();
    const c = new Check(body);
    if (!c.has('date')) c.err('date', 'Field required');
    else if (typeof body.date !== 'string') c.err('date', 'Input should be a valid string');
    else { const e = validDate(body.date); if (e) c.err('date', e); else c.out.date = body.date; }
    if (c.has('meals') && body.meals != null) {
      const raw = body.meals;
      if (!Array.isArray(raw)) c.err('meals', 'Input should be a valid list');
      else {
        const n = c.errors.length;
        raw.forEach((x, i) => { if (!MEAL_KEYS.includes(x)) c.err(`meals.${i}`, MEAL_CHOICE); });
        if (c.errors.length === n) {
          if (raw.length < 1) c.err('meals', 'List should have at least 1 item after validation, not 0');
          else if (raw.length > 4) c.err('meals', `List should have at most 4 items after validation, not ${raw.length}`);
          else if (new Set(raw).size !== raw.length) c.err('meals', 'each meal may be listed once');
          else c.out.meals = [...raw];
        }
      }
    } else c.out.meals = null;
    for (const name of ['use_saved_meals', 'use_usual', 'use_starters']) {
      if (!c.has(name)) { c.out[name] = true; continue; }
      const r = KH.settings.validate({ type: 'bool' }, body[name]);
      if (r.error) c.err(name, r.error); else c.out[name] = r.value;
    }
    c.num('variant', { def: 0, ge: 0, le: 4, int: true, nullable: false });
    if (c.has('explain')) { const r = KH.settings.validate({ type: 'bool' }, body.explain); if (r.error) c.err('explain', r.error); else c.out.explain = r.value; }
    else c.out.explain = false;
    const known = ['date', 'meals', 'use_saved_meals', 'use_usual', 'use_starters', 'variant', 'explain'];
    for (const k of Object.keys(c.body)) if (!known.includes(k)) c.err(k, 'Extra inputs are not permitted');
    const b = c.done();
    const off = this._guidanceGate('plan');
    if (off) return off;
    const ctx = this._guidanceContext(b.date);
    if (!this._guidanceHasTargets(ctx.profile)) return this._guidanceUnavailable('no_targets', GE.M.NO_TARGETS);
    const counter = { foods: 0, meals: 0 };
    const result = GE.planDay(ctx, b.meals, { useSavedMeals: b.use_saved_meals, useUsual: b.use_usual, useStarters: b.use_starters,
      variant: b.variant, counter });
    result.targets = this._guidanceTargets(ctx);
    if (b.explain) {
      result.explain = { evaluations: counter.foods, meal_evaluations: counter.meals, pool_per_role: ctx.tunables.pool_per_role,
        beam_width: ctx.tunables.beam_width };
    }
    return planModel(result);
  });

  route('GET', '/api/guidance/insights/day', function ({ qp }) {
    this._currentUser();
    const day = parseDay(qp('date'));
    const off = this._guidanceGate('insights');
    if (off) return off;
    const ctx = this._guidanceContext(day, { history60: false, savedMeals: false, combos: false });
    if (!this._guidanceHasTargets(ctx.profile)) return this._guidanceUnavailable('no_targets', GE.M.NO_TARGETS);
    return GE.dayInsights(ctx);
  });

  route('GET', '/api/guidance/insights/period', function ({ qp }) {
    this._currentUser();
    const start = qp('start') ? parseDay(qp('start'), 'start') : null;
    const end = qp('end') ? parseDay(qp('end'), 'end') : null;
    const [s, e, prevS, prevE] = GE.periodBounds(start, end, todayStr());
    if (e < s) fail(400, 'end must not be before start');
    if (R.daysBetween(s, e) + 1 > R.PERIOD_MAX_DAYS) fail(400, `range too large (max ${R.PERIOD_MAX_DAYS} days)`);
    const off = this._guidanceGate('insights');
    if (off) return off;
    const profile = this._guidanceProfile();
    if (!this._guidanceHasTargets(profile)) return this._guidanceUnavailable('no_targets', GE.M.NO_TARGETS);
    const ctx = GE.makeContext({ date: todayStr(), profile, prefs: this._guidancePrefs(), foods: new Map() });
    const foods = this._guidanceFoods();
    const result = GE.periodInsights(ctx.profile, ctx.prefs, s, e, this._guidanceHistory(foods, s, e), this._guidanceHistory(foods, prevS, prevE));
    result.previous = { start: prevS, end: prevE };
    return result;
  });

  route('GET', '/api/guidance/rules', function () {
    this._currentUser();
    return { rules_version: R.RULES_VERSION, rules_hash: R.RULES_HASH, rules: R.rulesTable(), notes: R.ruleNotes(), topic_pages: GE.T.TOPIC_PAGES,
      tips: GE.T.ALL_TIPS.map((t) => ({ code: t.code, handbook: t.slug, text: t.text })) };
  });

  route('GET', '/api/guidance/not-for-me', function () { this._currentUser(); return this._notForMeList(); });
  // PUT / DELETE /api/guidance/not-for-me/{food_id}: a path int (any sign); not yours or unknown → 404.
  route('*', /^\/api\/guidance\/not-for-me\/([^/]+)$/, function ({ method, id }) {
    this._currentUser();
    if (method !== 'PUT' && method !== 'DELETE') fail(405, 'Method Not Allowed');
    const raw = decodeURIComponent(id);
    if (pydanticInt(raw) === undefined) failFields(['food_id: Input should be a valid integer, unable to parse string as an integer']);
    const big = bigOf(raw);
    const foodId = big <= MAX_ID && big >= -MAX_ID ? Number(big) : NaN;
    const prefs = this._foodPreferences();
    if (method === 'PUT') {
      if (!Number.isSafeInteger(foodId) || !this._food(foodId)) fail(404, `food ${big} not found`);
      if (!prefs.has(foodId)) {
        if (prefs.size >= MAX_NOT_FOR_ME) fail(409, `the "Not for me" list is full (${MAX_NOT_FOR_ME} foods); remove one first`);
        prefs.set(foodId, this._stamp());
      }
      return this._notForMeList();
    }
    if (!Number.isSafeInteger(foodId) || !prefs.has(foodId)) fail(404, `food ${big} is not on your list`);
    prefs.delete(foodId);
    return null;
  });

  Object.assign(M, { GUIDANCE_COMBOS: COMBOS });
})();
