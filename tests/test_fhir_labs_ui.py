"""The browser side of "Import from Apple Health (clinical records)": ``app/static/js/views/lab_fhir.js``, its card in ``index.html``, the
engine ``js/engine/fhir_labs.js``, ``css/labs.css``.

The files are read on the device and never uploaded: nothing in the two scripts is an inline script, handler, style or HTML string,
neither makes a network call (the only way out is the CSV import's own save, ``KH.views.labs.saveImported``, which sends the rows the
person kept to ``POST /api/labs/import``), nothing is kept in the browser's storage, and what the page does (a file over 1 MB is never
read, more than 2,000 files are refused before any is read, new results start ticked, saved ones do not, only ticked rows are handed to
the save, and text from a file is drawn as text) is checked by running the file against a fake page in Node
(``tests/js/fhir_labs_page.mjs``).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = (STATIC / "js" / "views" / "lab_fhir.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "fhir_labs.js").read_text(encoding="utf-8")
LABS_JS = (STATIC / "js" / "views" / "labs.js").read_text(encoding="utf-8")
MOCK_LABS = (STATIC / "js" / "mock" / "labs.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
LABS_CSS = (STATIC / "css" / "labs.css").read_text(encoding="utf-8")
CARD = INDEX[INDEX.index('<section class="card" id="lab-fhir"'):]
CARD = CARD[:CARD.index("</section>")]


def code_of(js: str) -> str:
    """The script without its comments and string literals' contents, for checks on what it can DO."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|[^:'\"`])//[^\n]*", r"\1", js)


def test_the_files_are_in_the_shell_in_dependency_order_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/engine/kidney_function.js") < scripts.index("js/engine/fhir_labs.js") < scripts.index("js/core.js")
    assert scripts.index("js/engine/lab_import.js") + 1 == scripts.index("js/engine/fhir_labs.js")
    assert scripts.index("js/views/labs.js") < scripts.index("js/views/lab_fhir.js") < scripts.index("js/main.js")  # saveImported exists first
    assert "'/js/engine/fhir_labs.js'," in SW and "'/js/views/lab_fhir.js'," in SW
    assert "KH.fhirLabs = {" in ENGINE and "KH.labFhir = {" in VIEW


def test_the_card_sits_next_to_the_csv_import_and_explains_the_steps():
    assert INDEX.index('id="lab-import"') < INDEX.index('id="lab-fhir"') < INDEX.index('id="lab-photo"')
    assert "Import from Apple Health (clinical records)" in CARD
    for words in ("Export All Health Data", "Files", "unzip", "clinical-records", "Select All", "nothing is uploaded"):
        assert words in CARD, words
    assert re.search(r'<input id="lab-fhir-file"[^>]* type="file" multiple accept="[^"]*\.json[^"]*"', CARD)
    assert 'id="lab-fhir-preview"' in CARD and "Up to 2,000 files, 1 MB each" in CARD
    # no capture attribute, no form, no action: the chooser can only hand files to the page
    assert "<form" not in CARD and "capture=" not in CARD and "action=" not in CARD


def test_no_inline_script_handler_style_or_html_string():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    assert not re.search(r"\s(on[a-z]+|style)\s*=", CARD, re.IGNORECASE)
    for name, js in (("lab_fhir.js", VIEW), ("fhir_labs.js", ENGINE)):
        assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\(|new Function|\bFunction\(", js), name
        assert not re.search(r"""\s(on[a-z]+|style)\s*:|['"]\s*(on[a-z]+|style)\s*['"]\s*:""", code_of(js), re.IGNORECASE), name
    assert not re.search(r"<\s*(script|img|iframe|style|a|b|i|u)\b", VIEW, re.IGNORECASE)
    assert "textContent" in VIEW or "h('" in VIEW  # text goes in through the h() helper, which sets text nodes


def test_nothing_is_uploaded_the_only_way_out_is_the_csv_imports_own_save():
    for name, js in (("lab_fhir.js", VIEW), ("fhir_labs.js", ENGINE)):
        code = code_of(js)
        assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|\bimport\s*\(|navigator\.", code), name
        assert not re.search(r"localStorage|sessionStorage|indexedDB|caches\.|document\.cookie", code), name  # nothing is kept in the browser
        assert not re.search(r"\bapi\.|\brequest\(|FormData|\.upload", code), name
    assert not re.search(r"https?://", code_of(VIEW))
    assert "KH.views.labs.saveImported(kept, box, 'your Apple Health files', forget)" in VIEW
    assert "importLabs" not in VIEW
    # the shared save is the CSV import's own and is unchanged in what it sends: the ticked rows' test, value, unit and day only
    assert "api.importLabs(LI.requestBody(kept))" in LABS_JS
    assert "results.map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on }))" in (STATIC / "js" / "engine" / "lab_import.js").read_text(encoding="utf-8")
    # the file contents are read with File.text() and handed on; the file object itself and its name are never given to the save
    assert "file.text()" in VIEW and "FileReader" not in VIEW and "URL.createObjectURL" not in VIEW
    assert "kept = ticked().map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on, label: r.label, text: r.text }))" in VIEW


def test_the_engine_reads_only_fixed_paths_and_never_evaluates():
    code = code_of(ENGINE)
    assert "JSON.parse(" in code and code.count("JSON.parse(") == 1  # the one parse, in try/catch
    assert re.search(r"try \{\s*doc = JSON\.parse\(", code)
    assert not re.search(r"\beval\b|new Function|\bFunction\b|Object\.assign|__proto__|constructor\[|\[\s*['\"]constructor", code)
    # the people in a file are never read
    for field in ("subject", "performer", "patient", "name", "identifier", "telecom", "address", "birthDate", "note", "author"):
        assert not re.search(rf"\b(obs|doc|resource|entries\[i\])\.{field}\b", code), field
    for limit in ("MAX_FILES = 2000", "MAX_FILE_BYTES = 1024 * 1024", "MAX_DEPTH = 40", "MAX_NODES = 300000"):
        assert limit in ENGINE, limit


def test_the_demo_has_the_import_route_the_save_uses():
    assert "route('POST', '/api/labs/import'" in MOCK_LABS


def test_the_classes_the_file_uses_are_styled():
    css = LABS_CSS + (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    used = {token for group in re.findall(r"class: '([^']+)'", VIEW) for token in group.split()}
    assert {"lab-fhir-list", "lab-fhir-refused", "lab-import-list", "lab-import-saved", "lab-row", "lab-row-date", "lab-import-why"} <= used
    for cls in ("lab-fhir-steps", "lab-fhir-refused", "lab-import-list", "lab-import-saved", "lab-import-why"):
        assert f".{cls}" in css, cls


@pytest.fixture(scope="module")
def page():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "fhir_labs_page.mjs")], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_mixed_pick_is_read_on_the_device_and_summarised(page):
    mixed = page["mixed"]
    # every file is read except the one over 1 MB, which is never opened
    assert "huge.json" not in mixed["read"] and len(mixed["read"]) == 7
    assert mixed["summary"] == ("3 results found in 8 files; 2 records that are not lab results; 1 result in a unit the app cannot convert; "
                                "1 file that is not JSON; 1 file over 1 MB; 1 file that could not be read.")
    assert mixed["ticked"] == [True, True, True]  # the data comes from the health system, not an AI: new rows start ticked
    assert mixed["save"] == {"text": "Save 3 results", "disabled": False}
    assert mixed["rows"][:3] == ["Potassium 5.4 mmol/L", "Creatinine (blood) 150 µmol/L = 1.70 mg/dL", "Creatinine (blood) 1.70 mg/dL"]
    assert mixed["days"][:3] == ["day 2026-10-07", "day 2026-10-07", "day 2026-09-01"]
    assert mixed["why"] == ["Not imported (Observation-mgdl.json): the app cannot convert the unit “mg/dL” for Potassium"]
    assert mixed["classes"] == ["list labs-list lab-import-list lab-fhir-list", "list labs-list lab-import-list lab-fhir-refused"]  # the CSV import's table
    assert mixed["focused"] == "lab-fhir-summary"  # the headline is read out first
    assert "not from an AI" in mixed["hint"][0] and "Nothing is saved until you press Save" in mixed["hint"][0]


def test_only_the_ticked_rows_are_handed_to_the_save_and_no_file_name_or_identity_is(page):
    assert page["unticked"] == {"save": "Save 2 results"}
    saved = page["saved"]
    assert saved["saved"] == [{"kept": [
        {"analyte": "potassium", "value": 5.4, "unit": "mmol/L", "taken_on": "2026-10-07", "label": "Potassium", "text": "5.4 mmol/L"},
        {"analyte": "creatinine", "value": 1.7, "unit": "mg/dL", "taken_on": "2026-09-01", "label": "Creatinine (blood)", "text": "1.7 mg/dL"},
    ], "source": "your Apple Health files"}]
    assert saved["input"] == "" and saved["shown"] == "Saved 2"  # the chosen files are forgotten once saved
    sent = json.dumps(saved["saved"])
    for never in ("Sam Example", "example-0001", ".json", "Observation-"):
        assert never not in sent, never


def test_results_the_person_already_has_start_unticked_and_new_ones_ticked(page):
    saved = page["alreadySaved"]
    assert saved["summary"] == "2 results found in 2 files; 1 already saved."
    assert saved["ticked"] == [True, False] and saved["tags"] == ["already saved"] and saved["save"] == "Save 1 result"


def test_cancel_forgets_the_pick_and_sends_nothing(page):
    assert page["cancelled"] == {"box": "", "input": "", "focused": "input", "saved": 0}


def test_more_than_2000_files_are_refused_before_any_is_read(page):
    many = page["tooMany"]
    assert many["read"] == 0 and many["alert"] == 1
    assert many["message"] == "You chose 2,001 files; the app reads up to 2,000 at a time. Choose fewer files, for example only the Observation files."
    assert page["exactly2000"] == {"read": 2000, "summary": "1 result found in 2,000 files; 1,999 records that are not lab results."}


def test_a_bundle_with_over_a_thousand_results_shows_the_newest_thousand(page):
    many = page["many"]
    assert many["summary"] == "1,000 results found in 1 file; 5 left out (the app takes the newest 1,000 at a time)."
    assert many["rows"] == 1000 and many["save"] == {"text": "Save 1000 results", "disabled": False}  # POST /api/labs/import takes 1 to 1,000
    assert many["firstDay"] == "day 2025-10-01"


def test_text_from_a_file_is_drawn_as_text(page):
    hostile = page["hostile"]
    assert hostile["noRealElements"] is True
    assert set(hostile["tags"]) <= {"button", "div", "input", "label", "li", "p", "span", "ul"}
    assert any("<img src=x onerror=alert(1)>" in line for line in hostile["why"])
    assert any("<script>alert(1)</script>" in line for line in hostile["why"])


def test_a_pick_with_nothing_the_app_keeps_says_so_and_offers_no_save(page):
    nothing = page["nothing"]
    assert nothing["summary"] == "0 results found in 2 files; 2 records that are not lab results."
    assert nothing["buttons"] == ["Close"] and nothing["checkboxes"] == 0
    assert "No lab result the app keeps was found" in nothing["hint"][0]


def test_choosing_again_while_reading_drops_the_older_pick(page):
    assert page["newerWins"] == {"rows": ["Creatinine (blood) 1.20 mg/dL"]}
    assert page["empty"] == {"box": "", "children": 0}


def test_the_page_makes_no_network_call(page):
    assert page["network"] == []  # fetch, XMLHttpRequest, WebSocket and sendBeacon were all trapped; none was touched
