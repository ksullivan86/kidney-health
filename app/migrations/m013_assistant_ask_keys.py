"""Step 13: duplicate guard for the Ask chat's saves (``docs/dev/plans/assistant-step2.md`` part C; ARCHITECTURE "Ask chat").

When a person trusts the Ask chat to save for them, a chat request that is sent twice (a lost answer, a tap on
Send again) must not save twice. Each save carries a key made from the request's own ``request_id``; the first save
with a key remembers it in the same transaction, and a second one with the same key answers with what the first
saved. It is the same idea as step 11's ``assistant_request_keys`` for access tokens, in its own table because an
Ask save has no token (that table's ``token_id`` is ``NOT NULL`` and references ``api_tokens``).

``assistant_ask_keys``: ``key_hash`` is the SHA-256 (64 hex characters) of the key together with the person's id, so
the plain key is never stored and another person's identical key is another key; ``tool`` is ``log_food`` or
``save_recipe``; ``saved_json`` holds what was saved (entry ids, or the saved meal's id) so a repeat can read them from
the database again, for that person only; ``created_at`` is when (rows older than 24 hours are ignored and deleted).

``user_id`` references ``users`` with ``ON DELETE CASCADE``. Idempotent: ``IF NOT EXISTS`` everywhere. Nothing else
changes: the trust choice itself is a field of the person's ``ai`` setting, not a column.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 13
DESCRIPTION = "assistant ask keys (duplicate guard for the Ask chat's saves)"

SCHEMA = ""  # references users (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS assistant_ask_keys (
  key_hash TEXT PRIMARY KEY CHECK (length(key_hash) = 64),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tool TEXT NOT NULL CHECK (length(tool) BETWEEN 1 AND 40),
  saved_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_ask_keys_created ON assistant_ask_keys(created_at);
CREATE INDEX IF NOT EXISTS assistant_ask_keys_user ON assistant_ask_keys(user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
