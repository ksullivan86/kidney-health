"""Step 36: notes from the Care team (design note 37 §8).

* ``shares`` and ``care_invites`` get one more switch, ``may_note`` (``INTEGER NOT NULL DEFAULT 0``, 0 or 1): this person may
  write notes for the person who shares. Every existing share and invite starts with it off, so nothing changes until a person
  turns it on. The ``role`` column of step 27 is not touched: a Clinician is stored as ``viewer``, so an older build sees a
  Viewer.
* ``shares.view_hours`` (TEXT, JSON, NULL): for a share with ``may_note`` on, the UTC hour and the areas already written to the
  person's activity in that hour, and the area of the latest such row (design note 37 §6). Like ``helper_changes`` of step 31
  it is a small counter the audit log cannot hold, since audit rows are never updated.
* A new table, ``care_notes``: a short note a Care team member wrote for the person. It hangs off the person with
  ``ON DELETE CASCADE`` (deleting the person's account deletes their notes). The author and the share are ``ON DELETE SET
  NULL``: when the author's account is deleted the person keeps the note, with the name it was written under
  (``author_name``).

The step does not read or need the tables of step 35, so it runs the same on a database at step 34 or 35. Idempotent: columns
are added only when missing, the rest is ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 36
DESCRIPTION = "notes from the Care team: may_note on shares and care_invites, care_notes"

SCHEMA = ""  # alters tables of steps 24 and 27 and references shares, so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS care_notes (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- the person the note is for
  author_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,          -- NULL once the author's account is deleted
  share_id INTEGER REFERENCES shares(id) ON DELETE SET NULL,               -- the share it was written through
  author_name TEXT NOT NULL,                                               -- display name, else user name, when written
  area TEXT CHECK (area IS NULL OR area IN ('food', 'labs', 'body', 'symptoms', 'activity')),
  about_date TEXT,                                                         -- YYYY-MM-DD or NULL
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 1000),
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  read_at TEXT,
  CHECK (author_user_id IS NULL OR author_user_id != owner_user_id),
  CHECK (edited_at IS NULL OR read_at IS NULL OR edited_at <= read_at)
);
CREATE INDEX IF NOT EXISTS care_notes_owner ON care_notes(owner_user_id, created_at);
CREATE INDEX IF NOT EXISTS care_notes_share ON care_notes(share_id, created_at);
CREATE INDEX IF NOT EXISTS care_notes_author ON care_notes(author_user_id, owner_user_id, created_at);
"""


def migrate(conn: sqlite3.Connection) -> None:
    for table in ("shares", "care_invites"):
        add_column_if_missing(conn, table, "may_note", "INTEGER NOT NULL DEFAULT 0 CHECK (may_note IN (0, 1))")
    add_column_if_missing(conn, "shares", "view_hours", "TEXT")
    execute_script(conn, DDL)
