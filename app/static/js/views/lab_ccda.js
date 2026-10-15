/* Kidney Diet Log — lab results from a patient-portal C-CDA file (KH.labCcda; ARCHITECTURE.md "Lab results from a patient-portal C-CDA
   file", docs/targets-and-labs.md). Lives in the Labs view, below "Import from Apple Health".

   * The person downloads a health summary (a "C-CDA" .xml file) from their patient portal (MyChart and others) and chooses it here (a
     pick of up to 20 files, 5 MB each). THE FILES ARE READ ON THIS DEVICE and never uploaded: each is read with File.text(), handed to
     KH.ccdaLabs (js/engine/ccda_labs.js), which parses it with the browser's own XML parser (a browser never fetches an
     external entity or DTD for it; a file that has a DOCTYPE or ENTITY is refused before parsing) and lets go of its text and its
     document before the next file; a file over 5 MB is not even read. Names, ids, addresses and providers inside the files are never
     looked at, and no file or file name is sent anywhere.
   * What the engine finds is shown in the same table as the CSV and Apple Health imports (KH.labFhir.review), with a headline ("12
     results found in 1 file; ..."), the refusals with their reasons, and a note for a file that was refused as a whole. The data comes
     from the person's health system, not from an AI, so the new results start TICKED; results already saved are not. Nothing is saved
     until Save; then only the ticked rows (test, value, unit and day) go to POST /api/labs/import through KH.views.labs.saveImported,
     so the potassium banner and "what this changed" work exactly as for a CSV file.

   Rules: everything that comes from a file is drawn with textContent (the h() helper), never as HTML; no inline script, handler or
   style; the only network call is the app's own API, through saveImported; nothing is stored in the browser. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear } = KH;
  const CC = KH.ccdaLabs;
  const FH = KH.labFhir;

  const plural = (n, singular, other) => `${n} ${n === 1 ? singular : other}`;
  const PREFIX = 'lab-ccda';

  const input = $('#lab-ccda-file');
  const box = $('#lab-ccda-preview');
  let pick = 0; // which pick is current; choosing again while one is still being read drops the older one

  function showError(message) {
    clear(box).append(h('p', { class: 'form-error', role: 'alert' }, message));
  }

  /* One file for the engine: {name, size, text}; {name, size} when it is over the limit (never read); {name, unreadable: true}. */
  async function readOne(file) {
    const name = file && file.name ? String(file.name) : '';
    if (!file || typeof file.size !== 'number') return { name, unreadable: true };
    if (file.size > CC.MAX_FILE_BYTES) return { name, size: file.size };
    try {
      return { name, size: file.size, text: await file.text() };
    } catch (e) {
      return { name, unreadable: true };
    }
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
    if (files.length > CC.MAX_FILES) { showError(CC.tooManyFiles(files.length)); return; }
    const existing = await savedRows();
    if (mine !== pick) return;
    const run = CC.start({ today: KH.util.todayStr(), existing });
    const progress = h('p', { class: 'muted small' }, `Reading ${plural(files.length, 'file', 'files')} on this device…`);
    clear(box).append(progress);
    box.setAttribute('aria-busy', 'true');
    try {
      for (let i = 0; i < files.length; i++) {
        const one = await readOne(files[i]); // one file at a time: a file's text and document are let go of before the next is read
        if (mine !== pick) return; // a newer pick (or Cancel) took over
        run.add(one);
        progress.textContent = `Read ${i + 1} of ${plural(files.length, 'file', 'files')}…`;
      }
      const analysis = run.finish();
      const view = FH.review(box, analysis, {
        prefix: PREFIX,
        emptyHint: 'Choose the .xml file of a health summary or visit summary from your patient portal (not the PDF).',
        onSave,
        onCancel,
      });
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
      await KH.views.labs.saveImported(kept, box, 'your patient portal file', forget);
    } catch (err) {
      saveBtn.disabled = false;
      if (err.handled) return;
      if (err.status === 400) showError(err.detail || err.message); else if (KH.toastError) KH.toastError(err); else showError(err.message || 'Something went wrong');
    }
  }

  if (input) input.addEventListener('change', onPick);

  KH.labCcda = { readOne, onPick };
})();
