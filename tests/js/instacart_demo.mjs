// The demo's Instacart (js/mock/lists.js, design note 33), run in Node for tests/test_instacart_ui.py: it is on, preview shows the
// same lines as the list sync, Send answers a placeholder link that stays in the page, and the refusals. Prints one JSON object.
import { loadDemo, newDemo } from './demo_loader.mjs';

const KH = loadDemo();
const api = newDemo(KH);
const call = (method, path, body) => {
  try { return { status: 200, body: JSON.parse(JSON.stringify(api.handle(method, path, body) ?? null)) }; } catch (e) {
    return { status: e.status || 500, detail: e.detail || String(e) };
  }
};
const today = KH.util.todayStr();
const out = {};
out.get = call('GET', '/api/instacart').body;
const rice = call('GET', '/api/foods?q=rice%20white').body.foods[0];
call('POST', '/api/log', { date: today, meal: 'lunch', food_id: rice.id, servings: 2, status: 'planned' });
out.preview = call('POST', '/api/instacart/preview', { start: today, end: today }).body;
out.listPreview = call('POST', '/api/list-sync/preview', { start: today, end: today }).body;
out.send = call('POST', '/api/instacart/send', { start: today, end: today, food_ids: [rice.id] }).body;
out.none = call('POST', '/api/instacart/send', { start: today, end: today, food_ids: [987654] });
out.tooMany = call('POST', '/api/instacart/send', { start: today, end: today, food_ids: Array.from({ length: 201 }, (_, i) => i + 1) });
console.log(JSON.stringify(out));
