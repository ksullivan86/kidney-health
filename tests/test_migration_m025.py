"""Schema step 25 (``app/migrations/m025_share_time_limit.py``): ``shares.lasts_days`` and ``shares.ends_at`` (design note 19 §11).

A schema-v24 database with links and shares upgrades with every row kept and both columns NULL (they last until stopped, as
before), a re-run changes nothing, and ``lasts_days`` must be 1 to 365. The "before" database is built from ``steps()[:24]``."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users


def test_step_25_follows_step_24():
    step = migrations.steps()[24]
    assert step.version == 25 and step.name == "m025_share_time_limit" and step.atomic and step.foreign_key_check


def test_a_v24_database_keeps_its_shares_and_they_last_until_stopped(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    db.migrate(conn, migrations.steps()[:24])
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at) VALUES (1, 2, '[\"food\"]', 'now', 'now')")
    conn.execute("INSERT INTO shares (owner_user_id, code_id, verifier_hash, areas, created_at, expires_at) "
                 "VALUES (1, 'aaaaaaaaaaaaaaaa', x'01', '[\"labs\"]', 'now', 'later')")
    conn.commit()
    conn.close()

    conn = db.connect(path)
    assert db.migrate(conn)[0] == 25
    rows = conn.execute("SELECT lasts_days, ends_at FROM shares ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(None, None), (None, None)]
    assert db.migrate(conn) == []
    conn.execute("UPDATE shares SET lasts_days = 365 WHERE id = 2")
    for bad in (0, 366):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE shares SET lasts_days = ? WHERE id = 2", (bad,))
    conn.close()
