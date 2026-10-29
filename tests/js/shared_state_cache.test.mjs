// Run the real shared-cache section of core.js without booting the DOM/router.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/core.js', import.meta.url), 'utf8');
const start = source.indexOf('  // Shared caches. Profile:');
const end = source.indexOf('  // Theme', start);
assert.ok(start >= 0 && end > start);
const helpers = source.slice(start, end);
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const value = (key, marker) => key === 'profile' ? { marker } : [{ marker }];

function setup() {
  const state = { profile: null, meals: null }, calls = { profile: [], meals: [] };
  const api = {};
  for (const key of ['profile', 'meals']) api[key] = () => new Promise((resolve, reject) => calls[key].push({
    resolve: (data) => resolve(key === 'profile' ? data : { meals: data }), reject,
  }));
  const context = vm.createContext({ state, api });
  vm.runInContext(helpers, context);
  return { state, calls, context, load: (key, force = false) => key === 'profile' ? context.loadProfile(force) : context.loadMeals(force),
    invalidate: (key) => key === 'meals' ? context.invalidateMeals() : context.invalidateSharedCaches() };
}

for (const key of ['profile', 'meals']) {
  test(`${key}: concurrent uncached readers share one request and then use the cache`, async () => {
    const s = setup();
    const first = s.load(key), second = s.load(key);
    assert.equal(s.calls[key].length, 1);
    const data = value(key, 'Loaded');
    s.calls[key][0].resolve(data);
    assert.equal(await first, data);
    assert.equal(await second, data);
    assert.equal(await s.load(key), data);
    assert.equal(s.calls[key].length, 1);
  });

  test(`${key}: a completed save wins over an earlier read and its returned value`, async () => {
    const s = setup();
    s.state[key] = value(key, 'Before');
    const pending = s.load(key, true);
    const saved = value(key, 'Saved');
    s.state[key] = saved;
    s.calls[key][0].resolve(value(key, 'Old reply'));
    assert.equal(await pending, saved);
    assert.equal(s.state[key], saved);
  });

  test(`${key}: an old read error cannot hide a completed save`, async () => {
    const s = setup();
    const pending = s.load(key);
    const saved = value(key, 'Saved');
    s.state[key] = saved;
    s.calls[key][0].reject(Error('pre-save read failed'));
    assert.equal(await pending, saved);
    assert.equal(s.state[key], saved);
  });

  test(`${key}: the latest force refresh wins over old replies`, async () => {
    const s = setup();
    const old = s.load(key), current = s.load(key, true);
    s.calls[key][0].resolve(value(key, 'Old'));
    await settle();
    const newest = value(key, 'Newest');
    s.calls[key][1].resolve(newest);
    assert.equal(await current, newest);
    assert.equal(await old, newest);
    assert.equal(s.state[key], newest);
  });

  test(`${key}: clearing an initially empty cache invalidates its pending read`, async () => {
    const s = setup();
    const old = s.load(key);
    s.invalidate(key);
    const current = s.load(key);
    assert.equal(s.calls[key].length, 2);
    const newest = value(key, 'Newest');
    s.calls[key][1].resolve(newest);
    await current;
    s.calls[key][0].resolve(value(key, 'Old'));
    assert.equal(await old, newest);
    assert.equal(s.state[key], newest);
  });

  test(`${key}: a late reply after a newer read and another save preserves that save`, async () => {
    const s = setup();
    const old = s.load(key), current = s.load(key, true);
    s.calls[key][1].resolve(value(key, 'New read'));
    await current;
    const saved = value(key, 'Saved after the new read');
    s.state[key] = saved;
    s.calls[key][0].resolve(value(key, 'Old'));
    assert.equal(await old, saved);
    assert.equal(s.state[key], saved);
  });

  test(`${key}: genuine errors allow retry without silent extra requests`, async () => {
    const s = setup();
    const pending = s.load(key);
    s.calls[key][0].reject(Error('current failure'));
    await assert.rejects(pending, /current failure/);
    const retry = s.load(key);
    assert.equal(s.calls[key].length, 2);
    const recovered = value(key, 'Recovered');
    s.calls[key][1].resolve(recovered);
    assert.equal(await retry, recovered);
  });

  test(`${key}: an older reader follows the newest failure without starting another request`, async () => {
    const s = setup();
    const old = s.load(key), current = s.load(key, true);
    const a = assert.rejects(old, /newest failure/), b = assert.rejects(current, /newest failure/);
    s.calls[key][1].reject(Error('newest failure'));
    s.calls[key][0].resolve(value(key, 'Old'));
    await Promise.all([a, b]);
    assert.equal(s.calls[key].length, 2);
  });
}

test('an explicitly saved empty meal list cannot be resurrected by an old read', async () => {
  const s = setup();
  const pending = s.load('meals');
  const saved = [];
  s.state.meals = saved;
  s.calls.meals[0].resolve(value('meals', 'Deleted meal'));
  assert.equal(await pending, saved);
  assert.equal(s.state.meals, saved);
});

test('Profile and meal reads remain independent', async () => {
  const s = setup();
  const profile = s.load('profile'), meals = s.load('meals');
  s.context.invalidateMeals();
  const freshMeals = s.load('meals');
  const p = value('profile', 'Profile'), m = value('meals', 'Fresh meals');
  s.calls.profile[0].resolve(p);
  s.calls.meals[1].resolve(m);
  s.calls.meals[0].resolve(value('meals', 'Old meals'));
  assert.equal(await profile, p);
  assert.equal(await meals, m);
  assert.equal(await freshMeals, m);
  assert.equal(s.calls.profile.length, 1);
});
