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

The Ask chat (assistant step 2, part C) saves with the same two tools and has no token: its keys are made from the
chat request's own ``request_id`` and live in ``assistant_ask_keys`` (schema step 13), selected by passing
``token_id=None``. The hash there covers the person's id and the key, so another person's identical key is another key.

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


def ask_key_hash(user_id: int, key: str) -> str:
    """The same for the Ask chat, which has no token: SHA-256 of the person's id and the key."""
    return hashlib.sha256(f"ask-request-key\x00{int(user_id)}\x00{key}".encode("utf-8")).hexdigest()


def _cutoff() -> str:
    return clock.iso(clock.now() - KEEP)


def find(conn: sqlite3.Connection, user_id: int, token_id: int | None, key: str) -> Seen | None:
    """The save this token (``None``: the Ask chat) made with ``key`` in the last 24 hours, or None. Read-only."""
    if token_id is None:
        row = conn.execute(
            """SELECT tool, saved_json, created_at FROM assistant_ask_keys
               WHERE key_hash = ? AND user_id = ? AND created_at > ?""",
            (ask_key_hash(user_id, key), int(user_id), _cutoff()),
        ).fetchone()
        return None if row is None else Seen(row["tool"], json.loads(row["saved_json"]), row["created_at"])
    row = conn.execute(
        """SELECT tool, saved_json, created_at FROM assistant_request_keys
           WHERE key_hash = ? AND user_id = ? AND token_id = ? AND created_at > ?""",
        (key_hash(token_id, key), int(user_id), int(token_id), _cutoff()),
    ).fetchone()
    if row is None:
        return None
    return Seen(row["tool"], json.loads(row["saved_json"]), row["created_at"])


def remember(conn: sqlite3.Connection, user_id: int, token_id: int | None, tool: str, key: str,
             saved: dict[str, Any]) -> None:
    """Write the key in the save's own transaction (no commit), after deleting the rows older than 24 hours."""
    conn.execute("DELETE FROM assistant_request_keys WHERE created_at <= ?", (_cutoff(),))
    conn.execute("DELETE FROM assistant_ask_keys WHERE created_at <= ?", (_cutoff(),))
    if token_id is None:
        conn.execute(
            """INSERT INTO assistant_ask_keys (key_hash, user_id, tool, saved_json, created_at) VALUES (?, ?, ?, ?, ?)""",
            (ask_key_hash(user_id, key), int(user_id), tool, json.dumps(saved, separators=(",", ":")), clock.now_iso()),
        )
        return
    conn.execute(
        """INSERT INTO assistant_request_keys (key_hash, user_id, token_id, tool, saved_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (key_hash(token_id, key), int(user_id), int(token_id), tool, json.dumps(saved, separators=(",", ":")),
         clock.now_iso()),
    )


def purge_old(conn: sqlite3.Connection) -> int:
    """Delete keys older than 24 hours, a token's and the Ask chat's (commits). Returns how many."""
    removed = 0
    for table in ("assistant_request_keys", "assistant_ask_keys"):
        if table_exists(conn, table):
            removed += int(conn.execute(f"DELETE FROM {table} WHERE created_at <= ?", (_cutoff(),)).rowcount or 0)
    conn.commit()
    return removed


housekeeping.register_daily("assistant_request_keys", lambda conn, ctx: purge_old(conn))
