"""Reading a lab report from a photo: the checks the app makes in code on what the model copied (pure; no I/O).

The model only copies printed result lines (``{analyte, value, unit, taken_on}``, :mod:`app.ai.schemas`). It never says
whether a value is normal, high or low and it never decides what is saved. This module turns its answer into *proposed*
rows for the person to check; the route that calls it writes nothing. Saving is the person's tick on a row and the
ordinary ``POST /api/labs/import``, which checks every row again.

What happens to each copied line, in this order:

1. ``analyte`` must be one of the app's own lab test codes (:data:`app.units.ANALYTES`); anything else is dropped and
   counted as ``unknown_analyte`` ("N lines were not recognised");
2. ``unit`` must be a unit the app's conversion knows for that test (:func:`app.units.canonical_unit_name`); anything
   else is dropped and counted as ``unknown_unit`` (a value is never guessed to be in the usual unit);
3. the value is checked with **the same validation as ``POST /api/labs``** (:class:`app.models.LabCreate`: a non-negative
   number, converted and inside the test's plausible range); a failure is dropped and counted as ``out_of_range``;
4. the date is read only when it cannot mean two things (:func:`parse_printed_date`) and must not be in the future
   (:func:`app.models.validate_past_date`); otherwise ``taken_on`` is ``null`` and ``date_problem`` says why, so the person
   types the date. The printed text of the date is shown beside it (letters, digits and ``/ - . , :`` only).

Nothing the model wrote reaches the person as free text: the test is a code the app labels itself, the value a number, the
unit the app's own spelling, the date a calendar date the app parsed.
"""
from __future__ import annotations

import re
from datetime import date as _date
from typing import Any, Mapping

from pydantic import ValidationError

from .. import units
from ..models import LabCreate, validate_past_date
from ..textclean import clean_text
from . import schemas

MAX_PRINTED_DATE = 40  # the printed date shown beside the date field
DROPPED_KEYS: tuple[str, ...] = ("unknown_analyte", "unknown_unit", "out_of_range")
NOTICE = "Read by AI from your photo. Check each value against the report before you tick it."
NOT_A_REPORT = "This does not look like a lab report."
UNREADABLE = "The report could not be read; try a sharper photo with less glare, cropped to the results table."
NO_RESULTS = "No result the app knows was found in this photo."
DATE_PROBLEMS: Mapping[str, str] = {
    "missing": "No date was read from the photo. Enter the date of the test.",
    "ambiguous": "The date on the report could mean two different days. Enter the date of the test.",
    "unreadable": "The date on the report could not be read. Enter the date of the test.",
    "future": "The date read from the photo is in the future. Enter the date of the test.",
    "too_old": "The date read from the photo is before 1900. Enter the date of the test.",
}

_MONTHS = {name: i for i, names in enumerate(
    (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
     ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")), start=1)
    for name in names}
_SEPARATORS = re.compile(r"[ /.,:\-]+")
_DATE_TOKEN = re.compile(r"^(?:\d{1,4}|\d{1,2}(?:st|nd|rd|th)|t|am|pm)$")
MAX_DATE_TOKENS = 8
_YMD = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ,].*)?$")
_NUMERIC = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[T ,].*)?$")
_DAY_NAME_YEAR = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[ -]([A-Za-z]{3,9})\.?,?[ -](\d{4})(?:[T ,].*)?$")
_NAME_DAY_YEAR = re.compile(r"^([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})(?:[T ,].*)?$")


def clean_printed_date(text: str | None) -> str | None:
    """The date as printed, for display next to the date field; ``None`` unless it is made of nothing but numbers, month names
    and ``/ . , : -`` (and has a number in it). The date field is not a place for words: a sentence, a URL or markup the model
    put there is not shown to the person (it is still not used as a date either)."""
    cleaned = clean_text(text, max_len=MAX_PRINTED_DATE) if text else None
    if not cleaned:
        return None
    tokens = [t for t in _SEPARATORS.split(cleaned) if t]
    if not tokens or len(tokens) > MAX_DATE_TOKENS or not any(t.isdigit() for t in tokens):
        return None
    if not all(_DATE_TOKEN.match(t.lower()) or t.lower() in _MONTHS for t in tokens):
        return None
    return cleaned


def parse_printed_date(text: str | None) -> tuple[str | None, str | None]:
    """``(YYYY-MM-DD, None)`` for a date that means one day, else ``(None, problem)`` with the problem one of ``missing``,
    ``ambiguous`` (``03/04/2026``: March 4 or April 3), ``unreadable`` (not a real date, a two-digit year, a sentence).

    Read: ``2026-10-07``, ``2026/10/07``, ``7 Oct 2026``, ``Oct 7, 2026`` and ``07/10/2026`` only when a part above 12 or two
    equal parts settle which is the day. The future and the distant past are judged by the caller."""
    printed = clean_printed_date(text)
    if not printed:
        return None, "missing" if not (text or "").strip() else "unreadable"
    m = _YMD.match(printed)
    if m:
        year, month, day = (int(g) for g in m.groups())
        return _calendar(year, month, day)
    m = _NUMERIC.match(printed)
    if m:
        first, second, year = (int(g) for g in m.groups())
        if first > 12 and second <= 12:
            return _calendar(year, second, first)  # day/month/year
        if second > 12 and first <= 12:
            return _calendar(year, first, second)  # month/day/year
        if first == second:
            return _calendar(year, first, second)
        if first <= 12 and second <= 12:
            return None, "ambiguous"
        return None, "unreadable"
    m = _DAY_NAME_YEAR.match(printed)
    if m and m.group(2).lower() in _MONTHS:
        return _calendar(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = _NAME_DAY_YEAR.match(printed)
    if m and m.group(1).lower() in _MONTHS:
        return _calendar(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None, "unreadable"


def _calendar(year: int, month: int, day: int) -> tuple[str | None, str | None]:
    try:
        return _date(year, month, day).isoformat(), None
    except ValueError:
        return None, "unreadable"


def _check_date(iso: str | None) -> tuple[str | None, str | None]:
    """The date if it passes the check ``POST /api/labs`` makes (a real day, not in the future, 1900 or later)."""
    if iso is None:
        return None, None
    try:
        validate_past_date(iso)
    except ValueError as exc:
        return None, "future" if "future" in str(exc) else "too_old"
    return iso, None


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def dropped_notes(dropped: Mapping[str, int]) -> list[str]:
    """The sentences that say how many copied lines the app left out (empty when none)."""
    out = []
    n = dropped.get("unknown_analyte", 0)
    if n:
        out.append(f"{plural(n, 'line was', 'lines were')} not recognised: it is not one of the tests this app keeps.")
    n = dropped.get("unknown_unit", 0)
    if n:
        out.append(f"{plural(n, 'line was', 'lines were')} left out because its unit is not one the app knows for that test.")
    n = dropped.get("out_of_range", 0)
    if n:
        out.append(f"{plural(n, 'line was', 'lines were')} left out because the number is outside the range the app accepts "
                   "(check the number and the unit on the report).")
    return out


def judge(answer: schemas.LabReportAnswer) -> dict[str, Any]:
    """Turn the model's copied lines into proposed rows (nothing is saved here)."""
    dropped = {key: 0 for key in DROPPED_KEYS}
    if answer.status == "not_a_lab_report":
        return {"status": "not_a_lab_report", "message": NOT_A_REPORT, "rows": [], "dropped": dropped, "dropped_notes": []}
    if answer.status == "unreadable":
        return {"status": "unreadable", "message": UNREADABLE, "rows": [], "dropped": dropped, "dropped_notes": []}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, float, str, str | None]] = set()
    for line in answer.rows:
        analyte = line.analyte.strip().lower()
        if analyte not in units.ANALYTES:
            dropped["unknown_analyte"] += 1
            continue
        try:
            unit = units.canonical_unit_name(analyte, line.unit)
        except units.UnitError:
            dropped["unknown_unit"] += 1
            continue
        iso, problem = parse_printed_date(line.taken_on)
        iso, late = _check_date(iso)
        problem = late or problem
        try:  # the very validation POST /api/labs makes (a date is needed to make one: today stands in for a missing one)
            LabCreate.model_validate({"analyte": analyte, "value": line.value, "unit": unit,
                                      "taken_on": iso or _date.today().isoformat()})
            converted = units.convert(analyte, line.value, unit)
        except (ValidationError, units.UnitError):
            dropped["out_of_range"] += 1
            continue
        key = (analyte, float(line.value), unit, iso)
        if key in seen:  # the same line read twice
            continue
        seen.add(key)
        rows.append({
            "analyte": analyte,
            "label": units.analyte_def(analyte).label,
            "value": float(line.value),
            "unit": unit,
            "display": converted["display"],
            "taken_on": iso,
            "printed_date": clean_printed_date(line.taken_on),
            "date_problem": problem,
            "date_note": DATE_PROBLEMS.get(problem) if problem else None,  # what to tell the person about the date, in the app's words
        })
    notes = dropped_notes(dropped)
    if not rows:
        return {"status": "no_results", "message": NO_RESULTS, "rows": [], "dropped": dropped, "dropped_notes": notes}
    return {"status": "ok", "rows": rows, "dropped": dropped, "dropped_notes": notes, "notice": NOTICE}
