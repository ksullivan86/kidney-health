"""Schema step 5 (``app/migrations/m005_guidance_log.py``; note 06 §4.11, note 02 R5) applied to a
populated schema-v4 database: entry purpose and client_id, the per-person unique client_id index,
``meal_templates.meal_hint``, ``food_preferences`` and the ``meta.foods_rev`` triggers."""
from __future__ import annotations

import sqlite3

import pytest
from app import db, migrations
from app.migrations import m005_guidance_log as m005
from conftest import insert_users

NOW = "2026-10-05T08:00:00.000000Z"


def build_v4_with_data(path) -> None:
    """A database exactly at schema v4 with two people, a custom food, entries and a saved meal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:4]) == [1, 2, 3, 4]
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (1, 'Rice', 'custom', '1 cup', 158, 1, ?, ?), (2, 'Glucose tablets', 'custom', '4 tablets', 16, 2, ?, ?)""",
        (NOW, NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, created_at, updated_at)
           VALUES (1, '2026-10-05', 'lunch', 1, 'Rice', 1, ?, ?), (2, '2026-10-05', 'snack', 2, 'Glucose tablets', 1, ?, ?)""",
        (NOW, NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO meal_templates (user_id, name, items_json, created_at, updated_at)
           VALUES (1, 'Usual lunch', '[{"food_id": 1, "servings": 1}]', ?, ?)""",
        (NOW, NOW),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 4
    assert {"purpose", "client_id"}.isdisjoint(db.table_columns(conn, "log_entries"))
    assert "meal_hint" not in db.table_columns(conn, "meal_templates")
    assert not db.table_exists(conn, "food_preferences")
    conn.close()


def foods_rev(conn: sqlite3.Connection) -> int:
    return int(db.get_meta(conn, m005.FOODS_REV_KEY))


def test_step_5_follows_the_targets_step():
    steps = migrations.steps()
    assert [s.version for s in steps][:5] == [1, 2, 3, 4, 5]
    assert steps[4].name == "m005_guidance_log" and steps[4].atomic and steps[4].schema == ""


def test_populated_v4_database_upgrades_and_keeps_every_row(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v4_with_data(path)
    applied = db.init_db(path)
    assert applied[0] == 5
    conn = db.connect(path)
    assert {"purpose", "client_id"} <= db.table_columns(conn, "log_entries")
    assert "meal_hint" in db.table_columns(conn, "meal_templates")
    rows = conn.execute("SELECT user_id, food_name, purpose, client_id FROM log_entries ORDER BY id").fetchall()
    # Existing rows are never guessed to be low treatments.
    assert [tuple(r) for r in rows] == [(1, "Rice", None, None), (2, "Glucose tablets", None, None)]
    template = conn.execute("SELECT name, meal_hint FROM meal_templates").fetchone()
    assert tuple(template) == ("Usual lunch", None)
    assert {"user_id", "food_id", "preference", "created_at"} == db.table_columns(conn, "food_preferences")
    index = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'log_client_id'").fetchone()[0]
    assert "UNIQUE" in index and "user_id, client_id" in index and "client_id IS NOT NULL" in index
    assert foods_rev(conn) >= 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_step_5_is_idempotent(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v4_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    rev = foods_rev(conn)
    m005.migrate(conn)  # a re-run (partly upgraded database) changes nothing
    conn.commit()
    assert foods_rev(conn) == rev
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'foods_rev_%'").fetchone()[0] == 3
    conn.close()
    assert db.init_db(path) == []


def test_client_id_is_unique_per_person_only(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v4_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    insert = """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, client_id, created_at, updated_at)
                VALUES (?, '2026-10-06', 'lunch', 1, 'Rice', 1, ?, ?, ?)"""
    cid = "6f1c2c1e-7d0b-4c47-9a53-3f2f5a0b9e11"
    conn.execute(insert, (1, cid, NOW, NOW))
    conn.execute(insert, (2, cid, NOW, NOW))  # another person may use the same id
    conn.execute(insert, (1, None, NOW, NOW))
    conn.execute(insert, (1, None, NOW, NOW))  # entries without an id never clash
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (1, cid, NOW, NOW))
    conn.close()


def test_food_preferences_cascade_with_the_food_and_the_account(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v4_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    conn.execute("INSERT INTO food_preferences VALUES (1, 1, 'not_for_me', ?)", (NOW,))
    conn.execute("INSERT INTO food_preferences VALUES (2, 2, 'not_for_me', ?)", (NOW,))
    with pytest.raises(sqlite3.IntegrityError):  # one row per person and food
        conn.execute("INSERT INTO food_preferences VALUES (1, 1, 'not_for_me', ?)", (NOW,))
    conn.execute("DELETE FROM log_entries WHERE food_id = 2")
    conn.execute("DELETE FROM foods WHERE id = 2")
    assert [tuple(r) for r in conn.execute("SELECT user_id, food_id FROM food_preferences")] == [(1, 1)]
    conn.execute("DELETE FROM log_entries WHERE user_id = 1")
    conn.execute("DELETE FROM meal_templates WHERE user_id = 1")
    conn.execute("DELETE FROM foods WHERE owner_user_id = 1")
    conn.execute("DELETE FROM users WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) FROM food_preferences").fetchone()[0] == 0
    conn.close()


def test_every_food_write_bumps_the_foods_revision(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v4_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    seen = [foods_rev(conn)]

    def changed() -> None:
        seen.append(foods_rev(conn))
        assert seen[-1] > seen[-2]

    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, fdc_id, created_at, updated_at)
           VALUES (3, 'Apple', 'usda', '1 medium', 182, 171688, ?, ?)""",
        (NOW, NOW),
    )
    changed()
    conn.execute("UPDATE foods SET hidden = 1 WHERE id = 1")
    changed()
    conn.execute("INSERT INTO user_food_links (user_id, food_id, created_at) VALUES (1, 3, ?)", (NOW,))
    changed()
    conn.execute("DELETE FROM user_food_links WHERE food_id = 3")
    changed()
    conn.execute("DELETE FROM foods WHERE id = 3")
    changed()
    conn.close()
