"""``POST /api/ai/chat``, the Ask screen's back end (``app/ai/chat.py`` and ``app/ai/routes.py``; docs/dev/plans/
assistant-step2.md; ARCHITECTURE "Ask chat").

Covered: the switch, sign-in and consent; the rules answering a low or an emergency without the model; the JSON step
loop with a scripted fake provider (a tool call, its result in the next request, the answer); unknown tools and bad
arguments; the six-call limit; one unit of quota and one activity row per model call; two people never seeing each
other's data; the dose and number checks on the way out; what the prompt and the activity log hold (no identity, no
message text). No network."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, attach, chat
from conftest import DAY, HTTPS_URL, TestClient, add_user, log_food, make_settings, sign_in
from test_ai_routes import TARGETS, ai_settings, enable
from app.main import create_app

WITHHELD_DOSE = "This answer was not shown because it touched on medicine or insulin doses. Ask your care team about doses."
WITHHELD_NUMBER = "The assistant's answer had a number the app did not work out, so it is not shown. Here are the app's own numbers."
UNFINISHED = "The assistant could not finish; here are the app's numbers."
MARKER = "zebra-marker-4417"


def step_call(tool: str, **arguments: Any) -> dict[str, Any]:
    return chat({"call": {"tool": tool, "arguments": arguments}})


def step_answer(text: str) -> dict[str, Any]:
    return chat({"answer": text})


def ask(client: TestClient, text: str = "what is left today", *, history: tuple[dict[str, str], ...] = (), **params: Any):
    body = {"messages": [*history, {"role": "user", "text": text}]}
    return client.post("/api/ai/chat", json=body, params=params)


def become_ready(client: TestClient, *, targets: bool = True, consent: bool = True, **prefs: Any) -> int:
    """Targets set, opted in, consent for the chat given; returns the provider id."""
    if targets:
        assert client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    assert client.patch("/api/me/ai", json={"opt_in": True, **prefs}).status_code == 200
    pid = client.get("/api/ai/status").json()["provider"]["id"]
    if consent:
        r = client.post("/api/ai/consent", json={"provider_id": pid, "purpose": "chat"})
        assert r.status_code == 200, r.text
    return pid


@pytest.fixture
def ask_client(tmp_path, foods_json) -> Iterator[TestClient]:
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True})
        become_ready(c)
        yield c


@pytest.fixture
def ask_two(ask_client: TestClient) -> tuple[TestClient, TestClient]:
    sam = add_user(ask_client)
    become_ready(sam)
    return ask_client, sam


def remaining(client: TestClient) -> int:
    return client.get("/api/ai/status").json()["remaining_today"]


def db_rows(client: TestClient, table: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(client.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Availability: the switch, sign-in, consent
# --------------------------------------------------------------------------- #


def test_chat_is_404_while_the_switch_is_off_even_with_ai_on(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c)
        become_ready(c, consent=False)
        assert c.get("/api/admin/settings").json()["settings"]["ai.chat_enabled"]["value"] is False
        with attach(c.app, FakeProvider()) as provider:
            r = ask(c)
            assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
            assert c.post("/api/ai/chat", json={}).status_code == 404  # before the body is looked at
            assert ask(c, "I feel low").status_code == 404  # not even the rules answer: the Ask screen is not there
            assert provider.calls == 0
        status = c.get("/api/ai/status").json()
        assert status["features"]["chat"] is False and status["features"]["next_meal"] is True


def test_chat_is_404_while_ai_is_off_and_the_status_follows_the_switch(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.post("/api/ai/chat", json={"messages": [{"role": "user", "text": "hi"}]}).status_code == 404
        enable(c)
        become_ready(c, consent=False)
        assert c.get("/api/ai/status").json()["features"]["chat"] is False
        enable(c, **{"ai.chat_enabled": True})
        assert c.get("/api/ai/status").json()["features"]["chat"] is True


def test_chat_needs_a_signed_in_person(anon_client):
    assert anon_client.post("/api/ai/chat", json={"messages": [{"role": "user", "text": "hi"}]}).status_code == 401


def test_the_admin_switch_is_a_registered_setting_with_an_env_name():
    from app import settings_registry

    definition = settings_registry.REGISTRY["ai.chat_enabled"]
    assert (definition.scope, definition.default, definition.env) == ("instance", False, "AI_CHAT_ENABLED")
    assert "ai.chat_enabled" in settings_registry.NO_SIGNIN_ENV_ONLY


def test_the_chat_needs_its_own_consent_and_the_409_says_what_would_be_sent(ask_client):
    c = ask_client
    pid = c.get("/api/ai/status").json()["provider"]["id"]
    assert c.delete(f"/api/ai/consent/{pid}", params={"purpose": "chat"}).status_code == 204
    for purpose in ("text", "photos"):  # the other purposes do not cover the chat
        assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose}).status_code == 200
    with attach(c.app, FakeProvider()) as provider:
        r = ask(c)
        assert r.status_code == 409 and r.json()["consent_required"] is True
        assert r.json()["consent"]["purpose"] == "chat" and r.json()["consent"]["provider_id"] == pid
        assert provider.calls == 0
        assert c.get("/api/ai/status").json()["consent"]["chat"] is None
    assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": "chat"}).status_code == 200
    assert c.get("/api/ai/status").json()["consent"]["chat"]["host"]
    with attach(c.app, FakeProvider([step_answer("Fine.")])):
        assert ask(c).json()["kind"] == "answer"


def test_the_chat_consent_is_listed_and_can_be_withdrawn_on_its_own(ask_client):
    c = ask_client
    mine = c.get("/api/me/ai").json()["consents"]
    assert [x["purpose"] for x in mine] == ["chat"]
    pid = mine[0]["provider_id"]
    assert c.delete(f"/api/ai/consent/{pid}", params={"purpose": "chat"}).status_code == 204
    assert c.get("/api/me/ai").json()["consents"] == []


def test_a_person_who_has_not_opted_in_gets_the_usual_503(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True})
        with attach(c.app, FakeProvider()) as provider:
            r = ask(c)
            assert r.status_code == 503 and r.json()["reason"] == "not_opted_in" and provider.calls == 0


def test_the_body_is_checked(ask_client):
    c = ask_client
    ok = {"role": "user", "text": "hi"}
    assert c.post("/api/ai/chat", json={"messages": []}).status_code == 400
    assert c.post("/api/ai/chat", json={"messages": [{"role": "assistant", "text": "x"}]}).status_code == 400  # last is the person's
    assert c.post("/api/ai/chat", json={"messages": [{"role": "user", "text": ""}]}).status_code == 400
    assert c.post("/api/ai/chat", json={"messages": [{"role": "user", "text": "x" * 2001}]}).status_code == 400
    assert c.post("/api/ai/chat", json={"messages": [{"role": "system", "text": "x"}]}).status_code == 400
    assert c.post("/api/ai/chat", json={"messages": [ok] * 21}).status_code == 400
    assert c.post("/api/ai/chat", json={"messages": [ok], "extra": 1}).status_code == 400
    assert c.post("/api/ai/chat", json={"messages": [{**ok, "id": 1}]}).status_code == 400
    with attach(c.app, FakeProvider([step_answer("A."), step_answer("B.")])):
        assert c.post("/api/ai/chat", json={"messages": [ok] * 20}).status_code == 200
        assert c.post("/api/ai/chat", json={"messages": [{"role": "user", "text": "x" * 2000}]}).status_code == 200
    only_control = c.post("/api/ai/chat", json={"messages": [{"role": "user", "text": "​​"}]})
    assert only_control.status_code == 400 and "empty" in only_control.json()["detail"]


# --------------------------------------------------------------------------- #
# Rules first: no model call
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", ["I feel shaky and low", "my sugar is 3.2", "bg 62 mg/dL", "I think I'm going low"])
def test_low_wording_gets_the_treating_a_low_card_and_the_model_is_not_called(ask_client, text):
    c = ask_client
    assert c.patch("/api/me/settings", json={"guidance": {"hypo_dose_g": 20}}).status_code == 200
    before = remaining(c)
    with attach(c.app, FakeProvider()) as provider:
        r = ask(c, text)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "treat_low" and body["text"] == "Treat the low first. When you feel better, ask again."
        [card] = body["cards"]
        assert card["title"] == "Treating a low" and "take 20 g of fast carbs now" in card["lines"][0]  # the person's own grams
        assert card["url"] == "/learn/t1d/treating-a-low/" and "full_url" not in card
        assert body["ai_called"] is False and body["provider"] is None and body["model_calls"] == 0
        assert body["numbers"] == [] and body["label"]["source"] == "app"
        assert provider.requests == []  # nothing reached the provider, not even a lookup
    assert remaining(c) == before  # no quota spent
    assert db_rows(c, "ai_audit") == []  # and nothing in the activity log


def test_emergency_wording_gets_get_help_now_and_a_low_in_the_same_message_keeps_its_card(ask_client):
    c = ask_client
    with attach(c.app, FakeProvider()) as provider:
        help_only = ask(c, "I have chest pain and can't breathe").json()
        assert help_only["kind"] == "get_help_now" and [x["title"] for x in help_only["cards"]] == ["Get help now"]
        assert help_only["cards"][0]["url"] == "/learn/get-help-now/"
        both = ask(c, "I'm shaky and confused").json()
        assert both["kind"] == "get_help_now" and [x["title"] for x in both["cards"]] == ["Get help now", "Treating a low"]
        assert both["ai_called"] is False and provider.requests == []


def test_the_rules_answer_before_consent_and_before_the_provider_is_looked_at(tmp_path, foods_json):
    """A low is answered even when the person has not agreed to anything yet, and the answer never waits for the AI."""
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True})
        with attach(c.app, FakeProvider()) as provider:  # not opted in, no consent
            assert ask(c, "I feel low").json()["kind"] == "treat_low"
            assert provider.requests == []


def test_a_low_in_the_dry_run_is_answered_not_previewed(ask_client):
    with attach(ask_client.app, FakeProvider()) as provider:
        body = ask(ask_client, "I feel shaky and low", dry_run="true").json()
        assert body["kind"] == "treat_low" and "dry_run" not in body and provider.requests == []


def test_food_talk_that_only_looks_like_a_low_is_not_stopped(ask_client):
    with attach(ask_client.app, FakeProvider([step_answer("Yes.")])) as provider:
        assert ask(ask_client, "low-fat yogurt with berries and low sodium soup").json()["kind"] == "answer"
        assert provider.calls == 1


def test_an_earlier_low_or_emergency_message_is_never_sent_to_the_model(ask_client):
    history = ({"role": "user", "text": "I went low an hour ago"},
               {"role": "assistant", "text": "Treat the low first. When you feel better, ask again."},
               {"role": "user", "text": "I felt faint"},
               {"role": "assistant", "text": "Get help now first. When you are safe, ask again."})
    with attach(ask_client.app, FakeProvider([step_answer("Rice fits.")])) as provider:
        body = ask(ask_client, "what can I eat now", history=history).json()
        assert body["kind"] == "answer"
        sent = json.dumps(provider.bodies()[0])
        assert "went low" not in sent and "faint" not in sent and "Treat the low" not in sent and "Get help now" not in sent
        assert "what can I eat now" in sent


# --------------------------------------------------------------------------- #
# The step loop
# --------------------------------------------------------------------------- #


def potassium_total(client: TestClient, day: str = DAY) -> int:
    return round(client.get("/api/log", params={"date": day}).json()["totals"]["potassium_mg"])


def test_the_model_calls_get_today_and_the_answer_is_checked_and_shown(ask_client):
    c = ask_client
    log_food(c, "banana", "breakfast")
    total = potassium_total(c)
    assert total > 0
    answer = f"You have eaten {total} mg of potassium so far."
    with attach(c.app, FakeProvider([step_call("get_today", date=DAY), step_answer(answer)])) as provider:
        r = ask(c, "how much potassium have I had")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "answer" and body["text"] == answer
        assert (body["model_calls"], body["tool_calls"], body["ai_called"]) == (2, 1, True)
        assert body["label"]["source"] == "ai" and body["label"]["checked"] is True
        assert body["provider"]["model"] == "gpt-6-luna" and body["prompt_version"]
        assert provider.calls == 2
        first, second = provider.bodies()
        assert first["response_format"] == {"type": "json_object"}  # free-form arguments: plain JSON mode
        assert [m["role"] for m in first["messages"]] == ["system", "user"]
        # the second request carries the model's own call and the app's result for this person
        assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "user"]
        assert json.loads(second["messages"][2]["content"]) == {"call": {"tool": "get_today", "arguments": {"date": DAY}}}
        assert "RESULT of get_today" in second["messages"][3]["content"] and f'"value":{total}' in second["messages"][3]["content"].replace(".0,", ",")
    [group] = [g for g in body["numbers"] if g["title"].startswith("The day")]
    potassium = next(row for row in group["rows"] if row["label"] == "Potassium")
    assert potassium["value"] == f"{total:,} mg" and "limit 2,500 mg" in potassium["detail"]


def test_a_made_up_number_is_withheld_and_the_apps_numbers_are_shown(ask_client):
    c = ask_client
    log_food(c, "banana", "breakfast")
    total = potassium_total(c)
    wrong = total + 111
    with attach(c.app, FakeProvider([step_call("get_today", date=DAY), step_answer(f"You have eaten {wrong} mg of potassium.")])):
        body = ask(c).json()
    assert body["kind"] == "withheld" and body["text"] == WITHHELD_NUMBER
    assert any(g["title"].startswith("The day") for g in body["numbers"])  # the app's own figures stay
    assert str(wrong) not in json.dumps(body)


def test_a_number_the_person_typed_may_be_quoted(ask_client):
    with attach(ask_client.app, FakeProvider([step_answer("Yes, 250 ml of water fits your plan.")])):
        assert ask(ask_client, "can I drink 250 ml of water").json()["kind"] == "answer"
    with attach(ask_client.app, FakeProvider([step_answer("Yes, 300 ml of water fits your plan.")])):
        assert ask(ask_client, "can I drink 250 ml of water").json()["kind"] == "withheld"


@pytest.mark.parametrize("answer", [
    "Take 4 units of insulin before you eat that.",
    "A bolus would cover it.",
    "Skip your insulin if you eat that.",
    "Ask about sevelamer; the dose depends on the meal.",
    "If your sugar is low, wait before eating anything with potassium.",
])
def test_insulin_and_dose_talk_is_withheld(ask_client, answer):
    with attach(ask_client.app, FakeProvider([step_answer(answer)])):
        body = ask(ask_client, "what should I do about dinner").json()
    assert body["kind"] == "withheld" and body["text"] == WITHHELD_DOSE
    assert answer not in json.dumps(body)


@pytest.mark.parametrize("answer", [
    "Have more rice if you are still hungry.",
    "Extra water is not advised by me; check with your care team about fluid.",
    "Avoid salt substitutes: they contain potassium. Check with your care team first.",
    "Choose low-sodium bread. See /learn/sodium/ for more.",
])
def test_ordinary_food_talk_passes_the_dose_check(ask_client, answer):
    with attach(ask_client.app, FakeProvider([step_answer(answer)])):
        body = ask(ask_client, "what about dinner").json()
    assert body["kind"] == "answer" and body["text"] == answer


def test_links_are_removed_from_the_answer_except_the_apps_learn_pages(ask_client):
    with attach(ask_client.app, FakeProvider([step_answer("Read more at https://example.com/x and /learn/potassium/ today.")])):
        body = ask(ask_client).json()
    assert body["kind"] == "answer" and "example.com" not in body["text"] and "/learn/potassium/" in body["text"]


def test_lab_words_add_the_fixed_note(ask_client):
    with attach(ask_client.app, FakeProvider([step_answer("I cannot read that for you; your care team can.")])):
        body = ask(ask_client, "what does my eGFR mean").json()
    assert body["kind"] == "answer" and body["notes"] == ["Lab results are for your care team to interpret."]
    with attach(ask_client.app, FakeProvider([step_answer("Your A1c is something your team reads.")])):
        assert ask(ask_client, "hello").json()["notes"] == ["Lab results are for your care team to interpret."]
    with attach(ask_client.app, FakeProvider([step_answer("Rice fits.")])):
        assert ask(ask_client, "rice?").json()["notes"] == []


def test_an_unknown_tool_and_bad_arguments_are_told_to_the_model_which_may_retry(ask_client):
    c = ask_client
    script = [step_call("log_food", items=[{"food": "banana"}], meal="lunch"),   # a saving tool: not offered
              step_call("check_meal", items=[]),                                   # bad arguments
              step_call("check_meal", items=[{"food": "banana", "amount": 1}]),
              step_answer("Checked.")]
    with attach(c.app, FakeProvider(script)) as provider:
        body = ask(c, "is a banana ok").json()
        bodies = provider.bodies()
    assert body["kind"] == "answer" and (body["model_calls"], body["tool_calls"]) == (4, 3)
    assert 'There is no tool called "log_food"' in bodies[1]["messages"][-1]["content"]
    assert "ERROR from check_meal: Invalid arguments" in bodies[2]["messages"][-1]["content"]
    assert "RESULT of check_meal" in bodies[3]["messages"][-1]["content"]
    assert c.get("/api/log", params={"date": DAY}).json()["entries"] == []  # nothing was saved
    assert any(g["title"] == "This meal" for g in body["numbers"])


def test_at_most_six_tool_calls_then_the_model_must_answer(ask_client):
    with attach(ask_client.app, FakeProvider([step_call("get_today")] * 6 + [step_answer("Done.")])) as provider:
        body = ask(ask_client).json()
        assert body["kind"] == "answer" and (body["model_calls"], body["tool_calls"]) == (7, 6) and provider.calls == 7
        assert "No tool calls are left" in provider.bodies()[6]["messages"][-1]["content"]


def test_a_model_that_keeps_calling_gets_the_fixed_text_and_the_numbers_gathered(ask_client):
    c = ask_client
    log_food(c, "banana", "breakfast")
    with attach(c.app, FakeProvider([step_call("get_today", date=DAY)] * 7 + [step_answer("never")])) as provider:
        body = ask(c).json()
        assert provider.calls == 7  # the seventh call is the last
    assert body["kind"] == "unfinished" and body["text"] == UNFINISHED
    assert (body["model_calls"], body["tool_calls"]) == (7, 6)
    assert body["numbers"] and body["numbers"][0]["title"].startswith("The day")


def test_every_model_call_costs_one_unit_of_quota_and_has_an_activity_row(ask_client):
    c = ask_client
    before = remaining(c)
    with attach(c.app, FakeProvider([step_call("get_today"), step_call("search_foods", query="rice"), step_answer("Fine.")])):
        assert ask(c).json()["model_calls"] == 3
    assert remaining(c) == before - 3
    rows = db_rows(c, "ai_audit")
    assert [r["feature"] for r in rows] == ["chat"] * 3 and [r["status"] for r in rows] == ["ok"] * 3
    verdicts = [json.loads(r["verdict_json"]) for r in rows]
    assert [(v["step"], v.get("tool"), v["outcome"]) for v in verdicts] == [(0, "get_today", "call"), (1, "search_foods", "call"),
                                                                            (2, None, "answer")]
    usage = db_rows(c, "ai_usage")
    assert sum(r["requests"] for r in usage) == 3 and sum(r["prompt_tokens"] for r in usage) == 3000
    assert [e["feature"] for e in c.get("/api/ai/audit").json()["events"]] == ["chat"] * 3


def test_the_daily_quota_ends_the_loop_with_the_numbers_after_the_first_call(ask_client):
    c = ask_client
    log_food(c, "banana", "breakfast")
    assert c.patch("/api/admin/settings", json={"ai.shared_daily_limit": 2}).status_code == 200
    with attach(c.app, FakeProvider([step_call("get_today", date=DAY), step_call("search_foods", query="rice"), step_answer("x")])) as provider:
        body = ask(c).json()
        assert body["kind"] == "unfinished" and body["text"] == UNFINISHED and provider.calls == 2
        assert body["numbers"] and (body["model_calls"], body["tool_calls"]) == (2, 2)
        again = ask(c)
        assert again.status_code == 429 and again.json()["reason"] == "quota_exhausted" and provider.calls == 2  # the first call is refused


def test_the_repair_turn_is_one_model_call(ask_client):
    c = ask_client
    before = remaining(c)
    with attach(c.app, FakeProvider([chat("Sure! Here you go."), step_answer("Fine.")])) as provider:
        body = ask(c).json()
        assert body["kind"] == "answer" and body["model_calls"] == 1 and provider.calls == 2
        assert "not valid" in provider.bodies()[1]["messages"][-1]["content"]
    assert remaining(c) == before - 1
    assert json.loads(db_rows(c, "ai_audit")[0]["verdict_json"])["repaired"] is True


def test_a_step_with_both_a_call_and_an_answer_is_repaired(ask_client):
    both = chat({"call": {"tool": "get_today", "arguments": {}}, "answer": "also this"})
    with attach(ask_client.app, FakeProvider([both, step_answer("Fine.")])) as provider:
        assert ask(ask_client).json()["kind"] == "answer" and provider.calls == 2


def test_a_provider_error_is_a_clear_message_with_the_numbers_gathered(ask_client):
    c = ask_client
    log_food(c, "banana", "breakfast")
    script = [step_call("get_today", date=DAY), {"status": 401, "body": {"error": {"message": "invalid key"}}}]
    with attach(c.app, FakeProvider(script)):
        body = ask(c).json()
    assert body["kind"] == "error" and body["text"] == "The AI server refused the key." and body["numbers"]
    statuses = [r["status"] for r in db_rows(c, "ai_audit")]
    assert statuses == ["ok", "error:http_401"]


def test_a_refusal_from_the_provider_is_the_usual_sentence(ask_client):
    with attach(ask_client.app, FakeProvider([chat(None, refusal="I cannot help with that")])):
        body = ask(ask_client).json()
    assert body["kind"] == "error" and body["text"] == "This is outside what the app's AI helps with. Your care team can answer it."


def test_an_answer_that_is_nothing_after_cleaning_is_an_error(ask_client):
    with attach(ask_client.app, FakeProvider([step_answer("https://example.com/nothing-else")])):
        body = ask(ask_client).json()
    assert body["kind"] == "error" and body["text"] == "The AI answer was empty."


def test_a_busy_person_is_told_to_wait(ask_client):
    c = ask_client
    state = c.app.state.ai
    state.gate.enter(1)  # the admin's own earlier question is still running
    try:
        with attach(c.app, FakeProvider()) as provider:
            r = ask(c)
            assert r.status_code == 429 and r.json()["reason"] == "busy_person" and provider.requests == []
    finally:
        state.gate.leave(1)
    with attach(c.app, FakeProvider([step_answer("Fine.")])):
        assert ask(c).status_code == 200
    assert state.gate.active == 0  # the slot is given back


# --------------------------------------------------------------------------- #
# Two people
# --------------------------------------------------------------------------- #


def test_another_persons_data_never_reaches_the_model_or_the_screen(ask_two):
    admin, sam = ask_two
    assert admin.post("/api/foods", json={"name": "Admin secret stew", "serving_desc": "1 bowl", "serving_g": 300,
                                          "nutrients": {"potassium_mg": 777, "calories_kcal": 321}}).status_code in (200, 201)
    log_food(admin, "banana", "breakfast")
    log_food(sam, "apple", "lunch")
    admin_total = potassium_total(admin)
    sam_total = potassium_total(sam)
    assert admin_total != sam_total
    script = [step_call("get_today", date=DAY), step_call("search_foods", query="stew"), step_answer("Looked.")]
    with attach(sam.app, FakeProvider(list(script))) as provider:
        body = ask(sam, "what did I eat").json()
        sent = json.dumps(provider.bodies())
        assert body["kind"] == "answer"
    assert "Admin secret stew" not in sent and "Admin secret stew" not in json.dumps(body)
    assert f'"value":{sam_total}' in sent.replace("\\", "").replace(".0,", ",")
    # Sam's quota and activity are Sam's own
    assert len(sam.get("/api/ai/audit").json()["events"]) == 3 and admin.get("/api/ai/audit").json()["events"] == []
    # and the other way round: the admin's search finds the admin's food
    with attach(admin.app, FakeProvider([step_call("search_foods", query="stew"), step_answer("Found it.")])) as provider:
        ask(admin, "find the stew")
        assert "Admin secret stew" in json.dumps(provider.bodies()[1])


# --------------------------------------------------------------------------- #
# What the prompt and the activity log hold
# --------------------------------------------------------------------------- #

PROFILE = {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "weight_kg": 71.3, "height_cm": 168,
           "birth_month": "1961-04", "sex": "female", "targets": TARGETS}


def test_the_prompt_has_no_identity_and_the_dry_run_shows_the_first_request(ask_client):
    c = ask_client
    assert c.put("/api/profile", json=PROFILE).status_code == 200
    assert c.patch("/api/me/ai", json={"preferences": "vegetarian, no fish"}).status_code == 200
    with attach(c.app, FakeProvider([step_answer("Fine.")])) as provider:
        dry = ask(c, f"what about {MARKER}", dry_run="true").json()
        assert provider.requests == []  # nothing is sent, nothing is counted
        assert dry["dry_run"] is True and dry["feature"] == "chat" and dry["destination"].endswith("/chat/completions")
        ask(c, f"what about {MARKER}")
        sent = provider.bodies()[0]
    assert dry["body"] == sent  # the dry run is exactly what is sent
    text = json.dumps(sent)
    system = sent["messages"][0]["content"]
    for tool in ("get_today", "search_foods", "check_meal"):
        assert tool in system
    assert "log_food" not in system and "save_recipe" not in system and "safety_check" not in system  # never offered
    assert "At most" not in system and "at most 6 tool calls" in system and "PERSON:" in system
    assert '"ckd_stage":"4"' in system and '"diabetes":"type1"' in system and "vegetarian, no fish" in system
    assert '"age_band":null' in system and '"sex":null' in system  # not shared: null, not the value
    for identity in ("admin", "71.3", "168", "1961", "female", "60-69", "@"):
        assert identity not in text.replace("administrator", ""), identity
    assert sent["messages"][-1] == {"role": "user", "content": f"what about {MARKER}"}
    assert sent.get("safety_identifier") and "admin" not in sent["safety_identifier"]  # a keyed hash, not the user


def test_age_band_and_sex_are_sent_only_with_the_persons_own_choice(ask_client):
    c = ask_client
    assert c.put("/api/profile", json=PROFILE).status_code == 200
    assert c.patch("/api/me/ai", json={"share_age_sex": True}).status_code == 200
    system = ask(c, dry_run="true").json()["body"]["messages"][0]["content"]
    assert '"age_band":"60-69"' in system and '"sex":"female"' in system and "1961" not in system


def test_the_activity_log_and_the_database_keep_no_message_text(ask_client):
    c = ask_client
    log_food(c, "banana", "breakfast")
    history = ({"role": "user", "text": f"earlier question {MARKER}"}, {"role": "assistant", "text": f"earlier answer {MARKER}"})
    total = potassium_total(c)
    with attach(c.app, FakeProvider([step_call("get_today", date=DAY), step_answer(f"{total} mg of potassium {MARKER}.")])):
        body = ask(c, f"how much potassium {MARKER}", history=history).json()
    assert body["kind"] == "answer" and MARKER in body["text"]
    for row in db_rows(c, "ai_audit"):
        assert row["request_json"] is None and row["response_text"] is None  # not even the retention window keeps bodies
    conn = sqlite3.connect(c.app.state.settings.db_path)
    try:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in conn.execute(f'SELECT * FROM "{table}"').fetchall():
                assert MARKER not in repr(row), table
    finally:
        conn.close()
    assert MARKER not in json.dumps(c.get("/api/ai/audit").json())
    activity = c.get("/api/me/activity")
    assert activity.status_code == 200 and MARKER not in json.dumps(activity.json())


def test_a_small_prompt_budget_drops_the_oldest_messages_and_then_refuses(tmp_path, foods_json):
    with TestClient(create_app(ai_settings(tmp_path, foods_json, context_tokens=5000)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True})
        become_ready(c)
        long = "word " * 380
        history = tuple({"role": "user" if i % 2 == 0 else "assistant", "text": f"turn{i} " + long} for i in range(12))
        with attach(c.app, FakeProvider([step_answer("Fine.")])) as provider:
            assert ask(c, "the newest question", history=history).json()["kind"] == "answer"
            sent = json.dumps(provider.bodies()[0])
            assert "the newest question" in sent and "turn0 " not in sent and "turn11 " in sent  # the newest are kept
            assert provider.bodies()[0]["messages"][1]["role"] == "user"
    with TestClient(create_app(ai_settings(tmp_path / "b", foods_json, context_tokens=1024)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True})
        become_ready(c)
        with attach(c.app, FakeProvider()) as provider:
            r = ask(c, "any question")
            assert r.status_code == 503 and r.json()["reason"] == "context_too_small" and provider.requests == []


def test_a_tool_that_fails_does_not_end_the_conversation(ask_client, monkeypatch):
    from app.mcp import tools

    def broken(call, args):
        raise RuntimeError("boom")

    original = tools.TOOLS_BY_NAME["get_today"]
    patched = tools.Tool(original.name, original.title, original.description, original.input_schema, original.args, broken)
    monkeypatch.setitem(tools.TOOLS_BY_NAME, "get_today", patched)
    with attach(ask_client.app, FakeProvider([step_call("get_today"), step_answer("I could not look that up.")])) as provider:
        body = ask(ask_client).json()
        assert body["kind"] == "answer" and "The tool could not run" in provider.bodies()[1]["messages"][-1]["content"]
        assert "boom" not in json.dumps(provider.bodies())
