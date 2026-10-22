#!/usr/bin/env python3
"""Generate tests/data/body_vectors.json: parity vectors for the browser twin of the weight and blood pressure log.

    python3 tests/data/gen_body_vectors.py           # rewrite the file
    python3 tests/data/gen_body_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/body.py`` and the models of ``app/models.py`` (note 10 §4.4, §4.7), and replayed on the
JavaScript side by ``node tests/js/run_vectors.mjs`` against ``app/static/js/engine/body.js`` (the units, the weight-gain alarm,
the 7-day means against the goal, the six-month change, the flags, the API shape of a row, the summary) and the demo API
``app/static/js/mock/body.js``:

* ``constants``: the tables the twin must equal (contexts, sources, limits, the handbook's words);
* ``unit_cases``, ``alarm_cases``, ``week_cases``, ``six_month_cases``, ``flag_cases``, ``row_cases``, ``summary_cases``: one
  call of a pure function and what the server's function answers;
* ``context_cases`` and ``watch_cases`` (design note 12): ``body.context_for`` and ``body.is_watch_source``, which the Apple Health reader
  (``KH.appleHealth.contextOf`` and ``isWatchSource``, ``js/engine/apple_health.js``) must answer the same way for a phone shortcut and
  the file import to give a reading the same context; ``node tests/js/run_vectors.mjs`` checks the reader against them;
* ``script``: one list of requests, run in order against a fresh server (here) and a fresh demo account (there), with the answers
  the server gave: every route, every refusal and its exact text. A ``{{today:N}}`` in a path or a body is the date N days from
  today (negative: earlier), so the "not in the future" rule is checked on both sides at today's date; ``created_at`` and
  ``updated_at`` are written as ``<ts>``. A step with ``"quiet": true`` is set-up (a setting, the profile): only whether it
  worked is compared.

Needs the app's dependencies (it starts the app against a temporary database).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "body_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import body as B  # noqa: E402
from app import models as Mo  # noqa: E402

D1, D2, D3, D4, D5, D6 = "2025-03-03", "2025-03-04", "2025-03-05", "2025-03-10", "2025-03-11", "2025-03-12"
TODAY = re.compile(r"\{\{today:(-?\d+)\}\}")
MARKER_RANGE = range(-45, 6)
POST, PUT, GET, DELETE, PATCH = "POST", "PUT", "GET", "DELETE", "PATCH"
STAMP = "2026-10-05T12:30:00.000000Z"


def w(kg: Any = 70.0, when: str = D1, context: Any = "morning", **extra: Any) -> dict[str, Any]:
    return {"date": when, "kg": kg, "context": context, **extra}


def bp(systolic: Any = 128, diastolic: Any = 78, when: str = D1, context: Any = "morning", **extra: Any) -> dict[str, Any]:
    return {"date": when, "systolic": systolic, "diastolic": diastolic, "context": context, **extra}


# --------------------------------------------------------------------------- pure functions


def wrow(kg: float, when: str, context: str = "morning", time: str | None = None, n: int = 1) -> dict[str, Any]:
    return {"id": n, "date": when, "time": time, "kg": kg, "context": context, "note": "", "source": "manual", "created_at": STAMP,
            "updated_at": STAMP}


def series(*specs: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Weights with ids 1, 2, ... in the order given (the order of the list): each spec is (kg, date[, context[, time]])."""
    out = []
    for n, spec in enumerate(specs, start=1):
        kg, when, *rest = spec
        out.append(wrow(kg, when, rest[0] if rest else "morning", rest[1] if len(rest) > 1 else None, n))
    return out


def rrow(systolic: int, diastolic: int, when: str, n: int = 1, time: str | None = None, context: str = "morning", pulse: int | None = None) -> dict[str, Any]:
    return {"id": n, "date": when, "time": time, "systolic": systolic, "diastolic": diastolic, "pulse": pulse, "context": context, "note": "",
            "source": "manual", "created_at": STAMP, "updated_at": STAMP, "flag": B.bp_flag(systolic, diastolic)}


def unit_cases() -> list[dict[str, Any]]:
    cases = []
    for lb in (0.5, 1, 2.2, 100, 154.25, 154.3, 154.35, 154.45, 154.5, 165.3465, 200, 220.462, 330.693, 400, 0.01, 44.0925, 881.849):
        kg = B.lb_to_kg(lb)
        cases.append({"lb": lb, "kg": kg, "shown_lb": B.shown_weight(kg, "lb"), "shown_kg": B.shown_weight(kg, "kg"),
                      "text_lb": B.format_weight(kg, "lb"), "text_kg": B.format_weight(kg, "kg")})
    rounding = [{"value": v, "round_kg": B.round_kg(v)} for v in (70.125, 70.135, 70.145, 70.005, 70.004, 20.0, 19.995, 399.995, 0.005, 0.015, 123.456, 1e-7)]
    shown = [{"kg": kg, "unit": unit, "shown": B.shown_weight(kg, unit), "text": B.format_weight(kg, unit)}
             for kg in (20, 69.99, 70.0, 70.04, 70.05, 70.15, 70.25, 70.35, 99.95, 400, 0.45, 1.36) for unit in ("kg", "lb")]
    return [{"name": "pounds to the stored kilograms, and back to what is shown", "cases": cases},
            {"name": "kilograms rounded half up to 0.01", "cases": rounding},
            {"name": "the number and the text shown for a stored weight", "cases": shown}]


def alarm_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    def add(name: str, weights: list[dict[str, Any]], amount: float | None = 1.0, over: str = "days", days: int = 1, dry: float | None = None,
            unit: str = "kg") -> None:
        alarm = {"amount_kg": amount, "over": over, "days": days}
        cases.append({"name": name, "weights": weights, "alarm": alarm, "dry_weight_kg": dry, "unit": unit,
                      "expected": B.weight_alarm_check(weights, alarm, dry_weight_kg=dry, unit=unit)})

    add("days: gain exactly the alarm is not over", series((70.0, D1), (71.0, D2)))
    add("days: one hundredth more is over", series((70.0, D1), (71.01, D2)))
    add("days: a loss", series((71.0, D1), (70.0, D2)))
    add("days: shown in pounds", series((70.0, D1), (71.5, D2)), unit="lb")
    add("days: a different context is not compared", series((70.0, D1, "before_dialysis"), (72.0, D2, "morning")))
    add("days: looks back at most twice the days (one day back, two allowed)", series((70.0, D1), (72.0, D3)))
    add("days: three days back with days 1 is too far", series((70.0, D1), (72.0, D4)))
    add("days: two days, a weight two days back", series((70.0, D1), (72.0, D3)), days=2)
    add("days: two days, four days back is the window's edge", series((70.0, D1), (72.0, D2), (73.0, D5)), days=2)
    add("days: two days, five days back is too far", series((70.0, D1), (73.0, D6)), days=2)
    add("days: seven days", series((70.0, "2025-03-01"), (73.0, "2025-03-08")), days=7)
    add("days: the same day never counts", series((70.0, D1, "morning", "07:00"), (72.0, D1, "morning", "19:00")))
    add("days: the newest weight of the day it looks back to", series((70.0, D1, "morning", "06:00"), (70.5, D1, "morning", "08:00"), (71.0, D2)))
    add("days: the latest is the last by time, a weight with no time after the timed ones",
        series((70.0, D1), (74.0, D2, "morning", "07:00"), (71.0, D2)))
    add("days: only one weight", series((70.0, D1)))
    add("days: an alarm of 0.2 kg", series((70.0, D1), (70.2, D2)), amount=0.2)
    add("days: an alarm of 0.2 kg, a hundredth more", series((70.0, D1), (70.21, D2)), amount=0.2)
    add("days: float noise does not decide (71.1 - 70.1)", series((70.1, D1), (71.1, D2)))
    add("days: float noise does not decide (70.3 - 69.3)", series((69.3, D1), (70.3, D2)))
    add("between sessions: the last weight after a session", series((70.0, D1, "after_dialysis"), (70.6, D2, "after_dialysis"), (71.0, D3, "morning"),
                                                                 (73.0, D4, "before_dialysis")), amount=2.0, over="between_sessions")
    add("between sessions: exactly the alarm", series((70.0, D1, "after_dialysis"), (72.0, D2, "before_dialysis")), amount=2.0, over="between_sessions")
    add("between sessions: shown in pounds", series((70.0, D1, "after_dialysis"), (73.5, D2, "before_dialysis")), amount=2.0, over="between_sessions", unit="lb")
    add("between sessions: nothing after a session and no dry weight", series((73.0, D1, "before_dialysis")), amount=2.0, over="between_sessions")
    add("between sessions: nothing after a session, the dry weight in Profile", series((73.0, D1, "before_dialysis")), amount=2.0, over="between_sessions", dry=70.0)
    add("between sessions: the dry weight in pounds", series((73.0, D1, "before_dialysis")), amount=2.0, over="between_sessions", dry=70.0, unit="lb")
    add("between sessions: an after-session weight 8 days back is too old", series((70.0, "2025-03-02", "after_dialysis"), (73.0, "2025-03-10", "before_dialysis")),
        amount=2.0, over="between_sessions")
    add("between sessions: 7 days back is inside", series((70.0, "2025-03-03", "after_dialysis"), (73.0, "2025-03-10", "before_dialysis")),
        amount=2.0, over="between_sessions")
    add("between sessions: too old, then the dry weight", series((70.0, "2025-03-02", "after_dialysis"), (73.0, "2025-03-10", "before_dialysis")),
        amount=2.0, over="between_sessions", dry=71.0)
    add("between sessions: the same day, earlier", series((70.0, D1, "after_dialysis", "12:00"), (72.5, D1, "before_dialysis", "18:00")), amount=2.0,
        over="between_sessions")
    add("between sessions: the same day, later is not compared", series((72.5, D1, "before_dialysis", "09:00"), (70.0, D1, "after_dialysis", "12:00")),
        amount=2.0, over="between_sessions")
    add("between sessions: the latest weight is itself after a session", series((70.0, D1, "after_dialysis"), (70.4, D2, "after_dialysis")),
        amount=2.0, over="between_sessions")
    add("between sessions: the days setting is ignored", series((70.0, D1, "after_dialysis"), (73.0, D2, "before_dialysis")), amount=2.0,
        over="between_sessions", days=5)
    add("no alarm number", series((70.0, D1), (75.0, D2)), amount=None)
    add("no weights", [])
    add("no weights, between sessions", [], over="between_sessions", dry=70.0)
    return cases


def week_cases() -> list[dict[str, Any]]:
    cases = []

    def add(name: str, readings: list[dict[str, Any]], day: str, goal: dict[str, Any]) -> None:
        cases.append({"name": name, "readings": readings, "day": day, "goal": goal, "expected": B.blood_pressure_week(readings, day, goal)})

    base = [rrow(130, 80, "2025-03-04", 1), rrow(131, 81, "2025-03-07", 2), rrow(129, 79, "2025-03-10", 3), rrow(300, 200, "2025-03-03", 4)]
    add("three readings in the week, the day before the week is out", base, "2025-03-10", {"systolic": 130, "diastolic": 80})
    add("a goal one above the means", base, "2025-03-10", {"systolic": 131, "diastolic": 81})
    add("only the top number has a goal", base, "2025-03-10", {"systolic": 130, "diastolic": None})
    add("only the bottom number has a goal", base, "2025-03-10", {"systolic": None, "diastolic": 80})
    add("no goal", base, "2025-03-10", {"systolic": None, "diastolic": None})
    add("the week starts six days back (inclusive)", base, "2025-03-10", {"systolic": 130, "diastolic": 80})
    add("a week later the first reading is out", base, "2025-03-11", {"systolic": 130, "diastolic": 80})
    add("two readings: the means and no verdict", base[:2], "2025-03-10", {"systolic": 100, "diastolic": 60})
    add("one reading", base[:1], "2025-03-10", {"systolic": 100, "diastolic": 60})
    add("no readings", [], "2025-03-10", {"systolic": 130, "diastolic": 80})
    add("a mean of x.5 rounds up", [rrow(127, 77, "2025-03-09", 1), rrow(128, 78, "2025-03-09", 2), rrow(128, 78, "2025-03-10", 3), rrow(127, 77, "2025-03-10", 4)],
        "2025-03-10", {"systolic": 128, "diastolic": 78})
    add("a mean of x.33 rounds down", [rrow(130, 80, "2025-03-08", 1), rrow(129, 79, "2025-03-09", 2), rrow(129, 79, "2025-03-10", 3)], "2025-03-10",
        {"systolic": 130, "diastolic": 80})
    add("readings after the day are ignored", [*base, rrow(200, 110, "2025-03-11", 5)], "2025-03-10", {"systolic": 130, "diastolic": 80})
    add("a mean at the goal", [rrow(120, 70, "2025-03-08", 1), rrow(120, 70, "2025-03-09", 2), rrow(120, 70, "2025-03-10", 3)], "2025-03-10",
        {"systolic": 120, "diastolic": 70})
    add("a mean below the goal", [rrow(119, 69, "2025-03-08", 1), rrow(119, 69, "2025-03-09", 2), rrow(119, 69, "2025-03-10", 3)], "2025-03-10",
        {"systolic": 120, "diastolic": 70})
    return cases


def six_month_cases() -> list[dict[str, Any]]:
    cases = []

    def add(name: str, weights: list[dict[str, Any]]) -> None:
        cases.append({"name": name, "weights": weights, "expected": B.six_month_change(weights)})

    latest = wrow(70.0, "2026-10-20", n=9)
    add("exactly 182 days back", [wrow(74.0, "2026-04-21", n=1), latest])
    add("the closest day wins", [wrow(76.0, "2026-04-10", n=1), wrow(75.0, "2026-04-26", n=2), wrow(74.0, "2026-04-18", n=3), latest])
    add("a tie goes to the earlier day", [wrow(75.0, "2026-04-24", n=1), wrow(74.0, "2026-04-18", n=2), latest])
    add("the same day: the later weight", [wrow(74.0, "2026-04-21", time="07:00", n=1), wrow(73.0, "2026-04-21", time="19:00", n=2), latest])
    add("30 days after the target", [wrow(74.0, "2026-05-21", n=1), latest])
    add("31 days after the target", [wrow(74.0, "2026-05-22", n=1), latest])
    add("30 days before the target", [wrow(74.0, "2026-03-22", n=1), latest])
    add("31 days before the target", [wrow(74.0, "2026-03-21", n=1), latest])
    add("a gain", [wrow(65.0, "2026-04-21", n=1), latest])
    add("no change", [wrow(70.0, "2026-04-21", n=1), latest])
    add("a loss of more than 5 percent", [wrow(75.0, "2026-04-21", n=1), latest])
    add("only the latest weight", [latest])
    add("no weights", [])
    add("a weight in the window but only weeks ago", [wrow(74.0, "2026-10-01", n=1), latest])
    return cases


def flag_cases() -> list[dict[str, Any]]:
    pairs = [(179, 119), (180, 80), (140, 120), (181, 121), (180, 120), (300, 199), (120, 80), (179, 120), (180, 119), (50, 20), (300, 200), (179, 60),
             (130, 119), (150, 100)]
    return [{"systolic": s, "diastolic": d, "flag": B.bp_flag(s, d)} for s, d in pairs]


def row_cases() -> list[dict[str, Any]]:
    weights = [
        {"id": 1, "date": D1, "time": "07:30", "kg": 70.25, "context": "morning", "note": "kept", "source": "manual", "source_key": None, "created_at": STAMP,
         "updated_at": STAMP},
        {"id": 2, "date": D2, "time": None, "kg": 70, "context": "after_dialysis", "note": None, "source": "apple_health", "source_key": "abc", "created_at": STAMP,
         "updated_at": "2026-10-06T08:00:00.000000Z"},
        {"id": 3, "date": D2, "time": "07:15", "kg": 69.99, "context": "morning", "note": "", "source": "shortcut", "source_key": "s", "via": "Morning weight",
         "created_at": STAMP, "updated_at": STAMP},
        {"id": 4, "date": D2, "time": None, "kg": 70.5, "context": "other", "note": "", "source": "manual", "source_key": None, "via": None, "created_at": STAMP,
         "updated_at": STAMP},
    ]
    readings = [
        {"id": 1, "date": D1, "time": "07:35", "systolic": 128, "diastolic": 78, "pulse": 64, "context": "morning", "note": "", "source": "manual",
         "source_key": None, "created_at": STAMP, "updated_at": STAMP},
        {"id": 2, "date": D2, "time": None, "systolic": 185, "diastolic": 100, "pulse": None, "context": "evening", "note": None, "source": "import",
         "source_key": "k", "created_at": STAMP, "updated_at": STAMP},
        {"id": 3, "date": D2, "time": None, "systolic": 140, "diastolic": 120, "pulse": None, "context": "other", "note": "x", "source": "manual",
         "source_key": None, "created_at": STAMP, "updated_at": STAMP},
        {"id": 4, "date": D2, "time": "19:40", "systolic": 124, "diastolic": 79, "pulse": None, "context": "evening", "note": "", "source": "shortcut",
         "source_key": "t", "via": "Evening cuff", "created_at": STAMP, "updated_at": STAMP},
    ]
    return [{"kind": "weight", "row": r, "api": B.row_to_weight(r)} for r in weights] + [{"kind": "reading", "row": r, "api": B.row_to_reading(r)} for r in readings]


def context_cases() -> list[dict[str, Any]]:
    """``context_for(kind, time)`` at every boundary; ``minutes`` is what the browser reader's ``contextOf(kind, minutes)`` takes."""
    times = ["00:00", "03:59", "04:00", "04:01", "07:30", "10:58", "10:59", "11:00", "12:00", "16:59", "17:00", "17:01", "20:00", "23:59"]
    out = []
    for kind in ("weight", "reading"):
        for t in times:
            hours, minutes = t.split(":")
            out.append({"kind": kind, "time": t, "minutes": int(hours) * 60 + int(minutes), "context": B.context_for(kind, t)})
    out.append({"kind": "weight", "time": None, "minutes": None, "context": B.context_for("weight", None)})
    out.append({"kind": "reading", "time": None, "minutes": None, "context": B.context_for("reading", None)})
    return out


def watch_cases() -> list[dict[str, Any]]:
    """``is_watch_source(name)``: a name that contains "watch" in any letter case."""
    names = ["Apple Watch", "Sandra's Apple Watch", "watch", "WATCH", "wAtCh", "Stopwatch", "Watchful", "Withings", "Health", "Omron Connect",
             "", " ", "Wat ch", "Wätch", "Apple\u00a0Watch", "iPhone", "Series 9 (Watch)", "Garmin Connect", "W\u0061tch", "wacth"]
    return [{"name": n, "watch": B.is_watch_source(n)} for n in names] + [{"name": None, "watch": B.is_watch_source(None)}]


def summary_cases() -> list[dict[str, Any]]:
    cases = []

    def add(name: str, weights: list[dict[str, Any]], readings: list[dict[str, Any]], day: str, units: str = "lb", alarm: dict[str, Any] | None = None,
            goal: dict[str, Any] | None = None, dry: float | None = None) -> None:
        alarm = alarm or {"amount_kg": None, "over": "days", "days": 1}
        goal = goal or {"systolic": None, "diastolic": None}
        cases.append({"name": name, "weights": weights, "readings": readings, "day": day, "units": units, "alarm": alarm, "goal": goal, "dry_weight_kg": dry,
                      "expected": B.summarise(weights, readings, day=day, units=units, alarm=alarm, goal=goal, dry_weight_kg=dry)})

    add("nothing recorded", [], [], D3)
    ws = series((70.0, D1, "morning", "07:00"), (70.4, D2, "morning", "07:00"), (71.6, D3, "morning", "07:00"), (99.0, D3, "other", "23:00"))
    rs = [rrow(130, 80, D1, 1), rrow(190, 95, D3, 2, "08:00"), rrow(150, 90, D3, 3, "09:00"), rrow(125, 75, D3, 4)]
    add("weights and readings, no alarm and no goal", ws, rs, D3)
    add("the same as of the day before: later rows are ignored", ws, rs, D2, units="kg")
    add("an alarm that is over, a goal", ws[:3], rs, D3, units="kg", alarm={"amount_kg": 1.0, "over": "days", "days": 1},
        goal={"systolic": 130, "diastolic": 80})
    add("an alarm that is not over", ws[:2], rs, D2, units="kg", alarm={"amount_kg": 1.0, "over": "days", "days": 1})
    add("a flagged reading today and the latest is the one with no time", ws, rs, D3, goal={"systolic": 130, "diastolic": 80})
    add("a flagged reading on an earlier day is not flagged today", ws, [rrow(190, 95, D1, 1), rrow(120, 80, D3, 2)], D3)
    add("rows given in any order", list(reversed(ws)), list(reversed(rs)), D3, alarm={"amount_kg": 5.0, "over": "days", "days": 1})
    add("hemodialysis: the dry weight in Profile", series((73.0, D3, "before_dialysis")), [], D3, units="lb",
        alarm={"amount_kg": 2.0, "over": "between_sessions", "days": 1}, dry=70.0)
    add("a single weight", series((70.0, D3)), [], D3, alarm={"amount_kg": 1.0, "over": "days", "days": 1})
    return cases


# --------------------------------------------------------------------------- the request script


def script() -> list[dict[str, Any]]:
    """The requests, in order: ``{name, method, path, body?, quiet?}``."""
    steps: list[dict[str, Any]] = []

    def add(name: str, method: str, path: str, *body: Any, quiet: bool = False) -> None:
        step: dict[str, Any] = {"name": name, "method": method, "path": path}
        if body:
            step["body"] = body[0]
        if quiet:
            step["quiet"] = True
        steps.append(step)

    c, p = "/api/body/weights", "/api/body/blood-pressure"
    # --- recording weights, and what the answer says
    add("a weight with a time and a note, kg to two decimals", POST, c, w(70.256, D1, "morning", time="07:30", note="after the long night"))
    add("a weight with no time", POST, c, w(71.5, D1, "other"))
    add("a weight before dialysis", POST, c, w(72.4, D2, "before_dialysis", time="06:40"))
    add("a weight after dialysis", POST, c, w(70.1, D2, "after_dialysis", time="11:20"))
    add("kg as text", POST, c, w("71.5", D3))
    add("kg as a whole float", POST, c, w(72.0, D3, "other"))
    add("kg half a hundredth up", POST, c, w(70.125, D3, "other"))
    add("a blank time is no time", POST, c, w(70.0, D3, "other", time="   "))
    add("a null time and note", POST, c, w(70.0, D3, "other", time=None, note=None))
    add("surrounding spaces in the date and the note", POST, c, w(70.0, " " + D3 + " ", "other", note=" kept  "))
    add("the lightest weight", POST, c, w(20, D3, "other"))
    add("the heaviest weight", POST, c, w(400, D3, "other"))
    add("a note of the longest length (counted in characters)", POST, c, w(70.0, D3, "other", note="😀" * Mo.MAX_BODY_NOTE))
    add("a note with a line break and a tab", POST, c, w(70.0, D3, "other", note="line one\nline two\tand a tab"))
    add("the latest time of the day", POST, c, w(70.0, D3, "other", time="23:59"))
    add("the earliest time of the day", POST, c, w(70.0, D3, "other", time="00:00"))
    # --- listing
    add("list the first days", GET, f"{c}?start={D1}&end={D3}")
    add("list one day", GET, f"{c}?start={D2}&end={D2}")
    add("list days with nothing", GET, f"{c}?start=2024-01-01&end=2024-01-31")
    add("list needs a start", GET, c)
    add("list needs an end", GET, f"{c}?start={D1}")
    add("list: a start that is not a date", GET, f"{c}?start=soon&end={D3}")
    add("list: an end that is not a real date", GET, f"{c}?start={D1}&end=2025-02-30")
    add("list: end before start", GET, f"{c}?start={D3}&end={D1}")
    add("list: more than a year", GET, f"{c}?start=2024-01-01&end=2025-03-05")
    add("list: exactly the longest range", GET, f"{c}?start=2024-03-05&end=2025-03-05")
    add("list: an empty start", GET, f"{c}?start=&end={D3}")
    # --- changing and deleting weights
    add("update the first weight: another day, a context, no note, no time", PUT, f"{c}/1", w(72.5, D3, "after_dialysis", note=""))
    add("update keeps what the models fill in", PUT, f"{c}/2", w(71.0, D1, "morning", time="07:05"))
    add("update of a weight that is not there", PUT, f"{c}/99", w())
    add("update of a weight that is not there, with a bad body", PUT, f"{c}/99", w(5, D1, "x"))
    add("list after the changes", GET, f"{c}?start={D1}&end={D3}")
    add("delete", DELETE, f"{c}/3")
    add("delete again", DELETE, f"{c}/3")
    add("update after the delete", PUT, f"{c}/3", w())
    for odd in ("0", "-1", "+99", "9_9", "99.0", "99999999999999999999"):
        add(f"delete with the id {odd}", DELETE, f"{c}/{odd}")
        add(f"update with the id {odd}", PUT, f"{c}/{odd}", w())
    for odd in ("abc", "1.5"):
        add(f"delete with the id {odd!r}", DELETE, f"{c}/{odd}")
    add("update with an id that is not a number", PUT, f"{c}/abc", w())
    add("update with an id that is not a number and a bad body", PUT, f"{c}/abc", w(5, D1, "x"))
    # --- refusals, with their exact texts
    bad: list[tuple[str, Any]] = [
        ("kg just under the lightest", w(19.99)),
        ("kg just over the heaviest", w(400.01)),
        ("kg zero", w(0)),
        ("kg negative", w(-70)),
        ("kg as words", w("heavy")),
        ("kg null", w(None)),
        ("kg true", w(True)),
        ("kg a list", w([70])),
        ("kg as text with spaces", w(" 70.5 ")),
        ("kg as text with underscores", w("7_0")),
        ("kg as text, not a number", w("7 0")),
        ("kg infinity as text", w("inf")),
        ("kg not-a-number as text", w("nan")),
        ("kg in scientific text", w("7e1")),
        ("an unknown context", w(70, D1, "evening")),
        ("a context in capitals", w(70, D1, "MORNING")),
        ("a null context", w(70, D1, None)),
        ("a context that is a number", w(70, D1, 7)),
        ("a date in the future", w(70, "2999-01-01")),
        ("a date long ago", w(70, "1899-12-31")),
        ("a date in the wrong form", w(70, "10/05/2026")),
        ("a date that is not on the calendar", w(70, "2026-02-30")),
        ("a date that is a number", w(70, 20261005)),
        ("a date that is empty", w(70, "")),
        ("a time without its leading zero", w(70, D1, "morning", time="7:30")),
        ("a time of 24:00", w(70, D1, "morning", time="24:00")),
        ("a time with 60 minutes", w(70, D1, "morning", time="12:60")),
        ("a time with seconds", w(70, D1, "morning", time="07:30:00")),
        ("a time in words", w(70, D1, "morning", time="noon")),
        ("a time that is a number", w(70, D1, "morning", time=730)),
        ("a note that is too long", w(70, D1, "morning", note="n" * (Mo.MAX_BODY_NOTE + 1))),
        ("a note of too many emoji", w(70, D1, "morning", note="😀" * (Mo.MAX_BODY_NOTE + 1))),
        ("a note with a control character", w(70, D1, "morning", note="bad\u0000note")),
        ("a note with a bell", w(70, D1, "morning", note="bad\u0007note")),
        ("a note that is a number", w(70, D1, "morning", note=5)),
        ("an unknown field", {**w(), "surprise": 1}),
        ("an id in the body", {**w(), "id": 7}),
        ("a user_id in the body", {**w(), "user_id": 2}),
        ("a source in the body", {**w(), "source": "apple_health"}),
        ("a source key in the body", {**w(), "source_key": "k"}),
        ("several problems at once, in the model's order", {"context": "x", "kg": 9, "time": "x", "date": "bad", "note": 5, "extra": 1, "more": 2}),
        ("nothing", {}),
        ("a list", [w()]),
        ("a string", "70"),
        ("a number", 7),
    ]
    for name, payload in bad:
        add(f"POST: {name}", POST, c, payload)
    add("POST with no body", POST, c)
    for name, payload in bad[:6] + bad[14:16] + bad[18:20] + bad[24:26] + bad[30:32]:
        add(f"PUT: {name}", PUT, f"{c}/4", payload)
    add("PUT with no body", PUT, f"{c}/4")
    add("nothing was stored by the refusals", GET, f"{c}?start={D1}&end={D3}")
    # --- a day holds a bounded number
    for n in range(Mo.MAX_WEIGHTS_PER_DAY):
        add(f"fill the day with weights, {n + 1}", POST, c, w(60 + n / 10, D4, "other"))
    add("the day is full", POST, c, w(70, D4))
    add("a weight on another day is fine", POST, c, w(70, D5))
    # ids: 19 weights were made before the fill (the refusals above include three that are fine: text with spaces, with underscores
    # and in scientific notation), so the fill is 20-39 and the weight on the other day is 40
    add("moving a weight into the full day is refused", PUT, f"{c}/40", w(70, D4))
    add("editing a weight inside the full day is fine", PUT, f"{c}/20", w(61, D4, "other"))
    add("list the full day", GET, f"{c}?start={D4}&end={D4}")
    # --- blood pressure
    add("a reading with a time, a pulse and a note", POST, p, bp(128, 78, D1, "morning", time="07:35", pulse=64, note="seated"))
    add("a reading with no time and no pulse", POST, p, bp(150, 95, D1, "evening"))
    add("a reading at 179/119 is not flagged", POST, p, bp(179, 119, D2, "morning"))
    add("a top number of 180 is flagged", POST, p, bp(180, 80, D2, "morning", time="08:00"))
    add("a bottom number of 120 is flagged", POST, p, bp(140, 120, D2, "other", time="09:00"))
    add("the highest reading", POST, p, bp(300, 200, D2, "before_dialysis", time="10:00", pulse=250))
    add("the lowest reading", POST, p, bp(50, 20, D2, "after_dialysis", time="11:00", pulse=20))
    add("numbers as text and a whole float", POST, p, bp("120", 80.0, D3, "other", pulse="70"))
    add("a null pulse and note", POST, p, bp(120, 80, D3, "other", pulse=None, note=None))
    add("a blank time", POST, p, bp(120, 80, D3, "other", time=""))
    add("list readings", GET, f"{p}?start={D1}&end={D3}")
    add("list readings of one day", GET, f"{p}?start={D2}&end={D2}")
    add("list readings: no start", GET, p)
    add("list readings: end before start", GET, f"{p}?start={D3}&end={D1}")
    add("list readings: more than a year", GET, f"{p}?start=2024-01-01&end=2025-03-05")
    add("update a reading to a flagged one", PUT, f"{p}/1", bp(190, 100, D1, "before_dialysis", pulse=80))
    add("update a reading to a plain one", PUT, f"{p}/4", bp(135, 85, D2, "morning"))
    add("update of a reading that is not there", PUT, f"{p}/99", bp())
    add("delete a reading", DELETE, f"{p}/2")
    add("delete it again", DELETE, f"{p}/2")
    add("update it after the delete", PUT, f"{p}/2", bp())
    add("list readings after the changes", GET, f"{p}?start={D1}&end={D3}")
    for odd in ("0", "-1", "+99", "9_9", "99.0", "99999999999999999999"):
        add(f"delete a reading with the id {odd}", DELETE, f"{p}/{odd}")
        add(f"update a reading with the id {odd}", PUT, f"{p}/{odd}", bp())
    add("delete a reading with an id that is not a number", DELETE, f"{p}/abc")
    add("update a reading with an id that is not a number and a bad body", PUT, f"{p}/abc", bp(5, 5, D1, "x"))
    bad_readings: list[tuple[str, Any]] = [
        ("systolic just under the lowest", bp(49, 20)),
        ("systolic just over the highest", bp(301, 200)),
        ("diastolic just under the lowest", bp(120, 19)),
        ("diastolic just over the highest", bp(250, 201)),
        ("pulse just under the lowest", bp(120, 80, D1, "morning", pulse=19)),
        ("pulse just over the highest", bp(120, 80, D1, "morning", pulse=251)),
        ("the top number equal to the bottom number", bp(80, 80)),
        ("the top number under the bottom number", bp(70, 90)),
        ("systolic with a fraction", bp(120.5, 80)),
        ("systolic as words", bp("high", 80)),
        ("systolic null", bp(None, 80)),
        ("systolic true", bp(True, 80)),
        ("systolic as text with a fraction", bp("120.5", 80)),
        ("pulse as words", bp(120, 80, D1, "morning", pulse="fast")),
        ("pulse with a fraction", bp(120, 80, D1, "morning", pulse=64.5)),
        ("an unknown context", bp(120, 80, D1, "bedtime")),
        ("a null context", bp(120, 80, D1, None)),
        ("a date in the future", bp(120, 80, "2999-01-01")),
        ("a bad time", bp(120, 80, D1, "morning", time="99:99")),
        ("a note that is too long", bp(120, 80, D1, "morning", note="n" * (Mo.MAX_BODY_NOTE + 1))),
        ("a note with a control character", bp(120, 80, D1, "morning", note="bad\u0000note")),
        ("an unknown field", {**bp(), "surprise": 1}),
        ("a flag in the body", {**bp(), "flag": None}),
        ("several problems at once, in the model's order", {"context": "x", "pulse": 1, "diastolic": 1, "systolic": 1, "time": "x", "date": "bad", "note": 5, "extra": 1}),
        ("nothing", {}),
        ("a list", [bp()]),
    ]
    for name, payload in bad_readings:
        add(f"POST reading: {name}", POST, p, payload)
    add("POST reading with no body", POST, p)
    for name, payload in bad_readings[:8] + bad_readings[15:18]:
        add(f"PUT reading: {name}", PUT, f"{p}/1", payload)
    for n in range(Mo.MAX_READINGS_PER_DAY):
        add(f"fill the day with readings, {n + 1}", POST, p, bp(120 + n % 20, 70, D4, "other"))
    add("the day of readings is full", POST, p, bp(120, 80, D4))
    add("a reading on another day is fine", POST, p, bp(120, 80, D5))
    # --- the batch routes
    k = {"source": "apple_health", "source_key": "a1"}
    add("batch: two weights", POST, f"{c}/batch", {"rows": [{**w(70.2, D6, "other", time="07:00"), **k}, {**w(70.3, D6, "other"), "source_key": "a2"}]})
    add("batch: the same again adds nothing", POST, f"{c}/batch", {"rows": [{**w(70.2, D6, "other", time="07:00"), **k}, {**w(70.3, D6, "other"), "source_key": "a2"}]})
    add("batch: a repeat inside the request is skipped", POST, f"{c}/batch", {"rows": [{**w(70.4, D6, "other"), "source_key": "a3"}, {**w(70.5, D6, "other"), "source_key": "a3"}]})
    add("batch: the rows came in as imports", GET, f"{c}?start={D6}&end={D6}")
    add("batch: a row the person edits keeps its key", PUT, f"{c}/41", w(99, D6, "other"))
    add("batch: the old value does not come back", POST, f"{c}/batch", {"rows": [{**w(70.2, D6, "other", time="07:00"), **k}]})
    add("batch: two readings", POST, f"{p}/batch", {"rows": [{**bp(131, 81, D6, "morning", time="07:10", pulse=66), **k}, {**bp(185, 100, D6, "evening"), "source_key": "b2"}]})
    add("batch: the readings again", POST, f"{p}/batch", {"rows": [{**bp(131, 81, D6, "morning", time="07:10", pulse=66), **k}, {**bp(185, 100, D6, "evening"), "source_key": "b2"}]})
    add("batch: the readings came in flagged where they should", GET, f"{p}?start={D6}&end={D6}")
    batch_bad: list[tuple[str, Any]] = [
        ("a row with several problems: the first row to fail is named, with all its problems",
         {"rows": [{**w(70, D6, "other"), "source_key": "z0"}, {**w(5, "2999-01-01", "x"), "source": "manual"}, {"nonsense": 1}]}),
        ("an empty source key", {"rows": [{**w(70, D6, "other"), "source_key": ""}]}),
        ("a source key of spaces", {"rows": [{**w(70, D6, "other"), "source_key": "   "}]}),
        ("a source key that is too long", {"rows": [{**w(70, D6, "other"), "source_key": "k" * (Mo.MAX_SOURCE_KEY + 1)}]}),
        ("a source key of the longest length", {"rows": [{**w(70, D6, "other"), "source_key": "é" * Mo.MAX_SOURCE_KEY}]}),
        ("a source key of two lines", {"rows": [{**w(70, D6, "other"), "source_key": "a\nb"}]}),
        ("a source key that is a number", {"rows": [{**w(70, D6, "other"), "source_key": 7}]}),
        ("no source key", {"rows": [w(70, D6, "other")]}),
        ("a source of manual", {"rows": [{**w(70, D6, "other"), "source": "manual", "source_key": "m"}]}),
        ("a source that is a number", {"rows": [{**w(70, D6, "other"), "source": 5, "source_key": "m"}]}),
        ("an unknown field in a row", {"rows": [{**w(70, D6, "other"), "source_key": "u", "surprise": 1}]}),
        ("no rows", {}),
        ("rows is empty", {"rows": []}),
        ("rows is not a list", {"rows": "x"}),
        ("a row that is not an object", {"rows": [5, {"a": 1}, "x"]}),
        ("an unknown field next to rows", {"rows": [{**w(70, D6, "other"), "source_key": "u"}], "extra": 1}),
        ("too many rows", {"rows": [{}] * (Mo.MAX_BODY_BATCH + 1)}),
        ("a body that is a list", [{"rows": []}]),
    ]
    for name, payload in batch_bad:
        add(f"batch weights: {name}", POST, f"{c}/batch", payload)
    add("batch weights with no body", POST, f"{c}/batch")
    add("batch weights: a day that would be overfull (D4 holds 20)", POST, f"{c}/batch", {"rows": [{**w(70, D4, "other"), "source_key": "full1"}]})
    add("batch weights: a known key never counts against the day", POST, f"{c}/batch", {"rows": [{**w(70, D4, "other"), "source_key": "a1"}]})
    add("batch weights: nothing was stored by the refusals", GET, f"{c}?start={D6}&end={D6}")
    for name, payload in [
        ("the top number not above the bottom number: named by row", {"rows": [{**bp(120, 80, D6), "source_key": "r0"}, {**bp(80, 80, D6), "source_key": "r1"}]}),
        ("a row with a field problem before one with a model problem", {"rows": [{**bp(80, 80, D6), "source_key": "r1"}, {**bp(120, 80, D6, "x"), "source_key": "r2"}]}),
        ("a row with a field problem", {"rows": [{**bp(500, 80, D6), "source_key": "r1"}]}),
        ("a day that would be overfull", {"rows": [{**bp(120, 80, D4), "source_key": "full1"}]}),
        ("a pulse in a row", {"rows": [{**bp(120, 80, D6, pulse=10), "source_key": "r1"}]}),
    ]:
        add(f"batch readings: {name}", POST, f"{p}/batch", payload)
    add("batch readings: default source and a null pulse", POST, f"{p}/batch", {"rows": [{**bp(120, 80, D6, pulse=None), "source_key": "r9"}]})
    add("batch readings: the new one is an import", GET, f"{p}?start={D6}&end={D6}")
    # --- the summary
    add("summary needs a date", GET, "/api/body/summary")
    add("summary: a date that is not a date", GET, "/api/body/summary?date=soon")
    add("summary: an empty date", GET, "/api/body/summary?date=")
    add("summary of a day with data, no alarm and no goal", GET, f"/api/body/summary?date={D2}")
    add("summary of a day with nothing before it", GET, "/api/body/summary?date=2024-01-01")
    add("set a weight-gain alarm", PATCH, "/api/me/settings", {"body.weight_alarm": {"amount_kg": 1.0, "over": "days", "days": 1}}, quiet=True)
    add("set a blood pressure goal", PATCH, "/api/me/settings", {"body.bp_goal": {"systolic": 130, "diastolic": 80}}, quiet=True)
    add("a morning weight to compare with", POST, c, w(70.0, "2025-04-01", "morning", time="07:00"))
    add("a morning weight over the alarm", POST, c, w(71.4, "2025-04-02", "morning", time="07:00"))
    add("two readings the days before", POST, p, bp(135, 85, "2025-03-30", "morning", time="07:00"))
    add("another reading the day before", POST, p, bp(125, 75, "2025-03-31", "morning", time="07:00"))
    add("a flagged reading on the day", POST, p, bp(185, 110, "2025-04-02", "morning", time="07:05"))
    add("a plain reading on the day, later", POST, p, bp(120, 80, "2025-04-02", "evening", time="19:00"))
    add("summary over the alarm, a flagged reading and means above the goal", GET, "/api/body/summary?date=2025-04-02")
    add("summary the day before", GET, "/api/body/summary?date=2025-04-01")
    add("summary with an alarm and a goal", GET, f"/api/body/summary?date={D3}")
    add("summary of the next day", GET, f"/api/body/summary?date={D2}")
    add("summary of a day in the full week", GET, f"/api/body/summary?date={D5}")
    add("set the unit to kilograms", PATCH, "/api/me/settings", {"user.units.weight": "kg"}, quiet=True)
    add("summary in kilograms", GET, f"/api/body/summary?date={D3}")
    add("summary over the alarm, in kilograms", GET, "/api/body/summary?date=2025-04-02")
    add("an alarm between sessions with no dry weight in Profile", PATCH, "/api/me/settings",
        {"body.weight_alarm": {"amount_kg": 2.0, "over": "between_sessions", "days": 1}}, quiet=True)
    add("summary between sessions", GET, f"/api/body/summary?date={D2}")
    add("hemodialysis with a dry weight in Profile", PUT, "/api/profile", {"weight_kg": 70, "dialysis": "hemodialysis"}, quiet=True)
    add("summary between sessions with a dry weight", GET, f"/api/body/summary?date={D2}")
    add("summary between sessions on a later day", GET, f"/api/body/summary?date={D3}")
    add("no dialysis, no dry weight", PUT, "/api/profile", {"dialysis": "none"}, quiet=True)
    add("summary between sessions without hemodialysis", GET, f"/api/body/summary?date={D2}")
    # settings the body log reads are checked like any other
    add("an alarm below the lowest", PATCH, "/api/me/settings", {"body.weight_alarm": {"amount_kg": 0.19}})
    add("an alarm above the highest", PATCH, "/api/me/settings", {"body.weight_alarm": {"amount_kg": 10.01}})
    add("an alarm in words", PATCH, "/api/me/settings", {"body.weight_alarm": {"amount_kg": "lots"}})
    add("a goal whose top number is not above the bottom one", PATCH, "/api/me/settings", {"body.bp_goal": {"systolic": 120, "diastolic": 120}})
    add("a unit that is not one", PATCH, "/api/me/settings", {"user.units.weight": "stone"})
    # --- today's date, which only the clock can say
    add("today", POST, c, w(70, "{{today:0}}"))
    add("tomorrow is allowed (the person's clock may be ahead)", POST, c, w(70, "{{today:1}}"))
    add("the day after tomorrow is not", POST, c, w(70, "{{today:2}}"))
    add("a reading today", POST, p, bp(120, 80, "{{today:0}}"))
    add("a reading the day after tomorrow is not allowed", POST, p, bp(120, 80, "{{today:2}}"))
    add("the list ends at today", GET, f"{c}?start={{{{today:-3}}}}&end={{{{today:0}}}}")
    add("the list can end tomorrow", GET, f"{p}?start={{{{today:-1}}}}&end={{{{today:1}}}}")
    add("the summary of today", GET, "/api/body/summary?date={{today:0}}")
    # --- the same reading (design note 12 §4.3): a batch row is skipped when the person has a row that is not typed with the same day,
    # the same HH:MM and the same numbers; a typed row never matches, and neither does a row with no time
    sd = "2025-02-10"
    k = {"source": "apple_health"}
    add("same reading: a first imported weight", POST, f"{c}/batch", {"rows": [{**w(65.5, sd, "morning", time="07:30"), **k, "source_key": "sr1"}]})
    add("same reading: the same weight under another key is skipped", POST, f"{c}/batch",
        {"rows": [{**w(65.5, sd, "morning", time="07:30"), "source": "import", "source_key": "sr2"}]})
    add("same reading: the same kilograms to the hundredth", POST, f"{c}/batch",
        {"rows": [{**w(65.504, sd, "morning", time="07:30"), **k, "source_key": "sr2b"}]})
    add("same reading: another weight at the same minute is added", POST, f"{c}/batch",
        {"rows": [{**w(65.6, sd, "morning", time="07:30"), **k, "source_key": "sr3"}]})
    add("same reading: the same weight a minute later is added", POST, f"{c}/batch",
        {"rows": [{**w(65.5, sd, "morning", time="07:31"), **k, "source_key": "sr4"}]})
    add("same reading: a typed weight", POST, c, w(66.1, sd, "other", time="08:00"))
    add("same reading: an imported weight like the typed one is added", POST, f"{c}/batch",
        {"rows": [{**w(66.1, sd, "other", time="08:00"), **k, "source_key": "sr5"}]})
    add("same reading: rows with no time never match", POST, f"{c}/batch",
        {"rows": [{**w(65.5, sd, "other"), **k, "source_key": "sr6"}, {**w(65.5, sd, "other"), **k, "source_key": "sr7"}]})
    add("same reading: two new rows alike in one request are one", POST, f"{c}/batch",
        {"rows": [{**w(67.0, sd, "other", time="09:00"), **k, "source_key": "sr8"}, {**w(67.0, sd, "other", time="09:00"), "source": "import", "source_key": "sr9"}]})
    add("same reading: the weights of that day", GET, f"{c}?start={sd}&end={sd}")
    add("same reading: a first imported reading", POST, f"{p}/batch", {"rows": [{**bp(131, 81, sd, "morning", time="07:10"), **k, "source_key": "sr1"}]})
    add("same reading: the same reading under another key is skipped", POST, f"{p}/batch",
        {"rows": [{**bp(131, 81, sd, "morning", time="07:10"), "source": "import", "source_key": "sr2"}]})
    add("same reading: another bottom number is added", POST, f"{p}/batch", {"rows": [{**bp(131, 82, sd, "morning", time="07:10"), **k, "source_key": "sr3"}]})
    add("same reading: a typed reading", POST, p, bp(125, 75, sd, "other", time="12:00"))
    add("same reading: an imported reading like the typed one is added", POST, f"{p}/batch",
        {"rows": [{**bp(125, 75, sd, "other", time="12:00"), **k, "source_key": "sr4"}]})
    add("same reading: readings with no time never match", POST, f"{p}/batch",
        {"rows": [{**bp(131, 81, sd, "other"), **k, "source_key": "sr5"}, {**bp(131, 81, sd, "other"), **k, "source_key": "sr6"}]})
    add("same reading: two new readings alike in one request are one", POST, f"{p}/batch",
        {"rows": [{**bp(118, 76, sd, "other", time="15:00"), **k, "source_key": "sr7"}, {**bp(118, 76, sd, "other", time="15:00"), "source": "import", "source_key": "sr8"}]})
    add("same reading: the readings of that day", GET, f"{p}?start={sd}&end={sd}")
    return steps


def with_dates(value: Any, today: date) -> Any:
    """Replace ``{{today:N}}`` in strings by the date."""
    if isinstance(value, str):
        return TODAY.sub(lambda m: (today + timedelta(days=int(m.group(1)))).isoformat(), value)
    if isinstance(value, list):
        return [with_dates(v, today) for v in value]
    if isinstance(value, dict):
        return {k: with_dates(v, today) for k, v in value.items()}
    return value


def as_markers(value: Any, today: date) -> Any:
    """The reverse for an answer: a date within the marker range becomes ``{{today:N}}``; ``created_at`` and ``updated_at`` become ``<ts>``."""
    by_date = {(today + timedelta(days=n)).isoformat(): f"{{{{today:{n}}}}}" for n in MARKER_RANGE}
    if isinstance(value, str):
        return by_date.get(value, value)
    if isinstance(value, list):
        return [as_markers(v, today) for v in value]
    if isinstance(value, dict):
        return {k: ("<ts>" if k in ("created_at", "updated_at") and isinstance(v, str) else as_markers(v, today)) for k, v in value.items()}
    return value


def run_script(client: Any, steps: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for step in steps:
        kwargs: dict[str, Any] = {}
        if "body" in step:
            kwargs["json"] = with_dates(step["body"], today)
        r = client.request(step["method"], with_dates(step["path"], today), **kwargs)
        if r.status_code >= 400:
            answers.append({"ok": False, "status": r.status_code, "detail": r.json()["detail"]})
        elif step.get("quiet"):
            answers.append({"ok": True})
        else:
            answers.append({"ok": True, "body": r.json() if r.content else None})
    return [as_markers(a, today) for a in answers]


# What a few steps must answer, so a change to the script's ids or order cannot quietly turn a refusal into a success.
INTENT = {
    "the day is full": (400, "too many weights for one day (max 20)"),
    "moving a weight into the full day is refused": (400, "too many weights for one day (max 20)"),
    "editing a weight inside the full day is fine": (200, None),
    "a weight on another day is fine": (200, None),
    "the day of readings is full": (400, "too many blood pressure readings for one day (max 30)"),
    "a reading on another day is fine": (200, None),
    "batch: a row the person edits keeps its key": (200, None),
    "batch: the old value does not come back": (200, None),
    "batch weights: a day that would be overfull (D4 holds 20)": (400, "rows.0: too many weights for one day (max 20)"),
    "batch weights: a known key never counts against the day": (200, None),
    "batch readings: a day that would be overfull": (400, "rows.0: too many blood pressure readings for one day (max 30)"),
    "a morning weight over the alarm": (200, None),
    "the day after tomorrow is not": (400, "date: must not be in the future"),
    "tomorrow is allowed (the person's clock may be ahead)": (200, None),
    "same reading: the same weight under another key is skipped": (200, None),
    "same reading: the same reading under another key is skipped": (200, None),
}


def check_intent(steps: list[dict[str, Any]], answers: list[dict[str, Any]]) -> None:
    seen = set()
    for step, answer in zip(steps, answers):
        want = INTENT.get(step["name"])
        if want is None:
            continue
        seen.add(step["name"])
        status = 200 if answer["ok"] else answer["status"]
        assert status == want[0] and (want[1] is None or answer.get("detail") == want[1]), (step["name"], answer)
    assert seen == set(INTENT), sorted(set(INTENT) - seen)
    bodies = {s["name"]: a.get("body") for s, a in zip(steps, answers)}
    assert bodies["batch: the old value does not come back"] == {"added": 0, "skipped": 1}
    over = bodies["summary over the alarm, a flagged reading and means above the goal"]
    assert over["weight"]["alarm"]["over_alarm"] is True and over["weight"]["alarm"]["flag"] is not None
    assert over["bp"]["flagged_today"]["systolic"] == 185 and over["bp"]["week"]["above_goal"] is True and over["bp"]["week"]["count"] == 4
    assert bodies["batch weights: a known key never counts against the day"] == {"added": 0, "skipped": 1}
    for name, want in {
        "same reading: a first imported weight": {"added": 1, "skipped": 0},
        "same reading: the same weight under another key is skipped": {"added": 0, "skipped": 1},
        "same reading: the same kilograms to the hundredth": {"added": 0, "skipped": 1},
        "same reading: another weight at the same minute is added": {"added": 1, "skipped": 0},
        "same reading: the same weight a minute later is added": {"added": 1, "skipped": 0},
        "same reading: an imported weight like the typed one is added": {"added": 1, "skipped": 0},
        "same reading: rows with no time never match": {"added": 2, "skipped": 0},
        "same reading: two new rows alike in one request are one": {"added": 1, "skipped": 1},
        "same reading: a first imported reading": {"added": 1, "skipped": 0},
        "same reading: the same reading under another key is skipped": {"added": 0, "skipped": 1},
        "same reading: another bottom number is added": {"added": 1, "skipped": 0},
        "same reading: an imported reading like the typed one is added": {"added": 1, "skipped": 0},
        "same reading: readings with no time never match": {"added": 2, "skipped": 0},
        "same reading: two new readings alike in one request are one": {"added": 1, "skipped": 1},
    }.items():
        assert bodies[name] == want, (name, bodies[name])


def constants() -> dict[str, Any]:
    return {
        "kg_per_lb": B.KG_PER_LB,
        "weight_contexts": list(B.WEIGHT_CONTEXTS),
        "blood_pressure_contexts": list(B.BLOOD_PRESSURE_CONTEXTS),
        "sources": list(B.SOURCES),
        "units": list(B.UNITS),
        "limits": {"min_kg": Mo.MIN_WEIGHT_KG, "max_kg": Mo.MAX_WEIGHT_KG, "min_systolic": Mo.MIN_SYSTOLIC, "max_systolic": Mo.MAX_SYSTOLIC,
                   "min_diastolic": Mo.MIN_DIASTOLIC, "max_diastolic": Mo.MAX_DIASTOLIC, "min_pulse": Mo.MIN_PULSE, "max_pulse": Mo.MAX_PULSE,
                   "max_note": Mo.MAX_BODY_NOTE, "max_weights_per_day": Mo.MAX_WEIGHTS_PER_DAY, "max_readings_per_day": Mo.MAX_READINGS_PER_DAY,
                   "max_batch": Mo.MAX_BODY_BATCH, "max_source_key": Mo.MAX_SOURCE_KEY},
        "flag_systolic": B.BP_FLAG_SYSTOLIC,
        "flag_diastolic": B.BP_FLAG_DIASTOLIC,
        "href": B.GET_HELP_NOW_HREF,
        "link_text": B.GET_HELP_NOW_LINK_TEXT,
        "red_flags": {key: {"level": e["level"], "text": e["text"], "prominent": e["prominent"]} for key, e in B.RED_FLAGS.items()},
    }


def build() -> dict[str, Any]:
    """The whole document (also what ``tests/test_body_vectors.py`` compares the committed file with)."""
    from starlette.testclient import TestClient as BareClient

    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, FIXTURE_FOODS, make_settings

    today = date.today()
    steps = script()
    with tempfile.TemporaryDirectory() as tmp:
        foods = Path(tmp) / "foods.json"
        foods.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
        with BareClient(create_app(make_settings(Path(tmp), foods)), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text
            answers = run_script(client, steps, today)
    check_intent(steps, answers)
    doc = {
        "constants": constants(),
        "unit_cases": unit_cases(),
        "alarm_cases": alarm_cases(),
        "week_cases": week_cases(),
        "six_month_cases": six_month_cases(),
        "flag_cases": flag_cases(),
        "row_cases": row_cases(),
        "summary_cases": summary_cases(),
        "context_cases": context_cases(),
        "watch_cases": watch_cases(),
        "script": [{**step, "answer": answer} for step, answer in zip(steps, answers)],
    }
    return json.loads(json.dumps(doc))  # the same JSON round trip as the file (3.0 becomes 3.0, tuples become lists)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_body_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
