"""The OpenAPI document, made honest and stable (design note 14 change 2; ``docs/api/README.md``).

FastAPI writes a document from the routes, and out of the box it is wrong about this app in four ways. This module fixes them in one
place, so the document at ``/openapi.json`` (off unless ``ENABLE_API_DOCS``) and the checked-in snapshot ``docs/api/openapi.json``
(``scripts/gen_openapi.py``) say the same true things:

* **Operation ids** (:func:`operation_id`) are ``<first tag>_<route function>`` (the tag is left off when the function already starts
  with it): ``auth_login``, ``log_create_entry``, ``admin_list_users``. FastAPI's default (``login_api_auth_login_post``) contains the
  path and the method, so it changed whenever a route moved. A client generator turns the id into a method name, so the id must not
  move. ``tests/test_openapi_snapshot.py`` asserts the ids are unique.
* **Validation errors are 400**, with the body ``security.validation_error_handler`` really sends (``{detail, errors: [{type, loc,
  msg}]}``), not FastAPI's 422. The 422 FastAPI adds is removed from every operation; the 422 a route declares itself (the out-of-scope
  refusal of ``GET /api/profile/suggested-targets``) stays.
* **Every error has one shape** (the ``Problem`` schema: ``{detail: string, ...}``), as shared ``components.responses``. They are added
  by rules that follow from how the app is built, not guessed per route (:func:`_statuses`), plus a short reviewed list of the routes
  that answer 409, 415 or 429 (:data:`CONFLICT`, :data:`UNSUPPORTED_MEDIA`, :data:`RATE_LIMITED`). Every ``/api`` operation also has a
  ``default`` response with the same shape, so a status the list does not name is still described.
* **Security schemes**: ``session`` (the cookie, and the CSRF header it needs), ``assistantToken`` (``kha_`` at ``/mcp``) and
  ``deviceToken`` (``khd_`` at ``POST /push/v1/body``). Which one a route has is read from its dependencies
  (:func:`_needs_session`: ``current_user`` anywhere in the dependency tree) and from :data:`BEARER_OPERATIONS`, which a test holds equal
  to ``security.BEARER_PATHS``.

``info.version`` is the app's version and ``info.x-api-version`` is :data:`app.api_version.API_VERSION`.

Nothing here changes what a route does: the document is the only thing that is rewritten.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI
from fastapi import routing as fastapi_routing

from . import brand
from .ai.routes import require_ai_enabled
from .api_version import API_VERSION
from .auth.deps import current_user

SESSION = "session"
ASSISTANT_TOKEN = "assistantToken"
DEVICE_TOKEN = "deviceToken"

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
UNSAFE_METHODS = ("post", "put", "patch", "delete")
BODY_METHODS = ("post", "put", "patch")  # the methods whose body the global size limit (413) applies to

# The two bearer-only surfaces outside /api. Only the POST takes the token; the 405 stubs for the other methods answer without one.
# tests/test_openapi_snapshot.py holds these paths equal to ``security.BEARER_PATHS``.
BEARER_OPERATIONS: dict[tuple[str, str], str] = {
    ("post", "/mcp"): ASSISTANT_TOKEN,
    ("post", "/push/v1/body"): DEVICE_TOKEN,
    ("get", "/push/v1/check"): DEVICE_TOKEN,
}
# The stubs that answer 405 for the methods a bearer route does not offer. ``/mcp`` answers 404 first while ``assistant.enabled`` is off.
NOT_ALLOWED_SUFFIX = "_not_allowed"

# Operations that answer these statuses on top of the structural rules, by operation id. Reviewed by hand against the handlers
# (grep ``ApiProblem(409``, ``HTTPException(status_code=409``, ``limits.take``, ``too_many(`` and the consent, routing and key-test helpers).
# A status missing here is still covered by the operation's ``default`` response; a new entry only makes the document more exact.
CONFLICT: frozenset[str] = frozenset({
    "auth_setup", "auth_register", "me_delete_me", "me_update_my_settings", "me_create_my_token", "me_import_my_data",
    "admin_create_account", "admin_update_account", "admin_delete_account", "admin_issue_reset_link", "admin_create_invite",
    "admin_set_shared_key", "admin_delete_shared_key", "admin_update_instance_settings",
    "foods_update_food", "foods_delete_food", "log_create_entry", "log_create_batch", "log_quick_add",
    "guidance_put_preference", "guidance_add_not_for_me",
    "ai_give_consent", "ai_next_meal", "ai_parse_meal", "ai_chat", "ai_transcribe",
    "vision_read_label", "vision_plate", "vision_read_lab_report",
    "admin_update_ai_provider", "admin_delete_ai_provider", "admin_update_ai_routing",
    "me_setup_totp", "me_enable_totp", "me_renew_recovery_codes",
    "me_passkey_creation_options", "me_add_passkey",
})
UNSUPPORTED_MEDIA: frozenset[str] = frozenset({
    "vision_read_label", "vision_plate", "vision_read_lab_report", "ai_transcribe", "me_import_my_data", "push_body",
})
RATE_LIMITED: frozenset[str] = frozenset({
    "auth_login", "auth_setup", "auth_register", "auth_reset_info", "auth_reset", "auth_reauth",
    "me_change_password", "me_delete_me", "me_set_my_key", "me_export_my_data", "me_create_my_token", "me_import_my_data",
    "admin_set_shared_key", "admin_probe_ai_provider", "admin_probe_voice", "ai_probe_my_provider",
    "body_create_weights", "body_create_readings", "barcode_lookup", "foods_usda_search", "foods_usda_import",
    "ai_next_meal", "ai_parse_meal", "ai_chat", "ai_transcribe", "vision_read_label", "vision_plate", "vision_read_lab_report",
    "mcp_post", "push_body", "push_check", "me_enable_totp",
    "me_passkey_creation_options", "auth_passkey_request_options", "auth_passkey_sign_in",
})
# Public routes that answer 401: the sign-in with a wrong name or password, and a passkey that did not work.
UNAUTHORIZED_PUBLIC: frozenset[str] = frozenset({"auth_login", "auth_passkey_sign_in"})

_REF = "#/components/"
_PROBLEM_SCHEMA = _REF + "schemas/Problem"


# --------------------------------------------------------------------------- #
# Operation ids
# --------------------------------------------------------------------------- #


def operation_id(route: Any) -> str:
    """``<first tag>_<route function name>``; just the name when it already starts with the tag or the route has no tag.

    Stable when a path, a prefix or a method changes, which FastAPI's default is not. Renaming the route function (or
    changing its first tag) renames the id: a rename is a change a client generated from the document will notice.
    """
    name = re.sub(r"\W", "_", str(route.name))
    tags = getattr(route, "tags", None) or []
    tag = re.sub(r"\W", "_", str(getattr(tags[0], "value", tags[0]))) if tags else ""
    if not tag or name == tag or name.startswith(tag + "_"):
        return name
    return f"{tag}_{name}"


# --------------------------------------------------------------------------- #
# Shared components
# --------------------------------------------------------------------------- #

_BOOL_FLAG = "true when present"


def _schemas() -> dict[str, Any]:
    return {
        "Problem": {
            "type": "object",
            "title": "Problem",
            "description": (
                "Every error answer. `detail` is a sentence for the person and is always there; a route may add keys next to it "
                "(the ones below are the common ones; read others from `additionalProperties`). Validation errors are the "
                "`ValidationProblem` form of this."
            ),
            "required": ["detail"],
            "additionalProperties": True,
            "properties": {
                "detail": {"type": "string", "description": "What went wrong, in a sentence."},
                "reason": {"type": "string", "description": "A short machine-readable code some routes add (barcode lookups, USDA keys, AI availability)."},
                "code": {"type": "string", "description": "A machine-readable code for a refusal that has one (the out-of-scope refusals of suggested targets)."},
                "field": {"type": "string", "description": "The request field the refusal is about, when it is about one."},
                "problems": {"type": "array", "items": {"type": "string"}, "description": "Every password-policy message (with `field: password`)."},
                "retry_after": {"type": "integer", "minimum": 1, "description": "Seconds to wait (429); the `Retry-After` header says the same."},
                "reauth_required": {"type": "boolean", "description": f"403: enter your password again with POST /api/auth/reauth, then retry once ({_BOOL_FLAG})."},
                "password_change_required": {"type": "boolean", "description": f"403: the person must choose a new password first ({_BOOL_FLAG})."},
                "setup_required": {"type": "boolean", "description": f"503: first-run setup is not done yet ({_BOOL_FLAG})."},
                "https_required": {"type": "boolean", "description": f"400: sign-in is refused over plain HTTP on this server ({_BOOL_FLAG})."},
                "locked_by_env": {"type": "string", "description": "409: the setting is fixed by this environment variable and cannot be changed here."},
            },
        },
        "ValidationProblem": {
            "type": "object",
            "title": "ValidationProblem",
            "description": (
                "The 400 answer. `detail` joins the problems into one sentence (`field: message; field: message`); `errors` lists each one when "
                "the request failed validation and is absent for the other 400s (a rule of the route, not of the shape). The value the "
                "person sent is never echoed back."
            ),
            "required": ["detail"],
            "additionalProperties": True,
            "allOf": [{"$ref": _PROBLEM_SCHEMA}],
            "properties": {
                "detail": {"type": "string"},
                "errors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type", "loc", "msg"],
                        "properties": {
                            "type": {"type": "string", "description": "The kind of problem (`missing`, `string_too_short`, `value_error`, ...)."},
                            "loc": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                                    "description": "Where: `body`, `query` or `path`, then the field names and list positions."},
                            "msg": {"type": "string", "description": "What is wrong with it."},
                        },
                    },
                },
            },
        },
        "EntryConflictProblem": {
            "type": "object",
            "title": "EntryConflictProblem",
            "description": "412 on a log entry: `If-Match` is not the entry's version now. `current` is the entry as stored; nothing was changed.",
            "required": ["detail", "current"],
            "additionalProperties": True,
            "allOf": [{"$ref": _PROBLEM_SCHEMA}],
            "properties": {"detail": {"type": "string"}, "current": {"$ref": _REF + "schemas/Entry"}},
        },
        "JsonRpcError": {
            "type": "object",
            "title": "JsonRpcError",
            "description": "A JSON-RPC 2.0 error object, the body of the 400 that `POST /mcp` answers to a message it cannot read.",
            "required": ["jsonrpc", "id", "error"],
            "properties": {
                "jsonrpc": {"type": "string", "enum": ["2.0"]},
                "id": {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
                "error": {"type": "object", "required": ["code", "message"],
                          "properties": {"code": {"type": "integer"}, "message": {"type": "string"}}},
            },
        },
    }


def _problem_response(description: str, *, schema: str = "Problem", headers: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": _REF + "schemas/" + schema}}},
    }
    if headers:
        out["headers"] = headers
    return out


_RETRY_AFTER = {"Retry-After": {"description": "Seconds to wait before trying again.", "schema": {"type": "integer", "minimum": 1}}}


def _responses() -> dict[str, Any]:
    retry = _RETRY_AFTER
    challenge = {"WWW-Authenticate": {"description": f'Always `Bearer realm="{brand.BEARER_REALM}"`.', "schema": {"type": "string"}}}
    allow = {"Allow": {"description": "The one method the route offers: `POST`.", "schema": {"type": "string"}}}
    return {
        "BadRequest": _problem_response(
            "The request was refused. When it failed validation, `errors` lists each problem (`type`, `loc`, `msg`) and `detail` joins them; "
            "other refusals (a rule of the route, a bad `Content-Length`, HTTPS required) have `detail` and may add `reason`, `field` or other keys. "
            "This app answers **400** for a validation error, never 422.",
            schema="ValidationProblem",
        ),
        "Unauthorized": _problem_response(
            "Not signed in (`Sign in required`): there is no valid session cookie. (Sign-in itself answers this for a wrong name or password.)"
        ),
        "BearerUnauthorized": _problem_response(
            "No token, or a token that does not work here: unknown, revoked, expired, of the other family, without the scope, "
            "or the instance switch for this family is off. Every case is the same generic answer.",
            headers=challenge,
        ),
        "Forbidden": _problem_response(
            f"Refused. On `/api`: an unsafe request without the `X-Requested-With: {brand.CSRF_HEADER_VALUE}` header or from another site; a route "
            "for admins (`Admins only`); the password must be entered again (`reauth_required`) or changed first (`password_change_required`). "
            "On `/mcp`, `/push/v1/body` and `/push/v1/check`: a foreign `Origin` header."
        ),
        "NotFound": _problem_response(
            "The record does not exist or is not the signed-in person's (the two look the same), or the feature is switched off on this server "
            "(the AI routes while the AI is off, `/mcp` while assistant access is off)."
        ),
        "Conflict": _problem_response(
            "The change clashes with what is stored or with a server rule: a name taken, the last admin, a setting fixed by the server's "
            "environment, a consent the person has not given yet, a list that is full."
        ),
        "PayloadTooLarge": _problem_response("The request body is larger than this route allows (`MAX_BODY_BYTES` or the route's own limit)."),
        "UnsupportedMediaType": _problem_response(
            "The body is not the type the route reads (JSON, `image/jpeg`, a recording, `export.json`); `detail` names it."
        ),
        "TooManyRequests": _problem_response(
            "Too many requests (a rate limit, a sign-in throttle, or a quota). Wait `Retry-After` seconds.", headers=retry
        ),
        "MethodNotAllowed": _problem_response("This path offers POST only.", headers=allow),
        "Error": _problem_response(
            "Any other error. Every error answer has the `Problem` shape: a `detail` sentence, and possibly more keys. Treat an unlisted status "
            "as an error with this body."
        ),
    }


def _security_schemes() -> dict[str, Any]:
    return {
        SESSION: {
            "type": "apiKey",
            "in": "cookie",
            "name": brand.SESSION_COOKIE,
            "description": (
                f"The signed-in person's session cookie: `{brand.SESSION_COOKIE_HOST}` when the server is reached over HTTPS, `{brand.SESSION_COOKIE}` over plain HTTP "
                "(each name is read only on its own scheme; this scheme lists the plain name because OpenAPI allows one). `POST /api/auth/login` "
                "sets it (HttpOnly, SameSite=Lax; 30 days at most, 14 days idle) and `POST /api/auth/logout` ends it. With `AUTH_MODE=proxy` the "
                "identity comes from the trusted proxy's header instead, and with `AUTH_MODE=none` nobody signs in.\n\n"
                f"**Every unsafe request (POST, PUT, PATCH, DELETE) to `/api` must also send the header `X-Requested-With: {brand.CSRF_HEADER_VALUE}`**, and an "
                "`Origin` it sends must be the server's own; without the header the answer is 403. A request that carries only a bearer token "
                "(either kind) is anonymous on `/api`: a token is never a sign-in here."
            ),
        },
        ASSISTANT_TOKEN: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": f"{brand.ASSISTANT_TOKEN_PREFIX} followed by 43 characters",
            "description": (
                f"An assistant access token (`Authorization: Bearer {brand.ASSISTANT_TOKEN_PREFIX}...`), made in Settings, Assistant access, with the scope `assistant:read` and "
                "optionally `assistant:log`. It works only at `/mcp`, and only while the instance switch `assistant.enabled` is on. No cookie is "
                "read there, and the cookie checks of `/api` do not apply."
            ),
        },
        DEVICE_TOKEN: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": f"{brand.DEVICE_TOKEN_PREFIX} followed by 43 characters",
            "description": (
                f"A device token (`Authorization: Bearer {brand.DEVICE_TOKEN_PREFIX}...`), made in Settings, Phone shortcuts, with the one scope `body:write`. It works only at "
                "`POST /push/v1/body` (and `GET /push/v1/check`, which tests it), only while the instance switch `push.enabled` is on, and it can add "
                "weights and blood pressure readings and read nothing. No cookie is read there."
            ),
        },
    }


# --------------------------------------------------------------------------- #
# Reading the routes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Facts:
    """What the routes themselves say about one operation (read from FastAPI's dependency tree, not guessed from the path)."""

    session: bool  # ``current_user`` is somewhere in its dependencies: a signed-in person, or 401
    ai_gated: bool  # ``require_ai_enabled``: 404 while ``ai.enabled`` is off
    path_params: bool  # the path names a record: 404 when it is not found or not yours


def _dependency_calls(dependant: Any) -> set[Callable[..., Any]]:
    seen: set[Callable[..., Any]] = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        for sub in node.dependencies:
            if sub.call is not None:
                seen.add(sub.call)
            stack.append(sub)
    return seen


def _needs_session(calls: set[Callable[..., Any]]) -> bool:
    return current_user in calls


def route_facts(app: FastAPI) -> dict[tuple[str, str], Facts]:
    """``{(method, path): Facts}`` for every route in the schema."""
    out: dict[tuple[str, str], Facts] = {}
    for ctx in fastapi_routing.iter_route_contexts(app.routes):
        if not isinstance(ctx.original_route, fastapi_routing.APIRoute) or not ctx.include_in_schema:
            continue
        calls = _dependency_calls(ctx.dependant)
        facts = Facts(session=_needs_session(calls), ai_gated=require_ai_enabled in calls, path_params=bool(ctx.dependant.path_params))
        for method in ctx.methods or ():
            out[(method.lower(), ctx.path_format)] = facts
    return out


# --------------------------------------------------------------------------- #
# Rewriting the document
# --------------------------------------------------------------------------- #


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _ref_response(name: str) -> dict[str, str]:
    return {"$ref": _REF + "responses/" + name}


def _drop_validation_422(responses: dict[str, Any]) -> bool:
    """Remove the 422 FastAPI adds for request validation (its schema is ``HTTPValidationError``); True when there was one."""
    found = responses.get("422")
    if found is None:
        return False
    schema = (((found.get("content") or {}).get("application/json") or {}).get("schema")) or {}
    if schema.get("$ref") == _REF + "schemas/HTTPValidationError":
        del responses["422"]
        return True
    return False  # a 422 the route declares itself


def _statuses(method: str, path: str, opid: str, facts: Facts | None, had_validation: bool) -> dict[str, str]:
    """``{status: shared response}`` this operation is known to answer, from the structure of the app."""
    bearer = BEARER_OPERATIONS.get((method, path))
    api = _is_api(path)
    wanted: dict[str, str] = {}
    session = bool(facts and facts.session)
    if had_validation:
        wanted["400"] = "BadRequest"  # request validation, and the route's own 400s
    if session:
        wanted["401"] = "Unauthorized"
    elif bearer:
        wanted["401"] = "BearerUnauthorized"
    elif opid in UNAUTHORIZED_PUBLIC:
        wanted["401"] = "Unauthorized"
    if bearer or session or (api and method in UNSAFE_METHODS):
        wanted["403"] = "Forbidden"  # the CSRF header and Origin checks cover every unsafe /api call, signed in or not
    if facts is not None and (facts.path_params or facts.ai_gated):
        wanted["404"] = "NotFound"
    elif path == "/mcp":
        wanted["404"] = "NotFound"
    if opid in CONFLICT:
        wanted["409"] = "Conflict"
    if method in BODY_METHODS and (api or bearer):
        wanted["413"] = "PayloadTooLarge"
    if opid in UNSUPPORTED_MEDIA:
        wanted["415"] = "UnsupportedMediaType"
    if opid in RATE_LIMITED:
        wanted["429"] = "TooManyRequests"
    return wanted


def _document_operation(op: dict[str, Any], method: str, path: str, facts: Facts | None) -> None:
    responses: dict[str, Any] = op.setdefault("responses", {})
    had_validation = _drop_validation_422(responses)
    opid = op["operationId"]
    bearer = BEARER_OPERATIONS.get((method, path))

    if opid.endswith(NOT_ALLOWED_SUFFIX):  # the 405 stubs of /mcp and /push/v1: FastAPI shows their code path's 200
        op["responses"] = {"405": _ref_response("MethodNotAllowed")}
        if path == "/mcp":
            op["responses"]["404"] = _ref_response("NotFound")
        return

    if facts is not None and facts.session:
        op["security"] = [{SESSION: []}]
    elif bearer:
        op["security"] = [{bearer: []}]

    for status, name in _statuses(method, path, opid, facts, had_validation).items():
        responses.setdefault(status, _ref_response(name))
    if opid == "push_body":
        responses.setdefault("400", _ref_response("BadRequest"))  # raw body: no FastAPI validation, the route's own strict reader
    if opid == "mcp_post":
        responses.setdefault("400", {"description": "The message is not one JSON-RPC 2.0 request object.",
                                     "content": {"application/json": {"schema": {"$ref": _REF + "schemas/JsonRpcError"}}}})

    for status, response in list(responses.items()):  # a route's own declaration keeps its words and gains the shared shape
        if not status.isdigit() or int(status) < 400 or "$ref" in response or "content" in response:
            continue
        if status == "412":
            schema = "EntryConflictProblem"
        elif status == "400" and had_validation:
            schema = "ValidationProblem"  # the route words its own 400s; a bad field is still the validation body
        else:
            schema = "Problem"
        response["content"] = {"application/json": {"schema": {"$ref": _REF + "schemas/" + schema}}}
        if status == "429" and "headers" not in response:
            response["headers"] = copy.deepcopy(_RETRY_AFTER)

    if (_is_api(path) or bearer) and path != "/mcp":  # /mcp's own errors are JSON-RPC objects, not problems
        responses.setdefault("default", _ref_response("Error"))
    op["responses"] = dict(sorted(responses.items(), key=lambda item: (not item[0].isdigit(), item[0])))


def _unreferenced(doc: dict[str, Any], schema: str) -> bool:
    return f'"{_REF}schemas/{schema}"' not in json.dumps(doc["paths"]) + json.dumps(doc["components"].get("responses", {}))


def build_document(app: FastAPI, base: dict[str, Any]) -> dict[str, Any]:
    """``base`` (what FastAPI generated) rewritten as described in the module docstring. ``base`` is not changed."""
    doc = copy.deepcopy(base)
    info = doc["info"]
    info["x-api-version"] = API_VERSION
    info["description"] = (
        f"{info.get('description', '').rstrip()}\n\n"
        "This document is checked in as `docs/api/openapi.json`. `info.version` is the app's version; `info.x-api-version` is the API version, an "
        "integer that is raised only for a breaking change. Every error answer is `{\"detail\": string, ...}`; request validation is **400** "
        "with `errors`, never 422. Sign in with `POST /api/auth/login` (a cookie, see the `session` scheme); `/mcp` and `/push/v1/body` take bearer tokens."
    ).strip()
    components = doc.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.update(_schemas())
    components["responses"] = _responses()
    components["securitySchemes"] = _security_schemes()

    facts = route_facts(app)
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method in HTTP_METHODS:
                _document_operation(op, method, path, facts.get((method, path)))

    for name in ("HTTPValidationError", "ValidationError"):  # FastAPI's 422 body, now unused
        if name in schemas and _unreferenced(doc, name):
            del schemas[name]
    doc["components"]["schemas"] = {k: schemas[k] for k in sorted(schemas)}
    return doc


def install(app: FastAPI) -> None:
    """Make ``app.openapi()`` return the rewritten document (cached like FastAPI's own)."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            raw = original()  # FastAPI's own document (it caches it as app.openapi_schema; replaced just below)
            app.openapi_schema = build_document(app, raw)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
