"""Step 28: test accounts and Send feedback (design note 26 §4).

* ``users.is_test_account`` (0 or 1, default 0): the server made this account itself because the admin turned on test accounts
  (``TEST_ACCOUNT_ENABLED``). Every existing account is a real account (0).
* Two triggers keep a test account from ever being an admin: an insert or an update that would give a row both ``role = 'admin'``
  and ``is_test_account = 1`` is refused, whatever code path tries it.
* A new table, ``feedback``: what a tester typed in Send feedback, with the screen name, the app version and the time. Nothing else
  is copied in. ``user_id`` is ``ON DELETE SET NULL`` and ``username`` is kept as text, so a reset of the test accounts (which
  deletes them and makes them again) leaves the feedback for the admin. ``done_at`` / ``done_by`` record "mark done".

Nothing existing changes. Idempotent: ``IF NOT EXISTS`` and a column added only when missing.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 28
DESCRIPTION = "test accounts: users.is_test_account, never an admin, feedback"

SCHEMA = ""  # references users and alters it (step 3), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TRIGGER IF NOT EXISTS users_test_account_never_admin_insert
BEFORE INSERT ON users WHEN NEW.role = 'admin' AND NEW.is_test_account = 1
BEGIN SELECT RAISE(ABORT, 'a test account cannot be an admin'); END;

CREATE TRIGGER IF NOT EXISTS users_test_account_never_admin_update
BEFORE UPDATE ON users WHEN NEW.role = 'admin' AND NEW.is_test_account = 1
BEGIN SELECT RAISE(ABORT, 'a test account cannot be an admin'); END;

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  username TEXT NOT NULL CHECK (length(username) BETWEEN 1 AND 255),
  screen TEXT NOT NULL CHECK (length(screen) BETWEEN 1 AND 60),
  trying TEXT NOT NULL CHECK (length(trying) <= 2000),
  happened TEXT NOT NULL CHECK (length(happened) <= 2000),
  useful TEXT CHECK (useful IS NULL OR useful IN ('yes', 'somewhat', 'no')),
  unsafe INTEGER NOT NULL DEFAULT 0 CHECK (unsafe IN (0, 1)),
  app_version TEXT NOT NULL CHECK (length(app_version) BETWEEN 1 AND 40),
  created_at TEXT NOT NULL,
  done_at TEXT,
  done_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS feedback_user ON feedback(user_id);
CREATE INDEX IF NOT EXISTS feedback_created ON feedback(created_at);
"""


def migrate(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "users", "is_test_account", "INTEGER NOT NULL DEFAULT 0 CHECK (is_test_account IN (0, 1))")
    execute_script(conn, DDL)
