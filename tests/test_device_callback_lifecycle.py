"""OAuth replies cannot reinstall a disconnected or replaced device connection."""
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app.devices import store
from app.main import create_app
from conftest import HTTPS_URL, TestClient, add_user, make_settings, setup_code_from_logs
from devices_support import FakeWhoop, FakeWithings, attach, attach_whoop, env, whoop_env
from test_auth_modes import PROXY, proxy_settings, via_proxy
from test_connected_devices import db, uid
from test_connected_devices import dev as withings_dev  # noqa: F401 - shared fixture
from test_whoop import dev as whoop_dev  # noqa: F401 - shared fixture


def start(client, provider):
    response = client.post(f"/api/devices/{provider}/start")
    assert response.status_code == 200, response.text
    return {key: values[0] for key, values in parse_qs(urlsplit(response.json()["url"]).query).items()}


def callback(client, provider, fake, flow):
    return client.get(f"/api/devices/{provider}/callback", params={
        "state": flow["state"], "code": fake.issue_code(flow["redirect_uri"]),
    }, follow_redirects=False)


def token_stamp(row):
    return hashlib.sha256(bytes(row["tokens_enc"])).hexdigest()


@pytest.mark.parametrize("provider", ["withings", "whoop"])
@pytest.mark.parametrize("change", ["disconnect_before", "disconnect_during", "switch", "replace", "disabled", "logout",
                                   "deleted_user", "password", "expired", "idle", "normal", "metadata"])
def test_callback_only_installs_for_the_still_current_connection_and_person(request, monkeypatch, provider, change):
    admin, fake = request.getfixturevalue(f"{provider}_dev")
    client = add_user(admin, "member") if change in ("disabled", "deleted_user", "password") else admin
    person = uid(client)
    old_row = change in ("disconnect_before", "disconnect_during", "replace", "metadata")
    if old_row:
        first = callback(client, provider, fake, start(client, provider))
        assert first.status_code == 303 and "/connected/" in first.headers["location"]
        with db(client) as conn:
            conn.execute("UPDATE device_connections SET status = ? WHERE user_id = ? AND provider = ?",
                         (store.STATUS_NEEDS_RECONNECT, person, provider))
    flow = start(client, provider)
    replacement = start(client, provider) if change == "replace" else None
    if change == "disconnect_before":
        assert client.delete(f"/api/devices/{provider}").status_code == 200
    live_provider = client.app.state.devices.provider(provider)
    exchange = live_provider.exchange
    acted = False
    expected_tokens = None

    def finish_exchange(**kwargs):
        nonlocal acted, expected_tokens
        tokens = exchange(**kwargs)
        if acted:
            return tokens
        acted = True
        if change == "disconnect_during":
            response = client.delete(f"/api/devices/{provider}")
            assert response.status_code == 200, response.text
        elif change == "switch":
            assert admin.patch("/api/admin/settings", json={"devices.enabled": False}).status_code == 200
        elif change == "replace":
            response = callback(client, provider, fake, replacement)
            assert response.status_code == 303 and "/connected/" in response.headers["location"]
            with db(client) as conn:
                expected_tokens = token_stamp(store.connection(conn, person, provider))
        elif change == "disabled":
            response = admin.patch(f"/api/admin/users/{person}", json={"status": "disabled"})
            assert response.status_code == 200, response.text
        elif change == "logout":
            assert client.post("/api/auth/logout").status_code == 200
        elif change == "deleted_user":
            response = admin.request("DELETE", f"/api/admin/users/{person}", json={"confirm_username": "member"})
            assert response.status_code == 204, response.text
            replacement_user = add_user(admin, "replacement")
            assert uid(replacement_user) != person  # account ids are not reused
        elif change == "password":
            response = admin.patch(f"/api/admin/users/{person}", json={"must_change_password": True})
            assert response.status_code == 200, response.text
        elif change in ("expired", "idle"):
            field = "expires_at" if change == "expired" else "last_seen_at"
            with db(client) as conn:
                conn.execute(f"UPDATE sessions SET {field} = '2000-01-01T00:00:00.000000Z' WHERE user_id = ?", (person,))
        elif change == "metadata":
            with db(client) as conn:
                conn.execute("UPDATE device_connections SET last_sync_at = '2026-01-01', last_error = 'network', "
                             "updated_at = '2026-01-01' WHERE user_id = ? AND provider = ?", (person, provider))
        return tokens

    monkeypatch.setattr(live_provider, "exchange", finish_exchange)
    response = callback(client, provider, fake, flow)
    with db(client) as conn:
        row = store.connection(conn, person, provider)
        if change in ("normal", "metadata"):
            assert response.status_code == 303 and "/connected/" in response.headers["location"]
            assert row["status"] == store.STATUS_ACTIVE
        elif change == "replace":
            assert response.status_code == 303 and "/connected/" not in response.headers["location"], response.text
            assert token_stamp(row) == expected_tokens
        else:
            assert response.status_code != 303 or "/connected/" not in response.headers["location"]
            assert row is None
        connected = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'device.connected'").fetchone()[0]
        assert connected == int(old_row) + int(change in ("normal", "metadata", "replace"))


@pytest.mark.parametrize("provider", ["withings", "whoop"])
@pytest.mark.parametrize("mode", ["none", "proxy"])
def test_callback_without_a_local_session(tmp_path, foods_json, caplog, provider, mode):
    options = {"public_url": HTTPS_URL, provider: env() if provider == "withings" else whoop_env()}
    settings = (proxy_settings(tmp_path, foods_json, **options) if mode == "proxy"
                else make_settings(tmp_path, foods_json, auth_mode="none", **options))
    with TestClient(create_app(settings), base_url=HTTPS_URL, client=PROXY) as boot:
        client = via_proxy(boot.app, "alice") if mode == "proxy" else boot
        if mode == "proxy":
            response = client.post("/api/auth/setup", json={"code": setup_code_from_logs(caplog)})
            assert response.status_code == 200, response.text
        assert client.patch("/api/admin/settings", json={"devices.enabled": True}).status_code == 200
        fake = attach(client.app, FakeWithings()) if provider == "withings" else attach_whoop(client.app, FakeWhoop())
        response = callback(client, provider, fake, start(client, provider))
        assert response.status_code == 303 and "/connected/" in response.headers["location"]
        with db(client) as conn:
            assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
            assert store.connection(conn, uid(client), provider)["status"] == store.STATUS_ACTIVE
