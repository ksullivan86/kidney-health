/* Kidney Diet Log — Lab results view (#labs; note 05 §4.8) and the lab helpers Profile uses (KH.labs).

   * Add a result: the test, the value, a unit picker (the person's user.units.labs setting picks the
     unit offered first; any accepted unit can be chosen), the date and a note. The value converted
     to the unit the rules use is echoed while typing ("1.94 mmol/L = 6.0 mg/dL", js/engine/
     kidney_function.js, the parity-checked twin of app/units.py), and an implausible number is
     flagged before saving. The server converts and checks again (POST /api/labs).
   * What it changed: the suggested targets before and after the result (GET /api/profile/
     suggested-targets twice); a change also raises the "Review suggested targets" prompt in Profile.
     Nothing is ever applied to the saved targets from here.
   * A red banner for a potassium of 6.0 mmol/L or more (KDIGO 2024 Table 28): the server's alert
     right after saving, and for the newest potassium result while it counts (GET /api/labs `alerts`:
     the server applies targets.lab_fresh_days.potassium, 90 days unless an admin changed it).
   * The kidney-function card (GET /api/labs/kidney-function): eGFR with its G category, the
     albuminuria category, and the server's "talk to your nephrologist" text. It never changes the
     saved stage.
   * Import from a spreadsheet (v0.3.1): a CSV file is read on this device (js/engine/lab_import.js); every
     result is listed with its conversion before anything is saved, columns that are not tests are never
     sent, and only the ticked results go to POST /api/labs/import, which checks each one again.
   * History: every result, newest first, grouped by test, with deletion. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, state, toast, toastError, router, sheets } = KH;
  const { todayStr, addDays, parseDate } = KH.util;
  const { splitFieldErrors, fieldError, clearFieldErrors } = KH.forms;
  const K = KH.kidney;
  const T = KH.targets;

  // The picker's order: the tests that change targets first, then kidney function, then the rest.
  const ANALYTE_ORDER = ['potassium', 'phosphate', 'albumin', 'bicarbonate', 'creatinine', 'cystatin_c', 'egfr', 'uacr', 'a1c'];
  // What each test does in this app (shown under the picker).
  const ROLE = {
    potassium: 'Can change the suggested potassium limit. 6.0 mmol/L or more shows an urgent warning.',
    phosphate: 'Can change the suggested phosphorus limit.',
    albumin: 'A low result is a sign of malnutrition risk and raises protein and calories.',
    bicarbonate: 'A low result adds a note about acid build-up.',
    creatinine: 'With your age and sex, gives an estimate of kidney function (eGFR).',
    cystatin_c: 'Gives an estimate of kidney function (eGFR), alone or with creatinine.',
    egfr: 'The eGFR printed on your report; it is used as it is.',
    uacr: 'Gives the albuminuria category (A1 to A3). It does not change food targets.',
    a1c: 'Kept with your results. It does not change food targets.',
  };
  // Handbook pages per test (tests/test_learn_links.py checks that each one exists).
  const LEARN = {
    potassium: '/learn/labs/blood-potassium/', phosphate: '/learn/labs/phosphate-calcium-pth/', albumin: '/learn/labs/albumin/',
    bicarbonate: '/learn/labs/bicarbonate/', creatinine: '/learn/labs/egfr-and-creatinine/', cystatin_c: '/learn/labs/egfr-and-creatinine/',
    egfr: '/learn/labs/egfr-and-creatinine/', uacr: '/learn/labs/uacr/', a1c: '/learn/labs/a1c/',
  };
  const TARGET_LABELS = [['calories_kcal', 'Calories'], ['protein_g', 'Protein'], ['carbs_g', 'Carbohydrate'], ['carbs_per_meal_g', 'Carbohydrate per meal'],
    ['fiber_g', 'Fiber'], ['sodium_mg', 'Sodium'], ['potassium_mg', 'Potassium'], ['phosphorus_mg', 'Phosphorus'], ['calcium_mg', 'Calcium'], ['fluid_ml', 'Fluid']];
  const FIELD_INPUT = { analyte: 'lab-analyte', value: 'lab-value', unit: 'lab-unit', taken_on: 'lab-date', note: 'lab-note' };

  const cache = { data: null, loading: null, unitSystem: null };
  const label = (analyte) => (K.ANALYTES[analyte] ? K.ANALYTES[analyte].label : analyte);
  function learnLink(analyte, text = null) {
    const href = KH.learn && LEARN[analyte] ? KH.learn.href(LEARN[analyte]) : null;
    if (!href) return null;
    return h('a', { class: 'learn-more', href, target: '_blank', rel: 'noopener' }, text || `Learn: ${label(analyte)}`, h('span', { class: 'sr-only' }, ' (opens in a new tab)'));
  }
  // "Oct 5, 2026": lab results span years, so the year is always shown.
  const fmtDay = (iso) => parseDate(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });

  // ---------------------------------------------------------------------------
  // Shared helpers (Profile's summary card uses them too)
  // ---------------------------------------------------------------------------
  function load() {
    if (cache.data) return Promise.resolve(cache.data);
    if (!cache.loading) {
      cache.loading = Promise.all([api.labs({ limit: 1000 }), api.kidneyFunction()])
        .then(([list, kf]) => { cache.data = { labs: list.labs || [], alerts: list.alerts || [], kf }; return cache.data; })
        .finally(() => { cache.loading = null; });
    }
    return cache.loading;
  }
  function invalidate() { cache.data = null; }
  function newestOf(labs, analyte) {
    let best = null;
    for (const r of labs) if (r.analyte === analyte && (!best || r.taken_on > best.taken_on || (r.taken_on === best.taken_on && r.id > best.id))) best = r;
    return best;
  }
  // The safety alert for the newest potassium result while it counts. The server decides (GET /api/labs
  // `alerts`, with the window the admin set in targets.lab_fresh_days.potassium), so this banner, Profile's
  // card and Suggest targets always agree; the app never applies a window of its own.
  function currentAlert(data) {
    return (data && data.alerts && data.alerts[0]) || null;
  }
  function alertBanner(alert, { link = false } = {}) {
    const help = KH.learn ? KH.learn.link('pages', alert.level === 'emergency' ? 'get_help_now' : 'blood_potassium') : null;
    return h('div', { class: `lab-alert level-${alert.level}` },
      h('p', { class: 'lab-alert-title' }, alert.level === 'emergency' ? 'Emergency: very high potassium' : 'Urgent: very high potassium'),
      h('p', {}, alert.message),
      h('p', { class: 'lab-alert-links' }, help, link ? [help ? ' · ' : null, h('button', { class: 'link-btn', type: 'button', onclick: () => router.show('labs') }, 'Lab results')] : null));
  }
  // Profile's card: the newest result of each test, and the kidney-function line.
  function summary(data) {
    const frag = document.createDocumentFragment();
    const latest = ANALYTE_ORDER.map((a) => newestOf(data.labs, a)).filter(Boolean);
    if (!latest.length) {
      frag.append(h('p', { class: 'muted small' }, 'No results yet. Add your latest blood test results: potassium and phosphate can change the suggested limits, and creatinine or eGFR shows which stage your kidney function suggests.'));
      return frag;
    }
    frag.append(h('ul', { class: 'labs-latest' }, latest.map((r) => h('li', {}, h('span', { class: 'labs-latest-name' }, r.label),
      h('b', {}, `${r.value} ${r.unit}`), h('span', { class: 'muted small' }, ` ${fmtDay(r.taken_on)}`)))));
    const eg = data.kf && data.kf.egfr;
    if (eg && eg.category) frag.append(h('p', { class: 'small' }, `Kidney function: eGFR ${eg.value != null ? eg.value : `${Math.min(eg.female, eg.male)}–${Math.max(eg.female, eg.male)}`} on ${fmtDay(eg.taken_on)}, stage ${eg.category}${eg.matches_profile === false ? ` (your profile says ${data.kf.profile_stage}; talk to your nephrologist)` : ''}.`));
    return frag;
  }

  // ---------------------------------------------------------------------------
  // Entry form
  // ---------------------------------------------------------------------------
  const form = $('#lab-form');
  const analyteSel = $('#lab-analyte');
  const unitSel = $('#lab-unit');
  const valueInp = $('#lab-value');
  const dateInp = $('#lab-date');
  for (const a of ANALYTE_ORDER) analyteSel.append(h('option', { value: a }, label(a)));
  const roleHint = h('span', { class: 'hint', id: 'lab-analyte-hint' });
  analyteSel.after(roleHint);
  analyteSel.setAttribute('aria-describedby', 'lab-analyte-hint');
  const filterSel = $('#labs-filter');
  for (const a of ANALYTE_ORDER) filterSel.append(h('option', { value: a }, label(a)));

  async function unitSystem() {
    if (cache.unitSystem) return cache.unitSystem;
    try {
      const res = await api.mySettings();
      const item = res && res.settings ? res.settings['user.units.labs'] : null;
      cache.unitSystem = item && K.UNIT_SYSTEMS.includes(item.value) ? item.value : 'us';
    } catch (err) { cache.unitSystem = 'us'; }
    return cache.unitSystem;
  }
  function fillUnits() {
    const a = K.ANALYTES[analyteSel.value];
    clear(unitSel);
    for (const u of Object.keys(a.units)) unitSel.append(h('option', { value: u }, u));
    unitSel.value = K.defaultUnit(a.key, cache.unitSystem || 'us');
    roleHint.textContent = ROLE[a.key] || '';
    echo();
  }
  // "4,6" (a decimal comma) reads as 4.6; anything else that is not a number is reported.
  function parseValue(raw) {
    const text = String(raw || '').trim();
    if (!text) return { empty: true };
    const t = /^\d+,\d+$/.test(text) ? text.replace(',', '.') : text;
    const n = Number(t);
    return /^\d*\.?\d+(e[+-]?\d+)?$/i.test(t) && Number.isFinite(n) ? { value: n } : { error: 'Enter the result as a number, for example 4.6' };
  }
  // The conversion echo (note 05 §4.2: "always show the converted value back before saving").
  function echo() {
    const el = $('#lab-echo');
    el.hidden = false;
    el.className = 'lab-echo';
    const v = parseValue(valueInp.value);
    if (v.empty) { el.textContent = 'The value is shown converted here before you save.'; return; }
    if (v.error) { el.textContent = v.error; el.classList.add('warn'); return; }
    try {
      const c = K.convert(analyteSel.value, v.value, unitSel.value);
      el.textContent = `Will be saved as ${c.display}.`;
    } catch (e) {
      el.textContent = e instanceof K.UnitError ? e.message : String(e);
      el.classList.add('warn');
    }
  }
  // Typing or changing the test or unit replaces an old error with the live echo.
  analyteSel.addEventListener('change', () => { clearErrors(); fillUnits(); });
  unitSel.addEventListener('change', () => { clearErrors(); echo(); });
  valueInp.addEventListener('input', () => { clearErrors(); echo(); });

  function clearErrors() { clearFieldErrors(form); clear($('#lab-form-error')).classList.remove('sr-only'); }
  // Each reason under its field (a conversion problem is about the value); the alert region says it
  // to screen readers. The echo steps aside so the reason is not shown twice.
  function showErrors(detail) {
    clearErrors();
    const parts = splitFieldErrors(detail);
    const box = $('#lab-form-error');
    box.append(parts.length > 1 ? h('ul', {}, parts.map((p) => h('li', {}, p.message))) : h('p', {}, parts[0] ? parts[0].message : detail));
    let first = null;
    for (const p of parts) {
      const input = document.getElementById(FIELD_INPUT[p.field] || 'lab-value');
      if (!input) continue;
      fieldError(input, p.message);
      if (!first) first = input;
    }
    box.classList.add('sr-only');
    $('#lab-echo').hidden = true;
    if (first) first.focus();
  }

  // GET /api/profile/suggested-targets, or why there is none.
  async function suggestionNow() {
    if (!state.profile || state.profile.weight_kg == null) return { unavailable: 'Save your weight in Profile to see suggested targets.' };
    const refusal = KH.views.profile.refusalFor(state.profile);
    if (refusal) return { unavailable: refusal.message };
    try { return { res: await api.suggested() }; } catch (err) {
      if (err.handled) return { unavailable: '' };
      return { unavailable: err.status === 422 ? err.detail : `Suggested targets could not be worked out: ${err.detail || err.message}` };
    }
  }
  function targetChanges(before, after) {
    const view = KH.views.profile;
    const out = [];
    for (const [key, name] of TARGET_LABELS) {
      const a = before.targets ? before.targets[key] : undefined;
      const b = after.targets ? after.targets[key] : undefined;
      if (!view.sameTarget(a, b)) out.push(`${name}: ${view.targetText(key, a)} → ${view.targetText(key, b)}`);
    }
    return out;
  }

  sheets.onSubmit(form, async (e) => {
    e.preventDefault();
    clearErrors();
    const v = parseValue(valueInp.value);
    if (v.empty || v.error) { showErrors(`value: ${v.empty ? 'Enter the result' : v.error}`); return; }
    if (!dateInp.value) { showErrors('taken_on: Enter the date of the test'); return; }
    // The same conversion and plausibility check as the server (parity-tested twin): say it now.
    try { K.convert(analyteSel.value, v.value, unitSel.value); } catch (err) {
      if (err instanceof K.UnitError) { showErrors(err.message); return; }
      throw err;
    }
    const body = { analyte: analyteSel.value, value: v.value, unit: unitSel.value, taken_on: dateInp.value, note: $('#lab-note').value.trim() };
    const btn = $('#lab-save');
    btn.disabled = true;
    try {
      const before = await suggestionNow();
      const saved = await api.addLab(body);
      invalidate();
      valueInp.value = '';
      $('#lab-note').value = '';
      echo();
      $('#labs-live').textContent = `Saved: ${saved.label} ${saved.display} on ${fmtDay(saved.taken_on)}.`;
      toast('Result saved', 'ok');
      renderAlert(saved.alerts && saved.alerts[0] ? saved.alerts[0] : null, true);
      const after = await suggestionNow();
      renderReview(saved, before, after);
      await refresh();
      valueInp.focus();
    } catch (err) {
      if (err.handled) return;
      if (err.status === 400) showErrors(err.detail || err.message); else toastError(err);
    } finally { btn.disabled = false; }
  });

  // ---------------------------------------------------------------------------
  // What the result changed (never applied: "Review suggested targets" opens Profile's suggestion)
  // ---------------------------------------------------------------------------
  // `imported` (an import's headline) replaces the one result's line: several results were saved at once.
  function renderReview(saved, before, after, imported = null) {
    const box = $('#labs-review');
    const body = clear($('#labs-review-body'));
    const go = $('#labs-review-go');
    go.hidden = true;
    const It = imported ? 'They' : 'It';
    if (imported) body.append(h('p', {}, h('b', {}, imported)));
    else {
      body.append(h('p', {}, h('b', {}, `${saved.label} ${saved.display}`), ` on ${fmtDay(saved.taken_on)} was saved.`));
      if (K.KIDNEY_ANALYTES.includes(saved.analyte)) body.append(h('p', {}, 'It is used for the kidney-function estimate below.'));
    }
    if (after.res && before.res) {
      const changes = targetChanges(before.res, after.res);
      if (after.res.derived && after.res.derived.lab_rules_enabled === false) {
        body.append(h('p', {}, KH.flags.MOCK
          ? 'The demo does not use lab results to change suggested targets until a clinician has reviewed the lab rules (an admin setting: Server administration → Server settings).'
          : 'This server does not use lab results to change suggested targets (an admin setting).'));
      } else if (changes.length) {
        body.append(h('p', {}, `${It} ${imported ? 'change' : 'changes'} your suggested targets (your saved targets stay as they are until you save new ones in Profile):`),
          h('ul', {}, changes.map((c) => h('li', {}, c))));
        go.hidden = false;
      } else {
        body.append(h('p', {}, `${It} ${imported ? 'do' : 'does'} not change your suggested targets.`));
      }
    } else if (after.unavailable) {
      body.append(h('p', { class: 'muted' }, after.unavailable));
    }
    const more = imported ? null : learnLink(saved.analyte);
    if (more) body.append(h('p', { class: 'notes-learn' }, more));
    box.hidden = false;
    noteReview(before, after, imported ? 'imported lab results' : `new ${saved.label.toLowerCase()} result`);
  }
  // Profile's "Review suggested targets" prompt: every change since the suggestion that was current
  // before the first unreviewed result (results added and deleted since then count together); it
  // goes away when nothing differs any more, when targets are saved, or when it is dismissed.
  function noteReview(before, after, what) {
    if (!after.res || (after.res.derived && after.res.derived.lab_rules_enabled === false)) return;
    const rv = state.targetsReview;
    const baseline = rv && rv.baseline ? rv.baseline : before.res ? before.res.targets : null;
    if (!baseline) return;
    const changes = targetChanges({ targets: baseline }, after.res);
    state.targetsReview = changes.length ? { baseline, what: rv ? 'new lab results' : what, changes } : null;
  }
  $('#labs-review-dismiss').addEventListener('click', () => { $('#labs-review').hidden = true; state.targetsReview = null; valueInp.focus(); });
  $('#labs-review-go').addEventListener('click', () => {
    state.profileAutoSuggest = true; // Profile runs "Suggest targets" once the saved profile is on screen
    router.show('profile');
  });
  $('#labs-back').addEventListener('click', () => router.show('profile'));

  // ---------------------------------------------------------------------------
  // Import from a spreadsheet (v0.3.1). The file is read here; nothing is sent until "Save", and then only the
  // ticked results (KH.labImport.requestBody: test, value, unit and date), never the file or its other columns.
  // ---------------------------------------------------------------------------
  const LI = KH.labImport;
  const importFile = $('#lab-import-file');
  const importBox = $('#lab-import-preview');
  const imp = { text: null, units: {}, dateOrder: null, unticked: new Set() }; // unticked: ids the person cleared
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function importError(message) {
    clear(importBox).append(h('p', { class: 'form-error', role: 'alert' }, message));
  }
  importFile.addEventListener('change', async () => {
    const file = importFile.files && importFile.files[0];
    clear(importBox);
    imp.text = null;
    if (!file) return;
    if (file.size > LI.MAX_CHARS) { importError('The file is larger than 1 MB. Split it into smaller files.'); return; }
    try { imp.text = await file.text(); } catch (e) { importError('The file could not be read. Save it again as CSV and choose it again.'); return; }
    imp.units = {};
    imp.unticked = new Set();
    imp.dateOrder = (cache.unitSystem || 'us') === 'si' ? 'dmy' : 'mdy';
    renderImport();
  });

  function renderImport() {
    const existing = cache.data ? cache.data.labs : [];
    const a = LI.analyse(imp.text, { today: todayStr(), units: imp.units, dateOrder: imp.dateOrder, existing });
    const box = clear(importBox);
    if (a.problem) { importError(a.problem); return; }

    // What the person sets: the unit of a column whose header has none (or one the app does not know), and
    // the order of dates written 03/04/2026 unless a day above 12 settles it.
    const settings = h('div', { class: 'form-grid lab-import-settings' });
    for (const col of a.columns) {
      const chosen = Object.prototype.hasOwnProperty.call(imp.units, col.index);
      if (!col.needsUnit && !chosen) continue;
      const id = `lab-import-unit-${col.index}`;
      const sel = h('select', { id }, h('option', { value: '' }, 'Choose the unit'), col.units.map((u) => h('option', { value: u }, u)));
      sel.value = chosen ? imp.units[col.index] : '';
      sel.addEventListener('change', () => {
        if (sel.value) imp.units[col.index] = sel.value; else delete imp.units[col.index];
        renderImport();
        const again = document.getElementById(id);
        if (again) again.focus();
      });
      settings.append(h('div', { class: 'field' }, h('label', { for: id }, `Unit of “${col.header}”`), sel,
        h('span', { class: col.problem ? 'hint warn' : 'hint' }, col.problem || 'Use the unit printed on your report.')));
    }
    if (a.slashDates) {
      const sel = h('select', { id: 'lab-import-dates' },
        h('option', { value: 'mdy' }, 'Month/day/year (03/04 is March 4)'), h('option', { value: 'dmy' }, 'Day/month/year (03/04 is April 3)'));
      sel.value = a.dateOrder;
      sel.disabled = a.dateOrderDetected;
      sel.addEventListener('change', () => { imp.dateOrder = sel.value; renderImport(); const again = $('#lab-import-dates'); if (again) again.focus(); });
      settings.append(h('div', { class: 'field' }, h('label', { for: 'lab-import-dates' }, 'Dates are written'), sel,
        h('span', { class: 'hint' }, a.dateOrderDetected ? 'Worked out from a day above 12.' : 'Check the dates below.')));
    }
    if (settings.childNodes.length) box.append(settings);

    const ok = a.results.filter((r) => !r.problem);
    const refused = a.results.length - ok.length;
    const already = ok.filter((r) => r.saved).length;
    const waiting = a.columns.filter((c) => c.needsUnit).map((c) => `“${c.header}”`);
    const lines = [`${plural(a.rows, 'row', 'rows')} read: ${plural(ok.length, 'result', 'results')} to check`];
    if (already) lines.push(`${already} already saved`);
    if (refused) lines.push(`${refused} cannot be imported`);
    box.append(h('p', { class: 'lab-import-summary', role: 'status' }, `${lines.join(', ')}.`));
    if (waiting.length) box.append(h('p', { class: 'hint warn' }, `Choose the unit of ${waiting.join(', ')} to see those results.`));
    if (a.ignored.length) box.append(h('p', { class: 'muted small' }, `Not read, and not sent: ${a.ignored.join(', ')}.`));

    const list = h('ul', { class: 'list labs-list lab-import-list' });
    const ticks = [];
    for (const r of a.results) {
      const when = r.taken_on ? fmtDay(r.taken_on) : '';
      if (r.problem) {
        list.append(h('li', { class: 'lab-row lab-import-problem' }, h('div', { class: 'lab-row-main' },
          h('span', { class: 'lab-row-date' }, when), h('span', { class: 'lab-row-value' }, `${r.label} ${r.text}`),
          h('span', { class: 'lab-import-why' }, `Not imported (row ${r.row}): ${r.problem}`))));
        continue;
      }
      const id = `lab-import-${r.row}-${r.column}`;
      const cb = h('input', { type: 'checkbox', id });
      cb.checked = !r.saved && !imp.unticked.has(id); // a new unit or date order redraws the list: keep the person's choices
      cb.addEventListener('change', () => {
        if (cb.checked) imp.unticked.delete(id); else imp.unticked.add(id);
        updateSave();
      });
      ticks.push([cb, r]);
      list.append(h('li', { class: 'lab-row' }, cb, h('label', { for: id },
        h('span', { class: 'lab-row-date' }, when), h('span', { class: 'lab-row-value' }, `${r.label} ${r.display}`),
        r.saved ? h('span', { class: 'lab-import-saved' }, 'already saved') : null)));
    }
    if (list.childNodes.length) box.append(list);

    const save = h('button', { class: 'btn primary', type: 'button', id: 'lab-import-save' }, 'Save');
    const cancel = h('button', { class: 'btn secondary', type: 'button', id: 'lab-import-cancel' }, 'Cancel');
    const tooMany = h('p', { class: 'hint warn', hidden: true }, `Up to ${LI.MAX_RESULTS.toLocaleString('en-US')} results at a time: untick some, or split the file.`);
    function updateSave() {
      const n = ticks.filter(([cb]) => cb.checked).length;
      save.textContent = n === 1 ? 'Save 1 result' : `Save ${n} results`;
      save.disabled = n === 0 || n > LI.MAX_RESULTS;
      tooMany.hidden = n <= LI.MAX_RESULTS;
    }
    updateSave();
    cancel.addEventListener('click', () => { imp.text = null; imp.unticked = new Set(); importFile.value = ''; clear(importBox); importFile.focus(); });
    save.addEventListener('click', async () => {
      const kept = ticks.filter(([cb]) => cb.checked).map(([, r]) => r);
      if (!kept.length) return;
      save.disabled = true;
      try {
        const before = await suggestionNow();
        const res = await api.importLabs(LI.requestBody(kept));
        invalidate();
        imp.text = null;
        importFile.value = '';
        const done = [`Saved ${plural(res.saved, 'result', 'results')}`];
        if (res.duplicates) done.push(`${res.duplicates} already saved`);
        if (res.refused.length) done.push(`${res.refused.length} refused`);
        const out = clear(importBox);
        out.append(h('p', { class: 'lab-import-summary', role: 'status' }, `${done.join(', ')}.`));
        if (res.refused.length) {
          out.append(h('ul', { class: 'lab-import-refused' }, res.refused.map((x) => {
            const r = kept[x.index];
            return h('li', {}, `${r.label} ${r.text} (${fmtDay(r.taken_on)}): ${x.reason}`);
          })));
        }
        toast(`${done.join(', ')}`, 'ok');
        $('#labs-live').textContent = `${done.join(', ')}.`;
        renderAlert(res.alerts && res.alerts[0] ? res.alerts[0] : null, Boolean(res.alerts && res.alerts.length));
        if (res.saved) renderReview(null, before, await suggestionNow(), `${plural(res.saved, 'result was', 'results were')} saved from your file.`);
        await refresh();
      } catch (err) {
        save.disabled = false;
        if (err.handled) return;
        if (err.status === 400) importError(err.detail || err.message); else toastError(err);
      }
    });
    box.append(tooMany, h('div', { class: 'form-actions' }, save, cancel));
  }

  // ---------------------------------------------------------------------------
  // Banner, kidney-function card and history
  // ---------------------------------------------------------------------------
  function renderAlert(alert, justSaved = false) {
    const box = clear($('#labs-alert'));
    if (alert) box.append(alertBanner(alert));
    if (alert && justSaved) { try { box.scrollIntoView({ block: 'start' }); } catch (e) { /* old browsers */ } }
  }
  function renderKidneyFunction(kf) {
    const box = clear($('#kf-body'));
    if (!kf) return;
    const tiles = h('div', { class: 'kf-tiles' });
    const eg = kf.egfr;
    if (eg) {
      const value = eg.value != null ? String(eg.value) : `${Math.min(eg.female, eg.male)}–${Math.max(eg.female, eg.male)}`;
      tiles.append(h('div', { class: 'kf-tile' }, h('span', { class: 'kf-label' }, 'eGFR'),
        h('span', { class: 'kf-value' }, value, h('span', { class: 'kf-unit' }, ' mL/min/1.73 m²')),
        h('span', { class: 'kf-cat' }, eg.category ? `Stage ${eg.category}` : 'No stage suggested'),
        h('span', { class: 'muted small' }, `${eg.method_label}, ${fmtDay(eg.taken_on)}`)));
    }
    const al = kf.albuminuria;
    if (al) {
      tiles.append(h('div', { class: 'kf-tile' }, h('span', { class: 'kf-label' }, 'Urine albumin (UACR)'),
        h('span', { class: 'kf-value' }, String(al.entered_value), h('span', { class: 'kf-unit' }, ` ${al.entered_unit}`)),
        h('span', { class: 'kf-cat' }, `${al.category}: ${al.label}`),
        h('span', { class: 'muted small' }, fmtDay(al.taken_on))));
    }
    if (tiles.childNodes.length) box.append(tiles);
    box.append(h('p', { class: 'kf-message' }, kf.message));
    if (eg && eg.matches_profile === false) box.append(h('p', { class: 'small' }, 'Your profile keeps the stage you saved; only your nephrologist can say whether it has changed.'));
    const links = [learnLink('egfr', 'Learn: eGFR and creatinine'), al ? learnLink('uacr', 'Learn: urine albumin') : null].filter(Boolean);
    if (links.length) box.append(h('p', {}, links.flatMap((a, i) => (i ? [' · ', a] : [a]))));
  }
  function renderHistory(labs) {
    const box = clear($('#labs-history'));
    const only = filterSel.value;
    const shown = ANALYTE_ORDER.filter((a) => !only || a === only).map((a) => [a, labs.filter((r) => r.analyte === a)]).filter(([, rows]) => rows.length);
    if (!shown.length) {
      box.append(h('p', { class: 'empty-state' }, only ? `No ${label(only).toLowerCase()} results yet.` : 'No results yet. Add one above.'));
      return;
    }
    for (const [a, rows] of shown) {
      const list = h('ul', { class: 'list labs-list' });
      for (const r of rows) {
        const veryHigh = r.analyte === 'potassium' && Number(r.value) >= T.POTASSIUM_VERY_HIGH;
        const del = h('button', { class: 'link-btn danger-link', type: 'button', 'aria-label': `Delete ${r.label} ${r.display} from ${fmtDay(r.taken_on)}` }, 'Delete');
        const actions = h('div', { class: 'lab-row-actions' }, del);
        del.addEventListener('click', (ev) => KH.confirm.inline(actions, ev.currentTarget, {
          message: `Delete ${r.label.toLowerCase()} ${r.display} from ${fmtDay(r.taken_on)}?`,
          onConfirm: async () => {
            await api.deleteLab(r.id);
            invalidate();
            if (state.targetsReview) noteReview({}, await suggestionNow(), null);
            toast('Result deleted', 'ok');
            $('#labs-live').textContent = `Deleted ${r.label} ${r.display} from ${fmtDay(r.taken_on)}.`;
            await refresh();
            $('#labs-history-h').focus();
            return true;
          },
        }));
        list.append(h('li', { class: 'lab-row' },
          h('div', { class: 'lab-row-main' },
            h('span', { class: 'lab-row-date' }, fmtDay(r.taken_on)),
            h('span', { class: 'lab-row-value' }, r.display, veryHigh ? h('span', { class: 'badge very-high' }, 'Very high') : null),
            r.note ? h('span', { class: 'lab-row-note' }, r.note) : null),
          actions));
      }
      const more = learnLink(a);
      box.append(h('section', { class: 'labs-group', 'aria-label': label(a) }, h('h3', { class: 'labs-group-title' }, label(a), more ? [' ', more] : null), list));
    }
  }
  filterSel.addEventListener('change', () => { if (cache.data) renderHistory(cache.data.labs); });

  async function refresh() {
    try {
      const data = await load();
      renderAlert(currentAlert(data));
      renderKidneyFunction(data.kf);
      renderHistory(data.labs);
    } catch (err) {
      if (err.handled) return;
      clear($('#labs-history')).append(h('p', { class: 'form-error' }, `Lab results could not be loaded: ${err.detail || err.message}`));
    }
  }

  router.register('labs', async () => {
    $('#labs-title').focus();
    if (!dateInp.value) dateInp.value = todayStr();
    dateInp.max = addDays(todayStr(), 1);
    // The unit offered first follows Settings → Preferences (it may have changed since the last visit).
    const before = cache.unitSystem;
    cache.unitSystem = null;
    const system = await unitSystem();
    if (!unitSel.options.length || system !== before) fillUnits();
    if (!state.profile) KH.loadProfile().catch(toastError);
    invalidate();
    refresh();
  });

  KH.labs = { load, invalidate, currentAlert, alertBanner, summary, learnLink, LEARN, ANALYTE_ORDER };
  KH.views.labs = { refresh, renderReview, parseValue };
})();
