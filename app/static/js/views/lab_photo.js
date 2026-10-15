/* Kidney Diet Log — read a lab report from a photo (KH.labPhoto; ARCHITECTURE.md "Lab report photos", docs/ai.md "Lab report
   photos"). Lives in the Labs view, below "Import from a spreadsheet".

   * Offered only when the server says the local AI can read a report (GET /api/ai/status → features.lab_report). A report photo
     can show a name, a date of birth and record numbers that cannot be removed from an image, so it is read only by the AI on the
     admin's own network, never by a cloud AI and never by a person's own provider. When it is not offered, the card says why
     (the server's own sentence, for example "Needs a local AI on your own network ..."). The demo and the preview never offer it.
   * The person takes or chooses a photo (redrawn on the device as a JPEG without camera data, like every AI photo), agrees to
     the consent sheet the first time (it says where the photo goes, that a report can show a name, a date of birth and record
     numbers, that the photo is not kept, and to crop it), and may look at "What will be sent?" first.
   * The AI only copies the printed results; the server keeps the app's own tests and units and drops the rest, with counts. The
     answer comes back as PROPOSED rows in the same kind of table as the CSV import. Every row starts UNTICKED, with the line
     "Read by AI from your photo. Check each value against the report before you tick it." A row whose date was not read (or could
     mean two days) needs the person's date before it can be ticked. Only ticked rows go to POST /api/labs/import (through
     KH.views.labs.saveImported, so the potassium banner and "what this changed" work exactly as for a CSV file). Nothing is
     saved by reading.

   Rules: everything the server sends is drawn with textContent (the h() helper), never as HTML; no inline script, handler or
   style; the only network calls are the app's own API (through KH.ai); the photo is held in memory until the person discards the
   result or saves, and is never stored. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear } = KH;

  const NOTICE = 'Read by AI from your photo. Check each value against the report before you tick it.';
  const MAX_RESULTS = 1000; // as the CSV import: POST /api/labs/import takes 1 to 1,000 results
  const plural = (n, singular, other) => `${n} ${n === 1 ? singular : other}`;

  const section = $('#lab-photo');
  const why = $('#lab-photo-why');
  const controls = $('#lab-photo-controls');
  const fileInput = $('#lab-photo-file');
  const readBtn = $('#lab-photo-read');
  const whatBtn = $('#lab-photo-what');
  const errorBox = $('#lab-photo-error');
  const results = $('#lab-photo-results');
  const photo = { file: null, jpeg: null }; // the chosen picture, and its redrawn JPEG (memory only)

  // ---------------------------------------------------------------------------
  // The review table (also what the Node page test drives)
  // ---------------------------------------------------------------------------
  const dayNumber = (iso) => (KH.kidney && KH.kidney.dayNumber ? KH.kidney.dayNumber(iso) : Date.parse(`${iso}T00:00:00Z`) / 86400000);
  const validDate = (iso, today) => /^\d{4}-\d{2}-\d{2}$/.test(iso || '') && iso >= '1900-01-01' && dayNumber(iso) <= dayNumber(today) + 1;
  const fmtDay = (iso) => (KH.views.labs && KH.views.labs.fmtDay ? KH.views.labs.fmtDay(iso) : iso);

  // The same test, date and shown value as a saved result (what POST /api/labs/import calls a duplicate).
  function savedKeys(existing) {
    const keys = new Set();
    for (const r of existing || []) {
      try { keys.add(`${r.analyte}|${r.taken_on}|${KH.kidney.formatValue(r.analyte, r.value)}`); } catch (e) { /* a result of a test this version does not know */ }
    }
    return keys;
  }
  function rowKey(r) {
    try { return `${r.analyte}|${r.taken_on}|${KH.kidney.formatValue(r.analyte, KH.kidney.convert(r.analyte, r.value, r.unit).value)}`; } catch (e) { return ''; }
  }

  /* review(box, answer, {existing, today, onSave, onDiscard}) draws the proposed rows of an `ok` answer into `box`:
     the notice, how many lines the app left out, the table (every row unticked), Save and Discard. `onSave(rows)` gets the
     ticked rows as {analyte, value, unit, taken_on, label, text}; the caller sends them. Returns {save, discard, rows}. */
  function review(box, answer, opts = {}) {
    const today = opts.today || KH.util.todayStr();
    const saved = savedKeys(opts.existing);
    const rows = (answer.rows || []).map((r, i) => ({ ...r, index: i, ticked: false, cb: null, tag: null, when: null }));
    clear(box);
    box.append(h('div', { class: 'settings-note caution', role: 'note' }, h('p', {}, h('strong', {}, answer.notice || NOTICE))));
    box.append(h('p', { class: 'lab-import-summary', role: 'status' },
      `${plural(rows.length, 'result', 'results')} read from your photo. None is ticked: tick the ones that match the report. Nothing is saved until you press Save.`));
    for (const line of answer.dropped_notes || []) box.append(h('p', { class: 'hint' }, line));

    const list = h('ul', { class: 'list labs-list lab-import-list lab-photo-list' });
    for (const r of rows) {
      const id = `lab-photo-row-${r.index}`;
      const cb = h('input', { type: 'checkbox', id });
      cb.checked = false; // every row starts unticked: the person checks it against the report first
      cb.disabled = !r.taken_on; // a row without a date cannot be ticked until the person enters one
      r.cb = cb;
      r.when = h('span', { class: 'lab-row-date' }, r.taken_on ? fmtDay(r.taken_on) : 'Date needed');
      r.tag = h('span', { class: 'lab-import-saved' });
      const li = h('li', { class: 'lab-row' }, cb, h('label', { for: id }, r.when, h('span', { class: 'lab-row-value' }, `${r.label} ${r.display}`), r.tag));
      if (!r.taken_on) {
        const dateId = `${id}-date`;
        const date = h('input', { type: 'date', id: dateId, min: '1900-01-01', max: KH.util.addDays(today, 1) });
        const printed = r.printed_date ? `Printed on the report as ${r.printed_date}. ` : '';
        r.dateInput = date;
        date.addEventListener('change', () => setDate(r, date.value));
        date.addEventListener('input', () => setDate(r, date.value));
        li.append(h('div', { class: 'field lab-photo-date' }, h('label', { for: dateId }, `Date of the test (${r.label} ${r.display})`), date,
          h('span', { class: 'hint warn' }, `${printed}${r.date_note || 'Enter the date of the test.'}`)));
      } else markSaved(r);
      cb.addEventListener('change', () => { r.ticked = cb.checked; update(); });
      list.append(li);
    }
    box.append(list);

    function markSaved(r) {
      r.tag.textContent = r.taken_on && saved.has(rowKey(r)) ? 'already saved' : '';
    }
    function setDate(r, value) {
      if (validDate(value, today)) {
        r.taken_on = value;
        r.cb.disabled = false;
        r.when.textContent = fmtDay(value);
      } else {
        r.taken_on = null;
        r.cb.checked = false;
        r.cb.disabled = true;
        r.ticked = false;
        r.when.textContent = 'Date needed';
      }
      markSaved(r);
      update();
    }

    const save = h('button', { class: 'btn primary', type: 'button', id: 'lab-photo-save' }, 'Save 0 results');
    const discard = h('button', { class: 'btn secondary', type: 'button', id: 'lab-photo-discard' }, 'Discard');
    const tooMany = h('p', { class: 'hint warn', hidden: true }, `Up to ${MAX_RESULTS.toLocaleString('en-US')} results at a time.`);
    const ticked = () => rows.filter((r) => r.cb.checked && r.taken_on);
    function update() {
      const n = ticked().length;
      save.textContent = n === 1 ? 'Save 1 result' : `Save ${n} results`;
      save.disabled = n === 0 || n > MAX_RESULTS;
      tooMany.hidden = n <= MAX_RESULTS;
    }
    update();
    save.addEventListener('click', () => {
      const kept = ticked().map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on, label: r.label, text: r.display }));
      if (kept.length && opts.onSave) opts.onSave(kept, save);
    });
    discard.addEventListener('click', () => { if (opts.onDiscard) opts.onDiscard(); });
    box.append(tooMany, h('div', { class: 'form-actions' }, save, discard));
    return { save, discard, rows, update };
  }

  // What to say instead of a table: the server's message (not a lab report, unreadable, nothing the app keeps) and the counts.
  function nothing(box, answer) {
    clear(box);
    box.append(h('p', { class: 'hint warn', role: 'status' }, answer.message || 'No result could be read from this photo.'));
    for (const line of answer.dropped_notes || []) box.append(h('p', { class: 'hint' }, line));
  }

  // ---------------------------------------------------------------------------
  // The card in the Labs view
  // ---------------------------------------------------------------------------
  function showError(err) {
    clear(errorBox);
    if (err) errorBox.append(h('p', {}, typeof err === 'string' ? err : (err.detail || err.message || 'Something went wrong')));
  }

  // Why the card offers nothing: the server's own sentence for the lab report route, or the person's opt-in.
  function whyOff(st) {
    if (st.opted_in === false) return 'Turn on AI ideas in Settings first: reading a lab report photo uses the AI on your own network.';
    const labs = st.routes && st.routes.labs;
    if (labs && labs.available) return 'The local AI on this server cannot read photos yet: your admin has not given it a vision model.';
    return (labs && labs.text) || 'Needs a local AI on your own network, which is not set up on this server, so it is off.';
  }

  async function show() {
    if (!section) return;
    let st = null;
    try { st = await KH.ai.status(); } catch (e) { st = null; }
    if (!st || !st.enabled) { section.hidden = true; return; } // AI is off here (or this is the demo): nothing to offer or explain
    section.hidden = false;
    if (st.features && st.features.lab_report) {
      controls.hidden = false;
      why.hidden = true;
      return;
    }
    controls.hidden = true;
    clear(results);
    why.hidden = false;
    why.textContent = whyOff(st);
  }

  const upload = (blob, dry) => KH.ai.uploadPhoto('lab-report', blob, dry);
  async function jpeg() {
    if (!photo.file) throw new Error('Choose a photo or screenshot of the report first.');
    if (!photo.jpeg) photo.jpeg = await KH.ai.prepareJpeg(photo.file);
    return photo.jpeg;
  }
  function forget() {
    photo.file = null;
    photo.jpeg = null;
    if (fileInput) fileInput.value = '';
  }

  async function read(btn) {
    showError(null);
    clear(results);
    btn.disabled = true;
    btn.textContent = 'Reading…';
    results.setAttribute('aria-busy', 'true');
    try {
      const blob = await jpeg();
      const answer = await KH.ai.withConsent('labs', () => upload(blob, false), () => upload(blob, true), btn, 'labs');
      if (!answer) return; // the person declined the consent sheet or the request
      if (answer.status !== 'ok') { nothing(results, answer); return; }
      let existing = [];
      try { existing = (await KH.labs.load()).labs; } catch (e) { /* the table still works; "already saved" is just not shown */ }
      review(results, answer, { existing, onSave, onDiscard });
      const first = $('#lab-photo-row-0');
      if (first && !first.disabled && first.focus) first.focus();
    } catch (e) {
      if (!e.handled && !e.cancelled) showError(e);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Read the report';
      results.removeAttribute('aria-busy');
    }
  }

  async function onSave(kept, saveBtn) {
    showError(null);
    saveBtn.disabled = true;
    try {
      await KH.views.labs.saveImported(kept, results, 'your photo', forget);
    } catch (e) {
      saveBtn.disabled = false;
      if (!e.handled) showError(e.status === 400 ? (e.detail || e.message) : e);
    }
  }
  function onDiscard() {
    forget();
    clear(results);
    showError(null);
    if (fileInput && fileInput.focus) fileInput.focus();
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      photo.file = (fileInput.files && fileInput.files[0]) || null;
      photo.jpeg = null;
      clear(results);
      showError(null);
    });
  }
  if (readBtn) readBtn.addEventListener('click', () => read(readBtn));
  if (whatBtn) {
    whatBtn.addEventListener('click', async () => {
      showError(null);
      try { await KH.ai.showSent(await upload(await jpeg(), true), { trigger: whatBtn }); } catch (e) { if (!e.handled) showError(e); }
    });
  }

  KH.labPhoto = { show, review, nothing, whyOff, NOTICE, MAX_RESULTS };
})();
