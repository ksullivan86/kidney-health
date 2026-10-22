"""The weight and blood pressure screens say the server's numbers (ARCHITECTURE.md "Weight and blood pressure", note 10 Part B).

What a person types goes through the screens' engine (``app/static/js/engine/body_ui.js``, run by ``tests/js/body_ui_runner.mjs``)
and must come out as the server would store it: the same kilograms, the same plausibility ranges (``app/models.py`` and
``app/settings_registry.py``), the same one-decimal half-up display (``app/body.py``). The visit prep section's sums
(``bodyPage`` in ``js/engine/visitprep.js``) are checked against the server's own functions. No network."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app import body
from app.models import BloodPressureCreate, WeightCreate
from app.settings_registry import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "body_ui_runner.mjs"
DAY = "2026-10-14"


def run(*calls: tuple[str, ...]) -> list[Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the body screens' engine (CLAUDE.md, Parity)"
    payload = {"calls": [{"fn": c[0], "args": list(c[1:])} for c in calls]}
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["results"]


def one(*call: Any) -> Any:
    return run(call)[0]


def server_takes_weight(kg: float) -> bool:
    try:
        WeightCreate(date=DAY, kg=kg, context="morning")
    except ValidationError:
        return False
    return True


def server_takes_reading(systolic: int, diastolic: int, pulse: int | None = None) -> bool:
    try:
        BloodPressureCreate(date=DAY, systolic=systolic, diastolic=diastolic, pulse=pulse, context="morning")
    except ValidationError:
        return False
    return True


def day(offset: int) -> str:
    return (date.fromisoformat(DAY) + timedelta(days=offset)).isoformat()


def w(offset: int, kg: float, context: str = "morning", time: str | None = "07:15", id: int = 1) -> dict[str, Any]:
    return {"id": id, "date": day(offset), "time": time, "kg": kg, "context": context, "note": "", "source": "manual",
            "created_at": "x", "updated_at": "x"}


def r(offset: int, systolic: int, diastolic: int, time: str | None = "07:20", id: int = 1) -> dict[str, Any]:
    return {"id": id, "date": day(offset), "time": time, "systolic": systolic, "diastolic": diastolic, "pulse": None, "context": "morning",
            "note": "", "source": "manual", "created_at": "x", "updated_at": "x", "flag": body.bp_flag(systolic, diastolic)}


# --------------------------------------------------------------------------- what a person types
@pytest.mark.parametrize("lb", [44.0, 44.1, 70, 100.5, 154.25, 154.3, 200, 881.8, 881.9, 1000])
def test_a_weight_typed_in_pounds_is_stored_and_refused_as_the_server_does(lb):
    got = one("bodyUi.weightFromInput", str(lb), "lb")
    kg = body.lb_to_kg(lb)
    if server_takes_weight(kg):
        assert got == {"kg": kg}, got
        # the echo shows both units the way the server writes them: one decimal, half up
        assert one("bodyUi.echoWeight", kg, "lb") == f"{body.format_weight(kg, 'lb')} = {body.format_weight(kg, 'kg')}"
    else:
        assert "error" in got and "between 44.1 and 881.8 lb" in got["error"], got


@pytest.mark.parametrize("kg", [19.99, 20, 20.004, 70.2, 154.3, 399.99, 400, 400.01])
def test_a_weight_typed_in_kilograms_is_stored_and_refused_as_the_server_does(kg):
    got = one("bodyUi.weightFromInput", str(kg), "kg")
    stored = body.round_kg(kg)
    assert ("kg" in got) == server_takes_weight(stored), got
    if "kg" in got:
        assert got["kg"] == stored


def test_the_ends_of_the_range_in_pounds_are_the_ends_a_person_can_type():
    """The message names 44.1 and 881.8 lb: each is accepted and a tenth beyond each is not (the server's 20 and 400 kg)."""
    lo, hi = one("bodyUi.weightFromInput", "44.1", "lb"), one("bodyUi.weightFromInput", "881.8", "lb")
    assert "kg" in lo and "kg" in hi
    assert "error" in one("bodyUi.weightFromInput", "44.0", "lb") and "error" in one("bodyUi.weightFromInput", "881.9", "lb")
    assert one("bodyUi.rangeText", 20, 400, "lb") == "44.1 and 881.8 lb" and one("bodyUi.rangeText", 20, 400, "kg") == "20 and 400 kg"


@pytest.mark.parametrize("text", ["", "  ", "abc", "1e2", "-5", "70..2", "70 kg", "0x10"])
def test_what_is_not_a_number_is_refused_in_words(text):
    got = one("bodyUi.weightFromInput", text, "kg")
    assert "kg" not in got and got["error"].startswith(("Enter your weight", "Enter a number"))


def test_a_comma_is_a_decimal_mark():
    assert one("bodyUi.weightFromInput", "70,2", "kg") == {"kg": 70.2}
    assert one("bodyUi.parseNumber", "154,3") == 154.3


@pytest.mark.parametrize("systolic,diastolic,pulse", [
    (49, 20, None), (50, 20, None), (300, 200, None), (301, 200, None), (120, 19, None), (120, 80, 19), (120, 80, 20), (120, 80, 250), (120, 80, 251),
    (80, 80, None), (80, 79, None), (200, 200, None), (180, 95, 64), (120, 20, None), (50, 49, None),
])
def test_a_reading_is_accepted_and_refused_as_the_server_does(systolic, diastolic, pulse):
    got = one("bodyUi.readingFromInput", {"systolic": str(systolic), "diastolic": str(diastolic), "pulse": "" if pulse is None else str(pulse)})
    assert (not got["errors"]) == server_takes_reading(systolic, diastolic, pulse), got
    if not got["errors"]:
        assert (got["systolic"], got["diastolic"], got["pulse"]) == (systolic, diastolic, pulse)


def test_a_reading_with_the_top_number_not_above_the_bottom_one_says_so_under_the_bottom_number():
    got = one("bodyUi.readingFromInput", {"systolic": "95", "diastolic": "180", "pulse": ""})
    assert got["errors"] == {"diastolic": "The top number must be higher than the bottom number."}
    assert one("bodyUi.readingFromInput", {"systolic": "", "diastolic": "", "pulse": ""})["errors"] == {
        "systolic": "Enter the top number.", "diastolic": "Enter the bottom number."}


def test_the_echo_names_the_top_number_then_the_bottom_number():
    echo = lambda *a: one("bodyUi.echoReading", *a)  # noqa: E731
    assert echo("180", "95", "") == "Top 180, bottom 95"
    assert echo("180", "95", "64") == "Top 180, bottom 95, pulse 64"
    assert echo("", "95", "") == "Bottom 95" and echo("", "", "") == "" and echo("1800", " 59 ", "") == "Top 1800, bottom 59"
    assert echo("abc", "", "") == ""  # only digits are repeated


@pytest.mark.parametrize("kg", [0.19, 0.2, 0.9072, 1, 10, 10.01])
def test_the_alarm_typed_in_kilograms_is_accepted_as_the_registry_does(kg):
    got = one("bodyUi.alarmFromInput", str(kg), "kg")
    stored = body.round_kg(kg)
    try:
        REGISTRY["body.weight_alarm"].validate({"amount_kg": stored, "over": "days", "days": 1})
        ok = True
    except ValidationError:
        ok = False
    assert ("amount_kg" in got and got["amount_kg"] is not None) == ok, got


@pytest.mark.parametrize("lb", [0.4, 0.5, 2.2, 22, 22.1])
def test_the_alarm_typed_in_pounds_is_accepted_as_the_registry_does(lb):
    got = one("bodyUi.alarmFromInput", str(lb), "lb")
    kg = body.lb_to_kg(lb)
    try:
        REGISTRY["body.weight_alarm"].validate({"amount_kg": kg, "over": "days", "days": 1})
        ok = True
    except ValidationError:
        ok = False
    assert ("amount_kg" in got) == ok, got
    if not ok:
        assert "between 0.5 and 22 lb" in got["error"]


def test_an_empty_alarm_box_means_no_alarm():
    assert one("bodyUi.alarmFromInput", "", "lb") == {"amount_kg": None}


@pytest.mark.parametrize("systolic,diastolic", [(79, ""), (80, ""), (200, ""), (201, ""), ("", 39), ("", 40), ("", 130), ("", 131), (130, 80), (80, 80), (80, 79), ("", ""), (130, 130)])
def test_the_goal_typed_in_two_boxes_is_accepted_as_the_registry_does(systolic, diastolic):
    got = one("bodyUi.goalFromInput", str(systolic), str(diastolic))
    value = {"systolic": None if systolic == "" else systolic, "diastolic": None if diastolic == "" else diastolic}
    try:
        REGISTRY["body.bp_goal"].validate(value)
        ok = True
    except ValidationError:
        ok = False
    assert (not got["errors"]) == ok, got
    if ok:
        assert (got["systolic"], got["diastolic"]) == (value["systolic"], value["diastolic"])


# --------------------------------------------------------------------------- words
def test_amounts_and_gains_are_shown_as_the_server_shows_them():
    for kg in (0.91, 1, 1.13, 2.5, 69.99, 72.45):
        for unit in ("kg", "lb"):
            assert one("bodyUi.amountText", kg, unit) == body.format_weight(kg, unit)
    assert one("bodyUi.gainText", 0.8, "lb") == "up 1.8 lb" and one("bodyUi.gainText", -0.5, "kg") == "down 0.5 kg"
    assert one("bodyUi.gainText", 0.04, "kg") == "no change" and one("bodyUi.gainText", 0, "lb") == "no change"


def test_the_alarm_is_worded_the_way_the_care_team_gave_it():
    assert one("bodyUi.alarmSentence", {"amount_kg": 1, "over": "days", "days": 1}, "kg") == "more than 1.0 kg in 1 day"
    assert one("bodyUi.alarmSentence", {"amount_kg": 1, "over": "days", "days": 3}, "lb") == "more than 2.2 lb in 3 days"
    assert one("bodyUi.alarmSentence", {"amount_kg": 2, "over": "between_sessions", "days": 1}, "kg") == "more than 2.0 kg between sessions"


def test_the_goal_is_worded_with_the_numbers_that_are_set():
    goal = lambda s, d: one("bodyUi.goalText", {"systolic": s, "diastolic": d})  # noqa: E731
    assert goal(130, 80) == "under 130/80" and goal(130, None) == "top number under 130" and goal(None, 80) == "bottom number under 80"
    assert goal(None, None) is None


def test_the_week_sentences_follow_the_servers_week():
    readings = [r(-i, 135 + i % 3, 84 - i % 2) for i in range(5)]
    goal = {"systolic": 130, "diastolic": 80}
    week = body.blood_pressure_week(readings, DAY, goal)
    lines = one("bodyUi.weekSentences", week, goal)
    assert lines[0] == f"Last 7 days: average {week['systolic']}/{week['diastolic']} from 5 readings."
    assert week["above_goal"] is True and "at or above" in lines[1]
    few = body.blood_pressure_week(readings[:2], DAY, goal)
    assert one("bodyUi.weekSentences", few, goal)[1] == "Only 2 readings, too few to compare with your goal."
    assert one("bodyUi.weekSentences", body.blood_pressure_week([], DAY, goal), goal) == ["No readings in the last 7 days."]
    low = body.blood_pressure_week([r(-i, 120, 70) for i in range(4)], DAY, goal)
    assert one("bodyUi.weekSentences", low, goal)[1] == "The average is under your goal (under 130/80)."


def test_the_time_of_day_is_written_for_a_person():
    assert [one("bodyUi.fmtTime", t) for t in ("07:15", "00:05", "12:00", "13:30", "23:59")] == ["7:15 AM", "12:05 AM", "12:00 PM", "1:30 PM", "11:59 PM"]
    assert one("bodyUi.fmtTime", None) == ""


def test_the_dialysis_choices_are_offered_only_on_dialysis_and_never_hide_the_rows_own_choice():
    keys = lambda kind, hd, cur=None: [k for k, _ in one("bodyUi.contextChoices", kind, hd, cur)]  # noqa: E731
    assert keys("weight", False) == ["morning", "other"] and keys("weight", True) == ["morning", "before_dialysis", "after_dialysis", "other"]
    assert keys("bp", False) == ["morning", "evening", "other"] and keys("bp", True) == ["morning", "evening", "before_dialysis", "after_dialysis", "other"]
    assert keys("weight", False, "after_dialysis") == ["morning", "after_dialysis", "other"]  # an edit keeps its own choice
    for kind, contexts in (("weight", body.WEIGHT_CONTEXTS), ("bp", body.BLOOD_PRESSURE_CONTEXTS)):
        assert keys(kind, True) == list(contexts)  # every context the server knows is offered, in its order


def test_the_profile_lines_name_the_weight_in_kilograms_and_in_pounds_for_a_person_who_uses_them():
    entry = {"kg": 70.23}
    assert one("bodyUi.profileWeightHint", "latest", entry, "Oct 20", "kg") == "Latest in your log: 70.2 kg on Oct 20"
    assert one("bodyUi.profileWeightHint", "sixmonth", {"kg": 74.0}, "Apr 21", "kg") == "In your log: 74.0 kg on Apr 21"
    assert one("bodyUi.profileWeightHint", "latest", entry, "Oct 20", "lb") == f"Latest in your log: 70.2 kg ({body.shown_weight(70.23, 'lb'):.1f} lb) on Oct 20"


def test_the_look_back_for_the_profile_helper_holds_every_candidate_of_the_six_month_rule():
    """Profile reads the weights from this many days before the latest one: the rule's 182 days and its 30 days either way."""
    js = (ROOT / "app" / "static" / "js" / "engine" / "body_ui.js").read_text(encoding="utf-8")
    assert f"SIX_MONTH_LOOKBACK_DAYS = {body.SIX_MONTH_DAYS} + {body.SIX_MONTH_WINDOW_DAYS};" in js
    assert body.SIX_MONTH_DAYS + body.SIX_MONTH_WINDOW_DAYS < 366  # one list request (the route allows 366 days)


# --------------------------------------------------------------------------- the averages of each kind of weight
def test_each_kind_of_weight_is_averaged_on_its_own_over_the_last_seven_days():
    weights = [w(0, 70.0, id=1), w(-1, 70.4, id=2), w(-2, 70.0, id=3), w(-6, 71.0, id=4), w(-7, 90.0, id=5),
               w(0, 71.0, "before_dialysis", "06:40", id=6), w(0, 69.0, "after_dialysis", "11:20", id=7), w(-3, 70.0, "other", None, id=8)]
    got = one("bodyUi.weekAverages", weights, DAY)
    assert [(a["context"], a["count"], a["mean_kg"]) for a in got] == [
        ("morning", 4, body.round_kg((70.0 + 70.4 + 70.0 + 71.0) / 4)), ("before_dialysis", 1, 71.0), ("after_dialysis", 1, 69.0), ("other", 1, 70.0)]
    assert one("bodyUi.weekAverages", [], DAY) == []


# --------------------------------------------------------------------------- the charts
@pytest.mark.parametrize("lo,hi", [(69.9, 72.6), (154.0, 158.1), (120, 185), (50, 200), (70, 70), (0.5, 0.9)])
def test_nice_ticks_cover_the_values_in_steps_of_one_two_or_five(lo, hi):
    t = one("bodyUi.niceTicks", lo, hi, 4)
    assert t["min"] <= lo and t["max"] >= hi and t["ticks"][0] == t["min"] and t["ticks"][-1] == t["max"]
    assert all(b > a for a, b in zip(t["ticks"], t["ticks"][1:]))
    assert round(t["step"] / 10 ** math.floor(math.log10(t["step"]) + 1e-9), 6) in (1, 2, 5), t
    assert 2 <= len(t["ticks"]) <= 8


def test_marks_go_by_day_and_time_of_day_and_values_go_up_the_page():
    opts = {"start": day(-6), "end": DAY, "width": 340, "height": 190, "domain": {"min": 60, "max": 80}}
    got = one("axesAt", opts, [[day(-6), None], [day(-6), "00:00"], [day(-6), "23:59"], [day(-5), "00:00"], [DAY, "12:00"]], [60, 70, 80])
    assert got["days"] == 7 and got["x"][1] < got["x"][0] < got["x"][2] <= got["x"][3] + 1e-9 and got["x"][4] < 340 - 12 + 1e-6
    assert abs(got["x"][0] - (44 + 0.5 * got["slot"])) < 1e-9  # no time: the middle of the day
    assert got["y"][0] > got["y"][1] > got["y"][2] and abs(got["y"][2] - 14) < 1e-9  # the top of the plot is the top value


def test_the_labels_under_the_chart_end_on_the_last_day_and_name_a_new_month():
    labs = one("bodyUi.xLabels", "2026-09-28", "2026-10-04", 40)
    assert [x["day"] for x in labs] == [day for day in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04")]
    assert [x["month"] for x in labs] == ["Sep", None, None, "Oct", None, None, None]
    narrow = one("bodyUi.xLabels", "2026-09-05", "2026-10-04", 9)  # 30 days on a phone: every third day, counted back from the last
    assert narrow[-1]["day"] == "2026-10-04" and all(a["index"] < b["index"] for a, b in zip(narrow, narrow[1:]))


def test_a_line_is_an_svg_path_through_the_points_in_order():
    assert one("bodyUi.linePath", [{"x": 1, "y": 2.25}, {"x": 3.04, "y": 4}]) == "M1,2.3 L3,4"
    assert one("bodyUi.linePath", []) == ""


def test_the_series_and_the_tables_are_in_time_order_and_say_the_context_in_words():
    weights = [w(0, 70.0, "after_dialysis", "11:20", id=2), w(0, 71.0, "before_dialysis", "06:40", id=1), w(-1, 70.5, "morning", None, id=3)]
    series = one("bodyUi.weightSeries", weights, "lb")
    assert [p["id"] for p in series] == [3, 1, 2] and [p["after"] for p in series] == [False, False, True]
    assert series[1]["value"] == pytest.approx(71.0 / body.KG_PER_LB)  # a chart does not round
    rows = one("bodyUi.weightRows", weights, "lb")
    assert [x["value"] for x in rows] == [f"{body.shown_weight(k, 'lb'):.1f}" for k in (70.5, 71.0, 70.0)]
    assert [x["context"] for x in rows] == ["Morning", "Before dialysis", "After dialysis"] and rows[0]["time"] == ""
    readings = [r(0, 185, 95, id=2), r(-1, 120, 80, "19:10", id=1)]
    got = one("bodyUi.readingRows", readings)
    assert [(x["systolic"], x["diastolic"], x["flagged"]) for x in got] == [(120, 80, False), (185, 95, True)] and got[0]["time"] == "7:10 PM"


# --------------------------------------------------------------------------- visit prep
def test_the_six_month_change_is_the_servers():
    weights = [w(-190, 74.0, id=1), w(-182, 73.5, id=2), w(-175, 72.0, id=3), w(-60, 71.0, id=4), w(0, 70.2, id=5)]
    page = one("visitPrep.bodyPage", {"weights": weights, "readings": [], "summary": {"units": "kg", "weight": {"latest": weights[-1], "alarm": None},
               "bp": {"goal": {"systolic": None, "diastolic": None}}}, "today": DAY, "periodDays": 28})
    assert page["sixMonth"] == body.six_month_change(weights)
    assert page["latest"]["id"] == 5 and page["units"] == "kg" and page["sessions"] is None and page["empty"] is False


def test_the_latest_weight_comes_from_the_summary_even_when_the_list_is_short():
    old = w(-400, 69.0, id=9)
    page = one("visitPrep.bodyPage", {"weights": [], "readings": [], "summary": {"units": "lb", "weight": {"latest": old, "alarm": None},
               "bp": {"goal": {"systolic": None, "diastolic": None}}}, "today": DAY, "periodDays": 28})
    assert page["latest"]["id"] == 9 and page["sixMonth"] is None and page["empty"] is False
    assert one("visitPrep.bodyPage", {"weights": [], "readings": [], "summary": None, "today": DAY, "periodDays": 28})["empty"] is True


def test_the_seven_day_window_is_the_servers_week_and_the_thirty_day_window_uses_the_same_rule():
    readings = [r(-i, 118 + (i * 7) % 25, 70 + (i * 5) % 14, id=i + 1) for i in range(0, 40, 2)]
    goal = {"systolic": 130, "diastolic": 80}
    week = body.blood_pressure_week(readings, DAY, goal)
    got = one("visitPrep.readingsWindow", readings, DAY, 7, goal)
    assert (got["count"], got["systolic"], got["diastolic"], got["few"]) == (week["count"], week["systolic"], week["diastolic"], week["few"])
    month = one("visitPrep.readingsWindow", readings, DAY, 30, goal)
    inside = [x for x in readings if day(-29) <= x["date"] <= DAY]
    assert month["count"] == len(inside) == 15
    assert month["systolic"] == int(body._half_up(sum(x["systolic"] for x in inside) / len(inside), 0))
    assert month["diastolic"] == int(body._half_up(sum(x["diastolic"] for x in inside) / len(inside), 0))
    # "at or above": a top number at or above 130 or a bottom number at or above 80 ("under 130/80": 130 is not under)
    assert month["at_or_above"] == sum(1 for x in inside if x["systolic"] >= 130 or x["diastolic"] >= 80)
    boundary = [r(0, 130, 70, id=1), r(-1, 129, 79, id=2), r(-2, 129, 80, id=3)]
    assert one("visitPrep.readingsWindow", boundary, DAY, 7, goal)["at_or_above"] == 2
    assert one("visitPrep.readingsWindow", boundary, DAY, 7, {"systolic": None, "diastolic": None})["at_or_above"] is None
    assert one("visitPrep.readingsWindow", boundary, DAY, 7, {"systolic": 130, "diastolic": None})["at_or_above"] == 1
    assert one("visitPrep.readingsWindow", [], DAY, 30, goal)["systolic"] is None


def test_the_readings_the_handbook_points_to_are_the_servers_flags_newest_first_within_the_period():
    readings = [r(-40, 190, 100, id=1), r(-10, 185, 95, id=2), r(-5, 120, 80, id=3), r(-2, 150, 120, id=4)]
    page = one("visitPrep.bodyPage", {"weights": [], "readings": readings, "summary": {"units": "kg", "weight": {"latest": None, "alarm": None},
               "bp": {"goal": {"systolic": None, "diastolic": None}}}, "today": DAY, "periodDays": 28})
    assert [x["id"] for x in page["bp"]["flagged"]] == [4, 2]  # the 40-day-old one is outside a 28-day period; newest first
    assert page["bp"]["flag"] == body.flag_of("blood_pressure")  # the server's words, untouched
    quiet = one("visitPrep.bodyPage", {"weights": [], "readings": [r(-2, 140, 90)], "summary": None, "today": DAY, "periodDays": 28})
    assert quiet["bp"]["flagged"] == [] and quiet["bp"]["flag"] is None


def test_the_gains_between_sessions_are_the_servers_comparison():
    alarm = {"amount_kg": 1.5, "over": "between_sessions", "days": 1}
    weights = [w(-6, 70.0, "after_dialysis", "11:20", 1), w(-4, 71.2, "before_dialysis", "06:40", 2), w(-4, 70.1, "after_dialysis", "11:20", 3),
               w(-2, 72.0, "before_dialysis", "06:40", 4), w(-2, 70.3, "after_dialysis", "11:20", 5), w(0, 72.1, "before_dialysis", "06:40", 6)]
    rows = one("visitPrep.sessionGains", weights, alarm, 69.5)
    assert [x["weight"]["id"] for x in rows] == [6, 4, 2]  # newest session first
    # the newest one is exactly what the Today card's alarm check says about the latest weight
    check = body.weight_alarm_check(weights, alarm, dry_weight_kg=69.5, unit="kg")
    assert rows[0]["gain_kg"] == check["gain_kg"] == 1.8 and rows[0]["over_alarm"] is check["over_alarm"] is True
    assert rows[0]["reference_kind"] == check["reference_kind"] == "after_dialysis" and rows[0]["reference"]["id"] == check["reference"]["id"] == 5
    assert [x["gain_kg"] for x in rows] == [1.8, 1.9, 1.2] and [x["over_alarm"] for x in rows] == [True, True, False]
    # a session with no weight after a session in the 7 days before it: the dry weight in Profile, else nothing
    first = [weights[1]]
    assert one("visitPrep.sessionGains", first, alarm, 69.5)[0]["reference_kind"] == "dry_weight"
    assert one("visitPrep.sessionGains", first, alarm, 69.5)[0]["gain_kg"] == body.round_kg(71.2 - 69.5)
    nothing = one("visitPrep.sessionGains", first, alarm, None)[0]
    assert nothing["gain_kg"] is None and nothing["over_alarm"] is None and nothing["reference_kind"] is None
    # an alarm that is not "between sessions" is not a limit for a gain between sessions; no alarm, no verdict
    assert one("visitPrep.sessionGains", weights, {"amount_kg": 1.5, "over": "days", "days": 1}, 69.5)[0]["over_alarm"] is None
    assert one("visitPrep.sessionGains", weights, None, 69.5)[0]["over_alarm"] is None
    assert len(one("visitPrep.sessionGains", [w(-i, 71.0, "before_dialysis", id=i + 1) for i in range(10)], None, 70.0)) == 6  # up to 6


def test_the_sessions_are_listed_only_on_hemodialysis_and_the_alarm_comes_from_the_summary():
    weights = [w(-2, 70.3, "after_dialysis", "11:20", 5), w(0, 72.1, "before_dialysis", "06:40", 6)]
    alarm = body.weight_alarm_check(weights, {"amount_kg": 1.5, "over": "between_sessions", "days": 1}, dry_weight_kg=None, unit="kg")
    summary = {"units": "kg", "weight": {"latest": weights[-1], "alarm": alarm}, "bp": {"goal": {"systolic": None, "diastolic": None}}}
    hd = one("visitPrep.bodyPage", {"weights": weights, "readings": [], "summary": summary, "today": DAY, "periodDays": 28, "dialysis": "hemodialysis", "dryWeightKg": 70})
    assert hd["sessions"]["alarm"] == {"amount_kg": 1.5, "over": "between_sessions", "days": 1} and hd["sessions"]["rows"][0]["over_alarm"] is True
    none = one("visitPrep.bodyPage", {"weights": weights, "readings": [], "summary": summary, "today": DAY, "periodDays": 28, "dialysis": "peritoneal"})
    assert none["sessions"] is None
