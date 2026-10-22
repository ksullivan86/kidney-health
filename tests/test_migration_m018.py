"""Schema step 18 (``app/migrations/m018_body_measurements.py``): the weight and blood pressure log on a populated schema-v17
database (note 10 §4.1). Every earlier row stays; the two new tables have the columns and the indexes the app relies on
(the (user, date) index and a unique (user, source_key) index that ignores rows without a key), no CHECK on a context or a
source (a later value must not need a table rebuild), and deleting an account removes its rows (``ON DELETE CASCADE``).

The "before" database is built from ``steps()[:17]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m018_body_measurements as m018
from conftest import insert_users

NOW = "2026-10-22T08:00:00.000000Z"

WEIGHT_COLUMNS = {"id", "user_id", "date", "time", "kg", "context", "note", "source", "source_key", "created_at", "updated_at"}
BP_COLUMNS = {"id", "user_id", "date", "time", "systolic", "diastolic", "pulse", "context", "note", "source", "source_key",
              "created_at", "updated_at"}


def build_v17_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:17]) == list(range(1, 18))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (1, 'Rice', 'custom', '1 cup', 158, 2, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, created_at, updated_at)
           VALUES (2, '2026-10-21', 'lunch', 1, 'Rice', 1, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at)
           VALUES (2, '2026-10-21', 'swelling', '', 2, '', ?)""",
        (NOW,),
    )
    conn.execute(
        """INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, created_at)
           VALUES (2, 'potassium', 4.8, 4.8, 'mmol/L', '2026-10-01', ?)""",
        (NOW,),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 17
    assert not db.table_exists(conn, "weights") and not db.table_exists(conn, "blood_pressures")
    conn.close()


def weight(conn: sqlite3.Connection, *, user_id: int = 2, date: str = "2026-10-21", time: str | None = "07:30", kg: float = 70.25,
           context: str = "morning", note: str | None = "", source: str | None = None, source_key: str | None = None) -> None:
    columns = ["user_id", "date", "time", "kg", "context", "note", "source_key", "created_at", "updated_at"]
    values = [user_id, date, time, kg, context, note, source_key, NOW, NOW]
    if source is not None:
        columns.append("source")
        values.append(source)
    conn.execute(f"INSERT INTO weights ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", values)


def reading(conn: sqlite3.Connection, *, user_id: int = 2, date: str = "2026-10-21", time: str | None = "07:35", systolic: int = 128,
            diastolic: int = 78, pulse: int | None = 64, context: str = "morning", source_key: str | None = None) -> None:
    conn.execute(
        """INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source_key, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)""",
        (user_id, date, time, systolic, diastolic, pulse, context, source_key, NOW, NOW),
    )


def indexes(conn: sqlite3.Connection, table: str) -> dict[str, tuple[bool, list[str], str | None]]:
    out = {}
    for r in conn.execute(f"PRAGMA index_list({table})"):
        cols = [c["name"] for c in conn.execute(f"PRAGMA index_info({r['name']})")]
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (r["name"],)).fetchone()[0]
        out[r["name"]] = (bool(r["unique"]), cols, sql)
    return out


def test_step_18_follows_step_17():
    steps = migrations.steps()
    assert [s.version for s in steps][:18] == list(range(1, 19))
    step = steps[17]
    assert step.name == "m018_body_measurements" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v17_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    build_v17_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 18 and applied == list(range(18, db.SCHEMA_VERSION + 1))  # step 18, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    for table in ("log_entries", "symptoms", "lab_results", "foods"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {'owner_user_id' if table == 'foods' else 'user_id'} = 2").fetchone()[0] == 1
    assert db.table_columns(conn, "weights") == WEIGHT_COLUMNS | {"api_token_id"}  # step 19 adds the device token's id
    assert db.table_columns(conn, "blood_pressures") == BP_COLUMNS | {"api_token_id"}
    for table in ("weights", "blood_pressures"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    for table, prefix in (("weights", "weights"), ("blood_pressures", "blood_pressures")):
        found = indexes(conn, table)
        assert found[f"{prefix}_user_date"][:2] == (False, ["user_id", "date"])
        unique = found[f"{prefix}_user_source_key"]
        assert unique[:2] == (True, ["user_id", "source_key"]) and "WHERE source_key IS NOT NULL" in unique[2]
    m018.migrate(conn)  # a re-run changes nothing
    assert db.migrate(conn) == []
    conn.close()


def test_a_fresh_database_gets_the_tables_too(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert db.table_exists(conn, "weights") and db.table_exists(conn, "blood_pressures")
    conn.close()


def test_the_tables_hold_what_the_api_writes_and_the_import_key_is_unique_per_person(tmp_path):
    path = tmp_path / "kidney.db"
    build_v17_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    weight(conn)
    weight(conn, time=None, note=None)  # the time and the note are optional
    weight(conn, user_id=1, kg=88.0, context="after_dialysis", source="apple_health", source_key="a" * 32)
    weight(conn, kg=71.0, source="import", source_key="a" * 32)  # the same key for another person is fine
    weight(conn, kg=71.5, context="a context a later version adds")  # the table lists no contexts: no rebuild is needed
    reading(conn)
    reading(conn, time=None, pulse=None, context="evening")
    reading(conn, user_id=1, systolic=150, diastolic=95, context="before_dialysis", source_key="b" * 32)
    reading(conn, source_key="b" * 32)
    conn.commit()
    row = conn.execute("SELECT source, source_key, note FROM weights WHERE user_id = 2 ORDER BY id LIMIT 1").fetchone()
    assert (row["source"], row["source_key"], row["note"]) == ("manual", None, "")  # manual is the default source
    # Rows with no key never clash with each other; a repeated key for one person is refused.
    weight(conn, source_key="k1")
    with pytest.raises(sqlite3.IntegrityError):
        weight(conn, source_key="k1")
    conn.rollback()
    reading(conn, source_key="k1")
    with pytest.raises(sqlite3.IntegrityError):
        reading(conn, source_key="k1")
    conn.rollback()
    # NOT NULL holds, and a row needs a person who exists.
    for bad in (dict(kg=None), dict(date=None), dict(context=None), dict(user_id=99)):
        with pytest.raises(sqlite3.IntegrityError):
            weight(conn, **bad)
        conn.rollback()
    for bad in (dict(systolic=None), dict(diastolic=None), dict(date=None), dict(context=None), dict(user_id=99)):
        with pytest.raises(sqlite3.IntegrityError):
            reading(conn, **bad)
        conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM blood_pressures").fetchone()[0] == 4
    conn.close()


def test_ids_are_never_reused(tmp_path):
    path = tmp_path / "kidney.db"
    build_v17_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    weight(conn)
    weight(conn)
    conn.execute("DELETE FROM weights WHERE id = 2")
    weight(conn)
    assert [r[0] for r in conn.execute("SELECT id FROM weights ORDER BY id")] == [1, 3]
    conn.close()


def test_deleting_an_account_removes_its_rows_and_only_its_own(tmp_path):
    path = tmp_path / "kidney.db"
    build_v17_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    weight(conn)
    weight(conn, user_id=1, kg=90.0)
    reading(conn)
    reading(conn, user_id=1, systolic=140, diastolic=90)
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert [(r["user_id"], r["kg"]) for r in conn.execute("SELECT user_id, kg FROM weights")] == [(1, 90.0)]
    assert [(r["user_id"], r["systolic"]) for r in conn.execute("SELECT user_id, systolic FROM blood_pressures")] == [(1, 140)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
