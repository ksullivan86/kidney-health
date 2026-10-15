#!/usr/bin/env node
// Runs app/static/js/views/lab_photo.js against a tiny fake page and fake server answers, together with the real
// js/engine/rules.js and js/engine/kidney_function.js (the parity-tested conversions), and prints what happened as JSON, so
// pytest (tests/test_lab_photo_ui.py) can check the behaviour without a browser: the card is offered only when the server says
// so (and says why when it is not), every row of the review table starts unticked, a row without a date cannot be ticked until
// the person enters one, only ticked rows are handed to the shared save (POST /api/labs/import), and what the server sends is
// drawn as text. The helpers the file takes from KH (h, $, clear, util, ai, labs) are stand-ins with the contract of js/core.js.
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
const page = { focused: null, byId: {}, stubs: {} };
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

const TODAY = '2026-10-15';
const log = { consent: [], uploads: [], saved: [], shown: [], toasts: [] };
let status = { enabled: true, opted_in: true, features: { lab_report: true }, routes: { labs: { available: true, text: 'Runs on your local AI (ollama.lan:11434).' } } };
let answer = null;
let existing = [];
const KH = {
  h, $, clear, toast: (m, k) => log.toasts.push([k, m]),
  flags: { MOCK: false },
  util: {
    todayStr: () => TODAY,
    addDays: (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10),
  },
  ai: {
    status: async () => status,
    prepareJpeg: async (file) => `jpeg:${file.name}`,
    withConsent: async (purpose, send, preview, trigger, feature) => { log.consent.push([purpose, feature]); return send(); },
    uploadPhoto: async (kind, blob, dry) => { log.uploads.push([kind, blob, dry]); return dry ? { dry_run: true } : answer; },
    showSent: async (dry) => { log.shown.push(dry); return true; },
  },
  labs: { load: async () => ({ labs: existing }) },
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
const context = vm.createContext({ window: { KH }, console });
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
    consent: log.consent, uploads: log.uploads, ticked: boxes.map((b) => b.checked), readText: text(readBtn),
    focused: page.focused,
  };
  boxes[1].checked = true; await boxes[1].fire('change');
  await byText(results, 'Save').fire('click');
  out.flowSaved = { saved: log.saved, input: file.value, results: text(results) };
  // "What will be sent?" asks for a dry run of the same upload and shows it
  file.files = [{ name: 'again.png' }]; await file.fire('change');
  await $('#lab-photo-what').fire('click');
  out.what = { uploads: log.uploads.slice(-1)[0], shown: log.shown };
  // reading without a photo says so
  file.files = []; await file.fire('change');
  await readBtn.fire('click');
  out.noPhoto = text($('#lab-photo-error'));
}

console.log(JSON.stringify(out));
