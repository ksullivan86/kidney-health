"""Assistant access tokens (schema step 10; ``app/auth/api_tokens.py``; docs/dev/plans/assistant-step1.md part A).

A test-only route stands in for the assistant surface (part B's ``/mcp`` depends on ``AssistantUser`` the
same way). Covered: the lifecycle, the hash at rest, expiry, revocation by the person and by the account
events (password change or reset, disable, delete), isolation between two people, the instance switch,
the sign-in throttle, and that the bearer dependency is the only place a token counts.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request

from app.auth import api_tokens
from app.auth.api_tokens import AssistantUser
from app.settings_registry import REGISTRY
from conftest import ADMIN_PASSWORD, USER_PASSWORD, TestClient, add_user, sign_in

PROBE = "/assistant-probe"
TOKEN_RE = re.compile(r"^kha_[A-Za-z0-9_-]{43}$")
DENIED = {"detail": api_tokens.DENIED}


def mount_probe(app: Any) -> None:
    """A route on the assistant surface, placed before the static "/" mount."""
    if getattr(app.state, "assistant_probe", False):
        return

    def probe(user: AssistantUser, request: Request) -> dict[str, Any]:
        return {"id": user.id, "username": user.username, "token_id": request.state.api_token.id}

    app.add_api_route(PROBE, probe, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())
    app.state.assistant_probe = True


def switch(admin: TestClient, on: bool) -> None:
    r = admin.patch("/api/admin/settings", json={"assistant.enabled": on})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["assistant.enabled"]["value"] is on


def make(client: TestClient, name: str = "Open WebUI", days: int | None = None, can_log: bool | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if days is not None:
        body["expires_in_days"] = days
    if can_log is not None:
        body["can_log"] = can_log
    r = client.post("/api/me/tokens", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def bearer(app: Any, token: str | None, scheme: str = "Bearer") -> Any:
    """A request with nothing but the Authorization header (no cookie)."""
    mount_probe(app)
    headers = {} if token is None else {"Authorization": f"{scheme} {token}".rstrip()}
    return TestClient(app, base_url="https://localhost").get(PROBE, headers=headers)


def db(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def audit_rows(client: TestClient, action: str) -> list[dict[str, Any]]:
    conn = db(client)
    try:
        rows = conn.execute("SELECT actor_user_id, target_type, target_id, details_json FROM audit_log WHERE action = ? ORDER BY id",
                            (action,)).fetchall()
    finally:
        conn.close()
    return [{**dict(r), "details": json.loads(r["details_json"])} for r in rows]


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    switch(client, True)
    return client


@pytest.fixture
def pair(two_clients: tuple[TestClient, TestClient]) -> tuple[TestClient, TestClient]:
    admin, sam = two_clients
    switch(admin, True)
    return admin, sam


# --------------------------------------------------------------------------- the switch


def test_the_switch_is_an_instance_setting_off_by_default_with_an_env_lock(client):
    d = REGISTRY["assistant.enabled"]
    assert (d.scope, d.default, d.env) == ("instance", False, "ASSISTANT_ENABLED")
    item = client.get("/api/admin/settings").json()["settings"]["assistant.enabled"]
    assert item["value"] is False and item["source"] == "default"


def test_switch_off_lists_but_refuses_new_tokens_and_every_bearer_request(admin):
    token = make(admin)["token"]
    assert bearer(admin.app, token).status_code == 200
    switch(admin, False)
    listed = admin.get("/api/me/tokens").json()
    assert listed["enabled"] is False and [t["state"] for t in listed["tokens"]] == ["active"]
    r = admin.post("/api/me/tokens", json={"name": "Another"})
    assert r.status_code == 409 and "turned off" in r.json()["detail"]
    for _ in range(25):  # refused without a lookup and without counting toward the address's sign-in limit
        r = bearer(admin.app, token)
        assert r.status_code == 401 and r.json() == DENIED
    # still revocable while off; switched on again, the tokens that are still valid work again
    other_id = make_while_on(admin)["id"]
    switch(admin, False)
    assert admin.delete(f"/api/me/tokens/{other_id}").status_code == 204
    switch(admin, True)
    assert bearer(admin.app, token).status_code == 200


def make_while_on(admin: TestClient) -> dict[str, Any]:
    switch(admin, True)
    return make(admin, "Second")


def test_env_lock_turns_it_on_and_the_admin_page_cannot_change_it(tmp_path, foods_json, monkeypatch):
    from conftest import make_settings, signed_in_client

    monkeypatch.setenv("ASSISTANT_ENABLED", "true")
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:
        item = c.get("/api/admin/settings").json()["settings"]["assistant.enabled"]
        assert item["value"] is True and item["locked_by_env"] == "ASSISTANT_ENABLED"
        assert c.patch("/api/admin/settings", json={"assistant.enabled": False}).status_code == 409
        assert bearer(c.app, make(c)["token"]).status_code == 200


# --------------------------------------------------------------------------- lifecycle


def test_lifecycle_create_list_use_and_revoke(admin):
    created = make(admin, "  Open\tWebUI\u0007 on the laptop ")
    token = created["token"]
    assert TOKEN_RE.match(token)
    assert created["name"] == "Open WebUI on the laptop"  # cleaned: control characters out, single spaces
    assert created["prefix"] == token[:12] and created["scopes"] == ["assistant:read"]
    assert created["state"] == "active" and created["last_used_at"] is None and created["revoked_at"] is None
    from app.auth import clock

    span = clock.parse(created["expires_at"]) - clock.parse(created["created_at"])
    assert span.days == 90  # the default

    listed = admin.get("/api/me/tokens")
    assert listed.status_code == 200
    doc = listed.json()
    assert doc["enabled"] is True and doc["max_active"] == 5 and doc["expiry_days"] == [30, 90, 365]
    assert doc["default_expiry_days"] == 90
    (item,) = doc["tokens"]
    assert set(item) == {"id", "name", "prefix", "scopes", "created_at", "last_used_at", "expires_at", "revoked_at", "state"}
    # write-only: the list never carries the token, nor its hash
    assert token not in listed.text and hashlib.sha256(token.encode()).hexdigest() not in listed.text

    r = bearer(admin.app, token)
    me = admin.get("/api/me").json()
    assert r.status_code == 200 and r.json() == {"id": me["id"], "username": me["username"], "token_id": created["id"]}
    assert admin.get("/api/me/tokens").json()["tokens"][0]["last_used_at"] is not None

    assert admin.delete(f"/api/me/tokens/{created['id']}").status_code == 204
    (item,) = admin.get("/api/me/tokens").json()["tokens"]
    assert item["state"] == "revoked" and item["revoked_at"] is not None
    r = bearer(admin.app, token)
    assert r.status_code == 401 and r.json() == DENIED
    # revoking again is a no-op (one activity entry); an unknown id is 404
    assert admin.delete(f"/api/me/tokens/{created['id']}").status_code == 204
    assert admin.delete("/api/me/tokens/999999").status_code == 404
    assert admin.delete(f"/api/me/tokens/{2**64}").status_code == 400  # out of range, never a 500
    assert len(audit_rows(admin, "api_token.revoked")) == 1


def test_the_database_keeps_only_the_hash_and_logs_never_see_the_token(admin, caplog):
    caplog.set_level("DEBUG")
    created = make(admin)
    token = created["token"]
    assert bearer(admin.app, token).status_code == 200
    conn = db(admin)
    try:
        row = conn.execute("SELECT * FROM api_tokens WHERE id = ?", (created["id"],)).fetchone()
        assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest() and row["prefix"] == token[:12]
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for record in conn.execute(f"SELECT * FROM {table}").fetchall():
                assert token not in repr(tuple(record)), table
    finally:
        conn.close()
    assert token not in caplog.text
    # the audit rows name the token by id, never by its text or prefix
    (made,) = audit_rows(admin, "api_token.created")
    assert made["target_type"] == "api_token" and made["target_id"] == str(created["id"])
    assert made["details"] == {"expires_in_days": 90, "scopes": ["assistant:read"]}


@pytest.mark.parametrize("days", [30, 90, 365])
def test_expiry_choices(admin, days):
    from app.auth import clock

    item = make(admin, days=days)
    assert (clock.parse(item["expires_at"]) - clock.parse(item["created_at"])).days == days


@pytest.mark.parametrize("body, field", [
    ({"name": ""}, "name"),
    ({"name": "   "}, "name"),
    ({"name": "\u0007\u0008"}, "name"),
    ({"name": "x" * 61}, "name"),
    ({"name": "ok", "expires_in_days": 7}, "expires_in_days"),
    ({"name": "ok", "expires_in_days": "forever"}, "expires_in_days"),
    ({"name": "ok", "scopes": ["assistant:log"]}, "scopes"),  # not a field yet: refused, never ignored
    ({}, "name"),
])
def test_invalid_bodies_are_400(admin, body, field):
    r = admin.post("/api/me/tokens", json=body)
    assert r.status_code == 400, r.text
    assert field in r.json()["detail"] or r.json().get("field") == field
    assert admin.get("/api/me/tokens").json()["tokens"] == []


def test_at_most_five_active_tokens(admin):
    items = [make(admin, f"Token {i}") for i in range(5)]
    r = admin.post("/api/me/tokens", json={"name": "Sixth"})
    assert r.status_code == 400 and "5 active tokens" in r.json()["detail"]
    assert admin.delete(f"/api/me/tokens/{items[0]['id']}").status_code == 204
    make(admin, "Sixth")  # a revoked one no longer counts


def test_making_tokens_is_rate_limited(admin):
    for i in range(20):
        item = make(admin, f"T{i}")
        assert admin.delete(f"/api/me/tokens/{item['id']}").status_code == 204
    r = admin.post("/api/me/tokens", json={"name": "One too many"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_making_a_token_needs_a_recent_password(admin, fake_clock):
    fake_clock.advance(minutes=11)  # REAUTH_MINUTES is 10; signing in counted as entering the password
    r = admin.post("/api/me/tokens", json={"name": "Late"})
    assert r.status_code == 403 and r.json()["reauth_required"] is True
    assert admin.get("/api/me/tokens").status_code == 200  # listing and revoking need no password
    assert admin.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    make(admin, "Late")


# --------------------------------------------------------------------------- time


def test_expired_tokens_are_refused_listed_as_expired_then_removed(admin, fake_clock):
    item = make(admin, days=30)
    assert bearer(admin.app, item["token"]).status_code == 200
    fake_clock.advance(days=30, seconds=1)
    r = bearer(admin.app, item["token"])
    assert r.status_code == 401 and r.json() == DENIED
    sign_in(admin)  # the 30-day session ended too
    (listed,) = admin.get("/api/me/tokens").json()["tokens"]
    assert listed["state"] == "expired"
    assert admin.delete(f"/api/me/tokens/{item['id']}").status_code == 204  # nothing to do: no activity entry
    assert audit_rows(admin, "api_token.revoked") == []
    fake_clock.advance(days=30)
    sign_in(admin)
    assert admin.get("/api/me/tokens").json()["tokens"] == []  # ended 30 days ago: no longer listed
    conn = db(admin)
    try:  # the daily housekeeping (run from requests) deleted the row already
        assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
        assert api_tokens.purge_ended(conn) == 0
    finally:
        conn.close()


def test_last_used_is_written_at_most_once_a_minute(admin, fake_clock):
    item = make(admin)
    assert bearer(admin.app, item["token"]).status_code == 200

    def last_used() -> str:
        conn = db(admin)
        try:
            return conn.execute("SELECT last_used_at FROM api_tokens WHERE id = ?", (item["id"],)).fetchone()[0]
        finally:
            conn.close()

    first = last_used()
    fake_clock.advance(seconds=59)
    assert bearer(admin.app, item["token"]).status_code == 200
    assert last_used() == first
    fake_clock.advance(seconds=2)
    assert bearer(admin.app, item["token"]).status_code == 200
    assert last_used() > first


# --------------------------------------------------------------------------- the bearer rules


def test_every_failure_is_the_same_401_with_a_bearer_challenge(pair, fake_clock):
    admin, sam = pair
    good = make(admin)["token"]
    revoked = make(admin, "Revoked")
    assert admin.delete(f"/api/me/tokens/{revoked['id']}").status_code == 204
    sams = make(sam)["token"]
    assert admin.patch(f"/api/admin/users/{sam.get('/api/me').json()['id']}", json={"status": "disabled"}).status_code == 200
    cases = {
        "no header": None,
        "unknown": "kha_" + "A" * 43,
        "malformed": "kha_short",
        "empty": "",
        "revoked": revoked["token"],
        "disabled person": sams,
        "the hash itself": hashlib.sha256(good.encode()).hexdigest(),
        "the prefix only": good[:12],
    }
    for label, token in cases.items():
        r = bearer(admin.app, token)
        assert r.status_code == 401 and r.json() == DENIED, label
        assert r.headers["www-authenticate"].startswith('Bearer realm="kidney-health"'), label
        assert ('error="invalid_token"' in r.headers["www-authenticate"]) is (token is not None), label
    # another scheme is no bearer token at all
    r = bearer(admin.app, good, scheme="Basic")
    assert r.status_code == 401 and r.json() == DENIED
    assert bearer(admin.app, good).status_code == 200


def test_failed_tokens_count_toward_the_sign_in_limit_of_the_address(admin):
    good = make(admin)["token"]
    for _ in range(30):  # no bearer header: nothing was guessed, nothing counts
        assert bearer(admin.app, None).status_code == 401
    for _ in range(20):  # LOGIN_IP_MAX_FAILURES (20) wrong tokens from one address
        assert bearer(admin.app, "kha_" + "B" * 43).status_code == 401
    r = bearer(admin.app, good)  # even a good token waits while the address is blocked
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    # the same limiter as sign-in: the address cannot sign in either
    other = TestClient(admin.app)
    r = other.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 429


def test_a_bearer_token_is_ignored_by_the_rest_of_the_api(pair):
    """The cookie decides who you are; a token next to it changes nothing, and alone it opens nothing."""
    admin, sam = pair
    token = make(admin)["token"]
    r = sam.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["username"] == "sam"
    alone = TestClient(admin.app, base_url="https://localhost", headers={"Authorization": f"Bearer {token}"})
    for method, path in (("GET", "/api/me"), ("GET", "/api/log?date=2026-10-05"), ("GET", "/api/me/tokens"),
                         ("POST", "/api/me/tokens"), ("GET", "/api/admin/users"), ("PATCH", "/api/admin/settings"),
                         ("GET", "/api/profile"), ("GET", "/api/me/export.zip")):
        r = alone.request(method, path, json={"name": "x"} if method != "GET" else None)
        assert r.status_code == 401 and r.json()["detail"] == "Sign in required", (method, path, r.status_code)


# --------------------------------------------------------------------------- isolation


def test_another_persons_tokens_are_invisible_and_404(pair):
    admin, sam = pair
    mine = make(admin, "Admin's")
    theirs = make(sam, "Sam's")
    assert [t["name"] for t in admin.get("/api/me/tokens").json()["tokens"]] == ["Admin's"]
    assert [t["name"] for t in sam.get("/api/me/tokens").json()["tokens"]] == ["Sam's"]
    assert sam.delete(f"/api/me/tokens/{mine['id']}").status_code == 404
    assert admin.delete(f"/api/me/tokens/{theirs['id']}").status_code == 404
    assert bearer(admin.app, mine["token"]).json()["username"] == "admin"
    assert bearer(admin.app, theirs["token"]).json()["username"] == "sam"
    # each person's five count separately
    for i in range(4):
        make(sam, f"Sam {i}")
    make(admin, "Admin 2")
    # deleting Sam's account removes Sam's tokens only
    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    assert bearer(admin.app, theirs["token"]).status_code == 401
    assert bearer(admin.app, mine["token"]).status_code == 200
    conn = db(admin)
    try:
        assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 2
    finally:
        conn.close()
    (gone,) = audit_rows(admin, "api_token.revoked")
    assert gone["details"] == {"reason": "account_deleted", "count": 5}


# --------------------------------------------------------------------------- account events revoke every token


def test_a_password_change_revokes_every_token(pair):
    admin, sam = pair
    tokens = [make(sam, "One")["token"], make(sam, "Two")["token"]]
    admins = make(admin)["token"]
    new = "silver-meadow-compass-41"
    r = sam.post("/api/me/password", json={"current_password": USER_PASSWORD, "new_password": new})
    assert r.status_code == 200, r.text
    for token in tokens:
        assert bearer(admin.app, token).status_code == 401
    assert bearer(admin.app, admins).status_code == 200
    assert {t["state"] for t in sam.get("/api/me/tokens").json()["tokens"]} == {"revoked"}
    (row,) = audit_rows(admin, "api_token.revoked")
    sam_id = sam.get("/api/me").json()["id"]
    assert (row["actor_user_id"], row["target_type"], row["target_id"]) == (sam_id, "user", str(sam_id))
    assert row["details"] == {"reason": "password_changed", "count": 2}
    # the person sees it in their own activity; a change with no token writes no extra row
    actions = [e["action"] for e in sam.get("/api/me/activity").json()["events"]]
    assert "api_token.revoked" in actions and "api_token.created" in actions
    assert sam.post("/api/me/password", json={"current_password": new, "new_password": USER_PASSWORD}).status_code == 200
    assert len(audit_rows(admin, "api_token.revoked")) == 1


def test_an_admin_reset_link_revokes_every_token_when_it_is_used(pair):
    admin, sam = pair
    sam_id = sam.get("/api/me").json()["id"]
    token = make(sam)["token"]
    link = admin.post(f"/api/admin/users/{sam_id}/reset-link").json()["url"].split("/#/reset/", 1)[1]
    assert bearer(admin.app, token).status_code == 200  # a link alone changes nothing yet
    anon = TestClient(admin.app, base_url="https://localhost")
    assert anon.post("/api/auth/reset", json={"token": link, "password": "amber-violin-harbor-62"}).status_code == 200
    assert bearer(admin.app, token).status_code == 401
    (row,) = audit_rows(admin, "api_token.revoked")
    assert row["details"] == {"reason": "password_reset", "count": 1}


def test_disabling_revokes_and_enabling_does_not_bring_tokens_back(pair):
    admin, sam = pair
    sam_id = sam.get("/api/me").json()["id"]
    token = make(sam)["token"]
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"status": "disabled"}).status_code == 200
    assert bearer(admin.app, token).status_code == 401
    (row,) = audit_rows(admin, "api_token.revoked")
    admin_id = admin.get("/api/me").json()["id"]
    assert (row["actor_user_id"], row["target_id"], row["details"]) == (admin_id, str(sam_id), {"reason": "account_disabled", "count": 1})
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"status": "active"}).status_code == 200
    assert bearer(admin.app, token).status_code == 401


def test_a_required_password_change_stops_tokens_until_the_change_revokes_them(pair):
    admin, sam = pair
    sam_id = sam.get("/api/me").json()["id"]
    token = make(sam)["token"]
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"must_change_password": True}).status_code == 200
    assert bearer(admin.app, token).status_code == 401
    new = "copper-lantern-meadow-19"
    assert sam.post("/api/me/password", json={"current_password": USER_PASSWORD, "new_password": new}).status_code == 200
    assert bearer(admin.app, token).status_code == 401
    assert sam.get("/api/me/tokens").json()["tokens"][0]["state"] == "revoked"


def test_the_cli_reset_and_disable_revoke_tokens(pair):
    import io

    from app import admin as cli

    admin, sam = pair
    env = {"DATA_DIR": str(admin.app.state.settings.data_dir)}
    token = make(sam)["token"]
    out = io.StringIO()
    new = "velvet-orchard-signal-83"
    assert cli.main(["reset-password", "sam", "--stdin"], env=env, out=out, stdin=io.StringIO(new + "\n")) == 0, out.getvalue()
    assert bearer(admin.app, token).status_code == 401
    sam = TestClient(admin.app, base_url="https://localhost")
    sign_in(sam, "sam", new)
    token = make(sam)["token"]
    assert cli.main(["disable-user", "sam"], env=env, out=out) == 0, out.getvalue()
    assert bearer(admin.app, token).status_code == 401
    rows = audit_rows(admin, "api_token.revoked")
    assert [(r["actor_user_id"], r["details"]["reason"]) for r in rows] == [(None, "password_reset"), (None, "account_disabled")]


# --------------------------------------------------------------------------- who may use a token


@pytest.mark.parametrize("mode, source, user_id, ok", [
    ("local", "local", 2, True),
    ("local", "proxy", 2, False),  # an account the server's mode cannot sign in
    ("proxy", "proxy", 2, True),
    ("proxy", "local", 2, False),
    ("none", "local", 1, True),
    ("none", "local", 2, False),  # with no sign-in, only user 1 exists for the app
])
def test_the_owner_must_be_able_to_use_the_app_in_this_auth_mode(tmp_path, mode, source, user_id, ok):
    from app import db as app_db
    from conftest import insert_users

    conn = app_db.connect(tmp_path / "k.db")
    app_db.migrate(conn)
    insert_users(conn, [(1, "admin"), (2, "sam")])
    conn.execute("UPDATE users SET auth_source = ? WHERE id = ?", (source, user_id))
    conn.commit()
    ctx = SimpleNamespace(settings=SimpleNamespace(auth_mode=mode))
    user = api_tokens._owner(conn, ctx, user_id)
    assert (user is not None) is ok
    for status in ("disabled", "locked", "pending_setup"):
        if mode == "none":
            break
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        assert api_tokens._owner(conn, ctx, user_id) is None, status
    conn.close()


def test_unknown_scopes_grant_nothing():
    assert api_tokens.parse_scopes("assistant:read") == ("assistant:read",)
    assert api_tokens.parse_scopes("admin assistant:write") == ()
    assert api_tokens.parse_scopes("assistant:log admin") == ("assistant:read", "assistant:log")  # log implies read
    assert api_tokens.parse_scopes(None) == ()
    with pytest.raises(ValueError):
        api_tokens.revoke_all(sqlite3.connect(":memory:"), 1, reason="because", actor_id=None)


# --------------------------------------------------------------------------- #
# Scopes (part C): assistant:log, ticked as "can also save food and recipes"
# --------------------------------------------------------------------------- #


def test_a_token_is_read_only_unless_can_log_is_asked_for(admin):
    plain = make(admin, "reader")
    assert plain["scopes"] == ["assistant:read"]
    assert make(admin, "explicit", can_log=False)["scopes"] == ["assistant:read"]
    saver = make(admin, "saver", can_log=True)
    assert saver["scopes"] == ["assistant:read", "assistant:log"]  # log implies read
    listed = {t["name"]: t["scopes"] for t in admin.get("/api/me/tokens").json()["tokens"]}
    assert listed == {"reader": ["assistant:read"], "explicit": ["assistant:read"],
                      "saver": ["assistant:read", "assistant:log"]}
    conn = db(admin)
    try:
        stored = {r["name"]: r["scopes"] for r in conn.execute("SELECT name, scopes FROM api_tokens")}
    finally:
        conn.close()
    assert stored == {"reader": "assistant:read", "explicit": "assistant:read", "saver": "assistant:read assistant:log"}
    created = {r["details"]["scopes"][-1] for r in audit_rows(admin, "api_token.created")}
    assert created == {"assistant:read", "assistant:log"}  # the activity log says what a token may do


def test_scopes_cannot_be_sent_by_name_and_can_log_must_be_a_boolean(admin):
    assert admin.post("/api/me/tokens", json={"name": "x", "scopes": ["assistant:log"]}).status_code == 400
    assert admin.post("/api/me/tokens", json={"name": "x", "can_log": "yes please"}).status_code == 400
    assert admin.post("/api/me/tokens", json={"name": "x", "can_log": None}).status_code == 400
    assert admin.get("/api/me/tokens").json()["tokens"] == []


def test_a_saving_token_still_reads_and_authenticates_like_any_token(admin):
    saver = make(admin, "saver", can_log=True)["token"]
    assert bearer(admin.app, saver).status_code == 200
    assert api_tokens.parse_scopes("assistant:read assistant:log") == api_tokens.SCOPES
    assert api_tokens.scopes_for(False) == (api_tokens.READ,) and api_tokens.scopes_for(True) == api_tokens.SCOPES


# --------------------------------------------------------------------------- an admin revokes a person's tokens


def person_id(client: TestClient) -> int:
    return int(client.get("/api/me").json()["id"])


def revoke_tokens_of(admin: TestClient, user_id: int | str) -> Any:
    return admin.post(f"/api/admin/users/{user_id}/revoke-tokens")


def test_an_admin_revokes_every_active_token_of_one_person_and_no_one_elses(pair):
    admin, sam = pair
    sam_id, admin_id = person_id(sam), person_id(admin)
    mine = make(admin, "Admin's")["token"]
    one, two, saver = make(sam, "One"), make(sam, "Two"), make(sam, "Saver", can_log=True)
    assert sam.delete(f"/api/me/tokens/{one['id']}").status_code == 204  # revoked by the person earlier: not counted
    r = revoke_tokens_of(admin, sam_id)
    assert r.status_code == 200 and r.json() == {"revoked": 2}
    for token in (two["token"], saver["token"], one["token"]):
        assert bearer(admin.app, token).status_code == 401
    assert bearer(admin.app, mine).status_code == 200  # the admin's own token, and everyone else's, are untouched
    listed = {t["name"]: t for t in sam.get("/api/me/tokens").json()["tokens"]}  # the person sees them revoked
    assert {t["state"] for t in listed.values()} == {"revoked"} and listed["Two"]["revoked_at"]
    assert [t["state"] for t in admin.get("/api/me/tokens").json()["tokens"]] == ["active"]
    rows = audit_rows(admin, "api_token.revoked")  # one by the person, one by the admin
    assert [(r_["actor_user_id"], r_["target_type"], r_["target_id"]) for r_ in rows] == [
        (sam_id, "api_token", str(one["id"])), (admin_id, "user", str(sam_id))]
    assert rows[1]["details"] == {"reason": "admin", "count": 2}
    events = sam.get("/api/me/activity").json()["events"]  # and sees who did it in their own activity
    assert any(e["action"] == "api_token.revoked" and e["details"] == {"reason": "admin", "count": 2}
               and str(e["actor_user_id"]) == str(admin_id) for e in events)
    # nothing left to revoke: a second press changes nothing and writes no second row
    assert revoke_tokens_of(admin, sam_id).json() == {"revoked": 0}
    assert len(audit_rows(admin, "api_token.revoked")) == 2
    # the person can make a new one
    fresh = make(sam, "Fresh")
    assert bearer(admin.app, fresh["token"]).status_code == 200


def test_an_admin_can_revoke_their_own_tokens_and_while_the_switch_is_off(pair):
    admin, sam = pair
    mine, theirs = make(admin, "Admin's"), make(sam, "Sam's")
    switch(admin, False)
    assert revoke_tokens_of(admin, person_id(admin)).json() == {"revoked": 1}
    assert revoke_tokens_of(admin, person_id(sam)).json() == {"revoked": 1}
    assert [t["state"] for t in admin.get("/api/me/tokens").json()["tokens"]] == ["revoked"]
    assert [t["state"] for t in sam.get("/api/me/tokens").json()["tokens"]] == ["revoked"]
    switch(admin, True)
    assert bearer(admin.app, mine["token"]).status_code == 401 and bearer(admin.app, theirs["token"]).status_code == 401


def test_only_an_admin_who_entered_the_password_lately_can_revoke_a_persons_tokens(pair, fake_clock):
    admin, sam = pair
    token = make(sam, "Sam's")["token"]
    sam_id = person_id(sam)
    r = revoke_tokens_of(sam, sam_id)  # a member cannot, not even for themselves
    assert r.status_code == 403 and r.json()["detail"] == "Admins only"
    r = revoke_tokens_of(sam, person_id(admin))
    assert r.status_code == 403
    anon = TestClient(admin.app, base_url="https://localhost")
    assert anon.post(f"/api/admin/users/{sam_id}/revoke-tokens").status_code == 401
    assert bearer(admin.app, token).status_code == 200  # none of that revoked anything
    fake_clock.advance(minutes=11)  # REAUTH_MINUTES is 10
    stale = revoke_tokens_of(admin, sam_id)
    assert stale.status_code == 403 and stale.json()["reauth_required"] is True
    assert bearer(admin.app, token).status_code == 200
    assert admin.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    assert revoke_tokens_of(admin, sam_id).json() == {"revoked": 1}
    assert bearer(admin.app, token).status_code == 401


@pytest.mark.parametrize("missing", [9999, 2**70, 0])
def test_revoking_the_tokens_of_a_person_who_does_not_exist_is_404_and_changes_nothing(pair, missing):
    admin, sam = pair
    token = make(sam, "Sam's")["token"]
    r = revoke_tokens_of(admin, missing)
    assert r.status_code == 404
    assert bearer(admin.app, token).status_code == 200 and len(audit_rows(admin, "api_token.revoked")) == 0
    assert revoke_tokens_of(admin, "not-a-number").status_code == 400  # a bad id is a validation error


def test_the_admin_list_shows_how_many_assistant_tokens_each_person_has_active(pair, fake_clock):
    admin, sam = pair
    sam_id, admin_id = person_id(sam), person_id(admin)

    def counts() -> dict[int, int]:
        users = admin.get("/api/admin/users").json()["users"]
        assert all(set(u) >= {"assistant_tokens", "reset_link", "can_use_shared"} for u in users)
        return {u["id"]: u["assistant_tokens"] for u in users}

    assert counts() == {admin_id: 0, sam_id: 0}
    make(sam, "Short", days=30)
    long = make(sam, "Long", days=365)
    make(admin, "Admin's")
    assert counts() == {admin_id: 1, sam_id: 2}
    assert sam.delete(f"/api/me/tokens/{long['id']}").status_code == 204  # revoked tokens are not counted
    assert counts() == {admin_id: 1, sam_id: 1}
    fake_clock.advance(days=31)  # expired ones are not counted either (asked of the code: the session is old by now)
    conn = db(admin)
    try:
        assert api_tokens.active_counts(conn) == {admin_id: 1}
    finally:
        conn.close()
    # only a number: no token, hash or prefix reaches the admin
    dump = json.dumps(admin.get("/api/admin/users").json())
    assert "kha_" not in dump and "token_hash" not in dump
