"""Step 23: passkeys (design note 18 §4).

One new table, ``passkeys``: one row per passkey a person has added. ``credential_id`` is the ID the authenticator chose
(unique across the server, at most 1,023 bytes); ``public_key`` is the COSE key exactly as the authenticator sent it, and ``alg``
its COSE algorithm. A public key is not a secret, so nothing is sealed. ``user_handle`` is the random 32 bytes the passkey was
made for (the same for all of one person's passkeys); ``sign_count`` the last signature counter; ``backed_up`` whether the
authenticator said it is synced to a cloud keychain.

Rows cascade when the account is deleted. Nothing existing changes. Idempotent: ``IF NOT EXISTS`` throughout.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 23
DESCRIPTION = "passkeys (sign in with a fingerprint, face or device PIN)"

SCHEMA = ""  # references users (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS passkeys (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  credential_id BLOB NOT NULL UNIQUE CHECK (length(credential_id) BETWEEN 1 AND 1023),
  public_key BLOB NOT NULL,
  alg INTEGER NOT NULL,
  user_handle BLOB NOT NULL CHECK (length(user_handle) BETWEEN 1 AND 64),
  sign_count INTEGER NOT NULL DEFAULT 0 CHECK (sign_count >= 0),
  name TEXT NOT NULL,
  backed_up INTEGER NOT NULL DEFAULT 0 CHECK (backed_up IN (0, 1)),
  created_at TEXT NOT NULL,
  last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS passkeys_user ON passkeys(user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
