"""Step 11: duplicate guard for the assistant's saving tools (``docs/assistant.md`` "Retries"; ARCHITECTURE "Assistant
MCP server").

Chat clients retry tool calls. ``log_food`` and ``save_recipe`` take an optional ``request_key``; a second call with
the same key by the same token within 24 hours does not save again, it answers with what the first call saved.
``assistant_request_keys`` remembers the first call: ``key_hash`` is the SHA-256 (64 hex characters) of the token's
id together with the key, so the plain key is never stored; ``tool`` is the tool that saved; ``saved_json`` holds
what it saved (entry ids, or the saved meal's id) so the repeat can read them from the database again, for that
person only; ``created_at`` is when (rows older than 24 hours are ignored and deleted).

``user_id`` and ``token_id`` reference ``users`` and ``api_tokens`` with ``ON DELETE CASCADE``: deleting an account
or purging an old token removes its keys. Idempotent: ``IF NOT EXISTS`` everywhere.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 11
DESCRIPTION = "assistant request keys (duplicate guard for log_food and save_recipe)"

SCHEMA = ""  # references users and api_tokens (steps 3 and 10), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS assistant_request_keys (
  key_hash TEXT PRIMARY KEY CHECK (length(key_hash) = 64),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_id INTEGER NOT NULL REFERENCES api_tokens(id) ON DELETE CASCADE,
  tool TEXT NOT NULL CHECK (length(tool) BETWEEN 1 AND 40),
  saved_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant_request_keys_created ON assistant_request_keys(created_at);
CREATE INDEX IF NOT EXISTS assistant_request_keys_user ON assistant_request_keys(user_id);
CREATE INDEX IF NOT EXISTS assistant_request_keys_token ON assistant_request_keys(token_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
