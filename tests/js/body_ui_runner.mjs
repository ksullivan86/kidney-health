#!/usr/bin/env node
// Runs js/engine/body_ui.js (what the weight and blood pressure screens are made of) and the body part of js/engine/visitprep.js on
// plain JSON from stdin, so tests/test_body_ui_numbers.py can check them against the server's own functions (app/body.py).
//
//   echo '{"calls": [{"fn": "bodyUi.weightFromInput", "args": ["154.3", "lb"]}]}' | node tests/js/body_ui_runner.mjs
//
// Output: { results: [...] }, one per call, in order. `fn` is "<module>.<function>" with module bodyUi, bodyRules or visitPrep. Two calls
// are special because they return functions: "axesAt" (args: options of makeAxes, [[day, time], ...], [value, ...]) answers the x and y
// of the marks and the plot's size, and "week" (args: weights, day) is weekAverages. The engine files are evaluated in one bare context,
// as under `run_vectors.mjs`.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const context = vm.createContext({ console });
vm.runInContext('globalThis.window = globalThis;', context);
for (const file of ['rules.js', 'symptoms.js', 'body.js', 'visitprep.js', 'body_ui.js']) {
  const rel = `app/static/js/engine/${file}`;
  vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
}
const KH = vm.runInContext('globalThis.KH', context);
const modules = { bodyUi: KH.bodyUi, bodyRules: KH.bodyRules, visitPrep: KH.visitPrep };

const input = JSON.parse(readFileSync(0, 'utf8'));
const results = input.calls.map((call) => {
  if (call.fn === 'axesAt') {
    const [options, marks, values] = call.args;
    const axes = KH.bodyUi.makeAxes(options);
    return { days: axes.days, plotW: axes.plotW, plotH: axes.plotH, slot: axes.slot, x: marks.map(([day, time]) => axes.x(day, time)), y: values.map((v) => axes.y(v)) };
  }
  const [mod, name] = call.fn.split('.');
  const fn = modules[mod] && modules[mod][name];
  if (typeof fn !== 'function') throw new Error(`no function ${call.fn}`);
  return fn(...call.args);
});
process.stdout.write(JSON.stringify({ results }));
