"""``/api/me/*``: the signed-in person's account, devices, settings, keys, usage, activity, export
and deletion (note 07 §4.11, §4.12, §4.14, §4.16). Every route acts on ``user.id`` only."""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from .. import account, credentials
from ..audit import USER_VISIBLE_ACTIONS, audit, list_events
from ..db import get_db, utcnow
from ..settings_store import InvalidSettingValue, SettingLocked, SettingNotEditable, SettingsUnavailable
from . import clock, sessions, tokens
from .accounts import (
    PasswordRejected,
    begin_immediate,
    check_new_password,
    hash_password,
    lock_account,
    password_problem,
    set_password,
    verify_password,
    would_remove_last_admin,
)
from .context import AuthContext, auth_context, request_ip
from .deps import CurrentUser, RecentUser, current_user
from .errors import ApiProblem, too_many
from .models import USER_COLUMNS, User, clean_display, load_user, me_dict
from .routes import start_session
from .schemas import DeleteMeBody, KeyPut, MePatch, PasswordChangeBody
from .throttle import HARD_STOP, REAUTH_MAX_FAILURES

router = APIRouter(prefix="/api/me", tags=["me"], dependencies=[Depends(current_user)])

USAGE_DAYS = 30


# --------------------------------------------------------------------------- #
# Account
# --------------------------------------------------------------------------- #


@router.get("")
def read_me(user: CurrentUser) -> dict[str, Any]:
    return me_dict(user)


@router.patch("")
def update_me(body: MePatch, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    conn.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?", (clean_display(body.display_name), utcnow(), user.id))
    conn.commit()
    return me_dict(load_user(conn, user.id))


def check_own_password(request: Request, conn: sqlite3.Connection, ctx: AuthContext, user: User, password: str) -> None:
    """Verify the person's own password, counting failures like ``/api/auth/reauth`` (§9 N7)."""
    th = ctx.throttle
    ip = request_ip(request)
    wait = th.ip_wait(ip)
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user.id,)).fetchone()
    mac = th.name_mac(row["username_norm"])
    wait = wait or th.username_wait(conn, mac)
    if wait:
        raise too_many(wait)
    if verify_password(password, row["password_hash"]):
        th.forget(conn, mac)
        info = getattr(request.state, "auth_session", None)
        if info is not None:
            th.reauth_reset(info.id)
        return
    th.ip_failure(ip)
    count = th.record_failure(conn, mac)
    audit(conn, user.id, "login.failed", "user", user.id, ip=ip, via="password_check")
    if count >= HARD_STOP:
        lock_account(conn, user.id, ip=ip)
    info = getattr(request.state, "auth_session", None)
    if info is not None and th.reauth_failure(info.id) >= REAUTH_MAX_FAILURES:
        sessions.revoke(conn, info.id, user.id)
        audit(conn, user.id, "session.revoked_reauth", "user", user.id, ip=ip)
        conn.commit()
        th.reauth_reset(info.id)
        raise ApiProblem(401, "Signed out after too many wrong passwords. Sign in again.")
    conn.commit()
    raise ApiProblem(403, "That password is not right.", field="current_password")


@router.post("/password")
def change_password(body: PasswordChangeBody, request: Request, response: Response, user: CurrentUser,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Needs the current password (OWASP); signs out every other device and renews this session."""
    ctx = auth_context(request)
    if ctx.settings.auth_mode != "local" or user.auth_source != "local":
        raise HTTPException(status_code=404, detail="Not Found")
    check_own_password(request, conn, ctx, user, body.current_password.get_secret_value())
    new = body.new_password.get_secret_value()
    try:
        check_new_password(ctx, conn, new, username=user.username, display_name=user.display_name or "")
    except PasswordRejected as exc:
        raise password_problem(exc) from None
    set_password(conn, user.id, hash_password(new))
    sessions.revoke_user_sessions(conn, user.id)
    tokens.void_reset_links(conn, user.id)  # an older reset link must not undo this change
    start_session(request, response, conn, ctx, user.id)  # rotate: a new id for this device
    audit(conn, user.id, "user.password_changed", "user", user.id, ip=request_ip(request), via="self")
    conn.commit()
    return {"user": me_dict(load_user(conn, user.id))}


@router.delete("", status_code=204, response_class=Response)
def delete_me(request: Request, user: CurrentUser, body: DeleteMeBody = Body(...),
              conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Delete the account and everything it owns (needs the password and ``"confirm": "DELETE"``)."""
    ctx = auth_context(request)
    if ctx.settings.auth_mode == "none":
        # Every request is user 1 here, so deleting it would leave the server unusable (it answers 503
        # until user 1 exists again). The data can be removed entry by entry, or the database replaced.
        raise ApiProblem(
            409,
            "This server runs without sign-in (AUTH_MODE=none), so there is no personal account to delete.",
        )
    if body.confirm != "DELETE":
        raise ApiProblem(400, 'Type DELETE to confirm.', field="confirm")
    if ctx.settings.auth_mode == "local":
        if body.password is None:
            raise ApiProblem(403, "Please enter your password again", reauth_required=True)
        check_own_password(request, conn, ctx, user, body.password.get_secret_value())
    begin_immediate(conn)  # the last-admin check and the delete see the same data
    if would_remove_last_admin(conn, user.id):
        raise ApiProblem(409, "You are the only admin. Make someone else an admin first.")
    account.delete_user(conn, user.id, actor_id=user.id, ip=request_ip(request))
    response = Response(status_code=204)
    sessions.clear_cookies(response, request)
    response.headers["Clear-Site-Data"] = '"cache", "storage"'
    return response


# --------------------------------------------------------------------------- #
# Signed-in devices
# --------------------------------------------------------------------------- #


def _current_session_id(request: Request) -> str | None:
    info = getattr(request.state, "auth_session", None)
    return info.id if info is not None else None


@router.get("/sessions")
def list_my_sessions(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"sessions": sessions.list_sessions(conn, user.id, current_id=_current_session_id(request))}


@router.delete("/sessions/{session_id}", status_code=204, response_class=Response)
def revoke_my_session(session_id: str, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    if len(session_id) > 64 or not sessions.revoke(conn, session_id, user.id):
        raise HTTPException(status_code=404, detail="session not found")
    audit(conn, user.id, "sessions.revoked", "user", user.id, ip=request_ip(request), count=1)
    conn.commit()
    response = Response(status_code=204)
    if session_id == _current_session_id(request):
        sessions.clear_cookies(response, request)
    return response


@router.post("/sessions/revoke-others")
def revoke_other_sessions(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    count = sessions.revoke_user_sessions(conn, user.id, except_id=_current_session_id(request))
    audit(conn, user.id, "sessions.revoked", "user", user.id, ip=request_ip(request), count=count)
    conn.commit()
    return {"revoked": count}


# --------------------------------------------------------------------------- #
# Settings (note 07 §4.11)
# --------------------------------------------------------------------------- #


def settings_error(exc: Exception) -> ApiProblem:
    if isinstance(exc, KeyError):
        return ApiProblem(400, str(exc.args[0]) if exc.args else "unknown setting")
    if isinstance(exc, SettingLocked):
        return ApiProblem(409, str(exc), locked_by_env=exc.env)
    if isinstance(exc, SettingNotEditable):
        return ApiProblem(403, str(exc))
    if isinstance(exc, InvalidSettingValue):
        return ApiProblem(400, str(exc))
    if isinstance(exc, SettingsUnavailable):
        return ApiProblem(503, "Settings are not available yet")
    raise exc


@router.get("/settings")
def read_my_settings(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"settings": auth_context(request).store.user_view(conn, user.id)}


@router.patch("/settings")
def update_my_settings(request: Request, user: CurrentUser, body: dict[str, Any] = Body(...),
                       conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    store = auth_context(request).store
    try:
        view = store.update_user(conn, user.id, body)
    except (KeyError, SettingLocked, SettingNotEditable, InvalidSettingValue, SettingsUnavailable) as exc:
        conn.rollback()
        raise settings_error(exc) from None
    conn.commit()
    return {"settings": view}


# --------------------------------------------------------------------------- #
# Keys (note 07 §4.12): write-only
# --------------------------------------------------------------------------- #


def provider_or_404(provider: str) -> credentials.Provider:
    try:
        return credentials.get_provider(provider)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider[:40]!r}") from None


def _setting(ctx: AuthContext, conn: sqlite3.Connection, p: credentials.Provider, name: str, default: Any) -> Any:
    if not p.settings_prefix:
        return default
    try:
        return ctx.store.get(conn, f"{p.settings_prefix}.{name}")
    except KeyError:
        return default


def key_item(conn: sqlite3.Connection, ctx: AuthContext, user: User, p: credentials.Provider) -> dict[str, Any]:
    keyring = ctx.require_keyring()
    allowed = bool(_setting(ctx, conn, p, "user_keys_allowed", True))
    own = credentials.secret_status(conn, keyring, p.slug, owner_user_id=user.id)
    shared_set = bool(credentials.env_secret(ctx.settings, p.slug)) or credentials.secret_status(
        conn, keyring, p.slug, owner_user_id=None
    ).get("set", False)
    shared_on = shared_set and bool(_setting(ctx, conn, p, "shared_enabled", True)) and user.can_use_shared
    limit = int(_setting(ctx, conn, p, "daily_limit_per_user", 0) or 0)
    remaining = None if not limit else max(0, limit - credentials.used_today(conn, user.id, p.slug, "shared"))
    if allowed and own.get("set") and own.get("status") != "unreadable":
        effective = "own"
    elif shared_on and (remaining is None or remaining > 0):
        effective = "shared"
    else:
        effective = "none"
    return {
        "provider": p.slug,
        "label": p.label,
        "own": own,
        "shared": {"available": shared_on, "remaining_today": remaining, "daily_limit": limit or None},
        "user_keys_allowed": allowed,
        "effective": effective,
    }


def run_key_test(ctx: AuthContext, p: credentials.Provider, fields: dict[str, str], limiter_key: Any) -> str | None:
    if p.tester is None:
        return None
    ctx.limits.take("keys_test", limiter_key)
    try:
        return p.tester(fields)
    except Exception:  # a broken upstream never turns into a 500 here
        return "unreachable"


@router.get("/keys")
def read_my_keys(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    return {"providers": [key_item(conn, ctx, user, p) for p in credentials.PROVIDERS.values()]}


@router.put("/keys/{provider}")
def set_my_key(provider: str, body: KeyPut, request: Request, user: RecentUser,
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    p = provider_or_404(provider)
    if not _setting(ctx, conn, p, "user_keys_allowed", True):
        raise ApiProblem(403, "Your admin has turned off personal keys for this provider.")
    fields = {"api_key": body.api_key.get_secret_value()}
    try:
        credentials.validate_api_key(fields["api_key"])
    except credentials.InvalidCredential as exc:
        raise ApiProblem(400, f"api_key: {exc}", field="api_key") from None
    test = run_key_test(ctx, p, fields, f"user:{user.id}") if body.test else None
    credentials.store_secret(conn, ctx.require_keyring(), p.slug, fields, owner_user_id=user.id, updated_by=user.id)
    audit(conn, user.id, "secret.set", "secret", p.slug, ip=request_ip(request), provider=p.slug, scope="user")
    conn.commit()
    item = key_item(conn, ctx, user, p)
    if test is not None:
        item["test"] = test
    return item


@router.delete("/keys/{provider}", status_code=204, response_class=Response)
def delete_my_key(provider: str, request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    p = provider_or_404(provider)
    if credentials.delete_secret(conn, p.slug, owner_user_id=user.id):
        audit(conn, user.id, "secret.removed", "secret", p.slug, ip=request_ip(request), provider=p.slug, scope="user")
        conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Usage, activity, export
# --------------------------------------------------------------------------- #


@router.get("/usage")
def read_my_usage(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    today = credentials.today()
    since = (clock.now() - timedelta(days=USAGE_DAYS - 1)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT provider, key_scope, day, requests FROM usage_daily WHERE user_id = ? AND day >= ?
           ORDER BY day DESC, provider, key_scope""",
        (user.id, since),
    ).fetchall()
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        item = totals.setdefault((r["provider"], r["key_scope"]), {"provider": r["provider"], "scope": r["key_scope"], "today": 0, "last_30_days": 0})
        item["last_30_days"] += int(r["requests"])
        if r["day"] == today:
            item["today"] += int(r["requests"])
    return {"days": USAGE_DAYS, "usage": list(totals.values()), "by_day": [{k: r[k] for k in r.keys()} for r in rows]}


@router.get("/activity")
def read_my_activity(user: CurrentUser, before: int | None = None, limit: int = 50,
                     conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    events = list_events(conn, before=before, limit=max(1, min(limit, 200)), actor_user_id=user.id, actions=USER_VISIBLE_ACTIONS)
    return {"events": events}


@router.get("/export.zip")
def export_my_data(request: Request, user: RecentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    ctx = auth_context(request)
    ctx.limits.take("export", f"user:{user.id}")
    data = account.build_export(conn, user.id, app_version=request.app.version)
    audit(conn, user.id, "export.created", "user", user.id, ip=request_ip(request), bytes=len(data))
    conn.commit()
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{account.export_filename(user.username)}"',
            "Cache-Control": "no-store",
        },
    )
