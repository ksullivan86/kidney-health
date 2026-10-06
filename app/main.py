"""FastAPI application factory.

``uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`` serves the API and the
static frontend (``X-Forwarded-*`` are handled by :mod:`app.security` from ``TRUSTED_PROXIES``,
so uvicorn must not apply them too). Tests call :func:`create_app` with their own
:class:`Settings`.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError

from . import auth, crypto, foods, log as log_router, meals, profile, pwa, security
from . import labs  # M2 targets: /api/labs
from .guidance import api as guidance_api  # M2 guidance: /api/guidance
from .guidance import api as guidance_api  # M2 guidance: /api/guidance
from . import handbook  # M3: the handbook at /learn and /api/handbook
from .auth import bootstrap as auth_bootstrap
from .config import DEFAULT_STATIC_DIR, ConfigError, Settings, load_settings
from .db import connect, get_db, init_db, table_exists
from .settings_store import SettingsStore, default_store

logger = logging.getLogger("kidney_health")

APP_VERSION = "0.3.0.dev0"
STATIC_DIR = DEFAULT_STATIC_DIR


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
        auth_ctx.keyring = app.state.keyring
        conn = connect(settings.db_path)
        try:
            result = foods.import_builtin_foods(conn, settings.foods_json)
            app.state.foods_import = result
            _startup_maintenance(conn, store)
            try:
                auth_bootstrap.startup(conn, auth_ctx)
            except auth_bootstrap.StartupError as exc:
                logger.error("start-up stopped: %s", exc)
                raise
        finally:
            conn.close()
        logger.info("database %s ready; builtin foods: %s", settings.db_path, result.get("status"))
        yield

    docs = settings.docs_enabled
    app = FastAPI(
        title="Kidney Health Food Log",
        version=APP_VERSION,
        description="Self-hosted food log with renal-diet and type 1 diabetes nutrient warnings, meal planning and period summaries.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.settings_store = store
    app.add_exception_handler(RequestValidationError, security.validation_error_handler)
    auth_ctx = auth.install(app, settings, store)  # /api/auth, /api/me, /api/admin + error handler

    # Middleware: added innermost first (security.install adds the outer stack last).
    pwa.setup(app, settings)  # GET /sw.js (before the static mount) + gzip for static files
    learn = handbook.setup(app, settings)  # the built handbook, or None (/learn is then 404)
    security.install(app, settings, path_policies=handbook.csp_policies(learn))  # /learn's own CSP

    app.include_router(profile.router)
    app.include_router(foods.router)
    app.include_router(log_router.router)
    app.include_router(meals.router)
    app.include_router(meals.plan_router)
    app.include_router(labs.router)
    app.include_router(guidance_api.router)
    app.include_router(guidance_api.router)
    app.include_router(handbook.router)

    @app.get("/healthz")
    def healthz(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
        # Public: counts only the shared builtin foods (nothing about anybody's own data).
        count = conn.execute("SELECT COUNT(*) FROM foods WHERE hidden = 0 AND source = 'builtin'").fetchone()[0]
        return {"status": "ok", "foods": int(count)}

    handbook.mount(app, learn)  # before the "/" mount
    pwa.mount_static(app, settings)
    return app


try:
    app = create_app()
except ConfigError as _exc:  # a clean message instead of a traceback from `uvicorn app.main:app`
    raise SystemExit(f"kidney-health: configuration error: {_exc}") from None
