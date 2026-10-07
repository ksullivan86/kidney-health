#!/usr/bin/env python3
"""Time the meal-guidance engine the way a request runs it (note 06 §4.12, §9 "Performance").

For each food-list size it builds a temporary SQLite database exactly as the app does (migrations,
builtin food import), with one person who has stage-4 targets, 60 days of eaten history (4 meals a
day, 3 foods each), 100 saved meals and a logged breakfast today. Each measured call loads that
person's guidance context from SQLite (warm food-vector cache, as in a running server) and runs the
engine function behind one endpoint. Sizes are copies of ``data/foods.json``: 1 copy is the real list
(395 foods), 5 copies are the 2,000-food budget case (copies 2–5 have every number perturbed by ±5 %
and their own names, so they are distinct foods).

Budget (§4.12): p95 < 200 ms per request on a Raspberry Pi 4 (4 GB) with 2,000 foods; on the x86 CI
runner what-fits ≤ 25 ms, swaps ≤ 5 ms, plan-day ≤ 40 ms, insights ≤ 15 ms (engine time).

Usage::

    python3 scripts/bench_guidance.py                 # 50 runs at 1 and 5 copies, a table
    python3 scripts/bench_guidance.py --runs 20 --copies 5 --json bench.json
    python3 scripts/bench_guidance.py --max-p95 200   # exit 1 if any p95 is above 200 ms (the Pi gate)

Record the Raspberry Pi 4 and Pi 5 numbers in docs/guidance.md ("Performance") before a release.
Nothing here needs the network; the database lives in a temporary directory that is removed.
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.foods import fetch_food, import_builtin_foods  # noqa: E402
from app.guidance import context as C  # noqa: E402
from app.guidance import fits, insights, planner, swaps  # noqa: E402
from app.guidance.score import Counter  # noqa: E402
from app.log import insert_entry  # noqa: E402
from app.meals import insert_template  # noqa: E402
from app.settings_store import SettingsStore  # noqa: E402

FOODS_JSON = ROOT / "data" / "foods.json"
TODAY = "2026-10-05"
TARGETS = {
    "calories_kcal": 2100, "protein_g": {"min": 42, "max": 56}, "carbs_g": 236, "carbs_per_meal_g": 60,
    "sodium_mg": 2000, "potassium_mg": 3000, "phosphorus_mg": 1000, "calcium_mg": 1000, "fluid_ml": None,
}
X86_BUDGET_MS = {"next-meal": 25.0, "swaps": 5.0, "plan-day": 40.0, "insights/day": 15.0}
COPY_FDC_OFFSET = 10_000_000


def synthetic_foods(copies: int, source: Path = FOODS_JSON) -> dict[str, Any]:
    """``data/foods.json`` plus ``copies − 1`` perturbed copies (deterministic, ±5 % per food)."""
    data = json.loads(source.read_text(encoding="utf-8"))
    out = []
    for copy in range(copies):
        for index, item in enumerate(data["foods"]):
            if copy == 0:
                out.append(item)
                continue
            factor = 1.0 + (((index * 7 + copy * 13) % 11) - 5) / 100.0
            clone = dict(item)
            clone["name"] = f"{item['name']} (copy {copy})"
            clone["fdc_id"] = item["fdc_id"] + COPY_FDC_OFFSET * copy
            clone["nutrients"] = {k: (None if v is None else round(float(v) * factor, 3)) for k, v in item["nutrients"].items()}
            out.append(clone)
    return {**data, "version": f"{data['version']}-x{copies}", "foods": out}


def build_database(path: Path, copies: int, seed: int = 1) -> int:
    """A database with ``copies`` of the food list and one person's 60 days; returns the user id (1)."""
    foods_file = path.parent / f"foods-x{copies}.json"
    foods_file.write_text(json.dumps(synthetic_foods(copies)), encoding="utf-8")
    db.init_db(path)
    conn = db.connect(path)
    try:
        import_builtin_foods(conn, foods_file)
        user_id = 1
        conn.execute("INSERT OR IGNORE INTO user_profiles (user_id, updated_at, updated_by) VALUES (?, ?, ?)",
                     (user_id, db.utcnow(), user_id))
        conn.execute("UPDATE user_profiles SET targets_json = ?, diabetes = 'type1', dialysis = 'none' WHERE user_id = ?",
                     (json.dumps(TARGETS), user_id))
        rows = conn.execute("SELECT id, flags_json FROM foods WHERE hidden = 0 ORDER BY id").fetchall()
        bad = ("avoid_ckd", "hypo_treatment", "ingredient")
        eligible = [r["id"] for r in rows if not any(f in (r["flags_json"] or "") for f in bad)]
        rnd = random.Random(seed)
        today = date.fromisoformat(TODAY)
        for back in range(1, 61):
            day = (today - timedelta(days=back)).isoformat()
            for meal in ("breakfast", "lunch", "dinner", "snack"):
                for food_id in rnd.sample(eligible, 3):
                    insert_entry(conn, user_id=user_id, date=day, meal=meal, food=fetch_food(conn, food_id),
                                 servings=rnd.choice([0.5, 1.0, 1.5]), grams=None, note=None)
        for food_id in rnd.sample(eligible, 2):
            insert_entry(conn, user_id=user_id, date=TODAY, meal="breakfast", food=fetch_food(conn, food_id), servings=1.0,
                         grams=None, note=None)
        for i in range(100):
            items = [{"food_id": fid, "servings": 1.0} for fid in rnd.sample(eligible, 3)]
            insert_template(conn, user_id=user_id, name=f"Saved meal {i + 1}", note=None, items=items,
                            meal_hint=rnd.choice(["breakfast", "lunch", "dinner", None]))
        conn.commit()
        return user_id
    finally:
        conn.close()


def timed(fn: Callable[[], Any], runs: int) -> dict[str, float]:
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    return {"p50": round(statistics.median(samples), 2),
            "p95": round(samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))], 2),
            "max": round(samples[-1], 2)}


def scenario(path: Path, user_id: int) -> dict[str, Callable[[], Any]]:
    """The engine call behind each endpoint, each loading the context from SQLite first."""
    store = SettingsStore(env={})
    cache = C.VectorCache()

    def ctx(day: str = TODAY, **opts: bool):
        conn = db.connect(path)
        try:
            return C.load(conn, user_id, day, store=store, foods_json=FOODS_JSON,
                          options=C.LoadOptions(**opts) if opts else C.LoadOptions(), cache=cache)
        finally:
            conn.close()

    probe = ctx()
    potato = next(f for f in probe.foods.values() if f.name == "Potato, baked, with skin")

    def period() -> Any:
        conn = db.connect(path)
        try:
            prof = C.load_profile(conn, user_id)
            prefs = C.load_prefs(conn, store, user_id)
            s, e, ps, pe = insights.period_bounds(None, None, TODAY)
            return insights.period_insights(prof, prefs, s, e, C.load_period(conn, user_id, s, e),
                                            C.load_period(conn, user_id, ps, pe))
        finally:
            conn.close()

    def cold_vectors() -> Any:
        conn = db.connect(path)
        try:
            return C.VectorCache().get(conn, user_id, FOODS_JSON)
        finally:
            conn.close()

    return {
        "next-meal": lambda: fits.what_fits(ctx(), "lunch"),
        "swaps": lambda: swaps.find_swaps(ctx(history60=False, combos=False), "dinner", potato, 1.0),
        "plan-day": lambda: planner.plan_day(ctx()),
        "insights/day": lambda: insights.day_insights(ctx(history60=False, saved_meals=False, combos=False)),
        "insights/period": period,
        "hypo-options": lambda: swaps.hypo_options(ctx(history=False, history60=False, saved_meals=False, combos=False)),
        "vectors (cold cache)": cold_vectors,
        "engine only: next-meal": (lambda c=probe: fits.what_fits(c, "lunch")),
        "engine only: swaps": (lambda c=probe: swaps.find_swaps(c, "dinner", potato, 1.0)),
        "engine only: plan-day": (lambda c=probe: planner.plan_day(c)),
        "engine only: insights/day": (lambda c=probe: insights.day_insights(c)),
    }


def counts(path: Path, user_id: int) -> dict[str, int]:
    conn = db.connect(path)
    try:
        ctx = C.load(conn, user_id, TODAY, store=SettingsStore(env={}), foods_json=FOODS_JSON, cache=C.VectorCache())
    finally:
        conn.close()
    fit, plan = Counter(), Counter()
    fits.what_fits(ctx, "lunch", counter=fit)
    planner.plan_day(ctx, counter=plan)
    return {"foods": len(ctx.foods), "eligible": len(fits.eligible_foods(ctx)), "what_fits_food_evaluations": fit.foods,
            "plan_food_evaluations": plan.foods, "plan_meal_evaluations": plan.meals}


def run(copies_list: list[int], runs: int) -> dict[str, Any]:
    report: dict[str, Any] = {"python": platform.python_version(), "machine": platform.machine(),
                              "processor": platform.processor() or platform.platform(), "runs": runs, "sizes": {}}
    for copies in copies_list:
        with tempfile.TemporaryDirectory(prefix="kh-bench-") as tmp:
            path = Path(tmp) / "kidney.db"
            user_id = build_database(path, copies)
            calls = scenario(path, user_id)
            for fn in calls.values():  # warm-up: caches, imports
                fn()
            size = {"counts": counts(path, user_id), "timings_ms": {name: timed(fn, runs) for name, fn in calls.items()}}
            report["sizes"][str(size["counts"]["foods"])] = size
    return report


def print_report(report: dict[str, Any]) -> None:
    print(f"Python {report['python']} on {report['machine']} ({report['processor']}), {report['runs']} runs each")
    for foods, size in report["sizes"].items():
        print(f"\n{foods} foods  {json.dumps(size['counts'])}")
        print(f"  {'call':<28}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}   x86 budget")
        for name, t in size["timings_ms"].items():
            budget = X86_BUDGET_MS.get(name.replace("engine only: ", "")) if name.startswith("engine only") else None
            mark = "" if budget is None else (f"≤ {budget:g} ms " + ("ok" if t["p95"] <= budget else "OVER"))
            print(f"  {name:<28}{t['p50']:>9.2f}{t['p95']:>9.2f}{t['max']:>9.2f}   {mark}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=50, help="timed runs per call (default 50)")
    parser.add_argument("--copies", default="1,5", help="food-list copies to test, comma-separated (default 1,5)")
    parser.add_argument("--json", type=Path, help="also write the report as JSON to this file")
    parser.add_argument("--max-p95", type=float, help="exit 1 when a request (not engine-only) p95 exceeds this many ms")
    args = parser.parse_args(argv)
    copies = [int(c) for c in args.copies.split(",") if c.strip()]
    if args.runs < 1 or not copies or any(c < 1 or c > 20 for c in copies):
        parser.error("--runs must be ≥ 1 and --copies between 1 and 20")
    report = run(copies, args.runs)
    print_report(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.max_p95 is not None:
        slow = [(foods, name, t["p95"]) for foods, size in report["sizes"].items()
                for name, t in size["timings_ms"].items()
                if not name.startswith("engine only") and name != "vectors (cold cache)" and t["p95"] > args.max_p95]
        for foods, name, p95 in slow:
            print(f"OVER BUDGET: {name} at {foods} foods: p95 {p95} ms > {args.max_p95} ms", file=sys.stderr)
        return 1 if slow else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
