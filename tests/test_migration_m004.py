"""Schema step 4 (``app/migrations/m004_targets_labs.py``, note 05 §4.6): profile fields on
``user_profiles`` and the ``lab_results`` table, applied to a populated schema-v3 database."""
from __future__ import annotations

import sqlite3

from app import db, migrations
from app.migrations import m004_targets_labs as m004
from conftest import insert_users

NOW = "2026-10-05T08:00:00.000000Z"
NEW_COLUMNS = {name for name, _ in m004.PROFILE_COLUMNS}


def build_v3_with_data(path) -> None:
    """A database exactly at schema v3 with two people, their profiles and a log entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:3]) == [1, 2, 3]
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO user_profiles (user_id, name, weight_kg, height_cm, ckd_stage, dialysis, diabetes, targets_json, updated_at)
           VALUES (1, 'Ann', 70, 175, '3b', 'none', 'type1', '{"potassium_mg": 2500}', ?),
                  (2, 'Sam', 85, 180, '5', 'hemodialysis', 'none', '{}', ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO foods (name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES ('Rice', 'custom', '1 cup', 158, 1, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, created_at, updated_at)
           VALUES (1, '2026-10-05', 'lunch', 1, 'Rice', 1, ?, ?)""",
        (NOW, NOW),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 3
    assert NEW_COLUMNS.isdisjoint(db.table_columns(conn, "user_profiles"))
    assert not db.table_exists(conn, "lab_results")
    conn.close()


def test_step_4_is_registered_after_the_accounts_step():
    steps = migrations.steps()
    assert [s.version for s in steps][:4] == [1, 2, 3, 4]
    assert steps[3].name == "m004_targets_labs" and steps[3].atomic and steps[3].schema == ""


def test_populated_v3_database_upgrades_and_keeps_every_row(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v3_with_data(path)
    applied = db.init_db(path)
    assert applied[0] == 4 and applied == list(range(4, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert NEW_COLUMNS <= db.table_columns(conn, "user_profiles")
    rows = {r["user_id"]: r for r in conn.execute("SELECT * FROM user_profiles ORDER BY user_id")}
    assert rows[1]["name"] == "Ann" and rows[1]["weight_kg"] == 70 and rows[1]["targets_json"] == '{"potassium_mg": 2500}'
    assert rows[2]["dialysis"] == "hemodialysis"
    for row in rows.values():  # the defaults of note 05 §4.2 (activity: NULL = not chosen)
        assert row["sex"] == "unspecified" and row["activity"] is None
        assert (row["frail_or_sarcopenic"], row["pregnant_or_breastfeeding"], row["hyperkalemia_history"]) == (0, 0, 0)
        for column in ("birth_month", "transplant_date", "weight_6_months_ago_kg", "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal"):
            assert row[column] is None, column
    assert conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0] == 1
    assert {"id", "user_id", "analyte", "value", "entered_value", "entered_unit", "taken_on", "note", "created_at"} == db.table_columns(
        conn, "lab_results"
    )
    index = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'lab_results_lookup'").fetchone()[0]
    assert "user_id, analyte, taken_on DESC, id DESC" in index
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_step_4_is_idempotent(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v3_with_data(path)
    db.init_db(path)
    assert db.init_db(path) == []
    conn = db.connect(path)
    before = [tuple(r) for r in conn.execute("PRAGMA table_info(user_profiles)")]
    m004.migrate(conn)  # a re-run (or a partly applied step) changes nothing and does not fail
    m004.migrate(conn)
    conn.commit()
    assert [tuple(r) for r in conn.execute("PRAGMA table_info(user_profiles)")] == before
    conn.close()


def test_partly_applied_step_adds_only_the_missing_columns(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v3_with_data(path)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE user_profiles ADD COLUMN sex TEXT NOT NULL DEFAULT 'unspecified'")
    conn.execute("UPDATE user_profiles SET sex = 'female' WHERE user_id = 1")
    conn.commit()
    conn.close()
    db.init_db(path)
    conn = db.connect(path)
    assert NEW_COLUMNS <= db.table_columns(conn, "user_profiles")
    assert conn.execute("SELECT sex FROM user_profiles WHERE user_id = 1").fetchone()[0] == "female"
    conn.close()


def test_lab_results_cascade_with_the_account(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v3_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    for uid in (1, 2, 2):
        conn.execute(
            """INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, created_at)
               VALUES (?, 'potassium', 4.5, 4.5, 'mmol/L', '2026-10-01', ?)""",
            (uid, NOW),
        )
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT user_id FROM lab_results")] == [1]
    assert conn.execute("SELECT COUNT(*) FROM user_profiles WHERE user_id = 2").fetchone()[0] == 0
    conn.close()


def test_fresh_database_gets_the_same_step_4_shape(tmp_path):
    fresh, old = tmp_path / "fresh.db", tmp_path / "data" / "kidney.db"
    db.init_db(fresh)
    build_v3_with_data(old)
    db.init_db(old)
    a, b = db.connect(fresh), db.connect(old)
    for table in ("user_profiles", "lab_results"):
        assert [tuple(r) for r in a.execute(f"PRAGMA table_info({table})")] == [tuple(r) for r in b.execute(f"PRAGMA table_info({table})")]
    a.close()
    b.close()
