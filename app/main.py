"""FastAPI application factory.

``uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`` serves the API and the
static frontend (``X-Forwarded-*`` are handled by :mod:`app.security` from ``TRUSTED_PROXIES``,
so uvicorn must not apply them too). Tests call :func:`create_app` with their own
:class:`Settings`.
"""
from __future__ import annotations

import base64
import binascii
import logging
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from . import crypto, foods, log as log_router, meals, profile, pwa, security
from .config import DEFAULT_STATIC_DIR, ConfigError, Settings, load_settings
from .db import connect, get_db, init_db, table_exists
from .settings_store import SettingsStore, default_store

logger = logging.getLogger("kidney_health")

STATIC_DIR = DEFAULT_STATIC_DIR
AUTH_REALM = "kidney-health"
# Liveness/readiness probes cannot carry a secret, so the health check stays open; the PWA
# manifest, icons and /sw.js are public too (note 02 R6). See app.pwa.is_public_path.
AUTH_EXEMPT_PATHS = pwa.PUBLIC_PATHS


class BasicAuthMiddleware:
    """Pure-ASGI HTTP Basic auth: any username, one shared password (v0.2; replaced by accounts in v0.3)."""

    def __init__(
        self,
        app: ASGIApp,
        password: str,
        realm: str = AUTH_REALM,
        is_exempt: Callable[[str], bool] = pwa.is_public_path,
    ):
        self.app = app
        self._password = password.encode("utf-8")
        self.realm = realm
        self.is_exempt = is_exempt

    def _authorised(self, header: str | None) -> bool:
        if not header:
            return False
        scheme, _, param = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            decoded = base64.b64decode(param.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        _, _, password = decoded.partition(":")
        return secrets.compare_digest(password.encode("utf-8"), self._password)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.is_exempt(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if self._authorised(Headers(scope=scope).get("authorization")):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{self.realm}"'},
        )
        await response(scope, receive, send)


def _startup_maintenance(conn: sqlite3.Connection, store: SettingsStore) -> None:
    """Housekeeping that needs schema v3 tables; skipped on older databases."""
    if table_exists(conn, "audit_log"):
        from .audit import purge_expired

        removed = purge_expired(conn, int(store.get(conn, "audit.retention_days")))
        conn.commit()
        if removed:
            logger.info("audit log: removed %d entries past the retention period", removed)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    warnings = tuple(dict.fromkeys((*settings.warnings, *settings.validate())))
    if not logging.getLogger().handlers:
        logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    security.install_log_redaction(settings.secret_values())
    store = default_store()  # env locks from os.environ; shared with app.settings_store's module functions
    store.validate_env_locks()  # a bad INSTANCE_NAME / REGISTRATION_MODE / ... fails at start-up

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        for warning in warnings:
            logger.warning("configuration: %s", warning)
        settings.ensure_data_dir()
        app.state.keyring = crypto.load_keyring(settings)
        applied = init_db(settings.db_path)
        if applied:
            logger.info("database schema migrated to version %d (steps %s)", applied[-1], applied)
        conn = connect(settings.db_path)
        try:
            result = foods.import_builtin_foods(conn, settings.foods_json)
            app.state.foods_import = result
            _startup_maintenance(conn, store)
        finally:
            conn.close()
        logger.info("database %s ready; builtin foods: %s", settings.db_path, result.get("status"))
        yield

    docs = settings.docs_enabled
    app = FastAPI(
        title="Kidney Health Food Log",
        version="0.2.0",
        description="Self-hosted food log with renal-diet and type 1 diabetes nutrient warnings, meal planning and period summaries.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.settings_store = store
    app.add_exception_handler(RequestValidationError, security.validation_error_handler)

    # Middleware: added innermost first (security.install adds the outer stack last).
    if settings.app_password:
        app.add_middleware(BasicAuthMiddleware, password=settings.app_password)
    pwa.setup(app, settings)  # GET /sw.js (before the static mount) + gzip for static files
    security.install(app, settings)

    app.include_router(profile.router)
    app.include_router(foods.router)
    app.include_router(log_router.router)
    app.include_router(meals.router)
    app.include_router(meals.plan_router)

    @app.get("/healthz")
    def healthz(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
        count = conn.execute("SELECT COUNT(*) FROM foods WHERE hidden = 0").fetchone()[0]
        return {"status": "ok", "foods": int(count)}

    pwa.mount_static(app, settings)
    return app


try:
    app = create_app()
except ConfigError as _exc:  # a clean message instead of a traceback from `uvicorn app.main:app`
    raise SystemExit(f"kidney-health: configuration error: {_exc}") from None
