"""Visit prep shows the server's numbers and does no sums of its own (ARCHITECTURE.md "Visit prep").

A seeded person's `GET /api/log/summary`, `GET /api/labs` and `GET /api/symptoms` answers go through the page's engine
(`app/static/js/engine/visitprep.js`, run by `tests/js/visitprep_runner.mjs`): every average, target, percent, count of days
over and count of foods that do not list a value must equal the endpoint's. A value some foods do not list is "at least" or
"Not listed", never 0. No network; fixture foods."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import log_food

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "visitprep_runner.mjs"
DAYS = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-05"]  # 10-04 has no entries
START, END = "2026-09-18", "2026-10-15"  # 28 days
ORDER = ["sodium_mg", "potassium_mg", "phosphorus_mg", "protein_g", "fluid_ml"]


def node(payload: dict[str, Any]) -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the Visit prep engine (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(payload), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def js_number(value: float, key: str) -> str:
    """`fmtNum` of js/engine/rules.js: whole numbers for mg, kcal and mL, one decimal otherwise, thousands separated."""
    if key.endswith(("_mg", "_ml")):
        return f"{round(value):,}"
    return f"{round(value, 1):,.1f}".rstrip("0").rstrip(".")


def summary(client: Any, start: str = START, end: str = END) -> dict[str, Any]:
    r = client.get("/api/log/summary", params={"start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()


def seed(client: Any) -> None:
    r = client.put("/api/profile", json={"weight_kg": 70, "targets": {
        "potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000, "protein_g": 60, "fluid_ml": 1500}})
    assert r.status_code == 200, r.text
    for day in DAYS:
        log_food(client, "banana", "breakfast", 2, day)
        log_food(client, "cheese", "lunch", 3, day)
        log_food(client, "chicken", "dinner", 1, day)
        log_food(client, "water", "snack", 2, day)


def test_the_averages_are_the_period_endpoints_numbers(client):
    seed(client)
    sm = summary(client)
    got = node({"summary": sm})["averages"]
    assert got["days"] == sm["days"] == 28 and got["loggedDays"] == sm["logged_days"] == len(DAYS)
    assert [r["key"] for r in got["rows"]] == ORDER  # sodium, potassium, phosphorus, protein, fluid
    assert got["withoutTarget"] == []
    for row in got["rows"]:
        nt = sm["nutrients"][row["key"]]
        assert row["text"] == js_number(nt["average"], row["key"]), row
        assert row["target"] == js_number(nt["target"], row["key"])
        assert row["percent"] == round(nt["fraction"] * 100) and row["daysOver"] == nt["days_over"]
        assert row["level"] == nt["level"] and row["judged"] == nt["assessment"]
        assert (row["unknownDays"], row["unknownEntries"]) == (0, 0) and row["atLeast"] is False
    # every number on the page is one the endpoint sent: the engine has no arithmetic of its own for the food log
    js = (ROOT / "app" / "static" / "js" / "engine" / "visitprep.js").read_text(encoding="utf-8")
    body = js.split("function averageRows", 1)[1].split("// ---- the lab results", 1)[0]
    assert not any(op in body for op in (" / ", " * ", ".reduce(", "Math.", "fsum")), "averageRows must only pick the server's numbers"


def test_a_target_that_is_not_set_is_named_and_fluid_only_appears_when_tracked(client):
    client.put("/api/profile", json={"weight_kg": 70, "targets": {"potassium_mg": 2500, "sodium_mg": 2000}})
    log_food(client, "banana", "breakfast", 1, "2026-10-01")
    got = node({"summary": summary(client)})["averages"]
    assert [r["key"] for r in got["rows"]] == ["sodium_mg", "potassium_mg"]
    assert got["withoutTarget"] == ["Phosphorus", "Protein"]  # fluid is not listed as missing: it is optional


def test_foods_that_do_not_list_a_value_are_at_least_or_not_listed_never_zero(client):
    client.put("/api/profile", json={"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000}})
    mystery = client.post("/api/foods", json={"name": "Mystery bar", "serving_desc": "1 bar", "serving_g": 50,
                                              "nutrients": {"sodium_mg": 100, "potassium_mg": None, "phosphorus_mg": None}})
    assert mystery.status_code == 201, mystery.text
    # 10-01: a banana and the bar (potassium known for one food only); 10-02: only the bar (nothing listed at all)
    log_food(client, "banana", "breakfast", 1, "2026-10-01")
    for day in ("2026-10-01", "2026-10-02"):
        r = client.post("/api/log", json={"date": day, "meal": "snack", "food_id": mystery.json()["id"], "servings": 1})
        assert r.status_code == 201, r.text
    sm = summary(client)
    rows = {r["key"]: r for r in node({"summary": sm})["averages"]["rows"]}
    k = rows["potassium_mg"]
    nt = sm["nutrients"]["potassium_mg"]
    assert k["unknownDays"] == nt["unknown_days"] == 2 and k["unknownEntries"] == nt["unknown_entries"] == 2
    assert k["text"] == f"≥ {js_number(nt['average'], 'potassium_mg')}" and k["atLeast"] is True and nt["average"] > 0
    assert k["level"] != "ok"  # a total that misses values is never "OK"
    assert rows["sodium_mg"]["text"] == js_number(sm["nutrients"]["sodium_mg"]["average"], "sodium_mg")  # known on every food
    # only the bar on the only logged day: "Not listed", with the counts, and no percent
    only = summary(client, "2026-10-02", "2026-10-02")
    row = {r["key"]: r for r in node({"summary": only})["averages"]["rows"]}["phosphorus_mg"]
    assert row["text"] == "Not listed" and row["percent"] is None
    assert (row["unknownDays"], row["unknownEntries"]) == (1, 1) and row["level"] == "unknown"
    assert "0" not in row["text"]


def test_days_without_entries_say_so_and_never_show_zero(client):
    client.put("/api/profile", json={"weight_kg": 70, "targets": {"potassium_mg": 2500}})
    sm = summary(client)
    got = node({"summary": sm})["averages"]
    assert got["loggedDays"] == 0 and got["rows"][0]["text"] == "No entries" and got["rows"][0]["percent"] is None


def test_lab_rows_are_the_newest_and_the_one_before_with_an_arrow(client):
    for analyte, value, unit, day in (("potassium", 4.8, "mmol/L", "2026-08-01"), ("potassium", 5.2, "mmol/L", "2026-09-20"),
                                      ("phosphate", 5.0, "mg/dL", "2026-08-01"), ("phosphate", 4.2, "mg/dL", "2026-09-20"),
                                      ("albumin", 3.8, "g/dL", "2026-09-20"), ("a1c", 7.0, "%", "2026-07-01"), ("a1c", 7.0, "%", "2026-09-01")):
        r = client.post("/api/labs", json={"analyte": analyte, "value": value, "unit": unit, "taken_on": day})
        assert r.status_code == 201, r.text
    labs = client.get("/api/labs", params={"limit": 1000}).json()["labs"]
    rows = {r["analyte"]: r for r in node({"labs": labs, "order": ["potassium", "phosphate", "albumin", "bicarbonate", "a1c"]})["labs"]}
    assert list(rows) == ["potassium", "phosphate", "albumin", "a1c"]  # bicarbonate: none saved, so no row
    assert rows["potassium"]["trend"] == "up" and rows["potassium"]["latest"]["taken_on"] == "2026-09-20"
    assert rows["potassium"]["previous"]["taken_on"] == "2026-08-01"
    assert rows["phosphate"]["trend"] == "down" and rows["a1c"]["trend"] == "same"
    assert rows["albumin"]["previous"] is None and rows["albumin"]["trend"] is None  # one result: no arrow
    by_id = {r["id"]: r for r in labs}
    for row in rows.values():  # the values are the server's rows, untouched
        assert row["latest"] == by_id[row["latest"]["id"]]


def test_symptoms_are_grouped_by_symptom_with_days_and_the_worst_severity(client):
    for day, symptom, sev, label in (("2026-10-01", "swelling", 1, ""), ("2026-10-03", "swelling", 3, ""), ("2026-10-03", "itching", 2, ""),
                                     ("2026-10-04", "other", 1, "Dry mouth"), ("2026-10-05", "other", 2, "dry mouth")):
        body = {"date": day, "symptom": symptom, "severity": sev, **({"label": label} if label else {})}
        r = client.post("/api/symptoms", json=body)
        assert r.status_code == 201, r.text
    rows = client.get("/api/symptoms", params={"start": START, "end": "2026-10-05"}).json()["symptoms"]
    groups = {g["name"]: g for g in node({"symptoms": rows})["groups"]}
    assert set(groups) == {"Swelling", "Itching", "Dry mouth"}  # an "other" is grouped by its own name, case ignored
    assert (groups["Swelling"]["dayCount"], groups["Swelling"]["worst"]) == (2, 3)
    assert [d["date"] for d in groups["Swelling"]["days"]] == ["2026-10-01", "2026-10-03"]
    assert groups["Swelling"]["red_flag"] and groups["Swelling"]["red_flag"]["prominent"] is True  # the handbook's line, as in Trends
    assert groups["Swelling"]["red_flag"]["text"] == next(r["red_flag"]["text"] for r in rows if r["symptom"] == "swelling" and r["severity"] == 3)
    assert groups["Itching"]["red_flag"] is None and groups["Dry mouth"]["dayCount"] == 2


def test_the_period_questions_and_their_limits():
    out = node({"range": {"today": "2026-10-15", "days": 28}, "questions": ["  Who do I call?  ", "", "Who do I call?", "two\nlines\tand\u0007bell", "x" * 400]})
    assert out["range"] == {"start": "2026-09-18", "end": "2026-10-15", "days": 28}
    q = out["questions"]
    assert q[0]["list"] == ["Who do I call?"] and q[0]["error"] == ""
    assert q[1]["error"] == "Write a question first." and q[2]["error"] == "That question is already on the list."
    assert q[3]["list"][-1] == "two lines and bell"  # one line of plain text
    assert len(q[4]["list"][-1]) == 300
    full = node({"questions": [f"question {i}" for i in range(21)]})["questions"]
    assert len(full[19]["list"]) == 20 and full[20]["error"].startswith("A page holds 20 questions") and len(full[20]["list"]) == 20
    for days, first in ((14, "2026-10-02"), (90, "2026-07-18")):
        assert node({"range": {"today": "2026-10-15", "days": days}})["range"]["start"] == first
