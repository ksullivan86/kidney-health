"""HTTP security layer: pure-ASGI middlewares, the validation-error handler and log redaction.

Spec: ``docs/dev/research/01-rootless-and-security.md`` §3.7, §5.5 and §10 (S1-S4), and
``07-accounts-settings-secrets.md`` §4.8 and §9 (N1, N4, N10). :func:`install` registers the stack;
the outermost middleware comes first:

1. :class:`SecurityHeadersMiddleware` - CSP and the other headers on **every** response, including
   the rejections below, 404s and unhandled 500s; ``Cache-Control: no-store`` on ``/api``; HSTS and
   ``upgrade-insecure-requests`` only when the effective scheme is https. One policy everywhere,
   except the API docs (``ENABLE_API_DOCS``) and path prefixes given to :func:`install` as
   ``path_policies`` (the handbook at ``/learn``, :mod:`app.handbook`).
2. :class:`PeerCaptureMiddleware` - the real TCP peer in ``scope["state"]["peer"]``.
3. :class:`HostAllowlistMiddleware` - DNS-rebinding defence: ``localhost``, any IP literal, the host
   of ``PUBLIC_URL`` and ``ALLOWED_HOSTS`` names; anything else is ``400 Unknown host``.
4. :class:`TrustedProxyMiddleware` - ``X-Forwarded-For``/``-Proto`` (via uvicorn's
   ``ProxyHeadersMiddleware``) and the identity headers count only from ``TRUSTED_PROXIES`` and,
   when ``TRUSTED_PROXY_SECRET`` is set, only with a matching ``X-Proxy-Secret`` (which is always
   removed). Run uvicorn with ``--no-proxy-headers`` so this happens exactly once.
5. :class:`BodyLimitMiddleware` - ``413`` above ``MAX_BODY_BYTES`` (``Content-Length`` or counted
   while streaming); prefixes registered with :func:`register_body_limit` use a larger setting.
6. :class:`CsrfMiddleware` - ``Sec-Fetch-Site``/``Origin`` checks on unsafe methods, the required
   ``X-Requested-With: kidney-health`` on unsafe ``/api`` requests, and no cross-site or same-site
   reads of ``/api`` at all.

Request state other code may read (``request.state.<name>``): ``peer`` (TCP peer), ``client_ip``
(after trusted proxy handling), ``scheme`` (effective scheme), ``proxy_trusted`` (bool).
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import re
import threading
from typing import Any, Iterable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import Settings, normalize_origin

log = logging.getLogger("kidney_health.security")

# --------------------------------------------------------------------------- #
# Policy constants
# --------------------------------------------------------------------------- #

CSP_DIRECTIVES: tuple[str, ...] = (
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "style-src 'self'",
    "img-src 'self' blob:",
    "connect-src 'self'",
    "font-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "require-trusted-types-for 'script'",
    # One named policy, created once by the service-worker registration code and allowing only
    # '/sw.js' (note 01 §10 S3). Never add 'allow-duplicates' or a 'default' policy.
    "trusted-types kh-sw",
)
CONTENT_SECURITY_POLICY = "; ".join(CSP_DIRECTIVES)

# Swagger UI and ReDoc load from a CDN and use inline script; only these paths get this policy, and
# only when ENABLE_API_DOCS=true.
DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
DOCS_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly",
        "font-src 'self' https://fonts.gstatic.com",
        "worker-src 'self' blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

STATIC_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "kidney-health"
PROXY_SECRET_HEADER = "X-Proxy-Secret"
_FORWARDING_HEADERS = frozenset(
    {b"x-forwarded-for", b"x-forwarded-proto", b"x-forwarded-host", b"x-forwarded-port", b"x-real-ip", b"forwarded"}
)


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


# --------------------------------------------------------------------------- #
# Request-state helpers (for app/auth and friends)
# --------------------------------------------------------------------------- #


def scope_state(scope: Scope) -> dict[str, Any]:
    state = scope.get("state")
    if state is None:
        state = scope["state"] = {}
    return state


def peer_ip(scope: Scope) -> str | None:
    """The real TCP peer (captured before any proxy handling)."""
    state = scope_state(scope)
    if "peer" in state:
        return state["peer"]
    client = scope.get("client")
    return client[0] if client else None


def client_ip(scope: Scope) -> str | None:
    """The client address after trusted-proxy handling (use this for per-IP limits)."""
    state = scope_state(scope)
    if "client_ip" in state:
        return state["client_ip"]
    client = scope.get("client")
    return client[0] if client else None


def effective_scheme(scope: Scope) -> str:
    return scope_state(scope).get("scheme") or scope.get("scheme") or "http"


def is_loopback(address: str | None) -> bool:
    if not address:
        return False
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def request_is_secure(scope: Scope) -> bool:
    """https (after trusted proxy handling), or a loopback client. Used for ALLOW_INSECURE_HTTP."""
    return effective_scheme(scope) == "https" or is_loopback(client_ip(scope))


def _json_response(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


class SecurityState:
    """Facts the admin About page shows (note 01 §10 S2, note 07 R1). One per app."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.first_forwarded_peer: str | None = None
        self.ignored_identity_headers = 0
        self.last_ignored_identity_peer: str | None = None
        self.rejected_hosts = 0
        self._warned_hosts: set[str] = set()
        self._warned_origin = False

    def note_forwarded(self, peer: str | None) -> None:
        with self._lock:
            if self.first_forwarded_peer is not None:
                return
            self.first_forwarded_peer = peer or "?"
        log.info("first request with X-Forwarded-For came from trusted proxy %s", peer)

    def note_ignored_identity(self, peer: str | None) -> None:
        with self._lock:
            self.ignored_identity_headers += 1
            first = self.ignored_identity_headers == 1
            self.last_ignored_identity_peer = peer
        if first:
            log.warning(
                "ignored an identity header from %s: the peer is not in TRUSTED_PROXIES or X-Proxy-Secret did not match",
                peer,
            )

    def note_rejected_host(self, host: str) -> bool:
        """Count a rejection; True when this host should be logged (first time, bounded)."""
        with self._lock:
            self.rejected_hosts += 1
            if host in self._warned_hosts or len(self._warned_hosts) >= 100:
                return False
            self._warned_hosts.add(host)
            return True

    def note_origin_mismatch(self) -> bool:
        with self._lock:
            if self._warned_origin:
                return False
            self._warned_origin = True
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "first_forwarded_peer": self.first_forwarded_peer,
                "ignored_identity_headers": self.ignored_identity_headers,
                "last_ignored_identity_peer": self.last_ignored_identity_peer,
                "rejected_hosts": self.rejected_hosts,
            }


# --------------------------------------------------------------------------- #
# Middlewares
# --------------------------------------------------------------------------- #


class SecurityHeadersMiddleware:
    """Adds the CSP and the other security headers to every HTTP response.

    ``path_policies`` is a sequence of ``(prefix, policy)``: a request for ``prefix`` itself or for
    anything below ``prefix + "/"`` gets ``policy`` instead of :data:`CONTENT_SECURITY_POLICY`. Every
    other header is the same on every path.
    """

    def __init__(self, app: ASGIApp, settings: Settings, path_policies: Iterable[tuple[str, str]] = ()) -> None:
        self.app = app
        self.hsts_max_age = settings.hsts_max_age
        self.docs_enabled = settings.docs_enabled
        self.path_policies = tuple(path_policies)
        for prefix, _policy in self.path_policies:
            if not prefix.startswith("/") or prefix.endswith("/") or is_api_path(prefix):
                raise ValueError(f"path policy prefix {prefix!r} must start with '/', not end with '/' and not be under /api")

    def policy_for(self, path: str) -> str:
        """The Content-Security-Policy for ``path`` (before ``upgrade-insecure-requests``)."""
        if self.docs_enabled and path in DOCS_PATHS:
            return DOCS_CONTENT_SECURITY_POLICY
        for prefix, policy in self.path_policies:
            if path == prefix or path.startswith(prefix + "/"):
                return policy
        return CONTENT_SECURITY_POLICY

    def _apply(self, headers: MutableHeaders, scope: Scope) -> None:
        path = scope.get("path", "")
        https = effective_scheme(scope) == "https"
        csp = self.policy_for(path)
        if https:
            csp += "; upgrade-insecure-requests"
        headers["Content-Security-Policy"] = csp
        for name, value in STATIC_HEADERS:
            headers[name] = value
        if https and self.hsts_max_age > 0:
            headers["Strict-Transport-Security"] = f"max-age={self.hsts_max_age}"
        if is_api_path(path):
            headers["Cache-Control"] = "no-store"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                self._apply(MutableHeaders(scope=message), scope)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            # The framework's own 500 page is rendered outside this middleware; answer here so the
            # error page carries the headers too, then let the server log the exception.
            if not started:
                await PlainTextResponse("Internal Server Error", status_code=500)(scope, receive, send_with_headers)
            raise


class PeerCaptureMiddleware:
    """Stores the TCP peer in ``scope["state"]["peer"]`` before anything rewrites ``scope["client"]``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _unmap(host: str) -> str:
        """``::ffff:192.0.2.1`` (an IPv4 client on a dual-stack socket) → ``192.0.2.1``."""
        if ":" not in host:
            return host
        try:
            mapped = ipaddress.IPv6Address(host).ipv4_mapped
        except ValueError:
            return host
        return str(mapped) if mapped is not None else host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            if client and client[0]:
                unmapped = self._unmap(client[0])
                if unmapped != client[0]:
                    client = scope["client"] = (unmapped, client[1])
            state = scope_state(scope)
            state["peer"] = client[0] if client else None
            state.setdefault("client_ip", state["peer"])
            state.setdefault("scheme", scope.get("scheme", "http"))
        await self.app(scope, receive, send)


def split_host_header(value: str) -> str | None:
    """``Host`` header → lower-case host without port (IPv6 without brackets); None if malformed."""
    value = value.strip().lower()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        host, rest = value[1:end], value[end + 1 :]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        try:
            return str(ipaddress.IPv6Address(host))
        except ValueError:
            return None
    if value.count(":") > 1:
        return None  # an IPv6 literal must be bracketed in Host
    host, _, port = value.partition(":")
    if port and not port.isdigit():
        return None
    host = host.rstrip(".")
    return host or None


class HostPolicy:
    """``localhost``, any IP literal, the ``PUBLIC_URL`` host and the ``ALLOWED_HOSTS`` names."""

    def __init__(self, settings: Settings) -> None:
        names = {h.lower().rstrip(".") for h in settings.allowed_hosts}
        self.allow_all = "*" in names
        names.discard("*")
        self.wildcards = tuple(n[1:] for n in names if n.startswith("*."))  # ".example.org"
        self.names = {n for n in names if not n.startswith("*.")} | {"localhost"}
        if settings.public_host:
            self.names.add(settings.public_host)

    def allows(self, host: str | None) -> bool:
        if host is None:
            return False
        if self.allow_all:
            return True
        try:
            ipaddress.ip_address(host)
            return True  # rebinding needs a DNS name; IP literals are safe
        except ValueError:
            pass
        return host in self.names or any(host.endswith(suffix) for suffix in self.wildcards)


class HostAllowlistMiddleware:
    """DNS-rebinding defence (note 01 §10 S1): unknown ``Host`` → ``400 {"detail": "Unknown host"}``."""

    def __init__(self, app: ASGIApp, settings: Settings, state: SecurityState | None = None) -> None:
        self.app = app
        self.policy = HostPolicy(settings)
        self.state = state or SecurityState()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        raw = Headers(scope=scope).get("host", "")
        host = split_host_header(raw)
        if self.policy.allows(host):
            await self.app(scope, receive, send)
            return
        shown = (host or raw)[:100]
        if self.state.note_rejected_host(shown):
            log.warning(
                "refused a request for unknown host %r; if this is your server's name, add it to ALLOWED_HOSTS "
                "(or set PUBLIC_URL)",
                shown,
            )
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await _json_response(400, "Unknown host")(scope, receive, send)


class TrustedProxyMiddleware:
    """Applies ``X-Forwarded-*`` and keeps identity headers only from trusted proxies (note 01 §5.5, §10 S2)."""

    def __init__(self, app: ASGIApp, settings: Settings, state: SecurityState | None = None) -> None:
        self.app = app
        self.state = state or SecurityState()
        self.networks = tuple(ipaddress.ip_network(p, strict=False) for p in settings.trusted_proxies)
        self.secret = settings.trusted_proxy_secret.encode("utf-8") if settings.trusted_proxy_secret else None
        self.identity_headers = frozenset(
            h.lower().encode("latin-1")
            for h in (settings.trusted_proxy_user_header, settings.trusted_proxy_groups_header, settings.trusted_proxy_name_header)
            if h
        )
        self.proxy = ProxyHeadersMiddleware(self._after_proxy, trusted_hosts=[str(n) for n in self.networks])

    def is_trusted_peer(self, address: str | None) -> bool:
        if not address:
            return False
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        return any(ip in net for net in self.networks)

    async def _after_proxy(self, scope: Scope, receive: Receive, send: Send) -> None:
        state = scope_state(scope)
        client = scope.get("client")
        state["client_ip"] = client[0] if client else None
        state["scheme"] = scope.get("scheme", "http")
        await self.app(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        peer = peer_ip(scope)
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        trusted = self.is_trusted_peer(peer)
        if trusted and self.secret is not None:
            supplied = next((v for k, v in headers if k == b"x-proxy-secret"), None)
            trusted = supplied is not None and hmac.compare_digest(supplied, self.secret)
        kept: list[tuple[bytes, bytes]] = []
        ignored_identity = False
        forwarded = False
        for name, value in headers:
            if name == b"x-proxy-secret":
                continue
            if name in _FORWARDING_HEADERS:
                if not trusted:
                    continue
                forwarded = forwarded or name == b"x-forwarded-for"
            if name in self.identity_headers and not trusted:
                ignored_identity = True
                continue
            kept.append((name, value))
        if len(kept) != len(headers):
            scope["headers"] = kept
        scope_state(scope)["proxy_trusted"] = trusted
        if ignored_identity:
            self.state.note_ignored_identity(peer)
        if forwarded:
            self.state.note_forwarded(peer)
        await self.proxy(scope, receive, send)


class BodyTooLarge(StarletteHTTPException):
    """Raised from ``receive()`` when the streamed body passes the limit. It is an HTTPException so
    FastAPI's body parser re-raises it (as 413) instead of turning it into a 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request body too large")


# Path prefixes with their own (larger) limit: (prefix, Settings attribute). Photo routes register
# themselves here with "max_image_bytes" (note 03 R8, note 01 §10 S5).
_BODY_LIMIT_OVERRIDES: list[tuple[str, str]] = []


def register_body_limit(prefix: str, setting: str = "max_image_bytes") -> None:
    """Give requests under ``prefix`` the limit in ``Settings.<setting>`` instead of ``MAX_BODY_BYTES``."""
    if not prefix.startswith("/"):
        raise ValueError("prefix must start with '/'")
    if setting not in Settings.__dataclass_fields__:
        raise ValueError(f"unknown setting {setting!r}")
    entry = (prefix, setting)
    if entry not in _BODY_LIMIT_OVERRIDES:
        _BODY_LIMIT_OVERRIDES.append(entry)
        _BODY_LIMIT_OVERRIDES.sort(key=lambda e: len(e[0]), reverse=True)


class BodyLimitMiddleware:
    """``413`` when a request body exceeds its limit (declared ``Content-Length`` or counted bytes)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    def limit_for(self, path: str) -> int:
        for prefix, setting in _BODY_LIMIT_OVERRIDES:
            if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                return int(getattr(self.settings, setting))
        return self.settings.max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("path", ""))
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            try:
                size = int(declared)
                if size < 0:
                    raise ValueError
            except ValueError:
                await _json_response(400, "Invalid Content-Length header")(scope, receive, send)
                return
            if size > limit:
                await _json_response(413, "Request body too large")(scope, receive, send)
                return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if started:
                raise
            await _json_response(413, "Request body too large")(scope, receive, tracking_send)


class CsrfMiddleware:
    """CSRF and cross-site read checks (note 01 §5.5, note 07 §4.8 and §9 N10, note 01 §10 S4)."""

    def __init__(self, app: ASGIApp, settings: Settings, state: SecurityState | None = None) -> None:
        self.app = app
        self.public_origin = settings.public_origin
        self.state = state or SecurityState()

    def request_origin(self, scope: Scope, headers: Headers) -> str | None:
        host = headers.get("host")
        if not host:
            return None
        try:
            return normalize_origin(f"{effective_scheme(scope)}://{host.strip()}")
        except ValueError:
            return None

    def origin_allowed(self, origin: str, scope: Scope, headers: Headers) -> bool:
        if origin.strip().lower() == "null":
            return False
        try:
            normalized = normalize_origin(origin.strip())
        except ValueError:
            return False
        if not normalized.startswith(("http://", "https://")) or normalized.endswith("://"):
            return False
        own = self.request_origin(scope, headers)
        if normalized == own or (self.public_origin is not None and normalized == self.public_origin):
            return True
        if own and self.state.note_origin_mismatch():
            log.warning(
                "refused a write from Origin %s (this request's own origin is %s). If that is your own site "
                "behind a reverse proxy, set PUBLIC_URL to it or list the proxy in TRUSTED_PROXIES",
                normalized,
                own,
            )
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        headers = Headers(scope=scope)
        api = is_api_path(path)
        site = headers.get("sec-fetch-site")
        if site is not None:
            site = site.strip().lower()
        if api and site in ("cross-site", "same-site"):
            await _json_response(403, "Cross-site request refused")(scope, receive, send)
            return
        if method in UNSAFE_METHODS:
            if site is not None and site != "same-origin":
                await _json_response(403, "Cross-site request refused")(scope, receive, send)
                return
            origin = headers.get("origin")
            if origin is not None and not self.origin_allowed(origin, scope, headers):
                await _json_response(403, "Cross-site request refused")(scope, receive, send)
                return
            if api and headers.get("x-requested-with") != CSRF_HEADER_VALUE:
                await _json_response(403, f"Missing {CSRF_HEADER} header")(scope, receive, send)
                return
        await self.app(scope, receive, send)


def install(app: FastAPI, settings: Settings, *, path_policies: Iterable[tuple[str, str]] = ()) -> SecurityState:
    """Register the middleware stack (call after any inner middleware such as auth).

    ``path_policies``: ``(prefix, Content-Security-Policy)`` pairs for path prefixes that need their
    own policy (see :class:`SecurityHeadersMiddleware`); everything else gets the app's policy.
    """
    state = SecurityState()
    app.state.security = state
    # add_middleware puts the last one outermost.
    app.add_middleware(CsrfMiddleware, settings=settings, state=state)
    app.add_middleware(BodyLimitMiddleware, settings=settings)
    app.add_middleware(TrustedProxyMiddleware, settings=settings, state=state)
    app.add_middleware(HostAllowlistMiddleware, settings=settings, state=state)
    app.add_middleware(PeerCaptureMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings, path_policies=tuple(path_policies))
    return state


# --------------------------------------------------------------------------- #
# Validation errors (note 07 §9 N4)
# --------------------------------------------------------------------------- #

# Request fields that carry secrets. Models declare them as pydantic.SecretStr; their validation
# errors are reported without any value-derived message.
SECRET_FIELD_NAMES = frozenset(
    {"password", "current_password", "new_password", "api_key", "token", "code", "setup_code", "secret"}
)


def _is_secret_loc(loc: Iterable[Any]) -> bool:
    return any(isinstance(part, str) and part.lower() in SECRET_FIELD_NAMES for part in loc)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Flatten Pydantic errors to ``{"detail": "<message>", "errors": [{type, loc, msg}]}`` with status 400.

    The offending ``input`` and ``ctx`` are never echoed (a password, API key or setup code could
    be in them), so the body is always JSON-serialisable.
    """
    detail, errors = flatten_validation_errors(exc.errors())
    return JSONResponse({"detail": detail, "errors": errors}, status_code=400)


def flatten_validation_errors(raw: Iterable[Any]) -> tuple[str, list[dict[str, Any]]]:
    """``("field: message; ...", [{type, loc, msg}])`` for Pydantic errors, as the 400 handler words them (also used
    for the per-row reasons of ``POST /api/labs/import``)."""
    parts: list[str] = []
    errors: list[dict[str, Any]] = []
    for err in raw:
        loc = tuple(err.get("loc", ()))
        name = ".".join(str(x) for x in loc if x not in ("body", "query", "path"))
        kind = str(err.get("type", "value_error"))
        msg = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
        if _is_secret_loc(loc) and kind in ("value_error", "assertion_error"):
            msg = "invalid value"
        msg = redact(msg)
        parts.append(f"{name}: {msg}" if name else msg)
        errors.append({"type": kind, "loc": [p if isinstance(p, (str, int)) else str(p) for p in loc], "msg": msg})
    return "; ".join(parts) or "invalid request", errors


# --------------------------------------------------------------------------- #
# Log redaction (note 07 §9 N4)
# --------------------------------------------------------------------------- #

REDACTED = "[redacted]"
_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()
_SECRET_MIN_LENGTH = 6
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 " + REDACTED),
    (
        re.compile(r"(?i)\b(x-api-key|x-proxy-secret|api[_-]?key|password|passwd|secret|token)(\s*[=:]\s*)([^\s&,;\"']+)"),
        r"\1\2" + REDACTED,
    ),
)
HTTP_CLIENT_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore2", "h11")


def register_secret(value: str | None) -> None:
    """Make every later log line replace ``value`` with ``[redacted]`` (short values are ignored)."""
    if value and len(value) >= _SECRET_MIN_LENGTH:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    with _SECRETS_LOCK:
        secrets = sorted(_SECRETS, key=len, reverse=True)
    for value in secrets:
        if value in text:
            text = text.replace(value, REDACTED)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Rewrites a record's message, arguments and traceback text with :func:`redact`."""

    def filter(self, record: logging.LogRecord) -> bool:
        _redact_record(record)
        return True


def _redact_record(record: logging.LogRecord) -> None:
    try:
        original = record.getMessage()
    except Exception:  # a broken format string is not ours to fix here
        return
    if redact(original) != original:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: (redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
        try:
            still = record.getMessage()
        except Exception:
            still = original
        if redact(still) != still:
            record.msg, record.args = redact(still), ()
    if record.exc_info and not record.exc_text:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    if record.exc_text:
        record.exc_text = redact(record.exc_text)


_FACTORY_INSTALLED = False


def install_log_redaction(secrets: Iterable[str | None] = ()) -> None:
    """Redact registered secrets and bearer tokens in every log record; pin HTTP client loggers to WARNING."""
    global _FACTORY_INSTALLED
    for value in secrets:
        register_secret(value)
    if not _FACTORY_INSTALLED:
        previous = logging.getLogRecordFactory()

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = previous(*args, **kwargs)
            _redact_record(record)
            return record

        logging.setLogRecordFactory(factory)
        _FACTORY_INSTALLED = True
    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
