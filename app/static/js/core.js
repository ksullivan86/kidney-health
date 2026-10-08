/* Kidney Diet Log — core: DOM helpers, icons, the API client, shared state, toasts, theme,
   view router, sheets (dialogs) and the in-page confirmation. Vanilla ES2020, no dependencies,
   no HTML string sinks (the page runs under a strict CSP with Trusted Types; build DOM with
   KH.h / KH.s and textContent only).

   Everything hangs off window.KH. Load order (index.html): js/engine/*.js, core.js, js/mock/*.js,
   js/views/*.js, pwa.js, main.js. Talks only to same-origin /api/... (see ARCHITECTURE.md);
   ?mock=1 or window.KDL_PREVIEW runs against the in-page demo API (js/mock/*). */
(() => {
  'use strict';
  const KH = window.KH || (window.KH = {});
  const { NUT, MEAL_LABEL, fmtNum, pct } = KH.rules;

  // Demo mode runs an in-page copy of the server (no backend): `?mock=1` while developing, or
  // window.KDL_PREVIEW === true in the self-contained preview built by scripts/build_preview.py
  // (the preview's host does not pass a query string to the page).
  const PREVIEW = window.KDL_PREVIEW === true;
  const QUERY = (() => { try { return String(location.search || ''); } catch (e) { return ''; } })();
  const MOCK = PREVIEW || /[?&]mock=1(?:&|$)/.test(QUERY);
  const MOCK_HD = MOCK && /[?&]hd=1(?:&|$)/.test(QUERY); // demo profile on hemodialysis (Mon/Wed/Fri)
  const THEME_KEY = 'kdl-theme';
  const SHOP_KEY = 'kdl-shop'; // shopping-list checkboxes live only in this browser
  const SVG_NS = 'http://www.w3.org/2000/svg';

  // ---------------------------------------------------------------------------
  // UI orderings and labels
  // ---------------------------------------------------------------------------
  const KEY_NUMBERS = ['carbs_g', 'protein_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg'];
  const ROW_NUMBERS = ['carbs_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg'];
  const STATUS_ORDER = ['carbs_g', 'potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'fluid_ml', 'calories_kcal', 'calcium_mg', 'fiber_g'];
  const TREND_ORDER = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'carbs_g', 'fluid_ml', 'calories_kcal', 'calcium_mg'];
  const PLAN_CHIPS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g', 'carbs_g', 'fluid_ml'];
  const STRIP_KEYS = ['potassium_mg', 'phosphorus_mg', 'sodium_mg', 'protein_g'];
  const INTERDIALYTIC_KEYS = ['potassium_mg', 'sodium_mg', 'fluid_ml'];
  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']; // 0 = Monday, as in the contract
  const WEEKDAYS_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const RATING_LABEL = {
    green: 'Green: generally kidney-friendly',
    yellow: 'Yellow: moderate, watch the portion',
    red: 'Red: high, needs careful consideration',
    unknown: 'Not complete: some foods do not list this value',
  };
  // "unknown": a total under its limit that misses values some foods do not list, so it may be higher (never green).
  const LEVEL_TEXT = { ok: 'OK', caution: 'Near limit', over: 'Over limit', unknown: 'Not complete' };
  // A range whose minimum equals its maximum is "about X" (protein 0.8 g/kg with diabetes, note 05 §4.8): it is a
  // target, not a limit, so its levels read "Near target" / "Above target" (v0.3.0 review L8). The level itself
  // (and its colour) stays the server's: how far above "about" still counts as on target is a clinical decision
  // the app does not make (handbook/REVIEW.md, "Food targets").
  const ABOUT_LEVEL_TEXT = { ok: 'OK', caution: 'Near target', over: 'Above target', unknown: 'Not complete' };
  // `key` (optional): a limit (potassium, sodium, phosphorus, fluid) is never an "about" target (nutrients.is_about).
  const isAboutTarget = (st, key = null) => !!st && st.min != null && st.target != null && Number(st.min) === Number(st.target)
    && !(key && KH.rules.NUT[key] && KH.rules.NUT[key].role === 'limit');
  const levelTextFor = (st, level, key = null) => (isAboutTarget(st, key) ? ABOUT_LEVEL_TEXT : LEVEL_TEXT)[level] || level;
  const LEVEL_RATING = { ok: 'green', caution: 'yellow', over: 'red', medium: 'yellow', high: 'red', unknown: 'unknown' };

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function setAttrs(el, attrs) {
    if (!attrs) return el;
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.setAttribute('class', v);
      else if (k === 'text') el.textContent = v;
      else if (k === 'style') el.style.cssText = String(v); // CSSOM, not a style attribute: allowed by style-src 'self'
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    return el;
  }
  function appendChildren(el, children) {
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  function h(tag, attrs, ...children) {
    return appendChildren(setAttrs(document.createElement(tag), attrs), children);
  }
  function s(tag, attrs, ...children) {
    return appendChildren(setAttrs(document.createElementNS(SVG_NS, tag), attrs), children);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

  function localISO(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  function todayStr() { return localISO(new Date()); }
  function parseDate(str) { const [y, m, d] = str.split('-').map(Number); return new Date(y, m - 1, d); }
  function addDays(str, n) { const d = parseDate(str); d.setDate(d.getDate() + n); return localISO(d); }
  function fmtDateLong(str) {
    const d = parseDate(str);
    const t = todayStr();
    if (str === t) return `Today, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    if (str === addDays(t, -1)) return `Yesterday, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    if (str === addDays(t, 1)) return `Tomorrow, ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
  }
  function fmtDateShort(str) {
    return parseDate(str).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  }
  function fmtMonthDay(str) { return parseDate(str).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); }
  function fmtRange(start, end) { return `${fmtMonthDay(start)} – ${fmtMonthDay(end)}`; }
  function weekdayMon(str) { return (parseDate(str).getDay() + 6) % 7; } // 0 = Monday … 6 = Sunday
  function weekStartOf(str, weekStart) {
    const back = weekStart === 'sunday' ? parseDate(str).getDay() : weekdayMon(str);
    return addDays(str, -back);
  }
  function daysBetween(a, b) { return Math.round((parseDate(b) - parseDate(a)) / 86400000); }
  function defaultStatusFor(date) { return date > todayStr() ? 'planned' : 'eaten'; }
  function fmtChange(pctValue) {
    if (pctValue == null || !Number.isFinite(Number(pctValue))) return null;
    const n = Math.round(Number(pctValue) * 10) / 10;
    if (Math.abs(n) < 0.05) return 'no change';
    return `${n > 0 ? '+' : '−'}${Math.abs(n).toLocaleString('en-US', { maximumFractionDigits: 1 })} %`;
  }
  function defaultMealForNow() {
    const hr = new Date().getHours();
    if (hr < 10) return 'breakfast';
    if (hr < 14) return 'lunch';
    if (hr < 17) return 'snack';
    if (hr < 21) return 'dinner';
    return 'snack';
  }
  function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }
  function qs(params) {
    const u = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== '') u.set(k, v);
    return u.toString();
  }
  function numOrNull(v) {
    if (v == null) return null;
    const str = String(v).trim();
    if (str === '') return null;
    const n = Number(str);
    return Number.isFinite(n) ? n : null;
  }

  // ---------------------------------------------------------------------------
  // Icons
  // ---------------------------------------------------------------------------
  function ratingIcon(ratingOrLevel, opts = {}) {
    const r = LEVEL_RATING[ratingOrLevel] || ratingOrLevel || 'green';
    const label = opts.label || RATING_LABEL[r];
    const svg = s('svg', { class: `rating ${r}`, viewBox: '0 0 24 24', focusable: 'false' });
    if (opts.decorative) svg.setAttribute('aria-hidden', 'true');
    else { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label); svg.append(s('title', {}, label)); }
    if (r === 'green') {
      svg.append(s('circle', { class: 'shape', cx: 12, cy: 12, r: 11 }));
      svg.append(s('path', { class: 'glyph', d: 'M6.8 12.6l1.7-1.7 2.6 2.6 5.4-5.4 1.7 1.7-7.1 7.1z' }));
    } else if (r === 'yellow') {
      svg.append(s('path', { class: 'shape', d: 'M12 2.2 23 21.5H1z' }));
      svg.append(s('rect', { class: 'glyph', x: 10.9, y: 9, width: 2.2, height: 6.2, rx: 1 }));
      svg.append(s('circle', { class: 'glyph', cx: 12, cy: 18.2, r: 1.35 }));
    } else if (r === 'unknown') {
      svg.append(s('circle', { class: 'shape', cx: 12, cy: 12, r: 11 }));
      svg.append(s('path', { class: 'glyph', d: 'M9.1 9.4a2.9 2.9 0 1 1 4.3 2.6c-.9.5-1.3 1-1.3 1.9v.6h-2.2v-.8c0-1.6.8-2.5 1.9-3.1a.8.8 0 1 0-1.2-.8z' }));
      svg.append(s('circle', { class: 'glyph', cx: 11, cy: 17.6, r: 1.35 }));
    } else {
      svg.append(s('path', { class: 'shape', d: 'M7.6 1.5h8.8l6.1 6.1v8.8l-6.1 6.1H7.6l-6.1-6.1V7.6z' }));
      svg.append(s('rect', { class: 'glyph', x: 10.9, y: 6, width: 2.2, height: 7.5, rx: 1 }));
      svg.append(s('circle', { class: 'glyph', cx: 12, cy: 16.8, r: 1.45 }));
    }
    return svg;
  }
  // Values a food does not list (most scanned products give no potassium or phosphorus). A total skips them, and
  // the server says how many entries each total misses (ARCHITECTURE.md "Foods and log changes"): such a total
  // is shown as "≥ 55" with "+ 1 not listed", never as a plain, complete number, and its "left" is not shown.
  function unknownOf(counts, key) {
    const n = Number(counts && counts[key]);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }
  function notListed(n) { return `+ ${n} not listed`; }
  function foodsNotListing(n, key) {
    const word = (NUT[key] ? NUT[key].label : key).toLowerCase();
    return `${n} ${n === 1 ? 'food does' : 'foods do'} not list ${word}`;
  }
  // "≥ 55" (and "at least 55" for screen readers) when values are missing, else "55".
  function atLeast(text, n) { return n > 0 ? `≥ ${text}` : text; }
  function atLeastWords(text, n) { return n > 0 ? `at least ${text}` : text; }
  function levelPill(level, text) {
    return h('span', { class: `pill level-${level}` }, ratingIcon(level, { decorative: true }), text || LEVEL_TEXT[level] || level);
  }
  function plusIcon() {
    return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { d: 'M12 5v14M5 12h14', stroke: 'currentColor', 'stroke-width': 2.2, 'stroke-linecap': 'round' }));
  }
  function dashedIcon() {
    return s('svg', { class: 'rating dashed', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('circle', { cx: 12, cy: 12, r: 9.5, fill: 'none', stroke: 'currentColor', 'stroke-width': 2, 'stroke-dasharray': '3.5 3' }));
  }
  function checkIcon() {
    return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { d: 'M5 12.5l4.5 4.5L19 7.5', fill: 'none', stroke: 'currentColor', 'stroke-width': 2.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
  }
  function closeIcon() {
    return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      s('path', { d: 'M6 6l12 12M18 6L6 18', stroke: 'currentColor', 'stroke-width': 2.2, 'stroke-linecap': 'round' }));
  }

  // ---------------------------------------------------------------------------
  // Toast
  // ---------------------------------------------------------------------------
  const toastEl = $('#toast');
  let toastTimer = null;
  function toast(message, type = '') {
    toastEl.textContent = message;
    toastEl.className = `toast show ${type}`.trim();
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), type === 'error' ? 6000 : 3200);
  }
  function toastError(err) {
    if (err && err.handled) return; // already explained to the person (e.g. KH.auth.onUnauthorized)
    console.error(err);
    toast(err && (err.detail || err.message) ? String(err.detail || err.message) : 'Something went wrong', 'error');
  }

  // ---------------------------------------------------------------------------
  // Auth hooks. The API client hands these answers to KH.auth (js/views/auth.js replaces the
  // stubs with the in-app screens):
  //   401                                  → onUnauthorized(err): the sign-in screen
  //   403 {reauth_required: true}          → reauth(err): asks for the password, resolves true
  //                                          once POST /api/auth/reauth succeeded; the request is
  //                                          then sent again, once
  //   403 {password_change_required: true} → onPasswordChangeRequired(err)
  //   503 {setup_required: true}           → onSetupRequired(err)
  // ---------------------------------------------------------------------------
  const auth = KH.auth || {};
  if (typeof auth.onUnauthorized !== 'function') {
    auth.onUnauthorized = function onUnauthorized() {
      toast('You are signed out. Reload the page to sign in again.', 'error');
    };
  }
  if (typeof auth.reauth !== 'function') auth.reauth = async () => false;
  if (typeof auth.onPasswordChangeRequired !== 'function') auth.onPasswordChangeRequired = () => toast('Choose a new password first.', 'error');
  if (typeof auth.onSetupRequired !== 'function') auth.onSetupRequired = () => toast('This server needs its first-run setup.', 'error');

  // ---------------------------------------------------------------------------
  // API layer
  // ---------------------------------------------------------------------------
  function errorDetail(data, res) {
    const d = data && data.detail;
    if (Array.isArray(d)) return d.map((x) => (x && x.msg ? `${(x.loc || []).slice(-1)[0] || ''}: ${x.msg}` : JSON.stringify(x))).join('; ');
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object') return JSON.stringify(d);
    return res ? `${res.status} ${res.statusText || 'error'}` : 'Request failed';
  }
  // One error path for the server and the demo API: hands auth answers to KH.auth and marks the
  // error `handled` when the person has already been told (no second toast).
  function apiError(status, data, res) {
    const err = new Error(errorDetail(data, res));
    err.status = status; err.detail = err.message; err.data = data;
    return err;
  }
  async function afterError(err, retry, opts) {
    const data = err.data || {};
    if (err.status === 401 && !opts.quiet401) {
      err.handled = true;
      try { KH.auth.onUnauthorized(err); } catch (e) { console.error(e); }
    } else if (err.status === 403 && data.reauth_required && !opts.retried) {
      let ok = false;
      try { ok = await KH.auth.reauth(err); } catch (e) { console.error(e); }
      if (ok) return retry({ ...opts, retried: true });
      err.handled = true; err.cancelled = true; // the person closed the password prompt
    } else if (err.status === 403 && data.password_change_required) {
      err.handled = true;
      try { KH.auth.onPasswordChangeRequired(err); } catch (e) { console.error(e); }
    } else if (err.status === 503 && data.setup_required) {
      err.handled = true;
      try { KH.auth.onSetupRequired(err); } catch (e) { console.error(e); }
    }
    throw err;
  }
  // Offline support (js/offline.js sets KH.net; note 02 R5). The client works without it:
  //   prepare(method, path, body) → body      adds a client_id to the writes the outbox can queue
  //   timeoutFor(method, path) → ms | 0         an AbortController timeout (a private IP can hang for minutes)
  //   offlineNow() → bool                       the demo API counts as unreachable while the browser is offline
  //   onNetworkError(method, path, body, err, opts) → answer | undefined   a saved copy, or the write queued
  //   onUnavailable(method, path, body, err, opts) → answer | undefined    the same for a 502/503/504 gateway answer
  //   afterResponse(method, path, body, data, opts) → data                 saves copies, merges waiting entries
  function networkError(timedOut = false) {
    const err = new Error(timedOut ? 'The server did not answer in time. Check your connection.' : 'Cannot reach the server. Check your connection.');
    err.status = 0; err.detail = err.message; err.offline = true; err.timedOut = timedOut;
    return err;
  }
  async function unreachable(method, path, body, opts, err) {
    const net = KH.net;
    if (net && typeof net.onNetworkError === 'function' && !opts.noQueue) {
      const answer = await net.onNetworkError(method, path, body, err, opts);
      if (answer !== undefined) return answer;
    }
    throw err;
  }
  async function answered(method, path, body, data, opts) {
    const net = KH.net;
    return net && typeof net.afterResponse === 'function' ? net.afterResponse(method, path, body, data, opts) : data;
  }
  // opts: { quiet401 } leaves a 401 to the caller (the sign-in screens), { retried } is internal,
  // { noQueue } is the outbox's own sync (never queued again, never answered from a saved copy).
  async function request(method, path, body, opts = {}) {
    const net = KH.net;
    if (net && typeof net.prepare === 'function' && !opts.noQueue) body = net.prepare(method, path, body);
    const retry = (o) => request(method, path, body, o);
    const mock = KH.mock && KH.mock.instance;
    if (mock) {
      if (net && typeof net.offlineNow === 'function' && net.offlineNow()) return unreachable(method, path, body, opts, networkError());
      let data;
      try { data = await mock.request(method, path, body); } catch (e) {
        if (!(KH.mock.ApiError && e instanceof KH.mock.ApiError)) throw e;
        return afterError(apiError(e.status, { detail: e.detail, ...(e.extra || {}) }, null), retry, opts);
      }
      return answered(method, path, body, data, opts);
    }
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    // Every write carries the app's own header: the server's CSRF check refuses cross-site
    // form posts, which cannot set it (note 07; plain-HTTP LANs send no Sec-Fetch-Site).
    if (method !== 'GET' && method !== 'HEAD') headers['X-Requested-With'] = 'kidney-health';
    const timeout = net && typeof net.timeoutFor === 'function' ? net.timeoutFor(method, path) : 0;
    const ctrl = timeout && typeof AbortController === 'function' ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), timeout) : null;
    let res;
    let text;
    try {
      res = await fetch(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: 'same-origin',
        signal: ctrl ? ctrl.signal : undefined,
      });
      // Read even an empty 204 body: an unread one is reported as net::ERR_ABORTED in DevTools.
      text = await res.text();
    } catch (e) {
      return unreachable(method, path, body, opts, networkError(!!(ctrl && ctrl.signal.aborted)));
    } finally {
      if (timer) clearTimeout(timer);
    }
    // A newer server under a cached shell (note 02 §5): let the PWA layer fetch the update and show its toast.
    if (KH.pwa && typeof KH.pwa.versionSeen === 'function') KH.pwa.versionSeen(res.headers.get('X-KDL-Version'));
    if (res.status === 204) return answered(method, path, body, null, opts);
    let data = null;
    let fromApp = true; // the app always answers JSON; a proxy in front of a stopped app answers HTML or nothing
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text.slice(0, 200) }; fromApp = false; }
    if (!res.ok) {
      // A gateway in front of a stopped app (502/503/504 that is not the app's own JSON) is "unreachable" too.
      if ([502, 503, 504].includes(res.status) && (!fromApp || !text) && net && typeof net.onUnavailable === 'function' && !opts.noQueue) {
        const answer = await net.onUnavailable(method, path, body, apiError(res.status, data, res), opts);
        if (answer !== undefined) return answer;
      }
      return afterError(apiError(res.status, data, res), retry, opts);
    }
    return answered(method, path, body, data, opts);
  }
  // A file download (GET) through the same error handling: the browser saves the body under the
  // server's Content-Disposition name. Used for the data export (re-auth may be asked first).
  async function download(path, fallbackName, opts = {}) {
    let res;
    try {
      res = await fetch(path, { method: 'GET', headers: { Accept: 'application/zip, application/json' }, credentials: 'same-origin' });
    } catch (e) {
      const err = new Error('Cannot reach the server. Check your connection.');
      err.status = 0; err.detail = err.message; throw err;
    }
    if (!res.ok) {
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text.slice(0, 200) }; }
      return afterError(apiError(res.status, data, res), (o) => download(path, fallbackName, o), opts);
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = /filename="?([^";]+)"?/i.exec(cd);
    const name = m ? m[1] : fallbackName;
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: name, class: 'sr-only' });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return { name, bytes: blob.size };
  }
  const api = {
    profile: () => request('GET', '/api/profile'),
    saveProfile: (b) => request('PUT', '/api/profile', b),
    suggested: () => request('GET', '/api/profile/suggested-targets'),
    // lab results and kidney function (ARCHITECTURE.md "M2 API: targets and labs")
    labs: (params = {}) => request('GET', '/api/labs?' + qs(params)),
    addLab: (b) => request('POST', '/api/labs', b),
    deleteLab: (id) => request('DELETE', `/api/labs/${id}`),
    kidneyFunction: () => request('GET', '/api/labs/kidney-function'),
    foods: (params) => request('GET', '/api/foods?' + qs(params)),
    categories: () => request('GET', '/api/foods/categories'),
    food: (id) => request('GET', `/api/foods/${id}`),
    deleteFood: (id) => request('DELETE', `/api/foods/${id}`),
    usdaSearch: (q) => request('GET', '/api/foods/usda/search?' + qs({ q })),
    usdaImport: (fdc_id) => request('POST', '/api/foods/usda/import', { fdc_id }),
    day: (date) => request('GET', '/api/log?' + qs({ date })),
    addEntry: (b) => request('POST', '/api/log', b),
    updateEntry: (id, b) => request('PUT', `/api/log/${id}`, b),
    deleteEntry: (id) => request('DELETE', `/api/log/${id}`),
    quick: (b) => request('POST', '/api/log/quick', b),
    range: (start, end) => request('GET', '/api/log/range?' + qs({ start, end })),
    summary: (start, end) => request('GET', '/api/log/summary?' + qs({ start, end })),
    markEaten: (b) => request('POST', '/api/log/mark-eaten', b),
    copyDay: (b) => request('POST', '/api/log/copy-day', b),
    exportUrl: (start, end) => '/api/log/export.csv?' + qs({ start, end }),
    meals: () => request('GET', '/api/meals'),
    createMeal: (b) => request('POST', '/api/meals', b),
    updateMeal: (id, b) => request('PUT', `/api/meals/${id}`, b),
    deleteMeal: (id) => request('DELETE', `/api/meals/${id}`),
    mealFromLog: (b) => request('POST', '/api/meals/from-log', b),
    applyMeal: (id, b) => request('POST', `/api/meals/${id}/apply`, b),
    shopping: (start, end) => request('GET', '/api/plan/shopping?' + qs({ start, end })),
    // accounts, settings, keys (ARCHITECTURE.md "M1 API")
    authStatus: () => request('GET', '/api/auth/status'),
    me: () => request('GET', '/api/me'),
    updateMe: (b) => request('PATCH', '/api/me', b),
    mySettings: () => request('GET', '/api/me/settings'),
    updateMySettings: (b) => request('PATCH', '/api/me/settings', b),
    myKeys: () => request('GET', '/api/me/keys'),
    setMyKey: (provider, b) => request('PUT', `/api/me/keys/${encodeURIComponent(provider)}`, b),
    deleteMyKey: (provider) => request('DELETE', `/api/me/keys/${encodeURIComponent(provider)}`),
  };

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const state = {
    view: 'today',
    date: todayStr(),
    profile: null,
    day: null,
    dayLoadedFor: null,
    categories: [],
    category: '',
    query: '',
    trendsDays: 14,
    trends: null,
    summary: null,
    addMealHint: null,
    addStatusHint: null,
    lastFocus: null,
    meals: null,          // saved meals cache (MealTemplate[])
    planStart: null,      // first day of the visible Plan week
    plan: null,           // { start, end, days: [...] }
    shopping: null,       // { start, end, items: [...] }
    targetsStale: null,   // { from, to } profiles: stage/dialysis changed since the targets were set
    authStatus: null,     // GET /api/auth/status (auth mode, registration, plain HTTP, instance name)
    me: null,             // the signed-in person (Me), null while signed out
  };

  // Shared caches. Profile: Today, Plan and Profile; saved meals: Add, Today and Plan.
  async function loadProfile(force = false) {
    if (state.profile && !force) return state.profile;
    state.profile = await api.profile();
    return state.profile;
  }
  async function loadMeals(force = false) {
    if (state.meals && !force) return state.meals;
    const res = await api.meals();
    state.meals = res.meals || [];
    return state.meals;
  }

  // ---------------------------------------------------------------------------
  // Theme
  // ---------------------------------------------------------------------------
  const root = document.documentElement;
  function storedTheme() { try { return localStorage.getItem(THEME_KEY) || 'auto'; } catch (e) { return 'auto'; } }
  // A page that embeds this one (the preview's host) may set data-theme itself; with no stored
  // choice of ours, "Match device" keeps that value instead of removing it.
  const HOST_THEME = (() => {
    const t = root.getAttribute('data-theme');
    return storedTheme() === 'auto' && (t === 'light' || t === 'dark') ? t : null;
  })();
  function effectiveTheme() {
    const t = root.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function syncThemeControls(mode) {
    const eff = effectiveTheme();
    $('#theme-toggle').setAttribute('aria-label', eff === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    const sel = $('#set-theme'); if (sel && mode) sel.value = mode;
    $$('meta[name="theme-color"]').forEach((mtag) => mtag.setAttribute('content', eff === 'dark' ? '#111417' : '#f4f5f7'));
  }
  function applyTheme(mode) {
    if (mode === 'light' || mode === 'dark') root.setAttribute('data-theme', mode);
    else if (HOST_THEME) root.setAttribute('data-theme', HOST_THEME);
    else root.removeAttribute('data-theme');
    try { if (mode === 'auto') localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, mode); } catch (e) { /* storage unavailable */ }
    syncThemeControls(mode);
  }
  $('#theme-toggle').addEventListener('click', () => applyTheme(effectiveTheme() === 'dark' ? 'light' : 'dark'));
  $('#set-theme').addEventListener('change', (e) => applyTheme(e.target.value));
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onScheme = () => syncThemeControls(null);
    if (mq.addEventListener) mq.addEventListener('change', onScheme); else if (mq.addListener) mq.addListener(onScheme);
  }
  // Keep the toggle's label right when the host switches data-theme while the page is open.
  if (window.MutationObserver) new MutationObserver(() => syncThemeControls(null)).observe(root, { attributes: true, attributeFilter: ['data-theme'] });

  // ---------------------------------------------------------------------------
  // Tabs / views. Each js/views/<name>.js registers what showing it loads.
  // ---------------------------------------------------------------------------
  // Tabbed views, then views without a tab (Settings: the header gear and Profile open it; Labs:
  // Profile's "Lab results" button).
  const TAB_VIEWS = ['today', 'add', 'plan', 'trends', 'profile'];
  const VIEWS = [...TAB_VIEWS, 'settings', 'labs'];
  const viewLoaders = {};
  function registerView(name, onShow) { viewLoaders[name] = onShow; }
  function showView(name, { focusTab = false } = {}) {
    if (!VIEWS.includes(name)) name = 'today';
    state.view = name;
    const authView = $('#view-auth');
    if (authView) authView.hidden = true;
    for (const v of VIEWS) {
      const panel = $(`#view-${v}`);
      const tab = $(`#tab-${v}`);
      const active = v === name;
      panel.hidden = !active;
      if (tab) {
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        // With Settings open no tab is selected; the first tab stays reachable with Tab.
        tab.tabIndex = active || (!TAB_VIEWS.includes(name) && v === TAB_VIEWS[0]) ? 0 : -1;
      }
    }
    const gear = $('#settings-open');
    if (gear) { if (name === 'settings') gear.setAttribute('aria-current', 'page'); else gear.removeAttribute('aria-current'); }
    if (focusTab && $(`#tab-${name}`)) $(`#tab-${name}`).focus();
    try { if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`); } catch (e) { /* sandboxed frame: the view still switches */ }
    window.scrollTo({ top: 0 });
    const load = viewLoaders[name];
    if (load) load();
  }
  // Open a given date in the Today view (used by the Plan grid and the week strip).
  function openDay(date) {
    state.date = date;
    showView('today');
  }
  $$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => showView(tab.dataset.view));
    tab.addEventListener('keydown', (e) => {
      const i = TAB_VIEWS.indexOf(tab.dataset.view);
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const next = TAB_VIEWS[(i + (e.key === 'ArrowRight' ? 1 : TAB_VIEWS.length - 1)) % TAB_VIEWS.length];
        showView(next, { focusTab: true });
      } else if (e.key === 'Home') { e.preventDefault(); showView(TAB_VIEWS[0], { focusTab: true }); }
      else if (e.key === 'End') { e.preventDefault(); showView(TAB_VIEWS[TAB_VIEWS.length - 1], { focusTab: true }); }
    });
  });
  window.addEventListener('hashchange', () => {
    const name = location.hash.replace('#', '');
    // Only while the app is showing (not on a sign-in screen): #/... routes belong to js/views/auth.js.
    if (VIEWS.includes(name) && name !== state.view && state.me && state.view !== 'auth') showView(name);
  });

  // ---------------------------------------------------------------------------
  // Sheets (dialogs)
  // ---------------------------------------------------------------------------
  // Forms run their handler from the submit button's click (Enter in a field clicks the default
  // button too): a sandboxed frame without allow-forms never fires "submit", so the app does not
  // depend on it. The handler's preventDefault() stops the native submission either way.
  function onSubmit(form, handler) {
    form.addEventListener('submit', handler);
    $$('button[type="submit"]', form).forEach((b) => b.addEventListener('click', handler));
  }

  // ---------------------------------------------------------------------------
  // ---------------------------------------------------------------------------
  // Field errors (WCAG 3.3.1): the server's "<field>: <message>" parts shown under the field they
  // name, linked with aria-describedby and marked aria-invalid, so the reason is in view when the
  // field gets focus. Used by the Profile and Labs forms.
  // ---------------------------------------------------------------------------
  // "birth_month: must be …; sex: Input should be …" → [{field: 'birth_month', message: 'Must be …'}, …];
  // a message without a field prefix comes back with field null. Splits only before "<field>: ".
  function splitFieldErrors(detail) {
    const parts = String(detail || '').split(/; (?=[a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*: )/);
    return parts.filter(Boolean).map((part) => {
      const m = /^([a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*): (.*)$/s.exec(part);
      const message = m ? m[2] : part;
      return { field: m ? m[1] : null, message: message.charAt(0).toUpperCase() + message.slice(1) };
    });
  }
  function clearFieldErrors(root) {
    $$('.field-error', root).forEach((el) => {
      const input = document.getElementById(el.dataset.for || '');
      if (input) {
        const ids = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter((x) => x && x !== el.id);
        if (ids.length) input.setAttribute('aria-describedby', ids.join(' ')); else input.removeAttribute('aria-describedby');
        input.removeAttribute('aria-invalid');
      }
      el.remove();
    });
  }
  // anchor: where the message goes (default: right after the input; a radio group passes its fieldset).
  function fieldError(input, message, anchor = null) {
    if (!input || !message) return;
    const id = `${input.id}-error`;
    const old = document.getElementById(id);
    if (old) old.remove();
    const el = h('p', { class: 'field-error', id, 'data-for': input.id }, message);
    (anchor || input.closest('.range-inputs') || input).after(el);
    const ids = (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
    if (!ids.includes(id)) input.setAttribute('aria-describedby', [...ids, id].join(' '));
    input.setAttribute('aria-invalid', 'true');
  }

  // In-page confirmation. window.confirm() is never shown in a home-screen web app or a
  // sandboxed frame, so destructive actions ask inside the page: the confirm row takes the
  // place of `host` (a sheet footer or an actions row), names what will be deleted, and gets
  // focus on its confirm button; Cancel or Escape puts the host back and refocuses the trigger.
  // ---------------------------------------------------------------------------
  let confirmSeq = 0;
  function dismissConfirm(host, refocus = false) {
    if (host && host._confirmRow) host._confirmRow._close(refocus);
  }
  function inlineConfirm(host, trigger, { message, confirmText = 'Delete', onConfirm }) {
    dismissConfirm(host);
    const msgId = `confirm-msg-${++confirmSeq}`;
    const cancel = h('button', { class: 'btn secondary', type: 'button' }, 'Cancel');
    const ok = h('button', { class: 'btn danger-solid', type: 'button' }, confirmText);
    const row = h('div', { class: `confirm-row${host.classList.contains('sheet-foot') ? ' sheet-foot' : ''}`, role: 'group', 'aria-labelledby': msgId },
      h('p', { class: 'confirm-msg', id: msgId }, message),
      h('div', { class: 'confirm-actions' }, cancel, ok));
    const close = (refocus) => {
      if (host._confirmRow !== row) return;
      host._confirmRow = null;
      row.remove();
      host.hidden = false;
      if (refocus && trigger && document.contains(trigger) && !trigger.hidden) { try { trigger.focus(); } catch (e) { /* ignore */ } }
    };
    row._close = close;
    host._confirmRow = row;
    host.hidden = true;
    host.after(row);
    cancel.addEventListener('click', () => close(true));
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
    });
    ok.addEventListener('click', async () => {
      ok.disabled = true; cancel.disabled = true;
      let done = false;
      try { done = (await onConfirm()) !== false; } catch (err) { toastError(err); }
      if (done) close(false);
      else if (host._confirmRow === row) { ok.disabled = false; cancel.disabled = false; ok.focus(); }
    });
    setTimeout(() => { if (document.contains(ok)) ok.focus(); }, 0);
    return row;
  }

  function setupDialog(dlg) {
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
    $$('[data-close]', dlg).forEach((b) => b.addEventListener('click', () => dlg.close()));
    dlg.addEventListener('close', () => {
      $$('.sheet-foot', dlg).forEach((foot) => dismissConfirm(foot));
      const f = dlg._returnFocus;
      dlg._returnFocus = null;
      if (f && document.contains(f)) { try { f.focus(); } catch (e) { /* ignore */ } }
    });
  }
  function openDialog(dlg, trigger, focusEl) {
    dlg._returnFocus = trigger || document.activeElement;
    if (typeof dlg.showModal === 'function') { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute('open', '');
    const target = focusEl || $('input, select, button:not([data-close])', dlg);
    if (target) setTimeout(() => target.focus({ preventScroll: true }), 30);
    $('.sheet-body', dlg).scrollTop = 0;
  }
  function renderWarnings(container, warnings, { emptyText } = {}) {
    clear(container);
    if (!warnings.length) {
      container.append(h('div', { class: 'warning level-ok' }, ratingIcon('ok', { label: 'No warnings' }),
        h('div', {}, h('span', { class: 'w-level' }, 'No warnings. '), emptyText || 'Nothing in this amount crosses a per-serving threshold.')));
      return;
    }
    for (const w of warnings) {
      const lvl = w.level === 'high' ? 'over' : 'caution';
      const more = KH.learn ? KH.learn.forWarning(w) : null; // the handbook page (js/learn.js), when there is one
      container.append(h('div', { class: `warning level-${lvl}` }, ratingIcon(lvl, { label: w.level === 'high' ? 'High' : 'Moderate' }),
        h('div', {}, h('span', { class: 'w-level' }, w.level === 'high' ? 'High. ' : 'Moderate. '), w.message, more ? [' ', more] : null)));
    }
  }

  // Segmented radio groups (meal, eaten / planned) shared by the sheets.
  function selectedMeal(groupEl) { const r = $('input:checked', groupEl); return r ? r.value : defaultMealForNow(); }
  function setMeal(groupEl, meal) { const r = $(`input[value="${meal}"]`, groupEl); if (r) r.checked = true; }
  function selectedStatus(groupEl) { const r = $('input:checked', groupEl); return r && r.value === 'planned' ? 'planned' : 'eaten'; }
  function setStatus(groupEl, status) { const r = $(`input[value="${status === 'planned' ? 'planned' : 'eaten'}"]`, groupEl); if (r) r.checked = true; }

  function isPlanned(e) { return e.status === 'planned'; }

  // Unrounded, like the server's entry snapshot (food × servings); the display rounds and the
  // warnings evaluator rounds exactly as app/nutrients.py does.
  function scaledNutrients(perServing, servings) {
    const out = {};
    for (const n of KH.rules.NUTRIENTS) {
      const v = perServing ? perServing[n.key] : null;
      out[n.key] = v == null ? null : Number(v) * servings;
    }
    return out;
  }

  // Where would the day's totals land after adding `scaled` to `meal`? For a planned entry the base is the
  // projected total (eaten + planned); for an eaten entry it is the eaten total. `editing` is subtracted first.
  function impactOn(day, scaled, meal, { editing = null, status = 'eaten' } = {}) {
    const out = [];
    const wf = (state.profile && state.profile.warn_fraction) || 0.8;
    const planned = status === 'planned' && day.projected_status;
    const statusMap = planned ? day.projected_status : day.status || {};
    const suffix = planned ? ' with everything planned' : '';
    const editVal = (key) => {
      if (!editing || !editing.nutrients) return 0;
      if (planned || !isPlanned(editing)) return editing.nutrients[key] || 0; // projected totals include every entry; eaten totals only eaten ones
      return 0;
    };
    for (const [key, st] of Object.entries(statusMap)) {
      if (!NUT[key] || !st.target) continue;
      const base = (st.value || 0) - editVal(key);
      const projected = base + (scaled[key] || 0);
      const fraction = projected / st.target;
      if (fraction < wf) continue;
      // An "about" target is over only above the person's tolerance (nutrients.over_at, v0.3.1).
      const level = fraction > KH.rules.overAt(key, st.min, st.target, (state.profile && state.profile.about_tolerance_pct) || 0) ? 'over' : 'caution';
      const contribution = (scaled[key] || 0) / st.target;
      // Only worth saying when this food changes the level or adds a meaningful share (>= 5 %) of the target.
      if (st.level === level && contribution < 0.05) continue;
      if (!(scaled[key] > 0)) continue;
      // The day's total misses foods that do not list this value (the entry being edited counts only once).
      const editingUnknown = editing && editing.nutrients && editing.nutrients[key] == null && (planned || !isPlanned(editing)) ? 1 : 0;
      const unknown = Math.max(0, Number(st.unknown || 0) - editingUnknown);
      out.push({ level, message: `${NUT[key].label} would reach ${atLeastWords(fmtNum(projected, key), unknown)} / ${fmtNum(st.target, key)} ${NUT[key].unit} (${pct(fraction)} %)${suffix}`
        + (unknown ? `; ${foodsNotListing(unknown, key)}` : '') });
    }
    const snackGoal = meal === 'snack' && day.targets && typeof day.targets.carbs_per_snack_g === 'number' ? day.targets.carbs_per_snack_g : null;
    const perMeal = snackGoal != null ? snackGoal : day.targets && typeof day.targets.carbs_per_meal_g === 'number' ? day.targets.carbs_per_meal_g : null;
    if (perMeal && day.meals && day.meals[meal]) {
      let mealBase = day.meals[meal].carbs_g || 0;
      if (planned && day.planned_meals && day.planned_meals[meal]) mealBase += day.planned_meals[meal].carbs_g || 0;
      // Entries that treated a low are left out of the meal's carbohydrate (nutrients.meal_carb_alerts, v0.3.1);
      // an edited entry is taken out once, either way.
      const isHypo = (e) => !!e && e.purpose === 'hypo';
      const hypoBase = (day.entries || []).filter((e) => e.meal === meal && isHypo(e) && (planned || !isPlanned(e)))
        .reduce((a, e) => a + ((e.nutrients && e.nutrients.carbs_g) || 0), 0);
      const base = mealBase - hypoBase - (editing && editing.meal === meal && !isHypo(editing) ? editVal('carbs_g') : 0);
      const projected = base + (scaled.carbs_g || 0);
      const fraction = projected / perMeal;
      const tol = Number(day.carb_tolerance_g || 0);
      if (fraction >= wf && scaled.carbs_g > 0) {
        const over = projected > perMeal + tol;
        const within = !over && projected > perMeal ? `, within your ${fmtNum(tol, 'carbs_g')} g tolerance` : '';
        out.push({ level: over ? 'over' : 'caution', message: `${MEAL_LABEL[meal]} carbohydrate would be ${fmtNum(projected, 'carbs_g')} / ${perMeal} g (${pct(fraction)} %${within})${suffix}` });
      }
    }
    return out;
  }

  Object.assign(KH, {
    flags: { PREVIEW, MOCK, MOCK_HD },
    keys: { THEME_KEY, SHOP_KEY },
    ui: {
      KEY_NUMBERS, ROW_NUMBERS, STATUS_ORDER, TREND_ORDER, PLAN_CHIPS, STRIP_KEYS, INTERDIALYTIC_KEYS, WEEKDAYS, WEEKDAYS_LONG,
      RATING_LABEL, LEVEL_TEXT, ABOUT_LEVEL_TEXT, LEVEL_RATING, isAboutTarget, levelTextFor,
      ratingIcon, levelPill, plusIcon, dashedIcon, checkIcon, closeIcon, unknownOf, notListed, foodsNotListing, atLeast, atLeastWords,
      renderWarnings, selectedMeal, setMeal, selectedStatus, setStatus, isPlanned, scaledNutrients, impactOn,
    },
    util: {
      localISO, todayStr, parseDate, addDays, fmtDateLong, fmtDateShort, fmtMonthDay, fmtRange, weekdayMon, weekStartOf,
      daysBetween, defaultStatusFor, fmtChange, defaultMealForNow, debounce, qs, numOrNull,
    },
    $, $$, h, s, clear,
    api, request, download, auth, state, toast, toastError, loadProfile, loadMeals,
    theme: { stored: storedTheme, effective: effectiveTheme, apply: applyTheme, sync: syncThemeControls },
    router: { VIEWS, TAB_VIEWS, register: registerView, show: showView, openDay },
    sheets: { setup: setupDialog, open: openDialog, onSubmit },
    confirm: { inline: inlineConfirm, dismiss: dismissConfirm },
    forms: { splitFieldErrors, fieldError, clearFieldErrors },
    views: KH.views || {},
  });
})();
