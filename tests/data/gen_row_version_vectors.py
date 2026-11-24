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
* ``match_cases``: an ``If-Match`` header, a version and whether the header allows the change;
* ``script``: one list of requests, run in order against a fresh server (here) and a fresh demo account with no sample data (there,
  ``app/static/js/mock/{foods,meals,symptoms,body,labs}.js``), with the answers the server gave: for a food, a saved meal, a symptom,
  a weight and a reading, a ``PUT`` with the version, one with an old version (``412`` and the row as stored), no header, ``*``, a
  list, a weak tag, an empty header, a bad body with an old version (``400``), a missing row (``404``), and ``DELETE`` with and
  without a match; for a lab result the ``DELETE`` only. In a step's path, body or header, ``{{id:N}}`` is the id of step N's answer
  and ``{{version:N}}`` the version of that answer (worked out from it, since the API leaves versions out). Each answer is shown as
  the fields its version is made of and its version (:func:`shown`); a ``412`` also says whether its ``current`` holds a
  ``client_id`` (a food's and a saved meal's do, as the server's row does).

Needs the app's dependencies for the script (it starts the app against a temporary database).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "row_version_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

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


# --------------------------------------------------------------------------- #
# The request script: If-Match on every kind's PUT and DELETE (design note 39 §8.3)
# --------------------------------------------------------------------------- #

PLACEHOLDER = re.compile(r"\{\{(id|version):(\d+)\}\}")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
OLD = "0000000000000000"  # a version no row has
DAY = "2026-10-05"


def ID(n: int) -> str:
    return "{{id:%d}}" % n


def V(n: int) -> str:
    return "{{version:%d}}" % n


def script() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(name: str, kind: str, method: str, path: str, body: Any = None, if_match: str | None = None) -> int:
        step: dict[str, Any] = {"name": name, "kind": kind, "method": method, "path": path}
        if body is not None:
            step["body"] = body
        if if_match is not None:
            step["if_match"] = if_match
        steps.append(step)
        return len(steps) - 1

    food = {"name": "Grandma's rice pudding", "serving_desc": "1 bowl", "serving_g": 150, "category": "Family recipes",
            "nutrients": {"calories_kcal": 210, "potassium_mg": 180, "phosphorus_mg": 120}}
    f0 = add("add a food", "food", "POST", "/api/foods", food)
    fp = f"/api/foods/{ID(f0)}"
    f1 = add("PUT with the matching version", "food", "PUT", fp, {**food, "name": "Rice pudding"}, f'"{V(f0)}"')
    add("PUT with the version it had before (412)", "food", "PUT", fp, {**food, "brand": "Acme"}, f'"{V(f0)}"')
    add("PUT with a bad body and an old version (400)", "food", "PUT", fp, {**food, "serving_g": -1}, f'"{OLD}"')
    f4 = add("PUT without the header", "food", "PUT", fp, {**food, "name": "Rice pudding", "kidney_notes": "Rich in phosphorus"})
    add("PUT with a weak tag (412)", "food", "PUT", fp, food, f'W/"{V(f4)}"')
    add("DELETE with an old version (412)", "food", "DELETE", fp, None, f'"{V(f1)}"')
    add("PUT of a food that is not there (404)", "food", "PUT", "/api/foods/999999", food, f'"{OLD}"')
    m0 = add("save a meal of it", "meal", "POST", "/api/meals",
             {"name": "Usual pudding", "meal_hint": "snack", "items": [{"food_id": ID(f0), "servings": 1}]})
    mp = f"/api/meals/{ID(m0)}"
    meal = {"name": "Usual pudding", "note": "after dinner", "items": [{"food_id": ID(f0), "servings": 2}]}
    m1 = add("PUT with the matching version", "meal", "PUT", mp, meal, f'"{V(m0)}"')
    add("PUT with the version it had before (412)", "meal", "PUT", mp, meal, f'"{V(m0)}"')
    add("PUT with a list that holds the version", "meal", "PUT", mp, {**meal, "steps": ["Warm it."]}, f'"{OLD}", "{V(m1)}"')
    add("DELETE with an old version (412)", "meal", "DELETE", mp, None, f'"{V(m1)}"')
    add("DELETE with a star", "meal", "DELETE", mp, None, "*")
    add("DELETE again (404)", "meal", "DELETE", mp, None, "*")
    f9 = add("read the food again", "food", "GET", fp)
    add("DELETE the food with its version", "food", "DELETE", fp, None, f'"{V(f9)}"')
    symptom = {"date": DAY, "symptom": "itching", "severity": 2}
    s0 = add("add a symptom", "symptom", "POST", "/api/symptoms", symptom)
    sp = f"/api/symptoms/{ID(s0)}"
    s1 = add("PUT with the matching version", "symptom", "PUT", sp, {**symptom, "severity": 3, "note": "all night"}, f'"{V(s0)}"')
    add("PUT with the version it had before (412)", "symptom", "PUT", sp, symptom, f'"{V(s0)}"')
    add("PUT with an empty header (412)", "symptom", "PUT", sp, symptom, "")
    add("DELETE with an old version (412)", "symptom", "DELETE", sp, None, f'"{V(s0)}"')
    add("DELETE with the version", "symptom", "DELETE", sp, None, f'"{V(s1)}"')
    add("DELETE of a symptom that is not there (404)", "symptom", "DELETE", "/api/symptoms/999999", None, f'"{OLD}"')
    weight = {"date": DAY, "time": "07:15", "kg": 70.2, "context": "morning"}
    w0 = add("add a weight", "weight", "POST", "/api/body/weights", weight)
    wp = f"/api/body/weights/{ID(w0)}"
    w1 = add("PUT with the matching version, unquoted", "weight", "PUT", wp, {**weight, "kg": 70.4}, V(w0))
    add("PUT with the version it had before (412)", "weight", "PUT", wp, weight, f'"{V(w0)}"')
    add("DELETE with an old version (412)", "weight", "DELETE", wp, None, f'"{V(w0)}"')
    add("DELETE with the version", "weight", "DELETE", wp, None, f'"{V(w1)}"')
    reading = {"date": DAY, "time": "07:20", "systolic": 122, "diastolic": 78, "context": "morning"}
    r0 = add("add a reading", "reading", "POST", "/api/body/blood-pressure", reading)
    rp = f"/api/body/blood-pressure/{ID(r0)}"
    r1 = add("PUT with the matching version", "reading", "PUT", rp, {**reading, "pulse": 64}, f'"{V(r0)}"')
    add("PUT with the version it had before (412)", "reading", "PUT", rp, reading, f'"{V(r0)}"')
    add("DELETE with an old version (412)", "reading", "DELETE", rp, None, f'"{V(r0)}"')
    add("DELETE with the version", "reading", "DELETE", rp, None, f'"{V(r1)}"')
    l0 = add("add a lab result", "lab", "POST", "/api/labs", {"analyte": "potassium", "value": 5.1, "unit": "mmol/L", "taken_on": DAY})
    lp = f"/api/labs/{ID(l0)}"
    add("DELETE with another version (412)", "lab", "DELETE", lp, None, f'"{OLD}"')
    add("DELETE with the version", "lab", "DELETE", lp, None, f'"{V(l0)}"')
    add("DELETE again (404)", "lab", "DELETE", lp, None, f'"{V(l0)}"')
    l4 = add("add another lab result", "lab", "POST", "/api/labs", {"analyte": "phosphate", "value": 4.1, "unit": "mg/dL", "taken_on": DAY})
    add("DELETE without the header", "lab", "DELETE", f"/api/labs/{ID(l4)}")
    return steps


def shown(kind: str, row: Any) -> Any:
    """A row as the vectors keep it: the fields its version is made of (a saved meal's items as their food's name and servings) and
    its version. Ids, timestamps and the rest of the answer are left out: they differ between the server and the demo."""
    if not isinstance(row, dict):
        return row
    out: dict[str, Any] = {}
    for name in RV.FIELDS[kind]:
        value = row.get(name)
        if name == "items":
            value = [{f: item.get(f) for f in RV.ITEM_FIELDS} for item in (value or [])]
        out[name] = value
    if kind == "food":
        out["nutrients"] = row.get("nutrients")
    out["version"] = row["version"] if "version" in row else RV.row_version(kind, row)
    return out


def resolve(text: str, raw: list[Any], steps: list[dict[str, Any]]) -> str:
    def value(match: re.Match[str]) -> str:
        n = int(match.group(2))
        return str(raw[n]["id"]) if match.group(1) == "id" else RV.row_version(steps[n]["kind"], raw[n])

    return PLACEHOLDER.sub(value, text)


def run_script(client: Any, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    raw: list[Any] = []  # the whole answers, for the placeholders
    for step in steps:
        headers: dict[str, str] = {}
        kwargs: dict[str, Any] = {}
        if "body" in step:
            text = re.sub(r'"(\{\{id:\d+\}\})"', r"\1", json.dumps(step["body"]))  # an id in a body is a number
            kwargs["content"] = resolve(text, raw, steps).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if "if_match" in step:
            headers["If-Match"] = resolve(step["if_match"], raw, steps)
        r = client.request(step["method"], resolve(step["path"], raw, steps), headers=headers, **kwargs)
        body = r.json() if r.content else None
        raw.append(body)
        if r.status_code >= 400:
            answer: dict[str, Any] = {"ok": False, "status": r.status_code, "detail": body["detail"]}
            if "current" in body:
                answer["current"] = shown(step["kind"], body["current"])
                answer["current_has_client_id"] = bool(UUID.match(str(body["current"].get("client_id") or "")))
        else:
            answer = {"ok": True, "body": shown(step["kind"], body)}
        answers.append(answer)
    return answers


def script_answers() -> list[dict[str, Any]]:
    from starlette.testclient import TestClient as BareClient

    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, FIXTURE_FOODS, make_settings

    steps = script()
    with tempfile.TemporaryDirectory() as tmp:
        foods = Path(tmp) / "foods.json"
        foods.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
        with BareClient(create_app(make_settings(Path(tmp), foods)), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text
            answers = run_script(client, steps)
    return [{**step, "answer": answer} for step, answer in zip(steps, answers)]


def build() -> dict[str, Any]:
    return json.loads(json.dumps({
        "about": "Generated by tests/data/gen_row_version_vectors.py from app/row_versions.py; do not edit by hand.",
        "fields": {**{k: list(v) for k, v in RV.FIELDS.items()}, "meal_item": list(RV.ITEM_FIELDS)},
        "kinds": list(RV.KINDS),
        "cases": cases(),
        "match_cases": match_cases(),
        "script": script_answers(),
    }))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    doc = build()
    text = json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_row_version_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['cases'])} rows, {len(doc['script'])} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
