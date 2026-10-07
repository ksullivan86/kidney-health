/* Kidney Diet Log — demo API: the food log, day / range / period summaries and CSV export
   (twins of app/log.py and app/periods.py).

   v0.3 (ARCHITECTURE.md "M2 API: guidance", "Log changes"): every entry carries `purpose` ("hypo" = it
   treated a low, else null) and `client_id` (the offline outbox's UUID, lower-case, unique per person);
   a repeated client_id answers with the entry already created; POST /api/log/batch adds 1–40 entries all
   or nothing. A hypo_treatment food defaults to purpose "hypo" unless the request says "none". Quick add takes
   gtin and ingredients_text (barcodes): the new custom food keeps the barcode and gets the additive scan. */
(() => {
  'use strict';
  const KH = window.KH;
  const { NUT, NUTRIENT_KEYS, MEAL_KEYS, ASSESSMENT, pyRound, pyRepr, pyFsum, sqliteSum, roundValue, roundNutrients, isIntUnit,
    evaluateWarnings, ratingFromWarnings, emptyTotals, addTotals, scaleNutrients, statusLevel, dailyStatus, buildAlerts, mealCarbAlerts,
    summaryTarget } = KH.rules;
  const { todayStr, addDays, daysBetween, weekdayMon } = KH.util;
  const M = KH.mock;
  const { route, MockApi, Check, fail, failFields, MEAL_RANK, MAX_INTERDIALYTIC_DAYS } = M;

  const INTERDIALYTIC_KEYS = ['potassium_mg', 'sodium_mg', 'fluid_ml'];
  const NOTE_DAILY = 'Potassium, sodium and fluid are judged day by day: a day well over the limit is a risk on its own, '
    + 'and a low day does not bank against a high one.';
  const NOTE_WEEKLY = 'Phosphorus and protein are judged on the weekly average: blood phosphate and nutritional status '
    + 'reflect weeks of intake, so an average above target matters more than one high day.';
  const NOTE_CARBS = 'Carbohydrate is counted per meal and per day for insulin; its weekly average is informational.';
  const NOTE_INTERDIALYTIC = 'Between hemodialysis sessions potassium, sodium and fluid accumulate until the next session; '
    + "the 'since last dialysis' totals cover the current interval (the long weekend gap is the one to watch).";
  const NOTE_NO_DIALYSIS_DAYS = 'Set your dialysis days in the profile to see potassium, sodium and fluid totals since your last session.';
  const NOTE_CAPPED = `No dialysis day fell within the last ${MAX_INTERDIALYTIC_DAYS} days, so the interval is capped at ${MAX_INTERDIALYTIC_DAYS} days.`;
  // log.CSV_COLUMNS: v0.3 adds purpose (guidance) and the food's source and licence (barcodes, ODbL notice).
  const CSV_COLUMNS = ['id', 'date', 'meal', 'status', 'food_id', 'food_name', 'servings', 'grams', 'note', ...NUTRIENT_KEYS, 'created_at', 'updated_at',
    'purpose', 'source', 'source_license'];
  const HYPO_PURPOSE = 'hypo';
  const MAX_LOG_BATCH = 40;
  const CLIENT_ID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
  // log.resolve_purpose: "hypo" / "none" as asked; left out, "hypo" for a hypo_treatment food.
  function resolvePurpose(food, requested) {
    if (requested === HYPO_PURPOSE) return HYPO_PURPOSE;
    if (requested === 'none') return null;
    return (food.flags || []).includes('hypo_treatment') ? HYPO_PURPOSE : null;
  }
  // models.validate_client_id (a field validator on `str | None`).
  function checkClientId(c) {
    if (!c.has('client_id')) { c.out.client_id = null; return; }
    const v = c.body.client_id;
    if (v == null) { c.out.client_id = null; return; }
    if (typeof v !== 'string') { c.err('client_id', 'Input should be a valid string'); return; }
    const t = v.trim();
    if (!CLIENT_ID_RE.test(t)) { c.err('client_id', 'must be a UUID such as 0f8fad5b-d9cb-469f-a165-70867728950e'); return; }
    c.out.client_id = t.toLowerCase();
  }

  function csvCell(v) {
    if (v == null) return '';
    const s = String(v);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  Object.assign(MockApi.prototype, {
    _insertEntry({ date, meal, food, servings, grams = null, note = null, status = 'eaten', createdAt = null, purpose = null, clientId = null }) {
      const now = createdAt || this._stamp();
      const row = { id: this._nextEntryId++, date, meal, food_id: food.id, food_name: food.name, servings: Number(servings),
        grams: grams == null ? null : Number(grams), note: note == null ? null : note, status,
        nutrients: scaleNutrients(food.nutrients, Number(servings)), purpose: purpose === HYPO_PURPOSE ? HYPO_PURPOSE : null,
        client_id: clientId || null, created_at: now, updated_at: now };
      this._entries.push(row);
      return row;
    },
    _entry(id) { return this._entries.find((e) => e.id === Number(id)) || null; },
    _entryByClientId(clientId) { return clientId ? this._entries.find((e) => e.client_id === clientId) || null : null; },
    _entryView(row) {
      const food = this._food(row.food_id) || { flags: [], kidney_notes: null };
      const warnings = evaluateWarnings(row.nutrients, food.flags, food.kidney_notes, 'in this entry');
      return { id: row.id, date: row.date, meal: row.meal, food_id: row.food_id, food_name: row.food_name, servings: pyRound(row.servings, 3),
        grams: row.grams == null ? null : pyRound(row.grams, 1), note: row.note, status: row.status, nutrients: roundNutrients(row.nutrients),
        warnings, kidney_rating: ratingFromWarnings(warnings), purpose: row.purpose || null, client_id: row.client_id || null,
        created_at: row.created_at, updated_at: row.updated_at };
    },
    // fetch_entries: ORDER BY date, meal, status (eaten first), created_at, id
    _fetchEntries({ start = null, end = null, status = null, meal = null } = {}) {
      return this._entries.filter((e) => (!start || e.date >= start) && (!end || e.date <= end) && (!status || e.status === status) && (!meal || e.meal === meal))
        .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)
          || (MEAL_RANK[a.meal] ?? 3) - (MEAL_RANK[b.meal] ?? 3)
          || (a.status === 'eaten' ? 0 : 1) - (b.status === 'eaten' ? 0 : 1)
          || (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0)
          || a.id - b.id);
    },
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
    },
    _day(date) {
      const rows = this._fetchEntries({ start: date, end: date });
      const f = this._dayFigures(rows);
      return { date, entries: rows.map((r) => this._entryView(r)), totals: f.totals, planned_totals: f.planned_totals, projected_totals: f.projected_totals,
        targets: this._profileView().targets, status: f.status, projected_status: f.projected_status, meals: f.meals, planned_meals: f.planned_meals,
        alerts: f.alerts, projected_alerts: f.projected_alerts, counts: f.counts };
    },
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
    },
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
    },
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
    },
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
    },
    _csv(start, end) {
      const s = start ? this._dateParam(start, 'start') : null;
      const e = end ? this._dateParam(end, 'end') : null;
      if (s && e && e < s) fail(400, 'end must not be before start');
      const lines = [CSV_COLUMNS.join(',')];
      for (const row of this._fetchEntries({ start: s, end: e })) {
        const values = [row.id, row.date, row.meal, row.status, row.food_id, row.food_name, pyRepr(pyRound(row.servings, 3)),
          row.grams == null ? null : pyRepr(pyRound(row.grams, 1)), row.note,
          ...NUTRIENT_KEYS.map((k) => { const v = roundValue(k, row.nutrients[k]); return v == null ? null : isIntUnit(k) ? String(v) : pyRepr(v); }),
          row.created_at, row.updated_at, row.purpose || null];
        const food = this._food(row.food_id) || {};
        values.push(food.source || null, food.source_license || null);
        lines.push(values.map(csvCell).join(','));
      }
      return `${lines.join('\r\n')}\r\n`;
    },
    _logBody(body, { update = false } = {}) {
      const c = new Check(body);
      if (update) { c.date('date', { required: false }); c.choice('meal', MEAL_KEYS, { nullable: true }); }
      else { c.date('date'); c.choice('meal', MEAL_KEYS, { required: true }); c.num('food_id', { required: true, ge: 1, int: true, nullable: false, maxId: true }); }
      c.num('servings', { gt: 0, le: 1000 });
      c.num('grams', { gt: 0, le: 100000 });
      c.str('note', { max: 500 });
      if (update) c.choice('status', ['eaten', 'planned'], { nullable: true }); else c.choice('status', ['eaten', 'planned'], { def: 'eaten' });
      c.choice('purpose', ['hypo', 'none'], { nullable: true });
      if (!update) checkClientId(c);
      return c.done();
    },
    // POST /api/log body after validation: the entry it creates (or the one its client_id already made).
    _createLogged(b, where = '') {
      const existing = this._entryByClientId(b.client_id);
      if (existing) return [existing, 'existing'];
      const food = this._food(b.food_id);
      if (!food || !this._foodVisible(food)) fail(404, `${where}food ${b.food_id} not found`);
      const [servings, grams] = b.grams != null ? [b.grams / food.serving_g, b.grams] : [b.servings != null ? b.servings : 1, null];
      return [this._insertEntry({ date: b.date, meal: b.meal, food, servings, grams, note: b.note ?? null, status: b.status,
        purpose: resolvePurpose(food, b.purpose), clientId: b.client_id }), 'created'];
    },
  });

  // ---- routes ----
  route('GET', '/api/log', function ({ qp }) {
    const date = qp('date');
    return this._day(date ? this._dateParam(date, 'date') : todayStr());
  });
  route('POST', '/api/log', function ({ body }) {
    const b = this._logBody(body);
    return this._entryView(this._createLogged(b)[0]);
  });
  // log.create_batch: each item validated as POST /api/log ("entries.<i>.<field>: …"), then all or nothing.
  route('POST', '/api/log/batch', function ({ body }) {
    const c = new Check(body);
    const items = [];
    if (!c.has('entries')) c.err('entries', 'Field required');
    else if (!Array.isArray(body.entries)) c.err('entries', 'Input should be a valid list');
    else {
      body.entries.forEach((it, i) => {
        if (!M.isDict(it)) { c.err(`entries.${i}`, 'Input should be a valid dictionary or object to extract fields from'); return; }
        try { items.push(this._logBody(it)); } catch (e) {
          if (!(e instanceof M.ApiError) || e.status !== 400) throw e;
          for (const part of String(e.detail).split('; ')) c.errors.push(`entries.${i}.${part}`); // "entries.0.date: Field required"
        }
      });
      const n = body.entries.length;
      if (c.errors.length === 0 && n < 1) c.err('entries', 'List should have at least 1 item after validation, not 0');
      if (c.errors.length === 0 && n > MAX_LOG_BATCH) c.err('entries', `List should have at most ${MAX_LOG_BATCH} items after validation, not ${n}`);
    }
    for (const k of Object.keys(c.body)) if (k !== 'entries') c.err(k, 'Extra inputs are not permitted');
    c.done();
    const seen = new Map();
    items.forEach((it, index) => {
      if (it.client_id == null) return;
      if (seen.has(it.client_id)) failFields([`entries[${index}].client_id repeats entries[${seen.get(it.client_id)}].client_id`]); // a model validator: no field prefix
      seen.set(it.client_id, index);
    });
    // One transaction: check every food first, so a failing item leaves nothing behind.
    items.forEach((it, index) => {
      const food = this._food(it.food_id);
      if (!this._entryByClientId(it.client_id) && !(food && this._foodVisible(food))) fail(404, `entries[${index}]: food ${it.food_id} not found`);
    });
    const results = items.map((it) => this._createLogged(it));
    return { entries: results.map(([row]) => this._entryView(row)),
      results: results.map(([row, state], index) => ({ index, id: row.id, result: state })) };
  });
  route('GET', '/api/log/range', function ({ qp }) { return this._range(qp('start'), qp('end')); });
  route('GET', '/api/log/summary', function ({ qp }) { return this._summary(qp('start'), qp('end')); });
  route('GET', '/api/log/export.csv', function ({ qp }) { return this._csv(qp('start'), qp('end')); });
  route('POST', '/api/log/quick', function ({ body }) {
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
    c.choice('purpose', ['hypo', 'none'], { nullable: true });
    checkClientId(c);
    M.checkGtin(c); // v0.3 barcodes: the food is found by this barcode next time
    c.str('ingredients_text', { max: KH.additives.MAX_INGREDIENTS_CHARS, def: null }); // v0.3: the additive scan reads it
    const b = c.done();
    const existing = this._entryByClientId(b.client_id);
    if (existing) return this._entryView(existing); // a repeat creates no second food
    const scanned = this._scanCustomFood(b.name, b.flags, null, b.ingredients_text);
    const food = this._food(this._insertFood({ source: 'custom', name: b.name, serving_desc: b.serving_desc, serving_g: b.serving_g, nutrients: b.nutrients,
      ...scanned, gtin: b.gtin || null }));
    return this._entryView(this._insertEntry({ date: b.date, meal: b.meal, food, servings: b.servings, grams: null, note: b.note, status: b.status,
      purpose: resolvePurpose(food, b.purpose), clientId: b.client_id }));
  });
  route('POST', '/api/log/mark-eaten', function ({ body }) {
    const c = new Check(body);
    c.date('date'); c.choice('meal', MEAL_KEYS, { nullable: true });
    const b = c.done();
    const now = this._stamp();
    let n = 0;
    for (const e of this._entries) {
      if (e.date === b.date && e.status === 'planned' && (!b.meal || e.meal === b.meal)) { e.status = 'eaten'; e.updated_at = now; n += 1; }
    }
    return { updated: n };
  });
  route('POST', '/api/log/copy-day', function ({ body }) {
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
      created.push(this._insertEntry({ date: b.to_date, meal: row.meal, food, servings, grams, note: row.note, status: b.status, purpose: row.purpose }));
    }
    const entries = created.map((r) => this._entryView(r));
    return { created: entries.length, entries };
  });
  route('*', '/api/log/{id}', function ({ method, id, body }) {
    const data = method === 'PUT' ? this._logBody(body, { update: true }) : null;
    const row = this._entry(id);
    if (!row) fail(404, `log entry ${id} not found`);
    if (method === 'DELETE') { this._entries.splice(this._entries.indexOf(row), 1); return null; }
    if (method === 'PUT') {
      const food = this._food(row.food_id);
      if (!food) fail(404, "the entry's food no longer exists");
      const date = data.date || row.date;
      const meal = data.meal || row.meal;
      const status = data.status || row.status;
      const note = 'note' in data ? data.note : row.note;
      const purpose = data.purpose == null ? row.purpose || null : data.purpose === HYPO_PURPOSE ? HYPO_PURPOSE : null;
      let servings = row.servings, grams = row.grams;
      if (data.grams != null) [servings, grams] = [data.grams / food.serving_g, data.grams];
      else if (data.servings != null) [servings, grams] = [data.servings, null];
      else if ('grams' in data) grams = null;
      else if (grams != null) servings = grams / food.serving_g; // weight-based entry follows the food's serving size
      Object.assign(row, { date, meal, status, food_name: food.name, servings, grams, note, purpose, nutrients: scaleNutrients(food.nutrients, servings), updated_at: this._stamp() });
      return this._entryView(row);
    }
    return fail(404, 'Not Found');
  });

  // The day figures (totals, status, alerts, projections) for any entry rows and targets: js/offline.js draws a
  // day with the entries still waiting to sync with the same twin of app/log.py the demo uses.
  function dayFigures(profile, rows) { return MockApi.prototype._dayFigures.call({ _profile: profile }, rows); }

  Object.assign(M, { csvCell, CSV_COLUMNS, resolvePurpose, dayFigures });
})();
