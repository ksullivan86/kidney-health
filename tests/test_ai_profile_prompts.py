"""The meal ideas and Ask prompts are worded from the profile (docs/ROADMAP.md, "Kidney-only profile: diabetes as an option,
not an assumption", part 3), checked on the requests the routes really build (the dry run is exactly what is sent):

* meal ideas and the Ask chat carry the person's condition from the profile: kidney disease stage (or "not chosen yet"),
  dialysis if any, and a diabetes type only when the profile has one; a profile with diabetes "None" says kidney disease
  only and gets no per-meal or per-snack carbohydrate goals in the data; a profile not chosen yet is not assumed to have
  type 1 (the stored default is not sent as an answer);
* nothing else about the prompts depends on the profile: the low-treatment rules and the hypo purpose of a logged food are
  the same text for every profile, and the rule-based low and emergency answers still never call the model;
* describe a meal, label and plate photo carry no profile data at all (one fixed sentence);
* no identity in any of them.

The text of each prompt is pinned in ``tests/test_ai_prompts.py``. No network."""
from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, attach
from conftest import HTTPS_URL, TestClient, sign_in
from app.ai import prompts
from app.main import create_app
from test_ai_chat import ask, become_ready
from test_ai_prompts import (ASSUMES_DIABETES, CHAT_LOW_RULE, CHAT_SAVE_LOW, DATA, HYPO_PURPOSE, MEAL_LOW_RULE,
                             TASK_LOW_RULE)
from test_ai_routes import TARGETS, ai_settings, enable
from test_vision_api import LABEL_JPG, PLATE_JPG, photo

DAY = "2026-10-05"
SECRET_NAME = "Margaret Example"
BODY = {"weight_kg": 71.3, "height_cm": 168, "birth_month": "1961-04", "sex": "female"}
CONDITION = {
    "type1": "chronic kidney disease (CKD, stage 4) and type 1 diabetes",
    "kidney_only": "chronic kidney disease only (CKD, stage 3b)",
    "not_chosen": ("chronic kidney disease (CKD, stage not chosen yet); whether they also have diabetes is not chosen yet, "
                   "so do not assume that they do or that they do not"),
}
PROFILES: dict[str, dict[str, Any]] = {
    "type1": {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1"},
    "kidney_only": {"ckd_stage": "3b", "dialysis": "none", "diabetes": "none"},
    "not_chosen": {},  # neither a stage nor a diabetes type picked: the stored defaults (3b, type 1) are not an answer
}


@pytest.fixture(params=sorted(PROFILES))
def person_client(request, tmp_path, foods_json) -> Iterator[tuple[str, TestClient]]:
    """A signed-in person with AI, the Ask chat and plate photos on, the profile of ``request.param`` and every consent."""
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.vision_plate_enabled": True})
        targets = {**TARGETS, "carbs_g": 200, "carbs_per_snack_g": 15}
        assert c.put("/api/profile", json={**PROFILES[request.param], **BODY, "targets": targets}).status_code == 200
        assert c.patch("/api/me", json={"display_name": SECRET_NAME}).status_code == 200
        pid = become_ready(c, targets=False)
        for purpose in ("text", "photos"):
            assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose}).status_code == 200
        yield request.param, c


def system_of(body: dict[str, Any]) -> str:
    assert body["messages"][0]["role"] == "system"
    return body["messages"][0]["content"]


def dry_runs(c: TestClient) -> dict[str, dict[str, Any]]:
    """The request each feature would send (the dry run), by feature."""
    out: dict[str, dict[str, Any]] = {}
    r = c.post("/api/ai/next-meal", params={"dry_run": "true"}, json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
    out["next_meal"] = r.json()["body"]
    r = c.post("/api/ai/parse-meal", params={"dry_run": "true"}, json={"text": "2 eggs and toast", "date": DAY})
    assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
    out["parse_meal"] = r.json()["body"]
    r = ask(c, "what is left today", dry_run="true")
    assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
    out["chat"] = r.json()["body"]
    for kind, jpeg in (("label", LABEL_JPG), ("plate", PLATE_JPG)):
        r = photo(c, f"/api/vision/{kind}", jpeg, dry_run="true")
        assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
        out[kind] = r.json()["body"]
    return out


def test_meal_ideas_and_ask_word_their_system_message_from_the_profile(person_client):
    name, c = person_client
    sent = dry_runs(c)
    person = json.loads(DATA.search(sent["next_meal"]["messages"][1]["content"]).group(1))["person"]
    assert system_of(sent["next_meal"]) == prompts.system_prompt(person)
    assert system_of(sent["chat"]).startswith(prompts.chat_prompt(person))
    for feature in ("next_meal", "chat"):
        assert CONDITION[name] in system_of(sent[feature]), (name, feature)
        assert "[[" not in system_of(sent[feature]), feature
        assert "insulin" in system_of(sent[feature]) and "Never diagnose" in system_of(sent[feature]), (name, feature)
    if name != "type1":  # nothing in the instructions assumes diabetes for a profile that does not say so
        for feature in ("next_meal", "chat"):
            assert not ASSUMES_DIABETES.search(system_of(sent[feature]).split("PERSON: ")[0]), (name, feature)


def test_describe_a_meal_and_photos_carry_no_profile_data(person_client):
    _, c = person_client
    sent = dry_runs(c)
    for feature in ("parse_meal", "label", "plate"):
        assert system_of(sent[feature]) == prompts.TASK_SYSTEM_PROMPT, feature  # the same text for every profile
        assert "and sometimes diabetes" in system_of(sent[feature])
        text = json.dumps(sent[feature])
        assert "stage" not in text.lower() and "type 1" not in text and '"diabetes"' not in text, feature


@pytest.mark.safety
def test_the_low_rules_and_the_hypo_purpose_are_the_same_for_every_profile(person_client):
    """Nothing about treating a low depends on the profile (a person with "None" can still have a low)."""
    _, c = person_client
    sent = dry_runs(c)
    assert MEAL_LOW_RULE in system_of(sent["next_meal"])
    chat = system_of(sent["chat"])
    assert CHAT_LOW_RULE in chat and CHAT_SAVE_LOW in chat and HYPO_PURPOSE in chat
    assert '"purpose"' in chat  # log_food still lists the purpose
    for feature in ("parse_meal", "label", "plate"):
        assert TASK_LOW_RULE in system_of(sent[feature]), feature


def test_what_the_profile_changes_in_the_data(person_client):
    name, c = person_client
    sent = dry_runs(c)
    data = json.loads(DATA.search(sent["next_meal"]["messages"][1]["content"]).group(1))
    person_in_chat = system_of(sent["chat"]).split("PERSON: ", 1)[1]
    if name == "type1":
        assert (data["person"]["ckd_stage"], data["person"]["diabetes"]) == ("4", "type1")
        assert data["targets"]["carbs_per_meal_g"] == 60 and data["targets"]["carbs_per_snack_g"] == 15
    elif name == "kidney_only":
        assert (data["person"]["ckd_stage"], data["person"]["diabetes"]) == ("3b", "none")
        assert "carbs_per_meal_g" not in data["targets"] and "carbs_per_snack_g" not in data["targets"]
        assert "carbs_g" not in data["meal_budget"]  # the rules already leave out the meal's carbohydrate goal
        assert data["targets"]["carbs_g"] == 200  # the day's carbohydrate is judged like any nutrient
        assert '"diabetes":"none"' in person_in_chat
    else:
        assert (data["person"]["ckd_stage"], data["person"]["diabetes"]) == (None, None)  # not the stored 3b and type 1
        assert '"ckd_stage":null' in person_in_chat and '"diabetes":null' in person_in_chat


def test_no_identity_in_any_request(person_client):
    _, c = person_client
    for feature, body in dry_runs(c).items():
        # safety_identifier is a keyed hash (hex): a digit run like "168" in it is chance, not the profile
        text = json.dumps({k: v for k, v in body.items() if k != "safety_identifier"}, ensure_ascii=False)
        assert body.get("safety_identifier") is None or "admin" not in body["safety_identifier"]
        for never in ("Margaret", "Example", "71.3", "168", "1961", "female", "admin", "@", DAY):
            assert never not in text.replace("administrator", ""), (feature, never)


@pytest.mark.safety
def test_a_low_and_an_emergency_are_answered_by_the_app_for_every_profile(person_client):
    """The rule-based pre-filters are code, not prompt wording: the same cards, no model call, for every profile."""
    _, c = person_client
    with attach(c.app, FakeProvider()) as provider:
        low = ask(c, "I feel shaky and low").json()
        emergency = ask(c, "I have chest pain and I can't breathe").json()
        parse = c.post("/api/ai/parse-meal", json={"text": "I am shaky and sweaty, sugar dropped", "date": DAY}).json()
        assert provider.calls == 0
    assert (low["kind"], low["ai_called"]) == ("treat_low", False) and low["cards"][0]["title"] == "Treating a low"
    assert (emergency["kind"], emergency["ai_called"]) == ("get_help_now", False)
    assert parse["cards"][0]["title"] == "Treating a low"
