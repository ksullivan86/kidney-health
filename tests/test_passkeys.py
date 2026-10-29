"""Passkeys (design note 18): the routes, sign-in, the admin and CLI ways out, storage and the migration.

The software passkey in ``tests/webauthn_support.py`` plays the device; ``tests/test_webauthn.py`` covers each check of the
verifier on its own. Here: adding (re-auth, the challenge is single use and the person's own, the limit of 10, the same passkey
twice), renaming and removing (not yours is 404), sign-in (a session, no two-step code, the counter, a disabled account, the
user handle, the generic 401 that counts against the address), the admin's removal and ``passkeys`` in the people list, the CLI,
account deletion, proxy and none modes, and an address without a name.
"""
from __future__ import annotations

import io
import sqlite3
from typing import Any
from urllib.parse import urlsplit

import pytest

from app.auth import clock, passkeys, totp
from app.auth.webauthn import b64url_decode
from app.main import create_app
from conftest import ADMIN_USERNAME, FakeClock, TestClient, add_user, make_settings
from tests.webauthn_support import SoftPasskey, assertion_json, registration_json


def origin_of(client: TestClient) -> tuple[str, str]:
    parts = urlsplit(str(client.base_url))
    return parts.hostname or "", f"{parts.scheme}://{parts.netloc}"


def add_passkey(client: TestClient, *, name: str | None = "Phone", alg: int = -7, synced: bool = False) -> tuple[SoftPasskey, dict]:
    rp_id, origin = origin_of(client)
    opts = client.post("/api/me/passkeys/options")
    assert opts.status_code == 200, opts.text
    pub = opts.json()["publicKey"]
    pk = SoftPasskey(alg=alg, rp_id=rp_id, user_handle=b64url_decode(pub["user"]["id"]), synced=synced)
    raw = pk.create(b64url_decode(pub["challenge"]), origin=origin)
    body: dict[str, Any] = {"challenge_id": opts.json()["challenge_id"], "credential": registration_json(pk, raw)}
    if name is not None:
        body["name"] = name
    r = client.post("/api/me/passkeys", json=body)
    assert r.status_code == 201, r.text
    return pk, r.json()


def sign_in_with(app: Any, pk: SoftPasskey, base_url: str, *, client: TestClient | None = None, **change: Any) -> Any:
    c = client or TestClient(app, base_url=base_url)
    opts = c.post("/api/auth/passkey/options")
    assert opts.status_code == 200, opts.text
    origin = change.pop("origin", f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}")
    user_handle = change.pop("user_handle", None)
    raw = pk.get(b64url_decode(opts.json()["publicKey"]["challenge"]), origin=origin, **change)
    return c.post("/api/auth/passkey", json={"challenge_id": opts.json()["challenge_id"],
                                             "credential": assertion_json(pk, raw, user_handle=user_handle)})


def base(client: TestClient) -> str:
    return str(client.base_url).rstrip("/")


def audit_rows(app: Any) -> list[tuple[str, str | None]]:
    with sqlite3.connect(app.state.settings.db_path) as conn:
        return conn.execute("SELECT action, details_json FROM audit_log ORDER BY id").fetchall()


@pytest.fixture
def pair(https_client: TestClient) -> tuple[TestClient, TestClient]:
    return https_client, add_user(https_client)


def sam_id(admin: TestClient) -> int:
    return next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["username"] == "sam")


# --------------------------------------------------------------------------- #
# Adding, renaming, removing
# --------------------------------------------------------------------------- #


def test_add_a_passkey_and_list_it(client: TestClient) -> None:
    assert client.get("/api/me/passkeys").json() == {"available": True, "usable": True, "reason": None, "passkeys": [], "max": 10}
    opts = client.post("/api/me/passkeys/options").json()["publicKey"]
    assert opts["rp"]["id"] == "localhost" and opts["user"]["name"] == ADMIN_USERNAME
    assert opts["authenticatorSelection"] == {"residentKey": "required", "requireResidentKey": True, "userVerification": "required"}
    assert opts["attestation"] == "none" and opts["excludeCredentials"] == []
    assert [p["alg"] for p in opts["pubKeyCredParams"]] == [-7, -8, -35, -36, -257]
    assert len(b64url_decode(opts["user"]["id"])) == 32 and len(b64url_decode(opts["challenge"])) == 32

    pk, item = add_passkey(client, synced=True)
    assert set(item) == {"id", "name", "created_at", "last_used_at", "backed_up"}
    assert item["name"] == "Phone" and item["backed_up"] is True and item["last_used_at"] is None
    listed = client.get("/api/me/passkeys").json()["passkeys"]
    assert listed == [item]
    again = client.post("/api/me/passkeys/options").json()["publicKey"]
    assert b64url_decode(again["user"]["id"]) == pk.user_handle  # the same user handle for all of one person's passkeys
    assert [b64url_decode(c["id"]) for c in again["excludeCredentials"]] == [pk.credential_id]
    assert any(a == "passkey.added" for a, _ in audit_rows(client.app))


def test_a_name_is_cleaned_and_has_a_default(client: TestClient) -> None:
    _, item = add_passkey(client, name=None)
    assert item["name"] == "Passkey"
    _, item = add_passkey(client, name="  Work\u0007   laptop " + "x" * 100)
    assert item["name"].startswith("Work laptop x") and len(item["name"]) == passkeys.NAME_MAX


def test_the_challenge_works_once_and_only_for_its_person(pair: tuple[TestClient, TestClient]) -> None:
    admin, sam = pair
    rp_id, origin = origin_of(admin)
    opts = admin.post("/api/me/passkeys/options").json()
    pk = SoftPasskey(rp_id=rp_id, user_handle=b64url_decode(opts["publicKey"]["user"]["id"]))
    body = {"challenge_id": opts["challenge_id"],
            "credential": registration_json(pk, pk.create(b64url_decode(opts["publicKey"]["challenge"]), origin=origin))}
    r = sam.post("/api/me/passkeys", json=body)  # another person's challenge
    assert r.status_code == 400 and "again" in r.json()["detail"]
    r = admin.post("/api/me/passkeys", json=body)  # used up by the try above
    assert r.status_code == 400
    assert admin.get("/api/me/passkeys").json()["passkeys"] == []


def test_a_failed_check_says_why(client: TestClient) -> None:
    rp_id, origin = origin_of(client)
    opts = client.post("/api/me/passkeys/options").json()
    pk = SoftPasskey(rp_id=rp_id)
    raw = pk.create(b64url_decode(opts["publicKey"]["challenge"]), origin=origin, uv=False)
    r = client.post("/api/me/passkeys", json={"challenge_id": opts["challenge_id"], "credential": registration_json(pk, raw)})
    assert r.status_code == 400 and r.json()["detail"] == "The passkey was not added: The device did not check a fingerprint, face or PIN."
    opts = client.post("/api/me/passkeys/options").json()
    raw = pk.create(b64url_decode(opts["publicKey"]["challenge"]), origin="https://evil.example")
    r = client.post("/api/me/passkeys", json={"challenge_id": opts["challenge_id"], "credential": registration_json(pk, raw)})
    assert r.status_code == 400 and "different web address" in r.json()["detail"]
    opts = client.post("/api/me/passkeys/options").json()
    raw = pk.create(b64url_decode(opts["publicKey"]["challenge"]), origin=origin)
    cred = registration_json(pk, raw)
    cred["rawId"] = "AAAA"
    r = client.post("/api/me/passkeys", json={"challenge_id": opts["challenge_id"], "credential": cred})
    assert r.status_code == 400 and "ID does not match" in r.json()["detail"]


def test_the_same_passkey_twice_and_the_limit_of_ten(client: TestClient) -> None:
    rp_id, origin = origin_of(client)
    pk, _ = add_passkey(client)
    opts = client.post("/api/me/passkeys/options").json()
    raw = pk.create(b64url_decode(opts["publicKey"]["challenge"]), origin=origin)
    r = client.post("/api/me/passkeys", json={"challenge_id": opts["challenge_id"], "credential": registration_json(pk, raw)})
    assert r.status_code == 409 and r.json()["detail"] == "This passkey is already added."
    for _ in range(9):
        add_passkey(client)
    r = client.post("/api/me/passkeys/options")
    assert r.status_code == 409 and "10 passkeys" in r.json()["detail"]


def test_rename_and_remove_and_not_yours_is_404(pair: tuple[TestClient, TestClient]) -> None:
    admin, sam = pair
    _, item = add_passkey(sam)
    pid = item["id"]
    assert admin.patch(f"/api/me/passkeys/{pid}", json={"name": "Mine now"}).status_code == 404
    assert admin.delete(f"/api/me/passkeys/{pid}").status_code == 404
    r = sam.patch(f"/api/me/passkeys/{pid}", json={"name": "Old phone"})
    assert r.status_code == 200 and r.json()["name"] == "Old phone"
    assert sam.delete(f"/api/me/passkeys/{pid}").status_code == 204
    assert sam.delete(f"/api/me/passkeys/{pid}").status_code == 404
    assert sam.get("/api/me/passkeys").json()["passkeys"] == []
    assert any(a == "passkey.removed" and '"via":"self"' in (d or "") for a, d in audit_rows(admin.app))


def test_adding_and_removing_need_the_password_again(client: TestClient, fake_clock: FakeClock) -> None:
    _, item = add_passkey(client)
    fake_clock.advance(minutes=client.app.state.settings.reauth_minutes + 1)
    for method, path in (("post", "/api/me/passkeys/options"), ("delete", f"/api/me/passkeys/{item['id']}")):
        r = client.request(method, path)
        assert r.status_code == 403 and r.json().get("reauth_required") is True, path
    r = client.post("/api/me/passkeys", json={"challenge_id": "x", "credential": {"rawId": "AA", "response": {
        "clientDataJSON": "AA", "attestationObject": "AA"}}})
    assert r.status_code == 403
    assert client.get("/api/me/passkeys").status_code == 200
    assert client.patch(f"/api/me/passkeys/{item['id']}", json={"name": "Phone 2"}).status_code == 200  # a name is not a credential


# --------------------------------------------------------------------------- #
# Signing in
# --------------------------------------------------------------------------- #


def test_sign_in_with_a_passkey(client: TestClient) -> None:
    pk, item = add_passkey(client)
    other = TestClient(client.app)
    opts = other.post("/api/auth/passkey/options").json()["publicKey"]
    assert opts["rpId"] == "localhost" and opts["userVerification"] == "required" and opts["allowCredentials"] == []
    r = sign_in_with(client.app, pk, base(client), client=other)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == ADMIN_USERNAME
    assert other.get("/api/me").json()["username"] == ADMIN_USERNAME
    listed = client.get("/api/me/passkeys").json()["passkeys"][0]
    assert listed["last_used_at"] is not None
    assert any(a == "login.succeeded" and '"via":"passkey"' in (d or "") for a, d in audit_rows(client.app))
    assert client.get("/api/auth/status").json()["passkeys"] is True


def test_a_passkey_sign_in_is_not_asked_for_the_two_step_code(client: TestClient, fake_clock: FakeClock) -> None:
    secret = client.post("/api/me/totp/setup").json()["secret"]
    code = totp.hotp(totp.secret_from_text(secret), totp.step_at(clock.seconds()))
    assert client.post("/api/me/totp/enable", json={"code": code}).status_code == 200
    pk, _ = add_passkey(client)
    assert sign_in_with(client.app, pk, base(client)).status_code == 200


def test_each_sign_in_challenge_works_once(client: TestClient) -> None:
    pk, _ = add_passkey(client)
    c = TestClient(client.app)
    opts = c.post("/api/auth/passkey/options").json()
    body = {"challenge_id": opts["challenge_id"],
            "credential": assertion_json(pk, pk.get(b64url_decode(opts["publicKey"]["challenge"]), origin=base(client)))}
    assert c.post("/api/auth/passkey", json=body).status_code == 200
    r = TestClient(client.app).post("/api/auth/passkey", json=body)
    assert r.status_code == 401 and r.json()["detail"] == "That passkey did not work. Try again, or sign in with your password."


@pytest.mark.parametrize("change", [{"uv": False}, {"origin": "https://evil.example"}, {"rp_id": "evil.example"},
                                    {"user_handle": b"\x01" * 32}, {"crossOrigin": True}])
def test_a_failed_sign_in_is_one_generic_answer(client: TestClient, change: dict) -> None:
    pk, _ = add_passkey(client)
    r = sign_in_with(client.app, pk, base(client), **change)
    assert r.status_code == 401 and r.json() == {"detail": "That passkey did not work. Try again, or sign in with your password."}
    assert any(a == "login.failed" and '"via":"passkey"' in (d or "") for a, d in audit_rows(client.app))


def test_an_unknown_passkey_is_refused(client: TestClient) -> None:
    stranger = SoftPasskey()
    assert sign_in_with(client.app, stranger, base(client)).status_code == 401


def test_a_counter_that_goes_back_is_refused_and_audited(client: TestClient) -> None:
    pk, _ = add_passkey(client)
    assert sign_in_with(client.app, pk, base(client)).status_code == 200
    assert sign_in_with(client.app, pk, base(client)).status_code == 200
    pk.counter = 1  # a copy of the key that was taken earlier
    assert sign_in_with(client.app, pk, base(client)).status_code == 401
    assert any(a == "passkey.counter_went_back" for a, _ in audit_rows(client.app))


def test_a_passkey_that_never_counts_keeps_working(client: TestClient) -> None:
    pk, _ = add_passkey(client)
    for _ in range(3):
        assert sign_in_with(client.app, pk, base(client), counter_step=0).status_code == 200


def test_a_disabled_account_cannot_sign_in_with_a_passkey(pair: tuple[TestClient, TestClient]) -> None:
    admin, sam = pair
    pk, _ = add_passkey(sam)
    assert admin.patch(f"/api/admin/users/{sam_id(admin)}", json={"status": "disabled"}).status_code == 200
    assert sign_in_with(admin.app, pk, base(admin)).status_code == 401


def test_failed_passkey_sign_ins_slow_the_address_down(client: TestClient, fake_clock: FakeClock) -> None:
    pk, _ = add_passkey(client)
    limit = client.app.state.settings.login_ip_max_failures
    codes = [sign_in_with(client.app, pk, base(client), uv=False).status_code for _ in range(limit)]
    assert codes == [401] * limit
    r = TestClient(client.app).post("/api/auth/passkey/options")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_the_options_route_has_a_rate_limit(client: TestClient) -> None:
    anon = TestClient(client.app)
    codes = [anon.post("/api/auth/passkey/options").status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_challenges_expire_and_are_bounded() -> None:
    store = passkeys.ChallengeStore(max_items=3, ttl_s=60)
    ids = [store.issue("get")[0] for _ in range(5)]
    assert len(store) == 3
    assert store.take(ids[0], "get") is None  # pushed out by newer ones
    assert store.take(ids[4], "create") is None  # the wrong kind uses it up
    assert store.take(ids[4], "get") is None
    assert store.take(ids[3], "get") is not None
    expired = passkeys.ChallengeStore(ttl_s=-1)
    cid, _ = expired.issue("get")
    assert expired.take(cid, "get") is None


# --------------------------------------------------------------------------- #
# The admin and CLI ways out, deletion, modes
# --------------------------------------------------------------------------- #


def test_an_admin_can_remove_someones_passkeys(pair: tuple[TestClient, TestClient]) -> None:
    admin, sam = pair
    pk, _ = add_passkey(sam)
    add_passkey(sam)
    sid = sam_id(admin)
    people = {u["username"]: u["passkeys"] for u in admin.get("/api/admin/users").json()["users"]}
    assert people == {"admin": 0, "sam": 2}
    assert sam.delete(f"/api/admin/users/{sid}/passkeys").status_code == 403
    assert admin.delete("/api/admin/users/99999/passkeys").status_code == 404
    assert admin.delete(f"/api/admin/users/{sid}/passkeys").json() == {"removed": 2}
    assert admin.delete(f"/api/admin/users/{sid}/passkeys").json() == {"removed": 0}
    assert sign_in_with(admin.app, pk, base(admin)).status_code == 401
    details = [d for a, d in audit_rows(admin.app) if a == "passkey.removed"]
    assert len(details) == 1 and '"via":"admin"' in details[0] and '"count":2' in details[0]


def test_the_cli_removes_them(client: TestClient) -> None:
    from app import admin as cli

    add_passkey(client)
    env = {"DATA_DIR": str(client.app.state.settings.data_dir)}
    out = io.StringIO()
    assert cli.main(["remove-passkeys", ADMIN_USERNAME], env=env, out=out) == 0
    assert "1 passkey(s) removed" in out.getvalue()
    out = io.StringIO()
    assert cli.main(["remove-passkeys", ADMIN_USERNAME], env=env, out=out) == 0
    assert "has no passkeys" in out.getvalue()
    assert cli.main(["remove-passkeys", "nobody"], env=env, out=io.StringIO()) != 0
    assert any(a == "passkey.removed" and '"via":"cli"' in (d or "") for a, d in audit_rows(client.app))


def test_deleting_the_account_deletes_its_passkeys(pair: tuple[TestClient, TestClient]) -> None:
    admin, sam = pair
    add_passkey(sam)
    sid = sam_id(admin)
    assert admin.request("DELETE", f"/api/admin/users/{sid}", json={"confirm_username": "sam"}).status_code == 204
    with sqlite3.connect(admin.app.state.settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM passkeys WHERE user_id = ?", (sid,)).fetchone()[0] == 0


def test_nothing_secret_or_identifying_is_shown(client: TestClient) -> None:
    pk, item = add_passkey(client)
    text = client.get("/api/me/passkeys").text + client.get("/api/admin/users").text
    for raw in (pk.credential_id, pk.cose_public_key()):
        from app.auth.webauthn import b64url

        assert b64url(raw) not in text and raw.hex() not in text


@pytest.mark.parametrize("mode", ["none", "proxy"])
def test_not_offered_without_local_sign_in(tmp_path: Any, foods_json: Any, mode: str) -> None:
    extra = {"trusted_proxy_user_header": "Remote-User", "trusted_proxy_secret": "p" * 40} if mode == "proxy" else {}
    with TestClient(create_app(make_settings(tmp_path, foods_json, auth_mode=mode, **extra))) as c:
        if mode == "none":
            assert c.get("/api/me/passkeys").json()["available"] is False
            for method, path in (("post", "/api/me/passkeys/options"), ("delete", "/api/me/passkeys/1"),
                                 ("patch", "/api/me/passkeys/1")):
                assert c.request(method, path, json={"name": "x"} if method == "patch" else None).status_code == 404, path
        assert c.post("/api/auth/passkey/options").status_code == 404
        assert c.post("/api/auth/passkey", json={"challenge_id": "x", "credential": {"rawId": "AA", "response": {
            "clientDataJSON": "AA", "authenticatorData": "AA", "signature": "AA"}}}).status_code == 404
        assert c.get("/api/auth/status").json()["passkeys"] is False


def test_an_address_that_is_an_ip_cannot_carry_passkeys(settings: Any) -> None:
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as c:
        from conftest import sign_in

        sign_in(c)
        got = c.get("/api/me/passkeys").json()
        assert got["usable"] is False and "IP address" in got["reason"]
        r = c.post("/api/me/passkeys/options")
        assert r.status_code == 409 and "PUBLIC_URL" in r.json()["detail"]
        assert c.get("/api/auth/status").json()["passkeys"] is False


def test_public_url_sets_where_passkeys_work(tmp_path: Any, foods_json: Any) -> None:
    settings = make_settings(tmp_path, foods_json, public_url="https://food.example.org")
    with TestClient(create_app(settings), base_url="https://food.example.org") as c:
        from conftest import sign_in

        sign_in(c)
        assert c.post("/api/me/passkeys/options").json()["publicKey"]["rp"]["id"] == "food.example.org"
        pk, _ = add_passkey(c)
        assert sign_in_with(c.app, pk, "https://food.example.org").status_code == 200


# --------------------------------------------------------------------------- #
# A passkey instead of the password when an action asks for it again (note 18 §10)
# --------------------------------------------------------------------------- #


def reauth_with(client: TestClient, pk: SoftPasskey, **change: Any) -> Any:
    opts = client.post("/api/auth/reauth/passkey/options")
    assert opts.status_code == 200, opts.text
    origin = change.pop("origin", base(client))
    raw = pk.get(b64url_decode(opts.json()["publicKey"]["challenge"]), origin=origin, **change)
    return client.post("/api/auth/reauth/passkey", json={"challenge_id": opts.json()["challenge_id"],
                                                          "credential": assertion_json(pk, raw)})


def test_a_passkey_answers_the_password_question(client: TestClient, fake_clock: FakeClock) -> None:
    pk, _ = add_passkey(client)
    fake_clock.advance(minutes=client.app.state.settings.reauth_minutes + 1)
    assert client.post("/api/me/passkeys/options").json().get("reauth_required") is True
    opts = client.post("/api/auth/reauth/passkey/options").json()["publicKey"]
    assert [b64url_decode(c["id"]) for c in opts["allowCredentials"]] == [pk.credential_id]
    assert opts["userVerification"] == "required"
    r = reauth_with(client, pk)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["reauth_until"]
    assert client.post("/api/me/passkeys/options").status_code == 200  # the action now goes through


def test_only_your_own_passkey_counts(pair: tuple[TestClient, TestClient], fake_clock: FakeClock) -> None:
    admin, sam = pair
    add_passkey(admin)
    sam_pk, _ = add_passkey(sam)
    fake_clock.advance(minutes=admin.app.state.settings.reauth_minutes + 1)
    r = reauth_with(admin, sam_pk)  # Sam's passkey on the admin's session
    assert r.status_code == 403 and r.json()["detail"] == "That passkey did not work. Try again, or type your password."
    assert any(a == "login.failed" and '"via":"passkey_reauth"' in (d or "") for a, d in audit_rows(admin.app))


def test_with_no_passkey_there_is_nothing_to_ask(client: TestClient) -> None:
    r = client.post("/api/auth/reauth/passkey/options")
    assert r.status_code == 409 and "Type your password" in r.json()["detail"]


def test_five_failed_passkey_answers_sign_the_device_out(client: TestClient, fake_clock: FakeClock) -> None:
    pk, _ = add_passkey(client)
    fake_clock.advance(minutes=client.app.state.settings.reauth_minutes + 1)
    codes = [reauth_with(client, pk, uv=False).status_code for _ in range(5)]
    assert codes == [403, 403, 403, 403, 401]
    assert client.get("/api/me").status_code == 401


def test_a_reentry_challenge_is_not_a_sign_in_challenge(client: TestClient) -> None:
    pk, _ = add_passkey(client)
    opts = client.post("/api/auth/reauth/passkey/options").json()
    raw = pk.get(b64url_decode(opts["publicKey"]["challenge"]), origin=base(client))
    r = TestClient(client.app).post("/api/auth/passkey", json={"challenge_id": opts["challenge_id"], "credential": assertion_json(pk, raw)})
    assert r.status_code == 401
    assert TestClient(client.app).post("/api/auth/reauth/passkey/options").status_code == 401  # signed in only
