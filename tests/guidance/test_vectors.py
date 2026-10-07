"""Food vectors (note 06 §4.3): roles, renal level, protein quality, building from rows (``vectors.py``)."""
from __future__ import annotations

import fixtures as fx
import pytest
from app.guidance import rules as R
from app.guidance.vectors import build_vectors, is_high, make_food, protein_quality, renal_level
from app.nutrients import food_warnings, kidney_rating

PORTIONS = [q / 4 for q in range(1, 13)]  # ¼ … 3 servings


def test_renal_level_equals_the_apps_rating_for_every_builtin_food_and_portion():
    """§6.7: float comparisons give exactly the Decimal-rounded rating of ``food_warnings()``."""
    checked = 0
    for item in fx.real_food_items():
        flags = set(item.get("flags") or ())
        if "avoid_ckd" in flags:
            continue  # never eligible, never rated by guidance
        for q in PORTIONS:
            scaled = {k: (None if v is None else float(v) * q) for k, v in item["nutrients"].items()}
            warnings = [w for w in food_warnings(scaled, flags) if w["nutrient"] in (R.K, R.P, R.NA)]
            expected = kidney_rating(warnings)
            got = renal_level(scaled[R.K], scaled[R.P], scaled[R.NA], "phosphate_additive" in flags)
            assert got == expected, (item["name"], q, scaled[R.K], scaled[R.P], scaled[R.NA])
            checked += 1
    assert checked > 4000


@pytest.mark.parametrize("value,expected", [
    (200.0, False), (200.49999999999997, False), (200.5, True), (201.0, True), (None, False),
])
def test_is_high_rounds_like_the_warnings(value, expected):
    assert is_high(R.K, value) is expected


@pytest.mark.parametrize("value,level", [(100.4, "green"), (100.5, "yellow"), (200.4, "yellow"), (200.5, "red")])
def test_renal_level_boundaries(value, level):
    assert renal_level(value, None, None, False) == level


def test_phosphate_additive_is_always_red_and_unknowns_are_not_counted():
    assert renal_level(0, 0, 0, True) == "red"
    assert renal_level(None, None, None, False) == "green"


@pytest.mark.parametrize("category,carbs,protein,role", [
    ("Meat, Poultry & Eggs", 0, 3.6, "protein"),
    ("Fish & Seafood", 0, 20, "protein"),
    ("Prepared & Fast Food", 30, 12, "mixed"),
    ("Prepared & Fast Food", 10, 12, "protein"),
    ("Prepared & Fast Food", 30, 3, "starch"),
    ("Prepared & Fast Food", 5, 3, "extra"),
    ("Dairy & Alternatives", 12, 8, "protein"),
    ("Dairy & Alternatives", 12, 6.9, "extra"),
    ("Legumes, Nuts & Seeds", 20, 7, "protein"),
    ("Legumes, Nuts & Seeds", 20, 5, "starch"),
    ("Legumes, Nuts & Seeds", 5, 5, "extra"),
    ("Grains & Breads", 15, 3, "starch"),
    ("Vegetables", 37, 4, "starch"),
    ("Vegetables", 5, 1, "veg_fruit"),
    ("Fruits", 27, 1, "veg_fruit"),
    ("Beverages", 13, 1, "drink"),
    ("Sweets & Snacks", 20, 2, "extra"),
    (None, None, None, "extra"),
])
def test_roles_follow_the_rule_table(category, carbs, protein, role):
    assert R.role_of(category, carbs, protein) == role


def test_curated_role_override_wins_and_bad_values_are_ignored():
    assert R.role_of("Prepared & Fast Food", 14, 1, "veg_fruit") == "veg_fruit"
    assert R.role_of("Prepared & Fast Food", 14, 1, "salad") == "extra"
    coleslaw = next(f for f in fx.real_foods().values() if f.name == "Coleslaw, fast food")
    assert coleslaw.role == "veg_fruit" and coleslaw.group == "veg_fruit"


def test_protein_quality_grades():
    chicken = protein_quality(27, 220, 195)  # 7.2 mg P and 8.1 mg K per g
    assert (chicken["p_grade"], chicken["k_grade"]) == ("good", "good")
    assert protein_quality(10, 250, 170) == {"p_per_g": 17.0, "k_per_g": 25.0, "p_grade": "poor", "k_grade": "poor"}
    assert protein_quality(10, 150, 120)["p_grade"] == "fair"
    assert protein_quality(6.9, 10, 10)["p_grade"] is None  # not a protein portion
    assert protein_quality(10, None, None) == {"p_per_g": None, "k_per_g": None, "p_grade": None, "k_grade": None}


def test_make_food_keeps_unknown_values_unknown_and_derives_once():
    f = make_food(id=1, name="  Label soup, tomato ", category="Prepared & Fast Food", serving_desc="1 cup", serving_g=240,
                  nutrients={"carbs_g": 20, "sodium_mg": 700}, flags=["processed", "phosphate_additive"], source="custom")
    assert f.k is None and f.p is None and f.na == 700.0
    assert f.family == "label" and f.processed and f.additive and f.level1 == "red"
    assert set(f.nutrients) >= {"potassium_mg", "phosphorus_mg", "calories_kcal"}


def test_build_vectors_applies_overrides_only_to_builtin_rows():
    row = {"id": 5, "name": "Coleslaw", "category": "Prepared & Fast Food", "serving_desc": "1 cup", "serving_g": 99,
           "source": "builtin", "fdc_id": 777, "kidney_notes": None, "hidden": 0,
           **{k: None for k in fx.nutrients(None, None, None, None, None, None)}, "carbs_g": 14.0, "protein_g": 1.0}
    custom = {**row, "id": 6, "source": "custom"}
    vecs = build_vectors([(row, []), (custom, ["hypo_treatment"])], {777: "veg_fruit"})
    assert vecs[5].role == "veg_fruit" and vecs[6].role == "extra" and vecs[6].hypo
