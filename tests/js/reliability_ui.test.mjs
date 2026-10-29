// Runs the real code behind two reliability fixes (ROADMAP item 1, the other screens that save) against a tiny fake page:
//
// * core.js toast(): an open sheet is a modal dialog, drawn above the page, and the page under it is inert. A toast left on the
//   page is hidden under the sheet and not read out, so the toast goes into the open sheet, and back to the page on close.
//   Only the toast part of core.js and its setupDialog() are run (the rest of core.js needs a whole page).
// * views/body.js loadToday(): while another day loads, the weight card never keeps the day before's weights under the new
//   day's heading, and a late answer for a day left behind is never drawn.
//
//   node --test tests/js/reliability_ui.test.mjs        (tests/test_reliability_ui.py runs it under pytest)
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../app/static/js/', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const between = (src, start, end) => {
  const a = src.indexOf(start);
  const b = src.indexOf(end, a);
  assert.ok(a >= 0 && b > a, `core.js still has "${start}" before "${end}"`);
  return src.slice(a, b);
};

// ---- the toast ----------------------------------------------------------------------------------------------------------
class Node {
  constructor(tag, { modal = true } = {}) {
    this.tag = tag; this.children = []; this.parentElement = null; this.open = false; this.modal = modal;
    this.handlers = {}; this.textContent = ''; this.className = '';
    const self = this;
    this.classList = { remove(c) { self.className = self.className.split(' ').filter((x) => x && x !== c).join(' '); } };
  }
  append(...nodes) {
    for (const n of nodes) {
      if (n.parentElement) n.parentElement.children = n.parentElement.children.filter((c) => c !== n);
      n.parentElement = this;
      this.children.push(n);
    }
  }
  contains(n) { for (let p = n; p; p = p.parentElement) if (p === this) return true; return false; }
  matches(sel) { assert.equal(sel, ':modal'); return this.open && this.modal; }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  showModal() { this.open = true; }
  show() { this.open = true; this.modal = false; }
  close() { this.open = false; for (const fn of this.handlers.close || []) fn({}); }
}

function toastPage() {
  const body = new Node('body');
  const toastEl = new Node('div');
  body.append(toastEl);
  const dialogs = [];
  const document = { body, contains: (n) => body.contains(n), activeElement: null };
  const $ = (sel) => { assert.equal(sel, '#toast'); return toastEl; };
  const $$ = (sel, box) => {
    if (sel === 'dialog[open]') return dialogs.filter((d) => d.open);
    assert.ok(box, `unexpected $$(${sel})`);
    return [];
  };
  const src = read('core.js');
  const code = between(src, "const toastEl = $('#toast');", '// Auth hooks')
    + between(src, 'function setupDialog(dlg)', 'function openDialog(')
    + '\n;({ toast, toastError, setupDialog });';
  const context = vm.createContext({ $, $$, document, console: { error() {} }, setTimeout: () => 0, clearTimeout() {},
    dismissConfirm() {} });
  const api = vm.runInContext(code, context);
  const sheet = (opts) => {
    const d = new Node('dialog', opts);
    body.append(d);
    api.setupDialog(d);
    dialogs.push(d);
    return d;
  };
  return { ...api, body, toastEl, sheet };
}

test('a toast with no sheet open is shown on the page', () => {
  const p = toastPage();
  p.toast('Saved', 'ok');
  assert.equal(p.toastEl.parentElement, p.body);
  assert.equal(p.toastEl.textContent, 'Saved');
  assert.match(p.toastEl.className, /\bshow\b/);
});

test('an error while a sheet is open is shown inside the sheet, where it can be seen', () => {
  const p = toastPage();
  const sheet = p.sheet();
  sheet.showModal();
  p.toastError({ detail: 'The server had a problem.' });
  assert.equal(p.toastEl.parentElement, sheet);
  assert.equal(p.toastEl.textContent, 'The server had a problem.');
  assert.match(p.toastEl.className, /\bshow error\b/);
});

test('with a sheet open over another sheet, the toast goes into the top one', () => {
  const p = toastPage();
  const lower = p.sheet();
  const upper = p.sheet();
  lower.showModal();
  upper.showModal();
  p.toast('Could not save');
  assert.equal(p.toastEl.parentElement, upper);
});

test('when the sheet closes, the toast goes back to the page', () => {
  const p = toastPage();
  const sheet = p.sheet();
  sheet.showModal();
  p.toast('Could not save', 'error');
  sheet.close();
  assert.equal(p.toastEl.parentElement, p.body);
  p.toast('Saved', 'ok');
  assert.equal(p.toastEl.parentElement, p.body);
});

test('a dialog that is open but not modal leaves the toast on the page', () => {
  const p = toastPage();
  const d = p.sheet();
  d.show();
  p.toast('Saved', 'ok');
  assert.equal(p.toastEl.parentElement, p.body);
});

// ---- the weight card ----------------------------------------------------------------------------------------------------
const TODAY = '2026-10-29';
const YESTERDAY = '2026-10-28';

function weightCard() {
  const elements = new Map();
  const el = (tag = 'div', attrs = {}, ...children) => ({
    tag, attrs, children: children.flat(Infinity).filter((v) => v != null), value: '', textContent: '', disabled: false,
    append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); },
    addEventListener() {}, setAttribute() {}, focus() {},
  });
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, el());
    return elements.get(id);
  };
  const pending = [];
  const ask = (kind) => (start) => new Promise((resolve, reject) => pending.push({ kind, date: start, resolve, reject }));
  const KH = {
    $, h: el, state: { profile: { dialysis: 'none' } },
    clear(node) { node.children = []; return node; },
    api: { bodyWeights: ask('weights'), bloodPressures: ask('bp'), bodySummary: ask('summary') },
    toast() {}, toastError() {}, sheets: { setup() {}, onSubmit() {}, open() {} }, router: { show() {} },
    ui: { ratingIcon: () => el('span') },
    util: { todayStr: () => TODAY, addDays: (d) => d, fmtDateShort: (d) => d, fmtMonthDay: (d) => d },
  };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, console });
  for (const file of ['rules', 'symptoms', 'body', 'visitprep', 'body_ui']) vm.runInContext(read(`engine/${file}.js`), context);
  vm.runInContext(read('views/body.js'), context);
  const answer = (date, kg) => {
    for (const r of pending.filter((x) => x.date === date && !x.done)) {
      r.done = true;
      if (r.kind === 'weights') r.resolve({ weights: [{ id: kg, date, time: '08:00', kg, context: 'morning', note: '' }] });
      else if (r.kind === 'bp') r.resolve({ readings: [] });
      else r.resolve({ units: 'lb' });
    }
  };
  const fail = (date) => {
    for (const r of pending.filter((x) => x.date === date && !x.done)) {
      r.done = true;
      r.reject(Object.assign(Error('The server had a problem.'), { status: 500 }));
    }
  };
  const text = (node = $('#body-today-body')) => (typeof node === 'string' ? node : node.children.map(text).join(' '));
  return { load: KH.body.today, answer, fail, text, pending };
}

test("while the day before loads, today's weight is not shown under it", async () => {
  const c = weightCard();
  const today = c.load(TODAY);
  c.answer(TODAY, 72);
  await today;
  assert.match(c.text(), /158\.7/);
  const before = c.load(YESTERDAY);
  await Promise.resolve();
  assert.doesNotMatch(c.text(), /158\.7/, c.text());
  assert.match(c.text(), /Loading/);
  c.answer(YESTERDAY, 68);
  await before;
  assert.match(c.text(), /149\.9/);
  assert.doesNotMatch(c.text(), /158\.7/);
});

test('loading the same day again (after a save) keeps its weights on screen until the answer comes', async () => {
  const c = weightCard();
  const first = c.load(TODAY);
  c.answer(TODAY, 72);
  await first;
  const again = c.load(TODAY);
  await Promise.resolve();
  assert.match(c.text(), /158\.7/);
  assert.doesNotMatch(c.text(), /Loading/);
  c.answer(TODAY, 72.5);
  await again;
  assert.match(c.text(), /159\.8/);
});

for (const late of ['an answer', 'an error']) {
  test(`a slow day left behind (${late}) is never drawn over the day shown now`, async () => {
    const c = weightCard();
    const first = c.load(TODAY);
    c.answer(TODAY, 72);
    await first;
    const slow = c.load(YESTERDAY);
    await Promise.resolve();
    const back = c.load(TODAY);
    await Promise.resolve();
    assert.doesNotMatch(c.text(), /149\.9/);
    c.answer(TODAY, 72);
    await back;
    if (late === 'an answer') c.answer(YESTERDAY, 68); else c.fail(YESTERDAY);
    await slow;
    assert.match(c.text(), /158\.7/);
    assert.doesNotMatch(c.text(), /149\.9|could not be loaded/);
  });
}

test('a day that fails to load says so, with Try again, and never shows the other day', async () => {
  const c = weightCard();
  const first = c.load(TODAY);
  c.answer(TODAY, 72);
  await first;
  const before = c.load(YESTERDAY);
  c.fail(YESTERDAY);
  await before;
  assert.match(c.text(), /could not be loaded/);
  assert.match(c.text(), /Try again/);
  assert.doesNotMatch(c.text(), /158\.7/);
});
