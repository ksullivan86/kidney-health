"""The duplicate guard of ``log_food`` and ``save_recipe`` (schema step 11; ``docs/assistant.md`` "Retries").

Chat clients retry tool calls, and a retried save would put the same food in the log twice. A save may therefore carry
a ``request_key`` (8 to 64 of ``A-Z a-z 0-9 _ -``). The first save with a key remembers it, in the same transaction
as the save; a second call by the **same token** with the **same key** within :data:`KEEP` does not save again, the
tool answers with what the first call saved (read from the database again, for that person, so it shows what is
still there).

* Only the SHA-256 of the token's id together with the key is stored (:func:`key_hash`), never the key. The same key
  on another token, or by another person, is another key.
* Every lookup is scoped by ``user_id`` and ``token_id`` as well as by the hash.
* A failed save stores nothing: the key is written inside the save's transaction, which is rolled back with it.
* Rows older than :data:`KEEP` are ignored by :func:`find`, deleted by the next keyed save and by the daily
  housekeeping (:func:`purge_old`).

Functions never commit unless they say so.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..auth import clock, housekeeping
from ..db import table_exists

KEY_MIN = 8
KEY_MAX = 64
KEY_PATTERN = r"^[A-Za-z0-9_-]+$"
KEY_RE = re.compile(KEY_PATTERN)
KEEP = timedelta(hours=24)


@dataclass(frozen=True)
class Seen:
    """What the first call with a key saved."""

    tool: str
    saved: dict[str, Any]
    created_at: str


def key_hash(token_id: int, key: str) -> str:
    """SHA-256 of the token's id and the key, as 64 hex characters (the key itself is never stored)."""
    return hashlib.sha256(f"request-key\x00{int(token_id)}\x00{key}".encode("utf-8")).hexdigest()


def _cutoff() -> str:
    return clock.iso(clock.now() - KEEP)


def find(conn: sqlite3.Connection, user_id: int, token_id: int, key: str) -> Seen | None:
    """The save this token made with ``key`` in the last 24 hours, or None. Read-only."""
    row = conn.execute(
        """SELECT tool, saved_json, created_at FROM assistant_request_keys
           WHERE key_hash = ? AND user_id = ? AND token_id = ? AND created_at > ?""",
        (key_hash(token_id, key), int(user_id), int(token_id), _cutoff()),
    ).fetchone()
    if row is None:
        return None
    return Seen(row["tool"], json.loads(row["saved_json"]), row["created_at"])


def remember(conn: sqlite3.Connection, user_id: int, token_id: int, tool: str, key: str, saved: dict[str, Any]) -> None:
    """Write the key in the save's own transaction (no commit), after deleting the rows older than 24 hours."""
    conn.execute("DELETE FROM assistant_request_keys WHERE created_at <= ?", (_cutoff(),))
    conn.execute(
        """INSERT INTO assistant_request_keys (key_hash, user_id, token_id, tool, saved_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (key_hash(token_id, key), int(user_id), int(token_id), tool, json.dumps(saved, separators=(",", ":")),
         clock.now_iso()),
    )


def purge_old(conn: sqlite3.Connection) -> int:
    """Delete keys older than 24 hours (commits). Returns how many."""
    if not table_exists(conn, "assistant_request_keys"):
        return 0
    cur = conn.execute("DELETE FROM assistant_request_keys WHERE created_at <= ?", (_cutoff(),))
    conn.commit()
    return int(cur.rowcount or 0)


housekeeping.register_daily("assistant_request_keys", lambda conn, ctx: purge_old(conn))
