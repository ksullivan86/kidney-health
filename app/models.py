"""Pydantic v2 request/response models (shapes from ARCHITECTURE.md)."""
from __future__ import annotations

import math
import re
from datetime import date as _date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .nutrients import FLAGS, NUTRIENT_KEYS, TARGET_KEYS
from .periods import normalise_dialysis_days

# Ceilings for numeric request fields. Pydantic floats accept the JSON literals Infinity/NaN
# and 1e308 unless told otherwise; an infinite snapshot made every day/range/summary read 500.
MAX_SERVINGS = 1000.0  # servings of one food in one entry (or one saved-meal item)
MIN_SERVING_G = 0.1  # a serving lighter than this makes grams / serving_g explode
MAX_SERVING_G = 100_000.0  # 100 kg
MAX_GRAMS = 100_000.0  # weight entered for one entry
MAX_SCALE = 100.0  # saved-meal apply scale
MAX_NUTRIENT_VALUE = 1_000_000.0  # per serving (1 kg of a mineral, 1e6 kcal) or per target
MAX_SQLITE_INT = 2**63 - 1  # larger ids make the sqlite3 binding raise OverflowError

Meal = Literal["breakfast", "lunch", "dinner", "snack"]
CkdStage = Literal["1", "2", "3a", "3b", "4", "5"]
Dialysis = Literal["none", "hemodialysis", "peritoneal"]
Diabetes = Literal["none", "type1", "type2"]
Level = Literal["medium", "high"]
Rating = Literal["green", "yellow", "red"]
StatusLevel = Literal["ok", "caution", "over"]
EntryStatus = Literal["eaten", "planned"]  # v0.2
WeekStart = Literal["monday", "sunday"]  # v0.2
CopyInclude = Literal["all", "eaten", "planned"]  # v0.2
Assessment = Literal["daily", "weekly_average"]  # v0.2

# int | float keeps integers (mg, mL) as integers in JSON instead of coercing to 422.0.
Number = int | float

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FLAG_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def validate_date(value: str) -> str:
    """Accept only ``YYYY-MM-DD`` that is a real calendar date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError("date must be formatted YYYY-MM-DD")
    try:
        _date.fromisoformat(value)
    except ValueError as exc:  # e.g. 2026-02-30
        raise ValueError("date is not a valid calendar date") from exc
    return value


def validate_nutrients(values: dict[str, Any] | None) -> dict[str, float | None]:
    """Keys must be registry keys; values non-negative numbers or null."""
    if values is None:
        return {}
    unknown = sorted(set(values) - set(NUTRIENT_KEYS))
    if unknown:
        raise ValueError(f"unknown nutrient key(s): {', '.join(unknown)}")
    out: dict[str, float | None] = {}
    for key, v in values.items():
        if v is None or v == "":
            out[key] = None
            continue
        if isinstance(v, bool):
            raise ValueError(f"{key} must be a number")
        try:
            num = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc
        if not math.isfinite(num) or num < 0:  # NaN, +/-Infinity or negative
            raise ValueError(f"{key} must be a non-negative number")
        if num > MAX_NUTRIENT_VALUE:
            raise ValueError(f"{key} must be at most {MAX_NUTRIENT_VALUE:g}")
        out[key] = num
    return out


def validate_flags(flags: list[str] | None) -> list[str]:
    """Normalise flags: strip, lower-case, de-duplicate, keep snake_case tokens."""
    if not flags:
        return []
    out: list[str] = []
    for raw in flags:
        if not isinstance(raw, str):
            raise ValueError("flags must be strings")
        flag = raw.strip().lower()
        if not flag:
            continue
        if not _FLAG_RE.match(flag):
            raise ValueError(f"invalid flag {raw!r}; use lowercase letters, digits and underscores")
        if flag not in out:
            out.append(flag)
    return out


class Range(BaseModel):
    """A target with a floor and/or a ceiling (used for protein)."""

    model_config = ConfigDict(extra="forbid")

    min: float | None = Field(default=None, ge=0, le=MAX_NUTRIENT_VALUE, allow_inf_nan=False)
    max: float | None = Field(default=None, ge=0, le=MAX_NUTRIENT_VALUE, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check_order(self) -> "Range":
        if self.min is None and self.max is None:
            raise ValueError("a range needs min and/or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


TargetValue = Number | Range | None


def validate_targets(targets: dict[str, Any] | None) -> dict[str, Any]:
    if targets is None:
        return {}
    unknown = sorted(set(targets) - set(TARGET_KEYS))
    if unknown:
        raise ValueError(f"unknown target key(s): {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for key, v in targets.items():
        if v is None:
            out[key] = None
        elif isinstance(v, Range):
            out[key] = v
        elif isinstance(v, dict):
            out[key] = Range.model_validate(v)
        elif isinstance(v, bool):
            raise ValueError(f"{key} target must be a number, a {{min,max}} object or null")
        else:
            try:
                num = float(v)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} target must be a number, a {{min,max}} object or null") from exc
            if not math.isfinite(num):
                raise ValueError(f"{key} target must be a finite number")
            if num < 0:
                raise ValueError(f"{key} target must not be negative")
            if num > MAX_NUTRIENT_VALUE:
                raise ValueError(f"{key} target must be at most {MAX_NUTRIENT_VALUE:g}")
            out[key] = int(num) if num.is_integer() else num
    return out


# --------------------------------------------------------------------------- #
# Shared pieces
# --------------------------------------------------------------------------- #


class Warning(BaseModel):
    nutrient: str | None
    level: Level
    value: Number | None = None
    flag: str | None = None
    message: str


class Counts(BaseModel):
    """How many entries of each status a day holds (v0.2)."""

    eaten: int
    planned: int


# --------------------------------------------------------------------------- #
# Foods
# --------------------------------------------------------------------------- #


class FoodCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    serving_desc: str = Field(min_length=1, max_length=200)
    serving_g: float = Field(ge=MIN_SERVING_G, le=MAX_SERVING_G, allow_inf_nan=False)
    nutrients: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    kidney_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("nutrients")
    @classmethod
    def _nutrients(cls, v: dict[str, Any] | None) -> dict[str, float | None]:
        return validate_nutrients(v)

    @field_validator("flags")
    @classmethod
    def _flags(cls, v: list[str] | None) -> list[str]:
        return validate_flags(v)

    @field_validator("brand", "category", "kidney_notes")
    @classmethod
    def _empty_to_none(cls, v: str | None) -> str | None:
        return v or None


class Food(BaseModel):
    id: int
    name: str
    brand: str | None
    category: str | None
    source: str
    fdc_id: int | None
    serving_desc: str
    serving_g: Number
    nutrients: dict[str, Number | None]
    flags: list[str]
    kidney_notes: str | None
    hidden: bool
    warnings: list[Warning]
    kidney_rating: Rating


class FoodList(BaseModel):
    foods: list[Food]


class Categories(BaseModel):
    categories: list[str]


class UsdaSearchHit(BaseModel):
    fdc_id: int
    description: str
    data_type: str | None = None
    brand: str | None = None
    category: str | None = None


class UsdaSearchResult(BaseModel):
    foods: list[UsdaSearchHit]


class UsdaImport(BaseModel):
    fdc_id: int = Field(gt=0, le=MAX_SQLITE_INT)


# --------------------------------------------------------------------------- #
# Log
# --------------------------------------------------------------------------- #


class LogCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    meal: Meal
    food_id: int = Field(ge=1, le=MAX_SQLITE_INT)
    servings: float | None = Field(default=None, gt=0, le=MAX_SERVINGS, allow_inf_nan=False)
    grams: float | None = Field(default=None, gt=0, le=MAX_GRAMS, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=500)
    status: EntryStatus = "eaten"

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)


class LogUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str | None = None
    meal: Meal | None = None
    servings: float | None = Field(default=None, gt=0, le=MAX_SERVINGS, allow_inf_nan=False)
    grams: float | None = Field(default=None, gt=0, le=MAX_GRAMS, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=500)
    status: EntryStatus | None = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return None if v is None else validate_date(v)


class QuickAdd(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    meal: Meal
    name: str = Field(min_length=1, max_length=200)
    serving_desc: str = Field(default="1 serving", min_length=1, max_length=200)
    serving_g: float = Field(default=100, ge=MIN_SERVING_G, le=MAX_SERVING_G, allow_inf_nan=False)
    nutrients: dict[str, Any] = Field(default_factory=dict)
    servings: float = Field(default=1, gt=0, le=MAX_SERVINGS, allow_inf_nan=False)
    flags: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)
    status: EntryStatus = "eaten"

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("nutrients")
    @classmethod
    def _nutrients(cls, v: dict[str, Any] | None) -> dict[str, float | None]:
        return validate_nutrients(v)

    @field_validator("flags")
    @classmethod
    def _flags(cls, v: list[str] | None) -> list[str]:
        return validate_flags(v)


class Entry(BaseModel):
    id: int
    date: str
    meal: Meal
    food_id: int
    food_name: str
    servings: Number
    grams: Number | None
    note: str | None
    status: EntryStatus
    nutrients: dict[str, Number | None]
    warnings: list[Warning]
    kidney_rating: Rating
    created_at: str
    updated_at: str


class MarkEaten(BaseModel):
    """``POST /api/log/mark-eaten``: every planned entry of the day (or meal) becomes eaten."""

    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    meal: Meal | None = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)


class MarkEatenResult(BaseModel):
    updated: int


class CopyDay(BaseModel):
    """``POST /api/log/copy-day``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    from_date: str
    to_date: str
    meals: list[Meal] | None = None
    include: CopyInclude = "all"
    status: EntryStatus = "planned"

    @field_validator("from_date", "to_date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("meals")
    @classmethod
    def _meals(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("meals must not be empty; omit it to copy every meal")
        out: list[str] = []
        for meal in v:
            if meal not in out:
                out.append(meal)
        return out

    @model_validator(mode="after")
    def _distinct_days(self) -> "CopyDay":
        if self.from_date == self.to_date:
            raise ValueError("from_date and to_date must differ")
        return self


class CopyDayResult(BaseModel):
    created: int
    entries: list[Entry]


class NutrientStatus(BaseModel):
    value: Number | None
    target: Number | None
    min: Number | None = None
    fraction: float | None
    level: StatusLevel


class Alert(BaseModel):
    level: Literal["caution", "over"]
    nutrient: str
    meal: Meal | None = None
    message: str


class DaySummary(BaseModel):
    date: str
    entries: list[Entry]
    totals: dict[str, Number | None]
    planned_totals: dict[str, Number | None]
    projected_totals: dict[str, Number | None]
    targets: dict[str, TargetValue]
    status: dict[str, NutrientStatus]
    projected_status: dict[str, NutrientStatus]
    meals: dict[str, dict[str, Number | None]]
    planned_meals: dict[str, dict[str, Number | None]]
    alerts: list[Alert]
    projected_alerts: list[Alert]
    counts: Counts


class DayTotals(BaseModel):
    date: str
    totals: dict[str, Number | None]
    planned_totals: dict[str, Number | None]
    projected_totals: dict[str, Number | None]
    status: dict[str, NutrientStatus]
    projected_status: dict[str, NutrientStatus]
    counts: Counts


class RangeSummary(BaseModel):
    days: list[DayTotals]


# --------------------------------------------------------------------------- #
# Period summary (v0.2)
# --------------------------------------------------------------------------- #


class MaxDay(BaseModel):
    date: str
    value: Number


class PeriodNutrient(BaseModel):
    role: str
    target: Number
    total: Number
    average: Number | None
    fraction: float | None
    level: StatusLevel
    days_over: int
    max_day: MaxDay | None
    previous_average: Number | None
    change_pct: float | None
    assessment: Assessment


class InterdialyticNutrient(BaseModel):
    total: Number
    limit: Number
    fraction: float
    level: StatusLevel


class Interdialytic(BaseModel):
    since: str
    days: int
    next: str
    nutrients: dict[str, InterdialyticNutrient]


class PeriodSummary(BaseModel):
    start: str
    end: str
    days: int
    logged_days: int
    nutrients: dict[str, PeriodNutrient]
    interdialytic: Interdialytic | None
    notes: list[str]


# --------------------------------------------------------------------------- #
# Saved meals (v0.2)
# --------------------------------------------------------------------------- #


class MealItemIn(BaseModel):
    food_id: int = Field(ge=1, le=MAX_SQLITE_INT)
    servings: float = Field(gt=0, le=MAX_SERVINGS, allow_inf_nan=False)


class MealTemplateCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    items: list[MealItemIn] = Field(min_length=1)

    @field_validator("note")
    @classmethod
    def _empty_to_none(cls, v: str | None) -> str | None:
        return v or None


class MealItem(BaseModel):
    food_id: int
    food_name: str
    servings: Number
    serving_desc: str
    nutrients: dict[str, Number | None]
    kidney_rating: Rating
    hidden: bool


class MealTemplate(BaseModel):
    id: int
    name: str
    note: str | None
    items: list[MealItem]
    totals: dict[str, Number | None]
    kidney_rating: Rating
    created_at: str
    updated_at: str


class MealList(BaseModel):
    meals: list[MealTemplate]


class MealFromLog(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    meal: Meal
    name: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("note")
    @classmethod
    def _empty_to_none(cls, v: str | None) -> str | None:
        return v or None


class MealApply(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str
    meal: Meal
    status: EntryStatus = "planned"
    scale: float = Field(default=1, gt=0, le=MAX_SCALE, allow_inf_nan=False)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)


class MealApplyResult(BaseModel):
    entries: list[Entry]


# --------------------------------------------------------------------------- #
# Shopping list (v0.2)
# --------------------------------------------------------------------------- #


class ShoppingItem(BaseModel):
    food_id: int
    food_name: str
    serving_desc: str
    servings: Number
    grams: Number
    days: int


class ShoppingList(BaseModel):
    items: list[ShoppingItem]


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=100)
    weight_kg: float | None = Field(default=None, gt=0, le=500, allow_inf_nan=False)
    height_cm: float | None = Field(default=None, gt=0, le=300, allow_inf_nan=False)
    ckd_stage: CkdStage | None = None
    dialysis: Dialysis | None = None
    diabetes: Diabetes | None = None
    warn_fraction: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    targets: dict[str, Any] | None = None
    dialysis_days: list[Any] | None = None
    week_start: WeekStart | None = None

    @field_validator("targets")
    @classmethod
    def _targets(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if v is None else validate_targets(v)

    @field_validator("dialysis_days")
    @classmethod
    def _dialysis_days(cls, v: list[Any] | None) -> list[int] | None:
        """Weekdays 0 (Mon) .. 6 (Sun); duplicates dropped, sorted. ``null`` clears the list."""
        return normalise_dialysis_days(v)


class Profile(BaseModel):
    id: int
    name: str
    weight_kg: Number | None
    height_cm: Number | None
    ckd_stage: CkdStage
    dialysis: Dialysis
    diabetes: Diabetes
    warn_fraction: float
    dialysis_days: list[int]
    week_start: WeekStart
    targets: dict[str, TargetValue]
    updated_at: str


class SuggestedTargets(BaseModel):
    targets: dict[str, TargetValue]
    notes: list[str]


# Exported for the routers.
__all__ = [
    "Alert",
    "Categories",
    "CopyDay",
    "CopyDayResult",
    "Counts",
    "DaySummary",
    "DayTotals",
    "Entry",
    "FLAGS",
    "Food",
    "FoodCreate",
    "FoodList",
    "Interdialytic",
    "InterdialyticNutrient",
    "LogCreate",
    "LogUpdate",
    "MarkEaten",
    "MarkEatenResult",
    "MaxDay",
    "MealApply",
    "MealApplyResult",
    "MealFromLog",
    "MealItem",
    "MealItemIn",
    "MealList",
    "MealTemplate",
    "MealTemplateCreate",
    "NutrientStatus",
    "PeriodNutrient",
    "PeriodSummary",
    "Profile",
    "ProfileUpdate",
    "QuickAdd",
    "Range",
    "RangeSummary",
    "ShoppingItem",
    "ShoppingList",
    "SuggestedTargets",
    "UsdaImport",
    "UsdaSearchHit",
    "UsdaSearchResult",
    "Warning",
    "validate_date",
    "validate_flags",
    "validate_nutrients",
    "validate_targets",
]
