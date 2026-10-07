"""Performance budget (note 06 §4.12): hardware-independent evaluation counts plus generous wall-clock
bounds, on the real food list and on the 2,000-food synthetic list (5 perturbed copies of
``data/foods.json``), each with 60 days of history and 100 saved meals in SQLite. The scenario is
``scripts/bench_guidance.py``'s (one source); run that script for p50/p95 tables on real hardware."""
from __future__ import annotations

import importlib.util
import statistics
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _bench():
    spec = importlib.util.spec_from_file_location("bench_guidance", ROOT / "scripts" / "bench_guidance.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BENCH = _bench()

# Generous bounds (ms, median of 5): about 4× the x86 budget, so a real regression fails and a busy CI
# runner does not. The budget itself (what-fits ≤ 25, swaps ≤ 5, plan-day ≤ 40, insights ≤ 15 ms
# engine time at 2,000 foods) is printed by the bench script.
WALL_CLOCK_MS = {"next-meal": 100.0, "swaps": 50.0, "plan-day": 150.0, "insights/day": 60.0, "insights/period": 60.0,
                 "hypo-options": 50.0}


@pytest.fixture(scope="module", params=[1, 5], ids=["real-395", "synthetic-2000"])
def scenario(request, tmp_path_factory):
    path = tmp_path_factory.mktemp(f"bench{request.param}") / "kidney.db"
    user_id = BENCH.build_database(path, request.param)
    return request.param, path, user_id


def test_evaluation_counts_stay_within_the_budget(scenario):
    copies, path, user_id = scenario
    counts = BENCH.counts(path, user_id)
    assert counts["foods"] == 395 * copies
    assert counts["what_fits_food_evaluations"] <= 4 * counts["eligible"]
    assert counts["plan_food_evaluations"] <= 8000
    assert counts["plan_meal_evaluations"] <= 1500


def test_requests_stay_well_inside_generous_wall_clock_bounds(scenario):
    _, path, user_id = scenario
    calls = BENCH.scenario(path, user_id)
    for name, bound in WALL_CLOCK_MS.items():
        calls[name]()  # warm
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            calls[name]()
            samples.append((time.perf_counter() - start) * 1000.0)
        assert statistics.median(samples) < bound, (name, samples)


def test_synthetic_copies_are_distinct_deterministic_foods():
    a = BENCH.synthetic_foods(3)
    b = BENCH.synthetic_foods(3)
    assert a == b and len(a["foods"]) == 3 * 395
    names = [f["name"] for f in a["foods"]]
    fdc = [f["fdc_id"] for f in a["foods"]]
    assert len(set(names)) == len(names) and len(set(fdc)) == len(fdc)


def test_bench_script_runs_and_reports(tmp_path, capsys):
    out = tmp_path / "bench.json"
    assert BENCH.main(["--runs", "2", "--copies", "1", "--json", str(out), "--max-p95", "10000"]) == 0
    printed = capsys.readouterr().out
    assert "next-meal" in printed and "engine only: plan-day" in printed
    import json

    report = json.loads(out.read_text())
    timings = report["sizes"]["395"]["timings_ms"]
    assert set(WALL_CLOCK_MS) <= set(timings)
    assert BENCH.main(["--runs", "1", "--copies", "1", "--max-p95", "0.0001"]) == 1  # the gate fails loudly
