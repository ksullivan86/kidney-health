/* Kidney Diet Log — Profile view: about you (note 05 §4.2: birth month, sex used in formulas,
   activity, weight history, health flags), kidneys and diabetes (with the transplant date and the
   dialysis-only fields shown for the matching mode), a summary of the latest lab results, and the
   daily targets with "Suggest targets" (never auto-saved; note 05 §4.8: what changes compared with
   the saved targets, "Why this number?" with every rule's source, grade and expert-opinion badge,
   the refusals, and the inputs that would make the suggestion more personal). Theme, account,
   keys and this device are in Settings. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, api, state, toast, toastError, router, sheets } = KH;
  const { WEEKDAYS, WEEKDAYS_LONG } = KH.ui;
  const { numOrNull } = KH.util;
  const { NUT, fmtNum } = KH.rules;
  const { splitFieldErrors, fieldError, clearFieldErrors } = KH.forms;

  const profileForm = $('#profile-form');
  const SEX_TEXT = { female: 'female', male: 'male', unspecified: 'sex not set' };
  const BASIS_TEXT = {
    actual: 'your weight', actual_no_height: 'your weight (no height saved)',
    adjusted_above_bmi25: 'adjusted: above the healthy BMI range', adjusted_below_bmi18_5: 'adjusted: below the healthy BMI range',
  };
  // Where a server error about a field is shown.
  const FIELD_INPUT = {
    name: 'pf-name', weight_kg: 'pf-weight', height_cm: 'pf-height', ckd_stage: 'pf-stage', dialysis: 'pf-dialysis', diabetes: 'pf-diabetes',
    warn_fraction: 'pf-warn', about_tolerance_pct: 'pf-about-tol', week_start: 'pf-week-start', dialysis_days: 'pf-dd-0', birth_month: 'pf-birth-month', sex: 'pf-sex',
    activity: 'pf-act-none', transplant_date: 'pf-transplant-date', frail_or_sarcopenic: 'pf-frail', weight_6_months_ago_kg: 'pf-weight-6mo',
    pregnant_or_breastfeeding: 'pf-pregnant', hyperkalemia_history: 'pf-hyperk', urine_output_ml: 'pf-urine', pd_uf_ml: 'pf-uf',
    pd_dialysate_kcal: 'pf-pdkcal', targets: 'tg-potassium_mg',
  };
  // missing_inputs (note 05 §4.6) → the prompt's words and the field it opens.
  const MISSING = {
    height_cm: ['your height', 'pf-height'], birth_month: ['your birth month', 'pf-birth-month'], sex: ['the sex used in formulas', 'pf-sex'],
    activity: ['your activity', 'pf-act-inactive'], urine_output_ml: ['your daily urine volume', 'pf-urine'],
    pd_uf_ml: ['your daily ultrafiltration', 'pf-uf'], pd_dialysate_kcal: ['the calories from dialysis fluid', 'pf-pdkcal'],
  };
  // Suggested targets in reading order; carbohydrate per meal is shown with the daily carbohydrate.
  const TARGET_ROWS = [
    ['calories_kcal', 'Calories', ['E']], ['protein_g', 'Protein', ['P']], ['carbs_g', 'Carbohydrate', ['C']], ['fiber_g', 'Fiber', ['FB']],
    ['sodium_mg', 'Sodium', ['NA']], ['potassium_mg', 'Potassium', ['K']], ['phosphorus_mg', 'Phosphorus', ['PH']],
    ['calcium_mg', 'Calcium', ['CA']], ['fluid_ml', 'Fluid', ['F']],
  ];
  const GENERAL_GROUPS = [['W', 'Weight basis'], ['N', 'Nutrition risk']];

  // ---------------------------------------------------------------------------
  // Form fields
  // ---------------------------------------------------------------------------
  (function buildDialysisDays() {
    const box = $('#pf-dialysis-days');
    WEEKDAYS.forEach((d, i) => {
      box.append(h('label', { class: 'wd-check', for: `pf-dd-${i}` },
        h('input', { type: 'checkbox', id: `pf-dd-${i}`, value: i, 'data-weekday': i }),
        h('span', {}, h('span', { class: 'sr-only' }, WEEKDAYS_LONG[i]), h('span', { 'aria-hidden': 'true' }, d))));
    });
  })();
  // Fields that only apply to one treatment (note 05 §4.8): dialysis days and urine (hemodialysis),
  // urine, ultrafiltration and dialysate calories (peritoneal), the transplant date (no dialysis).
  function syncConditionalFields() {
    const dialysis = $('#pf-dialysis').value;
    $('#pf-dialysis-days-field').hidden = dialysis !== 'hemodialysis';
    $('#pf-urine-field').hidden = dialysis === 'none';
    $('#pf-uf-field').hidden = dialysis !== 'peritoneal';
    $('#pf-pdkcal-field').hidden = dialysis !== 'peritoneal';
    $('#pf-transplant-field').hidden = dialysis !== 'none';
    const onDialysis = dialysis !== 'none';
    $('#pf-weight-label').textContent = onDialysis ? 'Dry weight (kg, after dialysis)' : 'Weight (kg)';
    $('#pf-weight-hint').textContent = onDialysis
      ? 'Your weight after a dialysis session, without extra fluid. Calories and protein are worked out from it.'
      : 'Calories and protein are worked out from it.';
    const transplant = !onDialysis && !!$('#pf-transplant-date').value;
    $('#pf-stage-label').textContent = transplant ? 'Transplant kidney stage' : 'CKD stage';
    $('#pf-stage-hint').textContent = transplant ? "The stage of your transplant's function, as your transplant team gives it." : 'The stage your nephrologist gave you.';
    // A kidney-only profile (diabetes "None", v0.3.1): meals have no carbohydrate goal, so the per-meal and per-snack
    // carbohydrate targets are hidden; their values stay and are saved unchanged.
    const kidneyOnly = $('#pf-diabetes').value === 'none';
    for (const id of ['#tg-carbs_per_meal_g', '#tg-carbs_per_snack_g']) $(id).closest('.field').hidden = kidneyOnly;
  }
  $('#pf-dialysis').addEventListener('change', syncConditionalFields);
  $('#pf-diabetes').addEventListener('change', syncConditionalFields);
  $('#pf-transplant-date').addEventListener('input', syncConditionalFields);
  function selectedDialysisDays() { return $$('#pf-dialysis-days input:checked').map((c) => Number(c.dataset.weekday)).sort(); }
  function setMaxDates() {
    const today = KH.util.todayStr();
    $('#pf-transplant-date').max = today;
    $('#pf-birth-month').max = today.slice(0, 7);
  }

  // The v0.3 fields as the form shows them (empty string = not set).
  function readAbout() {
    const activity = $('input[name="activity"]:checked', profileForm);
    return {
      birth_month: $('#pf-birth-month').value.trim() || null,
      sex: $('#pf-sex').value || 'unspecified',
      activity: activity && activity.value ? activity.value : null,
      transplant_date: $('#pf-transplant-date').value || null,
      frail_or_sarcopenic: $('#pf-frail').checked,
      weight_6_months_ago_kg: numOrNull($('#pf-weight-6mo').value),
      pregnant_or_breastfeeding: $('#pf-pregnant').checked,
      hyperkalemia_history: $('#pf-hyperk').checked,
      urine_output_ml: numOrNull($('#pf-urine').value),
      pd_uf_ml: numOrNull($('#pf-uf').value),
      pd_dialysate_kcal: numOrNull($('#pf-pdkcal').value),
    };
  }
  function fillAbout(p) {
    $('#pf-birth-month').value = p.birth_month || '';
    $('#pf-sex').value = p.sex === 'female' || p.sex === 'male' ? p.sex : 'unspecified';
    const act = $(`#pf-act-${p.activity || 'none'}`) || $('#pf-act-none');
    act.checked = true;
    $('#pf-transplant-date').value = p.transplant_date || '';
    $('#pf-frail').checked = !!p.frail_or_sarcopenic;
    $('#pf-weight-6mo').value = p.weight_6_months_ago_kg ?? '';
    $('#pf-pregnant').checked = !!p.pregnant_or_breastfeeding;
    $('#pf-hyperk').checked = !!p.hyperkalemia_history;
    $('#pf-urine').value = p.urine_output_ml ?? '';
    $('#pf-uf').value = p.pd_uf_ml ?? '';
    $('#pf-pdkcal').value = p.pd_dialysate_kcal ?? '';
  }

  function renderProfile() {
    const p = state.profile;
    if (!p) return;
    setMaxDates();
    $('#pf-name').value = p.name || '';
    $('#pf-weight').value = p.weight_kg ?? '';
    $('#pf-height').value = p.height_cm ?? '';
    // "Not chosen yet" (schema step 8): the stored default still applies until the person picks.
    $('#pf-stage').value = p.ckd_stage_chosen === false ? '' : (p.ckd_stage || '3b');
    $('#pf-dialysis').value = p.dialysis || 'none';
    $('#pf-diabetes').value = p.diabetes_chosen === false ? '' : (p.diabetes || 'type1');
    $('#pf-warn').value = Math.round((p.warn_fraction ?? 0.8) * 100);
    $('#pf-about-tol').value = p.about_tolerance_pct ?? 0;
    $('#pf-week-start').value = p.week_start === 'sunday' ? 'sunday' : 'monday';
    const dd = new Set((p.dialysis_days || []).map(Number));
    $$('#pf-dialysis-days input').forEach((c) => { c.checked = dd.has(Number(c.dataset.weekday)); });
    fillAbout(p);
    syncConditionalFields();
    fillTargets(p.targets || {});
    $('#suggest-notes').hidden = true;
    $('#suggest-refusal').hidden = true;
    clearErrors();
    renderTargetsStale();
    renderTargetsReview();
    // A fresh database already has a profile row (with a creation timestamp); only call it
    // "saved" once the person has actually stored something.
    const hasContent = p.weight_kg != null || p.height_cm != null || !!p.name || !!p.birth_month || Object.values(p.targets || {}).some((v) => v != null);
    $('#profile-saved').textContent = p.updated_at && hasContent ? `Last saved ${new Date(p.updated_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}` : '';
  }

  // ---------------------------------------------------------------------------
  // Targets editor: single numbers, {min, max} ranges (protein, calcium) and the fibre goal ({min} only)
  // ---------------------------------------------------------------------------
  // `onlyGiven`: leave the boxes of targets the answer does not include (a suggestion never sets the snack carb
  // goal, which comes from the person's diabetes team) as they are.
  function fillTargets(targets, { onlyGiven = false } = {}) {
    for (const inp of $$('input[data-target]')) {
      if (onlyGiven && !(inp.dataset.target in targets)) continue;
      const v = targets[inp.dataset.target];
      inp.value = typeof v === 'number' ? v : v && typeof v === 'object' ? (v.max ?? v.min ?? '') : '';
    }
    for (const inp of $$('input[data-range-min]')) {
      const v = targets[inp.dataset.rangeMin];
      inp.value = v && typeof v === 'object' && v.min != null ? v.min : '';
    }
    for (const inp of $$('input[data-range-max]')) {
      const v = targets[inp.dataset.rangeMax];
      inp.value = v == null ? '' : typeof v === 'object' ? (v.max ?? '') : v;
    }
    for (const inp of $$('input[data-target-goal]')) {
      const v = targets[inp.dataset.targetGoal];
      inp.value = v == null ? '' : typeof v === 'object' ? (v.min ?? v.max ?? '') : v;
    }
  }
  class FormProblem extends Error { constructor(message, input) { super(message); this.detail = message; this.input = input; } }
  function readTargets() {
    const targets = {};
    for (const inp of $$('input[data-target]')) targets[inp.dataset.target] = numOrNull(inp.value);
    for (const minInp of $$('input[data-range-min]')) {
      const key = minInp.dataset.rangeMin;
      const maxInp = $(`input[data-range-max="${key}"]`);
      const label = NUT[key].label;
      const lo = numOrNull(minInp.value), hi = numOrNull(maxInp.value);
      if (lo == null && hi == null) targets[key] = null;
      else if (lo == null) targets[key] = hi;
      else if (hi == null) throw new FormProblem(`${label} needs a maximum when a minimum is set`, maxInp);
      else if (lo > hi) throw new FormProblem(`${label} minimum must not exceed the maximum`, minInp);
      else targets[key] = { min: lo, max: hi };
    }
    for (const inp of $$('input[data-target-goal]')) {
      const v = numOrNull(inp.value);
      targets[inp.dataset.targetGoal] = v == null ? null : { min: v };
    }
    return targets;
  }

  // ---------------------------------------------------------------------------
  // Errors: the alert at the end of the form, and each reason under its field
  // ---------------------------------------------------------------------------
  function clearErrors() { clearFieldErrors(profileForm); clear($('#profile-form-error')).classList.remove('sr-only'); }
  function showErrors(err) {
    clearErrors();
    const parts = splitFieldErrors(err.detail || err.message);
    const box = $('#profile-form-error');
    box.append(h('p', {}, parts.length > 1 ? 'Please check these fields:' : 'Please check this:'),
      h('ul', {}, parts.map((p) => h('li', {}, p.field ? `${fieldLabel(p.field)}: ${p.message}` : p.message))));
    let first = null;
    let placed = 0;
    for (const p of parts) {
      const root = p.field ? p.field.split('.')[0] : null;
      const input = root && document.getElementById(FIELD_INPUT[root] || '');
      if (!input) continue;
      fieldError(input, p.message, input.type === 'radio' || input.type === 'checkbox' ? input.closest('fieldset, .field') : null);
      placed += 1;
      if (!first) first = input;
    }
    // Every reason is shown under its field: the alert stays for screen readers only.
    box.classList.toggle('sr-only', placed === parts.length);
    if (first) { revealField(first); first.focus(); }
  }
  function fieldLabel(field) {
    const id = FIELD_INPUT[field.split('.')[0]];
    const input = id && document.getElementById(id);
    const label = input && (input.labels && input.labels[0] ? input.labels[0].textContent : null);
    const legend = input && input.closest('fieldset') ? input.closest('fieldset').querySelector('legend') : null;
    return (input && input.type === 'radio' && legend ? legend.textContent : label) || field;
  }
  // Hidden conditional fields are shown before focusing them (a server error can name one).
  function revealField(input) {
    for (let el = input; el && el !== profileForm; el = el.parentElement) if (el.hidden) el.hidden = false;
    try { input.scrollIntoView({ block: 'center' }); } catch (e) { /* old browsers */ }
  }

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------
  function formBody(targets) {
    const warnPct = numOrNull($('#pf-warn').value);
    const aboutPct = numOrNull($('#pf-about-tol').value);
    return {
      name: $('#pf-name').value.trim(),
      weight_kg: numOrNull($('#pf-weight').value),
      height_cm: numOrNull($('#pf-height').value),
      // Empty = "Not chosen yet": null keeps the stored value and leaves the choice open.
      ckd_stage: $('#pf-stage').value || null,
      dialysis: $('#pf-dialysis').value,
      diabetes: $('#pf-diabetes').value || null,
      warn_fraction: warnPct != null ? Math.min(1, Math.max(0.5, warnPct / 100)) : 0.8,
      // Schema step 9: empty means 0 (the number itself); the server refuses anything outside 0–10.
      about_tolerance_pct: aboutPct != null ? aboutPct : 0,
      ...(targets ? { targets } : {}),
      dialysis_days: $('#pf-dialysis').value === 'hemodialysis' ? selectedDialysisDays() : [],
      week_start: $('#pf-week-start').value === 'sunday' ? 'sunday' : 'monday',
      ...readAbout(),
    };
  }
  sheets.onSubmit(profileForm, async (e) => {
    e.preventDefault();
    let targets;
    try { targets = readTargets(); } catch (err) {
      clearErrors();
      $('#profile-form-error').append(h('p', {}, err.message));
      if (err.input) { fieldError(err.input, err.message); err.input.focus(); }
      return;
    }
    const body = formBody(targets);
    const btn = $('#btn-save-profile');
    const before = state.profile;
    btn.disabled = true;
    try {
      state.profile = await api.saveProfile(body);
      // Targets are not recomputed when the stage or dialysis changes (they may come from the
      // care team); say so until the targets are saved again or the notice is dismissed, and
      // offer the suggestion for the new setting to review.
      const now = state.profile;
      if (before && (before.ckd_stage !== now.ckd_stage || before.dialysis !== now.dialysis)) {
        state.targetsStale = { from: state.targetsStale ? state.targetsStale.from : before, to: now };
        if (state.targetsStale.from.ckd_stage === now.ckd_stage && state.targetsStale.from.dialysis === now.dialysis) state.targetsStale = null; // changed back
      } else if (state.targetsStale && before && JSON.stringify(before.targets) !== JSON.stringify(now.targets)) state.targetsStale = null;
      else if (state.targetsStale) state.targetsStale.to = now;
      if (state.targetsReview && before && JSON.stringify(before.targets) !== JSON.stringify(now.targets)) state.targetsReview = null;
      renderProfile();
      state.dayLoadedFor = null; state.trends = null; state.summary = null; state.plan = null; state.planStart = null; state.shopping = null;
      if (KH.labs) KH.labs.invalidate();
      toast('Profile saved', 'ok');
      loadLabsSummary();
    } catch (err) {
      if (err.handled) return;
      if (err.status === 400) showErrors(err); else toastError(err);
    } finally { btn.disabled = false; }
  });

  // ---------------------------------------------------------------------------
  // Notices: stale targets after a stage or dialysis change, and "Review suggested targets" after
  // a lab result changed the suggestion (set by js/views/labs.js; never auto-applied)
  // ---------------------------------------------------------------------------
  function settingText(p) {
    const mode = { hemodialysis: 'on hemodialysis', peritoneal: 'on peritoneal dialysis' }[p.dialysis] || 'without dialysis';
    return `CKD stage ${p.ckd_stage} ${mode}`;
  }
  function renderTargetsStale() {
    const st = state.targetsStale;
    $('#targets-stale').hidden = !st;
    if (st) {
      $('#targets-stale-msg').textContent = `You changed from ${settingText(st.from)} to ${settingText(st.to)}. Your daily targets below have not changed. `
        + 'Suggested starting points depend on stage and dialysis: review them for the new setting, or keep the targets your care team gave you.';
    }
  }
  function renderTargetsReview() {
    const rv = state.targetsReview;
    $('#targets-review').hidden = !rv;
    const box = clear($('#targets-review-msg'));
    if (!rv) return;
    box.append(h('p', {}, `Your ${rv.what} changes the suggested targets. Nothing has changed in your saved targets.`),
      h('ul', {}, rv.changes.map((c) => h('li', {}, c))));
  }
  $('#targets-stale-keep').addEventListener('click', () => { state.targetsStale = null; renderTargetsStale(); $('#btn-suggest').focus(); });
  $('#targets-stale-suggest').addEventListener('click', () => suggestTargetsIntoForm({ from: '#targets-stale-suggest' }));
  $('#targets-review-dismiss').addEventListener('click', () => { state.targetsReview = null; renderTargetsReview(); $('#btn-suggest').focus(); });
  $('#targets-review-suggest').addEventListener('click', () => suggestTargetsIntoForm({ from: '#targets-review-suggest' }));
  $('#btn-suggest').addEventListener('click', () => suggestTargetsIntoForm());

  // ---------------------------------------------------------------------------
  // Suggest targets
  // ---------------------------------------------------------------------------
  const sameNumber = (a, b) => (a ?? null) === (b ?? null) || (a != null && b != null && Number(a) === Number(b));
  // The fields the suggestion reads that differ between the form and the saved profile.
  function unsavedChanges(saved) {
    const body = formBody(null);
    const changed = [];
    for (const k of ['weight_kg', 'height_cm']) if (!sameNumber(body[k], saved[k])) changed.push(k);
    const savedChoice = (k) => (saved[`${k}_chosen`] === false ? null : saved[k]);
    for (const k of ['ckd_stage', 'diabetes']) if ((body[k] || null) !== (savedChoice(k) ?? null)) changed.push(k);
    if (body.dialysis !== saved.dialysis) changed.push('dialysis');
    for (const k of ['weight_6_months_ago_kg', 'urine_output_ml', 'pd_uf_ml', 'pd_dialysate_kcal']) if (!sameNumber(body[k], saved[k])) changed.push(k);
    for (const k of ['birth_month', 'sex', 'activity', 'transplant_date']) if ((body[k] || null) !== (saved[k] || null)) changed.push(k);
    for (const k of ['frail_or_sarcopenic', 'pregnant_or_breastfeeding', 'hyperkalemia_history']) if (!!body[k] !== !!saved[k]) changed.push(k);
    return changed;
  }
  async function suggestTargetsIntoForm({ from = null } = {}) {
    const btn = from ? $(from) : $('#btn-suggest');
    // The endpoint works from the *saved* profile; check the form first so the person is told
    // what to do in plain words instead of seeing the server's 400, and is not handed numbers for
    // details the form no longer shows.
    const weight = numOrNull($('#pf-weight').value);
    const saved = state.profile || {};
    if (weight == null) { toast('Enter your weight (kg) first; the suggestions are per kg of body weight', 'error'); $('#pf-weight').focus(); return; }
    const unchosen = ['#pf-stage', '#pf-diabetes'].find((sel) => !$(sel).value);
    if (unchosen) { toast('Choose your CKD stage and diabetes type first; the suggestions depend on both', 'error'); $(unchosen).focus(); return; }
    const changed = unsavedChanges(saved);
    if (saved.weight_kg == null || changed.includes('weight_kg') || changed.includes('height_cm')) {
      toast('Save profile first so the suggestion uses your weight and height', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    if (changed.some((k) => ['ckd_stage', 'dialysis', 'diabetes'].includes(k))) {
      toast('Save profile first so the suggestion uses your stage and dialysis setting', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    if (changed.length) {
      toast('Save profile first so the suggestion uses the details you changed', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    // The refusals (pregnancy, under 18, the first 12 weeks after a transplant) depend only on the
    // saved profile; the parity-tested twin of the rules says them without a request that would
    // only come back 422. The server still refuses on its own.
    const refusal = refusalFor(saved);
    if (refusal) { renderRefusal(refusal.code, refusal.message); return; }
    btn.disabled = true;
    $('#suggest-live').textContent = 'Working out suggested targets…';
    try {
      const res = await api.suggested();
      fillTargets(res.targets || {}, { onlyGiven: true });
      $('#suggest-refusal').hidden = true;
      renderSuggestion(res, saved);
      state.targetsStale = null; // the suggestion for the saved setting is in the form now
      state.targetsReview = null;
      renderTargetsStale();
      renderTargetsReview();
      $('#suggest-live').textContent = 'Suggested targets are filled in below. They are not saved yet.';
      if (from) $('#suggest-notes').focus();
      toast('Targets suggested; review and save', 'ok');
    } catch (err) {
      $('#suggest-live').textContent = '';
      if (err.handled) return;
      if (err.status === 422 && err.data && err.data.code) renderRefusal(err.data.code, err.detail);
      else toastError(err);
    } finally { btn.disabled = false; }
  }

  // {code, message} when the rules refuse this saved profile (js/engine/targets.js OutOfScope), else null.
  function refusalFor(profile) {
    if (!profile || profile.weight_kg == null) return null;
    const today = KH.util.todayStr();
    try { KH.targets.suggest(KH.targets.inputsFromRecords(profile, [], today), today); } catch (e) {
      if (e instanceof KH.targets.OutOfScope) return { code: e.code, message: e.message };
    }
    return null;
  }
  // 422: pregnancy, under 18, the first 12 weeks after a transplant (note 05 §4.5). No numbers at all.
  function renderRefusal(code, message) {
    const box = clear($('#suggest-refusal'));
    $('#suggest-notes').hidden = true;
    const learn = KH.learn ? KH.learn.link('pages', 'targets') : null;
    box.append(h('div', { class: 'notes-title' }, 'No suggested targets for you'), h('p', {}, message),
      h('p', { class: 'muted small' }, 'Your saved targets have not changed. Type the targets your care team gives you below, then press Save profile.'),
      learn ? h('p', { class: 'notes-learn' }, learn) : null);
    box.dataset.code = code;
    box.hidden = false;
    $('#suggest-live').textContent = message;
    box.focus();
  }

  // ---- presenting the answer ----
  function unitOf(key) { return NUT[key] ? NUT[key].unit : 'g'; }
  // "3,500 mg/day", "about 56 g/day", "56–70 g/day", "at least 29 g/day", "no limit".
  function targetText(key, v) {
    const u = unitOf(key);
    if (v == null) return 'no limit';
    if (typeof v === 'number') return `${fmtNum(v, key)} ${u}/day`;
    const lo = v.min ?? null, hi = v.max ?? null;
    if (lo != null && hi != null) return lo === hi ? `about ${fmtNum(hi, key)} ${u}/day` : `${fmtNum(lo, key)}–${fmtNum(hi, key)} ${u}/day`;
    if (lo != null) return `at least ${fmtNum(lo, key)} ${u}/day`;
    return hi != null ? `${fmtNum(hi, key)} ${u}/day` : 'no limit';
  }
  function norm(v) {
    if (v == null) return null;
    if (typeof v === 'number') return { min: null, max: v };
    return { min: v.min ?? null, max: v.max ?? null };
  }
  const sameTarget = (a, b) => JSON.stringify(norm(a)) === JSON.stringify(norm(b));
  // The rule's note, paired with the rule (every applied rule has one note, in the same order,
  // and the last note is the "starting points only" reminder; note 05 §4.4–§4.5).
  function pairRules(res) {
    const rules = res.rules || [];
    const notes = res.notes || [];
    const paired = notes.length === rules.length + 1;
    return { items: rules.map((r, i) => ({ rule: r, note: paired ? notes[i] : null })), end: paired ? notes[notes.length - 1] : null, paired };
  }
  const prefixOf = (id) => String(id).split('-')[0];
  // The note's first sentence without its "Potassium: " lead-in (no look-behind: older Safari lacks it).
  function firstSentence(note) {
    const text = String(note || '');
    const m = /[.!?]\s+[A-Z]/.exec(text);
    return (m ? text.slice(0, m.index + 1) : text).replace(/^[A-Z][a-z]+: /, '');
  }
  function safeUrl(url) { return /^https:\/\/[^\s"<>]+$/.test(String(url || '')) ? url : null; }
  function ruleMeta(rule) {
    const url = safeUrl(rule.url);
    const source = url
      ? h('a', { class: 'src-link', href: url, target: '_blank', rel: 'noopener noreferrer' }, `Source: ${rule.source}`, h('span', { class: 'sr-only' }, ' (opens in a new tab)'))
      : h('span', {}, `Source: ${rule.source}`);
    return h('div', { class: 'why-meta' },
      h('p', {}, h('span', { class: 'rule-id' }, `Rule ${rule.id}`), ` · Grade: ${rule.grade}`,
        rule.opinion ? [' ', h('span', { class: 'badge opinion' }, 'Expert opinion'), rule.opinion_note ? h('span', { class: 'opinion-note' }, ` (${rule.opinion_note})`) : null] : null),
      h('p', {}, source));
  }
  function whyBlock(items) {
    return items.map(({ rule, note }) => h('div', { class: 'why-rule' }, note ? h('p', {}, note) : null, ruleMeta(rule)));
  }
  function renderSuggestion(res, saved) {
    const box = clear($('#suggest-notes'));
    const t = res.targets || {};
    const savedTargets = saved.targets || {};
    const derived = res.derived || {};
    const { items, end } = pairRules(res);
    const groups = {};
    for (const it of items) (groups[prefixOf(it.rule.id)] = groups[prefixOf(it.rule.id)] || []).push(it);

    box.append(h('div', { class: 'notes-title' }, `Suggested starting points for ${settingText(saved)}, filled in below and not saved yet.`),
      h('p', {}, 'Discuss them with your care team, change any number, then press Save profile.'));
    // Safety first: a very high potassium result (KDIGO 2024 Table 28), whatever the settings say.
    for (const a of res.alerts || []) box.append(KH.labs ? KH.labs.alertBanner(a) : h('p', { class: 'lab-alert', role: 'alert' }, a.message));
    if (derived.lab_rules_enabled === false) {
      box.append(h('p', { class: 'muted small' }, 'This server does not use lab results to change targets (an admin setting). A very high potassium result is still flagged.'));
    }

    // What saving would change (with the deciding rule's first sentence as the reason).
    const anySaved = Object.values(savedTargets).some((v) => v != null);
    // The suggestion is worked out from the saved profile: without diabetes it names no carbohydrate per meal.
    const mealCarbs = !(state.profile && state.profile.diabetes === 'none');
    if (anySaved) {
      const changes = [];
      for (const [key, label, prefixes] of TARGET_ROWS) {
        const keys = key === 'carbs_g' && mealCarbs ? ['carbs_g', 'carbs_per_meal_g'] : [key];
        for (const k of keys) {
          if (!(k in t) || sameTarget(savedTargets[k], t[k])) continue;
          const decisive = prefixes.flatMap((p) => groups[p] || []).filter((x) => x.note).pop();
          const name = k === 'carbs_per_meal_g' ? 'Carbohydrate per meal' : label;
          const fromText = savedTargets[k] == null ? 'not tracked' : targetText(k, savedTargets[k]);
          changes.push(h('li', {}, h('b', {}, name), `: ${fromText} → `, h('b', {}, targetText(k, t[k])),
            decisive && k !== 'carbs_per_meal_g' ? h('span', { class: 'why-short' }, `Why: ${firstSentence(decisive.note)}`) : null));
        }
      }
      box.append(h('h3', { class: 'suggest-h' }, 'Compared with your saved targets'),
        changes.length ? h('ul', { class: 'suggest-changes' }, changes) : h('p', {}, 'The suggestion is the same as your saved targets.'));
    }

    // How it was worked out, then every target with its rules ("Why this number?").
    const general = GENERAL_GROUPS.flatMap(([p]) => groups[p] || []);
    if (general.length) box.append(h('h3', { class: 'suggest-h' }, 'How the numbers were worked out'), ...whyBlock(general));
    box.append(derivedLine(derived));
    const list = h('div', { class: 'why-list' });
    for (const [key, label, prefixes] of TARGET_ROWS) {
      const its = prefixes.flatMap((p) => groups[p] || []);
      if (!(key in t) && !its.length) continue;
      const value = key === 'carbs_g' && mealCarbs && t.carbs_per_meal_g != null ? `${targetText(key, t[key])}, about ${t.carbs_per_meal_g} g per meal` : targetText(key, t[key]);
      list.append(h('div', { class: 'why-item' },
        h('div', { class: 'why-head' }, h('b', {}, label), h('span', { class: 'why-value' }, value)),
        its.length ? h('details', { class: 'why' }, h('summary', {}, 'Why this number?', h('span', { class: 'sr-only' }, ` (${label.toLowerCase()})`)), ...whyBlock(its)) : null));
    }
    box.append(h('h3', { class: 'suggest-h' }, anySaved ? 'Each suggested target' : 'Suggested targets'), list);
    const labNotes = groups.L || [];
    if (labNotes.length) box.append(h('h3', { class: 'suggest-h' }, 'About your lab results'), ...whyBlock(labNotes));

    // The inputs that would make it more personal.
    const missing = (res.missing_inputs || []).filter((k) => MISSING[k]);
    if (missing.length) {
      box.append(h('div', { class: 'suggest-missing' },
        h('p', {}, 'For a more personal suggestion, add these, save the profile and suggest again:'),
        h('div', { class: 'missing-btns' }, missing.map((k) => {
          const [words, id] = MISSING[k];
          return h('button', { class: 'link-btn', type: 'button', onclick: () => { const el = document.getElementById(id); revealField(el); el.focus(); } },
            words.charAt(0).toUpperCase() + words.slice(1));
        }))));
    }
    if (end) box.append(h('p', { class: 'suggest-end' }, end));
    // How the numbers are worked out, and which details change them (the handbook, when there is one).
    const how = KH.learn ? [KH.learn.link('pages', 'targets'), KH.learn.link('pages', 'first_setup')].filter(Boolean) : [];
    if (how.length) box.append(h('p', { class: 'notes-learn' }, how.flatMap((a, i) => (i ? [' · ', a] : [a]))));
    box.hidden = false;
  }
  function derivedLine(d) {
    const parts = [];
    if (d.age != null) parts.push(`age ${d.age}`);
    if (d.sex) parts.push(SEX_TEXT[d.sex] || d.sex);
    if (d.reference_weight_kg != null) parts.push(`reference weight ${d.reference_weight_kg} kg (${BASIS_TEXT[d.weight_basis] || d.weight_basis})`);
    if (d.bmi != null) parts.push(`BMI ${d.bmi}`);
    if (d.kcal_per_kg != null) parts.push(`${d.kcal_per_kg} kcal/kg`);
    if (d.activity) parts.push(`activity: ${(KH.targets.ACTIVITY_LABELS || {})[d.activity] || d.activity}`);
    const used = Object.entries(d.labs_used || {}).filter(([, v]) => v);
    const labs = used.length
      ? `Lab results used: ${used.map(([a, v]) => `${KH.kidney.ANALYTES[a].label.toLowerCase()} ${v.value} ${v.unit} (${KH.kidney.displayDate(v.taken_on)})`).join(', ')}.`
      : 'No recent lab results were used.';
    return h('p', { class: 'muted small derived' }, parts.length ? `Worked out for: ${parts.join(', ')}. ` : '', labs);
  }

  // ---------------------------------------------------------------------------
  // Lab results summary (the full view is js/views/labs.js)
  // ---------------------------------------------------------------------------
  async function loadLabsSummary() {
    const box = $('#pf-labs-summary');
    if (!KH.labs) return;
    try {
      const data = await KH.labs.load();
      clear(box);
      box.append(KH.labs.summary(data));
      const alertBox = clear($('#profile-lab-alert'));
      const alert = KH.labs.currentAlert(data);
      if (alert) alertBox.append(KH.labs.alertBanner(alert, { link: true }));
    } catch (err) {
      if (err.handled) return;
      clear(box).append(h('p', { class: 'muted small' }, `Lab results could not be loaded: ${err.detail || err.message}`));
    }
  }
  $('#pf-open-labs').addEventListener('click', () => router.show('labs'));
  $('#profile-open-settings').addEventListener('click', () => router.show('settings'));

  router.register('profile', () => {
    KH.loadProfile().then(() => {
      renderProfile();
      // "Review suggested targets" in the Labs view: suggest once the saved profile is in the form.
      if (state.profileAutoSuggest) { state.profileAutoSuggest = false; suggestTargetsIntoForm({ from: '#btn-suggest' }); }
    }).catch(toastError);
    loadLabsSummary();
  });
  KH.views.profile = { renderProfile, fillTargets, readTargets, suggestTargetsIntoForm, targetText, sameTarget, renderTargetsReview, refusalFor };
})();
