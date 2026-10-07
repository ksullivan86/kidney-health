"""Lab analytes, units and conversions (``app/units.py``; note 05 §4.2 and §5.2 U1–U7)."""
from __future__ import annotations

import math

import pytest

from app import units


@pytest.mark.parametrize(
    "analyte, value, unit, canonical, shown",
    [
        ("creatinine", 106, "µmol/L", 1.199, "106 µmol/L = 1.20 mg/dL"),  # U1
        ("phosphate", 1.94, "mmol/L", 6.008, "1.94 mmol/L = 6.0 mg/dL"),  # U2 (note 05 §4.2 example)
        ("albumin", 34, "g/L", 3.4, "34 g/L = 3.4 g/dL"),  # U3
        ("uacr", 25, "mg/mmol", 221.239, "25 mg/mmol = 221.2 mg/g"),  # U4
        ("uacr", 3.0, "mg/mmol", 26.549, "3 mg/mmol = 26.5 mg/g"),  # U5
        ("a1c", 53, "mmol/mol", 6.999, "53 mmol/mol = 7.0 %"),  # U6
        ("potassium", 4.6, "mEq/L", 4.6, "4.6 mEq/L = 4.6 mmol/L"),
        ("bicarbonate", 21, "mmol/L", 21.0, "21.0 mmol/L"),
        ("cystatin_c", 1.6, "mg/L", 1.6, "1.60 mg/L"),
        ("egfr", 58, "mL/min/1.73 m²", 58.0, "58 mL/min/1.73 m²"),
    ],
)
def test_conversions_and_the_echo_shown_before_saving(analyte, value, unit, canonical, shown):
    result = units.convert(analyte, value, unit)
    assert result["value"] == pytest.approx(canonical, abs=0.001)
    assert result["unit"] == units.analyte_def(analyte).canonical_unit
    assert result["entered_value"] == value and result["entered_unit"] == unit
    assert result["display"] == shown


def test_factors_match_the_molar_masses():
    """Note 05 §10.1: creatinine 113.12 g/mol -> 88.4; phosphorus 30.97 g/mol -> 0.3229; A1c IFCC/NGSP master equation."""
    assert units.to_canonical("creatinine", 88.4, "µmol/L") == pytest.approx(1.0)
    assert units.to_canonical("phosphate", 0.3229, "mmol/L") == pytest.approx(1.0)
    assert units.to_canonical("uacr", 0.113, "mg/mmol") == pytest.approx(1.0)
    assert units.to_canonical("albumin", 40, "g/L") == pytest.approx(4.0)
    assert units.to_canonical("a1c", 48, "mmol/mol") == pytest.approx(48 / 10.929 + 2.15)


@pytest.mark.parametrize(
    "analyte, typed, expected",
    [
        ("creatinine", "umol/l", "µmol/L"),
        ("creatinine", "μmol/L", "µmol/L"),  # Greek mu
        ("creatinine", "mcmol/L", "µmol/L"),
        ("creatinine", " MG/DL ", "mg/dL"),
        ("potassium", "meq/l", "mEq/L"),
        ("egfr", "mL/min/1.73m2", "mL/min/1.73 m²"),
        ("a1c", "%", "%"),
    ],
)
def test_unit_spellings_are_normalised(analyte, typed, expected):
    assert units.canonical_unit_name(analyte, typed) == expected


@pytest.mark.parametrize(
    "args, message",
    [
        (("potassium", 4.2, "mg/dL"), "not accepted for potassium; use one of: mmol/L, mEq/L"),
        (("sodium", 140, "mmol/L"), "unknown analyte 'sodium'"),
        (("potassium", 12, "mmol/L"), "Potassium 12.0 mmol/L is outside the plausible range 1.5–9 mmol/L"),
        (("phosphate", 15, "mmol/L"), "Phosphate 15 mmol/L (46.5 mg/dL) is outside the plausible range 0.5–20 mg/dL"),
        (("creatinine", 0.05, "mg/dL"), "outside the plausible range 0.1–25 mg/dL"),
        (("a1c", 25, "%"), "outside the plausible range 3–20 %"),
        (("albumin", -1, "g/dL"), "must be a non-negative number"),
        (("albumin", math.nan, "g/dL"), "must be a non-negative number"),
        (("albumin", math.inf, "g/dL"), "must be a non-negative number"),
    ],
)
def test_bad_entries_are_refused_with_an_actionable_message(args, message):
    with pytest.raises(units.UnitError, match=None) as info:
        units.convert(*args)
    assert message in str(info.value)
    if "plausible" in message:
        assert "check the number and the unit" in str(info.value)


def test_plausibility_is_judged_on_the_shown_value():
    assert units.convert("potassium", 9.04, "mmol/L")["display"] == "9.0 mmol/L"
    assert units.convert("potassium", 1.45, "mmol/L")["display"] == "1.5 mmol/L"
    with pytest.raises(units.UnitError):
        units.convert("potassium", 9.05, "mmol/L")
    with pytest.raises(units.UnitError):
        units.convert("potassium", 1.44, "mmol/L")
    assert units.convert("uacr", 0, "mg/g")["value"] == 0  # 0 is a valid (A1) result


def test_every_accepted_unit_converts_a_plausible_value():
    for analyte in units.ANALYTE_KEYS:
        a = units.analyte_def(analyte)
        middle = sum(a.plausible) / 2
        for unit, conversion in a.units.items():
            # invert the conversion for a value that lands in the middle of the plausible range
            entered = ((middle - conversion.add) * conversion.div) / conversion.mul
            result = units.convert(analyte, entered, unit)
            assert result["value"] == pytest.approx(middle), (analyte, unit)


def test_display_and_format_use_half_up_on_the_analyte_decimals():
    assert units.format_value("phosphate", 4.45) == "4.5"
    assert units.format_value("creatinine", 1.005) == "1.01"
    assert units.format_value("egfr", 59.5) == "60"
    assert units.display_value("potassium", 5.05) == 5.1


def test_default_unit_follows_the_unit_system_setting():
    assert units.default_unit("creatinine", "us") == "mg/dL"
    assert units.default_unit("creatinine", "si") == "µmol/L"
    assert units.default_unit("phosphate", "si") == "mmol/L"
    assert units.default_unit("albumin", "si") == "g/L"
    assert units.default_unit("uacr", "si") == "mg/mmol"
    assert units.default_unit("a1c", "si") == "mmol/mol"
    assert units.default_unit("potassium", "si") == units.default_unit("potassium", "us") == "mmol/L"
    for analyte in units.ANALYTE_KEYS:  # the SI default is always an accepted unit
        assert units.default_unit(analyte, "si") in units.analyte_def(analyte).units


def test_freshness_windows_and_overrides():
    """Note 05 §4.2 [OPINION] windows; only potassium, phosphate, albumin and bicarbonate are settings."""
    assert {a: units.fresh_days(a) for a in units.ANALYTE_KEYS} == {
        "potassium": 90, "phosphate": 90, "albumin": 180, "bicarbonate": 180, "uacr": 365,
        "creatinine": 365, "cystatin_c": 365, "egfr": 365, "a1c": 365,
    }
    assert units.fresh_days("potassium", {"potassium": 30}) == 30
    assert units.fresh_days("phosphate", {"potassium": 30}) == 90
    assert set(units.CONFIGURABLE_FRESHNESS) == {"potassium", "phosphate", "albumin", "bicarbonate"}


def test_unit_table_is_plain_data_for_the_browser_twin():
    table = units.unit_table()
    assert [row["key"] for row in table] == list(units.ANALYTE_KEYS)
    phosphate = next(row for row in table if row["key"] == "phosphate")
    assert phosphate["units"]["mmol/L"] == {"mul": 1.0, "div": 0.3229, "add": 0.0}
    assert phosphate["plausible"] == [0.5, 20.0] and phosphate["si_unit"] == "mmol/L"


DATES = ["2026-10-07", "2026-09-01", "2026-01-31", "2027-12-25", "0999-05-09", "2026-13-01", "2026-00-10", "2026-1-01",
         "2026-10-07T10:00", "", "not a date", "٢٠٢٦-١٠-٠٧"]


def test_lab_dates_in_messages_read_like_the_app_shows_them() -> None:
    """Review L12: messages said "on 2026-10-07" beside the history's "Oct 7, 2026"."""
    assert [units.display_date(d) for d in DATES[:5]] == ["Oct 7, 2026", "Sep 1, 2026", "Jan 31, 2026", "Dec 25, 2027", "May 9, 999"]
    assert [units.display_date(d) for d in DATES[5:]] == DATES[5:]  # anything else is left as it is
    assert units.display_date(None) == ""


def test_the_browser_twin_formats_lab_dates_the_same_way() -> None:
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    assert node, "Node.js 22 is needed to run the browser twin (CLAUDE.md, Parity)"
    root = Path(__file__).resolve().parents[1]
    script = (
        "const fs = require('fs'); const vm = require('vm'); const ctx = vm.createContext({});"
        "for (const f of ['rules', 'kidney_function']) vm.runInContext(fs.readFileSync("
        f"{json.dumps(str(root / 'app' / 'static' / 'js' / 'engine'))} + '/' + f + '.js', 'utf8'), ctx);"
        "const K = vm.runInContext('globalThis.KH.kidney', ctx);"
        f"process.stdout.write(JSON.stringify({json.dumps(DATES + [None])}.map((d) => K.displayDate(d))));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, check=True).stdout
    assert json.loads(out) == [units.display_date(d) for d in DATES + [None]]
