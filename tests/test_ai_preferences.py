"""What the optional AI is told about taste, and how its claim is checked (note 09 §4.7, decision Q3; part C of "Learn my
food preferences"). The Ask tool that proposes a taste is in ``tests/test_ai_chat_preference.py``; the guard's own checks of
the ``you_like`` claim are in ``tests/test_ai_guard_preferences.py``.

* The ``person`` object of meal ideas and Ask carries ``likes``, ``less_often`` and ``not_for_me``: the foods and food groups
  the person chose, by name, cleaned like any untrusted name (NFKC, no control or format characters, at most 60 characters),
  at most 10 each, null when empty. Only their explicit choices: never a learned signal, never a ``neutral`` row.
* They go where the person block already goes (meal ideas and Ask), behind the gates those features already pass, and the dry
  run ("What will be sent?") shows them. Describe-a-meal, label and plate photos and lab report photos never get them.
* A candidate of the meal ideas data carries ``liked`` next to ``often``; an idea claiming "you said you like this" through
  the real route keeps the claim only for a liked candidate.
No network."""
from __future__ import annotations

import inspect
import json
from datetime import date, timedelta
from typing import Any, Iterator

import pytest

from ai_support import FakeProvider, attach, chat
from conftest import HTTPS_URL, TestClient, add_user, sign_in
from app.ai import prompts
from app.ai import routes as ai_routes
from app.main import create_app
from test_ai_chat import ask, become_ready
from test_ai_prompts import DAY, PROFILE, data_of
from test_ai_routes import ai_settings, enable
from test_vision_api import LABEL_JPG, PLATE_JPG, photo

NAMES = ("Apple, raw, with skin", "Chicken breast, roasted", "Egg white, raw")


@pytest.fixture
def ai(tmp_path, foods_json) -> Iterator[TestClient]:
    """A signed-in person with meal ideas, Ask and plate photos on, every consent given, no taste chosen yet."""
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.vision_plate_enabled": True})
        assert c.put("/api/profile", json=PROFILE).status_code == 200
        pid = become_ready(c, targets=False)
        for purpose in ("text", "photos"):
            assert c.post("/api/ai/consent", json={"provider_id": pid, "purpose": purpose}).status_code == 200
        yield c


def food_id(c: TestClient, name: str) -> int:
    hits = c.get("/api/foods", params={"q": name.split(",")[0], "limit": 50}).json()["foods"]
    return int(next(f for f in hits if f["name"] == name)["id"])


def mark(c: TestClient, name: str, preference: str) -> None:
    assert c.put(f"/api/guidance/preferences/{food_id(c, name)}", json={"preference": preference}).status_code == 200


def guidance(c: TestClient) -> dict[str, Any]:
    return c.get("/api/me/settings").json()["settings"]["guidance"]["value"]


def set_groups(c: TestClient, **lists: list[str]) -> None:
    assert c.patch("/api/me/settings", json={"guidance": {**guidance(c), **lists}}).status_code == 200


def ideas_person(c: TestClient) -> dict[str, Any]:
    r = c.post("/api/ai/next-meal", params={"dry_run": "true"}, json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
    return data_of(r.json()["body"])["person"]


# --------------------------------------------------------------------------- #
# The person block
# --------------------------------------------------------------------------- #


def test_names_are_cleaned_capped_deduplicated_and_null_when_empty():
    assert prompts.taste_names(None) is None and prompts.taste_names([]) is None and prompts.taste_names(["", "  ", "​"]) is None
    assert prompts.taste_names(["Ｓａｌｍｏｎ", "Salmon", "  Tuna‮ ​ fish  "]) == ["Salmon", "Tuna fish"]  # NFKC, no Cf, one space
    assert prompts.taste_names(["x" * 100]) == ["x" * 60]
    assert prompts.taste_names([f"food {i}" for i in range(25)]) == [f"food {i}" for i in range(10)]
    assert prompts.taste_names(["a\u0007b\nc"]) == ["ab c"]  # control characters out, a line break is a space
    assert prompts.taste_names([None, 5, "ok"]) == ["ok"]  # only text is a name
    assert prompts.TASTE_NAME_CHARS == 60 and prompts.TASTE_NAMES_MAX == 10
    assert prompts.TASTE_KEYS == ("likes", "less_often", "not_for_me")


def test_the_person_block_has_the_three_keys_and_nothing_else_changes():
    profile = {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "sex": "female", "birth_month": "1961-04"}
    plain = prompts.person_block(profile, {}, date(2026, 10, 5))
    assert plain == {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "preferences": None, "age_band": None, "sex": None,
                     "likes": None, "less_often": None, "not_for_me": None}
    tastes = {"likes": ["Salmon"], "less_often": [], "not_for_me": ["Olives", "Beverages"], "learned": ["Banana"], "neutral": ["Egg"]}
    block = prompts.person_block(profile, {"preferences": "no pork"}, date(2026, 10, 5), tastes)
    assert block["likes"] == ["Salmon"] and block["less_often"] is None and block["not_for_me"] == ["Olives", "Beverages"]
    assert "learned" not in block and "neutral" not in block and "Banana" not in json.dumps(block)  # only the three lists are read
    rest = {k: v for k, v in plain.items() if k not in prompts.TASTE_KEYS}
    assert {k: v for k, v in block.items() if k not in prompts.TASTE_KEYS} == {**rest, "preferences": "no pork"}


def test_the_dry_run_of_meal_ideas_shows_the_explicit_choices_by_name(ai):
    c = ai
    assert (lambda p: (p["likes"], p["less_often"], p["not_for_me"]))(ideas_person(c)) == (None, None, None)
    mark(c, "Apple, raw, with skin", "like")
    mark(c, "Chicken breast, roasted", "less")
    mark(c, "Egg white, raw", "not_for_me")
    mark(c, "Banana, raw", "neutral")
    set_groups(c, like_categories=["Fruits"], exclude_categories=["Beverages"])
    person = ideas_person(c)
    assert person["likes"] == ["Apple, raw, with skin", "Fruits"] and person["less_often"] == ["Chicken breast, roasted"]
    assert person["not_for_me"] == ["Egg white, raw", "Beverages"]
    assert "Banana" not in json.dumps(person)


def test_each_list_holds_at_most_ten_names_most_recent_first(ai):
    c = ai
    for i in range(14):
        made = c.post("/api/foods", json={"name": f"Soup number {i:02d}", "serving_desc": "1 cup (100 g)", "serving_g": 100,
                                          "nutrients": {"potassium_mg": 100}})
        assert c.put(f"/api/guidance/preferences/{made.json()['id']}", json={"preference": "like"}).status_code == 200
    likes = ideas_person(c)["likes"]
    assert len(likes) == 10 and likes[0] == "Soup number 13"


def test_a_learned_signal_never_enters_the_person_block(ai):
    c = ai
    apple = food_id(c, "Apple, raw, with skin")
    for back in range(1, 7):  # eaten on six of the last 14 days: a learned "often"
        day = (date.today() - timedelta(days=back)).isoformat()
        assert c.post("/api/log", json={"date": day, "meal": "breakfast", "food_id": apple, "servings": 1}).status_code == 201
    assert any(i["kind"] == "often" for i in c.get("/api/guidance/learned").json()["items"])
    person = ideas_person(c)
    assert (person["likes"], person["less_often"], person["not_for_me"]) == (None, None, None)
    sent = c.post("/api/ai/next-meal", params={"dry_run": "true"}, json={"meal": "dinner", "date": DAY}).json()["body"]
    assert "Apple" in json.dumps(data_of(sent)["candidates"])  # the candidate is there, with its "often" bit but not as a taste


# --------------------------------------------------------------------------- #
# Where it goes, and where it does not
# --------------------------------------------------------------------------- #


def dry_runs(c: TestClient) -> dict[str, str]:
    """The text of every request the app would send for each AI feature, by feature (the dry run is exactly what is sent)."""
    out: dict[str, str] = {}
    r = c.post("/api/ai/next-meal", params={"dry_run": "true"}, json={"meal": "dinner", "date": DAY})
    out["next_meal"] = json.dumps(r.json()["body"], ensure_ascii=False)
    r = c.post("/api/ai/parse-meal", params={"dry_run": "true"}, json={"text": "2 eggs and toast", "date": DAY})
    out["parse_meal"] = json.dumps(r.json()["body"], ensure_ascii=False)
    r = ask(c, "what is left today", dry_run="true")
    out["chat"] = json.dumps(r.json()["body"], ensure_ascii=False)
    for kind, jpeg in (("label", LABEL_JPG), ("plate", PLATE_JPG)):
        r = photo(c, f"/api/vision/{kind}", jpeg, dry_run="true")
        assert r.status_code == 200 and r.json()["dry_run"] is True, r.text
        out[kind] = json.dumps(r.json()["body"], ensure_ascii=False)
    return out


def test_tastes_are_in_meal_ideas_and_ask_and_in_no_other_feature(ai):
    c = ai
    mark(c, "Apple, raw, with skin", "like")
    mark(c, "Egg white, raw", "not_for_me")
    set_groups(c, less_categories=["Beverages"])
    sent = dry_runs(c)
    for feature in ("next_meal", "chat"):
        assert "Apple, raw, with skin" in sent[feature] and "Egg white, raw" in sent[feature] and "Beverages" in sent[feature], feature
    for feature in ("parse_meal", "label", "plate"):
        assert "Beverages" not in sent[feature] and "less_often" not in sent[feature] and "not_for_me" not in sent[feature], feature
        assert "Apple, raw, with skin" not in sent[feature] and "Egg white, raw" not in sent[feature], feature


def test_only_the_two_features_with_a_person_block_build_one():
    source = inspect.getsource(ai_routes)
    assert source.count("_person(conn, state, user") == 2  # the meal ideas and the Ask chat build one; nothing else calls it
    assert source.count("explicit_preferences(") == 1  # read in one place
    from app.ai import features, lab_report

    for module in (features, lab_report):
        assert "explicit_preferences(" not in inspect.getsource(module)
    assert "person_block" not in inspect.getsource(lab_report)


def test_nothing_is_sent_without_the_persons_opt_in_or_the_hosts_consent(ai):
    c = ai
    mark(c, "Apple, raw, with skin", "like")
    pid = c.get("/api/ai/status").json()["provider"]["id"]
    assert c.delete(f"/api/ai/consent/{pid}", params={"purpose": "text"}).status_code == 204
    with attach(c.app, FakeProvider()) as provider:
        r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 409 and r.json()["consent_required"] is True
        assert c.patch("/api/me/ai", json={"opt_in": False}).status_code == 200
        r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
        assert r.status_code == 503 and r.json()["reason"] == "not_opted_in"
        assert provider.requests == []


def test_another_persons_tastes_are_never_in_my_requests(ai):
    c = ai
    sam = add_user(c)
    assert sam.put("/api/profile", json={"targets": PROFILE["targets"]}).status_code == 200
    mark(c, "Apple, raw, with skin", "like")
    sams_apple = food_id(sam, "Apple, raw, with skin")
    assert sam.put(f"/api/guidance/preferences/{sams_apple}", json={"preference": "not_for_me"}).status_code == 200
    assert ideas_person(c)["not_for_me"] is None and ideas_person(c)["likes"] == ["Apple, raw, with skin"]


# --------------------------------------------------------------------------- #
# The "liked" bit and the claim, through the real route
# --------------------------------------------------------------------------- #


def candidates(c: TestClient) -> dict[str, dict[str, Any]]:
    r = c.post("/api/ai/next-meal", params={"dry_run": "true"}, json={"meal": "dinner", "date": DAY})
    return {x["name"]: x for x in data_of(r.json()["body"])["candidates"]}


def idea_answer(c: TestClient, name: str, *codes: str) -> dict[str, Any]:
    fid = candidates(c)[name]["id"]
    return chat({"status": "ok", "refusal": "none", "ideas": [
        {"theme": "light", "items": [{"food_id": fid, "quarters": 4}], "reason_codes": list(codes), "handbook": []}]})


def test_a_candidate_carries_liked_next_to_often_and_only_for_a_marked_food(ai):
    c = ai
    assert {x["liked"] for x in candidates(c).values()} == {False}
    mark(c, "Apple, raw, with skin", "like")
    mark(c, "Chicken breast, roasted", "less")
    found = candidates(c)
    assert found["Apple, raw, with skin"]["liked"] is True and found["Apple, raw, with skin"]["often"] is False
    assert all(x["liked"] is False for n, x in found.items() if n != "Apple, raw, with skin")
    assert all("you_like" not in x["reasons"] for x in found.values())
    set_groups(c, like_categories=["Meat, Poultry & Eggs"])  # a liked group is not a liked food
    assert [n for n, x in candidates(c).items() if x["liked"]] == ["Apple, raw, with skin"]


def test_the_you_like_claim_survives_for_a_liked_candidate_and_is_corrected_for_another(ai):
    c = ai
    mark(c, "Apple, raw, with skin", "like")
    with attach(c.app, FakeProvider([idea_answer(c, "Apple, raw, with skin", "you_like")])):
        r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200, r.text
    [shown] = r.json()["ideas"]
    assert shown["reason_codes"] == ["you_like"] and r.json()["claims_corrected"] == 0
    assert shown["why"] == "Uses a food you said you like."
    c.app.state.ai.answers.drop_user(1)
    with attach(c.app, FakeProvider([idea_answer(c, "Chicken breast, roasted", "you_like", "adds_protein")])):
        r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    [shown] = r.json()["ideas"]
    assert "you_like" not in shown["reason_codes"] and r.json()["claims_corrected"] == 1
    assert "like" not in shown["why"]


def test_a_food_the_person_said_not_for_me_is_never_a_candidate_and_an_idea_naming_it_is_dropped(ai):
    c = ai
    egg = food_id(c, "Egg white, raw")
    mark(c, "Egg white, raw", "not_for_me")
    assert "Egg white, raw" not in candidates(c)
    answer = chat({"status": "ok", "refusal": "none", "ideas": [
        {"theme": "light", "items": [{"food_id": egg, "quarters": 4}], "reason_codes": ["adds_protein"], "handbook": []}]})
    with attach(c.app, FakeProvider([answer])):
        r = c.post("/api/ai/next-meal", json={"meal": "dinner", "date": DAY})
    assert r.status_code == 200 and r.json()["ideas"] == [] and r.json()["dropped"][0]["reason"] == "not_for_me"
