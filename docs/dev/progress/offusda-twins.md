Status: complete (commit 6b210c9 on branch worktree-agent-adb01ff032e2aff20; not pushed, as asked)

# offusda-twins: JavaScript twins of the Open Food Facts and USDA mapping (design note 38 §5.3)

Task: browser twins of `app/off.py` `map_product` (+ `trim_product` and helpers) and `app/foods.py`
`map_usda_record` (+ the search item of `usda_search`), with parity vectors. No bridge, no mock routes, no Swift.

## Done (all verified with the commands below)
* `app/static/js/engine/off.js`: `KH.off.py` (Python reading of JSON: get, truthy, or, iter, float, int, str,
  repr, PyError), `finiteNumber`, `trimProduct`, `parseNutritionV35`, `isLiquid`, `mapProduct`, `foodKwargs`, `row`.
* `app/static/js/engine/usda.js` (new, `KH.usda`): `mapRecord`, `row`, `searchItem`, `categoryStr`; added to
  `app/static/index.html` (after off.js, before core.js) and `app/static/sw.js`.
* `app/static/js/engine/gtin.js`: `looseGtin14` (twin of `gtin.loose_gtin14`).
* `app/foods.py`: the search hit dict moved into pure `usda_search_item(item)`; the route calls it (same answers).
* Vectors: `off_map_cases` (197) in tests/data/barcode_vectors.json via tests/data/gen_barcode_vectors.py (own seeded
  stream, existing groups unchanged); tests/data/gen_usda_vectors.py → tests/data/usda_vectors.json (176 record cases,
  22 search item cases). tests/js/run_vectors.mjs replays both (barcode group + new "usda" group) and checks the demo's
  three DEMO_PRODUCTS rows equal the twin's row after the stored rounding.
* Tests: tests/test_usda_vectors.py (fresh file, coverage, route helper); tests/test_barcode_vectors.py gained a
  coverage test for off_map_cases.
* ARCHITECTURE.md: paragraph in the barcode "Parity" section.

## Commands
* `python tests/data/gen_barcode_vectors.py` and `python tests/data/gen_usda_vectors.py` (venv python)
* `node tests/js/run_vectors.mjs` → barcode 2580 checks, usda 372 checks, all pass
* `python -m pytest -q -p no:cacheprovider -o addopts="" tests/test_barcode_vectors.py tests/test_usda_vectors.py`
* Checked that breaking the twin (KJ factor, alcohol rule) makes the runner fail.

## Decisions
* Every case keeps its input as JSON text (what the iPhone app hands over; also allows 1e400).
* JSON.parse cannot tell 208 from 208.0: JS treats every whole number as a Python int. Vectors avoid float-valued
  whole numbers in fields the server turns into text. This is the one known gap.
* A Python exception (for example `foodPortions: 5`) is a case with `error`; the twin must throw KH.off.py.PyError.
* Rows are returned before the stored rounding; the demo's `_insertFood` rounds as `foods.stored_food_values`.
