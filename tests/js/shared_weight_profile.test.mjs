// The real shared weight chart must never use its viewer's dry-weight reference.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const root = new URL('../../app/static/js/', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');

function setup(sharedProfile) {
  const elements = new Map();
  function element(tag = '', attrs = {}, ...children) {
    return { tag, attrs, children: children.flat(Infinity).filter((v) => v != null), clientWidth: 700,
      append(...nodes) { this.children.push(...nodes.flat(Infinity).filter((v) => v != null)); }, addEventListener() {} };
  }
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const ownProfile = { dialysis: 'hemodialysis', weight_kg: 91 };
  const reads = {
    bodyWeights: async () => ({ weights: [{ id: 1, date: '2026-10-29', time: '09:00', kg: 70, context: 'morning' }] }),
    bloodPressures: async () => ({ readings: [] }),
    bodySummary: async () => ({ units: 'kg' }),
    profile: sharedProfile,
  };
  const KH = {
    $, h: element, s: element, state: { profile: ownProfile }, api: reads,
    clear(node) { node.children = []; return node; },
    util: { fmtDateShort: (d) => d, fmtMonthDay: (d) => d, daysBetween: () => 6 },
  };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, console });
  for (const file of ['rules', 'symptoms', 'body', 'visitprep', 'body_ui']) {
    vm.runInContext(read(`engine/${file}.js`), context);
  }
  vm.runInContext(read('views/body_trends.js'), context);
  const share = { name: 'Ana', areas: ['body'], reads };
  const nodes = () => {
    const result = [];
    function walk(node) {
      if (!node || typeof node !== 'object') return;
      result.push(node);
      node.children.forEach(walk);
    }
    walk($('#body-trends-body'));
    return result;
  };
  return { KH, share, nodes };
}

test('a failed shared profile read omits the dry-weight line, including on resize', async () => {
  const s = setup(async () => { throw Error('profile unavailable'); });
  await s.KH.bodyTrends.show('2026-10-23', '2026-10-29', s.share);
  assert.equal(s.nodes().filter((node) => node.tag === 'line' && node.attrs.class === 'ref dry').length, 0);
  assert.ok(s.nodes().some((node) => node.tag === 'path' && node.attrs.class === 'series weight'), 'weights still render');
  assert.doesNotMatch(JSON.stringify(s.nodes()), /91\.0|Dry weight in Profile/);
  s.KH.bodyTrends.render();
  assert.equal(s.nodes().filter((node) => node.attrs.class === 'ref dry').length, 0);
});

test('a shared chart uses the owner profile when available', async () => {
  const s = setup(async () => ({ dialysis: 'hemodialysis', weight_kg: 65 }));
  await s.KH.bodyTrends.show('2026-10-23', '2026-10-29', s.share);
  assert.equal(s.nodes().filter((node) => node.tag === 'line' && node.attrs.class === 'ref dry').length, 2); // chart and legend
  assert.match(JSON.stringify(s.nodes()), /65\.0/);
  assert.doesNotMatch(JSON.stringify(s.nodes()), /91\.0/);
});

test('own Trends retain the signed-in person dry-weight line', async () => {
  const s = setup(async () => { throw Error('shared route should not be used'); });
  await s.KH.bodyTrends.show('2026-10-23', '2026-10-29');
  assert.equal(s.nodes().filter((node) => node.tag === 'line' && node.attrs.class === 'ref dry').length, 2);
  assert.match(JSON.stringify(s.nodes()), /91\.0/);
});
