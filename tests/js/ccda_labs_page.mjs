#!/usr/bin/env node
// Runs app/static/js/views/lab_ccda.js against a tiny fake page and fake files, together with the real js/engine/rules.js,
// js/engine/kidney_function.js, js/engine/fhir_labs.js, js/engine/ccda_labs.js and js/views/lab_fhir.js (whose review table it
// shares), and prints what happened as JSON, so pytest (tests/test_ccda_labs_ui.py) can check the behaviour without a browser: which
// files are read (a file over 5 MB never is), which are parsed and as what (a file with a DOCTYPE never is), what the person is shown,
// that new results start ticked and saved ones do not, what is handed to the shared save (POST /api/labs/import) and that it holds no
// file name or identity, that too many files are refused before any is read, that text from a file is drawn as text, and that nothing
// calls the network. The helpers the file takes from KH (h, $, clear, util, labs, views.labs) are stand-ins with the contract of
// js/core.js; DOMParser is a stand-in that records the type it was asked for and parses with the dev-only tests/js/mini_xml.mjs.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { parse } from './mini_xml.mjs';

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
const log = { read: [], parsed: [], saved: [], toasts: [], network: [] };
let existing = [];
const input = new El('input'); page.byId['lab-ccda-file'] = input;
const box = new El('div'); page.byId['lab-ccda-preview'] = box;
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
// The browser's parser, as far as the engine uses it: it records the type it was asked for. Like the app's page (CSP `require-trusted-types-for
// 'script'`) it throws on a plain string: only a TrustedHTML made by a policy is accepted, and a policy is a name the CSP lists.
class TrustedHTML { constructor(s) { this.s = s; } }
class FakeDOMParser {
  parseFromString(source, type) {
    if (!(source instanceof TrustedHTML)) throw new TypeError("Failed to execute 'parseFromString' on 'DOMParser': This document requires 'TrustedHTML' assignment.");
    log.parsed.push(type);
    return parse(source.s);
  }
}
const made = []; // the policies created: [name, policy]
const trustedTypes = {
  createPolicy(name, rules) {
    if (name !== 'kh-xml' || made.some(([n]) => n === name)) throw new TypeError(`Policy ${name} disallowed.`); // the CSP's list, no duplicates
    const policy = { createHTML: (s) => new TrustedHTML(rules.createHTML(s)) };
    made.push([name, policy]);
    return policy;
  },
};
const window = { KH, DOMParser: FakeDOMParser, trustedTypes };
const context = vm.createContext({ window, console, fetch: trap('fetch'), XMLHttpRequest: trap('XMLHttpRequest'), WebSocket: trap('WebSocket'), navigator: { sendBeacon: trap('sendBeacon') } });
for (const file of [['js', 'engine', 'rules.js'], ['js', 'engine', 'kidney_function.js'], ['js', 'engine', 'fhir_labs.js'], ['js', 'engine', 'ccda_labs.js'], ['js', 'views', 'lab_fhir.js'], ['js', 'views', 'lab_ccda.js']]) {
  vm.runInContext(read(...file), context, { filename: file.join('/') });
}
const CC = window.KH.ccdaLabs;
const out = {};

// ---- fake files ------------------------------------------------------------------------------------------------------------------
const NS = 'xmlns="urn:hl7-org:v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"';
const obs = (code, value, unit, date) => `<component><observation classCode="OBS" moodCode="EVN"><templateId root="2.16.840.1.113883.10.20.22.4.2"/>`
  + `<id root="1.3.6.1.4.1.99999.3" extension="example-obs"/><code code="${code}" codeSystem="2.16.840.1.113883.6.1"/><statusCode code="completed"/>`
  + `<effectiveTime value="${date}"/><value xsi:type="PQ" value="${value}" unit="${unit}"/></observation></component>`;
const doc = (...observations) => `<?xml version="1.0" encoding="UTF-8"?><ClinicalDocument ${NS}><recordTarget><patientRole><patient><name><given>Sam</given><family>Example</family></name></patient></patientRole></recordTarget>`
  + `<component><structuredBody><component><section><templateId root="2.16.840.1.113883.10.20.22.2.3.1"/><title>Results</title><entry><organizer classCode="BATTERY" moodCode="EVN">`
  + `<templateId root="2.16.840.1.113883.10.20.22.4.1"/>${observations.join('')}</organizer></entry></section></component></structuredBody></component></ClinicalDocument>`;
const fileOf = (name, content, size = null) => ({
  name, size: size == null ? Buffer.byteLength(content instanceof Error ? '' : content) : size,
  text: async () => { log.read.push(name); if (content instanceof Error) throw content; return content; },
});
const pickFiles = async (files) => { input.files = files; input.value = 'C:\\fakepath\\x'; log.read = []; log.parsed = []; await input.fire('change'); };
const checkboxes = () => find(box, (e) => e.tag === 'input' && e.attrs.type === 'checkbox');
const buttons = () => find(box, (e) => e.tag === 'button');
const byText = (label) => buttons().find((b) => text(b).startsWith(label));
const summary = () => { const s = find(box, (e) => e.attrs.class === 'lab-import-summary')[0]; return s ? text(s) : null; };

// 1. A mixed pick: two summaries, text that is not XML, a file with a DOCTYPE (never parsed), a file over 5 MB (never read), one that cannot be read, FHIR XML.
{
  await pickFiles([
    fileOf('summary-1.xml', doc(obs('2823-3', 5.4, 'mmol/L', '20261007'), obs('14682-9', 150, 'umol/L', '20261007'))),
    fileOf('summary-2.xml', doc(obs('2160-0', 1.7, 'mg/dL', '20260901'), obs('2823-3', 18, 'mg/dL', '20261002'))),
    fileOf('notes.xml', 'not xml at all'),
    fileOf('dtd.xml', `<?xml version="1.0"?><!DOCTYPE ClinicalDocument [<!ENTITY x "y">]>${doc(obs('2823-3', 4.4, 'mmol/L', '20261001'))}`),
    fileOf('huge.xml', doc(obs('2823-3', 4.4, 'mmol/L', '20261001')), 9 * 1024 * 1024),
    fileOf('locked.xml', new Error('NotReadableError')),
    fileOf('fhir.xml', '<Observation xmlns="http://hl7.org/fhir"/>'),
  ]);
  const boxes = checkboxes();
  out.mixed = {
    read: log.read, parsed: log.parsed, summary: summary(), ticked: boxes.map((b) => b.checked),
    rows: find(box, (e) => e.attrs.class === 'lab-row-value').map(text),
    days: find(box, (e) => e.attrs.class === 'lab-row-date').map(text),
    why: find(box, (e) => e.attrs.class === 'lab-import-why').map(text),
    save: { text: text(byText('Save')), disabled: byText('Save').disabled },
    classes: find(box, (e) => e.tag === 'ul').map((e) => e.attrs.class), focused: page.focused,
    hint: find(box, (e) => e.attrs.class === 'hint').map(text),
    ids: [...find(box, (e) => e.attrs.id).map((e) => e.attrs.id)],
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
  await pickFiles([fileOf('a.xml', doc(obs('2823-3', 5.4, 'mmol/L', '20261007'))), fileOf('b.xml', doc(obs('2823-3', 4.9, 'mmol/L', '20261008')))]);
  out.alreadySaved = { summary: summary(), ticked: checkboxes().map((b) => b.checked), tags: find(box, (e) => e.attrs.class === 'lab-import-saved').map(text), save: text(byText('Save')) };
  existing = [];
}

// 3. Cancel forgets the pick and puts the focus back on the file chooser; nothing was sent.
{
  await pickFiles([fileOf('a.xml', doc(obs('2823-3', 5.4, 'mmol/L', '20261007')))]);
  await byText('Cancel').fire('click');
  out.cancelled = { box: text(box), input: input.value, focused: page.focused, saved: log.saved.length };
}

// 4. More than 20 files are refused before any is read.
{
  const many = Array.from({ length: CC.MAX_FILES + 1 }, (_, i) => fileOf(`s-${i}.xml`, '<a/>'));
  await pickFiles(many);
  out.tooMany = { read: log.read.length, parsed: log.parsed.length, message: text(box), alert: find(box, (e) => e.attrs.role === 'alert').length };
}

// 5. Exactly 20 files are read (in order, one at a time), and a file with more than 1,000 results shows the newest 1,000.
{
  const days = Array.from({ length: 1005 }, (_, i) => new Date(Date.UTC(2023, 0, 1 + i)).toISOString().slice(0, 10).replace(/-/g, ''));
  await pickFiles([fileOf('big.xml', doc(...days.map((d, i) => obs('2823-3', 4 + (i % 40) / 10, 'mmol/L', d))))]);
  const boxes = checkboxes();
  out.many = { summary: summary(), rows: boxes.length, save: { text: text(byText('Save')), disabled: byText('Save').disabled }, firstDay: text(find(box, (e) => e.attrs.class === 'lab-row-date')[0]) };
  await byText('Cancel').fire('click');
  const twenty = Array.from({ length: CC.MAX_FILES }, (_, i) => fileOf(`s-${i}.xml`, i === 0 ? doc(obs('2823-3', 4.5, 'mmol/L', '20261001')) : '<a/>'));
  await pickFiles(twenty);
  out.exactly20 = { read: log.read.length, order: log.read.slice(0, 3), summary: summary() };
  await byText('Cancel').fire('click');
}

// 6. Text from a file is drawn as text: a hostile unit and date make no element.
{
  await pickFiles([
    fileOf('<img src=x onerror=alert(1)>.xml', doc(obs('2823-3', 4.4, '&lt;img src=x onerror=alert(1)&gt;', '20261001'), obs('2160-0', 1.2, 'mg/dL', '&lt;script&gt;alert(1)&lt;/script&gt;'))),
    fileOf('<script>alert(1)</script>.xml', doc(obs('2823-3', 4.4, '&lt;b&gt;mg/dL&lt;/b&gt;', '20261001'))),
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
  await pickFiles([fileOf('fhir.xml', '<Observation xmlns="http://hl7.org/fhir"/>'), fileOf('allergies.xml', `<ClinicalDocument ${NS}><component><structuredBody><component><section><templateId root="2.16.840.1.113883.10.20.22.2.6.1"/></section></component></structuredBody></component></ClinicalDocument>`)]);
  out.nothing = { summary: summary(), hint: find(box, (e) => e.attrs.class === 'hint warn').map(text), buttons: buttons().map(text), checkboxes: checkboxes().length };
}

// 8. A newer pick wins over an older one that is still being read.
{
  let release;
  const slow = { name: 'slow.xml', size: 10, text: () => new Promise((resolve) => { release = () => resolve(doc(obs('2823-3', 4.4, 'mmol/L', '20261001'))); }) };
  input.files = [slow]; input.value = 'x';
  const first = input.fire('change');
  await settle();
  input.files = [fileOf('fast.xml', doc(obs('2160-0', 1.2, 'mg/dL', '20261002')))];
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

// 10. The one policy: created once (the CSP does not allow a second), and it refuses what must never reach the parser.
{
  const policy = made[0] && made[0][1];
  const tries = (s) => { try { policy.createHTML(s); return 'accepted'; } catch (e) { return 'refused'; } };
  out.policy = {
    created: made.map(([name]) => name),
    xml: tries('<?xml version="1.0"?><ClinicalDocument xmlns="urn:hl7-org:v3"/>'),
    doctype: tries('<!DOCTYPE x [<!ENTITY y "z">]><x/>'),
    entity: tries('<x><!ENTITY y "z"></x>'),
    notAString: tries({ toString: () => '<x/>' }),
  };
}

out.network = log.network;
console.log(JSON.stringify(out));
