"""``/api/guidance`` routes (note 06 §4.10; ARCHITECTURE "M2 API: guidance"). I/O.

Every route needs a signed-in person (``current_user``) and reads only that person's log, foods,
saved meals, profile and preferences (:mod:`app.guidance.context`); a food or entry that is not theirs
answers 404 like one that does not exist. Routes are sync ``def`` (pure Python plus SQLite) and write
nothing except the person's food preferences (``/preferences``, and ``/not-for-me`` as its older alias). Every computed response carries ``rules_version``; ``/api/*``
responses are ``Cache-Control: no-store`` (``app/security.py``).

Two answers instead of a result: ``{"status": "no_targets"}`` when the profile has no numeric
potassium, phosphorus or sodium target and no meal carb goal (§4.2), and ``{"status": "disabled"}``
when an admin switched guidance off (``guidance.enabled``) or the person did (``guidance`` setting).
The low-treatment options and the rules table are always available: knowing what to take for a low
is never switched off.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date as _date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import brand
from ..auth.deps import CurrentUser, current_user
from ..db import get_db, utcnow
from ..foods import WEIGHT_UNKNOWN_DETAIL, fetch_food, fetch_user_food, weight_known
from ..meals import fetch_template, parse_items, recipe_fields
from ..models import MAX_GRAMS, MAX_SERVINGS, MAX_SQLITE_INT, Meal, validate_date
from ..settings_store import SettingsStore, default_store
from . import context as C
from . import insights as I
from . import messages as M
from . import rules as R
from . import topics as T
from .ai_bridge import ai_status
from .fits import learned, what_fits
from .models import (
    FitRecipeRequest,
    FitRecipeResponse,
    DayInsightsResponse,
    GuidanceUnavailable,
    HypoOptionsResponse,
    LearnedList,
    NextMealResponse,
    NotForMeList,
    PeriodInsightsResponse,
    PlanDayRequest,
    PlanDayResponse,
    PreferenceBody,
    PreferenceFood,
    PreferenceList,
    RulesResponse,
    SwapResponse,
)
from .planner import plan_day
from .recipes import Target, fit_recipe, next_open_meal
from .score import Counter
from .state import GuidanceContext
from .swaps import find_swaps, hypo_options

log = logging.getLogger(f"{brand.LOGGER_NAME}.guidance")

router = APIRouter(prefix="/api/guidance", tags=["guidance"], dependencies=[Depends(current_user)])

DISABLED_BY_USER = "Meal guidance is switched off in your settings."
PLAN_OFF = "The plan builder is switched off in your settings."
INSIGHTS_OFF = "Insights are switched off in your settings."
TARGET_KEYS_SHOWN = (R.K, R.P, R.NA, R.FLUID, R.PROTEIN, R.CARBS, "carbs_per_meal_g", "carbs_per_snack_g", R.KCAL)

FoodId = Annotated[int, Query(ge=1, le=MAX_SQLITE_INT)]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def settings_store(request: Request) -> SettingsStore:
    """The app's settings store (a bare router in a test falls back to the default store)."""
    return getattr(request.app.state, "settings_store", None) or default_store()


def foods_json(request: Request) -> Path | None:
    settings = getattr(request.app.state, "settings", None)
    return getattr(settings, "foods_json", None)


def today_local() -> str:
    """The server's local date (the default ``date``, as ``GET /api/log`` uses)."""
    return datetime.now().date().isoformat()


def parse_day(value: str | None, name: str = "date") -> str:
    if value is None or value == "":
        return today_local()
    try:
        return validate_date(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name}: {exc}") from exc


MAX_EXCLUDE = 60  # food ids in "exclude": two or three rounds of "Show other foods"
EXCLUDE_ERROR = f"exclude: a comma list of at most {MAX_EXCLUDE} food ids"


def parse_exclude(value: str | None) -> frozenset[int]:
    """``exclude=12,40,7``: the food ids already shown, so the next answer finds others."""
    if value is None or value == "":
        return frozenset()
    parts = value.split(",")
    if len(value) > 13 * MAX_EXCLUDE or len(parts) > MAX_EXCLUDE or not all(re.fullmatch(r"[0-9]{1,12}", p) for p in parts):
        raise HTTPException(status_code=400, detail=EXCLUDE_ERROR)
    return frozenset(int(p) for p in parts)


RECIPE_UNAVAILABLE = "A food in this recipe is no longer in your food list. Edit the recipe first."


def unavailable(status: str, message: str) -> dict[str, Any]:
    return {"status": status, "rules_version": R.RULES_VERSION, "message": message}


def gate(conn: sqlite3.Connection, store: SettingsStore, user_id: int, feature: str | None = None) -> dict[str, Any] | None:
    """``None`` when guidance may answer, else the ``disabled`` answer (server switch, then the person's)."""
    if not store.get(conn, "guidance.enabled"):
        return unavailable("disabled", M.DISABLED)
    prefs = C.user_settings(conn, store, user_id)
    if not C.setting_value(prefs, "enabled", True):
        return unavailable("disabled", DISABLED_BY_USER)
    if feature == "plan" and not C.setting_value(prefs, "show_plan_builder", True):
        return unavailable("disabled", PLAN_OFF)
    if feature == "insights" and not C.setting_value(prefs, "show_insights", True):
        return unavailable("disabled", INSIGHTS_OFF)
    return None


def targets_used(ctx: GuidanceContext) -> dict[str, Any]:
    t = ctx.profile.targets
    return {"values": {k: t.get(k) for k in TARGET_KEYS_SHOWN if t.get(k) is not None},
            "profile_updated_at": ctx.profile.targets_updated_at}


def load_ctx(request: Request, conn: sqlite3.Connection, user_id: int, day: str,
             options: C.LoadOptions = C.LoadOptions()) -> GuidanceContext:
    return C.load(conn, user_id, day, store=settings_store(request), foods_json=foods_json(request), options=options)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/next-meal", response_model=NextMealResponse | GuidanceUnavailable)
def next_meal(
    request: Request,
    user: CurrentUser,
    meal: Meal,
    date: str | None = None,
    limit: Annotated[int, Query(ge=1, le=R.MAX_LIMIT)] = R.DEFAULT_LIMIT,
    explain: bool = False,
    exclude: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """What fits now (§4.5): foods, saved and usual meals that fit ``meal`` on ``date``; ``exclude`` leaves out foods
    already shown."""
    day = parse_day(date)
    skip = parse_exclude(exclude)
    store = settings_store(request)
    off = gate(conn, store, user.id)
    if off is not None:
        return off
    ctx = load_ctx(request, conn, user.id, day)
    if not C.has_targets(ctx.profile):
        return unavailable("no_targets", M.NO_TARGETS)
    result = what_fits(ctx, meal, limit=limit, explain=explain, exclude=skip)
    result["ai"] = ai_status(conn, user.id)
    result["targets"] = targets_used(ctx)
    return result


@router.get("/swaps", response_model=SwapResponse | GuidanceUnavailable)
def swaps(
    request: Request,
    user: CurrentUser,
    date: str | None = None,
    meal: Meal | None = None,
    food_id: Annotated[int | None, Query(ge=1, le=MAX_SQLITE_INT)] = None,
    servings: Annotated[float | None, Query(gt=0, le=MAX_SERVINGS, allow_inf_nan=False)] = None,
    grams: Annotated[float | None, Query(gt=0, le=MAX_GRAMS, allow_inf_nan=False)] = None,
    entry_id: Annotated[int | None, Query(ge=1, le=MAX_SQLITE_INT)] = None,
    purpose: Literal["hypo", "none"] | None = None,
    explain: bool = False,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Swap ideas (§4.6) for a food and amount before saving (``food_id`` + ``servings`` or ``grams``,
    with ``date`` and ``meal``) or for a saved entry (``entry_id``). ``purpose=hypo`` (the default for a
    low-treatment food, as when logging) asks only for other low treatments at the full amount;
    ``purpose=none`` treats it as food."""
    if (food_id is None) == (entry_id is None):
        raise HTTPException(status_code=400, detail="give either food_id (with servings or grams) or entry_id")
    store = settings_store(request)
    off = gate(conn, store, user.id)
    if off is not None:
        return off
    if entry_id is not None:
        row = C.entry_for_swap(conn, user.id, entry_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"log entry {entry_id} not found")
        day, slot, fid, amount = row["date"], row["meal"], int(row["food_id"]), float(row["servings"])
        stored = "hypo" if row["purpose"] == "hypo" else "none"
        wanted = purpose or stored
    else:
        if meal is None:
            raise HTTPException(status_code=400, detail="meal is required with food_id")
        day, slot, fid = parse_day(date), meal, int(food_id)  # type: ignore[arg-type]
        amount, wanted = 1.0, purpose
    ctx = load_ctx(request, conn, user.id, day, C.LoadOptions(history60=False, saved_meals=True, combos=False))
    food = ctx.foods.get(fid)
    if food is None:
        raise HTTPException(status_code=404, detail=f"food {fid} not found")
    if entry_id is None:
        if grams is not None:
            row = fetch_food(conn, fid)
            if row is not None and not weight_known(row):
                raise HTTPException(status_code=400, detail=WEIGHT_UNKNOWN_DETAIL)
            amount = grams / food.serving_g if food.serving_g > 0 else 1.0
        elif servings is not None:
            amount = servings
        if wanted is None:
            wanted = "hypo" if food.hypo else "none"  # the same default as POST /api/log
    if not C.has_targets(ctx.profile):
        return unavailable("no_targets", M.NO_TARGETS)
    if entry_id is not None:
        ctx = ctx.with_day(tuple(e for e in ctx.day if e.id != entry_id))
    result = find_swaps(ctx, slot, food, amount, wanted, explain=explain)
    if entry_id is not None:
        result["entry_id"] = entry_id
    return result


@router.post("/fit-recipe", response_model=FitRecipeResponse | GuidanceUnavailable)
def fit_a_recipe(body: FitRecipeRequest, request: Request, user: CurrentUser,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Recipes that fit (note 16 §7): one serving of a saved recipe (``meal_id``) or a draft (``items`` and ``servings_made``)
    against a meal's room or what is left today. Lowers amounts, swaps a food or suggests a smaller serving, and lists every
    change. Computes only; the person saves a fitted copy through ``POST /api/meals``."""
    if (body.meal_id is None) == (body.items is None):
        raise HTTPException(status_code=400, detail="give either meal_id or items")
    store = settings_store(request)
    off = gate(conn, store, user.id)
    if off is not None:
        return off
    if body.meal_id is not None:
        row = fetch_template(conn, user.id, body.meal_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"saved meal {body.meal_id} not found")
        wanted = [(int(i["food_id"]), float(i["servings"])) for i in parse_items(row["items_json"])]
        servings_made = recipe_fields(row)[0]
    else:
        wanted = [(i.food_id, i.servings) for i in body.items or []]
        for food_id, _ in wanted:
            if fetch_user_food(conn, user.id, food_id) is None:
                raise HTTPException(status_code=404, detail=f"food {food_id} not found")
        servings_made = body.servings_made
    if len(wanted) > R.RECIPE_MAX_ITEMS:
        raise HTTPException(status_code=400, detail=f"a recipe can have at most {R.RECIPE_MAX_ITEMS} foods")
    day = parse_day(body.target.date)
    ctx = load_ctx(request, conn, user.id, day, C.LoadOptions(history60=False, saved_meals=False, combos=False))
    if not C.has_targets(ctx.profile):
        return unavailable("no_targets", M.NO_TARGETS)
    meal = None if body.target.kind == "day" else (body.target.meal or next_open_meal(ctx))
    head = {"rules_version": R.RULES_VERSION, "target": {"kind": body.target.kind, "meal": meal, "date": day},
            "servings_made": float(servings_made or 1.0)}
    recipe = [(ctx.foods.get(fid), q) for fid, q in wanted]
    if not recipe or any(f is None for f, _ in recipe):
        return {**head, "status": "unavailable", "message": RECIPE_UNAVAILABLE}
    result = fit_recipe(ctx, recipe, servings_made, Target(body.target.kind, meal))  # type: ignore[arg-type]
    return {**head, **result}


@router.get("/hypo-options", response_model=HypoOptionsResponse)
def low_treatment_options(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's low-treatment foods at the amount that treats a low, lowest potassium first, with
    the "Treating a low" card (§4.6). Never filtered by a budget, never switched off, never sent to AI."""
    ctx = load_ctx(request, conn, user.id, today_local(),
                   C.LoadOptions(history=False, history60=False, saved_meals=False, combos=False))
    return hypo_options(ctx)


@router.post("/plan-day", response_model=PlanDayResponse | GuidanceUnavailable)
def plan_the_day(body: PlanDayRequest, request: Request, user: CurrentUser,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Plan the rest of the day (§4.7). Computes only; "Use this plan" sends ``apply.entries`` to
    ``POST /api/log/batch``."""
    store = settings_store(request)
    off = gate(conn, store, user.id, "plan")
    if off is not None:
        return off
    ctx = load_ctx(request, conn, user.id, body.date)
    if not C.has_targets(ctx.profile):
        return unavailable("no_targets", M.NO_TARGETS)
    counter = Counter()
    result = plan_day(ctx, body.meals, use_saved_meals=body.use_saved_meals, use_usual=body.use_usual,
                      use_starters=body.use_starters, variant=body.variant, counter=counter)
    result["targets"] = targets_used(ctx)
    if body.explain:
        result["explain"] = {"evaluations": counter.foods, "meal_evaluations": counter.meals,
                             "pool_per_role": ctx.tunables.pool_per_role, "beam_width": ctx.tunables.beam_width}
    return result


@router.get("/insights/day", response_model=DayInsightsResponse | GuidanceUnavailable)
def insights_day(request: Request, user: CurrentUser, date: str | None = None,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """End-of-day insights (§4.8) from eaten entries; planned ones are counted in ``planned_excluded``."""
    day = parse_day(date)
    off = gate(conn, settings_store(request), user.id, "insights")
    if off is not None:
        return off
    ctx = load_ctx(request, conn, user.id, day, C.LoadOptions(history60=False, saved_meals=False, combos=False))
    if not C.has_targets(ctx.profile):
        return unavailable("no_targets", M.NO_TARGETS)
    return I.day_insights(ctx)


@router.get("/insights/period", response_model=PeriodInsightsResponse | GuidanceUnavailable)
def insights_period(request: Request, user: CurrentUser, start: str | None = None, end: str | None = None,
                    conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Period insights (§4.8): default the 7 days ending yesterday; at most 92 days."""
    start_s = parse_day(start, "start") if start else None
    end_s = parse_day(end, "end") if end else None
    s, e, prev_s, prev_e = I.period_bounds(start_s, end_s, today_local())
    if e < s:
        raise HTTPException(status_code=400, detail="end must not be before start")
    span = (_date.fromisoformat(e) - _date.fromisoformat(s)).days + 1
    if span > R.PERIOD_MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"range too large (max {R.PERIOD_MAX_DAYS} days)")
    off = gate(conn, settings_store(request), user.id, "insights")
    if off is not None:
        return off
    store = settings_store(request)
    profile = C.load_profile(conn, user.id)
    if not C.has_targets(profile):
        return unavailable("no_targets", M.NO_TARGETS)
    prefs = C.load_prefs(conn, store, user.id)
    result = I.period_insights(profile, prefs, s, e, C.load_period(conn, user.id, s, e),
                               C.load_period(conn, user.id, prev_s, prev_e))
    result["previous"] = {"start": prev_s, "end": prev_e}
    return result


@router.get("/rules", response_model=RulesResponse)
def rules() -> dict[str, Any]:
    """Every number of the engine, its version and the handbook pages it links to (for the docs page)."""
    return {
        "rules_version": R.RULES_VERSION,
        "rules_hash": R.rules_hash(),
        "rules": R.rules_table(),
        "notes": R.rule_notes(),
        "topic_pages": T.TOPIC_PAGES,
        "tips": [{"code": t.code, "handbook": t.slug, "text": t.text} for t in T.ALL_TIPS],
    }


# --------------------------------------------------------------------------- #
# What the log taught the ranking (note 09 §4.4)
# --------------------------------------------------------------------------- #


@router.get("/learned", response_model=LearnedList)
def learned_signals(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The signals the ranking learned from this person's log, each with a plain reason (note 09 §4.4): foods eaten
    often, foods usually eaten in one meal, usual meals, foods planned again and again but not eaten. Computed on the
    spot by the same rules the ranking uses, never stored; empty with "Learn from my log" off."""
    ctx = load_ctx(request, conn, user.id, today_local(), C.LoadOptions(saved_meals=False, combos=False))
    return learned(ctx)


# --------------------------------------------------------------------------- #
# Food preferences (note 09 §4.10): like, less often, "Not for me", neutral
# --------------------------------------------------------------------------- #

_PREFERENCE_COLUMNS = """p.food_id, f.name, f.category, p.preference, COALESCE(p.source, 'person') AS source,
                         p.created_at, COALESCE(p.updated_at, p.created_at) AS updated_at"""


def _preference_food(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in ("food_id", "name", "category", "preference", "source", "created_at", "updated_at")}


def _preference_list(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> dict[str, Any]:
    rows = conn.execute(
        f"""SELECT {_PREFERENCE_COLUMNS} FROM food_preferences p JOIN foods f ON f.id = p.food_id
            WHERE p.user_id = ? ORDER BY f.name COLLATE NOCASE, p.food_id""",
        (int(user_id),),
    ).fetchall()
    settings = C.user_settings(conn, store, user_id)
    return {
        "rules_version": R.RULES_VERSION,
        "limit": C.MAX_FOOD_PREFERENCES,
        "not_for_me_limit": C.MAX_NOT_FOR_ME,
        "foods": [_preference_food(r) for r in rows],
        "groups": {"like": list(C.setting_value(settings, "like_categories", ()) or ()),
                   "less": list(C.setting_value(settings, "less_categories", ()) or ()),
                   "never": list(C.setting_value(settings, "exclude_categories", ()) or ())},
        "learn_from_log": bool(C.setting_value(settings, "learn_from_log", True)),
    }


def apply_preference(conn: sqlite3.Connection, user_id: int, food_id: int, preference: str, source: str) -> str | None:
    """Insert or change one preference row inside the write transaction the caller has open; no commit. Returns the value that
    was there before (``None``: no row). The caller has checked that the food is the person's to use.

    The same value again changes nothing (idempotent, ``updated_at`` and ``source`` stay). 409 at 500 "Not for me" foods and
    at 1,000 preferences in all; a row that is only changing its value does not add to the total. The PUT routes and the MCP
    tool ``set_food_preference`` (``app/mcp/preference_tool.py``) both end here."""
    row = conn.execute("SELECT preference FROM food_preferences WHERE user_id = ? AND food_id = ?",
                       (user_id, food_id)).fetchone()
    if row is None or row["preference"] != preference:
        total, never = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(preference = ?), 0) FROM food_preferences WHERE user_id = ?",
            (C.PREFERENCE_NOT_FOR_ME, user_id)).fetchone()
        if preference == C.PREFERENCE_NOT_FOR_ME and never >= C.MAX_NOT_FOR_ME:
            raise HTTPException(status_code=409, detail=f"the \"Not for me\" list is full ({C.MAX_NOT_FOR_ME} foods); "
                                                        "remove one first")
        now = utcnow()
        if row is None:
            if total >= C.MAX_FOOD_PREFERENCES:
                raise HTTPException(status_code=409, detail=f"your food preferences are full ({C.MAX_FOOD_PREFERENCES} foods); "
                                                            "remove one first")
            conn.execute(
                """INSERT INTO food_preferences (user_id, food_id, preference, created_at, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""", (user_id, food_id, preference, now, source, now))
        else:
            conn.execute("UPDATE food_preferences SET preference = ?, source = ?, updated_at = ? "
                         "WHERE user_id = ? AND food_id = ?", (preference, source, now, user_id, food_id))
    return None if row is None else str(row["preference"])


def drop_preference(conn: sqlite3.Connection, user_id: int, food_id: int) -> str | None:
    """Delete the person's preference row for a food inside the caller's transaction; no commit. Returns the value that was
    there, or ``None`` when there was no row (``OverflowError`` for an id SQLite cannot hold, which has no row either)."""
    try:
        row = conn.execute("SELECT preference FROM food_preferences WHERE user_id = ? AND food_id = ?",
                           (user_id, food_id)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM food_preferences WHERE user_id = ? AND food_id = ?", (user_id, food_id))
    except OverflowError:
        return None
    return str(row["preference"])


def _store_preference(conn: sqlite3.Connection, user_id: int, food_id: int, preference: str, source: str) -> None:
    """:func:`apply_preference` under ``BEGIN IMMEDIATE`` (the limits are checked in the same transaction), then commit."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_preference(conn, user_id, food_id, preference, source)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@router.get("/preferences", response_model=PreferenceList)
def list_preferences(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The person's food preferences by name, their food-group choices and the "Learn from my log" switch."""
    return _preference_list(conn, settings_store(request), user.id)


@router.put("/preferences/{food_id}", response_model=PreferenceFood)
def put_preference(food_id: int, body: PreferenceBody, user: CurrentUser,
                   conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Say ``like``, ``less`` (less often), ``not_for_me`` or ``neutral`` (stop using what was learned) about one food,
    replacing what was there. ``source`` is ``ask`` for a change the Ask chat proposed and the person confirmed. 404
    for a food the person cannot use; 409 at the limits."""
    if fetch_user_food(conn, user.id, food_id) is None:
        raise HTTPException(status_code=404, detail=f"food {food_id} not found")
    _store_preference(conn, user.id, food_id, body.preference, body.source)
    row = conn.execute(
        f"""SELECT {_PREFERENCE_COLUMNS} FROM food_preferences p JOIN foods f ON f.id = p.food_id
            WHERE p.user_id = ? AND p.food_id = ?""", (user.id, food_id)).fetchone()
    return _preference_food(row)


@router.delete("/preferences/{food_id}", status_code=204, response_class=Response)
def delete_preference(food_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Forget what was said about this food. 404 when there is nothing."""
    if drop_preference(conn, user.id, food_id) is None:
        raise HTTPException(status_code=404, detail=f"food {food_id} has no preference of yours")
    conn.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# "Not for me" (§4.14): the older routes, kept as aliases of the ``not_for_me`` rows of /preferences
# --------------------------------------------------------------------------- #


def _not_for_me(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT p.food_id, f.name, f.category, p.created_at FROM food_preferences p JOIN foods f ON f.id = p.food_id
           WHERE p.user_id = ? AND p.preference = ? ORDER BY f.name COLLATE NOCASE, p.food_id""",
        (int(user_id), C.PREFERENCE_NOT_FOR_ME),
    ).fetchall()
    return {"rules_version": R.RULES_VERSION, "limit": C.MAX_NOT_FOR_ME,
            "foods": [{"food_id": r["food_id"], "name": r["name"], "category": r["category"], "created_at": r["created_at"]}
                      for r in rows]}


@router.get("/not-for-me", response_model=NotForMeList)
def list_not_for_me(user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return _not_for_me(conn, user.id)


@router.put("/not-for-me/{food_id}", response_model=NotForMeList)
def add_not_for_me(food_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Never suggest this food again (it stays searchable and loggable); replaces another preference on the food.
    404 for a food the person cannot use; 409 at the limit of 500."""
    if fetch_user_food(conn, user.id, food_id) is None:
        raise HTTPException(status_code=404, detail=f"food {food_id} not found")
    _store_preference(conn, user.id, food_id, C.PREFERENCE_NOT_FOR_ME, "person")
    return _not_for_me(conn, user.id)


@router.delete("/not-for-me/{food_id}", status_code=204, response_class=Response)
def remove_not_for_me(food_id: int, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    """Suggest this food again. 404 when it is not on the person's "Not for me" list (another preference stays)."""
    try:
        cur = conn.execute("DELETE FROM food_preferences WHERE user_id = ? AND food_id = ? AND preference = ?",
                           (user.id, food_id, C.PREFERENCE_NOT_FOR_ME))
    except OverflowError:
        raise HTTPException(status_code=404, detail=f"food {food_id} is not on your list") from None
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"food {food_id} is not on your list")
    conn.commit()
    return Response(status_code=204)
