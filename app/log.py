"""Food log: entries (eaten or planned) with nutrient snapshots, day / range / period
summaries, mark-eaten, copy-day, CSV export, quick add and (v0.3) batch add.

Every query is scoped by the signed-in person's ``user_id`` (note 07 §4.10); an entry id that
belongs to someone else answers 404, exactly like one that does not exist.

v0.3 (note 06 §4.11, note 02 R5):

* ``purpose``: ``"hypo"`` marks an entry that treated a low. It still counts toward every total
  (the person really ate it), but guidance leaves it out of the meal's carbohydrate and never
  suggests a smaller treatment. A request may send ``"hypo"`` or ``"none"``; left out, an entry of a
  ``hypo_treatment`` food defaults to ``"hypo"`` (the entry sheet's pre-ticked "Used to treat a low").
* ``client_id``: the offline outbox's UUID. ``POST /api/log``, ``/quick`` and ``/batch`` answer a
  repeat with the entry already created (200 instead of 201), so a replay never logs twice.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date as _date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from .auth.deps import CurrentUser, current_user
from .db import get_db, utcnow
from .foods import (
    WEIGHT_UNKNOWN_DETAIL,
    Provenance,
    fetch_food,
    fetch_user_food,
    insert_food,
    parse_flags,
    raw_nutrients,
    scan_custom_food,
    weight_known,
)
from .models import (
    CopyDay,
    CopyDayResult,
    DaySummary,
    Entry,
    LogBatch,
    LogBatchResult,
    LogCreate,
    LogUpdate,
    MarkEaten,
    MarkEatenResult,
    PeriodSummary,
    QuickAdd,
    RangeSummary,
    validate_date,
)
from .nutrients import (
    MEALS,
    NUTRIENT_KEYS,
    add_totals,
    build_alerts,
    build_projected_alerts,
    carb_tolerance,
    count_unknown,
    daily_status,
    empty_totals,
    food_warnings,
    kidney_rating,
    mark_unknown,
    meal_carb_alerts,
    merge_unknown,
    projected_meal_carb_alerts,
    round_nutrients,
    round_value,
    scale_nutrients,
)
from .periods import interdialytic_block, interdialytic_interval, previous_period, summarize_period, summary_notes, to_date
from .profile import get_profile, settings_store

router = APIRouter(prefix="/api/log", tags=["log"], dependencies=[Depends(current_user)])

MAX_RANGE_DAYS = 366
DEFAULT_SUMMARY_DAYS = 7
ENTRY_STATUSES: tuple[str, ...] = ("eaten", "planned")

_MEAL_ORDER_SQL = "CASE e.meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END"
_STATUS_ORDER_SQL = "CASE e.status WHEN 'eaten' THEN 0 ELSE 1 END"
_NUTRIENT_COLS = ", ".join(NUTRIENT_KEYS)
_NUTRIENT_PLACEHOLDERS = ", ".join("?" for _ in NUTRIENT_KEYS)
_ENTRY_SELECT = """
    SELECT e.*, f.flags_json AS food_flags_json, f.kidney_notes AS food_kidney_notes,
           f.source AS food_source, f.source_license AS food_source_license
    FROM log_entries e
    JOIN foods f ON f.id = e.food_id
"""
# Contract order: meal, then status (eaten before planned), then created_at.
_ENTRY_ORDER = f" ORDER BY e.date, {_MEAL_ORDER_SQL}, {_STATUS_ORDER_SQL}, e.created_at, e.id"

CSV_COLUMNS: tuple[str, ...] = (
    "id", "date", "meal", "status", "food_id", "food_name", "servings", "grams", "note",
    *NUTRIENT_KEYS,
    "created_at", "updated_at",
    "purpose",  # v0.3: "hypo" for a low treatment, else empty
    # v0.3 barcodes (note 03 R6): where the food's data came from, and its licence. "ODbL-1.0" is the
    # Open Database License notice for Open Food Facts data leaving the app (a Produced Work, ODbL §4.3).
    "source", "source_license",
)
HYPO_PURPOSE = "hypo"
HYPO_FLAG = "hypo_treatment"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def parse_date_param(value: str | None, name: str) -> str:
    if value is None or value == "":
        raise HTTPException(status_code=400, detail=f"{name} is required (YYYY-MM-DD)")
    try:
        return validate_date(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name}: {exc}") from exc


def check_range(start_d: _date, end_d: _date, max_days: int = MAX_RANGE_DAYS) -> None:
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must not be before start")
    if (end_d - start_d).days >= max_days:
        raise HTTPException(status_code=400, detail=f"range too large (max {max_days} days)")


def parse_range(start: str | None, end: str | None) -> tuple[str, str]:
    """Validate a required ``start``/``end`` query pair (ordered, at most ``MAX_RANGE_DAYS``)."""
    start_s = parse_date_param(start, "start")
    end_s = parse_date_param(end, "end")
    check_range(_date.fromisoformat(start_s), _date.fromisoformat(end_s))
    return start_s, end_s


def today_local() -> str:
    return datetime.now().date().isoformat()


def row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
    nutrients = raw_nutrients(row)
    flags = parse_flags(row["food_flags_json"])
    warnings = food_warnings(nutrients, flags, row["food_kidney_notes"], scope="in this entry")
    grams = row["grams"]
    return {
        "id": row["id"],
        "date": row["date"],
        "meal": row["meal"],
        "food_id": row["food_id"],
        "food_name": row["food_name"],
        "servings": round(float(row["servings"]), 3),
        "grams": None if grams is None else round(float(grams), 1),
        "note": row["note"],
        "status": row["status"],
        "nutrients": round_nutrients(nutrients),
        "warnings": warnings,
        "kidney_rating": kidney_rating(warnings),
        "purpose": _column(row, "purpose"),
        "client_id": _column(row, "client_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _column(row: sqlite3.Row, name: str) -> Any:
    """``row[name]``, or ``None`` on a database without the column (before schema step 5)."""
    return row[name] if name in row.keys() else None


def resolve_purpose(food: sqlite3.Row, requested: str | None) -> str | None:
    """The stored purpose of a new entry: ``"hypo"``/``"none"`` as asked; left out, ``"hypo"`` for a
    ``hypo_treatment`` food (note 06 §4.11), else ``None``."""
    if requested == HYPO_PURPOSE:
        return HYPO_PURPOSE
    if requested == "none":
        return None
    return HYPO_PURPOSE if HYPO_FLAG in parse_flags(food["flags_json"]) else None


def fetch_entry_by_client_id(conn: sqlite3.Connection, user_id: int, client_id: str | None) -> sqlite3.Row | None:
    """The person's entry created with ``client_id`` (the offline outbox's id), if any."""
    if not client_id:
        return None
    return conn.execute(_ENTRY_SELECT + " WHERE e.user_id = ? AND e.client_id = ?", (int(user_id), client_id)).fetchone()


def fetch_entry(conn: sqlite3.Connection, user_id: int, entry_id: int) -> sqlite3.Row | None:
    try:
        return conn.execute(_ENTRY_SELECT + " WHERE e.id = ? AND e.user_id = ?", (entry_id, int(user_id))).fetchone()
    except OverflowError:  # id beyond SQLite's 64-bit INTEGER: no such row
        return None


def get_entry_or_404(conn: sqlite3.Connection, user_id: int, entry_id: int) -> sqlite3.Row:
    row = fetch_entry(conn, user_id, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"log entry {entry_id} not found")
    return row


def fetch_entries(
    conn: sqlite3.Connection,
    user_id: int,
    start: str | None = None,
    end: str | None = None,
    *,
    status: str | None = None,
    meal: str | None = None,
) -> list[sqlite3.Row]:
    where: list[str] = ["e.user_id = ?"]
    params: list[Any] = [int(user_id)]
    if start:
        where.append("e.date >= ?")
        params.append(start)
    if end:
        where.append("e.date <= ?")
        params.append(end)
    if status:
        where.append("e.status = ?")
        params.append(status)
    if meal:
        where.append("e.meal = ?")
        params.append(meal)
    sql = _ENTRY_SELECT + " WHERE " + " AND ".join(where) + _ENTRY_ORDER
    return conn.execute(sql, params).fetchall()


def eaten_day_totals(conn: sqlite3.Connection, user_id: int, start: str, end: str) -> dict[str, dict[str, float]]:
    """``{date: totals}`` of ``user_id``'s *eaten* entries per day; days without eaten entries are absent."""
    sums = ", ".join(f"SUM({key}) AS {key}" for key in NUTRIENT_KEYS)
    rows = conn.execute(
        f"""SELECT date, {sums} FROM log_entries
            WHERE user_id = ? AND status = 'eaten' AND date >= ? AND date <= ? GROUP BY date""",
        (int(user_id), start, end),
    ).fetchall()
    return {row["date"]: {key: float(row[key] or 0.0) for key in NUTRIENT_KEYS} for row in rows}


def eaten_day_unknown(conn: sqlite3.Connection, user_id: int, start: str, end: str) -> dict[str, dict[str, int]]:
    """``{date: {key: n}}``: how many of ``user_id``'s *eaten* entries that day have no value for
    ``key`` (only days and keys with a count). :func:`eaten_day_totals` cannot tell those apart from 0."""
    counts = ", ".join(f"SUM({key} IS NULL) AS {key}" for key in NUTRIENT_KEYS)
    rows = conn.execute(
        f"""SELECT date, {counts} FROM log_entries
            WHERE user_id = ? AND status = 'eaten' AND date >= ? AND date <= ? GROUP BY date""",
        (int(user_id), start, end),
    ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        day = {key: int(row[key]) for key in NUTRIENT_KEYS if row[key]}
        if day:
            out[row["date"]] = day
    return out


def resolve_servings(food: sqlite3.Row, servings: float | None, grams: float | None) -> tuple[float, float | None]:
    """``grams`` wins when given (servings = grams / serving_g); default 1 serving.

    400 when ``grams`` is given for a food whose serving weight does not describe its values
    (:func:`app.foods.weight_known`: Open Food Facts prepared-only values)."""
    if grams is not None:
        if not weight_known(food):
            raise HTTPException(status_code=400, detail=WEIGHT_UNKNOWN_DETAIL)
        return float(grams) / float(food["serving_g"]), float(grams)
    return (float(servings) if servings is not None else 1.0), None


def insert_entry(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    date: str,
    meal: str,
    food: sqlite3.Row,
    servings: float,
    grams: float | None,
    note: str | None,
    status: str = "eaten",
    purpose: str | None = None,
    client_id: str | None = None,
) -> int:
    """Insert one entry with its nutrient snapshot; the caller commits. A ``client_id`` the person
    already used raises ``sqlite3.IntegrityError`` (index ``log_client_id``)."""
    if status not in ENTRY_STATUSES:
        raise ValueError(f"status must be one of {', '.join(ENTRY_STATUSES)}")
    if purpose not in (None, HYPO_PURPOSE):
        raise ValueError("purpose must be 'hypo' or None")
    snapshot = scale_nutrients(raw_nutrients(food), servings)
    now = utcnow()
    cur = conn.execute(
        f"""INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, grams, note, status,
                {_NUTRIENT_COLS}, purpose, client_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {_NUTRIENT_PLACEHOLDERS}, ?, ?, ?, ?)""",
        (int(user_id), date, meal, food["id"], food["name"], servings, grams, note, status,
         *[snapshot[k] for k in NUTRIENT_KEYS], purpose, client_id, now, now),
    )
    return int(cur.lastrowid)


def _is_hypo(row: Any) -> bool:
    """The entry treated a low (``purpose = "hypo"``); rows without the column (before schema step 5) did not."""
    try:
        return row["purpose"] == HYPO_PURPOSE
    except (IndexError, KeyError):
        return False


def carb_tolerance_for(conn: sqlite3.Connection, request: Request, user_id: int) -> float:
    """The person's carbohydrate tolerance (``guidance.carb_tolerance_g``, 5–20 g, default 10): how far above a
    meal's goal still counts as on target. Today's per-meal alert and meal guidance use the same number."""
    prefs = settings_store(request).get(conn, "guidance", user_id)
    value = prefs.get("carb_tolerance_g") if isinstance(prefs, dict) else getattr(prefs, "carb_tolerance_g", None)
    return carb_tolerance(value)


def day_figures(rows: list[sqlite3.Row], profile: dict[str, Any], carb_tolerance_g: Any = 0) -> dict[str, Any]:
    """Totals, status and alerts for one day's rows: eaten, planned and projected (eaten + planned).

    ``totals`` / ``status`` / ``alerts`` are computed on eaten entries only (unchanged from
    v0.1). ``projected_alerts`` is empty when nothing is planned, so the UI never shows
    "If you eat what's planned…" for a day that has no plan.

    A total skips entries whose value is unknown (``NULL``), so every total comes with how many
    entries it misses: ``unknown`` / ``planned_unknown`` / ``projected_unknown`` and
    ``meal_unknown`` / ``planned_meal_unknown`` (``{key: entries}``, only keys with a count), and
    every status item has ``"unknown": n`` (its level is judged on what is known; with ``n > 0`` the
    true total may be higher). A total of 0 with an unknown count means "not listed", never "none".

    v0.3.1: a meal's carbohydrate alert fires only more than ``carb_tolerance_g`` above its goal and leaves out
    entries that treated a low (they still count in every total); an "about" target is judged with the profile's
    ``about_tolerance_pct``. ``carb_tolerance_g`` is returned so the UI draws the meal lines the same way.
    """
    eaten = empty_totals()
    planned = empty_totals()
    meals = {meal: empty_totals() for meal in MEALS}
    planned_meals = {meal: empty_totals() for meal in MEALS}
    hypo_meals: dict[str, float] = {}
    projected_hypo_meals: dict[str, float] = {}
    unknown: dict[str, int] = {}
    planned_unknown: dict[str, int] = {}
    meal_unknown: dict[str, dict[str, int]] = {meal: {} for meal in MEALS}
    planned_meal_unknown: dict[str, dict[str, int]] = {meal: {} for meal in MEALS}
    counts = {"eaten": 0, "planned": 0}
    for row in rows:
        raw = raw_nutrients(row)
        if _is_hypo(row):
            carbs = float(raw.get("carbs_g") or 0.0)
            projected_hypo_meals[row["meal"]] = projected_hypo_meals.get(row["meal"], 0.0) + carbs
            if row["status"] != "planned":
                hypo_meals[row["meal"]] = hypo_meals.get(row["meal"], 0.0) + carbs
        if row["status"] == "planned":
            add_totals(planned, raw)
            add_totals(planned_meals.setdefault(row["meal"], empty_totals()), raw)
            count_unknown(planned_unknown, raw)
            count_unknown(planned_meal_unknown.setdefault(row["meal"], {}), raw)
            counts["planned"] += 1
        else:
            add_totals(eaten, raw)
            add_totals(meals.setdefault(row["meal"], empty_totals()), raw)
            count_unknown(unknown, raw)
            count_unknown(meal_unknown.setdefault(row["meal"], {}), raw)
            counts["eaten"] += 1
    projected = add_totals(dict(eaten), planned)
    projected_unknown = merge_unknown(unknown, planned_unknown)

    targets = profile["targets"]
    warn_fraction = profile["warn_fraction"]
    about = profile.get("about_tolerance_pct", 0)
    tolerance = carb_tolerance(carb_tolerance_g)
    status = mark_unknown(daily_status(eaten, targets, warn_fraction, about), unknown)
    projected_status = mark_unknown(daily_status(projected, targets, warn_fraction, about), projected_unknown)
    alerts = build_alerts(status) + meal_carb_alerts(meals, targets.get("carbs_per_meal_g"), targets.get("carbs_per_snack_g"),
                                                     tolerance_g=tolerance, hypo_carbs=hypo_meals)
    projected_alerts: list[dict[str, Any]] = []
    if counts["planned"]:
        projected_meals = {meal: add_totals(dict(meals[meal]), planned_meals.get(meal, {})) for meal in meals}
        projected_alerts = build_projected_alerts(projected_status) + projected_meal_carb_alerts(
            projected_meals, targets.get("carbs_per_meal_g"), targets.get("carbs_per_snack_g"),
            tolerance_g=tolerance, hypo_carbs=projected_hypo_meals,
        )
    return {
        "totals": round_nutrients(eaten),
        "planned_totals": round_nutrients(planned),
        "projected_totals": round_nutrients(projected),
        "status": status,
        "projected_status": projected_status,
        "meals": {meal: round_nutrients(values) for meal, values in meals.items()},
        "planned_meals": {meal: round_nutrients(values) for meal, values in planned_meals.items()},
        "alerts": alerts,
        "projected_alerts": projected_alerts,
        "counts": counts,
        "unknown": unknown,
        "planned_unknown": planned_unknown,
        "projected_unknown": projected_unknown,
        "meal_unknown": meal_unknown,
        "planned_meal_unknown": planned_meal_unknown,
        "carb_tolerance_g": tolerance,
    }


def summarize_day(date: str, rows: list[sqlite3.Row], profile: dict[str, Any], carb_tolerance_g: Any = 0) -> dict[str, Any]:
    figures = day_figures(rows, profile, carb_tolerance_g)
    return {
        "date": date,
        "entries": [row_to_entry(r) for r in rows],
        "targets": profile["targets"],
        **figures,
    }


# --------------------------------------------------------------------------- #
# Routes (static paths before ``/{entry_id}``)
# --------------------------------------------------------------------------- #


@router.get("", response_model=DaySummary)
def get_day(user: CurrentUser, request: Request, date: str | None = None,
            conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    day = parse_date_param(date, "date") if date else today_local()
    profile = get_profile(conn, user.id)
    rows = fetch_entries(conn, user.id, day, day)
    return summarize_day(day, rows, profile, carb_tolerance_for(conn, request, user.id))


@router.get("/range", response_model=RangeSummary)
def get_range(user: CurrentUser, start: str | None = None, end: str | None = None,
              conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    start_s, end_s = parse_range(start, end)
    start_d, end_d = _date.fromisoformat(start_s), _date.fromisoformat(end_s)

    profile = get_profile(conn, user.id)
    by_date: dict[str, list[sqlite3.Row]] = {}
    for row in fetch_entries(conn, user.id, start_s, end_s):
        by_date.setdefault(row["date"], []).append(row)

    days = []
    current = start_d
    while current <= end_d:
        key = current.isoformat()
        figures = day_figures(by_date.get(key, []), profile)
        days.append(
            {
                "date": key,
                "totals": figures["totals"],
                "planned_totals": figures["planned_totals"],
                "projected_totals": figures["projected_totals"],
                "status": figures["status"],
                "projected_status": figures["projected_status"],
                "counts": figures["counts"],
                "unknown": figures["unknown"],
                "planned_unknown": figures["planned_unknown"],
                "projected_unknown": figures["projected_unknown"],
            }
        )
        current += timedelta(days=1)
    return {"days": days}


@router.get("/summary", response_model=PeriodSummary)
def get_summary(user: CurrentUser, start: str | None = None, end: str | None = None,
                conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Period summary of *eaten* entries: averages per logged day vs targets, days over,
    the same-length previous period and, for hemodialysis, the current interdialytic interval.

    Default: the 7 days ending today. Giving only one bound fills the other for a 7-day period.
    """
    span = timedelta(days=DEFAULT_SUMMARY_DAYS - 1)
    if start is None and end is None:
        end_d = _date.fromisoformat(today_local())
        start_d = end_d - span
    elif end is None:
        start_d = _date.fromisoformat(parse_date_param(start, "start"))
        end_d = start_d + span
    elif start is None:
        end_d = _date.fromisoformat(parse_date_param(end, "end"))
        start_d = end_d - span
    else:
        start_d = _date.fromisoformat(parse_date_param(start, "start"))
        end_d = _date.fromisoformat(parse_date_param(end, "end"))
    check_range(start_d, end_d)

    profile = get_profile(conn, user.id)
    targets = profile["targets"]
    warn_fraction = profile["warn_fraction"]

    interval = None
    if profile["dialysis"] == "hemodialysis":
        interval = interdialytic_interval(end_d, profile["dialysis_days"])

    fetch_from, _ = previous_period(start_d, end_d)
    if interval is not None:
        fetch_from = min(fetch_from, to_date(interval["since"]))
    day_totals = eaten_day_totals(conn, user.id, fetch_from.isoformat(), end_d.isoformat())
    day_unknown = eaten_day_unknown(conn, user.id, fetch_from.isoformat(), end_d.isoformat())

    summary = summarize_period(start_d, end_d, day_totals, targets, warn_fraction, day_unknown=day_unknown,
                               about_tolerance_pct=profile.get("about_tolerance_pct", 0))
    summary["interdialytic"] = None if interval is None else interdialytic_block(interval, day_totals, targets, warn_fraction,
                                                                                  day_unknown=day_unknown)
    summary["notes"] = summary_notes(profile["dialysis"], profile["dialysis_days"], interval)
    return summary


# A cell starting with one of these runs as a formula in Excel, LibreOffice and Google Sheets
# (CSV injection, OWASP); such text cells get a leading apostrophe.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "\uff1d", "\uff0b", "\uff0d", "\uff20")


def csv_safe(value: Any) -> Any:
    """A CSV cell value: ``None`` → empty; text that a spreadsheet would run as a formula is escaped."""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_row(row: sqlite3.Row) -> list[Any]:
    """One entry as the values of :data:`CSV_COLUMNS` (not yet escaped)."""
    values: list[Any] = [
        row["id"], row["date"], row["meal"], row["status"], row["food_id"], row["food_name"],
        round(float(row["servings"]), 3),
        None if row["grams"] is None else round(float(row["grams"]), 1),
        row["note"],
    ]
    values += [round_value(key, row[key]) for key in NUTRIENT_KEYS]
    values += [row["created_at"], row["updated_at"], _column(row, "purpose")]
    values += [_column(row, "food_source"), _column(row, "food_source_license")]
    return values


@router.get("/export.csv")
def export_csv(user: CurrentUser, start: str | None = None, end: str | None = None,
               conn: sqlite3.Connection = Depends(get_db)) -> StreamingResponse:
    start_s = parse_date_param(start, "start") if start else None
    end_s = parse_date_param(end, "end") if end else None
    if start_s and end_s and end_s < start_s:
        raise HTTPException(status_code=400, detail="end must not be before start")
    rows = fetch_entries(conn, user.id, start_s, end_s)  # materialised before the connection closes

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_COLUMNS)
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([csv_safe(v) for v in csv_row(row)])
            yield buffer.getvalue()

    filename = f"kidney-log_{start_s or 'all'}_{end_s or 'all'}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/quick", response_model=Entry, status_code=201, responses={200: {"model": Entry, "description": "Repeat of a client_id: the entry already created"}})
def quick_add(body: QuickAdd, user: CurrentUser, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Create a custom food from manually entered nutrients, then log it. A repeated ``client_id``
    answers 200 with the entry already created and creates no second food."""
    existing = fetch_entry_by_client_id(conn, user.id, body.client_id)
    if existing is not None:
        response.status_code = 200
        return row_to_entry(existing)
    flags, notes, ingredients, found = scan_custom_food(body.name, body.flags, None, body.ingredients_text)
    food_id = insert_food(
        conn,
        source="custom",
        owner_user_id=user.id,
        name=body.name,
        serving_desc=body.serving_desc,
        serving_g=body.serving_g,
        nutrients=body.nutrients,
        flags=flags,
        kidney_notes=notes,
        provenance=Provenance(gtin=body.gtin, ingredients_text=ingredients, additives=tuple(found)),
    )
    food = fetch_food(conn, food_id)
    try:
        entry_id = insert_entry(
            conn, user_id=user.id, date=body.date, meal=body.meal, food=food, servings=body.servings, grams=None,
            note=body.note, status=body.status, purpose=resolve_purpose(food, body.purpose), client_id=body.client_id,
        )
    except sqlite3.IntegrityError:
        return _replayed(conn, user.id, body.client_id, response)  # a concurrent request with the same id won
    conn.commit()
    return row_to_entry(fetch_entry(conn, user.id, entry_id))


@router.post("/mark-eaten", response_model=MarkEatenResult)
def mark_eaten(body: MarkEaten, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Set every planned entry of the day (or of one meal) to ``eaten``."""
    sql = "UPDATE log_entries SET status = 'eaten', updated_at = ? WHERE user_id = ? AND date = ? AND status = 'planned'"
    params: list[Any] = [utcnow(), user.id, body.date]
    if body.meal:
        sql += " AND meal = ?"
        params.append(body.meal)
    cur = conn.execute(sql, params)
    conn.commit()
    return {"updated": int(cur.rowcount)}


@router.post("/copy-day", response_model=CopyDayResult, status_code=201)
def copy_day(body: CopyDay, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Copy a day's entries onto another date (snapshot recomputed from the current foods).

    Entries entered by weight keep their grams (servings follow the food's current
    serving size); all others keep their servings. Notes are copied.
    """
    status_filter = None if body.include == "all" else body.include
    rows = fetch_entries(conn, user.id, body.from_date, body.from_date, status=status_filter)
    if body.meals:
        rows = [r for r in rows if r["meal"] in body.meals]
    if not rows:
        what = "entries" if body.include == "all" else f"{body.include} entries"
        raise HTTPException(status_code=400, detail=f"no {what} on {body.from_date} to copy")

    created: list[int] = []
    for row in rows:
        food = fetch_food(conn, row["food_id"])
        if food is None:  # cannot happen with foreign keys on
            continue
        if row["grams"] is not None and weight_known(food):
            servings, grams = resolve_servings(food, None, row["grams"])
        else:  # by servings (also an old by-weight entry of a food whose weight is no longer usable)
            servings, grams = float(row["servings"]), None
        created.append(
            insert_entry(
                conn, user_id=user.id, date=body.to_date, meal=row["meal"], food=food, servings=servings, grams=grams,
                note=row["note"], status=body.status, purpose=_column(row, "purpose"),
            )
        )
    conn.commit()
    entries = [row_to_entry(fetch_entry(conn, user.id, entry_id)) for entry_id in created]
    return {"created": len(entries), "entries": entries}


def _replayed(conn: sqlite3.Connection, user_id: int, client_id: str | None, response: Response) -> dict[str, Any]:
    """After an ``IntegrityError`` on insert: the entry a concurrent request created with the same
    ``client_id`` (200), or the error again when that is not what happened."""
    conn.rollback()
    existing = fetch_entry_by_client_id(conn, user_id, client_id)
    if existing is None:
        raise HTTPException(status_code=409, detail="the entry could not be saved; try again")
    response.status_code = 200
    return row_to_entry(existing)


def _insert_logged(conn: sqlite3.Connection, user_id: int, body: LogCreate, where: str = "") -> int:
    """Validate visibility (404) and insert one ``POST /api/log`` item; the caller commits."""
    food = fetch_user_food(conn, user_id, body.food_id)
    if food is None:
        raise HTTPException(status_code=404, detail=f"{where}food {body.food_id} not found")
    servings, grams = resolve_servings(food, body.servings, body.grams)
    return insert_entry(
        conn, user_id=user_id, date=body.date, meal=body.meal, food=food, servings=servings, grams=grams,
        note=body.note, status=body.status, purpose=resolve_purpose(food, body.purpose), client_id=body.client_id,
    )


@router.post("/batch", response_model=LogBatchResult, status_code=201,
             responses={200: {"model": LogBatchResult, "description": "Every item was a repeat of its client_id"}})
def create_batch(body: LogBatch, user: CurrentUser, response: Response,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Add 1–40 entries in one transaction ("Use this plan", the offline outbox; note 06 §4.10).

    Each item is validated exactly as ``POST /api/log`` (body rules, then the food must be visible).
    All or nothing: the first failing item (``entries[i]: …``) rolls the whole batch back. Items whose
    ``client_id`` the person already used are not added again; their result is ``existing``. 201 when
    at least one entry was created, 200 when every item already existed.
    """
    for attempt in range(2):
        results: list[tuple[int, str]] = []
        try:
            for index, item in enumerate(body.entries):
                existing = fetch_entry_by_client_id(conn, user.id, item.client_id)
                if existing is not None:
                    results.append((int(existing["id"]), "existing"))
                    continue
                results.append((_insert_logged(conn, user.id, item, where=f"entries[{index}]: "), "created"))
        except sqlite3.IntegrityError:
            conn.rollback()  # a concurrent request used one of the client_ids: the retry sees it as existing
            if attempt:
                raise HTTPException(status_code=409, detail="the entries could not be saved; try again") from None
            continue
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        break
    if not any(state == "created" for _, state in results):
        response.status_code = 200
    entries = [row_to_entry(fetch_entry(conn, user.id, entry_id)) for entry_id, _ in results]
    return {
        "entries": entries,
        "results": [{"index": i, "id": entry_id, "result": state} for i, (entry_id, state) in enumerate(results)],
    }


@router.post("", response_model=Entry, status_code=201,
             responses={200: {"model": Entry, "description": "Repeat of a client_id: the entry already created"}})
def create_entry(body: LogCreate, user: CurrentUser, response: Response,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    existing = fetch_entry_by_client_id(conn, user.id, body.client_id)
    if existing is not None:
        response.status_code = 200
        return row_to_entry(existing)
    try:
        entry_id = _insert_logged(conn, user.id, body)
    except sqlite3.IntegrityError:
        return _replayed(conn, user.id, body.client_id, response)
    conn.commit()
    return row_to_entry(fetch_entry(conn, user.id, entry_id))


@router.put("/{entry_id}", response_model=Entry)
def update_entry(entry_id: int, body: LogUpdate, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    row = get_entry_or_404(conn, user.id, entry_id)
    food = fetch_food(conn, row["food_id"])
    if food is None:  # cannot happen with foreign keys on, but keep the error explicit
        raise HTTPException(status_code=404, detail="the entry's food no longer exists")
    data = body.model_dump(exclude_unset=True)

    date = data.get("date") or row["date"]
    meal = data.get("meal") or row["meal"]
    status = data.get("status") or row["status"]
    note = data["note"] if "note" in data else row["note"]
    purpose = _column(row, "purpose")
    if data.get("purpose") is not None:
        purpose = HYPO_PURPOSE if data["purpose"] == HYPO_PURPOSE else None

    servings = float(row["servings"])
    grams = row["grams"]
    if data.get("grams") is not None:
        servings, grams = resolve_servings(food, None, data["grams"])
    elif data.get("servings") is not None:
        servings, grams = float(data["servings"]), None
    elif "grams" in data:  # explicit null clears the weight, servings unchanged
        grams = None
    elif grams is not None and weight_known(food):
        # Weight-based entry, amount untouched: the servings follow the food's *current* serving
        # size (as copy-day does), so grams and servings agree after a food is re-portioned.
        servings, grams = resolve_servings(food, None, grams)
    elif grams is not None:  # the food's weight is no longer usable: keep the servings, drop the grams
        grams = None

    snapshot = scale_nutrients(raw_nutrients(food), servings)
    sets = ["date = ?", "meal = ?", "status = ?", "food_name = ?", "servings = ?", "grams = ?", "note = ?", "purpose = ?"]
    params: list[Any] = [date, meal, status, food["name"], servings, grams, note, purpose]
    for key in NUTRIENT_KEYS:
        sets.append(f"{key} = ?")
        params.append(snapshot[key])
    sets.append("updated_at = ?")
    params += [utcnow(), entry_id, user.id]
    conn.execute(f"UPDATE log_entries SET {', '.join(sets)} WHERE id = ? AND user_id = ?", params)
    conn.commit()
    return row_to_entry(fetch_entry(conn, user.id, entry_id))


@router.delete("/{entry_id}", status_code=204, response_class=Response)
def delete_entry(entry_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    get_entry_or_404(conn, user.id, entry_id)
    conn.execute("DELETE FROM log_entries WHERE id = ? AND user_id = ?", (entry_id, user.id))
    conn.commit()
    return Response(status_code=204)
