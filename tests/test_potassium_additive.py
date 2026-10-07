"""The ``potassium_additive`` flag and its warning (ARCHITECTURE.md v0.3 item 9; note 03 R5, §6 item 5)."""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pytest

from app.nutrients import FLAGS, FOOD_SOURCES, POTASSIUM_ADDITIVE_MESSAGE, food_warnings, kidney_rating

ROOT = Path(__file__).resolve().parents[1]


def potassium_warnings(nutrients, flags, scope="per serving"):
    return [w for w in food_warnings(nutrients, flags, scope=scope) if w["nutrient"] == "potassium_mg"]


def test_registry() -> None:
    assert "potassium_additive" in FLAGS
    assert "off" in FOOD_SOURCES


@pytest.mark.parametrize("scope", ["per serving", "in this entry", "in this meal"])
def test_unknown_potassium_with_the_flag_is_a_medium_warning(scope: str) -> None:
    warnings = food_warnings({"potassium_mg": None}, ["potassium_additive"], scope=scope)
    assert warnings == [{"nutrient": "potassium_mg", "level": "medium", "value": None, "flag": "potassium_additive",
                         "message": "Contains a potassium additive; potassium not listed"}]
    assert kidney_rating(warnings) == "yellow"


def test_missing_key_counts_as_unknown() -> None:
    assert potassium_warnings({}, ["potassium_additive"])[0]["level"] == "medium"


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_value_counts_as_unknown(bad: float) -> None:
    assert potassium_warnings({"potassium_mg": bad}, ["potassium_additive"])[0]["flag"] == "potassium_additive"


@pytest.mark.parametrize("value, level", [(0, None), (50, None), (100.4, None), (101, "medium"), (200, "medium"), (201, "high"), (900, "high")])
def test_listed_potassium_uses_the_normal_thresholds(value: float, level: str | None) -> None:
    """Never a high warning from the flag itself; a listed value is judged like any other food's."""
    with_flag = potassium_warnings({"potassium_mg": value}, ["potassium_additive"])
    without = potassium_warnings({"potassium_mg": value}, [])
    assert with_flag == without
    assert (with_flag[0]["level"] if with_flag else None) == level
    assert all(w["flag"] is None for w in with_flag)


def test_never_high_from_the_flag_alone() -> None:
    for flags in (["potassium_additive"], ["potassium_additive", "processed"], ["potassium_additive", "counts_as_fluid"]):
        assert kidney_rating(food_warnings({"potassium_mg": None}, flags)) == "yellow"


def test_hypo_treatment_keeps_the_mineral_warning_and_still_has_no_carb_warning() -> None:
    warnings = food_warnings({"potassium_mg": None, "carbs_g": 40}, ["potassium_additive", "hypo_treatment", "high_gi"])
    assert [w["nutrient"] for w in warnings] == ["potassium_mg"]


def test_with_other_flags() -> None:
    warnings = food_warnings({}, ["potassium_additive", "phosphate_additive", "avoid_ckd"], "AVOID: salt substitute.")
    assert [(w["nutrient"], w["level"], w["flag"]) for w in warnings] == [
        ("avoid_ckd", "high", "avoid_ckd"), ("phosphorus_mg", "high", "phosphate_additive"),
        ("potassium_mg", "medium", "potassium_additive"),
    ]


def test_curated_flag_list_matches_the_registry() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import curated_foods
    finally:
        sys.path.pop(0)
    assert set(curated_foods.FLAGS) == set(FLAGS)


def test_browser_twin_has_the_same_message_and_flag() -> None:
    source = (ROOT / "app" / "static" / "js" / "engine" / "rules.js").read_text(encoding="utf-8")
    match = re.search(r"const POTASSIUM_ADDITIVE_MESSAGE = '([^']*)';", source)
    assert match and match.group(1) == POTASSIUM_ADDITIVE_MESSAGE
    assert "key: 'potassium_additive'" in source
