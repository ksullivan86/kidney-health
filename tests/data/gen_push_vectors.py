#!/usr/bin/env python3
"""Generate tests/data/push_vectors.json: what ``POST /push/v1/body`` makes of each row, for a native client.

    python3 tests/data/gen_push_vectors.py           # rewrite the file
    python3 tests/data/gen_push_vectors.py --check   # exit 1 when the committed file is stale

Produced by the route's own code (``app/push.py``, with the ranges of ``app/models.py`` and the rules of ``app/body.py``), and replayed
by the Swift package ``ios/KidneyHealthCore`` (design note 15 §4.1). The iOS app checks every row the way the server would before it
sends a batch, because one row the server refuses makes the whole request a ``400`` and nothing is stored:

* ``constants``: the route's limits;
* ``clock_cases``: an instant and a time zone, the ``at`` text a client sends for it, and what the route reads from that text (the
  wall clock as written, and the stamp of the ``source_key``). Daylight saving changes and zones with half hours are in the cases;
* ``at_cases``: ``at`` texts the route reads or refuses;
* ``value_cases``: a weight a client holds as a double, sent as a JSON number in its shortest form, and the text the route
  builds its key from (``null`` when the route would refuse it). A client that sends this text as a string gets the same key;
* ``source_cases``: a source name as sent and as the route keeps it (NFC, no control characters, single spaces), or refused;
* ``weight_cases`` and ``reading_cases``: one row as sent, and the row the route plans (date, time, kilograms, context, key, and
  for a reading whether it comes from a watch), or the field it refuses. No case depends on today's date.

Needs the app's dependencies (it imports ``app.push``). No server is started.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "push_vectors.json"
sys.path.insert(0, str(ROOT))

from app import push as P  # noqa: E402
from app.models import (  # noqa: E402
    MAX_DIASTOLIC,
    MAX_READINGS_PER_DAY,
    MAX_SYSTOLIC,
    MAX_WEIGHT_KG,
    MAX_WEIGHTS_PER_DAY,
    MIN_DIASTOLIC,
    MIN_SYSTOLIC,
    MIN_WEIGHT_KG,
)

# (UTC instant, zone): ordinary days, both sides of the US and EU daylight saving changes, half-hour and 45-minute zones,
# the date line, and midnight edges.
CLOCKS = [
    ("2026-10-22T11:15:00Z", "America/New_York"),
    ("2026-10-22T11:15:00Z", "UTC"),
    ("2026-10-22T11:15:42Z", "Europe/Berlin"),
    ("2026-03-08T06:59:59Z", "America/New_York"),  # 01:59:59 EST, a second before the clocks go forward
    ("2026-03-08T07:00:00Z", "America/New_York"),  # 03:00:00 EDT
    ("2026-11-01T05:30:00Z", "America/New_York"),  # 01:30 EDT, the first of the two 01:30s
    ("2026-11-01T06:30:00Z", "America/New_York"),  # 01:30 EST, the second
    ("2026-03-29T00:59:00Z", "Europe/London"),
    ("2026-03-29T01:00:00Z", "Europe/London"),
    ("2026-10-25T00:30:00Z", "Europe/London"),
    ("2026-10-25T01:30:00Z", "Europe/London"),
    ("2026-10-22T01:45:00Z", "Asia/Kolkata"),  # +05:30
    ("2026-10-22T01:45:00Z", "Asia/Kathmandu"),  # +05:45
    ("2026-10-22T10:00:00Z", "Pacific/Kiritimati"),  # +14:00, the next day
    ("2026-10-22T10:05:00Z", "Pacific/Honolulu"),  # -10:00, 00:05
    ("2026-10-22T09:59:00Z", "Pacific/Honolulu"),  # 23:59 the day before
    ("2026-10-21T18:30:00Z", "Australia/Adelaide"),  # +10:30 in its summer
    ("2026-04-05T15:59:59Z", "Australia/Sydney"),  # 02:59:59 AEDT, before the clocks go back
    ("2026-04-05T16:00:00Z", "Australia/Sydney"),  # 02:00:00 AEST
    ("2024-02-29T12:00:00Z", "America/Los_Angeles"),  # a leap day
]

AT_TEXTS = [
    "2026-10-22T07:15:00-04:00", "2026-10-22T07:15:00Z", "2026-10-22T23:50:00+14:00", "2026-10-22T00:05:00-10:00",
    "2026-10-22T07:15:00+05:30", "2026-10-22T07:15:00-0400", "2026-10-22 07:15:00 -0400", "2026-10-22T07:15-04:00",
    "2026-10-22T07:15:30.123456-04:00", "2026-10-22T07:15:00-04", "  2026-10-22T07:15:00Z  ",
    "", "2026-10-22", "2026-10-22T07:15", "2026-10-22T07:15:00", "07:15:00-04:00", "22/10/2026 07:15 -0400",
    "2026-10-22T24:00:00Z", "2026-10-22T07:60:00Z", "2026-10-22T07:15:60Z", "2026-02-30T07:15:00Z", "2026-13-01T07:15:00Z",
    "0000-01-01T07:15:00Z", "2026-10-22T07:15:00+24:00", "2026-10-22T07:15:00+05:60", "2026-10-22T07:15:00 UTC",
    "2026-10-22T07:15:00z", "2026-10-22T7:15:00Z", "yesterday", "２０２６-10-22T07:15:00Z",
    "2024-02-29T08:00:00-08:00", "2025-02-29T08:00:00-08:00",
]

# Weights a client holds as a double, sent as a JSON number in their shortest form: the text the route builds the key from.
VALUE_NUMBERS = [70.5, 70.0, 154.3, 154.29999999999998, 154.3 * 1.0000000001, 69.99, 70.125, 100.0, 99.9999, 99.9994, 0.5,
                 123.4567, 400.0, 20.0, 881.849, 70.1, 3.14159, 72.0005, 72.0015, 1000.0, 999.9996]

SOURCES = ["Health", "  Withings  Health Mate ", "Omron\tConnect", "Apple Watch", "Café Scale", "Scale​",
           "Scale\u0007", "a" * 60, "a" * 61, "", "   ", "​", "Sam’s iPhone", "x y", "Ω scale", "Ｗａｔｃｈ"]

WEIGHTS = [
    {"at": "2026-10-19T07:15:00-04:00", "value": "70.5", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "154.3", "unit": "lb", "source": "Withings"},
    {"at": "2026-10-19T03:59:00-04:00", "value": "70", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T11:00:00+01:00", "value": "70.125", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T19:30:00Z", "value": "154.25", "unit": "lb", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "20", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "400", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "19.99", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "400.01", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "44.0925", "unit": "lb", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "44.08", "unit": "lb", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "881.849", "unit": "lb", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "882", "unit": "lb", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "70.5", "unit": "kg", "source": "Sam’s Apple Watch"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "70.5", "unit": "kg", "source": "  Withings \t Scale "},
    {"at": "2026-10-19T07:15:00-04:00", "value": "70,5", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "1234", "unit": "kg", "source": "Health"},
    {"at": "2026-10-19T07:15:00-04:00", "value": "70.5", "unit": "kg", "source": ""},
    {"at": "2026-10-19T07:15:00-04:00", "value": "70.5", "unit": "kg", "source": "b" * 61},
    {"at": "2026-10-19T07:15:00", "value": "70.5", "unit": "kg", "source": "Health"},
    {"at": "1899-12-31T07:15:00Z", "value": "70.5", "unit": "kg", "source": "Health"},
    {"at": "1900-01-01T07:15:00Z", "value": "70.5", "unit": "kg", "source": "Health"},
    {"at": "2999-01-01T07:15:00Z", "value": "70.5", "unit": "kg", "source": "Health"},
]

READINGS = [
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122", "diastolic": "78", "source": "Omron Connect"},
    {"at": "2026-10-19T17:00:00-04:00", "systolic": "130", "diastolic": "85", "source": "Omron Connect"},
    {"at": "2026-10-19T16:59:00-04:00", "systolic": "130", "diastolic": "85", "source": "Omron Connect"},
    {"at": "2026-10-19T23:59:00-04:00", "systolic": "130", "diastolic": "85", "source": "Omron Connect"},
    {"at": "2026-10-19T10:59:00-04:00", "systolic": "130", "diastolic": "85", "source": "Omron Connect"},
    {"at": "2026-10-19T11:00:00-04:00", "systolic": "130", "diastolic": "85", "source": "Omron Connect"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122", "diastolic": "78", "source": "Sam’s Apple Watch"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122", "diastolic": "78", "source": "Stopwatch"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122", "diastolic": "78", "source": "Wätch"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "50", "diastolic": "20", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "300", "diastolic": "200", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "49", "diastolic": "20", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "301", "diastolic": "78", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122", "diastolic": "19", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "250", "diastolic": "201", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "80", "diastolic": "80", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "79", "diastolic": "80", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122.5", "diastolic": "78", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "1220", "diastolic": "78", "source": "Omron"},
    {"at": "2026-10-19T07:20:00-04:00", "systolic": "122", "diastolic": "78", "source": "\u0007"},
    {"at": "2026-10-19T07:20", "systolic": "122", "diastolic": "78", "source": "Omron"},
    {"at": "2026-10-19T07:20:00+05:45", "systolic": "122", "diastolic": "78", "source": "Omron | Arm"},
]


def _moment(m: P.Moment) -> dict[str, str]:
    return {"date": m.date, "time": m.time, "stamp": m.stamp}


def clock_cases() -> list[dict[str, Any]]:
    out = []
    for instant, zone in CLOCKS:
        moment = datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(timezone.utc)
        local = moment.astimezone(ZoneInfo(zone))
        at = local.isoformat(timespec="seconds")
        out.append({"epoch": int(moment.timestamp()), "zone": zone, "at": at, **_moment(P.parse_at(at))})
    return out


def at_cases() -> list[dict[str, Any]]:
    out = []
    for text in AT_TEXTS:
        try:
            out.append({"at": text, **_moment(P.parse_at(text))})
        except ValueError:
            out.append({"at": text, "refused": True})
    return out


def value_cases() -> list[dict[str, Any]]:
    out = []
    for value in VALUE_NUMBERS:
        try:
            _, text = P._weight_value(P.parse_json(repr(value).encode()))
            # The same text sent as a string gives the same key text; a text over 3 digits is not taken as a string.
            if P._weight_value(text)[1] != text:
                raise AssertionError((value, text))
        except ValueError:
            text = None
        out.append({"number": value, "text": text})
    return out


def source_cases() -> list[dict[str, Any]]:
    out = []
    for raw in SOURCES:
        try:
            out.append({"source": raw, "kept": P.clean_source(raw)})
        except ValueError:
            out.append({"source": raw, "kept": None})
    return out


def _refusal(exc: P.RowProblem) -> dict[str, Any]:
    return {"refused": exc.where.split(".", 2)[2]}


def weight_cases() -> list[dict[str, Any]]:
    out = []
    for row in WEIGHTS:
        try:
            w = P.plan_weight(0, P.PushWeight(**row))
        except P.RowProblem as exc:
            out.append({"row": row, **_refusal(exc)})
            continue
        source = P.clean_source(row["source"])
        stamp = P.parse_at(row["at"]).stamp
        out.append({"row": row, "planned": {"date": w.date, "time": w.time, "kg": w.kg, "context": w.context,
                                            "key_text": P.weight_key_text(stamp, row["value"].strip(), source), "key": w.key}})
    return out


def reading_cases() -> list[dict[str, Any]]:
    out = []
    for row in READINGS:
        try:
            r = P.plan_reading(0, P.PushReading(**row))
        except P.RowProblem as exc:
            out.append({"row": row, **_refusal(exc)})
            continue
        source = P.clean_source(row["source"])
        stamp = P.parse_at(row["at"]).stamp
        out.append({"row": row, "planned": {
            "date": r.date, "time": r.time, "systolic": r.systolic, "diastolic": r.diastolic, "context": r.context,
            "key_text": P.reading_key_text(stamp, r.systolic, r.diastolic, source), "key": r.key, "watch": r.watch}})
    return out


def build() -> dict[str, Any]:
    doc = {
        "about": "Made by tests/data/gen_push_vectors.py from app/push.py. Replayed by ios/KidneyHealthCore (swift test).",
        "constants": {
            "path": f"/push/{P.VERSION}{P.PATH}",
            "max_rows": P.MAX_ROWS,
            "max_body_bytes": P.MAX_BODY_BYTES,
            "max_source_chars": P.MAX_SOURCE_CHARS,
            "max_weights_per_day": MAX_WEIGHTS_PER_DAY,
            "max_readings_per_day": MAX_READINGS_PER_DAY,
            "kg": [MIN_WEIGHT_KG, MAX_WEIGHT_KG],
            "systolic": [MIN_SYSTOLIC, MAX_SYSTOLIC],
            "diastolic": [MIN_DIASTOLIC, MAX_DIASTOLIC],
            "weight_type": "HKQuantityTypeIdentifierBodyMass",
            "reading_type": "BloodPressure",
        },
        "clock_cases": clock_cases(),
        "at_cases": at_cases(),
        "value_cases": value_cases(),
        "source_cases": source_cases(),
        "weight_cases": weight_cases(),
        "reading_cases": reading_cases(),
    }
    return json.loads(json.dumps(doc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_push_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
