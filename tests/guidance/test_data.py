"""Curated data for guidance (note 06 §4.11, §7 "Data"): ``data/combos.json`` starter meals and the
``ingredient`` flag / ``role`` override in ``data/foods.json``."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.guidance import rules as R
from app.guidance.context import read_combos

ROOT = Path(__file__).resolve().parents[2]
COMBOS = json.loads((ROOT / "data" / "combos.json").read_text(encoding="utf-8"))
FOODS = {f["fdc_id"]: f for f in json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))["foods"]}

# docs/diet-guide.md §6 "A sample day": carbs g, protein g, K, P, Na mg per meal (USDA SR Legacy, re-summed).
GUIDE = {
    "sample-day-breakfast": (46, 13, 324, 174, 231),
    "sample-day-snack": (17, 4, 180, 60, 5),
    "sample-day-lunch": (46, 20, 462, 191, 425),
    "sample-day-dinner": (42, 24, 453, 231, 54),
}
KEYS = ("carbs_g", "protein_g", "potassium_mg", "phosphorus_mg", "sodium_mg")


def test_combos_file_shape_and_ids():
    assert COMBOS["version"] and COMBOS["combos"]
    ids = [c["id"] for c in COMBOS["combos"]]
    assert len(ids) == len(set(ids)) == 4
    assert {c["meal"] for c in COMBOS["combos"]} == {"breakfast", "lunch", "dinner", "snack"}
    for c in COMBOS["combos"]:
        assert c["source"] == "diet-guide §6" and c["name"]
        for item in c["items"]:
            assert item["fdc_id"] in FOODS, (c["id"], item)  # never a guessed id
            assert R.PORTION_MIN <= item["servings"] <= R.PORTION_MAX
            assert "avoid_ckd" not in FOODS[item["fdc_id"]]["flags"]
            assert "hypo_treatment" not in FOODS[item["fdc_id"]]["flags"]


@pytest.mark.parametrize("combo", COMBOS["combos"], ids=lambda c: c["id"])
def test_combos_add_up_to_the_diet_guide_sample_day(combo):
    totals = dict.fromkeys(KEYS, 0.0)
    for item in combo["items"]:
        for key in KEYS:
            totals[key] += (FOODS[item["fdc_id"]]["nutrients"][key] or 0) * item["servings"]
    carbs, protein, k, p, na = GUIDE[combo["id"]]
    assert abs(totals["carbs_g"] - carbs) <= 1
    assert abs(totals["protein_g"] - protein) <= 1
    assert abs(totals["potassium_mg"] - k) <= 10
    assert abs(totals["phosphorus_mg"] - p) <= 10
    # The food list has salted peanut butter only; the combo says so in its "as" text.
    allowed_na = 70 if combo["id"] == "sample-day-snack" else 10
    assert abs(totals["sodium_mg"] - na) <= allowed_na


def test_combos_are_read_and_cached():
    assert read_combos() == tuple(COMBOS["combos"])
    assert read_combos(ROOT / "data" / "no-such-file.json") == ()


def test_ingredients_and_role_overrides_in_the_food_list():
    flagged = sorted(f["name"] for f in FOODS.values() if "ingredient" in f["flags"])
    assert len(flagged) == 12 and "Flour, all-purpose" in flagged and "Salt, table" in flagged
    overrides = {f["name"]: f["role"] for f in FOODS.values() if "role" in f}
    assert overrides == {"Coleslaw, fast food": "veg_fruit"}
    assert all(role in R.ROLES for role in overrides.values())
