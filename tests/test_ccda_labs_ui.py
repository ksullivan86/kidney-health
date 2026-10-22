"""The browser side of "Import from a patient portal file (C-CDA .xml)": ``app/static/js/views/lab_ccda.js``, its card in ``index.html``, the
engine ``js/engine/ccda_labs.js``, ``css/labs.css``.

The files are read and parsed on the device and never uploaded: nothing in the two scripts is an inline script, handler, style or HTML
string, neither makes a network call (the only way out is the CSV import's own save, ``KH.views.labs.saveImported``, which sends the
rows the person kept to ``POST /api/labs/import``), nothing is kept in the browser's storage, the only parser is the browser's
``DOMParser`` asked for ``application/xml``, a file with a DOCTYPE or ENTITY is refused before it is parsed, and what the page does (a file
over 5 MB is never read, more than 20 files are refused before any is read, new results start ticked, saved ones do not, only ticked rows are
handed to the save, and text from a file is drawn as text) is checked by running the file against a fake page in Node
(``tests/js/ccda_labs_page.mjs``).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = (STATIC / "js" / "views" / "lab_ccda.js").read_text(encoding="utf-8")
FHIR_VIEW = (STATIC / "js" / "views" / "lab_fhir.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "ccda_labs.js").read_text(encoding="utf-8")
LABS_JS = (STATIC / "js" / "views" / "labs.js").read_text(encoding="utf-8")
MOCK_LABS = (STATIC / "js" / "mock" / "labs.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
LABS_CSS = (STATIC / "css" / "labs.css").read_text(encoding="utf-8")
CARD = INDEX[INDEX.index('<section class="card" id="lab-ccda"'):]
CARD = CARD[:CARD.index("</section>")]


def code_of(js: str) -> str:
    """The script without its comments, for checks on what it can DO."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|[^:'\"`])//[^\n]*", r"\1", js)


def test_the_files_are_in_the_shell_in_dependency_order_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX, re.IGNORECASE)
    assert scripts.index("js/engine/kidney_function.js") < scripts.index("js/engine/fhir_labs.js") < scripts.index("js/engine/ccda_labs.js") < scripts.index("js/core.js")
    assert scripts.index("js/views/labs.js") < scripts.index("js/views/lab_fhir.js") < scripts.index("js/views/lab_ccda.js") < scripts.index("js/main.js")  # saveImported and the review table exist first
    assert "'/js/engine/ccda_labs.js'," in SW and "'/js/views/lab_ccda.js'," in SW
    assert "KH.ccdaLabs = {" in ENGINE and "KH.labCcda = {" in VIEW
    assert "FL = KH.fhirLabs" in ENGINE and "FH = KH.labFhir" in VIEW  # the pieces it borrows are there when it runs


def test_the_card_sits_next_to_the_apple_health_import_and_explains_the_steps():
    assert INDEX.index('id="lab-import"') < INDEX.index('id="lab-fhir"') < INDEX.index('id="lab-ccda"') < INDEX.index('id="lab-photo"')
    assert "Import from a patient portal file (C-CDA .xml)" in re.sub(r"</?span[^>]*>", "", CARD)  # the name is in a no-break span so it never breaks at its hyphen
    for words in ("MyChart", "health summary", "visit summary", "Download", "XML", "C-CDA", "not the PDF", "nothing is uploaded"):
        assert words in CARD, words
    assert re.search(r'<input id="lab-ccda-file"[^>]* type="file" multiple accept="[^"]*\.xml[^"]*"', CARD, re.IGNORECASE)
    assert 'id="lab-ccda-preview"' in CARD and "Up to 20 files, 5 MB each" in CARD
    # no capture attribute, no form, no action: the chooser can only hand files to the page
    assert "<form" not in CARD and "capture=" not in CARD and "action=" not in CARD


def test_no_inline_script_handler_style_or_html_string():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    assert not re.search(r"\s(on[a-z]+|style)\s*=", CARD, re.IGNORECASE)
    for name, js in (("lab_ccda.js", VIEW), ("ccda_labs.js", ENGINE)):
        assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\(|new Function|\bFunction\(", js), name
        assert not re.search(r"""\s(on[a-z]+|style)\s*:|['"]\s*(on[a-z]+|style)\s*['"]\s*:""", code_of(js), re.IGNORECASE), name
    assert not re.search(r"<\s*(script|img|iframe|style|a|b|i|u)\b", VIEW, re.IGNORECASE)
    assert "h('" in VIEW  # text goes in through the h() helper, which sets text nodes (the shared table is drawn the same way)
    assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML", FHIR_VIEW)


def test_nothing_is_uploaded_the_only_way_out_is_the_csv_imports_own_save():
    for name, js in (("lab_ccda.js", VIEW), ("ccda_labs.js", ENGINE)):
        code = code_of(js)
        assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|\bimport\s*\(|navigator\.", code), name
        assert not re.search(r"localStorage|sessionStorage|indexedDB|caches\.|document\.cookie", code), name  # nothing is kept in the browser
        assert not re.search(r"\bapi\.|\brequest\(|FormData|\.upload", code), name
    assert not re.search(r"https?://", code_of(VIEW))
    assert "KH.views.labs.saveImported(kept, box, 'your patient portal file', forget)" in VIEW
    assert "importLabs" not in VIEW
    # the shared save is the CSV import's own and is unchanged in what it sends: the ticked rows' test, value, unit and day only
    assert "api.importLabs(LI.requestBody(kept))" in LABS_JS
    assert "results.map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on }))" in (STATIC / "js" / "engine" / "lab_import.js").read_text(encoding="utf-8")
    # the file contents are read with File.text() and handed on; the file object itself and its name are never given to the save
    assert "file.text()" in VIEW and "FileReader" not in VIEW and "URL.createObjectURL" not in VIEW
    assert "onSave(kept, saveBtn)" in VIEW and "kept = ticked().map((r) => ({ analyte: r.analyte, value: r.value, unit: r.unit, taken_on: r.taken_on, label: r.label, text: r.text }))" in FHIR_VIEW


def test_the_only_parser_is_the_browsers_domparser_as_xml_and_the_view_never_parses():
    code = code_of(ENGINE)
    assert code.count("DOMParser") == 2  # the typeof guard at start-up and the one call
    assert "new root.DOMParser().parseFromString(trustedXml(text), 'application/xml')" in code
    # Trusted Types: the CSP lists exactly the policy this file creates (tests/test_frontend_shell.py guards that nothing else does)
    from app import security
    assert "trusted-types kh-sw kh-xml kh-pdf" in security.CSP_DIRECTIVES
    assert "tt.createPolicy('kh-xml'" in code and code.count("createPolicy(") == 1
    assert not re.search(r"text/html|text/xml|image/svg|application/xhtml|XSLTProcessor|\.load\(|createDocument|importNode|DOMImplementation", code)
    assert "DOMParser" not in code_of(VIEW) and "parseFromString" not in code_of(VIEW)
    # the parser is a parameter: the engine also runs under Node with tests/js/mini_xml.mjs, which no page file loads
    assert "opts.parseXml" in ENGINE
    assert "mini_xml" not in INDEX and "mini_xml" not in SW


def test_a_file_with_a_doctype_or_entity_is_refused_before_it_is_parsed_and_says_why():
    add = ENGINE[ENGINE.index("    function add(f) {"):ENGINE.index("    function finish() {")]
    assert re.search(r"const DTD_RE = /<!\\s\*\(\?:DOCTYPE\|ENTITY\)/i;", ENGINE, re.IGNORECASE)
    assert add.index("DTD_RE.test(text)") < add.index("parseXml(text)")
    # the reason reaches the person
    assert "a DOCTYPE or ENTITY declaration (a real health summary has none)" in ENGINE
    # and so does a malformed document (a parsererror element, wherever the browser puts it)
    assert "getElementsByTagName('parsererror')" in ENGINE and "'parsererror'" in ENGINE


def test_the_engine_reads_only_fixed_paths_and_never_the_people_in_a_file():
    code = code_of(ENGINE)
    assert not re.search(r"\beval\b|new Function|\bFunction\b|Object\.assign|__proto__|\['constructor'\]", code)
    # the elements it asks for and the attributes it reads: nothing else of a document is touched
    elements = set(re.findall(r"\bkids?\(\s*[\w.]+,\s*'(\w+)'", code))
    assert elements == {"templateId", "code", "translation", "statusCode", "effectiveTime", "low", "value"}
    attributes = set(re.findall(r"\battr\(\s*[\w.]+,\s*'([\w:]+)'", code))
    assert attributes == {"root", "codeSystem", "code", "nullFlavor", "value", "unit", "xsi:type"}
    structure = set(re.findall(r"'(\w+)'", re.search(r"const SECTION_PATH = (.*)\n\s*const ENTRY_PATH = (.*)\n", code).group(0)))
    assert structure == {"ClinicalDocument", "component", "structuredBody", "section", "entry", "organizer", "observation"}
    # no name, address, id, author, performer, narrative or note, and no node text of any kind
    for field in ("recordTarget", "patientRole", "patient", "name", "addr", "telecom", "author", "performer", "informant", "participant",
                  "assignedPerson", "assignedEntity", "birthTime", "id", "text", "originalText", "reference", "entryRelationship", "referenceRange",
                  "interpretationCode", "title", "participantRole", "playingEntity"):
        assert f"'{field}'" not in code, field
    assert not re.search(r"\.(textContent|innerText|nodeValue|wholeText|childNodes|firstChild|lastChild|data|attributes|outerHTML|cloneNode)\b", code)
    for limit in ("MAX_FILES = 20", "MAX_FILE_BYTES = 5 * 1024 * 1024", "MAX_ELEMENTS = 200000", "MAX_DEPTH = 64"):
        assert limit in ENGINE, limit


def test_the_demo_has_the_import_route_the_save_uses():
    assert "route('POST', '/api/labs/import'" in MOCK_LABS


def test_the_classes_the_file_uses_are_styled():
    css = LABS_CSS + (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    used = {token for group in re.findall(r"class: '([^']+)'", VIEW) for token in group.split()}
    assert used <= {"muted", "small", "form-error"}  # the table itself is drawn by the shared review of lab_fhir.js
    for cls in ("lab-fhir-steps", "lab-fhir-refused", "lab-import-list", "lab-import-saved", "lab-import-why"):
        assert f".{cls}" in css, cls
    assert 'class="small lab-fhir-steps"' in CARD


@pytest.fixture(scope="module")
def page():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "ccda_labs_page.mjs")], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_one_trusted_types_policy_is_created_once_and_refuses_a_dtd(page):
    # The page's CSP makes the parser a Trusted Types sink; the fake parser throws on a plain string just as Chromium does, so every pick
    # above went through the policy, which was created once.
    assert page["policy"] == {"created": ["kh-xml"], "xml": "accepted", "doctype": "refused", "entity": "refused", "notAString": "refused"}


def test_a_mixed_pick_is_read_on_the_device_and_summarised(page):
    mixed = page["mixed"]
    # every file is read except the one over 5 MB, which is never opened; the one with a DTD is read as text but never parsed
    assert "huge.xml" not in mixed["read"] and len(mixed["read"]) == 6
    assert mixed["parsed"] == ["application/xml"] * 4  # the two summaries, the text and the FHIR file; not dtd.xml
    assert mixed["summary"] == (
        "3 results found in 7 files; 1 result in a unit the app cannot convert; "
        "1 file refused because it has a DOCTYPE or ENTITY declaration (a real health summary has none); 1 file that is not valid XML; "
        "1 XML file that is not a C-CDA health summary; 1 file over 5 MB; 1 file that could not be read."
    )
    assert mixed["ticked"] == [True, True, True]  # the data comes from the health system, not an AI: new rows start ticked
    assert mixed["save"] == {"text": "Save 3 results", "disabled": False}
    assert mixed["rows"][:3] == ["Potassium 5.4 mmol/L", "Creatinine (blood) 150 µmol/L = 1.70 mg/dL", "Creatinine (blood) 1.70 mg/dL"]
    assert mixed["days"][:3] == ["day 2026-10-07", "day 2026-10-07", "day 2026-09-01"]
    assert mixed["why"] == ["Not imported (summary-2.xml): the app cannot convert the unit “mg/dL” for Potassium"]
    assert mixed["classes"] == ["list labs-list lab-import-list lab-fhir-list", "list labs-list lab-import-list lab-fhir-refused"]  # the shared table
    assert mixed["focused"] == "lab-ccda-summary"  # the headline is read out first
    assert "not from an AI" in mixed["hint"][0] and "Nothing is saved until you press Save" in mixed["hint"][0]
    # its own ids, so that it never shares one with the Apple Health table
    assert mixed["ids"] == ["lab-ccda-summary", "lab-ccda-row-0", "lab-ccda-row-1", "lab-ccda-row-2", "lab-ccda-save", "lab-ccda-cancel"]
    assert not any(i.startswith("lab-fhir") for i in mixed["ids"])


def test_only_the_ticked_rows_are_handed_to_the_save_and_no_file_name_or_identity_is(page):
    assert page["unticked"] == {"save": "Save 2 results"}
    saved = page["saved"]
    assert saved["saved"] == [{"kept": [
        {"analyte": "potassium", "value": 5.4, "unit": "mmol/L", "taken_on": "2026-10-07", "label": "Potassium", "text": "5.4 mmol/L"},
        {"analyte": "creatinine", "value": 1.7, "unit": "mg/dL", "taken_on": "2026-09-01", "label": "Creatinine (blood)", "text": "1.7 mg/dL"},
    ], "source": "your patient portal file"}]
    assert saved["input"] == "" and saved["shown"] == "Saved 2"  # the chosen files are forgotten once saved
    sent = json.dumps(saved["saved"])
    for never in ("Sam", "Example", "example", ".xml", "summary-"):
        assert never not in sent, never


def test_results_the_person_already_has_start_unticked_and_new_ones_ticked(page):
    saved = page["alreadySaved"]
    assert saved["summary"] == "2 results found in 2 files; 1 already saved."
    assert saved["ticked"] == [True, False] and saved["tags"] == ["already saved"] and saved["save"] == "Save 1 result"


def test_cancel_forgets_the_pick_and_sends_nothing(page):
    assert page["cancelled"] == {"box": "", "input": "", "focused": "input", "saved": 0}


def test_more_than_20_files_are_refused_before_any_is_read(page):
    many = page["tooMany"]
    assert many["read"] == 0 and many["parsed"] == 0 and many["alert"] == 1
    assert many["message"] == "You chose 21 files; the app reads up to 20 at a time. Choose fewer files, for example only your latest health summary."
    assert page["exactly20"]["read"] == 20 and page["exactly20"]["order"] == ["s-0.xml", "s-1.xml", "s-2.xml"]
    assert page["exactly20"]["summary"] == "1 result found in 20 files; 19 XML files that are not a C-CDA health summary."


def test_a_file_with_over_a_thousand_results_shows_the_newest_thousand(page):
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
    assert nothing["summary"] == "0 results found in 2 files; 1 XML file that is not a C-CDA health summary; 1 health summary without a Results section."
    assert nothing["buttons"] == ["Close"] and nothing["checkboxes"] == 0
    assert "No lab result the app keeps was found" in nothing["hint"][0] and "(not the PDF)" in nothing["hint"][0]


def test_choosing_again_while_reading_drops_the_older_pick(page):
    assert page["newerWins"] == {"rows": ["Creatinine (blood) 1.20 mg/dL"]}
    assert page["empty"] == {"box": "", "children": 0}


def test_the_page_makes_no_network_call(page):
    assert page["network"] == []  # fetch, XMLHttpRequest, WebSocket and sendBeacon were all trapped; none was touched
