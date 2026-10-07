"""``/api/ai/*``, ``/api/me/ai`` and ``/api/admin/ai-providers`` (note 04 R3, R4, R9, R11 "routes"; §9 A1,
A5–A8): AI off → 404, consent, dry run == the sent body, quotas and limits, isolation between people,
write-only keys, ``AUTH_MODE=none``, the env provider, export and deletion, retention. No network."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, attach, chat
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from app.ai import config as K
from app.ai import routes as ai_routes
from app.config import AiEnv, ConfigError, Settings, load_settings
from app.main import create_app

DAY = "2026-10-05"
OPENAI_KEY = "sk-env-0123456789abcdefghijklmn"
OWN_KEY = "sk-own-ZYXWVUTSRQPONMLKJIHGFEDC9xQz"
TARGETS = {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "carbs_per_meal_g": 60, "protein_g": {"min": 42, "max": 56}}
IDEAS = {"status": "ok", "refusal": "none", "ideas": []}


def ai_settings(tmp_path, foods_json, **ai: Any) -> Settings:
    env = {"provider": "openai", "api_key": OPENAI_KEY, "model": "gpt-6-luna", "vision_model": "gpt-6-luna", **ai}
    return make_settings(tmp_path, foods_json, ai=AiEnv(**env))


def enable(client: TestClient, **extra: Any) -> None:
    r = client.patch("/api/admin/settings", json={"ai.enabled": True, **extra})
    assert r.status_code == 200, r.text


def ready(client: TestClient, *, consent: bool = True) -> int:
    """Targets set, opted in, consent given; returns the provider id."""
    assert client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    assert client.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    status = client.get("/api/ai/status").json()
    pid = status["provider"]["id"]
    if consent:
        for purpose in ("text", "photos"):
            r = client.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose})
            assert r.status_code == 200, r.text
    return pid


@pytest.fixture
def ai_client(tmp_path, foods_json) -> Iterator[TestClient]:
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        yield c


def ideas_answer() -> dict[str, Any]:
    return chat(IDEAS)


# --------------------------------------------------------------------------- #
# AI off → 404; anonymous → 401
# --------------------------------------------------------------------------- #

AI_ROUTES = [("get", "/api/ai/status"), ("post", "/api/ai/next-meal"), ("post", "/api/ai/parse-meal"), ("post", "/api/ai/consent"),
             ("delete", "/api/ai/consent/1"), ("get", "/api/ai/audit"), ("delete", "/api/ai/audit"),
             ("post", "/api/vision/label"), ("post", "/api/vision/plate")]


@pytest.mark.parametrize("method, path", AI_ROUTES)
def test_ai_off_answers_404_like_an_unregistered_route(client, method, path):
    r = client.request(method.upper(), path, json={})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("method, path", AI_ROUTES)
def test_anonymous_callers_get_401_first(anon_client, method, path):
    assert anon_client.request(method.upper(), path, json={}).status_code == 401


def test_ai_off_sends_nothing_and_settings_still_answer(client):
    me = client.get("/api/me/ai").json()
    assert me["enabled"] is False and me["settings"]["opt_in"] is False and me["own"] is None
    assert client.post("/api/me/ai/probe").status_code == 404


def test_a_configured_provider_is_never_contacted_while_ai_is_off(tmp_path, foods_json, monkeypatch):
    """AI is off by default (contract item 8's sibling, note 04 §9): with an env provider configured but
    ``ai.enabled`` left at its default, start-up and every AI, photo and guidance route send nothing: no
    address of the provider is even looked up."""
    import socket

    from app.ai import transport

    looked_up: list[str] = []

    def no_lookup(host, *args, **kwargs):
        looked_up.append(str(host))
        raise socket.gaierror("no lookups in this test")

    monkeypatch.setattr(transport.socket, "getaddrinfo", no_lookup)
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.get("/api/admin/settings").json()["settings"]["ai.enabled"]["value"] is False
        assert c.put("/api/profile", json={"targets": TARGETS}).status_code == 200
        assert c.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
        for method, path in AI_ROUTES:
            assert c.request(method.upper(), path, json={"meal": "dinner"}).status_code == 404, path
        assert c.post("/api/me/ai/probe").status_code == 404
        assert c.get("/api/me/ai").json()["enabled"] is False
        fits = c.get("/api/guidance/next-meal", params={"meal": "dinner", "date": DAY}).json()
        assert fits["status"] == "ok" and fits["ai"]["available"] is False
    assert looked_up == []


def test_switching_ai_on_needs_no_restart(client):
    assert client.get("/api/ai/status").status_code == 404
    enable(client)
    assert client.get("/api/ai/status").status_code == 200
    client.patch("/api/admin/settings", json={"ai.enabled": False})
    assert client.get("/api/ai/status").status_code == 404


# --------------------------------------------------------------------------- #
# Status, opt-in, consent, dry run
# --------------------------------------------------------------------------- #


def test_status_needs_opt_in_then_consent(ai_client):
    status = ai_client.get("/api/ai/status").json()
    assert status["available"] is False and status["reason"] == "not_opted_in"
    assert status["provider"]["host"] == "api.openai.com" and "30 days" in status["provider"]["policy"]
    assert ai_client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 503 and r.json()["reason"] == "not_opted_in"
    ai_client.patch("/api/me/ai", json={"opt_in": True})
    with attach(ai_client.app, FakeProvider([ideas_answer()])) as provider:
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 409 and r.json()["consent_required"] is True and provider.calls == 0
        consent = r.json()["consent"]
        assert consent["host"] == "api.openai.com" and consent["purpose"] == "text" and consent["policy_version"]
        assert ai_client.post("/api/ai/consent", json={"provider_id": consent["provider_id"] + 99, "purpose": "text"}).status_code == 409
        assert ai_client.post("/api/ai/consent", json={"provider_id": consent["provider_id"], "purpose": "text"}).status_code == 200
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 200 and provider.calls == 1
    status = ai_client.get("/api/ai/status").json()
    assert status["available"] and status["consent"]["text"]["host"] == "api.openai.com" and status["consent"]["photos"] is None
    assert ai_client.delete(f"/api/ai/consent/{consent['provider_id']}").status_code == 204
    assert ai_client.delete(f"/api/ai/consent/{consent['provider_id']}").status_code == 404


def test_dry_run_is_exactly_the_sent_body_and_sends_nothing(ai_client):
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([ideas_answer()])) as provider:
        dry = ai_client.post("/api/ai/next-meal?dry_run=true", json={"meal": "dinner", "date": DAY}).json()
        assert provider.calls == 0 and dry["dry_run"] is True
        assert dry["destination"] == "https://api.openai.com/v1/chat/completions"
        assert dry["headers"]["Authorization"] == "Bearer [your key, not shown]"
        assert OPENAI_KEY not in json.dumps(dry)
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert provider.bodies()[0] == dry["body"]
        assert provider.chat_requests[0].headers["Authorization"] == f"Bearer {OPENAI_KEY}"
    # nothing counted for the dry run, one call for the real one
    assert ai_client.get("/api/me/ai").json()["remaining_today"] == 29


def test_parse_meal_dry_run_and_prefilter(ai_client):
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([])) as provider:
        dry = ai_client.post("/api/ai/parse-meal?dry_run=true", json={"text": "2 eggs and toast"}).json()
        assert "2 eggs and toast" in dry["body"]["messages"][1]["content"]
        low = ai_client.post("/api/ai/parse-meal", json={"text": "shaky, glucose 58"}).json()
        assert low["status"] == "treating_a_low" and low["ai_called"] is False and provider.calls == 0
        assert ai_client.post("/api/ai/parse-meal", json={"text": "x" * 301}).status_code == 400


def test_parse_meal_matches_foods_with_servings(ai_client):
    ready(ai_client)
    answer = chat({"status": "ok", "items": [{"text": "an apple", "search": "apple", "amount": 1, "unit": "serving"},
                                             {"text": "100 g banana", "search": "banana", "amount": 100, "unit": "g"},
                                             {"text": "a cup of water", "search": "water", "amount": 1, "unit": "cup"}]})
    with attach(ai_client.app, FakeProvider([answer])):
        result = ai_client.post("/api/ai/parse-meal", json={"text": "an apple, 100 g banana and a cup of water"}).json()
    assert result["status"] == "ok" and len(result["items"]) == 3
    apple, banana, water = result["items"]
    assert apple["matches"][0]["food"]["name"] == "Apple, raw, with skin" and apple["matches"][0]["servings"] == 1
    assert banana["matches"][0]["servings"] == 0.75  # 100 g of a 118 g serving, to the nearest quarter
    assert water["matches"][0]["servings"] == 1.0  # "1 cup (240 g)"
    assert "warnings" in apple["matches"][0]["food"]


def test_upstream_errors_degrade_to_the_rule_result(ai_client):
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([{"status": 401, "body": {"error": {"message": "bad key sk-xyz"}}}])):
        result = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).json()
    assert result["status"] == "error" and result["reason"] == "http_401" and "fallback" in result
    assert "bad key" not in json.dumps(result)


def test_disabled_guidance_and_missing_targets(ai_client):
    ai_client.patch("/api/me/ai", json={"opt_in": True})
    r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.json()["status"] == "no_targets"
    ai_client.patch("/api/admin/settings", json={"guidance.enabled": False})
    assert ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).json()["status"] == "disabled"


def test_swap_mode_needs_one_target_and_refuses_low_treatments(ai_client):
    ready(ai_client)
    assert ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "mode": "swap"}).status_code == 400
    assert ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "mode": "swap", "entry_id": 999}).status_code == 404
    assert ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "mode": "swap", "food_id": 9999, "servings": 1}).status_code == 404
    foods = ai_client.get("/api/foods", params={"q": "Glucose"}).json()["foods"]
    r = ai_client.post("/api/ai/next-meal", json={"meal": "snack", "mode": "swap", "food_id": foods[0]["id"], "servings": 1, "date": DAY})
    assert r.json()["status"] == "treating_a_low" and r.json()["ai_called"] is False


# --------------------------------------------------------------------------- #
# Quotas and limits
# --------------------------------------------------------------------------- #


def test_shared_daily_limit(ai_client):
    enable(ai_client, **{"ai.shared_daily_limit": 2})
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([ideas_answer(), ideas_answer(), ideas_answer()])) as provider:
        for _ in range(2):
            assert ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).status_code == 200
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 429 and r.json()["reason"] == "quota_exhausted" and int(r.headers["Retry-After"]) >= 60
        assert provider.calls == 2
    assert ai_client.get("/api/ai/status").json()["remaining_today"] == 0


def test_one_call_per_person_and_server_concurrency(ai_client):
    ready(ai_client)
    gate = ai_client.app.state.ai.gate
    gate.enter(1)  # the admin's own call is still running
    try:
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 429 and r.json()["reason"] == "busy_person" and r.headers["Retry-After"] == "5"
    finally:
        gate.leave(1)
    gate.enter(101)
    gate.enter(102)  # two other people fill ai.max_concurrency = 2
    try:
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 429 and r.json()["reason"] == "busy_server"
    finally:
        gate.leave(101)
        gate.leave(102)
    assert ai_client.get("/api/me/ai").json()["remaining_today"] == 30  # refused calls cost nothing


# --------------------------------------------------------------------------- #
# Isolation (two people)
# --------------------------------------------------------------------------- #


@pytest.fixture
def ai_two(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as admin:
        sign_in(admin)
        enable(admin)
        yield admin, add_user(admin)


def test_ai_activity_consent_and_providers_are_per_person(ai_two):
    admin, sam = ai_two
    ready(admin)
    with attach(admin.app, FakeProvider([ideas_answer()])):
        admin.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    events = admin.get("/api/ai/audit").json()["events"]
    assert len(events) == 1 and events[0]["destination_host"] == "api.openai.com" and events[0]["request_json"]["model"] == "gpt-6-luna"
    assert sam.get("/api/ai/audit").json()["events"] == []
    assert sam.get("/api/ai/status").json()["consent"]["text"] is None  # admin's consent is not Sam's
    assert sam.delete(f"/api/ai/consent/{events[0]['provider_id']}").status_code == 404
    sam.patch("/api/me/ai", json={"opt_in": True, "preferences": "no fish"})
    assert admin.get("/api/me/ai").json()["settings"]["preferences"] == ""
    assert sam.delete("/api/ai/audit").status_code == 204
    assert len(admin.get("/api/ai/audit").json()["events"]) == 1  # Sam deleting his history leaves the admin's
    assert admin.delete("/api/ai/audit").status_code == 204 and admin.get("/api/ai/audit").json()["events"] == []
    usage = admin.get("/api/admin/ai-usage").json()["usage"]
    assert usage and usage[0]["username"] == "admin" and "request_json" not in usage[0]  # counts only


def test_can_use_shared_false_means_no_shared_ai(ai_two):
    admin, sam = ai_two
    users = admin.get("/api/admin/users").json()["users"]
    sam_id = next(u["id"] for u in users if u["username"] == "sam")
    assert admin.patch(f"/api/admin/users/{sam_id}", json={"can_use_shared": False}).status_code == 200
    sam.patch("/api/me/ai", json={"opt_in": True})
    status = sam.get("/api/ai/status").json()
    assert status["available"] is False and status["reason"] == "not_allowed"


# --------------------------------------------------------------------------- #
# A person's own provider: write-only key, no fallback to the shared one
# --------------------------------------------------------------------------- #


def test_own_provider_key_is_write_only_and_never_falls_back(ai_two, caplog):
    admin, sam = ai_two
    caplog.set_level(logging.DEBUG)
    r = sam.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY})
    assert r.status_code == 200, r.text
    own = r.json()["own"]
    assert own["key"] == {"set": True, "last4": "9xQz"} and own["scope"] == "user"
    sam.patch("/api/me/ai", json={"opt_in": True, "provider": "own"})
    assert sam.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    status = sam.get("/api/ai/status").json()
    assert status["provider"]["scope"] == "user" and status["remaining_today"] is None
    sam.post("/api/ai/consent", json={"provider_id": own["id"], "purpose": "text"})
    with attach(admin.app, FakeProvider([{"status": 401, "body": {"error": {"message": "invalid key"}}}])) as provider:
        result = sam.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).json()
        assert result["status"] == "error" and result["reason"] == "http_401" and provider.calls == 1  # never the shared key
        assert provider.chat_requests[0].headers["Authorization"] == f"Bearer {OWN_KEY}"
        assert "safety_identifier" not in provider.bodies()[0]  # own key: no shared-key identifier
    for text in (json.dumps(sam.get("/api/me/ai").json()), json.dumps(admin.get("/api/admin/ai-providers").json()), caplog.text):
        assert OWN_KEY not in text
    # the stored ciphertext is bound to its row: moving it to another row does not decrypt
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    token = conn.execute("SELECT api_key_enc FROM ai_providers WHERE scope = 'user'").fetchone()[0]
    assert OWN_KEY.encode() not in token
    conn.close()
    # admin turns personal providers off: Sam's choice is unavailable, not silently shared
    enable(admin, **{"ai.user_keys_allowed": False})
    status = sam.get("/api/ai/status").json()
    assert status["available"] is False and status["reason"] == "own_unavailable"
    assert sam.put("/api/me/ai/provider", json={"preset": "openai", "model": "m", "api_key": OWN_KEY}).status_code == 403


def test_own_provider_validation(ai_client):
    bad = [
        ({"preset": "ollama", "model": "m"}, 400),                                      # not a personal preset
        ({"preset": "openai", "model": "m"}, 400),                                      # key required
        ({"preset": "openai", "model": "m", "api_key": "short"}, 400),
        ({"preset": "openai", "model": "m", "api_key": "has spaces in it ok"}, 400),
        ({"preset": "openai", "model": "bad model!", "api_key": OWN_KEY}, 400),
        ({"preset": "openai_compatible", "model": "m", "base_url": "https://ai.example.com/v1"}, 403),  # custom URLs off
        ({"preset": "openai", "model": "m", "api_key": OWN_KEY, "extra": 1}, 400),
    ]
    for body, status in bad:
        r = ai_client.put("/api/me/ai/provider", json=body)
        assert r.status_code == status, (body, r.text)
        assert OWN_KEY not in r.text and "has spaces" not in r.text and "short" not in r.text.replace("shortened", "")
    enable(ai_client, **{"ai.allow_user_base_url": True})
    for url in ("http://ai.example.com/v1", "https://ai.example.com:8443/v1", "https://10.0.0.5/v1", "https://ai.example.com/"):
        r = ai_client.put("/api/me/ai/provider", json={"preset": "openai_compatible", "model": "m", "base_url": url})
        assert r.status_code == 400, url
    ok = ai_client.put("/api/me/ai/provider", json={"preset": "openai_compatible", "model": "m", "base_url": "https://ai.example.com/v1"})
    assert ok.status_code == 200 and ok.json()["own"]["host"] == "ai.example.com"
    assert ai_client.delete("/api/me/ai/provider").status_code == 204
    assert ai_client.delete("/api/me/ai/provider").status_code == 404


def test_ai_settings_object_has_no_key_field(ai_client):
    r = ai_client.patch("/api/me/settings", json={"ai": {"opt_in": True, "api_key": OWN_KEY}})
    assert r.status_code == 400 and OWN_KEY not in r.text
    assert ai_client.patch("/api/me/ai", json={"api_key": OWN_KEY}).status_code == 400
    assert ai_client.patch("/api/me/ai", json={"provider": "shared:abc"}).status_code == 400
    assert ai_client.patch("/api/me/ai", json={"preferences": "x" * 201}).status_code == 400


# --------------------------------------------------------------------------- #
# Probes (R4 Test connection, §9 A5 e)
# --------------------------------------------------------------------------- #


def test_own_probe_is_limited_and_counted(ai_client):
    ai_client.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY})
    route = lambda r: {"status": 200, "body": {"data": [{"id": "gpt-6-luna"}]}} if r.url.path.endswith("/models") else chat({"ok": "yes"})  # noqa: E731
    with attach(ai_client.app, FakeProvider(route=route)):
        for _ in range(5):
            r = ai_client.post("/api/me/ai/probe")
            assert r.status_code == 200 and r.json()["probe"]["ok"] is True and r.json()["probe"]["structured"] == "json_schema"
        r = ai_client.post("/api/me/ai/probe")
        assert r.status_code == 429
    own = ai_client.get("/api/me/ai").json()["own"]
    assert own["probe"]["ok"] is True
    usage = ai_client.get("/api/admin/ai-usage").json()["usage"]
    assert usage[0]["requests"] == 10 and usage[0]["key_scope"] == "own"  # 5 probes x (models + chat)


# --------------------------------------------------------------------------- #
# Admin providers, the env provider, AUTH_MODE=none (§9 A7)
# --------------------------------------------------------------------------- #


def test_env_provider_is_locked_and_its_key_stays_in_env(ai_client):
    providers = ai_client.get("/api/admin/ai-providers").json()
    env = providers["providers"][0]
    assert env["locked"] and env["key"] == {"set": True, "source": "env", "locked": True} and providers["env_provider"]
    assert ai_client.put(f"/api/admin/ai-providers/{env['id']}", json={"preset": "openai", "model": "x"}).status_code == 409
    assert ai_client.delete(f"/api/admin/ai-providers/{env['id']}").status_code == 409
    conn = sqlite3.connect(ai_client.app.state.settings.db_path)
    assert conn.execute("SELECT api_key_enc FROM ai_providers WHERE locked = 1").fetchone()[0] is None
    conn.close()


def test_admin_provider_crud_and_host_change_resets_consent(ai_client):
    r = ai_client.post("/api/admin/ai-providers", json={"preset": "ollama", "model": "qwen3-vl:8b", "base_url": "http://ollama:11434/v1"})
    assert r.status_code == 400 and r.json()["reason"] == "blocked_address"  # not in AI_PRIVATE_HOSTS
    r = ai_client.post("/api/admin/ai-providers", json={"preset": "openrouter", "model": "qwen/qwen3", "api_key": "sk-or-0123456789abcdefghijkl"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["key"]["last4"] == "ijkl" and r.json()["host"] == "openrouter.ai"
    ai_client.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})
    assert ai_client.post("/api/ai/consent", json={"provider_id": pid, "purpose": "text"}).status_code == 200
    r = ai_client.put(f"/api/admin/ai-providers/{pid}", json={"preset": "openai_compatible", "model": "m",
                                                              "base_url": "https://llm.example.net/v1"})
    assert r.status_code == 200 and r.json()["host"] == "llm.example.net"
    assert ai_client.get("/api/ai/status").json()["consent"]["text"] is None  # asked again for the new host
    audit = ai_client.get("/api/admin/audit").json()["events"]
    changed = [e for e in audit if e["action"] == "ai_provider.changed"]
    assert changed and changed[0]["details"]["consents_reset"] is True and "sk-or" not in json.dumps(audit)
    assert ai_client.delete(f"/api/admin/ai-providers/{pid}").status_code == 204
    assert ai_client.delete(f"/api/admin/ai-providers/{pid}").status_code == 404


def test_admin_probe_hermes_tool_check_and_error_body(tmp_path, foods_json):
    settings = ai_settings(tmp_path, foods_json, private_hosts=("host.containers.internal:8643",))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        r = c.post("/api/admin/ai-providers", json={"preset": "hermes", "model": "kidney", "api_key": "hermes-key-0123456789abcdefgh"})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        toolsets = [{"name": "core", "enabled": True, "configured": True, "tools": ["terminal"]}]
        provider = FakeProvider(route=lambda req: {"status": 200, "body": toolsets} if req.url.path.endswith("/toolsets") else chat(IDEAS),
                                address="169.254.1.2")
        with attach(c.app, provider):
            probe = c.post(f"/api/admin/ai-providers/{pid}/probe").json()
        assert probe["probe"]["ok"] is False and probe["provider"]["disabled_reason"] == "hermes_tools" and provider.calls == 0
        # the person using it is refused before anything is sent, and re-checked (fixed tools → usable again)
        c.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})
        c.put("/api/profile", json={"targets": TARGETS})
        c.post("/api/ai/consent", json={"provider_id": pid, "purpose": "text"})
        with attach(c.app, provider):
            r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 503 and r.json()["reason"] == "hermes_tools" and provider.calls == 0
        toolsets[0]["enabled"] = False
        with attach(c.app, provider):
            r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
            assert r.status_code == 200 and provider.calls == 1
            checks = sum(1 for q in provider.requests if q.url.path.endswith("/toolsets"))
            c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})  # within 5 minutes: no new check
            assert sum(1 for q in provider.requests if q.url.path.endswith("/toolsets")) == checks
        # older than 5 minutes → checked again before the call
        conn = sqlite3.connect(c.app.state.settings.db_path)
        probe_json = json.loads(conn.execute("SELECT probe_json FROM ai_providers WHERE id = ?", (pid,)).fetchone()[0])
        probe_json["tools_checked_at"] = time.time() - 301
        conn.execute("UPDATE ai_providers SET probe_json = ? WHERE id = ?", (json.dumps(probe_json), pid))
        conn.commit()
        conn.close()
        with attach(c.app, provider):
            c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert sum(1 for q in provider.requests if q.url.path.endswith("/toolsets")) == checks + 1


def test_admin_writes_need_admin_and_none_mode_refuses(ai_two, tmp_path, foods_json):
    admin, sam = ai_two
    assert sam.get("/api/admin/ai-providers").status_code == 403
    assert sam.post("/api/admin/ai-providers", json={"preset": "openai", "model": "m"}).status_code == 403
    none = Settings(data_dir=tmp_path / "none", foods_json=foods_json, auth_mode="none",
                    ai=AiEnv(provider="openai", api_key=OPENAI_KEY, model="gpt-6-luna"))
    with TestClient(create_app(none)) as c:
        r = c.post("/api/admin/ai-providers", json={"preset": "openai", "model": "m", "api_key": OWN_KEY})
        assert r.status_code == 403 and r.json()["detail"] == "Set AI providers with environment variables when sign-in is off"
        r = c.patch("/api/admin/settings", json={"ai.enabled": True})
        assert r.status_code == 403 and r.json()["keys"] == ["ai.enabled"]
        assert c.patch("/api/admin/settings", json={"ui.theme": "dark"}).status_code == 200  # other settings still work
        assert c.put("/api/me/ai/provider", json={"preset": "openai", "model": "m", "api_key": OWN_KEY}).status_code == 403
        assert c.get("/api/admin/ai-providers").json()["writable"] is False


# --------------------------------------------------------------------------- #
# Start-up configuration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("env, message", [
    ({"AI_PROVIDER": "skynet"}, "unknown AI preset"),
    ({"AI_PROVIDER": "openai"}, "AI_API_KEY"),
    ({"AI_PROVIDER": "ollama"}, "AI_MODEL"),
    ({"AI_PROVIDER": "openai_compatible", "AI_MODEL": "m"}, "AI_BASE_URL"),
    ({"AI_PROVIDER": "ollama", "AI_MODEL": "m", "AI_BASE_URL": "http://ollama:11434/api"}, "AI_BASE_URL"),
    ({"AI_PRIVATE_HOSTS": "*"}, "wildcard"),
    ({"AI_PRIVATE_HOSTS": "ollama"}, "port"),
    ({"AI_DENY_CIDRS": "nope"}, "AI_DENY_CIDRS"),
    ({"AI_HTTP_PROXY": "proxy:3128"}, "AI_HTTP_PROXY"),
    ({"ALLOW_PRIVATE_AI_HOSTS": "true"}, "AI_PRIVATE_HOSTS"),
    ({"AI_MAX_TOKENS": "10"}, "AI_MAX_TOKENS"),
    ({"AI_STRUCTURED_OUTPUT": "yaml"}, "AI_STRUCTURED_OUTPUT"),
])
def test_bad_ai_environment_stops_the_start(tmp_path, env, message):
    with pytest.raises(ConfigError) as info:
        settings = load_settings({"DATA_DIR": str(tmp_path), **env})
        create_app(settings)
    assert message in str(info.value)


def test_env_provider_follows_the_environment(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json))) as c:
        sign_in(c)
    conn = sqlite3.connect(tmp_path / "data" / "kidney.db")
    conn.execute("PRAGMA foreign_keys = ON")
    pid = conn.execute("SELECT id FROM ai_providers WHERE locked = 1").fetchone()[0]
    conn.execute("INSERT INTO ai_consents VALUES (1, ?, 'text', 'api.openai.com', 'v', 0, 'now')", (pid,))
    conn.commit()
    conn.close()
    other = ai_settings(tmp_path, foods_json, provider="openrouter", api_key="sk-or-0123456789abcdefghijkl", model="qwen/qwen3")
    with TestClient(create_app(other)):
        pass
    conn = sqlite3.connect(tmp_path / "data" / "kidney.db")
    row = conn.execute("SELECT id, preset, base_url FROM ai_providers WHERE locked = 1").fetchone()
    assert row == (pid, "openrouter", "https://openrouter.ai/api/v1")
    assert conn.execute("SELECT COUNT(*) FROM ai_consents").fetchone()[0] == 0  # new host: everyone is asked again
    conn.close()
    with TestClient(create_app(make_settings(tmp_path, foods_json))):
        pass
    conn = sqlite3.connect(tmp_path / "data" / "kidney.db")
    assert conn.execute("SELECT COUNT(*) FROM ai_providers").fetchone()[0] == 0  # AI_PROVIDER unset → gone
    conn.close()


# --------------------------------------------------------------------------- #
# Guidance's ai block, export, deletion, retention
# --------------------------------------------------------------------------- #


def test_next_meal_ai_block_reflects_the_ai_layer(ai_client):
    ai_client.put("/api/profile", json={"targets": TARGETS})
    block = ai_client.get("/api/guidance/next-meal", params={"meal": "dinner", "date": DAY}).json()["ai"]
    assert block == {"available": False, "provider_label": None}
    ai_client.patch("/api/me/ai", json={"opt_in": True})
    block = ai_client.get("/api/guidance/next-meal", params={"meal": "dinner", "date": DAY}).json()["ai"]
    assert block == {"available": True, "provider_label": "OpenAI"}


def test_export_includes_ai_data_without_keys_and_deletion_erases_it(ai_two):
    admin, sam = ai_two
    sam.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY})
    ready(sam)
    with attach(admin.app, FakeProvider([ideas_answer()])):
        sam.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    sign_in(sam, "sam", "quiet-harbour-lantern-58")  # a fresh password entry for the export
    r = sam.get("/api/me/export.zip")
    assert r.status_code == 200
    import io
    import zipfile

    data = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("export.json"))
    assert len(data["ai_audit"]) == 1 and data["ai_usage"][0]["requests"] == 1 and data["ai_consents"]
    assert data["ai_provider"]["preset"] == "openai" and data["ai_provider"]["key_set"] is True
    assert OWN_KEY not in r.content.decode("latin-1") and "9xQz" not in json.dumps(data)
    assert sam.request("DELETE", "/api/me", json={"password": "quiet-harbour-lantern-58", "confirm": "DELETE"}).status_code == 204
    conn = sqlite3.connect(admin.app.state.settings.db_path)
    for table, col in (("ai_audit", "user_id"), ("ai_usage", "user_id"), ("ai_consents", "user_id"), ("ai_providers", "owner_user_id")):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = 2").fetchone()[0] == 0, table
    conn.close()


def test_retention_clears_bodies_then_rows(ai_client):
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([ideas_answer()])):
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    conn = sqlite3.connect(ai_client.app.state.settings.db_path)
    conn.execute("UPDATE ai_audit SET created_at = '2026-01-01T00:00:00.000000Z'")
    conn.commit()
    from datetime import datetime, timezone

    result = K.purge(conn, body_days=30, row_days=365, now=datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert result["bodies_cleared"] == 1 and result["rows_deleted"] == 0
    row = conn.execute("SELECT request_json, response_text, status, verdict_json FROM ai_audit").fetchone()
    assert row[0] is None and row[1] is None and row[2] == "dropped_all" and row[3]  # metadata stays
    assert K.purge(conn, body_days=30, row_days=30, now=datetime(2026, 3, 1, tzinfo=timezone.utc))["rows_deleted"] == 1
    conn.close()


def test_retention_runs_daily_even_with_ai_switched_off(tmp_path, foods_json, fake_clock):
    """Review L1: the purge ran only on AI traffic or at start-up, so switching AI off kept the bodies
    (targets, day totals, describe-a-meal text, model answers) until the next restart. Now it is a step of
    the app's daily housekeeping, run by any signed-in request."""
    from datetime import timedelta

    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        ready(c)
        with attach(c.app, FakeProvider([ideas_answer()])):
            assert c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).status_code == 200
        assert c.patch("/api/admin/settings", json={"ai.enabled": False}).status_code == 200
        conn = sqlite3.connect(c.app.state.settings.db_path)
        old = (fake_clock.moment - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute("UPDATE ai_audit SET created_at = ?", (old,))
        conn.commit()
        assert c.get("/api/profile").status_code == 200  # not yet a day since start-up
        assert conn.execute("SELECT COUNT(*) FROM ai_audit WHERE request_json IS NOT NULL").fetchone()[0] == 1
        fake_clock.advance(hours=25)
        assert c.get("/api/profile").status_code == 200  # an ordinary request with AI off
        row = conn.execute("SELECT request_json, response_text, status FROM ai_audit").fetchone()
        assert row[0] is None and row[1] is None and row[2] == "dropped_all"  # bodies gone, metadata kept
        conn.close()


def test_a_failing_daily_task_does_not_stop_the_others(tmp_path, foods_json, fake_clock, caplog):
    from app.auth import housekeeping

    ran: list[str] = []

    def broken(conn, ctx):  # noqa: ANN001, ANN202
        raise RuntimeError("boom")

    housekeeping.register_daily("zz_test_broken", broken)
    housekeeping.register_daily("zz_test_ok", lambda conn, ctx: ran.append("ok"))
    try:
        with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
            sign_in(c)
            assert c.get("/api/profile").status_code == 200  # the first request after start-up starts the day
            fake_clock.advance(hours=25)
            assert c.get("/api/profile").status_code == 200
        assert ran == ["ok"] and "daily housekeeping task zz_test_broken failed" in caplog.text
    finally:
        housekeeping._daily_tasks.pop("zz_test_broken", None)
        housekeeping._daily_tasks.pop("zz_test_ok", None)


def test_retention_zero_keeps_metadata_only(ai_client):
    enable(ai_client, **{"ai.audit_retention_days": 0})
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([ideas_answer()])):
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    event = ai_client.get("/api/ai/audit").json()["events"][0]
    assert event["request_json"] is None and event["response_text"] is None and event["status"] == "dropped_all"
    assert event["verdict_json"]["status"] == "dropped_all" and event["destination_host"] == "api.openai.com"


def test_logs_carry_metadata_only(ai_client, caplog):
    caplog.set_level(logging.INFO, logger="kidney_health.ai")
    ready(ai_client)
    with attach(ai_client.app, FakeProvider([ideas_answer()])):
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("ai call"))
    assert "feature=next_meal" in line and "host=api.openai.com" in line and "status=dropped_all" in line
    assert "candidates" not in caplog.text and OPENAI_KEY not in caplog.text and "Rice" not in caplog.text


def test_install_registers_the_guidance_status_provider(tmp_path, foods_json):
    app = create_app(make_settings(tmp_path, foods_json))
    assert isinstance(app.state.ai, ai_routes.AiState)


# --------------------------------------------------------------------------- #
# Connection tests kept current (R4 step 5): daily for shared providers, after a change of the env key
# --------------------------------------------------------------------------- #


def probing_provider() -> FakeProvider:
    """Answers the models list, the probe's JSON and vision questions, and the meal call."""
    from ai_support import fixture

    def route(req: Any) -> Any:
        if req.url.path.endswith("/models"):
            return fixture("openai_models.json")
        body = json.loads(req.content)
        name = (body.get("response_format") or {}).get("json_schema", {}).get("name")
        if name == "probe":
            return chat({"ok": "yes"})
        if name == "vision_probe":
            return chat({"color": "red"})
        return chat(IDEAS)

    return FakeProvider(route=route)


def _probed_at(client: TestClient, pid: int) -> str | None:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    try:
        return conn.execute("SELECT probed_at FROM ai_providers WHERE id = ?", (pid,)).fetchone()[0]
    finally:
        conn.close()


def test_a_shared_provider_is_tested_again_daily_after_a_call(ai_client):
    pid = ready(ai_client)
    assert _probed_at(ai_client, pid) is None  # never tested
    provider = probing_provider()
    with attach(ai_client.app, provider, reprobe=True):
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200
    paths = [q.url.path for q in provider.requests]
    assert paths[0].endswith("/chat/completions") and any(p.endswith("/models") for p in paths[1:])
    assert len(provider.chat_requests) == 3  # the call, then the JSON probe and the vision probe (after the answer)
    view = ai_client.get("/api/admin/ai-providers").json()["providers"][0]
    assert view["probe"]["ok"] is True and view["probe"]["structured"] == "json_schema" and view["probed_at"]
    assert ai_client.get("/api/ai/audit").json()["events"].__len__() == 1  # the test is not the person's AI activity
    assert ai_client.get("/api/me/ai").json()["remaining_today"] == 29  # and counts toward nobody's quota

    with attach(ai_client.app, provider, reprobe=True):  # tested today: no new test
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert len(provider.chat_requests) == 4

    conn = sqlite3.connect(ai_client.app.state.settings.db_path)
    conn.execute("UPDATE ai_providers SET probed_at = '2026-01-01T00:00:00.000000Z' WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    with attach(ai_client.app, provider, reprobe=True):  # a day old, but an attempt was made within the hour
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert len(provider.chat_requests) == 5
    ai_client.app.state.ai.reprobe_attempts.clear()
    with attach(ai_client.app, provider, reprobe=True):
        ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert len(provider.chat_requests) == 8 and _probed_at(ai_client, pid) != "2026-01-01T00:00:00.000000Z"


def test_the_daily_test_skips_own_providers_and_survives_failures(ai_client, caplog):
    ai_client.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY})
    ai_client.patch("/api/me/ai", json={"provider": "own"})
    ready(ai_client)
    provider = probing_provider()
    with attach(ai_client.app, provider, reprobe=True):
        assert ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}).status_code == 200
    assert len(provider.requests) == 1  # a person's own provider is tested only when they ask

    ai_client.patch("/api/me/ai", json={"provider": "auto"})
    pid = ai_client.get("/api/ai/status").json()["provider"]["id"]
    ai_client.post("/api/ai/consent", json={"provider_id": pid, "purpose": "text"})
    broken = FakeProvider(route=lambda req: chat(IDEAS) if req.url.path.endswith("/chat/completions") and len(broken.requests) == 1
                          else {"status": 500, "body": {"error": "down"}})
    caplog.set_level(logging.INFO, logger="kidney_health.ai")
    with attach(ai_client.app, broken, reprobe=True):
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200 and r.json()["status"] == "dropped_all"  # the person's answer is unaffected
    view = ai_client.get("/api/admin/ai-providers").json()["providers"][0]
    assert view["probe"]["ok"] is False and view["probe"]["errors"]
    assert "daily connection test ok=False" in caplog.text


def test_a_new_env_key_means_a_new_connection_test(tmp_path, foods_json):
    def start(key: str) -> dict[str, Any]:
        with TestClient(create_app(ai_settings(tmp_path, foods_json, api_key=key)), base_url=HTTPS_URL) as c:
            sign_in(c)
            pid = c.get("/api/admin/ai-providers").json()["providers"][0]["id"]
            if _probed_at(c, pid) is None:
                with attach(c.app, probing_provider()):
                    assert c.post(f"/api/admin/ai-providers/{pid}/probe").json()["probe"]["ok"] is True
            return c.get("/api/admin/ai-providers").json()["providers"][0]

    first = start(OPENAI_KEY)
    assert first["probed_at"]
    assert start(OPENAI_KEY)["probed_at"] == first["probed_at"]  # same key: the test stands
    conn = sqlite3.connect(tmp_path / "data" / "kidney.db")
    stored = conn.execute("SELECT probe_json FROM ai_providers WHERE locked = 1").fetchone()[0]
    conn.close()
    assert OPENAI_KEY not in stored and "key_fp" in stored  # a fingerprint, never the key
    with TestClient(create_app(ai_settings(tmp_path, foods_json, api_key="sk-env-rotated-0123456789abcdef"))):
        pass
    conn = sqlite3.connect(tmp_path / "data" / "kidney.db")
    assert conn.execute("SELECT probe_json, probed_at FROM ai_providers WHERE locked = 1").fetchone() == (None, None)
    conn.close()


def test_missing_ca_certificates_stop_an_https_env_provider(tmp_path, foods_json, monkeypatch):
    import ssl

    from app.ai import transport

    empty = ssl.DefaultVerifyPaths(None, None, "SSL_CERT_FILE", str(tmp_path / "none.pem"), "SSL_CERT_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(transport.ssl, "get_default_verify_paths", lambda: empty)
    monkeypatch.setattr(transport, "CA_FILE_CANDIDATES", (str(tmp_path / "missing.pem"),))
    assert "ca-certificates" in (transport.ca_store_problem("linux") or "")
    assert transport.ca_store_problem("darwin") is None  # truststore uses the system store there
    with pytest.raises(ConfigError, match="uses https, but no CA certificates"):
        create_app(ai_settings(tmp_path, foods_json))
    local = ai_settings(tmp_path, foods_json, provider="ollama", api_key=None, model="qwen3-vl:8b", private_hosts=("ollama:11434",))
    warnings = K.check_env(local)  # a plain-http self-hosted provider still starts, with a warning
    assert any("AI providers on https will not work" in w for w in warnings)
    bundle = tmp_path / "bundle.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setattr(transport, "CA_FILE_CANDIDATES", (str(bundle),))
    assert transport.ca_store_problem("linux") is None


# --------------------------------------------------------------------------- #
# Failure paths: nothing unchecked is shown, nothing falls back to another provider, errors are logged
# --------------------------------------------------------------------------- #


def test_a_judge_bug_shows_nothing_unchecked(ai_client, monkeypatch, caplog):
    from app.ai import guard

    ready(ai_client)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(guard, "judge_ideas", broken)
    with attach(ai_client.app, FakeProvider([ideas_answer()])):
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    data = r.json()
    assert r.status_code == 200 and data["status"] == "error" and data["reason"] == "judge_failed"
    assert "ideas" not in data and "AI judge failed" in caplog.text


def _corrupt_key(client: TestClient, where: str) -> None:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.execute(f"UPDATE ai_providers SET api_key_enc = X'00112233' WHERE {where}")
    conn.commit()
    conn.close()


def test_an_unreadable_own_key_never_falls_back_to_the_shared_provider(ai_client):
    ai_client.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY})
    ai_client.patch("/api/me/ai", json={"provider": "own"})
    ready(ai_client, consent=False)
    _corrupt_key(ai_client, "scope = 'user'")
    status = ai_client.get("/api/ai/status").json()
    assert status["available"] is False and status["reason"] == "own_key_unreadable"
    assert ai_client.get("/api/me/ai").json()["own"]["key"] == {"set": True, "status": "unreadable"}
    provider = FakeProvider()
    with attach(ai_client.app, provider):
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 503 and r.json()["reason"] == "own_key_unreadable" and provider.requests == []


def test_an_unreadable_shared_key_switches_that_provider_off(ai_client, caplog):
    r = ai_client.post("/api/admin/ai-providers", json={"preset": "openrouter", "model": "qwen/qwen3", "api_key": "sk-or-0123456789abcdefghijkl"})
    pid = r.json()["id"]
    ai_client.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})
    _corrupt_key(ai_client, f"id = {pid}")
    status = ai_client.get("/api/ai/status").json()
    assert status["reason"] == "provider_disabled" and "cannot be decrypted" in caplog.text


def test_a_prompt_budget_too_small_for_one_candidate_is_a_clear_503(ai_client):
    r = ai_client.post("/api/admin/ai-providers", json={"preset": "openrouter", "model": "qwen/qwen3", "api_key": "sk-or-0123456789abcdefghijkl",
                                                        "context_tokens": 1024, "max_tokens": 1000})
    pid = r.json()["id"]
    ai_client.put("/api/profile", json={"targets": TARGETS})
    ai_client.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})
    provider = FakeProvider()
    with attach(ai_client.app, provider):
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}, params={"dry_run": "true"})
    assert r.status_code == 503 and r.json()["reason"] == "context_too_small" and "AI_CONTEXT_TOKENS" in r.json()["detail"]


def test_candidates_are_trimmed_to_fit_the_prompt_budget(ai_client):
    ai_client.put("/api/profile", json={"targets": TARGETS})
    body = {"preset": "openrouter", "model": "qwen/qwen3", "api_key": "sk-or-0123456789abcdefghijkl", "max_tokens": 1500,
            "context_tokens": 2_000_000}
    pid = ai_client.post("/api/admin/ai-providers", json=body).json()["id"]
    ai_client.patch("/api/me/ai", json={"opt_in": True, "provider": f"shared:{pid}"})

    def dry() -> dict[str, Any]:
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}, params={"dry_run": "true"})
        assert r.status_code == 200, r.text
        return r.json()

    def candidate_ids(sent: dict[str, Any]) -> list[int]:
        text = sent["body"]["messages"][1]["content"]
        return [c["id"] for c in json.loads(text.split("<data>\n", 1)[1].split("\n</data>")[0])["candidates"]]

    full = dry()
    assert full["trimmed_candidates"] == 0 and len(candidate_ids(full)) >= 2
    estimate = int(len(json.dumps(full["body"], ensure_ascii=False)) / 3.5) + 1
    body["context_tokens"] = max(1024, estimate + 1500 - 1)  # one token short of the full request
    assert ai_client.put(f"/api/admin/ai-providers/{pid}", json=body).status_code == 200
    small = dry()
    assert small["trimmed_candidates"] >= 1
    kept = candidate_ids(small)
    assert kept and kept == candidate_ids(full)[: len(kept)]  # the lowest-ranked candidates go first


def test_a_failing_retention_purge_is_logged_and_does_not_break_the_call(ai_client, monkeypatch, caplog):
    ready(ai_client)

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(K, "purge", failing)
    ai_client.app.state.ai.last_purge = None
    with attach(ai_client.app, FakeProvider([ideas_answer()])):
        r = ai_client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200 and "AI activity retention purge failed" in caplog.text


def test_a_self_hosted_prompt_near_4096_tokens_warns_about_ollama_truncation(tmp_path, foods_json, caplog):
    settings = ai_settings(tmp_path, foods_json, provider="ollama", api_key=None, model="qwen3-vl:8b", vision_model=None,
                           private_hosts=("ollama:11434",))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        ready(c, consent=False)
        pid = c.get("/api/ai/status").json()["provider"]["id"]
        c.post("/api/ai/consent", json={"provider_id": pid, "purpose": "text"})
        with attach(c.app, FakeProvider([chat(IDEAS, usage=(4090, 50))], address="10.89.0.5")):
            r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 200 and "OLLAMA_CONTEXT_LENGTH" in caplog.text


def test_the_daily_test_skips_quietly_when_the_server_is_busy_or_the_key_is_unreadable(ai_client, caplog):
    import anyio

    pid = ready(ai_client)
    app = ai_client.app
    provider = probing_provider()
    with attach(app, provider, reprobe=True):
        app.state.ai.gate.enter(101, 2)  # both slots (ai.max_concurrency = 2) are taken
        app.state.ai.gate.enter(102, 2)
        try:
            anyio.run(ai_routes.maintenance_probe, app, pid)
        finally:
            app.state.ai.gate.leave(101)
            app.state.ai.gate.leave(102)
    assert provider.requests == [] and _probed_at(ai_client, pid) is None
    r = ai_client.post("/api/admin/ai-providers", json={"preset": "openrouter", "model": "qwen/qwen3", "api_key": "sk-or-0123456789abcdefghijkl"})
    other = r.json()["id"]
    _corrupt_key(ai_client, f"id = {other}")
    with attach(app, provider, reprobe=True):
        anyio.run(ai_routes.maintenance_probe, app, other)
    assert provider.requests == [] and "its key cannot be decrypted" in caplog.text


# --------------------------------------------------------------------------- #
# The 10-minute reuse of a meal's answer (note 06 §4.13; v0.3.0 review L13)
# --------------------------------------------------------------------------- #


def _rerank_first_candidate(request) -> dict[str, Any]:
    """A rerank answer naming the first candidate the app sent (so the rules accept it: status ok)."""
    text = json.loads(request.content)["messages"][1]["content"]
    first = json.loads(text.split("<data>\n", 1)[1].split("\n</data>")[0])["candidates"][0]
    return chat({"status": "ok", "refusal": "none", "order": [{"ref": first["ref"], "reason_codes": ["low_potassium"]}]})


def test_the_same_question_within_ten_minutes_reuses_the_checked_answer(ai_client):
    ready(ai_client)
    clock = [1000.0]
    from app.ai.cache import AnswerCache

    ai_client.app.state.ai.answers = AnswerCache(clock=lambda: clock[0])
    body = {"meal": "dinner", "date": DAY, "mode": "rerank"}
    with attach(ai_client.app, FakeProvider(route=_rerank_first_candidate)) as provider:
        first = ai_client.post("/api/ai/next-meal", json=body).json()
        assert first["status"] == "ok" and first["cached"] is False and provider.calls == 1
        clock[0] += 599
        again = ai_client.post("/api/ai/next-meal", json=body).json()
        assert provider.calls == 1  # nothing sent again
        assert again["cached"] is True and again["status"] == "ok" and again["order"] == first["order"]
        assert again["provider"] == first["provider"] and again["audit_id"] != first["audit_id"]
        assert ai_client.get("/api/me/ai").json()["remaining_today"] == 29  # one shared call spent, not two
        events = ai_client.get("/api/ai/audit").json()["events"]
        assert [e["status"] for e in events] == ["cached", "ok"]
        assert events[0]["verdict_json"]["cached_from"] == first["audit_id"]
        assert events[0]["request_json"] is None and events[0]["response_text"] is None  # nothing was sent or received
        # Another meal, another mode or a dry run is another question.
        assert ai_client.post("/api/ai/next-meal", json={**body, "meal": "lunch"}).json()["cached"] is False
        assert provider.calls == 2
        # After ten minutes the provider is asked again.
        clock[0] += 2
        assert ai_client.post("/api/ai/next-meal", json=body).json()["cached"] is False and provider.calls == 3


def test_logging_food_changes_the_question_so_the_answer_is_not_reused(ai_client):
    ready(ai_client)
    body = {"meal": "dinner", "date": DAY, "mode": "rerank"}
    with attach(ai_client.app, FakeProvider(route=_rerank_first_candidate)) as provider:
        assert ai_client.post("/api/ai/next-meal", json=body).json()["cached"] is False
        foods = ai_client.get("/api/foods", params={"limit": 50}).json()["foods"]
        food = next(f for f in foods if (f["nutrients"].get("potassium_mg") or 0) > 0)
        assert ai_client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": food["id"], "servings": 1}).status_code == 201
        assert ai_client.post("/api/ai/next-meal", json=body).json()["cached"] is False and provider.calls == 2
        assert ai_client.post("/api/ai/next-meal", json=body).json()["cached"] is True and provider.calls == 2


def test_fallbacks_are_not_kept_and_deleting_activity_or_consent_forgets_answers(ai_client):
    pid = ready(ai_client)
    body = {"meal": "dinner", "date": DAY}
    with attach(ai_client.app, FakeProvider([ideas_answer(), ideas_answer()])) as provider:  # no idea: the rules' result
        for _ in range(2):
            assert ai_client.post("/api/ai/next-meal", json=body).json()["cached"] is False
        assert provider.calls == 2  # asking again really asks again
    rerank = {**body, "mode": "rerank"}
    with attach(ai_client.app, FakeProvider(route=_rerank_first_candidate)) as provider:
        ai_client.post("/api/ai/next-meal", json=rerank)
        assert len(ai_client.app.state.ai.answers) == 1
        assert ai_client.delete("/api/ai/audit").status_code == 204
        assert len(ai_client.app.state.ai.answers) == 0
        ai_client.post("/api/ai/next-meal", json=rerank)
        assert provider.calls == 2 and len(ai_client.app.state.ai.answers) == 1
        assert ai_client.delete(f"/api/ai/consent/{pid}", params={"purpose": "text"}).status_code == 204
        assert len(ai_client.app.state.ai.answers) == 0
        r = ai_client.post("/api/ai/next-meal", json=rerank)
        assert r.status_code == 409 and provider.calls == 2  # no consent: nothing shown, nothing sent


def test_answers_are_kept_per_person_provider_and_prompt_version():
    from app.ai.cache import AnswerCache

    cache = AnswerCache()
    key = AnswerCache.key(1, 7, "shared", "next_meal", "rerank", "v", "h", {"messages": ["same body"]})
    cache.put(key, {"order": ["f1"]}, 11)
    assert cache.get(AnswerCache.key(2, 7, "shared", "next_meal", "rerank", "v", "h", {"messages": ["same body"]})) is None
    assert cache.get(AnswerCache.key(1, 8, "shared", "next_meal", "rerank", "v", "h", {"messages": ["same body"]})) is None
    assert cache.get(AnswerCache.key(1, 7, "shared", "next_meal", "rerank", "v2", "h", {"messages": ["same body"]})) is None
    hit = cache.get(key)
    assert hit is not None and hit.audit_id == 11
    hit.fresh_copy()["order"].append("f2")  # a judge changing its copy changes nothing kept
    assert cache.get(key).parsed == {"order": ["f1"]}
    assert cache.drop_user(1) == 1 and cache.get(key) is None


def test_the_answer_cache_is_bounded_and_expires():
    from app.ai.cache import AnswerCache

    now = [0.0]
    cache = AnswerCache(ttl_s=600, max_entries=3, clock=lambda: now[0])
    keys = [AnswerCache.key(1, 1, "shared", "next_meal", "ideas", "v", "h", {"n": i}) for i in range(4)]
    for i, k in enumerate(keys):
        now[0] = float(i)
        cache.put(k, {"n": i}, i)
    assert len(cache) == 3 and cache.get(keys[0]) is None  # the oldest went first
    assert AnswerCache.key(1, 1, "s", "f", None, "v", "h", {"a": 1, "b": 2}) == AnswerCache.key(1, 1, "s", "f", None, "v", "h", {"b": 2, "a": 1})
    now[0] = 601.0  # keys[1] was stored at 1.0: exactly 600 s old
    assert cache.get(keys[1]) is None and cache.get(keys[2]) is not None
    now[0] = 1000.0
    assert len(cache) == 0
