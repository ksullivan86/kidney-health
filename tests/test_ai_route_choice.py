"""Chosen people pick the server's local or cloud AI, per feature (design note 32; ``app/ai/route_choice.py``, the step in
``app/ai/routing.py``, ``PUT /api/me/ai/route-choice``, ``users.can_choose_ai``).

The rig is the owner's: the home GPU as the local AI (``gpu.lan``) and a LiteLLM key for cloud models as the cloud AI
(``litellm.lan``), both from the environment. A fake transport records every connection by host, so "never contacted" means no
connection was opened. What is pinned down: the switch off changes nothing; without the admin's tick the choice is refused and a
stored one ignored; local and cloud resolve per feature; the admin's ``off`` wins; lab report photos are never offered, never
stored, never cloud; a newly chosen cloud AI asks for consent first; the privacy filter runs when a person picks the cloud; a
person's own provider still wins; only admins give the tick, and both kinds of change are in the audit log; one person's choice
never changes another's. No network."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, attach_routed, chat
from conftest import HTTPS_URL, TestClient, add_user, sign_in
from test_ai_chat import ask, step_answer
from test_ai_cloud_env import both, cloud_only
from test_ai_cloud_routing import Two, attached, servers, start_two
from test_ai_privacy_filter import MEAL, PARSED, name_the_account
from test_ai_routes import OWN_KEY, TARGETS
from test_ai_routing import IDEAS, PARSE, Rig, add_local, cloud_id, db, describe, fakes, next_meal, pin_roles, ready, routed_settings, turn_on
from test_lab_photo import GOOD, read
from app.ai import route_choice as RC
from app.main import create_app

SWITCH = "ai.person_route_choice"


@pytest.fixture
def two(tmp_path, foods_json) -> Iterator[Two]:
    """The admin's routing: photos and lab reports local; meal ideas, describe a meal and Ask in the cloud."""
    yield from start_two(both(tmp_path, foods_json))


@pytest.fixture
def added(tmp_path, foods_json) -> Iterator[Rig]:
    """The environment's OpenAI provider (cloud) and an Ollama an admin added on a private host (it can be deleted)."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        yield Rig(c, add_local(c), cloud_id(c))


def switch(client: TestClient, on: bool = True) -> None:
    r = client.patch("/api/admin/settings", json={SWITCH: on})
    assert r.status_code == 200, r.text


def user_id(admin: TestClient, username: str) -> int:
    return next(u["id"] for u in admin.get("/api/admin/users").json()["users"] if u["username"] == username)


def tick(admin: TestClient, username: str, on: bool = True):
    return admin.patch(f"/api/admin/users/{user_id(admin, username)}", json={"can_choose_ai": on})


def choose(client: TestClient, **features: str):
    return client.put("/api/me/ai/route-choice", json=features)


def store_directly(client: TestClient, uid: int, **features: str) -> None:
    """A stored choice that never went through the route (an old value, or a hand-edited database)."""
    conn = sqlite_row_conn(client)
    try:
        client.app.state.ai.store.set_user(conn, uid, RC.SETTING, {**{f: "default" for f in RC.FEATURES}, **features})
        conn.commit()
    finally:
        conn.close()


def agree_now(client: TestClient) -> None:
    """Targets set, opted in, and agreed (through the consent route) to the provider each feature resolves to now."""
    assert client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    assert client.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    for route in client.get("/api/ai/status").json()["routes"].values():
        if route["runs_on"] is not None and route["consent"] is None:
            r = client.post("/api/ai/consent", json={"provider_id": route["runs_on"]["id"], "purpose": route["purpose"]})
            assert r.status_code == 200, r.text


def where(client: TestClient, feature: str) -> dict[str, Any]:
    return client.get("/api/ai/status").json()["routes"][feature]


# --------------------------------------------------------------------------- #
# The switch and the tick
# --------------------------------------------------------------------------- #


def test_with_the_switch_off_nothing_changes(two):
    c = two.client
    agree_now(c)
    assert tick(c, "admin").status_code == 200  # the tick alone does nothing
    assert c.get("/api/me/ai").json()["route_choice"] is None
    refused = choose(c, describe="local")
    assert refused.status_code == 403 and refused.json()["detail"] == RC.NOT_ALLOWED
    store_directly(c, 1, describe="local", meal_ideas="local")
    hosts = servers(cloud=[chat(PARSE), chat(IDEAS)])
    with attached(c.app, hosts):
        assert describe(c).json()["provider"]["id"] == two.cloud  # the admin's route, as before
        assert next_meal(c).json()["provider"]["id"] == two.cloud
    assert hosts.requests("gpu.lan") == []
    assert where(c, "describe")["chosen"] is None


def test_without_the_tick_the_choice_is_refused_and_a_stored_one_ignored(two):
    c = two.client
    agree_now(c)
    switch(c)
    assert c.get("/api/me/ai").json()["route_choice"] is None
    assert choose(c, describe="local").status_code == 403
    store_directly(c, 1, describe="local")
    hosts = servers(cloud=[chat(PARSE)])
    with attached(c.app, hosts):
        assert describe(c).json()["provider"]["id"] == two.cloud
    assert hosts.requests("gpu.lan") == []


def test_taking_the_tick_or_the_switch_away_counts_from_the_next_request_and_keeps_the_choice(two):
    c = two.client
    agree_now(c)
    switch(c)
    assert tick(c, "admin").status_code == 200
    assert choose(c, describe="local").status_code == 200
    agree_now(c)
    hosts = servers(gpu=[chat(PARSE), chat(PARSE)], cloud=[chat(PARSE), chat(PARSE)])
    with attached(c.app, hosts):
        assert describe(c).json()["provider"]["id"] == two.local
        assert tick(c, "admin", False).status_code == 200
        assert describe(c).json()["provider"]["id"] == two.cloud  # at once: back on the admin's route
        assert c.get("/api/me/ai").json()["route_choice"] is None
        assert tick(c, "admin").status_code == 200
        assert describe(c).json()["provider"]["id"] == two.local  # kept: the choice applies again
        switch(c, False)
        assert describe(c).json()["provider"]["id"] == two.cloud
    assert stored_choice(c, 1)["describe"] == "local"


def sqlite_row_conn(client: TestClient) -> sqlite3.Connection:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def stored_choice(client: TestClient, uid: int) -> dict[str, str]:
    conn = sqlite_row_conn(client)
    try:
        return RC.stored(conn, client.app.state.ai.store, uid)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Each feature goes where the person chose
# --------------------------------------------------------------------------- #


def test_local_and_cloud_resolve_per_feature(two):
    c = two.client
    agree_now(c)
    switch(c)
    tick(c, "admin")
    view = c.get("/api/me/ai").json()["route_choice"]
    assert view["choices"] == {f: "default" for f in RC.FEATURES}
    assert view["local"]["host"].startswith("gpu.lan")
    assert view["cloud"]["host"].startswith("litellm.lan")
    assert [f["feature"] for f in view["features"]] == list(RC.FEATURES)  # no lab report photos
    r = choose(c, describe="local", chat="local", photos="cloud")
    assert r.status_code == 200, r.text
    assert r.json()["route_choice"]["choices"] == {"photos": "cloud", "meal_ideas": "default", "describe": "local", "chat": "local",
                                                   "recipes": "default"}
    agree_now(c)
    hosts = servers(gpu=[chat(PARSE), step_answer("Oatmeal is a fine breakfast.")], cloud=[chat(IDEAS)])
    with attached(c.app, hosts):
        assert describe(c).json()["provider"]["id"] == two.local
        assert ask(c, "is oatmeal ok for breakfast").json()["provider"]["id"] == two.local
        assert next_meal(c).json()["provider"]["id"] == two.cloud  # "Server default" keeps the admin's route
    assert len(hosts.requests("gpu.lan")) == 2 and len(hosts.requests("litellm.lan")) == 1
    status = c.get("/api/ai/status").json()["routes"]
    assert status["describe"]["chosen"] == "local" and status["describe"]["role"] == "local"
    assert status["describe"]["text"].endswith("You chose this.")
    assert status["photos"]["chosen"] == "cloud" and status["photos"]["role"] == "cloud"
    assert status["meal_ideas"]["chosen"] is None and status["meal_ideas"]["route"] == "cloud"
    assert status["labs"]["chosen"] is None and status["labs"]["role"] == "local"
    # A chosen local AI is pinned to the private network like every local call.
    assert {scope for host, scope in hosts.connections if host == "gpu.lan"} == {"local"}


def test_a_chosen_feature_never_falls_back(tmp_path, foods_json):
    """"Local, then cloud" stays the admin's rule for Server default; a person who picked the local AI gets only the local AI."""
    for rig in start_two(both(tmp_path, foods_json), describe="local_then_cloud"):
        c = rig.client
        agree_now(c)
        switch(c)
        tick(c, "admin")
        assert where(c, "describe")["fallback"] is not None
        assert choose(c, describe="local").status_code == 200
        agree_now(c)
        assert where(c, "describe")["fallback"] is None
        hosts = servers(gpu=[chat({"status": "ok", "items": []}), chat({"status": "ok", "items": []})], cloud=[chat(PARSE)])
        with attached(c.app, hosts):
            describe(c)
        assert hosts.requests("litellm.lan") == []


# --------------------------------------------------------------------------- #
# What always stays: off, lab report photos, consent, the privacy filter, a person's own provider
# --------------------------------------------------------------------------- #


def test_the_admins_off_wins(two):
    c = two.client
    agree_now(c)
    switch(c)
    tick(c, "admin")
    assert choose(c, describe="local").status_code == 200
    assert c.put("/api/admin/ai-routing", json={"describe": "off"}).status_code == 200
    hosts = servers()
    with attached(c.app, hosts):
        off = describe(c)
    assert off.status_code == 503 and off.json()["reason"] == "feature_off"
    assert hosts.connections == []
    refused = choose(c, describe="cloud")
    assert refused.status_code == 409 and refused.json()["reason"] == "feature_off"
    assert choose(c, describe="default").status_code == 200  # going back to the admin's choice is always allowed
    feature = next(f for f in c.get("/api/me/ai").json()["route_choice"]["features"] if f["feature"] == "describe")
    assert feature["admin_off"] is True


def test_lab_report_photos_are_never_offered_stored_or_sent_to_the_cloud(two):
    c = two.client
    agree_now(c)
    switch(c)
    tick(c, "admin")
    for value in ("cloud", "local", "default"):
        refused = choose(c, labs=value)
        assert refused.status_code in (400, 422), refused.text
    assert "labs" not in c.get("/api/me/ai").json()["route_choice"]["choices"]
    refused = c.patch("/api/me/settings", json={RC.SETTING: {"labs": "cloud"}})
    assert refused.status_code == 403
    assert choose(c, **{f: "cloud" for f in RC.FEATURES}).status_code == 200
    agree_now(c)
    hosts = servers(gpu=[chat(GOOD)])
    with attached(c.app, hosts):
        r = read(c)
    assert r.status_code == 200 and r.json()["provider"]["id"] == two.local
    assert hosts.requests("litellm.lan") == []
    assert where(c, "labs")["chosen"] is None


def test_a_newly_chosen_cloud_ai_asks_for_consent_first(two):
    c = two.client
    ready(c, {two.local: ("photos", "labs")})  # agreed to the local AI only
    switch(c)
    tick(c, "admin")
    assert choose(c, photos="cloud").status_code == 200
    from test_vision_api import LABEL_ANSWER, photo

    hosts = servers(cloud=[chat(LABEL_ANSWER)])
    with attached(c.app, hosts):
        asked = photo(c, "/api/vision/label")
        assert asked.status_code == 409 and asked.json()["consent_required"] is True
        consent = asked.json()["consent"]
        assert consent["provider_id"] == two.cloud and consent["host"].startswith("litellm.lan") and consent["local"] is False
        assert hosts.requests("litellm.lan") == []  # nothing left before the person agreed
        assert c.post("/api/ai/consent", json={"provider_id": two.cloud, "purpose": "photos"}).status_code == 200
        done = photo(c, "/api/vision/label")
    assert done.status_code == 200 and done.json()["provider"]["id"] == two.cloud
    assert hosts.requests("gpu.lan") == []


def test_the_privacy_filter_runs_when_a_person_picks_the_cloud(tmp_path, foods_json):
    for rig in start_two(both(tmp_path, foods_json), describe="local"):
        c = rig.client
        name_the_account(c)
        agree_now(c)
        switch(c)
        tick(c, "admin")
        assert choose(c, describe="cloud").status_code == 200
        agree_now(c)
        hosts = servers(cloud=[chat(PARSED)])
        with attached(c.app, hosts):
            dry = describe_text(c, MEAL, dry_run="true").json()
            r = describe_text(c, MEAL)
        assert r.status_code == 200, r.text
        assert dry["privacy_filter"]["on"] is True and dry["privacy_filter"]["replaced"] == 3
        sent = json.dumps(hosts.by_host["litellm.lan"].bodies())
        for word in ("Margaret", "Tom", "30 Oct 2026"):
            assert word not in sent
        assert hosts.requests("gpu.lan") == []
        assert [i["text"] for i in r.json()["items"]] == ["Margaret's lentil soup", "2 slices of toast from Tom"]


def describe_text(client: TestClient, text: str, **params: Any):
    return client.post("/api/ai/parse-meal", json={"text": text}, params=params)


def test_a_persons_own_provider_still_wins(two):
    c = two.client
    agree_now(c)
    switch(c)
    tick(c, "admin")
    assert choose(c, describe="local").status_code == 200
    assert c.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "api_key": OWN_KEY}).status_code == 200
    own = c.get("/api/me/ai").json()["own"]["id"]
    assert c.patch("/api/me/ai", json={"provider": "own"}).status_code == 200
    assert c.post("/api/ai/consent", json={"provider_id": own, "purpose": "text"}).status_code == 200
    assert c.get("/api/me/ai").json()["route_choice"]["own_wins"] is True
    hosts = servers()
    hosts.by_host["api.openai.com"] = FakeProvider([chat(PARSE)])
    with attached(c.app, hosts):
        r = describe(c)
    assert r.status_code == 200 and r.json()["provider"]["id"] == own
    assert hosts.requests("gpu.lan") == [] and hosts.requests("litellm.lan") == []
    assert where(c, "describe")["role"] == "own" and where(c, "describe")["chosen"] is None


# --------------------------------------------------------------------------- #
# Only an AI that exists; an AI that goes away
# --------------------------------------------------------------------------- #


def test_only_an_ai_that_exists_can_be_chosen(tmp_path, foods_json):
    for rig in start_two(cloud_only(tmp_path, foods_json), photos="cloud", labs="local"):
        c = rig.client
        agree_now(c)
        switch(c)
        tick(c, "admin")
        view = c.get("/api/me/ai").json()["route_choice"]
        assert view["local"] is None and view["cloud"] is not None
        refused = choose(c, describe="local")
        assert refused.status_code == 400 and refused.json()["reason"] == "no_local_provider"
        assert "no local AI" in refused.json()["detail"]
        assert choose(c, describe="cloud").status_code == 200


def test_a_chosen_ai_that_goes_away_leaves_the_feature_off_not_moved(tmp_path, foods_json):
    """The local AI is chosen, then it stops being private (AI_PRIVATE_HOSTS changed): nothing goes to the cloud instead."""
    for rig in start_two(both(tmp_path, foods_json)):
        c = rig.client
        agree_now(c)
        switch(c)
        tick(c, "admin")
        assert choose(c, describe="local").status_code == 200
        agree_now(c)
        conn = sqlite3.connect(c.app.state.settings.db_path)
        try:
            conn.execute("UPDATE ai_providers SET enabled = 0 WHERE id = ?", (rig.local,))
            conn.commit()
        finally:
            conn.close()
        hosts = servers(cloud=[chat(PARSE)])
        with attached(c.app, hosts):
            r = describe(c)
        assert r.status_code == 503 and r.json()["reason"] == "provider_disabled"
        assert hosts.requests("litellm.lan") == []
        assert c.get("/api/me/ai").json()["route_choice"]["local"] is None  # no longer offered


def test_a_chosen_ai_that_is_deleted_leaves_the_feature_off_and_says_why(added):
    """An admin-added local AI is chosen, then deleted: the feature is off for this person with a plain reason; nothing goes to
    the cloud AI on its own, and "Server default" brings the admin's route back."""
    c = added.client
    pin_roles(added)
    c.put("/api/admin/ai-routing", json={"describe": "cloud"})
    agree_now(c)
    switch(c)
    tick(c, "admin")
    assert choose(c, describe="local").status_code == 200
    agree_now(c)
    assert c.delete(f"/api/admin/ai-providers/{added.local}").status_code == 204
    local, cloud = fakes(cloud_answers=(chat(PARSE),))
    with attach_routed(c.app, local=local, cloud=cloud):
        off = describe(c)
        assert off.status_code == 503 and off.json()["reason"] == "chosen_role_missing"
        assert "Choose again in Settings" in off.json()["detail"]
        line = where(c, "describe")
        assert line["chosen"] == "local" and line["text"].startswith("You chose an AI that is not set up")
        assert cloud.requests == []
        assert choose(c, describe="default").status_code == 200
        assert describe(c).json()["provider"]["id"] == added.cloud
    assert local.requests == [] and cloud.calls == 1


# --------------------------------------------------------------------------- #
# Who may change what, and the audit log
# --------------------------------------------------------------------------- #


def test_only_admins_give_the_tick_and_each_change_is_audited(two):
    c = two.client
    sam = add_user(c)
    sam_id = user_id(c, "sam")
    refused = sam.patch(f"/api/admin/users/{sam_id}", json={"can_choose_ai": True})
    assert refused.status_code == 403
    assert sam.patch("/api/admin/users/1", json={"can_choose_ai": True}).status_code == 403
    users = {u["username"]: u for u in c.get("/api/admin/users").json()["users"]}
    assert users["sam"]["can_choose_ai"] is False and users["admin"]["can_choose_ai"] is False
    assert tick(c, "sam").status_code == 200
    assert tick(c, "sam").status_code == 200  # no change: no second row
    assert c.get("/api/admin/users").json()["users"][-1]["can_choose_ai"] is True
    rows = db(c, "SELECT actor_user_id, action, target_id, details_json FROM audit_log WHERE action = 'user.updated'")
    assert [(r["actor_user_id"], r["target_id"], json.loads(r["details_json"])) for r in rows] == [(1, str(sam_id), {"can_choose_ai": True})]
    assert c.patch(f"/api/admin/users/{sam_id}", json={"can_choose_ai": None}).status_code == 200  # null leaves it alone
    assert c.patch(f"/api/admin/users/{sam_id}", json={"can_choose_ai": "yes please"}).status_code in (400, 422)
    switch(c)
    agree_now(sam)
    assert choose(sam, describe="local").status_code == 200
    assert choose(sam, describe="local").status_code == 200  # the same again: nothing new to record
    events = sam.get("/api/me/activity").json()["events"]
    mine = [e for e in events if e["action"] == "ai.route_choice_changed"]
    assert [e["details"] for e in mine] == [{"feature": "describe", "old": "default", "new": "local"}]


def test_the_general_settings_route_cannot_set_the_choice(two):
    c = two.client
    switch(c)
    tick(c, "admin")
    r = c.patch("/api/me/settings", json={RC.SETTING: {"describe": "cloud"}})
    assert r.status_code == 403 and "Settings → AI features" in r.json()["detail"]
    assert stored_choice(c, 1)["describe"] == "default"


def test_one_persons_choice_never_changes_anothers(two):
    c = two.client
    sam = add_user(c)
    agree_now(c)
    agree_now(sam)
    switch(c)
    tick(c, "admin")
    tick(c, "sam")
    assert choose(c, describe="local").status_code == 200
    agree_now(c)
    hosts = servers(gpu=[chat(PARSE)], cloud=[chat(PARSE)])
    with attached(c.app, hosts):
        assert describe(c).json()["provider"]["id"] == two.local
        assert describe(sam).json()["provider"]["id"] == two.cloud  # sam keeps the admin's route
    assert sam.get("/api/me/ai").json()["route_choice"]["choices"]["describe"] == "default"
    assert where(sam, "describe")["chosen"] is None

