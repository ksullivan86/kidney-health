/* Kidney Diet Log — the pages of a PDF lab report, drawn on the device (KH.pdfPages; docs/dev/research/13-lab-results-from-a-pdf.md
   §4.2, ARCHITECTURE.md "Lab report photos" → "PDFs").

   Patient portals hand out a lab report as a PDF. Labs → "Read a lab report" lets a person choose that file; this module opens it IN
   THE BROWSER with the vendored pdf.js (app/static/vendor/pdfjs-dist-6.4.299/, README.md there) and draws the pages the person ticks
   as JPEG pictures, which js/views/lab_photo.js then sends one by one, like photos, to POST /api/ai/read-lab-report (local AI only).
   The PDF itself is never sent anywhere and the server never parses one: it only sees the checked JPEGs it already takes.

   API (window.KH.pdfPages)
     supported()                   true when this browser can run it: Worker, Promise.withResolvers and a canvas that makes a JPEG.
                                   (pdf.js's legacy build still calls Promise.withResolvers natively: Safari 17.4, Chrome 119, Firefox 121.
                                   Module workers are older than that in every browser, so this one check covers them too.)
     open(file, {maxBytes, maxPages, signal})
                                   → Promise<{numPages, render(pageNumber, {signal}) → Promise<Blob image/jpeg>, close()}>
     planScale(width, height)      → {scale, width, height}: the size a page of width × height points is drawn at (pure; the tests use it)
     LIMITS, PDFJS_URL, WORKER_URL, ERROR_CODES

   Limits (all checked here, none by pdf.js):
     * the file: at most 20 MiB (`maxBytes`), checked from file.size BEFORE it is read; the first five bytes must be "%PDF-";
     * the document: at most 50 pages (`maxPages`);
     * each drawn page: the longer side at most 2048 px and the area at most 4,000,000 px (what app/imagecheck.py accepts: 16–2048 px a
       side, 4 megapixels, 4:1), at least 16 px a side, and never more than 4× the page's size in points (288 dpi is more than a reader
       needs, and a postage-stamp page is not blown up to 2000 px). A US Letter or A4 page comes out at about 1583 × 2048 (3.2 MP);
       a page more than 4:1 long is drawn as it is and the server refuses it, which the screen shows as that page's own line.
     The picture then goes through the same redraw as every AI photo (KH.ai.prepareJpeg), which removes anything but pixels.

   What pdf.js is allowed to do (note 13 D1–D4; every option is listed here so an update can be reviewed against the new source):
     * It runs in a module Web Worker that THIS file makes, under the Trusted Types policy `kh-pdf` (named in the CSP's `trusted-types`
       list, app/security.py). That policy is created here and nowhere else, never as a default policy and never allowed twice, and its
       createScriptURL returns its input only when it is exactly WORKER_URL and throws for anything else. `GlobalWorkerOptions.workerPort`
       is set to that worker BEFORE getDocument, so pdf.js never makes a worker of its own. With a port it has no "fake worker" to fall
       back to; if it ever did (a different version, a changed API) the check after getDocument sees that nothing was posted to our worker
       and the file is refused (`browser`) before any of its bytes is handed over. A worker that cannot start (module workers missing,
       the file blocked) fires `error` and the file is refused the same way; nothing waits for it.
     * getDocument({data, isEvalSupported: false, enableXfa: false, disableAutoFetch: true, disableStream: true, disableRange: true,
       stopAtErrors: false}) and nothing else:
         data              the bytes (an ArrayBuffer; pdf.js hands the buffer to the worker, this page keeps no copy). No `url`, so nothing
                           is fetched, and no `httpHeaders`, `withCredentials`, `password`, `range`.
         isEvalSupported   false. pdf.js 6.4 no longer has this switch (its eval code path was removed, CVE-2024-4367 was the reason in
                           4.x); the option is ignored there and kept so that a build that has it again starts with it off. This page's
                           CSP has no 'unsafe-eval' either.
         enableXfa         false: no XFA forms.
         disableAutoFetch, disableStream, disableRange   true: the document is in memory, nothing is streamed or requested later.
         stopAtErrors      false: a page with a broken object is drawn as far as it goes (the person ticks which pages to read).
       NOT passed, on purpose: `cMapUrl`, `standardFontDataUrl`, `iccUrl`, `wasmUrl` (nothing is fetched; fonts that are not in the PDF fall
       back to the browser's own, CJK fonts that need CMaps and JPEG 2000 / JBIG2 images, which need the WebAssembly decoders, are not
       drawn), `enableScripting` (not a getDocument option: scripting runs only in the pdf.js viewer, which is not here), `password`
       and `onPassword` (the app never asks for a PDF password: a protected file is refused).
     * page.render({canvas, viewport, background: '#ffffff', annotationMode: AnnotationMode.DISABLE}): a white page (a JPEG has no
       transparency), no form fields and no annotation layer, no text layer, no optional-content changes. 6.4 takes `canvas` (the old
       `canvasContext` still works but is deprecated).
     * Afterwards page.cleanup(), canvas set to 0 × 0 (Safari keeps big canvases alive otherwise).
     * close() destroys the pdf.js task (document, fonts, caches) AND terminates the worker (with a port pdf.js does not), and clears
       `workerPort`. One document is open at a time: open() closes the previous one first.

   Error codes (error.code; the screen has a plain sentence for each, js/views/lab_photo.js):
     too_big          the file is over maxBytes (error.size is its size); nothing was read
     not_pdf          the file does not start with "%PDF-" (or is empty)
     password         the PDF needs a password (PasswordException); never asked for
     damaged          pdf.js could not read it, it has no pages, or one page could not be drawn
     too_many_pages   more than maxPages pages (error.numPages)
     browser          this browser cannot do it: supported() is false, pdf.js or its worker could not be loaded or started, the policy could
                      not be created, pdf.js did not use our worker, or the canvas could not make a JPEG
   Cancel is `AbortError` (name 'AbortError', as fetch): thrown from open() and render() when `signal` aborts; whatever was started is
   released first.

   Plain script (no module syntax, so index.html loads it like the other engines); pdf.js itself is loaded with a dynamic import() on
   the first PDF only, from this origin (script-src 'self'). Runs in the page and, with fake globals, under Node
   (tests/js/pdf_pages_page.mjs). */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});

  const PDFJS_URL = '/vendor/pdfjs-dist-6.4.299/pdf.min.mjs';
  const WORKER_URL = '/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs';
  const LIMITS = Object.freeze({
    MAX_BYTES: 20 * 1024 * 1024, // the file
    MAX_PAGES: 50, // the document
    MAX_EDGE: 2048, // px, the longer side of a drawn page (app/imagecheck.py MAX_SIDE)
    MAX_AREA: 4000000, // px (app/imagecheck.py MAX_PIXELS)
    MIN_EDGE: 16, // px (app/imagecheck.py MIN_SIDE)
    MAX_SCALE: 4, // × the size in points
    JPEG_QUALITY: 0.9,
  });
  const ERROR_CODES = Object.freeze(['too_big', 'not_pdf', 'password', 'damaged', 'too_many_pages', 'browser']);

  function fail(code, extra) {
    return Object.assign(new Error(`PDF: ${code}`), { code }, extra || {});
  }
  function abortError() {
    return typeof root.DOMException === 'function' ? new root.DOMException('The PDF was not read.', 'AbortError') : Object.assign(new Error('The PDF was not read.'), { name: 'AbortError' });
  }
  const isAbort = (e) => !!e && e.name === 'AbortError';
  function throwIfAborted(signal) {
    if (signal && signal.aborted) throw abortError();
  }
  // `promise`, or an AbortError as soon as `signal` aborts (the work behind it is stopped by the caller's cleanup).
  function raceAbort(promise, signal) {
    if (!signal) return promise;
    return new Promise((resolve, reject) => {
      const onAbort = () => reject(abortError());
      if (signal.aborted) { onAbort(); return; }
      signal.addEventListener('abort', onAbort, { once: true });
      promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
    });
  }

  function supported() {
    try {
      const canvasOk = typeof root.OffscreenCanvas === 'function'
        || (typeof root.HTMLCanvasElement === 'function' && typeof root.HTMLCanvasElement.prototype.toBlob === 'function');
      return typeof root.Worker === 'function' && typeof root.Promise === 'function' && typeof root.Promise.withResolvers === 'function' && canvasOk;
    } catch (e) {
      return false;
    }
  }

  /* The size a page of width × height points is drawn at: the largest scale that keeps the longer side ≤ MAX_EDGE and the area ≤ MAX_AREA,
     at most MAX_SCALE; and, for a tiny page, at least enough for MIN_EDGE on the shorter side (never beyond the other limits). Sizes are
     rounded DOWN, so the limits hold exactly. */
  function planScale(width, height) {
    const { MAX_EDGE, MAX_AREA, MIN_EDGE, MAX_SCALE } = LIMITS;
    const w = Number.isFinite(width) && width > 0 ? width : 612;
    const h = Number.isFinite(height) && height > 0 ? height : 792;
    const hard = Math.min(MAX_EDGE / Math.max(w, h), Math.sqrt(MAX_AREA / (w * h)));
    let scale = Math.min(hard, MAX_SCALE);
    if (Math.min(w, h) * scale < MIN_EDGE) scale = Math.min(hard, MIN_EDGE / Math.min(w, h));
    const px = (side) => Math.max(1, Math.floor(side * scale + 1e-6));
    return { scale, width: px(w), height: px(h) };
  }

  // ---------------------------------------------------------------------------
  // Trusted Types: the one policy this page creates for pdf.js's worker
  // ---------------------------------------------------------------------------
  /* The page's CSP has `require-trusted-types-for 'script'`: the Worker constructor takes a TrustedScriptURL. This module creates ONE named
     policy, kh-pdf (named in the CSP's `trusted-types` list, app/security.py), whose createScriptURL returns its input only when it is exactly
     WORKER_URL. The policy object stays in this closure; it is never a default policy and never allowed twice. Without Trusted Types (an
     older browser, Node) the URL string itself is used; if the policy cannot be created (a host page whose CSP does not list the name) the
     file is refused (`browser`), no worker is made. */
  let policy = null; // the policy, or false once it could not be created
  function workerUrl() {
    const tt = root.trustedTypes;
    if (!tt || typeof tt.createPolicy !== 'function') return WORKER_URL;
    if (policy === false) throw new TypeError('no Trusted Types policy for the PDF worker');
    if (!policy) {
      try {
        policy = tt.createPolicy('kh-pdf', {
          createScriptURL: (url) => { if (url === WORKER_URL) return url; throw new TypeError('blocked worker URL'); },
        });
      } catch (e) {
        policy = false;
        throw e;
      }
    }
    return policy.createScriptURL(WORKER_URL);
  }

  // ---------------------------------------------------------------------------
  // open
  // ---------------------------------------------------------------------------
  let active = null; // the document that is open now (GlobalWorkerOptions is global state: one at a time)

  function hasPdfHeader(buffer) {
    if (!buffer || buffer.byteLength < 5) return false;
    const head = new Uint8Array(buffer, 0, 5);
    return head[0] === 0x25 && head[1] === 0x50 && head[2] === 0x44 && head[3] === 0x46 && head[4] === 0x2d; // %PDF-
  }
  const isPasswordError = (lib, e) => !!e && (e.name === 'PasswordException' || (typeof lib.PasswordException === 'function' && e instanceof lib.PasswordException));

  async function open(file, opts = {}) {
    const maxBytes = opts.maxBytes || LIMITS.MAX_BYTES;
    const maxPages = opts.maxPages || LIMITS.MAX_PAGES;
    const signal = opts.signal || null;
    if (active) active.close();
    throwIfAborted(signal);
    if (!supported()) throw fail('browser');
    if (!file || typeof file.size !== 'number' || typeof file.arrayBuffer !== 'function') throw fail('not_pdf');
    if (file.size > maxBytes) throw fail('too_big', { size: file.size });
    const bytes = await file.arrayBuffer();
    throwIfAborted(signal);
    if (!hasPdfHeader(bytes)) throw fail('not_pdf');

    let lib;
    try {
      lib = await raceAbort(import(PDFJS_URL), signal);
    } catch (e) {
      throw isAbort(e) ? e : fail('browser');
    }
    if (!lib || !lib.GlobalWorkerOptions || typeof lib.getDocument !== 'function') throw fail('browser');

    let worker;
    try {
      worker = new root.Worker(workerUrl(), { type: 'module' });
    } catch (e) {
      throw fail('browser');
    }
    // Count what pdf.js posts to our worker. It posts "configure" the moment it takes the port, inside getDocument (see below).
    let posted = 0;
    const post = worker.postMessage;
    worker.postMessage = function (...args) { posted += 1; return post.apply(this, args); };
    // A worker that fails to start only fires `error`; pdf.js would wait for it forever.
    const dead = new Promise((resolve, reject) => {
      worker.addEventListener('error', () => reject(fail('browser')));
      worker.addEventListener('messageerror', () => reject(fail('browser')));
    });
    dead.catch(() => {});

    let task = null;
    let closed = false;
    let handle = null;
    function close() {
      if (closed) return;
      closed = true;
      if (active === handle) active = null;
      try { if (task) Promise.resolve(task.destroy()).catch(() => {}); } catch (e) { /* already gone */ }
      try { worker.terminate(); } catch (e) { /* already gone */ }
      try { if (lib.GlobalWorkerOptions.workerPort === worker) lib.GlobalWorkerOptions.workerPort = null; } catch (e) { /* nothing to clear */ }
    }

    try {
      lib.GlobalWorkerOptions.workerPort = worker;
      if (lib.GlobalWorkerOptions.workerPort !== worker) throw fail('browser');
      task = lib.getDocument({
        data: bytes,
        isEvalSupported: false,
        enableXfa: false,
        disableAutoFetch: true,
        disableStream: true,
        disableRange: true,
        stopAtErrors: false,
      });
      // pdf.js took our port: it has already posted "configure" to it. If it did not, it is setting up a worker of its own (a fake one on
      // the main thread) and the document is not opened; this check runs before the bytes can be handed to anything.
      if (posted === 0) throw fail('browser');
      const doc = await raceAbort(Promise.race([task.promise, dead]), signal);
      if (!doc || !(doc.numPages >= 1)) throw fail('damaged');
      if (doc.numPages > maxPages) throw fail('too_many_pages', { numPages: doc.numPages });
      handle = {
        numPages: doc.numPages,
        render: (pageNumber, ropts) => renderPage(lib, doc, worker, pageNumber, ropts || {}, () => closed),
        close,
      };
      active = handle;
      return handle;
    } catch (e) {
      close();
      if (isAbort(e) || ERROR_CODES.includes(e && e.code)) throw e;
      throw fail(isPasswordError(lib, e) ? 'password' : 'damaged');
    }
  }

  // ---------------------------------------------------------------------------
  // render
  // ---------------------------------------------------------------------------
  function makeCanvas(width, height) {
    if (root.document && typeof root.document.createElement === 'function') {
      const canvas = root.document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      return canvas;
    }
    return new root.OffscreenCanvas(width, height);
  }
  function canvasToJpeg(canvas) {
    const type = 'image/jpeg';
    if (typeof canvas.toBlob === 'function') return new Promise((resolve) => canvas.toBlob(resolve, type, LIMITS.JPEG_QUALITY));
    return canvas.convertToBlob({ type, quality: LIMITS.JPEG_QUALITY });
  }

  async function renderPage(lib, doc, worker, pageNumber, ropts, isClosed) {
    const signal = ropts.signal || null;
    if (isClosed()) throw fail('damaged');
    if (!Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > doc.numPages) throw new RangeError(`page ${pageNumber} is not in this document`);
    throwIfAborted(signal);
    let page = null;
    let canvas = null;
    let running = null;
    try {
      page = await raceAbort(doc.getPage(pageNumber), signal);
      const size = page.getViewport({ scale: 1 });
      const plan = planScale(size.width, size.height);
      const viewport = page.getViewport({ scale: plan.scale });
      canvas = makeCanvas(plan.width, plan.height);
      const ctx = canvas.getContext('2d', { alpha: false });
      if (ctx) { ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, plan.width, plan.height); }
      running = page.render({ canvas, viewport, background: '#ffffff', annotationMode: lib.AnnotationMode.DISABLE });
      await raceAbort(running.promise, signal);
      const blob = await canvasToJpeg(canvas);
      if (!blob) throw fail('browser'); // the browser refused a canvas this size
      return blob;
    } catch (e) {
      if (running && typeof running.cancel === 'function') { try { running.cancel(); } catch (err) { /* finished */ } }
      if (isAbort(e) || ERROR_CODES.includes(e && e.code) || e instanceof RangeError) throw e;
      throw fail('damaged');
    } finally {
      if (canvas) { canvas.width = 0; canvas.height = 0; }
      if (page && typeof page.cleanup === 'function') { try { page.cleanup(); } catch (e) { /* the document was closed meanwhile */ } }
    }
  }

  KH.pdfPages = { supported, open, planScale, LIMITS, PDFJS_URL, WORKER_URL, ERROR_CODES };
})(typeof window !== 'undefined' ? window : globalThis);
