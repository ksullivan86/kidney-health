/* Kidney Diet Log — device mode only: the person's own server's food services and AI, through its token gateway (design note 39
   §5 to §7, plan steps 3 and 4; ARCHITECTURE.md "Device mode").

   The page builds every request and reads every answer; the iPhone app only carries it (ios/KidneyHealth/Services/ServerSync.swift),
   to the paired server over HTTPS with the token from its Keychain, and only when the method and path are on its allow-list
   (KidneyHealthCore/ServerAPI.swift). The bridge message:
       { kind: 'serverApi', method, path: '/push/v1/…', body?: '<json>', jpeg?: '<base64>', ifMatch? }
         → { ok, status, json, retryAfter? } or { error: 'not_paired' | 'offline' | 'refused' | 'bad_request' | 'no_app' }
   The token never reaches the page, and no key moves either way: the server's keys stay on the server, the phone's own keys
   (Keys and services) stay in the app.

   Which kind of token is paired comes from GET /push/v1/about (note 39 §5.3), asked at most every few minutes:
       both        200: a token "For the iPhone app, both ways" (scope app:sync). The server's food services and AI may be used.
       add_only    401 or 403: a token that only adds rows, or both ways is off on the server. It keeps working for sending rows.
       old_server  404 or 405: a server without the gateway. Sending rows still works.
       offline     the server could not be reached (asked again after a minute).
       not_paired, no_app, error.
   `about` is read leniently, since the server may grow it: `account`, `api_version`, and per feature whether it is on, either at
   the top or under `features`: `usda_search` (or `usda`), `barcodes` (or `barcode`), `ai` ({ enabled, routes: { <feature>:
   { available } } }, the routes of GET /api/ai/status). A feature it does not mention is tried; the server answers for itself.
   The AI's choice (server, then the iPhone's own, then none) is in js/mock/ai.js; the food lookups are in foods.js and barcode.js.
   No DOM, nothing stored but the answer of `about` in memory. */
(() => {
  'use strict';
  const KH = window.KH;
  const M = KH.mock;
  if (!KH.flags || KH.flags.DEVICE !== true || !M) return;

  const TTL_MS = { both: 5 * 60 * 1000, add_only: 5 * 60 * 1000, old_server: 30 * 60 * 1000, offline: 60 * 1000, error: 60 * 1000,
    not_paired: 15 * 1000, no_app: 60 * 60 * 1000 };
  const isDict = (v) => v != null && typeof v === 'object' && !Array.isArray(v);
  let known = null; // { state, server, about, at }
  let asking = null;
  const listeners = new Set();
  const emit = () => { for (const fn of [...listeners]) { try { fn(); } catch (e) { /* a view that threw must not stop the rest */ } } };

  async function ask(request) {
    let handler = null;
    try { handler = window.webkit.messageHandlers.bridge; } catch (e) { handler = null; }
    if (!handler) return { error: 'no_app' };
    try {
      const answer = await handler.postMessage(request);
      return answer && typeof answer === 'object' ? answer : { error: 'bad_answer' };
    } catch (e) {
      return { error: 'bridge' };
    }
  }
  function parse(answer) {
    if (!answer || typeof answer.json !== 'string' || !answer.json) return null;
    try { return JSON.parse(answer.json); } catch (e) { return null; }
  }

  // What `about` says, in the names this page uses. null for a flag it does not mention.
  function readAbout(json) {
    if (!isDict(json)) return null;
    const f = isDict(json.features) ? json.features : {};
    const pick = (...names) => {
      for (const n of names) {
        const v = n in f ? f[n] : json[n];
        if (typeof v === 'boolean') return v;
        if (isDict(v) && typeof v.enabled === 'boolean') return v.enabled;
        if (isDict(v) && typeof v.available === 'boolean') return v.available;
      }
      return null;
    };
    const ai = isDict(f.ai) ? f.ai : isDict(json.ai) ? json.ai : null;
    let routes = null;
    const raw = ai && isDict(ai.routes) ? ai.routes : null;
    if (raw) {
      routes = {};
      for (const [k, v] of Object.entries(raw)) routes[k] = v === true || (isDict(v) && v.available === true);
    }
    return { account: typeof json.account === 'string' ? json.account.slice(0, 200) : null, version: Number(json.api_version) || null,
      sync: pick('sync'), usda: pick('usda_search', 'usda'), barcode: pick('barcodes', 'barcode'), ai: pick('ai'), aiRoutes: routes };
  }

  function remember(state, server = known ? known.server : null, about = null) {
    const before = known ? known.state : null;
    known = { state, server, about, at: Date.now() };
    if (before !== state) emit();
    return known;
  }

  // What the paired server offers this phone now. `force` asks again whatever the cache says.
  async function check({ force = false } = {}) {
    if (!force && known && Date.now() - known.at < (TTL_MS[known.state] || 60000)) return known;
    if (asking) return asking;
    asking = (async () => {
      const info = await ask({ kind: 'serverInfo' });
      if (info.error === 'no_app') return remember('no_app', null);
      if (!info.ok || !info.paired) return remember('not_paired', null);
      const server = typeof info.server === 'string' ? info.server.slice(0, 300) : null;
      const res = await ask({ kind: 'serverApi', method: 'GET', path: '/push/v1/about' });
      if (res.error === 'offline') return remember('offline', server);
      if (res.error === 'not_paired') return remember('not_paired', null);
      if (res.error) return remember('error', server);
      if (res.status === 200) {
        const about = readAbout(parse(res));
        return about ? remember('both', server, about) : remember('error', server);
      }
      if (res.status === 401 || res.status === 403) return remember('add_only', server);
      if (res.status === 404 || res.status === 405) return remember('old_server', server);
      return remember('error', server);
    })();
    try { return await asking; } finally { asking = null; }
  }
  function forget() { known = null; emit(); }

  // May the page use the server for `what` ('usda', 'barcode', 'ai')? Only with a token both ways; a flag `about` sets to false
  // says no; one it does not mention says yes (the server answers for itself).
  async function offers(what) {
    const k = await check();
    if (k.state !== 'both') return false;
    const flag = k.about ? k.about[what] : null;
    return flag !== false;
  }

  // One request through the gateway. `path` is the /api path (or a /push/v1 path). Answers { status, json, retryAfter } when the
  // server answered, { offline: true } when it could not be reached, or { error } when the app refused or is missing.
  async function call(method, path, { body, jpeg, ifMatch } = {}) {
    const request = { kind: 'serverApi', method, path: path.startsWith('/push/v1/') ? path : `/push/v1${path}` };
    if (body !== undefined) request.body = JSON.stringify(body);
    if (jpeg) request.jpeg = jpeg;
    if (ifMatch) request.ifMatch = ifMatch;
    const res = await ask(request);
    if (res.error === 'offline') { remember('offline'); return { offline: true }; }
    if (res.error) return { error: res.error };
    if (res.status === 401 || res.status === 403) forget(); // the token changed or was revoked: ask `about` again next time
    return { status: res.status, json: parse(res), retryAfter: res.retryAfter || null };
  }

  // The server's error answer as the page's own (its detail and the keys beside it, such as reason, consent or retry_after).
  function failWith(res) {
    const json = isDict(res.json) ? res.json : {};
    const detail = typeof json.detail === 'string' ? json.detail : `Your server answered ${res.status}.`;
    const extra = { ...json };
    delete extra.detail;
    if (res.retryAfter && extra.retry_after == null) extra.retry_after = res.retryAfter;
    M.fail(res.status, detail, Object.keys(extra).length ? extra : null);
  }

  // A photo (a Blob) as base64 for the bridge.
  async function base64(blob) {
    const buf = new Uint8Array(await blob.arrayBuffer());
    let text = '';
    for (let i = 0; i < buf.length; i += 0x8000) text += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return btoa(text);
  }

  M.serverApi = {
    check, offers, call, failWith, forget, readAbout, base64,
    status: () => known,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
})();
