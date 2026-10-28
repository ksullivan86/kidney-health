"""Two-step sign-in (design note 17): the RFC vectors, the codes, the routes, sign-in, reset links, the admin and CLI ways out.

Covered: RFC 4226 and RFC 6238 test vectors; the ±1 step window and that a code works once; recovery codes (format, single use,
typed with dashes, spaces or capitals); turning it on (re-auth, a code from the pending secret, other sessions signed out, codes
shown once), renewing codes and turning it off; every row of note 17 §5 (no code is a 401 that is not counted, a wrong code is
counted like a wrong password, a recovery code signs in once and says how many are left); reset links do not skip the second
step; the admin's removal and ``two_step`` in the people list; 404 outside local mode; the sealed secret (no plain secret in the
database, a moved row does not decrypt, key rotation keeps it working); the CLI; account deletion.
"""
from __future__ import annotations

import io
import sqlite3
from typing import Any

import pytest

from app.auth import clock, totp
from app.auth.throttle import FREE_FAILURES
from app.config import Settings
from app.main import create_app
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, USER_PASSWORD, FakeClock, TestClient, add_user, make_settings

NEW_PASSWORD = "meadow-copper-violin-41"


# --------------------------------------------------------------------------- #
# The algorithm
# --------------------------------------------------------------------------- #


def test_hotp_matches_rfc_4226_appendix_d() -> None:
    key = b"12345678901234567890"
    want = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
    assert [totp.hotp(key, i) for i in range(10)] == want


@pytest.mark.parametrize(("seconds", "code"), [
    (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130"),
])
def test_totp_matches_rfc_6238_appendix_b_sha1(seconds: int, code: str) -> None:
    assert totp.totp(b"12345678901234567890", seconds, digits=8) == code


def test_the_secret_is_160_bits_shown_as_32_base32_letters() -> None:
    key = totp.new_secret()
    text = totp.secret_text(key)
    assert len(key) == 20 and len(text) == 32 and text.isupper() and "=" not in text
    assert totp.secret_from_text(text.lower()) == key
    assert totp.secret_from_text(" ".join(text[i:i + 4] for i in range(0, 32, 4))) == key  # as an app shows it, in groups


def test_the_otpauth_link_is_what_authenticator_apps_read() -> None:
    key = b"12345678901234567890"
    uri = totp.otpauth_uri(key, issuer="Kidney Health", account="sam@home")
    assert uri == ("otpauth://totp/Kidney%20Health:sam@home?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&issuer=Kidney%20Health"
                   "&algorithm=SHA1&digits=6&period=30")


def test_a_code_is_good_for_one_step_either_side_and_works_once() -> None:
    key = totp.new_secret()
    now = 1_800_000_015.0
    step = totp.step_at(now)
    for offset in (-1, 0, 1):
        assert totp.matching_step(key, totp.hotp(key, step + offset), seconds=now, after_step=0) == step + offset
    for offset in (-2, 2):
        assert totp.matching_step(key, totp.hotp(key, step + offset), seconds=now, after_step=0) is None
    code = totp.hotp(key, step)
    assert totp.matching_step(key, code, seconds=now, after_step=step) is None  # used already
    assert totp.matching_step(key, totp.hotp(key, step - 1), seconds=now, after_step=step) is None  # older than the last used
    assert totp.matching_step(key, "12345", seconds=now, after_step=0) is None
    assert totp.matching_step(key, "１２３４５６", seconds=now, after_step=0) is None  # digits are ASCII only


def test_recovery_codes_are_ten_different_codes_without_look_alike_letters() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == len(set(codes)) == 10
    for code in codes:
        assert len(code) == 11 and code[5] == "-"
        cleaned = totp.clean_code(code)
        assert totp.looks_like_recovery_code(cleaned) and not set(cleaned) & set("ilo01")
    assert totp.clean_code(" ABCDE - fghjk ") == "abcdefghjk"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def code_now(secret: str, *, offset_steps: int = 0) -> str:
    return totp.hotp(totp.secret_from_text(secret), totp.step_at(clock.seconds()) + offset_steps)


def turn_on(client: TestClient, fake_clock: FakeClock | None = None) -> tuple[str, list[str]]:
    """Setup and enable for the client's person; returns (secret, recovery codes)."""
    r = client.post("/api/me/totp/setup")
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = client.post("/api/me/totp/enable", json={"code": code_now(secret)})
    assert r.status_code == 200, r.text
    if fake_clock is not None:
        fake_clock.advance(seconds=30)  # the next code is a new step
    return secret, r.json()["recovery_codes"]


def login(app: Any, password: str = ADMIN_PASSWORD, code: str | None = None, username: str = ADMIN_USERNAME,
          client: TestClient | None = None) -> Any:
    c = client or TestClient(app)
    body: dict[str, Any] = {"username": username, "password": password}
    if code is not None:
        body["code"] = code
    return c.post("/api/auth/login", json=body)


def audit_actions(app: Any) -> list[tuple[str, str | None]]:
    db = app.state.settings.db_path
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT action, details_json FROM audit_log ORDER BY id").fetchall()


# --------------------------------------------------------------------------- #
# Turning it on and off
# --------------------------------------------------------------------------- #


def test_off_until_the_person_types_a_code_from_the_new_secret(client: TestClient, fake_clock: FakeClock) -> None:
    assert client.get("/api/me/totp").json() == {"available": True, "enabled": False, "enabled_at": None, "recovery_codes_left": 0}
    r = client.post("/api/me/totp/setup")
    assert r.status_code == 200
    got = r.json()
    assert got["uri"].startswith("otpauth://totp/Kidney%20Health:admin?secret=" + got["secret"])
    assert got["account"] == "admin" and got["digits"] == 6 and got["period"] == 30
    assert client.get("/api/me/totp").json()["enabled"] is False
    assert login(client.app).status_code == 200  # a setup not finished changes nothing

    r = client.post("/api/me/totp/enable", json={"code": "000000" if code_now(got["secret"]) != "000000" else "111111"})
    assert r.status_code == 400 and r.json()["field"] == "code"
    other = TestClient(client.app)
    assert login(client.app, client=other).status_code == 200  # another device, signed in before

    r = client.post("/api/me/totp/enable", json={"code": code_now(got["secret"])})
    assert r.status_code == 200
    body = r.json()
    assert len(body["recovery_codes"]) == 10 and body["signed_out"] >= 1
    assert body["enabled"] is True and body["recovery_codes_left"] == 10
    assert other.get("/api/me").status_code == 401  # signed out
    assert client.get("/api/me").status_code == 200  # this device stays signed in
    assert client.post("/api/me/totp/setup").status_code == 409
    assert client.post("/api/me/totp/enable", json={"code": "123456"}).status_code == 409
    status = client.get("/api/me/totp").json()
    assert status["enabled"] is True and status["enabled_at"] and "secret" not in status


def test_enable_needs_a_setup_and_limits_tries(client: TestClient) -> None:
    assert client.post("/api/me/totp/enable", json={"code": "123456"}).status_code == 409  # counts as one of the 10 tries
    client.post("/api/me/totp/setup")
    codes = [client.post("/api/me/totp/enable", json={"code": "abcdef"}).status_code for _ in range(10)]
    assert codes[:9] == [400] * 9 and codes[9] == 429


def test_every_change_needs_the_password_again(client: TestClient, fake_clock: FakeClock) -> None:
    turn_on(client, fake_clock)
    fake_clock.advance(minutes=client.app.state.settings.reauth_minutes + 1)
    for method, path in (("post", "/api/me/totp/setup"), ("post", "/api/me/totp/recovery-codes"), ("delete", "/api/me/totp")):
        r = client.request(method, path)
        assert r.status_code == 403 and r.json().get("reauth_required") is True, path
    assert client.get("/api/me/totp").status_code == 200  # reading the status needs no re-auth


def test_new_recovery_codes_replace_the_old_set_and_turning_off_removes_it(client: TestClient, fake_clock: FakeClock) -> None:
    secret, old = turn_on(client, fake_clock)
    r = client.post("/api/me/totp/recovery-codes")
    assert r.status_code == 200
    new = r.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    assert login(client.app, code=old[0]).status_code == 401
    assert login(client.app, code=new[0]).status_code == 200

    assert client.delete("/api/me/totp").status_code == 204
    assert client.get("/api/me/totp").json()["enabled"] is False
    assert client.post("/api/me/totp/recovery-codes").status_code == 409
    assert login(client.app).status_code == 200  # the password alone again
    assert client.delete("/api/me/totp").status_code == 204  # already off: nothing to do
    actions = [a for a, _ in audit_actions(client.app)]
    assert actions.count("totp.enabled") == 1 and actions.count("totp.disabled") == 1
    assert "totp.recovery_codes_renewed" in actions and "totp.recovery_code_used" in actions


# --------------------------------------------------------------------------- #
# Sign-in (note 17 §5)
# --------------------------------------------------------------------------- #


def test_sign_in_asks_for_the_code_after_the_right_password(client: TestClient, fake_clock: FakeClock) -> None:
    secret, _ = turn_on(client, fake_clock)
    app = client.app

    r = login(app, password="not-the-password")
    assert r.status_code == 401 and r.json() == {"detail": "Username or password is incorrect"}  # nothing about codes
    r = login(app, password="not-the-password", code=code_now(secret))
    assert r.status_code == 401 and "totp_required" not in r.json()

    r = login(app)
    assert r.status_code == 401
    assert r.json() == {"detail": "Enter the 6-digit code from your authenticator app.", "totp_required": True, "field": "code"}
    assert login(app, code="  ").json().get("totp_required") is True

    r = login(app, code="000000" if code_now(secret) != "000000" else "111111")
    assert r.status_code == 401 and r.json()["totp_required"] is True and r.json()["field"] == "code"
    assert "recovery code" in r.json()["detail"]

    code = code_now(secret)
    c = TestClient(app)
    r = login(app, code=f"{code[:3]} {code[3:]}", client=c)  # as an app shows it
    assert r.status_code == 200 and r.json()["user"]["username"] == ADMIN_USERNAME
    assert c.get("/api/me").status_code == 200
    assert login(app, code=code).status_code == 401  # the same code does not work twice
    fake_clock.advance(seconds=30)
    assert login(app, code=code_now(secret)).status_code == 200

    failed = [d for a, d in audit_actions(app) if a == "login.failed"]
    assert sum('"via":"code"' in (d or "") for d in failed) == 2  # the two wrong codes, not the missing ones


def test_wrong_codes_slow_down_like_wrong_passwords(client: TestClient, fake_clock: FakeClock) -> None:
    secret, _ = turn_on(client, fake_clock)
    wrong = "000000" if code_now(secret) != "000000" else "111111"
    for _ in range(FREE_FAILURES + 1):  # the free ones, then the first that sets a delay
        assert login(client.app, code=wrong).status_code == 401
    r = login(client.app, code=code_now(secret))  # even the right code waits now
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_a_missing_code_is_not_counted(client: TestClient, fake_clock: FakeClock) -> None:
    secret, _ = turn_on(client, fake_clock)
    for _ in range(FREE_FAILURES + 2):
        assert login(client.app).status_code == 401
    assert login(client.app, code=code_now(secret)).status_code == 200


def test_a_recovery_code_signs_in_once_and_says_how_many_are_left(client: TestClient, fake_clock: FakeClock) -> None:
    _, codes = turn_on(client, fake_clock)
    r = login(client.app, code=codes[0].upper().replace("-", " "))
    assert r.status_code == 200 and r.json()["notice"] == "You signed in with a recovery code. 9 are left."
    assert login(client.app, code=codes[0]).status_code == 401
    for code in codes[1:9]:
        assert login(client.app, code=code).status_code == 200
    r = login(client.app, code=codes[9])
    assert r.status_code == 200 and "last recovery code" in r.json()["notice"]
    assert client.get("/api/me/totp").json()["recovery_codes_left"] == 0


def test_the_code_field_has_a_length_limit(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "code": "1" * 33})
    assert r.status_code in (400, 422)


def test_a_person_without_two_step_sign_in_is_not_asked(client: TestClient) -> None:
    assert login(client.app, code="123456").status_code == 200  # a stray code is ignored


# --------------------------------------------------------------------------- #
# Reset links, other people, the admin
# --------------------------------------------------------------------------- #


@pytest.fixture
def pair(https_client: TestClient) -> tuple[TestClient, TestClient]:
    return https_client, add_user(https_client)


def sam_id(admin: TestClient) -> int:
    return next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["username"] == "sam")


def test_a_reset_link_sets_the_password_but_does_not_skip_the_code(pair: tuple[TestClient, TestClient], fake_clock: FakeClock) -> None:
    admin, sam = pair
    secret, _ = turn_on(sam, fake_clock)
    url = admin.post(f"/api/admin/users/{sam_id(admin)}/reset-link").json()["url"]
    holder = TestClient(admin.app, base_url=str(admin.base_url).rstrip("/"))
    r = holder.post("/api/auth/reset", json={"token": url.split("/#/reset/")[1], "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json() == {"user": None, "totp_required": True}
    assert holder.get("/api/me").status_code == 401  # not signed in
    base = str(admin.base_url).rstrip("/")
    assert login(admin.app, password=NEW_PASSWORD, username="sam", client=TestClient(admin.app, base_url=base)).json()["totp_required"]
    r = login(admin.app, password=NEW_PASSWORD, username="sam", code=code_now(secret), client=TestClient(admin.app, base_url=base))
    assert r.status_code == 200


def test_one_persons_two_step_sign_in_is_their_own(pair: tuple[TestClient, TestClient], fake_clock: FakeClock) -> None:
    admin, sam = pair
    turn_on(sam, fake_clock)
    assert admin.get("/api/me/totp").json()["enabled"] is False
    base = str(admin.base_url).rstrip("/")
    assert login(admin.app, client=TestClient(admin.app, base_url=base)).status_code == 200  # the admin is not asked
    people = {u["username"]: u["two_step"] for u in admin.get("/api/admin/users").json()["users"]}
    assert people == {"admin": False, "sam": True}


def test_an_admin_can_remove_it_for_someone_who_lost_their_phone(pair: tuple[TestClient, TestClient], fake_clock: FakeClock) -> None:
    admin, sam = pair
    turn_on(sam, fake_clock)
    sid = sam_id(admin)
    assert sam.delete(f"/api/admin/users/{sid}/totp").status_code == 403  # admins only
    assert admin.delete("/api/admin/users/99999/totp").status_code == 404
    r = admin.delete(f"/api/admin/users/{sid}/totp")
    assert r.status_code == 200 and r.json() == {"removed": True}
    assert admin.delete(f"/api/admin/users/{sid}/totp").json() == {"removed": False}
    base = str(admin.base_url).rstrip("/")
    assert login(admin.app, password=USER_PASSWORD, username="sam", client=TestClient(admin.app, base_url=base)).status_code == 200
    details = [d for a, d in audit_actions(admin.app) if a == "totp.disabled"]
    assert len(details) == 1 and '"via":"admin"' in details[0]


def test_deleting_the_account_deletes_its_two_step_rows(pair: tuple[TestClient, TestClient], fake_clock: FakeClock) -> None:
    admin, sam = pair
    turn_on(sam, fake_clock)
    sid = sam_id(admin)
    assert admin.request("DELETE", f"/api/admin/users/{sid}", json={"confirm_username": "sam"}).status_code == 204
    with sqlite3.connect(admin.app.state.settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM totp_factors WHERE user_id = ?", (sid,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM totp_recovery_codes WHERE user_id = ?", (sid,)).fetchone()[0] == 0


def test_not_offered_without_local_sign_in(tmp_path: Any, foods_json: Any) -> None:
    settings: Settings = make_settings(tmp_path, foods_json, auth_mode="none")
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/me/totp").json() == {"available": False, "enabled": False, "enabled_at": None, "recovery_codes_left": 0}
        for method, path in (("post", "/api/me/totp/setup"), ("post", "/api/me/totp/enable"), ("post", "/api/me/totp/recovery-codes"),
                             ("delete", "/api/me/totp")):
            r = c.request(method, path, json={"code": "123456"} if path.endswith("enable") else None)
            assert r.status_code == 404, path


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


def test_the_secret_is_sealed_and_bound_to_its_owner(pair: tuple[TestClient, TestClient], fake_clock: FakeClock) -> None:
    admin, sam = pair
    secret, codes = turn_on(sam, fake_clock)
    sid = sam_id(admin)
    raw = open(admin.app.state.settings.db_path, "rb").read()
    assert secret.encode() not in raw and codes[0].encode() not in raw and codes[0].replace("-", "").encode() not in raw
    keyring = admin.app.state.auth.keyring
    with sqlite3.connect(admin.app.state.settings.db_path) as conn:
        conn.row_factory = sqlite3.Row
        assert totp.load(conn, keyring, sid).key == totp.secret_from_text(secret)
        row = conn.execute("SELECT secret_enc FROM totp_factors WHERE user_id = ?", (sid,)).fetchone()
        conn.execute("INSERT INTO totp_factors (user_id, secret_enc, created_at, enabled_at) VALUES (1, ?, 'x', 'x')", (row["secret_enc"],))
        assert totp.load(conn, keyring, 1).key is None  # a copied row does not decrypt for another person


def test_key_rotation_keeps_the_codes_working(client: TestClient, fake_clock: FakeClock) -> None:
    from app.crypto import Keyring, new_key_line, reencrypt_all

    secret, _ = turn_on(client, fake_clock)
    old = client.app.state.auth.keyring
    with sqlite3.connect(client.app.state.settings.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rotated = Keyring([new_key_line(), *[m.decode() for m in old._masters]])
        assert reencrypt_all(conn, rotated)["reencrypted"] >= 1
        conn.commit()
        assert totp.load(conn, Keyring([rotated._masters[0].decode()]), 1).key == totp.secret_from_text(secret)


def test_the_cli_removes_it(client: TestClient, fake_clock: FakeClock) -> None:
    from app import admin as cli

    turn_on(client, fake_clock)
    env = {"DATA_DIR": str(client.app.state.settings.data_dir)}
    out = io.StringIO()
    assert cli.main(["remove-two-step", ADMIN_USERNAME], env=env, out=out) == 0
    assert "removed" in out.getvalue()
    assert client.get("/api/me/totp").json()["enabled"] is False
    out = io.StringIO()
    assert cli.main(["remove-two-step", ADMIN_USERNAME], env=env, out=out) == 0
    assert "does not use" in out.getvalue()
    assert cli.main(["remove-two-step", "nobody"], env=env, out=io.StringIO()) != 0
    assert any(a == "totp.disabled" and '"via":"cli"' in (d or "") for a, d in audit_actions(client.app))
