/* Kidney Diet Log — demo API: the export (twin of app/account.py export_data and build_export).

   GET /api/me/export.json answers the document that is export.json inside the server's GET /api/me/export.zip: the same
   keys, the same record shapes, so the file can be chosen in "Import from a file" on a real server (app/data_import.py) and
   in this demo (js/mock/import.js).

   The archive itself (M.exportZip, used by KH.demoLocal.exportFile: the iPhone app and "Keep my data in this browser") is built
   here, in the page: export.json, the CSV files and README.txt of the server's archive, in its order. The CSV files and the README
   are the server's text for the same data (app/account.py _csv and README, app/log.py csv_safe and csv_row; parity in
   tests/data/export_vectors.json). The zip is written with the STORE method (no compression) and a CRC-32 for each file, which
   every unzip tool and this app's own import (js/engine/zip.js) read; the server's is compressed. export.json is
   JSON.stringify(doc, null, 2): a whole number the server writes as 2.0 is 2 here, which every JSON reader takes as the same.

   What differs from a server's file, on purpose: `linked_foods` items have `linked_at: null` (the demo does not keep when a
   shared food was scanned), the AI sections are empty (`ai_audit`, `ai_usage`, `ai_consents`, `ai_provider: null`: the
   demo has no AI), and `app_version` is the page's own version. Passwords, sessions and keys are never in it. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi } = M;
  const EXPORT_FORMAT = KH.brand.exportFormat;
  const EXPORT_VERSION = 1;
  const MAX_EVENTS = 500;

  const byId = (a, b) => a.id - b.id;

  Object.assign(MockApi.prototype, {
    // The export.json document of the signed-in person (app/account.py export_data), key order included.
    _exportDocument() {
      const u = this._currentUser();
      const uid = u.id;
      const own = this._settingsState().users[uid] || {};
      const settings = {};
      for (const key of Object.keys(own).sort()) settings[key] = JSON.parse(JSON.stringify(own[key]));

      // log.entry_fields: the version is derived, not data, and the Care helper's name is not in the file (as on the server)
      const entries = this._fetchEntries().map((row) => { const v = this._entryView(row); delete v.version; delete v.added_by; return v; });
      // client_id (schema step 38, design note 39 §8.2): every synced row's ID on every device; a shared food has none.
      const customFoods = this._foods.filter((f) => f.source === 'custom').sort(byId).map((f) => ({ ...this._foodView(f), client_id: f.client_id || null }));
      const linked = this._foods.filter((f) => f.source !== 'builtin' && f.source !== 'custom' && this._foodLinks().has(f.id)).sort(byId)
        .map((f) => ({ id: f.id, name: f.name, source: f.source, fdc_id: f.fdc_id, linked_at: null, gtin: f.gtin || null,
          food: { ...this._foodView(f), client_id: null } }));
      const templates = this._templates.slice().sort(byId).map((t) => { const v = this._templateView(t); return { id: v.id, client_id: t.client_id || null, ...v }; });
      const labs = this._labsOf(uid).slice().sort((a, b) => (a.taken_on < b.taken_on ? -1 : a.taken_on > b.taken_on ? 1 : a.id - b.id)).map((r) => ({
        id: r.id, analyte: r.analyte, value: r.value, unit: (KH.kidney.ANALYTES[r.analyte] || {}).canonical_unit || '',
        entered_value: r.entered_value, entered_unit: r.entered_unit, taken_on: r.taken_on, note: r.note, created_at: r.created_at, client_id: r.client_id || null }));
      const symptoms = this._symptomsOf(uid).slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.id - b.id)).map((r) => ({
        id: r.id, date: r.date, symptom: r.symptom, label: r.label, severity: r.severity, note: r.note, created_at: r.created_at, client_id: r.client_id || null }));
      // weights and blood_pressures (schema step 18): the stored columns, oldest day first (app/body.py export_weights / export_readings)
      const BR = KH.bodyRules;
      const weights = this._weightsOf(uid).slice().sort(BR.compareRows).map((r) => ({ id: r.id, date: r.date, time: r.time, kg: r.kg, context: r.context,
        note: r.note || '', source: r.source, source_key: r.source_key == null ? null : r.source_key, created_at: r.created_at, updated_at: r.updated_at,
        client_id: r.client_id || null }));
      const bloodPressures = this._readingsOf(uid).slice().sort(BR.compareRows).map((r) => ({ id: r.id, date: r.date, time: r.time, systolic: r.systolic,
        diastolic: r.diastolic, pulse: r.pulse, context: r.context, note: r.note || '', source: r.source, source_key: r.source_key == null ? null : r.source_key,
        created_at: r.created_at, updated_at: r.updated_at, client_id: r.client_id || null }));
      // food_preferences (schema steps 5 and 17): every preference of the person, with who set it and when it last changed.
      const prefs = [...this._foodPreferences().entries()].map(([foodId, row]) => ({ food: this._food(foodId), row }))
        .filter((p) => p.food).sort((a, b) => a.food.id - b.food.id)
        .map((p) => ({ food_id: p.food.id, name: p.food.name, preference: p.row.preference, created_at: p.row.created_at,
          source: p.row.source || 'person', updated_at: p.row.updated_at || p.row.created_at }));
      // The built-in foods the entries, saved meals and food preferences point at, so another server can find them by FoodData Central id.
      const used = new Set(entries.map((e) => e.food_id));
      for (const t of this._templates) for (const it of t.items) used.add(it.food_id);
      for (const p of prefs) used.add(p.food_id);
      const builtin = [...used].map((id) => this._food(id)).filter((f) => f && f.source === 'builtin').sort(byId)
        .map((f) => ({ id: f.id, name: f.name, fdc_id: f.fdc_id }));
      const a = this._authState();
      const activity = a.events.filter((e) => (e.target_type === 'user' && e.target_id === String(uid))
        || (e.actor_user_id === uid && (e.target_type !== 'user' || e.target_id == null || e.target_id === String(uid))))
        .sort((x, y) => y.id - x.id).slice(0, MAX_EVENTS).map((e) => JSON.parse(JSON.stringify(e)));
      const views = KH.views || {};
      return {
        format: EXPORT_FORMAT,
        version: EXPORT_VERSION,
        exported_at: this._stamp(new Date()),
        app_version: views.settings && views.settings.APP_VERSION ? views.settings.APP_VERSION : null,
        user: { username: u.username, display_name: u.display_name || '', created_at: u.created_at, email: u.email || null, email_confirmed_at: u.email ? (u.email_confirmed_at || null) : null },
        profile: this._profileView(),
        settings,
        log_entries: entries,
        custom_foods: customFoods,
        linked_foods: linked,
        meal_templates: templates,
        lab_results: labs,
        symptoms,
        weights,
        blood_pressures: bloodPressures,
        ai_audit: [],
        activity,
        food_preferences: prefs,
        ai_usage: [],
        ai_consents: [],
        ai_provider: null,
        builtin_foods: builtin,
        ...(this._activityExport ? this._activityExport() : { activity_days: [], activity_workouts: [], activity_extra: null }),
        care_suggestions: this._careExport ? this._careExport() : [], // suggestions from the Care team (js/mock/care.js)
        reminders: this._remindersExport ? this._remindersExport() : [], // reminders (js/mock/reminders.js); never the devices
        care_notes: this._careNotesExport ? this._careNotesExport() : [], // notes from the Care team (js/mock/care.js)
      };
    },
  });


  // --------------------------------------------------------------------------- the archive (app/account.py build_export)
  const R = KH.rules;
  // app/log.py _FORMULA_PREFIXES and csv_safe: text a spreadsheet would run as a formula starts with a quote.
  const FORMULA_PREFIXES = ['=', '+', '-', '@', '\t', '\r', '\n', '＝', '＋', '－', '＠'];
  const csvSafe = (v) => (v == null ? '' : typeof v === 'string' && FORMULA_PREFIXES.some((p) => v.startsWith(p)) ? `'${v}` : v);
  // One cell as Python's csv.writer writes it (QUOTE_MINIMAL, "\r\n"). The kind says what Python held, since JSON cannot:
  // 'f' a float (5 is "5.0"), 'n:<key>' a rounded nutrient (whole for mg and mL, else a float), 'b' a bool ("True").
  function cell(v, kind) {
    let s;
    if (v == null || v === '') s = '';
    else if (kind === 'f') s = R.pyRepr(v);
    else if (kind && kind.startsWith('n:')) s = R.isIntUnit(kind.slice(2)) ? String(v) : R.pyRepr(v);
    else if (kind === 'b' || typeof v === 'boolean') s = v ? 'True' : 'False';
    else s = String(csvSafe(v));
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  // account._csv: a header line, then one line per row; cols is [[name, kind], ...].
  function csv(cols, rows) {
    const lines = [cols.map(([name]) => cell(name)).join(',')];
    for (const row of rows) lines.push(cols.map(([, kind], i) => cell(row[i], kind)).join(','));
    return `${lines.join('\r\n')}\r\n`;
  }
  const plainCols = (names, kinds = {}) => names.map((n) => [n, kinds[n] || null]);
  const NUT_COLS = () => R.NUTRIENT_KEYS.map((k) => [k, `n:${k}`]);
  const LOG_COLS = () => [...plainCols(['id', 'date', 'meal', 'status', 'food_id', 'food_name', 'servings', 'grams', 'note'], { servings: 'f', grams: 'f' }),
    ...NUT_COLS(), ...plainCols(['created_at', 'updated_at', 'purpose', 'source', 'source_license'])];
  const FOOD_FIELDS = ['id', 'name', 'brand', 'category', 'source', 'fdc_id', 'serving_desc', 'serving_g', 'gtin', 'source_license', 'source_url'];
  const LAB_COLUMNS = ['id', 'analyte', 'value', 'unit', 'entered_value', 'entered_unit', 'taken_on', 'note', 'created_at'];
  const SYMPTOM_COLUMNS = ['id', 'date', 'symptom', 'label', 'severity', 'note', 'created_at'];
  const WEIGHT_COLUMNS = ['id', 'date', 'time', 'kg', 'context', 'note', 'source', 'source_key', 'created_at', 'updated_at'];
  const READING_COLUMNS = ['id', 'date', 'time', 'systolic', 'diastolic', 'pulse', 'context', 'note', 'source', 'source_key', 'created_at', 'updated_at'];
  const DAY_COLUMNS = ['date', 'kcal', 'strain', 'recovery_pct', 'resting_hr', 'hrv_ms', 'sleep_minutes', 'sleep_performance_pct', 'finished', 'source'];
  const WORKOUT_COLUMNS = ['date', 'start_time', 'end_time', 'minutes', 'sport', 'kcal', 'strain', 'source'];
  const pick = (names) => (row) => names.map((k) => (row[k] === undefined ? null : row[k]));

  // account.README, word for word (tests/data/export_vectors.json holds the server's text).
  function readme(name = KH.brand.name, format = KH.brand.exportFormat) {
    const title = `${name} export`;
    return `${title}
${'='.repeat(title.length)}

This archive holds everything this server stores about your account, in two forms:

* export.json  - every record, in a documented JSON format ("${format}", version 1). To move
                 to another server, unzip it, then use Settings > Account > Your data > "Import from a
                 file" on the new server and choose export.json.
* log.csv      - your food log (eaten and planned entries) with the nutrient snapshot of each entry.
* foods.csv    - foods you created, and shared foods you imported or scanned.
* meals.csv    - your saved meals, one line per food.
* labs.csv     - your lab results (empty if you have none).
* symptoms.csv - the symptoms you recorded, with date and severity (1 mild, 2 moderate, 3 severe; empty if none).
* weights.csv  - the weights you recorded, in kilograms, with the date, time and when they were taken (empty if none).
* blood_pressure.csv - the blood pressure readings you recorded: top number (systolic) and bottom number (diastolic) in mmHg,
                 pulse, date, time and when they were taken (empty if none).
* activity.csv - your days from Whoop: calories burned, strain, recovery, resting heart rate, HRV, sleep (empty if none).
* workouts.csv - your workouts from Whoop: date, start, end, sport, calories burned, strain (empty if none).

export.json also holds your food preferences (the foods you marked More like this, Less often or Not for me,
and the foods where you switched off what the app learned from your log; the food groups you chose are in
"settings"), your AI activity (what the app sent to an AI provider for you and what came back, for as long as
the server keeps it; never photos), your daily AI call counts and the AI providers you agreed to send data to.

What is NOT in it: your password, your sign-in sessions, your assistant access tokens, your phone shortcut tokens and any
API keys you stored (not even part of them). The person who runs the server keeps backups of the
whole database; deleting your account does not reach those backups until they expire.

Where a food's data came from is in the "source" and "source_license" columns. Rows marked ODbL-1.0
contain information from Open Food Facts (https://world.openfoodfacts.org), which is made available
under the Open Database License (https://opendatacommons.org/licenses/odbl/1-0/). Rows marked CC0-1.0
come from USDA FoodData Central (public domain).

The numbers are what the app recorded. They are not medical advice; talk to your kidney team or
dietitian about your targets.
`;
  }

  // build_export without export.json: [[name, text], ...] in the archive's order. `source(foodId)` gives [source, source_license]
  // of the food an entry uses (log.csv reads them from the food row, which the document does not repeat for built-in foods).
  function csvFiles(doc, source) {
    const entries = (doc.log_entries || []).map((e) => {
      const [src, lic] = source(e.food_id) || [null, null];
      return [e.id, e.date, e.meal, e.status, e.food_id, e.food_name, e.servings, e.grams, e.note,
        ...R.NUTRIENT_KEYS.map((k) => (e.nutrients || {})[k]), e.created_at, e.updated_at, e.purpose, src, lic];
    });
    const foods = [...(doc.custom_foods || []), ...(doc.linked_foods || []).map((l) => l.food)].map((f) => [
      ...FOOD_FIELDS.map((k) => (f[k] === undefined ? null : f[k])), ...R.NUTRIENT_KEYS.map((k) => (f.nutrients || {})[k]),
      (f.flags || []).join(' '), f.kidney_notes]);
    const foodCols = [...plainCols(FOOD_FIELDS, { serving_g: 'f' }), ...NUT_COLS(), ...plainCols(['flags', 'kidney_notes'])];
    const meals = [];
    for (const m of doc.meal_templates || []) {
      for (const it of (m.items && m.items.length ? m.items : [{}])) meals.push([m.id, m.name, m.note, it.food_id, it.food_name, it.servings]);
    }
    return [
      ['log.csv', csv(LOG_COLS(), entries)],
      ['foods.csv', csv(foodCols, foods)],
      ['meals.csv', csv(plainCols(['meal_id', 'meal_name', 'note', 'food_id', 'food_name', 'servings'], { servings: 'f' }), meals)],
      ['labs.csv', csv(plainCols(LAB_COLUMNS, { value: 'f', entered_value: 'f' }), (doc.lab_results || []).map(pick(LAB_COLUMNS)))],
      ['symptoms.csv', csv(plainCols(SYMPTOM_COLUMNS), (doc.symptoms || []).map(pick(SYMPTOM_COLUMNS)))],
      ['weights.csv', csv(plainCols(WEIGHT_COLUMNS, { kg: 'f' }), (doc.weights || []).map(pick(WEIGHT_COLUMNS)))],
      ['blood_pressure.csv', csv(plainCols(READING_COLUMNS), (doc.blood_pressures || []).map(pick(READING_COLUMNS)))],
      ['activity.csv', csv(plainCols(DAY_COLUMNS, { strain: 'f', hrv_ms: 'f', finished: 'b' }), (doc.activity_days || []).map(pick(DAY_COLUMNS)))],
      ['workouts.csv', csv(plainCols(WORKOUT_COLUMNS, { strain: 'f' }), (doc.activity_workouts || []).map(pick(WORKOUT_COLUMNS)))],
    ];
  }

  // UTF-8 bytes, without TextEncoder where the page has none.
  function utf8(text) {
    if (typeof TextEncoder === 'function') return new TextEncoder().encode(text);
    const bin = unescape(encodeURIComponent(text));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }
  let CRC_TABLE = null;
  function crc32(bytes) {
    if (!CRC_TABLE) {
      CRC_TABLE = new Uint32Array(256);
      for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; CRC_TABLE[n] = c >>> 0; }
    }
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  // A .zip of [[name, text], ...]: STORE (method 0), a CRC-32 each, the time in UTC as the server writes it. No zip64: refused
  // above 4 GiB or 65,535 files (an export is far smaller).
  function zip(files, when = new Date()) {
    const time = (when.getUTCHours() << 11) | (when.getUTCMinutes() << 5) | (when.getUTCSeconds() >> 1);
    const date = ((Math.max(1980, when.getUTCFullYear()) - 1980) << 9) | ((when.getUTCMonth() + 1) << 5) | when.getUTCDate();
    const parts = [];
    const central = [];
    let offset = 0;
    for (const [name, text] of files) {
      const nameBytes = utf8(name);
      const data = typeof text === 'string' ? utf8(text) : text;
      const crc = crc32(data);
      const utf8Flag = /^[\x20-\x7e]*$/.test(name) ? 0 : 0x0800;
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 10, true); local.setUint16(6, utf8Flag, true); local.setUint16(8, 0, true);
      local.setUint16(10, time, true); local.setUint16(12, date, true); local.setUint32(14, crc, true);
      local.setUint32(18, data.length, true); local.setUint32(22, data.length, true); local.setUint16(26, nameBytes.length, true); local.setUint16(28, 0, true);
      const dir = new DataView(new ArrayBuffer(46));
      dir.setUint32(0, 0x02014b50, true); dir.setUint16(4, 20, true); dir.setUint16(6, 10, true); dir.setUint16(8, utf8Flag, true); dir.setUint16(10, 0, true);
      dir.setUint16(12, time, true); dir.setUint16(14, date, true); dir.setUint32(16, crc, true); dir.setUint32(20, data.length, true);
      dir.setUint32(24, data.length, true); dir.setUint16(28, nameBytes.length, true); dir.setUint32(38, 0o100644 * 65536, true);
      dir.setUint32(42, offset, true);
      parts.push(new Uint8Array(local.buffer), nameBytes, data);
      central.push(new Uint8Array(dir.buffer), nameBytes);
      offset += 30 + nameBytes.length + data.length;
      if (offset > 0xFFFFFFFF || files.length > 0xFFFF) throw new Error('The export is too large for one file.');
    }
    const dirSize = central.reduce((n, b) => n + b.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, dirSize, true); end.setUint32(16, offset, true);
    const all = [...parts, ...central, new Uint8Array(end.buffer)];
    const out = new Uint8Array(all.reduce((n, b) => n + b.length, 0));
    let at = 0;
    for (const b of all) { out.set(b, at); at += b.length; }
    return out;
  }
  // account.export_filename: "<slug>-<username, safe>-<UTC day>.zip".
  function filename(username, when = new Date()) {
    const safe = Array.from(String(username || '')).map((ch) => (/^[\p{L}\p{Nd}\p{Nl}\p{No}._-]$/u.test(ch) ? ch : '-')).slice(0, 40).join('') || 'account';
    return `${KH.brand.slug}-${safe}-${when.toISOString().slice(0, 10)}.zip`;
  }

  Object.assign(MockApi.prototype, {
    // The server's GET /api/me/export.zip, built here: { name, bytes (Uint8Array), files }. Audited as the server does.
    _exportArchive(when = new Date()) {
      const doc = this._exportDocument();
      const source = (id) => { const f = this._food(id); return f ? [f.source || null, f.source_license || null] : null; };
      const files = [['export.json', JSON.stringify(doc, null, 2)], ...csvFiles(doc, source), ['README.txt', readme()]];
      const bytes = zip(files, when);
      const u = this._currentUser();
      this._audit(u.id, 'export.created', 'user', u.id, { bytes: bytes.length });
      return { name: filename(u.username, when), bytes, files };
    },
  });

  route('GET', '/api/me/export.json', function () {
    const doc = this._exportDocument();
    this._audit(this._currentUser().id, 'export.created', 'user', this._currentUser().id, { bytes: JSON.stringify(doc).length });
    return doc;
  });

  M.exportZip = { csvSafe, cell, csv, csvFiles, readme, crc32, zip, filename, FORMULA_PREFIXES };
  Object.assign(M, { EXPORT_FORMAT, EXPORT_VERSION });
})();
