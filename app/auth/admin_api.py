"""``/api/admin/*``: accounts, invites, instance settings, shared keys, usage, audit, About.

Admins manage accounts, not people's data: nothing here reads another person's log, foods, meals,
profile or keys (note 07 §0.7). Every write needs a password entry within ``REAUTH_MINUTES``. With
``AUTH_MODE=none`` the account pages are hidden (404) and shared-key writes are refused (403).
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from .. import account, credentials
from ..audit import audit, list_events
from ..crypto import secret_report
from ..db import database_file, get_db, get_meta, get_schema_version, utcnow
from . import clock, sessions, tokens
from .accounts import (
    begin_immediate,
    check_local_username,
    create_user,
    user_admin_dict,
    username_taken,
    would_remove_last_admin,
)
from .context import AuthContext, auth_context, public_base, request_ip
from .deps import AdminUser, RecentAdmin, require_admin
from .errors import ApiProblem
from .me import provider_or_404, run_key_test, settings_error
from .models import USER_COLUMNS, active_count, clean_display, normalize_username
from .proxy import clean_subject
from .routes import start_session
from .schemas import InviteCreate, KeyPut, UserCreate, UserDeleteBody, UserPatch

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

RESET_LINK_HOURS = 24
PRE_V3_BACKUP_DAYS = 30


def _no_accounts_in_none_mode(ctx: AuthContext) -> None:
    if ctx.settings.auth_mode == "none":
        raise HTTPException(status_code=404, detail="Not Found")


def _user_or_404(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    try:
        row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (int(user_id),)).fetchone()
    except OverflowError:
        row = None
    if row is None or (row["status"] == "pending_setup" and row["username_norm"].startswith("#")):
        raise HTTPException(status_code=404, detail=f"user {user_id} not found")
    return row


def _user_view(conn: sqlite3.Connection, row: sqlite3.Row, links: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """``user_admin_dict`` plus ``reset_link``: the open reset or account-setup link for the account
    (``{id, created_by, created_at, expires_at}``, never the token), so an admin can see and revoke a
    link that someone else issued, including one for their own account."""
    if links is None:
        links = tokens.open_reset_links(conn)
    return {**user_admin_dict(row), "reset_link": links.get(int(row["id"]))}


def _void_admin_links(conn: sqlite3.Connection, uid: int) -> dict[str, int]:
    """When ``uid`` stops being an active admin, the invites and links they created stop working."""
    voided = tokens.void_issued_by(conn, uid)
    return {"links_revoked": voided} if voided else {}


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


@router.get("/users")
def list_users(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _no_accounts_in_none_mode(auth_context(request))
    rows = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE username_norm NOT LIKE '#%' ORDER BY id").fetchall()
    links = tokens.open_reset_links(conn)
    return {"users": [_user_view(conn, r, links) for r in rows]}


@router.post("/users", status_code=201)
def create_account(body: UserCreate, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Local mode: a ``pending_setup`` account plus a one-time link where the person sets a password.
    Proxy mode: pre-create the identity the proxy will send (no link)."""
    ctx = auth_context(request)
    _no_accounts_in_none_mode(ctx)
    ip = request_ip(request)
    display = clean_display(body.display_name)
    if ctx.settings.auth_mode == "proxy":
        subject = clean_subject(body.username)
        if subject is None:
            raise ApiProblem(400, "username: the name your sign-in proxy sends", field="username")
        norm = normalize_username(subject)
        if username_taken(conn, norm):
            raise ApiProblem(409, "That username is taken.", field="username")
        user_id = create_user(conn, username=subject, username_norm=norm, display_name=display, role=body.role,
                              auth_source="proxy", external_subject=subject)
        audit(conn, admin.id, "user.invited", "user", user_id, ip=ip, role=body.role, via="proxy_account")
        conn.commit()
        return {"user": _user_view(conn, _user_or_404(conn, user_id)), "setup_url": None, "expires_at": None}
    typed, norm = check_local_username(body.username)
    if username_taken(conn, norm):
        raise ApiProblem(409, "That username is taken.", field="username")
    user_id = create_user(conn, username=typed, username_norm=norm, display_name=display, role=body.role, status="pending_setup")
    ttl_days = int(ctx.store.get(conn, "registration.invite_ttl_days"))
    token, row = tokens.create_token(conn, tokens.RESET, ttl=timedelta(days=ttl_days), user_id=user_id, created_by=admin.id)
    audit(conn, admin.id, "user.invited", "user", user_id, ip=ip, role=body.role, via="account")
    conn.commit()
    return {
        "user": _user_view(conn, _user_or_404(conn, user_id)),
        "setup_url": tokens.link(public_base(request, ctx.settings), "reset", token),
        "expires_at": row["expires_at"],
    }


@router.patch("/users/{user_id}")
def update_account(user_id: int, body: UserPatch, request: Request, response: Response, admin: RecentAdmin,
                   conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    _no_accounts_in_none_mode(ctx)
    begin_immediate(conn)  # the last-admin check and the write see the same data
    row = _user_or_404(conn, user_id)
    uid = int(row["id"])
    ip = request_ip(request)
    data = body.model_dump(exclude_unset=True)

    if data.get("role") is not None and data["role"] != row["role"]:
        if data["role"] != "admin" and would_remove_last_admin(conn, uid):
            raise ApiProblem(409, "This is the only admin. Make someone else an admin first.")
        conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (data["role"], utcnow(), uid))
        voided = _void_admin_links(conn, uid) if row["role"] == "admin" else {}
        audit(conn, admin.id, "user.role_changed", "user", uid, ip=ip, old=row["role"], new=data["role"], **voided)
        if uid == admin.id:
            start_session(request, response, conn, ctx, uid)  # rotate on privilege change
        else:
            sessions.revoke_user_sessions(conn, uid)

    status = data.get("status")
    if status is not None and status != row["status"]:
        if status == "disabled":
            if uid == admin.id:
                raise ApiProblem(409, "You cannot disable your own account.")
            if would_remove_last_admin(conn, uid):
                raise ApiProblem(409, "This is the only admin. Make someone else an admin first.")
            conn.execute("UPDATE users SET status = 'disabled', updated_at = ? WHERE id = ?", (utcnow(), uid))
            sessions.revoke_user_sessions(conn, uid)
            tokens.void_reset_links(conn, uid)  # an old link must not work again once the account is enabled
            audit(conn, admin.id, "user.disabled", "user", uid, ip=ip, **_void_admin_links(conn, uid))
        else:  # active
            if row["status"] != "disabled":
                raise ApiProblem(409, "Only a disabled account can be enabled here. A locked or new account needs a reset link.")
            conn.execute("UPDATE users SET status = 'active', updated_at = ? WHERE id = ?", (utcnow(), uid))
            audit(conn, admin.id, "user.enabled", "user", uid, ip=ip)

    if data.get("can_use_shared") is not None and bool(data["can_use_shared"]) != bool(row["can_use_shared"]):
        conn.execute("UPDATE users SET can_use_shared = ?, updated_at = ? WHERE id = ?", (int(data["can_use_shared"]), utcnow(), uid))
        audit(conn, admin.id, "user.updated", "user", uid, ip=ip, can_use_shared=bool(data["can_use_shared"]))

    if data.get("must_change_password") and not row["must_change_password"]:
        if row["auth_source"] != "local":
            raise ApiProblem(409, "This account signs in through the proxy and has no password here.")
        conn.execute("UPDATE users SET must_change_password = 1, updated_at = ? WHERE id = ?", (utcnow(), uid))
        audit(conn, admin.id, "user.must_change_password", "user", uid, ip=ip)

    if data.get("display_name") is not None:
        conn.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?", (clean_display(data["display_name"]), utcnow(), uid))
    conn.commit()
    return {"user": _user_view(conn, _user_or_404(conn, uid))}


@router.delete("/users/{user_id}", status_code=204, response_class=Response)
def delete_account(user_id: int, request: Request, admin: RecentAdmin, body: UserDeleteBody = Body(...),
                   conn: sqlite3.Connection = Depends(get_db)) -> Response:
    ctx = auth_context(request)
    _no_accounts_in_none_mode(ctx)
    begin_immediate(conn)  # the last-admin check and the delete see the same data
    row = _user_or_404(conn, user_id)
    if int(row["id"]) == admin.id:
        raise ApiProblem(409, "Delete your own account from Settings → Account instead.")
    if normalize_username(body.confirm_username) != row["username_norm"]:
        raise ApiProblem(400, "Type the account's username to confirm.", field="confirm_username")
    if would_remove_last_admin(conn, int(row["id"])):
        raise ApiProblem(409, "This is the only admin. Make someone else an admin first.")
    account.delete_user(conn, int(row["id"]), actor_id=admin.id, ip=request_ip(request), action="user.deleted")
    return Response(status_code=204)


@router.post("/users/{user_id}/reset-link")
def issue_reset_link(user_id: int, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A 24-hour, single-use link to set a new password (also unlocks a locked account)."""
    ctx = auth_context(request)
    _no_accounts_in_none_mode(ctx)
    if ctx.settings.auth_mode != "local":
        raise ApiProblem(409, "Passwords are managed by your sign-in proxy in this mode.")
    row = _user_or_404(conn, user_id)
    if row["auth_source"] != "local":
        raise ApiProblem(409, "This account signs in through the proxy and has no password here.")
    if row["status"] == "disabled":
        raise ApiProblem(409, "Enable the account first.")
    tokens.void_reset_links(conn, int(row["id"]))
    token, token_row = tokens.create_token(
        conn, tokens.RESET, ttl=timedelta(hours=RESET_LINK_HOURS), user_id=int(row["id"]), created_by=admin.id
    )
    audit(conn, admin.id, "user.reset_link_issued", "user", int(row["id"]), ip=request_ip(request))
    conn.commit()
    return {"url": tokens.link(public_base(request, ctx.settings), "reset", token), "expires_at": token_row["expires_at"]}


@router.delete("/users/{user_id}/reset-link", status_code=204, response_class=Response)
def revoke_reset_link(user_id: int, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Void the account's open reset or account-setup link (404 when there is none)."""
    _no_accounts_in_none_mode(auth_context(request))
    row = _user_or_404(conn, user_id)
    if not tokens.void_reset_links(conn, int(row["id"])):
        raise HTTPException(status_code=404, detail="no open link for this account")
    audit(conn, admin.id, "user.reset_link_revoked", "user", int(row["id"]), ip=request_ip(request))
    conn.commit()
    return Response(status_code=204)


@router.post("/users/{user_id}/revoke-sessions")
def revoke_user_sessions(user_id: int, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _no_accounts_in_none_mode(auth_context(request))
    row = _user_or_404(conn, user_id)
    count = sessions.revoke_user_sessions(conn, int(row["id"]))
    audit(conn, admin.id, "sessions.revoked", "user", int(row["id"]), ip=request_ip(request), count=count)
    conn.commit()
    return {"revoked": count}


# --------------------------------------------------------------------------- #
# Invites
# --------------------------------------------------------------------------- #


@router.get("/invites")
def list_invites(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    _no_accounts_in_none_mode(auth_context(request))
    rows = conn.execute("SELECT * FROM auth_tokens WHERE purpose = 'invite' ORDER BY created_at DESC LIMIT 200").fetchall()
    return {"invites": [tokens.invite_dict(r) for r in rows]}


@router.post("/invites", status_code=201)
def create_invite(body: InviteCreate, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A single-use invite link (shown once). The token travels in the URL fragment."""
    ctx = auth_context(request)
    _no_accounts_in_none_mode(ctx)
    if ctx.settings.auth_mode != "local":
        raise ApiProblem(409, "Invites are for local accounts; in proxy mode add the person with their proxy name instead.")
    if ctx.store.get(conn, "registration.mode") == "closed":
        raise ApiProblem(409, "Registration is closed. Create the account instead, or switch registration to invites.")
    ttl_days = body.ttl_days or int(ctx.store.get(conn, "registration.invite_ttl_days"))
    note = clean_display(body.note, 200) or None
    token, row = tokens.create_token(conn, tokens.INVITE, ttl=timedelta(days=ttl_days), role=body.role, note=note, created_by=admin.id)
    audit(conn, admin.id, "user.invited", "invite", row["id"], ip=request_ip(request), role=body.role)
    conn.commit()
    return {
        "invite": tokens.invite_dict(row),
        "url": tokens.link(public_base(request, ctx.settings), "invite", token),
        "expires_at": row["expires_at"],
    }


@router.delete("/invites/{invite_id}", status_code=204, response_class=Response)
def revoke_invite(invite_id: str, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    _no_accounts_in_none_mode(auth_context(request))
    cur = conn.execute("DELETE FROM auth_tokens WHERE id = ? AND purpose = 'invite' AND used_at IS NULL", (invite_id[:64],))
    if not cur.rowcount:
        raise HTTPException(status_code=404, detail="invite not found")
    audit(conn, admin.id, "invite.revoked", "invite", invite_id[:64], ip=request_ip(request))
    conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Instance settings
# --------------------------------------------------------------------------- #


@router.get("/settings")
def read_instance_settings(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"settings": auth_context(request).store.admin_view(conn)}


@router.patch("/settings")
def update_instance_settings(request: Request, admin: RecentAdmin, body: dict[str, Any] = Body(...),
                             conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    store = ctx.store
    if ctx.settings.auth_mode == "none":  # note 04 §9 A7: everyone on the network is an admin in this mode
        from ..settings_registry import NO_SIGNIN_ENV_ONLY

        env_only = sorted(k for k in body if k in NO_SIGNIN_ENV_ONLY)
        if env_only:
            raise ApiProblem(403, "Set AI settings with environment variables when sign-in is off (AUTH_MODE=none).", keys=env_only)
    try:
        changed = store.update_instance(conn, body, updated_by=admin.id)
    except Exception as exc:  # mapped to 400/403/409; anything else re-raised by settings_error
        conn.rollback()
        raise settings_error(exc) from None
    ip = request_ip(request)
    for key, old, new in changed:
        audit(conn, admin.id, "settings.changed", "setting", key, ip=ip, key=key, old=old, new=new)
    conn.commit()
    return {"settings": store.admin_view(conn)}


# --------------------------------------------------------------------------- #
# Shared keys
# --------------------------------------------------------------------------- #


def _shared_item(conn: sqlite3.Connection, ctx: AuthContext, p: credentials.Provider) -> dict[str, Any]:
    return {
        "provider": p.slug,
        "label": p.label,
        "shared": credentials.shared_status(conn, ctx.require_keyring(), ctx.settings, p.slug),
    }


def _shared_writable(ctx: AuthContext, p: credentials.Provider) -> None:
    if ctx.settings.auth_mode == "none":
        raise ApiProblem(403, "Shared keys cannot be changed while the server runs without sign-in (AUTH_MODE=none).")
    if credentials.env_secret(ctx.settings, p.slug):
        raise ApiProblem(409, "This key is set by the server's environment and cannot be changed here.", locked=True)


@router.get("/keys")
def read_shared_keys(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    return {"providers": [_shared_item(conn, ctx, p) for p in credentials.PROVIDERS.values()]}


@router.put("/keys/{provider}")
def set_shared_key(provider: str, body: KeyPut, request: Request, admin: RecentAdmin,
                   conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    p = provider_or_404(provider)
    _shared_writable(ctx, p)
    fields = {"api_key": body.api_key.get_secret_value()}
    try:
        credentials.validate_api_key(fields["api_key"])
    except credentials.InvalidCredential as exc:
        raise ApiProblem(400, f"api_key: {exc}", field="api_key") from None
    test = run_key_test(ctx, p, fields, f"user:{admin.id}") if body.test else None
    credentials.store_secret(conn, ctx.require_keyring(), p.slug, fields, owner_user_id=None, updated_by=admin.id)
    audit(conn, admin.id, "secret.set", "secret", p.slug, ip=request_ip(request), provider=p.slug, scope="shared")
    conn.commit()
    item = _shared_item(conn, ctx, p)
    if test is not None:
        item["test"] = test
    return item


@router.delete("/keys/{provider}", status_code=204, response_class=Response)
def delete_shared_key(provider: str, request: Request, admin: RecentAdmin, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    ctx = auth_context(request)
    p = provider_or_404(provider)
    _shared_writable(ctx, p)
    if credentials.delete_secret(conn, p.slug, owner_user_id=None):
        audit(conn, admin.id, "secret.removed", "secret", p.slug, ip=request_ip(request), provider=p.slug, scope="shared")
        conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Usage, audit, About
# --------------------------------------------------------------------------- #


@router.get("/usage")
def read_usage(admin: AdminUser, days: int = Query(30, ge=1, le=366), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Request counts per person, provider and key scope (counts only, nothing about what was looked up)."""
    since = (clock.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT u.user_id, us.username, u.provider, u.key_scope, SUM(u.requests) AS requests
           FROM usage_daily u LEFT JOIN users us ON us.id = u.user_id
           WHERE u.day >= ? GROUP BY u.user_id, u.provider, u.key_scope ORDER BY u.user_id, u.provider, u.key_scope""",
        (since,),
    ).fetchall()
    return {"days": days, "usage": [{k: r[k] for k in r.keys()} for r in rows]}


@router.get("/audit")
def read_audit(admin: AdminUser, before: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=500),
               conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"events": list_events(conn, before=before, limit=limit)}


def pre_v3_backup(conn: sqlite3.Connection) -> dict[str, Any] | None:
    path = database_file(conn)
    if not path:
        return None
    backup = Path(f"{path}.pre-v3.bak")
    if not backup.exists():
        return None
    migrated = clock.parse(get_meta(conn, "accounts_migrated_at"))
    expires = clock.iso(migrated + timedelta(days=PRE_V3_BACKUP_DAYS)) if migrated else None
    return {"path": str(backup), "bytes": backup.stat().st_size, "deleted_after": expires}


@router.get("/about")
def about(request: Request, admin: AdminUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    ctx = auth_context(request)
    s = ctx.settings
    keyring = ctx.require_keyring()
    from ..security import effective_scheme

    last_backup = conn.execute("SELECT at FROM audit_log WHERE action = 'backup.created' ORDER BY id DESC LIMIT 1").fetchone()
    key_on_volume = keyring.source == "auto"
    security_state = getattr(request.app.state, "security", None)
    return {
        "version": request.app.version,
        "schema_version": get_schema_version(conn),
        "auth_mode": s.auth_mode,
        "accounts": {"active": active_count(conn), "total": int(conn.execute("SELECT COUNT(*) FROM users WHERE username_norm NOT LIKE '#%'").fetchone()[0])},
        "https": effective_scheme(request.scope) == "https",
        "public_url": s.public_url,
        "secret_key": {
            "source": keyring.source,
            "on_data_volume": key_on_volume,
            "warning": (
                "The secret key lives on the data volume, so volume backups contain it. Mount SECRET_KEY_FILE "
                "from your engine's secret store instead (docs/security.md)."
                if key_on_volume else None
            ),
            "secrets": secret_report(conn, keyring),
        },
        "proxy": security_state.snapshot() if security_state is not None else {},
        "pre_v3_backup": pre_v3_backup(conn),
        "last_backup_at": last_backup["at"] if last_backup else None,
    }
