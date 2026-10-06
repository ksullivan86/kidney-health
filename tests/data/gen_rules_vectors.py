#!/usr/bin/env python3
"""Generate tests/data/rules_vectors.json: the shared parity vectors for the rules engine.

    python3 tests/data/gen_rules_vectors.py           # rewrite the file
    python3 tests/data/gen_rules_vectors.py --check   # exit 1 when the committed file is stale

The vectors are produced by the server's own pure functions in ``app/nutrients.py``
(``food_warnings``, ``kidney_rating``, ``round_value`` / ``round_nutrients``) and checked on both
sides of the parity rule (ARCHITECTURE.md, "Frontend modules"):

* Python: ``tests/test_rules_vectors.py`` fails when this file would change (a rule changed
  without the vectors being regenerated);
* JavaScript: ``node tests/js/run_vectors.mjs`` loads ``app/static/js/engine/rules.js`` and
  checks every vector against ``KH.rules.evaluateWarnings`` / ``ratingFromWarnings`` /
  ``roundValue`` / ``roundNutrients``.

Contents
  * ``foods``: every builtin food of ``data/foods.json`` (per-serving nutrients, flags, and the
    kidney notes when ``avoid_ckd`` makes them the warning text);
  * ``food_cases``: each food at 0.5, 1 and 2.5 servings (the nutrients are the food's values
    times the servings, unrounded, as an entry snapshot is), each with a different message
    scope, with the expected warnings, kidney rating and the 12 rounded values (an array in
    ``nutrient_keys`` order);
  * ``boundary_cases``: threshold edges (x.4 / x.5 / x.6 around every limit, the 15 g
    high-GI gate), every flag that changes a rule, unknown values, avoid_ckd with and without
    notes, and a fixed-seed sample of mixed cases;
  * ``round_cases``: ``round_value`` on half-way and binary-unfriendly numbers for every unit.
Standard library only (plus the app package on the path).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "rules_vectors.json"
FOODS_JSON = ROOT / "data" / "foods.json"
SERVINGS = (0.5, 1, 2.5)
SCOPE_FOR = {0.5: "in this entry", 1: "per serving", 2.5: "in this meal"}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.nutrients import NUTRIENT_KEYS, food_warnings, kidney_rating, round_nutrients, round_value  # noqa: E402

BOUNDARIES = {
    "potassium_mg": [0.5, 1e-9, 100.4, 100.49999, 100.5, 101, 199.5, 200, 200.4, 200.5, 200.6],
    "phosphorus_mg": [100.4, 100.5, 101, 149.5, 150, 150.4, 150.5, 151],
    "sodium_mg": [140.4, 140.5, 141, 399.5, 400, 400.4, 400.5],
    "carbs_g": [0.04, 0.05, 0.06, 4, 7.5, 14.94, 14.95, 14.96, 15, 22.5, 29.95, 29.96, 30, 30.04, 30.05, 37.5, 52.5, 67.5],
    "protein_g": [14.94, 14.95, 15, 24.95, 25, 25.04, 25.05, 25.06],
}
FLAG_SETS = ([], ["high_gi"], ["hypo_treatment"], ["phosphate_additive"], ["hypo_treatment", "high_gi"], ["avoid_ckd"],
             ["potassium_additive"], ["potassium_additive", "hypo_treatment"])
ROUND_VALUES = [0, 0.05, 0.15, 0.25, 0.35, 0.45, 0.5, 1.005, 1.5, 2.5, 2.675, 14.95, 26.95, 29.95, 100.5, 100.49999,
                200.5, 1e-7, 0.000123, 123456.75, 999999.95, 1 / 3, 2 / 3, 0.1 + 0.2, 33.3 * 3, 422 * 1.5, 26.95 * 2.5]


def food_vectors(foods: list[dict]) -> tuple[list[dict], list[dict]]:
    out_foods, cases = [], []
    for i, f in enumerate(foods):
        nutrients = {k: f["nutrients"].get(k) for k in NUTRIENT_KEYS}
        flags = list(f.get("flags") or [])
        notes = f.get("kidney_notes") if "avoid_ckd" in flags else None
        out_foods.append({"i": i, "fdc_id": f.get("fdc_id"), "name": f["name"], "nutrients": nutrients, "flags": flags, "kidney_notes": notes})
        for servings in SERVINGS:
            scaled = {k: (None if v is None else float(v) * servings) for k, v in nutrients.items()}
            scope = SCOPE_FOR[servings]
            warnings = food_warnings(scaled, flags, notes, scope=scope)
            rounded = round_nutrients(scaled)
            cases.append({"food": i, "servings": servings, "scope": scope, "warnings": warnings,
                          "kidney_rating": kidney_rating(warnings), "rounded": [rounded[k] for k in NUTRIENT_KEYS]})
    return out_foods, cases


def boundary_vectors() -> list[dict]:
    cases: list[dict] = []

    def add(nutrients, flags, notes, scope):
        warnings = food_warnings(nutrients, flags, notes, scope=scope)
        cases.append({"nutrients": nutrients, "flags": flags, "kidney_notes": notes, "scope": scope,
                      "warnings": warnings, "kidney_rating": kidney_rating(warnings)})

    for key, values in BOUNDARIES.items():
        for v in values:
            for flags in FLAG_SETS:
                add({key: v}, list(flags), None, "per serving")
    add({}, [], None, "per serving")
    add({k: None for k in NUTRIENT_KEYS}, ["phosphate_additive"], None, "in this entry")
    add({"carbs_g": 0}, ["high_gi"], None, "per serving")
    add({"carbs_g": None}, ["high_gi"], None, "per serving")
    add({"potassium_mg": 121}, ["avoid_ckd"], "  Star fruit contains caramboxin.  ", "per serving")
    add({"potassium_mg": 121}, ["avoid_ckd"], "   ", "in this meal")
    # potassium_additive (ARCHITECTURE v0.3 item 9): medium when potassium is unknown, thresholds when listed.
    for flags in (["potassium_additive"], ["potassium_additive", "hypo_treatment"], ["potassium_additive", "phosphate_additive"],
                  ["potassium_additive", "avoid_ckd"], ["potassium_additive", "high_gi"]):
        for scope in ("per serving", "in this entry", "in this meal"):
            add({"potassium_mg": None, "phosphorus_mg": None, "carbs_g": 20}, flags, "Avoid." if "avoid_ckd" in flags else None, scope)
        add({}, flags, None, "per serving")
        add({k: None for k in NUTRIENT_KEYS}, flags, None, "in this entry")
        add({"potassium_mg": 0}, flags, None, "per serving")
    rnd = random.Random(20261005)
    pool = ["high_gi", "hypo_treatment", "phosphate_additive", "avoid_ckd", "counts_as_fluid", "processed"]
    base = [26.95, 422, 105, 0.15, 1.29, 33.3, 12.25, 0.35, 2.45, 18.75]
    factors = [0.25, 0.333, 0.5, 0.75, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 3.3, 7]
    for _ in range(400):
        nut = {}
        for key in BOUNDARIES:
            r = rnd.random()
            if r < 0.1:
                nut[key] = None
            elif r < 0.4:
                nut[key] = rnd.choice(BOUNDARIES[key])
            elif r < 0.7:
                nut[key] = rnd.choice(base) * rnd.choice(factors)
            else:
                nut[key] = round(rnd.uniform(0, 600), rnd.choice([0, 1, 2, 3]))
        flags = [f for f in pool if rnd.random() < 0.2]
        notes = rnd.choice([None, "", "Avoid.", "  Star fruit contains caramboxin.  "])
        add(nut, flags, notes, rnd.choice(["per serving", "in this entry", "in this meal"]))
    # A second fixed-seed sample with the v0.3 potassium_additive flag (kept separate so the first
    # sample above stays byte-for-byte the same).
    rnd = random.Random(20261006)
    pool_v3 = pool + ["potassium_additive"]
    for _ in range(150):
        nut = {key: (None if rnd.random() < 0.35 else rnd.choice(BOUNDARIES[key])) for key in BOUNDARIES}
        flags = [f for f in pool_v3 if rnd.random() < (0.6 if f == "potassium_additive" else 0.15)]
        add(nut, flags, rnd.choice([None, "Avoid."]), rnd.choice(["per serving", "in this entry", "in this meal"]))
    return cases


def round_vectors() -> list[dict]:
    keys = ["potassium_mg", "fluid_ml", "calories_kcal", "carbs_g", "protein_g", "sugar_g"]
    return [{"key": k, "value": v, "expected": round_value(k, v)} for k in keys for v in ROUND_VALUES]


def build() -> dict:
    data = json.loads(FOODS_JSON.read_text(encoding="utf-8"))
    foods, food_cases = food_vectors(data["foods"])
    return {
        "about": "Parity vectors for app/static/js/engine/rules.js, generated from app/nutrients.py by "
                 "tests/data/gen_rules_vectors.py. Do not edit by hand: change the rules, then regenerate.",
        "foods_version": data.get("version"),
        "servings": list(SERVINGS),
        "nutrient_keys": list(NUTRIENT_KEYS),  # the order of every "rounded" array
        "foods": foods,
        "food_cases": food_cases,
        "boundary_cases": boundary_vectors(),
        "round_cases": round_vectors(),
    }


def dumps(doc: dict) -> str:
    """One vector per line, so a rule change shows up as a readable diff."""
    lines = ["{"]
    items = list(doc.items())
    for n, (key, value) in enumerate(items):
        comma = "," if n < len(items) - 1 else ""
        if isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(f"  {json.dumps(key)}: [")
            for m, item in enumerate(value):
                lines.append("    " + json.dumps(item, ensure_ascii=False, separators=(",", ":")) + ("," if m < len(value) - 1 else ""))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = dumps(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if json.loads(current or "null") != json.loads(text):
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_rules_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['food_cases'])} food cases, {len(doc['boundary_cases'])} boundary cases, "
          f"{len(doc['round_cases'])} rounding cases ({len(text.encode()):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
