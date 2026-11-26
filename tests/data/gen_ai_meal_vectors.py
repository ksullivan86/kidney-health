#!/usr/bin/env python3
"""Generate tests/data/ai_meal_vectors.json: parity vectors for the browser twins of AI meal ideas and AI recipes on the iPhone app
(app/static/js/engine/aimeal.js; design note 39 §6.6).

    python3 tests/data/gen_ai_meal_vectors.py           # rewrite the file
    python3 tests/data/gen_ai_meal_vectors.py --check   # exit 1 when the committed file is stale

Made by the server's own code: app/guidance/ai_bridge.py (candidates_for_ai, validate_ai_items), app/ai/guard.py (judge_ideas,
fallback), app/ai/recipes.py (recipe_candidates, judge_recipes with steps off), app/ai/prompts.py (next_meal_context,
recipe_context, person_block, condition_text); for AI order, swaps and day plans also candidates_for_ai with modes rerank, swap
and plan, guard.judge_rerank / judge_swap / judge_plan, prompts.swap_extra / plan_extra and the V2 models RerankAnswer, SwapAnswer
and PlanAnswer (``ai_check``: does the answer pass). The inputs are those of tests/data/gen_guidance_vectors.py (its foods and its
context replayer), so ``input`` has the same shape as there. ``call.fn`` names the function; ``output`` is its JSON answer.
tests/js/run_vectors.mjs replays every case on the twin; tests/test_phone_ai_more.py checks the file is current.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "ai_meal_vectors.json"
_spec = importlib.util.spec_from_file_location("gen_guidance_vectors", Path(__file__).resolve().parent / "gen_guidance_vectors.py")
G = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(G)

from pydantic import ValidationError  # noqa: E402

from app.ai import guard, prompts, schemas  # noqa: E402
from app.ai import recipes as AR  # noqa: E402
from app.guidance import ai_bridge  # noqa: E402
from app.guidance.budget import open_slots  # noqa: E402
from app.guidance.recipes import Target, fit_recipe  # noqa: E402

FORMAT = 1
LABEL, MODEL = "OpenAI (your own key)", "gpt-6-luna"
TODAY = date(2026, 10, 5)


def target_of(spec: Mapping[str, Any]) -> Target:
    return Target(spec["target"]["kind"], spec["target"].get("meal"))


def change_block(ctx: Any, bridge: Mapping[str, Any], original: list, makes: float, target: Target) -> dict[str, Any]:
    """prepare_recipes' ``recipe`` block for mode ``change`` (the person's recipe: foods, pot amounts, the app's findings)."""
    before = fit_recipe(ctx, original, makes, target)["before"]
    sendable = [(f, q) for f, q in original if any(int(c["food_id"]) == f.id for c in bridge["foods"])]
    return {"ref": "r1", "makes": makes, "ingredients": [{"id": f.id, "quarters": AR.quarters_of(q)} for f, q in sendable],
            "findings": [{"nutrient": c["nutrient"], "per_serving": c["used"], "room": c["room"], "ok": c["ok"]} for c in before["checks"]]}


def call(inp: Mapping[str, Any], spec: Mapping[str, Any], foods: Mapping[int, Any]) -> Any:
    fn = spec["fn"]
    if fn == "condition_text":
        return prompts.condition_text(spec["person"])
    if fn == "person_block":
        return prompts.person_block(spec["profile"], spec["ai_prefs"], date.fromisoformat(spec["today"]), spec.get("tastes"))
    if fn == "ai_check":  # the V2 answer models (app/ai/schemas.py): does the answer pass?
        try:
            getattr(schemas, spec["model"]).model_validate(spec["answer"])
        except ValidationError:
            return {"ok": False}
        return {"ok": True}
    ctx = G.context_from(inp, foods)
    exclude = frozenset(spec.get("exclude", ()))
    mode = spec.get("ai_mode", "ideas")  # "mode" is the recipes' own (suggest, change)
    if mode != "ideas" or fn in ("ai_judge_rerank", "ai_judge_swap", "ai_judge_plan"):
        return mode_call(ctx, spec, fn, mode)
    if fn == "ai_candidates":
        return ai_bridge.candidates_for_ai(ctx, spec["meal"], "ideas", exclude=exclude)
    if fn == "ai_validate":
        return ai_bridge.validate_ai_items(ctx, spec["meal"], spec["ideas"], spec.get("candidate_ids"))
    if fn == "ai_judge_ideas":
        bridge = ai_bridge.candidates_for_ai(ctx, spec["meal"], "ideas", exclude=exclude)
        return guard.judge_ideas(spec["answer"], ctx, spec["meal"], bridge, provider_label=LABEL, model=MODEL)
    if fn == "ai_next_meal_data":
        bridge = ai_bridge.candidates_for_ai(ctx, spec["meal"], "ideas", exclude=exclude)
        data = prompts.next_meal_context(bridge, ctx, mode="ideas", meal=spec["meal"], meals_left=open_slots(spec["meal"], ctx.day),
                                         person=spec["person"])
        return {"data": data, "fallback": guard.fallback(bridge)}
    target = target_of(spec)
    original = [(ctx.foods[i], q) for i, q in spec.get("recipe", [])]
    if fn == "ai_recipe_candidates":
        return AR.recipe_candidates(ctx, target, [f for f, _ in original], exclude)
    bridge = AR.recipe_candidates(ctx, target, [f for f, _ in original], exclude)
    makes = float(spec["makes"])
    if fn == "ai_recipe_data":
        meal = target.meal if target.kind == "meal" and target.meal else bridge["meal"]
        request: dict[str, Any] = {"mode": spec["mode"], "makes": makes}
        if spec["mode"] == "suggest":
            request["dish"] = spec["dish"]
        block = change_block(ctx, bridge, original, makes, target) if spec["mode"] == "change" else None
        return prompts.recipe_context(bridge, ctx, meal=meal if target.kind == "meal" else "day",
                                      meals_left=list(open_slots(meal, ctx.day)) if target.kind == "meal" else [],
                                      person=spec["person"], request=request, recipe=block)
    if fn == "ai_judge_recipes":
        return AR.judge_recipes(spec["answer"], ctx, target, bridge, mode=spec["mode"], makes=makes, steps=False, original=original,
                                name=spec.get("name"), provider_label=LABEL, model=MODEL)
    raise ValueError(f"unknown fn {fn!r}")


def bridge_for(ctx: Any, spec: Mapping[str, Any], mode: str) -> dict[str, Any]:
    """candidates_for_ai for AI order, swaps and day plans (spec "swap": [food id, servings, purpose])."""
    if mode == "swap":
        food_id, servings, purpose = spec["swap"]
        return ai_bridge.candidates_for_ai(ctx, spec["meal"], "swap", food=ctx.foods[food_id], servings=servings, purpose=purpose)
    return ai_bridge.candidates_for_ai(ctx, spec["meal"], mode)


def mode_call(ctx: Any, spec: Mapping[str, Any], fn: str, mode: str) -> Any:
    """AI order (rerank), AI swaps and AI day plans (phone-ai-more2): candidates, the data block and the judges."""
    mode = {"ai_judge_rerank": "rerank", "ai_judge_swap": "swap", "ai_judge_plan": "plan"}.get(fn, mode)
    try:
        bridge = bridge_for(ctx, spec, mode)
    except ValueError as exc:
        return {"error": str(exc)}
    if fn == "ai_candidates":
        return bridge
    if fn == "ai_next_meal_data":
        extra: dict[str, Any] = {}
        if mode == "swap":
            extra = prompts.swap_extra(bridge, ctx.foods[spec["swap"][0]], float(spec["swap"][1]))
        elif mode == "plan":
            extra = prompts.plan_extra(bridge)
        return {"data": prompts.next_meal_context(bridge, ctx, mode=mode, meal=spec["meal"], meals_left=open_slots(spec["meal"], ctx.day),
                                                  person=spec["person"], extra=extra)}
    if fn == "ai_judge_rerank":
        return guard.judge_rerank(spec["answer"], ctx, spec["meal"], bridge, provider_label=LABEL, model=MODEL)
    if fn == "ai_judge_swap":
        return guard.judge_swap(spec["answer"], ctx, spec["meal"], bridge, provider_label=LABEL, model=MODEL)
    if fn == "ai_judge_plan":
        return guard.judge_plan(spec["answer"], ctx, bridge, provider_label=LABEL, model=MODEL)
    raise ValueError(f"unknown fn {fn!r} for mode {mode!r}")


def picks(key: str, *rows: Any, status: str = "ok", refusal: str = "none") -> dict:
    return {key: list(rows), "status": status, "refusal": refusal}


def ref(r: str, *codes: str) -> dict:
    return {"ref": r, "reason_codes": list(codes or ("low_potassium",))}


def mode_cases(base: Any, real: Any, rid: Any) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    potato, oj, chicken = rid("Potato, baked, with skin"), rid("Orange juice"), rid("Chicken breast, roasted, skinless")
    breakfast_eaten = real(day=[G.entry(1, rid("Egg, scrambled"), "breakfast")])
    swap_potato = {"meal": "dinner", "swap": [potato, 1.0, None]}
    return [
        ("MCAND rerank, dinner, fixture", base(), {"fn": "ai_candidates", "meal": "dinner", "ai_mode": "rerank"}),
        ("MCAND swap a baked potato, fixture", base(), {"fn": "ai_candidates", "meal": "dinner", "ai_mode": "swap", "swap": [2, 1.0, None]}),
        ("MCAND swap a baked potato, real", real(), {"fn": "ai_candidates", "ai_mode": "swap", **swap_potato}),
        ("MCAND swap orange juice for a low: never sent", base(), {"fn": "ai_candidates", "meal": "snack", "ai_mode": "swap", "swap": [11, 1.0, "hypo"]}),
        ("MCAND swap orange juice with a meal", real(), {"fn": "ai_candidates", "meal": "dinner", "ai_mode": "swap", "swap": [oj, 1.0, None]}),
        ("MCAND plan, real", breakfast_eaten, {"fn": "ai_candidates", "meal": "lunch", "ai_mode": "plan"}),
        ("MCAND plan, fixture with a saved meal", base(saved_meals=[{"id": 1, "name": "Usual dinner", "meal_hint": "dinner",
                                                                   "items": [[3, 1.0], [1, 0.625], [5, 1.0]]}]),
         {"fn": "ai_candidates", "meal": "breakfast", "ai_mode": "plan"}),
        ("MDATA rerank", real(), {"fn": "ai_next_meal_data", "meal": "dinner", "ai_mode": "rerank", "person": PERSON}),
        ("MDATA swap", real(), {"fn": "ai_next_meal_data", "ai_mode": "swap", "person": PERSON, **swap_potato}),
        ("MDATA plan", breakfast_eaten, {"fn": "ai_next_meal_data", "meal": "lunch", "ai_mode": "plan", "person": KIDNEY_ONLY}),
        ("MJUDGE rerank: good, made up, twice, too many claims", real(), {"fn": "ai_judge_rerank", "meal": "dinner",
            "answer": picks("order", ref("f3", "adds_protein", "you_like"), ref("zz"), ref("f3"), ref("f1", "low_sodium", "low_potassium", "fits_carb_goal"),
                            *[ref(f"f{i}") for i in range(4, 16)])}),
        ("MJUDGE rerank: none kept", base(), {"fn": "ai_judge_rerank", "meal": "dinner", "answer": picks("order", ref("q9"))}),
        ("MJUDGE rerank: refused", base(), {"fn": "ai_judge_rerank", "meal": "dinner", "answer": picks("order", status="refused", refusal="outside_scope")}),
        ("MJUDGE swap: picks and a made-up ref", real(), {"fn": "ai_judge_swap", "answer": picks("pick", ref("s2", "low_potassium", "you_like"), ref("s9x"),
                                                                                                    ref("s1"), ref("s2"), ref("s3"), ref("s4")), **swap_potato}),
        ("MJUDGE swap: none kept", real(), {"fn": "ai_judge_swap", "answer": picks("pick", ref("f1")), **swap_potato}),
        ("MJUDGE swap: refused", real(), {"fn": "ai_judge_swap", "answer": picks("pick", status="refused", refusal="outside_scope"), **swap_potato}),
        ("MJUDGE plan: picks rebuilt and checked", breakfast_eaten, {"fn": "ai_judge_plan", "meal": "lunch", "answer": picks("picks",
            {"meal": "lunch", "index": 1, "reason_codes": ["adds_protein"]}, {"meal": "dinner", "index": 2, "reason_codes": ["low_sodium"]},
            {"meal": "lunch", "index": 0, "reason_codes": ["low_sodium"]}, {"meal": "breakfast", "index": 0, "reason_codes": ["low_sodium"]},
            {"meal": "dinner", "index": 99, "reason_codes": ["low_sodium"]})}),
        ("MJUDGE plan: none kept", breakfast_eaten, {"fn": "ai_judge_plan", "meal": "lunch", "answer": picks("picks",
            {"meal": "snack", "index": 40, "reason_codes": ["low_sodium"]})}),
        ("MJUDGE plan: refused", base(), {"fn": "ai_judge_plan", "meal": "dinner", "answer": picks("picks", status="refused", refusal="outside_scope")}),
        ("MCHECK rerank ok", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", ref("f1"), ref("f2", "adds_protein", "low_sodium"))}),
        ("MCHECK rerank: a number for a ref", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", {"ref": 1, "reason_codes": ["low_sodium"]})}),
        ("MCHECK rerank: a long ref", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", ref("f123456789"))}),
        ("MCHECK rerank: no reason", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", {"ref": "f1", "reason_codes": []})}),
        ("MCHECK rerank: four reasons", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", ref("f1", "low_sodium", "low_potassium",
                                                                                                                    "adds_protein", "you_like"))}),
        ("MCHECK rerank: an unknown reason", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", ref("f1", "tasty"))}),
        ("MCHECK rerank: an extra key", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", {**ref("f1"), "why": "x"})}),
        ("MCHECK rerank: an extra top key", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": {**picks("order"), "note": "x"}}),
        ("MCHECK rerank: a status not on the list", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", status="maybe")}),
        ("MCHECK rerank: 41 rows", base(), {"fn": "ai_check", "model": "RerankAnswer", "answer": picks("order", *[ref("f1")] * 41)}),
        ("MCHECK swap: 15 rows", base(), {"fn": "ai_check", "model": "SwapAnswer", "answer": picks("pick", *[ref("s1")] * 15)}),
        ("MCHECK swap: 16 rows", base(), {"fn": "ai_check", "model": "SwapAnswer", "answer": picks("pick", *[ref("s1")] * 16)}),
        ("MCHECK swap: the wrong list", base(), {"fn": "ai_check", "model": "SwapAnswer", "answer": picks("order", ref("s1"))}),
        ("MCHECK plan ok", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", {"meal": "lunch", "index": 0, "reason_codes": ["low_sodium"]})}),
        ("MCHECK plan: a text index", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", {"meal": "lunch", "index": "0",
                                                                                                                "reason_codes": ["low_sodium"]})}),
        ("MCHECK plan: a true index", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", {"meal": "lunch", "index": True,
                                                                                                                "reason_codes": ["low_sodium"]})}),
        ("MCHECK plan: index 21", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", {"meal": "lunch", "index": 21,
                                                                                                             "reason_codes": ["low_sodium"]})}),
        ("MCHECK plan: a meal not on the list", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", {"meal": "brunch", "index": 0,
                                                                                                                         "reason_codes": ["low_sodium"]})}),
        ("MCHECK plan: five picks", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", *[{"meal": "lunch", "index": 0,
                                                                                                                "reason_codes": ["low_sodium"]}] * 5)}),
        ("MCHECK plan: refused and empty", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": picks("picks", status="refused", refusal="outside_scope")}),
        ("MCHECK not an object", base(), {"fn": "ai_check", "model": "PlanAnswer", "answer": ["picks"]}),
    ]


def idea(items: list[tuple[int, int]], theme: str = "light", codes: tuple[str, ...] = ("low_potassium",), handbook: tuple = ()) -> dict:
    return {"theme": theme, "items": [{"food_id": f, "quarters": q} for f, q in items], "reason_codes": list(codes), "handbook": list(handbook)}


def ideas(*rows: dict, status: str = "ok", refusal: str = "none") -> dict:
    return {"ideas": list(rows), "status": status, "refusal": refusal}


def recipe(items: list[tuple[int, int]], dish: str = "stew", theme: str = "hearty", codes: tuple[str, ...] = ("adds_protein",),
           steps: tuple[str, ...] = ()) -> dict:
    return {"dish": dish, "theme": theme, "ingredients": [{"food_id": f, "quarters": q} for f, q in items], "steps": list(steps),
            "reason_codes": list(codes)}


PERSON = {"ckd_stage": "4", "dialysis": "none", "diabetes": "type1", "preferences": "no fish", "likes": ["Tofu, firm"], "less_often": None,
          "not_for_me": None, "age_band": None, "sex": None}
KIDNEY_ONLY = {**PERSON, "diabetes": "none", "preferences": None, "likes": None}


def cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    rid = G.rid
    base, real = G.base_input, G.real_input
    tofu, chicken, rice, beans = rid("Tofu, firm"), rid("Chicken breast, roasted, skinless"), rid("Rice, white, long-grain, cooked"), rid("Green beans, boiled")
    liked = real(food_pref=[[tofu, "like"], [rid("Pasta, cooked"), "less"]],
                 history=[G.hist(d, chicken, "dinner") for d in ("2026-10-04", "2026-10-03", "2026-10-02", "2026-10-01")])
    stew = [[rid("Beef, chuck pot roast, braised"), 4], [rid("Potato, baked, with skin"), 4], [rid("Green beans, boiled"), 4],
            [rid("Olive oil"), 1]]
    dinner = {"kind": "meal", "meal": "dinner"}
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("COND stage 4 and type 1", base(), {"fn": "condition_text", "person": PERSON}),
        ("COND kidney only on dialysis", base(), {"fn": "condition_text", "person": {"ckd_stage": "5", "dialysis": "hemodialysis", "diabetes": "none"}}),
        ("COND nothing chosen", base(), {"fn": "condition_text", "person": {}}),
        ("PERSON with consent and tastes", base(), {"fn": "person_block", "profile": {"ckd_stage": "3b", "dialysis": "none", "diabetes": "type2",
            "birth_month": "1971-03", "sex": "female", "name": "Robin"}, "ai_prefs": {"share_age_sex": True, "preferences": "  likes​ soup  "},
            "today": "2026-10-05", "tastes": {"likes": ["Tofu", "Tofu", "Rice"], "less_often": [], "not_for_me": ["Fish"]}}),
        ("PERSON no consent, defaults not chosen", base(), {"fn": "person_block", "profile": {"ckd_stage": "3b", "ckd_stage_chosen": False,
            "diabetes": "type1", "diabetes_chosen": False, "birth_month": "1971-03", "sex": "male"}, "ai_prefs": {}, "today": "2026-10-05"}),
        ("CAND dinner, fixture", base(), {"fn": "ai_candidates", "meal": "dinner"}),
        ("CAND snack, fixture, rice left out", base(), {"fn": "ai_candidates", "meal": "snack", "exclude": [1]}),
        ("CAND lunch, real, likes and habits", liked, {"fn": "ai_candidates", "meal": "lunch"}),
        ("CAND dinner, real, kidney only", real(diabetes="none"), {"fn": "ai_candidates", "meal": "dinner"}),
        ("VAL fits, merges, too many", base(), {"fn": "ai_validate", "meal": "dinner", "ideas": [
            [{"food_id": 1, "quarters": 2}, {"food_id": 5, "quarters": 2}, {"food_id": 1, "quarters": 1}],
            [{"food_id": 999, "quarters": 4}], [{"food_id": 3, "quarters": 40}], [{"food_id": 1, "quarters": 4}]]}),
        ("VAL lowered to fit", real(), {"fn": "ai_validate", "meal": "dinner", "candidate_ids": [chicken, rice, beans, rid("Potato, baked, with skin")],
            "ideas": [[{"food_id": rid("Potato, baked, with skin"), "quarters": 12}, {"food_id": chicken, "quarters": 8}]]}),
        ("JUDGE ideas: good, made up, not for me, extra field", real(exclude_food_ids=[rid("Egg, scrambled")]), {"fn": "ai_judge_ideas", "meal": "dinner",
            "answer": ideas(idea([(chicken, 4), (rice, 4), (beans, 4)], "hearty", ("adds_protein", "you_like", "low_sodium"), ("protein", "nope", "protein")),
                            idea([(424242, 4)]), idea([(rid("Egg, scrambled"), 4)]), {**idea([(rice, 4)]), "title": "Free text"})}),
        ("JUDGE ideas: likes and often", liked, {"fn": "ai_judge_ideas", "meal": "lunch",
            "answer": ideas(idea([(tofu, 4), (rice, 4)], "familiar", ("you_like", "you_eat_often")), idea([(chicken, 4)], "new_idea", ("you_eat_often",)))}),
        ("JUDGE ideas: a portion made smaller", real(), {"fn": "ai_judge_ideas", "meal": "dinner",
            "answer": ideas(idea([(rid("Couscous, cooked"), 12), (tofu, 8), (beans, 8)], "hearty"))}),
        ("JUDGE ideas: too many and malformed", base(), {"fn": "ai_judge_ideas", "meal": "dinner",
            "answer": ideas(idea([(1, 2)]), "x", {"theme": "light", "items": [{"food_id": True, "quarters": 2}], "reason_codes": [], "handbook": []},
                            idea([(1, 2), (5, 2)]), idea([(1, 2)]))}),
        ("JUDGE ideas: refused", base(), {"fn": "ai_judge_ideas", "meal": "dinner", "answer": ideas(status="refused", refusal="outside_scope")}),
        ("JUDGE ideas: no fit", base(), {"fn": "ai_judge_ideas", "meal": "dinner", "answer": ideas(refusal="no_fit")}),
        ("JUDGE ideas: all dropped", base(), {"fn": "ai_judge_ideas", "meal": "dinner", "answer": ideas(idea([(77777, 2)]))}),
        ("DATA next meal, fixture", base(saved_meals=[{"id": 1, "name": "Usual\u0007 dinner <b>", "meal_hint": "dinner", "items": [[3, 1.0], [1, 0.625], [5, 1.0]]}],
                                           repeat_ok_food_ids=[1], repeat_ok_meal_ids=[1]),
         {"fn": "ai_next_meal_data", "meal": "dinner", "person": PERSON}),
        ("DATA next meal, real, kidney only", liked, {"fn": "ai_next_meal_data", "meal": "lunch", "person": KIDNEY_ONLY}),
        ("RCAND dinner, real", real(), {"fn": "ai_recipe_candidates", "target": dinner}),
        ("RCAND the day, real, some left out", real(exclude_food_ids=[tofu]), {"fn": "ai_recipe_candidates", "target": {"kind": "day"}, "exclude": [chicken, rid("Olive oil")]}),
        ("RCAND fixture with a recipe to rework", base(), {"fn": "ai_recipe_candidates", "target": dinner, "recipe": [[9, 1.0], [1, 1.0]]}),
        ("RDATA suggest a stew", real(), {"fn": "ai_recipe_data", "target": dinner, "mode": "suggest", "dish": "stew", "makes": 4, "person": PERSON}),
        ("RDATA rework, the day", real(), {"fn": "ai_recipe_data", "target": {"kind": "day"}, "mode": "change", "makes": 4, "person": KIDNEY_ONLY,
                                           "recipe": stew}),
        ("RJUDGE a stew, steps dropped", real(), {"fn": "ai_judge_recipes", "target": dinner, "mode": "suggest", "makes": 4,
            "answer": {"recipes": [recipe([(f, q) for f, q in stew], steps=("Brown the beef.",)),
                                   recipe([(chicken, 4)]), recipe([(424242, 4), (rice, 4)]), recipe([(rice, 4), (beans, 4)])],
                       "status": "ok", "refusal": "none"}}),
        ("RJUDGE too big a share", real(), {"fn": "ai_judge_recipes", "target": dinner, "mode": "suggest", "makes": 1,
            "answer": {"recipes": [recipe([(rid("Potato, baked, with skin"), 16), (chicken, 4)], dish="bake")], "status": "ok", "refusal": "none"}}),
        ("RJUDGE rework", real(), {"fn": "ai_judge_recipes", "target": {"kind": "day"}, "mode": "change", "makes": 4, "recipe": stew,
            "name": "Grandma's beef stew with a very long name that goes on and on and on and on",
            "answer": {"recipes": [recipe([(rid("Beef, chuck pot roast, braised"), 3), (rid("Green beans, boiled"), 6), (rid("Rice, white, long-grain, cooked"), 4)])],
                       "status": "ok", "refusal": "none"}}),
        ("RJUDGE refused and no fit", base(), {"fn": "ai_judge_recipes", "target": dinner, "mode": "suggest", "makes": 2,
            "answer": {"recipes": [], "status": "refused", "refusal": "outside_scope"}}),
        ("RJUDGE nothing fits", base(), {"fn": "ai_judge_recipes", "target": dinner, "mode": "suggest", "makes": 2,
            "answer": {"recipes": [], "status": "ok", "refusal": "no_fit"}}),
        ("RJUDGE extra field and malformed", base(), {"fn": "ai_judge_recipes", "target": dinner, "mode": "suggest", "makes": 2,
            "answer": {"recipes": [{**recipe([(1, 2), (5, 2)]), "title": "x"}, {**recipe([(1, 2)]), "ingredients": [{"food_id": 1}]}],
                       "status": "ok", "refusal": "none"}}),
    ]
    out += mode_cases(base, real, rid)
    return out


def build() -> dict[str, Any]:
    foods = G.food_map(G.FOODS)
    return {"format": FORMAT, "about": "Generated by tests/data/gen_ai_meal_vectors.py from app/ai and app/guidance; see its docstring.",
            "label": LABEL, "model": MODEL, "foods": G.FOODS,
            "cases": [{"id": cid, "input": inp, "call": spec, "output": call(inp, spec, foods)} for cid, inp, spec in cases()]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = G.dumps(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if json.loads(current or "null") != json.loads(text):
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_ai_meal_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(json.loads(text)['cases'])} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
