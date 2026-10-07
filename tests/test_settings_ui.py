"""The sign-in screens and the Settings view (note 07 §4.5, §4.17; note 02 R10): static checks of the
markup and scripts, the settings twin's parity vectors, and the two Open Food Facts keys the setup
screen and Settings use (ARCHITECTURE v0.3 item 8).

The browser behaviour itself is walked with Playwright against the real server and in the preview
(see docs/dev/progress/frontend-signin-settings.md for the commands)."""
from __future__ import annotations

import importlib.util
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app import settings_registry
from app.config import Settings
from app.main import APP_VERSION, create_app

from conftest import ADMIN_PASSWORD, TestClient, setup_code_from_logs, signed_in_client

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SETTINGS_JS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
AUTH_JS = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
ENGINE_JS = (STATIC / "js" / "engine" / "settings.js").read_text(encoding="utf-8")
VECTORS = ROOT / "tests" / "data" / "settings_vectors.json"


class _Inputs(HTMLParser):
    """Every <input>, <label for>, and element id inside the #view-auth section and the re-auth sheet."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str | None]] = []
        self.labels: set[str] = set()
        self.toggles: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(str(a["id"]))
        if tag == "input":
            self.inputs.append(a)
        elif tag == "label" and a.get("for"):
            self.labels.add(str(a["for"]))
        elif tag == "button" and "pw-toggle" in (a.get("class") or ""):
            self.toggles.append(str(a.get("aria-controls")))


def _section(start: str, end: str) -> str:
    i = INDEX.index(start)
    return INDEX[i:INDEX.index(end, i)]


def _parse(html: str) -> _Inputs:
    p = _Inputs()
    p.feed(html)
    return p


# --------------------------------------------------------------------------- markup
def test_auth_forms_are_password_manager_friendly() -> None:
    auth = _parse(_section('<section id="view-auth"', "</section>\n"))
    by_id = {i["id"]: i for i in auth.inputs if i.get("id")}
    assert by_id["login-username"]["autocomplete"] == "username"
    assert by_id["login-password"]["autocomplete"] == "current-password"
    for new in ("setup-password", "reg-password", "reset-password", "chg-new"):
        assert by_id[new]["autocomplete"] == "new-password" and by_id[new]["type"] == "password", new
        assert by_id[new]["maxlength"] == "128" and by_id[new]["minlength"] == "15", new
    assert by_id["chg-current"]["autocomplete"] == "current-password"
    # the forced new-password form carries the username for the password manager
    assert by_id["chg-username"]["autocomplete"] == "username" and "readonly" in by_id["chg-username"]
    assert by_id["setup-code"]["autocomplete"] == "one-time-code"
    # every visible input has a label; every password field has a Show toggle pointing at it
    for i in auth.inputs:
        if "hidden" in i:
            continue
        assert i["id"] in auth.labels, f"input #{i['id']} has no <label for>"
    passwords = {i["id"] for i in auth.inputs if i.get("type") == "password"}
    assert set(auth.toggles) == passwords
    # the Open Food Facts first-run box is off unless ticked (ARCHITECTURE v0.3 item 8)
    assert by_id["setup-off"]["type"] == "checkbox" and "checked" not in by_id["setup-off"]


def test_auth_messages_use_live_regions_and_the_reauth_sheet_is_complete() -> None:
    assert '<div class="auth-error" id="auth-error" role="alert" aria-live="assertive"></div>' in INDEX
    assert '<div class="auth-error" id="reauth-error" role="alert" aria-live="assertive"></div>' in INDEX
    sheet = _parse(_section('<dialog id="sheet-reauth"', "</dialog>"))
    by_id = {i["id"]: i for i in sheet.inputs}
    assert by_id["reauth-password"]["autocomplete"] == "current-password"
    assert by_id["reauth-username"]["autocomplete"] == "username" and "hidden" in by_id["reauth-username"]
    assert sheet.toggles == ["reauth-password"]
    # the plain-HTTP, HTTPS-required and no-login notes exist and start hidden
    for note in ('id="auth-https" role="note" hidden', 'id="auth-insecure" role="note" hidden', 'id="nologin-banner" role="note" hidden'):
        assert note in INDEX, note
    assert "Anyone who can open this page can see and change this data." in INDEX


def test_settings_view_sections_and_entry_points() -> None:
    view = _section('<section id="view-settings"', "</main>")
    for sec in ("set-account", "set-prefs", "set-food", "set-ai", "set-device", "set-admin", "set-about"):
        assert f'id="{sec}"' in view, sec
    assert 'id="set-admin" data-title="Admin" aria-labelledby="set-admin-h" hidden' in view  # admins only
    # This device holds the install panel (note 02 R10), hidden until js/pwa.js fills it
    assert '<div class="install-panel" id="install-panel" aria-labelledby="install-heading" hidden>' in view
    # reachable from the header gear and from Profile; the gear and the tabs wait for sign-in
    assert '<button id="settings-open" class="icon-btn" type="button" aria-label="Settings" title="Settings" data-signed-in hidden>' in INDEX
    assert '<nav class="tabs" aria-label="Views" data-signed-in hidden>' in INDEX
    assert 'id="profile-open-settings"' in INDEX
    assert "router.show('settings')" in (STATIC / "js" / "views" / "profile.js").read_text(encoding="utf-8")
    # Settings is a view without a tab (later views without a tab, such as Labs, follow it)
    assert re.search(r"const VIEWS = \[\.\.\.TAB_VIEWS, 'settings'(?:, '[a-z]+')*\];", (STATIC / "js" / "core.js").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- scripts
def test_keys_are_write_only_in_the_page() -> None:
    """The key field is an empty password box that is never filled from a response (note 07 §4.17)."""
    widget = SETTINGS_JS[SETTINGS_JS.index("function keyStateText("):SETTINGS_JS.index("// Section: Account")]
    assert "type: 'password', autocomplete: 'off'" in widget and "spellcheck: 'false'" in widget
    assert re.findall(r"input\.value = ([^;]+);", widget) == ["''", "''"], "the key input is only ever cleared"
    # responses are read for set / last4 / updated_at / status only
    assert "st.last4" in widget and not re.search(r"\b(?:st|res|item|own|shared)\.(?:api_key|key)\b", widget)
    # what goes to the server: { api_key: key, test } bodies only
    assert len(re.findall(r"\{ api_key: key, test \}", SETTINGS_JS)) == 2


def test_link_tokens_leave_the_address_bar() -> None:
    assert "try { history.replaceState(null, '', HASH[route.screen]); }" in AUTH_JS
    assert "sessionStorage.setItem(TOKEN_KEY" in AUTH_JS and "sessionStorage.removeItem(TOKEN_KEY)" in AUTH_JS
    # tokens are never logged or put in a request URL
    assert "console" not in AUTH_JS.replace("console.error(e)", "")
    assert not re.search(r"request\(\s*'[A-Z]+',\s*`[^`]*\$\{linkToken", AUTH_JS)


def test_settings_page_never_touches_service_workers_itself() -> None:
    """The preview build leaves js/pwa.js out and must not mention service workers at all."""
    for js in (SETTINGS_JS, AUTH_JS):
        assert "serviceWorker" not in js and "/sw.js" not in js and "kh-sw" not in js


def test_app_version_shown_in_settings_matches_the_server() -> None:
    m = re.search(r"const APP_VERSION = '([^']+)';", SETTINGS_JS)
    assert m and m.group(1) == APP_VERSION


# --------------------------------------------------------------------------- settings twin parity
def _generator():
    spec = importlib.util.spec_from_file_location("gen_settings_vectors", ROOT / "tests" / "data" / "gen_settings_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_settings_vectors_are_current() -> None:
    committed = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert committed == _generator().build(), (
        "tests/data/settings_vectors.json is stale: app/settings_registry.py or app/settings_store.py changed. "
        "Run `python3 tests/data/gen_settings_vectors.py`, then `node tests/js/run_vectors.mjs`, and update "
        "app/static/js/engine/settings.js until both agree."
    )


def test_engine_registry_lists_every_server_key() -> None:
    """A Python-only check of what node tests/js/run_vectors.mjs verifies in full."""
    js_keys = re.findall(r"\{ key: '([a-z0-9_.]+)'", ENGINE_JS)
    assert js_keys == [d.key for d in settings_registry.all_settings()]
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    sources = {item["source"] for case in doc["precedence_cases"] for view in ("user_view", "admin_view") for item in case[view].values()}
    assert sources == {"env", "user", "instance", "default"}  # every level of the precedence is exercised


# --------------------------------------------------------------------------- the Open Food Facts keys
def test_open_food_facts_keys_are_registered() -> None:
    on = settings_registry.get("food.off_enabled")
    consent = settings_registry.get("food.off_consent")
    assert (on.scope, on.default, on.env) == ("instance", False, "OFF_ENABLED")
    assert (consent.scope, consent.default, consent.env) == ("user", False, None)


def test_first_run_checkbox_turns_open_food_facts_on(tmp_path, foods_json, caplog) -> None:
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), TestClient(create_app(settings)) as c:
        body = {"code": setup_code_from_logs(caplog), "username": "mum", "password": ADMIN_PASSWORD, "off_enabled": True}
        assert c.post("/api/auth/setup", json=body).status_code == 200
        item = c.get("/api/admin/settings").json()["settings"]["food.off_enabled"]
        assert item == {"value": True, "source": "instance", "locked_by_env": None, "scope": "instance"}
        mine = c.get("/api/me/settings").json()["settings"]
        assert mine["food.off_consent"] == {"value": False, "source": "default", "editable": True}
        assert "food.off_enabled" not in mine  # an instance key: not in a person's view


def test_off_enabled_env_lock_wins_and_is_shown_as_locked(settings, monkeypatch) -> None:
    monkeypatch.setenv("OFF_ENABLED", "false")
    with signed_in_client(settings) as c:
        item = c.get("/api/admin/settings").json()["settings"]["food.off_enabled"]
        assert item == {"value": False, "source": "env", "locked_by_env": "OFF_ENABLED", "scope": "instance"}
        r = c.patch("/api/admin/settings", json={"food.off_enabled": True}, headers={"X-Requested-With": "kidney-health"})
        assert r.status_code == 409 and r.json()["locked_by_env"] == "OFF_ENABLED"


@pytest.mark.parametrize("value", ["yes", "maybe"])
def test_off_consent_is_a_personal_boolean(settings, value) -> None:
    with signed_in_client(settings) as c:
        r = c.patch("/api/me/settings", json={"food.off_consent": value}, headers={"X-Requested-With": "kidney-health"})
        if value == "yes":
            assert r.status_code == 200 and r.json()["settings"]["food.off_consent"]["value"] is True
        else:
            assert r.status_code == 400 and "food.off_consent" in r.json()["detail"]
        r = c.patch("/api/me/settings", json={"food.off_enabled": True}, headers={"X-Requested-With": "kidney-health"})
        assert r.status_code == 403  # the server switch is the admin's


# --------------------------------------------------------------------------- M1 review fixes

MOCK_AUTH_JS = (STATIC / "js" / "mock" / "auth.js").read_text(encoding="utf-8")


def test_reset_screen_shows_whose_account_the_link_is_for() -> None:
    """An admin-created account's owner never saw its username: the link page shows it (read-only,
    autocomplete=username, so password managers save both) and uses welcome wording."""
    form = _section('<form id="form-reset"', "</form>")
    m = re.search(r'<input id="reset-username"[^>]*>', form)
    assert m and 'autocomplete="username"' in m.group(0) and "readonly" in m.group(0)
    assert 'id="reset-intro"' in form
    assert "'/api/auth/reset/info'" in AUTH_JS and "new_account" in AUTH_JS
    assert "sign in as ${res.user.username}" in AUTH_JS
    # the demo answers the new public route like an expired link, as the server would
    assert "'POST /api/auth/reset/info'" in MOCK_AUTH_JS and "route('POST', '/api/auth/reset/info'" in MOCK_AUTH_JS


def test_field_errors_sit_next_to_the_field() -> None:
    assert "function fieldError(" in AUTH_JS and "aria-describedby" in AUTH_JS
    assert "function withoutFieldPrefix(" in AUTH_JS
    assert ".field-error" in (STATIC / "css" / "auth.css").read_text(encoding="utf-8")


def test_connection_row_asks_the_address_not_is_secure_context() -> None:
    """isSecureContext is true on http://localhost, which is not encrypted."""
    assert "window.location.protocol === 'https:'" in SETTINGS_JS
    assert re.search(r"\['Connection', https \?", SETTINGS_JS)


def test_admin_people_list_shows_and_revokes_open_links() -> None:
    assert "u.reset_link" in SETTINGS_JS and "revokeResetLink" in SETTINGS_JS
    assert "`/api/admin/users/${id}/reset-link`" in SETTINGS_JS
    assert "Someone created a password reset link for your account" in SETTINGS_JS
    assert "route('DELETE', userIdRoute('/reset-link')" in MOCK_AUTH_JS and "reset_link:" in MOCK_AUTH_JS
    assert "_voidIssuedBy" in MOCK_AUTH_JS


def test_activity_logs_name_the_target_account() -> None:
    assert "function targetOf(" in SETTINGS_JS and "deleted user #" in SETTINGS_JS
    assert "'user.reset_link_revoked'" in SETTINGS_JS and "'user.reset_link_revoked'" in MOCK_AUTH_JS


def test_no_delete_form_without_sign_in() -> None:
    assert "set-delete-none" in SETTINGS_JS


def test_api_has_the_reset_link_routes(two_clients) -> None:
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    assert admin.post(f"/api/admin/users/{sam_id}/reset-link").status_code == 200
    users = {u["id"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert set(users[sam_id]["reset_link"]) == {"id", "created_by", "created_at", "expires_at"}
    assert users[1]["reset_link"] is None
    assert admin.request("DELETE", f"/api/admin/users/{sam_id}/reset-link").status_code == 204
    assert sam.request("DELETE", f"/api/admin/users/{sam_id}/reset-link").status_code == 403  # admins only


# --------------------------------------------------------------------------- Admin → Server settings groups
def _server_setting_groups() -> dict[str, list[str]]:
    block = re.search(r"const GROUPS = \[(.*?)\n  \];", SETTINGS_JS, re.S)
    assert block, "GROUPS not found in js/views/settings.js"
    groups: dict[str, list[str]] = {}
    for title, keys in re.findall(r"\['([^']+)', \[(.*?)\]\]", block.group(1), re.S):
        groups[title] = re.findall(r"'([a-z0-9_.]+)'", keys)
    return groups


def test_every_server_setting_has_a_named_group() -> None:
    """CONTRIBUTING ("Add a setting"): every admin-editable key belongs to a group in Admin → Server settings, so
    nothing lands under "Other" in registry order (v0.3.0 review: the eight ai.* switches did)."""
    grouped = [k for keys in _server_setting_groups().values() for k in keys]
    assert len(grouped) == len(set(grouped)), "a key is listed in two groups"
    editable = {k for k, d in settings_registry.REGISTRY.items() if d.admin_editable}
    assert editable - set(grouped) == set(), f"not in any group (would show under 'Other'): {sorted(editable - set(grouped))}"
    assert set(grouped) - set(settings_registry.REGISTRY) == set(), "GROUPS names a key the registry does not have"
    ai = _server_setting_groups()["Optional AI"]
    assert ai[0] == "ai.enabled", "the AI master switch comes first (Settings → AI ideas sends admins to it)"


def test_an_ai_switch_change_refreshes_the_ai_panel_and_buttons() -> None:
    """v0.3.0 review: after an admin switched "Optional AI ideas", Settings → AI ideas kept the old text until the
    view was opened again. The save handler now asks js/views/ai.js to draw again (status cache dropped), and that
    render keeps only its newest copy when two overlap."""
    assert "if (key.startsWith('ai.') && KH.ai) {" in SETTINGS_JS
    for call in ("KH.ai.forget()", "KH.ai.renderSettings()", "KH.ai.renderAddSlot()"):
        assert call in SETTINGS_JS, call
    ai_js = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
    body = ai_js[ai_js.index("async function renderSettings()"):ai_js.index("function personalPart(me)")]
    assert "const ticket = ++settingsRender;" in body and "if (current()) slot.replaceChildren(...parts);" in body
    assert "slot.append(personalPart" not in body and "slot.append(await adminPart" not in body


def test_the_ui_promises_no_unbuilt_feature() -> None:
    """Quality bar (v0.3.0): no disabled placeholder control that promises "a later version" (the "Units: other units
    (lb, oz) are planned" select had no spec behind it). Deferred work belongs in docs/ROADMAP.md, not in the UI."""
    for path in [STATIC / "index.html", *(STATIC / "js").rglob("*.js")]:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in ("later version", "coming soon", "coming in v0.", "not yet available", "planned for a later"):
            assert phrase not in text, f"{path.relative_to(ROOT)} says {phrase!r}"
    assert 'id="set-units"' not in INDEX
