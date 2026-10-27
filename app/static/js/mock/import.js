/* Kidney Diet Log — demo API: import of a person's own export.json (twin of app/data_import.py).

   POST /api/me/import?dry_run=1&merge=1&replace_profile=1 takes the export.json that GET /api/me/export.json (js/mock/export.js)
   or a server's GET /api/me/export.zip holds, and answers like the server: the same refusals in the same words for a file that is
   not an export, one record that is not valid (the first problem, named by record kind and position, never repeating a value
   back), the same duplicate rules, the same "never imported" list. A dry run counts and keeps nothing.

   The file is untrusted input. Strict shape: every record kind is a small schema below (the server's pydantic models with
   extra="forbid" and strict types), checked in the same order, so the FIRST problem is the same one. Never imported, even when
   present: the user section, passwords, sessions, tokens, AI keys, providers, consents, usage and activity; `settings` carries over
   only the four IMPORTED_SETTINGS and only with replace_profile (`ai` and the consents never). Depth limit 32, body limit 16 MiB.

   Parity: tests/data/import_vectors.json (tests/data/gen_import_vectors.py runs a request script against the real server) is
   replayed against this file by `node tests/js/run_vectors.mjs` ("import" section). Known differences, because the browser has
   already parsed the file with JSON.parse: a float written 2.0 is the integer 2 here (strict integer fields accept it), an integer
   beyond 2**53 is rounded, and case folding uses toLowerCase (the server's casefold also maps the German sharp s). */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  const { route, MockApi, fail } = M;
  const R = KH.rules;
  const { NUTRIENT_KEYS, pyRound } = R;

  const EXPORT_FORMAT = KH.brand.exportFormat;
  const SUPPORTED_VERSION = 1;
  const MAX_ENTRIES = 30000, MAX_CUSTOM_FOODS = 5000, MAX_LINKED_FOODS = 5000, MAX_BUILTIN_REFS = 5000, MAX_MEALS = 1000, MAX_MEAL_ITEMS = 100;
  const MAX_LABS = 5000, MAX_SYMPTOMS = 20000, MAX_WEIGHTS = 20000, MAX_BLOOD_PRESSURES = 20000, MAX_SETTINGS = 200, MAX_SKIPPED_SHOWN = 100, MAX_MESSAGE_CHARS = 200, MAX_NOTE_CHARS = 1000;
  const MAX_NOT_FOR_ME = 500;
  const MAX_FOOD_PREFERENCES = 1000;
  const MAX_DEPTH = 32;
  const MAX_IMPORT_BYTES = 16 * 1024 * 1024;
  const MIN_SERVING_G = 0.1, MAX_SERVING_G = 100000, MAX_SERVINGS = 1000, MAX_GRAMS = 100000, MAX_NUTRIENT_VALUE = 1000000;
  const IMPORTED_SETTINGS = ['guidance', 'ui.theme', 'user.units.labs', 'food.scan_prefer_camera', 'user.units.weight', 'body.weight_alarm', 'body.bp_goal'];
  const SKIPPED_SECTIONS = ['user', 'ai_audit', 'activity', 'ai_usage', 'ai_consents', 'ai_provider'];
  const NOT_IMPORTED = [
    'Your username, password and sign-in sessions',
    'Assistant access tokens and any API keys (an export never holds them; a file that does is ignored)',
    'AI activity, AI usage counts, the AI providers you agreed to send data to, and an AI provider of your own (agree to those again on this server)',
    'Your sign-in activity list',
    'Your Open Food Facts barcode choice and your AI ideas choice (they are consents; choose them again here)',
  ];
  const RULE = 'Your file\'s foods, log entries, saved meals, lab results, symptoms, weights, blood pressure readings and food preferences are added to this account. '
    + 'If the account already has entries, foods of your own, saved meals, lab results, symptoms, weights or blood pressure readings, nothing is imported unless you '
    + 'choose "Add to my existing data". Then whatever is already '
    + 'here is left out: an entry with the same date, meal, food, amount, status and time; a food of yours with the same name, serving and values; a saved meal with '
    + 'the same name and foods; a lab result with the same test, date and value; a symptom with the same date, name, severity and note; a weight or blood pressure '
    + 'reading that came from an import and has the same key, or one you typed with the same date, time, numbers, circumstances and note. So importing the same file '
    + 'again adds nothing. Your profile, targets and settings are replaced only if you choose "Also replace my profile, targets and settings".';
  const COUNT_KEYS = ['log_entries', 'custom_foods', 'shared_foods_kept_as_own', 'shared_foods_linked', 'built_in_foods_matched', 'meal_templates', 'lab_results',
    'symptoms', 'weights', 'blood_pressures', 'food_preferences', 'profile', 'settings'];
  const ALREADY_KEYS = ['log_entries', 'custom_foods', 'shared_foods_linked', 'meal_templates', 'lab_results', 'symptoms', 'weights', 'blood_pressures', 'food_preferences'];
  const TOO_DEEP = `This is not a ${KH.brand.name} export: the file is nested too deeply.`;
  const NOT_FINITE = 'The file holds a value that is not a finite number (NaN, Infinity or too large). A real export never does; nothing was imported.';
  const GAVE_UP = 'The file was not imported. ';

  class Refused extends Error {
    constructor(message, kind = null, index = null) { super(message); this.kind = kind; this.index = index; }
  }
  // The first problem a schema finds: where (the pydantic loc) and what.
  class Bad extends Error { constructor(loc, msg) { super(msg); this.loc = loc; this.msg = msg; } }

  const CTRL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g;
  const chars = (s) => Array.from(s);
  const clip = (s, n) => { const c = chars(s); return c.length <= n ? s : `${c.slice(0, n - 1).join('')}…`; };
  // importer.short: a value from the file made safe to show: control characters out, cut at `limit`.
  function short(text, limit = 60) { return clip(String(text).replace(CTRL, ' ').trim(), limit); }
  // Python str.strip(): the characters str.isspace() accepts (js/mock/symptoms.js has the same).
  const PY_SPACE = '\\t\\n\\u000b\\u000c\\r\\u001c-\\u001f \\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
  const PY_STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, 'g');
  const pyStrip = (s) => s.replace(PY_STRIP, '');
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);

  // ---------------------------------------------------------------------------
  // Field checks (pydantic strict mode): each returns the cleaned value or throws Bad(loc, message)
  // ---------------------------------------------------------------------------
  const TS_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
  // import.parse_timestamp: 2000 to one day ahead; returned in the fixed form the database uses.
  function parseTimestamp(value) {
    if (typeof value !== 'string' || !TS_RE.test(value)) throw new Error('must be a UTC time such as 2026-10-05T12:30:00.123456Z');
    const [date, rest] = value.slice(0, -1).split('T');
    const [clock, frac = ''] = rest.split('.');
    const [y, mo, d] = date.split('-').map(Number);
    const [h, mi, s] = clock.split(':').map(Number);
    const t = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
    if (mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || s > 59 || t.getUTCFullYear() !== y || t.getUTCMonth() !== mo - 1 || t.getUTCDate() !== d) {
      throw new Error('is not a valid time');
    }
    if (y < 2000 || t.getTime() + Number(`0.${frac || '0'}`) * 1000 > Date.now() + 86400000) throw new Error('must be between the year 2000 and tomorrow');
    return `${date}T${clock}.${frac.padEnd(6, '0')}Z`;
  }
  const OFF_PAGE = /^https:\/\/world\.openfoodfacts\.org\/product\/\d{8,14}$/;
  const USDA_HOME_URL = 'https://fdc.nal.usda.gov/';
  const LICENSES = ['ODbL-1.0', 'CC0-1.0', 'CC0-1.0 AND ODbL-1.0'];

  const T = {
    str({ strip = false, min = 0, max = Infinity, nullable = false, after = null } = {}) {
      return (v, loc) => {
        if (v == null && nullable) return null;
        if (typeof v !== 'string') throw new Bad(loc, 'Input should be a valid string');
        const s = strip ? pyStrip(v) : v;
        const n = chars(s).length;
        if (n < min) throw new Bad(loc, `String should have at least ${min} character${min === 1 ? '' : 's'}`);
        if (n > max) throw new Bad(loc, `String should have at most ${max} characters`);
        return after ? run(after, s, loc) : s;
      };
    },
    int({ ge = null, le = null } = {}) {
      // a JS number cannot hold 2**63 - 1: a bound that large is the database's, written as the server writes it
      const shown = (n) => (Math.abs(n) >= 2 ** 63 ? `${n < 0 ? '-' : ''}9223372036854775807` : String(n));
      return (v, loc) => {
        if (typeof v !== 'number' || !Number.isInteger(v)) throw new Bad(loc, 'Input should be a valid integer');
        if (ge != null && (v < ge || (Math.abs(ge) >= 2 ** 63 && v <= ge))) throw new Bad(loc, `Input should be greater than or equal to ${shown(ge)}`);
        if (le != null && (v > le || (Math.abs(le) >= 2 ** 63 && v >= le))) throw new Bad(loc, `Input should be less than or equal to ${shown(le)}`);
        return v;
      };
    },
    num({ gt = null, ge = null, le = null, nullable = false } = {}) {
      return (v, loc) => {
        if (v == null && nullable) return null;
        if (typeof v !== 'number') throw new Bad(loc, 'Input should be a valid number');
        if (!Number.isFinite(v)) throw new Bad(loc, 'Input should be a finite number');
        if (gt != null && !(v > gt)) throw new Bad(loc, `Input should be greater than ${gt}`);
        if (ge != null && !(v >= ge)) throw new Bad(loc, `Input should be greater than or equal to ${ge}`);
        if (le != null && !(v <= le)) throw new Bad(loc, `Input should be less than or equal to ${le}`);
        return v;
      };
    },
    bool() { return (v, loc) => { if (typeof v !== 'boolean') throw new Bad(loc, 'Input should be a valid boolean'); return v; }; },
    lit(options, { nullable = false } = {}) {
      return (v, loc) => {
        if (v == null && nullable) return null;
        if (!options.includes(v)) throw new Bad(loc, M.choiceMessage(options));
        return v;
      };
    },
    // a dict[str, Any] followed by a value check that reports through `after`
    dict(after = null) {
      return (v, loc) => {
        if (!isDict(v)) throw new Bad(loc, 'Input should be a valid dictionary');
        return after ? run(after, v, loc) : v;
      };
    },
    list(item, { max = Infinity, after = null } = {}) {
      return (v, loc) => {
        if (!Array.isArray(v)) throw new Bad(loc, 'Input should be a valid list');
        if (v.length > max) throw new Bad(loc, `List should have at most ${max} items after validation, not ${v.length}`);
        const out = v.map((x, i) => item(x, [...loc, i]));
        return after ? run(after, out, loc) : out;
      };
    },
    // [name, check, { required }]; extra keys are refused after the fields (extra="forbid"); `after(record)` runs only when every field passed
    model(name, fields, { after = null } = {}) {
      const names = fields.map((f) => f[0]);
      return (v, loc) => {
        if (!isDict(v)) throw new Bad(loc, `Input should be a valid dictionary or instance of ${name}`);
        const out = {};
        for (const [name, check, { required = false } = {}] of fields) {
          if (!Object.prototype.hasOwnProperty.call(v, name)) { if (required) throw new Bad([...loc, name], 'Field required'); continue; }
          out[name] = check(v[name], [...loc, name]);
        }
        for (const key of Object.keys(v)) if (!names.includes(key)) throw new Bad([...loc, key], 'unknown field; this server does not read it');
        return after ? run(after, out, loc) : out;
      };
    },
  };
  // A validator written as (value) => value that throws Error(message) for "Value error": reported at `loc`.
  function run(fn, value, loc) {
    try { return fn(value); } catch (e) { if (e instanceof Bad) throw e; throw new Bad(loc, e.message); }
  }
  const required = { required: true };
  const nullableStr = (opts) => T.str({ ...opts, nullable: true });
  const short$ = (n, min = 0, nullable = false) => T.str({ strip: true, min, max: n, nullable });
  const ID = T.int({ ge: 1, le: 2 ** 63 - 1 });
  const idOrNull = (v, loc) => (v == null ? null : ID(v, loc));
  // FdcId (data_import.py): a curated built-in food (glucose tablets, salt substitutes) has a negative number of its own
  const FDC = T.int({ ge: -(2 ** 63 - 1), le: 2 ** 63 - 1 });
  const fdcOrNull = (v, loc) => (v == null ? null : FDC(v, loc));
  const TS = T.str({ max: 40, after: parseTimestamp });
  const tsOrNull = T.str({ max: 40, nullable: true, after: parseTimestamp });
  const RATING = T.lit(['green', 'yellow', 'red']);
  const MEALS = T.lit(R.MEAL_KEYS);
  const STATUS = T.lit(['eaten', 'planned']);

  // import.checked_nutrients: validate_nutrients without repeating the names of nutrients it does not know.
  function checkedNutrients(values) {
    const errors = [];
    const out = M.validateNutrients(values, errors);
    if (errors.length) {
      const msg = errors[0].replace(/^nutrients: /, '');
      throw new Error(/^unknown nutrient/.test(msg) ? 'has a nutrient this server does not know' : msg);
    }
    return out;
  }
  function checkedFlags(flags) {
    const errors = [];
    const out = M.validateFlags(flags.map((f) => f), errors);
    if (errors.length) throw new Error(errors[0].replace(/^flags: /, ''));
    return out;
  }
  const flagList = (v, loc) => {
    if (!Array.isArray(v)) throw new Bad(loc, 'Input should be a valid list');
    if (v.length > 60) throw new Bad(loc, `List should have at most 60 items after validation, not ${v.length}`);
    const items = v.map((x, i) => { if (typeof x !== 'string') throw new Bad([...loc, i], 'Input should be a valid string'); return x; });
    return run(checkedFlags, items, loc);
  };
  const validateGtin = (v) => {
    if (v == null || (typeof v === 'string' && !v.trim())) return null;
    try { return KH.gtin.normalize(v, 'unknown'); } catch (e) { if (e instanceof KH.gtin.GtinError) throw new Error(e.message); throw e; }
  };
  const gtinField = T.str({ max: 32, nullable: true, after: validateGtin });
  const validateClientId = (v) => {
    if (v == null) return null;
    if (!/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(v)) throw new Error('must be a UUID such as 0f8fad5b-d9cb-469f-a165-70867728950e');
    return v.toLowerCase();
  };
  const validateDate = (v) => { const e = M.validDate(v); if (e) throw new Error(e); return v; };

  const warningModel = T.model('ImportWarning', [['nutrient', short$(40, 0, true)], ['level', T.lit(['medium', 'high']), required], ['value', T.num({ nullable: true })],
    ['flag', short$(40, 0, true)], ['message', short$(1500), required]]);
  const qualityModel = T.model('ImportQuality', [['code', short$(80), required], ['message', short$(400), required]]);
  const foodModel = T.model('ImportFood', [
    ['id', ID, required], ['name', short$(200, 1), required], ['brand', short$(200, 0, true)], ['category', short$(100, 0, true)],
    ['source', T.lit(['custom', 'usda', 'off']), required], ['fdc_id', fdcOrNull], ['serving_desc', short$(200, 1), required],
    ['serving_g', T.num({ ge: MIN_SERVING_G, le: MAX_SERVING_G }), required], ['nutrients', T.dict(checkedNutrients), required],
    ['flags', flagList, required], ['kidney_notes', short$(1000, 0, true)], ['hidden', T.bool(), required],
    ['warnings', T.list(warningModel, { max: 40 }), required], ['kidney_rating', RATING, required], ['gtin', gtinField],
    ['source_url', T.str({ max: 200, nullable: true, after: (v) => { if (v === USDA_HOME_URL || OFF_PAGE.test(v)) return v; throw new Error('must be an Open Food Facts product page or the FoodData Central address'); } })],
    ['source_license', T.str({ max: 40, nullable: true, after: (v) => { if (LICENSES.includes(v)) return v; throw new Error('is not a licence this app writes'); } })],
    ['quality', T.list(qualityModel, { max: 30 }), required], ['additives', T.list(short$(40), { max: 40 }), required], ['ingredients_text', short$(4000, 0, true)],
  ]);
  const linkedModel = T.model('ImportLinkedFood', [['id', ID, required], ['name', short$(200), required], ['source', T.lit(['usda', 'off']), required], ['fdc_id', idOrNull],
    ['linked_at', tsOrNull], ['gtin', gtinField], ['food', (v, loc) => (v == null ? null : foodModel(v, loc))]], {
    after: (r) => { if (r.food != null && (r.food.id !== r.id || r.food.source !== r.source)) throw new Error('food does not describe this food (id or source differ)'); return r; } });
  const builtinRefModel = T.model('ImportBuiltinRef', [['id', ID, required], ['name', short$(200, 1), required], ['fdc_id', fdcOrNull]]);
  const entryModel = T.model('ImportEntry', [
    ['id', ID, required], ['date', T.str({ after: validateDate }), required], ['meal', MEALS, required], ['food_id', ID, required], ['food_name', short$(200, 1), required],
    ['servings', T.num({ gt: 0, le: MAX_SERVINGS }), required], ['grams', T.num({ gt: 0, le: MAX_GRAMS, nullable: true })], ['note', short$(500, 0, true)],
    ['status', STATUS, required], ['nutrients', T.dict(checkedNutrients), required], ['warnings', T.list(warningModel, { max: 40 }), required],
    ['kidney_rating', RATING, required], ['purpose', T.lit(['hypo'], { nullable: true })], ['client_id', T.str({ nullable: true, after: validateClientId })],
    ['created_at', TS, required], ['updated_at', TS, required], ['version', short$(64, 0, true)],
  ]);
  const mealItemModel = T.model('ImportMealItem', [['food_id', ID, required], ['food_name', short$(200), required], ['servings', T.num({ gt: 0, le: MAX_SERVINGS }), required],
    ['serving_desc', short$(200), required], ['nutrients', T.dict(checkedNutrients), required], ['kidney_rating', RATING, required], ['hidden', T.bool(), required]]);
  const mealModel = T.model('ImportMeal', [['id', ID, required], ['name', short$(200, 1), required], ['note', short$(1000, 0, true)], ['meal_hint', T.lit(R.MEAL_KEYS, { nullable: true })],
    ['items', T.list(mealItemModel, { max: MAX_MEAL_ITEMS }), required], ['totals', T.dict(checkedNutrients), required], ['kidney_rating', RATING, required],
    // A recipe (schema step 21); an export from before it has none of these. per_serving and unknown are worked out again.
    ['servings_made', T.num({ gt: 0, le: 100, nullable: true })],
    ['steps', (v, loc) => (v == null ? null : T.list(short$(500, 1), { max: 20 })(v, loc))],
    ['source_url', T.str({ strip: true, min: 1, max: 900, nullable: true, after: (v) => { const e = M.checkSourceUrl(v); if (e) throw new Error(e.replace(/^Value error, /, '')); return v; } })],
    ['per_serving', (v, loc) => (v == null ? null : T.dict()(v, loc))], ['unknown', (v, loc) => (v == null ? null : T.dict()(v, loc))],
    ['created_at', TS, required], ['updated_at', TS, required]]);

  // A model the demo API already checks for a request body (LabCreate, SymptomCreate): the first problem it finds, as "where: message"
  // cut at 120 characters, which is how the server words it (import._as_typed, _as_recorded).
  function viaRequestBody(check, fallbackWhere) {
    try { check(); } catch (e) {
      if (!(e instanceof M.ApiError)) throw e;
      const first = String(e.detail).split(/; (?=[A-Za-z_][A-Za-z_0-9.]*: )/)[0].replace(/^Value error, /, '');
      const has = /^[A-Za-z_][A-Za-z_0-9.]*: /.test(first);
      const where = has ? first.slice(0, first.indexOf(': ')) : fallbackWhere;
      const msg = has ? first.slice(first.indexOf(': ') + 2) : first;
      throw new Error(`${where}: ${chars(msg).slice(0, 120).join('')}`);
    }
  }
  const labModel = T.model('ImportLab', [
    ['id', ID, required], ['analyte', T.lit(KH.kidney.ANALYTE_KEYS), required], ['value', T.num({ ge: 0, le: MAX_NUTRIENT_VALUE }), required], ['unit', short$(40), required],
    ['entered_value', T.num({ ge: 0, le: MAX_NUTRIENT_VALUE }), required], ['entered_unit', short$(40), required], ['taken_on', T.str(), required],
    ['note', short$(500, 0, true)], ['created_at', TS, required]], {
    after: (r) => { viaRequestBody(() => M.instance._labBody({ analyte: r.analyte, value: r.entered_value, unit: r.entered_unit, taken_on: r.taken_on, note: r.note || '' }), 'result'); return r; } });
  const symptomModel = T.model('ImportSymptom', [
    ['id', ID, required], ['date', T.str(), required], ['symptom', T.lit(KH.symptomRules.KEYS), required], ['label', short$(KH.symptomRules.MAX_LABEL, 0, true)],
    ['severity', T.int({ ge: 1, le: 3 }), required], ['note', short$(KH.symptomRules.MAX_NOTE, 0, true)], ['created_at', TS, required]], {
    after: (r) => { viaRequestBody(() => M.instance._symptomBody({ date: r.date, symptom: r.symptom, severity: r.severity, label: r.label || '', note: r.note || '' }), 'symptom'); return r; } });
  // Weights and blood pressure readings (schema step 18): checked exactly like POST /api/body/weights and /blood-pressure; the id is never used.
  const BR = KH.bodyRules;
  const weightModel = T.model('ImportWeight', [
    ['id', ID, required], ['date', T.str(), required], ['time', T.str({ nullable: true })], ['kg', T.num({}), required],
    ['context', T.lit(BR.WEIGHT_CONTEXTS), required], ['note', short$(BR.LIMITS.max_note, 0, true)], ['source', T.lit(BR.SOURCES), required],
    ['source_key', short$(BR.LIMITS.max_source_key, 0, true)], ['created_at', TS, required], ['updated_at', TS, required]], {
    after: (r) => { viaRequestBody(() => M.instance._weightBody(weightRequest(r)), 'weight'); return r; } });
  const readingModel = T.model('ImportBloodPressure', [
    ['id', ID, required], ['date', T.str(), required], ['time', T.str({ nullable: true })], ['systolic', T.int({}), required], ['diastolic', T.int({}), required],
    ['pulse', (v, loc) => (v == null ? null : T.int({})(v, loc))], ['context', T.lit(BR.BLOOD_PRESSURE_CONTEXTS), required], ['note', short$(BR.LIMITS.max_note, 0, true)],
    ['source', T.lit(BR.SOURCES), required], ['source_key', short$(BR.LIMITS.max_source_key, 0, true)], ['created_at', TS, required], ['updated_at', TS, required]], {
    after: (r) => { viaRequestBody(() => M.instance._readingBody(readingRequest(r)), 'reading'); return r; } });
  const weightRequest = (r) => ({ date: r.date, time: r.time === undefined ? null : r.time, kg: r.kg, context: r.context, note: r.note || '' });
  const readingRequest = (r) => ({ date: r.date, time: r.time === undefined ? null : r.time, systolic: r.systolic, diastolic: r.diastolic,
    pulse: r.pulse === undefined ? null : r.pulse, context: r.context, note: r.note || '' });
  // A file from before schema step 17 holds only not_for_me rows without source and updated_at.
  const preferenceModel = T.model('ImportFoodPreference', [['food_id', ID, required], ['name', short$(200), required],
    ['preference', T.lit(['like', 'less', 'not_for_me', 'neutral']), required], ['created_at', TS, required],
    ['source', T.lit(['person', 'ask', 'assistant'], { nullable: true })], ['updated_at', tsOrNull]]);

  // The profile, as GET /api/profile shows it, checked like PUT /api/profile (strict types here, then the same rules as the route).
  const orNull = (check) => (v, loc) => (v == null ? null : check(v, loc));
  const PROFILE_TYPES = [
    ['name', T.str({ strip: true, max: 100, nullable: true })], ['weight_kg', T.num({ nullable: true })], ['height_cm', T.num({ nullable: true })],
    ['ckd_stage', T.lit(['1', '2', '3a', '3b', '4', '5'], { nullable: true })], ['dialysis', T.lit(['none', 'hemodialysis', 'peritoneal'], { nullable: true })],
    ['diabetes', T.lit(['none', 'type1', 'type2'], { nullable: true })], ['warn_fraction', T.num({ nullable: true })], ['about_tolerance_pct', orNull(T.int({}))],
    ['targets', orNull(T.dict())], ['dialysis_days', (v, loc) => { if (v != null && !Array.isArray(v)) throw new Bad(loc, 'Input should be a valid list'); return v; }],
    ['week_start', T.lit(['monday', 'sunday'], { nullable: true })], ['birth_month', T.str({ strip: true, nullable: true })],
    ['sex', T.lit(['female', 'male', 'unspecified'], { nullable: true })], ['activity', T.lit(['inactive', 'low_active', 'active', 'very_active'], { nullable: true })],
    ['transplant_date', T.str({ strip: true, nullable: true })], ['frail_or_sarcopenic', orNull(T.bool())],
    ['weight_6_months_ago_kg', T.num({ nullable: true })], ['pregnant_or_breastfeeding', orNull(T.bool())],
    ['hyperkalemia_history', orNull(T.bool())], ['urine_output_ml', T.num({ nullable: true })], ['pd_uf_ml', T.num({ nullable: true })],
    ['pd_dialysate_kcal', T.num({ nullable: true })],
    ['id', idOrNull], ['updated_at', T.str({ max: 40, nullable: true })], ['ckd_stage_chosen', T.bool()], ['diabetes_chosen', T.bool()],
  ];
  const V03_BLANK_IS_NULL = ['birth_month', 'sex', 'activity', 'transplant_date', 'frail_or_sarcopenic', 'weight_6_months_ago_kg', 'pregnant_or_breastfeeding',
    'hyperkalemia_history', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal'];
  const PROFILE_FIELDS = PROFILE_TYPES.map((f) => f[0]);
  function checkProfile(v, loc) {
    if (!isDict(v)) throw new Bad(loc, 'Input should be a valid dictionary or instance of ImportProfile');
    const body = { ...v };
    for (const k of V03_BLANK_IS_NULL) if (typeof body[k] === 'string' && !pyStrip(body[k])) body[k] = null; // ProfileUpdate._empty_is_null
    // 1. the strict type of every field, in the model's order; 2. the route's own rules (the lax check of PUT /api/profile), by field
    const typeProblems = new Map();
    for (const [name, check] of PROFILE_TYPES) {
      if (!Object.prototype.hasOwnProperty.call(body, name)) continue;
      try { check(body[name], [...loc, name]); } catch (e) { if (!(e instanceof Bad)) throw e; typeProblems.set(name, e); }
    }
    let ruleProblems = [];
    const scratch = new MockApi({ foodsData: null, seed: false });
    try {
      const probe = { ...body };
      for (const k of ['id', 'updated_at', 'ckd_stage_chosen', 'diabetes_chosen']) delete probe[k];
      scratch._updateProfile(probe);
    } catch (e) {
      if (!(e instanceof M.ApiError)) throw e;
      ruleProblems = String(e.detail).split(/; (?=[A-Za-z_][A-Za-z_0-9.]*: )/);
    }
    for (const name of PROFILE_FIELDS) {
      if (typeProblems.has(name)) throw typeProblems.get(name);
      const hit = ruleProblems.find((p) => p.startsWith(`${name}: `) || p.startsWith(`${name}.`));
      if (hit) {
        const msg = hit.slice(hit.indexOf(': ') + 2);
        // an unknown key inside a target range is "extra_forbidden" of the server's own Range model, worded like every unknown field
        throw new Bad([...loc, ...hit.split(': ')[0].split('.')], msg === 'Extra inputs are not permitted' ? 'unknown field; this server does not read it' : msg);
      }
    }
    for (const key of Object.keys(v)) if (!PROFILE_FIELDS.includes(key)) throw new Bad([...loc, key], 'unknown field; this server does not read it');
    return v;
  }

  // ExportFile.settings: at most 200 keys; the four carried over must hold a value this server accepts.
  function checkSettings(v, loc) {
    if (!isDict(v)) throw new Bad(loc, 'Input should be a valid dictionary');
    const keys = Object.keys(v);
    if (keys.length > MAX_SETTINGS) throw new Bad(loc, `Dictionary should have at most ${MAX_SETTINGS} items after validation, not ${keys.length}`);
    for (const key of keys) {
      if (chars(key).length > 100) throw new Bad(loc, 'a setting name is too long');
      if (IMPORTED_SETTINGS.includes(key)) {
        const def = KH.settings.BY_KEY[key];
        const r = def ? KH.settings.validate(def, v[key]) : { error: 'unknown' };
        if (!def || r.error !== undefined) throw new Bad(loc, `${key}: not a value this server accepts`);
      }
    }
    return v;
  }
  const kind = (name, check, max) => [name, (v, loc) => {
    if (!Array.isArray(v)) throw new Bad(loc, 'Input should be a valid list');
    if (v.length > max) throw new Bad(loc, `List should have at most ${max} items after validation, not ${v.length}`);
    return v.map((x, i) => check(x, [...loc, i]));
  }];
  const EXPORT_FILE = T.model('ExportFile', [
    ['format', T.lit([EXPORT_FORMAT]), required], ['version', T.lit([SUPPORTED_VERSION]), required], ['exported_at', tsOrNull], ['app_version', short$(40, 0, true)],
    ['profile', (v, loc) => (v == null ? null : checkProfile(v, loc))], ['settings', checkSettings],
    kind('log_entries', entryModel, MAX_ENTRIES), kind('custom_foods', foodModel, MAX_CUSTOM_FOODS), kind('linked_foods', linkedModel, MAX_LINKED_FOODS),
    kind('builtin_foods', builtinRefModel, MAX_BUILTIN_REFS), kind('meal_templates', mealModel, MAX_MEALS), kind('lab_results', labModel, MAX_LABS),
    kind('symptoms', symptomModel, MAX_SYMPTOMS), kind('weights', weightModel, MAX_WEIGHTS), kind('blood_pressures', readingModel, MAX_BLOOD_PRESSURES),
    kind('food_preferences', preferenceModel, MAX_FOOD_PREFERENCES),
    ...SKIPPED_SECTIONS.map((name) => [name, (v) => v]),
  ], {
    after: (doc) => {
      (doc.custom_foods || []).forEach((food, i) => { if (food.source !== 'custom') throw new Error(`custom_foods[${i}].source: must be custom`); });
      return doc;
    } });

  // import._where / _refusal
  function refusal(bad) {
    let text = '';
    let knd = null;
    let index = null;
    bad.loc.forEach((part, n) => {
      if (typeof part === 'number') { text += `[${part}]`; if (n === 1) index = part; } else {
        const name = String(part).slice(0, 40);
        text += text ? `.${name}` : name;
        if (n === 0) knd = name;
      }
    });
    const message = short(bad.msg, MAX_MESSAGE_CHARS);
    return new Refused(text ? `${text}: ${message}` : message, knd, index);
  }

  // json.loads(parse_constant=…, parse_float=…) refuses what JSON.parse turned into Infinity; nested_deeper_than has no recursion.
  function nonFinite(value) {
    const stack = [value];
    while (stack.length) {
      const item = stack.pop();
      if (typeof item === 'number') { if (!Number.isFinite(item)) return true; } else if (Array.isArray(item)) { for (const v of item) stack.push(v); } // no spread: a long list must not overflow the call
      else if (isDict(item)) { for (const v of Object.values(item)) stack.push(v); }
    }
    return false;
  }
  function nestedDeeperThan(value, limit) {
    const stack = [[value, 1]];
    while (stack.length) {
      const [item, depth] = stack.pop();
      if (depth > limit) return true;
      if (Array.isArray(item)) for (const v of item) stack.push([v, depth + 1]);
      else if (isDict(item)) for (const v of Object.values(item)) stack.push([v, depth + 1]);
    }
    return false;
  }
  function parseExport(data) {
    if (nonFinite(data)) throw new Refused(NOT_FINITE);
    if (nestedDeeperThan(data, MAX_DEPTH)) throw new Refused(TOO_DEEP);
    if (!isDict(data)) throw new Refused(`This is not a ${KH.brand.name} export: the file must hold one JSON object.`);
    if (data.format !== EXPORT_FORMAT) throw new Refused(`This is not a ${KH.brand.name} export (its "format" is not "${EXPORT_FORMAT}").`);
    const version = data.version;
    if (typeof version === 'boolean' || version !== SUPPORTED_VERSION) {
      const shown = typeof version === 'boolean' ? (version ? 'True' : 'False') : typeof version === 'number' || typeof version === 'string' ? short(version, 20) : 'unknown';
      throw new Refused(`This export is version ${shown} of the format; this server reads version ${SUPPORTED_VERSION}. Export again from a server of the same release, or update this one.`);
    }
    let doc;
    try { doc = EXPORT_FILE(data, []); } catch (e) { if (e instanceof Bad) throw refusal(e); throw e; }
    for (const key of ['settings']) if (doc[key] === undefined) doc[key] = {};
    for (const [key] of [['log_entries'], ['custom_foods'], ['linked_foods'], ['builtin_foods'], ['meal_templates'], ['lab_results'], ['symptoms'], ['weights'], ['blood_pressures'], ['food_preferences']]) {
      if (doc[key] === undefined) doc[key] = [];
    }
    if (doc.profile === undefined) doc.profile = null;
    return doc;
  }
  function checkIds(doc) {
    const seen = new Map();
    for (const knd of ['custom_foods', 'linked_foods', 'builtin_foods']) {
      doc[knd].forEach((item, index) => {
        if (seen.has(item.id)) {
          const other = seen.get(item.id);
          throw new Refused(`${knd}[${index}].id: the same food id is used twice (also in ${other === knd ? 'this list' : other})`, knd, index);
        }
        seen.set(item.id, knd);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Importing it (the Importer class of app/data_import.py over the demo's tables)
  // ---------------------------------------------------------------------------
  const asciiLower = M.asciiLower;
  const fold = (s) => String(s).toLowerCase();
  const countOf = () => new Map();
  const bump = (map, key, n = 1) => map.set(key, (map.get(key) || 0) + n);
  const tupleKey = (...parts) => JSON.stringify(parts);

  class Blocked extends Error { constructor(existing) { super('account_not_empty'); this.existing = existing; this.summary = null; } }

  class Importer {
    constructor(api, doc, { merge, replaceProfile }) {
      this.api = api; this.doc = doc; this.merge = merge; this.replaceProfile = replaceProfile;
      this.userId = api._currentUser().id;
      this.counts = new Map(); this.already = new Map(); this.skippedByKind = new Map(); this.skipped = [];
      this.foodMap = new Map(); this.unmatched = new Map(); this.notSelected = [];
    }
    skip(knd, index, label, reason) {
      bump(this.skippedByKind, knd);
      if (this.skipped.length < MAX_SKIPPED_SHOWN) this.skipped.push({ kind: knd, index, label: short(label), reason });
    }
    existingCounts() {
      const a = this.api;
      return { log_entries: a._entries.length, custom_foods: a._foods.filter((f) => f.source === 'custom').length, meal_templates: a._templates.length,
        lab_results: a._labsOf(this.userId).length, symptoms: a._symptomsOf(this.userId).length, weights: a._weightsOf(this.userId).length,
        blood_pressures: a._readingsOf(this.userId).length };
    }
    // -- foods
    foodKey(name, brand, category, servingDesc, servingG, values, flags, notes, gtin, hidden) {
      return tupleKey(fold(name), brand || '', category || '', servingDesc, pyRound(Number(servingG), 1), NUTRIENT_KEYS.map((k) => (values[k] == null ? null : values[k])),
        [...flags].sort(), notes || '', gtin || '', !!hidden);
    }
    ownFoodIndex() {
      const index = new Map();
      for (const row of this.api._foods.filter((f) => f.source === 'custom').sort((a, b) => a.id - b.id)) {
        const key = this.foodKey(row.name, row.brand, row.category, row.serving_desc, row.serving_g, row.nutrients, row.flags, row.kidney_notes, row.gtin, row.hidden);
        if (!index.has(key)) index.set(key, []);
        index.get(key).push(row.id);
      }
      return index;
    }
    ownFood(food, index) {
      const scan = this.api._scanCustomFood(food.name, food.flags, food.kidney_notes, food.ingredients_text);
      const [serving, values] = this.api._storedFoodValues(food.nutrients, scan.flags, food.serving_g);
      const key = this.foodKey(food.name, food.brand, food.category, food.serving_desc, serving, values, scan.flags, scan.kidney_notes, food.gtin, food.hidden);
      const same = index.get(key);
      if (same && same.length) { bump(this.already, 'custom_foods'); return same.shift(); }
      bump(this.counts, 'custom_foods');
      return this.api._insertFood({ source: 'custom', name: food.name, brand: food.brand || null, category: food.category || null, serving_desc: food.serving_desc,
        serving_g: food.serving_g, nutrients: food.nutrients, flags: scan.flags, kidney_notes: scan.kidney_notes, hidden: food.hidden, fdc_id: food.fdc_id,
        gtin: food.gtin, source_url: food.source_url, source_license: food.source_license, ingredients_text: scan.ingredients_text, additives: scan.additives });
    }
    sharedMatch(linked) {
      const shared = this.api._foods.filter((f) => f.source === linked.source).sort((a, b) => a.id - b.id);
      let row = null;
      if (linked.source === 'usda' && linked.fdc_id != null) row = shared.find((f) => f.fdc_id === linked.fdc_id) || null;
      else if (linked.source === 'off') {
        const gtin = linked.gtin || (linked.food ? linked.food.gtin : null);
        if (gtin) row = shared.find((f) => f.gtin === gtin) || null;
      }
      if (!row) return null;
      if (linked.food != null) return Math.abs(Number(row.serving_g) - linked.food.serving_g) < 0.05 ? row : null;
      return fold(row.name) === fold(linked.name) ? row : null;
    }
    builtinMatch(foodId, name, fdcId, byId) {
      const builtins = this.api._foods.filter((f) => f.source === 'builtin').sort((a, b) => (a.hidden ? 1 : 0) - (b.hidden ? 1 : 0) || a.id - b.id);
      if (fdcId != null) return builtins.find((f) => f.fdc_id === fdcId) || null;
      if (byId) return builtins.find((f) => f.id === foodId) || null;
      return builtins.find((f) => f.fdc_id == null && asciiLower(f.name) === asciiLower(name)) || null;
    }
    resolveFoods() {
      const { doc, api } = this;
      const index = this.ownFoodIndex();
      for (const food of doc.custom_foods) this.foodMap.set(food.id, this.ownFood(food, index));
      const linkedBefore = new Set(api._foodLinks());
      for (const linked of doc.linked_foods) {
        const row = this.sharedMatch(linked);
        if (row) {
          api._foodLinks().add(row.id);
          this.foodMap.set(linked.id, row.id);
          if (linkedBefore.has(row.id)) bump(this.already, 'shared_foods_linked');
          else { bump(this.counts, 'shared_foods_linked'); linkedBefore.add(row.id); }
        } else if (linked.food != null) {
          this.foodMap.set(linked.id, this.ownFood(linked.food, index));
          bump(this.counts, 'shared_foods_kept_as_own');
        } else {
          this.unmatched.set(linked.id, 'a shared food (USDA or Open Food Facts) this server does not have, and this older file does not carry its data');
        }
      }
      const seen = new Map(); // the names the file gives each food id it points at
      const see = (id, name) => { if (!seen.has(id)) seen.set(id, new Set()); seen.get(id).add(fold(name)); };
      for (const e of doc.log_entries) see(e.food_id, e.food_name);
      for (const m of doc.meal_templates) for (const it of m.items) see(it.food_id, it.food_name);
      for (const p of doc.food_preferences) see(p.food_id, p.name);
      const listed = new Set(doc.builtin_foods.map((r) => r.id));
      for (const ref of doc.builtin_foods) {
        const row = this.builtinMatch(ref.id, ref.name, ref.fdc_id, false);
        if (row) { this.foodMap.set(ref.id, row.id); bump(this.counts, 'built_in_foods_matched'); } else this.unmatched.set(ref.id, 'a built-in food this server does not have');
      }
      for (const [foodId, names] of seen) {
        if (this.foodMap.has(foodId) || this.unmatched.has(foodId) || listed.has(foodId)) continue;
        const row = this.builtinMatch(foodId, '', null, true);
        if (row && names.has(fold(row.name))) { this.foodMap.set(foodId, row.id); bump(this.counts, 'built_in_foods_matched'); } else {
          this.unmatched.set(foodId, 'a food that is not in the file and is not a built-in food of this server');
        }
      }
    }
    reasonFor(foodId) { return `its food is ${this.unmatched.get(foodId) || 'not in the file'}`; }
    // -- log entries
    importEntries() {
      const api = this.api;
      const have = countOf();
      for (const r of api._entries) bump(have, tupleKey(r.date, r.meal, r.food_id, pyRound(Number(r.servings), 3), r.grams == null ? null : pyRound(Number(r.grams), 1), r.status, r.created_at));
      this.doc.log_entries.forEach((e, index) => {
        const target = this.foodMap.get(e.food_id);
        if (target === undefined) { this.skip('log_entries', index, `${e.date} ${e.meal}: ${e.food_name}`, this.reasonFor(e.food_id)); return; }
        const food = api._food(target);
        const grams = e.grams != null && KH.off.weightKnown(food) ? e.grams : null;
        const key = tupleKey(e.date, e.meal, target, pyRound(e.servings, 3), grams == null ? null : pyRound(grams, 1), e.status, e.created_at);
        if ((have.get(key) || 0) > 0) { have.set(key, have.get(key) - 1); bump(this.already, 'log_entries'); return; }
        const row = api._insertEntry({ date: e.date, meal: e.meal, food, servings: e.servings, grams, note: e.note || null, status: e.status, purpose: e.purpose,
          createdAt: e.created_at });
        row.updated_at = e.updated_at;
        bump(this.counts, 'log_entries');
      });
    }
    // -- saved meals
    importMeals() {
      const api = this.api;
      const have = countOf();
      for (const t of api._templates) bump(have, tupleKey(fold(t.name), t.note || '', t.meal_hint || null, t.items.map((i) => [i.food_id, pyRound(i.servings, 3)])));
      this.doc.meal_templates.forEach((m, index) => {
        const items = [];
        const lost = [];
        for (const item of m.items) {
          const target = this.foodMap.get(item.food_id);
          if (target === undefined) lost.push([`${m.name}: ${item.food_name}`, this.reasonFor(item.food_id)]);
          else items.push({ food_id: target, servings: Number(item.servings) });
        }
        if (!items.length) { this.skip('meal_templates', index, m.name, lost.length ? 'none of its foods could be matched' : 'it has no foods'); return; }
        let note = m.note || '';
        if (lost.length) {
          const names = m.items.filter((i) => this.foodMap.get(i.food_id) === undefined).map((i) => i.food_name);
          const shown = names.slice(0, 5).map((n) => short(n, 40)).join(', ') + (names.length > 5 ? ` and ${names.length - 5} more` : '');
          const added = `Imported without ${names.length} ${names.length === 1 ? 'food' : 'foods'} that could not be matched: ${shown}.`;
          note = `${chars(note).slice(0, Math.max(0, MAX_NOTE_CHARS - chars(added).length - 1)).join('')} ${added}`.trim();
          for (const [label, reason] of lost) this.skip('meal_templates', index, label, reason);
        }
        const key = tupleKey(fold(m.name), note, m.meal_hint || null, items.map((i) => [i.food_id, pyRound(i.servings, 3)]));
        if ((have.get(key) || 0) > 0) { have.set(key, have.get(key) - 1); bump(this.already, 'meal_templates'); return; }
        const t = api._insertTemplate({ name: m.name, note: note || null, items, mealHint: m.meal_hint, createdAt: m.created_at,
          servingsMade: m.servings_made ?? null, steps: m.steps ?? null, sourceUrl: m.source_url ?? null });
        t.updated_at = m.updated_at;
        bump(this.counts, 'meal_templates');
      });
    }
    // -- lab results
    importLabs() {
      const api = this.api;
      const K = KH.kidney;
      const have = countOf();
      for (const r of api._labsOf(this.userId)) if (K.ANALYTES[r.analyte]) bump(have, tupleKey(r.analyte, r.taken_on, K.formatValue(r.analyte, r.value)));
      for (const lab of this.doc.lab_results) {
        const result = K.convert(lab.analyte, lab.entered_value, lab.entered_unit);
        const key = tupleKey(result.analyte, lab.taken_on, K.formatValue(result.analyte, result.value));
        if ((have.get(key) || 0) > 0) { have.set(key, have.get(key) - 1); bump(this.already, 'lab_results'); continue; }
        api._insertLab(this.userId, result, lab.taken_on, lab.note || '', lab.created_at);
        bump(this.counts, 'lab_results');
      }
    }
    // -- symptoms
    importSymptoms() {
      const api = this.api;
      const R2 = KH.symptomRules;
      const have = countOf();
      const perDay = new Map();
      for (const r of api._symptomsOf(this.userId)) { bump(have, tupleKey(r.date, r.symptom, r.label, r.severity, r.note)); bump(perDay, r.date); }
      this.doc.symptoms.forEach((s, index) => {
        const label = s.label || '', note = s.note || '';
        const key = tupleKey(s.date, s.symptom, label, s.severity, note);
        if ((have.get(key) || 0) > 0) { have.set(key, have.get(key) - 1); bump(this.already, 'symptoms'); return; }
        if ((perDay.get(s.date) || 0) >= R2.MAX_PER_DAY) {
          this.skip('symptoms', index, label || R2.NAMES[s.symptom], `that day already has ${R2.MAX_PER_DAY} symptoms, the most one day holds`);
          return;
        }
        api._insertSymptom(this.userId, { date: s.date, symptom: s.symptom, label, severity: s.severity, note }, s.created_at);
        bump(perDay, s.date);
        bump(this.counts, 'symptoms');
      });
    }
    // -- weights and blood pressure readings (schema step 18): a row with a source_key is left out when the person has that key; a row
    // without one (typed by the person) when an identical one is here; a crowded day is skipped and reported
    importWeights() {
      const api = this.api;
      const keys = api._bodyKeys('weights', this.userId);
      const have = countOf();
      const perDay = new Map();
      for (const r of api._weightsOf(this.userId)) {
        if (r.source_key == null) bump(have, tupleKey(r.date, r.time, Math.round(r.kg * 100) / 100, r.context, r.note || ''));
        bump(perDay, r.date);
      }
      this.doc.weights.forEach((w, index) => {
        const rec = api._weightBody(weightRequest(w)); // the same cleaning as POST /api/body/weights
        const kg = BR.roundKg(rec.kg);
        if (w.source_key != null) {
          if (keys.has(w.source_key)) { bump(this.already, 'weights'); return; }
        } else {
          const identity = tupleKey(rec.date, rec.time, kg, w.context, rec.note);
          if ((have.get(identity) || 0) > 0) { have.set(identity, have.get(identity) - 1); bump(this.already, 'weights'); return; }
        }
        if ((perDay.get(rec.date) || 0) >= BR.LIMITS.max_weights_per_day) {
          this.skip('weights', index, `${kg.toFixed(2)} kg on ${rec.date}`, `that day already has ${BR.LIMITS.max_weights_per_day} weights, the most one day holds`);
          return;
        }
        api._insertWeight(this.userId, rec, { source: w.source, sourceKey: w.source_key == null ? null : w.source_key, createdAt: w.created_at });
        const row = api._weights[api._weights.length - 1];
        row.updated_at = w.updated_at;
        if (w.source_key != null) keys.add(w.source_key);
        bump(perDay, rec.date);
        bump(this.counts, 'weights');
      });
    }
    importBloodPressures() {
      const api = this.api;
      const keys = api._bodyKeys('readings', this.userId);
      const have = countOf();
      const perDay = new Map();
      for (const r of api._readingsOf(this.userId)) {
        if (r.source_key == null) bump(have, tupleKey(r.date, r.time, r.systolic, r.diastolic, r.pulse, r.context, r.note || ''));
        bump(perDay, r.date);
      }
      this.doc.blood_pressures.forEach((b, index) => {
        const rec = api._readingBody(readingRequest(b));
        if (b.source_key != null) {
          if (keys.has(b.source_key)) { bump(this.already, 'blood_pressures'); return; }
        } else {
          const identity = tupleKey(rec.date, rec.time, b.systolic, b.diastolic, rec.pulse, b.context, rec.note);
          if ((have.get(identity) || 0) > 0) { have.set(identity, have.get(identity) - 1); bump(this.already, 'blood_pressures'); return; }
        }
        if ((perDay.get(rec.date) || 0) >= BR.LIMITS.max_readings_per_day) {
          this.skip('blood_pressures', index, `${b.systolic}/${b.diastolic} on ${rec.date}`,
            `that day already has ${BR.LIMITS.max_readings_per_day} blood pressure readings, the most one day holds`);
          return;
        }
        api._insertReading(this.userId, rec, { source: b.source, sourceKey: b.source_key == null ? null : b.source_key, createdAt: b.created_at });
        const row = api._readings[api._readings.length - 1];
        row.updated_at = b.updated_at;
        if (b.source_key != null) keys.add(b.source_key);
        bump(perDay, rec.date);
        bump(this.counts, 'blood_pressures');
      });
    }
    // -- food preferences (like, less often, "Not for me", neutral)
    importPreferences() {
      const prefs = this.api._foodPreferences();
      let count = prefs.size;
      let never = 0;
      for (const row of prefs.values()) if (row.preference === 'not_for_me') never += 1;
      this.doc.food_preferences.forEach((p, index) => {
        const target = this.foodMap.get(p.food_id);
        if (target === undefined) { this.skip('food_preferences', index, p.name, this.reasonFor(p.food_id)); return; }
        if (prefs.has(target)) { bump(this.already, 'food_preferences'); return; }
        if (p.preference === 'not_for_me' && never >= MAX_NOT_FOR_ME) { this.skip('food_preferences', index, p.name, `the "Not for me" list is full (${MAX_NOT_FOR_ME} foods)`); return; }
        if (count >= MAX_FOOD_PREFERENCES) { this.skip('food_preferences', index, p.name, `your food preferences are full (${MAX_FOOD_PREFERENCES} foods)`); return; }
        prefs.set(target, { preference: p.preference, source: p.source || 'person', created_at: p.created_at, updated_at: p.updated_at || p.created_at });
        count += 1;
        if (p.preference === 'not_for_me') never += 1;
        bump(this.counts, 'food_preferences');
      });
    }
    // -- profile, targets, settings
    importProfileAndSettings() {
      const { doc, api } = this;
      if (!this.replaceProfile) {
        if (doc.profile != null) this.notSelected.push('your profile and targets');
        if (Object.keys(doc.settings).some((k) => IMPORTED_SETTINGS.includes(k))) this.notSelected.push('your meal-guidance, display, weight and blood pressure settings');
        return;
      }
      if (doc.profile != null) {
        const data = {};
        for (const [k, v] of Object.entries(doc.profile)) if (!['id', 'updated_at', 'ckd_stage_chosen', 'diabetes_chosen'].includes(k)) data[k] = v;
        for (const k of V03_BLANK_IS_NULL) if (typeof data[k] === 'string' && !pyStrip(data[k])) data[k] = null;
        if (doc.profile.ckd_stage_chosen === false) delete data.ckd_stage; // "not chosen yet" stays so
        if (doc.profile.diabetes_chosen === false) delete data.diabetes;
        if (data.targets != null) api._profile.targets = {}; // the person's targets are replaced, not merged key by key
        api._updateProfile(data);
        bump(this.counts, 'profile');
      }
      for (const [key, value] of Object.entries(doc.settings)) {
        if (!IMPORTED_SETTINGS.includes(key)) {
          this.skip('settings', 0, key, 'it is not a setting this import carries over (consents and server settings are never imported)');
          continue;
        }
        try { api._patchSettings({ [key]: value }, { admin: false, userId: this.userId }); bump(this.counts, 'settings'); } catch (e) {
          if (!(e instanceof M.ApiError)) throw e;
          this.skip('settings', 0, key, 'this server does not let you change it');
        }
      }
    }
    run() {
      const existing = this.existingCounts();
      if (Object.values(existing).some((n) => n > 0) && !this.merge) throw new Blocked(existing);
      this.resolveFoods(); this.importEntries(); this.importMeals(); this.importLabs(); this.importSymptoms(); this.importWeights(); this.importBloodPressures(); this.importPreferences(); this.importProfileAndSettings();
    }
    skippedAnswer() {
      const total = [...this.skippedByKind.values()].reduce((a, b) => a + b, 0);
      return { total, shown: this.skipped, by_kind: Object.fromEntries(this.skippedByKind), more: Math.max(0, total - this.skipped.length) };
    }
  }

  const fileSummary = (doc) => ({
    format: doc.format, version: doc.version, exported_at: doc.exported_at === undefined ? null : doc.exported_at, app_version: doc.app_version ? short(doc.app_version, 40) : null,
    records: { log_entries: doc.log_entries.length, custom_foods: doc.custom_foods.length, linked_foods: doc.linked_foods.length, meal_templates: doc.meal_templates.length,
      lab_results: doc.lab_results.length, symptoms: doc.symptoms.length, weights: doc.weights.length, blood_pressures: doc.blood_pressures.length,
      food_preferences: doc.food_preferences.length, profile: doc.profile != null ? 1 : 0 },
  });
  const zeroed = (keys) => Object.fromEntries(keys.map((k) => [k, 0]));
  const blockedAnswer = (existing, { dryRun, merge, replaceProfile, summary }) => ({
    dry_run: dryRun, imported: false, can_import: false,
    blocked: { code: 'account_not_empty', existing, message: 'This account already has data. Importing is refused unless you choose "Add to my existing data".' },
    file: summary, options: { merge, replace_profile: replaceProfile }, counts: zeroed(COUNT_KEYS), already_there: zeroed(ALREADY_KEYS),
    skipped: { total: 0, shown: [], by_kind: {}, more: 0 }, not_selected: [], not_imported: [...NOT_IMPORTED], rule: RULE,
  });

  // What the import touches, so a dry run can put it all back (the server runs it in a transaction it then rolls back).
  const TABLES = ['_foods', '_foodById', '_nextFoodId', '_entries', '_nextEntryId', '_templates', '_nextTemplateId', '_labs', '_nextLabId', '_symptoms', '_nextSymptomId',
    '_weights', '_nextWeightId', '_readings', '_nextReadingId', '_foodPrefs', '_links', '_profile', '_settings', '_lastUs'];
  function snapshotTables(api) {
    api._foodPreferences(); // a copy saved before the preference profile (`_notForMe`) is converted first, so a dry run puts the new shape back
    const snap = {};
    for (const k of TABLES) {
      const v = api[k];
      snap[k] = v === undefined ? undefined : v instanceof Map ? new Map(v) : v instanceof Set ? new Set(v) : Array.isArray(v) ? v.map((x) => (x && typeof x === 'object' ? { ...x } : x))
        : v && typeof v === 'object' ? JSON.parse(JSON.stringify(v)) : v;
    }
    snap._foodById = undefined; // rebuilt from _foods
    return snap;
  }
  function restoreTables(api, snap) {
    for (const k of TABLES) {
      if (k === '_foodById') continue;
      if (snap[k] === undefined) delete api[k]; else api[k] = snap[k];
    }
    api._foodById = new Map(api._foods.map((f) => [f.id, f]));
  }

  MockApi.prototype._runImport = function runImport(body, { dryRun, merge, replaceProfile }) {
    const user = this._currentUser();
    let doc;
    try {
      doc = parseExport(body);
      checkIds(doc);
    } catch (e) {
      if (e instanceof Refused) fail(400, `${GAVE_UP}${e.message}`, { kind: e.kind, index: e.index });
      throw e;
    }
    const importer = new Importer(this, doc, { merge, replaceProfile });
    const snap = snapshotTables(this);
    let committed = false;
    try {
      importer.run();
      if (dryRun) restoreTables(this, snap);
      else {
        const c = importer.counts;
        this._audit(user.id, 'data.imported', 'user', user.id, { merge, profile: !!c.get('profile'), log_entries: c.get('log_entries') || 0, custom_foods: c.get('custom_foods') || 0,
          meal_templates: c.get('meal_templates') || 0, lab_results: c.get('lab_results') || 0, symptoms: c.get('symptoms') || 0, weights: c.get('weights') || 0,
          blood_pressures: c.get('blood_pressures') || 0, food_preferences: c.get('food_preferences') || 0 });
        committed = true;
      }
    } catch (e) {
      restoreTables(this, snap);
      if (e instanceof Blocked) {
        e.summary = fileSummary(doc);
        const answer = blockedAnswer(e.existing, { dryRun, merge, replaceProfile, summary: e.summary });
        if (dryRun) return answer;
        fail(409, answer.blocked.message, { blocked: answer.blocked });
      }
      throw e;
    }
    void committed;
    const n = (map, keys) => Object.fromEntries(keys.map((k) => [k, map.get(k) || 0]));
    return {
      dry_run: dryRun, imported: !dryRun, can_import: true, blocked: null, file: fileSummary(doc), options: { merge, replace_profile: replaceProfile },
      counts: n(importer.counts, COUNT_KEYS), already_there: n(importer.already, ALREADY_KEYS), skipped: importer.skippedAnswer(), not_selected: importer.notSelected,
      not_imported: [...NOT_IMPORTED], rule: RULE,
    };
  };

  // FastAPI bool query parameters (lax): 1/0, true/false, yes/no, on/off, t/f, y/n.
  const BOOL = { true: true, false: false, 1: true, 0: false, yes: true, no: false, on: true, off: false, t: true, f: false, y: true, n: false };
  function flag(qp, name) {
    const v = qp(name);
    if (v == null) return false;
    const b = BOOL[String(v).toLowerCase()];
    if (b === undefined) {
      const msg = 'Input should be a valid boolean, unable to interpret input';
      fail(400, `${name}: ${msg}`, { errors: [{ type: 'bool_parsing', loc: ['query', name], msg }] });
    }
    return b;
  }
  route('POST', '/api/me/import', function ({ qp, body }) {
    this._currentUser();
    const dryRun = flag(qp, 'dry_run'), merge = flag(qp, 'merge'), replaceProfile = flag(qp, 'replace_profile');
    if (body == null) fail(400, `${GAVE_UP}It is empty.`);
    let size = 0;
    try { size = new TextEncoder().encode(JSON.stringify(body)).length; } catch (e) { size = 0; }
    if (size > MAX_IMPORT_BYTES) fail(413, 'Request body too large');
    return this._runImport(body, { dryRun, merge, replaceProfile });
  });

  Object.assign(M, { IMPORT_NOT_IMPORTED: NOT_IMPORTED, IMPORT_RULE: RULE, IMPORTED_SETTINGS, IMPORT_MAX_DEPTH: MAX_DEPTH, importShort: short, importParseTimestamp: parseTimestamp });
})();
