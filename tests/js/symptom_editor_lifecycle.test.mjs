// Real symptom sheet handlers with held writes; handbook rules remain the real engine.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';
const source = readFileSync(new URL('../../app/static/js/views/symptoms.js', import.meta.url), 'utf8');
const start = source.indexOf('  // ---- the sheet '), end = source.indexOf('  // ---- Trends', start);
assert.ok(start >= 0 && end > start);
function setup() {
  const page = makePage(), calls = [], errors = [];
  const form = page.$('#symptom-form'); form.tag = 'form'; page.$('#sheet-symptom').append(form);
  for (const field of ['kind', 'label', 'date', 'note']) {
    const el = page.$(`#symptom-${field}`); el.tag = field === 'kind' ? 'select' : field === 'note' ? 'textarea' : 'input'; form.append(el);
  }
  const severity = page.$('#symptom-severity'); form.append(severity);
  for (const value of ['1', '2', '3']) { const el = page.h('input'); el.value = value; severity.append(el); }
  const save = page.$('#symptom-save'); save.tag = 'button'; form.append(save);
  const request = (method) => (...args) => { const d = deferred(); calls.push({ method, args, ...d }); return d.promise; };
  const context = vm.createContext({ ...page,
    $: (sel, scope) => sel === 'input:checked' ? page.$$('input', scope).find((x) => x.checked) : page.$(sel, scope),
    api: { addSymptom: request('add'), updateSymptom: request('update') },
    dlg: page.$('#sheet-symptom'), addBtn: page.$('#symptoms-add'),
    sheets: { open(dlg) { dlg.open = true; }, onSubmit(form, fn) { form.addEventListener('submit', fn); } },
    shownDate: '2026-11-06', todayStr: () => '2026-11-06', flagEl: () => page.h('p'),
    toast: (m, kind) => { if (kind === 'error') errors.push(m); }, live() {}, sevWord: String, fmtDateShort: String, loadToday: async () => {}, toastError: (e) => errors.push(e.message),
  });
  vm.runInContext('globalThis.window = globalThis;', context);
  vm.runInContext(readFileSync(new URL('../../app/static/js/engine/symptoms.js', import.meta.url), 'utf8'), context);
  vm.runInContext('const R = KH.symptomRules;', context);
  vm.runInContext(source.slice(start, end) + '\nglobalThis.openSymptom = openSheet;', context);
  return { ...page, calls, errors,
    open(edit = false) {
      context.openSymptom(edit ? { symptom: { id: 9, symptom: 'itching', severity: 2, date: '2026-11-06', note: 'Existing', label: '' } } : {});
      if (!edit) { page.$('#symptom-kind').value = 'tiredness'; severity.querySelectorAll('input')[0].checked = true; }
    },
    async submit() { form.fire('submit'); await settle(); },
    close() { page.$('#sheet-symptom').close(); },
  };
}
const answer = (call) => ({ ...call.args.at(-1), id: 9, name: 'Tiredness' });
for (const outcome of ['success', 'validation', 'error']) {
  test(`late ${outcome} preserves the reopened symptom draft`, async () => {
    const s = setup(); s.open(); await s.submit(); s.close(); s.open(true); s.$('#symptom-note').value = 'Keep this new draft';
    await s.submit(); assert.equal(s.calls.length, 1); assert.equal(s.$('#symptom-save').disabled, true);
    if (outcome === 'success') s.calls[0].resolve(answer(s.calls[0]));
    else s.calls[0].reject(outcome === 'validation' ? { status: 400, detail: 'Old value refused' } : new Error('Old server failure'));
    await settle();
    assert.equal(s.$('#sheet-symptom').open, true);
    assert.equal(s.$('#symptom-note').value, 'Keep this new draft');
    assert.equal(s.$('#symptom-error').hidden, true);
    assert.deepEqual(s.errors, outcome === 'success' ? [] : ['An earlier save did not go through. Check it and try again.']); // said, without touching the new draft
    assert.equal(s.$('#symptom-save').disabled, false);
    await s.submit(); assert.equal(s.calls.length, 2); assert.equal(s.calls[1].method, 'update');
    assert.equal(s.calls[1].args[0], 9); s.calls[1].resolve(answer(s.calls[1])); await settle();
    assert.equal(s.$('#sheet-symptom').open, false);
  });
}
test('the submitted symptom fields freeze while Close stays available', async () => {
  const s = setup(); s.open(); await s.submit();
  for (const field of ['kind', 'label', 'date', 'note']) assert.equal(s.$(`#symptom-${field}`).disabled, true);
  assert.ok(s.$('#symptom-severity').querySelectorAll('input').every((el) => el.disabled));
  s.close(); s.open(); assert.equal(s.$('#symptom-note').disabled, false); assert.equal(s.$('#symptom-save').disabled, true);
  s.calls[0].resolve(answer(s.calls[0])); await settle(); assert.equal(s.$('#symptom-save').disabled, false);
});
test('a current refusal preserves the submitted draft and prevents duplicate writes', async () => {
  const s = setup(); s.open(true); await s.submit(); await s.submit(); assert.equal(s.calls.length, 1);
  s.calls[0].reject({ status: 400, detail: 'Check this symptom' }); await settle();
  assert.equal(s.$('#sheet-symptom').open, true); assert.equal(s.$('#symptom-note').value, 'Existing');
  assert.equal(s.$('#symptom-error').textContent, 'Check this symptom');
  assert.equal(s.$('#symptom-save').disabled, false); assert.equal(s.$('#symptom-kind').disabled, false);
});
