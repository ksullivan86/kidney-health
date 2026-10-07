"""Installable-app plumbing on the server (note 02 R4 and R6).

* ``GET /sw.js`` serves ``app/static/sw.js`` with ``__VERSION__`` replaced by the first 12 hex
  digits of a SHA-256 over every file in ``app/static`` (computed once at start-up), so a new
  release changes ``sw.js`` byte for byte and the browser picks up the update. ``Cache-Control:
  no-cache``. With ``PWA_ENABLED=false`` it serves a kill-switch worker that deletes the app's
  caches, unregisters itself and reloads open pages (the documented recovery for a bad release).
* :class:`ShellStaticFiles` (the ``/`` mount) sets the content types and cache headers of R6:
  manifest ``application/manifest+json`` + ``no-cache``; icons, ``apple-touch-icon.png`` and
  ``/vendor/`` ``public, max-age=604800``; the HTML/JS/CSS shell ``no-cache`` (revalidate with
  the ETag, so a page and its scripts always come from the same release).
* :func:`is_public_path` lists what needs no sign-in: the health check, the manifest, icons and
  ``/sw.js`` (iOS fetches the icon at install time, before any session exists).
* :class:`StaticGZipMiddleware` gzips static responses (not ``/api``) of 1 KiB or more.
* :class:`ApiVersionMiddleware` puts ``X-KDL-Version: <shell version>`` (the same hash as ``/sw.js``)
  on every ``/api`` response (note 02 §5 and §6 item 9): a page running a cached shell that is
  older than the server sees the difference and asks its service worker for the update, which shows
  the "Update ready · Reload" toast (``js/core.js`` → ``KH.pwa.versionSeen``).
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings

log = logging.getLogger("kidney_health.pwa")

# Deterministic types whatever /etc/mime.types says (the runtime image may not have one).
for _type, _ext in (
    ("application/manifest+json", ".webmanifest"),
    ("application/wasm", ".wasm"),
    ("text/javascript", ".js"),
    ("text/javascript", ".mjs"),
    ("image/svg+xml", ".svg"),
    ("image/png", ".png"),
    ("text/css", ".css"),
):
    mimetypes.add_type(_type, _ext)

SW_TEMPLATE = "sw.js"
VERSION_PLACEHOLDER = "__VERSION__"
VERSION_LENGTH = 12
VERSION_HEADER = "X-KDL-Version"

MANIFEST_PATH = "/manifest.webmanifest"
MANIFEST_TYPE = "application/manifest+json"
JS_TYPE = "text/javascript; charset=utf-8"
LONG_CACHE = "public, max-age=604800"
NO_CACHE = "no-cache"

PUBLIC_PATHS = frozenset({"/healthz", "/sw.js", MANIFEST_PATH, "/apple-touch-icon.png"})
PUBLIC_PREFIXES: tuple[str, ...] = ("/icons/",)
LONG_CACHE_PATHS = frozenset({"/apple-touch-icon.png"})
LONG_CACHE_PREFIXES: tuple[str, ...] = ("/icons/", "/vendor/")
_SHELL_SUFFIXES = (".html", ".js", ".mjs", ".css")

KILL_SWITCH_SW = """\
// PWA_ENABLED=false on the server: remove this app's caches and service worker, then reload open pages.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('kdl-')) await caches.delete(key);
    }
    await self.registration.unregister();
    for (const client of await self.clients.matchAll({ type: 'window' })) client.navigate(client.url);
  })());
});
"""


def is_public_path(path: str) -> bool:
    """Paths that never require a signed-in user (note 02 R6, note 07 §4.10)."""
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def _shell_files(static_dir: Path) -> list[Path]:
    files = []
    for path in static_dir.rglob("*"):
        rel = path.relative_to(static_dir)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda p: p.relative_to(static_dir).as_posix())


def shell_version(static_dir: Path) -> str:
    """First 12 hex digits of SHA-256 over every static file (relative path and bytes)."""
    digest = hashlib.sha256()
    if static_dir.is_dir():
        for path in _shell_files(static_dir):
            digest.update(path.relative_to(static_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:VERSION_LENGTH]


@dataclass(frozen=True)
class PwaState:
    enabled: bool
    version: str
    service_worker: bytes | None  # None: no sw.js template (404)


def build_state(settings: Settings) -> PwaState:
    static_dir = Path(settings.static_dir)
    version = shell_version(static_dir)
    if not settings.pwa_enabled:
        return PwaState(enabled=False, version=version, service_worker=KILL_SWITCH_SW.encode("utf-8"))
    template = static_dir / SW_TEMPLATE
    try:
        text = template.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.info("no %s in %s; /sw.js answers 404", SW_TEMPLATE, static_dir)
        return PwaState(enabled=True, version=version, service_worker=None)
    if VERSION_PLACEHOLDER not in text:
        log.warning("%s has no %s placeholder; browsers will not see new releases", template, VERSION_PLACEHOLDER)
    return PwaState(enabled=True, version=version, service_worker=text.replace(VERSION_PLACEHOLDER, version).encode("utf-8"))


router = APIRouter(tags=["pwa"])


@router.get("/sw.js")
def service_worker(request: Request) -> Response:
    """The service worker, versioned by the shell hash (or the kill switch when PWA_ENABLED=false)."""
    state: PwaState = request.app.state.pwa
    if state.service_worker is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(
        content=state.service_worker,
        media_type="text/javascript",
        headers={"Content-Type": JS_TYPE, "Cache-Control": NO_CACHE},
    )


def cache_headers_for(path: str) -> dict[str, str]:
    """Headers the static mount adds for ``path`` (note 02 R6)."""
    if path == MANIFEST_PATH:
        return {"Content-Type": MANIFEST_TYPE, "Cache-Control": NO_CACHE}
    if path in LONG_CACHE_PATHS or path.startswith(LONG_CACHE_PREFIXES):
        return {"Cache-Control": LONG_CACHE}
    if path == "/" or path.endswith(_SHELL_SUFFIXES):
        headers = {"Cache-Control": NO_CACHE}
        if path.endswith((".js", ".mjs")):
            headers["Content-Type"] = JS_TYPE
        return headers
    return {}


class ShellStaticFiles(StaticFiles):
    """``StaticFiles`` with the PWA content types and cache headers."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            for name, value in cache_headers_for(scope.get("path", "/")).items():
                response.headers[name] = value
        return response


class StaticGZipMiddleware:
    """gzip for everything except ``/api`` (no compression of personal data responses)."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if scope["type"] != "http" or path == "/api" or path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        await self.gzip(scope, receive, send)


class ApiVersionMiddleware:
    """``X-KDL-Version`` on every ``/api`` response (errors included), so a cached shell can tell that
    the server runs a newer release than the one it was loaded from (note 02 §5)."""

    def __init__(self, app: ASGIApp, version: str) -> None:
        self.app = app
        self.header = (VERSION_HEADER.lower().encode("latin-1"), version.encode("latin-1"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if scope["type"] != "http" or not (path == "/api" or path.startswith("/api/")):
            await self.app(scope, receive, send)
            return

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != self.header[0]]
                message = {**message, "headers": [*headers, self.header]}
            await send(message)

        await self.app(scope, receive, send_with_version)


def setup(app: FastAPI, settings: Settings) -> PwaState:
    """Compute the service worker once, register ``/sw.js`` (before the static mount), gzip, and the
    ``X-KDL-Version`` header on API responses."""
    state = build_state(settings)
    app.state.pwa = state
    app.include_router(router)
    app.add_middleware(StaticGZipMiddleware)
    app.add_middleware(ApiVersionMiddleware, version=state.version)
    return state


def mount_static(app: FastAPI, settings: Settings) -> bool:
    """Mount the frontend at ``/`` (last, so API routes and ``/sw.js`` win)."""
    static_dir = Path(settings.static_dir)
    if not static_dir.is_dir():
        log.warning("static directory %s missing; only the API is served", static_dir)
        return False
    app.mount("/", ShellStaticFiles(directory=str(static_dir), html=True), name="static")
    return True
