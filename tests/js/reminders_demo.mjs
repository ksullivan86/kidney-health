// The demo's reminders (js/mock/reminders.js, design note 35), run in Node for tests/test_reminders_ui.py: on, add / change /
// remove, the refusals, a placeholder device, and a test that says nothing was sent. Prints one JSON object.
import { loadDemo, newDemo } from './demo_loader.mjs';

const KH = loadDemo();
const api = newDemo(KH);
const call = (method, path, body) => {
  try { return { status: 200, body: JSON.parse(JSON.stringify(api.handle(method, path, body) ?? null)) }; } catch (e) {
    return { status: e.status || 500, detail: e.detail || String(e) };
  }
};
const out = {};
out.get = call('GET', '/api/reminders').body;
out.noDevice = call('POST', '/api/reminders/test');
out.add = call('POST', '/api/reminders', { kind: 'log_meal', meal: 'lunch', time: '12:00', days: 127, time_zone: 'America/Chicago' }).body;
out.change = call('PATCH', `/api/reminders/${out.add.id}`, { time: '12:30', days: 31 }).body;
out.noMeal = call('POST', '/api/reminders', { kind: 'log_meal', time: '12:00' });
out.mealHere = call('POST', '/api/reminders', { kind: 'weigh_in', meal: 'lunch', time: '12:00' });
out.badTime = call('POST', '/api/reminders', { kind: 'weigh_in', time: '7:00' });
out.noDays = call('POST', '/api/reminders', { kind: 'weigh_in', time: '07:00', days: 0 });
out.badZone = call('POST', '/api/reminders', { kind: 'weigh_in', time: '07:00', time_zone: 'Mars/Olympus' });
out.insulin = call('POST', '/api/reminders', { kind: 'insulin', time: '07:00' });
out.badHost = call('POST', '/api/reminders/subscriptions', { endpoint: 'https://example.org/push', keys: { p256dh: 'x', auth: 'y' } });
out.device = call('POST', '/api/reminders/subscriptions', { endpoint: 'https://web.push.apple.com/demo-1', keys: { p256dh: 'x', auth: 'y' } }).body;
out.test = call('POST', '/api/reminders/test').body;
out.after = call('GET', '/api/reminders').body;
out.export = call('GET', '/api/me/export.json').body.reminders;
out.removeDevice = call('DELETE', `/api/reminders/subscriptions/${out.device.id}`).status;
out.remove = call('DELETE', `/api/reminders/${out.add.id}`).status;
out.removeAgain = call('DELETE', `/api/reminders/${out.add.id}`).status;
out.texts = KH.mock.REMINDER_TEXTS;
console.log(JSON.stringify(out));
