"""Schema step 23 (``app/migrations/m023_passkeys.py``): the ``passkeys`` table (design note 18 §4).

On a populated schema-v22 database every account stays and nobody has a passkey, a re-run changes nothing, a credential ID is
unique and at most 1,023 bytes, deleting an account deletes its rows, and a fresh database has the same table. The "before"
database is built from ``steps()[:22]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users

ROW = ("INSERT INTO passkeys (user_id, credential_id, public_key, alg, user_handle, name, created_at) "
       "VALUES (?, ?, x'a1', -7, ?, 'Phone', 'now')")


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_step_23_follows_step_22():
    steps = migrations.steps()
    assert [s.version for s in steps][:23] == list(range(1, 24))
    step = steps[22]
    assert step.name == "m023_passkeys" and step.atomic and step.schema == "" and step.foreign_key_check


def test_a_v22_database_upgrades_with_nobody_having_a_passkey(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:22]) == list(range(1, 23))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.commit()
    assert "passkeys" not in tables(conn)
    conn.close()

    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 23 and applied == list(range(23, db.SCHEMA_VERSION + 1))
    assert "passkeys" in tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] == 0
    assert db.migrate(conn) == []  # a re-run changes nothing

    conn.execute(ROW, (2, b"\x01" * 16, b"\x02" * 32))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ROW, (1, b"\x01" * 16, b"\x03" * 32))  # the same credential ID twice
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ROW, (1, b"x" * 1024, b"\x03" * 32))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ROW, (1, b"", b"\x03" * 32))
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] == 0
    conn.close()


def test_a_fresh_database_has_the_same_table(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    db.migrate(conn)
    assert "passkeys" in tables(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(passkeys)")}
    assert cols == {"id", "user_id", "credential_id", "public_key", "alg", "user_handle", "sign_count", "name", "backed_up",
                    "created_at", "last_used_at"}
    conn.close()
