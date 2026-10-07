"""The demo logs a product with only prepared values in servings, never grams, as the server does (v0.3.0 review C7).

An Open Food Facts product whose values are only "as prepared" has nutrients per serving as prepared but a serving
weight as sold (Kraft macaroni: 70.9 g dry makes a 198 g cup), so 198 g would count 2.8 servings, 140 g of
carbohydrate instead of 50. The server refuses grams for it (``app.foods.weight_known``, ``WEIGHT_UNKNOWN_DETAIL``;
``tests/test_barcode_api.py``); the demo (``js/mock/log.js``, ``js/mock/guidance.js`` over ``KH.off.weightKnown``)
must answer the same, and the entry sheet hides the grams field for such a food (``js/views/add.js``).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.foods import WEIGHT_UNKNOWN_CODES, WEIGHT_UNKNOWN_DETAIL

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "demo_api.mjs"
KRAFT = "0021000658831"  # recorded in js/mock/barcode.js: prepared values only
DAY = "2026-10-05"


def _demo(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo API (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(requests), capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_twin_knows_the_servers_codes_and_text() -> None:
    off_js = (ROOT / "app" / "static" / "js" / "engine" / "off.js").read_text(encoding="utf-8")
    codes = re.search(r"const WEIGHT_UNKNOWN_CODES = \[(.*?)\];", off_js)
    assert codes and set(re.findall(r"'(\w+)'", codes.group(1))) == set(WEIGHT_UNKNOWN_CODES)
    text = re.search(r'const WEIGHT_UNKNOWN_DETAIL = "(.*?)"\n\s*\+ \'(.*?)\';', off_js, re.S)
    assert text and (text.group(1) + text.group(2)) == WEIGHT_UNKNOWN_DETAIL


def test_the_demo_logs_a_prepared_only_product_in_servings_never_grams() -> None:
    kraft = {"$ref": [1, "food.id"]}
    answers = _demo([
        {"method": "PATCH", "path": "/api/me/settings", "body": {"food.off_consent": True}},
        {"method": "POST", "path": "/api/foods/barcode", "body": {"code": KRAFT}},
        {"method": "POST", "path": "/api/log", "body": {"date": DAY, "meal": "dinner", "food_id": kraft, "grams": 198}},
        {"method": "POST", "path": "/api/log", "body": {"date": DAY, "meal": "dinner", "food_id": kraft, "servings": 1}},
        {"method": "POST", "path": "/api/log/batch", "body": {"entries": [
            {"date": DAY, "meal": "lunch", "food_id": kraft, "grams": 100, "client_id": "00000000-0000-4000-8000-0000000000c7"}]}},
    ])
    assert answers[1]["ok"], answers[1]
    assert "prepared_values" in [q["code"] for q in answers[1]["body"]["food"]["quality"]]
    assert answers[2] == {"ok": False, "status": 400, "detail": WEIGHT_UNKNOWN_DETAIL}
    assert answers[3]["ok"] and answers[3]["body"]["grams"] is None and answers[3]["body"]["nutrients"]["carbs_g"] == 50
    assert answers[4] == {"ok": False, "status": 400, "detail": WEIGHT_UNKNOWN_DETAIL}  # no entries[i] prefix, as the server


def test_the_demo_refuses_grams_on_edit_and_in_swaps() -> None:
    first = _demo([
        {"method": "PATCH", "path": "/api/me/settings", "body": {"food.off_consent": True}},
        {"method": "POST", "path": "/api/foods/barcode", "body": {"code": KRAFT}},
    ])
    food_id = first[1]["body"]["food"]["id"]
    answers = _demo([
        {"method": "PATCH", "path": "/api/me/settings", "body": {"food.off_consent": True}},
        {"method": "POST", "path": "/api/foods/barcode", "body": {"code": KRAFT}},
        {"method": "PUT", "path": "/api/profile", "body": {"targets": {"potassium_mg": 2500, "phosphorus_mg": 1000,
                                                                       "sodium_mg": 2000, "carbs_per_meal_g": 60}}},
        {"method": "POST", "path": "/api/log", "body": {"date": DAY, "meal": "dinner", "food_id": food_id, "servings": 1}},
        {"method": "GET", "path": f"/api/guidance/swaps?food_id={food_id}&grams=198&meal=dinner&date={DAY}"},
        {"method": "GET", "path": f"/api/guidance/swaps?food_id={food_id}&servings=1&meal=dinner&date={DAY}"},
    ])
    assert answers[1]["body"]["food"]["id"] == food_id  # a fresh demo gives the scanned product the same id
    entry_id = answers[3]["body"]["id"]
    assert answers[4] == {"ok": False, "status": 400, "detail": WEIGHT_UNKNOWN_DETAIL}
    assert answers[5]["ok"], answers[5]
    edits = _demo([
        {"method": "PATCH", "path": "/api/me/settings", "body": {"food.off_consent": True}},
        {"method": "POST", "path": "/api/foods/barcode", "body": {"code": KRAFT}},
        {"method": "POST", "path": "/api/log", "body": {"date": DAY, "meal": "dinner", "food_id": food_id, "servings": 1}},
        {"method": "PUT", "path": f"/api/log/{entry_id}", "body": {"grams": 198}},
        {"method": "PUT", "path": f"/api/log/{entry_id}", "body": {"servings": 1.5}},
    ])
    assert edits[2]["body"]["id"] == entry_id
    assert edits[3] == {"ok": False, "status": 400, "detail": WEIGHT_UNKNOWN_DETAIL}
    assert edits[4]["ok"] and edits[4]["body"]["nutrients"]["carbs_g"] == 75


def test_the_entry_sheet_hides_grams_for_such_a_food() -> None:
    add_js = (ROOT / "app" / "static" / "js" / "views" / "add.js").read_text(encoding="utf-8")
    assert "function applyWeightRule(food)" in add_js and "entryGrams.closest('.field').hidden = !known;" in add_js
    assert add_js.count("applyWeightRule(") == 3  # the function, a new entry's food, an edited entry's food once loaded
    assert "Log it in servings: the values are for the product as prepared." in add_js
    assert "if (sheet.servingsOnly) return;" in add_js  # never fills grams from servings for it
