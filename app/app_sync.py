"""``POST /push/v1/sync``: the iPhone app sends the rows it added on the phone (design note 38 §5.5, step 4; ARCHITECTURE.md
"Device tokens and /push/v1"; guide ``docs/push.md``).

The phone keeps the person's log (note 38 §10, D2: local-first). When the person's server can be reached, the app sends the
**new** rows it made: food log entries, the person's own foods those entries need, lab results, symptoms, weights and blood
pressure readings. It never sends an edit or a delete, and it reads nothing back. Like ``/push/v1/body`` the route is bearer-only,
outside ``/api``, and never reads a cookie.

Order of checks (each answers before the next runs):

1. The middlewares (:mod:`app.security`): the global body limit, then ``Origin`` on the exact path (``403``).
2. A device token with the scope ``app:add`` (an **app** token, made in Settings → Phone shortcuts with "For the iPhone app"):
   the generic ``401`` for every failure, ``429`` for a blocked address. A shortcut token (``body:write`` only) is refused the
   same way. While ``push.enabled`` is off every request is that ``401`` and nothing is looked up.
3. The per-token limit: **60 requests an hour** (``ratelimit`` ``push_sync``, key ``token:<id>``). ``GET /push/v1/sync`` (the
   token check) counts toward it too.
4. ``Content-Type: application/json`` (``415``) and a body of at most **256 KiB** (``413``).
5. One JSON object with the lists ``foods``, ``entries``, ``labs``, ``symptoms``, ``weights`` and ``readings`` (each optional),
   at most **200 rows** in all and at least one; unknown fields refused. Every row is checked by the model of its normal create
   route (``FoodCreate``, ``LogCreate``, ``LabCreate``, ``SymptomCreate``, ``WeightCreate``, ``BloodPressureCreate``), so the
   limits and the words are the same. The first problem is a ``400`` naming the row (``entries.3.date: …``); nothing is stored.
6. In one ``BEGIN IMMEDIATE`` transaction: the token is checked again (``401`` if it ended meanwhile), then foods, entries,
   labs, symptoms, weights and readings, in that order. A row whose ``client_id`` this person's phone sent before (any app token)
   is counted ``already_there`` and nothing is added. Rows that depend on what this server holds are **skipped**, not refused:
   an entry whose food this server cannot find (``food_not_found``) and a symptom, weight or reading on a day that is full
   (``day_full``). A skipped row gets no receipt, so sending it again tries again.
7. At most **2,000 new receipts a day for each token** (a sliding 24 hours, read from the receipts): past it the whole request
   is rolled back and answers ``429`` with ``Retry-After``.

Every row is stored as the token owner's. Each new row gets a receipt in ``app_sync_rows`` (schema step 37) with the token, so
Settings shows what the token sent and "Delete what it sent" removes it. Weights and readings are also marked like a
shortcut's (``source = 'shortcut'``, ``api_token_id``), so the weight and blood pressure screens say "from a shortcut (name)".

The answer is **counts only**: ``{"added": {…}, "already_there": {…}, "skipped": {"food_not_found": n, "day_full": n}}``, with
``Cache-Control: no-store``. No row, id, name or value is echoed, and values are never logged.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import brand, units
from . import foods as foods_module
from .audit import audit
from .auth import api_tokens, clock
from .auth.accounts import begin_immediate
from .auth.context import auth_context
from .auth.errors import ApiProblem, too_many
from .auth.models import User
from .auth.ratelimit import register_limit
from .body import known_reading_marks, known_weight_marks, round_kg
from .data_import import FdcId, Id, builtin_match, food_key, own_food_key, parse_timestamp, shared_match
from .data_import import _source_license, _source_url
from .db import get_db, utcnow
from .foods import Provenance, fetch_user_food, link_food, scan_custom_food, stored_food_values
from .log import fetch_entry_by_client_id, insert_entry, resolve_purpose, resolve_servings
from .models import (
    MAX_READINGS_PER_DAY,
    MAX_SOURCE_KEY,
    MAX_SYMPTOMS_PER_DAY,
    MAX_WEIGHTS_PER_DAY,
    BloodPressureCreate,
    FoodCreate,
    LabCreate,
    LogCreate,
    SymptomCreate,
    WeightCreate,
    validate_client_id,
    validate_gtin,
)
from .push import NO_STORE, _is_json_type, parse_json, read_capped
from .security import flatten_validation_errors

logger = logging.getLogger(f"{brand.LOGGER_NAME}.push")

PATH = "/sync"
MAX_BODY_BYTES = 256 * 1024
MAX_ROWS = 200  # every list together
MAX_PER_DAY = 2000  # new receipts per token in a sliding 24 hours
RATE_LIMIT = "push_sync"
register_limit(RATE_LIMIT, 60, 3600, "Too many requests from this app. Try again later.")
DAY_CAP_MESSAGE = "This app has sent as much as it may in one day. It sends the rest later."

KINDS: dict[str, str] = {  # the request's list → the receipt's kind
    "foods": "food", "entries": "entry", "labs": "lab", "symptoms": "symptom", "weights": "weight", "readings": "reading",
}
TABLES: dict[str, str] = {  # the receipt's kind → the table its row is in
    "food": "foods", "entry": "log_entries", "lab": "lab_results", "symptom": "symptoms", "weight": "weights",
    "reading": "blood_pressures",
}
SKIP_REASONS = ("food_not_found", "day_full")

router = APIRouter(prefix="/push/v1", tags=["push"])


# --------------------------------------------------------------------------- #
# The request: every row is its normal create model plus a client_id
# --------------------------------------------------------------------------- #


def _client_id(value: str) -> str:
    out = validate_client_id(value)
    assert out is not None
    return out


def _created_at(value: str | None) -> str | None:
    return None if value is None else parse_timestamp(value)


class SyncFood(FoodCreate):
    """A food the phone's entries use, other than a built-in one: one the person made (``source: custom``), or a USDA
    (``fdc_id``) or Open Food Facts (``gtin``) food the phone found. Checked exactly like ``POST /api/foods``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    client_id: str
    source: Literal["custom", "usda", "off"] = "custom"
    fdc_id: FdcId | None = None
    source_url: str | None = Field(default=None, max_length=200)
    source_license: str | None = Field(default=None, max_length=40)

    _cid = field_validator("client_id")(staticmethod(_client_id))
    _url = field_validator("source_url")(staticmethod(_source_url))
    _licence = field_validator("source_license")(staticmethod(_source_license))

    @model_validator(mode="after")
    def _keys(self) -> "SyncFood":
        if self.source == "usda" and (self.fdc_id is None or self.fdc_id < 1):
            raise ValueError("a USDA food needs its fdc_id")
        if self.source == "off" and not self.gtin:
            raise ValueError("an Open Food Facts food needs its gtin (barcode)")
        return self


class BuiltinRef(BaseModel):
    """A built-in food by the key the built-in list is kept up to date by: its ``fdc_id``, or its name when it has none."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    fdc_id: FdcId | None = None
    name: str = Field(min_length=1, max_length=200)


class UsdaRef(BaseModel):
    """A USDA food this server already holds, by ``fdc_id``; the name (or the serving weight) must agree, as for an import."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    fdc_id: Id
    name: str = Field(min_length=1, max_length=200)
    serving_g: float | None = Field(default=None, gt=0, le=100_000, allow_inf_nan=False)


class OffRef(BaseModel):
    """An Open Food Facts food this server already holds, by barcode; the name (or the serving weight) must agree."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    gtin: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    serving_g: float | None = Field(default=None, gt=0, le=100_000, allow_inf_nan=False)

    _gtin = field_validator("gtin")(staticmethod(validate_gtin))


class FoodRef(BaseModel):
    """Which food an entry is: exactly one of ``client_id`` (a food in ``foods``, now or earlier), ``builtin``, ``usda``, ``off``."""

    model_config = ConfigDict(extra="forbid")

    client_id: str | None = None
    builtin: BuiltinRef | None = None
    usda: UsdaRef | None = None
    off: OffRef | None = None

    @field_validator("client_id")
    @classmethod
    def _cid(cls, v: str | None) -> str | None:
        return validate_client_id(v)

    @model_validator(mode="after")
    def _one(self) -> "FoodRef":
        given = [k for k in ("client_id", "builtin", "usda", "off") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of client_id, builtin, usda and off")
        return self


class SyncEntry(LogCreate):
    """A food log entry, checked exactly like ``POST /api/log``, with ``food`` in place of ``food_id`` (ids on the phone mean
    nothing here). ``created_at`` is kept when given, as an import keeps it."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    food_id: None = None  # type: ignore[assignment]
    food: FoodRef
    client_id: str  # type: ignore[assignment]
    created_at: str | None = Field(default=None, max_length=40)

    _cid = field_validator("client_id")(staticmethod(_client_id))
    _created = field_validator("created_at")(staticmethod(_created_at))


class SyncLab(LabCreate):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    client_id: str
    created_at: str | None = Field(default=None, max_length=40)

    _cid = field_validator("client_id")(staticmethod(_client_id))
    _created = field_validator("created_at")(staticmethod(_created_at))


class SyncSymptom(SymptomCreate):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    client_id: str
    created_at: str | None = Field(default=None, max_length=40)

    _cid = field_validator("client_id")(staticmethod(_client_id))
    _created = field_validator("created_at")(staticmethod(_created_at))


def _source_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("must be one line of plain text")
    return value


class SyncWeight(WeightCreate):
    """A weight, checked exactly like ``POST /api/body/weights``. ``source_key`` is the key of an Apple Health sample (the
    phone's ``source_key``), so a sample the app already sent to ``/push/v1/body`` is not added twice."""

    client_id: str
    source_key: str | None = Field(default=None, max_length=MAX_SOURCE_KEY)

    _cid = field_validator("client_id")(staticmethod(_client_id))
    _key = field_validator("source_key")(staticmethod(_source_key))


class SyncReading(BloodPressureCreate):
    client_id: str
    source_key: str | None = Field(default=None, max_length=MAX_SOURCE_KEY)

    _cid = field_validator("client_id")(staticmethod(_client_id))
    _key = field_validator("source_key")(staticmethod(_source_key))


class SyncBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    foods: list[SyncFood] = Field(default_factory=list)
    entries: list[SyncEntry] = Field(default_factory=list)
    labs: list[SyncLab] = Field(default_factory=list)
    symptoms: list[SyncSymptom] = Field(default_factory=list)
    weights: list[SyncWeight] = Field(default_factory=list)
    readings: list[SyncReading] = Field(default_factory=list)


class SyncCounts(BaseModel):
    foods: int
    entries: int
    labs: int
    symptoms: int
    weights: int
    readings: int


class SyncSkipped(BaseModel):
    food_not_found: int
    day_full: int


class SyncResult(BaseModel):
    """Counts only: nothing the app sent is echoed."""

    added: SyncCounts
    already_there: SyncCounts
    skipped: SyncSkipped


class SyncCheck(BaseModel):
    ok: Literal[True]


def read_body(raw: bytes) -> SyncBody:
    """The checked request, or a ``400`` naming the first row that is not valid. Nothing is stored here."""
    try:
        doc = parse_json(raw)
    except ValueError:
        raise ApiProblem(400, "The body is not valid JSON.") from None
    if not isinstance(doc, dict):
        raise ApiProblem(400, 'Send one JSON object: {"foods": [...], "entries": [...], "labs": [...], ...}.')
    count = sum(len(doc[k]) for k in KINDS if isinstance(doc.get(k), list))
    if count > MAX_ROWS:
        raise ApiProblem(400, f"Send at most {MAX_ROWS} rows in one request (all the lists together).")
    try:
        body = SyncBody.model_validate(_plain_numbers(doc))
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_input=False, include_context=False)
        detail, flat = flatten_validation_errors(errors[:1])
        raise ApiProblem(400, detail, field=".".join(str(p) for p in errors[0]["loc"]), errors=flat) from None
    if not any(getattr(body, k) for k in KINDS):
        raise ApiProblem(400, "Send at least one row.")
    for key in KINDS:
        seen: dict[str, int] = {}
        for index, row in enumerate(getattr(body, key)):
            if row.client_id in seen:
                where = f"{key}.{index}.client_id"
                raise ApiProblem(400, f"{where}: repeats {key}.{seen[row.client_id]}.client_id", field=where)
            seen[row.client_id] = index
    return body


def _plain_numbers(value: Any) -> Any:
    """:func:`app.push.parse_json` keeps the text of a decimal number for the Health key; these models want plain floats."""
    if isinstance(value, float):
        return float(value)
    if isinstance(value, list):
        return [_plain_numbers(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain_numbers(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------- #
# Receipts (schema step 37)
# --------------------------------------------------------------------------- #


def _receipts(conn: sqlite3.Connection, user_id: int, kind: str, client_ids: list[str]) -> dict[str, sqlite3.Row]:
    out: dict[str, sqlite3.Row] = {}
    for start in range(0, len(client_ids), 400):
        chunk = client_ids[start:start + 400]
        if not chunk:
            continue
        marks = ", ".join("?" for _ in chunk)
        for r in conn.execute(f"SELECT id, client_id, row_id, added FROM app_sync_rows WHERE user_id = ? AND kind = ? "
                              f"AND client_id IN ({marks})", (user_id, kind, *chunk)):
            out[r["client_id"]] = r
    return out


def sent_by_tokens(conn: sqlite3.Connection, user_id: int) -> dict[int, dict[str, int]]:
    """How many rows each app token added that are still here, by list name (``entries``, ``foods``, ``labs``, ``symptoms``):
    the receipts with ``added = 1`` whose row still exists for the person. Weights and readings are counted by
    :func:`app.auth.api_tokens.sent_counts` from their own ``api_token_id``."""
    out: dict[int, dict[str, int]] = {}
    for key, kind in (("entries", "entry"), ("foods", "food"), ("labs", "lab"), ("symptoms", "symptom")):
        table = TABLES[kind]
        owner = "owner_user_id" if table == "foods" else "user_id"
        rows = conn.execute(
            f"""SELECT r.api_token_id, COUNT(*) AS n FROM app_sync_rows r JOIN {table} t ON t.id = r.row_id AND t.{owner} = r.user_id
                WHERE r.user_id = ? AND r.kind = ? AND r.added = 1 AND r.api_token_id IS NOT NULL GROUP BY r.api_token_id""",
            (int(user_id), kind),
        )
        for r in rows:
            out.setdefault(int(r["api_token_id"]), {})[key] = int(r["n"])
    return out


def delete_sent(conn: sqlite3.Connection, user_id: int, token_id: int) -> dict[str, int]:
    """Delete the entries, labs and symptoms the token added, then the person's own foods it added that nothing of theirs uses
    any more (an entry or saved meal the person made with it keeps it). Rows the app found already here are never touched.
    Returns the counts by list name; the caller commits. Weights and readings are deleted by their ``api_token_id``."""
    uid, tid = int(user_id), int(token_id)
    counts: dict[str, int] = {}
    for key, kind in (("entries", "entry"), ("labs", "lab"), ("symptoms", "symptom")):
        table = TABLES[kind]
        cur = conn.execute(
            f"""DELETE FROM {table} WHERE user_id = ? AND id IN
                (SELECT row_id FROM app_sync_rows WHERE user_id = ? AND api_token_id = ? AND kind = ? AND added = 1)""",
            (uid, uid, tid, kind),
        )
        counts[key] = int(cur.rowcount or 0)
    foods = 0
    for (food_id,) in conn.execute(
            """SELECT f.id FROM foods f JOIN app_sync_rows r ON r.row_id = f.id
               WHERE r.user_id = ? AND r.api_token_id = ? AND r.kind = 'food' AND r.added = 1
                 AND f.owner_user_id = ? AND f.source = 'custom'""", (uid, tid, uid)).fetchall():
        if not foods_module.food_is_referenced(conn, int(food_id), uid):
            foods += conn.execute("DELETE FROM foods WHERE id = ? AND owner_user_id = ?", (int(food_id), uid)).rowcount or 0
    counts["foods"] = int(foods)
    return counts


# --------------------------------------------------------------------------- #
# Storing
# --------------------------------------------------------------------------- #


class Sync:
    """One request's work on ``conn``, inside the caller's transaction."""

    def __init__(self, conn: sqlite3.Connection, user: User, token_id: int) -> None:
        self.conn = conn
        self.uid = int(user.id)
        self.token_id = int(token_id)
        self.added: Counter[str] = Counter()
        self.there: Counter[str] = Counter()
        self.skipped: Counter[str] = Counter()
        self.new_receipts = 0
        self.food_ids: dict[str, int] = {}  # a food's client_id -> its food id here
        self.now = utcnow()  # the rows' created_at, as the normal routes write it
        self.stamp = clock.now_iso()  # the receipts' (the day cap reads it)

    def free(self, kind: str, client_id: str) -> str | None:
        """The phone's ``client_id`` for a row it adds, when the person has no row of that kind with it (schema step 38): the phone
        and the server then name the row the same (design note 39 §8.2). Else None, and the row gets an ID of its own."""
        table = TABLES[kind]
        owner = "owner_user_id" if table == "foods" else "user_id"
        if not any(r[1] == "client_id" for r in self.conn.execute(f"PRAGMA table_info({table})")):
            return None
        taken = self.conn.execute(f"SELECT 1 FROM {table} WHERE {owner} = ? AND client_id = ?", (self.uid, client_id)).fetchone()
        return None if taken else client_id

    def receipt(self, kind: str, client_id: str, row_id: int, added: bool) -> None:
        self.conn.execute(
            "INSERT INTO app_sync_rows (user_id, api_token_id, kind, client_id, row_id, added, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.uid, self.token_id, kind, client_id, int(row_id), int(added), self.stamp),
        )
        self.new_receipts += 1

    # -- foods ----------------------------------------------------------------------------------------------------------
    def foods(self, foods: list[SyncFood]) -> None:
        c = self.conn
        known = _receipts(c, self.uid, "food", [f.client_id for f in foods])
        index: dict[tuple, list[int]] = {}
        for row in c.execute("SELECT * FROM foods WHERE owner_user_id = ? AND source = 'custom' ORDER BY id", (self.uid,)):
            index.setdefault(own_food_key(row), []).append(int(row["id"]))
        linked = {int(r[0]) for r in c.execute("SELECT food_id FROM user_food_links WHERE user_id = ?", (self.uid,))}
        for food in foods:
            old = known.get(food.client_id)
            if old is not None and fetch_user_food(c, self.uid, int(old["row_id"])) is not None:
                self.food_ids[food.client_id] = int(old["row_id"])
                self.there["foods"] += 1
                continue
            food_id, added_row, new = self._resolve_food(food, index, linked)
            self.food_ids[food.client_id] = food_id
            (self.added if new else self.there)["foods"] += 1
            if old is None:
                self.receipt("food", food.client_id, food_id, added_row)
            else:  # the food it named was deleted here since: the receipt now names the food found or made again
                c.execute("UPDATE app_sync_rows SET row_id = ?, added = ?, api_token_id = ? WHERE id = ?",
                          (food_id, int(added_row), self.token_id, int(old["id"])))

    def _resolve_food(self, food: SyncFood, index: dict[tuple, list[int]], linked: set[int]) -> tuple[int, bool, bool]:
        """``(food id, the receipt's added, counted as added)``. A USDA or Open Food Facts food is the shared row this server
        holds (linked to the person), as an import links it; else it is kept as the person's own copy, as an import keeps it."""
        c = self.conn
        if food.source == "usda":
            row = foods_module.fetch_user_usda_food(c, self.uid, int(food.fdc_id or 0))
            if row is not None:
                return int(row["id"]), False, False
        if food.source in ("usda", "off"):
            row = shared_match(c, food.source, fdc_id=food.fdc_id, gtin=food.gtin, name=food.name, serving_g=food.serving_g)
            if row is not None:
                new = int(row["id"]) not in linked
                link_food(c, self.uid, int(row["id"]))
                linked.add(int(row["id"]))
                return int(row["id"]), False, new
        flags, notes, ingredients, found = scan_custom_food(food.name, food.flags, food.kidney_notes, food.ingredients_text)
        serving, values = stored_food_values(food.nutrients, flags, food.serving_g)
        key = food_key(food.name, food.brand, food.category, food.serving_desc, serving, values, flags, notes, food.gtin, False)
        same = index.get(key)
        if same:
            return same[0], False, False
        food_id = foods_module.insert_food(
            c, source="custom", owner_user_id=self.uid, name=food.name, brand=food.brand, category=food.category,
            serving_desc=food.serving_desc, serving_g=food.serving_g, nutrients=food.nutrients, flags=flags, kidney_notes=notes,
            fdc_id=food.fdc_id if food.source == "usda" else None,
            provenance=Provenance(gtin=food.gtin, source_url=food.source_url, source_license=food.source_license,
                                  ingredients_text=ingredients, additives=tuple(found)),
        )
        index.setdefault(key, []).append(food_id)
        cid = self.free("food", food.client_id)
        if cid is not None:
            c.execute("UPDATE foods SET client_id = ? WHERE id = ? AND owner_user_id = ?", (cid, food_id, self.uid))
        return food_id, True, True

    def _food_for(self, ref: FoodRef) -> sqlite3.Row | None:
        c = self.conn
        if ref.client_id is not None:
            food_id = self.food_ids.get(ref.client_id)
            if food_id is None:
                old = _receipts(c, self.uid, "food", [ref.client_id]).get(ref.client_id)
                food_id = None if old is None else int(old["row_id"])
            return None if food_id is None else fetch_user_food(c, self.uid, food_id)
        if ref.builtin is not None:
            return builtin_match(c, ref.builtin.name, ref.builtin.fdc_id)
        if ref.usda is not None:
            row = foods_module.fetch_user_usda_food(c, self.uid, ref.usda.fdc_id)
            if row is None:
                row = shared_match(c, "usda", fdc_id=ref.usda.fdc_id, gtin=None, name=ref.usda.name, serving_g=ref.usda.serving_g)
        else:
            assert ref.off is not None
            row = c.execute(
                f"""SELECT f.* FROM foods f WHERE f.source = 'off' AND f.gtin = ? AND f.owner_user_id IS NULL
                    AND {foods_module.access_clause('f')} ORDER BY f.id LIMIT 1""",
                (ref.off.gtin, *foods_module.access_params(self.uid)),
            ).fetchone()
            if row is None:
                row = shared_match(c, "off", fdc_id=None, gtin=ref.off.gtin, name=ref.off.name, serving_g=ref.off.serving_g)
        if row is not None and row["source"] in ("usda", "off"):  # a built-in food carrying the fdc_id needs no link
            link_food(c, self.uid, int(row["id"]))
        return row

    # -- entries --------------------------------------------------------------------------------------------------------
    def entries(self, entries: list[SyncEntry]) -> None:
        c = self.conn
        known = _receipts(c, self.uid, "entry", [e.client_id for e in entries])
        for i, e in enumerate(entries):
            if e.client_id in known:
                self.there["entries"] += 1
                continue
            existing = fetch_entry_by_client_id(c, self.uid, e.client_id)
            if existing is not None:
                self.there["entries"] += 1
                self.receipt("entry", e.client_id, int(existing["id"]), False)
                continue
            food = self._food_for(e.food)
            if food is None:
                self.skipped["food_not_found"] += 1
                continue
            try:
                servings, grams = resolve_servings(food, e.servings, e.grams)
            except HTTPException as exc:
                raise ApiProblem(400, f"entries.{i}.{exc.detail}", field=f"entries.{i}.grams") from None
            if e.created_at is not None:
                same = c.execute(
                    """SELECT id FROM log_entries WHERE user_id = ? AND date = ? AND meal = ? AND food_id = ? AND status = ?
                       AND created_at = ? AND abs(servings - ?) < 0.0005
                       AND ((grams IS NULL AND ? IS NULL) OR abs(grams - ?) < 0.05) LIMIT 1""",
                    (self.uid, e.date, e.meal, food["id"], e.status, e.created_at, servings, grams, grams or 0),
                ).fetchone()
                if same is not None:  # imported from a file the phone exported
                    self.there["entries"] += 1
                    self.receipt("entry", e.client_id, int(same["id"]), False)
                    continue
            entry_id = insert_entry(c, user_id=self.uid, date=e.date, meal=e.meal, food=food, servings=servings, grams=grams,
                                    note=e.note, status=e.status, purpose=resolve_purpose(food, e.purpose),
                                    client_id=e.client_id, created_at=e.created_at, updated_at=e.created_at)
            self.added["entries"] += 1
            self.receipt("entry", e.client_id, entry_id, True)

    # -- labs and symptoms ------------------------------------------------------------------------------------------------
    def labs(self, labs: list[SyncLab]) -> None:
        c = self.conn
        known = _receipts(c, self.uid, "lab", [lab.client_id for lab in labs])
        for lab in labs:
            if lab.client_id in known:
                self.there["labs"] += 1
                continue
            result = units.convert(lab.analyte, lab.value, lab.unit)  # checked by LabCreate already
            if lab.created_at is not None:
                same = next((r for r in c.execute(
                    "SELECT id, value FROM lab_results WHERE user_id = ? AND analyte = ? AND taken_on = ? AND created_at = ?",
                    (self.uid, result["analyte"], lab.taken_on, lab.created_at))
                    if units.format_value(result["analyte"], r["value"]) == units.format_value(result["analyte"], result["value"])),
                    None)
                if same is not None:
                    self.there["labs"] += 1
                    self.receipt("lab", lab.client_id, int(same["id"]), False)
                    continue
            cur = c.execute(
                """INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, note, created_at, client_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.uid, result["analyte"], result["value"], result["entered_value"], result["entered_unit"], lab.taken_on,
                 lab.note, lab.created_at or self.now, self.free("lab", lab.client_id)),
            )
            self.added["labs"] += 1
            self.receipt("lab", lab.client_id, int(cur.lastrowid), True)

    def symptoms(self, symptoms: list[SyncSymptom]) -> None:
        c = self.conn
        known = _receipts(c, self.uid, "symptom", [s.client_id for s in symptoms])
        per_day: Counter[str] = Counter()
        for day in {s.date for s in symptoms}:
            per_day[day] = int(c.execute("SELECT COUNT(*) FROM symptoms WHERE user_id = ? AND date = ?", (self.uid, day)).fetchone()[0])
        for s in symptoms:
            if s.client_id in known:
                self.there["symptoms"] += 1
                continue
            if s.created_at is not None:
                same = c.execute(
                    """SELECT id FROM symptoms WHERE user_id = ? AND date = ? AND symptom = ? AND label = ? AND severity = ?
                       AND note = ? AND created_at = ? LIMIT 1""",
                    (self.uid, s.date, s.symptom, s.label, s.severity, s.note, s.created_at)).fetchone()
                if same is not None:
                    self.there["symptoms"] += 1
                    self.receipt("symptom", s.client_id, int(same["id"]), False)
                    continue
            if per_day[s.date] >= MAX_SYMPTOMS_PER_DAY:
                self.skipped["day_full"] += 1
                continue
            cur = c.execute(
                "INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at, client_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.uid, s.date, s.symptom, s.label, s.severity, s.note, s.created_at or self.now, self.free("symptom", s.client_id)),
            )
            per_day[s.date] += 1
            self.added["symptoms"] += 1
            self.receipt("symptom", s.client_id, int(cur.lastrowid), True)

    # -- weights and readings (stored like a shortcut's: app/push.py) -----------------------------------------------------
    def _body(self, key: str, kind: str, rows: list[Any]) -> None:
        c = self.conn
        table = TABLES[kind]
        known = _receipts(c, self.uid, kind, [r.client_id for r in rows])
        days = {r.date for r in rows}
        keys = {r[0]: int(r[1]) for r in c.execute(f"SELECT source_key, id FROM {table} WHERE user_id = ? AND source_key IS NOT NULL",
                                                   (self.uid,))}
        marks = known_weight_marks(c, self.uid, days) if kind == "weight" else known_reading_marks(c, self.uid, days)
        per_day: Counter[str] = Counter()
        for day in days:
            per_day[day] = int(c.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ? AND date = ?", (self.uid, day)).fetchone()[0])
        limit = MAX_WEIGHTS_PER_DAY if kind == "weight" else MAX_READINGS_PER_DAY
        for r in rows:
            if r.client_id in known:
                self.there[key] += 1
                continue
            if r.source_key is not None and r.source_key in keys:
                self.there[key] += 1
                self.receipt(kind, r.client_id, keys[r.source_key], False)
                continue
            mark = (r.date, r.time, round_kg(r.kg)) if kind == "weight" else (r.date, r.time, r.systolic, r.diastolic)
            if r.time is not None and mark in marks:
                self.there[key] += 1  # the same reading from the Health app or a shortcut (no row id to name: no receipt)
                continue
            if per_day[r.date] >= limit:
                self.skipped["day_full"] += 1
                continue
            if kind == "weight":
                cur = c.execute(
                    "INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, api_token_id, created_at, "
                    "updated_at, client_id) VALUES (?, ?, ?, ?, ?, ?, 'shortcut', ?, ?, ?, ?, ?)",
                    (self.uid, r.date, r.time, round_kg(r.kg), r.context, r.note, r.source_key, self.token_id, self.now, self.now,
                     self.free(kind, r.client_id)),
                )
            else:
                cur = c.execute(
                    "INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, "
                    "api_token_id, created_at, updated_at, client_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'shortcut', ?, ?, ?, ?, ?)",
                    (self.uid, r.date, r.time, r.systolic, r.diastolic, r.pulse, r.context, r.note, r.source_key, self.token_id,
                     self.now, self.now, self.free(kind, r.client_id)),
                )
            if r.source_key is not None:
                keys[r.source_key] = int(cur.lastrowid)
            if r.time is not None:
                marks.add(mark)  # type: ignore[arg-type]
            per_day[r.date] += 1
            self.added[key] += 1
            self.receipt(kind, r.client_id, int(cur.lastrowid), True)

    def answer(self) -> dict[str, Any]:
        return {"added": {k: int(self.added[k]) for k in KINDS},
                "already_there": {k: int(self.there[k]) for k in KINDS},
                "skipped": {k: int(self.skipped[k]) for k in SKIP_REASONS}}


def received_today(conn: sqlite3.Connection, token_id: int) -> tuple[int, int]:
    """How many receipts the token wrote in the last 24 hours, and the seconds until the oldest of them is a day old."""
    now = clock.now()
    row = conn.execute("SELECT COUNT(*), MIN(created_at) FROM app_sync_rows WHERE api_token_id = ? AND created_at > ?",
                       (int(token_id), clock.iso(now - timedelta(days=1)))).fetchone()
    oldest = clock.parse(row[1]) if row[1] else None
    wait = int((oldest + timedelta(days=1) - now).total_seconds()) + 1 if oldest is not None else 1
    return int(row[0]), max(1, wait)


def store(conn: sqlite3.Connection, user: User, token: api_tokens.TokenInfo, body: SyncBody, request: Request) -> dict[str, Any]:
    """Recheck access, then add what is missing and count it, in one transaction. Any refusal leaves nothing written."""
    begin_immediate(conn)
    try:
        api_tokens.require_current_write(request, conn, api_tokens.APP_ADD)
        work = Sync(conn, user, token.id)
        work.foods(body.foods)
        work.entries(body.entries)
        work.labs(body.labs)
        work.symptoms(body.symptoms)
        work._body("weights", "weight", body.weights)
        work._body("readings", "reading", body.readings)
        if work.new_receipts:
            count, wait = received_today(conn, token.id)
            if count > MAX_PER_DAY:
                raise too_many(wait, DAY_CAP_MESSAGE)
        result = work.answer()
        if any(result["added"].values()):
            audit(conn, user.id, "app.rows_added", "api_token", token.id, via=token.name, **result["added"])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return result


def process(conn: sqlite3.Connection, user: User, token: api_tokens.TokenInfo, raw: bytes, request: Request) -> dict[str, Any]:
    """Check the body, then store it (runs in a worker thread)."""
    body = read_body(raw)
    result = store(conn, user, token, body, request)
    # Counts and the token's id only: never a value, a date or a name.
    logger.info("sync: token %d added %s, %s already there, %s skipped", token.id,
                sum(result["added"].values()), sum(result["already_there"].values()), sum(result["skipped"].values()))
    return result


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.post(PATH, response_model=SyncResult, summary="Add rows the iPhone app made (app token, add only, counts only)")
async def push_sync(request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The route the iPhone app posts its new rows to; the module docstring has the whole contract."""
    ctx = auth_context(request)
    user = await run_in_threadpool(api_tokens.authenticate, request, conn, api_tokens.APP_ADD)
    token = request.state.api_token
    ctx.limits.take(RATE_LIMIT, f"token:{token.id}")
    if not _is_json_type(request):
        raise ApiProblem(415, "Send the body as JSON with the header Content-Type: application/json.")
    raw = await read_capped(request, MAX_BODY_BYTES)
    result = await run_in_threadpool(process, conn, user, token, raw, request)
    response.headers.update(NO_STORE)
    return result


@router.get(PATH, response_model=SyncCheck, summary="Test an app token without sending anything")
async def push_sync_check(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """``{"ok": true}`` when the token may use ``POST /push/v1/sync``: the same check, the same generic ``401``, and one request of
    the same 60 an hour. Nothing is read or stored but the token's last use."""
    await run_in_threadpool(api_tokens.authenticate, request, conn, api_tokens.APP_ADD)
    auth_context(request).limits.take(RATE_LIMIT, f"token:{request.state.api_token.id}")
    return JSONResponse({"ok": True}, headers=NO_STORE)


def sync_other() -> JSONResponse:
    """``405`` for every method but GET and POST."""
    return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "GET, POST", **NO_STORE})


for _method in ("DELETE", "PUT", "PATCH"):  # one route each, so every OpenAPI operation id is unique
    router.add_api_route(PATH, sync_other, methods=[_method], operation_id=f"push_sync_{_method.lower()}_not_allowed",
                         summary="Not offered: GET and POST only (405)")
