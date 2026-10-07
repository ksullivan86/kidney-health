"""Proxy-header and no-login modes (note 07 §4.5, §9 N2), switching modes, and secrets never echoed
in validation errors or logs (§9 N4)."""
from __future__ import annotations

import logging
import sqlite3

import pytest

from app.config import ConfigError, Settings, load_settings
from app.main import create_app

from conftest import ADMIN_PASSWORD, DAY, HTTPS_URL, TestClient, make_settings, setup_code_from_logs, sign_in

PROXY_SECRET = "p" * 40
PROXY = ("127.0.0.1", 4321)


def proxy_settings(tmp_path, foods_json, **kw) -> Settings:
    values = dict(
        data_dir=tmp_path / "data",
        foods_json=foods_json,
        auth_mode="proxy",
        trusted_proxies=("127.0.0.1",),
        trusted_proxy_user_header="Remote-User",
        trusted_proxy_groups_header="Remote-Groups",
        trusted_proxy_name_header="Remote-Name",
        trusted_proxy_secret=PROXY_SECRET,
        proxy_logout_url="https://auth.example.org/logout",
    )
    values.update(kw)
    return Settings(**values)


def via_proxy(app, user: str | None = None, *, secret: str = PROXY_SECRET, client=PROXY, **headers: str) -> TestClient:
    h = {"X-Proxy-Secret": secret, **headers}
    if user is not None:
        h["Remote-User"] = user
    return TestClient(app, client=client, headers=h)


@pytest.fixture
def proxy_app(tmp_path, foods_json, caplog):
    """A proxy-mode app whose first-run setup was completed by "alice" through the proxy."""
    settings = proxy_settings(tmp_path, foods_json, trusted_proxy_admin_group="kidney-admins", proxy_auto_create_users=True)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), TestClient(create_app(settings), client=PROXY) as boot:
        code = setup_code_from_logs(caplog)
        alice = via_proxy(boot.app, "alice", **{"Remote-Groups": "family|kidney-admins"})
        assert alice.get("/api/auth/status").json()["setup_required"] is True
        r = alice.post("/api/auth/setup", json={"code": code})
        assert r.status_code == 200, r.text
        assert r.json()["user"] == {**r.json()["user"], "id": 1, "username": "alice", "auth_source": "proxy", "role": "admin"}
        yield boot.app


def test_identity_comes_from_the_trusted_header(proxy_app):
    alice = via_proxy(proxy_app, "alice", **{"Remote-Groups": "kidney-admins"})
    assert alice.get("/api/me").json()["username"] == "alice"
    assert alice.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 1}).status_code == 201
    status = alice.get("/api/auth/status").json()
    assert status["auth_mode"] == "proxy" and status["user"]["username"] == "alice"
    assert status["logout_url"] == "https://auth.example.org/logout" and status["registration"] == "disabled"
    r = alice.post("/api/auth/logout")
    assert r.status_code == 200 and r.json()["redirect"] == "https://auth.example.org/logout"
    assert alice.get("/api/me/export.zip").status_code == 200  # the IdP handles re-authentication


def test_headers_from_untrusted_peers_or_without_the_secret_are_ignored(proxy_app):
    assert via_proxy(proxy_app, "alice", secret="wrong" * 10).get("/api/me").status_code == 401
    assert via_proxy(proxy_app, "alice", secret="").get("/api/me").status_code == 401
    assert via_proxy(proxy_app, "alice", client=("198.51.100.20", 1)).get("/api/me").status_code == 401
    assert proxy_app.state.security.snapshot()["ignored_identity_headers"] >= 3


def test_password_routes_are_404_and_session_cookies_are_ignored(proxy_app):
    alice = via_proxy(proxy_app, "alice")
    for path, body in (
        ("/api/auth/login", {"username": "alice", "password": ADMIN_PASSWORD}),
        ("/api/auth/register", {"username": "x", "password": ADMIN_PASSWORD}),
        ("/api/auth/reset", {"token": "a.b", "password": ADMIN_PASSWORD}),
        ("/api/auth/reauth", {"password": ADMIN_PASSWORD}),
        ("/api/me/password", {"current_password": ADMIN_PASSWORD, "new_password": ADMIN_PASSWORD}),
    ):
        assert alice.post(path, json=body).status_code == 404, path
    nobody = via_proxy(proxy_app)
    assert nobody.get("/api/me", headers={"Cookie": "kh_session=" + "a" * 32 + ".b"}).status_code == 401
    assert alice.post("/api/admin/invites", json={}).status_code == 409


def test_auto_create_is_user_and_groups_sync_the_role(proxy_app):
    bob = via_proxy(proxy_app, "bob", **{"Remote-Name": "Bob B"})
    me = bob.get("/api/me").json()
    assert me["role"] == "user" and me["display_name"] == "Bob B" and me["auth_source"] == "proxy"
    promoted = via_proxy(proxy_app, "bob", **{"Remote-Groups": "kidney-admins, family"})
    assert promoted.get("/api/me").json()["role"] == "admin"
    assert via_proxy(proxy_app, "bob", **{"Remote-Groups": "family"}).get("/api/me").json()["role"] == "user"
    alice = via_proxy(proxy_app, "alice", **{"Remote-Groups": "kidney-admins"})
    events = alice.get("/api/admin/audit").json()["events"]
    assert [e["action"] for e in events].count("user.role_changed") == 2
    assert "user.created_by_proxy" in [e["action"] for e in events]


def test_unknown_identities_need_the_admin_without_auto_create(tmp_path, foods_json, caplog):
    settings = proxy_settings(tmp_path, foods_json)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), TestClient(create_app(settings), client=PROXY) as boot:
        code = setup_code_from_logs(caplog)
        assert via_proxy(boot.app, "alice").post("/api/auth/setup", json={"code": code}).status_code == 200
        carol = via_proxy(boot.app, "carol@example.org")
        r = carol.get("/api/me")
        assert r.status_code == 403 and "carol@example.org" in r.json()["detail"]
        alice = via_proxy(boot.app, "alice")
        r = alice.post("/api/admin/users", json={"username": "carol@example.org"})
        assert r.status_code == 201 and r.json()["setup_url"] is None
        assert carol.get("/api/me").json()["role"] == "user"  # no admin group configured: never admin


def test_proxy_names_never_link_to_local_accounts(proxy_app):
    conn = sqlite3.connect(proxy_app.state.settings.db_path)
    conn.execute(
        """INSERT INTO users (username, username_norm, role, status, auth_source, password_hash, created_at, updated_at)
           VALUES ('dave', 'dave', 'admin', 'active', 'local', 'x', 'n', 'n')"""
    )
    conn.commit()
    r = via_proxy(proxy_app, "DAVE").get("/api/me")
    assert r.status_code == 403
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'proxy.username_conflict'").fetchone()[0] == 1
    conn.close()


def test_proxy_mode_needs_its_secret_and_refuses_wide_trust(tmp_path):
    base = {"DATA_DIR": str(tmp_path), "AUTH_MODE": "proxy", "TRUSTED_PROXY_USER_HEADER": "Remote-User"}
    with pytest.raises(ConfigError, match="TRUSTED_PROXY_SECRET_FILE"):
        load_settings(base)
    with pytest.raises(ConfigError, match="0.0.0.0/0"):
        load_settings({**base, "TRUSTED_PROXY_SECRET": PROXY_SECRET, "TRUSTED_PROXIES": "0.0.0.0/0"})
    assert load_settings({**base, "TRUSTED_PROXY_SECRET_OPTIONAL": "true"}).auth_mode == "proxy"


def test_switching_auth_mode_signs_everybody_out(tmp_path, foods_json):
    local = make_settings(tmp_path, foods_json)
    with TestClient(create_app(local)) as c:
        sign_in(c)
        conn = sqlite3.connect(local.db_path)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        conn.close()
    with TestClient(create_app(proxy_settings(tmp_path, foods_json))):
        conn = sqlite3.connect(local.db_path)
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT value FROM meta WHERE key = 'auth_mode'").fetchone()[0] == "proxy"
        conn.close()


# --------------------------------------------------------------------------- #
# AUTH_MODE=none
# --------------------------------------------------------------------------- #


@pytest.fixture
def none_client(tmp_path, foods_json):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data", foods_json=foods_json, auth_mode="none"))) as c:
        yield c


def test_none_mode_is_user_one_with_a_banner_flag(none_client):
    status = none_client.get("/api/auth/status").json()
    assert status["no_login"] is True and status["auth_mode"] == "none" and status["setup_required"] is False
    assert status["user"]["id"] == 1 and status["user"]["role"] == "admin"
    assert none_client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 1}).status_code == 201
    assert none_client.get("/api/profile").status_code == 200
    conn = sqlite3.connect(none_client.app.state.settings.db_path)
    assert conn.execute("SELECT user_id FROM log_entries").fetchall() == [(1,)]
    conn.close()


def test_none_mode_hides_accounts_and_refuses_shared_key_writes(none_client):
    for method, path, body in (
        ("POST", "/api/auth/login", {"username": "a", "password": "b"}),
        ("POST", "/api/auth/setup", {"code": "x"}),
        ("POST", "/api/auth/register", {"username": "a", "password": "b"}),
        ("GET", "/api/admin/users", None),
        ("POST", "/api/admin/invites", {}),
    ):
        assert none_client.request(method, path, json=body).status_code == 404, path
    r = none_client.put("/api/admin/keys/usda", json={"api_key": "a-shared-key-for-everyone-1234"})
    assert r.status_code == 403
    assert none_client.request("DELETE", "/api/admin/keys/usda").status_code == 403
    assert none_client.get("/api/admin/settings").status_code == 200


def test_data_from_none_mode_stays_with_whoever_sets_up_local_mode(tmp_path, foods_json, caplog):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, auth_mode="none")
    with TestClient(create_app(settings)) as c:
        c.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 1})
    local = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), TestClient(create_app(local)) as c:
        code = setup_code_from_logs(caplog)
        assert c.post("/api/auth/setup", json={"code": code, "username": "mum", "password": ADMIN_PASSWORD}).status_code == 200
        assert len(c.get("/api/log", params={"date": DAY}).json()["entries"]) == 1


# --------------------------------------------------------------------------- #
# Secrets are never echoed (§9 N4)
# --------------------------------------------------------------------------- #

SECRET = "Zebra-Secret-Value-9921-xyz"


def test_validation_errors_never_echo_secrets(two_clients, caplog):
    admin, sam = two_clients
    anon = TestClient(admin.app, base_url=HTTPS_URL)
    too_long = SECRET * 60
    attempts = [
        (anon, "POST", "/api/auth/login", {"username": "admin", "password": too_long}),
        (anon, "POST", "/api/auth/login", {"username": SECRET * 20, "password": 5}),
        (anon, "POST", "/api/auth/setup", {"code": too_long}),
        (anon, "POST", "/api/auth/register", {"token": too_long, "username": "a", "password": SECRET}),
        (anon, "POST", "/api/auth/reset", {"token": SECRET, "password": too_long}),
        (sam, "POST", "/api/auth/reauth", {"password": too_long}),
        (sam, "POST", "/api/me/password", {"current_password": SECRET, "new_password": too_long}),
        (sam, "PUT", "/api/me/keys/usda", {"api_key": f"has space {SECRET}"}),
        (sam, "PUT", "/api/me/keys/usda", {"api_key": too_long}),
        (admin, "PUT", "/api/admin/keys/usda", {"api_key": f"{SECRET}\t"}),
        (sam, "DELETE", "/api/me", {"password": too_long, "confirm": "DELETE"}),
    ]
    with caplog.at_level(logging.DEBUG):
        for client, method, path, body in attempts:
            r = client.request(method, path, json=body)
            assert r.status_code in (400, 403, 404, 409), (path, r.status_code)
            assert SECRET not in r.text, (path, r.text[:300])
    assert SECRET not in caplog.text


def test_keys_are_write_only_everywhere(two_clients, caplog, monkeypatch):
    import app.foods as foods_module
    import httpx2

    admin, sam = two_clients
    own_key = "OWNKEY-" + SECRET
    shared_key = "SHAREDKEY-" + SECRET
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("x-api-key", ""))
        return httpx2.Response(200, json={"foods": []})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    bodies = []
    with caplog.at_level(logging.DEBUG):
        r = sam.put("/api/me/keys/usda", json={"api_key": own_key, "test": True})
        assert r.status_code == 200 and r.json()["test"] == "ok" and r.json()["own"]["last4"] == own_key[-4:]
        bodies.append(r.text)
        r = admin.put("/api/admin/keys/usda", json={"api_key": shared_key})
        assert r.status_code == 200 and r.json()["shared"]["set"] is True
        bodies.append(r.text)
        for client, path in ((sam, "/api/me/keys"), (admin, "/api/admin/keys"), (admin, "/api/admin/about"),
                             (admin, "/api/admin/audit"), (sam, "/api/me/activity"), (admin, "/api/admin/settings")):
            r = client.get(path)
            assert r.status_code == 200
            bodies.append(r.text)
        sam.get("/api/foods/usda/search", params={"q": "oats"})
        admin.get("/api/foods/usda/search", params={"q": "oats"})
        bodies.append(sam.get("/api/me/export.zip").content.decode("latin-1"))
    assert seen[-2:] == [own_key, shared_key]  # own key wins for sam; the admin uses the shared key
    for body in bodies:
        assert SECRET not in body
    assert SECRET not in caplog.text
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    dump = "\n".join(conn.iterdump())
    assert SECRET not in dump  # encrypted at rest
    conn.close()
