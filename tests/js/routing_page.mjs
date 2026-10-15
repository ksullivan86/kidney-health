#!/usr/bin/env node
// Runs app/static/js/views/ai_routing.js against a tiny fake page and fake server answers, and prints what happened as
// JSON, so pytest (tests/test_ai_routing_ui.py) can check the behaviour without a browser: the table of features, which
// choices are offered, the warning for every feature that sends something to the cloud, what is sent on Save, and the
// lines a person reads. The helpers the file takes from KH (h, clear, toast) are stand-ins with the contract of js/core.js.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const source = readFileSync(join(ROOT, 'app', 'static', 'js', 'views', 'ai_routing.js'), 'utf8');

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this.textContent = ''; this.disabled = false; this._value = null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'object' && k && k.nodeType ? k : new Text(String(k))); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  get value() {
    if (this._value !== null) return this._value;
    if (this.tag === 'select') {
      const opts = this.children.filter((c) => c.tag === 'option');
      const picked = opts.find((o) => o.attrs.selected !== undefined) || opts[0];
      return picked ? picked.attrs.value : '';
    }
    return this.attrs.value ?? '';
  }
  set value(v) { this._value = String(v); }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({}); await new Promise((r) => setTimeout(r, 0)); }
}
const h = (tag, attrs, ...kids) => {
  const el = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    el.setAttribute(k, v === true ? '' : String(v));
  }
  const add = (k) => { if (k == null || k === false) return; if (Array.isArray(k)) { k.forEach(add); return; } el.append(k.nodeType ? k : new Text(String(k))); };
  kids.forEach(add);
  return el;
};
const clear = (el) => { el.children = []; return el; };
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();
const find = (el, pred, out = []) => { if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach((c) => find(c, pred, out)); } return out; };

const log = { saved: [], toasts: [], forgot: 0, after: 0 };
let failSave = null;
const KH = {
  h, clear, toast: (m, k) => log.toasts.push([k, m]),
  ai: { forget: () => { log.forgot += 1; }, api: { setRouting: async (b) => { if (failSave) throw failSave; log.saved.push(b); return {}; } } },
};
const context = vm.createContext({ window: { KH }, document: { contains: () => true }, console });
vm.runInContext(source, context, { filename: 'ai_routing.js' });
const R = context.window.KH.aiRouting;

const FEATURES = [
  ['photos', 'Photos (labels and plates)', 'your photos of labels and plates'],
  ['meal_ideas', 'Meal ideas', 'your meal data (stage, targets, today\'s totals and the foods the rules offered)'],
  ['describe', 'Describe a meal', 'the meals you describe in words'],
  ['chat', 'Ask', 'your messages in Ask and the app\'s own numbers the AI looks up'],
];
const PROVIDERS = [
  { id: 1, label: 'OpenAI', host: 'api.openai.com', private: false, role: 'cloud', photos: true, usable: true, locked: true },
  { id: 2, label: 'Ollama', host: 'ollama.lan:11434', private: true, role: 'local', photos: true, usable: true, locked: false },
  { id: 3, label: 'Spare cloud', host: 'api.example.com', private: false, role: null, photos: false, usable: true, locked: false },
];
function data({ routes = {}, locked = {}, roles = { local: 2, cloud: 1 }, providers = PROVIDERS, writable = true, envRole = null } = {}) {
  const features = FEATURES.map(([feature, label, sends]) => ({ feature, label, sends, route: routes[feature] || 'local', source: 'default', locked_by_env: locked[feature] || null }));
  const role = (r) => (roles[r] ? { id: roles[r], label: 'x', host: 'x', private: r === 'local' } : null);
  return { features, roles: { local: role('local'), cloud: role('cloud') }, providers, env_role: envRole, as_before: features.some((f) => f.route === 'any'), writable };
}
const warningsOf = (root) => find(root, (e) => e.attrs.class === 'ai-routing-warnings').map(text).join(' | ');
const radio = (root, feature, route) => find(root, (e) => e.tag === 'input' && e.attrs['aria-label'] === `${FEATURES.find((f) => f[0] === feature)[1]}: ${{ local: 'Local', cloud: 'Cloud', off: 'Off', any: 'As before' }[route]}`)[0];
const selects = (root) => find(root, (e) => e.tag === 'select');
const options = (sel) => sel.children.filter((c) => c.tag === 'option').map((o) => o.attrs.value + ':' + text(o));
const out = {};

// 1. A routed server: every feature local. Picking cloud for meal ideas shows the warning and sends one change on Save.
{
  const root = R.adminPart(data(), () => { log.after += 1; });
  const [localSel, cloudSel] = selects(root);
  out.routed = {
    header: find(root, (e) => e.tag === 'th' && e.attrs.scope === 'col').map(text),
    rows: find(root, (e) => e.tag === 'th' && e.attrs.scope === 'row').map(text),
    localOptions: options(localSel), cloudOptions: options(cloudSel),
    anyRadio: !!radio(root, 'photos', 'any'),
    asBeforeBanner: text(root).includes('Routing is not set up yet'),
    warningsAtStart: warningsOf(root),
  };
  radio(root, 'meal_ideas', 'cloud').attrs.checked = '';
  await radio(root, 'meal_ideas', 'cloud').fire('change');
  out.afterCloud = warningsOf(root);
  const save = find(root, (e) => e.tag === 'button' && text(e) === 'Save routing')[0];
  await save.fire('click');
  out.saved = log.saved.slice();
  out.afterSave = { forgot: log.forgot, after: log.after, toasts: log.toasts.slice() };
  const fresh = R.adminPart(data(), null);
  await find(fresh, (e) => e.tag === 'button' && text(e) === 'Save routing')[0].fire('click');
  out.nothingChanged = { saved: log.saved.length, message: text(find(fresh, (e) => e.tag === 'p' && e.attrs.role === 'status')[0]) };
}

// 2. A feature pinned to cloud with no cloud AI chosen: the one left-over provider is offered, visibly.
{
  const root = R.adminPart(data({ roles: { local: 2 }, providers: [{ ...PROVIDERS[0], role: null }, PROVIDERS[1]] }), null);
  const cloudSel = selects(root)[1];
  out.noCloudYet = { before: cloudSel.value, warnings: warningsOf(root) };
  await radio(root, 'chat', 'cloud').fire('change');
  out.offered = { cloudValue: cloudSel.value, warnings: warningsOf(root) };
  await find(root, (e) => e.tag === 'button' && text(e) === 'Save routing')[0].fire('click');
  out.offeredSaved = log.saved[log.saved.length - 1];
}

// 3. Local with no local AI, an upgraded server (As before), a locked row, no sign-in.
{
  const noLocal = R.adminPart(data({ roles: {}, providers: [PROVIDERS[0], PROVIDERS[2]] }), null);
  out.noLocal = { warnings: warningsOf(noLocal), localOptions: options(selects(noLocal)[0]), hint: text(noLocal).includes('No shared provider is on a private address yet') };
  const asBefore = R.adminPart(data({ routes: { photos: 'any', meal_ideas: 'any', describe: 'any', chat: 'any' } }), null);
  out.asBefore = {
    banner: text(asBefore).includes('Routing is not set up yet'),
    header: find(asBefore, (e) => e.tag === 'th' && e.attrs.scope === 'col').map(text),
    anyEnabled: radio(asBefore, 'photos', 'any').disabled === false,
    warnings: warningsOf(asBefore),
  };
  const lockedRoot = R.adminPart(data({ locked: { photos: 'AI_ROUTE_PHOTOS' } }), null);
  out.locked = { disabled: radio(lockedRoot, 'photos', 'local').disabled, other: radio(lockedRoot, 'chat', 'local').disabled, note: text(lockedRoot).includes('Set by the server (AI_ROUTE_PHOTOS)') };
  const readonly = R.adminPart(data({ writable: false }), null);
  out.readonly = {
    radio: radio(readonly, 'photos', 'local').disabled, select: selects(readonly)[0].disabled,
    save: find(readonly, (e) => e.tag === 'button' && text(e) === 'Save routing')[0].disabled,
    note: text(readonly).includes('AI_ROUTE_PHOTOS'),
  };
  const envRole = R.adminPart(data({ envRole: 'local' }), null);
  out.envRole = { localDisabled: selects(envRole)[0].disabled, cloudDisabled: selects(envRole)[1].disabled, text: text(envRole).includes('AI_PROVIDER_ROLE=local') };
}

// 4. A refused save shows the server's words and keeps the form.
{
  const root = R.adminPart(data(), null);
  await radio(root, 'photos', 'off').fire('change');
  failSave = Object.assign(new Error('x'), { detail: 'not a private host' });
  await find(root, (e) => e.tag === 'button' && text(e) === 'Save routing')[0].fire('click');
  failSave = null;
  out.refused = text(find(root, (e) => e.attrs.role === 'alert')[0]);
}

// 5. What a person reads.
{
  const routing = { mode: 'routed', features: [
    { feature: 'photos', label: 'Photos (labels and plates)', text: 'Runs on your local AI (ollama.lan:11434).' },
    { feature: 'chat', label: 'Ask', text: 'Runs on OpenAI (api.openai.com), a cloud AI outside your network.' },
    { feature: 'describe', label: 'Describe a meal', text: 'Switched off by your admin.' },
  ] };
  out.person = { lines: text(R.personLines(routing)), none: R.personLines(null), before: text(R.personLines({ ...routing, mode: 'as_before' })) };
}

// 6. Lab report photos are local or off only: the row offers those two choices and nothing else, and says so.
{
  const withLabs = data();
  withLabs.features.push({ feature: 'labs', label: 'Lab report photos', sends: 'your photos of lab reports', route: 'local', source: 'default', locked_by_env: null, allowed: ['local', 'off'] });
  FEATURES.push(['labs', 'Lab report photos', 'your photos of lab reports']);
  const root = R.adminPart(withLabs, null);
  const row = find(root, (e) => e.tag === 'tr' && find(e, (x) => x.tag === 'th' && x.attrs.scope === 'row' && text(x).startsWith('Lab report photos')).length)[0];
  out.labs = {
    radios: find(row, (e) => e.tag === 'input').map((e) => e.attrs['aria-label']),
    cells: find(row, (e) => e.tag === 'td').length,
    notOffered: find(row, (e) => e.attrs.class === 'ai-route-na').map(text),
    hint: text(find(row, (e) => e.tag === 'th')[0]),
    intro: text(root).includes('never go to a cloud AI'),
    cloudWarning: warningsOf(root),
  };
  await radio(root, 'labs', 'off').fire('change');
  await find(root, (e) => e.tag === 'button' && text(e) === 'Save routing')[0].fire('click');
  out.labsSaved = log.saved[log.saved.length - 1];
}

console.log(JSON.stringify(out));
