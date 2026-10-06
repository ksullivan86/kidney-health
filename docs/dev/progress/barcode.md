Status: in progress

# barcode (M2): barcode lookup, Open Food Facts, USDA branded, potassium_additive

Spec: docs/dev/research/03-barcode-and-photo.md R1–R6, R10, R11, §6 checklist, §9 security review
(incl. §9.3; overrides earlier text) + ARCHITECTURE.md v0.3 items 8 (OFF off by default) and 9
(`potassium_additive` = MEDIUM when potassium is unknown, normal thresholds when listed).
Not mine: photo/vision routes, `app/imagecheck.py` (AI builder), `app/static/**` except
`app/static/js/engine/rules.js`. Ports 8340–8349.
Scratch: /tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/v030/barcode/

## Plan (sub-steps)
1. Pure modules: `app/textclean.py` (§9 B3), `app/gtin.py` (R2), `app/additives.py` (R5) + tests
2. `app/nutrients.py`: FOOD_SOURCES += off, FLAGS += potassium_additive, warning rule (item 9);
   `rules.js` twin; regenerate `tests/data/rules_vectors.json` (+ generator cases); curated FLAGS
3. Fixtures: record real OFF v3.4/v3.6/404 + USDA branded responses (`scripts/record_barcode_fixtures.py`)
4. `app/off.py`: request, UA, caps (decoded bytes), pacing bucket, 503 retry, mapping, quality, v3.5 parser
5. Schema step `m007_barcode.py` (needs m006 from the AI builder first: numbering must stay contiguous)
6. `app/foods.py` gtin/source fields, USDA branded-by-barcode; `app/barcode.py` router; settings keys
7. gtin on FoodCreate / quick add / copy; CSV `source`, `source_license`; export
8. Tests per R12 + §9 (isolation, transport spy, oracle, caps, CSV, invisible chars)
9. Docs: docs/barcode-and-photos.md, ARCHITECTURE "M2 API: barcode", network allowlist, fact-check,
   ROADMAP items, live smoke on 8340

## Done (and how verified)
* Step 1: `app/textclean.py` (NFKC, Cf/Cc/Cs removal, whitespace, cap; idempotent), `app/gtin.py`
  (normalize/classify/off_code/usda_candidates/loose_gtin14, UPC-E all 4 cases, GS1-8 prefixes),
  `app/additives.py` (E tiers, tag sub-codes, text scan in en/de/nl/fr/es/it/pt, trace notes, KCl first →
  avoid_ckd, salt-substitute names). Tests: tests/test_textclean.py, tests/test_gtin.py, tests/test_additives.py.

* Step 2: `nutrients.py` FOOD_SOURCES += off, FLAGS += potassium_additive, rule in food_warnings (unknown
  or non-finite potassium → medium, flag potassium_additive, "Contains a potassium additive; potassium not
  listed"; listed → normal thresholds), `_fmt` no longer crashes on NaN; `rules.js` twin (FLAGS entry,
  POTASSIUM_ADDITIVE_MESSAGE); `gen_rules_vectors.py` extra flag sets + a second seeded sample;
  `rules_vectors.json` regenerated (5721 JS checks pass); curated FLAGS. Tests: tests/test_potassium_additive.py.
  Note: `node tests/js/run_vectors.mjs` still fails on the *settings* vectors (settings.js lacks the targets
  and guidance keys; frontend-owned, pre-existing).

* Step 3–4 (part): `app/egress.py` (SSRF-checked transport: resolve at request time, check every
  address incl. IPv4-in-IPv6, deny metadata/link-local/reserved/k8s API, private only for an operator host,
  pin IP + Host + SNI, env HTTPS_PROXY honoured; `read_capped` counts decoded bytes); `app/off.py` (request
  builder, OffClient with 503 retry/429/redirect/HTML/oversize handling, TokenBucket, trim_product,
  parse_nutrition_v35, map_product with quality codes, quality_items). Fixtures recorded 2026-10-06:
  tests/fixtures/off/*.json (real, via proxy); tests/fixtures/usda: rate_limited.json real API 429 for DEMO_KEY,
  search_*/food_* from the FDC web app endpoints (provenance in README). Tests: tests/test_egress.py,
  tests/test_off_mapping.py (helpers: tests/barcode_support.py). Recorder: scripts/record_barcode_fixtures.py.

* foods.py (committed d01663f): usda_client through egress, `_usda_fetch` (2 MiB decoded cap, JSON only,
  UsdaError), `map_usda_record` (labelNutrients incl. "postassium", cleaned text, additive scan, mL servings),
  `usda_find_by_gtin` (≤3 searches, exact gtinUpc). Tests: tests/test_usda_branded.py.

* Docs and checks (commits e554193, 70a9f77, 18cc31a): docs/barcode-and-photos.md (barcode part + "Photos"
  section left for the AI builder), docs/research/fact-check.md §5 (potassium-additive rule: Parpia 2018,
  Sherman 2009, Picard 2019, KDIGO 2024 Fig 33), docs/ROADMAP.md barcode items (dietitian sign-off of the
  medium level, OFF API 3.5+ move, OFF dump, Tesseract, server zxing, OFF usage form), docs/network-allowlist.md
  rows (USDA branded + world.openfoodfacts.org), handbook app/barcode-and-photo.md + self-hosting/configuration.md
  (strict mkdocs build passed), scripts/check_off_live.py (0 problems against live and staging) and the weekly
  warn-only .github/workflows/off-live-check.yml (actionlint + zizmor clean), §9.3 guard test (product text never
  reaches AI prompts; tests/test_off_mapping.py). k8s NetworkPolicy / Cilium already list world.openfoodfacts.org.

## Schema step 7 and the route (ported 2026-10-06 18:45 UTC, after the AI builder committed m006 in 671ca1d)
* Ported from the local branch `barcode-m007-pending` (rebased on 11a35e9; `git apply` of
  `git diff HEAD...barcode-m007-pending`, working tree only, no conflicts; the LOCAL STUB m006 of the scratch
  clone was never copied). Contents: m007 (foods gtin/source_url/source_license/retrieved_at/ingredients_text/
  additives_json/quality_json, barcode_cache), app/barcode.py (POST /api/foods/barcode, cache, chain, merge, store,
  link, refresh, remap), Provenance + custom-food additive scan in app/foods.py, BarcodeLookup/BarcodeResult/Food
  fields in app/models.py, quick add gtin/ingredients + CSV source/source_license (app/log.py), export
  foods.csv/README (app/account.py), 4 food.* keys (app/settings_registry.py), OFF_BASE_URL (app/config.py),
  remap-barcodes and purge-barcode-cache (app/admin.py), router (app/main.py); tests test_barcode_api.py (~40),
  test_migration_m007.py, test_barcode_settings.py, isolation + CSV header updates; settings vectors carry a
  string key's `pattern` (gen_settings_vectors.py). ARCHITECTURE.md: "M2 API: barcode", potassium row of the
  thresholds table, Flags paragraph, Food fields line.
* Verified in the main tree with the AI builder's real m006: `python -m pytest` exit 0 with the two settings-twin
  tests deselected (they fail only on settings.js, below); `gen_settings_vectors.py --check` current.

## Handoffs
* **Frontend (settings.js; I may not edit it):** `test_settings_ui.py::test_engine_registry_lists_every_server_key`
  and the settings part of `node tests/js/run_vectors.mjs` fail until `app/static/js/engine/settings.js` has the
  4 new keys (plus the guidance keys from guidance.md). Paste after the `food.off_enabled` DEFS entry:
  ```js
      { key: 'food.barcode_negative_ttl_hours', type: 'int', min: 1, max: 720, default: 24, scope: 'instance', env: 'BARCODE_NEGATIVE_TTL_HOURS',
        label: 'Remember barcodes that were not found for (hours)',
        help: 'A barcode that Open Food Facts or USDA did not know is not asked again for this long.' },
      { key: 'food.off_contact', type: 'str', minLength: 3, maxLength: 200, pattern: '^[\\x20-\\x27\\x2a-\\x5b\\x5d-\\x7e]+$',
        default: 'https://github.com/ksullivan86/kidney-health', scope: 'instance', env: 'OFF_CONTACT',
        label: 'Contact sent to Open Food Facts',
        help: 'Goes into the User-Agent of every lookup, as Open Food Facts asks of API users. An admin email address is better than '
          + 'the default project address. Letters, digits and punctuation only (no round brackets or backslash).' },
      { key: 'food.off_rate_per_minute', type: 'int', min: 1, max: 15, default: 10, scope: 'instance', env: 'OFF_RATE_PER_MINUTE',
        label: 'Open Food Facts lookups per minute (whole server)',
        help: 'Open Food Facts allows 15 product lookups a minute from one address and may block an address that sends more. '
          + 'Everyone on this server shares this budget; products already looked up do not count.' },
      { key: 'food.usda_branded_barcode', type: 'bool', default: true, scope: 'instance', env: 'USDA_BRANDED_BARCODE',
        label: 'Also look barcodes up in USDA FoodData Central',
        help: "Uses the person's USDA key or the shared one, when Open Food Facts does not know a product, has no nutrition facts "
          + 'for it, or lacks potassium or sodium for a US product.' },
  ```
  and in `validate()`, `case 'str'`, after the maxLength check:
  ```js
          if (def.pattern != null && !new RegExp(def.pattern).test(v)) return { error: `String should match pattern '${def.pattern}'` };
  ```
  (checked in the clone: with these lines no `food.*` vector fails; the vectors now carry `pattern` and 9 pattern cases).
* **Frontend device (scan.js, About page):** R11 attribution under the product name and on the About page; build the
  product link only from `attribution.url` when it starts with `https://`; show `quality[].message` and "not listed"
  for `null` potassium/phosphorus; 404 → Quick add with `gtin` and `name`; consent switch `food.off_consent`.
* **AI builder:** label/plate photo text that the model reads must go through `app.textclean.clean_text`; never put
  `ingredients_text`, product names or other provider text into a prompt as instructions (§9.3; guarded by
  `tests/test_off_mapping.py::test_product_text_never_reaches_an_ai_prompt_unmarked`).
* **M3 integration (README, §6 item 18):** feature list line for barcode lookups (Open Food Facts opt-in, USDA
  branded), configuration rows for OFF_ENABLED, OFF_CONTACT, OFF_RATE_PER_MINUTE, BARCODE_NEGATIVE_TTL_HOURS,
  USDA_BRANDED_BARCODE and OFF_BASE_URL (env only), and README line 169 "(and, later, Open Food Facts or AI)".

## Incident to report (Open Food Facts)
* While verifying the "add a product" URL on 2026-10-06 a manual GET of
  `https://world.openfoodfacts.org/cgi/product.pl?type=search_or_add&action=process&code=0099999999990` created an
  empty anonymous product 0099999999990 (en:empty) on Open Food Facts. The recorded 404 fixture predates it.
  It needs deletion by an OFF moderator (report via the OFF Slack #moderation or contact@openfoodfacts.org).
  The app itself only links to `action=display`, which does not create anything.

## Decisions (and why)
* No shared SSRF transport existed (note 04's app/ai/transport.py is the AI builder's and AI-specific), so
  `app/egress.py` is a small generic one for fixed operator-set hosts; `usda_client()` uses it too.
* `food.off_consent` (user, M1) is honoured: OFF is contacted only when the instance switch is on AND the
  person consented. Shared off/usda rows matched by GTIN are returned only when the person could have
  fetched them now or already linked them (no cross-user oracle, §9 B7).
* Quality codes may carry a nutrient: `implausible:<key>`, `filled_from_<src>:<key>` (stored in quality_json).
* OFF "add product" link verified 2026-10-06: `cgi/product.pl?type=search_or_add&action=display&code=` (the
  spec's `type=add` is 404). FDC food pages have no stable public URL, so USDA attribution links to fdc.nal.usda.gov.
* m007 waits for m006 (AI builder): discover() refuses a gap, so committing m007 first would break every start.

## Reproduce the checks
```
python -m pytest tests/test_gtin.py tests/test_additives.py tests/test_textclean.py -q
python3 tests/data/gen_rules_vectors.py --check && node tests/js/run_vectors.mjs
```
