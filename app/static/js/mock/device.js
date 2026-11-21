/* Kidney Diet Log — device mode only: what the iPhone app asks of the page (design note 38, steps 2 and 3).

   The app packed inside the iPhone app (KH.flags.DEVICE, scripts/build_preview.py --device) runs the demo API with no server.
   This file is the page's side of the iPhone app's bridge:

   * window.KHDevice.addBody(json): the iPhone app hands over weights and blood pressure readings from Apple Health, already planned
     with the server's rules (date, time, kg or the two numbers, context, source "apple_health", the server's source key). They go
     through the same batch routes as the Health export import, so a reading already in the log is skipped; the log is saved before
     the answer, and only then does the iPhone app move its Health anchor on. Answers a JSON text: { added, skipped } per kind, or
     { error, status } when the page refused the rows.
   * KH.mock.device.lookup(request): asks the iPhone app to fetch from a food service the person turned on (USDA FoodData Central,
     Open Food Facts). The page itself never reaches the network (its CSP allows none); the app answers the service's raw JSON.

   Outside device mode none of this exists. No DOM, no storage of its own. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  // The stored log is read back at start (js/mock/persist.js boot); rows added before that would be replaced by it.
  async function booted() {
    for (let waited = 0; waited < 15000; waited += 50) {
      if (M.local && M.local.on()) return true;
      await wait(50);
    }
    return false;
  }

  async function addBody(json) {
    let rows;
    try { rows = JSON.parse(String(json)); } catch (e) { return JSON.stringify({ error: 'The rows could not be read.', status: 400 }); }
    if (!(await booted())) return JSON.stringify({ error: 'The log is not ready yet.', status: 503 });
    const added = { weights: 0, readings: 0 };
    const skipped = { weights: 0, readings: 0 };
    try {
      if (Array.isArray(rows.weights) && rows.weights.length) {
        const res = await KH.request('POST', '/api/body/weights/batch', { rows: rows.weights });
        added.weights = res.added; skipped.weights = res.skipped;
      }
      if (Array.isArray(rows.readings) && rows.readings.length) {
        const res = await KH.request('POST', '/api/body/blood-pressure/batch', { rows: rows.readings });
        added.readings = res.added; skipped.readings = res.skipped;
      }
    } catch (e) {
      return JSON.stringify({ error: String((e && (e.detail || e.message)) || 'The rows were refused.'), status: (e && e.status) || 400 });
    }
    const saved = await M.local.flush(); // saved before the answer: the iPhone app keeps its anchor only after this
    if (saved && (saved.error || saved.conflict)) return JSON.stringify({ error: saved.error || 'The log could not be saved.', status: 503 });
    if ((added.weights || added.readings) && typeof KH.toast === 'function') {
      const parts = [];
      if (added.weights) parts.push(`${added.weights} weight${added.weights === 1 ? '' : 's'}`);
      if (added.readings) parts.push(`${added.readings} blood pressure reading${added.readings === 1 ? '' : 's'}`);
      KH.toast(`Added ${parts.join(' and ')} from Apple Health.`);
    }
    return JSON.stringify({ added, skipped });
  }

  // The iPhone app's food services (step 2). Resolves the app's answer: { ok: true, json } or { error, message }.
  async function lookup(request) {
    let handler = null;
    try { handler = window.webkit.messageHandlers.bridge; } catch (e) { handler = null; }
    if (!handler) return { error: 'no_app', message: 'Food lookups need the iPhone app.' };
    try {
      const answer = await handler.postMessage(request);
      return answer && typeof answer === 'object' ? answer : { error: 'bad_answer', message: 'The app gave no answer.' };
    } catch (e) {
      return { error: 'bridge', message: String((e && e.message) || e) };
    }
  }

  window.KHDevice = { addBody };
  M.device = { lookup, addBody };
})();
