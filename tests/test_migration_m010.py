"""Schema step 10 (``app/migrations/m010_api_tokens.py``): assistant access tokens on a populated schema-v9
database. Every earlier row stays; the new table keeps hashes only, with the constraints the app relies on,
and deleting an account removes its tokens (``ON DELETE CASCADE``)."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app import db, migrations
from app.migrations import m010_api_tokens as m010
from conftest import insert_users

NOW = "2026-10-14T08:00:00.000000Z"
LATER = "2027-01-12T08:00:00.000000Z"


def build_v9_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:9]) == list(range(1, 10))
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
    conn.execute("INSERT INTO user_profiles (user_id, about_tolerance_pct, updated_at, updated_by) VALUES (2, 5, ?, 2)", (NOW,))
    conn.commit()
    assert db.get_schema_version(conn) == 9 and not db.table_exists(conn, "api_tokens")
    conn.close()


def token_row(conn: sqlite3.Connection, user_id: int, token: str, *, name: str = "Open WebUI") -> int:
    cur = conn.execute(
        """INSERT INTO api_tokens (user_id, name, token_hash, prefix, scopes, created_at, expires_at)
           VALUES (?, ?, ?, ?, 'assistant:read', ?, ?)""",
        (user_id, name, hashlib.sha256(token.encode()).hexdigest(), token[:12], NOW, LATER),
    )
    return int(cur.lastrowid)


def test_step_10_follows_step_9():
    steps = migrations.steps()
    assert [s.version for s in steps][:10] == list(range(1, 11))
    step = steps[9]
    assert step.name == "m010_api_tokens" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v9_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    build_v9_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 10 and applied == list(range(10, db.SCHEMA_VERSION + 1))  # step 10, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = 2").fetchone()[0] == 1
    assert conn.execute("SELECT about_tolerance_pct FROM user_profiles WHERE user_id = 2").fetchone()[0] == 5
    assert db.table_columns(conn, "api_tokens") == {"id", "user_id", "name", "token_hash", "prefix", "scopes", "created_at",
                                                     "last_used_at", "expires_at", "revoked_at"}
    m010.migrate(conn)  # a re-run changes nothing
    assert db.migrate(conn) == []
    conn.close()


def test_constraints_and_the_cascade(tmp_path):
    path = tmp_path / "kidney.db"
    build_v9_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    token = "kha_" + "a" * 43
    first = token_row(conn, 2, token)
    token_row(conn, 1, "kha_" + "b" * 43)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # the same hash twice
        token_row(conn, 1, token)
    with pytest.raises(sqlite3.IntegrityError):  # a name of 61 characters
        token_row(conn, 1, "kha_" + "c" * 43, name="x" * 61)
    with pytest.raises(sqlite3.IntegrityError):  # an empty name
        token_row(conn, 1, "kha_" + "d" * 43, name="")
    with pytest.raises(sqlite3.IntegrityError):  # a person who does not exist
        token_row(conn, 99, "kha_" + "e" * 43)
    with pytest.raises(sqlite3.IntegrityError):  # not a SHA-256 hex digest
        conn.execute("""INSERT INTO api_tokens (user_id, name, token_hash, prefix, scopes, created_at, expires_at)
                        VALUES (1, 'x', 'plain', 'kha_aaaaaaaa', 'assistant:read', ?, ?)""", (NOW, LATER))
    conn.rollback()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM api_tokens WHERE id = ?", (first,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id = 1").fetchone()[0] == 1
    # AUTOINCREMENT: a new token never reuses a removed token's id
    assert token_row(conn, 1, "kha_" + "f" * 43) > first + 1
    conn.close()
