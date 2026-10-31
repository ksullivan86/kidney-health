"""The assistant's tools (``docs/dev/plans/assistant-step1.md`` parts B and C; ARCHITECTURE.md "Assistant MCP
server"): four read-only ones and, for a token that also has ``assistant:log``, two that save. Each answers one
JSON object, sent as ``structuredContent`` and as text. A seventh, ``set_food_preference``, is for a token with the separate
``assistant:prefs`` scope; it needs Ask's own checks, so it lives in :mod:`app.mcp.preference_tool` and
:func:`app.mcp.server.all_tools` puts the list together (:attr:`Tool.needs` says which scope a tool needs).

Every number comes from the app's own functions, never from a copy of the maths:

* ``get_today``: :func:`app.log.day_summary`, the function behind ``GET /api/log?date=`` (Today), so the numbers
  are Today's; dialysis totals from the period summary's :func:`app.periods.interdialytic_block`.
* ``search_foods``: :func:`app.foods.search_foods` (the person's foods and the built-in list), then FoodData
  Central through the app's own key resolution and record mapping (:func:`app.foods.map_usda_record`); nothing
  is saved.
* ``check_meal``: the item is found in the app, scaled like a log entry (:func:`app.nutrients.scale_nutrients`),
  warned about with :func:`app.rules_kidney.food_warnings`, and the day is projected with
  :func:`app.log.day_figures` as if the items were planned entries. Nothing is saved.
* ``log_food`` (writes): the items are placed exactly as ``check_meal`` places them, then saved through
  :func:`app.log.insert_logged`, the function behind ``POST /api/log`` and ``/api/log/batch``, in one transaction
  with the USDA foods they need (:func:`app.foods.add_usda_food`, the code behind the USDA import route). If any
  item is unresolved nothing is saved.
* ``save_recipe`` (writes): the ingredients are placed the same way and saved as a saved meal
  (:func:`app.meals.insert_template`): the ingredients are for the whole recipe, ``servings_made`` says how many
  servings they make, and the source link is kept as text in ``source_url`` (never fetched; schema step 21).
* Both take an optional ``request_key``: a retry with the same key by the same token within 24 hours saves nothing
  and answers with what the first call saved (:mod:`app.mcp.request_keys`).
* ``safety_check``: the app's rule-based pre-filters: :func:`app.guidance.hypo.prefilter` (the Treating a low
  card with the person's own ``hypo_dose_g``) and :func:`app.ai.features.red_flag` (Get help now).

Unknown stays unknown: a value a food does not list is ``null``, and every total says how many items or entries
it misses (``not_listed_by``); a total that is all unknown is ``null``, never 0. No tool returns insulin or
medicine doses, medicine advice or lab interpretation, and nothing here ever delays or warns against treating a low
(``log_food`` takes ``purpose: "hypo"`` for food eaten to treat a low and saves it like any other entry).
"""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from typing import Any, Callable, Literal, Mapping

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..brand import LOGGER_NAME, MCP_SOURCE  # the names, not the module: ``brand`` is a food's field here
from .. import foods, meals
from .. import log as food_log
from ..ai import features as ai_features
from ..audit import audit
from ..auth import api_tokens
from ..auth.accounts import begin_immediate
from ..auth.context import public_base, request_ip
from ..auth.errors import ApiProblem
from ..auth.models import User
from ..guidance import context as guidance_context
from ..guidance import hypo
from ..models import MAX_GRAMS, MAX_RECIPE_SERVINGS, MAX_SERVINGS, SOURCE_URL_MAX, LogCreate, check_source_url, validate_date
from ..nutrients import (MEALS, NUTRIENT_BY_KEY, NUTRIENT_KEYS, _carb_goals, _status_word, add_totals,
                         count_unknown, empty_totals, food_warnings, is_about, kidney_rating, round_nutrients,
                         round_value, scale_nutrients)
from ..periods import (MAX_INTERDIALYTIC_DAYS, NOTE_CAPPED, NOTE_INTERDIALYTIC, NOTE_NO_DIALYSIS_DAYS, WEEKDAY_NAMES,
                       interdialytic_block, interdialytic_interval)
from ..profile import get_profile, settings_store
from ..textclean import clean_label
from . import measures as M
from . import request_keys

logger = logging.getLogger(f"{LOGGER_NAME}.mcp")

SOURCE = MCP_SOURCE
REMINDER = "Numbers come from the app; fetch them again after any change."
MAX_ROW_ID = 2**63 - 1
GET_HELP_NOW = "/learn/get-help-now/"
# check_meal: candidates read per item, alternatives offered when the match is not certain, and the longest phrase
# tried again without one of its words (one search per word, so it stays short).
SEARCH_CANDIDATES = 8
MAX_ALTERNATIVES = 5
MAX_PARTIAL_WORDS = 6
# A planned item with no meal: counted in the day's totals, compared with no meal's carbohydrate goal
# (app.nutrients judges per-meal carbohydrate for breakfast, lunch, dinner and snack only).
NO_MEAL = "unassigned"


class ToolError(Exception):
    """A short, safe message for the model (an ``isError`` result)."""


ASK_VIA = "Ask"


@dataclass(frozen=True)
class Asker:
    """The in-app Ask chat saving for the person (assistant step 2, part C): no token, so its saves are audited as
    ``via: "Ask"`` (never a token name) and its duplicate keys live in ``assistant_ask_keys``. Quacks like the token
    info the saving tools read (``id`` None, ``name``)."""

    id: None = None
    name: str = ASK_VIA


@dataclass(frozen=True)
class Call:
    request: Request
    conn: sqlite3.Connection
    user: User
    asker: Asker | None = None  # set only by the Ask chat, for log_food and save_recipe


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
    fdc_id: int | None = Field(default=None, ge=1, le=MAX_ROW_ID)  # a USDA food from search_foods (in_app false)


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
        "units": units_for(mapped["serving_desc"], True),
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
        try:
            out.append(usda_food(record, fdc_id))
        except (TypeError, ValueError, KeyError, AttributeError):  # one odd record never costs the other results
            logger.warning("assistant search: USDA record %d could not be mapped; skipped", fdc_id)
            continue
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
                          "list yet: give their fdc_id (not a food_id) to check_meal, log_food or save_recipe. "
                          "check_meal only reads them; log_food and save_recipe add the food to the person's list "
                          "when they save.")
    if not results:
        result["note"] = "Nothing matched. Try fewer or simpler words (the app searches every word in the name)."
    return finish(result)


# --------------------------------------------------------------------------- #
# check_meal
# --------------------------------------------------------------------------- #


@dataclass
class Found:
    row: Mapping[str, Any]  # a foods row; for a USDA food not in the person's list yet, its unsaved twin (id None)
    how: str  # food_id | fdc_id | name | only_match
    mapped: foods.UsdaMapped | None = None  # set with an unsaved USDA row: what an import would store


def _keys(text: str | None) -> list[str]:
    """The words of a name as comparison keys (plural and singular alike: "Apples" and "apple" match)."""
    return [M.word_key(w) for w in M.search_words(text or "")]


def _parts(name: str) -> list[str]:
    return [p.strip() for p in (name or "").split(",") if p.strip()]


def _named_as(name: str) -> list[list[str]]:
    """What a food is called, as keys: a name without a comma as it is; a "Noun, kind, …" name of the food lists by
    its first part ("Apple" in "Apple, raw, with skin") or its two first parts the natural way round ("Juice,
    apple" is apple juice, "Milk, whole" whole milk). The order counts: "Chocolate, milk" is milk chocolate, never
    "chocolate milk"."""
    parts = _parts(name)
    if len(parts) <= 1:
        return [_keys(name)]
    return [_keys(parts[0]), _keys(parts[1] + " " + parts[0])]


def _word_orders(food: Mapping[str, Any]) -> list[list[str]]:
    """The name's words in the order a person says them: the natural way round ("white rice long-grain cooked" for
    "Rice, white, long-grain, cooked"; a name without a comma as written), alone or with the brand before or after.
    Never a comma name as written: "Chocolate, milk" read left to right would be "chocolate milk"."""
    parts = _parts(food["name"])
    natural, brand = _keys(" ".join(parts[1:2] + parts[:1] + parts[2:])), _keys(food["brand"])
    return [natural, brand + natural, natural + brand]


def _in_order(wanted: list[str], keys: list[str]) -> bool:
    """Every wanted word is a word of ``keys``, in the same order (others may come between)."""
    rest = iter(keys)
    return bool(wanted) and all(any(word == key for key in rest) for word in wanted)


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
    the words (:func:`_named_as`: "apple" for "Apple, raw, with skin", "apple juice" for "Juice, apple"), or when
    the search finds a single food that has every word, whole and in order (:func:`_word_orders`: "chicken" for
    "Chicken breast, roasted"); otherwise the alternatives, to ask, and never a guess."""
    words = M.search_words(text)
    singular = [M.singular(w) for w in words]
    found = _candidates(call, words, singular if singular != words else [])
    partial = False
    if not found and 1 < len(words) <= MAX_PARTIAL_WORDS:  # "grilled chicken breast": try without one word at a time
        partial = True
        found = _candidates(call, *(singular[:skip] + singular[skip + 1:] for skip in range(len(singular))))
    if not found:
        return {"reason": "no_match",
                "question": f'No food in the app matches "{text}". Ask the person for another name for it, or to add it '
                            "in the app (search_foods also shows foods from USDA FoodData Central)."}
    wanted = _keys(text)
    typed = [_keys(p) for p in _parts(text)]  # the exact name, commas and all ("Juice, apple" from search_foods)
    named = [] if partial else [f for f in found
                                if wanted in _named_as(f["name"]) or typed == [_keys(p) for p in _parts(f["name"])]]
    if len(named) == 1:
        how, food = "name", named[0]
    elif not partial and len(found) == 1 and any(_in_order(wanted, order) for order in _word_orders(found[0])):
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


UsdaCache = dict[int, "Found | dict[str, Any]"]


def usda_found(call: Call, fdc_id: int, cache: UsdaCache) -> Found | dict[str, Any]:
    """A USDA food named by its ``fdc_id`` (the id ``search_foods`` shows for a result with ``in_app`` false): the
    person's own copy when it is in their list already, else FoodData Central's record, mapped as an import maps
    it but not saved here (``log_food`` and ``save_recipe`` add it to the list when they save; ``check_meal`` never
    saves). A failed lookup is an ``unresolved`` entry with the reason."""
    if fdc_id in cache:
        return cache[fdc_id]
    found: Found | dict[str, Any]
    row = foods.fetch_user_usda_food(call.conn, call.user.id, fdc_id)
    if row is not None:
        found = Found(row, "fdc_id")
    else:
        found = usda_unsaved(call, fdc_id)
    cache[fdc_id] = found
    return found


def usda_unsaved(call: Call, fdc_id: int) -> Found | dict[str, Any]:
    try:
        cred = foods.usda_credential(call.request, call.conn, call.user.id, call.user.can_use_shared)
    except ApiProblem as exc:  # no key, not shared with this person, quota used up, paused near the hourly limit
        return {"reason": "usda_unavailable",
                "question": f"{exc.detail} Ask the person to add this food in the app, or to choose another food."}
    try:
        mapped = foods.usda_record(fdc_id, cred.api_key, guard=foods.guard_id(cred, call.user.id),
                                   own_key=cred.scope == "own")
        return Found(foods.usda_unsaved_row(fdc_id, mapped), "fdc_id", mapped)
    except foods.UsdaError as exc:
        if exc.status == 404:
            return {"reason": "unknown_fdc_id",
                    "question": "USDA has no food with that fdc_id. Use search_foods to find the food again."}
        return {"reason": "usda_unavailable",
                "question": f"USDA FoodData Central did not answer ({exc.detail}). Try again in a moment, or ask the "
                            "person to add the food in the app."}
    except (TypeError, ValueError, KeyError, AttributeError):  # one odd record never costs the other items
        logger.warning("assistant: USDA record %d could not be mapped", fdc_id)
        return {"reason": "usda_unavailable",
                "question": "That USDA record could not be read. Ask the person to choose another food."}


@dataclass
class Placed:
    """An item the app found and sized: the food, how it was found, and the amount as the log stores it."""

    item: MealItem
    row: Mapping[str, Any]  # a foods row, or (``mapped`` set) the unsaved twin of a USDA food not in the list yet
    how: str
    servings: float
    grams: float | None
    by_grams: bool  # the amount was given in grams, so the entry keeps them (as the log API does)
    quantity: float  # the amount as asked, in ``unit`` (1 when none was given)
    amount_: float | None
    unit: str | None
    mapped: foods.UsdaMapped | None = None

    @property
    def food_id(self) -> int | None:
        return None if self.row["id"] is None else int(self.row["id"])


def place_item(call: Call, item: MealItem, cache: UsdaCache) -> Placed | dict[str, Any]:
    """Find the food and size the amount (the part ``check_meal``, ``log_food`` and ``save_recipe`` share), or an
    ``unresolved`` entry (with ``food`` filled in) saying what to ask the person. Saves nothing."""
    name_text, parsed_amount, parsed_unit = M.split_amount(item.food)  # "white rice 1 cup" → "white rice", 1, cup
    amount_, unit = item.amount, item.unit
    if amount_ is None and unit is None:  # explicit amount and unit win over words in the food text
        amount_, unit = parsed_amount, parsed_unit
    found: Found | dict[str, Any]
    if item.food_id is not None:
        row = foods.fetch_user_food(call.conn, call.user.id, item.food_id)
        if row is None:  # unknown, or another person's own food: the same answer
            return {"food": item.food, "reason": "unknown_food_id",
                    "question": "That food_id is not in the person's foods. Use search_foods to find the food again."}
        found = Found(row, "food_id")
    elif item.fdc_id is not None:
        found = usda_found(call, item.fdc_id, cache)
    else:
        found = find_food(call, name_text or item.food)
    if isinstance(found, dict):
        return {"food": item.food, **found}
    row = found.row
    resolved = item_amount(row, amount_, unit)
    if isinstance(resolved, dict):
        return {"food": item.food, "food_id": None if row["id"] is None else int(row["id"]), "name": row["name"],
                **resolved}
    servings, grams = resolved
    by_grams = M.normalize_unit(unit) == "g" and foods.weight_known(row)
    quantity = 1.0 if amount_ is None else float(amount_)
    return Placed(item, row, found.how, servings, grams, by_grams, quantity, amount_, unit, found.mapped)


def place_items(call: Call, items: list[MealItem]) -> tuple[list[Placed], list[dict[str, Any]]]:
    """Every item placed or listed as unresolved, in the order given (a USDA food named twice is fetched once)."""
    cache: UsdaCache = {}
    placed: list[Placed] = []
    unresolved: list[dict[str, Any]] = []
    for item in items:
        outcome = place_item(call, item, cache)
        if isinstance(outcome, dict):
            unresolved.append(outcome)
        else:
            placed.append(outcome)
    return placed, unresolved


def check_item(call: Call, placed: Placed) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(item view, virtual planned row)`` for a placed item."""
    row = placed.row
    scaled = scale_nutrients(foods.raw_nutrients(row), placed.servings)
    flags = foods.parse_flags(row["flags_json"])
    warnings = food_warnings(scaled, flags, row["kidney_notes"], scope="in this amount")
    purpose = food_log.resolve_purpose(row, None)
    view = {
        "food": placed.item.food,
        "matched": {"food_id": placed.food_id, "name": row["name"], "brand": row["brand"], "source": row["source"],
                    "in_app": placed.food_id is not None},
        "how_matched": placed.how,
        "amount": {"as_asked": _as_asked(placed.amount_, placed.unit), "servings": round(placed.servings, 3),
                   "grams": None if placed.grams is None else round(placed.grams, 1)},
        "serving": {"description": row["serving_desc"], "grams": round(float(row["serving_g"]), 1)},
        "nutrients": round_nutrients(scaled),
        "warnings": warnings,
        "kidney_rating": kidney_rating(warnings),
        "counted_as_treating_a_low": purpose == food_log.HYPO_PURPOSE,
    }
    if placed.mapped is not None:
        view["matched"]["fdc_id"] = row["fdc_id"]
        view["note"] = ("A USDA food that is not in the person's food list yet; nothing was added. log_food and "
                        "save_recipe add it to the list when they save.")
    virtual = {**scaled, "food_name": row["name"], "status": "planned", "purpose": purpose}
    return view, virtual


def check_meal(call: Call, args: MealArgs) -> dict[str, Any]:
    today = food_log.today_local()
    day = args.date or today
    items: list[dict[str, Any]] = []
    virtual: list[dict[str, Any]] = []
    placed, unresolved = place_items(call, args.items)
    for one in placed:
        view, row = check_item(call, one)
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
# log_food and save_recipe (a token with the assistant:log scope)
# --------------------------------------------------------------------------- #

READ_ONLY = ("This token can only read. The person can make a token that can also save in Settings → Outside AI "
             "apps.")
RECIPE_NAME_MAX = 60


class LogArgs(_Args):
    items: list[MealItem] = Field(min_length=1, max_length=20)
    meal: Literal["breakfast", "lunch", "dinner", "snack"]
    date: str | None = None
    status: Literal["planned", "eaten"] = "eaten"
    purpose: Literal["hypo", "none"] | None = None  # the log API's purposes: "hypo" = eaten to treat a low
    request_key: str | None = Field(default=None, min_length=request_keys.KEY_MIN, max_length=request_keys.KEY_MAX,
                                    pattern=request_keys.KEY_PATTERN)

    check_date = field_validator("date")(_check_date)


class RecipeArgs(_Args):
    name: str = Field(min_length=1, max_length=RECIPE_NAME_MAX)
    ingredients: list[MealItem] = Field(min_length=1, max_length=30)
    servings: float = Field(gt=0, le=MAX_RECIPE_SERVINGS, allow_inf_nan=False)
    source_url: str | None = Field(default=None, min_length=1, max_length=SOURCE_URL_MAX)
    request_key: str | None = Field(default=None, min_length=request_keys.KEY_MIN, max_length=request_keys.KEY_MAX,
                                    pattern=request_keys.KEY_PATTERN)

    check_url = field_validator("source_url")(check_source_url)


def token_info(call: Call) -> api_tokens.TokenInfo | Asker:
    return call.asker if call.asker is not None else call.request.state.api_token


def audit_target(token: api_tokens.TokenInfo | Asker) -> tuple[str | None, int | None]:
    """What a food-log activity row points at: the token that saved; the Ask chat has none (the row says ``via: Ask``)."""
    return ("api_token", token.id) if token.id is not None else (None, None)


def write_once(call: Call, placed: list[Placed], body: Callable[[list[dict[str, Any]]], Any]) -> Any:
    """Run ``body`` in one write transaction, all or nothing. First the USDA foods the items need are added to the
    person's food list (:func:`app.foods.add_usda_food`, the import route's code) and the items point at the saved
    rows; ``body(added)`` then saves and audits. Any failure rolls the food additions back too."""
    conn = call.conn
    try:
        begin_immediate(conn)
        food_ids: dict[int, int] = {}
        added: list[dict[str, Any]] = []
        for one in placed:
            if one.mapped is None:
                continue
            fdc_id = int(one.row["fdc_id"])
            if fdc_id not in food_ids:
                food_ids[fdc_id] = foods.add_usda_food(conn, call.user.id, fdc_id, one.mapped)
                added.append({"food_id": food_ids[fdc_id], "fdc_id": fdc_id, "name": one.row["name"]})
            one.row = foods.fetch_user_food(conn, call.user.id, food_ids[fdc_id])
            one.mapped = None
        result = body(added)
        conn.commit()
        return result
    except HTTPException as exc:  # the log or meals code refusing an item: say why, save nothing
        conn.rollback()
        raise ToolError(str(exc.detail)) from None
    except ValidationError as exc:
        conn.rollback()
        raise ToolError(describe(exc)) from None
    except BaseException:
        conn.rollback()
        raise


def saved_totals(rows: list[Mapping[str, Any]], divisor: float = 1.0) -> dict[str, Any]:
    """Totals of ``rows`` (each with the 12 nutrient keys) divided by ``divisor``, with how many rows miss each."""
    totals = empty_totals()
    missing: dict[str, int] = {}
    for row in rows:
        add_totals(totals, row)
        count_unknown(missing, row)
    rounded = round_nutrients({key: value / divisor for key, value in totals.items()})
    return {key: amount(rounded[key], missing.get(key)) for key in NUTRIENT_KEYS}


def unresolved_result(unresolved: list[dict[str, Any]], what: str, **fields: Any) -> dict[str, Any]:
    return finish({
        "saved": False, **fields, "unresolved": unresolved,
        "notes": [f"Nothing was saved, not even the items the app did find. Ask the person the questions in unresolved, "
                  f"then call {what} again with all the items (food_id, or fdc_id for a USDA food, where "
                  "alternatives are listed)."],
    })


class AlreadySaved(Exception):
    """A retry whose ``request_key`` an earlier call already used: raised inside the save's transaction (which is
    rolled back, so nothing is added) when the first call finished while this one was waiting to save."""

    def __init__(self, seen: request_keys.Seen) -> None:
        super().__init__("request_key already used")
        self.seen = seen


def earlier_save(call: Call, tool: str, key: str | None) -> request_keys.Seen | None:
    """What this token already saved with ``key`` in the last 24 hours (a retry), or None. The same key on the other
    saving tool is a mistake of the model's, not a retry: it is refused so nothing is mixed up."""
    if key is None:
        return None
    seen = request_keys.find(call.conn, call.user.id, token_info(call).id, key)
    if seen is not None and seen.tool != tool:
        raise ToolError(f"That request_key was already used by {seen.tool}. Send a new request_key for each save you "
                        "intend, and reuse one only to retry the same save.")
    return seen


def retry_note(what: str) -> str:
    return (f"A call with this request_key already saved {what}, so nothing was saved again; this is what that call "
            "saved, read from the app now. Tell the person what was saved. If this was a different save, call the "
            "tool again with a new request_key.")


def log_food(call: Call, args: LogArgs) -> dict[str, Any]:
    key = args.request_key
    seen = earlier_save(call, "log_food", key)
    if seen is not None:
        return logged_again(call, seen)
    day = args.date or food_log.today_local()
    placed, unresolved = place_items(call, args.items)
    if unresolved:
        return unresolved_result(unresolved, "log_food", date=day, meal=args.meal, status=args.status)
    token = token_info(call)

    added_foods: list[dict[str, Any]] = []

    def save(added: list[dict[str, Any]]) -> list[sqlite3.Row]:
        again = earlier_save(call, "log_food", key)  # now inside the write lock: a retry that raced the first call
        if again is not None:
            raise AlreadySaved(again)
        added_foods.extend(added)
        ids = []
        for one in placed:
            create = LogCreate(
                date=day, meal=args.meal, food_id=one.food_id, status=args.status, purpose=args.purpose,
                servings=None if one.by_grams else one.servings, grams=one.quantity if one.by_grams else None)
            ids.append(food_log.insert_logged(call.conn, call.user.id, create))
        target_type, target_id = audit_target(token)
        audit(call.conn, call.user.id, "assistant.food_logged", target_type, target_id, ip=request_ip(call.request),
              via=token.name, entries=len(ids), status=args.status, meal=args.meal, date=day, foods_added=len(added))
        if key is not None:
            request_keys.remember(call.conn, call.user.id, token.id, "log_food", key,
                                  {"entry_ids": ids, "added_to_foods": added})
        return [food_log.fetch_entry(call.conn, call.user.id, entry_id) for entry_id in ids]

    try:
        rows = write_once(call, placed, save)
    except AlreadySaved as again:
        return logged_again(call, again.seen)
    return logged_answer(call, rows, added_foods)


def logged_again(call: Call, seen: request_keys.Seen) -> dict[str, Any]:
    """The answer to a retry of ``log_food``: the first call's entries as they are in the log now (an entry the person
    deleted since is not listed, and a note says so). Nothing is saved."""
    ids = [int(i) for i in seen.saved.get("entry_ids", [])]
    rows = [row for row in (food_log.fetch_entry(call.conn, call.user.id, i) for i in ids) if row is not None]
    gone = len(ids) - len(rows)
    if not rows:
        return finish({
            "saved": False, "duplicate": True, "entries": [],
            "notes": ["A call with this request_key already saved these entries, but none of them is in the log now "
                      "(the person deleted them), so nothing was saved again. Tell the person; if they still want "
                      "the food logged, call log_food again with a new request_key."]})
    notes = [retry_note("these entries")]
    if gone:
        notes.append(f"{gone} of the {len(ids)} entries that call saved {'is' if gone == 1 else 'are'} not in the log "
                     "now (the person deleted them); only those still there are listed.")
    return logged_answer(call, rows, still_in_foods(call, seen), notes, duplicate=True)


def still_in_foods(call: Call, seen: request_keys.Seen) -> list[dict[str, Any]]:
    """The foods the first call added to the person's list that are still in it."""
    return [a for a in seen.saved.get("added_to_foods", [])
            if foods.fetch_user_food(call.conn, call.user.id, int(a["food_id"])) is not None]


def logged_answer(call: Call, rows: list[sqlite3.Row], added_foods: list[dict[str, Any]],
                  notes: list[str] | None = None, *, duplicate: bool = False) -> dict[str, Any]:
    """The answer of ``log_food``: the entries, their totals and the day's figures read after saving."""
    entries = [saved_entry(food_log.row_to_entry(row)) for row in rows]
    first = entries[0]
    notes = [*(notes or []),
             "Tell the person what was saved: the entries, with amounts. Numbers in day are the app's, read after saving."]
    if any(e["counted_as_treating_a_low"] for e in entries):
        notes.append("Entries marked as treating a low count in the day's totals but never toward a meal's "
                     "carbohydrate goal.")
    result: dict[str, Any] = {
        "saved": True, **({"duplicate": True} if duplicate else {}),
        "date": first["date"], "meal": first["meal"], "status": first["status"],
        "entries": entries, "added_to_foods": added_foods,
        "totals": saved_totals([foods.raw_nutrients(row) for row in rows]),
    }
    try:  # the entries are saved already: a failure here must not look like a failed save
        figures = get_today(call, TodayArgs(date=first["date"]))
        figures.pop("source", None)
        figures.pop("reminder", None)
        result["day"] = figures
    except Exception:  # noqa: BLE001
        logger.exception("assistant log_food: the day's figures could not be read after saving")
        result["day"] = None
        notes.append("The entries are saved, but the day's figures could not be read just now: call get_today.")
    result["notes"] = notes
    return finish(result)


def saved_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """What the assistant is told about an entry it saved: no warnings (a food eaten to treat a low is never
    warned about) and unknown nutrients as null."""
    return {
        "entry_id": entry["id"], "date": entry["date"], "meal": entry["meal"], "status": entry["status"],
        "food_id": entry["food_id"], "food_name": entry["food_name"], "servings": entry["servings"],
        "grams": entry["grams"], "nutrients": entry["nutrients"], "purpose": entry["purpose"],
        "counted_as_treating_a_low": entry["purpose"] == food_log.HYPO_PURPOSE,
    }


def save_recipe(call: Call, args: RecipeArgs) -> dict[str, Any]:
    key = args.request_key
    seen = earlier_save(call, "save_recipe", key)
    if seen is not None:
        return recipe_again(call, seen)
    name = clean_label(args.name, max_len=RECIPE_NAME_MAX)
    if name is None:
        raise ToolError("Give the recipe a name.")
    placed, unresolved = place_items(call, args.ingredients)
    if unresolved:
        return unresolved_result(unresolved, "save_recipe", name=name)
    token = token_info(call)
    added_foods: list[dict[str, Any]] = []

    def save(added: list[dict[str, Any]]) -> int:
        again = earlier_save(call, "save_recipe", key)  # now inside the write lock: a retry that raced the first call
        if again is not None:
            raise AlreadySaved(again)
        added_foods.extend(added)
        items = [{"food_id": one.food_id, "servings": float(one.servings)} for one in placed]
        meal_id = meals.insert_template(call.conn, user_id=call.user.id, name=name, note=None, items=items,
                                          servings_made=float(args.servings), source_url=args.source_url)
        audit(call.conn, call.user.id, "assistant.recipe_saved", "meal", meal_id, ip=request_ip(call.request),
              via=token.name, name=name, ingredients=len(items), servings=args.servings, foods_added=len(added))
        if key is not None:
            request_keys.remember(call.conn, call.user.id, token.id, "save_recipe", key,
                                  {"meal_id": meal_id, "servings_made": args.servings, "source_url": args.source_url,
                                   "added_to_foods": added})
        return meal_id

    try:
        meal_id = write_once(call, placed, save)
    except AlreadySaved as again:
        return recipe_again(call, again.seen)
    scaled = [scale_nutrients(foods.raw_nutrients(one.row), one.servings) for one in placed]
    return recipe_answer(call, meal_id, scaled, args.servings, args.source_url, added_foods)


def recipe_again(call: Call, seen: request_keys.Seen) -> dict[str, Any]:
    """The answer to a retry of ``save_recipe``: the first call's saved meal as it is now (if the person deleted it
    since, a note says so). Nothing is saved."""
    row = meals.fetch_template(call.conn, call.user.id, int(seen.saved.get("meal_id", 0)))
    if row is None:
        return finish({
            "saved": False, "duplicate": True,
            "notes": ["A call with this request_key already saved this recipe, but the saved meal is not in the app "
                      "now (the person deleted it), so nothing was saved again. Tell the person; if they still want "
                      "it, call save_recipe again with a new request_key."]})
    built = (meals.build_item(call.conn, raw) for raw in meals.parse_items(row["items_json"]))
    scaled = [figures for _, figures in built if figures is not None]
    return recipe_answer(call, int(row["id"]), scaled, float(seen.saved.get("servings_made") or 1),
                         seen.saved.get("source_url"), still_in_foods(call, seen), [retry_note("this recipe")],
                         duplicate=True)


def recipe_answer(call: Call, meal_id: int, scaled: list[dict[str, float | None]], servings: float,
                  source_url: str | None, added_foods: list[dict[str, Any]], notes: list[str] | None = None, *,
                  duplicate: bool = False) -> dict[str, Any]:
    """The answer of ``save_recipe``: the saved meal (read from the database) and its totals."""
    saved = meals.row_to_template(call.conn, meals.fetch_template(call.conn, call.user.id, meal_id))
    return finish({
        "saved": True, **({"duplicate": True} if duplicate else {}),
        "meal": {
            "id": saved["id"], "name": saved["name"], "note": saved["note"], "servings_made": saved["servings_made"],
            "source_url": saved["source_url"],
            "items": [{"food_id": i["food_id"], "food_name": i["food_name"], "servings": i["servings"],
                       "serving_desc": i["serving_desc"], "nutrients": i["nutrients"]} for i in saved["items"]],
        },
        "servings_made": servings,
        "source_url": source_url,
        "totals_whole_recipe": saved_totals(scaled),
        "totals_per_serving": saved_totals(scaled, servings),
        "added_to_foods": added_foods,
        "notes": [*(notes or []),
                  "The saved meal holds the ingredients for the whole recipe, how many servings they make and the "
                  "source link. Tell the person what was saved."],
    })


# --------------------------------------------------------------------------- #
# The tool list
# --------------------------------------------------------------------------- #

_DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$",
         "description": "A day as YYYY-MM-DD. Leave it out for today (the server's date)."}
ANNOTATIONS = {"readOnlyHint": True, "openWorldHint": False}
# Tools that save: not read-only, they only add (never delete or overwrite), a repeat adds again (unless it carries
# the same request_key as the first call), and they reach no outside service for the model (a USDA lookup is the
# app's own).
WRITE_ANNOTATIONS = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    args: type[BaseModel]
    run: Callable[[Call, Any], dict[str, Any]]
    writes: bool = False  # saves something (a failure says "nothing was saved")
    # The token scope listing and calling the tool need: None means assistant:log for a tool that saves food or a recipe
    # (``writes``) and assistant:read for the rest. ``set_food_preference`` (app/mcp/preference_tool.py) needs assistant:prefs.
    scope: str | None = None
    hints: Mapping[str, bool] | None = None  # the annotation hints, when the default for read-only or saving tools is not true

    @property
    def needs(self) -> str:
        return self.scope or (api_tokens.LOG if self.writes else api_tokens.READ)

    def listing(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": self.input_schema,
                "annotations": {"title": self.title, **(self.hints or (WRITE_ANNOTATIONS if self.writes else ANNOTATIONS))}}


# The duplicate guard of the two saving tools (app/mcp/request_keys.py).
RETRY_ADVICE = ("Send a new request_key with each save you mean to make, and send the same one again only to retry "
                "that same save after an error or no answer: a repeat with the same key saves nothing and answers "
                "with what the first call saved.")
_REQUEST_KEY = {
    "type": "string", "minLength": request_keys.KEY_MIN, "maxLength": request_keys.KEY_MAX,
    "pattern": request_keys.KEY_PATTERN,
    "description": "A fresh random string for this save (8 to 64 letters, digits, - or _). Reuse it only to retry "
                   "this same save; a repeat with the same key is not saved twice."}

# An item as check_meal, log_food and save_recipe take it.
_ITEM = {
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
                    "description": "A food_id from search_foods or from the alternatives in unresolved; it wins "
                                   "over food."},
        "fdc_id": {"type": "integer", "minimum": 1,
                   "description": "The fdc_id of a USDA result from search_foods (in_app false), when the person "
                                  "chose that one. log_food and save_recipe add it to the person's food list; "
                                  "check_meal does not."}}}


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
        "the units check_meal accepts for it; a USDA result (in_app false) is used by its fdc_id.",
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
             "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": _ITEM},
             "date": _DATE,
             "meal": {"type": "string", "enum": list(MEALS)}}},
        MealArgs, check_meal,
    ),
    Tool(
        "log_food", "Save food to the log",
        "Save food to the person's food log, only after you read the items back and the person said yes. Items are "
        "placed exactly as in check_meal (name, amount and unit, food_id, or the fdc_id of a USDA result). If any "
        "item is unresolved nothing at all is saved and unresolved says what to ask; otherwise every item is saved "
        "as an entry (eaten, or planned) for that meal and day, and the answer lists what was saved and the day's "
        "figures after saving. Use purpose \"hypo\" for food eaten to treat a low: it is saved like any other and "
        "counts in the day's totals. " + RETRY_ADVICE + " Say what was saved.",
        {"type": "object", "additionalProperties": False, "required": ["items", "meal"],
         "properties": {
             "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": _ITEM},
             "meal": {"type": "string", "enum": list(MEALS)},
             "date": _DATE,
             "status": {"type": "string", "enum": ["eaten", "planned"], "default": "eaten",
                        "description": "\"eaten\" (default) for food already eaten, \"planned\" for food to eat later."},
             "purpose": {"type": "string", "enum": ["hypo", "none"],
                         "description": "\"hypo\" when the food is eaten to treat a low; \"none\" to leave it "
                                        "out for a food the app would otherwise count that way."},
             "request_key": _REQUEST_KEY}},
        LogArgs, log_food, True,
    ),
    Tool(
        "save_recipe", "Save a recipe",
        "Save a recipe as a saved meal, only after you read the name, ingredients and number of servings back and "
        "the person said yes. Ingredients are placed as in check_meal (name, amount and unit, food_id, or the "
        "fdc_id of a USDA result); if any is unresolved nothing is saved and unresolved says what to ask. The saved "
        "meal holds the ingredients for the whole recipe, how many servings they make, and the source link (text; "
        "the app never opens it). The answer gives the totals for the whole recipe and per "
        "serving (null means not listed). " + RETRY_ADVICE + " Say what was saved.",
        {"type": "object", "additionalProperties": False, "required": ["name", "ingredients", "servings"],
         "properties": {
             "name": {"type": "string", "minLength": 1, "maxLength": RECIPE_NAME_MAX},
             "ingredients": {"type": "array", "minItems": 1, "maxItems": 30, "items": _ITEM},
             "servings": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_RECIPE_SERVINGS,
                          "description": "How many servings the whole recipe makes."},
             "source_url": {"type": "string", "minLength": 1, "maxLength": SOURCE_URL_MAX,
                            "description": "An http or https link to where the recipe came from (optional)."},
             "request_key": _REQUEST_KEY}},
        RecipeArgs, save_recipe, True,
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
