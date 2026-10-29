"""Recipes that fit (note 16 §9): ``check_meal`` kind ``recipe``, ``fit_recipe`` on the note 06 fixture, and
``POST /api/guidance/fit-recipe``.

The fixture day: breakfast eaten, lunch planned, so dinner has 750 mg of potassium, 167 mg of phosphorus, 600 mg of sodium and
60 g of carbohydrate (tolerance 10 g) of room."""
from __future__ import annotations

from typing import Any

import pytest

from app.guidance import rules as R
from app.guidance.messages import BANNED_PATTERN
from app.guidance.recipes import Target, fit_recipe, shares
from app.guidance.score import check_meal
from fixtures import context, foods
from test_api_guidance import DAY, food_id, real, set_targets  # noqa: F401  (real is a fixture)

FS = foods()
DINNER = Target("meal", "dinner")


def fit(items: list[tuple[int, float]], n: float | None = 4, target: Target = DINNER, **ctx: Any) -> dict[str, Any]:
    return fit_recipe(context(**ctx), [(FS[i], q) for i, q in items], n, target)


def texts(result: dict[str, Any]) -> list[str]:
    return [c["text"] for c in result["changes"]]


# --------------------------------------------------------------------------- check_meal kind "recipe"


def test_the_recipe_kind_allows_small_shares_ingredients_and_low_treatments_but_not_more_than_three_servings():
    ctx = context()
    from app.guidance.budget import meal_room

    room = meal_room(ctx, "dinner")
    small = [(FS[1], 0.1), (FS[5], 0.1)]
    assert not check_meal(small, room, kind="saved").ok and check_meal(small, room, kind="saved").reason == "portion_out_of_range"
    assert check_meal(small, room, kind="recipe").ok
    assert check_meal([(FS[12], 0.5)], room, kind="recipe").ok  # a juice the person put in their own recipe
    assert check_meal([(FS[7], 3.5)], room, kind="recipe").reason == "portion_out_of_range"


# --------------------------------------------------------------------------- fit_recipe


def test_a_pot_for_four_is_judged_one_serving_at_a_time():
    pot = [(3, 4), (1, 4), (5, 4)]
    assert fit(pot, n=4)["before"]["per_serving"]["potassium_mg"] == 365
    assert fit(pot, n=None)["before"]["per_serving"]["potassium_mg"] == 1460  # the same pot as one serving
    assert fit(pot, n=4)["status"] != "does_not_fit"


def test_a_recipe_that_fits_is_left_alone():
    r = fit([(1, 2), (5, 2)], n=2)
    assert r["status"] == "fits" and r["changes"] == [] and r["fitted"]["items"][0]["servings"] == 2
    assert r["fitted"]["log_scale"] == 0.5


def test_lowering_never_touches_protein_and_stops_at_the_floor():
    r = fit([(3, 4), (1, 4), (5, 4)], n=None)  # the whole pot as one serving: far over
    for c in r["changes"]:
        assert not (c["code"] == "lowered" and c["food_id"] == 3), c
    for item in (r["fitted"] or r["closest"])["items"]:
        if item["food_id"] == 3:
            assert item["servings"] == 4  # chicken stays
        else:
            assert item["servings"] >= 2  # at least half of 4


def test_a_low_treatment_is_never_lowered_or_swapped():
    r = fit([(12, 8), (1, 2)], n=1)  # 8 × apple juice in one serving
    items = (r["fitted"] or r["closest"])["items"]
    assert {i["food_id"]: i["servings"] for i in items}[12] == 8
    assert all(c.get("food_id") != 12 and c.get("from_food_id") != 12 for c in r["changes"] if c["code"] != "does_not_fit")


def test_a_food_to_avoid_is_swapped_and_the_line_says_why():
    r = fit([(9, 1), (1, 1)], n=1)
    assert r["status"] == "fits_after_changes"
    [change] = r["changes"]
    assert change["code"] == "swapped" and change["from_food_id"] == 9 and change["food_id"] != 9
    assert "foods to avoid with kidney disease" in change["text"]


def test_a_smaller_serving_is_offered_when_lowering_and_swaps_are_not_enough():
    r = fit([(3, 4), (1, 4), (5, 4)], n=4)
    assert r["status"] == "fits_smaller_serving" and r["fitted"]["serving_fraction"] in R.RECIPE_SERVING_FRACTIONS
    assert r["changes"][-1]["code"] == "smaller_serving"
    assert r["fitted"]["log_scale"] == pytest.approx(r["fitted"]["serving_fraction"] / 4, abs=1e-4)
    assert all(c["ok"] for c in r["after"]["checks"])


def test_what_does_not_fit_shows_the_closest_and_has_nothing_to_save():
    r = fit([(3, 4), (1, 4), (5, 4)], n=None)
    assert r["status"] == "does_not_fit" and r["fitted"] is None and r["after"] is None
    assert r["closest"]["serving_fraction"] == 0.5 and r["still_over"]
    assert r["changes"][-1]["code"] == "does_not_fit" and "Still over" in r["changes"][-1]["text"]


def test_the_day_target_has_no_carbohydrate_check():
    r = fit([(1, 8)], n=4, target=Target("day"))  # 90 g carbohydrate per serving
    assert "carbs_g" not in {c["nutrient"] for c in r["before"]["checks"]}
    assert r["status"] == "fits"


def test_unknown_values_stay_unknown():
    from fixtures import food

    fs = dict(FS)
    fs[20] = food((20, "Mystery soup", "Soups", "1 cup (240 g)", 240, 10, 2, None, None, None, 0, ()))
    r = fit_recipe(context(food_map=fs), [(fs[20], 4)], 4, DINNER)
    assert r["before"]["per_serving"]["potassium_mg"] is None and r["before"]["unknown"]["potassium_mg"] == 1


def _without(fid: int, **missing: None) -> dict[int, Any]:
    """The fixture foods with one food that does not list some values (``potassium_mg=None``)."""
    from app.guidance.vectors import make_food

    f = FS[fid]
    fs = dict(FS)
    fs[fid] = make_food(id=f.id, name=f.name, category=f.category, serving_desc=f.serving_desc, serving_g=f.serving_g,
                        nutrients={**f.nutrients, **missing}, flags=f.flags, source="builtin")
    return fs


def _fit_with(fs: dict[int, Any], items: list[tuple[int, float]], n: float | None, target: Target = DINNER) -> dict[str, Any]:
    return fit_recipe(context(food_map=fs), [(fs[i], q) for i, q in items], n, target)


def test_a_value_some_foods_do_not_list_is_at_least_in_every_change_line():
    # Lowered potatoes; the green beans list no potassium, so both per-serving figures are "at least".
    r = _fit_with(_without(5, potassium_mg=None), [(2, 4), (5, 4)], 4)
    assert r["status"] == "fits_after_changes"
    assert r["before"]["unknown"]["potassium_mg"] == 1 and r["after"]["unknown"]["potassium_mg"] == 1
    assert texts(r) == ["Used 3¼ × 1 medium (173 g) of Potato, baked instead of 4 × 1 medium (173 g), to keep potassium within "
                        "this dinner's room. Potassium per serving: at least 925 → at least 752 mg (app figures)."]
    # A smaller serving; the rice lists no phosphorus.
    r = _fit_with(_without(1, phosphorus_mg=None), [(3, 4), (1, 4), (5, 4)], 4)
    assert r["status"] == "fits_smaller_serving"
    assert texts(r)[-1] == ("Have ¾ of a serving: a full serving would use at least 215 mg of phosphorus against 167 mg of room; "
                            "¾ uses at least 161 mg (app figures).")
    # Swaps; the chicken lists no potassium or protein, and the food it is swapped for does.
    r = _fit_with(_without(3, potassium_mg=None, protein_g=None), [(2, 8), (3, 4)], 4, Target("meal", "lunch"))
    assert "Potassium per serving: at least 1,850 → 100 mg; protein at least 8 → 6.9 g (app figures)." in texts(r)[0]
    # Does not fit; the green beans list no phosphorus.
    r = _fit_with(_without(5, phosphorus_mg=None), [(3, 4), (1, 4), (5, 4)], None)
    assert r["status"] == "does_not_fit"
    assert "Still over: phosphorus at least 460 mg against 167 mg of room (app figures)." in texts(r)[-1]
    # With every value listed, the lines are unchanged: no "at least".
    assert not any("at least" in t for t in texts(fit([(2, 8), (3, 4), (5, 4)], n=4)))


def test_every_line_is_plain_words_with_no_banned_term_and_the_app_figures():
    cases = [([(3, 4), (1, 4), (5, 4)], 4), ([(3, 4), (1, 4), (5, 4)], None), ([(9, 1), (1, 1)], 1), ([(2, 8), (3, 4)], 4)]
    for items, n in cases:
        for text in texts(fit(items, n=n)):
            assert not BANNED_PATTERN.search(text), text
            assert "insulin" not in text.lower()


def test_the_fit_is_deterministic():
    first = fit([(2, 8), (3, 4), (5, 4)], n=4)
    assert all(fit([(2, 8), (3, 4), (5, 4)], n=4) == first for _ in range(3))


def test_shares_divide_by_the_servings_and_the_fraction():
    from app.guidance.recipes import Item

    items = [Item(FS[1], 4.0, 4.0)]
    assert shares(items, 4.0, 0.5) == [(FS[1], 0.5)]


# --------------------------------------------------------------------------- the route


def saved(client, body: dict[str, Any]) -> int:
    r = client.post("/api/meals", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_the_route_fits_a_saved_recipe_and_a_draft_and_writes_nothing(real):  # noqa: F811
    set_targets(real)
    rice = food_id(real, "Rice, white, long-grain, cooked")
    meal = saved(real, {"name": "Rice pot", "servings_made": 4, "items": [{"food_id": rice, "servings": 4}]})
    before = real.get("/api/meals").json()
    r = real.post("/api/guidance/fit-recipe", json={"meal_id": meal, "target": {"meal": "dinner", "date": DAY}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("fits", "fits_after_changes", "fits_smaller_serving")
    assert body["target"] == {"kind": "meal", "meal": "dinner", "date": DAY} and body["rules_version"] == R.RULES_VERSION
    draft = real.post("/api/guidance/fit-recipe", json={"items": [{"food_id": rice, "servings": 4}], "servings_made": 4,
                                                        "target": {"meal": "dinner", "date": DAY}}).json()
    assert draft["before"] == body["before"]
    day = real.post("/api/guidance/fit-recipe", json={"meal_id": meal, "target": {"kind": "day", "date": DAY}}).json()
    assert day["target"] == {"kind": "day", "meal": None, "date": DAY}
    assert real.get("/api/meals").json() == before  # nothing written
    assert real.get("/api/log", params={"date": DAY}).json()["entries"] == []


def test_the_route_is_scoped_to_the_person(real):  # noqa: F811
    from conftest import add_user

    set_targets(real)
    rice = food_id(real, "Rice, white, long-grain, cooked")
    meal = saved(real, {"name": "Mine", "servings_made": 2, "items": [{"food_id": rice, "servings": 2}]})
    sam = add_user(real)
    set_targets(sam)
    assert sam.post("/api/guidance/fit-recipe", json={"meal_id": meal}).status_code == 404
    soup = real.post("/api/log/quick", json={"date": DAY, "meal": "lunch", "name": "Admin's own soup",
                                             "nutrients": {"carbs_g": 20, "potassium_mg": 50}}).json()["food_id"]
    assert sam.post("/api/guidance/fit-recipe", json={"items": [{"food_id": soup, "servings": 1}]}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"meal_id": 1, "items": [{"food_id": 1, "servings": 1}]}, {"items": []},
                                  {"items": [{"food_id": 1, "servings": 41}]}, {"meal_id": 1, "target": {"kind": "week"}},
                                  {"meal_id": 1, "extra": 1}])
def test_the_route_refuses_a_bad_body(real, body):  # noqa: F811
    set_targets(real)
    assert real.post("/api/guidance/fit-recipe", json=body).status_code == 400


def test_the_route_answers_no_targets_first(real):  # noqa: F811
    rice = food_id(real, "Rice, white, long-grain, cooked")
    r = real.post("/api/guidance/fit-recipe", json={"items": [{"food_id": rice, "servings": 1}]})
    assert r.json()["status"] == "no_targets"
