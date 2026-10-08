"""v0.3.1 item 6 (docs/dev/plans/v0.3.1.md): lab results from a CSV file.

The browser reads the file (``js/engine/lab_import.js``, pinned by ``tests/data/lab_import_vectors.json`` and run by
``node tests/js/run_vectors.mjs``) and sends only the results the person kept to ``POST /api/labs/import``, which
checks each one like ``POST /api/labs``, skips repeats and lists what it refused.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import units
from app.models import MAX_LAB_IMPORT

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VECTORS = json.loads((ROOT / "tests" / "data" / "lab_import_vectors.json").read_text(encoding="utf-8"))


def day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def result(analyte: str, value: float, unit: str, taken_on: str, **extra) -> dict:
    return {"analyte": analyte, "value": value, "unit": unit, "taken_on": taken_on, **extra}


def labs(client) -> list[dict]:
    return client.get("/api/labs").json()["labs"]


# --------------------------------------------------------------------------- the route


def test_import_saves_each_result_converted_like_one_entry(client):
    r = client.post("/api/labs/import", json={"results": [
        result("potassium", 4.6, "mmol/L", day(30)),
        result("creatinine", 150, "umol/L", day(30)),
        result("phosphate", 1.2, "mmol/L", day(10), note="before dialysis"),
    ]})
    assert r.status_code == 200, r.text
    assert r.json() == {"saved": 3, "duplicates": 0, "refused": [], "alerts": []}
    rows = {row["analyte"]: row for row in labs(client)}
    assert rows["creatinine"]["display"] == "150 µmol/L = 1.70 mg/dL" and rows["creatinine"]["taken_on"] == day(30)
    assert rows["phosphate"]["display"] == "1.2 mmol/L = 3.7 mg/dL" and rows["phosphate"]["note"] == "before dialysis"
    # the same stored row as POST /api/labs would make
    one = client.post("/api/labs", json=result("potassium", 4.6, "mmol/L", day(31))).json()
    assert {k: v for k, v in rows["potassium"].items() if k not in ("id", "taken_on", "created_at")} == \
        {k: v for k, v in one.items() if k not in ("id", "taken_on", "created_at", "alerts")}


def test_refused_rows_are_listed_with_the_entry_message_and_the_rest_saved(client):
    single = client.post("/api/labs", json=result("potassium", 15, "mmol/L", day(3)))
    assert single.status_code == 400
    r = client.post("/api/labs/import", json={"results": [
        result("potassium", 15, "mmol/L", day(3)),        # implausible
        result("phosphate", 1.1, "mg/L", day(3)),          # a unit phosphate does not use
        result("albumin", 40, "g/L", day(-5)),             # in the future
        result("sodium", 140, "mmol/L", day(3)),           # not a test the app knows
        {"analyte": "potassium", "value": 4.1, "unit": "mmol/L"},  # no date
        result("potassium", 4.1, "mmol/L", day(3), flag="H"),     # a field the API does not take
        result("bicarbonate", 22, "mEq/L", day(3)),        # fine
    ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == 1 and body["duplicates"] == 0
    reasons = {x["index"]: x["reason"] for x in body["refused"]}
    assert sorted(reasons) == [0, 1, 2, 3, 4, 5]
    assert reasons[0] == single.json()["detail"]  # word for word what one entry would say
    assert "unit 'mg/L' is not accepted for phosphate" in reasons[1]
    assert reasons[2] == "taken_on: must not be in the future"
    assert reasons[3].startswith("analyte: Input should be")
    assert reasons[4] == "taken_on: Field required"
    assert reasons[5] == "flag: Extra inputs are not permitted"
    assert [row["analyte"] for row in labs(client)] == ["bicarbonate"]


def test_repeats_are_skipped_against_saved_results_and_within_the_request(client):
    client.post("/api/labs", json=result("potassium", 5.1, "mmol/L", day(5)))
    r = client.post("/api/labs/import", json={"results": [
        result("potassium", 5.1, "mEq/L", day(5)),     # saved already (mEq/L = mmol/L)
        result("potassium", 5.12, "mmol/L", day(5)),   # shown as 5.1: the same result
        result("potassium", 5.3, "mmol/L", day(5)),    # another value that day: saved
        result("potassium", 5.3, "mmol/L", day(5)),    # repeated in the request
        result("potassium", 5.1, "mmol/L", day(6)),    # another day: saved
    ]})
    assert r.json() == {"saved": 2, "duplicates": 3, "refused": [], "alerts": []}
    assert sorted((row["taken_on"], row["value"]) for row in labs(client)) == [(day(6), 5.1), (day(5), 5.1), (day(5), 5.3)]
    again = client.post("/api/labs/import", json={"results": [result("potassium", 5.3, "mmol/L", day(5))]})
    assert again.json()["saved"] == 0 and again.json()["duplicates"] == 1


def test_another_persons_results_are_never_repeats_and_never_touched(two_clients):
    admin, sam = two_clients
    admin.post("/api/labs", json=result("creatinine", 1.4, "mg/dL", day(20)))
    before = labs(admin)
    r = sam.post("/api/labs/import", json={"results": [result("creatinine", 1.4, "mg/dL", day(20))]})
    assert r.json()["saved"] == 1 and r.json()["duplicates"] == 0
    assert labs(admin) == before
    assert [row["analyte"] for row in labs(sam)] == ["creatinine"]


def test_a_very_high_newest_potassium_returns_the_safety_alert(client):
    r = client.post("/api/labs/import", json={"results": [result("potassium", 4.4, "mmol/L", day(40)),
                                                          result("potassium", 6.3, "mmol/L", day(2))]})
    alerts = r.json()["alerts"]
    assert [a["level"] for a in alerts] == ["urgent"]  # 6.0–6.4 mmol/L (KDIGO 2024 Table 28; 6.5 or more: emergency)
    assert alerts == client.get("/api/labs").json()["alerts"]  # the banner and the import agree


def test_the_request_shape_and_its_limits(client):
    for body, detail in (
        ({}, "results: Field required"),
        ({"results": []}, "results: List should have at least 1 item after validation, not 0"),
        ({"results": "x"}, "results: Input should be a valid list"),
        ({"results": [1]}, "results.0: Input should be a valid dictionary"),
        ({"results": [result("potassium", 4, "mmol/L", day(1))], "file": "x"}, "file: Extra inputs are not permitted"),
        ({"results": [result("potassium", 4, "mmol/L", day(1))] * (MAX_LAB_IMPORT + 1)},
         f"results: List should have at most {MAX_LAB_IMPORT} items after validation, not {MAX_LAB_IMPORT + 1}"),
    ):
        r = client.post("/api/labs/import", json=body)
        assert r.status_code == 400 and r.json()["detail"] == detail, (body if len(str(body)) < 200 else "too many", r.text)
    assert labs(client) == []
    full = client.post("/api/labs/import", json={"results": [result("potassium", round(3 + i / 1000, 3), "mmol/L", day(1 + i % 300))
                                                              for i in range(MAX_LAB_IMPORT)]})
    assert full.status_code == 200 and full.json()["saved"] + full.json()["duplicates"] == MAX_LAB_IMPORT


def test_import_needs_a_session(anon_client):
    r = anon_client.post("/api/labs/import", json={"results": [result("potassium", 4, "mmol/L", day(1))]})
    assert r.status_code == 401


# --------------------------------------------------------------------------- the reader's vectors


def test_the_vectors_cover_the_reader_and_agree_with_the_server_units():
    names = [case["name"] for case in VECTORS["cases"]]
    assert len(names) == len(set(names)) >= 10
    checked = 0
    for case in VECTORS["cases"]:
        for res in case["expected"].get("results", []):
            if res["problem"] is None:
                converted = units.convert(res["analyte"], res["value"], res["unit"])
                assert converted["display"] == res["display"], (case["name"], res)
                checked += 1
            elif res["display"] is None and res["value"] is not None and "plausible" in res["problem"]:
                with pytest.raises(units.UnitError) as exc:
                    units.convert(res["analyte"], res["value"], res["unit"])
                assert str(exc.value) == res["problem"], case["name"]
    assert checked >= 20


def test_vectors_send_what_the_import_route_accepts(client):
    # Every result the reader marks importable in the vectors (with dates moved into the past) is accepted.
    sent = []
    for case in VECTORS["cases"]:
        for res in case["expected"].get("results", []):
            if res["problem"] is None:
                sent.append(result(res["analyte"], res["value"], res["unit"], day(1 + len(sent))))
    r = client.post("/api/labs/import", json={"results": sent})
    assert r.status_code == 200 and r.json()["refused"] == [] and r.json()["saved"] == len(sent)


# --------------------------------------------------------------------------- the page


def test_the_labs_view_imports_from_a_file_read_on_the_device():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    labs_js = (STATIC / "js" / "views" / "labs.js").read_text(encoding="utf-8")
    assert 'id="lab-import-file"' in index and 'accept=".csv,text/csv,text/plain"' in index
    scripts = [line.strip() for line in index.splitlines() if line.strip().startswith("<script src=\"js/engine/")]
    assert scripts.index('<script src="js/engine/lab_import.js"></script>') > scripts.index('<script src="js/engine/kidney_function.js"></script>')
    assert "KH.labImport" in labs_js and "file.text()" in labs_js
    # only the kept results go to the server, never the file
    assert "api.importLabs(LI.requestBody(" in labs_js
    core = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
    assert "importLabs: (b) => request('POST', '/api/labs/import', b)" in core


def test_the_auth_coverage_list_names_the_route():
    # Every /api route needs a session (tests/test_auth_coverage.py walks the app); the contract list names this one.
    text = (ROOT / "tests" / "test_auth_coverage.py").read_text(encoding="utf-8")
    assert '("post", "/api/labs/import")' in text

