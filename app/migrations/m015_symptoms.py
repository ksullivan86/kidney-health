"""Step 15: the symptoms log (ROADMAP "Symptoms log"; ARCHITECTURE "Symptoms log").

``symptoms``: one row per symptom a person records for a day. ``symptom`` is a key from a small fixed list
(:data:`app.symptoms.SYMPTOMS`); ``other`` carries a short free-text ``label`` (at most 60 characters), every other key
has an empty label. ``severity`` is 1 (mild), 2 (moderate) or 3 (severe). ``date`` is the person's local date
(``YYYY-MM-DD``), ``note`` is optional (at most 300 characters) and ``created_at`` is UTC.

The table has **no CHECK on the symptom key**: SQLite cannot change a CHECK without rebuilding the table (steps 12 and
14 had to), and a later version may add a key. The API validates the key; a row with a key this version does not know
is kept and left out of the lists. The ranges that never change (severity 1 to 3, the lengths, the date's shape) are
checked by the table as well.

``user_id`` references ``users`` with ``ON DELETE CASCADE``, so deleting an account deletes its symptoms. Idempotent:
``IF NOT EXISTS`` everywhere. Nothing else changes.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 15
DESCRIPTION = "symptoms log (a person's symptoms by date and severity)"

SCHEMA = ""  # references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS symptoms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL CHECK (length(date) = 10),                          -- YYYY-MM-DD, the person's local date
  symptom TEXT NOT NULL CHECK (length(symptom) BETWEEN 1 AND 40),        -- a key of app.symptoms.SYMPTOMS (not a CHECK list)
  label TEXT NOT NULL DEFAULT '' CHECK (length(label) <= 60),            -- only for 'other'
  severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 3),            -- 1 mild, 2 moderate, 3 severe
  note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 300),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS symptoms_user_date ON symptoms(user_id, date, id);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
