"""Import of a person's own ``export.json`` into their account on this server (note 07 §4.14, ROADMAP).

``POST /api/me/import`` (cookie session + CSRF like every ``/api/me`` route; the password entered within
``REAUTH_MINUTES``, :data:`~app.auth.deps.RecentUser`; the signed-in person only) takes the exact JSON file that
``GET /api/me/export.zip`` wrote (:mod:`app.account`) as the request body. Two calls with the same body:

* ``?dry_run=1``: everything is checked and counted, nothing is kept (the work runs inside the transaction that is
  then rolled back, so the answer is exactly what the real import would do);
* without it: the same, then written, **all or nothing** in one transaction.

The file is untrusted input (it may have been edited, or made up to look like an export):

* **Strict shape.** Every record kind has a pydantic model with ``extra="forbid"``, strict types, bounded lists
  and strings, and the API's own limits and validators (:mod:`app.models`), so an imported record is never one the
  normal API would refuse. NaN, Infinity and numbers too large for a float are refused while the JSON is read. The
  first problem refuses the whole file with a message that names the record kind and its position (``log_entries[17]
  .date: ...``) and never repeats a value back. Only ``format`` ``kidney-health-export`` version 1 is read.
* **Never imported, even when present:** the ``user`` section, passwords and sessions, assistant tokens, AI keys,
  providers, consents and usage, the AI and sign-in activity records, other people's data, instance settings,
  personal settings that are consents (``food.off_consent``, ``ai``). Those sections are accepted but never read.
  Any other top-level key is refused.
* **Ids are remapped.** Own foods get new ids (an identical own food is reused instead, so importing twice is
  harmless); a built-in food is found by its FoodData Central id (older files: by id and name); a shared USDA or
  Open Food Facts food is linked when this server has the same shared row and otherwise kept as the person's own
  copy (the file carries the record) or reported as skipped. Entries, saved meals and "Not for me" items point at
  the new ids; one whose food is neither in the file nor built in is skipped and listed, never guessed.
  An entry's nutrient numbers are recomputed from its food and servings, as every entry is, never taken from the
  file.
* **Duplicates.** An account that already has entries, own foods, saved meals, lab results, symptoms, weights or blood
  pressure readings is refused (409) unless the person chose ``merge=1`` ("Add to my existing data"); then whatever is
  already here is left out (:data:`RULE`), so importing the same file again adds nothing. A weight or reading that carries a
  ``source_key`` (it came from an import) is left out when the person has that key; one without a key (typed by the person)
  is left out when an identical one is here.
* The person's profile, targets and settings are replaced only with ``replace_profile=1``: they are clinical
  settings the person may have agreed with their care team on this server.

One ``data.imported`` audit row records the counts (no content). The request body limit for this one path is
``MAX_IMPORT_BYTES`` (16 MiB: a pretty-printed year at eight entries a day is about 3.5 MB).
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Iterable, Literal, Mapping

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from . import foods as foods_module
from . import settings_registry, units
from .audit import audit
from .auth.context import auth_context, request_ip
from .auth.deps import RecentUser, current_user
from .auth.errors import ApiProblem, busy
from .brand import EXPORT_FORMAT, NAME as PRODUCT_NAME  # the names, not the module: ``brand`` is a food's field here
from .db import get_db, utcnow
from .foods import Provenance, link_food, scan_custom_food, stored_food_values
from .guidance.context import MAX_FOOD_PREFERENCES, MAX_NOT_FOR_ME, PREFERENCE_NOT_FOR_ME
from .body import round_kg
from .log import insert_entry
from .meals import insert_template, parse_items
from .models import (
    MAX_GRAMS,
    MAX_INGREDIENTS_CHARS,
    MAX_NUTRIENT_VALUE,
    MAX_RECIPE_SERVINGS,
    MAX_RECIPE_STEP_CHARS,
    MAX_RECIPE_STEPS,
    SOURCE_URL_MAX,
    check_source_url,
    MAX_SERVING_G,
    MAX_SERVINGS,
    MAX_SQLITE_INT,
    MAX_BODY_NOTE,
    MAX_READINGS_PER_DAY,
    MAX_SOURCE_KEY,
    MAX_SYMPTOM_LABEL,
    MAX_SYMPTOM_NOTE,
    MAX_SYMPTOMS_PER_DAY,
    MAX_WEIGHTS_PER_DAY,
    MIN_SERVING_G,
    Analyte,
    BloodPressureContext,
    BloodPressureCreate,
    BodySourceKey,
    EntryStatus,
    LabCreate,
    Meal,
    ProfileUpdate,
    SymptomCreate,
    SymptomKey,
    WeightContext,
    WeightCreate,
    validate_client_id,
    validate_date,
    validate_flags,
    validate_gtin,
    validate_nutrients,
)
from .nutrients import NUTRIENT_KEYS
from .profile import apply_profile_changes, get_profile
from .security import register_body_limit
from .settings_store import SettingLocked, SettingNotEditable, SettingsUnavailable

register_body_limit("/api/me/import", "max_import_bytes")

router = APIRouter(prefix="/api/me/import", tags=["me"], dependencies=[Depends(current_user)])

SUPPORTED_VERSION = 1

# Bounds on the lists of a file. The body limit (MAX_IMPORT_BYTES) is the first fence; these keep the work and the
# memory of one request proportional too. "Not for me" is the app's own limit.
MAX_ENTRIES = 30_000
MAX_CUSTOM_FOODS = 5_000
MAX_LINKED_FOODS = 5_000
MAX_BUILTIN_REFS = 5_000
MAX_MEALS = 1_000
MAX_MEAL_ITEMS = 100
MAX_LABS = 5_000
MAX_SYMPTOMS = 20_000
MAX_WEIGHTS = 20_000
MAX_BLOOD_PRESSURES = 20_000
MAX_SETTINGS = 200
MAX_SKIPPED_SHOWN = 100  # skipped items listed in the answer; the total is always given
MAX_MESSAGE_CHARS = 200
MAX_NOTE_CHARS = 1000  # a saved meal's note, as MealTemplateCreate allows

# Personal settings carried over with "replace my profile and targets": the meal-guidance preferences (carb tolerance
# and the grams the person takes for a low come from their diabetes team), three display preferences and the weight log's
# three (the unit, and the weight-gain alarm and blood pressure goal the person's care team gave them). Consents
# (Open Food Facts barcodes, AI) are never carried over: they are agreed again where they take effect.
IMPORTED_SETTINGS: tuple[str, ...] = ("guidance", "ui.theme", "user.units.labs", "food.scan_prefer_camera", "user.units.weight",
                                      "body.weight_alarm", "body.bp_goal")

# Sections the export writes that belong to the server, not to the person's records: accepted, never read.
SKIPPED_SECTIONS: tuple[str, ...] = ("user", "ai_audit", "activity", "ai_usage", "ai_consents", "ai_provider", "activity_days",
                                     "activity_workouts", "activity_extra")

NOT_IMPORTED: tuple[str, ...] = (
    "Your username, password and sign-in sessions",
    "Assistant access tokens and any API keys (an export never holds them; a file that does is ignored)",
    "AI activity, AI usage counts, the AI providers you agreed to send data to, and an AI provider of your own "
    "(agree to those again on this server)",
    "Your sign-in activity list",
    "Your Open Food Facts barcode choice and your AI ideas choice (they are consents; choose them again here)",
    "Your days and workouts from Whoop and your active-day calorie setting (connect Whoop again here)",
)

RULE = (
    "Your file's foods, log entries, saved meals, lab results, symptoms, weights, blood pressure readings and food "
    "preferences are added to this account. If the account already has entries, foods of your own, saved meals, lab "
    "results, symptoms, weights or blood pressure readings, nothing is "
    "imported unless you choose \"Add to my existing data\". Then whatever is already here is left out: an entry with "
    "the same date, meal, food, amount, status and time; a food of yours with the same name, serving and values; a "
    "saved meal with the same name and foods; a lab result with the same test, date and value; a symptom with the same "
    "date, name, severity and note; a weight or blood pressure reading that came from an import and has the same key, or "
    "one you typed with the same date, time, numbers, circumstances and note. So importing the same file again adds nothing. Your profile, targets and settings are replaced only if you choose \"Also replace my profile, targets "
    "and settings\"."
)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_OFF_PAGE_RE = re.compile(r"^https://world\.openfoodfacts\.org/product/\d{8,14}$")
_LICENSES = frozenset({"ODbL-1.0", "CC0-1.0", "CC0-1.0 AND ODbL-1.0"})
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


# --------------------------------------------------------------------------- #
# Reading the file
# --------------------------------------------------------------------------- #


class ImportRefused(Exception):
    """The file is not one this server imports. ``kind`` and ``index`` name the record when there is one."""

    def __init__(self, message: str, *, kind: str | None = None, index: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.index = index


class NotFinite(ValueError):
    """The JSON holds NaN, Infinity or a number beyond what a float can hold."""


def _refuse_constant(name: str) -> Any:
    raise NotFinite(name)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise NotFinite(text)
    return value


def short(text: Any, limit: int = 60) -> str:
    """A value from the file made safe to show: control characters out, cut at ``limit``."""
    clean = _CTRL_RE.sub(" ", str(text)).strip()
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def parse_timestamp(value: str) -> str:
    """``2026-10-05T12:30:00.123456Z`` (seconds and fraction optional), from 2000 to one day ahead; returned in the
    fixed form the database uses, so timestamps sort and compare as text."""
    if not isinstance(value, str) or not _TS_RE.match(value):
        raise ValueError("must be a UTC time such as 2026-10-05T12:30:00.123456Z")
    try:
        moment = datetime.strptime(value.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z" if "." in value else "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        raise ValueError("is not a valid time") from None
    if moment.year < 2000 or moment > datetime.now(timezone.utc) + timedelta(days=1):
        raise ValueError("must be between the year 2000 and tomorrow")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _source_url(value: str | None) -> str | None:
    """Attribution addresses the server itself writes: an Open Food Facts product page or the FoodData Central home."""
    if value is None:
        return None
    if value == foods_module.USDA_HOME_URL or _OFF_PAGE_RE.match(value):
        return value
    raise ValueError("must be an Open Food Facts product page or the FoodData Central address")


def _source_license(value: str | None) -> str | None:
    if value is None:
        return None
    if value in _LICENSES:
        return value
    raise ValueError("is not a licence this app writes")


Timestamp = Annotated[str, Field(max_length=40)]
Id = Annotated[int, Field(ge=1, le=MAX_SQLITE_INT)]
# A built-in food the app curates itself (glucose tablets, gel and shots, the salt substitutes: ``data/foods.json``) carries a
# negative number of its own where a FoodData Central food has its id, and a copy of one keeps it. An export holds those, so the
# import must read them (a made-up number simply matches no food here).
FdcId = Annotated[int, Field(ge=-MAX_SQLITE_INT, le=MAX_SQLITE_INT)]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Rating = Literal["green", "yellow", "red"]


def _short(n: int, *, min_length: int = 0) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=n)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImportWarning(_Strict):
    """A warning the server worked out when it wrote the file. Checked for shape, never used."""

    nutrient: _short(40) | None = None
    level: Literal["medium", "high"]
    value: Finite | None = None
    flag: _short(40) | None = None
    message: _short(1500)


class ImportQuality(_Strict):
    code: _short(80)
    message: _short(400)


class ImportFood(_Strict):
    """A food as ``GET /api/foods/{id}`` shows it (``custom_foods`` items and the ``food`` of a linked food)."""

    id: Id
    name: _short(200, min_length=1)
    brand: _short(200) | None = None
    category: _short(100) | None = None
    source: Literal["custom", "usda", "off"]
    fdc_id: FdcId | None = None
    serving_desc: _short(200, min_length=1)
    serving_g: Annotated[float, Field(ge=MIN_SERVING_G, le=MAX_SERVING_G, allow_inf_nan=False)]
    nutrients: dict[str, Any]
    flags: Annotated[list[str], Field(max_length=60)]
    kidney_notes: _short(1000) | None = None
    hidden: bool
    warnings: Annotated[list[ImportWarning], Field(max_length=40)]
    kidney_rating: Rating
    gtin: Annotated[str, Field(max_length=32)] | None = None
    source_url: Annotated[str, Field(max_length=200)] | None = None
    source_license: Annotated[str, Field(max_length=40)] | None = None
    quality: Annotated[list[ImportQuality], Field(max_length=30)]
    additives: Annotated[list[_short(40)], Field(max_length=40)]
    ingredients_text: _short(MAX_INGREDIENTS_CHARS) | None = None

    @field_validator("nutrients")
    @classmethod
    def _nutrients(cls, v: dict[str, Any]) -> dict[str, float | None]:
        return checked_nutrients(v)

    @field_validator("flags")
    @classmethod
    def _flags(cls, v: list[str]) -> list[str]:
        return validate_flags(v)

    @field_validator("gtin")
    @classmethod
    def _gtin(cls, v: str | None) -> str | None:
        return validate_gtin(v)

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _source_url(v)

    @field_validator("source_license")
    @classmethod
    def _license(cls, v: str | None) -> str | None:
        return _source_license(v)


class ImportLinkedFood(_Strict):
    """A shared food the person imported or scanned. ``food`` is missing in files from before import existed."""

    id: Id
    name: _short(200)
    source: Literal["usda", "off"]
    fdc_id: Id | None = None
    linked_at: Timestamp | None = None
    gtin: Annotated[str, Field(max_length=32)] | None = None
    food: ImportFood | None = None

    @field_validator("gtin")
    @classmethod
    def _gtin(cls, v: str | None) -> str | None:
        return validate_gtin(v)

    @field_validator("linked_at")
    @classmethod
    def _linked_at(cls, v: str | None) -> str | None:
        return None if v is None else parse_timestamp(v)

    @model_validator(mode="after")
    def _same_food(self) -> "ImportLinkedFood":
        f = self.food
        if f is not None and (f.id != self.id or f.source != self.source):
            raise ValueError("food does not describe this food (id or source differ)")
        return self


class ImportBuiltinRef(_Strict):
    id: Id
    name: _short(200, min_length=1)
    fdc_id: FdcId | None = None


class ImportEntry(_Strict):
    id: Id
    date: str
    meal: Meal
    food_id: Id
    food_name: _short(200, min_length=1)
    servings: Annotated[float, Field(gt=0, le=MAX_SERVINGS, allow_inf_nan=False)]
    grams: Annotated[float, Field(gt=0, le=MAX_GRAMS, allow_inf_nan=False)] | None = None
    note: _short(500) | None = None
    status: EntryStatus
    nutrients: dict[str, Any]
    warnings: Annotated[list[ImportWarning], Field(max_length=40)]
    kidney_rating: Rating
    purpose: Literal["hypo"] | None = None
    client_id: str | None = None
    created_at: Timestamp
    updated_at: Timestamp
    # The export leaves it out (it is worked out from the content); an entry copied from GET /api/log carries it. Never used.
    version: _short(64) | None = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return validate_date(v)

    @field_validator("nutrients")
    @classmethod
    def _nutrients(cls, v: dict[str, Any]) -> dict[str, float | None]:
        return checked_nutrients(v)

    @field_validator("client_id")
    @classmethod
    def _client_id(cls, v: str | None) -> str | None:
        return validate_client_id(v)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _time(cls, v: str) -> str:
        return parse_timestamp(v)


class ImportMealItem(_Strict):
    food_id: Id
    food_name: _short(200)
    servings: Annotated[float, Field(gt=0, le=MAX_SERVINGS, allow_inf_nan=False)]
    serving_desc: _short(200)
    nutrients: dict[str, Any]
    kidney_rating: Rating
    hidden: bool

    @field_validator("nutrients")
    @classmethod
    def _nutrients(cls, v: dict[str, Any]) -> dict[str, float | None]:
        return checked_nutrients(v)


class ImportMeal(_Strict):
    id: Id
    name: _short(200, min_length=1)
    note: _short(1000) | None = None
    meal_hint: Meal | None = None
    items: Annotated[list[ImportMealItem], Field(max_length=MAX_MEAL_ITEMS)]
    totals: dict[str, Any]
    kidney_rating: Rating
    # A recipe (schema step 21); an export from before it has none of these. per_serving and unknown are worked out again.
    servings_made: Annotated[float, Field(gt=0, le=MAX_RECIPE_SERVINGS, allow_inf_nan=False)] | None = None
    steps: Annotated[list[_short(MAX_RECIPE_STEP_CHARS, min_length=1)], Field(max_length=MAX_RECIPE_STEPS)] | None = None
    source_url: _short(SOURCE_URL_MAX, min_length=1) | None = None
    per_serving: dict[str, Any] | None = None
    unknown: dict[str, Any] | None = None
    created_at: Timestamp
    updated_at: Timestamp

    check_url = field_validator("source_url")(check_source_url)

    @field_validator("totals")
    @classmethod
    def _totals(cls, v: dict[str, Any]) -> dict[str, float | None]:
        return checked_nutrients(v)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _time(cls, v: str) -> str:
        return parse_timestamp(v)


class ImportLab(_Strict):
    id: Id
    analyte: Analyte
    value: Annotated[float, Field(ge=0, le=MAX_NUTRIENT_VALUE, allow_inf_nan=False)]
    unit: _short(40)
    entered_value: Annotated[float, Field(ge=0, le=MAX_NUTRIENT_VALUE, allow_inf_nan=False)]
    entered_unit: _short(40)
    taken_on: str
    note: _short(500) | None = None
    created_at: Timestamp

    @field_validator("created_at")
    @classmethod
    def _time(cls, v: str) -> str:
        return parse_timestamp(v)

    @model_validator(mode="after")
    def _as_typed(self) -> "ImportLab":
        """What the person typed (value and unit) is checked exactly like ``POST /api/labs``; the canonical value in
        the file is recomputed from it, never taken as is."""
        try:
            LabCreate(analyte=self.analyte, value=self.entered_value, unit=self.entered_unit, taken_on=self.taken_on,
                      note=self.note or "")
        except ValidationError as exc:
            first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
            where = ".".join(str(p) for p in first["loc"]) or "result"
            raise ValueError(f"{where}: {str(first['msg']).removeprefix('Value error, ')[:120]}") from None
        return self


class ImportSymptom(_Strict):
    id: Id
    date: str
    symptom: SymptomKey
    label: _short(MAX_SYMPTOM_LABEL) | None = None
    severity: Annotated[int, Field(ge=1, le=3)]
    note: _short(MAX_SYMPTOM_NOTE) | None = None
    created_at: Timestamp

    @field_validator("created_at")
    @classmethod
    def _time(cls, v: str) -> str:
        return parse_timestamp(v)

    @model_validator(mode="after")
    def _as_recorded(self) -> "ImportSymptom":
        """Checked exactly like ``POST /api/symptoms`` (date not in the future, a label only for "other", plain text);
        the id in the file is never used."""
        try:
            SymptomCreate(date=self.date, symptom=self.symptom, severity=self.severity, label=self.label or "",
                          note=self.note or "")
        except ValidationError as exc:
            first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
            where = ".".join(str(p) for p in first["loc"]) or "symptom"
            raise ValueError(f"{where}: {str(first['msg']).removeprefix('Value error, ')[:120]}") from None
        return self


class ImportWeight(_Strict):
    """A weight of ``export.json`` (:mod:`app.account`), kilograms. Checked exactly like ``POST /api/body/weights``; the id in
    the file is never used."""

    id: Id
    date: str
    time: str | None = None
    kg: Annotated[float, Field(allow_inf_nan=False)]
    context: WeightContext
    note: _short(MAX_BODY_NOTE) | None = None
    source: BodySourceKey
    source_key: _short(MAX_SOURCE_KEY) | None = None
    created_at: Timestamp
    updated_at: Timestamp

    @field_validator("created_at", "updated_at")
    @classmethod
    def _time(cls, v: str) -> str:
        return parse_timestamp(v)

    def as_recorded(self) -> WeightCreate:
        return WeightCreate(date=self.date, time=self.time, kg=self.kg, context=self.context, note=self.note or "")

    @model_validator(mode="after")
    def _as_recorded(self) -> "ImportWeight":
        try:
            self.as_recorded()
        except ValidationError as exc:
            first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
            where = ".".join(str(p) for p in first["loc"]) or "weight"
            raise ValueError(f"{where}: {str(first['msg']).removeprefix('Value error, ')[:120]}") from None
        return self


class ImportBloodPressure(_Strict):
    """A blood pressure reading of ``export.json``, checked exactly like ``POST /api/body/blood-pressure``."""

    id: Id
    date: str
    time: str | None = None
    systolic: int
    diastolic: int
    pulse: int | None = None
    context: BloodPressureContext
    note: _short(MAX_BODY_NOTE) | None = None
    source: BodySourceKey
    source_key: _short(MAX_SOURCE_KEY) | None = None
    created_at: Timestamp
    updated_at: Timestamp

    @field_validator("created_at", "updated_at")
    @classmethod
    def _time(cls, v: str) -> str:
        return parse_timestamp(v)

    def as_recorded(self) -> BloodPressureCreate:
        return BloodPressureCreate(date=self.date, time=self.time, systolic=self.systolic, diastolic=self.diastolic,
                                   pulse=self.pulse, context=self.context, note=self.note or "")

    @model_validator(mode="after")
    def _as_recorded(self) -> "ImportBloodPressure":
        try:
            self.as_recorded()
        except ValidationError as exc:
            first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
            where = ".".join(str(p) for p in first["loc"]) or "reading"
            raise ValueError(f"{where}: {str(first['msg']).removeprefix('Value error, ')[:120]}") from None
        return self


class ImportFoodPreference(_Strict):
    """A food preference of ``export.json`` (:mod:`app.account`). A file from before schema step 17 holds only
    ``not_for_me`` rows without ``source`` and ``updated_at``; they import as the person's own, changed when made."""

    food_id: Id
    name: _short(200)
    preference: Literal["like", "less", "not_for_me", "neutral"]
    created_at: Timestamp
    source: Literal["person", "ask", "assistant"] | None = None  # "assistant": set over MCP with an assistant:prefs token
    updated_at: Timestamp | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def _time(cls, v: str | None) -> str | None:
        return None if v is None else parse_timestamp(v)


class ImportProfile(ProfileUpdate):
    """The profile as ``GET /api/profile`` shows it: the fields a person edits, checked exactly like ``PUT
    /api/profile``, plus the read-only fields the server adds (accepted, not used)."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: Id | None = None
    updated_at: Timestamp | None = None
    ckd_stage_chosen: bool = True
    diabetes_chosen: bool = True


class ExportFile(_Strict):
    """``export.json`` version 1 (:mod:`app.account`). Every section but ``format`` and ``version`` may be missing:
    a file from an earlier build of version 1 has fewer."""

    format: Literal["kidney-health-export"]  # a Literal needs the text itself; tests/test_brand.py keeps it equal to brand.EXPORT_FORMAT
    version: Literal[1]
    exported_at: Timestamp | None = None
    app_version: _short(40) | None = None
    profile: ImportProfile | None = None
    settings: Annotated[dict[str, Any], Field(max_length=MAX_SETTINGS)] = {}
    log_entries: Annotated[list[ImportEntry], Field(max_length=MAX_ENTRIES)] = []
    custom_foods: Annotated[list[ImportFood], Field(max_length=MAX_CUSTOM_FOODS)] = []
    linked_foods: Annotated[list[ImportLinkedFood], Field(max_length=MAX_LINKED_FOODS)] = []
    builtin_foods: Annotated[list[ImportBuiltinRef], Field(max_length=MAX_BUILTIN_REFS)] = []
    meal_templates: Annotated[list[ImportMeal], Field(max_length=MAX_MEALS)] = []
    lab_results: Annotated[list[ImportLab], Field(max_length=MAX_LABS)] = []
    symptoms: Annotated[list[ImportSymptom], Field(max_length=MAX_SYMPTOMS)] = []
    weights: Annotated[list[ImportWeight], Field(max_length=MAX_WEIGHTS)] = []
    blood_pressures: Annotated[list[ImportBloodPressure], Field(max_length=MAX_BLOOD_PRESSURES)] = []
    food_preferences: Annotated[list[ImportFoodPreference], Field(max_length=MAX_FOOD_PREFERENCES)] = []
    # Accepted without looking inside, never read or stored.
    user: Any = None
    ai_audit: Any = None
    activity: Any = None
    ai_usage: Any = None
    ai_consents: Any = None
    ai_provider: Any = None
    activity_days: Any = None
    activity_workouts: Any = None
    activity_extra: Any = None

    @field_validator("exported_at")
    @classmethod
    def _exported_at(cls, v: str | None) -> str | None:
        return None if v is None else parse_timestamp(v)

    @field_validator("settings")
    @classmethod
    def _settings(cls, v: dict[str, Any]) -> dict[str, Any]:
        for key, value in v.items():
            if len(key) > 100:
                raise ValueError("a setting name is too long")
            if key in IMPORTED_SETTINGS:
                try:
                    settings_registry.get(key).validate(value)
                except (ValidationError, KeyError):
                    raise ValueError(f"{key}: not a value this server accepts") from None
        return v

    @model_validator(mode="after")
    def _custom_are_custom(self) -> "ExportFile":
        for i, food in enumerate(self.custom_foods):
            if food.source != "custom":
                raise ValueError(f"custom_foods[{i}].source: must be custom")
        return self


def checked_nutrients(values: dict[str, Any]) -> dict[str, float | None]:
    """:func:`~app.models.validate_nutrients`, without repeating the names of nutrients it does not know."""
    try:
        return validate_nutrients(values)
    except ValueError as exc:
        if "unknown nutrient" in str(exc):
            raise ValueError("has a nutrient this server does not know") from None
        raise


def _where(loc: Iterable[Any]) -> tuple[str, str | None, int | None]:
    text = ""
    kind: str | None = None
    index: int | None = None
    for n, part in enumerate(loc):
        if isinstance(part, int):
            text += f"[{part}]"
            if n == 1:
                index = part
        else:
            name = str(part)[:40]
            text += name if not text else f".{name}"
            if n == 0:
                kind = name
    return text, kind, index


def _refusal(exc: ValidationError) -> ImportRefused:
    first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
    where, kind, index = _where(first["loc"])
    message = str(first["msg"]).removeprefix("Value error, ")
    if first["type"] == "extra_forbidden":
        message = "unknown field; this server does not read it"
    message = short(message, MAX_MESSAGE_CHARS)
    return ImportRefused(f"{where}: {message}" if where else message, kind=kind, index=index)


MAX_DEPTH = 32  # a real export is about 5 levels deep
TOO_DEEP = f"This is not a {PRODUCT_NAME} export: the file is nested too deeply."


def nested_deeper_than(value: Any, limit: int) -> bool:
    """Whether lists and objects in ``value`` nest more than ``limit`` levels (no recursion, so any depth is safe)."""
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > limit:
            return True
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return False


def parse_export(raw: bytes) -> ExportFile:
    """The validated file, or :class:`ImportRefused` (nothing has touched the database yet)."""
    try:
        data = json.loads(raw, parse_constant=_refuse_constant, parse_float=_finite_float)
    except NotFinite:
        raise ImportRefused("The file holds a value that is not a finite number (NaN, Infinity or too large). "
                            "A real export never does; nothing was imported.") from None
    except RecursionError:  # Python 3.12's parser; 3.14's parses deep nesting, so the depth check below catches it
        raise ImportRefused(TOO_DEEP) from None
    except ValueError:  # includes UnicodeDecodeError, JSONDecodeError and int digit limits
        raise ImportRefused("This is not a valid JSON file. Choose the export.json from your export.") from None
    if nested_deeper_than(data, MAX_DEPTH):
        raise ImportRefused(TOO_DEEP)
    if not isinstance(data, dict):
        raise ImportRefused(f"This is not a {PRODUCT_NAME} export: the file must hold one JSON object.")
    fmt = data.get("format")
    if fmt != EXPORT_FORMAT:
        raise ImportRefused(f"This is not a {PRODUCT_NAME} export (its \"format\" is not \"{EXPORT_FORMAT}\").")
    version = data.get("version")
    if isinstance(version, bool) or version != SUPPORTED_VERSION:
        shown = short(version, 20) if isinstance(version, (int, float, str)) else "unknown"
        raise ImportRefused(f"This export is version {shown} of the format; this server reads version {SUPPORTED_VERSION}. "
                            "Export again from a server of the same release, or update this one.")
    try:
        return ExportFile.model_validate(data)
    except ValidationError as exc:
        raise _refusal(exc) from None


def check_ids(doc: ExportFile) -> None:
    """Food ids are what entries and saved meals point at, so they must name one food each."""
    seen: dict[int, str] = {}
    for kind, items in (("custom_foods", doc.custom_foods), ("linked_foods", doc.linked_foods),
                        ("builtin_foods", doc.builtin_foods)):
        for index, item in enumerate(items):
            if item.id in seen:
                other = seen[item.id]
                where = "this list" if other == kind else other
                raise ImportRefused(f"{kind}[{index}].id: the same food id is used twice (also in {where})",
                                    kind=kind, index=index)
            seen[item.id] = kind


# --------------------------------------------------------------------------- #
# Importing it
# --------------------------------------------------------------------------- #


class Blocked(Exception):
    """The account already has data and the person did not choose to add to it."""

    def __init__(self, existing: dict[str, int]) -> None:
        super().__init__("account_not_empty")
        self.existing = existing
        self.summary: dict[str, Any] | None = None


def _food_key(name: str, brand: str | None, category: str | None, serving_desc: str, serving_g: float,
              values: Mapping[str, Any], flags: Iterable[str], notes: str | None, gtin: str | None, hidden: bool) -> tuple:
    """What makes two own foods the same: everything the person sees (the values at the precision they are stored)."""
    return (name.casefold(), brand or "", category or "", serving_desc, round(float(serving_g), 1),
            tuple(values.get(k) for k in NUTRIENT_KEYS), tuple(sorted(flags)), notes or "", gtin or "", bool(hidden))


class Importer:
    """One run over a validated file. Everything happens on ``conn`` inside the caller's transaction."""

    def __init__(self, conn: sqlite3.Connection, user_id: int, doc: ExportFile, *, merge: bool, replace_profile: bool,
                 store: Any) -> None:
        self.conn = conn
        self.uid = int(user_id)
        self.doc = doc
        self.merge = merge
        self.replace_profile = replace_profile
        self.store = store
        self.counts: Counter[str] = Counter()
        self.already: Counter[str] = Counter()
        self.skipped_by_kind: Counter[str] = Counter()
        self.skipped: list[dict[str, Any]] = []
        self.food_map: dict[int, int] = {}  # a food id in the file -> the food id on this server
        self.unmatched: dict[int, str] = {}  # a food id in the file -> why it has no food here
        self._rows: dict[int, sqlite3.Row] = {}
        self.not_selected: list[str] = []

    # -- helpers ------------------------------------------------------------------------------------------------
    def skip(self, kind: str, index: int, label: str, reason: str) -> None:
        self.skipped_by_kind[kind] += 1
        if len(self.skipped) < MAX_SKIPPED_SHOWN:
            self.skipped.append({"kind": kind, "index": index, "label": short(label), "reason": reason})

    def food_row(self, food_id: int) -> sqlite3.Row:
        row = self._rows.get(food_id)
        if row is None:
            row = foods_module.fetch_food(self.conn, food_id)
            assert row is not None
            self._rows[food_id] = row
        return row

    def existing_counts(self) -> dict[str, int]:
        c, u = self.conn, self.uid
        return {
            "log_entries": c.execute("SELECT COUNT(*) FROM log_entries WHERE user_id = ?", (u,)).fetchone()[0],
            "custom_foods": c.execute("SELECT COUNT(*) FROM foods WHERE owner_user_id = ? AND source = 'custom'", (u,)).fetchone()[0],
            "meal_templates": c.execute("SELECT COUNT(*) FROM meal_templates WHERE user_id = ?", (u,)).fetchone()[0],
            "lab_results": c.execute("SELECT COUNT(*) FROM lab_results WHERE user_id = ?", (u,)).fetchone()[0],
            "symptoms": c.execute("SELECT COUNT(*) FROM symptoms WHERE user_id = ?", (u,)).fetchone()[0],
            "weights": c.execute("SELECT COUNT(*) FROM weights WHERE user_id = ?", (u,)).fetchone()[0],
            "blood_pressures": c.execute("SELECT COUNT(*) FROM blood_pressures WHERE user_id = ?", (u,)).fetchone()[0],
        }

    # -- foods ----------------------------------------------------------------------------------------------------
    def _own_food_index(self) -> dict[tuple, list[int]]:
        index: dict[tuple, list[int]] = {}
        for row in self.conn.execute("SELECT * FROM foods WHERE owner_user_id = ? AND source = 'custom' ORDER BY id", (self.uid,)):
            key = _food_key(row["name"], row["brand"], row["category"], row["serving_desc"], row["serving_g"],
                            foods_module.raw_nutrients(row), foods_module.parse_flags(row["flags_json"]),
                            row["kidney_notes"], row["gtin"], row["hidden"])
            index.setdefault(key, []).append(row["id"])
        return index

    def _own_food(self, food: ImportFood, index: dict[tuple, list[int]]) -> int:
        """The person's own food for ``food``: an identical one they already have, else a new one (the same checks
        and additive scan as ``POST /api/foods``). A shared food that this server lacks is kept the way ``POST
        /api/foods/{id}/copy`` keeps it: as an own food that remembers its barcode, ingredients and licence."""
        flags, notes, ingredients, found = scan_custom_food(food.name, food.flags, food.kidney_notes, food.ingredients_text)
        serving, values = stored_food_values(food.nutrients, flags, food.serving_g)
        gtin = food.gtin
        key = _food_key(food.name, food.brand, food.category, food.serving_desc, serving,
                        values, flags, notes, gtin, food.hidden)
        same = index.get(key)
        if same:
            self.already["custom_foods"] += 1
            return same.pop(0)
        self.counts["custom_foods"] += 1
        return foods_module.insert_food(
            self.conn, source="custom", owner_user_id=self.uid, name=food.name, brand=food.brand or None,
            category=food.category or None, serving_desc=food.serving_desc, serving_g=food.serving_g,
            nutrients=food.nutrients, flags=flags, kidney_notes=notes, hidden=food.hidden, fdc_id=food.fdc_id,
            provenance=Provenance(gtin=gtin, source_url=food.source_url, source_license=food.source_license,
                                  ingredients_text=ingredients, additives=tuple(found)),
        )

    def _shared_match(self, linked: ImportLinkedFood) -> sqlite3.Row | None:
        """This server's shared row for the same product (same FoodData Central id or barcode, and the same name or
        serving), so the person's link points at data this server already holds."""
        if linked.source == "usda" and linked.fdc_id is not None:
            row = self.conn.execute("SELECT * FROM foods WHERE source = 'usda' AND fdc_id = ? AND owner_user_id IS NULL ORDER BY id LIMIT 1",
                                    (linked.fdc_id,)).fetchone()
        elif linked.source == "off" and (gtin := linked.gtin or (linked.food.gtin if linked.food else None)):
            row = self.conn.execute("SELECT * FROM foods WHERE source = 'off' AND gtin = ? AND owner_user_id IS NULL LIMIT 1",
                                    (gtin,)).fetchone()
        else:
            return None
        if row is None:
            return None
        if linked.food is not None:
            return row if abs(float(row["serving_g"]) - linked.food.serving_g) < 0.05 else None
        return row if row["name"].casefold() == linked.name.casefold() else None

    def _builtin_match(self, food_id: int, name: str, fdc_id: int | None, *, by_id: bool) -> sqlite3.Row | None:
        """A built-in food of this server: by FoodData Central id; without one by name (how the built-in list is
        kept up to date); in a file with no ``builtin_foods`` by its id and name together."""
        c = self.conn
        if fdc_id is not None:
            return c.execute("SELECT * FROM foods WHERE source = 'builtin' AND fdc_id = ? ORDER BY hidden, id LIMIT 1", (fdc_id,)).fetchone()
        if by_id:
            return c.execute("SELECT * FROM foods WHERE source = 'builtin' AND id = ?", (food_id,)).fetchone()
        return c.execute("SELECT * FROM foods WHERE source = 'builtin' AND fdc_id IS NULL AND lower(name) = lower(?) ORDER BY hidden, id LIMIT 1",
                         (name,)).fetchone()

    def resolve_foods(self) -> None:
        doc, c = self.doc, self.conn
        index = self._own_food_index()
        for food in doc.custom_foods:
            self.food_map[food.id] = self._own_food(food, index)

        linked_before = {r[0] for r in c.execute("SELECT food_id FROM user_food_links WHERE user_id = ?", (self.uid,))}
        for linked in doc.linked_foods:
            row = self._shared_match(linked)
            if row is not None:
                link_food(c, self.uid, row["id"])
                self.food_map[linked.id] = row["id"]
                if row["id"] in linked_before:
                    self.already["shared_foods_linked"] += 1
                else:
                    self.counts["shared_foods_linked"] += 1
                    linked_before.add(row["id"])
            elif linked.food is not None:
                self.food_map[linked.id] = self._own_food(linked.food, index)
                self.counts["shared_foods_kept_as_own"] += 1
            else:
                self.unmatched[linked.id] = ("a shared food (USDA or Open Food Facts) this server does not have, and this older "
                                             "file does not carry its data")

        seen: dict[int, set[str]] = {}  # the names the file gives each food id it points at
        for entry in doc.log_entries:
            seen.setdefault(entry.food_id, set()).add(entry.food_name.casefold())
        for meal in doc.meal_templates:
            for item in meal.items:
                seen.setdefault(item.food_id, set()).add(item.food_name.casefold())
        for pref in doc.food_preferences:
            seen.setdefault(pref.food_id, set()).add(pref.name.casefold())
        listed = {ref.id for ref in doc.builtin_foods}
        for ref in doc.builtin_foods:
            row = self._builtin_match(ref.id, ref.name, ref.fdc_id, by_id=False)
            if row is not None:
                self.food_map[ref.id] = row["id"]
                self.counts["built_in_foods_matched"] += 1
            else:
                self.unmatched[ref.id] = "a built-in food this server does not have"
        for food_id, names in seen.items():
            if food_id in self.food_map or food_id in self.unmatched or food_id in listed:
                continue
            # No food of this id anywhere in the file: in an older file that is how a built-in food looks. It must be
            # a built-in food of this server with this id, and one of the names the file gives it must be its name.
            row = self._builtin_match(food_id, "", None, by_id=True)
            if row is not None and row["name"].casefold() in names:
                self.food_map[food_id] = row["id"]
                self.counts["built_in_foods_matched"] += 1
            else:
                self.unmatched[food_id] = "a food that is not in the file and is not a built-in food of this server"

    def reason_for(self, food_id: int) -> str:
        return f"its food is {self.unmatched.get(food_id, 'not in the file')}"

    # -- log entries ----------------------------------------------------------------------------------------------
    def import_entries(self) -> None:
        rows = self.conn.execute(
            "SELECT date, meal, food_id, servings, grams, status, created_at FROM log_entries WHERE user_id = ?", (self.uid,)
        ).fetchall()
        have: Counter[tuple] = Counter(
            (r["date"], r["meal"], r["food_id"], round(float(r["servings"]), 3),
             None if r["grams"] is None else round(float(r["grams"]), 1), r["status"], r["created_at"])
            for r in rows
        )
        for index, e in enumerate(self.doc.log_entries):
            target = self.food_map.get(e.food_id)
            if target is None:
                self.skip("log_entries", index, f"{e.date} {e.meal}: {e.food_name}", self.reason_for(e.food_id))
                continue
            food = self.food_row(target)
            grams = e.grams if foods_module.weight_known(food) else None
            key = (e.date, e.meal, target, round(e.servings, 3), None if grams is None else round(grams, 1), e.status, e.created_at)
            if have[key] > 0:
                have[key] -= 1
                self.already["log_entries"] += 1
                continue
            insert_entry(self.conn, user_id=self.uid, date=e.date, meal=e.meal, food=food, servings=e.servings, grams=grams,
                         note=e.note or None, status=e.status, purpose=e.purpose, client_id=None,
                         created_at=e.created_at, updated_at=e.updated_at)
            self.counts["log_entries"] += 1

    # -- saved meals ----------------------------------------------------------------------------------------------
    def import_meals(self) -> None:
        have: Counter[tuple] = Counter()
        for r in self.conn.execute("SELECT name, note, meal_hint, items_json FROM meal_templates WHERE user_id = ?", (self.uid,)):
            items = tuple((i["food_id"], round(i["servings"], 3)) for i in parse_items(r["items_json"]))
            have[(r["name"].casefold(), r["note"] or "", r["meal_hint"], items)] += 1
        for index, m in enumerate(self.doc.meal_templates):
            items: list[dict[str, Any]] = []
            lost: list[tuple[str, str]] = []
            for item in m.items:
                target = self.food_map.get(item.food_id)
                if target is None:
                    lost.append((f"{m.name}: {item.food_name}", self.reason_for(item.food_id)))
                else:
                    items.append({"food_id": target, "servings": float(item.servings)})
            if not items:
                self.skip("meal_templates", index, m.name, "none of its foods could be matched" if lost else "it has no foods")
                continue
            note = m.note or ""
            if lost:
                # The meal is kept without them, and says so in its note for good: totals that miss a food must not
                # read as complete. The person is also told which foods in the answer.
                names = [item.food_name for item in m.items if self.food_map.get(item.food_id) is None]
                shown = ", ".join(short(n, 40) for n in names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
                added = f"Imported without {len(names)} {'food' if len(names) == 1 else 'foods'} that could not be matched: {shown}."
                note = f"{note[:max(0, MAX_NOTE_CHARS - len(added) - 1)]} {added}".strip()
                for label, reason in lost:
                    self.skip("meal_templates", index, label, reason)
            key = (m.name.casefold(), note, m.meal_hint, tuple((i["food_id"], round(i["servings"], 3)) for i in items))
            if have[key] > 0:
                have[key] -= 1
                self.already["meal_templates"] += 1
                continue
            insert_template(self.conn, user_id=self.uid, name=m.name, note=note or None, items=items,
                            meal_hint=m.meal_hint, created_at=m.created_at, updated_at=m.updated_at,
                            servings_made=m.servings_made, steps=m.steps, source_url=m.source_url)
            self.counts["meal_templates"] += 1

    # -- lab results ----------------------------------------------------------------------------------------------
    def import_labs(self) -> None:
        have: Counter[tuple] = Counter(
            (r["analyte"], r["taken_on"], units.format_value(r["analyte"], r["value"]))
            for r in self.conn.execute("SELECT analyte, taken_on, value FROM lab_results WHERE user_id = ?", (self.uid,))
            if r["analyte"] in units.ANALYTES  # a row written by a later version is kept, never matched
        )
        for lab in self.doc.lab_results:
            result = units.convert(lab.analyte, lab.entered_value, lab.entered_unit)  # checked when the file was read
            key = (result["analyte"], lab.taken_on, units.format_value(result["analyte"], result["value"]))
            if have[key] > 0:
                have[key] -= 1
                self.already["lab_results"] += 1
                continue
            self.conn.execute(
                """INSERT INTO lab_results (user_id, analyte, value, entered_value, entered_unit, taken_on, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.uid, result["analyte"], result["value"], result["entered_value"], result["entered_unit"],
                 lab.taken_on, lab.note or "", lab.created_at),
            )
            self.counts["lab_results"] += 1

    # -- symptoms ---------------------------------------------------------------------------------------------------
    def import_symptoms(self) -> None:
        from .symptoms import SYMPTOM_NAMES

        have: Counter[tuple] = Counter(
            (r["date"], r["symptom"], r["label"], r["severity"], r["note"])
            for r in self.conn.execute("SELECT date, symptom, label, severity, note FROM symptoms WHERE user_id = ?", (self.uid,))
        )
        per_day: Counter[str] = Counter(r[0] for r in self.conn.execute("SELECT date FROM symptoms WHERE user_id = ?", (self.uid,)))
        for index, s in enumerate(self.doc.symptoms):
            label, note = s.label or "", s.note or ""
            key = (s.date, s.symptom, label, s.severity, note)
            if have[key] > 0:
                have[key] -= 1
                self.already["symptoms"] += 1
                continue
            if per_day[s.date] >= MAX_SYMPTOMS_PER_DAY:
                self.skip("symptoms", index, label or SYMPTOM_NAMES[s.symptom],
                          f"that day already has {MAX_SYMPTOMS_PER_DAY} symptoms, the most one day holds")
                continue
            self.conn.execute(
                "INSERT INTO symptoms (user_id, date, symptom, label, severity, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.uid, s.date, s.symptom, label, s.severity, note, s.created_at),
            )
            per_day[s.date] += 1
            self.counts["symptoms"] += 1

    # -- weights and blood pressure readings (schema step 18) ----------------------------------------------------------
    def import_weights(self) -> None:
        """A row with a ``source_key`` is left out when the person has that key; a row without one (typed by the person) is
        left out when an identical one is here. A crowded day is skipped and reported."""
        c, u = self.conn, self.uid
        keys = {r[0] for r in c.execute("SELECT source_key FROM weights WHERE user_id = ? AND source_key IS NOT NULL", (u,))}
        have: Counter[tuple] = Counter(
            (r["date"], r["time"], round(float(r["kg"]), 2), r["context"], r["note"] or "")
            for r in c.execute("SELECT date, time, kg, context, note FROM weights WHERE user_id = ? AND source_key IS NULL", (u,)))
        per_day: Counter[str] = Counter(r[0] for r in c.execute("SELECT date FROM weights WHERE user_id = ?", (u,)))
        for index, w in enumerate(self.doc.weights):
            rec = w.as_recorded()  # the same cleaning as POST /api/body/weights (text stripped, a blank time is none)
            note, kg, time = rec.note, round_kg(rec.kg), rec.time
            if w.source_key is not None:
                if w.source_key in keys:
                    self.already["weights"] += 1
                    continue
            else:
                identity = (rec.date, time, kg, w.context, note)
                if have[identity] > 0:
                    have[identity] -= 1
                    self.already["weights"] += 1
                    continue
            if per_day[rec.date] >= MAX_WEIGHTS_PER_DAY:
                self.skip("weights", index, f"{kg:.2f} kg on {rec.date}", f"that day already has {MAX_WEIGHTS_PER_DAY} weights, the most one day holds")
                continue
            c.execute(
                "INSERT INTO weights (user_id, date, time, kg, context, note, source, source_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (u, rec.date, time, kg, w.context, note, w.source, w.source_key, w.created_at, w.updated_at),
            )
            if w.source_key is not None:
                keys.add(w.source_key)
            per_day[rec.date] += 1
            self.counts["weights"] += 1

    def import_blood_pressures(self) -> None:
        c, u = self.conn, self.uid
        keys = {r[0] for r in c.execute("SELECT source_key FROM blood_pressures WHERE user_id = ? AND source_key IS NOT NULL", (u,))}
        have: Counter[tuple] = Counter(
            (r["date"], r["time"], r["systolic"], r["diastolic"], r["pulse"], r["context"], r["note"] or "")
            for r in c.execute("SELECT date, time, systolic, diastolic, pulse, context, note FROM blood_pressures "
                               "WHERE user_id = ? AND source_key IS NULL", (u,)))
        per_day: Counter[str] = Counter(r[0] for r in c.execute("SELECT date FROM blood_pressures WHERE user_id = ?", (u,)))
        for index, b in enumerate(self.doc.blood_pressures):
            rec = b.as_recorded()
            note, time = rec.note, rec.time
            if b.source_key is not None:
                if b.source_key in keys:
                    self.already["blood_pressures"] += 1
                    continue
            else:
                identity = (rec.date, time, b.systolic, b.diastolic, b.pulse, b.context, note)
                if have[identity] > 0:
                    have[identity] -= 1
                    self.already["blood_pressures"] += 1
                    continue
            if per_day[rec.date] >= MAX_READINGS_PER_DAY:
                self.skip("blood_pressures", index, f"{b.systolic}/{b.diastolic} on {rec.date}",
                          f"that day already has {MAX_READINGS_PER_DAY} blood pressure readings, the most one day holds")
                continue
            c.execute(
                "INSERT INTO blood_pressures (user_id, date, time, systolic, diastolic, pulse, context, note, source, source_key, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (u, rec.date, time, b.systolic, b.diastolic, b.pulse, b.context, note, b.source, b.source_key, b.created_at, b.updated_at),
            )
            if b.source_key is not None:
                keys.add(b.source_key)
            per_day[rec.date] += 1
            self.counts["blood_pressures"] += 1

    # -- food preferences (like, less often, "Not for me", neutral) -------------------------------------------------
    def import_preferences(self) -> None:
        c = self.conn
        count = c.execute("SELECT COUNT(*) FROM food_preferences WHERE user_id = ?", (self.uid,)).fetchone()[0]
        never = c.execute("SELECT COUNT(*) FROM food_preferences WHERE user_id = ? AND preference = ?",
                          (self.uid, PREFERENCE_NOT_FOR_ME)).fetchone()[0]
        for index, p in enumerate(self.doc.food_preferences):
            target = self.food_map.get(p.food_id)
            if target is None:
                self.skip("food_preferences", index, p.name, self.reason_for(p.food_id))
                continue
            if c.execute("SELECT 1 FROM food_preferences WHERE user_id = ? AND food_id = ?", (self.uid, target)).fetchone():
                self.already["food_preferences"] += 1
                continue
            if p.preference == PREFERENCE_NOT_FOR_ME and never >= MAX_NOT_FOR_ME:
                self.skip("food_preferences", index, p.name, f"the \"Not for me\" list is full ({MAX_NOT_FOR_ME} foods)")
                continue
            if count >= MAX_FOOD_PREFERENCES:
                self.skip("food_preferences", index, p.name, f"your food preferences are full ({MAX_FOOD_PREFERENCES} foods)")
                continue
            c.execute("""INSERT INTO food_preferences (user_id, food_id, preference, created_at, source, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (self.uid, target, p.preference, p.created_at, p.source or "person", p.updated_at or p.created_at))
            count += 1
            never += p.preference == PREFERENCE_NOT_FOR_ME
            self.counts["food_preferences"] += 1

    # -- profile, targets, settings -----------------------------------------------------------------------------------
    def import_profile_and_settings(self) -> None:
        doc = self.doc
        if not self.replace_profile:
            if doc.profile is not None:
                self.not_selected.append("your profile and targets")
            if any(key in IMPORTED_SETTINGS for key in doc.settings):
                self.not_selected.append("your meal-guidance, display, weight and blood pressure settings")
            return
        if doc.profile is not None:
            self.conn.execute("INSERT OR IGNORE INTO user_profiles (user_id, updated_at, updated_by) VALUES (?, ?, ?)",
                              (self.uid, utcnow(), self.uid))
            data = doc.profile.model_dump(exclude_unset=True, exclude={"id", "updated_at", "ckd_stage_chosen", "diabetes_chosen"})
            # A stage or diabetes type the person had not chosen yet stays "not chosen yet" here too.
            if not doc.profile.ckd_stage_chosen:
                data.pop("ckd_stage", None)
            if not doc.profile.diabetes_chosen:
                data.pop("diabetes", None)
            apply_profile_changes(self.conn, self.uid, data, get_profile(self.conn, self.uid), replace_targets=True)
            self.counts["profile"] = 1
        for key, value in doc.settings.items():
            if key not in IMPORTED_SETTINGS:
                self.skip("settings", 0, key, "it is not a setting this import carries over (consents and server settings are never imported)")
                continue
            try:
                self.store.set_user(self.conn, self.uid, key, value)
                self.counts["settings"] += 1
            except (SettingLocked, SettingNotEditable, SettingsUnavailable):
                self.skip("settings", 0, key, "this server does not let you change it")

    # -- the run ----------------------------------------------------------------------------------------------------
    def run(self) -> None:
        existing = self.existing_counts()
        if any(existing.values()) and not self.merge:
            raise Blocked(existing)
        self.resolve_foods()
        self.import_entries()
        self.import_meals()
        self.import_labs()
        self.import_symptoms()
        self.import_weights()
        self.import_blood_pressures()
        self.import_preferences()
        self.import_profile_and_settings()

    def skipped_answer(self) -> dict[str, Any]:
        total = sum(self.skipped_by_kind.values())
        return {"total": total, "shown": self.skipped, "by_kind": dict(self.skipped_by_kind),
                "more": max(0, total - len(self.skipped))}


COUNT_KEYS = ("log_entries", "custom_foods", "shared_foods_kept_as_own", "shared_foods_linked", "built_in_foods_matched",
              "meal_templates", "lab_results", "symptoms", "weights", "blood_pressures", "food_preferences", "profile", "settings")
ALREADY_KEYS = ("log_entries", "custom_foods", "shared_foods_linked", "meal_templates", "lab_results", "symptoms",
                "weights", "blood_pressures", "food_preferences")


def _file_summary(doc: ExportFile) -> dict[str, Any]:
    return {
        "format": doc.format, "version": doc.version, "exported_at": doc.exported_at,
        "app_version": short(doc.app_version, 40) if doc.app_version else None,
        "records": {"log_entries": len(doc.log_entries), "custom_foods": len(doc.custom_foods),
                    "linked_foods": len(doc.linked_foods), "meal_templates": len(doc.meal_templates),
                    "lab_results": len(doc.lab_results), "symptoms": len(doc.symptoms),
                    "weights": len(doc.weights), "blood_pressures": len(doc.blood_pressures),
                    "food_preferences": len(doc.food_preferences),
                    "profile": 1 if doc.profile is not None else 0},
    }


def run_import(conn: sqlite3.Connection, user_id: int, raw: bytes, *, dry_run: bool, merge: bool, replace_profile: bool,
                store: Any, ip: str | None) -> dict[str, Any]:
    """Read ``raw``, import it for ``user_id``, answer what was (or, for a dry run, would be) done. Raises
    :class:`ImportRefused` for a file this server does not read and :class:`Blocked` for an account that has data."""
    doc = parse_export(raw)
    check_ids(doc)
    if conn.in_transaction:
        conn.commit()
    importer = Importer(conn, user_id, doc, merge=merge, replace_profile=replace_profile, store=store)
    committed = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        importer.run()
        if dry_run:
            conn.rollback()
        else:
            audit(conn, user_id, "data.imported", "user", user_id, ip=ip, merge=merge, profile=bool(importer.counts["profile"]),
                  **{k: int(importer.counts[k]) for k in ("log_entries", "custom_foods", "meal_templates", "lab_results",
                                                          "symptoms", "weights", "blood_pressures", "food_preferences")})
            conn.commit()
            committed = True
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise busy() from None
        raise
    except Blocked as exc:
        conn.rollback()
        exc.summary = _file_summary(doc)
        raise
    except BaseException:
        conn.rollback()
        raise
    finally:
        if not committed and replace_profile:
            store.invalidate()  # settings read back inside the transaction that was rolled back must not stay cached
    return {
        "dry_run": dry_run, "imported": not dry_run, "can_import": True, "blocked": None,
        "file": _file_summary(doc),
        "options": {"merge": merge, "replace_profile": replace_profile},
        "counts": {k: int(importer.counts[k]) for k in COUNT_KEYS},
        "already_there": {k: int(importer.already[k]) for k in ALREADY_KEYS},
        "skipped": importer.skipped_answer(),
        "not_selected": importer.not_selected,
        "not_imported": list(NOT_IMPORTED),
        "rule": RULE,
    }


def blocked_answer(existing: dict[str, int], *, dry_run: bool, merge: bool, replace_profile: bool, doc_summary: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "dry_run": dry_run, "imported": False, "can_import": False,
        "blocked": {"code": "account_not_empty", "existing": existing,
                    "message": "This account already has data. Importing is refused unless you choose \"Add to my existing data\"."},
        "file": doc_summary, "options": {"merge": merge, "replace_profile": replace_profile},
        "counts": {k: 0 for k in COUNT_KEYS}, "already_there": {k: 0 for k in ALREADY_KEYS},
        "skipped": {"total": 0, "shown": [], "by_kind": {}, "more": 0}, "not_selected": [],
        "not_imported": list(NOT_IMPORTED), "rule": RULE,
    }


def handle(conn: sqlite3.Connection, user_id: int, raw: bytes, *, dry_run: bool, merge: bool, replace_profile: bool,
           store: Any, ip: str | None) -> dict[str, Any]:
    """:func:`run_import` with the refusals turned into HTTP problems (400 for the file, 409 for a filled account;
    a dry run answers 200 with ``can_import: false`` for the latter, so the page can offer the choice)."""
    try:
        return run_import(conn, user_id, raw, dry_run=dry_run, merge=merge, replace_profile=replace_profile, store=store, ip=ip)
    except ImportRefused as exc:
        raise ApiProblem(400, f"The file was not imported. {exc.message}", kind=exc.kind, index=exc.index) from None
    except Blocked as exc:
        answer = blocked_answer(exc.existing, dry_run=dry_run, merge=merge, replace_profile=replace_profile,
                                doc_summary=exc.summary)
        if dry_run:
            return answer
        raise ApiProblem(409, answer["blocked"]["message"], blocked=answer["blocked"]) from None


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #


@router.post("")
async def import_my_data(request: Request, user: RecentUser, dry_run: bool = False, merge: bool = False,
                         replace_profile: bool = False, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Import the person's own ``export.json`` (the request body, ``application/json``). See the module docstring."""
    ctx = auth_context(request)
    ctx.limits.take("import", f"user:{user.id}")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ApiProblem(415, "Send the export.json file as application/json")
    raw = await request.body()  # BodyLimitMiddleware has capped it at MAX_IMPORT_BYTES
    if not raw:
        raise ApiProblem(400, "The file was not imported. It is empty.")
    return await run_in_threadpool(
        handle, conn, user.id, raw, dry_run=dry_run, merge=merge, replace_profile=replace_profile,
        store=request.app.state.settings_store, ip=request_ip(request),
    )
