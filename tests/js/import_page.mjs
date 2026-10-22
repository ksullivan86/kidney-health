#!/usr/bin/env node
// Runs the "Import from a file" block of app/static/js/views/settings.js against a tiny fake page and a fake server
// answer, and prints what happened as JSON, so pytest (tests/test_data_import_ui.py) can check the behaviour without
// a browser: which file is read, what is sent (and what never is), what the person is shown, which choices re-check,
// and what is reset after Import. The block is cut out of the view by its markers; the helpers it uses (h, clear,
// action, ...) are stand-ins with the same contract as js/core.js and the view's own. The real zip reader (js/engine/zip.js) is
// loaded, and node tests/js/import_page.mjs <folder> opens the archives that tests/test_data_import_ui.py built in <folder> (a
// .zip pick, docs/dev/research/11-reading-a-zip-in-the-browser.md section 4.5).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const folder = process.argv[2] || null;
vm.runInThisContext(readFileSync(join(ROOT, 'app', 'static', 'js', 'engine', 'zip.js'), 'utf8'), { filename: 'zip.js' });
const source = readFileSync(join(ROOT, 'app', 'static', 'js', 'views', 'settings.js'), 'utf8');
const code = source.slice(source.indexOf('  const IMPORT_MAX_BYTES'), source.indexOf('  const ACTION_LABEL = {'));

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this.textContent = ''; this.disabled = false; this.checked = false; this.value = ''; this.files = null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  // like Element.append(): a null becomes the text "null", which is what the real page would show
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'object' && k && k.nodeType ? k : new Text(String(k))); }
  get firstChild() { return this.children[0] || null; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  focus() { page.focused = this.attrs.id || this.tag; }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({}); await settle(); }
}
const page = { focused: null, byId: {} };
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const h = (tag, attrs, ...kids) => {
  const el = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    el.setAttribute(k, v === true ? '' : String(v));
    if (k === 'id') page.byId[v] = el;
  }
  const add = (k) => { if (k == null || k === false) return; if (Array.isArray(k)) { k.forEach(add); return; } el.append(k.nodeType ? k : new Text(String(k))); };
  kids.forEach(add);
  return el;
};
const clear = (el) => { el.children = []; return el; };
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();

const log = { calls: [], toasts: [], labsInvalidated: 0, profileLoaded: 0 };
let answer = () => ({});
const A = { importData: async (body, o) => { log.calls.push({ options: { ...o }, keys: Object.keys(body) }); return answer(o); } };
const state = { dayLoadedFor: 'x', plan: {}, planStart: 1, trends: {}, summary: {}, shopping: {}, meals: [] };
const KH = { labs: { invalidate() { log.labsInvalidated += 1; } }, loadProfile: async () => { log.profileLoaded += 1; }, zip: globalThis.KH.zip };
function action(label, cls, fn, attrs = {}) {
  const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
  btn.handlers.click = [async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    try { await fn(btn); } catch (err) { log.toasts.push(['error', err.message]); } finally { btn.disabled = false; }
  }];
  return btn;
}
function build(MOCK) {
  page.byId = {};
  const context = vm.createContext({
    h, clear, action, A, state, KH, MOCK, toast: (m, t) => log.toasts.push([t || '', m]), subtitle: (t, id) => h('h3', { id }, t),
    statusMsg: (id) => h('p', { id }), note: (kind, ...c) => h('div', { class: kind }, ...c), fmtBytes: (n) => `${n} B`,
    fmtDate: (s) => s, $: (sel) => page.byId[sel.slice(1)] || null, console, JSON, Promise, AbortController,
  });
  vm.runInContext(`${code}\nglobalThis.importBlock = importBlock;`, context);
  return context.importBlock();
}

const out = {};
const demo = build(true);
out.demo = { text: text(demo), hasInput: 'set-import-file' in page.byId, calls: log.calls.length };

const block = build(false);
const input = page.byId['set-import-file'];
const msg = page.byId['set-import-msg'];
const result = page.byId['set-import-result'];
out.input = { type: input.attrs.type, accept: input.attrs.accept };
out.block = text(block);
async function pick(name, content, size) {
  input.files = [{ name, type: '', size: size ?? content.length, text: async () => content }];
  await input.fire('change');
}
const file = { format: 'kidney-health-export', version: 1, user: { username: 'sam' }, ai_audit: [{ prompt: 'x' }], activity: [], ai_usage: [], ai_consents: [],
  ai_provider: { api_key: 'secret' }, log_entries: [] };
const reply = (over = {}) => ({
  dry_run: true, imported: false, can_import: true, blocked: null,
  file: { exported_at: '2026-10-15T07:00:00Z', app_version: '0.3.0', records: { log_entries: 2, custom_foods: 1, meal_templates: 1, lab_results: 0, profile: 1 } },
  counts: { log_entries: 2, custom_foods: 1, meal_templates: 1, profile: 0, settings: 0 }, already_there: { log_entries: 1 },
  skipped: { total: 1, shown: [{ kind: 'log_entries', index: 0, label: '2026-10-05 lunch: Ghost pie', reason: 'its food is not in the file' }], by_kind: { log_entries: 1 }, more: 0 },
  not_selected: ['your profile and targets'], not_imported: ['Passwords'], rule: 'The rule.', ...over,
});

await pick('export.zip', 'PK');
out.zip = { message: msg.textContent, calls: log.calls.length };
await pick('export.json', 'x', 17 * 1024 * 1024);
out.tooBig = { message: msg.textContent, calls: log.calls.length };
await pick('export.json', 'not json');
out.notJson = { message: msg.textContent, calls: log.calls.length };
await pick('export.json', '[1, 2]');
out.notObject = { message: msg.textContent, calls: log.calls.length };

answer = () => reply();
await pick('export.json', JSON.stringify(file));
out.first = {
  options: log.calls[0].options, keys: log.calls[0].keys, focused: page.focused, message: msg.textContent, text: text(result),
  importDisabled: page.byId['set-import-go'].disabled, merge: page.byId['set-import-merge'].checked, profile: page.byId['set-import-profile'].checked,
};

page.byId['set-import-merge'].checked = true;
await page.byId['set-import-merge'].fire('change');
out.merged = { options: log.calls[1].options, focused: page.focused };
page.byId['set-import-profile'].checked = true;
await page.byId['set-import-profile'].fire('change');
out.profileChosen = { options: log.calls[2].options, focused: page.focused };

page.byId['set-import-merge'].checked = false;
page.byId['set-import-profile'].checked = false;
answer = (o) => (o.merge ? reply() : reply({ can_import: false, blocked: { code: 'account_not_empty', existing: { log_entries: 3, custom_foods: 1 } } }));
await page.byId['set-import-merge'].fire('change');
out.blocked = { text: text(result), importDisabled: page.byId['set-import-go'].disabled };

answer = () => reply({ counts: { log_entries: 0, custom_foods: 0, meal_templates: 0, profile: 0, settings: 0 }, already_there: {}, skipped: { total: 0, shown: [], by_kind: {}, more: 0 } });
await page.byId['set-import-merge'].fire('change');
out.nothingNew = text(result);

page.byId['set-import-merge'].checked = true;
answer = () => reply();
await page.byId['set-import-merge'].fire('change');
const before = log.calls.length;
answer = (o) => reply({ dry_run: false, imported: true, counts: { log_entries: 2, custom_foods: 1, meal_templates: 0, profile: 1, settings: 2 } });
await page.byId['set-import-go'].handlers.click[0]();
await settle();
out.imported = {
  options: log.calls[before].options, message: msg.textContent, toast: log.toasts[log.toasts.length - 1], result: result.children.length,
  fileInput: input.value, state, labsInvalidated: log.labsInvalidated, profileLoaded: log.profileLoaded,
};

answer = () => { const e = new Error('The file was not imported. log_entries[3].servings: must be greater than 0'); e.detail = e.message; throw e; };
await pick('export.json', JSON.stringify(file));
out.refused = { text: text(result), message: msg.textContent };

answer = () => { const e = new Error('cancelled'); e.cancelled = true; e.handled = true; throw e; };
input.value = 'C:\\fakepath\\export.json'; // what a browser's file box holds once a file is chosen
await pick('export.json', JSON.stringify(file));
out.cancelled = { text: text(result), message: msg.textContent, fileInput: input.value };

// Cancel button forgets the file
answer = () => reply();
await pick('export.json', JSON.stringify(file));
await page.byId['set-import-cancel'].handlers.click[0]();
out.cancel = { message: msg.textContent, result: result.children.length };

// ---- a .zip: the archives tests/test_data_import_ui.py built (their folder is the first argument) ------------------------------------------------
if (folder) {
  const RealDS = globalThis.DecompressionStream;
  const zipFile = (name, archive, type = 'application/zip') => {
    const blob = new Blob([readFileSync(join(folder, archive))]);
    return Object.defineProperties(blob, { name: { value: name }, type: { value: type } });
  };
  const pickZip = async (archive, name = 'kidney-health-sam.zip', type = 'application/zip') => {
    input.files = [zipFile(name, archive, type)];
    await input.fire('change');
  };
  const seen = (before, extra = {}) => ({ message: msg.textContent, calls: log.calls.length - before, result: result.children.length, ...extra });
  answer = () => reply();
  out.zips = {};
  for (const [key, archive] of Object.entries({
    missing: 'no_export.zip', ambiguous: 'two_exports.zip', damaged: 'damaged.zip', encrypted: 'encrypted.zip', notJson: 'not_json.zip', notObject: 'array.zip',
    notZip: 'not_a_zip.zip', tooBig: 'too_big.zip',
  })) {
    const before = log.calls.length;
    await pickZip(archive);
    out.zips[key] = seen(before);
  }
  out.zips.sizes = JSON.parse(readFileSync(join(folder, 'sizes.json'), 'utf8'));
  for (const [key, archive, name, type] of [['plain', 'export_ok.zip', 'kidney-health-sam.zip', 'application/zip'], ['rezipped', 'rezipped.zip', 'folder.zip', 'application/zip'],
    ['byType', 'export_ok.zip', 'download', 'application/zip'], ['byNameOnly', 'export_ok.zip', 'EXPORT.ZIP', '']]) {
    const before = log.calls.length;
    await pickZip(archive, name, type);
    out.zips[key] = seen(before, { options: log.calls[before] && log.calls[before].options, keys: log.calls[before] && log.calls[before].keys, focused: page.focused,
      importDisabled: page.byId['set-import-go'] && page.byId['set-import-go'].disabled, text: text(result) });
  }
  { // the same dry run as the export.json inside it picked by itself
    const before = log.calls.length;
    await pick('export.json', JSON.stringify(file));
    out.zips.json = seen(before, { options: log.calls[before].options, keys: log.calls[before].keys, text: text(result) });
  }
  { // a browser without DecompressionStream: the old advice, and the archive is not even opened
    delete globalThis.DecompressionStream;
    const before = log.calls.length;
    await pickZip('export_ok.zip');
    out.zips.browser = seen(before);
    globalThis.DecompressionStream = RealDS;
  }
  { // choosing again while the first .zip is still being read: only the second choice is checked
    const before = log.calls.length;
    input.files = [zipFile('first.zip', 'export_ok.zip')];
    const slow = input.fire('change');
    input.files = [{ name: 'second.json', type: '', size: 10, text: async () => JSON.stringify({ ...file, log_entries: [], second: true }) }];
    await input.fire('change');
    await slow;
    await settle();
    out.zips.race = seen(before, { keys: log.calls.map((c) => c.keys.join(',')).slice(before) });
  }
  { // Cancel forgets a checked .zip; a new pick of nothing leaves the block empty
    await pickZip('export_ok.zip');
    await page.byId['set-import-cancel'].handlers.click[0]();
    out.zips.cancel = { message: msg.textContent, result: result.children.length, fileInput: input.value };
    input.files = [];
    await input.fire('change');
    out.zips.nothing = { message: msg.textContent, result: result.children.length };
  }
}

console.log(JSON.stringify(out));
