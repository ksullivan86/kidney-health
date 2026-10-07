"""Periodic clean-up, run from request paths (no background threads; one process).

* hourly: expired sessions (§4.7) and idle sign-in throttle rows (§4.9);
* daily: audit rows past ``audit.retention_days`` (§4.13), the pre-v3 backup once it is 30 days
  old (§9 N11), and every task a feature registered with :func:`register_daily` (the AI activity
  retention of note 04 §9 A8, so it runs whether or not AI is on or used).

Start-up runs the same steps (:mod:`app.auth.bootstrap`, :func:`app.main._startup_maintenance`).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import TYPE_CHECKING, Callable

from . import clock, sessions

if TYPE_CHECKING:  # pragma: no cover
    from .context import AuthContext

log = logging.getLogger("kidney_health.auth")

HOURLY_S = 3600
DAILY_S = 86400

_lock = threading.Lock()

DailyTask = Callable[[sqlite3.Connection, "AuthContext"], None]
_daily_tasks: dict[str, DailyTask] = {}


def register_daily(name: str, task: DailyTask) -> None:
    """Run ``task(conn, ctx)`` with the daily step (after the audit purge). A task commits its own
    work; an error is logged and rolled back without stopping the others. Registering a name again
    replaces the task (one per feature, whatever the number of app instances in a process)."""
    with _lock:
        _daily_tasks[name] = task


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
            with _lock:
                tasks = list(_daily_tasks.items())
            for name, task in tasks:
                try:
                    task(conn, ctx)
                except Exception:
                    log.exception("daily housekeeping task %s failed", name)
                    if conn.in_transaction:
                        conn.rollback()
    except Exception:  # pragma: no cover - logged, never fatal
        log.exception("housekeeping failed")
        if conn.in_transaction:
            conn.rollback()
