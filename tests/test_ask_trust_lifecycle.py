"""Ending trusted saves during a model/food lookup must leave a confirmation card."""
import pytest

from ai_support import FakeProvider, attach
from app import foods
from app.ai import chat as CH
from conftest import DAY, HTTPS_URL, TestClient
from test_ai_chat import step_answer, step_call
from test_ai_chat_save import count, entries, meals, send, trust
from test_ai_chat_save import trusting_client, usda_client  # noqa: F401 - shared fixtures


def change_trust(client, change):
    # The provider mock runs on the original event loop; another browser session changes the setting.
    other = TestClient(client.app, base_url=HTTPS_URL, cookies=client.cookies)
    try:
        if change == "switch":
            response = other.patch("/api/admin/settings", json={"ai.allow_trusted_saves": False})
            assert response.status_code == 200, response.text
        else:
            trust(other, change)
    finally:
        other.close()


def save_call(tool, *, usda=False):
    item = {"food": "nectar", "fdc_id": 2000001} if usda else {"food": "banana"}
    return (step_call(tool, items=[item], meal="lunch", date=DAY) if tool == "log_food" else
            step_call(tool, name="Fruit recipe", ingredients=[item], servings=2))


def assert_confirmation(client, response, tool):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "confirm_save", body
    assert body["trust"] == "ask"
    assert body["saved"] == [] and body["pending_save"]["tool"] == tool
    assert entries(client) == [] and meals(client) == [] and count(client, "log_entries") == 0
    assert count(client, "assistant_ask_keys") == 0


@pytest.mark.parametrize("tool", ["log_food", "save_recipe"])
@pytest.mark.parametrize("change", ["switch", "ask", "conversation"])
def test_trust_ended_while_the_model_answered_requires_confirmation(trusting_client, tool, change):  # noqa: F811
    client = trusting_client
    trust(client, "always")
    changed = False

    def reply(request):
        nonlocal changed
        if request.url.path.endswith("/chat/completions") and not changed:
            change_trust(client, change)
            changed = True

    with attach(client.app, FakeProvider([save_call(tool), step_answer("Saved.")], route=reply)):
        response = send(client, "Save this fruit for lunch", request_id="trust-model-wait")
    assert changed
    assert_confirmation(client, response, tool)


@pytest.mark.parametrize("tool", ["log_food", "save_recipe"])
@pytest.mark.parametrize("change", ["switch", "ask"])
def test_trust_ended_during_food_lookup_rolls_back_the_food_and_requires_confirmation(usda_client, monkeypatch, tool, change):  # noqa: F811
    client = usda_client
    trust(client, "always")
    original = foods.usda_client
    changed = False

    def lookup():
        nonlocal changed
        if not changed:
            change_trust(client, change)
            changed = True
        return original()

    monkeypatch.setattr(foods, "usda_client", lookup)
    with attach(client.app, FakeProvider([save_call(tool, usda=True), step_answer("Saved.")])):
        response = send(client, "Save the mango nectar for lunch", request_id="trust-food-wait")
    assert changed
    assert_confirmation(client, response, tool)
    assert client.get("/api/foods", params={"q": "nectar"}).json()["foods"] == []


def test_enabling_trust_during_an_ask_request_does_not_authorize_an_automatic_save(trusting_client):  # noqa: F811
    client = trusting_client
    trust(client, "ask")
    changed = False

    def reply(request):
        nonlocal changed
        if request.url.path.endswith("/chat/completions") and not changed:
            change_trust(client, "always")
            changed = True

    with attach(client.app, FakeProvider([save_call("log_food")], route=reply)):
        response = send(client, "Log a banana for lunch", request_id="trust-never-expand")
    assert changed
    assert_confirmation(client, response, "log_food")


@pytest.mark.parametrize("tool,table", [("log_food", "log_entries"), ("save_recipe", "meal_templates")])
def test_retry_after_trust_ends_reports_the_existing_save_without_a_new_confirmation(trusting_client, tool, table):  # noqa: F811
    client = trusting_client
    trust(client, "always")
    with attach(client.app, FakeProvider([save_call(tool), step_answer("Saved.")])):
        first = send(client, "Save this fruit for lunch", request_id="trust-retry-original")
    assert first.status_code == 200 and first.json()["saved"], first.text
    trust(client, "ask")
    with attach(client.app, FakeProvider([save_call(tool), step_answer("Already saved.")])):
        response = send(client, "Save this fruit for lunch", request_id="trust-retry-original")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pending_save"] is None and len(body["saved"]) == 1, body
    assert body["trust"] == "ask"
    assert count(client, table) == 1 and count(client, "assistant_ask_keys") == 1


def test_trust_ending_after_one_save_keeps_it_and_requests_confirmation_for_the_next(trusting_client):  # noqa: F811
    client = trusting_client
    trust(client, "always")
    replies = 0

    def reply(request):
        nonlocal replies
        if request.url.path.endswith("/chat/completions"):
            replies += 1
            if replies == 2:
                change_trust(client, "ask")

    with attach(client.app, FakeProvider([save_call("log_food"), save_call("save_recipe"), step_answer("Saved.")], route=reply)):
        response = send(client, "Save the fruit and its recipe for lunch", request_id="trust-after-first-save")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "confirm_save" and body["trust"] == "ask", body
    assert len(body["saved"]) == 1 and body["pending_save"]["tool"] == "save_recipe"
    assert body["text"] != CH.CONFIRM_TEXT and "complete" in body["text"].lower()
    assert count(client, "log_entries") == 1 and count(client, "meal_templates") == 0
    assert count(client, "assistant_ask_keys") == 1


def first_call_still_writing(monkeypatch):
    """Make a retry see the first call's key only inside a write transaction, as when that call commits while the
    retry waits for the lock."""
    from app.mcp import tools as T
    real = T.earlier_save

    def seen_only_under_the_lock(call, tool, key):
        return real(call, tool, key) if call.conn.in_transaction else None
    monkeypatch.setattr(T, "earlier_save", seen_only_under_the_lock)


@pytest.mark.parametrize("tool,table", [("log_food", "log_entries"), ("save_recipe", "meal_templates")])
@pytest.mark.parametrize("trust_on_retry", ["ask", "always"])
def test_a_retry_racing_its_first_call_reports_that_save_not_a_card(trusting_client, monkeypatch, tool, table, trust_on_retry):  # noqa: F811
    # "ask": the retry finds trust off before it saves; "always": trust ends while it waits for the write lock.
    client = trusting_client
    trust(client, "always")
    with attach(client.app, FakeProvider([save_call(tool), step_answer("Saved.")])):
        first = send(client, "Save this fruit for lunch", request_id="trust-race-original")
    assert first.status_code == 200 and first.json()["saved"], first.text
    first_call_still_writing(monkeypatch)
    if trust_on_retry == "ask":
        trust(client, "ask")
    else:  # trusted when the retry starts, ended by the time it holds the lock
        from app.ai import chat_save
        real, answers = chat_save.effective_trust, iter(["always"])
        monkeypatch.setattr(chat_save, "effective_trust", lambda **kw: next(answers, "ask") if real(**kw) != "ask" else "ask")
    with attach(client.app, FakeProvider([save_call(tool), step_answer("Already saved.")])):
        response = send(client, "Save this fruit for lunch", request_id="trust-race-original")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pending_save"] is None, body
    assert count(client, table) == 1 and count(client, "assistant_ask_keys") == 1
