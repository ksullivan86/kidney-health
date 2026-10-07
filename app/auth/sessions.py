"""Opaque server-side sessions and their cookies (note 07 §4.7, §9 N6).

* A session is ``<selector>.<verifier>``: the selector (16 random bytes, hex) is the row id, the
  verifier (32 random bytes) is stored only as its SHA-256. A stolen database therefore holds no
  usable session.
* Over HTTPS (the effective scheme after trusted-proxy handling) the cookie is
  ``__Host-kh_session`` with ``Secure; HttpOnly; SameSite=Lax; Path=/``; over plain HTTP it is
  ``kh_session`` without ``Secure``. Each scheme reads **only** its own name, so a plain-HTTP page on
  the same host cannot toss a cookie into the HTTPS app; logout expires both.
* At most ``SESSION_MAX_DAYS`` (absolute) and ``SESSION_IDLE_DAYS`` without use. ``last_seen_at``
  is written at most every 5 minutes. Expired rows are deleted at start-up and hourly.
* ``reauth_at`` is the last time the password was entered (sign-in or ``/api/auth/reauth``);
  sensitive actions need it within ``REAUTH_MINUTES``.

Every function takes ``user_id`` where a row is selected, so one person can never act on another
person's session by selector (§9 N5 (4)). Functions never commit.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from ..audit import ip_prefix
from ..security import effective_scheme
from . import clock

COOKIE_HTTPS = "__Host-kh_session"
COOKIE_HTTP = "kh_session"
TOUCH_INTERVAL = timedelta(minutes=5)
USER_AGENT_LIMIT = 200


@dataclass(frozen=True)
class SessionInfo:
    id: str
    user_id: int
    created_at: str
    last_seen_at: str
    expires_at: str
    reauth_at: str | None
    user_agent: str | None
    ip_prefix: str | None


def _hash(verifier: str) -> bytes:
    return hashlib.sha256(verifier.encode("utf-8")).digest()


def _info(row: sqlite3.Row) -> SessionInfo:
    return SessionInfo(
        id=row["id"],
        user_id=int(row["user_id"]),
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        expires_at=row["expires_at"],
        reauth_at=row["reauth_at"],
        user_agent=row["user_agent"],
        ip_prefix=row["ip_prefix"],
    )


def is_https(request: Request) -> bool:
    return effective_scheme(request.scope) == "https"


def cookie_name(https: bool) -> str:
    return COOKIE_HTTPS if https else COOKIE_HTTP


def create_session(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    max_days: int,
    user_agent: str | None = None,
    ip: str | None = None,
    reauth: bool = True,
) -> tuple[str, SessionInfo]:
    """Insert a new session; returns ``(cookie value, info)``. Never reuses an id."""
    now = clock.now()
    sid = secrets.token_hex(16)
    verifier = secrets.token_urlsafe(32)
    stamp = clock.iso(now)
    expires = clock.iso(now + timedelta(days=max_days))
    agent = (user_agent or "")[:USER_AGENT_LIMIT] or None
    prefix = ip_prefix(ip)
    conn.execute(
        """INSERT INTO sessions (id, user_id, verifier_hash, created_at, last_seen_at, expires_at, reauth_at, user_agent, ip_prefix)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, int(user_id), _hash(verifier), stamp, stamp, expires, stamp if reauth else None, agent, prefix),
    )
    info = SessionInfo(sid, int(user_id), stamp, stamp, expires, stamp if reauth else None, agent, prefix)
    return f"{sid}.{verifier}", info


def split_token(token: str | None) -> tuple[str, str] | None:
    if not token or "." not in token or len(token) > 256:
        return None
    sid, _, verifier = token.partition(".")
    if len(sid) != 32 or not verifier:
        return None
    return sid, verifier


def lookup(conn: sqlite3.Connection, token: str | None) -> SessionInfo | None:
    """The session row matching ``token`` (expired or not), without writing anything."""
    parts = split_token(token)
    if parts is None:
        return None
    sid, verifier = parts
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None or not hmac.compare_digest(bytes(row["verifier_hash"]), _hash(verifier)):
        return None
    return _info(row)


def validate(conn: sqlite3.Connection, token: str | None, *, idle_days: int) -> SessionInfo | None:
    """The session for ``token`` if it exists, matches, and has not expired (absolute or idle)."""
    parts = split_token(token)
    if parts is None:
        return None
    sid, verifier = parts
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None or not hmac.compare_digest(bytes(row["verifier_hash"]), _hash(verifier)):
        return None
    now = clock.now()
    expires = clock.parse(row["expires_at"])
    last_seen = clock.parse(row["last_seen_at"])
    if expires is None or last_seen is None or now >= expires or now >= last_seen + timedelta(days=idle_days):
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        conn.commit()
        return None
    info = _info(row)
    if now - last_seen >= TOUCH_INTERVAL:
        stamp = clock.iso(now)
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (stamp, sid))
        conn.commit()
        info = SessionInfo(**{**info.__dict__, "last_seen_at": stamp})
    return info


def mark_reauth(conn: sqlite3.Connection, session_id: str, user_id: int) -> str:
    stamp = clock.now_iso()
    conn.execute("UPDATE sessions SET reauth_at = ? WHERE id = ? AND user_id = ?", (stamp, session_id, int(user_id)))
    return stamp


def reauth_is_recent(info: SessionInfo | None, minutes: int) -> bool:
    if info is None or not info.reauth_at:
        return False
    at = clock.parse(info.reauth_at)
    return at is not None and clock.now() - at <= timedelta(minutes=minutes)


def revoke(conn: sqlite3.Connection, session_id: str, user_id: int) -> bool:
    cur = conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, int(user_id)))
    return (cur.rowcount or 0) > 0


def revoke_user_sessions(conn: sqlite3.Connection, user_id: int, *, except_id: str | None = None) -> int:
    if except_id is None:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(user_id),))
    else:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ? AND id != ?", (int(user_id), except_id))
    return int(cur.rowcount or 0)


def list_sessions(conn: sqlite3.Connection, user_id: int, *, current_id: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, created_at, last_seen_at, expires_at, user_agent, ip_prefix FROM sessions
           WHERE user_id = ? ORDER BY last_seen_at DESC, id""",
        (int(user_id),),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "last_seen_at": r["last_seen_at"],
            "expires_at": r["expires_at"],
            "user_agent": r["user_agent"],
            "ip_prefix": r["ip_prefix"],
            "current": r["id"] == current_id,
        }
        for r in rows
    ]


def purge_expired(conn: sqlite3.Connection, *, idle_days: int) -> int:
    """Delete sessions past their absolute or idle expiry (no commit)."""
    now = clock.now()
    cur = conn.execute(
        "DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at <= ?",
        (clock.iso(now), clock.iso(now - timedelta(days=idle_days))),
    )
    return int(cur.rowcount or 0)


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #


def read_token(request: Request) -> str | None:
    """The session cookie for this request's scheme only (§9 N6)."""
    return request.cookies.get(cookie_name(is_https(request)))


def set_cookie(response: Response, request: Request, token: str, *, max_days: int) -> None:
    https = is_https(request)
    response.set_cookie(
        cookie_name(https),
        token,
        max_age=max_days * 86400,
        path="/",
        secure=https,
        httponly=True,
        samesite="lax",
    )


def clear_cookies(response: Response, request: Request) -> None:
    """Expire both session cookie names (the ``__Host-`` one needs ``Secure`` to be accepted;
    a browser on plain HTTP ignores that line, which is fine: it cannot hold such a cookie)."""
    del request
    response.delete_cookie(COOKIE_HTTP, path="/", secure=False, httponly=True, samesite="lax")
    response.delete_cookie(COOKIE_HTTPS, path="/", secure=True, httponly=True, samesite="lax")
