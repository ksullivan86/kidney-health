"""Note 06 §6.2 budget vectors TV-B1 … TV-B7, plus edge cases of the room maths."""
from __future__ import annotations

import math

import pytest

import fixtures as fx
from app.guidance import budget
from app.guidance.state import Prefs


def test_tv_b1_phosphorus_allowance_is_clamped_to_80_percent():
    ctx = fx.context()
    allowance, n, total = budget.week_allowance(1000, ctx.history, fx.DATE)
    assert (n, total) == (4, 4400)  # raw 1,000 × 5 − 4,400 = 600
    assert allowance == 800


def test_tv_b2_no_logged_days_and_six_heavy_days():
    assert budget.week_allowance(1000, (), fx.DATE)[0] == 1000
    fs = fx.foods()
    six = [fx.hist(fs[1], f"2026-09-{d:02d}", "lunch", override={"phosphorus_mg": 900.0}) for d in range(29, 31)]
    six += [fx.hist(fs[1], f"2026-10-{d:02d}", "lunch", override={"phosphorus_mg": 900.0}) for d in range(1, 5)]
    allowance, n, total = budget.week_allowance(1000, six, fx.DATE)
    assert (n, total) == (6, 5400)  # raw 1,000 × 7 − 5,400 = 1,600
    assert allowance == 1200


def test_week_allowance_ignores_days_outside_the_previous_six_and_today():
    fs = fx.foods()
    old = [fx.hist(fs[1], "2026-09-28", "lunch", override={"phosphorus_mg": 5000.0}),  # 7 days back
           fx.hist(fs[1], fx.DATE, "lunch", override={"phosphorus_mg": 5000.0})]  # today: not history
    assert budget.week_allowance(1000, old, fx.DATE)[1:] == (0, 0)


def test_tv_b3_open_slots():
    ctx = fx.context()
    assert budget.open_slots("dinner", ctx.day) == ["dinner", "snack"]  # lunch is planned, so not open
    assert budget.open_slots("snack", ctx.day) == ["snack", "dinner"]
    assert budget.open_slots("breakfast", ()) == ["breakfast", "lunch", "dinner", "snack"]
    assert budget.open_slots("lunch", ctx.day) == ["lunch", "dinner", "snack"]  # the meal itself stays open


def test_tv_b4_room_for_dinner():
    room = budget.meal_room(fx.context(), "dinner")
    k, p, na = room.nutrients["potassium_mg"], room.nutrients["phosphorus_mg"], room.nutrients["sodium_mg"]
    assert (k.remaining, round(k.share), k.cap, k.room) == (1200, 800, 750, 750)
    assert (na.remaining, round(na.share), na.cap, na.room) == (900, 600, 600, 600)
    assert p.allowance == 800 and p.remaining == 250 and round(p.share, 1) == 166.7 and round(p.room, 1) == 166.7
    assert p.basis == "week_average" and k.basis == "day"
    assert room.carbs.gap == 60 and room.carbs.tolerance == 10
    assert round(room.protein.aim, 2) == 9.33 and round(room.protein.aim_min, 2) == 4.67
    assert {item.level for item in room.nutrients.values()} == {"ok"}
    assert "fluid_ml" not in room.nutrients and math.isinf(room.room_of("fluid_ml"))


def test_tv_b5_room_for_the_snack_slot():
    room = budget.meal_room(fx.context(), "snack")
    assert room.nutrients["potassium_mg"].room == 375  # min(375 cap, 400 share)
    assert room.nutrients["sodium_mg"].room == 300
    assert round(room.nutrients["phosphorus_mg"].room, 1) == 83.3
    assert room.carbs.goal == 30
    assert round(room.protein.aim, 2) == 4.67


def test_tv_b6_interdialytic_allowance_on_a_long_gap():
    """Hemodialysis Mon/Wed/Fri, Sunday 2026-10-04, 5,800 mg potassium eaten Friday and Saturday."""
    fs = fx.foods()
    history = [fx.hist(fs[2], "2026-10-02", "dinner", override={"potassium_mg": 2900.0}),
               fx.hist(fs[2], "2026-10-03", "dinner", override={"potassium_mg": 2900.0})]
    assert budget.interdialytic_allowance(2500, "potassium_mg", history, "2026-10-04", (0, 2, 4)) == 1700
    ctx = fx.context(date="2026-10-04", day=(), history=history, dialysis="hemodialysis", dialysis_days=(0, 2, 4),
                     targets={**fx.TARGETS, "fluid_ml": 1500})
    k = budget.meal_room(ctx, "breakfast").nutrients["potassium_mg"]
    assert k.allowance == 1700 and k.basis == "interdialytic"
    # On a dialysis day the interval restarts: the allowance is the daily target again.
    assert budget.interdialytic_allowance(2500, "potassium_mg", history, "2026-10-05", (0, 2, 4)) == 2500
    assert budget.interdialytic_allowance(2500, "potassium_mg", history, "2026-10-04", ()) is None


def test_tv_b7_a_low_treatment_counts_for_minerals_but_not_meal_carbs():
    fs = fx.foods()
    day = fx.context().day + (fx.entry(fs[10], "dinner", purpose="hypo"),)
    room = budget.meal_room(fx.context(day=day), "dinner")
    assert room.carbs.in_meal == 0 and room.carbs.hypo_excluded == 16
    totals = budget.day_totals(day)
    assert totals.projected["carbs_g"] == 55 + 60 + 16  # the day still counts it
    assert totals.meal_groups["dinner"] == frozenset()  # and it is not "a meal"


def test_levels_follow_the_projected_day_and_raise_the_phosphorus_weight():
    fs = fx.foods()
    heavy = (fx.entry(fs[13], "breakfast", 3.0),)  # 1,800 K, 750 P, 1,500 Na
    room = budget.meal_room(fx.context(day=heavy), "lunch")
    assert room.nutrients["potassium_mg"].level == "ok"  # 1,800 / 2,500 = 72 %
    assert room.nutrients["sodium_mg"].level == "ok"  # 1,500 / 2,000 = 75 %
    assert room.nutrients["phosphorus_mg"].level == "caution" and room.usage_weight["phosphorus_mg"] == 3


def test_over_allowance_leaves_no_room():
    fs = fx.foods()
    over = (fx.entry(fs[2], "breakfast", 3.0),)  # 2,775 mg potassium
    room = budget.meal_room(fx.context(day=over), "dinner")
    assert room.nutrients["potassium_mg"].level == "over" and room.nutrients["potassium_mg"].room == 0


def test_without_diabetes_or_targets_parts_of_the_room_are_absent():
    ctx = fx.context(diabetes="none", targets={"potassium_mg": 2500})
    room = budget.meal_room(ctx, "dinner")
    assert room.carbs is None and room.protein is None
    assert set(room.nutrients) == {"potassium_mg"}


def test_snack_goal_explicit_and_default_and_tolerance_setting():
    ctx = fx.context(targets={**fx.TARGETS, "carbs_per_snack_g": 20}, prefs=Prefs(carb_tolerance_g=5))
    room = budget.meal_room(ctx, "snack")
    assert room.carbs.goal == 20 and room.carbs.tolerance == 5
    assert budget.snack_carb_goal({}, 45) == 25  # 5 × round(4.5) with half up
    assert budget.snack_carb_goal({}, 20) == 15  # never below one carbohydrate choice


@pytest.mark.parametrize("bad", [None, "x", {"max": None}, float("nan"), float("inf"), -5, 0, True])
def test_unusable_targets_are_treated_as_untracked(bad):
    room = budget.meal_room(fx.context(targets={"potassium_mg": bad, "carbs_per_meal_g": 60}), "dinner")
    assert "potassium_mg" not in room.nutrients
