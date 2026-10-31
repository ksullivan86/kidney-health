"""Step 31: the full Care team (design note 29 §6).

* ``shares`` and ``care_invites`` get four switches, each ``INTEGER NOT NULL DEFAULT 0`` (0 or 1): ``may_plan`` (plan meals and use
  the shopping list), ``may_log`` (log eaten food), ``may_use_saved_meals`` and ``may_suggest``. Every existing share and invite
  keeps its meaning exactly: a ``care_helper`` gets ``may_plan = 1``, a ``viewer`` nothing. The ``role`` column of step 27 stays
  with its ``CHECK``; the app writes it ``care_helper`` exactly when ``may_plan`` is on, so an older build still reads it right.
* A new table, ``care_suggestions`` (note 21 §4): a meal someone on the Care team suggests for the person, waiting until the
  person adds it to their plan or says no, or until it expires. It cascades with its share and with both accounts.

The role is mapped only when the switch is first added, so running the step again changes nothing. Idempotent: ``IF NOT EXISTS``
and a column added only when missing.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 31
DESCRIPTION = "full Care team: switches on shares and care_invites, care_suggestions"

SCHEMA = ""  # alters tables of steps 24 and 27 and references shares, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

SWITCHES = ("may_plan", "may_log", "may_use_saved_meals", "may_suggest")

DDL = """
CREATE TABLE IF NOT EXISTS care_suggestions (
  id INTEGER PRIMARY KEY,
  share_id INTEGER NOT NULL REFERENCES shares(id) ON DELETE CASCADE,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  meal TEXT NOT NULL CHECK (meal IN ('breakfast', 'lunch', 'dinner', 'snack')),
  items_json TEXT NOT NULL CHECK (json_valid(items_json) AND json_type(items_json) = 'array'
                                  AND json_array_length(items_json) BETWEEN 1 AND 30),
  note TEXT CHECK (note IS NULL OR length(note) <= 280),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  answered_at TEXT,
  answer TEXT CHECK (answer IN ('accepted', 'declined', 'expired', 'ended')),
  CHECK ((answered_at IS NULL) = (answer IS NULL)),
  CHECK (from_user_id != owner_user_id)
);
CREATE INDEX IF NOT EXISTS care_suggestions_owner ON care_suggestions(owner_user_id, answer);
CREATE INDEX IF NOT EXISTS care_suggestions_share ON care_suggestions(share_id);
CREATE INDEX IF NOT EXISTS care_suggestions_from ON care_suggestions(from_user_id, created_at);
"""


def migrate(conn: sqlite3.Connection) -> None:
    for table in ("shares", "care_invites"):
        added = [add_column_if_missing(conn, table, name, f"INTEGER NOT NULL DEFAULT 0 CHECK ({name} IN (0, 1))") for name in SWITCHES]
        if added[0]:  # first time only: a Care helper plans, as before
            conn.execute(f"UPDATE {table} SET may_plan = 1 WHERE role = 'care_helper'")
    execute_script(conn, DDL)
