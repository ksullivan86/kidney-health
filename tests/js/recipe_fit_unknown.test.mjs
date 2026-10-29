// Exercise the real Fit sheet row and carbohydrate confirmation formatting.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/plan.js', import.meta.url), 'utf8');
const core = readFileSync(new URL('../../app/static/js/core.js', import.meta.url), 'utf8');
const start = source.indexOf('  function fitNumber(');
const end = source.indexOf('  function renderFit()', start);
const carbsStart = source.indexOf('  const carbsOf =');
const carbsEnd = source.indexOf("  $('#fit-target').addEventListener", carbsStart);
assert.ok(start >= 0 && end > start && carbsStart >= 0 && carbsEnd > carbsStart);
// The real helpers from core.js, so the test reads what the screen shows.
const helper = (name) => {
  const at = core.indexOf(`  function ${name}(`);
  assert.ok(at >= 0, name);
  const line = core.slice(at, core.indexOf('\n', at));
  return line.trimEnd().endsWith('}') ? line : core.slice(at, core.indexOf('\n  }\n', at) + 4);
};

function setup() {
  const context = vm.createContext({
    NUT: { potassium_mg: { unit: 'mg', label: 'Potassium' }, carbs_g: { unit: 'g', label: 'Carbohydrate' } },
    fmtNum: (value) => value == null ? '—' : String(value), fit: {},
    h: (tag, attrs, ...children) => ({ tag, attrs, children: children.flat(Infinity) }),
  });
  vm.runInContext(['unknownOf', 'atLeast', 'atLeastWords'].map(helper).join('\n'), context);
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
test('a partially listed amount is qualified on the row, and the row is not the green "fits"', () => {
  const node = setup().row(figures(100, 1));
  assert.match(text(node), /Potassium ≥ 100 mg/);
  assert.equal(node.attrs.class, 'fit-unknown');
});
test('a genuine known zero stays 0 mg, on the green row', () => {
  const node = setup().row(figures(0));
  assert.match(text(node), /Potassium 0 mg/);
  assert.equal(node.attrs.class, 'fit-ok');
});
test('a known zero with a food that does not list it is "≥ 0", never a complete 0 (as in the meal editor)', () => {
  const row = text(setup().row(figures(0, 1)));
  assert.match(row, /Potassium ≥ 0 mg/);
});
test('a swap that fills a data gap shows the change even when the numeric subtotal is equal', () => {
  assert.match(text(setup().row(figures(100, 1), figures(100))), /≥ 100 mg → 100 mg/);
});
test('before and after amounts use their own missing-data flags, each with its unit', () => {
  assert.match(text(setup().row(figures(null, 2), figures(80, 1))), /not listed → ≥ 80 mg/);
  assert.match(text(setup().row(figures(80, 1), figures(null, 2))), /≥ 80 mg → not listed/);
});
test('the Replace confirmation qualifies partial and missing carbohydrate', () => {
  const s = setup();
  s.context.fit.result = { before: figures(20, 1, 'carbs_g'), after: figures(null, 1, 'carbs_g') };
  assert.equal(s.context.confirmation(), 'Carbohydrate per serving goes from at least 20 g to not listed.');
  s.context.fit.result = { before: figures(null, 1, 'carbs_g'), after: figures(null, 1, 'carbs_g') };
  assert.equal(s.context.confirmation(), 'No food in it lists carbohydrate.');
});
test('known carbohydrate remains a plain numeric before and after', () => {
  const s = setup();
  s.context.fit.result = { before: figures(20, 0, 'carbs_g'), after: figures(10, 0, 'carbs_g') };
  assert.equal(s.context.confirmation(), 'Carbohydrate per serving goes from 20 g to 10 g.');
});
