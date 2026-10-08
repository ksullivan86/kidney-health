/* Kidney Diet Log — demo API core: an in-page copy of the FastAPI server (app/foods.py, log.py,
   meals.py, profile.py, nutrients.py, periods.py) over in-memory tables. Same routes, same
   numbers, same texts; nothing is persisted. On only with ?mock=1 or in the preview build.

   This file holds the request validation (the server's pydantic models, flattened like
   main.py does), the MockApi class with its request/handle entry points, and the route table:
       KH.mock.route(method, pattern, handler)
   `pattern` is an exact path, a path with `{id}` placeholders (digits), or a RegExp;
   `handler(req)` runs with `this` = the MockApi and req = { method, path, id, ids, query, qp, body }.
   Feature files (js/mock/foods.js, profile.js, log.js, meals.js, auth.js, settings.js) add their table methods to
   MockApi.prototype and register their routes; js/mock/seed.js seeds the demo person and
   KH.mock.start() (called by main.js in demo mode) builds the instance.

   Parity: every route here is checked against the real server by the parity harness and the
   shared vectors in tests/data/*.json (see ARCHITECTURE.md, "Frontend modules"). */
(() => {
  'use strict';
  const KH = window.KH;
  const { NUTRIENT_KEYS, TARGET_KEYS, MEAL_KEYS } = KH.rules;

  // ---------------------------------------------------------------------------
  // Constants shared by the feature twins
  // ---------------------------------------------------------------------------
  const MEAL_RANK = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 };
  const FOOD_CATEGORIES = ['Fruits', 'Vegetables', 'Grains & Breads', 'Dairy & Alternatives', 'Meat, Poultry & Eggs', 'Fish & Seafood',
    'Legumes, Nuts & Seeds', 'Beverages', 'Sweets & Snacks', 'Condiments & Sauces', 'Prepared & Fast Food', 'Diabetes supplies'];
  const MAX_SEARCH_QUERY_CHARS = 200;
  const MAX_SEARCH_WORDS = 10;
  const MAX_RANGE_DAYS = 366;
  const MAX_INTERDIALYTIC_DAYS = 7;

  // `extra`: the keys the server adds next to `detail` (reauth_required, retry_after, field, ...).
  class ApiError extends Error {
    constructor(status, detail, extra = null) { super(detail); this.status = status; this.detail = detail; this.extra = extra; }
  }
  function fail(status, detail, extra = null) { throw new ApiError(status, detail, extra); }
  function failFields(errors) { fail(400, errors.join('; ') || 'invalid request'); }

  // ---------------------------------------------------------------------------
  // Request validation (the server's pydantic models, flattened like main.py does)
  // Pydantic collects every field's errors in the model's field order before failing, and main.py
  // joins them with "; ". Literal fields compare the raw value (str_strip_whitespace only applies
  // to str fields), and number fields run in lax mode: true/false count as 1/0 and strings parse.
  // ---------------------------------------------------------------------------
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
  // SQLite LOWER() / COLLATE NOCASE fold ASCII letters only.
  function asciiLower(s) { return String(s).replace(/[A-Z]+/g, (m) => m.toLowerCase()); }
  function nocaseCompare(a, b) { const x = asciiLower(a), y = asciiLower(b); return x < y ? -1 : x > y ? 1 : 0; }

  // ---------------------------------------------------------------------------
  // Route table
  // ---------------------------------------------------------------------------
  const ROUTES = [];
  function compilePattern(pattern) {
    if (pattern instanceof RegExp) return pattern;
    const src = String(pattern).split(/(\{\w+\})/).map((part) => (/^\{\w+\}$/.test(part) ? '(\\d+)' : part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).join('');
    return new RegExp(`^${src}$`);
  }
  // method: 'GET' | 'POST' | 'PUT' | 'DELETE' | '*' (any method).
  function route(method, pattern, handler) {
    ROUTES.push({ method: String(method).toUpperCase(), pattern: compilePattern(pattern), handler });
  }

  class MockApi {
    constructor({ foodsData = null, hemodialysis = false } = {}) {
      this._lastUs = 0;
      this._foods = []; this._foodById = new Map(); this._nextFoodId = 1;
      this._entries = []; this._nextEntryId = 1;
      this._templates = []; this._nextTemplateId = 1;
      this.foodsSource = foodsData ? 'embedded' : 'fallback';
      this._profile = { id: 1, name: '', weight_kg: null, height_cm: null, ckd_stage: '3b', dialysis: 'none', diabetes: 'type1', warn_fraction: 0.8, about_tolerance_pct: 0,
        ckd_stage_chosen: false, diabetes_chosen: false, dialysis_days: [], week_start: 'monday', targets: {}, updated_at: this._stamp() };
      this._importBuiltin(foodsData || KH.mock.fallbackFoods());
      KH.mock.seedSampleData(this, { hemodialysis });
    }

    // utcnow(): ISO-8601 UTC with microseconds, strictly increasing within the page.
    _stamp(date = null) {
      let us = (date ? date.getTime() : Date.now()) * 1000;
      if (!date) { if (us <= this._lastUs) us = this._lastUs + 1; this._lastUs = us; }
      const ms = Math.floor(us / 1000);
      return `${new Date(ms).toISOString().slice(0, 19)}.${String(ms % 1000).padStart(3, '0')}${String(us % 1000).padStart(3, '0')}Z`;
    }
    // Query parameters shared by several routes.
    _dateParam(value, name) {
      if (value == null || value === '') fail(400, `${name} is required (YYYY-MM-DD)`);
      const e = validDate(value);
      if (e) fail(400, `${name}: ${e}`);
      return value;
    }
    _checkRange(start, end) {
      if (end < start) fail(400, 'end must not be before start');
      if (KH.util.daysBetween(start, end) >= MAX_RANGE_DAYS) fail(400, `range too large (max ${MAX_RANGE_DAYS} days)`);
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
      for (const r of ROUTES) {
        if (r.method !== '*' && r.method !== method) continue;
        const m = p.match(r.pattern);
        if (!m) continue;
        return r.handler.call(this, { method, path: p, id: m[1], ids: m.slice(1), query: q, qp, body });
      }
      fail(404, 'Not Found');
      return null;
    }
  }

  KH.mock = Object.assign(KH.mock || {}, {
    instance: null,
    route, routes: ROUTES, MockApi, ApiError, fail, failFields, Check, choiceMessage, validDate, pydanticInt, pydanticFloat,
    validateNutrients, validateFlags, validateTargets, isDict, asciiLower, nocaseCompare,
    MEAL_RANK, MEAL_KEYS, FOOD_CATEGORIES, MAX_SEARCH_QUERY_CHARS, MAX_SEARCH_WORDS, MAX_RANGE_DAYS, MAX_INTERDIALYTIC_DAYS,
  });
})();
