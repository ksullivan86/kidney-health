"""The validator pipeline V3–V9 and the text policy (note 04 R7, §9 A2), with a test per blocklist term.
Pure: the guidance engine's note 06 §6.1 fixture context, no database, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "guidance"))

import fixtures as fx  # noqa: E402  (tests/guidance/fixtures.py)

from app.ai import guard as G  # noqa: E402
from app.ai.schemas import REASON_CODES, THEMES  # noqa: E402
from app.guidance import ai_bridge  # noqa: E402
from app.guidance import messages as M  # noqa: E402
from app.guidance.budget import day_totals, meal_room  # noqa: E402
from app.guidance.vectors import make_food  # noqa: E402

LABEL = {"provider_label": "OpenAI", "model": "gpt-6-luna"}


@pytest.fixture(autouse=True)
def no_status_provider():
    ai_bridge.register_ai_status(None)
    yield
    ai_bridge.register_ai_status(None)


def setup(meal: str = "dinner", mode: str = "ideas", **kwargs):
    ctx = fx.context(**kwargs)
    return ctx, ai_bridge.candidates_for_ai(ctx, meal, mode)


def idea(items, theme="light", codes=("low_potassium",), handbook=("potassium",)):
    return {"theme": theme, "items": [{"food_id": f, "quarters": q} for f, q in items], "reason_codes": list(codes),
            "handbook": list(handbook)}


def judge(ideas, **kwargs):
    ctx, bridge = setup(**kwargs)
    return G.judge_ideas({"status": "ok", "refusal": "none", "ideas": ideas}, ctx, "dinner", bridge, **LABEL)


# --------------------------------------------------------------------------- #
# V6 text policy: one test per blocklist term, obfuscations, and words that must pass
# --------------------------------------------------------------------------- #

BLOCKED_TERMS = [
    "insulin", "insulins", "bolus", "basal", "unit", "units", "ratio", "ratios", "correction", "corrections", "dose", "doses",
    "dosed", "dosing", "dosage", "pump", "pumps", "binder", "binders", "sevelamer", "lanthanum", "calcium acetate", "patiromer",
    "zirconium", "supplement", "supplements", "diagnose", "diagnosis", "lab result", "lab results", "safe to eat", "unlimited",
    "as much as", "don't worry", "dont worry", "no need to", "inject", "injection",
]


@pytest.mark.parametrize("term", BLOCKED_TERMS)
def test_every_blocklist_term_is_caught(term):
    assert G.blocked(f"Rice with {term} please") is not None
    assert G.name_policy(f"Rice {term}")[0] is None


@pytest.mark.parametrize("text", [
    "ins​ulin",          # zero-width space
    "ins­ulin",          # soft hyphen
    "іnsulin",                # Cyrillic і
    "INSULIN",
    "Ｉｎｓｕｌｉｎ",              # full-width (NFKC)
    "s‮afe to eat",      # bidi override
    "bοlus",                  # Greek ο
])
def test_obfuscated_terms_are_caught(text):
    assert G.blocked(text) is not None


@pytest.mark.parametrize("text", ["Pumpkin soup", "Masala dosa", "Basil chicken", "Unity loaf", "Rationed rice", "Pasta with lentils",
                                  "7-grain bread", "Supper salad"])
def test_ordinary_food_names_pass(text):
    assert G.blocked(text) is None
    assert G.name_policy(text)[0] == text


@pytest.mark.parametrize("text, reason", [
    ("", "empty"), ("   ", "empty"), (None, "empty"),
    ("see https://evil.example/x", "url"), ("www.evil.example", "url"), ("go to evil.com now", "url"), ("me@example.org", "url"),
    ("<script>", "markup"), ("rice {x}", "markup"), ("`rm -rf`", "markup"), ("a | b", "markup"), ("[link]", "markup"),
    ("rice and insulin", "blocklist:insulin"),
])
def test_name_policy_refusals(text, reason):
    assert G.name_policy(text) == (None, reason)


def test_name_policy_cleans_and_caps():
    assert G.name_policy("  white​   rice‮ ") == ("white rice", None)
    assert len(G.name_policy("r" * 200)[0]) == 80


def test_server_templates_never_use_banned_words():
    texts = [G.REFUSED_TEXT, G.FALLBACK_TEXT, G.NO_FIT_TEXT, *G.REASON_TEXT.values(), *G.THEME_TITLE.values()]
    for text in texts:
        assert not M.BANNED_PATTERN.search(text.format(meal="dinner")), text
        assert G.blocked(text.format(meal="dinner")) is None, text
    assert set(G.REASON_TEXT) == set(REASON_CODES) and set(G.THEME_TITLE) == set(THEMES)


# --------------------------------------------------------------------------- #
# Claims: reason codes and themes are checked against the numbers
# --------------------------------------------------------------------------- #


def test_true_reasons_and_claim_correction():
    ctx = fx.context()
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    rice, chicken = ctx.foods[1], ctx.foods[3]
    truth = G.true_reasons([(rice, 1.0)], room, often=())
    assert {"low_potassium", "low_phosphorus", "adds_missing_group"} <= truth
    assert "adds_protein" not in truth and "you_eat_often" not in truth
    assert "adds_protein" in G.true_reasons([(chicken, 1.0)], room, often=())
    assert "you_eat_often" in G.true_reasons([(rice, 1.0)], room, often=[1])
    codes, corrected = G.check_claims(["adds_protein", "low_potassium", "nonsense", "low_potassium"], [(rice, 1.0)], room, ())
    assert codes == ["low_potassium"] and corrected == 2
    codes, corrected = G.check_claims(["adds_protein"], [(rice, 1.0)], room, ())
    assert codes and "adds_protein" not in codes and corrected == 1  # none true → the true ones


def test_true_reasons_without_targets_use_per_item_limits():
    ctx = fx.context(targets={"carbs_per_meal_g": 60})
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    assert "low_sodium" in G.true_reasons([(ctx.foods[7], 1.0)], room, ())
    assert "low_sodium" not in G.true_reasons([(ctx.foods[8], 1.0)], room, ())  # 470 mg processed cheese
    unknown = make_food(id=50, name="Mystery", category="Vegetables", serving_desc="1 cup", serving_g=50,
                        nutrients=fx.nutrients(5, 1, None, None, None, 0))
    assert not {"low_potassium", "low_phosphorus", "low_sodium"} & G.true_reasons([(unknown, 1.0)], room, ())


def test_fits_carb_goal_claim():
    ctx = fx.context()
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    assert "fits_carb_goal" in G.true_reasons([(ctx.foods[1], 1.0), (ctx.foods[7], 1.0)], room, ())  # 56 g of 60
    assert "fits_carb_goal" not in G.true_reasons([(ctx.foods[7], 1.0)], room, ())


def test_true_theme():
    ctx = fx.context()
    light = [(ctx.foods[7], 1.0)]
    hearty = [(make_food(id=60, name="Stew", category="Prepared & Fast Food", serving_desc="1 bowl", serving_g=400,
                         nutrients={**fx.nutrients(40, 30, 300, 200, 300, 0, 600)}), 1.0)]
    assert G.true_theme(light, "light", ()) == "light"
    assert G.true_theme(light, "hearty", ()) == "light"
    assert G.true_theme(hearty, "light", ()) == "hearty"
    assert G.true_theme(hearty, "hearty", ()) == "hearty"
    assert G.true_theme(light, "familiar", ()) == "new_idea"
    assert G.true_theme(light, "familiar", [7]) == "familiar"
    assert G.true_theme(light, "new_idea", [7]) == "familiar"
    assert G.true_theme(light, "new_idea", ()) == "new_idea"


def test_sentence():
    assert G.sentence(["low_potassium", "fits_carb_goal"], "dinner") == \
        "Low in potassium for what is left today; brings dinner close to your carbohydrate goal."
    assert G.sentence([], "lunch") == "Fits your targets for lunch."


def test_handbook_refs_keep_allowed_slugs_only():
    pages, dropped = G.handbook_refs(["potassium", "treating-a-low", "nope", 5, "potassium", "sodium", "fluid"])
    assert [p["slug"] for p in pages] == ["potassium", "sodium"] and dropped == 5
    assert pages[0]["url"] == "/learn/eat/potassium/"


# --------------------------------------------------------------------------- #
# V3–V5 via the guidance engine, V8 and V9
# --------------------------------------------------------------------------- #


def test_a_good_idea_is_labelled_and_numbered_by_the_server():
    result = judge([idea([(1, 4), (7, 4)], codes=["low_potassium", "adds_protein"])])
    assert result["status"] == "ok" and len(result["ideas"]) == 1
    shown = result["ideas"][0]
    assert shown["source"] == "ai" and shown["checked"] is True and shown["provider_label"] == "OpenAI"
    assert shown["notice"] == "AI idea · OpenAI · gpt-6-luna · checked against your targets · not medical advice"
    assert shown["reason_codes"] == ["low_potassium"] and result["claims_corrected"] == 1  # rice + berries add no protein
    assert shown["title"] == "A light dinner" and shown["why"].startswith("Low in potassium")
    assert [i["food_id"] for i in shown["items"]] == [1, 7] and shown["items"][0]["nutrients"]["potassium_mg"] == 55
    assert shown["after"]["potassium_mg"]["used"] == 110 and shown["handbook"][0]["slug"] == "potassium"


@pytest.mark.parametrize("ideas, reason", [
    ([idea([(999, 4)])], "not_a_candidate"),
    ([idea([(6, 4)])], "not_a_candidate"),  # banana: not offered for this dinner
    ([idea([(1, 0)])], "quarters_out_of_range"),
    ([idea([(1, 13)])], "quarters_out_of_range"),
    ([idea([(1, 1), (3, 1), (4, 1), (5, 1), (7, 1), (11, 1)])], "too_many_items"),
    ([{"theme": "light", "items": []}], "empty"),
    ([{"theme": "light", "items": [{"food_id": "1", "quarters": 4}]}], "malformed_item"),
    ([{"theme": "light", "items": [{"food_id": True, "quarters": 4}]}], "malformed_item"),
    ([{"theme": "light", "items": [{"food_id": 1, "quarters": 4, "x": 1}]}], "malformed_item"),
    ([{"theme": "light"}], "malformed_idea"),
    (["rice"], "malformed_idea"),
])
def test_grounding_drops(ideas, reason):
    result = judge(ideas)
    assert result["status"] == "dropped_all" and result["dropped"][0]["reason"] == reason
    assert result["message"] == G.FALLBACK_TEXT


def test_avoid_ckd_and_low_treatments_are_dropped_even_if_named():
    ctx, bridge = setup()
    answer = {"status": "ok", "refusal": "none", "ideas": [idea([(9, 4)]), idea([(10, 4)])]}
    result = G.judge_ideas(answer, ctx, "dinner", bridge, **LABEL)
    assert [d["reason"] for d in result["dropped"]] == ["not_a_candidate", "not_a_candidate"]
    # even when the candidate list is forced to include them, the rules gate refuses them
    ctx2 = fx.context()
    checked = ai_bridge.validate_ai_items(ctx2, "dinner", [[{"food_id": 9, "quarters": 4}], [{"food_id": 10, "quarters": 4}]],
                                         candidate_ids=[9, 10])
    assert [d["reason"] for d in checked["dropped"]] == ["avoid_ckd", "hypo_treatment"]


def test_ideas_that_exceed_the_room_are_dropped():
    result = judge([idea([(1, 12), (3, 12)])])
    assert result["status"] == "dropped_all"
    assert result["dropped"][0]["reason"].startswith(("would_exceed:", "too_many_carbs", "portion_out_of_range"))


def test_more_than_three_ideas_and_duplicates_merge():
    good = idea([(1, 2), (1, 2), (7, 4)])
    result = judge([good, good, good, good])
    assert len(result["ideas"]) == 3 and result["dropped"] == [{"index": 3, "reason": "too_many_ideas"}]
    assert [i["servings"] for i in result["ideas"][0]["items"]] == [1.0, 1.0]  # 2 + 2 quarters of rice merged


def test_one_bad_idea_does_not_drop_the_others():
    result = judge([idea([(999, 4)]), idea([(7, 4)])])
    assert result["status"] == "ok" and [i["index"] for i in result["ideas"]] == [1]
    assert result["dropped"] == [{"index": 0, "reason": "not_a_candidate"}]


def test_refusal_and_no_fit():
    ctx, bridge = setup()
    refused = G.judge_ideas({"status": "refused", "refusal": "outside_scope", "ideas": []}, ctx, "dinner", bridge, **LABEL)
    assert refused["status"] == "refused" and refused["message"] == G.REFUSED_TEXT
    nofit = G.judge_ideas({"status": "ok", "refusal": "no_fit", "ideas": []}, ctx, "dinner", bridge, **LABEL)
    assert nofit["status"] == "no_fit" and nofit["message"] == G.NO_FIT_TEXT


def test_saved_meal_foods_may_be_used():
    result = judge([idea([(3, 4), (1, 4), (5, 4)], theme="hearty", codes=["adds_protein"])])
    assert result["status"] in ("ok", "dropped_all")
    if result["status"] == "dropped_all":
        assert not result["dropped"][0]["reason"] == "not_a_candidate"


def test_rerank():
    ctx, bridge = setup(mode="rerank")
    refs = [f["ref"] for f in bridge["foods"]]
    answer = {"status": "ok", "refusal": "none", "order": [{"ref": refs[2], "reason_codes": ["adds_protein"]},
                                                           {"ref": "f999", "reason_codes": ["low_sodium"]},
                                                           {"ref": refs[2], "reason_codes": ["low_sodium"]},
                                                           {"ref": refs[0], "reason_codes": ["low_potassium"]}]}
    result = G.judge_rerank(answer, ctx, "dinner", bridge, **LABEL)
    assert [o["ref"] for o in result["order"]] == [refs[2], refs[0]] and result["order"][0]["ai_rank"] == 1
    assert [d["reason"] for d in result["dropped"]] == ["not_a_candidate", "duplicate"]
    assert {r["ref"] for r in result["rest"]} == set(refs) - {refs[0], refs[2]}
    empty = G.judge_rerank({"status": "ok", "refusal": "none", "order": [{"ref": "zz", "reason_codes": ["low_sodium"]}]},
                           ctx, "dinner", bridge, **LABEL)
    assert empty["status"] == "dropped_all"
    assert G.judge_rerank({"status": "refused", "refusal": "outside_scope", "order": []}, ctx, "dinner", bridge, **LABEL)["status"] == "refused"


def test_swap_picks_come_from_the_rule_swaps():
    ctx = fx.context()
    bridge = ai_bridge.candidates_for_ai(ctx, "dinner", "swap", food=ctx.foods[2], servings=1.0)
    refs = [s["ref"] for s in bridge["swaps"]]
    answer = {"status": "ok", "refusal": "none", "pick": [{"ref": refs[0], "reason_codes": ["low_potassium"]},
                                                          {"ref": "f1", "reason_codes": ["low_potassium"]}]}
    result = G.judge_swap(answer, ctx, "dinner", bridge, **LABEL)
    assert [p["ref"] for p in result["pick"]] == [refs[0]] and result["dropped"] == [{"index": 1, "reason": "not_a_candidate"}]
    assert result["pick"][0]["food_id"] == bridge["swaps"][0]["food_id"] and result["pick"][0]["checked"] is True
    many = {"status": "ok", "refusal": "none", "pick": [{"ref": r, "reason_codes": ["low_potassium"]} for r in refs[:5]]}
    assert len(G.judge_swap(many, ctx, "dinner", bridge, **LABEL)["pick"]) == min(3, len(refs))
    assert G.judge_swap({"status": "ok", "refusal": "none", "pick": []}, ctx, "dinner", bridge, **LABEL)["status"] == "dropped_all"
    assert G.judge_swap({"status": "refused", "refusal": "outside_scope", "pick": []}, ctx, "dinner", bridge, **LABEL)["status"] == "refused"


def test_plan_picks_are_rechecked_by_the_planner():
    ctx = fx.context()
    bridge = ai_bridge.candidates_for_ai(ctx, "dinner", "plan")
    slots = list(bridge["plan"])
    assert slots
    answer = {"status": "ok", "refusal": "none", "picks": [{"meal": slots[0], "index": 0, "reason_codes": ["low_potassium"]},
                                                           {"meal": slots[0], "index": 0, "reason_codes": ["low_potassium"]},
                                                           {"meal": "brunch", "index": 0, "reason_codes": ["low_potassium"]},
                                                           {"meal": slots[0], "index": 99, "reason_codes": ["low_potassium"]}]}
    result = G.judge_plan(answer, ctx, bridge, **LABEL)
    assert result["status"] == "ok" and result["ai_picks"] == {slots[0]: 0}
    assert [d["reason"] for d in result["dropped"]] == ["duplicate", "not_a_candidate", "not_a_candidate"]
    assert result["plan"]["status"] == "ok"
    assert G.judge_plan({"status": "ok", "refusal": "none", "picks": []}, ctx, bridge, **LABEL)["status"] == "dropped_all"
    assert G.judge_plan({"status": "refused", "refusal": "outside_scope", "picks": []}, ctx, bridge, **LABEL)["status"] == "refused"


def test_fallback_is_the_rule_result():
    _, bridge = setup()
    fb = G.fallback(bridge)
    assert fb["note"] == M.AI_FALLBACK and fb["foods"][0]["food_id"] == bridge["foods"][0]["food_id"] and len(fb["foods"]) <= 8
    assert fb["meals"] == bridge["meals"]


def test_without_a_meal_carb_goal_there_is_no_carb_claim_and_no_carb_delta():
    ctx = fx.context(targets={"potassium_mg": 2500, "sodium_mg": 2000})
    room = meal_room(ctx, "dinner", totals=day_totals(ctx.day))
    assert room.carbs is None
    assert "fits_carb_goal" not in G.true_reasons([(ctx.foods[1], 1.0)], room, ())
    after = G.after_room(room, [(ctx.foods[1], 1.0)])
    assert "carbs_g" not in after and after["potassium_mg"]["used"] == 55


def test_rerank_keeps_at_most_twelve():
    ctx, bridge = setup(mode="rerank", food_map=fx.real_foods(), targets=fx.TARGETS, day=(), history=(), saved=())
    refs = [f["ref"] for f in bridge["foods"]]
    assert len(refs) > 12
    answer = {"status": "ok", "refusal": "none", "order": [{"ref": r, "reason_codes": ["low_sodium"]} for r in refs[:14]]}
    result = G.judge_rerank(answer, ctx, "dinner", bridge, **LABEL)
    assert len(result["order"]) == 12 and [d["reason"] for d in result["dropped"]] == ["too_many", "too_many"]
