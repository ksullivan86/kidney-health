"""Unit tests for the pure period maths in app/periods.py and the projected-alert builders."""
from __future__ import annotations

from datetime import date

import pytest

from app import nutrients as n
from app import periods as p

# 2026-10-05 is a Monday.
MON, TUE, WED, THU, FRI, SAT, SUN = ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11")


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #


def test_period_length_and_date_range():
    assert p.period_length("2026-09-29", "2026-10-05") == 7
    assert p.period_length(date(2026, 10, 5), "2026-10-05") == 1
    assert p.date_range("2026-10-03", "2026-10-05") == ["2026-10-03", "2026-10-04", "2026-10-05"]
    with pytest.raises(ValueError):
        p.period_length("2026-10-06", "2026-10-05")


def test_previous_period_is_the_same_length_immediately_before():
    assert p.previous_period("2026-09-29", "2026-10-05") == (date(2026, 9, 22), date(2026, 9, 28))
    assert p.previous_period("2026-10-05", "2026-10-05") == (date(2026, 10, 4), date(2026, 10, 4))
    # month and year boundaries
    assert p.previous_period("2026-01-01", "2026-01-31") == (date(2025, 12, 1), date(2025, 12, 31))


@pytest.mark.parametrize(
    "day, week_start, expected",
    [
        (MON, "monday", (MON, SUN)),
        (SUN, "monday", (MON, SUN)),
        (WED, "monday", (MON, SUN)),
        ("2026-10-04", "sunday", ("2026-10-04", "2026-10-10")),  # a Sunday starts its own week
        (MON, "sunday", ("2026-10-04", "2026-10-10")),
        (SAT, "sunday", ("2026-10-04", "2026-10-10")),
        (SUN, "sunday", (SUN, "2026-10-17")),
        ("2026-01-01", "monday", ("2025-12-29", "2026-01-04")),  # year boundary
    ],
)
def test_week_bounds(day, week_start, expected):
    start, end = p.week_bounds(day, week_start)
    assert (start.isoformat(), end.isoformat()) == expected
    assert (end - start).days == 6


def test_week_bounds_rejects_unknown_week_start():
    with pytest.raises(ValueError):
        p.week_bounds(MON, "tuesday")


def test_normalise_dialysis_days():
    assert p.normalise_dialysis_days(None) == []
    assert p.normalise_dialysis_days([]) == []
    assert p.normalise_dialysis_days([4, 0, 2, 0]) == [0, 2, 4]
    assert p.normalise_dialysis_days((6,)) == [6]
    for bad in ([7], [-1], ["1"], [True], [1.5]):
        with pytest.raises(ValueError):
            p.normalise_dialysis_days(bad)


# --------------------------------------------------------------------------- #
# Period aggregation
# --------------------------------------------------------------------------- #


def test_summary_target_uses_max_for_limits_and_ranges_and_omits_untracked():
    assert p.summary_target("potassium_mg", 2500) == 2500
    assert p.summary_target("protein_g", {"min": 42, "max": 56}) == 56
    assert p.summary_target("protein_g", {"min": 42}) is None
    assert p.summary_target("fluid_ml", None) is None
    assert p.summary_target("fluid_ml", 0) is None


TARGETS = {"potassium_mg": 2500, "phosphorus_mg": 1000, "protein_g": {"min": 42, "max": 56}, "carbs_g": 236, "fluid_ml": None}
DAY_TOTALS = {
    # current period 2026-09-29 .. 2026-10-05 (three logged days)
    "2026-09-29": {"potassium_mg": 2000, "phosphorus_mg": 800, "protein_g": 50, "carbs_g": 200},
    "2026-10-01": {"potassium_mg": 3100, "phosphorus_mg": 1200, "protein_g": 60, "carbs_g": 250},
    "2026-10-03": {"potassium_mg": 1800, "phosphorus_mg": 700, "protein_g": 40, "carbs_g": 180},
    # previous period 2026-09-22 .. 2026-09-28 (two logged days)
    "2026-09-25": {"potassium_mg": 2400, "phosphorus_mg": 1000, "protein_g": 55, "carbs_g": 220},
    "2026-09-27": {"potassium_mg": 2600, "phosphorus_mg": 900, "protein_g": 45, "carbs_g": 200},
    # after the period: must be ignored
    "2026-10-06": {"potassium_mg": 9000, "phosphorus_mg": 9000, "protein_g": 900, "carbs_g": 900},
}


def test_summarize_period_matches_contract_shape_and_maths():
    s = p.summarize_period("2026-09-29", "2026-10-05", DAY_TOTALS, TARGETS, 0.8)
    assert (s["start"], s["end"], s["days"], s["logged_days"]) == ("2026-09-29", "2026-10-05", 7, 3)
    assert set(s["nutrients"]) == {"potassium_mg", "phosphorus_mg", "protein_g", "carbs_g"}  # null fluid omitted

    k = s["nutrients"]["potassium_mg"]
    assert k == {
        "role": "limit", "target": 2500, "total": 6900, "average": 2300, "fraction": 0.92, "level": "caution",
        "days_over": 1, "max_day": {"date": "2026-10-01", "value": 3100},
        "previous_average": 2500, "change_pct": -8.0, "assessment": "daily",
    }
    ph = s["nutrients"]["phosphorus_mg"]
    assert ph["total"] == 2700 and ph["average"] == 900 and ph["fraction"] == 0.9 and ph["level"] == "caution"
    assert ph["days_over"] == 1 and ph["max_day"] == {"date": "2026-10-01", "value": 1200}
    assert ph["previous_average"] == 950 and ph["change_pct"] == -5.3 and ph["assessment"] == "weekly_average"

    pr = s["nutrients"]["protein_g"]
    assert pr["role"] == "range" and pr["target"] == 56.0
    assert pr["total"] == 150.0 and pr["average"] == 50.0 and pr["fraction"] == 0.89 and pr["level"] == "caution"
    assert pr["days_over"] == 1 and pr["max_day"] == {"date": "2026-10-01", "value": 60.0}
    assert pr["previous_average"] == 50.0 and pr["change_pct"] == 0.0 and pr["assessment"] == "weekly_average"

    c = s["nutrients"]["carbs_g"]
    assert c["role"] == "track" and c["assessment"] == "daily" and c["days_over"] == 1 and c["average"] == 210.0


def test_summarize_period_level_follows_warn_fraction():
    s = p.summarize_period("2026-09-29", "2026-10-05", DAY_TOTALS, {"potassium_mg": 2500}, 0.95)
    assert s["nutrients"]["potassium_mg"]["level"] == "ok"  # 0.92 < 0.95
    s = p.summarize_period("2026-09-29", "2026-10-05", DAY_TOTALS, {"potassium_mg": 2000}, 0.8)
    assert s["nutrients"]["potassium_mg"]["level"] == "over" and s["nutrients"]["potassium_mg"]["days_over"] == 1


def test_summarize_period_without_logged_days():
    s = p.summarize_period("2030-01-01", "2030-01-07", DAY_TOTALS, TARGETS, 0.8)
    assert s["logged_days"] == 0 and s["days"] == 7
    k = s["nutrients"]["potassium_mg"]
    assert k["total"] == 0 and k["average"] is None and k["fraction"] is None and k["level"] == "ok"
    assert k["days_over"] == 0 and k["max_day"] is None and k["previous_average"] is None and k["change_pct"] is None


def test_summarize_period_previous_period_edge_cases():
    # current data, no previous data -> previous_average / change_pct null
    s = p.summarize_period("2026-09-29", "2026-10-05", {"2026-10-01": {"potassium_mg": 1000}}, {"potassium_mg": 2500}, 0.8)
    k = s["nutrients"]["potassium_mg"]
    assert k["average"] == 1000 and k["previous_average"] is None and k["change_pct"] is None
    # previous data, no current data -> previous_average set, change_pct null
    s = p.summarize_period("2026-09-29", "2026-10-05", {"2026-09-25": {"potassium_mg": 1000}}, {"potassium_mg": 2500}, 0.8)
    k = s["nutrients"]["potassium_mg"]
    assert k["average"] is None and k["previous_average"] == 1000 and k["change_pct"] is None
    # previous average of zero -> no percentage (division by zero avoided)
    s = p.summarize_period(
        "2026-09-29", "2026-10-05",
        {"2026-10-01": {"potassium_mg": 1000}, "2026-09-25": {"potassium_mg": 0}},
        {"potassium_mg": 2500}, 0.8,
    )
    assert s["nutrients"]["potassium_mg"]["previous_average"] == 0
    assert s["nutrients"]["potassium_mg"]["change_pct"] is None
    # the day right before the period belongs to the previous period, the day after is ignored
    s = p.summarize_period(
        "2026-09-29", "2026-10-05",
        {"2026-09-28": {"potassium_mg": 500}, "2026-10-06": {"potassium_mg": 5000}, "2026-10-05": {"potassium_mg": 1000}},
        {"potassium_mg": 2500}, 0.8,
    )
    assert s["nutrients"]["potassium_mg"]["previous_average"] == 500 and s["nutrients"]["potassium_mg"]["change_pct"] == 100.0


def test_summarize_period_single_day_and_invalid_order():
    s = p.summarize_period("2026-10-01", "2026-10-01", DAY_TOTALS, {"potassium_mg": 2500}, 0.8)
    assert s["days"] == 1 and s["logged_days"] == 1 and s["nutrients"]["potassium_mg"]["average"] == 3100
    assert s["nutrients"]["potassium_mg"]["previous_average"] is None  # 2026-09-30 not logged
    with pytest.raises(ValueError):
        p.summarize_period("2026-10-05", "2026-10-01", DAY_TOTALS, TARGETS, 0.8)


def test_assessment_table_matches_the_contract():
    assert {k for k, v in p.ASSESSMENT.items() if v == "daily"} == {"potassium_mg", "sodium_mg", "fluid_ml", "carbs_g"}
    assert {k for k, v in p.ASSESSMENT.items() if v == "weekly_average"} == {"phosphorus_mg", "protein_g", "calories_kcal", "calcium_mg"}


# --------------------------------------------------------------------------- #
# Interdialytic interval
# --------------------------------------------------------------------------- #


def test_interdialytic_interval_end_on_a_dialysis_day_counts_toward_the_next_session():
    iv = p.interdialytic_interval(MON, [0, 2, 4])
    assert iv == {"since": MON, "end": MON, "days": 1, "next": WED, "capped": False}


def test_interdialytic_interval_weekend_gap_mon_wed_fri():
    iv = p.interdialytic_interval("2026-10-04", [0, 2, 4])  # Sunday
    assert (iv["since"], iv["days"], iv["next"], iv["capped"]) == ("2026-10-02", 3, MON, False)
    iv = p.interdialytic_interval(TUE, [0, 2, 4])
    assert (iv["since"], iv["days"], iv["next"]) == (MON, 2, WED)
    iv = p.interdialytic_interval(SAT, [0, 2, 4])
    assert (iv["since"], iv["days"], iv["next"]) == (FRI, 2, "2026-10-12")


def test_interdialytic_interval_tue_thu_sat_schedule_wraps_the_week():
    iv = p.interdialytic_interval(MON, [1, 3, 5])
    assert (iv["since"], iv["days"], iv["next"]) == ("2026-10-03", 3, TUE)


def test_interdialytic_interval_once_a_week_spans_seven_days_without_capping():
    iv = p.interdialytic_interval(SUN, [0])
    assert (iv["since"], iv["days"], iv["next"], iv["capped"]) == (MON, 7, "2026-10-12", False)


def test_interdialytic_interval_caps_when_no_dialysis_day_in_window():
    iv = p.interdialytic_interval(THU, [0], max_days=3)
    assert iv["capped"] is True
    assert (iv["since"], iv["days"], iv["next"]) == (TUE, 3, "2026-10-12")
    assert p.MAX_INTERDIALYTIC_DAYS == 7


def test_interdialytic_interval_without_dialysis_days_is_null():
    assert p.interdialytic_interval(MON, []) is None
    assert p.interdialytic_interval(MON, None) is None
    assert p.interdialytic_interval(MON, [9, -3]) is None  # out-of-range weekdays are ignored


def test_interdialytic_block_totals_over_the_interval_against_target_times_days():
    iv = p.interdialytic_interval("2026-10-04", [0, 2, 4])  # Fri 10-02 .. Sun 10-04
    day_totals = {
        "2026-10-01": {"potassium_mg": 9999, "sodium_mg": 9999, "fluid_ml": 9999},  # before the interval
        "2026-10-02": {"potassium_mg": 2000, "sodium_mg": 1500, "fluid_ml": 1000},
        "2026-10-03": {"potassium_mg": 2500},
        "2026-10-04": {"potassium_mg": 1500, "sodium_mg": 2500},
    }
    targets = {"potassium_mg": 2500, "sodium_mg": 2000, "fluid_ml": None, "protein_g": {"min": 42, "max": 56}}
    block = p.interdialytic_block(iv, day_totals, targets, 0.8)
    assert set(block) == {"since", "days", "next", "nutrients"}
    assert (block["since"], block["days"], block["next"]) == ("2026-10-02", 3, MON)
    assert set(block["nutrients"]) == {"potassium_mg", "sodium_mg"}  # fluid untracked, protein not interdialytic
    assert block["nutrients"]["potassium_mg"] == {"total": 6000, "limit": 7500, "fraction": 0.8, "level": "caution"}
    assert block["nutrients"]["sodium_mg"] == {"total": 4000, "limit": 6000, "fraction": 0.67, "level": "ok"}
    # a fluid target brings fluid in
    block = p.interdialytic_block(iv, day_totals, {"fluid_ml": 1500}, 0.8)
    assert block["nutrients"] == {"fluid_ml": {"total": 1000, "limit": 4500, "fraction": 0.22, "level": "ok"}}


def test_summary_notes():
    base = p.summary_notes("none", [], None)
    assert base == [p.NOTE_DAILY, p.NOTE_WEEKLY, p.NOTE_CARBS]
    assert p.summary_notes("peritoneal", [0, 2], None) == base
    assert p.summary_notes("hemodialysis", [], None) == base + [p.NOTE_NO_DIALYSIS_DAYS]
    iv = p.interdialytic_interval(MON, [0, 2, 4])
    assert p.summary_notes("hemodialysis", [0, 2, 4], iv) == base + [p.NOTE_INTERDIALYTIC]
    capped = p.interdialytic_interval(THU, [0], max_days=3)
    notes = p.summary_notes("hemodialysis", [0], capped)
    assert notes[-1] == p.NOTE_CAPPED.format(n=7) and "capped at 7 days" in notes[-1]


# --------------------------------------------------------------------------- #
# Projected alerts (nutrients.py)
# --------------------------------------------------------------------------- #


def test_build_projected_alerts_wording_and_order():
    status = n.daily_status(
        {"potassium_mg": 2600, "sodium_mg": 1700, "carbs_g": 50},
        {"potassium_mg": 2500, "sodium_mg": 2000, "carbs_g": 236},
        0.8,
    )
    alerts = n.build_projected_alerts(status)
    assert [a["nutrient"] for a in alerts] == ["potassium_mg", "sodium_mg"]  # over first, carbs fine
    assert alerts[0] == {
        "level": "over", "nutrient": "potassium_mg",
        "message": "If you eat what's planned, potassium reaches 104 % of today's limit (2600 / 2500 mg)",
    }
    assert alerts[1]["level"] == "caution"
    assert alerts[1]["message"] == "If you eat what's planned, sodium reaches 85 % of today's limit (1700 / 2000 mg)"
    assert n.build_projected_alerts(n.daily_status({"potassium_mg": 10}, {"potassium_mg": 2500}, 0.8)) == []


def test_projected_meal_carb_alerts():
    meals = {"breakfast": {"carbs_g": 70}, "lunch": {"carbs_g": 60}, "dinner": {}, "snack": {"carbs_g": 61}}
    alerts = n.projected_meal_carb_alerts(meals, 60)
    assert [(a["meal"], a["level"], a["nutrient"]) for a in alerts] == [("breakfast", "over", "carbs_g"), ("snack", "over", "carbs_g")]
    assert alerts[0]["message"] == "If you eat what's planned, breakfast carbohydrate reaches 70 / 60 g (over the per-meal goal)"
    assert n.projected_meal_carb_alerts(meals, None) == []


def test_summarize_period_ignores_non_finite_stored_values_and_targets():
    inf = float("inf")
    totals = {MON: {"potassium_mg": inf, "phosphorus_mg": 500}, TUE: {"potassium_mg": 1000, "phosphorus_mg": 700}}
    out = p.summarize_period(MON, TUE, totals, {"potassium_mg": 2500, "phosphorus_mg": inf, "sodium_mg": 2000})
    k = out["nutrients"]["potassium_mg"]
    assert k["total"] == 1000 and k["average"] == 500 and k["max_day"] == {"date": TUE, "value": 1000}
    assert "phosphorus_mg" not in out["nutrients"]  # infinite target = not tracked
    assert p.summary_target("phosphorus_mg", inf) is None and p.summary_target("phosphorus_mg", {"max": float("nan")}) is None
    block = p.interdialytic_block({"since": MON, "end": TUE, "days": 2, "next": WED}, totals, {"potassium_mg": 2500})
    assert block["nutrients"]["potassium_mg"]["total"] == 1000
