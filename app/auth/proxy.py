"""Trusted reverse-proxy identity (``AUTH_MODE=proxy``; note 07 §4.5 and §9 N2).

The identity header counts only when :class:`app.security.TrustedProxyMiddleware` marked the request
as coming from ``TRUSTED_PROXIES`` with the right ``X-Proxy-Secret`` (``request.state.proxy_trusted``);
otherwise the middleware has already removed the header and counted it on Admin → About.

* Accounts are found by ``(auth_source='proxy', external_subject=<header>)``. A proxy identity is
  never linked to a local account by name: when its normalised name collides with an existing
  account the request gets 403 and ``proxy.username_conflict`` is audited.
* Unknown identities get 403 unless ``PROXY_AUTO_CREATE_USERS=true``. Without
  ``TRUSTED_PROXY_ADMIN_GROUP``, proxy-created accounts are always ``user``; with it, the role follows
  the groups header on every request (changes audited).
* No session cookie is involved; local passwords exist only for the break-glass CLI.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata

from starlette.requests import Request

from ..audit import audit
from ..db import utcnow
from .accounts import create_user
from .context import AuthContext, request_ip
from .errors import ApiProblem
from .models import MAX_PROXY_SUBJECT, USER_COLUMNS, User, clean_display, normalize_username, user_from_row

_GROUP_SPLIT = re.compile(r"[,|]")


def clean_subject(raw: str | None) -> str | None:
    """Strip, NFC, no control characters, at most 255 characters; None when empty."""
    if not raw:
        return None
    text = unicodedata.normalize("NFC", raw).strip()
    if not text or len(text) > MAX_PROXY_SUBJECT or any(unicodedata.category(ch)[0] == "C" for ch in text):
        return None
    return text


def trusted_subject(request: Request, ctx: AuthContext) -> str | None:
    header = ctx.settings.trusted_proxy_user_header
    if not header or not getattr(request.state, "proxy_trusted", False):
        return None
    return clean_subject(request.headers.get(header))


def _groups(request: Request, ctx: AuthContext) -> set[str] | None:
    """The groups the proxy sent; None when the header is not configured or not sent at all (no
    information: the role is left alone), an empty set when it was sent empty (no groups)."""
    header = ctx.settings.trusted_proxy_groups_header
    if not header:
        return None
    raw = request.headers.get(header)
    if raw is None:
        return None
    return {g.strip() for g in _GROUP_SPLIT.split(raw) if g.strip()}


def _wanted_role(request: Request, ctx: AuthContext) -> str | None:
    admin_group = ctx.settings.trusted_proxy_admin_group
    if not admin_group:
        return None
    groups = _groups(request, ctx)
    if groups is None:
        return None
    return "admin" if admin_group in groups else "user"


def _display_name(request: Request, ctx: AuthContext) -> str | None:
    header = ctx.settings.trusted_proxy_name_header
    if not header:
        return None
    value = clean_display(request.headers.get(header))
    return value or None


def user_from_request(request: Request, conn: sqlite3.Connection, ctx: AuthContext) -> User | None:
    subject = trusted_subject(request, ctx)
    if subject is None:
        return None
    row = conn.execute(
        f"SELECT {USER_COLUMNS} FROM users WHERE auth_source = 'proxy' AND external_subject = ?", (subject,)
    ).fetchone()
    ip = request_ip(request)
    if row is None:
        norm = normalize_username(subject)
        clash = conn.execute("SELECT id FROM users WHERE username_norm = ?", (norm,)).fetchone()
        if clash is not None:
            audit(conn, None, "proxy.username_conflict", "user", clash["id"], ip=ip)
            conn.commit()
            raise ApiProblem(
                403,
                "This sign-in name is already used by another account on this server. Ask the admin to sort it out.",
            )
        if not ctx.settings.proxy_auto_create_users:
            raise ApiProblem(403, f"Your account is not enabled here. Ask the admin to add {subject}.")
        role = _wanted_role(request, ctx) or "user"
        user_id = create_user(
            conn,
            username=subject,
            username_norm=norm,
            display_name=_display_name(request, ctx) or "",
            role=role,
            auth_source="proxy",
            external_subject=subject,
        )
        audit(conn, None, "user.created_by_proxy", "user", user_id, ip=ip, role=role)
        conn.commit()
        row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()
    if row["status"] != "active":
        raise ApiProblem(403, "This account is disabled. Ask the admin.")
    wanted = _wanted_role(request, ctx)
    name = _display_name(request, ctx)
    changes: dict[str, str] = {}
    if wanted is not None and wanted != row["role"]:
        changes["role"] = wanted
    if name is not None and name != (row["display_name"] or ""):
        changes["display_name"] = name
    if changes:
        sets = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(f"UPDATE users SET {sets}, updated_at = ? WHERE id = ?", (*changes.values(), utcnow(), row["id"]))
        if "role" in changes:
            audit(conn, None, "user.role_changed", "user", row["id"], ip=ip, old=row["role"], new=changes["role"], via="proxy_groups")
        conn.commit()
        row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (row["id"],)).fetchone()
    return user_from_row(row)
