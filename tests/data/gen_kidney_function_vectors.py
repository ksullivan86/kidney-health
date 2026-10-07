#!/usr/bin/env python3
"""Generate tests/data/kidney_function_vectors.json: parity vectors for the browser twin of the lab maths.

    python3 tests/data/gen_kidney_function_vectors.py           # rewrite the file
    python3 tests/data/gen_kidney_function_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own pure functions in ``app/units.py`` (analytes, unit conversion,
plausibility, the echo shown before saving) and ``app/kidney_function.py`` (CKD-EPI equations, G and A
categories, age, and the kidney-function card of ``GET /api/labs/kidney-function``), and replayed on
the JavaScript side against ``app/static/js/engine/kidney_function.js`` (ARCHITECTURE.md "Frontend
modules"). pytest checks the file is current (``tests/test_targets_vectors.py``). ``today`` is
always given. Sections:

* ``unit_table``: every analyte with its accepted units and conversions (``{mul, div, add}``:
  ``canonical = value * mul / div + add``, each step skipped when it is the identity), plausible
  range, freshness window, shown decimals and SI default unit;
* ``conversion_cases``: ``units.convert(analyte, value, unit)`` → the stored values and the echo, or
  ``{"error": message}``;
* ``egfr_cases``: the three equations (unrounded value, compare within 1e-9 relative; the rounded
  integer and the category exactly), or ``{"error": message}`` for inputs they refuse;
* ``category_cases``, ``albuminuria_cases``, ``age_cases``;
* ``assess_cases``: the whole card for a profile and a list of stored lab rows.

Standard library only (plus the app package on the path).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "kidney_function_vectors.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import kidney_function as kf  # noqa: E402
from app import units  # noqa: E402

TODAY = "2026-10-05"


def conversion_cases() -> list[dict[str, Any]]:
    inputs: list[tuple[str, Any, str]] = [
        ("creatinine", 106, "µmol/L"), ("creatinine", 106, "umol/l"), ("creatinine", 106, "μmol/L"), ("creatinine", 1.2, "mg/dL"),
        ("phosphate", 1.94, "mmol/L"), ("phosphate", 6.1, "mg/dL"), ("albumin", 34, "g/L"), ("albumin", 3.4, "g/dL"),
        ("uacr", 25, "mg/mmol"), ("uacr", 3.0, "mg/mmol"), ("uacr", 0, "mg/g"), ("uacr", 450, "mg/g"),
        ("a1c", 53, "mmol/mol"), ("a1c", 7.4, "%"), ("potassium", 4.6, "mEq/L"), ("potassium", 9.04, "mmol/L"),
        ("potassium", 1.45, "mmol/L"), ("bicarbonate", 21, "meq/l"), ("bicarbonate", 24.5, "mmol/L"), ("cystatin_c", 1.6, "mg/L"), ("egfr", 58, "mL/min/1.73 m²"),
        ("egfr", 58, "ml/min/1.73m2"),
        # refused
        ("potassium", 9.05, "mmol/L"), ("potassium", 1.44, "mmol/L"), ("potassium", 42, "mmol/L"), ("phosphate", 15, "mmol/L"),
        ("creatinine", 3000, "µmol/L"), ("creatinine", 0.05, "mg/dL"), ("a1c", 25, "%"), ("potassium", 4.2, "mg/dL"),
        ("sodium", 140, "mmol/L"), ("albumin", -1, "g/dL"), ("albumin", math.inf, "g/dL"),
    ]
    out = []
    for analyte, value, unit in inputs:
        case: dict[str, Any] = {"analyte": analyte, "value": value if math.isfinite(value) else "Infinity", "unit": unit}
        try:
            case["expect"] = units.convert(analyte, value, unit)
        except units.UnitError as exc:
            case["expect"] = {"error": str(exc)}
        out.append(case)
    return out


def egfr_cases() -> list[dict[str, Any]]:
    inputs: list[tuple[str, dict[str, Any]]] = [
        ("cr", {"creatinine": 1.2, "age": 50, "sex": "female"}),  # E1
        ("cr", {"creatinine": 1.2, "age": 50, "sex": "male"}),  # E2
        ("cr", {"creatinine": 2.0, "age": 70, "sex": "male"}),  # E3
        ("cr", {"creatinine": 106 / 88.4, "age": 65, "sex": "female"}),  # E4
        ("cr", {"creatinine": 0.6, "age": 30, "sex": "female"}),  # E5
        ("cr_cys", {"creatinine": 1.5, "cystatin_c": 1.6, "age": 60, "sex": "male"}),  # E6
        ("cys", {"cystatin_c": 1.2, "age": 40, "sex": "female"}),  # E7
        ("cr", {"creatinine": 1.1, "age": 60, "sex": "female"}),  # E8
        ("cr", {"creatinine": 1.1, "age": 60, "sex": "male"}),  # E9
        ("cr", {"creatinine": 4.8, "age": 75, "sex": "female"}),  # E10
        ("cr", {"creatinine": 0.9, "age": 18, "sex": "male"}), ("cr", {"creatinine": 0.7, "age": 18, "sex": "female"}),
        ("cr", {"creatinine": 0.5, "age": 95, "sex": "male"}), ("cr", {"creatinine": 12.0, "age": 40, "sex": "male"}),
        ("cr_cys", {"creatinine": 0.6, "cystatin_c": 0.6, "age": 25, "sex": "female"}),
        ("cr_cys", {"creatinine": 0.9, "cystatin_c": 0.8, "age": 40, "sex": "male"}),
        ("cr_cys", {"creatinine": 3.2, "cystatin_c": 2.9, "age": 66, "sex": "female"}),
        ("cys", {"cystatin_c": 0.8, "age": 40, "sex": "male"}), ("cys", {"cystatin_c": 0.5, "age": 33, "sex": "male"}),
        ("cys", {"cystatin_c": 4.0, "age": 80, "sex": "female"}),
        # refused
        ("cr", {"creatinine": 1.0, "age": 17, "sex": "male"}), ("cr", {"creatinine": 1.0, "age": 40, "sex": "unspecified"}),
        ("cr", {"creatinine": 0, "age": 40, "sex": "male"}), ("cys", {"cystatin_c": -1, "age": 40, "sex": "female"}),
    ]
    out = []
    for equation, args in inputs:
        case: dict[str, Any] = {"equation": equation, **args}
        try:
            if equation == "cr":
                value = kf.egfr_cr(args["creatinine"], args["age"], args["sex"])
            elif equation == "cr_cys":
                value = kf.egfr_cr_cys(args["creatinine"], args["cystatin_c"], args["age"], args["sex"])
            else:
                value = kf.egfr_cys(args["cystatin_c"], args["age"], args["sex"])
            case["expect"] = {"unrounded": value, "rounded": kf.round_egfr(value), "category": kf.gfr_category(value)}
        except kf.KidneyFunctionError as exc:
            case["expect"] = {"error": str(exc)}
        out.append(case)
    return out


def lab(i: int, analyte: str, value: float, taken_on: str = "2026-10-01", entered: float | None = None, unit: str | None = None) -> dict[str, Any]:
    return {"id": i, "analyte": analyte, "value": value, "entered_value": value if entered is None else entered,
            "entered_unit": unit or units.analyte_def(analyte).canonical_unit, "taken_on": taken_on}


def assess_cases() -> list[dict[str, Any]]:
    base = {"ckd_stage": "3b", "birth_month": "1976-10", "sex": "female"}
    inputs: list[tuple[str, dict[str, Any], list[dict[str, Any]], str]] = [
        ("no results", base, [], TODAY),
        ("creatinine", base, [lab(1, "creatinine", 1.2)], TODAY),
        ("lab eGFR same day wins", base, [lab(1, "creatinine", 1.2), lab(2, "egfr", 41)], TODAY),
        ("newer creatinine beats older lab eGFR", base, [lab(1, "egfr", 41, "2026-06-01"), lab(2, "creatinine", 1.2, "2026-09-01")], TODAY),
        ("creatinine and cystatin same day", {**base, "birth_month": "1966-01", "sex": "male"},
         [lab(1, "creatinine", 1.5), lab(2, "cystatin_c", 1.6)], TODAY),
        ("cystatin newer than creatinine", {**base, "birth_month": "1986-01"},
         [lab(1, "creatinine", 1.5, "2026-09-01"), lab(2, "cystatin_c", 1.2, "2026-09-20")], TODAY),
        ("newest entry of the day", base, [lab(1, "creatinine", 2.0), lab(5, "creatinine", 1.2), lab(3, "creatinine", 4.0)], TODAY),
        ("unspecified sex, formulas disagree", {**base, "birth_month": "1966-04", "sex": "unspecified"}, [lab(1, "creatinine", 1.1)], TODAY),
        ("unspecified sex, formulas agree", {**base, "birth_month": "1966-04", "sex": "unspecified"}, [lab(1, "creatinine", 3.0)], TODAY),
        ("unspecified sex, lab eGFR", {**base, "sex": "unspecified"}, [lab(1, "egfr", 58)], TODAY),
        ("transplant T suffix", {**base, "transplant": True}, [lab(1, "creatinine", 1.2)], TODAY),
        ("matches profile", {**base, "ckd_stage": "3a"}, [lab(1, "creatinine", 1.2)], TODAY),
        ("hemodialysis", {**base, "ckd_stage": "5", "dialysis": "hemodialysis"}, [lab(1, "creatinine", 6.0), lab(2, "uacr", 450)], TODAY),
        ("peritoneal", {**base, "ckd_stage": "5", "dialysis": "peritoneal"}, [lab(1, "creatinine", 6.0)], TODAY),
        ("pregnant", {**base, "pregnant_or_breastfeeding": True}, [lab(1, "egfr", 50)], TODAY),
        ("under 18 by the last day", {**base, "birth_month": "2008-10"}, [lab(1, "egfr", 50)], TODAY),
        ("no birth month, creatinine only", {**base, "birth_month": None}, [lab(1, "creatinine", 1.2)], TODAY),
        ("no birth month, older lab eGFR", {**base, "birth_month": None},
         [lab(1, "egfr", 52, "2026-08-01"), lab(2, "creatinine", 1.2, "2026-10-01")], TODAY),
        ("365 days old counts", base, [lab(1, "creatinine", 1.2, "2025-10-05")], TODAY),
        ("366 days old does not", base, [lab(1, "creatinine", 1.2, "2025-10-04")], TODAY),
        ("UACR in mg/mmol", base, [lab(1, "uacr", 3.0 / 0.113, entered=3.0, unit="mg/mmol")], TODAY),
        ("UACR A3 and G4", {**base, "birth_month": "1950-02", "sex": "male"}, [lab(1, "uacr", 450), lab(2, "creatinine", 2.6)], TODAY),
        ("G1", {**base, "birth_month": "1996-02"}, [lab(1, "creatinine", 0.6)], TODAY),
        ("G5", {**base, "birth_month": "1951-02"}, [lab(1, "creatinine", 4.8)], TODAY),
    ]
    out = []
    for name, profile, labs, today in inputs:
        args = {"ckd_stage": profile["ckd_stage"], "dialysis": profile.get("dialysis", "none"), "transplant": profile.get("transplant", False),
                "birth_month": profile.get("birth_month"), "sex": profile.get("sex", "unspecified"),
                "pregnant_or_breastfeeding": profile.get("pregnant_or_breastfeeding", False)}
        out.append({"name": name, "today": today, "profile": args, "labs": labs,
                    "expect": kf.assess(labs=labs, today=date.fromisoformat(today), **args)})
    return out


def build() -> dict[str, Any]:
    today = date.fromisoformat(TODAY)
    return {
        "about": "Parity vectors for app/static/js/engine/kidney_function.js, generated from app/units.py and "
                 "app/kidney_function.py by tests/data/gen_kidney_function_vectors.py. Do not edit by hand. Unrounded eGFR "
                 "values: compare within 1e-9 relative; everything else exactly. 'Infinity' stands for the JSON-less number.",
        "unit_table": units.unit_table(),
        "unit_systems": list(units.UNIT_SYSTEMS),
        "conversion_cases": conversion_cases(),
        "egfr_cases": egfr_cases(),
        "category_cases": [{"egfr": e, "category": kf.gfr_category(e)}
                           for e in (120, 90, 89.5, 89.49, 60, 59.5, 59.49, 45, 44.6, 44.4, 30, 29.4, 15, 14.5, 14.49, 0.4)],
        "albuminuria_cases": [{"value": v, "unit": u, "category": kf.albuminuria_category(v, u)}
                              for v, u in ((29.9, "mg/g"), (29.96, "mg/g"), (30, "mg/g"), (300.0, "mg/g"), (300.04, "mg/g"),
                                           (300.05, "mg/g"), (0, "mg/g"), (25, "mg/mmol"), (3.0, "mg/mmol"), (2.94, "mg/mmol"),
                                           (2.95, "mg/mmol"), (30.04, "mg/mmol"), (30.05, "mg/mmol"))],
        "age_cases": [{"birth_month": bm, "today": t, "last_day": last, "age": kf.age_on(bm, date.fromisoformat(t), last_day=last)}
                      for bm, t, last in (("1971-03", TODAY, False), ("1976-10", TODAY, False), ("2008-10", TODAY, False),
                                          ("2008-10", TODAY, True), ("2008-09", TODAY, True), ("2000-02", "2026-02-28", True),
                                          ("2008-12", "2026-12-31", True), ("1971-10", "2026-09-30", False))],
        "assess_cases": assess_cases(),
        "today": today.isoformat(),
    }


def dumps(doc: dict[str, Any]) -> str:
    lines = ["{"]
    items = list(doc.items())
    for n, (key, value) in enumerate(items):
        comma = "," if n < len(items) - 1 else ""
        if isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(f"  {json.dumps(key)}: [")
            for m, item in enumerate(value):
                lines.append("    " + json.dumps(item, ensure_ascii=False, separators=(",", ":")) + ("," if m < len(value) - 1 else ""))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = dumps(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if json.loads(current or "null") != json.loads(text):
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_kidney_function_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['conversion_cases'])} conversions, {len(doc['egfr_cases'])} eGFR cases, "
          f"{len(doc['assess_cases'])} cards ({len(text.encode()):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
