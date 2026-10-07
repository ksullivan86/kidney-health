/* Kidney Diet Log — offline data and the outbox (KH.offline; note 02 R5).

   When the server cannot be reached (no network, the home server away, a phone that froze the app), the
   person can still open the app, see what this device saved, find foods it has seen and log food. Entries
   wait on the device and reach the server exactly once when it is back.

   * Storage: IndexedDB database `kdl` (no library), version 1, stores
       meta       key string                 {key, value}: last full food download, …
       snapshots  key [user_id, path]        {user_id, path, data, fetched_at}: the last answer of a GET the app
                                             can show offline: /api/auth/status (user 0, to start offline), the
                                             profile, the log of the last 14 days and the next 7, range and
                                             summary answers, saved meals, categories, the handbook links
       foods      key [user_id, id]          every food this person's device has seen (search results, barcode
                                             answers, a daily download of the visible foods), for offline search
       outbox     key client_id, index created_at
                                             {client_id, user_id, kind, method, path, body, food, created_at,
                                              attempts, state: 'pending'|'failed', last_error}
     The demo and the preview keep the same tables in memory only (they store nothing on the device); a browser
     without IndexedDB does the same and Settings says so.
   * Queued while unreachable (R5 "queueable"): POST /api/log, POST /api/log/quick and POST /api/log/mark-eaten.
     Every POST /api/log and /quick carries a fresh client_id (a v4 UUID) from its first try, so a request that
     reached the server before the connection dropped is answered "existing", never logged twice. The caller gets
     the entry as it will look (`pending: true`; warnings worked out here with the rules twin js/engine/rules.js).
     Everything else that needs the server (edits, deletes, profile, barcodes, AI) fails with "Cannot reach the
     server" as before.
   * Sync: FIFO under the Web Lock `kdl-sync` (one tab at a time; a plain-HTTP page has no Web Locks, and the
     client_id keeps a double send harmless). Consecutive POST /api/log items go together through POST
     /api/log/batch (≤ 40, all or nothing on the server); quick adds and mark-eaten one by one. The first network
     error, 5xx or 429 stops the run (tried again later); a 4xx marks that item `failed` with the server's reason
     and the rest go on; failed items are shown with Retry and Discard and never dropped silently. Runs at start,
     when the page becomes visible or is shown again, on `online`, after any successful API call, and every 30 s
     while the page is visible and something waits.
   * Timeouts: GETs the app can answer offline and the queueable writes give up after 6 s; other GETs after 20 s.
   * Today shows waiting entries with a "waiting to sync" (or "not saved") badge, in the day's totals; the header
     badge shows "Offline" and the number waiting; Settings → This device lists them (Sync now, Retry, Discard,
     Discard all). Sign-out asks first when something waits (the server's Clear-Site-Data and the purge remove it).
   * Resume: when the page becomes visible on a new local day and Today showed "today", it moves to the new day.

   Exposes KH.offline and KH.net (the hooks js/core.js calls). */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, clear, state, toast, util, rules } = KH;
  const { MOCK } = KH.flags;

  const DB_NAME = 'kdl';
  const DB_VERSION = 1;
  const FAST_MS = 6000; // R5: every fetch the app can do without the server gives up after 6 s
  const SLOW_MS = 20000; // other reads: still not "minutes"
  const SYNC_EVERY_MS = 30000;
  const DAYS_BACK = 13; // the last 14 days of /api/log?date=
  const DAYS_AHEAD = 7; // and a week of plans
  const MAX_SEARCH_SNAPSHOTS = 24; // range and summary answers kept
  const BATCH_MAX = 40;
  const FULL_FOODS_EVERY_MS = 24 * 3600 * 1000;
  const DEVICE_USER = 0; // snapshots that come before anyone is known (GET /api/auth/status)
  const KINDS = { 'POST /api/log': 'entry', 'POST /api/log/quick': 'quick', 'POST /api/log/mark-eaten': 'mark' };

  // ---------------------------------------------------------------------------
  // Storage: IndexedDB, or memory (demo, preview, no IndexedDB)
  // ---------------------------------------------------------------------------
  const KEYS = { meta: 'key', snapshots: ['user_id', 'path'], foods: ['user_id', 'id'], outbox: 'client_id' };
  let persistent = false;
  let dbPromise = null;
  const memory = { meta: new Map(), snapshots: new Map(), foods: new Map(), outbox: new Map() };
  const memKey = (name, value) => JSON.stringify(Array.isArray(KEYS[name]) ? KEYS[name].map((k) => value[k]) : value[KEYS[name]]);

  function openDb() {
    if (MOCK) return Promise.resolve(null);
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve) => {
      let req;
      try { req = window.indexedDB ? window.indexedDB.open(DB_NAME, DB_VERSION) : null; } catch (e) { req = null; }
      if (!req) { resolve(null); return; }
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta', { keyPath: 'key' });
        if (!db.objectStoreNames.contains('snapshots')) db.createObjectStore('snapshots', { keyPath: KEYS.snapshots });
        if (!db.objectStoreNames.contains('foods')) db.createObjectStore('foods', { keyPath: KEYS.foods });
        if (!db.objectStoreNames.contains('outbox')) db.createObjectStore('outbox', { keyPath: 'client_id' }).createIndex('created_at', 'created_at');
      };
      req.onsuccess = () => {
        const db = req.result;
        // Settings → "Clear offline data", sign-out or another tab deletes the database: let it.
        db.onversionchange = () => { db.close(); dbPromise = null; };
        persistent = true;
        resolve(db);
      };
      req.onerror = () => { console.warn('Offline storage unavailable; entries waiting to sync are kept only while this page is open.', req.error); resolve(null); };
      req.onblocked = () => resolve(null);
    });
    return dbPromise;
  }
  function tx(db, name, mode, fn) {
    return new Promise((resolve, reject) => {
      let out;
      const t = db.transaction(name, mode);
      t.oncomplete = () => resolve(out);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error || new Error('aborted'));
      const r = fn(t.objectStore(name));
      if (r) r.onsuccess = () => { out = r.result; };
    });
  }
  const store = {
    async get(name, key) {
      const db = await openDb();
      if (!db) return memory[name].get(JSON.stringify(key)) || null;
      try { return (await tx(db, name, 'readonly', (s) => s.get(key))) || null; } catch (e) { console.warn('Offline storage read failed:', e); return null; }
    },
    async put(name, value) {
      const db = await openDb();
      if (!db) { memory[name].set(memKey(name, value), value); return; }
      try { await tx(db, name, 'readwrite', (s) => s.put(value)); } catch (e) { console.warn('Offline storage write failed:', e); memory[name].set(memKey(name, value), value); }
    },
    async del(name, key) {
      const db = await openDb();
      memory[name].delete(JSON.stringify(key));
      if (!db) return;
      try { await tx(db, name, 'readwrite', (s) => s.delete(key)); } catch (e) { console.warn('Offline storage delete failed:', e); }
    },
    async all(name) {
      const db = await openDb();
      const mem = [...memory[name].values()];
      if (!db) return mem;
      try { return [...((await tx(db, name, 'readonly', (s) => s.getAll())) || []), ...mem]; } catch (e) { console.warn('Offline storage read failed:', e); return mem; }
    },
  };

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  function uuid4() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    const b = window.crypto.getRandomValues(new Uint8Array(16)); // works over plain HTTP too
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const x = [...b].map((v) => v.toString(16).padStart(2, '0')).join('');
    return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
  }
  const userId = () => (state.me && Number.isInteger(state.me.id) ? state.me.id : null);
  const nowIso = () => new Date().toISOString();
  function pathOf(path) { try { return new URL(path, 'http://app.invalid'); } catch (e) { return null; } }
  function kindOf(method, path) { const u = pathOf(path); return u ? KINDS[`${method} ${u.pathname}`] || null : null; }
  const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));
  // Answers served from this device, with when they were saved (views say "Saved at …").
  const servedOffline = new WeakMap();
  function markOffline(obj, info) { if (obj && typeof obj === 'object') servedOffline.set(obj, info); return obj; }

  // Which GET answers are kept for offline use; the key path (null = not kept).
  function snapshotPath(path) {
    const u = pathOf(path);
    if (!u) return null;
    const p = u.pathname;
    if (['/api/auth/status', '/api/profile', '/api/handbook', '/api/foods/categories', '/api/meals', '/api/me'].includes(p)) return p;
    if (p === '/api/log') {
      const date = u.searchParams.get('date');
      if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
      const today = util.todayStr();
      if (date < util.addDays(today, -DAYS_BACK) || date > util.addDays(today, DAYS_AHEAD)) return null;
      return `/api/log?date=${date}`;
    }
    if (p === '/api/log/range' || p === '/api/log/summary') return `${p}${u.search}`;
    return null;
  }
  function snapshotUser(key) { return key === '/api/auth/status' ? DEVICE_USER : userId(); }

  // ---------------------------------------------------------------------------
  // Connection state, badge and announcements
  // ---------------------------------------------------------------------------
  let offline = false;
  let syncing = false;
  let counts = { pending: 0, failed: 0 };
  const listeners = new Set();
  function notify() { for (const fn of listeners) { try { fn(); } catch (e) { console.error(e); } } }
  function announce(text) { const el = $('#sync-live'); if (el) { el.textContent = ''; setTimeout(() => { el.textContent = text; }, 50); } }
  function setOffline(value) {
    if (offline === value) return;
    offline = value;
    renderBadge();
    if (value) announce('Your server cannot be reached. Entries you add are kept on this device and sync when it is back.');
    notify();
  }
  function renderBadge() {
    const badge = $('#sync-badge');
    if (!badge) return;
    const waiting = counts.pending + counts.failed;
    const show = !!state.me && (offline || waiting > 0);
    badge.hidden = !show;
    if (!show) return;
    badge.classList.toggle('failed', counts.failed > 0);
    badge.classList.toggle('syncing', syncing);
    const parts = [];
    if (offline) parts.push('Offline');
    if (counts.failed) parts.push(`${counts.failed} not saved`);
    if (counts.pending) parts.push(`${counts.pending} to sync`);
    $('#sync-badge-text').textContent = parts.join(' · ');
    const long = [offline ? 'Your server cannot be reached.' : '', counts.pending ? `${counts.pending} ${counts.pending === 1 ? 'entry is' : 'entries are'} waiting to sync.` : '',
      counts.failed ? `${counts.failed} could not be saved: review ${counts.failed === 1 ? 'it' : 'them'}.` : ''].filter(Boolean).join(' ');
    badge.setAttribute('aria-label', `${long} Open Settings, This device.`);
    badge.title = long;
  }
  async function refreshCounts() {
    const items = await myItems();
    counts = { pending: items.filter((i) => i.state !== 'failed').length, failed: items.filter((i) => i.state === 'failed').length };
    renderBadge();
    notify();
    return counts;
  }
  $('#sync-badge').addEventListener('click', () => {
    KH.router.show('settings');
    setTimeout(() => {
      const sec = $('#set-device');
      if (sec) { sec.scrollIntoView({ block: 'start' }); const head = $('#set-device-h'); if (head) { head.tabIndex = -1; head.focus(); } }
    }, 50);
  });

  // ---------------------------------------------------------------------------
  // The outbox
  // ---------------------------------------------------------------------------
  async function allItems() { return (await store.all('outbox')).sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0)); }
  async function myItems() { const uid = userId(); return uid == null ? [] : (await allItems()).filter((i) => i.user_id === uid); }

  async function knownFood(foodId) {
    const uid = userId();
    if (uid == null) return null;
    const row = await store.get('foods', [uid, Number(foodId)]);
    return row ? row.food : null;
  }
  // The per-serving values and flags of what an item logs (a known food, or the quick add's own numbers).
  function itemFood(item) {
    if (item.kind === 'quick') {
      const b = item.body;
      const flags = [...(b.flags || [])];
      const scan = KH.additives && b.ingredients_text ? KH.additives.scan([], b.ingredients_text, b.name) : { flags: [], kidney_notes: null };
      for (const f of scan.flags) if (!flags.includes(f)) flags.push(f);
      const nutrients = {};
      for (const k of rules.NUTRIENT_KEYS) nutrients[k] = b.nutrients && b.nutrients[k] != null ? Number(b.nutrients[k]) : null;
      nutrients.fluid_ml = flags.includes('counts_as_fluid') ? (nutrients.fluid_ml != null ? nutrients.fluid_ml : Number(b.serving_g || 100)) : 0;
      return { id: null, name: b.name, nutrients, flags, kidney_notes: scan.kidney_notes || null, serving_g: Number(b.serving_g || 100) };
    }
    return item.food || null;
  }
  // The entry an item will create, as the server would answer it (warnings from the rules twin).
  function entryView(item) {
    const b = item.body || {};
    const food = itemFood(item);
    let servings = b.servings != null ? Number(b.servings) : 1;
    let grams = null;
    if (item.kind === 'entry' && b.grams != null && food && food.serving_g) { grams = Number(b.grams); servings = grams / Number(food.serving_g); }
    const scaled = food ? rules.scaleNutrients(food.nutrients, servings) : Object.fromEntries(rules.NUTRIENT_KEYS.map((k) => [k, null]));
    const warnings = food ? rules.evaluateWarnings(scaled, food.flags || [], food.kidney_notes || null, 'in this entry') : [];
    const hypo = b.purpose === 'hypo' || (b.purpose == null && food && (food.flags || []).includes('hypo_treatment'));
    return { id: `pending:${item.client_id}`, date: b.date, meal: b.meal, food_id: food ? food.id : b.food_id || null,
      food_name: food ? food.name : b.name || 'A food', servings: Math.round(servings * 1000) / 1000, grams, note: b.note || null,
      status: b.status === 'planned' ? 'planned' : 'eaten', nutrients: rules.roundNutrients(scaled), raw: scaled, warnings,
      kidney_rating: rules.ratingFromWarnings(warnings), purpose: hypo ? 'hypo' : null, client_id: item.client_id,
      created_at: item.created_at, updated_at: item.created_at, pending: true, failed: item.state === 'failed', last_error: item.last_error || null };
  }

  async function enqueue(method, path, body) {
    const kind = kindOf(method, path);
    const uid = userId();
    if (!kind || uid == null || !body || typeof body !== 'object') return undefined;
    const item = { client_id: kind === 'mark' ? uuid4() : body.client_id || uuid4(), user_id: uid, kind, method, path, body: clone(body),
      food: kind === 'entry' ? await knownFood(body.food_id) : null, created_at: nowIso(), attempts: 0, state: 'pending', last_error: null };
    if (kind !== 'mark') item.body.client_id = item.client_id;
    await store.put('outbox', item);
    await refreshCounts();
    announce('Saved on this device. It will sync when your server can be reached.');
    if (kind === 'mark') {
      const day = state.day && state.day.date === body.date ? state.day : null;
      const n = day ? (day.entries || []).filter((e) => e.status === 'planned' && !e.pending && (!body.meal || e.meal === body.meal)).length : 0;
      return { updated: n, pending: true };
    }
    return entryView(item);
  }

  async function discard(clientId) {
    await store.del('outbox', clientId);
    await refreshCounts();
    refreshViews();
  }
  async function discardAll() {
    for (const item of await myItems()) await store.del('outbox', item.client_id);
    await refreshCounts();
    refreshViews();
  }
  async function retry(clientId) {
    const item = await store.get('outbox', clientId);
    if (!item) return;
    item.state = 'pending'; item.last_error = null; item.attempts = 0;
    await store.put('outbox', item);
    await refreshCounts();
    await syncNow();
  }

  // ---------------------------------------------------------------------------
  // Sync
  // ---------------------------------------------------------------------------
  let syncPromise = null;
  function syncNow() {
    if (syncPromise) return syncPromise;
    syncPromise = (async () => {
      try {
        if (userId() == null || offlineNow()) return { sent: 0 };
        const run = () => syncRun();
        if (navigator.locks && typeof navigator.locks.request === 'function') {
          return await navigator.locks.request('kdl-sync', { ifAvailable: true }, (lock) => (lock ? run() : { sent: 0, busy: true }));
        }
        return await run();
      } finally { syncPromise = null; }
    })();
    return syncPromise;
  }
  // The item index a batch failure names: "entries.3.servings: …", "entries[3]: food 9 not found", "entries[1].client_id repeats …".
  function failedIndex(detail) {
    const m = /entries(?:\.|\[)(\d+)/.exec(String(detail || ''));
    return m ? Number(m[1]) : null;
  }
  function cleanReason(detail) {
    return String(detail || 'The server refused this entry.').replace(/^entries(?:\.\d+\.|\[\d+\][.:]?\s?)/, '').replace(/^\w+: /, (m) => m);
  }
  async function markFailed(item, err) {
    item.state = 'failed'; item.attempts += 1; item.last_error = cleanReason(err.detail || err.message);
    await store.put('outbox', item);
  }
  const STOP = Symbol('stop');
  // A request of the run: STOP on a network error, 5xx, 429 or a sign-in problem; the error for any other 4xx.
  async function send(path, body) {
    try { return { ok: await KH.request('POST', path, body, { noQueue: true, quiet401: true }) }; } catch (err) {
      if (err.status === 0 || err.status >= 500 || err.status === 429 || err.status === 401 || err.status === 403) {
        if (err.status === 0 || err.status >= 500) setOffline(true);
        return STOP;
      }
      return { error: err };
    }
  }
  async function syncRun() {
    syncing = true; renderBadge();
    let sent = 0; let failed = 0;
    try {
      let items = (await myItems()).filter((i) => i.state !== 'failed');
      while (items.length) {
        const head = items[0];
        if (head.kind === 'entry') {
          let chunk = [];
          for (const it of items) { if (it.kind !== 'entry' || chunk.length >= BATCH_MAX) break; chunk.push(it); }
          // A batch is all or nothing on the server: drop the item it names and send the rest again.
          for (;;) {
            if (!chunk.length) break;
            const r = await send('/api/log/batch', { entries: chunk.map((i) => i.body) });
            if (r === STOP) return { sent, failed, stopped: true };
            if (r.ok) {
              for (const it of chunk) await store.del('outbox', it.client_id);
              sent += chunk.length;
              break;
            }
            const index = failedIndex(r.error.detail);
            if (index != null && chunk[index]) {
              await markFailed(chunk[index], r.error); failed += 1;
              chunk = chunk.filter((_, i) => i !== index);
              continue;
            }
            // No item named: send them one by one to find the one the server refuses.
            for (const it of chunk) {
              const one = await send('/api/log', it.body);
              if (one === STOP) return { sent, failed, stopped: true };
              if (one.ok) { await store.del('outbox', it.client_id); sent += 1; } else { await markFailed(it, one.error); failed += 1; }
            }
            break;
          }
        } else {
          const r = await send(head.path, head.body);
          if (r === STOP) return { sent, failed, stopped: true };
          if (r.ok) { await store.del('outbox', head.client_id); sent += 1; } else { await markFailed(head, r.error); failed += 1; }
        }
        items = (await myItems()).filter((i) => i.state !== 'failed');
      }
      setOffline(false);
      return { sent, failed };
    } finally {
      syncing = false;
      await refreshCounts();
      if (sent || failed) {
        const words = [];
        if (sent) words.push(`${sent} ${sent === 1 ? 'entry' : 'entries'} synced`);
        if (failed) words.push(`${failed} could not be saved (see Settings → This device)`);
        announce(`${words.join('; ')}.`);
        if (sent) toast(`${words[0].charAt(0).toUpperCase()}${words[0].slice(1)}`, 'ok');
        refreshViews();
      }
    }
  }
  function refreshViews() {
    state.dayLoadedFor = null; state.plan = null; state.trends = null; state.summary = null;
    if (state.view === 'today' && KH.views.today && typeof KH.views.today.loadDay === 'function') KH.views.today.loadDay();
  }

  // ---------------------------------------------------------------------------
  // Saved copies (snapshots) and the foods this device has seen
  // ---------------------------------------------------------------------------
  async function saveSnapshot(key, data) {
    const uid = snapshotUser(key);
    if (uid == null) return;
    await store.put('snapshots', { user_id: uid, path: key, data: clone(data), fetched_at: nowIso() });
    if (key.startsWith('/api/log/range') || key.startsWith('/api/log/summary') || key.startsWith('/api/log?date=')) pruneSnapshots(uid).catch(() => {});
  }
  async function pruneSnapshots(uid) {
    const today = util.todayStr();
    const mine = (await store.all('snapshots')).filter((s) => s.user_id === uid);
    for (const s of mine) {
      const m = /^\/api\/log\?date=(\d{4}-\d{2}-\d{2})$/.exec(s.path);
      if (m && (m[1] < util.addDays(today, -DAYS_BACK) || m[1] > util.addDays(today, DAYS_AHEAD))) await store.del('snapshots', [uid, s.path]);
    }
    const ranges = mine.filter((s) => s.path.startsWith('/api/log/range') || s.path.startsWith('/api/log/summary'))
      .sort((a, b) => (a.fetched_at < b.fetched_at ? 1 : -1));
    for (const s of ranges.slice(MAX_SEARCH_SNAPSHOTS)) await store.del('snapshots', [uid, s.path]);
  }
  async function readSnapshot(key) {
    const uid = snapshotUser(key);
    if (uid == null) return null;
    return store.get('snapshots', [uid, key]);
  }
  async function rememberFoods(foods) {
    const uid = userId();
    if (uid == null) return;
    const seen = nowIso();
    for (const f of foods || []) if (f && Number.isInteger(f.id)) await store.put('foods', { user_id: uid, id: f.id, food: clone(f), seen_at: seen });
  }
  // GET /api/foods offline: the server's search rules (every word in the name or brand, prefix matches first) over
  // the foods this device has seen; without words, the most recently seen first.
  async function searchLocal(path) {
    const u = pathOf(path);
    const uid = userId();
    if (!u || uid == null) return null;
    const q = (u.searchParams.get('q') || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
    const words = q ? q.split(' ').slice(0, 10) : [];
    const category = u.searchParams.get('category') || '';
    const source = u.searchParams.get('source') || '';
    const limit = Math.max(1, Math.min(200, Number(u.searchParams.get('limit')) || 25));
    const lower = KH.mock && KH.mock.asciiLower ? KH.mock.asciiLower : (s) => String(s).toLowerCase();
    let rows = (await store.all('foods')).filter((r) => r.user_id === uid && r.food && !r.food.hidden
      && (!category || r.food.category === category) && (!source || r.food.source === source)
      && words.every((w) => lower(r.food.name).includes(w) || lower(r.food.brand || '').includes(w)));
    rows.sort((a, b) => (a.seen_at < b.seen_at ? 1 : a.seen_at > b.seen_at ? -1 : 0) || String(a.food.name).localeCompare(String(b.food.name)));
    if (words.length && KH.mock && KH.mock.searchRank) {
      rows = rows.map((r, i) => [r, i]).sort((a, b) => (KH.mock.searchRank(a[0].food.name, a[0].food.brand, q, words)
        - KH.mock.searchRank(b[0].food.name, b[0].food.brand, q, words)) || a[1] - b[1]).map(([r]) => r);
    }
    return { foods: rows.slice(0, limit).map((r) => clone(r.food)), offline: true };
  }
  // Once a day, while connected: every food this person can use (builtin by category, their own, the shared ones they
  // scanned), so search works offline. Without a server route for the whole list this is one request per group.
  let downloading = false;
  async function downloadFoods() {
    if (MOCK || downloading || userId() == null || offlineNow()) return;
    const meta = await store.get('meta', `foods_full_sync:${userId()}`);
    if (meta && Date.now() - Date.parse(meta.value) < FULL_FOODS_EVERY_MS) return;
    downloading = true;
    try {
      const get = (q) => KH.request('GET', `/api/foods?${util.qs({ ...q, limit: 200 })}`, undefined, { quiet401: true, noQueue: true });
      const cats = await KH.request('GET', '/api/foods/categories', undefined, { quiet401: true, noQueue: true });
      for (const category of (cats && cats.categories) || []) await rememberFoods((await get({ category, source: 'builtin' })).foods);
      for (const source of ['custom', 'off', 'usda']) await rememberFoods((await get({ source })).foods);
      await store.put('meta', { key: `foods_full_sync:${userId()}`, value: nowIso() });
    } catch (e) {
      if (!e.handled) console.warn('Saving foods for offline search stopped:', e.detail || e.message);
    } finally { downloading = false; }
  }

  // ---------------------------------------------------------------------------
  // The day with its waiting entries
  // ---------------------------------------------------------------------------
  // A copy of `day` (a DaySummary, or null for a day this device has no copy of) with the waiting entries of that
  // date in it and the totals, status and alerts worked out again with the twin of app/log.py (js/mock/log.js).
  async function withWaiting(day, date) {
    const items = (await myItems()).filter((i) => (i.body && i.body.date) === date);
    if (!items.length) return day;
    const profile = state.profile || {};
    const base = day ? clone(day) : { date, entries: [], targets: profile.targets || {} };
    const targets = base.targets || profile.targets || {};
    const entries = base.entries || [];
    for (const item of items) {
      if (item.kind === 'mark') {
        for (const e of entries) {
          if (e.status === 'planned' && (!item.body.meal || e.meal === item.body.meal)) { e.status = 'eaten'; e.pending = true; e.failed = item.state === 'failed'; }
        }
      } else {
        entries.push(entryView(item));
      }
    }
    const order = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 };
    entries.sort((a, b) => (order[a.meal] ?? 3) - (order[b.meal] ?? 3) || (a.status === 'eaten' ? 0 : 1) - (b.status === 'eaten' ? 0 : 1)
      || (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
    const rows = entries.map((e) => ({ status: e.status, meal: e.meal, nutrients: e.raw || e.nutrients }));
    const f = KH.mock.dayFigures({ targets, warn_fraction: profile.warn_fraction || 0.8 }, rows);
    for (const e of entries) delete e.raw;
    return Object.assign(base, { entries, targets, totals: f.totals, planned_totals: f.planned_totals, projected_totals: f.projected_totals,
      status: f.status, projected_status: f.projected_status, meals: f.meals, planned_meals: f.planned_meals, alerts: f.alerts,
      projected_alerts: f.projected_alerts, counts: f.counts });
  }

  // ---------------------------------------------------------------------------
  // The hooks js/core.js calls (KH.net)
  // ---------------------------------------------------------------------------
  // The demo API is in the page: it counts as unreachable while the browser says it is offline, so the outbox can be
  // tried in the demo too.
  function offlineNow() { return MOCK && navigator.onLine === false; }
  function prepare(method, path, body) {
    const kind = kindOf(method, path);
    if ((kind === 'entry' || kind === 'quick') && body && typeof body === 'object' && !Array.isArray(body) && body.client_id == null) {
      return { ...body, client_id: uuid4() };
    }
    return body;
  }
  function timeoutFor(method, path) {
    if (method === 'GET') return snapshotPath(path) || (pathOf(path) || {}).pathname === '/api/foods' ? FAST_MS : SLOW_MS;
    return kindOf(method, path) ? FAST_MS : 0;
  }
  async function onNetworkError(method, path, body, err) {
    setOffline(true);
    try {
      if (method === 'GET') {
        const u = pathOf(path);
        const p = u ? u.pathname : '';
        if (p === '/api/foods') { const res = await searchLocal(path); return res ? markOffline(res, { local: true }) : undefined; }
        const m = /^\/api\/foods\/(\d+)$/.exec(p);
        if (m) { const food = await knownFood(m[1]); return food ? markOffline(clone(food), { local: true }) : undefined; }
        const key = snapshotPath(path);
        if (!key) return undefined;
        const snap = await readSnapshot(key);
        if (p === '/api/log') {
          const date = u.searchParams.get('date');
          const day = await withWaiting(snap ? snap.data : null, date);
          return day ? markOffline(day, { fetched_at: snap ? snap.fetched_at : null }) : undefined;
        }
        return snap ? markOffline(clone(snap.data), { fetched_at: snap.fetched_at }) : undefined;
      }
      if (method === 'POST' && kindOf(method, path)) return await enqueue(method, path, body);
    } catch (e) {
      console.warn('Offline answer failed:', e);
    }
    return undefined;
  }
  async function afterResponse(method, path, body, data, opts) {
    try {
      if (!opts || !opts.noQueue) { setOffline(false); scheduleSync(); }
      const u = pathOf(path);
      const p = u ? u.pathname : '';
      if (method === 'GET') {
        const key = snapshotPath(path);
        if (key && data != null) await saveSnapshot(key, data);
        if (p === '/api/foods' && data && Array.isArray(data.foods)) await rememberFoods(data.foods);
        if (/^\/api\/foods\/\d+$/.test(p) && data && data.id) await rememberFoods([data]);
        if (p === '/api/log' && data && data.date) return await withWaiting(data, data.date);
      } else if (method === 'POST') {
        if (p === '/api/foods/barcode' && data && data.food) await rememberFoods([data.food]);
        else if ((p === '/api/foods' || /^\/api\/foods\/\d+\/copy$/.test(p)) && data && data.id) await rememberFoods([data]);
      } else if (method === 'PUT' && /^\/api\/foods\/\d+$/.test(p) && data && data.id) await rememberFoods([data]);
    } catch (e) {
      console.warn('Saving for offline use failed:', e);
    }
    return data;
  }
  async function onUnavailable(method, path, body, err, opts) {
    // A gateway answering for a stopped app: queue the writes that can wait; reads use their saved copy.
    return onNetworkError(method, path, body, err, opts);
  }
  KH.net = { prepare, timeoutFor, offlineNow, onNetworkError, onUnavailable, afterResponse };

  // ---------------------------------------------------------------------------
  // Triggers, resume, start
  // ---------------------------------------------------------------------------
  let syncTimer = null;
  let started = false;
  let lastToday = util.todayStr();
  function scheduleSync(delay = 300) {
    if (syncTimer || syncing || userId() == null) return;
    syncTimer = setTimeout(() => {
      syncTimer = null;
      if (counts.pending > 0) syncNow().catch((e) => console.warn('Sync failed:', e));
    }, delay);
  }
  function onVisible() {
    if (document.visibilityState !== 'visible' || !started) return;
    const today = util.todayStr();
    if (today !== lastToday) {
      // R5 "Resume": a page that slept through midnight moves Today to the new day.
      if (state.view === 'today' && state.date === lastToday && KH.views.today) KH.views.today.setDate(today);
      lastToday = today;
    }
    refreshCounts().then(() => scheduleSync(0)).catch(() => {});
  }
  document.addEventListener('visibilitychange', onVisible);
  window.addEventListener('pageshow', onVisible);
  window.addEventListener('online', () => { setOffline(false); scheduleSync(0); });
  window.addEventListener('offline', () => setOffline(true));
  setInterval(() => {
    if (started && document.visibilityState === 'visible' && counts.pending > 0) syncNow().catch(() => {});
  }, SYNC_EVERY_MS);

  // Called once per signed-in page (js/main.js KH.app.start).
  async function start() {
    started = true;
    lastToday = util.todayStr();
    await refreshCounts();
    scheduleSync(0);
    setTimeout(() => { downloadFoods().catch(() => {}); }, 4000);
  }

  // ---------------------------------------------------------------------------
  // Sign-out (js/views/auth.js) and clearing this device
  // ---------------------------------------------------------------------------
  const unsyncedDlg = $('#sheet-unsynced');
  KH.sheets.setup(unsyncedDlg);
  function itemLine(item) {
    const v = entryView(item);
    if (item.kind === 'mark') {
      return `Mark ${item.body.meal ? `${rules.MEAL_LABEL[item.body.meal].toLowerCase()} ` : 'everything planned '}eaten on ${util.fmtDateLong(item.body.date)}`;
    }
    const amount = v.grams != null ? `${rules.fmtNum(v.grams, 'fluid_ml')} g` : rules.fmtServings(v.servings);
    return `${v.food_name}, ${amount}: ${rules.MEAL_LABEL[v.meal] || v.meal}${v.status === 'planned' ? ' (planned)' : ''}, ${util.fmtDateLong(v.date)}`;
  }
  // Resolves true when sign-out may go on: nothing waits, or the person chose to lose it.
  async function beforeSignOut() {
    const items = await myItems();
    if (!items.length) return true;
    return new Promise((resolve) => {
      let answered = false;
      const finish = (ok) => { if (answered) return; answered = true; resolve(ok); if (unsyncedDlg.open) unsyncedDlg.close(); };
      const draw = (list) => {
        $('#sheet-unsynced-sub').textContent = `${list.length} ${list.length === 1 ? 'entry on this device has' : 'entries on this device have'} not reached your server. `
          + 'Signing out removes them from this device.';
        const body = clear($('#sheet-unsynced-body'));
        body.append(h('ul', { class: 'outbox-list' }, list.map((i) => h('li', { class: `outbox-item${i.state === 'failed' ? ' failed' : ''}` },
          h('p', { class: 'outbox-title' }, itemLine(i)), i.last_error ? h('p', { class: 'outbox-error' }, i.last_error) : null))));
        const foot = clear($('#sheet-unsynced-foot'));
        const status = h('p', { class: 'status-msg', role: 'status', 'aria-live': 'polite' });
        const trySync = h('button', { class: 'btn secondary', type: 'button' }, 'Try to sync now');
        trySync.addEventListener('click', async () => {
          trySync.disabled = true;
          status.textContent = 'Syncing…';
          await syncNow();
          const left = await myItems();
          if (!left.length) { status.textContent = 'Everything is synced.'; finish(true); return; }
          status.textContent = offline ? 'Your server still cannot be reached.' : `${left.length} still waiting.`;
          trySync.disabled = false;
          draw(left);
        });
        const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Stay signed in');
        cancel.addEventListener('click', () => finish(false));
        const lose = h('button', { class: 'btn danger-solid', type: 'button' }, 'Sign out and lose them');
        lose.addEventListener('click', () => finish(true));
        body.append(status);
        foot.append(trySync, h('span', { class: 'spacer' }), cancel, lose);
      };
      draw(items);
      unsyncedDlg.addEventListener('close', () => finish(false), { once: true });
      KH.sheets.open(unsyncedDlg, document.activeElement, $('#sheet-unsynced-foot button'));
    });
  }
  // Everything this device keeps for offline use, for everyone (sign-out, "Clear offline data").
  async function purge() {
    for (const m of Object.values(memory)) m.clear();
    const db = await (dbPromise || Promise.resolve(null));
    if (db) { try { db.close(); } catch (e) { /* closed */ } }
    dbPromise = null;
    if (!MOCK && window.indexedDB) {
      await new Promise((resolve) => {
        let req;
        try { req = window.indexedDB.deleteDatabase(DB_NAME); } catch (e) { resolve(); return; }
        req.onsuccess = req.onerror = req.onblocked = () => resolve();
      });
    }
    counts = { pending: 0, failed: 0 };
    offline = false;
    renderBadge();
  }

  // ---------------------------------------------------------------------------
  // Settings → This device: the entries waiting to sync
  // ---------------------------------------------------------------------------
  async function renderDevice(container) {
    const box = h('div', { class: 'outbox', id: 'set-outbox' });
    container.append(box);
    const draw = async () => {
      clear(box);
      const items = await myItems();
      const where = MOCK ? 'In the demo they are kept in this page only.'
        : persistent ? 'They are kept in this browser’s storage until they reach your server.'
          : 'This browser cannot store them, so they are kept only while this page stays open.';
      box.append(h('h3', { class: 'settings-subtitle', id: 'set-outbox-h' }, 'Entries waiting to sync'));
      if (!items.length) {
        box.append(h('p', {}, offline ? 'Nothing waits. Your server cannot be reached right now; new entries will wait here.' : 'Everything is synced.'));
        return;
      }
      const failedN = items.filter((i) => i.state === 'failed').length;
      box.append(h('p', {}, `${items.length} ${items.length === 1 ? 'entry has' : 'entries have'} not reached your server${failedN ? `; ${failedN} could not be saved` : ''}. ${where}`));
      const list = h('ul', { class: 'outbox-list', 'aria-labelledby': 'set-outbox-h' });
      for (const item of items) {
        const row = h('li', { class: `outbox-item${item.state === 'failed' ? ' failed' : ''}` });
        const actions = h('div', { class: 'outbox-actions' });
        if (item.state === 'failed') {
          const again = h('button', { class: 'btn secondary', type: 'button' }, 'Retry');
          again.addEventListener('click', async () => { again.disabled = true; await retry(item.client_id); await draw(); });
          actions.append(again);
        }
        const drop = h('button', { class: 'btn danger', type: 'button', 'aria-label': `Discard: ${itemLine(item)}` }, 'Discard');
        drop.addEventListener('click', () => KH.confirm.inline(actions, drop, {
          message: `Discard “${itemLine(item)}”? It has not reached your server, so it will be gone.`, confirmText: 'Discard',
          onConfirm: async () => { await discard(item.client_id); await draw(); const next = $('#set-outbox button'); if (next) next.focus(); return true; },
        }));
        actions.append(drop);
        row.append(h('p', { class: 'outbox-title' }, itemLine(item)),
          item.state === 'failed' ? h('p', { class: 'outbox-error' }, `Not saved: ${item.last_error || 'the server refused it'}`) : h('p', { class: 'hint' }, 'Waiting to sync'),
          actions);
        list.append(row);
      }
      const all = h('div', { class: 'settings-actions' });
      const now = h('button', { class: 'btn primary', type: 'button', id: 'set-sync-now' }, 'Sync now');
      now.addEventListener('click', async () => {
        now.disabled = true;
        const r = await syncNow();
        await draw();
        if (r && r.stopped) toast('Your server cannot be reached right now. The entries keep waiting.', 'error');
        const again = $('#set-sync-now'); if (again) again.focus();
      });
      const dropAll = h('button', { class: 'btn danger', type: 'button' }, 'Discard all');
      dropAll.addEventListener('click', () => KH.confirm.inline(all, dropAll, {
        message: `Discard all ${items.length} entries that have not reached your server?`, confirmText: 'Discard all',
        onConfirm: async () => { await discardAll(); await draw(); return true; },
      }));
      all.append(now, dropAll);
      box.append(list, all);
    };
    await draw();
    const off = onChange(() => { if (document.contains(box)) draw(); else off(); });
  }
  function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

  async function pendingCount() { const c = await refreshCounts(); return c.pending + c.failed; }

  KH.offline = { start, syncNow, pendingCount, purge, beforeSignOut, renderDevice, discard, discardAll, retry, onChange,
    isOffline: () => offline, servedOffline: (obj) => (obj && typeof obj === 'object' ? servedOffline.get(obj) || null : null),
    counts: () => ({ ...counts }), persistent: () => persistent, uuid4, entryView, withWaiting };
})();
