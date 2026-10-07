"""The plain data the pure guidance modules work on (note 06 §4.2). No I/O.

:mod:`app.guidance.context` fills these from SQLite for one signed-in person; tests and the parity
vector generator build them by hand. Everything is immutable, so one :class:`GuidanceContext` can be
shared by every function of a request (and the planner adds "virtual" planned entries by building
new tuples, never by mutating).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from . import rules as R
from .vectors import FoodVec


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
