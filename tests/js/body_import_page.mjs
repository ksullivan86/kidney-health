#!/usr/bin/env node
// Runs app/static/js/views/body_import.js (the sheet that imports weights and blood pressure from the Health app's export.xml) against a tiny
// fake page, a fake backend that keeps the server's batch rules (app/body.py: 1 to 1,000 rows a request, a known source_key is skipped, a row
// that would be the 21st weight or 31st reading of its day refuses the WHOLE request and writes nothing, a list is at most 366 days) and fake
// files, together with the real js/engine/rules.js, apple_health.js and body.js, and prints what happened as JSON, so pytest
// (tests/test_body_import_ui.py) can check the behaviour without a browser: what the review says, that the watch readings start unticked, the
// default period, what goes up (no source name, source apple_health), the per-day trimming against the rows the person already has, a refusal
// in the middle (the server's words and what was already added), Cancel and Stop, that text from the file is drawn as text, and that nothing
// calls the network except through KH.api. The helpers the file takes from KH (h, $, clear, api, state, toast, router, sheets, util) are
// stand-ins with the contract of js/core.js. The export.zip picks (docs/dev/research/11-reading-a-zip-in-the-browser.md section 4.5) run the real
// js/engine/zip.js on archives made in memory by tests/js/zip_writer.mjs: the same rows as the same export.xml picked by itself, each message,
// Cancel while a .zip is being read, and a browser without DecompressionStream.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { makeZip, zipFile as zipFileOf } from './zip_writer.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (...p) => readFileSync(join(ROOT, 'app', 'static', ...p), 'utf8');

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) {
    this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this._text = '';
    this.disabled = false; this.checked = false; this.hidden = false; this.value = ''; this.files = null; this.open = false;
  }
  get textContent() { return this._text; }
  set textContent(v) { this.children.forEach(forget); this._text = String(v); this.children = []; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  getAttribute(k) { return this.attrs[k]; }
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'object' && k && k.nodeType ? k : new Text(String(k))); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  focus() { page.focused = this.attrs.id || this.tag; }
  close() { this.open = false; for (const fn of this.handlers.close || []) fn({}); }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({}); await settle(); }
}
const page = { focused: null, byId: {} };
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
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
const forget = (el) => { if (el.nodeType !== 1) return; if (el.attrs.id && page.byId[el.attrs.id] === el) delete page.byId[el.attrs.id]; el.children.forEach(forget); };
const clear = (el) => { el.children.forEach(forget); el.children = []; el._text = ''; return el; };
const stub = (id, tag = 'div') => { const el = new El(tag); el.attrs.id = id; page.byId[id] = el; return el; };
const $ = (sel) => page.byId[sel.replace(/^#/, '')] || new El('div');
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();
const find = (el, pred, out = []) => { if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach((c) => find(c, pred, out)); } return out; };

// the elements of the sheet in index.html
const dlg = stub('sheet-body-import', 'dialog');
const input = stub('body-import-file', 'input');
const pickEl = stub('body-import-pick');
const problemEl = stub('body-import-problem', 'p'); problemEl.hidden = true;
const statusEl = stub('body-import-status', 'p');
const reviewEl = stub('body-import-review'); reviewEl.hidden = true;
const cancelBtn = stub('body-import-cancel', 'button'); cancelBtn.textContent = 'Close';
const goBtn = stub('body-import-go', 'button'); goBtn.hidden = true; goBtn.textContent = 'Import';

// ---- dates (js/core.js)
const TODAY = '2026-10-22';
const parseDate = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const localISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (s, n) => { const d = parseDate(s); d.setDate(d.getDate() + n); return localISO(d); };
const daysBetween = (a, b) => Math.round((parseDate(b) - parseDate(a)) / 86400000);

// ---- the fake backend: app/body.py's batch routes and list routes
const MAX = { weights: 20, readings: 30 };
const ALLOWED = {
  weights: ['date', 'time', 'kg', 'context', 'note', 'source', 'source_key'],
  readings: ['date', 'time', 'systolic', 'diastolic', 'pulse', 'context', 'note', 'source', 'source_key'],
};
function backend({ weights = [], readings = [], listFails = false, delay = 0 } = {}) {
  const st = { weights: weights.map((r, i) => ({ id: i + 1, source: 'manual', ...r })), readings: readings.map((r, i) => ({ id: i + 1, source: 'manual', ...r })),
    calls: [], lists: [], fail: {}, delay };
  const refuse = (status, detail) => Object.assign(new Error(detail), { status, detail });
  const post = (kind, many) => async (rows) => {
    const sent = st.calls.filter((c) => c.kind === kind).length;
    st.calls.push({ kind, rows });
    if (st.delay) await sleep(st.delay);
    const f = st.fail[kind];
    if (f && sent >= (f.after || 0)) throw refuse(f.status, f.detail);
    if (!Array.isArray(rows) || rows.length < 1 || rows.length > 1000) throw refuse(400, 'rows: List should have between 1 and 1000 items');
    rows.forEach((row, i) => {
      for (const k of Object.keys(row)) if (!ALLOWED[kind].includes(k)) throw refuse(400, `rows.${i}.${k}: Extra inputs are not permitted`);
      if (!['apple_health', 'import'].includes(row.source || 'import')) throw refuse(400, `rows.${i}.source: Input should be 'apple_health' or 'import'`);
    });
    const known = new Set(st[kind].map((r) => r.source_key).filter(Boolean));
    const perDay = new Map();
    for (const r of st[kind]) perDay.set(r.date, (perDay.get(r.date) || 0) + 1);
    const fresh = [];
    rows.forEach((row, i) => {
      if (known.has(row.source_key)) return;
      if ((perDay.get(row.date) || 0) >= MAX[kind]) throw refuse(400, `rows.${i}: too many ${many} for one day (max ${MAX[kind]})`);
      known.add(row.source_key);
      perDay.set(row.date, (perDay.get(row.date) || 0) + 1);
      fresh.push(row);
    });
    for (const row of fresh) st[kind].push({ id: st[kind].length + 1, ...row });
    return { added: fresh.length, skipped: rows.length - fresh.length };
  };
  const list = (kind, key) => async (start, end) => {
    st.lists.push([kind, start, end]);
    if (listFails) throw refuse(500, 'list failed');
    if (daysBetween(start, end) >= 366) throw refuse(400, 'range too large (max 366 days)');
    return { [key]: st[kind].filter((r) => r.date >= start && r.date <= end).map(({ source_key, ...r }) => r) };
  };
  return {
    st,
    api: { importWeights: post('weights', 'weights'), importBloodPressures: post('readings', 'blood pressure readings'),
      bodyWeights: list('weights', 'weights'), bloodPressures: list('readings', 'readings') },
  };
}

let be = backend();
const log = { toasts: [], shown: [], opened: [], network: [] };
const state = { view: 'trends', dayLoadedFor: '2026-10-22', trends: { days: [] }, summary: { ok: true } };
const KH = {
  h, $, clear, state,
  api: new Proxy({}, { get: (_, name) => be.api[name] }),
  toast: (message, type = '') => log.toasts.push([message, type]),
  router: { show: (view) => log.shown.push(view) },
  sheets: { setup: () => {}, open: (d, trigger, focusEl) => { d.open = true; log.opened.push(focusEl ? focusEl.attrs.id : null); } },
  util: { todayStr: () => TODAY, addDays, parseDate },
};
const trap = (name) => (...args) => { log.network.push([name, String(args[0])]); throw new Error(`${name} must not be called`); };
const win = { KH, TextEncoder, TextDecoder, crypto: globalThis.crypto, ReadableStream, TransformStream, DecompressionStream, DOMException };
const context = vm.createContext({
  window: win, console, TextDecoderStream, AbortController, ReadableStream,
  fetch: trap('fetch'), XMLHttpRequest: trap('XMLHttpRequest'), WebSocket: trap('WebSocket'), navigator: { sendBeacon: trap('sendBeacon') },
});
for (const file of [['js', 'engine', 'rules.js'], ['js', 'engine', 'apple_health.js'], ['js', 'engine', 'zip.js'], ['js', 'engine', 'body.js'], ['js', 'views', 'body_import.js']]) {
  vm.runInContext(read(...file), context, { filename: file.join('/') });
}
const BI = win.KH.bodyImport;

// ---- generated export.xml text and fake files
const HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE HealthData [\n<!ENTITY lol "ha">\n]>\n<HealthData locale="en_US">\n';
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const weightRec = (date, time, value, unit, source) => `<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="${esc(source)}" unit="${unit}" startDate="${date} ${time}:00 -0400" value="${value}"/>\n`;
const half = (type, date, time, value, source, tail = '/>') => `<Record type="HKQuantityTypeIdentifierBloodPressure${type}" sourceName="${esc(source)}" unit="mmHg" startDate="${date} ${time}:00 -0400" value="${value}"${tail}\n`;
const pair = (date, time, sys, dia, source) => half('Diastolic', date, time, dia, source) + half('Systolic', date, time, sys, source);
const exportXml = (...parts) => HEAD + parts.join('') + '</HealthData>\n';
const WATCH = 'Sam\u2019s Apple Watch';
const HOSTILE = '<img src=x onerror=alert(1)> Scale';
const fileOf = (name, xml, { chunk = 2048, delay = 0, type = 'text/xml' } = {}) => {
  const bytes = Buffer.from(xml, 'utf8');
  const file = { name, size: bytes.length, type, cancelled: 0, pulls: 0 };
  file.stream = () => {
    let at = 0;
    return new ReadableStream({
      async pull(controller) {
        file.pulls += 1;
        if (delay) await sleep(delay);
        if (at >= bytes.length) { controller.close(); return; }
        controller.enqueue(new Uint8Array(bytes.subarray(at, at + chunk)));
        at += chunk;
      },
      cancel() { file.cancelled += 1; },
    });
  };
  return file;
};

// the entries of the Health app's export.zip around an export.xml: the other files it holds, an encrypted one among them, and the macOS extras
const healthEntries = (xml, more = []) => [
  { name: 'apple_health_export/', data: '', method: 'store' },
  { name: 'apple_health_export/export.xml', data: xml },
  { name: 'apple_health_export/export_cda.xml', data: '<ClinicalDocument/>' },
  { name: 'apple_health_export/clinical-records/Observation-1.json', data: '{"resourceType": "Observation"}' },
  { name: 'apple_health_export/workout-routes/route_1.gpx', data: 'not readable', flags: 1, method: 'store' },
  { name: '__MACOSX/apple_health_export/._export.xml', data: 'AppleDouble', method: 'store' },
  ...more,
];

const MAIN = exportXml(
  weightRec('2026-10-20', '07:30', '70.2', 'kg', 'Withings Body+'), weightRec('2026-10-15', '07:30', '154.3', 'lb', 'Withings Body+'),
  weightRec('2026-10-01', '21:00', '69.9', 'kg', HOSTILE), weightRec('2026-03-10', '07:30', '71.0', 'kg', 'Withings Body+'),
  weightRec('2026-01-05', '07:30', '72.5', 'kg', 'Withings Body+'), weightRec('2026-10-12', '12:00', '500', 'kg', 'Health'),
  weightRec('2026-10-11', '12:00', '70000', 'g', 'Health'),
  pair('2026-10-20', '08:05', 122, 78, 'Omron Connect'), pair('2026-10-18', '20:15', 131, 84, 'Omron Connect'), pair('2026-02-01', '08:05', 125, 80, 'Omron Connect'),
  pair('2026-10-19', '09:00', 118, 76, WATCH), pair('2026-02-02', '09:00', 117, 75, WATCH),
  half('Systolic', '2026-10-17', '10:00', 119, 'Omron Connect'), pair('2026-10-16', '10:30', 400, 80, 'Omron Connect'),
  '<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Health" unit="count/min" startDate="2026-10-20 07:00:00 -0400" value="61"/>\n',
  '<Record type="HKQuantityTypeIdentifierBloodGlucose" sourceName="Health" unit="mg/dL" startDate="2026-10-20 07:00:00 -0400" value="104"/>\n',
  '<Record type="HKQuantityTypeIdentifierInsulinDelivery" sourceName="Health" unit="IU" startDate="2026-10-20 07:00:00 -0400" value="3"/>\n',
);

// ---- helpers for the sheet
const labelOf = (id) => find(reviewEl, (e) => e.tag === 'label' && e.attrs.for === id)[0];
const boxes = () => find(reviewEl, (e) => e.tag === 'input' && e.attrs.type === 'checkbox');
const radios = () => find(reviewEl, (e) => e.tag === 'input' && e.attrs.type === 'radio');
const snapshot = () => ({
  headline: page.byId['body-import-summary'] ? text(page.byId['body-import-summary']) : null,
  range: page.byId['body-import-range'] ? text(page.byId['body-import-range']) : null,
  sources: page.byId['body-import-sources'] ? text(page.byId['body-import-sources']) : null,
  leftOut: page.byId['body-import-left-out'] ? find(page.byId['body-import-left-out'], (e) => e.tag === 'li').map(text) : [],
  periods: radios().map((r) => ({ id: r.attrs.id, checked: r.checked, label: text(labelOf(r.attrs.id)) })),
  watch: page.byId['body-import-watch'] ? { text: text(page.byId['body-import-watch']), ticked: boxes().map((b) => b.checked), labels: boxes().map((b) => text(labelOf(b.attrs.id))) } : null,
  days: page.byId['body-import-days'] ? { text: text(page.byId['body-import-days']), hidden: page.byId['body-import-days'].hidden } : null,
  go: { text: text(goBtn), disabled: goBtn.disabled, hidden: goBtn.hidden }, cancel: text(cancelBtn), status: text(statusEl),
  problem: problemEl.hidden ? null : problemEl.children.map(text), reviewHidden: reviewEl.hidden, pickHidden: pickEl.hidden,
  focused: page.focused,
});
const pick = async (file) => { input.files = [file]; input.value = `C:\\fakepath\\${file.name}`; await input.fire('change'); };
const openFresh = () => {
  be.st.calls.length = 0; be.st.lists.length = 0; log.toasts.length = 0; log.shown.length = 0;
  state.dayLoadedFor = TODAY; state.trends = { days: [] }; state.summary = { ok: true };
  BI.open();
};
const fresh = (b) => { be = b; };
const resultText = () => (page.byId['body-import-result'] ? text(page.byId['body-import-result']) : null);
const posted = () => be.st.calls.map((c) => ({ kind: c.kind, n: c.rows.length }));
const allTags = () => { const tags = new Set(); const walk = (e) => { if (e.nodeType === 1) { tags.add(e.tag); e.children.forEach(walk); } }; walk(reviewEl); walk(problemEl); return [...tags].sort(); };

const out = {};

// 1. Opening the sheet, and the files it refuses.
{
  openFresh();
  out.opened = { open: dlg.open, focus: log.opened, cancel: text(cancelBtn), pickHidden: pickEl.hidden, reviewHidden: reviewEl.hidden, goHidden: goBtn.hidden };
  await pick(zipFileOf('export.zip', Buffer.from('PK\x03\x04 this only starts like a zip')));
  out.zip = { problem: snapshot().problem, input: input.value, reviewHidden: reviewEl.hidden };
  await pick(fileOf('export_cda.xml', '<ClinicalDocument/>'));
  out.cda = { problem: snapshot().problem, input: input.value };
  await pick(fileOf('export.xml', ''));
  out.empty = { problem: snapshot().problem, input: input.value };
  out.noWrites = { calls: be.st.calls.length, lists: be.st.lists.length };
  dlg.close();
}

// 2. The review of a mixed file: counts, left out, range, period, sources, the watch readings unticked.
{
  fresh(backend());
  openFresh();
  const f = fileOf('export.xml', MAIN);
  await pick(f);
  out.review = { ...snapshot(), tags: allTags(), calls: be.st.calls.length, lists: be.st.lists.length, networkTrapped: log.network.length };
  out.review.hostileInDom = find(reviewEl, (e) => e.tag === 'img').length;
  out.review.hostileText = text(reviewEl).includes('<img src=x onerror=alert(1)> Scale');
  out.review.noNullText = !/\bnull\b|\bundefined\b|\bNaN\b/.test(text(reviewEl));

  // ticking the watch source and choosing everything changes the counts and the button
  const watchBox = boxes()[0];
  watchBox.checked = true; await watchBox.fire('change');
  const afterTick = snapshot();
  const all = radios().find((r) => r.attrs.value === 'all');
  all.checked = true; await all.fire('change');
  const afterAll = snapshot();
  watchBox.checked = false; await watchBox.fire('change');
  const afterUntick = snapshot();
  out.choices = { afterTick: { periods: afterTick.periods.map((p) => p.label), go: afterTick.go.text, watch: afterTick.watch.labels },
    afterAll: { go: afterAll.go.text, watch: afterAll.watch.labels }, afterUntick: { go: afterUntick.go.text } };
  const recent = radios().find((r) => r.attrs.value === 'recent');
  recent.checked = true; await recent.fire('change');
  out.choices.backToRecent = snapshot().go.text;
  // Cancel at the review: the file is forgotten and nothing was sent
  await cancelBtn.fire('click');
  out.reviewCancelled = { ...snapshot(), input: input.value, calls: be.st.calls.length, focused: page.focused };
  dlg.close();
}

// 3. Import the default period: what goes up, and what happens to the page.
{
  fresh(backend());
  openFresh();
  await pick(fileOf('export.xml', MAIN));
  const before = { ...state };
  await goBtn.fire('click');
  out.imported = {
    posted: posted(), rowKeys: be.st.calls.map((c) => [...new Set(c.rows.flatMap((r) => Object.keys(r)))].sort()),
    sources: [...new Set(be.st.calls.flatMap((c) => c.rows.map((r) => r.source)))],
    weights: be.st.calls[0].rows.map((r) => [r.date, r.time, r.kg, r.context]),
    readings: be.st.calls[1].rows.map((r) => [r.date, r.time, r.systolic, r.diastolic, r.context]),
    keysAreHex: be.st.calls.flatMap((c) => c.rows).every((r) => /^[0-9a-f]{32}$/.test(r.source_key)),
    uploadText: JSON.stringify(be.st.calls), result: resultText(), focused: page.focused, status: statusEl.textContent,
    snapshot: snapshot(), toasts: [...log.toasts], shown: [...log.shown], cleared: [state.dayLoadedFor, state.trends, state.summary], was: [before.dayLoadedFor !== null, before.trends !== null],
    lists: [...be.st.lists],
  };
  // the same file again: nothing is added, all are "already here"
  dlg.close();
  openFresh();
  await pick(fileOf('export.xml', MAIN));
  await goBtn.fire('click');
  out.again = { result: resultText(), shown: [...log.shown], stored: [be.st.weights.length, be.st.readings.length] };
  dlg.close();
}

// 4. Everything with the watch ticked
{
  fresh(backend());
  openFresh();
  await pick(fileOf('export.xml', MAIN));
  boxes()[0].checked = true; await boxes()[0].fire('change');
  const all = radios().find((r) => r.attrs.value === 'all');
  all.checked = true; await all.fire('change');
  await goBtn.fire('click');
  out.everything = { result: resultText(), weights: be.st.weights.length, readings: be.st.readings.map((r) => [r.date, r.systolic, r.diastolic]).sort() };
  dlg.close();
}

// 5. Days with more rows than a day can hold
const crowdedXml = () => {
  let x = weightRec('2026-10-01', '07:30', '70.5', 'kg', 'Withings Body+');
  for (let i = 0; i < 25; i += 1) x += weightRec('2026-10-10', `06:${String(i).padStart(2, '0')}`, (70 + i / 100).toFixed(2), 'kg', 'Withings Body+');
  for (let i = 0; i < 35; i += 1) x += pair('2026-10-12', `${String(8 + Math.floor(i / 6)).padStart(2, '0')}:${String((i % 6) * 10).padStart(2, '0')}`, 120 + (i % 7), 80 + (i % 5), 'Omron Connect');
  return exportXml(x);
};
{
  fresh(backend());
  openFresh();
  await pick(fileOf('export.xml', crowdedXml()));
  const review = snapshot();
  await goBtn.fire('click');
  const day10 = be.st.weights.filter((r) => r.date === '2026-10-10').map((r) => r.time).sort();
  out.crowded = {
    review: { headline: review.headline, days: review.days, go: review.go.text },
    result: resultText(), left: page.byId['body-import-left'] ? text(page.byId['body-import-left']) : null,
    weightsOnDay: day10.length, firstTimes: [day10[0], day10[day10.length - 1]], readingsOnDay: be.st.readings.filter((r) => r.date === '2026-10-12').length,
    posted: posted(), lists: [...be.st.lists],
  };
  // the same file again: the 20 stored ones are "already here"; only the surplus is "left out"
  dlg.close();
  openFresh();
  await pick(fileOf('export.xml', crowdedXml()));
  await goBtn.fire('click');
  out.crowdedAgain = { result: resultText(), left: page.byId['body-import-left'] ? text(page.byId['body-import-left']) : null, weightsOnDay: be.st.weights.filter((r) => r.date === '2026-10-10').length };
  dlg.close();
}
{
  // three weights typed in by hand on that day: room for 17 of the file's
  const manual = [0, 1, 2].map((i) => ({ date: '2026-10-10', time: `05:0${i}`, kg: 80 + i, context: 'other' }));
  fresh(backend({ weights: manual }));
  openFresh();
  await pick(fileOf('export.xml', crowdedXml()));
  await goBtn.fire('click');
  const day10 = be.st.weights.filter((r) => r.date === '2026-10-10' && r.source === 'apple_health').map((r) => r.time).sort();
  out.crowdedManual = { result: resultText(), left: text(page.byId['body-import-left']), imported: day10.length, last: day10[day10.length - 1], total: be.st.weights.filter((r) => r.date === '2026-10-10').length };
  dlg.close();
}
{
  // the rows already here cannot be read: only the limit is used, and a day the server finds fuller than that refuses the request, which stops the import
  const manual = [0, 1, 2].map((i) => ({ date: '2026-10-10', time: `05:0${i}`, kg: 80 + i, context: 'other' }));
  fresh(backend({ weights: manual, listFails: true }));
  openFresh();
  await pick(fileOf('export.xml', crowdedXml()));
  await goBtn.fire('click');
  out.crowdedUnknown = { problem: snapshot().problem, posted: posted(), stored: be.st.weights.length, go: snapshot().go, lists: be.st.lists.length };
  dlg.close();
}

// 6. A refusal in the middle: the server's words, what was already added, nothing lost, Import again carries on
{
  fresh(backend());
  be.st.fail.readings = { status: 400, detail: 'rows.1: too many blood pressure readings for one day (max 30)' };
  openFresh();
  await pick(fileOf('export.xml', MAIN));
  await goBtn.fire('click');
  const first = snapshot();
  out.refused = { problem: first.problem, go: first.go, status: first.status, pickHidden: first.pickHidden, reviewHidden: first.reviewHidden, cancel: first.cancel,
    weightsStored: be.st.weights.length, readingsStored: be.st.readings.length, shown: [...log.shown], toasts: [...log.toasts] };
  be.st.fail = {};
  await goBtn.fire('click');
  out.refusedThenAgain = { result: resultText(), problem: snapshot().problem, weightsStored: be.st.weights.length, readingsStored: be.st.readings.length, shown: [...log.shown] };
  dlg.close();
}
{
  // 2,500 weights (three requests); the second is refused: 1,000 were added, and the words name the row's day
  let x = '';
  for (let i = 0; i < 2500; i += 1) x += weightRec(addDays('2026-10-01', -Math.floor(i / 10)), `0${i % 10}:15`, (60 + (i % 100) / 10).toFixed(1), 'kg', 'Withings Body+');
  fresh(backend());
  be.st.fail.weights = { status: 429, detail: 'Too many imports of weights and readings. Try again later.', after: 1 };
  openFresh();
  await pick(fileOf('export.xml', exportXml(x)));
  const all = radios().find((r) => r.attrs.value === 'all');
  all.checked = true; await all.fire('change');
  const review = snapshot();
  await goBtn.fire('click');
  out.manyRefused = { review: review.headline, go: review.go.text, problem: snapshot().problem, posted: posted(), stored: be.st.weights.length };
  // a row of a batch named by the server gets its day
  be.st.fail = { weights: { status: 400, detail: 'rows.3.kg: Input should be greater than or equal to 20', after: 0 } };
  await goBtn.fire('click');
  out.rowNamed = { problem: snapshot().problem, stored: be.st.weights.length };
  be.st.fail = {};
  await goBtn.fire('click');
  out.manyDone = { result: resultText(), stored: be.st.weights.length, posted: posted().length };
  dlg.close();
}
{
  // a gateway error while sending: the same stop, in the server's own words
  fresh(backend());
  be.st.fail.weights = { status: 502, detail: '502 Bad Gateway' };
  openFresh();
  await pick(fileOf('export.xml', MAIN));
  await goBtn.fire('click');
  out.gateway = { problem: snapshot().problem, stored: be.st.weights.length, go: snapshot().go };
  dlg.close();
}
{
  // signed out (a handled 401): the sheet closes so the sign-in screen is visible
  fresh(backend());
  be.api.importWeights = async () => { throw Object.assign(new Error('Not signed in'), { status: 401, detail: 'Not signed in', handled: true }); };
  openFresh();
  await pick(fileOf('export.xml', MAIN));
  await goBtn.fire('click');
  out.signedOut = { open: dlg.open, phase: snapshot().pickHidden, problem: snapshot().problem };
}

// 7. Cancel while the file is being read: the stream is cancelled, nothing is sent
{
  fresh(backend());
  openFresh();
  const slow = fileOf('export.xml', exportXml(weightRec('2026-10-20', '07:30', '70.2', 'kg', 'Health').repeat(400)), { chunk: 512, delay: 5 });
  input.files = [slow];
  const reading = input.fire('change');
  await sleep(60);
  const during = snapshot();
  await cancelBtn.fire('click');
  await reading;
  await sleep(40);
  out.cancelled = { during: { status: during.status, cancel: during.cancel, pickHidden: during.pickHidden, reviewHidden: during.reviewHidden, go: during.go.hidden },
    after: snapshot(), streamCancelled: slow.cancelled, pulls: slow.pulls, totalChunks: Math.ceil(slow.size / 512), input: input.value, calls: be.st.calls.length, focused: page.focused };
  // closing the sheet while reading does the same
  const slow2 = fileOf('export.xml', exportXml(weightRec('2026-10-20', '07:30', '70.2', 'kg', 'Health').repeat(400)), { chunk: 512, delay: 5 });
  openFresh();
  input.files = [slow2];
  const reading2 = input.fire('change');
  await sleep(60);
  dlg.close();
  await reading2;
  await sleep(40);
  out.closedWhileReading = { streamCancelled: slow2.cancelled, reviewHidden: reviewEl.hidden, status: statusEl.textContent, calls: be.st.calls.length };
}

// 8. Stop in the middle of an import, and closing the sheet in the middle
{
  let x = '';
  for (let i = 0; i < 2500; i += 1) x += weightRec(addDays('2026-10-01', -Math.floor(i / 10)), `0${i % 10}:15`, (60 + (i % 100) / 10).toFixed(1), 'kg', 'Withings Body+');
  fresh(backend({ delay: 30 }));
  openFresh();
  await pick(fileOf('export.xml', exportXml(x)));
  const all = radios().find((r) => r.attrs.value === 'all');
  all.checked = true; await all.fire('change');
  const running = goBtn.fire('click');
  await sleep(10);
  const during = snapshot();
  const controlsDisabled = [...radios(), ...boxes()].length > 0 && [...radios(), ...boxes()].every((c) => c.disabled);
  await cancelBtn.fire('click'); // "Stop"
  await running;
  const after = snapshot();
  out.stopped = { during: { cancel: during.cancel, go: during.go, status: during.status, controlsDisabled },
    after: { status: after.status, go: after.go, cancel: after.cancel, problem: after.problem }, posted: posted(), stored: be.st.weights.length, shown: [...log.shown] };
  be.st.calls.length = 0;
  await goBtn.fire('click');
  out.stoppedThenDone = { result: resultText(), stored: be.st.weights.length };
  dlg.close();

  fresh(backend({ delay: 30 }));
  openFresh();
  await pick(fileOf('export.xml', exportXml(x)));
  const all2 = radios().find((r) => r.attrs.value === 'all');
  all2.checked = true; await all2.fire('change');
  const running2 = goBtn.fire('click');
  await sleep(10);
  dlg.close(); // closes the sheet while the first request is in flight
  await running2;
  await sleep(50);
  out.closedWhileImporting = { posted: posted(), stored: be.st.weights.length, toasts: [...log.toasts], reviewCleared: reviewEl.children.length, shown: [...log.shown], open: dlg.open };
}

// 9. A file with nothing the app keeps, a file that is all recent, and one with a single day
{
  fresh(backend());
  openFresh();
  await pick(fileOf('export.xml', exportXml('<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Health" unit="count/min" startDate="2026-10-20 07:00:00 -0400" value="61"/>\n')));
  const none = snapshot();
  out.nothing = { headline: none.headline, go: none.go, cancel: none.cancel, periods: none.periods.length, tags: allTags(), status: none.status };
  await cancelBtn.fire('click');
  out.nothingCancel = { pickHidden: snapshot().pickHidden, reviewHidden: reviewEl.hidden };
  await pick(fileOf('export.xml', exportXml(weightRec('2026-10-20', '07:30', '70.2', 'kg', 'Health'), pair('2026-10-20', '08:00', 120, 80, 'Omron Connect'))));
  const recent = snapshot();
  out.allRecent = { headline: recent.headline, range: recent.range, periods: recent.periods.length, hint: text(page.byId['body-import-period']), go: recent.go.text, watch: recent.watch };
  dlg.close();
  openFresh();
  await pick(fileOf('export.xml', exportXml(weightRec('2026-10-20', '07:30', '70.2', 'kg', 'Health'), weightRec('2026-10-20', '07:30', '154', 'lb', 'Health'),
    weightRec('2026-10-20', '08:30', '154', 'lb', 'Health'))));
  out.sameDay = { range: snapshot().range };
  dlg.close();
  // only watch readings in the file: nothing to import until a source is ticked
  openFresh();
  await pick(fileOf('export.xml', exportXml(pair('2026-10-20', '09:00', 118, 76, WATCH), pair('2026-04-20', '09:00', 117, 75, 'Apple Watch of Sam'))));
  const w = snapshot();
  out.onlyWatch = { go: w.go, watch: w.watch, headline: w.headline };
  const second = boxes()[1]; // Sam's Apple Watch: the one with a reading in the last 3 months (boxes are in name order)
  second.checked = true; await second.fire('change');
  out.onlyWatchTicked = { go: snapshot().go };
  dlg.close();
  // a source named with markup that also has "Watch" in it: its name is text in the watch list too
  openFresh();
  await pick(fileOf('export.xml', exportXml(pair('2026-10-20', '09:00', 118, 76, '<script>alert(1)</script> Watch'))));
  out.hostileWatch = { labels: snapshot().watch.labels, tags: allTags(), scripts: find(reviewEl, (e) => e.tag === 'script').length };
  dlg.close();
}

// 10. Many days to ask about: the lists are asked in windows of 366 days, only where the file has rows
{
  fresh(backend());
  openFresh();
  await pick(fileOf('export.xml', exportXml(
    weightRec('2026-10-20', '07:30', '70.2', 'kg', 'Health'), weightRec('2024-05-01', '07:30', '71.2', 'kg', 'Health'),
    weightRec('2019-02-03', '07:30', '72.2', 'kg', 'Health'), pair('2024-05-02', '08:00', 120, 80, 'Omron Connect'))));
  const all = radios().find((r) => r.attrs.value === 'all');
  all.checked = true; await all.fire('change');
  await goBtn.fire('click');
  out.windows = { lists: [...be.st.lists], result: resultText() };
  dlg.close();
}

// 11. The module, trimDays on its own
{
  const same = (stored, row) => stored.time === row.time;
  const day = (date, n, from = 0) => Array.from({ length: n }, (_, i) => ({ date, time: `06:${String(from + i).padStart(2, '0')}`, id: `${date}-${from + i}` }));
  const t = (rows, limit, stored) => { const r = BI.trimDays(rows, limit, stored, same); return { keep: r.keep.map((x) => x.id), leftOut: r.leftOut, days: [...r.days] }; };
  const rows = [...day('2026-10-01', 3), ...day('2026-10-02', 25), ...day('2026-10-03', 2)];
  out.trim = {
    fits: t(day('2026-10-01', 20), 20, null).leftOut,
    over: t(day('2026-10-02', 25), 20, null),
    mixed: t(rows, 20, null).days,
    keepOrder: t(rows, 20, null).keep.slice(0, 4),
    sameArrayWhenNothingDropped: BI.trimDays(day('2026-10-01', 5), 20, null, same).keep.length,
    withManual: t(day('2026-10-02', 25), 20, [{ date: '2026-10-02', time: '05:00', source: 'manual' }, { date: '2026-10-02', time: '05:01', source: 'manual' }]),
    withImported: t(day('2026-10-02', 25), 20, day('2026-10-02', 20).map((r) => ({ ...r, source: 'apple_health' }))),
    importedAndManual: t(day('2026-10-02', 25), 20, [...day('2026-10-02', 10).map((r) => ({ ...r, source: 'apple_health' })), ...Array.from({ length: 5 }, (_, i) => ({ date: '2026-10-02', time: `05:0${i}`, source: 'manual' }))]),
    fullDay: t(day('2026-10-02', 3), 20, Array.from({ length: 20 }, (_, i) => ({ date: '2026-10-02', time: `04:${String(i).padStart(2, '0')}`, source: 'manual' }))),
    editedImportedRowIsNotMatched: t(day('2026-10-02', 22), 20, day('2026-10-02', 20).map((r) => ({ ...r, source: 'manual' }))),
    other_day_rows: t(day('2026-10-02', 25), 20, [{ date: '2026-10-05', time: '06:00', source: 'manual' }]),
    empty: t([], 20, null),
  };
}

// 12. An export.zip: the same review and the same rows as the export.xml inside it, picked by itself
{
  fresh(backend());
  openFresh();
  const zipped = zipFileOf('export.zip', healthEntries(MAIN));
  await pick(zipped);
  out.zipReview = { ...snapshot(), tags: allTags(), calls: be.st.calls.length, lists: be.st.lists.length, networkTrapped: log.network.length };
  out.zipRead = { opened: zipped.opened, over: zipped.over, slices: zipped.slices.length, size: zipped.size };
  dlg.close();

  fresh(backend());
  openFresh();
  await pick(zipFileOf('Health export.ZIP', healthEntries(MAIN, [{ name: 'apple_health_export/clinical-records/Observation-2.json', data: '{}' }])));
  await goBtn.fire('click');
  out.zipImported = {
    posted: posted(), sources: [...new Set(be.st.calls.flatMap((c) => c.rows.map((r) => r.source)))],
    weights: be.st.calls[0].rows.map((r) => [r.date, r.time, r.kg, r.context]), readings: be.st.calls[1].rows.map((r) => [r.date, r.time, r.systolic, r.diastolic, r.context]),
    keys: be.st.calls.map((c) => [...new Set(c.rows.flatMap((r) => Object.keys(r)))].sort()), result: resultText(), shown: [...log.shown],
  };
  dlg.close();

  // by type alone (no .zip in the name), and a re-zipped folder (the file one level down, a __MACOSX copy beside it)
  fresh(backend());
  openFresh();
  await pick(zipFileOf('download', [{ name: 'Health Data/export.xml', data: MAIN }, { name: '__MACOSX/Health Data/._export.xml', data: 'x', method: 'store' }], { type: 'application/zip' }));
  out.zipByType = { headline: snapshot().headline, problem: snapshot().problem };
  dlg.close();

  // what is wrong with a .zip, in words, and nothing was sent
  fresh(backend());
  openFresh();
  out.zips = {};
  const wrong = {
    missing: zipFileOf('export.zip', [{ name: 'apple_health_export/export_other.xml', data: '<HealthData/>' }, { name: 'apple_health_export/workout-routes/a.gpx', data: 'x' }]),
    cdaOnly: zipFileOf('export.zip', [{ name: 'apple_health_export/export_cda.xml', data: '<ClinicalDocument/>' }]),
    twoExports: zipFileOf('export.zip', [{ name: 'a/export.xml', data: MAIN }, { name: 'b/export.xml', data: MAIN }]),
    damaged: zipFileOf('export.zip', [{ name: 'apple_health_export/export.xml', data: MAIN, crcXor: 1 }]),
    encrypted: zipFileOf('export.zip', [{ name: 'apple_health_export/export.xml', data: MAIN, flags: 1 }]),
    cutOff: zipFileOf('export.zip', makeZip(healthEntries(MAIN)).subarray(0, 700)),
    empty: zipFileOf('export.zip', Buffer.alloc(0)),
  };
  for (const [key, file] of Object.entries(wrong)) {
    await pick(file);
    const snap = snapshot();
    out.zips[key] = { problem: snap.problem, input: input.value, pickHidden: snap.pickHidden, reviewHidden: snap.reviewHidden, status: snap.status, cancel: snap.cancel, calls: be.st.calls.length, lists: be.st.lists.length };
  }
  // a browser without DecompressionStream: the old advice, and the archive is not even opened
  delete win.DecompressionStream;
  const untouched = zipFileOf('export.zip', healthEntries(MAIN));
  await pick(untouched);
  out.zips.browser = { problem: snapshot().problem, input: input.value, slices: untouched.slices.length, opened: untouched.opened };
  win.DecompressionStream = DecompressionStream;
  // the sheet works again once the browser can (the same file is chosen again)
  await pick(untouched);
  out.zips.afterwards = { headline: snapshot().headline };
  dlg.close();
}
{
  // Cancel while a .zip is being read: the stream of the file is let go of, nothing is sent, the name is text. Each step waits until
  // the sheet says it is reading (a fixed wait let a fast machine finish the read first).
  const whileReading = async () => {
    for (let waited = 0; waited < 3000 && !String(statusEl.textContent || '').startsWith('Reading'); waited += 5) await sleep(5);
  };
  fresh(backend());
  openFresh();
  let many = '';
  for (let i = 0; i < 3000; i += 1) many += weightRec(addDays('2026-10-01', -Math.floor(i / 10)), `0${i % 10}:15`, (60 + ((i * 7) % 100) / 10).toFixed(1), 'kg', `Scale ${i % 97}`);
  const slow = zipFileOf('<img src=x onerror=alert(1)>.zip', healthEntries(exportXml(many)), { chunk: 512, delay: 4 });
  input.files = [slow];
  input.value = `C:\\fakepath\\${slow.name}`;
  const reading = input.fire('change');
  await whileReading();
  const during = snapshot();
  const imgs = find(statusEl, (e) => e.tag === 'img').length + find(problemEl, (e) => e.tag === 'img').length;
  await cancelBtn.fire('click');
  await reading;
  await sleep(60);
  const after = snapshot();
  out.zipCancelled = {
    during: { status: during.status, cancel: during.cancel, pickHidden: during.pickHidden, reviewHidden: during.reviewHidden, go: during.go.hidden, imgs },
    after: { status: after.status, pickHidden: after.pickHidden, reviewHidden: after.reviewHidden, problem: after.problem, focused: after.focused },
    opened: slow.opened, over: slow.over, size: slow.size, input: input.value, calls: be.st.calls.length, lists: be.st.lists.length,
  };
  // closing the sheet while a .zip is being read does the same
  const slow2 = zipFileOf('export.zip', healthEntries(exportXml(many)), { chunk: 512, delay: 4 });
  openFresh();
  input.files = [slow2];
  const reading2 = input.fire('change');
  await whileReading();
  dlg.close();
  await reading2;
  await sleep(60);
  out.zipClosedWhileReading = { opened: slow2.opened, over: slow2.over, reviewHidden: reviewEl.hidden, status: statusEl.textContent, calls: be.st.calls.length };
}

out.network = log.network;
console.log(JSON.stringify(out));
