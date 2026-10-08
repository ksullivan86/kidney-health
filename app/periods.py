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

from .nutrients import NUTRIENT_BY_KEY, NUTRIENT_KEYS, _fmt, over_at, round_value, status_level, target_bounds

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
    *,
    day_unknown: Mapping[str, Mapping[str, int]] | None = None,
    about_tolerance_pct: Any = 0,
) -> dict[str, Any]:
    """Aggregate eaten day totals over ``[start, end]``.

    ``day_totals`` maps ``YYYY-MM-DD`` to that day's eaten totals and must contain only
    days that have at least one eaten entry (a present key *is* a logged day). It may
    hold dates outside the period: the previous period is read from the same mapping.
    ``day_unknown`` maps a date to ``{key: entries without a value}`` (a day total skips them).

    Returns ``{"start", "end", "days", "logged_days", "nutrients": {...}}`` with one
    item per nutrient that has a numeric target (see ARCHITECTURE.md ``PeriodSummary``);
    ``unknown_entries`` / ``unknown_days`` say how many eaten entries (on how many logged days of
    the period) the totals and averages miss. An "about" target (minimum = maximum) is ``over``, and a day counts
    in ``days_over``, only above the person's ``about_tolerance_pct`` (as on Today).
    """
    unknown = day_unknown or {}
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
        lo, _ = target_bounds(targets.get(key))
        limit_at = over_at(key, lo, target, about_tolerance_pct)
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
            "level": status_level(fraction, warn_fraction, limit_at),
            "days_over": sum(1 for _, v in values if (v > target if limit_at == 1.0 else v / target > limit_at)),
            "max_day": None if max_day is None else {"date": max_day[0], "value": round_value(key, max_day[1])},
            "previous_average": None if previous_average is None else round_value(key, previous_average),
            "change_pct": change_pct,
            "assessment": ASSESSMENT.get(key, DEFAULT_ASSESSMENT),
            "unknown_entries": sum(int((unknown.get(d) or {}).get(key, 0)) for d in current),
            "unknown_days": sum(1 for d in current if (unknown.get(d) or {}).get(key)),
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
    *,
    day_unknown: Mapping[str, Mapping[str, int]] | None = None,
) -> dict[str, Any]:
    """``PeriodSummary.interdialytic``: eaten totals over the interval vs ``per-day target × days``.

    Only potassium, sodium and fluid are included, and only when they have a numeric target;
    ``unknown_entries`` counts the eaten entries in the interval the total misses (no value).
    """
    unknown = day_unknown or {}
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
            "unknown_entries": sum(int((unknown.get(d) or {}).get(key, 0)) for d in window),
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


# --------------------------------------------------------------------------- #
# Running high over several days (v0.3.1, docs/dev/plans/v0.3.1.md item 4)
# --------------------------------------------------------------------------- #

# Display rules, not clinical thresholds: every number compared is the person's own target. "2 of the last 3
# days" and "at least 3 logged days for a weekly average" are marked for clinical review in handbook/REVIEW.md.
RECENT_DAYS = 3
RECENT_HIGH_DAYS = 2
WEEKLY_DAYS = 7
WEEKLY_MIN_LOGGED_DAYS = 3
DAILY_PATTERN_KEYS: tuple[str, ...] = ("potassium_mg", "sodium_mg", "fluid_ml")
WEEKLY_PATTERN_KEYS: tuple[str, ...] = ("phosphorus_mg", "protein_g")
MAX_PATTERN_SOURCES = 2
WEEKDAY_NAMES: tuple[str, ...] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _day_value(day_values: Mapping[str, Mapping[str, Any]], day: date, key: str) -> float:
    value = float((day_values.get(day.isoformat()) or {}).get(key) or 0.0)
    return value if math.isfinite(value) else 0.0


def _sources_text(key: str, planned_sources: Iterable[tuple[str, Mapping[str, Any]]]) -> str:
    """" The planned foods adding the most: banana (422 mg) and juice (300 mg)." (one food: singular; none: "")."""
    by_name: dict[str, float] = {}
    for name, nutrients in planned_sources:
        value = float((nutrients or {}).get(key) or 0.0)
        if value > 0 and math.isfinite(value):
            by_name[name] = by_name.get(name, 0.0) + value
    top = sorted(by_name.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_PATTERN_SOURCES]
    if not top:
        return ""
    unit = NUTRIENT_BY_KEY[key].unit
    parts = [f"{name} ({_fmt(key, value)} {unit})" for name, value in top]
    if len(parts) == 1:
        return f" The planned food adding the most: {parts[0]}."
    return f" The planned foods adding the most: {parts[0]} and {parts[1]}."


def pattern_alerts(
    day: str | date,
    day_values: Mapping[str, Mapping[str, Any]],
    planned_totals: Mapping[str, Any],
    planned_sources: Iterable[tuple[str, Mapping[str, Any]]],
    targets: Mapping[str, Any],
    *,
    dialysis: str = "none",
    dialysis_days: Iterable[int] | None = None,
    about_tolerance_pct: Any = 0,
) -> list[dict[str, Any]]:
    """Warnings that join the last few days with what is planned for ``day`` (``DaySummary.pattern_alerts``).

    ``day_values`` maps ``YYYY-MM-DD`` to the totals each day stands for: what was eaten on days before today,
    eaten plus planned from today on (the caller decides, ``log.pattern_inputs``). It holds ``day`` itself and
    only days that have entries. ``planned_totals`` are the day's planned entries: a nutrient the plan does not
    add is never warned about. ``planned_sources`` are ``(food name, nutrients)`` of the day's planned entries,
    without low treatments (one is never named as something to cut).

    * Potassium, sodium, fluid: the day's total with the plan is over the limit and so were at least
      ``RECENT_HIGH_DAYS`` of the ``RECENT_DAYS`` days before it ("recent_days", level "over"). On hemodialysis
      with dialysis days set, the current interval instead: its total with the plan is over the limit times its
      days ("interdialytic", level "over"); a dialysis day itself is left to the day's own alert.
    * Phosphorus and protein: the average of the logged days of the last ``WEEKLY_DAYS`` days, with the plan, is
      over the target ("weekly_average", level "caution"; they are judged on the weekly average). An "about"
      target uses the person's tolerance (``nutrients.over_at``).

    Unknown values count as nothing, as everywhere: a total of known values that is already over stays over.
    Carbohydrate is not part of this, and nothing here blocks logging or planning.
    """
    d = to_date(day)
    sources = list(planned_sources)
    out: list[dict[str, Any]] = []
    interval = interdialytic_interval(d, dialysis_days) if dialysis == "hemodialysis" else None
    for key in DAILY_PATTERN_KEYS:
        limit = summary_target(key, targets.get(key))
        if limit is None or not float(planned_totals.get(key) or 0.0) > 0:
            continue
        nutrient = NUTRIENT_BY_KEY[key]
        unit = nutrient.unit
        if interval is not None:
            days = int(interval["days"])
            if days < 2:
                continue
            since = to_date(interval["since"])
            total = math.fsum(_day_value(day_values, since + timedelta(days=i), key) for i in range(days))
            cap = limit * days
            if total > cap:
                out.append({"level": "over", "nutrient": key, "kind": "interdialytic", "message": (
                    f"Since your last dialysis day ({WEEKDAY_NAMES[since.weekday()]}), {nutrient.label.lower()} adds up to "
                    f"{_fmt(key, total)} / {_fmt(key, cap)} {unit} with what's planned ({days} days at {_fmt(key, limit)} {unit})."
                    + _sources_text(key, sources))})
            continue
        total = _day_value(day_values, d, key)
        if not total > limit:
            continue
        high = sum(1 for back in range(1, RECENT_DAYS + 1) if _day_value(day_values, d - timedelta(days=back), key) > limit)
        if high >= RECENT_HIGH_DAYS:
            when = f"each of the last {RECENT_DAYS} days" if high == RECENT_DAYS else f"{high} of the last {RECENT_DAYS} days"
            out.append({"level": "over", "nutrient": key, "kind": "recent_days", "message": (
                f"{nutrient.label} was over your limit on {when}, and with what's planned it goes over again: "
                f"{_fmt(key, total)} / {_fmt(key, limit)} {unit}." + _sources_text(key, sources))})
    for key in WEEKLY_PATTERN_KEYS:
        target = summary_target(key, targets.get(key))
        if target is None or not float(planned_totals.get(key) or 0.0) > 0:
            continue
        lo, _ = target_bounds(targets.get(key))
        limit_at = over_at(key, lo, target, about_tolerance_pct)
        logged = [d - timedelta(days=back) for back in range(WEEKLY_DAYS) if (d - timedelta(days=back)).isoformat() in day_values]
        if len(logged) < WEEKLY_MIN_LOGGED_DAYS:
            continue
        average = math.fsum(_day_value(day_values, x, key) for x in logged) / len(logged)
        if average / target > limit_at:
            nutrient = NUTRIENT_BY_KEY[key]
            out.append({"level": "caution", "nutrient": key, "kind": "weekly_average", "message": (
                f"With what's planned, {nutrient.label.lower()} averages {_fmt(key, average)} {nutrient.unit} a day over "
                f"the {len(logged)} days you logged this past week, above your {_fmt(key, target)} {nutrient.unit} target. "
                f"It is judged on the weekly average, so lighter days around it balance it out."
                + _sources_text(key, sources))})
    return out
