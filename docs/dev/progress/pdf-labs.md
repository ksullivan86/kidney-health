Status: in progress

# pdf-labs: lab results from a PDF report (design note 13)

Spec: `docs/dev/research/13-lab-results-from-a-pdf.md` (decided 2026-10-22). Branch: this worktree, started from `65c1dcb`
(origin/main + note 13). Do not push; commit own paths only (see CLAUDE.md "checkpoint as you go").

## Plan (in order) and state

1. [x] Vendoring: `scripts/vendor_barcode.py` gets the pdfjs-dist group (`--only` flag added, existing CLI unchanged),
       `app/static/vendor/pdfjs-dist-6.4.299/`, regenerated `vendor/README.md`, `tests/test_vendor.py`, vendor-check workflow wording.
2. [x] `app/static/js/engine/pdf_pages.js` (`KH.pdfPages`) + `tests/js/pdf_pages_page.mjs` + a pytest wrapper.
3. [x] CSP: `trusted-types kh-sw kh-xml kh-pdf` in `app/security.py` + every test that pins the string + policy-owner test.
4. [x] `index.html` (script tag, file input accept, card text) and `sw.js` (precache `pdf_pages.js`, comments).
5. [x] `lab_photo.js` PDF flow + extended `tests/js/lab_photo_page.mjs` / `tests/test_lab_photo_ui.py`.
6. [ ] Browser walk `tools/e2e/lab_pdf.py` (no lab-photo walk existed; this one starts a fake local AI like `fallback.py`),
       listed in `tools/e2e/README.md` and `tests/test_e2e_tools.py`.
7. [ ] Docs: ARCHITECTURE, docs/ai.md, handbook page, docs/security.md, docs/deployment.md + handbook upgrades page (CSP string),
       ROADMAP, CHANGELOG (`## Unreleased`), maintainers/README mentions; `python scripts/build_handbook.py --check`.
8. [ ] Full run: `python -m pytest` (no xdist installed), `node tests/js/run_vectors.mjs`, `ruff check .`.

## Findings so far (pdfjs-dist 6.4.299)

* Tarball `https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz`, 8,539,589 bytes (> the script's old 8 MiB cap, so the
  cap is per package now); `dist.integrity` `sha512-AVl138zALtfaAPvADulE0PZThbYzCBS79nL4pOSL/6Sm/4AH5A21BD9VHt97OlCuzJuCpmeZtAtkinisF4Vb1g==`
  matched before reading. Extracted (data filter, nothing run) into the session scratch directory only.
* Build choice: `legacy/build/`. pdf.js FAQ (wiki "Which browsers/environments are supported?"): the default build is "intended for
  the latest browsers" and lists only Firefox and Chrome as supported; the `legacy` build lists Firefox ESR+, Chrome 125+, Safari 18+
  ("mostly"). The modern build calls `Promise.try` (Safari 18.2), `Promise.withResolvers` (17.4), `Math.sumPrecise` and
  `Uint8Array.fromBase64` with no polyfill; the legacy build bundles core-js for them. Note 02 covers Safari 16.4+, so by the note's
  own rule (modern needs more) the legacy build.
* API differences from note 13 D3: `isEvalSupported` no longer exists in 6.4 (no eval path left in the library; ignored if passed);
  `render()` takes `canvas` (recommended) next to the old `canvasContext`; new options `wasmUrl`/`useWasm`/`iccUrl` (unused: no wasm
  decoders vendored, so JPEG 2000 / JBIG2 images and ICC profiles are not decoded; nothing is fetched); `getDocument` options
  `data`, `enableXfa`, `disableAutoFetch`, `disableStream`, `disableRange`, `stopAtErrors` all still exist; `GlobalWorkerOptions.workerPort`
  exists (setter requires `instanceof Worker`); with a port pdf.js never makes a fake worker, but a worker that fails to load only
  fires `error` on the Worker (the load promise never settles), so `pdf_pages.js` listens for it.

## Decisions

* The photo prep helper `KH.ai.prepareJpeg` redraws at 1600 px long edge (`PHOTO_EDGE`), so a page drawn at 2048 px is scaled down
  once more; kept as the note says (reuse, no second helper). Mentioned in the report as a possible follow-up.

## Commands that reproduce checks

`python3 scripts/vendor_barcode.py --check` (offline pins), `python -m pytest tests/test_vendor.py tests/test_pdf_pages.py tests/test_frontend_shell.py tests/test_security.py tests/test_ccda_labs_ui.py tests/test_preview_build.py -q`,
`node tests/js/pdf_pages_page.mjs` (prints JSON; needs Node 22, uses vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER + module.registerHooks, so it prints an ExperimentalWarning on stderr).

Done so far (verified by the commands above): vendoring script (`--only barcode|pdfjs`, per-package download cap, tarball URL equality, pdf.js
group, README sections), the three vendored files, pdf_pages.js and its Node test (fake pdf.js), the CSP directive and its tests,
index.html script tag and sw.js precache entry (sw.js test in test_vendor.py). index.html's file input / card text and lab_photo.js are next.
