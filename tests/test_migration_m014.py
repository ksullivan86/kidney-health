"""Schema step 14 (``app/migrations/m014_ai_consent_voice.py``): ``ai_consents`` accepts the purpose ``voice``.

Step 12 made the purpose ``CHECK (purpose IN ('text','photos','chat'))`` and SQLite cannot change a CHECK, so the table is
rebuilt. Every earlier row must survive, the key, the foreign keys and the index must be the same, a column that a
step in between added must survive, and the step must be safe to run twice.

The tests build the "before" database from ``steps()[:13]``, whatever step 13 does."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m014_ai_consent_voice as m014
from conftest import insert_users

NOW = "2026-10-15T08:00:00.000000Z"


def provider(conn: sqlite3.Connection, label: str = "Shared") -> int:
    cur = conn.execute(
        """INSERT INTO ai_providers (scope, owner_user_id, preset, label, base_url, model, created_at, updated_at)
           VALUES ('shared', NULL, 'openai', ?, 'https://api.openai.com/v1', 'm', ?, ?)""",
        (label, NOW, NOW),
    )
    return int(cur.lastrowid)


def consent(conn: sqlite3.Connection, user_id: int, provider_id: int, purpose: str, *, skip_preview: int = 0, host: str = "api.openai.com") -> None:
    conn.execute(
        """INSERT INTO ai_consents (user_id, provider_id, purpose, host, policy_version, skip_preview, created_at)
           VALUES (?, ?, ?, ?, 'p1', ?, ?)""",
        (user_id, provider_id, purpose, host, skip_preview, NOW),
    )


def build_v13_with_data(path) -> tuple[int, int]:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:13]) == list(range(1, 14))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    first, second = provider(conn, "One"), provider(conn, "Two")
    consent(conn, 1, first, "text")
    consent(conn, 1, first, "photos", skip_preview=1)
    consent(conn, 1, first, "chat")
    consent(conn, 2, second, "chat", skip_preview=1)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # the old table cannot hold a voice consent
        consent(conn, 2, second, "voice", host="stt.lan:8000")
    conn.rollback()
    assert db.get_schema_version(conn) == 13
    conn.close()
    return first, second


def test_step_14_follows_step_13():
    steps = migrations.steps()
    assert [s.version for s in steps][:14] == list(range(1, 15))
    step = steps[13]
    assert step.name == "m014_ai_consent_voice" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v13_database_upgrades_keeps_every_consent_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    first, second = build_v13_with_data(path)
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:14]) == [14]
    assert db.get_schema_version(conn) == 14
    rows = conn.execute("SELECT user_id, provider_id, purpose, host, policy_version, skip_preview, created_at "
                        "FROM ai_consents ORDER BY user_id, provider_id, purpose").fetchall()
    assert [tuple(r) for r in rows] == [
        (1, first, "chat", "api.openai.com", "p1", 0, NOW),
        (1, first, "photos", "api.openai.com", "p1", 1, NOW),
        (1, first, "text", "api.openai.com", "p1", 0, NOW),
        (2, second, "chat", "api.openai.com", "p1", 1, NOW),
    ]
    assert db.table_columns(conn, "ai_consents") == {"user_id", "provider_id", "purpose", "host", "policy_version",
                                                      "skip_preview", "created_at"}
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'ai_consents'")}
    assert names == {"ai_consents", "ai_consents_provider"}  # no leftover table, the index is back
    assert "ai_consents_new" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'ai_consents'").fetchone()[0]
    assert "WITHOUT ROWID" in sql and "'voice'" in sql and "'chat'" in sql
    m014.migrate(conn)  # a re-run changes nothing
    conn.commit()
    assert db.migrate(conn, migrations.steps()[:14]) == []
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 4
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_the_new_table_keeps_the_constraints_and_the_cascades(tmp_path):
    path = tmp_path / "kidney.db"
    first, second = build_v13_with_data(path)
    conn = db.connect(path)
    db.migrate(conn, migrations.steps()[:14])
    consent(conn, 2, second, "voice", host="stt.lan:8000")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # one row per person, provider and purpose
        consent(conn, 2, second, "voice")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # still only the four purposes
        consent(conn, 2, second, "music")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # skip_preview is a flag
        consent(conn, 2, first, "voice", skip_preview=2)
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # a provider that does not exist
        consent(conn, 2, 999, "voice")
    conn.rollback()
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (second,))  # a provider's consents go with it
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_consents WHERE provider_id = ?", (second,)).fetchone()[0] == 0
    conn.execute("DELETE FROM users WHERE id = 1")  # and so do a person's
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 0
    conn.close()


def test_a_column_added_by_a_step_in_between_is_kept(tmp_path):
    path = tmp_path / "kidney.db"
    first, _ = build_v13_with_data(path)
    conn = db.connect(path)
    conn.execute("ALTER TABLE ai_consents ADD COLUMN extra TEXT")
    conn.execute("UPDATE ai_consents SET extra = 'kept' WHERE purpose = 'photos'")
    conn.commit()
    db.migrate(conn, migrations.steps()[:14])
    assert db.table_columns(conn, "ai_consents") >= {"extra", "purpose", "host"}
    assert conn.execute("SELECT extra FROM ai_consents WHERE purpose = 'photos'").fetchone()[0] == "kept"
    consent(conn, 1, first, "voice", host="stt.lan:8000")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 5
    conn.close()


def test_an_unexpected_definition_stops_the_step_instead_of_guessing():
    with pytest.raises(RuntimeError, match="unexpected definition"):
        m014.widened_ddl("CREATE TABLE ai_consents (purpose TEXT)")
    renamed = 'CREATE TABLE "ai_consents" (purpose TEXT NOT NULL CHECK (purpose IN (\'text\',\'chat\')))'
    assert m014.widened_ddl(renamed) == "CREATE TABLE ai_consents_new (purpose TEXT NOT NULL CHECK (purpose IN ('text','chat','voice')))"


def test_a_fresh_database_accepts_voice_and_the_step_is_safe_without_the_table(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    assert db.migrate(conn)[-1] == len(migrations.steps())
    insert_users(conn, [(5, "kim")])
    consent(conn, 5, provider(conn), "voice", host="stt.lan:8000")
    conn.commit()
    # a database that somehow lacks the table gets it in its final shape
    conn.execute("DROP TABLE ai_consents")
    m014.migrate(conn)
    consent(conn, 5, conn.execute("SELECT id FROM ai_providers").fetchone()[0], "voice", host="stt.lan:8000")
    conn.commit()
    assert conn.execute("SELECT purpose FROM ai_consents").fetchone()[0] == "voice"
    conn.close()
