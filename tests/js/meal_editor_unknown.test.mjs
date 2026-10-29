// Render the real saved-meal editor preview from its actual edited ingredients.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/views/plan.js', import.meta.url), 'utf8');
const start = source.indexOf('  function renderMealTotals()');
const end = source.indexOf('  async function runMealSearch()', start);
assert.ok(start >= 0 && end > start);
function setup(items, makes = '') {
  const nodes = new Map();
  const $ = (key) => {
    if (!nodes.has(key)) nodes.set(key, { children: [], value: '', append(...children) { this.children.push(...children); } });
    return nodes.get(key);
  };
  $('#meal-makes').value = makes;
  const NUT = { potassium_mg: { label: 'Potassium', short: 'K', unit: 'mg' }, carbs_g: { label: 'Carbohydrate', short: 'C', unit: 'g' } };
  const context = vm.createContext({
    $, NUT, NUTRIENTS: Object.keys(NUT).map((key) => ({ key })), KEY_NUMBERS: Object.keys(NUT),
    mealEd: { items }, fmtNum: (n) => String(n),
    atLeast: (text, count) => count ? `≥ ${text}` : text,
    atLeastWords: (text, count) => count ? `at least ${text}` : text,
    foodsNotListing: (count, key) => `${count} ${count === 1 ? 'food does' : 'foods do'} not list ${NUT[key].label.toLowerCase()}`,
    clear: (node) => { node.children = []; return node; },
    h: (tag, attrs, ...children) => ({ tag, attrs, children: children.flat(Infinity).filter((c) => c != null) }),
  });
  vm.runInContext(source.slice(start, end), context);
  const render = () => { context.renderMealTotals(); return $('#meal-preview-key').children; };
  return { $, render, items };
}
const item = (per, servings = 1) => ({ per, servings });
const text = (node) => node == null ? '' : typeof node === 'object' ? node.children.map(text).join(' ') : String(node);
const amount = (node) => text(node.children.find((child) => child.attrs?.class === 'kn-v'));

test('all missing potassium is not listed, including omitted keys and explicit null', () => {
  const s = setup([item({ carbs_g: 10 }), item({ potassium_mg: null, carbs_g: 5 })]);
  const potassium = s.render()[0];
  assert.equal(amount(potassium), 'not listed');
  assert.doesNotMatch(text(potassium), /\b0\b|\bmg\b/);
});
test('a partial total shows ≥ and the number of foods with missing data', () => {
  const s = setup([item({ potassium_mg: 100 }), item({})]);
  const potassium = s.render()[0];
  assert.equal(amount(potassium), '≥ 100');
  assert.match(potassium.attrs.title, /1 food does not list potassium/);
  assert.match(potassium.attrs['aria-label'], /at least 100 mg/);
});
test('known zero remains exactly 0 with its unit', () => {
  const potassium = setup([item({ potassium_mg: 0 })]).render()[0];
  assert.equal(amount(potassium), '0');
  assert.match(text(potassium), /mg/);
});
test('a known zero plus missing data is qualified rather than an exact zero', () => {
  assert.equal(amount(setup([item({ potassium_mg: 0 }), item({})]).render()[0]), '≥ 0');
});
test('Makes scales known values while preserving missing counts', () => {
  const s = setup([item({ potassium_mg: 100 }, 2), item({})], '4');
  assert.equal(amount(s.render()[0]), '≥ 50');
  s.$('#meal-makes').value = '2';
  assert.equal(amount(s.render()[0]), '≥ 100');
});
test('removing the unknown ingredient restores an exact total', () => {
  const s = setup([item({ potassium_mg: 100 }), item({})]);
  s.render(); s.items.pop();
  assert.equal(amount(s.render()[0]), '100');
});
test('removing the known ingredient leaves not listed', () => {
  const s = setup([item({ potassium_mg: 100 }), item({})]);
  s.render(); s.items.shift();
  assert.equal(amount(s.render()[0]), 'not listed');
});
test('an empty editor keeps the empty total at zero', () => {
  assert.equal(amount(setup([]).render()[0]), '0');
});
