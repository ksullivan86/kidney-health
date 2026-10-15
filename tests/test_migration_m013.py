"""Schema step 13 (``app/migrations/m013_assistant_ask_keys.py``): the Ask chat's duplicate guard on a populated
schema-v12 database. Every earlier row stays; the new table keeps hashes only, with the constraints the app relies on,
and deleting an account removes its keys (``ON DELETE CASCADE``). Nothing else changes: the trust choice is a field of
the ``ai`` setting, not a column."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app import db, migrations
from app.migrations import m013_assistant_ask_keys as m013
from conftest import insert_users

NOW = "2026-10-15T08:00:00.000000Z"
SAVED = '{"entry_ids":[1]}'


def build_v12_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:12]) == list(range(1, 13))
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
        "INSERT INTO user_settings (user_id, key, value_json, updated_at) VALUES (2, 'ai', '{\"opt_in\":true}', ?)", (NOW,))
    conn.commit()
    assert db.get_schema_version(conn) == 12 and not db.table_exists(conn, "assistant_ask_keys")
    conn.close()


def key_row(conn: sqlite3.Connection, seed: str, *, user_id: int = 2, tool: str = "log_food",
            key_hash: str | None = None) -> None:
    conn.execute(
        "INSERT INTO assistant_ask_keys (key_hash, user_id, tool, saved_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (key_hash or hashlib.sha256(seed.encode()).hexdigest(), user_id, tool, SAVED, NOW),
    )


def test_step_13_follows_step_12():
    steps = migrations.steps()
    assert [s.version for s in steps][:13] == list(range(1, 14))
    step = steps[12]
    assert step.name == "m013_assistant_ask_keys" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v12_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    build_v12_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 13 and applied == list(range(13, db.SCHEMA_VERSION + 1))  # step 13, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = 2").fetchone()[0] == 1
    assert conn.execute("SELECT value_json FROM user_settings WHERE user_id = 2").fetchone()[0] == '{"opt_in":true}'
    assert db.table_columns(conn, "assistant_ask_keys") == {"key_hash", "user_id", "tool", "saved_json", "created_at"}
    assert db.table_columns(conn, "assistant_request_keys") >= {"token_id"}  # step 11's table is untouched
    assert conn.execute("SELECT COUNT(*) FROM assistant_ask_keys").fetchone()[0] == 0
    m013.migrate(conn)  # a re-run changes nothing
    assert db.migrate(conn) == []
    conn.close()


def test_a_fresh_database_gets_the_table_too(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert db.table_exists(conn, "assistant_ask_keys")
    conn.close()


def test_constraints_and_the_cascade(tmp_path):
    path = tmp_path / "kidney.db"
    build_v12_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    key_row(conn, "a")
    key_row(conn, "b", user_id=1)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # the same hash twice
        key_row(conn, "a")
    with pytest.raises(sqlite3.IntegrityError):  # not a SHA-256 hex digest (the plain key must never fit)
        key_row(conn, "x", key_hash="request-id-0001-1")
    with pytest.raises(sqlite3.IntegrityError):  # no tool
        key_row(conn, "d", tool="")
    with pytest.raises(sqlite3.IntegrityError):  # a person who does not exist
        key_row(conn, "e", user_id=99)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM assistant_ask_keys").fetchone()[0] == 2
    conn.execute("DELETE FROM users WHERE id = 2")  # a deleted account takes its keys
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT user_id FROM assistant_ask_keys")] == [1]
    conn.close()
