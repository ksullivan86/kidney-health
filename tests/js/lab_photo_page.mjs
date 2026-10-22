#!/usr/bin/env node
// Runs app/static/js/views/lab_photo.js against a tiny fake page and fake server answers, together with the real
// js/engine/rules.js and js/engine/kidney_function.js (the parity-tested conversions), and prints what happened as JSON, so
// pytest (tests/test_lab_photo_ui.py) can check the behaviour without a browser: the card is offered only when the server says
// so (and says why when it is not), every row of the review table starts unticked, a row without a date cannot be ticked until
// the person enters one, only ticked rows are handed to the shared save (POST /api/labs/import), and what the server sends is
// drawn as text. A PDF pick (design note 13) is driven with a stand-in for KH.pdfPages (js/engine/pdf_pages.js has its own test): the
// page list (pages 1-6 ticked, at most 10), one request per ticked page with the page's own picture and never the PDF, progress and
// Cancel, the merged review table with page numbers and repeated rows shown once, a page that fails or has no result, the messages for a
// file that cannot be used, and everything let go on discard, save, a new pick and a run that ends.
// The helpers the file takes from KH (h, $, clear, util, ai, labs) are stand-ins with the contract of js/core.js.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (...p) => readFileSync(join(ROOT, 'app', 'static', ...p), 'utf8');

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) {
    this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this._text = '';
    this.disabled = false; this.checked = false; this.hidden = false; this.value = ''; this.files = null;
  }
  // like the DOM: assigning textContent replaces whatever the element held
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'object' && k && k.nodeType ? k : new Text(String(k))); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  focus() { page.focused = this.attrs.id || this.tag; }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({}); await settle(); }
}
const page = { focused: null, byId: {}, stubs: {}, said: [] };
class SayEl extends El {
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; if (v) page.said.push(String(v)); }
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const h = (tag, attrs, ...kids) => {
  const el = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'hidden') el.hidden = true;
    el.setAttribute(k, v === true ? '' : String(v));
    if (k === 'id') page.byId[v] = el;
  }
  const add = (k) => { if (k == null || k === false) return; if (Array.isArray(k)) { k.forEach(add); return; } el.append(k.nodeType ? k : new Text(String(k))); };
  kids.forEach(add);
  return el;
};
const clear = (el) => { el.children = []; el._text = ''; return el; };
// The page's static elements, by the selectors lab_photo.js asks for; rows the file builds are found by id.
const $ = (sel) => {
  const id = sel.replace(/^#/, '');
  if (page.byId[id]) return page.byId[id];
  return (page.stubs[sel] ||= new El('div'));
};
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();
const find = (el, pred, out = []) => { if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach((c) => find(c, pred, out)); } return out; };

page.stubs['#lab-photo-progress'] = new SayEl('p');
const TODAY = '2026-10-15';
const log = { consent: [], uploads: [], saved: [], shown: [], toasts: [], signals: [], notices: [] };
let status = { enabled: true, opted_in: true, features: { lab_report: true }, routes: { labs: { available: true, text: 'Runs on your local AI (ollama.lan:11434).' } } };
let answer = null;
let existing = [];
// PDF stand-ins: what the file's pages are, what the AI says about each drawn page (by its picture's name), how consent goes.
const abortError = () => Object.assign(new Error('Aborted'), { name: 'AbortError' });
const pdfLog = { opens: [], closes: 0, opened: 0, renders: [] };
const pdfState = { supported: true, pages: 4, openError: null, renderErrors: new Map(), rules: new Map(), consent: 'send', holdFor: new Set() };
const KH = {
  h, $, clear, toast: (m, k) => log.toasts.push([k, m]),
  flags: { MOCK: false },
  util: {
    todayStr: () => TODAY,
    addDays: (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10),
  },
  ai: {
    status: async () => status,
    prepareJpeg: async (file) => `jpeg:${file.name}`, // (a drawn page is named page-3.jpg)
    withConsent: async (purpose, send, preview, trigger, feature) => {
      log.consent.push([purpose, feature]);
      if (pdfState.consent === 'declined') return null;
      if (pdfState.consent === 'ask') {
        try { return await send(); } catch (e) {
          if (e.status !== 409) throw e;
          log.notices.push([...e.data.consent.notice]); // what the consent sheet would show
          return send();
        }
      }
      return send();
    },
    uploadPhoto: async (kind, blob, dry, signal) => {
      log.uploads.push([kind, blob, dry]);
      log.signals.push(!!signal);
      if (dry) return { dry_run: true };
      if (pdfState.holdFor.has(blob) && signal) { // a request that never answers; only Cancel (the signal) ends it
        await new Promise((resolve, reject) => { if (signal.aborted) reject(abortError()); signal.addEventListener('abort', () => reject(abortError())); });
      }
      if (pdfState.rules.has(blob)) {
        const rule = pdfState.rules.get(blob);
        if (rule instanceof Error) throw rule;
        if (typeof rule === 'function') return rule();
        return rule;
      }
      return answer;
    },
    showSent: async (dry) => { log.shown.push(dry); return true; },
  },
  labs: { load: async () => ({ labs: existing }) },
  pdfPages: {
    supported: () => pdfState.supported,
    open: async (file, opts = {}) => {
      pdfLog.opens.push({ name: file.name, signal: !!opts.signal });
      if (pdfState.openError) throw Object.assign(new Error('refused'), pdfState.openError);
      pdfLog.opened += 1;
      let closed = false;
      return {
        numPages: pdfState.pages,
        render: async (n, o = {}) => {
          pdfLog.renders.push(n);
          if (o.signal && o.signal.aborted) throw abortError();
          if (pdfState.renderErrors.has(n)) throw Object.assign(new Error('x'), { code: 'damaged' });
          return { name: `page-${n}.jpg`, type: 'image/jpeg' };
        },
        close: () => { if (!closed) { closed = true; pdfLog.closes += 1; } },
      };
    },
  },
  views: { labs: {
    fmtDay: (iso) => `day ${iso}`,
    saveImported: async (kept, box, source, onSaved) => {
      log.saved.push({ kept, source });
      onSaved();
      clear(box).append(h('p', {}, `Saved ${kept.length}`));
      return { saved: kept.length };
    },
  } },
};
const context = vm.createContext({ window: { KH }, console, AbortController });
for (const file of [['js', 'engine', 'rules.js'], ['js', 'engine', 'kidney_function.js'], ['js', 'views', 'lab_photo.js']]) {
  vm.runInContext(read(...file), context, { filename: file.join('/') });
}
const LP = context.window.KH.labPhoto;
const out = {};

const ROWS = [
  { analyte: 'potassium', label: 'Potassium', value: 5.4, unit: 'mmol/L', display: '5.4 mmol/L', taken_on: '2026-10-07', printed_date: '2026-10-07', date_problem: null, date_note: null },
  { analyte: 'phosphate', label: 'Phosphate', value: 1.2, unit: 'mmol/L', display: '1.2 mmol/L = 3.7 mg/dL', taken_on: '2026-10-07', printed_date: '2026-10-07', date_problem: null, date_note: null },
  { analyte: 'creatinine', label: 'Creatinine (blood)', value: 88, unit: 'µmol/L', display: '88 µmol/L = 1.00 mg/dL', taken_on: null, printed_date: '03/04/2026', date_problem: 'ambiguous', date_note: 'The date on the report could mean two different days. Enter the date of the test.' },
];
const NOTICE = 'Read by AI from your photo. Check each value against the report before you tick it.';
const answerOk = (rows = ROWS, extra = {}) => ({ status: 'ok', rows, dropped: { unknown_analyte: 2, unknown_unit: 0, out_of_range: 0 },
  dropped_notes: ['2 lines were not recognised: it is not one of the tests this app keeps.'], notice: NOTICE, ...extra });
const checkboxes = (root) => find(root, (e) => e.tag === 'input' && e.attrs.type === 'checkbox');
const buttons = (root) => find(root, (e) => e.tag === 'button');
const byText = (root, label) => buttons(root).find((b) => text(b).startsWith(label));

// 1. The review table: every row starts unticked, the notice and the counts are there, a row without a date waits for one.
{
  const box = new El('div');
  const saves = [];
  const view = LP.review(box, answerOk(), { existing: [], today: TODAY, onSave: (kept) => saves.push(kept), onDiscard: () => { log.discarded = true; } });
  const boxes = checkboxes(box);
  out.start = {
    notice: text(box).includes(NOTICE), dropped: text(box).includes('2 lines were not recognised'),
    summary: text(find(box, (e) => e.attrs.class === 'lab-import-summary')[0]),
    ticked: boxes.map((b) => b.checked), disabled: boxes.map((b) => b.disabled),
    save: { text: text(view.save), disabled: view.save.disabled },
    dateField: find(box, (e) => e.tag === 'input' && e.attrs.type === 'date').map((e) => ({ id: e.attrs.id, max: e.attrs.max, min: e.attrs.min })),
    dateNote: text(find(box, (e) => e.attrs.class === 'hint warn')[0]),
    dateNeeded: find(box, (e) => e.attrs.class === 'lab-row-date').map(text),
    classes: find(box, (e) => e.tag === 'ul').map((e) => e.attrs.class),
  };
  // Tick the first two; the third (no date) cannot be ticked, and an unreadable or future date does not enable it.
  boxes[0].checked = true; await boxes[0].fire('change');
  boxes[1].checked = true; await boxes[1].fire('change');
  out.twoTicked = { save: text(view.save), disabled: view.save.disabled };
  const date = find(box, (e) => e.tag === 'input' && e.attrs.type === 'date')[0];
  for (const bad of ['', '2099-01-01', '1899-12-31', 'x']) {
    date.value = bad; await date.fire('change');
    out[`badDate:${bad}`] = { disabled: boxes[2].disabled, ticked: boxes[2].checked };
  }
  date.value = '2026-04-03'; await date.fire('change');
  out.goodDate = { disabled: boxes[2].disabled, when: text(find(box, (e) => e.attrs.class === 'lab-row-date')[2]) };
  boxes[2].checked = true; await boxes[2].fire('change');
  out.threeTicked = { save: text(view.save), disabled: view.save.disabled };
  boxes[1].checked = false; await boxes[1].fire('change');
  await view.save.fire('click');
  out.saveSends = saves[0];
  await view.discard.fire('click');
  out.discarded = log.discarded === true;
}

// 2. A date cleared again after a tick unticks the row (nothing without a date is ever sent).
{
  const box = new El('div');
  const saves = [];
  const view = LP.review(box, answerOk([ROWS[2]]), { today: TODAY, onSave: (kept) => saves.push(kept) });
  const cb = checkboxes(box)[0];
  const date = find(box, (e) => e.tag === 'input' && e.attrs.type === 'date')[0];
  date.value = '2026-04-03'; await date.fire('change');
  cb.checked = true; await cb.fire('change');
  const withDate = text(view.save);
  date.value = ''; await date.fire('change');
  out.clearedDate = { withDate, afterClear: text(view.save), ticked: cb.checked, disabled: cb.disabled, saveDisabled: view.save.disabled };
  await view.save.fire('click');
  out.clearedDateSends = saves.length;
}

// 3. "already saved" is shown for a result with the same test, date and shown value; the row still starts unticked.
{
  const box = new El('div');
  LP.review(box, answerOk([ROWS[0]]), { existing: [{ analyte: 'potassium', taken_on: '2026-10-07', value: 5.4 }, { analyte: 'nonsense', taken_on: '2026-10-07', value: 1 }], today: TODAY });
  out.alreadySaved = { tag: text(find(box, (e) => e.attrs.class === 'lab-import-saved')[0]), ticked: checkboxes(box).map((b) => b.checked) };
}

// 4. Text from the server is drawn as text: a hostile label or note makes no element.
{
  const box = new El('div');
  const evil = { ...ROWS[0], label: '<img src=x onerror=alert(1)>Potassium', display: '<b>5.4</b> mmol/L', printed_date: '<script>1</script>', taken_on: null, date_note: '<i>Enter the date</i>' };
  LP.review(box, answerOk([evil], { dropped_notes: ['<a href="http://evil.example/">1 line</a>'], notice: '<u>Read by AI</u>' }), { today: TODAY });
  const tags = new Set(find(box, () => true).map((e) => e.tag));
  out.hostile = { tags: [...tags].sort(), hasText: text(box).includes('<img src=x onerror=alert(1)>Potassium'), noRealElements: !tags.has('img') && !tags.has('script') && !tags.has('a') && !tags.has('b') && !tags.has('i') && !tags.has('u') };
}

// 5. Instead of a table: the server's message for a photo that is not a report, one that cannot be read, or nothing the app keeps.
{
  const box = new El('div');
  LP.nothing(box, { status: 'not_a_lab_report', message: 'This does not look like a lab report.', dropped_notes: [] });
  out.notAReport = text(box);
  LP.nothing(box, { status: 'no_results', message: 'No result the app knows was found in this photo.', dropped_notes: ['3 lines were not recognised: it is not one of the tests this app keeps.'] });
  out.noResults = text(box);
}

// 6. The card is offered only when the server says so, and says why when it does not.
{
  const section = $('#lab-photo');
  const controls = $('#lab-photo-controls');
  const why = $('#lab-photo-why');
  section.hidden = true; controls.hidden = true; why.hidden = true;
  const state = () => ({ section: section.hidden, controls: controls.hidden, why: why.hidden, whyText: why.textContent });
  await LP.show(); out.offered = state();
  status = { enabled: false, demo: true }; await LP.show(); out.aiOff = state();
  status = { enabled: true, opted_in: true, features: { lab_report: false }, routes: { labs: { available: false, text: 'Needs a local AI on your own network, which is not set up on this server, so it is off.' } } };
  await LP.show(); out.noLocalAi = state();
  status = { enabled: true, opted_in: false, features: { lab_report: false }, routes: { labs: { available: false, text: 'x' } } };
  await LP.show(); out.notOptedIn = state();
  status = { enabled: true, opted_in: true, features: { lab_report: false }, routes: { labs: { available: true, text: 'Runs on your local AI (ollama.lan:11434).' } } };
  await LP.show(); out.noVisionModel = state();
  status = { enabled: true, opted_in: true, features: { lab_report: false }, routes: { labs: { available: false, text: 'Switched off by your admin.' } } };
  await LP.show(); out.switchedOff = state();
  status = { enabled: true, opted_in: true, features: { lab_report: true }, routes: { labs: { available: true, text: '' } } };
  await LP.show(); out.offeredAgain = state();
}

// 7. The whole flow through the card's own controls: choose a photo, read it (consent for labs, upload as a lab report), tick, save.
{
  answer = answerOk([ROWS[0], ROWS[1]]);
  existing = [];
  const file = $('#lab-photo-file');
  file.files = [{ name: 'report.png' }];
  await file.fire('change');
  const readBtn = $('#lab-photo-read');
  await readBtn.fire('click');
  const results = $('#lab-photo-results');
  const boxes = checkboxes(results);
  out.flow = {
    consent: log.consent.map((c) => [...c]), uploads: log.uploads.map((u) => [...u]), ticked: boxes.map((b) => b.checked), readText: text(readBtn),
    focused: page.focused,
  };
  boxes[1].checked = true; await boxes[1].fire('change');
  await byText(results, 'Save').fire('click');
  out.flowSaved = { saved: log.saved.map((x) => ({ ...x })), input: file.value, results: text(results) };
  // "What will be sent?" asks for a dry run of the same upload and shows it
  file.files = [{ name: 'again.png' }]; await file.fire('change');
  await $('#lab-photo-what').fire('click');
  out.what = { uploads: log.uploads.slice(-1)[0], shown: [...log.shown] };
  // reading without a photo says so
  file.files = []; await file.fire('change');
  await readBtn.fire('click');
  out.noPhoto = text($('#lab-photo-error'));
}

// ---------------------------------------------------------------------------
// 8. A PDF (design note 13)
// ---------------------------------------------------------------------------
const pdfFile = (name = 'results.pdf', size = 300000) => ({ name, type: 'application/pdf', size });
const fileInput = $('#lab-photo-file');
const pagesBox = $('#lab-photo-pages');
const resultsBox = $('#lab-photo-results');
const readButton = $('#lab-photo-read');
const cancelButton = $('#lab-photo-cancel');
const progressBox = $('#lab-photo-progress');
const errorBox = $('#lab-photo-error');
const pageInputs = () => find(pagesBox, (e) => e.tag === 'input' && e.attrs.type === 'checkbox');
const ticks = () => pageInputs().map((cb) => (cb.checked ? 1 : 0)).join('');
const disabledBoxes = () => pageInputs().map((cb) => (cb.disabled ? 1 : 0)).join('');
const pickPdf = async (file = pdfFile(), pages = 4) => { pdfState.pages = pages; fileInput.files = [file]; await fileInput.fire('change'); await settle(); };
const resetPdf = async () => {
  fileInput.files = []; await fileInput.fire('change'); // choosing nothing lets go of the last PDF, as a new pick does
  Object.assign(pdfState, { supported: true, pages: 4, openError: null, consent: 'send' });
  pdfState.renderErrors.clear(); pdfState.rules.clear(); pdfState.holdFor.clear();
  log.uploads.length = 0; log.signals.length = 0; log.consent.length = 0; log.notices.length = 0; log.saved.length = 0; log.shown.length = 0;
  pdfLog.opens.length = 0; pdfLog.renders.length = 0; pdfLog.closes = 0; pdfLog.opened = 0; page.said.length = 0;
};
const pageRow = (analyte, label, value, taken_on = '2026-10-07') => ({ analyte, label, value, unit: 'mmol/L', display: `${value} mmol/L`, taken_on, printed_date: taken_on, date_problem: null, date_note: null });
const POTASSIUM = pageRow('potassium', 'Potassium', 5.4);
const PHOSPHATE = pageRow('phosphate', 'Phosphate', 1.2);
const ALBUMIN = { ...pageRow('albumin', 'Albumin', 38), unit: 'g/L', display: '38 g/L' };
const hintLines = (box) => find(box, (e) => e.tag === 'p' && /hint/.test(e.attrs.class || '') && !e.hidden).map(text);
const state = () => ({ pickCount: pdfLog.opens.length, opened: pdfLog.opened, closes: pdfLog.closes, list: pagesBox.hidden ? 'hidden' : 'shown', boxes: pageInputs().length, input: fileInput.value });
out.pdf = {};
const pdfOut = out.pdf;

// 8.1 Choosing a PDF opens it here and lists its pages; nothing is sent.
{
  await resetPdf();
  answer = answerOk([POTASSIUM]);
  await pickPdf(pdfFile('results.pdf', 300000), 8);
  pdfOut.pick = {
    opened: pdfLog.opens.map((o) => ({ ...o })), ticks: ticks(), disabled: disabledBoxes(), state: state(), uploads: log.uploads.length, consent: log.consent.length,
    legend: text(find(pagesBox, (e) => e.tag === 'legend')[0]), labels: find(pagesBox, (e) => e.tag === 'label').map(text),
    hints: find(pagesBox, (e) => e.attrs.class === 'hint').map(text), progress: progressBox.hidden, said: [...page.said], error: text(errorBox),
  };
  // the ticks: at most 10; with 12 pages 1-6 start ticked
  await pickPdf(pdfFile('twelve.pdf'), 12);
  const first = ticks();
  const boxes = pageInputs();
  for (const n of [7, 8, 9, 10]) { boxes[n - 1].checked = true; await boxes[n - 1].fire('change'); }
  const full = { ticks: ticks(), disabled: disabledBoxes(), count: text(find(pagesBox, (e) => e.attrs.role === 'status')[0]) };
  boxes[0].checked = false; await boxes[0].fire('change');
  const freed = { ticks: ticks(), disabled: disabledBoxes(), count: text(find(pagesBox, (e) => e.attrs.role === 'status')[0]) };
  pdfOut.ticks = { first, full, freed, closedFirst: pdfLog.closes };
  // a one-page PDF; a PDF with 3 pages ticks them all
  await pickPdf(pdfFile('one.pdf'), 1);
  pdfOut.onePage = { ticks: ticks(), count: text(find(pagesBox, (e) => e.attrs.role === 'status')[0]) };
}

// 8.2 Reading: one request per ticked page, each with that page's own picture, merged into one table.
{
  await resetPdf();
  answer = null;
  pdfState.rules.set('jpeg:page-1.jpg', { ...answerOk([POTASSIUM, PHOSPHATE], { dropped_notes: ['2 lines were not recognised: it is not one of the tests this app keeps.'] }) });
  pdfState.rules.set('jpeg:page-2.jpg', { ...answerOk([POTASSIUM, ALBUMIN]) }); // the potassium line is the same as page 1's
  pdfState.rules.set('jpeg:page-3.jpg', Object.assign(new Error('The photo is too wide for its height.'), { status: 422, detail: 'The photo is too wide for its height.' }));
  pdfState.rules.set('jpeg:page-4.jpg', { status: 'no_results', message: 'No result the app knows was found in this photo.', rows: [], dropped_notes: [] });
  await pickPdf(pdfFile('four.pdf'), 4);
  const pickedOpens = pdfLog.opened;
  await readButton.fire('click');
  const boxes = checkboxes(resultsBox);
  pdfOut.read = {
    renders: [...pdfLog.renders], uploads: log.uploads.map((u) => [u[1], u[2]]), signals: [...log.signals], consent: log.consent.map((c) => [...c]),
    said: [...page.said].filter((x) => x.startsWith('Reading')), summary: text(find(resultsBox, (e) => e.attrs.class === 'lab-import-summary')[0]),
    notice: text(find(resultsBox, (e) => e.attrs.role === 'note')[0]),
    rows: find(resultsBox, (e) => e.tag === 'li' && e.attrs.class === 'lab-row').map(text),
    pages: find(resultsBox, (e) => e.attrs.class === 'lab-row-page').map(text),
    ticked: boxes.map((b) => b.checked), lines: hintLines(resultsBox),
    warned: find(resultsBox, (e) => e.attrs.class === 'hint warn' && !e.hidden).map(text),
    state: state(), reopened: pdfLog.opened - pickedOpens, cancelHidden: cancelButton.hidden, readText: text(readButton), readDisabled: readButton.disabled,
    busy: resultsBox.attrs['aria-busy'] || null, progressHidden: progressBox.hidden, ticksAfter: ticks(), disabledAfter: disabledBoxes(),
    pdfAsPicture: log.uploads.some((u) => typeof u[1] !== 'string'),
    focused: page.focused,
  };
  // Save sends only the ticked rows, through the shared save, "from your PDF"; then everything is let go.
  boxes[2].checked = true; await boxes[2].fire('change');
  boxes[0].checked = true; await boxes[0].fire('change');
  await byText(resultsBox, 'Save').fire('click');
  pdfOut.saved = { saved: log.saved.map((x) => ({ ...x })), state: state(), results: text(resultsBox), progress: progressBox.hidden, closes: pdfLog.closes };
}

// 8.3 Cancel stops between pages and aborts the request in flight; what was read stays.
{
  await resetPdf();
  answer = null;
  pdfState.rules.set('jpeg:page-1.jpg', answerOk([POTASSIUM]));
  await pickPdf(pdfFile('cancel.pdf'), 3);
  pdfState.holdFor.add('jpeg:page-2.jpg'); // page 2's request never answers; pressing Cancel aborts it
  const reading = readButton.fire('click');
  await settle(); await settle();
  const during = { cancelHidden: cancelButton.hidden, readText: text(readButton), readDisabled: readButton.disabled, progress: progressBox.textContent, boxes: disabledBoxes(), busy: resultsBox.attrs['aria-busy'] || null };
  await cancelButton.fire('click');
  await reading;
  pdfOut.cancel = {
    during, cancelHidden: cancelButton.hidden, readText: text(readButton), uploads: log.uploads.map((u) => u[1]), renders: [...pdfLog.renders],
    summary: text(find(resultsBox, (e) => e.attrs.class === 'lab-import-summary')[0]),
    lines: hintLines(resultsBox), rows: find(resultsBox, (e) => e.tag === 'li' && e.attrs.class === 'lab-row').map(text),
    closes: pdfLog.closes, opened: pdfLog.opened, listStill: pagesBox.hidden ? 'hidden' : 'shown', progressHidden: progressBox.hidden,
  };
}

// 8.4 Cancel with nothing read yet; and the consent sheet declined.
{
  await resetPdf();
  answer = answerOk([POTASSIUM]);
  await pickPdf(pdfFile('declined.pdf'), 2);
  pdfState.consent = 'declined';
  await readButton.fire('click');
  pdfOut.declined = {
    uploads: log.uploads.length, renders: [...pdfLog.renders], text: text(resultsBox), closes: pdfLog.closes, list: pagesBox.hidden ? 'hidden' : 'shown',
    readText: text(readButton), readDisabled: readButton.disabled, input: fileInput.value,
  };
  // the list is still there: reading again works once consent is given
  pdfState.consent = 'send';
  await readButton.fire('click');
  pdfOut.afterDecline = { uploads: log.uploads.length, rows: find(resultsBox, (e) => e.tag === 'li' && e.attrs.class === 'lab-row').length, reopened: pdfLog.opened, closes: pdfLog.closes };
}

// 8.5 The first page's 409 gets the line about the PDF before the consent sheet is drawn.
{
  await resetPdf();
  answer = answerOk([POTASSIUM]);
  let asked = 0;
  pdfState.rules.set('jpeg:page-1.jpg', () => {
    asked += 1;
    if (asked === 1) throw Object.assign(new Error('consent'), { status: 409, data: { consent_required: true, consent: { purpose: 'labs', notice: ['Your photo goes to ollama.lan.', 'Crop it.'] } } });
    return answerOk([POTASSIUM]);
  });
  pdfState.consent = 'ask';
  await pickPdf(pdfFile('consent.pdf'), 2);
  await readButton.fire('click');
  pdfOut.consentNotice = { notices: log.notices.map((n) => [...n]), uploads: log.uploads.map((u) => [u[1], u[2]]) };
}

// 8.6 A page that cannot be drawn, a systemic refusal, a browser that cannot.
{
  await resetPdf();
  answer = answerOk([POTASSIUM]);
  pdfState.renderErrors.set(2, true);
  pdfState.rules.set('jpeg:page-3.jpg', answerOk([PHOSPHATE]));
  await pickPdf(pdfFile('undrawable.pdf'), 3);
  await readButton.fire('click');
  pdfOut.undrawable = {
    renders: [...pdfLog.renders], uploads: log.uploads.map((u) => u[1]),
    lines: hintLines(resultsBox), rows: find(resultsBox, (e) => e.tag === 'li' && e.attrs.class === 'lab-row').map(text),
  };

  await resetPdf();
  pdfState.rules.set('jpeg:page-1.jpg', Object.assign(new Error('Daily limit reached.'), { status: 429, detail: 'Daily limit reached.' }));
  await pickPdf(pdfFile('limit.pdf'), 3);
  await readButton.fire('click');
  pdfOut.limit = { uploads: log.uploads.map((u) => u[1]), text: text(resultsBox), closes: pdfLog.closes };

  await resetPdf();
  pdfState.rules.set('jpeg:page-2.jpg', Object.assign(new Error('The AI gave an answer that failed its checks.'), { status: 502, detail: 'The AI gave an answer that failed its checks.' }));
  pdfState.rules.set('jpeg:page-1.jpg', answerOk([POTASSIUM]));
  pdfState.rules.set('jpeg:page-3.jpg', answerOk([PHOSPHATE]));
  await pickPdf(pdfFile('badanswer.pdf'), 3);
  await readButton.fire('click');
  pdfOut.badAnswer = { uploads: log.uploads.map((u) => u[1]), lines: hintLines(resultsBox), rows: find(resultsBox, (e) => e.tag === 'li' && e.attrs.class === 'lab-row').length };

  // no row on any page: the headline, then why each page had none
  await resetPdf();
  pdfState.rules.set('jpeg:page-1.jpg', { status: 'not_a_lab_report', message: 'This does not look like a lab report.', rows: [], dropped_notes: [] });
  pdfState.rules.set('jpeg:page-2.jpg', { status: 'unreadable', message: 'The photo could not be read.', rows: [], dropped_notes: [] });
  await pickPdf(pdfFile('nothing.pdf'), 2);
  await readButton.fire('click');
  pdfOut.nothing = text(resultsBox);

  // nothing ticked
  await resetPdf();
  await pickPdf(pdfFile('none.pdf'), 3);
  for (const cb of pageInputs()) { cb.checked = false; await cb.fire('change'); }
  await readButton.fire('click');
  pdfOut.noneTicked = { error: text(errorBox), uploads: log.uploads.length, renders: pdfLog.renders.length, count: text(find(pagesBox, (e) => e.attrs.role === 'status')[0]) };
}

// 8.7 The messages for a file that cannot be used: shown as text, the choice forgotten, nothing sent.
{
  const cases = {
    too_big: { code: 'too_big', size: 25 * 1024 * 1024 }, too_big_small: { code: 'too_big', size: 20 * 1024 * 1024 + 123456 }, not_pdf: { code: 'not_pdf' }, password: { code: 'password' },
    damaged: { code: 'damaged' }, too_many_pages: { code: 'too_many_pages', numPages: 80 }, browser: { code: 'browser' }, unknown: { code: undefined },
  };
  pdfOut.messages = {};
  for (const [name, failure] of Object.entries(cases)) {
    await resetPdf();
    pdfState.openError = failure;
    await pickPdf(pdfFile('bad.pdf', 25 * 1024 * 1024), 4);
    pdfOut.messages[name] = { error: text(errorBox), state: state(), uploads: log.uploads.length };
  }
  await resetPdf();
  pdfState.supported = false;
  await pickPdf(pdfFile('old-browser.pdf'), 4);
  pdfOut.unsupported = { error: text(errorBox), opens: pdfLog.opens.length, input: fileInput.value };
  pdfState.supported = true;
}

// 8.8 A new pick lets go of the old PDF; so does Discard; a photo after a PDF is read as a photo.
{
  await resetPdf();
  answer = answerOk([POTASSIUM, PHOSPHATE]);
  await pickPdf(pdfFile('first.pdf'), 3);
  await pickPdf(pdfFile('second.pdf'), 5);
  pdfOut.secondPick = { opened: pdfLog.opened, closes: pdfLog.closes, boxes: pageInputs().length, ticks: ticks() };
  fileInput.files = [{ name: 'screenshot.png', type: 'image/png' }]; await fileInput.fire('change'); await settle();
  pdfOut.photoAfter = { closes: pdfLog.closes, list: pagesBox.hidden ? 'hidden' : 'shown', boxes: pageInputs().length };
  await readButton.fire('click');
  pdfOut.photoRead = { uploads: log.uploads.map((u) => [u[1], u[2]]), rows: find(resultsBox, (e) => e.tag === 'li' && e.attrs.class === 'lab-row').map(text), pageTags: find(resultsBox, (e) => e.attrs.class === 'lab-row-page').length,
    summary: text(find(resultsBox, (e) => e.attrs.class === 'lab-import-summary')[0]) };
  // a PDF, read, then Discard
  await resetPdf();
  pdfState.rules.set('jpeg:page-1.jpg', answerOk([POTASSIUM]));
  await pickPdf(pdfFile('discard.pdf'), 2);
  await readButton.fire('click');
  await $('#lab-photo-discard').fire('click');
  pdfOut.discard = { closes: pdfLog.closes, state: state(), results: text(resultsBox), error: text(errorBox), focused: page.focused };
  // a photo's Save headline still says "your photo"
  pdfOut.photoSaveSource = log.saved.length;
}

// 8.9 "What will be sent?" for a PDF draws the first ticked page and shows the dry run; it closes the PDF again.
{
  await resetPdf();
  await pickPdf(pdfFile('what.pdf'), 3);
  const boxes = pageInputs();
  boxes[0].checked = false; await boxes[0].fire('change');
  await $('#lab-photo-what').fire('click');
  pdfOut.what = { renders: [...pdfLog.renders], uploads: log.uploads.map((u) => [u[1], u[2]]), shown: [...log.shown], closes: pdfLog.closes, signals: [...log.signals] };
}

// 8.10 A run that ends closes pdf.js; reading again opens the chosen file again.
{
  await resetPdf();
  pdfState.rules.set('jpeg:page-1.jpg', answerOk([POTASSIUM]));
  pdfState.rules.set('jpeg:page-2.jpg', answerOk([PHOSPHATE]));
  await pickPdf(pdfFile('again.pdf'), 2);
  await readButton.fire('click');
  const once = { opened: pdfLog.opened, closes: pdfLog.closes, file: fileInput.value };
  await readButton.fire('click');
  pdfOut.again = { once, twice: { opened: pdfLog.opened, closes: pdfLog.closes }, renders: [...pdfLog.renders] };
}

// 8.10b Pages that are not the first: "Reading page 1 of 2… (page 2 of your PDF)".
{
  await resetPdf();
  pdfState.rules.set('jpeg:page-2.jpg', answerOk([POTASSIUM]));
  pdfState.rules.set('jpeg:page-4.jpg', answerOk([PHOSPHATE]));
  await pickPdf(pdfFile('gaps.pdf'), 5);
  const boxes = pageInputs();
  for (const n of [1, 3, 5, 6]) { if (boxes[n - 1]) { boxes[n - 1].checked = false; await boxes[n - 1].fire('change'); } }
  await readButton.fire('click');
  pdfOut.gaps = { said: page.said.filter((x) => x.startsWith('Reading')), renders: [...pdfLog.renders], pages: find(resultsBox, (e) => e.attrs.class === 'lab-row-page').map(text) };
}

// 8.11 The merge by itself: the first page keeps a repeated row; a row without a date repeats too; different values stay.
{
  const LP2 = context.window.KH.labPhoto;
  const a = { ...POTASSIUM }; const b = { ...POTASSIUM, value: 5.5, display: '5.5 mmol/L' }; const c = { ...POTASSIUM, taken_on: null };
  const merged = LP2.mergePages([{ page: 1, rows: [a, c] }, { page: 2, rows: [{ ...a }, b, { ...c }] }, { page: 3, rows: [] }]);
  pdfOut.merge = { rows: merged.rows.map((r) => [r.analyte, r.value, r.taken_on, r.page]), duplicates: merged.duplicates };
  pdfOut.exported = { messages: Object.keys(LP2).sort(), noticeLine: LP2.PDF_SEND_LINE, notice: LP2.PDF_NOTICE, max: LP2.MAX_TICKED, def: LP2.DEFAULT_TICKED };
}

console.log(JSON.stringify(out));
