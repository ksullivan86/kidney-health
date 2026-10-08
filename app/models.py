"""Pydantic v2 request/response models (shapes from ARCHITECTURE.md)."""
from __future__ import annotations

import math
import re
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

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
# v0.3 personalised targets (note 05 §4.2, §4.6); the pure modules keep the same tuples.
Sex = Literal["female", "male", "unspecified"]
Activity = Literal["inactive", "low_active", "active", "very_active"]
Analyte = Literal["potassium", "phosphate", "albumin", "bicarbonate", "uacr", "creatinine", "cystatin_c", "egfr", "a1c"]

# v0.3 guidance and offline outbox (note 06 §4.11, note 02 R5). ``purpose`` in a request: "hypo" (the
# entry treats a low) or "none" (it does not); left out, a food flagged ``hypo_treatment`` defaults to
# "hypo". ``Entry.purpose`` is "hypo" or null.
PurposeIn = Literal["hypo", "none"]
EntryPurpose = Literal["hypo"]
MAX_LOG_BATCH = 40  # POST /api/log/batch items (note 06 §4.10)
_CLIENT_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# int | float keeps integers (mg, mL) as integers in JSON instead of coercing to 422.0.
Number = int | float

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FLAG_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def validate_client_id(value: str | None) -> str | None:
    """An offline-outbox id: a UUID in its 36-character text form (note 02 R5), stored lower-case."""
    if value is None:
        return None
    if not isinstance(value, str) or not _CLIENT_ID_RE.match(value):
        raise ValueError("must be a UUID such as 0f8fad5b-d9cb-469f-a165-70867728950e")
    return value.lower()


def validate_date(value: str) -> str:
    """Accept only ``YYYY-MM-DD`` that is a real calendar date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError("date must be formatted YYYY-MM-DD")
    try:
        _date.fromisoformat(value)
    except ValueError as exc:  # e.g. 2026-02-30
        raise ValueError("date is not a valid calendar date") from exc
    return value


# A date or month "today" may be one day ahead of the server's date (the client's time zone).
FUTURE_TOLERANCE = _timedelta(days=1)
MAX_AGE_YEARS = 120  # note 05 §4.2: birth year within the last 120 years
_BIRTH_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _latest_allowed_date() -> _date:
    return _datetime.now().date() + FUTURE_TOLERANCE


def validate_past_date(value: str) -> str:
    """``YYYY-MM-DD``, a real date, not in the future (one day of time-zone slack) and not before 1900.

    Messages leave out the field name: the validation handler prefixes it (``taken_on: …``).
    """
    validate_date(value)
    day = _date.fromisoformat(value)
    if day > _latest_allowed_date():
        raise ValueError("must not be in the future")
    if day.year < 1900:
        raise ValueError("must be 1900 or later")
    return value


def validate_birth_month(value: str) -> str:
    """``YYYY-MM`` (note 05 §4.2): month 01–12, not in the future, at most 120 years ago."""
    if not isinstance(value, str) or not _BIRTH_MONTH_RE.match(value):
        raise ValueError("must be a year and month formatted YYYY-MM (for example 1971-03)")
    latest = _latest_allowed_date()
    if value > latest.isoformat()[:7]:
        raise ValueError("must not be in the future")
    if int(value[:4]) < latest.year - MAX_AGE_YEARS:
        raise ValueError(f"must be within the last {MAX_AGE_YEARS} years")
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


MAX_INGREDIENTS_CHARS = 4000  # note 03 R3: an ingredient list is capped at 4,000 characters


def validate_gtin(value: str | None) -> str | None:
    """A barcode typed or scanned for a food: 8, 12, 13 or 14 digits (spaces and hyphens ignored) with a
    valid GS1 check digit, stored as a GTIN-14 (note 03 R2). Empty means none."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    from .gtin import GtinError, normalize

    try:
        return normalize(value, "unknown")
    except GtinError as exc:
        raise ValueError(str(exc)) from None


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
    # v0.3 barcodes (note 03 R6, R8): the product's barcode, so the next scan finds this food, and its
    # ingredient list, which the additive scan reads on save.
    gtin: str | None = Field(default=None, max_length=32)
    ingredients_text: str | None = Field(default=None, max_length=MAX_INGREDIENTS_CHARS)

    @field_validator("nutrients")
    @classmethod
    def _nutrients(cls, v: dict[str, Any] | None) -> dict[str, float | None]:
        return validate_nutrients(v)

    @field_validator("flags")
    @classmethod
    def _flags(cls, v: list[str] | None) -> list[str]:
        return validate_flags(v)

    @field_validator("brand", "category", "kidney_notes", "ingredients_text")
    @classmethod
    def _empty_to_none(cls, v: str | None) -> str | None:
        return v or None

    @field_validator("gtin")
    @classmethod
    def _gtin(cls, v: str | None) -> str | None:
        return validate_gtin(v)


class QualityNote(BaseModel):
    """A data-quality note on a food from a provider (note 03 R3): ``code`` and the sentence shown."""

    code: str
    message: str


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
    # v0.3 barcodes (note 03 R6); absent on older clients' expectations, always sent by the server.
    gtin: str | None = None
    source_url: str | None = None
    source_license: str | None = None
    quality: list[QualityNote] = Field(default_factory=list)
    additives: list[str] = Field(default_factory=list)
    ingredients_text: str | None = None


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


BarcodeFormat = Literal["ean_13", "ean_8", "upc_a", "upc_e", "unknown"]


class BarcodeLookup(BaseModel):
    """``POST /api/foods/barcode`` (note 03 R6): the digits only, as the decoder reported them."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    format: BarcodeFormat = "unknown"
    refresh: bool = False


class Attribution(BaseModel):
    text: str
    url: str
    license: str


class BarcodeResult(BaseModel):
    food: Food
    gtin: str
    source: Literal["off", "usda", "local"]
    attribution: Attribution | None = None
    attributions: list[Attribution] = Field(default_factory=list)
    quality: list[QualityNote] = Field(default_factory=list)


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
    purpose: PurposeIn | None = None  # v0.3: left out → "hypo" for a hypo_treatment food
    client_id: str | None = None  # v0.3 offline outbox: a repeat answers 200 with the existing entry

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("client_id")
    @classmethod
    def _client_id(cls, v: str | None) -> str | None:
        return validate_client_id(v)


class LogBatch(BaseModel):
    """``POST /api/log/batch`` (note 06 §4.10): 1–40 entries, each validated exactly as ``POST /api/log``."""

    model_config = ConfigDict(extra="forbid")

    entries: list[LogCreate] = Field(min_length=1, max_length=MAX_LOG_BATCH)

    @model_validator(mode="after")
    def _distinct_client_ids(self) -> "LogBatch":
        seen: dict[str, int] = {}
        for index, entry in enumerate(self.entries):
            if entry.client_id is None:
                continue
            if entry.client_id in seen:
                raise ValueError(f"entries[{index}].client_id repeats entries[{seen[entry.client_id]}].client_id")
            seen[entry.client_id] = index
        return self


class LogUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    date: str | None = None
    meal: Meal | None = None
    servings: float | None = Field(default=None, gt=0, le=MAX_SERVINGS, allow_inf_nan=False)
    grams: float | None = Field(default=None, gt=0, le=MAX_GRAMS, allow_inf_nan=False)
    note: str | None = Field(default=None, max_length=500)
    status: EntryStatus | None = None
    purpose: PurposeIn | None = None  # v0.3: left out or null keeps the stored purpose

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
    purpose: PurposeIn | None = None  # v0.3: left out → "hypo" when ``flags`` has hypo_treatment
    client_id: str | None = None  # v0.3: a repeat answers 200 and creates no second food
    gtin: str | None = Field(default=None, max_length=32)  # v0.3 barcodes: found by this barcode next time
    ingredients_text: str | None = Field(default=None, max_length=MAX_INGREDIENTS_CHARS)  # v0.3: additive scan

    @field_validator("gtin")
    @classmethod
    def _gtin(cls, v: str | None) -> str | None:
        return validate_gtin(v)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("client_id")
    @classmethod
    def _client_id(cls, v: str | None) -> str | None:
        return validate_client_id(v)

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
    purpose: EntryPurpose | None = None  # v0.3: "hypo" = used to treat a low
    client_id: str | None = None  # v0.3: the offline outbox id it was created with
    created_at: str
    updated_at: str


class LogBatchResult(BaseModel):
    """Per-item results of ``POST /api/log/batch`` in request order: ``created`` or ``existing``
    (an earlier request with the same ``client_id`` created it)."""

    entries: list[Entry]
    results: list[dict[str, Any]]


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
    # Entries whose value is unknown (not counted in ``value``; the true total may be higher).
    unknown: int = Field(default=0, ge=0)


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
    # {nutrient: entries without a value}, only nutrients with a count (the totals skip them).
    unknown: dict[str, int] = Field(default_factory=dict)
    planned_unknown: dict[str, int] = Field(default_factory=dict)
    projected_unknown: dict[str, int] = Field(default_factory=dict)
    meal_unknown: dict[str, dict[str, int]] = Field(default_factory=dict)
    planned_meal_unknown: dict[str, dict[str, int]] = Field(default_factory=dict)


class DayTotals(BaseModel):
    date: str
    totals: dict[str, Number | None]
    planned_totals: dict[str, Number | None]
    projected_totals: dict[str, Number | None]
    status: dict[str, NutrientStatus]
    projected_status: dict[str, NutrientStatus]
    counts: Counts
    unknown: dict[str, int] = Field(default_factory=dict)
    planned_unknown: dict[str, int] = Field(default_factory=dict)
    projected_unknown: dict[str, int] = Field(default_factory=dict)


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
    unknown_entries: int = 0  # eaten entries in the period without a value (not in total/average)
    unknown_days: int = 0  # logged days of the period with at least one such entry


class InterdialyticNutrient(BaseModel):
    total: Number
    limit: Number
    fraction: float
    level: StatusLevel
    unknown_entries: int = 0


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
    meal_hint: Meal | None = None  # v0.3 (note 06 §4.11): the slot it is for; left out on PUT keeps it

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
    meal_hint: Meal | None = None  # v0.3
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


PROFILE_V03_FIELDS: tuple[str, ...] = (
    "birth_month", "sex", "activity", "transplant_date", "frail_or_sarcopenic", "weight_6_months_ago_kg",
    "pregnant_or_breastfeeding", "hyperkalemia_history", "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal",
)


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
    # v0.3 "About you" and treatment fields (note 05 §4.2). Empty or null clears a field: back to NULL,
    # or to the default for sex ("unspecified") and the yes/no fields (false).
    birth_month: str | None = None  # 'YYYY-MM'
    sex: Sex | None = None
    activity: Activity | None = None  # null: not chosen (the instance default applies)
    transplant_date: str | None = None  # 'YYYY-MM-DD'
    frail_or_sarcopenic: bool | None = None
    weight_6_months_ago_kg: float | None = Field(default=None, ge=20, le=400, allow_inf_nan=False)
    pregnant_or_breastfeeding: bool | None = None
    hyperkalemia_history: bool | None = None
    urine_output_ml: float | None = Field(default=None, ge=0, le=5000, allow_inf_nan=False)
    pd_uf_ml: float | None = Field(default=None, ge=0, le=4000, allow_inf_nan=False)
    pd_dialysate_kcal: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)

    @field_validator(*PROFILE_V03_FIELDS, mode="before")
    @classmethod
    def _empty_is_null(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("birth_month")
    @classmethod
    def _birth_month(cls, v: str | None) -> str | None:
        return None if v is None else validate_birth_month(v)

    @field_validator("transplant_date")
    @classmethod
    def _transplant_date(cls, v: str | None) -> str | None:
        return None if v is None else validate_past_date(v)

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
    birth_month: str | None = None
    sex: Sex = "unspecified"
    activity: Activity | None = None
    transplant_date: str | None = None
    frail_or_sarcopenic: bool = False
    weight_6_months_ago_kg: Number | None = None
    pregnant_or_breastfeeding: bool = False
    hyperkalemia_history: bool = False
    urine_output_ml: Number | None = None
    pd_uf_ml: Number | None = None
    pd_dialysate_kcal: Number | None = None
    # False until the person picks a value in the Profile form (schema step 8); the stored default
    # (stage 3b, type 1 diabetes) still drives targets and guidance meanwhile.
    ckd_stage_chosen: bool = True
    diabetes_chosen: bool = True
    updated_at: str


# --------------------------------------------------------------------------- #
# Personalised targets and labs (v0.3 M2 targets, note 05 §4.6)
# --------------------------------------------------------------------------- #


class SuggestedRange(BaseModel):
    """A suggested ``{"min", "max"}`` target; a missing bound is left out (fibre is ``{"min": 29}``)."""

    min: int | None = None
    max: int | None = None

    @model_serializer
    def _without_missing_bounds(self) -> dict[str, int]:
        return {k: v for k, v in (("min", self.min), ("max", self.max)) if v is not None}


class AppliedRule(BaseModel):
    """One rule behind the suggestion ("Why this number?"): source, grade and whether part of it is the project's opinion."""

    id: str
    source: str
    grade: str
    opinion: bool
    opinion_note: str | None
    url: str


class SafetyAlert(BaseModel):
    """A lab result that needs action now (potassium of 6.0 mmol/L or more, KDIGO 2024 Table 28)."""

    level: Literal["urgent", "emergency"]
    code: str
    analyte: str
    value: float
    taken_on: str
    message: str


class SuggestedTargets(BaseModel):
    targets: dict[str, int | SuggestedRange | None]
    notes: list[str]
    # v0.3, additive (old clients ignore them): note 05 §4.6.
    rules: list[AppliedRule] = []
    derived: dict[str, Any] = {}
    missing_inputs: list[str] = []
    alerts: list[SafetyAlert] = []


class LabCreate(BaseModel):
    """``POST /api/labs``: one result as typed; converted to the analyte's canonical unit (app/units.py)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    analyte: Analyte
    value: float = Field(ge=0, le=MAX_NUTRIENT_VALUE, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)
    taken_on: str
    note: str = Field(default="", max_length=500)

    @field_validator("taken_on")
    @classmethod
    def _taken_on(cls, v: str) -> str:
        return validate_past_date(v)

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v: Any) -> Any:
        return "" if v is None else v

    @model_validator(mode="after")
    def _convert(self) -> "LabCreate":
        from .units import UnitError, convert

        try:
            convert(self.analyte, self.value, self.unit)
        except UnitError as exc:
            raise ValueError(str(exc)) from None
        return self


class LabResult(BaseModel):
    id: int
    analyte: Analyte
    label: str
    value: Number  # canonical unit, rounded to the analyte's shown decimals
    unit: str  # canonical unit
    entered_value: Number
    entered_unit: str
    display: str  # "1.94 mmol/L = 6.0 mg/dL"
    taken_on: str
    note: str
    created_at: str


class LabCreated(LabResult):
    alerts: list[SafetyAlert]


class LabList(BaseModel):
    labs: list[LabResult]
    # The safety alert of the newest potassium while it counts under targets.lab_fresh_days.potassium,
    # the window the suggestions use, so the Labs banner and Suggest targets agree (v0.3.0 review L3).
    alerts: list[SafetyAlert]


class EgfrResult(BaseModel):
    value: int | None
    method: Literal["lab", "ckd_epi_2021_cr_cys", "ckd_epi_2021_cr", "ckd_epi_2012_cys"]
    method_label: str
    category: str | None  # "G3a", "G3aT" after a transplant; null when the two formulas disagree
    suggested_stage: CkdStage | None
    matches_profile: bool | None
    female: int | None  # both formulas when sex is unspecified
    male: int | None
    taken_on: str


class AlbuminuriaResult(BaseModel):
    value_mg_g: float
    category: Literal["A1", "A2", "A3"]
    label: str
    entered_value: Number
    entered_unit: str
    taken_on: str


class KidneyFunction(BaseModel):
    egfr: EgfrResult | None
    albuminuria: AlbuminuriaResult | None
    profile_stage: CkdStage
    mode: Literal["ckd", "transplant", "hemodialysis", "peritoneal"]
    message: str


# Exported for the routers.
__all__ = [
    "Activity",
    "Alert",
    "AlbuminuriaResult",
    "Analyte",
    "AppliedRule",
    "Attribution",
    "BarcodeLookup",
    "BarcodeResult",
    "Categories",
    "CopyDay",
    "CopyDayResult",
    "Counts",
    "DaySummary",
    "DayTotals",
    "EgfrResult",
    "Entry",
    "FLAGS",
    "Food",
    "FoodCreate",
    "FoodList",
    "Interdialytic",
    "InterdialyticNutrient",
    "KidneyFunction",
    "LabCreate",
    "LabCreated",
    "LabList",
    "LabResult",
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
    "PROFILE_V03_FIELDS",
    "Profile",
    "ProfileUpdate",
    "QualityNote",
    "QuickAdd",
    "Range",
    "RangeSummary",
    "SafetyAlert",
    "Sex",
    "ShoppingItem",
    "ShoppingList",
    "SuggestedRange",
    "SuggestedTargets",
    "UsdaImport",
    "UsdaSearchHit",
    "UsdaSearchResult",
    "Warning",
    "validate_birth_month",
    "validate_date",
    "validate_flags",
    "validate_gtin",
    "validate_nutrients",
    "validate_past_date",
    "validate_targets",
]
