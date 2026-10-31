"""Schema step 32 (``app/migrations/m032_list_sync.py``): ``list_sync``, a person's own list app (design note 30 §4).

A database at step 31 gains the table and keeps everything else; the step is safe to run twice; a person's row goes with their
account; one row per person."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m032_list_sync as m032
from conftest import insert_users

NOW = "2026-10-31T08:00:00.000000Z"


def test_step_32_follows_step_31():
    step = migrations.steps()[31]
    assert step.version == 32 and step.name == "m032_list_sync" and step.atomic and step.foreign_key_check


def test_a_step_31_database_gains_the_table_and_runs_twice(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, migrations.steps()[:31]) == list(range(1, 32))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.commit()
    assert db.migrate(conn) == list(range(32, db.SCHEMA_VERSION + 1))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(list_sync)")]
    assert cols == ["user_id", "app", "base_url", "list_id", "list_name", "key_enc", "key_id", "last_test_at", "last_test_error",
                    "last_sent_at", "last_sent_count", "created_at", "updated_at"]
    m032.migrate(conn)  # again: nothing changes
    conn.execute("INSERT INTO list_sync (user_id, app, base_url, created_at, updated_at) VALUES (2, 'grocy', 'https://g', ?, ?)",
                 (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO list_sync (user_id, app, base_url, created_at, updated_at) VALUES (2, 'mealie', 'https://m', ?, ?)",
                     (NOW, NOW))
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM list_sync").fetchone()[0] == 0
    conn.close()
