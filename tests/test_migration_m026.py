"""Schema 26 adds owned request receipts without altering existing health records."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users


def test_step_26_is_atomic_and_follows_the_released_steps():
    step = migrations.steps()[25]
    assert step.version == 26 and step.name == "m026_write_receipts"
    assert step.atomic and step.foreign_key_check


def test_v25_upgrade_preserves_records_and_repeated_migration_is_safe(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    db.migrate(conn, migrations.steps()[:25])
    insert_users(conn, [(1, "admin")])
    conn.execute("INSERT INTO weights (user_id, date, kg, context, source, created_at, updated_at) VALUES (1, '2026-10-01', 70.2, 'morning', 'manual', 'now', 'now')")
    conn.commit()
    db.migrate(conn)
    assert conn.execute("SELECT kg FROM weights WHERE user_id = 1").fetchone()[0] == 70.2
    assert conn.execute("SELECT COUNT(*) FROM write_receipts").fetchone()[0] == 0
    migrations.steps()[25].migrate(conn)
    assert db.get_schema_version(conn) >= 26
    conn.close()


def test_receipts_cascade_when_their_person_is_removed(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    db.migrate(conn)
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO write_receipts VALUES (2, 'body.weight', 'receipt-key', ?, '{}', 'now')", ("a" * 64,))
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM write_receipts WHERE user_id = 2").fetchone()[0] == 0
    conn.close()


def test_receipts_require_a_real_owner(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    db.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO write_receipts VALUES (999, 'body.weight', 'receipt-key', ?, '{}', 'now')", ("a" * 64,))
    conn.close()
