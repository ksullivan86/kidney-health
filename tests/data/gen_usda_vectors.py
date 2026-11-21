#!/usr/bin/env python3
"""Generate tests/data/usda_vectors.json: parity vectors for the browser twin of the USDA mapping.

    python3 tests/data/gen_usda_vectors.py           # rewrite the file
    python3 tests/data/gen_usda_vectors.py --check   # exit 1 when the committed file is stale

In device mode (design note 38 §5.3) the page has no server and maps FoodData Central's raw JSON itself, with
``js/engine/usda.js``. This file is produced by the server's own code and replayed by ``node tests/js/run_vectors.mjs``:

* ``map_cases``: ``app.foods.map_usda_record`` (the ``UsdaMapped`` fields) and the row an import stores
  (the kwargs plus ``foods.usda_provenance``, without the time), against ``KH.usda.mapRecord`` and ``KH.usda.row``:
  the recorded Branded records (as fetched and as the barcode cache trims them), hand-made SR Legacy, Foundation
  and Branded records with edge cases, and seeded variants of the recorded ones. A case with ``error`` is one the
  server refuses with an exception; the twin must throw too.
* ``search_item_cases``: ``app.foods.usda_search_item`` (one hit of ``GET /api/foods/usda/search``) over every
  recorded search answer and hand-made hits, against ``KH.usda.searchItem``.

Each input is kept as JSON text, as the iPhone app hands it to the page. JavaScript reads ``208.0`` as ``208``, so
no case puts a whole number written as a float where the server turns it into text (js/engine/off.js explains).
Deterministic (seeded); no network.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "usda_vectors.json"
FIXTURES = ROOT / "tests" / "fixtures" / "usda"
sys.path.insert(0, str(ROOT))

from app import foods  # noqa: E402

SEED = 20261121


def _nutrient(number: str, nid: int, amount: object, key: str = "amount") -> dict:
    return {"nutrient": {"id": nid, "number": number, "name": f"n{number}"}, key: amount}


SR_BANANA = {
    "dataType": "SR Legacy", "description": "Bananas, raw", "foodCategory": {"description": "Fruits and Fruit Juices"},
    "foodNutrients": [_nutrient("208", 1008, 89), _nutrient("203", 1003, 1.09), _nutrient("204", 1004, 0.33),
                      _nutrient("205", 1005, 22.84), _nutrient("291", 1079, 2.6), _nutrient("269", 2000, 12.23),
                      _nutrient("307", 1093, 1), _nutrient("306", 1092, 358), _nutrient("305", 1091, 22),
                      _nutrient("301", 1087, 5), _nutrient("255", 1051, 74.91), _nutrient("606", 1258, 0.112)],
    "foodPortions": [{"amount": 1, "modifier": "medium (7\" to 7-7/8\" long)", "gramWeight": 118,
                      "measureUnit": {"name": "undetermined"}},
                     {"amount": 1, "modifier": "cup, mashed", "gramWeight": 225, "measureUnit": {"name": "undetermined"}}],
}
FOUNDATION_MILK = {
    "dataType": "Foundation", "description": "Milk, whole, 3.25% milkfat, with added vitamin D",
    "foodCategory": {"description": "Dairy and Egg Products"},
    "foodNutrients": [{"nutrient": {"id": 1008, "number": "208"}, "amount": 61.5}, {"nutrient": {"id": 1003, "number": "203"}, "amount": 3.27},
                      {"nutrient": {"id": 1004, "number": "204"}, "amount": 3.2}, {"nutrient": {"id": 1092, "number": "306"}, "amount": 150},
                      {"nutrient": {"id": 1091, "number": "305"}, "amount": 101}, {"nutrient": {"id": 1093, "number": "307"}, "amount": 38},
                      {"nutrient": {"id": 1051, "number": "255"}, "amount": 88.1}],
    "foodPortions": [{"amount": 1, "gramWeight": 249, "measureUnit": {"name": "cup"}, "portionDescription": "1 cup"}],
}
BRANDED_SODA = {
    "dataType": "Branded", "description": "COLA", "brandOwner": "Acme Drinks", "brandedFoodCategory": "Soda",
    "gtinUpc": "049000028911", "ingredients": "CARBONATED WATER, PHOSPHORIC ACID, POTASSIUM BENZOATE",
    "servingSize": 355, "servingSizeUnit": "MLT", "householdServingFullText": "1 can",
    "foodNutrients": [{"nutrientNumber": "208", "value": 42}, {"nutrientNumber": "307", "value": 11}],
    "labelNutrients": {"calories": {"value": 150}, "sodium": {"value": 40}, "potassium": {"value": 0}, "postassium": {"value": 5}},
}


def _with(base: dict, **changes: object) -> dict:
    out = json.loads(json.dumps(base))
    for key, value in changes.items():
        if value is ...:
            out.pop(key, None)
        else:
            out[key] = value
    return out


MAP_HAND: list[tuple[str, int, object]] = [  # (id, fdc_id, record: a dict or raw JSON text)
    ("sr_legacy_banana", 173944, SR_BANANA),
    ("foundation_milk", 746782, FOUNDATION_MILK),
    ("branded_soda_ml", 1000001, BRANDED_SODA),
    ("empty", 1, {}),
    ("missing_description", 2, _with(SR_BANANA, description=...)),
    ("blank_description", 3, _with(SR_BANANA, description="  ​ ")),
    ("long_text", 4, {"description": "Very long name " * 30, "brandOwner": "Owner " * 50, "ingredients": "water, " * 700 + "sodium phosphate",
                      "foodCategory": "Category " * 20}),
    ("no_nutrients_branded", 5, _with(BRANDED_SODA, foodNutrients=[], labelNutrients=...)),
    ("alcohol_by_nutrient", 6, {"description": "Beer, regular", "foodCategory": {"description": "Beverages"},
                                "foodNutrients": [_nutrient("221", 1018, 3.9), _nutrient("208", 1008, 43), _nutrient("221", 1018, 0)]}),
    ("alcohol_low", 7, {"description": "Beer, non-alcoholic", "foodNutrients": [_nutrient("221", 1018, 0.3)]}),
    ("alcohol_missing_amount_then_value", 8, {"description": "x", "foodNutrients": [_nutrient("221", 1018, None), _nutrient("221", 1018, 1)]}),
    ("alcohol_by_name", 9, {"description": "Alcoholic beverage, wine, table, red"}),
    ("nutrient_ids_only", 10, {"description": "x", "foodNutrients": [{"nutrientId": 1008, "value": 100}, {"nutrientId": "1092", "amount": "250"},
                                                                    {"nutrient": {"id": 1091}, "amount": 80}]}),
    ("duplicate_numbers_first_wins", 11, {"description": "x", "foodNutrients": [_nutrient("208", 1008, None), _nutrient("208", 1008, 50),
                                                                               _nutrient("208", 1008, 70)]}),
    ("amount_null_value_set", 12, {"description": "x", "foodNutrients": [{"nutrientNumber": "208", "amount": None, "value": 99}]}),
    ("bad_amounts", 13, '{"description": "x", "foodNutrients": [{"nutrientNumber": "208", "amount": -5}, '
                        '{"nutrientNumber": "203", "amount": "12.5"}, {"nutrientNumber": "204", "amount": "abc"}, '
                        '{"nutrientNumber": "205", "amount": "inf"}, {"nutrientNumber": "306", "amount": 1e400}, '
                        '{"nutrientNumber": "305", "amount": true}, {"nutrientNumber": "307", "amount": " 1_5 "}, '
                        '{"nutrientNumber": "301", "amount": [1]}, {"nutrientNumber": "291", "amount": "-0"}, '
                        '{"nutrientNumber": "269", "amount": "\\u0661\\u0662"}, 5, null, "208"]}'),
    ("portion_edges", 14, {"description": "x", "foodNutrients": [_nutrient("208", 1008, 100)], "foodPortions": [
        "not a portion", {"gramWeight": 0, "amount": 1}, {"gramWeight": 200000}, {"gramWeight": "abc"},
        {"gramWeight": 30.5, "amount": "abc", "measureUnit": {"name": "tbsp"}, "modifier": "TBSP"}]}),
    ("portion_description", 15, {"description": "x", "foodPortions": [{"gramWeight": 42, "amount": 2, "measureUnit": {"name": "undetermined"},
                                                                      "portionDescription": "2 slices"}]}),
    ("portion_quantity_not_specified", 16, {"description": "x", "foodPortions": [
        {"gramWeight": 42, "measureUnit": {"name": "undetermined"}, "portionDescription": "Quantity not specified"}]}),
    ("portion_amount_fraction", 17, {"description": "x", "foodPortions": [{"gramWeight": 10000.25, "amount": 0.333333333,
                                                                         "measureUnit": "cup", "modifier": "chopped"}]}),
    ("portion_true_amount", 18, {"description": "x", "foodPortions": [{"gramWeight": 15, "amount": True, "measureUnit": {"name": "Tbsp"}}]}),
    ("portions_not_a_list", 19, {"description": "x", "foodPortions": {"a": 1}, "servingSize": 30, "servingSizeUnit": "g"}),
    ("portions_text", 20, {"description": "x", "foodPortions": "1 cup"}),
    ("portions_number", 21, {"description": "x", "foodPortions": 5}),
    ("nutrients_number", 22, {"description": "x", "foodNutrients": 7}),
    ("serving_ounces", 23, {"description": "x", "servingSize": 2, "servingSizeUnit": "oz", "foodNutrients": [_nutrient("208", 1008, 100)]}),
    ("serving_grm_household", 24, {"description": "x", "servingSize": "28.35", "servingSizeUnit": "GRM", "householdServingFullText": "1 oz",
                                   "foodNutrients": [_nutrient("208", 1008, 500), _nutrient("306", 1092, 1200)]}),
    ("serving_zero", 25, {"description": "x", "servingSize": 0, "servingSizeUnit": "g"}),
    ("serving_huge", 26, {"description": "x", "servingSize": 100001, "servingSizeUnit": "g"}),
    ("labels_with_portions_ignored", 27, _with(BRANDED_SODA, foodPortions=[{"gramWeight": 240, "amount": 1, "measureUnit": {"name": "cup"}}])),
    ("labels_bare_numbers", 28, _with(BRANDED_SODA, labelNutrients={"calories": 100, "protein": "2", "fat": -1, "saturatedFat": None,
                                                                    "fiber": {"value": "x"}, "sugars": {"amount": 3}, "calcium": {"value": 20}})),
    ("labels_not_a_dict", 29, _with(BRANDED_SODA, labelNutrients=[1, 2])),
    ("water_beverage", 30, {"description": "Juice, apple", "foodCategory": {"description": "Beverages"},
                            "foodNutrients": [_nutrient("255", 1051, 88)], "foodPortions": [{"gramWeight": 248, "amount": 1, "measureUnit": {"name": "cup"}}]}),
    ("beverage_word", 31, {"description": "Drink", "brandedFoodCategory": "Soda & Other Beverages", "servingSize": 240, "servingSizeUnit": "g"}),
    ("category_name_key", 32, {"description": "x", "foodCategory": {"name": "Snacks"}}),
    ("category_unmapped", 33, {"description": "x", "foodCategory": {"description": "  Baby Foods  "}}),
    ("category_empty_dict", 34, {"description": "x", "foodCategory": {}, "brandedFoodCategory": "Cereal"}),
    ("category_number", 35, {"description": "x", "foodCategory": 12}),
    ("category_list", 36, {"description": "x", "foodCategory": ["Fruits", "it's \"odd\""]}),
    ("category_constructor", 37, {"description": "x", "foodCategory": "constructor"}),
    ("brand_name_only", 38, {"description": "x", "brandOwner": "", "brandName": "Lay's"}),
    ("gtin_int", 39, {"description": "x", "gtinUpc": 49000028911}),
    ("gtin_spaced", 40, {"description": "x", "gtinUpc": "0 49000 02891-1"}),
    ("gtin_too_long", 41, {"description": "x", "gtinUpc": "123456789012345"}),
    ("gtin_letters", 42, {"description": "x", "gtinUpc": "04900002891a"}),
    ("phosphate_ingredients", 43, {"description": "Ham", "ingredients": "PORK, WATER, SODIUM TRIPOLYPHOSPHATE, POTASSIUM LACTATE"}),
    ("salt_substitute", 44, {"description": "NoSalt Original", "ingredients": "potassium chloride",
                             "foodNutrients": [_nutrient("306", 1092, 50000), _nutrient("305", 1091, 0)]}),
    ("invisible_text", 45, {"description": "Cola​­ Zero", "brandOwner": "‮Acme", "ingredients": "sodium phos​phate"}),
    ("not_a_dict_nutrient", 46, {"description": "x", "foodNutrients": [{"nutrient": "208", "nutrientNumber": 208, "value": 77}]}),
    ("number_as_int_nutrient", 47, {"description": "x", "foodNutrients": [{"nutrient": {"number": 307}, "amount": 400}]}),
]

SEARCH_HAND: list[tuple[str, object]] = [
    ("full", {"fdcId": 173944, "description": "Bananas, raw", "dataType": "SR Legacy", "foodCategory": "Fruits and Fruit Juices"}),
    ("no_id", {"description": "x"}),
    ("null_id", {"fdcId": None, "description": "x"}),
    ("text_id", {"fdcId": " 12 ", "description": "x"}),
    ("fraction_id", {"fdcId": 12.7}),
    ("bad_id", {"fdcId": "abc"}),
    ("list_id", {"fdcId": [1]}),
    ("true_id", {"fdcId": True}),
    ("zero_id", {"fdcId": 0, "description": ""}),
    ("blank_description", {"fdcId": 5, "description": "   "}),
    ("description_number", {"fdcId": 5, "description": 42}),
    ("description_list", {"fdcId": 5, "description": ["a", "b's"]}),
    ("brand_name_only", {"fdcId": 5, "brandOwner": "", "brandName": "Lay's"}),
    ("brand_neither", {"fdcId": 5, "brandOwner": "", "brandName": ""}),
    ("brand_number", {"fdcId": 5, "brandOwner": 7}),
    ("category_dict", {"fdcId": 5, "foodCategory": {"description": "Snacks", "id": 3}}),
    ("category_dict_name", {"fdcId": 5, "foodCategory": {"name": " Dairy "}}),
    ("category_blank", {"fdcId": 5, "foodCategory": "  "}),
    ("data_type_number", {"fdcId": 5, "dataType": 3}),
]

NUMBER_FORMS = [lambda v: v, lambda v: str(v), lambda v: f" {v} ", lambda v: "abc", lambda v: None, lambda v: -v if v else -1,
                lambda v: v * 1000, lambda v: "NaN"]


def _mutate(rng: random.Random, record: dict) -> dict:
    r = json.loads(json.dumps(record))
    items = r.get("foodNutrients") if isinstance(r.get("foodNutrients"), list) else []
    kept = []
    for item in items:
        if rng.random() < 0.2:
            continue
        if rng.random() < 0.2 and isinstance(item, dict):
            key = "amount" if "amount" in item else "value"
            if isinstance(item.get(key), (int, float)) and not isinstance(item.get(key), bool):
                item[key] = rng.choice(NUMBER_FORMS)(item[key])
        kept.append(item)
    r["foodNutrients"] = kept
    if rng.random() < 0.3:
        r["servingSize"] = rng.choice([None, 0, 28.5, "30", 240, 200000, -1])
    if rng.random() < 0.3:
        r["servingSizeUnit"] = rng.choice(["g", "GRM", "ml", "MLT", "oz", None, ""])
    if rng.random() < 0.2:
        r.pop("labelNutrients", None)
    elif rng.random() < 0.2 and isinstance(r.get("labelNutrients"), dict):
        for key in list(r["labelNutrients"]):
            if rng.random() < 0.4:
                del r["labelNutrients"][key]
    if rng.random() < 0.2:
        r["description"] = rng.choice([None, "", "Alcoholic beverage, beer", "x" * 250])
    if rng.random() < 0.2:
        r["brandedFoodCategory"] = rng.choice(["Soda", "Beverages", "Chips, Pretzels & Snacks", None, {"description": "Sweets"}])
    if rng.random() < 0.2:
        r["foodPortions"] = rng.choice([[], [{"gramWeight": 30, "amount": 1, "measureUnit": {"name": "oz"}}], None])
    if rng.random() < 0.2:
        r["gtinUpc"] = rng.choice(["028400421584", 28400421584, "", None, "0 2840 0421 584"])
    return r


def _map_case(case_id: str, fdc_id: int, text: str) -> dict:
    case: dict = {"id": case_id, "fdc_id": fdc_id, "json": text}
    try:
        mapped = foods.map_usda_record(json.loads(text), fdc_id)
    except Exception as exc:  # the twin must fail where the server fails
        case["error"] = type(exc).__name__
        return case
    case["mapped"] = {"kwargs": mapped.kwargs, "gtin14": mapped.gtin14, "ingredients_text": mapped.ingredients_text,
                      "additives": mapped.additives, "quality": mapped.quality}
    p = foods.usda_provenance(mapped, retrieved_at="-")
    case["row"] = {**mapped.kwargs, "source": "usda", "fdc_id": fdc_id, "gtin": p.gtin, "source_url": p.source_url,
                   "source_license": p.source_license, "ingredients_text": p.ingredients_text, "additives": list(p.additives),
                   "quality": list(p.quality)}
    return case


def _search_case(case_id: str, text: str) -> dict:
    case: dict = {"id": case_id, "json": text}
    try:
        case["item"] = foods.usda_search_item(json.loads(text))
    except Exception as exc:
        case["error"] = type(exc).__name__
    return case


def _dumps(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def build() -> dict:
    from app.barcode import _trim_usda_record

    rng = random.Random(SEED)
    map_cases = []
    recorded = []
    for path in sorted(FIXTURES.glob("food_*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))["body"]
        fdc_id = int(path.stem.split("_")[1])
        recorded.append((path.stem, fdc_id, record))
        map_cases.append(_map_case(f"fixture:{path.stem}", fdc_id, _dumps(record)))
        map_cases.append(_map_case(f"fixture-trimmed:{path.stem}", fdc_id, _dumps(_trim_usda_record(record))))
    for case_id, fdc_id, record in MAP_HAND:
        map_cases.append(_map_case(case_id, fdc_id, _dumps(record)))
    for n in range(120):
        stem, fdc_id, record = rng.choice(recorded)
        map_cases.append(_map_case(f"variant:{n}:{stem}", fdc_id, _dumps(_mutate(rng, record))))

    search_cases = []
    for path in sorted(FIXTURES.glob("search_*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))["body"]
        for n, item in enumerate(body.get("foods") or []):
            search_cases.append(_search_case(f"fixture:{path.stem}:{n}", _dumps(item)))
    for case_id, item in SEARCH_HAND:
        search_cases.append(_search_case(case_id, _dumps(item)))
    return {
        "about": "Generated by tests/data/gen_usda_vectors.py from app/foods.py map_usda_record and usda_search_item; "
                 "replayed against js/engine/usda.js by tests/js/run_vectors.mjs.",
        "map_cases": map_cases,
        "search_item_cases": search_cases,
    }


def dump(doc: dict) -> str:
    # One case per line; ASCII escapes keep invisible characters visible in diffs.
    lines = ["{"]
    keys = list(doc)
    for n, key in enumerate(keys):
        value = doc[key]
        comma = "," if n < len(keys) - 1 else ""
        if isinstance(value, list):
            lines.append(f"  {json.dumps(key)}: [")
            for m, item in enumerate(value):
                lines.append("    " + json.dumps(item, separators=(",", ":"), allow_nan=False) + ("," if m < len(value) - 1 else ""))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = dump(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_usda_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
