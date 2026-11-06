"""Intervening disconnects, reconnects and account changes win over an old device sync.

Provider hooks make the change during the fetch/refresh, with separate real database connections.
The route, encrypted credentials, storage and transaction boundaries are the production ones.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.db import connect
from app.devices import store
from app.devices.base import ActivityDay, FetchResult, ProviderError, Reading, TokenSet, Workout
from conftest import HTTPS_URL, add_user, make_settings, signed_in_client
from devices_support import env, whoop_env


@pytest.fixture(params=["withings", "whoop"])
def device(request, tmp_path: Path, foods_json: Path, monkeypatch):
    settings = make_settings(tmp_path, foods_json, public_url=HTTPS_URL, withings=env(), whoop=whoop_env())
    with signed_in_client(settings, base_url=HTTPS_URL) as admin:
        admin.patch("/api/admin/settings", json={"devices.enabled": True})
        client = add_user(admin, base_url=HTTPS_URL)
        user_id = client.get("/api/me").json()["id"]
        app = client.app
        kind = request.param
        provider = app.state.devices.provider(kind)
        tokens = TokenSet("old-access", "old-refresh", 3600, "old-account", "test")
        with connect(settings.db_path) as conn:
            store.connect(conn, app.state.keyring, user_id, kind, tokens)
        day = date.today().isoformat()
        result = FetchResult([Reading("weight", "weight:one", day, "07:00", kg=72)] if kind == "withings" else [], "old-cursor",
                             days=[ActivityDay("cycle:one", day, day + "T00:00:00Z", False, kcal=1800)] if kind == "whoop" else [],
                             workouts=[Workout("workout:one", day, "08:00", "08:30", 30, "Walking", kcal=100)] if kind == "whoop" else [])
        monkeypatch.setattr(provider, "fetch", lambda *_a, **_kw: result)
        monkeypatch.setattr(provider, "refresh", lambda *_a: TokenSet("rotated-access", "rotated-refresh", 3600, "old-account", "test"))
        monkeypatch.setattr(provider, "revoke", lambda *_a, **_kw: True)
        yield client, provider, result, user_id


def tables(client) -> dict[str, int]:
    with connect(client.app.state.settings.db_path) as conn:
        return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("weights", "blood_pressures", "activity_days", "activity_workouts", "device_imports")}


@pytest.mark.parametrize("delete_readings", [False, True])
def test_disconnect_during_fetch_does_not_import_afterward(device, monkeypatch, delete_readings):
    client, provider, result, _ = device

    def fetch(*_a, **_kw):
        removed = client.delete(f"/api/devices/{provider.id}", params={"delete_readings": str(delete_readings).lower()})
        assert removed.status_code == 200
        return result

    monkeypatch.setattr(provider, "fetch", fetch)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.status_code == 404
    assert "disconnected while syncing" in response.json()["detail"]
    assert not any(tables(client).values()), "a disconnected sync must not add readings, activity or ledger rows"


def test_reconnect_during_fetch_does_not_import_the_previous_accounts_data(device, monkeypatch):
    client, provider, result, user_id = device

    def fetch(*_a, **_kw):
        with connect(client.app.state.settings.db_path) as conn:
            store.connect(conn, client.app.state.keyring, user_id, provider.id,
                          TokenSet("new-access", "new-refresh", 3600, "new-account", "test"))
        return result

    monkeypatch.setattr(provider, "fetch", fetch)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.json()["error"] == "connection_changed"
    assert not any(tables(client).values())
    with connect(client.app.state.settings.db_path) as conn:
        row = store.connection(conn, user_id, provider.id)
        assert row["sync_cursor"] is None
        assert store.load_tokens(client.app.state.keyring, row) == ("new-access", "new-refresh")


def test_old_auth_failure_does_not_erase_a_new_connections_tokens(device, monkeypatch):
    client, provider, _, user_id = device

    def fetch(*_a, **_kw):
        with connect(client.app.state.settings.db_path) as conn:
            store.connect(conn, client.app.state.keyring, user_id, provider.id,
                          TokenSet("new-access", "new-refresh", 3600, "new-account", "test"))
        raise ProviderError("auth")

    monkeypatch.setattr(provider, "fetch", fetch)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.json()["error"] == "connection_changed"
    with connect(client.app.state.settings.db_path) as conn:
        row = store.connection(conn, user_id, provider.id)
        assert row["status"] == "active" and row["last_error"] is None
        assert store.load_tokens(client.app.state.keyring, row) == ("new-access", "new-refresh")


def test_old_refresh_does_not_replace_new_credentials(device, monkeypatch):
    client, provider, _, user_id = device
    with connect(client.app.state.settings.db_path) as conn:
        conn.execute("UPDATE device_connections SET access_expires_at = NULL")

    def refresh(*_a):
        with connect(client.app.state.settings.db_path) as conn:
            store.connect(conn, client.app.state.keyring, user_id, provider.id,
                          TokenSet("new-access", "new-refresh", 3600, "new-account", "test"))
        return TokenSet("old-rotated-access", "old-rotated-refresh", 3600, "old-account", "test")

    monkeypatch.setattr(provider, "refresh", refresh)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.json()["error"] == "connection_changed"
    assert not any(tables(client).values())
    with connect(client.app.state.settings.db_path) as conn:
        assert store.load_tokens(client.app.state.keyring, store.connection(conn, user_id, provider.id)) == ("new-access", "new-refresh")


@pytest.mark.parametrize("change", ["disable", "test_account", "switch_off"])
def test_account_or_server_change_during_fetch_stops_import(device, monkeypatch, change):
    client, provider, result, user_id = device

    def fetch(*_a, **_kw):
        with connect(client.app.state.settings.db_path) as conn:
            if change == "switch_off":
                client.app.state.settings_store.set_instance(conn, "devices.enabled", False, updated_by=user_id)
            elif change == "disable":
                conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (user_id,))
            else:
                conn.execute("UPDATE users SET is_test_account = 1 WHERE id = ?", (user_id,))
        return result

    monkeypatch.setattr(provider, "fetch", fetch)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.json()["error"] == "connection_changed"
    assert not any(tables(client).values())


def test_a_failed_sync_marker_rolls_back_imports_and_ledger_too(device, monkeypatch):
    client, provider, _, _ = device

    def fail(*_a, **_kw):
        raise RuntimeError("cursor update failed")

    monkeypatch.setattr(store, "mark", fail)
    with pytest.raises(RuntimeError, match="cursor update failed"):
        client.post(f"/api/devices/{provider.id}/sync")
    assert not any(tables(client).values()), "one fetched result must commit or roll back together"


def test_a_new_sign_in_to_the_same_provider_account_also_cancels_old_results(device, monkeypatch):
    client, provider, result, user_id = device

    def fetch(*_a, **_kw):
        with connect(client.app.state.settings.db_path) as conn:
            store.connect(conn, client.app.state.keyring, user_id, provider.id,
                          TokenSet("new-access", "new-refresh", 3600, "old-account", "test"))
        return result

    monkeypatch.setattr(provider, "fetch", fetch)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.json()["error"] == "connection_changed"
    assert not any(tables(client).values())


def test_a_deleted_user_during_fetch_adds_nothing_and_returns_404(device, monkeypatch):
    client, provider, result, user_id = device

    def fetch(*_a, **_kw):
        with connect(client.app.state.settings.db_path) as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return result

    monkeypatch.setattr(provider, "fetch", fetch)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.status_code == 404
    assert not any(tables(client).values())


def test_refresh_after_disconnect_does_not_continue_fetching(device, monkeypatch):
    client, provider, _, user_id = device
    with connect(client.app.state.settings.db_path) as conn:
        conn.execute("UPDATE device_connections SET access_expires_at = NULL WHERE user_id = ?", (user_id,))

    def refresh(*_a):
        assert client.delete(f"/api/devices/{provider.id}").status_code == 200
        return TokenSet("rotated-access", "rotated-refresh", 3600, "old-account", "test")

    def fetch(*_a, **_kw):
        pytest.fail("a cancelled refresh must never continue to fetch")

    monkeypatch.setattr(provider, "refresh", refresh)
    monkeypatch.setattr(provider, "fetch", fetch)
    # Disconnect revokes separately; do not make revocation call this refresh hook recursively.
    monkeypatch.setattr("app.devices.api._revoke", lambda *_a, **_kw: True)
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.status_code == 404
    assert not any(tables(client).values())


def test_ordinary_sync_commits_all_rows_ledger_and_cursor_together(device):
    client, provider, _, user_id = device
    response = client.post(f"/api/devices/{provider.id}/sync")
    assert response.status_code == 200 and response.json()["error"] is None
    expected = {"weights": 1, "readings": 0, "days": 0, "workouts": 0} if provider.id == "withings" else {
        "weights": 0, "readings": 0, "days": 1, "workouts": 1}
    assert response.json()["result"]["added"] == expected
    with connect(client.app.state.settings.db_path) as conn:
        assert store.connection(conn, user_id, provider.id)["sync_cursor"] == "old-cursor"
        assert conn.execute("SELECT COUNT(*) FROM device_imports WHERE user_id = ?", (user_id,)).fetchone()[0] == sum(expected.values())
