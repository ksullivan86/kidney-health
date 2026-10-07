"""Fixes from the M1 review: removed admins are contained, sign-in floods stay per address and never
stall other routes, ``AUTH_MODE=none`` keeps user 1, last-admin and single-use races, IPv6 limiter keys."""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from app.auth import passwords, throttle as throttle_module
from app.main import create_app

from conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    HTTPS_URL,
    USER_PASSWORD,
    TestClient,
    add_user,
    make_settings,
    sign_in,
)

NEW_PASSWORD = "violet-meadow-compass-19"
ATTACKER_PASSWORD = "copper-thistle-avalanche-42"


def db(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def token_of(url: str, kind: str) -> str:
    return url.split(f"/#/{kind}/", 1)[1]


# --------------------------------------------------------------------------- #
# A removed admin's invites and links stop working
# --------------------------------------------------------------------------- #


@pytest.fixture
def planted(https_client):
    """Admin "admin2" (invited as admin) plants an admin invite, a reset link for the first admin and a
    pending admin account with its setup link; returns ``(boss, admin2, admin2_id, links)``."""
    boss = https_client
    admin2 = add_user(boss, "admin2", USER_PASSWORD, role="admin")
    admin2_id = admin2.get("/api/me").json()["id"]
    invite = admin2.post("/api/admin/invites", json={"role": "admin", "ttl_days": 90})
    assert invite.status_code == 201
    reset = admin2.post("/api/admin/users/1/reset-link")
    assert reset.status_code == 200
    pend = admin2.post("/api/admin/users", json={"username": "pend", "role": "admin"})
    assert pend.status_code == 201
    links = {
        "invite": token_of(invite.json()["url"], "invite"),
        "reset": token_of(reset.json()["url"], "reset"),
        "setup": token_of(pend.json()["setup_url"], "reset"),
    }
    return boss, admin2, admin2_id, links


def assert_links_dead(app, links: dict[str, str]) -> None:
    stranger = TestClient(app, base_url=HTTPS_URL)
    r = stranger.post("/api/auth/register", json={"token": links["invite"], "username": "mallory", "password": ATTACKER_PASSWORD})
    assert r.status_code == 400, r.text
    for kind in ("reset", "setup"):
        r = stranger.post("/api/auth/reset", json={"token": links[kind], "password": ATTACKER_PASSWORD})
        assert r.status_code == 400, (kind, r.text)
    # the first admin still signs in with their own password
    sign_in(TestClient(app, base_url=HTTPS_URL))


def test_the_remaining_admin_sees_and_can_revoke_a_link_planted_for_their_account(planted):
    boss, admin2, admin2_id, links = planted
    users = {u["username"]: u for u in boss.get("/api/admin/users").json()["users"]}
    link = users[ADMIN_USERNAME]["reset_link"]
    assert link["created_by"] == admin2_id and link["expires_at"] and "token" not in link
    assert users["pend"]["reset_link"]["created_by"] == admin2_id  # the setup link of the pending account
    assert users["admin2"]["reset_link"] is None
    assert boss.request("DELETE", "/api/admin/users/1/reset-link").status_code == 204
    assert boss.request("DELETE", "/api/admin/users/1/reset-link").status_code == 404  # nothing open any more
    r = TestClient(boss.app, base_url=HTTPS_URL).post("/api/auth/reset", json={"token": links["reset"], "password": ATTACKER_PASSWORD})
    assert r.status_code == 400
    events = boss.get("/api/admin/audit").json()["events"]
    assert any(e["action"] == "user.reset_link_revoked" and e["target_id"] == "1" for e in events)


def test_demoting_an_admin_voids_their_invites_and_links(planted):
    boss, admin2, admin2_id, links = planted
    r = boss.patch(f"/api/admin/users/{admin2_id}", json={"role": "user"})
    assert r.status_code == 200
    assert_links_dead(boss.app, links)
    assert [i for i in boss.get("/api/admin/invites").json()["invites"] if i["created_by"] == admin2_id] == []
    users = {u["username"]: u for u in boss.get("/api/admin/users").json()["users"]}
    assert users[ADMIN_USERNAME]["reset_link"] is None and users["pend"]["reset_link"] is None
    event = next(e for e in boss.get("/api/admin/audit").json()["events"] if e["action"] == "user.role_changed")
    assert event["details"]["links_revoked"] == 3


def test_disabling_an_admin_voids_their_invites_and_links(planted):
    boss, admin2, admin2_id, links = planted
    assert boss.patch(f"/api/admin/users/{admin2_id}", json={"status": "disabled"}).status_code == 200
    assert_links_dead(boss.app, links)


def test_deleting_an_admin_voids_their_invites_and_links_before_the_row_goes(planted):
    boss, admin2, admin2_id, links = planted
    assert boss.patch(f"/api/admin/users/{admin2_id}", json={"role": "user"}).status_code == 200
    # a fresh, still-admin admin2 again, then deleted straight away (no demotion first)
    assert boss.patch(f"/api/admin/users/{admin2_id}", json={"role": "admin"}).status_code == 200
    again = TestClient(boss.app, base_url=HTTPS_URL)
    sign_in(again, "admin2", USER_PASSWORD)
    url = again.post("/api/admin/invites", json={"role": "admin"}).json()["url"]
    reset = again.post("/api/admin/users/1/reset-link").json()["url"]
    r = boss.request("DELETE", f"/api/admin/users/{admin2_id}", json={"confirm_username": "admin2"})
    assert r.status_code == 204
    assert_links_dead(boss.app, {"invite": token_of(url, "invite"), "reset": token_of(reset, "reset"), "setup": links["setup"]})
    conn = db(boss)
    assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE created_by IS NULL AND used_at IS NULL AND purpose != 'setup'").fetchone()[0] == 0
    conn.close()


def test_a_password_change_voids_open_reset_links_for_that_account(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    url = admin.post(f"/api/admin/users/{sam_id}/reset-link").json()["url"]
    r = sam.post("/api/me/password", json={"current_password": USER_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    r = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/reset", json={"token": token_of(url, "reset"), "password": ATTACKER_PASSWORD})
    assert r.status_code == 400
    sign_in(TestClient(admin.app, base_url=HTTPS_URL), "sam", NEW_PASSWORD)


def test_redeeming_a_link_voids_the_accounts_other_links(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    first = admin.post(f"/api/admin/users/{sam_id}/reset-link").json()["url"]
    conn = db(admin)  # a second open link, e.g. one from the CLI (issuing from the API voids the old one)
    from app.auth import tokens

    second, _ = tokens.create_token(conn, tokens.RESET, ttl=__import__("datetime").timedelta(hours=1), user_id=sam_id)
    conn.commit()
    conn.close()
    person = TestClient(admin.app, base_url=HTTPS_URL)
    assert person.post("/api/auth/reset", json={"token": token_of(first, "reset"), "password": NEW_PASSWORD}).status_code == 200
    assert person.post("/api/auth/reset", json={"token": second, "password": ATTACKER_PASSWORD}).status_code == 400


def test_disabling_an_account_voids_its_reset_link_for_good(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    url = admin.post(f"/api/admin/users/{sam_id}/reset-link").json()["url"]
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"status": "disabled"}).status_code == 200
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"status": "active"}).status_code == 200
    r = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/reset", json={"token": token_of(url, "reset"), "password": NEW_PASSWORD})
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# Races: last admin, single-use links
# --------------------------------------------------------------------------- #


def _race(*calls):
    barrier = threading.Barrier(len(calls))
    results: list = [None] * len(calls)

    def run(i, fn):
        barrier.wait()
        results[i] = fn()

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


@pytest.mark.parametrize("change", [{"role": "user"}, {"status": "disabled"}])
def test_two_admins_removing_each_other_at_once_leave_one_admin(https_client, change):
    boss = https_client
    other = add_user(boss, "admin2", USER_PASSWORD, role="admin")
    other_id = other.get("/api/me").json()["id"]
    for _ in range(3):
        results = _race(
            lambda: boss.patch(f"/api/admin/users/{other_id}", json=change).status_code,
            lambda: other.patch("/api/admin/users/1", json=change).status_code,
        )
        conn = db(boss)
        admins = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'").fetchone()[0]
        conn.close()
        assert admins >= 1, results
        assert sorted(results) == [200, 409] or sorted(results) in ([200, 401], [200, 403]), results
        if admins == 2:
            break
        # restore for the next round: whichever admin is left promotes/enables the other again
        survivor = boss if boss.get("/api/admin/users").status_code == 200 else other
        target = other_id if survivor is boss else 1
        undo = {"role": "admin"} if "role" in change else {"status": "active"}
        assert survivor.patch(f"/api/admin/users/{target}", json=undo).status_code == 200
        loser = other if survivor is boss else boss
        sign_in(loser, "admin2" if loser is other else ADMIN_USERNAME, USER_PASSWORD if loser is other else ADMIN_PASSWORD)


def test_a_reset_link_cannot_be_redeemed_twice_by_racing_requests(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    url = admin.post(f"/api/admin/users/{sam_id}/reset-link").json()["url"]
    token = token_of(url, "reset")
    a, b = TestClient(admin.app, base_url=HTTPS_URL), TestClient(admin.app, base_url=HTTPS_URL)
    results = _race(
        lambda: a.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code,
        lambda: b.post("/api/auth/reset", json={"token": token, "password": ATTACKER_PASSWORD}).status_code,
    )
    assert sorted(results) == [200, 400], results


# --------------------------------------------------------------------------- #
# Sign-in floods (note 07 §9 N3 a)
# --------------------------------------------------------------------------- #


def fail(c: TestClient, username: str = "zzz"):
    return c.post("/api/auth/login", json={"username": username, "password": "wrong password " * 2})


def test_username_delay_answers_count_per_address_and_spend_no_global_slot(tmp_path, foods_json, fake_clock):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=10)
    with TestClient(create_app(settings), client=("192.0.2.2", 4000)) as attacker:
        bucket = attacker.app.state.auth.throttle.global_bucket
        for _ in range(6):
            assert fail(attacker).status_code == 401  # "zzz" is now in its 30 s delay
        before = bucket.tokens
        statuses = [fail(attacker).status_code for _ in range(10)]
        assert statuses[:4] == [429] * 4  # failures 7-10 come from the username delay ...
        assert set(statuses[4:]) == {429}  # ... and then the address itself is blocked
        assert attacker.app.state.auth.throttle.ip_wait("192.0.2.2") > 0
        assert bucket.tokens >= before - 0.01  # none of them took a slot of the instance-wide budget
        victim = TestClient(attacker.app, client=("198.51.100.9", 4000))
        sign_in(victim)  # another address still gets in


def test_https_required_answers_count_per_address(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=3)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        add_user(admin)  # two accounts: plain HTTP from the LAN is refused from now on
        lan = TestClient(admin.app, client=("192.0.2.2", 4000))
        statuses = [lan.post("/api/auth/login", json={"username": "sam", "password": USER_PASSWORD}).status_code for _ in range(4)]
        assert statuses == [400, 400, 400, 429]


def test_one_address_has_a_per_minute_attempt_budget(tmp_path, foods_json, fake_clock):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=1000)
    with TestClient(create_app(settings), client=("192.0.2.3", 4000)) as c:
        for i in range(throttle_module.IP_ATTEMPTS_PER_MINUTE):
            assert fail(c, f"name{i}").status_code == 401
        r = fail(c, "another")
        assert r.status_code == 429 and 1 <= int(r.headers["retry-after"]) <= 60
        fake_clock.advance(seconds=61)
        sign_in(c)


def test_waiting_sign_ins_do_not_stall_other_routes(tmp_path, foods_json, monkeypatch):
    """A queue of sign-ins waiting for the instance-wide budget holds no worker thread, so /healthz and
    signed-in routes keep answering (AnyIO's default pool has 40 threads)."""
    settings = make_settings(tmp_path, foods_json)
    with TestClient(create_app(settings), client=("127.0.0.1", 4000)) as c:  # an exempt (proxy) address
        sign_in(c)
        bucket = c.app.state.auth.throttle.global_bucket
        bucket.wait_s = 3.0
        bucket.rate = 1e-6  # empty budget: every sign-in waits the full 3 s, then gets 503
        bucket.tokens = 0.0
        # The same client (one event loop and one AnyIO thread pool, like a real server) from 60 threads.
        results: list[int] = []
        threads = [threading.Thread(target=lambda: results.append(fail(c, "nobody").status_code)) for _ in range(60)]
        for t in threads:
            t.start()
        time.sleep(0.5)  # every flood request is now waiting
        started = time.monotonic()
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/foods", params={"q": "apple"}).status_code == 200
        elapsed = time.monotonic() - started
        for t in threads:
            t.join(30)
        assert elapsed < 1.5, elapsed
        assert results.count(503) == 60


def test_async_bucket_waits_then_refuses():
    import anyio

    bucket = throttle_module.TokenBucket(per_minute=2, wait_s=0.2)

    async def main():
        assert await bucket.acquire_async() and await bucket.acquire_async()
        started = time.monotonic()
        assert await bucket.acquire_async() is False
        return time.monotonic() - started

    assert anyio.run(main) >= 0.19


def test_async_verify_shares_the_two_slot_gate(monkeypatch):
    import anyio

    stored = passwords.hash_password("correct horse battery staple")
    monkeypatch.setattr(passwords, "GATE_TIMEOUT_S", 0.1)
    held = [passwords._GATE.acquire(), passwords._GATE.acquire()]
    try:
        with pytest.raises(passwords.HashBusy):
            anyio.run(passwords.verify_password_async, "correct horse battery staple", stored)
    finally:
        for _ in held:
            passwords._GATE.release()
    assert anyio.run(passwords.verify_password_async, "correct horse battery staple", stored) is True


# --------------------------------------------------------------------------- #
# IPv6 clients are limited per /64
# --------------------------------------------------------------------------- #


def test_ip_key_groups_ipv6_by_64_and_unmaps_ipv4():
    key = throttle_module.ip_key
    assert key("2001:db8:1:2::1") == key("2001:db8:1:2::dead:beef") == "2001:db8:1:2::/64"
    assert key("2001:db8:1:3::1") != key("2001:db8:1:2::1")
    assert key("::ffff:192.0.2.7") == key("192.0.2.7") == "192.0.2.7"
    assert key("testclient") == "testclient" and key(None) == ""


def test_per_ip_block_covers_the_whole_ipv6_64(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=3)
    with TestClient(create_app(settings), client=("2001:db8:1:2::1", 4000)) as c:
        for i in range(3):
            assert fail(c, f"name{i}").status_code == 401
        neighbour = TestClient(c.app, client=("2001:db8:1:2::dead:beef", 4000))
        assert fail(neighbour, "other").status_code == 429
        elsewhere = TestClient(c.app, client=("2001:db8:9:9::1", 4000))
        sign_in(elsewhere)


# --------------------------------------------------------------------------- #
# AUTH_MODE=none keeps user 1
# --------------------------------------------------------------------------- #


@pytest.fixture
def none_settings(tmp_path, foods_json):
    return make_settings(tmp_path, foods_json, auth_mode="none", admin_password=None, admin_username=None)


def test_none_mode_refuses_to_delete_user_1(none_settings):
    with TestClient(create_app(none_settings)) as c:
        r = c.request("DELETE", "/api/me", json={"confirm": "DELETE"})
        assert r.status_code == 409 and "AUTH_MODE=none" in r.json()["detail"]
        assert c.get("/api/me").status_code == 200


def test_none_mode_start_recreates_a_missing_user_1(none_settings):
    with TestClient(create_app(none_settings)) as c:
        conn = db(c)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = 1")  # e.g. deleted in local mode before the switch
        conn.commit()
        conn.close()
        assert c.get("/api/me").status_code == 503
    with TestClient(create_app(none_settings)) as c:
        me = c.get("/api/me")
        assert me.status_code == 200 and me.json()["id"] == 1
        assert c.get("/api/profile").status_code == 200


def test_admin_check_reports_a_missing_user_1(none_settings):
    import io

    from app import admin as admin_cli

    with TestClient(create_app(none_settings)) as c:
        path = c.app.state.settings.db_path
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM users WHERE id = 1")
    conn.commit()
    conn.close()
    out = io.StringIO()
    args = admin_cli.build_parser().parse_args(["check"])
    args.env = {}
    assert admin_cli.cmd_check(args, none_settings, out) == 0  # a warning, not a problem
    assert "user 1 is missing" in out.getvalue()


# --------------------------------------------------------------------------- #
# A setup or reset link says whose account it is for
# --------------------------------------------------------------------------- #


def test_reset_info_names_the_account_for_the_link_holder(https_client):
    r = https_client.post("/api/admin/users", json={"username": "gran", "display_name": "Gran"})
    token = token_of(r.json()["setup_url"], "reset")
    person = TestClient(https_client.app, base_url=HTTPS_URL)
    info = person.post("/api/auth/reset/info", json={"token": token})
    assert info.status_code == 200
    assert info.json() == {"username": "gran", "display_name": "Gran", "new_account": True, "expires_at": r.json()["expires_at"]}
    assert person.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    # used: the link says nothing any more, and wrong links count toward the per-address block
    r = person.post("/api/auth/reset/info", json={"token": token})
    assert r.status_code == 400 and r.json()["field"] == "token"
    sam_url = https_client.post("/api/admin/users/1/reset-link").json()["url"]
    info = person.post("/api/auth/reset/info", json={"token": token_of(sam_url, "reset")}).json()
    assert info["username"] == ADMIN_USERNAME and info["new_account"] is False


def test_reset_info_failures_count_per_address(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=3)
    with TestClient(create_app(settings), client=("192.0.2.9", 4000)) as c:
        statuses = [c.post("/api/auth/reset/info", json={"token": f"abc{i}.def"}).status_code for i in range(4)]
        assert statuses == [400, 400, 400, 429]
