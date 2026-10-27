"""Saving from the Ask chat, with a trust setting (assistant step 2, part C; ``docs/dev/plans/assistant-step2.md``;
ARCHITECTURE "Ask chat").

The model may call ``log_food`` and ``save_recipe``. By default (``ask``) nothing it asks for is executed: the answer is a
``confirm_save`` card, and the page posts the card's body to the normal save route when the person presses Save. When the
admin switch ``ai.allow_trusted_saves`` is on and the person chose "Trust it for this conversation" (and the page says so)
or "Trust it always", the save runs at once through the MCP tools' own code, with a key made from the request's
``request_id`` so a request sent twice saves once, and the answer carries what was saved with the ids Undo deletes.

Covered: the effective trust (the matrix of admin switch, stored choice and what the page sends); ask mode (nothing
written, the card equals ``place_items``, the card's body is accepted by ``/api/log/batch`` and ``/api/meals`` as it is,
the questions when an item is unresolved); trusted mode (saved at once, all or nothing, retry saves once, Undo through the
normal DELETE routes, another person's food never saved, ``via: "Ask"`` in the activity log); a low treated with food is
saved and never warned about; a message that matched a safety rule never saves; the choice is audited from both routes
that can write it. Fake provider, no network."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest

from ai_support import FakeProvider, attach
from conftest import DAY, HTTPS_URL, TestClient, add_user, log_food, make_settings, sign_in
from test_ai_chat import become_ready, db_rows, step_answer, step_call
from test_ai_routes import OPENAI_KEY, ai_settings, enable
from test_mcp_write import USDA_RECORDS
from app import foods as foods_module
from app.ai import chat as CH
from app.ai import chat_save as CS
from app.config import AiEnv
from app.main import create_app
from app.mcp import request_keys
from app.mcp import tools as T

RID = "req-trust-0001"


@pytest.fixture
def trusting_client(tmp_path, foods_json):
    """Ask on, the admin switch for trusted saves on, one person ready (trust left at the default)."""
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.allow_trusted_saves": True})
        become_ready(c)
        yield c


@pytest.fixture
def plain_client(tmp_path, foods_json):
    """Ask on, the admin switch for trusted saves left off (its default)."""
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True})
        become_ready(c)
        yield c


def send(c: TestClient, text: str = "log a banana for breakfast", **fields: Any):
    return c.post("/api/ai/chat", json={"messages": [{"role": "user", "text": text}], **fields})


def trust(c: TestClient, value: str) -> None:
    r = c.patch("/api/me/ai", json={"trust": value})
    assert r.status_code == 200, r.text


def banana(**extra: Any) -> dict[str, Any]:
    return step_call("log_food", items=[{"food": "banana", "amount": 1}], meal="breakfast", date=DAY, **extra)


def entries(c: TestClient, day: str = DAY) -> list[dict[str, Any]]:
    return c.get("/api/log", params={"date": day}).json()["entries"]


def meals(c: TestClient) -> list[dict[str, Any]]:
    return c.get("/api/meals").json()["meals"]


def count(c: TestClient, table: str) -> int:
    return len(db_rows(c, table))


def audit(c: TestClient, action: str) -> list[dict[str, Any]]:
    return [{**dict(r), "details": json.loads(r["details_json"])} for r in db_rows(c, "audit_log") if r["action"] == action]


def unchanged(c: TestClient) -> tuple[int, int, int, int]:
    """Rows a save would touch: log entries, saved meals, foods, remembered keys."""
    return count(c, "log_entries"), count(c, "meal_templates"), count(c, "foods"), count(c, "assistant_ask_keys")


# --------------------------------------------------------------------------- #
# The effective trust
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("allowed, stored, requested, expected", [
    (False, "ask", None, "ask"), (False, "always", None, "ask"), (False, "always", "conversation", "ask"),
    (False, "conversation", "conversation", "ask"),
    (True, "ask", None, "ask"), (True, "ask", "conversation", "ask"),  # the page cannot grant what the person did not choose
    (True, "conversation", None, "ask"), (True, "conversation", "ask", "ask"), (True, "conversation", "conversation", "conversation"),
    (True, "always", None, "always"), (True, "always", "ask", "always"), (True, "always", "conversation", "always"),
    (True, "sometimes", "conversation", "ask"),  # a stored value nobody knows is never trust
])
def test_effective_trust_matrix(allowed, stored, requested, expected):
    assert CS.effective_trust(admin_allows=allowed, stored=stored, requested=requested) == expected


def test_the_default_is_ask_and_the_status_says_what_the_admin_allows(trusting_client):
    c = trusting_client
    assert c.get("/api/ai/status").json()["trust"] == {"setting": "ask", "allowed": True, "effective": "ask"}
    assert c.get("/api/me/ai").json()["trusted_saves_allowed"] is True
    trust(c, "always")
    assert c.get("/api/ai/status").json()["trust"] == {"setting": "always", "allowed": True, "effective": "always"}
    assert c.patch("/api/admin/settings", json={"ai.allow_trusted_saves": False}).status_code == 200
    # stored, but the admin has not allowed it (any more): the effective choice is ask, and the screens can say so
    assert c.get("/api/ai/status").json()["trust"] == {"setting": "always", "allowed": False, "effective": "ask"}
    assert c.get("/api/me/ai").json()["trusted_saves_allowed"] is False


def test_trusted_saves_are_off_by_default(plain_client):
    assert plain_client.get("/api/ai/status").json()["trust"] == {"setting": "ask", "allowed": False, "effective": "ask"}
    assert plain_client.get("/api/admin/settings").json()["settings"]["ai.allow_trusted_saves"]["value"] is False


def test_the_admin_switch_is_a_registered_setting_with_an_env_name():
    from app import settings_registry

    definition = settings_registry.REGISTRY["ai.allow_trusted_saves"]
    assert (definition.scope, definition.default, definition.env) == ("instance", False, "AI_ALLOW_TRUSTED_SAVES")
    assert "ai.allow_trusted_saves" in settings_registry.NO_SIGNIN_ENV_ONLY
    assert "saves" in definition.help and "Undo" not in definition.help.replace("undone", "")


def test_the_trust_choice_is_validated_and_the_body_cannot_ask_for_always(plain_client):
    assert plain_client.patch("/api/me/ai", json={"trust": "sometimes"}).status_code == 400
    assert plain_client.patch("/api/me/settings", json={"ai": {"opt_in": True, "trust": "yes"}}).status_code == 400
    assert send(plain_client, trust="always").status_code == 400
    for bad in ("short", "has space 123", "x" * 49):
        assert send(plain_client, request_id=bad).status_code == 400


# --------------------------------------------------------------------------- #
# Ask mode: a card, nothing written
# --------------------------------------------------------------------------- #


def test_ask_mode_a_save_call_is_not_executed_and_the_card_equals_place_items(plain_client):
    c = plain_client
    before = unchanged(c)
    script = [step_call("log_food", items=[{"food": "banana", "amount": 2}, {"food": "apple", "amount": 100, "unit": "g"}],
                        meal="lunch", date=DAY, status="planned")]
    with attach(c.app, FakeProvider(script)) as provider:
        r = send(c, "plan two bananas and 100 g of apple for lunch", request_id=RID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert provider.calls == 1  # the loop ends at the save: the app writes the words, not the model
    assert body["kind"] == "confirm_save" and body["text"] == CH.CONFIRM_TEXT and body["trust"] == "ask"
    assert body["saved"] == [] and body["questions"] == [] and (body["model_calls"], body["tool_calls"]) == (1, 1)
    assert unchanged(c) == before and entries(c) == []  # nothing was saved, not even a remembered key
    card = body["pending_save"]
    assert (card["tool"], card["date"], card["meal"], card["status"], card["purpose"]) == ("log_food", DAY, "lunch", "planned", None)
    conn = sqlite3.connect(c.app.state.settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        placed, unresolved = T.place_items(
            T.Call(None, conn, SimpleNamespace(id=1, can_use_shared=True)),  # type: ignore[arg-type]
            [T.MealItem(food="banana", amount=2), T.MealItem(food="apple", amount=100, unit="g")])
    finally:
        conn.close()
    assert unresolved == [] and len(card["items"]) == len(card["payload"]["entries"]) == len(placed) == 2
    for shown, entry, one in zip(card["items"], card["payload"]["entries"], placed):
        assert shown["food_id"] == entry["food_id"] == one.food_id and shown["name"] == one.row["name"]
        assert shown["servings"] == round(one.servings, 3) and shown["new_food"] is False and shown["fdc_id"] is None
        assert (entry["date"], entry["meal"], entry["status"]) == (DAY, "lunch", "planned")
        assert entry.get("servings") == (None if one.by_grams else one.servings) or entry.get("grams") == one.quantity
    assert card["items"][0]["as_asked"] == "2 servings" and card["items"][1]["as_asked"] == "100 g"
    [group] = card["numbers"]
    assert group["title"] == "This adds" and {row["label"] for row in group["rows"]} >= {"Potassium"}
    assert card["imports"] == []


def test_the_cards_payload_is_accepted_by_the_log_route_as_it_is_and_a_second_press_adds_nothing(plain_client):
    c = plain_client
    with attach(c.app, FakeProvider([banana(status="planned")])):
        card = send(c, request_id=RID).json()["pending_save"]
    payload = json.loads(json.dumps(card["payload"]))
    assert "fdc_id" not in json.dumps(payload) and all(e["client_id"] for e in payload["entries"])
    first = c.post("/api/log/batch", json=payload)  # exactly what the page posts, with the status the card was given
    assert first.status_code == 201, first.text
    [saved] = first.json()["entries"]
    assert (saved["food_name"], saved["status"], saved["meal"], saved["date"]) == ("Banana, raw", "planned", "breakfast", DAY)
    again = c.post("/api/log/batch", json=payload)  # a double press: the same client_id answers with the same entry
    assert again.status_code == 200 and again.json()["entries"][0]["id"] == saved["id"] and len(entries(c)) == 1
    eaten = {"entries": [{**e, "status": "eaten", "client_id": "0f8fad5b-d9cb-469f-a165-70867728950e"} for e in payload["entries"]]}
    assert c.post("/api/log/batch", json=eaten).status_code == 201  # "Save as eaten" is the same body with the other status
    assert sorted(e["status"] for e in entries(c)) == ["eaten", "planned"]


@pytest.mark.safety
def test_the_cards_entries_never_carry_a_warning_and_a_low_treatment_is_kept_as_one(plain_client):
    c = plain_client
    script = [step_call("log_food", items=[{"food": "glucose tablets", "amount": 4}], meal="snack", date=DAY, purpose="hypo")]
    with attach(c.app, FakeProvider(script)):
        body = send(c, "log 4 glucose tablets for a snack", request_id=RID).json()
    card = body["pending_save"]
    assert body["kind"] == "confirm_save" and card["purpose"] == "hypo" and card["items"][0]["counted_as_treating_a_low"] is True
    assert card["payload"]["entries"][0]["purpose"] == "hypo"
    assert not any(word in json.dumps(body).lower() for word in ("warning", "avoid", "careful", "wait", "too much"))
    saved = c.post("/api/log/batch", json=card["payload"])
    assert saved.status_code == 201 and saved.json()["entries"][0]["purpose"] == "hypo"


def test_an_unresolved_item_shows_the_questions_and_no_card(plain_client):
    c = plain_client
    before = unchanged(c)
    script = [step_call("log_food", items=[{"food": "banana"}, {"food": "dragon pudding"}], meal="lunch", date=DAY),
              step_answer("I could not find the pudding. Which food did you mean?")]
    with attach(c.app, FakeProvider(script)) as provider:
        body = send(c, "log a banana and dragon pudding for lunch").json()
        assert "unresolved" in provider.bodies()[1]["messages"][-1]["content"]  # the model is told, as the MCP tool tells it
    assert body["kind"] == "answer" and body["pending_save"] is None and body["saved"] == []
    assert body["questions"] == [{"food": "dragon pudding",
                                  "question": 'I could not find "dragon pudding" in your foods. Try another name, or add it in Foods.'}]
    assert unchanged(c) == before  # not even the banana: all or nothing


def test_a_recipe_card_is_accepted_by_the_meals_route_as_it_is(plain_client):
    c = plain_client
    script = [step_call("save_recipe", name="Banana apple bowl", ingredients=[{"food": "banana"}, {"food": "apple", "amount": 2}],
                        servings=2, source_url="https://example.com/bowl")]
    with attach(c.app, FakeProvider(script)):
        body = send(c, "save my banana apple bowl recipe, it makes 2 servings", request_id=RID).json()
    card = body["pending_save"]
    assert body["kind"] == "confirm_save" and card["tool"] == "save_recipe" and meals(c) == []
    assert (card["name"], card["servings_made"]) == ("Banana apple bowl", 2)
    assert [g["title"] for g in card["numbers"]] == ["Whole recipe", "Per serving"]
    assert "note" not in card["payload"]  # schema step 21: the count and the link have their own fields
    assert (card["payload"]["servings_made"], card["payload"]["source_url"]) == (2, "https://example.com/bowl")
    made = c.post("/api/meals", json=card["payload"])
    assert made.status_code == 201, made.text
    assert [i["food_name"] for i in made.json()["items"]] == ["Banana, raw", "Apple, raw, with skin"]
    assert made.json()["items"][1]["servings"] == 2


def test_the_model_cannot_choose_the_key_and_a_bad_call_is_told_to_it(plain_client):
    c = plain_client
    script = [step_call("log_food", items=[], meal="lunch"),  # bad arguments: told to the model, which may retry
              banana(request_key="chosen-by-the-model")]     # a key from the model is ignored
    with attach(c.app, FakeProvider(script)) as provider:
        body = send(c).json()
        assert "ERROR from log_food: Invalid arguments" in provider.bodies()[1]["messages"][-1]["content"]
    assert body["kind"] == "confirm_save" and "chosen-by-the-model" not in json.dumps(body)


# --------------------------------------------------------------------------- #
# Trusted mode: saved at once
# --------------------------------------------------------------------------- #


def test_always_saves_at_once_all_in_one_transaction_and_the_log_says_via_ask(trusting_client):
    c = trusting_client
    trust(c, "always")
    log_food(c, "apple", "breakfast")  # something else already in the day
    script = [step_call("log_food", items=[{"food": "banana", "amount": 2}, {"food": "chicken", "amount": 100, "unit": "g"}],
                        meal="lunch", date=DAY, status="eaten"),
              step_answer("Saved a banana and chicken for lunch.")]
    with attach(c.app, FakeProvider(script)) as provider:
        r = send(c, "I had two bananas and 100 g of chicken for lunch", request_id=RID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert provider.calls == 2
        assert "saved\":true" in provider.bodies()[1]["messages"][-1]["content"].replace(" ", "")
    assert body["kind"] == "answer" and body["trust"] == "always" and body["pending_save"] is None
    [card] = body["saved"]
    assert (card["tool"], card["date"], card["meal"], card["status"], card["duplicate"]) == ("log_food", DAY, "lunch", "eaten", False)
    lunch = [e for e in entries(c) if e["meal"] == "lunch"]
    assert sorted(e["food_name"] for e in lunch) == ["Banana, raw", "Chicken breast, roasted"]
    assert sorted(card["undo"]["entry_ids"]) == sorted(e["id"] for e in lunch) and len(entries(c)) == 3
    assert [i["name"] for i in card["items"]] == ["Banana, raw", "Chicken breast, roasted"]
    assert card["numbers"][0]["title"] == "Saved" and any(row["label"] == "Potassium" for row in card["numbers"][0]["rows"])
    assert any(g["title"].startswith("The day") for g in body["numbers"])  # "From the app": the day after the save
    [row] = audit(c, "assistant.food_logged")  # the same row an access token's save writes, but via "Ask"
    assert row["details"]["via"] == "Ask" and row["details"]["entries"] == 2 and row["details"]["meal"] == "lunch"
    assert row["target_type"] is None and row["actor_user_id"] == 1 and "token" not in row["details_json"].lower()
    activity = c.get("/api/me/activity").json()["events"]
    assert any(e["action"] == "assistant.food_logged" and e["details"]["via"] == "Ask" for e in activity)
    [key] = db_rows(c, "assistant_ask_keys")
    assert key["tool"] == "log_food" and key["user_id"] == 1 and RID not in dict(key).values()  # a hash, never the key


def test_the_answer_may_quote_what_the_save_returned_and_nothing_else(trusting_client):
    c = trusting_client
    trust(c, "always")
    with attach(c.app, FakeProvider([banana(), step_answer("done")])):
        total = send(c, "log a banana", request_id=RID).json()["saved"][0]["numbers"][0]["rows"]
    potassium = next(row for row in total if row["label"] == "Potassium")["value"]  # e.g. "422 mg"
    c.delete(f"/api/log/{entries(c)[0]['id']}")
    with attach(c.app, FakeProvider([banana(), step_answer(f"That is {potassium} of potassium.")])):
        body = send(c, "log a banana", request_id="req-trust-0002").json()
    assert body["kind"] == "answer" and potassium in body["text"]
    c.delete(f"/api/log/{entries(c)[0]['id']}")
    with attach(c.app, FakeProvider([banana(), step_answer("That is 9,876 mg of potassium.")])):
        body = send(c, "log a banana", request_id="req-trust-0003").json()
    assert body["kind"] == "withheld" and body["text"] == CH.WITHHELD_NUMBER_TEXT
    assert len(body["saved"]) == 1 and body["saved"][0]["undo"]["entry_ids"]  # saved, so Undo is still offered


@pytest.mark.safety
def test_a_dose_answer_after_a_save_is_withheld_but_the_save_card_stays(trusting_client):
    c = trusting_client
    trust(c, "always")
    with attach(c.app, FakeProvider([banana(), step_answer("Saved. Take 4 units of insulin with it.")])):
        body = send(c, "log a banana", request_id=RID).json()
    assert body["kind"] == "withheld" and body["text"] == CH.WITHHELD_DOSE_TEXT and "Take 4 units" not in json.dumps(body)
    assert len(body["saved"]) == 1 and len(entries(c)) == 1


def test_conversation_trust_needs_both_the_choice_and_the_page(trusting_client):
    c = trusting_client
    trust(c, "conversation")
    with attach(c.app, FakeProvider([banana()])):  # the page has not trusted this conversation
        assert send(c, request_id=RID).json()["kind"] == "confirm_save"
    assert entries(c) == []
    with attach(c.app, FakeProvider([banana(), step_answer("Saved.")])):
        body = send(c, request_id="req-trust-0002", trust="conversation").json()
    assert body["trust"] == "conversation" and len(body["saved"]) == 1 and len(entries(c)) == 1
    c.delete(f"/api/log/{entries(c)[0]['id']}")
    trust(c, "ask")  # the person went back to asking: the page's claim counts for nothing
    with attach(c.app, FakeProvider([banana()])):
        body = send(c, request_id="req-trust-0003", trust="conversation").json()
    assert body["kind"] == "confirm_save" and body["trust"] == "ask" and entries(c) == []


@pytest.mark.parametrize("stored, sent", [("always", None), ("conversation", "conversation"), ("always", "conversation")])
def test_the_admin_switch_off_forces_ask(plain_client, stored, sent):
    c = plain_client
    trust(c, stored)
    before = unchanged(c)
    with attach(c.app, FakeProvider([banana()])):
        body = send(c, request_id=RID, **({"trust": sent} if sent else {})).json()
    assert body["kind"] == "confirm_save" and body["trust"] == "ask" and body["saved"] == []
    assert unchanged(c) == before


def test_turning_the_admin_switch_off_later_ends_trusted_saves_at_once(trusting_client):
    c = trusting_client
    trust(c, "always")
    with attach(c.app, FakeProvider([banana(), step_answer("Saved.")])):
        assert send(c, request_id=RID).json()["trust"] == "always"
    assert c.patch("/api/admin/settings", json={"ai.allow_trusted_saves": False}).status_code == 200
    with attach(c.app, FakeProvider([banana()])):
        body = send(c, request_id="req-trust-0002").json()
    assert body["kind"] == "confirm_save" and body["trust"] == "ask" and len(entries(c)) == 1  # only the first save exists


def test_an_unresolved_item_saves_nothing_in_trusted_mode_too(trusting_client):
    c = trusting_client
    trust(c, "always")
    before = unchanged(c)
    script = [step_call("log_food", items=[{"food": "banana"}, {"food": "dragon pudding"}], meal="lunch", date=DAY),
              step_answer("I could not find the pudding, so nothing was saved. What is it called?")]
    with attach(c.app, FakeProvider(script)):
        body = send(c, "log a banana and dragon pudding", request_id=RID).json()
    assert body["kind"] == "answer" and body["saved"] == [] and body["questions"][0]["food"] == "dragon pudding"
    assert unchanged(c) == before and audit(c, "assistant.food_logged") == []


def test_a_request_sent_twice_saves_once_and_the_second_answer_still_offers_undo(trusting_client):
    c = trusting_client
    trust(c, "always")
    with attach(c.app, FakeProvider([banana(), step_answer("Saved a banana.")])):
        first = send(c, request_id=RID).json()
    with attach(c.app, FakeProvider([banana(), step_answer("Saved a banana.")])) as provider:
        second = send(c, request_id=RID).json()  # the answer was lost and the page sent the same request again
        told = provider.bodies()[1]["messages"][-1]["content"]
    assert len(entries(c)) == 1 and count(c, "assistant_ask_keys") == 1 and len(audit(c, "assistant.food_logged")) == 1
    assert "already made its save" in told and "request_key" not in told  # the model is not invited to save again
    assert second["saved"][0]["duplicate"] is True
    assert second["saved"][0]["undo"] == first["saved"][0]["undo"]
    with attach(c.app, FakeProvider([banana(), step_answer("Saved a banana.")])):
        send(c, request_id="req-trust-0002")  # a different request is a different save
    assert len(entries(c)) == 2


def test_after_a_repeat_the_model_cannot_save_again_in_the_same_message(trusting_client):
    c = trusting_client
    trust(c, "always")
    with attach(c.app, FakeProvider([banana(), step_answer("ok")])):
        send(c, request_id=RID)
    other = step_call("log_food", items=[{"food": "apple"}], meal="dinner", date=DAY)
    with attach(c.app, FakeProvider([banana(), other, step_answer("Only the first save counts.")])) as provider:
        body = send(c, request_id=RID).json()
        assert CH.SAVES_CLOSED_ERROR in provider.bodies()[2]["messages"][-1]["content"]
    assert len(entries(c)) == 1 and [e["meal"] for e in entries(c)] == ["breakfast"] and len(body["saved"]) == 1


def test_at_most_two_saves_for_one_message(trusting_client):
    c = trusting_client
    trust(c, "always")
    calls = [step_call("log_food", items=[{"food": "banana"}], meal=m, date=DAY) for m in ("breakfast", "lunch", "dinner")]
    with attach(c.app, FakeProvider([*calls, step_answer("Two are saved.")])) as provider:
        body = send(c, "log a banana three times", request_id=RID).json()
        assert CH.SAVE_LIMIT_ERROR in provider.bodies()[3]["messages"][-1]["content"]
    assert len(body["saved"]) == 2 and sorted(e["meal"] for e in entries(c)) == ["breakfast", "lunch"]
    assert [k["tool"] for k in db_rows(c, "assistant_ask_keys")] == ["log_food", "log_food"]


def test_undo_deletes_exactly_the_saved_rows_through_the_normal_routes(trusting_client):
    c = trusting_client
    trust(c, "always")
    mine = log_food(c, "apple", "breakfast")  # not part of the save
    with attach(c.app, FakeProvider([step_call("log_food", items=[{"food": "banana"}, {"food": "chicken"}], meal="lunch", date=DAY),
                                     step_answer("Saved.")])):
        ids = send(c, "log a banana and chicken for lunch", request_id=RID).json()["saved"][0]["undo"]["entry_ids"]
    assert len(ids) == 2 and mine["id"] not in ids and len(entries(c)) == 3
    for entry_id in ids:
        assert c.delete(f"/api/log/{entry_id}").status_code == 204
    assert [e["id"] for e in entries(c)] == [mine["id"]]
    assert c.delete(f"/api/log/{ids[0]}").status_code == 404  # already gone


def test_another_persons_entries_and_meals_cannot_be_undone_and_their_food_is_never_saved(trusting_client):
    c = trusting_client
    sam = add_user(c)
    become_ready(sam)
    trust(c, "always")
    trust(sam, "always")
    secret = sam.post("/api/foods", json={"name": "Sam's secret soup", "serving_desc": "1 cup (240 g)", "serving_g": 240,
                                          "nutrients": {"carbs_g": 20, "sodium_mg": 600}}).json()
    with attach(c.app, FakeProvider([banana(), step_answer("Saved.")])):
        ids = send(c, request_id=RID).json()["saved"][0]["undo"]["entry_ids"]
    assert sam.delete(f"/api/log/{ids[0]}").status_code == 404 and len(entries(c)) == 1  # not Sam's to undo
    before = unchanged(c)
    steal = step_call("log_food", items=[{"food": "soup", "food_id": secret["id"]}], meal="lunch", date=DAY)
    with attach(c.app, FakeProvider([steal, step_answer("I could not use that food.")])) as provider:
        body = send(c, "log Sam's soup", request_id="req-trust-0002").json()
        assert "not in the person's foods" in provider.bodies()[1]["messages"][-1]["content"]
    assert body["saved"] == [] and unchanged(c) == before and "Sam's secret soup" not in json.dumps(body)
    assert [e["food_name"] for e in entries(sam)] == []  # and nothing appeared in Sam's log either


def test_a_request_id_is_independent_for_another_person(trusting_client):
    """The Ask chat's duplicate guard (``assistant_ask_keys``): the same ``request_id`` from another person is another key."""
    c = trusting_client
    sam = add_user(c)
    become_ready(sam)
    trust(c, "always")
    trust(sam, "always")
    for client in (c, sam):
        with attach(c.app, FakeProvider([banana(), step_answer("Saved.")])):
            assert send(client, request_id=RID).json()["saved"][0]["duplicate"] is False
    assert len(entries(c)) == 1 and len(entries(sam)) == 1 and count(c, "assistant_ask_keys") == 2
    assert request_keys.ask_key_hash(1, RID) != request_keys.ask_key_hash(2, RID)
    assert {r["user_id"] for r in db_rows(c, "assistant_ask_keys")} == {1, 2}


@pytest.mark.safety
def test_a_food_eaten_to_treat_a_low_is_saved_and_never_warned_about(trusting_client):
    c = trusting_client
    trust(c, "always")
    script = [step_call("log_food", items=[{"food": "glucose tablets", "amount": 4}], meal="snack", date=DAY, purpose="hypo"),
              step_answer("Saved your glucose tablets for the snack.")]
    with attach(c.app, FakeProvider(script)):
        body = send(c, "log 4 glucose tablets for a snack", request_id=RID).json()
    assert body["kind"] == "answer" and body["saved"][0]["items"][0]["counted_as_treating_a_low"] is True
    assert [e["purpose"] for e in entries(c)] == ["hypo"]
    assert not any(word in json.dumps(body).lower() for word in ("warning", "avoid", "careful", "too much"))


@pytest.mark.safety
@pytest.mark.parametrize("text", ["I feel shaky and low, log 4 glucose tablets", "my sugar is 3.2 so log juice", "I have chest pain and can't breathe, log a banana"])
@pytest.mark.parametrize("who", ["always", "ask"])
def test_a_message_that_matches_a_safety_rule_never_saves_and_the_model_is_not_called(trusting_client, text, who):
    c = trusting_client
    trust(c, who)
    before = unchanged(c)
    with attach(c.app, FakeProvider()) as provider:
        body = send(c, text, request_id=RID, **({"trust": "conversation"} if who == "always" else {})).json()
        assert provider.requests == []
    assert body["kind"] in ("treat_low", "get_help_now") and body["saved"] == [] and body["pending_save"] is None
    assert unchanged(c) == before


@pytest.mark.safety
def test_a_save_step_never_runs_for_a_safety_message_even_if_called_directly(trusting_client):
    """Defence in depth: the rules answer first, and the save code refuses on its own as well."""
    step = CS.run_save(None, None, None, "log_food", {}, 1, mode="always", request_id=RID, newest="I feel low")  # type: ignore[arg-type]
    assert step.error == CS.SAFETY_ERROR and step.result is None and step.saved is None


def test_a_recipe_is_saved_at_once_and_undone_by_deleting_the_meal(trusting_client):
    c = trusting_client
    trust(c, "always")
    log_food(c, "apple", "breakfast")
    script = [step_call("save_recipe", name="Banana bowl", ingredients=[{"food": "banana"}], servings=2),
              step_answer("Saved the recipe Banana bowl.")]
    with attach(c.app, FakeProvider(script)):
        body = send(c, "save my banana bowl recipe, it makes 2 servings", request_id=RID).json()
    [card] = body["saved"]
    assert card["tool"] == "save_recipe" and card["name"] == "Banana bowl" and card["servings_made"] == 2
    assert [g["title"] for g in card["numbers"]] == ["Whole recipe", "Per serving"]
    [saved] = meals(c)
    assert card["undo"] == {"meal_id": saved["id"]} and saved["note"] is None and saved["servings_made"] == 2
    [row] = audit(c, "assistant.recipe_saved")
    assert row["details"]["via"] == "Ask" and row["target_type"] == "meal" and row["target_id"] == str(saved["id"])
    assert c.delete(f"/api/meals/{saved['id']}").status_code == 204 and meals(c) == [] and len(entries(c)) == 1


# --------------------------------------------------------------------------- #
# The choice is audited, wherever it is written
# --------------------------------------------------------------------------- #


def trust_events(c: TestClient) -> list[tuple[str, str]]:
    return [(r["details"]["old"], r["details"]["new"]) for r in audit(c, "ai.trust_changed")]


def test_every_change_of_the_choice_is_in_the_activity_log_from_both_routes(plain_client):
    c = plain_client
    assert c.patch("/api/me/ai", json={"trust": "ask"}).status_code == 200  # no change, no row
    assert c.patch("/api/me/ai", json={"preferences": "vegetarian"}).status_code == 200
    assert trust_events(c) == []
    trust(c, "conversation")
    trust(c, "conversation")  # again: unchanged
    assert c.patch("/api/me/settings", json={"ai": {"opt_in": True, "provider": "auto", "trust": "always"}}).status_code == 200
    assert c.patch("/api/me/settings", json={"ai": {"opt_in": True, "provider": "auto"}}).status_code == 200  # left out = ask
    assert c.patch("/api/me/settings", json={"ai": None}).status_code == 200  # back to the defaults
    assert trust_events(c) == [("ask", "conversation"), ("conversation", "always"), ("always", "ask")]
    assert c.patch("/api/me/settings", json={"ai": {"opt_in": "nope"}}).status_code == 400
    assert trust_events(c) == [("ask", "conversation"), ("conversation", "always"), ("always", "ask")]  # a refused change adds nothing
    mine = c.get("/api/me/activity").json()["events"]
    assert [e["details"]["new"] for e in mine if e["action"] == "ai.trust_changed"] == ["ask", "always", "conversation"]  # newest first
    assert {e["actor_user_id"] for e in audit(c, "ai.trust_changed")} == {1}


def test_a_change_of_one_persons_choice_is_not_in_anothers_activity(plain_client):
    c = plain_client
    sam = add_user(c)
    trust(c, "conversation")
    assert [e for e in sam.get("/api/me/activity").json()["events"] if e["action"] == "ai.trust_changed"] == []
    trust(sam, "always")
    assert [e["details"]["new"] for e in sam.get("/api/me/activity").json()["events"] if e["action"] == "ai.trust_changed"] == ["always"]
    assert [e["details"]["new"] for e in c.get("/api/me/activity").json()["events"] if e["action"] == "ai.trust_changed"] == ["conversation"]


# --------------------------------------------------------------------------- #
# The activity log of the model calls, the prompt, the pure parts
# --------------------------------------------------------------------------- #


def test_the_ai_activity_log_names_the_save_step_but_holds_no_text(trusting_client):
    c = trusting_client
    trust(c, "always")
    with attach(c.app, FakeProvider([banana(), step_answer("Saved.")])):
        send(c, "log a banana for breakfast please MARKER-9921", request_id=RID)
    rows = db_rows(c, "ai_audit")
    verdicts = [json.loads(r["verdict_json"]) for r in rows]
    assert [(v["step"], v.get("tool"), v["outcome"]) for v in verdicts] == [(0, "log_food", "call"), (1, None, "answer")]
    assert "MARKER-9921" not in json.dumps([dict(r) for r in rows])
    assert "Banana" not in json.dumps([dict(r) for r in rows])


def test_ask_mode_records_the_confirm_step(plain_client):
    c = plain_client
    with attach(c.app, FakeProvider([banana()])):
        send(c, request_id=RID)
    [verdict] = [json.loads(r["verdict_json"]) for r in db_rows(c, "ai_audit")]
    assert (verdict["tool"], verdict["outcome"]) == ("log_food", "confirm_save")


def test_the_prompt_tells_the_model_when_it_may_save_and_never_to_claim_a_save():
    from app.ai import prompts

    text = prompts.chat_prompt({"diabetes": "type1"})  # the profile-worded prompt (tests/test_ai_prompts.py has the other profiles)
    assert "only when the person has asked" in text and 'unless a tool result says "saved": true' in text
    assert "no doses" in text and "a low is never questioned or delayed" in text
    kidney_only = prompts.chat_prompt({"diabetes": "none"})  # the saving and low rules are the same for everyone
    assert "only when the person has asked" in kidney_only and 'unless a tool result says "saved": true' in kidney_only
    assert "still no doses, and a low is never questioned or delayed." in kidney_only
    assert "log_food" in prompts.CHAT_TOOL_NOTES and "save_recipe" in prompts.CHAT_TOOL_NOTES
    assert prompts.PROMPT_VERSION >= "2026-10-15.2"


def test_the_tool_text_offers_the_saving_tools_without_a_request_key_and_never_safety_check():
    text = CH.tools_text(CS.tool_schemas())
    assert "- log_food:" in text and "- save_recipe:" in text and "request_key" not in text and "safety_check" not in text
    assert "- set_food_preference:" in text  # a taste (note 09 §4.8); its tests are in tests/test_ai_chat_preference.py
    assert T.TOOLS_BY_NAME["log_food"].input_schema["properties"]["request_key"]  # the MCP tool itself keeps it


def test_questions_are_written_for_the_person_not_the_model():
    out = CS.person_questions([
        {"food": "x", "reason": "no_match", "question": "No food in the app matches. Ask the person for another name"},
        {"food": "rice", "reason": "several_matches", "alternatives": [{"name": "Rice, white"}, {"name": "Rice, brown"}],
         "question": "Which food is rice? Then check again with its food_id."},
        {"food": "milk", "reason": "unknown_unit", "question": 'How much is that in grams, or in servings of 1 cup?'},
        {"food": "z", "reason": "something_new"}])
    assert [o["question"] for o in out] == [
        'I could not find "x" in your foods. Try another name, or add it in Foods.', 'Which one is "rice"? Rice, white; Rice, brown',
        'How much is that in grams, or in servings of 1 cup?', 'I could not place "z".']
    assert not any("food_id" in o["question"] or "Ask the person" in o["question"] for o in out)


def test_card_ids_are_stable_per_person_and_request():
    first = CS.client_id(1, RID, 0)
    assert first == CS.client_id(1, RID, 0) and first != CS.client_id(2, RID, 0) and first != CS.client_id(1, RID, 1)
    assert first != CS.client_id(1, "req-trust-0002", 0) and len(first) == 36
    assert CS.save_key(RID, 2) == "req-trust-0001-2" and len(CS.save_key("x" * CS.REQUEST_ID_MAX, 2)) <= request_keys.KEY_MAX


# --------------------------------------------------------------------------- #
# A USDA food that is not in the person's list yet (FoodData Central is a mock)
# --------------------------------------------------------------------------- #


@pytest.fixture
def usda_client(tmp_path, foods_json, monkeypatch):
    def handler(request: httpx2.Request) -> httpx2.Response:
        prefix = "/fdc/v1/food/"
        if request.url.path.startswith(prefix) and int(request.url.path[len(prefix):]) in USDA_RECORDS:
            return httpx2.Response(200, json=USDA_RECORDS[int(request.url.path[len(prefix):])])
        return httpx2.Response(404, json={"error": "not found"})

    monkeypatch.setattr(foods_module, "usda_client",
                        lambda: httpx2.Client(base_url=foods_module.USDA_BASE_URL, transport=httpx2.MockTransport(handler)))
    ai = AiEnv(provider="openai", api_key=OPENAI_KEY, model="gpt-6-luna", vision_model="gpt-6-luna")
    with TestClient(create_app(make_settings(tmp_path, foods_json, ai=ai, usda_api_key="TESTKEY")), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.allow_trusted_saves": True})
        become_ready(c)
        yield c


def nectar(**extra: Any) -> dict[str, Any]:
    return step_call("log_food", items=[{"food": "mango nectar", "fdc_id": 2000001, "amount": 2}], meal="lunch", date=DAY, **extra)


def test_a_usda_food_in_a_card_is_added_to_the_list_only_when_the_page_imports_it(usda_client):
    c = usda_client
    before = unchanged(c)
    with attach(c.app, FakeProvider([nectar()])):
        card = send(c, "log two mango nectars for lunch", request_id=RID).json()["pending_save"]
    assert unchanged(c) == before and count(c, "user_food_links") == 0  # nothing added by proposing
    [item] = card["items"]
    assert (item["name"], item["new_food"], item["fdc_id"], item["food_id"]) == ("MANGO NECTAR", True, 2000001, None)
    assert card["imports"] == [2000001] and card["payload"]["entries"][0]["fdc_id"] == 2000001
    assert "TESTKEY" not in json.dumps(card)
    # what the page does: the normal import route, then the normal save with the food's new id
    food = c.post("/api/foods/usda/import", json={"fdc_id": 2000001})
    assert food.status_code == 200, food.text
    entry = {k: v for k, v in card["payload"]["entries"][0].items() if k != "fdc_id"}
    saved = c.post("/api/log/batch", json={"entries": [{**entry, "food_id": food.json()["id"], "status": "eaten"}]})
    assert saved.status_code == 201, saved.text
    assert saved.json()["entries"][0]["food_name"] == "MANGO NECTAR" and saved.json()["entries"][0]["servings"] == 2


def test_a_trusted_save_adds_the_usda_food_in_the_same_step_and_undo_keeps_the_food(usda_client):
    c = usda_client
    trust(c, "always")
    with attach(c.app, FakeProvider([nectar(), step_answer("Saved your mango nectar for lunch.")])):
        body = send(c, "log two mango nectars for lunch", request_id=RID).json()
    [card] = body["saved"]
    assert card["added_to_foods"] == ["MANGO NECTAR"] and [i["name"] for i in card["items"]] == ["MANGO NECTAR"]
    assert [f["name"] for f in c.get("/api/foods", params={"q": "mango"}).json()["foods"]] == ["MANGO NECTAR"]
    assert c.delete(f"/api/log/{card['undo']['entry_ids'][0]}").status_code == 204
    assert entries(c) == [] and len(c.get("/api/foods", params={"q": "mango"}).json()["foods"]) == 1  # the food stays in the list
