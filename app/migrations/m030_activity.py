"""Step 30: activity and recovery from Whoop, the active-day calorie extra, and a fifth Care team area (design note 28 §5).

Three new tables, each hanging off ``users`` with ``ON DELETE CASCADE``, so deleting an account deletes them:

* ``activity_days``: one row per person, date and source (``whoop``): calories burned (kcal), strain, recovery %, resting heart
  rate, HRV (ms), minutes asleep and sleep performance %. ``source_key`` is ``whoop:cycle:<id>``; ``finished`` is 0 while the
  person is still in that Whoop day (its numbers grow until it ends); ``started_at`` is the cycle's start (UTC).
* ``activity_workouts``: one row per workout: date, start and end on the person's clock, minutes, sport, kcal, strain.
  ``source_key`` is ``whoop:workout:<uuid>``.
* ``activity_extra``: the person's active-day calorie extra setting: on or off, the share counted (10–100 %), the daily ceiling
  (50–3000 kcal or none).

No CHECK on ``source``: a later provider may add values (as ``weights.source`` has none).

``shares.areas`` and ``care_invites.areas`` had ``CHECK (... json_array_length(areas) BETWEEN 1 AND 4)``; the new area
``activity`` makes five. SQLite cannot change a CHECK, so both tables are rebuilt from their stored definitions with ``4`` turned
into ``5`` in that one check (as step 14 did for ``ai_consents``): every column, constraint, index and row stays. Dropping
``shares`` with foreign keys on runs ``ON DELETE SET NULL`` on ``care_invites.share_id``, so the links from invites to their shares
are read first and written back after. Idempotent: ``IF NOT EXISTS`` for the new tables, and a table whose stored definition
already allows 5 areas is left alone.
"""
from __future__ import annotations

import re
import sqlite3

from ..db import execute_script

VERSION = 30
DESCRIPTION = "activity and recovery (activity_days, activity_workouts, activity_extra); Care team areas up to 5"

SCHEMA = ""  # references users and rebuilds shares and care_invites (steps 24 and 27), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True
BACKUP_BEFORE = True

DDL = """
CREATE TABLE IF NOT EXISTS activity_days (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,                          -- the person's date (design note 28 §4.3)
  source TEXT NOT NULL,                        -- whoop
  source_key TEXT NOT NULL,                    -- whoop:cycle:<id>
  kcal INTEGER,                                -- calories burned that day (kJ / 4.184)
  strain REAL,
  recovery_pct INTEGER,
  resting_hr INTEGER,
  hrv_ms REAL,                                 -- RMSSD; shown, never acted on
  sleep_minutes INTEGER,
  sleep_performance_pct INTEGER,
  finished INTEGER NOT NULL DEFAULT 0 CHECK (finished IN (0, 1)),
  started_at TEXT,                             -- UTC
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS activity_days_user_date ON activity_days(user_id, date, source);
CREATE UNIQUE INDEX IF NOT EXISTS activity_days_user_key ON activity_days(user_id, source_key);

CREATE TABLE IF NOT EXISTS activity_workouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  start_time TEXT,                             -- HH:MM, the person's clock
  end_time TEXT,
  minutes INTEGER,
  sport TEXT NOT NULL DEFAULT '',
  kcal INTEGER,
  strain REAL,
  source TEXT NOT NULL,
  source_key TEXT NOT NULL,                    -- whoop:workout:<uuid>
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS activity_workouts_user_key ON activity_workouts(user_id, source_key);
CREATE INDEX IF NOT EXISTS activity_workouts_user_date ON activity_workouts(user_id, date);

CREATE TABLE IF NOT EXISTS activity_extra (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
  share_pct INTEGER NOT NULL DEFAULT 100 CHECK (share_pct BETWEEN 10 AND 100),
  ceiling_kcal INTEGER CHECK (ceiling_kcal IS NULL OR ceiling_kcal BETWEEN 50 AND 3000),
  updated_at TEXT NOT NULL
);
"""

INDEXES = {
    "shares": "CREATE INDEX IF NOT EXISTS shares_owner ON shares(owner_user_id);\n"
              "CREATE INDEX IF NOT EXISTS shares_grantee ON shares(grantee_user_id);",
    "care_invites": "CREATE INDEX IF NOT EXISTS care_invites_owner ON care_invites(owner_user_id);\n"
                    "CREATE INDEX IF NOT EXISTS care_invites_invitee ON care_invites(invitee_user_id);",
}

_AREAS_CHECK = re.compile(r"(json_array_length\(\s*areas\s*\)\s+BETWEEN\s+1\s+AND\s+)4\b", re.IGNORECASE)


def widened_ddl(table: str, stored: str) -> str:
    """The stored ``CREATE TABLE`` of ``table`` named ``<table>_new`` with up to 5 areas."""
    name = re.compile(rf'^(\s*CREATE\s+TABLE\s+)"?{table}"?', re.IGNORECASE)
    if not _AREAS_CHECK.search(stored) or not name.match(stored):
        raise RuntimeError(f"{table} has an unexpected definition; schema step 30 cannot allow a fifth Care team area")
    widened = _AREAS_CHECK.sub(lambda m: f"{m.group(1)}5", stored, count=1)
    return name.sub(lambda m: f"{m.group(1)}{table}_new", widened, count=1)


def _widen(conn: sqlite3.Connection, table: str) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if row is None:
        return  # created by its own step; never missing after steps 24 and 27
    stored = row["sql"] or ""
    if not _AREAS_CHECK.search(stored):
        return  # already allows 5
    columns = ", ".join(f'"{r["name"]}"' for r in conn.execute(f"PRAGMA table_info({table})").fetchall())
    execute_script(conn, f"DROP TABLE IF EXISTS {table}_new;")
    conn.execute(widened_ddl(table, stored))
    conn.execute(f"INSERT INTO {table}_new ({columns}) SELECT {columns} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
    execute_script(conn, INDEXES[table])


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
    links = conn.execute("SELECT id, share_id FROM care_invites WHERE share_id IS NOT NULL").fetchall()
    _widen(conn, "shares")
    for link in links:  # dropping the old shares table set these to NULL
        conn.execute("UPDATE care_invites SET share_id = ? WHERE id = ?", (link["share_id"], link["id"]))
    _widen(conn, "care_invites")
