"""FastAPI application factory.

``uvicorn app.main:app --host 0.0.0.0 --port 8000`` serves the API and the static
frontend. Tests call :func:`create_app` with their own :class:`Settings`.
"""
from __future__ import annotations

import base64
import binascii
import logging
import math
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from . import foods, log as log_router, meals, profile
from .config import Settings, load_settings
from .db import connect, get_db, init_db

logger = logging.getLogger("kidney_health")

STATIC_DIR = Path(__file__).resolve().parent / "static"
AUTH_REALM = "kidney-health"
# Liveness/readiness probes cannot carry a secret, so the health check stays open.
AUTH_EXEMPT_PATHS = frozenset({"/healthz"})


class BasicAuthMiddleware:
    """Pure-ASGI HTTP Basic auth: any username, one shared password."""

    def __init__(self, app: ASGIApp, password: str, realm: str = AUTH_REALM, exempt: frozenset[str] = AUTH_EXEMPT_PATHS):
        self.app = app
        self._password = password.encode("utf-8")
        self.realm = realm
        self.exempt = exempt

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
        if scope["type"] != "http" or scope.get("path") in self.exempt:
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


def _json_safe_float(value: float) -> float | str:
    """NaN/Infinity are not JSON; echo them as text so the error body itself can be serialised."""
    return value if math.isfinite(value) else str(value)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Flatten Pydantic errors to ``{"detail": "<message>"}`` with status 400 (contract error shape)."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path"))
        msg = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    # The raw ``input`` (and ``ctx``) can hold NaN/Infinity or an exception object; keep only the
    # JSON-safe parts so a bad number yields the contract's 400 instead of a 500 while rendering.
    errors = [
        {k: v for k, v in err.items() if k in ("type", "loc", "msg", "input")}
        for err in exc.errors()
    ]
    body = {"detail": "; ".join(parts) or "invalid request", "errors": jsonable_encoder(errors, custom_encoder={float: _json_safe_float})}
    return JSONResponse(body, status_code=400)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_data_dir()
        applied = init_db(settings.db_path)
        if applied:
            logger.info("database schema migrated to version %d (steps %s)", applied[-1], applied)
        conn = connect(settings.db_path)
        try:
            result = foods.import_builtin_foods(conn, settings.foods_json)
            app.state.foods_import = result
        finally:
            conn.close()
        logger.info("database %s ready; builtin foods: %s", settings.db_path, result.get("status"))
        yield

    app = FastAPI(
        title="Kidney Health Food Log",
        version="0.2.0",
        description="Self-hosted food log with renal-diet and type 1 diabetes nutrient warnings, meal planning and period summaries.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    if settings.app_password:
        app.add_middleware(BasicAuthMiddleware, password=settings.app_password)

    app.include_router(profile.router)
    app.include_router(foods.router)
    app.include_router(log_router.router)
    app.include_router(meals.router)
    app.include_router(meals.plan_router)

    @app.get("/healthz")
    def healthz(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
        count = conn.execute("SELECT COUNT(*) FROM foods WHERE hidden = 0").fetchone()[0]
        return {"status": "ok", "foods": int(count)}

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:  # pragma: no cover - frontend not checked out
        logger.warning("static directory %s missing; only the API is served", STATIC_DIR)

    return app


app = create_app()
