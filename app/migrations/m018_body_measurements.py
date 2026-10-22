"""Step 18: the weight and blood pressure log (note 10 §4.1; ARCHITECTURE "Weight and blood pressure").

Two tables, because the two readings validate differently; both hang off ``users`` with ``ON DELETE CASCADE``, so deleting an
account deletes its readings.

* ``weights``: one row per weighing. ``kg`` is stored in kilograms, rounded to two decimals; the unit the person sees and types
  (``user.units.weight``) is display and entry only. ``context`` is ``morning``, ``before_dialysis``, ``after_dialysis`` or
  ``other``.
* ``blood_pressures``: one row per reading: ``systolic`` (the top number), ``diastolic`` (the bottom number), an optional
  ``pulse``, and a ``context`` that also has ``evening``.

Both carry the person's own ``date`` (``YYYY-MM-DD``) and an optional ``time`` (``HH:MM`` on the person's clock), an optional
``note`` (at most 200 characters), ``source`` (``manual``, ``apple_health`` or ``import``) and ``source_key``, the key a later
import de-duplicates on (NULL for a row the person typed). ``created_at`` and ``updated_at`` are UTC.

There is **no CHECK** beyond ``NOT NULL``: the ranges and the lists of contexts and sources live in the request models
(``app/models.py``), because SQLite cannot change a CHECK without rebuilding the table (steps 12 and 14 had to), and a later
version may add a context or a source. A row with a value this version does not know is kept and left out of the lists. The
ranges are the project's own plausibility choice, labelled so in ``app/body.py``.

``id`` is ``AUTOINCREMENT`` (as ``symptoms`` is, and as the note's ``INTEGER PRIMARY KEY`` allows): an id is never given to a
second row, so a page that still holds an old id can only find its own row or nothing.

Idempotent: ``IF NOT EXISTS`` everywhere. Nothing else changes.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 18
DESCRIPTION = "weight and blood pressure log (weights, blood_pressures)"

SCHEMA = ""  # references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS weights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,                          -- YYYY-MM-DD, the person's day
  time TEXT,                                   -- HH:MM on the person's clock, optional
  kg REAL NOT NULL,                            -- stored in kg, two decimals
  context TEXT NOT NULL,                       -- morning | before_dialysis | after_dialysis | other
  note TEXT,                                   -- at most 200 characters
  source TEXT NOT NULL DEFAULT 'manual',       -- manual | apple_health | import
  source_key TEXT,                             -- the import's de-duplication key, NULL for manual rows
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS weights_user_date ON weights(user_id, date);
CREATE UNIQUE INDEX IF NOT EXISTS weights_user_source_key ON weights(user_id, source_key) WHERE source_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS blood_pressures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  time TEXT,
  systolic INTEGER NOT NULL,                   -- mmHg, the top number
  diastolic INTEGER NOT NULL,                  -- mmHg, the bottom number
  pulse INTEGER,                               -- beats a minute, optional
  context TEXT NOT NULL,                       -- morning | evening | before_dialysis | after_dialysis | other
  note TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  source_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS blood_pressures_user_date ON blood_pressures(user_id, date);
CREATE UNIQUE INDEX IF NOT EXISTS blood_pressures_user_source_key ON blood_pressures(user_id, source_key) WHERE source_key IS NOT NULL;
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
