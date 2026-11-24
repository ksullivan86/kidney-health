"""The iPhone app's gateway ``/push/v1/api/<path>`` and ``GET /push/v1/about`` (design note 39 §5; ``app/app_gateway.py``).

Covered: the token kind "The iPhone app, both ways" (``app:sync``), the switch ``push.app_sync`` under ``push.enabled``, old app
tokens never widened, the order of checks (Origin, token, limit, list), no cookie ever read, the allow-list pinned (no re-auth,
admin, token, session, key, import, export or account route, ever), never an admin and never a recent password even if the list
were wrong, the second check on the route the router really chose, the isolation matrix run through the gateway, the AI's rules
unchanged (opt-in, consent per person, lab text only on the local AI, no cloud fallback), the body limit of the ``/api`` route,
``no-store``, the log line, the daily activity row, and ``about``'s answer and its ``account`` key.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

import httpx2
import pytest
from fastapi import Request
from starlette.routing import compile_path

import app.foods as foods_module
from app import app_gateway
from app.app_gateway import ALLOWED, NOT_ON_LIST, Allowed, never_allowed
from app.auth import api_tokens
from app.auth.deps import CurrentUser, require_admin, require_recent_auth
from conftest import DAY, HTTPS_URL, TestClient, add_user, make_settings, sign_in, signed_in_client
from test_api_tokens import audit_rows, make
from test_auth_coverage import _walk
from test_push import bare, make_device

GATEWAY = "/push/v1/api"
ABOUT = "/push/v1/about"
GENERIC = {"detail": api_tokens.DEVICE_DENIED}


def switches(admin: TestClient, push: bool = True, app_sync: bool = True) -> None:
    r = admin.patch("/api/admin/settings", json={"push.enabled": push, "push.app_sync": app_sync})
    assert r.status_code == 200, r.text


def make_sync(client: TestClient, name: str = "My iPhone", **extra: Any) -> dict[str, Any]:
    r = client.post("/api/me/tokens", json={"name": name, "family": "device", "kind": "app_sync", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def call(app: Any, token: str | None, method: str, path: str, *, headers: dict[str, str] | None = None, **kw: Any) -> Any:
    """A request as the iPhone app sends it: the bearer token and nothing else (no cookie, no Origin, no CSRF header)."""
    h = dict(headers or {})
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    return bare(app).request(method, path, headers=h, **kw)


@pytest.fixture
def admin(client: TestClient) -> TestClient:
    switches(client)
    return client


@pytest.fixture
def token(admin: TestClient) -> str:
    return make_sync(admin)["token"]


@pytest.fixture
def secure_admin(https_client: TestClient) -> TestClient:
    """The admin over https, where a second account can be made."""
    switches(https_client)
    return https_client


# --------------------------------------------------------------------------- #
# The token kind and the switch
# --------------------------------------------------------------------------- #


def test_the_switch_is_off_by_default_and_the_new_kind_cannot_be_made_while_it_is_off(client):
    assert client.get("/api/admin/settings").json()["settings"]["push.app_sync"]["value"] is False
    switches(client, push=True, app_sync=False)
    r = client.post("/api/me/tokens", json={"name": "x", "family": "device", "kind": "app_sync"})
    assert r.status_code == 409 and r.json()["detail"] == api_tokens.APP_SYNC_SWITCHED_OFF and r.json()["field"] == "kind"
    listed = client.get("/api/me/tokens", params={"family": "device"}).json()
    assert listed["enabled"] is True and listed["app_sync_enabled"] is False
    assert "app_sync_enabled" not in client.get("/api/me/tokens").json()  # the assistant list does not have it
    # the kinds that only add are unchanged
    assert client.post("/api/me/tokens", json={"name": "y", "family": "device", "kind": "app"}).status_code == 201


def test_the_new_kind_holds_app_sync_and_implies_the_others(admin):
    made = make_sync(admin)
    assert made["token"].startswith("khd_") and made["kind"] == "app_sync"
    assert made["scopes"] == ["body:write", "app:add", "app:sync"]
    assert made["sent"] == {"entries": 0, "foods": 0, "labs": 0, "symptoms": 0, "weights": 0, "readings": 0}
    assert made["pair_url"] is None or made["pair_url"].startswith("https://")
    item = admin.get("/api/me/tokens", params={"family": "device"}).json()
    assert item["app_sync_enabled"] is True and item["tokens"][0]["kind"] == "app_sync"
    assert api_tokens.parse_scopes("app:sync") == ("body:write", "app:add", "app:sync")
    assert api_tokens.parse_scopes("body:write app:add") == ("body:write", "app:add")  # an old app token is never widened
    assert api_tokens.parse_scopes("app:sync assistant:read") == ()  # families never mix
    assert api_tokens.kind_of_scopes("body:write app:add app:sync") == "app_sync"
    assert api_tokens.family_of_scopes("app:sync") == "device"
    created = audit_rows(admin, "api_token.created")[-1]["details"]
    assert created["kind"] == "app_sync" and created["family"] == "device"


def test_the_new_kind_still_adds_rows_at_push_v1_sync(admin, token):
    body = {"labs": [{"client_id": "6f1c2a9e-3b7d-4e8a-9c0f-1d2e3f4a5b6c", "analyte": "potassium", "value": 5, "unit": "mmol/L",
                      "taken_on": DAY}]}
    r = bare(admin.app).post("/push/v1/sync", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["added"]["labs"] == 1


@pytest.mark.parametrize("path", [f"{GATEWAY}/ai/status", ABOUT])
def test_while_either_switch_is_off_the_token_is_the_generic_401_and_nothing_is_looked_up(admin, token, path, monkeypatch):
    for push, app_sync in ((True, False), (False, True)):
        switches(admin, push=push, app_sync=app_sync)
        looked = []
        monkeypatch.setattr(api_tokens, "hash_token", lambda t: looked.append(t) or "0" * 64)
        r = call(admin.app, token, "GET", path)
        monkeypatch.undo()
        assert r.status_code == 401 and r.json() == GENERIC and r.headers["www-authenticate"].startswith("Bearer"), (push, app_sync)
        assert looked == [] and (path == ABOUT or r.headers["cache-control"] == "no-store")
    switches(admin)
    assert call(admin.app, token, "GET", path).status_code in (200, 404)  # 404: the AI is off, as if the route did not exist


def test_the_env_switch_locks_it(tmp_path, foods_json, monkeypatch):
    monkeypatch.setenv("PUSH_APP_SYNC", "true")
    with signed_in_client(make_settings(tmp_path, foods_json)) as c:
        item = c.get("/api/admin/settings").json()["settings"]["push.app_sync"]
        assert item["value"] is True and item["locked_by_env"] == "PUSH_APP_SYNC"


@pytest.mark.parametrize("path", [f"{GATEWAY}/ai/status", ABOUT])
def test_only_a_token_with_app_sync_opens_it(admin, path):
    assistant_on = admin.patch("/api/admin/settings", json={"assistant.enabled": True})
    assert assistant_on.status_code == 200
    old_app = admin.post("/api/me/tokens", json={"name": "old", "family": "device", "kind": "app"}).json()["token"]
    shortcut = make_device(admin)["token"]
    assistant = make(admin, can_log=True)["token"]
    for wrong in (old_app, shortcut, assistant, "khd_" + "A" * 43, "not-a-token"):
        r = call(admin.app, wrong, "GET", path)
        assert r.status_code == 401 and r.json() == GENERIC, wrong[:4]
    assert call(admin.app, None, "GET", path).status_code == 401  # nothing at all
    r = admin.get(path)  # the signed-in admin's cookie and no token
    assert r.status_code == 401 and r.json() == GENERIC


def test_a_revoked_or_expired_token_is_refused_at_once(admin, fake_clock):
    made = make_sync(admin, expires_in_days=30)
    other = make_sync(admin, name="second")
    assert call(admin.app, made["token"], "GET", ABOUT).status_code == 200
    assert admin.delete(f"/api/me/tokens/{other['id']}").status_code == 204
    assert call(admin.app, other["token"], "GET", f"{GATEWAY}/ai/status").status_code == 401
    fake_clock.advance(days=31)
    assert call(admin.app, made["token"], "GET", ABOUT).status_code == 401


# --------------------------------------------------------------------------- #
# The order of checks, the cookie and the browser
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("headers", [{"Origin": "https://localhost"}, {"Origin": "https://evil.example"}, {"Origin": "null"},
                                     {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-origin"}])
def test_any_origin_or_browser_fetch_is_refused_before_the_token_is_read(admin, token, headers, monkeypatch):
    looked = []
    monkeypatch.setattr(api_tokens, "hash_token", lambda t: looked.append(t) or "0" * 64)
    for method in ("GET", "POST"):
        r = call(admin.app, token, method, f"{GATEWAY}/ai/status", headers=headers)
        assert r.status_code == 403 and r.json() == {"detail": "Cross-site request refused"}, (method, headers)
    assert looked == []


def test_the_cookie_is_never_read_and_never_reaches_the_route(secure_admin):
    """Another person's session cookie next to the token changes nothing: the route runs as the token's owner. The route never
    sees the cookie or the Authorization header."""
    admin = secure_admin
    token = make_sync(admin)["token"]
    sam = add_user(admin)
    seen: list[dict[str, str]] = []

    def probe_route(request: Request, user: CurrentUser) -> dict[str, Any]:
        seen.append({k.lower(): v for k, v in request.headers.items()})
        return {"user": user.id, "role": user.role}

    admin.app.add_api_route("/api/zz-probe", probe_route, methods=["GET"], include_in_schema=False)
    admin.app.router.routes.insert(0, admin.app.router.routes.pop())  # before the static files at /
    app_gateway.resolve(admin.app)  # warm the cache, then widen it for this probe only
    allowed = admin.app.state.push_gateway_allowed
    route = next(r for m, p, r in app_gateway.walk_routes(admin.app.routes) if p == "/api/zz-probe")
    admin.app.state.push_gateway_allowed = Allowed(
        (*allowed.patterns, ("GET", "/api/zz-probe", compile_path("/api/zz-probe")[0])), {**allowed.routes, id(route): {"GET"}})
    cookie = "; ".join(f"{k}={v}" for k, v in sam.cookies.items())
    r = call(admin.app, token, "GET", f"{GATEWAY}/zz-probe", headers={"Cookie": cookie})
    assert r.status_code == 200 and r.json() == {"user": 1, "role": "user"}, r.text  # the token's owner, never an admin
    assert "cookie" not in seen[0] and "authorization" not in seen[0]


def test_a_route_not_on_the_list_is_404_after_the_token_check(admin, token):
    for method, path in (("GET", "/me"), ("GET", "/me/tokens"), ("POST", "/me/tokens"), ("GET", "/admin/users"),
                         ("GET", "/log"), ("DELETE", "/me"), ("GET", "/me/export.zip"), ("POST", "/me/import"),
                         ("GET", "/ai/status/extra"), ("HEAD", "/ai/status"), ("PUT", "/ai/status"), ("GET", "/nothing-here"),
                         ("GET", ""), ("GET", "/")):
        r = call(admin.app, token, method, f"{GATEWAY}{path}")
        assert r.status_code == 404, (method, path, r.status_code)
        if method != "HEAD":
            assert r.json() == {"detail": NOT_ON_LIST}, (method, path)
        assert r.headers["cache-control"] == "no-store"
    assert call(admin.app, None, "GET", f"{GATEWAY}/me").status_code == 401  # a stranger learns nothing about the list


def test_the_second_check_refuses_a_route_the_list_did_not_let_in(admin, token):
    """If the path check and the router ever disagreed, the route the router chose is checked again by identity."""
    app_gateway.resolve(admin.app)
    allowed = admin.app.state.push_gateway_allowed
    admin.app.state.push_gateway_allowed = Allowed((*allowed.patterns, ("GET", "/api/log", compile_path("/api/log")[0])), allowed.routes)
    r = call(admin.app, token, "GET", f"{GATEWAY}/log", params={"date": DAY})
    assert r.status_code == 404 and r.json() == {"detail": NOT_ON_LIST}


def test_even_a_wrong_list_could_not_make_an_admin_or_skip_the_password(admin, token):
    """Defence in depth: were an admin route or a route that needs a recent password ever put on the list, the gateway's caller is
    still not an admin and has entered no password."""
    app_gateway.resolve(admin.app)
    allowed = admin.app.state.push_gateway_allowed
    extra = {("GET", "/api/admin/users"), ("PUT", "/api/me/ai/provider"), ("POST", "/api/me/tokens")}
    routes = dict(allowed.routes)
    for m, p, route in app_gateway.walk_routes(admin.app.routes):
        if (m, p) in extra:
            routes.setdefault(id(route), set()).add(m)
    admin.app.state.push_gateway_allowed = Allowed((*allowed.patterns, *((m, p, compile_path(p)[0]) for m, p in sorted(extra))), routes)
    r = call(admin.app, token, "GET", f"{GATEWAY}/admin/users")
    assert r.status_code == 403 and r.json()["detail"] == "Admins only"
    r = call(admin.app, token, "PUT", f"{GATEWAY}/me/ai/provider", json={"preset": "openai", "api_key": "sk-test-0123456789abcdef"})
    assert r.status_code == 403 and r.json()["reauth_required"] is True
    r = call(admin.app, token, "POST", f"{GATEWAY}/me/tokens", json={"name": "more", "family": "device", "kind": "app_sync"})
    assert r.status_code == 403 and r.json()["reauth_required"] is True


# --------------------------------------------------------------------------- #
# The allow-list
# --------------------------------------------------------------------------- #


def _dependency_calls(route: Any) -> set[Any]:
    seen: set[Any] = set()
    stack = [route.dependant]
    while stack:
        node = stack.pop()
        for sub in node.dependencies:
            seen.add(sub.call)
            stack.append(sub)
    return seen


def test_the_allow_list_is_pinned(anon_client):
    """Every listed route exists, needs a signed-in person, needs no recent password, is no admin route, and is none of the routes
    that must never be on it. The list itself is pinned, so growing it is a reviewed change."""
    assert ALLOWED == {
        ("GET", "/api/ai/status"), ("POST", "/api/ai/consent"), ("DELETE", "/api/ai/consent/{provider_id}"),
        ("POST", "/api/ai/next-meal"), ("POST", "/api/ai/parse-meal"), ("POST", "/api/ai/recipes"), ("POST", "/api/ai/chat"),
        ("POST", "/api/ai/transcribe"), ("POST", "/api/vision/label"), ("POST", "/api/vision/plate"),
        ("POST", "/api/ai/read-lab-report"), ("POST", "/api/ai/read-lab-report-text"),
        ("GET", "/api/foods/usda/search"), ("POST", "/api/foods/usda/import"), ("POST", "/api/foods/barcode"),
        ("PATCH", "/api/me/settings"), ("PATCH", "/api/me/ai"),
    }
    assert app_gateway.BODY_KEYS == {("PATCH", "/api/me/settings"): {"food.off_consent"}, ("PATCH", "/api/me/ai"): {"opt_in"}}
    from app.auth.deps import current_user

    by_op = {(m, p): r for m, p, r in app_gateway.walk_routes(anon_client.app.routes)}
    for method, path in sorted(ALLOWED):
        assert (method, path) in by_op, (method, path)
        assert not never_allowed(method, path), (method, path)
        calls = _dependency_calls(by_op[(method, path)])
        assert current_user in calls, (method, path)
        assert require_recent_auth not in calls and require_admin not in calls, (method, path)
    for method, path in (("POST", "/api/auth/reauth"), ("GET", "/api/admin/users"), ("POST", "/api/me/tokens"),
                         ("GET", "/api/me/sessions"), ("PUT", "/api/me/keys/{provider}"), ("PUT", "/api/me/ai/provider"),
                         ("POST", "/api/me/import"), ("GET", "/api/me/export.zip"), ("DELETE", "/api/me"),
                         ("POST", "/api/me/shares"), ("POST", "/api/me/password")):
        assert never_allowed(method, path), (method, path)
    # every route that needs a recent password or an admin is in a never-allowed place
    for (method, path), route in by_op.items():
        if not path.startswith("/api/"):
            continue
        calls = _dependency_calls(route)
        if require_recent_auth in calls or require_admin in calls:
            assert never_allowed(method, path) or path.startswith("/api/admin/"), (method, path)


def test_two_settings_and_only_those_keys(admin, token):
    """The phone may set the person's Open Food Facts consent and AI opt-in, and nothing else of the settings."""
    r = call(admin.app, token, "PATCH", f"{GATEWAY}/me/settings", json={"food.off_consent": True})
    assert r.status_code == 200, r.text
    assert admin.get("/api/me/settings").json()["settings"]["food.off_consent"]["value"] is True
    for body in ({"food.off_consent": True, "ui.theme": "dark"}, {"ui.theme": "dark"}, {}, [], "x"):
        r = call(admin.app, token, "PATCH", f"{GATEWAY}/me/settings", json=body)
        assert r.status_code == 403 and r.json()["detail"] == "From the iPhone app this can change only: food.off_consent.", body
    r = call(admin.app, token, "PATCH", f"{GATEWAY}/me/settings", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 403
    assert admin.get("/api/me/settings").json()["settings"]["ui.theme"]["value"] == "system"
    r = call(admin.app, token, "PATCH", f"{GATEWAY}/me/ai", json={"opt_in": True, "trust": "high"})
    assert r.status_code == 403
    r = call(admin.app, token, "PATCH", f"{GATEWAY}/me/ai", json={"opt_in": True})
    assert r.status_code in (200, 404), r.text  # 404 while the AI is off, as for every AI route
    assert call(admin.app, token, "PUT", f"{GATEWAY}/me/settings", json={"food.off_consent": True}).status_code == 404  # PATCH only


def test_about_names_the_list(admin, token):
    about = call(admin.app, token, "GET", ABOUT).json()
    assert {(r["method"], r["path"]) for r in about["gateway"]} == ALLOWED


# --------------------------------------------------------------------------- #
# Limits, headers, the log and the activity row
# --------------------------------------------------------------------------- #


def test_600_requests_an_hour_per_token_shared_with_about(admin, monkeypatch):
    from app.auth import ratelimit

    monkeypatch.setitem(ratelimit.LIMITS, app_gateway.RATE_LIMIT, ratelimit.Limit(app_gateway.RATE_LIMIT, 3, 3600.0, "Too many"))
    assert ratelimit.LIMITS[app_gateway.RATE_LIMIT].max_requests == 3
    first, second = make_sync(admin)["token"], make_sync(admin, name="other")["token"]
    assert call(admin.app, first, "GET", ABOUT).status_code == 200
    assert call(admin.app, first, "GET", f"{GATEWAY}/ai/status").status_code == 404  # counted (the AI is off here)
    assert call(admin.app, first, "GET", f"{GATEWAY}/me").status_code == 404  # counted too: the limit comes before the list
    r = call(admin.app, first, "GET", ABOUT)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert call(admin.app, second, "GET", ABOUT).status_code == 200  # per token


def test_the_registered_limit_is_600_an_hour():
    from app.auth import ratelimit

    limit = ratelimit.LIMITS[app_gateway.RATE_LIMIT]
    assert (limit.max_requests, limit.window_s) == (600, 3600.0)


def test_answers_are_no_store_and_the_log_holds_no_value(admin, token, caplog):
    caplog.set_level(logging.INFO, logger="kidney_health.push")
    r = call(admin.app, token, "GET", f"{GATEWAY}/foods/usda/search", params={"q": "secret-stew-query"})
    assert r.headers["cache-control"] == "no-store"
    lines = [rec.getMessage() for rec in caplog.records if rec.getMessage().startswith("gateway:")]
    assert lines == [f"gateway: token {_token_id(admin)} GET /api/foods/usda/search -> {r.status_code}"]
    assert "secret-stew-query" not in caplog.text


def _token_id(client: TestClient) -> int:
    return client.get("/api/me/tokens", params={"family": "device"}).json()["tokens"][0]["id"]


def test_one_activity_row_a_day_per_token(admin, token, fake_clock):
    for _ in range(3):
        call(admin.app, token, "GET", f"{GATEWAY}/ai/status")
    rows = audit_rows(admin, "app.server_used")
    assert len(rows) == 1 and rows[0]["details"] == {"via": "My iPhone"} and rows[0]["target_type"] == "api_token"
    assert call(admin.app, token, "GET", ABOUT).status_code == 200  # about is not the gateway: no row
    actions = [e["action"] for e in admin.get("/api/me/activity").json()["events"]]
    assert "app.server_used" in actions


def test_the_body_limit_is_the_api_routes_own(tmp_path, foods_json):
    """The photo routes take up to MAX_IMAGE_BYTES through the gateway too; others keep MAX_BODY_BYTES."""
    settings = make_settings(tmp_path, foods_json, max_body_bytes=4096, max_image_bytes=64 * 1024)
    with signed_in_client(settings, base_url=HTTPS_URL) as c:
        switches(c)
        token = make_sync(c)["token"]
        big = b"x" * 10_000
        r = call(c.app, token, "POST", f"{GATEWAY}/ai/parse-meal", content=big, headers={"Content-Type": "application/json"})
        assert r.status_code == 413
        r = call(c.app, token, "POST", f"{GATEWAY}/vision/label", content=big, headers={"Content-Type": "image/jpeg"})
        assert r.status_code != 413  # past the size check (the AI is off: 404)
        r = call(c.app, token, "POST", f"{GATEWAY}/vision/label", content=b"x" * 70_000, headers={"Content-Type": "image/jpeg"})
        assert r.status_code == 413


# --------------------------------------------------------------------------- #
# GET /push/v1/about
# --------------------------------------------------------------------------- #


def test_about_answers_what_this_server_offers_this_person(admin, token):
    r = call(admin.app, token, "GET", ABOUT)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    about = r.json()
    assert set(about) == {"account", "api_version", "app_version", "sync", "gateway", "ai", "services", "capabilities", "features"}
    assert about["features"] == {"usda_search": about["services"]["usda_search"], "barcode": about["services"]["barcode"], "ai": False,
                                 "changes": True}
    assert re.fullmatch(r"[0-9a-f]{32}", about["account"])
    assert about["sync"] == {"gateway": True, "changes": app_gateway.CHANGE_FEED}
    assert about["ai"] == {"enabled": False, "available": False, "routes": {}}
    assert set(about["services"]) == {"usda_search", "barcode", "barcode_off", "barcode_usda", "recipe_import", "instacart", "list_sync"}
    assert about["capabilities"]["push"] is True
    assert about["api_version"] == admin.get("/api/meta").json()["api_version"]


def test_the_account_key_is_stable_per_person_and_names_no_one(secure_admin):
    admin = secure_admin
    sam = add_user(admin)
    first, second = make_sync(admin)["token"], make_sync(admin, name="iPad")["token"]
    sams = make_sync(sam)["token"]
    a1 = call(admin.app, first, "GET", ABOUT).json()["account"]
    a2 = call(admin.app, second, "GET", ABOUT).json()["account"]
    s1 = call(admin.app, sams, "GET", ABOUT).json()["account"]
    assert a1 == a2 and a1 != s1
    assert "1" != a1 and "admin" not in a1 and "sam" not in s1


def test_about_takes_get_only(admin, token):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = call(admin.app, token, method, ABOUT)
        assert r.status_code == 405 and r.headers["allow"] == "GET"


def test_about_follows_the_origin_rule_of_push_v1(admin, token):
    r = call(admin.app, token, "GET", ABOUT, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# The isolation matrix through the gateway
# --------------------------------------------------------------------------- #

CUSTOM = {"name": "Grandma's secret stew", "category": "Family recipes", "serving_desc": "1 bowl", "serving_g": 300,
          "nutrients": {"potassium_mg": 900, "sodium_mg": 1200}}
USDA_RECORD = {"fdcId": 424242, "description": "Shared USDA oats", "dataType": "SR Legacy",
               "foodCategory": {"description": "Breakfast Cereals"}, "foodNutrients": [{"nutrient": {"number": "306"}, "amount": 100}]}
# The isolation matrix's id-bearing routes (tests/test_isolation.py), opened to the gateway for this test only: the gateway runs the
# same route, so B's token gets 404 on every one of A's rows exactly as B's session does.
MATRIX = {("GET", "/api/foods/{food_id}"), ("PUT", "/api/foods/{food_id}"), ("DELETE", "/api/foods/{food_id}"),
          ("POST", "/api/foods/{food_id}/copy"), ("PUT", "/api/log/{entry_id}"), ("DELETE", "/api/log/{entry_id}"),
          ("GET", "/api/meals/{meal_id}"), ("PUT", "/api/meals/{meal_id}"), ("DELETE", "/api/meals/{meal_id}"),
          ("POST", "/api/meals/{meal_id}/apply"), ("POST", "/api/log"), ("POST", "/api/meals"), ("GET", "/api/log"),
          ("GET", "/api/foods"), ("GET", "/api/meals")}


@pytest.fixture
def pair(tmp_path, foods_json, monkeypatch) -> Iterator[tuple[TestClient, TestClient, str, dict[str, Any]]]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/fdc/v1/food/424242":
            return httpx2.Response(200, json=USDA_RECORD)
        return httpx2.Response(404, json={})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(app_gateway, "ALLOWED", ALLOWED | MATRIX)
    settings = make_settings(tmp_path, foods_json, usda_api_key="SHARED-ENV-KEY-0123456789")
    with signed_in_client(settings, base_url=HTTPS_URL) as a:
        switches(a)
        b = add_user(a, "sam")
        b_token = make_sync(b)["token"]
        banana = a.get("/api/foods", params={"q": "banana"}).json()["foods"][0]
        food = a.post("/api/foods", json=CUSTOM).json()
        entry = a.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"], "note": "A's note"}).json()
        meal = a.post("/api/meals", json={"name": "A's usual", "items": [{"food_id": food["id"], "servings": 1}]}).json()
        usda = a.post("/api/foods/usda/import", json={"fdc_id": 424242}).json()
        yield a, b, b_token, {"food": food, "entry": entry, "meal": meal, "usda": usda, "banana": banana}


def test_b_gets_404_on_every_id_bearing_route_of_a_through_the_gateway(pair):
    a, b, token, t = pair
    fid, eid, mid = t["food"]["id"], t["entry"]["id"], t["meal"]["id"]
    food_body = {"name": "x", "serving_desc": "1", "serving_g": 1, "nutrients": {}}
    checks = [
        ("GET", f"/foods/{fid}", None), ("PUT", f"/foods/{fid}", food_body), ("DELETE", f"/foods/{fid}", None),
        ("POST", f"/foods/{fid}/copy", None), ("PUT", f"/log/{eid}", {"servings": 2}), ("DELETE", f"/log/{eid}", None),
        ("GET", f"/meals/{mid}", None),
        ("PUT", f"/meals/{mid}", {"name": "mine now", "items": [{"food_id": t["banana"]["id"], "servings": 1}]}),
        ("DELETE", f"/meals/{mid}", None), ("POST", f"/meals/{mid}/apply", {"date": DAY, "meal": "lunch"}),
        ("POST", "/log", {"date": DAY, "meal": "lunch", "food_id": fid}),
        ("POST", "/meals", {"name": "x", "items": [{"food_id": fid, "servings": 1}]}),
        ("GET", f"/foods/{t['usda']['id']}", None),
        ("POST", "/log", {"date": DAY, "meal": "lunch", "food_id": t["usda"]["id"]}),
    ]
    for method, path, body in checks:
        r = call(a.app, token, method, f"{GATEWAY}{path}", json=body)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    assert a.get(f"/api/foods/{fid}").json()["name"] == CUSTOM["name"]
    assert a.get(f"/api/meals/{mid}").json()["name"] == "A's usual"
    assert [e["id"] for e in a.get("/api/log", params={"date": DAY}).json()["entries"]] == [eid]
    # lists hold only B's rows
    assert call(a.app, token, "GET", f"{GATEWAY}/log", params={"date": DAY}).json()["entries"] == []
    assert call(a.app, token, "GET", f"{GATEWAY}/meals").json() == {"meals": []}
    assert call(a.app, token, "GET", f"{GATEWAY}/foods", params={"q": "secret stew"}).json()["foods"] == []
    # and what B adds through the gateway is B's
    made = call(a.app, token, "POST", f"{GATEWAY}/log", json={"date": DAY, "meal": "lunch", "food_id": t["banana"]["id"]})
    assert made.status_code in (200, 201), made.text
    assert [e["id"] for e in b.get("/api/log", params={"date": DAY}).json()["entries"]] == [made.json()["id"]]
    assert [e["id"] for e in a.get("/api/log", params={"date": DAY}).json()["entries"]] == [eid]


def test_b_imports_the_shared_usda_food_through_the_gateway_without_seeing_a_link(pair):
    a, b, token, t = pair
    r = call(a.app, token, "POST", f"{GATEWAY}/foods/usda/import", json={"fdc_id": 424242})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == t["usda"]["id"]  # the one shared row, now linked to B too
    assert b.get(f"/api/foods/{t['usda']['id']}").status_code == 200
    assert a.get(f"/api/foods/{t['usda']['id']}").status_code == 200


# --------------------------------------------------------------------------- #
# The AI through the gateway: its rules are the route's, unchanged
# --------------------------------------------------------------------------- #


@pytest.fixture
def ai_rig(tmp_path, foods_json):
    from test_ai_routing import Rig, add_local, cloud_id, route, routed_settings, turn_on
    from app.main import create_app

    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        rig = Rig(c, add_local(c, vision_model=None, context_tokens=32_768), cloud_id(c))
        assert route(c, local_provider=rig.local, cloud_provider=rig.cloud).status_code == 200
        switches(c)
        yield rig


def _lab_text(app: Any, token: str, local: Any, cloud: Any) -> Any:
    from ai_support import attach_routed
    from test_lab_text import PAGE

    with attach_routed(app, local=local, cloud=cloud):
        return call(app, token, "POST", f"{GATEWAY}/ai/read-lab-report-text", json={"text": PAGE, "page": 1})


def test_lab_text_runs_on_the_local_ai_only_with_opt_in_and_consent_per_person(ai_rig):
    from ai_support import chat
    from test_ai_routing import fakes, ready
    from test_lab_text import GOOD

    c = ai_rig.client
    token = make_sync(c)["token"]
    local, cloud = fakes(chat(GOOD))
    r = _lab_text(c.app, token, local, cloud)
    assert r.status_code == 503 and r.json()["reason"] == "not_opted_in"  # the person's own opt-in, as on the web
    ready(c, {ai_rig.local: ("text",)})
    local, cloud = fakes(chat(GOOD))
    r = _lab_text(c.app, token, local, cloud)
    assert r.status_code == 409 and r.json()["consent_required"] is True and r.json()["consent"]["purpose"] == "labs"
    assert local.requests == [] and cloud.requests == []
    # the consent is given through the gateway, as the phone shows the server's sheet
    r = call(c.app, token, "POST", f"{GATEWAY}/ai/consent", json={"provider_id": ai_rig.local, "purpose": "labs"})
    assert r.status_code == 200, r.text
    local, cloud = fakes(chat(GOOD))
    r = _lab_text(c.app, token, local, cloud)
    assert r.status_code == 200, r.text
    assert local.calls == 1 and cloud.requests == []
    assert r.json()["provider"]["id"] == ai_rig.local
    # nothing of the text or the answer is kept in the AI activity row
    events = c.get("/api/ai/audit").json()["events"]
    assert events and "Potassium 5.4" not in json.dumps(events)
    # another person's token has none of this person's consent
    sam = add_user(c)
    sams = make_sync(sam)["token"]
    ready(sam, {})
    local, cloud = fakes(chat(GOOD))
    r = _lab_text(c.app, sams, local, cloud)
    assert r.status_code == 409 and local.requests == [] and cloud.requests == []


def test_lab_text_never_falls_back_to_the_cloud_through_the_gateway(tmp_path, foods_json):
    from ai_support import chat
    from test_ai_routing import fakes, ready, routed_settings, turn_on
    from test_lab_text import GOOD
    from app.main import create_app

    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        ready(c, {})
        switches(c)
        token = make_sync(c)["token"]
        local, cloud = fakes(chat(GOOD), cloud_answers=(chat(GOOD),))
        r = _lab_text(c.app, token, local, cloud)
        assert r.status_code == 503 and r.json()["reason"] == "no_local_provider", r.text
        assert cloud.requests == [] and local.requests == []
        about = call(c.app, token, "GET", ABOUT).json()
        assert about["ai"]["enabled"] is True and about["ai"]["routes"]["labs"]["available"] is False


def test_about_shows_the_same_ai_routes_as_the_status(ai_rig):
    from test_ai_routing import ready

    c = ai_rig.client
    ready(c, {ai_rig.local: ("text", "labs")})
    token = make_sync(c)["token"]
    about = call(c.app, token, "GET", ABOUT).json()
    status = call(c.app, token, "GET", f"{GATEWAY}/ai/status").json()
    assert about["ai"]["routes"] == status["routes"] == c.get("/api/ai/status").json()["routes"]
    assert about["ai"]["available"] is status["available"] is True


def test_the_gateway_reads_no_cookie_even_when_the_ai_is_on(ai_rig):
    c = ai_rig.client
    r = bare(c.app).get(f"{GATEWAY}/ai/status", headers={"Cookie": "; ".join(f"{k}={v}" for k, v in c.cookies.items())})
    assert r.status_code == 401 and r.json() == GENERIC


def test_the_bearer_paths_and_the_document_agree():
    from app import openapi_doc, security

    assert "/push/v1/about" in security.BEARER_PATHS
    assert openapi_doc.BEARER_OPERATIONS[("get", "/push/v1/about")] == openapi_doc.DEVICE_TOKEN
    assert security.is_gateway_path("/push/v1/api/ai/status") and security.is_gateway_path("/push/v1/api")
    assert not security.is_gateway_path("/push/v1/apix") and not security.is_gateway_path("/api/ai/status")
    assert security.gateway_api_path("/push/v1/api/ai/status") == "/api/ai/status"


def test_walk_finds_the_same_routes_as_the_coverage_walk(anon_client):
    ours = {(m.lower(), p) for m, p, _ in app_gateway.walk_routes(anon_client.app.routes)}
    theirs = {(m, p) for m, p, _ in _walk(anon_client.app.routes)}
    assert ours == theirs
