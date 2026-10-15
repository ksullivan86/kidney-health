"""The browser side of "Read a lab report photo" (``app/static/js/views/lab_photo.js``, its card in ``index.html``, the shared save
in ``labs.js``, the hooks in ``ai.js`` and ``ai_routing.js``, ``css/labs.css``): the file is in the shell and the service worker,
nothing in it is an inline script, handler, style or HTML string, it reaches the server only through the app's own AI client, the
demo never offers it, and its behaviour (offered only when the server says so and why not, every row unticked, a row without a
date cannot be ticked, only ticked rows are saved through the CSV import's own save) is checked by running the file against a
fake page in Node (``tests/js/lab_photo_page.mjs``)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
PHOTO_JS = (STATIC / "js" / "views" / "lab_photo.js").read_text(encoding="utf-8")
LABS_JS = (STATIC / "js" / "views" / "labs.js").read_text(encoding="utf-8")
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
ROUTING_JS = (STATIC / "js" / "views" / "ai_routing.js").read_text(encoding="utf-8")
MOCK_AI = (STATIC / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
LABS_CSS = (STATIC / "css" / "labs.css").read_text(encoding="utf-8")
AI_CSS = (STATIC / "css" / "ai.css").read_text(encoding="utf-8")

NOTICE = "Read by AI from your photo. Check each value against the report before you tick it."


def test_the_file_is_in_the_shell_after_labs_js_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/labs.js") + 1 == scripts.index("js/views/lab_photo.js")
    assert scripts.index("js/views/lab_photo.js") < scripts.index("js/views/ai.js") < scripts.index("js/main.js")
    assert "'/js/views/lab_photo.js'," in SW


def test_no_inline_script_handler_style_or_html_string():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\(|new Function", PHOTO_JS, re.IGNORECASE)
    assert not re.search(r"""\s(on[a-z]+|style)\s*:|['"]\s*(on[a-z]+|style)\s*['"]\s*:""", PHOTO_JS, re.IGNORECASE)
    assert not re.search(r"<\s*(script|img|iframe|style|a|b|i|u)\b", PHOTO_JS, re.IGNORECASE)
    section = INDEX[INDEX.index('id="lab-photo"'):INDEX.index("</section>", INDEX.index('id="lab-photo"'))]
    assert not re.search(r"\s(on[a-z]+|style)\s*=", section, re.IGNORECASE)


def test_it_reaches_the_server_only_through_the_apps_own_ai_client_and_the_shared_save():
    assert "fetch(" not in PHOTO_JS and "XMLHttpRequest" not in PHOTO_JS and "request(" not in PHOTO_JS
    assert not re.search(r"https?://", PHOTO_JS)
    assert "localStorage" not in PHOTO_JS and "sessionStorage" not in PHOTO_JS and "indexedDB" not in PHOTO_JS  # the photo is never stored
    assert "KH.ai.uploadPhoto('lab-report'" in PHOTO_JS and "KH.ai.withConsent('labs'" in PHOTO_JS and "KH.ai.prepareJpeg(" in PHOTO_JS
    assert "KH.views.labs.saveImported(" in PHOTO_JS and "importLabs" not in PHOTO_JS  # saving is the CSV import's own save
    # the shared save is the CSV import's, unchanged in what it sends: only the ticked results, through POST /api/labs/import
    assert "api.importLabs(LI.requestBody(kept))" in LABS_JS and "async function saveImported(kept, box, source, onSaved = null)" in LABS_JS
    assert "saveImported(kept, importBox, 'your file'" in LABS_JS
    assert "KH.views.labs = { refresh, renderReview, parseValue, saveImported, fmtDay };" in LABS_JS
    assert "if (KH.labPhoto) KH.labPhoto.show();" in LABS_JS


def test_the_card_is_hidden_until_the_server_says_the_local_ai_can_read_a_report():
    card = INDEX[INDEX.index('<section class="card" id="lab-photo"'):]
    card = card[:card.index("</section>")]
    assert re.search(r'<section class="card" id="lab-photo"[^>]* hidden>', card)
    assert re.search(r'<div id="lab-photo-controls" hidden>', card) and 'id="lab-photo-why" class="muted small" hidden' in card
    assert 'id="lab-photo-file"' in card and 'accept="image/*"' in card
    assert "Read a lab report photo" in card and "crop the photo to the results table" in card.lower()
    assert "features.lab_report" in PHOTO_JS and "st.features.lab_report" in PHOTO_JS
    assert "section.hidden = true; return; }" in PHOTO_JS  # AI off on the server (and the demo): nothing is offered


def test_the_demo_never_offers_it():
    assert "r'^\\/api\\/(?:ai|vision)\\/'" not in MOCK_AI  # (a JS regex literal, checked below)
    pattern = re.search(r"route\('\*', (/.+?/), function", MOCK_AI).group(1)
    assert re.match(pattern[1:-1].replace("\\/", "/"), "/api/ai/read-lab-report")  # answered 404, like every other AI route there
    assert "if (MOCK) return { enabled: false, demo: true };" in AI_JS or "if (MOCK) return { enabled: false, demo: true }" in AI_JS
    assert "Photos are read by AI only in the installed app." in AI_JS


def test_the_consent_sheet_uses_the_servers_own_words_for_a_lab_report():
    assert "consent.purpose === 'labs' && Array.isArray(consent.notice)" in AI_JS
    assert "const FEATURE_OF = { text: 'meal_ideas', photos: 'photos', chat: 'chat', labs: 'labs' };" in AI_JS
    assert "kind === 'lab-report' ? '/api/ai/read-lab-report'" in AI_JS
    assert "labs: 'Lab report photos'" in AI_JS and "read_lab_report: 'Read a lab report'" in AI_JS
    # the generic "Never sent: your name ..." line is not shown for a report (it would be untrue of a photo)
    assert "notice ? null : h('p', { class: 'hint' }, NEVER_SENT_TEXT" in AI_JS


def test_the_admin_table_offers_a_local_only_feature_two_choices():
    assert "f.allowed && !f.allowed.includes(c)" in ROUTING_JS and "Local or off, never sent to a cloud AI" in ROUTING_JS
    assert ".ai-route-na" in AI_CSS and ".ai-consent-notice" in AI_CSS


def test_the_classes_the_file_uses_are_styled():
    css = LABS_CSS + (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    used = {token for group in re.findall(r"class: '([^']+)'", PHOTO_JS) for token in group.split()}
    assert {"lab-photo-list", "lab-photo-date", "lab-import-list", "lab-import-saved", "lab-row", "lab-row-date"} <= used
    for cls in ("lab-photo-list", "lab-photo-date", "lab-import-list", "lab-import-saved"):
        assert f".{cls}" in css, cls  # the CSV import's table classes are reused; the two new ones are in labs.css


@pytest.fixture(scope="module")
def page():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "lab_photo_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_every_row_starts_unticked_with_the_notice_and_a_missing_date_must_be_entered(page):
    start = page["start"]
    assert start["ticked"] == [False, False, False]  # nothing is ticked for the person
    assert start["notice"] is True and start["dropped"] is True
    assert "None is ticked" in start["summary"] and "Nothing is saved until you press Save" in start["summary"]
    assert start["save"] == {"text": "Save 0 results", "disabled": True}
    assert start["disabled"] == [False, False, True]  # the row without a date cannot be ticked yet
    assert start["dateNeeded"][2] == "Date needed"
    assert start["dateField"] == [{"id": "lab-photo-row-2-date", "max": "2026-10-16", "min": "1900-01-01"}]
    assert start["dateNote"] == ("Printed on the report as 03/04/2026. The date on the report could mean two different days. "
                                 "Enter the date of the test.")
    assert start["classes"] == ["list labs-list lab-import-list lab-photo-list"]  # the CSV import's table, with one more class


def test_a_date_the_person_enters_unlocks_the_row_and_a_bad_one_does_not(page):
    assert page["twoTicked"] == {"save": "Save 2 results", "disabled": False}
    for bad in ("", "2099-01-01", "1899-12-31", "x"):
        assert page[f"badDate:{bad}"] == {"disabled": True, "ticked": False}, bad
    assert page["goodDate"] == {"disabled": False, "when": "day 2026-04-03"}
    assert page["threeTicked"] == {"save": "Save 3 results", "disabled": False}
    assert page["clearedDate"] == {"withDate": "Save 1 result", "afterClear": "Save 0 results", "ticked": False, "disabled": True, "saveDisabled": True}
    assert page["clearedDateSends"] == 0  # a row whose date was taken away again is never sent


def test_only_the_ticked_rows_are_handed_to_the_save_with_the_date_the_person_entered(page):
    assert page["saveSends"] == [
        {"analyte": "potassium", "value": 5.4, "unit": "mmol/L", "taken_on": "2026-10-07", "label": "Potassium", "text": "5.4 mmol/L"},
        {"analyte": "creatinine", "value": 88, "unit": "µmol/L", "taken_on": "2026-04-03", "label": "Creatinine (blood)", "text": "88 µmol/L = 1.00 mg/dL"},
    ]  # the phosphate was left unticked, so it is not here
    assert page["discarded"] is True


def test_already_saved_results_are_marked_but_still_unticked(page):
    assert page["alreadySaved"] == {"tag": "already saved", "ticked": [False]}


def test_text_from_the_server_is_drawn_as_text(page):
    assert page["hostile"]["noRealElements"] is True and page["hostile"]["hasText"] is True
    assert set(page["hostile"]["tags"]) <= {"button", "div", "input", "label", "li", "p", "span", "strong", "ul"}


def test_messages_instead_of_a_table(page):
    assert page["notAReport"] == "This does not look like a lab report."
    assert page["noResults"].startswith("No result the app knows was found in this photo.") and "3 lines were not recognised" in page["noResults"]


def test_the_card_is_offered_only_when_the_server_says_so_and_says_why_when_it_is_not(page):
    assert page["offered"] == {"section": False, "controls": False, "why": True, "whyText": ""}
    assert page["aiOff"]["section"] is True  # AI is off on this server (or this is the demo): the card is not there at all
    assert page["noLocalAi"] == {"section": False, "controls": True, "why": False,
                                 "whyText": "Needs a local AI on your own network, which is not set up on this server, so it is off."}
    assert "Turn on AI ideas in Settings" in page["notOptedIn"]["whyText"] and page["notOptedIn"]["controls"] is True
    assert "cannot read photos yet" in page["noVisionModel"]["whyText"]
    assert page["switchedOff"]["whyText"] == "Switched off by your admin." and page["switchedOff"]["controls"] is True
    assert page["offeredAgain"]["controls"] is False and page["offeredAgain"]["section"] is False


def test_the_flow_reads_with_the_labs_consent_and_saves_only_what_was_ticked(page):
    flow = page["flow"]
    assert flow["consent"] == [["labs", "labs"]]  # its own consent purpose, resolved against the labs route
    assert flow["uploads"][0] == ["lab-report", "jpeg:report.png", False]  # the redrawn JPEG, to the lab report route
    assert flow["ticked"] == [False, False] and flow["readText"] == "Read the report"
    saved = page["flowSaved"]
    assert saved["saved"] == [{"kept": [{"analyte": "phosphate", "value": 1.2, "unit": "mmol/L", "taken_on": "2026-10-07",
                                         "label": "Phosphate", "text": "1.2 mmol/L = 3.7 mg/dL"}], "source": "your photo"}]
    assert saved["input"] == "" and saved["results"] == "Saved 1"  # the photo is forgotten once saved
    assert page["what"]["uploads"] == ["lab-report", "jpeg:again.png", True] and page["what"]["shown"] == [{"dry_run": True}]
    assert page["noPhoto"] == "Choose a photo or screenshot of the report first."


def test_the_admin_table_has_two_choices_for_lab_reports():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "routing_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["labs"]["radios"] == ["Lab report photos: Local", "Lab report photos: Off"]
    assert out["labs"]["notOffered"] == ["– Lab report photos: Cloud is not offered"] and out["labs"]["cells"] == 3
    assert "Local or off, never sent to a cloud AI" in out["labs"]["hint"] and out["labs"]["intro"] is True
    assert out["labsSaved"] == {"labs": "off"}
