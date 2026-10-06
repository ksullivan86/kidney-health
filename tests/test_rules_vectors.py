"""Parity vectors for the browser rules engine (ARCHITECTURE.md, "Frontend modules").

tests/data/rules_vectors.json is generated from app/nutrients.py by tests/data/gen_rules_vectors.py
and replayed against app/static/js/engine/rules.js by ``node tests/js/run_vectors.mjs``. These
tests fail when the committed file no longer matches the Python rules (regenerate it), and run
the Node side too when ``node`` is installed (CI runs it as its own step as well).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.nutrients import NUTRIENT_KEYS, food_warnings, kidney_rating

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "data" / "rules_vectors.json"


def _generator():
    spec = importlib.util.spec_from_file_location("gen_rules_vectors", ROOT / "tests" / "data" / "gen_rules_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rules_vectors_are_current() -> None:
    committed = json.loads(VECTORS.read_text(encoding="utf-8"))
    fresh = _generator().build()
    assert committed == fresh, (
        "tests/data/rules_vectors.json is stale: app/nutrients.py or data/foods.json changed. "
        "Run `python3 tests/data/gen_rules_vectors.py`, then `node tests/js/run_vectors.mjs`, and update "
        "app/static/js/engine/rules.js until both agree."
    )


def test_rules_vectors_cover_every_food_at_three_amounts() -> None:
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    foods = json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))["foods"]
    assert len(doc["foods"]) == len(foods) == 395
    assert doc["servings"] == [0.5, 1, 2.5]
    assert doc["nutrient_keys"] == list(NUTRIENT_KEYS)
    assert {(c["food"], c["servings"]) for c in doc["food_cases"]} == {(i, s) for i in range(len(foods)) for s in (0.5, 1, 2.5)}
    assert {c["scope"] for c in doc["food_cases"]} == {"per serving", "in this entry", "in this meal"}
    # Every rule that changes a warning is exercised: each level, each flag-driven warning.
    levels = {(w["nutrient"], w["level"], w["flag"]) for c in doc["food_cases"] + doc["boundary_cases"] for w in c["warnings"]}
    for expected in [("avoid_ckd", "high", "avoid_ckd"), ("phosphorus_mg", "high", "phosphate_additive"), ("carbs_g", "high", "high_gi"),
                     ("carbs_g", "medium", "high_gi"), ("potassium_mg", "medium", None), ("potassium_mg", "high", None),
                     ("sodium_mg", "medium", None), ("sodium_mg", "high", None), ("protein_g", "medium", None), ("protein_g", "high", None),
                     ("carbs_g", "medium", None), ("carbs_g", "high", None), ("phosphorus_mg", "medium", None),
                     ("potassium_mg", "medium", "potassium_additive")]:
        assert expected in levels, expected
    assert {c["kidney_rating"] for c in doc["food_cases"]} == {"green", "yellow", "red"}


def test_hypo_treatment_vectors_never_warn_about_carbohydrate() -> None:
    """The safety rule the vectors pin down on both sides: hypo treatments get no carb warning."""
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    hypo = [c for c in doc["boundary_cases"] if "hypo_treatment" in c["flags"]]
    hypo += [c for c in doc["food_cases"] if "hypo_treatment" in doc["foods"][c["food"]]["flags"]]
    assert hypo
    for c in hypo:
        assert not [w for w in c["warnings"] if w["nutrient"] == "carbs_g"], c
    # and the generator really calls the server's function
    w = food_warnings({"carbs_g": 40}, ["hypo_treatment", "high_gi"])
    assert w == [] and kidney_rating(w) == "green"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_engine_matches_vectors() -> None:
    proc = subprocess.run(["node", str(ROOT / "tests" / "js" / "run_vectors.mjs")], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checks passed" in proc.stdout
