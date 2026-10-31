"""Schema step 31 (``app/migrations/m031_care_team_full.py``): the switches of the full Care team and ``care_suggestions``.

Every existing share and invite keeps its meaning exactly: a Care helper plans (``may_plan = 1``), a Viewer does nothing, and no
other switch is on. Running the step twice changes nothing. The "before" database is ``steps()[:30]``."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from conftest import insert_users

NOW = "2026-10-31T08:00:00.000000Z"
SWITCHES = ("may_plan", "may_log", "may_use_saved_meals", "may_suggest")


def build_v30(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:30]) == list(range(1, 31))
    insert_users(conn, [(1, "admin"), (2, "sam"), (3, "kim")])
    conn.execute("INSERT INTO shares (id, owner_user_id, grantee_user_id, areas, created_at, accepted_at, role) "
                 "VALUES (7, 1, 2, '[\"food\",\"labs\"]', ?, ?, 'care_helper')", (NOW, NOW))
    conn.execute("INSERT INTO shares (id, owner_user_id, grantee_user_id, areas, created_at, accepted_at) "
                 "VALUES (8, 1, 3, '[\"labs\"]', ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO shares (id, owner_user_id, code_id, verifier_hash, areas, created_at, expires_at, role) "
                 "VALUES (9, 2, 'abcdef0123456789', x'00', '[\"food\"]', ?, ?, 'care_helper')", (NOW, NOW))
    conn.execute("INSERT INTO care_invites (id, owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at) "
                 "VALUES (3, 1, 2, 'sam', '[\"food\"]', 'care_helper', ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO care_invites (id, owner_user_id, invitee_user_id, username, areas, role, created_at, expires_at) "
                 "VALUES (4, 1, 3, 'kim', '[\"symptoms\"]', 'viewer', ?, ?)", (NOW, NOW))
    conn.commit()
    conn.close()


def switches(conn: sqlite3.Connection, table: str) -> dict[int, tuple[int, ...]]:
    return {int(r[0]): tuple(r[1:]) for r in conn.execute(f"SELECT id, {', '.join(SWITCHES)} FROM {table} ORDER BY id")}


def test_step_31_follows_step_30():
    step = migrations.steps()[30]
    assert step.version == 31 and step.name == "m031_care_team_full" and step.atomic and step.foreign_key_check


def test_old_shares_and_invites_keep_their_meaning(tmp_path):
    path = tmp_path / "kidney.db"
    build_v30(path)
    conn = db.connect(path)
    before = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("shares", "care_invites")}
    assert db.migrate(conn) == list(range(31, db.SCHEMA_VERSION + 1))  # step 31, then any later step
    assert switches(conn, "shares") == {7: (1, 0, 0, 0), 8: (0, 0, 0, 0), 9: (1, 0, 0, 0)}
    assert switches(conn, "care_invites") == {3: (1, 0, 0, 0), 4: (0, 0, 0, 0)}
    after = {t: [tuple(r)[:len(before[t][0])] for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in before}
    assert after == before  # every old column is unchanged
    # a second run (a partly upgraded database) never maps the role again
    conn.execute("UPDATE shares SET may_plan = 0 WHERE id = 7")
    migrations.steps()[30].migrate(conn)
    assert switches(conn, "shares")[7] == (0, 0, 0, 0)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE shares SET may_log = 2 WHERE id = 7")
    with pytest.raises(sqlite3.IntegrityError):  # the old role column keeps its check
        conn.execute("UPDATE shares SET role = 'caregiver' WHERE id = 7")
    conn.close()


def test_suggestions_check_and_cascade(tmp_path):
    path = tmp_path / "kidney.db"
    build_v30(path)
    conn = db.connect(path)
    db.migrate(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    ok = ("INSERT INTO care_suggestions (share_id, owner_user_id, from_user_id, date, meal, items_json, note, created_at, expires_at) "
          "VALUES (?, ?, ?, '2026-11-01', ?, ?, ?, ?, ?)")
    conn.execute(ok, (7, 1, 2, "lunch", '[{"food_id": 1, "servings": 1}]', "soup", NOW, NOW))
    bad = [
        (7, 1, 1, "lunch", '[{"food_id": 1}]', None, NOW, NOW),  # never to yourself
        (7, 1, 2, "brunch", '[{"food_id": 1}]', None, NOW, NOW),  # an unknown meal
        (7, 1, 2, "lunch", "[]", None, NOW, NOW),  # no food
        (7, 1, 2, "lunch", "{}", None, NOW, NOW),  # not a list
        (7, 1, 2, "lunch", '[{"food_id": 1}]', "x" * 281, NOW, NOW),  # a note over 280 characters
    ]
    for row in bad:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(ok, row)
    with pytest.raises(sqlite3.IntegrityError):  # an answer needs its time
        conn.execute("UPDATE care_suggestions SET answer = 'accepted'")
    conn.execute("UPDATE care_suggestions SET answer = 'ended', answered_at = ?", (NOW,))
    conn.execute("DELETE FROM users WHERE id = 2")  # the suggester's account goes: so do their suggestions and the share
    assert conn.execute("SELECT COUNT(*) FROM care_suggestions").fetchone()[0] == 0
    conn.close()
