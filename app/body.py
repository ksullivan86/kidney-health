"""Weight and blood pressure log (schema step 18; note 10 "Weight and blood pressure"): a person records a weight and a blood
pressure reading with a date, the app records and shows, and points to the handbook when a number is past a limit.

Routes (every one needs a signed-in person and reads or writes only that person's rows; a row that is not yours is a 404, like
one that does not exist):

* ``GET /api/body/weights?start=&end=`` and ``GET /api/body/blood-pressure?start=&end=`` (``YYYY-MM-DD``, both required, at
  most 366 days) → ``{weights: [...]}`` and ``{readings: [...]}``, oldest day first, then by time (no time last), then id.
  A reading carries ``flag`` (:func:`bp_flag`) or ``null``.
* ``POST`` to each → 201, the stored row. A weight is ``{date, time?, kg, context, note?}``; ``kg`` is kilograms (the unit the
  person sees and types, ``user.units.weight``, is display and entry only) and is stored rounded half up to 0.01 kg. A reading
  is ``{date, time?, systolic, diastolic, pulse?, context, note?}``. Ranges, ``systolic > diastolic``, the date (not in the
  future, not before 1900), ``time`` as ``HH:MM``, a note of at most 200 characters, unknown fields and a 21st weight or 31st
  reading on one day are 400s. The ranges are the project's own plausibility choice (they keep a typing error out of the
  log), not clinical numbers.
* ``PUT /api/body/weights/{id}`` and ``.../blood-pressure/{id}`` the same body → 200 (it replaces the editable fields; the
  row becomes ``manual`` and keeps ``created_at`` and its ``source_key``, so a second import does not bring the old value
  back). ``DELETE`` → 204.
* ``POST /api/body/weights/batch`` and ``.../blood-pressure/batch`` ``{rows: [...]}`` (1 to 1,000 rows; at most 60 requests an
  hour per person): the rows an import read on the person's device, each the same body plus ``source`` (``apple_health`` or
  ``import``) and a ``source_key``. The whole request is checked first and refused, writing nothing, on the first row that is
  not valid (``rows.3.kg: ...``) or would be the 21st weight (31st reading) of its day; rows whose ``source_key`` the person
  already has, and repeats within the request, are skipped and counted → ``{added, skipped}``.
* ``GET /api/body/summary?date=`` → what Today shows: the latest weight and the one before it, the change, the check against
  the person's weight-gain alarm, the latest reading, the 7-day means against the person's goal, and the latest flagged reading
  of that day (:func:`summarise`).

**What the app works out** is in the pure functions below (the browser twin is ``js/engine/body.js``; the vectors
``tests/data/body_vectors.json`` are generated from this file): kilograms and pounds (``0.45359237``, exactly), the check of
the latest weight against the person's weight-gain alarm, the 7-day blood pressure means against the person's goal, and the
change over six months. The alarm and the goal are **the person's care team's numbers**, entered in Settings
(``body.weight_alarm``, ``body.bp_goal``): the app never suggests either, and says nothing about a cause, a treatment or a
medicine.

**What the app says about a number.** One thing: a pointer to the handbook's Get help now page
(``handbook/docs/get-help-now.md``), in the handbook's own words. A weight gain above the person's alarm quotes the page's
"weight gain above the alarm number your team gave you" under "Call your care team today" (not prominent: the person set the
number). A reading with a top number of 180 or more, or a bottom number of 120 or more, quotes the page's two blood pressure
lines (NHLBI's "180/120"), says to rest 5 minutes and measure again, and is prominent. :data:`RED_FLAGS` is that list;
``tests/test_body.py`` checks every quoted phrase against the page, so a change to the page that drops a phrase fails a test
instead of leaving the app quoting words that are gone.

Weights and readings are health data: they are never logged, they leave the server only in the person's own export, and they
are never sent to an AI provider or the assistant (``app/ai/``, ``app/mcp/`` and ``app/guidance/`` do not read the tables;
``tests/test_body.py`` checks). Deleting the account deletes them (``ON DELETE CASCADE``).
"""
from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import timedelta as _timedelta
from typing import Any, Sequence, get_args

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError

from .auth.deps import CurrentUser, current_user
from .db import get_db, utcnow
from .log import parse_date_param, parse_range
from .models import (
    MAX_READINGS_PER_DAY,
    MAX_SQLITE_INT,
    MAX_WEIGHTS_PER_DAY,
    BloodPressureBatchRow,
    BloodPressureContext,
    BloodPressureCreate,
    BloodPressureList,
    BloodPressureOut,
    BodyBatch,
    BodyBatchResult,
    BodySourceKey,
    BodySummary,
    WeightBatchRow,
    WeightContext,
    WeightCreate,
    WeightList,
    WeightOut,
)
from .nutrients import _half_up
from .security import flatten_validation_errors
from .symptoms import EMERGENCY, GET_HELP_NOW_HREF, GET_HELP_NOW_LINK_TEXT, HANDBOOK_GROUP_HEADINGS, TODAY

router = APIRouter(prefix="/api/body", tags=["body"], dependencies=[Depends(current_user)])

WEIGHT_CONTEXTS: tuple[str, ...] = get_args(WeightContext)
BLOOD_PRESSURE_CONTEXTS: tuple[str, ...] = get_args(BloodPressureContext)
SOURCES: tuple[str, ...] = get_args(BodySourceKey)
UNITS: tuple[str, ...] = ("kg", "lb")

# --------------------------------------------------------------------------- #
# What the app works out (pure functions; the twin is js/engine/body.js)
# --------------------------------------------------------------------------- #

KG_PER_LB = 0.45359237  # exactly: the international pound (1959), NIST SP 811 Appendix B (note 10 F7)
BP_FLAG_SYSTOLIC = 180  # NHLBI "High Blood Pressure - Symptoms" (note 10 F5): "180/120". Reading it as a top number of 180
BP_FLAG_DIASTOLIC = 120  # or more, or a bottom number of 120 or more, is the project's cautious choice (note 10 Q3).
WEEK_DAYS = 7  # the means cover the date and the 6 days before it
MIN_READINGS_FOR_VERDICT = 3  # with fewer, the means are shown ("only n readings") and nothing is said against the goal
BETWEEN_SESSIONS_DAYS = 7  # the after-dialysis weight compared with is dated within this many days before the latest weight
SIX_MONTH_DAYS = 182  # the weight compared with in the six-month change is dated closest to this many days before the latest
SIX_MONTH_WINDOW_DAYS = 30  # ... and within this many days of it
SUMMARY_WEIGHT_ROWS = 400  # newest rows the summary reads: 15 days at 20 a day is 300 (the widest comparison window is 14 days)
SUMMARY_READING_ROWS = 250  # a week at 30 a day is 210

CONTEXT_PHRASES: dict[str, str] = {
    "morning": "your morning weight",
    "before_dialysis": "your weight before dialysis",
    "after_dialysis": "your weight after dialysis",
    "other": "your other weight",
}
NO_REFERENCE_BETWEEN_SESSIONS = "Add a weight after a session to compare"
NO_REFERENCE_DAYS = "Not enough weights to compare yet"


def round_kg(kg: float) -> float:
    """A weight as it is stored: kilograms, rounded half up to 0.01 kg."""
    return _half_up(float(kg), 2)


def lb_to_kg(lb: float) -> float:
    """Pounds to the stored kilograms (``kg = lb × 0.45359237``, rounded half up to 0.01 kg)."""
    return round_kg(float(lb) * KG_PER_LB)


def shown_weight(kg: float, unit: str) -> float:
    """The number shown for a stored weight in ``unit`` (``kg`` or ``lb``): one decimal, half up (154.25 shows 154.3)."""
    value = float(kg) if unit == "kg" else float(kg) / KG_PER_LB
    return _half_up(value, 1)


def format_weight(kg: float, unit: str) -> str:
    """``"154.3 lb"`` / ``"70.0 kg"``."""
    return f"{shown_weight(kg, unit):.1f} {unit}"


def order_key(row: dict[str, Any]) -> tuple[str, int, str, int]:
    """List order: oldest day first, then by time (a row with no time last), then id."""
    return (row["date"], 1 if row["time"] is None else 0, row["time"] or "", row["id"])


def shift_day(day: str, days: int) -> str:
    return (_date.fromisoformat(day) + _timedelta(days=days)).isoformat()


def days_between(first: str, second: str) -> int:
    return (_date.fromisoformat(second) - _date.fromisoformat(first)).days


def bp_flag(systolic: int, diastolic: int) -> dict[str, Any] | None:
    """The handbook pointer for a reading at 180 top or 120 bottom or more, else ``None``."""
    if systolic >= BP_FLAG_SYSTOLIC or diastolic >= BP_FLAG_DIASTOLIC:
        return flag_of("blood_pressure")
    return None


def weight_alarm_check(weights: Sequence[dict[str, Any]], alarm: dict[str, Any], *, dry_weight_kg: float | None,
                       unit: str) -> dict[str, Any] | None:
    """The latest of ``weights`` (oldest first, API shape) against the person's weight-gain alarm (note 10 §4.4), or ``None``
    with no weight or no alarm number. ``alarm`` is ``{amount_kg, over, days}``.

    * ``between_sessions`` (hemodialysis): the weight compared with is the latest ``after_dialysis`` weight before the latest
      one, dated within the 7 days before it (the same day counts when it is earlier); without one, ``dry_weight_kg`` (the
      profile's dry weight); without either there is nothing to compare.
    * ``days``: the latest weight with the same ``context`` dated on or before the latest weight's date minus ``days``,
      looking back at most ``2 × days`` days; without one, nothing to compare.

    The gain is the latest weight minus that one (rounded to 0.01 kg) and is over the alarm when it is **more** than
    ``amount_kg``. The answer names the two weights compared.
    """
    amount = alarm.get("amount_kg")
    if amount is None or not weights:
        return None
    latest = weights[-1]
    earlier = weights[:-1]
    over, days = alarm["over"], int(alarm["days"])
    reference: dict[str, Any] | None = None
    kind: str | None = None
    reference_kg: float | None = None
    if over == "between_sessions":
        floor = shift_day(latest["date"], -BETWEEN_SESSIONS_DAYS)
        found = [w for w in earlier if w["context"] == "after_dialysis" and w["date"] >= floor]
        if found:
            reference, kind, reference_kg = found[-1], "after_dialysis", found[-1]["kg"]
        elif dry_weight_kg is not None:
            kind, reference_kg = "dry_weight", float(dry_weight_kg)
        none_message = NO_REFERENCE_BETWEEN_SESSIONS
    else:
        target, floor = shift_day(latest["date"], -days), shift_day(latest["date"], -2 * days)
        found = [w for w in earlier if w["context"] == latest["context"] and floor <= w["date"] <= target]
        if found:
            reference, kind, reference_kg = found[-1], "same_context", found[-1]["kg"]
        none_message = NO_REFERENCE_DAYS
    out: dict[str, Any] = {"amount_kg": amount, "over": over, "days": days}
    if kind is None or reference_kg is None:
        out.update(status="no_reference", reference_kind=None, reference=None, reference_kg=None, gain_kg=None,
                   over_alarm=None, message=none_message, flag=None)
        return out
    gain = round_kg(latest["kg"] - reference_kg)
    over_alarm = gain > amount
    if kind == "dry_weight":
        message = f"Compared with your dry weight in Profile ({format_weight(reference_kg, unit)})."
    else:
        assert reference is not None
        phrase = CONTEXT_PHRASES[reference["context"]]
        message = f"Compared with {phrase} on {reference['date']} ({format_weight(reference_kg, unit)})."
    out.update(status="compared", reference_kind=kind, reference=reference, reference_kg=reference_kg, gain_kg=gain,
               over_alarm=over_alarm, message=message, flag=flag_of("weight_alarm") if over_alarm else None)
    return out


def blood_pressure_week(readings: Sequence[dict[str, Any]], day: str, goal: dict[str, Any]) -> dict[str, Any]:
    """The readings dated ``day`` and the 6 days before it: how many, the mean top and bottom number (each rounded half up to
    a whole number) and whether a mean is at or above the person's goal ("under 130/80": 130 is not under). With fewer than 3
    readings the means are given with ``few: true`` and no verdict."""
    floor = shift_day(day, -(WEEK_DAYS - 1))
    inside = [r for r in readings if floor <= r["date"] <= day]
    count = len(inside)
    few = count < MIN_READINGS_FOR_VERDICT
    systolic = diastolic = None
    if count:
        systolic = int(_half_up(sum(r["systolic"] for r in inside) / count, 0))
        diastolic = int(_half_up(sum(r["diastolic"] for r in inside) / count, 0))
    above: dict[str, bool | None] = {"systolic": None, "diastolic": None}
    if not few:
        if goal.get("systolic") is not None:
            above["systolic"] = systolic >= goal["systolic"]
        if goal.get("diastolic") is not None:
            above["diastolic"] = diastolic >= goal["diastolic"]
    verdicts = [v for v in above.values() if v is not None]
    return {"count": count, "systolic": systolic, "diastolic": diastolic, "few": few,
            "above_goal": any(verdicts) if verdicts else None, "above": above}


def six_month_change(weights: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The latest of ``weights`` (oldest first, API shape) against the weight dated closest to 182 days before it, within ±30
    days (a tie goes to the earlier day, then to the later weight of that day): ``{latest, earlier, days, change_kg,
    change_pct}`` (kg to 0.01, percent to one decimal), or ``None``. Visit prep shows it; no alert, and the GLIM rule reads
    it only if the person copies it into Profile."""
    if not weights:
        return None
    latest = weights[-1]
    target = shift_day(latest["date"], -SIX_MONTH_DAYS)
    best: tuple[tuple[int, str, int], dict[str, Any]] | None = None
    for index, w in enumerate(weights[:-1]):
        distance = abs(days_between(target, w["date"]))
        if distance > SIX_MONTH_WINDOW_DAYS:
            continue
        key = (distance, w["date"], -index)
        if best is None or key < best[0]:
            best = (key, w)
    if best is None:
        return None
    earlier = best[1]
    return {"latest": latest, "earlier": earlier, "days": days_between(earlier["date"], latest["date"]),
            "change_kg": round_kg(latest["kg"] - earlier["kg"]),
            "change_pct": _half_up((latest["kg"] - earlier["kg"]) / earlier["kg"] * 100, 1)}


def summarise(weights: Sequence[dict[str, Any]], readings: Sequence[dict[str, Any]], *, day: str, units: str, alarm: dict[str, Any],
              goal: dict[str, Any], dry_weight_kg: float | None) -> dict[str, Any]:
    """``GET /api/body/summary?date=`` from API-shaped rows (any order; rows dated after ``day`` are ignored)."""
    ws = sorted((w for w in weights if w["date"] <= day), key=order_key)
    rs = sorted((r for r in readings if r["date"] <= day), key=order_key)
    latest = ws[-1] if ws else None
    previous = ws[-2] if len(ws) > 1 else None
    gain = {"kg": round_kg(latest["kg"] - previous["kg"]), "since": previous} if latest and previous else None
    flagged = [r for r in rs if r["date"] == day and r["flag"] is not None]
    return {
        "date": day,
        "units": units,
        "weight": {"latest": latest, "previous": previous, "gain": gain,
                   "alarm": weight_alarm_check(ws, alarm, dry_weight_kg=dry_weight_kg, unit=units)},
        "bp": {"latest": rs[-1] if rs else None, "week": blood_pressure_week(rs, day, goal),
               "goal": {"systolic": goal.get("systolic"), "diastolic": goal.get("diastolic")},
               "flagged_today": flagged[-1] if flagged else None},
    }


# --------------------------------------------------------------------------- #
# The handbook's words for a warning sign
# --------------------------------------------------------------------------- #

# What the handbook's Get help now page says about a weight or a reading. ``quotes`` are (group, phrase) pairs copied from the
# page (without its bold marks) and ``text`` is the line the app shows, built only from those quotes and the page's own group
# headings (``HANDBOOK_GROUP_HEADINGS``) plus the one instruction the page also gives: rest 5 minutes and measure again.
RED_FLAGS: dict[str, dict[str, Any]] = {
    "weight_alarm": {
        "level": TODAY,
        "quotes": ((TODAY, "weight gain above the alarm number your team gave you"),),
        "text": "The handbook lists “weight gain above the alarm number your team gave you” under “Call your care team today”.",
        "prominent": False,  # the person set the number
    },
    "blood_pressure": {
        "level": EMERGENCY,
        "quotes": (
            (TODAY, "A blood pressure of 180/120 or higher that is still that high when you check again after resting 5 minutes"),
            (EMERGENCY, "A blood pressure of 180/120 or higher with a sudden severe headache, trouble breathing, sudden severe "
                        "pain in the chest, belly or back, numbness or weakness, a sudden change in vision or problems talking"),
        ),
        "text": "Rest for 5 minutes, then measure again. The handbook lists “a blood pressure of 180/120 or higher that is still "
                "that high when you check again after resting 5 minutes” under “Call your care team today”, and “a blood "
                "pressure of 180/120 or higher with a sudden severe headache, trouble breathing, sudden severe pain in the "
                "chest, belly or back, numbness or weakness, a sudden change in vision or problems talking” under “Call 911 "
                "now”.",
        "prominent": True,
    },
}
assert all(group in HANDBOOK_GROUP_HEADINGS for e in RED_FLAGS.values() for group, _ in e["quotes"])


def flag_of(key: str) -> dict[str, Any]:
    """The pointer for ``key`` of :data:`RED_FLAGS`: the handbook's words, the link and whether it is prominent."""
    entry = RED_FLAGS[key]
    return {"level": entry["level"], "text": entry["text"], "href": GET_HELP_NOW_HREF, "link_text": GET_HELP_NOW_LINK_TEXT,
            "prominent": entry["prominent"]}


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

WEIGHT_COLUMNS = "id, date, time, kg, context, note, source, source_key, created_at, updated_at"
READING_COLUMNS = "id, date, time, systolic, diastolic, pulse, context, note, source, source_key, created_at, updated_at"
# weights.csv and blood_pressure.csv in the export archive (app/account.py): the stored row.
WEIGHT_CSV_COLUMNS: tuple[str, ...] = tuple(WEIGHT_COLUMNS.split(", "))
READING_CSV_COLUMNS: tuple[str, ...] = tuple(READING_COLUMNS.split(", "))
ORDER = "ORDER BY date, (time IS NULL), time, id"


def row_to_weight(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """The API shape of a stored weight."""
    return {"id": row["id"], "date": row["date"], "time": row["time"], "kg": float(row["kg"]), "context": row["context"],
            "note": row["note"] or "", "source": row["source"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def row_to_reading(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """The API shape of a stored blood pressure reading, with its ``flag``."""
    systolic, diastolic = int(row["systolic"]), int(row["diastolic"])
    return {"id": row["id"], "date": row["date"], "time": row["time"], "systolic": systolic, "diastolic": diastolic,
            "pulse": None if row["pulse"] is None else int(row["pulse"]), "context": row["context"], "note": row["note"] or "",
            "source": row["source"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "flag": bp_flag(systolic, diastolic)}


def _known_weight(row: sqlite3.Row) -> bool:
    # a row written by a later version (a context or a source this one does not know) is kept, never shown
    return row["context"] in WEIGHT_CONTEXTS and row["source"] in SOURCES


def _known_reading(row: sqlite3.Row) -> bool:
    return row["context"] in BLOOD_PRESSURE_CONTEXTS and row["source"] in SOURCES


def export_weights(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """Every weight of ``user_id`` for the export: the stored columns (``note`` as text), oldest day first, also a context or
    source this version does not know, so nothing the person recorded is left out of their file."""
    rows = conn.execute(f"SELECT {WEIGHT_COLUMNS} FROM weights WHERE user_id = ? {ORDER}", (int(user_id),)).fetchall()
    return [{**{k: row[k] for k in WEIGHT_CSV_COLUMNS}, "kg": float(row["kg"]), "note": row["note"] or ""} for row in rows]


def export_readings(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT {READING_COLUMNS} FROM blood_pressures WHERE user_id = ? {ORDER}", (int(user_id),)).fetchall()
    return [{**{k: row[k] for k in READING_CSV_COLUMNS}, "note": row["note"] or ""} for row in rows]


def count_on_day(conn: sqlite3.Connection, table: str, user_id: int, day: str, *, except_id: int | None = None) -> int:
    assert table in ("weights", "blood_pressures")
    sql = f"SELECT COUNT(*) FROM {table} WHERE user_id = ? AND date = ?"
    params: list[Any] = [int(user_id), day]
    if except_id is not None:
        sql += " AND id <> ?"
        params.append(int(except_id))
    return int(conn.execute(sql, params).fetchone()[0])


def _check_weight_day(conn: sqlite3.Connection, user_id: int, day: str, *, except_id: int | None = None) -> None:
    if count_on_day(conn, "weights", user_id, day, except_id=except_id) >= MAX_WEIGHTS_PER_DAY:
        raise HTTPException(status_code=400, detail=f"too many weights for one day (max {MAX_WEIGHTS_PER_DAY})")


def _check_reading_day(conn: sqlite3.Connection, user_id: int, day: str, *, except_id: int | None = None) -> None:
    if count_on_day(conn, "blood_pressures", user_id, day, except_id=except_id) >= MAX_READINGS_PER_DAY:
        raise HTTPException(status_code=400, detail=f"too many blood pressure readings for one day (max {MAX_READINGS_PER_DAY})")


def _fetch_weight(conn: sqlite3.Connection, user_id: int, weight_id: int) -> sqlite3.Row:
    """The person's own weight, or a 404 (the same for a weight that is somebody else's and one that does not exist)."""
    row = None
    if 1 <= weight_id <= MAX_SQLITE_INT:
        row = conn.execute(f"SELECT {WEIGHT_COLUMNS} FROM weights WHERE id = ? AND user_id = ?", (weight_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Weight not found")
    return row


def _fetch_reading(conn: sqlite3.Connection, user_id: int, reading_id: int) -> sqlite3.Row:
    row = None
    if 1 <= reading_id <= MAX_SQLITE_INT:
        row = conn.execute(f"SELECT {READING_COLUMNS} FROM blood_pressures WHERE id = ? AND user_id = ?",
                           (reading_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Blood pressure reading not found")
    return row


# --------------------------------------------------------------------------- #
# Weights
# --------------------------------------------------------------------------- #


@router.get("/weights", response_model=WeightList)
def list_weights(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                 end: str | None = None) -> dict[str, Any]:
    start_s, end_s = parse_range(start, end)
    rows = conn.execute(f"SELECT {WEIGHT_COLUMNS} FROM weights WHERE user_id = ? AND date >= ? AND date <= ? {ORDER}",
                        (user.id, start_s, end_s)).fetchall()
    return {"weights": [row_to_weight(r) for r in rows if _known_weight(r)]}


@router.post("/weights", status_code=201, response_model=WeightOut)
def create_weight(body: WeightCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _check_weight_day(conn, user.id, body.date)
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'manual', NULL, ?, ?)",
        (user.id, body.date, body.time, round_kg(body.kg), body.context, body.note, now, now),
    )
    conn.commit()
    return row_to_weight(_fetch_weight(conn, user.id, int(cur.lastrowid)))


@router.put("/weights/{weight_id}", response_model=WeightOut)
def update_weight(weight_id: int, body: WeightCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _fetch_weight(conn, user.id, weight_id)
    _check_weight_day(conn, user.id, body.date, except_id=weight_id)
    conn.execute(
        "UPDATE weights SET date = ?, time = ?, kg = ?, context = ?, note = ?, source = 'manual', updated_at = ? "
        "WHERE id = ? AND user_id = ?",
        (body.date, body.time, round_kg(body.kg), body.context, body.note, utcnow(), weight_id, user.id),
    )
    conn.commit()
    return row_to_weight(_fetch_weight(conn, user.id, weight_id))


@router.delete("/weights/{weight_id}", status_code=204)
def delete_weight(weight_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _fetch_weight(conn, user.id, weight_id)
    conn.execute("DELETE FROM weights WHERE id = ? AND user_id = ?", (weight_id, user.id))
    conn.commit()
    return Response(status_code=204)


def _checked_rows(model: Any, body: BodyBatch) -> list[Any]:
    """Every row of a batch checked by ``model``; the first row that is not valid refuses the whole request."""
    out = []
    for index, item in enumerate(body.rows):
        try:
            out.append(model.model_validate(item))
        except ValidationError as exc:
            errors = [{**e, "loc": ("rows", index, *e["loc"])} for e in exc.errors(include_url=False, include_input=False, include_context=False)]
            raise HTTPException(status_code=400, detail=flatten_validation_errors(errors)[0]) from None
    return out


def _per_day(conn: sqlite3.Connection, table: str, user_id: int, days: set[str]) -> dict[str, int]:
    assert table in ("weights", "blood_pressures")
    counts: dict[str, int] = {}
    wanted = sorted(days)
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        for r in conn.execute(f"SELECT date, COUNT(*) AS n FROM {table} WHERE user_id = ? AND date IN ({', '.join('?' for _ in chunk)}) "
                              "GROUP BY date", (user_id, *chunk)):
            counts[r["date"]] = int(r["n"])
    return counts


def _known_keys(conn: sqlite3.Connection, table: str, user_id: int) -> set[str]:
    assert table in ("weights", "blood_pressures")
    return {r[0] for r in conn.execute(f"SELECT source_key FROM {table} WHERE user_id = ? AND source_key IS NOT NULL", (user_id,))}


@router.post("/weights/batch", response_model=BodyBatchResult)
def create_weights(body: BodyBatch, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    request.app.state.auth.limits.take("body_batch", user.id)
    rows: list[WeightBatchRow] = _checked_rows(WeightBatchRow, body)
    known = _known_keys(conn, "weights", user.id)
    per_day = _per_day(conn, "weights", user.id, {r.date for r in rows})
    fresh: list[WeightBatchRow] = []
    for index, row in enumerate(rows):
        if row.source_key in known:
            continue
        if per_day.get(row.date, 0) >= MAX_WEIGHTS_PER_DAY:
            raise HTTPException(status_code=400, detail=f"rows.{index}: too many weights for one day (max {MAX_WEIGHTS_PER_DAY})")
        known.add(row.source_key)
        per_day[row.date] = per_day.get(row.date, 0) + 1
        fresh.append(row)
    now = utcnow()
    conn.executemany(
        "INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(user.id, r.date, r.time, round_kg(r.kg), r.context, r.note, r.source, r.source_key, now, now) for r in fresh],
    )
    conn.commit()
    return {"added": len(fresh), "skipped": len(rows) - len(fresh)}


# --------------------------------------------------------------------------- #
# Blood pressure
# --------------------------------------------------------------------------- #


@router.get("/blood-pressure", response_model=BloodPressureList)
def list_readings(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db), start: str | None = None,
                  end: str | None = None) -> dict[str, Any]:
    start_s, end_s = parse_range(start, end)
    rows = conn.execute(f"SELECT {READING_COLUMNS} FROM blood_pressures WHERE user_id = ? AND date >= ? AND date <= ? {ORDER}",
                        (user.id, start_s, end_s)).fetchall()
    return {"readings": [row_to_reading(r) for r in rows if _known_reading(r)]}


@router.post("/blood-pressure", status_code=201, response_model=BloodPressureOut)
def create_reading(body: BloodPressureCreate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _check_reading_day(conn, user.id, body.date)
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', NULL, ?, ?)",
        (user.id, body.date, body.time, body.systolic, body.diastolic, body.pulse, body.context, body.note, now, now),
    )
    conn.commit()
    return row_to_reading(_fetch_reading(conn, user.id, int(cur.lastrowid)))


@router.put("/blood-pressure/{reading_id}", response_model=BloodPressureOut)
def update_reading(reading_id: int, body: BloodPressureCreate, user: CurrentUser,
                   conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _fetch_reading(conn, user.id, reading_id)
    _check_reading_day(conn, user.id, body.date, except_id=reading_id)
    conn.execute(
        "UPDATE blood_pressures SET date = ?, time = ?, systolic = ?, diastolic = ?, pulse = ?, context = ?, note = ?, "
        "source = 'manual', updated_at = ? WHERE id = ? AND user_id = ?",
        (body.date, body.time, body.systolic, body.diastolic, body.pulse, body.context, body.note, utcnow(), reading_id, user.id),
    )
    conn.commit()
    return row_to_reading(_fetch_reading(conn, user.id, reading_id))


@router.delete("/blood-pressure/{reading_id}", status_code=204)
def delete_reading(reading_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _fetch_reading(conn, user.id, reading_id)
    conn.execute("DELETE FROM blood_pressures WHERE id = ? AND user_id = ?", (reading_id, user.id))
    conn.commit()
    return Response(status_code=204)


@router.post("/blood-pressure/batch", response_model=BodyBatchResult)
def create_readings(body: BodyBatch, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    request.app.state.auth.limits.take("body_batch", user.id)
    rows: list[BloodPressureBatchRow] = _checked_rows(BloodPressureBatchRow, body)
    known = _known_keys(conn, "blood_pressures", user.id)
    per_day = _per_day(conn, "blood_pressures", user.id, {r.date for r in rows})
    fresh: list[BloodPressureBatchRow] = []
    for index, row in enumerate(rows):
        if row.source_key in known:
            continue
        if per_day.get(row.date, 0) >= MAX_READINGS_PER_DAY:
            raise HTTPException(status_code=400,
                                detail=f"rows.{index}: too many blood pressure readings for one day (max {MAX_READINGS_PER_DAY})")
        known.add(row.source_key)
        per_day[row.date] = per_day.get(row.date, 0) + 1
        fresh.append(row)
    now = utcnow()
    conn.executemany(
        "INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(user.id, r.date, r.time, r.systolic, r.diastolic, r.pulse, r.context, r.note, r.source, r.source_key, now, now)
         for r in fresh],
    )
    conn.commit()
    return {"added": len(fresh), "skipped": len(rows) - len(fresh)}


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


@router.get("/summary", response_model=BodySummary)
def summary(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db), date: str | None = None) -> dict[str, Any]:
    from .profile import get_profile, settings_store

    day = parse_date_param(date, "date")
    store = settings_store(request)
    units = store.get(conn, "user.units.weight", user.id)
    alarm = store.get(conn, "body.weight_alarm", user.id)
    goal = store.get(conn, "body.bp_goal", user.id)
    profile = get_profile(conn, user.id)
    dry_weight = profile["weight_kg"] if profile["dialysis"] == "hemodialysis" else None  # on hemodialysis the profile holds the dry weight
    wrows = conn.execute(f"SELECT {WEIGHT_COLUMNS} FROM weights WHERE user_id = ? AND date <= ? ORDER BY date DESC, id DESC LIMIT ?",
                         (user.id, day, SUMMARY_WEIGHT_ROWS)).fetchall()
    rrows = conn.execute(f"SELECT {READING_COLUMNS} FROM blood_pressures WHERE user_id = ? AND date <= ? ORDER BY date DESC, id DESC LIMIT ?",
                         (user.id, day, SUMMARY_READING_ROWS)).fetchall()
    return summarise([row_to_weight(r) for r in wrows if _known_weight(r)], [row_to_reading(r) for r in rrows if _known_reading(r)],
                     day=day, units=units, alarm=alarm.model_dump(), goal=goal.model_dump(), dry_weight_kg=dry_weight)
