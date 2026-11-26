// Profile's two weights in pounds or kilograms (user.units.weight): the engine's box helpers (js/engine/body.js) and Profile's weight
// boxes (js/views/profile.js), run with a fake page. The profile stores kilograms; a weight the person did not touch keeps them.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const read = (rel) => readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');
const context = vm.createContext({ console });
vm.runInContext('globalThis.window = globalThis;', context);
for (const file of ['rules.js', 'body.js']) vm.runInContext(read(`app/static/js/engine/${file}`), context, { filename: file });
const R = vm.runInContext('globalThis.KH.bodyRules', context);

test('a stored weight shows as kilograms as saved, or pounds to 0.1', () => {
  assert.equal(R.KG_PER_LB, 0.45359237);
  assert.equal(R.weightBoxText(70, 'kg'), '70');
  assert.equal(R.weightBoxText(70.23, 'kg'), '70.23');
  assert.equal(R.weightBoxText(70, 'lb'), '154.3'); // 154.32 lb
  assert.equal(R.weightBoxText(68.04, 'lb'), '150'); // 150.0 lb
  assert.equal(R.weightBoxText(null, 'lb'), '');
  assert.equal(R.weightBoxText('', 'kg'), '');
});

test('a typed weight becomes kilograms: pounds with the exact factor, kept to 0.01 kg', () => {
  assert.equal(R.weightBoxKg('70.2', 'kg'), 70.2);
  assert.equal(R.weightBoxKg('154.3', 'lb'), 69.99); // 69.988...
  assert.equal(R.weightBoxKg('150', 'lb'), 68.04);
  assert.equal(R.weightBoxKg(' 200 ', 'lb'), 90.72);
  assert.equal(R.weightBoxKg('', 'lb'), null);
  assert.equal(R.weightBoxKg(null, 'kg'), null);
  assert.equal(R.weightBoxKg('x', 'lb'), null);
});

test('the ranges in pounds stay inside the kilogram limits', () => {
  assert.deepEqual({ ...R.weightBoxRange(20, 300, 'kg') }, { min: 20, max: 300, step: 0.1 });
  assert.deepEqual({ ...R.weightBoxRange(20, 300, 'lb') }, { min: 44.1, max: 661.3, step: 0.1 });
  assert.deepEqual({ ...R.weightBoxRange(20, 400, 'lb') }, { min: 44.1, max: 881.8, step: 0.1 });
  assert.ok(R.weightBoxKg('44.1', 'lb') >= 20 && R.weightBoxKg('881.8', 'lb') <= 400);
});

test('every weight typed to 0.1 lb shows the same again', () => {
  for (let tenths = 441; tenths <= 8818; tenths += 1) {
    const text = String(tenths / 10);
    assert.equal(R.weightBoxText(R.weightBoxKg(text, 'lb'), 'lb'), text, text);
  }
});

// Profile's weight block, from "let weightUnit" to the end of loadWeightUnit, with a fake page.
const source = read('app/static/js/views/profile.js');
const start = source.indexOf('  let weightUnit =');
const end = source.indexOf('  // The v0.3 fields as the form shows them');
assert.ok(start >= 0 && end > start);

function profile(settings = null) {
  const nodes = new Map();
  const $ = (id) => {
    if (!nodes.has(id)) nodes.set(id, { id: id.slice(1), value: id === '#pf-dialysis' ? 'none' : '', textContent: '' });
    return nodes.get(id);
  };
  const state = {};
  let hints = 0;
  const ctx = vm.createContext({
    $, state, KH: { bodyRules: R }, showBodyHints: () => { hints += 1; },
    api: { mySettings: async () => { if (settings instanceof Error) throw settings; return { settings: settings || {} }; } },
  });
  vm.runInContext(`${source.slice(start, end)}; globalThis.P = { fillWeight, readWeightKg, setWeightUnit, loadWeightUnit, showWeightUnit };`, ctx);
  return { $, state, P: ctx.P, hints: () => hints };
}

test('Profile shows a saved weight in pounds by default and keeps the saved kilograms when untouched', () => {
  const { $, P } = profile();
  P.fillWeight('#pf-weight', 70.23);
  P.fillWeight('#pf-weight-6mo', 74);
  assert.equal($('#pf-weight').value, '154.8');
  assert.equal($('#pf-weight-6mo').value, '163.1');
  assert.equal(P.readWeightKg('#pf-weight'), 70.23); // not 70.22: showing it never changes it
  assert.equal(P.readWeightKg('#pf-weight-6mo'), 74);
  $('#pf-weight').value = '155';
  assert.equal(P.readWeightKg('#pf-weight'), 70.31);
  $('#pf-weight').value = '';
  assert.equal(P.readWeightKg('#pf-weight'), null);
  P.fillWeight('#pf-weight-6mo', null);
  assert.equal($('#pf-weight-6mo').value, '');
  assert.equal(P.readWeightKg('#pf-weight-6mo'), null);
});

test('the labels, ranges and example follow the unit', () => {
  const { $, P } = profile();
  P.showWeightUnit();
  assert.equal($('#pf-weight-label').textContent, 'Weight (lb)');
  assert.equal($('#pf-weight-6mo-label').textContent, 'Weight 6 months ago (lb)');
  assert.deepEqual([$('#pf-weight').min, $('#pf-weight').max, $('#pf-weight').step], ['44.1', '661.3', '0.1']);
  assert.deepEqual([$('#pf-weight-6mo').min, $('#pf-weight-6mo').max], ['44.1', '881.8']);
  assert.equal($('#pf-weight').placeholder, 'e.g. 154');
  $('#pf-dialysis').value = 'hemodialysis';
  P.setWeightUnit('kg');
  assert.equal($('#pf-weight-label').textContent, 'Dry weight (kg, after dialysis)');
  assert.equal($('#pf-weight-6mo-label').textContent, 'Weight 6 months ago (kg)');
  assert.deepEqual([$('#pf-weight').min, $('#pf-weight').max, $('#pf-weight-6mo').max], ['20', '300', '400']);
  assert.equal($('#pf-weight').placeholder, 'e.g. 70');
});

test('changing the unit shows the same weights in the other unit, typed or saved', async () => {
  const { $, P, state, hints } = profile({ 'user.units.weight': { value: 'kg', source: 'user', editable: true } });
  P.fillWeight('#pf-weight', 70.23);
  P.fillWeight('#pf-weight-6mo', 74);
  await P.loadWeightUnit();
  assert.equal(state.weightUnit, 'kg');
  assert.equal($('#pf-weight').value, '70.23');
  assert.equal(P.readWeightKg('#pf-weight'), 70.23);
  assert.equal(hints(), 1); // the log's hints are written again in the unit
  $('#pf-weight-6mo').value = '80';
  P.setWeightUnit('lb');
  assert.equal($('#pf-weight').value, '154.8');
  assert.equal($('#pf-weight-6mo').value, '176.4');
  assert.equal(P.readWeightKg('#pf-weight'), 70.23);
  assert.equal(P.readWeightKg('#pf-weight-6mo'), 80);
  P.setWeightUnit('lb'); // the same unit again changes nothing
  assert.equal(P.readWeightKg('#pf-weight'), 70.23);
  assert.equal(hints(), 2);
});

test('Profile keeps the last unit when the settings cannot be read', async () => {
  for (const answer of [new Error('offline'), {}]) {
    const { $, P } = profile(answer);
    P.fillWeight('#pf-weight', 90);
    await P.loadWeightUnit();
    assert.equal($('#pf-weight').value, '198.4');
    assert.equal(P.readWeightKg('#pf-weight'), 90);
  }
});
