"""``/api/instacart``: open the Plan's shopping list at Instacart (design note 33).

Off unless the setting ``lists.instacart_enabled`` (``INSTACART_ENABLED``) is on **and** the server owner's key is set
(``INSTACART_API_KEY_FILE``). While either is missing, ``GET /api/instacart`` answers ``enabled: false`` and the other routes are
``404``. Every route needs a signed-in person and reads only that person's own planned foods.

* ``GET``: whether it is on, and the most foods a send takes.
* ``POST /preview``: the exact lines a send would make, for a range of the Plan.
* ``POST /send``: the server asks Instacart for a shopping list page with the chosen foods of that range and answers its link.
  The browser opens the link; it never calls Instacart's API itself.

What leaves the server, and only on Send: the title "Shopping list" and, for each chosen food, its name, the line the person saw
("Rice, white, cooked: 3 servings of 1/2 cup (79 g)") and its weight in grams when the app knows it. Nothing about the person:
no name, id, targets, dates or address of this server. Nothing is stored about the list or the link; the activity list gets one
row with the number of lines.

The request goes through :class:`app.egress.CheckedTransport` with private addresses refused, never follows a redirect, reads at
most 64 KiB, and has 15 seconds a request and 20 seconds in all (:func:`app.egress.run_with_deadline`). The key is used only in
the ``Authorization`` header, registered with the log redaction, and never logged or returned. Log lines carry only an error code.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import brand, egress
from .audit import audit
from .auth.context import auth_context, request_ip
from .auth.deps import CurrentUser
from .auth.errors import ApiProblem
from .auth.ratelimit import register_limit
from .db import get_db
from .list_sync.api import list_item
from .log import parse_range
from .meals import shopping_items
from .security import register_secret

log = logging.getLogger(f"{brand.LOGGER_NAME}.instacart")

router = APIRouter(prefix="/api/instacart", tags=["instacart"])

SWITCH = "lists.instacart_enabled"
PATH = "/idp/v1/products/products_link"
TITLE = "Shopping list"  # plain on purpose: the brand name would tell Instacart something about the person's health
EXPIRES_DAYS = 7
MAX_ITEMS = 200
NAME_MAX = 200
TEXT_MAX = 300
MAX_LINK_CHARS = 2048
MAX_RESPONSE_BYTES = 64 * 1024
HTTP_TIMEOUT_S = 15.0
DEADLINE_S = 20.0
SENDS_PER_HOUR = 10
LINK_DOMAINS = ("instacart.com", "instacart.tools")
register_limit("instacart_send", SENDS_PER_HOUR, 3600, "You have opened the list at Instacart several times this hour. Try again later.")

ERROR_CODES = ("unreachable", "blocked", "auth", "rejected", "busy", "bad_answer", "timeout")
ERROR_TEXT = {
    "unreachable": "Instacart did not answer. Try again later.",
    "blocked": "This server could not reach Instacart. Ask the person who runs it to check its network.",
    "auth": "Instacart did not accept this server's key. Ask the person who runs the server to check it.",
    "rejected": "Instacart did not accept the list. Try again with fewer foods, or later.",
    "busy": "Instacart is busy. Try again in a few minutes.",
    "bad_answer": "Instacart gave an answer the app could not use. Try again later.",
    "timeout": "Instacart took too long to answer. Try again later.",
}


class InstacartError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code if code in ERROR_CODES else "bad_answer"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class StatusOut(BaseModel):
    enabled: bool
    max_items: int


class RangeIn(BaseModel):
    start: str
    end: str


class SendIn(RangeIn):
    food_ids: list[int] = Field(min_length=1, max_length=MAX_ITEMS)


class LineOut(BaseModel):
    food_id: int
    name: str
    amount: str
    text: str


class PreviewOut(BaseModel):
    title: str
    items: list[LineOut]


class SendOut(BaseModel):
    url: str | None
    items: int
    error: str | None
    message: str | None


# --------------------------------------------------------------------------- #
# The lines and the request body
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Line:
    food_id: int
    name: str
    amount: str
    text: str
    grams: float | None


def _plain(text: str, limit: int) -> str:
    """One line of plain text: control characters and runs of spaces become one space."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())[:limit]


def line_of(row: dict[str, Any]) -> Line:
    """A shopping list row as a line: the same words as Share list and the list sync (``app.list_sync.api.list_item``)."""
    item = list_item(row)
    grams = row.get("grams")
    name = _plain(item.name, NAME_MAX)
    return Line(food_id=item.food_id, name=name, amount=item.amount, text=_plain(f"{name}: {item.amount}", TEXT_MAX),
                grams=float(grams) if isinstance(grams, (int, float)) and grams >= 1 else None)


def request_body(lines: list[Line]) -> dict[str, Any]:
    """The body of ``POST /idp/v1/products/products_link``: the title and the foods, nothing about the person."""
    items: list[dict[str, Any]] = []
    for line in lines:
        item: dict[str, Any] = {"name": line.name, "display_text": line.text}
        if line.grams is not None:
            item["line_item_measurements"] = [{"quantity": round(line.grams), "unit": "g"}]
        items.append(item)
    return {"title": TITLE, "link_type": "shopping_list", "expires_in": EXPIRES_DAYS, "line_items": items}


def check_link(value: Any) -> str:
    """The link Instacart answered, or :class:`InstacartError` ``bad_answer``: ``https://`` on one of Instacart's domains."""
    if not isinstance(value, str) or not value or len(value) > MAX_LINK_CHARS or any(ch.isspace() or not ch.isprintable() for ch in value):
        raise InstacartError("bad_answer")
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError:
        raise InstacartError("bad_answer") from None
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        raise InstacartError("bad_answer")
    if not any(host == d or host.endswith("." + d) for d in LINK_DOMAINS):
        raise InstacartError("bad_answer")
    return value


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


class InstacartClient:
    """``app.state.instacart``. ``resolver``, ``direct`` and ``use_env_proxy`` exist for tests (a fake Instacart behind the real
    checked transport)."""

    def __init__(self, base_url: str, *, resolver: Callable[[str, int], list[str]] | None = None,
                 direct: httpx2.BaseTransport | None = None, use_env_proxy: bool = True, deadline_s: float = DEADLINE_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.resolver = resolver
        self.direct = direct
        self.use_env_proxy = use_env_proxy
        self.deadline_s = deadline_s

    def _client(self) -> httpx2.Client:
        transport = egress.CheckedTransport(allow_private=False, resolver=self.resolver, use_env_proxy=self.use_env_proxy,
                                            direct=self.direct)
        return httpx2.Client(transport=transport, timeout=HTTP_TIMEOUT_S, follow_redirects=False, trust_env=False,
                             headers={"User-Agent": brand.USER_AGENT_INSTACART, "Accept": "application/json"})

    def create_link(self, key: str, lines: list[Line]) -> str:
        """The link of a new shopping list page. Raises :class:`InstacartError`; the whole call has ``deadline_s`` seconds."""
        body = request_body(lines)
        try:
            return egress.run_with_deadline("instacart", lambda: self._post(key, body), self.deadline_s)
        except egress.DeadlineExceeded:
            log.warning("instacart: the call took too long")
            raise InstacartError("timeout") from None

    def _post(self, key: str, body: dict[str, Any]) -> str:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            with self._client() as client, client.stream("POST", self.base_url + PATH, json=body, headers=headers) as response:
                status = response.status_code
                raw = egress.read_capped(response, MAX_RESPONSE_BYTES) if 200 <= status < 300 else b""
        except egress.BlockedAddress:
            log.warning("instacart: the server refused the address Instacart's host resolves to")
            raise InstacartError("blocked") from None
        except egress.ResponseTooLarge:
            log.warning("instacart: the answer was too large")
            raise InstacartError("bad_answer") from None
        except httpx2.TimeoutException:
            log.warning("instacart: no answer in time")
            raise InstacartError("timeout") from None
        except httpx2.HTTPError:
            log.warning("instacart: no answer")
            raise InstacartError("unreachable") from None
        code = _status_code(status)
        if code is not None:
            log.warning("instacart: the answer was %s (HTTP %d)", code, status)
            raise InstacartError(code)
        try:
            data = json.loads(raw)
        except ValueError:
            raise InstacartError("bad_answer") from None
        return check_link(data.get("products_link_url") if isinstance(data, dict) else None)


def _status_code(status: int) -> str | None:
    if 200 <= status < 300:
        return None
    if status in (401, 403):
        return "auth"
    if status == 429 or status >= 500:
        return "busy"
    if status in (400, 404, 409, 413, 422):
        return "rejected"
    return "bad_answer"  # a redirect (never followed) or anything else


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _key(request: Request) -> str | None:
    key = request.app.state.settings.instacart.api_key
    if key:
        register_secret(key)
    return key or None


def enabled(request: Request, conn: sqlite3.Connection) -> bool:
    return bool(_key(request)) and bool(auth_context(request).store.get(conn, SWITCH))


def _require_on(request: Request, conn: sqlite3.Connection) -> None:
    if not enabled(request, conn):
        raise HTTPException(status_code=404, detail="Not Found")


def client_of(request: Request) -> InstacartClient:
    client = getattr(request.app.state, "instacart", None)
    if client is None:
        client = request.app.state.instacart = InstacartClient(request.app.state.settings.instacart.base_url)
    return client


def _lines(conn: sqlite3.Connection, user_id: int, body: RangeIn) -> list[Line]:
    start_s, end_s = parse_range(body.start, body.end)
    return [line_of(row) for row in shopping_items(conn, user_id, start_s, end_s)]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("", response_model=StatusOut)
def get_instacart(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"enabled": enabled(request, conn), "max_items": MAX_ITEMS}  # answer, not 404: Plan asks on every open


@router.post("/preview", response_model=PreviewOut)
def preview(body: RangeIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    lines = _lines(conn, user.id, body)
    return {"title": TITLE, "items": [{"food_id": x.food_id, "name": x.name, "amount": x.amount, "text": x.text} for x in lines]}


@router.post("/send", response_model=SendOut)
def send(body: SendIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    wanted = set(body.food_ids)
    lines = [x for x in _lines(conn, user.id, body) if x.food_id in wanted]
    if not lines:
        raise ApiProblem(400, "None of those foods are on this list. Open the list again and choose what to send.")
    auth_context(request).limits.take("instacart_send", user.id)
    if conn.in_transaction:
        conn.commit()
    key = _key(request)
    if key is None:  # pragma: no cover - _require_on checked it
        raise HTTPException(status_code=404, detail="Not Found")
    url: str | None = None
    code: str | None = None
    try:
        url = client_of(request).create_link(key, lines)
    except InstacartError as exc:
        code = exc.code
    if code != "blocked":  # the list may have reached Instacart
        audit(conn, user.id, "instacart.sent", "instacart", None, ip=request_ip(request), items=len(lines))
        conn.commit()
    return {"url": url, "items": len(lines) if url else 0, "error": code, "message": ERROR_TEXT.get(code) if code else None}
