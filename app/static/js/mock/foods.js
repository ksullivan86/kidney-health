/* Kidney Diet Log — demo API: foods (twin of app/foods.py) and /healthz. */
(() => {
  'use strict';
  const KH = window.KH;
  const { NUTRIENT_KEYS, pyRound, pyG, roundNutrients, evaluateWarnings, ratingFromWarnings } = KH.rules;
  const M = KH.mock;
  const { route, MockApi, Check, fail, failFields, pydanticInt, asciiLower, nocaseCompare, FOOD_CATEGORIES, MAX_SEARCH_QUERY_CHARS, MAX_SEARCH_WORDS } = M;

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
  // foods.search_rank
  function searchRank(name, brand, query, words) {
    const n = name.toLowerCase();
    if (n.startsWith(query)) return 0;
    if (words.length && n.split(/[^a-z0-9]+/).some((tok) => tok && tok.startsWith(words[0]))) return 1;
    if (brand && brand.toLowerCase().startsWith(query)) return 2;
    return 3;
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
    return { version: 'mock-fallback', source: 'hand-typed sample (js/mock/foods.js)', foods: foods.map((f, i) => ({ fdc_id: 100001 + i, ...f })) };
  }

  Object.assign(MockApi.prototype, {
    _importBuiltin(data) {
      if (!data || typeof data !== 'object' || !Array.isArray(data.foods)) return;
      const byFdc = new Map(), byName = new Map();
      // The curated guidance role of a builtin food (coleslaw is a vegetable side), by fdc_id: what
      // app/guidance/context.py role_overrides() reads from data/foods.json (js/mock/guidance.js uses it).
      this._builtinRoles = new Map();
      for (const item of data.foods) {
        if (item && item.fdc_id != null && typeof item.role === 'string') this._builtinRoles.set(Math.trunc(Number(item.fdc_id)), item.role);
      }
      for (const item of data.foods) {
        let parsed;
        try { parsed = parseBuiltinItem(item); } catch (e) { continue; }
        const existing = parsed.fdc_id != null ? byFdc.get(parsed.fdc_id) : byName.get(parsed.name.toLowerCase());
        if (existing != null) { this._updateFood(existing, { ...parsed, hidden: false }); continue; }
        const id = this._insertFood({ source: 'builtin', ...parsed });
        if (parsed.fdc_id != null) byFdc.set(parsed.fdc_id, id); else byName.set(parsed.name.toLowerCase(), id);
      }
      this.foodsVersion = data.version ? String(data.version) : null;
    },
    _normaliseFluid(nutrients, flags, servingG) {
      const out = Object.fromEntries(NUTRIENT_KEYS.map((k) => [k, nutrients[k] == null ? null : Number(nutrients[k])]));
      if (flags.includes('counts_as_fluid')) { if (out.fluid_ml == null) out.fluid_ml = Number(servingG); }
      else out.fluid_ml = 0;
      return out;
    },
    // foods.stored_food_values: a food row keeps what the API shows (serving_g to 1 decimal,
    // mg/mL whole, the rest to 1 decimal), so scaling the shown values gives the entry's numbers.
    _storedFoodValues(nutrients, flags, servingG) {
      const serving = pyRound(Number(servingG), 1);
      return [serving, roundNutrients(this._normaliseFluid(nutrients, flags, serving))];
    },
    _insertFood({ name, serving_desc, serving_g, nutrients, source = 'custom', brand = null, category = null, fdc_id = null, flags = [], kidney_notes = null, hidden = false }) {
      const now = this._stamp();
      const [servingG, values] = this._storedFoodValues(nutrients, flags, serving_g);
      const row = { id: this._nextFoodId++, name, brand, category, source, fdc_id, serving_desc, serving_g: servingG,
        nutrients: values, flags: [...flags], kidney_notes, hidden: !!hidden, created_at: now, updated_at: now };
      this._foods.push(row);
      this._foodById.set(row.id, row);
      return row.id;
    },
    _updateFood(id, { name, serving_desc, serving_g, nutrients, brand = null, category = null, flags = [], kidney_notes = null, hidden = null, fdc_id }) {
      const row = this._foodById.get(id);
      const [servingG, values] = this._storedFoodValues(nutrients, flags, serving_g);
      Object.assign(row, { name, brand, category, serving_desc, serving_g: servingG, nutrients: values,
        flags: [...flags], kidney_notes, updated_at: this._stamp() });
      if (hidden != null) row.hidden = !!hidden;
      if (fdc_id !== undefined) row.fdc_id = fdc_id;
    },
    _food(id) { return this._foodById.get(Number(id)) || null; },
    _foodOr404(id) { const f = this._food(id); if (!f) fail(404, `food ${id} not found`); return f; },
    _foodView(row) {
      const warnings = evaluateWarnings(row.nutrients, row.flags, row.kidney_notes, 'per serving');
      return { id: row.id, name: row.name, brand: row.brand, category: row.category, source: row.source, fdc_id: row.fdc_id,
        serving_desc: row.serving_desc, serving_g: pyRound(row.serving_g, 1), nutrients: roundNutrients(row.nutrients), flags: [...row.flags],
        kidney_notes: row.kidney_notes, hidden: row.hidden, warnings, kidney_rating: ratingFromWarnings(warnings) };
    },
    _foodReferenced(id) {
      return this._entries.some((e) => e.food_id === id) || this._templates.some((t) => t.items.some((it) => it.food_id === id));
    },
    _searchFoods(q, category, source, limit) {
      const query = String(q || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
      const words = query ? query.split(' ').slice(0, MAX_SEARCH_WORDS) : [];
      const last = new Map(); // food_id -> MAX(created_at) of its log entries
      for (const e of this._entries) { const l = last.get(e.food_id); if (l == null || e.created_at > l) last.set(e.food_id, e.created_at); }
      const rows = this._foods.filter((f) => !f.hidden && (!category || f.category === category) && (!source || f.source === source)
        && words.every((w) => asciiLower(f.name).includes(w) || asciiLower(f.brand || '').includes(w)));
      rows.sort((a, b) => {
        const la = last.get(a.id), lb = last.get(b.id);
        if ((la == null) !== (lb == null)) return la == null ? 1 : -1;
        if (la != null && la !== lb) return la > lb ? -1 : 1;
        return nocaseCompare(a.name, b.name) || a.id - b.id;
      });
      if (words.length) rows.sort((a, b) => searchRank(a.name, a.brand, query, words) - searchRank(b.name, b.brand, query, words));
      return rows.slice(0, limit).map((f) => this._foodView(f));
    },
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
    },
  });

  // ---- routes ----
  // v0.3: the public health check counts only the shared builtin foods (nobody's own data).
  route('*', '/healthz', function () { return { status: 'ok', foods: this._foods.filter((f) => !f.hidden && f.source === 'builtin').length }; });
  route('GET', '/api/foods', function ({ qp }) {
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
  });
  route('POST', '/api/foods', function ({ body }) {
    const b = this._foodBody(body);
    return this._foodView(this._food(this._insertFood({ ...b, source: 'custom' })));
  });
  route('GET', '/api/foods/categories', function () {
    const extras = [...new Set(this._foods.filter((f) => !f.hidden && f.category).map((f) => f.category))].filter((c) => !FOOD_CATEGORIES.includes(c)).sort();
    return { categories: [...FOOD_CATEGORIES, ...extras] };
  });
  // USDA lookups need the server's key: the demo validates like the server, then answers 503.
  route('GET', '/api/foods/usda/search', function ({ qp }) {
    if ((qp('q') || '').length > 200) failFields(['q: String should have at most 200 characters']);
    fail(503, 'USDA_API_KEY not configured');
  });
  route('POST', '/api/foods/usda/import', function ({ body }) {
    const c = new Check(body); // UsdaImport
    c.num('fdc_id', { required: true, gt: 0, int: true, nullable: false, maxId: true });
    c.done();
    fail(503, 'USDA_API_KEY not configured');
  });
  route('POST', '/api/foods/{id}/copy', function ({ id }) {
    const row = this._foodOr404(id);
    return this._foodView(this._food(this._insertFood({ source: 'custom', fdc_id: row.fdc_id, name: row.name, brand: row.brand, category: row.category,
      serving_desc: row.serving_desc, serving_g: row.serving_g, nutrients: { ...row.nutrients }, flags: row.flags, kidney_notes: row.kidney_notes })));
  });
  route('*', '/api/foods/{id}', function ({ method, id, body }) {
    const b = method === 'PUT' ? this._foodBody(body) : null; // the body is validated before the lookup
    const row = this._foodOr404(id);
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
    return fail(404, 'Not Found');
  });

  Object.assign(M, { parseBuiltinItem, searchRank, fallbackFoods });
})();
