"""Barcode settings and configuration (note 03 R10, §9 B5)."""
from __future__ import annotations

import pytest

from app import settings_registry
from app.config import ConfigError, load_settings
from app.settings_store import SettingsStore
from conftest import signed_in_client


@pytest.mark.parametrize("key, default, env, scope", [
    ("food.off_enabled", False, "OFF_ENABLED", "instance"),
    ("food.off_consent", False, None, "user"),
    ("food.scan_prefer_camera", True, None, "user"),  # note 03 R10 "Prefer live camera" (v0.3.0 review L15)
    ("food.off_contact", "https://github.com/ksullivan86/kidney-health", "OFF_CONTACT", "instance"),
    ("food.off_rate_per_minute", 10, "OFF_RATE_PER_MINUTE", "instance"),
    ("food.barcode_negative_ttl_hours", 24, "BARCODE_NEGATIVE_TTL_HOURS", "instance"),
    ("food.usda_branded_barcode", True, "USDA_BRANDED_BARCODE", "instance"),
])
def test_registered_keys(key: str, default: object, env: str | None, scope: str) -> None:
    d = settings_registry.get(key)
    assert (d.default, d.env, d.scope) == (default, env, scope)
    assert d.label


@pytest.mark.parametrize("value, ok", [(1, True), (10, True), (15, True), (0, False), (16, False), ("12", True)])
def test_off_rate_is_capped_at_what_open_food_facts_allows(value: object, ok: bool) -> None:
    d = settings_registry.get("food.off_rate_per_minute")
    if ok:
        assert 1 <= d.validate(value) <= 15
    else:
        with pytest.raises(Exception):
            d.validate(value)


@pytest.mark.parametrize("value, ok", [
    ("admin@example.org", True), ("https://example.org/contact", True), ("Mum's server, mum@example.org", True),
    ("ab", False), ("a(b)c", False), ("x\r\nX-Evil: 1", False), ("tab\there", False), ("café@example.org", False),
    ("x" * 201, False),
])
def test_contact_cannot_break_the_user_agent(value: str, ok: bool) -> None:
    d = settings_registry.get("food.off_contact")
    if ok:
        assert d.validate(value) == value.strip()
    else:
        with pytest.raises(Exception):
            d.validate(value)


def test_env_locks(tmp_path) -> None:
    store = SettingsStore(env={"OFF_RATE_PER_MINUTE": "5", "USDA_BRANDED_BARCODE": "false", "OFF_CONTACT": "ops@example.org"})
    store.validate_env_locks()  # valid values: no error
    from app import db

    conn = db.connect(":memory:")
    db.migrate(conn)
    assert store.get(conn, "food.off_rate_per_minute") == 5
    assert store.get(conn, "food.usda_branded_barcode") is False
    assert store.get(conn, "food.off_contact") == "ops@example.org"
    conn.close()


def test_bad_env_lock_fails_at_start_up() -> None:
    store = SettingsStore(env={"OFF_RATE_PER_MINUTE": "40"})
    with pytest.raises(ConfigError):
        store.validate_env_locks()


@pytest.mark.parametrize("raw, expected", [
    (None, "https://world.openfoodfacts.org"),
    ("https://world.openfoodfacts.net/", "https://world.openfoodfacts.net"),
    ("https://off.lan:8443", "https://off.lan:8443"),
    ("http://localhost:8080", "http://localhost:8080"),
])
def test_off_base_url_from_the_environment(tmp_path, raw: str | None, expected: str) -> None:
    env = {"DATA_DIR": str(tmp_path)}
    if raw is not None:
        env["OFF_BASE_URL"] = raw
    assert load_settings(env).off_base_url == expected


@pytest.mark.parametrize("raw", ["http://world.openfoodfacts.org", "https://user:pw@off.example", "https://off.example/api",
                                 "file:///etc/passwd", "gopher://x", "https://off.example/?x=1"])
def test_unsafe_off_base_url_stops_the_start(tmp_path, raw: str) -> None:
    with pytest.raises(ConfigError) as info:
        load_settings({"DATA_DIR": str(tmp_path), "OFF_BASE_URL": raw})
    assert "OFF_BASE_URL" in str(info.value)


def test_off_base_url_is_not_a_runtime_setting(settings) -> None:
    assert not any("base_url" in d.key for d in settings_registry.all_settings() if d.key.startswith("food."))
    with signed_in_client(settings) as c:
        r = c.patch("/api/admin/settings", json={"food.off_base_url": "https://evil.example"})
        assert r.status_code == 400
