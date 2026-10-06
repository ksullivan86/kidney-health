"""Periodic clean-up, run from request paths (no background threads; one process).

* hourly: expired sessions (§4.7) and idle sign-in throttle rows (§4.9);
* daily: audit rows past ``audit.retention_days`` (§4.13) and the pre-v3 backup once it is 30 days
  old (§9 N11).

Start-up runs the same steps (:mod:`app.auth.bootstrap`, :func:`app.main._startup_maintenance`).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import TYPE_CHECKING

from . import clock, sessions

if TYPE_CHECKING:  # pragma: no cover
    from .context import AuthContext

log = logging.getLogger("kidney_health.auth")

HOURLY_S = 3600
DAILY_S = 86400

_lock = threading.Lock()


def _due(ctx: "AuthContext", name: str, every_s: float) -> bool:
    now = clock.seconds()
    with _lock:
        stamps = ctx.housekeeping
        if name not in stamps:
            stamps[name] = now  # start-up just did it
            return False
        if now - stamps[name] < every_s:
            return False
        stamps[name] = now
        return True


def run(conn: sqlite3.Connection, ctx: "AuthContext") -> None:
    """Do whatever is due; never raises (housekeeping must not break a request)."""
    try:
        if _due(ctx, "hourly", HOURLY_S):
            sessions.purge_expired(conn, idle_days=ctx.settings.session_idle_days)
            ctx.throttle.prune(conn)
            conn.commit()
        if _due(ctx, "daily", DAILY_S):
            from ..audit import purge_expired
            from .bootstrap import expire_pre_v3_backup

            removed = purge_expired(conn, int(ctx.store.get(conn, "audit.retention_days")))
            conn.commit()
            if removed:
                log.info("audit log: removed %d entries past the retention period", removed)
            expire_pre_v3_backup(conn)
    except Exception:  # pragma: no cover - logged, never fatal
        log.exception("housekeeping failed")
        if conn.in_transaction:
            conn.rollback()
