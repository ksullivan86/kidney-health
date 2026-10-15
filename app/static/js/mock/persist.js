/* Kidney Diet Log — demo only: "Keep my data in this browser" (ARCHITECTURE.md "Keep my data in this browser").

   The Pages demo answers every /api call from an in-page copy of the server (js/mock/*) that lives in memory. This file lets a
   person choose, once and on purpose, to keep that copy in this browser's IndexedDB so the demo works as a small log with no
   server: the whole state of the demo API is saved after each write that went through (debounced), and read back at the next
   start. Nothing is sent anywhere. It is OFF unless the person turned it on in the sheet js/views/demo_local.js opens, and it
   is only reachable in the demo build (window.KDL_PREVIEW): `allowed()` is false in the installed app, which therefore never
   opens a database from here (tests/test_demo_local_ui.py, tests/js/demo_local_storage.mjs).

   Stored record (one key, "current", in the object store "state" of the database "kdl-demo-local"):
       { format: "kidney-health-demo-local", schema: 1, rev, savedAt, foodsVersion, state: {…the demo API's own properties…} }
   * `schema` is the shape of `state`. A copy with a NEWER schema than this file knows is never loaded and never overwritten
     (the sheet says why); an unreadable one is treated the same. Change the shape of the demo's state in a way an old copy
     cannot satisfy → bump SCHEMA and add the step to `migrate()`. Properties the mock creates lazily need no step.
   * `rev` counts the saves. A save only goes through when the stored rev is the one this page loaded or wrote last, inside one
     transaction: a second tab that changed the data first makes this page stop saving (and say so) instead of overwriting it.
   Every IndexedDB call is inside try/catch and rejects with a plain sentence; where IndexedDB is missing or refuses (private
   browsing, blocked site data, a sandboxed frame) the demo stays in memory and the sheet says so. A database is created only when
   the person turns the mode on; starting the demo only looks for an existing one and never leaves an empty one behind.

   No network, no storage but IndexedDB (and navigator.storage.persist() for the "keep it" request), no DOM. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;

  const DB_NAME = 'kdl-demo-local';
  const DB_VERSION = 1;
  const STORE = 'state';
  const KEY = 'current';
  const FORMAT = 'kidney-health-demo-local';
  const SCHEMA = 1;
  const SAVE_DELAY_MS = 1500;
  // Derived caches of the demo API, rebuilt on demand: never saved.
  const TRANSIENT = new Set(['_guidanceVectors']);

  const st = {
    on: false, // the mode is on: a copy is stored and every write is saved
    blocked: null, // { code: 'newer' | 'unreadable', message }: a stored copy this page will not load, change or delete
    unavailable: null, // why IndexedDB cannot be used here, once something tried
    persisted: null, // navigator.storage.persist(): true granted, false not granted, null unknown
    savedAt: null, // ISO time of the last save (or of the copy loaded)
    rev: 0,
    saving: false,
    error: null, // the last save failed: a sentence for the person (the copy on disk is the one before)
    conflict: false, // another tab changed the stored copy: this page no longer saves
  };
  const listeners = new Set();
  let override; // tests: a stand-in for window.indexedDB (undefined → the page's own)
  let timer = null;
  let dirty = false;

  const emit = () => { for (const fn of [...listeners]) { try { fn(status()); } catch (e) { /* a view that threw must not stop a save */ } } };
  function status() {
    return { on: st.on, blocked: st.blocked, unavailable: st.unavailable, persisted: st.persisted, savedAt: st.savedAt, saving: st.saving,
      error: st.error, conflict: st.conflict, allowed: allowed() };
  }
  // The demo build only (scripts/build_preview.py --pages / the self-contained preview set window.KDL_PREVIEW). The installed app,
  // and a development server's ?mock=1 page, never use this.
  function allowed() { return !!(KH.flags && KH.flags.PREVIEW === true && M.instance); }

  function factory() {
    if (override !== undefined) return override;
    try { return window.indexedDB || null; } catch (e) { return null; } // a sandboxed frame throws on the property itself
  }
  const NO_STORAGE = 'This browser does not let this page store data (private browsing, blocked site data, or a frame without storage). The demo stays in memory: nothing is saved.';
  function problem(e, fallback = NO_STORAGE) {
    const name = e && e.name;
    if (name === 'QuotaExceededError') return 'This browser has no room left to save. Export your data, free some space, then try again.';
    if (name === 'SecurityError' || name === 'InvalidStateError' || name === 'NotAllowedError') return NO_STORAGE;
    return e && e.userMessage ? e.userMessage : fallback;
  }
  const unavailableError = (message) => Object.assign(new Error(message), { name: 'Unavailable', userMessage: message });

  function result(req) {
    return new Promise((resolve, reject) => { req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });
  }
  // Opens the database. create: false never leaves one behind: an upgrade means there was none, so it is aborted and null answers.
  function openDb({ create }) {
    return new Promise((resolve, reject) => {
      const f = factory();
      if (!f) { reject(unavailableError(NO_STORAGE)); return; }
      let req;
      let none = false;
      try { req = f.open(DB_NAME, DB_VERSION); } catch (e) { reject(e); return; }
      req.onupgradeneeded = () => {
        if (create) { try { req.result.createObjectStore(STORE); } catch (e) { reject(e); } return; }
        none = true;
        try { req.transaction.abort(); } catch (e) { /* the open fails next */ }
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onversionchange = () => { try { db.close(); } catch (e) { /* already closed */ } }; // never hold up another tab's delete
        resolve(db);
      };
      req.onerror = (ev) => {
        if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
        if (none) resolve(null); else reject(req.error || unavailableError(NO_STORAGE));
      };
      req.onblocked = () => { /* waits for the other tab to let go */ };
    });
  }
  async function readRecord() {
    const db = await openDb({ create: false });
    if (!db) return null;
    try {
      const value = await result(db.transaction(STORE, 'readonly').objectStore(STORE).get(KEY));
      return value === undefined ? null : value;
    } finally { try { db.close(); } catch (e) { /* ignore */ } }
  }

  // What a stored record is to this version of the page.
  function migrate(record) { return record; } // schema 1 is the first: nothing to carry forward yet
  function classify(rec) {
    if (rec == null) return { kind: 'none' };
    const shaped = typeof rec === 'object' && rec.format === FORMAT && Number.isInteger(rec.schema) && rec.schema >= 1
      && rec.state && typeof rec.state === 'object' && !Array.isArray(rec.state);
    if (!shaped) {
      return { kind: 'unreadable', message: 'A copy of data is stored in this browser by this demo, but it cannot be read. It was not loaded and it will not be changed or deleted.' };
    }
    if (rec.schema > SCHEMA) {
      return { kind: 'newer', schema: rec.schema, message: `The copy stored in this browser was saved by a newer version of this demo (format ${rec.schema}; this page reads up to ${SCHEMA}). It was not loaded and it will not be changed or deleted. Open the newer demo to use it.` };
    }
    return { kind: 'ok', record: migrate(rec) };
  }

  function buildRecord(api) {
    const state = {};
    for (const key of Object.keys(api)) if (!TRANSIENT.has(key)) state[key] = api[key];
    return { format: FORMAT, schema: SCHEMA, savedAt: new Date().toISOString(), foodsVersion: api.foodsVersion || null, state };
  }
  // One transaction: read the stored copy, check it is still the one this page knows, write the next revision.
  // expect: 'none' (turning on: nothing may be there) or the rev this page loaded or wrote last.
  async function writeRecord(record, expect) {
    const db = await openDb({ create: true });
    try {
      return await new Promise((resolve, reject) => {
        let outcome = null;
        let tx;
        try { tx = db.transaction(STORE, 'readwrite'); } catch (e) { reject(e); return; }
        const os = tx.objectStore(STORE);
        const getReq = os.get(KEY);
        getReq.onsuccess = () => {
          const cur = getReq.result;
          if (cur != null && (typeof cur !== 'object' || cur.format !== FORMAT || !Number.isInteger(cur.schema) || cur.schema > SCHEMA)) {
            outcome = { conflict: 'foreign' }; try { tx.abort(); } catch (e) { /* ignore */ } return;
          }
          const curRev = cur ? (Number.isInteger(cur.rev) ? cur.rev : 0) : 0;
          if ((expect === 'none' && cur != null) || (expect !== 'none' && (cur == null || curRev !== expect))) {
            outcome = { conflict: 'changed' }; try { tx.abort(); } catch (e) { /* ignore */ } return;
          }
          try { os.put({ ...record, rev: curRev + 1 }, KEY); outcome = { rev: curRev + 1 }; } catch (e) { reject(e); try { tx.abort(); } catch (e2) { /* ignore */ } }
        };
        tx.oncomplete = () => resolve(outcome || { conflict: 'changed' });
        tx.onabort = () => (outcome && outcome.conflict ? resolve(outcome) : reject(tx.error || unavailableError('The save was cancelled.')));
        tx.onerror = () => { /* onabort follows */ };
      });
    } finally { try { db.close(); } catch (e) { /* ignore */ } }
  }
  function deleteDb() {
    return new Promise((resolve, reject) => {
      const f = factory();
      if (!f) { resolve(); return; }
      let req;
      try { req = f.deleteDatabase(DB_NAME); } catch (e) { reject(e); return; }
      const giveUp = setTimeout(() => reject(unavailableError('Another tab of this demo is still open and holds the stored copy. Close it, then try again.')), 8000);
      req.onsuccess = () => { clearTimeout(giveUp); resolve(); };
      req.onerror = () => { clearTimeout(giveUp); reject(req.error || unavailableError(NO_STORAGE)); };
      req.onblocked = () => { /* the other tab closes its connection on versionchange */ };
    });
  }

  // A browser may ask the person before it answers (Firefox does); the answer is optional, so waiting for it has an end.
  const PERSIST_WAIT_MS = 8000;
  async function askPersistent() {
    try {
      if (typeof navigator === 'undefined' || !navigator.storage) return null;
      if (typeof navigator.storage.persisted === 'function' && await navigator.storage.persisted()) return true;
      if (typeof navigator.storage.persist === 'function') {
        let timer;
        const gaveUp = new Promise((resolve) => { timer = setTimeout(() => resolve(null), PERSIST_WAIT_MS); });
        try { return await Promise.race([navigator.storage.persist().then((granted) => !!granted), gaveUp]); } finally { clearTimeout(timer); }
      }
    } catch (e) { /* the question is optional */ }
    return null;
  }
  async function knowPersistent() {
    try {
      if (typeof navigator !== 'undefined' && navigator.storage && typeof navigator.storage.persisted === 'function') return !!(await navigator.storage.persisted());
    } catch (e) { /* ignore */ }
    return null;
  }

  // ---- saving ----
  function scheduleSave() {
    if (!st.on || st.conflict) return;
    dirty = true;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => { timer = null; flush(); }, SAVE_DELAY_MS);
  }
  // Saves now (also what the debounce calls). Resolves when this save has finished; never rejects.
  async function flush() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!st.on || st.conflict || !M.instance) return status();
    if (st.saving) { dirty = true; return status(); }
    if (!dirty && !st.error) return status();
    dirty = false;
    st.saving = true; emit();
    try {
      const out = await writeRecord(buildRecord(M.instance), st.rev);
      if (out.conflict) {
        st.conflict = true;
        st.error = 'Another tab changed the data stored in this browser. This page has stopped saving so it cannot overwrite it. Export what you need from here, then reload the page.';
      } else { st.rev = out.rev; st.savedAt = new Date().toISOString(); st.error = null; }
    } catch (e) {
      st.error = problem(e, 'The data could not be saved in this browser just now. It is still in this page; it will be tried again after the next change.');
      dirty = true;
    } finally { st.saving = false; }
    emit();
    if (dirty && !st.error && !st.conflict) scheduleSave();
    return status();
  }

  // Replace everything the demo API holds with a stored state (the same object stays the page's instance).
  function applyState(api, state) {
    for (const key of Object.keys(api)) delete api[key];
    Object.assign(api, state);
  }

  // Called once by main.js before the first request, in the demo only.
  async function boot() {
    if (!allowed()) return status();
    try {
      const rec = await readRecord();
      const c = classify(rec);
      if (c.kind === 'ok') {
        applyState(M.instance, c.record.state);
        st.on = true; st.rev = Number.isInteger(rec.rev) ? rec.rev : 0; st.savedAt = rec.savedAt || null;
        st.persisted = await knowPersistent();
      } else if (c.kind !== 'none') st.blocked = { code: c.kind, message: c.message };
    } catch (e) {
      st.unavailable = problem(e); // nothing stored is known; stay in memory and say so when asked
    }
    if (typeof document !== 'undefined' && document && document.addEventListener) {
      try { document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); }); } catch (e) { /* no document */ }
    }
    emit();
    return status();
  }

  // The sheet's probe: can this page store anything at all? (Opens without creating.) Sets `unavailable`.
  async function probe() {
    if (!allowed()) { st.unavailable = 'Keeping data in the browser is only offered in the demo.'; return status(); }
    try { await readRecord(); st.unavailable = null; } catch (e) { st.unavailable = problem(e); }
    emit();
    return status();
  }

  // Turn the mode on. fresh: start from an empty account (the person brings their own data) instead of the sample person; the
  // page then reloads (the caller) and starts from what was stored. Resolves { reload } or rejects with an Error holding a sentence.
  async function enable({ fresh = true } = {}) {
    if (!allowed()) throw unavailableError('Keeping data in the browser is only offered in the demo.');
    if (st.blocked) throw unavailableError(st.blocked.message);
    if (st.on) return { reload: false };
    st.persisted = await askPersistent();
    const api = M.instance;
    const source = fresh ? new M.MockApi({ foodsData: M.embeddedFoods ? M.embeddedFoods() : null, seed: false }) : api;
    let out;
    try { out = await writeRecord(buildRecord(source), 'none'); } catch (e) { st.unavailable = problem(e); emit(); throw unavailableError(problem(e)); }
    if (out.conflict) throw unavailableError('A copy is already stored in this browser by another tab of this demo. Reload this page to use it.');
    st.on = true; st.rev = out.rev; st.savedAt = new Date().toISOString(); st.error = null; st.unavailable = null; dirty = false;
    emit();
    return { reload: fresh };
  }

  // Delete the stored copy and go back to the in-memory demo (the caller reloads: the sample demo starts again).
  async function disable() {
    if (timer) { clearTimeout(timer); timer = null; }
    dirty = false;
    const wasOn = st.on;
    st.on = false; // no new save starts from here on; one already running is waited for (it could otherwise write after the delete)
    for (let waited = 0; st.saving && waited < 3000; waited += 25) await new Promise((r) => setTimeout(r, 25));
    try { await deleteDb(); } catch (e) { st.on = wasOn; throw unavailableError(problem(e, 'The stored copy could not be deleted just now.')); }
    st.rev = 0; st.savedAt = null; st.error = null; st.conflict = false; st.persisted = null;
    emit();
    return { reload: true };
  }

  // A POST that only asks (the import's dry run changes nothing) is not a reason to save.
  const ASKS_ONLY = /^\/api\/me\/import\?(?:[^#]*&)?dry_run=(?:1|true|yes|on|t|y)(?:&|$)/i;
  M.onWrite = (api, method, path) => { if (st.on && api === M.instance && !ASKS_ONLY.test(path)) scheduleSave(); };
  M.local = {
    DB_NAME, STORE, KEY, FORMAT, SCHEMA, SAVE_DELAY_MS,
    allowed, on: () => st.on, status, boot, probe, enable, disable, flush,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    // for the tests: a stand-in for window.indexedDB, and the pure parts
    _useIndexedDB(fake) { override = fake; },
    _classify: classify, _buildRecord: buildRecord, _applyState: applyState,
  };
})();
