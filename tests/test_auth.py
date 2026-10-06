"""Local accounts: first-run setup, sessions and cookies, sign-in throttling, re-auth, invites,
registration modes, reset links and the plain-HTTP rule (note 07 §4.3–§4.9 and §9 N3, N6–N9, N12)."""
from __future__ import annotations

import logging
import sqlite3

import pytest

from app.auth import throttle as throttle_module
from app.config import Settings
from app.main import create_app

from conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    DAY,
    HTTPS_URL,
    USER_PASSWORD,
    TestClient,
    add_user,
    invite_token,
    make_settings,
    setup_code_from_logs,
    sign_in,
    signed_in_client,
)

NEW_PASSWORD = "violet-meadow-compass-19"
LOGIN_FAILED = {"detail": "Username or password is incorrect"}


def db(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


# --------------------------------------------------------------------------- #
# First-run setup
# --------------------------------------------------------------------------- #


def test_first_run_setup_with_the_logged_code(tmp_path, foods_json, caplog):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), TestClient(create_app(settings)) as c:
        code = setup_code_from_logs(caplog)
        assert "FIRST-RUN SETUP: open https://<this server>/#/setup" in caplog.text
        status = c.get("/api/auth/status").json()
        assert status["setup_required"] is True and status["auth_mode"] == "local" and status["password_min_length"] == 15
        body = {"code": "AAAA-BBBB-CCCC-DDDD", "username": "Mum", "display_name": "Mum", "password": ADMIN_PASSWORD}
        r = c.post("/api/auth/setup", json=body)
        assert r.status_code == 400 and "setup code" in r.json()["detail"]
        assert c.post("/api/auth/setup", json={**body, "code": code, "password": "short"}).status_code == 400
        assert c.post("/api/auth/setup", json={**body, "code": code, "username": "x"}).status_code == 400
        r = c.post("/api/auth/setup", json={**body, "code": code.lower().replace("-", " ")})  # forgiving input
        assert r.status_code == 200, r.text
        me = r.json()["user"]
        assert me["id"] == 1 and me["username"] == "Mum" and me["role"] == "admin"
        assert c.get("/api/profile").status_code == 200  # signed in by setup
        assert c.get("/api/auth/status").json()["setup_required"] is False
        assert c.post("/api/auth/setup", json={**body, "code": code}).status_code == 409  # single use
        conn = db(c)
        assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE purpose = 'setup' AND used_at IS NOT NULL").fetchone()[0] == 1
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log ORDER BY id")]
        assert "setup.completed" in actions and "login.succeeded" not in actions
        conn.close()
    # login works afterwards, with a case-insensitive username
    with TestClient(create_app(settings)) as c:
        assert sign_in(c, "MUM", ADMIN_PASSWORD)["user"]["id"] == 1


def test_setup_code_expires(tmp_path, foods_json, caplog, fake_clock):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json, setup_code_ttl_minutes=5)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"), TestClient(create_app(settings)) as c:
        code = setup_code_from_logs(caplog)
        fake_clock.advance(minutes=6)
        r = c.post("/api/auth/setup", json={"code": code, "username": "mum", "password": ADMIN_PASSWORD})
        assert r.status_code == 400


def test_setup_code_is_stored_hashed_and_regenerated_per_start(tmp_path, foods_json, caplog):
    settings = Settings(data_dir=tmp_path / "data", foods_json=foods_json)
    with caplog.at_level(logging.WARNING, logger="kidney_health.auth"):
        with TestClient(create_app(settings)) as c:
            first = setup_code_from_logs(caplog)
            conn = db(c)
            stored = conn.execute("SELECT verifier_hash FROM auth_tokens WHERE purpose = 'setup'").fetchall()
            assert len(stored) == 1 and first.encode() not in bytes(stored[0][0])
            conn.close()
        caplog.clear()
        with TestClient(create_app(settings)) as c:
            second = setup_code_from_logs(caplog)
            assert second != first
            assert c.post("/api/auth/setup", json={"code": first, "username": "mum", "password": ADMIN_PASSWORD}).status_code == 400
            assert c.post("/api/auth/setup", json={"code": second, "username": "mum", "password": ADMIN_PASSWORD}).status_code == 200


def test_admin_password_env_creates_the_admin_and_a_weak_one_stops_the_start(tmp_path, foods_json):
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:
        assert c.get("/api/me").json()["username"] == ADMIN_USERNAME
    weak = Settings(data_dir=tmp_path / "weak", foods_json=foods_json, admin_username="admin", admin_password="tooshort")
    with pytest.raises(Exception, match="ADMIN_PASSWORD does not meet the password policy"):
        with TestClient(create_app(weak)):
            pass


# --------------------------------------------------------------------------- #
# Sessions and cookies (§4.7, §9 N6)
# --------------------------------------------------------------------------- #


def test_http_login_sets_kh_session_without_secure(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    cookies = set_cookie_headers(r)
    session = next(c for c in cookies if c.startswith("kh_session="))
    attrs = {a.strip().lower() for a in session.split(";")[1:]}
    assert {"httponly", "path=/", "samesite=lax", "max-age=2592000"} <= attrs and "secure" not in attrs
    assert "domain" not in session.lower()
    device = next(c for c in cookies if c.startswith("kh_device="))
    assert "samesite=strict" in device.lower() and "max-age=31536000" in device.lower()
    token = session.split(";")[0].split("=", 1)[1]
    sid, verifier = token.split(".")
    assert len(sid) == 32 and len(verifier) >= 40
    conn = db(anon_client)
    row = conn.execute("SELECT verifier_hash, expires_at FROM sessions WHERE id = ?", (sid,)).fetchone()
    assert row is not None and verifier.encode() not in bytes(row["verifier_hash"])  # only the SHA-256 is stored
    conn.close()


def test_https_login_sets_host_prefixed_secure_cookie(settings):
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        r = c.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        session = next(x for x in set_cookie_headers(r) if x.startswith("__Host-kh_session="))
        attrs = {a.strip().lower() for a in session.split(";")[1:]}
        assert {"secure", "httponly", "path=/", "samesite=lax"} <= attrs
        assert any(x.startswith("__Host-kh_device=") for x in set_cookie_headers(r))
        assert c.get("/api/profile").status_code == 200


def test_https_behind_a_trusted_proxy_uses_the_host_cookie(settings):
    with TestClient(create_app(settings), client=("127.0.0.1", 5000)) as c:
        r = c.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
                   headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"})
        assert r.status_code == 200
        assert any(x.startswith("__Host-kh_session=") and "Secure" in x for x in set_cookie_headers(r))


def test_each_scheme_reads_only_its_own_cookie_name(settings):
    """§9 N6: a plain-HTTP page cannot toss a kh_session cookie into the HTTPS app."""
    with TestClient(create_app(settings)) as http:
        r = http.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        token = r.cookies["kh_session"]
        https = TestClient(http.app, base_url=HTTPS_URL)
        assert https.get("/api/profile", headers={"Cookie": f"kh_session={token}"}).status_code == 401
        assert https.get("/api/profile", headers={"Cookie": f"__Host-kh_session={token}"}).status_code == 200
        plain = TestClient(http.app)
        assert plain.get("/api/profile", headers={"Cookie": f"__Host-kh_session={token}"}).status_code == 401
        assert plain.get("/api/profile", headers={"Cookie": f"kh_session={token}"}).status_code == 200


def test_logout_revokes_clears_and_sends_clear_site_data(client):
    token = client.cookies["kh_session"]
    r = client.post("/api/auth/logout")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["clear-site-data"] == '"cache", "storage"'
    cleared = set_cookie_headers(r)
    assert any(c.startswith('kh_session=""') or c.startswith("kh_session=;") or "kh_session=" in c and "Max-Age=0" in c for c in cleared)
    assert any(c.startswith("__Host-kh_session=") and "Max-Age=0" in c for c in cleared)
    conn = db(client)
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (token.split(".")[0],)).fetchone()[0] == 0
    conn.close()
    stale = TestClient(client.app)
    assert stale.get("/api/profile", headers={"Cookie": f"kh_session={token}"}).status_code == 401


def test_login_rotates_the_session(client):
    first = client.cookies["kh_session"]
    sign_in(client)
    second = client.cookies["kh_session"]
    assert first.split(".")[0] != second.split(".")[0]
    conn = db(client)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1  # the pre-login session is gone
    conn.close()


def test_absolute_and_idle_expiry(settings, fake_clock):
    with signed_in_client(settings) as c:
        fake_clock.advance(days=13)
        assert c.get("/api/profile").status_code == 200  # touches last_seen_at
        fake_clock.advance(days=13)
        assert c.get("/api/profile").status_code == 200  # 26 days old, used 13 days ago
        fake_clock.advance(days=5)
        assert c.get("/api/profile").status_code == 401  # 31 days: past SESSION_MAX_DAYS
        sign_in(c)
        fake_clock.advance(days=14, seconds=1)
        assert c.get("/api/profile").status_code == 401  # idle for 14 days


def test_last_seen_is_written_at_most_every_five_minutes(client, fake_clock):
    sid = client.cookies["kh_session"].split(".")[0]
    conn = db(client)
    first = conn.execute("SELECT last_seen_at FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
    fake_clock.advance(minutes=2)
    client.get("/api/profile")
    assert conn.execute("SELECT last_seen_at FROM sessions WHERE id = ?", (sid,)).fetchone()[0] == first
    fake_clock.advance(minutes=4)
    client.get("/api/profile")
    assert conn.execute("SELECT last_seen_at FROM sessions WHERE id = ?", (sid,)).fetchone()[0] != first
    conn.close()


def test_device_list_and_revoking_other_devices(https_client):
    other = TestClient(https_client.app, base_url=HTTPS_URL)
    sign_in(other)
    sessions = https_client.get("/api/me/sessions").json()["sessions"]
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    assert {"id", "created_at", "last_seen_at", "user_agent", "ip_prefix", "current"} <= set(sessions[0])
    r = https_client.post("/api/me/sessions/revoke-others")
    assert r.status_code == 200 and r.json() == {"revoked": 1}
    assert other.get("/api/profile").status_code == 401
    assert https_client.get("/api/profile").status_code == 200
    mine = https_client.get("/api/me/sessions").json()["sessions"][0]["id"]
    assert https_client.delete(f"/api/me/sessions/{mine}").status_code == 204
    assert https_client.get("/api/profile").status_code == 401


# --------------------------------------------------------------------------- #
# Throttling (§4.9, §9 N3, N9)
# --------------------------------------------------------------------------- #


def fail(c: TestClient, username: str = ADMIN_USERNAME, **kw):
    return c.post("/api/auth/login", json={"username": username, "password": "wrong password " * 2}, **kw)


def test_delay_schedule():
    assert [throttle_module.delay_for(n) for n in range(1, 13)] == [0, 0, 0, 0, 0, 30, 60, 120, 240, 480, 900, 900]
    assert throttle_module.delay_for(99) == 900


def test_sixth_failure_is_delayed_and_success_resets(anon_client, fake_clock):
    for _ in range(5):
        r = fail(anon_client)
        assert r.status_code == 401 and r.json() == LOGIN_FAILED
    r = fail(anon_client)
    assert r.status_code == 401  # the 6th failure is counted and starts a 30 s delay
    r = anon_client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) == 30  # even the right password waits
    fake_clock.advance(seconds=31)
    r = fail(anon_client)
    assert r.status_code == 401
    r = fail(anon_client)
    assert r.status_code == 429 and int(r.headers["retry-after"]) == 60  # doubles
    fake_clock.advance(seconds=61)
    sign_in(anon_client)
    conn = db(anon_client)
    assert conn.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 0  # success forgets
    conn.close()


def test_unknown_and_known_usernames_get_identical_answers(anon_client):
    known = fail(anon_client, ADMIN_USERNAME)
    unknown = fail(anon_client, "nobody-here")
    invalid = fail(anon_client, "No Such User With Spaces")
    assert known.status_code == unknown.status_code == invalid.status_code == 401
    assert known.json() == unknown.json() == invalid.json() == LOGIN_FAILED
    conn = db(anon_client)
    # unknown names are throttled too, but only an HMAC of the name is stored, never the typed text
    rows = conn.execute("SELECT name_mac FROM login_failures").fetchall()
    assert len(rows) == 3 and all(len(bytes(r[0])) == 32 for r in rows)
    dump = "\n".join(conn.iterdump())
    assert "nobody-here" not in dump and "No Such User" not in dump
    # a failed login is audited only for an existing account
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'login.failed'").fetchone()[0] == 1
    conn.close()


def test_every_login_runs_exactly_one_hash(anon_client, monkeypatch):
    """§9 N9: unknown, disabled and password-less accounts cost the same one verify."""
    from app.auth import passwords

    calls = []
    original = passwords._verify_unlocked  # what both the sync and the async verify run
    monkeypatch.setattr(passwords, "_verify_unlocked", lambda pw, stored: calls.append(stored) or original(pw, stored))
    conn = db(anon_client)
    conn.execute(
        "INSERT INTO users (username, username_norm, status, created_at, updated_at) VALUES ('ghost', 'ghost', 'disabled', 'x', 'x')"
    )
    conn.commit()
    conn.close()
    for name in ("nobody", "ghost", ADMIN_USERNAME):
        calls.clear()
        fail(anon_client, name)
        assert len(calls) == 1, name


def test_hundred_failures_lock_the_account(anon_client):
    conn = db(anon_client)
    mac = anon_client.app.state.auth.throttle.name_mac(ADMIN_USERNAME)
    conn.execute(
        "INSERT INTO login_failures (name_mac, consecutive, locked_until, last_failure_at) VALUES (?, 99, NULL, '2026-01-01T00:00:00.000000Z')",
        (mac,),
    )
    conn.commit()
    assert fail(anon_client).status_code == 401
    assert conn.execute("SELECT status FROM users WHERE id = 1").fetchone()[0] == "locked"
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'user.locked'").fetchone()[0] == 1
    conn.execute("DELETE FROM login_failures")
    conn.commit()
    conn.close()
    r = anon_client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 401 and r.json() == LOGIN_FAILED  # locked: same generic answer


def test_per_ip_block_after_too_many_failures(tmp_path, foods_json, fake_clock):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=4)
    with TestClient(create_app(settings), client=("198.51.100.7", 4000)) as c:
        for i in range(4):
            assert fail(c, f"name{i}").status_code == 401  # different names: no username delay
        r = c.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 429 and 590 <= int(r.headers["retry-after"]) <= 600
        assert c.post("/api/auth/reset", json={"token": "a.b", "password": NEW_PASSWORD}).status_code == 429
        other = TestClient(c.app, client=("198.51.100.8", 4000))
        sign_in(other)  # another address is not blocked
        fake_clock.advance(minutes=11)
        sign_in(c)


def test_per_ip_layer_is_skipped_for_proxy_and_gateway_addresses(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, login_ip_max_failures=2)
    with TestClient(create_app(settings), client=("127.0.0.1", 4000)) as c:  # the proxy's own address
        for i in range(4):
            assert fail(c, f"name{i}").status_code == 401
        sign_in(c)
    assert c.app.state.auth.throttle.ip_exempt("10.0.2.100")  # slirp4netns: every client looks like this


def test_device_cookie_skips_the_username_delay(anon_client):
    sign_in(anon_client)  # gets a device cookie for the admin
    attacker = TestClient(anon_client.app)
    for _ in range(7):
        fail(attacker)
    assert attacker.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}).status_code == 429
    # the owner's own device still gets in, and its failures do not feed the account counter
    assert fail(anon_client).status_code == 401
    sign_in(anon_client)


def test_device_cookie_is_void_after_ten_failures(anon_client):
    sign_in(anon_client)
    for _ in range(10):
        assert fail(anon_client).status_code == 401
    # now the device cookie is void, so the account's username counter applies again
    for _ in range(6):
        fail(anon_client)
    assert anon_client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}).status_code == 429


def test_hashing_overload_answers_503(anon_client, monkeypatch):
    from app.auth import passwords

    monkeypatch.setattr(passwords, "GATE_TIMEOUT_S", 0.1)
    held = [passwords._GATE.acquire(), passwords._GATE.acquire()]  # both hashing slots busy
    try:
        r = fail(anon_client)
    finally:
        for _ in held:
            passwords._GATE.release()
    assert r.status_code == 503 and r.headers["retry-after"] == "1"


# --------------------------------------------------------------------------- #
# Re-authentication (§4.5, §9 N7)
# --------------------------------------------------------------------------- #


def test_sensitive_actions_need_a_recent_password(client, fake_clock):
    assert client.get("/api/me/export.zip").status_code == 200  # signed in moments ago
    fake_clock.advance(minutes=11)
    r = client.get("/api/me/export.zip")
    assert r.status_code == 403 and r.json() == {"detail": "Please enter your password again", "reauth_required": True}
    assert client.post("/api/admin/invites", json={}).json()["reauth_required"] is True
    r = client.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/me/export.zip").status_code == 200


def test_reauth_failures_count_and_revoke_the_session(client):
    for _ in range(4):
        r = client.post("/api/auth/reauth", json={"password": "not my password at all"})
        assert r.status_code == 403
    r = client.post("/api/auth/reauth", json={"password": "not my password at all"})
    assert r.status_code == 401
    assert client.get("/api/profile").status_code == 401
    conn = db(client)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'session.revoked_reauth'").fetchone()[0] == 1
    # they also count toward the account's username delay
    assert conn.execute("SELECT consecutive FROM login_failures").fetchone()[0] == 5
    conn.close()


# --------------------------------------------------------------------------- #
# Passwords: change, must-change (§4.6, §9 N8)
# --------------------------------------------------------------------------- #


def test_password_change_needs_the_current_one_and_signs_out_other_devices(https_client):
    other = TestClient(https_client.app, base_url=HTTPS_URL)
    sign_in(other)
    old_sid = https_client.cookies["__Host-kh_session"].split(".")[0]
    r = https_client.post("/api/me/password", json={"current_password": "wrong wrong wrong", "new_password": NEW_PASSWORD})
    assert r.status_code == 403
    r = https_client.post("/api/me/password", json={"current_password": ADMIN_PASSWORD, "new_password": "123456789012345"})
    assert r.status_code == 400 and "problems" in r.json()
    r = https_client.post("/api/me/password", json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200, r.text
    assert https_client.cookies["__Host-kh_session"].split(".")[0] != old_sid  # rotated
    assert https_client.get("/api/profile").status_code == 200
    assert other.get("/api/profile").status_code == 401
    assert TestClient(https_client.app, base_url=HTTPS_URL).post(
        "/api/auth/login", json={"username": ADMIN_USERNAME, "password": NEW_PASSWORD}).status_code == 200


def test_must_change_password_is_enforced_by_the_server(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"must_change_password": True}).status_code == 200
    r = sam.get("/api/profile")
    assert r.status_code == 403 and r.json() == {"detail": "Choose a new password first", "password_change_required": True}
    assert sam.get("/api/me").status_code == 403
    assert sam.get("/api/auth/status").json()["user"]["must_change_password"] is True
    r = sam.post("/api/me/password", json={"current_password": USER_PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    assert sam.get("/api/profile").status_code == 200


# --------------------------------------------------------------------------- #
# Invites and registration modes (§3.9, §4.5)
# --------------------------------------------------------------------------- #


def test_invite_is_single_use_fragment_link_and_revocable(https_client):
    r = https_client.post("/api/admin/invites", json={"role": "user", "note": "for Mum"})
    assert r.status_code == 201
    data = r.json()
    assert data["url"].startswith("https://localhost/#/invite/")  # the token travels in the fragment
    token = data["url"].split("/#/invite/")[1]
    conn = db(https_client)
    stored = conn.execute("SELECT verifier_hash, note FROM auth_tokens WHERE id = ?", (data["invite"]["id"],)).fetchone()
    assert token.split(".")[1].encode() not in bytes(stored[0]) and stored[1] == "for Mum"
    conn.close()
    listed = https_client.get("/api/admin/invites").json()["invites"]
    assert listed[0]["state"] == "open" and "url" not in listed[0] and "token" not in listed[0]

    newcomer = TestClient(https_client.app, base_url=HTTPS_URL)
    body = {"token": token, "username": "mum", "display_name": "Mum", "password": USER_PASSWORD}
    r = newcomer.post("/api/auth/register", json=body)
    assert r.status_code == 201 and r.json()["user"]["role"] == "user"
    assert newcomer.get("/api/profile").status_code == 200
    again = TestClient(https_client.app, base_url=HTTPS_URL)
    assert again.post("/api/auth/register", json={**body, "username": "mum2"}).status_code == 400
    assert https_client.get("/api/admin/invites").json()["invites"][0]["state"] == "used"

    revoked = invite_token(https_client)
    invite_id = revoked.split(".")[0]
    assert https_client.delete(f"/api/admin/invites/{invite_id}").status_code == 204
    assert https_client.delete(f"/api/admin/invites/{invite_id}").status_code == 404
    assert again.post("/api/auth/register", json={**body, "token": revoked, "username": "mum3"}).status_code == 400


def test_invites_expire_and_can_grant_admin(https_client, fake_clock):
    token = invite_token(https_client, role="admin")
    fake_clock.advance(days=8)
    newcomer = TestClient(https_client.app, base_url=HTTPS_URL)
    body = {"token": token, "username": "late", "password": USER_PASSWORD}
    assert newcomer.post("/api/auth/register", json=body).status_code == 400
    sign_in(https_client)
    token = invite_token(https_client, role="admin")
    assert newcomer.post("/api/auth/register", json={**body, "token": token}).json()["user"]["role"] == "admin"


def test_registration_needs_an_invite_and_names_are_unique(https_client):
    anon = TestClient(https_client.app, base_url=HTTPS_URL)
    r = anon.post("/api/auth/register", json={"username": "walkin", "password": USER_PASSWORD})
    assert r.status_code == 403 and "invite" in r.json()["detail"]
    token = invite_token(https_client)
    r = anon.post("/api/auth/register", json={"token": token, "username": "ADMIN", "password": USER_PASSWORD})
    assert r.status_code == 409


def test_closed_and_open_registration(https_client, monkeypatch):
    assert https_client.patch("/api/admin/settings", json={"registration.mode": "closed"}).status_code == 200
    assert https_client.post("/api/admin/invites", json={}).status_code == 409
    anon = TestClient(https_client.app, base_url=HTTPS_URL)
    assert anon.post("/api/auth/register", json={"username": "walkin", "password": USER_PASSWORD}).status_code == 403
    assert anon.get("/api/auth/status").json()["registration"] == "closed"

    assert https_client.patch("/api/admin/settings", json={"registration.mode": "open"}).status_code == 200
    for i in range(3):
        r = TestClient(https_client.app, base_url=HTTPS_URL).post(
            "/api/auth/register", json={"username": f"walkin{i}", "password": USER_PASSWORD})
        assert r.status_code == 201, r.text
    r = TestClient(https_client.app, base_url=HTTPS_URL).post("/api/auth/register", json={"username": "walkin9", "password": USER_PASSWORD})
    assert r.status_code == 429  # 3 per address per hour
    http = TestClient(https_client.app)
    r = http.post("/api/auth/register", json={"username": "plain", "password": USER_PASSWORD})
    assert r.status_code == 400 and r.json()["https_required"] is True


# --------------------------------------------------------------------------- #
# Plain HTTP (§4.3 ALLOW_INSECURE_HTTP)
# --------------------------------------------------------------------------- #


def test_second_account_needs_https_unless_allowed(client):
    token = invite_token(client)
    newcomer = TestClient(client.app)
    r = newcomer.post("/api/auth/register", json={"token": token, "username": "sam", "password": USER_PASSWORD})
    assert r.status_code == 400 and r.json()["https_required"] is True
    loopback = TestClient(client.app, client=("127.0.0.1", 1234))  # localhost counts as secure
    r = loopback.post("/api/auth/register", json={"token": token, "username": "sam", "password": USER_PASSWORD})
    assert r.status_code == 201
    # with two accounts, signing in over non-loopback plain HTTP is refused
    status = TestClient(client.app).get("/api/auth/status").json()
    assert status["insecure_http"] is True and status["https_required"] is True
    r = TestClient(client.app).post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 400 and r.json()["https_required"] is True
    sign_in(TestClient(client.app, base_url=HTTPS_URL))


def test_allow_insecure_http_true_permits_plain_http(tmp_path, foods_json):
    with signed_in_client(make_settings(tmp_path, foods_json, allow_insecure_http=True)) as c:
        add_user(c)
        sign_in(TestClient(c.app))


# --------------------------------------------------------------------------- #
# Reset links and admin account management (§4.5, §9 N12)
# --------------------------------------------------------------------------- #


def test_admin_reset_link_unlocks_signs_out_and_is_noticed(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    conn = db(admin)
    conn.execute("UPDATE users SET status = 'locked' WHERE id = ?", (sam_id,))
    conn.commit()
    assert sam.get("/api/profile").status_code == 401
    r = admin.post(f"/api/admin/users/{sam_id}/reset-link")
    assert r.status_code == 200 and "/#/reset/" in r.json()["url"]
    token = r.json()["url"].split("/#/reset/")[1]
    person = TestClient(admin.app, base_url=HTTPS_URL)
    assert person.post("/api/auth/reset", json={"token": token, "password": "123456789012345"}).status_code == 400
    r = person.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["username"] == "sam"
    assert person.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 400
    assert conn.execute("SELECT status FROM users WHERE id = ?", (sam_id,)).fetchone()[0] == "active"
    conn.close()
    fresh = TestClient(admin.app, base_url=HTTPS_URL)
    login = fresh.post("/api/auth/login", json={"username": "sam", "password": NEW_PASSWORD}).json()
    # N12: the next password sign-in says an admin's link changed the password (whoever used it) ...
    assert "reset with a link from an admin" in login["notice"]
    # ... once
    again = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "sam", "password": NEW_PASSWORD})
    assert again.json()["notice"] is None
    activity = fresh.get("/api/me/activity").json()["events"]
    assert any(e["action"] == "user.password_changed" and e["details"]["via"] == "admin_reset_link" for e in activity)


def test_reset_notice_shows_at_the_next_sign_in(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    url = admin.post(f"/api/admin/users/{sam_id}/reset-link").json()["url"]
    admin_side = TestClient(admin.app, base_url=HTTPS_URL)  # e.g. the admin used the link themselves
    assert admin_side.post("/api/auth/reset", json={"token": url.split("/#/reset/")[1], "password": NEW_PASSWORD}).status_code == 200
    assert admin_side.get("/api/me").json()["username"] == "sam"  # the link signed its holder in
    # no clock tricks: the reset's own sign-in does not hide the notice from Sam's next sign-in
    login = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "sam", "password": NEW_PASSWORD})
    assert "reset with a link from an admin" in login.json()["notice"]
    # a reset link Sam asked the CLI for (no admin) or a self-service change gives no notice
    sam2 = TestClient(admin.app, base_url=HTTPS_URL)
    sign_in(sam2, "sam", NEW_PASSWORD)
    assert sam2.post("/api/me/password", json={"current_password": NEW_PASSWORD, "new_password": USER_PASSWORD}).status_code == 200
    login = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "sam", "password": USER_PASSWORD})
    assert login.json()["notice"] is None


def test_admin_creates_an_account_with_a_setup_link(https_client):
    r = https_client.post("/api/admin/users", json={"username": "grandad", "display_name": "Grandad"})
    assert r.status_code == 201
    user, url = r.json()["user"], r.json()["setup_url"]
    assert user["status"] == "pending_setup" and user["has_password"] is False and "/#/reset/" in url
    person = TestClient(https_client.app, base_url=HTTPS_URL)
    assert person.post("/api/auth/login", json={"username": "grandad", "password": NEW_PASSWORD}).status_code == 401
    r = person.post("/api/auth/reset", json={"token": url.split("/#/reset/")[1], "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Grandad"
    assert https_client.post("/api/admin/users", json={"username": "GRANDAD"}).status_code == 409


def test_roles_disable_enable_and_the_last_admin_guard(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    r = admin.patch("/api/admin/users/1", json={"role": "user"})
    assert r.status_code == 409 and "only admin" in r.json()["detail"]
    assert admin.patch("/api/admin/users/1", json={"status": "disabled"}).status_code == 409
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"status": "disabled"}).json()["user"]["status"] == "disabled"
    assert sam.get("/api/profile").status_code == 401  # signed out everywhere
    r = TestClient(admin.app, base_url=HTTPS_URL).post("/api/auth/login", json={"username": "sam", "password": USER_PASSWORD})
    assert r.status_code == 401 and r.json() == LOGIN_FAILED
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"status": "active"}).status_code == 200
    sam2 = TestClient(admin.app, base_url=HTTPS_URL)
    sign_in(sam2, "sam", USER_PASSWORD)
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"role": "admin"}).json()["user"]["role"] == "admin"
    assert sam2.get("/api/profile").status_code == 401  # role change rotates (signs out) their sessions
    sign_in(sam2, "sam", USER_PASSWORD)
    assert sam2.get("/api/admin/users").status_code == 200
    # now there are two admins, so the first one may step down
    assert admin.patch("/api/admin/users/1", json={"role": "user"}).status_code == 200
    assert admin.get("/api/admin/users").status_code == 403
    actions = [e["action"] for e in sam2.get("/api/admin/audit").json()["events"]]
    assert {"user.disabled", "user.enabled", "user.role_changed"} <= set(actions)


def test_admin_deletes_an_account_with_typed_confirmation(two_clients):
    admin, sam = two_clients
    sam_id = sam.get("/api/me").json()["id"]
    sam.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": 1})
    r = admin.request("DELETE", f"/api/admin/users/{sam_id}", json={"confirm_username": "someone"})
    assert r.status_code == 400
    assert admin.request("DELETE", "/api/admin/users/1", json={"confirm_username": "admin"}).status_code == 409
    assert admin.request("DELETE", f"/api/admin/users/{sam_id}", json={"confirm_username": "SAM"}).status_code == 204
    assert sam.get("/api/profile").status_code == 401
    conn = db(admin)
    assert conn.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'user.deleted'").fetchone()[0] == 1
    conn.close()
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"role": "user"}).status_code == 404


def test_housekeeping_runs_hourly_and_daily_from_requests(client, fake_clock):
    conn = db(client)
    conn.execute(
        "INSERT INTO sessions (id, user_id, verifier_hash, created_at, last_seen_at, expires_at) VALUES (?, 1, x'00', ?, ?, ?)",
        ("f" * 32, "2000-01-01T00:00:00.000000Z", "2000-01-01T00:00:00.000000Z", "2000-02-01T00:00:00.000000Z"),
    )
    conn.execute("INSERT INTO audit_log (at, action) VALUES ('2000-01-01T00:00:00.000000Z', 'login.failed')")
    conn.commit()
    client.get("/api/profile")  # first request: start-up just cleaned, nothing due yet
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
    fake_clock.advance(hours=1, seconds=1)
    client.get("/api/profile")
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1  # expired row purged hourly
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE at < '2001'").fetchone()[0] == 1
    fake_clock.advance(days=1)
    sign_in(client)  # a day later (the session itself went idle-old in fake time is fine: sign in again)
    client.get("/api/profile")
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE at < '2001'").fetchone()[0] == 0  # daily retention
    conn.close()


def test_instance_wide_cap_waits_then_refuses():
    import time

    bucket = throttle_module.TokenBucket(per_minute=2, wait_s=0.2)
    assert bucket.acquire() and bucket.acquire()
    started = time.monotonic()
    assert bucket.acquire() is False  # queued for up to wait_s, then refused (the route answers 503)
    assert time.monotonic() - started >= 0.19
