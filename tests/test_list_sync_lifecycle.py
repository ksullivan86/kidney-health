"""Changes made while a list app answers must not be overwritten by its old reply."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db import connect
from app.list_sync.apps import ListAppError, ListRef
from conftest import DAY, HTTPS_URL, add_user, make_settings, signed_in_client
from test_list_sync import plan, set_up


@pytest.fixture
def linked(tmp_path, foods_json, monkeypatch):
    settings = make_settings(tmp_path, foods_json)
    with signed_in_client(settings, base_url=HTTPS_URL) as admin:
        admin.patch("/api/admin/settings", json={"lists.sync_enabled": True})
        user = add_user(admin, base_url=HTTPS_URL)
        set_up(user, list_id="1", list_name="Old list")
        food = plan(user, "apple")
        fake = SimpleNamespace(test=lambda: [ListRef("1", "Old list")], send=lambda *_a: 1)
        monkeypatch.setattr("app.list_sync.api._client", lambda *_a: fake)
        yield admin, user, fake, food


def change(admin, user, kind):
    if kind == "remove":
        assert user.delete("/api/list-sync").status_code == 204
    elif kind == "switch_off":
        assert admin.patch("/api/admin/settings", json={"lists.sync_enabled": False}).status_code == 200
    elif kind == "list":
        assert user.put("/api/list-sync", json={"app": "grocy", "base_url": "https://lists.example.com", "list_id": "9", "list_name": "New list"}).status_code == 200
    elif kind == "key":
        set_up(user, key="new-key", list_id="9", list_name="New list")
    else:
        set_up(user, url="https://new.example.com", list_id="9", list_name="New list")


@pytest.mark.parametrize("kind", ["remove", "switch_off", "list", "key", "address"])
def test_old_test_result_does_not_overwrite_new_configuration(linked, kind):
    admin, user, fake, _ = linked

    def test():
        change(admin, user, kind)
        return [ListRef("1", "Old server list")]

    fake.test = test
    reply = user.post("/api/list-sync/test")
    assert reply.status_code == 409
    assert reply.json()["reason"] == "connection_changed"
    if kind not in ("remove", "switch_off"):
        row = user.get("/api/list-sync").json()["connection"]
        assert row["list_id"] == "9" and row["list_name"] == "New list"
        assert row["last_test_at"] is None


@pytest.mark.parametrize("kind", ["remove", "switch_off", "list", "key", "address"])
def test_old_send_does_not_mark_the_new_list_as_sent_and_reports_uncertainty(linked, kind):
    admin, user, fake, food = linked

    def send(*_a):
        change(admin, user, kind)
        return 1

    fake.send = send
    reply = user.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [food]})
    assert reply.status_code == 409
    assert reply.json()["reason"] == "connection_changed" and reply.json()["sent"] == 1
    assert "before sending again" in reply.json()["detail"]
    if kind not in ("remove", "switch_off"):
        row = user.get("/api/list-sync").json()["connection"]
        assert row["last_sent_at"] is None and row["last_sent_count"] is None
    with connect(user.app.state.settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'list_sync.sent'").fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["list", "key", "address"])
def test_reconfiguring_a_list_clears_the_previous_lists_receipt(linked, kind):
    admin, user, _, food = linked
    assert user.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [food]}).status_code == 200
    change(admin, user, kind)
    row = user.get("/api/list-sync").json()["connection"]
    assert row["last_sent_at"] is None and row["last_sent_count"] is None


def test_current_test_and_send_still_update_the_current_list(linked):
    _, user, _, food = linked
    test = user.post("/api/list-sync/test")
    assert test.status_code == 200 and test.json()["ok"] is True
    send = user.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [food]})
    assert send.status_code == 200 and send.json()["sent"] == 1
    assert send.json()["connection"]["last_sent_count"] == 1


def test_an_old_test_error_is_not_recorded_on_the_new_connection(linked):
    admin, user, fake, _ = linked

    def test():
        change(admin, user, "address")
        raise ListAppError("auth")

    fake.test = test
    assert user.post("/api/list-sync/test").status_code == 409
    assert user.get("/api/list-sync").json()["connection"]["last_test_error"] is None


def test_a_partial_old_send_reports_confirmed_items_without_marking_the_new_list(linked):
    admin, user, fake, food = linked

    def send(*_a):
        change(admin, user, "address")
        error = ListAppError("timeout")
        error.sent = 1
        raise error

    fake.send = send
    response = user.post("/api/list-sync/send", json={"start": DAY, "end": DAY, "food_ids": [food]})
    assert response.status_code == 409 and response.json()["sent"] == 1
    assert "without a reply" in response.json()["detail"]
    assert user.get("/api/list-sync").json()["connection"]["last_sent_at"] is None


@pytest.mark.parametrize("operation", ["test", "send"])
def test_deleted_account_during_a_request_returns_a_conflict_without_a_foreign_key_error(linked, operation):
    _, user, fake, food = linked
    user_id = user.get("/api/me").json()["id"]

    def deleted(*_a):
        with connect(user.app.state.settings.db_path) as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return [] if operation == "test" else 1

    setattr(fake, operation, deleted)
    body = {} if operation == "test" else {"start": DAY, "end": DAY, "food_ids": [food]}
    response = user.post(f"/api/list-sync/{operation}", json=body)
    assert response.status_code == 409 and response.json()["reason"] == "connection_changed"
