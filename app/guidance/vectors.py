"""Food vectors: one food as the engine sees it (note 06 §4.1 ``vectors.py``, §4.3). Pure, no I/O.

A :class:`FoodVec` holds one serving's numbers as plain floats (``None`` = unknown, never 0, note 03)
plus everything derived once per food: role and group (§4.3), name family, renal level at one
serving and the flags the hot path tests. :mod:`app.guidance.context` builds them from SQLite through
:func:`build_vectors` and caches them per ``(meta.foods_rev, user_id)``; tests and the parity vector
generator build them with :func:`make_food`.

:func:`renal_level` is the guidance version of the app's kidney rating (potassium, phosphorus,
sodium and phosphate additives only), written with float comparisons instead of ``Decimal`` for
speed; ``tests/guidance/test_vectors.py`` proves it equals ``app.nutrients`` on every builtin food at
every portion from ¼ to 3 servings.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..nutrients import NUTRIENT_KEYS
from . import rules as R

_K_HIGH, _P_HIGH, _NA_HIGH = R.RENAL_HIGH_CUT[R.K], R.RENAL_HIGH_CUT[R.P], R.RENAL_HIGH_CUT[R.NA]
_K_MED, _P_MED, _NA_MED = R.RENAL_MEDIUM_CUT[R.K], R.RENAL_MEDIUM_CUT[R.P], R.RENAL_MEDIUM_CUT[R.NA]
_P_GOOD, _P_POOR = R.P_PER_G_PROTEIN
_K_GOOD, _K_POOR = R.K_PER_G_PROTEIN


def renal_level(k: float | None, p: float | None, na: float | None, additive: bool) -> str:
    """``green`` / ``yellow`` / ``red`` from potassium, phosphorus and sodium of one portion (§4.3).

    The guidance version of :func:`app.nutrients.kidney_rating`: amounts are judged rounded to whole
    milligrams (like the warnings, on the displayed value); any above "high" or a phosphate additive
    → red; any at "medium" → yellow. Carbohydrate and protein warnings are left out on purpose (F10:
    carbohydrate is handled by the meal goal). ``avoid_ckd`` foods never get here (not eligible).
    Equals the rating of ``food_warnings()`` restricted to potassium, phosphorus, sodium and the
    additive flag (property test over every builtin food × portions ¼…3).
    """
    if additive:
        return "red"
    if (k is not None and k >= _K_HIGH) or (p is not None and p >= _P_HIGH) or (na is not None and na >= _NA_HIGH):
        return "red"
    if (k is not None and k >= _K_MED) or (p is not None and p >= _P_MED) or (na is not None and na >= _NA_MED):
        return "yellow"
    return "green"


def is_high(key: str, value: float | None) -> bool:
    """The portion is above the per-serving "high" threshold for ``key`` (rounded like the warnings)."""
    return value is not None and value >= R.RENAL_HIGH_CUT[key]




@dataclass(frozen=True, slots=True)
class FoodVec:
    """One food as the engine sees it: per-serving numbers as floats (``None`` = unknown)."""

    id: int
    name: str
    category: str | None
    source: str
    fdc_id: int | None
    serving_desc: str
    serving_g: float
    flags: frozenset[str]
    kidney_notes: str | None
    hidden: bool
    nutrients: Mapping[str, float | None]  # all 12 keys, per serving, unrounded
    role: str
    group: str
    family: str
    name_fold: str
    carbs: float | None
    protein: float | None
    k: float | None
    p: float | None
    na: float | None
    fluid: float | None
    kcal: float | None
    additive: bool
    processed: bool
    high_gi: bool
    hypo: bool
    avoid: bool
    ingredient: bool
    supplies: bool
    beverage: bool
    level1: str  # renal level at one serving (pre-ranking)


def make_food(
    *,
    id: int,
    name: str,
    category: str | None,
    serving_desc: str,
    serving_g: float,
    nutrients: Mapping[str, Any],
    flags: Any = (),
    source: str = "builtin",
    fdc_id: int | None = None,
    kidney_notes: str | None = None,
    hidden: bool = False,
    role_override: str | None = None,
) -> FoodVec:
    """Build a :class:`FoodVec` from row-like values (the single place roles and flags are derived)."""
    values: dict[str, float | None] = {}
    for key in NUTRIENT_KEYS:
        v = nutrients.get(key)
        values[key] = None if v is None else float(v)
    flag_set = frozenset(str(f) for f in (flags or ()))
    carbs, protein = values["carbs_g"], values["protein_g"]
    role = R.role_of(category, carbs, protein, role_override)
    additive = "phosphate_additive" in flag_set
    return FoodVec(
        id=int(id),
        name=str(name),
        category=category,
        source=source,
        fdc_id=fdc_id,
        serving_desc=str(serving_desc),
        serving_g=float(serving_g),
        flags=flag_set,
        kidney_notes=kidney_notes,
        hidden=bool(hidden),
        nutrients=values,
        role=role,
        group=R.group_of(role),
        family=R.family_of(name),
        name_fold=str(name).casefold(),
        carbs=carbs,
        protein=protein,
        k=values["potassium_mg"],
        p=values["phosphorus_mg"],
        na=values["sodium_mg"],
        fluid=values["fluid_ml"],
        kcal=values["calories_kcal"],
        additive=additive,
        processed="processed" in flag_set,
        high_gi="high_gi" in flag_set,
        hypo="hypo_treatment" in flag_set,
        avoid="avoid_ckd" in flag_set,
        ingredient=R.INGREDIENT_FLAG in flag_set,
        supplies=category == R.SUPPLIES_CATEGORY,
        beverage=category == R.BEVERAGES,
        level1=renal_level(values["potassium_mg"], values["phosphorus_mg"], values["sodium_mg"], additive),
    )


def protein_quality(protein_g: float | None, potassium_mg: float | None, phosphorus_mg: float | None) -> dict[str, Any]:
    """Phosphorus and potassium per gram of protein of one portion (note 06 F2) and their grades.

    ``{"p_per_g", "k_per_g", "p_grade", "k_grade"}`` with grades ``good`` (P ≤ 10, K ≤ 10 mg/g),
    ``poor`` (P ≥ 16, K ≥ 20 mg/g) or ``fair``; ``None`` when protein is under ``PROTEIN_ROLE_MIN_G``
    (not a protein portion) or the mineral is unknown.
    """
    out: dict[str, Any] = {"p_per_g": None, "k_per_g": None, "p_grade": None, "k_grade": None}
    if protein_g is None or protein_g < R.PROTEIN_ROLE_MIN_G:
        return out
    if phosphorus_mg is not None:
        ratio = phosphorus_mg / protein_g
        out["p_per_g"] = ratio
        out["p_grade"] = "good" if ratio <= _P_GOOD else "poor" if ratio >= _P_POOR else "fair"
    if potassium_mg is not None:
        ratio = potassium_mg / protein_g
        out["k_per_g"] = ratio
        out["k_grade"] = "good" if ratio <= _K_GOOD else "poor" if ratio >= _K_POOR else "fair"
    return out


def food_from_row(row: sqlite3.Row | Mapping[str, Any], flags: Iterable[str], role_override: str | None = None) -> FoodVec:
    """A :class:`FoodVec` from a ``foods`` row (``app.foods`` column names) and its parsed flags."""
    return make_food(
        id=row["id"], name=row["name"], category=row["category"], serving_desc=row["serving_desc"],
        serving_g=row["serving_g"], nutrients={k: row[k] for k in NUTRIENT_KEYS}, flags=flags,
        source=row["source"], fdc_id=row["fdc_id"], kidney_notes=row["kidney_notes"], hidden=bool(row["hidden"]),
        role_override=role_override,
    )


def build_vectors(rows: Iterable[tuple[sqlite3.Row | Mapping[str, Any], Iterable[str]]],
                  role_overrides: Mapping[int, str] | None = None) -> dict[int, FoodVec]:
    """``{food id: FoodVec}`` from ``(row, flags)`` pairs; ``role_overrides`` maps a builtin food's
    ``fdc_id`` to its curated ``role`` in ``data/foods.json`` (coleslaw is a vegetable side)."""
    overrides = role_overrides or {}
    out: dict[int, FoodVec] = {}
    for row, flags in rows:
        override = overrides.get(row["fdc_id"]) if row["source"] == "builtin" and row["fdc_id"] is not None else None
        vec = food_from_row(row, flags, override)
        out[vec.id] = vec
    return out
