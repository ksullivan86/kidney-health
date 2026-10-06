"""Schema versioning: a v0.1 ``kidney.db`` upgrades in place on startup; fresh databases get the full schema."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app import db
from app.config import Settings
from app.main import create_app

from conftest import TestClient, DAY

# The v0.1 schema verbatim: no log_entries.status, no profile.dialysis_days_json /
# week_start, no meal_templates table.
SCHEMA_V1 = """
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
  calories_kcal REAL, protein_g REAL, fat_g REAL, sat_fat_g REAL, carbs_g REAL, fiber_g REAL, sugar_g REAL,
  sodium_mg REAL, potassium_mg REAL, phosphorus_mg REAL, calcium_mg REAL, fluid_ml REAL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_date ON log_entries(date);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

NOW = "2026-10-01T08:00:00.000000Z"


def build_v01_database(path: Path, foods_version: str = "test-1") -> None:
    """A realistic v0.1 file: profile with targets, a builtin and a custom food, two log entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_V1)
    conn.execute(
        "INSERT INTO profile (id, name, weight_kg, ckd_stage, targets_json, updated_at) VALUES (1, 'Sam', 70, '4', ?, ?)",
        (json.dumps({"potassium_mg": 2500}), NOW),
    )
    conn.execute(
        """INSERT INTO foods (id, name, source, fdc_id, serving_desc, serving_g, potassium_mg, carbs_g, flags_json, created_at, updated_at)
           VALUES (1, 'Old banana', 'builtin', 173944, '1 medium (118 g)', 118, 422, 27, '[]', ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, carbs_g, flags_json, created_at, updated_at)
           VALUES (2, 'Old cracker', 'custom', '1 cracker (10 g)', 10, 5, '[]', ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (id, date, meal, food_id, food_name, servings, potassium_mg, carbs_g, created_at, updated_at)
           VALUES (1, ?, 'breakfast', 1, 'Old banana', 1, 422, 27, ?, ?)""",
        (DAY, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (id, date, meal, food_id, food_name, servings, carbs_g, created_at, updated_at)
           VALUES (2, ?, 'snack', 2, 'Old cracker', 3, 15, ?, ?)""",
        (DAY, NOW, NOW),
    )
    # Same version as the fixture file so the builtin import is skipped and the old rows stay untouched.
    conn.execute("INSERT INTO meta (key, value) VALUES ('foods_json_version', ?)", (foods_version,))
    conn.commit()
    conn.close()


def test_v01_database_upgrades_on_startup_and_old_rows_read_back_as_eaten(tmp_path, foods_json):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    build_v01_database(settings.db_path)

    before = db.connect(settings.db_path)
    assert "status" not in db.table_columns(before, "log_entries")
    assert {"dialysis_days_json", "week_start"}.isdisjoint(db.table_columns(before, "profile"))
    assert db.table_columns(before, "meal_templates") == set()
    assert db.get_schema_version(before) == 0
    before.close()

    with TestClient(create_app(settings)) as c:
        assert c.app.state.foods_import["status"] == "unchanged"
        day = c.get("/api/log", params={"date": DAY}).json()
        assert [e["id"] for e in day["entries"]] == [1, 2]
        assert [e["status"] for e in day["entries"]] == ["eaten", "eaten"]
        assert day["counts"] == {"eaten": 2, "planned": 0}
        assert day["totals"]["potassium_mg"] == 422 and day["totals"]["carbs_g"] == 42.0
        assert day["planned_totals"]["carbs_g"] == 0 and day["projected_totals"]["carbs_g"] == 42.0

        profile = c.get("/api/profile").json()
        assert profile["name"] == "Sam" and profile["ckd_stage"] == "4"
        assert profile["targets"] == {"potassium_mg": 2500}
        assert profile["dialysis_days"] == [] and profile["week_start"] == "monday"

        # the upgraded database accepts the new features straight away
        r = c.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 1, "status": "planned"})
        assert r.status_code == 201 and r.json()["status"] == "planned"
        assert c.get("/api/meals").json() == {"meals": []}
        assert c.put("/api/profile", json={"dialysis_days": [0, 2, 4], "week_start": "sunday"}).status_code == 200

    after = db.connect(settings.db_path)
    assert "status" in db.table_columns(after, "log_entries")
    assert {"dialysis_days_json", "week_start"} <= db.table_columns(after, "profile")
    assert {"id", "name", "note", "items_json"} <= db.table_columns(after, "meal_templates")
    assert db.get_schema_version(after) == db.SCHEMA_VERSION == 2
    rows = after.execute("SELECT id, status FROM log_entries ORDER BY id").fetchall()
    assert [(r["id"], r["status"]) for r in rows] == [(1, "eaten"), (2, "eaten"), (3, "planned")]
    after.close()


def test_migrations_are_idempotent_and_record_the_version(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == [1, 2]
    assert db.init_db(path) == []
    conn = db.connect(path)
    assert db.get_schema_version(conn) == 2
    assert db.get_meta(conn, db.SCHEMA_VERSION_KEY) == "2"
    # the step list is ordered and ends at the advertised version
    assert [v for v, _, _ in db.MIGRATIONS] == sorted(v for v, _, _ in db.MIGRATIONS)
    assert db.MIGRATIONS[-1][0] == db.SCHEMA_VERSION
    conn.close()


def test_fresh_database_has_the_full_v02_schema(tmp_path):
    path = tmp_path / "kidney.db"
    db.init_db(path)
    conn = db.connect(path)
    assert "status" in db.table_columns(conn, "log_entries")
    assert {"dialysis_days_json", "week_start"} <= db.table_columns(conn, "profile")
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"profile", "foods", "log_entries", "meal_templates", "meta"} <= tables
    # the defaults match the contract
    conn.execute("INSERT INTO profile (id, updated_at) VALUES (1, ?)", (NOW,))
    row = conn.execute("SELECT dialysis_days_json, week_start FROM profile").fetchone()
    assert (row["dialysis_days_json"], row["week_start"]) == ("[]", "monday")
    conn.close()


def test_add_column_only_when_missing(tmp_path):
    path = tmp_path / "scratch.db"
    conn = db.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT)")
    assert db.add_column_if_missing(conn, "t", "a", "TEXT") is False
    assert db.add_column_if_missing(conn, "t", "b", "TEXT NOT NULL DEFAULT 'x'") is True
    assert db.add_column_if_missing(conn, "t", "b", "TEXT NOT NULL DEFAULT 'x'") is False
    conn.execute("INSERT INTO t (a) VALUES ('row')")
    assert conn.execute("SELECT b FROM t").fetchone()["b"] == "x"
    assert db.table_columns(conn, "does_not_exist") == set()
    conn.close()


def test_partially_upgraded_database_gets_only_the_missing_columns(tmp_path, foods_json):
    """Someone added ``status`` by hand but nothing else: the step must not fail on it."""
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    build_v01_database(settings.db_path)
    conn = sqlite3.connect(settings.db_path)
    conn.execute("ALTER TABLE log_entries ADD COLUMN status TEXT NOT NULL DEFAULT 'eaten'")
    conn.execute("UPDATE log_entries SET status = 'planned' WHERE id = 2")
    conn.commit()
    conn.close()

    with TestClient(create_app(settings)) as c:
        day = c.get("/api/log", params={"date": DAY}).json()
        assert {e["id"]: e["status"] for e in day["entries"]} == {1: "eaten", 2: "planned"}
        assert day["counts"] == {"eaten": 1, "planned": 1}
        assert c.get("/api/profile").json()["week_start"] == "monday"

    conn = db.connect(settings.db_path)
    assert db.get_schema_version(conn) == 2
    assert {"dialysis_days_json", "week_start"} <= db.table_columns(conn, "profile")
    conn.close()
