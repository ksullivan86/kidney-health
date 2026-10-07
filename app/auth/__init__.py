"""Accounts, sessions and per-user access (note 07; ARCHITECTURE.md v0.3 contract).

* :mod:`app.auth.deps` - ``current_user``, ``CurrentUser``, ``require_admin``, ``AdminUser``,
  ``require_recent_auth`` (the fixed identity interface).
* :mod:`app.auth.routes` (``/api/auth``), :mod:`app.auth.me` (``/api/me``),
  :mod:`app.auth.admin_api` (``/api/admin``).
* :mod:`app.auth.passwords`, :mod:`app.auth.policy`, :mod:`app.auth.sessions`,
  :mod:`app.auth.throttle`, :mod:`app.auth.proxy`, :mod:`app.auth.tokens`,
  :mod:`app.auth.ratelimit`, :mod:`app.auth.bootstrap`.

:func:`install` wires it into an app: the shared state (``app.state.auth``), the routers and the
error handler for ``{"detail", "reauth_required" | "setup_required" | ...}`` responses.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .context import AuthContext
from .errors import ApiProblem, api_problem_handler

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

    from ..config import Settings
    from ..settings_store import SettingsStore


def install(app: "FastAPI", settings: "Settings", store: "SettingsStore") -> AuthContext:
    from . import admin_api, me, routes

    ctx = AuthContext(settings=settings, store=store)
    app.state.auth = ctx
    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.include_router(routes.router)
    app.include_router(me.router)
    app.include_router(admin_api.router)
    return ctx


__all__ = ["ApiProblem", "AuthContext", "install"]
