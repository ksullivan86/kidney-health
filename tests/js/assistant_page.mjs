#!/usr/bin/env node
// Runs the "new token" form and the token list of Settings -> Assistant access (app/static/js/views/settings.js; ARCHITECTURE
// "Assistant access tokens") against a tiny fake page and a fake server, and prints what happened as JSON, so pytest
// (tests/test_assistant_ui.py) can check the behaviour without a browser: the two separate ticks (save food and recipes; remember
// tastes), both off by default, what Create sends for each combination, and what the list says a token can do. The section is cut
// out of the view by its markers; the helpers it uses (h, clear, action, selectEl, ...) are stand-ins with the contract of js/core.js
// and the view's own, the same ones tests/js/push_page.mjs uses.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const source = readFileSync(join(ROOT, 'app', 'static', 'js', 'views', 'settings.js'), 'utf8');
const code = source.slice(source.indexOf('  const ASSISTANT_INTRO'), source.indexOf('  // Section: This device'));

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this.textContent = ''; this.disabled = false; this.value = ''; this.checked = false; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { for (const k of kids) this.children.push(typeof k === 'object' && k && k.nodeType ? k : new Text(String(k))); }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  focus() {}
}
const page = { byId: {} };
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

const log = { calls: [] };
const A = {
  createToken: async (b) => { log.calls.push(['createToken', b]); return { id: 9, name: b.name, token: 'kha_NOTSHOWNHERE', scopes: ['assistant:read'] }; },
  tokens: async () => ({ enabled: true, max_active: 5, expiry_days: [30, 90, 365], default_expiry_days: 90, tokens: [] }),
  revokeToken: async () => {},
};
function action(label, cls, fn, attrs = {}) {
  const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
  btn.handlers.click = [async () => { if (btn.disabled) return; btn.disabled = true; try { await fn(btn); } finally { btn.disabled = false; } }];
  return btn;
}
function selectEl(id, options, value) {
  const sel = h('select', { id }, options.map(([v, label]) => h('option', { value: v }, label)));
  sel.value = String(value);
  return sel;
}
function build() {
  page.byId = {};
  const context = vm.createContext({
    h, clear, action, A, selectEl, MOCK: false, state: {}, confirm: { inline() {} }, $: () => null, renderNav() {},
    linkBox: () => h('div', {}), subtitle: (t, id) => h('h3', { id }, t), failed: () => h('p', {}, 'failed'),
    formError: () => h('div', { class: 'form-error' }),
    showFormError: (box, err) => { clear(box); box.append(h('p', {}, typeof err === 'string' ? err : err.detail || err.message)); },
    fmtDate: (s) => `d(${s})`, relTime: (s) => `r(${s})`, isAdmin: () => false, toast() {}, console, Number, Promise, String, Array, Object,
  });
  vm.runInContext(`${code}\nglobalThis.newTokenForm = newTokenForm; globalThis.tokenSub = tokenSub; globalThis.tokenList = tokenList; globalThis.ASSISTANT_INTRO = ASSISTANT_INTRO;`, context);
  return context;
}
const listing = { max_active: 5, expiry_days: [30, 90, 365], default_expiry_days: 90 };
const out = {};

// ---- the form: two separate ticks, both off by default
{
  const ctx = build();
  const form = ctx.newTokenForm(listing, 0);
  const log_ = page.byId['set-token-can-log'];
  const prefs = page.byId['set-token-can-prefs'];
  const labels = find(form, (e) => e.tag === 'label' && e.attrs.class === 'check').map(text);
  out.form = {
    ticks: find(form, (e) => e.tag === 'input' && e.attrs.type === 'checkbox').map((e) => [e.attrs.id, e.checked, e.attrs['aria-describedby']]),
    labels,
    hints: { log: text(page.byId['set-token-can-log-hint']), prefs: text(page.byId['set-token-can-prefs-hint']) },
    intro: ctx.ASSISTANT_INTRO,
    distinct: log_ !== prefs,
  };
}

// ---- what Create sends for each combination of the two ticks
out.sent = [];
for (const [log_, prefs] of [[false, false], [true, false], [false, true], [true, true]]) {
  log.calls = [];
  const ctx = build();
  ctx.newTokenForm(listing, 0);
  page.byId['set-token-name'].value = ' Hermes ';
  page.byId['set-token-can-log'].checked = log_;
  page.byId['set-token-can-prefs'].checked = prefs;
  await page.byId['set-token-create'].handlers.click[0]();
  await settle();
  out.sent.push({ ticked: [log_, prefs], calls: log.calls });
}

// ---- the list says what each token can do
{
  const ctx = build();
  const item = (scopes, over = {}) => ({ id: 1, name: 'T', prefix: 'kha_AbCd1234', scopes, created_at: '2026-10-22T07:00:00Z', last_used_at: null, expires_at: '2027-01-20T07:00:00Z', revoked_at: null, state: 'active', ...over });
  const word = (scopes) => ctx.tokenSub(item(scopes)).split(' · ')[0];
  out.words = {
    read: word(['assistant:read']), log: word(['assistant:read', 'assistant:log']), prefs: word(['assistant:read', 'assistant:prefs']),
    both: word(['assistant:read', 'assistant:log', 'assistant:prefs']), nothing: word([]),
  };
  const rows = ctx.tokenList([item(['assistant:read', 'assistant:prefs'], { name: 'Hermes' })]);
  out.listed = text(rows);
}

console.log(JSON.stringify(out));
