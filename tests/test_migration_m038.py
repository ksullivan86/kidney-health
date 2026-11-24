"""Schema step 38 (``app/migrations/m038_change_feed.py``): one ``client_id`` for every synced row, and the change feed's table and
triggers (design note 39 §8.2 and §8.4).

A database at step 37 with rows of every kind and step 37's receipts: the phone's IDs carry over for rows it added, every other row
gets a new random ID, the step runs twice without change, the IDs are unique per person, the triggers record every insert, update and
delete (one change per row, the latest), new rows get an ID, a delete leaves a tombstone with the row's ID, and deleting an account
deletes its changes and writes no tombstone."""
from __future__ import annotations

import re
import sqlite3

import pytest

from app import db, migrations
from app.migrations import m038_change_feed as m038
from conftest import insert_users

NOW = "2026-11-21T10:00:00.000000Z"
PHONE = "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6c"
FOUND = "7f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6d"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
RECEIPT = "INSERT INTO app_sync_rows (user_id, api_token_id, kind, client_id, row_id, added, created_at) VALUES (?, NULL, ?, ?, ?, ?, ?)"


def _rows(conn: sqlite3.Connection) -> None:
    """User 2's rows of every kind (ids 1 and 2 of each), and user 3's lab (id 3)."""
    conn.execute("INSERT INTO foods (id, name, source, serving_desc, serving_g, created_at, updated_at, owner_user_id) "
                 "VALUES (100, 'Pudding', 'custom', '1 bowl', 150, ?, ?, 2)", (NOW, NOW))
    conn.execute("INSERT INTO foods (id, name, source, serving_desc, serving_g, created_at, updated_at) "
                 "VALUES (101, 'Shared oats', 'usda', '1 cup', 40, ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO log_entries (id, date, meal, food_id, food_name, servings, created_at, updated_at, user_id) "
                 "VALUES (1, '2026-11-20', 'lunch', 100, 'Pudding', 1, ?, ?, 2)", (NOW, NOW))
    conn.execute("INSERT INTO meal_templates (id, name, items_json, created_at, updated_at, user_id) VALUES (1, 'Usual', '[]', ?, ?, 2)", (NOW, NOW))
    for lab_id, user in ((1, 2), (2, 2), (3, 3)):
        conn.execute("INSERT INTO lab_results (id, user_id, analyte, value, entered_value, entered_unit, taken_on, created_at) "
                     "VALUES (?, ?, 'potassium', 5.1, 5.1, 'mmol/L', '2026-11-20', ?)", (lab_id, user, NOW))
    conn.execute("INSERT INTO symptoms (id, user_id, date, symptom, severity, created_at) VALUES (1, 2, '2026-11-20', 'itching', 2, ?)", (NOW,))
    conn.execute("INSERT INTO weights (id, user_id, date, kg, context, created_at, updated_at) VALUES (1, 2, '2026-11-20', 70, 'morning', ?, ?)",
                 (NOW, NOW))
    conn.execute("INSERT INTO blood_pressures (id, user_id, date, systolic, diastolic, context, created_at, updated_at) "
                 "VALUES (1, 2, '2026-11-20', 122, 78, 'morning', ?, ?)", (NOW, NOW))


@pytest.fixture
def at_37(tmp_path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "kidney.db")
    assert db.migrate(conn, migrations.steps()[:37]) == list(range(1, 38))
    insert_users(conn, [(1, "admin"), (2, "sam"), (3, "ana")])
    _rows(conn)
    conn.execute(RECEIPT, (2, "lab", PHONE, 1, 1, NOW))  # the phone added lab 1
    conn.execute(RECEIPT, (2, "symptom", FOUND, 1, 0, NOW))  # the phone's symptom matched symptom 1, already here
    conn.execute(RECEIPT, (2, "weight", PHONE, 99, 1, NOW))  # a row deleted since: nothing to carry over
    conn.commit()
    yield conn
    conn.close()


def test_step_38_follows_step_37():
    step = migrations.steps()[37]
    assert step.version == 38 and step.name == "m038_change_feed" and step.atomic and step.foreign_key_check


def test_ids_carry_over_and_every_row_gets_one(at_37):
    conn = at_37
    assert db.migrate(conn) == list(range(38, db.SCHEMA_VERSION + 1))
    m038.migrate(conn)  # again: nothing changes
    assert conn.execute("SELECT client_id FROM lab_results WHERE id = 1").fetchone()[0] == PHONE  # added by the phone: its ID
    assert conn.execute("SELECT client_id FROM symptoms WHERE id = 1").fetchone()[0] != FOUND  # found here: its own ID
    for table, where in (("foods", "owner_user_id IS NOT NULL"), ("log_entries", "1"), ("meal_templates", "1"), ("lab_results", "1"),
                         ("symptoms", "1"), ("weights", "1"), ("blood_pressures", "1")):
        ids = [r[0] for r in conn.execute(f"SELECT client_id FROM {table} WHERE {where}")]
        assert ids and all(i == PHONE or UUID_RE.match(i) for i in ids), table
    assert conn.execute("SELECT client_id FROM foods WHERE id = 101").fetchone()[0] is None  # a shared food has none
    # every row is in the feed once, with its ID
    changes = conn.execute("SELECT user_id, kind, row_id, client_id, deleted FROM sync_changes ORDER BY id").fetchall()
    assert sorted((r[1], r[2]) for r in changes) == sorted([("food", 100), ("entry", 1), ("meal", 1), ("lab", 1), ("lab", 2), ("lab", 3),
                                                           ("symptom", 1), ("weight", 1), ("reading", 1)])
    assert all(r[3] is not None and r[4] == 0 for r in changes)
    assert {r[0] for r in changes if (r[1], r[2]) == ("lab", 3)} == {3}


def test_ids_are_unique_per_person_and_checked(at_37):
    conn = at_37
    db.migrate(conn)
    conn.execute("UPDATE lab_results SET client_id = ? WHERE id = 3", (PHONE,))  # another person may have the same ID
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE lab_results SET client_id = ? WHERE id = 2", (PHONE,))  # but not the same person
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE symptoms SET client_id = 'short' WHERE id = 1")


def test_the_triggers_record_the_latest_change_of_each_row(at_37):
    conn = at_37
    db.migrate(conn)
    top = conn.execute("SELECT MAX(id) FROM sync_changes").fetchone()[0]
    cur = conn.execute("INSERT INTO symptoms (user_id, date, symptom, severity, created_at) VALUES (2, '2026-11-21', 'cramps', 1, ?)", (NOW,))
    new_id = cur.lastrowid
    made = conn.execute("SELECT client_id FROM symptoms WHERE id = ?", (new_id,)).fetchone()[0]
    assert UUID_RE.match(made)  # a new row gets an ID
    given = conn.execute("INSERT INTO weights (user_id, date, kg, context, created_at, updated_at, client_id) "
                         "VALUES (2, '2026-11-21', 71, 'morning', ?, ?, ?)", (NOW, NOW, FOUND)).lastrowid
    assert conn.execute("SELECT client_id FROM weights WHERE id = ?", (given,)).fetchone()[0] == FOUND  # a given one is kept
    conn.execute("UPDATE symptoms SET severity = 3 WHERE id = ?", (new_id,))
    conn.execute("UPDATE symptoms SET note = 'x' WHERE id = ?", (new_id,))
    rows = conn.execute("SELECT kind, row_id, client_id, deleted FROM sync_changes WHERE id > ? ORDER BY id", (top,)).fetchall()
    assert [tuple(r) for r in rows] == [("weight", given, FOUND, 0), ("symptom", new_id, made, 0)]  # one per row, the latest last
    conn.execute("DELETE FROM symptoms WHERE id = ?", (new_id,))
    last = conn.execute("SELECT user_id, kind, row_id, client_id, deleted FROM sync_changes ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(last) == (2, "symptom", new_id, made, 1)  # the tombstone keeps the ID
    assert conn.execute("SELECT COUNT(*) FROM sync_changes WHERE kind = 'symptom' AND row_id = ?", (new_id,)).fetchone()[0] == 1
    # a shared food is never in anyone's feed
    conn.execute("UPDATE foods SET name = 'Oats' WHERE id = 101")
    assert conn.execute("SELECT COUNT(*) FROM sync_changes WHERE kind = 'food' AND row_id = 101").fetchone()[0] == 0


def test_deleting_an_account_deletes_its_changes_and_writes_no_tombstone(at_37):
    conn = at_37
    db.migrate(conn)
    conn.execute("INSERT INTO sync_purged (user_id, through_id) VALUES (2, 1)")
    conn.execute("DELETE FROM users WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) FROM sync_changes WHERE user_id = 2").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sync_purged").fetchone()[0] == 0
    assert [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM sync_changes")] == [3]


def test_a_new_database_has_the_tables_and_triggers():
    conn = db.connect(":memory:")
    db.migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger')")}
    assert {"sync_changes", "sync_purged", "sync_changes_feed", "sync_changes_user_deleted", "lab_results_client_id",
            "sync_log_entries_inserted", "sync_foods_deleted", "sync_blood_pressures_client_id"} <= names
    conn.close()
