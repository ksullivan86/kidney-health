"""Height in feet and inches or centimetres (user.units.height).

The profile stores the height in centimetres; the setting changes only how Profile shows and takes it. These tests cover the
setting (registry, environment variable, API, import), the iPhone app's gateway list, the page's wiring, and the conversions and
Profile's boxes in tests/js/height_units.test.mjs.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import app_gateway, data_import
from app.settings_registry import REGISTRY
from app.settings_store import SettingsStore
from conftest import TestClient, make_settings, signed_in_client
from test_data_import import export_doc, post_import

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
KEY = "user.units.height"


def test_the_setting_is_registered_like_the_weight_unit():
    d = REGISTRY[KEY]
    assert (d.scope, d.env, d.default, d.label) == ("user_default", "HEIGHT_UNITS", "ft_in", "Units for height")
    assert d.validate("cm") == "cm" and d.validate("ft_in") == "ft_in"
    for bad in ("CM", "inches", None, 5):
        with pytest.raises(Exception):
            d.validate(bad)
    assert SettingsStore(env={"HEIGHT_UNITS": "cm"}).env_value(d) == (True, "cm")


def test_a_person_sets_it_and_the_admin_sets_the_default(client: TestClient):
    settings = client.get("/api/me/settings").json()["settings"]
    assert settings[KEY] == {"value": "ft_in", "source": "default", "editable": True}
    assert client.patch("/api/me/settings", json={KEY: "cm"}).status_code == 200
    assert client.get("/api/me/settings").json()["settings"][KEY] == {"value": "cm", "source": "user", "editable": True}
    r = client.patch("/api/me/settings", json={KEY: "inches"})
    assert r.status_code == 400 and "Input should be 'ft_in' or 'cm'" in r.json()["detail"]
    assert client.patch("/api/admin/settings", json={KEY: "cm"}).status_code == 200


def test_the_environment_variable_locks_it(tmp_path, foods_json, monkeypatch):
    monkeypatch.setenv("HEIGHT_UNITS", "cm")
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:
        item = c.get("/api/me/settings").json()["settings"][KEY]
        assert item["value"] == "cm" and item["source"] == "env" and item["editable"] is False


def test_it_moves_with_an_import_and_the_iphone_app_can_set_it(client: TestClient, tmp_path, foods_json):
    assert KEY in data_import.IMPORTED_SETTINGS
    assert KEY in app_gateway.BODY_KEYS[("PATCH", "/api/me/settings")]
    assert client.patch("/api/me/settings", json={KEY: "cm"}).status_code == 200
    with signed_in_client(make_settings(tmp_path / "second", foods_json)) as fresh:
        r = post_import(fresh, export_doc(client), replace_profile=True)
        assert r.status_code == 200, r.text
        assert fresh.get("/api/me/settings").json()["settings"][KEY]["value"] == "cm"


def test_the_page_offers_feet_and_inches_and_centimetres():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    ftin = html[html.index('id="pf-height-ftin-field"'):]
    ftin = ftin[:ftin.index("</fieldset>")]
    assert '<legend class="sr-only">Height</legend>' in ftin
    assert '<label for="pf-height-ft">Height (feet)</label>' in ftin and '<label for="pf-height-in">inches</label>' in ftin
    assert re.search(r'id="pf-height-ft"[^>]*min="3" max="8" step="1"', ftin)
    assert re.search(r'id="pf-height-in"[^>]*min="0" max="11.5" step="0.5"', ftin)
    assert re.search(r'<div class="field" id="pf-height-cm-field" hidden>\s*<label for="pf-height">Height \(cm\)</label>', html)
    assert '<option value="ft_in">Feet and inches</option>' in html and '<option value="cm">Centimetres (cm)</option>' in html
    assert '<select id="set-height-units"' in html
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "'user.units.height': { ft_in: 'Feet and inches', cm: 'Centimetres (cm)' }" in settings
    assert "['Default for everyone', ['ui.theme', 'user.units.labs', 'user.units.weight', 'user.units.height']]" in settings
    assert "api.updateMySettings({ 'user.units.height': sel.value })" in settings and "KH.views.profile.setHeightUnit(sel.value)" in settings
    profile = (STATIC / "js" / "views" / "profile.js").read_text(encoding="utf-8")
    assert "height_cm: readHeightCm()," in profile and "fillHeight(p.height_cm ?? null);" in profile and "loadHeightUnit();" in profile
    for name in ("import.js", "server_account.js"):
        assert "'user.units.weight', 'user.units.height'" in (STATIC / "js" / "mock" / name).read_text(encoding="utf-8"), name


def test_the_conversions_and_profile_boxes():
    assert shutil.which("node"), "Node.js is required for the height tests"
    runner = ROOT / "tests" / "js" / "height_units.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
