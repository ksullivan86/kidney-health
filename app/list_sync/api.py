"""``/api/list-sync``: send the shopping list to the person's own Grocy, KitchenOwl or Mealie (design note 30 §2, §5).

Every route needs a signed-in person and only reaches that person's own row (there is no id to guess). While
``lists.sync_enabled`` is off, ``GET /api/list-sync`` answers ``enabled: false`` and every other route is ``404``.

* ``GET``: the apps, and the person's list app: address, chosen list, whether a key is set, the last test and send. Never the key.
* ``PUT``: the app, the address and the key (write-only). The key may be left out only while the app and the address stay the
  same, so a stored key is never sent to an address it was not typed for. Test accounts get ``403``.
* ``DELETE``: forget the address and the key.
* ``POST /test``: check the address and key; answers the person's lists.
* ``POST /preview``: the exact lines a send would add, for a range of the Plan.
* ``POST /send``: add the chosen foods of that range's list to the chosen list in the app.

The key is sealed with the app's keyring (purpose ``list-sync``, owner the person's id), registered with the log redaction
whenever it is read, and never logged, returned or written to the activity list.
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..audit import audit
from ..auth.context import auth_context, request_ip
from ..auth.deps import CurrentUser
from ..auth.errors import ApiProblem
from ..auth.ratelimit import register_limit
from ..crypto import InvalidToken, Keyring
from ..db import get_db, utcnow
from ..log import parse_range
from ..meals import shopping_items
from ..security import register_secret
from .apps import APPS, HostAllowlist, Item, ListAppError, Net, check_base_url, client_for, valid_list_id

router = APIRouter(prefix="/api/list-sync", tags=["list sync"])

SWITCH = "lists.sync_enabled"
PURPOSE = "list-sync"
MAX_ITEMS = 200
MAX_KEY_CHARS = 4096
SENDS_PER_HOUR = 6
TESTS_PER_HOUR = 30
register_limit("list_send", SENDS_PER_HOUR, 3600, "You have sent the list several times this hour. Try again later.")
register_limit("list_test", TESTS_PER_HOUR, 3600, "Too many tests this hour. Try again later.")

TEST_ACCOUNT_REFUSAL = "Test accounts cannot send the list to a list app. Sign in with your own account to set yours up."
KEY_AGAIN = "Enter the key again: it is needed for a new address or a different app."
NO_LIST = "Choose a list first: press Test in Settings → Shopping list app."
ERROR_TEXT = {
    "unreachable": "The list app did not answer. Check the address, and that this server can reach it.",
    "blocked": "This server does not connect to that address. A home address works only when your admin allows it.",
    "redirect": "The list app sent the app on to another address. Enter the address it sends you to.",
    "auth": "The list app did not accept the key. Check it, or make a new one.",
    "not_found": "The list app has no such page. Check the address, and that it is the right app.",
    "app_error": "The list app gave an answer the app could not read.",
    "no_key": "The key can no longer be read on this server. Enter it again.",
}


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

AppId = Literal["grocy", "kitchenowl", "mealie"]


class AppOut(BaseModel):
    id: str
    name: str
    key_name: str
    key_help: str


class ConnectionOut(BaseModel):
    app: str
    base_url: str
    list_id: str | None
    list_name: str | None
    key_set: bool
    last_test_at: str | None
    last_test_error: str | None
    last_sent_at: str | None
    last_sent_count: int | None


class ListSyncOut(BaseModel):
    enabled: bool
    can_use: bool  # false for a test account
    private_hosts: bool  # the admin allowed home addresses (LIST_SYNC_ALLOWED_HOSTS)
    apps: list[AppOut]
    connection: ConnectionOut | None


class ListSyncIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    app: AppId
    base_url: str = Field(min_length=1, max_length=500)
    key: str | None = Field(default=None, min_length=1, max_length=MAX_KEY_CHARS)
    list_id: str | None = Field(default=None, max_length=64)
    list_name: str | None = Field(default=None, max_length=200)


class ListRefOut(BaseModel):
    id: str
    name: str


class TestOut(BaseModel):
    ok: bool
    error: str | None
    message: str | None
    lists: list[ListRefOut]
    connection: ConnectionOut


class RangeIn(BaseModel):
    start: str
    end: str


class SendIn(RangeIn):
    food_ids: list[int] = Field(min_length=1, max_length=MAX_ITEMS)


class PreviewItem(BaseModel):
    food_id: int
    name: str
    amount: str
    text: str


class PreviewOut(BaseModel):
    app: str
    app_name: str
    list_name: str | None
    ready: bool  # a list is chosen
    items: list[PreviewItem]
    last_sent_at: str | None
    last_sent_count: int | None


class SendOut(BaseModel):
    sent: int
    error: str | None
    message: str | None
    connection: ConnectionOut


# --------------------------------------------------------------------------- #
# The list text (the same words as Plan's "Share list")
# --------------------------------------------------------------------------- #


def servings_words(servings: float) -> str:
    """``fmtServings`` of ``js/engine/rules.js``: "3 servings", "1 serving", "1.25 servings", "1,200 servings"."""
    rounded = math.floor(float(servings) * 100 + 0.5) / 100
    text = f"{rounded:,.2f}".rstrip("0").rstrip(".")
    return f"{text} {'serving' if rounded == 1 else 'servings'}"


def list_item(row: dict[str, Any]) -> Item:
    amount = servings_words(row["servings"]) + (f" of {row['serving_desc']}" if row.get("serving_desc") else "")
    return Item(food_id=int(row["food_id"]), name=row["food_name"], amount=amount, text=f"{row['food_name']}: {amount}")


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #


def row_of(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM list_sync WHERE user_id = ?", (int(user_id),)).fetchone()


def view(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"app": row["app"], "base_url": row["base_url"], "list_id": row["list_id"], "list_name": row["list_name"],
            "key_set": row["key_enc"] is not None, "last_test_at": row["last_test_at"], "last_test_error": row["last_test_error"],
            "last_sent_at": row["last_sent_at"], "last_sent_count": row["last_sent_count"]}


def load_key(keyring: Keyring, row: sqlite3.Row) -> str | None:
    if row["key_enc"] is None:
        return None
    try:
        fields = keyring.unseal(row["key_enc"], purpose=PURPOSE, owner=int(row["user_id"]))
    except InvalidToken:
        return None
    key = fields.get("key")
    register_secret(key)
    return key or None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def enabled(request: Request, conn: sqlite3.Connection) -> bool:
    return bool(auth_context(request).store.get(conn, SWITCH))


def _require_on(request: Request, conn: sqlite3.Connection) -> None:
    if not enabled(request, conn):
        raise HTTPException(status_code=404, detail="Not Found")


def allowlist_of(request: Request) -> HostAllowlist:
    return HostAllowlist.parse(request.app.state.settings.list_sync_allowed_hosts)


def net_of(request: Request) -> Net:
    net = getattr(request.app.state, "list_sync_net", None)
    if net is None:
        net = request.app.state.list_sync_net = Net(allowlist_of(request))
    return net


def _require_row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = row_of(conn, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return row


def _items(conn: sqlite3.Connection, user_id: int, body: RangeIn) -> list[Item]:
    start_s, end_s = parse_range(body.start, body.end)
    return [list_item(row) for row in shopping_items(conn, user_id, start_s, end_s)]


def _client(request: Request, row: sqlite3.Row) -> Any:
    key = load_key(auth_context(request).require_keyring(), row)
    if key is None:
        return None
    return client_for(net_of(request), row["app"], row["base_url"], key)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("", response_model=ListSyncOut)
def get_list_sync(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    if not enabled(request, conn):  # answer, not 404: Settings and Plan ask on every open
        return {"enabled": False, "can_use": False, "private_hosts": False, "apps": [], "connection": None}
    return {"enabled": True, "can_use": not user.is_test_account, "private_hosts": not allowlist_of(request).empty,
            "apps": [{"id": k, **v} for k, v in APPS.items()], "connection": view(row_of(conn, user.id))}


@router.put("", response_model=ConnectionOut)
def put_list_sync(body: ListSyncIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    if user.is_test_account:
        raise ApiProblem(403, TEST_ACCOUNT_REFUSAL)
    try:
        base_url = check_base_url(body.base_url, allowlist_of(request))
    except ValueError as exc:
        raise ApiProblem(400, str(exc)) from None
    row = row_of(conn, user.id)
    same_place = row is not None and row["app"] == body.app and row["base_url"] == base_url
    if body.key is None and not (same_place and row is not None and row["key_enc"] is not None):
        raise ApiProblem(400, KEY_AGAIN)
    list_id = body.list_id or None
    if list_id is not None and not valid_list_id(body.app, list_id):
        raise ApiProblem(400, "That list cannot be used. Press Test and choose one of your lists.")
    if list_id is None and same_place and "list_id" not in body.model_fields_set and row is not None:
        list_id, list_name = row["list_id"], row["list_name"]
    else:
        list_name = (body.list_name or None) if list_id else None
    now = utcnow()
    if body.key is not None:
        sealed, key_id = auth_context(request).require_keyring().seal(purpose=PURPOSE, owner=int(user.id), fields={"key": body.key})
    else:
        sealed, key_id = row["key_enc"], row["key_id"]  # type: ignore[index]
    if row is None:
        conn.execute("INSERT INTO list_sync (user_id, app, base_url, list_id, list_name, key_enc, key_id, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (user.id, body.app, base_url, list_id, list_name, sealed, key_id, now, now))
    else:
        keep_test = same_place and body.key is None
        conn.execute("UPDATE list_sync SET app = ?, base_url = ?, list_id = ?, list_name = ?, key_enc = ?, key_id = ?, "
                     "last_test_at = ?, last_test_error = ?, updated_at = ? WHERE user_id = ?",
                     (body.app, base_url, list_id, list_name, sealed, key_id, row["last_test_at"] if keep_test else None,
                      row["last_test_error"] if keep_test else None, now, user.id))
    if row is None or not same_place or body.key is not None:
        audit(conn, user.id, "list_sync.set_up", "list_sync", body.app, ip=request_ip(request), app=body.app)
    conn.commit()
    return view(row_of(conn, user.id))  # type: ignore[return-value]


@router.delete("", status_code=204, response_class=Response)
def delete_list_sync(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _require_on(request, conn)
    row = _require_row(conn, user.id)
    conn.execute("DELETE FROM list_sync WHERE user_id = ?", (user.id,))
    audit(conn, user.id, "list_sync.removed", "list_sync", row["app"], ip=request_ip(request), app=row["app"])
    conn.commit()
    return Response(status_code=204)


@router.post("/test", response_model=TestOut)
def test_list_sync(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    row = _require_row(conn, user.id)
    auth_context(request).limits.take("list_test", user.id)
    if conn.in_transaction:
        conn.commit()
    client = _client(request, row)
    lists: list[dict[str, str]] = []
    code: str | None = None
    if client is None:
        code = "no_key"
    else:
        try:
            lists = [{"id": x.id, "name": x.name} for x in client.test()]
        except ListAppError as exc:
            code = exc.code
    list_id, list_name = row["list_id"], row["list_name"]
    if code is None:
        chosen = next((x for x in lists if x["id"] == list_id), None)
        if chosen is not None:
            list_name = chosen["name"]
        elif len(lists) == 1:
            list_id, list_name = lists[0]["id"], lists[0]["name"]
    conn.execute("UPDATE list_sync SET last_test_at = ?, last_test_error = ?, list_id = ?, list_name = ? WHERE user_id = ?",
                 (utcnow(), code, list_id, list_name, user.id))
    conn.commit()
    return {"ok": code is None, "error": code, "message": ERROR_TEXT.get(code) if code else None, "lists": lists,
            "connection": view(row_of(conn, user.id))}


@router.post("/preview", response_model=PreviewOut)
def preview(body: RangeIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    row = _require_row(conn, user.id)
    items = _items(conn, user.id, body)
    return {"app": row["app"], "app_name": APPS[row["app"]]["name"] if row["app"] in APPS else row["app"],
            "list_name": row["list_name"], "ready": bool(row["list_id"]),
            "items": [vars(i) for i in items], "last_sent_at": row["last_sent_at"], "last_sent_count": row["last_sent_count"]}


@router.post("/send", response_model=SendOut)
def send(body: SendIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    row = _require_row(conn, user.id)
    if not row["list_id"]:
        raise ApiProblem(409, NO_LIST)
    if row["app"] not in APPS:
        raise HTTPException(status_code=404, detail="Not Found")
    wanted = set(body.food_ids)
    items = [i for i in _items(conn, user.id, body) if i.food_id in wanted]
    if not items:
        raise ApiProblem(400, "None of those foods are on this list. Open the list again and choose what to send.")
    auth_context(request).limits.take("list_send", user.id)
    if conn.in_transaction:
        conn.commit()
    client = _client(request, row)
    sent = 0
    code: str | None = None
    if client is None:
        code = "no_key"
    else:
        try:
            sent = client.send(str(row["list_id"]), items)
        except ListAppError as exc:
            code, sent = exc.code, exc.sent
    if sent:
        conn.execute("UPDATE list_sync SET last_sent_at = ?, last_sent_count = ? WHERE user_id = ?", (utcnow(), sent, user.id))
        audit(conn, user.id, "list_sync.sent", "list_sync", row["app"], ip=request_ip(request), app=row["app"], items=sent)
    conn.commit()
    return {"sent": sent, "error": code, "message": ERROR_TEXT.get(code) if code else None, "connection": view(row_of(conn, user.id))}
