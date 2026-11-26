/* Kidney Diet Log — device mode only: reminders as the iPhone's own notifications (design note 35 §7).

   In the iPhone app there is no server and no Web Push. The reminders are kept in the log on the phone (js/mock/reminders.js), and
   this file asks the app to replace its pending notifications with a fresh plan:

   * plan(reminders, now, eatenToday): the next 7 days as single notifications, soonest first, at most 60 (iOS keeps 64). Only
     reminders that are on, on their days, at their time, still in the future. A meal reminder for today is left out when that
     meal already has eaten food logged today (app/reminders.py run_due does the same). Times are the phone's own: local dates.
   * sync(): plans and sends { kind: 'reminders', action: 'schedule', items } to the app's bridge. It runs after each save of the
     log, after a reminder changes, and when the app comes back to the front. The app answers { ok, scheduled, permission }.
   * status(), allow(), test(), openSettings(): the Settings screen's questions to the app (js/views/reminders.js).

   The page sends only the kind and the meal of each one. The app writes the words (title "Food log", the server's bodies), so no
   other text reaches the lock screen. Outside device mode none of this runs. No DOM, no storage of its own. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH && KH.mock;
  if (!M) return;

  const DAYS_AHEAD = 7;
  const MAX_PENDING = 60;
  const SCREENS = { log_meal: 'add', plan_tomorrow: 'plan', weigh_in: 'today' }; // app/reminders.py PAGES
  const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;
  const NO_APP = 'Notifications need the iPhone app.';

  const device = () => !!(KH.flags && KH.flags.DEVICE === true);
  const pad = (n) => String(n).padStart(2, '0');
  const isoDay = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  function plan(reminders, now, eatenToday, { days = DAYS_AHEAD, max = MAX_PENDING } = {}) {
    const eaten = new Set(eatenToday || []);
    const out = [];
    for (let offset = 0; offset < days; offset += 1) {
      const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
      const bit = 1 << ((day.getDay() + 6) % 7); // bit 0 is Monday, as on the server
      for (const r of reminders || []) {
        if (!r || !r.enabled || !SCREENS[r.kind] || !(Number(r.days) & bit)) continue;
        const m = TIME_RE.exec(String(r.time || ''));
        if (!m) continue;
        const at = new Date(day.getFullYear(), day.getMonth(), day.getDate(), Number(m[1]), Number(m[2]));
        if (at.getTime() <= now.getTime()) continue;
        if (offset === 0 && r.kind === 'log_meal' && eaten.has(r.meal)) continue;
        out.push({ id: `reminder-${r.id}-${isoDay(day)}`, at: `${isoDay(day)}T${m[1]}:${m[2]}`, kind: r.kind,
          meal: r.kind === 'log_meal' ? r.meal : null, t: at.getTime() });
      }
    }
    out.sort((a, b) => a.t - b.t || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    return out.slice(0, max).map(({ id, at, kind, meal }) => ({ id, at, kind, meal }));
  }

  function bridge() {
    try { return (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.bridge) || null; } catch (e) { return null; }
  }
  async function ask(action, extra = {}) {
    const handler = bridge();
    if (!handler) return { error: 'no_app', message: NO_APP };
    try {
      const answer = await handler.postMessage({ kind: 'reminders', action, ...extra });
      return answer && typeof answer === 'object' ? answer : { error: 'bad_answer', message: 'The app gave no answer.' };
    } catch (e) {
      return { error: 'bridge', message: String((e && e.message) || e) };
    }
  }

  // What the plan is made from: the reminders kept on the phone and the meals eaten today.
  function current(now) {
    const api = M.instance;
    if (!api || typeof api._remindersState !== 'function') return null;
    const today = isoDay(now);
    const eaten = (api._entries || []).filter((e) => e.date === today && e.status === 'eaten').map((e) => e.meal);
    return plan(api._remindersState().reminders, now, eaten);
  }

  let clock = () => new Date(); // tests set another
  let running = null;
  let again = false;
  let last = null; // { at, items, answer }: the last plan sent (tests, and Settings)
  async function syncOnce() {
    const now = clock();
    const items = current(now);
    if (!items) return { skipped: 'not_ready' };
    const answer = await ask('schedule', { items });
    last = { at: now.toISOString(), items: items.length, answer };
    return answer;
  }
  async function sync() {
    if (!device()) return { skipped: 'not_device' };
    if (!(M.local && typeof M.local.on === 'function' && M.local.on())) return { skipped: 'not_ready' }; // the log is read back first
    if (running) { again = true; return running; }
    running = (async () => {
      let out;
      try { do { again = false; out = await syncOnce(); } while (again); return out; } finally { running = null; }
    })();
    return running;
  }
  let timer = null;
  function soon(ms = 300) {
    if (!device()) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; sync().catch(() => { /* the next save tries again */ }); }, ms);
  }

  // When: after each save of the log (a meal logged can drop today's reminder), at the start once the log is read back, and when
  // the app comes back to the front (a new day).
  if (M.local && typeof M.local.subscribe === 'function') {
    let lastSaved = null;
    M.local.subscribe((s) => { if (s && s.on && s.savedAt !== lastSaved) { lastSaved = s.savedAt; soon(); } });
  }
  try {
    if (typeof document !== 'undefined' && document && typeof document.addEventListener === 'function') {
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') soon(1000); });
    }
  } catch (e) { /* no document */ }

  async function allow() {
    const answer = await ask('allow');
    if (answer && answer.permission === 'allowed') await sync();
    return answer;
  }

  M.phoneReminders = {
    DAYS_AHEAD, MAX_PENDING, SCREENS,
    plan, sync, soon,
    status: () => ask('status'),
    allow,
    test: () => ask('test'),
    openSettings: () => ask('openSettings'),
    last: () => last,
    _setClock(fn) { clock = fn || (() => new Date()); },
  };
})();
