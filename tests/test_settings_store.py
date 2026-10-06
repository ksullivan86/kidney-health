"""Settings registry and store (note 07 §4.11): precedence, env locks, validation, cache."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from app import db, settings_registry
from app.config import ConfigError
from app.settings_registry import SettingDef
from app.settings_store import (
    InvalidSettingValue,
    SettingLocked,
    SettingNotEditable,
    SettingsStore,
    SettingsUnavailable,
    create_settings_tables,
)

USERS_STUB = "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)"


def make_db(path: str | Path = ":memory:") -> sqlite3.Connection:
    """A migrated database plus the schema-v3 settings tables (as m003 will create them)."""
    conn = db.connect(path)
    db.migrate(conn)
    conn.execute(USERS_STUB)
    create_settings_tables(conn)
    conn.executemany("INSERT INTO users (id, username) VALUES (?, ?)", [(1, "admin"), (2, "sam")])
    conn.commit()
    return conn


class Guidance(BaseModel):
    enabled: bool = True
    carb_tolerance_g: int = Field(default=10, ge=0, le=50)


CUSTOM = {
    d.key: d
    for d in (
        SettingDef("instance.name", Annotated[str, Field(min_length=1, max_length=80)], "Kidney Health", "instance", env="INSTANCE_NAME"),
        SettingDef("registration.mode", Literal["invite", "closed", "open"], "invite", "instance", env="REGISTRATION_MODE"),
        SettingDef("ui.theme", Literal["system", "light", "dark"], "system", "user_default"),
        SettingDef("guidance", Guidance, Guidance(), "user"),
        SettingDef("limits.daily", Annotated[int, Field(ge=0)], 200, "instance", env="DAILY_LIMIT"),
    )
}


@pytest.fixture
def conn():
    c = make_db()
    yield c
    c.close()


def test_registry_has_note_07_keys():
    keys = {d.key: d for d in settings_registry.all_settings()}
    expected = {
        "instance.name": ("instance", "INSTANCE_NAME", "Kidney Health"),
        "registration.mode": ("instance", "REGISTRATION_MODE", "invite"),
        "registration.invite_ttl_days": ("instance", None, 7),
        "audit.retention_days": ("instance", "AUDIT_RETENTION_DAYS", 365),
        "providers.usda.shared_enabled": ("instance", None, True),
        "providers.usda.user_keys_allowed": ("instance", None, True),
        "providers.usda.daily_limit_per_user": ("instance", "USDA_SHARED_DAILY_LIMIT", 200),
        "ui.theme": ("user_default", None, "system"),
    }
    for key, (scope, env, default) in expected.items():
        d = keys[key]
        assert (d.scope, d.env, d.default) == (scope, env, default), key


def test_register_rejects_duplicates_and_bad_defaults():
    with pytest.raises(ValueError, match="already registered"):
        settings_registry.register(SettingDef("instance.name", str, "Other", "instance"))
    with pytest.raises(ValueError, match="env lock"):
        settings_registry.register(SettingDef("test.other_name", str, "x", "instance", env="INSTANCE_NAME"))
    with pytest.raises(ValidationError):
        SettingDef("test.bad_default", Annotated[int, Field(ge=1)], 0, "instance")
    with pytest.raises(ValueError, match="scope"):
        SettingDef("test.bad_scope", int, 1, "global")  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        settings_registry.get("no.such.key")


def test_precedence_env_user_instance_default(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    eff = store.effective(conn, "ui.theme", 2)
    assert (eff.value, eff.source, eff.locked) == ("system", "default", False)

    store.set_instance(conn, "ui.theme", "dark", updated_by=1)
    assert (store.effective(conn, "ui.theme", 2).value, store.effective(conn, "ui.theme", 2).source) == ("dark", "instance")
    assert store.effective(conn, "ui.theme").source == "instance"

    store.set_user(conn, 2, "ui.theme", "light")
    assert (store.get(conn, "ui.theme", 2), store.effective(conn, "ui.theme", 2).source) == ("light", "user")
    assert store.get(conn, "ui.theme", 1) == "dark"  # another person still inherits
    assert store.get(conn, "ui.theme") == "dark"

    store.set_user(conn, 2, "ui.theme", None)  # null = back to inherited
    assert store.effective(conn, "ui.theme", 2).source == "instance"
    store.set_instance(conn, "ui.theme", None)
    assert store.effective(conn, "ui.theme", 2).source == "default"


def test_env_lock_beats_user_and_instance(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    store.set_instance(conn, "registration.mode", "closed")
    store.set_instance(conn, "limits.daily", 50)
    locked = SettingsStore(env={"REGISTRATION_MODE": "open", "DAILY_LIMIT": " 0 "}, defs=CUSTOM)
    eff = locked.effective(conn, "registration.mode")
    assert (eff.value, eff.source, eff.locked, eff.env) == ("open", "env", True, "REGISTRATION_MODE")
    assert locked.get(conn, "limits.daily") == 0
    with pytest.raises(SettingLocked, match="set by the server \\(REGISTRATION_MODE\\)"):
        locked.set_instance(conn, "registration.mode", "invite")
    assert locked.admin_view(conn)["registration.mode"] == {
        "value": "open", "source": "env", "locked_by_env": "REGISTRATION_MODE", "scope": "instance",
    }
    assert sorted(locked.validate_env_locks()) == ["limits.daily", "registration.mode"]


def test_invalid_env_lock_is_a_config_error(conn):
    store = SettingsStore(env={"REGISTRATION_MODE": "everyone"}, defs=CUSTOM)
    with pytest.raises(ConfigError, match="REGISTRATION_MODE \\(setting registration.mode\\) is invalid"):
        store.validate_env_locks()
    with pytest.raises(ConfigError):
        SettingsStore(env={"DAILY_LIMIT": "-3"}, defs=CUSTOM).validate_env_locks()


def test_object_settings_and_env_json(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    eff = store.set_user(conn, 2, "guidance", {"enabled": False, "carb_tolerance_g": 20})
    assert eff.value == Guidance(enabled=False, carb_tolerance_g=20)
    assert store.user_view(conn, 2)["guidance"] == {"value": {"enabled": False, "carb_tolerance_g": 20}, "source": "user", "editable": True}
    with pytest.raises(InvalidSettingValue):
        store.set_user(conn, 2, "guidance", {"carb_tolerance_g": 999})


def test_validation_on_write_never_echoes_the_value(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    with pytest.raises(InvalidSettingValue) as info:
        store.set_instance(conn, "registration.mode", "secret-ish-value")
    assert "secret-ish-value" not in str(info.value)
    with pytest.raises(InvalidSettingValue):
        store.set_instance(conn, "instance.name", "")
    with pytest.raises(KeyError):
        store.set_instance(conn, "no.such", 1)


def test_scope_rules(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    with pytest.raises(SettingNotEditable):
        store.set_user(conn, 2, "registration.mode", "open")  # users cannot change instance keys
    with pytest.raises(SettingNotEditable):
        store.set_instance(conn, "guidance", {"enabled": False})  # no admin default for personal keys
    assert set(store.user_view(conn, 2)) == {"ui.theme", "guidance"}
    assert set(store.admin_view(conn)) == {"instance.name", "registration.mode", "ui.theme", "limits.daily"}


def test_invalid_stored_value_falls_back_with_a_warning(conn, caplog):
    store = SettingsStore(env={}, defs=CUSTOM)
    now = db.utcnow()
    conn.execute("INSERT INTO instance_settings (key, value_json, updated_at) VALUES ('ui.theme', '\"dark\"', ?)", (now,))
    conn.execute("INSERT INTO user_settings (user_id, key, value_json, updated_at) VALUES (2, 'ui.theme', '\"purple\"', ?)", (now,))
    conn.execute("INSERT INTO instance_settings (key, value_json, updated_at) VALUES ('limits.daily', 'not json', ?)", (now,))
    with caplog.at_level(logging.WARNING, logger="kidney_health.settings"):
        eff = store.effective(conn, "ui.theme", 2)
        assert (eff.value, eff.source) == ("dark", "instance")  # the bad personal value is skipped
        assert store.effective(conn, "limits.daily").source == "default"
    assert "invalid stored value for setting ui.theme" in caplog.text
    assert "purple" not in caplog.text


def test_update_user_and_instance_validate_everything_first(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    with pytest.raises(InvalidSettingValue):
        store.update_user(conn, 2, {"ui.theme": "dark", "guidance": {"carb_tolerance_g": -1}})
    assert store.effective(conn, "ui.theme", 2).source == "default"  # nothing written
    view = store.update_user(conn, 2, {"ui.theme": "dark"})
    assert view["ui.theme"]["value"] == "dark"
    changes = store.update_instance(conn, {"instance.name": "Sam's kitchen", "registration.mode": "invite"}, updated_by=1)
    assert changes == [("instance.name", "Kidney Health", "Sam's kitchen")]  # unchanged values are not reported
    row = conn.execute("SELECT updated_by FROM instance_settings WHERE key = 'instance.name'").fetchone()
    assert row[0] == 1


def test_missing_tables_read_defaults_and_refuse_writes(tmp_path):
    conn = db.connect(":memory:")
    db.migrate(conn)  # schema v2: no settings tables yet
    store = SettingsStore(env={}, defs=CUSTOM)
    assert store.effective(conn, "ui.theme", 1).source == "default"
    assert SettingsStore(env={"REGISTRATION_MODE": "closed"}, defs=CUSTOM).get(conn, "registration.mode") == "closed"
    with pytest.raises(SettingsUnavailable):
        store.set_instance(conn, "ui.theme", "dark")
    conn.close()


def test_store_functions_do_not_commit(conn):
    store = SettingsStore(env={}, defs=CUSTOM)
    store.set_instance(conn, "instance.name", "Before rollback")
    assert conn.in_transaction
    conn.rollback()
    assert store.effective(conn, "instance.name").source == "default"


def test_cache_sees_writes_from_another_process(tmp_path):
    path = tmp_path / "kidney.db"
    conn = make_db(path)
    server = SettingsStore(env={}, defs=CUSTOM)
    assert server.get(conn, "instance.name") == "Kidney Health"
    snap = server._cache[str(path)]
    assert server.get(conn, "instance.name") == "Kidney Health" and server._cache[str(path)] is snap  # cached

    cli = SettingsStore(env={}, defs=CUSTOM)  # e.g. python -m app.admin settings set
    other = db.connect(path)
    cli.set_instance(other, "instance.name", "From the CLI")
    other.commit()
    other.close()
    assert server.get(conn, "instance.name") == "From the CLI"

    # a rolled-back write leaves no stale cache behind
    server.set_instance(conn, "instance.name", "Rolled back")
    conn.rollback()
    assert server.get(conn, "instance.name") == "From the CLI"
    conn.close()


def test_default_registry_store(conn):
    store = SettingsStore(env={})
    assert store.get(conn, "providers.usda.daily_limit_per_user") == 200
    store.set_instance(conn, "providers.usda.daily_limit_per_user", 0)
    assert store.get(conn, "providers.usda.daily_limit_per_user") == 0
    with pytest.raises(InvalidSettingValue):
        store.set_instance(conn, "providers.usda.daily_limit_per_user", -1)
    assert SettingsStore(env={"USDA_SHARED_DAILY_LIMIT": "25"}).get(conn, "providers.usda.daily_limit_per_user") == 25
    assert SettingsStore(env={"INSTANCE_NAME": "  Clinic  "}).get(conn, "instance.name") == "Clinic"


def test_settings_tables_ddl_is_idempotent_and_cascades(conn):
    create_settings_tables(conn)
    store = SettingsStore(env={}, defs=CUSTOM)
    store.set_user(conn, 2, "ui.theme", "dark")
    store.set_instance(conn, "ui.theme", "light", updated_by=2)
    conn.commit()
    conn.execute("DELETE FROM users WHERE id = 2")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM user_settings").fetchone()[0] == 0
    assert conn.execute("SELECT updated_by FROM instance_settings").fetchone()[0] is None
