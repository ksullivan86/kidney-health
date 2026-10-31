"""Fetching each person's readings (design note 27 §2.1, §2.11): one connection at a time, and the loop that syncs everyone.

:func:`sync_connection` refreshes the access token when it is about to run out (and keeps the new pair at once), fetches what
changed since the connection's cursor (the first time: the last year), adds it with :func:`app.devices.store.add_readings` and
records how it went. A refusal of the tokens, even after one refresh, deletes them and marks the connection "needs reconnect";
"too many requests" pauses that connection for an hour; anything else is kept as an error code and tried again next time. The
Activity list gets one row when a connection's error changes, not one per retry.

The loop (:func:`loop`, started by the app's lifespan) wakes every 10 minutes and, while ``devices.enabled`` is on, syncs each
connection whose last try is older than ``devices.sync_hours``, one after another (Withings allows 120 requests a minute per
app). It never syncs a disabled account or a test account. No request path waits for it.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import brand
from ..audit import audit
from ..config import Settings
from ..crypto import Keyring
from ..settings_store import SettingsStore
from . import store
from .base import Provider, ProviderError
from .whoop import WhoopProvider
from .withings import WithingsProvider

log = logging.getLogger(f"{brand.LOGGER_NAME}.devices")

FIRST_DAYS = 365  # the first sync reaches this far back (a provider may say less: Whoop's ``first_days`` is 90)
REFRESH_MARGIN_S = 300
RATE_PAUSE_S = 3600
SYNC_NOW_MIN_S = 600  # Withings: "do not poll more than once every 10 minutes per user"
TICK_S = 600
FIRST_TICK_S = 120
BETWEEN_PEOPLE_S = 0.6


class Devices:
    """``app.state.devices``: the providers this server knows, and which connections are being synced right now."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.providers: dict[str, Provider] = {"withings": WithingsProvider(settings.withings),
                                               "whoop": WhoopProvider(settings.whoop)}
        self._busy: set[int] = set()
        self._lock = threading.Lock()

    def provider(self, provider_id: str) -> Provider | None:
        return self.providers.get(provider_id)

    def claim(self, connection_id: int) -> bool:
        with self._lock:
            if connection_id in self._busy:
                return False
            self._busy.add(connection_id)
            return True

    def release(self, connection_id: int) -> None:
        with self._lock:
            self._busy.discard(connection_id)


def today_local() -> str:
    """The server's date, as ``app.log.today_local`` gives it."""
    return datetime.now().date().isoformat()


def _utc(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def seconds_since(text: str | None) -> float | None:
    at = _utc(text)
    return None if at is None else (datetime.now(timezone.utc) - at).total_seconds()


def _record_error(conn: sqlite3.Connection, row: sqlite3.Row, code: str, **kwargs: Any) -> None:
    if row["last_error"] != code:
        audit(conn, int(row["user_id"]), "device.sync_failed", "device", row["provider"], provider=row["provider"], error=code)
    store.mark(conn, row, error=code, **kwargs)


def sync_connection(conn: sqlite3.Connection, keyring: Keyring, provider: Provider, row: sqlite3.Row) -> dict[str, Any]:
    """Sync one connection and record the outcome (commits). Returns the counts; raises :class:`ProviderError` after recording
    a failure."""
    pair = store.load_tokens(keyring, row)
    if pair is None:
        _record_error(conn, row, "auth", needs_reconnect=True)
        raise ProviderError("auth", "no_tokens")
    access, refresh_token = pair
    refreshed = False

    def refresh() -> str:
        nonlocal refreshed
        tokens = provider.refresh(refresh_token)
        store.save_refreshed(conn, keyring, row, tokens)
        refreshed = True
        return tokens.access

    try:
        expires = _utc(row["access_expires_at"])
        if expires is None or expires - datetime.now(timezone.utc) < timedelta(seconds=REFRESH_MARGIN_S):
            access = refresh()
        since = int(time.time()) - int(getattr(provider, "first_days", FIRST_DAYS)) * 86400
        try:
            result = provider.fetch(access, cursor=row["sync_cursor"], since=since)
        except ProviderError as exc:
            if exc.code != "auth" or refreshed:
                raise
            access = refresh()  # an access token Withings ended early: one refresh, then once more
            result = provider.fetch(access, cursor=row["sync_cursor"], since=since)
    except ProviderError as exc:
        if exc.code == "auth":
            _record_error(conn, row, "auth", needs_reconnect=True)
        elif exc.code == "rate_limited":
            _record_error(conn, row, "rate_limited", pause_s=RATE_PAUSE_S)
        else:
            _record_error(conn, row, exc.code)
        raise
    if result.external_user_id and not row["external_user_id"]:
        try:
            store.set_external(conn, row, result.external_user_id)
        except ProviderError:  # that company account is connected to someone else here: nothing of it is kept
            conn.rollback()
            _record_error(conn, row, "account_taken", needs_reconnect=True)
            raise
        conn.commit()
    counts = store.add_readings(conn, int(row["user_id"]), row["provider"], result.readings)
    activity = store.add_activity(conn, int(row["user_id"]), row["provider"], result.days, result.workouts, today=today_local())
    store.mark(conn, row, error=None, cursor=result.cursor)
    counts["added"].update(days=activity["days"], workouts=activity["workouts"])
    counts["updated"] = activity["updated"]
    counts["skipped"] += activity["skipped"]
    counts["left_out"] = result.left_out
    return counts


def due_connections(conn: sqlite3.Connection, provider_id: str, every_hours: int) -> list[sqlite3.Row]:
    """Active connections of active people (no test accounts) whose last try is older than ``every_hours`` and not paused."""
    rows = conn.execute(
        "SELECT c.* FROM device_connections c JOIN users u ON u.id = c.user_id "
        "WHERE c.provider = ? AND c.status = ? AND c.tokens_enc IS NOT NULL AND u.status <> 'disabled' AND u.is_test_account = 0 "
        "ORDER BY c.last_sync_at IS NOT NULL, c.last_sync_at, c.id", (provider_id, store.STATUS_ACTIVE)).fetchall()
    out = []
    for row in rows:
        age = seconds_since(row["last_sync_at"])
        pause = seconds_since(row["next_sync_after"])
        if (age is None or age >= every_hours * 3600 - 60) and (pause is None or pause >= 0):
            out.append(row)
    return out


def run_due(devices: Devices, keyring: Keyring, settings_store: SettingsStore, db_path: Any) -> int:
    """Sync every connection that is due (one pass of the loop). Returns how many were tried."""
    from ..db import connect

    conn = connect(db_path)
    tried = 0
    try:
        if not settings_store.get(conn, "devices.enabled"):
            return 0
        every = int(settings_store.get(conn, "devices.sync_hours"))
        for provider_id, provider in devices.providers.items():
            if not provider.available:
                continue
            for row in due_connections(conn, provider_id, every):
                if not devices.claim(int(row["id"])):
                    continue
                tried += 1
                try:
                    sync_connection(conn, keyring, provider, row)
                except ProviderError:
                    pass  # recorded on the connection
                except Exception:
                    log.exception("connected devices: a sync failed")
                    if conn.in_transaction:
                        conn.rollback()
                finally:
                    devices.release(int(row["id"]))
                time.sleep(BETWEEN_PEOPLE_S)
    finally:
        conn.close()
    return tried


async def loop(app: Any) -> None:
    """Every :data:`TICK_S`, sync what is due (in a worker thread; the server keeps answering requests)."""
    from starlette.concurrency import run_in_threadpool

    await asyncio.sleep(FIRST_TICK_S)
    while True:
        try:
            await run_in_threadpool(run_due, app.state.devices, app.state.keyring, app.state.settings_store,
                                    app.state.settings.db_path)
        except Exception:
            log.exception("connected devices: the sync loop failed")
        await asyncio.sleep(TICK_S)
