/* Kidney Diet Log — barcodes and label photos (KH.scan; note 03 R7, R8, R11, §9 B4; note 02 R7).

   * The Scan sheet (#sheet-scan, from Add → "Scan a barcode"): three ways to the same POST /api/foods/barcode.
     1. Camera: live, only in a secure context (HTTPS, or http://localhost) with getUserMedia; plain HTTP says why.
        With the person's "Start the camera when I open Scan" (food.scan_prefer_camera, on by default; note 03 R10)
        it starts as the sheet opens, unless they already chose a photo or typed digits.
        Two identical reads are needed, about 8 detections a second, every track stops when the sheet closes, the
        page is hidden or the view changes, and a camera that shows no frame within 4 s (WebKit bug 282327 in iOS
        home-screen apps) is closed with a pointer to the photo button.
     2. Photo of a barcode: decoded on this device (createImageBitmap, or <img> + canvas); never uploaded, so it
        works over plain HTTP too.
     3. Typed digits (USB and Bluetooth scanners type here too): the check digit and the GS1 ranges that are never
        looked up are checked on the device first (js/engine/gtin.js), with the server's own words.
   * Decoder: the browser's BarcodeDetector when it reads EAN-13 (Chrome on Android, macOS, ChromeOS); otherwise the
     vendored ponyfill (window.BarcodeDetectionAPI, a static deferred script in index.html) pointed at
     /vendor/zxing-wasm-3.1.3/, whose 1 MB WebAssembly reader is fetched on first use only (never from a CDN).
   * Result → review → log: a found product opens the existing entry sheet (warnings, amount, eaten/planned); the
     entry sheet shows where the data came from (renderProvenance: attribution with a link only to an https URL,
     quality notes, the additives behind a flag, the ingredient list). Not found → "Enter from the label" (Quick add
     with the barcode and the product name) and "Add it to Open Food Facts". Open Food Facts needs the person's
     consent (food.off_consent): the sheet asks, says what is sent, and looks up again.
   * Quick add's label photo (R8): "Use a photo of the label" shows the photo beside the form (zoom 1×/2×/3×; the
     object URL is revoked when the photo is removed or the sheet closes; nothing is uploaded). When the server
     offers AI to this person, "Read the label for me" redraws the photo on the device (KH.ai.prepareJpeg: JPEG,
     long edge ≤ 1600 px, no EXIF), asks consent through KH.ai.withConsent, and fills the fields, each marked
     "from photo" or "estimated" until the person edits it. Nothing is saved without "Log it".

   Text from products (names, ingredient lists, quality notes) is set with textContent only. Exposes KH.scan. */
(() => {
  'use strict';
  const KH = window.KH;
  const { h, $, $$, clear, request, state, toast, toastError, sheets, ui, rules } = KH;
  const { MOCK, PREVIEW } = KH.flags;
  const { NUT } = rules;

  const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];
  const WASM_DIR = '/vendor/zxing-wasm-3.1.3/';
  const DETECT_EVERY_MS = 125; // about 8 detections a second
  const NO_FRAME_MS = 4000; // WebKit 282327: the camera starts and shows nothing
  const READS_NEEDED = 2;
  const PONYFILL_WAIT_MS = 5000;
  const PHOTO_EDGE = 1600;

  const dlg = $('#sheet-scan');
  const statusEl = $('#scan-status');
  const resultEl = $('#scan-result');
  const codeInput = $('#scan-code');
  const codeRow = codeInput.closest('.scan-type-row'); // field errors go under the row, not between the input and its button
  const video = $('#scan-video');
  sheets.setup(dlg);
  let trigger = null;
  let seq = 0;
  const uid = (p) => `${p}-${++seq}`;

  // The sheet's status line (role="status"): shown for progress, read out but not shown again when a panel
  // below says the same in full.
  function say(text, { visible = true } = {}) {
    statusEl.textContent = text || '';
    statusEl.classList.toggle('sr-only', !visible);
  }
  // A link to another site, in a new tab. The preview runs inside a sandboxed frame that may not open
  // windows, so there the address is shown as text instead of a link that would do nothing.
  function newTab(href, text) {
    if (PREVIEW) return h('span', { class: 'ext-text' }, text, ` (${String(href).replace(/^https:\/\//, '').replace(/\/$/, '')})`);
    return h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, text, h('span', { class: 'sr-only' }, ' (opens in a new tab)'));
  }
  function note(kind, ...children) { return h('div', { class: `settings-note ${kind}`, role: 'note' }, ...children); }
  function actionButton(label, cls, fn, attrs = {}) {
    const btn = h('button', { class: `btn ${cls}`, type: 'button', ...attrs }, label);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      try { await fn(btn); } catch (err) { if (!err.handled && !err.cancelled) toastError(err); } finally { if (document.contains(btn)) btn.disabled = false; }
    });
    return btn;
  }

  // ---------------------------------------------------------------------------
  // Decoder selection
  // ---------------------------------------------------------------------------
  let detectorPromise = null;
  let decoderKind = null; // 'native' | 'wasm' | 'none'

  async function nativeDetector() {
    const BD = window.BarcodeDetector;
    if (typeof BD !== 'function' || typeof BD.getSupportedFormats !== 'function') return null;
    let supported = [];
    try { supported = await BD.getSupportedFormats(); } catch (e) { return null; }
    if (!Array.isArray(supported) || !supported.includes('ean_13')) return null;
    return new BD({ formats: FORMATS.filter((f) => supported.includes(f)) });
  }
  // The deferred ponyfill script runs after the page is parsed: wait for it briefly when asked very early.
  function ponyfill() {
    if (window.BarcodeDetectionAPI) return Promise.resolve(window.BarcodeDetectionAPI);
    if (PREVIEW || document.readyState === 'complete') return Promise.resolve(null); // the preview leaves it out
    return new Promise((resolve) => {
      const done = () => resolve(window.BarcodeDetectionAPI || null);
      window.addEventListener('load', done, { once: true });
      setTimeout(done, PONYFILL_WAIT_MS);
    });
  }
  async function wasmDetector() {
    const API = await ponyfill();
    if (!API || typeof API.prepareZXingModule !== 'function') return null;
    // Point the reader at the vendored file before anything is constructed (its default is a CDN).
    const locateFile = (path, prefix) => (path.endsWith('.wasm') ? WASM_DIR + path : prefix + path);
    try {
      await API.prepareZXingModule({ overrides: { locateFile }, fireImmediately: true });
    } catch (e) {
      const err = new Error('The barcode reader could not be loaded. Connect to your server once (after that it works offline), or type the digits.');
      err.cause = e;
      throw err;
    }
    return new API.BarcodeDetector({ formats: FORMATS });
  }
  function getDetector() {
    if (!detectorPromise) {
      detectorPromise = (async () => {
        const native = await nativeDetector();
        if (native) { decoderKind = 'native'; return native; }
        const wasm = await wasmDetector();
        decoderKind = wasm ? 'wasm' : 'none';
        return wasm;
      })();
      detectorPromise.catch(() => { detectorPromise = null; }); // a failed load can be tried again later
    }
    return detectorPromise;
  }
  // The first usable code of a detect() answer: {code, format}.
  function pickCode(found) {
    for (const b of found || []) {
      const raw = String((b && b.rawValue) || '').trim();
      if (!/^\d{8,14}$/.test(raw)) continue;
      return { code: raw, format: FORMATS.includes(b.format) ? b.format : 'unknown' };
    }
    return null;
  }

  // ---------------------------------------------------------------------------
  // Photo of a barcode (decoded here, never uploaded)
  // ---------------------------------------------------------------------------
  async function bitmapOf(file) {
    try {
      return await createImageBitmap(file, { imageOrientation: 'from-image' });
    } catch (e) {
      return new Promise((resolve, reject) => {
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('This photo could not be opened. Try a JPEG or PNG.')); };
        img.src = url;
      });
    }
  }
  function scaledCanvas(source, edge) {
    const w0 = source.width || source.naturalWidth;
    const h0 = source.height || source.naturalHeight;
    const scale = Math.min(1, edge / Math.max(w0, h0));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(w0 * scale));
    canvas.height = Math.max(1, Math.round(h0 * scale));
    canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
  }
  // {code, format} from a photo, or null when no barcode was found. Throws when no decoder is available.
  async function decodeFile(file) {
    const detector = await getDetector();
    if (!detector) throw new Error(noDecoderText());
    const source = await bitmapOf(file);
    try {
      let hit = pickCode(await detector.detect(source));
      // A large, noisy phone photo can read better a little smaller.
      if (!hit && Math.max(source.width || source.naturalWidth, source.height || source.naturalHeight) > PHOTO_EDGE) {
        hit = pickCode(await detector.detect(scaledCanvas(source, PHOTO_EDGE)));
      }
      return hit;
    } finally {
      if (source.close) source.close();
    }
  }
  function noDecoderText() {
    return PREVIEW ? 'Reading barcodes from a photo needs the installed app (this preview has no barcode reader). Type the digits instead.'
      : 'This browser cannot read barcodes from photos. Type the digits instead.';
  }

  // ---------------------------------------------------------------------------
  // Live camera
  // ---------------------------------------------------------------------------
  let live = null; // { stream, timer, watchdog, last, count, busy }
  let opening = 0; // the sheet's current opening; an automatic start belongs to one
  let chose = false; // the person picked a way themselves (camera, photo or typed digits) since the sheet opened
  function liveSupported() {
    return !PREVIEW && window.isSecureContext === true && !!(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === 'function');
  }
  function liveNoteText() {
    if (PREVIEW) return 'The camera works in the installed app (this preview runs inside another page). Type the digits instead.';
    if (window.isSecureContext !== true) {
      return 'Live scanning needs HTTPS (or this app opened on the same computer at http://localhost), because browsers only allow the '
        + 'camera on secure pages. Your admin can set HTTPS up with docs/https.md. A photo of the barcode works now.';
    }
    return 'This browser does not offer the camera to web pages. Take a photo of the barcode instead.';
  }
  function cameraError(e) {
    const name = e && e.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') return 'The camera was not allowed. Allow it for this site in the browser settings, or take a photo of the barcode instead.';
    if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No camera was found. Take a photo of the barcode, or type the digits.';
    if (name === 'NotReadableError' || name === 'AbortError') return 'The camera is busy (another app may be using it). Close that app, or take a photo of the barcode instead.';
    return 'The camera could not start. Take a photo of the barcode, or type the digits.';
  }
  function showCameraControls(running) {
    $('#scan-viewfinder').hidden = !running;
    $('#scan-camera').hidden = running;
    $('#scan-camera-stop').hidden = !running;
  }
  function stopCamera(message = null) {
    if (live) {
      clearTimeout(live.timer);
      clearTimeout(live.watchdog);
      for (const track of live.stream ? live.stream.getTracks() : []) { try { track.stop(); } catch (e) { /* already stopped */ } }
      live = null;
    }
    try { video.pause(); } catch (e) { /* not playing */ }
    video.srcObject = null;
    showCameraControls(false);
    if (message) say(message);
  }
  // `auto`: started because the sheet opened (food.scan_prefer_camera); it gives way to anything the person does.
  async function startCamera({ auto = null } = {}) {
    if (live) return;
    const gaveWay = () => auto !== null && (auto !== opening || chose || !dlg.open);
    if (gaveWay()) return;
    clear(resultEl);
    let detector;
    try { detector = await getDetector(); } catch (e) { if (!gaveWay()) say(e.message); return; }
    if (!detector) { if (!gaveWay()) say(noDecoderText()); return; }
    if (gaveWay()) return;
    say('Starting the camera…');
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false,
      });
    } catch (e) {
      if (gaveWay()) return;
      say(cameraError(e) + (auto !== null ? ' To stop the camera starting by itself, switch off "Start the camera when I open Scan" in Settings → Food data.' : ''));
      $('#scan-file').focus();
      return;
    }
    if (!dlg.open || gaveWay() || live) { for (const t of stream.getTracks()) t.stop(); return; } // closed or overtaken meanwhile
    live = { stream, timer: null, watchdog: null, last: null, count: 0, frames: 0 };
    const session = live;
    video.srcObject = stream;
    const hadFocus = document.activeElement === $('#scan-camera');
    showCameraControls(true);
    if (hadFocus) $('#scan-camera-stop').focus(); // the button that had focus is hidden now
    if (typeof video.requestVideoFrameCallback === 'function') {
      const onFrame = () => { if (live === session) { session.frames += 1; if (session.frames < 3) video.requestVideoFrameCallback(onFrame); } };
      video.requestVideoFrameCallback(onFrame);
    }
    // Not awaited: a camera that never delivers a frame (WebKit 282327) leaves play() pending forever.
    const playing = video.play();
    if (playing && typeof playing.catch === 'function') playing.catch(() => { /* autoplay rules: muted + playsinline normally allow it */ });
    say('Hold the barcode inside the frame, about a hand’s width from the camera.');
    // No frame within 4 s: close the camera and offer the photo button instead.
    session.watchdog = setTimeout(() => {
      if (live !== session) return;
      const noFrame = typeof video.requestVideoFrameCallback === 'function' ? session.frames === 0 : !(video.videoWidth > 0 && video.currentTime > 0);
      if (noFrame) {
        stopCamera('The camera did not show a picture (this happens in some iPhone home-screen apps). Take a photo of the barcode instead.');
        $('#scan-file').focus();
      }
    }, NO_FRAME_MS);
    const tick = async () => {
      if (live !== session) return;
      let hit = null;
      if (video.readyState >= 2 && video.videoWidth > 0) {
        try { hit = pickCode(await detector.detect(video)); } catch (e) { hit = null; }
      }
      if (live !== session) return;
      if (hit) {
        if (session.last && session.last.code === hit.code) session.count += 1; else { session.last = hit; session.count = 1; }
        if (session.count >= READS_NEEDED) {
          stopCamera();
          say(`Read ${hit.code}. Looking it up…`);
          await lookup(hit.code, hit.format);
          return;
        }
      }
      session.timer = setTimeout(tick, DETECT_EVERY_MS);
    };
    session.timer = setTimeout(tick, DETECT_EVERY_MS);
  }
  $('#scan-camera').addEventListener('click', () => { chose = true; startCamera().catch((e) => { stopCamera(); toastError(e); }); });
  $('#scan-camera-stop').addEventListener('click', () => { stopCamera('Camera stopped.'); $('#scan-camera').focus(); });
  dlg.addEventListener('close', () => stopCamera());
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden' && live) stopCamera('The camera stopped while the app was in the background. Tap “Use the camera” to start it again.'); });
  window.addEventListener('pagehide', () => stopCamera());
  window.addEventListener('hashchange', () => { if (live) stopCamera(); });

  // ---------------------------------------------------------------------------
  // Photo input and typed digits
  // ---------------------------------------------------------------------------
  $('#scan-file').addEventListener('click', () => { chose = true; });
  $('#scan-file').addEventListener('change', async (e) => {
    chose = true;
    const input = e.currentTarget;
    const file = input.files && input.files[0];
    if (!file) return;
    stopCamera();
    clear(resultEl);
    say('Reading the barcode in your photo…');
    let hit;
    try { hit = await decodeFile(file); } catch (err) { say(err.message); return; } finally { input.value = ''; }
    if (!hit) {
      say('No barcode was found in this photo. Try again closer, in focus and with the whole barcode in the picture, or type the digits.');
      return;
    }
    say(`Read ${hit.code}. Looking it up…`);
    await lookup(hit.code, hit.format);
  });

  function typedSubmit(e) {
    e.preventDefault();
    chose = true;
    KH.forms.clearFieldErrors($('#scan-form'));
    const raw = codeInput.value.trim();
    if (!raw) { KH.forms.fieldError(codeInput, 'Enter the barcode number.', codeRow); codeInput.focus(); return; }
    let gtin14;
    try { gtin14 = KH.gtin.normalize(raw, 'unknown'); } catch (err) {
      if (!(err instanceof KH.gtin.GtinError)) throw err;
      KH.forms.fieldError(codeInput, err.message, codeRow);
      codeInput.focus();
      return;
    }
    const kind = KH.gtin.classify(gtin14);
    if (kind !== 'retail') { KH.forms.fieldError(codeInput, KH.gtin.CLASS_MESSAGES[kind], codeRow); codeInput.focus(); return; }
    stopCamera();
    say(`Looking up ${raw}…`);
    lookup(raw, 'unknown', { typed: true }).catch(toastError);
  }
  sheets.onSubmit($('#scan-form'), typedSubmit);
  codeInput.addEventListener('input', () => { chose = true; KH.forms.clearFieldErrors($('#scan-form')); });

  // ---------------------------------------------------------------------------
  // Lookup and its answers
  // ---------------------------------------------------------------------------
  let lastCode = null;
  async function lookup(code, format, { typed = false, refresh = false } = {}) {
    lastCode = { code, format, typed };
    clear(resultEl);
    resultEl.setAttribute('aria-busy', 'true');
    let res;
    try {
      res = await request('POST', '/api/foods/barcode', { code, format, refresh });
    } catch (err) {
      resultEl.removeAttribute('aria-busy');
      if (err.handled || err.cancelled) { say(''); return null; }
      showProblem(err, code);
      return null;
    }
    resultEl.removeAttribute('aria-busy');
    found(res);
    return res;
  }

  function found(res) {
    const food = res.food;
    say(`Found ${food.name}.`);
    state.dayLoadedFor = null; // a new linked food may now show in search
    const back = trigger && document.contains(trigger) ? trigger : $('#btn-scan');
    dlg.close();
    KH.views.add.openEntrySheet('add', { food, trigger: back });
  }

  // The scanned or typed digits, for "Enter from the label" (the server stores them as a GTIN-14).
  function enterFromLabel(gtin, name, cls = 'primary') {
    const digits = lastCode ? lastCode.code : gtin || '';
    return h('button', { class: `btn ${cls}`, type: 'button', onclick: () => {
      dlg.close();
      KH.views.add.openQuick({ name: name || '', gtin: digits, trigger: $('#btn-scan'), photoFirst: true });
    } }, 'Enter from the label');
  }
  function tryAgain(label = 'Try again') {
    return actionButton(label, 'secondary', async () => { if (lastCode) await lookup(lastCode.code, lastCode.format, { typed: lastCode.typed }); });
  }
  function panel(title, ...children) {
    statusEl.classList.add('sr-only');
    const id = uid('scan-panel');
    const box = h('section', { class: 'scan-panel', 'aria-labelledby': id }, h('h3', { class: 'scan-h', id }, title), ...children);
    clear(resultEl).append(box);
    const first = $('button, a', box);
    if (first) setTimeout(() => { if (document.contains(first)) first.focus(); }, 0);
    return box;
  }

  function showProblem(err, code) {
    const data = err.data || {};
    const detail = err.detail || err.message || 'The lookup failed.';
    if (err.status === 0) {
      say('Barcode lookups need a connection to your server.');
      panel('No connection', h('p', {}, 'Barcode lookups need a connection to your server. Enter the food from its label now, or try again when you are connected.'),
        h('div', { class: 'settings-actions' }, enterFromLabel(code), tryAgain()));
      return;
    }
    if (err.status === 404) {
      say(data.name ? `${data.name}: no nutrition facts.` : 'Not found.');
      const contribute = KH.off.safeHttpsUrl(data.contribute_url);
      panel(data.name ? 'No nutrition facts for this product' : 'Product not found',
        data.name ? h('p', { class: 'scan-product' }, data.name) : null,
        h('p', {}, detail),
        h('div', { class: 'settings-actions' }, enterFromLabel(data.gtin, data.name)),
        contribute ? h('p', { class: 'hint' }, 'Want to help others? ', newTab(contribute, 'Add it to Open Food Facts'),
          ' (their free, open database; you can add the label photo and numbers there).') : null);
      return;
    }
    if (err.status === 503 && data.reason === 'off_consent_required') {
      say('Open Food Facts needs your agreement first.');
      const agree = actionButton('Send barcodes to Open Food Facts and look up', 'primary', async (btn) => {
        await KH.api.updateMySettings({ 'food.off_consent': true });
        btn.textContent = 'Agreed';
        if (lastCode) await lookup(lastCode.code, lastCode.format, { typed: lastCode.typed });
      });
      panel('Look this up in Open Food Facts?',
        h('p', {}, 'This server does not know this product yet. It can ask Open Food Facts, a free database of packaged foods. '
          + 'Only the barcode number is sent, from your server, and only for products it does not know yet.'),
        h('p', { class: 'hint' }, 'You can change this any time in Settings → Food data. Product data © Open Food Facts contributors, ODbL.'),
        h('div', { class: 'settings-actions' }, agree, enterFromLabel(data.gtin, '', 'secondary')));
      return;
    }
    if (err.status === 429) {
      const wait = Number(data.retry_after) || null;
      say(detail);
      panel('Too many lookups just now', h('p', {}, detail), wait ? h('p', { class: 'hint' }, `Try again in ${wait < 120 ? `${wait} seconds` : `${Math.round(wait / 60)} minutes`}.`) : null,
        h('div', { class: 'settings-actions' }, enterFromLabel(data.gtin)));
      return;
    }
    if (err.status === 502) {
      say(detail);
      panel('The food databases did not answer', h('p', {}, detail), h('div', { class: 'settings-actions' }, tryAgain(), enterFromLabel(data.gtin)));
      return;
    }
    if (err.status === 400 && data.reason) {
      say(detail);
      if (lastCode && lastCode.typed) { KH.forms.fieldError(codeInput, detail, codeRow); codeInput.focus(); clear(resultEl); return; }
      panel(data.reason === 'check_digit' || data.reason === 'format' ? 'That did not read correctly' : 'This barcode is not looked up',
        h('p', {}, detail), h('div', { class: 'settings-actions' }, enterFromLabel(null)));
      return;
    }
    // 503 lookups off / USDA reasons, and anything else: the server's sentence and the way forward.
    say(detail);
    panel(err.status === 503 ? 'Barcode lookups are not available' : 'The lookup failed', h('p', {}, detail),
      h('div', { class: 'settings-actions' }, enterFromLabel(data.gtin)));
  }

  // ---------------------------------------------------------------------------
  // Opening the sheet
  // ---------------------------------------------------------------------------
  function open({ trigger: from = null } = {}) {
    trigger = from;
    stopCamera();
    clear(resultEl);
    say('');
    codeInput.value = '';
    KH.forms.clearFieldErrors($('#scan-form'));
    const canLive = liveSupported();
    $('#scan-camera-row').hidden = !canLive;
    $('#scan-camera').hidden = !canLive;
    $('#scan-camera-stop').hidden = true;
    $('#scan-viewfinder').hidden = true;
    const liveNote = $('#scan-live-note');
    liveNote.hidden = canLive;
    liveNote.textContent = canLive ? '' : liveNoteText();
    opening += 1;
    chose = false;
    sheets.open(dlg, from, canLive ? $('#scan-camera') : $('#scan-file'));
    if (canLive) {
      const mine = opening;
      cameraPreferred().then((on) => { if (on) return startCamera({ auto: mine }); return null; })
        .catch((e) => { stopCamera(); toastError(e); });
    }
  }
  // The person's food.scan_prefer_camera (GET /api/me/settings; default on). Unreadable (offline): no automatic start.
  async function cameraPreferred() {
    try {
      const res = await KH.api.mySettings();
      const item = res && res.settings ? res.settings['food.scan_prefer_camera'] : null;
      return !item || item.value !== false;
    } catch (e) { return false; }
  }
  $('#btn-scan').addEventListener('click', (e) => open({ trigger: e.currentTarget }));

  // ---------------------------------------------------------------------------
  // Where a food's data came from (the entry sheet; note 03 R11, §9 B4)
  // ---------------------------------------------------------------------------
  // barcode._attributions_of_row: USDA first for a USDA row, the Open Food Facts product page when ODbL data is in it.
  function attributionsOf(food) {
    const license = (food && food.source_license) || '';
    const out = [];
    if (license.includes('CC0-1.0') && food.source === 'usda') out.push(KH.off.usdaAttribution());
    if (license.includes('ODbL-1.0') && food.gtin) out.push(KH.off.attribution(food.gtin));
    if (license.includes('CC0-1.0') && food.source !== 'usda') out.push(KH.off.usdaAttribution());
    return out;
  }
  function additiveLabel(code) {
    const E = KH.additives ? KH.additives.E_NAMES : {};
    return /^e\d/.test(code) ? `${E[code] || KH.additives.displayCode(code)} (${KH.additives.displayCode(code)})` : code;
  }
  function renderProvenance(container, food) {
    if (!container) return;
    clear(container);
    const atts = food ? attributionsOf(food) : [];
    const quality = (food && food.quality) || [];
    const additives = (food && food.additives) || [];
    if (!atts.length && !quality.length && !additives.length && !(food && (food.gtin || food.ingredients_text))) { container.hidden = true; return; }
    container.hidden = false;
    for (const a of atts) {
      const href = KH.off.safeHttpsUrl(a.url);
      container.append(h('p', { class: 'attribution' }, href ? newTab(href, a.text) : a.text));
    }
    if (food.gtin) container.append(h('p', { class: 'hint' }, `Barcode ${KH.gtin.offCode(food.gtin)}`));
    if (quality.length) {
      container.append(h('ul', { class: 'quality-notes', 'aria-label': 'About this data' }, quality.map((q) => h('li', {}, q.message))));
    }
    if (additives.length) {
      container.append(h('p', { class: 'hint' }, 'Additives found: ', additives.map(additiveLabel).join(', '), '.'));
    }
    if (food.ingredients_text) {
      container.append(h('details', { class: 'inline-details' }, h('summary', {}, 'Ingredients'), h('p', { class: 'ingredients-text' }, food.ingredients_text)));
    }
  }

  // ---------------------------------------------------------------------------
  // Quick add: the photo of the label beside the form, and "Read the label for me" (AI)
  // ---------------------------------------------------------------------------
  const quickDlg = $('#sheet-quick');
  const photoInput = $('#q-photo');
  const photoView = $('#q-photo-view');
  const photoImg = $('#q-photo-img');
  const photoFrame = $('#q-photo-frame');
  const aiBox = $('#q-photo-ai');
  const photo = { file: null, url: null, jpeg: null };

  function setZoom(n) {
    for (const b of $$('[data-zoom]', photoView)) b.setAttribute('aria-pressed', String(Number(b.dataset.zoom) === n));
    photoFrame.classList.remove('zoom-1', 'zoom-2', 'zoom-3');
    photoFrame.classList.add(`zoom-${n}`);
  }
  for (const b of $$('[data-zoom]', photoView)) b.addEventListener('click', () => setZoom(Number(b.dataset.zoom)));

  function dropPhoto() {
    if (photo.url) URL.revokeObjectURL(photo.url);
    photo.file = null; photo.url = null; photo.jpeg = null;
    photoImg.removeAttribute('src');
    photoView.hidden = true;
    quickDlg.classList.remove('with-photo');
    clear(aiBox);
    aiBox.hidden = true;
  }
  photoInput.addEventListener('change', () => {
    const file = photoInput.files && photoInput.files[0];
    if (photo.url) URL.revokeObjectURL(photo.url);
    photo.jpeg = null;
    if (!file) { dropPhoto(); return; }
    photo.file = file;
    photo.url = URL.createObjectURL(file);
    photoImg.src = photo.url;
    photoView.hidden = false;
    quickDlg.classList.add('with-photo');
    setZoom(1);
    renderAi().catch((e) => console.warn('AI label reading unavailable:', e));
  });
  $('#q-photo-remove').addEventListener('click', () => { dropPhoto(); photoInput.value = ''; photoInput.focus(); });
  quickDlg.addEventListener('close', () => { dropPhoto(); photoInput.value = ''; });

  async function renderAi() {
    clear(aiBox);
    aiBox.hidden = true;
    if (!photo.file) return;
    if (MOCK) {
      aiBox.append(h('p', { class: 'hint' }, 'In the installed app, AI can read the label for you when your admin has switched it on. This demo never sends photos anywhere.'));
      aiBox.hidden = false;
      return;
    }
    if (!KH.ai || typeof KH.ai.status !== 'function') return;
    const st = await KH.ai.status();
    if (!st || !st.enabled) return;
    if (!st.available || !(st.features && st.features.label)) {
      if (st.reason === 'not_opted_in') {
        aiBox.append(h('p', { class: 'hint' }, 'AI can read the label for you. ',
          h('button', { class: 'link-btn', type: 'button', onclick: () => { quickDlg.close(); KH.router.show('settings'); } }, 'Turn on AI ideas in Settings')));
        aiBox.hidden = false;
      }
      return;
    }
    const out = h('div', { class: 'ai-results', 'aria-live': 'polite' });
    const err = h('div', { class: 'form-error', role: 'alert' });
    const jpeg = async () => { if (!photo.jpeg) photo.jpeg = await KH.ai.prepareJpeg(photo.file); return photo.jpeg; };
    const read = actionButton('Read the label for me (AI)', 'secondary', async (btn) => {
      clear(err); clear(out);
      btn.textContent = 'Reading…';
      out.setAttribute('aria-busy', 'true');
      try {
        const blob = await jpeg();
        const answer = await KH.ai.withConsent('photos', () => KH.ai.uploadPhoto('label', blob, false), () => KH.ai.uploadPhoto('label', blob, true), btn);
        if (answer) fillFromLabel(answer, out);
      } catch (e) {
        if (!e.handled && !e.cancelled) err.append(h('p', {}, e.detail || e.message || 'The label could not be read.'));
      } finally { btn.textContent = 'Read the label for me (AI)'; out.removeAttribute('aria-busy'); }
    });
    const what = actionButton('What will be sent?', 'secondary', async (btn) => {
      clear(err);
      try { await KH.ai.showSent(await KH.ai.uploadPhoto('label', await jpeg(), true), { trigger: btn }); } catch (e) { if (!e.handled) err.append(h('p', {}, e.detail || e.message)); }
    });
    aiBox.append(h('p', { class: 'hint' }, `AI (${st.provider ? st.provider.label : 'your AI service'}) can copy the numbers from this photo into the form. Check each one before saving.`),
      h('div', { class: 'settings-actions' }, read, what), err, out);
    aiBox.hidden = false;
  }

  // The label draft into the Quick add fields, each marked until the person changes it.
  function fillFromLabel(answer, out) {
    clear(out);
    if (answer.status !== 'ok' || !answer.draft) {
      const text = answer.status === 'not_a_label' ? 'This does not look like a nutrition label. Try a photo of the Nutrition Facts panel.'
        : answer.status === 'unreadable' ? 'The label could not be read. Try a sharper photo in good light, or type the numbers.'
          : answer.message || 'The AI answer could not be used. Type the numbers from the photo.';
      out.append(note('caution', h('p', {}, text)));
      return;
    }
    const d = answer.draft;
    const fromPhoto = new Set(answer.from_photo || []);
    const estimated = new Set(answer.estimated || []);
    const fill = (input, value, key) => {
      if (!input) return;
      input.value = value == null ? '' : String(value);
      const label = document.querySelector(`label[for="${input.id}"]`);
      if (label) $$('.ai-tag', label).forEach((t) => t.remove());
      input.classList.remove('from-photo');
      if (!(fromPhoto.has(key) || estimated.has(key))) return;
      input.classList.add('from-photo');
      const tag = h('span', { class: `ai-tag${estimated.has(key) ? ' est' : ''}` }, estimated.has(key) ? 'estimated' : 'from photo');
      if (label) label.append(' ', tag);
      input.addEventListener('input', () => { input.classList.remove('from-photo'); tag.remove(); }, { once: true });
    };
    fill($('#q-name'), d.name, 'name');
    fill($('#q-serving-desc'), d.serving_desc, 'serving_desc');
    fill($('#q-serving-g'), d.serving_g, 'serving_g');
    for (const key of Object.keys(NUT)) {
      if (key === 'fluid_ml') continue;
      fill($(`#qn-${key}`), d.nutrients ? d.nutrients[key] : null, key);
    }
    fill($('#q-ingredients'), d.ingredients_text, 'ingredients_text');
    $('#quick-form').dispatchEvent(new Event('input', { bubbles: true }));
    const checks = (answer.checks || []).map((c) => h('li', {}, c.message));
    out.append(note('caution', h('p', {}, h('strong', {}, answer.notice || 'Read by AI from your photo. Check every number against the label before saving.'))),
      checks.length ? h('ul', { class: 'ai-checks' }, checks) : null);
    toast('The form is filled from your photo. Check every number.');
    const needs = (answer.needs || [])[0];
    const focus = needs === 'name' ? $('#q-name') : needs === 'serving_g' ? $('#q-serving-g') : $('#q-name');
    setTimeout(() => focus.focus(), 0);
  }

  // Called by Quick add when it opens (js/views/add.js): a fresh panel, the photo first when asked.
  function quickOpened({ photoFirst = false } = {}) {
    dropPhoto();
    photoInput.value = '';
    $('#quick-photo').classList.toggle('prompt', !!photoFirst);
  }

  KH.scan = { open, lookup, decodeFile, getDetector, decoder: () => decoderKind, liveSupported, stopCamera, attributionsOf,
    renderProvenance, quickOpened, newTab, FORMATS };
})();
