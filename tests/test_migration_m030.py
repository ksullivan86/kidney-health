"""Schema step 30 (``app/migrations/m030_activity.py``): activity and recovery tables, and a fifth Care team area.

``shares.areas`` and ``care_invites.areas`` held at most 4 areas; the step rebuilds both with 5. Every row must survive, the link
from an invite to its share too (dropping ``shares`` would set it to NULL), the indexes must come back, and the step must be safe to
run twice. The "before" database is ``steps()[:29]``."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m030_activity as m030
from conftest import insert_users

NOW = "2026-10-31T08:00:00.000000Z"
FIVE = '["food","labs","body","symptoms","activity"]'


def build_v29(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:29]) == list(range(1, 30))
    insert_users(conn, [(1, "admin"), (2, "sam"), (3, "kim")])
    conn.execute("INSERT INTO shares (id, owner_user_id, grantee_user_id, areas, created_at, accepted_at, role) "
                 "VALUES (7, 1, 2, '[\"food\",\"labs\"]', ?, ?, 'care_helper')", (NOW, NOW))
    conn.execute("INSERT INTO shares (id, owner_user_id, code_id, verifier_hash, areas, created_at, expires_at) "
                 "VALUES (8, 1, 'abcdef0123456789', x'00', '[\"body\"]', ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO care_invites (id, owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at, "
                 "answered_at, answer, share_id) VALUES (3, 1, 2, 'sam', '[\"food\",\"labs\"]', 'care_helper', ?, ?, ?, 'accepted', 7)",
                 (NOW, NOW, NOW))
    conn.execute("INSERT INTO care_invites (id, owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at) "
                 "VALUES (4, 1, 3, 'kim', '[\"symptoms\"]', 'viewer', ?, ?)", (NOW, NOW))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE shares SET areas = ? WHERE id = 7", (FIVE,))
    conn.rollback()
    conn.close()


def test_step_30_follows_step_29():
    step = migrations.steps()[29]
    assert step.version == 30 and step.name == "m030_activity" and step.atomic and step.foreign_key_check and step.backup_before


def test_upgrade_keeps_shares_invites_and_links_and_allows_five_areas(tmp_path):
    path = tmp_path / "kidney.db"
    build_v29(path)
    conn = db.connect(path)
    before = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("shares", "care_invites")}
    assert db.migrate(conn, migrations.steps()[:30]) == [30]
    after = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("shares", "care_invites")}
    assert after == before  # the invite still points at share 7
    conn.execute("UPDATE shares SET areas = ? WHERE id = 7", (FIVE,))
    conn.execute("UPDATE care_invites SET areas = ? WHERE id = 4", (FIVE,))
    with pytest.raises(sqlite3.IntegrityError):  # still at most five, at least one
        conn.execute("UPDATE shares SET areas = '[]' WHERE id = 7")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE tbl_name IN ('shares', 'care_invites') AND type = 'index' "
                                        "AND name NOT LIKE 'sqlite_%'")}
    assert names == {"shares_owner", "shares_grantee", "care_invites_owner", "care_invites_invitee"}
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_new'").fetchall()
    assert db.table_columns(conn, "activity_days") >= {"user_id", "date", "kcal", "hrv_ms", "finished", "source_key"}
    conn.commit()
    m030.migrate(conn)  # again: nothing changes
    assert [tuple(r) for r in conn.execute("SELECT id, share_id FROM care_invites ORDER BY id")] == [(3, 7), (4, None)]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM shares WHERE id = 7")  # the foreign key still points at the rebuilt table
    assert conn.execute("SELECT share_id FROM care_invites WHERE id = 3").fetchone()[0] is None
    conn.close()


def test_activity_tables_cascade_and_check(tmp_path):
    conn = db.connect(tmp_path / "kidney.db")
    db.migrate(conn)
    insert_users(conn, [(1, "admin")])
    conn.execute("INSERT INTO activity_days (user_id, date, source, source_key, kcal, finished, created_at, updated_at) "
                 "VALUES (1, '2026-10-30', 'whoop', 'whoop:cycle:1', 2400, 1, ?, ?)", (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):  # one row per person, date and source
        conn.execute("INSERT INTO activity_days (user_id, date, source, source_key, created_at, updated_at) "
                     "VALUES (1, '2026-10-30', 'whoop', 'whoop:cycle:2', ?, ?)", (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO activity_extra (user_id, enabled, share_pct, updated_at) VALUES (1, 1, 5, ?)", (NOW,))
    conn.execute("INSERT INTO activity_extra (user_id, enabled, share_pct, ceiling_kcal, updated_at) VALUES (1, 1, 50, 400, ?)", (NOW,))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM users WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) FROM activity_days").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM activity_extra").fetchone()[0] == 0
    conn.close()
