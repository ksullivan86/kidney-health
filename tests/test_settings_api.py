"""Settings and key routes (note 07 §4.11, §4.12): precedence through the API, env locks, admin-only
instance keys, write-only keys, own → shared → none resolution, quotas and the USDA test call."""
from __future__ import annotations

import httpx2
import pytest

import app.foods as foods_module
from app.settings_store import default_store

from conftest import HTTPS_URL, TestClient, add_user, make_settings, signed_in_client

OWN_KEY = "own-usda-key-ABCDEFGHIJKLMNOP-1"
SHARED_KEY = "shared-usda-key-QRSTUVWXYZ-0042"


@pytest.fixture
def usda_upstream(monkeypatch):
    """Mocked FoodData Central: 401 for keys starting with "bad", else an empty search."""
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        key = request.headers.get("x-api-key", "")
        seen.append(key)
        if key.startswith("bad"):
            return httpx2.Response(401, json={"error": "API_KEY_INVALID"})
        return httpx2.Response(200, json={"foods": []}, headers={"X-RateLimit-Remaining": "900"})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    return seen


@pytest.fixture
def env_cleanup(monkeypatch):
    yield monkeypatch
    default_store().invalidate()


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def test_user_settings_precedence_and_reset(two_clients):
    admin, sam = two_clients
    view = sam.get("/api/me/settings").json()["settings"]
    assert view["ui.theme"] == {"value": "system", "source": "default", "editable": True}
    assert "registration.mode" not in view  # instance keys are not personal
    # the admin's instance default applies to everybody who has not chosen
    assert admin.patch("/api/admin/settings", json={"ui.theme": "light"}).status_code == 200
    assert sam.get("/api/me/settings").json()["settings"]["ui.theme"]["source"] == "instance"
    r = sam.patch("/api/me/settings", json={"ui.theme": "dark"})
    assert r.status_code == 200 and r.json()["settings"]["ui.theme"] == {"value": "dark", "source": "user", "editable": True}
    assert admin.get("/api/me/settings").json()["settings"]["ui.theme"]["value"] == "light"
    r = sam.patch("/api/me/settings", json={"ui.theme": None})  # back to inherited
    assert r.json()["settings"]["ui.theme"]["source"] == "instance"


def test_user_settings_validation_and_scope(client):
    assert client.patch("/api/me/settings", json={"ui.theme": "purple"}).status_code == 400
    assert client.patch("/api/me/settings", json={"no.such.key": 1}).status_code == 400
    r = client.patch("/api/me/settings", json={"registration.mode": "open"})
    assert r.status_code == 403  # an instance key cannot be set as a personal value


def test_admin_settings_are_audited_and_admin_only(two_clients):
    admin, sam = two_clients
    view = admin.get("/api/admin/settings").json()["settings"]
    assert view["registration.mode"] == {"value": "invite", "source": "default", "locked_by_env": None, "scope": "instance"}
    assert sam.get("/api/admin/settings").status_code == 403
    assert sam.patch("/api/admin/settings", json={"instance.name": "Mine"}).status_code == 403
    r = admin.patch("/api/admin/settings", json={"instance.name": "The Smiths", "providers.usda.daily_limit_per_user": 5})
    assert r.status_code == 200 and r.json()["settings"]["instance.name"]["value"] == "The Smiths"
    assert admin.patch("/api/admin/settings", json={"providers.usda.daily_limit_per_user": -1}).status_code == 400
    events = [e for e in admin.get("/api/admin/audit").json()["events"] if e["action"] == "settings.changed"]
    assert {(e["details"]["key"], e["details"]["new"]) for e in events} == {
        ("instance.name", "The Smiths"), ("providers.usda.daily_limit_per_user", 5)}
    assert TestClient(admin.app).get("/api/auth/status").json()["instance_name"] == "The Smiths"


def test_env_locks_win_and_cannot_be_changed(two_clients, env_cleanup):
    admin, sam = two_clients
    env_cleanup.setenv("REGISTRATION_MODE", "closed")
    view = admin.get("/api/admin/settings").json()["settings"]["registration.mode"]
    assert view == {"value": "closed", "source": "env", "locked_by_env": "REGISTRATION_MODE", "scope": "instance"}
    r = admin.patch("/api/admin/settings", json={"registration.mode": "open"})
    assert r.status_code == 409 and r.json()["locked_by_env"] == "REGISTRATION_MODE"
    assert admin.post("/api/admin/invites", json={}).status_code == 409  # closed


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #


def test_own_key_lifecycle_is_write_only(client, usda_upstream):
    item = client.get("/api/me/keys").json()["providers"][0]
    assert item["own"] == {"set": False} and item["effective"] == "none" and item["label"] == "USDA FoodData Central"
    r = client.put("/api/me/keys/usda", json={"api_key": OWN_KEY})
    assert r.status_code == 200
    own = r.json()["own"]
    assert own["set"] is True and own["last4"] == OWN_KEY[-4:] and OWN_KEY not in r.text
    assert r.json()["effective"] == "own"
    short = client.put("/api/me/keys/usda", json={"api_key": "short-key-12"}).json()
    assert "last4" not in short["own"]  # keys under 20 characters get no hint
    assert client.put("/api/me/keys/usda", json={"api_key": "bad key with spaces"}).status_code == 400
    assert client.put("/api/me/keys/nope", json={"api_key": OWN_KEY}).status_code == 404
    assert client.request("DELETE", "/api/me/keys/usda").status_code == 204
    assert client.get("/api/me/keys").json()["providers"][0]["own"] == {"set": False}
    actions = [e["action"] for e in client.get("/api/me/activity").json()["events"]]
    assert actions.count("secret.set") == 2 and "secret.removed" in actions


def test_key_test_call_and_its_rate_limit(client, usda_upstream):
    r = client.put("/api/me/keys/usda", json={"api_key": "bad-" + OWN_KEY, "test": True})
    assert r.status_code == 200 and r.json()["test"] == "rejected"
    r = client.put("/api/me/keys/usda", json={"api_key": OWN_KEY, "test": True})
    assert r.json()["test"] == "ok"
    for _ in range(8):
        client.put("/api/me/keys/usda", json={"api_key": OWN_KEY, "test": True})
    r = client.put("/api/me/keys/usda", json={"api_key": OWN_KEY, "test": True})
    assert r.status_code == 429 and "retry-after" in r.headers  # 10 tests per hour (a key-checking oracle)
    assert client.put("/api/me/keys/usda", json={"api_key": OWN_KEY}).status_code == 200  # saving without a test is fine


def test_resolution_own_then_shared_with_quota(tmp_path, foods_json, usda_upstream):
    settings = make_settings(tmp_path, foods_json)
    with signed_in_client(settings, base_url=HTTPS_URL) as admin:
        sam = add_user(admin)
        assert admin.put("/api/admin/keys/usda", json={"api_key": SHARED_KEY}).status_code == 200
        assert admin.patch("/api/admin/settings", json={"providers.usda.daily_limit_per_user": 2}).status_code == 200
        item = sam.get("/api/me/keys").json()["providers"][0]
        assert item["effective"] == "shared" and item["shared"] == {"available": True, "remaining_today": 2, "daily_limit": 2}
        assert sam.get("/api/foods/usda/search", params={"q": "oats"}).status_code == 200
        assert sam.get("/api/foods/usda/search", params={"q": "oats"}).status_code == 200
        r = sam.get("/api/foods/usda/search", params={"q": "oats"})
        assert r.status_code == 503 and r.json()["reason"] == "quota_exhausted"
        assert usda_upstream == [SHARED_KEY, SHARED_KEY]
        # an own key wins and is not limited
        assert sam.put("/api/me/keys/usda", json={"api_key": OWN_KEY}).status_code == 200
        assert sam.get("/api/foods/usda/search", params={"q": "oats"}).status_code == 200
        assert usda_upstream[-1] == OWN_KEY
        usage = {(u["provider"], u["scope"]): u for u in sam.get("/api/me/usage").json()["usage"]}
        assert usage[("usda", "shared")]["today"] == 2 and usage[("usda", "own")]["today"] == 1
        admin_usage = admin.get("/api/admin/usage").json()["usage"]
        assert {"user_id", "username", "provider", "key_scope", "requests"} == set(admin_usage[0])
        # a rejected own key never falls back to the shared one
        assert sam.put("/api/me/keys/usda", json={"api_key": "bad-" + OWN_KEY}).status_code == 200
        r = sam.get("/api/foods/usda/search", params={"q": "oats"})
        assert r.status_code == 503 and "Your USDA key was rejected" in r.json()["detail"]
        assert usda_upstream[-1] == "bad-" + OWN_KEY


def test_shared_key_switches(tmp_path, foods_json, usda_upstream):
    with signed_in_client(make_settings(tmp_path, foods_json), base_url=HTTPS_URL) as admin:
        sam = add_user(admin)
        sam_id = sam.get("/api/me").json()["id"]
        r = sam.get("/api/foods/usda/search", params={"q": "x"})
        assert r.status_code == 503 and r.json()["reason"] == "not_configured"
        admin.put("/api/admin/keys/usda", json={"api_key": SHARED_KEY})
        assert admin.patch(f"/api/admin/users/{sam_id}", json={"can_use_shared": False}).status_code == 200
        r = sam.get("/api/foods/usda/search", params={"q": "x"})
        assert r.status_code == 503 and r.json()["reason"] == "not_allowed"
        admin.patch(f"/api/admin/users/{sam_id}", json={"can_use_shared": True})
        admin.patch("/api/admin/settings", json={"providers.usda.shared_enabled": False})
        assert sam.get("/api/foods/usda/search", params={"q": "x"}).json()["reason"] == "not_allowed"
        admin.patch("/api/admin/settings", json={"providers.usda.user_keys_allowed": False})
        assert sam.put("/api/me/keys/usda", json={"api_key": OWN_KEY}).status_code == 403
        assert admin.request("DELETE", "/api/admin/keys/usda").status_code == 204
        assert admin.get("/api/admin/keys").json()["providers"][0]["shared"] == {"set": False}


def test_env_shared_key_is_locked(tmp_path, foods_json, usda_upstream):
    settings = make_settings(tmp_path, foods_json, usda_api_key=SHARED_KEY)
    with signed_in_client(settings) as admin:
        shared = admin.get("/api/admin/keys").json()["providers"][0]["shared"]
        assert shared == {"set": True, "source": "env", "locked": True}
        assert admin.put("/api/admin/keys/usda", json={"api_key": OWN_KEY}).status_code == 409
        assert admin.request("DELETE", "/api/admin/keys/usda").status_code == 409


def test_unreadable_key_asks_to_be_entered_again(client, usda_upstream):
    import sqlite3

    assert client.put("/api/me/keys/usda", json={"api_key": OWN_KEY}).status_code == 200
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.execute("UPDATE secrets SET ciphertext = ? WHERE owner_user_id = 1", (b"gAAAAA-not-a-valid-token",))
    conn.commit()
    conn.close()
    own = client.get("/api/me/keys").json()["providers"][0]["own"]
    assert own["set"] is True and own["status"] == "unreadable"
    r = client.get("/api/foods/usda/search", params={"q": "x"})
    assert r.status_code == 503 and r.json()["reason"] == "own_key_unreadable"


def test_usda_hourly_guard_pauses_a_key_close_to_its_limit(client, monkeypatch):
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(200, json={"foods": []}, headers={"X-RateLimit-Remaining": "12"})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(foods_module, "_usda_guard", {})
    client.put("/api/me/keys/usda", json={"api_key": OWN_KEY})
    assert client.get("/api/foods/usda/search", params={"q": "x"}).status_code == 200
    r = client.get("/api/foods/usda/search", params={"q": "x"})
    assert r.status_code == 429 and len(calls) == 1


def test_usda_guard_is_keyed_by_whose_key_it_is_never_by_key_material():
    from app.credentials import Credential

    own = Credential(provider="usda", scope="own", source="user", fields={"api_key": OWN_KEY})
    shared = Credential(provider="usda", scope="shared", source="db", fields={"api_key": SHARED_KEY})
    assert foods_module.guard_id(own, 7) == "usda:user:7"
    assert foods_module.guard_id(own, 8) == "usda:user:8"          # each person's own key is tracked separately
    assert foods_module.guard_id(shared, 7) == foods_module.guard_id(shared, 8) == "usda:shared:db"
    for cred in (own, shared):
        assert cred.api_key not in foods_module.guard_id(cred, 7)
