/* Kidney Diet Log — lab results from Apple Health clinical records (KH.labFhir; ARCHITECTURE.md "Lab results from Apple Health clinical
   records", docs/targets-and-labs.md). Lives in the Labs view, below "Import from a spreadsheet".

   * The person unzips the Health app's "Export All Health Data" zip in the Files app, opens apple_health_export/clinical-records/ and
     chooses its JSON files here (a pick of up to 2,000 files, 1 MB each). THE FILES ARE READ ON THIS DEVICE and never uploaded: each is
     read with File.text(), handed to KH.fhirLabs (js/engine/fhir_labs.js) and let go of; a file over 1 MB is not even read. Names, ids and
     providers inside the files are never looked at, and no file or file name is sent anywhere.
   * What the engine finds is shown in the same kind of table as the CSV import, with a headline ("41 results found in 380 files; ...")
     and the refusals with their reasons. The data comes from the person's health system, not from an AI, so the new results start
     TICKED (as in the CSV import); results already saved are not. Nothing is saved until Save; then only the ticked rows (test, value,
     unit and day) go to POST /api/labs/import through KH.views.labs.saveImported, so the potassium banner and "what this changed" work
     exactly as for a CSV file.

   Rules: everything that comes from a file is drawn with textContent (the h() helper), never as HTML; no inline script, handler or
   style; the only network call is the app's own API, through saveImported; nothing is stored in the browser. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear } = KH;
  const FL = KH.fhirLabs;

  const BATCH = 16; // files read at the same time
  const plural = (n, singular, other) => `${n} ${n === 1 ? singular : other}`;
  const fmtDay = (iso) => (KH.views && KH.views.labs && KH.views.labs.fmtDay ? KH.views.labs.fmtDay(iso) : iso);

  const input = $('#lab-fhir-file');
  const box = $('#lab-fhir-preview');
  let pick = 0; // which pick is current; choosing again while one is still being read drops the older one

  function showError(message) {
    clear(box).append(h('p', { class: 'form-error', role: 'alert' }, message));
  }

  /* One file for the engine: {name, size, text}; {name, size} when it is over the limit (never read); {name, unreadable: true}. */
  async function readOne(file) {
    const name = file && file.name ? String(file.name) : '';
    if (!file || typeof file.size !== 'number') return { name, unreadable: true };
    if (file.size > FL.MAX_FILE_BYTES) return { name, size: file.size };
    try {
      return { name, size: file.size, text: await file.text() };
    } catch (e) {
      return { name, unreadable: true };
    }
  }

  /* review(box, analysis, {onSave, onCancel}) draws an analysis of KH.fhirLabs (start().finish()): the headline, the table (new rows
     ticked), the refusals, Save and Cancel. onSave(kept, saveButton) gets the ticked rows as {analyte, value, unit, taken_on, label,
     text}; the caller sends them. Returns {save, cancel, rows}. */
  function review(into, analysis, opts = {}) {
    clear(into);
    if (analysis.problem) {
      into.append(h('p', { class: 'form-error', role: 'alert' }, analysis.problem));
      return { save: null, cancel: null, rows: [], headline: null };
    }
    const headline = h('p', { class: 'lab-import-summary', role: 'status', id: 'lab-fhir-summary', tabindex: '-1' }, `${analysis.summary.join('; ')}.`);
    into.append(headline);
    const rows = analysis.results.map((r, i) => ({ ...r, index: i, cb: null }));
    if (!rows.length) {
      into.append(h('p', { class: 'hint warn' }, 'No lab result the app keeps was found. Choose the files in the clinical-records folder (the ones whose names start with Observation). '
        + 'The app keeps potassium, phosphate, albumin, bicarbonate, urine albumin-to-creatinine ratio, creatinine, cystatin C, eGFR and HbA1c.'));
    } else {
      into.append(h('p', { class: 'hint' }, 'These come from your health system, not from an AI. The new ones are ticked: untick any you do not want. Nothing is saved until you press Save.'));
    }

    const list = h('ul', { class: 'list labs-list lab-import-list lab-fhir-list' });
    for (const r of rows) {
      const id = `lab-fhir-row-${r.index}`;
      const cb = h('input', { type: 'checkbox', id });
      cb.checked = !r.saved; // a result the person already has starts unticked
      r.cb = cb;
      cb.addEventListener('change', () => update());
      list.append(h('li', { class: 'lab-row' }, cb, h('label', { for: id },
        h('span', { class: 'lab-row-date' }, fmtDay(r.taken_on)), h('span', { class: 'lab-row-value' }, `${r.label} ${r.display}`),
        r.saved ? h('span', { class: 'lab-import-saved' }, 'already saved') : null)));
    }
    if (rows.length) into.append(list);

    if (analysis.problems.length) {
      const refused = h('ul', { class: 'list labs-list lab-import-list lab-fhir-refused' });
      for (const p of analysis.problems) {
        refused.append(h('li', { class: 'lab-row lab-import-problem' }, h('div', { class: 'lab-row-main' },
          h('span', { class: 'lab-row-date' }, p.taken_on ? fmtDay(p.taken_on) : ''), h('span', { class: 'lab-row-value' }, `${p.label} ${p.text}`.trim()),
          h('span', { class: 'lab-import-why' }, `Not imported${p.file ? ` (${p.file})` : ''}: ${p.problem}`))));
      }
      into.append(refused);
      const hidden = analysis.counts.problemsHidden;
      if (hidden) into.append(h('p', { class: 'muted small' }, `${plural(hidden, 'more is', 'more are')} not listed.`));
    }

    const save = h('button', { class: 'btn primary', type: 'button', id: 'lab-fhir-save' }, 'Save');
    const cancel = h('button', { class: 'btn secondary', type: 'button', id: 'lab-fhir-cancel' }, rows.length ? 'Cancel' : 'Close');
    const ticked = () => rows.filter((r) => r.cb.checked);
    function update() {
      const n = ticked().length;
      save.textContent = n === 1 ? 'Save 1 result' : `Save ${n} results`;
      save.disabled = n === 0 || n > FL.MAX_RESULTS;
    }
    update();
    save.addEventListener('click', () => {
      const kept = ticked().map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on, label: r.label, text: r.text }));
      if (kept.length && opts.onSave) opts.onSave(kept, save);
    });
    cancel.addEventListener('click', () => { if (opts.onCancel) opts.onCancel(); });
    into.append(h('div', { class: 'form-actions' }, rows.length ? save : null, cancel));
    return { save, cancel, rows, update, headline };
  }

  function forget() {
    pick += 1;
    if (input) input.value = '';
  }

  async function savedRows() {
    try { return (await KH.labs.load()).labs; } catch (e) { return []; } // the table still works; "already saved" is just not shown
  }

  async function onPick() {
    pick += 1;
    const mine = pick;
    clear(box);
    const files = Array.from((input && input.files) || []);
    if (!files.length) return;
    if (files.length > FL.MAX_FILES) { showError(FL.tooManyFiles(files.length)); return; }
    const existing = await savedRows();
    if (mine !== pick) return;
    const run = FL.start({ today: KH.util.todayStr(), existing });
    const progress = h('p', { class: 'muted small' }, `Reading ${plural(files.length, 'file', 'files')} on this device…`);
    clear(box).append(progress);
    box.setAttribute('aria-busy', 'true');
    try {
      for (let i = 0; i < files.length; i += BATCH) {
        const part = await Promise.all(files.slice(i, i + BATCH).map(readOne));
        if (mine !== pick) return; // a newer pick (or Cancel) took over
        for (const f of part) run.add(f);
        progress.textContent = `Read ${Math.min(i + BATCH, files.length)} of ${plural(files.length, 'file', 'files')}…`;
      }
      const analysis = run.finish();
      const view = review(box, analysis, { onSave, onCancel });
      if (view.headline && view.headline.focus) view.headline.focus(); // the headline is read out; Tab goes on to the first result
    } catch (e) {
      showError('The files could not be read. Choose them again.');
    } finally {
      box.removeAttribute('aria-busy');
    }
  }

  function onCancel() {
    forget();
    clear(box);
    if (input && input.focus) input.focus();
  }

  async function onSave(kept, saveBtn) {
    saveBtn.disabled = true;
    try {
      await KH.views.labs.saveImported(kept, box, 'your Apple Health files', forget);
    } catch (err) {
      saveBtn.disabled = false;
      if (err.handled) return;
      if (err.status === 400) showError(err.detail || err.message); else if (KH.toastError) KH.toastError(err); else showError(err.message || 'Something went wrong');
    }
  }

  if (input) input.addEventListener('change', onPick);

  KH.labFhir = { review, readOne, onPick };
})();
