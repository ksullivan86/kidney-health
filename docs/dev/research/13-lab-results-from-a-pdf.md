# 13 · Lab results from a PDF report (pages drawn in the browser, read like a photo)

| | |
|---|---|
| Status | Decided 2026-10-22 (§7), to be built in one part. |
| Date researched | 2026-10-22, against `main` at `2998cb5` |
| Scope | The PDF a lab portal downloads (Quest, Labcorp, a hospital portal), chosen in Labs → **Read a lab report**: the browser draws the chosen pages with a vendored pdf.js and sends each page, as a picture, through the existing lab-report photo reading (local AI only), so the person reviews the same proposed rows. |
| Out of scope | Parsing a PDF on the server (the server never takes a PDF); reading the PDF's text layer (a later improvement, §6); password-protected PDFs; PDF forms, scripts, attachments, annotations; any PDF outside the lab-report import; a cloud AI for reports (note 04's rule stands: a report can show a name, a date of birth and record numbers). |
| Builds on | `js/views/lab_photo.js` and `POST /api/ai/read-lab-report` (`app/ai/features.py prepare_read_lab_report`, `local_only=True`, `app/ai/lab_report.py`'s judge), `app/imagecheck.py` (16–2048 px a side, at most 4 megapixels, 4:1), the vendoring pattern of `app/static/vendor/` (`scripts/vendor_barcode.py`, `vendor/README.md`, `tests/test_vendor.py`), the CSP and Trusted Types policies in `app/security.py`, ROADMAP "Lab results from a PDF report". |
| Re-verify | Real lab PDFs on the owner's local vision model (`scripts/ai_eval.py` cases from a PDF page, as for photos); an iPhone (Safari) and a desktop browser opening a real portal PDF. |

---

## 1. Context

Since 0.4.0 a person can photograph or screenshot a lab report and the admin's local AI copies the printed results into proposed rows (nothing saved until ticked). Most US portals hand out the report as a PDF. Today the person has to screenshot each page. The ROADMAP item suggested text extraction or rendering **on the server**; this note keeps the server out of it: the PDF stays on the device, and only what the photo route already accepts (one checked JPEG a request) reaches the server.

## 2. Facts used

| # | Fact | Source |
|---|---|---|
| D1 | pdf.js (Mozilla, Apache-2.0) parses and draws PDFs in the browser; `pdfjs-dist` 6.4.299 was published 2026-10-03 (more than 7 days ago, the project's cooldown). The display layer hands parsing to a Web Worker (`pdf.worker.min.mjs`); `GlobalWorkerOptions.workerPort` takes a worker the page made itself. | npm registry `pdfjs-dist` (time, dist-tags); pdf.js `src/display/api.js` (`getDocument` options, `GlobalWorkerOptions`) |
| D2 | CVE-2024-4367 (pdf.js before 4.2.67): a crafted font could run script through `new Function` in the font loader; the fix and the mitigation is `isEvalSupported: false`. This page's CSP has no `'unsafe-eval'`, so `new Function` would be refused anyway. | NVD CVE-2024-4367 ("a type check was missing when handling fonts in PDF.js, which would allow arbitrary JavaScript execution"); the pdf.js security advisory for it (fixed in pdfjs-dist 4.2.67; workaround `isEvalSupported: false`; re-verify the advisory's wording when vendoring) |
| D3 | `getDocument` options used here: `data` (an `ArrayBuffer`, no URL fetch), `isEvalSupported: false`, `enableXfa: false`, `disableAutoFetch: true`, `disableStream: true`, `disableRange: true`, no `cMapUrl` and no `standardFontDataUrl` (nothing is fetched; non-embedded fonts fall back to the browser's fonts). Scripting runs only in the pdf.js viewer with `enableScripting`, which this page does not use. A password-protected file rejects with `PasswordException`. | pdf.js `src/display/api.js` option docs |
| D4 | The page's CSP: `script-src 'self' 'wasm-unsafe-eval'`, `worker-src 'self'`, `require-trusted-types-for 'script'`, `trusted-types kh-sw kh-xml`. A `Worker` URL is a Trusted Types sink (`TrustedScriptURL`). | `app/security.py` CSP_DIRECTIVES; W3C Trusted Types §4 (sinks) |
| D5 | The photo route checks every image on the server: 16–2048 px a side, at most 4 megapixels, aspect at most 4:1, JPEG/PNG; a US Letter or A4 page at 2048 px tall is about 1583 × 2048 (3.2 MP). | `app/imagecheck.py` |

## 3. Goals

1. A person chooses a PDF report and sees the same kind of proposed rows as for a photo, every row unticked, each saying which page it came from.
2. The PDF never leaves the device. Only the drawn pages the person ticked are sent, one JPEG per request, through the route and the local-AI-only rule that exist today.
3. pdf.js runs with the least power that draws a page: in a worker, with no eval, no network, no scripting, no forms, and it is loaded only when the person picks a PDF.
4. One new Trusted Types policy that allows exactly one URL; nothing else in the CSP changes.

## 4. Design

### 4.1 Vendoring (`app/static/vendor/pdfjs-dist-6.4.299/`)

* Files: `pdf.min.mjs`, `pdf.worker.min.mjs`, `LICENSE` from the npm tarball. Choose the modern `build/` or the `legacy/build/` by pdf.js 6.4's own browser-support statement against the Safari versions note 02 covers (16.4 and later); if the modern build needs more, or the statement is unclear, take `legacy/build/`. Write which one and why into `vendor/README.md`.
* `scripts/vendor_barcode.py` becomes the general vendoring script for both groups (keep its file name and CLI; the weekly `--check-latest` CI job then covers pdf.js too): the tarball's `dist.integrity` (SHA-512) is checked before it is read, each file is pinned by SHA-256 in the script and in `vendor/README.md` (a new section "PDF reader (note 13)"), and `tests/test_vendor.py` checks them.
* Not precached by the service worker (about 1.5 MB): fetched on the first PDF and kept by the existing runtime cache for `/vendor/` (as the barcode WASM is); if `sw.js` has no such rule for `/vendor/`, add the narrowest one.

### 4.2 Loading pdf.js (`js/engine/pdf_pages.js`, `KH.pdfPages`)

* `KH.pdfPages.supported()`: `typeof Worker === 'function'` and module workers can be made, `OffscreenCanvas` or `HTMLCanvasElement.prototype.toBlob` present.
* `KH.pdfPages.open(file, {maxBytes, maxPages, signal})`:
  * `file.size > 20 MiB` → refuse (`too_big`) before reading; `await file.arrayBuffer()`; the first five bytes must be `%PDF-` (`not_pdf`).
  * pdf.js is loaded with `await import('/vendor/pdfjs-dist-6.4.299/pdf.min.mjs')` (same origin, allowed by `script-src 'self'`).
  * The worker is made by this module only: `new Worker(policy.createScriptURL(WORKER_URL), {type: 'module'})`, where the policy `kh-pdf` (created once, here) returns its input only when it equals exactly `/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs` and throws otherwise; then `GlobalWorkerOptions.workerPort = worker`, so pdf.js never makes a worker itself and never falls back to a "fake worker" on the main thread (if it would, refuse: `browser`).
  * `getDocument({data, isEvalSupported: false, enableXfa: false, disableAutoFetch: true, disableStream: true, disableRange: true, stopAtErrors: false})` (D3; no `url`, no `cMapUrl`, no `standardFontDataUrl`, no `httpHeaders`).
  * `PasswordException` → `password`; any other load error → `damaged`; `numPages > maxPages (50)` → `too_many_pages`.
  * Returns `{numPages, render(pageNumber) -> Promise<Blob JPEG>, close()}`. `close()` destroys the document and terminates the worker; the view calls it on discard, save, sheet close and a new pick.
* `render(n)`: `page.getViewport({scale})` with `scale` chosen so the longer side is at most 2048 px and the area at most 4,000,000 px (D5), at least 16 px a side; draw on a canvas with a white background (`background: 'white'` / fill first), `annotationMode: AnnotationMode.DISABLE` (no form fields, no annotation layer), no text layer; `canvas.toBlob('image/jpeg', 0.9)`; `page.cleanup()`. The JPEG then goes through the same "redraw on the device without camera data" step as every AI photo (reuse the lab photo's own helper, do not write a second one).
* Error codes, each with a plain message in the view (§4.3): `too_big`, `not_pdf`, `password`, `damaged`, `too_many_pages`, `browser`, and `AbortError` for Cancel.

### 4.3 The screen (`js/views/lab_photo.js`, the existing "Read a lab report" card)

* The picker accepts images (as today) and `application/pdf,.pdf`. The card's text says "a photo, a screenshot or the PDF from your lab's website". Offered and refused exactly as today (`features.lab_report`, local AI only; demo and preview never offer it).
* A PDF pick opens a page list: "Page 1", "Page 2", … with check boxes; pages 1–6 ticked by default, at most 10 ticked ("Reading a page takes a while on your own AI; choose the pages with results."). The consent sheet is the photo's (same words, plus "Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not sent.").
* Read: page by page, "Reading page 2 of 4…", Cancel stops between pages and aborts the current request (`AbortController`). Each page is one `POST /api/ai/read-lab-report` with that page's JPEG, exactly as a photo.
* Results from all pages go into the one review table: every row unticked, with "Read by AI from page N of your PDF. Check each value against the report before you tick it."; a row the same as an earlier one (test, value, unit, date) is shown once, keeping the first page number. A page that fails (the route's own error) says so in a line ("Page 3 could not be read: …") and the others still count. Save sends only the ticked rows through `KH.views.labs.saveImported`, as today.
* Messages (textContent): `too_big` "That PDF is X MB; the largest this app reads is 20 MB."; `not_pdf` "That file is not a PDF."; `password` "This PDF has a password. Open it on your device and take a screenshot of each page instead."; `damaged` "This PDF could not be read. Download it again, or take a screenshot of each page."; `too_many_pages` "This PDF has more than 50 pages. Take screenshots of the pages with your results."; `browser` "This browser cannot read a PDF here. Take a screenshot of each page instead."
* Nothing is stored: the PDF's bytes, the drawn pages and the pdf.js document are let go on discard, save or a new pick.

### 4.4 Server and CSP

* `app/security.py`: `trusted-types kh-sw kh-xml kh-pdf`, and the comment above it names kh-pdf (js/engine/pdf_pages.js, allowing only the vendored worker URL). Nothing else changes: no `'unsafe-eval'`, no `blob:` in `worker-src` or `script-src`.
* No server code, route, setting or migration. The server keeps checking each page image like any photo; `local_only=True` stands.

## 5. Tests (`python -m pytest`, no network)

* `tests/test_vendor.py`: the pdf.js files match their pins and `vendor/README.md`; the script's PACKAGES and the README agree.
* CSP: `trusted-types` names exactly `kh-sw kh-xml kh-pdf`; a test that every `createPolicy(` in `app/static/js` is one of those names, each in exactly the one file the CSP comment names, and `kh-pdf`'s policy function returns only the one worker URL (read from the source, as the kh-sw test does, or run under Node with a fake `trustedTypes`).
* `tests/js/pdf_pages_page.mjs` (Node, a fake pdf.js module and fake canvas): options passed to `getDocument` are exactly D3's (no `url`, `isEvalSupported: false`, …); `workerPort` is set before `getDocument`; scale picks ≤ 2048 px and ≤ 4 MP for Letter, A4, a long receipt-shaped page and a tiny page; each error code; `close()` terminates the worker; Cancel between pages.
* `tests/js/lab_photo_page.mjs` (extend): a PDF pick shows the page list with 1–6 ticked and at most 10; each ticked page is one request; rows merged with page numbers and duplicates collapsed; a failed page leaves the others; messages; the PDF itself is never in any request body.
* Browser walk (`tools/e2e/`, real Chromium, the server with the test AI provider the lab photo walk already uses): a two-page PDF written by a tiny hand-written PDF generator in the harness (no new dependency), pick, tick, read, review, save; the CSP report count stays 0 (no Trusted Types or eval violations); pdf.js was fetched from `/vendor/` and nothing else was requested.

## 6. Risks and later

| Risk | Answer |
|---|---|
| A crafted PDF exploits pdf.js | It runs in a worker on the person's own file, with eval off (and refused by CSP), no scripting, no XFA, no annotations, no network; pinned version, weekly update check; the PDF is never parsed on the server. |
| The vendored pdf.js gets a security fix | `--check-latest` weekly (warn), the update steps in `vendor/README.md`; a pdf.js advisory is a reason to update outside the cooldown (write why in the PR). |
| Non-embedded fonts draw a little differently | The AI reads the picture; small font differences do not change digits. Re-verify with real portal PDFs. |
| Slow on a phone or a small local model | Pages are ticked by the person (default up to 6, at most 10), read one by one with progress and Cancel. |
| Later: text-layer reading | Many portal PDFs have real text; reading it (`getTextContent`) and sending text instead of pictures could be faster and more exact, but needs a new AI feature and its own prompt and judge: a separate note. |

## 7. Decisions (2026-10-22, the owner's standing "recommended least-trust choice")

1. **Draw in the browser, not on the server**: the server never parses a PDF; it only sees the page pictures the photo route already takes.
2. **Pictures, not text, for now**: reuses the shipped reading, prompt, judge and review; text is a later note.
3. **pdf.js locked down** (D3), its worker made by our own code under a single-URL Trusted Types policy (`kh-pdf`); no fake worker on the main thread.
4. **No passwords**: a protected PDF is refused with the screenshot route; the app never asks for a PDF password.
5. **The person ticks the pages** (default 1–6, at most 10), and every row still starts unticked.
