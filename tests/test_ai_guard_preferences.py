"""Food preferences in the AI guard (note 09 §4.7, part C): the ``liked`` bit of a candidate, the ``you_like`` reason code,
and what the person said no to. Pure: the guidance engine's note 06 §6.1 fixture context, no database, no network.

* A "you said you like this" claim is true only for a candidate the person marked Like (the ``liked`` bit the model was
  shown), exactly the way "you eat this often" is true only for a candidate with the ``often`` bit. A false claim is
  removed and counted (``claims_corrected``); the sentence the person reads is the server's.
* ``you_like`` is in the closed lists the wire schemas and the guard use.
* An idea that uses a food the person marked Not for me, or a food of a group they never want suggested, is dropped
  whatever the model said, even when the food only reached the model as part of a saved meal.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "guidance"))

import fixtures as fx  # noqa: E402  (tests/guidance/fixtures.py)

from app.ai import guard as G  # noqa: E402
from app.ai import schemas  # noqa: E402
from app.ai.schemas import REASON_CODES  # noqa: E402
from app.guidance.budget import day_totals, meal_room  # noqa: E402
from app.guidance.state import Prefs  # noqa: E402
from test_ai_guard import LABEL, idea, judge, no_status_provider, setup  # noqa: E402,F401  (the autouse fixture is re-exported)

LIKES_RICE = Prefs(food_pref={1: "like"})


def candidate(bridge, food_id):
    return next(f for f in bridge["foods"] if f["food_id"] == food_id)


def test_the_liked_bit_is_the_persons_like_not_whether_the_card_had_room_to_show_it():
    _, plain = setup()
    _, liked = setup(prefs=LIKES_RICE)
    assert candidate(plain, 1)["liked"] is False
    rice = candidate(liked, 1)
    # rice has two kidney reasons, so a card (at most two reasons) has no room for "You said you like this": the bit does not
    # depend on that
    assert rice["liked"] is True and "you_like" not in rice["reasons"] and len(rice["reasons"]) >= 2
    assert [f["food_id"] for f in liked["foods"] if f["liked"]] == [1]  # only the marked food
    assert G.liked_ids(liked) == {1} and G.liked_ids(plain) == set()
    assert all("you_like" not in f["reasons"] for f in liked["foods"])  # the AI layer's own list of reasons never holds it


def test_a_group_like_a_less_often_choice_or_a_neutral_food_is_not_a_liked_food():
    _, bridge = setup(prefs=Prefs(food_pref={1: "less", 7: "neutral"}, like_categories=frozenset({"Vegetables", "Fruits"})))
    assert G.liked_ids(bridge) == set()


def test_you_like_is_in_the_closed_lists_the_schema_and_the_guard_use():
    assert "you_like" in REASON_CODES and "you_like" in G.REASON_TEXT
    ideas = schemas.ideas_schema([1], [])["properties"]["ideas"]["items"]["properties"]["reason_codes"]["items"]["enum"]
    order = schemas.rerank_schema(["f1"])["properties"]["order"]["items"]["properties"]["reason_codes"]["items"]["enum"]
    assert "you_like" in ideas and "you_like" in order
    schemas.Idea.model_validate({"theme": "light", "items": [{"food_id": 1, "quarters": 4}], "reason_codes": ["you_like"]})
    assert G.REASON_TEXT["you_like"] == "uses a food you said you like"
    assert G.sentence(["you_like"], "dinner") == "Uses a food you said you like."


def test_true_reasons_say_you_like_only_for_a_liked_food():
    ctx = fx.context()
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    rice, chicken = ctx.foods[1], ctx.foods[3]
    assert "you_like" not in G.true_reasons([(rice, 1.0)], room, ())
    assert "you_like" not in G.true_reasons([(rice, 1.0)], room, often=[1])  # often is another claim
    assert "you_like" in G.true_reasons([(rice, 1.0)], room, (), liked=[1])
    assert "you_like" in G.true_reasons([(chicken, 1.0), (rice, 1.0)], room, (), liked=[1])  # one liked food in the idea is enough
    assert "you_like" not in G.true_reasons([(chicken, 1.0)], room, (), liked=[1])
    assert "you_eat_often" not in G.true_reasons([(rice, 1.0)], room, (), liked=[1])  # and the other way round


def test_a_you_like_claim_for_a_food_that_is_not_liked_is_removed_and_counted():
    result = judge([idea([(1, 4), (7, 4)], codes=["low_potassium", "you_like"])])
    shown = result["ideas"][0]
    assert shown["reason_codes"] == ["low_potassium"] and result["claims_corrected"] == 1
    assert "like" not in shown["why"]
    only = judge([idea([(1, 4), (7, 4)], codes=["you_like"])])  # every claim false: the true ones replace it, the claim never stays
    assert "you_like" not in only["ideas"][0]["reason_codes"] and only["claims_corrected"] == 1


def test_a_you_like_claim_for_a_liked_candidate_is_kept_and_worded_by_the_server():
    result = judge([idea([(1, 4), (7, 4)], codes=["you_like", "low_potassium"])], prefs=LIKES_RICE)
    shown = result["ideas"][0]
    assert shown["reason_codes"] == ["you_like", "low_potassium"] and result["claims_corrected"] == 0
    assert shown["why"].startswith("Uses a food you said you like; low in potassium (")
    other = judge([idea([(7, 4)], codes=["you_like", "low_potassium"])], prefs=LIKES_RICE)  # the liked food is not in this idea
    assert "you_like" not in other["ideas"][0]["reason_codes"] and other["claims_corrected"] == 1


def test_you_like_is_checked_in_rerank_too():
    ctx, bridge = setup(mode="rerank", prefs=LIKES_RICE)
    refs = {f["food_id"]: f["ref"] for f in bridge["foods"]}
    answer = {"status": "ok", "refusal": "none", "order": [{"ref": refs[1], "reason_codes": ["you_like"]},
                                                           {"ref": refs[7], "reason_codes": ["you_like"]}]}
    result = G.judge_rerank(answer, ctx, "dinner", bridge, **LABEL)
    by_ref = {o["ref"]: o for o in result["order"]}
    assert by_ref[refs[1]]["reason_codes"] == ["you_like"]
    assert "you_like" not in by_ref[refs[7]]["reason_codes"] and result["claims_corrected"] == 1


def test_an_idea_with_a_food_the_person_said_no_to_is_dropped_even_from_a_saved_meal():
    # the saved meal "Usual dinner" holds chicken, rice and green beans: its foods are candidate ids, whatever the person thinks of them
    ideas = [idea([(3, 4), (1, 4), (5, 4)], codes=["adds_protein"]), idea([(3, 4), (1, 4)], codes=["adds_protein"])]
    never = judge(ideas, prefs=Prefs(exclude_food_ids=frozenset({5})))
    assert {"index": 0, "reason": "not_for_me"} in never["dropped"]
    assert all(i["index"] != 0 for i in never["ideas"])
    group = judge(ideas, prefs=Prefs(exclude_categories=frozenset({"Vegetables"})))  # green beans are a vegetable
    assert {"index": 0, "reason": "excluded_category"} in group["dropped"]
    # a "less often" food is not forbidden: the rules rank it lower, they never hide it
    less = judge(ideas, prefs=Prefs(food_pref={5: "less"}))
    assert all(d["reason"] not in G.NOT_FOR_ME_REASONS for d in less["dropped"])
    assert G.person_excluded(fx.context(prefs=Prefs(exclude_food_ids=frozenset({5}))), [3, 1, 5, 999]) == "not_for_me"
    assert G.person_excluded(fx.context(), [3, 1, 5]) is None
