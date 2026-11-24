"""The change feed for the iPhone app both ways: ``GET`` and ``POST /push/v1/changes`` and ``POST /push/v1/match`` (design note 39 §8,
plan step 5; ARCHITECTURE.md "The change feed"; guide ``docs/push.md``).

Every route takes a device token with ``app:sync`` (:data:`app.auth.api_tokens.AppSyncUser`): the generic ``401`` for every failure,
``push.enabled`` and ``push.app_sync`` both on, no cookie ever read, ``Origin`` refused when it is not this server's (``403``), every
query scoped by the token's owner. Answers have ``Cache-Control: no-store``; the log holds the token's id and counts, never a value.

**What syncs** (:data:`KINDS`): ``food`` (the person's own foods), ``entry``, ``meal`` (saved meals and recipes), ``lab``,
``symptom``, ``weight`` and ``reading``. A row's ``id`` here is its ``client_id`` (schema step 38), the same on every device.

``GET /push/v1/changes?after=<cursor>&limit=<1..500>`` (120 an hour for each token, ``push_changes``) answers::

    {"changes": [{"kind": "entry", "id": "<client_id>", "op": "put", "version": "<16 hex>", "row": {…}},
                 {"kind": "lab", "id": "<client_id>", "op": "delete", "version": null}],
     "foods": [{"ref": {…}, "food": {…}}],
     "next": "<cursor>", "more": false}

* Only the latest state of each row since the cursor, oldest change first. ``row`` has the shape of the export
  (``GET /api/me/export.zip``), with ``client_id``; an entry's and a saved meal item's ``food`` is a reference in the shape
  ``POST /push/v1/sync`` takes: ``{"client_id": …}`` (the person's own food), ``{"builtin": {"fdc_id", "name"}}``,
  ``{"usda": {"fdc_id", "name", "serving_g"}}`` or ``{"off": {"gtin", "name", "serving_g"}}``.
* ``foods`` holds every food (not built-in) that the entries and saved meals of this answer use, with the export's food record, so
  the phone can show them at once.
* The cursor is opaque: send ``next`` back as ``after``. Missing or ``"0"`` reads everything. A cursor older than the tombstones
  kept (180 days) is ``410 {"resync": true}``: read again from the start.

``POST /push/v1/changes`` (120 an hour for each token together with ``match``, ``push_changes_write``) takes
``{"changes": [{"kind", "id", "op": "edit" | "delete", "base": "<version>", "fields"?: {…}, "version"?: "<version>"}]}``: at most 200,
at most 256 KiB. ``base`` is the version the phone's change was made on; ``fields`` (edit only) is the body of that kind's ``PUT`` route
(an entry's ``LogUpdate``; a food's ``FoodCreate``; a saved meal's ``MealTemplateCreate``; ``SymptomCreate``, ``WeightCreate``,
``BloodPressureCreate``); ``version`` (optional) is the version of the phone's copy after its change. Each change runs through the same
function as its ``PUT`` or ``DELETE`` route, with ``If-Match: "<base>"``, and is answered on its own:

* ``{"status": "done", "version": …}`` (``version`` null after a delete);
* ``{"status": "conflict", "version": …, "row": {…}}``: the row changed since ``base``; nothing was written (note 02: never
  overwrite another device's change). For an edit whose ``version`` equals the row's version now, the same change was made on both
  sides: that is ``done``, and nothing is written. A delete of a row changed since ``base`` is always a conflict;
* ``{"status": "gone"}``: no such row for this person (deleted elsewhere, or never here);
* ``{"status": "refused", "detail": …}``: the change is not valid (the route's ``400`` or ``409``, or lab results, which are only added
  and deleted).

One answer never stops the others.

``POST /push/v1/match`` (the first two-way sync, §8.7) takes ``{"ids": {"<kind>": ["<the phone's client_id>", …]}}`` (at most 2,000
in all) and answers ``{"known": {"<kind>": {"<phone id>": "<this server's id>"}}, "unknown": {"<kind>": [ids]}}``: an ID this server
has for the person maps to itself; one the phone sent before (step 4's receipts, ``POST /push/v1/sync``) that matched a row already
here maps to that row's ID.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import replace
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import body as body_module
from . import brand, foods as foods_module, labs as labs_module, log as log_module, meals as meals_module
from . import symptoms as symptoms_module
from .app_gateway import note_use
from .auth import api_tokens, clock, housekeeping
from .auth.accounts import begin_immediate
from .auth.context import auth_context
from .auth.errors import ApiProblem
from .auth.models import User
from .auth.ratelimit import register_limit
from .db import get_db, table_exists
from .models import (BloodPressureCreate, FoodCreate, LogUpdate, MealTemplateCreate, SymptomCreate, WeightCreate,
                     validate_client_id)
from .push import NO_STORE, _is_json_type, read_capped
from .row_versions import row_version
from .security import flatten_validation_errors

logger = logging.getLogger(f"{brand.LOGGER_NAME}.push")

router = APIRouter(prefix="/push/v1", tags=["push"])
CHANGES_PATH = "/changes"
MATCH_PATH = "/match"

FEED_LIMIT = "push_changes"
WRITE_LIMIT = "push_changes_write"
register_limit(FEED_LIMIT, 120, 3600, "Too many requests from this app. Try again later.")
register_limit(WRITE_LIMIT, 120, 3600, "Too many requests from this app. Try again later.")

MAX_PAGE = 500
MAX_CHANGES = 200
MAX_MATCH_IDS = 2000
MAX_BODY_BYTES = 256 * 1024
TOMBSTONE_DAYS = 180
RESYNC = "This iPhone has not synced for too long. Read everything again from the start."

# kind → (table, the column that names the person)
TABLES: dict[str, tuple[str, str]] = {
    "food": ("foods", "owner_user_id"), "entry": ("log_entries", "user_id"), "meal": ("meal_templates", "user_id"),
    "lab": ("lab_results", "user_id"), "symptom": ("symptoms", "user_id"), "weight": ("weights", "user_id"),
    "reading": ("blood_pressures", "user_id"),
}
RECEIPT_KINDS = ("food", "entry", "lab", "symptom", "weight", "reading")  # step 37's receipts (no saved meals)
_CURSOR_RE = re.compile(r"^(0|[1-9][0-9]{0,18})$")
_VERSION_RE = re.compile(r"^[0-9a-f]{16}$")


# --------------------------------------------------------------------------- #
# Rows as the export shows them
# --------------------------------------------------------------------------- #


def food_ref(food: sqlite3.Row, user_id: int) -> dict[str, Any] | None:
    """How the phone names a food: by its ``client_id`` (the person's own), or by the keys of a shared one."""
    source = food["source"]
    if source == "custom":
        return {"client_id": food["client_id"]} if food["owner_user_id"] == user_id else None
    if source == "builtin":
        return {"builtin": {"fdc_id": food["fdc_id"], "name": food["name"]}}
    if source == "usda":
        return {"usda": {"fdc_id": food["fdc_id"], "name": food["name"], "serving_g": float(food["serving_g"])}}
    if source == "off":
        return {"off": {"gtin": food["gtin"], "name": food["name"], "serving_g": float(food["serving_g"])}}
    return None


class Reader:
    """Rows of one person, in the export's shape, and the foods they use."""

    def __init__(self, conn: sqlite3.Connection, user_id: int) -> None:
        self.conn = conn
        self.uid = int(user_id)
        self.used: dict[int, sqlite3.Row] = {}  # food id → row, for the answer's ``foods``

    def _use(self, food_id: int) -> dict[str, Any] | None:
        food = foods_module.fetch_food(self.conn, int(food_id))
        if food is None:
            return None
        ref = food_ref(food, self.uid)
        if ref is not None and food["source"] != "builtin":
            self.used[int(food["id"])] = food
        return ref

    def row(self, kind: str, row_id: int) -> dict[str, Any] | None:
        c, uid = self.conn, self.uid
        if kind == "entry":
            r = log_module.fetch_entry(c, uid, row_id)
            if r is None:
                return None
            out = log_module.entry_fields(r)
            out["food"] = self._use(r["food_id"])
            return out
        if kind == "food":
            r = c.execute("SELECT * FROM foods WHERE id = ? AND owner_user_id = ?", (row_id, uid)).fetchone()
            return None if r is None else foods_module.row_to_food(r)
        if kind == "meal":
            r = meals_module.fetch_template(c, uid, row_id)
            if r is None:
                return None
            out = meals_module.row_to_template(c, r)
            for item in out["items"]:
                item["food"] = self._use(item["food_id"])
            return out
        if kind == "lab":
            r = c.execute(f"SELECT {labs_module.COLUMNS} FROM lab_results WHERE id = ? AND user_id = ?", (row_id, uid)).fetchone()
            if r is None:
                return None
            out = {k: r[k] for k in labs_module.COLUMNS.split(", ")}
            try:
                out["unit"] = labs_module.units.analyte_def(r["analyte"]).canonical_unit
            except labs_module.units.UnitError:  # a row written by a later version, as the export keeps it
                out["unit"] = ""
            return {**{k: out[k] for k in labs_module.CSV_COLUMNS}, "client_id": r["client_id"]}
        if kind == "symptom":
            r = c.execute(f"SELECT {symptoms_module.COLUMNS} FROM symptoms WHERE id = ? AND user_id = ?", (row_id, uid)).fetchone()
            return None if r is None else {**{k: r[k] for k in symptoms_module.CSV_COLUMNS}, "client_id": r["client_id"]}
        if kind == "weight":
            r = c.execute(f"SELECT {body_module.WEIGHT_COLUMNS}, client_id FROM weights WHERE id = ? AND user_id = ?", (row_id, uid)).fetchone()
            return None if r is None else body_module.export_weight(r)
        if kind == "reading":
            r = c.execute(f"SELECT {body_module.READING_COLUMNS}, client_id FROM blood_pressures WHERE id = ? AND user_id = ?",
                          (row_id, uid)).fetchone()
            return None if r is None else body_module.export_reading(r)
        raise ValueError(kind)

    def by_client_id(self, kind: str, client_id: str) -> tuple[int, dict[str, Any]] | None:
        table, owner = TABLES[kind]
        r = self.conn.execute(f"SELECT id FROM {table} WHERE {owner} = ? AND client_id = ?", (self.uid, client_id)).fetchone()
        if r is None:
            return None
        row = self.row(kind, int(r[0]))
        return None if row is None else (int(r[0]), row)

    def foods(self) -> list[dict[str, Any]]:
        return [{"ref": food_ref(f, self.uid), "food": foods_module.row_to_food(f)} for _, f in sorted(self.used.items())]


# --------------------------------------------------------------------------- #
# GET /push/v1/changes
# --------------------------------------------------------------------------- #


def parse_cursor(after: str | None) -> int:
    if after is None or after == "":
        return 0
    if not _CURSOR_RE.match(after):
        raise ApiProblem(400, "after must be the next value of an earlier answer, or 0.", field="after")
    return int(after)


def read_page(conn: sqlite3.Connection, user_id: int, after: int, limit: int) -> dict[str, Any]:
    """One page of the feed from ``after``, read in one snapshot."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")  # one snapshot for the whole page
    try:
        purged = conn.execute("SELECT through_id FROM sync_purged WHERE user_id = ?", (int(user_id),)).fetchone()
        if after > 0 and purged is not None and after < int(purged[0]):
            raise ApiProblem(410, RESYNC, headers=dict(NO_STORE), resync=True)
        rows = conn.execute("SELECT id, kind, row_id, client_id, deleted FROM sync_changes WHERE user_id = ? AND id > ? ORDER BY id LIMIT ?",
                            (int(user_id), after, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        reader = Reader(conn, user_id)
        changes: list[dict[str, Any]] = []
        for r in rows:
            kind = r["kind"]
            if r["deleted"]:
                changes.append({"kind": kind, "id": r["client_id"], "op": "delete", "version": None})
                continue
            row = reader.row(kind, int(r["row_id"]))
            if row is None or not row.get("client_id"):  # cannot happen inside one snapshot; never send a row without its ID
                continue
            changes.append({"kind": kind, "id": row["client_id"], "op": "put", "version": row_version(kind, row), "row": row})
        top = int(rows[-1]["id"]) if rows else after
        return {"changes": changes, "foods": reader.foods(), "next": str(top), "more": more}
    finally:
        conn.rollback()


def _summary(changes: list[dict[str, Any]]) -> str:
    return f"{sum(c['op'] == 'put' for c in changes)} put, {sum(c['op'] == 'delete' for c in changes)} delete"


@router.get(CHANGES_PATH, summary="The changes since a cursor (token with app:sync)")
def read_changes(request: Request, user: api_tokens.AppSyncUser, after: str | None = None, limit: int = MAX_PAGE,
                 conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """The person's changes since ``after``: the module docstring has the whole contract."""
    token = request.state.api_token
    auth_context(request).limits.take(FEED_LIMIT, f"token:{token.id}")
    cursor = parse_cursor(after)
    if not 1 <= limit <= MAX_PAGE:
        raise ApiProblem(400, f"limit must be from 1 to {MAX_PAGE}.", field="limit")
    page = read_page(conn, user.id, cursor, limit)
    note_use(conn, user, token)
    logger.info("changes: token %d read %s, more=%s", token.id, _summary(page["changes"]), page["more"])
    return JSONResponse(page, headers=NO_STORE)


# --------------------------------------------------------------------------- #
# POST /push/v1/changes
# --------------------------------------------------------------------------- #


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["food", "entry", "meal", "lab", "symptom", "weight", "reading"]
    id: str
    op: Literal["edit", "delete"]
    base: str
    fields: dict[str, Any] | None = None
    version: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        out = validate_client_id(v)
        assert out is not None
        return out

    @field_validator("base", "version")
    @classmethod
    def _version(cls, v: str | None) -> str | None:
        if v is not None and not _VERSION_RE.match(v):
            raise ValueError("must be a version: 16 lower-case hex digits")
        return v

    @model_validator(mode="after")
    def _fields(self) -> "Change":
        if self.op == "edit" and self.fields is None:
            raise ValueError("an edit needs fields")
        if self.op == "delete" and self.fields is not None:
            raise ValueError("a delete has no fields")
        return self


class ChangesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[Change] = Field(min_length=1, max_length=MAX_CHANGES)


EDIT_MODELS: dict[str, type[BaseModel]] = {
    "entry": LogUpdate, "food": FoodCreate, "meal": MealTemplateCreate, "symptom": SymptomCreate, "weight": WeightCreate,
    "reading": BloodPressureCreate,
}


def _read_json(raw: bytes, model: type[BaseModel]) -> Any:
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ApiProblem(400, "The body is not valid JSON.") from None
    try:
        return model.model_validate(doc)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_input=False, include_context=False)
        detail, flat = flatten_validation_errors(errors[:1])
        raise ApiProblem(400, detail, field=".".join(str(p) for p in errors[0]["loc"]), errors=flat) from None


def _run(conn: sqlite3.Connection, user: User, change: Change, row_id: int) -> None:
    """The change through its route's own function, with ``If-Match: "<base>"`` (each commits its own work)."""
    if_match = f'"{change.base}"'
    kind = change.kind
    if change.op == "delete":
        delete = {"entry": log_module.delete_entry, "food": foods_module.delete_food, "meal": meals_module.delete_meal,
                  "lab": labs_module.delete_lab, "symptom": symptoms_module.delete_symptom, "weight": body_module.delete_weight,
                  "reading": body_module.delete_reading}[kind]
        delete(row_id, user=user, if_match=if_match, conn=conn)
        return
    if kind == "lab":
        raise HTTPException(status_code=400, detail="Lab results can only be added or deleted.")
    body = EDIT_MODELS[kind].model_validate(change.fields)
    update = {"entry": log_module.update_entry, "food": foods_module.update_food, "meal": meals_module.update_meal,
              "symptom": symptoms_module.update_symptom, "weight": body_module.update_weight, "reading": body_module.update_reading}[kind]
    update(row_id, body, user=user, if_match=if_match, conn=conn)


def apply_change(conn: sqlite3.Connection, user: User, change: Change) -> dict[str, Any]:
    reader = Reader(conn, user.id)
    found = reader.by_client_id(change.kind, change.id)
    if found is None:
        return {"status": "gone"}
    row_id, row = found
    now = row_version(change.kind, row)
    if change.op == "edit" and change.version == now:  # the same edit on both sides: no conflict, nothing to write (note 39 §8.6)
        return {"status": "done", "version": now}
    try:
        _run(conn, user, change, row_id)
    except ApiProblem as exc:
        _rollback(conn)
        if exc.status == 412:
            return _conflict(conn, user, change)
        return {"status": "refused", "detail": exc.detail}
    except HTTPException as exc:
        _rollback(conn)
        if exc.status_code == 404:
            return {"status": "gone"}
        return {"status": "refused", "detail": str(exc.detail)}
    except ValidationError as exc:
        _rollback(conn)
        detail, _flat = flatten_validation_errors(exc.errors(include_url=False, include_input=False, include_context=False)[:1])
        return {"status": "refused", "detail": f"fields.{detail}"}
    if change.op == "delete":
        return {"status": "done", "version": None}
    after = Reader(conn, user.id).by_client_id(change.kind, change.id)
    return {"status": "done", "version": None if after is None else row_version(change.kind, after[1])}


def _conflict(conn: sqlite3.Connection, user: User, change: Change) -> dict[str, Any]:
    found = Reader(conn, user.id).by_client_id(change.kind, change.id)
    if found is None:
        return {"status": "gone"}
    row = found[1]
    return {"status": "conflict", "version": row_version(change.kind, row), "row": row}


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.rollback()


def write_changes(conn: sqlite3.Connection, user: User, body: ChangesBody, request: Request) -> list[dict[str, Any]]:
    begin_immediate(conn)  # the token is checked again under the write lock before anything changes
    try:
        api_tokens.require_current_write(request, conn, api_tokens.APP_SYNC)
    finally:
        _rollback(conn)
    person = replace(user, role="user")
    out = []
    for change in body.changes:
        result = apply_change(conn, person, change)
        out.append({"kind": change.kind, "id": change.id, **result})
    return out


@router.post(CHANGES_PATH, summary="Send edits and deletes made on the iPhone (token with app:sync)")
async def post_changes(request: Request, user: api_tokens.AppSyncUser, conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """Each change through its route's ``PUT`` or ``DELETE`` with ``If-Match``; the module docstring has the whole contract."""
    token = request.state.api_token
    auth_context(request).limits.take(WRITE_LIMIT, f"token:{token.id}")
    if not _is_json_type(request):
        raise ApiProblem(415, "Send the body as JSON with the header Content-Type: application/json.")
    raw = await read_capped(request, MAX_BODY_BYTES)
    body = _read_json(raw, ChangesBody)
    results = await run_in_threadpool(write_changes, conn, user, body, request)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    logger.info("changes: token %d sent %d: %s", token.id, len(results), ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return JSONResponse({"results": results}, headers=NO_STORE)


# --------------------------------------------------------------------------- #
# POST /push/v1/match
# --------------------------------------------------------------------------- #


class MatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: dict[Literal["food", "entry", "meal", "lab", "symptom", "weight", "reading"], list[str]]

    @field_validator("ids")
    @classmethod
    def _ids(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if sum(len(x) for x in v.values()) > MAX_MATCH_IDS:
            raise ValueError(f"send at most {MAX_MATCH_IDS} ids in all")
        out = {}
        for kind, ids in v.items():
            checked = []
            for i, value in enumerate(ids):
                try:
                    cid = validate_client_id(value)
                except ValueError as exc:
                    raise ValueError(f"{kind}.{i}: {exc}") from None
                checked.append(cid)
            out[kind] = checked
        return out


def match_ids(conn: sqlite3.Connection, user_id: int, ids: dict[str, list[str]]) -> dict[str, Any]:
    uid = int(user_id)
    known: dict[str, dict[str, str]] = {}
    unknown: dict[str, list[str]] = {}
    receipts = table_exists(conn, "app_sync_rows")
    for kind, wanted in ids.items():
        table, owner = TABLES[kind]
        k_known: dict[str, str] = {}
        k_unknown: list[str] = []
        for cid in dict.fromkeys(wanted):
            if conn.execute(f"SELECT 1 FROM {table} WHERE {owner} = ? AND client_id = ?", (uid, cid)).fetchone():
                k_known[cid] = cid
                continue
            server = None
            if receipts and kind in RECEIPT_KINDS:
                r = conn.execute(
                    f"""SELECT t.client_id FROM app_sync_rows s JOIN {table} t ON t.id = s.row_id AND t.{owner} = s.user_id
                        WHERE s.user_id = ? AND s.kind = ? AND s.client_id = ?""", (uid, kind, cid)).fetchone()
                server = None if r is None else r[0]
            if server:
                k_known[cid] = server
            else:
                k_unknown.append(cid)
        known[kind] = k_known
        unknown[kind] = k_unknown
    return {"known": known, "unknown": unknown}


@router.post(MATCH_PATH, summary="This server's ID for each of the phone's rows (token with app:sync)")
async def post_match(request: Request, user: api_tokens.AppSyncUser, conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """``{"known": {kind: {phone id: server id}}, "unknown": {kind: [ids]}}``; the module docstring has the whole contract."""
    token = request.state.api_token
    auth_context(request).limits.take(WRITE_LIMIT, f"token:{token.id}")
    if not _is_json_type(request):
        raise ApiProblem(415, "Send the body as JSON with the header Content-Type: application/json.")
    raw = await read_capped(request, MAX_BODY_BYTES)
    body = _read_json(raw, MatchBody)
    answer = await run_in_threadpool(match_ids, conn, user.id, body.ids)
    logger.info("match: token %d asked %d, knew %d", token.id, sum(len(v) for v in body.ids.values()),
                sum(len(v) for v in answer["known"].values()))
    return JSONResponse(answer, headers=NO_STORE)


def changes_other() -> JSONResponse:
    return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "GET, POST", **NO_STORE})


def match_other() -> JSONResponse:
    return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "POST", **NO_STORE})


for _method in ("DELETE", "PUT", "PATCH"):  # one route each, so every OpenAPI operation id is unique
    router.add_api_route(CHANGES_PATH, changes_other, methods=[_method], operation_id=f"push_changes_{_method.lower()}_not_allowed",
                         summary="Not offered: GET and POST only (405)")
for _method in ("GET", "DELETE", "PUT", "PATCH"):
    router.add_api_route(MATCH_PATH, match_other, methods=[_method], operation_id=f"push_match_{_method.lower()}_not_allowed",
                         summary="Not offered: POST only (405)")


# --------------------------------------------------------------------------- #
# Tombstones: kept 180 days
# --------------------------------------------------------------------------- #


def purge_tombstones(conn: sqlite3.Connection) -> int:
    """Delete tombstones older than :data:`TOMBSTONE_DAYS`, remembering per person the highest id removed (a cursor below it is
    ``410``). Commits. Returns how many were removed."""
    if not table_exists(conn, "sync_changes"):
        return 0
    cutoff = clock.iso(clock.now() - timedelta(days=TOMBSTONE_DAYS))
    rows = conn.execute("SELECT user_id, MAX(id) FROM sync_changes WHERE deleted = 1 AND at < ? GROUP BY user_id", (cutoff,)).fetchall()
    removed = 0
    for user_id, top in rows:
        conn.execute("""INSERT INTO sync_purged (user_id, through_id) SELECT ?, ? WHERE EXISTS (SELECT 1 FROM users WHERE id = ?)
                        ON CONFLICT(user_id) DO UPDATE SET through_id = MAX(through_id, excluded.through_id)""",
                     (int(user_id), int(top), int(user_id)))
        removed += conn.execute("DELETE FROM sync_changes WHERE user_id = ? AND deleted = 1 AND id <= ? AND at < ?",
                                (int(user_id), int(top), cutoff)).rowcount or 0
    conn.commit()
    return removed


housekeeping.register_daily("sync_tombstones", lambda conn, ctx: purge_tombstones(conn))
