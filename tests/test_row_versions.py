"""Versions and ``If-Match`` for every synced kind (design note 39 §8.3; ``app/row_versions.py``).

Covered: the committed vectors are current, the field lists and what changes a version (and what does not: ids, timestamps, the
order of a food's flags), the API shape and the export shape give the same version, and every kind's ``PUT`` and ``DELETE`` route:
no header behaves as before, the right version changes the row, a stale one is ``412`` with the row as stored and nothing changes,
``*`` and lists, and another person's row is ``404`` whatever the header says. The JS twin is replayed by
``node tests/js/run_vectors.mjs``.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app import row_versions as RV
from conftest import DAY, find_food

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"


def generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_row_version_vectors", DATA / "gen_row_version_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_vectors_are_current():
    committed = json.loads((DATA / "row_version_vectors.json").read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(generator().build())), "run python3 tests/data/gen_row_version_vectors.py"


def test_the_vectors_cover_every_kind_and_the_rules():
    doc = generator().build()
    assert {c["kind"] for c in doc["cases"]} == set(RV.KINDS)
    by_name = {c["name"]: c["version"] for c in doc["cases"]}
    assert by_name["flags in one order"] == by_name["the same flags in the other order"]
    assert by_name["a saved meal"] == by_name["the same items on another server (other food ids)"]
    assert by_name["a saved meal"] != by_name["items in the other order"]
    assert by_name["a whole value"] == by_name["the same whole value as a float"]
    assert by_name["a lab result"] == by_name["a missing note is an empty note"]  # a lab's note "" and None: the same
    assert len(set(by_name.values())) >= len(by_name) - 6


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_browser_twin_agrees():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "run_vectors.mjs")], capture_output=True, text=True, timeout=600, check=False)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert "row version vectors:" in done.stdout


def test_a_version_ignores_ids_and_timestamps_but_not_content():
    lab = {"analyte": "potassium", "entered_value": 5.1, "entered_unit": "mmol/L", "taken_on": DAY, "note": ""}
    v = RV.row_version("lab", lab)
    assert RV.row_version("lab", {**lab, "id": 9, "created_at": "x", "client_id": "y", "value": 5.1}) == v
    assert RV.row_version("lab", {**lab, "note": None}) == v
    assert RV.row_version("lab", {**lab, "note": "x"}) != v
    assert RV.row_version("symptom", {"date": DAY, "symptom": "itching", "label": "", "severity": 2, "note": ""}) != v
    with pytest.raises(ValueError):
        RV.row_version("medicine", {})


# --------------------------------------------------------------------------- the routes


def _q(version: str) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def _make(client) -> dict[str, dict[str, Any]]:
    food = client.post("/api/foods", json={"name": "Grandma's rice pudding", "serving_desc": "1 bowl", "serving_g": 150,
                                          "nutrients": {"calories_kcal": 210, "potassium_mg": 180}}).json()
    apple = find_food(client, "apple")
    meal = client.post("/api/meals", json={"name": "Usual", "items": [{"food_id": apple["id"], "servings": 1}]}).json()
    lab = client.post("/api/labs", json={"analyte": "potassium", "value": 5.1, "unit": "mmol/L", "taken_on": DAY}).json()
    symptom = client.post("/api/symptoms", json={"date": DAY, "symptom": "itching", "severity": 2}).json()
    weight = client.post("/api/body/weights", json={"date": DAY, "time": "07:15", "kg": 70.2, "context": "morning"}).json()
    reading = client.post("/api/body/blood-pressure", json={"date": DAY, "time": "07:20", "systolic": 122, "diastolic": 78,
                                                           "context": "morning"}).json()
    return {"food": food, "meal": meal, "lab": lab, "symptom": symptom, "weight": weight, "reading": reading}


ROUTES = {"food": "/api/foods/{}", "meal": "/api/meals/{}", "lab": "/api/labs/{}", "symptom": "/api/symptoms/{}",
          "weight": "/api/body/weights/{}", "reading": "/api/body/blood-pressure/{}"}


def _edit_body(kind: str, row: dict[str, Any], apple_id: int) -> dict[str, Any]:
    if kind == "food":
        return {"name": "Rice pudding", "serving_desc": "1 bowl", "serving_g": 150, "nutrients": {"calories_kcal": 200}}
    if kind == "meal":
        return {"name": "Usual, changed", "items": [{"food_id": apple_id, "servings": 2}]}
    if kind == "symptom":
        return {"date": DAY, "symptom": "itching", "severity": 3}
    if kind == "weight":
        return {"date": DAY, "time": "07:15", "kg": 70.4, "context": "morning"}
    return {"date": DAY, "time": "07:20", "systolic": 124, "diastolic": 79, "context": "morning"}


def test_the_api_shape_and_the_export_shape_have_one_version(client):
    made = _make(client)
    exported = client.get("/api/me/export.zip")
    assert exported.status_code == 200
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(exported.content)) as z:
        doc = json.loads(z.read(next(n for n in z.namelist() if n.endswith(".json"))))
    pairs = {"food": doc["custom_foods"][0], "meal": doc["meal_templates"][0], "lab": doc["lab_results"][0], "symptom": doc["symptoms"][0],
             "weight": doc["weights"][0], "reading": doc["blood_pressures"][0]}
    for kind, row in pairs.items():
        assert RV.row_version(kind, row) == RV.row_version(kind, made[kind]), kind


@pytest.mark.parametrize("kind", ["food", "meal", "symptom", "weight", "reading"])
def test_put_takes_if_match(client, kind):
    made = _make(client)
    row = made[kind]
    apple_id = find_food(client, "apple")["id"]
    url = ROUTES[kind].format(row["id"])
    version = RV.row_version(kind, row)
    stale = "0" * 16
    r = client.put(url, json=_edit_body(kind, row, apple_id), headers=_q(stale))
    assert r.status_code == 412, r.text
    body = r.json()
    assert body["detail"].endswith("was changed on another device") and body["current"]["id"] == row["id"]
    assert body["current"]["version"] == version
    assert RV.row_version(kind, client.get(url).json() if kind in ("food", "meal") else body["current"]) == version  # nothing changed
    for weak in (f'W/"{version}"',):
        assert client.put(url, json=_edit_body(kind, row, apple_id), headers={"If-Match": weak}).status_code == 412
    r = client.put(url, json=_edit_body(kind, row, apple_id), headers={"If-Match": f'"{stale}", "{version}"'})
    assert r.status_code == 200, r.text
    changed = r.json()
    assert RV.row_version(kind, changed) != version
    assert client.put(url, json=_edit_body(kind, row, apple_id), headers=_q(version)).status_code == 412  # the old version is stale now
    assert client.put(url, json=_edit_body(kind, row, apple_id), headers={"If-Match": "*"}).status_code == 200
    assert client.put(url, json=_edit_body(kind, row, apple_id)).status_code == 200  # no header: as before


@pytest.mark.parametrize("kind", ["food", "meal", "lab", "symptom", "weight", "reading"])
def test_delete_takes_if_match(client, kind):
    made = _make(client)
    row = made[kind]
    url = ROUTES[kind].format(row["id"])
    r = client.delete(url, headers=_q("0" * 16))
    assert r.status_code == 412 and r.json()["current"]["version"] == RV.row_version(kind, row)
    r = client.delete(url, headers=_q(RV.row_version(kind, row)))
    assert r.status_code == 204, r.text
    assert client.delete(url, headers=_q(RV.row_version(kind, row))).status_code == 404


@pytest.mark.parametrize("kind", ["food", "meal", "lab", "symptom", "weight", "reading"])
def test_not_yours_is_404_whatever_the_header_says(two_clients, kind):
    admin, sam = two_clients
    made = _make(admin)
    row = made[kind]
    url = ROUTES[kind].format(row["id"])
    version = RV.row_version(kind, row)
    for header in (_q(version), _q("0" * 16), {"If-Match": "*"}):
        assert sam.delete(url, headers=header).status_code == 404, header
        if kind != "lab":
            body = _edit_body(kind, row, find_food(admin, "apple")["id"])
            assert sam.put(url, json=body, headers=header).status_code == 404, header
    assert admin.delete(url, headers=_q(version)).status_code == 204  # it was there all along
