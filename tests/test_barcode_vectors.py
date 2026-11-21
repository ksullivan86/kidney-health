"""Parity vectors for the browser barcode twins (ARCHITECTURE.md "Frontend modules", "M2 API: barcode").

tests/data/barcode_vectors.json is generated from app/gtin.py, app/textclean.py, app/additives.py, app/off.py
and the barcode route by tests/data/gen_barcode_vectors.py, and replayed against js/engine/{gtin,textclean,
additives,off}.js and the demo's POST /api/foods/barcode by ``node tests/js/run_vectors.mjs`` (run by
tests/test_rules_vectors.py and by CI). These tests fail when the committed file no longer matches the Python
side, and when the three products embedded in js/mock/barcode.js differ from the generated rows.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from app import off

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "barcode_vectors.json"
MOCK = ROOT / "app" / "static" / "js" / "mock" / "barcode.js"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_barcode_vectors", ROOT / "tests" / "data" / "gen_barcode_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_barcode_vectors_are_current() -> None:
    gen = _generator()
    assert VECTORS.read_text(encoding="utf-8") == gen.dump(gen.build()), (
        "tests/data/barcode_vectors.json is stale: app/gtin.py, app/textclean.py, app/additives.py, app/off.py or the "
        "recorded fixtures changed. Run `python3 tests/data/gen_barcode_vectors.py`, then `node tests/js/run_vectors.mjs`, "
        "and update the twins in app/static/js/engine/ (and the DEMO_PRODUCTS block of js/mock/barcode.js) until both agree."
    )


def test_demo_products_block_equals_the_generated_rows() -> None:
    text = MOCK.read_text(encoding="utf-8")
    m = re.search(r"/\* DEMO_PRODUCTS:BEGIN[^*]*\*/\s*const DEMO_PRODUCTS = (\[.*?\]);\s*/\* DEMO_PRODUCTS:END \*/", text, re.S)
    assert m, "js/mock/barcode.js lost its DEMO_PRODUCTS markers"
    embedded = json.loads(m.group(1))
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert embedded == [{k: p[k] for k in ("fixture", "code", "format", "row")} for p in doc["demo_products"]]


def test_vectors_cover_every_rule_the_twins_implement() -> None:
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    reasons = {c["error"]["reason"] for c in doc["gtin_cases"] if "error" in c}
    classes = {c["classify"] for c in doc["gtin_cases"] if "classify" in c}
    assert reasons == {"format", "check_digit"}
    assert classes == {"retail", "restricted", "isbn", "issn", "coupon", "reserved"}
    assert any(c["format"] == "upc_e" and c.get("normalize") == "00012345000065" for c in doc["gtin_cases"])
    flags = {f for c in doc["additive_cases"] for f in c["result"]["flags"]}
    kinds = {f["kind"] for c in doc["additive_cases"] for f in c["result"]["findings"]}
    sources = {f["source"] for c in doc["additive_cases"] for f in c["result"]["findings"]}
    assert flags == {"phosphate_additive", "potassium_additive", "avoid_ckd"}
    assert kinds == {"phosphate", "phosphate_trace", "potassium", "potassium_trace"}
    assert sources == {"tag", "text", "name"}
    # invisible characters must not hide an additive (note 03 §9 B3): the zero-width cases still flag
    hidden = [c for c in doc["additive_cases"] if c["text"] == "sodium phos\u200bphate"]
    assert hidden and all("phosphate_additive" in c["result"]["flags"] for c in hidden)
    assert {p["fixture"] for p in doc["demo_products"]} == {"diet_coke_v3.4", "kraft_mac_cheese_v3.4", "nutella_v3.4"}
    for p in doc["demo_products"]:
        assert p["result"]["attribution"]["license"] == "ODbL-1.0"
        assert p["result"]["attribution"]["url"].startswith("https://world.openfoodfacts.org/product/")


def test_off_mapping_vectors_cover_every_quality_code() -> None:
    # Device mode (design note 38 §5.3): js/engine/off.js maps raw Open Food Facts answers itself.
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = doc["off_map_cases"]
    mapped = [c["mapped"] for c in cases if "mapped" in c]
    codes = {q.split(":")[0] for m in mapped for q in m["quality"]}
    assert codes == set(off.QUALITY_MESSAGES) - {"filled_from_usda", "filled_from_off"}
    assert {m["status"] for m in mapped} == {"found", "no_nutrition"}
    flags = {f for m in mapped for f in m["flags"]}
    assert {"counts_as_fluid", "processed", "high_gi", "alcohol", "phosphate_additive", "avoid_ckd"} <= flags
    fixtures = {c["id"] for c in cases if c["id"].startswith("fixture:")}
    assert {f"fixture:{name}" for name in ("diet_coke_v3.4", "kraft_mac_cheese_v3.4", "nutella_v3.4", "nutella_v3.6")} <= fixtures
    assert all("row" in c for c in cases if c.get("mapped", {}).get("status") == "found")
