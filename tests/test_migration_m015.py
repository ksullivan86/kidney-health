"""Schema step 15 (``app/migrations/m015_symptoms.py``): the symptoms log on a populated schema-v14 database. Every earlier
row stays; the new table has the constraints the app relies on, no list of symptom keys (a later key must not need a table
rebuild), the (user, date) index, and deleting an account removes its symptoms (``ON DELETE CASCADE``)."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m015_symptoms as m015
from conftest import insert_users

NOW = "2026-10-15T08:00:00.000000Z"


def build_v14_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:14]) == list(range(1, 15))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (1, 'Rice', 'custom', '1 cup', 158, 2, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, created_at, updated_at)
           VALUES (2, '2026-10-15', 'lunch', 1, 'Rice', 1, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, created_at)
           VALUES (2, 'potassium', 4.8, 4.8, 'mmol/L', '2026-10-01', ?)""",
        (NOW,),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 14 and not db.table_exists(conn, "symptoms")
    conn.close()


def symptom(conn: sqlite3.Connection, *, user_id: int = 2, date: str = "2026-10-15", key: str = "tiredness", label: str = "",
            severity: int = 2, note: str = "") -> None:
    conn.execute(
        "INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, date, key, label, severity, note, NOW),
    )


def test_step_15_follows_step_14():
    steps = migrations.steps()
    assert [s.version for s in steps][:15] == list(range(1, 16))
    step = steps[14]
    assert step.name == "m015_symptoms" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v14_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    build_v14_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 15 and applied == list(range(15, db.SCHEMA_VERSION + 1))  # step 15, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = 2").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM lab_results WHERE user_id = 2").fetchone()[0] == 1
    assert db.table_columns(conn, "symptoms") == {"id", "user_id", "date", "symptom", "label", "severity", "note", "created_at"}
    assert conn.execute("SELECT COUNT(*) FROM symptoms").fetchone()[0] == 0
    indexes = {r["name"]: [c["name"] for c in conn.execute(f"PRAGMA index_info({r['name']})")] for r in conn.execute("PRAGMA index_list(symptoms)")}
    assert indexes["symptoms_user_date"] == ["user_id", "date", "id"]
    m015.migrate(conn)  # a re-run changes nothing
    assert db.migrate(conn) == []
    conn.close()


def test_a_fresh_database_gets_the_table_too(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert db.table_exists(conn, "symptoms")
    conn.close()


def test_constraints_and_the_cascade(tmp_path):
    path = tmp_path / "kidney.db"
    build_v14_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    symptom(conn)
    symptom(conn, user_id=1, key="other", label="Dry mouth", severity=3, note="n" * 300)
    symptom(conn, key="dizziness")  # a key that a later version adds: the table does not list keys, so no rebuild is needed
    conn.commit()
    for bad in (dict(severity=0), dict(severity=4), dict(date="2026-10-5"), dict(key=""), dict(key="k" * 41),
                dict(label="l" * 61), dict(note="n" * 301), dict(user_id=99)):
        with pytest.raises(sqlite3.IntegrityError):
            symptom(conn, **bad)
        conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM symptoms").fetchone()[0] == 3
    conn.execute("DELETE FROM users WHERE id = 2")  # a deleted account takes its symptoms (and nothing of anybody else's)
    conn.commit()
    assert [(r["user_id"], r["symptom"]) for r in conn.execute("SELECT user_id, symptom FROM symptoms")] == [(1, "other")]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
