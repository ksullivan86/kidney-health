#!/usr/bin/env python3
"""Generate tests/data/guidance_vectors.json: parity vectors for the demo-mode twin of meal guidance.

    python3 tests/data/gen_guidance_vectors.py           # rewrite the file
    python3 tests/data/gen_guidance_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own pure engine (``app/guidance/``) and meant to be replayed by the
browser twin (``app/static/js/engine/guidance.js``, ARCHITECTURE.md "Frontend modules"; written by the
frontend builder) and by ``tests/guidance/test_parity_vectors.py``, which also checks the file is
current. Plain JSON in, plain JSON out, no clock, no randomness:

* ``foods``: a fixed subset — the note 06 §6.1 fixture foods (ids 1–14) and 33 real foods of
  ``data/foods.json`` (ids 101…) — as stored rows: per-serving ``nutrients`` (12 keys, ``null`` =
  unknown), ``flags``, ``category``, ``serving_desc``/``serving_g``, ``source``, ``fdc_id``,
  ``hidden`` and the curated ``role`` override (or ``null``);
* ``cases``: ``{id, input, call, output}``. ``input`` is everything a request loads for one person:
  ``date``, ``food_set`` (``fixture``: ids below 101, ``real``: 101 and up, ``all``), ``profile`` (``targets``, ``warn_fraction``, ``dialysis``, ``dialysis_days``,
  ``diabetes``), ``prefs`` (``carb_tolerance_g``, ``hypo_dose_g``, ``exclude_food_ids``,
  ``exclude_categories``, and the food preferences of note 09: ``food_pref`` as ``[food_id, "like" | "less" |
  "neutral"]`` pairs, ``like_categories``, ``less_categories``, ``learn_from_log``, ``hidden_usual_meals``),
  ``tunables``, ``day`` (entries with their nutrient snapshot already multiplied by ``servings``), ``history``
  (eaten entries of the previous 14 days), ``history60``, ``planned30`` (``[food_id, date, meal]`` of the entries
  still planned on the last 30 days), ``saved_meals`` and ``combos`` (items as ``[food_id, servings]``).
  ``call.fn`` names the engine function: ``meal_room``, ``what_fits``, ``find_swaps``, ``hypo_options``,
  ``plan_day``, ``plan_days``, ``day_insights``, ``period_insights``, ``learned``, ``fit_recipe`` or ``prefilter``; ``output`` is
  its JSON answer exactly as the API body (before the API adds ``ai`` and ``targets``). ``plan_days`` (design note 23) plans
  ``input.day`` and then one day for each list of entries in ``call.later_days`` (the same shape as ``day``).

Numbers: every output number is already rounded by the engine (scores with JavaScript ``Math.round``
semantics to 2 decimals, milligrams to integers and grams to 1 decimal with the app's half-up display
rounding); JSON floats are written in their shortest round-trip form, which ``JSON.stringify`` also uses.
Changing ``app/guidance/rules.py`` (and so ``RULES_VERSION``) means regenerating this file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "guidance_vectors.json"
for extra in (ROOT, ROOT / "tests" / "guidance"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import fixtures as fx  # noqa: E402  (the note 06 §6.1 fixture, tests/guidance/fixtures.py)

from app.guidance import recipes, fits, hypo, insights, planner, swaps  # noqa: E402
from app.guidance import rules as R  # noqa: E402
from app.guidance.budget import meal_room  # noqa: E402
from app.guidance.state import (  # noqa: E402
    Combo, DayEntry, GuidanceContext, HistoryEntry, PlannedEntry, Prefs, Profile, SavedMeal, Tunables,
)
from app.guidance.vectors import FoodVec, make_food  # noqa: E402
from app.nutrients import NUTRIENT_KEYS, suggest_targets  # noqa: E402

FORMAT = 1
REAL_NAMES = (
    "Chicken breast, roasted, skinless", "Egg white", "Egg, scrambled", "Tofu, firm", "Cheese, cheddar",
    "Cheese, mozzarella, part skim", "Cheese, American, processed", "Beef, chuck pot roast, braised",
    "Rice, white, long-grain, cooked", "Pasta, cooked", "Couscous, cooked", "Grits, cooked", "Cream of wheat, cooked",
    "Bread, white", "Potato, baked, with skin", "Corn flakes cereal", "Green beans, boiled", "Blueberries, raw",
    "Raspberries, raw", "Banana, raw", "Apple, raw, with skin", "Coleslaw, fast food", "Cauliflower, boiled",
    "Orange juice", "Apple juice", "Milk, 2% reduced fat", "Cola, regular", "Glucose tablet (4 g carb)",
    "Glucose gel (15 g carb tube)", "Olive oil", "Butter, unsalted", "Flour, all-purpose", "Star fruit (carambola)",
    "Root beer", "Beer, regular", "Wine, red", "Spirits (gin, rum, vodka, whiskey), 80 proof",
)
REAL_ID0 = 101
DATE = fx.DATE


# --------------------------------------------------------------------------- #
# Foods (plain rows) and the replayer (plain JSON → GuidanceContext → engine)
# --------------------------------------------------------------------------- #


def food_rows() -> list[dict[str, Any]]:
    rows = []
    for fid, name, cat, desc, grams, carbs, protein, k, p, na, fluid, flags in fx.FOOD_ROWS:
        rows.append({"id": fid, "name": name, "category": cat, "serving_desc": desc, "serving_g": grams,
                     "nutrients": fx.nutrients(carbs, protein, k, p, na, fluid), "flags": list(flags), "source": "builtin",
                     "fdc_id": 10000 + fid, "kidney_notes": None, "hidden": False, "role": None})
    real = {item["name"]: item for item in fx.real_food_items()}
    for offset, name in enumerate(REAL_NAMES):
        item = real[name]
        rows.append({"id": REAL_ID0 + offset, "name": item["name"], "category": item["category"],
                     "serving_desc": item["serving_desc"], "serving_g": item["serving_g"],
                     "nutrients": {k: item["nutrients"].get(k) for k in NUTRIENT_KEYS}, "flags": list(item.get("flags") or []),
                     "source": "builtin", "fdc_id": item["fdc_id"], "kidney_notes": item.get("kidney_notes"),
                     "hidden": False, "role": item.get("role")})
    return rows


def food_map(rows: list[Mapping[str, Any]]) -> dict[int, FoodVec]:
    return {r["id"]: make_food(id=r["id"], name=r["name"], category=r["category"], serving_desc=r["serving_desc"],
                               serving_g=r["serving_g"], nutrients=r["nutrients"], flags=r["flags"], source=r["source"],
                               fdc_id=r["fdc_id"], kidney_notes=r["kidney_notes"], hidden=r["hidden"],
                               role_override=r["role"])
            for r in rows}


def foods_for(inp: Mapping[str, Any], foods: Mapping[int, FoodVec]) -> dict[int, FoodVec]:
    """The foods one case may use: ``food_set`` ``fixture`` (ids below 101), ``real`` (101 and up) or ``all``."""
    which = inp["food_set"]
    if which == "all":
        return dict(foods)
    return {i: f for i, f in foods.items() if (i < REAL_ID0) == (which == "fixture")}


def context_from(inp: Mapping[str, Any], all_foods: Mapping[int, FoodVec]) -> GuidanceContext:
    """The replayer: the same context ``app/guidance/context.py`` loads from SQLite. ``food_overrides`` ({id: {nutrient: value}})
    changes a food's values for one case only, such as a food that does not list potassium."""
    foods = foods_for(inp, all_foods)
    rows = {r["id"]: r for r in FOODS}
    for fid, values in (inp.get("food_overrides") or {}).items():
        row = rows[int(fid)]
        foods[int(fid)] = food_map([{**row, "nutrients": {**row["nutrients"], **values}}])[int(fid)]
    def day_entry(e: Mapping[str, Any]) -> DayEntry:
        return day_entry_of(e, foods)

    def history_entry(h: Mapping[str, Any]) -> HistoryEntry:
        return HistoryEntry(date=h["date"], meal=h["meal"], food_id=h["food_id"], name=h["name"], servings=h["servings"],
                            nutrients=dict(h["nutrients"]), purpose=h["purpose"], flags=foods[h["food_id"]].flags)

    profile, prefs = inp["profile"], inp["prefs"]
    history = tuple(history_entry(h) for h in inp["history"])
    return GuidanceContext(
        date=inp["date"],
        profile=Profile(targets=profile["targets"], warn_fraction=profile["warn_fraction"], dialysis=profile["dialysis"],
                        dialysis_days=tuple(profile["dialysis_days"]), diabetes=profile["diabetes"]),
        prefs=Prefs(carb_tolerance_g=prefs["carb_tolerance_g"], hypo_dose_g=prefs["hypo_dose_g"],
                    exclude_food_ids=frozenset(prefs["exclude_food_ids"]),
                    exclude_categories=frozenset(prefs["exclude_categories"]),
                    food_pref={int(fid): kind for fid, kind in prefs.get("food_pref", [])},
                    like_categories=frozenset(prefs.get("like_categories", [])),
                    less_categories=frozenset(prefs.get("less_categories", [])),
                    learn_from_log=bool(prefs.get("learn_from_log", True)),
                    hidden_usual_meals=frozenset(prefs.get("hidden_usual_meals", [])),
                    repeat_ok_food_ids=frozenset(prefs.get("repeat_ok_food_ids", [])),
                    repeat_ok_meal_ids=frozenset(prefs.get("repeat_ok_meal_ids", []))),
        foods=foods,
        day=tuple(day_entry(e) for e in inp["day"]),
        history=history,
        history60=tuple(history_entry(h) for h in inp["history60"]) if inp.get("history60") is not None else history,
        planned30=tuple(PlannedEntry(food_id=p[0], date=p[1], meal=p[2]) for p in inp.get("planned30", [])),
        saved_meals=tuple(SavedMeal(id=m["id"], name=m["name"], meal_hint=m["meal_hint"],
                                    items=tuple((i[0], i[1]) for i in m["items"])) for m in inp["saved_meals"]),
        combos=tuple(Combo(id=c["id"], name=c["name"], meal=c["meal"], items=tuple((i[0], i[1]) for i in c["items"]),
                           source=c["source"]) for c in inp["combos"]),
        tunables=Tunables(**inp["tunables"]),
    )


def day_entry_of(e: Mapping[str, Any], foods: Mapping[int, FoodVec]) -> DayEntry:
    f = foods[e["food_id"]]
    return DayEntry(id=e["id"], meal=e["meal"], status=e["status"], food_id=f.id, name=e["name"], servings=e["servings"],
                    nutrients=dict(e["nutrients"]), purpose=e["purpose"], role=f.role, family=f.family,
                    category=f.category, flags=f.flags)


def _finite(value: Any) -> Any:
    return None if isinstance(value, float) and value == float("inf") else value


def call(inp: Mapping[str, Any], spec: Mapping[str, Any], foods: Mapping[int, FoodVec]) -> Any:
    fn = spec["fn"]
    if fn == "prefilter":
        return hypo.prefilter(spec["text"], spec.get("dose_g", R.HYPO_DOSE_G))
    if fn == "period_insights":
        ctx = context_from(inp, foods)
        hist = lambda rows: [HistoryEntry(date=h["date"], meal=h["meal"], food_id=h["food_id"], name=h["name"],  # noqa: E731
                                          servings=h["servings"], nutrients=dict(h["nutrients"]), purpose=h["purpose"],
                                          flags=foods[h["food_id"]].flags) for h in rows]
        return insights.period_insights(ctx.profile, ctx.prefs, spec["start"], spec["end"], hist(spec["entries"]),
                                        hist(spec.get("previous", [])))
    ctx = context_from(inp, foods)
    if fn == "meal_room":
        room = meal_room(ctx, spec["meal"], open_meals=spec.get("open_meals"))
        return {"open_meals": list(room.open_meals), "room": fits.room_json(room), "meal_has": dict(room.meal_has),
                "meal_high_k": room.meal_high_k, "day_high_k": room.day_high_k,
                "usage_weight": dict(room.usage_weight), "day_left": {k: _finite(v) for k, v in room.day_left.items()}}
    if fn == "what_fits":
        return fits.what_fits(ctx, spec["meal"], limit=spec.get("limit", R.DEFAULT_LIMIT), explain=spec.get("explain", False),
                              exclude=frozenset(spec.get("exclude", ())))
    if fn == "find_swaps":
        return swaps.find_swaps(ctx, spec["meal"], ctx.foods[spec["food_id"]], spec["servings"], spec.get("purpose"),
                                explain=spec.get("explain", False))
    if fn == "hypo_options":
        return swaps.hypo_options(ctx)
    if fn == "plan_day":
        return planner.plan_day(ctx, spec.get("meals"), use_saved_meals=spec.get("use_saved_meals", True),
                                use_usual=spec.get("use_usual", True), use_starters=spec.get("use_starters", True),
                                variant=spec.get("variant", 0))
    if fn == "plan_days":
        days = [ctx.day] + [tuple(day_entry_of(e, ctx.foods) for e in later) for later in spec["later_days"]]
        return planner.plan_days(ctx, days, spec.get("meals"), use_saved_meals=spec.get("use_saved_meals", True),
                                 use_usual=spec.get("use_usual", True), use_starters=spec.get("use_starters", True),
                                 variant=spec.get("variant", 0), repeat_meals=spec.get("repeat_meals", ()),
                                 snack=spec.get("snack"), skip_first_day=spec.get("skip_first_day", ()))
    if fn == "day_insights":
        return insights.day_insights(ctx)
    if fn == "learned":
        return fits.learned(ctx)
    if fn == "fit_recipe":
        target = recipes.Target(spec["target"]["kind"], spec["target"].get("meal"))
        return recipes.fit_recipe(ctx, [(ctx.foods[i], q) for i, q in spec["items"]], spec.get("servings_made"), target)
    raise ValueError(f"unknown fn {fn!r}")


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

FOODS = food_rows()
BY_NAME = {r["name"]: r for r in FOODS}
FIXTURE_TARGETS = dict(fx.TARGETS)
STAGE4 = dict(fx.STAGE4_TARGETS)
HD = dict(fx.HD_TARGETS)


def rid(name: str) -> int:
    return BY_NAME[name]["id"]


def snap(food_id: int, servings: float, override: Mapping[str, float] | None = None) -> dict[str, Any]:
    row = next(r for r in FOODS if r["id"] == food_id)
    values = {k: (None if v is None else v * servings) for k, v in row["nutrients"].items()}
    values.update(override or {})
    return values


def entry(i: int, food_id: int, meal: str, servings: float = 1.0, status: str = "eaten", purpose: str | None = None,
          override: Mapping[str, float] | None = None) -> dict[str, Any]:
    row = next(r for r in FOODS if r["id"] == food_id)
    return {"id": i, "meal": meal, "status": status, "food_id": food_id, "name": row["name"], "servings": servings,
            "purpose": purpose, "nutrients": snap(food_id, servings, override)}


def hist(day: str, food_id: int, meal: str, servings: float = 1.0, purpose: str | None = None,
         override: Mapping[str, float] | None = None) -> dict[str, Any]:
    row = next(r for r in FOODS if r["id"] == food_id)
    return {"date": day, "meal": meal, "food_id": food_id, "name": row["name"], "servings": servings, "purpose": purpose,
            "nutrients": snap(food_id, servings, override)}


def base_input(**kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "date": DATE,
        "food_set": "fixture",
        "profile": {"targets": FIXTURE_TARGETS, "warn_fraction": 0.8, "dialysis": "none", "dialysis_days": [],
                    "diabetes": "type1"},
        "prefs": {"carb_tolerance_g": 10.0, "hypo_dose_g": 15.0, "exclude_food_ids": [], "exclude_categories": [],
                  "food_pref": [], "like_categories": [], "less_categories": [], "learn_from_log": True,
                  "hidden_usual_meals": []},
        "tunables": {"pool_per_role": R.POOL_PER_ROLE, "beam_width": R.BEAM_WIDTH},
        "day": [entry(1, 13, "breakfast"), entry(2, 14, "lunch", status="planned")],
        "history": [hist(d, 13, "breakfast", override={"phosphorus_mg": 1100.0, "protein_g": 49.0})
                    for d in ("2026-10-04", "2026-10-03", "2026-10-01", "2026-09-29")],
        "history60": None,
        "planned30": [],
        "saved_meals": [{"id": 1, "name": "Usual dinner", "meal_hint": "dinner", "items": [[3, 1.0], [1, 1.0], [5, 1.0]]}],
        "combos": [],
    }
    for key, value in kw.items():
        if key in ("targets", "dialysis", "dialysis_days", "diabetes", "warn_fraction"):
            out["profile"] = {**out["profile"], key: value}
        elif key in ("carb_tolerance_g", "hypo_dose_g", "exclude_food_ids", "exclude_categories", "food_pref", "like_categories",
                     "less_categories", "learn_from_log", "hidden_usual_meals", "repeat_ok_food_ids", "repeat_ok_meal_ids"):
            out["prefs"] = {**out["prefs"], key: value}
        else:
            out[key] = value
    return out


def real_input(**kw: Any) -> dict[str, Any]:
    defaults = {"targets": STAGE4, "day": [], "history": [], "saved_meals": [], "food_set": "real"}
    return base_input(**{**defaults, **kw})


def tv_i1_day() -> list[dict[str, Any]]:
    bread = rid("Bread, white")
    return [entry(1, 11, "breakfast", 2.0), entry(2, bread, "breakfast", 2.0), entry(3, 6, "lunch"), entry(4, 1, "lunch"),
            entry(5, 3, "lunch"), entry(6, 2, "dinner"), entry(7, 3, "dinner"), entry(8, 5, "dinner"), entry(9, 1, "dinner"),
            entry(10, 10, "snack", purpose="hypo"), entry(11, 11, "snack", purpose="hypo")]


def tv_i2_entries() -> list[dict[str, Any]]:
    base = [rid("Rice, white, long-grain, cooked"), rid("Chicken breast, roasted, skinless"), rid("Bread, white"),
            rid("Egg, scrambled"), rid("Green beans, boiled"), rid("Apple, raw, with skin"), rid("Pasta, cooked"),
            rid("Milk, 2% reduced fat")]
    out = []
    for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
        out += [hist(d, fid, "lunch") for fid in base]
        if d in ("2026-09-28", "2026-09-30", "2026-10-02", "2026-10-03"):
            out += [hist(d, rid("Cheese, cheddar"), "dinner"), hist(d, rid("Cola, regular"), "snack")]
    return out


def usual_dinner() -> tuple[list[dict[str, Any]], str]:
    """Three dinners of chicken, rice and green beans (a usual meal, 2026-09-30…10-02) and the meal's key."""
    names = ("Chicken breast, roasted, skinless", "Rice, white, long-grain, cooked", "Green beans, boiled")
    rows = [hist(d, rid(n), "dinner") for d in ("2026-09-30", "2026-10-01", "2026-10-02") for n in names]
    return rows, R.usual_meal_key("dinner", [(rid(n), 1.0) for n in names])


def skipped_green_beans(planned_dates: tuple[str, ...], other_dates: tuple[str, ...], eaten_dates: tuple[str, ...] = ()) -> dict[str, Any]:
    """Fixture person who plans green beans (food 5) for dinner on ``planned_dates`` and leaves them planned; on
    ``other_dates`` they ate rice (food 1) at dinner instead, and they ate green beans on ``eaten_dates``."""
    rows = [hist(d, 1, "dinner") for d in other_dates] + [hist(d, 5, "lunch") for d in eaten_dates]
    return {"day": [], "history": rows, "history60": rows, "planned30": [[5, d, "dinner"] for d in planned_dates], "saved_meals": []}


def preference_cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Note 09 §6: P1-P7 and the hand-computed TV-PREF-1 and TV-PREF-2, on the fixture and on the real list."""
    rice, beans, bread = rid("Rice, white, long-grain, cooked"), rid("Green beans, boiled"), rid("Bread, white")
    usual_rows, usual_key = usual_dinner()
    dinners = ("2026-09-28", "2026-09-30", "2026-10-02", "2026-10-03")
    four = skipped_green_beans(dinners, dinners)
    soft = {"food_pref": [[10, "less"], [12, "neutral"], [1, "like"]], "like_categories": ["Beverages"],
            "less_categories": ["Diabetes supplies"], "learn_from_log": False, "hidden_usual_meals": ["dinner:1x4,3x4,5x4"]}
    # The meal the planner builds for an empty day's dinner, as a starter meal: it wins (it scores the same), unless it holds
    # a food the person does not want.
    combo = {"id": "starter-dinner", "name": "Starter dinner: beef, pasta and green beans", "meal": "dinner",
             "items": [[rid("Beef, chuck pot roast, braised"), 1.0], [rid("Pasta, cooked"), 1.5], [beans, 0.5]],
             "source": "diet-guide §6"}
    return [
        # P-terms: the food, the group and the clamp
        ("PREF likes, less often and two food groups (explain)", base_input(
            food_pref=[[4, "like"], [11, "like"], [1, "less"]], like_categories=["Fruits"], less_categories=["Vegetables"]),
         {"fn": "what_fits", "meal": "dinner", "explain": True}),
        ("TV-PREF-2 a green food that is less often and in a less-often group is clamped at -2.5", base_input(
            food_pref=[[5, "less"]], less_categories=["Vegetables"]), {"fn": "what_fits", "meal": "dinner", "explain": True}),
        ("PREF a like lifts a food but not over better ones (real list)", real_input(
            food_pref=[[rid("Apple, raw, with skin"), "like"], [rid("Cheese, cheddar"), "like"], [bread, "like"]]),
         {"fn": "what_fits", "meal": "lunch", "limit": 20, "explain": True}),
        # A food that does not list potassium: a meal with it says which totals are "at least" (``unknown``).
        ("UNKNOWN a saved meal with a food that lists no potassium", base_input(day=[], food_overrides={"3": {"potassium_mg": None}}),
         {"fn": "what_fits", "meal": "dinner"}),
        ("UNKNOWN a planned meal with a food that lists no potassium", base_input(day=[], food_overrides={"3": {"potassium_mg": None}}),
         {"fn": "plan_day", "meals": ["dinner"]}),
        ("UNKNOWN what fits dinner leaves out the chicken, which lists no carbs", base_input(food_overrides={"3": {"carbs_g": None}}),
         {"fn": "what_fits", "meal": "dinner"}),
        # Swap ideas name a value a food does not list as "not listed", and its difference is null, never a difference from 0.
        ("UNKNOWN swaps for star fruit, the blueberries list no carbs or potassium",
         base_input(food_overrides={"7": {"carbs_g": None, "potassium_mg": None}}),
         {"fn": "find_swaps", "meal": "dinner", "food_id": 9, "servings": 1.0}),
        ("UNKNOWN swaps for a potato that lists no carbs, and its smaller portion",
         base_input(food_overrides={"2": {"carbs_g": None}}), {"fn": "find_swaps", "meal": "dinner", "food_id": 2, "servings": 1.0}),
        ("UNKNOWN swaps for a banana, the blueberries list no phosphorus",
         base_input(food_overrides={"7": {"phosphorus_mg": None}}), {"fn": "find_swaps", "meal": "dinner", "food_id": 6, "servings": 1.0}),
        ("UNKNOWN low treatments, the apple juice lists no potassium",
         base_input(food_overrides={"12": {"potassium_mg": None}}), {"fn": "hypo_options"}),
        ("OTHER foods already shown are left out, so the next ones move up (real list)", real_input(),
         {"fn": "what_fits", "meal": "lunch", "limit": 20, "explain": True,
          "exclude": [rid("Apple, raw, with skin"), rid("Cheese, cheddar"), bread, rice]}),
        ("PREF less often on a grain and its group drops it behind the others (real list)", real_input(
            food_pref=[[rice, "less"]], less_categories=["Grains & Breads"]),
         {"fn": "what_fits", "meal": "lunch", "limit": 20, "explain": True}),
        ("PREF a liked group lifts every food in it (real list)", real_input(like_categories=["Fruits"]),
         {"fn": "what_fits", "meal": "snack", "limit": 20, "explain": True}),
        # P5: neutral
        ("PREF breakfast habit (control)", base_input(day=[]), {"fn": "what_fits", "meal": "breakfast", "explain": True}),
        ("PREF a neutral food: no habit history, slot habit or often reason", base_input(day=[], food_pref=[[13, "neutral"]]),
         {"fn": "what_fits", "meal": "breakfast", "explain": True}),
        # P6: learn from my log off, hidden usual meals
        ("PREF learn from my log off: no habit history, slot habit or often reason; the saved meal stays", base_input(
            day=[], learn_from_log=False), {"fn": "what_fits", "meal": "breakfast", "explain": True}),
        ("PREF learn from my log off: the saved meal still ranks, no usual meal", real_input(
            history=usual_rows, learn_from_log=False, saved_meals=[{"id": 1, "name": "Usual dinner", "meal_hint": "dinner",
                                                                    "items": [[rid("Chicken breast, roasted, skinless"), 1.0],
                                                                              [rice, 1.0], [beans, 1.0]]}]),
         {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF a usual dinner (control)", real_input(history=usual_rows), {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF a hidden usual meal is not offered", real_input(history=usual_rows, hidden_usual_meals=[usual_key]),
         {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF another meal's key hides nothing", real_input(history=usual_rows, hidden_usual_meals=["lunch:101x4,109x4,117x4"]),
         {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF a hidden usual meal is not planned", real_input(history=usual_rows, hidden_usual_meals=[usual_key]),
         {"fn": "plan_day", "meals": ["dinner"]}),
        # P7: familiar meals and "Not for me"
        ("PREF a usual meal with a Not for me food is not offered", real_input(history=usual_rows, exclude_food_ids=[beans]),
         {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF a usual meal with a Never suggest group is not offered", real_input(history=usual_rows,
                                                                                   exclude_categories=["Vegetables"]),
         {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF a usual meal with a Not for me food is not planned", real_input(history=usual_rows, exclude_food_ids=[beans]),
         {"fn": "plan_day", "meals": ["dinner"]}),
        ("PREF a saved meal with a Not for me food is still offered", base_input(exclude_food_ids=[5]),
         {"fn": "what_fits", "meal": "dinner", "limit": 3}),
        ("PREF a starter meal (control)", real_input(combos=[combo]), {"fn": "plan_day", "meals": ["dinner"]}),
        ("PREF a starter meal with a Never suggest group is not planned", real_input(
            combos=[combo], exclude_categories=["Vegetables"]), {"fn": "plan_day", "meals": ["dinner"]}),
        ("PREF a starter meal with a Not for me food is not planned", real_input(combos=[combo], exclude_food_ids=[beans]),
         {"fn": "plan_day", "meals": ["dinner"]}),
        # plan and swaps use the same term
        ("PREF plan the rest of the day with likes and less often", base_input(
            food_pref=[[4, "like"], [7, "like"], [1, "less"]], less_categories=["Vegetables"]), {"fn": "plan_day"}),
        ("PREF real list: plan the day with likes and a less-often group", real_input(
            food_pref=[[rid("Tofu, firm"), "like"], [rid("Egg white"), "less"], [rid("Pasta, cooked"), "like"]],
            like_categories=["Fruits"], less_categories=["Sweets & Snacks"]), {"fn": "plan_day"}),
        ("PREF swaps for baked potato with a like and a less often (explain)", base_input(
            food_pref=[[5, "like"], [7, "less"]], like_categories=["Grains & Breads"]),
         {"fn": "find_swaps", "meal": "dinner", "food_id": 2, "servings": 1.0, "explain": True}),
        # planned but not eaten (decision Q5, refined): skipped on dates, eaten on fewer than half of the planned dates
        ("PREF planned but not eaten: green beans skipped on four dinners (explain)", base_input(**four),
         {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        ("PREF planned but not eaten, learned list", base_input(**four), {"fn": "learned"}),
        ("PREF planned, eaten once: still skipped", base_input(**skipped_green_beans(dinners, dinners, ("2026-10-01",))),
         {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        ("PREF planned and eaten on half of the dates: not skipped", base_input(
            **skipped_green_beans(dinners, dinners, ("2026-10-01", "2026-10-04"))), {"fn": "what_fits", "meal": "dinner",
                                                                                     "explain": True}),
        ("PREF planned, but nothing was eaten in those meals: nothing inferred", base_input(
            **skipped_green_beans(dinners, ())), {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        ("PREF skipped on one date only: nothing inferred", base_input(**skipped_green_beans(dinners[:1], dinners[:1])),
         {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        ("PREF skipped, but a neutral food: nothing learned", base_input(**four, food_pref=[[5, "neutral"]]),
         {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        ("PREF skipped, but learn from my log is off", base_input(**four, learn_from_log=False),
         {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        ("PREF skipped and also less often: -2.0 -0.5", base_input(**four, food_pref=[[5, "less"]]),
         {"fn": "what_fits", "meal": "dinner", "limit": 7, "explain": True}),
        # the learned list
        ("PREF learned list: breakfast habit", base_input(day=[]), {"fn": "learned"}),
        ("PREF learned list: a usual dinner", real_input(history=usual_rows), {"fn": "learned"}),
        ("PREF learned list: a hidden usual meal and a neutral food are not listed", real_input(
            history=usual_rows + [hist(d, rid("Banana, raw"), "snack") for d in ("2026-10-01", "2026-10-02")],
            hidden_usual_meals=[usual_key], food_pref=[[rid("Banana, raw"), "neutral"]]), {"fn": "learned"}),
        ("PREF learned list: learn from my log off is empty", real_input(history=usual_rows, learn_from_log=False),
         {"fn": "learned"}),
        # low treatments never read a preference (P4) and the floor (decision Q1)
        ("PREF hypo options ignore every soft preference", base_input(**soft), {"fn": "hypo_options"}),
        ("PREF hypo options: one of two low treatments is Not for me", base_input(exclude_food_ids=[10]), {"fn": "hypo_options"}),
        ("PREF hypo options: both are Not for me, the whole list is shown with a note", base_input(exclude_food_ids=[10, 12]),
         {"fn": "hypo_options"}),
        ("PREF hypo options: their groups are never suggested, the whole list is shown with a note", base_input(
            exclude_categories=["Diabetes supplies", "Beverages"]), {"fn": "hypo_options"}),
        ("PREF real list: every low treatment is Not for me", real_input(
            exclude_food_ids=[rid("Glucose tablet (4 g carb)"), rid("Glucose gel (15 g carb tube)"), rid("Orange juice"),
                              rid("Apple juice"), rid("Cola, regular"), rid("Root beer")]), {"fn": "hypo_options"}),
        ("PREF a low-treatment swap ignores every soft preference", base_input(**soft),
         {"fn": "find_swaps", "meal": "snack", "food_id": 11, "servings": 1.0, "purpose": "hypo"}),
        ("PREF day insights ignore soft preferences", base_input(food_pref=[[10, "less"]], learn_from_log=False,
                                                                 day=tv_i1_day(), history=[], food_set="all"),
         {"fn": "day_insights"}),
    ]


def cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    hd_days = [0, 2, 4]
    out: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        # §6.2 budget
        ("TV-B4 room for dinner", base_input(), {"fn": "meal_room", "meal": "dinner"}),
        ("TV-B5 room for the snack slot", base_input(), {"fn": "meal_room", "meal": "snack"}),
        ("TV-B6 interdialytic allowance", base_input(
            date="2026-10-04", dialysis="hemodialysis", dialysis_days=hd_days, day=[],
            history=[hist("2026-10-02", 2, "dinner", override={"potassium_mg": 2900.0}),
                     hist("2026-10-03", 2, "dinner", override={"potassium_mg": 2900.0})]),
         {"fn": "meal_room", "meal": "dinner"}),
        ("TV-B7 a low treatment at dinner", base_input(day=[entry(1, 13, "breakfast"), entry(2, 14, "lunch", status="planned"),
                                                            entry(3, 10, "dinner", purpose="hypo")]),
         {"fn": "meal_room", "meal": "dinner"}),
        ("planner room with later slots", base_input(day=[]), {"fn": "meal_room", "meal": "lunch",
                                                               "open_meals": ["lunch", "dinner", "snack"]}),
        # §6.3 what fits now
        ("TV-F what fits dinner (explain)", base_input(), {"fn": "what_fits", "meal": "dinner", "explain": True}),
        ("TV-F8 rice excluded", base_input(exclude_food_ids=[1]), {"fn": "what_fits", "meal": "dinner"}),
        ("what fits the snack slot", base_input(), {"fn": "what_fits", "meal": "snack", "limit": 20}),
        ("what fits, no diabetes", base_input(diabetes="none"), {"fn": "what_fits", "meal": "dinner"}),
        ("what fits, potassium over today", base_input(day=[entry(1, 13, "breakfast", 5.0)]),
         {"fn": "what_fits", "meal": "dinner", "explain": True}),
        ("real list: lunch on an empty day", real_input(), {"fn": "what_fits", "meal": "lunch", "explain": True}),
        ("real list: breakfast, carb tolerance 5", real_input(carb_tolerance_g=5.0), {"fn": "what_fits", "meal": "breakfast"}),
        # Alcoholic drinks are never suggested (delayed lows with insulin): not eligible, left out of usual meals.
        ("real list: snack slot, alcohol not eligible", real_input(), {"fn": "what_fits", "meal": "snack", "limit": 20,
                                                                       "explain": True}),
        ("real list: usual dinner without the wine", real_input(history=[
            h for d in ("2026-09-30", "2026-10-01", "2026-10-02") for h in (
                hist(d, rid("Chicken breast, roasted, skinless"), "dinner"), hist(d, rid("Rice, white, long-grain, cooked"), "dinner"),
                hist(d, rid("Green beans, boiled"), "dinner"), hist(d, rid("Wine, red"), "dinner"))]),
         {"fn": "what_fits", "meal": "dinner"}),
        # A saved meal never tips the day into "over" (review L4): 30 mg potassium left today, so the
        # egg-white supper (55 mg, within the dinner room + the 50 mg negligible amount) is offered at ½.
        ("saved meal near the potassium limit", base_input(
            day=[entry(1, 13, "breakfast", override={"potassium_mg": 2470.0})], history=[],
            saved_meals=[{"id": 2, "name": "Egg-white supper", "meal_hint": "dinner", "items": [[4, 1.0]]}]),
         {"fn": "what_fits", "meal": "dinner"}),
        # §6.4 swaps
        ("TV-S1 banana", base_input(), {"fn": "find_swaps", "meal": "dinner", "food_id": 6, "servings": 1.0}),
        ("TV-S2 baked potato", base_input(), {"fn": "find_swaps", "meal": "dinner", "food_id": 2, "servings": 1.0,
                                              "explain": True}),
        ("TV-S3 processed cheese", base_input(), {"fn": "find_swaps", "meal": "dinner", "food_id": 8, "servings": 1.0}),
        ("TV-S4 orange juice for a low", base_input(), {"fn": "find_swaps", "meal": "snack", "food_id": 11, "servings": 1.0,
                                                        "purpose": "hypo"}),
        ("TV-S5 orange juice with a meal", base_input(), {"fn": "find_swaps", "meal": "dinner", "food_id": 11,
                                                          "servings": 1.0}),
        ("TV-S6 no trigger", base_input(), {"fn": "find_swaps", "meal": "dinner", "food_id": 1, "servings": 1.0}),
        ("avoid mode: star fruit", base_input(), {"fn": "find_swaps", "meal": "dinner", "food_id": 9, "servings": 1.0}),
        ("real list: TV-S7 baked potato", real_input(day=[
            entry(1, rid("Bread, white"), "breakfast", 2.0), entry(2, rid("Egg, scrambled"), "breakfast"),
            entry(3, rid("Orange juice"), "breakfast"), entry(4, rid("Chicken breast, roasted, skinless"), "lunch"),
            entry(5, rid("Pasta, cooked"), "lunch"), entry(6, rid("Green beans, boiled"), "lunch")]),
         {"fn": "find_swaps", "meal": "dinner", "food_id": rid("Potato, baked, with skin"), "servings": 1.0}),
        ("real list: TV-S8 processed cheese", real_input(),
         {"fn": "find_swaps", "meal": "dinner", "food_id": rid("Cheese, American, processed"), "servings": 1.0}),
        ("real list: orange juice at dinner, no alcoholic swap", real_input(),
         {"fn": "find_swaps", "meal": "dinner", "food_id": rid("Orange juice"), "servings": 1.0, "purpose": "none",
          "explain": True}),
        ("hypo options, dose 15", base_input(), {"fn": "hypo_options"}),
        ("real list: hypo options, dose 20", real_input(hypo_dose_g=20.0), {"fn": "hypo_options"}),
        # §6.5 plan
        ("TV-P1 plan the rest of the day", base_input(), {"fn": "plan_day"}),
        ("TV-P2 hemodialysis, empty day", base_input(targets={**FIXTURE_TARGETS, "protein_g": {"min": 70, "max": 84},
                                                              "fluid_ml": 1500}, dialysis="hemodialysis", day=[], history=[]),
         {"fn": "plan_day"}),
        ("TV-P6 dinner, variant 1", base_input(), {"fn": "plan_day", "meals": ["dinner"], "variant": 1}),
        ("TV-P7 nothing fits", base_input(day=[entry(1, 13, "breakfast", 5.0)], history=[], saved_meals=[],
                                          exclude_food_ids=[4, 5, 7]), {"fn": "plan_day", "meals": ["dinner"]}),
        ("repair near the potassium limit", base_input(day=[entry(1, 13, "breakfast", override={"potassium_mg": 2400.0})],
                                                       history=[], saved_meals=[]), {"fn": "plan_day"}),
        ("real list: stage 4 empty day", real_input(), {"fn": "plan_day"}),
        ("real list: hemodialysis with combos", real_input(targets=HD, dialysis="hemodialysis", combos=[
            {"id": "starter-dinner", "name": "Starter dinner: chicken, rice and green beans", "meal": "dinner",
             "items": [[rid("Chicken breast, roasted, skinless"), 0.66], [rid("Rice, white, long-grain, cooked"), 0.67],
                       [rid("Green beans, boiled"), 2.0], [rid("Olive oil"), 1.0]], "source": "diet-guide §6"}]),
         {"fn": "plan_day"}),
        ("real list: current stage 4 suggestion", real_input(targets=suggest_targets(70, "4")["targets"]),
         {"fn": "plan_day", "meals": ["lunch", "dinner"]}),
        # §6.6 insights
        ("TV-I1 end of day", base_input(day=tv_i1_day(), history=[], food_set="all"), {"fn": "day_insights"}),
        ("TV-I5 only planned entries", base_input(day=[entry(1, 2, "dinner", status="planned")]), {"fn": "day_insights"}),
        ("interdialytic and energy", base_input(
            date="2026-10-04", food_set="all", dialysis="hemodialysis", dialysis_days=hd_days,
            targets={**FIXTURE_TARGETS, "fluid_ml": 1500},
            day=[entry(1, rid("Rice, white, long-grain, cooked"), m) for m in ("breakfast", "lunch", "dinner")],
            history=[hist("2026-10-03", 2, "dinner", 7.0)]), {"fn": "day_insights"}),
        ("TV-I2 period", base_input(food_set="all"), {"fn": "period_insights", "start": "2026-09-28", "end": "2026-10-04",
                                        "entries": tv_i2_entries(), "previous": []}),
        ("TV-I3 period with two logged days", base_input(food_set="all"), {"fn": "period_insights", "start": "2026-09-28",
                                                             "end": "2026-10-04", "entries": tv_i2_entries()[:16]}),
        # v0.3.0 review: the better low treatment names the portion that reaches the dose (F5).
        ("real list: low treated with juice, dose 20, gel not for me", real_input(
            hypo_dose_g=20.0, targets=HD, dialysis="hemodialysis", exclude_food_ids=[rid("Glucose gel (15 g carb tube)")],
            day=[entry(1, rid("Orange juice"), "snack", 2.0, purpose="hypo")]), {"fn": "day_insights"}),
        ("real list: low treated with juice, dose 30", real_input(
            hypo_dose_g=30.0, day=[entry(1, rid("Orange juice"), "snack", 2.0, purpose="hypo")]), {"fn": "day_insights"}),
        # v0.3.0 review: a nutrient with unknown values is never "within" and never "less than before" (R4).
        ("unknown potassium is never all good", base_input(diabetes="none", day=[
            entry(1, 1, "lunch", override={"potassium_mg": None, "phosphorus_mg": None}), entry(2, 5, "dinner")], history=[]),
         {"fn": "day_insights"}),
        # v0.3.0 review (C1): a room built on totals that miss values is an upper bound ("at most", unknown counts).
        ("room with a spread that lists no potassium, phosphorus or carbs", base_input(day=[
            entry(1, 13, "breakfast"), entry(2, 1, "lunch", override={"potassium_mg": None, "phosphorus_mg": None, "carbs_g": None}),
            entry(3, 5, "dinner", status="planned", override={"potassium_mg": None})]),
         {"fn": "meal_room", "meal": "dinner"}),
        ("what fits dinner after foods that list no potassium", base_input(day=[
            entry(1, 13, "breakfast"), entry(2, 1, "dinner", override={"potassium_mg": None, "carbs_g": None})]),
         {"fn": "what_fits", "meal": "dinner"}),
        ("period with unknown potassium and sodium", base_input(food_set="all"), {
            "fn": "period_insights", "start": "2026-09-28", "end": "2026-10-04",
            "entries": [hist(d, 1, "lunch", override={"potassium_mg": None if d < "2026-10-01" else 500.0, "sodium_mg": None})
                        for d in ("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03",
                                  "2026-10-04")],
            "previous": [hist(d, 1, "lunch", override={"potassium_mg": 2000.0}) for d in ("2026-09-21", "2026-09-22",
                                                                                         "2026-09-23")]}),
    ]
    for i, text in enumerate(("I'm low", "feeling shaky and sweaty", "glucose 3.4", "bg 62", "low-fat milk and toast",
                              "2 eggs, toast with butter, tea", "", "sugar dropped", "cgm says 3,4", "need sugar fast",
                              "I'm at 58, what should I eat", "61 mg/dL", "soup with 60 mg sodium", "sodium 60 mg",
                              "tea with sugar 2 tsp", "lunch at 12:30", "at 1.5 cups", "only ٤٨")):
        out.append((f"prefilter {i + 1}", base_input(), {"fn": "prefilter", "text": text}))
    out += preference_cases()
    out += recipe_cases()
    out += plan_days_cases()
    return out


def plan_days_cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Several days at once (design note 23): variety, the repeat rule, the dialysis interval, the phosphorus week, "Not for
    me", a low treatment already logged, a value a food does not list, and the shopping list."""
    def days(n: int, **kw: Any) -> dict[str, Any]:
        return {"fn": "plan_days", "later_days": [[] for _ in range(n - 1)], **kw}

    only_rice = [2, 3, 4, 5, 6, 7, 8, 11, 13, 14]
    return [
        ("DAYS three days, the rest of today first", base_input(), days(3)),
        ("DAYS four dinners, the saved meal comes back after two days", base_input(day=[], history=[]),
         days(4, meals=["dinner"])),
        ("DAYS nothing else fits, the meal repeats", base_input(day=[], history=[], saved_meals=[], exclude_food_ids=only_rice),
         days(3, meals=["dinner"])),
        ("DAYS hemodialysis, Monday over on potassium", base_input(
            date="2026-10-05", dialysis="hemodialysis", dialysis_days=[0, 2, 4], targets={**FIXTURE_TARGETS, "fluid_ml": 1500},
            day=[entry(1, 2, "lunch", 3.0)], history=[]), days(3, meals=["dinner", "snack"])),
        ("DAYS phosphorus week with a heavy first day", base_input(day=[entry(1, 14, "lunch", 4.0)], history=[]),
         days(2, meals=["dinner"])),
        ("DAYS a low treatment and a logged day later", base_input(day=[entry(1, 10, "snack", purpose="hypo")], history=[]),
         {"fn": "plan_days", "later_days": [[entry(2, 10, "snack", purpose="hypo"), entry(3, 1, "lunch", status="planned")],
                                            [entry(4, 1, m) for m in ("breakfast", "lunch", "dinner", "snack")]]}),
        ("DAYS a food that lists no potassium", base_input(day=[entry(1, 1, "lunch", override={"potassium_mg": None})],
                                                           history=[]), days(2, meals=["dinner"])),
        ("DAYS real list: a week", real_input(), days(7)),
        ("DAYS real list: hemodialysis, not for me, variant 2", real_input(
            targets=HD, dialysis="hemodialysis", dialysis_days=[1, 3, 5],
            exclude_food_ids=[rid("Egg white"), rid("Rice, white, long-grain, cooked")]), days(5, variant=2)),
        # The owner's answers (note 23 §12): meals that may repeat, "OK to repeat" foods and saved meals, the optional snack,
        # the first day's past meals (a low treatment logged that day stays), and a long plan.
        ("DAYS breakfast may repeat on following days", real_input(), days(5, meals=["breakfast"], repeat_meals=["breakfast"])),
        ("DAYS lunch and snack may repeat, the rest rotates", real_input(),
         days(4, repeat_meals=["lunch", "snack"], snack=True)),
        ("DAYS a saved meal marked OK to repeat comes back every day", base_input(day=[], history=[], repeat_ok_meal_ids=[1]),
         days(4, meals=["dinner"])),
        ("DAYS foods marked OK to repeat do not rotate", real_input(repeat_ok_food_ids=[
            rid("Egg, scrambled"), rid("Bread, white"), rid("Rice, white, long-grain, cooked"), rid("Apple, raw, with skin")]),
         days(4)),
        ("DAYS no snack unless asked", base_input(), days(3, snack=False)),
        ("DAYS the snack added to the ticked meals", base_input(day=[], history=[]), days(2, meals=["dinner"], snack=True)),
        ("DAYS the first day's past meals are skipped, the low treatment stays",
         base_input(day=[entry(1, 10, "breakfast", purpose="hypo")], history=[]),
         days(3, skip_first_day=["breakfast", "lunch"], snack=False)),
        ("DAYS every meal of the first day skipped", base_input(day=[], history=[]),
         days(2, skip_first_day=["breakfast", "lunch", "dinner", "snack"])),
        ("DAYS a long plan: 60 breakfasts", base_input(day=[], history=[]), days(60, meals=["breakfast"], snack=False)),
        ("DAYS real list: likes and history", real_input(
            food_pref=[[rid("Tofu, firm"), "like"], [rid("Pasta, cooked"), "less"]],
            history=[hist("2026-10-04", rid("Chicken breast, roasted, skinless"), "dinner"),
                     hist("2026-10-03", rid("Couscous, cooked"), "lunch")]), days(4, meals=["lunch", "dinner"])),
    ]


def recipe_cases() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Recipes that fit (note 16 §9): every status and every move, on the fixture and on real foods."""
    dinner = {"kind": "meal", "meal": "dinner"}

    def fit(items: list[list[float]], n: float | None, target: dict[str, Any] = dinner) -> dict[str, Any]:
        return {"fn": "fit_recipe", "items": items, "servings_made": n, "target": target}

    stew = [[rid("Beef, chuck pot roast, braised"), 4], [rid("Potato, baked, with skin"), 4], [rid("Cheese, cheddar"), 2],
            [rid("Green beans, boiled"), 4], [rid("Milk, 2% reduced fat"), 1]]
    return [
        ("REC fits as it is", base_input(), fit([[1, 2], [5, 2]], 2)),
        ("REC a pot for four, a smaller serving", base_input(), fit([[3, 4], [1, 4], [5, 4]], 4)),
        ("REC the whole pot as one serving does not fit", base_input(), fit([[3, 4], [1, 4], [5, 4]], None)),
        ("REC a food to avoid is swapped", base_input(), fit([[9, 1], [1, 1]], 1)),
        ("REC a low treatment stays", base_input(), fit([[12, 8], [1, 2]], 1)),
        ("REC potatoes swapped at lunch", base_input(), fit([[2, 8], [3, 4]], 4, {"kind": "meal", "meal": "lunch"})),
        ("REC against what is left today", base_input(), fit([[2, 8], [3, 4]], 4, {"kind": "day"})),
        ("REC the next open meal", base_input(), fit([[1, 4], [5, 4]], 4, {"kind": "meal"})),
        ("REC more than 3 servings of a food in a serving is lowered", base_input(), fit([[5, 3.5], [1, 0.5]], 1)),
        ("REC more than 3 servings of a protein food in a serving is swapped", base_input(), fit([[4, 3.5], [1, 0.5]], 1)),
        ("REC a stew on real foods", real_input(), fit(stew, 4)),
        ("REC a stew on real foods, for one", real_input(), fit(stew, 1)),
        ("REC a stew on real foods, the day", real_input(), fit(stew, 2, {"kind": "day"})),
        # A food that does not list a value: the figures and the change lines say "at least" (``unknown`` counts the foods).
        ("UNKNOWN REC lowered potatoes, the green beans list no potassium",
         base_input(food_overrides={"5": {"potassium_mg": None}}), fit([[2, 4], [5, 4]], 4)),
        ("UNKNOWN REC a smaller serving, the rice lists no phosphorus",
         base_input(food_overrides={"1": {"phosphorus_mg": None}}), fit([[3, 4], [1, 4], [5, 4]], 4)),
        ("UNKNOWN REC swaps, the chicken lists no potassium or protein",
         base_input(food_overrides={"3": {"potassium_mg": None, "protein_g": None}}),
         fit([[2, 8], [3, 4]], 4, {"kind": "meal", "meal": "lunch"})),
        ("UNKNOWN REC does not fit, the green beans list no phosphorus",
         base_input(food_overrides={"5": {"phosphorus_mg": None}}), fit([[3, 4], [1, 4], [5, 4]], None)),
    ]


def build() -> dict[str, Any]:
    foods = food_map(FOODS)
    doc_cases = []
    for case_id, inp, spec in cases():
        doc_cases.append({"id": case_id, "input": inp, "call": spec, "output": call(inp, spec, foods)})
    return {
        "format": FORMAT,
        "rules_version": R.RULES_VERSION,
        "rules_hash": R.rules_hash(),
        "about": "Generated by tests/data/gen_guidance_vectors.py from app/guidance/; see its docstring.",
        "foods": FOODS,
        "cases": doc_cases,
    }


def dumps(doc: Mapping[str, Any]) -> str:
    """One food and one case per line (sorted keys), so a rule change shows up as a readable diff."""
    lines = ["{"]
    items = list(doc.items())
    for n, (key, value) in enumerate(items):
        comma = "," if n < len(items) - 1 else ""
        if isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(f"  {json.dumps(key)}: [")
            for m, item in enumerate(value):
                text = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                lines.append("    " + text + ("," if m < len(value) - 1 else ""))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = dumps(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if json.loads(current or "null") != json.loads(text):
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_guidance_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['foods'])} foods, {len(doc['cases'])} cases ({len(text.encode()):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
