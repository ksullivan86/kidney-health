/* Kidney Diet Log — Symptoms: the Today card, the add / edit sheet and the Trends list (ARCHITECTURE.md "Symptoms log").

   The app records a symptom with a date and a severity and shows it back. It never says what a symptom means, never
   names a cause and never suggests a treatment. The one thing it adds is a pointer: a symptom that the handbook's Get
   help now page lists as a warning sign carries the handbook's own words and a link to that page (the server sends
   them in `red_flag`; js/engine/symptoms.js is the demo's copy). A severe one is shown as a block that stands out and is
   listed first.

   * Today (js/views/today.js calls KH.symptoms.today(date) after it draws a day): the day's symptoms, Edit and Delete
     for each, and Add, which opens the sheet. Nothing is saved until Save. Days after today cannot be added to.
   * Trends (js/views/trends.js calls KH.symptoms.trends(start, end)): one row per symptom with the number of days, the
     worst severity, a strip of marks over the period (a mark's height is its severity; the dates and the words are
     under it, so nothing depends on colour or on seeing the strip) and the same handbook line. No chart library.
   * Symptoms are not kept offline: a save needs the connection to the server, and the card says so when it cannot load.

   All text goes in with textContent (h() children), never as HTML; no inline script or style. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, api, toast, toastError, sheets } = KH;
  const R = KH.symptomRules;
  const { ratingIcon } = KH.ui;
  const { todayStr, addDays, daysBetween, fmtDateShort, fmtMonthDay } = KH.util;

  const dlg = $('#sheet-symptom');
  const todayBody = $('#symptoms-today-body');
  const addBtn = $('#symptoms-add');
  if (!dlg || !todayBody || !addBtn || !R) return;
  sheets.setup(dlg);

  const live = (text) => { const el = $('#symptoms-live'); if (el) el.textContent = text; };
  const lower = (s) => String(s).toLowerCase();
  const message = (text) => h('p', { class: 'symptoms-empty' }, text);
  const sevWord = (n) => lower(R.SEVERITY_LABELS[n]);

  // ---- the handbook's line ------------------------------------------------------------------------------------------
  // `rf` is the server's red_flag: { level, text, href, link_text, prominent }. The link goes where the handbook is
  // served (or published); with no handbook there is no link and the line still names the handbook's heading.
  function flagEl(rf) {
    const target = KH.learn ? KH.learn.href(rf.href) : null;
    const link = target ? h('a', { class: 'learn-more', href: target, target: '_blank', rel: 'noopener' }, rf.link_text, h('span', { class: 'sr-only' }, ' (opens in a new tab)')) : null;
    return h('p', { class: `sym-flag${rf.prominent ? ' prominent' : ''}` },
      ratingIcon(rf.prominent ? 'over' : 'caution', { decorative: true }),
      h('span', {}, rf.prominent ? h('b', {}, 'Severe. ') : null, rf.text, link ? [' ', link] : null));
  }

  // ---- Today --------------------------------------------------------------------------------------------------------
  let shownDate = null;
  let todayReq = 0;

  function entryEl(s) {
    const what = `${s.name}, ${sevWord(s.severity)}, ${fmtDateShort(s.date)}`;
    const edit = h('button', { class: 'link-btn', type: 'button', 'aria-label': `Edit ${what}` }, 'Edit');
    const del = h('button', { class: 'link-btn danger-link', type: 'button', 'aria-label': `Delete ${what}` }, 'Delete');
    const actions = h('div', { class: 'sym-actions' }, edit, del);
    edit.addEventListener('click', (ev) => openSheet({ symptom: s, trigger: ev.currentTarget }));
    del.addEventListener('click', (ev) => KH.confirm.inline(actions, ev.currentTarget, {
      message: `Delete ${s.name} (${sevWord(s.severity)}) from ${fmtDateShort(s.date)}?`,
      onConfirm: async () => {
        await api.deleteSymptom(s.id);
        toast('Symptom deleted', 'ok');
        live(`Deleted ${what}.`);
        await loadToday(shownDate || todayStr());
        const heading = $('#symptoms-today-h');
        if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus(); }
        return true;
      },
    }));
    return h('li', { class: 'sym-item' },
      h('div', { class: 'sym-main' }, h('span', { class: 'sym-name' }, s.name), h('span', { class: `sym-sev sev-${s.severity}` }, s.severity_label), actions),
      s.note ? h('p', { class: 'sym-note' }, s.note) : null,
      s.red_flag ? flagEl(s.red_flag) : null);
  }

  function renderToday(rows) {
    clear(todayBody);
    if (!rows.length) { todayBody.append(message('No symptoms recorded for this day.')); return; }
    const first = (s) => (s.red_flag && s.red_flag.prominent ? 0 : 1);
    const sorted = rows.slice().sort((a, b) => (first(a) - first(b)) || (a.id - b.id));
    todayBody.append(h('ul', { class: 'sym-list' }, sorted.map(entryEl)));
  }

  async function loadToday(date) {
    const req = ++todayReq;
    shownDate = date;
    const future = date > todayStr();
    addBtn.disabled = future;
    if (future) {
      clear(todayBody).append(message('You can record symptoms for today and for days that have passed.'));
      return;
    }
    try {
      const res = await api.symptoms(date, date);
      if (req !== todayReq) return;
      renderToday(res.symptoms || []);
    } catch (err) {
      if (req !== todayReq) return;
      if (err && err.handled) return;
      clear(todayBody).append(message(err && err.status ? 'Symptoms could not be loaded.' : 'Symptoms need a connection to your server, and there is none right now.'),
        h('button', { class: 'link-btn', type: 'button', onclick: () => loadToday(date) }, 'Try again'));
    }
  }

  // ---- the sheet ----------------------------------------------------------------------------------------------------
  const form = $('#symptom-form');
  const kind = $('#symptom-kind');
  const labelField = $('#symptom-label-field');
  const labelInput = $('#symptom-label');
  const sevGroup = $('#symptom-severity');
  const dateInput = $('#symptom-date');
  const noteInput = $('#symptom-note');
  const flagBox = $('#symptom-flag');
  const errorBox = $('#symptom-error');
  const saveBtn = $('#symptom-save');
  const S = { editing: null, busy: false };

  kind.append(h('option', { value: '' }, 'Choose a symptom'),
    ...R.SYMPTOMS.map(([key, name]) => h('option', { value: key }, key === 'other' ? 'Other (name it)' : name)));

  const severity = () => { const r = $('input:checked', sevGroup); return r ? Number(r.value) : 0; };
  const setSeverity = (n) => { for (const r of sevGroup.querySelectorAll('input')) r.checked = Number(r.value) === n; };
  const showError = (text) => { errorBox.textContent = text || ''; errorBox.hidden = !text; };

  // What the handbook says about the chosen symptom, before it is saved (the same line the list shows afterwards).
  function syncForm() {
    labelField.hidden = kind.value !== 'other';
    clear(flagBox);
    const rf = R.redFlag(kind.value, severity());
    if (rf) flagBox.append(flagEl(rf));
  }
  kind.addEventListener('change', syncForm);
  sevGroup.addEventListener('change', syncForm);

  function openSheet({ symptom = null, trigger = null } = {}) {
    S.editing = symptom;
    $('#sheet-symptom-title').textContent = symptom ? 'Edit symptom' : 'Add a symptom';
    kind.value = symptom ? symptom.symptom : '';
    labelInput.value = symptom ? symptom.label : '';
    setSeverity(symptom ? symptom.severity : 0);
    const day = shownDate && shownDate <= todayStr() ? shownDate : todayStr();
    dateInput.value = symptom ? symptom.date : day;
    dateInput.max = todayStr();
    noteInput.value = symptom ? symptom.note : '';
    showError('');
    syncForm();
    sheets.open(dlg, trigger, kind);
  }
  addBtn.addEventListener('click', (ev) => openSheet({ trigger: ev.currentTarget }));

  sheets.onSubmit(form, async (e) => {
    e.preventDefault();
    if (S.busy) return;
    const key = kind.value;
    if (!R.KEYS.includes(key)) { showError('Choose which symptom it is.'); kind.focus(); return; }
    if (key === 'other' && !labelInput.value.trim()) { showError('Name the symptom, for example dry mouth.'); labelInput.focus(); return; }
    if (!severity()) { showError('Choose how bad it is: mild, moderate or severe.'); $('input', sevGroup).focus(); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) { showError('Choose the date.'); dateInput.focus(); return; }
    const body = { date: dateInput.value, symptom: key, severity: severity(), note: noteInput.value };
    if (key === 'other') body.label = labelInput.value;
    const editing = S.editing;
    S.busy = true;
    saveBtn.disabled = true;
    showError('');
    try {
      const saved = editing ? await api.updateSymptom(editing.id, body) : await api.addSymptom(body);
      dlg.close();
      toast(editing ? 'Symptom updated' : 'Symptom saved', 'ok');
      live(`${editing ? 'Updated' : 'Saved'} ${saved.name}, ${sevWord(saved.severity)}, ${fmtDateShort(saved.date)}.`);
      await loadToday(shownDate || todayStr());
    } catch (err) {
      if (err && err.status === 400) showError(err.detail || err.message);
      else toastError(err);
    } finally {
      S.busy = false;
      saveBtn.disabled = false;
    }
  });

  // ---- Trends -------------------------------------------------------------------------------------------------------
  let trendsReq = 0;

  function groupEl(g, start, end) {
    const marks = [];
    const byDate = new Map(g.days.map((d) => [d.date, d.severity]));
    for (let day = start; day <= end; day = addDays(day, 1)) marks.push(h('i', { 'data-sev': byDate.get(day) || null }));
    const dates = g.days.map((d) => `${fmtMonthDay(d.date)} ${sevWord(d.severity)}`).join(', ');
    return h('li', { class: 'sym-group' },
      h('div', { class: 'sym-group-head' },
        h('span', { class: 'sym-group-name' }, g.name),
        h('span', { class: 'sym-group-count' }, `${g.dayCount} ${g.dayCount === 1 ? 'day' : 'days'}, worst: ${sevWord(g.worst)}`)),
      h('div', { class: 'sym-strip', 'aria-hidden': 'true' }, marks),
      h('p', { class: 'sym-axis', 'aria-hidden': 'true' }, h('span', {}, fmtMonthDay(start)), h('span', {}, fmtMonthDay(end))),
      h('p', { class: 'sym-dates' }, dates),
      g.red_flag ? flagEl(g.red_flag) : null);
  }

  async function trends(start, end) {
    const body = $('#symptoms-trends-body');
    const sub = $('#symptoms-trends-sub');
    if (!body) return;
    const req = ++trendsReq;
    const days = daysBetween(start, end) + 1;
    if (sub) sub.textContent = `last ${days} days`;
    try {
      const res = await api.symptoms(start, end);
      if (req !== trendsReq) return;
      const groups = R.summarise(res.symptoms || []);
      clear(body);
      if (!groups.length) { body.append(message('No symptoms recorded in this period. You can add them on Today.')); return; }
      const first = (g) => (g.red_flag && g.red_flag.prominent ? 0 : 1);
      groups.sort((a, b) => first(a) - first(b)); // a stable sort: the rest stay most days first
      body.append(h('ul', { class: 'sym-groups' }, groups.map((g) => groupEl(g, start, end))));
    } catch (err) {
      if (req !== trendsReq || (err && err.handled)) return;
      clear(body).append(message(err && err.status ? 'Symptoms could not be loaded.' : 'Symptoms need a connection to your server, and there is none right now.'));
    }
  }

  KH.symptoms = { today: loadToday, trends, open: openSheet };
})();
