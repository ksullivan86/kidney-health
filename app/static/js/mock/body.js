/* Kidney Diet Log — demo API: the weight and blood pressure log (twin of app/body.py with the WeightCreate, BloodPressureCreate and
   BodyBatch models of app/models.py).

   Weights and readings live in memory, one list for every demo account, each row keeping its owner's id: every route reads and
   writes only the signed-in person's rows, and a row that is not theirs is a 404, as on the server. The numbers, the words and the
   flags come from the browser twin js/engine/body.js (KH.bodyRules). Nothing is persisted here ("Keep my data in this browser",
   js/mock/persist.js, keeps the tables below).

   Differences from the server, on purpose: the demo has no rate limit on the batch routes (60 requests an hour per person on a
   server), and no body-size limit.

   Parity: tests/data/body_vectors.json replays one request script against the server and against this file
   (node tests/js/run_vectors.mjs), answers and error texts included. */
(() => {
  'use strict';
  const KH = window.KH;
  const R = KH.bodyRules;
  const M = KH.mock;
  const { route, MockApi, Check, fail, failFields, pydanticInt, isDict } = M;
  const L = R.LIMITS;

  // models._SYMPTOM_TEXT_BAD / _SYMPTOM_LABEL_BAD: control characters (a note may hold tab, newline, carriage return).
  const TEXT_BAD = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
  const LABEL_BAD = /[\u0000-\u001f\u007f]/;
  // Python str.strip() (pydantic's str_strip_whitespace): the characters str.isspace() accepts.
  const PY_SPACE = '\\t\\n\\u000b\\u000c\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');
  const pyStrip = (s) => s.replace(PY_STRIP, '');
  const TIME_RE = /^([01][0-9]|2[0-3]):[0-5][0-9]$/; // models._TIME_RE: ASCII digits, the whole string
  const TIME_MESSAGE = 'must be a time such as 07:30 (HH:MM, 00:00 to 23:59)';

  // str field with a default of "" that a null also gives (the before-validator), a length limit in characters (code points) and a
  // plain-text check, in the order of the model's validators.
  function textField(c, k, max, bad, badMessage) {
    if (!c.has(k)) { c.out[k] = ''; return; }
    let v = c.body[k];
    if (v == null) v = '';
    if (typeof v !== 'string') { c.err(k, 'Input should be a valid string'); return; }
    v = pyStrip(v);
    if (Array.from(v).length > max) { c.err(k, `String should have at most ${max} characters`); return; }
    if (bad.test(v)) { c.err(k, badMessage); return; }
    c.out[k] = v;
  }
  // `str` that must be there, with limits in characters and a plain-text check (the batch row's source_key).
  function keyField(c, k, min, max) {
    if (!c.has(k)) { c.err(k, 'Field required'); return; }
    let v = c.body[k];
    if (typeof v !== 'string') { c.err(k, 'Input should be a valid string'); return; }
    v = pyStrip(v);
    const n = Array.from(v).length;
    if (n < min) { c.err(k, `String should have at least ${min} character${min === 1 ? '' : 's'}`); return; }
    if (n > max) { c.err(k, `String should have at most ${max} characters`); return; }
    if (LABEL_BAD.test(v)) { c.err(k, 'must be one line of plain text'); return; }
    c.out[k] = v;
  }
  // _BodyRow: the day and the optional time.
  function dayFields(c) {
    if (!c.has('date')) c.err('date', 'Field required');
    else if (typeof c.body.date !== 'string') c.err('date', 'Input should be a valid string');
    else {
      const s = pyStrip(c.body.date);
      const e = M.pastDateError(s);
      if (e) c.err('date', e); else c.out.date = s;
    }
    if (!c.has('time') || c.body.time == null) { c.out.time = null; return; }
    if (typeof c.body.time !== 'string') { c.err('time', 'Input should be a valid string'); return; }
    const s = pyStrip(c.body.time);
    if (!s) c.out.time = null; // a blank time is no time
    else if (!TIME_RE.test(s)) c.err('time', TIME_MESSAGE);
    else c.out.time = s;
  }
  // The fields of WeightCreate / BloodPressureCreate, in the models' order; `batch` adds source and source_key.
  function weightFields(c, batch) {
    dayFields(c);
    c.num('kg', { required: true, nullable: false, ge: L.min_kg, le: L.max_kg });
    c.choice('context', R.WEIGHT_CONTEXTS, { required: true });
    textField(c, 'note', L.max_note, TEXT_BAD, 'must be plain text');
    if (batch) batchFields(c);
    extras(c, ['date', 'time', 'kg', 'context', 'note', ...(batch ? ['source', 'source_key'] : [])]);
  }
  function readingFields(c, batch) {
    dayFields(c);
    c.num('systolic', { required: true, nullable: false, int: true, ge: L.min_systolic, le: L.max_systolic });
    c.num('diastolic', { required: true, nullable: false, int: true, ge: L.min_diastolic, le: L.max_diastolic });
    c.num('pulse', { int: true, ge: L.min_pulse, le: L.max_pulse, def: null });
    c.choice('context', R.BLOOD_PRESSURE_CONTEXTS, { required: true });
    textField(c, 'note', L.max_note, TEXT_BAD, 'must be plain text');
    if (batch) batchFields(c);
    extras(c, ['date', 'time', 'systolic', 'diastolic', 'pulse', 'context', 'note', ...(batch ? ['source', 'source_key'] : [])]);
  }
  function batchFields(c) {
    c.choice('source', ['apple_health', 'import'], { def: 'import' });
    keyField(c, 'source_key', 1, L.max_source_key);
  }
  function extras(c, known) {
    for (const k of Object.keys(c.body)) if (!known.includes(k)) c.err(k, 'Extra inputs are not permitted');
  }
  const TOP_BELOW_BOTTOM = 'systolic must be greater than diastolic';

  // A request id: pydantic reads "-1", "+2", "1_0" and "3.0" as whole numbers (a 404 or the row they name) and fails anything else
  // with a validation error, listed before the body's errors.
  const idError = (name) => `${name}: Input should be a valid integer, unable to parse string as an integer`;

  Object.assign(MockApi.prototype, {
    _bodyState() {
      if (!this._weights) { this._weights = []; this._nextWeightId = 1; this._readings = []; this._nextReadingId = 1; }
      return this._weights;
    },
    _weightsOf(userId) { return this._bodyState().filter((r) => r.user_id === userId); },
    _readingsOf(userId) { this._bodyState(); return this._readings.filter((r) => r.user_id === userId); },
    // Store one checked weight / reading (also usable by a demo seed). `data` is what the models give; kg is stored to 0.01.
    _insertWeight(userId, data, { source = 'manual', sourceKey = null, createdAt = null } = {}) {
      this._bodyState();
      const at = createdAt || this._stamp();
      const row = { id: this._nextWeightId++, user_id: userId, date: data.date, time: data.time == null ? null : data.time, kg: R.roundKg(data.kg),
        context: data.context, note: data.note || '', source, source_key: sourceKey, created_at: at, updated_at: at };
      this._weights.push(row);
      return row;
    },
    _insertReading(userId, data, { source = 'manual', sourceKey = null, createdAt = null } = {}) {
      this._bodyState();
      const at = createdAt || this._stamp();
      const row = { id: this._nextReadingId++, user_id: userId, date: data.date, time: data.time == null ? null : data.time, systolic: data.systolic,
        diastolic: data.diastolic, pulse: data.pulse == null ? null : data.pulse, context: data.context, note: data.note || '', source,
        source_key: sourceKey, created_at: at, updated_at: at };
      this._readings.push(row);
      return row;
    },
    // WeightCreate / BloodPressureCreate: field errors in the model's order, then unknown fields, then the model's own rule.
    _weightBody(body) {
      const c = new Check(body);
      weightFields(c, false);
      return c.done();
    },
    _readingBody(body) {
      const c = new Check(body);
      readingFields(c, false);
      const data = c.done();
      if (data.systolic <= data.diastolic) fail(400, TOP_BELOW_BOTTOM);
      return data;
    },
    // body.py _fetch_*: the person's own row, or a 404 (the same for somebody else's and one that does not exist).
    _weightOf(userId, id) {
      const row = Number.isSafeInteger(id) && id >= 1 ? this._weightsOf(userId).find((r) => r.id === id) : null;
      if (!row) fail(404, 'Weight not found');
      return row;
    },
    _readingOf(userId, id) {
      const row = Number.isSafeInteger(id) && id >= 1 ? this._readingsOf(userId).find((r) => r.id === id) : null;
      if (!row) fail(404, 'Blood pressure reading not found');
      return row;
    },
    _checkWeightDay(userId, day, exceptId = null) {
      const n = this._weightsOf(userId).filter((r) => r.date === day && r.id !== exceptId).length;
      if (n >= L.max_weights_per_day) fail(400, `too many weights for one day (max ${L.max_weights_per_day})`);
    },
    _checkReadingDay(userId, day, exceptId = null) {
      const n = this._readingsOf(userId).filter((r) => r.date === day && r.id !== exceptId).length;
      if (n >= L.max_readings_per_day) fail(400, `too many blood pressure readings for one day (max ${L.max_readings_per_day})`);
    },
    _updateWeight(user, id, data) {
      const row = this._weightOf(user.id, id);
      this._checkWeightDay(user.id, data.date, row.id);
      Object.assign(row, { date: data.date, time: data.time, kg: R.roundKg(data.kg), context: data.context, note: data.note, source: 'manual', updated_at: this._stamp() });
      return R.rowToWeight(row);
    },
    _updateReading(user, id, data) {
      const row = this._readingOf(user.id, id);
      this._checkReadingDay(user.id, data.date, row.id);
      Object.assign(row, { date: data.date, time: data.time, systolic: data.systolic, diastolic: data.diastolic, pulse: data.pulse, context: data.context,
        note: data.note, source: 'manual', updated_at: this._stamp() });
      return R.rowToReading(row);
    },
    _deleteWeight(user, id) {
      const row = this._weightOf(user.id, id);
      this._weights.splice(this._weights.indexOf(row), 1);
      return null;
    },
    _deleteReading(user, id) {
      const row = this._readingOf(user.id, id);
      this._readings.splice(this._readings.indexOf(row), 1);
      return null;
    },
    // BodyBatch, then every row by the route (the first row with a problem refuses the whole request and names the row).
    _batchRows(body, fields, modelCheck = null) {
      const c = new Check(body);
      if (!c.has('rows')) c.err('rows', 'Field required');
      else if (!Array.isArray(c.body.rows)) c.err('rows', 'Input should be a valid list');
      else {
        let bad = false;
        c.body.rows.forEach((x, i) => { if (!isDict(x)) { c.err(`rows.${i}`, 'Input should be a valid dictionary'); bad = true; } });
        const n = c.body.rows.length;
        if (!bad && n < 1) c.err('rows', 'List should have at least 1 item after validation, not 0');
        else if (!bad && n > L.max_batch) c.err('rows', `List should have at most ${L.max_batch} items after validation, not ${n}`);
        else if (!bad) c.out.rows = c.body.rows;
      }
      extras(c, ['rows']);
      const { rows } = c.done();
      return rows.map((raw, index) => {
        const rc = new Check(raw, { nested: true });
        fields(rc, true);
        const errors = rc.errors.map((e) => `rows.${index}.${e}`);
        if (errors.length) failFields(errors);
        const problem = modelCheck ? modelCheck(rc.out) : null; // the model's own rule runs only when every field is valid
        if (problem) fail(400, `rows.${index}: ${problem}`);
        return { index, data: rc.out };
      });
    },
    _bodyKeys(table, userId) {
      return new Set(this[table === 'weights' ? '_weightsOf' : '_readingsOf'](userId).filter((r) => r.source_key != null).map((r) => r.source_key));
    },
    // "The same reading" (app/body.py known_weight_marks / known_reading_marks): the person's rows that are not typed and have a time, as
    // date|HH:MM|kg (a weight) or date|HH:MM|systolic/diastolic (a reading). A typed row never matches; a row with no time cannot match.
    _weightMarks(userId) {
      return new Set(this._weightsOf(userId).filter((r) => r.source !== 'manual' && r.time != null).map((r) => `${r.date}|${r.time}|${R.roundKg(r.kg)}`));
    },
    _readingMarks(userId) {
      return new Set(this._readingsOf(userId).filter((r) => r.source !== 'manual' && r.time != null).map((r) => `${r.date}|${r.time}|${r.systolic}/${r.diastolic}`));
    },
  });

  // ---- weights
  route('GET', '/api/body/weights', function ({ qp }) {
    const user = this._currentUser();
    const start = this._dateParam(qp('start'), 'start');
    const end = this._dateParam(qp('end'), 'end');
    this._checkRange(start, end);
    const rows = this._weightsOf(user.id).filter((r) => r.date >= start && r.date <= end).map(R.rowToWeight).sort(R.compareRows);
    return { weights: rows };
  });
  route('POST', '/api/body/weights', function ({ body }) {
    const user = this._currentUser();
    const data = this._weightBody(body);
    this._checkWeightDay(user.id, data.date);
    return R.rowToWeight(this._insertWeight(user.id, data));
  });
  route('POST', '/api/body/weights/batch', function ({ body }) {
    const user = this._currentUser();
    const rows = this._batchRows(body, weightFields);
    const known = this._bodyKeys('weights', user.id);
    const marks = this._weightMarks(user.id);
    const perDay = new Map();
    for (const r of this._weightsOf(user.id)) perDay.set(r.date, (perDay.get(r.date) || 0) + 1);
    const fresh = [];
    for (const { index, data } of rows) {
      const mark = data.time == null ? null : `${data.date}|${data.time}|${R.roundKg(data.kg)}`;
      if (known.has(data.source_key) || (mark !== null && marks.has(mark))) continue;
      if ((perDay.get(data.date) || 0) >= L.max_weights_per_day) fail(400, `rows.${index}: too many weights for one day (max ${L.max_weights_per_day})`);
      known.add(data.source_key);
      if (mark !== null) marks.add(mark);
      perDay.set(data.date, (perDay.get(data.date) || 0) + 1);
      fresh.push(data);
    }
    const at = this._stamp();
    for (const data of fresh) this._insertWeight(user.id, data, { source: data.source, sourceKey: data.source_key, createdAt: at });
    return { added: fresh.length, skipped: rows.length - fresh.length };
  });
  route('PUT', '/api/body/weights/{id}', function ({ id, body }) {
    const user = this._currentUser();
    const data = this._weightBody(body); // the body is checked before the row is looked up, as FastAPI does
    return this._updateWeight(user, Number(id), data);
  });
  route('DELETE', '/api/body/weights/{id}', function ({ id }) {
    return this._deleteWeight(this._currentUser(), Number(id));
  });
  route('PUT', /^\/api\/body\/weights\/([^/]+)$/, function ({ id, body }) {
    const user = this._currentUser();
    const n = pydanticInt(id);
    const errors = n === undefined ? [idError('weight_id')] : [];
    let data = null;
    try { data = this._weightBody(body); } catch (e) {
      if (!e || e.status !== 400) throw e;
      errors.push(e.detail);
    }
    if (errors.length) failFields(errors);
    return this._updateWeight(user, n, data);
  });
  route('DELETE', /^\/api\/body\/weights\/([^/]+)$/, function ({ id }) {
    const user = this._currentUser();
    const n = pydanticInt(id);
    if (n === undefined) failFields([idError('weight_id')]);
    return this._deleteWeight(user, n);
  });

  // ---- blood pressure
  route('GET', '/api/body/blood-pressure', function ({ qp }) {
    const user = this._currentUser();
    const start = this._dateParam(qp('start'), 'start');
    const end = this._dateParam(qp('end'), 'end');
    this._checkRange(start, end);
    const rows = this._readingsOf(user.id).filter((r) => r.date >= start && r.date <= end).map(R.rowToReading).sort(R.compareRows);
    return { readings: rows };
  });
  route('POST', '/api/body/blood-pressure', function ({ body }) {
    const user = this._currentUser();
    const data = this._readingBody(body);
    this._checkReadingDay(user.id, data.date);
    return R.rowToReading(this._insertReading(user.id, data));
  });
  route('POST', '/api/body/blood-pressure/batch', function ({ body }) {
    const user = this._currentUser();
    const rows = this._batchRows(body, readingFields, (data) => (data.systolic <= data.diastolic ? TOP_BELOW_BOTTOM : null));
    const known = this._bodyKeys('readings', user.id);
    const marks = this._readingMarks(user.id);
    const perDay = new Map();
    for (const r of this._readingsOf(user.id)) perDay.set(r.date, (perDay.get(r.date) || 0) + 1);
    const fresh = [];
    for (const { index, data } of rows) {
      const mark = data.time == null ? null : `${data.date}|${data.time}|${data.systolic}/${data.diastolic}`;
      if (known.has(data.source_key) || (mark !== null && marks.has(mark))) continue;
      if ((perDay.get(data.date) || 0) >= L.max_readings_per_day) {
        fail(400, `rows.${index}: too many blood pressure readings for one day (max ${L.max_readings_per_day})`);
      }
      known.add(data.source_key);
      if (mark !== null) marks.add(mark);
      perDay.set(data.date, (perDay.get(data.date) || 0) + 1);
      fresh.push(data);
    }
    const at = this._stamp();
    for (const data of fresh) this._insertReading(user.id, data, { source: data.source, sourceKey: data.source_key, createdAt: at });
    return { added: fresh.length, skipped: rows.length - fresh.length };
  });
  route('PUT', '/api/body/blood-pressure/{id}', function ({ id, body }) {
    const user = this._currentUser();
    const data = this._readingBody(body);
    return this._updateReading(user, Number(id), data);
  });
  route('DELETE', '/api/body/blood-pressure/{id}', function ({ id }) {
    return this._deleteReading(this._currentUser(), Number(id));
  });
  route('PUT', /^\/api\/body\/blood-pressure\/([^/]+)$/, function ({ id, body }) {
    const user = this._currentUser();
    const n = pydanticInt(id);
    const errors = n === undefined ? [idError('reading_id')] : [];
    let data = null;
    try { data = this._readingBody(body); } catch (e) {
      if (!e || e.status !== 400) throw e;
      errors.push(e.detail);
    }
    if (errors.length) failFields(errors);
    return this._updateReading(user, n, data);
  });
  route('DELETE', /^\/api\/body\/blood-pressure\/([^/]+)$/, function ({ id }) {
    const user = this._currentUser();
    const n = pydanticInt(id);
    if (n === undefined) failFields([idError('reading_id')]);
    return this._deleteReading(user, n);
  });

  // ---- summary
  const SUMMARY_WEIGHT_ROWS = 400; // app/body.py: the newest rows the summary reads
  const SUMMARY_READING_ROWS = 250;
  route('GET', '/api/body/summary', function ({ qp }) {
    const user = this._currentUser();
    const day = this._dateParam(qp('date'), 'date');
    const get = (key) => this._effectiveSetting(key, user.id).value;
    const units = get('user.units.weight');
    const profile = this._profileView();
    const newest = (rows, n) => rows.filter((r) => r.date <= day).sort((a, b) => (a.date !== b.date ? (a.date < b.date ? 1 : -1) : b.id - a.id)).slice(0, n);
    return R.summarise(newest(this._weightsOf(user.id), SUMMARY_WEIGHT_ROWS).map(R.rowToWeight), newest(this._readingsOf(user.id), SUMMARY_READING_ROWS).map(R.rowToReading),
      { day, units, alarm: get('body.weight_alarm'), goal: get('body.bp_goal'), dryWeightKg: profile.dialysis === 'hemodialysis' ? profile.weight_kg : null });
  });
})();
