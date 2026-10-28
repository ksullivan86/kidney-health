"""Schema step 22 (``app/migrations/m022_totp.py``): ``totp_factors`` and ``totp_recovery_codes`` for two-step sign-in (note 17 §4).

On a populated schema-v21 database every account stays and nobody has two-step sign-in, a re-run changes nothing, deleting an
account deletes its rows, a recovery code hash must be 32 bytes, and a fresh database has the same tables. The "before" database is
built from ``steps()[:21]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users

TABLES = {"totp_factors", "totp_recovery_codes"}


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_step_22_follows_step_21():
    steps = migrations.steps()
    assert [s.version for s in steps][:22] == list(range(1, 23))
    step = steps[21]
    assert step.name == "m022_totp" and step.atomic and step.schema == "" and step.foreign_key_check


def test_a_v21_database_upgrades_with_nobody_using_two_step_sign_in(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:21]) == list(range(1, 22))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.commit()
    assert not TABLES & tables(conn)
    conn.close()

    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 22 and applied == list(range(22, db.SCHEMA_VERSION + 1))
    assert TABLES <= tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM totp_factors").fetchone()[0] == 0
    assert db.migrate(conn) == []  # a re-run changes nothing

    conn.execute("INSERT INTO totp_factors (user_id, secret_enc, created_at, enabled_at) VALUES (2, x'00', 'now', 'now')")
    conn.execute("INSERT INTO totp_recovery_codes (user_id, code_hash) VALUES (2, ?)", (b"\x01" * 32,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO totp_recovery_codes (user_id, code_hash) VALUES (2, ?)", (b"\x01" * 16,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO totp_factors (user_id, secret_enc, created_at, last_step) VALUES (1, x'00', 'now', -1)")
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM totp_factors").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM totp_recovery_codes").fetchone()[0] == 0
    conn.close()


def test_a_fresh_database_has_the_same_tables(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    db.migrate(conn)
    assert TABLES <= tables(conn)
    cols = db.table_columns(conn, "totp_factors")
    assert cols == {"user_id", "secret_enc", "key_id", "created_at", "enabled_at", "last_step"}
    conn.close()
