#!/usr/bin/env python3
"""Generate tests/data/import_vectors.json: parity vectors for the browser twin of the export.json import.

    python3 tests/data/gen_import_vectors.py           # rewrite the file
    python3 tests/data/gen_import_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code (``app/data_import.py`` behind ``POST /api/me/import``) and replayed on the JavaScript side by
``node tests/js/run_vectors.mjs`` against the demo API (``app/static/js/mock/import.js``, "Keep my data in this browser"):

* ``script``: one list of requests, run in order against a fresh server (here) and a fresh, empty demo (there), each with the
  answer the server gave. First the refusals, every one a dry run so nothing changes: a file that is not an export, a version
  the server does not read, a file nested too deeply, an unknown field at the top and inside every kind of record, a missing field,
  a field of the wrong kind, a value out of range, a date or a time that is not one, a nutrient or a flag the server does not know,
  a food id used twice, a list over its limit, the profile and settings rules. Then the flow: a dry run of a whole file, the
  refusal for an account that already has data, the import itself (``replace_profile`` too), adding the same file again (nothing
  new), a file without a built-in food list (matched by id and name), and what the account holds afterwards (read back through
  the ordinary routes, ids and times left out: they differ between the two sides).

The files are built here, not exported, so they exercise the rules (``ai`` and the consents never imported, the allowlisted
settings, the depth limit of 32) and not one side's idea of an export. Timestamps are fixed and in the past, or far in the future.
What the browser cannot see (a float written 2.0 against the integer 2, numbers beyond 2**53, Infinity) is left out; the Node
test of the twin covers Infinity.

Needs the app's dependencies (it starts the app against a temporary database and the real built-in food list).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "import_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import data_import  # noqa: E402
from app.nutrients import NUTRIENT_KEYS  # noqa: E402

D1, D2 = "2026-10-05", "2026-10-06"
T1, T2 = "2026-10-05T12:30:00.123456Z", "2026-10-06T08:00:00Z"
GUIDANCE = {"enabled": True, "carb_tolerance_g": 15, "hypo_dose_g": 20, "exclude_categories": ["Sweets & Snacks"],
            "show_plan_builder": True, "show_insights": False, "ai_enrich": False, "learn_from_log": False,
            "like_categories": ["Fruits"], "less_categories": ["Dairy & Alternatives"], "hidden_usual_meals": ["dinner:5x4,9x2"]}
VOLATILE = {"id", "food_id", "created_at", "updated_at", "version", "linked_at", "client_id"}


def nutrients(**given: Any) -> dict[str, Any]:
    return {key: given.get(key) for key in NUTRIENT_KEYS}


def food(i: int, name: str, **kw: Any) -> dict[str, Any]:
    return {"id": i, "name": name, "brand": None, "category": None, "source": "custom", "fdc_id": None, "serving_desc": "1 bowl", "serving_g": 300.0,
            "nutrients": nutrients(potassium_mg=400, phosphorus_mg=120, carbs_g=20), "flags": [], "kidney_notes": None, "hidden": False, "warnings": [],
            "kidney_rating": "green", "gtin": None, "source_url": None, "source_license": None, "quality": [], "additives": [], "ingredients_text": None, **kw}


def entry(i: int, food_id: int, name: str, **kw: Any) -> dict[str, Any]:
    return {"id": i, "date": D1, "meal": "lunch", "food_id": food_id, "food_name": name, "servings": 1, "grams": None, "note": None, "status": "eaten",
            "nutrients": nutrients(), "warnings": [], "kidney_rating": "green", "purpose": None, "client_id": None, "created_at": T1, "updated_at": T1, **kw}


def meal(i: int, name: str, items: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return {"id": i, "name": name, "note": None, "meal_hint": None, "items": items, "totals": nutrients(), "kidney_rating": "green",
            "created_at": T1, "updated_at": T2, **kw}


def item(food_id: int, name: str, servings: float = 1) -> dict[str, Any]:
    return {"food_id": food_id, "food_name": name, "servings": servings, "serving_desc": "1 serving", "nutrients": nutrients(), "kidney_rating": "green", "hidden": False}


def lab(i: int, analyte: str, value: float, unit: str, taken_on: str, **kw: Any) -> dict[str, Any]:
    return {"id": i, "analyte": analyte, "value": value, "unit": unit, "entered_value": value, "entered_unit": unit, "taken_on": taken_on, "note": None,
            "created_at": T1, **kw}


def symptom(i: int, key: str, day: str, severity: int = 1, **kw: Any) -> dict[str, Any]:
    return {"id": i, "date": day, "symptom": key, "label": None, "severity": severity, "note": None, "created_at": T1, **kw}


def weight(i: int, kg: float, day: str, context: str = "morning", **kw: Any) -> dict[str, Any]:
    return {"id": i, "date": day, "time": None, "kg": kg, "context": context, "note": None, "source": "manual", "source_key": None, "created_at": T1,
            "updated_at": T1, **kw}


def reading(i: int, systolic: int, diastolic: int, day: str, context: str = "morning", **kw: Any) -> dict[str, Any]:
    return {"id": i, "date": day, "time": None, "systolic": systolic, "diastolic": diastolic, "pulse": None, "context": context, "note": None,
            "source": "manual", "source_key": None, "created_at": T1, "updated_at": T1, **kw}


def base_doc(ids: dict[str, int]) -> dict[str, Any]:
    """A whole, valid file. ``ids``: the built-in foods' ids on the server (the demo has the same list)."""
    banana, tablets, rice = ids["banana"], ids["tablets"], ids["rice"]
    entries = [
        entry(1, banana, "Banana, raw", servings=2, note="with breakfast", meal="breakfast"),
        entry(2, 101, "My soup", servings=1.5, note="with bread"),
        entry(3, 101, "My soup", grams=150, servings=0.5, meal="dinner"),
        entry(4, 102, "Home gel", meal="snack", purpose="hypo", created_at=T2, updated_at=T2),
        entry(5, tablets, "Glucose tablet (4 g carb)", servings=4, meal="snack", purpose="hypo"),
        entry(6, 103, "Retired stew", date=D2, meal="dinner", status="planned"),
        entry(7, 202, "Old shared food", date=D2),
        entry(8, 777, "A food nobody has", date=D2, meal="snack"),
        entry(9, rice, "Rice, white, long-grain, cooked", date=D2, servings=0.75),
    ]
    return {
        "format": "kidney-health-export", "version": 1, "exported_at": "2026-10-06T09:00:00Z", "app_version": "0.3.0",
        "user": {"username": "someone", "display_name": "Someone", "created_at": T1},
        "profile": {"id": 1, "name": "Sam", "weight_kg": 70, "height_cm": 170, "ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "warn_fraction": 0.8,
                    "about_tolerance_pct": 0, "dialysis_days": [0, 3], "week_start": "monday", "targets": {"potassium_mg": 2500, "protein_g": {"min": 50, "max": 60}},
                    "birth_month": "1971-03", "sex": "unspecified", "activity": "low_active", "transplant_date": None, "frail_or_sarcopenic": False,
                    "weight_6_months_ago_kg": None, "pregnant_or_breastfeeding": False, "hyperkalemia_history": True, "urine_output_ml": None,
                    "pd_uf_ml": None, "pd_dialysate_kcal": None, "ckd_stage_chosen": True, "diabetes_chosen": True, "updated_at": T1},
        "settings": {"guidance": GUIDANCE, "ui.theme": "dark", "user.units.labs": "si", "food.scan_prefer_camera": True, "ai": {"opt_in": True, "provider": "own"},
                     "food.off_consent": True, "user.units.weight": "kg", "body.weight_alarm": {"amount_kg": 1.5, "over": "days", "days": 2},
                     "body.bp_goal": {"systolic": 130, "diastolic": 80}},
        "log_entries": entries,
        "custom_foods": [food(101, "My soup", brand="Home", category="Prepared & Fast Food", flags=["processed"], kidney_notes="Watch the salt."),
                         food(102, "Home gel", serving_desc="1 pouch", serving_g=32.0, nutrients=nutrients(carbs_g=22, sugar_g=20), flags=["hypo_treatment"]),
                         food(103, "Retired stew", serving_g=250.0, nutrients=nutrients(potassium_mg=700), hidden=True)],
        "linked_foods": [
            {"id": 201, "name": "Shared pasta", "source": "usda", "fdc_id": 424242, "linked_at": T1, "gtin": None,
             "food": food(201, "Shared pasta", source="usda", fdc_id=424242, serving_desc="1 cup", serving_g=140.0, nutrients=nutrients(potassium_mg=60, carbs_g=43))},
            {"id": 202, "name": "Old shared food", "source": "usda", "fdc_id": 515151, "linked_at": None, "gtin": None},
            {"id": 203, "name": "Diet Coke", "source": "off", "fdc_id": None, "linked_at": T1, "gtin": "00049000028911",
             "food": food(203, "Diet Coke", source="off", brand="Coca-Cola", serving_desc="1 can", serving_g=355.0, nutrients=nutrients(sodium_mg=40),
                          gtin="00049000028911", source_url="https://world.openfoodfacts.org/product/00049000028911", source_license="ODbL-1.0")},
        ],
        "builtin_foods": [{"id": banana, "name": "Banana, raw", "fdc_id": 173944}, {"id": tablets, "name": "Glucose tablet (4 g carb)", "fdc_id": -10},
                          {"id": rice, "name": "Rice, white, long-grain, cooked", "fdc_id": 168878}],
        "meal_templates": [
            meal(1, "Usual lunch", [item(101, "My soup"), item(banana, "Banana, raw", 2)], note="weekdays", meal_hint="lunch"),
            meal(2, "Lost foods", [item(777, "Ghost 1"), item(778, "Ghost 2"), item(779, "Ghost 3"), item(780, "Ghost 4"), item(781, "Ghost 5"), item(782, "Ghost 6"),
                                   item(banana, "Banana, raw")], note="n"),
            meal(3, "Only ghosts", [item(777, "Ghost 1")]),
            meal(4, "Empty", []),
        ],
        "lab_results": [lab(1, "potassium", 4.8, "mmol/L", "2026-10-01"), lab(2, "creatinine", 110, "µmol/L", "2026-09-20", note="fasting")],
        "symptoms": [symptom(1, "swelling", D1, 2, note="ankles"), symptom(2, "other", D1, 1, label="Cramps"),
                     *[symptom(10 + n, "itching", D2, 1, note=f"n{n}") for n in range(31)]],
        "weights": [weight(1, 70.25, D1, time="07:30", note="kept"), weight(2, 70.5, D1), weight(3, 70.5, D1),
                    weight(4, 71.0, D1, "after_dialysis", time="11:20", source="apple_health", source_key="a" * 32, updated_at=T2),
                    weight(5, 72.0, D2, "other", source="import", source_key="key-2"),
                    *[weight(10 + n, 60 + n / 10, D2, "other", note=f"n{n}") for n in range(21)]],
        "blood_pressures": [reading(1, 128, 78, D1, time="07:35", pulse=64), reading(2, 185, 100, D1, "evening", note="rested"),
                            reading(3, 140, 120, D2, "before_dialysis", source="apple_health", source_key="b" * 32, updated_at=T2),
                            reading(4, 120, 80, D2, "other", source="import", source_key="key-4"),
                            *[reading(10 + n, 120 + n % 20, 70, D2, "other", note=f"n{n}") for n in range(31)]],
        "food_preferences": [{"food_id": 101, "name": "My soup", "preference": "like", "created_at": T1, "source": "ask", "updated_at": T2},
                             {"food_id": banana, "name": "Banana, raw", "preference": "not_for_me", "created_at": T1},
                             {"food_id": tablets, "name": "Glucose tablet (4 g carb)", "preference": "neutral", "created_at": T1,
                              "source": "person", "updated_at": T1},
                             {"food_id": 102, "name": "Home gel", "preference": "less", "created_at": T2, "source": "assistant"},
                             {"food_id": 777, "name": "A food nobody has", "preference": "not_for_me", "created_at": T1}],
        "ai_audit": [{"prompt": "x"}], "activity": [], "ai_usage": [], "ai_consents": [], "ai_provider": {"api_key": "secret"},
    }


DELETE = object()


def path_of(path: str | list[Any]) -> list[Any]:
    return list(path) if isinstance(path, list) else [int(p) if p.isdigit() else p for p in path.split(".")]


def edit(path: str | list[Any], value: Any) -> dict[str, Any]:
    """One edit of the base file: set ``path`` (dotted, or a list when a key holds a dot) to ``value``, or delete it."""
    return {"op": "delete", "path": path_of(path)} if value is DELETE else {"op": "set", "path": path_of(path), "value": value}


def apply_edits(doc: Any, edits: list[dict[str, Any]]) -> Any:
    """The same edits are replayed by run_vectors.mjs (``applyEdits``)."""
    for e in edits:
        if e["op"] == "replace":
            doc = copy.deepcopy(e["value"])
            continue
        node = doc
        for part in e["path"][:-1]:
            node = node[part]
        last = e["path"][-1]
        if e["op"] == "delete":
            if isinstance(node, list):
                node.pop(last)
            else:
                node.pop(last, None)
        else:
            node[last] = copy.deepcopy(e["value"])
    return doc


LONG = "x" * 201


def refusals() -> list[tuple[str, list[dict[str, Any]]]]:
    s = lambda path, value: [edit(path, value)]  # noqa: E731
    deep = lambda n: [edit("settings", nest(n))]  # noqa: E731
    whole = lambda value: [{"op": "replace", "value": value}]  # noqa: E731
    out: list[tuple[str, list[dict[str, Any]]]] = [
        ("not an object: a list", whole([])),
        ("not an object: a number", whole(5)),
        ("not an object: text", whole("export")),
        ("an empty object", whole({})),
        ("format missing", s("format", DELETE)),
        ("format wrong", s("format", "something-else")),
        ("format of the wrong kind", s("format", 7)),
        ("version missing", s("version", DELETE)),
        ("version 2", s("version", 2)),
        ("version as text", s("version", "1")),
        ("version true", s("version", True)),
        ("version null", s("version", None)),
        ("version 1.5", s("version", 1.5)),
        ("version a long text with a line break", s("version", "9" * 30 + "\n10")),
        ("version a list", s("version", [1])),
        ("nested 33 deep", deep(31)),
        ("nested 32 deep is read", deep(30)),
        ("an unknown top-level field", s("colour", "red")),
        ("a long unknown top-level field", s("c" * 60, 1)),
        ("exported_at not a time", s("exported_at", "yesterday")),
        ("exported_at of the wrong kind", s("exported_at", 5)),
        ("exported_at before 2000", s("exported_at", "1999-12-31T23:59:59Z")),
        ("exported_at in the far future", s("exported_at", "2999-01-01T00:00:00Z")),
        ("exported_at with a month 13", s("exported_at", "2026-13-01T00:00:00Z")),
        ("exported_at on 30 February", s("exported_at", "2026-02-30T00:00:00Z")),
        ("exported_at with seven decimals", s("exported_at", "2026-10-05T12:30:00.1234567Z")),
        ("exported_at too long", s("exported_at", "2026-10-05T12:30:00." + "1" * 40 + "Z")),
        ("app_version too long", s("app_version", "v" * 41)),
        ("app_version of the wrong kind", s("app_version", 3)),
        ("log_entries not a list", s("log_entries", {})),
        ("a log entry that is not an object", s("log_entries.0", "x")),
        ("a log entry with an unknown field", s("log_entries.2.colour", "red")),
        ("a log entry without a date", s("log_entries.1.date", DELETE)),
        ("a log entry without a meal", s("log_entries.1.meal", DELETE)),
        ("a log entry with a wrong id", s("log_entries.0.id", "1")),
        ("a log entry with id 0", s("log_entries.0.id", 0)),
        ("a log entry with a negative food id", s("log_entries.0.food_id", -3)),
        ("a log entry with a fractional id", s("log_entries.0.id", 1.5)),
        ("a log entry with a true id", s("log_entries.0.id", True)),
        ("a log entry date in the wrong form", s("log_entries.0.date", "5/10/2026")),
        ("a log entry date that is not a day", s("log_entries.0.date", "2026-02-30")),
        ("a log entry date of the wrong kind", s("log_entries.0.date", 20261005)),
        ("a log entry with another meal", s("log_entries.0.meal", "brunch")),
        ("a log entry with another status", s("log_entries.0.status", "maybe")),
        ("a log entry with servings 0", s("log_entries.0.servings", 0)),
        ("a log entry with servings 1001", s("log_entries.0.servings", 1001)),
        ("a log entry with servings as text", s("log_entries.0.servings", "2")),
        ("a log entry with servings true", s("log_entries.0.servings", True)),
        ("a log entry with servings null", s("log_entries.0.servings", None)),
        ("a log entry with grams 0", s("log_entries.2.grams", 0)),
        ("a log entry with too many grams", s("log_entries.2.grams", 100001)),
        ("a log entry with an empty food name", s("log_entries.0.food_name", "   ")),
        ("a log entry with a food name over 200", s("log_entries.0.food_name", LONG)),
        ("a log entry with 200 emoji in the name is read", s("log_entries.0.food_name", "🍌" * 200)),
        ("a log entry with 201 emoji in the name", s("log_entries.0.food_name", "🍌" * 201)),
        ("a log entry with a long note", s("log_entries.0.note", "n" * 501)),
        ("a log entry with a note of the wrong kind", s("log_entries.0.note", 5)),
        ("a log entry with purpose none", s("log_entries.0.purpose", "none")),
        ("a log entry with a client id that is not a UUID", s("log_entries.0.client_id", "abc")),
        ("a log entry with a client id", s("log_entries.0.client_id", "0F8FAD5B-D9CB-469F-A165-70867728950E")),
        ("a log entry created at no time", s("log_entries.0.created_at", "soon")),
        ("a log entry created in the far future", s("log_entries.0.created_at", "2999-01-01T00:00:00Z")),
        ("a log entry updated before 2000", s("log_entries.0.updated_at", "1999-01-01T00:00:00Z")),
        ("a log entry with nutrients of the wrong kind", s("log_entries.0.nutrients", [1])),
        ("a log entry with an unknown nutrient", s("log_entries.0.nutrients", {"bogus": 1})),
        ("a log entry with a negative nutrient", s("log_entries.0.nutrients", {"potassium_mg": -1})),
        ("a log entry with a text nutrient", s("log_entries.0.nutrients", {"potassium_mg": "lots"})),
        ("a log entry with a huge nutrient", s("log_entries.0.nutrients", {"potassium_mg": 1e7})),
        ("a log entry with a true nutrient", s("log_entries.0.nutrients", {"potassium_mg": True})),
        ("a log entry with a rating that is not one", s("log_entries.0.kidney_rating", "blue")),
        ("a log entry with warnings of the wrong kind", s("log_entries.0.warnings", "none")),
        ("a log entry with a bad warning", s("log_entries.0.warnings", [{"level": "low", "message": "m"}])),
        ("a log entry with a warning with an unknown field", s("log_entries.0.warnings", [{"level": "high", "message": "m", "colour": 1}])),
        ("a log entry with a warning without a message", s("log_entries.0.warnings", [{"level": "high"}])),
        ("a log entry with a version", s("log_entries.0.version", "abc123")),
        ("a log entry with a long version", s("log_entries.0.version", "v" * 65)),
        ("a log entry with too many warnings", s("log_entries.0.warnings", [{"level": "high", "message": "m"}] * 41)),
        ("a log entry with far too many warnings", s("log_entries.0.warnings", [{"level": "high", "message": "m"}] * 45)),
        ("a log entry with many warnings and one bad one", s("log_entries.0.warnings", [{"level": "high", "message": "m"}] * 44 + [{"level": "x", "message": "m"}])),
        ("custom_foods not a list", s("custom_foods", "x")),
        ("a custom food with another source", s("custom_foods.1.source", "usda")),
        ("a custom food with an unknown source", s("custom_foods.0.source", "mine")),
        ("a custom food with an unknown field", s("custom_foods.0.colour", 1)),
        ("a custom food without a serving", s("custom_foods.0.serving_desc", DELETE)),
        ("a custom food with an empty serving", s("custom_foods.0.serving_desc", "")),
        ("a custom food with a serving weight under the minimum", s("custom_foods.0.serving_g", 0.05)),
        ("a custom food with a serving weight over the maximum", s("custom_foods.0.serving_g", 100001)),
        ("a custom food with a hidden flag of the wrong kind", s("custom_foods.0.hidden", "yes")),
        ("a custom food without a hidden flag", s("custom_foods.0.hidden", DELETE)),
        ("a custom food with flags of the wrong kind", s("custom_foods.0.flags", "processed")),
        ("a custom food with a flag that is not text", s("custom_foods.0.flags", ["processed", 5])),
        ("a custom food with a flag with capitals and spaces", s("custom_foods.0.flags", ["Processed Food"])),
        ("a custom food with a flag with capitals only", s("custom_foods.0.flags", ["PROCESSED", "processed", ""])),
        ("a custom food with 61 flags", s("custom_foods.0.flags", [f"f{n}" for n in range(61)])),
        ("a custom food with 60 flags", s("custom_foods.0.flags", [f"f{n}" for n in range(60)])),
        ("a custom food with 75 flags", s("custom_foods.0.flags", [f"f{n}" for n in range(75)])),
        ("a custom food with 75 flags and a bad one", s("custom_foods.0.flags", [f"f{n}" for n in range(74)] + ["BAD FLAG"])),
        ("a custom food with a bad barcode", s("custom_foods.0.gtin", "123")),
        ("a custom food with a barcode", s("custom_foods.0.gtin", "0049000028911")),
        ("a custom food with a long barcode", s("custom_foods.0.gtin", "1" * 33)),
        ("a custom food with a source address of its own", s("custom_foods.0.source_url", "https://example.com/x")),
        ("a custom food with the FoodData Central address", s("custom_foods.0.source_url", "https://fdc.nal.usda.gov/")),
        ("a custom food with a licence of its own", s("custom_foods.0.source_license", "MIT")),
        ("a custom food with a licence", s("custom_foods.0.source_license", "CC0-1.0 AND ODbL-1.0")),
        ("a custom food with a negative curated id", s("custom_foods.0.fdc_id", -10)),
        ("a custom food with an id of 0 for FoodData Central", s("custom_foods.0.fdc_id", 0)),
        ("a custom food with a long note", s("custom_foods.0.kidney_notes", "k" * 1001)),
        ("a custom food with a long ingredient list", s("custom_foods.0.ingredients_text", "i" * 4001)),
        ("a custom food with quality of the wrong kind", s("custom_foods.0.quality", [{"code": "c"}])),
        ("a custom food with too many additives", s("custom_foods.0.additives", ["a"] * 41)),
        ("a custom food with a long additive", s("custom_foods.0.additives", ["a" * 41])),
        ("a custom food with a rating that is not one", s("custom_foods.0.kidney_rating", "")),
        ("a custom food with a name of spaces", s("custom_foods.0.name", "  ")),
        ("a custom food with a brand over 200", s("custom_foods.0.brand", LONG)),
        ("a custom food with a category over 100", s("custom_foods.0.category", "c" * 101)),
        ("linked_foods not a list", s("linked_foods", 3)),
        ("a linked food that describes another", s("linked_foods.0.food.id", 999)),
        ("a linked food of another source", s("linked_foods.0.food.source", "off")),
        ("a linked food with an unknown field", s("linked_foods.1.role", "admin")),
        ("a linked food from custom", s("linked_foods.1.source", "custom")),
        ("a linked food with a time that is not one", s("linked_foods.0.linked_at", "x")),
        ("a linked food with a bad barcode", s("linked_foods.2.gtin", "12")),
        ("a linked food with a long name", s("linked_foods.1.name", LONG)),
        ("builtin_foods not a list", s("builtin_foods", None)),
        ("a built-in reference without a name", s("builtin_foods.0.name", DELETE)),
        ("a built-in reference with an unknown field", s("builtin_foods.0.role", 1)),
        ("a built-in reference with a text id", s("builtin_foods.1.id", "x")),
        ("a built-in reference with a number beyond the database", s("builtin_foods.1.fdc_id", -(2**63))),
        ("a built-in reference with a made-up number", s("builtin_foods.1.fdc_id", -987654)),
        ("a food id used twice in custom foods", s("custom_foods.1.id", 101)),
        ("a food id used in custom and linked foods", [edit("linked_foods.0.id", 101), edit("linked_foods.0.food.id", 101)]),
        ("a food id used in linked and built-in foods", s("builtin_foods.0.id", 201)),
        ("a food id used twice in linked foods", [edit("linked_foods.1.id", 201), edit("linked_foods.1.food", DELETE)]),
        ("meal_templates not a list", s("meal_templates", {})),
        ("a saved meal that is not an object", s("meal_templates.0", [])),
        ("a saved meal with 101 foods", s("meal_templates.0.items", [item(101, "My soup")] * 101)),
        ("a saved meal with 150 foods", s("meal_templates.0.items", [item(101, "My soup")] * 150)),
        ("a saved meal with an unknown field", s("meal_templates.0.colour", 1)),
        ("a saved meal with an empty name", s("meal_templates.0.name", "")),
        ("a saved meal with another meal hint", s("meal_templates.0.meal_hint", "brunch")),
        ("a saved meal with a food without servings", s("meal_templates.0.items.0.servings", DELETE)),
        ("a saved meal with servings over the maximum", s("meal_templates.0.items.0.servings", 1001)),
        ("a saved meal with a hidden flag of the wrong kind", s("meal_templates.0.items.1.hidden", 1)),
        ("a saved meal with totals of the wrong kind", s("meal_templates.0.totals", "x")),
        ("a saved meal with a long note", s("meal_templates.0.note", "n" * 1001)),
        ("a saved meal updated at no time", s("meal_templates.0.updated_at", "x")),
        ("lab_results not a list", s("lab_results", "x")),
        ("a lab result with an unknown test", s("lab_results.0.analyte", "sodium")),
        ("a lab result with an unknown unit", s("lab_results.0.entered_unit", "bananas")),
        ("a lab result outside the plausible range", s("lab_results.0.entered_value", 40)),
        ("a lab result with a negative value", s("lab_results.0.value", -1)),
        ("a lab result in the future", s("lab_results.0.taken_on", "2999-01-01")),
        ("a lab result on a day that is not one", s("lab_results.0.taken_on", "2026-13-01")),
        ("a lab result with a day of the wrong kind", s("lab_results.0.taken_on", 5)),
        ("a lab result before 1900", s("lab_results.0.taken_on", "1899-12-31")),
        ("a lab result with a long note", s("lab_results.0.note", "n" * 501)),
        ("a lab result with an unknown field", s("lab_results.0.panel", "renal")),
        ("a lab result without the entered value", s("lab_results.1.entered_value", DELETE)),
        ("symptoms not a list", s("symptoms", 1)),
        ("a symptom that is not on the list", s("symptoms.0.symptom", "boredom")),
        ("a symptom with severity 4", s("symptoms.0.severity", 4)),
        ("a symptom with severity 0", s("symptoms.0.severity", 0)),
        ("a symptom with severity 2.0 text", s("symptoms.0.severity", "2")),
        ("a symptom with a label though not other", s("symptoms.0.label", "Ankles")),
        ("an other symptom without a label", s("symptoms.1.label", None)),
        ("a symptom in the future", s("symptoms.0.date", "2999-01-01")),
        ("a symptom with a label over 60", s("symptoms.1.label", "l" * 61)),
        ("a symptom with a note over 300", s("symptoms.0.note", "n" * 301)),
        ("a symptom with a line break in the label", s("symptoms.1.label", "two\nlines")),
        ("a symptom with a control character in the note", s("symptoms.0.note", "a\x07b")),
        ("a symptom with a tab in the note", s("symptoms.0.note", "a\tb")),
        ("weights not a list", s("weights", 1)),
        ("a weight that is not an object", s("weights.0", 5)),
        ("a weight under the lightest", s("weights.0.kg", 19.99)),
        ("a weight over the heaviest", s("weights.0.kg", 400.01)),
        ("a weight of the lightest", s("weights.0.kg", 20)),
        ("a weight of the heaviest", s("weights.0.kg", 400)),
        ("a weight as text", s("weights.0.kg", "70")),
        ("a weight true", s("weights.0.kg", True)),
        ("a weight null", s("weights.0.kg", None)),
        ("a weight without kg", s("weights.0.kg", DELETE)),
        ("a weight with another context", s("weights.0.context", "evening")),
        ("a weight with a context of the wrong kind", s("weights.0.context", 3)),
        ("a weight with another source", s("weights.0.source", "fitbit")),
        ("a weight without a source", s("weights.0.source", DELETE)),
        ("a typed weight that keeps a key", [edit("weights.0.source_key", "k1")]),
        ("a weight in the future", s("weights.0.date", "2999-01-01")),
        ("a weight before 1900", s("weights.0.date", "1899-12-31")),
        ("a weight on a day that is not one", s("weights.0.date", "2026-02-30")),
        ("a weight with a padded date and time is read", [edit("weights.0.date", " 2026-10-05 "), edit("weights.0.time", " 07:30 ")]),
        ("a weight with a blank time is read", s("weights.0.time", "  ")),
        ("a weight with a time without its zero", s("weights.0.time", "7:30")),
        ("a weight with the time 24:00", s("weights.0.time", "24:00")),
        ("a weight with a time of the wrong kind", s("weights.0.time", 730)),
        ("a weight with a note over 200", s("weights.0.note", "n" * 201)),
        ("a weight with 200 emoji in the note is read", s("weights.0.note", "😀" * 200)),
        ("a weight with a control character in the note", s("weights.0.note", "a\x07b")),
        ("a weight with a tab in the note", s("weights.0.note", "a\tb")),
        ("a weight with a source key over 64", s("weights.3.source_key", "k" * 65)),
        ("a weight with a source key of the wrong kind", s("weights.3.source_key", 5)),
        ("a weight created at no time", s("weights.0.created_at", "soon")),
        ("a weight updated in the far future", s("weights.0.updated_at", "2999-01-01T00:00:00Z")),
        ("a weight with id 0", s("weights.0.id", 0)),
        ("a weight with an unknown field", s("weights.0.user_id", 2)),
        ("a weight without a date", s("weights.0.date", DELETE)),
        ("blood_pressures not a list", s("blood_pressures", {})),
        ("a reading that is not an object", s("blood_pressures.0", "x")),
        ("a top number under the lowest", s("blood_pressures.0.systolic", 49)),
        ("a top number over the highest", s("blood_pressures.0.systolic", 301)),
        ("a bottom number under the lowest", s("blood_pressures.0.diastolic", 19)),
        ("a bottom number over the highest", s("blood_pressures.0.diastolic", 201)),
        ("a top number equal to the bottom number", s("blood_pressures.0.systolic", 78)),
        ("a top number under the bottom number", s("blood_pressures.0.systolic", 70)),
        ("a top number as text", s("blood_pressures.0.systolic", "128")),
        ("a top number with a fraction", s("blood_pressures.0.systolic", 128.5)),
        ("a top number true", s("blood_pressures.0.systolic", True)),
        ("a reading without a top number", s("blood_pressures.0.systolic", DELETE)),
        ("a reading without a bottom number", s("blood_pressures.0.diastolic", DELETE)),
        ("a pulse under the lowest", s("blood_pressures.0.pulse", 19)),
        ("a pulse over the highest", s("blood_pressures.0.pulse", 251)),
        ("a pulse as text", s("blood_pressures.0.pulse", "64")),
        ("a reading with another context", s("blood_pressures.0.context", "bedtime")),
        ("a reading with another source", s("blood_pressures.0.source", "omron")),
        ("a reading in the future", s("blood_pressures.0.date", "2999-01-01")),
        ("a reading with a bad time", s("blood_pressures.0.time", "99:99")),
        ("a reading with a long note", s("blood_pressures.0.note", "n" * 201)),
        ("a reading with a source key over 64", s("blood_pressures.2.source_key", "k" * 65)),
        ("a reading with a flag field", s("blood_pressures.0.flag", None)),
        ("a reading with an unknown field", s("blood_pressures.0.user_id", 2)),
        ("food_preferences not a list", s("food_preferences", 1)),
        ("a preference that is none of the four", s("food_preferences.0.preference", "love")),
        ("a preference with no value", s("food_preferences.0.preference", None)),
        ("a preference with a source that is not person, ask or assistant", s("food_preferences.0.source", "robot")),
        ("a preference with a null source", s("food_preferences.0.source", None)),
        ("a preference with an updated_at that is not a time", s("food_preferences.0.updated_at", "yesterday")),
        ("a preference with an updated_at in the far future", s("food_preferences.0.updated_at", "2999-01-01T00:00:00Z")),
        ("a preference with an unknown field", s("food_preferences.0.colour", 1)),
        ("a preference with 1001 foods", s("food_preferences", [{"food_id": 101, "name": "My soup", "preference": "like", "created_at": T1}] * 1001)),
        ("a preference with 1020 foods", s("food_preferences", [{"food_id": 101, "name": "My soup", "preference": "less", "created_at": T1}] * 1020)),
        ("the profile is not an object", s("profile", [])),
        ("the profile has an unknown field", s("profile.colour", "red")),
        ("the profile weight is text", s("profile.weight_kg", "70")),
        ("the profile weight is 0", s("profile.weight_kg", 0)),
        ("the profile weight is over 500", s("profile.weight_kg", 501)),
        ("the profile weight is true", s("profile.weight_kg", True)),
        ("the profile stage is not one", s("profile.ckd_stage", "9")),
        ("the profile stage is a number", s("profile.ckd_stage", 4)),
        ("the profile name is over 100", s("profile.name", "n" * 101)),
        ("the profile tolerance is a fraction", s("profile.about_tolerance_pct", 1.5)),
        ("the profile tolerance is over 10", s("profile.about_tolerance_pct", 11)),
        ("the profile targets are a list", s("profile.targets", [])),
        ("the profile targets hold an unknown key", s("profile.targets", {"bogus_mg": 1})),
        ("the profile targets hold a negative number", s("profile.targets", {"potassium_mg": -5})),
        ("the profile targets hold a range upside down", s("profile.targets", {"protein_g": {"min": 60, "max": 50}})),
        ("the profile targets hold a range with an unknown key", s("profile.targets", {"protein_g": {"min": 50, "max": 60, "colour": 1}})),
        ("the profile dialysis days are text", s("profile.dialysis_days", "mon")),
        ("the profile dialysis days hold 7", s("profile.dialysis_days", [7])),
        ("the profile birth month is a day", s("profile.birth_month", "1971-03-01")),
        ("the profile birth month is blank", s("profile.birth_month", "  ")),
        ("the profile sex is not one", s("profile.sex", "x")),
        ("the profile transplant date is in the future", s("profile.transplant_date", "2999-01-01")),
        ("the profile yes/no is text", s("profile.frail_or_sarcopenic", "yes")),
        ("the profile urine output is over the maximum", s("profile.urine_output_ml", 5001)),
        ("the profile id is text", s("profile.id", "1")),
        ("the profile time is not one", s("profile.updated_at", "x")),
        ("the profile chosen flag is text", s("profile.ckd_stage_chosen", "no")),
        ("settings not an object", s("settings", [])),
        ("a setting name over 100", s("settings", {"s" * 101: 1})),
        ("201 settings", s("settings", {f"s{n}": n for n in range(201)})),
        ("260 settings", s("settings", {f"s{n}": n for n in range(260)})),
        ("200 settings are read", s("settings", {f"s{n}": n for n in range(200)})),
        ("a guidance setting with an unknown field", s("settings.guidance", {**GUIDANCE, "colour": 1})),
        ("a guidance setting of the wrong kind", s("settings.guidance", "on")),
        ("a guidance setting out of range", s("settings.guidance", {**GUIDANCE, "carb_tolerance_g": 500})),
        ("a theme that is not one", s(["settings", "ui.theme"], "purple")),
        ("a unit system that is not one", s("settings", {"user.units.labs": "imperial"})),
        ("a weight unit that is not one", s("settings", {"user.units.weight": "stone"})),
        ("a weight alarm above the highest", s("settings", {"body.weight_alarm": {"amount_kg": 50}})),
        ("a weight alarm with an unknown field", s("settings", {"body.weight_alarm": {"amount_kg": 1, "colour": 1}})),
        ("a weight alarm of the wrong kind", s("settings", {"body.weight_alarm": 5})),
        ("a blood pressure goal with the top number not above the bottom", s("settings", {"body.bp_goal": {"systolic": 100, "diastolic": 100}})),
        ("a blood pressure goal is read", s("settings", {"body.bp_goal": {"systolic": 130}})),
        ("the camera choice of the wrong kind", s("settings", {"food.scan_prefer_camera": "yes"})),
        ("the AI setting is ignored without being read", s("settings", {"ai": 5})),
        ("a consent is ignored without being read", s("settings", {"food.off_consent": {"x": 1}})),
        ("the skipped sections hold anything", [edit("user", [1, 2, {"a": None}]), edit("ai_audit", "text")]),
    ]
    return out


def nest(levels: int) -> dict[str, Any]:
    node: dict[str, Any] = {}
    for _ in range(levels):
        node = {"a": node}
    return node


def script(ids: dict[str, int]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(name: str, doc: Any, query: str = "dry_run=1", *, raw_path: str | None = None, method: str = "POST") -> None:
        path = raw_path or f"/api/me/import{'?' + query if query else ''}"
        step: dict[str, Any] = {"name": name, "method": method, "path": path}
        if method == "POST":
            if doc is base:
                step["edits"] = []
            elif isinstance(doc, dict) and set(doc) >= set(base) and all(doc[k] == base[k] for k in base if k != "log_entries"):
                step["edits"] = [edit("log_entries", doc["log_entries"])]  # the base with other log entries
            else:
                step["body"] = doc
        steps.append(step)

    base = base_doc(ids)
    for name, edits in refusals():
        steps.append({"name": name, "method": "POST", "path": "/api/me/import?dry_run=1", "edits": edits})
    # the allowlist: what a good file does and does not carry over
    add("a whole file, as a dry run", base)
    add("a whole file, as a dry run, replacing the profile", base, "dry_run=1&replace_profile=1")
    add("a whole file with merge ticked, as a dry run", base, "dry_run=1&merge=1&replace_profile=1")
    add("dry_run=true and merge=yes", base, "dry_run=true&merge=yes")
    add("dry_run=maybe", base, "dry_run=maybe")
    minimal = {"format": "kidney-health-export", "version": 1}
    add("a minimal file", minimal)
    add("a minimal file with a profile only", {**minimal, "profile": {"name": "Pat"}}, "dry_run=1&replace_profile=1")
    add("a file of settings only, replacing", {**minimal, "settings": {"ui.theme": "light", "ai": {"opt_in": True}, "food.off_consent": True, "other": 1}}, "dry_run=1&replace_profile=1")
    add("a file of settings only, not replacing", {**minimal, "settings": {"ui.theme": "light"}})
    add("a file of weight settings only, replacing", {**minimal, "settings": {"user.units.weight": "lb", "body.weight_alarm": {"amount_kg": 2, "over": "between_sessions"},
                                                                              "body.bp_goal": {"systolic": 120, "diastolic": 70}}}, "dry_run=1&replace_profile=1")
    add("a file of weight settings only, not replacing", {**minimal, "settings": {"user.units.weight": "lb"}})
    add("a file with a weight only", {**minimal, "weights": [weight(1, 70, D1)]})
    # the account is empty: the import itself
    add("the whole file imported, with the profile", base, "replace_profile=1")
    add("the account is not empty any more", base, "dry_run=1")
    add("the account is not empty: the real import is refused", base, "")
    add("the same file again, added to the data", base, "dry_run=1&merge=1&replace_profile=1")
    add("the same file again, imported", base, "merge=1&replace_profile=1")
    add("a file with an entry more, added", {**base, "log_entries": [*base["log_entries"], entry(20, 101, "My soup", date="2026-10-07", created_at="2026-10-07T07:00:00Z", updated_at="2026-10-07T07:00:00Z")]},
        "merge=1")
    add("a file with a weight and a reading more, added: typed rows by content, imported rows by key", {
        **minimal, "weights": [weight(1, 70.25, D1, time="07:30", note="kept"), weight(2, 69.0, D1), weight(3, 71.0, D1, "after_dialysis", time="11:20",
                                                                                                   source="apple_health", source_key="a" * 32),
                               weight(4, 68.0, "2026-10-07", source="apple_health", source_key="new-key")],
        "blood_pressures": [reading(1, 128, 78, D1, time="07:35", pulse=64), reading(2, 130, 80, D1), reading(3, 140, 120, D2, "before_dialysis", source="apple_health",
                                                                                                           source_key="b" * 32),
                            reading(4, 126, 76, "2026-10-07", source="import", source_key="new-key-2")]}, "merge=1")
    add("an older file without the list of built-in foods, matched by id and name", {
        **minimal, "log_entries": [entry(1, ids["banana"], "Banana, raw", date="2026-10-08"), entry(2, ids["rice"], "Not the name of this food", date="2026-10-08"),
                                   entry(3, 31, "Banana, raw", date="2026-10-08")],
        "food_preferences": [{"food_id": ids["rice"], "name": "RICE, WHITE, LONG-GRAIN, COOKED", "preference": "not_for_me", "created_at": T1}]}, "merge=1")
    add("a built-in food listed without its FoodData Central number", {**minimal, "builtin_foods": [{"id": 5, "name": "Banana, raw", "fdc_id": None}],
                                                 "log_entries": [entry(1, 5, "Banana, raw", date="2026-10-09")]}, "merge=1&dry_run=1")
    # what the account holds now, ids and times left out
    add("read back: the first day", None, raw_path=f"/api/log?date={D1}", method="GET")
    add("read back: the second day", None, raw_path=f"/api/log?date={D2}", method="GET")
    add("read back: saved meals", None, raw_path="/api/meals", method="GET")
    add("read back: lab results", None, raw_path="/api/labs", method="GET")
    add("read back: symptoms", None, raw_path=f"/api/symptoms?start={D1}&end={D2}", method="GET")
    add("read back: weights", None, raw_path=f"/api/body/weights?start={D1}&end={D2}", method="GET")
    add("read back: blood pressure", None, raw_path=f"/api/body/blood-pressure?start={D1}&end={D2}", method="GET")
    add("read back: Not for me", None, raw_path="/api/guidance/not-for-me", method="GET")
    add("read back: food preferences", None, raw_path="/api/guidance/preferences", method="GET")
    add("read back: the profile", None, raw_path="/api/profile", method="GET")
    return steps


def scrub(value: Any) -> Any:
    """What is the same on both sides: ids and times are not."""
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in VOLATILE}
    return value


def body_of(step: dict[str, Any], base: dict[str, Any]) -> Any:
    return apply_edits(copy.deepcopy(base), step["edits"]) if "edits" in step else step.get("body")


def run_script(client: Any, steps: list[dict[str, Any]], base: dict[str, Any]) -> list[dict[str, Any]]:
    from app.auth.ratelimit import RateLimits

    answers: list[dict[str, Any]] = []
    for step in steps:
        client.app.state.auth.limits = RateLimits()  # the allowance is per hour; the script has many steps
        if step["method"] == "GET":
            r = client.get(step["path"])
        else:
            r = client.post(step["path"], content=json.dumps(body_of(step, base)), headers={"content-type": "application/json"})
        body = r.json() if r.content else None
        answers.append({"status": r.status_code, "body": scrub(body) if step["method"] == "GET" else body})
    return answers


def build() -> dict[str, Any]:
    """The whole document (also what ``tests/test_import_vectors.py`` compares the committed file with)."""
    from starlette.testclient import TestClient as BareClient

    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, make_settings

    foods = ROOT / "data" / "foods.json"
    with tempfile.TemporaryDirectory() as tmp:
        with BareClient(create_app(make_settings(Path(tmp), foods)), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text

            def builtin(query: str) -> int:
                return client.get("/api/foods", params={"q": query}).json()["foods"][0]["id"]

            ids = {"banana": builtin("banana, raw"), "tablets": builtin("glucose tablet"), "rice": builtin("rice, white, long-grain")}
            base = base_doc(ids)
            steps = script(ids)
            answers = run_script(client, steps, base)
    doc = {
        "constants": {
            "rule": data_import.RULE, "not_imported": list(data_import.NOT_IMPORTED), "imported_settings": list(data_import.IMPORTED_SETTINGS),
            "skipped_sections": list(data_import.SKIPPED_SECTIONS), "max_depth": data_import.MAX_DEPTH,
        },
        "base": base,
        "script": [{**step, "answer": answer} for step, answer in zip(steps, answers)],
    }
    return json.loads(json.dumps(doc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_import_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
