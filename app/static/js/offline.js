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
                                              attempts, state: 'pending'|'failed', last_error, sent, edited_after_send,
                                              deleted}; an edit or delete adds entry_id, version, base, rev
     The demo and the preview keep the same tables in memory only (they store nothing on the device); a browser
     without IndexedDB does the same and Settings says so.
   * Queued while unreachable (R5 "queueable"): POST /api/log, POST /api/log/quick and POST /api/log/mark-eaten,
     and the edit (PUT) and delete (DELETE) of an entry already on the server. Every POST /api/log and /quick carries
     a fresh client_id (a v4 UUID) from its first try, so a request that reached the server before the connection
     dropped is answered "existing", never logged twice. The caller gets the entry as it will look (`pending: true`;
     warnings worked out here with the rules twin js/engine/rules.js). Everything else that needs the server (the
     profile and targets, barcodes, AI) fails with "Cannot reach the server" as before: a care team's targets are
     never overwritten by a copy that waited on a phone.
   * Offline edits and deletes never overwrite silently (ARCHITECTURE.md "Offline edits and deletes"). An edit or delete
     is queued with the `version` of the entry as the person saw it and is sent with If-Match. One change waits per
     entry (a second edit joins the first; a delete replaces it), so the entry's own earlier change never makes a
     conflict. An edit of an entry that was itself made offline and has not been sent rewrites the queued create, and
     a delete of one removes it without any request. A 412 means the entry changed on the server: when the server's
     entry still equals the one the change was made on (our own queued "mark eaten" got there first) the change is
     sent again with the new version, otherwise the item becomes a conflict card (Settings → This device) with the
     server's entry and the person's side by side: "Keep the saved one" drops the change, "Use mine" sends it with
     the new version. A 404 means the entry is gone (or not the person's): "This entry no longer exists", dropped.
   * A change made while its item is being sent is never lost. A create is marked `sent` as it goes; an edit of it after
     that is marked `edited_after_send`, a delete keeps the row as `deleted`, and the server's answer (the entry, found by
     its client_id) turns the row into the edit or the delete of that entry, sent next with If-Match. A second edit that
     joins a change being sent raises its `rev`, and the answer leaves what is still different waiting.
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

  const DB_NAME = KH.brand.idbName;
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
  const ENTRY_PATH = /^\/api\/log\/(\d+)$/; // PUT / DELETE of an entry that is on the server
  const WAITING_PATH = /^\/api\/log\/pending:([0-9a-f-]{36})$/i; // the same for an entry that still waits on this device
  // What a person sees and edits of an entry (app/log.py VERSION_FIELDS): a 412 whose entry equals the one the change was
  // made on means nothing foreign happened, and the change is sent again with the new version.
  const SAME_FIELDS = ['date', 'meal', 'food_name', 'servings', 'grams', 'note', 'status', 'purpose'];

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
  // The outbox in memory is copied in and out, as IndexedDB does: a row read for a send never changes under it.
  const memCopy = (name, v) => (name === 'outbox' ? clone(v) : v);
  const store = {
    async get(name, key) {
      const db = await openDb();
      if (!db) return memCopy(name, memory[name].get(JSON.stringify(key))) || null;
      try { return (await tx(db, name, 'readonly', (s) => s.get(key))) || null; } catch (e) { console.warn('Offline storage read failed:', e); return null; }
    },
    async put(name, value) {
      const db = await openDb();
      if (!db) { memory[name].set(memKey(name, value), memCopy(name, value)); return; }
      try { await tx(db, name, 'readwrite', (s) => s.put(value)); } catch (e) { console.warn('Offline storage write failed:', e); memory[name].set(memKey(name, value), memCopy(name, value)); }
    },
    async del(name, key) {
      const db = await openDb();
      memory[name].delete(JSON.stringify(key));
      if (!db) return;
      try { await tx(db, name, 'readwrite', (s) => s.delete(key)); } catch (e) { console.warn('Offline storage delete failed:', e); }
    },
    async all(name) {
      const db = await openDb();
      const mem = [...memory[name].values()].map((v) => memCopy(name, v));
      if (!db) return mem;
      try { return [...((await tx(db, name, 'readonly', (s) => s.getAll())) || []), ...mem]; } catch (e) { console.warn('Offline storage read failed:', e); return mem; }
    },
    // Read, change and write one row in a single step, so a change made in between (the person editing an entry while the
    // sync settles it) is never written over. `fn(row or null)` returns the row to store, null to delete it, or undefined to
    // leave it; it must not wait for anything. Resolves to what `fn` returned.
    async update(name, key, fn) {
      const db = await openDb();
      const k = JSON.stringify(key);
      if (!db || memory[name].has(k)) { // no IndexedDB, or a row that lives in memory after a failed write
        const out = fn(memory[name].has(k) ? clone(memory[name].get(k)) : null);
        if (out === null) memory[name].delete(k); else if (out !== undefined) memory[name].set(k, clone(out));
        return out;
      }
      try {
        return await new Promise((resolve, reject) => {
          let out;
          const t = db.transaction(name, 'readwrite');
          const s = t.objectStore(name);
          const r = s.get(key);
          r.onsuccess = () => { out = fn(r.result || null); if (out === null) s.delete(key); else if (out !== undefined) s.put(out); };
          t.oncomplete = () => resolve(out);
          t.onerror = () => reject(t.error);
          t.onabort = () => reject(t.error || new Error('aborted'));
        });
      } catch (e) { console.warn('Offline storage write failed:', e); return undefined; }
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
  // The outbox replays in created_at order, so two changes queued in the same millisecond must still get distinct, rising
  // stamps: otherwise the tie falls back to the store's key order (a random id) and a "mark eaten" could replay after a later edit.
  let lastQueued = 0;
  const queueStamp = () => { lastQueued = Math.max(Date.now(), lastQueued + 1); return new Date(lastQueued).toISOString(); };
  function pathOf(path) { try { return new URL(path, 'http://app.invalid'); } catch (e) { return null; } }
  function kindOf(method, path) {
    const u = pathOf(path);
    if (!u) return null;
    if (KINDS[`${method} ${u.pathname}`]) return KINDS[`${method} ${u.pathname}`];
    if (ENTRY_PATH.test(u.pathname)) return method === 'PUT' ? 'edit' : method === 'DELETE' ? 'delete' : null;
    return null;
  }
  const isChange = (item) => item.kind === 'edit' || item.kind === 'delete'; // a change to an entry that is on the server
  const isCreate = (item) => item.kind === 'entry' || item.kind === 'quick'; // an entry that is made when it is sent
  const isQueued = (item) => item.state !== 'failed' && item.state !== 'conflict'; // what a sync run sends
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
  let counts = { pending: 0, failed: 0, conflict: 0, changes: 0 }; // changes: of the pending, edits and deletes
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
    const waiting = counts.pending + counts.failed + counts.conflict;
    const show = !!state.me && (offline || waiting > 0);
    badge.hidden = !show;
    if (!show) return;
    badge.classList.toggle('failed', counts.failed + counts.conflict > 0);
    badge.classList.toggle('syncing', syncing);
    const parts = [];
    if (offline) parts.push('Offline');
    if (counts.conflict) parts.push(`${counts.conflict} to review`);
    if (counts.failed) parts.push(`${counts.failed} not saved`);
    if (counts.pending) parts.push(`${counts.pending} to sync`);
    $('#sync-badge-text').textContent = parts.join(' · ');
    // Phones: the number waiting, or "Offline" when nothing waits (the aria-label says it in full).
    $('#sync-badge-short').textContent = waiting ? String(waiting) : 'Offline';
    const noun = counts.changes ? (counts.pending === 1 ? 'change is' : 'changes are') : (counts.pending === 1 ? 'entry is' : 'entries are');
    const long = [offline ? 'Your server cannot be reached.' : '', counts.pending ? `${counts.pending} ${noun} waiting to sync.` : '',
      counts.conflict ? `${counts.conflict} ${counts.conflict === 1 ? 'entry was' : 'entries were'} changed on another device too: choose which version to keep.` : '',
      counts.failed ? `${counts.failed} could not be saved: review ${counts.failed === 1 ? 'it' : 'them'}.` : ''].filter(Boolean).join(' ');
    badge.setAttribute('aria-label', `${long} Open Settings, This device.`);
    badge.title = long;
  }
  async function refreshCounts() {
    const items = await myItems();
    const queued = items.filter(isQueued);
    counts = { pending: queued.length, failed: items.filter((i) => i.state === 'failed').length, conflict: items.filter((i) => i.state === 'conflict').length,
      changes: queued.filter(isChange).length };
    renderBadge();
    notify();
    return counts;
  }
  // The badge opens Settings → This device. Settings draws its sections one by one, so wait for the outbox list,
  // then bring it into view and move focus to its heading (scroll anchoring keeps it there while the rest loads).
  $('#sync-badge').addEventListener('click', () => {
    KH.router.show('settings');
    const until = Date.now() + 4000;
    const go = () => {
      const head = $('#set-outbox-h');
      if (!head) { if (Date.now() < until && state.view === 'settings') setTimeout(go, 80); return; }
      head.tabIndex = -1;
      head.scrollIntoView({ block: 'start' });
      head.focus({ preventScroll: true });
    };
    setTimeout(go, 0);
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

  async function enqueue(method, path, body, opts) {
    const kind = kindOf(method, path);
    const uid = userId();
    if (kind === 'edit' || kind === 'delete') return enqueueChange(method, path, body, opts);
    if (!kind || uid == null || !body || typeof body !== 'object') return undefined;
    const item = { client_id: kind === 'mark' ? uuid4() : body.client_id || uuid4(), user_id: uid, kind, method, path, body: clone(body),
      food: kind === 'entry' ? await knownFood(body.food_id) : null, created_at: queueStamp(), attempts: 0, state: 'pending', last_error: null };
    if (kind !== 'mark') item.body.client_id = item.client_id;
    await store.put('outbox', item);
    if (kind === 'mark') await markExpected(body);
    await refreshCounts();
    announce('Saved on this device. It will sync when your server can be reached.');
    if (kind === 'mark') {
      const day = state.day && state.day.date === body.date ? state.day : null;
      const n = day ? (day.entries || []).filter((e) => e.status === 'planned' && !e.pending && (!body.meal || e.meal === body.meal)).length : 0;
      return { updated: n, pending: true };
    }
    return entryView(item);
  }

  // ---------------------------------------------------------------------------
  // Edits and deletes of entries (offline edits; never overwrite silently)
  // ---------------------------------------------------------------------------
  const problem = (status, text) => Object.assign(new Error(text), { status, detail: text });
  const amountOf = (e) => (e.grams != null ? `${rules.fmtNum(e.grams, 'fluid_ml')} g` : rules.fmtServings(e.servings));
  function scaleBy(nutrients, from, to) {
    const k = Number(from) > 0 ? Number(to) / Number(from) : 1;
    return Object.fromEntries(rules.NUTRIENT_KEYS.map((key) => [key, nutrients && nutrients[key] != null ? Number(nutrients[key]) * k : null]));
  }
  const foodOf = (entry) => (entry && entry.food_id != null ? knownFood(entry.food_id) : Promise.resolve(null));
  // `entry` with a PUT /api/log/{id} body applied, as the server would answer it (the amount is worked out from the
  // food when this device knows it, else by scaling the entry's own numbers; warnings need the food).
  function appliedEntry(entry, body, food) {
    const e = clone(entry);
    delete e.pending; delete e.failed; delete e.conflict; delete e.raw; delete e.last_error;
    if (body.date) e.date = body.date;
    if (body.meal) e.meal = body.meal;
    if (body.status) e.status = body.status;
    if ('note' in body) e.note = body.note ? String(body.note) : null;
    if (body.purpose === 'hypo') e.purpose = 'hypo'; else if (body.purpose === 'none') e.purpose = null;
    if ('servings' in body || 'grams' in body) {
      let servings = Number(entry.servings);
      let grams = entry.grams;
      if (body.grams != null) { grams = Number(body.grams); servings = food && food.serving_g ? grams / Number(food.serving_g) : body.servings != null ? Number(body.servings) : servings; }
      else if (body.servings != null) { servings = Number(body.servings); grams = null; } else if ('grams' in body) grams = null;
      e.servings = Math.round(servings * 1000) / 1000;
      e.grams = grams == null ? null : Math.round(grams * 10) / 10;
      const scaled = food ? rules.scaleNutrients(food.nutrients, servings) : scaleBy(entry.nutrients, entry.servings, servings);
      e.raw = scaled;
      e.nutrients = rules.roundNutrients(scaled);
      if (food) {
        e.warnings = rules.evaluateWarnings(scaled, food.flags || [], food.kidney_notes || null, 'in this entry');
        e.kidney_rating = rules.ratingFromWarnings(e.warnings);
      }
    }
    return e;
  }
  // The entry a waiting edit leaves: `current` (the entry on the day now, else the one the change was made on) with the
  // edit applied, marked as waiting. Its version stays the one it was made on.
  function editedView(item, food, current = item.base) {
    const e = appliedEntry(current, item.body || {}, food);
    return Object.assign(e, { pending: true, failed: item.state === 'failed', conflict: item.state === 'conflict', last_error: item.last_error || null });
  }
  const sameContent = (a, b) => !!a && !!b && SAME_FIELDS.every((k) => (a[k] == null ? null : a[k]) === (b[k] == null ? null : b[k]));
  // "Mark eaten" waits as one item for a day; the changes already waiting for planned entries it covers now expect them
  // eaten, so their own version check (a 412 after the mark was sent first) still finds nothing foreign.
  async function markExpected(markBody) {
    for (const it of await myItems()) {
      if (isChange(it) && it.base && it.base.date === markBody.date && it.base.status === 'planned' && (!markBody.meal || it.base.meal === markBody.meal)) {
        await store.update('outbox', it.client_id, (row) => {
          if (!row || !isChange(row) || !row.base || row.base.status !== 'planned') return undefined;
          row.base.status = 'eaten';
          return row;
        });
      }
    }
  }

  // What an edit changes, as against the entry the person saw. The entry sheet always sends the meal, day, status and note
  // (and the amount once it was touched); only what differs is kept, so "Use mine" after a conflict puts back what the person
  // changed and never a field they did not touch (a note another device wrote meanwhile stays).
  function changedFields(base, body) {
    const out = {};
    for (const key of ['date', 'meal', 'status']) if (body[key] && body[key] !== base[key]) out[key] = body[key];
    if ('note' in body && (body.note ? String(body.note) : null) !== (base.note || null)) out.note = body.note ? String(body.note) : null;
    if (body.purpose === 'hypo' || body.purpose === 'none') {
      if ((body.purpose === 'hypo' ? 'hypo' : null) !== (base.purpose || null)) out.purpose = body.purpose;
    }
    if ('servings' in body || 'grams' in body) {
      const grams = body.grams != null ? Number(body.grams) : null;
      const same = grams != null ? grams === base.grams : base.grams == null && body.servings != null && Number(body.servings) === Number(base.servings);
      if (!same) { if ('servings' in body) out.servings = body.servings; if ('grams' in body) out.grams = body.grams; }
    }
    return out;
  }

  // An edit or delete of an entry on the server, made while it cannot be reached (or with a change already waiting for
  // that entry, so the order holds). One item per entry: a second edit joins the first, a delete replaces it. Needs the
  // entry the person saw (`opts.base`): without it there is no version to check, so nothing is queued.
  async function enqueueChange(method, path, body, opts) {
    const kind = kindOf(method, path);
    const uid = userId();
    const base = opts && opts.base && typeof opts.base === 'object' ? clone(opts.base) : null;
    if (uid == null || !base || (kind === 'edit' && (!body || typeof body !== 'object'))) return undefined;
    const entryId = Number(ENTRY_PATH.exec(pathOf(path).pathname)[1]);
    const waiting = (await myItems()).find((i) => isChange(i) && i.entry_id === entryId);
    if (waiting && waiting.state === 'conflict') throw problem(409, 'This entry was changed on another device. Choose which version to keep in Settings → This device first.');
    if (waiting && waiting.kind === 'delete') throw problem(404, 'This entry no longer exists');
    const changes = kind === 'edit' ? changedFields(base, body) : null;
    if (kind === 'edit' && !Object.keys(changes).length) return waiting ? editedView(waiting, await foodOf(waiting.base)) : { ...base, pending: false }; // nothing differs
    // Joined in one step: the sync may be sending this item right now, and `rev` tells it a newer change came in meanwhile.
    let decided = false;
    let item = waiting ? await store.update('outbox', waiting.client_id, (row) => {
      if (!row || !isChange(row) || row.entry_id !== entryId) return undefined; // just sent: a new item below
      if (row.state === 'conflict') { decided = true; return undefined; }
      if (kind === 'delete') { row.kind = 'delete'; row.method = 'DELETE'; row.body = null; } else row.body = { ...row.body, ...changes };
      row.created_at = queueStamp(); // it goes after anything queued since (a "mark eaten"), as the person did it
      row.state = 'pending'; row.last_error = null; row.attempts = 0; row.rebased = false; row.rev = (row.rev || 0) + 1;
      return row;
    }) : undefined;
    if (decided) throw problem(409, 'This entry was changed on another device. Choose which version to keep in Settings → This device first.');
    if (!item) {
      item = { client_id: uuid4(), user_id: uid, kind, method, path, entry_id: entryId, body: changes,
        version: typeof opts.ifMatch === 'string' ? opts.ifMatch : base.version || null, base, created_at: queueStamp(), attempts: 0, state: 'pending',
        last_error: null, rebased: false, rev: 0 };
      await store.put('outbox', item);
    }
    await refreshCounts();
    if (offline) announce('Saved on this device. It will sync when your server can be reached.');
    return kind === 'delete' ? { pending: true } : editedView(item, await foodOf(item.base));
  }
  // The person's change refused with a 412 while online: keep it as a conflict card next to the server's entry.
  async function onConflict(method, path, body, err, opts) {
    const kind = kindOf(method, path);
    const uid = userId();
    const current = err.data && err.data.current;
    if ((kind !== 'edit' && kind !== 'delete') || uid == null || !opts || !opts.base || !current) return;
    const entryId = Number(ENTRY_PATH.exec(pathOf(path).pathname)[1]);
    if (!(await myItems()).some((i) => isChange(i) && i.entry_id === entryId)) {
      await store.put('outbox', { client_id: uuid4(), user_id: uid, kind, method, path, entry_id: entryId, body: kind === 'edit' ? changedFields(opts.base, body || {}) : null,
        version: typeof opts.ifMatch === 'string' ? opts.ifMatch : null, base: clone(opts.base), server: clone(current), created_at: queueStamp(), attempts: 1,
        state: 'conflict', last_error: 'changed on another device', rebased: false });
      await refreshCounts();
    }
    err.conflict = true;
    err.message = err.detail = 'This entry was changed on another device, so your change was not saved. Choose which version to keep in Settings → This device.';
  }
  // Editing or deleting an entry that is still only on this device (id "pending:<client_id>"): the queued create is
  // rewritten, or removed, and the server hears of neither. Once a send of it has started (`sent`), the server may already
  // have it: an edit is marked `edited_after_send` and a delete keeps the row as `deleted`, and when the server's answer
  // comes the sync sends the edit, or the delete, of the entry it made (settleCreate). Nothing the person did last is lost.
  async function editWaiting(clientId, body) {
    let gone = false;
    const item = await store.update('outbox', clientId, (row) => {
      if (!row || row.user_id !== userId() || !isCreate(row)) return undefined;
      if (row.deleted) { gone = true; return undefined; }
      const b = row.body;
      for (const key of ['date', 'meal', 'status']) if (body[key]) b[key] = body[key];
      if ('note' in body) b.note = body.note ? String(body.note) : null;
      if (body.purpose === 'hypo' || body.purpose === 'none') b.purpose = body.purpose;
      if ('servings' in body || 'grams' in body) {
        if (row.kind === 'entry' && body.grams != null) { b.grams = Number(body.grams); if (body.servings != null) b.servings = Number(body.servings); }
        else {
          delete b.grams;
          const food = itemFood(row);
          if (body.servings != null) b.servings = Number(body.servings);
          else if (body.grams != null && food && food.serving_g) b.servings = Number(body.grams) / Number(food.serving_g);
        }
      }
      row.state = 'pending'; row.last_error = null; row.attempts = 0; // a changed entry is sent again
      if (row.sent) row.edited_after_send = true;
      return row;
    });
    if (gone) throw problem(404, 'This entry no longer exists');
    if (!item) throw problem(409, 'This entry has just reached your server. Close this and open it again to change it.');
    await refreshCounts();
    return entryView(item);
  }
  async function deleteWaiting(clientId) {
    let found = false;
    await store.update('outbox', clientId, (row) => {
      if (!row || row.user_id !== userId() || !isCreate(row)) return undefined;
      found = true;
      if (row.deleted) return undefined;
      if (!row.sent || row.state === 'failed') return null; // the server never took it: gone with no request
      row.deleted = true; // it may be on the server already: delete it there once the answer says which entry it is
      return row;
    });
    if (!found) throw problem(409, 'This entry has just reached your server. Close this and open it again to delete it.');
    await refreshCounts();
    announce('Removed from this device.');
    return null;
  }
  // A change for an entry on the server, in the order the person made it; an entry that waits here is dealt with locally.
  async function intercept(method, path, body, opts) {
    if (method !== 'PUT' && method !== 'DELETE') return undefined;
    const u = pathOf(path);
    if (!u) return undefined;
    const here = WAITING_PATH.exec(u.pathname);
    if (here) return method === 'PUT' ? editWaiting(here[1].toLowerCase(), body || {}) : deleteWaiting(here[1].toLowerCase());
    const m = ENTRY_PATH.exec(u.pathname);
    if (!m || userId() == null || !opts || !opts.base) return undefined;
    if (!(await myItems()).some((i) => isChange(i) && i.entry_id === Number(m[1]))) return undefined;
    const out = await enqueueChange(method, path, body, opts);
    scheduleSync(0);
    return out;
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
  // The two answers to a conflict card. "Keep the saved one" drops the change (the server's entry stays as it is).
  async function keepSaved(clientId) {
    await discard(clientId);
    announce('Kept the saved one. Your change was dropped.');
  }
  // "Use mine" sends the change again with the version the server has now; if it changed again meanwhile, it is a new conflict.
  async function useMine(clientId) {
    const item = await store.get('outbox', clientId);
    if (!item || item.state !== 'conflict') return undefined;
    item.version = (item.server && item.server.version) || item.version;
    item.state = 'pending'; item.last_error = null; item.attempts = 0; item.rebased = true;
    await store.put('outbox', item);
    await refreshCounts();
    return syncNow();
  }

  // ---------------------------------------------------------------------------
  // Sync
  // ---------------------------------------------------------------------------
  let syncPromise = null;
  // One sync at a time in this page (and, with Web Locks, across this person's tabs). The promise is cleared once
  // it settles; checks that answer at once stay outside it, or the clearing would run before the assignment.
  function syncNow() {
    if (syncPromise) return syncPromise;
    if (userId() == null || offlineNow()) return Promise.resolve({ sent: 0 });
    const run = () => syncRun();
    const p = navigator.locks && typeof navigator.locks.request === 'function'
      ? navigator.locks.request('kdl-sync', { ifAvailable: true }, (lock) => (lock ? run() : { sent: 0, busy: true }))
      : run();
    syncPromise = p;
    const done = () => { if (syncPromise === p) syncPromise = null; };
    p.then(done, done);
    return p;
  }
  // The item index a batch failure names: "entries.3.servings: …", "entries[3]: food 9 not found", "entries[1].client_id repeats …".
  function failedIndex(detail) {
    const m = /entries(?:\.|\[)(\d+)/.exec(String(detail || ''));
    return m ? Number(m[1]) : null;
  }
  function cleanReason(detail) {
    return String(detail || 'The server refused this entry.').replace(/^entries(?:\.\d+\.|\[\d+\][.:]?\s?)/, '').replace(/^\w+: /, (m) => m);
  }
  // The server refused the item: kept as "not saved" with its reason, on the row as it is now (an edit made meanwhile stays).
  // An entry the person deleted while it was being sent is simply gone: the server refused it, so it never made it.
  async function markFailed(item, err) {
    await store.update('outbox', item.client_id, (row) => {
      if (!row) return undefined;
      if (row.deleted) return null;
      row.state = 'failed'; row.attempts = (row.attempts || 0) + 1; row.last_error = cleanReason(err.detail || err.message);
      return row;
    });
  }
  // Changes the stored row of `item` (the one being sent) with `fn`, so a change the person made meanwhile is kept.
  const updateItem = (item, fn) => store.update('outbox', item.client_id, (row) => (row ? (fn(row), row) : undefined));
  const STOP = Symbol('stop');
  // A request of the run: STOP on a network error, 5xx, 429 or a sign-in problem; the error for any other 4xx.
  async function send(path, body, method = 'POST', extra = {}) {
    try { return { ok: true, data: await KH.request(method, path, body, { noQueue: true, quiet401: true, ...extra }) }; } catch (err) {
      if (err.status === 0 || err.status >= 500 || err.status === 429 || err.status === 401 || err.status === 403) {
        if (err.status === 0 || err.status >= 500) setOffline(true);
        return STOP;
      }
      return { error: err };
    }
  }
  // One edit or delete of an entry on the server, sent with If-Match (the version the person saw). STOP, or what happened:
  //   { sent }       done
  //   { retry }      a 412 whose entry equals the one the change was made on (our own queued "mark eaten" got there first):
  //                  the change goes again, once, with the version the server has now
  //   { conflict }   a 412 with a different entry: kept as a card for the person to decide, nothing sent
  //   { gone }       a 404: the entry is gone (or never was the person's, which the server does not tell): dropped
  //   { failed }     any other 4xx: kept as "not saved" with the server's reason
  async function sendChange(head) {
    const item = await store.get('outbox', head.client_id); // as it is now: an edit may have joined it since the run began
    if (!item || !isChange(item) || !isQueued(item)) return {};
    if (!item.version && item.base) {
      // The entry came from a copy this device saved before entries had versions: there is nothing to send as If-Match, and
      // sending none would overwrite unchecked. Read the server's entry first and compare it with the one the change was
      // made on: equal, and its version is the one to send; different, and it is a conflict like any other.
      const day = await send(`/api/log?date=${item.base.date}`, undefined, 'GET');
      if (day === STOP) return STOP;
      if (!day.ok) { await markFailed(item, day.error); return { failed: 1 }; } // never sent unchecked
      const current = ((day.data && day.data.entries) || []).find((e) => e.id === item.entry_id);
      if (!current) { await store.del('outbox', item.client_id); return { gone: item.base.food_name || 'entry' }; }
      if (current.version && !sameContent(item.base, current)) {
        await updateItem(item, (row) => { row.state = 'conflict'; row.server = current; row.attempts += 1; row.last_error = 'changed on another device'; });
        return { conflict: 1 };
      }
      if (current.version) { item.version = current.version; await updateItem(item, (row) => { row.version = current.version; }); }
    }
    const rev = item.rev || 0;
    const r = await send(item.path, item.kind === 'edit' ? clone(item.body) : undefined, item.method, item.version ? { ifMatch: item.version } : {});
    if (r === STOP) return STOP;
    if (r.ok) {
      // Done, unless the person changed the entry again while this was on its way (`rev`): then what is left goes next,
      // checked against the entry the server answered with. A delete is the last word.
      const answered = r.data && r.data.id != null ? r.data : null;
      await store.update('outbox', item.client_id, (row) => {
        if (!row) return undefined;
        if ((row.rev || 0) === rev || item.kind === 'delete' || !isChange(row)) return null;
        const now = answered || appliedEntry(item.base, item.body || {}, null);
        if (row.kind === 'edit') {
          row.body = changedFields(now, row.body || {});
          if (!Object.keys(row.body).length) return null;
        }
        row.base = clone(now); row.version = answered ? answered.version || null : null; row.rebased = false;
        row.state = 'pending'; row.attempts = 0; row.last_error = null;
        return row;
      });
      return { sent: 1 };
    }
    const err = r.error;
    if (err.status === 404) { await store.del('outbox', item.client_id); return { gone: (item.base && item.base.food_name) || 'entry' }; }
    if (err.status === 412) {
      const current = err.data && err.data.current;
      if (current && current.version && !item.rebased && sameContent(item.base, current)) {
        await updateItem(item, (row) => { row.version = current.version; row.rebased = true; });
        return { retry: 1 };
      }
      await updateItem(item, (row) => { row.state = 'conflict'; row.server = current || null; row.attempts += 1; row.last_error = 'changed on another device'; });
      return { conflict: 1 };
    }
    await markFailed(item, err);
    return { failed: 1 };
  }
  // A create (an entry, a quick add, a "mark eaten") is marked `sent` and its body read in the same step, so a change the
  // person makes from now on is known to come after this send. Resolves to the row as sent, or null when it no longer waits.
  async function startSend(clientId) {
    return (await store.update('outbox', clientId, (row) => (row && isQueued(row) ? Object.assign(row, { sent: true }) : undefined))) || null;
  }
  // The server answered a create with `entry`. Usually the item is done. If the person deleted the entry while it was on its
  // way, the item becomes the delete of the entry the server made; if they edited it, the edit of it (only what differs).
  // Both then go like any other change (If-Match with the version the server gave), next in the queue.
  async function settleCreate(clientId, entry) {
    await store.update('outbox', clientId, (row) => {
      if (!row || !isCreate(row)) return row && row.kind === 'mark' ? null : undefined; // a "mark eaten" is simply done
      if (!entry || entry.id == null || !(row.deleted || row.edited_after_send)) return null;
      const changes = row.deleted ? null : changedFields(entry, row.body || {});
      if (changes && !Object.keys(changes).length) return null;
      const kind = row.deleted ? 'delete' : 'edit';
      return { client_id: row.client_id, user_id: row.user_id, kind, method: kind === 'delete' ? 'DELETE' : 'PUT', path: `/api/log/${entry.id}`,
        entry_id: entry.id, body: changes, version: entry.version || null, base: clone(entry), created_at: row.created_at, attempts: 0,
        state: 'pending', last_error: null, rebased: false, rev: 0 };
    });
  }
  // One create on its own (a quick add, a "mark eaten", or an entry of a batch that is sent one by one).
  async function sendCreate(path, clientId) {
    const row = await startSend(clientId);
    if (!row) return {};
    const r = await send(path, clone(row.body));
    if (r === STOP) return STOP;
    if (r.ok) { await settleCreate(clientId, r.data); return { sent: 1 }; }
    await markFailed(row, r.error);
    return { failed: 1 };
  }
  async function syncRun() {
    syncing = true; renderBadge();
    let sent = 0; let failed = 0; let sentChanges = 0; let conflicts = 0;
    const gone = [];
    try {
      let items = (await myItems()).filter(isQueued);
      while (items.length) {
        const head = items[0];
        if (head.kind === 'entry') {
          let chunk = [];
          for (const it of items) { if (it.kind !== 'entry' || chunk.length >= BATCH_MAX) break; chunk.push(it.client_id); }
          // A batch is all or nothing on the server: drop the item it names and send the rest again.
          for (;;) {
            const rows = [];
            for (const id of chunk) { const row = await startSend(id); if (row) rows.push(row); }
            if (!rows.length) break;
            const r = await send('/api/log/batch', { entries: rows.map((i) => clone(i.body)) });
            if (r === STOP) return { sent, failed, stopped: true };
            if (r.ok) {
              const made = (r.data && r.data.entries) || [];
              for (const [i, row] of rows.entries()) await settleCreate(row.client_id, made.find((e) => e.client_id === row.client_id) || made[i]);
              sent += rows.length;
              break;
            }
            const index = failedIndex(r.error.detail);
            if (index != null && rows[index]) {
              await markFailed(rows[index], r.error); failed += 1;
              chunk = rows.filter((_, i) => i !== index).map((row) => row.client_id);
              continue;
            }
            // No item named: send them one by one to find the one the server refuses.
            for (const row of rows) {
              const one = await sendCreate('/api/log', row.client_id);
              if (one === STOP) return { sent, failed, stopped: true };
              sent += one.sent || 0; failed += one.failed || 0;
            }
            break;
          }
        } else if (isChange(head)) {
          const r = await sendChange(head);
          if (r === STOP) return { sent, failed, conflicts, gone: gone.length, stopped: true };
          if (r.sent) { sent += 1; sentChanges += 1; }
          failed += r.failed || 0; conflicts += r.conflict || 0;
          if (r.gone) gone.push(r.gone);
        } else {
          const r = await sendCreate(head.path, head.client_id);
          if (r === STOP) return { sent, failed, conflicts, gone: gone.length, stopped: true };
          sent += r.sent || 0; failed += r.failed || 0;
        }
        items = (await myItems()).filter(isQueued);
      }
      setOffline(false);
      return { sent, failed, conflicts, gone: gone.length };
    } finally {
      syncing = false;
      await refreshCounts();
      if (sent || failed || conflicts || gone.length) {
        const words = [];
        const created = sent - sentChanges;
        if (created) words.push(`${created} ${created === 1 ? 'entry' : 'entries'} synced`);
        if (sentChanges) words.push(`${sentChanges} ${sentChanges === 1 ? 'change' : 'changes'} synced`);
        if (failed) words.push(`${failed} could not be saved (see Settings → This device)`);
        announce([...words, ...(conflicts ? [`${conflicts} ${conflicts === 1 ? 'entry was' : 'entries were'} changed on another device too: choose which version to keep in Settings → This device`] : []),
          ...gone.map((name) => `This entry no longer exists (${name}), so your change was dropped`)].join('; ') + '.');
        const ok = words.filter((w) => !w.includes('could not be saved'));
        if (ok.length) toast(`${ok.join('; ').charAt(0).toUpperCase()}${ok.join('; ').slice(1)}`, 'ok');
        if (conflicts) toast(`${conflicts} ${conflicts === 1 ? 'entry was' : 'entries were'} changed on another device while you were offline. Choose which version to keep in Settings → This device.`, 'error');
        if (gone.length) toast(`This entry no longer exists, so your change to ${gone.length === 1 ? `“${gone[0]}”` : `${gone.length} entries`} was dropped.`, 'error');
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
  // Once a day, while connected: every food this person can use (the builtin list, their own, the shared ones they
  // scanned), so search works offline. The builtin list comes from GET /api/foods/builtin with the ETag of the last
  // copy: an unchanged list answers 304 with no body (note 02 §6 item 9, R5).
  let downloading = false;
  async function downloadBuiltin() {
    const key = `builtin_etag:${userId()}`;
    const last = await store.get('meta', key);
    const headers = { Accept: 'application/json' };
    if (last && last.value) headers['If-None-Match'] = last.value;
    // Not KH.request: it has no use for a 304. Same origin only; a newer server still shows the Reload toast.
    const res = await fetch('/api/foods/builtin', { headers, credentials: 'same-origin', cache: 'no-store' });
    if (KH.pwa && typeof KH.pwa.versionSeen === 'function') KH.pwa.versionSeen(res.headers.get(KH.brand.versionHeader));
    if (res.status === 304) { await res.text(); return; } // read the empty body: an unread one shows as net::ERR_ABORTED
    if (!res.ok) { const err = new Error(`GET /api/foods/builtin answered ${res.status}`); err.detail = err.message; throw err; }
    const data = await res.json();
    const uid = userId();
    // A builtin food the new list no longer has (data/foods.json hides it) leaves offline search too.
    const keep = new Set((data.foods || []).map((f) => f.id));
    for (const r of await store.all('foods')) {
      if (r.user_id === uid && r.food && r.food.source === 'builtin' && !keep.has(r.id)) await store.del('foods', [uid, r.id]);
    }
    await rememberFoods(data.foods || []);
    const etag = res.headers.get('ETag');
    if (etag) await store.put('meta', { key, value: etag });
  }
  async function downloadFoods() {
    if (MOCK || downloading || userId() == null || offlineNow()) return;
    const meta = await store.get('meta', `foods_full_sync:${userId()}`);
    if (meta && Date.now() - Date.parse(meta.value) < FULL_FOODS_EVERY_MS) return;
    downloading = true;
    try {
      const get = (q) => KH.request('GET', `/api/foods?${util.qs({ ...q, limit: 200 })}`, undefined, { quiet401: true, noQueue: true });
      await downloadBuiltin();
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
  // Whether an item changes what `date` shows: its entries, the day a mark covers, or an entry that leaves or joins it.
  function touchesDay(item, date) {
    if (item.kind === 'edit') return (item.base && item.base.date === date) || (item.body && item.body.date === date);
    if (item.kind === 'delete') return !!item.base && item.base.date === date;
    return (item.body && item.body.date) === date;
  }
  async function withWaiting(day, date) {
    const mine = await myItems();
    const items = mine.filter((i) => touchesDay(i, date));
    // An entry that is being sent can already be on the server: the day shows it once, as it waits here (or not at all
    // when the person deleted it meanwhile).
    const sending = new Set(mine.filter((i) => isCreate(i) && i.sent).map((i) => i.client_id));
    const onServer = (e) => !(e.client_id && sending.has(e.client_id));
    if (!items.length && (!day || (day.entries || []).every(onServer))) return day;
    const profile = state.profile || {};
    const base = day ? clone(day) : { date, entries: [], targets: profile.targets || {} };
    const targets = base.targets || profile.targets || {};
    const entries = (base.entries || []).filter(onServer);
    for (const item of items) {
      if (item.kind === 'mark') {
        for (const e of entries) {
          if (e.status === 'planned' && (!item.body.meal || e.meal === item.body.meal)) { e.status = 'eaten'; e.pending = true; e.failed = item.state === 'failed'; }
        }
      } else if (isChange(item)) {
        const at = entries.findIndex((e) => e.id === item.entry_id);
        if (!isQueued(item)) { // not saved, or waiting for a decision: the entry as the server has it, marked
          if (at >= 0) Object.assign(entries[at], { pending: true, failed: item.state === 'failed', conflict: item.state === 'conflict' });
        } else if (item.kind === 'delete') {
          if (at >= 0) entries.splice(at, 1);
        } else {
          const view = editedView(item, await foodOf(item.base), at >= 0 ? entries[at] : item.base);
          if (view.date !== date) { if (at >= 0) entries.splice(at, 1); } // moved to another day
          else if (at >= 0) entries[at] = view;
          else entries.push(view); // moved in from another day
        }
      } else {
        if (!item.deleted) entries.push(entryView(item));
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
  // The demo counts as unreachable while the browser is offline, except when the person keeps the demo's data in this browser
  // (js/mock/persist.js): then there is no server to reach, and a write goes straight into the stored copy.
  function offlineNow() { return MOCK && navigator.onLine === false && !(KH.mock && KH.mock.local && KH.mock.local.on()); }
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
  async function onNetworkError(method, path, body, err, opts) {
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
      if (method !== 'GET' && kindOf(method, path)) {
        const queued = await enqueue(method, path, body, opts);
        if (queued !== undefined) return queued;
      }
      // Everything else that changes data needs the server (note 02 R5): say so instead of a bare network error.
      if (err && method !== 'GET') {
        err.message = `${err.timedOut ? 'Your server did not answer in time' : 'Your server cannot be reached'}, so this change was not saved: `
          + 'it needs a connection. Food you log still waits on this device and syncs later.';
        err.detail = err.message;
      }
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
        // The outbox's own read (noQueue) wants the server's day as it is, not with what waits drawn on it.
        if (p === '/api/log' && data && data.date && !(opts && opts.noQueue)) return await withWaiting(data, data.date);
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
  KH.net = { prepare, timeoutFor, offlineNow, intercept, onConflict, onNetworkError, onUnavailable, afterResponse };

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
    if (item.kind === 'mark') {
      return `Mark ${item.body.meal ? `${rules.MEAL_LABEL[item.body.meal].toLowerCase()} ` : 'everything planned '}eaten on ${util.fmtDateLong(item.body.date)}`;
    }
    if (isChange(item)) {
      const v = item.base ? (item.kind === 'edit' ? appliedEntry(item.base, item.body || {}, null) : item.base) : null;
      if (!v) return `${item.kind === 'edit' ? 'Change' : 'Delete'} an entry`;
      return `${item.kind === 'edit' ? 'Change' : 'Delete'}: ${v.food_name}, ${amountOf(v)}: ${rules.MEAL_LABEL[v.meal] || v.meal}${v.status === 'planned' ? ' (planned)' : ''}, ${util.fmtDateLong(v.date)}`;
    }
    const v = entryView(item);
    return `${item.deleted ? 'Delete: ' : ''}${v.food_name}, ${amountOf(v)}: ${rules.MEAL_LABEL[v.meal] || v.meal}${v.status === 'planned' ? ' (planned)' : ''}, ${util.fmtDateLong(v.date)}`;
  }
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  // "3 entries have" / "2 items have" (once an edit or delete is among them they are not all entries).
  const haveText = (list) => (list.some(isChange) ? plural(list.length, 'item has', 'items have') : plural(list.length, 'entry has', 'entries have'));
  // Resolves true when sign-out may go on: nothing waits, or the person chose to lose it.
  async function beforeSignOut() {
    const items = await myItems();
    if (!items.length) return true;
    return new Promise((resolve) => {
      let answered = false;
      const finish = (ok) => { if (answered) return; answered = true; resolve(ok); if (unsyncedDlg.open) unsyncedDlg.close(); };
      const draw = (list) => {
        $('#sheet-unsynced-sub').textContent = `${list.some(isChange) ? plural(list.length, 'item on this device has', 'items on this device have')
          : plural(list.length, 'entry on this device has', 'entries on this device have')} not reached your server. `
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
    counts = { pending: 0, failed: 0, conflict: 0, changes: 0 };
    offline = false;
    renderBadge();
  }

  // ---------------------------------------------------------------------------
  // Settings → This device: the entries waiting to sync
  // ---------------------------------------------------------------------------
  // A change that met a different entry on the server: both versions side by side and the person's choice. All text goes in
  // as text nodes (the notes are the person's own words).
  function summaryLines(e) {
    return [['Food', e.food_name], ['Day', util.fmtDateLong(e.date)], ['Meal', rules.MEAL_LABEL[e.meal] || e.meal], ['Amount', amountOf(e)],
      ['Status', e.status === 'planned' ? 'Planned' : 'Eaten'], ['Note', e.note || 'None']];
  }
  function conflictSide(title, lines, against) {
    const dl = h('dl', { class: 'conflict-lines' });
    lines.forEach(([label, value], i) => {
      const differs = !!against && against[i][1] !== value;
      dl.append(h('dt', {}, label), h('dd', { class: differs ? 'differs' : null }, value, differs ? h('span', { class: 'sr-only' }, ' (different)') : null));
    });
    return h('div', { class: 'conflict-side' }, h('p', { class: 'conflict-side-title' }, title), dl);
  }
  function conflictCard(item, draw) {
    const name = (item.base && item.base.food_name) || 'this entry';
    const serverLines = item.server ? summaryLines(item.server) : null;
    // "Your change" is what "Use mine" leaves: the server's entry with the person's changes on top of it.
    const mineLines = item.kind === 'edit' && item.base ? summaryLines(appliedEntry(item.server || item.base, item.body || {}, null)) : null;
    const sides = h('div', { class: 'conflict-sides' },
      serverLines ? conflictSide('Saved on your server', serverLines, mineLines)
        : h('div', { class: 'conflict-side' }, h('p', { class: 'conflict-side-title' }, 'Saved on your server'), h('p', {}, 'Not loaded yet. Press Sync now.')),
      mineLines ? conflictSide('Your change', mineLines, serverLines)
        : h('div', { class: 'conflict-side' }, h('p', { class: 'conflict-side-title' }, 'Your change'), h('p', {}, `Delete ${name}`)));
    const keep = h('button', { class: 'btn secondary', type: 'button', 'aria-label': `Keep the saved one: ${name}` }, 'Keep the saved one');
    const mine = h('button', { class: `btn ${item.kind === 'delete' ? 'danger' : 'primary'}`, type: 'button', 'aria-label': `Use mine: ${name}` }, 'Use mine');
    const settle = (decide) => async () => {
      keep.disabled = true; mine.disabled = true;
      await decide(item.client_id);
      await draw();
      const next = $('#set-outbox button'); if (next) next.focus();
    };
    keep.addEventListener('click', settle(keepSaved));
    mine.addEventListener('click', settle(useMine));
    return h('li', { class: 'outbox-item conflict', 'aria-label': `Changed on another device: ${name}` },
      h('p', { class: 'outbox-title' }, 'This entry was changed on another device while you were offline'),
      h('p', { class: 'hint' }, item.kind === 'delete' ? `You deleted ${name} here. Choose which to keep.` : `You changed ${name} here too. Choose which to keep.`),
      sides, h('div', { class: 'outbox-actions' }, keep, mine));
  }

  // Appends the list to `container` (Settings may pass a detached fragment it shows later) and keeps it
  // current while it is on the page. Returns a function that stops the updates; Settings calls it when a
  // newer render replaces the section. Draws can overlap (a change arrives while one waits for IndexedDB):
  // each builds its content first and only the newest replaces the box, so nothing is listed twice.
  async function renderDevice(container) {
    const box = h('div', { class: 'outbox', id: 'set-outbox' });
    container.append(box);
    let drawn = 0;
    let shown = false;
    let stopped = false;
    const draw = async () => {
      const ticket = ++drawn;
      const items = await myItems();
      if (ticket !== drawn || stopped) return; // a newer draw (or none at all) owns the box
      if (box.isConnected) shown = true;
      const parts = [];
      const where = MOCK ? 'In the demo they are kept in this page only.'
        : persistent ? 'They are kept in this browser’s storage until they reach your server.'
          : 'This browser cannot store them, so they are kept only while this page stays open.';
      parts.push(h('h3', { class: 'settings-subtitle', id: 'set-outbox-h' }, 'Entries waiting to sync'));
      if (!items.length) {
        parts.push(h('p', {}, offline ? 'Nothing waits. Your server cannot be reached right now; new entries will wait here.' : 'Everything is synced.'));
        box.replaceChildren(...parts);
        return;
      }
      const failedN = items.filter((i) => i.state === 'failed').length;
      const conflictN = items.filter((i) => i.state === 'conflict').length;
      parts.push(h('p', {}, `${haveText(items)} not reached your server${failedN ? `; ${failedN} could not be saved` : ''}${conflictN ? `; ${conflictN} need${conflictN === 1 ? 's' : ''} your decision` : ''}. ${where}`));
      const list = h('ul', { class: 'outbox-list', 'aria-labelledby': 'set-outbox-h' });
      for (const item of items) {
        if (item.state === 'conflict') { list.append(conflictCard(item, draw)); continue; }
        const row = h('li', { class: `outbox-item${item.state === 'failed' ? ' failed' : ''}` });
        const actions = h('div', { class: 'outbox-actions' });
        if (item.state === 'failed') {
          const again = h('button', { class: 'btn secondary', type: 'button' }, 'Retry');
          again.addEventListener('click', async () => { again.disabled = true; await retry(item.client_id); await draw(); });
          actions.append(again);
        }
        const drop = h('button', { class: 'btn danger', type: 'button', 'aria-label': `Discard: ${itemLine(item)}` }, 'Discard');
        drop.addEventListener('click', () => KH.confirm.inline(actions, drop, {
          message: isChange(item) ? `Discard “${itemLine(item)}”? The entry stays as it is on your server.`
            : item.deleted ? `Discard “${itemLine(item)}”? If the entry reached your server, it stays there.`
              : `Discard “${itemLine(item)}”? It has not reached your server, so it will be gone.`, confirmText: 'Discard',
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
        message: `Discard all ${items.length} ${items.some(isChange) ? 'items' : 'entries'} that have not reached your server?`, confirmText: 'Discard all',
        onConfirm: async () => { await discardAll(); await draw(); return true; },
      }));
      all.append(now, dropAll);
      parts.push(list, all);
      box.replaceChildren(...parts);
    };
    await draw();
    // Draw on every outbox change while the list is (or is about to be) on the page; once it has been
    // shown and is gone (Settings re-rendered or the view changed), stop listening.
    const off = onChange(() => {
      if (box.isConnected) shown = true;
      else if (shown) { stop(); return; }
      draw();
    });
    function stop() { stopped = true; off(); }
    return stop;
  }
  function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

  async function pendingCount() { const c = await refreshCounts(); return c.pending + c.failed; }

  KH.offline = { start, syncNow, pendingCount, purge, beforeSignOut, renderDevice, discard, discardAll, retry, keepSaved, useMine, items: myItems, onChange,
    isOffline: () => offline, servedOffline: (obj) => (obj && typeof obj === 'object' ? servedOffline.get(obj) || null : null),
    counts: () => ({ ...counts }), persistent: () => persistent, uuid4, entryView, withWaiting };
})();
