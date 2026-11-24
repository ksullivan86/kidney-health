"""The iPhone app's bearer gateway ``/push/v1/api/<path>`` and ``GET /push/v1/about`` (design note 39 §5; ARCHITECTURE.md
"Device tokens and /push/v1"; guide ``docs/push.md``).

Once the iPhone app is paired with a token of the kind "The iPhone app, both ways" (scope ``app:sync``), it can use some of this
server's ``/api`` routes as the token's owner: the AI features and the food lookups. ``/api`` itself stays cookie-only. The gateway
runs the same route the web app calls, so every rule of that route still holds: ``user.id`` scoping, not-yours is ``404``, the AI's
routing, consent, prefilters, guard, daily limit and activity list, the lab routes' local-only rule, the food services' keys, limits
and outbound checks.

Order of checks at ``/push/v1/api/<path>`` (each answers before the next runs):

1. The middlewares of :mod:`app.security`: the body limit of the ``/api`` route it stands for, then **any** ``Origin`` header, or a
   ``Sec-Fetch-Site`` other than ``none``, is ``403``. The iPhone app sends neither; a browser always does.
2. A device token with ``app:sync`` (:func:`app.auth.api_tokens.authenticate`): the generic ``401`` for every failure, ``429`` for a
   blocked address. While ``push.enabled`` or ``push.app_sync`` is off every request is that ``401`` and nothing is looked up. A
   request with a session cookie and no token is that ``401`` too: no cookie is read.
3. The token's own limit: **600 requests an hour** (``ratelimit`` ``push_gateway``, key ``token:<id>``), shared with
   ``GET /push/v1/about``. The route's own limits apply after it, as they do for the web app.
4. The allow-list (:data:`ALLOWED`): a method and ``/api`` route that is not on it is ``404`` with :data:`NOT_ON_LIST`. A route that
   needs a recent password, an admin route, sign-in, tokens, sessions, keys and providers, sharing, the import, the ``.zip`` export
   and deleting the account are never on it (:data:`NEVER`, pinned by ``tests/test_app_gateway.py``).
5. The route runs as the token's owner with the role ``user`` (:class:`app.auth.deps.GatewayCaller`): a gateway request is never an
   admin. The ``Cookie`` and ``Authorization`` headers are removed before it runs. A second check inside the app
   (:func:`guard`, an app-wide dependency) refuses any route but the one on the list the request was let in for.

Every answer has ``Cache-Control: no-store``. The log line holds the token's id, the route's template and the status, never a value.
The first use of each token each UTC day writes one activity row, ``app.server_used`` ("The iPhone app used your server").

``GET /push/v1/about`` answers what this server offers this person, so the phone can choose without trying each route: an opaque
``account`` key (an HMAC of the person's id under this server's secret key: it names neither), the versions, the gateway's list, the
AI (``available`` and the same ``routes`` as ``GET /api/ai/status``), and the food and list services.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import barcode, brand, instacart, meta
from .ai import routes as ai_routes
from .api_version import API_VERSION
from .audit import audit
from .auth import api_tokens
from .auth.context import auth_context
from .auth.deps import GATEWAY_STATE, GatewayCaller, gateway_caller
from .auth.errors import ApiProblem
from .auth.models import User
from .auth.ratelimit import register_limit
from .db import connect, get_db
from .list_sync import api as list_sync_api
from .push import NO_STORE
from .recipe_import import api as recipe_import_api
from .security import gateway_api_path, is_gateway_path

logger = logging.getLogger(f"{brand.LOGGER_NAME}.push")

RATE_LIMIT = "push_gateway"
register_limit(RATE_LIMIT, 600, 3600, "Too many requests from this app. Try again later.")
NOT_ON_LIST = "This is not open to the iPhone app."

# The routes the gateway runs (design note 39 §5.2 and §11 step 2): the AI features of §6.4 and the food lookups of §7. Each is
# (method, the /api route's template). The list grows step by step; a test fails if one is missing, needs a recent password or is
# an admin route.
ALLOWED: frozenset[tuple[str, str]] = frozenset({
    # The server's AI (§6): status, consent, and every feature. The lab routes run only on the local AI (note 36).
    ("GET", "/api/ai/status"),
    ("POST", "/api/ai/consent"),
    ("DELETE", "/api/ai/consent/{provider_id}"),
    ("POST", "/api/ai/next-meal"),
    ("POST", "/api/ai/parse-meal"),
    ("POST", "/api/ai/recipes"),
    ("POST", "/api/ai/chat"),
    ("POST", "/api/ai/transcribe"),
    ("POST", "/api/vision/label"),
    ("POST", "/api/vision/plate"),
    ("POST", "/api/ai/read-lab-report"),
    ("POST", "/api/ai/read-lab-report-text"),
    # The server's food services (§7): USDA with the key the server would use for this person, and barcodes.
    ("GET", "/api/foods/usda/search"),
    ("POST", "/api/foods/usda/import"),
    ("POST", "/api/foods/barcode"),
    # Two settings the phone needs before it may ask the server (§6.1, §7), and only those keys (BODY_KEYS): the person's own
    # Open Food Facts consent, and their AI opt-in.
    ("PATCH", "/api/me/settings"),
    ("PATCH", "/api/me/ai"),
})
# Routes on the list that take only some keys through the gateway: the body must be one JSON object holding at least one of these
# keys and nothing else, or the answer is 403 and the route never runs.
BODY_KEYS: dict[tuple[str, str], frozenset[str]] = {
    ("PATCH", "/api/me/settings"): frozenset({"food.off_consent"}),
    ("PATCH", "/api/me/ai"): frozenset({"opt_in"}),
}
ONLY_KEYS = "From the iPhone app this can change only: {keys}."
MAX_KEYS_BODY = 4096

# Never on the list, whatever it grows into (§5.2): prefixes of /api paths, and single routes.
NEVER_PREFIXES: tuple[str, ...] = (
    "/api/auth/", "/api/admin/", "/api/me/tokens", "/api/me/sessions", "/api/me/keys", "/api/me/ai/provider", "/api/me/ai/probe",
    "/api/me/import", "/api/me/export.zip", "/api/me/password", "/api/me/totp", "/api/me/passkeys", "/api/me/oidc",
    "/api/me/email", "/api/me/shares", "/api/shared", "/api/devices",
)
NEVER: frozenset[tuple[str, str]] = frozenset({("DELETE", "/api/me"), ("PATCH", "/api/me")})


def never_allowed(method: str, path: str) -> bool:
    """True for a route the gateway must never run."""
    return (method.upper(), path) in NEVER or any(path == p.rstrip("/") or path.startswith(p) for p in NEVER_PREFIXES)


# --------------------------------------------------------------------------- #
# The routes the list names, found in the app's route tree
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Allowed:
    """The list resolved against one app: a regex per allowed template, and the route objects themselves."""

    patterns: tuple[tuple[str, str, re.Pattern[str]], ...]  # (method, template, compiled path)
    routes: dict[int, set[str]]  # id(route object) -> the methods allowed on it


def walk_routes(routes: Iterable[Any]) -> Iterable[tuple[str, str, Any]]:
    """``(METHOD, full path, route object)`` for every endpoint, through FastAPI's tree of included routers."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):  # FastAPI >= 0.137: an included router
            for ctx in contexts():
                for method in getattr(ctx, "methods", None) or ():
                    yield method.upper(), ctx.path, ctx.original_route
            continue
        path, methods = getattr(route, "path", None), getattr(route, "methods", None)
        if path and methods:
            for method in methods:
                yield method.upper(), path, route


def resolve(app: Any) -> Allowed:
    """The allow-list against ``app``'s routes (cached on ``app.state``). A listed route the app does not have is an error."""
    cached = getattr(app.state, "push_gateway_allowed", None)
    if isinstance(cached, Allowed):
        return cached
    found: dict[int, set[str]] = {}
    seen: set[tuple[str, str]] = set()
    for method, path, route in walk_routes(app.routes):
        if (method, path) in ALLOWED:
            found.setdefault(id(route), set()).add(method)
            seen.add((method, path))
    missing = ALLOWED - seen
    if missing:
        raise RuntimeError(f"the gateway's allow-list names routes this app does not have: {sorted(missing)}")
    patterns = tuple((m, p, compile_path(p)[0]) for m, p in sorted(ALLOWED))
    allowed = Allowed(patterns, found)
    app.state.push_gateway_allowed = allowed
    return allowed


def match(allowed: Allowed, method: str, api_path: str) -> str | None:
    """The template on the list that ``method api_path`` would run, or None."""
    for m, template, regex in allowed.patterns:
        if m == method and regex.match(api_path):
            return template
    return None


def guard(request: Request) -> None:
    """An app-wide dependency: a gateway request may run only a route on the list (the route the router chose, by identity).
    Every other request passes untouched."""
    if gateway_caller(request) is None:
        return
    allowed = resolve(request.app)
    route = request.scope.get("route")
    if route is None or request.method.upper() not in allowed.routes.get(id(route), set()):
        raise ApiProblem(404, NOT_ON_LIST)


# --------------------------------------------------------------------------- #
# The middleware: check the token, then run the /api route as its owner
# --------------------------------------------------------------------------- #


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def note_use(conn: sqlite3.Connection, user: User, token: api_tokens.TokenInfo) -> None:
    """One ``app.server_used`` activity row per token per UTC day (commits when it writes)."""
    day = _today()
    seen = conn.execute(
        "SELECT 1 FROM audit_log WHERE action = 'app.server_used' AND target_type = 'api_token' AND target_id = ? AND at >= ? LIMIT 1",
        (str(token.id), day)).fetchone()
    if seen is None:
        audit(conn, user.id, "app.server_used", "api_token", token.id, via=token.name)
        conn.commit()


def admit(request: Request, method: str, api_path: str) -> tuple[GatewayCaller, str]:
    """Steps 2 to 4 of the module docstring, in a worker thread. Returns who the route runs as, and its template."""
    conn = connect(request.app.state.settings.db_path)
    try:
        user = api_tokens.authenticate(request, conn, api_tokens.APP_SYNC)
        token: api_tokens.TokenInfo = request.state.api_token
        auth_context(request).limits.take(RATE_LIMIT, f"token:{token.id}")
        template = match(resolve(request.app), method, api_path)
        if template is None:
            raise ApiProblem(404, NOT_ON_LIST)
        note_use(conn, user, token)
    finally:
        conn.close()
    request.state.user = None  # set by authenticate; the route sets its own from the caller below
    return GatewayCaller(replace(user, role="user"), token), template


_DROP_HEADERS = frozenset({b"cookie", b"authorization"})


class GatewayMiddleware:
    """Runs ``/push/v1/api/<path>`` as ``/api/<path>`` for the owner of an ``app:sync`` token (inside :mod:`app.security`'s
    stack, so the headers, the host check, the body limit and the Origin rule have already run)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_gateway_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        api_path = gateway_api_path(scope["path"])
        request = Request(scope)
        try:
            caller, template = await run_in_threadpool(admit, request, method, api_path)
        except ApiProblem as exc:
            response = exc.response()
            response.headers.update(NO_STORE)
            await response(scope, receive, send)
            return
        keys = BODY_KEYS.get((method, template))
        if keys is not None:
            body = await _read_all(receive)
            if not _only_keys(body, keys):
                response = ApiProblem(403, ONLY_KEYS.format(keys=", ".join(sorted(keys)))).response()
                response.headers.update(NO_STORE)
                await response(scope, receive, send)
                return
            receive = _replay(body)
        inner = dict(scope)
        inner["path"] = api_path
        inner["raw_path"] = api_path.encode("utf-8")
        inner["headers"] = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in _DROP_HEADERS]
        state = scope.setdefault("state", {})
        state[GATEWAY_STATE] = caller
        inner["state"] = state

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                message = {**message, "headers": [*headers, (b"cache-control", b"no-store")]}
                # The token's id, the route's template and the status: never a value.
                logger.info("gateway: token %d %s %s -> %d", caller.token.id, method, template, int(message["status"]))
            await send(message)

        await self.app(inner, receive, send_no_store)


async def _read_all(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_KEYS_BODY:
            return b""  # far more than two settings: refused below
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _only_keys(raw: bytes, keys: frozenset[str]) -> bool:
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(doc, dict) and bool(doc) and set(doc) <= keys


def _replay(body: bytes) -> Receive:
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


# --------------------------------------------------------------------------- #
# GET /push/v1/about
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/push/v1", tags=["push"])
ABOUT_PATH = "/about"


class AboutRoute(BaseModel):
    method: str
    path: str = Field(description="The `/api` route; the phone calls it at `/push/v1` + this path.")


class AboutAi(BaseModel):
    enabled: bool = Field(description="The AI is on for this person (`ai.enabled`, and for a test account `test_accounts.ai`).")
    available: bool = Field(description="As `GET /api/ai/status`: the person opted in and a provider answers.")
    routes: dict[str, Any] = Field(description="As `routes` of `GET /api/ai/status`: where each feature runs. Empty while off.")


class AboutServices(BaseModel):
    usda_search: bool = Field(description="USDA search and import with the key this server would use for this person.")
    barcode: bool
    barcode_off: bool
    barcode_usda: bool
    recipe_import: bool = Field(description="This server reads a recipe page from its link (`RECIPE_IMPORT_ENABLED`).")
    instacart: bool
    list_sync: bool


class AboutSync(BaseModel):
    gateway: bool = Field(description="`/push/v1/api/` runs the routes of `gateway`.")
    changes: bool = Field(description="The change feed (`GET` and `POST /push/v1/changes`, `POST /push/v1/match`).")


class AboutFeatures(BaseModel):
    usda_search: bool = Field(description="As `services.usda_search`.")
    barcode: bool = Field(description="As `services.barcode`.")
    ai: bool = Field(description="As `ai.available`.")
    changes: bool = Field(description="As `sync.changes`.")


class About(BaseModel):
    account: str = Field(description="Opaque and stable for this person on this server; names neither. A new value means a "
                                     "different account or server.")
    api_version: int
    app_version: str
    sync: AboutSync
    gateway: list[AboutRoute]
    ai: AboutAi
    services: AboutServices
    capabilities: meta.Capabilities
    features: AboutFeatures


def account_key(request: Request, user_id: int) -> str:
    """An HMAC of the person's id under this server's secret key (32 hex characters)."""
    keyring = auth_context(request).require_keyring()
    return keyring.mac(brand.HKDF_APP_ACCOUNT_INFO, str(int(user_id))).hex()[:32]


def about_view(request: Request, conn: sqlite3.Connection, user: User, *, changes: bool) -> dict[str, Any]:
    person = replace(user, role="user")
    caps = meta.capabilities(request, conn, person)
    ai_on = ai_routes.ai_on_for(request, conn, person)
    view = ai_routes.status_view(request, conn, person) if ai_on else None
    usda = barcode.usda_unavailable_reason(conn, request, person) is None
    return {
        "account": account_key(request, person.id),
        "api_version": API_VERSION,
        "app_version": request.app.version,
        "sync": {"gateway": True, "changes": changes},
        "gateway": [{"method": m, "path": p} for m, p in sorted(ALLOWED, key=lambda mp: (mp[1], mp[0]))],
        "ai": {"enabled": ai_on, "available": bool(view and view["available"]), "routes": dict(view["routes"]) if view else {}},
        "services": {"usda_search": usda, "barcode": caps["barcode"], "barcode_off": caps["barcode_off"],
                     "barcode_usda": caps["barcode_usda"], "recipe_import": recipe_import_api.web_enabled(request, conn),
                     "instacart": instacart.enabled(request, conn), "list_sync": list_sync_api.enabled(request, conn)},
        "capabilities": caps,
        "features": {"usda_search": usda, "barcode": caps["barcode"], "ai": bool(view and view["available"]), "changes": changes},
    }


CHANGE_FEED = True  # design note 39 step 5: GET and POST /push/v1/changes and POST /push/v1/match (app/sync_feed.py)


@router.get(ABOUT_PATH, response_model=About, summary="What this server offers the iPhone app (token with app:sync)")
def push_about(request: Request, user: api_tokens.AppSyncUser, conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    """The ``account`` key, the versions, the gateway's list, the AI and the services for the token's owner. One request of the
    token's 600 an hour."""
    token = request.state.api_token
    auth_context(request).limits.take(RATE_LIMIT, f"token:{token.id}")
    return JSONResponse(About.model_validate(about_view(request, conn, user, changes=CHANGE_FEED)).model_dump(mode="json"),
                        headers=NO_STORE)


def about_other() -> JSONResponse:
    """``405`` for every method but GET."""
    return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "GET", **NO_STORE})


for _method in ("POST", "DELETE", "PUT", "PATCH"):  # one route each, so every OpenAPI operation id is unique
    router.add_api_route(ABOUT_PATH, about_other, methods=[_method], operation_id=f"push_about_{_method.lower()}_not_allowed",
                         summary="Not offered: GET only (405)")
