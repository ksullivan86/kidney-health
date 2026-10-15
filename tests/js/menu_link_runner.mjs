#!/usr/bin/env node
// Runs js/engine/menu_link.js (the reader of the handbook's "Add this day to my plan" link) on plain JSON from stdin
// and prints its answers, so tests/test_menu_plan.py can check every link the handbook build writes against the real
// built-in food list the server answers with.
//
//   echo '{"hashes": ["#plan-menu?items=b1x1"], "foods": [...], "date": "2026-10-20"}' | node tests/js/menu_link_runner.mjs
//
// Output: [{ parsed, resolved: { rows: [{ meal, fdc_id, servings, food_id, source }], skipped }, batch: [...] }, ...] with
// the batch body built for `date` from every resolved row and client ids "id-1", "id-2", ...
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FILE = 'app/static/js/engine/menu_link.js';
const context = vm.createContext({ console });
vm.runInContext(readFileSync(join(ROOT, FILE), 'utf8'), context, { filename: FILE });
const L = vm.runInContext('globalThis.KH.menuLink', context);

const input = JSON.parse(readFileSync(0, 'utf8'));
const out = input.hashes.map((hash) => {
  const parsed = L.parse(hash);
  if (!parsed.ok) return { parsed, resolved: null, batch: null };
  const resolved = L.resolve(parsed.items, input.foods);
  let n = 0;
  const batch = L.batchEntries(resolved.rows, input.date, () => `00000000-0000-4000-8000-${String(++n).padStart(12, '0')}`);
  return {
    parsed,
    resolved: {
      rows: resolved.rows.map((r) => ({ meal: r.meal, fdc_id: r.fdc_id, servings: r.servings, food_id: r.food.id, source: r.food.source })),
      skipped: resolved.skipped,
    },
    batch,
  };
});
process.stdout.write(JSON.stringify(out));
