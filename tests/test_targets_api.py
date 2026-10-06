"""API of the personalised targets and labs (note 05 §4.6, §4.9; ARCHITECTURE "M2 API: targets and labs").

Profile fields, ``GET /api/profile/suggested-targets`` (rules, derived, missing inputs, alerts, the 422
refusals), ``/api/labs`` (conversion echo, potassium alert, history, delete, validation), the
kidney-function card, the ``targets.*`` / ``user.units.labs`` settings, two-person isolation, and lab
results in the export archive and the account deletion.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from typing import Any

import pytest

from app import db
from app import settings_registry as registry
from app import target_rules as R
from app import units
from conftest import ADMIN_PASSWORD, USER_PASSWORD, send_json

TODAY = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> date:
    """The server's "today" for the rules (validation of future dates still uses the real clock)."""
    monkeypatch.setattr("app.profile.today", lambda: TODAY)
    return TODAY


def add_lab(client, analyte: str, value: float, unit: str | None = None, taken_on: str = "2026-10-01", **extra: Any) -> dict[str, Any]:
    body = {"analyte": analyte, "value": value, "unit": unit or units.analyte_def(analyte).canonical_unit, "taken_on": taken_on, **extra}
    response = client.post("/api/labs", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Profile fields
# --------------------------------------------------------------------------- #


def test_profile_has_the_new_fields_with_defaults(client):
    profile = client.get("/api/profile").json()
    assert {k: profile[k] for k in ("birth_month", "sex", "activity", "transplant_date", "frail_or_sarcopenic",
                                    "weight_6_months_ago_kg", "pregnant_or_breastfeeding", "hyperkalemia_history",
                                    "urine_output_ml", "pd_uf_ml", "pd_dialysate_kcal")} == {
        "birth_month": None, "sex": "unspecified", "activity": None, "transplant_date": None, "frail_or_sarcopenic": False,
        "weight_6_months_ago_kg": None, "pregnant_or_breastfeeding": False, "hyperkalemia_history": False,
        "urine_output_ml": None, "pd_uf_ml": None, "pd_dialysate_kcal": None,
    }


def test_profile_put_stores_merges_and_clears_the_new_fields(client):
    body = {"birth_month": "1971-03", "sex": "male", "activity": "low_active", "transplant_date": "2019-04-02",
            "frail_or_sarcopenic": True, "weight_6_months_ago_kg": 80, "pregnant_or_breastfeeding": False,
            "hyperkalemia_history": True, "urine_output_ml": 450, "pd_uf_ml": 700, "pd_dialysate_kcal": 320.5}
    saved = client.put("/api/profile", json=body).json()
    assert {k: saved[k] for k in body} == body
    # other fields keep their values (merge semantics)
    assert client.put("/api/profile", json={"name": "Ann"}).json()["birth_month"] == "1971-03"
    # empty or null clears: nullable fields to null, sex and the yes/no fields back to their defaults
    cleared = client.put("/api/profile", json={"birth_month": "", "sex": None, "activity": "", "transplant_date": None,
                                               "frail_or_sarcopenic": None, "hyperkalemia_history": None,
                                               "urine_output_ml": "", "pd_dialysate_kcal": None}).json()
    assert cleared["birth_month"] is None and cleared["sex"] == "unspecified" and cleared["activity"] is None
    assert cleared["transplant_date"] is None and cleared["frail_or_sarcopenic"] is False and cleared["hyperkalemia_history"] is False
    assert cleared["urine_output_ml"] is None and cleared["pd_dialysate_kcal"] is None and cleared["pd_uf_ml"] == 700


@pytest.mark.parametrize(
    "body, message",
    [
        ({"birth_month": "1971-3"}, "birth_month: must be a year and month formatted YYYY-MM"),
        ({"birth_month": "1971-13"}, "birth_month: must be a year and month formatted YYYY-MM"),
        ({"birth_month": "2999-01"}, "birth_month: must not be in the future"),
        ({"birth_month": "1880-01"}, "birth_month: must be within the last 120 years"),
        ({"sex": "other"}, "sex: "),
        ({"activity": "athlete"}, "activity: "),
        ({"transplant_date": "2999-01-01"}, "transplant_date: must not be in the future"),
        ({"transplant_date": "2026-02-30"}, "transplant_date: date is not a valid calendar date"),
        ({"weight_6_months_ago_kg": 19}, "weight_6_months_ago_kg: "),
        ({"weight_6_months_ago_kg": 401}, "weight_6_months_ago_kg: "),
        ({"urine_output_ml": -1}, "urine_output_ml: "),
        ({"urine_output_ml": 5001}, "urine_output_ml: "),
        ({"pd_uf_ml": 4001}, "pd_uf_ml: "),
        ({"pd_dialysate_kcal": 1001}, "pd_dialysate_kcal: "),
        ({"frail_or_sarcopenic": "maybe"}, "frail_or_sarcopenic: "),
    ],
)
def test_profile_put_validates_the_new_fields(client, body, message):
    response = client.put("/api/profile", json=body)
    assert response.status_code == 400 and response.json()["detail"].startswith(message), response.text


def test_profile_put_refuses_non_finite_numbers(client):
    assert send_json(client, "PUT", "/api/profile", {"urine_output_ml": float("inf")}).status_code == 400


# --------------------------------------------------------------------------- #
# Suggested targets
# --------------------------------------------------------------------------- #


def test_suggested_targets_have_rules_derived_missing_inputs_and_alerts(client):
    client.put("/api/profile", json={"weight_kg": 70, "height_cm": 175, "ckd_stage": "3b", "birth_month": "1971-03", "sex": "male"})
    body = client.get("/api/profile/suggested-targets").json()  # note 05 §4.6 example (TV02)
    assert body["targets"] == {"calories_kcal": 2280, "protein_g": {"min": 56, "max": 56}, "carbs_g": 257, "carbs_per_meal_g": 65,
                               "fiber_g": {"min": 32}, "sodium_mg": 2000, "potassium_mg": 3500, "phosphorus_mg": 1000,
                               "calcium_mg": 1000, "fluid_ml": None}
    assert body["rules"][1] == {"id": "E-1", "source": "NASEM 2023 DRI Energy Table S-1; KDOQI 2020 3.1.1", "grade": "DRI; 1C (range)",
                                "opinion": True, "opinion_note": R.RULES["E-1"]["opinion_note"], "url": R.URL_NASEM_2023_ENERGY}
    derived = body["derived"]
    assert {k: derived[k] for k in ("mode", "age", "sex", "bmi", "reference_weight_kg", "weight_basis", "eer_kcal", "kcal_per_kg")} == {
        "mode": "ckd", "age": 55, "sex": "male", "bmi": 22.9, "reference_weight_kg": 70.0, "weight_basis": "actual",
        "eer_kcal": 2282, "kcal_per_kg": 32.6}
    assert derived["labs_used"]["potassium"] is None and derived["lab_rules_enabled"] is True
    assert body["missing_inputs"] == ["activity"] and body["alerts"] == []
    assert body["notes"][-1] == R.NOTES["END"]
    # never auto-saved
    assert client.get("/api/profile").json()["targets"] == {}


def test_suggested_targets_use_fresh_labs_and_return_the_potassium_alert(client):
    client.put("/api/profile", json={"weight_kg": 70, "height_cm": 170, "ckd_stage": "4", "birth_month": "1961-05", "sex": "female"})
    add_lab(client, "potassium", 5.2, taken_on="2026-06-01")  # older: not the newest
    add_lab(client, "potassium", 6.3, taken_on="2026-10-05")
    add_lab(client, "phosphate", 1.94, "mmol/L")  # 6.0 mg/dL -> PH-3
    body = client.get("/api/profile/suggested-targets").json()  # TV16 + phosphate
    assert body["targets"]["potassium_mg"] == 2000 and body["targets"]["phosphorus_mg"] == 800
    assert [r["id"] for r in body["rules"] if r["id"].startswith(("K-", "PH-"))] == ["K-5", "PH-3"]
    assert [(a["level"], a["code"], a["value"]) for a in body["alerts"]] == [("urgent", "potassium_very_high", 6.3)]
    assert body["derived"]["labs_used"]["phosphate"] == {"value": 6.0, "unit": "mg/dL", "taken_on": "2026-10-01"}


def test_stale_labs_do_not_change_targets(client):
    client.put("/api/profile", json={"weight_kg": 70, "ckd_stage": "3b"})
    add_lab(client, "potassium", 4.2, taken_on="2026-07-06")  # 91 days before TODAY
    body = client.get("/api/profile/suggested-targets").json()
    assert body["targets"]["potassium_mg"] == 3500 and "K-0" in [r["id"] for r in body["rules"]]


@pytest.mark.parametrize(
    "profile, code",
    [
        ({"pregnant_or_breastfeeding": True}, "out_of_scope_pregnancy"),
        ({"birth_month": "2009-01"}, "out_of_scope_under_18"),
        ({"birth_month": "2008-10"}, "out_of_scope_under_18"),  # TV23
        ({"transplant_date": "2026-08-24", "ckd_stage": "3a"}, "out_of_scope_early_transplant"),  # TV09
    ],
)
def test_out_of_scope_people_get_a_refusal_and_no_numbers(client, profile, code):
    client.put("/api/profile", json={"weight_kg": 60, "ckd_stage": "3a", **profile})
    response = client.get("/api/profile/suggested-targets")
    assert response.status_code == 422
    body = response.json()
    assert body == {"detail": R.REFUSALS[code][1], "code": code}
    assert "targets" not in body and "you can still enter" in body["detail"].lower()


def test_suggested_targets_still_400_without_a_weight(client):
    client.put("/api/profile", json={"birth_month": "1971-03"})
    response = client.get("/api/profile/suggested-targets")
    assert response.status_code == 400 and "weight" in response.json()["detail"]


def test_lab_rules_setting_and_freshness_settings(client):
    """C6: targets.lab_rules_enabled=false falls back to K-0/PH-0 but POST /api/labs still alerts."""
    client.put("/api/profile", json={"weight_kg": 70, "ckd_stage": "4"})
    add_lab(client, "phosphate", 6.0)
    response = client.patch("/api/admin/settings", json={"targets.lab_rules_enabled": False})
    assert response.status_code == 200, response.text
    alert = client.post("/api/labs", json={"analyte": "potassium", "value": 6.6, "unit": "mmol/L", "taken_on": "2026-10-04"}).json()
    assert [a["level"] for a in alert["alerts"]] == ["emergency"]
    body = client.get("/api/profile/suggested-targets").json()
    ids = [r["id"] for r in body["rules"]]
    assert "K-0" in ids and "PH-0" in ids and body["targets"]["potassium_mg"] == 3000 and body["targets"]["phosphorus_mg"] == 1000
    assert body["derived"]["lab_rules_enabled"] is False and [a["level"] for a in body["alerts"]] == ["emergency"]
    # back on, with a 3-day potassium window the 6.6 from 1 day ago still counts, the phosphate (4 days) does not
    client.patch("/api/admin/settings", json={"targets.lab_rules_enabled": True, "targets.lab_fresh_days.potassium": 3,
                                              "targets.lab_fresh_days.phosphate": 3})
    body = client.get("/api/profile/suggested-targets").json()
    assert body["targets"]["potassium_mg"] == 2000 and body["targets"]["phosphorus_mg"] == 1000
    assert "no phosphate result from the last 3 days" in [n for n in body["notes"] if n.startswith("Phosphorus")][0]


def test_default_activity_setting(client):
    client.put("/api/profile", json={"weight_kg": 70, "height_cm": 175, "birth_month": "1971-03", "sex": "male"})
    assert client.patch("/api/admin/settings", json={"targets.default_activity": "active"}).status_code == 200
    body = client.get("/api/profile/suggested-targets").json()
    assert body["derived"]["activity"] == "active" and body["missing_inputs"] == ["activity"]
    client.put("/api/profile", json={"activity": "inactive"})
    assert client.get("/api/profile/suggested-targets").json()["derived"]["activity"] == "inactive"
    assert client.patch("/api/admin/settings", json={"targets.default_activity": "sporty"}).status_code == 400


def test_settings_keys_match_the_rules():
    """One source of truth: the registry defaults equal app/units.py and app/target_rules.py."""
    for analyte in units.CONFIGURABLE_FRESHNESS:
        assert registry.get(f"targets.lab_fresh_days.{analyte}").default == units.fresh_days(analyte)
    assert registry.get("targets.default_activity").adapter.json_schema()["enum"] == list(R.ACTIVITIES)
    assert registry.get("targets.lab_rules_enabled").default is True
    assert registry.get("user.units.labs").adapter.json_schema()["enum"] == list(units.UNIT_SYSTEMS)


def test_lab_unit_preference_is_a_personal_setting_with_an_admin_default(client):
    settings = client.get("/api/me/settings").json()["settings"]
    assert settings["user.units.labs"] == {"value": "us", "source": "default", "editable": True}
    client.patch("/api/admin/settings", json={"user.units.labs": "si"})
    assert client.get("/api/me/settings").json()["settings"]["user.units.labs"]["value"] == "si"
    client.patch("/api/me/settings", json={"user.units.labs": "us"})
    assert client.get("/api/me/settings").json()["settings"]["user.units.labs"] == {"value": "us", "source": "user", "editable": True}
    assert client.patch("/api/me/settings", json={"user.units.labs": "metric"}).status_code == 400


# --------------------------------------------------------------------------- #
# Labs
# --------------------------------------------------------------------------- #


def test_post_lab_converts_and_echoes(client):
    lab = add_lab(client, "phosphate", 1.94, "mmol/L", note="  after dialysis  ")
    assert {k: lab[k] for k in ("analyte", "label", "value", "unit", "entered_value", "entered_unit", "display", "taken_on", "note", "alerts")} == {
        "analyte": "phosphate", "label": "Phosphate", "value": 6.0, "unit": "mg/dL", "entered_value": 1.94, "entered_unit": "mmol/L",
        "display": "1.94 mmol/L = 6.0 mg/dL", "taken_on": "2026-10-01", "note": "after dialysis", "alerts": []}
    assert lab["id"] > 0 and lab["created_at"].endswith("Z")
    creatinine = add_lab(client, "creatinine", 106, "umol/l")
    assert creatinine["entered_unit"] == "µmol/L" and creatinine["display"] == "106 µmol/L = 1.20 mg/dL" and creatinine["value"] == 1.2
    assert add_lab(client, "egfr", 58)["value"] == 58 and add_lab(client, "a1c", 53, "mmol/mol")["display"] == "53 mmol/mol = 7.0 %"


@pytest.mark.parametrize("value, level", [(5.9, None), (5.95, "urgent"), (6.0, "urgent"), (6.44, "urgent"), (6.45, "emergency"), (7.2, "emergency")])
def test_post_potassium_returns_the_safety_alert(client, value, level):
    lab = add_lab(client, "potassium", value)
    assert [a["level"] for a in lab["alerts"]] == ([] if level is None else [level])
    if level:
        alert = lab["alerts"][0]
        assert alert["code"] == "potassium_very_high" and alert["taken_on"] == "2026-10-01"
        assert alert["message"].startswith(f"Potassium {units.format_value('potassium', value)} mmol/L on 2026-10-01 is dangerously high.")


@pytest.mark.parametrize(
    "body, message",
    [
        ({"analyte": "sodium", "value": 140, "unit": "mmol/L", "taken_on": "2026-10-01"}, "analyte: "),
        ({"analyte": "potassium", "value": 4.2, "unit": "mg/dL", "taken_on": "2026-10-01"}, "unit 'mg/dL' is not accepted for potassium"),
        ({"analyte": "potassium", "value": 42, "unit": "mmol/L", "taken_on": "2026-10-01"}, "Potassium 42.0 mmol/L is outside the plausible range"),
        ({"analyte": "phosphate", "value": 15, "unit": "mmol/L", "taken_on": "2026-10-01"}, "Phosphate 15 mmol/L (46.5 mg/dL) is outside"),
        ({"analyte": "potassium", "value": -1, "unit": "mmol/L", "taken_on": "2026-10-01"}, "value: "),
        ({"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "2999-01-01"}, "taken_on: must not be in the future"),
        ({"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "1899-12-31"}, "taken_on: must be 1900 or later"),
        ({"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "05/10/2026"}, "taken_on: date must be formatted YYYY-MM-DD"),
        ({"analyte": "potassium", "value": 4.2, "unit": "mmol/L"}, "taken_on: "),
        ({"analyte": "potassium", "value": 4.2, "unit": "", "taken_on": "2026-10-01"}, "unit: "),
        ({"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "2026-10-01", "note": "x" * 501}, "note: "),
        ({"analyte": "potassium", "value": 4.2, "unit": "mmol/L", "taken_on": "2026-10-01", "user_id": 2}, "user_id: "),
    ],
)
def test_post_lab_validation(client, body, message):
    response = client.post("/api/labs", json=body)
    assert response.status_code == 400 and message in response.json()["detail"], response.text
    assert client.get("/api/labs").json()["labs"] == []


def test_post_lab_refuses_non_finite_values(client):
    response = send_json(client, "POST", "/api/labs", {"analyte": "potassium", "value": float("nan"), "unit": "mmol/L", "taken_on": "2026-10-01"})
    assert response.status_code == 400


def test_history_is_newest_first_filterable_and_limited(client):
    a = add_lab(client, "potassium", 4.1, taken_on="2026-09-01")
    b = add_lab(client, "potassium", 4.6, taken_on="2026-10-01")
    c = add_lab(client, "albumin", 3.6, taken_on="2026-10-01")
    d = add_lab(client, "potassium", 4.4, taken_on="2026-10-01")  # same day, entered later
    assert [x["id"] for x in client.get("/api/labs").json()["labs"]] == [d["id"], c["id"], b["id"], a["id"]]
    assert [x["id"] for x in client.get("/api/labs", params={"analyte": "potassium"}).json()["labs"]] == [d["id"], b["id"], a["id"]]
    assert [x["id"] for x in client.get("/api/labs", params={"limit": 2}).json()["labs"]] == [d["id"], c["id"]]
    assert client.get("/api/labs", params={"analyte": "sodium"}).status_code == 400
    assert client.get("/api/labs", params={"limit": 0}).status_code == 400
    assert client.get("/api/labs", params={"limit": 1001}).status_code == 400


def test_delete_lab(client):
    lab = add_lab(client, "potassium", 4.1)
    assert client.delete(f"/api/labs/{lab['id']}").status_code == 204
    assert client.delete(f"/api/labs/{lab['id']}").status_code == 404
    assert client.delete("/api/labs/0").status_code == 404
    assert client.delete(f"/api/labs/{2**63}").status_code == 404
    assert client.get("/api/labs").json()["labs"] == []


def test_kidney_function_card(client):
    client.put("/api/profile", json={"weight_kg": 70, "ckd_stage": "3b", "birth_month": "1976-10", "sex": "female"})
    assert client.get("/api/labs/kidney-function").json()["message"].startswith("No creatinine, cystatin C or eGFR result")
    add_lab(client, "creatinine", 1.2)
    add_lab(client, "uacr", 3.0, "mg/mmol")
    card = client.get("/api/labs/kidney-function").json()
    assert card["egfr"]["value"] == 55 and card["egfr"]["category"] == "G3a" and card["egfr"]["suggested_stage"] == "3a"
    assert card["albuminuria"]["category"] == "A2" and card["albuminuria"]["value_mg_g"] == 26.5
    assert card["profile_stage"] == "3b" and card["mode"] == "ckd" and "Talk to your nephrologist" in card["message"]
    assert client.get("/api/profile").json()["ckd_stage"] == "3b"  # never changed
    client.put("/api/profile", json={"sex": "unspecified"})
    card = client.get("/api/labs/kidney-function").json()
    assert card["egfr"]["value"] is None and card["egfr"]["female"] == 55 and card["egfr"]["male"] == 74
    client.put("/api/profile", json={"dialysis": "hemodialysis", "ckd_stage": "5"})
    assert client.get("/api/labs/kidney-function").json()["egfr"] is None


# --------------------------------------------------------------------------- #
# Two people, export and deletion
# --------------------------------------------------------------------------- #


def test_two_people_never_see_each_others_labs(two_clients):
    admin, sam = two_clients
    mine = add_lab(admin, "potassium", 6.2)
    theirs = add_lab(sam, "potassium", 4.0)
    assert [x["id"] for x in admin.get("/api/labs").json()["labs"]] == [mine["id"]]
    assert [x["id"] for x in sam.get("/api/labs").json()["labs"]] == [theirs["id"]]
    assert sam.delete(f"/api/labs/{mine['id']}").status_code == 404  # not yours = not found
    assert admin.get("/api/labs").json()["labs"][0]["id"] == mine["id"]
    # suggestions and the card use only your own results
    for c in (admin, sam):
        c.put("/api/profile", json={"weight_kg": 70, "ckd_stage": "3b"})
    assert admin.get("/api/profile/suggested-targets").json()["alerts"] and not sam.get("/api/profile/suggested-targets").json()["alerts"]
    add_lab(admin, "creatinine", 1.2)
    sam.put("/api/profile", json={"birth_month": "1976-10", "sex": "female"})
    assert sam.get("/api/labs/kidney-function").json()["egfr"] is None


def test_anonymous_requests_are_refused(anon_client):
    for method, path in (("get", "/api/labs"), ("post", "/api/labs"), ("delete", "/api/labs/1"), ("get", "/api/labs/kidney-function"),
                         ("get", "/api/profile/suggested-targets")):
        assert anon_client.request(method, path, json={} if method == "post" else None).status_code == 401, (method, path)


def test_export_contains_labs_and_the_new_profile_fields(client):
    client.put("/api/profile", json={"birth_month": "1971-03", "sex": "female", "hyperkalemia_history": True})
    add_lab(client, "phosphate", 1.94, "mmol/L", note="=HYPERLINK(\"x\")")
    add_lab(client, "potassium", 4.4)
    client.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD})
    response = client.get("/api/me/export.zip")
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    data = json.loads(archive.read("export.json"))
    assert data["profile"]["birth_month"] == "1971-03" and data["profile"]["hyperkalemia_history"] is True
    labs = data["lab_results"]
    assert [lab["analyte"] for lab in labs] == ["phosphate", "potassium"]
    assert labs[0]["value"] == pytest.approx(6.008, abs=0.001) and labs[0]["unit"] == "mg/dL" and labs[0]["entered_unit"] == "mmol/L"
    assert "user_id" not in labs[0]
    lines = archive.read("labs.csv").decode("utf-8").splitlines()
    assert lines[0] == "id,analyte,value,unit,entered_value,entered_unit,taken_on,note,created_at"
    assert len(lines) == 3 and "'=HYPERLINK" in lines[1]  # formula-escaped (ARCHITECTURE "CSV")


def test_empty_export_has_a_labs_header(client):
    client.post("/api/auth/reauth", json={"password": ADMIN_PASSWORD})
    archive = zipfile.ZipFile(io.BytesIO(client.get("/api/me/export.zip").content))
    assert archive.read("labs.csv").decode("utf-8").splitlines() == ["id,analyte,value,unit,entered_value,entered_unit,taken_on,note,created_at"]


def test_deleting_an_account_deletes_its_labs(two_clients, settings):
    admin, sam = two_clients
    add_lab(admin, "potassium", 4.5)
    add_lab(sam, "potassium", 4.0)
    add_lab(sam, "creatinine", 1.3)
    response = sam.request("DELETE", "/api/me", json={"password": USER_PASSWORD, "confirm": "DELETE"})
    assert response.status_code == 204, response.text
    conn = db.connect(settings.db_path)
    try:
        assert [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM lab_results")] == [1]
    finally:
        conn.close()
