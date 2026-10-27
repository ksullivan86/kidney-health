"""Two providers from the environment, routed (docs/ai.md, "A local AI and a cloud AI, both from the environment").

The owner's setup: one LiteLLM proxy with two keys, a local key that can only call models on the home GPU and a cloud key that can only
call cloud models. ``AI_PROVIDER`` + ``AI_PROVIDER_ROLE=local`` is the first, ``AI_CLOUD_PROVIDER`` the second, and the features are
pinned: photos and lab reports ``local``, meal ideas, describe a meal and Ask ``cloud``.

What is pinned down here: each feature reaches the provider its route names, with that provider's key and model, and nothing else is
contacted; **a lab report never reaches the cloud provider**, whatever happens to the local one (unreachable, switched off, gone, not
private any more, resolving to a public address, named by a setting), and photos pinned to ``local`` stay on it too; the cloud provider
follows ``AI_DENY_CIDRS`` and ``AI_HTTP_PROXY`` like every shared provider; ``local_then_cloud`` can use the environment's cloud
provider. A fake transport records every connection by host, so "never contacted" means no connection was even opened. No network."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import httpx2
import pytest

from ai_support import PUBLIC_IP, FakeProvider, chat, no_sleep
from conftest import HTTPS_URL, TestClient, sign_in
from test_ai_chat import ask, step_answer
from test_ai_cloud_env import CLOUD_KEY, CLOUD_URL, LOCAL_KEY, both, cloud_env, cloud_only
from test_ai_routes import DAY, _rerank_first_candidate
from test_ai_routing import IDEAS, PARSE, db, describe, next_meal, ready, route, turn_on
from test_lab_photo import GOOD, read
from test_vision_api import LABEL_ANSWER, photo, usage_rows
from app.ai import routing as R
from app.ai.netpolicy import NetPolicy, parse_private_hosts
from app.ai.transport import PinnedTransport
from app.config import ConfigError
from app.main import create_app

LAN = "10.0.0.5"


class Hosts:
    """Fake AI servers by host name. Every connection is recorded as ``(host, network scope)`` even when nothing is sent, and a host that
    was not named fails the test: nothing may be contacted by accident."""

    def __init__(self, **by_host: FakeProvider) -> None:
        self.by_host = by_host
        self.connections: list[tuple[str, str]] = []

    def factory(self, base: Any, scope: Any, policy: Any) -> Any:
        self.connections.append((base.host, scope))
        assert base.host in self.by_host, f"unexpected connection to {base.host}"
        return self.by_host[base.host].factory(base, scope, policy)

    def hosts(self) -> set[str]:
        return {host for host, _ in self.connections}

    def requests(self, host: str) -> list[httpx2.Request]:
        return self.by_host[host].requests


@contextmanager
def attached(app: Any, hosts: Hosts) -> Iterator[Hosts]:
    state = app.state.ai
    old = state.client.transport_factory, state.client._sleep, state.auto_reprobe
    state.client.transport_factory, state.client._sleep, state.auto_reprobe = hosts.factory, no_sleep, False
    try:
        yield hosts
    finally:
        state.client.transport_factory, state.client._sleep, state.auto_reprobe = old


def servers(*, gpu: list[Any] | None = None, cloud: list[Any] | None = None, gpu_address: str = LAN) -> Hosts:
    return Hosts(**{"gpu.lan": FakeProvider(list(gpu or []), address=gpu_address), "litellm.lan": FakeProvider(list(cloud or []), address=LAN)})


def keys_sent(fake: FakeProvider) -> set[str]:
    return {r.headers["authorization"] for r in fake.requests}


@dataclass
class Two:
    client: TestClient
    local: int  # AI_PROVIDER: the proxy key that can call only the home GPU
    cloud: int  # AI_CLOUD_PROVIDER: the proxy key that can call only cloud models


def start_two(settings, **routes: str) -> Iterator[Two]:
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        ids = {p["env"]: p["id"] for p in c.get("/api/admin/ai-providers").json()["providers"]}
        pinned = {"photos": "local", "meal_ideas": "cloud", "describe": "cloud", "chat": "cloud", "labs": "local", **routes}
        r = route(c, **pinned)
        assert r.status_code == 200, r.text
        yield Two(c, ids.get("AI_PROVIDER", 0), ids["AI_CLOUD_PROVIDER"])


@pytest.fixture
def two(tmp_path, foods_json) -> Iterator[Two]:
    """The recommended setup: photos and lab reports local; meal ideas, describe a meal and Ask in the cloud."""
    yield from start_two(both(tmp_path, foods_json))


@pytest.fixture
def two_one_host(tmp_path, foods_json) -> Iterator[Two]:
    """The owner's real setup: ONE LiteLLM address for both, told apart only by the key."""
    settings = both(tmp_path, foods_json, base_url=CLOUD_URL, private_hosts=("litellm.lan:4000",), cloud=cloud_env())
    yield from start_two(settings)


def agree(rig: Two, *, local: tuple[str, ...] = ("photos", "labs"), cloud: tuple[str, ...] = ("text", "chat")) -> None:
    ready(rig.client, {rig.local: local, rig.cloud: cloud})


# --------------------------------------------------------------------------- #
# Each feature reaches the provider its route names
# --------------------------------------------------------------------------- #


def test_each_feature_reaches_the_provider_its_route_names(two):
    c = two.client
    agree(two)
    hosts = servers(gpu=[chat(LABEL_ANSWER), chat(GOOD)], cloud=[chat(IDEAS), chat(PARSE), step_answer("Oatmeal is a fine breakfast.")])
    gpu, litellm = hosts.by_host["gpu.lan"], hosts.by_host["litellm.lan"]
    with attached(c.app, hosts):
        meal = next_meal(c)
        assert meal.status_code == 200 and meal.json()["provider"]["id"] == two.cloud
        assert (len(gpu.requests), len(litellm.requests)) == (0, 1)
        words = describe(c)
        assert words.status_code == 200 and words.json()["provider"]["id"] == two.cloud
        assert (len(gpu.requests), len(litellm.requests)) == (0, 2)
        chat_reply = ask(c, "is oatmeal ok for breakfast")
        assert chat_reply.status_code == 200 and chat_reply.json()["provider"]["id"] == two.cloud
        assert (len(gpu.requests), len(litellm.requests)) == (0, 3)
        label = photo(c, "/api/vision/label")
        assert label.status_code == 200 and label.json()["provider"]["id"] == two.local
        assert (len(gpu.requests), len(litellm.requests)) == (1, 3)
        labs = read(c)
        assert labs.status_code == 200 and labs.json()["provider"]["id"] == two.local
        assert (len(gpu.requests), len(litellm.requests)) == (2, 3)
    assert hosts.hosts() == {"gpu.lan", "litellm.lan"}
    assert [s for h, s in hosts.connections if h == "litellm.lan"] == ["shared"] * 3  # the cloud provider is a shared one, not pinned to the LAN
    assert {s for h, s in hosts.connections if h == "gpu.lan"} == {"local"}  # the local one is pinned to private addresses
    assert keys_sent(gpu) == {f"Bearer {LOCAL_KEY}"} and keys_sent(litellm) == {f"Bearer {CLOUD_KEY}"}  # each provider's own key
    assert {b["model"] for b in litellm.bodies()} == {"claude-sonnet"}
    assert [b["model"] for b in gpu.bodies()] == ["gemma-vision", "gemma-vision"]
    usage = {r["provider_id"]: r["requests"] for r in db(c, "SELECT provider_id, SUM(requests) AS requests FROM ai_usage GROUP BY provider_id")}
    assert usage == {two.cloud: 3, two.local: 2}  # quota and activity name the provider that served each call


def test_with_one_address_for_both_keys_the_key_tells_them_apart(two_one_host):
    c = two_one_host.client
    agree(two_one_host)
    hosts = Hosts(**{"litellm.lan": FakeProvider([chat(IDEAS), chat(LABEL_ANSWER), chat(GOOD)], address=LAN)})
    with attached(c.app, hosts):
        assert next_meal(c).status_code == 200
        assert photo(c, "/api/vision/label").status_code == 200
        assert read(c).status_code == 200
    sent = [(b.headers["authorization"], b.url.path) for b in hosts.requests("litellm.lan")]
    assert sent == [(f"Bearer {CLOUD_KEY}", "/v1/chat/completions"), (f"Bearer {LOCAL_KEY}", "/v1/chat/completions"),
                    (f"Bearer {LOCAL_KEY}", "/v1/chat/completions")]
    assert [s for _, s in hosts.connections] == ["shared", "local", "local"]


def test_a_feature_pinned_to_local_never_reaches_the_cloud_provider_and_the_other_way_round(tmp_path, foods_json):
    for c in start_two(both(tmp_path, foods_json), meal_ideas="local", describe="local", chat="local"):
        agree(c, local=("photos", "labs", "text"), cloud=())
        hosts = servers(gpu=[chat(IDEAS), chat(PARSE)])
        with attached(c.client.app, hosts):
            assert next_meal(c.client).json()["provider"]["id"] == c.local
            assert describe(c.client).json()["provider"]["id"] == c.local
        assert hosts.hosts() == {"gpu.lan"} and hosts.requests("litellm.lan") == []


def test_a_cloud_only_server_serves_the_cloud_features_and_has_no_local_ones(tmp_path, foods_json):
    for c in start_two(cloud_only(tmp_path, foods_json)):
        assert c.local == 0
        agree(c, local=(), cloud=("text", "chat"))
        status = c.client.get("/api/ai/status").json()
        assert status["routes"]["meal_ideas"]["available"] is True and status["routes"]["meal_ideas"]["role"] == "cloud"
        for feature in ("photos", "labs"):
            assert status["routes"][feature]["available"] is False and status["routes"][feature]["reason"] == "no_local_provider"
        hosts = servers(cloud=[chat(IDEAS)])
        with attached(c.client.app, hosts):
            assert next_meal(c.client).status_code == 200
            for r in (photo(c.client, "/api/vision/label"), read(c.client)):
                assert r.status_code == 503 and r.json()["reason"] == "no_local_provider"
        assert len(hosts.requests("litellm.lan")) == 1 and hosts.hosts() == {"litellm.lan"}


def test_the_status_lines_say_where_each_feature_runs(two):
    agree(two)
    text = {r["feature"]: r["text"] for r in two.client.get("/api/me/ai").json()["routing"]["features"]}
    assert text["photos"] == "Runs on your local AI (gpu.lan:4000)."
    assert text["labs"] == "Runs on your local AI (gpu.lan:4000)."
    assert text["meal_ideas"] == "Runs on LiteLLM proxy (litellm.lan:4000), a cloud AI outside your network."
    assert text["chat"].startswith("Runs on LiteLLM proxy (litellm.lan:4000)")


# --------------------------------------------------------------------------- #
# Lab reports never reach the cloud provider
# --------------------------------------------------------------------------- #


def no_cloud(hosts: Hosts) -> None:
    """The cloud address was not asked for, let alone sent anything."""
    assert "litellm.lan" not in hosts.hosts() and hosts.requests("litellm.lan") == []
    assert all(CLOUD_KEY not in (r.headers.get("authorization") or "") for h in hosts.by_host.values() for r in h.requests)


def lab_attempt(two: Two, hosts: Hosts):
    with attached(two.client.app, hosts):
        return read(two.client)


def test_a_lab_report_with_the_local_provider_unreachable_does_not_go_to_the_cloud(two):
    agree(two)
    hosts = servers(gpu=[httpx2.ConnectError("refused"), httpx2.ConnectError("refused")], cloud=[chat(GOOD)])
    r = lab_attempt(two, hosts)
    assert r.status_code != 200 and r.json().get("status") != "ok", r.text  # no answer: the model on the GPU could not be reached
    assert hosts.hosts() == {"gpu.lan"} and len(hosts.requests("gpu.lan")) == 2  # one try and the one allowed retry, both to the GPU
    no_cloud(hosts)
    assert usage_rows(two.client) >= 1 and db(two.client, "SELECT COUNT(*) AS n FROM lab_results")[0]["n"] == 0


def test_a_lab_report_with_the_local_provider_slow_or_erroring_does_not_go_to_the_cloud(two):
    agree(two)
    for failing in ({"status": 500, "body": {"error": "boom"}}, {"status": 429, "headers": {"Retry-After": "1", "Content-Type": "application/json"},
                                                                  "body": {"error": "slow down"}}, {"status": 401, "body": {"error": "bad key"}}):
        hosts = servers(gpu=[failing, failing], cloud=[chat(GOOD)])
        r = lab_attempt(two, hosts)
        assert r.status_code != 200 or r.json().get("status") != "ok", r.text
        no_cloud(hosts)


def test_a_lab_report_with_the_local_provider_switched_off_is_not_sent_anywhere(two):
    agree(two)
    conn = sqlite3.connect(two.client.app.state.settings.db_path)
    conn.execute("UPDATE ai_providers SET enabled = 0 WHERE id = ?", (two.local,))
    conn.commit()
    conn.close()
    hosts = servers(gpu=[chat(GOOD)], cloud=[chat(GOOD)])
    r = lab_attempt(two, hosts)
    assert r.status_code == 503 and r.json()["reason"] == "provider_disabled", r.text
    assert hosts.connections == [] and usage_rows(two.client) == 0  # nothing was sent, to either
    status = two.client.get("/api/ai/status").json()
    assert status["features"]["lab_report"] is False and status["routes"]["labs"]["available"] is False


def test_a_lab_report_when_the_local_provider_is_gone_is_not_sent_to_the_cloud_one(tmp_path, foods_json):
    """AI_PROVIDER is unset (the GPU is retired): the cloud provider is all that is left, and labs stay off."""
    for c in start_two(cloud_only(tmp_path, foods_json)):
        ready(c.client, {c.cloud: ("text", "chat")})
        hosts = servers(cloud=[chat(GOOD)])
        r = lab_attempt(c, hosts)
        assert r.status_code == 503 and r.json()["reason"] == "no_local_provider"
        assert hosts.connections == []
        # consent for lab reports cannot even be given to the cloud provider
        agreed = c.client.post("/api/ai/consent", json={"provider_id": c.cloud, "purpose": "labs"})
        assert agreed.status_code in (409, 503), agreed.text
        assert db(c.client, "SELECT COUNT(*) AS n FROM ai_consents WHERE purpose = 'labs'")[0]["n"] == 0


def test_no_setting_can_make_the_cloud_provider_the_local_one_for_lab_reports(tmp_path, foods_json):
    for c in start_two(cloud_only(tmp_path, foods_json)):
        state = c.client.app.state
        conn = sqlite3.connect(state.settings.db_path)
        conn.row_factory = sqlite3.Row
        try:
            state.ai.store.set_instance(conn, "ai.route.local_provider", c.cloud, updated_by=None)  # written straight into the settings
            conn.commit()
        finally:
            conn.close()
        ready(c.client, {c.cloud: ("text",)})
        hosts = servers(cloud=[chat(GOOD)])
        r = lab_attempt(c, hosts)
        assert r.status_code == 503 and r.json()["reason"] == "no_local_provider" and hosts.connections == []
        assert c.client.get("/api/ai/status").json()["routes"]["labs"]["available"] is False


def test_a_lab_report_route_cannot_be_cloud_or_any_with_two_providers_either(tmp_path, foods_json, monkeypatch):
    for c in start_two(both(tmp_path, foods_json)):
        for bad in ("cloud", "any", "local_then_cloud"):
            r = route(c.client, labs=bad)
            assert r.status_code in (400, 422), (bad, r.text)
        assert next(f for f in c.client.get("/api/admin/ai-routing").json()["features"] if f["feature"] == "labs")["route"] == "local"
    monkeypatch.setenv("AI_ROUTE_LABS", "cloud")
    with pytest.raises(ConfigError, match="AI_ROUTE_LABS"):
        with TestClient(create_app(both(tmp_path, foods_json)), base_url=HTTPS_URL):
            pass


def test_a_lab_report_is_refused_when_the_local_provider_is_not_private_or_resolves_publicly(two):
    agree(two)
    # the name now resolves to a public address: the transport refuses before sending, and the cloud is not tried
    hosts = servers(gpu=[chat(GOOD)], cloud=[chat(GOOD)], gpu_address=PUBLIC_IP)
    r = lab_attempt(two, hosts)
    assert r.status_code != 200 or r.json().get("status") != "ok", r.text
    assert hosts.by_host["gpu.lan"].requests == []
    no_cloud(hosts)
    # AI_PRIVATE_HOSTS no longer lists the local host: the role is re-checked before the call
    state = two.client.app.state
    conn = sqlite3.connect(state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        narrower = NetPolicy(private_hosts=parse_private_hosts("litellm.lan:4000"))
        resolved = R.resolve_feature(conn, state.ai.store, state.keyring, state.settings, narrower, user_id=1, can_use_shared=True, feature="labs")
        assert resolved.cfg is None and resolved.reason == "local_not_private" and resolved.fallback is None
    finally:
        conn.close()


def test_a_lab_report_never_uses_the_cloud_provider_even_when_the_local_one_fails_the_checks(two):
    """Not even ``local_then_cloud`` exists for labs, and a bad answer from the local AI is just a bad answer."""
    agree(two)
    hosts = servers(gpu=[chat("this is not json at all"), chat("this is not json at all")], cloud=[chat(GOOD)])
    r = lab_attempt(two, hosts)
    assert r.status_code != 200 or r.json().get("status") != "ok"
    no_cloud(hosts)


def test_photos_pinned_to_local_stay_on_it_when_it_fails(two):
    agree(two)
    for failing in ([httpx2.ConnectError("refused")] * 2, [chat("not json at all")] * 2, [{"status": 500, "body": {}}] * 2):
        hosts = servers(gpu=list(failing), cloud=[chat(LABEL_ANSWER)])
        with attached(two.client.app, hosts):
            r = photo(two.client, "/api/vision/label")
        assert r.status_code != 200 or r.json().get("status") != "ok", r.text
        no_cloud(hosts)
    off = sqlite3.connect(two.client.app.state.settings.db_path)
    off.execute("UPDATE ai_providers SET enabled = 0 WHERE id = ?", (two.local,))
    off.commit()
    off.close()
    hosts = servers(gpu=[chat(LABEL_ANSWER)], cloud=[chat(LABEL_ANSWER)])
    with attached(two.client.app, hosts):
        r = photo(two.client, "/api/vision/label")
    assert r.status_code == 503 and r.json()["reason"] == "provider_disabled" and hosts.connections == []


def test_labs_and_photos_are_the_only_features_the_local_pin_protects_and_the_cloud_pin_is_a_choice(two):
    """The other features were pinned to the cloud by the admin: they may go there. Photos and labs were not."""
    agree(two)
    features = {f["feature"]: f["route"] for f in two.client.get("/api/admin/ai-routing").json()["features"]}
    assert features == {"photos": "local", "meal_ideas": "cloud", "describe": "cloud", "chat": "cloud", "labs": "local"}
    assert route(two.client, photos="cloud").status_code == 200  # an admin may send photos to the cloud, on purpose, and sees the warning
    assert route(two.client, labs="cloud").status_code == 400  # but never a lab report


# --------------------------------------------------------------------------- #
# Address rules apply to the cloud provider as they do to every shared provider
# --------------------------------------------------------------------------- #


def test_a_denied_address_is_refused_for_the_cloud_provider_and_the_local_one_still_works(tmp_path, foods_json):
    settings = both(tmp_path, foods_json, deny_cidrs=("10.0.0.0/24",))
    for c in start_two(settings):
        agree(c)
        hosts = Hosts(**{"gpu.lan": FakeProvider([chat(LABEL_ANSWER)], address="10.0.1.5"), "litellm.lan": FakeProvider([chat(IDEAS)], address="10.0.0.5")})
        with attached(c.client.app, hosts):
            denied = next_meal(c.client).json()
            assert denied["status"] == "error" and denied["reason"] == "blocked_address"
            assert photo(c.client, "/api/vision/label").status_code == 200
        assert hosts.requests("litellm.lan") == [] and len(hosts.requests("gpu.lan")) == 1


def test_the_http_proxy_takes_a_public_cloud_provider_and_leaves_the_listed_lan_host_direct(tmp_path, foods_json):
    """AI_HTTP_PROXY: public names go through it (the proxy resolves them), allowlisted private hosts are reached directly."""
    cloud = cloud_env(provider="openai", base_url=None, model="gpt-6-luna", upstream=None, api_key=CLOUD_KEY)
    settings = both(tmp_path, foods_json, http_proxy="http://proxy.lan:3128", cloud=cloud)
    direct, proxied = FakeProvider([chat(LABEL_ANSWER)], address=LAN), FakeProvider([chat(IDEAS)], address=PUBLIC_IP)

    def resolver(host: str, port: int) -> list[str]:
        return [PUBLIC_IP] if host == "api.openai.com" else [LAN]

    def factory(base: Any, scope: Any, policy: Any) -> Any:
        return PinnedTransport(base, scope, policy, resolver=resolver, inner=httpx2.MockTransport(direct.handler),
                               proxied=httpx2.MockTransport(proxied.handler))

    for c in start_two(settings):
        agree(c)
        state = c.client.app.state.ai
        assert state.policy.proxy == "http://proxy.lan:3128"
        state.client.transport_factory, state.auto_reprobe = factory, False
        assert next_meal(c.client).status_code == 200
        assert photo(c.client, "/api/vision/label").status_code == 200
        assert [r.url.host for r in proxied.requests] == ["api.openai.com"]  # the cloud provider, through the proxy
        assert [r.url.host for r in direct.requests] == [LAN]  # the GPU, reached directly at its checked address
        assert proxied.requests[0].headers["authorization"] == f"Bearer {CLOUD_KEY}"


# --------------------------------------------------------------------------- #
# Local, then cloud, with the environment's cloud provider
# --------------------------------------------------------------------------- #


def test_local_then_cloud_asks_the_environments_cloud_provider_only_when_the_local_answer_fails(tmp_path, foods_json):
    for c in start_two(both(tmp_path, foods_json), meal_ideas="local_then_cloud"):
        agree(c, local=("photos", "labs", "text"), cloud=("text",))
        body = {"meal": "dinner", "date": DAY, "mode": "rerank"}
        hosts = Hosts(**{"gpu.lan": FakeProvider([chat("this is not json at all"), chat("this is not json at all")], address=LAN),
                         "litellm.lan": FakeProvider(route=_rerank_first_candidate, address=LAN)})
        with attached(c.client.app, hosts):
            r = c.client.post("/api/ai/next-meal", json=body)
        assert r.status_code == 200 and r.json()["status"] == "ok", r.text
        assert r.json()["provider"]["id"] == c.cloud and r.json()["cloud_fallback"]["used"] is True
        assert keys_sent(hosts.by_host["gpu.lan"]) == {f"Bearer {LOCAL_KEY}"} and keys_sent(hosts.by_host["litellm.lan"]) == {f"Bearer {CLOUD_KEY}"}
        scopes = [s for _, s in hosts.connections]  # the GPU first (the call and its one repair turn), then the cloud provider once
        assert scopes[-1] == "shared" and set(scopes[:-1]) == {"local"} and [h for h, _ in hosts.connections][-1] == "litellm.lan"
        # the local answer is fine: the cloud provider is not asked
        hosts = Hosts(**{"gpu.lan": FakeProvider(route=_rerank_first_candidate, address=LAN), "litellm.lan": FakeProvider(address=LAN)})
        with attached(c.client.app, hosts):
            ok = c.client.post("/api/ai/next-meal", json={**body, "meal": "lunch"})
        assert ok.status_code == 200 and ok.json()["provider"]["id"] == c.local
        assert hosts.requests("litellm.lan") == [] and hosts.hosts() == {"gpu.lan"}


def test_photos_and_labs_do_not_take_the_fallback_unless_chosen_and_labs_never(two):
    agree(two)
    assert route(two.client, photos="local_then_cloud").status_code == 200
    assert route(two.client, labs="local_then_cloud").status_code == 400
    assert route(two.client, chat="local_then_cloud").status_code == 400


def test_no_cloud_value_from_the_environment_changes_the_first_providers_settings(tmp_path, foods_json):
    """The two sets of variables do not mix: a cloud model name, timeout or token cap never lands on the GPU's row."""
    cloud = cloud_env(model="claude-sonnet", timeout_s=200.0, max_tokens=4000, context_tokens=70_000, structured="json_object", reasoning_effort="high")
    for c in start_two(both(tmp_path, foods_json, cloud=cloud)):
        rows = {r["env_slot"]: r for r in db(c.client, "SELECT * FROM ai_providers WHERE locked = 1")}
        main, cl = rows["main"], rows["cloud"]
        assert (main["model"], main["timeout_s"], main["max_tokens"], main["context_tokens"], main["structured"], main["reasoning_effort"]) == (
            "gemma", None, 1500, None, "auto", None)
        assert (cl["model"], cl["timeout_s"], cl["max_tokens"], cl["context_tokens"], cl["structured"], cl["reasoning_effort"]) == (
            "claude-sonnet", 200.0, 4000, 70_000, "json_object", "high")
        agree(c)
        hosts = servers(cloud=[chat(IDEAS)])
        with attached(c.client.app, hosts):
            assert next_meal(c.client).status_code == 200
        body = hosts.by_host["litellm.lan"].bodies()[0]
        assert body["model"] == "claude-sonnet" and body["max_tokens"] == 4000  # litellm uses the max_tokens field
