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

## In progress

## Decisions (and why)

## Reproduce the checks
```
python -m pytest tests/test_gtin.py tests/test_additives.py tests/test_textclean.py -q
python3 tests/data/gen_rules_vectors.py --check && node tests/js/run_vectors.mjs
```
