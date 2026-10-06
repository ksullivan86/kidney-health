Status: in progress

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
* tests/test_vendor.py is parked in $S/test_vendor.py.pending until js/scan.js, the index.html ponyfill tag and
  the sw.js entry exist (its last two tests check them); restore it then.

## Decisions
* Additive scan twin in the browser (not in the contract's list before): Quick add shows what the server will flag
  before saving, and the demo stores the same flags as the server; kept in parity by vectors.
* js/engine/off.js holds the quality sentences and attribution constants (one file per Python module, as guidance).
* Demo: OFF "on" (env-locked) with three recorded products; consent still needed per person (shows the real flow).

## Reproduce
(to be filled)
