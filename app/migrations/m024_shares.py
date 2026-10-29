"""Step 24: read-only sharing with a caregiver or dietitian (design note 19 §4).

One new table, ``shares``. A row starts as a **code**: the link a person sends, with the SHA-256 of its verifier, the areas it
shares and when it ends. When the other person accepts it, the same row becomes a **share**: ``grantee_user_id`` and
``accepted_at`` are set and the code's fields are cleared, so a link works once. ``ended_at`` and ``ended_by`` record who stopped
it (the owner, the other person, an admin, or a newer code from the same person). The ``CHECK``s keep the two states apart.

Rows cascade when either account is deleted. Nothing existing changes. Idempotent: ``IF NOT EXISTS`` throughout.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 24
DESCRIPTION = "shares (read-only sharing with a caregiver or dietitian)"

SCHEMA = ""  # references users (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  grantee_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  code_id TEXT UNIQUE,
  verifier_hash BLOB,
  areas TEXT NOT NULL CHECK (json_valid(areas) AND json_type(areas) = 'array' AND json_array_length(areas) BETWEEN 1 AND 4),
  created_at TEXT NOT NULL,
  expires_at TEXT,
  accepted_at TEXT,
  ended_at TEXT,
  ended_by TEXT CHECK (ended_by IN ('owner', 'grantee', 'admin', 'replaced')),
  last_viewed_at TEXT,
  CHECK ((ended_at IS NULL) = (ended_by IS NULL)),
  CHECK (accepted_at IS NOT NULL OR (grantee_user_id IS NULL AND code_id IS NOT NULL AND verifier_hash IS NOT NULL
                                     AND expires_at IS NOT NULL)),
  CHECK (accepted_at IS NULL OR (grantee_user_id IS NOT NULL AND code_id IS NULL AND verifier_hash IS NULL)),
  CHECK (grantee_user_id IS NULL OR grantee_user_id != owner_user_id)
);
CREATE INDEX IF NOT EXISTS shares_owner ON shares(owner_user_id);
CREATE INDEX IF NOT EXISTS shares_grantee ON shares(grantee_user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
