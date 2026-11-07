"""Schema step 34 (``app/migrations/m034_reset_email.py``): ``users.email``, ``users.email_confirmed_at`` and ``email_tokens``
(design note 34).

A database at step 33 gains the columns empty for every account and keeps everything else; the step is safe to run twice; a
confirmed address belongs to one account only, while the same address typed but not confirmed blocks nobody; tokens go with
their account."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m034_reset_email as m034
from conftest import insert_users


def test_step_34_follows_step_33():
    step = migrations.steps()[33]
    assert step.version == 34 and step.name == "m034_reset_email" and step.atomic and step.foreign_key_check


def test_a_step_33_database_gains_the_columns_and_runs_twice(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, migrations.steps()[:33]) == list(range(1, 34))
    insert_users(conn, [(1, "admin"), (2, "sam"), (3, "alex")])
    conn.commit()
    assert db.migrate(conn) == list(range(34, db.SCHEMA_VERSION + 1))
    assert [tuple(r) for r in conn.execute("SELECT email, email_confirmed_at FROM users ORDER BY id")] == [(None, None)] * 3
    m034.migrate(conn)  # again: nothing changes

    conn.execute("UPDATE users SET email = 'sam@example.org' WHERE id IN (2, 3)")  # typed twice, confirmed by nobody: fine
    conn.execute("UPDATE users SET email_confirmed_at = '2026-11-07T10:00:00Z' WHERE id = 2")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE users SET email_confirmed_at = '2026-11-07T10:00:00Z' WHERE id = 3")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE users SET email = ? WHERE id = 1", ("a" * 310 + "@example.org",))

    conn.execute("INSERT INTO email_tokens (id, user_id, email, verifier_hash, created_at, expires_at) "
                 "VALUES ('t1', 3, 'sam@example.org', x'00', '2026-11-07T10:00:00Z', '2026-11-08T10:00:00Z')")
    conn.execute("DELETE FROM users WHERE id = 3")
    assert conn.execute("SELECT COUNT(*) FROM email_tokens").fetchone()[0] == 0
    conn.close()


def test_a_new_database_has_the_columns_and_table():
    conn = db.connect(":memory:")
    db.migrate(conn)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    assert "email" in columns and "email_confirmed_at" in columns
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'email_tokens'").fetchone() is not None
    conn.close()


def test_old_confirmation_links_are_purged():
    from app.auth.email_api import purge_old_links

    conn = db.connect(":memory:")
    db.migrate(conn)
    insert_users(conn, [(1, "admin")])
    rows = [("used", "2026-11-07T10:00:00Z", "2999-01-01T00:00:00Z"), ("old", None, "2000-01-01T00:00:00Z"),
            ("open", None, "2999-01-01T00:00:00Z")]
    for token_id, used, expires in rows:
        conn.execute("INSERT INTO email_tokens (id, user_id, email, verifier_hash, created_at, expires_at, used_at) "
                     "VALUES (?, 1, 'a@example.org', x'00', '2026-11-07T10:00:00Z', ?, ?)", (token_id, expires, used))
    assert purge_old_links(conn) == 2
    assert [r[0] for r in conn.execute("SELECT id FROM email_tokens")] == ["open"]
    conn.close()

