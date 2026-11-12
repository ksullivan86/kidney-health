"""Schema step 35 (``app/migrations/m035_reminders.py``): ``push_subscriptions`` and ``reminders`` (design note 35).

A database at step 34 gains both tables empty and keeps everything else; the step is safe to run twice; only the three generic
kinds and four meals pass the CHECKs; an endpoint belongs to one device row; both tables go with their account."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m035_reminders as m035
from conftest import insert_users

NOW = "2026-11-12T10:00:00Z"


def test_step_35_follows_step_34():
    step = migrations.steps()[34]
    assert step.version == 35 and step.name == "m035_reminders" and step.atomic and step.foreign_key_check


def test_a_step_34_database_gains_the_tables_check_and_cascade(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, migrations.steps()[:34]) == list(range(1, 35))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.commit()
    assert db.migrate(conn) == list(range(35, db.SCHEMA_VERSION + 1))
    m035.migrate(conn)  # again: nothing changes
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0

    add = "INSERT INTO reminders (user_id, kind, meal, time_local, days, created_at) VALUES (?, ?, ?, '12:00', ?, ?)"
    conn.execute(add, (2, "log_meal", "lunch", 127, NOW))
    conn.execute(add, (2, "weigh_in", None, 1, NOW))
    for kind, meal, days in (("insulin", None, 127), ("low_glucose", None, 127), ("log_meal", "insulin", 127), ("weigh_in", None, 0),
                             ("weigh_in", None, 128)):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(add, (2, kind, meal, days, NOW))
    sub = "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) VALUES (?, ?, 'k', 'a', ?)"
    conn.execute(sub, (2, "https://web.push.apple.com/abc", NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sub, (1, "https://web.push.apple.com/abc", NOW))
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0
    conn.close()


def test_a_new_database_has_the_tables():
    conn = db.connect(":memory:")
    db.migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"reminders", "push_subscriptions"} <= names
    conn.close()
