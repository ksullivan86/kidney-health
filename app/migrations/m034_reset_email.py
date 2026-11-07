"""Step 34: password reset by email (design note 34).

* ``users.email`` (TEXT, NULL = none, at most 320 characters, stored lower-cased): the address a person gave in Settings →
  Account for password resets. Optional.
* ``users.email_confirmed_at`` (TEXT, UTC, NULL = not confirmed yet): set when the person opened the confirmation link sent to
  that address. Only a confirmed address gets reset emails.
* Unique index ``users_email_confirmed`` on ``email`` for confirmed addresses only. An address typed but not confirmed never
  blocks the real owner from confirming it on their own account.
* ``email_tokens``: the confirmation links (single use, 24 hours). Like ``auth_tokens``, only the SHA-256 of the verifier is
  stored. Each row keeps the address it was sent to, so a link for an older address never confirms a newer one. Rows hang off
  ``users`` with ``ON DELETE CASCADE``.

Every existing account starts with no address. Idempotent: columns are added only when missing, the rest is ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 34
DESCRIPTION = "password reset by email: users.email, users.email_confirmed_at, email_tokens"

SCHEMA = ""  # alters users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS users_email_confirmed ON users(email)
  WHERE email IS NOT NULL AND email_confirmed_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS email_tokens (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,                         -- the address the link was sent to
  verifier_hash BLOB NOT NULL,                 -- SHA-256 of the verifier; the link itself is never stored
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE INDEX IF NOT EXISTS email_tokens_user ON email_tokens(user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "users", "email", "TEXT CHECK (email IS NULL OR length(email) <= 320)")
    add_column_if_missing(conn, "users", "email_confirmed_at", "TEXT")
    execute_script(conn, DDL)
