"""Step 27: the Care team (design note 25 §4).

* ``shares.role`` (``viewer`` or ``care_helper``, default ``viewer``): every existing share becomes a Viewer, exactly the
  read-only share it was. A Care helper may also plan meals for the person and use their shopping list.
* ``shares.helper_changes`` (JSON text or NULL): the Care helper's changes on the latest day they changed the plan,
  ``{"day", "added", "changed", "removed"}``, for the person's Care team list. The activity row is written once a day.
* A new table, ``care_invites``: an invite by user name, waiting until the invited person accepts or declines it.
  ``invitee_user_id`` is NULL when no active account had that name when it was sent, so the inviter gets the same answer either
  way; ``username`` is the name as typed (normalized), shown only to the inviter. ``answer`` records how it ended.
* ``log_entries.added_by_user_id``: the Care helper who added a planned entry (NULL for everything else, and when that account is
  deleted).

Nothing existing changes. Idempotent: ``IF NOT EXISTS`` and a column added only when missing.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 27
DESCRIPTION = "Care team: shares.role, shares.helper_changes, care_invites, log_entries.added_by_user_id"

SCHEMA = ""  # references users and shares and alters tables of earlier steps, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS care_invites (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  invitee_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  username TEXT NOT NULL CHECK (length(username) BETWEEN 1 AND 255),
  areas TEXT NOT NULL CHECK (json_valid(areas) AND json_type(areas) = 'array' AND json_array_length(areas) BETWEEN 1 AND 4),
  role TEXT NOT NULL CHECK (role IN ('viewer', 'care_helper')),
  lasts_days INTEGER CHECK (lasts_days IS NULL OR lasts_days BETWEEN 1 AND 365),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  answered_at TEXT,
  answer TEXT CHECK (answer IN ('accepted', 'declined', 'cancelled', 'replaced')),
  share_id INTEGER REFERENCES shares(id) ON DELETE SET NULL,
  CHECK ((answered_at IS NULL) = (answer IS NULL)),
  CHECK (invitee_user_id IS NULL OR invitee_user_id != owner_user_id)
);
CREATE INDEX IF NOT EXISTS care_invites_owner ON care_invites(owner_user_id);
CREATE INDEX IF NOT EXISTS care_invites_invitee ON care_invites(invitee_user_id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    add_column_if_missing(conn, "shares", "role", "TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'care_helper'))")
    add_column_if_missing(conn, "shares", "helper_changes", "TEXT CHECK (helper_changes IS NULL OR json_valid(helper_changes))")
    add_column_if_missing(conn, "log_entries", "added_by_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
    execute_script(conn, DDL)
