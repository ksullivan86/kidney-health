// Runs the Server administration frame of app/static/js/views/settings.js (cut out between its markers, like
// tests/js/assistant_page.mjs does) on a fake page: two loads that overlap (a double tap on the shield on a slow connection)
// must build each part once, not twice.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/settings.js', import.meta.url), 'utf8');
const start = source.indexOf('  const isAdmin = () =>');
const end = source.indexOf('  // ---- People: accounts and invites');
assert.ok(start > 0 && end > start, 'the admin frame markers are in settings.js');
const code = source.slice(start, end);

function setup({ blocked = false } = {}) {
  const page = makePage();
  const { $, h } = page;
  const checks = [];
  const loads = [];
  const context = vm.createContext({
    h, clear: page.clear, $, state: { me: { id: 1, role: 'admin' } },
    request: (method, path) => { const d = deferred(); checks.push({ method, path, ...d }); return d.promise; },
    authMode: () => 'local', note: (kind, ...kids) => h('div', { class: `settings-note ${kind}` }, ...kids),
    subtitle: (t, id) => h('h3', { class: 'settings-subtitle', id }, t), loading: () => h('p', {}, 'Loading…'),
    loadServerSettings: () => { loads.push('settings'); return Promise.resolve(); }, loadPeople: () => { loads.push('people'); return Promise.resolve(); },
    loadSharedKeys: () => loads.push('keys'), loadUsage: () => loads.push('usage'), loadAudit: () => loads.push('audit'),
    loadServerAbout: () => loads.push('about'), console, Promise,
  });
  vm.runInContext(`${code}\nglobalThis.renderAdminFrame = renderAdminFrame;`, context);
  const count = (id) => page.find($('#set-admin-body'), (e) => e.id === id).length;
  const answer = (i) => checks[i].resolve({ required: blocked, enabled: false });
  return { page, $, context, checks, loads, count, answer };
}

for (const order of ['in order', 'newest first']) {
  test(`two overlapping loads answered ${order} build each part once`, async () => {
    const s = setup();
    const first = s.context.renderAdminFrame();
    const second = s.context.renderAdminFrame();
    assert.equal(s.checks.length, 2);
    if (order === 'in order') { s.answer(0); s.answer(1); } else { s.answer(1); await settle(); s.answer(0); }
    await Promise.all([first, second]);
    await settle();
    for (const id of ['set-people', 'set-server', 'set-shared', 'set-usage', 'set-audit', 'set-server-about']) assert.equal(s.count(id), 1, id);
    assert.equal(s.loads.filter((l) => l === 'people').length, 1, 'the people list is read once');
  });
}

test('one load builds every part and starts each read', async () => {
  const s = setup();
  const done = s.context.renderAdminFrame();
  s.answer(0);
  await done;
  for (const id of ['set-people', 'set-server', 'set-shared', 'set-usage', 'set-audit', 'set-server-about']) assert.equal(s.count(id), 1, id);
  assert.deepEqual(s.loads.sort(), ['about', 'audit', 'keys', 'people', 'settings', 'usage']);
});

test('the two-step note shows once when both loads are told to turn it on first', async () => {
  const s = setup({ blocked: true });
  const first = s.context.renderAdminFrame();
  const second = s.context.renderAdminFrame();
  s.answer(0); s.answer(1);
  await Promise.all([first, second]);
  assert.equal(s.count('admin-two-step-go'), 1);
  assert.equal(s.loads.length, 0);
});
