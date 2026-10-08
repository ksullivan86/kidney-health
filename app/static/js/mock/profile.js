/* Kidney Diet Log — demo API: profile and suggested targets (twin of app/profile.py and the
   ProfileUpdate model in app/models.py).

   v0.3 (note 05 §4.2, ARCHITECTURE.md "M2 API: targets and labs"): the "About you" and treatment
   fields, validated like the server (an empty string or null clears a field: back to null, or to
   the default for sex and the yes/no fields), and the personalised suggestion computed by the
   browser twin of app/targets.py (js/engine/targets.js) from this profile, the person's newest
   lab results (js/mock/labs.js) and the targets.* settings (js/mock/settings.js). Refusals are
   422 {"detail": message, "code"}, as on the server. */
(() => {
  'use strict';
  const KH = window.KH;
  const { CKD_STAGES, DIALYSIS_MODES, DIABETES_TYPES } = KH.rules;
  const T = KH.targets;
  const M = KH.mock;
  const { route, MockApi, Check, fail, validDate, isDict } = M;
  const { todayStr, addDays } = KH.util;

  // models.PROFILE_V03_FIELDS, in the model's field order.
  const V03_FIELDS = ['birth_month', 'sex', 'activity', 'transplant_date', 'frail_or_sarcopenic', 'weight_6_months_ago_kg',
    'pregnant_or_breastfeeding', 'hyperkalemia_history', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal'];
  const V03_DEFAULTS = { birth_month: null, sex: 'unspecified', activity: null, transplant_date: null, frail_or_sarcopenic: false,
    weight_6_months_ago_kg: null, pregnant_or_breastfeeding: false, hyperkalemia_history: false, urine_output_ml: null, pd_uf_ml: null,
    pd_dialysate_kcal: null };
  const BOOL_FIELDS = ['frail_or_sarcopenic', 'pregnant_or_breastfeeding', 'hyperkalemia_history'];
  const MAX_AGE_YEARS = 120;
  const PY_TRUE = new Set(['1', 'on', 't', 'true', 'y', 'yes']);
  const PY_FALSE = new Set(['0', 'off', 'f', 'false', 'n', 'no']);

  // "Not in the future" allows one day ahead of the server's date (the client's time zone).
  function latestAllowedDate() { return addDays(todayStr(), 1); }
  // models.validate_past_date (after validate_date): null when fine, else the message.
  function pastDateError(value) {
    const e = validDate(value);
    if (e) return e;
    if (value > latestAllowedDate()) return 'must not be in the future';
    if (Number(value.slice(0, 4)) < 1900) return 'must be 1900 or later';
    return null;
  }
  // models.validate_birth_month.
  function birthMonthError(value) {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return 'must be a year and month formatted YYYY-MM (for example 1971-03)';
    const latest = latestAllowedDate();
    if (value > latest.slice(0, 7)) return 'must not be in the future';
    if (Number(value.slice(0, 4)) < Number(latest.slice(0, 4)) - MAX_AGE_YEARS) return `must be within the last ${MAX_AGE_YEARS} years`;
    return null;
  }
  // A `str | None` field with an after-validator (str_strip_whitespace applies first).
  function checkStr(c, k, validate) {
    if (!c.has(k)) return;
    const v = c.body[k];
    if (v == null) { c.out[k] = null; return; }
    if (typeof v !== 'string') { c.err(k, 'Input should be a valid string'); return; }
    const s = v.trim();
    const e = validate(s);
    if (e) c.err(k, e); else c.out[k] = s;
  }
  // `bool | None` in pydantic's lax mode: 0/1, the words true/false, yes/no, on/off, t/f, y/n
  // (any case, not trimmed), else an error.
  function checkBool(c, k) {
    if (!c.has(k)) return;
    const v = c.body[k];
    if (v == null) { c.out[k] = null; return; }
    if (typeof v === 'boolean') { c.out[k] = v; return; }
    if (typeof v === 'number') {
      if (v === 0 || v === 1) { c.out[k] = v === 1; return; }
      c.err(k, Number.isInteger(v) ? 'Input should be a valid boolean, unable to interpret input' : 'Input should be a valid boolean');
      return;
    }
    if (typeof v === 'string') {
      const t = v.toLowerCase();
      if (PY_TRUE.has(t)) { c.out[k] = true; return; }
      if (PY_FALSE.has(t)) { c.out[k] = false; return; }
      c.err(k, 'Input should be a valid boolean, unable to interpret input');
      return;
    }
    c.err(k, 'Input should be a valid boolean');
  }

  // profile._about_tolerance: anything outside 0..10 reads as 0.
  function aboutTolerancePct(v) { return Number.isInteger(v) && v >= 0 && v <= KH.rules.ABOUT_TOLERANCE_MAX_PCT ? v : 0; }

  Object.assign(MockApi.prototype, {
    _profileView() {
      const p = this._profile;
      const targets = {};
      for (const [k, v] of Object.entries(p.targets)) targets[k] = v && typeof v === 'object' ? { min: v.min, max: v.max } : v;
      const v03 = {};
      for (const k of V03_FIELDS) v03[k] = p[k] === undefined ? V03_DEFAULTS[k] : p[k];
      return { id: 1, name: p.name, weight_kg: p.weight_kg, height_cm: p.height_cm, ckd_stage: p.ckd_stage, dialysis: p.dialysis, diabetes: p.diabetes,
        warn_fraction: p.warn_fraction, about_tolerance_pct: aboutTolerancePct(p.about_tolerance_pct),
        dialysis_days: [...p.dialysis_days], week_start: p.week_start === 'sunday' ? 'sunday' : 'monday', targets,
        ...v03, ckd_stage_chosen: p.ckd_stage_chosen !== false, diabetes_chosen: p.diabetes_chosen !== false, updated_at: p.updated_at };
    },
    _updateProfile(body) {
      // ProfileUpdate._empty_is_null: a blank string clears a v0.3 field (before any other check).
      let b = body;
      if (isDict(body)) {
        b = { ...body };
        for (const k of V03_FIELDS) if (typeof b[k] === 'string' && !b[k].trim()) b[k] = null;
      }
      const c = new Check(b);
      c.str('name', { max: 100 });
      c.num('weight_kg', { gt: 0, le: 500 });
      c.num('height_cm', { gt: 0, le: 300 });
      c.choice('ckd_stage', CKD_STAGES, { nullable: true });
      c.choice('dialysis', DIALYSIS_MODES, { nullable: true });
      c.choice('diabetes', DIABETES_TYPES, { nullable: true });
      c.num('warn_fraction', { gt: 0, le: 1 });
      c.num('about_tolerance_pct', { int: true, ge: 0, le: KH.rules.ABOUT_TOLERANCE_MAX_PCT });
      c.targets();
      c.dialysisDays();
      c.choice('week_start', ['monday', 'sunday'], { nullable: true });
      checkStr(c, 'birth_month', birthMonthError);
      c.choice('sex', T.SEXES, { nullable: true });
      c.choice('activity', T.ACTIVITIES, { nullable: true });
      checkStr(c, 'transplant_date', pastDateError);
      checkBool(c, 'frail_or_sarcopenic');
      c.num('weight_6_months_ago_kg', { ge: 20, le: 400 });
      checkBool(c, 'pregnant_or_breastfeeding');
      checkBool(c, 'hyperkalemia_history');
      c.num('urine_output_ml', { ge: 0, le: 5000 });
      c.num('pd_uf_ml', { ge: 0, le: 4000 });
      c.num('pd_dialysate_kcal', { ge: 0, le: 1000 });
      const data = c.done();
      const p = this._profile;
      for (const col of ['weight_kg', 'height_cm', 'birth_month', 'activity', 'transplant_date', 'weight_6_months_ago_kg', 'urine_output_ml', 'pd_uf_ml',
        'pd_dialysate_kcal']) if (col in data) p[col] = data[col];
      for (const col of ['name', 'ckd_stage', 'dialysis', 'diabetes', 'warn_fraction', 'week_start']) if (col in data && data[col] != null) p[col] = data[col];
      // Schema step 8: sending a stage or a diabetes type is the person's choice; null keeps "Not chosen yet".
      for (const col of ['ckd_stage', 'diabetes']) if (data[col] != null) p[`${col}_chosen`] = true;
      // profile._RESET_TO_DEFAULT: null puts sex and the yes/no fields back to their default.
      for (const col of ['sex', ...BOOL_FIELDS]) if (col in data) p[col] = data[col] == null ? V03_DEFAULTS[col] : data[col];
      // Schema step 9: the tolerance above "about" targets; null puts it back to 0.
      if ('about_tolerance_pct' in data) p.about_tolerance_pct = data.about_tolerance_pct == null ? 0 : data.about_tolerance_pct;
      if (data.targets != null) p.targets = { ...p.targets, ...data.targets };
      if ('dialysis_days' in data) p.dialysis_days = data.dialysis_days || [];
      p.updated_at = this._stamp();
      return this._profileView();
    },
    // profile.target_settings: the instance settings the rules read (note 05 §4.9).
    _targetSettings() {
      const get = (key) => this._effectiveSetting(key, null).value;
      const freshDays = {};
      for (const a of Object.keys(T.DEFAULT_FRESH_DAYS)) freshDays[a] = Math.trunc(Number(get(`targets.lab_fresh_days.${a}`)));
      return { lab_rules_enabled: !!get('targets.lab_rules_enabled'), default_activity: get('targets.default_activity'), fresh_days: freshDays };
    },
    // GET /api/profile/suggested-targets: 400 without a weight, 422 {detail, code} for a refusal.
    _suggested() {
      const p = this._profileView();
      if (p.weight_kg == null) fail(400, 'Save your weight in the profile first; the suggestions are per kg of body weight');
      const labs = this._latestLabs(this._currentUser().id, T.TARGET_LABS);
      try {
        return T.suggestFromRecords(p, labs, todayStr(), this._targetSettings());
      } catch (e) {
        if (e instanceof T.OutOfScope) return fail(422, e.message, { code: e.code });
        if (e instanceof T.InvalidInput) return fail(400, e.message);
        throw e;
      }
    },
  });

  route('GET', '/api/profile', function () { return this._profileView(); });
  route('PUT', '/api/profile', function ({ body }) { return this._updateProfile(body); });
  route('GET', '/api/profile/suggested-targets', function () { return this._suggested(); });

  Object.assign(M, { pastDateError, birthMonthError, PROFILE_V03_FIELDS: V03_FIELDS, PROFILE_V03_DEFAULTS: V03_DEFAULTS });
})();
