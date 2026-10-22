"""``POST /mcp``: the MCP Streamable HTTP transport for a chat assistant (``docs/dev/plans/assistant-step1.md``
part B; ARCHITECTURE.md "Assistant MCP server").

One endpoint, JSON-RPC 2.0, one JSON object per request and one JSON object per answer (no SSE stream),
stateless (no ``Mcp-Session-Id``). Protocol versions 2025-06-18 and 2025-03-26: ``initialize`` answers the
client's version when it is one of them, else the newest. The ``MCP-Protocol-Version`` header is accepted and
not required.

Order of checks for every request (each one answers before the next runs):

1. The middlewares (``app.security``): the body limit (``MAX_BODY_BYTES``, ``413``), then ``Origin`` on the
   exact path ``/mcp``: present and not this server's own origin (or ``PUBLIC_URL``) → ``403``. The cookie CSRF
   checks do not apply here: no cookie is ever read.
2. The instance switch ``assistant.enabled`` off → ``404`` for every method, as if the route did not exist.
3. ``GET``, ``DELETE``, ``PUT``, ``PATCH`` → ``405`` with ``Allow: POST`` (no SSE stream, no sessions to end).
4. The bearer token (:func:`app.auth.api_tokens.authenticate`, scope ``assistant:read``): the generic ``401``
   with ``WWW-Authenticate: Bearer``, or ``429`` for an address blocked after refused tokens.
5. The per-token limit, 60 requests a minute (``ratelimit`` ``mcp``, every request counts, saving ones too) →
   ``429`` with ``Retry-After``.
6. The JSON-RPC message: not JSON → ``-32700``; not one request object (a batch array, no ``"jsonrpc": "2.0"``,
   a bad ``id``) → ``-32600``, both with HTTP 400; a notification, or a response from the client → ``202``
   without a body; an unknown method → ``-32601``; unusable ``params`` or an unknown tool → ``-32602``.
   Wrong tool arguments and tool failures are tool results with ``isError: true`` and a short text.

Scopes: every request needs ``assistant:read``. The tools that save (``log_food``, ``save_recipe``) are listed by
``tools/list`` and callable only with a token that also has ``assistant:log``; calling one without it is a tool
result with ``isError: true`` that says the token can only read, and nothing is saved. ``set_food_preference``
(:mod:`app.mcp.preference_tool`) is listed and callable only with ``assistant:prefs``, a separate opt-in that
``assistant:log`` does not give; a token without it is told "Unknown tool", as if there were no such tool. A limit
refusal inside a tool (the daily cap on taste changes) is the ``429`` of that limit, like the per-token limit above.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from ..auth import api_tokens
from ..auth.context import auth_context
from ..auth.errors import ApiProblem
from ..auth.ratelimit import register_limit
from ..db import get_db
from . import preference_tool as PT
from . import tools as T

logger = logging.getLogger("kidney_health.mcp")

PATH = "/mcp"
PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26")  # newest first
SERVER_NAME = "kidney-health"
SERVER_TITLE = "Kidney Health food log"
INSTRUCTIONS = (
    "Read-only access to one person's kidney-health food log. Call safety_check first with every message from the "
    "person and follow its action before anything else. Take every number (targets, totals, foods, what is left) "
    "from these tools, never from memory or your own knowledge, and fetch again after any change. null means the "
    "value is not listed (unknown), never zero: say so. Never give insulin or medicine doses and never interpret "
    "lab results: those belong to the person's care team."
)
# Added to the instructions for a token that can also save (assistant:log).
WRITE_INSTRUCTIONS = (
    " This token can also save: log_food saves food to the log and save_recipe saves a recipe. Before saving, read "
    "the items back (food, amount, meal, day, eaten or planned) and ask the person to confirm; after saving, say what "
    "was saved. The confirmation is only about the record: it never comes before the person treats a low. Send a new "
    "request_key with each save, and the same one again only to retry that save: a repeat is not saved twice."
)

# Added to the instructions for a token that can also remember tastes (assistant:prefs).
PREFS_INSTRUCTIONS = (
    " This token can also remember tastes: set_food_preference records that the person likes a food or food group, wants "
    "it less often, or does not want it, or clears one of those. Use it only when the person says so in this conversation, "
    "after you read it back and they said yes; never infer a taste from what they log or ask about, and never use it for an "
    "allergy (the app cannot check allergens). Send a new request_key with each change, and say what you set: the person can "
    "change or remove it in the app. It only changes the order of the app's suggestions and has no part in treating a low."
)

RATE_LIMIT = "mcp"
register_limit(RATE_LIMIT, 60, 60, "Too many assistant requests with this token. Try again in a minute.")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

NO_STORE = {"Cache-Control": "no-store"}

router = APIRouter(tags=["assistant"])


def _json(body: Any, status: int = 200, headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={**NO_STORE, **(headers or {})})


def _not_found() -> JSONResponse:
    return _json({"detail": "Not Found"}, 404)


def _error(code: int, message: str, request_id: Any = None, status: int = 200) -> JSONResponse:
    return _json({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status)


def _result(request_id: Any, result: Mapping[str, Any]) -> JSONResponse:
    return _json({"jsonrpc": "2.0", "id": request_id, "result": result})


def _valid_id(value: Any) -> bool:
    """MCP request ids are strings or integers (never null, never a boolean)."""
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _parse(body: bytes) -> Any:
    """The decoded message; ``ValueError`` for anything that is not strict JSON (NaN and Infinity included)."""
    try:
        return json.loads(body.decode("utf-8"), parse_constant=_refuse_constant)
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError(str(exc)) from None


def can_log(request: Request) -> bool:
    """The token of this request also has ``assistant:log`` (``authenticate`` has set it)."""
    return api_tokens.LOG in request.state.api_token.scopes


def can_prefs(request: Request) -> bool:
    """The token of this request also has ``assistant:prefs`` (it never comes with ``assistant:log``)."""
    return api_tokens.PREFS in request.state.api_token.scopes


def all_tools() -> tuple[T.Tool, ...]:
    """Every tool the server has: :data:`app.mcp.tools.TOOLS` and the taste tool, which needs Ask's own checks and so lives in
    :mod:`app.mcp.preference_tool` (it imports :mod:`app.mcp.tools`, so the list is put together here)."""
    return (*T.TOOLS, PT.TOOL)


def tool_named(name: str) -> T.Tool | None:
    return T.TOOLS_BY_NAME.get(name) or (PT.TOOL if name == PT.TOOL.name else None)


def allowed(request: Request, tool: T.Tool) -> bool:
    """The token has the scope the tool needs (:attr:`app.mcp.tools.Tool.needs`)."""
    return tool.needs in request.state.api_token.scopes


def initialize_result(params: Mapping[str, Any], version: str, can_save: bool = False,
                      can_remember: bool = False) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    return {
        "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": version},
        "instructions": INSTRUCTIONS + (WRITE_INSTRUCTIONS if can_save else "") + (PREFS_INSTRUCTIONS if can_remember else ""),
    }


def tool_result(result: Mapping[str, Any]) -> dict[str, Any]:
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {"content": [{"type": "text", "text": text}], "structuredContent": result, "isError": False}


def tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def call_tool(tool: T.Tool, call: T.Call, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Run one tool (in a worker thread): its result, or an ``isError`` result with a short, safe text."""
    try:
        return tool_result(T.run(tool, call, arguments))
    except T.ToolError as exc:
        return tool_error(str(exc))
    except ApiProblem:  # a limit inside the tool (the daily cap on taste changes): its own 429 with Retry-After
        raise
    except Exception:  # noqa: BLE001 - never a stack trace or a value in the answer; the log has the details
        logger.exception("assistant tool %s failed", tool.name)
        if tool.writes:  # every save is one transaction: a failure before the commit leaves nothing behind
            return tool_error(f"{tool.name} could not save this time and nothing was saved. Try again; if it keeps "
                              "failing, tell the person to use the app directly.")
        return tool_error(f"{tool.name} could not answer this time. Try again; if it keeps failing, tell the person "
                          "to use the app directly.")


@router.post(PATH, summary="Assistant MCP server (JSON-RPC 2.0, bearer token)", response_class=JSONResponse, operation_id="mcp_post")
async def mcp_post(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """MCP Streamable HTTP (JSON answers, stateless) for a chat assistant with an assistant access token."""
    ctx = auth_context(request)
    if not await run_in_threadpool(api_tokens.is_enabled, conn, ctx):
        return _not_found()
    user = await run_in_threadpool(api_tokens.authenticate, request, conn, api_tokens.READ)
    ctx.limits.take(RATE_LIMIT, f"token:{request.state.api_token.id}")

    try:
        message = _parse(await request.body())
    except ValueError:
        return _error(PARSE_ERROR, "Parse error: the body is not JSON.", status=400)
    if not isinstance(message, dict):
        return _error(INVALID_REQUEST, "Invalid request: send one JSON-RPC object (batches are not supported).",
                      status=400)
    request_id = message.get("id")
    shown_id = request_id if _valid_id(request_id) else None
    if message.get("jsonrpc") != "2.0":
        return _error(INVALID_REQUEST, 'Invalid request: "jsonrpc" must be "2.0".', shown_id, status=400)
    method = message.get("method")
    if method is None:
        if "id" in message and ("result" in message or "error" in message):
            return Response(status_code=202, headers=NO_STORE)  # a response from the client: nothing to do
        return _error(INVALID_REQUEST, "Invalid request: no method.", shown_id, status=400)
    if not isinstance(method, str):
        return _error(INVALID_REQUEST, "Invalid request: method must be a string.", shown_id, status=400)
    if "id" not in message:
        return Response(status_code=202, headers=NO_STORE)  # a notification (notifications/initialized, …)
    if not _valid_id(request_id):
        return _error(INVALID_REQUEST, "Invalid request: id must be a string or an integer.", status=400)

    params = message.get("params", {})
    if method not in ("initialize", "ping", "tools/list", "tools/call"):
        return _error(METHOD_NOT_FOUND, f"Method not found: {method[:80]}", request_id)
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(INVALID_PARAMS, "Invalid params: params must be an object.", request_id)

    if method == "initialize":
        return _result(request_id, initialize_result(params, request.app.version, can_log(request), can_prefs(request)))
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [tool.listing() for tool in all_tools() if allowed(request, tool)]})

    name = params.get("name")
    tool = tool_named(name) if isinstance(name, str) else None
    if tool is not None and not allowed(request, tool):
        if tool.needs == api_tokens.LOG:  # a read-only token: say so, save nothing
            return _result(request_id, tool_error(T.READ_ONLY))
        tool = None  # a tool the token has no scope for is not there at all
    if tool is None:
        return _error(INVALID_PARAMS, f"Unknown tool: {str(name)[:80]}", request_id)
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _result(request_id, tool_error("Invalid arguments: arguments must be an object."))
    result = await run_in_threadpool(call_tool, tool, T.Call(request, conn, user), arguments)
    return _result(request_id, result)


def mcp_other(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """``405`` (``404`` while assistant access is off): the server offers no SSE stream and keeps no sessions."""
    if not api_tokens.is_enabled(conn, auth_context(request)):
        return _not_found()
    return _json({"detail": "Method Not Allowed"}, 405, {"Allow": "POST"})


for _method in ("GET", "DELETE", "PUT", "PATCH"):  # one route each, so every OpenAPI operation id is unique
    router.add_api_route(PATH, mcp_other, methods=[_method], operation_id=f"mcp_{_method.lower()}_not_allowed",
                         summary="Not offered: no SSE stream, no sessions (405)")
