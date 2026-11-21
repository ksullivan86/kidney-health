"""Parity vectors for the browser twin of the USDA mapping (design note 38 §5.3, device mode).

tests/data/usda_vectors.json is generated from app/foods.py (map_usda_record, usda_search_item) by
tests/data/gen_usda_vectors.py and replayed against js/engine/usda.js by ``node tests/js/run_vectors.mjs`` (run by
tests/test_rules_vectors.py and by CI). These tests fail when the committed file no longer matches the Python side.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app import foods

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "usda_vectors.json"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_usda_vectors", ROOT / "tests" / "data" / "gen_usda_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_usda_vectors_are_current() -> None:
    gen = _generator()
    assert VECTORS.read_text(encoding="utf-8") == gen.dump(gen.build()), (
        "tests/data/usda_vectors.json is stale: app/foods.py or the recorded USDA fixtures changed. Run "
        "`python3 tests/data/gen_usda_vectors.py`, then `node tests/js/run_vectors.mjs`, and update js/engine/usda.js "
        "until both agree."
    )


def test_vectors_cover_each_kind_of_record() -> None:
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = doc["map_cases"]
    kinds = {json.loads(c["json"]).get("dataType") for c in cases if c["json"].startswith("{")}
    assert {"SR Legacy", "Foundation", "Branded"} <= kinds
    mapped = [c["mapped"] for c in cases if "mapped" in c]
    flags = {f for m in mapped for f in m["kwargs"]["flags"]}
    assert {"counts_as_fluid", "alcohol", "phosphate_additive", "potassium_additive", "avoid_ckd"} <= flags
    quality = {q for m in mapped for q in m["quality"]}
    assert quality == {"no_serving", "ml_as_g", "potassium_unknown", "phosphorus_unknown"}
    assert any(m["kwargs"]["name"].startswith("USDA food ") for m in mapped)
    assert any("error" in c for c in cases) and any("error" in c for c in doc["search_item_cases"])
    assert any(c.get("item") is None and "error" not in c for c in doc["search_item_cases"])
    assert sum(c["id"].startswith("fixture:") for c in cases) == 3


def test_search_route_uses_the_pure_item_mapping() -> None:
    # GET /api/foods/usda/search lists exactly what usda_search_item gives (the twin's reference).
    item = {"fdcId": 173944, "description": " Bananas, raw ", "dataType": "SR Legacy", "brandOwner": "",
            "brandName": "", "foodCategory": {"description": "Fruits and Fruit Juices"}}
    assert foods.usda_search_item(item) == {"fdc_id": 173944, "description": "Bananas, raw", "data_type": "SR Legacy",
                                            "brand": None, "category": "Fruits and Fruit Juices"}
    assert foods.usda_search_item({"description": "no id"}) is None
