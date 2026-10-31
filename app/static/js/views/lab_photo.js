/* Kidney Diet Log — read a lab report from a photo, a screenshot or a PDF (KH.labPhoto; ARCHITECTURE.md "Lab report photos", docs/ai.md
   "Lab report photos"). Lives in the Labs view, below "Import from a spreadsheet".

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

   A PDF (design note 13): the file picker also takes the PDF a lab's website hands out. The PDF NEVER leaves the device and the server
   never sees one. KH.pdfPages (js/engine/pdf_pages.js) opens it here with the vendored pdf.js, and this file shows a list of its pages
   (Page 1, Page 2, ...): pages 1 to 6 are ticked at first, at most 10 can be ticked ("Reading a page takes a while on your own AI; choose
   the pages with results."), and the line "Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not
   sent." is on the list and in the consent sheet (the 409 answer's notice gets it before the sheet is drawn). "Read the report" then goes
   page by page: the page is drawn, redrawn as a JPEG without camera data (KH.ai.prepareJpeg, the same helper as for a photo), and sent as
   its own POST /api/ai/read-lab-report through the same consent (and, if the person asked for it, the same "What will be sent?" before each
   page). The screen says "Reading page 2 of 4…" and has a Cancel button that stops between pages and aborts the request in flight. The
   rows of all pages go into ONE review table, every row unticked and saying which page it came from; a row the same as an earlier one
   (test, value, unit, date) is shown once, with the first page's number. A page that fails ("Page 3 could not be read: …") or has no
   result ("Page 2: …", the server's own sentence) is said in a line and the other pages still count. Messages for a file that cannot be
   used (too big, not a PDF, a password, damaged, more than 50 pages, a browser that cannot) are fixed sentences below. The PDF's
   bytes, the drawn pages and the pdf.js document are let go when the person discards, saves, picks another file or cancels, and the
   pdf.js document and its worker are closed as soon as a run of reading ends (the chosen file stays chosen, as a photo does).

   Rules: everything the server sends is drawn with textContent (the h() helper), never as HTML; no inline script, handler or
   style; the only network calls are the app's own API (through KH.ai); the photo or the pages are held in memory until the person
   discards the result or saves, and are never stored. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear } = KH;

  const NOTICE = 'Read by AI from your photo. Check each value against the report before you tick it.';
  const PDF_NOTICE = 'Read by AI from the pages of your PDF that you ticked. Check each value against the report before you tick it.';
  const PDF_SEND_LINE = 'Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not sent.';
  const PDF_TIP = 'Reading a page takes a while on your own AI; choose the pages with results.';
  const MAX_RESULTS = 1000; // as the CSV import: POST /api/labs/import takes 1 to 1,000 results
  const DEFAULT_TICKED = 6; // pages ticked when a PDF is chosen
  const MAX_TICKED = 10; // pages that can be ticked at once
  const MB = 1024 * 1024;
  const plural = (n, singular, other) => `${n} ${n === 1 ? singular : other}`;
  const isAbort = (e) => !!e && e.name === 'AbortError';
  const sentence = (text) => (/[.!?]$/.test(text) ? text : `${text}.`);

  // The sentence for each reason a PDF cannot be used (the codes of KH.pdfPages; the module throws, this file says it).
  const PDF_MESSAGES = {
    too_big: (e) => `That PDF is ${(Math.round((e.size / MB) * 10) / 10).toFixed(1)} MB; the largest this app reads is 20 MB.`,
    not_pdf: 'That file is not a PDF.',
    password: 'This PDF has a password. Open it on your device and take a screenshot of each page instead.',
    damaged: 'This PDF could not be read. Download it again, or take a screenshot of each page.',
    too_many_pages: 'This PDF has more than 50 pages. Take screenshots of the pages with your results.',
    browser: 'This browser cannot read a PDF here. Take a screenshot of each page instead.',
  };
  function pdfMessage(e) {
    const m = e && PDF_MESSAGES[e.code];
    if (typeof m === 'function') return m(e);
    return m || PDF_MESSAGES.damaged;
  }
  const isPdf = (file) => !!file && (file.type === 'application/pdf' || /\.pdf$/i.test(file.name || ''));

  const section = $('#lab-photo');
  const why = $('#lab-photo-why');
  const controls = $('#lab-photo-controls');
  const fileInput = $('#lab-photo-file');
  const readBtn = $('#lab-photo-read');
  const whatBtn = $('#lab-photo-what');
  const cancelBtn = $('#lab-photo-cancel');
  const pagesBox = $('#lab-photo-pages');
  const progress = $('#lab-photo-progress');
  const errorBox = $('#lab-photo-error');
  const results = $('#lab-photo-results');
  const photo = { file: null, jpeg: null }; // the chosen picture, and its redrawn JPEG (memory only)
  const shown = { source: 'your photo' }; // what the table on screen was read from (the saved headline says "saved from your PDF")
  // The chosen PDF: the file (the input holds it), the open pdf.js document while pages are being drawn, the ticked page numbers.
  // `pick` counts picks and releases, so a slow answer from an earlier file is recognised and dropped.
  const pdf = { file: null, doc: null, numPages: 0, ticked: new Set(), boxes: [], count: null, control: null, busy: false, pick: 0 };

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

  /* review(box, answer, {existing, today, onSave, onDiscard, source, notes}) draws the proposed rows of an `ok` answer into `box`:
     the notice, how many lines the app left out, the table (every row unticked), Save and Discard. `onSave(rows)` gets the
     ticked rows as {analyte, value, unit, taken_on, label, text}; the caller sends them. `source` is 'photo' (the default) or
     'PDF' (the summary says "read from your PDF"); a row with a `page` says which page of the PDF it came from; `notes` are
     extra lines {text, warn} (a page that failed, a page with no result) drawn under the summary. Returns {save, discard, rows}. */
  function review(box, answer, opts = {}) {
    const today = opts.today || KH.util.todayStr();
    const saved = savedKeys(opts.existing);
    const source = opts.source || 'photo';
    const rows = (answer.rows || []).map((r, i) => ({ ...r, index: i, ticked: false, cb: null, tag: null, when: null }));
    clear(box);
    box.append(h('div', { class: 'settings-note caution', role: 'note' }, h('p', {}, h('strong', {}, answer.notice || NOTICE))));
    box.append(h('p', { class: 'lab-import-summary', role: 'status' },
      `${plural(rows.length, 'result', 'results')} read from your ${source}. None is ticked: tick the ones that match the report. Nothing is saved until you press Save.`));
    for (const line of opts.notes || []) box.append(h('p', { class: line.warn ? 'hint warn' : 'hint' }, line.text));
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
      const li = h('li', { class: 'lab-row' }, cb, h('label', { for: id }, r.when, h('span', { class: 'lab-row-value' }, `${r.label} ${r.display}`),
        r.page ? h('span', { class: 'lab-row-page' }, `page ${r.page} of your PDF`) : null, r.tag));
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
  // `notes` (a PDF's per-page lines) follow the message.
  function nothing(box, answer, notes) {
    clear(box);
    box.append(h('p', { class: 'hint warn', role: 'status' }, answer.message || 'No result could be read from this photo.'));
    for (const line of notes || []) box.append(h('p', { class: line.warn ? 'hint warn' : 'hint' }, line.text));
    for (const line of answer.dropped_notes || []) box.append(h('p', { class: 'hint' }, line));
  }

  /* The rows of all the pages read, in page order, as one list: [{page, rows}] → {rows, duplicates}. A row the same as an earlier one
     (test, value, unit, date) is dropped and counted, so the first page keeps it; each kept row gets its `page`. */
  function mergePages(pages) {
    const seen = new Set();
    const rows = [];
    let duplicates = 0;
    for (const entry of pages) {
      for (const r of entry.rows || []) {
        const key = [r.analyte, r.value, r.unit, r.taken_on || ''].join('|');
        if (seen.has(key)) { duplicates += 1; continue; }
        seen.add(key);
        rows.push({ ...r, page: entry.page });
      }
    }
    return { rows, duplicates };
  }

  // ---------------------------------------------------------------------------
  // The card in the Labs view
  // ---------------------------------------------------------------------------
  function showError(err) {
    clear(errorBox);
    if (err) errorBox.append(h('p', {}, typeof err === 'string' ? err : (err.detail || err.message || 'Something went wrong')));
  }
  function say(text) {
    progress.textContent = text || '';
    progress.hidden = !text;
  }

  // Why the card offers nothing: the server's own sentence for the lab report route, or the person's opt-in.
  function whyOff(st) {
    if (st.opted_in === false) return 'Turn on AI features in Settings first: reading a lab report photo uses the AI on your own network.';
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
    releasePdf();
    clear(results);
    why.hidden = false;
    why.textContent = whyOff(st);
  }

  const upload = (blob, dry, signal) => KH.ai.uploadPhoto('lab-report', blob, dry, signal);
  async function jpeg() {
    if (!photo.file) throw new Error('Choose a photo, a screenshot or a PDF of the report first.');
    if (!photo.jpeg) photo.jpeg = await KH.ai.prepareJpeg(photo.file);
    return photo.jpeg;
  }
  // Everything held for a result: the photo, the PDF and its pages, the chosen file.
  function forget() {
    photo.file = null;
    photo.jpeg = null;
    releasePdf();
    if (fileInput) fileInput.value = '';
  }

  async function read(btn) {
    if (pdf.file) { await readPdf(btn); return; }
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
      shown.source = 'your photo';
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
      await KH.views.labs.saveImported(kept, results, shown.source, forget);
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

  // ---------------------------------------------------------------------------
  // A PDF: the page list, then page by page
  // ---------------------------------------------------------------------------
  function closeDoc() {
    if (!pdf.doc) return;
    try { pdf.doc.close(); } catch (e) { /* already closed */ }
    pdf.doc = null;
  }
  // Let go of the PDF: stop what is running, close pdf.js and its worker, forget the file, the ticks and the page list.
  function releasePdf() {
    pdf.pick += 1;
    if (pdf.control) { pdf.control.abort(); pdf.control = null; }
    closeDoc();
    pdf.file = null;
    pdf.numPages = 0;
    pdf.ticked = new Set();
    pdf.boxes = [];
    pdf.count = null;
    pdf.busy = false;
    if (pagesBox) { clear(pagesBox); pagesBox.hidden = true; }
    if (cancelBtn) cancelBtn.hidden = true;
    if (progress) say('');
  }

  function syncPages() {
    const n = pdf.ticked.size;
    pdf.boxes.forEach((cb, i) => { cb.disabled = pdf.busy || (!pdf.ticked.has(i + 1) && n >= MAX_TICKED); });
    if (!pdf.count) return;
    if (n === 0) pdf.count.textContent = 'No page is ticked.';
    else if (n >= MAX_TICKED) pdf.count.textContent = `${plural(n, 'page is', 'pages are')} ticked, the most at a time. Untick one to choose another.`;
    else pdf.count.textContent = `${plural(n, 'page is', 'pages are')} ticked.`;
  }
  function renderPages() {
    clear(pagesBox);
    pdf.boxes = [];
    const list = h('ul', { class: 'list lab-photo-page-list' });
    for (let n = 1; n <= pdf.numPages; n += 1) {
      const id = `lab-photo-page-${n}`;
      const cb = h('input', { type: 'checkbox', id });
      cb.checked = pdf.ticked.has(n);
      cb.addEventListener('change', () => {
        if (cb.checked) pdf.ticked.add(n); else pdf.ticked.delete(n);
        syncPages();
      });
      pdf.boxes.push(cb);
      list.append(h('li', { class: 'lab-photo-page' }, cb, h('label', { for: id }, `Page ${n}`)));
    }
    pdf.count = h('p', { class: 'hint', role: 'status' });
    pagesBox.append(h('fieldset', { class: 'lab-photo-fieldset' },
      h('legend', {}, `Pages to read (this PDF has ${plural(pdf.numPages, 'page', 'pages')})`),
      h('p', { class: 'hint' }, PDF_TIP), list, pdf.count, h('p', { class: 'hint' }, PDF_SEND_LINE)));
    pagesBox.hidden = false;
    syncPages();
  }

  // A PDF was chosen: open it here (nothing leaves the device) and list its pages.
  async function pickPdf(file) {
    if (!KH.pdfPages || !KH.pdfPages.supported()) { forget(); showError(PDF_MESSAGES.browser); return; }
    const mine = pdf.pick;
    const control = new AbortController();
    pdf.file = file;
    pdf.control = control;
    say('Opening the PDF…');
    try {
      const doc = await KH.pdfPages.open(file, { signal: control.signal });
      if (mine !== pdf.pick) { doc.close(); return; } // another file was chosen meanwhile
      pdf.doc = doc;
      pdf.numPages = doc.numPages;
      pdf.ticked = new Set(Array.from({ length: Math.min(DEFAULT_TICKED, doc.numPages) }, (_, i) => i + 1));
      pdf.control = null;
      say('');
      renderPages();
    } catch (e) {
      if (mine !== pdf.pick || isAbort(e)) return;
      forget(); // a file that cannot be used is not kept
      showError(pdfMessage(e));
    }
  }

  async function ensureDoc(signal) {
    if (pdf.doc) return pdf.doc;
    const doc = await KH.pdfPages.open(pdf.file, { signal });
    if (signal.aborted) { doc.close(); throw Object.assign(new Error('Stopped.'), { name: 'AbortError' }); }
    pdf.doc = doc;
    return doc;
  }
  const tickedPages = () => [...pdf.ticked].sort((a, b) => a - b);

  // The route's own refusals that would repeat for every page: stop instead of asking N times.
  const systemic = (e) => [0, 401, 403, 404, 429, 503].includes(e.status);

  async function readPdf(btn) {
    showError(null);
    clear(results);
    if (!pdf.numPages) { showError('The PDF is still being opened. Wait a moment, then try again.'); return; }
    const pages = tickedPages();
    if (!pages.length) { showError('Tick at least one page to read.'); return; }
    if (pdf.busy) return;
    const run = pdf.pick;
    const control = new AbortController();
    const { signal } = control;
    pdf.control = control;
    pdf.busy = true;
    btn.disabled = true;
    btn.textContent = 'Reading…';
    cancelBtn.hidden = false;
    syncPages();
    results.setAttribute('aria-busy', 'true');
    const got = []; // [{page, rows}] of the pages the AI answered `ok` for
    const lines = []; // [{text, warn}] one per page that failed or had nothing, and the reason a run ended early
    let ended = null; // 'cancelled' | 'declined' | 'stopped' (a refusal that would repeat) | 'browser' | 'file'
    try {
      const doc = await ensureDoc(signal);
      for (let i = 0; i < pages.length; i += 1) {
        if (signal.aborted) { ended = 'cancelled'; break; }
        const n = pages[i];
        say(`Reading page ${i + 1} of ${pages.length}…${n === i + 1 ? '' : ` (page ${n} of your PDF)`}`);
        let step = 'draw';
        try {
          const drawn = await doc.render(n, { signal });
          const picture = await KH.ai.prepareJpeg(drawn);
          step = 'read';
          const answer = await KH.ai.withConsent('labs', () => sendPage(picture, signal), () => upload(picture, true, signal), btn, 'labs');
          if (!answer) { ended = 'declined'; break; } // the person declined the consent sheet or the request
          if (answer.status === 'ok') {
            got.push({ page: n, rows: answer.rows || [] });
          } else {
            lines.push({ text: `Page ${n}: ${answer.message || 'No result could be read from this page.'}` });
          }
          for (const note of answer.dropped_notes || []) lines.push({ text: `Page ${n}: ${note}` });
        } catch (e) {
          if (isAbort(e) || signal.aborted) { ended = 'cancelled'; break; }
          if (e.handled) { ended = 'stopped'; break; } // signed out: the sign-in screen is already showing
          if (e.code === 'browser') { ended = 'browser'; break; }
          const reason = step === 'draw' ? 'it could not be drawn from the PDF.' : sentence(e.detail || e.message || 'the server refused it.');
          lines.push({ text: `Page ${n} could not be read: ${reason}`, warn: true });
          if (step === 'read' && systemic(e)) { ended = 'stopped'; break; }
        }
      }
    } catch (e) { // the PDF could not be opened again (it was opened when it was chosen)
      if (isAbort(e) || signal.aborted) ended = 'cancelled';
      else if (e.handled) ended = 'stopped';
      else { ended = 'file'; lines.push({ text: pdfMessage(e), warn: true }); }
    } finally {
      if (run === pdf.pick) {
        pdf.busy = false;
        if (pdf.control === control) pdf.control = null;
        closeDoc();
        say('');
        syncPages();
      }
      cancelBtn.hidden = true;
      btn.disabled = false;
      btn.textContent = 'Read the report';
      results.removeAttribute('aria-busy');
    }
    if (run !== pdf.pick) return; // discarded, saved or another file chosen while this ran: nothing to show
    if (ended === 'browser') { showError(PDF_MESSAGES.browser); return; }
    if (ended === 'cancelled') {
      lines.unshift({ text: got.length ? `Stopped. These results are from ${plural(got.length, 'page', 'pages')} read before you pressed Cancel.` : 'Stopped. Nothing was read.' });
    } else if (ended === 'declined') {
      lines.unshift({ text: got.length ? 'Stopped. Nothing more was sent. These results are from the pages read so far.' : 'Nothing was sent.' });
    } else if (ended === 'stopped') {
      lines.push({ text: 'Reading stopped here; the pages after it were not sent.', warn: true });
    }
    const merged = mergePages(got);
    if (merged.duplicates) lines.push({ text: `${plural(merged.duplicates, 'result was', 'results were')} the same as one already shown, so it is shown once.` });
    if (!merged.rows.length) {
      const stopped = ended === 'declined' || ended === 'cancelled'; // the first line then says so: it becomes the headline
      nothing(results, { message: stopped ? lines.shift().text : 'No result could be read from the pages you ticked.' }, lines);
      return;
    }
    let existing = [];
    try { existing = (await KH.labs.load()).labs; } catch (e) { /* the table still works; "already saved" is just not shown */ }
    if (run !== pdf.pick) return;
    shown.source = 'your PDF';
    review(results, { rows: merged.rows, dropped_notes: [], notice: PDF_NOTICE }, { existing, source: 'PDF', notes: lines, onSave, onDiscard });
    const first = $('#lab-photo-row-0');
    if (first && !first.disabled && first.focus) first.focus();
  }

  // The first page's request meets the consent sheet; the notice the server sends with its 409 gets the line about the PDF before the
  // sheet is drawn (the sheet shows the notice as it is).
  async function sendPage(picture, signal) {
    try {
      return await upload(picture, false, signal);
    } catch (e) {
      const consent = e && e.status === 409 && e.data && e.data.consent;
      if (consent && Array.isArray(consent.notice) && !consent.notice.includes(PDF_SEND_LINE)) consent.notice = [...consent.notice, PDF_SEND_LINE];
      throw e;
    }
  }

  async function previewPdf() {
    if (!pdf.numPages) { showError('The PDF is still being opened. Wait a moment, then try again.'); return; }
    const pages = tickedPages();
    if (!pages.length) { showError('Tick at least one page to read.'); return; }
    if (pdf.busy) return;
    const run = pdf.pick;
    const control = new AbortController();
    pdf.control = control;
    pdf.busy = true;
    syncPages();
    say(`Drawing page ${pages[0]}…`);
    try {
      const doc = await ensureDoc(control.signal);
      const picture = await KH.ai.prepareJpeg(await doc.render(pages[0], { signal: control.signal }));
      await KH.ai.showSent(await upload(picture, true, control.signal), { trigger: whatBtn });
    } catch (e) {
      if (!isAbort(e) && !e.handled && run === pdf.pick) showError(e.code ? pdfMessage(e) : e);
    } finally {
      if (run === pdf.pick) {
        pdf.busy = false;
        if (pdf.control === control) pdf.control = null;
        closeDoc();
        say('');
        syncPages();
      }
    }
  }

  if (fileInput) {
    fileInput.addEventListener('change', () => {
      releasePdf(); // a new pick lets go of the old PDF, its pages and anything still running
      const file = (fileInput.files && fileInput.files[0]) || null;
      photo.file = file;
      photo.jpeg = null;
      clear(results);
      showError(null);
      if (isPdf(file)) {
        photo.file = null;
        pickPdf(file);
      }
    });
  }
  if (readBtn) readBtn.addEventListener('click', () => read(readBtn));
  if (cancelBtn) cancelBtn.addEventListener('click', () => { if (pdf.control) pdf.control.abort(); });
  if (whatBtn) {
    whatBtn.addEventListener('click', async () => {
      showError(null);
      if (pdf.file) { await previewPdf(); return; }
      try { await KH.ai.showSent(await upload(await jpeg(), true), { trigger: whatBtn }); } catch (e) { if (!e.handled) showError(e); }
    });
  }

  KH.labPhoto = { show, review, nothing, whyOff, mergePages, pdfMessage, NOTICE, PDF_NOTICE, PDF_SEND_LINE, MAX_RESULTS, MAX_TICKED, DEFAULT_TICKED };
})();
