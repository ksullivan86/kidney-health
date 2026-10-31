"""Connections, the import ledger, and adding fetched readings to the log (design note 27 §2, §3; schema step 29).

* **Tokens** are sealed with :class:`app.crypto.Keyring` under purpose ``device:<provider>`` and the person's id as owner, so a
  ciphertext copied to another person's row does not open. They are read only by :func:`load_tokens`, for a sync, and never
  appear in a view, a log line or an audit row.
* **The ledger** (``device_imports``) remembers every measure the sync has seen, imported or not, so a reading the person deleted
  never comes back and a measure is looked at once.
* **Adding readings** (:func:`add_readings`) only inserts. A reading is not added when the person already has one at the same date
  and minute with the same numbers, **from any source, typed ones included** (a typed copy of the cuff's display is the same
  reading), when its ``source_key`` is already there (a restored export), when it is outside the app's plausibility ranges or
  dated after today, or when its day already holds the most rows a day may hold. Nothing that is already in the log is changed.

Every function takes the person's id and never commits unless it says so.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from pydantic import ValidationError

from ..body import context_for, round_kg
from ..crypto import InvalidToken, Keyring
from ..db import utcnow
from ..models import MAX_READINGS_PER_DAY, MAX_WEIGHTS_PER_DAY, BloodPressureCreate, WeightCreate
from .base import ProviderError, Reading, TokenSet

STATUS_ACTIVE = "active"
STATUS_NEEDS_RECONNECT = "needs_reconnect"
_CHUNK = 400


def purpose(provider: str) -> str:
    return f"device:{provider}"


def connection(conn: sqlite3.Connection, user_id: int, provider: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM device_connections WHERE user_id = ? AND provider = ?", (user_id, provider)).fetchone()


def _iso_after(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sealed(keyring: Keyring, user_id: int, provider: str, tokens: TokenSet) -> tuple[bytes, str]:
    return keyring.seal(purpose=purpose(provider), owner=int(user_id), fields={"access": tokens.access, "refresh": tokens.refresh})


def connect(conn: sqlite3.Connection, keyring: Keyring, user_id: int, provider: str, tokens: TokenSet) -> int:
    """Save a new or renewed connection (no commit). Raises :class:`ProviderError` ``account_taken`` when that company account is
    connected to another person on this server."""
    other = conn.execute("SELECT user_id FROM device_connections WHERE provider = ? AND external_user_id = ? AND user_id <> ?",
                         (provider, tokens.external_user_id, user_id)).fetchone()
    if other is not None:
        raise ProviderError("account_taken", "account_taken")
    sealed, key_id = _sealed(keyring, user_id, provider, tokens)
    now = utcnow()
    expires = _iso_after(tokens.expires_in)
    row = connection(conn, user_id, provider)
    if row is None:
        cur = conn.execute(
            "INSERT INTO device_connections (user_id, provider, external_user_id, tokens_enc, key_id, access_expires_at, scopes, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, provider, tokens.external_user_id, sealed, key_id, expires, tokens.scopes, STATUS_ACTIVE, now, now))
        return int(cur.lastrowid or 0)
    # Connecting again (after "needs reconnect"): a different company account starts its own "changed since" mark.
    same_account = row["external_user_id"] == tokens.external_user_id
    conn.execute(
        "UPDATE device_connections SET external_user_id = ?, tokens_enc = ?, key_id = ?, access_expires_at = ?, scopes = ?, "
        "status = ?, last_error = NULL, next_sync_after = NULL, sync_cursor = ?, updated_at = ? WHERE id = ? AND user_id = ?",
        (tokens.external_user_id, sealed, key_id, expires, tokens.scopes, STATUS_ACTIVE, row["sync_cursor"] if same_account else None,
         now, row["id"], user_id))
    return int(row["id"])


def save_refreshed(conn: sqlite3.Connection, keyring: Keyring, row: sqlite3.Row, tokens: TokenSet) -> None:
    """Keep a refreshed pair at once and commit: Withings' old refresh token stops working 8 hours after the new one is made."""
    sealed, key_id = _sealed(keyring, int(row["user_id"]), row["provider"], tokens)
    conn.execute("UPDATE device_connections SET tokens_enc = ?, key_id = ?, access_expires_at = ?, updated_at = ? "
                 "WHERE id = ? AND user_id = ?", (sealed, key_id, _iso_after(tokens.expires_in), utcnow(), row["id"], row["user_id"]))
    conn.commit()


def load_tokens(keyring: Keyring, row: sqlite3.Row) -> tuple[str, str] | None:
    """``(access, refresh)``, or None when there are none or they cannot be read (the secret key changed)."""
    if row["tokens_enc"] is None:
        return None
    try:
        fields = keyring.unseal(row["tokens_enc"], purpose=purpose(row["provider"]), owner=int(row["user_id"]))
    except InvalidToken:
        return None
    access, refresh = fields.get("access"), fields.get("refresh")
    return (access, refresh) if access and refresh else None


def mark(conn: sqlite3.Connection, row: sqlite3.Row, *, error: str | None, cursor: str | None = None,
         needs_reconnect: bool = False, pause_s: int | None = None) -> None:
    """Record a sync try (and commit): the error code or none, the new cursor, a pause, or "needs reconnect" (tokens deleted)."""
    now = utcnow()
    sets = ["last_sync_at = ?", "last_error = ?", "updated_at = ?"]
    params: list[Any] = [now, error, now]
    if error is None:
        sets.append("last_success_at = ?")
        params.append(now)
        sets.append("next_sync_after = NULL")
    if cursor is not None:
        sets.append("sync_cursor = ?")
        params.append(cursor)
    if pause_s is not None:
        sets.append("next_sync_after = ?")
        params.append(_iso_after(pause_s))
    if needs_reconnect:
        sets += ["status = ?", "tokens_enc = NULL", "key_id = NULL", "access_expires_at = NULL"]
        params.append(STATUS_NEEDS_RECONNECT)
    conn.execute(f"UPDATE device_connections SET {', '.join(sets)} WHERE id = ? AND user_id = ?", (*params, row["id"], row["user_id"]))
    conn.commit()


def imported_counts(conn: sqlite3.Connection, user_id: int, provider: str) -> dict[str, int]:
    """How many of the person's weights and readings still say they came from ``provider``."""
    w = conn.execute("SELECT COUNT(*) FROM weights WHERE user_id = ? AND source = ?", (user_id, provider)).fetchone()[0]
    r = conn.execute("SELECT COUNT(*) FROM blood_pressures WHERE user_id = ? AND source = ?", (user_id, provider)).fetchone()[0]
    return {"weights": int(w), "readings": int(r)}


def view(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, Any] | None:
    """What the person sees about a connection. Never a token, never the company's id for the person."""
    if row is None:
        return None
    return {
        "status": row["status"],
        "connected_at": row["created_at"],
        "last_sync_at": row["last_sync_at"],
        "last_success_at": row["last_success_at"],
        "last_error": row["last_error"],
        "imported": imported_counts(conn, int(row["user_id"]), row["provider"]),
    }


def disconnect(conn: sqlite3.Connection, user_id: int, provider: str, *, delete_readings: bool) -> dict[str, int]:
    """Remove the connection (its tokens go with it; no commit). With ``delete_readings`` also the rows that still say they came
    from ``provider`` and the ledger, so a later connection brings them back; otherwise the ledger stays, so a reading the person
    deleted stays deleted after connecting again. Rows the person edited are theirs (``manual``) and are always kept."""
    conn.execute("DELETE FROM device_connections WHERE user_id = ? AND provider = ?", (user_id, provider))
    removed = {"weights": 0, "readings": 0}
    if delete_readings:
        removed["weights"] = int(conn.execute("DELETE FROM weights WHERE user_id = ? AND source = ?", (user_id, provider)).rowcount or 0)
        removed["readings"] = int(conn.execute("DELETE FROM blood_pressures WHERE user_id = ? AND source = ?",
                                               (user_id, provider)).rowcount or 0)
        conn.execute("DELETE FROM device_imports WHERE user_id = ? AND provider = ?", (user_id, provider))
    return removed


# --------------------------------------------------------------------------- #
# Adding readings
# --------------------------------------------------------------------------- #


def _chunks(items: list[Any]) -> Iterable[list[Any]]:
    for i in range(0, len(items), _CHUNK):
        yield items[i:i + _CHUNK]


def _seen(conn: sqlite3.Connection, user_id: int, provider: str, ids: list[str]) -> set[str]:
    out: set[str] = set()
    for part in _chunks(ids):
        marks = ", ".join("?" for _ in part)
        out |= {r[0] for r in conn.execute(f"SELECT external_id FROM device_imports WHERE user_id = ? AND provider = ? "
                                           f"AND external_id IN ({marks})", (user_id, provider, *part))}
    return out


def _day_rows(conn: sqlite3.Connection, table: str, user_id: int, days: set[str]) -> list[sqlite3.Row]:
    assert table in ("weights", "blood_pressures")
    rows: list[sqlite3.Row] = []
    for part in _chunks(sorted(days)):
        marks = ", ".join("?" for _ in part)
        rows += conn.execute(f"SELECT * FROM {table} WHERE user_id = ? AND date IN ({marks})", (user_id, *part)).fetchall()
    return rows


def _keys(conn: sqlite3.Connection, table: str, user_id: int, keys: list[str]) -> set[str]:
    assert table in ("weights", "blood_pressures")
    out: set[str] = set()
    for part in _chunks(keys):
        marks = ", ".join("?" for _ in part)
        out |= {r[0] for r in conn.execute(f"SELECT source_key FROM {table} WHERE user_id = ? AND source_key IN ({marks})",
                                           (user_id, *part))}
    return out


def add_readings(conn: sqlite3.Connection, user_id: int, provider: str, readings: list[Reading]) -> dict[str, Any]:
    """Add what the person does not have yet and record every measure in the ledger, in one transaction (committed here).
    Returns ``{added: {weights, readings}, already_there, skipped}``."""
    from ..auth.accounts import begin_immediate

    added = {"weights": 0, "readings": 0}
    there = skipped = 0
    unique: dict[str, Reading] = {}
    for r in readings:
        unique.setdefault(r.external_id, r)  # one fetch may list a group twice across pages
    begin_immediate(conn)
    try:
        seen = _seen(conn, user_id, provider, list(unique))
        fresh = [r for r in unique.values() if r.external_id not in seen]
        weights_there = _day_rows(conn, "weights", user_id, {r.date for r in fresh if r.kind == "weight"})
        readings_there = _day_rows(conn, "blood_pressures", user_id, {r.date for r in fresh if r.kind == "blood_pressure"})
        wmarks = {(w["date"], w["time"], round_kg(w["kg"])) for w in weights_there if w["time"]}
        rmarks = {(b["date"], b["time"], b["systolic"], b["diastolic"]) for b in readings_there if b["time"]}
        wday: dict[str, int] = {}
        for w in weights_there:
            wday[w["date"]] = wday.get(w["date"], 0) + 1
        rday: dict[str, int] = {}
        for b in readings_there:
            rday[b["date"]] = rday.get(b["date"], 0) + 1
        keys_there = _keys(conn, "weights", user_id, [f"{provider}:{r.external_id}" for r in fresh if r.kind == "weight"])
        keys_there |= _keys(conn, "blood_pressures", user_id, [f"{provider}:{r.external_id}" for r in fresh if r.kind == "blood_pressure"])
        now = utcnow()
        for r in fresh:
            key = f"{provider}:{r.external_id}"
            row_id: int | None = None
            if r.kind == "weight":
                try:
                    data = WeightCreate(date=r.date, time=r.time, kg=r.kg, context=context_for("weight", r.time))
                except ValidationError:
                    skipped += 1
                else:
                    mark_ = (data.date, data.time, round_kg(data.kg))
                    if key in keys_there or mark_ in wmarks:
                        there += 1
                    elif wday.get(data.date, 0) >= MAX_WEIGHTS_PER_DAY:
                        skipped += 1
                    else:
                        row_id = int(conn.execute(
                            "INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?)",
                            (user_id, data.date, data.time, round_kg(data.kg), data.context, provider, key, now, now)).lastrowid or 0)
                        wmarks.add(mark_)
                        wday[data.date] = wday.get(data.date, 0) + 1
                        added["weights"] += 1
            elif r.kind == "blood_pressure":
                pulse = r.pulse
                try:
                    reading = BloodPressureCreate(date=r.date, time=r.time, systolic=r.systolic, diastolic=r.diastolic,
                                                  pulse=pulse, context=context_for("reading", r.time))
                except ValidationError:
                    try:  # a pulse out of range drops the pulse, not the reading
                        reading = BloodPressureCreate(date=r.date, time=r.time, systolic=r.systolic, diastolic=r.diastolic,
                                                      pulse=None, context=context_for("reading", r.time))
                    except ValidationError:
                        reading = None
                if reading is None:
                    skipped += 1
                else:
                    mark_r = (reading.date, reading.time, reading.systolic, reading.diastolic)
                    if key in keys_there or mark_r in rmarks:
                        there += 1
                    elif rday.get(reading.date, 0) >= MAX_READINGS_PER_DAY:
                        skipped += 1
                    else:
                        row_id = int(conn.execute(
                            "INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, "
                            "source_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)",
                            (user_id, reading.date, reading.time, reading.systolic, reading.diastolic, reading.pulse, reading.context,
                             provider, key, now, now)).lastrowid or 0)
                        rmarks.add(mark_r)
                        rday[reading.date] = rday.get(reading.date, 0) + 1
                        added["readings"] += 1
            else:
                skipped += 1
            conn.execute("INSERT OR IGNORE INTO device_imports (user_id, provider, external_id, kind, row_id, imported_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (user_id, provider, r.external_id, r.kind, row_id, now))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {"added": added, "already_there": there + (len(unique) - len(fresh)), "skipped": skipped}
