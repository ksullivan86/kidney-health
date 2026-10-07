"""Schema step 7 (``app/migrations/m007_barcode.py``, note 03 R6): food barcode and provenance columns and
``barcode_cache``, applied to a populated database at the step before it (§6 checklist item 9)."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m007_barcode as m007
from conftest import insert_users

NOW = "2026-10-05T08:00:00.000000Z"
NEW_COLUMNS = {name for name, _ in m007.FOOD_COLUMNS}


def build_v6_with_data(path) -> None:
    """A database exactly at schema 6 with two people, builtin, custom and USDA foods and log entries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:6]) == [1, 2, 3, 4, 5, 6]
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.executemany(
        """INSERT INTO foods (name, source, fdc_id, serving_desc, serving_g, potassium_mg, flags_json, owner_user_id,
                              created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("Banana, raw", "builtin", 173944, "1 medium (118 g)", 118, 422, "[]", None, NOW, NOW),
            ("Rice", "custom", None, "1 cup", 158, 55, "[]", 1, NOW, NOW),
            ("Oats", "usda", 424242, "100 g", 100, 362, "[]", None, NOW, NOW),
        ],
    )
    conn.execute("INSERT INTO user_food_links (user_id, food_id, created_at) VALUES (2, 3, ?)", (NOW,))
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, created_at, updated_at)
           VALUES (1, '2026-10-05', 'lunch', 2, 'Rice', 1, ?, ?), (2, '2026-10-05', 'breakfast', 3, 'Oats', 0.5, ?, ?)""",
        (NOW, NOW, NOW, NOW),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 6
    assert NEW_COLUMNS.isdisjoint(db.table_columns(conn, "foods"))
    assert not db.table_exists(conn, "barcode_cache")
    conn.close()


def test_step_7_is_registered_in_order():
    steps = migrations.steps()
    assert [s.version for s in steps][:7] == [1, 2, 3, 4, 5, 6, 7]
    assert steps[6].name == "m007_barcode" and steps[6].atomic and steps[6].schema == ""


def test_populated_database_upgrades_and_keeps_every_row(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v6_with_data(path)
    applied = db.init_db(path)
    assert applied[0] == 7 and applied == list(range(7, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert NEW_COLUMNS <= db.table_columns(conn, "foods")
    rows = conn.execute("SELECT * FROM foods ORDER BY id").fetchall()
    assert [(r["name"], r["source"], r["potassium_mg"]) for r in rows] == [("Banana, raw", "builtin", 422), ("Rice", "custom", 55),
                                                                         ("Oats", "usda", 362)]
    for row in rows:  # old rows read as "no barcode, no notes"
        assert row["quality_json"] == "[]" and row["additives_json"] == "[]"
        for column in ("gtin", "source_url", "source_license", "retrieved_at", "ingredients_text"):
            assert row[column] is None, column
    assert conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM user_food_links").fetchone()[0] == 1
    assert db.table_columns(conn, "barcode_cache") == {"gtin", "provider", "status", "payload_json", "fetched_at"}
    indexes = {r["name"]: r["sql"] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")}
    assert "WHERE gtin IS NOT NULL" in indexes["foods_gtin"]
    assert "UNIQUE" in indexes["foods_off_gtin"] and "source = 'off'" in indexes["foods_off_gtin"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_step_7_is_idempotent_and_a_fresh_database_matches(tmp_path):
    upgraded = tmp_path / "up" / "kidney.db"
    build_v6_with_data(upgraded)
    db.init_db(upgraded)
    assert db.init_db(upgraded) == []
    conn = db.connect(upgraded)
    m007.migrate(conn)  # a re-run of the step itself changes nothing
    conn.commit()
    up_cols = db.table_columns(conn, "foods")
    conn.close()
    fresh = tmp_path / "fresh" / "kidney.db"
    fresh.parent.mkdir(parents=True)
    db.init_db(fresh)
    conn = db.connect(fresh)
    assert db.table_columns(conn, "foods") == up_cols
    conn.close()


def test_constraints(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    path.parent.mkdir(parents=True)
    db.init_db(path)
    conn = db.connect(path)
    insert = "INSERT INTO barcode_cache (gtin, provider, status, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?)"
    conn.execute(insert, ("00049000028911", "off", "found", "{}", NOW))
    for bad in [("123", "off", "found", None, NOW), ("00049000028911", "nutritionix", "found", None, NOW),
                ("00049000028911", "usda", "maybe", None, NOW)]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, bad)
    with pytest.raises(sqlite3.IntegrityError):  # one row per (gtin, provider)
        conn.execute(insert, ("00049000028911", "off", "not_found", None, NOW))
    food = "INSERT INTO foods (name, source, serving_desc, serving_g, gtin, created_at, updated_at) VALUES (?, ?, '100 g', 100, ?, ?, ?)"
    conn.execute(food, ("Diet Coke", "off", "00049000028911", NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):  # one shared Open Food Facts row per barcode
        conn.execute(food, ("Diet Coke again", "off", "00049000028911", NOW, NOW))
    conn.execute(food, ("Diet Coke (USDA)", "usda", "00049000028911", NOW, NOW))  # other sources may share it
    conn.close()
