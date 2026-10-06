"""Note 06 §6.7 properties over seeded random days on the real food list: every returned food and plan
item passes ``check_meal()`` against the room used; nothing forbidden is ever suggested; a suggested
food never tips the day into "over"; output is identical across runs and ``PYTHONHASHSEED`` values.
(The renal-level and beam-versus-exhaustive properties live in test_vectors.py and test_planner.py, the
wording lint in test_messages.py.)"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import fixtures as fx
import pytest
from app.guidance import fits, planner, swaps
from app.guidance.budget import meal_room
from app.guidance.score import check_meal
from app.nutrients import NUTRIENT_KEYS, daily_status, suggest_targets

ROOT = Path(__file__).resolve().parents[2]
DAY_KEYS = ("potassium_mg", "sodium_mg", "fluid_ml")
PROFILES = [("3a", "none"), ("3b", "none"), ("4", "none"), ("5", "none"), ("5", "hemodialysis"), ("5", "peritoneal")]


@pytest.fixture(scope="module")
def foods():
    return fx.real_foods()


def random_days(foods, n: int = 24):
    eligible = [f for f in foods.values() if not (f.avoid or f.hypo or f.supplies)]
    hypo = [f for f in foods.values() if f.hypo]
    for seed in range(n):
        rnd = random.Random(1000 + seed)
        stage, dialysis = PROFILES[seed % len(PROFILES)]
        targets = suggest_targets(rnd.choice([55, 70, 90]), stage, dialysis)["targets"]
        day = []
        for meal in ("breakfast", "lunch")[: rnd.randint(0, 2)]:
            for f in rnd.sample(eligible, rnd.randint(1, 4)):
                day.append(fx.entry(f, meal, rnd.choice([0.5, 1.0, 1.5, 2.0]), status=rnd.choice(["eaten", "planned"])))
        if rnd.random() < 0.3:
            day.append(fx.entry(rnd.choice(hypo), "snack", 1.0, purpose="hypo"))
        ctx = fx.context(food_map=foods, targets=targets, dialysis=dialysis, dialysis_days=(0, 2, 4) if dialysis == "hemodialysis" else (),
                         day=tuple(day), history=(), saved=())
        yield seed, ctx, rnd.choice(["lunch", "dinner", "snack"])


def projected(ctx, extra=()):
    totals = {k: 0.0 for k in NUTRIENT_KEYS}
    for e in ctx.day:
        for k in NUTRIENT_KEYS:
            totals[k] += e.nutrients.get(k) or 0.0
    for f, q in extra:
        for k in NUTRIENT_KEYS:
            totals[k] += (f.nutrients.get(k) or 0.0) * q
    return totals


def test_what_fits_foods_pass_the_meal_check_never_forbidden_never_tip_the_day(foods):
    checked = 0
    for seed, ctx, meal in random_days(foods):
        room = meal_room(ctx, meal)
        result = fits.what_fits(ctx, meal, limit=20)
        before = daily_status(projected(ctx), ctx.profile.targets, ctx.profile.warn_fraction)
        for item in result["foods"]:
            f, q = foods[item["food_id"]], item["servings"]
            assert not (f.avoid or f.ingredient or f.hypo or f.supplies), (seed, f.name)
            assert check_meal([(f, q)], room, "built").ok, (seed, meal, f.name, q, check_meal([(f, q)], room).reason)
            after = daily_status(projected(ctx, [(f, q)]), ctx.profile.targets, ctx.profile.warn_fraction)
            for k in DAY_KEYS:
                if k in after and before.get(k, {}).get("level") != "over":
                    assert after[k]["level"] != "over", (seed, meal, f.name, q, k)
            checked += 1
        for m in result["saved_meals"]:
            assert m["source"] in ("saved", "usual")
    assert checked > 100


def test_plan_items_pass_the_meal_check_of_their_slot(foods):
    for seed, ctx, _ in random_days(foods, 12):
        result = planner.plan_day(ctx)
        for m in result["meals"]:
            if m["status"] == "no_fit":
                assert m["items"] == []
                continue
            items = [(foods[i["food_id"]], i["servings"]) for i in m["items"]]
            for f, _q in items:
                assert not (f.avoid or f.supplies), (seed, f.name)
                if m["source"] == "built":
                    assert not (f.hypo or f.ingredient), (seed, f.name)
            kind = m["source"] if m["source"] in ("saved", "usual", "starter") else "built"
            room = m["room"]
            for key in ("potassium_mg", "phosphorus_mg", "sodium_mg", "fluid_ml"):
                if room[key] is not None:
                    total = sum((f.nutrients.get(key) or 0.0) * q for f, q in items)
                    assert total <= room[key]["room"] + {"potassium_mg": 50, "phosphorus_mg": 30, "sodium_mg": 50,
                                                         "fluid_ml": 30}[key] + 0.5, (seed, m["meal"], key)
            if room["carbs_g"] is not None:
                carbs = sum((f.carbs or 0.0) * q for f, q in items)
                assert carbs - room["carbs_g"]["gap"] <= room["carbs_g"]["tolerance"] + 0.05, (seed, m["meal"], kind)


def test_swaps_never_offer_forbidden_foods_and_lower_every_trigger(foods):
    """Swaps keep the original's carbohydrate (or protein) on purpose, so the meal check applies to their
    minerals: a swap marked ``fits_meal`` fits the meal's room."""
    some = [f for f in foods.values() if not f.hypo][::11]
    for seed, ctx, meal in random_days(foods, 6):
        for f in some:
            r = swaps.find_swaps(ctx, meal, f, 1.0)
            keys = [t["nutrient"] for t in r["triggers"] if t["nutrient"] in DAY_KEYS + ("phosphorus_mg",)]
            for s in r["swaps"]:
                cand = foods[s["food_id"]]
                assert not (cand.avoid or cand.ingredient or cand.supplies), (seed, f.name, cand.name)
                assert not cand.hypo or f.beverage  # low treatments only as swaps for drinks (TV-S5)
                for k in keys:
                    assert s["nutrients"][k] <= 0.75 * (f.nutrients[k] or 0.0) + 1, (f.name, cand.name, k)
                if s["fits_meal"]:  # the minerals fit the room; carbs match the original by design (F4)
                    room = meal_room(ctx, meal)
                    for key, item in room.nutrients.items():
                        amount = (cand.nutrients.get(key) or 0.0) * s["servings"]
                        assert amount <= item.room + {"potassium_mg": 50, "phosphorus_mg": 30, "sodium_mg": 50,
                                                      "fluid_ml": 30}[key] + 1e-6, (f.name, cand.name, key)


_DETERMINISM = r"""
import json, sys
sys.path.insert(0, {root!r}); sys.path.insert(0, {tests!r})
import fixtures as fx
from app.guidance import fits, insights, planner, swaps
foods = fx.real_foods()
ctx = fx.context(food_map=foods, targets=fx.STAGE4_TARGETS, day=(), history=(), saved=())
out = {{"fits": fits.what_fits(ctx, "lunch", explain=True), "plan": planner.plan_day(ctx),
       "swaps": swaps.find_swaps(ctx, "dinner", fx.by_name(foods, "Potato, baked, with skin"), 1.0),
       "insights": insights.day_insights(fx.context())}}
print(json.dumps(out, sort_keys=True))
"""


def test_output_is_identical_across_runs_and_hash_seeds():
    code = _DETERMINISM.format(root=str(ROOT), tests=str(ROOT / "tests" / "guidance"))
    outputs = []
    for seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120, check=True)
        outputs.append(run.stdout)
    assert outputs[0] == outputs[1] == outputs[2]
    assert json.loads(outputs[0])["plan"]["status"] == "ok"
