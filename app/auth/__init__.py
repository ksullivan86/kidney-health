"""Accounts, sessions and per-user access (note 07; ARCHITECTURE.md v0.3 contract).

* :mod:`app.auth.deps` - ``current_user``, ``CurrentUser``, ``require_admin``, ``AdminUser``,
  ``require_recent_auth`` (the fixed identity interface).
* :mod:`app.auth.routes` (``/api/auth``), :mod:`app.auth.me` (``/api/me``),
  :mod:`app.auth.admin_api` (``/api/admin``), :mod:`app.auth.api_tokens` (``/api/me/tokens`` and the
  bearer dependency ``AssistantUser``, the only place an ``Authorization`` header is read),
  :mod:`app.auth.totp_api` (``/api/me/totp``, two-step sign-in; the codes are :mod:`app.auth.totp`).
  :mod:`app.auth.passkeys_api` (``/api/me/passkeys``, ``/api/auth/passkey``; the checks are :mod:`app.auth.webauthn`).
  :mod:`app.auth.oidc_api` (``/api/auth/oidc``, ``/api/me/oidc``: sign-in with a provider; the client is :mod:`app.auth.oidc`).
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
    from . import admin_api, api_tokens, me, oidc, oidc_api, passkeys_api, routes, totp_api

    ctx = AuthContext(settings=settings, store=store)
    app.state.auth = ctx
    # Every sign-in provider (design note 24 §13), in order, sharing one flow store: each gets an equal share of it.
    providers = settings.oidc.all()
    flows = oidc.FlowStore(per_provider=oidc.MAX_FLOWS // max(1, len(providers)))
    clients = [oidc.OidcClient(p, settings.public_origin, flows=flows) for p in providers]
    app.state.oidc_providers = {c.id: c for c in clients if c.enabled}
    app.state.oidc = clients[0] if clients else oidc.OidcClient(settings.oidc, settings.public_origin, flows=flows)
    app.add_exception_handler(ApiProblem, api_problem_handler)
    app.include_router(routes.router)
    app.include_router(me.router)
    app.include_router(totp_api.router)
    app.include_router(passkeys_api.me_router)
    app.include_router(passkeys_api.auth_router)
    app.include_router(passkeys_api.reauth_router)
    app.include_router(oidc_api.router)
    app.include_router(oidc_api.reauth_router)
    app.include_router(oidc_api.me_router)
    app.include_router(api_tokens.router)
    app.include_router(admin_api.router)
    return ctx


__all__ = ["ApiProblem", "AuthContext", "install"]
