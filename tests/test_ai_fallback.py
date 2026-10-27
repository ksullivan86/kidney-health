"""Privacy tiers, tier 3: the route ``local_then_cloud`` ("local first, cloud only when the local answer fails"; docs/ai.md,
ARCHITECTURE "Privacy tiers", ROADMAP tier 3).

What is pinned down here:

* the route exists only for the structured features (photos, meal ideas, describe a meal); Ask and lab report photos refuse it
  (``PUT /api/admin/ai-routing``, ``routing.plan``, the settings, the environment), ``labs`` stays local-only exactly as it was;
* the cloud AI is sent the second request **only when the local answer fails the schema or the app's rules**; never when the
  local AI is unreachable, too slow, errors, is over quota or declines; never without the person's consent for the cloud host;
  never to a person's own provider;
* what the person is told (the line, the provider field, the consent sheet, "What will be sent?"), and what the AI activity log
  and the quota hold (two calls, two rows, two units);
* defaults and the upgrade rule do not change.

No network: every request ends in a fake provider (``ai_support.attach_routed``)."""
from __future__ import annotations

import sqlite3
from typing import Any, Iterator

import httpx2
import pytest

from ai_support import FakeProvider, attach_routed, chat
from conftest import HTTPS_URL, TestClient, add_user, sign_in
from test_ai_routes import DAY, OWN_KEY, TARGETS, _rerank_first_candidate
from test_ai_routing import (PARSE, PRIVATE_IP, Rig, add_local, cloud_id, db, describe, pin_roles, ready, route,
                             routed_settings, turn_on)
from test_vision_api import LABEL_ANSWER, LABEL_JPG, PLATE_ANSWER, PLATE_JPG, photo
from app.ai import config as K
from app.ai import features as F
from app.ai import routing as R
from app.ai.cache import AnswerCache
from app.main import create_app
from app.settings_registry import REGISTRY
from app.settings_store import SettingsStore

RULE = "The local AI's answer did not pass the app's checks, so the cloud AI (api.openai.com) answered."
BAD_JSON = "this is not json at all"
# Every idea the model names is a food the rules did not offer: the judge drops all of it (dropped_all).
NOT_CANDIDATES = {"status": "ok", "refusal": "none", "order": [{"ref": "zz9", "reason_codes": ["low_potassium"]}]}
URL_ITEM = {"status": "ok", "items": [{"text": "see http://evil.example/x", "search": "apple", "amount": 1, "unit": "serving"}]}


@pytest.fixture
def fb(tmp_path, foods_json) -> Iterator[Rig]:
    """A new server with a local AI (Ollama on a private host) and a cloud AI (OpenAI, the environment provider), every
    structured feature on ``local_then_cloud``, the person opted in and agreed to send text and photos to BOTH hosts."""
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        rig = Rig(c, add_local(c), cloud_id(c))
        pin_roles(rig)
        r = route(c, photos="local_then_cloud", meal_ideas="local_then_cloud", describe="local_then_cloud")
        assert r.status_code == 200, r.text
        ready(c, {rig.local: ("text", "photos"), rig.cloud: ("text", "photos")})
        yield rig


def rerank(client: TestClient, **params: Any):
    return client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY, "mode": "rerank"}, params=params)


def valid_local(**kw: Any) -> FakeProvider:
    return FakeProvider(route=_rerank_first_candidate, address=PRIVATE_IP)


def usage(client: TestClient) -> list[tuple[int, int]]:
    return [(r["provider_id"], r["requests"]) for r in db(client, "SELECT provider_id, SUM(requests) AS requests FROM ai_usage GROUP BY provider_id ORDER BY provider_id")]


def audit(client: TestClient) -> list[dict[str, Any]]:
    return list(reversed(client.get("/api/ai/audit").json()["events"]))  # oldest first


def cloud_consent(client: TestClient, rig: Rig, purpose: str = "text") -> None:
    assert client.delete(f"/api/ai/consent/{rig.cloud}", params={"purpose": purpose}).status_code == 204


# --------------------------------------------------------------------------- #
# The setting: which features take it
# --------------------------------------------------------------------------- #


def test_the_structured_features_take_the_route_and_ask_and_labs_refuse_it(fb):
    for feature in ("photos", "meal_ideas", "describe"):
        assert route(fb.client, **{feature: "local_then_cloud"}).status_code == 200
        assert route(fb.client, **{feature: "local"}).status_code == 200
    for feature in ("chat", "labs"):
        r = route(fb.client, **{feature: "local_then_cloud"})
        assert r.status_code == 400, (feature, r.text)
    status = {f["feature"]: f for f in fb.client.get("/api/admin/ai-routing").json()["features"]}
    assert status["chat"]["route"] == "local" and status["labs"]["route"] == "local"  # nothing changed
    assert all("local_then_cloud" in status[f]["allowed"] for f in ("photos", "meal_ideas", "describe"))
    assert "local_then_cloud" not in status["chat"]["allowed"] and "local_then_cloud" not in status["labs"]["allowed"]


def test_plan_refuses_the_route_for_ask_and_labs_with_a_reason(fb):
    state = fb.client.app.state
    conn = sqlite3.connect(state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        args = (conn, state.ai.store, state.settings, state.ai.policy)
        ok = R.plan(*args, features={"photos": "local_then_cloud", "meal_ideas": "local_then_cloud", "describe": "local_then_cloud"}, providers={})
        assert ok == {"ai.route.photos": "local_then_cloud", "ai.route.meal_ideas": "local_then_cloud", "ai.route.describe": "local_then_cloud"}
        with pytest.raises(R.RoutingError) as chat_err:
            R.plan(*args, features={"chat": "local_then_cloud"}, providers={})
        assert chat_err.value.status == 400 and chat_err.value.extra["reason"] == "no_fallback" and "several AI calls" in str(chat_err.value)
        with pytest.raises(R.RoutingError) as labs_err:
            R.plan(*args, features={"labs": "local_then_cloud"}, providers={})
        assert labs_err.value.status == 400 and labs_err.value.extra["reason"] == "local_only" and "never sent to a cloud AI" in str(labs_err.value)
    finally:
        conn.close()


def test_labs_stays_local_only_exactly_as_it_was():
    assert R.LOCAL_ONLY == ("labs",) and R.LOCAL_ONLY_ROUTES == ("local", "off")
    assert R.allowed_routes("labs") == ("local", "off") and R.FALLBACK_FEATURES == ("photos", "meal_ideas", "describe", "recipes")
    assert "chat" not in R.FALLBACK_FEATURES and "labs" not in R.FALLBACK_FEATURES
    assert R.allowed_routes("chat") == R.ROUTES and "local_then_cloud" not in R.ROUTES


def test_the_settings_and_the_environment_refuse_it_for_ask_and_labs(fb):
    for key in ("ai.route.chat", "ai.route.labs"):
        r = fb.client.patch("/api/admin/settings", json={key: "local_then_cloud"})
        assert r.status_code == 400, (key, r.text)
    for key in ("ai.route.photos", "ai.route.meal_ideas", "ai.route.describe"):
        assert fb.client.patch("/api/admin/settings", json={key: "local_then_cloud"}).status_code == 200
    for env in ("AI_ROUTE_CHAT", "AI_ROUTE_LABS"):
        with pytest.raises(Exception):
            SettingsStore(env={env: "local_then_cloud"}).env_value(REGISTRY[f"ai.route.{env.removeprefix('AI_ROUTE_').lower()}"])
    assert SettingsStore(env={"AI_ROUTE_PHOTOS": "local_then_cloud"}).env_value(REGISTRY["ai.route.photos"]) == (True, "local_then_cloud")


def test_a_stored_value_labs_would_never_accept_still_reads_local_only_and_never_falls_back(fb):
    conn = sqlite3.connect(fb.client.app.state.settings.db_path)
    conn.execute("INSERT OR REPLACE INTO instance_settings (key, value_json, updated_at) VALUES ('ai.route.labs', '\"local_then_cloud\"', 'now')")
    conn.execute("INSERT OR REPLACE INTO instance_settings (key, value_json, updated_at) VALUES ('ai.route.chat', '\"local_then_cloud\"', 'now')")
    conn.commit()
    conn.close()
    fb.client.app.state.settings_store.invalidate()
    routes = fb.client.get("/api/ai/status").json()["routes"]
    assert routes["labs"]["route"] == "local" and routes["labs"]["fallback"] is None and routes["chat"]["fallback"] is None
    assert routes["labs"]["role"] == "local" and routes["chat"]["role"] == "local"


def test_defaults_and_the_upgrade_rule_do_not_choose_the_route(tmp_path, foods_json):
    assert all(REGISTRY[f"ai.route.{f}"].default == "local" for f in R.FEATURES)
    with TestClient(create_app(routed_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:  # an upgraded server: one provider already
        sign_in(c)
        settings = c.get("/api/admin/settings").json()["settings"]
    assert {f: settings[f"ai.route.{f}"]["value"] for f in ("photos", "meal_ideas", "describe", "chat")} == {
        "photos": "local", "meal_ideas": "local", "describe": "local", "chat": "local"}  # a new server: the least-trusting default
    assert not any(settings[f"ai.route.{f}"]["value"] == "local_then_cloud" for f in R.FEATURES)


# --------------------------------------------------------------------------- #
# Resolution and what a person reads
# --------------------------------------------------------------------------- #


def test_both_roles_are_held_and_the_person_reads_one_line(fb):
    me = fb.client.get("/api/me/ai").json()["routing"]
    lines = {f["feature"]: f["text"] for f in me["features"]}
    assert lines["meal_ideas"] == ("Runs on your local AI (ollama.lan:11434); if its answer fails the app's checks, on the cloud AI (api.openai.com).")
    assert lines["chat"] == "Runs on your local AI (ollama.lan:11434)." and lines["labs"] == "Runs on your local AI (ollama.lan:11434)."
    status = fb.client.get("/api/ai/status").json()["routes"]["describe"]
    assert status["route"] == "local_then_cloud" and status["role"] == "local" and status["runs_on"]["id"] == fb.local
    assert status["fallback"]["runs_on"]["id"] == fb.cloud and status["fallback"]["consent"]["host"] == "api.openai.com"
    assert "fails the app's checks" in status["fallback"]["rule"]


def test_with_no_cloud_provider_it_behaves_as_local(fb):
    assert route(fb.client, cloud_provider=0).status_code == 200
    line = next(f["text"] for f in fb.client.get("/api/me/ai").json()["routing"]["features"] if f["feature"] == "photos")
    assert line == "Runs on your local AI (ollama.lan:11434)."
    cloud = FakeProvider([chat(PARSE)])
    with attach_routed(fb.client.app, local=FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), cloud=cloud):
        r = rerank(fb.client)
    assert r.status_code == 200 and r.json()["status"] == "error" and r.json()["reason"] == "no_json" and "cloud_fallback" not in r.json()
    assert cloud.requests == []


def test_with_no_local_provider_it_is_off_as_local_is(fb):
    assert route(fb.client, local_provider=0).status_code == 200
    r = rerank(fb.client)
    assert r.status_code == 503 and r.json()["reason"] == "no_local_provider"
    status = fb.client.get("/api/ai/status").json()["routes"]["meal_ideas"]
    assert status["available"] is False and status["fallback"] is None
    assert "Needs a local AI" in status["text"]


def test_a_person_with_their_own_provider_is_not_routed_and_is_never_a_fallback(fb):
    r = fb.client.put("/api/me/ai/provider", json={"preset": "openai", "model": "gpt-6-luna", "vision_model": "gpt-6-luna", "api_key": OWN_KEY})
    assert r.status_code == 200, r.text
    assert fb.client.patch("/api/me/ai", json={"provider": "own"}).status_code == 200
    line = next(f for f in fb.client.get("/api/me/ai").json()["routing"]["features"] if f["feature"] == "meal_ideas")
    assert line["text"].startswith("Runs on your own AI provider") and line["fallback"] is None
    own_id = fb.client.get("/api/ai/status").json()["routes"]["meal_ideas"]["runs_on"]["id"]
    assert own_id not in (fb.local, fb.cloud)
    assert fb.client.post("/api/ai/consent", json={"provider_id": own_id, "purpose": "text"}).status_code == 200
    local, cloud, own = valid_local(), FakeProvider(), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud, own=own):
        good = rerank(fb.client).json()
    assert good["provider"]["id"] == own_id and own.calls == 1 and local.requests == [] and cloud.requests == []  # no local first
    own = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)])
    fb.client.app.state.ai.answers = AnswerCache()  # the good answer is kept for ten minutes
    with attach_routed(fb.client.app, local=local, cloud=cloud, own=own):
        bad = rerank(fb.client).json()
    assert bad["status"] == "error" and bad["provider"]["id"] == own_id and "cloud_fallback" not in bad
    assert local.requests == [] and cloud.requests == []  # their own provider failing does not send the question anywhere else


def test_a_person_who_cannot_use_the_shared_provider_gets_no_fallback(fb):
    state = fb.client.app.state
    conn = sqlite3.connect(state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        res = R.resolve_feature(conn, state.ai.store, state.keyring, state.settings, state.ai.policy, user_id=1, can_use_shared=False,
                                feature="meal_ideas", require_opt_in=False)
    finally:
        conn.close()
    assert res.cfg is None and res.fallback is None and res.reason == "not_allowed"


# --------------------------------------------------------------------------- #
# The rule: only a failed schema or a failed rule check asks the cloud
# --------------------------------------------------------------------------- #


def test_a_good_local_answer_never_reaches_the_cloud(fb):
    local, cloud = valid_local(), FakeProvider()
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = rerank(fb.client)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["provider"]["id"] == fb.local
    assert local.calls == 1 and cloud.requests == []
    assert "cloud_fallback" not in body  # exactly the answer route "local" gives
    assert usage(fb.client) == [(fb.local, 1)]


def test_an_answer_that_fails_the_schema_goes_to_the_cloud_once_and_says_so(fb):
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = rerank(fb.client)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["provider"]["id"] == fb.cloud and body["provider"]["host"] == "api.openai.com"  # which AI answered
    assert body["cloud_fallback"]["message"] == RULE and body["cloud_fallback"]["used"] is True and body["cloud_fallback"]["answered"] is True
    assert body["cloud_fallback"]["local"]["id"] == fb.local and body["cloud_fallback"]["cloud"]["id"] == fb.cloud
    assert local.calls == 2 and cloud.calls == 1  # the local AI got its one repair turn; the cloud AI was asked once
    assert cloud.bodies()[0]["model"] == "gpt-6-luna"


def test_an_answer_the_rules_reject_goes_to_the_cloud(fb):
    local, cloud = FakeProvider([chat(NOT_CANDIDATES)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = rerank(fb.client)
    body = r.json()
    assert body["status"] == "ok" and body["provider"]["id"] == fb.cloud and body["cloud_fallback"]["message"] == RULE
    assert local.calls == 1 and cloud.calls == 1


def test_the_cloud_gets_exactly_what_route_cloud_would_send(fb):
    local, cloud = FakeProvider([chat(NOT_CANDIDATES)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        assert rerank(fb.client).json()["provider"]["id"] == fb.cloud
        via_fallback = cloud.bodies()[0]
        fb.client.app.state.ai.answers = AnswerCache()  # the kept answer must not hide the second request
        assert route(fb.client, meal_ideas="cloud").status_code == 200
        assert rerank(fb.client).status_code == 200
        via_route = cloud.bodies()[1]
    assert via_fallback == via_route
    assert local.calls == 1  # route "cloud" never touches the local AI


def test_the_local_ai_being_unreachable_slow_or_erroring_never_reaches_the_cloud(fb):
    def refuse(request):
        return httpx2.ConnectError("refused", request=request)

    def slow(request):
        return httpx2.ReadTimeout("slow", request=request)

    cases = {"connect_failed": FakeProvider(route=refuse, address=PRIVATE_IP), "timeout": FakeProvider(route=slow, address=PRIVATE_IP),
             "http_5xx": FakeProvider([{"status": 500, "body": {}}, {"status": 502, "body": {}}], address=PRIVATE_IP),
             "http_401": FakeProvider([{"status": 401, "body": {"error": "no"}}], address=PRIVATE_IP)}
    for reason, local in cases.items():
        cloud = FakeProvider()
        with attach_routed(fb.client.app, local=local, cloud=cloud):
            r = rerank(fb.client)
        assert r.status_code == 200 and r.json()["status"] == "error", reason
        assert r.json()["reason"] == reason and "cloud_fallback" not in r.json() and cloud.requests == [], reason  # as with route "local"


def test_a_local_refusal_never_reaches_the_cloud(fb):
    refusal = chat(None, refusal="I can't help with that.")
    in_schema = chat({"status": "refused", "refusal": "outside_scope", "order": []})
    for answer in (refusal, in_schema):
        fb.client.app.state.ai.answers = AnswerCache()
        local, cloud = FakeProvider([answer], address=PRIVATE_IP), FakeProvider()
        with attach_routed(fb.client.app, local=local, cloud=cloud):
            r = rerank(fb.client)
        assert r.json()["status"] == "refused" and r.json()["provider"]["id"] == fb.local
        assert cloud.requests == [] and "cloud_fallback" not in r.json()


def test_a_model_that_says_nothing_fits_is_an_answer_not_a_failure(fb):
    nothing = chat({"status": "ok", "refusal": "no_fit", "ideas": []})
    local, cloud = FakeProvider([nothing], address=PRIVATE_IP), FakeProvider()
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = fb.client.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.json()["status"] == "no_fit" and cloud.requests == []


def test_a_local_ai_that_is_over_quota_never_reaches_the_cloud(fb):
    assert fb.client.patch("/api/admin/settings", json={"ai.shared_daily_limit": 1}).status_code == 200
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        first = rerank(fb.client)  # takes the only unit; the answer fails; the cloud call has no unit left
        second = rerank(fb.client)  # over quota before anything is sent
    assert second.status_code == 429 and second.json()["reason"] == "quota_exhausted"
    assert first.json()["status"] == "error" and first.json()["provider"]["id"] == fb.local
    assert first.json()["cloud_fallback"]["used"] is False and first.json()["cloud_fallback"]["reason"] == "quota_exhausted"
    assert first.json()["cloud_fallback"]["message"].endswith("was not asked because today's shared AI calls are used up.")
    assert cloud.requests == [] and local.calls == 2  # (the second request never left; the first used its repair turn)


def test_without_consent_for_the_cloud_host_nothing_is_sent_and_the_local_failure_is_returned(fb):
    cloud_consent(fb.client, fb)
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = rerank(fb.client)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "error" and body["reason"] == "no_json" and body["provider"]["id"] == fb.local
    assert cloud.requests == []
    fallback = body["cloud_fallback"]
    assert fallback["used"] is False and fallback["answered"] is False and fallback["reason"] == "no_consent"
    assert fallback["message"] == ("The local AI's answer did not pass the app's checks. The cloud AI (api.openai.com) was not asked "
                                   "because you have not agreed to send this there.")
    assert fallback["consent"]["provider_id"] == fb.cloud and fallback["consent"]["host"] == "api.openai.com"  # the page can offer to agree
    assert usage(fb.client) == [(fb.local, 1)]
    row = audit(fb.client)[0]
    assert row["verdict_json"]["cloud_fallback"] == "no_consent"
    # Agreeing (the ordinary consent route) is all it takes; the next failure then asks the cloud.
    assert fb.client.post("/api/ai/consent", json={"provider_id": fb.cloud, "purpose": "text"}).status_code == 200
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        again = rerank(fb.client).json()
    assert again["provider"]["id"] == fb.cloud and again["cloud_fallback"]["message"] == RULE and cloud.calls == 1


def test_consent_for_another_purpose_or_another_person_does_not_count(fb):
    cloud_consent(fb.client, fb, "text")  # the photos consent for the cloud host stays
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        assert rerank(fb.client).json()["cloud_fallback"]["reason"] == "no_consent"
    assert cloud.requests == []
    assert fb.client.post("/api/ai/consent", json={"provider_id": fb.cloud, "purpose": "text"}).status_code == 200
    # a second person who has agreed to nothing is asked for the local consent first, and the first person's consent is not theirs
    sam = add_user(fb.client, "sam")
    assert sam.put("/api/profile", json={"targets": TARGETS}).status_code == 200 and sam.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    assert sam.post("/api/ai/consent", json={"provider_id": fb.local, "purpose": "text"}).status_code == 200  # local only
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        out = rerank(sam).json()
    assert out["status"] == "error" and out["cloud_fallback"]["reason"] == "no_consent" and cloud.requests == []
    sam.close()


def test_the_cloud_failing_too_returns_the_local_failure_and_says_the_cloud_was_asked(fb):
    local = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP)
    for cloud in (FakeProvider([chat(BAD_JSON), chat(BAD_JSON)]), FakeProvider([{"status": 401, "body": {"error": "no"}}])):
        local.answers = [chat(BAD_JSON), chat(BAD_JSON)]
        with attach_routed(fb.client.app, local=local, cloud=cloud):
            r = rerank(fb.client)
        body = r.json()
        assert body["status"] == "error" and body["provider"]["id"] == fb.local and body["cloud_fallback"]["used"] is True
        assert body["cloud_fallback"]["answered"] is False
        assert body["cloud_fallback"]["message"] == ("The local AI's answer did not pass the app's checks, so the cloud AI (api.openai.com) "
                                                     "was asked as well, but it gave no usable answer.")


def test_each_call_is_counted_and_logged_and_the_rows_link_up(fb):
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        body = rerank(fb.client).json()
    assert sorted(usage(fb.client)) == sorted([(fb.local, 1), (fb.cloud, 1)])
    assert fb.client.get("/api/me/ai").json()["remaining_today"] == 28  # two shared calls spent
    rows = audit(fb.client)
    assert [(r["provider_id"], r["status"]) for r in rows] == [(fb.local, "invalid"), (fb.cloud, "ok")]
    assert rows[0]["verdict_json"]["cloud_fallback"] == "asked" and rows[1]["verdict_json"]["fallback_for"] == rows[0]["id"]
    assert rows[0]["destination_host"].split(":")[0] == "ollama.lan" and rows[1]["destination_host"] == "api.openai.com"
    assert rows[0]["feature"] == rows[1]["feature"] == "next_meal:rerank"
    assert body["audit_id"] == rows[1]["id"] and body["cloud_fallback"]["local_audit_id"] == rows[0]["id"] == body["cloud_fallback"]["audit_id"] - 1


def test_the_cloud_answer_is_kept_for_ten_minutes_and_not_asked_again(fb):
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        first = rerank(fb.client).json()
        again = rerank(fb.client).json()
    assert first["cached"] is False and again["cached"] is True and again["provider"]["id"] == fb.cloud
    assert again["cloud_fallback"]["message"] == RULE and again["cloud_fallback"]["cached"] is True
    assert (local.calls, cloud.calls) == (2, 1)  # nothing was sent again, to either AI
    # withdrawing the consent for the cloud host drops it: an answer is never shown again without consent
    cloud_consent(fb.client, fb)
    assert len(fb.client.app.state.ai.answers) == 0


def test_an_answer_kept_from_route_cloud_is_not_shown_as_a_fallback_and_the_other_way_round(fb):
    local, cloud = valid_local(), FakeProvider(route=_rerank_first_candidate)
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        assert route(fb.client, meal_ideas="cloud").status_code == 200
        via_cloud = rerank(fb.client).json()
        assert route(fb.client, meal_ideas="local_then_cloud").status_code == 200
        via_local = rerank(fb.client).json()  # the kept cloud answer belongs to route "cloud": the local AI is asked
    assert via_cloud["provider"]["id"] == fb.cloud and via_local["provider"]["id"] == fb.local and via_local["cached"] is False
    assert "cloud_fallback" not in via_local and (local.calls, cloud.calls) == (1, 1)
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider(route=_rerank_first_candidate)
    fb.client.app.state.ai.answers = AnswerCache()
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        assert rerank(fb.client).json()["cloud_fallback"]["message"] == RULE  # kept as a fallback answer
        assert route(fb.client, meal_ideas="cloud").status_code == 200
        plain = rerank(fb.client).json()  # route "cloud": its own question, not the fallback's kept answer
    assert plain["cached"] is False and "cloud_fallback" not in plain and cloud.calls == 2


def test_settings_says_whether_the_person_agreed_to_the_cloud_ai_and_carries_the_sheet(fb):
    def lines():
        return {f["feature"]: f for f in fb.client.get("/api/me/ai").json()["routing"]["features"]}

    assert lines()["meal_ideas"]["fallback"]["given"] is True and lines()["chat"]["fallback"] is None and lines()["labs"]["fallback"] is None
    cloud_consent(fb.client, fb, "text")
    after = lines()
    assert after["meal_ideas"]["fallback"]["given"] is False and after["describe"]["fallback"]["given"] is False
    assert after["photos"]["fallback"]["given"] is True  # photos are agreed separately
    request = after["meal_ideas"]["fallback"]["request"]
    assert request["provider_id"] == fb.cloud and request["host"] == "api.openai.com" and request["purpose"] == "text"
    assert request["as_fallback"] is True and request["rule"] == K.FALLBACK_RULE and "fallback" not in request
    assert fb.client.post("/api/ai/consent", json={"provider_id": request["provider_id"], "purpose": request["purpose"]}).status_code == 200
    assert lines()["meal_ideas"]["fallback"]["given"] is True and lines()["describe"]["fallback"]["given"] is True


# --------------------------------------------------------------------------- #
# Describe a meal and photos
# --------------------------------------------------------------------------- #


def test_describe_falls_back_on_a_failed_schema_and_on_items_the_text_policy_drops(fb):
    for bad in ([chat(BAD_JSON), chat(BAD_JSON)], [chat(URL_ITEM)]):
        local, cloud = FakeProvider(bad, address=PRIVATE_IP), FakeProvider([chat(PARSE)])
        with attach_routed(fb.client.app, local=local, cloud=cloud):
            r = describe(fb.client)
        body = r.json()
        assert r.status_code == 200 and body["status"] == "ok" and body["provider"]["id"] == fb.cloud and body["items"]
        assert body["cloud_fallback"]["message"] == RULE and cloud.calls == 1
    local, cloud = FakeProvider([chat(PARSE)], address=PRIVATE_IP), FakeProvider()
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        good = describe(fb.client).json()
    assert good["provider"]["id"] == fb.local and "cloud_fallback" not in good and cloud.requests == []


def test_describe_that_the_local_ai_cannot_reach_does_not_ask_the_cloud(fb):
    local, cloud = FakeProvider(route=lambda r: httpx2.ConnectError("x", request=r), address=PRIVATE_IP), FakeProvider([chat(PARSE)])
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        body = describe(fb.client).json()
    assert body["status"] == "error" and cloud.requests == []


def test_photos_fall_back_on_a_failed_schema_with_the_same_photo(fb):
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider([chat(LABEL_ANSWER)])
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = photo(fb.client, "/api/vision/label")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["provider"]["id"] == fb.cloud and body["cloud_fallback"]["message"] == RULE
    assert local.calls == 2 and cloud.calls == 1
    assert cloud.bodies()[0]["model"] == "gpt-6-luna" and local.bodies()[0]["model"] == "llava"  # each AI's own vision model
    sent = lambda p: p.bodies()[0]["messages"][-1]["content"][-1]["image_url"]["url"] if isinstance(p.bodies()[0]["messages"][-1]["content"], list) else None  # noqa: E731
    assert sent(local) == sent(cloud)  # the same photo


def test_a_plate_photo_falls_back_and_a_local_error_does_not(fb):
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider([chat(PLATE_ANSWER)])
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = photo(fb.client, "/api/vision/plate", PLATE_JPG)
    assert r.status_code == 200 and r.json()["provider"]["id"] == fb.cloud and r.json()["cloud_fallback"]["message"] == RULE
    local, cloud = FakeProvider(route=lambda req: httpx2.ConnectError("x", request=req), address=PRIVATE_IP), FakeProvider([chat(PLATE_ANSWER)])
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = photo(fb.client, "/api/vision/plate", PLATE_JPG)
    assert r.status_code == 502 and r.json()["reason"] == "connect_failed" and cloud.requests == [] and "cloud_fallback" not in r.json()


def test_a_photo_that_fails_on_both_says_the_cloud_was_asked(fb):
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider([chat(BAD_JSON), chat(BAD_JSON)])
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = photo(fb.client, "/api/vision/label")
    assert r.status_code == 502 and "so the cloud AI (api.openai.com) was asked as well" in r.json()["detail"]
    assert r.json()["cloud_fallback"]["used"] is True


def test_a_cloud_without_a_vision_model_is_no_fallback_for_photos(tmp_path, foods_json):
    with TestClient(create_app(routed_settings(tmp_path, foods_json, vision_model=None)), base_url=HTTPS_URL) as c:
        sign_in(c)
        turn_on(c)
        rig = Rig(c, add_local(c), cloud_id(c))
        pin_roles(rig)
        assert route(c, photos="local_then_cloud", meal_ideas="local_then_cloud").status_code == 200
        ready(c, {rig.local: ("text", "photos"), rig.cloud: ("text", "photos")})
        local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider([chat(LABEL_ANSWER)])
        with attach_routed(c.app, local=local, cloud=cloud):
            r = photo(c, "/api/vision/label")
        assert r.status_code == 502 and "cloud_fallback" not in r.json() and cloud.requests == []
        dry = photo(c, "/api/vision/label", dry_run="true").json()
        assert "cloud_fallback" not in dry


def test_the_lab_report_photo_never_leaves_the_network_whatever_the_other_routes_say(fb):
    from test_lab_photo import GOOD

    assert fb.client.post("/api/ai/consent", json={"provider_id": fb.local, "purpose": "labs"}).status_code == 200
    local, cloud = FakeProvider([chat(BAD_JSON), chat(BAD_JSON)], address=PRIVATE_IP), FakeProvider([chat(GOOD)])
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        r = fb.client.post("/api/ai/read-lab-report", content=LABEL_JPG, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 502 and cloud.requests == [] and "cloud_fallback" not in r.json()
    assert fb.client.post("/api/ai/consent", json={"provider_id": fb.cloud, "purpose": "labs"}).status_code == 409


# --------------------------------------------------------------------------- #
# The consent sheet and "What will be sent?"
# --------------------------------------------------------------------------- #


def test_the_consent_sheet_names_both_hosts_and_says_when_the_cloud_one_is_used(fb):
    for purpose in ("text", "photos"):
        for pid in (fb.local, fb.cloud):
            fb.client.delete(f"/api/ai/consent/{pid}", params={"purpose": purpose})
    local, cloud = valid_local(), FakeProvider()
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        asked = rerank(fb.client)
        label = photo(fb.client, "/api/vision/label")
    assert asked.status_code == 409 and asked.json()["consent_required"] is True
    consent = asked.json()["consent"]
    assert consent["provider_id"] == fb.local and consent["host"].split(":")[0] == "ollama.lan" and consent["local"] is True
    assert consent["fallback"]["provider_id"] == fb.cloud and consent["fallback"]["host"] == "api.openai.com" and consent["fallback"]["given"] is False
    assert consent["fallback"]["rule"] == K.FALLBACK_RULE and "only if the local AI's answer fails the app's checks" in consent["fallback"]["rule"]
    assert label.status_code == 409 and label.json()["consent"]["fallback"]["host"] == "api.openai.com"
    assert local.requests == [] and cloud.requests == []  # nothing left before the person agreed
    # a feature that is not local_then_cloud has no second host on its sheet
    assert route(fb.client, meal_ideas="local").status_code == 200
    plain = rerank(fb.client).json()["consent"]
    assert "fallback" not in plain
    # each host is agreed to on its own
    assert route(fb.client, meal_ideas="local_then_cloud").status_code == 200
    assert fb.client.post("/api/ai/consent", json={"provider_id": fb.cloud, "purpose": "text"}).status_code == 200
    again = rerank(fb.client).json()["consent"]
    assert again["provider_id"] == fb.local and again["fallback"]["given"] is True
    assert fb.client.post("/api/ai/consent", json={"provider_id": 9999, "purpose": "text"}).status_code == 409


def test_what_will_be_sent_shows_the_local_request_and_that_a_second_may_go_to_the_cloud(fb):
    local, cloud = valid_local(), FakeProvider()
    with attach_routed(fb.client.app, local=local, cloud=cloud):
        dry = rerank(fb.client, dry_run="true").json()
        dry_describe = fb.client.post("/api/ai/parse-meal", params={"dry_run": "true"}, json={"text": "an apple"}).json()
        dry_photo = photo(fb.client, "/api/vision/label", dry_run="true").json()
    assert local.requests == [] and cloud.requests == []  # nothing is sent by looking
    for shown in (dry, dry_describe, dry_photo):
        assert shown["dry_run"] is True and shown["host"].split(":")[0] == "ollama.lan" and shown["provider"]["local"] is True
        second = shown["cloud_fallback"]
        assert second["host"] == "api.openai.com" and second["consent"] is True and second["model"] == "gpt-6-luna"
        assert "only if the local AI's answer fails the app's checks" in second["message"] and second["message"].count("api.openai.com") == 1
        assert second["body"]["model"] == "gpt-6-luna" and shown["body"]["model"] != "gpt-6-luna"
    # the second request is what route "cloud" would send
    assert route(fb.client, meal_ideas="cloud").status_code == 200
    plain = rerank(fb.client, dry_run="true").json()
    assert plain["body"] == dry["cloud_fallback"]["body"] and "cloud_fallback" not in plain
    # without consent for the cloud host the dry run says it would not be sent
    assert route(fb.client, meal_ideas="local_then_cloud").status_code == 200
    cloud_consent(fb.client, fb)
    unsent = rerank(fb.client, dry_run="true").json()["cloud_fallback"]
    assert unsent["consent"] is False and "You have not agreed to send this to that host, so it would not be sent." in unsent["message"]


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #


def test_judge_rejected_is_only_the_apps_own_rejection():
    assert F.judge_rejected({"status": "dropped_all"}) is True
    assert F.judge_rejected({"status": "ok", "items": [], "dropped": [{"index": 0, "reason": "text_policy:url"}]}) is True
    for verdict in ({"status": "ok", "items": [{"text": "x"}], "dropped": []}, {"status": "ok", "items": [], "dropped": []},
                    {"status": "refused"}, {"status": "no_fit"}, {"status": "not_a_label"}, {"status": "unreadable"}, {"status": "no_food", "items": []},
                    {"status": "error", "reason": "judge_failed"}, {"status": "ok", "order": []}):
        assert F.judge_rejected(verdict) is False, verdict


def test_the_dry_run_of_a_prepared_call_without_a_fallback_is_unchanged():
    from ai_support import make_cfg

    prep = F.prepare_parse_meal(make_cfg("openai"), "an apple", search=lambda q: [])
    assert prep.cloud is None and "cloud_fallback" not in prep.dry_run("test")
    prep.cloud = F.prepare_parse_meal(make_cfg("openai", model="other"), "an apple", search=lambda q: [])
    shown = prep.dry_run("test", cloud_consent=None)
    assert shown["cloud_fallback"]["consent"] is None and shown["cloud_fallback"]["model"] == "other"
