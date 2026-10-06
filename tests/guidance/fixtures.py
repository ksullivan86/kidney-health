"""The note 06 §6.1 fixture as pure engine data (no database), plus small builders for other cases.

Targets: potassium 2,500 mg, phosphorus 1,000 mg, sodium 2,000 mg, protein 42–56 g, carbs 236 g with
60 g per meal, no fluid limit, calories 2,100 kcal, calcium 1,000 mg; warn at 80 %; no dialysis; type 1;
carb tolerance 10 g. Date 2026-10-05 (a Monday). Food 13 is eaten at breakfast and food 14 planned at
lunch. History: on 2026-10-04, 10-03, 10-01 and 09-29 one eaten breakfast entry of food 13 with
1,100 mg phosphorus and 49 g protein (4 logged days of the previous 6; the spec gives only the
numbers, and TV-F3's −0.58 for food 13 needs those entries to be food 13). Saved meal 1 "Usual dinner"
(``meal_hint`` dinner): chicken × 1, rice × 1, green beans × 1.

The synthetic foods carry no calories, so the energy note stays empty (§4.10 note under plan-day).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.guidance.state import Combo, DayEntry, GuidanceContext, HistoryEntry, Prefs, Profile, SavedMeal
from app.guidance.vectors import FoodVec, make_food
from app.nutrients import NUTRIENT_KEYS

DATE = "2026-10-05"

TARGETS: dict[str, Any] = {
    "potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 42, "max": 56},
    "carbs_g": 236, "carbs_per_meal_g": 60, "fluid_ml": None, "calories_kcal": 2100, "calcium_mg": 1000,
}

# id, name, category, serving, carbs, protein, K, P, Na, fluid, flags
FOOD_ROWS: tuple[tuple[Any, ...], ...] = (
    (1, "Rice, white, cooked", "Grains & Breads", "1 cup (158 g)", 158, 45, 4, 55, 70, 0, 0, ()),
    (2, "Potato, baked", "Vegetables", "1 medium (173 g)", 173, 37, 4, 925, 120, 15, 0, ()),
    (3, "Chicken breast, roasted", "Meat, Poultry & Eggs", "3 oz (85 g)", 85, 0, 27, 220, 195, 65, 0, ()),
    (4, "Egg white, cooked", "Meat, Poultry & Eggs", "1 large (33 g)", 33, 0, 3.6, 55, 5, 55, 0, ()),
    (5, "Green beans, boiled", "Vegetables", "1/2 cup (63 g)", 63, 5, 1, 90, 20, 0, 0, ()),
    (6, "Banana", "Fruits", "1 medium (118 g)", 118, 27, 1, 420, 25, 0, 0, ()),
    (7, "Blueberries", "Fruits", "1/2 cup (74 g)", 74, 11, 0.5, 55, 10, 0, 0, ("low_potassium_fruit",)),
    (8, "Cheese, processed", "Dairy & Alternatives", "1 slice (28 g)", 28, 1, 5, 35, 180, 470, 0,
     ("phosphate_additive", "processed")),
    (9, "Star fruit", "Fruits", "1 medium (91 g)", 91, 6, 0, 120, 11, 0, 0, ("avoid_ckd",)),
    (10, "Glucose tablets, 4", "Diabetes supplies", "4 tablets (16 g)", 16, 16, 0, 0, 0, 0, 0,
     ("hypo_treatment", "high_gi")),
    (11, "Orange juice", "Beverages", "1/2 cup (124 g)", 124, 13, 1, 250, 20, 0, 110, ("high_gi", "counts_as_fluid")),
    (12, "Apple juice", "Beverages", "1/2 cup (124 g)", 124, 14, 0, 125, 9, 0, 110,
     ("hypo_treatment", "high_gi", "counts_as_fluid")),
    (13, "Breakfast block (test)", "Prepared & Fast Food", "1 serving", 100, 55, 15, 600, 250, 500, 0, ()),
    (14, "Lunch block (test)", "Prepared & Fast Food", "1 serving", 100, 60, 20, 700, 300, 600, 0, ()),
)


def nutrients(carbs: float | None, protein: float | None, k: float | None, p: float | None, na: float | None,
              fluid: float | None, kcal: float | None = None) -> dict[str, float | None]:
    values: dict[str, float | None] = {key: None for key in NUTRIENT_KEYS}
    values.update({"carbs_g": carbs, "protein_g": protein, "potassium_mg": k, "phosphorus_mg": p, "sodium_mg": na,
                   "fluid_ml": fluid, "calories_kcal": kcal})
    return values


def food(row: tuple[Any, ...], **extra: Any) -> FoodVec:
    fid, name, cat, desc, grams, carbs, protein, k, p, na, fluid, flags = row
    return make_food(id=fid, name=name, category=cat, serving_desc=desc, serving_g=grams,
                     nutrients=nutrients(carbs, protein, k, p, na, fluid), flags=flags, fdc_id=10000 + fid, **extra)


def foods(rows: Iterable[tuple[Any, ...]] = FOOD_ROWS) -> dict[int, FoodVec]:
    return {row[0]: food(row) for row in rows}


def entry(f: FoodVec, meal: str, servings: float = 1.0, status: str = "eaten", purpose: str | None = None,
          entry_id: int | None = None, override: Mapping[str, float] | None = None) -> DayEntry:
    values = {k: (None if v is None else v * servings) for k, v in f.nutrients.items()}
    if override:
        values.update(override)
    return DayEntry(id=entry_id, meal=meal, status=status, food_id=f.id, name=f.name, servings=servings,
                    nutrients=values, purpose=purpose, role=f.role, family=f.family, category=f.category, flags=f.flags)


def hist(f: FoodVec, date: str, meal: str, servings: float = 1.0, purpose: str | None = None,
         override: Mapping[str, float] | None = None) -> HistoryEntry:
    values = {k: (None if v is None else v * servings) for k, v in f.nutrients.items()}
    if override:
        values.update(override)
    return HistoryEntry(date=date, meal=meal, food_id=f.id, name=f.name, servings=servings, nutrients=values,
                        purpose=purpose, flags=f.flags)


def fixture_history(fs: Mapping[int, FoodVec]) -> tuple[HistoryEntry, ...]:
    return tuple(
        hist(fs[13], d, "breakfast", override={"phosphorus_mg": 1100.0, "protein_g": 49.0})
        for d in ("2026-10-04", "2026-10-03", "2026-10-01", "2026-09-29")
    )


SAVED_MEAL = SavedMeal(id=1, name="Usual dinner", meal_hint="dinner", items=((3, 1.0), (1, 1.0), (5, 1.0)))


def context(
    *,
    targets: Mapping[str, Any] | None = None,
    day: Iterable[DayEntry] | None = None,
    history: Iterable[HistoryEntry] | None = None,
    history60: Iterable[HistoryEntry] | None = None,
    saved: Iterable[SavedMeal] | None = None,
    combos: Iterable[Combo] = (),
    prefs: Prefs | None = None,
    dialysis: str = "none",
    dialysis_days: tuple[int, ...] = (),
    diabetes: str = "type1",
    date: str = DATE,
    food_map: Mapping[int, FoodVec] | None = None,
    warn_fraction: float = 0.8,
) -> GuidanceContext:
    fs = dict(food_map) if food_map is not None else foods()
    if day is None:
        day = (entry(fs[13], "breakfast", entry_id=1), entry(fs[14], "lunch", status="planned", entry_id=2))
    if history is None:
        history = fixture_history(fs)
    return GuidanceContext(
        date=date,
        profile=Profile(targets=dict(targets if targets is not None else TARGETS), warn_fraction=warn_fraction,
                        dialysis=dialysis, dialysis_days=dialysis_days, diabetes=diabetes),
        prefs=prefs or Prefs(),
        foods=fs,
        day=tuple(day),
        history=tuple(history),
        history60=tuple(history60 if history60 is not None else history),
        saved_meals=tuple(saved if saved is not None else (SAVED_MEAL,)),
        combos=tuple(combos),
    )


# --------------------------------------------------------------------------- #
# The real builtin food list (data/foods.json), as the database would hold it on a fresh install
# (ids in file order), for TV-S7, TV-S8, TV-P3, TV-P4 and the performance tests.
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parents[2]
FOODS_JSON = ROOT / "data" / "foods.json"


@lru_cache(maxsize=1)
def real_food_items() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(FOODS_JSON.read_text(encoding="utf-8"))["foods"])


def real_foods(copies: int = 1) -> dict[int, FoodVec]:
    """``copies`` > 1 adds perturbed copies (names suffixed, numbers ×(1 ± a few %)) for the 2,000-food
    performance tests (§4.12: "5 perturbed copies of foods.json")."""
    out: dict[int, FoodVec] = {}
    items = real_food_items()
    next_id = 1
    for copy in range(copies):
        for index, item in enumerate(items):
            factor = 1.0 + (((index * 7 + copy * 13) % 11) - 5) / 100.0 if copy else 1.0
            values = {k: (None if v is None else float(v) * factor) for k, v in item["nutrients"].items()}
            name = item["name"] if copy == 0 else f"{item['name']} (copy {copy})"
            out[next_id] = make_food(
                id=next_id, name=name, category=item["category"], serving_desc=item["serving_desc"],
                serving_g=item["serving_g"], nutrients=values, flags=item.get("flags") or (),
                fdc_id=item["fdc_id"] if copy == 0 else None, kidney_notes=item.get("kidney_notes"),
                role_override=item.get("role"),
            )
            next_id += 1
    return out


def by_name(food_map: Mapping[int, FoodVec], name: str) -> FoodVec:
    for f in food_map.values():
        if f.name == name:
            return f
    raise KeyError(name)


# note 06 TV-S7/TV-P3: suggest_targets(70, "4") as it was when the note was written (protein 0.6–0.8 g/kg;
# v0.3 decision 10 later raised the floor to 0.8 g/kg, which test_planner checks separately).
STAGE4_TARGETS: dict[str, Any] = {
    "calories_kcal": 2100, "protein_g": {"min": 42, "max": 56}, "carbs_g": 236, "carbs_per_meal_g": 60,
    "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": None,
}
HD_TARGETS: dict[str, Any] = {
    "calories_kcal": 2100, "protein_g": {"min": 70, "max": 84}, "carbs_g": 236, "carbs_per_meal_g": 60,
    "sodium_mg": 2000, "potassium_mg": 2500, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": 1500,
}
