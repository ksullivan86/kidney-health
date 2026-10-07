"""Schema step 6 (``app/migrations/m006_ai.py``; note 04 R4, §9 A6/A8) applied to a populated
schema-v5 database: AI providers, consents, usage and audit tables, their constraints and the
``ON DELETE CASCADE`` from ``users`` that makes account deletion erase AI data."""
from __future__ import annotations

import sqlite3

import pytest
from app import db, migrations
from app.migrations import m006_ai as m006
from conftest import insert_users

NOW = "2026-10-06T08:00:00.000000Z"
AI_TABLES = ("ai_providers", "ai_consents", "ai_usage", "ai_audit")


def build_v5_with_data(path) -> None:
    """A database exactly at schema v5 with two people, a custom food, entries and a preference."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:5]) == [1, 2, 3, 4, 5]
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute(
        """INSERT INTO foods (id, name, source, serving_desc, serving_g, owner_user_id, created_at, updated_at)
           VALUES (1, 'Rice', 'custom', '1 cup', 158, 1, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute(
        """INSERT INTO log_entries (user_id, date, meal, food_id, food_name, servings, purpose, created_at, updated_at)
           VALUES (1, '2026-10-05', 'lunch', 1, 'Rice', 1, NULL, ?, ?)""",
        (NOW, NOW),
    )
    conn.execute("INSERT INTO food_preferences VALUES (2, 1, 'not_for_me', ?)", (NOW,))
    conn.execute("INSERT INTO user_settings (user_id, key, value_json, updated_at) VALUES (1, 'ui.theme', '\"dark\"', ?)", (NOW,))
    conn.commit()
    assert db.get_schema_version(conn) == 5
    assert not any(db.table_exists(conn, t) for t in AI_TABLES)
    conn.close()


def provider(conn: sqlite3.Connection, *, scope: str = "shared", owner: int | None = None, locked: int = 0) -> int:
    cur = conn.execute(
        """INSERT INTO ai_providers (scope, owner_user_id, preset, label, base_url, model, locked, created_at, updated_at)
           VALUES (?, ?, 'openai', 'OpenAI', 'https://api.openai.com/v1', 'gpt-6-luna', ?, ?, ?)""",
        (scope, owner, locked, NOW, NOW),
    )
    return int(cur.lastrowid)


def test_step_6_follows_the_guidance_step():
    steps = migrations.steps()
    assert [s.version for s in steps][:6] == [1, 2, 3, 4, 5, 6]
    step = steps[5]
    assert step.name == "m006_ai" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v5_database_upgrades_and_keeps_every_row(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v5_with_data(path)
    applied = db.init_db(path)
    assert applied[0] == 6
    conn = db.connect(path)
    for table in AI_TABLES:
        assert db.table_exists(conn, table), table
    assert {"api_key_enc", "api_key_hint", "probe_json", "disabled_reason", "locked", "context_tokens"} <= db.table_columns(conn, "ai_providers")
    assert {"request_json", "response_text", "verdict_json", "destination_host", "prompt_version"} <= db.table_columns(conn, "ai_audit")
    # nothing that existed before is touched
    assert conn.execute("SELECT food_name FROM log_entries").fetchone()[0] == "Rice"
    assert conn.execute("SELECT COUNT(*) FROM food_preferences").fetchone()[0] == 1
    assert conn.execute("SELECT value_json FROM user_settings WHERE key = 'ui.theme'").fetchone()[0] == '"dark"'
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_step_6_is_idempotent(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v5_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    pid = provider(conn)
    conn.commit()
    m006.migrate(conn)  # a re-run (partly upgraded database) changes nothing
    conn.commit()
    assert conn.execute("SELECT id FROM ai_providers").fetchall()[0][0] == pid
    conn.close()
    assert db.init_db(path) == []


def test_provider_scope_owner_and_lock_constraints(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v5_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    provider(conn, scope="shared")
    provider(conn, scope="user", owner=2)
    with pytest.raises(sqlite3.IntegrityError):  # a shared provider has no owner
        provider(conn, scope="shared", owner=1)
    with pytest.raises(sqlite3.IntegrityError):  # a personal provider needs one
        provider(conn, scope="user", owner=None)
    with pytest.raises(sqlite3.IntegrityError):  # one personal provider per person
        provider(conn, scope="user", owner=2)
    with pytest.raises(sqlite3.IntegrityError):  # only shared providers can be the env-locked one
        provider(conn, scope="user", owner=1, locked=1)
    provider(conn, scope="shared", locked=1)
    with pytest.raises(sqlite3.IntegrityError):  # only one env provider
        provider(conn, scope="shared", locked=1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO ai_providers (scope, preset, label, base_url, model, structured, created_at, updated_at)
               VALUES ('shared', 'openai', 'x', 'https://api.openai.com/v1', 'm', 'yaml', ?, ?)""",
            (NOW, NOW),
        )
    conn.close()


def test_provider_ids_are_never_reused(tmp_path):
    """Usage and audit rows keep a provider id after the provider is removed; a new provider must not inherit them."""
    path = tmp_path / "data" / "kidney.db"
    build_v5_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    first = provider(conn)
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (first,))
    assert provider(conn) > first
    conn.close()


def test_deleting_an_account_erases_its_ai_data(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v5_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    shared = provider(conn)
    own = provider(conn, scope="user", owner=2)
    for uid, pid in ((1, shared), (2, shared), (2, own)):
        conn.execute("INSERT INTO ai_consents VALUES (?, ?, 'text', 'api.openai.com', '2026-10-05.1', 0, ?)", (uid, pid, NOW))
        conn.execute("INSERT INTO ai_usage VALUES (?, '2026-10-06', ?, 'shared', 3, 100, 20)", (uid, pid))
        conn.execute(
            """INSERT INTO ai_audit (user_id, created_at, feature, provider_id, destination_host, prompt_version,
                                     request_json, verdict_json, status) VALUES (?, ?, 'next_meal', ?, 'api.openai.com', 'v', '{}', '{}', 'ok')""",
            (uid, NOW, pid),
        )
    conn.commit()
    conn.execute("DELETE FROM log_entries WHERE user_id = 2")
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    for table, column in (("ai_consents", "user_id"), ("ai_usage", "user_id"), ("ai_audit", "user_id"), ("ai_providers", "owner_user_id")):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = 2").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM ai_audit WHERE user_id = 1").fetchone()[0] == 1
    # removing a provider drops the consents given for it (everyone is asked again)
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (shared,))
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_consent_purpose_is_checked(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v5_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    pid = provider(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO ai_consents VALUES (1, ?, 'everything', 'h', 'v', 0, ?)", (pid, NOW))
    with pytest.raises(sqlite3.IntegrityError):  # a consent for a provider that does not exist
        conn.execute("INSERT INTO ai_consents VALUES (1, 9999, 'text', 'h', 'v', 0, ?)", (NOW,))
    conn.close()
