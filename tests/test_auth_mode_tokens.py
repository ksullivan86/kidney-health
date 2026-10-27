"""Changing AUTH_MODE ends every assistant (kha_) and phone shortcut (khd_) token of every person.

With ``AUTH_MODE=none`` anyone who reaches the server is user 1, an admin, and can make tokens that last a year.
Those tokens must not survive the owner switching sign-in back on (access-control audit, finding 1).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from itertools import permutations

import pytest

from app.auth import api_tokens
from app.config import Settings
from app.main import create_app

from conftest import TestClient, insert_users, make_settings, sign_in
from test_auth_modes import proxy_settings

MCP = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
PUSH = {"weights": [{"at": "2026-10-22T07:15:00-04:00", "value": 70, "unit": "kg", "source": "Health"}]}
MODES = ("none", "local", "proxy")


def settings_for(mode, tmp_path, foods_json) -> Settings:
    if mode == "proxy":
        return proxy_settings(tmp_path, foods_json)
    if mode == "none":
        return make_settings(tmp_path, foods_json, auth_mode="none", admin_username=None, admin_password=None)
    return make_settings(tmp_path, foods_json)


def start(mode, tmp_path, foods_json) -> TestClient:
    return TestClient(create_app(settings_for(mode, tmp_path, foods_json)), client=("127.0.0.1", 4321))


def conn_of(app) -> sqlite3.Connection:
    conn = sqlite3.connect(app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def states(app) -> dict[str, bool]:
    """name -> still active, for every token row."""
    conn = conn_of(app)
    try:
        now = api_tokens.clock.now_iso()
        rows = conn.execute("SELECT name, revoked_at, expires_at FROM api_tokens").fetchall()
    finally:
        conn.close()
    return {r["name"]: r["revoked_at"] is None and r["expires_at"] > now for r in rows}


def audit_rows(app) -> list[dict]:
    conn = conn_of(app)
    try:
        rows = conn.execute(
            "SELECT actor_user_id, target_type, target_id, details_json FROM audit_log WHERE action = 'api_token.revoked' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [{**dict(r), "details": json.loads(r["details_json"])} for r in rows]


def plant(app, user_id: int, tag: str) -> dict[str, str]:
    """One assistant and one phone shortcut token for the person, straight into the table."""
    conn = conn_of(app)
    try:
        a, _ = api_tokens.create(conn, user_id, f"{tag}-assistant", 365, (api_tokens.READ,))
        d, _ = api_tokens.create(conn, user_id, f"{tag}-device", 365, (api_tokens.BODY_WRITE,))
        conn.commit()
    finally:
        conn.close()
    return {"assistant": a, "device": d}


def test_tokens_made_while_sign_in_was_off_stop_working_when_it_is_back_on(tmp_path, foods_json):
    """The audit's case: a none-era kha_ token reached /mcp and a khd_ token reached /push after the switch."""
    with start("local", tmp_path, foods_json) as c:
        sign_in(c)
        r = c.patch("/api/admin/settings", json={"assistant.enabled": True, "push.enabled": True})
        assert r.status_code == 200, r.text
    with start("none", tmp_path, foods_json) as c:
        a = c.post("/api/me/tokens", json={"name": "visitor", "can_log": True}).json()["token"]
        d = c.post("/api/me/tokens", json={"name": "visitor", "family": "device"}).json()["token"]
        assert (a[:4], d[:4]) == ("kha_", "khd_")
        assert TestClient(c.app, headers={"Authorization": f"Bearer {a}"}).post("/mcp", json=MCP).status_code == 200  # works while open
    with start("local", tmp_path, foods_json) as c:
        assert TestClient(c.app, headers={"Authorization": f"Bearer {a}"}).post("/mcp", json=MCP).status_code == 401
        assert TestClient(c.app, headers={"Authorization": f"Bearer {d}"}).post("/push/v1/body", json=PUSH).status_code == 401
        sign_in(c)
        assert {t["state"] for t in c.get("/api/me/tokens").json()["tokens"]} == {"revoked"}
        # the owner can make new ones, and those work
        fresh = c.post("/api/me/tokens", json={"name": "mine"}).json()["token"]
        assert TestClient(c.app, headers={"Authorization": f"Bearer {fresh}"}).post("/mcp", json=MCP).status_code == 200


@pytest.mark.parametrize(("before", "after"), list(permutations(MODES, 2)))
def test_any_change_of_sign_in_mode_revokes_both_families_for_everyone(tmp_path, foods_json, before, after, caplog):
    with start(before, tmp_path, foods_json) as c:
        conn = conn_of(c.app)
        try:
            insert_users(conn, [(2, "sam")])
            conn.commit()
        finally:
            conn.close()
        plant(c.app, 1, "one")
        plant(c.app, 2, "two")
        assert set(states(c.app).values()) == {True} and len(states(c.app)) == 4
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), start(after, tmp_path, foods_json) as c:
        assert states(c.app) == {"one-assistant": False, "one-device": False, "two-assistant": False, "two-device": False}
        rows = audit_rows(c.app)
    assert [(r["actor_user_id"], r["target_type"], r["target_id"], r["details"]) for r in rows] == [
        (None, "user", "1", {"reason": "auth_mode_changed", "count": 2}),
        (None, "user", "2", {"reason": "auth_mode_changed", "count": 2}),
    ]
    warning = [m for m in caplog.messages if "revoked" in m and "tokens" in m]
    assert len(warning) == 1
    assert f"from {before} to {after}" in warning[0] and "revoked 4 assistant and phone shortcut tokens" in warning[0]


@pytest.mark.parametrize("mode", MODES)
def test_no_change_of_mode_revokes_nothing(tmp_path, foods_json, mode, caplog):
    with start(mode, tmp_path, foods_json) as c:
        plant(c.app, 1, "one")
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), start(mode, tmp_path, foods_json) as c:
        assert set(states(c.app).values()) == {True}
        assert audit_rows(c.app) == []
    assert not [m for m in caplog.messages if "revoked" in m]


def test_a_change_with_no_active_tokens_writes_no_audit_row_and_no_warning(tmp_path, foods_json, caplog):
    with start("none", tmp_path, foods_json) as c:
        conn = conn_of(c.app)
        try:
            api_tokens.create(conn, 1, "old", 30, (api_tokens.READ,))
            conn.execute("UPDATE api_tokens SET revoked_at = '2026-01-01T00:00:00.000000Z'")
            conn.commit()
        finally:
            conn.close()
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), start("local", tmp_path, foods_json) as c:
        assert audit_rows(c.app) == []
    assert not [m for m in caplog.messages if "revoked" in m]
