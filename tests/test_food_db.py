"""Invariants of the committed builtin database ``data/foods.json`` (no network).

These pin the review fixes to the curated list: flags must agree with the numbers shown next
to them, hypo treatments are served at a rescue portion, and the foods quoted in
docs/diet-guide.md section 3 carry the same USDA record (and therefore the same numbers).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.foods import CATEGORIES
from app.nutrients import FLAGS, NUTRIENT_KEYS, food_warnings, kidney_rating

FOODS_JSON = Path(__file__).resolve().parents[1] / "data" / "foods.json"


@pytest.fixture(scope="module")
def foods() -> dict[str, dict]:
    if not FOODS_JSON.is_file():
        pytest.skip("data/foods.json not checked out")
    doc = json.loads(FOODS_JSON.read_text(encoding="utf-8"))
    assert isinstance(doc.get("version"), str) and doc["version"]
    return {f["name"]: f for f in doc["foods"]}


def _warnings(f: dict) -> list[dict]:
    return food_warnings(f["nutrients"], f["flags"], f.get("kidney_notes"))


def test_shape_categories_flags_and_count(foods):
    assert len(foods) == 395
    for f in foods.values():
        assert f["category"] in CATEGORIES, f["name"]
        assert set(f["flags"]) <= set(FLAGS), f["name"]
        assert set(f["nutrients"]) == set(NUTRIENT_KEYS), f["name"]
        assert f["serving_g"] > 0 and f["serving_desc"].endswith("g)"), f["name"]
        if "counts_as_fluid" in f["flags"]:
            assert (f["nutrients"]["fluid_ml"] or 0) > 0, f["name"]
        else:
            assert f["nutrients"]["fluid_ml"] == 0, f["name"]


def test_low_potassium_fruit_badge_never_sits_next_to_a_high_potassium_warning(foods):
    badged = [f for f in foods.values() if "low_potassium_fruit" in f["flags"]]
    assert len(badged) >= 15
    for f in badged:
        assert f["nutrients"]["potassium_mg"] <= 200, f"{f['name']}: {f['nutrients']['potassium_mg']} mg"
        assert all(not (w["nutrient"] == "potassium_mg" and w["level"] == "high") for w in _warnings(f)), f["name"]
    # the guide's 1/2-cup servings (docs/research/food-lists.md Appendix 1)
    assert foods["Strawberries, raw"]["serving_g"] == 76 and foods["Strawberries, raw"]["nutrients"]["potassium_mg"] == 116
    assert foods["Grapes, red or green, raw"]["serving_g"] == 75.5 and foods["Grapes, red or green, raw"]["nutrients"]["potassium_mg"] == 144
    assert foods["Blackberries, raw"]["serving_g"] == 72 and foods["Blueberries, raw"]["serving_g"] == 74
    assert foods["Pear, raw"]["serving_desc"].startswith("1 small") and foods["Pear, raw"]["nutrients"]["potassium_mg"] == 172


def test_hypo_treatments_are_served_as_a_rescue_portion_and_get_no_carb_warning(foods):
    hypo = [f for f in foods.values() if "hypo_treatment" in f["flags"]]
    assert len(hypo) >= 10
    for f in hypo:
        assert f["nutrients"]["carbs_g"] <= 20, f"{f['name']}: {f['nutrients']['carbs_g']} g per {f['serving_desc']}"
        assert all(w["nutrient"] != "carbs_g" for w in _warnings(f)), f["name"]
    # the sodas are no longer a whole can; the sports drink is the 8 fl oz of its own note
    assert foods["Lemon-lime soda, regular"]["serving_g"] == 123 and foods["Lemon-lime soda, regular"]["nutrients"]["carbs_g"] == 12.8
    assert foods["Ginger ale"]["serving_g"] == 122
    assert foods["Sports drink (lemon-lime)"]["serving_g"] == 243 and foods["Sports drink (lemon-lime)"]["nutrients"]["carbs_g"] == 19.1
    # cranberry juice is the guide's lowest-potassium rescue juice (section 4): 1/2 cup, 17 g carbs, 18 mg K
    cran = foods["Cranberry juice cocktail"]
    assert "hypo_treatment" in cran["flags"] and cran["serving_g"] == 126.5
    assert cran["nutrients"]["carbs_g"] == 17.1 and cran["nutrients"]["potassium_mg"] == 18
    assert kidney_rating(_warnings(cran)) == "green"
    # a whole can of root beer (no hypo flag) still rates red for its sugar
    assert kidney_rating(_warnings(foods["Root beer"])) == "red"


def test_guide_eat_list_foods_use_the_guide_usda_records(foods):
    turkey = foods["Turkey breast, roasted"]
    assert turkey["fdc_id"] == 171496 and turkey["serving_g"] == 85
    assert (turkey["nutrients"]["potassium_mg"], turkey["nutrients"]["phosphorus_mg"], turkey["nutrients"]["sodium_mg"]) == (212, 196, 84)
    tofu = foods["Tofu, firm"]
    assert tofu["fdc_id"] == 172448 and tofu["serving_g"] == 81
    assert (tofu["nutrients"]["potassium_mg"], tofu["nutrients"]["phosphorus_mg"], tofu["nutrients"]["protein_g"]) == (120, 98, 7.3)


def test_glycaemic_index_alone_does_not_make_condiments_or_white_bread_red(foods):
    for name in ("Ketchup", "Pickle relish, sweet", "Sugar, brown", "Bread, white", "Teriyaki sauce"):
        f = foods[name]
        carb = [w for w in _warnings(f) if w["nutrient"] == "carbs_g"]
        assert carb and carb[0]["level"] == "medium" and carb[0]["flag"] == "high_gi", name
    # white bread (the guide's renal swap) is not rated worse than whole-wheat bread
    rank = {"green": 0, "yellow": 1, "red": 2}
    assert rank[kidney_rating(_warnings(foods["Bread, white"]))] <= rank[kidney_rating(_warnings(foods["Bread, whole-wheat"]))]
    # from one carb choice up the flag still upgrades to high
    assert kidney_rating(_warnings(foods["Cookies, chocolate chip"])) == "red"


def test_liquids_count_as_fluid(foods):
    assert "counts_as_fluid" in foods["Gravy, beef, canned"]["flags"]
    assert 40 <= foods["Gravy, beef, canned"]["nutrients"]["fluid_ml"] <= 58


INGREDIENTS = {
    "Flour, all-purpose", "Salt, table", "Baking powder (phosphate type)", "Black pepper, ground", "Vinegar, cider",
    "Vinegar, balsamic", "Olive oil", "Canola oil", "Sugar, brown", "Margarine, stick", "Butter, salted",
    "Butter, unsalted",
}


def test_ingredients_are_flagged_so_meal_guidance_never_suggests_them_alone(foods):
    """Note 06 F9/§4.11: flour, salt, oils, butter … are only ever added to other food."""
    flagged = {name for name, f in foods.items() if "ingredient" in f["flags"]}
    assert flagged == INGREDIENTS


def test_role_overrides_are_valid_and_rare(foods):
    """Note 06 §4.11: an optional curated ``role`` corrects the derived meal-guidance role."""
    from app.guidance.rules import ROLES

    overridden = {name: f["role"] for name, f in foods.items() if "role" in f}
    assert overridden == {"Coleslaw, fast food": "veg_fruit"}
    assert set(overridden.values()) <= set(ROLES)
