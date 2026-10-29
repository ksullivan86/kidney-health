// Runs the real code behind a reliability fix (ROADMAP item 1, the other screens that save) against a tiny fake page.
// core.js toast(): an open sheet is a modal dialog, drawn above the page, and the page under it is inert. A toast left on the
// page is hidden under the sheet and not read out, so the toast goes into the open sheet, and back to the page on close.
// Only the toast part of core.js and its setupDialog() are run (the rest of core.js needs a whole page).
// The weight card while a day loads is tests/js/body_day_loading.test.mjs.
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
