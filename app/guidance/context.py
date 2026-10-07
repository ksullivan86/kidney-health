"""Loads one person's :class:`~app.guidance.state.GuidanceContext` from SQLite (note 06 §4.2). I/O.

Every query takes the signed-in person's ``user_id`` (note 07 §4.4): their log, saved meals,
preferences and the foods they may use (builtin rows, their own custom foods and shared rows they
linked). Nothing here writes.

* **Targets** come from :func:`load_profile`, which reads the same stored profile the Today screen
  shows (``app.profile.get_profile``): the effective daily targets the person saved (or accepted from
  the personalised suggestion), ``warn_fraction``, dialysis mode and days, and diabetes type.
* **Foods** come from :class:`VectorCache`: per database file and ``meta.foods_rev`` (bumped by
  triggers on every food or link write, schema step 5), builtin vectors are built once and shared;
  each person's custom and linked foods are added on top. A stale entry can never be served: a new
  revision is a new key.
* **Starter combos** come from ``data/combos.json`` (curated), resolved to builtin food ids by
  ``fdc_id``; a combo that names a food this server does not have is skipped.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..config import REPO_ROOT
from ..db import database_file, get_meta
from ..foods import access_clause, access_params, parse_flags
from ..meals import parse_items
from ..nutrients import NUTRIENT_KEYS
from ..profile import get_profile
from ..settings_store import SettingsStore
from . import rules as R
from .state import Combo, DayEntry, GuidanceContext, HistoryEntry, Prefs, Profile, SavedMeal, Tunables
from .vectors import FoodVec, build_vectors, food_from_row

log = logging.getLogger("kidney_health.guidance")

COMBOS_JSON = REPO_ROOT / "data" / "combos.json"
FOODS_REV_KEY = "foods_rev"
PREFERENCE_NOT_FOR_ME = "not_for_me"
MAX_NOT_FOR_ME = 500  # note 06 §4.14: "≤ 500 ids"


# --------------------------------------------------------------------------- #
# Profile, targets and preferences
# --------------------------------------------------------------------------- #


def load_profile(conn: sqlite3.Connection, user_id: int) -> Profile:
    """The targets and profile fields guidance uses: exactly what the Today screen reads
    (``GET /api/log`` → ``app.profile.get_profile``), so guidance and the day's status always agree."""
    p = get_profile(conn, user_id)
    try:
        warn = float(p["warn_fraction"])
    except (TypeError, ValueError):
        warn = 0.8
    if not math.isfinite(warn) or not 0 < warn <= 1:
        warn = 0.8
    return Profile(
        targets=dict(p["targets"] or {}),
        warn_fraction=warn,
        dialysis=p["dialysis"] or "none",
        dialysis_days=tuple(p["dialysis_days"] or ()),
        diabetes=p["diabetes"] or "none",
        targets_updated_at=p.get("updated_at"),
    )


def has_targets(profile: Profile) -> bool:
    """Guidance needs a numeric potassium, phosphorus or sodium target, or a per-meal carb goal (§4.2)."""
    t = profile.targets
    return any(R.target_max(t.get(k)) is not None for k in (R.K, R.P, R.NA, "carbs_per_meal_g"))


def setting_value(settings: Any, name: str, default: Any) -> Any:
    """One field of the ``guidance`` settings object (a model instance or, from older code, a dict)."""
    if settings is None:
        return default
    if isinstance(settings, Mapping):
        return settings.get(name, default)
    return getattr(settings, name, default)


def user_settings(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> Any:
    """The person's ``guidance`` settings object (registry key ``guidance``, note 06 §4.14)."""
    return store.get(conn, "guidance", user_id)


def not_for_me_ids(conn: sqlite3.Connection, user_id: int) -> frozenset[int]:
    rows = conn.execute(
        "SELECT food_id FROM food_preferences WHERE user_id = ? AND preference = ?", (int(user_id), PREFERENCE_NOT_FOR_ME)
    ).fetchall()
    return frozenset(int(r["food_id"]) for r in rows)


def load_prefs(conn: sqlite3.Connection, store: SettingsStore, user_id: int) -> Prefs:
    settings = user_settings(conn, store, user_id)
    return Prefs(
        carb_tolerance_g=float(setting_value(settings, "carb_tolerance_g", R.CARB_TOLERANCE_G)),
        hypo_dose_g=float(setting_value(settings, "hypo_dose_g", R.HYPO_DOSE_G)),
        exclude_food_ids=not_for_me_ids(conn, user_id),
        exclude_categories=frozenset(setting_value(settings, "exclude_categories", ()) or ()),
    )


def load_tunables(conn: sqlite3.Connection, store: SettingsStore) -> Tunables:
    return Tunables(pool_per_role=int(store.get(conn, "guidance.pool_per_role")),
                    beam_width=int(store.get(conn, "guidance.beam_width")))


# --------------------------------------------------------------------------- #
# Food vectors
# --------------------------------------------------------------------------- #


_role_cache: dict[tuple[str, int], dict[int, str]] = {}
_role_lock = threading.Lock()


def role_overrides(foods_json: Path | None) -> dict[int, str]:
    """``{fdc_id: role}`` from the curated ``role`` of builtin foods in ``foods_json`` (cached by mtime)."""
    if foods_json is None:
        return {}
    path = Path(foods_json)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}
    with _role_lock:
        cached = _role_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        roles = {int(f["fdc_id"]): str(f["role"]) for f in data.get("foods", [])
                 if isinstance(f, dict) and f.get("role") in R.ROLES and f.get("fdc_id") is not None}
    except (OSError, ValueError, TypeError) as exc:
        log.warning("guidance: could not read food roles from %s (%s); derived roles are used", path, exc)
        roles = {}
    with _role_lock:
        _role_cache.clear()
        _role_cache[key] = roles
    return roles


class VectorCache:
    """Process-wide food vectors keyed by ``(database file, meta.foods_rev, user_id)`` (§4.2, §4.12).

    Builtin vectors are shared by every person of one database revision; a person's own custom and
    linked foods are added on top. At most ``max_entries`` dictionaries are kept (least recently used
    first out), about 200 bytes per food each.
    """

    def __init__(self, max_entries: int = 64) -> None:
        self.max_entries = max_entries
        self._builtin: OrderedDict[tuple[str, str], dict[int, FoodVec]] = OrderedDict()
        self._users: OrderedDict[tuple[str, str, int], dict[int, FoodVec]] = OrderedDict()
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._builtin.clear()
            self._users.clear()

    def _remember(self, store: OrderedDict, key: Any, value: dict[int, FoodVec]) -> None:
        with self._lock:
            store[key] = value
            store.move_to_end(key)
            while len(store) > self.max_entries:
                store.popitem(last=False)

    def _recall(self, store: OrderedDict, key: Any) -> dict[int, FoodVec] | None:
        with self._lock:
            value = store.get(key)
            if value is not None:
                store.move_to_end(key)
            return value

    def get(self, conn: sqlite3.Connection, user_id: int, foods_json: Path | None = None) -> dict[int, FoodVec]:
        """Every food ``user_id`` may use, hidden ones included (old entries and saved meals point at them)."""
        db = str(database_file(conn) or ":memory:")
        rev = get_meta(conn, FOODS_REV_KEY) or "0"
        key = (db, rev, int(user_id))
        cached = self._recall(self._users, key)
        if cached is not None:
            return cached
        overrides = role_overrides(foods_json)
        builtin = self._recall(self._builtin, (db, rev))
        if builtin is None:
            rows = conn.execute("SELECT * FROM foods WHERE source = 'builtin'").fetchall()
            builtin = build_vectors(((r, parse_flags(r["flags_json"])) for r in rows), overrides)
            self._remember(self._builtin, (db, rev), builtin)
        rows = conn.execute(
            f"SELECT f.* FROM foods f WHERE f.source != 'builtin' AND {access_clause('f')}", access_params(user_id)
        ).fetchall()
        foods = dict(builtin)
        foods.update(build_vectors(((r, parse_flags(r["flags_json"])) for r in rows), overrides))
        self._remember(self._users, key, foods)
        return foods


VECTOR_CACHE = VectorCache()


# --------------------------------------------------------------------------- #
# Log, saved meals, combos
# --------------------------------------------------------------------------- #

_ENTRY_SQL = """
    SELECT e.id, e.date, e.meal, e.status, e.food_id, e.food_name, e.servings, e.purpose,
           {cols},
           f.id AS f_id, f.name AS f_name, f.category AS f_category, f.serving_desc AS f_serving_desc,
           f.serving_g AS f_serving_g, f.source AS f_source, f.fdc_id AS f_fdc_id, f.kidney_notes AS f_kidney_notes,
           f.hidden AS f_hidden, f.flags_json AS f_flags_json, {food_cols}
    FROM log_entries e JOIN foods f ON f.id = e.food_id
    WHERE e.user_id = ? AND e.date >= ? AND e.date <= ? {status}
    ORDER BY e.date, CASE e.meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END,
             e.created_at, e.id
"""
_ENTRY_COLS = ", ".join(f"e.{k} AS {k}" for k in NUTRIENT_KEYS)
_FOOD_COLS = ", ".join(f"f.{k} AS f_{k}" for k in NUTRIENT_KEYS)


def _day_rows(conn: sqlite3.Connection, user_id: int, day: str) -> list[sqlite3.Row]:
    """Every entry (eaten and planned) of one day, with the columns of its food."""
    sql = _ENTRY_SQL.format(cols=_ENTRY_COLS, food_cols=_FOOD_COLS, status="")
    return conn.execute(sql, (int(user_id), day, day)).fetchall()


def _food_of(row: sqlite3.Row, foods: Mapping[int, FoodVec], overrides: Mapping[int, str]) -> FoodVec:
    """The entry's food vector (from the cache, else from the joined row: a shared food the person
    unlinked after logging it)."""
    vec = foods.get(int(row["food_id"]))
    if vec is not None:
        return vec
    food_row = {
        "id": row["f_id"], "name": row["f_name"], "category": row["f_category"], "serving_desc": row["f_serving_desc"],
        "serving_g": row["f_serving_g"], "source": row["f_source"], "fdc_id": row["f_fdc_id"],
        "kidney_notes": row["f_kidney_notes"], "hidden": row["f_hidden"],
        **{k: row[f"f_{k}"] for k in NUTRIENT_KEYS},
    }
    override = overrides.get(row["f_fdc_id"]) if row["f_source"] == "builtin" else None
    return food_from_row(food_row, parse_flags(row["f_flags_json"]), override)


def _snapshot(row: sqlite3.Row) -> dict[str, float | None]:
    return {k: (None if row[k] is None else float(row[k])) for k in NUTRIENT_KEYS}


def day_entry(row: sqlite3.Row, food: FoodVec) -> DayEntry:
    return DayEntry(
        id=int(row["id"]), meal=row["meal"], status=row["status"], food_id=int(row["food_id"]), name=row["food_name"],
        servings=float(row["servings"]), nutrients=_snapshot(row), purpose=row["purpose"], role=food.role,
        family=food.family, category=food.category, flags=food.flags,
    )


# History is the largest read of a request (60 days, up to ~3,000 rows): a narrow query read by
# position, flags parsed once per distinct JSON text (§4.12).
_HISTORY_SQL = f"""
    SELECT e.date, e.meal, e.food_id, e.food_name, e.servings, e.purpose, f.flags_json,
           {", ".join(f"e.{k}" for k in NUTRIENT_KEYS)}
    FROM log_entries e JOIN foods f ON f.id = e.food_id
    WHERE e.user_id = ? AND e.date >= ? AND e.date <= ? AND e.status = 'eaten'
    ORDER BY e.date, CASE e.meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END,
             e.created_at, e.id
"""


def load_history(conn: sqlite3.Connection, user_id: int, start: str, end: str) -> tuple[HistoryEntry, ...]:
    """The person's eaten entries of ``start``…``end`` (both inclusive), in log order."""
    flags_cache: dict[str | None, frozenset[str]] = {}
    out: list[HistoryEntry] = []
    keys = NUTRIENT_KEYS
    conn_rows = conn.execute(_HISTORY_SQL, (int(user_id), start, end))
    conn_rows.row_factory = None  # plain tuples: read by position
    for row in conn_rows:
        flags_json = row[6]
        flags = flags_cache.get(flags_json)
        if flags is None:
            flags = flags_cache[flags_json] = frozenset(parse_flags(flags_json))
        out.append(HistoryEntry(date=row[0], meal=row[1], food_id=int(row[2]), name=row[3], servings=float(row[4]),
                                nutrients=dict(zip(keys, row[7:])), purpose=row[5], flags=flags))
    return tuple(out)


def load_saved_meals(conn: sqlite3.Connection, user_id: int) -> tuple[SavedMeal, ...]:
    rows = conn.execute(
        "SELECT id, name, meal_hint, items_json FROM meal_templates WHERE user_id = ? ORDER BY name COLLATE NOCASE, id",
        (int(user_id),),
    ).fetchall()
    meals = []
    for row in rows:
        items = tuple((int(i["food_id"]), float(i["servings"])) for i in parse_items(row["items_json"]))
        hint = row["meal_hint"] if row["meal_hint"] in R.SLOT_ORDER else None
        meals.append(SavedMeal(id=int(row["id"]), name=row["name"], meal_hint=hint, items=items))
    return tuple(meals)


_combo_cache: dict[tuple[str, int], tuple[dict[str, Any], ...]] = {}


def read_combos(path: Path = COMBOS_JSON) -> tuple[dict[str, Any], ...]:
    """The curated starter combos (cached by mtime); an unreadable file is logged and gives none."""
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return ()
    cached = _combo_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        combos = tuple(c for c in data.get("combos", []) if isinstance(c, dict))
    except (OSError, ValueError) as exc:
        log.warning("guidance: could not read starter combos from %s (%s); none are offered", path, exc)
        combos = ()
    _combo_cache.clear()
    _combo_cache[key] = combos
    return combos


def resolve_combos(foods: Mapping[int, FoodVec], raw: Iterable[Mapping[str, Any]]) -> tuple[Combo, ...]:
    """Combos whose every ``fdc_id`` is a builtin food of this server, with food ids."""
    by_fdc = {f.fdc_id: f.id for f in foods.values() if f.source == "builtin" and f.fdc_id is not None}
    out: list[Combo] = []
    for c in raw:
        try:
            items = tuple((by_fdc[int(i["fdc_id"])], float(i["servings"])) for i in c["items"])
            meal = str(c["meal"])
        except (KeyError, TypeError, ValueError):
            continue
        if meal in R.SLOT_ORDER and items:
            out.append(Combo(id=str(c.get("id", "")), name=str(c.get("name", "")), meal=meal, items=items,
                             source=str(c.get("source", ""))))
    return tuple(out)


# --------------------------------------------------------------------------- #
# The context
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LoadOptions:
    history: bool = True  # eaten entries of the previous 14 days (habit, variety, week allowance)
    history60: bool = True  # eaten entries of the previous 60 days (usual meals)
    saved_meals: bool = True
    combos: bool = True


def _days_before(day: str, n: int) -> str:
    return (_date.fromisoformat(day) - timedelta(days=n)).isoformat()


def load(conn: sqlite3.Connection, user_id: int, day: str, *, store: SettingsStore, foods_json: Path | None = None,
         options: LoadOptions = LoadOptions(), cache: VectorCache = VECTOR_CACHE) -> GuidanceContext:
    """Everything one guidance request needs for ``user_id`` on ``day`` (every query scoped to the person)."""
    foods = cache.get(conn, user_id, foods_json)
    overrides = role_overrides(foods_json)
    day_rows = _day_rows(conn, user_id, day)
    entries = tuple(day_entry(r, _food_of(r, foods, overrides)) for r in day_rows)
    history: tuple[HistoryEntry, ...] = ()
    history60: tuple[HistoryEntry, ...] = ()
    if options.history or options.history60:
        span = R.USUAL_HISTORY_DAYS if options.history60 else R.HISTORY_DAYS
        all_history = load_history(conn, user_id, _days_before(day, span), _days_before(day, 1))
        start14 = _days_before(day, R.HISTORY_DAYS)
        history = tuple(h for h in all_history if h.date >= start14) if options.history else ()
        history60 = all_history if options.history60 else ()
    combos = resolve_combos(foods, read_combos()) if options.combos else ()
    return GuidanceContext(
        date=day,
        profile=load_profile(conn, user_id),
        prefs=load_prefs(conn, store, user_id),
        foods=foods,
        day=entries,
        history=history,
        history60=history60,
        saved_meals=load_saved_meals(conn, user_id) if options.saved_meals else (),
        combos=combos,
        tunables=load_tunables(conn, store),
    )


def load_period(conn: sqlite3.Connection, user_id: int, start: str, end: str) -> tuple[HistoryEntry, ...]:
    """Eaten entries of ``start``…``end`` (period insights)."""
    return load_history(conn, user_id, start, end)


def entry_for_swap(conn: sqlite3.Connection, user_id: int, entry_id: int) -> sqlite3.Row | None:
    """One of the person's entries (``None`` when it does not exist or is someone else's)."""
    try:
        return conn.execute(
            "SELECT id, date, meal, food_id, servings, purpose FROM log_entries WHERE id = ? AND user_id = ?",
            (int(entry_id), int(user_id)),
        ).fetchone()
    except OverflowError:
        return None
