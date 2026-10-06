"""Schema step 3 (note 07 §4.4): a v0.2 (and v0.1) database with data upgrades to accounts, everything
lands on user 1, the automatic ``kidney.db.pre-v3.bak`` is written once, and a fresh database gets
the same shape as an upgraded one."""
from __future__ import annotations

import json
import logging
import sqlite3
import stat
from pathlib import Path

import pytest

from app import db, migrations
from app.auth import bootstrap
from app.config import Settings
from app.main import create_app

from conftest import ADMIN_PASSWORD, DAY, TestClient, make_settings, setup_code_from_logs, signed_in_client
from test_migrations import build_v01_database
from test_migrations_framework import add_v02_data, build_with_v02_code

NOW = "2026-10-01T08:00:00.000000Z"


def build_v02_with_data(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    build_with_v02_code(path)
    add_v02_data(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO foods (id, name, source, fdc_id, serving_desc, serving_g, potassium_mg, created_at, updated_at) "
        "VALUES (6, 'USDA oats', 'usda', 424242, '40 g', 40, 140, ?, ?)",
        (NOW, NOW),
    )
    conn.execute(
        "INSERT INTO log_entries (date, meal, food_id, food_name, servings, status, created_at, updated_at) "
        "VALUES (?, 'breakfast', 6, 'USDA oats', 1, 'eaten', ?, ?)",
        (DAY, NOW, NOW),
    )
    conn.commit()
    conn.close()


def schema_shape(conn: sqlite3.Connection) -> dict[str, object]:
    objects = {(r[0], r[1]) for r in conn.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
    columns = {
        name: {(c[1], c[2], c[3], c[5]) for c in conn.execute(f"PRAGMA table_info({name})")}
        for kind, name in objects if kind == "table"
    }
    return {"objects": objects, "columns": columns}


def test_v02_database_upgrades_to_accounts_with_everything_on_user_one(tmp_path):
    path = tmp_path / "kidney.db"
    build_v02_with_data(path)
    assert db.init_db(path) == [3]
    conn = db.connect(path)
    assert db.get_schema_version(conn) == 3
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    user = conn.execute("SELECT id, role, status, username_norm FROM users").fetchall()
    assert [tuple(u) for u in user] == [(1, "admin", "pending_setup", "#setup")]
    assert {r[0] for r in conn.execute("SELECT user_id FROM log_entries")} == {1}
    assert conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0] == 2
    assert {r[0] for r in conn.execute("SELECT user_id FROM meal_templates")} == {1}
    assert conn.execute("SELECT owner_user_id FROM foods WHERE id = 5").fetchone()[0] == 1  # custom → user 1
    assert conn.execute("SELECT owner_user_id FROM foods WHERE id = 6").fetchone()[0] is None  # usda stays shared
    assert [tuple(r) for r in conn.execute("SELECT user_id, food_id FROM user_food_links")] == [(1, 6)]
    profile = conn.execute("SELECT * FROM user_profiles").fetchone()
    assert profile["user_id"] == 1 and profile["name"] == "Sam" and profile["weight_kg"] == 70
    assert json.loads(profile["dialysis_days_json"]) == [0, 2, 4]
    assert conn.execute("SELECT name FROM profile").fetchone()[0] == "Sam"  # the old table stays, frozen
    assert db.get_meta(conn, "accounts_migrated_at")
    conn.close()


def test_pre_v3_backup_is_written_once_private_and_restorable(tmp_path):
    path = tmp_path / "kidney.db"
    build_v02_with_data(path)
    db.init_db(path)
    backup = Path(f"{path}.pre-v3.bak")
    assert backup.exists() and stat.S_IMODE(backup.stat().st_mode) == 0o600
    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
    assert copy.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0] == 2
    assert copy.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'users'").fetchone()[0] == 0
    copy.close()
    mtime = backup.stat().st_mtime_ns
    assert db.init_db(path) == []
    assert backup.stat().st_mtime_ns == mtime
    fresh = tmp_path / "fresh.db"
    db.init_db(fresh)
    assert not Path(f"{fresh}.pre-v3.bak").exists()  # nothing to protect on a new database


def test_v01_database_upgrades_all_the_way(tmp_path):
    path = tmp_path / "data" / "kidney.db"
    build_v01_database(path)
    assert db.init_db(path) == [1, 2, 3]
    conn = db.connect(path)
    assert {r[0] for r in conn.execute("SELECT user_id FROM log_entries")} == {1}
    assert conn.execute("SELECT owner_user_id FROM foods WHERE source = 'custom'").fetchone()[0] == 1
    assert tuple(conn.execute("SELECT name, ckd_stage FROM user_profiles WHERE user_id = 1").fetchone()) == ("Sam", "4")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    assert Path(f"{path}.pre-v3.bak").exists()


def test_fresh_and_upgraded_databases_have_the_same_shape(tmp_path):
    fresh, upgraded = tmp_path / "fresh.db", tmp_path / "old.db"
    db.init_db(fresh)
    build_v02_with_data(upgraded)
    db.init_db(upgraded)
    a, b = db.connect(fresh), db.connect(upgraded)
    shape_a, shape_b = schema_shape(a), schema_shape(b)
    assert shape_a["objects"] == shape_b["objects"]
    assert shape_a["columns"] == shape_b["columns"]
    a.close()
    b.close()


def test_triggers_refuse_rows_without_an_owner(tmp_path):
    path = tmp_path / "kidney.db"
    build_v02_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    with pytest.raises(sqlite3.IntegrityError, match="log_entries.user_id is required"):
        conn.execute(
            "INSERT INTO log_entries (date, meal, food_id, food_name, servings, created_at, updated_at) VALUES (?, 'lunch', 5, 'x', 1, ?, ?)",
            (DAY, NOW, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError, match="meal_templates.user_id is required"):
        conn.execute("INSERT INTO meal_templates (name, items_json, created_at, updated_at) VALUES ('x', '[]', ?, ?)", (NOW, NOW))
    with pytest.raises(sqlite3.IntegrityError, match="meal_templates.user_id is required"):
        conn.execute("UPDATE meal_templates SET user_id = NULL")
    with pytest.raises(sqlite3.IntegrityError, match="owner_user_id is required"):
        conn.execute("UPDATE foods SET owner_user_id = NULL WHERE id = 5")
    conn.execute("INSERT INTO audit_log (at, action) VALUES (?, 'login.failed')", (NOW,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET action = 'x'")
    with pytest.raises(sqlite3.IntegrityError):  # one shared key per provider
        for _ in range(2):
            conn.execute(
                "INSERT INTO secrets (scope, provider, ciphertext, key_id, created_at, updated_at) VALUES ('shared', 'usda', x'00', 'k', ?, ?)",
                (NOW, NOW),
            )
    conn.close()


def test_deleting_user_one_cascades_and_ids_are_not_reused(tmp_path):
    path = tmp_path / "kidney.db"
    build_v02_with_data(path)
    db.init_db(path)
    conn = db.connect(path)
    conn.execute("UPDATE users SET status = 'active', username = 'a', username_norm = 'a' WHERE id = 1")
    conn.execute("INSERT INTO users (username, username_norm, created_at, updated_at) VALUES ('b', 'b', ?, ?)", (NOW, NOW))
    conn.execute("DELETE FROM users WHERE id = 1")
    for table in ("log_entries", "meal_templates", "user_profiles", "user_food_links"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'custom'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM foods WHERE source = 'usda'").fetchone()[0] == 1  # shared row stays
    conn.execute("INSERT INTO users (username, username_norm, created_at, updated_at) VALUES ('c', 'c', ?, ?)", (NOW, NOW))
    assert conn.execute("SELECT MAX(id) FROM users").fetchone()[0] == 3
    conn.close()


def test_upgraded_data_belongs_to_whoever_sets_up_the_server(tmp_path, foods_json, caplog):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    build_v02_with_data(settings.db_path)
    with caplog.at_level(logging.WARNING), TestClient(create_app(settings)) as c:
        assert "kidney.db.pre-v3.bak" in caplog.text
        code = setup_code_from_logs(caplog)
        r = c.post("/api/auth/setup", json={"code": code, "username": "sam", "password": ADMIN_PASSWORD})
        assert r.status_code == 200 and r.json()["user"]["id"] == 1
        day = c.get("/api/log", params={"date": DAY}).json()
        assert {e["food_name"] for e in day["entries"]} == {"Rice", "USDA oats"}
        assert c.get("/api/profile").json()["name"] == "Sam"
        assert [m["name"] for m in c.get("/api/meals").json()["meals"]] == ["Usual"]
        assert any(f["name"] == "USDA oats" for f in c.get("/api/foods", params={"q": "oats"}).json()["foods"])


def test_upgrade_with_admin_password_env(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json)
    build_v02_with_data(settings.db_path)
    with signed_in_client(settings) as c:
        assert len(c.get("/api/log", params={"date": DAY}).json()["entries"]) == 2


def test_pre_v3_backup_is_deleted_after_thirty_days(tmp_path, fake_clock):
    path = tmp_path / "kidney.db"
    build_v02_with_data(path)
    db.init_db(path)
    backup = Path(f"{path}.pre-v3.bak")
    conn = db.connect(path)
    fake_clock.advance(days=29)
    assert bootstrap.expire_pre_v3_backup(conn) is False and backup.exists()
    fake_clock.advance(days=2)
    assert bootstrap.expire_pre_v3_backup(conn) is True and not backup.exists()
    conn.close()


def test_steps_list_and_numbering():
    steps = migrations.steps()
    assert [s.version for s in steps][:3] == [1, 2, 3]
    m3 = steps[2]
    assert m3.name == "m003_accounts" and m3.backup_before and m3.foreign_key_check and m3.atomic and m3.schema == ""
