/* Kidney Diet Log — demo API: profile and suggested targets (twin of app/profile.py). */
(() => {
  'use strict';
  const KH = window.KH;
  const { CKD_STAGES, DIALYSIS_MODES, DIABETES_TYPES } = KH.rules;
  const M = KH.mock;
  const { route, MockApi, Check, fail } = M;

  Object.assign(MockApi.prototype, {
    _profileView() {
      const p = this._profile;
      const targets = {};
      for (const [k, v] of Object.entries(p.targets)) targets[k] = v && typeof v === 'object' ? { min: v.min, max: v.max } : v;
      return { id: 1, name: p.name, weight_kg: p.weight_kg, height_cm: p.height_cm, ckd_stage: p.ckd_stage, dialysis: p.dialysis, diabetes: p.diabetes,
        warn_fraction: p.warn_fraction, dialysis_days: [...p.dialysis_days], week_start: p.week_start === 'sunday' ? 'sunday' : 'monday', targets, updated_at: p.updated_at };
    },
    _updateProfile(body) {
      const c = new Check(body);
      c.str('name', { max: 100 });
      c.num('weight_kg', { gt: 0, le: 500 });
      c.num('height_cm', { gt: 0, le: 300 });
      c.choice('ckd_stage', CKD_STAGES, { nullable: true });
      c.choice('dialysis', DIALYSIS_MODES, { nullable: true });
      c.choice('diabetes', DIABETES_TYPES, { nullable: true });
      c.num('warn_fraction', { gt: 0, le: 1 });
      c.targets();
      c.dialysisDays();
      c.choice('week_start', ['monday', 'sunday'], { nullable: true });
      const data = c.done();
      const p = this._profile;
      for (const col of ['weight_kg', 'height_cm']) if (col in data) p[col] = data[col];
      for (const col of ['name', 'ckd_stage', 'dialysis', 'diabetes', 'warn_fraction', 'week_start']) if (col in data && data[col] != null) p[col] = data[col];
      if (data.targets != null) p.targets = { ...p.targets, ...data.targets };
      if ('dialysis_days' in data) p.dialysis_days = data.dialysis_days || [];
      p.updated_at = this._stamp();
      return this._profileView();
    },
    _suggested() {
      const p = this._profile;
      if (p.weight_kg == null) fail(400, 'Save your weight in the profile first; the suggestions are per kg of body weight');
      try { return KH.targets.suggestTargets(p.weight_kg, p.ckd_stage, p.dialysis, p.diabetes, p.height_cm); } catch (e) { return fail(400, e.message); }
    },
  });

  route('GET', '/api/profile', function () { return this._profileView(); });
  route('PUT', '/api/profile', function ({ body }) { return this._updateProfile(body); });
  route('GET', '/api/profile/suggested-targets', function () { return this._suggested(); });
})();
