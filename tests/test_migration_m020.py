"""Schema step 20 (``app/migrations/m020_ai_env_slots.py``): ``ai_providers`` gains ``env_slot`` and ``upstream``, so two providers can
come from the environment (``AI_PROVIDER`` and ``AI_CLOUD_PROVIDER``).

On a populated schema-v19 database every row stays, the one locked row becomes the ``main`` slot, nothing has a company named, the
consents and usage that point at it survive, the old one-locked-row index is replaced by one locked row per slot, a re-run changes
nothing, and a fresh database has the same shape. The "before" database is built from ``steps()[:19]``, whatever later steps do."""
from __future__ import annotations

import sqlite3

import pytest

from app import db, migrations
from app.migrations import m020_ai_env_slots as m020
from conftest import insert_users

NOW = "2026-10-27T08:00:00.000000Z"


def provider(conn: sqlite3.Connection, label: str, *, locked: int = 0, scope: str = "shared", owner: int | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO ai_providers (scope, owner_user_id, preset, label, base_url, model, locked, created_at, updated_at)
           VALUES (?, ?, 'openai', ?, 'https://api.openai.com/v1', 'm', ?, ?, ?)""",
        (scope, owner, label, locked, NOW, NOW),
    )
    return int(cur.lastrowid)


def build_v19_with_data(path) -> dict[str, int]:
    conn = db.connect(path)
    assert db.migrate(conn, migrations.steps()[:19]) == list(range(1, 20))
    insert_users(conn, [(1, "admin"), (2, "sam")])
    ids = {"env": provider(conn, "Env", locked=1), "shared": provider(conn, "Shared"), "own": provider(conn, "Own", scope="user", owner=2)}
    conn.execute("INSERT INTO ai_consents VALUES (1, ?, 'text', 'api.openai.com', 'p1', 0, ?)", (ids["env"], NOW))
    conn.execute("INSERT INTO ai_consents VALUES (2, ?, 'photos', 'api.openai.com', 'p1', 1, ?)", (ids["shared"], NOW))
    conn.execute("INSERT INTO ai_usage VALUES (1, '2026-10-26', ?, 'shared', 3, 100, 20)", (ids["env"],))
    conn.commit()
    assert db.get_schema_version(conn) == 19
    assert not {"env_slot", "upstream"} & db.table_columns(conn, "ai_providers")
    with pytest.raises(sqlite3.IntegrityError):  # before this step a second locked row is refused
        provider(conn, "Second env", locked=1)
    conn.rollback()
    conn.close()
    return ids


def test_step_20_follows_step_19():
    steps = migrations.steps()
    assert [s.version for s in steps][:20] == list(range(1, 21))
    step = steps[19]
    assert step.name == "m020_ai_env_slots" and step.atomic and step.schema == "" and step.foreign_key_check


def test_populated_v19_database_upgrades_keeps_every_row_and_is_idempotent(tmp_path):
    path = tmp_path / "kidney.db"
    ids = build_v19_with_data(path)
    conn = db.connect(path)
    applied = db.migrate(conn)
    assert applied[0] == 20 and applied == list(range(20, db.SCHEMA_VERSION + 1))  # step 20, then any later step
    assert {"env_slot", "upstream"} <= db.table_columns(conn, "ai_providers")
    rows = {r["label"]: (r["id"], r["locked"], r["env_slot"], r["upstream"]) for r in conn.execute("SELECT * FROM ai_providers")}
    assert rows == {"Env": (ids["env"], 1, "main", None), "Shared": (ids["shared"], 0, None, None), "Own": (ids["own"], 0, None, None)}
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 2  # nobody is asked again
    assert conn.execute("SELECT requests FROM ai_usage").fetchone()[0] == 3
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    m020.migrate(conn)  # a re-run changes nothing
    conn.commit()
    assert db.migrate(conn) == []
    assert conn.execute("SELECT env_slot FROM ai_providers WHERE label = 'Env'").fetchone()[0] == "main"
    conn.close()


def indexes(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["name"]: r["sql"] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ai_providers'")}


def test_one_locked_row_per_slot_replaces_one_locked_row(tmp_path):
    path = tmp_path / "kidney.db"
    build_v19_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    found = indexes(conn)
    assert "ai_providers_one_env" not in found and "ai_providers_one_per_user" in found
    assert "UNIQUE" in found["ai_providers_one_per_env_slot"] and "WHERE locked = 1" in found["ai_providers_one_per_env_slot"]

    def locked(label: str, slot: str | None) -> None:
        conn.execute("INSERT INTO ai_providers (scope, preset, label, base_url, model, locked, env_slot, created_at, updated_at) "
                     "VALUES ('shared', 'litellm', ?, 'http://litellm:4000/v1', 'm', 1, ?, ?, ?)", (label, slot, NOW, NOW))

    locked("Cloud", "cloud")  # the second environment provider
    with pytest.raises(sqlite3.IntegrityError):
        locked("Another cloud", "cloud")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        locked("Another main", "main")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # a locked row without a slot counts as the main one
        locked("No slot", None)
    conn.rollback()
    provider(conn, "Admin one more")  # admin-made providers are not limited
    provider(conn, "Admin and more")
    with pytest.raises(sqlite3.IntegrityError):  # a slot must be main or cloud
        locked("Odd", "other")
    conn.rollback()
    conn.close()


def test_the_columns_take_only_what_the_code_writes(tmp_path):
    path = tmp_path / "kidney.db"
    assert db.init_db(path) == list(range(1, db.SCHEMA_VERSION + 1))
    conn = db.connect(path)
    assert {"env_slot", "upstream"} <= db.table_columns(conn, "ai_providers")
    pid = provider(conn, "Proxy")
    conn.execute("UPDATE ai_providers SET upstream = ? WHERE id = ?", ("Anthropic", pid))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE ai_providers SET upstream = ? WHERE id = ?", ("x" * 61, pid))
    conn.rollback()
    assert indexes(conn).keys() >= {"ai_providers_one_per_env_slot"}
    conn.close()


def test_deleting_the_environment_provider_still_removes_its_consents(tmp_path):
    path = tmp_path / "kidney.db"
    ids = build_v19_with_data(path)
    conn = db.connect(path)
    db.migrate(conn)
    conn.execute("DELETE FROM ai_providers WHERE id = ?", (ids["env"],))
    conn.commit()
    assert [r["provider_id"] for r in conn.execute("SELECT provider_id FROM ai_consents")] == [ids["shared"]]
    conn.close()
