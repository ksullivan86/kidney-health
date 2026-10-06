"""Note 06 §6.3 "What fits now" vectors TV-F1 … TV-F8, reasons, tips and edge cases."""
from __future__ import annotations

import fixtures as fx
from app.guidance import budget, fits
from app.guidance.score import Counter, Scorer, habit_stats, today_stats
from app.guidance.state import Prefs
from app.guidance.vectors import make_food


def dinner(**kw):
    return fits.what_fits(fx.context(**kw), "dinner", explain=True)


def scorer_for(ctx, meal="dinner"):
    room = budget.meal_room(ctx, meal)
    return Scorer(room, habit_stats(ctx), today_stats(ctx.day)), room


def test_tv_f1_ineligible_foods():
    ctx = fx.context()
    eligible = {f.id for f in fits.eligible_foods(ctx)}
    assert not eligible & {9, 10, 12}  # avoid_ckd; diabetes supplies + hypo; hypo
    assert 11 in eligible  # orange juice is a drink, not flagged as a treatment


def test_tv_f2_hard_filter_and_half_portion():
    scorer, _ = scorer_for(fx.context())
    potato = fx.context().foods[2]
    assert scorer.evaluate(potato, 1.0).why_not == "would_exceed:potassium_mg"  # 925 > 750 + 50
    half = scorer.evaluate(potato, 0.5)
    assert half.why_not is None and half.score is not None  # 462.5 mg passes


def test_tv_f3_scores_to_two_decimals():
    scorer, _ = scorer_for(fx.context())
    fs = fx.context().foods
    expected = {(1, 1.0): 6.13, (4, 1.0): 5.04, (3, 0.5): 4.80, (5, 1.0): 4.59, (7, 1.0): 4.34, (11, 0.5): 0.66,
                (6, 0.5): -3.05, (2, 0.5): -3.53, (8, 0.5): -6.64, (13, 0.5): -0.58, (14, 0.5): -0.03}
    for (fid, q), score in expected.items():
        assert scorer.evaluate(fs[fid], q).score == score, (fid, q)
    # …and those are each food's best portion
    for fid, q in [(1, 1.0), (4, 1.0), (3, 0.5), (6, 0.5), (2, 0.5), (8, 0.5), (13, 0.5), (14, 0.5)]:
        from app.guidance import rules as R

        best, _ = scorer.best_portion(fs[fid], R.portions_for(fs[fid].role))
        assert best.servings == q, fid


def test_tv_f4_returned_order_and_portions():
    result = dinner()
    assert [(f["food_id"], f["servings"]) for f in result["foods"]] == [
        (1, 1.0), (4, 1.0), (3, 0.5), (5, 1.0), (7, 1.0), (11, 0.5)]
    assert [f["score"] for f in result["foods"]] == [6.13, 5.04, 4.8, 4.59, 4.34, 0.66]
    assert result["room_text"] == ("Left for dinner: 750 mg potassium · 167 mg phosphorus · 600 mg sodium · "
                                   "60 g carbs to reach 60 g")
    assert result["open_meals"] == ["dinner", "snack"]
    assert result["room"]["potassium_mg"] == {"room": 750, "cap": 750, "share": 800, "in_meal": 0,
                                              "remaining_today": 1200, "allowance_today": 2500, "level": "ok",
                                              "basis": "day"}
    assert result["room"]["fluid_ml"] is None
    assert result["room"]["carbs_g"] == {"goal": 60, "in_meal": 0, "gap": 60, "tolerance": 10, "hypo_excluded_g": 0}
    assert result["room"]["protein_g"] == {"aim": 9.3, "aim_min": 4.7}
    assert result["notes"] == ["Suggestions compare foods with the targets your care team set. They are not medical advice."]


def test_tv_f5_f6_reasons_and_texts():
    foods = {f["food_id"]: f for f in dinner()["foods"]}
    rice, chicken = foods[1], foods[3]
    assert rice["fit_text"] == "Fits: 45 g carbs · 55 mg potassium · 70 mg phosphorus · 0 mg sodium"
    assert rice["reasons"] == [{"code": "adds_missing_group", "text": "Adds the starch this dinner is missing"},
                               {"code": "fills_carbs", "text": "Brings dinner to 45 of your 60 g carbs"}]
    assert rice["handbook"] == [{"slug": "carb-counting", "title": "Carb counting on a kidney diet",
                                 "url": "/learn/eat/carb-counting/"}]
    assert rice["portion_text"] == "1 × 1 cup (158 g)" and rice["grams"] == 158
    assert rice["renal_rating"] == "green"
    assert [w["nutrient"] for w in rice["warnings"]] == ["carbs_g"]  # the per-portion warning still shows
    assert [r["code"] for r in chicken["reasons"]] == ["adds_missing_group", "protein_quality"]
    assert chicken["reasons"][1]["text"] == "14 g protein with little phosphorus (7 mg per g)"
    components = rice["explain"]["components"]
    assert components["base"] == 3 and components["static"] == 0.5 and components["carbs"] == 1.5


def test_tv_f7_saved_meal_fits_at_half_size():
    saved = dinner()["saved_meals"]
    assert len(saved) == 1
    meal = saved[0]
    assert (meal["template_id"], meal["scale"], meal["score"], meal["source"]) == (1, 0.5, -11.41, "saved")
    assert meal["totals"] == {"carbs_g": 25.0, "protein_g": 16.0, "potassium_mg": 183, "phosphorus_mg": 143,
                              "sodium_mg": 33}
    assert meal["note"] == ("Fits at half size (25 g carbs, 35 g under your 60 g goal): this week's phosphorus "
                            "leaves 167 mg for dinner.")


def test_tv_f8_excluded_food_leaves_the_starch_group_empty():
    result = dinner(prefs=Prefs(exclude_food_ids=frozenset({1})))
    assert 1 not in [f["food_id"] for f in result["foods"]]
    assert "starch" not in {f["group"] for f in result["foods"]}  # potato ×½ scores −3.53


def test_excluded_categories_and_why_not_in_explain():
    result = dinner(prefs=Prefs(exclude_categories=frozenset({"Fruits"})))
    assert not {7, 6} & {f["food_id"] for f in result["foods"]}
    why = dinner()["explain"]["why_not"]
    assert why == {}  # every eligible fixture food has at least one passing portion
    tight = fx.context(day=(fx.entry(fx.context().foods[13], "breakfast", 3.0),))
    assert "8" in fits.what_fits(tight, "dinner", explain=True)["explain"]["why_not"]  # additive while P not ok


def test_selection_limits_and_minimum_score():
    result = fits.what_fits(fx.context(), "dinner", limit=2)
    assert [f["food_id"] for f in result["foods"]] == [1, 4]
    assert fits.what_fits(fx.context(), "dinner", limit=500)["foods"]  # clamped, never an error
    # group limit: three protein foods at most, category limit two
    fs = fx.foods()
    extra = {100 + i: make_food(id=100 + i, name=f"Fish {i}", category="Fish & Seafood", serving_desc="1 oz (28 g)",
                                serving_g=28, nutrients=fx.nutrients(0, 7, 60, 50, 40, 0)) for i in range(4)}
    result = fits.what_fits(fx.context(food_map={**fs, **extra}), "dinner")
    groups = [f["group"] for f in result["foods"]]
    cats = [f for f in result["foods"] if f["food_id"] >= 100]
    assert groups.count("protein") <= 3 and len(cats) <= 2


def test_unknown_values_cost_points_or_block_when_the_day_is_not_ok():
    fs = fx.foods()
    mystery = make_food(id=50, name="Mystery stew", category="Vegetables", serving_desc="1 cup (200 g)", serving_g=200,
                        nutrients=fx.nutrients(5, 2, None, 20, 30, 0), source="custom")
    ctx = fx.context(food_map={**fs, 50: mystery})
    scorer, _ = scorer_for(ctx)
    ev = scorer.evaluate(mystery, 1.0)
    assert ev.why_not is None and ev.unknown == ("potassium_mg",)
    foods = {f["food_id"]: f for f in fits.what_fits(ctx, "dinner")["foods"]}
    if 50 in foods:
        assert foods[50]["reasons"][-1] == {"code": "unknown:potassium_mg",
                                            "text": "Potassium is not listed for this food; check the label"}
    caution = fx.context(food_map={**fs, 50: mystery}, day=(fx.entry(fs[2], "breakfast", 2.2),))  # 2,035 mg K
    scorer2, room2 = scorer_for(caution)
    assert room2.nutrients["potassium_mg"].level == "caution"
    assert scorer2.evaluate(mystery, 1.0).why_not == "unknown:potassium_mg"


def test_high_portions_are_filtered_only_while_that_nutrient_is_not_ok():
    fs = fx.foods()
    scorer, _ = scorer_for(fx.context())
    assert scorer.evaluate(fs[6], 1.0).why_not is None  # banana 420 mg: high, but potassium is ok today
    busy = fx.context(day=(fx.entry(fs[2], "breakfast", 2.2),))
    scorer2, _ = scorer_for(busy)
    assert scorer2.evaluate(fs[6], 0.5).why_not == "high_warning:potassium_mg"


def test_too_many_carbs_and_free_food_when_the_meal_is_done():
    fs = fx.foods()
    full = fx.context(day=fx.context().day + (fx.entry(fs[1], "dinner", 1.25),))  # 56 g already
    scorer, room = scorer_for(full)
    assert room.carbs.gap == 3.75
    assert scorer.evaluate(fs[6], 1.0).why_not == "too_many_carbs"
    result = fits.what_fits(full, "dinner")
    beans = next(f for f in result["foods"] if f["food_id"] == 5)
    assert "free_food" not in [r["code"] for r in beans["reasons"]] or beans["servings"] <= 1
    assert any(t["code"] == "free_foods" for t in result["tips"])


def test_tips_follow_the_day_state():
    fs = fx.foods()
    busy = fx.context(day=(fx.entry(fs[2], "breakfast", 2.2),))
    codes = [t["code"] for t in fits.what_fits(busy, "dinner")["tips"]]
    assert codes[0] == "potassium_leaching" and len(codes) <= 2
    assert fits.what_fits(busy, "dinner")["tips"][0]["url"] == "/learn/eat/potassium-leaching/"


def test_dialysis_tips_for_fluid_and_protein():
    fs = fx.foods()
    targets = {**fx.HD_TARGETS}
    day = (fx.entry(fs[11], "breakfast", 11.0),)  # 1,210 mL fluid, 11 g protein
    ctx = fx.context(targets=targets, dialysis="hemodialysis", day=day, history=())
    codes = [t["code"] for t in fits.what_fits(ctx, "lunch")["tips"]]
    assert "fluid_dialysis" in codes or "potassium_leaching" in codes
    ctx2 = fx.context(targets=targets, dialysis="hemodialysis", day=(fx.entry(fs[1], "breakfast"),), history=())
    assert "add_protein" in [t["code"] for t in fits.what_fits(ctx2, "lunch")["tips"]]


def test_counter_stays_within_four_evaluations_per_eligible_food():
    counter = Counter()
    ctx = fx.context(food_map=fx.real_foods())
    fits.what_fits(ctx, "dinner", counter=counter)
    assert counter.foods <= 4 * len(fits.eligible_foods(ctx))


def test_usual_meals_are_offered_from_history():
    fs = fx.foods()
    history60 = []
    for d in ("2026-09-20", "2026-09-27", "2026-10-02"):
        history60 += [fx.hist(fs[4], d, "dinner"), fx.hist(fs[1], d, "dinner"), fx.hist(fs[5], d, "dinner")]
    ctx = fx.context(history60=history60, saved=())
    usual = [m for m in fits.what_fits(ctx, "dinner")["saved_meals"] if m["source"] == "usual"]
    assert usual and usual[0]["name"] == "Your usual dinner: egg white, rice and green beans"
    assert usual[0]["template_id"] is None
