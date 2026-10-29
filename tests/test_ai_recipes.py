"""AI recipes (note 16 §8, phase 3): ``POST /api/ai/recipes``. The routing and consent, the exact request (the dry run) and what it
never holds, the schema's id enum, every drop reason of §8.5, the title from a template, the app's fit, the steps switch, and
that nothing is ever saved. No network: every call ends in a fake provider."""
from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from ai_support import LEGACY_ROUTING, FakeProvider, attach, chat
from conftest import HTTPS_URL, TestClient, add_user, make_settings, sign_in
from app.ai import presets as P
from app.ai import recipes as AR
from app.config import AiEnv
from app.guidance.messages import BANNED_PATTERN
from app.guidance.rules import INGREDIENT_FLAG
from app.main import create_app

DAY = "2026-10-05"
KEY = "sk-env-0123456789abcdefghijklmn"
TARGETS = {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "carbs_per_meal_g": 60, "protein_g": {"min": 42, "max": 56}}
APPLE, CHICKEN, EGG, JUICE, STAR, BANANA = ("Apple, raw, with skin", "Chicken breast, roasted", "Egg white, raw", "Juice, apple",
                                            "Star fruit (carambola)", "Banana, raw")


@pytest.fixture
def c(tmp_path, foods_json) -> Iterator[TestClient]:
    settings = make_settings(tmp_path, foods_json, ai=AiEnv(provider="openai", api_key=KEY, model="gpt-6-luna"))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as client:
        sign_in(client)
        on(client)
        ready(client)
        yield client


def on(client: TestClient, **extra: Any) -> None:
    r = client.patch("/api/admin/settings", json={"ai.enabled": True, **LEGACY_ROUTING, "ai.route.recipes": "any", **extra})
    assert r.status_code == 200, r.text


def ready(client: TestClient) -> None:
    assert client.put("/api/profile", json={"targets": TARGETS}).status_code == 200
    assert client.patch("/api/me/ai", json={"opt_in": True}).status_code == 200
    pid = client.get("/api/ai/status").json()["provider"]["id"]
    assert client.post("/api/ai/consent", json={"provider_id": pid, "purpose": "text"}).status_code == 200


def food_id(client: TestClient, name: str) -> int:
    for f in client.get("/api/foods", params={"q": name, "limit": 50}).json()["foods"]:
        if f["name"] == name:
            return f["id"]
    raise AssertionError(name)


def suggest(client: TestClient, **body: Any):
    return client.post("/api/ai/recipes", json={"mode": "suggest", "dish": "salad", "makes": 2, "meal": "lunch", "date": DAY, **body})


def answer(*recipes: dict[str, Any], status: str = "ok", refusal: str = "none") -> dict[str, Any]:
    return chat({"recipes": list(recipes), "status": status, "refusal": refusal})


def recipe(items: list[tuple[int, int]], *, dish: str = "salad", theme: str = "light", steps: list[str] | None = None,
           codes: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"dish": dish, "theme": theme, "ingredients": [{"food_id": f, "quarters": q} for f, q in items], "steps": steps or [],
            "reason_codes": codes or ["low_sodium"], **extra}


def run(client: TestClient, *recipes: dict[str, Any], **body: Any) -> dict[str, Any]:
    with attach(client.app, FakeProvider([answer(*recipes)])):
        r = suggest(client, **body)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Gates and routing
# --------------------------------------------------------------------------- #


def test_the_feature_is_listed_and_starts_local(c):
    status = c.get("/api/ai/status").json()
    assert status["routes"]["recipes"]["purpose"] == "text" and status["features"]["recipes"] is True
    assert status["features"]["recipe_steps"] is False  # off until the admin turns it on after a live run
    assert c.get("/api/meta").json()["capabilities"]["ai_recipes"] is True
    assert c.get("/api/admin/settings").json()["settings"]["ai.recipe_steps"]["value"] is False


def test_off_sends_nothing(c):
    on(c, **{"ai.route.recipes": "off"})
    with attach(c.app, FakeProvider([])) as provider:
        r = suggest(c)
    assert r.status_code == 503 and r.json()["reason"] == "feature_off" and provider.calls == 0
    assert c.get("/api/meta").json()["capabilities"]["ai_recipes"] is False


def test_the_new_policy_version_asks_everyone_again(c):
    assert P.POLICY_VERSION == "2026-10-27.1"
    pid = c.get("/api/ai/status").json()["provider"]["id"]
    c.delete(f"/api/ai/consent/{pid}")
    with attach(c.app, FakeProvider([])) as provider:
        r = suggest(c)
    assert r.status_code == 409 and r.json()["consent_required"] is True and provider.calls == 0


@pytest.mark.parametrize("body", [{"dish": None}, {"meal_id": 1}, {"mode": "change", "dish": None},
                                  {"makes": 3}, {"dish": "pie"}, {"extra": 1}])
def test_a_bad_body_is_refused(c, body):
    assert suggest(c, **body).status_code == 400


# --------------------------------------------------------------------------- #
# What is sent
# --------------------------------------------------------------------------- #


def test_other_recipes_leave_out_the_main_foods_already_shown_but_keep_ingredients(tmp_path):
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "data" / "foods.json"
    settings = make_settings(tmp_path, real, ai=AiEnv(provider="openai", api_key=KEY, model="gpt-6-luna"))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        on(c)
        ready(c)
        check_other_recipes(c)


def check_other_recipes(c: TestClient) -> None:
    body = {"mode": "suggest", "dish": "salad", "makes": 2, "meal": "lunch", "date": DAY}

    def candidates(**extra: Any) -> list[dict[str, Any]]:
        dry = c.post("/api/ai/recipes?dry_run=true", json={**body, **extra}).json()
        return json.loads(dry["body"]["messages"][-1]["content"].split("<data>\n", 1)[1].split("\n</data>", 1)[0])["candidates"]

    with attach(c.app, FakeProvider([])) as provider:
        shown = [f["id"] for f in candidates()]
        again = {f["id"] for f in candidates(exclude_food_ids=shown)}
        assert provider.calls == 0
    ingredients = {fid for fid in shown if INGREDIENT_FLAG in c.get(f"/api/foods/{fid}").json()["flags"]}
    assert ingredients and ingredients <= again  # oil, flour and the like stay: nearly every recipe needs them
    assert again - ingredients and not (again - ingredients) & set(shown)  # the main foods are new ones


@pytest.mark.safety
def test_the_dry_run_is_the_request_and_holds_no_recipe_text_or_low_treatment(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    meal = c.post("/api/meals", json={"name": "Grandma's secret stew", "note": "call Ann on 555-0100", "servings_made": 2,
                                      "steps": ["Brown it slowly"], "source_url": "https://example.com/stew",
                                      "items": [{"food_id": apple, "servings": 2}, {"food_id": chicken, "servings": 2}]}).json()["id"]
    body = {"mode": "change", "meal_id": meal, "meal": "lunch", "date": DAY}
    with attach(c.app, FakeProvider([answer(recipe([(apple, 8), (chicken, 8)]))])) as provider:
        dry = c.post("/api/ai/recipes?dry_run=true", json=body).json()
        assert dry["dry_run"] is True and provider.calls == 0
        c.post("/api/ai/recipes", json=body)
        assert provider.bodies()[0] == dry["body"]
    sent = json.dumps(dry["body"])
    for secret in ("Grandma", "secret stew", "555-0100", "Brown it slowly", "example.com", "admin"):
        assert secret not in sent, secret
    data = json.loads(dry["body"]["messages"][-1]["content"].split("<data>\n", 1)[1].split("\n</data>", 1)[0])
    assert data["recipe"]["makes"] == 2 and {i["id"] for i in data["recipe"]["ingredients"]} == {apple, chicken}
    assert data["recipe_request"] == {"mode": "change", "makes": 2.0}
    names = {f["name"] for f in data["candidates"]}
    assert JUICE not in names and STAR not in names and "Glucose tablets" not in names  # never a low treatment or avoid_ckd food
    assert all(f["portion_quarters"] == 4 for f in data["candidates"])  # each food's numbers are for one serving
    schema = json.dumps(dry["body"])
    assert '"maxItems": 0' in schema or '"maxItems":0' in schema  # steps off: the schema allows no step
    system = dry["body"]["messages"][0]["content"]
    assert "Never give, calculate or adjust insulin doses" in system and 'Leave "steps" empty' in system


@pytest.mark.safety
def test_a_recipe_with_a_low_treatment_is_never_sent(c):
    juice, chicken = food_id(c, JUICE), food_id(c, CHICKEN)
    meal = c.post("/api/meals", json={"name": "Smoothie", "servings_made": 1,
                                      "items": [{"food_id": juice, "servings": 1}, {"food_id": chicken, "servings": 1}]}).json()["id"]
    with attach(c.app, FakeProvider([])) as provider:
        r = c.post("/api/ai/recipes", json={"mode": "change", "meal_id": meal, "date": DAY}).json()
    assert r["status"] == "not_sent" and r["ai_called"] is False and provider.calls == 0
    assert "low" not in r["message"].lower()


def test_someone_elses_recipe_is_404(c):
    apple = food_id(c, APPLE)
    meal = c.post("/api/meals", json={"name": "Mine", "items": [{"food_id": apple, "servings": 1}]}).json()["id"]
    sam = add_user(c)
    ready(sam)
    with attach(c.app, FakeProvider([])) as provider:
        assert sam.post("/api/ai/recipes", json={"mode": "change", "meal_id": meal}).status_code == 404
    assert provider.calls == 0


# --------------------------------------------------------------------------- #
# The checks on the answer
# --------------------------------------------------------------------------- #


def test_a_good_recipe_is_shown_with_the_apps_numbers_title_and_body_and_nothing_is_saved(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    before = c.get("/api/meals").json()
    out = run(c, recipe([(apple, 4), (chicken, 4)], dish="salad", codes=["low_sodium", "adds_protein"]))
    assert out["status"] == "ok" and out["feature"] == "recipes" and out["mode"] == "suggest"
    [card] = out["recipes"]
    assert card["title"] == "Chicken breast and apple salad" or card["title"].endswith(" salad")
    assert card["notice"].startswith("AI recipe · ") and card["source"] == "ai"
    assert card["makes"] == 2 and card["body"]["servings_made"] >= 2 and card["body"]["meal_hint"] == "lunch"
    assert {i["food_id"] for i in card["body"]["items"]} == {apple, chicken} and card["body"]["steps"] == []
    assert card["per_serving"]["potassium_mg"] is not None and not BANNED_PATTERN.search(card["why"])
    assert c.get("/api/meals").json() == before  # the server never saves an AI recipe
    assert c.post("/api/meals", json=card["body"]).status_code == 201  # the person's tap saves it through the ordinary route


def test_the_title_is_a_template_even_when_the_model_sends_one(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    out = run(c, recipe([(apple, 4), (chicken, 4)], title="Kidney-safe miracle"))
    assert out["status"] == "dropped_all" and out["dropped"] == [{"index": 0, "reason": "unexpected_field"}]


@pytest.mark.safety
@pytest.mark.parametrize("make, reason", [
    (lambda ids: [(999_999, 4), (ids[CHICKEN], 4)], "not_a_candidate"),
    (lambda ids: [(ids[JUICE], 4), (ids[CHICKEN], 4)], "not_a_candidate"),  # a low treatment, whatever the model says
    (lambda ids: [(ids[STAR], 4), (ids[CHICKEN], 4)], "not_a_candidate"),  # avoid_ckd
    (lambda ids: [(ids[CHICKEN], 4)], "too_few_items"),
    (lambda ids: [(ids[APPLE], 0), (ids[CHICKEN], 4)], "quarters_out_of_range"),
    (lambda ids: [(ids[APPLE], 161), (ids[CHICKEN], 4)], "quarters_out_of_range"),
    (lambda ids: [(ids[APPLE], 160), (ids[CHICKEN], 4)], "share_too_large"),  # 20 servings of apple in each of 2: too much to lower
])
def test_every_drop_has_its_reason(c, make, reason):
    ids = {n: food_id(c, n) for n in (APPLE, CHICKEN, JUICE, STAR)}
    out = run(c, recipe(make(ids)))
    assert out["status"] == "dropped_all" and out["dropped"][0]["reason"] == reason, out


def test_a_share_that_is_only_too_big_is_made_smaller_and_kept(c):
    """7.5 servings of apple in a pot for 2 is 3.75 servings in each serving, above the 3 the meal check accepts. The live run of
    2026-10-29 dropped such a recipe (``share_too_large``); the fit now makes the share smaller and the card says so."""
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    out = run(c, recipe([(apple, 30), (chicken, 4)]))
    assert out["status"] == "ok" and out["dropped"] == [], out
    [card] = out["recipes"]
    n = card["body"]["servings_made"]
    share = {i["food_id"]: i["servings"] / n for i in card["body"]["items"]}
    assert all(q <= 3.0 + 1e-9 for q in share.values())  # one saved serving holds at most 3 servings of any food
    assert card["portion_note"] == AR.FOOD_SWAPPED_TEXT  # the fit swapped the apple for another fruit
    assert card["fit"]["status"] != "fits" and card["fit"]["changes"]  # the fit's own lines say what it changed
    [lowered] = out["portions_lowered"]
    assert lowered["index"] == 0 and lowered["reason"] == "share_too_large"
    assert lowered["changes"] == card["portions_lowered"]
    [change] = lowered["changes"]
    assert change["food_id"] == apple and change["from_servings"] == 3.75
    assert change["to_servings"] == round(share.get(apple, 0.0), 2)  # 0 when the fit swapped the apple out
    row = c.get("/api/ai/audit").json()["events"][0]["verdict_json"]
    assert row["portions_lowered"][0]["reason"] == "share_too_large"


def test_not_for_me_is_dropped(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    assert c.put(f"/api/guidance/preferences/{apple}", json={"preference": "not_for_me"}).status_code == 200
    out = run(c, recipe([(apple, 4), (chicken, 4)]))
    assert out["status"] == "dropped_all" and out["dropped"][0]["reason"] in ("not_for_me", "not_a_candidate")


def test_a_false_claim_is_corrected(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    out = run(c, recipe([(apple, 4), (chicken, 4)], codes=["you_like"]))
    assert out["status"] == "ok" and "you_like" not in out["recipes"][0]["reason_codes"] and out["claims_corrected"] >= 1


def test_a_refusal_and_no_fit(c):
    with attach(c.app, FakeProvider([answer(status="refused", refusal="outside_scope")])):
        assert suggest(c).json()["status"] == "refused"
    with attach(c.app, FakeProvider([answer(refusal="no_fit")])):
        assert suggest(c).json()["status"] == "no_fit"


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #


@pytest.mark.safety
def test_steps_are_dropped_while_the_switch_is_off(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    out = run(c, recipe([(apple, 4), (chicken, 4)], steps=["Chop the apple."]))
    card = out["recipes"][0]
    assert card["steps"] == [] and card["steps_dropped"] == [{"index": 0, "reason": "steps_off"}] and card["steps_label"] is None


@pytest.mark.safety
def test_with_the_switch_on_only_safe_steps_stay_and_carry_the_label(c):
    on(c, **{"ai.recipe_steps": True})
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    steps = ["Chop the apple and the chicken small.", "Have your insulin ready.", "Add 200 g of flour.", "Season with salt.",
             "Bake at 180 C (350 F) for 25 minutes."]
    out = run(c, recipe([(apple, 4), (chicken, 4)], steps=steps))
    card = out["recipes"][0]
    assert card["steps"] == ["Chop the apple and the chicken small.", "Bake at 180 C (350 F) for 25 minutes."]
    assert [d["reason"] for d in card["steps_dropped"]] == ["dose:insulin", "quantity", "unlisted_food"]
    assert card["steps_label"] and "not for cooking times or food safety" in card["steps_label"]
    assert card["body"]["steps"] == card["steps"]
    assert out["steps_dropped"] == 3


def test_the_change_mode_lists_what_differs_and_names_it_reworked(c):
    apple, chicken, egg = food_id(c, APPLE), food_id(c, CHICKEN), food_id(c, EGG)
    meal = c.post("/api/meals", json={"name": "Lunch bowl", "servings_made": 2,
                                      "items": [{"food_id": apple, "servings": 2}, {"food_id": chicken, "servings": 2}]}).json()["id"]
    with attach(c.app, FakeProvider([answer(recipe([(apple, 4), (egg, 8)], dish="bowl"))])):
        out = c.post("/api/ai/recipes", json={"mode": "change", "meal_id": meal, "meal": "lunch", "date": DAY}).json()
    [card] = out["recipes"]
    assert card["title"] == "Lunch bowl (reworked)"
    text = " ".join(card["differences"])
    assert "Added egg white" in text and "Took out chicken breast" in text and "instead of" in text


def test_only_one_recipe_comes_back_from_a_rework(c):
    apple, chicken = food_id(c, APPLE), food_id(c, CHICKEN)
    meal = c.post("/api/meals", json={"name": "Two", "servings_made": 1,
                                      "items": [{"food_id": apple, "servings": 1}, {"food_id": chicken, "servings": 1}]}).json()["id"]
    r = recipe([(apple, 4), (chicken, 4)])
    with attach(c.app, FakeProvider([answer(r, r)])):
        out = c.post("/api/ai/recipes", json={"mode": "change", "meal_id": meal, "date": DAY}).json()
    assert len(out["recipes"]) == 1 and out["dropped"] == [{"index": 1, "reason": "too_many_recipes"}]


def test_the_title_template():
    from guidance.fixtures import foods

    fs = foods()
    title = AR.title_for([(fs[3], 4), (fs[1], 4)], "soup")
    assert title.endswith(" soup") and title[0].isupper() and len(title) <= AR.NAME_MAX
