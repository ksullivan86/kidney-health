"""Schema step 17 (``app/migrations/m017_food_preference_source.py``): ``food_preferences`` gains ``source`` and
``updated_at`` (note 09 §4.2). Every earlier "Not for me" row stays, is the person's own (``source = 'person'``) and gets its
``created_at`` as ``updated_at``; the key, the foreign keys and the index are untouched; a re-run changes nothing, not even
a value the app wrote in between; deleting the account or the food still removes the row.

The "before" database is built from ``steps()[:16]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

from app import db, migrations
from app.migrations import m017_food_preference_source as m017
from conftest import insert_users

NOW = "2026-10-21T08:00:00.000000Z"
BEFORE = "2026-10-10T07:30:00.000000Z"


def build_v16_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:16]) == list(range(1, 17))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (1, 'Rice', 'custom', '1 cup', 158, 1, ?, ?), (2, 'Salmon', 'custom', '1 fillet', 150, 2, ?, ?)""",
        (NOW, NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO food_preferences (user_id, food_id, preference, created_at)
           VALUES (1, 1, 'not_for_me', ?), (2, 2, 'not_for_me', ?)""",
        (BEFORE, NOW),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 16
    assert {"source", "updated_at"}.isdisjoint(db.table_columns(conn, "food_preferences"))
    conn.close()


def rows(conn: sqlite3.Connection) -> list[tuple]:
    return [tuple(r) for r in conn.execute(
        "SELECT user_id, food_id, preference, created_at, source, updated_at FROM food_preferences ORDER BY user_id, food_id")]


def test_step_17_follows_step_16():
    steps = migrations.steps()
    assert [s.version for s in steps][:17] == list(range(1, 18))
    step = steps[16]
    assert step.name == "m017_food_preference_source" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v16_database_upgrades_and_keeps_every_row(tmp_path):
    path = tmp_path / "kidney.db"
    build_v16_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 17 and applied == list(range(17, db.SCHEMA_VERSION + 1))  # step 17, then any later step
    assert db.table_columns(conn, "food_preferences") == {"user_id", "food_id", "preference", "created_at", "source", "updated_at"}
    # The earlier rows are the person's own and were last changed when they were made.
    assert rows(conn) == [(1, 1, "not_for_me", BEFORE, "person", BEFORE), (2, 2, "not_for_me", NOW, "person", NOW)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    keys = [r["name"] for r in conn.execute("PRAGMA table_info(food_preferences)") if r["pk"]]
    assert keys == ["user_id", "food_id"]
    index = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'food_preferences_food'").fetchone()[0]
    assert "food_preferences(food_id)" in index
    conn.close()


def test_step_17_is_idempotent_and_keeps_what_the_app_wrote(tmp_path):
    path = tmp_path / "kidney.db"
    build_v16_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    # A preference the app wrote after the step, with its own source and time.
    conn.execute("UPDATE food_preferences SET preference = 'like', source = 'ask', updated_at = ? WHERE user_id = 2", (NOW,))
    conn.commit()
    before = rows(conn)
    m017.migrate(conn)  # a re-run changes nothing
    m017.migrate(conn)
    conn.commit()
    assert rows(conn) == before
    assert db.migrate(conn) == []
    conn.close()


def test_a_partly_upgraded_database_is_finished(tmp_path):
    """The column exists but the back-fill never ran (an interrupted older run): only the NULL rows are filled."""
    path = tmp_path / "kidney.db"
    build_v16_with_data(path)
    conn = db.connect(path)
    conn.execute("ALTER TABLE food_preferences ADD COLUMN source TEXT")
    conn.execute("UPDATE food_preferences SET source = 'ask' WHERE user_id = 2")
    conn.commit()
    m017.migrate(conn)
    conn.commit()
    assert rows(conn) == [(1, 1, "not_for_me", BEFORE, "person", BEFORE), (2, 2, "not_for_me", NOW, "ask", NOW)]
    conn.close()


def test_a_fresh_database_has_the_columns_and_the_table_still_cascades(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert {"source", "updated_at"} <= db.table_columns(conn, "food_preferences")
    insert_users(conn, [(2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (50, 'Rice', 'custom', '1 cup', 158, 2, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO food_preferences (user_id, food_id, preference, created_at, source, updated_at)
           VALUES (2, 50, 'less', ?, 'ask', ?)""",
        (NOW, NOW),
    )
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM food_preferences").fetchone()[0] == 0
    conn.close()
