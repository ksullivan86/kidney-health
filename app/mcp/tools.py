"""The assistant's four read-only tools (``docs/dev/plans/assistant-step1.md`` part B; ARCHITECTURE.md "Assistant
MCP server"). Each answers one JSON object, sent as ``structuredContent`` and as text.

Every number comes from the app's own functions, never from a copy of the maths:

* ``get_today``: :func:`app.log.day_summary`, the function behind ``GET /api/log?date=`` (Today), so the numbers
  are Today's; dialysis totals from the period summary's :func:`app.periods.interdialytic_block`.
* ``search_foods``: :func:`app.foods.search_foods` (the person's foods and the built-in list), then FoodData
  Central through the app's own key resolution and record mapping (:func:`app.foods.map_usda_record`); nothing
  is saved.
* ``check_meal``: the item is found in the app, scaled like a log entry (:func:`app.nutrients.scale_nutrients`),
  warned about with :func:`app.nutrients.food_warnings`, and the day is projected with
  :func:`app.log.day_figures` as if the items were planned entries. Nothing is saved.
* ``safety_check``: the app's rule-based pre-filters: :func:`app.guidance.hypo.prefilter` (the Treating a low
  card with the person's own ``hypo_dose_g``) and :func:`app.ai.features.red_flag` (Get help now).

Unknown stays unknown: a value a food does not list is ``null``, and every total says how many items or entries
it misses (``not_listed_by``); a total that is all unknown is ``null``, never 0. No tool returns insulin or
medicine doses, medicine advice or lab interpretation, and nothing here ever delays or warns against treating a low.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from typing import Any, Callable, Literal, Mapping

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .. import foods
from .. import log as food_log
from ..ai import features as ai_features
from ..auth.context import public_base
from ..auth.errors import ApiProblem
from ..auth.models import User
from ..guidance import context as guidance_context
from ..guidance import hypo
from ..models import MAX_GRAMS, MAX_SERVINGS, validate_date
from ..nutrients import (MEALS, NUTRIENT_BY_KEY, NUTRIENT_KEYS, _carb_goals, _status_word, add_totals,
                         count_unknown, empty_totals, food_warnings, is_about, kidney_rating, round_nutrients,
                         round_value, scale_nutrients)
from ..periods import (MAX_INTERDIALYTIC_DAYS, NOTE_CAPPED, NOTE_INTERDIALYTIC, NOTE_NO_DIALYSIS_DAYS, WEEKDAY_NAMES,
                       interdialytic_block, interdialytic_interval)
from ..profile import get_profile, settings_store
from . import measures as M

logger = logging.getLogger("kidney_health.mcp")

SOURCE = "kidney-health"
REMINDER = "Numbers come from the app; fetch them again after any change."
MAX_ROW_ID = 2**63 - 1
GET_HELP_NOW = "/learn/get-help-now/"
# check_meal: candidates read per item, alternatives offered when the match is not certain.
SEARCH_CANDIDATES = 8
MAX_ALTERNATIVES = 5
# A planned item with no meal: counted in the day's totals, compared with no meal's carbohydrate goal
# (app.nutrients judges per-meal carbohydrate for breakfast, lunch, dinner and snack only).
NO_MEAL = "unassigned"


class ToolError(Exception):
    """A short, safe message for the model (an ``isError`` result)."""


@dataclass(frozen=True)
class Call:
    request: Request
    conn: sqlite3.Connection
    user: User


# --------------------------------------------------------------------------- #
# Arguments
# --------------------------------------------------------------------------- #


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


def _check_date(value: str | None) -> str | None:
    return None if value is None else validate_date(value)


class TodayArgs(_Args):
    date: str | None = None

    check_date = field_validator("date")(_check_date)


class SearchArgs(_Args):
    query: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=5, ge=1, le=10)


class MealItem(_Args):
    food: str = Field(min_length=1, max_length=100)
    amount: float | None = Field(default=None, gt=0, le=MAX_GRAMS, allow_inf_nan=False)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    food_id: int | None = Field(default=None, ge=1, le=MAX_ROW_ID)


class MealArgs(_Args):
    items: list[MealItem] = Field(min_length=1, max_length=20)
    date: str | None = None
    meal: Literal["breakfast", "lunch", "dinner", "snack"] | None = None

    check_date = field_validator("date")(_check_date)


class SafetyArgs(_Args):
    message: str = Field(max_length=2000)


def describe(exc: ValidationError) -> str:
    """``"Invalid arguments: items.0.amount: Input should be greater than 0."``: field and rule, never the value."""
    parts = []
    for err in exc.errors()[:4]:
        where = ".".join(str(p) for p in err.get("loc", ())) or "arguments"
        parts.append(f"{where}: {err.get('msg', 'invalid')}")
    return "Invalid arguments: " + "; ".join(parts) + "."


# --------------------------------------------------------------------------- #
# Shared views
# --------------------------------------------------------------------------- #


def amount(value: Any, missing: Any) -> dict[str, Any]:
    """A total and how many items or entries it misses: ``{"value": 422, "not_listed_by": 0}``. With
    ``not_listed_by > 0`` the true total may be higher; when nothing that counts lists it, ``value`` is ``null``."""
    missing = int(missing or 0)
    return {"value": None if missing and not value else value, "not_listed_by": missing}


def target_view(key: str, item: Mapping[str, Any]) -> dict[str, Any]:
    """A daily status item's target: ``max`` (``target``), ``min``, whether it is an "about" target, and the word
    the app's alerts use for it (limit, maximum, goal, target)."""
    lo, hi = item.get("min"), item.get("target")
    about = lo is not None and hi is not None and is_about(key, float(lo), float(hi))
    return {"max": hi, "min": lo, "about": about, "kind": _status_word(key, item)}


def judged(key: str, item: Mapping[str, Any]) -> dict[str, Any]:
    """Level, percent, and what is left or over, as Today's bar shows it: "left" only when every entry lists the
    value (otherwise the total may be higher), "over" when above the maximum."""
    fraction = item.get("fraction")
    out: dict[str, Any] = {
        "level": item.get("level"),
        "percent": None if fraction is None else int(round(float(fraction) * 100)),
        "left": None,
        "over_by": None,
    }
    target, value = item.get("target"), item.get("value")
    if target is not None and value is not None:
        if fraction is not None and fraction > 1:
            out["over_by"] = round_value(key, float(value) - float(target))
            if item.get("level") != "over":
                out["within_tolerance"] = True  # an "about" target, within the person's own tolerance
        elif not int(item.get("unknown") or 0):
            out["left"] = round_value(key, float(target) - float(value))
    return out


def nutrient_views(figures: Mapping[str, Any], *, with_planned: bool) -> dict[str, Any]:
    """Every nutrient: eaten, planned and both, each with its unknown count; the target and the judgement where a
    target is set (``with_planned``: also eaten + planned against it)."""
    out: dict[str, Any] = {}
    for key in NUTRIENT_KEYS:
        nutrient = NUTRIENT_BY_KEY[key]
        view: dict[str, Any] = {
            "name": nutrient.label,
            "unit": nutrient.unit,
            "eaten": amount(figures["totals"][key], figures["unknown"].get(key)),
            "planned": amount(figures["planned_totals"][key], figures["planned_unknown"].get(key)),
            "eaten_and_planned": amount(figures["projected_totals"][key], figures["projected_unknown"].get(key)),
        }
        item = figures["status"].get(key)
        if item is not None:
            view["target"] = target_view(key, item)
            view["eaten_vs_target"] = judged(key, item)
            if with_planned:
                view["eaten_and_planned_vs_target"] = judged(key, figures["projected_status"][key])
        out[key] = view
    return out


def _carbs(value: Any) -> float:
    number = float(value or 0.0)
    return number if math.isfinite(number) else 0.0


def meal_carbohydrate(figures: Mapping[str, Any], targets: Mapping[str, Any], low_carbs: Mapping[str, float]) -> dict[str, Any]:
    """Per-meal carbohydrate against the meal goals (only for a profile with diabetes: ``has_meal_carb_goals``).
    ``low_carbs``: carbohydrate eaten to treat a low, per meal; it counts in the day's totals, never toward a meal."""
    goals = _carb_goals(targets.get("carbs_per_meal_g"), targets.get("carbs_per_snack_g"))
    over = {a.get("meal") for a in figures["alerts"] if a.get("meal")}
    over_planned = {a.get("meal") for a in figures["projected_alerts"] if a.get("meal")}
    meals: dict[str, Any] = {}
    for meal in MEALS:
        eaten = _carbs(figures["meals"][meal]["carbs_g"])
        missing = int(figures["meal_unknown"][meal].get("carbs_g", 0))
        low = low_carbs.get(meal, 0.0)
        goal = goals.get(meal)
        counted = eaten - low
        meals[meal] = {
            "goal_g": round_value("carbs_g", goal),
            "eaten_g": amount(round_value("carbs_g", eaten), missing)["value"],
            "not_listed_by": missing,
            "treating_a_low_g": round_value("carbs_g", low),
            "planned_g": round_value("carbs_g", _carbs(figures["planned_meals"][meal]["carbs_g"])),
            "left_g": None if goal is None or missing else round_value("carbs_g", max(0.0, goal - counted)),
            "over": meal in over,
            "over_if_planned_food_is_eaten": meal in over_planned,
        }
    return {
        "goals_set": bool(goals),
        "tolerance_g": figures["carb_tolerance_g"],
        "meals": meals,
        "note": ("Carbohydrate eaten to treat a low counts in the day's totals but never toward a meal's goal. A meal "
                 "counts as over only when it is more than tolerance_g above its goal."
                 + ("" if goals else " No per-meal carbohydrate goal is set yet (the person sets it in Profile).")),
    }


def dialysis_info(conn: sqlite3.Connection, user_id: int, profile: Mapping[str, Any], day: str) -> dict[str, Any] | None:
    """The dialysis type and, on hemodialysis with dialysis days set, whether ``day`` is one and the eaten totals
    since the last session (the period summary's ``interdialytic`` block)."""
    mode = profile.get("dialysis") or "none"
    if mode == "none":
        return None
    info: dict[str, Any] = {"type": mode}
    if mode != "hemodialysis":
        return info
    days = list(profile.get("dialysis_days") or [])
    info["dialysis_days"] = [WEEKDAY_NAMES[d] for d in days]
    if not days:
        info["notes"] = [NOTE_NO_DIALYSIS_DAYS]
        return info
    info["is_dialysis_day"] = _date.fromisoformat(day).weekday() in days
    interval = interdialytic_interval(day, days)
    if interval is not None:
        totals = food_log.eaten_day_totals(conn, user_id, interval["since"], day)
        unknown = food_log.eaten_day_unknown(conn, user_id, interval["since"], day)
        info["since_last_dialysis"] = interdialytic_block(interval, totals, profile["targets"], profile["warn_fraction"],
                                                          day_unknown=unknown)
        info["notes"] = [NOTE_INTERDIALYTIC] + ([NOTE_CAPPED.format(n=MAX_INTERDIALYTIC_DAYS)] if interval["capped"] else [])
    return info


def finish(result: dict[str, Any]) -> dict[str, Any]:
    result["source"] = SOURCE
    result["reminder"] = REMINDER
    return result


# --------------------------------------------------------------------------- #
# get_today
# --------------------------------------------------------------------------- #


def get_today(call: Call, args: TodayArgs) -> dict[str, Any]:
    today = food_log.today_local()
    day = args.date or today
    summary = food_log.day_summary(call.conn, call.request, call.user.id, day)
    profile = get_profile(call.conn, call.user.id)
    counts = summary["counts"]
    result: dict[str, Any] = {
        "date": day,
        "is_today": day == today,
        "entries": {"eaten": counts["eaten"], "planned": counts["planned"]},
        "targets_set": bool(summary["status"]),
        "nutrients": nutrient_views(summary, with_planned=bool(counts["planned"])),
        "alerts": summary["alerts"],
        "alerts_if_planned_food_is_eaten": summary["projected_alerts"],
        "pattern_alerts": summary["pattern_alerts"],
    }
    if not result["targets_set"]:
        result["note"] = "No targets are set yet: the person sets them in the app (Profile)."
    if profile.get("about_tolerance_pct"):
        result["about_tolerance_pct"] = profile["about_tolerance_pct"]
    if food_log.has_meal_carb_goals(profile):
        low: dict[str, float] = {}
        for entry in summary["entries"]:
            if entry["status"] != "planned" and entry.get("purpose") == food_log.HYPO_PURPOSE:
                low[entry["meal"]] = low.get(entry["meal"], 0.0) + _carbs(entry["nutrients"]["carbs_g"])
        result["meal_carbohydrate"] = meal_carbohydrate(summary, summary["targets"], low)
    dialysis = dialysis_info(call.conn, call.user.id, profile, day)
    if dialysis is not None:
        result["dialysis"] = dialysis
    return finish(result)


# --------------------------------------------------------------------------- #
# search_foods
# --------------------------------------------------------------------------- #


def grams_usable(quality: Any) -> bool:
    """Whether a food's serving weight describes its values (``app.foods.weight_known`` on the API's ``quality``)."""
    codes = {str(q.get("code")) for q in quality or () if isinstance(q, Mapping)}
    return not foods.WEIGHT_UNKNOWN_CODES.intersection(codes)


def units_for(serving_desc: str, weight_ok: bool) -> list[str]:
    """What ``check_meal`` accepts as ``unit`` for a food: servings, grams when the weight is known, and the
    household measures its serving description lists."""
    if not weight_ok:
        return ["serving"]
    return ["serving", "g", *(m.label for m in M.food_measures(serving_desc).values())]


def app_food(food: Mapping[str, Any]) -> dict[str, Any]:
    """A food from the app's own search (``app.foods.row_to_food``), per serving."""
    return {
        "id": food["id"],
        "fdc_id": food["fdc_id"],
        "name": food["name"],
        "brand": food["brand"],
        "source": food["source"],
        "in_app": True,
        "serving": {"description": food["serving_desc"], "grams": food["serving_g"]},
        "units": units_for(food["serving_desc"], grams_usable(food.get("quality"))),
        "nutrients_per_serving": food["nutrients"],
        "warnings_per_serving": food["warnings"],
        "kidney_rating": food["kidney_rating"],
        "notes": food["kidney_notes"],
    }


def usda_food(record: Mapping[str, Any], fdc_id: int) -> dict[str, Any]:
    """A FoodData Central search result, mapped as an import would map it (never saved)."""
    mapped = foods.map_usda_record(record, fdc_id).kwargs
    serving_g, values = foods.stored_food_values(mapped["nutrients"], mapped["flags"], mapped["serving_g"])
    warnings = food_warnings(values, mapped["flags"], mapped["kidney_notes"])
    return {
        "id": None,
        "fdc_id": fdc_id,
        "name": mapped["name"],
        "brand": mapped["brand"],
        "source": "usda",
        "in_app": False,
        "serving": {"description": mapped["serving_desc"], "grams": serving_g},
        "units": [],
        "nutrients_per_serving": round_nutrients(values),
        "warnings_per_serving": warnings,
        "kidney_rating": kidney_rating(warnings),
        "notes": mapped["kidney_notes"],
    }


def usda_results(call: Call, query: str, room: int, seen: set[int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Up to ``room`` FoodData Central results the app's own list does not have, and what happened."""
    if room <= 0:
        return [], {"searched": False, "detail": "The app's own foods filled the results."}
    try:
        cred = foods.usda_credential(call.request, call.conn, call.user.id, call.user.can_use_shared)
    except ApiProblem as exc:  # no key, not shared with this person, quota used up, paused near the hourly limit
        return [], {"searched": False, "detail": exc.detail}
    try:
        records = foods.usda_search_records(query, min(25, room + len(seen) + 5), cred.api_key,
                                            guard=foods.guard_id(cred, call.user.id), own_key=cred.scope == "own")
    except foods.UsdaError as exc:
        return [], {"searched": True, "detail": exc.detail}
    out: list[dict[str, Any]] = []
    for record in records:
        try:
            fdc_id = int(record.get("fdcId"))
        except (TypeError, ValueError):
            continue
        if not 0 < fdc_id <= MAX_ROW_ID or fdc_id in seen:
            continue
        seen.add(fdc_id)
        out.append(usda_food(record, fdc_id))
        if len(out) >= room:
            break
    return out, {"searched": True, "found": len(out)}


def search(call: Call, args: SearchArgs) -> dict[str, Any]:
    found = foods.search_foods(call.conn, call.user.id, q=args.query, limit=args.limit)
    results = [app_food(f) for f in found]
    seen = {int(f["fdc_id"]) for f in found if f["fdc_id"]}
    extra, usda = usda_results(call, args.query, args.limit - len(results), seen)
    results += extra
    result: dict[str, Any] = {"query": args.query, "results": results, "usda": usda}
    if extra:
        result["note"] = ("Results with in_app false come from USDA FoodData Central and are not in the person's food "
                          "list: check_meal cannot use them until the person adds the food in the app.")
    if not results:
        result["note"] = "Nothing matched. Try fewer or simpler words (the app searches every word in the name)."
    return finish(result)


# --------------------------------------------------------------------------- #
# check_meal
# --------------------------------------------------------------------------- #


@dataclass
class Found:
    row: sqlite3.Row
    how: str  # food_id | name | only_match


def _keys(text: str | None) -> list[str]:
    """The words of a name as comparison keys (plural and singular alike: "Apples" and "apple" match)."""
    return [M.word_key(w) for w in M.search_words(text or "")]


def _alternative(food: Mapping[str, Any]) -> dict[str, Any]:
    return {"food_id": food["id"], "name": food["name"], "brand": food["brand"], "serving": food["serving_desc"]}


def _candidates(call: Call, *queries: list[str]) -> list[dict[str, Any]]:
    """The app's search for each word list in turn (each needs every word in the name or brand), merged."""
    out: list[dict[str, Any]] = []
    for words in queries:
        if not words:
            continue
        for food in foods.search_foods(call.conn, call.user.id, q=" ".join(words), limit=SEARCH_CANDIDATES):
            if all(food["id"] != f["id"] for f in out):
                out.append(food)
    return out


def find_food(call: Call, text: str) -> Found | dict[str, Any]:
    """The food the person means, or an ``unresolved`` entry. Certain only when exactly one candidate is named by
    the words (its whole name, or its name before the first comma: "apple" for "Apple, raw, with skin"), or when the
    search finds a single food whose name has every word as a whole word ("white rice": "Rice, white, long-grain,
    cooked"); otherwise the alternatives, to ask, and never a guess."""
    words = M.search_words(text)
    singular = [M.singular(w) for w in words]
    found = _candidates(call, words, singular if singular != words else [])
    partial = False
    if not found and len(words) > 1:  # "grilled chicken breast": try without one word at a time
        partial = True
        found = _candidates(call, *(singular[:skip] + singular[skip + 1:] for skip in range(len(singular))))
    if not found:
        return {"reason": "no_match",
                "question": f'No food in the app matches "{text}". Ask the person for another name for it, or to add it '
                            "in the app (search_foods also shows foods from USDA FoodData Central)."}
    wanted = _keys(text)
    named = [] if partial else [f for f in found if wanted in (_keys(f["name"]), _keys(f["name"].split(",", 1)[0]))]
    if len(named) == 1:
        how, food = "name", named[0]
    elif not partial and len(found) == 1 and set(wanted) <= set(_keys(found[0]["name"]) + _keys(found[0]["brand"])):
        how, food = "only_match", found[0]
    else:
        ordered = named + [f for f in found if f not in named]
        names = "; ".join(f["name"] for f in ordered[:MAX_ALTERNATIVES])
        return {"reason": "several_matches", "alternatives": [_alternative(f) for f in ordered[:MAX_ALTERNATIVES]],
                "question": f'Which food is "{text}"? For example: {names}. Then check again with its food_id.'}
    row = foods.fetch_user_food(call.conn, call.user.id, int(food["id"]))
    if row is None:  # cannot happen for a search hit; never guess
        return {"reason": "no_match", "question": f'Ask the person what "{text}" is.'}
    return Found(row, how)


def item_amount(row: sqlite3.Row, amount_: float | None, unit: str | None) -> tuple[float, float | None] | dict[str, Any]:
    """``(servings, grams)`` for an amount in servings (default 1), grams, or a measure the food lists; or an
    ``unresolved`` entry when the food does not know the measure."""
    serving_desc = row["serving_desc"]
    weight_ok = foods.weight_known(row)
    quantity = 1.0 if amount_ is None else float(amount_)
    wanted = M.normalize_unit(unit)
    units = units_for(serving_desc, weight_ok)
    if wanted in ("", "serving"):
        servings = quantity
    elif not weight_ok:
        return {"reason": "servings_only", "units": units,
                "question": f"This food's values are per serving as prepared ({serving_desc}). How many servings?"}
    elif wanted == "g":
        servings, _ = food_log.resolve_servings(row, None, quantity)
    else:
        per = M.servings_per_unit(unit or "", M.food_measures(serving_desc), row["name"])
        if per is None:
            return {"reason": "unknown_unit", "units": units,
                    "question": f'How much is that in grams, or in servings of {serving_desc}? The app does not '
                                f'convert "{unit}" for this food.'}
        servings = quantity * per
    grams = servings * float(row["serving_g"]) if weight_ok else None
    if servings > MAX_SERVINGS or (grams is not None and grams > MAX_GRAMS):
        return {"reason": "amount_too_large", "question": "That amount looks too large. Ask the person to check it."}
    return servings, grams


def _as_asked(amount_: float | None, unit: str | None) -> str:
    if amount_ is None and not unit:
        return "1 serving"
    quantity = 1.0 if amount_ is None else float(amount_)
    return f"{quantity:g} {unit or ('serving' if quantity == 1 else 'servings')}"


def check_item(call: Call, item: MealItem) -> tuple[dict[str, Any], dict[str, Any]] | dict[str, Any]:
    """``(item view, virtual planned row)`` or an ``unresolved`` entry (with ``food`` filled in)."""
    name_text, parsed_amount, parsed_unit = M.split_amount(item.food)  # "white rice 1 cup" → "white rice", 1, cup
    amount_, unit = item.amount, item.unit
    if amount_ is None and unit is None:  # explicit amount and unit win over words in the food text
        amount_, unit = parsed_amount, parsed_unit
    if item.food_id is not None:
        row = foods.fetch_user_food(call.conn, call.user.id, item.food_id)
        if row is None:  # unknown, or another person's own food: the same answer
            return {"food": item.food, "reason": "unknown_food_id",
                    "question": "That food_id is not in the person's foods. Use search_foods to find the food again."}
        found: Found | dict[str, Any] = Found(row, "food_id")
    else:
        found = find_food(call, name_text or item.food)
    if isinstance(found, dict):
        return {"food": item.food, **found}
    row = found.row
    resolved = item_amount(row, amount_, unit)
    if isinstance(resolved, dict):
        return {"food": item.food, "food_id": int(row["id"]), "name": row["name"], **resolved}
    servings, grams = resolved
    scaled = scale_nutrients(foods.raw_nutrients(row), servings)
    flags = foods.parse_flags(row["flags_json"])
    warnings = food_warnings(scaled, flags, row["kidney_notes"], scope="in this amount")
    purpose = food_log.resolve_purpose(row, None)
    view = {
        "food": item.food,
        "matched": {"food_id": int(row["id"]), "name": row["name"], "brand": row["brand"], "source": row["source"]},
        "how_matched": found.how,
        "amount": {"as_asked": _as_asked(amount_, unit), "servings": round(servings, 3),
                   "grams": None if grams is None else round(grams, 1)},
        "serving": {"description": row["serving_desc"], "grams": round(float(row["serving_g"]), 1)},
        "nutrients": round_nutrients(scaled),
        "warnings": warnings,
        "kidney_rating": kidney_rating(warnings),
        "counted_as_treating_a_low": purpose == food_log.HYPO_PURPOSE,
    }
    virtual = {**scaled, "food_name": row["name"], "status": "planned", "purpose": purpose}
    return view, virtual


def check_meal(call: Call, args: MealArgs) -> dict[str, Any]:
    today = food_log.today_local()
    day = args.date or today
    items: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    virtual: list[dict[str, Any]] = []
    for item in args.items:
        outcome = check_item(call, item)
        if isinstance(outcome, dict):
            unresolved.append(outcome)
            continue
        view, row = outcome
        items.append(view)
        virtual.append({**row, "date": day, "meal": args.meal or NO_MEAL})
    totals = empty_totals()
    missing: dict[str, int] = {}
    for row in virtual:
        add_totals(totals, row)
        count_unknown(missing, row)
    rounded = round_nutrients(totals) if virtual else {key: None for key in NUTRIENT_KEYS}
    result: dict[str, Any] = {
        "date": day,
        "meal": args.meal,
        "saved": False,
        "items": items,
        "unresolved": unresolved,
        "totals": {key: amount(rounded[key], missing.get(key)) for key in NUTRIENT_KEYS} if virtual else None,
    }
    notes = []
    if unresolved:
        notes.append("Ask the person the questions in unresolved, then call check_meal again (with food_id where "
                     "alternatives are listed). Items in unresolved are not in the totals.")
    if virtual:
        profile = get_profile(call.conn, call.user.id)
        window = food_log.fetch_entries(call.conn, call.user.id,
                                        food_log.pattern_window_start(day) if day >= today else day, day)
        day_rows = [r for r in window if r["date"] == day]
        tolerance = food_log.carb_tolerance_for(call.conn, call.request, call.user.id)
        figures = food_log.day_figures(day_rows + virtual, profile, tolerance)
        result["day_with_these_items"] = projected_views(figures)
        result["alerts"] = figures["projected_alerts"]
        result["pattern_alerts"] = food_log.day_pattern_alerts(day, food_log.pattern_inputs(window + virtual, today),
                                                               profile, today)
        notes.append("day_with_these_items counts what is eaten, what is planned and these items as if they were "
                     "planned; alerts say \"If you eat what's planned\" in that sense.")
        if food_log.has_meal_carb_goals(profile):
            if args.meal:
                result["meal_carbohydrate"] = projected_meal_carbs(figures, profile, day_rows, virtual, args.meal)
            else:
                notes.append("Say which meal (breakfast, lunch, dinner or snack) to compare these items with that "
                             "meal's carbohydrate goal.")
    result["notes"] = notes
    return finish(result)


def projected_views(figures: Mapping[str, Any]) -> dict[str, Any]:
    """Every nutrient after eaten + planned + the checked items, judged against its target where one is set."""
    out: dict[str, Any] = {}
    for key in NUTRIENT_KEYS:
        nutrient = NUTRIENT_BY_KEY[key]
        view: dict[str, Any] = {"name": nutrient.label, "unit": nutrient.unit,
                                "total": amount(figures["projected_totals"][key], figures["projected_unknown"].get(key))}
        item = figures["projected_status"].get(key)
        if item is not None:
            view["target"] = target_view(key, item)
            view.update(judged(key, item))
        out[key] = view
    return out


def projected_meal_carbs(figures: Mapping[str, Any], profile: Mapping[str, Any], day_rows: list[Any],
                         virtual: list[Mapping[str, Any]], meal: str) -> dict[str, Any]:
    """The chosen meal's carbohydrate with what is eaten, planned and these items, against its goal; low treatments
    are left out of the goal (they count in the day's totals)."""
    goal = _carb_goals(profile["targets"].get("carbs_per_meal_g"), profile["targets"].get("carbs_per_snack_g")).get(meal)
    in_meal = [r for r in day_rows if r["meal"] == meal] + [r for r in virtual if r["meal"] == meal]
    total = math.fsum(_carbs(r["carbs_g"]) for r in in_meal)
    low = math.fsum(_carbs(r["carbs_g"]) for r in in_meal if r["purpose"] == food_log.HYPO_PURPOSE)
    these = math.fsum(_carbs(r["carbs_g"]) for r in virtual if r["meal"] == meal)
    missing = sum(1 for r in in_meal if r["carbs_g"] is None)
    counted = total - low
    over = meal in {a.get("meal") for a in figures["projected_alerts"] if a.get("meal")}
    return {
        "meal": meal,
        "goal_g": round_value("carbs_g", goal),
        "these_items_g": round_value("carbs_g", these),
        "meal_with_these_items_g": round_value("carbs_g", counted),
        "treating_a_low_g": round_value("carbs_g", low),
        "not_listed_by": missing,
        "left_g": None if goal is None or missing else round_value("carbs_g", max(0.0, goal - counted)),
        "over": over,
        "tolerance_g": figures["carb_tolerance_g"],
    }


# --------------------------------------------------------------------------- #
# safety_check
# --------------------------------------------------------------------------- #

SAY_FIRST = {
    "treat_low_first": (
        "Before anything else, show the person the Treating a low card below, in full. Do not plan food or give "
        "other numbers until they say they have treated the low. Never tell them to wait, or to skip or change a "
        "treatment because of potassium or carbohydrate."
    ),
    "get_help_now": (
        "Before anything else, show the Get help now card below, in full, with its link: the person should call "
        "their emergency number now. Do not plan food or give other numbers in this answer."
    ),
    "none": "No safety rule matched this message. Carry on, and call safety_check again with the next message.",
}
LOW_TOO = (" A low may be part of this: the Treating a low card is included; treat the low first, as the card says, "
           "and never delay it.")


def safety_check(call: Call, args: SafetyArgs) -> dict[str, Any]:
    prefs = guidance_context.load_prefs(call.conn, settings_store(call.request), call.user.id)
    # The Treating a low card the app shows instead of any AI call (note 04 G7), with the person's own grams.
    low = hypo.prefilter(args.message, prefs.hypo_dose_g)
    # Emergency wording: the app's own red-flag rule (note 04 G8), whose words follow the "Call 911 now" list of
    # the handbook page handbook/docs/get-help-now.md (chest pain, breathlessness, fainting or collapse, sudden
    # severe weakness, seizure, new confusion, someone who cannot be woken, signs of a stroke).
    emergency = ai_features.red_flag(args.message)
    base = public_base(call.request, call.request.app.state.settings)
    cards = []
    if emergency:
        cards.append(dict(ai_features.RED_FLAG_CARD))
    if low is not None:
        cards.append(dict(low["card"]))
    for card in cards:
        card["full_url"] = base + str(card.get("url") or "")
    action = "get_help_now" if emergency else "treat_low_first" if low is not None else "none"
    result: dict[str, Any] = {
        "action": action,
        "say_first": SAY_FIRST[action] + (LOW_TOO if emergency and low is not None else ""),
        "matched": {"low": low is not None, "emergency": emergency},
        "cards": cards,
    }
    if emergency:
        result["link"] = GET_HELP_NOW
        result["full_link"] = base + GET_HELP_NOW
    return finish(result)


# --------------------------------------------------------------------------- #
# The tool list
# --------------------------------------------------------------------------- #

_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$",
         "description": "A day as YYYY-MM-DD. Leave it out for today (the server's date)."}
ANNOTATIONS = {"readOnlyHint": True, "openWorldHint": False}


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    args: type[_Args]
    run: Callable[[Call, Any], dict[str, Any]]

    def listing(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": self.input_schema, "annotations": {"title": self.title, **ANNOTATIONS}}


TOOLS: tuple[Tool, ...] = (
    Tool(
        "safety_check", "Safety check",
        "Call this first with every message from the person, and follow its action before anything else. Rule-based: "
        "words that may describe a low give action treat_low_first with the app's Treating a low card; emergency "
        "words give get_help_now with the Get help now card and link; otherwise none.",
        {"type": "object", "additionalProperties": False, "required": ["message"],
         "properties": {"message": {"type": "string", "maxLength": 2000,
                                    "description": "The person's message, as they wrote or said it (in parts of up to "
                                                   "2000 characters if longer)."}}},
        SafetyArgs, safety_check,
    ),
    Tool(
        "get_today", "Today's numbers",
        "The person's targets and a day's totals from their food log, exactly as the app's Today screen has them: "
        "eaten, planned, both, what is left of each target, unknown values counted (null means not listed, never "
        "zero), alerts, per-meal carbohydrate goals when the person has diabetes, and dialysis-day totals. Use it for "
        "every number about the day.",
        {"type": "object", "additionalProperties": False, "properties": {"date": _DATE}},
        TodayArgs, get_today,
    ),
    Tool(
        "search_foods", "Search foods",
        "Search the person's own foods and the app's food list, then USDA FoodData Central when the server has a "
        "key. Values are per serving; null means the food does not list it (unknown, not zero). Each result lists "
        "the units check_meal accepts for it.",
        {"type": "object", "additionalProperties": False, "required": ["query"],
         "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 100,
                                  "description": "Food words, for example \"white rice\"."},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}}},
        SearchArgs, search,
    ),
    Tool(
        "check_meal", "Check a meal",
        "Check foods before they are eaten: the app finds each item, scales it to the amount, and returns values and "
        "warnings per item, the totals, and the person's day as if the items were planned (with alerts). Nothing is "
        "saved. Items the app cannot place come back in unresolved with a question to ask the person.",
        {"type": "object", "additionalProperties": False, "required": ["items"],
         "properties": {
             "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                 "type": "object", "additionalProperties": False, "required": ["food"],
                 "properties": {
                     "food": {"type": "string", "minLength": 1, "maxLength": 100,
                              "description": "The food as the person named it, for example \"white rice\"."},
                     "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_GRAMS,
                                "description": "How much, in unit. Default 1."},
                     "unit": {"type": "string", "minLength": 1, "maxLength": 40,
                              "description": "\"serving\" (default), \"g\", or a measure the food lists, such as "
                                             "\"cup\" or \"slice\" (see units in search_foods)."},
                     "food_id": {"type": "integer", "minimum": 1,
                                 "description": "A food_id from search_foods or from check_meal's alternatives; it "
                                                "wins over food."}}}},
             "date": _DATE,
             "meal": {"type": "string", "enum": list(MEALS)}}},
        MealArgs, check_meal,
    ),
)
TOOLS_BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def run(tool: Tool, call: Call, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Validate ``arguments`` and run the tool; raises :class:`ToolError` with a short, safe message."""
    try:
        args = tool.args.model_validate(dict(arguments))
    except ValidationError as exc:
        raise ToolError(describe(exc)) from None
    return tool.run(call, args)
