/* Kidney Diet Log — demo API: saved meals and the shopping list (twin of app/meals.py).

   v0.3 (ARCHITECTURE.md "Log changes"): a saved meal has `meal_hint`, the slot it is for (a meal or
   null). POST accepts it, PUT keeps the stored one when the field is left out (a v0.2 client) and
   clears it on null, POST /from-log sets it to the source meal and leaves low-treatment entries out. */
(() => {
  'use strict';
  const KH = window.KH;
  const { MEAL_KEYS, pyRound, sqliteSum, roundNutrients, evaluateWarnings, ratingFromWarnings, emptyTotals, addTotals, scaleNutrients } = KH.rules;
  const M = KH.mock;
  const { route, MockApi, Check, fail, nocaseCompare } = M;

  Object.assign(MockApi.prototype, {
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
      return { id: t.id, name: t.name, note: t.note, meal_hint: t.meal_hint || null, items, totals: roundNutrients(totals), kidney_rating: worst, created_at: t.created_at, updated_at: t.updated_at };
    },
    _templateBody(body) {
      const c = new Check(body);
      c.str('name', { required: true, min: 1, max: 200, nullable: false });
      c.str('note', { max: 1000, def: null, emptyToNull: true });
      c.models('items', (ic) => {
        ic.num('food_id', { required: true, ge: 1, int: true, nullable: false, maxId: true });
        ic.num('servings', { required: true, gt: 0, le: 1000, nullable: false });
      }, { minLength: 1 });
      c.choice('meal_hint', MEAL_KEYS, { nullable: true });
      return c.done();
    },
    _insertTemplate({ name, note, items, mealHint = null, createdAt = null }) {
      const now = createdAt || this._stamp();
      const t = { id: this._nextTemplateId++, name, note: note == null ? null : note, meal_hint: mealHint || null, items: items.map((it) => ({ food_id: Number(it.food_id), servings: Number(it.servings) })),
        created_at: now, updated_at: now };
      this._templates.push(t);
      return t;
    },
    _template(id) { const t = this._templates.find((x) => x.id === Number(id)); if (!t) fail(404, `saved meal ${id} not found`); return t; },
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
    },
  });

  // ---- routes ----
  route('GET', '/api/meals', function () {
    return { meals: [...this._templates].sort((a, b) => nocaseCompare(a.name, b.name) || a.id - b.id).map((t) => this._templateView(t)) };
  });
  route('POST', '/api/meals', function ({ body }) {
    const b = this._templateBody(body);
    for (const it of b.items) this._foodOr404(it.food_id);
    return this._templateView(this._insertTemplate({ ...b, mealHint: b.meal_hint }));
  });
  route('POST', '/api/meals/from-log', function ({ body }) {
    const c = new Check(body);
    c.date('date'); c.choice('meal', MEAL_KEYS, { required: true });
    c.str('name', { required: true, min: 1, max: 200, nullable: false });
    c.str('note', { max: 1000, def: null, emptyToNull: true });
    const b = c.done();
    // Entries that treated a low (purpose "hypo") are not part of the meal.
    const rows = this._fetchEntries({ start: b.date, end: b.date, meal: b.meal }).filter((r) => r.purpose !== 'hypo');
    if (!rows.length) fail(400, `nothing logged for ${b.meal} on ${b.date}`);
    return this._templateView(this._insertTemplate({ name: b.name, note: b.note, mealHint: b.meal,
      items: rows.map((r) => ({ food_id: r.food_id, servings: r.servings })) }));
  });
  route('POST', '/api/meals/{id}/apply', function ({ id, body }) {
    const c = new Check(body);
    c.date('date'); c.choice('meal', MEAL_KEYS, { required: true });
    c.choice('status', ['eaten', 'planned'], { def: 'planned' });
    c.num('scale', { def: 1, gt: 0, le: 100, nullable: false });
    const b = c.done();
    const t = this._template(id);
    if (!t.items.length) fail(400, 'this saved meal has no items');
    const created = [];
    for (const it of t.items) {
      const food = this._food(it.food_id);
      if (!food) fail(404, `food ${it.food_id} used by this saved meal no longer exists; edit the meal first`);
      created.push(this._insertEntry({ date: b.date, meal: b.meal, food, servings: it.servings * b.scale, grams: null, note: null, status: b.status }));
    }
    return { entries: created.map((r) => this._entryView(r)) };
  });
  route('*', '/api/meals/{id}', function ({ method, id, body }) {
    const b = method === 'PUT' ? this._templateBody(body) : null;
    const t = this._template(id);
    if (method === 'GET') return this._templateView(t);
    if (method === 'PUT') {
      for (const it of b.items) this._foodOr404(it.food_id);
      // A body without meal_hint (a v0.2 screen) keeps the stored one; null clears it.
      const mealHint = 'meal_hint' in b ? b.meal_hint : t.meal_hint || null;
      Object.assign(t, { name: b.name, note: b.note, meal_hint: mealHint, items: b.items.map((it) => ({ food_id: Number(it.food_id), servings: Number(it.servings) })), updated_at: this._stamp() });
      return this._templateView(t);
    }
    if (method === 'DELETE') { this._templates.splice(this._templates.indexOf(t), 1); return null; }
    return fail(404, 'Not Found');
  });
  route('GET', '/api/plan/shopping', function ({ qp }) { return this._shopping(qp('start'), qp('end')); });
})();
