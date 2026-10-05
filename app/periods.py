"""Pure period maths for the v0.2 summaries (no I/O, no database, no FastAPI).

* multi-day aggregation of *eaten* day totals with a same-length previous-period
  comparison (``GET /api/log/summary``),
* the hemodialysis interdialytic interval given a list of dialysis weekdays,
* week boundaries for the Plan view grid.

Dates are ``YYYY-MM-DD`` strings or :class:`datetime.date`; weekdays follow
:meth:`datetime.date.weekday` (0 = Monday .. 6 = Sunday), as the profile stores them.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

from .nutrients import NUTRIENT_BY_KEY, NUTRIENT_KEYS, round_value, status_level, target_bounds

# How a nutrient is judged over a period (ARCHITECTURE.md "Why periods matter").
ASSESSMENT: dict[str, str] = {
    "potassium_mg": "daily",
    "sodium_mg": "daily",
    "fluid_ml": "daily",
    "carbs_g": "daily",
    "phosphorus_mg": "weekly_average",
    "protein_g": "weekly_average",
    "calories_kcal": "weekly_average",
    "calcium_mg": "weekly_average",
}
DEFAULT_ASSESSMENT = "weekly_average"  # fat, saturated fat, fiber, sugars if someone targets them

# Nutrients that accumulate between hemodialysis sessions.
INTERDIALYTIC_KEYS: tuple[str, ...] = ("potassium_mg", "sodium_mg", "fluid_ml")
# A weekly schedule always has a session within the last 7 days; the cap guards the maths
# (and the wording) if the interval ever has to be computed without one.
MAX_INTERDIALYTIC_DAYS = 7

WEEK_STARTS: tuple[str, ...] = ("monday", "sunday")
WEEKDAY_NAMES: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

NOTE_DAILY = (
    "Potassium, sodium and fluid are judged day by day: a day well over the limit is a risk on its own, "
    "and a low day does not bank against a high one."
)
NOTE_WEEKLY = (
    "Phosphorus and protein are judged on the weekly average: blood phosphate and nutritional status "
    "reflect weeks of intake, so an average above target matters more than one high day."
)
NOTE_CARBS = "Carbohydrate is counted per meal and per day for insulin; its weekly average is informational."
NOTE_INTERDIALYTIC = (
    "Between hemodialysis sessions potassium, sodium and fluid accumulate until the next session; "
    "the 'since last dialysis' totals cover the current interval (the long weekend gap is the one to watch)."
)
NOTE_NO_DIALYSIS_DAYS = (
    "Set your dialysis days in the profile to see potassium, sodium and fluid totals since your last session."
)
NOTE_CAPPED = "No dialysis day fell within the last {n} days, so the interval is capped at {n} days."


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #


def to_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def period_length(start: str | date, end: str | date) -> int:
    """Number of calendar days in ``[start, end]`` (inclusive)."""
    n = (to_date(end) - to_date(start)).days + 1
    if n < 1:
        raise ValueError("end must not be before start")
    return n


def date_range(start: str | date, end: str | date) -> list[str]:
    """Every date in ``[start, end]`` as ``YYYY-MM-DD`` strings."""
    s = to_date(start)
    return [(s + timedelta(days=i)).isoformat() for i in range(period_length(start, end))]


def previous_period(start: str | date, end: str | date) -> tuple[date, date]:
    """The same-length period that ends the day before ``start``."""
    s = to_date(start)
    n = period_length(start, end)
    return s - timedelta(days=n), s - timedelta(days=1)


def week_bounds(day: str | date, week_start: str = "monday") -> tuple[date, date]:
    """First and last day of the week containing ``day`` for the given week start."""
    if week_start not in WEEK_STARTS:
        raise ValueError(f"week_start must be one of {', '.join(WEEK_STARTS)}")
    d = to_date(day)
    first_weekday = 0 if week_start == "monday" else 6
    start = d - timedelta(days=(d.weekday() - first_weekday) % 7)
    return start, start + timedelta(days=6)


def normalise_dialysis_days(days: Iterable[Any] | None) -> list[int]:
    """Validate weekdays: integers 0 (Monday) .. 6 (Sunday); duplicates dropped; sorted."""
    if days is None:
        return []
    out: set[int] = set()
    for raw in days:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError("dialysis_days must be whole numbers 0 (Monday) to 6 (Sunday)")
        if raw < 0 or raw > 6:
            raise ValueError("dialysis_days must be between 0 (Monday) and 6 (Sunday)")
        out.add(raw)
    return sorted(out)


# --------------------------------------------------------------------------- #
# Period aggregation
# --------------------------------------------------------------------------- #


def summary_target(key: str, target: Any) -> float | None:
    """The number a period is judged against: the max for limits/ranges, the goal for goals.

    ``None`` means the nutrient is not tracked and must be omitted from the summary.
    """
    _, hi = target_bounds(target)
    return hi if hi is not None and math.isfinite(hi) and hi > 0 else None


def _value(day_totals: Mapping[str, Mapping[str, Any]], day: str, key: str) -> float:
    """One day's total for ``key``; a non-finite stored value counts as 0 so one bad row
    cannot take the whole summary down (the API now refuses to create such rows)."""
    value = float((day_totals.get(day) or {}).get(key) or 0.0)
    return value if math.isfinite(value) else 0.0


# Sums of day totals use math.fsum: exactly rounded, so a period's total and average do not depend
# on the Python version (3.11's sum() adds left to right, 3.12+ compensates; the two can differ in
# the last bit and so by 0.1 after rounding, e.g. 2244.1499999999996 vs 2244.15).
def _average(values: list[float]) -> float | None:
    return (math.fsum(values) / len(values)) if values else None


def summarize_period(
    start: str | date,
    end: str | date,
    day_totals: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Any],
    warn_fraction: float = 0.8,
) -> dict[str, Any]:
    """Aggregate eaten day totals over ``[start, end]``.

    ``day_totals`` maps ``YYYY-MM-DD`` to that day's eaten totals and must contain only
    days that have at least one eaten entry (a present key *is* a logged day). It may
    hold dates outside the period: the previous period is read from the same mapping.

    Returns ``{"start", "end", "days", "logged_days", "nutrients": {...}}`` with one
    item per nutrient that has a numeric target (see ARCHITECTURE.md ``PeriodSummary``).
    """
    start_d, end_d = to_date(start), to_date(end)
    days = period_length(start_d, end_d)
    current = [d for d in date_range(start_d, end_d) if d in day_totals]
    prev_start, prev_end = previous_period(start_d, end_d)
    previous = [d for d in date_range(prev_start, prev_end) if d in day_totals]
    logged_days = len(current)

    nutrients: dict[str, dict[str, Any]] = {}
    for key in NUTRIENT_KEYS:
        target = summary_target(key, targets.get(key))
        if target is None:
            continue
        values = [(d, _value(day_totals, d, key)) for d in current]
        total = math.fsum(v for _, v in values)
        average = _average([v for _, v in values])
        fraction = None if average is None else round(average / target, 2)
        max_day = max(values, key=lambda t: t[1]) if values else None
        previous_average = _average([_value(day_totals, d, key) for d in previous])
        change_pct = None
        if average is not None and previous_average:
            change_pct = round((average - previous_average) / previous_average * 100.0, 1)
        nutrients[key] = {
            "role": NUTRIENT_BY_KEY[key].role,
            "target": round_value(key, target),
            "total": round_value(key, total),
            "average": None if average is None else round_value(key, average),
            "fraction": fraction,
            "level": status_level(fraction, warn_fraction),
            "days_over": sum(1 for _, v in values if v > target),
            "max_day": None if max_day is None else {"date": max_day[0], "value": round_value(key, max_day[1])},
            "previous_average": None if previous_average is None else round_value(key, previous_average),
            "change_pct": change_pct,
            "assessment": ASSESSMENT.get(key, DEFAULT_ASSESSMENT),
        }

    return {
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "days": days,
        "logged_days": logged_days,
        "nutrients": nutrients,
    }


# --------------------------------------------------------------------------- #
# Interdialytic interval (hemodialysis)
# --------------------------------------------------------------------------- #


def interdialytic_interval(
    end: str | date,
    dialysis_days: Iterable[int] | None,
    max_days: int = MAX_INTERDIALYTIC_DAYS,
) -> dict[str, Any] | None:
    """The interval that ``end`` belongs to, or ``None`` when no dialysis days are set.

    ``since`` is the most recent dialysis weekday on or before ``end`` (intake on a
    dialysis day counts toward the next session), ``days = end - since + 1`` and
    ``next`` is the first dialysis weekday after ``end``. When no dialysis day falls
    within the last ``max_days`` days the interval is capped at ``max_days`` and
    ``capped`` is ``True`` so the caller can say so.
    """
    weekdays = {int(d) for d in (dialysis_days or ()) if 0 <= int(d) <= 6}
    if not weekdays:
        return None
    end_d = to_date(end)
    since: date | None = None
    for back in range(max_days):
        candidate = end_d - timedelta(days=back)
        if candidate.weekday() in weekdays:
            since = candidate
            break
    capped = since is None
    if since is None:
        since = end_d - timedelta(days=max_days - 1)
    next_session = next(
        end_d + timedelta(days=ahead) for ahead in range(1, 8) if (end_d + timedelta(days=ahead)).weekday() in weekdays
    )
    return {
        "since": since.isoformat(),
        "end": end_d.isoformat(),
        "days": (end_d - since).days + 1,
        "next": next_session.isoformat(),
        "capped": capped,
    }


def interdialytic_block(
    interval: Mapping[str, Any],
    day_totals: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Any],
    warn_fraction: float = 0.8,
) -> dict[str, Any]:
    """``PeriodSummary.interdialytic``: eaten totals over the interval vs ``per-day target × days``.

    Only potassium, sodium and fluid are included, and only when they have a numeric target.
    """
    days = int(interval["days"])
    window = date_range(interval["since"], interval["end"])
    nutrients: dict[str, dict[str, Any]] = {}
    for key in INTERDIALYTIC_KEYS:
        target = summary_target(key, targets.get(key))
        if target is None:
            continue
        total = math.fsum(_value(day_totals, d, key) for d in window)
        limit = target * days
        fraction = round(total / limit, 2)
        nutrients[key] = {
            "total": round_value(key, total),
            "limit": round_value(key, limit),
            "fraction": fraction,
            "level": status_level(fraction, warn_fraction),
        }
    return {"since": interval["since"], "days": days, "next": interval["next"], "nutrients": nutrients}


def summary_notes(dialysis: str, dialysis_days: Iterable[int] | None, interval: Mapping[str, Any] | None) -> list[str]:
    """The explanatory sentences shown once under the summary card."""
    notes = [NOTE_DAILY, NOTE_WEEKLY, NOTE_CARBS]
    if dialysis == "hemodialysis":
        if interval is not None:
            notes.append(NOTE_INTERDIALYTIC)
            if interval.get("capped"):
                notes.append(NOTE_CAPPED.format(n=MAX_INTERDIALYTIC_DAYS))
        elif not list(dialysis_days or ()):
            notes.append(NOTE_NO_DIALYSIS_DAYS)
    return notes
