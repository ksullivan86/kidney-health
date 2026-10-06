"""``/api/auth/*``: status, first-run setup, sign-in, sign-out, registration, reset links, re-auth.

Public routes (no session needed): ``GET /status``, ``POST /login``, ``/setup``, ``/register`` and
``/reset`` (note 07 §4.10). ``/logout`` and ``/reauth`` need a signed-in person. In proxy mode the
password routes (login, register, reset, reauth) answer 404 (§9 N2); with ``AUTH_MODE=none`` so do
setup and registration. Every unsafe request also needs ``X-Requested-With: kidney-health``
(login CSRF; :class:`app.security.CsrfMiddleware`).
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import settings_registry
from ..audit import audit
from ..db import get_db
from . import clock, passwords, sessions, tokens
from .accounts import (
    PasswordRejected,
    check_local_username,
    check_new_password,
    claim_first_admin,
    create_user,
    hash_password,
    insecure_http_allowed,
    lock_account,
    password_problem,
    require_secure_enough,
    set_password,
    touch_login,
    username_taken,
    verify_password,
)
from .context import AuthContext, auth_context, plain_http, request_ip
from .deps import CurrentUser, ensure_setup_done, identify
from .errors import ApiProblem, busy, too_many
from .models import (
    USER_COLUMNS,
    clean_display,
    find_local_user,
    load_user,
    me_dict,
    normalize_username,
    setup_required,
    user_row,
    valid_local_username,
)
from .policy import MAX_LENGTH
from .proxy import trusted_subject
from .schemas import LoginBody, ReauthBody, RegisterBody, ResetBody, SetupBody
from .throttle import HARD_STOP, REAUTH_MAX_FAILURES

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_FAILED = "Username or password is incorrect"
LINK_INVALID = "This link is not valid any more. Ask your admin for a new one."
SETUP_CODE_INVALID = (
    "The setup code is wrong or has expired. Restart the server, or run python -m app.admin setup-code, for a new one."
)


def _only_modes(ctx: AuthContext, *modes: str) -> None:
    if ctx.settings.auth_mode not in modes:
        raise HTTPException(status_code=404, detail="Not Found")


def _ip_gate(ctx: AuthContext, ip: str | None) -> None:
    wait = ctx.throttle.ip_wait(ip)
    if wait:
        raise too_many(wait)


def start_session(request: Request, response: Response, conn: sqlite3.Connection, ctx: AuthContext, user_id: int) -> None:
    """New session (never reusing a pre-login cookie), session + device cookies, last_login_at."""
    s = ctx.settings
    old = sessions.lookup(conn, sessions.read_token(request))  # no commit: stays in the caller's transaction
    if old is not None:
        sessions.revoke(conn, old.id, old.user_id)
    token, info = sessions.create_session(
        conn,
        user_id,
        max_days=s.session_max_days,
        user_agent=request.headers.get("user-agent"),
        ip=request_ip(request),
    )
    request.state.auth_session = info
    sessions.set_cookie(response, request, token, max_days=s.session_max_days)
    ctx.throttle.set_device_cookie(response, request, user_id)
    touch_login(conn, user_id)


def _reset_notice(conn: sqlite3.Connection, user_id: int, since: str | None) -> str | None:
    """N12: tell the person when an admin-issued reset link changed their password since last sign-in."""
    row = conn.execute(
        """SELECT at FROM audit_log WHERE action = 'user.password_changed' AND target_type = 'user' AND target_id = ?
             AND details_json LIKE '%"via":"admin_reset_link"%' AND at > ? ORDER BY id DESC LIMIT 1""",
        (str(int(user_id)), since or ""),
    ).fetchone()
    if row is None:
        return None
    return f"Your password was reset with a link from an admin on {row['at'][:10]}."


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


@router.get("/status")
def auth_status(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    s = ctx.settings
    mode = s.auth_mode
    needs = mode != "none" and setup_required(conn)
    user = None
    if not needs:
        try:
            found = identify(request, conn)
        except ApiProblem:
            found = None
        if found is not None and found.is_active:
            user = me_dict(found)
    registration = "disabled" if mode != "local" else str(ctx.store.get(conn, "registration.mode"))
    insecure = plain_http(request)
    return {
        "setup_required": needs,
        "auth_mode": mode,
        "registration": registration,
        "insecure_http": insecure,
        "https_required": bool(insecure and not insecure_http_allowed(conn, s)),
        "password_min_length": s.password_min_length,
        "password_max_length": MAX_LENGTH,
        "instance_name": str(ctx.store.get(conn, "instance.name")),
        "user": user,
        "logout_url": s.proxy_logout_url if mode == "proxy" else None,
        # AUTH_MODE=none: the UI shows a red banner ("No sign-in: anyone who can open this page can see
        # and change this data").
        "no_login": mode == "none",
    }


# --------------------------------------------------------------------------- #
# Sign-in and sign-out
# --------------------------------------------------------------------------- #


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    _only_modes(ctx, "local")
    ensure_setup_done(conn, ctx)
    s = ctx.settings
    th = ctx.throttle
    ip = request_ip(request)
    _ip_gate(ctx, ip)
    if not th.global_acquire():
        raise busy()
    require_secure_enough(conn, s, request)

    norm = normalize_username(body.username)
    row = find_local_user(conn, norm) if valid_local_username(norm) else None
    device = th.device_nonce(th.read_device_cookie(request), int(row["id"])) if row is not None else None
    mac = th.name_mac(norm)
    if device is None:
        wait = th.username_wait(conn, mac)
        if wait:
            raise too_many(wait)

    # Exactly one hash per attempt, whatever the account's state (§9 N9).
    usable = row is not None and row["status"] == "active" and bool(row["password_hash"])
    stored = row["password_hash"] if usable else passwords.dummy_hash()
    ok = verify_password(body.password.get_secret_value(), stored) and usable

    if not ok:
        th.ip_failure(ip)
        if device is not None:
            th.device_failure(device)
        else:
            count = th.record_failure(conn, mac)
            if row is not None and row["status"] == "active" and count >= HARD_STOP:
                lock_account(conn, int(row["id"]), ip=ip)
        if row is not None:
            audit(conn, None, "login.failed", "user", int(row["id"]), ip=ip)
        conn.commit()
        raise ApiProblem(401, LOGIN_FAILED)

    user_id = int(row["id"])
    if device is not None:
        th.device_success(device)
    th.forget(conn, mac)
    if passwords.needs_rehash(stored):
        set_password(conn, user_id, hash_password(body.password.get_secret_value()), must_change=bool(row["must_change_password"]))
    notice = _reset_notice(conn, user_id, row["last_login_at"])
    start_session(request, response, conn, ctx, user_id)
    audit(conn, user_id, "login.succeeded", "user", user_id, ip=ip)
    conn.commit()
    user = load_user(conn, user_id)
    return {"user": me_dict(user), "notice": notice}


@router.post("/logout")
def logout(request: Request, response: Response, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    info = getattr(request.state, "auth_session", None)
    if info is not None:
        sessions.revoke(conn, info.id, user.id)
        conn.commit()
    sessions.clear_cookies(response, request)
    # The client warns about unsynced offline entries before calling this (note 02).
    response.headers["Clear-Site-Data"] = '"cache", "storage"'
    out: dict[str, Any] = {"ok": True}
    if ctx.settings.auth_mode == "proxy" and ctx.settings.proxy_logout_url:
        out["redirect"] = ctx.settings.proxy_logout_url
    return out


# --------------------------------------------------------------------------- #
# First-run setup
# --------------------------------------------------------------------------- #


@router.post("/setup")
def setup(body: SetupBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    _only_modes(ctx, "local", "proxy")
    s = ctx.settings
    if not setup_required(conn):
        raise ApiProblem(409, "Setup is already complete")
    ip = request_ip(request)
    _ip_gate(ctx, ip)
    if s.auth_mode == "local":
        require_secure_enough(conn, s, request)
    token_id = tokens.check_setup_code(conn, body.code.get_secret_value())
    if token_id is None:
        ctx.throttle.ip_failure(ip)
        raise ApiProblem(400, SETUP_CODE_INVALID, field="code")
    if s.auth_mode == "local":
        typed, norm = check_local_username(body.username)
        if body.password is None:
            raise ApiProblem(400, "password: choose a password", field="password")
        display = clean_display(body.display_name)
        password = body.password.get_secret_value()
        try:
            check_new_password(ctx, conn, password, username=typed, display_name=display)
        except PasswordRejected as exc:
            raise password_problem(exc) from None
        password_hash = hash_password(password)
    else:
        subject = trusted_subject(request, ctx)
        if subject is None:
            raise ApiProblem(400, "Open this page through your sign-in proxy so the server knows who you are.")
    # Take the single-use code first (this write holds the database lock), so two people racing
    # with the same code cannot both become the first admin.
    if not tokens.mark_used(conn, token_id) or not setup_required(conn):
        conn.rollback()
        raise ApiProblem(409, "Setup is already complete")

    if s.auth_mode == "proxy":
        norm = normalize_username(subject)
        display = clean_display(body.display_name) or subject
        user_id = claim_first_admin(
            conn, username=subject, username_norm=norm, display_name=display, auth_source="proxy", external_subject=subject
        )
    else:
        user_id = claim_first_admin(conn, username=typed, username_norm=norm, display_name=display, password_hash=password_hash)
    if body.off_enabled is not None and "food.off_enabled" in settings_registry.REGISTRY:
        try:
            ctx.store.set_instance(conn, "food.off_enabled", bool(body.off_enabled), updated_by=user_id)
        except Exception:  # locked by env or not editable: the env value wins
            pass
    audit(conn, user_id, "setup.completed", "user", user_id, ip=ip, auth_source=s.auth_mode)
    if s.auth_mode == "local":
        start_session(request, response, conn, ctx, user_id)
    conn.commit()
    ctx.setup_complete = True
    return {"user": me_dict(load_user(conn, user_id))}


# --------------------------------------------------------------------------- #
# Registration and reset links
# --------------------------------------------------------------------------- #


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    _only_modes(ctx, "local")
    ensure_setup_done(conn, ctx)
    s = ctx.settings
    ip = request_ip(request)
    _ip_gate(ctx, ip)
    mode = str(ctx.store.get(conn, "registration.mode"))
    invite = None
    if body.token is not None and body.token.get_secret_value():
        invite = tokens.find_token(conn, body.token.get_secret_value(), tokens.INVITE)
        if invite is None:
            ctx.throttle.ip_failure(ip)
            raise ApiProblem(400, "This invite link is not valid any more. Ask your admin for a new one.", field="token")
    if mode == "closed":
        raise ApiProblem(403, "Registration is closed on this server. Ask your admin to create an account for you.")
    if mode == "invite" and invite is None:
        raise ApiProblem(403, "You need an invite link from your admin to create an account here.")
    if invite is None:  # open registration: HTTPS always, 3 per address per hour
        if plain_http(request):
            raise ApiProblem(400, "HTTPS required to register on this server. See docs/https.md.", https_required=True)
        ctx.limits.take("register", ip)
    require_secure_enough(conn, s, request, adding_account=True)

    typed, norm = check_local_username(body.username)
    if username_taken(conn, norm):
        raise ApiProblem(409, "That username is taken. Choose another one.", field="username")
    display = clean_display(body.display_name)
    password = body.password.get_secret_value()
    try:
        check_new_password(ctx, conn, password, username=typed, display_name=display)
    except PasswordRejected as exc:
        raise password_problem(exc) from None
    role = invite["role"] if invite is not None and invite["role"] else "user"
    user_id = create_user(conn, username=typed, username_norm=norm, display_name=display, role=role, password_hash=hash_password(password))
    if invite is not None and not tokens.mark_used(conn, invite["id"]):
        conn.rollback()
        raise ApiProblem(400, "This invite link was just used. Ask your admin for a new one.", field="token")
    audit(conn, user_id, "user.registered", "user", user_id, ip=ip, via="invite" if invite is not None else "open",
          invite_id=invite["id"] if invite is not None else None, role=role)
    start_session(request, response, conn, ctx, user_id)
    conn.commit()
    return {"user": me_dict(load_user(conn, user_id))}


@router.post("/reset")
def reset(body: ResetBody, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    _only_modes(ctx, "local")
    ensure_setup_done(conn, ctx)
    s = ctx.settings
    ip = request_ip(request)
    _ip_gate(ctx, ip)
    token = tokens.find_token(conn, body.token.get_secret_value(), tokens.RESET)
    row = user_row(conn, int(token["user_id"])) if token is not None and token["user_id"] is not None else None
    if token is None or row is None or row["status"] == "disabled" or row["auth_source"] != "local":
        ctx.throttle.ip_failure(ip)
        raise ApiProblem(400, LINK_INVALID, field="token")
    require_secure_enough(conn, s, request, adding_account=row["status"] != "active")
    password = body.password.get_secret_value()
    try:
        check_new_password(ctx, conn, password, username=row["username"], display_name=row["display_name"] or "")
    except PasswordRejected as exc:
        raise password_problem(exc) from None
    user_id = int(row["id"])
    set_password(conn, user_id, hash_password(password))
    conn.execute("UPDATE users SET status = 'active' WHERE id = ? AND status IN ('locked', 'pending_setup')", (user_id,))
    sessions.revoke_user_sessions(conn, user_id)
    tokens.mark_used(conn, token["id"])
    ctx.throttle.forget(conn, ctx.throttle.name_mac(row["username_norm"]))
    if row["status"] == "pending_setup":
        via = "account_setup"  # a new account created by an admin: the first password, not a reset
    elif token["created_by"] is not None and int(token["created_by"]) != user_id:
        via = "admin_reset_link"
    else:
        via = "reset_link"
    audit(conn, user_id, "user.password_changed", "user", user_id, ip=ip, via=via, issued_by=token["created_by"])
    start_session(request, response, conn, ctx, user_id)
    conn.commit()
    return {"user": me_dict(load_user(conn, user_id))}


# --------------------------------------------------------------------------- #
# Re-authentication ("sudo" window)
# --------------------------------------------------------------------------- #


@router.post("/reauth")
def reauth(body: ReauthBody, request: Request, response: Response, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    _only_modes(ctx, "local")
    th = ctx.throttle
    ip = request_ip(request)
    _ip_gate(ctx, ip)
    info = request.state.auth_session
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user.id,)).fetchone()
    mac = th.name_mac(row["username_norm"])
    wait = th.username_wait(conn, mac)
    if wait:
        raise too_many(wait)
    if not verify_password(body.password.get_secret_value(), row["password_hash"]):
        th.ip_failure(ip)
        count = th.record_failure(conn, mac)
        failures = th.reauth_failure(info.id)
        audit(conn, user.id, "login.failed", "user", user.id, ip=ip, via="reauth")
        if count >= HARD_STOP:
            lock_account(conn, user.id, ip=ip)
        if failures >= REAUTH_MAX_FAILURES:
            sessions.revoke(conn, info.id, user.id)
            audit(conn, user.id, "session.revoked_reauth", "user", user.id, ip=ip)
            conn.commit()
            th.reauth_reset(info.id)
            raise ApiProblem(401, "Signed out after too many wrong passwords. Sign in again.")
        conn.commit()
        raise ApiProblem(403, "That password is not right.", field="password")
    th.reauth_reset(info.id)
    th.forget(conn, mac)
    at = sessions.mark_reauth(conn, info.id, user.id)
    conn.commit()
    until = clock.parse(at) + timedelta(minutes=ctx.settings.reauth_minutes)
    return {"ok": True, "reauth_until": clock.iso(until)}

