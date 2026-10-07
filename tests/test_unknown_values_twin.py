"""The demo's log twin counts values that are not listed exactly as the server does (v0.3.0 review, C1).

A total adds only the values a food lists, so a scanned product without potassium or phosphorus must never make a
total look complete. ``app/log.py`` and ``app/periods.py`` report how many entries each total misses
(ARCHITECTURE.md "Foods and log changes"); the demo and preview answer the same routes from
``app/static/js/mock/log.js`` over ``js/engine/rules.js`` (``countUnknown`` / ``mergeUnknown`` / ``markUnknown``).
This test feeds the same rows to both and compares the whole answers: the day figures (totals, status with
``unknown``, alerts, the per-meal counts), the period summary (``unknown_entries`` / ``unknown_days``, the
interdialytic block) and the range. ``tools/e2e/parity.py`` section 5 compares the routes on a real server.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from app.log import day_figures, eaten_day_totals, eaten_day_unknown
from app.models import NutrientStatus
from app.nutrients import NUTRIENT_KEYS
from app.periods import interdialytic_block, interdialytic_interval, previous_period, summarize_period, summary_notes, to_date

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "demo_log_twin.mjs"

FULL = {"calories_kcal": 300, "protein_g": 20, "fat_g": 10, "sat_fat_g": 3, "carbs_g": 30, "fiber_g": 4, "sugar_g": 5,
        "sodium_mg": 400, "potassium_mg": 500, "phosphorus_mg": 250, "calcium_mg": 80, "fluid_ml": 0}
# A scanned spread: no potassium, phosphorus, fibre or calcium listed (the review's Nutella case).
SPREAD = {**FULL, "calories_kcal": 80, "protein_g": 0.9, "carbs_g": 8.6, "sodium_mg": 6,
          "potassium_mg": None, "phosphorus_mg": None, "fiber_g": None, "calcium_mg": None}
# A quick add with only carbohydrate and sodium.
QUICK = {key: None for key in NUTRIENT_KEYS} | {"carbs_g": 15, "sodium_mg": 120, "fluid_ml": 0}

PROFILE = {"targets": {"potassium_mg": 3500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 50, "max": 60},
                       "fiber_g": {"min": 25}, "carbs_per_meal_g": 60, "fluid_ml": 1500},
           "warn_fraction": 0.8, "dialysis": "hemodialysis", "dialysis_days": [0, 2, 4]}

# (date, meal, status, nutrients): a week with unknown values eaten, planned and on days of the previous period.
ENTRIES = [
    ("2026-09-24", "lunch", "eaten", SPREAD),
    ("2026-09-28", "breakfast", "eaten", FULL),
    ("2026-09-29", "breakfast", "eaten", FULL),
    ("2026-09-29", "snack", "eaten", SPREAD),
    ("2026-09-29", "snack", "eaten", SPREAD),
    ("2026-09-30", "lunch", "eaten", QUICK),
    ("2026-10-02", "dinner", "eaten", FULL),
    ("2026-10-03", "dinner", "planned", SPREAD),
    ("2026-10-04", "snack", "eaten", SPREAD),
    ("2026-10-04", "lunch", "planned", QUICK),
]
START, END = "2026-09-28", "2026-10-04"


def _rows(day: str | None = None) -> list[dict[str, Any]]:
    return [{"status": status, "meal": meal, **values} for d, meal, status, values in ENTRIES if day is None or d == day]


def _as_served(figures: dict[str, Any]) -> dict[str, Any]:
    """The day figures as the API serves them (each status item through its response model: ``min`` is null when unset)."""
    out = json.loads(json.dumps(figures))
    for key in ("status", "projected_status"):
        out[key] = {k: NutrientStatus(**v).model_dump(mode="json") for k, v in out[key].items()}
    return out


def _js(payload: dict[str, Any]) -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo's twin (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _python_summary() -> dict[str, Any]:
    """app.log.get_summary's computation, over a table with exactly these entries (person 1)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(f"CREATE TABLE log_entries (user_id INTEGER, date TEXT, status TEXT, {', '.join(f'{k} REAL' for k in NUTRIENT_KEYS)})")
    for d, _meal, status, values in ENTRIES:
        conn.execute(f"INSERT INTO log_entries VALUES (1, ?, ?, {', '.join('?' for _ in NUTRIENT_KEYS)})",
                     (d, status, *[values[k] for k in NUTRIENT_KEYS]))
    start_d, end_d = date.fromisoformat(START), date.fromisoformat(END)
    interval = interdialytic_interval(end_d, PROFILE["dialysis_days"])
    fetch_from, _ = previous_period(start_d, end_d)
    fetch_from = min(fetch_from, to_date(interval["since"]))
    totals = eaten_day_totals(conn, 1, fetch_from.isoformat(), END)
    unknown = eaten_day_unknown(conn, 1, fetch_from.isoformat(), END)
    summary = summarize_period(start_d, end_d, totals, PROFILE["targets"], PROFILE["warn_fraction"], day_unknown=unknown)
    summary["interdialytic"] = interdialytic_block(interval, totals, PROFILE["targets"], PROFILE["warn_fraction"], day_unknown=unknown)
    summary["notes"] = summary_notes(PROFILE["dialysis"], PROFILE["dialysis_days"], interval)
    return summary


def test_day_figures_match_the_server() -> None:
    for day in sorted({d for d, *_ in ENTRIES}):
        py = day_figures(_rows(day), PROFILE)
        js = _js({"profile": PROFILE, "rows": [{"status": r["status"], "meal": r["meal"], "nutrients": {k: r[k] for k in NUTRIENT_KEYS}}
                                               for r in _rows(day)]})["day"]
        assert _as_served(py) == js, day


def test_the_spread_day_says_what_it_misses() -> None:
    """The review's repro: two spreads without potassium or phosphorus as a snack. The totals skip them, and every
    figure says so (2 entries), so the UI can show "+ 2 not listed" instead of a complete-looking number."""
    js = _js({"profile": PROFILE, "rows": [{"status": r["status"], "meal": r["meal"], "nutrients": {k: r[k] for k in NUTRIENT_KEYS}}
                                           for r in _rows("2026-09-29")]})["day"]
    assert js["unknown"]["potassium_mg"] == 2 and js["unknown"]["phosphorus_mg"] == 2
    assert js["meal_unknown"]["snack"] == {"potassium_mg": 2, "phosphorus_mg": 2, "fiber_g": 2, "calcium_mg": 2}
    assert js["meal_unknown"]["breakfast"] == {}
    assert js["status"]["potassium_mg"]["unknown"] == 2 and js["status"]["sodium_mg"]["unknown"] == 0
    assert js["totals"]["potassium_mg"] == 500  # only breakfast's: the spreads add nothing, and say so


def test_period_summary_and_range_match_the_server() -> None:
    js = _js({"profile": PROFILE, "entries": [
        {"id": i + 1, "date": d, "meal": meal, "status": status, "nutrients": values, "created_at": f"2026-10-01T00:00:{i:02d}Z"}
        for i, (d, meal, status, values) in enumerate(ENTRIES)], "summary": [START, END]})
    py = json.loads(json.dumps(_python_summary()))
    assert js["summary"] == py
    k = js["summary"]["nutrients"]["potassium_mg"]
    # 29 Sep (2 spreads), 30 Sep (the quick add), 4 Oct (1 spread); planned entries and 24 Sep (before the period) not counted
    assert (k["unknown_entries"], k["unknown_days"]) == (4, 3)
    assert js["summary"]["interdialytic"]["nutrients"]["potassium_mg"]["unknown_entries"] == 1  # since Fri 2 Oct
    for day in js["range"]["days"]:
        py_day = day_figures(_rows(day["date"]), PROFILE)
        for key in ("unknown", "planned_unknown", "projected_unknown"):
            assert day[key] == py_day[key], (day["date"], key)
