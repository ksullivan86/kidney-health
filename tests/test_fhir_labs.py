"""Lab results from Apple Health clinical records (FHIR JSON files), the engine side.

The browser reads the Health export's ``clinical-records/*.json`` files (``js/engine/fhir_labs.js``, ``KH.fhirLabs``), maps each
Observation's LOINC code to one of the app's own tests, converts and range-checks the value only through ``js/engine/kidney_function.js``
(the parity-tested twin of ``app/units.py``) and sends just the rows the person keeps to ``POST /api/labs/import``. The reader has no
Python twin, so ``tests/data/fhir_labs_vectors.json`` (``tests/js/gen_fhir_labs_vectors.mjs``: hand-written resources and hand-written
expectations) pins it for ``node tests/js/run_vectors.mjs``, and this file checks that the table and every converted value agree with
the server: every LOINC code's test and unit exist in ``app/units.py`` (so the twin cannot drift), every importable row converts the
way ``units.convert`` does, and the server accepts what the reader proposes.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app import units

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests" / "data" / "fhir_labs_vectors.json").read_text(encoding="utf-8"))
DOCS = (ROOT / "docs" / "targets-and-labs.md").read_text(encoding="utf-8")
ENGINE = (ROOT / "app" / "static" / "js" / "engine" / "fhir_labs.js").read_text(encoding="utf-8")
LOINC = VECTORS["loinc"]


def day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def case(name_start: str) -> dict:
    found = [c for c in VECTORS["cases"] if c["name"].startswith(name_start)]
    assert len(found) == 1, name_start
    return found[0]


def rows(c: dict) -> list[str]:
    return [f"{r['taken_on']} {r['analyte']} {r['display']}" for r in c["expected"]["results"]]


def loinc_check_digit_ok(code: str) -> bool:
    """LOINC's mod 10 check digit (a Luhn check on the number before the hyphen)."""
    base, check = code.split("-")
    total = 0
    for i, ch in enumerate(reversed(base)):
        n = int(ch)
        if i % 2 == 0:
            n = n * 2
            n = n // 10 + n % 10
        total += n
    return (10 - total % 10) % 10 == int(check)


# --------------------------------------------------------------------------- the LOINC table against the server's units


def test_every_loinc_code_names_a_test_and_a_unit_the_server_has():
    assert len(LOINC) >= 20
    for entry in LOINC:
        analyte = units.analyte_def(entry["analyte"])  # the test exists in app/units.py (raises otherwise)
        # LOINC's own example unit for the code reads as a unit the server accepts for that test
        assert entry["unit"] is not None, entry
        assert units.canonical_unit_name(analyte.key, entry["unit"]) == entry["unit"], entry


def test_the_table_covers_the_servers_tests_it_can_and_names_each_once():
    codes = [e["code"] for e in LOINC]
    assert len(codes) == len(set(codes))
    for e in LOINC:
        assert re.fullmatch(r"\d{1,6}-\d", e["code"]) and loinc_check_digit_ok(e["code"]), e["code"]  # a typo in a code is caught here
        assert e["name"] and e["url"] == f"https://loinc.org/{e['code']}"
    tests = {e["analyte"] for e in LOINC}
    assert tests == set(units.ANALYTE_KEYS)  # all nine tests the app keeps have at least one LOINC code
    # the codes a reader is most likely to need, as the roadmap asks: serum/plasma potassium, creatinine, CKD-EPI 2021 eGFR, phosphate
    by_code = {e["code"]: e for e in LOINC}
    assert by_code["2823-3"]["analyte"] == "potassium" and by_code["2160-0"]["analyte"] == "creatinine"
    assert by_code["98979-8"]["analyte"] == "egfr" and "CKD-EPI 2021" in by_code["98979-8"]["name"]
    assert by_code["2777-1"]["analyte"] == "phosphate"


def test_no_code_for_a_specimen_or_formula_the_app_does_not_mean():
    # Only "Serum or Plasma" and LOINC's own "Serum, Plasma or Blood" are read (plus HbA1c, which is a blood test by nature, and the
    # urine albumin-to-creatinine ratio, the one urine test the app keeps). Blood-gas, 24-hour, race-specific, MDRD and paediatric codes are not.
    for e in LOINC:
        name = e["name"]
        for banned in ("24 hour", "Venous blood", "Arterial blood", "black population", "MDRD", "Schwartz", "CKiD", "Test strip"):
            assert banned not in name, e
        if e["analyte"] == "uacr":
            assert name.endswith("in Urine"), e
        elif e["analyte"] == "a1c":
            assert name.startswith("Hemoglobin A1c/Hemoglobin.total in Blood"), e
        else:
            assert "Serum or Plasma" in name or "Serum, Plasma or Blood" in name, e


def test_every_unit_spelling_is_a_unit_the_server_accepts_for_some_test():
    accepted = {name for a in units.ANALYTES.values() for name in a.units}
    assert VECTORS["unit_aliases"]
    for spelling, target in VECTORS["unit_aliases"].items():
        assert target in accepted, (spelling, target)
    # a microgram per milligram is a milligram per gram: the alias must not change a number
    assert VECTORS["unit_aliases"]["ug/mg"] == "mg/g"
    assert units.to_canonical("uacr", 24, "mg/g") == 24


def test_the_engine_has_no_table_the_docs_do_not_list():
    for e in LOINC:
        assert e["code"] in DOCS and e["url"] in DOCS, e["code"]  # docs/targets-and-labs.md cites every code's own loinc.org page
    in_docs = set(re.findall(r"https://loinc\.org/(\d+-\d)", DOCS))
    assert in_docs == {e["code"] for e in LOINC}
    # the module's own comment table is the same list
    in_engine = set(re.findall(r"\['(\w+)', '(\d+-\d)', '", ENGINE))
    assert {code for _, code in in_engine} == {e["code"] for e in LOINC}


# --------------------------------------------------------------------------- every proposed row against the server's conversion


def test_every_importable_row_converts_the_way_the_server_does():
    checked = 0
    for c in VECTORS["cases"]:
        for res in c["expected"]["results"]:
            converted = units.convert(res["analyte"], res["value"], res["unit"])
            assert converted["display"] == res["display"], (c["name"], res)
            assert res["label"] == units.analyte_def(res["analyte"]).label
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", res["taken_on"]), res
            checked += 1
    assert checked >= 60


def test_every_refusal_for_a_number_is_the_servers_own_message():
    checked = 0
    for c in VECTORS["cases"]:
        for prob in c["expected"]["problems"]:
            if "plausible range" in prob["problem"]:
                value, unit = prob["text"].rsplit(" ", 1)
                with pytest.raises(units.UnitError) as exc:
                    units.convert(prob["analyte"], float(value), unit)
                assert str(exc.value) == prob["problem"], (c["name"], prob)
                checked += 1
            if prob["problem"] == "Potassium must be a non-negative number":
                with pytest.raises(units.UnitError) as exc:
                    units.convert("potassium", -4, "mmol/L")
                assert str(exc.value) == prob["problem"]
                checked += 1
    assert checked >= 5


def test_a_unit_the_reader_refuses_is_a_unit_the_server_does_not_accept_for_that_test():
    refused = case("a unit the app does not know")
    for prob in refused["expected"]["problems"]:
        if prob["problem"].startswith("the app cannot convert the unit"):
            unit = re.search(r"“(.*?)”", prob["problem"]).group(1)
            if len(unit) > 40:
                continue
            with pytest.raises(units.UnitError):
                units.canonical_unit_name(prob["analyte"], unit)


def test_vectors_send_what_the_import_route_accepts(client):
    sent = []
    for c in VECTORS["cases"]:
        for res in c["expected"]["results"]:
            sent.append({"analyte": res["analyte"], "value": res["value"], "unit": res["unit"], "taken_on": day(1 + len(sent))})
    assert len(sent) >= 60
    r = client.post("/api/labs/import", json={"results": sent[:1000]})
    assert r.status_code == 200, r.text
    assert r.json()["refused"] == [] and r.json()["saved"] == len(sent[:1000])


def test_the_dates_in_the_vectors_are_what_the_server_would_accept():
    # The reader lets a result through only on a real day from 1900 to tomorrow (as POST /api/labs does).
    for c in VECTORS["cases"]:
        today = c["options"].get("today")
        for res in c["expected"]["results"]:
            d = date.fromisoformat(res["taken_on"])
            assert d >= date(1900, 1, 1)
            if today:
                assert d <= date.fromisoformat(today) + timedelta(days=1), (c["name"], res)


# --------------------------------------------------------------------------- what the cases say (hand-checked against the units)


def test_each_code_in_the_table_reads_in_its_own_example_unit():
    c = case("every code in the table")
    assert c["expected"]["counts"]["found"] == len(LOINC) == c["expected"]["counts"]["observations"]
    by_analyte = {}
    for res in c["expected"]["results"]:
        by_analyte.setdefault(res["analyte"], []).append(res)
    assert set(by_analyte) == set(units.ANALYTE_KEYS)
    # the creatinine given in µmol/L and the HbA1c in mmol/mol arrive in the canonical units the server stores
    assert "150 µmol/L = 1.70 mg/dL" in {r["display"] for r in by_analyte["creatinine"]}
    assert "53 mmol/mol = 7.0 %" in {r["display"] for r in by_analyte["a1c"]}


def test_units_written_in_the_ways_real_exports_use_reach_the_same_canonical_value():
    c = case("units written in the several ways")
    assert rows(c) == [
        "2026-09-09 egfr 38 mL/min/1.73 m²",
        "2026-09-08 potassium 4.7 mEq/L = 4.7 mmol/L",
        "2026-09-07 uacr 3.4 mg/mmol = 30.1 mg/g",
        "2026-09-06 albumin 40 g/L = 4.0 g/dL",
        "2026-09-05 a1c 53 mmol/mol = 7.0 %",
        "2026-09-04 phosphate 1.3 mmol/L = 4.0 mg/dL",
        "2026-09-03 phosphate 3.9 mg/dL",
        "2026-09-02 creatinine 150.28 µmol/L = 1.70 mg/dL",
        "2026-09-01 creatinine 1.70 mg/dL",
    ]
    # each of those, worked out here from the factors in app/units.py (KDIGO 2024 conversion table)
    assert round(units.to_canonical("phosphate", 1.3, "mmol/L"), 1) == 4.0
    assert round(units.to_canonical("creatinine", 150.28, "µmol/L"), 2) == 1.70
    assert round(units.to_canonical("albumin", 40, "g/L"), 1) == 4.0
    assert round(units.to_canonical("a1c", 53, "mmol/mol"), 1) == 7.0
    assert round(units.to_canonical("uacr", 3.4, "mg/mmol"), 1) == 30.1


def test_only_observations_with_a_final_status_a_tracked_code_and_a_single_number_are_rows():
    status = case("only final, amended and corrected")["expected"]["counts"]
    assert status["found"] == 3 and status["wrongStatus"] == 7
    assert case("records that are not Observations")["expected"]["counts"]["notLab"] == 9
    assert case("an Observation that is not a lab test")["expected"]["counts"]["unknownCode"] == 10
    unit = case("a unit the app does not know")["expected"]["counts"]
    assert unit["badUnit"] == 7 and unit["found"] == 1
    number = case("a value that is not a single number")["expected"]
    assert number["counts"]["noValue"] == 4 and number["counts"]["notExact"] == 2 and rows(case("a value that is not a single number")) == ["2026-09-05 potassium 4.4 mmol/L"]


def test_dates_follow_the_rule_in_the_docs():
    zone = case("an instant with a time zone")
    assert zone["options"]["tzOffsetMinutes"] == -420
    assert rows(zone) == [
        "2026-09-05 potassium 4.4 mmol/L", "2026-09-05 potassium 4.5 mmol/L", "2026-09-04 potassium 4.3 mmol/L",
        "2026-09-03 potassium 4.2 mmol/L", "2026-09-01 potassium 4.1 mmol/L",
    ]
    future = case("future days")["expected"]
    assert future["counts"]["badDate"] == 8 and [r["taken_on"] for r in future["results"]] == ["2026-10-16", "2026-10-15"]  # tomorrow: one day of slack, as the server


def test_limits_are_the_ones_the_brief_names():
    limits = VECTORS["limits"]
    assert limits["max_files"] == 2000 and limits["max_file_bytes"] == 1024 * 1024
    assert limits["max_results"] == 1000  # what POST /api/labs/import takes
    from app.models import MAX_LAB_IMPORT
    assert limits["max_results"] == MAX_LAB_IMPORT
    big = case("more than 2,000 files")["expected"]
    assert big["problem"].startswith("You chose 2,001 files") and big["results"] == [] and big["counts"]["read"] == 0
    assert case("a file the page could not read")["expected"]["counts"]["tooBig"] == 2
    assert case("a file nested too deeply")["expected"]["counts"]["tooComplex"] == 3
    assert case("files that are not JSON")["expected"]["counts"]["notJson"] == 4


def test_nothing_from_the_identity_of_a_file_is_in_an_answer():
    # The resources carry a made-up name, id and provider; the reader never looks at them, so no answer holds them.
    for c in VECTORS["cases"]:
        answer = json.dumps(c["expected"], ensure_ascii=False)
        for secret in ("Sam Example", "Dr Example", "example-0001", "example-0002"):
            assert secret not in answer, (c["name"], secret)
    assert any("Sam Example" in json.dumps(c["files"]) for c in VECTORS["cases"])  # and the inputs do carry them


def test_the_vectors_are_hand_written_resources_with_no_real_person():
    text = json.dumps(VECTORS["cases"], ensure_ascii=False)
    hosts = {urlparse(url).hostname for url in re.findall(r'https?://[^\s"\\]+', text)}
    assert "Sam Example" in text and "example.org" in hosts  # made-up names and the reserved example domain
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)  # no social-security-like number
    assert not re.search(r"@[a-z0-9.-]+\.[a-z]{2,}", text)  # no e-mail address
