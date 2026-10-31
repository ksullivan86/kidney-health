"""Device tokens (design note 12 §4.1; ``app/auth/api_tokens.py``): the second token family, ``khd_`` with the one scope
``body:write``, in the same table as the assistant tokens.

Covered: the family's prefix and scope, that the families do not mix at either surface (``/mcp`` and ``/push/v1/body``) and
that both refusals are throttled, the per-family limit of five, the list filter, that a device token's scopes are not the person's
choice, the recent sign-in, ``revoke_all`` ending both families (password change, the admin's "revoke tokens"), the audit family,
the instance switch, and "Delete what it sent" (``DELETE /api/me/tokens/{id}/body-rows``) with the ``api_token_id`` links of
schema step 19. The route itself is in ``tests/test_push.py``.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from app.auth import api_tokens
from conftest import ADMIN_PASSWORD, USER_PASSWORD, TestClient
from test_api_tokens import audit_rows, bearer, db, make, switch
from test_push import AT, DAY, bare, counts, make_device, push, push_switch, reading, rows, weight

DEVICE_RE = re.compile(r"^khd_[A-Za-z0-9_-]{43}$")
GENERIC = {"detail": api_tokens.DEVICE_DENIED}


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    push_switch(client, True)
    switch(client, True)
    return client


@pytest.fixture
def pair(two_clients: tuple[TestClient, TestClient]) -> tuple[TestClient, TestClient]:
    admin, sam = two_clients
    push_switch(admin, True)
    switch(admin, True)
    return admin, sam


def mcp(app: Any, token: str) -> Any:
    return bare(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers={"Authorization": f"Bearer {token}"})


def person_id(client: TestClient) -> int:
    return int(client.get("/api/me").json()["id"])


# --------------------------------------------------------------------------- the family


def test_a_device_token_has_the_khd_prefix_the_one_scope_and_the_same_item_shape(admin):
    created = make_device(admin, "  Morning\tweight ")
    token = created["token"]
    assert DEVICE_RE.match(token) and not token.startswith("kha_")
    assert created["name"] == "Morning weight" and created["prefix"] == token[:12] and created["prefix"].startswith("khd_")
    assert created["scopes"] == ["body:write"] and created["state"] == "active"
    assert created["sent"] == {"weights": 0, "readings": 0}
    assert {"id", "name", "prefix", "scopes", "created_at", "last_used_at", "expires_at", "revoked_at", "state"} <= set(created)
    conn = db(admin)
    try:
        row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (created["id"],)).fetchone()
        assert row["scopes"] == "body:write" and row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in repr(tuple(row))  # hash only, as for assistant tokens
    finally:
        conn.close()
    assert push(admin.app, token, {"weights": [weight()]}).status_code == 200


def test_the_assistant_item_shape_is_unchanged_and_the_default_family_is_assistant(admin):
    plain = make(admin)
    assert plain["token"].startswith("kha_") and "sent" not in plain and plain["scopes"] == ["assistant:read"]
    listed = admin.get("/api/me/tokens").json()
    assert listed["family"] == "assistant" and [t["id"] for t in listed["tokens"]] == [plain["id"]]
    assert all("sent" not in t for t in listed["tokens"])
    assert admin.post("/api/me/tokens", json={"name": "x", "family": "assistant"}).status_code == 201


def test_the_list_takes_a_family_and_lists_only_that_family(admin):
    a1, a2 = make(admin, "A one"), make(admin, "A two")
    d1, d2 = make_device(admin, "D one"), make_device(admin, "D two")
    assistant = admin.get("/api/me/tokens").json()
    explicit = admin.get("/api/me/tokens?family=assistant").json()
    device = admin.get("/api/me/tokens?family=device").json()
    assert assistant == explicit and assistant["family"] == "assistant" and device["family"] == "device"
    assert [t["name"] for t in assistant["tokens"]] == ["A two", "A one"]
    assert [t["name"] for t in device["tokens"]] == ["D two", "D one"]
    assert {t["id"] for t in assistant["tokens"]} == {a1["id"], a2["id"]} and {t["id"] for t in device["tokens"]} == {d1["id"], d2["id"]}
    for doc in (assistant, device):
        assert doc["enabled"] is True and doc["max_active"] == 5 and doc["expiry_days"] == [30, 90, 365] and doc["default_expiry_days"] == 90
    dump = str(device)
    assert d1["token"] not in dump and hashlib.sha256(d1["token"].encode()).hexdigest() not in dump  # write-only, as ever
    for bad in ("", "all", "Device", "devices", "assistant,device"):
        r = admin.get("/api/me/tokens", params={"family": bad})
        assert r.status_code == 400 and r.json().get("field") == "family", bad


def test_a_device_tokens_scopes_are_not_the_persons_choice(admin):
    for body in ({"scopes": ["body:write"]}, {"scopes": ["assistant:read"]}, {"scope": "body:write"}, {"can_log": True},
                 {"can_prefs": True}, {"can_log": True, "can_prefs": True}, {"can_prefs": "yes"},
                 {"can_log": "yes"}, {"family": "phone"}, {"family": None}, {"family": ["device"]}, {"family": "DEVICE"}):
        r = admin.post("/api/me/tokens", json={"name": "x", "family": "device", **body})
        assert r.status_code == 400, body
    assert admin.get("/api/me/tokens?family=device").json()["tokens"] == []
    ok = admin.post("/api/me/tokens", json={"name": "x", "family": "device", "can_log": False})
    assert ok.status_code == 201 and ok.json()["scopes"] == ["body:write"]
    assert api_tokens.scopes_for(True) == ("assistant:read", "assistant:log")  # the assistant's choice is untouched


def test_scopes_of_the_two_families_never_mix():
    p = api_tokens.parse_scopes
    assert p("body:write") == ("body:write",)
    assert p("body:write admin") == ("body:write",)
    assert p("assistant:log") == ("assistant:read", "assistant:log")  # log implies read; nothing implies body:write
    assert p("assistant:read body:write") == () and p("assistant:log body:write") == ()  # a row that mixes them grants nothing
    assert p("assistant:prefs body:write") == () and p("body:write assistant:prefs assistant:log") == ()  # prefs is an assistant scope
    assert p("body:read body:delete") == ()
    assert api_tokens.family_of_scopes("body:write") == "device" and api_tokens.family_of_scopes("assistant:read") == "assistant"
    assert api_tokens.family_of_scope("body:write") == "device" and api_tokens.family_of_scope("assistant:log") == "assistant"
    with pytest.raises(ValueError):
        api_tokens.family_of_scope("assistant:write")
    with pytest.raises(ValueError):
        api_tokens.new_token("phone")
    assert api_tokens.new_token("device").startswith("khd_") and api_tokens.new_token().startswith("kha_")
    assert api_tokens.DEVICE_SCOPES == ("body:write",) and api_tokens.ALL_SCOPES == (*api_tokens.SCOPES, "body:write")


def test_a_row_that_mixes_scopes_or_lies_about_its_prefix_opens_nothing(admin):
    """Hand-edited rows: the prefix pattern of the family and the scope are both checked, so neither a mixed row nor a token
    whose text is of the other family reaches either surface."""
    import sqlite3

    device, assistant = make_device(admin, "D"), make(admin, "A")

    def set_scopes(token_id: int, scopes: str) -> None:
        conn = sqlite3.connect(admin.app.state.settings.db_path)
        conn.execute("UPDATE api_tokens SET scopes = ? WHERE id = ?", (scopes, token_id))
        conn.commit()
        conn.close()

    assert push(admin.app, device["token"], {"weights": [weight()]}).status_code == 200
    assert mcp(admin.app, assistant["token"]).status_code == 200
    set_scopes(device["id"], "assistant:read body:write")
    set_scopes(assistant["id"], "assistant:read body:write")
    assert push(admin.app, device["token"], {"weights": [weight()]}).status_code == 401
    assert mcp(admin.app, assistant["token"]).status_code == 401
    set_scopes(device["id"], "assistant:read")  # a khd_ text with an assistant scope: refused at /mcp by its prefix
    set_scopes(assistant["id"], "body:write")  # a kha_ text with the device scope: refused at /push by its prefix
    assert mcp(admin.app, device["token"]).status_code == 401
    assert push(admin.app, assistant["token"], {"weights": [weight()]}).status_code == 401
    assert [len(x) for x in rows(admin)] == [1, 0]  # only the first push, before the edits, was stored


# --------------------------------------------------------------------------- the families at the two surfaces


def test_an_assistant_token_at_push_and_a_device_token_at_mcp_are_the_generic_401_and_throttled(admin):
    assistant, device = make(admin)["token"], make_device(admin)["token"]
    r = push(admin.app, assistant, {"weights": [weight()]})
    assert r.status_code == 401 and r.json() == GENERIC and r.headers["www-authenticate"] == 'Bearer realm="kidney-health", error="invalid_token"'
    r = mcp(admin.app, device)
    assert r.status_code == 401 and r.json() == {"detail": api_tokens.DENIED}
    assert r.headers["www-authenticate"] == 'Bearer realm="kidney-health", error="invalid_token"'
    # the same body as a wrong token of the right family, and each counts toward the address's sign-in limit
    wrong = push(admin.app, "khd_" + "B" * 43, {"weights": [weight()]})
    assert (wrong.status_code, wrong.json(), wrong.headers["www-authenticate"]) == (401, GENERIC, r.headers["www-authenticate"])
    for _ in range(8):
        assert push(admin.app, assistant, {}).status_code == 401
        assert mcp(admin.app, device).status_code == 401
    assert push(admin.app, assistant, {}).status_code == 401  # the 20th refused token
    assert push(admin.app, device, {"weights": [weight()]}).status_code == 429  # 20 refused tokens block the address, the good one too
    assert mcp(admin.app, assistant).status_code == 429


def test_the_switches_are_independent(admin):
    assistant, device = make(admin)["token"], make_device(admin)["token"]
    switch(admin, False)  # assistant access off: /mcp is 404, /push still works
    assert mcp(admin.app, assistant).status_code == 404
    assert push(admin.app, device, {"weights": [weight()]}).status_code == 200
    switch(admin, True)
    push_switch(admin, False)  # phone shortcuts off: /push is the generic 401, /mcp still works
    assert push(admin.app, device, {"weights": [weight(f"{DAY}T08:00:00Z")]}).status_code == 401
    assert mcp(admin.app, assistant).status_code == 200
    r = admin.post("/api/me/tokens", json={"name": "late", "family": "device"})  # no new device token while off
    assert r.status_code == 409 and "Phone shortcuts are turned off" in r.json()["detail"]
    assert admin.post("/api/me/tokens", json={"name": "still ok"}).status_code == 201  # the assistant switch is on
    listed = admin.get("/api/me/tokens?family=device").json()
    assert listed["enabled"] is False and [t["state"] for t in listed["tokens"]] == ["active"]  # listing and revoking work while off
    assert admin.delete(f"/api/me/tokens/{listed['tokens'][0]['id']}").status_code == 204
    push_switch(admin, True)
    assert push(admin.app, device, {"weights": [weight(f"{DAY}T09:00:00Z")]}).status_code == 401  # revoked while it was off
    switch(admin, False)
    r = admin.post("/api/me/tokens", json={"name": "late"})
    assert r.status_code == 409 and "Outside AI apps are turned off" in r.json()["detail"]


def test_bearer_helper_of_the_assistant_surface_still_refuses_a_device_token(admin):
    assert bearer(admin.app, make_device(admin)["token"]).status_code == 401  # the probe route depends on AssistantUser
    assert bearer(admin.app, make(admin)["token"]).status_code == 200


# --------------------------------------------------------------------------- limits


def test_at_most_five_active_tokens_in_each_family(admin):
    assistants = [make(admin, f"A{i}") for i in range(5)]
    devices = [make_device(admin, f"D{i}") for i in range(5)]  # the assistant tokens do not use up the device ones
    r = admin.post("/api/me/tokens", json={"name": "A6"})
    assert r.status_code == 400 and "5 active tokens" in r.json()["detail"]
    r = admin.post("/api/me/tokens", json={"name": "D6", "family": "device"})
    assert r.status_code == 400 and "5 active tokens" in r.json()["detail"]
    assert admin.delete(f"/api/me/tokens/{devices[0]['id']}").status_code == 204
    make_device(admin, "D6")  # a revoked one no longer counts, and only in its family
    r = admin.post("/api/me/tokens", json={"name": "A6"})
    assert r.status_code == 400
    assert admin.delete(f"/api/me/tokens/{assistants[0]['id']}").status_code == 204
    make(admin, "A6")
    conn = db(admin)
    try:
        uid = person_id(admin)
        assert api_tokens.active_count(conn, uid) == 10
        assert api_tokens.active_count(conn, uid, "assistant") == 5 and api_tokens.active_count(conn, uid, "device") == 5
        assert api_tokens.active_counts(conn) == {uid: 10}
        assert api_tokens.active_counts(conn, "device") == {uid: 5} and api_tokens.active_counts(conn, "assistant") == {uid: 5}
    finally:
        conn.close()


def test_the_expiry_choices_and_the_hourly_limit_on_making_tokens_are_shared(admin):
    from app.auth import clock

    for days in (30, 90, 365):
        item = make_device(admin, f"{days} days", days=days)
        assert (clock.parse(item["expires_at"]) - clock.parse(item["created_at"])).days == days
        assert admin.delete(f"/api/me/tokens/{item['id']}").status_code == 204
    assert admin.post("/api/me/tokens", json={"name": "x", "family": "device", "expires_in_days": 7}).status_code == 400
    for i in range(17):  # 3 so far; 20 an hour in all, either family
        item = make_device(admin, f"T{i}") if i % 2 else make(admin, f"T{i}")
        assert admin.delete(f"/api/me/tokens/{item['id']}").status_code == 204
    r = admin.post("/api/me/tokens", json={"name": "one too many", "family": "device"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_making_a_device_token_needs_a_recent_password(admin, fake_clock):
    fake_clock.advance(minutes=11)  # REAUTH_MINUTES is 10
    r = admin.post("/api/me/tokens", json={"name": "Late", "family": "device"})
    assert r.status_code == 403 and r.json()["reauth_required"] is True
    assert admin.get("/api/me/tokens?family=device").status_code == 200  # listing and revoking need no password
    assert admin.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    make_device(admin, "Late")


def test_expiry_and_last_use_work_as_for_assistant_tokens(admin, fake_clock):
    item = make_device(admin, days=30)
    assert push(admin.app, item["token"], {"weights": [weight()]}).status_code == 200
    assert admin.get("/api/me/tokens?family=device").json()["tokens"][0]["last_used_at"] is not None
    fake_clock.advance(days=30, seconds=1)
    r = push(admin.app, item["token"], {"weights": [weight(f"{DAY}T08:00:00Z")]})
    assert r.status_code == 401 and r.json() == GENERIC
    from conftest import sign_in

    sign_in(admin)  # the 30-day session ended too
    (listed,) = admin.get("/api/me/tokens?family=device").json()["tokens"]
    assert listed["state"] == "expired"


# --------------------------------------------------------------------------- audit


def test_the_audit_rows_say_which_family(admin):
    a, d = make(admin, "A", can_log=True), make_device(admin, "D", days=30)
    made = {r["target_id"]: r["details"] for r in audit_rows(admin, "api_token.created")}
    assert made[str(a["id"])] == {"expires_in_days": 90, "scopes": ["assistant:read", "assistant:log"], "family": "assistant"}
    assert made[str(d["id"])] == {"expires_in_days": 30, "scopes": ["body:write"], "family": "device"}
    assert d["token"] not in str(audit_rows(admin, "api_token.created"))  # ids only, never the token or its prefix
    assert d["prefix"] not in str(audit_rows(admin, "api_token.created"))
    events = admin.get("/api/me/activity").json()["events"]
    assert {e["details"]["family"] for e in events if e["action"] == "api_token.created"} == {"assistant", "device"}


def test_a_person_revoking_one_token_is_audited_with_its_family_for_the_activity_list(admin):
    """The activity list says "Phone shortcut token revoked" or "Assistant token revoked" by ``details.family`` (Settings, js/views/settings.js)."""
    a, d = make(admin, "A"), make_device(admin, "D")
    assert admin.delete(f"/api/me/tokens/{d['id']}").status_code == 204
    assert admin.delete(f"/api/me/tokens/{a['id']}").status_code == 204
    revoked = {r["target_id"]: r["details"] for r in audit_rows(admin, "api_token.revoked")}
    assert revoked == {str(d["id"]): {"reason": "self", "family": "device"}, str(a["id"]): {"reason": "self", "family": "assistant"}}
    events = admin.get("/api/me/activity").json()["events"]
    assert {e["details"]["family"] for e in events if e["action"] == "api_token.revoked"} == {"assistant", "device"}
    assert admin.delete(f"/api/me/tokens/{d['id']}").status_code == 204  # revoking an ended token is a no-op: one row each, still
    assert len(audit_rows(admin, "api_token.revoked")) == 2
    assert admin.delete("/api/me/tokens/999999").status_code == 404


# --------------------------------------------------------------------------- revoke_all ends both families


def test_a_password_change_revokes_both_families(pair):
    admin, sam = pair
    a, d = make(sam, "A")["token"], make_device(sam, "D")["token"]
    mine = make_device(admin, "Mine")["token"]
    new = "silver-meadow-compass-41"
    assert sam.post("/api/me/password", json={"current_password": USER_PASSWORD, "new_password": new}).status_code == 200
    assert mcp(admin.app, a).status_code == 401 and push(admin.app, d, {"weights": [weight()]}).status_code == 401
    assert {t["state"] for t in sam.get("/api/me/tokens?family=device").json()["tokens"]} == {"revoked"}
    assert {t["state"] for t in sam.get("/api/me/tokens").json()["tokens"]} == {"revoked"}
    assert push(admin.app, mine, {"weights": [weight()]}).status_code == 200  # someone else's token is untouched
    (row,) = audit_rows(admin, "api_token.revoked")
    assert row["details"] == {"reason": "password_changed", "count": 2}


def test_an_admin_revokes_every_token_of_a_person_in_both_families(pair):
    admin, sam = pair
    sam_id = person_id(sam)
    tokens = [make(sam, "A")["token"], make_device(sam, "D1")["token"], make_device(sam, "D2")["token"]]
    mine = make_device(admin, "Mine")["token"]
    users = {u["id"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert (users[sam_id]["assistant_tokens"], users[sam_id]["device_tokens"]) == (1, 2)
    assert (users[person_id(admin)]["assistant_tokens"], users[person_id(admin)]["device_tokens"]) == (0, 1)
    r = admin.post(f"/api/admin/users/{sam_id}/revoke-tokens")
    assert r.status_code == 200 and r.json() == {"revoked": 3}
    assert mcp(admin.app, tokens[0]).status_code == 401
    assert all(push(admin.app, t, {"weights": [weight()]}).status_code == 401 for t in tokens[1:])
    assert push(admin.app, mine, {"weights": [weight()]}).status_code == 200
    users = {u["id"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert (users[sam_id]["assistant_tokens"], users[sam_id]["device_tokens"]) == (0, 0)
    (row,) = audit_rows(admin, "api_token.revoked")
    assert row["details"] == {"reason": "admin", "count": 3}
    assert "khd_" not in str(admin.get("/api/admin/users").json())  # only counts reach the admin


def test_disabling_the_account_revokes_device_tokens_too(pair):
    admin, sam = pair
    token = make_device(sam, "D")["token"]
    assert admin.patch(f"/api/admin/users/{person_id(sam)}", json={"status": "disabled"}).status_code == 200
    assert push(admin.app, token, {"weights": [weight()]}).status_code == 401
    assert audit_rows(admin, "api_token.revoked")[0]["details"] == {"reason": "account_disabled", "count": 1}


def test_a_token_of_a_disabled_or_required_password_change_account_is_refused(pair):
    admin, sam = pair
    token = make_device(sam, "D")["token"]
    assert admin.patch(f"/api/admin/users/{person_id(sam)}", json={"must_change_password": True}).status_code == 200
    assert push(admin.app, token, {"weights": [weight()]}).status_code == 401


# --------------------------------------------------------------------------- isolation


def test_another_persons_device_tokens_are_invisible_and_404(pair):
    admin, sam = pair
    mine, theirs = make_device(admin, "Mine"), make_device(sam, "Sam's")
    assert [t["name"] for t in admin.get("/api/me/tokens?family=device").json()["tokens"]] == ["Mine"]
    assert [t["name"] for t in sam.get("/api/me/tokens?family=device").json()["tokens"]] == ["Sam's"]
    assert sam.delete(f"/api/me/tokens/{mine['id']}").status_code == 404
    assert sam.delete(f"/api/me/tokens/{mine['id']}/body-rows").status_code == 404
    assert admin.delete(f"/api/me/tokens/{theirs['id']}/body-rows").status_code == 404
    assert push(admin.app, mine["token"], {"weights": [weight()]}).status_code == 200
    assert push(admin.app, theirs["token"], {"weights": [weight()]}).status_code == 200
    assert len(rows(admin)[0]) == 1 and len(rows(sam)[0]) == 1  # each token wrote to its own owner's log
    for i in range(4):  # each person's five count separately
        make_device(sam, f"S{i}")
    make_device(admin, "M2")


# --------------------------------------------------------------------------- "Delete what it sent"


def delete_rows(client: TestClient, token_id: int) -> Any:
    return client.delete(f"/api/me/tokens/{token_id}/body-rows")


def test_delete_what_it_sent_removes_only_that_tokens_rows_of_that_person(pair):
    admin, sam = pair
    a, b = make_device(admin, "Morning weight"), make_device(admin, "Evening cuff")
    theirs = make_device(sam, "Sam's phone")
    day2 = "2026-10-23"
    assert push(admin.app, a["token"], {"weights": [weight(AT, 70, "kg", "A1"), weight(f"{day2}T07:00:00Z", 71, "kg", "A2")],
                                       "readings": [reading(f"{day2}T07:05:00Z", 120, 80, "A3")]}).json() == counts(added_w=2, added_r=1)
    assert push(admin.app, b["token"], {"weights": [weight(f"{DAY}T19:00:00Z", 72, "kg", "B1")],
                                       "readings": [reading(f"{DAY}T19:05:00Z", 125, 82, "B2")]}).json() == counts(added_w=1, added_r=1)
    assert push(sam.app, theirs["token"], {"weights": [weight(AT, 80, "kg", "S1")], "readings": [reading(f"{DAY}T07:20:00Z", 110, 70, "S2")]}
                ).json() == counts(added_w=1, added_r=1)
    admin.post("/api/body/weights", json={"date": DAY, "kg": 90, "context": "other"})  # typed
    admin.post("/api/body/weights/batch", json={"rows": [{"date": DAY, "time": "05:00", "kg": 91, "context": "morning", "source": "apple_health",
                                                          "source_key": "hk1"}]})
    listed = {t["name"]: t["sent"] for t in admin.get("/api/me/tokens?family=device").json()["tokens"]}
    assert listed == {"Morning weight": {"weights": 2, "readings": 1}, "Evening cuff": {"weights": 1, "readings": 1}}
    r = delete_rows(admin, a["id"])
    assert r.status_code == 200 and r.json() == {"deleted": {"weights": 2, "readings": 1}}
    ws, rs = rows(admin, DAY, "2026-10-31")
    assert {(w["via"], w["source"]) for w in ws} == {(None, "apple_health"), (None, "manual"), ("Evening cuff", "shortcut")} and len(ws) == 3
    assert [(x["via"], x["source"]) for x in rs] == [("Evening cuff", "shortcut")]
    assert len(rows(sam)[0]) == 1 and len(rows(sam)[1]) == 1  # Sam's rows are untouched
    again = delete_rows(admin, a["id"])
    assert again.status_code == 200 and again.json() == {"deleted": {"weights": 0, "readings": 0}}
    (first, second) = audit_rows(admin, "body.token_rows_deleted")
    assert (first["actor_user_id"], first["target_type"], first["target_id"]) == (person_id(admin), "api_token", str(a["id"]))
    assert first["details"] == {"weights": 2, "readings": 1} and second["details"] == {"weights": 0, "readings": 0}
    assert "70" not in str(first) and "A1" not in str(first)  # counts only
    assert any(e["action"] == "body.token_rows_deleted" for e in admin.get("/api/me/activity").json()["events"])
    # the token still works after its rows are gone (revoking is separate), and sends again
    assert push(admin.app, a["token"], {"weights": [weight(AT, 70, "kg", "A1")]}).json() == counts(added_w=1)


def test_delete_what_it_sent_works_for_a_revoked_or_expired_token_still_in_the_list(admin, fake_clock):
    revoked, expired = make_device(admin, "Revoked", days=365), make_device(admin, "Expired", days=30)
    assert push(admin.app, revoked["token"], {"weights": [weight(AT, 70, "kg")]}).status_code == 200
    assert push(admin.app, expired["token"], {"readings": [reading()]}).status_code == 200
    fake_clock.advance(days=35)  # the 30-day token ended 5 days ago; ended tokens stay listed for 30 days
    from conftest import sign_in

    sign_in(admin)
    assert admin.delete(f"/api/me/tokens/{revoked['id']}").status_code == 204
    states = {t["name"]: t["state"] for t in admin.get("/api/me/tokens?family=device").json()["tokens"]}
    assert states == {"Revoked": "revoked", "Expired": "expired"}
    assert delete_rows(admin, revoked["id"]).json() == {"deleted": {"weights": 1, "readings": 0}}
    assert delete_rows(admin, expired["id"]).json() == {"deleted": {"weights": 0, "readings": 1}}
    assert rows(admin) == ([], [])


@pytest.mark.parametrize("missing", [999999, 2**62])
def test_delete_what_it_sent_for_an_unknown_token_is_404_and_changes_nothing(admin, missing):
    other = make_device(admin, "Real")
    assert push(admin.app, other["token"], {"weights": [weight()]}).status_code == 200
    assert delete_rows(admin, missing).status_code == 404
    assert len(rows(admin)[0]) == 1 and audit_rows(admin, "body.token_rows_deleted") == []
    assert admin.delete("/api/me/tokens/0/body-rows").status_code == 400 and admin.delete(f"/api/me/tokens/{2**64}/body-rows").status_code == 400
    assert admin.delete("/api/me/tokens/abc/body-rows").status_code == 400


def test_delete_what_it_sent_is_for_device_tokens_only(admin):
    assistant = make(admin, "Chat")
    admin.post("/api/body/weights", json={"date": DAY, "kg": 90, "context": "other"})
    r = delete_rows(admin, assistant["id"])
    assert r.status_code == 404 and r.json()["detail"] == "token not found"
    assert len(rows(admin)[0]) == 1


def test_delete_what_it_sent_needs_a_session_not_a_token_and_no_recent_password(admin, fake_clock):
    item = make_device(admin, "Phone")
    assert push(admin.app, item["token"], {"weights": [weight()]}).status_code == 200
    r = bare(admin.app).delete(f"/api/me/tokens/{item['id']}/body-rows", headers={"Authorization": f"Bearer {item['token']}", "X-Requested-With": "kidney-health"})
    assert r.status_code == 401  # the token that sent the rows cannot delete them
    assert TestClient(admin.app).delete(f"/api/me/tokens/{item['id']}/body-rows").status_code == 401
    assert admin.delete(f"/api/me/tokens/{item['id']}/body-rows", headers={"X-Requested-With": ""}).status_code == 403  # CSRF header missing
    assert len(rows(admin)[0]) == 1
    fake_clock.advance(minutes=11)  # a stale password does not matter for deleting the person's own rows
    assert delete_rows(admin, item["id"]).status_code == 200


def test_editing_a_pushed_row_makes_it_the_persons_own_and_leaves_the_tokens_rows(admin):
    item = make_device(admin, "Phone")
    assert push(admin.app, item["token"], {"weights": [weight(AT, 70, "kg"), weight(f"{DAY}T08:00:00Z", 71, "kg", "Other")],
                                          "readings": [reading()]}).json() == counts(added_w=2, added_r=1)
    ws, rs = rows(admin)
    assert admin.put(f"/api/body/weights/{ws[0]['id']}", json={"date": DAY, "time": "07:15", "kg": 70.5, "context": "morning"}).status_code == 200
    assert admin.put(f"/api/body/blood-pressure/{rs[0]['id']}", json={"date": DAY, "time": "07:20", "systolic": 119, "diastolic": 79,
                                                                      "context": "morning"}).status_code == 200
    ws, rs = rows(admin)
    assert [(w["source"], w["via"]) for w in ws] == [("manual", None), ("shortcut", "Phone")] and [(r["source"], r["via"]) for r in rs] == [("manual", None)]
    assert admin.get("/api/me/tokens?family=device").json()["tokens"][0]["sent"] == {"weights": 1, "readings": 0}
    assert delete_rows(admin, item["id"]).json() == {"deleted": {"weights": 1, "readings": 0}}
    ws, rs = rows(admin)
    assert [w["kg"] for w in ws] == [70.5] and len(rs) == 1  # what the person edited stays
    # and it is not pushed again as a new row: the key is kept (a re-run of the shortcut adds nothing)
    assert push(admin.app, item["token"], {"weights": [weight(AT, 70, "kg")]}).json() == counts(there_w=1)


# --------------------------------------------------------------------------- purge and delete: the rows outlive the token


def test_the_rows_outlive_a_purged_token_and_lose_only_its_name(admin, fake_clock):
    item = make_device(admin, "Old phone", days=30)
    assert push(admin.app, item["token"], {"weights": [weight()], "readings": [reading()]}).json() == counts(added_w=1, added_r=1)
    assert [x["via"] for x in rows(admin)[0]] == ["Old phone"]
    fake_clock.advance(days=61)  # expired 31 days ago: the daily housekeeping purges it
    from conftest import sign_in

    sign_in(admin)
    assert admin.get("/api/me/tokens?family=device").json()["tokens"] == []
    conn = db(admin)
    try:
        assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
        w = conn.execute("SELECT source, api_token_id FROM weights").fetchone()
        r = conn.execute("SELECT source, api_token_id FROM blood_pressures").fetchone()
        assert (w["source"], w["api_token_id"], r["source"], r["api_token_id"]) == ("shortcut", None, "shortcut", None)
    finally:
        conn.close()
    ws, rs = rows(admin)
    assert (ws[0]["source"], ws[0]["via"], rs[0]["source"], rs[0]["via"]) == ("shortcut", None, "shortcut", None)
    assert delete_rows(admin, item["id"]).status_code == 404  # nothing groups them any more


def test_deleting_an_account_removes_its_tokens_and_rows_and_no_one_elses(pair):
    admin, sam = pair
    theirs, mine = make_device(sam, "Sam's"), make_device(admin, "Mine")
    assert push(admin.app, theirs["token"], {"weights": [weight()], "readings": [reading()]}).status_code == 200
    assert push(admin.app, mine["token"], {"weights": [weight()], "readings": [reading()]}).status_code == 200
    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    conn = db(admin)
    try:
        assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM blood_pressures").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
    assert push(admin.app, theirs["token"], {"weights": [weight()]}).status_code == 401


# --------------------------------------------------------------------------- the export


def test_shortcut_rows_export_and_import_with_their_source_and_without_the_token_id(admin):
    import io
    import json
    import zipfile

    item = make_device(admin, "Phone")
    assert push(admin.app, item["token"], {"weights": [weight()], "readings": [reading(systolic=130, diastolic=85)]}).status_code == 200
    r = admin.get("/api/me/export.zip")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        doc = json.loads(z.read("export.json"))
        csv_text = z.read("weights.csv").decode()
    (w,), (rd,) = doc["weights"], doc["blood_pressures"]
    assert w["source"] == "shortcut" and rd["source"] == "shortcut" and re.fullmatch(r"[0-9a-f]{32}", w["source_key"])
    assert "api_token_id" not in w and "api_token_id" not in rd and "via" not in w
    assert "api_token_id" not in csv_text and item["token"] not in json.dumps(doc) and "Phone" not in json.dumps(doc["weights"])
    # imported into another account (or after deleting the rows) the rows come back as shortcut rows with no token
    admin.delete(f"/api/me/tokens/{item['id']}/body-rows")
    assert rows(admin) == ([], [])
    r = admin.post("/api/me/import", content=json.dumps(doc), headers={"content-type": "application/json"})
    assert r.status_code == 200, r.text
    ws, rs = rows(admin)
    assert [(x["source"], x["via"], x["kg"]) for x in ws] == [("shortcut", None, 69.99)] and [(x["source"], x["via"]) for x in rs] == [("shortcut", None)]
    conn = db(admin)
    try:
        assert conn.execute("SELECT api_token_id FROM weights").fetchone()[0] is None
    finally:
        conn.close()


def test_a_device_token_works_with_no_sign_in_mode_for_user_one(tmp_path, foods_json):
    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path / "data", foods_json=foods_json, auth_mode="none"))) as c:
        assert c.patch("/api/admin/settings", json={"push.enabled": True}).status_code == 200
        made = make_device(c, "Kitchen tablet")
        assert push(c.app, made["token"], {"weights": [weight()]}).json() == counts(added_w=1)
        (w,), _ = rows(c)
        assert (w["via"], w["source"]) == ("Kitchen tablet", "shortcut")


def test_log_lines_hide_a_device_token_like_an_assistant_token():
    from app.security import redact

    for prefix in ("kha_", "khd_"):
        token = prefix + "AbCdEfGh01234567AbCdEfGh01234567AbCdEfGh012"
        assert len(token) == 47
        shown = redact(f"refused {token} from 10.0.0.1")
        assert token not in shown and f"{prefix}[redacted]" in shown
        assert token not in redact(f"Authorization: Bearer {token}")
