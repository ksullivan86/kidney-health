"""Several sign-in providers at once and the provider-only mode (design note 24 §13).

Two fake providers (:mod:`oidc_support`), "authentik" and "google", each with its own keys, issuer and redirect URI: signing in
with each, linking both, removing one, a code or a state of one refused at the other, the last way in across providers, admin
groups per provider, a test account never promoted, the settings of each provider, the flow store's share per provider and the
admin's About page. Then ``OIDC_ONLY``: passwords refused (test accounts excepted), password sign-up refused, start-up refused
without a provider, and what the sign-in page is told. No network.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

from app.auth import oidc
from app.config import ConfigError, OidcEnv, load_settings
from app.main import create_app
from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, HTTPS_URL, TestClient, invite_token, make_settings, sign_in
from oidc_support import CLIENT_ID, CLIENT_SECRET, FakeProvider, attach, come_back, named_env, sign_in_with_provider
from test_test_accounts import PASSWORD as TESTER_PHRASE
from test_test_accounts import pw_file  # noqa: F401  (a fixture: the test accounts' password file, as there)

PUBLIC_URL = "https://localhost"
REPO = Path(__file__).resolve().parents[1]
ISSUER_A = "https://auth.example.org/application/o/kidney/"
ISSUER_G = "https://login.example.net"


@pytest.fixture
def authentik() -> FakeProvider:
    return FakeProvider(issuer=ISSUER_A)


@pytest.fixture
def google() -> FakeProvider:
    return FakeProvider(issuer=ISSUER_G, client_id="google-client")


def two_env(**changes: Any) -> OidcEnv:
    """OIDC_PROVIDERS=authentik,google (no OIDC_ISSUER). ``changes`` are keyed ``authentik_<field>`` or ``google_<field>``."""
    a = {k.removeprefix("authentik_"): v for k, v in changes.items() if k.startswith("authentik_")}
    g = {k.removeprefix("google_"): v for k, v in changes.items() if k.startswith("google_")}
    top = {k: v for k, v in changes.items() if not k.startswith(("authentik_", "google_"))}
    return OidcEnv(enabled=True, providers=(named_env("authentik", ISSUER_A, **a), named_env("google", ISSUER_G, client_id="google-client", **g)),
                   **top)


def make_app(tmp_path, foods_json, authentik, google, **env: Any):
    application = create_app(make_settings(tmp_path, foods_json, public_url=PUBLIC_URL, oidc=two_env(**env)))
    attach(application, authentik, "authentik")
    attach(application, google, "google")
    return application


@pytest.fixture
def app(tmp_path, foods_json, authentik, google):
    return make_app(tmp_path, foods_json, authentik, google)


@pytest.fixture
def admin(app) -> Iterator[TestClient]:
    with TestClient(app, base_url=HTTPS_URL) as c:
        sign_in(c)
        yield c


@pytest.fixture
def anon(app, admin) -> TestClient:
    return TestClient(app, base_url=HTTPS_URL)


def database(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.auth.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def set_setting(admin: TestClient, **values: Any) -> None:
    r = admin.patch("/api/admin/settings", json=values)
    assert r.status_code == 200, r.text


def link(client: TestClient, fake: FakeProvider, provider_id: str, sub: str, **claims: Any) -> str:
    r = client.post("/api/me/oidc/link", params={"provider": provider_id})
    assert r.status_code == 200, r.text
    return come_back(client, fake, r.json()["url"], claims={"sub": sub, **claims}).headers["location"]


# --------------------------------------------------------------------------- #
# Two providers
# --------------------------------------------------------------------------- #


def test_the_sign_in_page_gets_one_button_per_provider(anon):
    st = anon.get("/api/auth/status").json()["oidc"]
    assert st["providers"] == [{"id": "authentik", "label": "Sign in with Authentik"}, {"id": "google", "label": "Sign in with Google"}]
    assert st["enabled"] is True and st["label"] == "Sign in with Authentik" and st["only"] is False and st["password"] == "on"
    text = anon.get("/api/auth/status").text
    assert ISSUER_A not in text and ISSUER_G not in text and CLIENT_ID not in text


def test_each_provider_has_its_own_way_back(anon, authentik, google):
    r = anon.get("/api/auth/oidc/start", follow_redirects=False)  # no provider: the first one
    _, _, query = authentik.authorize(r.headers["location"])
    assert query["redirect_uri"] == "https://localhost/api/auth/oidc/callback/authentik"
    r = anon.get("/api/auth/oidc/start", params={"provider": "google"}, follow_redirects=False)
    _, _, query = google.authorize(r.headers["location"])
    assert query["redirect_uri"] == "https://localhost/api/auth/oidc/callback/google" and query["client_id"] == "google-client"
    # a provider that is not set up, and the first provider's old address while there is none, are 404
    assert anon.get("/api/auth/oidc/start", params={"provider": "github"}, follow_redirects=False).status_code == 404
    assert anon.get("/api/auth/oidc/callback", params={"code": "x", "state": "y"}, follow_redirects=False).status_code == 404
    assert anon.get("/api/auth/oidc/callback/github", params={"code": "x", "state": "y"}, follow_redirects=False).status_code == 404
    assert anon.get("/api/auth/oidc/start", params={"provider": "Google"}, follow_redirects=False).status_code == 400


def test_link_both_sign_in_with_each_and_remove_one(admin, anon, authentik, google):
    assert link(admin, authentik, "authentik", "a-admin") == "/#/oidc/linked/authentik"
    assert link(admin, google, "google", "g-admin", email="boss@example.net") == "/#/oidc/linked/google"
    st = admin.get("/api/me/oidc").json()
    assert [(p["id"], p["linked"]) for p in st["providers"]] == [("authentik", True), ("google", True)]
    assert st["can_link"] is False
    assert [(link_["provider_id"], link_["name"], link_["current"]) for link_ in st["links"]] == [
        ("authentik", "Authentik", True), ("google", "Google", True)]
    assert admin.post("/api/me/oidc/link", params={"provider": "google"}).status_code == 409  # one link per provider
    for fake, pid, sub in ((authentik, "authentik", "a-admin"), (google, "google", "g-admin")):
        browser = TestClient(admin.app, base_url=HTTPS_URL)
        back = sign_in_with_provider(browser, fake, provider_id=pid, claims={"sub": sub})
        assert back.headers["location"] == "/", pid
        assert browser.get("/api/me").json()["username"] == ADMIN_USERNAME
    google_link = next(item for item in st["links"] if item["provider_id"] == "google")
    assert admin.delete(f"/api/me/oidc/{google_link['id']}").status_code == 204
    st = admin.get("/api/me/oidc").json()
    assert [p["linked"] for p in st["providers"]] == [True, False] and st["can_link"] is True
    back = sign_in_with_provider(anon, google, provider_id="google", claims={"sub": "g-admin"})
    assert back.headers["location"] == "/#/oidc/no_account/google"


def test_a_state_or_a_code_of_one_provider_is_refused_at_the_other(admin, anon, authentik, google):
    link(admin, authentik, "authentik", "a-admin")
    link(admin, google, "google", "g-admin")
    # The state of an Authentik sign-in brought to Google's way back: nothing taken, nothing counted.
    asked = (len(authentik.token_forms), len(google.token_forms))
    r = anon.get("/api/auth/oidc/start", params={"provider": "authentik"}, follow_redirects=False)
    code_a, state_a, _ = authentik.authorize(r.headers["location"], claims={"sub": "a-admin"})
    wrong = anon.get("/api/auth/oidc/callback/google", params={"code": code_a, "state": state_a}, follow_redirects=False)
    assert wrong.headers["location"] == "/#/oidc/expired/google" and "set-cookie" not in wrong.headers
    assert (len(authentik.token_forms), len(google.token_forms)) == asked  # no provider was asked to redeem anything
    # The flow still waits for its own way back.
    right = anon.get("/api/auth/oidc/callback/authentik", params={"code": code_a, "state": state_a}, follow_redirects=False)
    assert right.headers["location"] == "/"
    # A code Authentik made (in another browser) brought back inside a Google flow: Google's token endpoint does not know it.
    other = TestClient(admin.app, base_url=HTTPS_URL)
    r = other.get("/api/auth/oidc/start", params={"provider": "google"}, follow_redirects=False)
    _, state_g, _ = google.authorize(r.headers["location"], claims={"sub": "g-admin"})
    r = TestClient(admin.app, base_url=HTTPS_URL).get("/api/auth/oidc/start", params={"provider": "authentik"}, follow_redirects=False)
    code_a2, _, _ = authentik.authorize(r.headers["location"], claims={"sub": "a-admin"})
    mixed = other.get("/api/auth/oidc/callback/google", params={"code": code_a2, "state": state_g}, follow_redirects=False)
    assert mixed.headers["location"] == "/#/oidc/failed/google"
    assert google.token_forms[-1]["code"] == [code_a2]  # only Google, which does not know it, was asked
    assert all(form["code"] != [code_a2] for form in authentik.token_forms)


def test_the_issuer_is_checked_per_provider(admin, authentik, google):
    link(admin, google, "google", "g-admin")
    browser = TestClient(admin.app, base_url=HTTPS_URL)
    # Google's flow, but the answer names Authentik in the iss parameter (a mix-up) or in the ID token.
    r = browser.get("/api/auth/oidc/start", params={"provider": "google"}, follow_redirects=False)
    code, state, _ = google.authorize(r.headers["location"], claims={"sub": "g-admin"})
    back = browser.get("/api/auth/oidc/callback/google", params={"code": code, "state": state, "iss": ISSUER_A}, follow_redirects=False)
    assert back.headers["location"] == "/#/oidc/failed/google"
    back = sign_in_with_provider(browser, google, provider_id="google", claims={"sub": "g-admin", "iss": ISSUER_A})
    assert back.headers["location"] == "/#/oidc/failed/google"
    # Authentik's subject of the same value is another person: a link is per issuer.
    back = sign_in_with_provider(browser, authentik, provider_id="authentik", claims={"sub": "g-admin"})
    assert back.headers["location"] == "/#/oidc/no_account/authentik"
    assert sign_in_with_provider(browser, google, provider_id="google", claims={"sub": "g-admin"}).headers["location"] == "/"


def test_the_cross_site_way_back_works_for_a_named_provider(admin, anon, google):
    link(admin, google, "google", "g-admin")
    nav = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
    r = anon.get("/api/auth/oidc/start", params={"provider": "google"}, follow_redirects=False)
    code, state, _ = google.authorize(r.headers["location"], claims={"sub": "g-admin"})
    fetch = {**nav, "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
    assert anon.get("/api/auth/oidc/callback/google", params={"code": code, "state": state}, headers=fetch).status_code == 403
    assert anon.get("/api/auth/oidc/callback/google/x", headers=nav).status_code == 403
    back = anon.get("/api/auth/oidc/callback/google", params={"code": code, "state": state}, headers=nav, follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == "/"


def test_the_last_way_in_counts_links_of_every_provider(admin, anon, authentik, google):
    set_setting(admin, **{"auth.oidc.allow_signup": True})
    assert sign_in_with_provider(anon, authentik, provider_id="authentik",
                                 claims={"sub": "only", "email": "only@example.org"}).headers["location"] == "/"
    assert link(anon, google, "google", "only-g") == "/#/oidc/linked/google"
    st = anon.get("/api/me/oidc").json()
    assert st["has_password"] is False and len(st["links"]) == 2
    first, second = st["links"]
    assert anon.delete(f"/api/me/oidc/{first['id']}").status_code == 204  # Google is still a way in
    r = anon.delete(f"/api/me/oidc/{second['id']}")
    assert r.status_code == 409 and "only way to sign in" in r.json()["detail"]
    # Google alone now signs this person in
    browser = TestClient(admin.app, base_url=HTTPS_URL)
    assert sign_in_with_provider(browser, google, provider_id="google", claims={"sub": "only-g"}).headers["location"] == "/"


def test_re_entry_offers_each_linked_provider(admin, google):
    link(admin, google, "google", "g-admin")
    with database(admin) as conn:
        conn.execute("UPDATE sessions SET reauth_at = NULL")
    assert admin.post("/api/auth/reauth/oidc", params={"provider": "authentik"}).status_code == 409  # not linked
    r = admin.post("/api/auth/reauth/oidc")  # no provider: the first one this person linked
    assert r.status_code == 200
    back = come_back(admin, google, r.json()["url"], claims={"sub": "g-admin"})
    assert back.headers["location"] == "/#/oidc/confirmed/google"


def test_admin_groups_and_sign_up_follow_each_provider(tmp_path, foods_json, authentik, google):
    application = make_app(tmp_path, foods_json, authentik, google, authentik_admin_groups="kidney admins",
                           authentik_allow_signup=True, google_allowed_domains="example.net")
    with TestClient(application, base_url=HTTPS_URL) as admin:
        sign_in(admin)
        set_setting(admin, **{"auth.oidc.admin_groups": "other"})  # the server-wide list, used by Google here
        anon = TestClient(application, base_url=HTTPS_URL)
        # Authentik may make accounts (its own switch), Google may not (the server-wide one is off)
        back = sign_in_with_provider(anon, authentik, provider_id="authentik",
                                     claims={"sub": "kim", "email": "kim@example.org", "groups": ["kidney admins"]})
        assert back.headers["location"] == "/"
        assert anon.get("/api/me").json()["role"] == "admin"
        back = sign_in_with_provider(TestClient(application, base_url=HTTPS_URL), google, provider_id="google",
                                     claims={"sub": "new", "email": "new@example.net"})
        assert back.headers["location"] == "/#/oidc/no_account/google"
        # Google's own domain list: an address elsewhere is refused before anything else
        back = sign_in_with_provider(TestClient(application, base_url=HTTPS_URL), google, provider_id="google",
                                     claims={"sub": "x", "email": "x@example.org"})
        assert back.headers["location"] == "/#/oidc/domain/google"
        assert link(anon, google, "google", "kim-g", email="kim@example.net") == "/#/oidc/linked/google"
        # Signing in with Google uses the server-wide groups ("other"): Kim is not in them, so Kim becomes a user again
        browser = TestClient(application, base_url=HTTPS_URL)
        back = sign_in_with_provider(browser, google, provider_id="google", claims={"sub": "kim-g", "email": "kim@example.net",
                                                                                   "groups": ["kidney admins"]})
        assert back.headers["location"] == "/" and browser.get("/api/me").json()["role"] == "user"
        with database(admin) as conn:
            row = conn.execute("SELECT details_json FROM audit_log WHERE action = 'user.role_changed' ORDER BY id").fetchall()
        assert ['"provider":"authentik"' in r[0] for r in row] == [True, False]
        about = admin.get("/api/admin/about").json()["oidc"]
        assert [(p["id"], p["admin_groups"], p["allow_signup"], p["allowed_domains"]) for p in about["providers"]] == [
            ("authentik", "kidney admins", True, ""), ("google", "other", False, "example.net")]


def test_the_about_page_shows_each_provider_without_its_secret(admin, authentik):
    sign_in_with_provider(TestClient(admin.app, base_url=HTTPS_URL), authentik, provider_id="authentik")  # reach Authentik once
    about = admin.get("/api/admin/about")
    o = about.json()["oidc"]
    assert o["enabled"] is True and o["only"] is False and o["admins_linked"] == 0
    assert [(p["id"], p["issuer"], p["redirect_uri"], p["secret"]) for p in o["providers"]] == [
        ("authentik", ISSUER_A, "https://localhost/api/auth/oidc/callback/authentik", "set"),
        ("google", ISSUER_G, "https://localhost/api/auth/oidc/callback/google", "set")]
    assert o["providers"][0]["discovery"] == "ok" and o["issuer"] == ISSUER_A  # the top level is the first provider, as before
    assert o["providers"][1]["discovery"] is None  # nobody pressed the Google button yet: not asked, not "reached"
    assert CLIENT_SECRET not in about.text


def test_the_flow_store_keeps_a_share_for_each_provider(monkeypatch):
    store = oidc.FlowStore(max_items=10, per_provider=2)
    for n in range(2):
        store.issue("signin", key=f"a{n}", provider="authentik")
    with pytest.raises(oidc.FlowStoreFull):  # Authentik's share is full ...
        store.issue("signin", key="a9", provider="authentik")
    state, binder, _ = store.issue("signin", key="g0", provider="google")  # ... Google still has room
    assert store.count("authentik") == 2 and store.count("google") == 1
    assert store.take(state, binder, "authentik") is None and len(store) == 3  # another provider's way back takes nothing
    assert store.take(state, binder, "google") is not None and store.count("google") == 0


def test_the_app_shares_the_store_out_evenly(app):
    clients = list(app.state.oidc_providers.values())
    assert [c.id for c in clients] == ["authentik", "google"] and clients[0].flows is clients[1].flows
    assert clients[0].flows._provider_cap == oidc.MAX_FLOWS // 2


def test_the_first_provider_keeps_its_old_address_next_to_named_ones(tmp_path, foods_json, authentik, google):
    """OIDC_ISSUER… stays the first provider (id ``default``, the old callback and the registry's button words)."""
    env = OidcEnv(enabled=True, issuer=ISSUER_A, client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
                  providers=(named_env("google", ISSUER_G, client_id="google-client", button_label="Use Google"),))
    application = create_app(make_settings(tmp_path, foods_json, public_url=PUBLIC_URL, oidc=env))
    attach(application, authentik)
    attach(application, google, "google")
    with TestClient(application, base_url=HTTPS_URL) as admin:
        sign_in(admin)
        st = admin.get("/api/auth/status").json()["oidc"]
        assert st["providers"] == [{"id": "default", "label": "Sign in with single sign-on"}, {"id": "google", "label": "Use Google"}]
        r = admin.post("/api/me/oidc/link")
        assert "redirect_uri=https%3A%2F%2Flocalhost%2Fapi%2Fauth%2Foidc%2Fcallback&" in r.json()["url"]
        assert come_back(admin, authentik, r.json()["url"], claims={"sub": "a"}).headers["location"] == "/#/oidc/linked"
        assert link(admin, google, "google", "g") == "/#/oidc/linked/google"


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def base_env(tmp_path, **extra: str) -> dict[str, str]:
    values = {"DATA_DIR": str(tmp_path / "d"), "OIDC_ENABLED": "true", "PUBLIC_URL": "https://kidney.example.org",
              "OIDC_PROVIDERS": "authentik, Google", "OIDC_AUTHENTIK_ISSUER": ISSUER_A, "OIDC_AUTHENTIK_CLIENT_ID": "kh",
              "OIDC_GOOGLE_ISSUER": "https://accounts.google.com", "OIDC_GOOGLE_CLIENT_ID": "123.apps.googleusercontent.com"}
    values.update(extra)
    return {k: v for k, v in values.items() if v is not None}


def test_config_reads_each_named_provider(tmp_path):
    secret = tmp_path / "google-client"
    secret.write_text("value-from-file\n", encoding="utf-8")
    s = load_settings(base_env(tmp_path, OIDC_GOOGLE_CLIENT_SECRET_FILE=str(secret), OIDC_GOOGLE_ALLOWED_DOMAINS="example.org",
                               OIDC_AUTHENTIK_ALLOW_PRIVATE_ISSUER="true", OIDC_AUTHENTIK_ADMIN_GROUPS="authentik Admins",
                               OIDC_AUTHENTIK_ALLOW_SIGNUP="true", OIDC_GOOGLE_SCOPES="openid email"))
    a, g = s.oidc.all()
    assert (a.id, a.issuer, a.client_id, a.allow_private_issuer, a.admin_groups, a.allow_signup, a.secret_set) == (
        "authentik", ISSUER_A, "kh", True, "authentik Admins", True, False)
    assert (g.id, g.allowed_domains, g.scopes, g.secret_set, g.allow_signup) == ("google", "example.org", "openid email", True, None)
    assert "value-from-file" in s.secret_values() and "value-from-file" not in repr(s)
    assert any("OIDC_AUTHENTIK_CLIENT_SECRET_FILE" in w for w in s.warnings)


@pytest.mark.parametrize("extra, message", [
    ({"OIDC_GOOGLE_CLIENT_SECRET": "x"}, "OIDC_GOOGLE_CLIENT_SECRET_FILE"),
    ({"OIDC_GOOGLE_ISSUER": None}, "OIDC_GOOGLE_ISSUER is missing"),
    ({"OIDC_GOOGLE_ISSUER": "http://accounts.google.com"}, "OIDC_GOOGLE_ISSUER must use https://"),
    ({"OIDC_AUTHENTIK_CLIENT_ID": None}, "OIDC_AUTHENTIK_CLIENT_ID is missing"),
    ({"OIDC_GOOGLE_SCOPES": "email"}, "OIDC_GOOGLE_SCOPES"),
    ({"OIDC_GOOGLE_ISSUER": ISSUER_A}, "same issuer"),
    ({"OIDC_PROVIDERS": "authentik,authentik"}, "twice"),
    ({"OIDC_PROVIDERS": "authentik,default"}, "not a usable name"),
    ({"OIDC_PROVIDERS": "my-idp"}, "not a usable name"),
    ({"OIDC_PROVIDERS": "aa,bb,cc,dd", "OIDC_ISSUER": "https://x.example.org", "OIDC_CLIENT_ID": "x"}, "At most 4"),
    ({"OIDC_GOOGLE_BUTTON_LABEL": "x" * 61}, "BUTTON_LABEL"),
    ({"OIDC_GOOGLE_ALLOWED_DOMAINS": "a;b"}, "ALLOWED_DOMAINS"),
    ({"OIDC_GOOGLE_ALLOW_SIGNUP": "maybe"}, "OIDC_GOOGLE_ALLOW_SIGNUP"),
    ({"PUBLIC_URL": None}, "PUBLIC_URL"),
])
def test_config_refuses_a_wrong_provider(tmp_path, extra, message):
    with pytest.raises(ConfigError, match=message):
        load_settings(base_env(tmp_path, **extra))


def test_config_without_oidc_enabled_names_the_stray_providers(tmp_path):
    s = load_settings(base_env(tmp_path, OIDC_ENABLED=None))
    assert s.oidc.all() == () and any("OIDC_PROVIDERS set without OIDC_ENABLED" in w for w in s.warnings)


# --------------------------------------------------------------------------- #
# OIDC_ONLY
# --------------------------------------------------------------------------- #


def test_config_refuses_oidc_only_without_a_provider(tmp_path):
    with pytest.raises(ConfigError, match="OIDC_ONLY=true needs a sign-in provider"):
        load_settings({"DATA_DIR": str(tmp_path / "d"), "OIDC_ONLY": "true"})
    s = load_settings(base_env(tmp_path, OIDC_ONLY="true"))
    assert s.oidc.only is True and any("OIDC_ONLY=false and restart" in w for w in s.warnings)


def test_start_up_says_why_it_refuses_oidc_only_without_a_provider(tmp_path, foods_json):
    with pytest.raises(ConfigError, match="OIDC_ONLY=true needs a sign-in provider"):
        create_app(make_settings(tmp_path, foods_json, oidc=OidcEnv(only=True)))
    env = {k: v for k, v in os.environ.items() if not k.endswith("_FILE") and not k.startswith("OIDC_")}
    env.update(DATA_DIR=str(tmp_path / "data"), OIDC_ONLY="true", PYTHONPATH=str(REPO))
    proc = subprocess.run([sys.executable, "-c", "import app.main"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1 and "Traceback" not in proc.stderr
    assert "configuration error: OIDC_ONLY=true needs a sign-in provider" in proc.stderr


@pytest.fixture
def only_app(tmp_path, foods_json, authentik, google):
    return make_app(tmp_path, foods_json, authentik, google, only=True)


def link_row(client: TestClient, username: str, issuer: str, sub: str) -> None:
    """A link made before OIDC_ONLY was turned on (in the test, written straight into the database)."""
    with database(client) as conn:
        uid = conn.execute("SELECT id FROM users WHERE username_norm = ?", (username,)).fetchone()[0]
        conn.execute("INSERT INTO oidc_links (user_id, issuer, subject, email, created_at, last_used_at) "
                     "VALUES (?, ?, ?, NULL, '2026-10-01T00:00:00.000000Z', NULL)", (uid, issuer, sub))


def test_oidc_only_refuses_passwords_and_lets_the_provider_in(only_app, authentik):
    with TestClient(only_app, base_url=HTTPS_URL) as c:
        st = c.get("/api/auth/status").json()["oidc"]
        assert st["only"] is True and st["password"] == "off"
        r = c.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 403 and r.json()["oidc_only"] is True and "sign-in provider only" in r.json()["detail"]
        r = c.post("/api/auth/login", json={"username": "nobody", "password": ADMIN_PASSWORD})
        assert r.status_code == 403  # the same answer for a name that does not exist
        link_row(c, ADMIN_USERNAME, ISSUER_A, "a-admin")
        assert sign_in_with_provider(c, authentik, provider_id="authentik", claims={"sub": "a-admin"}).headers["location"] == "/"
        about = c.get("/api/admin/about").json()["oidc"]
        assert about["only"] is True and about["admins_linked"] == 1
        # an invite: no password sign-up, but the provider can make the account
        token = invite_token(c, role="user")
        anon = TestClient(only_app, base_url=HTTPS_URL)
        r = anon.post("/api/auth/register", json={"token": token, "username": "ann", "password": "a long enough password here"})
        assert r.status_code == 403 and r.json()["oidc_only"] is True
        r = anon.post("/api/auth/oidc/invite", params={"provider": "authentik"}, json={"token": token})
        back = come_back(anon, authentik, r.json()["url"], claims={"sub": "ann", "email": "ann@example.org"})
        assert back.headers["location"] == "/" and anon.get("/api/me").json()["username"] == "ann@example.org"


def test_oidc_only_lets_the_test_accounts_keep_their_password(tmp_path, foods_json, authentik, google, pw_file):  # noqa: F811
    """The test accounts' password file comes from tests/test_test_accounts.py (its pw_file fixture, imported above)."""
    application = create_app(make_settings(tmp_path, foods_json, public_url=PUBLIC_URL, oidc=two_env(only=True),
                                           test_account_password_file=pw_file))
    attach(application, authentik, "authentik")
    with TestClient(application, base_url=HTTPS_URL) as c:
        link_row(c, ADMIN_USERNAME, ISSUER_A, "a-admin")
        sign_in_with_provider(c, authentik, provider_id="authentik", claims={"sub": "a-admin"})
        set_setting(c, **{"test_accounts.enabled": True})
        anon = TestClient(application, base_url=HTTPS_URL)
        assert anon.get("/api/auth/status").json()["oidc"]["password"] == "test_accounts"
        r = anon.post("/api/auth/login", json={"username": "tester", "password": TESTER_PHRASE})
        assert r.status_code == 200, r.text
        assert anon.get("/api/me").json()["username"] == "tester"
        r = anon.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 403  # everyone else still needs the provider
        # The sign-in page still hides the password form until a tester asks for it (js/views/auth.js), and passkeys stay.
        assert anon.get("/api/auth/status").json()["passkeys"] is True
