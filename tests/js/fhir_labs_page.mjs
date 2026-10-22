#!/usr/bin/env node
// Runs app/static/js/views/lab_fhir.js against a tiny fake page and fake files, together with the real js/engine/rules.js,
// js/engine/kidney_function.js and js/engine/fhir_labs.js, and prints what happened as JSON, so pytest (tests/test_fhir_labs_ui.py)
// can check the behaviour without a browser: which files are read (a file over 1 MB never is), what the person is shown, that new
// results start ticked and saved ones do not, what is handed to the shared save (POST /api/labs/import) and that it holds no file
// name or identity, that too many files are refused before any is read, that text from a file is drawn as text, and that nothing
// calls the network. The helpers the file takes from KH (h, $, clear, util, labs, views.labs) are stand-ins with the contract of js/core.js.
// The export.zip picks (docs/dev/research/11-reading-a-zip-in-the-browser.md section 4.5) run the real js/engine/zip.js on archives made in memory
// by tests/js/zip_writer.mjs: the same table as the same files picked one by one, the same caps, a damaged entry counted as a file that could
// not be read, a .zip with no clinical-records folder, and a browser without DecompressionStream.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { makeZip, zipFile } from './zip_writer.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (...p) => readFileSync(join(ROOT, 'app', 'static', ...p), 'utf8');

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) {
    this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this._text = '';
    this.disabled = false; this.checked = false; this.hidden = false; this.value = ''; this.files = null;
  }
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
const $ = (sel) => {
  const id = sel.replace(/^#/, '');
  if (page.byId[id]) return page.byId[id];
  return (page.stubs[sel] ||= new El('div'));
};
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();
const find = (el, pred, out = []) => { if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach((c) => find(c, pred, out)); } return out; };

const TODAY = '2026-10-15';
const log = { read: [], saved: [], toasts: [], network: [] };
let existing = [];
const input = new El('input'); page.byId['lab-fhir-file'] = input;
const box = new El('div'); page.byId['lab-fhir-preview'] = box;
const KH = {
  h, $, clear,
  util: { todayStr: () => TODAY },
  labs: { load: async () => ({ labs: existing }) },
  toastError: (e) => log.toasts.push(String(e && e.message || e)),
  views: { labs: {
    fmtDay: (iso) => `day ${iso}`,
    saveImported: async (kept, into, source, onSaved) => {
      log.saved.push({ kept, source });
      onSaved();
      clear(into).append(h('p', {}, `Saved ${kept.length}`));
      return { saved: kept.length };
    },
  } },
};
// A network call of any kind would land here; the file must make none.
const trap = (name) => (...args) => { log.network.push([name, String(args[0])]); throw new Error(`${name} must not be called`); };
const win = { KH, TextDecoder, ReadableStream, TransformStream, DecompressionStream, DOMException };
const context = vm.createContext({ window: win, console, fetch: trap('fetch'), XMLHttpRequest: trap('XMLHttpRequest'), WebSocket: trap('WebSocket'), navigator: { sendBeacon: trap('sendBeacon') } });
for (const file of [['js', 'engine', 'rules.js'], ['js', 'engine', 'kidney_function.js'], ['js', 'engine', 'fhir_labs.js'], ['js', 'engine', 'zip.js'], ['js', 'views', 'lab_fhir.js']]) {
  vm.runInContext(read(...file), context, { filename: file.join('/') });
}
const LF = context.window.KH.labFhir;
const FL = context.window.KH.fhirLabs;
const out = {};

// ---- fake files ------------------------------------------------------------------------------------------------------------------
const SUBJECT = { reference: 'Patient/example-0001', display: 'Sam Example' };
const obs = (code, value, unit, date, extra = {}) => ({
  resourceType: 'Observation', id: 'example', status: 'final', subject: SUBJECT,
  code: { coding: [{ system: 'http://loinc.org', code }] }, effectiveDateTime: date, valueQuantity: { value, unit, system: 'http://unitsofmeasure.org', code: unit }, ...extra,
});
const fileOf = (name, content, size = null) => ({
  name, size: size == null ? Buffer.byteLength(typeof content === 'string' ? content : JSON.stringify(content)) : size,
  text: async () => { log.read.push(name); if (content instanceof Error) throw content; return typeof content === 'string' ? content : JSON.stringify(content); },
});
const pickFiles = async (files) => { input.files = files; input.value = 'C:\\fakepath\\x'; log.read = []; await input.fire('change'); };
const checkboxes = () => find(box, (e) => e.tag === 'input' && e.attrs.type === 'checkbox');
const buttons = () => find(box, (e) => e.tag === 'button');
const byText = (label) => buttons().find((b) => text(b).startsWith(label));
const summary = () => { const s = find(box, (e) => e.attrs.class === 'lab-import-summary')[0]; return s ? text(s) : null; };

// 1. A mixed pick: labs, a Patient, a Bundle, text that is not JSON, a file over 1 MB (never read) and one that cannot be read.
{
  await pickFiles([
    fileOf('Observation-k.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07')),
    fileOf('Observation-cr.json', obs('14682-9', 150, 'umol/L', '2026-10-07')),
    fileOf('Patient-1.json', { resourceType: 'Patient', id: 'example', name: [{ family: 'Example' }] }),
    fileOf('Bundle-1.json', { resourceType: 'Bundle', type: 'collection', entry: [{ resource: obs('2160-0', 1.7, 'mg/dL', '2026-09-01') }, { resource: { resourceType: 'Condition', id: 'c' } }] }),
    fileOf('notes.json', 'not json at all'),
    fileOf('huge.json', obs('2823-3', 4.4, 'mmol/L', '2026-10-01'), 5 * 1024 * 1024),
    fileOf('locked.json', new Error('NotReadableError')),
    fileOf('Observation-mgdl.json', obs('2823-3', 18, 'mg/dL', '2026-10-02')),
  ]);
  const boxes = checkboxes();
  out.mixed = {
    read: log.read, summary: summary(), ticked: boxes.map((b) => b.checked),
    rows: find(box, (e) => e.attrs.class === 'lab-row-value').map(text),
    days: find(box, (e) => e.attrs.class === 'lab-row-date').map(text),
    why: find(box, (e) => e.attrs.class === 'lab-import-why').map(text),
    save: { text: text(byText('Save')), disabled: byText('Save').disabled },
    classes: find(box, (e) => e.tag === 'ul').map((e) => e.attrs.class), focused: page.focused,
    hint: find(box, (e) => e.attrs.class === 'hint').map(text),
  };
  // Untick the creatinine; the count follows.
  boxes[1].checked = false; await boxes[1].fire('change');
  out.unticked = { save: text(byText('Save')) };
  await byText('Save').fire('click');
  out.saved = { saved: log.saved, input: input.value, shown: text(box) };
  log.saved = [];
}

// 2. Results the person already has start unticked and are marked; the new one is ticked.
{
  existing = [{ analyte: 'potassium', taken_on: '2026-10-07', value: 5.4 }, { analyte: 'nonsense', taken_on: '2026-10-07', value: 1 }];
  await pickFiles([fileOf('a.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07')), fileOf('b.json', obs('2823-3', 4.9, 'mmol/L', '2026-10-08'))]);
  out.alreadySaved = { summary: summary(), ticked: checkboxes().map((b) => b.checked), tags: find(box, (e) => e.attrs.class === 'lab-import-saved').map(text), save: text(byText('Save')) };
  existing = [];
}

// 3. Cancel forgets the pick and puts the focus back on the file chooser; nothing was sent.
{
  await pickFiles([fileOf('a.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07'))]);
  await byText('Cancel').fire('click');
  out.cancelled = { box: text(box), input: input.value, focused: page.focused, saved: log.saved.length };
}

// 4. More than 2,000 files are refused before any is read.
{
  const many = Array.from({ length: FL.MAX_FILES + 1 }, (_, i) => fileOf(`o-${i}.json`, '{}'));
  await pickFiles(many);
  out.tooMany = { read: log.read.length, message: text(box), alert: find(box, (e) => e.attrs.role === 'alert').length };
}

// 5. Exactly 2,000 files are read (in order), and a Bundle with more than 1,000 results shows the newest 1,000.
{
  const entries = Array.from({ length: 1005 }, (_, i) => ({ resource: obs('2823-3', 4 + (i % 40) / 10, 'mmol/L', new Date(Date.UTC(2023, 0, 1 + i)).toISOString().slice(0, 10)) }));
  await pickFiles([fileOf('Bundle-big.json', { resourceType: 'Bundle', type: 'collection', entry: entries })]);
  const boxes = checkboxes();
  out.many = { summary: summary(), rows: boxes.length, save: { text: text(byText('Save')), disabled: byText('Save').disabled }, firstDay: text(find(box, (e) => e.attrs.class === 'lab-row-date')[0]) };
  await byText('Cancel').fire('click');
  const two = Array.from({ length: FL.MAX_FILES }, (_, i) => fileOf(`o-${i}.json`, i === 0 ? obs('2823-3', 4.5, 'mmol/L', '2026-10-01') : '{}'));
  await pickFiles(two);
  out.exactly2000 = { read: log.read.length, summary: summary() };
  await byText('Cancel').fire('click');
}

// 6. Text from a file is drawn as text: a hostile unit, name and date make no element.
{
  await pickFiles([
    fileOf('<img src=x onerror=alert(1)>.json', obs('2823-3', 4.4, '<img src=x onerror=alert(1)>', '2026-10-01')),
    fileOf('y.json', obs('2160-0', 1.2, 'mg/dL', '<script>alert(1)</script>')),
  ]);
  const tags = new Set(find(box, () => true).map((e) => e.tag));
  out.hostile = {
    tags: [...tags].sort(), why: find(box, (e) => e.attrs.class === 'lab-import-why').map(text),
    noRealElements: !tags.has('img') && !tags.has('script') && !tags.has('a') && !tags.has('b'),
  };
  await byText('Close').fire('click');
}

// 7. Nothing the app keeps: a hint and Close, no Save.
{
  await pickFiles([fileOf('Patient.json', { resourceType: 'Patient', id: 'x' }), fileOf('Condition.json', { resourceType: 'Condition', id: 'y' })]);
  out.nothing = { summary: summary(), hint: find(box, (e) => e.attrs.class === 'hint warn').map(text), buttons: buttons().map(text), checkboxes: checkboxes().length };
}

// 8. A newer pick wins over an older one that is still being read.
{
  let release;
  const slow = { name: 'slow.json', size: 10, text: () => new Promise((resolve) => { release = () => resolve(JSON.stringify(obs('2823-3', 4.4, 'mmol/L', '2026-10-01'))); }) };
  input.files = [slow]; input.value = 'x';
  const first = input.fire('change');
  await settle();
  input.files = [fileOf('fast.json', obs('2160-0', 1.2, 'mg/dL', '2026-10-02'))];
  await input.fire('change');
  release();
  await first;
  out.newerWins = { rows: find(box, (e) => e.attrs.class === 'lab-row-value').map(text) };
}

// 9. Nothing chosen (the picker cancelled) leaves the card empty.
{
  await pickFiles([]);
  out.empty = { box: text(box), children: box.children.length };
}

// 10. An export.zip: the clinical-records files inside it go through the same loop, caps and engine as files picked one by one
const REC = 'apple_health_export/clinical-records/';
const entryOf = (name, content, extra = {}) => ({ name: `${REC}${name}`, data: typeof content === 'string' ? content : JSON.stringify(content), ...extra });
const zipPick = async (file) => { input.files = [file]; input.value = 'C:\\fakepath\\export.zip'; log.read = []; await input.fire('change'); };
const shown = () => ({ error: find(box, (e) => e.attrs.role === 'alert').map(text), box: text(box), input: input.value, busy: box.attrs['aria-busy'] || null });
{
  // the same mix as scenario 1, as a .zip: the locked file is an encrypted entry; export.xml and other folders are never touched
  const hugeJson = JSON.stringify(obs('2823-3', 4.4, 'mmol/L', '2026-10-01')).replace('"final"', `"final", "padding": "${'x'.repeat(2 * 1024 * 1024)}"`);
  const mixed = zipFile('export.zip', [
    { name: 'apple_health_export/export.xml', data: '<HealthData>'.repeat(1000) },
    { name: 'apple_health_export/workout-routes/route_1.gpx', data: 'x', flags: 1, method: 'store' },
    entryOf('Observation-k.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07')),
    entryOf('Observation-cr.json', obs('14682-9', 150, 'umol/L', '2026-10-07')),
    entryOf('Patient-1.json', { resourceType: 'Patient', id: 'example', name: [{ family: 'Example' }] }),
    entryOf('Bundle-1.json', { resourceType: 'Bundle', type: 'collection', entry: [{ resource: obs('2160-0', 1.7, 'mg/dL', '2026-09-01') }, { resource: { resourceType: 'Condition', id: 'c' } }] }),
    entryOf('notes.json', 'not json at all'),
    entryOf('huge.json', hugeJson),
    entryOf('locked.json', obs('2823-3', 4.4, 'mmol/L', '2026-10-01'), { flags: 1, method: 'store' }),
    entryOf('Observation-mgdl.json', obs('2823-3', 18, 'mg/dL', '2026-10-02')),
    { name: '__MACOSX/apple_health_export/clinical-records/._Observation-k.json', data: 'AppleDouble', method: 'store' },
  ]);
  await zipPick(mixed);
  const boxes = checkboxes();
  out.zipMixed = {
    summary: summary(), ticked: boxes.map((b) => b.checked), rows: find(box, (e) => e.attrs.class === 'lab-row-value').map(text),
    days: find(box, (e) => e.attrs.class === 'lab-row-date').map(text), why: find(box, (e) => e.attrs.class === 'lab-import-why').map(text),
    save: { text: text(byText('Save')), disabled: byText('Save').disabled }, focused: page.focused, busy: box.attrs['aria-busy'] || null,
    streams: mixed.opened, over: mixed.over, read: log.read.length,
  };
  boxes[1].checked = false; await boxes[1].fire('change');
  await byText('Save').fire('click');
  out.zipSaved = { saved: log.saved, input: input.value, shown: text(box) };
  log.saved = [];
}
{
  // a damaged download (a checksum that does not match) is a file that could not be read, and the rest still import
  await zipPick(zipFile('export.zip', [
    entryOf('Observation-k.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07')),
    entryOf('Observation-bad.json', obs('2823-3', 4.9, 'mmol/L', '2026-10-08'), { crcXor: 1 }),
    entryOf('<img src=x onerror=alert(1)>.json', obs('2160-0', 1.2, 'mg/dL', '2026-10-09'), { flags: 1, method: 'store' }),
  ]));
  const tags = new Set(find(box, () => true).map((e) => e.tag));
  out.zipDamaged = { summary: summary(), rows: find(box, (e) => e.attrs.class === 'lab-row-value').map(text), tags: [...tags].sort(), noRealElements: !tags.has('img') && !tags.has('script') };
  await byText('Cancel').fire('click');
}
{
  // no clinical-records folder, a folder with another name, one that is too deep, and a macOS-only copy: the folder is not there
  out.zipNoFolder = {};
  const cases = {
    none: [{ name: 'apple_health_export/export.xml', data: '<HealthData/>' }],
    wrongName: [{ name: 'apple_health_export/Clinical-Records/Observation-1.json', data: '{}' }, { name: 'apple_health_export/clinical-records-2/Observation-1.json', data: '{}' }],
    tooDeep: [{ name: 'a/b/apple_health_export/clinical-records/Observation-1.json', data: '{}' }],
    macOnly: [{ name: '__MACOSX/apple_health_export/clinical-records/Observation-1.json', data: '{}' }, { name: 'apple_health_export/clinical-records/._Observation-1.json', data: '{}' }],
    notJsonFiles: [{ name: 'apple_health_export/clinical-records/readme.txt', data: 'x' }],
  };
  for (const [key, entries] of Object.entries(cases)) {
    const file = zipFile('export.zip', entries);
    await zipPick(file);
    out.zipNoFolder[key] = { ...shown(), opened: file.opened };
  }
  // a zip with the folder at the top (a re-zipped clinical-records folder) is fine
  await zipPick(zipFile('export.zip', [{ name: 'clinical-records/Observation-1.json', data: JSON.stringify(obs('2823-3', 5.4, 'mmol/L', '2026-10-07')) }]));
  out.zipTopFolder = { summary: summary() };
  await byText('Cancel').fire('click');
}
{
  // not a zip, cut off, empty, and a .zip chosen together with json files
  out.zipBroken = {};
  const cases = {
    notZip: zipFile('export.zip', Buffer.from('PK\x03\x04 this only starts like a zip')),
    cutOff: zipFile('export.zip', makeZip([entryOf('Observation-1.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07'))]).subarray(0, 100)),
    empty: zipFile('export.zip', Buffer.alloc(0)),
  };
  for (const [key, file] of Object.entries(cases)) {
    await zipPick(file);
    out.zipBroken[key] = { ...shown(), opened: file.opened };
  }
  const good = zipFile('export.zip', [entryOf('Observation-1.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07'))]);
  input.files = [good, fileOf('a.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07'))]; input.value = 'x'; log.read = [];
  await input.fire('change');
  out.zipAndFiles = { ...shown(), opened: good.opened, read: log.read.length, slices: good.slices.length };
  // by type alone (no .zip in the name)
  const byType = zipFile('download', [entryOf('Observation-1.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07'))], { type: 'application/zip' });
  input.files = [byType]; input.value = 'x';
  await input.fire('change');
  out.zipByType = { summary: summary() };
  await byText('Cancel').fire('click');
}
{
  // the caps: 2,001 entries are refused before any is read; exactly 2,000 are read (in order); an entry over 1 MB is skipped, not read
  const many = zipFile('export.zip', Array.from({ length: FL.MAX_FILES + 1 }, (_, i) => entryOf(`o-${i}.json`, '{}')));
  await zipPick(many);
  out.zipTooMany = { ...shown(), opened: many.opened };
  const exactly = zipFile('export.zip', Array.from({ length: FL.MAX_FILES }, (_, i) => entryOf(`o-${i}.json`, i === 0 ? obs('2823-3', 4.5, 'mmol/L', '2026-10-01') : '{}')));
  await zipPick(exactly);
  out.zipExactly2000 = { summary: summary(), opened: exactly.opened, over: exactly.over };
  await byText('Cancel').fire('click');
}
{
  // a browser without DecompressionStream: the old advice, the archive is not opened
  delete win.DecompressionStream;
  const file = zipFile('export.zip', [entryOf('Observation-1.json', obs('2823-3', 5.4, 'mmol/L', '2026-10-07'))]);
  await zipPick(file);
  out.zipBrowser = { ...shown(), slices: file.slices.length, opened: file.opened };
  win.DecompressionStream = DecompressionStream;
  await zipPick(file);
  out.zipBrowserBack = { summary: summary() };
  await byText('Cancel').fire('click');
}
{
  // a newer pick wins over a .zip that is still being read; Cancel during a .zip lets go of it
  const slow = zipFile('export.zip', Array.from({ length: 40 }, (_, i) => entryOf(`o-${i}.json`, obs('2823-3', 4.4, 'mmol/L', '2026-10-01'))), { chunk: 64, delay: 3 });
  input.files = [slow]; input.value = 'x';
  const first = input.fire('change');
  await new Promise((resolve) => setTimeout(resolve, 60));
  input.files = [fileOf('fast.json', obs('2160-0', 1.2, 'mg/dL', '2026-10-02'))];
  await input.fire('change');
  await first;
  await new Promise((resolve) => setTimeout(resolve, 200));
  out.zipNewerWins = { rows: find(box, (e) => e.attrs.class === 'lab-row-value').map(text), opened: slow.opened, over: slow.over };
  await byText('Cancel').fire('click');
  const slow2 = zipFile('export.zip', Array.from({ length: 40 }, (_, i) => entryOf(`o-${i}.json`, obs('2823-3', 4.4, 'mmol/L', '2026-10-01'))), { chunk: 64, delay: 3 });
  input.files = [slow2]; input.value = 'x';
  const second = input.fire('change');
  await new Promise((resolve) => setTimeout(resolve, 60));
  const during = shown();
  // there is no Cancel button while reading; choosing nothing (the picker cancelled) drops it
  input.files = []; await input.fire('change');
  await second;
  await new Promise((resolve) => setTimeout(resolve, 200));
  out.zipDropped = { during: during.box, after: shown(), saved: log.saved.length };
}

out.network = log.network;
console.log(JSON.stringify(out));
