/* Kidney Diet Log — Profile view: about you, dialysis days, daily targets with "Suggest
   targets" (never auto-saved), the stale-targets notice, and the theme choice. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, api, state, toast, toastError, router, sheets } = KH;
  const { WEEKDAYS, WEEKDAYS_LONG } = KH.ui;
  const { numOrNull } = KH.util;

  const profileForm = $('#profile-form');
  (function buildDialysisDays() {
    const box = $('#pf-dialysis-days');
    WEEKDAYS.forEach((d, i) => {
      box.append(h('label', { class: 'wd-check', for: `pf-dd-${i}` },
        h('input', { type: 'checkbox', id: `pf-dd-${i}`, value: i, 'data-weekday': i }),
        h('span', {}, h('span', { class: 'sr-only' }, WEEKDAYS_LONG[i]), h('span', { 'aria-hidden': 'true' }, d))));
    });
  })();
  function syncDialysisDaysVisibility() { $('#pf-dialysis-days-field').hidden = $('#pf-dialysis').value !== 'hemodialysis'; }
  $('#pf-dialysis').addEventListener('change', syncDialysisDaysVisibility);
  function selectedDialysisDays() { return $$('#pf-dialysis-days input:checked').map((c) => Number(c.dataset.weekday)).sort(); }
  function renderProfile() {
    const p = state.profile;
    if (!p) return;
    $('#pf-name').value = p.name || '';
    $('#pf-weight').value = p.weight_kg ?? '';
    $('#pf-height').value = p.height_cm ?? '';
    $('#pf-stage').value = p.ckd_stage || '3b';
    $('#pf-dialysis').value = p.dialysis || 'none';
    $('#pf-diabetes').value = p.diabetes || 'type1';
    $('#pf-warn').value = Math.round((p.warn_fraction ?? 0.8) * 100);
    $('#pf-week-start').value = p.week_start === 'sunday' ? 'sunday' : 'monday';
    const dd = new Set((p.dialysis_days || []).map(Number));
    $$('#pf-dialysis-days input').forEach((c) => { c.checked = dd.has(Number(c.dataset.weekday)); });
    syncDialysisDaysVisibility();
    fillTargets(p.targets || {});
    $('#pf-theme').value = KH.theme.stored();
    $('#suggest-notes').hidden = true;
    renderTargetsStale();
    // A fresh database already has a profile row (with a creation timestamp); only call it
    // "saved" once the person has actually stored something.
    const hasContent = p.weight_kg != null || p.height_cm != null || !!p.name || Object.values(p.targets || {}).some((v) => v != null);
    $('#profile-saved').textContent = p.updated_at && hasContent ? `Last saved ${new Date(p.updated_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}` : '';
  }
  function fillTargets(targets) {
    for (const inp of $$('input[data-target]')) {
      const v = targets[inp.dataset.target];
      inp.value = typeof v === 'number' ? v : v && typeof v === 'object' && v.max != null ? v.max : '';
    }
    const pr = targets.protein_g;
    $('#tg-protein_min').value = pr && typeof pr === 'object' && pr.min != null ? pr.min : '';
    $('#tg-protein_max').value = pr == null ? '' : typeof pr === 'object' ? (pr.max ?? '') : pr;
  }
  function readTargets() {
    const targets = {};
    for (const inp of $$('input[data-target]')) targets[inp.dataset.target] = numOrNull(inp.value);
    const pmin = numOrNull($('#tg-protein_min').value), pmax = numOrNull($('#tg-protein_max').value);
    if (pmin == null && pmax == null) targets.protein_g = null;
    else if (pmin == null) targets.protein_g = pmax;
    else if (pmax == null) { const err = new Error('Protein needs a maximum when a minimum is set'); err.detail = err.message; throw err; }
    else if (pmin > pmax) { const err = new Error('Protein minimum must not exceed the maximum'); err.detail = err.message; throw err; }
    else targets.protein_g = { min: pmin, max: pmax };
    return targets;
  }
  sheets.onSubmit(profileForm, async (e) => {
    e.preventDefault();
    let targets;
    try { targets = readTargets(); } catch (err) { toastError(err); $('#tg-protein_max').focus(); return; }
    const warnPct = numOrNull($('#pf-warn').value);
    const body = {
      name: $('#pf-name').value.trim(),
      weight_kg: numOrNull($('#pf-weight').value),
      height_cm: numOrNull($('#pf-height').value),
      ckd_stage: $('#pf-stage').value,
      dialysis: $('#pf-dialysis').value,
      diabetes: $('#pf-diabetes').value,
      warn_fraction: warnPct != null ? Math.min(1, Math.max(0.5, warnPct / 100)) : 0.8,
      targets,
      dialysis_days: $('#pf-dialysis').value === 'hemodialysis' ? selectedDialysisDays() : [],
      week_start: $('#pf-week-start').value === 'sunday' ? 'sunday' : 'monday',
    };
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
      renderProfile();
      state.dayLoadedFor = null; state.trends = null; state.summary = null; state.plan = null; state.planStart = null; state.shopping = null;
      toast('Profile saved', 'ok');
    } catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  });
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
  $('#targets-stale-keep').addEventListener('click', () => { state.targetsStale = null; renderTargetsStale(); $('#btn-suggest').focus(); });
  $('#targets-stale-suggest').addEventListener('click', () => suggestTargetsIntoForm({ fromNotice: true }));
  $('#btn-suggest').addEventListener('click', () => suggestTargetsIntoForm());
  async function suggestTargetsIntoForm({ fromNotice = false } = {}) {
    const btn = fromNotice ? $('#targets-stale-suggest') : $('#btn-suggest');
    // The endpoint computes from the *saved* profile; check the form first so the person is
    // told what to do in plain words instead of seeing the server's 400 (finding: raw field name),
    // and is not handed numbers for a stage or dialysis setting the form no longer shows.
    const weight = numOrNull($('#pf-weight').value);
    const height = numOrNull($('#pf-height').value);
    const saved = state.profile || {};
    if (weight == null) { toast('Enter your weight (kg) first; the suggestions are per kg of body weight', 'error'); $('#pf-weight').focus(); return; }
    if (saved.weight_kg == null || Number(saved.weight_kg) !== weight || (saved.height_cm ?? null) !== height) {
      toast('Save profile first so the suggestion uses your weight and height', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    if ($('#pf-stage').value !== saved.ckd_stage || $('#pf-dialysis').value !== saved.dialysis || $('#pf-diabetes').value !== saved.diabetes) {
      toast('Save profile first so the suggestion uses your stage and dialysis setting', 'error');
      $('#btn-save-profile').focus();
      return;
    }
    btn.disabled = true;
    try {
      const res = await api.suggested();
      fillTargets(res.targets || {});
      const notes = $('#suggest-notes');
      clear(notes);
      notes.append(h('div', { class: 'notes-title' }, `Suggested starting points for ${settingText(saved)} filled in below (not saved yet). Discuss with your care team, then press Save profile.`));
      if (res.notes && res.notes.length) notes.append(h('ul', {}, res.notes.map((t) => h('li', {}, t))));
      notes.hidden = false;
      state.targetsStale = null; // the suggestion for the saved setting is in the form now
      renderTargetsStale();
      if (fromNotice) notes.focus();
      toast('Targets suggested; review and save', 'ok');
    } catch (err) { toastError(err); }
    finally { btn.disabled = false; }
  }

  router.register('profile', () => KH.loadProfile().then(renderProfile).catch(toastError));
  KH.views.profile = { renderProfile, fillTargets, suggestTargetsIntoForm };
})();
