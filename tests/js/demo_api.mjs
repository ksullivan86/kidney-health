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
import { loadDemo, newDemo } from './demo_loader.mjs';

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
const KH = loadDemo();
const api = newDemo(KH);
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
