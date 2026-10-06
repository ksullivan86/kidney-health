"""Lab analytes, their units and conversions (note 05 §4.2, §5.2). Pure functions, no I/O.

Every result is stored in its analyte's **canonical unit** (the US unit the formulas use) together
with the value and unit the person typed. Conversions are written as data (multiply, divide, add)
so the browser twin (``js/engine/kidney_function.js``) performs exactly the same floating-point
operations; ``tests/data/kidney_function_vectors.json`` pins both sides.

Factors (KDIGO 2024 conversion table; re-derived from molar masses in note 05 §10.1):

* creatinine mg/dL × 88.4 = µmol/L (KDIGO's PDF prints "mmol/l", a lost µ);
* phosphate mg/dL × 0.3229 = mmol/L;
* potassium and bicarbonate mmol/L = mEq/L (monovalent);
* albumin g/dL × 10 = g/L;
* UACR mg/g × 0.113 = mg/mmol;
* HbA1c NGSP % = IFCC mmol/mol ÷ 10.929 + 2.15.

Categories are judged on the **displayed** value (rounded half-up, :data:`DISPLAY_DECIMALS`), like
the per-serving thresholds in :mod:`app.nutrients`, so a level always matches the number shown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .nutrients import _half_up


@dataclass(frozen=True)
class Conversion:
    """``canonical = value * mul / div + add`` (each step skipped when it is the identity)."""

    mul: float = 1.0
    div: float = 1.0
    add: float = 0.0

    def apply(self, value: float) -> float:
        out = float(value)
        if self.mul != 1.0:
            out = out * self.mul
        if self.div != 1.0:
            out = out / self.div
        if self.add != 0.0:
            out = out + self.add
        return out


@dataclass(frozen=True)
class Analyte:
    """One lab test the app understands (note 05 §4.2 table)."""

    key: str
    label: str
    canonical_unit: str
    units: dict[str, Conversion]  # accepted unit (display spelling) -> conversion to canonical
    plausible: tuple[float, float]  # canonical unit; outside -> refused as a likely unit or typing mistake
    fresh_days: int | None  # how long a result drives targets / kidney function (None: never)
    decimals: int  # displayed decimals in the canonical unit
    si_unit: str  # default unit picker for user.units.labs = "si" ("us" uses the canonical unit)


IDENTITY = Conversion()

ANALYTES: dict[str, Analyte] = {
    a.key: a
    for a in (
        Analyte("potassium", "Potassium", "mmol/L", {"mmol/L": IDENTITY, "mEq/L": IDENTITY}, (1.5, 9.0), 90, 1, "mmol/L"),
        Analyte("phosphate", "Phosphate", "mg/dL", {"mg/dL": IDENTITY, "mmol/L": Conversion(div=0.3229)}, (0.5, 20.0), 90, 1, "mmol/L"),
        Analyte("albumin", "Albumin (blood)", "g/dL", {"g/dL": IDENTITY, "g/L": Conversion(mul=0.1)}, (0.5, 6.5), 180, 1, "g/L"),
        Analyte("bicarbonate", "Bicarbonate (CO2)", "mmol/L", {"mmol/L": IDENTITY, "mEq/L": IDENTITY}, (5.0, 50.0), 180, 1, "mmol/L"),
        Analyte("uacr", "Urine albumin-to-creatinine ratio", "mg/g", {"mg/g": IDENTITY, "mg/mmol": Conversion(div=0.113)}, (0.0, 50000.0), 365, 1, "mg/mmol"),
        Analyte("creatinine", "Creatinine (blood)", "mg/dL", {"mg/dL": IDENTITY, "µmol/L": Conversion(div=88.4)}, (0.1, 25.0), 365, 2, "µmol/L"),
        Analyte("cystatin_c", "Cystatin C", "mg/L", {"mg/L": IDENTITY}, (0.2, 10.0), 365, 2, "mg/L"),
        Analyte("egfr", "eGFR (reported by the lab)", "mL/min/1.73 m²", {"mL/min/1.73 m²": IDENTITY}, (1.0, 200.0), 365, 0, "mL/min/1.73 m²"),
        Analyte("a1c", "HbA1c", "%", {"%": IDENTITY, "mmol/mol": Conversion(div=10.929, add=2.15)}, (3.0, 20.0), 365, 1, "mmol/mol"),
    )
}
ANALYTE_KEYS: tuple[str, ...] = tuple(ANALYTES)
UNIT_SYSTEMS: tuple[str, ...] = ("us", "si")

# Settings that may change a freshness window (note 05 §4.9); the others are fixed.
CONFIGURABLE_FRESHNESS: tuple[str, ...] = ("potassium", "phosphate", "albumin", "bicarbonate")


class UnitError(ValueError):
    """Unknown analyte or unit, or an implausible value."""


def _normalise_unit(unit: str) -> str:
    text = str(unit).strip().replace("μ", "µ").replace(" ", "").lower()  # Greek mu -> micro sign
    if text.startswith("umol") or text.startswith("mcmol"):
        text = "µmol" + text.split("mol", 1)[1]
    return text.replace("²", "2")


def canonical_unit_name(analyte: str, unit: str) -> str:
    """The display spelling of ``unit`` for ``analyte`` (``"umol/l"`` -> ``"µmol/L"``); raises :class:`UnitError`."""
    a = analyte_def(analyte)
    wanted = _normalise_unit(unit)
    for name in a.units:
        if _normalise_unit(name) == wanted:
            return name
    raise UnitError(f"unit {unit!r} is not accepted for {a.key}; use one of: {', '.join(a.units)}")


def analyte_def(analyte: str) -> Analyte:
    """The :class:`Analyte` for a key; raises :class:`UnitError` for an unknown one."""
    try:
        return ANALYTES[analyte]
    except KeyError:
        raise UnitError(f"unknown analyte {analyte!r}; use one of: {', '.join(ANALYTE_KEYS)}") from None


def to_canonical(analyte: str, value: float, unit: str) -> float:
    """``value`` in ``unit`` converted to the analyte's canonical unit (no rounding, no range check)."""
    a = analyte_def(analyte)
    name = canonical_unit_name(analyte, unit)
    v = float(value)
    if not math.isfinite(v):
        raise UnitError(f"{a.label} must be a finite number")
    return a.units[name].apply(v)


def display_value(analyte: str, value: float) -> float:
    """The canonical value rounded half-up to the analyte's displayed decimals."""
    return _half_up(float(value), analyte_def(analyte).decimals)


def format_value(analyte: str, value: float) -> str:
    """``"6.0"``, ``"1.20"``, ``"58"``: the canonical value as the app shows it."""
    a = analyte_def(analyte)
    return f"{display_value(analyte, value):.{a.decimals}f}"


def check_plausible(analyte: str, canonical_value: float, entered: str | None = None) -> None:
    """Raise :class:`UnitError` when a canonical value is outside the plausible range (note 05 §4.2).

    ``entered`` (e.g. ``"15 mmol/L"``) is named in the message when the person typed another unit,
    because a value in the wrong unit is the usual cause.
    """
    a = analyte_def(analyte)
    lo, hi = a.plausible
    v = float(canonical_value)
    # Judged on the shown value, like every other threshold, so 9.04 mmol/L (shown 9.0) is accepted.
    if not math.isfinite(v) or display_value(analyte, v) < lo or display_value(analyte, v) > hi:
        shown = f"{format_value(analyte, v)} {a.canonical_unit}" if math.isfinite(v) else str(v)
        what = f"{entered} ({shown})" if entered else shown
        raise UnitError(
            f"{a.label} {what} is outside the plausible range {_fmt_plain(lo)}–{_fmt_plain(hi)} {a.canonical_unit}; "
            "check the number and the unit"
        )


def _fmt_plain(v: float) -> str:
    return f"{v:g}" if math.isfinite(v) else str(v)


def convert(analyte: str, value: float, unit: str) -> dict[str, Any]:
    """Validate and convert one entered result.

    Returns ``{"analyte", "value" (canonical), "unit" (canonical), "entered_value", "entered_unit"
    (display spelling), "display"}`` where ``display`` echoes the conversion the way the UI shows it
    before saving: ``"1.94 mmol/L = 6.0 mg/dL"``, or just ``"6.0 mg/dL"`` for the canonical unit.
    """
    a = analyte_def(analyte)
    entered_unit = canonical_unit_name(analyte, unit)
    entered = float(value)
    if not math.isfinite(entered) or entered < 0:
        raise UnitError(f"{a.label} must be a non-negative number")
    canonical = a.units[entered_unit].apply(entered)
    check_plausible(analyte, canonical, None if entered_unit == a.canonical_unit else f"{entered:g} {entered_unit}")
    shown = f"{format_value(analyte, canonical)} {a.canonical_unit}"
    display = shown if entered_unit == a.canonical_unit else f"{entered:g} {entered_unit} = {shown}"
    return {
        "analyte": a.key,
        "value": canonical,
        "unit": a.canonical_unit,
        "entered_value": entered,
        "entered_unit": entered_unit,
        "display": display,
    }


def default_unit(analyte: str, system: str = "us") -> str:
    """The unit picker's default for ``user.units.labs`` (``us``: the canonical unit; ``si``: SI)."""
    a = analyte_def(analyte)
    return a.si_unit if system == "si" else a.canonical_unit


def fresh_days(analyte: str, overrides: dict[str, int] | None = None) -> int | None:
    """Freshness window in days (``overrides`` from the ``targets.lab_fresh_days.*`` settings)."""
    a = analyte_def(analyte)
    if overrides and analyte in overrides and overrides[analyte] is not None:
        return int(overrides[analyte])
    return a.fresh_days


def unit_table() -> list[dict[str, Any]]:
    """The analyte table as plain data (parity vectors and the docs)."""
    return [
        {
            "key": a.key,
            "label": a.label,
            "canonical_unit": a.canonical_unit,
            "units": {name: {"mul": c.mul, "div": c.div, "add": c.add} for name, c in a.units.items()},
            "plausible": list(a.plausible),
            "fresh_days": a.fresh_days,
            "decimals": a.decimals,
            "si_unit": a.si_unit,
        }
        for a in ANALYTES.values()
    ]
