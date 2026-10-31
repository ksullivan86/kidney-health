"""Test accounts and Send feedback (design note 26; ``app/test_accounts.py``, ``app/feedback.py``, schema step 28).

Covered: off by default; the password file (not set, missing, weak, and TEST_ACCOUNT_PASSWORD refused); making both accounts
(Sam's sample data, tester-helper as a Care helper); a real account with the name; never an admin (People, the triggers, single
sign-on groups); the Care team only between test accounts, both ways, by name and by link; the server's AI off unless allowed;
turning the switch off and on; Reset (Server administration and the command line); the shared password stays the file's; the
feedback routes (tester, admin, everyone else 404, limits, CSV); start-up; the port of the demo's seed.
"""
from __future__ import annotations

import io
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from app import admin as admin_cli
from app import db, test_accounts
from app.config import ConfigError, load_settings
from app.settings_store import SettingsStore
from conftest import HTTPS_URL, USER_PASSWORD, TestClient, add_user, make_settings, sign_in, signed_in_client

PASSWORD = "lantern-meadow-quartz-91"
REPO = Path(__file__).resolve().parent.parent


def conn_of(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def switch(admin: TestClient, **values: Any) -> dict[str, Any]:
    r = admin.patch("/api/admin/settings", json=values)
    assert r.status_code == 200, r.text
    return r.json()


def turn_on(admin: TestClient, sharing: bool = True) -> None:
    switch(admin, **{"test_accounts.enabled": True, **({"sharing.enabled": True} if sharing else {})})


def as_user(admin: TestClient, username: str, password: str = PASSWORD) -> TestClient:
    c = TestClient(admin.app, base_url=HTTPS_URL)
    sign_in(c, username, password)
    return c


def status(admin: TestClient) -> dict[str, Any]:
    r = admin.get("/api/admin/test-accounts")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def pw_file(tmp_path: Path) -> Path:
    path = tmp_path / "test-account-password"
    path.write_text(PASSWORD + "\n", encoding="utf-8")
    return path


@pytest.fixture
def admin(tmp_path: Path, foods_json: Path, pw_file: Path) -> Iterator[TestClient]:
    with signed_in_client(make_settings(tmp_path, foods_json, test_account_password_file=pw_file), base_url=HTTPS_URL) as c:
        yield c


@pytest.fixture
def on(admin: TestClient) -> TestClient:
    turn_on(admin)
    return admin


# --------------------------------------------------------------------------- the switch and the password file


def test_off_by_default_nothing_is_made(admin):
    assert status(admin) == {"enabled": False, "ai": False, "problem": None, "accounts": []}
    with conn_of(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE is_test_account = 1").fetchone()[0] == 0
    r = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
    assert r.status_code == 401


@pytest.mark.parametrize("content,says,logged", [(None, "Set TEST_ACCOUNT_PASSWORD_FILE", "Set TEST_ACCOUNT_PASSWORD_FILE"),
                                                 ("missing", "could not be read", "does not exist"),
                                                 ("short-1", "password policy", "password policy"),
                                                 ("tester", "password policy", "password policy")])
def test_a_missing_or_weak_password_file_makes_nothing(tmp_path, foods_json, caplog, content, says, logged):
    path = None
    if content is not None:
        path = tmp_path / "pw"
        if content != "missing":
            path.write_text(content, encoding="utf-8")
    with signed_in_client(make_settings(tmp_path, foods_json, test_account_password_file=path), base_url=HTTPS_URL) as admin:
        caplog.clear()
        turn_on(admin)
        got = status(admin)
        assert got["enabled"] is True and got["accounts"] == [] and says in got["problem"]
        assert any(logged in rec.getMessage() for rec in caplog.records)
        # The admin screen gets a fixed sentence: no file path or operating-system error (that stays in the log).
        assert path is None or str(path) not in got["problem"]
        assert PASSWORD not in str(got) and (content is None or content not in ("short-1",) or "short-1" not in str(got))
        assert admin.post("/api/admin/test-accounts/reset").status_code == 409


def test_the_password_itself_is_never_an_environment_variable(tmp_path):
    with pytest.raises(ConfigError, match="TEST_ACCOUNT_PASSWORD_FILE"):
        load_settings({"DATA_DIR": str(tmp_path), "TEST_ACCOUNT_PASSWORD": PASSWORD})
    assert load_settings({"DATA_DIR": str(tmp_path), "TEST_ACCOUNT_PASSWORD_FILE": "/run/secrets/x"}).test_account_password_file \
        == Path("/run/secrets/x")


def test_turning_it_on_makes_both_accounts_with_sams_data_and_the_care_team(on):
    got = status(on)
    assert got["problem"] is None and [a["username"] for a in got["accounts"]] == ["tester", "tester-helper"]
    assert {a["status"] for a in got["accounts"]} == {"active"}
    tester = as_user(on, "tester")
    me = tester.get("/api/me").json()
    assert me["test_account"] is True and me["role"] == "user" and me["display_name"] == "Sam"
    assert on.get("/api/me").json()["test_account"] is False
    profile = tester.get("/api/profile").json()
    assert (profile["name"], profile["ckd_stage"], profile["diabetes"], profile["dialysis"]) == ("Sam", "4", "type1", "none")
    assert profile["targets"]  # the suggestion's targets were saved
    assert len(tester.get("/api/labs").json()["labs"]) == len(test_accounts.LABS)
    with conn_of(on) as conn:
        uid = int(me["id"])
        assert conn.execute("SELECT COUNT(*) FROM weights WHERE user_id = ?", (uid,)).fetchone()[0] == 15
        assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = ?", (uid,)).fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM meal_templates WHERE user_id = ?", (uid,)).fetchone()[0] >= 1
    helper = as_user(on, "tester-helper")
    people = helper.get("/api/shared").json()["people"]
    assert [(p["username"], p["role"]) for p in people] == [("tester", "care_helper")]
    assert sorted(people[0]["areas"]) == sorted(test_accounts.HELPER_AREAS)
    team = tester.get("/api/me/shares").json()["sharing"]
    assert [(s["username"], s["role"]) for s in team] == [("tester-helper", "care_helper")]
    users = {u["username"]: u for u in on.get("/api/admin/users").json()["users"]}
    assert users["tester"]["test_account"] is True and users["admin"]["test_account"] is False


def test_a_real_account_with_the_name_keeps_it_and_nothing_is_made(admin):
    real = add_user(admin, "tester", USER_PASSWORD)
    turn_on(admin)
    got = status(admin)
    assert got["accounts"] == [] and "real account already uses the user name tester" in got["problem"]
    assert real.get("/api/me").json()["test_account"] is False


def test_turning_it_off_disables_and_signs_out_then_on_again_enables(on):
    tester = as_user(on, "tester")
    switch(on, **{"test_accounts.enabled": False})
    assert tester.get("/api/me").status_code == 401
    assert {a["status"] for a in status(on)["accounts"]} == {"disabled"}
    r = TestClient(on.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
    assert r.status_code == 401
    uid = status(on)["accounts"][0]["id"]
    assert on.patch(f"/api/admin/users/{uid}", json={"status": "active"}).status_code == 409  # not while the switch is off
    switch(on, **{"test_accounts.enabled": True})
    assert {a["status"] for a in status(on)["accounts"]} == {"active"}
    assert as_user(on, "tester").get("/api/me").json()["username"] == "tester"
    with conn_of(on) as conn:  # disabled, not deleted: the same accounts and data
        assert conn.execute("SELECT COUNT(*) FROM users WHERE is_test_account = 1").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = ?", (uid,)).fetchone()[0] > 0


def test_start_up_makes_them_and_sets_the_password_again(tmp_path, foods_json, pw_file):
    settings = make_settings(tmp_path, foods_json, test_account_password_file=pw_file)
    with signed_in_client(settings, base_url=HTTPS_URL) as admin:
        turn_on(admin)
    with conn_of(admin) as conn:
        conn.execute("DELETE FROM users WHERE username_norm = 'tester-helper'")
        conn.execute("UPDATE users SET status = 'locked' WHERE username_norm = 'tester'")
    new_password = "orchard-violet-signal-26"
    pw_file.write_text(new_password, encoding="utf-8")
    with signed_in_client(settings, base_url=HTTPS_URL) as admin:
        got = status(admin)
        assert [(a["username"], a["status"]) for a in got["accounts"]] == [("tester", "active"), ("tester-helper", "active")]
        helper = as_user(admin, "tester-helper", new_password)
        assert [p["username"] for p in helper.get("/api/shared").json()["people"]] == ["tester"]  # the Care team link again


# --------------------------------------------------------------------------- never an admin


def test_a_test_account_is_never_an_admin(on):
    uid = status(on)["accounts"][0]["id"]
    r = on.patch(f"/api/admin/users/{uid}", json={"role": "admin"})
    assert r.status_code == 409 and "never be an admin" in r.json()["detail"]
    with conn_of(on) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="cannot be an admin"):
            conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (uid,))
        with pytest.raises(sqlite3.IntegrityError, match="cannot be an admin"):
            conn.execute("INSERT INTO users (username, username_norm, role, is_test_account, created_at, updated_at) "
                         "VALUES ('x1', 'x1', 'admin', 1, 'now', 'now')")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be an admin"):
            conn.execute("UPDATE users SET is_test_account = 1 WHERE username_norm = 'admin'")


def test_single_sign_on_groups_never_make_a_test_account_an_admin(on, monkeypatch):
    from app.auth import oidc, oidc_api

    uid = status(on)["accounts"][0]["id"]
    store = SettingsStore(env={})
    with conn_of(on) as conn:
        store.set_instance(conn, "auth.oidc.admin_groups", "admins")
        conn.commit()
        monkeypatch.setattr(oidc, "groups", lambda claims: {"admins"})
        oidc_api._sync_role(conn, SimpleNamespace(store=store), uid, {"groups": ["admins"]}, None)
        conn.commit()
        assert conn.execute("SELECT role FROM users WHERE id = ?", (uid,)).fetchone()["role"] == "user"


# --------------------------------------------------------------------------- the Care team: only with test accounts


def test_a_test_account_and_a_real_account_never_meet_by_name(on):
    tester = as_user(on, "tester")
    sam = add_user(on, "sam")
    a = tester.post("/api/me/shares/invite", json={"username": "sam", "role": "viewer", "areas": ["labs"]})
    b = tester.post("/api/me/shares/invite", json={"username": "nobody-here", "role": "viewer", "areas": ["labs"]})
    assert a.status_code == b.status_code == 201
    assert {k for k in a.json()} == {k for k in b.json()}
    assert sam.get("/api/shared").json()["invites"] == []  # never reaches the real account
    r = sam.post("/api/me/shares/invite", json={"username": "tester", "role": "care_helper", "areas": ["food"]})
    assert r.status_code == 201
    assert tester.get("/api/shared").json()["invites"] == []  # and the other way round
    helper = as_user(on, "tester-helper")
    ok = tester.post("/api/me/shares/invite", json={"username": "tester-helper", "role": "viewer", "areas": ["labs"]})
    assert ok.status_code == 201 and [i["username"] for i in helper.get("/api/shared").json()["invites"]] == ["tester"]


def test_a_link_never_joins_a_test_account_and_a_real_account(on):
    tester = as_user(on, "tester")
    sam = add_user(on, "sam")
    for owner, other in ((tester, sam), (sam, tester)):
        made = owner.post("/api/me/shares", json={"areas": ["labs"]})
        assert made.status_code == 201, made.text
        code = made.json()["link"].split("#/share/", 1)[1]
        assert other.post("/api/shared/info", json={"code": code}).status_code == 404
        assert other.post("/api/shared/accept", json={"code": code}).status_code == 404


def test_a_share_between_kinds_is_404_and_listed_nowhere(on):
    tester = as_user(on, "tester")
    sam = add_user(on, "sam")
    with conn_of(on) as conn:  # however it got there (it cannot through the API), it never works and never shows
        t = int(tester.get("/api/me").json()["id"])
        s = int(sam.get("/api/me").json()["id"])
        cur = conn.execute("INSERT INTO shares (owner_user_id, grantee_user_id, areas, created_at, accepted_at, role) "
                           "VALUES (?, ?, '[\"food\",\"labs\"]', 'now', 'now', 'viewer')", (t, s))
        share_id = cur.lastrowid
    assert sam.get(f"/api/shared/{share_id}/labs").status_code == 404
    assert sam.get("/api/shared").json()["people"] == []
    assert [x["username"] for x in tester.get("/api/me/shares").json()["sharing"]] == ["tester-helper"]


# --------------------------------------------------------------------------- the server's AI


def test_the_ai_is_off_for_test_accounts_unless_allowed(on):
    switch(on, **{"ai.enabled": True})
    tester = as_user(on, "tester")
    assert on.get("/api/ai/status").status_code == 200
    assert tester.get("/api/ai/status").status_code == 404
    assert tester.get("/api/me/ai").json()["enabled"] is False
    assert tester.get("/api/meta").json()["capabilities"]["ai"] is False
    switch(on, **{"test_accounts.ai": True})
    assert tester.get("/api/ai/status").status_code == 200
    assert tester.get("/api/me/ai").json()["enabled"] is True


# --------------------------------------------------------------------------- one shared password


def test_the_shared_password_stays_the_files(on):
    tester = as_user(on, "tester")
    r = tester.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "brand-new-river-stone-55"})
    assert r.status_code == 409
    assert tester.post("/api/me/totp/setup").status_code == 409
    assert tester.request("DELETE", "/api/me", json={"password": PASSWORD, "confirm": "DELETE"}).status_code == 409
    uid = status(on)["accounts"][0]["id"]
    assert on.post(f"/api/admin/users/{uid}/reset-link").status_code == 409
    assert on.patch(f"/api/admin/users/{uid}", json={"must_change_password": True}).status_code == 409


# --------------------------------------------------------------------------- Reset


def _entries(client: TestClient) -> int:
    with conn_of(client) as conn:
        return conn.execute("SELECT COUNT(*) FROM log_entries l JOIN users u ON u.id = l.user_id WHERE u.username_norm = 'tester'").fetchone()[0]


def test_reset_deletes_what_they_made_and_starts_again(on):
    tester = as_user(on, "tester")
    seeded = _entries(on)
    tester.patch("/api/me", json={"display_name": "Changed"})
    food = tester.get("/api/foods", params={"q": "apple"}).json()["foods"][0]
    assert tester.post("/api/log", json={"date": date.today().isoformat(), "meal": "lunch", "food_id": food["id"], "servings": 9}).status_code == 201
    assert tester.post("/api/feedback", json={"screen": "Today", "happened": "a note"}).status_code == 201
    helper = as_user(on, "tester-helper")
    share_id = helper.get("/api/shared").json()["people"][0]["id"]
    assert helper.delete(f"/api/shared/{share_id}").status_code == 204  # the helper left the Care team
    assert _entries(on) == seeded + 1
    r = on.post("/api/admin/test-accounts/reset")
    assert r.status_code == 200, r.text
    assert [a["username"] for a in r.json()["accounts"]] == ["tester", "tester-helper"]
    assert tester.get("/api/me").status_code == 401 and helper.get("/api/me").status_code == 401  # signed out
    assert _entries(on) == seeded
    tester = as_user(on, "tester")
    assert tester.get("/api/me").json()["display_name"] == "Sam"
    assert [p["username"] for p in as_user(on, "tester-helper").get("/api/shared").json()["people"]] == ["tester"]
    assert tester.get("/api/feedback").json()["feedback"] == []  # a fresh account sees none of the old
    kept = on.get("/api/admin/feedback", params={"state": "all"}).json()["feedback"]
    assert [(f["username"], f["happened"]) for f in kept] == [("tester", "a note")]  # the admin still has it
    with conn_of(on) as conn:
        row = conn.execute("SELECT details_json FROM audit_log WHERE action = 'test_accounts.reset'").fetchone()
        assert row is not None and "tester-helper" in row["details_json"]


def test_reset_is_refused_while_off(admin):
    r = admin.post("/api/admin/test-accounts/reset")
    assert r.status_code == 409 and "Turn on test accounts" in r.json()["detail"]


def test_reset_from_the_command_line(on, monkeypatch):
    tester = as_user(on, "tester")
    food = tester.get("/api/foods", params={"q": "apple"}).json()["foods"][0]
    tester.post("/api/log", json={"date": date.today().isoformat(), "meal": "lunch", "food_id": food["id"], "servings": 9})
    seeded = _entries(on) - 1
    settings = on.app.state.settings
    monkeypatch.setattr(admin_cli, "load_settings", lambda env=None: settings)
    out = io.StringIO()
    assert admin_cli.main(["reset-test-accounts"], env={}, out=out) == 0
    assert "tester, tester-helper" in out.getvalue()
    assert _entries(on) == seeded
    switch(on, **{"test_accounts.enabled": False})
    assert admin_cli.main(["reset-test-accounts"], env={}, out=io.StringIO()) == 1


# --------------------------------------------------------------------------- Send feedback


def test_feedback_is_for_test_accounts_and_admins_only(on):
    tester = as_user(on, "tester")
    helper = as_user(on, "tester-helper")
    sam = add_user(on, "sam")
    sent = tester.post("/api/feedback", json={"screen": "Plan", "trying": "Plan: three days", "happened": "It worked",
                                              "useful": "yes", "unsafe": True})
    assert sent.status_code == 201, sent.text
    item = sent.json()
    assert item["screen"] == "Plan" and item["unsafe"] is True and item["done"] is False and item["app_version"] == on.app.version
    assert set(item) == {"id", "screen", "trying", "happened", "useful", "unsafe", "app_version", "created_at", "done"}
    helper.post("/api/feedback", json={"screen": "Today", "happened": "fine"})
    assert [f["id"] for f in tester.get("/api/feedback").json()["feedback"]] == [item["id"]]
    assert len(helper.get("/api/feedback").json()["feedback"]) == 1
    for client in (sam, on):  # a real account, even an admin, has no Send feedback
        assert client.get("/api/feedback").status_code == 404
        assert client.post("/api/feedback", json={"screen": "Today", "happened": "x"}).status_code == 404
    for client in (sam, tester):  # and only admins read everyone's
        assert client.get("/api/admin/feedback").status_code == 403
        assert client.patch(f"/api/admin/feedback/{item['id']}", json={"done": True}).status_code == 403
        assert client.get("/api/admin/test-accounts").status_code == 403
        assert client.post("/api/admin/test-accounts/reset").status_code == 403
    listed = on.get("/api/admin/feedback").json()
    assert listed["counts"] == {"open": 2, "done": 0, "unsafe_open": 1}
    assert [f["username"] for f in on.get("/api/admin/feedback", params={"unsafe": True}).json()["feedback"]] == ["tester"]
    done = on.patch(f"/api/admin/feedback/{item['id']}", json={"done": True})
    assert done.status_code == 200 and done.json()["done"] is True
    assert tester.get("/api/feedback").json()["feedback"][0]["done"] is True
    assert [f["id"] for f in on.get("/api/admin/feedback", params={"state": "done"}).json()["feedback"]] == [item["id"]]
    assert on.patch("/api/admin/feedback/999999", json={"done": True}).status_code == 404
    assert on.request("DELETE", "/api/admin/feedback/done").json() == {"deleted": 1}
    assert on.get("/api/admin/feedback", params={"state": "all"}).json()["counts"] == {"open": 1, "done": 0, "unsafe_open": 0}


def test_feedback_csv_escapes_formulas(on):
    tester = as_user(on, "tester")
    tester.post("/api/feedback", json={"screen": "Trends", "trying": "=HYPERLINK(\"x\")", "happened": "ok, \"quoted\""})
    r = on.get("/api/admin/feedback.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == "id,created_at,username,screen,trying,happened,useful,unsafe,app_version,done_at"
    assert "'=HYPERLINK" in lines[1] and ",no," in lines[1]


def test_feedback_limits(on):
    tester = as_user(on, "tester")
    assert tester.post("/api/feedback", json={"screen": "Today"}).status_code == 400  # nothing typed
    assert tester.post("/api/feedback", json={"screen": "Today", "happened": "x" * 2001}).status_code == 400
    assert tester.post("/api/feedback", json={"screen": "<script>", "happened": "x"}).status_code == 400
    assert tester.post("/api/feedback", json={"screen": "Today", "happened": "x", "email": "a@b"}).status_code == 400  # nothing else
    uid = int(tester.get("/api/me").json()["id"])
    with conn_of(on) as conn:
        now = db.utcnow()
        conn.executemany("INSERT INTO feedback (user_id, username, screen, trying, happened, app_version, created_at) "
                         "VALUES (?, 'tester', 'Today', '', 'x', '1', ?)", [(uid, now)] * 50)
    r = tester.post("/api/feedback", json={"screen": "Today", "happened": "one more"})
    assert r.status_code == 409 and "today" in r.json()["detail"]
    helper = as_user(on, "tester-helper")
    with conn_of(on) as conn:
        conn.executemany("INSERT INTO feedback (user_id, username, screen, trying, happened, app_version, created_at) "
                         "VALUES (NULL, 'old', 'Today', '', 'x', '1', '2026-01-01T00:00:00Z')", [()] * 4950)
    r = helper.post("/api/feedback", json={"screen": "Today", "happened": "full"})
    assert r.status_code == 409 and "full" in r.json()["detail"]


def test_feedback_is_limited_to_twenty_an_hour(on):
    helper = as_user(on, "tester-helper")
    codes = [helper.post("/api/feedback", json={"screen": "Today", "happened": f"n{i}"}).status_code for i in range(21)]
    assert codes[:20] == [201] * 20 and codes[20] == 429


# --------------------------------------------------------------------------- the seed: a port of the demo's


def test_the_seed_uses_the_same_foods_as_the_demo():
    js = (REPO / "app/static/js/mock/seed.js").read_text(encoding="utf-8")
    table = js[js.index("const FOODS = {"):js.index("};", js.index("const FOODS = {"))]
    found = {k: int(v) for k, v in re.findall(r"(\w+): \[(-?\d+), /", table)}
    assert found == {k: v[0] for k, v in test_accounts.FOODS.items()}
    for key, (_, pattern) in test_accounts.FOODS.items():
        assert f"{key}: [{test_accounts.FOODS[key][0]}, /{pattern}/i]" in table
    for text in ("Hypo 3.5 mmol/L before dinner; 5.8 after 15 minutes", "Usual breakfast", "Chicken & rice lunch",
                 "Hypo kit: glucose tablets", "0x5eed2610", "birth_month: '1971-03'", "activity: 'low_active'"):
        assert text in js


def test_the_seed_with_the_real_food_list(tmp_path):
    path = tmp_path / "kidney.db"
    db.init_db(path)
    conn = db.connect(path)
    from app import foods

    foods.import_builtin_foods(conn, REPO / "data" / "foods.json")
    conn.execute("INSERT INTO users (username, username_norm, role, status, is_test_account, created_at, updated_at) "
                 "VALUES ('tester', 'tester', 'user', 'active', 1, 'now', 'now')")
    uid = int(conn.execute("SELECT id FROM users WHERE username_norm = 'tester'").fetchone()[0])
    finder = test_accounts._food_finder(conn)
    assert [k for k in test_accounts.FOODS if finder(k) is None] == []  # every food of the demo's seed is in the food list
    today = date(2026, 10, 31)
    counts = test_accounts.seed_patient(conn, SettingsStore(env={}), uid, today=today)
    conn.commit()
    assert counts["saved_meals"] == 3 and counts["entries"] > 300
    hypo = conn.execute("SELECT date, note FROM log_entries WHERE user_id = ? AND purpose = 'hypo' ORDER BY date", (uid,)).fetchall()
    assert [(r["date"], r["note"]) for r in hypo] == [((today - timedelta(days=13)).isoformat(), test_accounts.SPECIAL[13]["hypo"]),
                                                       ((today - timedelta(days=4)).isoformat(), test_accounts.SPECIAL[4]["hypo"])]
    planned = conn.execute("SELECT DISTINCT date FROM log_entries WHERE user_id = ? AND status = 'planned' ORDER BY date", (uid,)).fetchall()
    assert [r[0] for r in planned] == [(today + timedelta(days=i)).isoformat() for i in range(4)]
    empty = {(today - timedelta(days=d)).isoformat() for d in test_accounts.EMPTY}
    days = {r[0] for r in conn.execute("SELECT DISTINCT date FROM log_entries WHERE user_id = ?", (uid,))}
    assert not (empty & days) and len(days) == 30 - 3 + 1 + 3
    created = [r[0] for r in conn.execute("SELECT created_at FROM log_entries WHERE user_id = ? ORDER BY id", (uid,))]
    assert created == sorted(created)  # inserted in time order, as the demo
    conn.close()
