"""SQLite helpers: connection factory, schema + ordered migrations, per-request dependency.

The schema below is the *current* (v0.2) shape and only uses ``CREATE ... IF NOT
EXISTS``, so a fresh database gets everything in one go. Because ``CREATE TABLE IF
NOT EXISTS`` never adds columns to an existing table, :data:`MIGRATIONS` holds an
ordered list of steps; each step inspects ``PRAGMA table_info`` and issues
``ALTER TABLE ... ADD COLUMN`` only when the column is missing, so a v0.1
``kidney.db`` upgrades in place on startup. ``meta.schema_version`` records the
last step applied. Columns are never dropped or renamed.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi import Request

log = logging.getLogger("kidney_health.db")

SCHEMA_VERSION_KEY = "schema_version"

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

# Schema copied from ARCHITECTURE.md ("Data model"). Every statement is
# idempotent so it can run on every startup.
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT '',
  weight_kg REAL,
  height_cm REAL,
  ckd_stage TEXT NOT NULL DEFAULT '3b',
  dialysis TEXT NOT NULL DEFAULT 'none',
  diabetes TEXT NOT NULL DEFAULT 'type1',
  warn_fraction REAL NOT NULL DEFAULT 0.8,
  targets_json TEXT NOT NULL DEFAULT '{{}}',
  dialysis_days_json TEXT NOT NULL DEFAULT '[]',
  week_start TEXT NOT NULL DEFAULT 'monday',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS foods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  brand TEXT,
  category TEXT,
  source TEXT NOT NULL,
  fdc_id INTEGER,
  serving_desc TEXT NOT NULL,
  serving_g REAL NOT NULL,
  calories_kcal REAL, protein_g REAL, fat_g REAL, sat_fat_g REAL, carbs_g REAL, fiber_g REAL, sugar_g REAL,
  sodium_mg REAL, potassium_mg REAL, phosphorus_mg REAL, calcium_mg REAL, fluid_ml REAL,
  flags_json TEXT NOT NULL DEFAULT '[]',
  kidney_notes TEXT,
  hidden INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS foods_name ON foods(name);
CREATE UNIQUE INDEX IF NOT EXISTS foods_builtin_fdc ON foods(source, fdc_id) WHERE source='builtin';
CREATE TABLE IF NOT EXISTS log_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  meal TEXT NOT NULL,
  food_id INTEGER NOT NULL REFERENCES foods(id),
  food_name TEXT NOT NULL,
  servings REAL NOT NULL,
  grams REAL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'eaten',
  calories_kcal REAL, protein_g REAL, fat_g REAL, sat_fat_g REAL, carbs_g REAL, fiber_g REAL, sugar_g REAL,
  sodium_mg REAL, potassium_mg REAL, phosphorus_mg REAL, calcium_mg REAL, fluid_ml REAL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_date ON log_entries(date);
{MEAL_TEMPLATES_DDL}
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def utcnow() -> str:
    """ISO-8601 UTC timestamp with microseconds and a ``Z`` suffix.

    Microseconds keep ``created_at`` ordering stable when several entries are
    added within the same second.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with the project's standard pragmas.

    ``check_same_thread=False`` is required because FastAPI may run a sync
    dependency and the endpoint it feeds on different worker threads; each
    connection is still used by exactly one request at a time.
    """
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Column names of ``table`` (empty set when the table does not exist)."""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE table ADD COLUMN column ddl`` unless the column already exists.

    Returns ``True`` when the column was added. ``ddl`` is the type and
    constraints, e.g. ``"TEXT NOT NULL DEFAULT 'eaten'"``; SQLite back-fills
    existing rows with the default.
    """
    if column in table_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    log.info("migration: added column %s.%s", table, column)
    return True


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """v0.1 base schema: created by :data:`SCHEMA`, nothing to do."""


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v0.2: entry status, dialysis weekdays, week start, saved meals."""
    add_column_if_missing(conn, "log_entries", "status", "TEXT NOT NULL DEFAULT 'eaten'")
    add_column_if_missing(conn, "profile", "dialysis_days_json", "TEXT NOT NULL DEFAULT '[]'")
    add_column_if_missing(conn, "profile", "week_start", "TEXT NOT NULL DEFAULT 'monday'")
    conn.executescript(MEAL_TEMPLATES_DDL)


# (version, description, step). Append only; never reorder or edit a shipped step.
MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "v0.1 base schema", _migrate_v1),
    (2, "v0.2 planned entries, dialysis days, week start, meal templates", _migrate_v2),
)
SCHEMA_VERSION: int = MIGRATIONS[-1][0]


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Stored ``meta.schema_version`` (0 for a v0.1 database that never recorded one)."""
    if "meta" not in {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
        return 0
    value = get_meta(conn, SCHEMA_VERSION_KEY)
    try:
        return int(value) if value is not None else 0
    except ValueError:
        return 0


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Create missing tables, then apply every migration step newer than the stored version.

    Returns the versions applied (empty when the database was already current).
    """
    conn.executescript(SCHEMA)
    current = get_schema_version(conn)
    applied: list[int] = []
    for version, description, step in MIGRATIONS:
        if version <= current:
            continue
        step(conn)
        set_meta(conn, SCHEMA_VERSION_KEY, str(version))
        conn.commit()
        applied.append(version)
        log.info("migration %d applied: %s", version, description)
    return applied


def init_db(path: Path | str) -> list[int]:
    """Create the database file, apply the schema and pending migrations (idempotent)."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        return migrate(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {k: row[k] for k in row.keys()}


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, closed afterwards."""
    conn = connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()
