// Loads the whole demo (app/static/js/engine/*.js, mock/*.js and core.js, in index.html's order) into one V8 context whose
// DOM is a no-op stand-in, and returns its KH object. core.js builds the page at load, so it needs something to build on;
// no request made through the demo API touches the page.
//
//   import { loadDemo, newDemo } from './demo_loader.mjs';
//   const KH = loadDemo();                 // the scripts, nothing started
//   const api = newDemo(KH);               // a fresh demo person with the sample data, signed in as the demo admin
//
// Used by tests/js/demo_api.mjs (requests replayed for pytest) and tests/js/run_vectors.mjs (the symptoms vectors).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const STATIC = join(ROOT, 'app', 'static');

function scripts() {
  const html = readFileSync(join(STATIC, 'index.html'), 'utf8');
  return [...html.matchAll(/<script[^>]*\ssrc="([^"]+)"/g)].map((m) => m[1])
    .filter((src) => /^js\/(engine\/|mock\/|core\.js$)/.test(src));
}

export function loadDemo() {
  const noop = new Proxy(function () {}, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => '' : k === Symbol.iterator ? function* () {} : k === 'length' ? 0 : noop),
    apply: () => noop,
    construct: () => noop,
  });
  const context = vm.createContext({ console, URL, URLSearchParams, setTimeout, clearTimeout, TextEncoder, TextDecoder, crypto });
  Object.assign(context, { document: noop, navigator: { userAgent: 'node' }, location: new URL('http://localhost/?mock=1'),
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} } });
  vm.runInContext('globalThis.window = globalThis; window.matchMedia = () => ({ matches: false, addEventListener() {} }); '
    + 'window.addEventListener = () => {};', context);
  for (const rel of scripts()) vm.runInContext(readFileSync(join(STATIC, rel), 'utf8'), context, { filename: rel });
  return vm.runInContext('globalThis.KH', context);
}

// A fresh demo API (the builtin foods of data/foods.json and its sample data), registered as the page's instance.
export function newDemo(KH) {
  const foods = JSON.parse(readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'));
  const api = new KH.mock.MockApi({ foodsData: foods });
  KH.mock.instance = api;
  return api;
}
