import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/careplan.js', import.meta.url), 'utf8');
const start = source.indexOf('  function toolsCard(');
const end = source.indexOf('  // The person\'s shopping list', start);
assert.ok(start > 0 && end > start);

function setup() {
  const page = makePage(); const confirmations = [], clears = [], batches = [], toasts = [];
  let draws = 0;
  const p = { id: 1, name: 'Ana', may_plan: true };
  const rt = {
    clearPlanned(from, to) { const d = deferred(); clears.push({ from, to, ...d }); return d.promise; },
    batch(entries) { const d = deferred(); batches.push({ entries, ...d }); return d.promise; },
  };
  const context = vm.createContext({
    ...page, h(tag, attrs, ...kids) { const el = page.h(tag, attrs, ...kids); if (attrs?.value != null) el.value = String(attrs.value); return el; },
    current: { date: '2026-11-04', person: p }, KH: { views: {} }, weekStartOf: (date) => date,
    nameOf: (p) => p.name, fmtMonthDay: String, fmtDateLong: String,
    MEAL_LABEL: {}, BATCH: 40, toast: (m) => toasts.push(m), confirm: { inline: (_host, _btn, opts) => confirmations.push(opts) },
    draw: () => { draws += 1; }, saveFailed: () => (e) => toasts.push(e.message), gone: (_e, fn) => fn(), failText: (e) => e.message,
  });
  vm.runInContext(source.slice(start, end) + '\nglobalThis.functions = { toolsCard, showPlan };', context);
  const tools = context.functions.toolsCard(p, rt); page.root.append(tools);
  const preview = page.$('#care-plan-preview');
  const show = (n) => context.functions.showPlan(p, rt, { status: 'ok', days: [], apply: { entries: Array.from({ length: n }, (_, i) => ({ food_id: i + 1, date: '2026-12-01' })) } }, preview);
  return { ...page, confirmations, clears, batches, toasts, show, preview, current: context.current, draws: () => draws };
}

for (const field of ['start', 'end', 'both']) {
  test(`Clear uses the confirmed dates after changing ${field}`, async () => {
    const s = setup();
    s.$('#care-clear-start').value = '2026-11-04'; s.$('#care-clear-end').value = '2026-11-06';
    s.$('#care-clear').click();
    if (field !== 'end') s.$('#care-clear-start').value = '2026-12-01';
    if (field !== 'start') s.$('#care-clear-end').value = '2026-12-31';
    const result = s.confirmations[0].onConfirm();
    assert.equal(s.clears[0].from, '2026-11-04'); assert.equal(s.clears[0].to, '2026-11-06');
    s.clears[0].resolve({ deleted: 2 }); await result;
  });
}

test('a new confirmation takes the newly chosen dates', async () => {
  const s = setup(); s.$('#care-clear').click();
  s.$('#care-clear-start').value = '2026-12-01'; s.$('#care-clear-end').value = '2026-12-03'; s.$('#care-clear').click();
  const result = s.confirmations[1].onConfirm();
  assert.equal(s.clears[0].from, '2026-12-01'); assert.equal(s.clears[0].to, '2026-12-03');
  s.clears[0].resolve({ deleted: 0 }); await result;
});

for (const succeeded of [0, 1]) {
  test(`an uncertain batch failure after ${succeeded} confirmed batches cannot resend the preview`, async () => {
    const s = setup(); s.show(65); const apply = s.$('#care-plan-apply'); apply.click();
    if (succeeded) { s.batches[0].resolve({}); await settle(); }
    s.batches.at(-1).reject(new Error('The reply was lost')); await settle();
    const count = s.batches.length; apply.click(); await settle();
    assert.equal(s.batches.length, count, 'the same preview cannot submit any batch twice');
    assert.equal(apply.disabled, true);
    const review = s.button(s.preview, 'Review the plan'); assert.ok(review); review.click();
    assert.equal(s.draws(), 1);
    assert.equal(s.current.date, '2026-12-01');
  });
}

test('a normal multi-batch save still applies every entry once', async () => {
  const s = setup(); s.show(65); s.$('#care-plan-apply').click();
  s.batches[0].resolve({}); await settle(); s.batches[1].resolve({}); await settle();
  assert.deepEqual(s.batches.map((b) => b.entries.length), [40, 25]); assert.equal(s.draws(), 1);
  assert.ok(s.toasts.some((m) => m.includes('65 planned foods added')));
});

test('a second click during a pending write does not send another batch', async () => {
  const s = setup(); s.show(1); s.$('#care-plan-apply').click(); s.$('#care-plan-apply').click();
  assert.equal(s.batches.length, 1); s.batches[0].resolve({}); await settle();
});
