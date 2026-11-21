"""Schema step 37 (``app/migrations/m037_app_sync.py``): ``app_sync_rows``, what the iPhone app sent (design note 38 §5.5).

A database at step 36 gains the table empty and keeps everything else; the step is safe to run twice; the CHECKs hold the kind,
the client ID's length and ``added``; ``(user_id, kind, client_id)`` is unique; purging a token keeps its receipts; the receipts go
with their account."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m037_app_sync as m037
from conftest import insert_users

NOW = "2026-11-21T10:00:00.000000Z"
CID = "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6c"
ADD = "INSERT INTO app_sync_rows (user_id, api_token_id, kind, client_id, row_id, added, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"


def test_step_37_follows_step_36():
    step = migrations.steps()[36]
    assert step.version == 37 and step.name == "m037_app_sync" and step.atomic and step.foreign_key_check


def test_a_step_36_database_gains_the_table_checks_and_cascades(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, migrations.steps()[:36]) == list(range(1, 37))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO api_tokens (id, user_id, name, token_hash, prefix, scopes, created_at, expires_at) "
                 "VALUES (7, 2, 'Phone', ?, 'khd_abcdefgh', 'body:write app:add', ?, '9999-12-31T23:59:59.999999Z')", ("0" * 64, NOW))
    conn.commit()
    assert db.migrate(conn) == list(range(37, db.SCHEMA_VERSION + 1))
    m037.migrate(conn)  # again: nothing changes
    assert conn.execute("SELECT COUNT(*) FROM app_sync_rows").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 1  # nothing else touched

    conn.execute(ADD, (2, 7, "entry", CID, 10, 1, NOW))
    conn.execute(ADD, (2, 7, "lab", CID, 11, 1, NOW))  # the same client ID for another kind is fine
    conn.execute(ADD, (1, None, "entry", CID, 12, 0, NOW))  # and for another person
    for row in ((2, 7, "entry", CID, 13, 1, NOW),  # repeated
                (2, 7, "medicine", "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6d", 1, 1, NOW),
                (2, 7, "food", "short", 1, 1, NOW),
                (2, 7, "food", "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6e", 1, 2, NOW),
                (3, None, "food", "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6f", 1, 1, NOW)):  # no such person
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ADD, row)
    conn.execute("DELETE FROM api_tokens WHERE id = 7")  # a purged token: the receipts stay, without it
    assert [r[0] for r in conn.execute("SELECT api_token_id FROM app_sync_rows WHERE user_id = 2")] == [None, None]
    conn.execute("DELETE FROM users WHERE id = 2")
    assert [r[0] for r in conn.execute("SELECT user_id FROM app_sync_rows")] == [1]
    conn.close()


def test_a_new_database_has_the_table():
    conn = db.connect(":memory:")
    db.migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
    assert {"app_sync_rows", "app_sync_rows_token", "app_sync_rows_row"} <= names
    conn.close()
