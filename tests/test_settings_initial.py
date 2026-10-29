"""First values from the environment (design note 20): ``SETTINGS_INITIAL_ONLY`` names the setting variables that the
server writes once, on the first start that sees them, and that stay changeable in the app afterwards."""
from __future__ import annotations

import io
import json

import pytest

from app import admin, db, settings_registry
from app.config import ConfigError
from app.main import _initial_settings
from app.settings_store import INITIAL_META_PREFIX, SettingsStore
from conftest import insert_users

# The two settings that name a row of the AI providers table: an environment provider gets its role from AI_PROVIDER_ROLE
# and AI_CLOUD_PROVIDER instead (app/ai/routing.py), so a variable for the id would have nothing to point at.
NO_VARIABLE = {"ai.route.local_provider", "ai.route.cloud_provider"}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "kidney.db"
    db.init_db(path)
    c = db.connect(path)
    insert_users(c, [(1, "admin"), (2, "sam")])
    c.commit()
    yield c
    c.close()


def store(**env: str) -> SettingsStore:
    return SettingsStore(env=env)


def audit_rows(conn) -> list[dict]:
    rows = conn.execute("SELECT actor_user_id, target_id, details_json FROM audit_log WHERE action = 'settings.changed' ORDER BY id").fetchall()
    return [{"actor": r[0], "key": r[1], **json.loads(r[2])} for r in rows]


def test_every_server_setting_can_be_set_from_the_environment():
    missing = [d.key for d in settings_registry.all_settings() if d.admin_editable and not d.env and d.key not in NO_VARIABLE]
    assert missing == []
    names = [d.env for d in settings_registry.all_settings() if d.env]
    assert len(names) == len(set(names)) and "SETTINGS_INITIAL_ONLY" not in names


def test_a_listed_variable_is_a_first_value_and_the_others_stay_locks(conn):
    s = store(SETTINGS_INITIAL_ONLY="SHARING_ENABLED, UI_THEME", SHARING_ENABLED="true", UI_THEME="dark", PUSH_ENABLED="true")
    assert s.validate_env_locks() == ["push.enabled"]
    assert s.initial_keys() == ["sharing.enabled", "ui.theme"]
    view = s.admin_view(conn)
    assert view["sharing.enabled"] == {"value": False, "source": "default", "locked_by_env": None, "scope": "instance"}
    assert view["push.enabled"]["locked_by_env"] == "PUSH_ENABLED"
    s.set_instance(conn, "sharing.enabled", False)  # a first value never blocks the admin


def test_a_star_makes_every_variable_a_first_value():
    s = store(SETTINGS_INITIAL_ONLY="*", OFF_ENABLED="true", INSTANCE_NAME="Our log")
    assert s.validate_env_locks() == []
    assert s.initial_keys() == ["food.off_enabled", "instance.name"]


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"SETTINGS_INITIAL_ONLY": "SHARING_ENABLED,AUTH_MODE,NOPE"}, "not the variable of a setting: AUTH_MODE, NOPE"),
        ({"SETTINGS_INITIAL_ONLY": "*,SHARING_ENABLED"}, "use \\* alone"),
        ({"SETTINGS_INITIAL_ONLY": "SHARING_ENABLED", "SHARING_ENABLED": "maybe"}, "SHARING_ENABLED \\(setting sharing.enabled\\) is invalid"),
    ],
)
def test_a_mistake_stops_the_start(env, message):
    with pytest.raises(ConfigError, match=message):
        store(**env).validate_env_locks()


def test_first_values_are_written_once_and_the_app_can_change_them_after(conn):
    env = {"SETTINGS_INITIAL_ONLY": "SHARING_ENABLED,INVITE_TTL_DAYS,UI_THEME", "SHARING_ENABLED": "true", "INVITE_TTL_DAYS": "3",
           "UI_THEME": "dark"}
    s = store(**env)
    _initial_settings(conn, s)
    assert [s.get(conn, k) for k in ("sharing.enabled", "registration.invite_ttl_days", "ui.theme")] == [True, 3, "dark"]
    assert s.get(conn, "ui.theme", 2) == "dark"  # the default for everyone; each person may still choose their own
    s.set_user(conn, 2, "ui.theme", "light")
    assert s.get(conn, "ui.theme", 2) == "light"
    assert audit_rows(conn) == [
        {"actor": None, "key": "registration.invite_ttl_days", "old": 7, "new": 3, "env": "INVITE_TTL_DAYS"},
        {"actor": None, "key": "sharing.enabled", "old": False, "new": True, "env": "SHARING_ENABLED"},
        {"actor": None, "key": "ui.theme", "old": "system", "new": "dark", "env": "UI_THEME"},
    ]
    # The admin turns sharing off and puts the invite lifetime back to its default; a restart keeps both.
    s.set_instance(conn, "sharing.enabled", False)
    s.set_instance(conn, "registration.invite_ttl_days", None)
    conn.commit()
    again = store(**env)
    _initial_settings(conn, again)
    assert again.get(conn, "sharing.enabled") is False and again.get(conn, "registration.invite_ttl_days") == 7
    assert len(audit_rows(conn)) == 3


def test_a_value_already_chosen_in_the_app_is_kept(conn):
    s = store()
    s.set_instance(conn, "instance.name", "Family log")
    conn.commit()
    later = store(SETTINGS_INITIAL_ONLY="INSTANCE_NAME,AUDIT_RETENTION_DAYS", INSTANCE_NAME="From env", AUDIT_RETENTION_DAYS="90")
    _initial_settings(conn, later)
    assert later.get(conn, "instance.name") == "Family log" and later.get(conn, "audit.retention_days") == 90
    marked = {r[0] for r in conn.execute("SELECT key FROM meta WHERE key LIKE ?", (INITIAL_META_PREFIX + "%",))}
    assert marked == {INITIAL_META_PREFIX + "instance.name", INITIAL_META_PREFIX + "audit.retention_days"}


def test_a_variable_added_to_the_list_later_is_written_on_the_next_start(conn):
    _initial_settings(conn, store(SETTINGS_INITIAL_ONLY="SHARING_ENABLED", SHARING_ENABLED="true"))
    later = store(SETTINGS_INITIAL_ONLY="SHARING_ENABLED,PUSH_ENABLED", SHARING_ENABLED="true", PUSH_ENABLED="true")
    _initial_settings(conn, later)
    assert later.get(conn, "push.enabled") is True
    assert [r["key"] for r in audit_rows(conn)] == ["sharing.enabled", "push.enabled"]


def test_the_server_writes_them_at_start_and_the_admin_page_can_change_them(tmp_path, foods_json, monkeypatch):
    from conftest import make_settings, signed_in_client

    monkeypatch.setenv("SETTINGS_INITIAL_ONLY", "SHARING_ENABLED")
    monkeypatch.setenv("SHARING_ENABLED", "true")
    monkeypatch.setenv("PUSH_ENABLED", "true")
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:
        items = c.get("/api/admin/settings").json()["settings"]
        assert items["sharing.enabled"] == {"value": True, "source": "instance", "locked_by_env": None, "scope": "instance"}
        assert items["push.enabled"]["locked_by_env"] == "PUSH_ENABLED"
        assert c.patch("/api/admin/settings", json={"sharing.enabled": False}).status_code == 200
        assert c.patch("/api/admin/settings", json={"push.enabled": False}).status_code == 409
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:  # a restart keeps the admin's choice
        assert c.get("/api/admin/settings").json()["settings"]["sharing.enabled"]["value"] is False


def test_the_check_command_names_them(tmp_path):
    out = io.StringIO()
    env = {"DATA_DIR": str(tmp_path / "data"), "SETTINGS_INITIAL_ONLY": "SHARING_ENABLED", "SHARING_ENABLED": "true", "PUSH_ENABLED": "true"}
    assert admin.main(["check"], env=env, out=out) == 0
    text = out.getvalue()
    assert "info: settings locked by env: push.enabled" in text
    assert "info: first values from env (changeable in the app afterwards): sharing.enabled" in text


def test_the_activity_list_says_where_a_first_value_came_from():
    from pathlib import Path

    view = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "${d.env ? ` (first value from ${d.env})` : ''}" in view


def test_env_template_lists_every_setting_and_is_a_valid_env_file(tmp_path):
    out = io.StringIO()
    assert admin.main(["env-template"], env={"DATA_DIR": str(tmp_path / "data")}, out=out) == 0
    text = out.getvalue()
    names = [line.split("=", 1)[0] for line in text.splitlines() if line and not line.startswith("#")]
    expected = sorted(d.env for d in settings_registry.all_settings() if d.env)
    assert sorted(names) == sorted(["SETTINGS_INITIAL_ONLY", *expected])
    assert "# registration.invite_ttl_days: Invite links expire after (days)" in text
    assert "#   Values: a whole number from 1 to 90. Default: 7." in text
    assert "#   Values: one of invite, closed, open. Default: invite." in text
    env = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))
    s = store(**env)
    assert s.validate_env_locks() == [] and s.initial_keys() == []  # all empty: nothing locked, nothing written

    out = io.StringIO()
    assert admin.main(["env-template", "--initial-only"], env={"DATA_DIR": str(tmp_path / "data")}, out=out) == 0
    assert "\nSETTINGS_INITIAL_ONLY=*\n" in out.getvalue()
