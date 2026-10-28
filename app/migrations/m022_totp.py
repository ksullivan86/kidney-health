"""Step 22: two-step sign-in with codes from an authenticator app (design note 17 §4).

Two new tables:

* ``totp_factors``: one row per person who has started or turned on two-step sign-in. ``secret_enc`` is the secret sealed with
  the keyring (purpose ``totp``, owner the person's id; ``app.crypto.ENCRYPTED_COLUMNS`` re-encrypts it on key rotation).
  ``enabled_at`` is NULL until the person has typed the first code. ``last_step`` is the last 30-second step whose code was used,
  so each code works once.
* ``totp_recovery_codes``: the SHA-256 of each of the person's single-use recovery codes, and when it was used.

Both cascade when the account is deleted. Nothing existing changes, so a person signs in as before until they turn it on.
Idempotent: ``IF NOT EXISTS`` throughout.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 22
DESCRIPTION = "totp_factors and totp_recovery_codes (two-step sign-in)"

SCHEMA = ""  # references users (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS totp_factors (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  secret_enc BLOB NOT NULL,
  key_id TEXT,
  created_at TEXT NOT NULL,
  enabled_at TEXT,
  last_step INTEGER NOT NULL DEFAULT 0 CHECK (last_step >= 0)
);
CREATE TABLE IF NOT EXISTS totp_recovery_codes (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash BLOB NOT NULL CHECK (length(code_hash) = 32),
  used_at TEXT
);
CREATE INDEX IF NOT EXISTS totp_recovery_codes_user ON totp_recovery_codes(user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
