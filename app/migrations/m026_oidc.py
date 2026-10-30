"""Step 26: sign-in with an OpenID Connect provider (design note 24 §6).

* A new table, ``oidc_links``: one row per provider account linked to an account here. ``issuer`` is the provider's issuer and
  ``subject`` its ``sub`` claim (the provider's stable id for the person); ``(issuer, subject)`` is unique, so one provider account
  signs in to one account here, and ``(user_id, issuer)`` is unique, so a person links one account per provider. ``email`` is what
  the provider last said, for the person's own Settings list. Nothing is a secret: no token is ever stored. Rows cascade when the
  account is deleted.
* ``sessions.signed_in_with`` (``TEXT``, NULL): ``oidc`` for a session the provider started. NULL for every earlier session and for a
  password or passkey sign-in. The two-step rule for admins reads it (note 24 §9).

Nothing existing changes. Idempotent: ``IF NOT EXISTS`` and a column added only when missing.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 26
DESCRIPTION = "oidc_links and sessions.signed_in_with (sign in with a provider)"

SCHEMA = ""  # references users and alters sessions (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS oidc_links (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  issuer TEXT NOT NULL CHECK (length(issuer) BETWEEN 1 AND 500),
  subject TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
  email TEXT CHECK (email IS NULL OR length(email) <= 320),
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  UNIQUE (issuer, subject),
  UNIQUE (user_id, issuer)
);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
    add_column_if_missing(conn, "sessions", "signed_in_with", "TEXT CHECK (signed_in_with IS NULL OR signed_in_with IN ('oidc'))")
