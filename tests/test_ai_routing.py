"""Privacy tiers, tier 1: provider roles (local / cloud) and per-feature routing (``app/ai/routing.py``,
``PUT /api/admin/ai-routing``, ``docs/ai.md`` "Which AI does each feature use?").

What is pinned down here: a provider that is not on a private network can never be the local AI; the defaults are
the least-trusting ones (local, so off until a local AI exists); an upgraded server keeps working as before until an
admin chooses; a feature routed to the local AI never reaches the cloud provider (the fake cloud sees zero requests),
and the other way round; ``off`` answers like a disabled feature; consent, usage and activity follow the provider the
feature resolves to; the status endpoint says per feature where it runs. No network: every request ends in a fake."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, PUBLIC_IP, attach_routed, chat
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from test_ai_chat import ask, step_answer
from test_ai_voice import WEBM, fake_stt, forwarded
from test_ai_routes import DAY, IDEAS, OWN_KEY, TARGETS
from test_vision_api import LABEL_ANSWER, PLATE_ANSWER, PLATE_JPG, photo
from app.ai import config as K
from app.ai import routing as R
from app.ai.netpolicy import NetPolicy, PolicyError, check_addresses, check_url, is_private_host, parse_base_url, parse_private_hosts
from app.config import AiEnv, ConfigError, load_ai_env
from app.main import create_app

CLOUD_KEY = "sk-env-0123456789abcdefghijklmn"
LOCAL_URL = "http://ollama.lan:11434/v1"
PRIVATE_IP = "10.0.0.5"
FEATURES = ("photos", "meal_ideas", "describe", "chat")  # the four an admin may send to the cloud or to "any"
ALL = (*FEATURES, "labs", "recipes")  # plus the local-only one (a lab report photo; tests/test_lab_photo.py)
PARSE = {"status": "ok", "items": [{"text": "an apple", "search": "apple", "amount": 1, "unit": "serving"}]}


def routed_settings(tmp_path, foods_json, **ai: Any):
    env = {"provider": "openai", "api_key": CLOUD_KEY, "model": "gpt-6-luna", "vision_model": "gpt-6-luna",
           "private_hosts": ("ollama.lan:11434",), **ai}
    return make_settings(tmp_path, foods_json, ai=AiEnv(**env))


@dataclass
class Rig:
    client: TestClient
    local: int  # the Ollama-like provider on ollama.lan:11434 (private)
    cloud: int  # the environment provider (OpenAI, public)


def add_local(client: TestClient, **extra: Any) -> int:
    body = {"preset": "ollama", "model": "gemma", "vision_model": "llava", "base_url": LOCAL_URL, **extra}
    r = client.post("/api/admin/ai-providers", json=body)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def cloud_id(client: TestClient) -> int:
    return next(int(p["id"]) for p in client.get("/api/admin/ai-providers").json()["providers"] if p["locked"])


def turn_on(client: TestClient, **extra: Any) -> None:
    r = client.patch("/api/admin/settings", json={"ai.enabled": True, "ai.chat_enabled": True, "ai.vision_plate_enabled": True, **extra})
    assert r.status_code == 200, r.text


def route(client: TestClient, **body: Any):
    return client.put("/api/admin/ai-routing", json=body)


def pin_roles(rig: Rig) -> None:
    r = route(rig.client, local_provider=rig.local, cloud_provider=rig.cloud)
    assert r.status_code == 200, r.text


def ready(client: TestClient, grants: dict[int, tuple[str, ...]]) -> None:
    """Targets set, opted in, and consent given: ``{provider id: purposes}``."""
    assert client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    assert client.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    for provider_id, purposes in grants.items():
        for purpose in purposes:
            r = client.post("/api/ai/consent", json={"provider_id": provider_id, "purpose": purpose})
            assert r.status_code == 200, r.text


def fakes(*answers: Any, cloud_answers: tuple[Any, ...] = (), local_address: str = PRIVATE_IP) -> tuple[FakeProvider, FakeProvider]:
    return FakeProvider(list(answers), address=local_address), FakeProvider(list(cloud_answers))


def next_meal(client: TestClient, **params: Any):
    return client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY}, params=params)


def describe(client: TestClient):
    return client.post("/api/ai/parse-meal", json={"text": "an apple"})


@pytest.fixture
def rig(tmp_path, foods_json) -> Iterator[Rig]:
    """A new server (fresh database): the environment's OpenAI provider (cloud) and an Ollama on a private host."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        yield Rig(c, add_local(c), cloud_id(c))


def db(client: TestClient, sql: str, *args: Any) -> list[sqlite3.Row]:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Roles: only a private host can be the local AI
# --------------------------------------------------------------------------- #


def test_a_public_provider_can_never_be_the_local_ai(rig):
    r = route(rig.client, local_provider=rig.cloud)
    assert r.status_code == 400 and r.json()["reason"] == "not_private" and r.json()["field"] == "local_provider"
    assert "AI_PRIVATE_HOSTS" in r.json()["detail"]
    assert rig.client.get("/api/admin/ai-routing").json()["roles"]["local"] is None


def test_a_private_provider_can_be_local_and_the_other_cloud(rig):
    r = route(rig.client, local_provider=rig.local, cloud_provider=rig.cloud)
    assert r.status_code == 200, r.text
    roles = r.json()["roles"]
    assert roles["local"]["id"] == rig.local and roles["local"]["private"] is True
    assert roles["cloud"]["id"] == rig.cloud and roles["cloud"]["private"] is False
    by_id = {p["id"]: p for p in r.json()["providers"]}
    assert by_id[rig.local]["role"] == "local" and by_id[rig.cloud]["role"] == "cloud"
    listed = {p["id"]: p for p in rig.client.get("/api/admin/ai-providers").json()["providers"]}
    assert listed[rig.local]["role"] == "local" and listed[rig.local]["private_host"] is True


def test_a_name_that_only_resolves_into_a_listed_network_is_not_private_enough(tmp_path, foods_json):
    """"A hostname that resolves to a private address counts only if netpolicy already treats it so": a name is
    private when it is listed by name; an address literal when it lies in a listed network."""
    settings = routed_settings(tmp_path, foods_json, private_hosts=("10.0.0.0/8",))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        by_name = add_local(c, base_url="http://llm.home:11434/v1")  # allowed to be contacted (the network is listed)...
        by_ip = add_local(c, base_url="http://10.0.0.7:11434/v1", label="Ollama by address")
        r = route(c, local_provider=by_name)
        assert r.status_code == 400 and r.json()["reason"] == "not_private"  # ...but not named as a local AI
        assert route(c, local_provider=by_ip).status_code == 200


def test_one_provider_cannot_hold_both_roles(rig):
    r = route(rig.client, local_provider=rig.local, cloud_provider=rig.local)
    assert r.status_code == 400 and r.json()["reason"] == "same_provider"
    assert rig.client.get("/api/admin/ai-routing").json()["roles"] == {"local": None, "cloud": None}  # nothing was half-applied


def test_unknown_and_personal_providers_are_not_found(rig):
    assert route(rig.client, cloud_provider=9999).status_code == 404
    assert rig.client.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY}).status_code == 200
    own = rig.client.get("/api/me/ai").json()["own"]["id"]
    assert route(rig.client, cloud_provider=own).status_code == 404  # a person's own provider is never a shared role


def test_an_empty_change_and_unknown_fields_are_refused(rig):
    assert route(rig.client).status_code == 400
    assert route(rig.client, photos="everywhere").status_code == 400
    assert route(rig.client, nothing="x").status_code == 400
    assert route(rig.client, local_provider=-1).status_code == 400


def test_only_admins_read_or_change_the_routing(rig):
    sam = add_user(rig.client)
    assert sam.get("/api/admin/ai-routing").status_code == 403
    assert sam.put("/api/admin/ai-routing", json={"photos": "off"}).status_code == 403
    assert rig.client.get("/api/admin/ai-routing").json()["features"][0]["route"] == "local"


def test_editing_the_local_provider_onto_a_public_address_is_refused(rig):
    pin_roles(rig)
    body = {"preset": "ollama", "model": "gemma", "vision_model": "llava", "base_url": "https://api.example.com/v1"}
    r = rig.client.put(f"/api/admin/ai-providers/{rig.local}", json=body)
    assert r.status_code == 400 and r.json()["reason"] == "not_private" and r.json()["field"] == "base_url"
    assert rig.client.put(f"/api/admin/ai-providers/{rig.local}", json={**body, "base_url": LOCAL_URL, "model": "gemma2"}).status_code == 200


def test_deleting_a_provider_clears_its_role(rig):
    pin_roles(rig)
    assert rig.client.delete(f"/api/admin/ai-providers/{rig.local}").status_code == 204
    roles = rig.client.get("/api/admin/ai-routing").json()["roles"]
    assert roles["local"] is None and roles["cloud"]["id"] == rig.cloud
    assert rig.client.get("/api/admin/settings").json()["settings"]["ai.route.local_provider"]["value"] == 0


def test_a_routing_change_is_audited_with_the_old_and_new_values(rig):
    assert route(rig.client, photos="off").status_code == 200
    events = rig.client.get("/api/admin/audit").json()
    rows = events["events"] if isinstance(events, dict) else events
    mine = [e for e in rows if e["action"] == "settings.changed" and e["target_id"] == "ai.route.photos"]
    assert mine and mine[0]["details"]["new"] == "off" and mine[0]["details"]["old"] == "local"


def test_a_locked_route_cannot_be_changed_here(tmp_path, foods_json, monkeypatch):
    monkeypatch.setenv("AI_ROUTE_PHOTOS", "off")
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        r = route(c, photos="cloud")
        assert r.status_code == 409 and r.json()["locked"] is True
        photos = next(f for f in c.get("/api/admin/ai-routing").json()["features"] if f["feature"] == "photos")
        assert photos["route"] == "off" and photos["locked_by_env"] == "AI_ROUTE_PHOTOS" and photos["source"] == "env"


def test_without_sign_in_routing_is_set_by_environment_only(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, auth_mode="none", ai=AiEnv(provider="openai", api_key=CLOUD_KEY, model="gpt-6-luna"))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        assert c.put("/api/admin/ai-routing", json={"photos": "off"}).status_code == 403
        assert c.patch("/api/admin/settings", json={"ai.route.photos": "off"}).status_code == 403
        assert c.get("/api/admin/ai-routing").json()["writable"] is False


# --------------------------------------------------------------------------- #
# Defaults, and the upgrade rule
# --------------------------------------------------------------------------- #


def test_the_registry_defaults_are_the_least_trusting_ones():
    from app import settings_registry as reg

    for feature in FEATURES:
        d = reg.get(f"ai.route.{feature}")
        assert d.default == "local" and d.scope == "instance" and d.env == f"AI_ROUTE_{feature.upper()}"
        assert d.validate("any") == "any" and d.validate("off") == "off"
        with pytest.raises(Exception):
            d.validate("lan")
    for role in ("local", "cloud"):
        assert reg.get(f"ai.route.{role}_provider").default == 0
    keys = {f"ai.route.{f}" for f in ALL} | {"ai.route.local_provider", "ai.route.cloud_provider"}
    assert keys <= reg.NO_SIGNIN_ENV_ONLY


def test_a_new_server_has_every_feature_off_until_a_local_ai_exists(tmp_path, foods_json):
    """No local provider, so the defaults leave every AI feature off: not even the cloud provider the environment
    defines is contacted, and what the person is told says why."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        assert [r["value"] for k, r in c.get("/api/admin/settings").json()["settings"].items() if k in {f"ai.route.{f}" for f in ALL}] == ["local"] * 6
        assert db(c, "SELECT value FROM meta WHERE key = 'ai_routing_initialised'")[0]["value"] == "least_trust"
        ready(c, {})
        status = c.get("/api/ai/status").json()
        assert status["available"] is False and status["reason"] == "no_local_provider"
        assert status["routing"] == {"mode": "routed"} and set(status["routes"]) == set(ALL)
        for f in ALL:
            assert status["routes"][f]["available"] is False and status["routes"][f]["reason"] == "no_local_provider"
        assert not any(status["features"].values())
        local, cloud = fakes()
        with attach_routed(c.app, local=local, cloud=cloud):
            for r in (next_meal(c), describe(c), photo(c, "/api/vision/label"), photo(c, "/api/vision/plate")):
                assert r.status_code == 503 and r.json()["reason"] == "no_local_provider", r.text
            assert ask(c).status_code == 503
        assert local.requests == [] and cloud.requests == []


def test_pinning_to_cloud_needs_a_cloud_ai_to_be_chosen(rig):
    ready(rig.client, {})
    assert route(rig.client, meal_ideas="cloud").status_code == 200
    local, cloud = fakes()
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = next_meal(rig.client)
    assert r.status_code == 503 and r.json()["reason"] == "no_cloud_provider" and cloud.requests == []


def upgraded(tmp_path, foods_json) -> Iterator[TestClient]:
    settings = routed_settings(tmp_path, foods_json)
    with TestClient(create_app(settings), base_url=HTTPS_URL):  # the server as it was: a provider, no routing yet
        pass
    conn = sqlite3.connect(settings.db_path)
    conn.execute("DELETE FROM meta WHERE key = 'ai_routing_initialised'")  # what an older database looks like
    conn.execute("DELETE FROM instance_settings WHERE key LIKE 'ai.route.%'")
    conn.commit()
    conn.close()
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        yield c


def test_an_upgraded_server_keeps_serving_every_feature_from_its_one_provider(tmp_path, foods_json):
    """The upgrade rule: a database that already has a shared provider starts every feature on "any" (the old rule), so
    nothing changes until an admin opens the routing and chooses."""
    for c in upgraded(tmp_path, foods_json):
        turn_on(c)
        settings = c.get("/api/admin/settings").json()["settings"]
        assert [settings[f"ai.route.{f}"]["value"] for f in FEATURES] == ["any"] * 4
        assert settings["ai.route.photos"]["source"] == "instance"
        assert settings["ai.route.labs"]["value"] == "local" and settings["ai.route.labs"]["source"] == "instance"  # never "any"
        assert db(c, "SELECT value FROM meta WHERE key = 'ai_routing_initialised'")[0]["value"] == "as_before"
        overview = c.get("/api/admin/ai-routing").json()
        assert overview["as_before"] is True and [f["route"] for f in overview["features"]] == ["any"] * 4 + ["local", "any"]
        cloud = cloud_id(c)
        ready(c, {cloud: ("text", "photos", "chat")})
        status = c.get("/api/ai/status").json()
        assert status["available"] is True and status["routing"] == {"mode": "as_before"}
        assert status["provider"]["host"] == "api.openai.com" and all(status["features"][k] for k in ("next_meal", "parse_meal", "label", "plate", "chat"))
        assert status["routes"]["photos"]["text"] == "Runs on OpenAI (api.openai.com)."
        local, cloud_fake = fakes(cloud_answers=(chat(IDEAS), chat(LABEL_ANSWER)))
        with attach_routed(c.app, local=local, cloud=cloud_fake):
            assert next_meal(c).status_code == 200
            assert photo(c, "/api/vision/label").status_code == 200
        assert cloud_fake.calls == 2 and local.requests == []


def test_routing_is_decided_once_and_an_admins_choice_survives_a_restart(tmp_path, foods_json):
    settings = routed_settings(tmp_path, foods_json)
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:  # a new server: nothing to preserve
        sign_in(c)
        assert [r["value"] for k, r in c.get("/api/admin/settings").json()["settings"].items() if k.startswith("ai.route.") and k.count(".") == 2
                and not k.endswith("_provider")] == ["local"] * 6
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:  # restarted, now with a provider in the database
        sign_in(c)
        assert c.get("/api/admin/settings").json()["settings"]["ai.route.photos"]["value"] == "local"  # still the new-server rule
        assert route(c, photos="off").status_code == 200
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.get("/api/admin/settings").json()["settings"]["ai.route.photos"]["value"] == "off"


def test_the_upgrade_does_not_overwrite_a_route_the_environment_locks(tmp_path, foods_json, monkeypatch):
    monkeypatch.setenv("AI_ROUTE_CHAT", "off")
    for c in upgraded(tmp_path, foods_json):
        settings = c.get("/api/admin/settings").json()["settings"]
        assert settings["ai.route.chat"]["value"] == "off" and settings["ai.route.chat"]["source"] == "env"
        assert settings["ai.route.photos"]["value"] == "any"


# --------------------------------------------------------------------------- #
# A feature routed to the local AI never reaches the cloud one
# --------------------------------------------------------------------------- #


def test_meal_ideas_run_on_the_local_ai_and_the_cloud_sees_nothing(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text",)})
    local, cloud = fakes(chat(IDEAS))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = next_meal(rig.client)
    assert r.status_code == 200 and r.json()["provider"]["id"] == rig.local and r.json()["provider"]["host"].startswith("ollama.lan")
    assert local.calls == 1 and cloud.requests == []
    assert local.chat_requests[0].headers["host"].startswith("ollama.lan")  # the connection goes to the pinned address, the name stays the Host


def test_describe_a_meal_runs_on_the_local_ai_and_the_cloud_sees_nothing(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text",)})
    local, cloud = fakes(chat(PARSE))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = describe(rig.client)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["provider"]["id"] == rig.local
    assert local.calls == 1 and cloud.requests == []


def test_photos_run_on_the_local_ai_and_the_cloud_sees_nothing(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("photos",)})
    local, cloud = fakes(chat(LABEL_ANSWER), chat(PLATE_ANSWER))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        label = photo(rig.client, "/api/vision/label")
        plate = photo(rig.client, "/api/vision/plate", PLATE_JPG)
    assert label.status_code == 200 and plate.status_code == 200
    assert label.json()["provider"]["id"] == rig.local and plate.json()["provider"]["id"] == rig.local
    assert local.calls == 2 and cloud.requests == []
    assert local.bodies()[0]["model"] == "llava"  # the local provider's own vision model


def test_the_ask_chat_runs_on_the_local_ai_and_the_cloud_sees_nothing(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("chat",)})
    local, cloud = fakes(step_answer("Oatmeal is a fine breakfast."))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = ask(rig.client, "is oatmeal ok for breakfast")
    assert r.status_code == 200, r.text
    assert r.json()["ai_called"] is True and r.json()["provider"]["id"] == rig.local
    assert local.calls == 1 and cloud.requests == []


def test_each_feature_can_go_to_a_different_provider(rig):
    """The recommended home setup: photos, ideas and describe local, chat in the cloud."""
    pin_roles(rig)
    assert route(rig.client, chat="cloud").status_code == 200
    ready(rig.client, {rig.local: ("text", "photos"), rig.cloud: ("chat",)})
    local, cloud = fakes(chat(IDEAS), chat(PARSE), chat(LABEL_ANSWER), cloud_answers=(step_answer("Oatmeal is a fine breakfast."),))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        assert next_meal(rig.client).status_code == 200
        assert describe(rig.client).status_code == 200
        assert photo(rig.client, "/api/vision/label").status_code == 200
        chat_answer = ask(rig.client, "is oatmeal ok for breakfast").json()
    assert (local.calls, cloud.calls) == (3, 1) and chat_answer["provider"]["id"] == rig.cloud


def test_the_local_ai_is_only_ever_contacted_on_a_private_address(rig):
    """Even if its name later resolves to a public address, the transport refuses: nothing is sent."""
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text",)})
    local, cloud = fakes(chat(IDEAS), local_address=PUBLIC_IP)
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = next_meal(rig.client)
    assert r.json()["status"] == "error" and r.json()["reason"] == "blocked_address"
    assert local.requests == [] and cloud.requests == []


def test_a_local_provider_that_stops_being_private_is_not_used(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text",)})
    state = rig.client.app.state
    conn = sqlite3.connect(state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        args = dict(user_id=1, can_use_shared=True, feature="meal_ideas")
        common = (conn, state.ai.store, state.keyring, state.settings)
        assert R.resolve_feature(*common, state.ai.policy, **args).cfg.local_only is True
        shrunk = R.resolve_feature(*common, NetPolicy(), **args)  # AI_PRIVATE_HOSTS no longer lists the host
        assert shrunk.cfg is None and shrunk.reason == "local_not_private"
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# A feature routed to the cloud, off, a person's own provider
# --------------------------------------------------------------------------- #


def test_a_feature_moved_to_cloud_uses_the_cloud_and_asks_for_consent_again(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text",)})
    local, cloud = fakes(chat(IDEAS), chat(IDEAS), cloud_answers=(chat(IDEAS),))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        assert next_meal(rig.client).status_code == 200  # consent for the local AI covers it
        assert route(rig.client, meal_ideas="cloud").status_code == 200
        asked = next_meal(rig.client)
        assert asked.status_code == 409 and asked.json()["consent_required"] is True
        consent = asked.json()["consent"]
        assert consent["provider_id"] == rig.cloud and consent["host"] == "api.openai.com" and consent["local"] is False
        assert cloud.requests == []  # nothing left before the person agreed
        given = rig.client.post("/api/ai/consent", json={"provider_id": rig.cloud, "purpose": "text"})
        assert given.status_code == 200 and given.json()["consent"]["host"] == "api.openai.com"
        again = next_meal(rig.client)
        assert again.status_code == 200 and again.json()["provider"]["id"] == rig.cloud
        assert route(rig.client, meal_ideas="local").status_code == 200
        assert next_meal(rig.client).status_code == 200  # the earlier consent for the local AI still stands
    assert (local.calls, cloud.calls) == (2, 1)


def test_consent_is_given_for_a_provider_a_feature_of_that_purpose_now_uses(rig):
    """"text" covers meal ideas and describe, which may run on different providers; any other provider is refused."""
    pin_roles(rig)
    assert route(rig.client, describe="cloud").status_code == 200
    ready(rig.client, {})
    for provider_id in (rig.local, rig.cloud):  # meal ideas → local, describe → cloud
        assert rig.client.post("/api/ai/consent", json={"provider_id": provider_id, "purpose": "text"}).status_code == 200
    stray = rig.client.post("/api/ai/consent", json={"provider_id": 9999, "purpose": "text"})
    assert stray.status_code == 409 and stray.json()["consent"]["provider_id"] in (rig.local, rig.cloud)
    wrong_purpose = rig.client.post("/api/ai/consent", json={"provider_id": rig.cloud, "purpose": "photos"})
    assert wrong_purpose.status_code == 409  # photos still run on the local AI
    status = rig.client.get("/api/ai/status").json()
    assert status["routes"]["meal_ideas"]["consent"]["host"].startswith("ollama.lan")
    assert status["routes"]["describe"]["consent"]["host"] == "api.openai.com"
    assert status["routes"]["photos"]["consent"] is None


def test_off_answers_like_a_disabled_feature_and_sends_nothing(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text", "photos", "chat")})
    assert route(rig.client, photos="off", meal_ideas="off", describe="off", chat="off", labs="off",
                 recipes="off").status_code == 200
    local, cloud = fakes()
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        for r in (next_meal(rig.client), describe(rig.client), photo(rig.client, "/api/vision/label"), photo(rig.client, "/api/vision/plate")):
            assert r.status_code == 503 and r.json()["reason"] == "feature_off", r.text
            assert r.json()["detail"] == "Your admin has switched this AI feature off."
        assert ask(rig.client).status_code == 404  # like Ask switched off (ai.chat_enabled): as if not registered
    assert local.requests == [] and cloud.requests == []
    status = rig.client.get("/api/ai/status").json()
    assert not any(status["features"].values()) and status["reason"] == "feature_off"
    assert [status["routes"][f]["route"] for f in ALL] == ["off"] * 6
    assert status["routes"]["photos"]["text"] == "Switched off by your admin."


def test_a_person_with_their_own_provider_keeps_it_but_off_is_off_for_everyone(rig):
    pin_roles(rig)
    c = rig.client
    assert c.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY}).status_code == 200
    own = c.get("/api/me/ai").json()["own"]["id"]
    ready(c, {})
    assert c.patch("/api/me/ai", json={"provider": "own"}).status_code == 200
    assert c.post("/api/ai/consent", json={"provider_id": own, "purpose": "text"}).status_code == 200
    local, cloud = fakes(cloud_answers=())
    mine = FakeProvider([chat(IDEAS)])
    with attach_routed(c.app, local=local, cloud=cloud, own=mine):
        ok = next_meal(c)
        assert ok.status_code == 200 and ok.json()["provider"]["id"] == own  # routed "local", but their own provider is their choice
        status = c.get("/api/ai/status").json()
        assert status["routes"]["meal_ideas"]["role"] == "own" and "outside your network" in status["routes"]["meal_ideas"]["text"]
        assert route(c, meal_ideas="off").status_code == 200
        refused = next_meal(c)
        assert refused.status_code == 503 and refused.json()["reason"] == "feature_off"
    assert mine.calls == 1 and local.requests == [] and cloud.requests == []


def test_the_shared_provider_a_person_picked_is_ignored_once_routing_decides(rig):
    pin_roles(rig)
    ready(rig.client, {rig.local: ("text",)})
    assert rig.client.patch("/api/me/ai", json={"provider": f"shared:{rig.cloud}"}).status_code == 200
    local, cloud = fakes(chat(IDEAS))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = next_meal(rig.client)
    assert r.status_code == 200 and r.json()["provider"]["id"] == rig.local and cloud.requests == []


# --------------------------------------------------------------------------- #
# Quota, activity, "What will be sent?", status, what a person reads
# --------------------------------------------------------------------------- #


def test_usage_activity_and_the_dry_run_follow_the_provider_the_feature_resolves_to(rig):
    pin_roles(rig)
    assert route(rig.client, describe="cloud").status_code == 200
    ready(rig.client, {rig.local: ("text",), rig.cloud: ("text",)})
    local, cloud = fakes(chat(IDEAS), cloud_answers=(chat(PARSE),))
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        dry = next_meal(rig.client, dry_run="true").json()
        assert dry["provider"]["id"] == rig.local and dry["provider"]["local"] is True and dry["host"].startswith("ollama.lan")
        assert "ollama.lan" in dry["destination"]
        assert local.requests == [] and cloud.requests == []  # a dry run sends nothing
        dry_cloud = rig.client.post("/api/ai/parse-meal?dry_run=true", json={"text": "an apple"}).json()
        assert dry_cloud["provider"]["id"] == rig.cloud and dry_cloud["provider"]["local"] is False
        assert next_meal(rig.client).status_code == 200
        assert describe(rig.client).status_code == 200
    assert {r["provider_id"]: r["requests"] for r in db(rig.client, "SELECT provider_id, SUM(requests) AS requests FROM ai_usage GROUP BY provider_id")} == {
        rig.local: 1, rig.cloud: 1}
    audit = {r["feature"]: r["provider_id"] for r in db(rig.client, "SELECT feature, provider_id FROM ai_audit")}
    assert audit["next_meal:ideas"] == rig.local and audit["parse_meal"] == rig.cloud


def test_the_status_says_where_each_feature_runs(rig):
    pin_roles(rig)
    assert route(rig.client, chat="cloud", photos="off").status_code == 200
    ready(rig.client, {rig.local: ("text",)})
    status = rig.client.get("/api/ai/status").json()
    routes = status["routes"]
    assert routes["meal_ideas"]["role"] == "local" and routes["meal_ideas"]["runs_on"]["id"] == rig.local
    assert routes["meal_ideas"]["text"] == "Runs on your local AI (ollama.lan:11434)." or routes["meal_ideas"]["text"].startswith("Runs on your local AI (ollama.lan")
    assert routes["describe"]["role"] == "local" and routes["meal_ideas"]["consent"]["host"].startswith("ollama.lan")
    assert routes["chat"]["role"] == "cloud" and routes["chat"]["runs_on"]["host"] == "api.openai.com"
    assert routes["chat"]["text"] == "Runs on OpenAI (api.openai.com), a cloud AI outside your network."
    assert routes["photos"]["available"] is False and routes["photos"]["reason"] == "feature_off" and routes["photos"]["runs_on"] is None
    assert routes["chat"]["consent"] is None  # not agreed for the cloud provider yet
    assert status["available"] is True and status["provider"]["id"] == rig.local  # the headline: the first feature that resolves
    assert status["features"] == {"next_meal": True, "parse_meal": True, "label": False, "plate": False, "chat": True, "voice": False,
                                  "lab_report": True, "recipes": True, "recipe_steps": False}
    assert status["consent"]["text"]["host"].startswith("ollama.lan") and status["consent"]["photos"] is None


def test_a_person_reads_one_line_per_feature(rig):
    pin_roles(rig)
    assert route(rig.client, chat="cloud").status_code == 200
    ready(rig.client, {})
    routing = rig.client.get("/api/me/ai").json()["routing"]
    assert routing["mode"] == "routed" and [f["feature"] for f in routing["features"]] == list(ALL)
    text = {f["feature"]: f["text"] for f in routing["features"]}
    assert text["photos"].startswith("Runs on your local AI (ollama.lan") and text["chat"].startswith("Runs on OpenAI (api.openai.com), a cloud AI")
    assert "consent" not in routing["features"][0]  # one line each, no consent detail


def test_the_guidance_block_follows_the_meal_ideas_route(rig):
    ready(rig.client, {})
    params = {"meal": "dinner", "date": DAY}
    assert rig.client.get("/api/guidance/next-meal", params=params).json()["ai"]["available"] is False  # no local AI yet
    pin_roles(rig)
    ai = rig.client.get("/api/guidance/next-meal", params=params).json()["ai"]
    assert ai["available"] is True and ai["provider_label"] == "Ollama"


def test_the_overview_has_what_the_admin_screen_needs(rig):
    pin_roles(rig)
    o = rig.client.get("/api/admin/ai-routing").json()
    assert [f["feature"] for f in o["features"]] == list(ALL) and o["writable"] is True and o["env_role"] is None
    assert o["defaults"] == {f: "local" for f in ALL} and o["as_before"] is False
    ROUTES4, ROUTES5 = ["local", "cloud", "off", "any"], ["local", "cloud", "off", "any", "local_then_cloud"]
    assert {f["feature"]: f["allowed"] for f in o["features"]} == {
        "photos": ROUTES5, "meal_ideas": ROUTES5, "describe": ROUTES5, "chat": ROUTES4, "labs": ["local", "off"],
        "recipes": ROUTES5}  # tier 3: not Ask, not labs
    assert all("sends" in f and f["label"] for f in o["features"])
    assert {p["id"]: p["private"] for p in o["providers"]} == {rig.local: True, rig.cloud: False}


# --------------------------------------------------------------------------- #
# The environment provider's role (AI_PROVIDER_ROLE)
# --------------------------------------------------------------------------- #


def test_ai_provider_role_is_read_and_checked():
    assert load_ai_env({"AI_PROVIDER_ROLE": "Local"}).provider_role == "local"
    assert load_ai_env({}).provider_role is None
    with pytest.raises(ConfigError):
        load_ai_env({"AI_PROVIDER_ROLE": "lan"})


def test_the_environment_provider_cannot_be_local_unless_its_host_is_private(tmp_path, foods_json):
    with pytest.raises(ConfigError, match="AI_PROVIDER_ROLE=local needs a private host"):
        K.check_env(routed_settings(tmp_path, foods_json, provider_role="local"))
    assert K.check_env(routed_settings(tmp_path, foods_json, provider_role="cloud")) == []
    local_env = routed_settings(tmp_path, foods_json, provider="ollama", base_url=LOCAL_URL, model="gemma", api_key=None, provider_role="local")
    assert K.check_env(local_env) == []
    stray = routed_settings(tmp_path, foods_json, provider=None, base_url=None, model=None, api_key=None, vision_model=None, provider_role="local")
    assert any("AI_PROVIDER_ROLE" in w for w in K.check_env(stray))


def test_the_environment_provider_holds_the_role_the_environment_names(tmp_path, foods_json):
    settings = routed_settings(tmp_path, foods_json, provider="ollama", base_url=LOCAL_URL, model="gemma", api_key=None, provider_role="local")
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        env_id = cloud_id(c)  # the locked row, whatever its role
        overview = c.get("/api/admin/ai-routing").json()
        assert overview["roles"]["local"]["id"] == env_id and overview["env_role"] == "local"
        ready(c, {env_id: ("text",)})
        local, cloud = fakes(chat(IDEAS))
        with attach_routed(c.app, local=local, cloud=cloud):
            assert next_meal(c).status_code == 200
        assert local.calls == 1 and cloud.requests == []
        r = route(c, local_provider=env_id)
        assert r.status_code == 409 and r.json()["locked"] is True  # the role comes from the environment
        other = add_local(c, base_url="http://ollama.lan:11434/v1", label="Second Ollama")
        assert route(c, cloud_provider=other).status_code == 200  # the cloud role is still the admin's
        assert route(c, cloud_provider=env_id).status_code == 409  # the environment provider holds no other role


# --------------------------------------------------------------------------- #
# The network policy: the local scope
# --------------------------------------------------------------------------- #

POLICY = NetPolicy(private_hosts=parse_private_hosts("ollama.lan:11434, 10.0.0.0/8, [::1]:8080"))


@pytest.mark.parametrize("url, private", [
    ("http://ollama.lan:11434/v1", True),
    ("https://ollama.lan:11434/v1", True),
    ("http://ollama.lan:11435/v1", False),  # another port
    ("http://other.lan:11434/v1", False),  # not listed by name
    ("http://10.2.3.4:8000/v1", True),  # an address inside a listed network
    ("http://10.2.3.4:9/v1", True),
    ("https://api.openai.com/v1", False),
    ("https://93.184.216.34/v1", False),  # a public address literal
    ("http://192.168.1.5:11434/v1", False),  # private, but not listed
    ("http://[::1]:8080/v1", True),
    ("http://169.254.169.254/v1", False),  # the cloud metadata address is denied, never private
])
def test_is_private_host(url, private):
    assert is_private_host(parse_base_url(url), POLICY) is private


def test_the_local_scope_refuses_anything_but_a_private_destination():
    local = parse_base_url("http://ollama.lan:11434/v1")
    check_url(local, "local", POLICY)
    assert check_addresses(local, ["10.9.9.9"], "local", POLICY)
    with pytest.raises(PolicyError, match="public address"):
        check_addresses(local, [PUBLIC_IP], "local", POLICY)  # a name that came to resolve publicly
    check_addresses(local, [PUBLIC_IP], "shared", POLICY)  # the shared scope would have gone there
    with pytest.raises(PolicyError, match="not a private host"):
        check_url(parse_base_url("https://api.openai.com/v1"), "local", POLICY)
    with pytest.raises(PolicyError):
        check_addresses(local, ["10.9.9.9", PUBLIC_IP], "local", POLICY)  # one public answer refuses the call


# --------------------------------------------------------------------------- #
# Connection tests, deployment files
# --------------------------------------------------------------------------- #


def test_the_connection_test_of_the_local_provider_stays_on_the_private_network(rig):
    pin_roles(rig)
    probe = {"status": 200, "headers": {"Content-Type": "application/json"}, "body": {"data": [{"id": "gemma"}]}}
    local, cloud = FakeProvider([probe], address=PUBLIC_IP), FakeProvider()
    with attach_routed(rig.client.app, local=local, cloud=cloud):
        r = rig.client.post(f"/api/admin/ai-providers/{rig.local}/probe")
    assert r.status_code == 200 and r.json()["probe"]["ok"] is False  # the name resolved publicly: refused, nothing sent
    assert local.requests == [] and cloud.requests == []


def test_the_deployment_files_pass_the_routing_variables_and_the_ollama_overlay_is_the_local_ai():
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    compose = (repo / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    example = (repo / "deploy" / ".env.example").read_text(encoding="utf-8")
    for name in ("AI_PROVIDER_ROLE", "AI_ROUTE_PHOTOS", "AI_ROUTE_MEAL_IDEAS", "AI_ROUTE_DESCRIBE", "AI_ROUTE_CHAT", "AI_ROUTE_LABS"):
        assert f"      {name}: ${{{name}:-}}" in compose, name
        assert f"\n{name}=\n" in example, name
    overlay = (repo / "deploy" / "compose.ai-ollama.yaml").read_text(encoding="utf-8")
    assert "AI_PROVIDER_ROLE: local" in overlay and "AI_PRIVATE_HOSTS: ollama:11434" in overlay


def test_a_blank_routing_variable_locks_nothing():
    from app.settings_registry import REGISTRY
    from app.settings_store import SettingsStore

    store = SettingsStore(env={f"AI_ROUTE_{f.upper()}": "" for f in FEATURES})
    for f in FEATURES:
        assert store.env_value(REGISTRY[f"ai.route.{f}"]) == (False, None)
    assert load_ai_env({"AI_PROVIDER_ROLE": ""}).provider_role is None
    assert SettingsStore(env={"AI_ROUTE_PHOTOS": "cloud"}).env_value(REGISTRY["ai.route.photos"]) == (True, "cloud")


# --------------------------------------------------------------------------- #
# Voice (the Ask microphone) rides with Ask: not routed, keyed to the chat route's provider
# --------------------------------------------------------------------------- #

STT_ENV = {"stt_base_url": "https://stt.example.com/v1", "stt_model": "whisper-1", "stt_api_key": "stt-key-ZYXWVUTSRQPONMLKJIHGFEDCBA123456"}


@pytest.fixture
def voice_rig(tmp_path, foods_json) -> Iterator[Rig]:
    """The routed server of ``rig`` with voice on: every feature at its default (local), roles chosen."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json, **STT_ENV)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c, **{"ai.voice_enabled": True})
        rig = Rig(c, add_local(c), cloud_id(c))
        pin_roles(rig)
        ready(c, {})
        yield rig


def voice_say(client: TestClient):
    return client.post("/api/ai/transcribe", content=WEBM, headers={"Content-Type": "audio/webm"})


def test_voice_consent_and_recording_work_with_every_feature_on_local(voice_rig):
    c, local_id = voice_rig.client, voice_rig.local
    status = c.get("/api/ai/status").json()
    assert [status["routes"][f]["route"] for f in FEATURES] == ["local"] * 4
    assert status["features"]["voice"] is True and status["voice"]["host"] == "stt.example.com"
    assert status["voice"]["request"]["provider_id"] == local_id  # keyed to the AI provider that serves Ask now
    assert status["voice"]["request"]["host"] == "stt.example.com" and status["voice"]["consent"] is None
    stt_fake, ai_fake = fake_stt(), FakeProvider([step_answer("Oatmeal is a fine breakfast.")], address=PRIVATE_IP)
    with attach_routed(c.app, local=ai_fake, cloud=stt_fake):
        assert voice_say(c).status_code == 409  # not agreed yet; nothing sent
        assert forwarded(stt_fake) == []
        agreed = c.post("/api/ai/consent", json={"provider_id": local_id, "purpose": "voice"})
        assert agreed.status_code == 200 and agreed.json()["consent"]["host"] == "stt.example.com" and agreed.json()["purpose"] == "voice"
        assert c.get("/api/ai/status").json()["voice"]["consent"]["host"] == "stt.example.com"
        heard = voice_say(c)
        assert heard.status_code == 200 and heard.json() == {"text": "what is left for today"}
        assert len(forwarded(stt_fake)) == 1 and ai_fake.requests == []  # the recording goes to the transcription server only
        assert c.post("/api/ai/consent", json={"provider_id": local_id, "purpose": "chat"}).status_code == 200
        asked = ask(c, "is oatmeal ok for breakfast")  # and Ask itself still runs on the local AI
        assert asked.status_code == 200 and asked.json()["provider"]["id"] == local_id
    assert ai_fake.calls == 1 and len(forwarded(stt_fake)) == 1


def test_voice_consent_names_the_provider_ask_uses_and_a_stray_one_is_asked_again(voice_rig):
    c = voice_rig.client
    stray = c.post("/api/ai/consent", json={"provider_id": voice_rig.cloud, "purpose": "voice"})  # Ask does not use the cloud AI
    assert stray.status_code == 409 and stray.json()["consent"]["provider_id"] == voice_rig.local
    assert stray.json()["consent"]["purpose"] == "voice" and stray.json()["consent"]["host"] == "stt.example.com"
    assert db(c, "SELECT * FROM ai_consents WHERE purpose = 'voice'") == []


def test_voice_follows_ask_when_ask_moves_to_the_cloud_and_asks_again(voice_rig):
    c = voice_rig.client
    assert c.post("/api/ai/consent", json={"provider_id": voice_rig.local, "purpose": "voice"}).status_code == 200
    assert route(c, chat="cloud").status_code == 200
    status = c.get("/api/ai/status").json()
    assert status["voice"]["request"]["provider_id"] == voice_rig.cloud and status["voice"]["consent"] is None
    stt_fake = fake_stt()
    with attach_routed(c.app, local=FakeProvider(), cloud=stt_fake):
        again = voice_say(c)
        assert again.status_code == 409 and again.json()["consent"]["provider_id"] == voice_rig.cloud and forwarded(stt_fake) == []
        assert c.post("/api/ai/consent", json={"provider_id": voice_rig.cloud, "purpose": "voice"}).status_code == 200
        assert voice_say(c).status_code == 200
    assert len(forwarded(stt_fake)) == 1


def test_voice_is_off_with_ask_and_unavailable_without_a_provider_for_ask(voice_rig, tmp_path, foods_json):
    c = voice_rig.client
    assert c.post("/api/ai/consent", json={"provider_id": voice_rig.local, "purpose": "voice"}).status_code == 200
    assert route(c, chat="off").status_code == 200
    status = c.get("/api/ai/status").json()
    assert status["voice"] is None and status["features"]["voice"] is False and status["consent"]["voice"] is None
    stt_fake = fake_stt()
    with attach_routed(c.app, local=FakeProvider(), cloud=stt_fake):
        assert voice_say(c).status_code == 404  # like Ask: as if not registered
        assert c.post("/api/ai/consent", json={"provider_id": voice_rig.local, "purpose": "voice"}).status_code == 503
    assert stt_fake.requests == []
    # A new server with no local AI: Ask is off until one exists, so the microphone is too.
    with TestClient(create_app(routed_settings(tmp_path / "new", foods_json, **STT_ENV)), base_url=HTTPS_URL) as n:
        sign_in(n)
        turn_on(n, **{"ai.voice_enabled": True})
        ready(n, {})
        assert n.get("/api/ai/status").json()["features"]["voice"] is False
        quiet = fake_stt()
        with attach_routed(n.app, local=FakeProvider(), cloud=quiet):
            r = voice_say(n)
            assert r.status_code == 503 and r.json()["reason"] == "no_local_provider"
            assert n.post("/api/ai/consent", json={"provider_id": 1, "purpose": "voice"}).status_code == 503
        assert quiet.requests == []
