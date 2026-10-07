"""Alcoholic drinks are never a guidance suggestion (integration fix, v0.3.0).

With insulin, alcohol can cause lows hours later (ADA Standards of Care 2026 §5, recommendations
5.18-5.19; handbook eat/eating-out), so "What fits now", swaps, the plan builder, the energy note,
usual meals and AI ideas never offer beer, wine or spirits. The person can still search for, log and
save them; a meal they saved themselves keeps its drink.
"""
from __future__ import annotations

import json
from pathlib import Path

import fixtures as fx
import pytest
from app.guidance import fits, planner, swaps
from app.guidance import rules as R
from app.guidance.budget import meal_room
from app.guidance.score import check_meal
from app.guidance.state import SavedMeal
from app.nutrients import FLAGS

ROOT = Path(__file__).resolve().parents[2]
FOODS = json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))["foods"]
COMBOS = json.loads((ROOT / "data" / "combos.json").read_text(encoding="utf-8"))["combos"]

# A low-potassium, no-carb drink: exactly what the rules would otherwise rank first for a full day.
VODKA = (20, "Vodka (test)", "Beverages", "1 jigger (42 g)", 42, 0, 0, 1, 2, 0, 28, ("counts_as_fluid", "alcohol"))
WATER = (21, "Sparkling water (test)", "Beverages", "1 cup (240 g)", 240, 0, 0, 2, 0, 5, 240, ("counts_as_fluid",))


@pytest.fixture(scope="module")
def real_foods():
    return fx.real_foods()


def _alcohol_ids(food_map) -> set[int]:
    return {f.id for f in food_map.values() if f.alcohol}


def test_flag_is_registered_and_used_by_the_builtin_drinks():
    assert R.ALCOHOL_FLAG == "alcohol" and "alcohol" in FLAGS
    flagged = sorted(f["name"] for f in FOODS if "alcohol" in f["flags"])
    assert flagged == ["Beer, light", "Beer, regular", "Spirits (gin, rum, vodka, whiskey), 80 proof", "Wine, red", "Wine, white"]
    for f in FOODS:
        name = f["name"].casefold()
        if f["category"] == "Beverages" and name.startswith(("beer", "wine", "spirits", "liqueur", "cider, hard")):
            assert "alcohol" in f["flags"], f["name"]
        if "alcohol" in f["flags"]:
            assert "hypo_treatment" not in f["flags"], f["name"]  # never a low treatment


def test_no_starter_meal_holds_an_alcoholic_drink():
    alcohol = {f["fdc_id"] for f in FOODS if "alcohol" in f["flags"]}
    for combo in COMBOS:
        assert not alcohol & {item["fdc_id"] for item in combo["items"]}, combo["id"]


def test_alcohol_is_not_eligible_for_meals():
    fs = fx.foods(fx.FOOD_ROWS + (VODKA, WATER))
    ctx = fx.context(food_map=fs)
    assert fits.ineligible_reason(fs[20], ctx) == "alcohol"
    assert not fits.eligible_for_meals(fs[20], ctx)
    assert fits.ineligible_reason(fs[21], ctx) is None
    assert fs[20] not in fits.eligible_foods(ctx)


def test_what_fits_never_lists_alcohol_and_explain_says_why(real_foods):
    alcohol = _alcohol_ids(real_foods)
    assert len(alcohol) == 5
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    for meal in ("breakfast", "lunch", "dinner", "snack"):
        r = fits.what_fits(ctx, meal, limit=20, explain=True)
        assert not alcohol & {f["food_id"] for f in r["foods"]}, meal
        assert {r["explain"]["not_eligible"][str(i)] for i in alcohol} == {"alcohol"}


def test_built_and_ai_meals_refuse_alcohol_but_a_saved_meal_keeps_it():
    fs = fx.foods(fx.FOOD_ROWS + (VODKA,))
    ctx = fx.context(food_map=fs, day=(), history=())
    room = meal_room(ctx, "dinner")
    items = [(fs[3], 1.0), (fs[1], 1.0), (fs[20], 1.0)]
    assert check_meal(items, room, "built").reason == "alcohol"
    assert check_meal(items, room, "ai").reason == "alcohol"
    assert check_meal(items, room, "saved").ok  # the person's own saved meal


def test_usual_meals_leave_the_drink_out():
    fs = fx.foods(fx.FOOD_ROWS + (VODKA,))
    history = tuple(fx.hist(fs[i], d, "dinner") for d in ("2026-10-01", "2026-10-02", "2026-10-03") for i in (3, 1, 5, 20))
    ctx = fx.context(food_map=fs, history=history, saved=())
    usual = fits.usual_meals_for(ctx, "dinner")
    assert usual and all(20 not in {f.id for f, _ in items} for _, items in usual)
    assert {f.id for f, _ in usual[0][1]} == {3, 1, 5}


def test_swaps_never_offer_alcohol(real_foods):
    alcohol = _alcohol_ids(real_foods)
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    juice = fx.by_name(real_foods, "Orange juice")
    r = swaps.find_swaps(ctx, "dinner", juice, 1.0, "none")
    assert r["swaps"] and not alcohol & {s["food_id"] for s in r["swaps"]}
    fs = fx.foods(fx.FOOD_ROWS + (VODKA, WATER))
    ctx2 = fx.context(food_map=fs)
    assert not swaps._eligible_swap(fs[20], fs[11], ctx2, "normal")
    assert swaps._eligible_swap(fs[21], fs[11], ctx2, "normal")


def test_plan_and_energy_note_never_hold_alcohol(real_foods):
    alcohol = _alcohol_ids(real_foods)
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
    r = planner.plan_day(ctx)
    planned = {i["food_id"] for m in r["meals"] for i in m["items"]}
    assert not alcohol & planned
    note = r["energy_note"]
    assert note is not None  # the stage 4 plan is low in calories, so the note lists energy-dense foods
    assert not alcohol & {f["food_id"] for f in note["foods"]}


def test_a_saved_meal_with_wine_is_still_offered(real_foods):
    wine = fx.by_name(real_foods, "Wine, red")
    chicken = fx.by_name(real_foods, "Chicken breast, roasted, skinless")
    rice = fx.by_name(real_foods, "Rice, white, long-grain, cooked")
    saved = (SavedMeal(id=7, name="Friday dinner", meal_hint="dinner", items=((chicken.id, 1.0), (rice.id, 1.0), (wine.id, 1.0))),)
    ctx = fx.context(food_map=real_foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=saved)
    r = fits.what_fits(ctx, "dinner")
    assert [m["name"] for m in r["saved_meals"] if m["source"] == "saved"] == ["Friday dinner"]
