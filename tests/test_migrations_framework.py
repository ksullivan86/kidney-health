"""The migrations package (``app/migrations``) and its runner in ``app/db.py``.

The v0.1/v0.2 schema moved out of ``db.py`` into ``m001_base`` and ``m002_planning`` verbatim: a
fresh database, an upgraded v0.1 database and an existing v0.2 database must come out exactly as
the v0.2 code left them. ``V02_SCHEMA`` / ``v02_migrate`` below are a frozen copy of that code.
"""
from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from app import audit, credentials, db, migrations
from app.migrations import MigrationLayoutError, Step
from app.settings_store import create_settings_tables

from test_migrations import build_v01_database

# --------------------------------------------------------------------------- #
# Frozen copy of the v0.2 app/db.py schema and migration steps
# --------------------------------------------------------------------------- #

V02_MEAL_TEMPLATES_DDL = """
CREATE TABLE IF NOT EXISTS meal_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  note TEXT,
  items_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

V02_SCHEMA = f"""
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
{V02_MEAL_TEMPLATES_DDL}
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def v02_migrate(conn: sqlite3.Connection) -> None:
    """What v0.2's ``db.migrate`` did."""
    conn.executescript(V02_SCHEMA)
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    current = int(row[0]) if row else 0
    if current < 1:
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1') ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        conn.commit()
    if current < 2:
        db.add_column_if_missing(conn, "log_entries", "status", "TEXT NOT NULL DEFAULT 'eaten'")
        db.add_column_if_missing(conn, "profile", "dialysis_days_json", "TEXT NOT NULL DEFAULT '[]'")
        db.add_column_if_missing(conn, "profile", "week_start", "TEXT NOT NULL DEFAULT 'monday'")
        conn.executescript(V02_MEAL_TEMPLATES_DDL)
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2') ON CONFLICT(key) DO UPDATE SET value = excluded.value")
        conn.commit()


def schema_of(path: Path) -> list[tuple[str, str, str, str | None]]:
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    conn.close()
    return rows


def dump_of(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    lines = list(conn.iterdump())
    conn.close()
    return lines


def build_with_v02_code(path: Path) -> None:
    conn = db.connect(path)
    v02_migrate(conn)
    conn.close()


def add_v02_data(path: Path) -> None:
    conn = sqlite3.connect(path)
    now = "2026-10-01T08:00:00.000000Z"
    conn.execute("INSERT INTO profile (id, name, weight_kg, dialysis_days_json, updated_at) VALUES (1, 'Sam', 70, '[0,2,4]', ?)", (now,))
    conn.execute(
        "INSERT INTO foods (id, name, source, serving_desc, serving_g, potassium_mg, created_at, updated_at) VALUES (5, 'Rice', 'custom', '1 cup', 158, 55, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO log_entries (date, meal, food_id, food_name, servings, status, created_at, updated_at) VALUES ('2026-10-05', 'lunch', 5, 'Rice', 1, 'planned', ?, ?)",
        (now, now),
    )
    conn.execute("INSERT INTO meal_templates (name, items_json, created_at, updated_at) VALUES ('Usual', '[{\"food_id\": 5, \"servings\": 1}]', ?, ?)", (now, now))
    conn.execute("INSERT INTO meta (key, value) VALUES ('foods_json_version', 'x')")
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# Byte-for-byte compatibility with v0.2
# --------------------------------------------------------------------------- #


def test_steps_are_discovered_in_order():
    steps = migrations.steps()
    assert [s.version for s in steps[:2]] == [1, 2]
    assert [s.name for s in steps[:2]] == ["m001_base", "m002_planning"]
    assert [v for v, _, _ in db.MIGRATIONS] == [s.version for s in steps]
    assert db.SCHEMA_VERSION == steps[-1].version
    assert db.MEAL_TEMPLATES_DDL == V02_MEAL_TEMPLATES_DDL


def test_full_schema_is_the_v02_schema():
    """The concatenated step SCHEMAs (+ meta) are the v0.2 SCHEMA statement for statement."""
    v1_v2 = db.full_schema(migrations.steps()[:2])
    assert db.split_sql(v1_v2) == db.split_sql(V02_SCHEMA)


def test_fresh_database_matches_v02(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    build_with_v02_code(old)
    assert db.init_db(new)[:2] == [1, 2]
    assert schema_of(new) == schema_of(old)
    assert dump_of(new) == dump_of(old)


def test_existing_v02_database_is_untouched(tmp_path):
    path = tmp_path / "kidney.db"
    build_with_v02_code(path)
    add_v02_data(path)
    before_schema, before_dump = schema_of(path), dump_of(path)
    applied = db.init_db(path)
    assert applied == [s.version for s in migrations.steps() if s.version > 2]
    if not applied:  # with only steps 1-2 the database must be byte-for-byte the same
        assert schema_of(path) == before_schema and dump_of(path) == before_dump
    else:  # later steps may add to it, but never change what v0.2 wrote
        after = dump_of(path)
        assert all(line in after for line in before_dump if line.startswith("INSERT INTO \"log_entries\""))


def test_v01_database_upgrades_exactly_like_v02_did(tmp_path, foods_json):
    old, new = tmp_path / "old" / "kidney.db", tmp_path / "new" / "kidney.db"
    build_v01_database(old)
    build_v01_database(new)
    build_with_v02_code(old)
    conn = db.connect(new)
    db.migrate(conn, migrations.steps()[:2])
    conn.close()
    assert schema_of(new) == schema_of(old)
    assert dump_of(new) == dump_of(old)


def test_rerun_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    first = db.init_db(path)
    assert first and first[0] == 1
    snapshot = (schema_of(path), dump_of(path))
    assert db.init_db(path) == []
    assert db.init_db(path) == []
    assert (schema_of(path), dump_of(path)) == snapshot
    conn = db.connect(path)
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    conn.close()


# --------------------------------------------------------------------------- #
# Runner behaviour
# --------------------------------------------------------------------------- #


def step(version: int, fn, *, schema: str = "", atomic: bool = True, backup_before: bool = False, fk: bool = False) -> Step:
    return Step(version=version, name=f"m{version:03d}_test", description=f"test step {version}", migrate=fn, schema=schema,
                atomic=atomic, backup_before=backup_before, foreign_key_check=fk)


def base_steps() -> list[Step]:
    return list(migrations.steps()[:2])


def test_failing_atomic_step_rolls_back_and_keeps_the_version(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    db.migrate(conn, base_steps())

    def broken(c: sqlite3.Connection) -> None:
        db.add_column_if_missing(c, "foods", "gtin", "TEXT")
        c.execute("CREATE TABLE half_done (x)")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        db.migrate(conn, [*base_steps(), step(3, broken)])
    assert db.get_schema_version(conn) == 2
    assert "gtin" not in db.table_columns(conn, "foods")
    assert not db.table_exists(conn, "half_done")

    def fixed(c: sqlite3.Connection) -> None:
        db.add_column_if_missing(c, "foods", "gtin", "TEXT")

    assert db.migrate(conn, [*base_steps(), step(3, fixed)]) == [3]
    assert db.migrate(conn, [*base_steps(), step(3, fixed)]) == []
    assert "gtin" in db.table_columns(conn, "foods")
    conn.close()


def test_backup_before_runs_once_and_only_for_existing_databases(tmp_path):
    def noop(c: sqlite3.Connection) -> None:
        pass

    fresh = tmp_path / "fresh.db"
    conn = db.connect(fresh)
    db.migrate(conn, [*base_steps(), step(3, noop, backup_before=True)])
    conn.close()
    assert not Path(f"{fresh}.pre-v3.bak").exists()

    existing = tmp_path / "kidney.db"
    build_with_v02_code(existing)
    add_v02_data(existing)
    conn = db.connect(existing)
    db.migrate(conn, [*base_steps(), step(3, noop, backup_before=True)])
    conn.close()
    bak = Path(f"{existing}.pre-v3.bak")
    assert bak.exists() and (bak.stat().st_mode & 0o777) == 0o600
    copy = sqlite3.connect(bak)
    assert copy.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
    assert copy.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0] == 1
    copy.close()


def test_foreign_key_check_failure_rolls_back(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    db.migrate(conn, base_steps())

    def orphan(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE child (id INTEGER PRIMARY KEY, food_id INTEGER REFERENCES foods(id))")
        c.execute("INSERT INTO child (food_id) VALUES (999)")

    conn.execute("PRAGMA foreign_keys = OFF")  # so the orphan row can be written; the check still sees it
    with pytest.raises(db.MigrationError, match="foreign-key violation"):
        db.migrate(conn, [*base_steps(), step(3, orphan, fk=True)])
    assert not db.table_exists(conn, "child") and db.get_schema_version(conn) == 2
    conn.close()


def test_step_schema_runs_before_steps(tmp_path):
    seen = []

    def check(c: sqlite3.Connection) -> None:
        seen.append(db.table_exists(c, "barcode_cache"))

    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    schema = "CREATE TABLE IF NOT EXISTS barcode_cache (gtin TEXT PRIMARY KEY, body TEXT);"
    db.migrate(conn, [*base_steps(), step(3, check, schema=schema)])
    assert seen == [True]
    conn.close()


def write_package(root: Path, name: str, files: dict[str, str]) -> str:
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for filename, body in files.items():
        (pkg / filename).write_text(textwrap.dedent(body))
    return name


STEP_SRC = """
VERSION = {v}
DESCRIPTION = "step {v}"
def migrate(conn):
    pass
"""


def test_discovery_refuses_gaps_duplicates_and_bad_modules(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    ok = write_package(tmp_path, "mig_ok", {"m001_a.py": STEP_SRC.format(v=1), "m002_b.py": STEP_SRC.format(v=2), "helpers.py": ""})
    assert [s.name for s in migrations.discover(ok)] == ["m001_a", "m002_b"]

    gap = write_package(tmp_path, "mig_gap", {"m001_a.py": STEP_SRC.format(v=1), "m003_c.py": STEP_SRC.format(v=3)})
    with pytest.raises(MigrationLayoutError, match="missing \\[2\\]"):
        migrations.discover(gap)

    dup = write_package(tmp_path, "mig_dup", {"m001_a.py": STEP_SRC.format(v=1), "m001_b.py": STEP_SRC.format(v=1)})
    with pytest.raises(MigrationLayoutError, match="two migration steps"):
        migrations.discover(dup)

    wrong = write_package(tmp_path, "mig_wrong", {"m001_a.py": STEP_SRC.format(v=7)})
    with pytest.raises(MigrationLayoutError, match="VERSION must be 1"):
        migrations.discover(wrong)

    nomigrate = write_package(tmp_path, "mig_nofn", {"m001_a.py": "VERSION = 1\nDESCRIPTION = 'x'\n"})
    with pytest.raises(MigrationLayoutError, match="migrate"):
        migrations.discover(nomigrate)


def test_split_sql_and_execute_script_stay_in_the_transaction():
    statements = db.split_sql(
        "CREATE TABLE a (x TEXT); -- note; with a semicolon\n"
        "CREATE TRIGGER t BEFORE UPDATE ON a BEGIN SELECT RAISE(ABORT, 'no; never'); END;\n"
        "INSERT INTO a VALUES ('semi;colon')\n-- trailing comment"
    )
    assert len(statements) == 3
    conn = sqlite3.connect(":memory:")
    conn.execute("BEGIN")
    db.execute_script(conn, "CREATE TABLE b (y); INSERT INTO b VALUES (1);")
    assert conn.in_transaction
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'b'").fetchone()[0] == 0
    with pytest.raises(ValueError):
        db.split_sql("INSERT INTO c VALUES ('unterminated")


def test_schema_v3_ddl_helpers_apply_on_a_migrated_database(tmp_path):
    """The DDL functions m003 will call: idempotent and transaction-safe on a v0.2 database."""
    path = tmp_path / "kidney.db"
    build_with_v02_code(path)
    conn = db.connect(path)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    for _ in range(2):
        create_settings_tables(conn)
        credentials.create_credentials_tables(conn)
        audit.create_audit_table(conn)
    assert conn.in_transaction
    conn.commit()
    for table in ("instance_settings", "user_settings", "secrets", "usage_daily", "audit_log"):
        assert db.table_exists(conn, table), table
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
