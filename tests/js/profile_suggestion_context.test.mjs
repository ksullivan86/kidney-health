// Run the real preflight/suggestion function with controlled network replies and form entries.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/profile.js', import.meta.url), 'utf8');
const start = source.indexOf('  const sameNumber =');
const end = source.indexOf('  // {code, message}', start);
assert.ok(start >= 0 && end > start);

function setup() {
  const nodes = new Map();
  const $ = (id) => {
    if (!nodes.has(id)) nodes.set(id, { id, value: '', checked: false, disabled: false, hidden: true, textContent: '', focus() {} });
    return nodes.get(id);
  };
  const saved = { weight_kg: 70, height_cm: 170, ckd_stage: '3b', diabetes: 'type1', dialysis: 'none' };
  const state = { profile: saved, targetsStale: { marker: 'stale' }, targetsReview: { marker: 'review' } };
  const fields = ['#pf-weight', '#pf-stage', '#pf-diabetes', '#tg-potassium_mg'].map($);
  fields[0].value = '70'; fields[1].value = '3b'; fields[2].value = 'type1'; fields[3].value = '2500';
  const form = { ...saved };
  const calls = [], toasts = [], rendered = [], errors = [];
  const context = vm.createContext({
    $, $$: () => fields, profileForm: {}, state,
    formBody: () => ({ ...form }), numOrNull: (v) => v === '' ? null : Number(v), refusalFor: () => null,
    api: { suggested: () => new Promise((resolve, reject) => calls.push({ resolve, reject })) },
    fillTargets: (targets) => { if ('potassium_mg' in targets) fields[3].value = String(targets.potassium_mg); },
    renderSuggestion: (reply) => rendered.push(reply), renderRefusal: (...args) => rendered.push(args),
    renderTargetsStale() {}, renderTargetsReview() {},
    toast: (...args) => toasts.push(args), toastError: (e) => errors.push(e),
  });
  vm.runInContext(source.slice(start, end), context);
  return { $, state, form, calls, toasts, rendered, errors, suggest: (options) => context.suggestTargetsIntoForm(options) };
}

test('an unchanged form receives the suggestion without saving it', async () => {
  const s = setup(), saved = s.state.profile;
  const pending = s.suggest();
  assert.equal(s.$('#btn-suggest').disabled, true);
  s.calls[0].resolve({ targets: { potassium_mg: 2000 } });
  await pending;
  assert.equal(s.$('#tg-potassium_mg').value, '2000');
  assert.equal(s.state.profile, saved);
  assert.equal(s.rendered.length, 1);
  assert.equal(s.$('#btn-suggest').disabled, false);
});

test('a target edited while waiting is kept instead of overwritten', async () => {
  const s = setup(), pending = s.suggest();
  s.$('#tg-potassium_mg').value = '1800';
  s.calls[0].resolve({ targets: { potassium_mg: 2000 } });
  await pending;
  assert.equal(s.$('#tg-potassium_mg').value, '1800');
  assert.equal(s.rendered.length, 0);
  assert.ok(s.state.targetsStale && s.state.targetsReview);
  assert.match(s.$('#suggest-live').textContent, /changed|kept/i);
});

test('a changed weight cannot receive numbers for the previous weight', async () => {
  const s = setup(), pending = s.suggest();
  s.$('#pf-weight').value = '90'; s.form.weight_kg = 90;
  s.calls[0].resolve({ targets: { potassium_mg: 2000 } });
  await pending;
  assert.equal(s.rendered.length, 0);
  assert.equal(s.$('#tg-potassium_mg').value, '2500');
});

test('a completed profile save invalidates an older suggestion even when the form matches', async () => {
  const s = setup(), pending = s.suggest();
  s.state.profile = { ...s.state.profile, targets: { potassium_mg: 1800 } };
  s.calls[0].resolve({ targets: { potassium_mg: 2000 } });
  await pending;
  assert.equal(s.rendered.length, 0);
});

test('an error for an edited form is discarded and permits retry', async () => {
  const s = setup(), pending = s.suggest();
  s.$('#tg-potassium_mg').value = '1800';
  s.calls[0].reject({ status: 422, data: { code: 'pregnant' }, detail: 'Old refusal' });
  await pending;
  assert.equal(s.rendered.length, 0);
  assert.equal(s.errors.length, 0);
  assert.equal(s.$('#btn-suggest').disabled, false);
  const retry = s.suggest();
  s.calls[1].resolve({ targets: { potassium_mg: 2200 } });
  await retry;
  assert.equal(s.$('#tg-potassium_mg').value, '2200');
});

test('the latest request owns the result and busy state across different triggers', async () => {
  const s = setup(), old = s.suggest({ from: '#targets-review-suggest' }), current = s.suggest();
  s.calls[0].resolve({ targets: { potassium_mg: 1000 } });
  await old;
  assert.equal(s.rendered.length, 0);
  assert.equal(s.$('#btn-suggest').disabled, true);
  s.calls[1].resolve({ targets: { potassium_mg: 2200 } });
  await current;
  assert.equal(s.$('#tg-potassium_mg').value, '2200');
  assert.equal(s.rendered.length, 1);
  assert.equal(s.$('#targets-review-suggest').disabled, false);
});

test('an older failure does not clear the newer working message or show an error', async () => {
  const s = setup(), old = s.suggest(), current = s.suggest();
  s.calls[0].reject(Error('old error'));
  await old;
  assert.equal(s.errors.length, 0);
  assert.match(s.$('#suggest-live').textContent, /Working/);
  assert.equal(s.$('#btn-suggest').disabled, true);
  s.calls[1].resolve({ targets: {} });
  await current;
});

test('a genuine failure remains visible and the next request succeeds', async () => {
  const s = setup(), pending = s.suggest();
  s.calls[0].reject(Error('offline'));
  await pending;
  assert.equal(s.errors.length, 1);
  assert.equal(s.$('#btn-suggest').disabled, false);
  const retry = s.suggest();
  s.calls[1].resolve({ targets: { potassium_mg: 2100 } });
  await retry;
  assert.equal(s.$('#tg-potassium_mg').value, '2100');
});
