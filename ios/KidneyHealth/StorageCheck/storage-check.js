// Design note 38, step 0: does data this page stores survive closing the app, offloading it and weeks without opening it?
// Each time the page opens it adds the time to IndexedDB and to localStorage, then reports how many times each holds and the
// first one. It stores dates only, and it never reaches the network (the page's CSP has connect-src 'none').
'use strict';

const DB_NAME = 'kh-storage-check';
const STORE = 'opens';
const LOCAL_KEY = 'kh-storage-check-opens';

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { autoIncrement: true });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function addAndReadAll(db, at) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    store.add({ at });
    const all = store.getAll();
    tx.oncomplete = () => resolve(all.result.map((row) => row.at));
    tx.onerror = () => reject(tx.error);
  });
}

async function indexedDbOpens(at) {
  try {
    const db = await openDb();
    const opens = await addAndReadAll(db, at);
    db.close(); // closed at once, so a force-quit cannot leave it half written
    return { count: opens.length, first: opens[0] || null };
  } catch (error) {
    return { error: String(error && error.message || error) };
  }
}

function localStorageOpens(at) {
  try {
    const opens = JSON.parse(localStorage.getItem(LOCAL_KEY) || '[]');
    opens.push(at);
    localStorage.setItem(LOCAL_KEY, JSON.stringify(opens));
    return { count: opens.length, first: opens[0] };
  } catch (error) {
    return { error: String(error && error.message || error) };
  }
}

async function storageInfo() {
  const info = { persisted: null, usage: null, quota: null };
  try {
    if (navigator.storage && navigator.storage.persisted) info.persisted = await navigator.storage.persisted();
    if (navigator.storage && navigator.storage.estimate) {
      const estimate = await navigator.storage.estimate();
      info.usage = estimate.usage;
      info.quota = estimate.quota;
    }
  } catch (error) {
    info.error = String(error && error.message || error);
  }
  return info;
}

function describe(name, result) {
  if (result.error) return `${name}: could not be used (${result.error})`;
  return `${name}: opened ${result.count} time${result.count === 1 ? '' : 's'}, first ${result.first}`;
}

async function run() {
  const at = new Date().toISOString();
  const report = {
    origin: location.origin,
    indexedDB: await indexedDbOpens(at),
    localStorage: localStorageOpens(at),
    storage: await storageInfo(),
  };
  document.getElementById('result').textContent = [
    describe('IndexedDB', report.indexedDB),
    describe('localStorage', report.localStorage),
    `Kept for good: ${report.storage.persisted === null ? 'unknown' : report.storage.persisted ? 'yes' : 'no'}`,
  ].join('\n');
  try {
    window.webkit.messageHandlers.storageCheck.postMessage(JSON.stringify(report));
  } catch (error) {
    // Outside the app there is no native side to tell.
  }
}

run();
