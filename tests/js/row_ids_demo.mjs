#!/usr/bin/env node
// One ID per row in the demo and the phone (design note 39 §8.2; the twin of schema step 38 and of app/data_import.py's free_id):
// every new food of the person's own, entry, saved meal, lab result, symptom, weight and reading gets a client_id (a lower-case
// UUID version 4); the export carries it for every kind; the import keeps it when the person has no row with it yet and gives the
// row a new one otherwise; a log kept from before (no IDs) gets one for every row, the one the phone's queue already sent when it
// has one. If-Match itself is pinned against the server by tests/data/row_version_vectors.json (node tests/js/run_vectors.mjs).
// pytest (tests/test_row_versions.py) runs it. Exits 1 on any mismatch.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadDemo, newDemo } from './demo_loader.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const FOODS = JSON.parse(readFileSync(join(ROOT, 'data', 'foods.json'), 'utf8'));
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DAY = '2026-10-05';
let checks = 0;
const ok = (fn, label) => { checks += 1; try { fn(); } catch (e) { e.message = `${label}: ${e.message}`; throw e; } };

const KH = loadDemo();
const fresh = () => { const api = new KH.mock.MockApi({ foodsData: FOODS, seed: false }); KH.mock.instance = api; return api; };
const tables = (api) => ({
  food: api._foods.filter((f) => f.source === 'custom'), entry: api._entries, meal: api._templates, lab: api._labs || [],
  symptom: api._symptoms || [], weight: api._weights || [], reading: api._readings || [],
});

// 1. Every new row of every synced kind has its own ID; a shared or built-in food has none.
const api = fresh();
const food = api.handle('POST', '/api/foods', { name: 'Rice pudding', serving_desc: '1 bowl', serving_g: 150, nutrients: { potassium_mg: 180 } });
api.handle('POST', '/api/log', { date: DAY, meal: 'lunch', food_id: food.id });
api.handle('POST', '/api/meals', { name: 'Usual', items: [{ food_id: food.id, servings: 1 }] });
api.handle('POST', '/api/labs', { analyte: 'potassium', value: 5.1, unit: 'mmol/L', taken_on: DAY });
api.handle('POST', '/api/symptoms', { date: DAY, symptom: 'itching', severity: 2 });
api.handle('POST', '/api/body/weights', { date: DAY, kg: 70.2, context: 'morning' });
api.handle('POST', '/api/body/blood-pressure', { date: DAY, systolic: 122, diastolic: 78, context: 'morning' });
const ids = [];
for (const [kind, rows] of Object.entries(tables(api))) {
  ok(() => assert.equal(rows.length, 1), `${kind}: one row`);
  ok(() => assert.match(rows[0].client_id, UUID4), `${kind}: a UUID version 4, lower-case`);
  ids.push(rows[0].client_id);
}
ok(() => assert.equal(new Set(ids).size, ids.length), 'every row its own ID');
ok(() => assert.ok(api._foods.filter((f) => f.source === 'builtin').every((f) => f.client_id == null)), 'built-in foods have none');
const copy = api.handle('POST', `/api/foods/${food.id}/copy`);
ok(() => assert.notEqual(api._food(copy.id).client_id, api._food(food.id).client_id), 'a copy is a new row with a new ID');
// an entry sent with a client_id keeps it, as before
const cid = '0f8fad5b-d9cb-469f-a165-70867728950e';
api.handle('POST', '/api/log', { date: DAY, meal: 'dinner', food_id: food.id, client_id: cid.toUpperCase() });
ok(() => assert.equal(api._entries.filter((e) => e.client_id === cid).length, 1), 'an entry keeps the ID it was sent with, lower-cased');

// 2. The sample data has IDs too.
const sample = newDemo(KH);
for (const [kind, rows] of Object.entries(tables(sample))) {
  ok(() => assert.ok(rows.every((r) => UUID4.test(r.client_id)), `${rows.filter((r) => !UUID4.test(r.client_id)).length} without`), `sample ${kind}`);
}

// 3. The export carries the ID of every kind (a shared food's is null), and the import keeps it.
KH.mock.instance = api;
const doc = api.handle('GET', '/api/me/export.json');
const byKind = { custom_foods: 'food', meal_templates: 'meal', lab_results: 'lab', symptoms: 'symptom', weights: 'weight', blood_pressures: 'reading' };
for (const [section, kind] of Object.entries(byKind)) {
  ok(() => assert.deepEqual(doc[section].map((r) => r.client_id).sort(), tables(api)[kind].map((r) => r.client_id).sort()), `export ${section}`);
}
ok(() => assert.deepEqual(doc.log_entries.map((e) => e.client_id).sort(), api._entries.map((e) => e.client_id).sort()), 'export log_entries');
ok(() => assert.deepEqual(Object.keys(doc.meal_templates[0]).slice(0, 2), ['id', 'client_id']), 'a saved meal names its ID second, as the server does');

const other = fresh();
const result = other.handle('POST', '/api/me/import?merge=true', JSON.parse(JSON.stringify(doc)));
ok(() => assert.equal(result.counts.custom_foods, 2), 'both foods imported');
for (const [section, kind] of Object.entries(byKind)) {
  ok(() => assert.deepEqual(tables(other)[kind].map((r) => r.client_id).sort(), doc[section].map((r) => r.client_id).sort()), `import keeps ${section}`);
}
ok(() => assert.deepEqual(other._entries.map((e) => e.client_id).sort(), doc.log_entries.map((e) => e.client_id).sort()), 'import keeps log_entries');

// An ID the person already has goes to a new row with a new ID (free_id); the rest of the row is imported as usual.
const taken = JSON.parse(JSON.stringify(doc));
taken.symptoms[0] = { ...taken.symptoms[0], symptom: 'cramps', note: 'another one' };
const third = other.handle('POST', '/api/me/import?merge=true', taken);
ok(() => assert.equal(third.counts.symptoms, 1), 'the changed symptom is imported');
const both = other._symptoms.filter((s) => s.date === DAY);
ok(() => assert.equal(both.length, 2), 'two symptoms now');
ok(() => assert.notEqual(both[0].client_id, both[1].client_id), 'and two IDs');

// A file whose client_id is not a UUID is refused, as on the server.
const bad = JSON.parse(JSON.stringify(doc));
bad.weights[0].client_id = 'not-a-uuid';
ok(() => assert.throws(() => fresh().handle('POST', '/api/me/import?merge=true', bad),
  (e) => e.status === 400 && /client_id/.test(e.detail)), 'a client_id that is not a UUID');

// 4. A log kept from before every row had an ID: each row gets one, the one the phone's queue sent it with when it has one.
const old = fresh();
old.handle('POST', '/api/symptoms', { date: DAY, symptom: 'itching', severity: 1 });
old.handle('POST', '/api/body/weights', { date: DAY, kg: 71, context: 'morning' });
const oldFood = old.handle('POST', '/api/foods', { name: 'Toast', serving_desc: '1 slice', serving_g: 30, nutrients: {} });
for (const rows of Object.values(tables(old))) for (const r of rows) delete r.client_id;
const queued = 'a3bb189e-8bf9-4888-9912-ace4e6543002';
old._serverSync = { v: 1, rows: { weight: { [old._weights[0].id]: { c: queued, s: 'sent' } } } };
old._fillClientIds();
ok(() => assert.equal(old._weights[0].client_id, queued), 'a sent row keeps the ID the server has');
ok(() => assert.match(old._symptoms[0].client_id, UUID4), 'the others get a new one');
ok(() => assert.match(old._food(oldFood.id).client_id, UUID4), 'and the person\'s own food');
const before = old._symptoms[0].client_id;
old._fillClientIds();
ok(() => assert.equal(old._symptoms[0].client_id, before), 'an ID is never changed once given');
const persist = readFileSync(join(ROOT, 'app', 'static', 'js', 'mock', 'persist.js'), 'utf8');
ok(() => assert.match(persist, /api\._fillClientIds\(\)/), 'a stored log gets its IDs when it is read back');

console.log(`row ids demo: ${checks} checks passed`);
