// Run both real shopping views with delayed server replies. No external service is called.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

function setup(kind) {
  const page = makePage();
  const calls = [], tabs = [], toasts = [];
  const instacart = kind === 'instacart';
  const prefix = instacart ? 'instacart' : 'list-send';
  const dlg = page.$(instacart ? '#sheet-instacart' : '#sheet-list-send');
  const KH = {
    ...page, flags: { MOCK: false },
    h(tag, attrs, ...children) {
      const el = page.h(tag, attrs, ...children);
      // Like a real checkbox, checked="" sets the checked property initially.
      if (attrs?.checked) el.checked = true;
      return el;
    },
    request(method, path, body) {
      const d = deferred(); calls.push({ method, path, body, ...d }); return d.promise;
    },
    toast: (msg) => toasts.push(msg), toastError: (err) => toasts.push(err.message),
    sheets: { setup() {}, open(el) { el.showModal(); }, onSubmit(form, fn) { form.addEventListener('submit', fn); } },
  };
  const window = { KH, open: (...args) => tabs.push(args) };
  vm.runInNewContext(readFileSync(new URL(`../../app/static/js/views/${instacart ? 'instacart' : 'list_sync'}.js`, import.meta.url), 'utf8'),
    { window, document: page.document, console, setTimeout, clearTimeout }, { filename: `${kind}.js` });
  const view = instacart ? KH.instacart : KH.listSync;
  const open = (start = '2026-11-02') => (instacart ? view.open : view.openSend)({ start, end: start, checks: new Set() });
  const preview = (id = 1, text = 'Rice: 1 serving') => ({
    title: 'Shopping list', ready: true, app_name: 'Grocy', list_name: 'Weekly',
    items: [{ food_id: id, name: text, amount: '1 serving', text }],
  });
  const ready = async () => { const p = open(); calls.at(-1).resolve(preview()); await p; };
  const submit = () => { page.$(`#${prefix}-form`).fire('submit'); };
  const success = () => instacart ? { url: 'https://www.instacart.com/list/one', items: 1 } : { sent: 1 };
  return { page, calls, tabs, toasts, view, dlg, open, preview, ready, submit, success,
    go: page.$(`#${prefix}-go`), body: page.$(`#${prefix}-body`) };
}

for (const kind of ['instacart', 'list-sync']) {
  test(`${kind}: an older preview cannot mix foods and dates after reopening`, async () => {
    const s = setup(kind);
    const a = s.open(); s.dlg.close();
    const b = s.open('2026-11-09');
    s.calls[1].resolve(s.preview(2, 'Apples: 2 servings')); await b;
    s.calls[0].resolve(s.preview()); await a;
    assert.match(s.page.text(s.body), /Apples/);
    assert.doesNotMatch(s.page.text(s.body), /Rice/);
    s.submit();
    const sent = s.calls.at(-1);
    assert.equal(sent.body.start, '2026-11-09');
    assert.deepEqual(Array.from(sent.body.food_ids), [2]);
    sent.resolve(s.success()); await settle();
  });

  test(`${kind}: an old preview failure does not replace the new preview`, async () => {
    const s = setup(kind);
    const a = s.open(); s.dlg.close(); const b = s.open('2026-11-09');
    s.calls[1].resolve(s.preview(2, 'Apples')); await b;
    s.calls[0].reject(new Error('Old preview failed')); await a;
    assert.match(s.page.text(s.body), /Apples/);
    assert.doesNotMatch(s.page.text(s.body), /Old preview failed/);
  });

  test(`${kind}: closing invalidates the preview before it answers`, async () => {
    const s = setup(kind); const p = s.open(); s.dlg.close();
    s.calls[0].resolve(s.preview()); await p;
    assert.doesNotMatch(s.page.text(s.body), /Rice/);
    assert.equal(s.go.disabled, true);
    s.submit(); assert.equal(s.calls.length, 1, 'a closed sheet cannot send');
  });

  test(`${kind}: the latest preview failure stays visible and a new open retries`, async () => {
    const s = setup(kind); const p = s.open();
    s.calls[0].reject(new Error('Current preview failed')); await p;
    assert.match(s.page.text(s.body), /Current preview failed/);
    assert.equal(s.go.disabled, true);
    s.dlg.close(); await s.ready(); assert.equal(s.go.disabled, false);
  });

  for (const outcome of ['success', 'error', 'rejection']) {
    test(`${kind}: a late send ${outcome} leaves a reopened sheet alone`, async () => {
      const s = setup(kind); await s.ready(); s.submit();
      const send = s.calls.at(-1);
      s.dlg.close(); const next = s.open('2026-11-09');
      s.calls.at(-1).resolve(s.preview(2, 'Apples')); await next;
      if (outcome === 'rejection') send.reject(new Error('Old send failed'));
      else send.resolve(outcome === 'success' ? s.success() : { error: 'timeout', message: 'Old send timed out' });
      await settle();
      assert.equal(s.dlg.open, true);
      assert.match(s.page.text(s.body), /Apples/);
      assert.deepEqual(s.tabs, []);
      assert.deepEqual(s.toasts, []);
      assert.equal(s.go.disabled, false, 'the original send released its lock');
      assert.equal(s.go.hidden, false);
    });
  }

  test(`${kind}: one send stays in flight across reopening and checkbox changes`, async () => {
    const s = setup(kind); await s.ready(); s.submit(); const send = s.calls.at(-1);
    assert.equal(s.go.disabled, true);
    s.dlg.close(); const next = s.open('2026-11-09');
    s.calls.at(-1).resolve(s.preview(2, 'Apples')); await next;
    const box = s.body.querySelector('input'); box.fire('change');
    assert.equal(s.go.disabled, true);
    s.submit(); assert.equal(s.calls.filter((c) => c.path.endsWith('/send')).length, 1);
    send.resolve(s.success()); await settle();
    assert.equal(s.go.disabled, false);
    s.submit(); const second = s.calls.at(-1);
    assert.equal(second.body.start, '2026-11-09');
    assert.deepEqual(Array.from(second.body.food_ids), [2]);
    second.resolve(s.success()); await settle();
  });

  test(`${kind}: a current send failure preserves choices and permits retry`, async () => {
    const s = setup(kind); await s.ready(); s.submit();
    s.calls.at(-1).reject(new Error('Current send failed')); await settle();
    assert.equal(s.dlg.open, true); assert.equal(s.go.disabled, false);
    assert.match(s.page.text(s.body), /Rice/); assert.deepEqual(s.toasts, ['Current send failed']);
    s.submit(); s.calls.at(-1).resolve(s.success()); await settle();
    if (kind === 'instacart') { assert.equal(s.tabs.length, 1); assert.equal(s.go.hidden, true); }
    else { assert.equal(s.dlg.open, false); assert.match(s.toasts.at(-1), /Sent 1 item/); }
  });

  test(`${kind}: a delayed status cannot show a Send button for an empty week`, async () => {
    const s = setup(kind); const btn = s.page.h('button', {});
    const p = s.view.planButton(btn, true);
    await s.view.planButton(btn, false);
    s.calls[0].resolve({ enabled: true, can_use: true, connection: { app: 'grocy' }, apps: [{ id: 'grocy', name: 'Grocy' }] });
    await p;
    assert.equal(btn.hidden, true);
  });
}
