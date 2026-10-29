"""Schema step 24 (``app/migrations/m024_shares.py``): the ``shares`` table (design note 19 §4).

On a populated schema-v23 database every account stays and nobody shares anything, a re-run changes nothing, the two states of a
row (a link, then a share) are kept apart by the table's checks, and deleting either account deletes its rows. The "before"
database is built from ``steps()[:23]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users

CODE = ("INSERT INTO shares (owner_user_id, code_id, verifier_hash, areas, created_at, expires_at) "
        "VALUES (?, ?, x'01', ?, 'now', 'later')")
SHARE = "INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at) VALUES (?, ?, ?, 'now', 'now')"


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_step_24_follows_step_23():
    steps = migrations.steps()
    assert [s.version for s in steps][:24] == list(range(1, 25))
    step = steps[23]
    assert step.name == "m024_shares" and step.atomic and step.schema == "" and step.foreign_key_check


def test_a_v23_database_upgrades_with_nobody_sharing(tmp_path):
    path = tmp_path / "kidney.db"
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:23]) == list(range(1, 24))
    insert_users(conn, [(1, "admin"), (2, "sam"), (3, "kim")])
    conn.commit()
    assert "shares" not in tables(conn)
    conn.close()

    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 24 and applied == list(range(24, db.SCHEMA_VERSION + 1))
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 3
    assert conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 0
    assert db.migrate(conn) == []  # a re-run changes nothing

    conn.execute(CODE, (1, "a" * 16, '["food"]'))
    conn.execute(SHARE, (1, 2, '["food", "labs"]'))
    conn.execute(SHARE, (3, 2, '["body"]'))
    for bad in (
        (SHARE, (1, 1, '["food"]')),  # with yourself
        (SHARE, (1, 2, "[]")),  # no area
        (SHARE, (1, 2, '"food"')),  # not a list
        (CODE, (1, "a" * 16, '["food"]')),  # the same link id twice
        ("INSERT INTO shares (owner_user_id, areas, created_at) VALUES (1, '[\"food\"]', 'now')", ()),  # a link without its code
        ("INSERT INTO shares (owner_user_id, grantee_user_id, code_id, areas, created_at, accepted_at) "
         "VALUES (1, 2, 'b', '[\"food\"]', 'now', 'now')", ()),  # an accepted share still holding a link id
        ("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at, ended_at) "
         "VALUES (1, 2, '[\"food\"]', 'now', 'now', 'now')", ()),  # ended without saying by whom
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(*bad)
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM shares").fetchone()[0] == 1  # only admin's unused link is left
    conn.close()


def test_a_fresh_database_has_the_same_table(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    db.migrate(conn, migrations.steps()[:24])  # step 25 adds two columns (tests/test_migration_m025.py)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(shares)")}
    assert cols == {"id", "owner_user_id", "grantee_user_id", "code_id", "verifier_hash", "areas", "created_at", "expires_at",
                    "accepted_at", "ended_at", "ended_by", "last_viewed_at"}
    conn.close()
