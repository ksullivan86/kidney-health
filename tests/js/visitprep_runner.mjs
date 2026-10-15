#!/usr/bin/env node
// Runs js/engine/visitprep.js (what the Visit prep page is made of) on plain JSON from stdin, so tests/test_visit_prep_numbers.py
// can check it against the server's own answers: the period summary, the lab list and the symptoms list of a seeded person.
//
//   echo '{"summary": {...}, "labs": [...], "order": ["potassium"], "symptoms": [...], "questions": ["a", " b "]}' | node tests/js/visitprep_runner.mjs
//
// Output: { averages: averageRows(summary), labs: labRows(labs, order), groups: summarise(symptoms), questions: [{ text, list, error }...] }
// (each key only when its input is given). The engine files are evaluated in one bare context, as under `run_vectors.mjs`.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const context = vm.createContext({ console });
vm.runInContext('globalThis.window = globalThis;', context);
for (const file of ['rules.js', 'symptoms.js', 'visitprep.js']) {
  const rel = `app/static/js/engine/${file}`;
  vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
}
const KH = vm.runInContext('globalThis.KH', context);
const V = KH.visitPrep;

const input = JSON.parse(readFileSync(0, 'utf8'));
const out = {};
if (input.summary) out.averages = V.averageRows(input.summary, KH.rules);
if (input.labs) out.labs = V.labRows(input.labs, input.order);
if (input.symptoms) out.groups = KH.symptomRules.summarise(input.symptoms);
if (input.questions) {
  let list = [];
  out.questions = input.questions.map((text) => {
    const res = V.addQuestion(list, text);
    list = res.list;
    return { text, list: res.list.slice(), error: res.error };
  });
}
if (input.range) out.range = V.periodRange(input.range.today, input.range.days, (iso, n) => {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
});
process.stdout.write(JSON.stringify(out));
