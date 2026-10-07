Status: complete

# frontend-device (M2/M3): scanning, label photos, AI cards check, offline outbox

Role prompt: note 03 R7, R8 (client side), R9, R11 (+ §6 items 12–15, 17, 18 About, 19 vendor check; §9 B4, B9);
note 02 R5 (offline outbox), R7 (camera); verify the KH.ai frontend (built by the ai role) against a fake
OpenAI-compatible server; demo/preview mock routes; Chromium tests. Ports 8370-8379.
Scratch: $S = /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/frontend-device/
Do not edit Python under app/. WIP commits end with " [skip ci]". Commit only my paths (never -A).

## Plan
1. Vendor barcode-detector 3.2.2 (dist/iife/ponyfill.js) + zxing-wasm 3.1.3 (dist/reader/zxing_reader.wasm) with
   `scripts/vendor_barcode.py` (npm registry through the proxy, dist.integrity SHA-512 check (§9 B9), SHA-256 pins,
   licences, vendor/README.md, `--check-latest`), tests/test_vendor.py.
2. JS twins + vectors: js/engine/gtin.js (app/gtin.py), js/engine/additives.js (app/additives.py + textclean),
   tests/data/gen_barcode_vectors.py → barcode_vectors.json, run_vectors.mjs section, pytest freshness test.
3. Mock: js/mock/barcode.js (POST /api/foods/barcode with 3 recorded Open Food Facts products, ODbL attribution),
   v0.3 Food fields + gtin/ingredients_text (+ additive scan) on POST/PUT /api/foods, /copy, /api/log/quick.
4. js/scan.js (KH.scan): decoder selection (native BarcodeDetector with ean_13, else the vendored ponyfill, WASM
   fetched on first detect), live camera (secure context only; two identical reads, ~8/s, 4 s no-frame watchdog,
   track cleanup), photo of a barcode, typed digits (client check digit), consent + attribution, result → entry
   sheet, 404 → Quick add with gtin + name, potassium_additive warning, "not listed" K/P.
5. Quick add (R8): photo beside the form (zoom 1×/2×/3×, object URL revoked on close), Ingredients box, gtin,
   "Read the label for me" (AI, when offered) filling fields marked "from photo".
6. Entry sheet: attribution line (https only, noopener noreferrer), quality notes, "not listed".
7. js/offline.js (KH.offline): IndexedDB `kdl` (meta, snapshots, foods, outbox), client_id on queueable writes,
   6 s timeouts, queue on network failure, sync FIFO (batch for /api/log, single /quick and /mark-eaten) under
   Web Locks, triggers, failed items (Retry/Discard), header badge, Today merge, Settings → This device list,
   sign-out warning sheet, resume day rollover, offline boot from snapshots, offline food search.
8. Settings: About → data sources (R11), admin Food data group keys; This device in demo mode.
9. Tests: pytest static (sinks, CSP, shell list, vectors, vendor), tools/e2e/device.py (Chromium: outbox offline,
   photo decode native + WASM, fake camera live scan on localhost, AI cards + label photo vs fake OpenAI server).
10. parity.py section for barcode/foods fields; sandbox.py; regress.py; walks 375/1280 light/dark.
11. Docs: ARCHITECTURE module list + frontend notes, docs/barcode-and-photos.md, docs/install-on-your-phone.md,
    handbook app pages, ROADMAP.

## Done (and how verified)
* Step 1 (vendor): `scripts/vendor_barcode.py` downloaded barcode-detector 3.2.2 + zxing-wasm 3.1.3 from
  registry.npmjs.org, matched dist.integrity (SHA-512), took ponyfill.iife.js, zxing_reader.wasm and both MIT
  licences out of the tarballs in memory, fetched ZXing-C++ LICENSE at a17fd9dc65d6… (the ponyfill's
  ZXING_CPP_COMMIT) from raw.githubusercontent.com; SHA-256 equal to the note 03 pins; README.md generated.
  `python3 scripts/vendor_barcode.py --check` passes offline; `--check-latest`: barcode-detector 3.2.2 is latest
  (zxing-wasm 3.1.5 exists but the ponyfill still uses 3.1.3). `.github/workflows/vendor-check.yml` (weekly,
  warn-only for releases, fails on a pin mismatch): actionlint + zizmor clean, tests/test_deploy.py passes.

* Step 2 (twins + vectors): js/engine/textclean.js, gtin.js, additives.js, off.js (KH.textclean/gtin/additives/off);
  tests/data/gen_barcode_vectors.py → barcode_vectors.json (784 GTIN, 528 text, 702 additive incl. every OFF/USDA
  fixture + 500 seeded generated lists, 5 quality, 3 demo products via the real route over the fixtures);
  run_vectors.mjs section 6: 2,028 checks pass. Mutations caught (drop e622 from POTASSIUM_BULK → 15 fail; drop the
  ß fold → 1 fail). tests/test_barcode_vectors.py (fresh file, DEMO_PRODUCTS block equal, coverage of every rule).
* Step 3 (mock): js/mock/barcode.js (POST /api/foods/barcode: model checks, normalise/classify 400s, local first,
  60/hour, consent, 3 recorded products, demo 404), mock foods v0.3 Food fields, gtin + ingredients_text on
  POST/PUT /api/foods and /api/log/quick with the additive scan, shared rows read-only/linked; demo env
  OFF_ENABLED=true (was false) so the samples answer after consent; Settings → Food data demo hint names the samples.
* tests/test_vendor.py restored (scan.js, the index.html ponyfill tag and sw.js entries exist now): passes.
* Steps 4–7 (scan.js, Quick add photo/ingredients/gtin, entry sheet provenance, offline.js + core.js KH.net hooks,
  badge, Today waiting entries + offline note, Settings → This device outbox, sign-out sheet, About data sources,
  admin Food data keys): built. tools/e2e/device.py (ports 8370 app / 8371 fake AI) verified in Chromium:
  `--only photo,native,live,outbox` all pass (photo WASM + native stand-in, fake camera y4m live scan on
  http://localhost incl. 4 s watchdog and plain-HTTP note, outbox: offline log + offline reload from the SW +
  reconnect synced once + refused item Retry/Discard + lost answer resent once ('existing') + sign-out sheet).
  Harness lesson: Playwright route handlers only run while Python is inside a Playwright call, so never
  time.sleep while a route must answer (use page.wait_for_timeout / wait_js).

## Decisions
* The offline food list is refreshed daily through `GET /api/foods?category=…` (≤ 200 per category) because the
  note 02 R5 route `GET /api/foods/builtin` (ETag) is server work outside this role; listed in docs/ROADMAP.md.
* Personal AI providers: the harness checks that only public presets are offered (custom addresses need the admin's
  `ai.allow_user_base_url`), rather than saving a private address.
* Additive scan twin in the browser (not in the contract's list before): Quick add shows what the server will flag
  before saving, and the demo stores the same flags as the server; kept in parity by vectors.
* js/engine/off.js holds the quality sentences and attribution constants (one file per Python module, as guidance).
* Demo: OFF "on" (env-locked) with three recorded products; consent still needed per person (shows the real flow).

* Step 8–11 (finished 2026-10-07):
  * Bugs found by the walks and fixed: syncNow() kept a settled promise after an early return (offline demo never
    synced again); the header badge covered the DEMO pill at 375 px (now the number on phones, full words in its
    aria-label); sign-out sheet and consent buttons were cut off at 375 px; 32–36 px summary/link targets at 1280;
    the badge's jump to Settings → This device lost its place while Settings loaded (now waits for the list and
    focuses its heading); new-tab links were dead in the preview's sandboxed frame (addresses shown as text there,
    wrapped at 320 px); key messages read "Saved, but The AI service…" (now the chosen service's name).
  * Offline: changes that cannot be queued (edits, deletes, profile) now say they need a connection (note 02 R5).
  * tools/e2e/device.py: 123 checks, all pass (photo WASM/native, fake-camera live scan + watchdog + plain-HTTP note,
    outbox incl. lost answer and sign-out, AI cards + label upload ≤1600 px without EXIF + activity + write-only
    personal key with no outside call (server proxy → 127.0.0.1:9), plate photo banner/unticked/planned, demo, walks
    demo + real server 375/1280 light/dark). Every photo picker's button is now 44 px.
  * tests/test_device_ui.py (22 static checks), device.py in tests/test_e2e_tools.py + tools/e2e/README.md.
  * parity.py section 13 (foods gtin/ingredients, POST /api/foods/barcode incl. reason/gtin/checked): full run
    6,497/6,497; mutation of a mock reason caught.
  * Preview built with scripts/build_preview.py into $S/preview; sandbox.py: 17 walks + 3 sweeps + probes, 0 issues.
  * regress.py on port 8375 with a clean tree: 469 passed, 0 failed. `python -m pytest` (3149 tests): passes;
    `node tests/js/run_vectors.mjs`: all sections pass (barcode 2,028); `scripts/vendor_barcode.py --check`: pins match.
  * Docs: ARCHITECTURE (module list, barcode "Frontend", "M2: the offline outbox"), docs/barcode-and-photos.md,
    install-on-your-phone.md (#offline), privacy.md (on-device data), ROADMAP (builtin ETag route, manual device
    checks, offline edits), handbook logging + barcode pages (mkdocs --strict builds).

## Reproduce
* `node tests/js/run_vectors.mjs` (barcode section 2,028 checks); `python3 scripts/vendor_barcode.py --check`
* `python3 tools/e2e/device.py --port 8370 --ai-port 8371 --out $S/dev [--only photo,native,live,outbox,ai,demo,shots]`
* `python3 tools/e2e/parity.py --port 8372 --static-port 8373 --out $S/parity [--sections 13]`
* `python3 scripts/build_preview.py --out $S/preview/kidney-diet-log.html && python3 tools/e2e/sandbox.py --preview $S/preview/kidney-diet-log.html --out $S/sandbox --port 8374`
* `python3 tools/e2e/regress.py --no-pytest --port 8375 --out $S/regress`; `python -m pytest`
