"""Schema step 11 (``app/migrations/m011_assistant_request_keys.py``): the duplicate guard's table on a populated
schema-v10 database. Every earlier row stays; the new table keeps hashes only, with the constraints the app relies on,
and deleting an account or a token removes its keys (``ON DELETE CASCADE``)."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app import db, migrations
from app.migrations import m011_assistant_request_keys as m011
from conftest import insert_users

NOW = "2026-10-14T08:00:00.000000Z"
LATER = "2027-01-12T08:00:00.000000Z"
SAVED = '{"entry_ids":[1]}'


def build_v10_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:10]) == list(range(1, 11))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (1, 'Rice', 'custom', '1 cup', 158, 2, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, created_at, updated_at)
           VALUES (2, '2026-10-14', 'lunch', 1, 'Rice', 1, ?, ?)""",
        (NOW, NOW),
    )
    for token_id, user_id in ((1, 1), (2, 2)):
        conn.execute(
            """INSERT INTO api_tokens (id, user_id, name, token_hash, prefix, scopes, created_at, expires_at)
               VALUES (?, ?, 'Open WebUI', ?, ?, 'assistant:read assistant:log', ?, ?)""",
            (token_id, user_id, hashlib.sha256(f"kha_{token_id}".encode()).hexdigest(), f"kha_{token_id:08d}", NOW, LATER),
        )
    conn.commit()
    assert db.get_schema_version(conn) == 10 and not db.table_exists(conn, "assistant_request_keys")
    conn.close()


def key_row(conn: sqlite3.Connection, seed: str, *, user_id: int = 2, token_id: int = 2, tool: str = "log_food",
            key_hash: str | None = None) -> None:
    conn.execute(
        """INSERT INTO assistant_request_keys (key_hash, user_id, token_id, tool, saved_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (key_hash or hashlib.sha256(seed.encode()).hexdigest(), user_id, token_id, tool, SAVED, NOW),
    )


def test_step_11_follows_step_10():
    steps = migrations.steps()
    assert [s.version for s in steps][:11] == list(range(1, 12))
    step = steps[10]
    assert step.name == "m011_assistant_request_keys" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v10_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    build_v10_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 11 and applied == list(range(11, db.SCHEMA_VERSION + 1))  # step 11, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = 2").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 2
    assert db.table_columns(conn, "assistant_request_keys") == {"key_hash", "user_id", "token_id", "tool", "saved_json",
                                                                "created_at"}
    assert conn.execute("SELECT COUNT(*) FROM assistant_request_keys").fetchone()[0] == 0
    m011.migrate(conn)  # a re-run changes nothing
    assert db.migrate(conn) == []
    conn.close()


def test_a_fresh_database_gets_the_table_too(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert db.table_exists(conn, "assistant_request_keys")
    conn.close()


def test_constraints_and_the_cascades(tmp_path):
    path = tmp_path / "kidney.db"
    build_v10_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    key_row(conn, "a")
    key_row(conn, "b", user_id=1, token_id=1)
    key_row(conn, "c")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # the same hash twice
        key_row(conn, "a")
    with pytest.raises(sqlite3.IntegrityError):  # not a SHA-256 hex digest (the plain key must never fit)
        key_row(conn, "x", key_hash="retry-key-0001")
    with pytest.raises(sqlite3.IntegrityError):  # no tool
        key_row(conn, "d", tool="")
    with pytest.raises(sqlite3.IntegrityError):  # a person who does not exist
        key_row(conn, "e", user_id=99)
    with pytest.raises(sqlite3.IntegrityError):  # a token that does not exist
        key_row(conn, "f", token_id=99)
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM assistant_request_keys").fetchone()[0] == 3
    conn.execute("DELETE FROM api_tokens WHERE id = 1")  # a purged token takes its keys
    conn.commit()
    assert [r[0] for r in conn.execute("SELECT user_id FROM assistant_request_keys")] == [2, 2]
    conn.execute("DELETE FROM users WHERE id = 2")  # a deleted account takes its keys (and its token)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM assistant_request_keys").fetchone()[0] == 0
    conn.close()
