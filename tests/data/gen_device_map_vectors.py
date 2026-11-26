#!/usr/bin/env python3
"""Generate tests/data/device_map_vectors.json: parity vectors for the page's reading of Withings and Whoop answers.

    python3 tests/data/gen_device_map_vectors.py           # rewrite the file
    python3 tests/data/gen_device_map_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/devices/withings.py`` (``readings_from_groups``) and ``app/devices/whoop.py``
(``build_days``, ``build_workouts``), and replayed by ``node tests/js/run_vectors.mjs`` against
``app/static/js/engine/device_map.js`` (the iPhone app with no server reads the companies' answers with the same rules):

* ``withings_cases``: ``measuregrps`` and the account's time zone, with the readings and how many were left out;
* ``whoop_day_cases``: cycles, recoveries and sleeps, with the days, how many were left out and the person's Whoop id;
* ``whoop_workout_cases``: workouts, with what is kept and how many were left out.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "device_map_vectors.json"
sys.path.insert(0, str(ROOT))

from app.devices import whoop, withings  # noqa: E402

T0 = 1_793_000_000  # 2026-10-26 in the morning, UTC


def wgroup(grpid: Any, epoch: Any, measures: list[Any], **extra: Any) -> dict[str, Any]:
    g = {"grpid": grpid, "attrib": 0, "date": epoch, "created": epoch, "modified": epoch, "category": 1, "measures": measures}
    g.update(extra)
    return g


def m(type_: Any, value: Any, unit: Any) -> dict[str, Any]:
    return {"type": type_, "value": value, "unit": unit}


def reading(r: withings.Reading) -> dict[str, Any]:
    out = {"kind": r.kind, "external_id": r.external_id, "date": r.date, "time": r.time}
    if r.kind == "weight":
        out["kg"] = r.kg
    else:
        out.update(systolic=r.systolic, diastolic=r.diastolic, pulse=r.pulse)
    return out


def withings_cases() -> list[dict[str, Any]]:
    bp = [m(10, 131, 0), m(9, 82, 0), m(11, 66, 0)]
    cases: list[tuple[str, Any, Any]] = [
        ("a weight in kilograms with three decimals", [wgroup(11, T0, [m(1, 75123, -3)])], "Europe/Paris"),
        ("a weight, two decimals", [wgroup(12, T0 + 60, [m(1, 7512, -2)])], "America/New_York"),
        ("a blood pressure reading with pulse", [wgroup(13, T0 + 120, bp)], "Europe/Paris"),
        ("a reading with a half that rounds up", [wgroup(14, T0, [m(10, 1205, -1), m(9, 795, -1), m(11, 645, -1)])], "UTC"),
        ("a reading with a half below that rounds down", [wgroup(15, T0, [m(10, 12049, -2), m(9, 7949, -2)])], "UTC"),
        ("weight and blood pressure in one group", [wgroup(16, T0, [m(1, 80000, -3), *bp])], "Asia/Tokyo"),
        ("a pulse alone is left out", [wgroup(17, T0, [m(11, 70, 0)])], "UTC"),
        ("half a blood pressure reading is left out", [wgroup(18, T0, [m(10, 130, 0)])], "UTC"),
        ("a goal is left out", [wgroup(19, T0, [m(1, 70, 0)], category=2)], "UTC"),
        ("ambiguous and typed-at-sign-up are left out", [wgroup(20, T0, [m(1, 70, 0)], attrib=1), wgroup(21, T0, [m(1, 70, 0)], attrib=4)],
         "UTC"),
        ("attribs the person owns are kept", [wgroup(22 + a, T0, [m(1, 70 + a, 0)], attrib=a) for a in (2, 5, 7, 8)], "UTC"),
        ("the group's zone wins over the account's", [wgroup(30, T0, [m(1, 70, 0)], timezone="Australia/Sydney")], "Europe/London"),
        ("an unknown zone falls back to the account's", [wgroup(31, T0, [m(1, 70, 0)], timezone="Not/AZone")], "America/Chicago"),
        ("no zone at all is UTC", [wgroup(32, T0, [m(1, 70, 0)])], None),
        ("a bad account zone is UTC", [wgroup(33, T0, [m(1, 70, 0)])], 42),
        ("a summer day in New York", [wgroup(34, 1_783_000_000, [m(1, 70, 0)])], "America/New_York"),
        ("late evening crosses midnight in Los Angeles", [wgroup(35, 1_793_062_800, [m(1, 70, 0)])], "America/Los_Angeles"),
        ("bad groups", ["x", None, wgroup(0, T0, [m(1, 70, 0)]), wgroup(-1, T0, [m(1, 70, 0)]), wgroup("40", T0, [m(1, 70, 0)]),
                        wgroup(41, 0, [m(1, 70, 0)]), wgroup(42, 10**11, [m(1, 70, 0)]), wgroup(43, "1793000000", [m(1, 70, 0)])], "UTC"),
        ("bad measures", [wgroup(44, T0, [m(1, 70.5, 0)]), wgroup(45, T0, [m(1, 70, 13)]), wgroup(46, T0, [m(1, 10**16, 0)]),
                          wgroup(47, T0, ["x", m(4, 170, -2)]), wgroup(48, T0, [])], "UTC"),
        ("measures that are not a list", [wgroup(49, T0, {"type": 1}), wgroup(50, T0, None)], "UTC"),
        ("the last of two of one type is kept", [wgroup(51, T0, [m(1, 70, 0), m(1, 71, 0)])], "UTC"),
        ("a missing category and attrib are a real measure", [{"grpid": 52, "date": T0, "measures": [m(1, 69, 0)]}], "UTC"),
        ("a null category is left out", [{"grpid": 53, "date": T0, "category": None, "measures": [m(1, 69, 0)]}], "UTC"),
        ("large and small units", [wgroup(54, T0, [m(1, 7, 1)]), wgroup(55, T0, [m(1, 750000000000, -10)])], "UTC"),
        ("not a list", "groups", "UTC"),
    ]
    out = []
    for label, groups, zone in cases:
        got, left = withings.readings_from_groups(groups, zone)
        out.append({"label": label, "groups": groups, "zone": zone, "readings": [reading(r) for r in got], "left_out": left})
    return out


def cycle(cid: Any, start: str, end: str | None, kj: Any = 9000.0, strain: Any = 9.5, offset: Any = "-05:00", state: str = "SCORED",
          user_id: Any = 10129) -> dict[str, Any]:
    c: dict[str, Any] = {"id": cid, "user_id": user_id, "start": start, "timezone_offset": offset, "score_state": state}
    if end is not None:
        c["end"] = end
    if state == "SCORED":
        c["score"] = {"strain": strain, "kilojoule": kj, "average_heart_rate": 70, "max_heart_rate": 150}
    return c


def recovery(cid: Any, score: Any = 66, rhr: Any = 58, hrv: Any = 42.37, state: str = "SCORED") -> dict[str, Any]:
    r: dict[str, Any] = {"cycle_id": cid, "sleep_id": "s", "user_id": 10129, "score_state": state}
    if state == "SCORED":
        r["score"] = {"recovery_score": score, "resting_heart_rate": rhr, "hrv_rmssd_milli": hrv}
    return r


def sleep(cid: Any, light: Any = 12_000_000, slow: Any = 6_000_000, rem: Any = 5_400_000, perf: Any = 88, nap: Any = False,
          state: str = "SCORED") -> dict[str, Any]:
    s: dict[str, Any] = {"id": "00000000-0000-4000-8000-000000000001", "cycle_id": cid, "nap": nap, "score_state": state}
    if state == "SCORED":
        s["score"] = {"stage_summary": {"total_light_sleep_time_milli": light, "total_slow_wave_sleep_time_milli": slow,
                                        "total_rem_sleep_time_milli": rem}, "sleep_performance_percentage": perf}
    return s


def day(d: whoop.ActivityDay) -> dict[str, Any]:
    return asdict(d)


def whoop_day_cases() -> list[dict[str, Any]]:
    a = "2026-10-20T03:30:00.000Z"
    b = "2026-10-21T03:45:12.345Z"
    cases: list[tuple[str, list[Any], list[Any], list[Any]]] = [
        ("one finished day with recovery and sleep", [cycle(1, a, b)], [recovery(1)], [sleep(1)]),
        ("the day still going on", [cycle(2, b, None, kj=4184)], [], []),
        ("kJ to kcal, half up", [cycle(3, a, b, kj=2.092 * 3), cycle(4, b, None, kj=4184.0 * 1.5 + 2.092)], [], []),
        ("strain to a tenth, half up", [cycle(5, a, b, strain=9.45), cycle(6, b, None, strain=12.35)], [], []),
        ("out of range is empty", [cycle(7, a, b, kj=10**9, strain=25)], [recovery(7, score=120, rhr=10, hrv=900)], []),
        ("not scored yet", [cycle(8, a, b, state="PENDING_SCORE")], [recovery(8, state="PENDING_SCORE")], []),
        ("naps are left out of sleep", [cycle(9, a, b)], [], [sleep(9, nap=True), sleep(9)]),
        ("two sleeps add up", [cycle(10, a, b)], [], [sleep(10, light=600_000.5), sleep(10, light=29_999, slow=0, rem=0)]),
        ("a sleep stage missing", [cycle(11, a, b)], [], [{**sleep(11), "score": {"stage_summary": {"total_light_sleep_time_milli": 1},
                                                                                 "sleep_performance_percentage": 90}}]),
        ("records for an unknown cycle", [cycle(12, a, b)], [recovery(99)], [sleep(98)]),
        ("two cycles on one date keep the later", [cycle(13, "2026-10-20T03:00:00Z", None), cycle(14, "2026-10-20T09:00:00Z", None)], [], []),
        ("the date is 12 hours after the start on the person's clock",
         [cycle(15, "2026-10-20T16:30:00Z", None, offset="+09:00"), cycle(16, "2026-10-20T23:30:00Z", None, offset="-08:00"),
          cycle(17, "2026-10-22T02:00:00Z", None, offset="0530"), cycle(18, "2026-10-24T02:00:00Z", None, offset="bad"),
          cycle(19, "2026-10-26T02:00:00Z", None, offset="+15:00")], [], []),
        ("timestamps in other forms", [cycle(20, "2026-10-27T03:00:00+02:00", None), cycle(21, "2026-10-28T03:00:00.123456Z", None),
                                       cycle(22, "2026-10-29T03:00:00", None), cycle(23, "2026-10-30 03:00:00Z", None),
                                       cycle(24, "2026-10-31", None)], [], []),
        ("bad cycles", ["x", cycle(0, a, b), cycle("25", a, b), cycle(26, "yesterday", b), cycle(27, 5, b), cycle(True, a, b)], [], []),
        ("a cycle with no numbers at all is not a day", [cycle(28, a, b, kj=None, strain=None)], [], []),
        ("a bad user id is skipped", [cycle(29, a, b, user_id="abc"), cycle(30, b, None, user_id=777)], [], []),
        ("bad recoveries and sleeps", [cycle(31, a, b)], ["x", {"cycle_id": 31, "score_state": "SCORED", "score": "x"}],
         [None, {**sleep(31), "score": {"stage_summary": "x", "sleep_performance_percentage": "88"}}]),
        ("negative sleep stage", [cycle(32, a, b)], [], [sleep(32, light=-1)]),
        ("hrv to a tenth", [cycle(33, a, b)], [recovery(33, hrv=42.25), ], []),
    ]
    out = []
    for label, cycles, recoveries, sleeps in cases:
        days, left, user_id = whoop.build_days(cycles, recoveries, sleeps)
        out.append({"label": label, "cycles": cycles, "recoveries": recoveries, "sleeps": sleeps, "days": [day(d) for d in days],
                    "left_out": left, "user_id": user_id})
    return out


def workout(wid: Any, start: Any, end: Any, kj: Any = 1500.0, strain: Any = 8.25, sport: Any = "functional-fitness",
            offset: Any = "-05:00", state: str = "SCORED") -> dict[str, Any]:
    w: dict[str, Any] = {"id": wid, "start": start, "end": end, "timezone_offset": offset, "sport_name": sport, "score_state": state}
    if state == "SCORED":
        w["score"] = {"strain": strain, "kilojoule": kj}
    return w


def whoop_workout_cases() -> list[dict[str, Any]]:
    s, e = "2026-10-20T22:10:00.000Z", "2026-10-20T22:55:30.000Z"
    cases = [
        ("a workout", [workout("ABCDEF12-3456-4789-abcd-ef0123456789", s, e)]),
        ("half a minute rounds up", [workout("w1", "2026-10-20T10:00:00Z", "2026-10-20T10:30:30Z")]),
        ("no end yet", [workout("w2", s, None)]),
        ("an end before the start has no minutes", [workout("w3", e, s)]),
        ("too long is left out", [workout("w4", "2026-10-18T10:00:00Z", "2026-10-20T10:00:00Z")]),
        ("sport names in plain words", [workout(f"s{i}", s, e, sport=name) for i, name in
                                        enumerate(["weightlifting_msk", "Hike/Rucking", "  ", 42, "ice-bath!!", "a" * 60, "jiu-jitsu (bjj)"])]),
        ("bad workouts", ["x", workout("bad id!", s, e), workout(7, s, e), workout("w5", "nope", e), workout("w6", s, e, state="UNSCORABLE")]),
        ("the person's clock", [workout("w7", "2026-10-21T02:30:00Z", "2026-10-21T03:00:00Z", offset="-07:00")]),
        ("out of range numbers are empty", [workout("w8", s, e, kj=0, strain=30)]),
    ]
    out = []
    for label, records in cases:
        got, left = whoop.build_workouts(records)
        out.append({"label": label, "records": records, "workouts": [asdict(w) for w in got], "left_out": left})
    return out


def build() -> dict[str, Any]:
    return {
        "about": "Generated by tests/data/gen_device_map_vectors.py from app/devices/withings.py and app/devices/whoop.py. Do not edit.",
        "withings_cases": withings_cases(),
        "whoop_day_cases": whoop_day_cases(),
        "whoop_workout_cases": whoop_workout_cases(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_device_map_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
