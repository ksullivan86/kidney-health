import test from 'node:test';
import assert from 'node:assert/strict';
import { loadDemo, newDemo } from './demo_loader.mjs';

for (const change of ['same', 'list', 'key', 'address']) {
  test(`the demo ${change === 'same' ? 'keeps' : 'clears'} the send receipt after ${change} configuration`, () => {
    const KH = loadDemo(), api = newDemo(KH);
    const day = KH.util.todayStr();
    const food = api.handle('GET', '/api/foods?q=rice').foods[0];
    api.handle('POST', '/api/log', { date: day, meal: 'lunch', food_id: food.id, servings: 1, status: 'planned' });
    const sent = api.handle('POST', '/api/list-sync/send', { start: day, end: day, food_ids: [food.id] });
    const body = { app: 'grocy', base_url: 'http://grocy.example' };
    if (change === 'list') Object.assign(body, { list_id: '9', list_name: 'New list' });
    if (change === 'key') body.key = 'new-key';
    if (change === 'address') Object.assign(body, { base_url: 'https://new.example', key: 'new-key' });
    const out = api.handle('PUT', '/api/list-sync', body);
    assert.equal(out.last_sent_at, change === 'same' ? sent.connection.last_sent_at : null);
    assert.equal(out.last_sent_count, change === 'same' ? 1 : null);
  });
}
