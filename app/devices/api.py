"""``/api/devices``: Settings → Connected devices (design note 27 §4).

Every route needs a signed-in person and only ever reaches that person's own connection (there is no id to guess: the provider
name and the session decide). Every route is ``404`` while ``devices.enabled`` is off, and a provider the server has not set up
is ``404`` too.

* ``GET /api/devices``: the providers, whether each is set up, and the person's connection to each (never a token, never the
  company's id for the person).
* ``POST /api/devices/{provider}/start`` → ``{url}``: where to send the browser. The state is 32 random bytes, kept in memory
  for 10 minutes, single use, tied to the person and the SHA-256 of their session; at most 5 wait per person. A test account
  gets ``403``; a working connection ``409``.
* ``GET /api/devices/{provider}/callback``: the way back from the company. Always a ``303`` to ``/#/devices/<word>/<provider>``:
  ``connected``, ``cancelled``, ``expired`` (no such state, or used), ``wrong_account`` (another person or another session),
  ``scope`` (the person did not allow the measures), ``taken`` (that company account is connected to someone else here),
  ``test_account``, ``unavailable`` (the company did not answer) or ``failed``. The code is used only after every check passed.
* ``POST /api/devices/{provider}/sync``: Sync now, at most once every 10 minutes (``429`` with ``Retry-After``); ``409`` while
  the connection needs a new sign-in or a sync of it is already running. ``200`` with the connection and the counts, or with
  ``error`` (the short code also kept on the connection).
* ``DELETE /api/devices/{provider}?delete_readings=true``: disconnect. The tokens are deleted here; the server also asks the
  company to end its access (best effort). Readings stay unless ``delete_readings``.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .. import brand
from ..audit import audit
from ..auth import clock
from ..auth.context import auth_context, request_ip
from ..auth.deps import CurrentUser
from ..auth.errors import ApiProblem, too_many
from ..db import get_db
from . import store
from .base import ProviderError
from .sync import SYNC_NOW_MIN_S, Devices, seconds_since, sync_connection

log = logging.getLogger(f"{brand.LOGGER_NAME}.devices")

router = APIRouter(prefix="/api/devices", tags=["devices"])

SWITCH = "devices.enabled"
FLOW_TTL_S = 600
FLOWS_PER_PERSON = 5
MAX_FLOWS = 1000
CALLBACK = "/api/devices/{provider}/callback"
RESULTS = ("connected", "cancelled", "expired", "wrong_account", "scope", "taken", "test_account", "unavailable", "failed")
TEST_ACCOUNT_REFUSAL = "Test accounts cannot connect a device. Sign in with your own account to connect yours."
ProviderId = Literal["withings"]


# --------------------------------------------------------------------------- #
# Flows waiting at the provider (in memory, like the sign-in provider's)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Flow:
    user_id: int
    session_hash: bytes
    provider: str
    started: float


class FlowStore:
    def __init__(self) -> None:
        self._flows: dict[bytes, Flow] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(state: str) -> bytes:
        return hashlib.sha256(state.encode("utf-8")).digest()

    def _prune(self, now: float) -> None:
        for key in [k for k, f in self._flows.items() if now - f.started > FLOW_TTL_S]:
            del self._flows[key]

    def start(self, user_id: int, session_hash: bytes, provider: str) -> str | None:
        """A new state, or None when this person (or everyone) has too many waiting."""
        now = clock.seconds()
        with self._lock:
            self._prune(now)
            mine = [k for k, f in self._flows.items() if f.user_id == user_id]
            if len(mine) >= FLOWS_PER_PERSON or len(self._flows) >= MAX_FLOWS:
                return None
            state = secrets.token_urlsafe(32)
            self._flows[self._key(state)] = Flow(user_id, session_hash, provider, now)
            return state

    def take(self, state: str) -> Flow | None:
        """The flow of ``state``, once: it is gone after this, whatever the outcome."""
        if not state or len(state) > 200:
            return None
        now = clock.seconds()
        with self._lock:
            self._prune(now)
            return self._flows.pop(self._key(state), None)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class ImportedCounts(BaseModel):
    weights: int
    readings: int


class ConnectionOut(BaseModel):
    status: str  # active | needs_reconnect
    connected_at: str
    last_sync_at: str | None
    last_success_at: str | None
    last_error: str | None  # auth | rate_limited | unreachable | provider_error
    imported: ImportedCounts


class ProviderOut(BaseModel):
    id: str
    name: str
    what: list[str]
    available: bool  # the server owner has set this provider up
    connection: ConnectionOut | None


class DevicesOut(BaseModel):
    enabled: bool
    can_connect: bool  # false for a test account
    sync_hours: int
    providers: list[ProviderOut]


class StartOut(BaseModel):
    url: str


class SyncCounts(BaseModel):
    added: ImportedCounts
    already_there: int
    skipped: int
    left_out: int


class SyncOut(BaseModel):
    connection: ConnectionOut
    result: SyncCounts | None
    error: str | None


class DisconnectOut(BaseModel):
    removed: ImportedCounts
    revoked: bool


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def devices_of(request: Request) -> Devices:
    return request.app.state.devices


def enabled(request: Request, conn: sqlite3.Connection) -> bool:
    return bool(auth_context(request).store.get(conn, SWITCH))


def _require_on(request: Request, conn: sqlite3.Connection) -> None:
    if not enabled(request, conn):
        raise HTTPException(status_code=404, detail="Not Found")


def _provider(request: Request, provider_id: str) -> Any:
    provider = devices_of(request).provider(provider_id)
    if provider is None or not provider.available:
        raise HTTPException(status_code=404, detail="Not Found")
    return provider


def _session_hash(request: Request) -> bytes:
    info = getattr(request.state, "auth_session", None)
    return hashlib.sha256(info.id.encode("utf-8")).digest() if info is not None else b""


def _flows(request: Request) -> FlowStore:
    flows = getattr(request.app.state, "device_flows", None)
    if flows is None:
        flows = request.app.state.device_flows = FlowStore()
    return flows


def redirect_uri(request: Request, provider_id: str) -> str:
    origin = request.app.state.settings.public_origin or ""
    return origin.rstrip("/") + CALLBACK.format(provider=provider_id)


def _back(word: str, provider_id: str) -> RedirectResponse:
    response = RedirectResponse(f"/#/devices/{word if word in RESULTS else 'failed'}/{provider_id}", status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _connection_out(conn: sqlite3.Connection, user_id: int, provider_id: str) -> dict[str, Any] | None:
    return store.view(conn, store.connection(conn, user_id, provider_id))


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("", response_model=DevicesOut)
def list_devices(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    devices = devices_of(request)
    providers = [{"id": p.id, "name": p.name, "what": list(p.what), "available": bool(p.available),
                  "connection": _connection_out(conn, user.id, p.id)} for p in devices.providers.values()]
    return {"enabled": True, "can_connect": not user.is_test_account,
            "sync_hours": int(auth_context(request).store.get(conn, "devices.sync_hours")), "providers": providers}


@router.post("/{provider_id}/start", response_model=StartOut)
def start(request: Request, user: CurrentUser, provider_id: ProviderId = Path(), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    provider = _provider(request, provider_id)
    if user.is_test_account:
        raise ApiProblem(403, TEST_ACCOUNT_REFUSAL)
    row = store.connection(conn, user.id, provider_id)
    if row is not None and row["status"] == store.STATUS_ACTIVE:
        raise ApiProblem(409, f"{provider.name} is already connected. Disconnect it first to connect another account.")
    state = _flows(request).start(user.id, _session_hash(request), provider_id)
    if state is None:
        raise too_many(FLOW_TTL_S, "Too many connections were started. Wait a few minutes, then try again.")
    return {"url": provider.authorize_url(state=state, redirect_uri=redirect_uri(request, provider_id))}


@router.get("/{provider_id}/callback", response_class=RedirectResponse, status_code=303)
def callback(request: Request, user: CurrentUser, provider_id: ProviderId = Path(), code: str = Query("", max_length=512),
             state: str = Query("", max_length=200), error: str = Query("", max_length=200),
             conn: sqlite3.Connection = Depends(get_db)) -> RedirectResponse:
    _require_on(request, conn)
    provider = _provider(request, provider_id)
    flow = _flows(request).take(state)
    if flow is None:
        return _back("expired", provider_id)
    if (flow.user_id != user.id or flow.provider != provider_id
            or not hmac.compare_digest(flow.session_hash, _session_hash(request))):
        log.warning("connected devices: a way back from %s did not match the person who started it", provider.name)
        return _back("wrong_account", provider_id)
    if user.is_test_account:
        return _back("test_account", provider_id)
    if error or not code:
        return _back("cancelled", provider_id)
    try:
        tokens = provider.exchange(code=code, redirect_uri=redirect_uri(request, provider_id))
    except ProviderError as exc:
        return _back({"scope": "scope", "unreachable": "unavailable", "rate_limited": "unavailable"}.get(exc.code, "failed"),
                     provider_id)
    keyring = auth_context(request).require_keyring()
    try:
        store.connect(conn, keyring, user.id, provider_id, tokens)
    except ProviderError:
        conn.rollback()
        return _back("taken", provider_id)
    audit(conn, user.id, "device.connected", "device", provider_id, ip=request_ip(request), provider=provider_id)
    conn.commit()
    return _back("connected", provider_id)


@router.post("/{provider_id}/sync", response_model=SyncOut)
def sync_now(request: Request, user: CurrentUser, provider_id: ProviderId = Path(),
             conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    provider = _provider(request, provider_id)
    row = store.connection(conn, user.id, provider_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not Found")
    if row["status"] != store.STATUS_ACTIVE:
        raise ApiProblem(409, f"{provider.name} needs you to connect again before it can sync.")
    age = seconds_since(row["last_sync_at"])
    if age is not None and age < SYNC_NOW_MIN_S:
        raise too_many(int(SYNC_NOW_MIN_S - age) + 1, "It synced a few minutes ago. Try again in a few minutes.")
    paused = seconds_since(row["next_sync_after"])
    if paused is not None and paused < 0:
        raise too_many(int(-paused) + 1, f"{provider.name} asked us to slow down. Try again later.")
    devices = devices_of(request)
    if not devices.claim(int(row["id"])):
        raise ApiProblem(409, "A sync is already running. Try again in a minute.")
    keyring = auth_context(request).require_keyring()
    result: dict[str, Any] | None = None
    code: str | None = None
    try:
        if conn.in_transaction:
            conn.commit()
        result = sync_connection(conn, keyring, provider, row)
    except ProviderError as exc:
        code = exc.code
    finally:
        devices.release(int(row["id"]))
    return {"connection": _connection_out(conn, user.id, provider_id), "result": result, "error": code}


@router.delete("/{provider_id}", response_model=DisconnectOut)
def disconnect(request: Request, user: CurrentUser, provider_id: ProviderId = Path(),
               delete_readings: bool = Query(False), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _require_on(request, conn)
    provider = devices_of(request).provider(provider_id)
    row = store.connection(conn, user.id, provider_id) if provider is not None else None
    if provider is None or row is None:
        raise HTTPException(status_code=404, detail="Not Found")
    external = row["external_user_id"]
    removed = store.disconnect(conn, user.id, provider_id, delete_readings=delete_readings)
    audit(conn, user.id, "device.disconnected", "device", provider_id, ip=request_ip(request), provider=provider_id,
          deleted_weights=removed["weights"], deleted_readings=removed["readings"])
    conn.commit()
    # After the commit: the tokens are gone here whatever Withings answers.
    revoked = bool(external) and provider.available and provider.revoke(str(external))
    return {"removed": removed, "revoked": bool(revoked)}


def about_view(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """``devices`` in ``GET /api/admin/about``: the switch, each provider's app without its secret, its return address and how
    many people are connected."""
    devices = devices_of(request)
    out = []
    for provider in devices.providers.values():
        info = dict(provider.about())
        counts = conn.execute("SELECT status, COUNT(*) AS n FROM device_connections WHERE provider = ? GROUP BY status",
                              (provider.id,)).fetchall()
        info["connected"] = {r["status"]: int(r["n"]) for r in counts}
        info["redirect_uri"] = redirect_uri(request, provider.id) if request.app.state.settings.public_origin else None
        out.append(info)
    return {"enabled": enabled(request, conn), "providers": out}
