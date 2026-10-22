/* Kidney Diet Log — lab results from Apple Health clinical records (KH.labFhir; ARCHITECTURE.md "Lab results from Apple Health clinical
   records", docs/targets-and-labs.md). Lives in the Labs view, below "Import from a spreadsheet".

   * The person chooses the Health app's "Export All Health Data" zip (export.zip) itself, or, if it was already unzipped in the Files
     app, the JSON files of apple_health_export/clinical-records/ (a pick of up to 2,000 files, 1 MB each). THE FILES ARE READ ON THIS
     DEVICE and never uploaded: each is read with File.text(), handed to KH.fhirLabs (js/engine/fhir_labs.js) and let go of; a file over
     1 MB is not even read. Names, ids and providers inside the files are never looked at, and no file or file name is sent anywhere.
   * A .zip is opened here by KH.zip (js/engine/zip.js, docs/dev/research/11-reading-a-zip-in-the-browser.md): only its
     clinical-records/*.json entries are read, one at a time through the same loop, the same caps (2,000 files, 1 MB each; a bigger
     entry is not read, a damaged or unreadable one is counted as a file that could not be read) and the same engine. Nothing else in
     the .zip is looked at. A .zip without a clinical-records folder, or that cannot be read, is told so in plain words.
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
  const ZIP_BROWSER = 'This browser cannot open a .zip here. In Files, tap the zip to unzip it, then choose the files in apple_health_export/clinical-records.';
  const ZIP_UNREADABLE = 'This .zip could not be read (it may be damaged or not finished downloading). Export from the Health app again, or unzip it in Files and choose the files in apple_health_export/clinical-records.';
  const ZIP_NO_FOLDER = 'This .zip has no clinical-records folder. It is there only if you linked your health system in the Health app.';
  const ZIP_AND_FILES = 'Choose either one .zip or the .json files, not both.';
  const zipTooMany = (n) => `This .zip has ${n.toLocaleString('en-US')} clinical-record files; the app reads up to ${FL.MAX_FILES.toLocaleString('en-US')} at a time. In Files, tap the zip to unzip it, then choose only some of the files, for example the Observation files.`;
  const isZipFile = (file) => /\.zip$/i.test(String((file && file.name) || '')) || (file && file.type) === 'application/zip';
  const plural = (n, singular, other) => `${n} ${n === 1 ? singular : other}`;
  const fmtDay = (iso) => (KH.views && KH.views.labs && KH.views.labs.fmtDay ? KH.views.labs.fmtDay(iso) : iso);

  const input = $('#lab-fhir-file');
  const box = $('#lab-fhir-preview');
  let pick = 0; // which pick is current; choosing again while one is still being read drops the older one

  function showError(message) {
    clear(box).append(h('p', { class: 'form-error', role: 'alert' }, message));
  }

  // A .zip that cannot be used: the reason, and the file box is emptied so that a new export with the same name can be chosen.
  function refuseZip(message) {
    if (input) input.value = '';
    showError(message);
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

  /* One entry of a .zip for the engine, the way readOne gives a file: {name, size, text}; {name, size} when it is over the limit (never read);
     {name, unreadable: true} when it is damaged, encrypted or cannot be read. The name is the entry's own file name, for the list of refusals. */
  async function readEntry(archive, entry) {
    const name = String(entry.name).split('/').pop();
    if (entry.size > FL.MAX_FILE_BYTES) return { name, size: entry.size };
    try {
      return { name, size: entry.size, text: await KH.zip.text(archive, entry, { maxBytes: FL.MAX_FILE_BYTES }) };
    } catch (e) {
      return { name, unreadable: true };
    }
  }

  /* review(box, analysis, {onSave, onCancel, prefix, emptyHint}) draws an analysis of KH.fhirLabs (start().finish()): the headline, the
     table (new rows ticked), the refusals, Save and Cancel. onSave(kept, saveButton) gets the ticked rows as {analyte, value, unit,
     taken_on, label, text}; the caller sends them. Returns {save, cancel, rows}. The patient-portal import (js/views/lab_ccda.js) draws
     its analysis with this too: `prefix` (default "lab-fhir") starts every element id, so that two tables on the page never share one,
     and `emptyHint` says where to look when nothing was found. */
  function review(into, analysis, opts = {}) {
    const prefix = opts.prefix || 'lab-fhir';
    clear(into);
    if (analysis.problem) {
      into.append(h('p', { class: 'form-error', role: 'alert' }, analysis.problem));
      return { save: null, cancel: null, rows: [], headline: null };
    }
    const headline = h('p', { class: 'lab-import-summary', role: 'status', id: `${prefix}-summary`, tabindex: '-1' }, `${analysis.summary.join('; ')}.`);
    into.append(headline);
    const rows = analysis.results.map((r, i) => ({ ...r, index: i, cb: null }));
    if (!rows.length) {
      into.append(h('p', { class: 'hint warn' }, `No lab result the app keeps was found. ${opts.emptyHint || 'Choose the files in the clinical-records folder (the ones whose names start with Observation).'} `
        + 'The app keeps potassium, phosphate, albumin, bicarbonate, urine albumin-to-creatinine ratio, creatinine, cystatin C, eGFR and HbA1c.'));
    } else {
      into.append(h('p', { class: 'hint' }, 'These come from your health system, not from an AI. The new ones are ticked: untick any you do not want. Nothing is saved until you press Save.'));
    }

    const list = h('ul', { class: 'list labs-list lab-import-list lab-fhir-list' });
    for (const r of rows) {
      const id = `${prefix}-row-${r.index}`;
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

    const save = h('button', { class: 'btn primary', type: 'button', id: `${prefix}-save` }, 'Save');
    const cancel = h('button', { class: 'btn secondary', type: 'button', id: `${prefix}-cancel` }, rows.length ? 'Cancel' : 'Close');
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
    if (files.some(isZipFile)) {
      if (files.length > 1) refuseZip(ZIP_AND_FILES); else await readZip(files[0], mine);
      return;
    }
    if (files.length > FL.MAX_FILES) { showError(FL.tooManyFiles(files.length)); return; }
    await readAll(files, mine, (part) => Promise.all(part.map(readOne)), `Reading ${plural(files.length, 'file', 'files')} on this device…`,
      'The files could not be read. Choose them again.');
  }

  // The loop of both picks: `items` (files, or entries of a .zip) are read BATCH at a time by `readPart`, handed to the engine and let go of.
  async function readAll(items, mine, readPart, first, failure) {
    const count = items.length;
    const existing = await savedRows();
    if (mine !== pick) return;
    const run = FL.start({ today: KH.util.todayStr(), existing });
    const progress = h('p', { class: 'muted small' }, first);
    clear(box).append(progress);
    box.setAttribute('aria-busy', 'true');
    try {
      for (let i = 0; i < count; i += BATCH) {
        const part = await readPart(items.slice(i, i + BATCH));
        if (mine !== pick) return; // a newer pick (or Cancel) took over
        for (const f of part) run.add(f);
        progress.textContent = `Read ${Math.min(i + BATCH, count)} of ${plural(count, 'file', 'files')}…`;
      }
      const analysis = run.finish();
      const view = review(box, analysis, { onSave, onCancel });
      if (view.headline && view.headline.focus) view.headline.focus(); // the headline is read out; Tab goes on to the first result
    } catch (e) {
      showError(failure);
    } finally {
      box.removeAttribute('aria-busy');
    }
  }

  // One export.zip: its clinical-records/*.json entries go through the same loop and the same caps as picked files.
  async function readZip(file, mine) {
    if (!KH.zip || !KH.zip.supported()) { refuseZip(ZIP_BROWSER); return; }
    clear(box).append(h('p', { class: 'muted small' }, `Opening ${file.name} on this device…`));
    box.setAttribute('aria-busy', 'true');
    let archive = null;
    let entries = null;
    try {
      archive = await KH.zip.open(file);
      entries = KH.zip.list(archive, KH.zip.RULES.clinicalRecords);
    } catch (e) {
      if (mine === pick) refuseZip(ZIP_UNREADABLE);
      return;
    } finally {
      box.removeAttribute('aria-busy');
    }
    if (mine !== pick) return;
    if (!entries.length) { refuseZip(ZIP_NO_FOLDER); return; }
    if (entries.length > FL.MAX_FILES) { refuseZip(zipTooMany(entries.length)); return; }
    await readAll(entries, mine, (part) => Promise.all(part.map((entry) => readEntry(archive, entry))),
      `Reading ${plural(entries.length, 'file', 'files')} in ${file.name} on this device…`, ZIP_UNREADABLE);
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

  KH.labFhir = { review, readOne, readEntry, onPick };
})();
