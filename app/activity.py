"""Activity and recovery (Whoop) and the active-day calorie extra (design note 28; ARCHITECTURE "Activity and recovery").

**The extra** (note 28 §4.2), off unless the person turns it on: on a day with a Whoop figure, the calorie target is the base
target (the person's own, unchanged: NASEM 2023 EER inside KDOQI 2020's 25–35 kcal/kg, rules E-1 to E-4) plus

    extra = min(ceiling, round-half-up-to-10(max(0, burned − quiet) × share% ÷ 100))

where ``burned`` is Whoop's calories for that day so far and ``quiet`` the person's **usual quiet-day level**: the lower quartile
(nearest rank) of Whoop's calories on their finished Whoop days in the 28 days before, with at least 14 such days (fewer: no extra
yet). Comparing Whoop with Whoop cancels a tracker's constant error (O'Driscoll 2020; Germini 2022: tracker calories are often off
by a third). **Only calories rise**: no other target changes, and HRV, recovery, sleep and strain never change anything. The JS twin
(``js/engine/activity.js``) must give the same numbers (``tests/data/activity_vectors.json``).

Routes (every one needs a signed-in person and reads only their own rows):

* ``GET /api/activity?start=&end=``: Whoop days and workouts in the range (default: the last 30 days) and the extra setting. Always
  ``200``, also with no data (Trends asks on every open).
* ``PUT /api/activity/extra``: the setting. The Activity list records turning it on or off.

The Care team read (``GET /api/shared/{id}/activity``, area ``activity``) lives in :mod:`app.sharing` and uses :func:`activity_view`.
"""
from __future__ import annotations

import sqlite3
from datetime import date as _date, timedelta
from typing import Any, Iterable, Mapping

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .audit import audit
from .auth.context import request_ip
from .auth.deps import CurrentUser
from .db import get_db, utcnow

router = APIRouter(prefix="/api/activity", tags=["activity"])

KJ_PER_KCAL = 4.184  # for the docs; the provider converts (app/devices/whoop.py)
QUIET_WINDOW_DAYS = 28
QUIET_MIN_DAYS = 14
QUIET_PERCENTILE = 25
SHARE_DEFAULT = 100
SHARE_MIN, SHARE_MAX = 10, 100
CEILING_MIN, CEILING_MAX = 50, 3000
DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 366
CALORIES = "calories_kcal"
DAY_COLUMNS = ("date", "kcal", "strain", "recovery_pct", "resting_hr", "hrv_ms", "sleep_minutes", "sleep_performance_pct",
               "finished", "source")
WORKOUT_COLUMNS = ("date", "start_time", "end_time", "minutes", "sport", "kcal", "strain", "source")


# --------------------------------------------------------------------------- #
# The engine (pure; the JS twin is js/engine/activity.js)
# --------------------------------------------------------------------------- #


def _whole(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value) if float(value).is_integer() else None


def quiet_level(history: Iterable[Any]) -> int | None:
    """The lower quartile (nearest rank) of the finished days' calories, or None with fewer than :data:`QUIET_MIN_DAYS`."""
    values = sorted(v for v in (_whole(h) for h in history) if v is not None and v > 0)
    if len(values) < QUIET_MIN_DAYS:
        return None
    rank = (QUIET_PERCENTILE * len(values) + 99) // 100  # ceil(25 % of n), at least 1
    return values[max(rank, 1) - 1]


def extra_kcal(burned: int, quiet: int, share_pct: int, ceiling_kcal: int | None) -> int:
    """The calories added: what was burned above the quiet level, times the share, half up to 10 kcal, at most the ceiling."""
    above = max(0, int(burned) - int(quiet))
    extra = (above * int(share_pct) + 500) // 1000 * 10
    return min(extra, int(ceiling_kcal)) if ceiling_kcal is not None else extra


def base_kcal(target: Any) -> float | None:
    """The calorie target the extra adds to: a number, or the top of a range (the bottom when there is no top)."""
    if isinstance(target, Mapping):
        for side in ("max", "min"):
            value = target.get(side)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                return value
        return None
    if isinstance(target, (int, float)) and not isinstance(target, bool) and target > 0:
        return target
    return None


def raised(target: Any, extra: int) -> Any:
    """``target`` with ``extra`` kcal added (both ends of a range move); unchanged when the extra is 0."""
    if not extra:
        return target
    if isinstance(target, Mapping):
        return {k: (v + extra if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in target.items()}
    return target + extra


def calorie_extra(setting: Mapping[str, Any], base_target: Any, burned: Any, history: Iterable[Any]) -> dict[str, Any] | None:
    """What Today shows for one day: ``None`` when the extra is off, there is no calorie target or no Whoop figure for the day;
    otherwise the base, the extra (0 on a quiet day or while fewer than 14 finished days exist), the calories burned, the quiet
    level (None while waiting), the share, the ceiling and how many finished days there are."""
    if not setting.get("enabled"):
        return None
    base = base_kcal(base_target)
    kcal = _whole(burned)
    if base is None or kcal is None or kcal <= 0:
        return None
    days = [h for h in history if (_whole(h) or 0) > 0]
    quiet = quiet_level(days)
    share = int(setting.get("share_pct") or SHARE_DEFAULT)
    ceiling = setting.get("ceiling_kcal")
    extra = 0 if quiet is None else extra_kcal(kcal, quiet, share, ceiling)
    return {"base_kcal": base, "extra_kcal": extra, "burned_kcal": kcal, "quiet_kcal": quiet, "share_pct": share,
            "ceiling_kcal": ceiling, "history_days": len(days), "source": "whoop"}


# --------------------------------------------------------------------------- #
# Reading the person's rows
# --------------------------------------------------------------------------- #


def extra_setting(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT enabled, share_pct, ceiling_kcal FROM activity_extra WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return {"enabled": False, "share_pct": SHARE_DEFAULT, "ceiling_kcal": None}
    return {"enabled": bool(row["enabled"]), "share_pct": int(row["share_pct"]), "ceiling_kcal": row["ceiling_kcal"]}


def _day_before(day: str, n: int) -> str:
    return (_date.fromisoformat(day) - timedelta(days=n)).isoformat()


def day_extra(conn: sqlite3.Connection, user_id: int, day: str, targets: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The targets for ``day`` with the extra added to the calorie target, and what Today shows about it (None: nothing to add)."""
    setting = extra_setting(conn, user_id)
    if not setting["enabled"] or base_kcal(targets.get(CALORIES)) is None:
        return dict(targets), None
    row = conn.execute("SELECT kcal FROM activity_days WHERE user_id = ? AND date = ? AND kcal IS NOT NULL "
                       "ORDER BY source LIMIT 1", (user_id, day)).fetchone()
    if row is None:
        return dict(targets), None
    history = [r[0] for r in conn.execute(
        "SELECT kcal FROM activity_days WHERE user_id = ? AND date >= ? AND date < ? AND finished = 1 AND kcal IS NOT NULL",
        (user_id, _day_before(day, QUIET_WINDOW_DAYS), day))]
    info = calorie_extra(setting, targets.get(CALORIES), row["kcal"], history)
    out = dict(targets)
    if info is not None:
        out[CALORIES] = raised(targets.get(CALORIES), info["extra_kcal"])
    return out, info


def activity_view(conn: sqlite3.Connection, user_id: int, start: str, end: str) -> dict[str, Any]:
    days = [{k: (bool(r[k]) if k == "finished" else r[k]) for k in DAY_COLUMNS} for r in conn.execute(
        f"SELECT {', '.join(DAY_COLUMNS)} FROM activity_days WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date, source",
        (user_id, start, end))]
    workouts = [{k: r[k] for k in WORKOUT_COLUMNS} for r in conn.execute(
        f"SELECT {', '.join(WORKOUT_COLUMNS)} FROM activity_workouts WHERE user_id = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, start_time, id", (user_id, start, end))]
    return {"start": start, "end": end, "days": days, "workouts": workouts}


def export_rows(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    """Everything for the person's own export (``export.json``)."""
    out = activity_view(conn, user_id, "0000-01-01", "9999-12-31")
    del out["start"], out["end"]
    out["extra"] = extra_setting(conn, user_id)
    return out


def parse_range(start: str | None, end: str | None) -> tuple[str, str]:
    from .log import check_range, parse_date_param, today_local

    end_s = parse_date_param(end, "end") if end else today_local()
    start_s = parse_date_param(start, "start") if start else _day_before(end_s, DEFAULT_RANGE_DAYS - 1)
    check_range(_date.fromisoformat(start_s), _date.fromisoformat(end_s), MAX_RANGE_DAYS)
    return start_s, end_s


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


class ActivityDayOut(BaseModel):
    date: str
    kcal: int | None
    strain: float | None
    recovery_pct: int | None
    resting_hr: int | None
    hrv_ms: float | None
    sleep_minutes: int | None
    sleep_performance_pct: int | None
    finished: bool
    source: str


class WorkoutOut(BaseModel):
    date: str
    start_time: str | None
    end_time: str | None
    minutes: int | None
    sport: str
    kcal: int | None
    strain: float | None
    source: str


class ExtraSetting(BaseModel):
    enabled: bool = False
    share_pct: int = Field(SHARE_DEFAULT, ge=SHARE_MIN, le=SHARE_MAX)
    ceiling_kcal: int | None = Field(None, ge=CEILING_MIN, le=CEILING_MAX)


class ActivityOut(BaseModel):
    start: str
    end: str
    days: list[ActivityDayOut]
    workouts: list[WorkoutOut]
    extra: ExtraSetting | None = None  # the person's own setting; not in a Care team view


@router.get("", response_model=ActivityOut)
def list_activity(user: CurrentUser, start: str | None = None, end: str | None = None,
                 conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    start_s, end_s = parse_range(start, end)
    return {**activity_view(conn, user.id, start_s, end_s), "extra": extra_setting(conn, user.id)}


@router.put("/extra", response_model=ExtraSetting)
def set_extra(body: ExtraSetting, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    before = extra_setting(conn, user.id)
    conn.execute("INSERT INTO activity_extra (user_id, enabled, share_pct, ceiling_kcal, updated_at) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled, share_pct = excluded.share_pct, "
                 "ceiling_kcal = excluded.ceiling_kcal, updated_at = excluded.updated_at",
                 (user.id, int(body.enabled), body.share_pct, body.ceiling_kcal, utcnow()))
    after = extra_setting(conn, user.id)
    if after != before and (after["enabled"] or before["enabled"]):
        action = "activity.extra_on" if after["enabled"] else "activity.extra_off"
        audit(conn, user.id, action, "user", user.id, ip=request_ip(request), share_pct=after["share_pct"],
              ceiling_kcal=after["ceiling_kcal"])
    conn.commit()
    return after
