/* Kidney Diet Log — demo API: the symptoms log (twin of app/symptoms.py with the SymptomCreate model of app/models.py).

   Symptoms live in memory, one list for every demo account, each row keeping its owner's id: every route reads and
   writes only the signed-in person's rows, and a symptom that is not theirs is a 404, as on the server. The words and
   the red flags come from the browser twin js/engine/symptoms.js (KH.symptomRules). Nothing is persisted.

   Parity: tests/data/symptoms_vectors.json replays one request script against the server and against this file
   (node tests/js/run_vectors.mjs), answers and error texts included. */
(() => {
  'use strict';
  const KH = window.KH;
  const R = KH.symptomRules;
  const M = KH.mock;
  const { route, MockApi, Check, fail, failFields, pydanticInt } = M;

  // models._SYMPTOM_TEXT_BAD / _SYMPTOM_LABEL_BAD: control characters (a note may hold tab, newline, carriage return).
  const TEXT_BAD = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
  const LABEL_BAD = /[\u0000-\u001f\u007f]/;
  // Python str.strip() (pydantic's str_strip_whitespace): the characters str.isspace() accepts.
  const PY_SPACE = '\\t\\n\\u000b\\u000c\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');
  const pyStrip = (s) => s.replace(PY_STRIP, '');

  const byDateThenId = (a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id);

  // str field with a default of "" that a null also gives (the before-validator), a length limit in characters (code
  // points) and a plain-text check, in the order of the model's validators.
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

  Object.assign(MockApi.prototype, {
    _symptomsState() {
      if (!this._symptoms) { this._symptoms = []; this._nextSymptomId = 1; }
      return this._symptoms;
    },
    _symptomsOf(userId) { return this._symptomsState().filter((r) => r.user_id === userId); },
    // Store one checked symptom (also usable by a demo seed).
    _insertSymptom(userId, data, createdAt = null) {
      this._symptomsState();
      const row = { id: this._nextSymptomId++, user_id: userId, date: data.date, symptom: data.symptom, label: data.label, severity: data.severity,
        note: data.note, created_at: createdAt || this._stamp() };
      this._symptoms.push(row);
      return row;
    },
    // SymptomCreate: field errors in the model's order, then unknown fields, then the label rule.
    _symptomBody(body) {
      const c = new Check(body);
      if (!c.has('date')) c.err('date', 'Field required');
      else if (typeof c.body.date !== 'string') c.err('date', 'Input should be a valid string');
      else {
        const s = pyStrip(c.body.date);
        const e = M.pastDateError(s);
        if (e) c.err('date', e); else c.out.date = s;
      }
      c.choice('symptom', R.KEYS, { required: true });
      c.num('severity', { required: true, nullable: false, int: true, ge: 1, le: 3 });
      textField(c, 'label', R.MAX_LABEL, LABEL_BAD, 'must be one line of plain text');
      textField(c, 'note', R.MAX_NOTE, TEXT_BAD, 'must be plain text');
      for (const k of Object.keys(c.body)) if (!['date', 'symptom', 'severity', 'label', 'note'].includes(k)) c.err(k, 'Extra inputs are not permitted');
      const data = c.done();
      if (data.symptom === 'other' && !data.label) fail(400, 'label is required when the symptom is other');
      if (data.symptom !== 'other' && data.label) fail(400, 'label is only for the symptom other');
      return data;
    },
    // symptoms._fetch: the person's own symptom, or a 404 (the same for somebody else's and one that does not exist).
    _symptomOf(userId, id) {
      const row = Number.isSafeInteger(id) && id >= 1 ? this._symptomsOf(userId).find((r) => r.id === id) : null;
      if (!row) fail(404, 'Symptom not found');
      return row;
    },
    _checkSymptomDay(userId, day, exceptId = null) {
      const n = this._symptomsOf(userId).filter((r) => r.date === day && r.id !== exceptId).length;
      if (n >= R.MAX_PER_DAY) fail(400, `too many symptoms for one day (max ${R.MAX_PER_DAY})`);
    },
    _updateSymptom(user, id, data) {
      const row = this._symptomOf(user.id, id);
      this._checkSymptomDay(user.id, data.date, row.id);
      Object.assign(row, { date: data.date, symptom: data.symptom, label: data.label, severity: data.severity, note: data.note });
      return R.rowToSymptom(row);
    },
    _deleteSymptom(user, id) {
      const row = this._symptomOf(user.id, id);
      this._symptoms.splice(this._symptoms.indexOf(row), 1);
      return null;
    },
  });

  route('GET', '/api/symptoms', function ({ qp }) {
    const user = this._currentUser();
    const start = this._dateParam(qp('start'), 'start');
    const end = this._dateParam(qp('end'), 'end');
    this._checkRange(start, end);
    const rows = this._symptomsOf(user.id).filter((r) => r.date >= start && r.date <= end).sort(byDateThenId);
    return { symptoms: rows.map((r) => R.rowToSymptom(r)) };
  });
  route('POST', '/api/symptoms', function ({ body }) {
    const user = this._currentUser();
    const data = this._symptomBody(body);
    this._checkSymptomDay(user.id, data.date);
    return R.rowToSymptom(this._insertSymptom(user.id, data));
  });
  route('PUT', '/api/symptoms/{id}', function ({ id, body }) {
    const user = this._currentUser();
    const data = this._symptomBody(body); // the body is checked before the symptom is looked up, as FastAPI does
    return this._updateSymptom(user, Number(id), data);
  });
  route('DELETE', '/api/symptoms/{id}', function ({ id }) {
    return this._deleteSymptom(this._currentUser(), Number(id));
  });
  // A path id that is not made of digits only: pydantic reads "-1", "+2", "1_0" and "3.0" as whole numbers (a 404 or the
  // symptom they name) and fails anything else with a validation error, listed before the body's errors.
  const ID_ERROR = 'symptom_id: Input should be a valid integer, unable to parse string as an integer';
  route('PUT', /^\/api\/symptoms\/([^/]+)$/, function ({ id, body }) {
    const user = this._currentUser();
    const n = pydanticInt(id);
    const errors = n === undefined ? [ID_ERROR] : [];
    let data = null;
    try { data = this._symptomBody(body); } catch (e) {
      if (!e || e.status !== 400) throw e;
      errors.push(e.detail);
    }
    if (errors.length) failFields(errors);
    return this._updateSymptom(user, n, data);
  });
  route('DELETE', /^\/api\/symptoms\/([^/]+)$/, function ({ id }) {
    const user = this._currentUser();
    const n = pydanticInt(id);
    if (n === undefined) failFields([ID_ERROR]);
    return this._deleteSymptom(user, n);
  });
})();
