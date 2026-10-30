"""FastAPI identity dependencies (note 07 §4.10; fixed names in ARCHITECTURE.md v0.3 item 3).

* :func:`current_user` / :data:`CurrentUser`: the signed-in, active person, from the session cookie
  (``AUTH_MODE=local``), the trusted proxy header (``proxy``) or user 1 (``none``). Anonymous → 401;
  before first-run setup → 503 ``{"setup_required": true}``; while ``must_change_password`` is set
  every route except ``POST /api/me/password`` and ``POST /api/auth/logout`` → 403
  ``{"password_change_required": true}`` (§9 N8).
* :func:`require_admin` / :data:`AdminUser`: ``role == 'admin'`` or 403. With ``auth.require_two_step_admins`` on (env
  ``AUTH_REQUIRE_TWO_STEP_ADMINS``, design note 17 §10) a local admin in ``AUTH_MODE=local`` also needs two-step sign-in on, or 403
  ``{"two_step_required": true}``; the person can still use the app and turn it on under ``/api/me/totp``.
* :func:`require_recent_auth`: the password was entered within ``REAUTH_MINUTES`` on this session,
  or 403 ``{"reauth_required": true}``. Proxy and no-login modes have no local password: the
  identity provider (or nobody) is responsible, so it passes there.

Every data router declares ``dependencies=[Depends(current_user)]`` and every handler that touches
data takes ``user: CurrentUser`` and passes ``user.id`` explicitly. Not found and not yours are
both 404.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import Depends, Request

from ..db import get_db
from . import housekeeping, proxy, sessions, totp
from .context import AuthContext, auth_context
from .errors import ApiProblem, password_change_required, reauth_required, setup_required, sign_in_required
from .models import User, load_user, setup_required as needs_setup, user_row

# Routes a person with ``must_change_password`` may still call (GET /api/auth/status is public).
PASSWORD_CHANGE_EXEMPT = frozenset({("POST", "/api/me/password"), ("POST", "/api/auth/logout")})


def _none_mode_user(conn: sqlite3.Connection) -> User:
    row = user_row(conn, 1)
    if row is None:
        raise ApiProblem(503, "User 1 is missing; restart the server to create it again (AUTH_MODE=none)")
    return User(
        id=1,
        username=row["username"] or "local",
        role="admin",
        status="active",
        display_name=row["display_name"] or None,
        auth_source="local",
        must_change_password=False,
        can_use_shared=bool(row["can_use_shared"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def _session_user(request: Request, conn: sqlite3.Connection, ctx: AuthContext) -> User | None:
    s = ctx.settings
    info = sessions.validate(conn, sessions.read_token(request), idle_days=s.session_idle_days)
    if info is None:
        return None
    user = load_user(conn, info.user_id)
    if user is None or user.auth_source != "local":
        return None
    request.state.auth_session = info
    return user


def ensure_setup_done(conn: sqlite3.Connection, ctx: AuthContext) -> None:
    if ctx.settings.auth_mode == "none" or ctx.setup_complete:
        return
    if needs_setup(conn):
        raise setup_required()
    ctx.setup_complete = True


def identify(request: Request, conn: sqlite3.Connection) -> User | None:
    """The person behind this request, or None (no checks on status or setup)."""
    ctx = auth_context(request)
    mode = ctx.settings.auth_mode
    request.state.auth_session = None
    if mode == "none":
        return _none_mode_user(conn)
    if mode == "proxy":
        return proxy.user_from_request(request, conn, ctx)
    return _session_user(request, conn, ctx)


def current_user(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> User:
    ctx = auth_context(request)
    ensure_setup_done(conn, ctx)
    housekeeping.run(conn, ctx)
    user = identify(request, conn)
    if user is None or not user.is_active:
        raise sign_in_required()
    if user.must_change_password and (request.method.upper(), request.url.path) not in PASSWORD_CHANGE_EXEMPT:
        raise password_change_required()
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(current_user)]


TWO_STEP_SETTING = "auth.require_two_step_admins"
TWO_STEP_FIRST = ("This server asks admins to use two-step sign-in. Turn it on in Settings → Account → Two-step sign-in, "
                  "then open Server administration again.")


def two_step_required(ctx: AuthContext, conn: sqlite3.Connection, user: User, request: Request | None = None) -> bool:
    """Whether this admin must turn on two-step sign-in before using admin routes: the switch is on, sign-in is local, and the
    account signs in with a password. The sign-in proxy (or no sign-in) is responsible for its own second factor, and so is the
    sign-in provider for a session it started (``sessions.signed_in_with = 'oidc'``, design note 24 §9)."""
    if ctx.settings.auth_mode != "local" or user.auth_source != "local":
        return False
    info = getattr(request.state, "auth_session", None) if request is not None else None
    if info is not None and getattr(info, "signed_in_with", None) == "oidc":
        return False
    return bool(ctx.store.get(conn, TWO_STEP_SETTING))


def require_admin(user: CurrentUser, request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]) -> User:
    if user.role != "admin":
        raise ApiProblem(403, "Admins only")
    if two_step_required(auth_context(request), conn, user, request) and not totp.is_enabled(conn, user.id):
        raise ApiProblem(403, TWO_STEP_FIRST, two_step_required=True)
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def require_recent_auth(user: CurrentUser, request: Request) -> User:
    ctx = auth_context(request)
    if ctx.settings.auth_mode != "local":
        return user
    info = getattr(request.state, "auth_session", None)
    if not sessions.reauth_is_recent(info, ctx.settings.reauth_minutes):
        raise reauth_required()
    return user


RecentUser = Annotated[User, Depends(require_recent_auth)]


def require_recent_admin(user: AdminUser, request: Request) -> User:
    return require_recent_auth(user, request)


RecentAdmin = Annotated[User, Depends(require_recent_admin)]
