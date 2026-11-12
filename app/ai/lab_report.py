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


def judge(answer: schemas.LabReportAnswer, *, date_notes: Mapping[str, str] = DATE_PROBLEMS) -> dict[str, Any]:
    """Turn the model's copied lines into proposed rows (nothing is saved here). ``date_notes`` are the sentences about a date
    the person must type (the text version says "from the page's text" instead of "from the photo")."""
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
            "date_note": date_notes.get(problem) if problem else None,  # what to tell the person about the date, in the app's words
        })
    notes = dropped_notes(dropped)
    if not rows:
        return {"status": "no_results", "message": NO_RESULTS, "rows": [], "dropped": dropped, "dropped_notes": notes}
    return {"status": "ok", "rows": rows, "dropped": dropped, "dropped_notes": notes, "notice": NOTICE}


# --------------------------------------------------------------------------- #
# The text of a PDF page (design note 36)
# --------------------------------------------------------------------------- #

MAX_TEXT_CHARS = 20_000  # one page's text, as the browser sends it
TEXT_NOTICE = "Read by AI from the text of your PDF. Check each value against the report before you tick it."
TEXT_UNREADABLE = "The text of this page could not be read as a lab report. Try reading it as a picture."
TEXT_NO_RESULTS = "No result the app knows was found in this page's text."
TEXT_DATE_PROBLEMS: Mapping[str, str] = {key: text.replace("from the photo", "from the page's text") for key, text in DATE_PROBLEMS.items()}
NOT_IN_TEXT = "left out because its number is not written in the page's text."
# A number as written: 5.4, 0.9, 88, 1,250 (thousands) or 1,2 (a decimal comma); never the middle of a longer number.
_NUMBER = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*(?!\d)")
_SPACES = re.compile(r"\s+")


def numbers_in(text: str) -> set[float]:
    """Every number written in ``text``, read each way it can be read: ``1,250`` is 1250 (and 1.25 with a decimal comma), ``1,2``
    is 1.2 (and 12), ``5.4`` is 5.4. A row's value must be one of these to be kept (:func:`judge_text`)."""
    out: set[float] = set()
    for token in _NUMBER.findall(text):
        readings = [token.replace(",", "")]
        if token.count(",") == 1 and "." not in token:
            readings.append(token.replace(",", "."))
        for reading in readings:
            if reading.count(".") <= 1:
                out.add(float(reading))
    return out


def _fold(text: str) -> str:
    return _SPACES.sub(" ", text).strip().casefold()


def judge_text(answer: schemas.LabReportAnswer, text: str) -> dict[str, Any]:
    """The lines the model copied from the text of a PDF page, checked against that text first (design note 36 §4.3).

    * a row whose value is not a number written in ``text`` is dropped and counted as ``not_in_text``: the model may copy, never
      invent, compute or round;
    * a row whose date is not written in ``text`` (spaces and case aside) loses its date, so the person types it;
    * then the photo's own checks (:func:`judge`): the app's tests and units, the checks of ``POST /api/labs``, dates that cannot
      mean two days."""
    written = numbers_in(text)
    folded = _fold(text)
    kept: list[schemas.LabReportRow] = []
    not_in_text = 0
    for line in answer.rows:
        value = float(line.value)
        if not any(abs(value - n) <= 1e-9 * max(1.0, abs(n)) for n in written):
            not_in_text += 1
            continue
        if line.taken_on is not None and _fold(line.taken_on) not in folded:
            line = line.model_copy(update={"taken_on": None})
        kept.append(line)
    verdict = judge(answer.model_copy(update={"rows": kept}), date_notes=TEXT_DATE_PROBLEMS)
    verdict["dropped"] = {**verdict["dropped"], "not_in_text": not_in_text}
    if not_in_text:
        verdict["dropped_notes"] = [*verdict["dropped_notes"], f"{plural(not_in_text, 'line was', 'lines were')} {NOT_IN_TEXT}"]
    if verdict["status"] == "unreadable":
        verdict["message"] = TEXT_UNREADABLE
    elif verdict["status"] == "no_results":
        verdict["message"] = TEXT_NO_RESULTS
    elif verdict["status"] == "ok":
        verdict["notice"] = TEXT_NOTICE
    return verdict
