"""Account helpers shared by the routes, start-up and the admin CLI (none of them commit)."""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from starlette.requests import Request

from ..audit import audit
from ..db import utcnow
from . import clock, passwords, policy, sessions
from .errors import ApiProblem, busy, https_required
from .models import (
    USERNAME_HELP,
    active_admin_count,
    active_count,
    clean_display,
    normalize_username,
    valid_local_username,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Settings
    from .context import AuthContext


class PasswordRejected(ValueError):
    """A new password failed the policy; ``problems`` are user-facing messages."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


# --------------------------------------------------------------------------- #
# Plain-HTTP rule (note 07 §4.3 ALLOW_INSECURE_HTTP)
# --------------------------------------------------------------------------- #


def insecure_http_allowed(conn: sqlite3.Connection, settings: "Settings", *, adding_account: bool = False) -> bool:
    """Whether sign-in over non-loopback plain HTTP is allowed right now.

    ``ALLOW_INSECURE_HTTP=true``/``false`` decide; unset ("auto") allows it while the server has at
    most one active account (counting the one being created).
    """
    if settings.allow_insecure_http is not None:
        return bool(settings.allow_insecure_http)
    return active_count(conn) + (1 if adding_account else 0) <= 1


def require_secure_enough(conn: sqlite3.Connection, settings: "Settings", request: Request, *, adding_account: bool = False) -> None:
    from .context import plain_http

    if plain_http(request) and not insecure_http_allowed(conn, settings, adding_account=adding_account):
        raise https_required()


# --------------------------------------------------------------------------- #
# Usernames and passwords
# --------------------------------------------------------------------------- #


def check_local_username(raw: str | None) -> tuple[str, str]:
    """``(username as typed, normalised)`` or a 400 explaining the rule."""
    typed = (raw or "").strip()
    norm = normalize_username(typed)
    if not valid_local_username(norm):
        raise ApiProblem(400, f"username: {USERNAME_HELP}.", field="username")
    return typed, norm


def username_taken(conn: sqlite3.Connection, norm: str, *, except_id: int | None = None) -> bool:
    row = conn.execute("SELECT id FROM users WHERE username_norm = ?", (norm,)).fetchone()
    return row is not None and (except_id is None or int(row["id"]) != except_id)


def check_new_password(ctx: "AuthContext", conn: sqlite3.Connection, password: str, *, username: str, display_name: str = "") -> None:
    problems = policy.validate_new_password(
        password,
        username=username,
        display_name=display_name,
        instance_name=str(ctx.store.get(conn, "instance.name")),
        min_length=ctx.settings.password_min_length,
        breach_check=ctx.settings.password_breach_check,
    )
    if problems:
        raise PasswordRejected(problems)


def password_problem(exc: PasswordRejected) -> ApiProblem:
    return ApiProblem(400, exc.problems[0], field="password", problems=exc.problems)


def hash_password(password: str) -> str:
    try:
        return passwords.hash_password(password)
    except passwords.HashBusy:
        raise busy() from None


def verify_password(password: str, stored: str | None) -> bool:
    try:
        return passwords.verify_password(password, stored)
    except passwords.HashBusy:
        raise busy() from None


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


def create_user(
    conn: sqlite3.Connection,
    *,
    username: str,
    username_norm: str,
    display_name: str = "",
    role: str = "user",
    status: str = "active",
    auth_source: str = "local",
    external_subject: str | None = None,
    password_hash: str | None = None,
    must_change_password: bool = False,
) -> int:
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO users (username, username_norm, display_name, role, status, auth_source, external_subject,
                              password_hash, password_changed_at, must_change_password, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            username, username_norm, clean_display(display_name), role, status, auth_source, external_subject,
            password_hash, now if password_hash else None, int(must_change_password), now, now,
        ),
    )
    return int(cur.lastrowid)


def claim_first_admin(
    conn: sqlite3.Connection,
    *,
    username: str,
    username_norm: str,
    display_name: str = "",
    password_hash: str | None = None,
    auth_source: str = "local",
    external_subject: str | None = None,
    must_change_password: bool = False,
) -> int:
    """Turn the ``pending_setup`` user 1 into the active admin (keeping id 1, so the data migrated
    from v0.2 is theirs). Creates a new admin if user 1 is gone or already claimed."""
    now = utcnow()
    cur = conn.execute(
        """UPDATE users SET username = ?, username_norm = ?, display_name = ?, role = 'admin', status = 'active',
                 auth_source = ?, external_subject = ?, password_hash = ?, password_changed_at = ?,
                 must_change_password = ?, updated_at = ?
           WHERE id = 1 AND status = 'pending_setup'""",
        (
            username, username_norm, clean_display(display_name), auth_source, external_subject, password_hash,
            now if password_hash else None, int(must_change_password), now,
        ),
    )
    if (cur.rowcount or 0) > 0:
        return 1
    return create_user(
        conn,
        username=username,
        username_norm=username_norm,
        display_name=display_name,
        role="admin",
        auth_source=auth_source,
        external_subject=external_subject,
        password_hash=password_hash,
        must_change_password=must_change_password,
    )


def set_password(conn: sqlite3.Connection, user_id: int, password_hash: str, *, must_change: bool = False) -> None:
    now = utcnow()
    conn.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = ?, must_change_password = ?, updated_at = ? WHERE id = ?",
        (password_hash, now, int(must_change), now, int(user_id)),
    )


def lock_account(conn: sqlite3.Connection, user_id: int, *, ip: str | None = None) -> None:
    """NIST hard stop: status ``locked``, every session revoked, audited."""
    conn.execute("UPDATE users SET status = 'locked', updated_at = ? WHERE id = ? AND status = 'active'", (utcnow(), int(user_id)))
    sessions.revoke_user_sessions(conn, user_id)
    audit(conn, None, "user.locked", "user", user_id, ip=ip, reason="too_many_failed_sign_ins")


def touch_login(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (clock.now_iso(), int(user_id)))


def begin_immediate(conn: sqlite3.Connection) -> None:
    """Start a write transaction now (``BEGIN IMMEDIATE``), so a check and the write that depends on it
    see the same data: two admins demoting, disabling or deleting each other at the same moment are
    serialised, and the second one sees that the first already removed an admin. Anything the request's
    dependencies left uncommitted (a session's ``last_seen_at``) is committed first."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")


def would_remove_last_admin(conn: sqlite3.Connection, user_id: int) -> bool:
    """True when ``user_id`` is an active admin and the only one. Call it inside
    :func:`begin_immediate` when the write depends on the answer."""
    row = conn.execute("SELECT role, status FROM users WHERE id = ?", (int(user_id),)).fetchone()
    if row is None or row["role"] != "admin" or row["status"] != "active":
        return False
    return active_admin_count(conn) <= 1


def user_admin_dict(row: sqlite3.Row) -> dict[str, Any]:
    """What an admin sees about an account: identity and status, never health data."""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or "",
        "role": row["role"],
        "status": row["status"],
        "auth_source": row["auth_source"],
        "can_use_shared": bool(row["can_use_shared"]),
        "must_change_password": bool(row["must_change_password"]),
        "has_password": row["password_hash"] is not None,
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }
