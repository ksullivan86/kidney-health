// Exercise the real Fit sheet row and carbohydrate confirmation formatting.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/plan.js', import.meta.url), 'utf8');
const start = source.indexOf('  function fitAmount(');
const end = source.indexOf('  function renderFit()', start);
const carbsStart = source.indexOf('  const carbsLine =');
const carbsEnd = source.indexOf("  $('#fit-target').addEventListener", carbsStart);
assert.ok(start >= 0 && end > start && carbsStart >= 0 && carbsEnd > carbsStart);

function setup() {
  const context = vm.createContext({
    NUT: { potassium_mg: { unit: 'mg', label: 'Potassium' }, carbs_g: { unit: 'g', label: 'Carbohydrate' } },
    fmtNum: (value) => value == null ? '—' : String(value), fit: {},
    h: (tag, attrs, ...children) => ({ tag, attrs, children: children.flat(Infinity) }),
  });
  vm.runInContext(source.slice(start, end) + '\n' + source.slice(carbsStart, carbsEnd) + '\nglobalThis.confirmation = carbsLine;', context);
  const row = (before, after = null) => context.fitRow(before.checks[0], before, after);
  return { context, row };
}
const figures = (value, count = 0, key = 'potassium_mg') => ({
  per_serving: { [key]: value }, unknown: count ? { [key]: count } : {},
  checks: [{ nutrient: key, used: value ?? 0, room: 500, ok: true }],
});
const text = (node) => node == null ? '' : typeof node === 'object' ? node.children.map(text).join('') : String(node);

test('a wholly missing nutrient says not listed instead of 0 mg', () => {
  const s = setup(), row = text(s.row(figures(null, 2)));
  assert.match(row, /Potassium not listed/);
  assert.doesNotMatch(row, /\b0 mg/);
});
test('a partially listed amount is qualified on the row', () => {
  assert.match(text(setup().row(figures(100, 1))), /Potassium ≥ 100 mg/);
});
test('a genuine known zero stays 0 mg', () => {
  assert.match(text(setup().row(figures(0))), /Potassium 0 mg/);
});
test('partial zero does not imply a complete zero', () => {
  const row = text(setup().row(figures(0, 1)));
  assert.match(row, /not listed/);
  assert.doesNotMatch(row, /\b0 mg/);
});
test('a swap that fills a data gap shows the change even when the numeric subtotal is equal', () => {
  assert.match(text(setup().row(figures(100, 1), figures(100))), /≥ 100 mg → 100 mg/);
});
test('before and after amounts use their own missing-data flags', () => {
  assert.match(text(setup().row(figures(null, 2), figures(80, 1))), /not listed → ≥ 80 mg/);
});
test('the Replace confirmation qualifies partial and missing carbohydrate', () => {
  const s = setup();
  s.context.fit.result = { before: figures(20, 1, 'carbs_g'), after: figures(null, 1, 'carbs_g') };
  assert.equal(s.context.confirmation(), 'Carbohydrate per serving goes from ≥ 20 g to not listed.');
});
test('known carbohydrate remains a plain numeric before and after', () => {
  const s = setup();
  s.context.fit.result = { before: figures(20, 0, 'carbs_g'), after: figures(10, 0, 'carbs_g') };
  assert.equal(s.context.confirmation(), 'Carbohydrate per serving goes from 20 g to 10 g.');
});
