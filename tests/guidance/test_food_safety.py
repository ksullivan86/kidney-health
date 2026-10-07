"""Raw eggs are never a guidance suggestion (v0.3.0 review).

The handbook tells people to avoid raw or undercooked eggs (stages/after-transplant.md, living/travel.md),
and transplant recipients take immunosuppressants. "What fits now" and the plan builder suggested
"Egg white, raw" under the USDA record's name. The builtin egg white row is now named "Egg white" with a
cooking note (its values are per egg, the same raw or cooked), and the whole raw egg is a recipe
``ingredient``, which guidance never suggests on its own."""
from __future__ import annotations

import json
import re
from pathlib import Path

import fixtures as fx
import pytest
from app.guidance import fits, planner

ROOT = Path(__file__).resolve().parents[2]
FOODS = json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))["foods"]
RAW_EGG = re.compile(r"\begg\b.*\braw\b|\braw\b.*\begg", re.IGNORECASE)


def _names(value) -> list[str]:
    """Every ``name`` in a guidance answer (meals, items, options)."""
    if isinstance(value, dict):
        return [v for k, v in value.items() if k == "name" and isinstance(v, str)] + [n for v in value.values() for n in _names(v)]
    if isinstance(value, list):
        return [n for v in value for n in _names(v)]
    return []


@pytest.fixture(scope="module")
def real_foods():
    return fx.real_foods()


def test_the_builtin_list_names_no_suggestible_raw_egg():
    for f in FOODS:
        if RAW_EGG.search(f["name"]):
            assert "ingredient" in f["flags"], f["name"]  # only ever part of a recipe
            assert "cook" in (f["kidney_notes"] or "").lower(), f["name"]
    white = next(f for f in FOODS if f["fdc_id"] == 172183)
    assert white["name"] == "Egg white" and "Cook it until firm" in white["kidney_notes"]


@pytest.mark.parametrize("targets, dialysis", [("STAGE4_TARGETS", "none"), ("HD_TARGETS", "hemodialysis")])
def test_what_fits_and_the_plan_never_offer_a_raw_egg(real_foods, targets, dialysis):
    raw = {f.id for f in real_foods.values() if RAW_EGG.search(f.name)}
    assert raw  # the whole raw egg is still in the list (to log a recipe)
    ctx = fx.context(food_map=real_foods, targets=getattr(fx, targets), dialysis=dialysis, day=(), history=(), saved=())
    for meal in ("breakfast", "lunch", "dinner", "snack"):
        r = fits.what_fits(ctx, meal, limit=40)
        assert not raw & {f["food_id"] for f in r["foods"]}, meal
        assert not any(RAW_EGG.search(f["name"]) for f in r["foods"]), meal
    names = _names(planner.plan_day(ctx))
    assert names and not [n for n in names if RAW_EGG.search(n)]
    # The egg white is still a suggestion: a renal-diet protein with little phosphorus.
    assert any(f["name"] == "Egg white" for meal in ("breakfast", "lunch", "dinner")
               for f in fits.what_fits(ctx, meal, limit=40)["foods"])
