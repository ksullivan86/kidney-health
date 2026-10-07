#!/usr/bin/env python3
"""Generate tests/data/targets_vectors.json: parity vectors for the browser twin of the targets rules.

    python3 tests/data/gen_targets_vectors.py           # rewrite the file
    python3 tests/data/gen_targets_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own pure functions (``app/targets.py`` with the data of
``app/target_rules.py``) and replayed on the JavaScript side against ``app/static/js/engine/targets.js``
(the demo/preview API's twin, ARCHITECTURE.md "Frontend modules"); pytest checks the file is current
(``tests/test_targets_vectors.py``). Plain JSON in, plain JSON out, ``today`` always given:

* ``tables``: the rule catalogue, note texts, refusals and every number table, which the JS twin must
  hold verbatim;
* ``reference_weight_cases`` / ``eer_cases``: the two formulas on their own;
* ``cases``: ``suggest_from_records(profile, labs, today, **settings)`` — the exact path of
  ``GET /api/profile/suggested-targets`` — with the whole answer (targets, notes word for word, rules,
  derived, missing inputs, alerts; ``rules`` as catalogue keys, see :func:`catalogue_key`), or
  ``{"error": {"code", "message"}}`` for a refusal (422), or
  ``{"invalid": message}`` for an input the rules cannot use (400). The note 05 §5.1 vectors TV01–TV23
  come first, then every threshold edge, then a fixed-seed random sample;
* ``wrapper_cases``: the v0.2 ``nutrients.suggest_targets(weight, stage, dialysis, diabetes, height)``.

Lab rows look like stored rows: ``{id, analyte, value (canonical), entered_value, entered_unit, taken_on}``.
Standard library only (plus the app package on the path).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "targets_vectors.json"
SPEC = Path(__file__).resolve().parent / "personal_target_vectors.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import nutrients, units  # noqa: E402
from app import target_rules as R  # noqa: E402
from app import targets as T  # noqa: E402

TODAY = "2026-10-05"
SPEC_LAB_UNITS = {"potassium": "mmol/L", "phosphate": "mg/dL", "albumin": "g/dL", "bicarbonate": "mmol/L", "uacr": "mg/g"}


def lab(i: int, analyte: str, value: float, taken_on: str = TODAY, entered: float | None = None, unit: str | None = None) -> dict[str, Any]:
    return {"id": i, "analyte": analyte, "value": value, "entered_value": value if entered is None else entered,
            "entered_unit": unit or units.analyte_def(analyte).canonical_unit, "taken_on": taken_on}


def labs_from(values: dict[str, float], taken_on: str = TODAY) -> list[dict[str, Any]]:
    return [lab(i + 1, a, v, taken_on) for i, (a, v) in enumerate(values.items())]


def run_case(case_id: str, profile: dict[str, Any], labs: list[dict[str, Any]] | None = None, today: str = TODAY,
             settings: dict[str, Any] | None = None) -> dict[str, Any]:
    labs = labs or []
    settings = settings or {}
    out: dict[str, Any] = {"id": case_id, "today": today, "profile": profile, "labs": labs, "settings": settings}
    try:
        result = T.suggest_from_records(profile, labs, date.fromisoformat(today), **settings)
        result["rules"] = [catalogue_key(rule) for rule in result["rules"]]
        out["expect"] = result
    except T.OutOfScope as exc:
        out["expect"] = {"error": {"code": exc.code, "message": exc.message}}
    except ValueError as exc:
        out["expect"] = {"invalid": str(exc)}
    return out


def catalogue_key(rule: dict[str, Any]) -> str:
    """The rule's key in ``tables.rules`` (P-2 is stored as its variant P-2d or P-2n); the full object is
    ``{"id": rule id, **tables.rules[key]}``, which keeps the file small."""
    if rule["id"] != "P-2":
        assert {k: v for k, v in rule.items() if k != "id"} == R.RULES[rule["id"]]
        return rule["id"]
    for key in ("P-2d", "P-2n"):
        if {k: v for k, v in rule.items() if k != "id"} == R.RULES[key]:
            return key
    raise AssertionError(f"rule {rule} is not in the catalogue")


def spec_cases() -> list[dict[str, Any]]:
    doc = json.loads(SPEC.read_text(encoding="utf-8"))
    cases = []
    for vector in doc["vectors"]:
        profile = dict(vector["input"])
        values = {a: profile.pop(a) for a in list(profile) if a in SPEC_LAB_UNITS}
        cases.append(run_case(vector["id"], profile, labs_from(values), doc["today"]))
    return cases


G3B = {"weight_kg": 70, "ckd_stage": "3b"}
ADULT = {"height_cm": 170, "birth_month": "1970-06", "sex": "female"}
PD = {"weight_kg": 60, "ckd_stage": "5", "dialysis": "peritoneal", "height_cm": 158, "birth_month": "1976-05", "sex": "female"}


def edge_cases() -> list[dict[str, Any]]:
    c: list[tuple[str, dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]] = []

    def add(case_id: str, profile: dict[str, Any], labs: list[dict[str, Any]] | None = None, today: str = TODAY, **settings: Any) -> None:
        c.append((case_id, profile, labs or [], today, settings))

    # potassium: every threshold on the shown value, ladders, caps, history, dialysis, transplant
    for k in (3.44, 3.45, 5.0, 5.04, 5.05, 5.5, 5.54, 5.55, 5.94, 5.95, 6.44, 6.45):
        add(f"K {k} G3b", G3B, labs_from({"potassium": k}))
    add("K normal G4 history", {**G3B, "ckd_stage": "4", "hyperkalemia_history": True}, labs_from({"potassium": 4.5}))
    add("K high G5 cap below ladder", {**G3B, "ckd_stage": "5"}, labs_from({"potassium": 5.3}))
    add("K normal HD", {**G3B, "ckd_stage": "5", "dialysis": "hemodialysis"}, labs_from({"potassium": 4.5}))
    add("K normal PD", {**G3B, "ckd_stage": "5", "dialysis": "peritoneal"}, labs_from({"potassium": 4.5}))
    add("K normal transplant G2", {**G3B, "ckd_stage": "2", "transplant_date": "2019-01-01"}, labs_from({"potassium": 4.5}))
    add("K newest of several", G3B, [lab(1, "potassium", 6.2, "2026-09-01"), lab(4, "potassium", 4.1, "2026-10-01"),
                                     lab(2, "potassium", 5.8, "2026-10-01")])
    # phosphate
    for p in (2.44, 2.45, 4.5, 4.54, 4.55):
        add(f"PH {p} G5", {**G3B, "ckd_stage": "5"}, labs_from({"phosphate": p}))
    add("PH transplant G3b no lab", {**G3B, "transplant_date": "2019-01-01"})
    add("PH transplant G2 normal", {**G3B, "ckd_stage": "2", "transplant_date": "2019-01-01"}, labs_from({"phosphate": 3.5}))
    add("PH transplant G5 no lab", {**G3B, "ckd_stage": "5", "transplant_date": "2019-01-01"})
    # weight basis
    add("BMI exactly 25", {"weight_kg": 72.25, "ckd_stage": "3b", "height_cm": 170})
    add("BMI exactly 18.5", {"weight_kg": 53.465, "ckd_stage": "3b", "height_cm": 170})
    add("BMI 25.01", {"weight_kg": 72.28, "ckd_stage": "3b", "height_cm": 170})
    add("BMI 34.6 (100 kg at 170 cm)", {"weight_kg": 100, "ckd_stage": "4", "height_cm": 170})
    add("BMI 15.6 (45 kg at 170 cm)", {"weight_kg": 45, "ckd_stage": "3b", "height_cm": 170})
    add("dry weight on HD", {"weight_kg": 70, "ckd_stage": "5", "dialysis": "hemodialysis", "height_cm": 175})
    # energy
    add("E clamp 35 unspecified active", {"weight_kg": 70, "ckd_stage": "3a", "height_cm": 168, "birth_month": "1976-10", "activity": "active"})
    add("E clamp 25", {"weight_kg": 110, "ckd_stage": "3b", "height_cm": 160, "birth_month": "1940-01", "sex": "female"})
    add("E very active male", {**G3B, "height_cm": 185, "birth_month": "1990-02", "sex": "male", "activity": "very_active"})
    add("E default activity setting", {**G3B, **ADULT}, default_activity="low_active")
    add("E-3 floor", {**G3B, "height_cm": 170, "birth_month": "1961-05", "sex": "female", "frail_or_sarcopenic": True})
    add("E-4 normal", {**PD, "pd_dialysate_kcal": 350, "urine_output_ml": 800, "pd_uf_ml": 900})
    add("E-4 floor", {**PD, "pd_dialysate_kcal": 1000})
    add("E-4 no diabetes", {**PD, "diabetes": "none", "pd_dialysate_kcal": 350.6})
    add("E-4 zero dialysate", {**PD, "pd_dialysate_kcal": 0})
    add("PD dialysate missing", PD)
    # protein
    for name, extra in (("P-1", {"ckd_stage": "2", "diabetes": "none"}), ("P-2d type2", {"ckd_stage": "3a", "diabetes": "type2"}),
                        ("P-2n", {"ckd_stage": "5", "diabetes": "none"}), ("P-6", {"ckd_stage": "5", "dialysis": "hemodialysis", "frail_or_sarcopenic": True}),
                        ("P-3 older only", {"ckd_stage": "5", "dialysis": "peritoneal", "birth_month": "1950-01"}),
                        ("P-5 G3b older", {"birth_month": "1950-01"}), ("P-5 G1 older", {"ckd_stage": "1", "birth_month": "1950-01"}),
                        ("P-7 G2", {"ckd_stage": "2", "transplant_date": "2020-01-01"}),
                        ("P-7 + P-5 G2 risk", {"ckd_stage": "2", "transplant_date": "2020-01-01", "frail_or_sarcopenic": True}),
                        ("P-7 G3a older not raised", {"ckd_stage": "3a", "transplant_date": "2020-01-01", "birth_month": "1950-01"})):
        add(name, {**G3B, **extra})
    # nutrition risk
    add("risk low BMI under 70", {"weight_kg": 57.6, "ckd_stage": "3b", "height_cm": 170, "birth_month": "1957-01"})
    add("risk BMI shown 20.0", {"weight_kg": 57.7, "ckd_stage": "3b", "height_cm": 170, "birth_month": "1957-01"})
    add("risk low BMI from 70", {"weight_kg": 60, "ckd_stage": "3b", "height_cm": 170, "birth_month": "1956-01"})
    add("risk weight loss 5.0", {"weight_kg": 95, "ckd_stage": "3b", "weight_6_months_ago_kg": 100})
    add("risk weight loss 5.1", {"weight_kg": 94.9, "ckd_stage": "3b", "weight_6_months_ago_kg": 100})
    add("risk all four", {"weight_kg": 50, "ckd_stage": "3b", "height_cm": 170, "weight_6_months_ago_kg": 60, "frail_or_sarcopenic": True},
        labs_from({"albumin": 3.3}))
    add("albumin shown 3.8", G3B, labs_from({"albumin": 3.75}))
    # calcium
    for bm, sex in (("2008-01", "male"), ("1990-01", "female"), ("1970-01", "female"), ("1970-01", "male"), ("1970-01", "unspecified"),
                    ("1950-01", "male")):
        add(f"CA-3 {bm} {sex}", {**G3B, "ckd_stage": "1", "birth_month": bm, "sex": sex})
    add("CA-0", {**G3B, "ckd_stage": "2"})
    add("CA-2 transplant G5", {**G3B, "ckd_stage": "5", "transplant_date": "2019-01-01"})
    # fluid
    for urine in (0, 324, 325, 1200):
        add(f"HD urine {urine}", {**G3B, "ckd_stage": "5", "dialysis": "hemodialysis", "urine_output_ml": urine})
    add("PD urine only", {**PD, "urine_output_ml": 800})
    add("PD urine and UF", {**PD, "urine_output_ml": 800, "pd_uf_ml": 913})
    add("F-0o male", {**G3B, "birth_month": "1950-01", "sex": "male"})
    add("F-0o unspecified", {**G3B, "birth_month": "1950-01"})
    add("F-0 at G4 older", {**G3B, "ckd_stage": "4", "birth_month": "1950-01"})
    # carbohydrate
    add("carbs per meal minimum", {"weight_kg": 15, "ckd_stage": "3b"})
    add("no diabetes carb note", {**G3B, "diabetes": "none"})
    # lab notes
    add("BIC 22.0 none", G3B, labs_from({"bicarbonate": 22.0}))
    add("BIC 21.95 shown 22.0", G3B, labs_from({"bicarbonate": 21.95}))
    add("BIC 21 G3a", {**G3B, "ckd_stage": "3a"}, labs_from({"bicarbonate": 21.0}))
    add("BIC 21 G3a high K", {**G3B, "ckd_stage": "3a"}, labs_from({"bicarbonate": 21.0, "potassium": 5.2}))
    add("BIC 17 HD both notes", {**G3B, "ckd_stage": "5", "dialysis": "hemodialysis"}, labs_from({"bicarbonate": 17.0}))
    add("UACR 3.0 mg/mmol A2", G3B, [lab(1, "uacr", 3.0 / 0.113, TODAY, 3.0, "mg/mmol")])
    add("UACR 2.94 mg/mmol A1", G3B, [lab(1, "uacr", 2.94 / 0.113, TODAY, 2.94, "mg/mmol")])
    add("UACR 35 mg/mmol A3 low albumin", G3B, [lab(1, "uacr", 35 / 0.113, TODAY, 35.0, "mg/mmol"), lab(2, "albumin", 3.2)])
    add("UACR 12 mg/g A1", G3B, labs_from({"uacr": 12}))
    add("A1c fresh", G3B, labs_from({"a1c": 7.4}))
    add("A1c stale", G3B, labs_from({"a1c": 7.4}, "2025-09-01"))
    # settings
    every_lab = {"potassium": 6.6, "phosphate": 6.0, "albumin": 3.0, "bicarbonate": 16.0, "uacr": 500.0, "a1c": 8.0}
    add("lab rules off", {**G3B, "ckd_stage": "4"}, labs_from(every_lab), lab_rules_enabled=False)
    add("lab rules on (same labs)", {**G3B, "ckd_stage": "4"}, labs_from(every_lab))
    add("K 90 days old", G3B, labs_from({"potassium": 4.5}, "2026-07-07"))
    add("K 91 days old", G3B, labs_from({"potassium": 4.5}, "2026-07-06"))
    add("K tomorrow", G3B, labs_from({"potassium": 4.5}, "2026-10-06"))
    add("K window 30 days", G3B, labs_from({"potassium": 4.5}, "2026-09-01"), fresh_days={"potassium": 30})
    add("albumin window 30 days", G3B, labs_from({"albumin": 3.0}, "2026-08-01"), fresh_days={"albumin": 30})
    add("labs from other analytes ignored", G3B, labs_from({"creatinine": 1.4, "egfr": 41, "cystatin_c": 1.5}))
    # refusals and their order
    add("refuse pregnancy first", {**G3B, "pregnant_or_breastfeeding": True, "birth_month": "2010-01", "transplant_date": "2026-10-01"})
    add("refuse under 18 last day", {**G3B, "birth_month": "2008-10"}, today="2026-10-30")
    add("allowed 18 at month end", {**G3B, "birth_month": "2008-10"}, today="2026-10-31")
    add("refuse transplant 83 days", {**G3B, "transplant_date": "2026-07-14"})
    add("allowed transplant 84 days", {**G3B, "transplant_date": "2026-07-13"})
    add("refuse transplant date ahead", {**G3B, "transplant_date": "2026-12-01"})
    add("HD after a transplant", {**G3B, "ckd_stage": "5", "dialysis": "hemodialysis", "transplant_date": "2026-10-01"})
    # invalid inputs (400)
    for name, extra in (("invalid weight", {"weight_kg": 0}), ("invalid stage", {"ckd_stage": "6"}), ("invalid sex", {"sex": "x"}),
                        ("invalid activity", {"activity": "athlete"}), ("invalid birth month", {"birth_month": "1970-13"}),
                        ("future birth month", {"birth_month": "2026-11"}), ("birth month over 120", {"birth_month": "1900-01"}),
                        ("invalid transplant date", {"transplant_date": "01/02/2020"}),
                        ("impossible transplant date", {"transplant_date": "2026-02-30"})):
        add(name, {**G3B, **extra})
    # missing inputs and age on a birthday boundary
    add("missing inputs PD", {**G3B, "ckd_stage": "5", "dialysis": "peritoneal"})
    add("nothing missing", {**G3B, "height_cm": 175, "birth_month": "1971-03", "sex": "male", "activity": "active"})
    add("age the day before", {**G3B, "height_cm": 175, "birth_month": "1971-10", "sex": "male"}, today="2026-09-30")
    add("age on the first", {**G3B, "height_cm": 175, "birth_month": "1971-10", "sex": "male"}, today="2026-10-01")
    return [run_case(case_id, profile, labs, today, settings) for case_id, profile, labs, today, settings in c]


def random_cases(n: int = 120, seed: int = 20261005) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        dialysis = rng.choice(("none", "none", "hemodialysis", "peritoneal"))
        profile: dict[str, Any] = {
            "weight_kg": round(rng.uniform(35, 160), 1),
            "ckd_stage": rng.choice(("1", "2", "3a", "3b", "4", "5")) if dialysis == "none" else "5",
            "dialysis": dialysis,
            "diabetes": rng.choice(("none", "type1", "type2")),
        }
        if rng.random() < 0.7:
            profile["height_cm"] = round(rng.uniform(145, 200), 1)
        if rng.random() < 0.7:
            profile["birth_month"] = f"{rng.randint(1925, 2007)}-{rng.randint(1, 12):02d}"
        if rng.random() < 0.7:
            profile["sex"] = rng.choice(R.SEXES)
        if rng.random() < 0.5:
            profile["activity"] = rng.choice(R.ACTIVITIES)
        for flag in ("frail_or_sarcopenic", "hyperkalemia_history"):
            if rng.random() < 0.2:
                profile[flag] = True
        if dialysis == "none" and rng.random() < 0.2:
            profile["transplant_date"] = f"{rng.randint(2005, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        if dialysis != "none" and rng.random() < 0.6:
            profile["urine_output_ml"] = rng.randint(0, 2500)
        if dialysis == "peritoneal" and rng.random() < 0.6:
            profile["pd_uf_ml"] = rng.randint(0, 2000)
            if rng.random() < 0.7:
                profile["pd_dialysate_kcal"] = rng.randint(0, 1000)
        if rng.random() < 0.25:
            profile["weight_6_months_ago_kg"] = round(profile["weight_kg"] * rng.uniform(0.9, 1.15), 1)
        labs = []
        for analyte, lo, hi in (("potassium", 2.8, 7.0), ("phosphate", 1.5, 8.0), ("albumin", 2.5, 4.8), ("bicarbonate", 14, 30),
                                ("uacr", 0, 2000), ("a1c", 5, 11)):
            if rng.random() < 0.45:
                taken = date.fromordinal(date.fromisoformat(TODAY).toordinal() - rng.randint(0, 400)).isoformat()
                labs.append(lab(len(labs) + 1, analyte, round(rng.uniform(lo, hi), 2), taken))
        settings: dict[str, Any] = {}
        if rng.random() < 0.15:
            settings["lab_rules_enabled"] = False
        if rng.random() < 0.15:
            settings["default_activity"] = rng.choice(R.ACTIVITIES)
        out.append(run_case(f"random {i:03d}", profile, labs, TODAY, settings))
    return out


def wrapper_cases() -> list[dict[str, Any]]:
    out = []
    combos = [(stage, "none") for stage in ("1", "2", "3a", "3b", "4", "5")] + [("5", "hemodialysis"), ("5", "peritoneal")]
    for weight in (70, 45):
        for stage, dialysis in combos:
            for diabetes in ("type1", "none"):
                for height in (None, 170):
                    args = [weight, stage, dialysis, diabetes, height]
                    out.append({"args": args, "expect": nutrients.suggest_targets(*args)})
    return out


def tables() -> dict[str, Any]:
    return {
        "rules": R.RULES,
        "rule_order": list(R.RULE_ORDER),
        "notes": R.NOTES,
        "potassium_note": R.POTASSIUM_NOTE,
        "refusals": {code: {"rule": rule, "message": message} for code, (rule, message) in R.REFUSALS.items()},
        "eer_coefficients": {sex: {a: list(c) for a, c in table.items()} for sex, table in R.EER_COEFFICIENTS.items()},
        "activities": list(R.ACTIVITIES),
        "activity_labels": R.ACTIVITY_LABELS,
        "protein_g_per_kg": {k: list(v) for k, v in R.PROTEIN_G_PER_KG.items()},
        "potassium_ladder": R.POTASSIUM_LADDER,
        "potassium_relaxed": R.POTASSIUM_RELAXED,
        "potassium_caps": R.POTASSIUM_CAPS,
        "phosphorus_default": R.PHOSPHORUS_DEFAULT,
        "calcium_dri": list(R.CALCIUM_DRI),
        "fluid_floor_text": R.FLUID_FLOOR_TEXT,
        "target_labs": list(T.TARGET_LABS),
        "default_fresh_days": T.DEFAULT_FRESH_DAYS,
        "missing_input_order": list(R.MISSING_INPUT_ORDER),
    }


def build() -> dict[str, Any]:
    ref_cases = []
    for weight, height in ((70, None), (70, 170), (100, 170), (45, 170), (72.25, 170), (53.465, 170), (95, 165), (52, 170), (82, 181),
                           (150.3, 158.4), (38.2, 181.0)):
        rw = T.reference_weight(weight, height)
        ref_cases.append({"weight_kg": weight, "height_cm": height, "expect": {"weight_kg": rw.weight_kg, "basis": rw.basis}})
    eer = []
    for sex in R.SEXES:
        for activity in R.ACTIVITIES:
            for age, height, weight in ((18, 150, 45.5), (55, 175, 70), (72, 160, 62), (90, 190, 101.3)):
                eer.append({"sex": sex, "activity": activity, "age": age, "height_cm": height, "weight_kg": weight,
                            "kcal": T.eer_kcal(sex, activity, age, height, weight)})
    return {
        "about": "Parity vectors for app/static/js/engine/targets.js, generated from app/targets.py and app/target_rules.py by "
                 "tests/data/gen_targets_vectors.py. Do not edit by hand: change the rules, then regenerate. Notes must match "
                 "byte for byte; eer kcal is unrounded (compare within 1e-9 relative). A case's rules are catalogue keys: "
                 "the API returns {id, ...tables.rules[key]} with id 'P-2' for the keys 'P-2d' and 'P-2n'.",
        "tables": tables(),
        "reference_weight_cases": ref_cases,
        "eer_cases": eer,
        "cases": spec_cases() + edge_cases() + random_cases(),
        "wrapper_cases": wrapper_cases(),
    }


def dumps(doc: dict[str, Any]) -> str:
    """One case per line, so a rule change shows up as a readable diff."""
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
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_targets_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['cases'])} cases, {len(doc['wrapper_cases'])} wrapper cases, "
          f"{len(doc['eer_cases'])} EER cases ({len(text.encode()):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
