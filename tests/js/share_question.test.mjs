// A share question and its Accept button must belong to the same, current link.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const codeA = 'a'.repeat(16) + '.' + 'b'.repeat(43);
const codeB = 'c'.repeat(16) + '.' + 'd'.repeat(43);
const ana = { id: 1, name: 'Ana', username: 'ana', areas: ['food'] };
const sam = { id: 2, name: 'Sam', username: 'sam', areas: ['food'] };
const text = (node) => typeof node === 'string' ? node : (node?.children || []).map(text).join('');

function setup() {
  const nodes = new Map(), requests = [], timers = [], opened = [], toasts = [];
  function h(tag = '', attrs = {}, ...children) {
    const node = { tag, attrs, children: children.flat(Infinity).filter((v) => v != null), dataset: {}, handlers: {},
      hidden: false, disabled: false, focused: 0, open: false,
      append(...more) { this.children.push(...more.flat(Infinity)); },
      addEventListener(kind, fn) { this.handlers[kind] = fn; }, focus() { ++this.focused; },
      close() { this.open = false; this.handlers.close?.(); },
    };
    Object.defineProperty(node, 'textContent', { get() { return text(this); }, set(v) { this.children = [String(v)]; } });
    return node;
  }
  const $ = (id) => {
    if (!nodes.has(id)) nodes.set(id, h());
    return nodes.get(id);
  };
  const KH = {
    $, h, state: {}, flags: { MOCK: false }, util: {}, views: { visit: { openShared: (person) => opened.push(person) } },
    sheets: { setup() {}, open(dlg) { dlg.open = true; } }, toast: (s) => toasts.push(s),
    clear(node) { node.children = []; return node; },
    request: (method, path, body) => new Promise((resolve, reject) => requests.push({ method, path, body, resolve, reject })),
  };
  const location = { hash: '', pathname: '/', search: '' };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, location, history: { replaceState() {} },
    setTimeout: (fn) => timers.push(fn), console });
  vm.runInContext(readFileSync(new URL('../../app/static/js/views/sharing.js', import.meta.url), 'utf8'), context);
  const open = (code) => { location.hash = '#/share/' + code; KH.sharing.takeLink(); return KH.sharing.openPending(); };
  const info = (code) => requests.find((r) => r.path.endsWith('/info') && r.body.code === code);
  const accepts = () => requests.filter((r) => r.path.endsWith('/accept'));
  return { $, open, info, accepts, timers, opened, toasts, dlg: $('#sheet-share'), accept: $('#share-accept') };
}

for (const outcome of ['resolve', 'reject']) {
  test(`old link info ${outcome} cannot replace the latest question and Accept code`, async () => {
    const s = setup();
    const first = s.open(codeA), second = s.open(codeB);
    s.info(codeB).resolve(sam);
    await second;
    s.info(codeA)[outcome](outcome === 'resolve' ? ana : { detail: 'Old link failed' });
    await first;
    assert.match(s.$('#share-question').textContent, /^Sam/);
    assert.equal(s.accept.dataset.code, codeB);
    assert.equal(s.accept.hidden, false);
    assert.equal(s.$('#share-error').hidden, true);
  });
}

test('checking a new link clears the old Accept code and cannot accept the previous link', async () => {
  const s = setup();
  const first = s.open(codeA);
  s.info(codeA).resolve(ana); await first;
  const second = s.open(codeB);
  assert.equal(s.accept.dataset.code, undefined);
  assert.equal(s.accept.hidden, true);
  await s.accept.handlers.click();
  assert.equal(s.accepts().length, 0);
  s.info(codeB).resolve(sam); await second;
  assert.equal(s.accept.dataset.code, codeB);
});

test('closing while info is pending cannot restore an Accept code or steal focus', async () => {
  const s = setup();
  const pending = s.open(codeA);
  s.dlg.close();
  s.info(codeA).resolve(ana); await pending;
  for (const timer of s.timers) timer();
  assert.equal(s.accept.dataset.code, undefined);
  assert.equal(s.accept.focused, 0);
  assert.equal(s.accept.hidden, true);
});

test('a queued focus callback does not focus a closed question', async () => {
  const s = setup();
  const pending = s.open(codeA);
  s.info(codeA).resolve(ana); await pending;
  s.dlg.close();
  for (const timer of s.timers) timer();
  assert.equal(s.accept.focused, 0);
});

test('a delayed close event from the previous opening does not clear a reopened question', async () => {
  const s = setup();
  const first = s.open(codeA);
  s.info(codeA).resolve(ana); await first;
  s.dlg.open = false; // close event is queued by the browser, rather than delivered immediately
  const second = s.open(codeB);
  s.info(codeB).resolve(sam); await second;
  s.dlg.handlers.close(); // the old queued event arrives after the dialog reopened
  assert.equal(s.accept.dataset.code, codeB);
  assert.equal(s.accept.hidden, false);
});

for (const outcome of ['resolve', 'reject']) {
  test(`an old acceptance ${outcome} cannot dismiss or change a newer question`, async () => {
    const s = setup();
    const first = s.open(codeA);
    s.info(codeA).resolve(ana); await first;
    const accepting = s.accept.handlers.click();
    const second = s.open(codeB);
    s.info(codeB).resolve(sam); await second;
    s.accepts()[0][outcome](outcome === 'resolve' ? ana : { detail: 'Old acceptance failed' });
    await accepting;
    assert.equal(s.dlg.open, true);
    assert.match(s.$('#share-question').textContent, /^Sam/);
    assert.equal(s.accept.dataset.code, codeB);
    assert.equal(s.$('#share-error').hidden, true);
    assert.equal(s.opened.length, 0);
  });
}

test('an explicitly accepted current question still accepts its displayed link once', async () => {
  const s = setup();
  const pending = s.open(codeB);
  s.info(codeB).resolve(sam); await pending;
  const accepting = s.accept.handlers.click();
  await s.accept.handlers.click(); // duplicate click while disabled
  assert.equal(s.accepts().length, 1);
  assert.equal(s.accepts()[0].body.code, codeB);
  s.accepts()[0].resolve(sam); await accepting;
  assert.equal(s.dlg.open, false);
  assert.equal(s.accept.dataset.code, undefined);
  assert.equal(s.opened[0].id, sam.id);
});
