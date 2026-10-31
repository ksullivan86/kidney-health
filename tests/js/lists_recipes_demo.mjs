// The demo's list app and recipe import (js/mock/lists.js, design note 30), run in Node for tests/test_lists_recipes_ui.py: the sample
// Grocy, Test, preview and Send against the fake list app in the page, the address and key rules, the sample recipe page for any
// link, pasted ingredients, a bad link, and saving the draft as a recipe. Prints one JSON object.
import { loadDemo, newDemo } from './demo_loader.mjs';

const KH = loadDemo();
const api = newDemo(KH);
const call = (method, path, body) => {
  try { return { status: 200, body: JSON.parse(JSON.stringify(api.handle(method, path, body) ?? null)) }; } catch (e) {
    return { status: e.status || 500, detail: e.detail || String(e), extra: e.extra || null };
  }
};
const today = KH.util.todayStr();
const out = {};
out.get = call('GET', '/api/list-sync').body;
out.test = call('POST', '/api/list-sync/test').body;
const rice = call('GET', '/api/foods?q=rice%20white').body.foods[0];
call('POST', '/api/log', { date: today, meal: 'lunch', food_id: rice.id, servings: 2, status: 'planned' });
out.preview = call('POST', '/api/list-sync/preview', { start: today, end: today }).body;
out.send = call('POST', '/api/list-sync/send', { start: today, end: today, food_ids: [rice.id] }).body;
out.sent = api._listsState().sent;
out.noKey = call('PUT', '/api/list-sync', { app: 'mealie', base_url: 'https://mealie.example' });
out.badUrl = call('PUT', '/api/list-sync', { app: 'grocy', base_url: 'https://kim:pw@grocy.example', key: 'k' });
out.keep = call('PUT', '/api/list-sync', { app: 'grocy', base_url: 'http://grocy.example/' }).body;
out.remove = call('DELETE', '/api/list-sync');
out.afterRemove = call('GET', '/api/list-sync').body.connection;
out.info = call('GET', '/api/recipe-import').body;
out.page = call('POST', '/api/recipe-import/page', { url: 'https://recipes.example.com/anything' }).body;
out.badLink = call('POST', '/api/recipe-import/page', { url: 'https://recipes.example.com:8080/x' });
out.text = call('POST', '/api/recipe-import/text', { text: 'For the rice:\n2 cups cooked white rice\n1 tsp dried thyme', name: 'Rice', servings: 2 }).body;
const items = out.page.lines.filter((l) => l.matches.length && l.matches[0].servings != null)
  .map((l) => ({ food_id: l.matches[0].food.id, servings: l.matches[0].servings }));
out.saved = call('POST', '/api/meals', { name: out.page.name, servings_made: out.page.servings_made, steps: out.page.steps,
  source_url: out.page.source_url, note: 'Not counted: 1 tsp dried thyme', items }).body;
console.log(JSON.stringify(out));
