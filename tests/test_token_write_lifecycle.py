"""A bearer write must still be authorized when its write transaction starts."""
from __future__ import annotations

import pytest

from app import foods, push as phone
from app.auth import api_tokens
from app.mcp import preference_tool
from conftest import DAY
from test_api_tokens import audit_rows, db, make, switch
from test_mcp import rpc
from test_mcp_write import usda_admin  # noqa: F401 - shared fixture
from test_push import make_device, push, push_switch, reading, weight


def end_access(client, token, change, family):
    if change == "revoke":
        response = client.delete(f"/api/me/tokens/{token['id']}")
        assert response.status_code == 204, response.text
    elif change == "switch":
        (switch if family == "assistant" else push_switch)(client, False)
    else:
        with db(client) as conn:
            if change == "expire":
                conn.execute("UPDATE api_tokens SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?", (token["id"],))
            elif change == "scope":
                conn.execute("UPDATE api_tokens SET scopes = ? WHERE id = ?", (api_tokens.READ, token["id"]))
            elif change == "password":
                conn.execute("UPDATE users SET must_change_password = 1 WHERE id = 1")
            elif change == "disabled":
                conn.execute("UPDATE users SET status = 'disabled' WHERE id = 1")
            elif change == "account_type":
                conn.execute("UPDATE users SET auth_source = 'proxy' WHERE id = 1")
            elif change == "delete_token":
                conn.execute("DELETE FROM api_tokens WHERE id = ?", (token["id"],))
            elif change == "delete_owner":
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("DELETE FROM users WHERE id = 1")
            else:
                raise AssertionError(change)


@pytest.mark.parametrize("tool", ["log_food", "save_recipe", "set_food_preference", "food_preference", "push"])
@pytest.mark.parametrize("change", ["revoke", "expire", "scope", "switch", "password", "disabled", "account_type",
                                   "delete_token", "delete_owner"])
def test_access_ended_while_request_waited_saves_nothing(usda_admin, monkeypatch, tool, change):  # noqa: F811
    client = usda_admin
    family = "device" if tool == "push" else "assistant"
    push_switch(client)
    token = make_device(client) if tool == "push" else make(client, can_log=True, can_prefs=True)
    changed = False

    def stop_access():
        nonlocal changed
        assert not changed
        end_access(client, token, change, family)
        changed = True

    if tool == "push":
        original_read = phone._read_capped

        async def read(request):
            raw = await original_read(request)
            stop_access()  # authentication happened before reading the request body
            return raw

        monkeypatch.setattr(phone, "_read_capped", read)
        response = push(client.app, token["token"], {"weights": [weight()], "readings": [reading()]})
    elif tool in ("set_food_preference", "food_preference"):
        original_check = preference_tool.check_target

        def check(call, args):
            result = original_check(call, args)
            if not changed:
                stop_access()
            return result

        monkeypatch.setattr(preference_tool, "check_target", check)
        target = {"category": "Fruits"} if tool == "set_food_preference" else {
            "food_id": client.get("/api/foods", params={"q": "banana"}).json()["foods"][0]["id"]}
        response = rpc(client.app, token["token"], "tools/call", {
            "name": "set_food_preference", "arguments": {**target, "preference": "like", "request_key": "lifecycle-test"}})
    else:
        original_client = foods.usda_client

        def lookup():
            stop_access()  # the tool authenticated, then needed a food not yet saved in the app
            return original_client()

        monkeypatch.setattr(foods, "usda_client", lookup)
        item = {"food": "nectar", "fdc_id": 2000001}
        args = ({"items": [item], "meal": "lunch", "date": DAY} if tool == "log_food" else
                {"ingredients": [item], "name": "Nectar recipe", "servings": 2})
        response = rpc(client.app, token["token"], "tools/call", {
            "name": tool, "arguments": {**args, "request_key": "lifecycle-test"}})

    assert changed
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": api_tokens.DEVICE_DENIED if tool == "push" else api_tokens.DENIED}
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    with db(client) as conn:
        for table in ("log_entries", "meal_templates", "assistant_request_keys", "food_preferences", "weights", "blood_pressures"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert conn.execute("SELECT COUNT(*) FROM foods WHERE fdc_id = 2000001").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM user_settings WHERE key = 'guidance'").fetchone()[0] == 0
    for action in ("assistant.food_logged", "assistant.recipe_saved", "assistant.preference_set"):
        assert audit_rows(client, action) == []
