"""Schema step 19 (``app/migrations/m019_body_token.py``): ``weights`` and ``blood_pressures`` gain ``api_token_id`` (design note 12
§4.3), on a populated schema-v18 database. Every earlier row stays and has no token; the column references ``api_tokens`` with
``ON DELETE SET NULL`` (purging a token keeps the rows); the partial indexes exist; step 18's ``(user_id, date)`` index is the one
the "same reading" check uses (no new ``(user_id, date, time)`` index); a re-run changes nothing; deleting an account still removes
its rows and its tokens.

The "before" database is built from ``steps()[:18]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m019_body_token as m019
from conftest import insert_users

NOW = "2026-10-22T08:00:00.000000Z"
LATER = "2026-11-22T08:00:00.000000Z"


def build_v18_with_data(path) -> None:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:18]) == list(range(1, 19))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO api_tokens (id, user_id, name, token_hash, prefix, scopes, created_at, expires_at)
           VALUES (1, 2, 'Open WebUI', ?, 'kha_AbCd1234', 'assistant:read', ?, ?)""",
        ("a" * 64, NOW, LATER),
    )
    conn.execute(
        """INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at)
           VALUES (2, '2026-10-21', '07:30', 70.25, 'morning', '', 'manual', NULL, ?, ?),
                  (2, '2026-10-21', '07:31', 70.5, 'morning', '', 'apple_health', 'k1', ?, ?),
                  (1, '2026-10-21', NULL, 88.0, 'other', '', 'import', 'k2', ?, ?)""",
        (NOW, NOW, NOW, NOW, NOW, NOW),
    )
    conn.execute(
        """INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, created_at, updated_at)
           VALUES (2, '2026-10-21', '07:35', 128, 78, 64, 'morning', '', 'manual', NULL, ?, ?),
                  (2, '2026-10-21', '19:35', 131, 81, NULL, 'evening', '', 'apple_health', 'k3', ?, ?)""",
        (NOW, NOW, NOW, NOW),
    )
    conn.commit()
    assert db.get_schema_version(conn) == 18
    assert "api_token_id" not in db.table_columns(conn, "weights") | db.table_columns(conn, "blood_pressures")
    conn.close()


def indexes(conn: sqlite3.Connection, table: str) -> dict[str, tuple[bool, list[str], str | None]]:
    out = {}
    for r in conn.execute(f"PRAGMA index_list({table})"):
        cols = [c["name"] for c in conn.execute(f"PRAGMA index_info({r['name']})")]
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (r["name"],)).fetchone()[0]
        out[r["name"]] = (bool(r["unique"]), cols, sql)
    return out


def test_step_19_follows_step_18():
    steps = migrations.steps()
    assert [s.version for s in steps][:19] == list(range(1, 20))
    step = steps[18]
    assert step.name == "m019_body_token" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v18_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    build_v18_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 19 and applied == list(range(19, db.SCHEMA_VERSION + 1))  # step 19, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    assert {"api_token_id"} <= db.table_columns(conn, "weights") and {"api_token_id"} <= db.table_columns(conn, "blood_pressures")
    # nothing was lost or changed, and no earlier row has a token
    assert [tuple(r) for r in conn.execute("SELECT user_id, time, kg, source, source_key, api_token_id FROM weights ORDER BY id")] == [
        (2, "07:30", 70.25, "manual", None, None), (2, "07:31", 70.5, "apple_health", "k1", None), (1, None, 88.0, "import", "k2", None)]
    assert [tuple(r) for r in conn.execute("SELECT user_id, systolic, diastolic, source, source_key, api_token_id FROM blood_pressures ORDER BY id")] == [
        (2, 128, 78, "manual", None, None), (2, 131, 81, "apple_health", "k3", None)]
    assert conn.execute("SELECT name FROM api_tokens").fetchone()[0] == "Open WebUI"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # the foreign key, and what it does on delete
    for table in ("weights", "blood_pressures"):
        (fk,) = [r for r in conn.execute(f"PRAGMA foreign_key_list({table})") if r["from"] == "api_token_id"]
        assert (fk["table"], fk["to"], fk["on_delete"]) == ("api_tokens", "id", "SET NULL")
    # the partial indexes; the (user_id, date) index of step 18 is the one the same-reading check uses, and nothing replaces it
    for table, name in (("weights", "weights_user_token"), ("blood_pressures", "blood_pressures_user_token")):
        found = indexes(conn, table)
        unique, columns, sql = found[name]
        assert (unique, columns) == (False, ["user_id", "api_token_id"]) and "WHERE api_token_id IS NOT NULL" in sql
        assert found[f"{table}_user_date"][:2] == (False, ["user_id", "date"])
        assert not any(cols == ["user_id", "date", "time"] for _, cols, _ in found.values())
    m019.migrate(conn)  # a re-run changes nothing
    conn.commit()
    assert db.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0] == 3
    conn.close()


def test_a_fresh_database_has_the_column_too(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert "api_token_id" in db.table_columns(conn, "weights") and "api_token_id" in db.table_columns(conn, "blood_pressures")
    conn.close()


def token(conn: sqlite3.Connection, token_id: int, user_id: int, name: str, scopes: str = "body:write") -> None:
    conn.execute(
        """INSERT INTO api_tokens (id, user_id, name, token_hash, prefix, scopes, created_at, expires_at)
           VALUES (?, ?, ?, ?, 'khd_AbCd1234', ?, ?, ?)""",
        (token_id, user_id, name, f"{token_id:064d}", scopes, NOW, LATER),
    )


def test_purging_a_token_keeps_its_rows_and_clears_the_link(tmp_path):
    path = tmp_path / "kidney.db"
    build_v18_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    token(conn, 7, 2, "Morning weight")
    token(conn, 8, 2, "Evening cuff")
    conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, api_token_id, created_at, updated_at) "
                 "VALUES (2, '2026-10-22', '07:15', 69.99, 'morning', '', 'shortcut', 's1', 7, ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, api_token_id, created_at, updated_at) "
                 "VALUES (2, '2026-10-22', '07:16', 70.01, 'morning', '', 'shortcut', 's2', 8, ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, api_token_id, "
                 "created_at, updated_at) VALUES (2, '2026-10-22', '07:20', 122, 78, NULL, 'morning', '', 'shortcut', 's3', 7, ?, ?)", (NOW, NOW))
    conn.commit()
    conn.execute("DELETE FROM api_tokens WHERE id = 7")  # what the daily purge does 30 days after a token ended
    conn.commit()
    assert [tuple(r) for r in conn.execute("SELECT source_key, source, api_token_id FROM weights WHERE source = 'shortcut' ORDER BY id")] == [
        ("s1", "shortcut", None), ("s2", "shortcut", 8)]
    assert [tuple(r) for r in conn.execute("SELECT source_key, source, api_token_id FROM blood_pressures WHERE source = 'shortcut'")] == [
        ("s3", "shortcut", None)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_the_column_takes_only_a_token_that_exists(tmp_path):
    path = tmp_path / "kidney.db"
    build_v18_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO weights (user_id, date, kg, context, source, api_token_id, created_at, updated_at) "
                     "VALUES (2, '2026-10-22', 70, 'other', 'shortcut', 999, ?, ?)", (NOW, NOW))
    conn.rollback()
    conn.close()


def test_deleting_an_account_removes_its_rows_and_its_tokens_and_only_its_own(tmp_path):
    path = tmp_path / "kidney.db"
    build_v18_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    token(conn, 7, 2, "Sam's phone")
    token(conn, 8, 1, "Admin's phone")
    conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, api_token_id, created_at, updated_at) "
                 "VALUES (2, '2026-10-22', '07:15', 69.99, 'morning', '', 'shortcut', 's1', 7, ?, ?)", (NOW, NOW))
    conn.execute("INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, api_token_id, created_at, updated_at) "
                 "VALUES (1, '2026-10-22', '07:15', 80.0, 'morning', '', 'shortcut', 's2', 8, ?, ?)", (NOW, NOW))
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert [(r["user_id"], r["api_token_id"]) for r in conn.execute("SELECT user_id, api_token_id FROM weights WHERE source = 'shortcut'")] == [(1, 8)]
    assert [r["name"] for r in conn.execute("SELECT name FROM api_tokens")] == ["Admin's phone"]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
