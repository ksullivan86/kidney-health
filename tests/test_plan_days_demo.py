"""The demo answers ``POST /api/guidance/plan-days`` and ``POST /api/log/clear-planned`` as the server does (design note 23).

The engine itself is checked by the ``plan_days`` cases of ``tests/data/guidance_vectors.json``; here the demo's routes
(``js/mock/guidance.js``, ``js/mock/log.js``) give the server's validation texts, the server's answer shape, and the same
rules for what clearing takes off: planned food only, never eaten food or a planned low treatment."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

import pytest
from conftest import HTTPS_URL, TestClient, make_settings, sign_in

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "demo_api.mjs"
DAY = "2026-10-05"
# The demo's sample log runs up to 3 days after today (js/mock/seed.js), so the planned range starts well after it.
FREE = [(date.today() + timedelta(days=30 + i)).isoformat() for i in range(3)]
TARGETS = {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": {"min": 42, "max": 56},
           "carbs_per_meal_g": 60}
BAD_PLANS = [
    {}, {"start": "2026-13-01"}, {"start": DAY, "days": 0}, {"start": DAY, "days": 15}, {"start": DAY, "days": 2.5},
    {"start": DAY, "days": None}, {"start": DAY, "meals": []}, {"start": DAY, "meals": ["dinner", "dinner"]},
    {"start": DAY, "meals": ["supper"]}, {"start": DAY, "date": DAY}, {"start": 5}, {"start": DAY, "variant": 5},
]
BAD_CLEARS = [
    {"start": DAY}, {"start": DAY, "end": "2026-10-04"}, {"start": "2026-10-01", "end": "2026-10-15"},
    {"start": DAY, "end": DAY, "ids": []}, {"start": DAY, "end": DAY, "ids": [0]}, {"start": DAY, "end": DAY, "ids": "x"},
    {"start": DAY, "end": DAY, "x": 1}, {"start": DAY, "end": DAY, "ids": [999999]},
]


def _demo(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assert shutil.which("node"), "Node.js 22 is needed to run the demo API (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(requests), capture_output=True, text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def server(tmp_path_factory) -> Iterator[TestClient]:
    from app.main import create_app

    settings = make_settings(tmp_path_factory.mktemp("plan-days-demo"), ROOT / "data" / "foods.json")
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        assert c.put("/api/profile", json={"targets": TARGETS, "diabetes": "type1", "dialysis": "none"}).status_code == 200
        yield c


# Maps whose keys follow the person's data (the demo person's sample profile has calorie and carb targets), not the model.
FREE_MAPS = {"projected_status", "projected_totals", "projected_unknown", "nutrients", "totals", "values", "room"}


def _shape(value: Any, path: str = "", out: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """The keys of every object in an answer, by where it sits (``days[].meals[].items[]``), merged over a list's items."""
    out = {} if out is None else out
    if isinstance(value, dict):
        out.setdefault(path, set()).update(value)
        for k, v in value.items():
            if k not in FREE_MAPS:
                _shape(v, f"{path}.{k}", out)
    elif isinstance(value, list):
        for v in value:
            _shape(v, f"{path}[]", out)
    return out


def _same_shape(demo: Any, real: Any) -> None:
    a, b = _shape(demo), _shape(real)
    for where in ("", ".days[]", ".days[].meals[]", ".days[].meals[].items[]", ".apply.entries[]", ".shopping.items[]"):
        assert where in a and where in b, where
    for where in a.keys() & b.keys():  # an empty list on one side says nothing about its items
        assert a[where] == b[where], where


def _error(r) -> dict[str, Any]:
    return {"ok": False, "status": r.status_code, "detail": r.json()["detail"]}


def test_the_demo_validates_both_routes_with_the_servers_words(server) -> None:
    profile = {"method": "PUT", "path": "/api/profile", "body": {"targets": TARGETS, "diabetes": "type1", "dialysis": "none"}}
    answers = _demo([profile]
                    + [{"method": "POST", "path": "/api/guidance/plan-days", "body": b} for b in BAD_PLANS]
                    + [{"method": "POST", "path": "/api/log/clear-planned", "body": b} for b in BAD_CLEARS])
    want = [_error(server.post("/api/guidance/plan-days", json=b)) for b in BAD_PLANS]
    want += [_error(server.post("/api/log/clear-planned", json=b)) for b in BAD_CLEARS]
    assert answers[1:] == want


def test_the_demo_plans_days_in_the_servers_shape_and_clears_only_planned_food(server) -> None:
    profile = {"method": "PUT", "path": "/api/profile", "body": {"targets": TARGETS, "diabetes": "type1", "dialysis": "none"}}
    plan = {"method": "POST", "path": "/api/guidance/plan-days", "body": {"start": FREE[0], "days": 3}}
    day = lambda d: {"method": "GET", "path": f"/api/log?date={d}"}  # noqa: E731
    bread, juice = {"$ref": [1, "foods.0.id"]}, {"$ref": [2, "foods.0.id"]}
    answers = _demo([profile,
                     {"method": "GET", "path": "/api/foods?q=Bread%2C%20white"},
                     {"method": "GET", "path": "/api/foods?q=Apple%20juice"},
                     {"method": "POST", "path": "/api/log", "body": {"date": FREE[1], "meal": "breakfast", "food_id": bread,
                                                                     "servings": 2}},
                     {"method": "POST", "path": "/api/log", "body": {"date": FREE[1], "meal": "snack", "food_id": juice,
                                                                     "servings": 1, "status": "planned"}},
                     plan,
                     {"method": "POST", "path": "/api/log/batch", "body": {"entries": {"$ref": [5, "apply.entries"]}}},
                     day(FREE[1]),
                     {"method": "POST", "path": "/api/log/clear-planned", "body": {"start": FREE[0], "end": FREE[2]}},
                     day(FREE[1]), day(FREE[0]), day(FREE[2])])
    assert all(a["ok"] for a in answers), [a for a in answers if not a["ok"]]
    eaten, low = answers[3]["body"], answers[4]["body"]
    assert eaten["status"] == "eaten" and low["status"] == "planned" and low["purpose"] == "hypo"
    demo = answers[5]["body"]
    real = server.post("/api/guidance/plan-days", json={"start": DAY, "days": 3}).json()
    assert demo["status"] == real["status"] == "ok"
    _same_shape(demo, real)
    assert [d["date"] for d in demo["days"]] == FREE and (demo["start"], demo["end"]) == (FREE[0], FREE[2])
    assert demo["rules_version"] == real["rules_version"]
    assert [m["meal"] for m in demo["days"][1]["meals"]] == ["lunch", "dinner"]  # breakfast is eaten, the snack is planned
    assert all(e["status"] == "planned" and e["purpose"] == "none" for e in demo["apply"]["entries"])
    added = answers[6]["body"]["results"]
    assert len(added) == len(demo["apply"]["entries"]) > 0
    mid = answers[7]["body"]
    assert mid["counts"]["eaten"] == 1  # planning made nothing eaten
    assert answers[8]["body"] == {"deleted": len(added)}
    assert sorted(e["id"] for e in answers[9]["body"]["entries"]) == sorted([eaten["id"], low["id"]])
    assert answers[10]["body"]["entries"] == answers[11]["body"]["entries"] == []


def test_the_demo_undo_takes_off_only_the_ids_it_is_given() -> None:
    profile = {"method": "PUT", "path": "/api/profile", "body": {"targets": TARGETS, "diabetes": "type1", "dialysis": "none"}}
    answers = _demo([profile,
                     {"method": "POST", "path": "/api/guidance/plan-days", "body": {"start": FREE[0], "days": 2}},
                     {"method": "POST", "path": "/api/log/batch", "body": {"entries": {"$ref": [1, "apply.entries"]}}},
                     {"method": "POST", "path": "/api/log/clear-planned",
                      "body": {"start": FREE[0], "end": FREE[1], "ids": [{"$ref": [2, "results.0.id"]}]}},
                     {"method": "GET", "path": f"/api/log?date={FREE[0]}"},
                     {"method": "GET", "path": f"/api/log?date={FREE[1]}"}])
    assert all(a["ok"] for a in answers), [a for a in answers if not a["ok"]]
    added = [r["id"] for r in answers[2]["body"]["results"]]
    assert answers[3]["body"] == {"deleted": 1}
    left = [e["id"] for e in answers[4]["body"]["entries"] + answers[5]["body"]["entries"]]
    assert sorted(left) == sorted(added[1:])
