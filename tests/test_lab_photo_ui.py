"""The browser side of "Read a lab report photo or PDF" (``app/static/js/views/lab_photo.js``, its card in ``index.html``, the shared save
in ``labs.js``, the hooks in ``ai.js`` and ``ai_routing.js``, ``css/labs.css``): the file is in the shell and the service worker,
nothing in it is an inline script, handler, style or HTML string, it reaches the server only through the app's own AI client, the
demo never offers it, and its behaviour (offered only when the server says so and why not, every row unticked, a row without a
date cannot be ticked, only ticked rows are saved through the CSV import's own save) is checked by running the file against a
fake page in Node (``tests/js/lab_photo_page.mjs``).

A PDF (design note 13 §4.3, §5) is checked the same way, with a stand-in for ``KH.pdfPages`` (``tests/test_pdf_pages.py`` runs the real
module): the page list with pages 1-6 ticked and at most 10, one request per ticked page with that page's own picture and never the PDF,
progress and Cancel, one review table with the page of each row and repeated rows shown once, a failed page that leaves the others, the
messages, and everything let go on discard, save and a new pick."""
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
    assert scripts.index("js/engine/pdf_pages.js") < scripts.index("js/views/lab_photo.js")  # KH.pdfPages is there when the view loads
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
    assert 'id="lab-photo-file"' in card and 'accept="image/*,application/pdf,.pdf"' in card
    assert "Read a lab report photo or PDF" in card and "crop the photo to the results table" in card.lower()
    assert "choose the PDF from your lab's website" in card  # the card says a PDF works too
    assert "A PDF stays on this device" in card and "only those pages are drawn here and sent as pictures" in card
    # the page list is built by the view into this container, with its own progress line and Cancel button (hidden until a PDF is read)
    assert re.search(r'<div id="lab-photo-pages" class="lab-photo-pages" hidden></div>', card)
    assert re.search(r'<button class="btn secondary" type="button" id="lab-photo-cancel" hidden>Cancel</button>', card)
    assert re.search(r'<p id="lab-photo-progress" class="hint" role="status" aria-live="polite" hidden></p>', card)
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
    assert "Turn on AI features in Settings" in page["notOptedIn"]["whyText"] and page["notOptedIn"]["controls"] is True
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
    assert page["noPhoto"] == "Choose a photo, a screenshot or a PDF of the report first."


def test_the_admin_table_has_two_choices_for_lab_reports():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "routing_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["labs"]["radios"] == ["Lab report photos: Local", "Lab report photos: Off"]
    assert out["labs"]["notOffered"] == ["– Lab report photos: Cloud is not offered"] and out["labs"]["cells"] == 3
    assert "Local or off, never sent to a cloud AI" in out["labs"]["hint"] and out["labs"]["intro"] is True
    assert out["labsSaved"] == {"labs": "off"}


# --------------------------------------------------------------------------- a PDF (design note 13)
CODE = re.sub(r"/\*.*?\*/", "", PHOTO_JS, flags=re.S)


def test_the_pdf_itself_is_never_sent_anywhere_and_nothing_is_stored():
    # `pdf.file` is the File the person chose. It goes to KH.pdfPages.open (this device) and nowhere else: not to upload, not to fetch.
    uses = [line.strip() for line in CODE.splitlines() if "pdf.file" in line]
    allowed = ("pdf.file = file;", "pdf.file = null;", "if (pdf.file) {", "if (pdf.file) { await previewPdf(); return; }", "const doc = await KH.pdfPages.open(pdf.file, { signal });")
    assert all(line.startswith(allowed) or line in allowed for line in uses), uses
    assert "KH.pdfPages.open(file, { signal: control.signal })" in CODE and "KH.pdfPages.open(pdf.file, { signal })" in CODE
    assert not re.search(r"upload\([^)]*\b(file|pdf)\b", CODE)  # a request gets a picture (the redrawn page), never the file
    assert not re.search(r"FileReader|createObjectURL|arrayBuffer|\.text\(\)|localStorage|sessionStorage|indexedDB|caches\.|navigator\.sendBeacon", CODE)
    assert "KH.ai.prepareJpeg(drawn)" in CODE and "KH.ai.prepareJpeg(await doc.render(" in CODE  # every page goes through the photo helper, no second one
    assert CODE.count("prepareJpeg") == 3  # the photo, a drawn page, the page "What will be sent?" shows


def test_each_ticked_page_is_its_own_request_through_the_same_consent_and_the_photo_route():
    assert "KH.ai.withConsent('labs', () => sendPage(picture, signal), () => upload(picture, true, signal), btn, 'labs')" in CODE
    assert "const upload = (blob, dry, signal) => KH.ai.uploadPhoto('lab-report', blob, dry, signal);" in CODE
    assert "for (let i = 0; i < pages.length; i += 1)" in CODE and "doc.render(n, { signal })" in CODE  # one at a time, in page order
    assert "say(`Reading page ${i + 1} of ${pages.length}…" in CODE
    assert "const DEFAULT_TICKED = 6;" in CODE and "const MAX_TICKED = 10;" in CODE
    # the abort reaches fetch: the AI client takes the signal and hands it on, and an abort is not turned into a message
    assert "async function uploadPhoto(kind, blob, dry, signal)" in AI_JS and "...(signal ? { signal } : {})," in AI_JS
    assert "if (e && e.name === 'AbortError') throw e;" in AI_JS


def test_the_messages_are_the_ones_in_the_design_note_and_are_drawn_as_text():
    for sentence in ("That file is not a PDF.",
                     "This PDF has a password. Open it on your device and take a screenshot of each page instead.",
                     "This PDF could not be read. Download it again, or take a screenshot of each page.",
                     "This PDF has more than 50 pages. Take screenshots of the pages with your results.",
                     "This browser cannot read a PDF here. Take a screenshot of each page instead.",
                     "Reading a page takes a while on your own AI; choose the pages with results.",
                     "Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not sent."):
        assert sentence in CODE, sentence
    assert "`That PDF is ${" in CODE and "MB; the largest this app reads is 20 MB.`" in CODE
    assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.(write|createElement)", CODE)  # the page list is built with h()


def test_the_page_list_styles_exist_and_the_two_new_classes_are_used():
    css = LABS_CSS
    used = {token for group in re.findall(r"class: '([^']+)'", PHOTO_JS) for token in group.split()}
    assert {"lab-photo-pages", "lab-photo-page-list", "lab-photo-page", "lab-photo-fieldset", "lab-row-page"} <= used | {"lab-photo-pages"}
    for cls in ("lab-photo-pages", "lab-photo-fieldset", "lab-photo-page-list", "lab-photo-page", "lab-row-page"):
        assert f".{cls}" in css, cls
    assert "lab-photo-pages" in INDEX


def pdf(page):
    return page["pdf"]


def test_a_pdf_pick_opens_it_here_and_lists_its_pages_with_the_first_six_ticked(page):
    pick = pdf(page)["pick"]
    assert pick["opened"] == [{"name": "results.pdf", "signal": True}]  # opened on this device, once, stoppable
    assert pick["legend"] == "Pages to read (this PDF has 8 pages)" and pick["labels"] == [f"Page {n}" for n in range(1, 9)]
    assert pick["ticks"] == "11111100" and pick["disabled"] == "00000000"
    assert pick["hints"] == ["Reading a page takes a while on your own AI; choose the pages with results.", "6 pages are ticked.",
                             "Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not sent."]
    assert pick["uploads"] == 0 and pick["consent"] == 0  # choosing a file sends nothing and asks nothing
    assert pick["state"]["list"] == "shown" and pick["said"] == ["Opening the PDF…"] and pick["progress"] is True and pick["error"] == ""


def test_at_most_ten_pages_can_be_ticked_and_a_short_pdf_ticks_what_it_has(page):
    ticks = pdf(page)["ticks"]
    assert ticks["first"] == "111111000000"
    assert ticks["full"] == {"ticks": "111111111100", "disabled": "000000000011",
                             "count": "10 pages are ticked, the most at a time. Untick one to choose another."}
    assert ticks["freed"] == {"ticks": "011111111100", "disabled": "000000000000", "count": "9 pages are ticked."}
    assert ticks["closedFirst"] == 1  # picking the 12-page file closed the first one
    assert pdf(page)["onePage"] == {"ticks": "1", "count": "1 page is ticked."}


def test_each_ticked_page_is_one_request_with_its_own_picture_and_the_rows_are_one_table_with_page_numbers(page):
    read = pdf(page)["read"]
    assert read["renders"] == [1, 2, 3, 4]
    assert read["uploads"] == [[f"jpeg:page-{n}.jpg", False] for n in (1, 2, 3, 4)]  # the drawn, redrawn page; never the PDF
    assert read["pdfAsPicture"] is False and read["signals"] == [True] * 4  # every request can be stopped
    assert read["consent"] == [["labs", "labs"]] * 4  # the photo's consent, asked again for each page (it answers at once once given)
    assert read["said"] == [f"Reading page {n} of 4…" for n in (1, 2, 3, 4)]
    assert read["notice"] == ("Read by AI from the pages of your PDF that you ticked. Check each value against the report before you tick it.")
    assert read["summary"].startswith("3 results read from your PDF. None is ticked")
    assert read["ticked"] == [False, False, False]
    assert read["rows"] == ["day 2026-10-07 Potassium 5.4 mmol/L page 1 of your PDF", "day 2026-10-07 Phosphate 1.2 mmol/L page 1 of your PDF",
                            "day 2026-10-07 Albumin 38 g/L page 2 of your PDF"]  # the potassium line of page 2 repeated page 1's: shown once, page 1
    assert read["focused"] == "lab-photo-row-0"


def test_a_failed_page_a_page_with_no_result_and_a_repeat_are_said_in_lines_and_the_others_still_count(page):
    read = pdf(page)["read"]
    assert read["lines"] == [
        "Page 1: 2 lines were not recognised: it is not one of the tests this app keeps.",
        "Page 2: 2 lines were not recognised: it is not one of the tests this app keeps.",
        "Page 3 could not be read: The photo is too wide for its height.",
        "Page 4: No result the app knows was found in this photo.",
        "1 result was the same as one already shown, so it is shown once.",
    ]
    assert read["warned"] == ["Page 3 could not be read: The photo is too wide for its height."]
    undrawable = pdf(page)["undrawable"]
    assert undrawable["renders"] == [1, 2, 3] and undrawable["uploads"] == ["jpeg:page-1.jpg", "jpeg:page-3.jpg"]  # page 2 could not be drawn: not sent
    assert "Page 2 could not be read: it could not be drawn from the PDF." in undrawable["lines"] and len(undrawable["rows"]) == 2
    bad = pdf(page)["badAnswer"]
    assert bad["uploads"] == ["jpeg:page-1.jpg", "jpeg:page-2.jpg", "jpeg:page-3.jpg"] and bad["rows"] == 2
    assert "Page 2 could not be read: The AI gave an answer that failed its checks." in bad["lines"]
    assert pdf(page)["nothing"] == ("No result could be read from the pages you ticked. Page 1: This does not look like a lab report. "
                                    "Page 2: The photo could not be read.")


def test_a_refusal_that_would_repeat_stops_the_run_and_says_so(page):
    limit = pdf(page)["limit"]
    assert limit["uploads"] == ["jpeg:page-1.jpg"]  # the daily limit: pages 2 and 3 were not tried
    assert limit["text"] == ("No result could be read from the pages you ticked. Page 1 could not be read: Daily limit reached. "
                             "Reading stopped here; the pages after it were not sent.")
    assert limit["closes"] == 1


def test_the_reading_ends_with_the_pdf_closed_the_button_back_and_the_list_still_there(page):
    read = pdf(page)["read"]
    assert read["state"]["closes"] == 1 and read["reopened"] == 0 and read["state"]["list"] == "shown"  # pdf.js and its worker are let go
    assert read["cancelHidden"] is True and read["readText"] == "Read the report" and read["readDisabled"] is False
    assert read["busy"] is None and read["progressHidden"] is True
    assert read["ticksAfter"] == "1111" and read["disabledAfter"] == "0000"  # the person can tick other pages and read again
    again = pdf(page)["again"]
    assert again["once"] == {"opened": 1, "closes": 1, "file": ""} and again["twice"] == {"opened": 2, "closes": 2}  # the chosen file is opened again
    assert again["renders"] == [1, 2, 1, 2]


def test_save_sends_only_the_ticked_rows_from_your_pdf_and_lets_everything_go(page):
    saved = pdf(page)["saved"]
    assert saved["saved"] == [{"kept": [
        {"analyte": "potassium", "value": 5.4, "unit": "mmol/L", "taken_on": "2026-10-07", "label": "Potassium", "text": "5.4 mmol/L"},
        {"analyte": "albumin", "value": 38, "unit": "g/L", "taken_on": "2026-10-07", "label": "Albumin", "text": "38 g/L"}], "source": "your PDF"}]
    assert "page" not in saved["saved"][0]["kept"][0]  # the page number is for the person; the server is sent the result only
    assert saved["state"] == {"pickCount": 1, "opened": 1, "closes": 1, "list": "hidden", "boxes": 0, "input": ""}
    assert saved["results"] == "Saved 2" and saved["progress"] is True


def test_cancel_stops_the_request_in_flight_keeps_what_was_read_and_closes_the_pdf(page):
    cancel = pdf(page)["cancel"]
    assert cancel["during"] == {"cancelHidden": False, "readText": "Reading…", "readDisabled": True, "progress": "Reading page 2 of 3…",
                                "boxes": "111", "busy": "true"}  # Cancel shows, the page boxes are locked while it reads
    assert cancel["uploads"] == ["jpeg:page-1.jpg", "jpeg:page-2.jpg"] and cancel["renders"] == [1, 2]  # page 3 was never drawn
    assert cancel["lines"][0] == "Stopped. These results are from 1 page read before you pressed Cancel."
    assert cancel["rows"] == ["day 2026-10-07 Potassium 5.4 mmol/L page 1 of your PDF"]
    assert cancel["cancelHidden"] is True and cancel["readText"] == "Read the report" and cancel["closes"] == 1 and cancel["progressHidden"] is True
    assert cancel["listStill"] == "shown"


def test_declining_the_consent_sends_nothing_and_leaves_the_pdf_chosen(page):
    declined = pdf(page)["declined"]
    assert declined["uploads"] == 0 and declined["text"] == "Nothing was sent." and declined["closes"] == 1 and declined["list"] == "shown"
    assert declined["readText"] == "Read the report" and declined["readDisabled"] is False
    after = pdf(page)["afterDecline"]
    assert after["uploads"] == 2 and after["rows"] == 1 and after["reopened"] == 2  # reading again opens the same file again


def test_the_first_pages_consent_sheet_says_each_page_is_sent_as_a_picture(page):
    notice = pdf(page)["consentNotice"]
    assert notice["notices"] == [["Your photo goes to ollama.lan.", "Crop it.",
                                  "Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not sent."]]
    assert notice["uploads"] == [["jpeg:page-1.jpg", False], ["jpeg:page-1.jpg", False], ["jpeg:page-2.jpg", False]]  # 409, then agreed, then page 2


def test_the_messages_for_a_file_that_cannot_be_used_and_the_choice_is_forgotten(page):
    messages = pdf(page)["messages"]
    assert messages["too_big"]["error"] == "That PDF is 25.0 MB; the largest this app reads is 20 MB."
    assert messages["too_big_small"]["error"] == "That PDF is 20.1 MB; the largest this app reads is 20 MB."
    assert messages["not_pdf"]["error"] == "That file is not a PDF."
    assert messages["password"]["error"] == "This PDF has a password. Open it on your device and take a screenshot of each page instead."
    assert messages["damaged"]["error"] == "This PDF could not be read. Download it again, or take a screenshot of each page."
    assert messages["unknown"]["error"] == messages["damaged"]["error"]  # an error that is none of the codes is "could not be read"
    assert messages["too_many_pages"]["error"] == "This PDF has more than 50 pages. Take screenshots of the pages with your results."
    assert messages["browser"]["error"] == "This browser cannot read a PDF here. Take a screenshot of each page instead."
    for name, shown in messages.items():
        assert shown["state"]["list"] == "hidden" and shown["state"]["boxes"] == 0 and shown["state"]["input"] == "" and shown["uploads"] == 0, name
    assert pdf(page)["unsupported"] == {"error": "This browser cannot read a PDF here. Take a screenshot of each page instead.", "opens": 0, "input": ""}


def test_reading_with_no_page_ticked_says_so_and_sends_nothing(page):
    none = pdf(page)["noneTicked"]
    assert none == {"error": "Tick at least one page to read.", "uploads": 0, "renders": 0, "count": "No page is ticked."}


def test_a_new_pick_discard_and_a_photo_after_a_pdf_let_the_pdf_go(page):
    assert pdf(page)["secondPick"] == {"opened": 2, "closes": 1, "boxes": 5, "ticks": "11111"}  # the first PDF was closed when the second was chosen
    assert pdf(page)["photoAfter"] == {"closes": 2, "list": "hidden", "boxes": 0}  # and the second when a photo was chosen
    photo = pdf(page)["photoRead"]
    assert photo["uploads"] == [["jpeg:screenshot.png", False]] and photo["pageTags"] == 0  # a photo is a photo: no page numbers
    assert photo["summary"].startswith("2 results read from your photo.")
    discard = pdf(page)["discard"]
    assert discard["closes"] == 1 and discard["state"]["list"] == "hidden" and discard["state"]["input"] == "" and discard["results"] == ""


def test_what_will_be_sent_for_a_pdf_draws_the_first_ticked_page_and_shows_the_dry_run(page):
    what = pdf(page)["what"]
    assert what["renders"] == [2] and what["uploads"] == [["jpeg:page-2.jpg", True]] and what["shown"] == [{"dry_run": True}]
    assert what["closes"] == 1 and what["signals"] == [True]


def test_pages_that_are_not_the_first_say_which_page_of_the_pdf_they_are(page):
    gaps = pdf(page)["gaps"]
    assert gaps["said"] == ["Reading page 1 of 2… (page 2 of your PDF)", "Reading page 2 of 2… (page 4 of your PDF)"]
    assert gaps["renders"] == [2, 4] and gaps["pages"] == ["page 2 of your PDF", "page 4 of your PDF"]


def test_the_merge_keeps_the_first_page_of_a_repeated_row_and_collapses_rows_without_a_date_too(page):
    merge = pdf(page)["merge"]
    assert merge["rows"] == [["potassium", 5.4, "2026-10-07", 1], ["potassium", 5.4, None, 1], ["potassium", 5.5, "2026-10-07", 2]]
    assert merge["duplicates"] == 2
    exported = pdf(page)["exported"]
    assert exported["max"] == 10 and exported["def"] == 6 and "mergePages" in exported["messages"] and "pdfMessage" in exported["messages"]
