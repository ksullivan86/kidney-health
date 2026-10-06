"""Wire schemas (sent to the model as a hint) and the Pydantic models that judge the answers
(note 04 R8 and §9 A2; note 03 R8, R9). Pure.

The wire schemas use only keywords in OpenAI's strict subset (F5): ``type``, ``enum``, ``required``,
``additionalProperties: false``, ``minItems``/``maxItems`` and integer ``minimum``/``maximum``; the
root is an object and every property is required. They are a hint: backends differ in what they
enforce, so every answer is checked again here with ``extra="forbid"`` models and bounds, and then
by the rules (:mod:`app.ai.guard`).

**No free text reaches a patient from the meal features (§9 A2).** An idea carries a ``theme`` and
``reason_codes`` from fixed enums; the server writes the sentence a person reads. Candidate food ids,
refs, handbook slugs and meal slots are enums built per request, so a constrained backend cannot
name anything outside the server's list (F5). The photo and describe-a-meal features must return
food names and copied label text; those strings are cleaned, capped and filtered by the guard.
"""
from __future__ import annotations

import math
from typing import Annotated, Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..nutrients import NUTRIENT_KEYS

THEMES: tuple[str, ...] = ("light", "hearty", "familiar", "new_idea")
REASON_CODES: tuple[str, ...] = (
    "low_potassium", "low_phosphorus", "low_sodium", "fits_carb_goal", "adds_protein", "adds_missing_group", "you_eat_often",
)
MEAL_SLOTS: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")
UNITS: tuple[str, ...] = ("serving", "g", "ml", "cup", "tbsp", "tsp", "slice", "piece", "oz", "fl_oz", "none")
LABEL_NUTRIENTS: tuple[str, ...] = tuple(k for k in NUTRIENT_KEYS if k != "fluid_ml")  # the 11 printed on a label
PERCENT_DV_KEYS: tuple[str, ...] = ("sodium", "potassium", "phosphorus", "calcium")

MAX_IDEAS = 3
MAX_ITEMS = 5
MAX_RERANK = 12
MAX_SWAP_PICKS = 3
MAX_PARSE_ITEMS = 8
MAX_PLATE_ITEMS = 8
MAX_NAME_CHARS = 80
MAX_TEXT_CHARS = 300
MAX_HANDBOOK = 2

Status = Literal["ok", "refused"]
Refusal = Literal["none", "outside_scope", "no_fit"]


def _str() -> dict[str, Any]:
    return {"type": "string"}


def _nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


def _enum_or_empty(values: Sequence[Any], kind: str) -> dict[str, Any]:
    return {"type": kind, "enum": list(values)} if values else {"type": kind}


def _array(items: Mapping[str, Any], *, lo: int = 0, hi: int) -> dict[str, Any]:
    return {"type": "array", "minItems": lo, "maxItems": hi, "items": dict(items)}


def _object(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": dict(properties)}


def _handbook(slugs: Sequence[str]) -> dict[str, Any]:
    if not slugs:
        return {"type": "array", "maxItems": 0, "items": {"type": "string"}}
    return _array({"type": "string", "enum": list(slugs)}, hi=MAX_HANDBOOK)


def _reasons() -> dict[str, Any]:
    return _array({"type": "string", "enum": list(REASON_CODES)}, lo=1, hi=3)


def _head(extra: Mapping[str, Any]) -> dict[str, Any]:
    return _object({
        "status": {"type": "string", "enum": ["ok", "refused"]},
        "refusal": {"type": "string", "enum": ["none", "outside_scope", "no_fit"]},
        **extra,
    })


# --------------------------------------------------------------------------- #
# Wire schemas (dict builders)
# --------------------------------------------------------------------------- #


def ideas_schema(candidate_ids: Sequence[int], slugs: Sequence[str]) -> dict[str, Any]:
    """``next_meal`` mode ``ideas`` (R8 with §9 A2: ``theme`` and ``reason_codes`` instead of title and why)."""
    item = _object({
        "food_id": {"type": "integer", "enum": list(candidate_ids)} if candidate_ids else {"type": "integer"},
        "quarters": {"type": "integer", "minimum": 1, "maximum": 12},
    })
    idea = _object({
        "theme": {"type": "string", "enum": list(THEMES)},
        "items": _array(item, lo=1, hi=MAX_ITEMS),
        "reason_codes": _reasons(),
        "handbook": _handbook(slugs),
    })
    return _head({"ideas": _array(idea, hi=MAX_IDEAS)})


def rerank_schema(refs: Sequence[str]) -> dict[str, Any]:
    entry = _object({"ref": _enum_or_empty(refs, "string"), "reason_codes": _reasons()})
    return _head({"order": _array(entry, hi=MAX_RERANK)})


def swap_schema(refs: Sequence[str]) -> dict[str, Any]:
    entry = _object({"ref": _enum_or_empty(refs, "string"), "reason_codes": _reasons()})
    return _head({"pick": _array(entry, hi=MAX_SWAP_PICKS)})


def plan_schema(slots: Sequence[str], max_index: int) -> dict[str, Any]:
    entry = _object({
        "meal": _enum_or_empty(slots, "string"),
        "index": {"type": "integer", "minimum": 0, "maximum": max(0, max_index)},
        "reason_codes": _reasons(),
    })
    return _head({"picks": _array(entry, hi=len(MEAL_SLOTS))})


def parse_meal_schema() -> dict[str, Any]:
    item = _object({
        "text": _str(),
        "search": _str(),
        "amount": _nullable("number"),
        "unit": {"type": "string", "enum": list(UNITS)},
    })
    return _object({"status": {"type": "string", "enum": ["ok", "refused"]}, "items": _array(item, hi=MAX_PARSE_ITEMS)})


def read_label_schema() -> dict[str, Any]:
    """Note 03 R8 merged with note 04 R8: printed values only, ``null`` when not printed."""
    return _object({
        "status": {"type": "string", "enum": ["ok", "not_a_label", "unreadable"]},
        "product_name": _nullable("string"),
        "serving_text": _nullable("string"),
        "serving_g": _nullable("number"),
        "basis": {"type": "string", "enum": ["per_serving", "per_100g", "per_100ml"]},
        "per_serving": _object({k: _nullable("number") for k in LABEL_NUTRIENTS}),
        "salt_g": _nullable("number"),
        "percent_dv": _object({k: _nullable("number") for k in PERCENT_DV_KEYS}),
        "ingredients_text": _nullable("string"),
        "label_style": {"type": "string", "enum": ["us_nutrition_facts", "eu_nutrition_declaration", "other"]},
    })


def plate_schema() -> dict[str, Any]:
    """Note 03 R9 (names and a gram estimate; never nutrients) with note 04's ``search`` term."""
    item = _object({
        "name": _str(),
        "search": _str(),
        "grams_estimate": _nullable("number"),
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    })
    return _object({"status": {"type": "string", "enum": ["ok", "no_food", "unsure"]}, "items": _array(item, hi=MAX_PLATE_ITEMS)})


# --------------------------------------------------------------------------- #
# Answer models (V2: types, enums and counts; text policy is per field, in the guard)
# --------------------------------------------------------------------------- #

_FORBID = ConfigDict(extra="forbid", strict=False)
Quarter = Annotated[int, Field(ge=1, le=12, strict=True)]
FoodId = Annotated[int, Field(ge=1, le=2**63 - 1, strict=True)]
Code = Literal["low_potassium", "low_phosphorus", "low_sodium", "fits_carb_goal", "adds_protein", "adds_missing_group", "you_eat_often"]
ShortText = Annotated[str, StringConstraints(max_length=MAX_TEXT_CHARS)]
Number = Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)]


class IdeaItem(BaseModel):
    model_config = _FORBID
    food_id: FoodId
    quarters: Quarter


class Idea(BaseModel):
    model_config = _FORBID
    theme: Literal["light", "hearty", "familiar", "new_idea"]
    items: Annotated[list[IdeaItem], Field(min_length=1, max_length=MAX_ITEMS)]
    reason_codes: Annotated[list[Code], Field(min_length=1, max_length=3)]
    handbook: Annotated[list[str], Field(max_length=MAX_HANDBOOK)] = []


class IdeasAnswer(BaseModel):
    """V2 counts are one more than the schema allows so the guard can drop the extra with a reason (V3)."""

    model_config = _FORBID
    status: Status
    refusal: Refusal
    ideas: Annotated[list[dict[str, Any]], Field(max_length=10)]


class RefPick(BaseModel):
    model_config = _FORBID
    ref: Annotated[str, StringConstraints(max_length=8)]
    reason_codes: Annotated[list[Code], Field(min_length=1, max_length=3)]


class RerankAnswer(BaseModel):
    model_config = _FORBID
    status: Status
    refusal: Refusal
    order: Annotated[list[RefPick], Field(max_length=40)]


class SwapAnswer(BaseModel):
    model_config = _FORBID
    status: Status
    refusal: Refusal
    pick: Annotated[list[RefPick], Field(max_length=15)]


class PlanPick(BaseModel):
    model_config = _FORBID
    meal: Literal["breakfast", "lunch", "dinner", "snack"]
    index: Annotated[int, Field(ge=0, le=20, strict=True)]
    reason_codes: Annotated[list[Code], Field(min_length=1, max_length=3)]


class PlanAnswer(BaseModel):
    model_config = _FORBID
    status: Status
    refusal: Refusal
    picks: Annotated[list[PlanPick], Field(max_length=4)]


class ParsedItem(BaseModel):
    model_config = _FORBID
    text: ShortText
    search: ShortText
    amount: Number | None
    unit: Literal["serving", "g", "ml", "cup", "tbsp", "tsp", "slice", "piece", "oz", "fl_oz", "none"]


class ParseMealAnswer(BaseModel):
    model_config = _FORBID
    status: Status
    items: Annotated[list[ParsedItem], Field(max_length=MAX_PARSE_ITEMS)]


def _finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("must be a finite number")
    return value


class LabelPerServing(BaseModel):
    model_config = _FORBID
    calories_kcal: Number | None
    protein_g: Number | None
    fat_g: Number | None
    sat_fat_g: Number | None
    carbs_g: Number | None
    fiber_g: Number | None
    sugar_g: Number | None
    sodium_mg: Number | None
    potassium_mg: Number | None
    phosphorus_mg: Number | None
    calcium_mg: Number | None


class LabelPercentDv(BaseModel):
    model_config = _FORBID
    sodium: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None
    potassium: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None
    phosphorus: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None
    calcium: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None


class LabelAnswer(BaseModel):
    model_config = _FORBID
    status: Literal["ok", "not_a_label", "unreadable"]
    product_name: Annotated[str, StringConstraints(max_length=400)] | None
    serving_text: Annotated[str, StringConstraints(max_length=200)] | None
    serving_g: Annotated[float, Field(gt=0, le=100_000, allow_inf_nan=False)] | None
    basis: Literal["per_serving", "per_100g", "per_100ml"]
    per_serving: LabelPerServing
    salt_g: Number | None
    percent_dv: LabelPercentDv
    ingredients_text: Annotated[str, StringConstraints(max_length=8000)] | None
    label_style: Literal["us_nutrition_facts", "eu_nutrition_declaration", "other"]


class PlateItem(BaseModel):
    model_config = _FORBID
    name: ShortText
    search: ShortText
    grams_estimate: Annotated[float, Field(ge=0, le=5000, allow_inf_nan=False)] | None
    confidence: Literal["low", "medium", "high"]


class PlateAnswer(BaseModel):
    model_config = _FORBID
    status: Literal["ok", "no_food", "unsure"]
    items: Annotated[list[PlateItem], Field(max_length=MAX_PLATE_ITEMS)]

    @field_validator("items")
    @classmethod
    def _cap(cls, value: list[PlateItem]) -> list[PlateItem]:
        return value


def model_validator_for(model: type[BaseModel]):
    """A validator for :meth:`app.ai.client.ChatClient.complete_json`."""

    def validate(data: Any) -> BaseModel:
        return model.model_validate(data)

    return validate


def enum_values(values: Iterable[Any]) -> list[Any]:
    return list(dict.fromkeys(values))
