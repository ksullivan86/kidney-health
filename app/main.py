"""FastAPI application factory.

``uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers`` serves the API and the
static frontend (``X-Forwarded-*`` are handled by :mod:`app.security` from ``TRUSTED_PROXIES``,
so uvicorn must not apply them too). Tests call :func:`create_app` with their own
:class:`Settings`.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError

from . import brand
from . import auth, crypto, foods, log as log_router, meals, profile, pwa, security
from . import labs  # M2 targets: /api/labs
from . import symptoms  # schema step 15: /api/symptoms
from . import body  # schema step 18: /api/body (weight and blood pressure)
from . import push  # schema step 19: POST /push/v1/body (device tokens) and DELETE /api/me/tokens/{id}/body-rows
from .guidance import api as guidance_api  # M2 guidance: /api/guidance
from . import handbook  # M3: the handbook at /learn and /api/handbook
from . import barcode  # M2 barcode: POST /api/foods/barcode
from . import vision  # M2 ai: POST /api/vision/label, /api/vision/plate
from .ai import voice as ai_voice  # assistant step 2, part B: POST /api/ai/transcribe
from .ai import routes as ai_routes  # M2 ai: /api/ai, /api/me/ai, /api/admin/ai-providers
from . import mcp as assistant_mcp  # assistant step 1: POST /mcp, the MCP server for a chat assistant
from . import data_import  # POST /api/me/import: the person's own export.json (own body limit, MAX_IMPORT_BYTES)
from . import meta  # design note 14 change 4: GET /api/meta (versions, capabilities, the nutrient registry)
from . import sharing  # schema step 24: read-only sharing with a caregiver or dietitian (/api/me/shares, /api/shared)
from . import feedback, test_accounts  # schema step 28: test accounts, Send feedback (/api/feedback, /api/admin/feedback)
from .devices import api as devices_api, sync as devices_sync  # schema step 29: connected devices (/api/devices)
from . import openapi_doc  # design note 14 change 2: stable operation ids, honest errors and security schemes in the OpenAPI document
from .auth import bootstrap as auth_bootstrap
from .config import DEFAULT_STATIC_DIR, ConfigError, Settings, load_settings
from .db import connect, get_db, init_db, table_exists
from .settings_store import SettingsStore, default_store

logger = logging.getLogger(brand.LOGGER_NAME)

APP_VERSION = "0.15.0"
STATIC_DIR = DEFAULT_STATIC_DIR


def _initial_settings(conn: sqlite3.Connection, store: SettingsStore) -> None:
    """Write the first values of SETTINGS_INITIAL_ONLY once (note 20), each with an audit row."""
    from .audit import audit_if_available

    for key, old, new in store.apply_initial(conn):
        env = store.definition(key).env
        audit_if_available(conn, None, "settings.changed", target_type="setting", target_id=key, key=key, old=old, new=new, env=env)
        logger.info("setting %s: first value from %s", key, env)
    conn.commit()


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
            _initial_settings(conn, store)
            _startup_maintenance(conn, store)
            ai_routes.startup(app, conn)  # M2 ai: env provider row, AI activity retention
            try:
                auth_bootstrap.startup(conn, auth_ctx)
            except auth_bootstrap.StartupError as exc:
                logger.error("start-up stopped: %s", exc)
                raise
            try:  # design note 26: make, enable or disable the test accounts; a problem is logged, never stops the start
                test_accounts.sync(conn, settings, store)
            except Exception:
                conn.rollback()
                logger.exception("test accounts: could not be brought in line with TEST_ACCOUNT_ENABLED")
        finally:
            conn.close()
        logger.info("database %s ready; builtin foods: %s", settings.db_path, result.get("status"))
        # Design note 27: fetch from connected devices every few hours, in a worker thread (it does nothing while off).
        devices_task = asyncio.create_task(devices_sync.loop(app))
        try:
            yield
        finally:
            devices_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await devices_task

    docs = settings.docs_enabled
    app = FastAPI(
        title=f"{brand.NAME} Food Log",
        version=APP_VERSION,
        description="Self-hosted food log with renal-diet and type 1 diabetes nutrient warnings, meal planning and period summaries.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        generate_unique_id_function=openapi_doc.operation_id,
    )
    openapi_doc.install(app)  # app.openapi(): the rewritten document (docs/api/openapi.json is made from it)
    app.state.settings = settings
    app.state.settings_store = store
    app.state.devices = devices_sync.Devices(settings)  # design note 27: the providers (tests swap in a fake Withings)
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
    app.include_router(symptoms.router)
    app.include_router(body.router)
    app.include_router(guidance_api.router)
    app.include_router(handbook.router)
    app.include_router(barcode.router)
    ai_routes.install(app, settings, store, app_version=APP_VERSION)  # M2 ai: checks the AI env, adds its routers
    app.include_router(vision.router)
    app.include_router(vision.lab_router)
    app.include_router(ai_voice.router)
    app.include_router(ai_voice.admin_router)
    app.include_router(assistant_mcp.router)
    app.include_router(push.router)  # bearer-only like /mcp, outside /api
    app.include_router(push.api_router)
    app.include_router(data_import.router)
    app.include_router(meta.router)
    app.include_router(sharing.me_router)
    app.include_router(sharing.shared_router)
    app.include_router(feedback.router)
    app.include_router(feedback.admin_router)
    app.include_router(devices_api.router)

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
    raise SystemExit(f"{brand.SLUG}: configuration error: {_exc}") from None
