// Run the real measurement sheets and number parsers with held writes.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';
const source = readFileSync(new URL('../../app/static/js/views/body.js', import.meta.url), 'utf8');
const start = source.indexOf('  // ---- the sheets: shared parts');
const end = source.indexOf('  // ---- Settings', start);
assert.ok(start >= 0 && end > start);
function setup() {
  const page = makePage(), calls = [], errors = [], loads = [];
  const S = { units: 'lb', shownDate: '2026-11-06', busy: false };
  for (const [type, fields] of [['weight', ['value', 'date', 'time', 'note']], ['bp', ['systolic', 'diastolic', 'pulse', 'date', 'time', 'note']]]) {
    const form = page.$(`#${type}-form`); form.tag = 'form';
    page.$(`#sheet-${type}`).append(form);
    for (const field of fields) { const el = page.$(`#${type}-${field}`); el.tag = field === 'note' ? 'textarea' : 'input'; form.append(el); }
    form.append(page.$(`#${type}-context`));
    const save = page.$(`#${type}-save`); save.tag = 'button'; form.append(save);
  }
  const request = (method) => (...args) => { const d = deferred(); calls.push({ method, args, ...d }); return d.promise; };
  const $ = (sel, scope) => sel === 'input:checked' ? page.$$('input', scope).find((x) => x.checked) : page.$(sel, scope);
  const context = vm.createContext({ ...page, $, S, console,
    h(tag, attrs, ...children) { const el = page.h(tag, attrs, ...children); if (attrs?.value != null) el.value = String(attrs.value); return el; },
    sheets: { open(dlg) { dlg.open = true; }, onSubmit(form, fn) { form.addEventListener('submit', fn); } },
    weightDlg: page.$('#sheet-weight'), bpDlg: page.$('#sheet-bp'), addWeightBtn: page.$('#body-add-weight'), addBpBtn: page.$('#body-add-bp'),
    api: Object.fromEntries(['addWeight', 'updateWeight', 'addBloodPressure', 'updateBloodPressure'].map((name) => [name, request(name)])),
    todayStr: () => '2026-11-06', onDialysis: () => false, learnLink: () => null, flagBlock: () => page.h('p'),
    live() {}, toast: (m, kind) => { if (kind === 'error') errors.push(m); }, toastError: (e) => errors.push(e.message), readingText: (r) => `${r.systolic}/${r.diastolic}`,
    fmtDateShort: String, loadToday: async (d) => loads.push(d), todayBody: page.h('div'), NEEDS_CONNECTION: 'Connection needed',
  });
  vm.runInContext('globalThis.window = globalThis;', context);
  for (const name of ['rules', 'body', 'body_ui']) vm.runInContext(readFileSync(new URL(`../../app/static/js/engine/${name}.js`, import.meta.url), 'utf8'), context);
  vm.runInContext('const R = KH.bodyRules, U = KH.bodyUi;', context);
  vm.runInContext(source.slice(start, end) + '\nglobalThis.openers = {weight: openWeight, bp: openBp};', context);
  const open = (type, edit = false) => {
    const record = type === 'weight' ? { id: 7, kg: 70.23, date: '2026-11-06', context: 'morning', note: 'old' }
      : { id: 8, systolic: 120, diastolic: 80, pulse: 70, date: '2026-11-06', context: 'morning', note: 'old' };
    context.openers[type](edit ? { [type === 'weight' ? 'weight' : 'reading']: record } : {});
    if (!edit) {
      if (type === 'weight') page.$('#weight-value').value = '154.3';
      else { page.$('#bp-systolic').value = '120'; page.$('#bp-diastolic').value = '80'; }
      page.$('input', page.$(`#${type}-context`)).checked = true;
    }
  };
  return { ...page, S, calls, errors, loads, open,
    async submit(type) { page.$(`#${type}-form`).fire('submit'); await settle(); },
    close(type) { page.$(`#sheet-${type}`).close(); },
  };
}
const answer = (type, call) => ({ ...call.args.at(-1), id: type === 'weight' ? 7 : 8 });
for (const type of ['weight', 'bp']) {
  for (const failure of [false, true]) {
    test(`${type}: a late ${failure ? 'validation error' : 'success'} preserves a reopened draft`, async () => {
      const s = setup(); s.open(type); await s.submit(type);
      s.close(type); s.open(type, true); s.$(`#${type}-note`).value = 'Keep this new draft';
      await s.submit(type); assert.equal(s.calls.length, 1);
      assert.equal(s.$(`#${type}-save`).disabled, true);
      if (failure) s.calls[0].reject({ status: 422, detail: 'Old validation error' });
      else s.calls[0].resolve(answer(type, s.calls[0]));
      await settle();
      assert.equal(s.$(`#sheet-${type}`).open, true);
      assert.equal(s.$(`#${type}-note`).value, 'Keep this new draft');
      assert.equal(s.$(`#${type}-error`).hidden, true);
      assert.equal(s.$(`#${type}-save`).disabled, false);
      // the closed sheet's failure is still said, without touching the new draft
      assert.deepEqual(s.errors, failure ? ['An earlier save did not go through. Check it and try again.'] : []);
      await s.submit(type); assert.equal(s.calls.length, 2);
      assert.match(s.calls[1].method, /^update/); s.calls[1].resolve(answer(type, s.calls[1])); await settle();
      assert.equal(s.$(`#sheet-${type}`).open, false);
    });
  }
  test(`${type}: submitted values freeze, duplicate saves stop, a refusal keeps the draft`, async () => {
    const s = setup(); s.open(type, true); await s.submit(type); await s.submit(type);
    assert.equal(s.calls.length, 1);
    assert.equal(s.$(`#${type}-note`).disabled, true);
    assert.equal(s.$(`#${type}-date`).disabled, true);
    s.calls[0].reject({ status: 422, detail: 'Check this value' }); await settle();
    assert.equal(s.$(`#sheet-${type}`).open, true);
    assert.equal(s.$(`#${type}-note`).disabled, false);
    assert.equal(s.$(`#${type}-error`).textContent, 'Check this value');
    assert.equal(s.$(`#${type}-save`).disabled, false);
  });
  test(`${type}: closing a submitted draft leaves the next draft editable while its Save waits`, async () => {
    const s = setup(); s.open(type); await s.submit(type); s.close(type); s.open(type);
    assert.equal(s.$(`#${type}-note`).disabled, false);
    assert.equal(s.$(`#${type}-save`).disabled, true);
    s.calls[0].resolve(answer(type, s.calls[0])); await settle();
    assert.equal(s.$(`#${type}-save`).disabled, false);
  });
}
test('weight: a page unit refresh cannot reinterpret the unit printed on the open draft', async () => {
  const s = setup(); s.open('weight'); s.S.units = 'kg'; await s.submit('weight');
  assert.equal(s.calls[0].args[0].kg, 69.99);
  s.calls[0].resolve(answer('weight', s.calls[0])); await settle();
});
test('weight: a note-only edit preserves the stored hundredth of a kilogram', async () => {
  const s = setup(); s.open('weight', true); s.$('#weight-note').value = 'New note'; await s.submit('weight');
  assert.equal(s.calls[0].args[0], 7); assert.equal(s.calls[0].args[1].kg, 70.23);
  s.calls[0].resolve(answer('weight', s.calls[0])); await settle();
});
