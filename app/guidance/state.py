"""The plain data the pure guidance modules work on (note 06 §4.2). No I/O.

:mod:`app.guidance.context` fills these from SQLite for one signed-in person; tests and the parity
vector generator build them by hand. Everything is immutable, so one :class:`GuidanceContext` can be
shared by every function of a request (and the planner adds "virtual" planned entries by building
new tuples, never by mutating).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..nutrients import NUTRIENT_KEYS
from . import rules as R


@dataclass(frozen=True, slots=True)
class FoodVec:
    """One food as the engine sees it: per-serving numbers as floats (``None`` = unknown)."""

    id: int
    name: str
    category: str | None
    source: str
    fdc_id: int | None
    serving_desc: str
    serving_g: float
    flags: frozenset[str]
    kidney_notes: str | None
    hidden: bool
    nutrients: Mapping[str, float | None]  # all 12 keys, per serving, unrounded
    role: str
    group: str
    family: str
    name_fold: str
    carbs: float | None
    protein: float | None
    k: float | None
    p: float | None
    na: float | None
    fluid: float | None
    kcal: float | None
    additive: bool
    processed: bool
    high_gi: bool
    hypo: bool
    avoid: bool
    ingredient: bool
    supplies: bool
    beverage: bool
    level1: str  # renal level at one serving (pre-ranking)


def make_food(
    *,
    id: int,
    name: str,
    category: str | None,
    serving_desc: str,
    serving_g: float,
    nutrients: Mapping[str, Any],
    flags: Any = (),
    source: str = "builtin",
    fdc_id: int | None = None,
    kidney_notes: str | None = None,
    hidden: bool = False,
    role_override: str | None = None,
) -> FoodVec:
    """Build a :class:`FoodVec` from row-like values (the single place roles and flags are derived)."""
    values: dict[str, float | None] = {}
    for key in NUTRIENT_KEYS:
        v = nutrients.get(key)
        values[key] = None if v is None else float(v)
    flag_set = frozenset(str(f) for f in (flags or ()))
    carbs, protein = values["carbs_g"], values["protein_g"]
    role = R.role_of(category, carbs, protein, role_override)
    additive = "phosphate_additive" in flag_set
    return FoodVec(
        id=int(id),
        name=str(name),
        category=category,
        source=source,
        fdc_id=fdc_id,
        serving_desc=str(serving_desc),
        serving_g=float(serving_g),
        flags=flag_set,
        kidney_notes=kidney_notes,
        hidden=bool(hidden),
        nutrients=values,
        role=role,
        group=R.group_of(role),
        family=R.family_of(name),
        name_fold=str(name).casefold(),
        carbs=carbs,
        protein=protein,
        k=values["potassium_mg"],
        p=values["phosphorus_mg"],
        na=values["sodium_mg"],
        fluid=values["fluid_ml"],
        kcal=values["calories_kcal"],
        additive=additive,
        processed="processed" in flag_set,
        high_gi="high_gi" in flag_set,
        hypo="hypo_treatment" in flag_set,
        avoid="avoid_ckd" in flag_set,
        ingredient=R.INGREDIENT_FLAG in flag_set,
        supplies=category == R.SUPPLIES_CATEGORY,
        beverage=category == R.BEVERAGES,
        level1=R.renal_level(values["potassium_mg"], values["phosphorus_mg"], values["sodium_mg"], additive),
    )


@dataclass(frozen=True, slots=True)
class DayEntry:
    """One log entry of the requested day (eaten or planned), or a virtual planned item of a plan.

    ``nutrients`` is the entry snapshot (already multiplied by ``servings``); ``id`` is ``None`` for
    virtual items. Role, family and flags come from the entry's food.
    """

    id: int | None
    meal: str
    status: str
    food_id: int
    name: str
    servings: float
    nutrients: Mapping[str, float | None]
    purpose: str | None
    role: str
    family: str
    category: str | None
    flags: frozenset[str]

    @property
    def hypo(self) -> bool:
        return self.purpose == "hypo"

    @property
    def group(self) -> str:
        return R.group_of(self.role)

    def get(self, key: str) -> float | None:
        return self.nutrients.get(key)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """An eaten entry from an earlier day (habit, variety, week allowance, usual meals, insights)."""

    date: str
    meal: str
    food_id: int
    name: str
    servings: float
    nutrients: Mapping[str, float | None]
    purpose: str | None
    flags: frozenset[str] = frozenset()

    @property
    def hypo(self) -> bool:
        return self.purpose == "hypo"


@dataclass(frozen=True, slots=True)
class SavedMeal:
    id: int
    name: str
    meal_hint: str | None
    items: tuple[tuple[int, float], ...]  # (food_id, servings)


@dataclass(frozen=True, slots=True)
class Combo:
    """A starter combo from ``data/combos.json`` with its builtin ``fdc_id`` items resolved to food ids."""

    id: str
    name: str
    meal: str
    items: tuple[tuple[int, float], ...]
    source: str


@dataclass(frozen=True, slots=True)
class Prefs:
    """The person's guidance settings (note 06 §4.14; registry key ``guidance``) and "Not for me" foods."""

    carb_tolerance_g: float = float(R.CARB_TOLERANCE_G)
    hypo_dose_g: float = float(R.HYPO_DOSE_G)
    exclude_food_ids: frozenset[int] = frozenset()
    exclude_categories: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Tunables:
    """Admin tunables (``GUIDANCE_POOL_PER_ROLE``, ``GUIDANCE_BEAM_WIDTH``)."""

    pool_per_role: int = R.POOL_PER_ROLE
    beam_width: int = R.BEAM_WIDTH


@dataclass(frozen=True, slots=True)
class Profile:
    """The targets and the parts of the profile guidance reads (the same values the Today screen uses)."""

    targets: Mapping[str, Any]
    warn_fraction: float = 0.8
    dialysis: str = "none"
    dialysis_days: tuple[int, ...] = ()
    diabetes: str = "type1"
    targets_updated_at: str | None = None


@dataclass(frozen=True)
class GuidanceContext:
    """Everything one guidance request needs, for one person and one date (note 06 §4.2)."""

    date: str
    profile: Profile
    prefs: Prefs
    foods: Mapping[int, FoodVec]  # every food the person may use (hidden ones too, for old entries)
    day: tuple[DayEntry, ...] = ()
    history: tuple[HistoryEntry, ...] = ()  # eaten entries of date-13 … date-1
    history60: tuple[HistoryEntry, ...] = ()  # eaten entries of date-60 … date-1 (usual meals)
    saved_meals: tuple[SavedMeal, ...] = ()
    combos: tuple[Combo, ...] = ()
    tunables: Tunables = field(default_factory=Tunables)

    def with_day(self, day: tuple[DayEntry, ...]) -> "GuidanceContext":
        """A copy with another day (the planner's virtual entries, a swap without the entry itself)."""
        return GuidanceContext(
            date=self.date, profile=self.profile, prefs=self.prefs, foods=self.foods, day=day,
            history=self.history, history60=self.history60, saved_meals=self.saved_meals, combos=self.combos,
            tunables=self.tunables,
        )


def virtual_entry(food: FoodVec, meal: str, servings: float) -> DayEntry:
    """A planned entry the planner has placed but not saved."""
    scaled = {key: (None if v is None else v * servings) for key, v in food.nutrients.items()}
    return DayEntry(
        id=None, meal=meal, status="planned", food_id=food.id, name=food.name, servings=servings,
        nutrients=scaled, purpose=None, role=food.role, family=food.family, category=food.category, flags=food.flags,
    )
