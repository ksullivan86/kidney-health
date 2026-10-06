#!/usr/bin/env node
// Parity check of the browser rules engine against the server (ARCHITECTURE.md, "Frontend modules").
//
//   node tests/js/run_vectors.mjs            # exit 0 when every vector matches, 1 otherwise
//
// Loads app/static/js/engine/rules.js (a plain browser script) into a fresh V8 context whose only
// global is a bare object: the script falls back from `window` to `globalThis` and sets
// globalThis.KH.rules, so no DOM or bundler is needed. Then it replays tests/data/rules_vectors.json,
// which tests/data/gen_rules_vectors.py generates from app/nutrients.py (pytest checks that the file
// is current). No dependencies beyond Node 18+.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const ENGINE = ['app/static/js/engine/rules.js'];
const VECTORS = join(ROOT, 'tests', 'data', 'rules_vectors.json');

function loadEngine() {
  const context = vm.createContext({ console });
  for (const rel of ENGINE) vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
  const KH = vm.runInContext('globalThis.KH', context);
  if (!KH || !KH.rules) throw new Error('rules.js did not define KH.rules');
  return KH.rules;
}

// Values cross the V8 context boundary; compare plain JSON copies.
const plain = (v) => JSON.parse(JSON.stringify(v));

function main() {
  const rules = loadEngine();
  const doc = JSON.parse(readFileSync(VECTORS, 'utf8'));
  const keys = doc.nutrient_keys;
  if (!isDeepStrictEqual(keys, plain(rules.NUTRIENT_KEYS))) {
    console.error(`nutrient keys differ: vectors ${keys} engine ${rules.NUTRIENT_KEYS}`);
    return 1;
  }
  const failures = [];
  let checks = 0;
  const expect = (label, got, want) => {
    checks += 1;
    if (!isDeepStrictEqual(plain(got), want)) failures.push({ label, got: plain(got), want });
  };

  for (const c of doc.food_cases) {
    const f = doc.foods[c.food];
    const scaled = Object.fromEntries(keys.map((k) => [k, f.nutrients[k] == null ? null : Number(f.nutrients[k]) * c.servings]));
    const label = `${f.name} x${c.servings} (${c.scope})`;
    const warnings = rules.evaluateWarnings(scaled, f.flags, f.kidney_notes, c.scope);
    expect(`${label}: warnings`, warnings, c.warnings);
    expect(`${label}: kidney_rating`, rules.ratingFromWarnings(warnings), c.kidney_rating);
    const rounded = rules.roundNutrients(scaled);
    expect(`${label}: rounded`, keys.map((k) => rounded[k]), c.rounded);
  }
  doc.boundary_cases.forEach((c, i) => {
    const label = `boundary ${i} ${JSON.stringify(c.nutrients)} ${JSON.stringify(c.flags)} (${c.scope})`;
    const warnings = rules.evaluateWarnings(c.nutrients, c.flags, c.kidney_notes, c.scope);
    expect(`${label}: warnings`, warnings, c.warnings);
    expect(`${label}: kidney_rating`, rules.ratingFromWarnings(warnings), c.kidney_rating);
  });
  for (const c of doc.round_cases) expect(`round_value(${c.key}, ${c.value})`, rules.roundValue(c.key, c.value), c.expected);

  if (failures.length) {
    for (const f of failures.slice(0, 20)) console.error(`MISMATCH ${f.label}\n   js:     ${JSON.stringify(f.got)}\n   python: ${JSON.stringify(f.want)}`);
    console.error(`\n${failures.length} of ${checks} checks failed (tests/data/rules_vectors.json vs app/static/js/engine/rules.js)`);
    return 1;
  }
  console.log(`rules vectors: ${checks} checks passed (${doc.food_cases.length} food cases, ${doc.boundary_cases.length} boundary cases, ${doc.round_cases.length} rounding cases)`);
  return 0;
}

process.exitCode = main();
