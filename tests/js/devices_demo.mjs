// The demo's sample Withings connection (js/mock/devices.js, design note 27), run in Node for tests/test_connected_devices_ui.py:
// the list, the sample readings "from Withings", Connect refused, Sync now, and Disconnect with "also delete". Prints one JSON object.
import { loadDemo, newDemo } from './demo_loader.mjs';

const KH = loadDemo();
const api = newDemo(KH);
const call = (method, path, body) => {
  try { return { status: 200, body: JSON.parse(JSON.stringify(api.handle(method, path, body) ?? null)) }; } catch (e) {
    return { status: e.status || 500, detail: e.detail || String(e) };
  }
};
const today = KH.util.todayStr();
const start = KH.util.addDays(today, -14);
const out = {};
out.list = call('GET', '/api/devices').body;
const readings = call('GET', `/api/body/blood-pressure?start=${start}&end=${today}`).body.readings;
out.sources = [...new Set(readings.map((r) => r.source))].sort();
out.origin = KH.bodyUi.originText(readings.find((r) => r.source === 'withings'));
out.start = call('POST', '/api/devices/withings/start');
out.sync = call('POST', '/api/devices/withings/sync').body;
out.remove = call('DELETE', '/api/devices/withings?delete_readings=true').body;
out.after = call('GET', '/api/devices').body.providers[0].connection;
out.left = call('GET', `/api/body/blood-pressure?start=${start}&end=${today}`).body.readings.map((r) => r.source);
console.log(JSON.stringify(out));
