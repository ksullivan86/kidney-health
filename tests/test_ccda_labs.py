"""Lab results from a patient-portal C-CDA file (an XML health summary), the engine side.

The browser parses the file with ``DOMParser`` (``application/xml``) and ``js/engine/ccda_labs.js`` (``KH.ccdaLabs``) reads the Results
section's Result Observations: the LOINC code (and its translations) is mapped to one of the app's own tests by the table of
``js/engine/fhir_labs.js`` (used, not copied), the value is converted and range-checked only through ``js/engine/kidney_function.js``
(the parity-tested twin of ``app/units.py``), and just the rows the person keeps go to ``POST /api/labs/import``. The reader has no Python
twin and the server never sees the XML, so ``tests/data/ccda_labs_vectors.json`` (``tests/js/gen_ccda_labs_vectors.mjs``: hand-written
documents and hand-written expectations, parsed in Node by the dev-only ``tests/js/mini_xml.mjs``) pins it for
``node tests/js/run_vectors.mjs``. This file checks that every converted value agrees with the server, that the OIDs are the ones the
HL7 C-CDA templates have and are cited, that a file with a DTD is refused before it is parsed, and what the cases say.
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
VECTORS = json.loads((ROOT / "tests" / "data" / "ccda_labs_vectors.json").read_text(encoding="utf-8"))
FHIR_VECTORS = json.loads((ROOT / "tests" / "data" / "fhir_labs_vectors.json").read_text(encoding="utf-8"))
DOCS = (ROOT / "docs" / "targets-and-labs.md").read_text(encoding="utf-8")
ENGINE = (ROOT / "app" / "static" / "js" / "engine" / "ccda_labs.js").read_text(encoding="utf-8")
FHIR_ENGINE = (ROOT / "app" / "static" / "js" / "engine" / "fhir_labs.js").read_text(encoding="utf-8")

# The HL7 C-CDA R2.1 template identifiers and the LOINC code system, written out here by hand (docs/targets-and-labs.md cites the sources).
LOINC_OID = "2.16.840.1.113883.6.1"
RESULTS_ENTRIES_REQUIRED = "2.16.840.1.113883.10.20.22.2.3.1"
RESULTS_ENTRIES_OPTIONAL = "2.16.840.1.113883.10.20.22.2.3"
RESULT_ORGANIZER = "2.16.840.1.113883.10.20.22.4.1"
RESULT_OBSERVATION = "2.16.840.1.113883.10.20.22.4.2"
DTD = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def day(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def case(name_start: str) -> dict:
    found = [c for c in VECTORS["cases"] if c["name"].startswith(name_start)]
    assert len(found) == 1, name_start
    return found[0]


def rows(c: dict) -> list[str]:
    return [f"{r['taken_on']} {r['analyte']} {r['display']}" for r in c["expected"]["results"]]


# --------------------------------------------------------------------------- the identifiers


def test_the_template_identifiers_are_the_hl7_ccda_ones():
    assert VECTORS["oids"] == {
        "loinc": LOINC_OID,
        "results_section": [RESULTS_ENTRIES_REQUIRED, RESULTS_ENTRIES_OPTIONAL],
        "result_organizer": RESULT_ORGANIZER,
        "result_observation": RESULT_OBSERVATION,
        "results_section_code": "30954-2",
        "namespace": "urn:hl7-org:v3",
    }
    for oid in (LOINC_OID, RESULTS_ENTRIES_REQUIRED, RESULTS_ENTRIES_OPTIONAL, RESULT_ORGANIZER, RESULT_OBSERVATION):
        assert f"'{oid}'" in ENGINE, oid
        assert oid in DOCS, oid  # docs/targets-and-labs.md names every OID the reader relies on
    # and says where they were checked
    assert "Results Section (entries required)" in DOCS and "Results Section (entries optional)" in DOCS
    assert "Result Observation" in DOCS and "Result Organizer" in DOCS


def test_the_reader_reuses_the_fhir_readers_table_units_and_day_rule_and_copies_none_of_them():
    # no second LOINC table, no second unit table, no second day rule, no second collector
    assert not re.search(r"\['(\w+)', '(\d+-\d)', '", ENGINE)
    for token in ("UNIT_ALIASES", "LOINC_LIST", "canonicalUnitName", "K.convert", "formatValue", "parseIsoDate", "getTimezoneOffset"):
        assert token not in ENGINE, token
    for use in ("FL.LOINC", "FL.unitOf(", "FL.dayOf(", "FL.collector(", "col.keep(", "col.results()", "col.summarize("):
        assert use in ENGINE, use
    # the pieces it borrows are exported by the FHIR reader
    for name in ("dayOf", "collector", "unitOf", "shown", "quote", "plural", "num"):
        assert re.search(rf"\b{name}\b", FHIR_ENGINE.split("KH.fhirLabs = {")[1]), name


def test_every_code_in_the_table_reads_from_a_cda_in_its_ucum_unit_and_gives_the_rows_the_fhir_reader_gives():
    c = case("every code in the table")
    fhir = next(f for f in FHIR_VECTORS["cases"] if f["name"].startswith("every code in the table"))
    assert c["expected"]["counts"]["found"] == len(FHIR_VECTORS["loinc"]) == c["expected"]["counts"]["observations"]
    # the same values and days through the two readers are the same rows
    assert rows(c) == [f"{r['taken_on']} {r['analyte']} {r['display']}" for r in fhir["expected"]["results"]]
    by_analyte = {r["analyte"] for r in c["expected"]["results"]}
    assert by_analyte == set(units.ANALYTE_KEYS)


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
    assert checked >= 100


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
    seen = 0
    for prob in refused["expected"]["problems"]:
        if prob["problem"].startswith("the app cannot convert the unit"):
            unit = re.search(r"“(.*?)”", prob["problem"]).group(1)
            if len(unit) > 40:
                continue
            with pytest.raises(units.UnitError):
                units.canonical_unit_name(prob["analyte"], unit)
            seen += 1
    assert seen >= 4


def test_vectors_send_what_the_import_route_accepts(client):
    sent = []
    for c in VECTORS["cases"]:
        for res in c["expected"]["results"][:60]:
            sent.append({"analyte": res["analyte"], "value": res["value"], "unit": res["unit"], "taken_on": day(1 + len(sent))})
    assert len(sent) >= 100
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


def test_only_completed_result_observations_of_a_tracked_code_and_a_single_number_are_rows():
    status = case("only completed results")["expected"]["counts"]
    assert status["found"] == 3 and status["wrongStatus"] == 9
    assert case("an observation that is not a lab test")["expected"]["counts"]["unknownCode"] == 12
    unit = case("a unit the app does not know")["expected"]["counts"]
    assert unit["badUnit"] == 7 and unit["found"] == 1
    number = case("a value that is not a single number")
    assert number["expected"]["counts"]["noValue"] == 9 and number["expected"]["counts"]["notExact"] == 4
    assert rows(number) == ["2026-09-10 potassium 4.3 mmol/L", "2026-09-09 potassium 4.4 mmol/L"]
    blank = case("a value the lab left blank")["expected"]["counts"]
    assert blank["noValue"] == 2 and blank["unknownCode"] == 2 and blank["badDate"] == 2 and blank["found"] == 1


def test_only_results_sections_are_read_and_both_templates_count():
    sections = case("organizers, observations directly in an entry")["expected"]
    assert sections["counts"]["found"] == 10 and sections["counts"]["read"] == 5
    ignored = case("a section that is not a Results section")["expected"]["counts"]
    # a lab code in a Vital Signs or Problems section, an act, a nested observation, and observations without the Result Observation
    # template never become rows
    assert ignored["found"] == 1 and ignored["notLab"] == 2 and ignored["noResults"] == 3
    translations = case("LOINC translation codes")["expected"]["counts"]
    assert translations["found"] == 4 and translations["unknownCode"] == 2


def test_dates_follow_the_rule_in_the_docs():
    zone = case("a time with a time zone")
    assert zone["options"]["tzOffsetMinutes"] == -420
    assert rows(zone) == [
        "2026-09-08 potassium 4.7 mmol/L", "2026-09-07 potassium 4.6 mmol/L", "2026-09-05 potassium 4.4 mmol/L", "2026-09-05 potassium 4.5 mmol/L",
        "2026-09-04 potassium 4.3 mmol/L", "2026-09-03 potassium 4.2 mmol/L", "2026-09-01 potassium 4.1 mmol/L",
    ]
    future = case("future days")["expected"]
    assert future["counts"]["badDate"] == 10 and [r["taken_on"] for r in future["results"]] == ["2026-10-16", "2026-10-15"]  # tomorrow: one day of slack, as the server
    low = case("the day: effectiveTime/@value")["expected"]
    assert low["counts"]["found"] == 4 and low["counts"]["badDate"] == 2


def test_the_fhir_readers_counting_rules_hold_here_too():
    repeated = case("the same result twice")["expected"]
    assert repeated["counts"]["duplicates"] == 3 and repeated["counts"]["found"] == 2
    saved = case("a result the person already has")["expected"]
    assert saved["counts"]["saved"] == 1 and [r["saved"] for r in saved["results"]] == [True, False]
    big = case("a file with over a thousand results")["expected"]
    assert big["counts"]["found"] == 1000 and big["counts"]["leftOut"] == 5 and big["counts"]["observations"] == 1005
    from app.models import MAX_LAB_IMPORT
    assert VECTORS["limits"]["max_results"] == MAX_LAB_IMPORT == 1000  # what POST /api/labs/import takes


def test_limits_are_the_ones_the_brief_names():
    limits = VECTORS["limits"]
    assert limits["max_files"] == 20 and limits["max_file_bytes"] == 5 * 1024 * 1024
    many = case("more than 20 files")["expected"]
    assert many["problem"].startswith("You chose 21 files") and many["results"] == [] and many["counts"]["read"] == 0
    assert case("exactly 20 files")["expected"]["counts"]["read"] == 20
    assert case("a file the page could not read")["expected"]["counts"]["tooBig"] == 2
    assert case("a file whose text is over 5 MB")["expected"]["counts"]["tooBig"] == 1
    assert case("a file nested too deeply")["expected"]["counts"]["tooComplex"] == 3


# --------------------------------------------------------------------------- the DTD rule


def test_a_file_with_a_doctype_or_entity_declaration_is_refused_before_it_is_parsed():
    # in the engine: the test comes before the parser is called, and the file is counted, not cleaned
    add = ENGINE[ENGINE.index("    function add(f) {"):]
    assert add.index("DTD_RE.test(text)") < add.index("parseXml(text)")
    assert re.search(r"const DTD_RE = /<!\\s\*\(\?:DOCTYPE\|ENTITY\)/i;", ENGINE, re.IGNORECASE)
    assert "counts.doctype += 1; return;" in add
    # in the vectors: every file that has one is counted as refused for it (and none gave a row)
    refused = case("a file with a DOCTYPE or an ENTITY declaration")["expected"]
    assert refused["counts"]["doctype"] == 7 and refused["counts"]["found"] == 1
    assert "DOCTYPE or ENTITY declaration (a real health summary has none)" in " ".join(refused["summary"])
    for c in VECTORS["cases"]:
        files = c["files"]
        if isinstance(files, dict):
            continue
        with_dtd = [f for f in files if isinstance(f.get("text"), str) and DTD.search(f["text"])]
        assert c["expected"]["counts"]["doctype"] == len(with_dtd), c["name"]


def test_malformed_and_foreign_xml_is_counted_and_never_read():
    bad = case("files that are not XML")["expected"]["counts"]
    assert bad["notXml"] == 9 and bad["read"] == 1 and bad["found"] == 1
    foreign = case("XML that is not a C-CDA")["expected"]["counts"]
    assert foreign["notCcda"] == 5 and foreign["read"] == 1 and foreign["found"] == 0


# --------------------------------------------------------------------------- the people in a file


def test_nothing_from_the_identity_of_a_file_is_in_an_answer():
    # The documents carry a made-up name, id, address, phone, birth year and a note; the reader never looks at them, so no answer holds them.
    for c in VECTORS["cases"]:
        answer = json.dumps(c["expected"], ensure_ascii=False)
        for secret in ("Sam", "Example", "example-0001", "example-0002", "Exampleville", "Street", "tel:", "1970", "called back"):
            assert secret not in answer, (c["name"], secret)
    assert any("Sam" in json.dumps(c["files"]) and "Exampleville" in json.dumps(c["files"]) for c in VECTORS["cases"])  # and the inputs do carry them


def test_the_vectors_are_hand_written_documents_with_no_real_person():
    text = json.dumps(VECTORS["cases"], ensure_ascii=False)
    # Made-up names, and only the hosts of standard names the documents refer to (the XML Schema instance namespace, HL7's FHIR namespace
    # in a FHIR file that is not a C-CDA, LOINC's system URI in the same file); never a real organisation's address.
    hosts = {urlparse(url).hostname for url in re.findall(r'https?://[^\s"\\]+', text)}
    assert hosts == {"hl7.org", "loinc.org", "www.w3.org"}
    assert "Sam" in text and "Example" in text
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)  # no social-security-like number
    assert not re.search(r"@[a-z0-9.-]+\.[a-z]{2,}", text)  # no e-mail address
