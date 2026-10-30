"""Step 10: assistant access tokens (``docs/dev/plans/assistant-step1.md`` part A; ARCHITECTURE "Assistant access").

``api_tokens`` holds the personal tokens a person makes in Settings → Outside AI apps for a chat assistant
they connect. Only the SHA-256 of the whole token is stored (``token_hash``, 64 hex characters); ``prefix``
keeps its first 12 characters (``kha_`` and 8 more) so the list can tell tokens apart. ``scopes`` is a
space-separated list of known scopes (``assistant:read`` in this step). A token works while it is neither
revoked nor expired, the person is active and the instance switch ``assistant.enabled`` is on
(``app/auth/api_tokens.py``).

``user_id`` references ``users`` with ``ON DELETE CASCADE``, so deleting an account removes its tokens.
``AUTOINCREMENT`` so a removed token's id is never given to another token (activity rows keep the id).
Idempotent: ``IF NOT EXISTS`` everywhere.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 10
DESCRIPTION = "assistant access tokens (api_tokens)"

SCHEMA = ""  # references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  prefix TEXT NOT NULL CHECK (length(prefix) = 12),
  scopes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens(user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
