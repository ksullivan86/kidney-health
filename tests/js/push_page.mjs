#!/usr/bin/env node
// Runs the "Phone shortcuts" block of app/static/js/views/settings.js (Settings -> Your data; docs/dev/research/12-phone-push-tokens.md
// section 4.4) against a tiny fake page and a fake server, and prints what happened as JSON, so pytest (tests/test_push_ui.py) can check
// the behaviour without a browser: what the person is shown in the demo, while the admin switch is off and on, the token that is shown
// once with its address and Copy, the list, Revoke, "Delete what it sent" with its count, a name that looks like markup, a password
// prompt that is closed, a list that cannot be loaded. The block is cut out of the view by its markers; the helpers it uses (h, clear,
// action, linkBox, confirm, ...) are stand-ins with the same contract as js/core.js and the view's own.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const source = readFileSync(join(ROOT, 'app', 'static', 'js', 'views', 'settings.js'), 'utf8');
const code = source.slice(source.indexOf('  // push block (begin)'), source.indexOf('  // push block (end)'));

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this.textContent = ''; this.disabled = false; this.value = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'object' && k && k.nodeType ? k : new Text(String(k))); }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  focus() { page.focused = this.attrs.id || this.attrs['aria-label'] || this.tag; }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({ key: 'x', preventDefault() {} }); await settle(); }
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
const walk = (el, fn) => { fn(el); if (el.nodeType === 1) el.children.forEach((c) => walk(c, fn)); };
const find = (root, pred) => { const out = []; walk(root, (e) => { if (e.nodeType === 1 && pred(e)) out.push(e); }); return out; };
const buttons = (root, label) => find(root, (e) => e.tag === 'button' && text(e) === label);

const log = { calls: [], toasts: [], copied: [], confirms: [], qr: [] };
// js/views/two_step.js qrSvg: draws the pairing link as an SVG; null stands for a page where the QR module is missing
let twoStep = { async qrSvg(url, label) { log.qr.push([url, label]); return h('svg', { role: 'img', 'aria-label': label }); } };
let isAdmin = false;
let answers = {};
const A = {
  deviceTokens: async () => { log.calls.push(['deviceTokens']); if (answers.listError) throw answers.listError; return answers.list(); },
  createToken: async (b) => { log.calls.push(['createToken', b]); if (answers.createError) throw answers.createError; return answers.created(b); },
  revokeToken: async (id) => { log.calls.push(['revokeToken', id]); },
  deleteTokenRows: async (id) => { log.calls.push(['deleteTokenRows', id]); return answers.deleted(id); },
};
const state = { dayLoadedFor: 'x', trends: {}, summary: {}, plan: { keep: true } };
function action(label, cls, fn, attrs = {}) {
  const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
  btn.handlers.click = [async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    try { await fn(btn); } catch (err) { log.toasts.push(['error', err.message]); } finally { btn.disabled = false; }
  }];
  return btn;
}
const confirm = { inline(host, trigger, opts) { log.confirms.push({ host, trigger, ...opts }); } };
// js/views/settings.js linkBox: a read-only box with the value and a Copy button
function linkBox(url, lines, opts = {}) {
  const input = h('input', { type: 'text', class: 'link-input', readonly: true, value: url });
  const copy = action(opts.copy || 'Copy link', 'primary', async () => { log.copied.push(url); log.toasts.push(['ok', opts.copied]); });
  return h('div', { class: 'link-box', role: 'group', 'aria-label': opts.group }, h('label', { class: 'label' }, opts.label), h('div', { class: 'link-row' }, input, copy), lines.map((t) => h('p', { class: 'hint' }, t)));
}
function selectEl(id, options, value) {
  const sel = h('select', { id }, options.map(([v, label]) => h('option', { value: v }, label)));
  sel.value = String(value);
  return sel;
}
let learn = null;
function build(MOCK) {
  page.byId = {};
  const context = vm.createContext({
    h, clear, action, A, state, confirm, linkBox, selectEl, MOCK, KH: { get learn() { return learn; }, get twoStep() { return twoStep; } }, window: { location: { origin: 'https://food.example.org' } },
    toast: (m, t) => log.toasts.push([t || '', m]), subtitle: (t, id) => h('h3', { id }, t), loading: () => h('p', {}, 'Loading…'),
    failed: (err) => h('p', { class: 'form-error' }, `Could not load this: ${err.detail || err.message}`),
    formError: () => h('div', { class: 'form-error' }),
    showFormError: (box, err) => { clear(box); box.append(h('p', {}, typeof err === 'string' ? err : err.detail || err.message)); },
    fmtDate: (s) => `d(${s})`, relTime: (s) => `r(${s})`, isAdmin: () => isAdmin, EXPIRY_LABEL: { 30: '30 days', 90: '90 days', 365: '1 year' },
    console, Number, Promise, String, Array, Object,
  });
  vm.runInContext(`${code}\nglobalThis.pushBlock = pushBlock; globalThis.pushCountsText = pushCountsText; globalThis.pushTokenSub = pushTokenSub; globalThis.pushPairBox = pushPairBox;`, context);
  return context;
}
const item = (over = {}) => ({ id: 1, name: 'Morning weight', prefix: 'khd_AbCd1234', scopes: ['body:write'], created_at: '2026-10-22T07:00:00Z', last_used_at: null,
  expires_at: '2027-01-20T07:00:00Z', revoked_at: null, state: 'active', sent: { weights: 0, readings: 0 }, ...over });
const listOf = (tokens, over = {}) => ({ family: 'device', enabled: true, max_active: 5, expiry_days: [30, 90, 365], default_expiry_days: 90, tokens, ...over });
const reset = () => { log.calls = []; log.toasts = []; log.copied = []; log.confirms = []; log.qr = []; page.focused = null; };

const out = {};

// ---- the demo: no request, the preview's words
{
  const ctx = build(true);
  const block = ctx.pushBlock();
  await settle();
  out.demo = { text: text(block), calls: log.calls.length, form: 'set-push-name' in page.byId, create: 'set-push-create' in page.byId };
}

// ---- the admin switch is off: the section is there and says so
reset();
isAdmin = false;
answers = { list: () => listOf([], { enabled: false }) };
{
  const ctx = build(false);
  const block = ctx.pushBlock();
  await settle();
  out.off = { text: text(block), form: 'set-push-name' in page.byId, create: 'set-push-create' in page.byId, calls: log.calls.map((c) => c[0]), admin: /PUSH_ENABLED/.test(text(block)) };
}
reset();
isAdmin = true;
answers = { list: () => listOf([item({ sent: { weights: 2, readings: 1 } }), item({ id: 2, name: 'Old phone', state: 'revoked', revoked_at: '2026-10-25T07:00:00Z', sent: { weights: 1, readings: 0 } })], { enabled: false }) };
{
  const ctx = build(false);
  const block = ctx.pushBlock();
  await settle();
  out.offWithTokens = { text: text(block), admin: /PUSH_ENABLED/.test(text(block)), form: 'set-push-name' in page.byId, revoke: buttons(block, 'Revoke').length,
    deletes: buttons(block, 'Delete what it sent').length };
}

// ---- on, nothing yet
reset();
isAdmin = false;
answers = { list: () => listOf([]) };
let ctx = build(false);
let block = ctx.pushBlock();
await settle();
const nameInput = page.byId['set-push-name'];
out.on = {
  text: text(block), calls: log.calls.map((c) => c[0]), name: { type: nameInput.attrs.type, maxlength: nameInput.attrs.maxlength },
  expiry: { value: page.byId['set-push-expiry'].value, options: page.byId['set-push-expiry'].children.map((o) => [o.attrs.value, text(o)]) },
  canLog: 'set-token-can-log' in page.byId, recipe: text(page.byId['set-push-recipe']), recipeLink: find(block, (e) => e.tag === 'a').length, admin: /PUSH_ENABLED/.test(text(block)),
};

// ---- the handbook link, where the handbook is served
learn = { info: () => ({ links: { pages: { weight_and_blood_pressure: { path: 'app/weight-and-blood-pressure/', title: 'Weight and blood pressure' } } } }), href: (p) => `/learn/${p}` };
ctx = build(false);
block = ctx.pushBlock();
await settle();
{
  const [a] = find(block, (e) => e.tag === 'a');
  out.recipeLink = { href: a.attrs.href, target: a.attrs.target, rel: a.attrs.rel, text: text(a) };
}
learn = null;

// ---- making a token
ctx = build(false);
block = ctx.pushBlock();
await settle();
reset();
await page.byId['set-push-create'].handlers.click[0]();
out.emptyName = { calls: log.calls.length, message: text(find(block, (e) => e.attrs.class === 'form-error' && e.children.length)[0]), focused: page.focused };
const made = { id: 7, name: 'Morning weight', prefix: 'khd_AbCd1234', scopes: ['body:write'], created_at: '2026-10-22T07:00:00Z', last_used_at: null,
  expires_at: '2027-10-22T07:00:00Z', revoked_at: null, state: 'active', sent: { weights: 0, readings: 0 }, token: 'khd_SECRETSECRETSECRETSECRETSECRETSECRETSECRET1',
  pair_url: 'kidneyhealthsync://pair?v=1&server=https%3A%2F%2Ffood.example.org&token=khd_SECRETSECRETSECRETSECRETSECRETSECRETSECRET1' };
answers = { list: () => listOf([item({ id: 7, expires_at: made.expires_at })]), created: () => made };
page.byId['set-push-name'].value = '  Morning weight ';
page.byId['set-push-expiry'].value = '365';
reset();
await page.byId['set-push-create'].handlers.click[0]();
{
  const newBox = find(block, (e) => e.attrs.role === 'group' && e.attrs['aria-label'] === 'New token')[0];
  const addressBox = find(block, (e) => e.attrs.role === 'group' && e.attrs['aria-label'] === 'Address to send to')[0];
  const inputs = (box) => find(box, (e) => e.tag === 'input').map((e) => e.attrs.value);
  await settle();
  const pairBox = find(block, (e) => e.attrs.role === 'group' && e.attrs['aria-label'] === 'Pair the iPhone app')[0];
  out.pair = { qr: log.qr.slice(), text: text(pairBox), svg: find(pairBox, (e) => e.tag === 'svg').length,
    order: find(block, (e) => e.attrs.role === 'group').map((e) => e.attrs['aria-label']) };
  out.created = {
    calls: log.calls, token: inputs(newBox), address: inputs(addressBox), tokenText: text(newBox), addressText: text(addressBox),
    copyButtons: [buttons(newBox, 'Copy token').length, buttons(addressBox, 'Copy address').length], list: text(page.byId['set-push-list']),
  };
  await buttons(newBox, 'Copy token')[0].handlers.click[0]();
  await buttons(addressBox, 'Copy address')[0].handlers.click[0]();
  out.copied = { copied: log.copied, toasts: log.toasts.slice(-2) };
}
// the token is shown by one draw only
reset();
page.focused = null;
{
  const revoke = buttons(block, 'Revoke')[0];
  await revoke.handlers.click[0]();
  const asked = log.confirms[0];
  out.revokeAsk = { message: asked.message, confirmText: asked.confirmText, host: asked.host.attrs.class, trigger: text(asked.trigger) };
  answers.list = () => listOf([item({ id: 7, state: 'revoked', revoked_at: '2026-10-22T08:00:00Z' })]);
  const done = await asked.onConfirm();
  out.revoked = { done, calls: log.calls, toast: log.toasts[log.toasts.length - 1], text: text(block), tokenStillShown: text(block).includes('SECRETSECRET'),
    boxes: find(block, (e) => e.attrs.role === 'group').length };
}

// ---- the list, Delete what it sent, and a name that looks like markup
reset();
answers = { list: () => listOf([
  item({ id: 1, name: '<img src=x onerror=alert(1)> & "quotes"', sent: { weights: 2, readings: 1 }, last_used_at: '2026-10-23T07:00:00Z' }),
  item({ id: 2, name: 'Evening cuff', sent: { weights: 0, readings: 1 } }),
  item({ id: 3, name: 'Quiet one' }),
  item({ id: 4, name: 'Expired one', state: 'expired', sent: { weights: 1, readings: 0 } }),
]), deleted: () => ({ deleted: { weights: 2, readings: 1 } }) };
ctx = build(false);
block = ctx.pushBlock();
await settle();
{
  const list = page.byId['set-push-list'];
  const rows = list.children.map((li) => ({ title: text(find(li, (e) => e.attrs.class === 'row-title')[0]), sub: text(find(li, (e) => e.attrs.class === 'row-sub')[0]),
    buttons: find(li, (e) => e.tag === 'button').map((b) => text(b)) }));
  out.list = { rows, tags: (() => { const tags = new Set(); walk(list, (e) => { if (e.nodeType === 1) tags.add(e.tag); }); return [...tags].sort(); })(),
    attrs: (() => { const names = new Set(); walk(block, (e) => { if (e.nodeType === 1) Object.keys(e.attrs).forEach((k) => names.add(k)); }); return [...names].sort(); })(), focusTarget: null };
}
reset();
{
  const del = buttons(block, 'Delete what it sent')[0];
  await del.handlers.click[0]();
  const asked = log.confirms[0];
  out.deleteAsk = { message: asked.message, confirmText: asked.confirmText, calls: log.calls.length };
  const done = await asked.onConfirm();
  out.deleted = { done, calls: log.calls.filter((c) => c[0] !== 'deviceTokens'), toast: log.toasts[log.toasts.length - 1], state: { ...state }, focused: page.focused };
}
state.dayLoadedFor = 'x'; state.trends = {}; state.summary = {};

// ---- five active tokens: no form
reset();
answers = { list: () => listOf([1, 2, 3, 4, 5].map((id) => item({ id, name: `T${id}` }))) };
ctx = build(false);
block = ctx.pushBlock();
await settle();
out.full = { text: text(page.byId['set-push-full']), form: 'set-push-name' in page.byId };

// ---- a password prompt that is closed, a refusal, a list that cannot be loaded after a token was made
reset();
answers = { list: () => listOf([]), createError: Object.assign(new Error('cancelled'), { cancelled: true, handled: true }) };
ctx = build(false);
block = ctx.pushBlock();
await settle();
page.byId['set-push-name'].value = 'Phone';
await page.byId['set-push-create'].handlers.click[0]();
out.cancelled = { calls: log.calls.map((c) => c[0]), errors: find(block, (e) => e.attrs.class === 'form-error' && e.children.length).length, tokenShown: text(block).includes('khd_') };
answers.createError = Object.assign(new Error('x'), { detail: 'You have 5 active tokens, the most allowed. Revoke one first.' });
await page.byId['set-push-create'].handlers.click[0]();
out.refused = { errors: find(block, (e) => e.attrs.class === 'form-error' && e.children.length).map((e) => text(e)) };
answers.createError = null;
answers.created = () => made;
answers.listError = null;
{
  // the token is made, then the list fails to load: the token is still shown
  let first = true;
  answers.list = () => { if (first) { first = false; return listOf([]); } throw Object.assign(new Error('boom'), { detail: 'The server could not answer.' }); };
  ctx = build(false);
  block = ctx.pushBlock();
  await settle();
  page.byId['set-push-name'].value = 'Phone';
  answers.listError = null;
  const original = A.deviceTokens;
  A.deviceTokens = async () => { throw Object.assign(new Error('boom'), { detail: 'The server could not answer.' }); };
  await page.byId['set-push-create'].handlers.click[0]();
  A.deviceTokens = original;
  out.listFailsAfterCreate = { text: text(block) };
}

// ---- the helpers
{
  const c = ctx.pushCountsText;
  out.counts = [c({ weights: 0, readings: 0 }), c({ weights: 1, readings: 0 }), c({ weights: 0, readings: 1 }), c({ weights: 2, readings: 3 }), c(null), c({})];
}

// ---- the QR code: none for a server without an https:// address, words when the QR module cannot draw
{
  const noLink = ctx.pushPairBox({ ...made, pair_url: null });
  twoStep = { qrSvg: async () => { throw new Error('module failed'); } };
  const failedBox = ctx.pushPairBox(made);
  await settle();
  twoStep = null;
  const missing = ctx.pushPairBox(made);
  await settle();
  out.pairless = { noLink: text(noLink), noLinkSvg: find(noLink, (e) => e.tag === 'svg').length, failed: text(failedBox), missing: text(missing) };
}

console.log(JSON.stringify(out));
