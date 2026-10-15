"""Schema step 12 (``app/migrations/m012_ai_consent_chat.py``): ``ai_consents`` accepts the purpose ``chat``.

Step 6 made the purpose ``CHECK (purpose IN ('text','photos'))`` and SQLite cannot change a CHECK, so the table is
rebuilt. Every earlier row must survive, the key, the foreign keys and the index must be the same, and the step must
be safe to run twice."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m012_ai_consent_chat as m012
from conftest import insert_users

NOW = "2026-10-15T08:00:00.000000Z"


def provider(conn: sqlite3.Connection, label: str = "Shared") -> int:
    cur = conn.execute(
        """INSERT INTO ai_providers (scope, owner_user_id, preset, label, base_url, model, created_at, updated_at)
           VALUES ('shared', NULL, 'openai', ?, 'https://api.openai.com/v1', 'm', ?, ?)""",
        (label, NOW, NOW),
    )
    return int(cur.lastrowid)


def consent(conn: sqlite3.Connection, user_id: int, provider_id: int, purpose: str, *, skip_preview: int = 0) -> None:
    conn.execute(
        """INSERT INTO ai_consents (user_id, provider_id, purpose, host, policy_version, skip_preview, created_at)
           VALUES (?, ?, ?, 'api.openai.com', 'p1', ?, ?)""",
        (user_id, provider_id, purpose, skip_preview, NOW),
    )


def build_v11_with_data(path) -> tuple[int, int]:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:11]) == list(range(1, 12))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    first, second = provider(conn, "One"), provider(conn, "Two")
    consent(conn, 1, first, "text")
    consent(conn, 1, first, "photos", skip_preview=1)
    consent(conn, 2, second, "text")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # the old table cannot hold a chat consent
        consent(conn, 2, second, "chat")
    conn.rollback()
    assert db.get_schema_version(conn) == 11
    conn.close()
    return first, second


def test_step_12_follows_step_11():
    steps = migrations.steps()
    assert [s.version for s in steps][:12] == list(range(1, 13))
    step = steps[11]
    assert step.name == "m012_ai_consent_chat" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v11_database_upgrades_keeps_every_consent_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    first, second = build_v11_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 12 and applied == list(range(12, db.SCHEMA_VERSION + 1))  # step 12, then any later step
    assert db.get_schema_version(conn) == db.SCHEMA_VERSION
    rows = conn.execute("SELECT user_id, provider_id, purpose, host, policy_version, skip_preview, created_at "
                        "FROM ai_consents ORDER BY user_id, provider_id, purpose").fetchall()
    assert [tuple(r) for r in rows] == [
        (1, first, "photos", "api.openai.com", "p1", 1, NOW),
        (1, first, "text", "api.openai.com", "p1", 0, NOW),
        (2, second, "text", "api.openai.com", "p1", 0, NOW),
    ]
    assert db.table_columns(conn, "ai_consents") == {"user_id", "provider_id", "purpose", "host", "policy_version",
                                                      "skip_preview", "created_at"}
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'ai_consents'")}
    assert names == {"ai_consents", "ai_consents_provider"}  # no leftover table, the index is back
    assert "ai_consents_new" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'ai_consents'").fetchone()[0]
    assert "WITHOUT ROWID" in sql and "'chat'" in sql
    m012.migrate(conn)  # a re-run changes nothing
    conn.commit()
    assert db.migrate(conn, migrations.steps()[:12]) == []
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 3
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_the_new_table_keeps_the_constraints_and_the_cascades(tmp_path):
    path = tmp_path / "kidney.db"
    first, second = build_v11_with_data(path)
    conn = db.connect(path)
    db.migrate(conn, migrations.steps()[:12])
    consent(conn, 2, second, "chat")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):  # one row per person, provider and purpose
        consent(conn, 2, second, "chat")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # still only the three purposes
        consent(conn, 2, second, "voice")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # skip_preview is a flag
        consent(conn, 2, first, "chat", skip_preview=2)
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # a provider that does not exist
        consent(conn, 2, 999, "chat")
    conn.rollback()
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (second,))  # a provider's consents go with it
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_consents WHERE provider_id = ?", (second,)).fetchone()[0] == 0
    conn.execute("DELETE FROM users WHERE id = 1")  # and so do a person's
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 0
    conn.close()


def test_a_fresh_database_accepts_chat_and_the_step_is_safe_without_the_table(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    assert db.migrate(conn)[-1] == db.SCHEMA_VERSION
    insert_users(conn, [(5, "kim")])
    consent(conn, 5, provider(conn), "chat")
    conn.commit()
    # a database that somehow lacks the table gets it in its final shape
    conn.execute("DROP TABLE ai_consents")
    m012.migrate(conn)
    consent(conn, 5, conn.execute("SELECT id FROM ai_providers").fetchone()[0], "chat")
    conn.commit()
    assert conn.execute("SELECT purpose FROM ai_consents").fetchone()[0] == "chat"
    conn.close()
