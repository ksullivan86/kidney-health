/* Kidney Diet Log — demo API: lab results and the kidney-function card (twin of app/labs.py
   with the LabCreate model of app/models.py).

   Results live in memory, one list for every demo account, each row keeping its owner's id: every
   route reads and writes only the signed-in person's rows, and a result that is not theirs is a
   404, as on the server. Values are converted to the analyte's canonical unit by the browser twin
   of app/units.py (js/engine/kidney_function.js); a potassium of 6.0 mmol/L or more returns the
   same safety alert as the server (js/engine/targets.js potassiumAlert), whatever the
   targets.lab_rules_enabled setting says. */
(() => {
  'use strict';
  const KH = window.KH;
  const K = KH.kidney;
  const T = KH.targets;
  const M = KH.mock;
  const { route, MockApi, Check, fail, failFields, choiceMessage, pydanticInt } = M;
  const { todayStr, addDays } = KH.util;

  const DEFAULT_LIST_LIMIT = 200;
  const MAX_LIST_LIMIT = 1000;
  const MAX_LAB_IMPORT = 1000;
  const MAX_NOTE = 500;
  const MAX_VALUE = 1000000;
  const LAB_FIELDS = ['analyte', 'value', 'unit', 'taken_on', 'note'];

  // newest first: taken_on, then entry order (the lab_results_lookup index order).
  const newestFirst = (a, b) => (a.taken_on < b.taken_on ? 1 : a.taken_on > b.taken_on ? -1 : b.id - a.id);

  Object.assign(MockApi.prototype, {
    _labsState() {
      if (!this._labs) { this._labs = []; this._nextLabId = 1; }
      return this._labs;
    },
    _labsOf(userId) { return this._labsState().filter((r) => r.user_id === userId); },
    // labs.latest_results: the newest stored result of each analyte for one person.
    _latestLabs(userId, analytes) {
      const mine = this._labsOf(userId).slice().sort(newestFirst);
      const out = [];
      for (const a of analytes) { const r = mine.find((x) => x.analyte === a); if (r) out.push({ ...r }); }
      return out;
    },
    // Store one converted result (also used by the demo seed).
    _insertLab(userId, conv, takenOn, note, createdAt = null) {
      this._labsState();
      const row = { id: this._nextLabId++, user_id: userId, analyte: conv.analyte, value: conv.value, entered_value: conv.entered_value,
        entered_unit: conv.entered_unit, taken_on: takenOn, note, created_at: createdAt || this._stamp() };
      this._labs.push(row);
      return row;
    },
    // LabCreate: field errors in the model's order, then unknown fields, then the conversion check.
    _labBody(body) {
      const c = new Check(body);
      c.choice('analyte', K.ANALYTE_KEYS, { required: true });
      c.num('value', { required: true, nullable: false, ge: 0, le: MAX_VALUE });
      c.str('unit', { required: true, nullable: false, min: 1, max: 40 });
      if (!c.has('taken_on')) c.err('taken_on', 'Field required');
      else if (typeof c.body.taken_on !== 'string') c.err('taken_on', 'Input should be a valid string');
      else {
        const s = c.body.taken_on.trim();
        const e = M.pastDateError(s);
        if (e) c.err('taken_on', e); else c.out.taken_on = s;
      }
      if (c.has('note') && c.body.note == null) c.out.note = ''; // the before-validator turns null into ""
      else c.str('note', { max: MAX_NOTE, def: '', nullable: false });
      for (const k of Object.keys(c.body)) if (!LAB_FIELDS.includes(k)) c.err(k, 'Extra inputs are not permitted');
      const data = c.done();
      try {
        return { ...data, conv: K.convert(data.analyte, data.value, data.unit) };
      } catch (e) {
        if (e instanceof K.UnitError) return fail(400, e.message);
        throw e;
      }
    },
    _labView(row) { return K.rowToLab(row); },
    // labs.current_alerts: the newest potassium's safety alert while it is fresh under
    // targets.lab_fresh_days.potassium, the window the suggestions use (v0.3.0 review L3).
    _labAlerts(userId) {
      const windows = this._targetSettings().fresh_days;
      const fresh = T.freshLabs(this._latestLabs(userId, ['potassium']), todayStr(), windows);
      const alert = T.potassiumAlert(fresh.potassium || null);
      return alert ? [alert] : [];
    },
  });

  route('POST', '/api/labs', function ({ body }) {
    const user = this._currentUser();
    const b = this._labBody(body);
    const row = this._insertLab(user.id, b.conv, b.taken_on, b.note);
    const out = this._labView(row);
    const alerts = [];
    if (row.analyte === 'potassium') {
      const alert = T.potassiumAlert({ value: row.value, taken_on: row.taken_on });
      if (alert) alerts.push(alert);
    }
    return { ...out, alerts };
  });
  // POST /api/labs/import (v0.3.1): each item checked like POST /api/labs (a refused one is listed with the same
  // message, the others saved); one that repeats a saved result of this person (test, date, shown value) or an
  // earlier item is skipped; `alerts` as GET /api/labs.
  route('POST', '/api/labs/import', function ({ body }) {
    const user = this._currentUser();
    const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
    if (!isObject(body)) failFields(['Input should be a valid dictionary or object to extract fields from']);
    const errors = [];
    const results = body.results;
    if (!Object.prototype.hasOwnProperty.call(body, 'results')) errors.push('results: Field required');
    else if (!Array.isArray(results)) errors.push('results: Input should be a valid list');
    else {
      results.forEach((item, i) => { if (!isObject(item)) errors.push(`results.${i}: Input should be a valid dictionary`); });
      if (results.length < 1) errors.push('results: List should have at least 1 item after validation, not 0');
      else if (results.length > MAX_LAB_IMPORT) errors.push(`results: List should have at most ${MAX_LAB_IMPORT} items after validation, not ${results.length}`);
    }
    for (const k of Object.keys(body)) if (k !== 'results') errors.push(`${k}: Extra inputs are not permitted`);
    if (errors.length) failFields(errors);
    const refused = [];
    const checked = [];
    results.forEach((item, index) => {
      try { checked.push(this._labBody(item)); } catch (e) {
        if (e && e.status === 400) refused.push({ index, reason: e.detail }); else throw e;
      }
    });
    const keyOf = (analyte, takenOn, value) => `${analyte}|${takenOn}|${K.formatValue(analyte, value)}`;
    const seen = new Set(this._labsOf(user.id).filter((r) => K.ANALYTE_KEYS.includes(r.analyte)).map((r) => keyOf(r.analyte, r.taken_on, r.value)));
    let saved = 0;
    let duplicates = 0;
    const now = this._stamp();
    for (const b of checked) {
      const key = keyOf(b.conv.analyte, b.taken_on, b.conv.value);
      if (seen.has(key)) { duplicates += 1; continue; }
      seen.add(key);
      this._insertLab(user.id, b.conv, b.taken_on, b.note, now);
      saved += 1;
    }
    return { saved, duplicates, refused, alerts: this._labAlerts(user.id) };
  });
  route('GET', '/api/labs', function ({ qp }) {
    const user = this._currentUser();
    const errors = [];
    const analyte = qp('analyte');
    if (analyte != null && !K.ANALYTE_KEYS.includes(analyte)) errors.push(`analyte: ${choiceMessage(K.ANALYTE_KEYS)}`);
    let limit = DEFAULT_LIST_LIMIT;
    if (qp('limit') != null) {
      limit = pydanticInt(qp('limit'));
      if (limit === undefined) errors.push('limit: Input should be a valid integer, unable to parse string as an integer');
      else if (limit < 1) errors.push('limit: Input should be greater than or equal to 1');
      else if (limit > MAX_LIST_LIMIT) errors.push(`limit: Input should be less than or equal to ${MAX_LIST_LIMIT}`);
    }
    if (errors.length) failFields(errors);
    const rows = this._labsOf(user.id).filter((r) => analyte == null || r.analyte === analyte).sort(newestFirst).slice(0, limit);
    return { labs: rows.map((r) => this._labView(r)), alerts: this._labAlerts(user.id) };
  });
  // labs.kidney_function: results of the last 365 days, the saved profile; never changes the stage.
  route('GET', '/api/labs/kidney-function', function () {
    const user = this._currentUser();
    const p = this._profileView();
    const day = todayStr();
    const analytes = [...K.KIDNEY_ANALYTES, 'uacr'];
    const window = Math.max(...analytes.map((a) => K.freshDays(a) || 0));
    const since = addDays(day, -window);
    const labs = this._labsOf(user.id).filter((r) => analytes.includes(r.analyte) && r.taken_on >= since).sort(newestFirst);
    return K.assess({ labs, today: day, ckd_stage: p.ckd_stage, dialysis: p.dialysis,
      transplant: T.modeOf(p.dialysis, p.transplant_date) === 'transplant', birth_month: p.birth_month, sex: p.sex,
      pregnant_or_breastfeeding: p.pregnant_or_breastfeeding });
  });
  route('DELETE', '/api/labs/{id}', function ({ id }) {
    const user = this._currentUser();
    const n = Number(id);
    const labs = this._labsState();
    const i = labs.findIndex((r) => r.id === n && r.user_id === user.id);
    if (i < 0) fail(404, 'Lab result not found');
    labs.splice(i, 1);
    return null;
  });
  // A path id that is not a whole number fails validation before the lookup (as FastAPI does);
  // DELETE /api/labs/kidney-function lands here too on the server.
  route('DELETE', /^\/api\/labs\/([^/]+)$/, function () {
    failFields(['lab_id: Input should be a valid integer, unable to parse string as an integer']);
  });

  Object.assign(M, { labsNewestFirst: newestFirst });
})();
