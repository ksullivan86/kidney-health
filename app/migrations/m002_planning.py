"""Step 2: v0.2 planned entries, dialysis weekdays, week start, saved meals (moved verbatim from ``app/db.py``)."""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing

VERSION = 2
DESCRIPTION = "v0.2 planned entries, dialysis days, week start, meal templates"

# v0.2 table, used by the full schema and by the migration step.
MEAL_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS meal_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  note TEXT,
  items_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

SCHEMA = MEAL_TEMPLATES_DDL

# Runs exactly as it did in v0.2 (no surrounding transaction): ``executescript`` commits anyway, and
# every statement is idempotent, so a crash part-way is repaired by the next start.
ATOMIC = False


def migrate(conn: sqlite3.Connection) -> None:
    """v0.2: entry status, dialysis weekdays, week start, saved meals."""
    add_column_if_missing(conn, "log_entries", "status", "TEXT NOT NULL DEFAULT 'eaten'")
    add_column_if_missing(conn, "profile", "dialysis_days_json", "TEXT NOT NULL DEFAULT '[]'")
    add_column_if_missing(conn, "profile", "week_start", "TEXT NOT NULL DEFAULT 'monday'")
    conn.executescript(MEAL_TEMPLATES_DDL)
