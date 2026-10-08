#!/usr/bin/env node
// Runs the demo's log twin (app/static/js/mock/log.js over js/engine/rules.js and the KH.util date helpers of
// js/core.js) on plain JSON from stdin and prints its answers, so tests/test_unknown_values_twin.py can compare them
// with app/log.py and app/periods.py on the same rows.
//
//   echo '{"profile": {...}, "rows": [...], "carb_tolerance_g": 10, "entries": [...], "summary": ["2026-10-01", "2026-10-07"]}' | node tests/js/demo_log_twin.mjs
//
// core.js builds the page at load, so it runs against a no-op stand-in for the DOM (nothing here touches the page).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FILES = ['engine/rules.js', 'core.js', 'mock/core.js', 'mock/log.js'].map((p) => `app/static/js/${p}`);

function load() {
  const noop = new Proxy(function () {}, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === Symbol.iterator ? function* () {} : k === 'length' ? 0 : noop),
    apply: () => noop,
    construct: () => noop,
  });
  const context = vm.createContext({ console, URL, URLSearchParams, setTimeout, clearTimeout });
  Object.assign(context, { document: noop, navigator: { userAgent: 'node' }, location: new URL('http://localhost/?mock=1'),
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} } });
  vm.runInContext('globalThis.window = globalThis; window.matchMedia = () => ({ matches: false, addEventListener() {} }); '
    + 'window.addEventListener = () => {};', context);
  for (const rel of FILES) vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
  return vm.runInContext('globalThis.KH', context);
}

const input = JSON.parse(readFileSync(0, 'utf8'));
const KH = load();
const out = {};
if (input.rows) out.day = KH.mock.dayFigures(input.profile, input.rows, input.carb_tolerance_g || 0);
if (input.entries && input.summary) {
  const api = Object.create(KH.mock.MockApi.prototype);
  api._entries = input.entries;
  api._profile = input.profile;
  out.summary = api._summary(input.summary[0], input.summary[1]);
  out.range = api._range(input.summary[0], input.summary[1]);
}
// v0.3.1 "running high": {"pattern": {"day", "today", "profile", "rows": [{date, meal, status, purpose, food_name, nutrients}]}}
if (input.pattern) {
  const { day, today, profile, rows } = input.pattern;
  out.pattern = KH.mock.dayPatternAlerts(day, KH.mock.patternInputs(rows, today), profile, today);
}
process.stdout.write(JSON.stringify(out));
