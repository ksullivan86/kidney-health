"""Sign-in with an OpenID Connect provider (design note 24): the flow, the ID token checks, the account rules, linking, re-entry,
two-step for admins, the settings and the address checks. No network: :mod:`oidc_support` is a fake provider that signs with real
keys, reached through the app's own SSRF-checked transport."""
from __future__ import annotations

import sqlite3
import time
from typing import Any, Iterator

import pytest

from app.auth import clock, oidc
from app.config import ConfigError, load_settings
from app.main import create_app
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, HTTPS_URL, TestClient, add_user, make_settings, sign_in
from oidc_support import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider, attach, come_back, env, rsa_key, sign_in_with_provider

PUBLIC_URL = "https://localhost"


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


def oidc_settings(tmp_path, foods_json, **changes: Any):
    values: dict[str, Any] = {"public_url": PUBLIC_URL, "oidc": env()}
    values.update(changes)
    return make_settings(tmp_path, foods_json, **values)


@pytest.fixture
def app(tmp_path, foods_json, provider):
    application = create_app(oidc_settings(tmp_path, foods_json))
    attach(application, provider)
    return application


@pytest.fixture
def admin(app) -> Iterator[TestClient]:
    with TestClient(app, base_url=HTTPS_URL) as c:
        sign_in(c)
        yield c


@pytest.fixture
def anon(app, admin) -> TestClient:
    """A second browser on the same running app (the admin's client started it)."""
    return TestClient(app, base_url=HTTPS_URL)


def database(client) -> sqlite3.Connection:
    path = client.app.state.auth.settings.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def set_setting(admin: TestClient, **values: Any) -> None:
    r = admin.patch("/api/admin/settings", json=values)
    assert r.status_code == 200, r.text


def link_admin(admin: TestClient, provider: FakeProvider, sub: str = "admin-sub", **claims: Any) -> None:
    r = admin.post("/api/me/oidc/link")
    assert r.status_code == 200, r.text
    back = come_back(admin, provider, r.json()["url"], claims={"sub": sub, **claims})
    assert back.headers["location"] == "/#/oidc/linked", back.headers["location"]


# --------------------------------------------------------------------------- #
# The flow
# --------------------------------------------------------------------------- #


def test_status_shows_the_button_and_nothing_about_the_connection(anon, admin):
    st = anon.get("/api/auth/status").json()
    assert st["oidc"] == {"enabled": True, "label": "Sign in with single sign-on", "only": False, "password": "on",
                          "providers": [{"id": "default", "label": "Sign in with single sign-on"}]}
    set_setting(admin, **{"auth.oidc.button_label": "Sign in with Authentik"})
    assert anon.get("/api/auth/status").json()["oidc"]["label"] == "Sign in with Authentik"
    text = anon.get("/api/auth/status").text
    assert ISSUER not in text and CLIENT_ID not in text


def test_off_by_default_every_route_is_404(tmp_path, foods_json):
    with TestClient(create_app(make_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        assert c.get("/api/auth/status").json()["oidc"] == {"enabled": False, "label": None, "providers": [], "only": False,
                                                               "password": "on"}
        assert c.get("/api/auth/oidc/start", follow_redirects=False).status_code == 404
        assert c.get("/api/auth/oidc/callback?code=x&state=y", follow_redirects=False).status_code == 404
        assert c.post("/api/auth/oidc/invite", json={"token": "a.b"}).status_code == 404
        sign_in(c)
        assert c.get("/api/me/oidc").json()["enabled"] is False
        assert c.post("/api/me/oidc/link").status_code == 404
        assert c.post("/api/auth/reauth/oidc").status_code == 404


def test_the_authorization_request_has_pkce_state_and_nonce(anon, provider):
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)
    assert r.status_code == 303 and r.headers["cache-control"] == "no-store"
    _, state, query = provider.authorize(r.headers["location"])
    assert query["redirect_uri"] == "https://localhost/api/auth/oidc/callback"
    assert query["scope"] == "openid email profile"
    assert len(query["state"]) >= 43 and len(query["nonce"]) >= 43 and len(query["code_challenge"]) == 43
    assert "prompt" not in query and "max_age" not in query
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-kh_oidc=") and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" in cookie
    assert "Path=/" in cookie and "Max-Age=600" in cookie


def test_happy_path_signs_in_a_linked_account(admin, anon, provider):
    link_admin(admin, provider)
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "__Host-kh_session=" in r.headers.get("set-cookie", "")
    me = anon.get("/api/me").json()
    assert me["username"] == ADMIN_USERNAME
    with database(admin) as conn:
        assert conn.execute("SELECT signed_in_with FROM sessions WHERE signed_in_with = 'oidc'").fetchone() is not None
        rows = conn.execute("SELECT action, details_json FROM audit_log WHERE action IN ('login.succeeded', 'oidc.linked')").fetchall()
        assert ("oidc.linked", '{"via":"settings"}') in [tuple(r) for r in rows]
        assert any(r["action"] == "login.succeeded" and '"via":"oidc"' in r["details_json"] for r in rows)
        dump = "\n".join(conn.iterdump())
    # The tokens of the answer are never stored, nor the client secret
    for secret in ("access-token-never-stored", "refresh-token-never-stored", CLIENT_SECRET):
        assert secret not in dump
    # client_secret_basic, the PKCE verifier, the exact redirect URI
    form = provider.token_forms[-1]
    assert form["redirect_uri"] == ["https://localhost/api/auth/oidc/callback"] and len(form["code_verifier"][0]) >= 43
    assert provider.token_headers[-1]["authorization"].startswith("Basic ")


def test_es256_and_eddsa_tokens_are_accepted(admin, anon, provider):
    link_admin(admin, provider)
    for kid in ("ec1", "ed1"):
        key = {"ec1": provider.ec, "ed1": provider.ed}[kid]
        alg = {"ec1": "ES256", "ed1": "EdDSA"}[kid]
        r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"kid": kid, "alg": alg}, key=key)
        assert r.headers["location"] == "/", (kid, r.headers["location"])


def test_unknown_subject_with_signup_off_is_refused_and_nothing_is_made(anon, admin, provider):
    r = sign_in_with_provider(anon, provider, claims={"sub": "stranger"})
    assert r.headers["location"] == "/#/oidc/no_account"
    assert anon.get("/api/me").status_code == 401
    with database(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE username_norm NOT LIKE '#%'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM oidc_links").fetchone()[0] == 0


class _FromNow:
    def __init__(self, offset: int) -> None:
        self.offset = offset

    def __add__(self, seconds: int) -> "_FromNow":
        return _FromNow(self.offset + seconds)

    def __sub__(self, seconds: int) -> "_FromNow":
        return _FromNow(self.offset - seconds)

    def __repr__(self) -> str:
        return f"now{self.offset:+d}"


NOW = _FromNow(0)


@pytest.mark.parametrize("change, word", [
    ({"nonce": "not-the-nonce"}, "failed"),
    ({"aud": "someone-else"}, "failed"),
    ({"aud": [CLIENT_ID, "other"]}, "failed"),  # two audiences and no azp
    ({"azp": "other"}, "failed"),
    ({"iss": "https://evil.example/"}, "failed"),
    ({"exp": NOW - 120}, "failed"),
    ({"iat": NOW + 600}, "failed"),
    ({"iat": NOW - 3600}, "failed"),
    ({"sub": ""}, "failed"),
    ({"exp": ...}, "failed"),
])
def test_bad_claims_are_refused(admin, anon, provider, change, word):
    # Times are offsets from when the test runs, not from collection: a long run would let "600 s ahead" pass.
    change = {k: int(time.time()) + v.offset if isinstance(v, _FromNow) else v for k, v in change.items()}
    link_admin(admin, provider)
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub", **change})
    assert r.headers["location"] == f"/#/oidc/{word}"
    assert anon.get("/api/me").status_code == 401


def test_two_audiences_with_the_right_azp_are_fine(admin, anon, provider):
    link_admin(admin, provider)
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub", "aud": [CLIENT_ID, "other"], "azp": CLIENT_ID})
    assert r.headers["location"] == "/"


def test_a_wrong_signature_none_and_hs256_are_refused(admin, anon, provider):
    link_admin(admin, provider)
    stranger = rsa_key()
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, key=stranger)  # kid rsa1, another key
    assert r.headers["location"] == "/#/oidc/failed"
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"alg": "none"})
    assert r.headers["location"] == "/#/oidc/failed"
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"alg": "HS256"}, key=CLIENT_SECRET.encode())
    assert r.headers["location"] == "/#/oidc/failed"
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"kid": "ec1", "alg": "RS256"})  # key type mismatch
    assert r.headers["location"] == "/#/oidc/failed"
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"crit": ["exp"]})
    assert r.headers["location"] == "/#/oidc/failed"


def test_an_unknown_kid_fetches_the_keys_again_once(admin, anon, provider):
    link_admin(admin, provider)
    assert sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}).headers["location"] == "/"
    before = provider.calls.count("/application/o/kidney/jwks")
    new_key = rsa_key()
    provider.keys.append(("rsa2", new_key, "RS256"))  # the provider rotates its keys
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"kid": "rsa2"}, key=new_key)
    assert r.headers["location"] == "/"
    assert provider.calls.count("/application/o/kidney/jwks") == before + 1
    # a stream of made-up kids does not hammer the provider: at most one refresh a minute
    for _ in range(3):
        r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"}, header={"kid": "made-up"})
        assert r.headers["location"] == "/#/oidc/failed"
    assert provider.calls.count("/application/o/kidney/jwks") == before + 1


def test_bad_state_and_a_flow_from_another_browser_are_refused(app, admin, anon, provider):
    link_admin(admin, provider)
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)
    code, state, _ = provider.authorize(r.headers["location"], claims={"sub": "admin-sub"})
    # an unknown state
    bad = anon.get("/api/auth/oidc/callback", params={"code": code, "state": "x" * 43}, follow_redirects=False)
    assert bad.headers["location"] == "/#/oidc/expired"
    # the right state in a browser without the cookie (login CSRF): refused, and nothing is signed in there
    other = TestClient(app, base_url=HTTPS_URL)
    stolen = other.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert stolen.headers["location"] == "/#/oidc/expired" and other.get("/api/me").status_code == 401
    # the browser that started it still finishes (a forged attempt does not burn the flow), and only once
    again = anon.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert again.headers["location"] == "/"
    replay = anon.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert replay.headers["location"] == "/#/oidc/expired"


def test_provider_errors_and_a_wrong_iss_parameter(admin, anon, provider):
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)
    _, state, _ = provider.authorize(r.headers["location"])
    r = anon.get("/api/auth/oidc/callback", params={"error": "access_denied", "error_description": "<script>", "state": state},
                 follow_redirects=False)
    assert r.headers["location"] == "/#/oidc/cancelled"
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)
    code, state, _ = provider.authorize(r.headers["location"])
    r = anon.get("/api/auth/oidc/callback", params={"code": code, "state": state, "iss": "https://evil.example/"}, follow_redirects=False)
    assert r.headers["location"] == "/#/oidc/failed"


def test_the_provider_can_send_the_browser_back_but_nothing_else_crosses_sites(admin, anon, provider):
    """The provider's redirect back is a cross-site (or same-site) top-level navigation: the cross-site read guard lets that one
    through, and only that one (a fetch, a frame, another method or another /api path stays refused)."""
    link_admin(admin, provider)
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)
    code, state, _ = provider.authorize(r.headers["location"], claims={"sub": "admin-sub"})
    for site in ("cross-site", "same-site"):
        for mode, dest in (("cors", "empty"), ("no-cors", "image"), ("navigate", "iframe")):
            refused = anon.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False,
                               headers={"Sec-Fetch-Site": site, "Sec-Fetch-Mode": mode, "Sec-Fetch-Dest": dest})
            assert refused.status_code == 403, (site, mode, dest)
    nav = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
    assert anon.get("/api/me", headers=nav).status_code == 403
    assert anon.get("/api/auth/oidc/start", headers=nav, follow_redirects=False).status_code == 403
    assert anon.post("/api/auth/oidc/callback", headers=nav).status_code == 403
    back = anon.get("/api/auth/oidc/callback", params={"code": code, "state": state}, headers=nav, follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/"
    # A forged return in a browser that did not start the flow is still refused by the route itself
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)
    code, state, _ = provider.authorize(r.headers["location"], claims={"sub": "admin-sub"})
    other = TestClient(admin.app, base_url=HTTPS_URL)
    forged = other.get("/api/auth/oidc/callback", params={"code": code, "state": state}, headers=nav, follow_redirects=False)
    assert forged.headers["location"] == "/#/oidc/expired"


def test_every_result_word_has_a_sentence_on_the_page():
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "views" / "oidc.js").read_text(encoding="utf-8")
    for word in oidc.RESULTS:
        assert f"{word}:" in js, word


# --------------------------------------------------------------------------- #
# Account rules
# --------------------------------------------------------------------------- #


def test_signup_makes_a_user_account_with_a_free_username(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True})
    r = sign_in_with_provider(anon, provider, claims={"sub": "new-1", "email": "Pat@Example.org", "name": "Pat"})
    assert r.headers["location"] == "/"
    me = anon.get("/api/me").json()
    assert me["username"] == "pat@example.org" and me["display_name"] == "Pat" and me["role"] == "user"
    # a second person with the same email name gets a suffix
    other = TestClient(admin.app, base_url=HTTPS_URL)
    with database(admin) as conn:
        conn.execute("UPDATE users SET username = 'x', username_norm = 'pat@example.org' WHERE id = ?", (me["id"],))
    r = sign_in_with_provider(other, provider, claims={"sub": "new-2", "email": "pat@example.org", "email_verified": False,
                                                       "preferred_username": "pat"})
    assert r.headers["location"] == "/" and other.get("/api/me").json()["username"] == "pat"
    with database(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'user.registered' AND details_json LIKE '%oidc_signup%'").fetchone()[0] == 2


def test_an_unverified_email_never_links(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.link_by_email": True})
    admin_made_account(admin, "sam@example.org")
    for verified in (False, "true", None):
        r = sign_in_with_provider(anon, provider, claims={"sub": "sam-sub", "email": "sam@example.org", "email_verified": verified})
        assert r.headers["location"] == "/#/oidc/no_account", verified
    r = sign_in_with_provider(anon, provider, claims={"sub": "sam-sub", "email": "SAM@example.org", "email_verified": True})
    assert r.headers["location"] == "/" and anon.get("/api/me").json()["username"] == "sam@example.org"


def test_link_by_email_is_off_by_default_and_never_links_an_admin(admin, anon, provider):
    admin_made_account(admin, "kim@example.org")
    r = sign_in_with_provider(anon, provider, claims={"sub": "kim-sub", "email": "kim@example.org"})
    assert r.headers["location"] == "/#/oidc/no_account"
    set_setting(admin, **{"auth.oidc.link_by_email": True})
    admin_made_account(admin, "boss@example.org", role="admin")
    r = sign_in_with_provider(anon, provider, claims={"sub": "boss-sub", "email": "boss@example.org"})
    assert r.headers["location"] == "/#/oidc/no_account"


def test_allowed_domains(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True, "auth.oidc.allowed_domains": "family.net, Example.org"})
    for claims in ({"email": "a@gmail.com"}, {"email": "a@example.org", "email_verified": False},
                   {"email": "a@example.org", "hd": "evil.com"}, {"email": ...}):
        r = sign_in_with_provider(anon, provider, claims={"sub": "d1", **claims})
        assert r.headers["location"] == "/#/oidc/domain", claims
    r = sign_in_with_provider(anon, provider, claims={"sub": "d1", "email": "a@example.org", "hd": "example.org"})
    assert r.headers["location"] == "/"
    # an existing link is checked too, at every sign-in
    set_setting(admin, **{"auth.oidc.allowed_domains": "family.net"})
    r = sign_in_with_provider(TestClient(admin.app, base_url=HTTPS_URL), provider, claims={"sub": "d1", "email": "a@example.org"})
    assert r.headers["location"] == "/#/oidc/domain"


def test_admin_groups_follow_the_claim_and_never_demote_the_last_admin(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True, "auth.oidc.admin_groups": "authentik Admins, family-admins"})
    r = sign_in_with_provider(anon, provider, claims={"sub": "g1", "email": "g1@example.org", "groups": ["family-admins"]})
    assert r.headers["location"] == "/" and anon.get("/api/me").json()["role"] == "admin"
    r = sign_in_with_provider(anon, provider, claims={"sub": "g1", "email": "g1@example.org", "groups": ["users"]})
    assert anon.get("/api/me").json()["role"] == "user"
    r = sign_in_with_provider(anon, provider, claims={"sub": "g1", "email": "g1@example.org"})  # no claim: left alone
    assert anon.get("/api/me").json()["role"] == "user"
    # the only admin, linked, without the group: kept
    link_admin(admin, provider)
    other = TestClient(admin.app, base_url=HTTPS_URL)
    r = sign_in_with_provider(other, provider, claims={"sub": "admin-sub", "groups": []})
    assert r.headers["location"] == "/" and other.get("/api/me").json()["role"] == "admin"
    with database(admin) as conn:
        changes = conn.execute("SELECT details_json FROM audit_log WHERE action = 'user.role_changed'").fetchall()
        assert len(changes) == 2 and all("oidc_groups" in r[0] for r in changes)


def test_a_disabled_account_is_refused_and_audited(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True})
    sign_in_with_provider(anon, provider, claims={"sub": "z1", "email": "z@example.org"})
    uid = anon.get("/api/me").json()["id"]
    assert admin.patch(f"/api/admin/users/{uid}", json={"status": "disabled"}).status_code == 200
    r = sign_in_with_provider(anon, provider, claims={"sub": "z1", "email": "z@example.org"})
    assert r.headers["location"] == "/#/oidc/disabled"
    with database(admin) as conn:
        row = conn.execute("SELECT details_json FROM audit_log WHERE action = 'login.failed' ORDER BY id DESC").fetchone()
        assert '"via":"oidc"' in row[0] and "account_not_active" in row[0]


def test_an_invite_link_makes_the_account_with_the_provider(admin, anon, provider):
    from conftest import invite_token

    token = invite_token(admin, role="user")
    r = anon.post("/api/auth/oidc/invite", json={"token": token})
    assert r.status_code == 200, r.text
    back = come_back(anon, provider, r.json()["url"], claims={"sub": "inv-1", "email": "ann@example.org", "name": "Ann"})
    assert back.headers["location"] == "/"
    assert anon.get("/api/me").json()["username"] == "ann@example.org"
    # the invite is used up
    assert anon.post("/api/auth/oidc/invite", json={"token": token}).status_code == 400
    assert anon.post("/api/auth/oidc/invite", json={"token": "nope.nope"}).status_code == 400


# --------------------------------------------------------------------------- #
# Linking, unlinking, re-entry
# --------------------------------------------------------------------------- #


def expire_reauth(client: TestClient) -> None:
    with database(client) as conn:
        conn.execute("UPDATE sessions SET reauth_at = NULL")


def test_link_and_unlink_need_a_recent_password(admin, provider):
    expire_reauth(admin)
    r = admin.post("/api/me/oidc/link")
    assert r.status_code == 403 and r.json()["reauth_required"] is True
    assert admin.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    link_admin(admin, provider)
    assert admin.post("/api/me/oidc/link").status_code == 409  # already linked
    item = admin.get("/api/me/oidc").json()
    assert item["links"][0]["provider"] == "idp.example.org" and item["links"][0]["current"] is True
    assert "subject" not in item["links"][0] and "admin-sub" not in str(item)
    expire_reauth(admin)
    link_id = item["links"][0]["id"]
    assert admin.delete(f"/api/me/oidc/{link_id}").status_code == 403
    assert admin.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD}).status_code == 200
    assert admin.delete(f"/api/me/oidc/{link_id}").status_code == 204
    assert admin.get("/api/me/oidc").json()["links"] == []


def test_linking_comes_back_only_in_the_same_session(app, admin, provider):
    r = admin.post("/api/me/oidc/link")
    url = r.json()["url"]
    code, state, _ = provider.authorize(url, claims={"sub": "x"})
    # the same browser, signed out and in again: another session
    other = TestClient(app, base_url=HTTPS_URL)
    sign_in(other)
    other.cookies.set("__Host-kh_oidc", admin.cookies.get("__Host-kh_oidc"), domain="localhost")
    back = other.get("/api/auth/oidc/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert back.headers["location"] == "/#/oidc/expired"
    assert admin.get("/api/me/oidc").json()["links"] == []


def test_a_provider_account_linked_to_someone_else_is_refused(admin, provider):
    link_admin(admin, provider, sub="shared-sub")
    sam = add_user(admin, username="sam", base_url=HTTPS_URL)
    r = sam.post("/api/me/oidc/link")
    back = come_back(sam, provider, r.json()["url"], claims={"sub": "shared-sub"})
    assert back.headers["location"] == "/#/oidc/taken"


def test_another_persons_link_is_404(admin, provider):
    link_admin(admin, provider)
    link_id = admin.get("/api/me/oidc").json()["links"][0]["id"]
    sam = add_user(admin, username="sam", base_url=HTTPS_URL)
    assert sam.delete(f"/api/me/oidc/{link_id}").status_code == 404
    assert sam.delete("/api/me/oidc/99999999999999999999999").status_code in (404, 422)
    assert len(admin.get("/api/me/oidc").json()["links"]) == 1
    assert sam.get("/api/me/oidc").json()["links"] == []


def test_deleting_the_account_deletes_its_links(admin, provider):
    link_admin(admin, provider)
    sam = add_user(admin, username="sam", base_url=HTTPS_URL)
    r = sam.post("/api/me/oidc/link")
    assert come_back(sam, provider, r.json()["url"], claims={"sub": "sam-sub"}).headers["location"] == "/#/oidc/linked"
    sam_id = sam.get("/api/me").json()["id"]
    from conftest import USER_PASSWORD

    assert sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"}).status_code == 204
    with database(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM oidc_links WHERE user_id = ?", (sam_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM oidc_links").fetchone()[0] == 1  # the admin's stays


def test_the_last_way_in_cannot_be_removed(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True})
    sign_in_with_provider(anon, provider, claims={"sub": "only", "email": "only@example.org"})
    st = anon.get("/api/me/oidc").json()
    assert st["has_password"] is False and st["passkeys"] == 0
    r = anon.delete(f"/api/me/oidc/{st['links'][0]['id']}")
    assert r.status_code == 409 and "only way to sign in" in r.json()["detail"]
    # and the admin can remove it for a lost provider account
    uid = anon.get("/api/me").json()["id"]
    assert admin.delete(f"/api/admin/users/{uid}/oidc").json() == {"removed": 1}
    assert next(u for u in admin.get("/api/admin/users").json()["users"] if u["id"] == uid)["oidc_links"] == 0


def test_confirm_with_the_provider_instead_of_a_password(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True})
    sign_in_with_provider(anon, provider, claims={"sub": "p1", "email": "p1@example.org"})
    expire_reauth(anon)
    assert anon.post("/api/me/tokens", json={"name": "x"}).json().get("reauth_required") in (True, None)
    r = anon.post("/api/auth/reauth/oidc")
    assert r.status_code == 200
    _, _, query = provider.authorize(r.json()["url"])
    assert query["prompt"] == "login" and query["max_age"] == "0"
    # an old auth_time is refused (the provider did not ask again)
    r = anon.post("/api/auth/reauth/oidc")
    stale = come_back(anon, provider, r.json()["url"], claims={"sub": "p1", "auth_time": int(time.time()) - 3600})
    assert stale.headers["location"] == "/#/oidc/failed"
    # another provider account is refused
    r = anon.post("/api/auth/reauth/oidc")
    wrong = come_back(anon, provider, r.json()["url"], claims={"sub": "p2"})
    assert wrong.headers["location"] == "/#/oidc/wrong_account"
    r = anon.post("/api/auth/reauth/oidc")
    ok = come_back(anon, provider, r.json()["url"], claims={"sub": "p1"})
    assert ok.headers["location"] == "/#/oidc/confirmed"
    with database(anon) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE reauth_at IS NOT NULL").fetchone()[0] >= 1
    # a passwordless account deletes itself after a fresh confirmation
    assert anon.request("DELETE", "/api/me", json={"confirm": "DELETE"}).status_code == 204


def test_an_admin_signed_in_by_the_provider_is_not_asked_for_the_apps_code(admin, anon, provider):
    from app.auth import totp

    # Turn on two-step for the admin (needed to switch the rule on), set the rule, then remove the admin's code.
    s = admin.post("/api/me/totp/setup").json()
    code = totp.totp(totp.secret_from_text(s["secret"]), time.time())
    assert admin.post("/api/me/totp/enable", json={"code": code}).status_code == 200
    set_setting(admin, **{"auth.require_two_step_admins": True})
    link_admin(admin, provider)
    with database(admin) as conn:
        conn.execute("DELETE FROM totp_factors")
    # a password session is blocked from admin routes, a provider session is not
    assert admin.get("/api/admin/users").status_code == 403
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub"})
    assert r.headers["location"] == "/"
    assert anon.get("/api/admin/users").status_code == 200
    assert anon.get("/api/me/totp").json()["required"] is False


# --------------------------------------------------------------------------- #
# The secret, the address checks, the settings
# --------------------------------------------------------------------------- #


def test_about_shows_the_connection_but_never_the_secret(admin, provider):
    about = admin.get("/api/admin/about").json()["oidc"]
    assert about["enabled"] is True and about["issuer"] == ISSUER and about["client_id"] == CLIENT_ID
    assert about["secret"] == "set" and about["redirect_uri"] == "https://localhost/api/auth/oidc/callback"
    for path in ("/api/admin/about", "/api/admin/settings", "/api/auth/status", "/api/me/oidc"):
        assert CLIENT_SECRET not in admin.get(path).text
    assert CLIENT_SECRET not in repr(admin.app.state.auth.settings)
    assert CLIENT_SECRET in admin.app.state.auth.settings.secret_values()


def test_a_private_issuer_is_refused_unless_allowed(tmp_path, foods_json):
    provider = FakeProvider()
    provider.address = "192.168.1.20"  # a home Authentik
    application = create_app(oidc_settings(tmp_path / "a", foods_json))
    attach(application, provider)
    with TestClient(application, base_url=HTTPS_URL) as c:
        r = c.get("/api/auth/oidc/start", follow_redirects=False)
        assert r.headers["location"] == "/#/oidc/unavailable"
        assert provider.calls == []  # nothing was sent
        sign_in(c)
        assert c.get("/api/admin/about").json()["oidc"]["discovery"] == "blocked_address"
    allowed = create_app(oidc_settings(tmp_path / "b", foods_json, oidc=env(allow_private_issuer=True)))
    attach(allowed, provider)
    with TestClient(allowed, base_url=HTTPS_URL) as c:
        r = c.get("/api/auth/oidc/start", follow_redirects=False)
        assert r.headers["location"].startswith(provider.base + "/authorize")
    provider.address = "169.254.169.254"  # metadata addresses: never, even when private ones are allowed
    allowed.state.oidc._metadata = None
    with TestClient(allowed, base_url=HTTPS_URL) as c:
        assert c.get("/api/auth/oidc/start", follow_redirects=False).headers["location"] == "/#/oidc/unavailable"


def test_discovery_must_name_the_same_issuer_and_https_endpoints(admin, anon, provider):
    provider.discovery_extra = {"issuer": "https://other.example/"}
    assert anon.get("/api/auth/oidc/start", follow_redirects=False).headers["location"] == "/#/oidc/unavailable"
    provider.discovery_extra = {"token_endpoint": "http://idp.example.org/token"}
    assert anon.get("/api/auth/oidc/start", follow_redirects=False).headers["location"] == "/#/oidc/unavailable"
    provider.discovery_extra = {"code_challenge_methods_supported": ["plain"]}
    assert anon.get("/api/auth/oidc/start", follow_redirects=False).headers["location"] == "/#/oidc/unavailable"
    provider.discovery_extra = {}
    assert anon.get("/api/auth/oidc/start", follow_redirects=False).headers["location"].startswith(provider.base)


def test_discovery_url_keeps_authentik_issuers_working():
    assert oidc.discovery_url("https://auth.example.org/application/o/kh/") == \
        "https://auth.example.org/application/o/kh/.well-known/openid-configuration"
    assert oidc.discovery_url("https://accounts.google.com") == "https://accounts.google.com/.well-known/openid-configuration"


def test_a_public_client_sends_only_its_id(tmp_path, foods_json):
    provider = FakeProvider(client_secret=None)
    application = create_app(oidc_settings(tmp_path, foods_json, oidc=env(client_secret=None)))
    attach(application, provider)
    with TestClient(application, base_url=HTTPS_URL) as c:
        sign_in(c)
        r = c.post("/api/me/oidc/link")
        back = come_back(c, provider, r.json()["url"], claims={"sub": "pub"})
        assert back.headers["location"] == "/#/oidc/linked"
        assert provider.token_forms[-1]["client_id"] == [CLIENT_ID] and "authorization" not in provider.token_headers[-1]


def write(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text + "\n", encoding="utf-8")
    return str(path)


def base_env(tmp_path, **extra: str) -> dict[str, str]:
    values = {"DATA_DIR": str(tmp_path / "data"), "OIDC_ENABLED": "true", "OIDC_ISSUER": "https://accounts.google.com",
              "OIDC_CLIENT_ID": "abc.apps.googleusercontent.com", "PUBLIC_URL": "https://kidney.example.org"}
    values.update(extra)
    return values


def test_config_reads_the_secret_only_from_a_file(tmp_path):
    secret_file = write(tmp_path, "oidc_secret", "s3cr3t-value")
    s = load_settings(base_env(tmp_path, OIDC_CLIENT_SECRET_FILE=secret_file))
    assert s.oidc.enabled and s.oidc.client_secret == "s3cr3t-value" and s.oidc.scopes == "openid email profile"
    assert "s3cr3t-value" not in repr(s) and "s3cr3t-value" in s.secret_values()
    with pytest.raises(ConfigError, match="OIDC_CLIENT_SECRET_FILE"):
        load_settings(base_env(tmp_path, OIDC_CLIENT_SECRET="s3cr3t-value"))


@pytest.mark.parametrize("extra, message", [
    ({"PUBLIC_URL": ""}, "PUBLIC_URL"),
    ({"AUTH_MODE": "none"}, "AUTH_MODE=local"),
    ({"OIDC_ISSUER": ""}, "OIDC_ISSUER"),
    ({"OIDC_ISSUER": "http://idp.example.org"}, "https://"),
    ({"OIDC_ISSUER": "https://idp.example.org/?x=1"}, "query"),
    ({"OIDC_CLIENT_ID": ""}, "OIDC_CLIENT_ID"),
    ({"OIDC_SCOPES": "email profile"}, "openid"),
])
def test_config_refuses_an_incomplete_setup(tmp_path, extra, message):
    with pytest.raises(ConfigError, match=message):
        load_settings(base_env(tmp_path, **extra))


def test_config_off_by_default_and_warns_about_stray_values(tmp_path):
    s = load_settings({"DATA_DIR": str(tmp_path / "d"), "OIDC_ISSUER": "https://accounts.google.com"})
    assert s.oidc.enabled is False
    assert any("OIDC_ENABLED" in w for w in s.warnings)
    s = load_settings(base_env(tmp_path, OIDC_ISSUER="http://127.0.0.1:8251"))  # loopback http, for tests and the local walk
    assert s.oidc.issuer == "http://127.0.0.1:8251"


def test_flow_store_is_single_use_and_bounded(monkeypatch):
    store = oidc.FlowStore(max_items=3, ttl_s=600)
    state, binder, _ = store.issue("signin", key="a")
    assert store.take(state, "wrong") is None and store.take(state, None) is None  # a wrong cookie changes nothing
    assert store.take(state, binder) is not None and store.take(state, binder) is None  # once
    issued = [store.issue("signin", key=f"k{n}") for n in range(3)]
    with pytest.raises(oidc.FlowStoreFull):  # full: refused, nothing waiting is dropped
        store.issue("signin", key="k9")
    assert len(store) == 3 and store.take(issued[0][0], issued[0][1]) is not None
    state, binder, _ = store.issue("signin", key="late")
    real = clock.seconds
    monkeypatch.setattr(clock, "seconds", lambda: real() + 601)
    assert store.take(state, binder) is None
    store.issue("signin", key="after")  # expired flows make room again
    assert len(store) == 1



# --------------------------------------------------------------------------- #
# Security review 2026-10-30 (the reviewer's proofs in scratchpad/oidc-review/test_poc_oidc.py, turned into regressions)
# --------------------------------------------------------------------------- #

SQUATTER_PASSWORD = "copper-meadow-violin-42"


def admin_made_account(admin: TestClient, username: str, role: str = "user") -> int:
    """An account the admin created in People: pending_setup, no password yet, a one-time setup link."""
    r = admin.post("/api/admin/users", json={"username": username, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["user"]["id"]


def test_review1_link_by_email_never_joins_a_self_registered_account(admin, anon, provider):
    """Pre-hijacking: an invited person registers the username victim@example.org with their own password. The real owner's first
    sign-in with the provider must not land in that account."""
    set_setting(admin, **{"auth.oidc.link_by_email": True})
    squatter = add_user(admin, username="victim@example.org", password=SQUATTER_PASSWORD)
    squatter_id = squatter.get("/api/me").json()["id"]
    r = sign_in_with_provider(anon, provider, claims={"sub": "real-victim", "email": "victim@example.org", "email_verified": True})
    assert r.headers["location"] == "/#/oidc/no_account"
    with database(admin) as conn:
        assert conn.execute("SELECT COUNT(*) FROM oidc_links WHERE user_id = ?", (squatter_id,)).fetchone()[0] == 0


def test_review1_link_by_email_plus_admin_groups_never_promotes_a_squatter(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.link_by_email": True, "auth.oidc.admin_groups": "family-admins"})
    squatter = add_user(admin, username="boss@example.org", password=SQUATTER_PASSWORD)
    r = sign_in_with_provider(anon, provider, claims={"sub": "real-boss", "email": "boss@example.org", "email_verified": True,
                                                      "groups": ["family-admins"]})
    assert r.headers["location"] != "/"
    later = TestClient(admin.app, base_url=HTTPS_URL)
    sign_in(later, "boss@example.org", SQUATTER_PASSWORD)
    assert later.get("/api/me").json()["role"] == "user" and later.get("/api/admin/users").status_code == 403
    del squatter


def test_review1_link_by_email_only_activates_an_account_the_admin_made(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.link_by_email": True, "auth.oidc.admin_groups": "family-admins"})
    uid = admin_made_account(admin, "gran@example.org")
    r = sign_in_with_provider(anon, provider, claims={"sub": "gran-sub", "email": "gran@example.org", "groups": ["family-admins"]})
    assert r.headers["location"] == "/"
    me = anon.get("/api/me").json()
    assert me["id"] == uid and me["username"] == "gran@example.org"
    assert me["role"] == "user"  # no promotion on the sign-in that linked by email
    with database(admin) as conn:
        row = conn.execute("SELECT status, password_hash FROM users WHERE id = ?", (uid,)).fetchone()
        assert row["status"] == "active" and row["password_hash"] is None
        # the admin's setup link for that account no longer works
        assert conn.execute("SELECT COUNT(*) FROM auth_tokens WHERE user_id = ? AND used_at IS NULL", (uid,)).fetchone()[0] == 0
    # the next sign-in follows the groups
    sign_in_with_provider(anon, provider, claims={"sub": "gran-sub", "email": "gran@example.org", "groups": ["family-admins"]})
    assert anon.get("/api/me").json()["role"] == "admin"


@pytest.mark.parametrize("username, email", [
    ("strasse@example.org", "straße@example.org"),  # NFKC/casefold would merge these two mailboxes
    ("kelvin@example.org", "Kelvin@example.org"),  # KELVIN SIGN
    ("full@example.org", "ｆull@example.org"),  # fullwidth f
])
def test_review1_link_by_email_compares_plain_ascii_only(admin, anon, provider, username, email):
    set_setting(admin, **{"auth.oidc.link_by_email": True})
    add_user(admin, username=username)  # a self-registered account (NFKC/casefold merged these before the fix)
    r = sign_in_with_provider(anon, provider, claims={"sub": f"sub-{username}", "email": email})
    assert r.headers["location"] == "/#/oidc/no_account"
    pending = "p-" + username
    admin_made_account(admin, pending)  # an account the admin made: only the same plain ASCII address links
    r = sign_in_with_provider(anon, provider, claims={"sub": f"sub2-{username}", "email": "p-" + email})
    assert r.headers["location"] == "/#/oidc/no_account"
    r = sign_in_with_provider(anon, provider, claims={"sub": f"sub3-{username}", "email": pending.upper()})
    assert r.headers["location"] == "/"


def test_review1_link_by_email_skips_accounts_with_any_way_in(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.link_by_email": True})
    uid = admin_made_account(admin, "has-key@example.org")
    with database(admin) as conn:  # a pending account that somehow already has a passkey
        conn.execute("INSERT INTO passkeys (user_id, credential_id, public_key, alg, user_handle, name, created_at) "
                     "VALUES (?, x'01', x'02', -7, x'03', 'phone', '2026-10-30T00:00:00Z')", (uid,))
    r = sign_in_with_provider(anon, provider, claims={"sub": "hk", "email": "has-key@example.org"})
    assert r.headers["location"] == "/#/oidc/no_account"
    admin_made_account(admin, "boss2@example.org", role="admin")
    r = sign_in_with_provider(anon, provider, claims={"sub": "b2", "email": "boss2@example.org"})
    assert r.headers["location"] == "/#/oidc/no_account"


def test_review2_made_up_callbacks_never_lock_the_address_out(admin, provider):
    nav = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
    victim = TestClient(admin.app, base_url=HTTPS_URL)
    started = victim.get("/api/auth/oidc/start", follow_redirects=False)
    code, state, _ = provider.authorize(started.headers["location"], claims={"sub": "nobody"})
    for i in range(25):
        r = victim.get("/api/auth/oidc/callback", params={"state": f"junk{i}", "code": "x"}, headers=nav, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/#/oidc/expired"
        assert "kh_oidc" not in r.headers.get("set-cookie", "")  # the visitor's own waiting flow keeps its cookie
    r = victim.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    # and the visitor's real flow still finishes
    back = victim.get("/api/auth/oidc/callback", params={"code": code, "state": state}, headers=nav, follow_redirects=False)
    assert back.headers["location"] == "/#/oidc/no_account" and "kh_oidc=\"\"" in back.headers.get("set-cookie", "")


def test_review3_link_by_email_keeps_the_https_rule(tmp_path, foods_json):
    provider = FakeProvider()
    application = create_app(oidc_settings(tmp_path, foods_json))
    attach(application, provider)
    with TestClient(application, base_url=HTTPS_URL) as adm:
        sign_in(adm)
        set_setting(adm, **{"auth.oidc.link_by_email": True})
        add_user(adm, username="sam")  # two active accounts: plain HTTP sign-in is refused from other machines
        admin_made_account(adm, "kim@example.org")
        plain = TestClient(application, base_url="http://localhost", client=("192.0.2.10", 5000))
        r = sign_in_with_provider(plain, provider, claims={"sub": "kim-sub", "email": "kim@example.org"})
        assert r.headers["location"] == "/#/oidc/https"
        assert plain.get("/api/me").status_code == 401


def add_passkey_row(client: TestClient, uid: int) -> int:
    with database(client) as conn:  # stand-in for a registered passkey (the WebAuthn ceremony is not the point here)
        conn.execute("INSERT INTO passkeys (user_id, credential_id, public_key, alg, user_handle, name, created_at) "
                     "VALUES (?, ?, x'02', -7, x'03', 'phone', '2026-10-30T00:00:00Z')", (uid, bytes([uid % 250 + 1, 7])))
        return conn.execute("SELECT MAX(id) FROM passkeys WHERE user_id = ?", (uid,)).fetchone()[0]


def test_review4_the_last_way_in_survives_passkey_removal(admin, anon, provider):
    set_setting(admin, **{"auth.oidc.allow_signup": True})
    assert sign_in_with_provider(anon, provider, claims={"sub": "p1", "email": "p1@example.org"}).headers["location"] == "/"
    uid = anon.get("/api/me").json()["id"]
    pk = add_passkey_row(admin, uid)
    link_id = anon.get("/api/me/oidc").json()["links"][0]["id"]
    assert anon.delete(f"/api/me/oidc/{link_id}").status_code == 204  # two ways in: the link may go
    r = anon.delete(f"/api/me/passkeys/{pk}")
    assert r.status_code == 409 and "only way to sign in" in r.json()["detail"]
    from app.auth.oidc_api import ways_in

    with database(admin) as conn:
        assert ways_in(conn, uid) == 1
    # with a password the passkey can still go
    pk2 = add_passkey_row(admin, 1)
    assert admin.delete(f"/api/me/passkeys/{pk2}").status_code == 204


def test_review5_a_flood_of_starts_never_pushes_out_someone_elses_flow():
    store = oidc.FlowStore(max_items=3, per_key=2)
    state, binder, _ = store.issue("signin", key="victim")
    for n in range(2):
        store.issue("signin", key=f"flood{n}")
    with pytest.raises(oidc.FlowStoreFull):
        store.issue("signin", key="flood9")
    assert store.take(state, binder) is not None  # still there
    with pytest.raises(oidc.FlowStoreFull):  # one address cannot hold more than its share
        for _ in range(3):
            store.issue("signin", key="flood0")


def test_review5_a_full_store_answers_a_plain_message(admin, anon, provider):
    oc = admin.app.state.oidc
    oc.flows = oidc.FlowStore(max_items=1)
    first = anon.get("/api/auth/oidc/start", follow_redirects=False)
    assert first.headers["location"].startswith(provider.base)
    second = TestClient(admin.app, base_url=HTTPS_URL).get("/api/auth/oidc/start", follow_redirects=False)
    assert second.headers["location"] == "/#/oidc/full"
    r = admin.post("/api/me/oidc/link")
    assert r.status_code == 503 and "Too many sign-ins started" in r.json()["detail"]


def test_review6_google_needs_hd_when_domains_are_set(tmp_path, foods_json):
    google = "https://accounts.google.com"
    provider = FakeProvider(issuer=google)
    application = create_app(oidc_settings(tmp_path, foods_json, oidc=env(issuer=google)))
    attach(application, provider)
    with TestClient(application, base_url=HTTPS_URL) as adm:
        sign_in(adm)
        set_setting(adm, **{"auth.oidc.allow_signup": True, "auth.oidc.allowed_domains": "corp.example"})
        other = TestClient(application, base_url=HTTPS_URL)
        # a personal Google account that uses a corp address: no hd
        r = sign_in_with_provider(other, provider, claims={"sub": "g-personal", "email": "ann@corp.example"})
        assert r.headers["location"] == "/#/oidc/domain"
        r = sign_in_with_provider(other, provider, claims={"sub": "g-work", "email": "ann@corp.example", "hd": "corp.example"})
        assert r.headers["location"] == "/"


def test_review7_code_and_state_are_redacted_in_the_access_log():
    from app import security

    line = '127.0.0.1:5 - "GET /api/auth/oidc/callback?code=4/0AbCdEf-secret_code&state=Zx9_state-value&iss=https%3A HTTP/1.1" 303'
    out = security.redact(line)
    assert "4/0AbCdEf-secret_code" not in out and "Zx9_state-value" not in out
    assert "code=[redacted]" in out and "state=[redacted]" in out and "iss=https%3A" in out
    assert security.redact("returncode=1 statement=ok") == "returncode=1 statement=ok"


@pytest.mark.parametrize("change", [{"exp": float("inf")}, {"iat": float("nan")}, {"exp": float("nan")}])
def test_review_non_finite_times_are_refused(admin, anon, provider, change):
    link_admin(admin, provider)
    r = sign_in_with_provider(anon, provider, claims={"sub": "admin-sub", **change})
    assert r.headers["location"] == "/#/oidc/failed"
