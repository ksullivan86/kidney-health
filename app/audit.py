"""Append-only audit log of admin and security events (note 07 §4.13).

Call :func:`audit` inside the same transaction as the change it records (it never commits). Rows
hold ids, never names, secret values or health data; ``details`` keys that look like secrets are
refused. ``UPDATE`` is blocked by a trigger; only retention (:func:`purge_expired`) deletes rows.
The table is created by schema step 3 through :func:`create_audit_table`.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .db import table_exists, utcnow

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor_user_id INTEGER,
  ip_prefix TEXT,
  action TEXT NOT NULL,
  target_type TEXT, target_id TEXT,
  details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_at ON audit_log(at);
CREATE TRIGGER IF NOT EXISTS audit_log_append_only BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def create_audit_table(conn: sqlite3.Connection) -> None:
    """Create ``audit_log`` with its index and append-only trigger (idempotent, transaction-safe)."""
    from .db import execute_script

    execute_script(conn, AUDIT_DDL)


# Note 07 §4.13 (+ §9 N2, N7). Other notes add theirs with register_action().
ACTIONS: set[str] = {
    "setup.completed",
    "login.succeeded",
    "login.failed",
    "user.locked",
    "user.invited",
    "invite.revoked",
    "user.registered",
    "user.created_by_proxy",
    "user.role_changed",
    "user.disabled",
    "user.enabled",
    "user.deleted",
    "user.updated",
    "user.reset_link_issued",
    "user.reset_link_revoked",
    "user.password_changed",
    "user.must_change_password",
    "sessions.revoked",
    "session.revoked_reauth",
    "proxy.username_conflict",
    "settings.changed",
    "secret.set",
    "secret.removed",
    "ai_provider.changed",
    "export.created",
    "account.deleted",
    "secret_key.rotated",
    "backup.created",
}
USER_VISIBLE_ACTIONS = frozenset(
    {
        "login.succeeded",
        "login.failed",
        "user.locked",
        "user.password_changed",
        "user.reset_link_issued",
        "user.reset_link_revoked",
        "user.must_change_password",
        "sessions.revoked",
        "session.revoked_reauth",
        "secret.set",
        "secret.removed",
        "export.created",
    }
)
_ACTION = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SECRETISH = re.compile(r"(?i)(password|passwd|secret|token|api_?key|last4|cookie|verifier|ciphertext|^(setup_|invite_|reset_)?code$)")
_MAX_DETAILS = 4096


def register_action(name: str) -> None:
    if not _ACTION.match(name):
        raise ValueError(f"audit action {name!r} must look like 'area.verb'")
    ACTIONS.add(name)


def ip_prefix(address: str | None) -> str | None:
    """IPv4 /24 or IPv6 /48 of ``address`` (what audit rows and the device list keep)."""
    if not address:
        return None
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    prefix = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


def _check_details(details: dict[str, Any]) -> str:
    for key in details:
        if _SECRETISH.search(str(key)):
            raise ValueError(f"audit details must not carry secrets (key {key!r})")
    text = json.dumps(details, separators=(",", ":"), sort_keys=True, default=str)
    if len(text) > _MAX_DETAILS:
        raise ValueError("audit details are too large")
    return text


def audit(
    conn: sqlite3.Connection,
    actor_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    *,
    ip: str | None = None,
    **details: Any,
) -> int:
    """Append one event (no commit). ``ip`` is reduced to its prefix. Returns the row id."""
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r} (register it with app.audit.register_action)")
    cur = conn.execute(
        """INSERT INTO audit_log (at, actor_user_id, ip_prefix, action, target_type, target_id, details_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            utcnow(),
            actor_id,
            ip_prefix(ip),
            action,
            target_type,
            None if target_id is None else str(target_id),
            _check_details(details),
        ),
    )
    return int(cur.lastrowid or 0)


def audit_if_available(conn: sqlite3.Connection, actor_id: int | None, action: str, **kwargs: Any) -> int | None:
    """:func:`audit` when the table exists (the CLI also runs against pre-v3 databases)."""
    if not table_exists(conn, "audit_log"):
        return None
    return audit(conn, actor_id, action, **kwargs)


def _row(row: sqlite3.Row | tuple) -> dict[str, Any]:
    keys = ("id", "at", "actor_user_id", "ip_prefix", "action", "target_type", "target_id", "details_json")
    data = dict(zip(keys, tuple(row), strict=True))
    data["details"] = json.loads(data.pop("details_json") or "{}")
    return data


def list_events(
    conn: sqlite3.Connection,
    *,
    before: int | None = None,
    limit: int = 50,
    actor_user_id: int | None = None,
    actions: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Newest first, paged by ``before`` (an id). ``actor_user_id`` + ``actions`` give a person's activity:
    events about their own account (whoever acted, e.g. an admin's reset link for it) and what they did
    themselves, except actions on another person's account (those belong in the admin log only)."""
    where, params = [], []
    if before is not None:
        where.append("id < ?")
        params.append(int(before))
    if actor_user_id is not None:
        uid = int(actor_user_id)
        where.append(
            "((target_type = 'user' AND target_id = ?)"
            " OR (actor_user_id = ? AND (COALESCE(target_type, '') != 'user' OR target_id IS NULL OR target_id = ?)))"
        )
        params.extend([str(uid), uid, str(uid)])
    if actions is not None:
        names = sorted(set(actions))
        if not names:
            return []
        where.append(f"action IN ({', '.join('?' for _ in names)})")
        params.extend(names)
    sql = "SELECT id, at, actor_user_id, ip_prefix, action, target_type, target_id, details_json FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [_row(r) for r in conn.execute(sql, params).fetchall()]


def purge_expired(conn: sqlite3.Connection, retention_days: int, *, now: datetime | None = None) -> int:
    """Delete rows older than ``retention_days`` (no commit). Returns the number deleted."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=int(retention_days))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cur = conn.execute("DELETE FROM audit_log WHERE at < ?", (cutoff,))
    return int(cur.rowcount or 0)
