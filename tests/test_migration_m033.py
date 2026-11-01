"""Schema step 33 (``app/migrations/m033_ai_route_choice.py``): ``users.can_choose_ai`` (design note 32).

A database at step 32 gains the column with 0 for every account and keeps everything else; the step is safe to run twice; the
column takes only 0 or 1."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m033_ai_route_choice as m033
from conftest import insert_users


def test_step_33_follows_step_32():
    step = migrations.steps()[32]
    assert step.version == 33 and step.name == "m033_ai_route_choice" and step.atomic and step.foreign_key_check


def test_a_step_32_database_gains_the_column_off_for_everyone_and_runs_twice(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, migrations.steps()[:32]) == list(range(1, 33))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.commit()
    assert db.migrate(conn) == list(range(33, db.SCHEMA_VERSION + 1))
    assert [r[0] for r in conn.execute("SELECT can_choose_ai FROM users ORDER BY id")] == [0, 0]
    m033.migrate(conn)  # again: nothing changes
    conn.execute("UPDATE users SET can_choose_ai = 1 WHERE id = 2")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE users SET can_choose_ai = 2 WHERE id = 2")
    assert [r[0] for r in conn.execute("SELECT can_choose_ai FROM users ORDER BY id")] == [0, 1]
    conn.close()


def test_a_new_database_has_the_column():
    conn = db.connect(":memory:")
    db.migrate(conn)
    assert "can_choose_ai" in [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    conn.close()
