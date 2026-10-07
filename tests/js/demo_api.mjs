#!/usr/bin/env node
// Replays requests against the demo API (app/static/js/mock/*.js over js/engine/*.js and the KH helpers of
// js/core.js, loaded in index.html's order) and prints each answer, so pytest can check the demo against the
// server's rules without a browser:
//
//   echo '[{"method": "POST", "path": "/api/log", "body": {...}}, ...]' | node tests/js/demo_api.mjs
//   → [{"ok": true, "body": {...}}, {"ok": false, "status": 400, "detail": "..."}]
//
// A fresh demo (the builtin foods of data/foods.json and its sample data) per run; requests run in order on it.
// The demo signs in as its demo admin; `{"$ref": [i, "a.b"]}` anywhere in a later request's body is replaced by
// that field of answer i (paths are plain strings: a test that needs an id in a path reads it from a first run). core.js builds the page at load, so it runs against a no-op
// stand-in for the DOM (no request touches the page).
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

function load() {
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

function resolveRefs(value, answers) {
  if (Array.isArray(value)) return value.map((v) => resolveRefs(v, answers));
  if (value && typeof value === 'object') {
    if (Array.isArray(value.$ref)) {
      const [i, path] = value.$ref;
      return String(path).split('.').reduce((o, k) => (o == null ? o : o[k]), answers[i] && answers[i].body);
    }
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, resolveRefs(v, answers)]));
  }
  return value;
}

const requests = JSON.parse(readFileSync(0, 'utf8'));
const KH = load();
const foods = JSON.parse(readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'));
const api = new KH.mock.MockApi({ foodsData: foods });
KH.mock.instance = api;
const answers = [];
for (const req of requests) {
  const path = resolveRefs(req.path, answers);
  const body = req.body === undefined ? undefined : resolveRefs(req.body, answers);
  try {
    const res = api.handle(req.method, path, body);
    answers.push({ ok: true, body: res == null ? null : JSON.parse(JSON.stringify(res)) });
  } catch (err) {
    if (!(err instanceof KH.mock.ApiError)) throw err;
    answers.push({ ok: false, status: err.status, detail: err.detail });
  }
}
process.stdout.write(JSON.stringify(answers));
