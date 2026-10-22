"""``POST /push/v1/body``: a phone shortcut sends its latest weight and blood pressure (design note 12 §4.2; ARCHITECTURE.md
"Device tokens and /push/v1"; guide ``docs/push.md``).

The route lives outside ``/api``, like ``/mcp``: every ``/api`` route is session-only, and this one is bearer-only. It never
reads a session cookie, so a browser cannot be made to post to it; a request with only a cookie is the generic ``401``.

Order of checks (each one answers before the next runs):

1. The middlewares (:mod:`app.security`): the global body limit, then ``Origin`` on the exact path ``/push/v1/body`` (present and not
   this server's own origin, or ``PUBLIC_URL`` → ``403``). The cookie CSRF checks do not apply: no cookie is read.
2. A device token (:func:`app.auth.api_tokens.authenticate`, scope ``body:write``, family ``device``): ``Authorization: Bearer khd_…``.
   Every failure is the same generic ``401`` with ``WWW-Authenticate: Bearer``; ``429`` for an address blocked after refused tokens.
   While the instance switch ``push.enabled`` is off every request is that ``401`` and nothing is looked up. A ``kha_`` assistant token
   is refused before any lookup.
3. The per-token limit: **60 requests an hour** (``ratelimit`` ``push_body``, key ``token:<id>``); every request that got this far counts.
4. ``Content-Type: application/json`` (else ``415``) and a body of at most **32 KiB** (``413``, decided from ``Content-Length`` before the
   body is read, and counted while it streams).
5. The JSON object ``{"weights": [...], "readings": [...]}``, at most **50 rows** in all, unknown fields refused (``400``):

   * a weight: ``{"at", "value", "unit", "source"}``; a reading: ``{"at", "systolic", "diastolic", "source"}``.
   * ``at``: ISO 8601 date and time **with its zone** (``2026-10-22T07:15:00-04:00``, or ``Z``). The row's ``date`` and ``time`` are the
     wall clock **as written** in that zone, not converted (the Health export writes the same). A time without a zone is a ``400``.
   * ``value``: a JSON number, or a plain decimal string (1 to 3 digits, optionally a point and 1 to 3 digits); ``unit`` is exactly ``kg`` or
     ``lb`` (``lb`` × 0.45359237, rounded half up to 0.01 kg, then the 20 to 400 kg range). ``systolic`` and ``diastolic`` are whole numbers (a JSON integer or a string of
     digits); a fraction is a ``400``.
   * ``source``: 1 to 60 characters after cleaning (NFC, no control characters, single spaces): the app or device the sample came from.
     It is not stored; it goes into the row's ``source_key`` and tells a watch from a cuff.

6. **Every row is checked before anything is written**; the first invalid row is a ``400`` that names it (``weights.0.at: …``) and
   nothing is stored. The ranges, ``systolic > diastolic``, the date (not in the future, not before 1900) and the per-day limits (20
   weights, 30 readings) are those of ``app/body.py`` (the same model classes), so they cannot drift.
7. A reading whose ``source`` is watch-like (:func:`app.body.is_watch_source`) is **not stored** and is counted as ``refused.watch``: a
   shortcut cannot ask the person to tick a box (note 10: cuffless readings are not recommended). A weight from a watch is kept.
8. A row the person already has is counted and not added: the same ``source_key`` (the first 32 hex characters of the SHA-256 of
   ``HKQuantityTypeIdentifierBodyMass|<at as YYYY-MM-DD HH:MM:SS +HHMM>|<value as sent>|<source>`` or ``BloodPressure|<at>|<systolic>/<diastolic>|<source>``,
   exactly what the Health export reader builds, so a later import of the export skips the row), or the same reading
   (:func:`app.body.known_weight_marks`: same date, same ``HH:MM``, same kilograms / same two numbers, from any source but ``manual``).
9. Rows are stored with ``source = 'shortcut'``, ``api_token_id`` = the token, the ``context`` the clock time gives
   (:func:`app.body.context_for`), no note, and written in one transaction.

The answer is **counts only**: ``{"added": {"weights": n, "readings": n}, "already_there": {…}, "refused": {"watch": n}}``. No row, id, flag
or name is echoed, so a token reads nothing. Values are never logged: the log line holds the token's id and the counts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from . import brand
from .audit import audit
from .auth import api_tokens
from .auth.accounts import begin_immediate
from .auth.context import auth_context, request_ip
from .auth.deps import CurrentUser, current_user
from .auth.errors import ApiProblem
from .auth.models import User, clean_display
from .auth.ratelimit import register_limit
from .body import (
    context_for,
    is_watch_source,
    known_reading_marks,
    known_weight_marks,
    lb_to_kg,
    round_kg,
)
from .db import get_db, utcnow
from .models import (
    MAX_DIASTOLIC,
    MAX_READINGS_PER_DAY,
    MAX_SYSTOLIC,
    MAX_WEIGHT_KG,
    MAX_WEIGHTS_PER_DAY,
    MIN_DIASTOLIC,
    MIN_SYSTOLIC,
    MIN_WEIGHT_KG,
    BloodPressureCreate,
    WeightCreate,
)
from .security import flatten_validation_errors

logger = logging.getLogger(f"{brand.LOGGER_NAME}.push")

PATH = "/body"
VERSION = "v1"
MAX_BODY_BYTES = 32 * 1024  # a request over this is a 413, before its body is parsed
MAX_ROWS = 50  # weights and readings together
MAX_SOURCE_CHARS = 60
RATE_LIMIT = "push_body"
register_limit(RATE_LIMIT, 60, 3600, "Too many requests from this shortcut. Try again later.")

NO_STORE = {"Cache-Control": "no-store"}

router = APIRouter(prefix=f"/push/{VERSION}", tags=["push"])
# "Delete what it sent" is a session route like every /api/me one (it lives here with the rest of the device-token code).
api_router = APIRouter(prefix="/api/me/tokens", tags=["me"], dependencies=[Depends(current_user)])


# --------------------------------------------------------------------------- #
# Reading the request
# --------------------------------------------------------------------------- #


class _Number(float):
    """A JSON number with a fraction or an exponent, remembering the text it was written with (the ``source_key`` is built from
    the value as sent)."""

    raw: str

    def __new__(cls, text: str) -> "_Number":
        obj = super().__new__(cls, text)
        obj.raw = text
        return obj


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def parse_json(body: bytes) -> Any:
    """The decoded body; ``ValueError`` for anything that is not strict JSON (NaN, Infinity, invalid UTF-8 included)."""
    try:
        return json.loads(body.decode("utf-8"), parse_float=_Number, parse_constant=_refuse_constant)
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError(str(exc)) from None


async def _read_capped(request: Request) -> bytes:
    """The request body, or a 413 as soon as it is known to pass :data:`MAX_BODY_BYTES` (a declared ``Content-Length`` before
    anything is read; a body that streams, as it passes the cap)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            raise ApiProblem(400, "Invalid Content-Length header") from None
        if size > MAX_BODY_BYTES:
            raise _too_large()
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _too_large() -> ApiProblem:
    return ApiProblem(413, f"The request is too large (at most {MAX_BODY_BYTES // 1024} KiB).")


def _is_json_type(request: Request) -> bool:
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return media == "application/json"


# --------------------------------------------------------------------------- #
# The body: shape (pydantic), then every row's meaning
# --------------------------------------------------------------------------- #


class PushWeight(BaseModel):
    """One weight as the shortcut sends it. ``value`` is checked by :func:`_weight_value` (a number or a plain decimal string)."""

    model_config = ConfigDict(extra="forbid")

    at: StrictStr = Field(max_length=64)
    value: Any
    unit: Literal["kg", "lb"]
    source: StrictStr = Field(max_length=400)


class PushReading(BaseModel):
    """One blood pressure reading. ``systolic`` and ``diastolic`` are checked by :func:`_whole_number`."""

    model_config = ConfigDict(extra="forbid")

    at: StrictStr = Field(max_length=64)
    systolic: Any
    diastolic: Any
    source: StrictStr = Field(max_length=400)


class PushBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: list[PushWeight] = Field(default_factory=list)
    readings: list[PushReading] = Field(default_factory=list)


class PushAdded(BaseModel):
    weights: int
    readings: int


class PushRefused(BaseModel):
    watch: int


class PushResult(BaseModel):
    """Counts only: nothing the token sent is echoed."""

    added: PushAdded
    already_there: PushAdded
    refused: PushRefused


class RowProblem(Exception):
    """A row that cannot be stored: ``where`` is ``weights.0.at`` style, ``message`` the rule."""

    def __init__(self, where: str, message: str) -> None:
        super().__init__(f"{where}: {message}")
        self.where = where
        self.message = message


# ASCII digits only (re.ASCII): the default \d also matches other scripts' digits, which float() and int() would read as numbers.
_AT = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d{1,9})?)?[ ]?(Z|[+-]\d{2}(?::?\d{2})?)?", re.ASCII
)
_DECIMAL = re.compile(r"\d{1,3}(?:\.\d{1,3})?", re.ASCII)
_WHOLE = re.compile(r"\d{1,3}", re.ASCII)
_WHOLE_FLOAT = re.compile(r"(\d{1,3})\.0{1,3}", re.ASCII)  # 122.0 is a whole number; 122.5 is not
AT_EXAMPLE = "2026-10-22T07:15:00-04:00"


@dataclass(frozen=True)
class Moment:
    """``at`` as written: the wall clock of the person (``date``, ``time`` = ``HH:MM``) and the text the Health export would write
    for it (``stamp``, ``YYYY-MM-DD HH:MM:SS +HHMM``)."""

    date: str
    time: str
    stamp: str


def parse_at(text: str) -> Moment:
    """``at`` → :class:`Moment`; ``ValueError`` (the message names the fix) for anything else. The wall clock is kept as
    written, never converted to another zone; a time without a zone is refused because its wall clock would be a guess."""
    m = _AT.fullmatch(text.strip())
    if m is None:
        raise ValueError(f"send the date and time with its zone, for example {AT_EXAMPLE}")
    if m.group(7) is None:
        raise ValueError(f"send the time with its zone (for example {AT_EXAMPLE}, or Z for UTC)")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    zone = m.group(7)
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("is not a time of day")
    try:
        _date(year, month, day)
    except ValueError:
        raise ValueError("is not a date on the calendar") from None
    if zone == "Z":
        offset = "+0000"
    else:
        digits = zone[1:].replace(":", "")
        offset_hours, offset_minutes = int(digits[:2]), int(digits[2:] or 0)
        if offset_hours > 23 or offset_minutes > 59:
            raise ValueError("has a zone that is not a UTC offset")
        offset = f"{zone[0]}{offset_hours:02d}{offset_minutes:02d}"
    day_text = f"{year:04d}-{month:02d}-{day:02d}"
    return Moment(date=day_text, time=f"{hour:02d}:{minute:02d}", stamp=f"{day_text} {hour:02d}:{minute:02d}:{second:02d} {offset}")


def _weight_value(raw: Any) -> tuple[float, str]:
    """``(number, text as sent)`` of a weight's ``value``: a JSON number, or a plain decimal string (1 to 3 digits, then optionally a
    point and 1 to 3 digits, such as ``"154.3"``). The text is what the ``source_key`` is built from. A JSON number is read as it is
    (a Shortcut may send ``154.29999999999998``); its text is the text it was written with when that is a plain decimal, else the
    number to 3 decimals. ``ValueError`` for anything else (``NaN`` and a boolean included); the range is checked later, in kilograms."""
    if isinstance(raw, bool):
        raise ValueError("must be a number")
    if isinstance(raw, int):
        if abs(raw) >= 10**9:
            raise ValueError("is too large")
        return float(raw), str(raw)
    if isinstance(raw, _Number):
        number = float(raw)
        if not math.isfinite(number) or abs(number) >= 10**9:
            raise ValueError("is too large")
        if _DECIMAL.fullmatch(raw.raw):
            return number, raw.raw
        return number, f"{number:.3f}".rstrip("0").rstrip(".")
    if isinstance(raw, str):
        text = raw.strip()
        if not _DECIMAL.fullmatch(text):
            raise ValueError("must be a plain number such as 154.3 (up to 3 digits, then a point and up to 3 more)")
        return float(text), text
    raise ValueError("must be a number or a plain decimal such as 154.3")


def _whole_number(raw: Any) -> int:
    """A systolic or diastolic: a JSON integer, 122.0, or a string of digits. A fraction is refused."""
    if isinstance(raw, bool):
        raise ValueError("must be a whole number")
    if isinstance(raw, int):
        text = str(raw)
    elif isinstance(raw, _Number):
        whole = _WHOLE_FLOAT.fullmatch(raw.raw)
        if whole is None:
            raise ValueError("must be a whole number, not a fraction")
        text = whole.group(1)
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        raise ValueError("must be a whole number")
    if not _WHOLE.fullmatch(text):
        raise ValueError("must be a whole number of up to 3 digits")
    return int(text)


def clean_source(raw: str) -> str:
    """The ``source``: NFC, no control characters, single spaces; 1 to 60 characters (``ValueError`` otherwise)."""
    text = clean_display(raw, limit=MAX_SOURCE_CHARS + 1)
    if not text:
        raise ValueError("send the name of the app or device the sample came from")
    if len(text) > MAX_SOURCE_CHARS:
        raise ValueError(f"use at most {MAX_SOURCE_CHARS} characters")
    return text


def source_key(text: str) -> str:
    """The first 32 hex characters of the SHA-256 of ``text``: the key the Health export reader builds (note 10 §4.8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def weight_key_text(stamp: str, value: str, source: str) -> str:
    return f"HKQuantityTypeIdentifierBodyMass|{stamp}|{value}|{source}"


def reading_key_text(stamp: str, systolic: int, diastolic: int, source: str) -> str:
    return f"BloodPressure|{stamp}|{systolic}/{diastolic}|{source}"


@dataclass(frozen=True)
class PlannedWeight:
    index: int
    date: str
    time: str
    kg: float
    context: str
    key: str


@dataclass(frozen=True)
class PlannedReading:
    index: int
    date: str
    time: str
    systolic: int
    diastolic: int
    context: str
    key: str
    watch: bool


def _model_problem(where: str, exc: ValidationError, rename: dict[str, str]) -> RowProblem:
    """The first problem of a ``WeightCreate`` / ``BloodPressureCreate`` as a :class:`RowProblem` on the field the sender used."""
    err = exc.errors(include_url=False, include_input=False, include_context=False)[0]
    field = str(err["loc"][0]) if err["loc"] else "systolic"  # a model-level rule: systolic > diastolic
    msg = str(err["msg"]).removeprefix("Value error, ")
    if field == "kg":
        msg = f"must be {MIN_WEIGHT_KG} to {MAX_WEIGHT_KG} kg (a weight in pounds is converted first)"
    elif field == "systolic" and not err["loc"]:
        msg = "systolic must be greater than diastolic"
    elif field == "systolic":
        msg = f"must be {MIN_SYSTOLIC} to {MAX_SYSTOLIC}"
    elif field == "diastolic":
        msg = f"must be {MIN_DIASTOLIC} to {MAX_DIASTOLIC}"
    return RowProblem(f"{where}.{rename.get(field, field)}", msg)


def plan_weight(index: int, row: PushWeight) -> PlannedWeight:
    """One weight checked by the same model as ``POST /api/body/weights`` (:class:`app.models.WeightCreate`)."""
    where = f"weights.{index}"
    try:
        moment = parse_at(row.at)
    except ValueError as exc:
        raise RowProblem(f"{where}.at", str(exc)) from None
    try:
        number, text = _weight_value(row.value)
    except ValueError as exc:
        raise RowProblem(f"{where}.value", str(exc)) from None
    try:
        source = clean_source(row.source)
    except ValueError as exc:
        raise RowProblem(f"{where}.source", str(exc)) from None
    kg = lb_to_kg(number) if row.unit == "lb" else round_kg(number)
    context = context_for("weight", moment.time)
    try:
        WeightCreate(date=moment.date, time=moment.time, kg=kg, context=context, note="")
    except ValidationError as exc:
        raise _model_problem(where, exc, {"date": "at", "time": "at", "kg": "value"}) from None
    return PlannedWeight(index, moment.date, moment.time, kg, context, source_key(weight_key_text(moment.stamp, text, source)))


def plan_reading(index: int, row: PushReading) -> PlannedReading:
    """One reading checked by the same model as ``POST /api/body/blood-pressure`` (:class:`app.models.BloodPressureCreate`)."""
    where = f"readings.{index}"
    try:
        moment = parse_at(row.at)
    except ValueError as exc:
        raise RowProblem(f"{where}.at", str(exc)) from None
    numbers: dict[str, int] = {}
    for name in ("systolic", "diastolic"):
        try:
            numbers[name] = _whole_number(getattr(row, name))
        except ValueError as exc:
            raise RowProblem(f"{where}.{name}", str(exc)) from None
    try:
        source = clean_source(row.source)
    except ValueError as exc:
        raise RowProblem(f"{where}.source", str(exc)) from None
    context = context_for("reading", moment.time)
    try:
        BloodPressureCreate(date=moment.date, time=moment.time, systolic=numbers["systolic"], diastolic=numbers["diastolic"],
                            context=context, note="")
    except ValidationError as exc:
        raise _model_problem(where, exc, {"date": "at", "time": "at"}) from None
    return PlannedReading(index, moment.date, moment.time, numbers["systolic"], numbers["diastolic"], context,
                          source_key(reading_key_text(moment.stamp, numbers["systolic"], numbers["diastolic"], source)),
                          is_watch_source(source))


def read_body(raw: bytes) -> tuple[list[PlannedWeight], list[PlannedReading]]:
    """The checked rows of a request body, in the order sent, or an :class:`ApiProblem` (400) naming the first row that is not
    valid. Nothing is stored here."""
    try:
        doc = parse_json(raw)
    except ValueError:
        raise ApiProblem(400, "The body is not valid JSON.") from None
    if not isinstance(doc, dict):
        raise ApiProblem(400, 'Send one JSON object: {"weights": [...], "readings": [...]}.')
    count = sum(len(doc[k]) for k in ("weights", "readings") if isinstance(doc.get(k), list))
    if count > MAX_ROWS:
        raise ApiProblem(400, f"Send at most {MAX_ROWS} rows in one request (weights and readings together).")
    try:
        body = PushBody.model_validate(doc)
    except ValidationError as exc:
        detail, errors = flatten_validation_errors(exc.errors(include_url=False, include_input=False, include_context=False))
        raise ApiProblem(400, detail, errors=errors) from None
    if not body.weights and not body.readings:
        raise ApiProblem(400, "Send at least one weight or reading.")
    try:
        return [plan_weight(i, w) for i, w in enumerate(body.weights)], [plan_reading(i, r) for i, r in enumerate(body.readings)]
    except RowProblem as problem:
        raise ApiProblem(400, f"{problem.where}: {problem.message}", field=problem.where) from None


# --------------------------------------------------------------------------- #
# Storing
# --------------------------------------------------------------------------- #


def _keys_present(conn: sqlite3.Connection, table: str, user_id: int, keys: list[str]) -> set[str]:
    assert table in ("weights", "blood_pressures")
    if not keys:
        return set()
    marks = ", ".join("?" for _ in keys)
    rows = conn.execute(f"SELECT source_key FROM {table} WHERE user_id = ? AND source_key IN ({marks})", (user_id, *keys))
    return {r[0] for r in rows}


def _count_by_day(conn: sqlite3.Connection, table: str, user_id: int, days: set[str]) -> dict[str, int]:
    assert table in ("weights", "blood_pressures")
    if not days:
        return {}
    wanted = sorted(days)
    marks = ", ".join("?" for _ in wanted)
    rows = conn.execute(f"SELECT date, COUNT(*) AS n FROM {table} WHERE user_id = ? AND date IN ({marks}) GROUP BY date",
                        (user_id, *wanted))
    return {r["date"]: int(r["n"]) for r in rows}


def store(conn: sqlite3.Connection, user: User, token_id: int, weights: list[PlannedWeight],
          readings: list[PlannedReading]) -> dict[str, Any]:
    """Add the rows the person does not have yet, in one transaction (all or nothing), and count them. The only error is the
    per-day limit, a ``400`` naming the row, after which nothing has been written."""
    added = {"weights": 0, "readings": 0}
    there = {"weights": 0, "readings": 0}
    watch = 0
    begin_immediate(conn)  # the checks below and the inserts see the same rows
    try:
        wkeys = _keys_present(conn, "weights", user.id, [w.key for w in weights])
        rkeys = _keys_present(conn, "blood_pressures", user.id, [r.key for r in readings if not r.watch])
        wmarks = known_weight_marks(conn, user.id, {w.date for w in weights})
        rmarks = known_reading_marks(conn, user.id, {r.date for r in readings if not r.watch})
        wday = _count_by_day(conn, "weights", user.id, {w.date for w in weights})
        rday = _count_by_day(conn, "blood_pressures", user.id, {r.date for r in readings if not r.watch})
        new_weights: list[PlannedWeight] = []
        new_readings: list[PlannedReading] = []
        for w in weights:
            mark = (w.date, w.time, w.kg)
            if w.key in wkeys or mark in wmarks:
                there["weights"] += 1
                continue
            if wday.get(w.date, 0) >= MAX_WEIGHTS_PER_DAY:
                raise ApiProblem(400, f"weights.{w.index}: too many weights for one day (max {MAX_WEIGHTS_PER_DAY})",
                                 field=f"weights.{w.index}")
            wkeys.add(w.key)
            wmarks.add(mark)
            wday[w.date] = wday.get(w.date, 0) + 1
            new_weights.append(w)
        for r in readings:
            if r.watch:
                watch += 1
                continue
            mark = (r.date, r.time, r.systolic, r.diastolic)
            if r.key in rkeys or mark in rmarks:
                there["readings"] += 1
                continue
            if rday.get(r.date, 0) >= MAX_READINGS_PER_DAY:
                raise ApiProblem(400, f"readings.{r.index}: too many blood pressure readings for one day (max {MAX_READINGS_PER_DAY})",
                                 field=f"readings.{r.index}")
            rkeys.add(r.key)
            rmarks.add(mark)
            rday[r.date] = rday.get(r.date, 0) + 1
            new_readings.append(r)
        now = utcnow()
        conn.executemany(
            "INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, api_token_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '', 'shortcut', ?, ?, ?, ?)",
            [(user.id, w.date, w.time, w.kg, w.context, w.key, token_id, now, now) for w in new_weights],
        )
        conn.executemany(
            "INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, "
            "api_token_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, '', 'shortcut', ?, ?, ?, ?)",
            [(user.id, r.date, r.time, r.systolic, r.diastolic, r.context, r.key, token_id, now, now) for r in new_readings],
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    added["weights"], added["readings"] = len(new_weights), len(new_readings)
    return {"added": added, "already_there": there, "refused": {"watch": watch}}


def process(conn: sqlite3.Connection, user: User, token_id: int, raw: bytes) -> dict[str, Any]:
    """Check the body, then store it (runs in a worker thread)."""
    weights, readings = read_body(raw)
    result = store(conn, user, token_id, weights, readings)
    # Counts and the token's id only: never a value, a time or a source name.
    logger.info("push: token %d added %d weights and %d readings, %d already there, %d refused", token_id,
                result["added"]["weights"], result["added"]["readings"],
                result["already_there"]["weights"] + result["already_there"]["readings"], result["refused"]["watch"])
    return result


@router.post(PATH, response_model=PushResult, summary="Add weights and blood pressure readings (device token, counts only)")
async def push_body(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The route a phone shortcut posts to; the module docstring has the whole contract."""
    ctx = auth_context(request)
    user = await run_in_threadpool(api_tokens.authenticate, request, conn, api_tokens.BODY_WRITE)
    token = request.state.api_token
    ctx.limits.take(RATE_LIMIT, f"token:{token.id}")
    if not _is_json_type(request):
        raise ApiProblem(415, "Send the body as JSON with the header Content-Type: application/json.")
    raw = await _read_capped(request)
    result = await run_in_threadpool(process, conn, user, token.id, raw)
    response.headers.update(NO_STORE)
    return result


def push_other() -> JSONResponse:
    """``405`` for every method but POST (the static mount at ``/`` would otherwise answer 404 for a GET)."""
    return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "POST", **NO_STORE})


for _method in ("GET", "DELETE", "PUT", "PATCH"):  # one route each, so every OpenAPI operation id is unique
    router.add_api_route(PATH, push_other, methods=[_method], operation_id=f"push_body_{_method.lower()}_not_allowed",
                         summary="Not offered: POST only (405)")


# --------------------------------------------------------------------------- #
# DELETE /api/me/tokens/{id}/body-rows ("Delete what it sent")
# --------------------------------------------------------------------------- #


TokenId = Annotated[int, Path(ge=1, le=api_tokens.MAX_ROW_ID)]


class DeletedRows(BaseModel):
    weights: int
    readings: int


class DeleteRowsResult(BaseModel):
    deleted: DeletedRows


@api_router.delete("/{token_id}/body-rows", response_model=DeleteRowsResult)
def delete_token_rows(token_id: TokenId, request: Request, user: CurrentUser,
                      conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Delete every weight and blood pressure reading this person's device token sent (rows whose ``api_token_id`` is the token) and
    nothing else: a row the person typed, imported, or edited afterwards (an edit makes it theirs) stays. The token must be one of
    the person's own **device** tokens; any other id (another person's, an assistant token, one already purged) is a 404. Works for a
    revoked or expired token that is still in the list. Audited as ``body.token_rows_deleted`` with the counts. Answers
    ``{"deleted": {"weights": n, "readings": n}}``."""
    row = conn.execute("SELECT id, scopes FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user.id)).fetchone()
    if row is None or api_tokens.family_of_scopes(row["scopes"]) != api_tokens.DEVICE:
        raise HTTPException(status_code=404, detail="token not found")
    weights = conn.execute("DELETE FROM weights WHERE user_id = ? AND api_token_id = ?", (user.id, token_id)).rowcount or 0
    readings = conn.execute("DELETE FROM blood_pressures WHERE user_id = ? AND api_token_id = ?", (user.id, token_id)).rowcount or 0
    audit(conn, user.id, "body.token_rows_deleted", "api_token", token_id, ip=request_ip(request), weights=weights, readings=readings)
    conn.commit()
    return {"deleted": {"weights": int(weights), "readings": int(readings)}}
