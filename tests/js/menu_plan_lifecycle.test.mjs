import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

function setup() {
  const page = makePage(), calls = [], toasts = [], views = [], reads = [];
  let serial = 0;
  const form = page.$('#menuplan-form'); form.tag = 'form'; page.$('#sheet-menuplan').append(form);
  for (const id of ['menuplan-date', 'menuplan-groups', 'menuplan-save']) form.append(page.$(`#${id}`));
  const KH = { ...page, state: {}, toast: (...args) => toasts.push(args),
    router: { show: (view) => views.push(view) },
    sheets: { setup() {}, open(dlg) { dlg.open = true; }, onSubmit(form, fn) { form.addEventListener('submit', fn); } },
    ui: { KEY_NUMBERS: [], ROW_NUMBERS: [], PLAN_CHIPS: [], LEVEL_TEXT: {}, ratingIcon: () => page.h('span'),
      scaledNutrients: () => ({}), impactOn: () => [], unknownOf: () => 0, atLeast: String },
    util: { todayStr: () => '2026-11-11', addDays: (d, n) => new Date(Date.parse(`${d}T12:00:00Z`) + n * 86400000).toISOString().slice(0, 10),
      fmtDateLong: String, weekStartOf: (d) => d },
    request(method, path, body) {
      if (method === 'GET') return Promise.resolve({ foods: [1, 2].map((id) => ({
        id, fdc_id: id, source: 'builtin', name: `Fruit ${id}`, serving_desc: 'one', nutrients: {}, flags: [],
      })) });
      const d = deferred(); calls.push({ method, path, body: structuredClone(body), ...d }); return d.promise;
    },
    api: { range: async () => ({ days: [] }), day(date) { const d = deferred(); reads.push({ date, ...d }); return d.promise; } },
  };
  const context = vm.createContext({ KH, ...page, location: { hash: '' }, history: {}, console, Uint8Array,
    crypto: { randomUUID: () => `key-${++serial}` }, addEventListener() {} });
  vm.runInContext('globalThis.window = globalThis;', context);
  for (const file of ['engine/rules.js', 'engine/menu_link.js', 'views/menuplan.js']) {
    vm.runInContext(readFileSync(new URL(`../../app/static/js/${file}`, import.meta.url), 'utf8'), context);
  }
  return { ...page, KH, calls, toasts, views, reads,
    async open(id = 1) { await KH.menuPlan.openLink(`#plan-menu?items=b${id}x1`); await settle(); },
    async submit() { form.fire('submit'); await settle(); },
    close() { page.$('#sheet-menuplan').close(); },
  };
}

for (const outcome of ['success', 'error', 'handled']) {
  test(`late ${outcome} leaves a reopened menu draft alone`, async () => {
    const s = setup(); await s.open(); await s.submit(); s.close(); await s.open(2);
    const rows = s.KH.menuPlan.state.rows;
    if (outcome === 'success') s.calls[0].resolve({ results: [{ result: 'created' }] });
    else s.calls[0].reject({ detail: 'Old plan error', handled: outcome === 'handled' });
    await settle();
    assert.equal(s.$('#sheet-menuplan').open, true);
    assert.equal(s.KH.menuPlan.state.rows, rows);
    assert.equal(s.$('#menuplan-error').hidden, true);
    assert.deepEqual(s.views, []);
    assert.equal(s.$('#menuplan-save').disabled, false);
    if (outcome === 'error') assert.equal(s.toasts.at(-1)[1], 'error');
  });
}
test('reopening cannot send a second batch while the original write is pending', async () => {
  const s = setup(); await s.open(); await s.submit(); s.close(); await s.open(2);
  await s.submit(); assert.equal(s.calls.length, 1);
  assert.equal(s.$('#menuplan-save').disabled, true);
  assert.equal(s.$('#menuplan-date').disabled, false);
  s.calls[0].resolve({ results: [{ result: 'created' }] }); await settle();
  await s.submit(); assert.equal(s.calls.length, 2);
  assert.equal(s.calls[1].body.entries[0].food_id, 2);
});
test('submitted date and choices freeze, and a failed retry preserves its client IDs', async () => {
  const s = setup(); await s.open(); await s.submit(); await s.submit();
  assert.equal(s.calls.length, 1);
  assert.equal(s.$('#menuplan-date').disabled, true);
  assert.ok(s.$('#menuplan-groups').querySelectorAll('input').every((el) => el.disabled));
  s.calls[0].reject({ detail: 'Try again' }); await settle();
  assert.equal(s.$('#sheet-menuplan').open, true);
  assert.equal(s.$('#menuplan-date').disabled, false);
  assert.equal(s.$('#menuplan-error').textContent, 'Try again');
  await s.submit(); assert.deepEqual(s.calls[1].body, s.calls[0].body);
});
test('the current successful menu still closes and navigates to its planned date', async () => {
  const s = setup(); await s.open(); await s.submit();
  s.calls[0].resolve({ results: [{ result: 'created' }] }); await settle();
  assert.equal(s.$('#sheet-menuplan').open, false);
  assert.deepEqual(s.views, ['plan']);
  assert.equal(s.KH.state.planStart, '2026-11-12');
});
test('a day reply from an old opening cannot fill the new opening', async () => {
  const s = setup(); await s.open(); s.close(); await s.open(2);
  s.reads[0].resolve({ old: true }); await settle();
  assert.equal(s.KH.menuPlan.state.day, null);
  s.reads[1].resolve(null); await settle();
});
test('an old day reply is ignored while the next link is still loading', async () => {
  const s = setup(); await s.open();
  const loading = deferred(), foods = await s.KH.request('GET');
  s.KH.request = () => loading.promise;
  const opening = s.open(2); await settle();
  s.reads[0].resolve({ old: true }); await settle();
  assert.equal(s.KH.menuPlan.state.day, null);
  loading.resolve(foods); await opening;
});
test('closing while the next link loads prevents a late reopen', async () => {
  const s = setup(); await s.open();
  const loading = deferred(); s.KH.api.range = () => loading.promise;
  const opening = s.open(2); await settle(); s.close();
  loading.resolve({ days: [] }); await opening;
  assert.equal(s.$('#sheet-menuplan').open, false);
});
for (const afterOpen of [false, true]) test(`a queued close ${afterOpen ? 'after' : 'before'} the new sheet opens leaves it alone`, async () => {
  const s = setup(); await s.open();
  s.$('#sheet-menuplan').open = false; // Chrome closes now, then dispatches its close event later.
  const opening = s.open(2);
  if (afterOpen) await opening;
  const token = s.KH.menuPlan.state.token;
  s.$('#sheet-menuplan').fire('close');
  assert.equal(s.KH.menuPlan.state.token, token);
  await opening;
  assert.equal(s.$('#sheet-menuplan').open, true);
  assert.equal(s.KH.menuPlan.state.rows[0].food.id, 2);
});
