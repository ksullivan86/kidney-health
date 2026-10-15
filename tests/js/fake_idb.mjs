// A small stand-in for window.indexedDB, enough for app/static/js/mock/persist.js: databases with one or more object stores,
// open / upgrade (with abort) / transaction / get / put / delete / deleteDatabase, structured cloning of what is stored, and
// switches for the failures the module must survive (a refusing browser, a full disk, a second tab that wrote first).
//
//   const idb = createFakeIndexedDB();   idb.calls.opens  idb.databases  idb.refuse = 'SecurityError'  idb.failPut = 'QuotaExceededError'
//
// It is NOT a conformance implementation: requests settle on the next macrotask, a transaction completes when its requests are
// done, and an aborted transaction drops its writes. Used by tests/js/demo_local_storage.mjs (pytest: tests/test_demo_local_storage.py).
const later = (fn) => setTimeout(fn, 0);
const defaultClone = (v) => (v === undefined ? undefined : structuredClone(v));

function domError(name, message = name) { const e = new Error(message); e.name = name; return e; }

class Request {
  constructor() { this.result = undefined; this.error = null; this.onsuccess = null; this.onerror = null; this.transaction = null; }
  succeed(value) { this.result = value; if (this.onsuccess) this.onsuccess({ target: this }); }
  fail(error) { this.error = error; if (this.onerror) this.onerror({ target: this, preventDefault() {} }); }
}

class Transaction {
  constructor(db, names, mode, upgrade = false) {
    this.db = db; this.mode = mode; this.names = names; this.pending = 0; this.buffer = []; this.aborted = false; this.finished = false;
    this.oncomplete = null; this.onabort = null; this.onerror = null; this.error = null; this.upgrade = upgrade;
  }
  objectStore(name) {
    if (!this.names.includes(name) || !this.db.data.stores.has(name)) throw domError('NotFoundError', `no object store ${name}`);
    return new ObjectStore(this, name);
  }
  abort() {
    if (this.finished || this.aborted) throw domError('InvalidStateError');
    this.aborted = true; this.buffer = [];
    later(() => { this.finished = true; if (this.error === null) this.error = domError('AbortError'); if (this.onabort) this.onabort({ target: this }); });
  }
  settle() {
    if (this.upgrade) return; // the open request completes it
    later(() => {
      if (this.finished || this.aborted || this.pending > 0) return;
      this.finished = true;
      for (const op of this.buffer) {
        const store = this.db.data.stores.get(op.store);
        if (op.type === 'put') store.set(op.key, op.value); else store.delete(op.key);
      }
      this.buffer = [];
      if (this.oncomplete) this.oncomplete({ target: this });
    });
  }
}

class ObjectStore {
  constructor(tx, name) { this.tx = tx; this.name = name; }
  _run(work) {
    const tx = this.tx;
    if (tx.finished || tx.aborted) throw domError('TransactionInactiveError');
    const req = new Request();
    tx.pending += 1;
    later(() => {
      tx.pending -= 1;
      if (tx.aborted) return;
      try { req.succeed(work()); } catch (e) { req.fail(e); }
      tx.settle();
    });
    return req;
  }
  _read(key) {
    for (let i = this.tx.buffer.length - 1; i >= 0; i--) {
      const op = this.tx.buffer[i];
      if (op.store === this.name && op.key === key) return op.type === 'put' ? op.value : undefined;
    }
    return this.tx.db.data.stores.get(this.name).get(key);
  }
  get(key) { const clone = this.tx.db.factory.clone; return this._run(() => clone(this._read(key))); }
  put(value, key) {
    if (this.tx.mode === 'readonly') throw domError('ReadOnlyError');
    const idb = this.tx.db.factory;
    if (idb.failPut) {
      const name = idb.failPut;
      const tx = this.tx;
      tx.error = domError(name);
      later(() => { if (!tx.aborted && !tx.finished) { tx.aborted = true; tx.buffer = []; tx.finished = true; if (tx.onabort) tx.onabort({ target: tx }); } });
      tx.pending += 1; // never completes
      return new Request();
    }
    const cloned = idb.clone(value); // DataCloneError for a function, as a real browser
    return this._run(() => { this.tx.buffer.push({ type: 'put', store: this.name, key, value: cloned }); return key; });
  }
  delete(key) { return this._run(() => { this.tx.buffer.push({ type: 'delete', store: this.name, key }); }); }
}

class Database {
  constructor(factory, name, data) { this.factory = factory; this.name = name; this.data = data; this.closed = false; this.onversionchange = null; }
  get version() { return this.data.version; }
  createObjectStore(name) { this.data.stores.set(name, new Map()); return new ObjectStore(this.upgradeTx, name); }
  transaction(names, mode = 'readonly') {
    if (this.closed) throw domError('InvalidStateError', 'the database is closed');
    const list = Array.isArray(names) ? names : [names];
    for (const n of list) if (!this.data.stores.has(n)) throw domError('NotFoundError', `no object store ${n}`);
    const tx = new Transaction(this, list, mode);
    tx.settle();
    return tx;
  }
  close() { this.closed = true; this.data.connections.delete(this); }
}

// clone: how a value is copied in and out (default structuredClone; a test passes one made inside the page's own realm);
// databases: shared between two "page loads" of the same browser profile.
export function createFakeIndexedDB({ clone = defaultClone, databases = new Map() } = {}) {
  const factory = {
    clone,
    databases, // name -> { version, stores: Map(name -> Map(key -> value)), connections: Set }
    calls: { opens: 0, deletes: 0 },
    refuse: null, // an error name: open() throws it at once (a sandboxed frame, blocked site data)
    failPut: null, // an error name: every put aborts its transaction with it (a full disk)
    open(name, version = 1) {
      factory.calls.opens += 1;
      if (factory.refuse) throw domError(factory.refuse);
      const req = new Request();
      later(() => {
        let data = factory.databases.get(name);
        const fresh = !data;
        if (fresh) data = { version: 0, stores: new Map(), connections: new Set() };
        const db = new Database(factory, name, data);
        if (fresh || data.version < version) {
          const tx = new Transaction(db, [...data.stores.keys()], 'versionchange', true);
          db.upgradeTx = tx;
          req.transaction = tx; req.result = db;
          const was = data.version;
          data.version = version;
          factory.databases.set(name, data);
          if (req.onupgradeneeded) req.onupgradeneeded({ target: req, oldVersion: was, newVersion: version });
          if (tx.aborted) {
            if (fresh) factory.databases.delete(name); else data.version = was;
            later(() => req.fail(domError('AbortError', 'the upgrade was aborted')));
            return;
          }
        }
        data.connections.add(db);
        req.succeed(db);
      });
      return req;
    },
    deleteDatabase(name) {
      factory.calls.deletes += 1;
      const req = new Request();
      later(() => {
        const data = factory.databases.get(name);
        if (data) for (const db of [...data.connections]) { if (db.onversionchange) db.onversionchange({}); }
        factory.databases.delete(name);
        req.succeed(undefined);
      });
      return req;
    },
    // test helpers
    read(dbName, store, key) { const d = factory.databases.get(dbName); return d && d.stores.get(store) ? clone(d.stores.get(store).get(key)) : undefined; },
    write(dbName, store, key, value) { const d = factory.databases.get(dbName); d.stores.get(store).set(key, clone(value)); },
    page(cloneForPage) { return createFakeIndexedDB({ clone: cloneForPage, databases: factory.databases }); },
  };
  return factory;
}
