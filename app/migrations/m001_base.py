"""Step 1: the v0.1 base schema (moved verbatim from ``app/db.py``).

``SCHEMA`` is the v0.2 shape of the base tables, exactly as ``app/db.py`` created it before v0.3,
so a fresh database is byte-for-byte the same as one created by v0.2. A real v0.1 file lacks the
v0.2 columns; step 2 adds them.
"""
from __future__ import annotations

import sqlite3

VERSION = 1
DESCRIPTION = "v0.1 base schema"

# Schema copied from ARCHITECTURE.md ("Data model"). Every statement is
# idempotent so it can run on every startup.
SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL DEFAULT '',
  weight_kg REAL,
  height_cm REAL,
  ckd_stage TEXT NOT NULL DEFAULT '3b',
  dialysis TEXT NOT NULL DEFAULT 'none',
  diabetes TEXT NOT NULL DEFAULT 'type1',
  warn_fraction REAL NOT NULL DEFAULT 0.8,
  targets_json TEXT NOT NULL DEFAULT '{}',
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
"""


def migrate(conn: sqlite3.Connection) -> None:
    """v0.1 base schema: created by :data:`SCHEMA`, nothing to do."""
