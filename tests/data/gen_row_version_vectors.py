#!/usr/bin/env python3
"""Generate tests/data/row_version_vectors.json: parity vectors for the browser twin of the versions of every synced kind.

    python3 tests/data/gen_row_version_vectors.py           # rewrite the file
    python3 tests/data/gen_row_version_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code (``app/row_versions.py``: ``row_version``, ``canonical_text``, ``version_matches``) and replayed
on the JavaScript side by ``node tests/js/run_vectors.mjs`` against ``app/static/js/engine/row_versions.js`` (design note 39 §8.3):

* ``fields``: each kind's field list, and a saved meal item's;
* ``cases``: a row of each kind, its canonical text and its version: text with accents and emoji, whole and fractional numbers,
  empty and missing notes, lists (a food's flags in any order, a meal's items and steps), booleans, and an entry (note 02's version,
  unchanged);
* ``match_cases``: an ``If-Match`` header, a version and whether the header allows the change.

Standard library only (plus the app package on the path).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "row_version_vectors.json"
sys.path.insert(0, str(ROOT))

from app import row_versions as RV  # noqa: E402
from app.nutrients import NUTRIENT_KEYS  # noqa: E402

D = "2026-11-24"


def nutrients(**given: Any) -> dict[str, Any]:
    return {key: given.get(key) for key in NUTRIENT_KEYS}


FOOD = {"name": "Grandma's rice pudding", "brand": None, "category": "Family recipes", "serving_desc": "1 bowl", "serving_g": 150.0,
        "gtin": None, "kidney_notes": None, "ingredients_text": None, "hidden": False, "flags": [],
        "nutrients": nutrients(calories_kcal=210, potassium_mg=180, phosphorus_mg=120)}
MEAL = {"name": "Usual breakfast", "note": None, "meal_hint": "breakfast", "servings_made": None, "source_url": None, "steps": None,
        "items": [{"food_id": 4, "food_name": "Apple, raw, with skin", "servings": 1.0}, {"food_id": 9, "food_name": "Oats", "servings": 0.5}]}
LAB = {"analyte": "potassium", "entered_value": 5.1, "entered_unit": "mmol/L", "taken_on": D, "note": ""}
SYMPTOM = {"date": D, "symptom": "itching", "label": "", "severity": 2, "note": ""}
WEIGHT = {"date": D, "time": "07:15", "kg": 70.2, "context": "morning", "note": ""}
READING = {"date": D, "time": "07:20", "systolic": 122, "diastolic": 78, "pulse": None, "context": "morning", "note": ""}
ENTRY = {"date": D, "meal": "lunch", "food_name": "Banana, raw", "servings": 1, "grams": None, "note": None, "status": "eaten",
         "purpose": None, "nutrients": nutrients(calories_kcal=105, potassium_mg=422, carbs_g=27)}


def cases() -> list[dict[str, Any]]:
    named: list[tuple[str, str, dict[str, Any]]] = [
        ("food", "a plain food", FOOD),
        ("food", "another name", {**FOOD, "name": "Rice pudding"}),
        ("food", "a brand and a barcode", {**FOOD, "brand": "Acme", "gtin": "00012345678905"}),
        ("food", "flags in one order", {**FOOD, "flags": ["processed", "phosphate_additive"]}),
        ("food", "the same flags in the other order", {**FOOD, "flags": ["phosphate_additive", "processed"]}),
        ("food", "hidden", {**FOOD, "hidden": True}),
        ("food", "a note and ingredients with accents", {**FOOD, "kidney_notes": "Riche en phosphore", "ingredients_text": "riz, lait, crème 🍚"}),
        ("food", "a whole serving weight", {**FOOD, "serving_g": 150}),
        ("food", "every nutrient", {**FOOD, "nutrients": {key: 10 * (i + 1) + 0.5 * (i % 2) for i, key in enumerate(NUTRIENT_KEYS)}}),
        ("food", "unknown nutrients", {**FOOD, "nutrients": nutrients()}),
        ("food", "fields an older row lacks", {"name": "Old", "serving_desc": "1", "serving_g": 1, "nutrients": {}}),
        ("meal", "a saved meal", MEAL),
        ("meal", "the same items on another server (other food ids)", {**MEAL, "items": [{**i, "food_id": i["food_id"] + 100} for i in MEAL["items"]]}),
        ("meal", "items in the other order", {**MEAL, "items": list(reversed(MEAL["items"]))}),
        ("meal", "a recipe with steps", {**MEAL, "servings_made": 4.0, "steps": ["Boil the water.", "Add the oats; stir 🥄"],
                                         "source_url": "https://example.org/oats"}),
        ("meal", "an empty note", {**MEAL, "note": ""}),
        ("meal", "no items", {**MEAL, "items": []}),
        ("lab", "a lab result", LAB),
        ("lab", "a whole value", {**LAB, "entered_value": 5}),
        ("lab", "the same whole value as a float", {**LAB, "entered_value": 5.0}),
        ("lab", "another unit", {**LAB, "analyte": "phosphate", "entered_value": 4.1, "entered_unit": "mg/dL"}),
        ("lab", "a missing note is an empty note", {**LAB, "note": None}),
        ("lab", "a note", {**LAB, "note": "after dialysis"}),
        ("symptom", "a symptom", SYMPTOM),
        ("symptom", "other, with a label", {**SYMPTOM, "symptom": "other", "label": "Hiccups"}),
        ("symptom", "a missing label is an empty label", {**SYMPTOM, "label": None}),
        ("symptom", "severe, with a note", {**SYMPTOM, "severity": 3, "note": "all night, très fort"}),
        ("weight", "a weight", WEIGHT),
        ("weight", "no time", {**WEIGHT, "time": None}),
        ("weight", "a whole number of kilograms", {**WEIGHT, "kg": 70}),
        ("weight", "a missing note is an empty note", {**WEIGHT, "note": None}),
        ("reading", "a reading", READING),
        ("reading", "with a pulse", {**READING, "pulse": 64}),
        ("reading", "another context and a note", {**READING, "context": "after_dialysis", "note": "dizzy 😵"}),
        ("entry", "an entry is note 02's version", ENTRY),
        ("entry", "a planned entry by weight", {**ENTRY, "status": "planned", "servings": 0.5, "grams": 59.0}),
    ]
    out = []
    for kind, name, row in named:
        text = None if kind == "entry" else RV.canonical_text(kind, row)
        out.append({"kind": kind, "name": name, "row": row, "text": text, "version": RV.row_version(kind, row)})
    return out


def match_cases() -> list[dict[str, Any]]:
    v = RV.row_version("lab", LAB)
    other = RV.row_version("lab", {**LAB, "note": "x"})
    headers = [("no header", None), ("the version, quoted", f'"{v}"'), ("unquoted", v), ("another version", f'"{other}"'),
               ("a list with it", f'"{other}", "{v}"'), ("a weak tag", f'W/"{v}"'), ("any", "*"), ("empty", "")]
    return [{"name": n, "header": h, "version": v, "expected": RV.version_matches(h, v)} for n, h in headers]


def build() -> dict[str, Any]:
    return {
        "about": "Generated by tests/data/gen_row_version_vectors.py from app/row_versions.py; do not edit by hand.",
        "fields": {**{k: list(v) for k, v in RV.FIELDS.items()}, "meal_item": list(RV.ITEM_FIELDS)},
        "kinds": list(RV.KINDS),
        "cases": cases(),
        "match_cases": match_cases(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_row_version_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(build()['cases'])} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
