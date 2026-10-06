"""Request and response shapes of ``/api/guidance`` (note 06 §4.10; ARCHITECTURE "M2 API: guidance").

The response models forbid unknown keys, so a field the engine adds without updating this module
(and the contract) fails the API tests instead of reaching clients silently. Numbers follow the app's
display rounding: milligrams and millilitres as integers, grams to one decimal. The log-side models
(``purpose``, ``client_id``, ``LogBatch``) live in :mod:`app.models` next to the other log shapes.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import MAX_SQLITE_INT, Alert, Meal, Number, NutrientStatus, Rating, Warning, validate_date

Group = Literal["protein", "starch", "veg_fruit", "extra"]
Role = Literal["protein", "mixed", "starch", "veg_fruit", "drink", "extra"]
RoomLevel = Literal["ok", "caution", "over"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Shared pieces
# --------------------------------------------------------------------------- #


class HandbookPage(_Out):
    slug: str
    title: str
    url: str


class Reason(_Out):
    code: str
    text: str


class Tip(_Out):
    code: str
    text: str
    handbook: str
    url: str


class LowCard(_Out):
    """The rule-based "Treating a low" card (note 04 G7)."""

    title: str
    lines: list[str]
    handbook: str
    url: str


class NutrientRoom(_Out):
    room: Number
    cap: Number | None  # null for fluid (no per-meal cap)
    share: Number
    in_meal: Number
    remaining_today: Number
    allowance_today: Number
    level: RoomLevel
    basis: Literal["day", "week_average", "interdialytic"]


class CarbRoom(_Out):
    goal: Number
    in_meal: Number
    gap: Number
    tolerance: Number
    hypo_excluded_g: Number


class ProteinRoom(_Out):
    aim: Number
    aim_min: Number


class GuidanceRoom(_Out):
    """The room left for one meal (§4.4); a nutrient without a numeric target is ``null``."""

    potassium_mg: NutrientRoom | None
    phosphorus_mg: NutrientRoom | None
    sodium_mg: NutrientRoom | None
    fluid_ml: NutrientRoom | None
    carbs_g: CarbRoom | None
    protein_g: ProteinRoom | None


class FoodPortion(_Out):
    """One food at one portion with its numbers, warnings and renal rating."""

    food_id: int
    name: str
    group: Group
    role: Role
    servings: Number
    serving_desc: str
    grams: Number
    portion_text: str
    nutrients: dict[str, Number | None]
    warnings: list[Warning]
    renal_rating: Rating


class TargetsUsed(_Out):
    """Which targets the result compared with (note 06 R10), as the Today screen shows them."""

    values: dict[str, Any]
    profile_updated_at: str | None


class AiStatus(_Out):
    available: bool
    provider_label: str | None


class GuidanceUnavailable(_Out):
    """``status`` ``no_targets`` (no numeric potassium, phosphorus or sodium target and no meal carb
    goal) or ``disabled`` (switched off on the server or in the person's settings)."""

    status: Literal["no_targets", "disabled"]
    rules_version: str
    message: str


# --------------------------------------------------------------------------- #
# GET /api/guidance/next-meal
# --------------------------------------------------------------------------- #


class GuidanceFood(FoodPortion):
    score: float
    fit_text: str
    reasons: list[Reason]
    handbook: list[HandbookPage]
    explain: dict[str, Any] | None = None


class OptionItem(_Out):
    food_id: int
    name: str
    servings: Number


class FamiliarMeal(_Out):
    """A saved meal (``template_id``), a usual meal mined from the log, or a starter combo."""

    template_id: int | None
    name: str
    source: Literal["saved", "usual", "starter"]
    scale: Number
    score: float
    items: list[OptionItem]
    totals: dict[str, Number | None]
    note: str


class NextMealResponse(_Out):
    status: Literal["ok"]
    rules_version: str
    date: str
    meal: Meal
    open_meals: list[Meal]
    room: GuidanceRoom
    room_text: str
    meal_has: dict[str, bool]
    foods: list[GuidanceFood]
    saved_meals: list[FamiliarMeal]
    tips: list[Tip]
    notes: list[str]
    ai: AiStatus
    targets: TargetsUsed
    explain: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# GET /api/guidance/swaps, /hypo-options
# --------------------------------------------------------------------------- #


class SwapFood(_Out):
    food_id: int
    name: str
    servings: Number
    serving_desc: str
    nutrients: dict[str, Number | None]


class Trigger(_Out):
    nutrient: str
    reasons: list[str]
    value: Number | None
    room: Number | None


class SwapIdea(FoodPortion):
    same_category: bool
    fits_meal: bool
    score: float
    deltas: dict[str, Number | None]
    text: str


class PortionOption(_Out):
    servings: Number
    fraction: Number
    fits_meal: bool
    nutrients: dict[str, Number | None]
    text: str


class SwapResponse(_Out):
    status: Literal["ok"]
    rules_version: str
    date: str
    meal: Meal
    mode: Literal["normal", "hypo", "avoid"]
    food: SwapFood
    triggers: list[Trigger]
    match: Literal["carbs", "protein", "serving"] | None
    swaps: list[SwapIdea]
    portion_option: PortionOption | None
    tips: list[Tip]
    widened: bool
    notes: list[str]
    reason: Literal["no_warning", "no_swap_found"] | None = None
    card: LowCard | None = None
    entry_id: int | None = None
    explain: dict[str, Any] | None = None


class HypoOption(FoodPortion):
    text: str


class HypoOptionsResponse(_Out):
    status: Literal["ok"]
    rules_version: str
    dose_g: Number
    options: list[HypoOption]
    card: LowCard
    notes: list[str]


# --------------------------------------------------------------------------- #
# POST /api/guidance/plan-day
# --------------------------------------------------------------------------- #


class PlanDayRequest(BaseModel):
    """Computes only; nothing is written ("Use this plan" sends ``apply.entries`` to ``/api/log/batch``)."""

    model_config = ConfigDict(extra="forbid")

    date: str
    meals: list[Meal] | None = Field(default=None, min_length=1, max_length=4)
    use_saved_meals: bool = True
    use_usual: bool = True
    use_starters: bool = True
    variant: int = Field(default=0, ge=0, le=4)
    explain: bool = False

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("meals")
    @classmethod
    def _unique(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("each meal may be listed once")
        return v


class Closest(_Out):
    scale: Number
    items: list[FoodPortion]
    totals: dict[str, Number | None]
    reason: str | None


class ApplySaved(_Out):
    endpoint: str
    body: dict[str, Any]


class PlanMeal(_Out):
    meal: Meal
    status: Literal["ok", "partial", "no_fit"]
    source: Literal["saved", "usual", "starter", "built"] | None
    name: str | None
    template_id: int | None
    scale: Number
    score: float | None
    items: list[FoodPortion]
    totals: dict[str, Number | None] | None
    why: list[str]
    room: GuidanceRoom
    reason: str | None
    message: str | None = None
    closest: Closest | None = None
    apply_saved: ApplySaved | None = None


class DayAfter(_Out):
    projected_totals: dict[str, Number | None]
    projected_status: dict[str, NutrientStatus]
    new_alerts: list[Alert]


class EnergyNote(_Out):
    kcal: Number
    goal: Number
    text: str
    foods: list[FoodPortion]
    handbook: str


class ApplyEntry(_Out):
    date: str
    meal: Meal
    food_id: int = Field(ge=1, le=MAX_SQLITE_INT)
    servings: Number
    status: Literal["planned"]
    purpose: Literal["none"]


class ApplyBlock(_Out):
    endpoint: str
    entries: list[ApplyEntry]


class PlanDayResponse(_Out):
    status: Literal["ok"]
    rules_version: str
    date: str
    variant: int
    meals: list[PlanMeal]
    protein_topup: list[Meal]
    day_after: DayAfter
    energy_note: EnergyNote | None
    apply: ApplyBlock
    notes: list[str]
    targets: TargetsUsed
    explain: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Insights
# --------------------------------------------------------------------------- #


class InsightSource(_Out):
    name: str
    short_name: str
    value: Number
    share_pct: int


class Insight(_Out):
    id: str
    severity: Literal["warning", "attention", "info", "good"]
    nutrient: str | None
    message: str
    numbers: dict[str, Any]
    sources: list[InsightSource]
    handbook: list[HandbookPage]


class DayInsightsResponse(_Out):
    status: Literal["ok"]
    rules_version: str
    date: str
    insights: list[Insight]
    planned_excluded: int
    notes: list[str]


class PeriodInsightsResponse(_Out):
    status: Literal["ok"]
    rules_version: str
    start: str
    end: str
    days: int
    logged_days: int
    insights: list[Insight]
    notes: list[str]
    previous: dict[str, str]


# --------------------------------------------------------------------------- #
# Rules and "Not for me"
# --------------------------------------------------------------------------- #


class RulesResponse(_Out):
    rules_version: str
    rules_hash: str
    rules: dict[str, Any]
    notes: dict[str, str]
    topic_pages: dict[str, HandbookPage]
    tips: list[dict[str, str]]


class NotForMeFood(_Out):
    food_id: int
    name: str
    category: str | None
    created_at: str


class NotForMeList(_Out):
    rules_version: str
    foods: list[NotForMeFood]
    limit: int
