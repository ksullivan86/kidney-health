// Height in feet and inches or centimetres (user.units.height): the engine's conversions (js/engine/body.js) and Profile's height
// boxes (js/views/profile.js), run with a fake page. The profile stores centimetres; a height the person did not touch keeps them.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const read = (rel) => readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');
const context = vm.createContext({ console });
vm.runInContext('globalThis.window = globalThis;', context);
for (const file of ['rules.js', 'body.js']) vm.runInContext(read(`app/static/js/engine/${file}`), context, { filename: file });
const R = vm.runInContext('globalThis.KH.bodyRules', context);

test('feet and inches become centimetres, half up to 0.5 cm', () => {
  assert.equal(R.CM_PER_INCH, 2.54);
  assert.deepEqual([...R.HEIGHT_UNITS], ['ft_in', 'cm']);
  assert.equal(R.feetInchesToCm(5, 10), 178); // 70 in = 177.8 cm
  assert.equal(R.feetInchesToCm('5', '5'), 165); // 65 in = 165.1 cm
  assert.equal(R.feetInchesToCm(5, 9), 175.5); // 69 in = 175.26 cm
  assert.equal(R.feetInchesToCm(6, 0), 183); // 72 in = 182.88 cm
  assert.equal(R.feetInchesToCm('6', ''), 183); // an empty inches box is 0
  assert.equal(R.feetInchesToCm(5, 7.5), 171.5); // 67.5 in = 171.45 cm
  assert.equal(R.feetInchesToCm(3, 0), 91.5);
  assert.equal(R.feetInchesToCm(8, 11.5), 273);
  assert.equal(R.feetInchesToCm('', ''), null);
  assert.equal(R.feetInchesToCm(null, undefined), null);
  assert.equal(R.feetInchesToCm('x', '2'), null);
});

test('centimetres become feet and inches to the nearest half inch, 12 inches carrying to the next foot', () => {
  assert.deepEqual({ ...R.cmToFeetInches(178) }, { feet: 5, inches: 10 });
  assert.deepEqual({ ...R.cmToFeetInches(170) }, { feet: 5, inches: 7 }); // 66.93 in
  assert.deepEqual({ ...R.cmToFeetInches(171.5) }, { feet: 5, inches: 7.5 });
  assert.deepEqual({ ...R.cmToFeetInches(182.5) }, { feet: 6, inches: 0 }); // 71.85 in rounds to 72: 6 ft 0 in, never 5 ft 12 in
  assert.deepEqual({ ...R.cmToFeetInches(100) }, { feet: 3, inches: 3.5 });
  assert.deepEqual({ ...R.cmToFeetInches(250) }, { feet: 8, inches: 2.5 });
  assert.equal(R.cmToFeetInches(null), null);
  assert.equal(R.cmToFeetInches(''), null);
  assert.equal(R.formatHeight(178, 'ft_in'), '5 ft 10 in');
  assert.equal(R.formatHeight(178, 'cm'), '178 cm');
  assert.equal(R.formatHeight(null, 'cm'), '');
});

test('every feet-and-inches height the boxes take comes back unchanged', () => {
  for (let ft = 3; ft <= 8; ft += 1) {
    for (let half = 0; half <= 23; half += 1) {
      const cm = R.feetInchesToCm(ft, half / 2);
      assert.deepEqual({ ...R.cmToFeetInches(cm) }, { feet: ft, inches: half / 2 }, `${ft} ft ${half / 2} in`);
    }
  }
});

// Profile's height block, from "let heightUnit" to the end of loadHeightUnit, with a fake page.
const source = read('app/static/js/views/profile.js');
const start = source.indexOf('  let heightUnit =');
const end = source.indexOf('  // The v0.3 fields as the form shows them');
assert.ok(start >= 0 && end > start);

function profile(settings = null) {
  const nodes = new Map();
  const $ = (id) => {
    if (!nodes.has(id)) nodes.set(id, { id: id.slice(1), value: '', hidden: false });
    return nodes.get(id);
  };
  const state = {};
  const ctx = vm.createContext({
    $, state, KH: { bodyRules: R }, numOrNull: (v) => (v === '' || v == null ? null : Number(v)),
    api: { mySettings: async () => { if (settings instanceof Error) throw settings; return { settings: settings || {} }; } },
  });
  vm.runInContext(`${source.slice(start, end)}; globalThis.P = { fillHeight, readHeightCm, setHeightUnit, loadHeightUnit, heightInput };`, ctx);
  return { $, state, P: ctx.P };
}

test('Profile shows a saved height in feet and inches by default and keeps the saved centimetres when untouched', () => {
  const { $, P } = profile();
  P.fillHeight(170.2);
  assert.equal($('#pf-height-ftin-field').hidden, false);
  assert.equal($('#pf-height-cm-field').hidden, true);
  assert.equal($('#pf-height-ft').value, '5');
  assert.equal($('#pf-height-in').value, '7');
  assert.equal(P.readHeightCm(), 170.2); // not 170: showing it never changes it
  assert.equal(P.heightInput().id, 'pf-height-ft');
  $('#pf-height-in').value = '8';
  assert.equal(P.readHeightCm(), 172.5); // 68 in = 172.72 cm
  $('#pf-height-ft').value = '';
  $('#pf-height-in').value = '';
  assert.equal(P.readHeightCm(), null);
});

test('Profile in centimetres keeps today\'s box', () => {
  const { $, P, state } = profile();
  P.setHeightUnit('cm');
  assert.equal(state.heightUnit, 'cm');
  P.fillHeight(165);
  assert.equal($('#pf-height-cm-field').hidden, false);
  assert.equal($('#pf-height-ftin-field').hidden, true);
  assert.equal($('#pf-height').value, 165);
  assert.equal(P.readHeightCm(), 165);
  assert.equal(P.heightInput().id, 'pf-height');
  $('#pf-height').value = '166.5';
  assert.equal(P.readHeightCm(), 166.5);
});

test('changing the unit shows the same height in the other unit, typed or saved', async () => {
  const { $, P } = profile({ 'user.units.height': { value: 'cm', source: 'user', editable: true } });
  P.fillHeight(170.2);
  await P.loadHeightUnit();
  assert.equal($('#pf-height').value, 170.2);
  assert.equal(P.readHeightCm(), 170.2);
  $('#pf-height').value = '178';
  P.setHeightUnit('ft_in');
  assert.equal($('#pf-height-ft').value, '5');
  assert.equal($('#pf-height-in').value, '10');
  assert.equal(P.readHeightCm(), 178);
  P.setHeightUnit('ft_in'); // the same unit again changes nothing
  assert.equal(P.readHeightCm(), 178);
});

test('Profile keeps the last unit when the settings cannot be read', async () => {
  for (const answer of [new Error('offline'), {}]) {
    const { $, P } = profile(answer);
    P.fillHeight(180);
    await P.loadHeightUnit();
    assert.equal(P.heightInput().id, 'pf-height-ft');
    assert.equal($('#pf-height-ft').value, '5');
    assert.equal($('#pf-height-in').value, '11');
    assert.equal(P.readHeightCm(), 180);
  }
});
