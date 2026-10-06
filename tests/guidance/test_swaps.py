"""Note 06 §6.4 swap vectors TV-S1 … TV-S8, the hypo rules (F5, note 04 G7) and hypo options."""
from __future__ import annotations

import fixtures as fx
import pytest
from app.guidance import messages as M
from app.guidance import swaps
from app.guidance.state import Prefs
from app.guidance.vectors import make_food


def swap(fid, servings=1.0, purpose=None, meal="dinner", ctx=None):
    ctx = ctx or fx.context()
    return swaps.find_swaps(ctx, meal, ctx.foods[fid], servings, purpose)


def test_tv_s1_banana_to_blueberries():
    r = swap(6)
    assert r["mode"] == "normal" and r["match"] == "carbs"
    assert r["triggers"] == [{"nutrient": "potassium_mg", "reasons": ["high_per_portion"], "value": 420, "room": 750}]
    top = r["swaps"][0]
    assert (top["food_id"], top["servings"], top["score"], top["same_category"], top["fits_meal"]) == (7, 2.5, 4.47, True, True)
    assert top["nutrients"]["carbs_g"] == 27.5 and top["nutrients"]["potassium_mg"] == 138
    assert r["widened"] is False


def test_tv_s2_baked_potato_to_rice_with_portion_option_and_leaching_tip():
    r = swap(2)
    assert r["triggers"][0]["reasons"] == ["high_per_portion", "over_meal_room"]
    top = r["swaps"][0]
    assert (top["food_id"], top["servings"], top["score"], top["same_category"]) == (1, 0.75, 5.54, False)
    assert top["deltas"] == {"carbs_g": -3.3, "potassium_mg": -884, "phosphorus_mg": -68, "sodium_mg": -15}
    assert top["text"] == ("Rice, white, cooked (¾ × 1 cup): about the same carbs (34 g vs 37 g) and 884 mg less "
                           "potassium")
    assert top["portion_text"] == "¾ × 1 cup (158 g)" and top["grams"] == 118.5
    assert r["widened"] is True
    po = r["portion_option"]
    assert (po["servings"], po["fraction"]) == (0.5, 0.5) and po["nutrients"]["potassium_mg"] == 463
    assert po["text"] == "Half portion: 19 g carbs and 463 mg potassium. The carbs change, so count the new amount."
    assert [t["code"] for t in r["tips"]] == ["leaching"] and r["tips"][0]["handbook"] == "potassium-leaching"


def test_tv_s3_processed_cheese_has_no_swap_and_no_smaller_portion():
    r = swap(8)
    assert [(t["nutrient"], t["reasons"]) for t in r["triggers"]] == [
        ("phosphorus_mg", ["high_per_portion", "phosphate_additive"]), ("sodium_mg", ["high_per_portion"])]
    assert r["match"] == "protein" and r["swaps"] == [] and r["reason"] == "no_swap_found"
    assert r["portion_option"] is None  # the additive stays in a smaller portion
    assert [t["code"] for t in r["tips"]] == ["additives"]


def test_tv_s4_hypo_mode_offers_at_least_the_dose_lowest_potassium_first():
    r = swap(11, purpose="hypo")
    assert r["mode"] == "hypo" and r["match"] == "carbs"
    assert [(s["food_id"], s["servings"]) for s in r["swaps"]] == [(10, 1.0), (12, 1.25)]  # apple juice ×1 is 14 g < 15
    assert r["swaps"][0]["text"] == ("For your next low: Glucose tablets, 4 (1 × 4 tablets) gives 16 g carbs with "
                                     "0 mg potassium")
    assert all(s["nutrients"]["carbs_g"] >= 15 for s in r["swaps"])
    assert r["portion_option"] is None  # a treatment is never shrunk
    assert r["card"]["title"] == "Treating a low" and r["tips"][0]["code"] == "treating_a_low"


def test_tv_s5_orange_juice_with_a_meal_to_apple_juice():
    r = swap(11)
    assert r["mode"] == "normal"
    top = r["swaps"][0]
    assert (top["food_id"], top["servings"], top["score"]) == (12, 1.0, 3.9)  # hypo foods allowed for drinks


def test_tv_s6_no_trigger_no_swaps():
    for fid, purpose in ((1, None), (12, None), (12, "none")):
        r = swap(fid, purpose=purpose)
        assert r["swaps"] == [] and r["reason"] == "no_warning", fid


def test_hypo_mode_never_reduces_the_treatment_and_respects_the_dose_setting():
    ctx = fx.context(prefs=Prefs(hypo_dose_g=20))
    r = swaps.find_swaps(ctx, "snack", ctx.foods[12], 1.0, "hypo")
    assert [(s["food_id"], s["servings"]) for s in r["swaps"]] == [(10, 1.25)]  # 20 g: tablets ×1¼ (20 g)
    assert all(s["nutrients"]["carbs_g"] >= 20 for s in r["swaps"])
    # never filtered by the room, even on a day that is over every limit
    busy = fx.context(day=(fx.entry(ctx.foods[2], "breakfast", 4.0),))
    r2 = swaps.find_swaps(busy, "snack", busy.foods[11], 1.0, "hypo")
    assert [s["food_id"] for s in r2["swaps"]] == [10, 12]


def test_glucose_tablets_have_nothing_lower_so_no_swaps():
    r = swap(10, purpose="hypo")
    assert r["triggers"] == [] and r["reason"] == "no_warning" and r["card"]["handbook"] == "treating-a-low"


def test_avoid_mode_offers_other_fruit():
    r = swap(9)
    assert r["mode"] == "avoid" and r["triggers"][0]["reasons"] == ["avoid_ckd"]
    assert r["swaps"] and all(s["food_id"] not in (9, 10, 12) for s in r["swaps"])
    assert "without the warning that Star fruit has" in r["swaps"][0]["text"]
    assert r["portion_option"] is None


def test_a_swap_never_creates_a_new_problem():
    fs = fx.foods()
    salty = make_food(id=60, name="Bean dip", category="Fruits", serving_desc="1/4 cup (60 g)", serving_g=60,
                      nutrients=fx.nutrients(27, 1, 100, 30, 500, 0))
    ctx = fx.context(food_map={**fs, 60: salty})
    r = swaps.find_swaps(ctx, "dinner", ctx.foods[6], 1.0)
    assert 60 not in [s["food_id"] for s in r["swaps"]]  # less potassium but a new "high" sodium portion


def test_portion_option_three_quarters_when_it_clears_the_trigger():
    r = swap(11)  # orange juice: 250 mg; ¾ = 188 mg is no longer high
    assert r["portion_option"]["fraction"] == 0.75


def test_hypo_options_rank_by_potassium_and_never_need_targets():
    ctx = fx.context(targets={})
    r = swaps.hypo_options(ctx)
    assert [(o["food_id"], o["servings"]) for o in r["options"]] == [(10, 1.0), (12, 1.25)]
    assert r["dose_g"] == 15 and r["card"]["url"] == "/learn/t1d/treating-a-low/"
    excluded = swaps.hypo_options(fx.context(prefs=Prefs(exclude_food_ids=frozenset({10}))))
    assert [o["food_id"] for o in excluded["options"]] == [12]


def test_hypo_option_dropped_when_three_servings_cannot_reach_the_dose():
    fs = fx.foods()
    weak = make_food(id=70, name="Gummy, 1", category="Diabetes supplies", serving_desc="1 piece (3 g)", serving_g=3,
                     nutrients=fx.nutrients(2.5, 0, 0, 0, 0, 0), flags=("hypo_treatment",))
    r = swaps.hypo_options(fx.context(food_map={**fs, 70: weak}))
    assert 70 not in [o["food_id"] for o in r["options"]]


# --------------------------------------------------------------------------- #
# Real food list (TV-S7, TV-S8)
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def real_day():
    fs = fx.real_foods()
    n = lambda name: fx.by_name(fs, name)  # noqa: E731
    day = (fx.entry(n("Bread, white"), "breakfast", 2), fx.entry(n("Egg, scrambled"), "breakfast"),
           fx.entry(n("Orange juice"), "breakfast"), fx.entry(n("Chicken breast, roasted, skinless"), "lunch"),
           fx.entry(n("Pasta, cooked"), "lunch"), fx.entry(n("Green beans, boiled"), "lunch"))
    return fx.context(food_map=fs, targets=fx.STAGE4_TARGETS, day=day, history=(), saved=()), n


def test_tv_s7_baked_potato_on_the_real_food_list(real_day):
    ctx, n = real_day
    r = swaps.find_swaps(ctx, "dinner", n("Potato, baked, with skin"), 1.0)
    top = [(s["name"], s["servings"]) for s in r["swaps"]]
    assert top == [("Couscous, cooked", 1.0), ("Pasta, cooked", 1.0), ("Grits, cooked", 1.0),
                   ("Rice, white, long-grain, cooked", 0.75), ("Cream of wheat, cooked", 1.5)]
    for s in r["swaps"]:
        f = ctx.foods[s["food_id"]]
        assert f.category == "Grains & Breads" and not f.ingredient
        assert 33 <= s["nutrients"]["carbs_g"] <= 40 and s["nutrients"]["potassium_mg"] <= 91


def test_tv_s8_processed_cheese_to_natural_cheese(real_day):
    ctx, n = real_day
    r = swaps.find_swaps(ctx, "dinner", n("Cheese, American, processed"), 1.0)
    assert r["match"] == "protein"
    assert {(s["name"], s["servings"]) for s in r["swaps"][:2]} == {
        ("Cheese, mozzarella, part skim", 0.75), ("Cheese, cheddar", 0.75)}
    assert not any(ctx.foods[s["food_id"]].additive for s in r["swaps"])


def test_swap_texts_pass_the_wording_rules(real_day):
    ctx, _ = real_day
    for f in list(ctx.foods.values())[::7]:
        r = swaps.find_swaps(ctx, "dinner", f, 1.0)
        for s in r["swaps"]:
            assert not M.BANNED_PATTERN.search(s["text"]), s["text"]
