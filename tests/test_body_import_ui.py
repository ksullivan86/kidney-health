"""The browser side of "Weights and blood pressure from the Health app" (note 10 section 4.8, Part C): the sheet ``<dialog id="sheet-body-import">``
in ``index.html``, its view ``app/static/js/views/body_import.js`` (``KH.bodyImport.open()``) and what it needs from the reader
``js/engine/apple_health.js`` and the batch routes of ``app/body.py``.

The export.zip is chosen as it is (``js/engine/zip.js``, note 11: only its export.xml is read, as a stream, by the same scan), or the export.xml inside it.
The file is read on the device and nothing is uploaded while it is read or reviewed; Import sends only the rows the person keeps, in batches of 1,000,
without the source name, with ``source`` ``apple_health``. Nothing in the view is an inline script, handler, style or HTML string, it makes no network
call of its own (only ``KH.api``), it keeps nothing in the browser's storage, and what it does is checked by running it against a fake page, a fake
backend that keeps the server's batch rules and fake files in Node (``tests/js/body_import_page.mjs``): the steps and the files it refuses, the review
(found, kept and left out in words, the date range, the last 3 months by default, the watch readings listed apart and unticked), what goes up, a day
with more weights or readings than a day can hold (the first rows of the day in time order, against the rows the person already has), a refusal in
the middle (the server's words and how many were already added), Cancel and Stop, and text from the file drawn as text.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from app import models
from app.log import MAX_RANGE_DAYS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = (STATIC / "js" / "views" / "body_import.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "apple_health.js").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
MOCK = (STATIC / "js" / "mock" / "body.js").read_text(encoding="utf-8")
CSS = "".join((STATIC / "css" / name).read_text(encoding="utf-8") for name in ("base.css", "sheets.css", "profile.css", "labs.css"))
SHEET = INDEX[INDEX.index('<dialog id="sheet-body-import"'):]
SHEET = SHEET[:SHEET.index("</dialog>")]


def code_of(js: str) -> str:
    """The script without its comments (and the text of its quoted strings left alone), for checks on what it can DO."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(^|[^:'\"`])//[^\n]*", r"\1", js)


# --------------------------------------------------------------------------- the files and the sheet


def test_the_files_are_in_the_shell_in_dependency_order_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    # the reader needs rules.js (halfUp) and comes right after it; the view needs core.js, the demo API and the engine twins before it
    assert scripts.index("js/engine/rules.js") + 1 == scripts.index("js/engine/apple_health.js") < scripts.index("js/engine/body.js") < scripts.index("js/core.js")
    assert scripts.index("js/core.js") < scripts.index("js/mock/body.js") < scripts.index("js/views/body_import.js") < scripts.index("js/main.js")
    assert "'/js/engine/apple_health.js'," in SW and "'/js/views/body_import.js'," in SW
    assert "KH.bodyImport = { open, trimDays };" in VIEW and "KH.appleHealth = {" in ENGINE
    assert "const KH = window.KH;" in VIEW and "KH.appleHealth" in VIEW and "KH.bodyRules.LIMITS" in VIEW


def test_the_sheet_explains_the_steps_and_takes_one_zip_or_xml_file():
    assert SHEET.startswith('<dialog id="sheet-body-import" class="sheet" aria-labelledby="sheet-body-import-title" aria-describedby="sheet-body-import-sub">')
    steps = re.search(r'<ol class="small lab-fhir-steps" id="body-import-steps">(.*?)</ol>', SHEET, re.S)
    assert steps
    plain = re.sub(r"<[^>]+>", "", steps.group(1))
    # Health app -> your picture -> Export All Health Data -> choose export.zip (or, if it was already unzipped in Files, apple_health_export/export.xml)
    for words in ("In the Health app, tap your picture", "Export All Health Data", "Files", "choose export.zip below", "already unzipped it in Files",
                  "choose apple_health_export/export.xml instead"):
        assert words in plain, words
    assert "tap export.zip to unzip it" not in plain  # nobody has to unzip it first any more
    order = [plain.index(w) for w in ("Export All Health Data", "choose export.zip below", "apple_health_export/export.xml")]
    assert order == sorted(order)  # the steps are in the order a person does them
    assert "Only weights and blood pressure readings are read" in SHEET and "not heart rate, steps, blood glucose or insulin" in SHEET
    assert re.search(r'<input id="body-import-file" class="ai-file" type="file" accept="\.zip,\.xml,application/zip,text/xml,application/xml"', SHEET)
    assert '<label for="body-import-file">export.zip (or export.xml)</label>' in SHEET
    assert "multiple" not in SHEET and "capture=" not in SHEET and "<form" not in SHEET and "action=" not in SHEET  # the chooser hands one file to the page
    for needed in ('id="body-import-problem" role="alert"', 'id="body-import-status" role="status"', 'id="body-import-review"', 'id="body-import-cancel"',
                   'id="body-import-go"', 'id="body-import-pick"', "data-close"):
        assert needed in SHEET, needed
    assert "Nothing is uploaded until you press Import" in SHEET


def test_no_inline_script_handler_style_or_html_string():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    assert not re.search(r"\s(on[a-z]+|style)\s*=", SHEET, re.IGNORECASE)
    assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\(|new Function|\bFunction\(|parseFromString|DOMParser|createPolicy|srcdoc", VIEW)
    assert "innerHTML" not in VIEW and "outerHTML" not in VIEW
    code = code_of(VIEW)
    assert not re.search(r"""[{,]\s*(on(click|change|input|submit|load|error|keydown|keyup|focus|blur)|style)\s*:|['"]\s*(on[a-z]+|style)\s*['"]\s*:""", code, re.IGNORECASE)  # no handler or style as an h() attribute
    assert not re.search(r"<\s*(script|img|iframe|style|a|b|i|u)\b", code, re.IGNORECASE)  # no markup in a string
    assert "h('" in VIEW  # every node is built with the h() helper, which sets text nodes


def test_the_view_calls_no_network_of_its_own_and_keeps_nothing_in_the_browser():
    code = code_of(VIEW)
    assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|\bimport\s*\(|navigator\.|FormData|createObjectURL|FileReader", code)
    assert not re.search(r"localStorage|sessionStorage|indexedDB|caches\.|document\.cookie", code)
    assert not re.search(r"https?://", code)
    # the only calls out of the page are the app's own API: the two list routes (what a day already holds) and the two batch routes
    assert sorted(set(re.findall(r"\bapi\.(\w+)", code))) == ["bloodPressures", "bodyWeights", "importBloodPressures", "importWeights"]
    for name in ("bodyWeights", "importWeights", "bloodPressures", "importBloodPressures"):
        assert f"{name}:" in CORE
    assert "/api/body/weights/batch" in CORE and "/api/body/blood-pressure/batch" in CORE
    # the file is read as a stream of text by the reader, never as a whole and never parsed
    assert "bytes = file.stream();" in VIEW and "bytes.pipeThrough(new TextDecoderStream())" in VIEW and "file.text()" not in VIEW and "arrayBuffer" not in VIEW
    # and so is the export.xml of a .zip: opened by KH.zip, then streamed (never given to text()), with the scan's own AbortController
    assert "bytes = KH.zip.stream(archive, entry, { signal: ctrl.signal });" in VIEW and "KH.zip.text(" not in VIEW
    assert "AH.scan(" in VIEW and "signal: ctrl.signal" in VIEW and "today: todayStr()" in VIEW and "onProgress" in VIEW


def test_what_goes_up_is_the_readers_rows_without_a_source_name_with_the_source_the_batch_model_expects():
    assert "AH.forUpload(rows).map((r) => ({ ...r, source: SOURCE }))" in VIEW and "const SOURCE = 'apple_health';" in VIEW
    assert "apple_health" in models.BodyImportSource.__args__ and "manual" not in models.BodyImportSource.__args__
    # the demo's batch routes take it too
    assert "c.choice('source', ['apple_health', 'import'], { def: 'import' });" in MOCK
    assert "AH.batches(upload)" in VIEW and "const BATCH_SIZE = 1000;" in ENGINE and models.MAX_BODY_BATCH == 1000
    assert "sourceName" not in code_of(VIEW).replace("r.sourceName", "").replace("sourceNames", "")  # a name is only read to tell a watch, count and show


def test_the_limits_the_view_trims_to_and_the_windows_it_asks_for_are_the_servers():
    assert "limit: LIMIT.max_weights_per_day" in VIEW and "limit: LIMIT.max_readings_per_day" in VIEW
    assert models.MAX_WEIGHTS_PER_DAY == 20 and models.MAX_READINGS_PER_DAY == 30
    assert re.search(rf"max_weights_per_day: {models.MAX_WEIGHTS_PER_DAY}, max_readings_per_day: {models.MAX_READINGS_PER_DAY}", (STATIC / "js" / "engine" / "body.js").read_text(encoding="utf-8"))
    assert f"const WINDOW_DAYS = {MAX_RANGE_DAYS};" in VIEW  # the list routes take at most 366 days
    # a window ends WINDOW_DAYS - 1 days after it starts, which the list route accepts: end - start < MAX_RANGE_DAYS
    assert "addDays(start, WINDOW_DAYS - 1)" in VIEW


def test_a_watch_reading_is_unticked_with_the_cuffless_line_and_the_note_names_its_source():
    assert "box1.checked = false;" in VIEW and "imp.ticked.has(r.sourceName)" in VIEW and "AH.isWatchSource" in VIEW
    assert "Cuffless devices such as watches and rings are not recommended for checking blood pressure (2025 AHA/ACC guideline)" in VIEW
    note = (ROOT / "docs" / "dev" / "research" / "10-weight-and-blood-pressure.md").read_text(encoding="utf-8")
    assert "cuffless devices (watches, rings) are not recommended for clinical blood pressure assessment" in note  # F4, the source of that line
    assert "2025 AHA/ACC" in note


def test_the_classes_the_view_uses_are_styled():
    used = {token for group in re.findall(r"class: '([^']+)'", VIEW) for token in group.split()}
    for cls in sorted(used):
        assert re.search(rf"\.{re.escape(cls)}\b", CSS) or cls in ("field", "hint", "form-error", "status-msg"), cls
    assert {"bi-headline", "bi-days", "bi-watch", "choice", "choice-list", "choice-text"} <= used


def test_the_demo_has_the_routes_the_sheet_uses():
    for route in ("route('POST', '/api/body/weights/batch'", "route('POST', '/api/body/blood-pressure/batch'", "route('GET', '/api/body/weights'",
                  "route('GET', '/api/body/blood-pressure'"):
        assert route in MOCK, route


# --------------------------------------------------------------------------- the view run in Node

ZIP_UNREADABLE = ("This .zip could not be read (it may be damaged or not finished downloading). Export from the Health app again, or unzip it in "
                  "Files and choose apple_health_export/export.xml.")
FROM_THE_HEALTH_APP = "Choose the export.zip you get from the Health app (tap your picture, then Export All Health Data)."


@pytest.fixture(scope="module")
def page():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "body_import_page.mjs")], capture_output=True, text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_opening_the_sheet_starts_at_the_file_chooser_and_refuses_a_file_that_only_looks_like_a_zip_the_cda_file_and_an_empty_file(page):
    opened = page["opened"]
    assert opened["open"] is True and opened["focus"][0] == "body-import-file" and opened["cancel"] == "Close"
    assert opened["pickHidden"] is False and opened["reviewHidden"] is True and opened["goHidden"] is True
    assert page["zip"]["problem"] == [ZIP_UNREADABLE]
    assert page["cda"]["problem"] == ["That is the clinical documents file (export_cda.xml). Choose export.xml from the same folder."]
    assert page["empty"]["problem"] == ["That file is empty. Choose export.xml from the unzipped export folder."]
    assert page["zip"]["input"] == page["cda"]["input"] == page["empty"]["input"] == ""  # the choice is dropped, so the same file can be chosen again
    assert page["noWrites"] == {"calls": 0, "lists": 0}


def test_the_review_says_in_words_what_was_found_kept_and_left_out_and_the_date_range(page):
    review = page["review"]
    assert review["headline"] == "Found 6 weights and 6 blood pressure readings. The app can keep 5 weights and 5 readings."
    assert review["range"] == "Dates in the file: Jan 5, 2026 to Oct 20, 2026."
    assert review["leftOut"] == [
        "1 record in a unit the app does not read (weights in kg or lb, blood pressure in mmHg)",
        "1 blood pressure record with only a top number or only a bottom number",
        "1 weight outside what the app accepts (20 to 400 kg)",
        "1 blood pressure reading outside what the app accepts (top number 50 to 300, bottom number 20 to 200, top above bottom)",
    ]
    assert review["sources"] == "From: <img src=x onerror=alert(1)> Scale, Omron Connect, Sam’s Apple Watch, Withings Body+."
    assert review["focused"] == "body-import-summary"  # the headline is read out first
    assert review["calls"] == 0 and review["lists"] == 0 and review["networkTrapped"] == 0  # nothing is sent while the file is read and reviewed


def test_the_period_defaults_to_the_last_three_months_with_the_counts_of_each_period(page):
    periods = page["review"]["periods"]
    assert [p["checked"] for p in periods] == [True, False]
    assert periods[0]["label"] == "The last 3 months Since Jul 22, 2026: 3 weights and 2 readings."  # defaultSince('2026-10-22'); the watch reading is not counted
    assert periods[1]["label"] == "Everything in the file Jan 5, 2026 to Oct 20, 2026: 5 weights and 3 readings."
    assert page["review"]["go"] == {"text": "Import 3 weights and 2 readings", "disabled": False, "hidden": False}
    assert page["review"]["cancel"] == "Cancel"


def test_readings_from_a_watch_are_listed_apart_unticked_and_with_the_cuffless_line(page):
    watch = page["review"]["watch"]
    assert watch["ticked"] == [False]
    assert watch["labels"] == ["Sam’s Apple Watch 1 reading in this period"]
    assert "not recommended for checking blood pressure" in watch["text"] and "These readings are not ticked" in watch["text"]
    choices = page["choices"]
    # ticking it adds its readings to the period counts and to the button; choosing everything adds the older ones; unticking takes them out again
    assert choices["afterTick"]["periods"][0].endswith("3 weights and 3 readings.") and choices["afterTick"]["go"] == "Import 3 weights and 3 readings"
    assert choices["afterAll"] == {"go": "Import 5 weights and 5 readings", "watch": ["Sam’s Apple Watch 2 readings in this period"]}
    assert choices["afterUntick"]["go"] == "Import 5 weights and 3 readings" and choices["backToRecent"] == "Import 3 weights and 2 readings"
    only = page["onlyWatch"]
    assert only["go"]["disabled"] is True and only["watch"]["ticked"] == [False, False]
    assert page["onlyWatchTicked"]["go"] == {"text": "Import 1 reading", "disabled": False, "hidden": False}


def test_source_names_from_the_file_are_drawn_as_text(page):
    review = page["review"]
    assert review["hostileInDom"] == 0 and review["hostileText"] is True and review["noNullText"] is True
    assert set(review["tags"]) <= {"b", "div", "fieldset", "input", "label", "legend", "li", "p", "span", "ul"}
    hostile = page["hostileWatch"]
    assert hostile["labels"] == ["<script>alert(1)</script> Watch 1 reading in this period"] and hostile["scripts"] == 0
    assert set(hostile["tags"]) <= {"b", "div", "fieldset", "input", "label", "legend", "p", "span"}


def test_cancel_at_the_review_forgets_the_file_and_sends_nothing(page):
    cancelled = page["reviewCancelled"]
    assert cancelled["status"] == "Cancelled. Nothing was saved." and cancelled["input"] == "" and cancelled["calls"] == 0
    assert cancelled["pickHidden"] is False and cancelled["reviewHidden"] is True and cancelled["go"]["hidden"] is True and cancelled["focused"] == "body-import-file"
    assert cancelled["headline"] is None and cancelled["watch"] is None  # the review is gone, nothing of it lingers


def test_import_sends_the_kept_rows_without_the_source_name_in_batches_with_source_apple_health(page):
    done = page["imported"]
    assert done["posted"] == [{"kind": "weights", "n": 3}, {"kind": "readings", "n": 2}]  # weights, then readings; only the default period, no watch reading
    assert done["rowKeys"][0] == ["context", "date", "kg", "source", "source_key", "time"]
    assert done["rowKeys"][1] == ["context", "date", "diastolic", "source", "source_key", "systolic", "time"]
    assert done["sources"] == ["apple_health"] and done["keysAreHex"] is True
    for never in ("sourceName", "Withings", "Omron", "Apple Watch", "Scale", "export.xml", "<img"):
        assert never not in done["uploadText"], never
    assert done["weights"] == [["2026-10-01", "21:00", 69.9, "other"], ["2026-10-15", "07:30", 69.99, "morning"], ["2026-10-20", "07:30", 70.2, "morning"]]  # 154.3 lb is 69.99 kg
    assert done["readings"] == [["2026-10-18", "20:15", 131, 84, "evening"], ["2026-10-20", "08:05", 122, 78, "morning"]]
    assert done["result"] == "Added 3 weights and 2 readings." and done["focused"] == "body-import-result"
    assert done["toasts"] == [["Added 3 weights and 2 readings.", "ok"]]
    assert done["snapshot"]["go"]["hidden"] is True and done["snapshot"]["cancel"] == "Close"


def test_a_page_that_showed_trends_loads_it_again_and_the_caches_are_cleared(page):
    done = page["imported"]
    assert done["was"] == [True, True] and done["cleared"] == [None, None, None]
    assert done["shown"] == ["trends"]
    assert done["lists"] == [["weights", "2026-10-01", "2026-10-20"], ["readings", "2026-10-18", "2026-10-20"]]  # what the person already has, for the days of the file


def test_the_same_file_again_adds_nothing_and_says_what_was_already_here(page):
    assert page["again"]["result"] == "Added 0 weights and 0 readings; 5 were already here."
    assert page["again"]["stored"] == [3, 2] and page["again"]["shown"] == []  # nothing changed, so nothing is loaded again
    assert page["everything"]["result"] == "Added 5 weights and 5 readings." and page["everything"]["weights"] == 5


def test_a_day_over_the_limit_keeps_the_first_rows_of_the_day_in_time_order_and_says_how_many_were_left_out(page):
    crowded = page["crowded"]
    assert crowded["review"]["days"] == {"text": "10 or more will be left out: 2 days in the file have more than the app keeps (at most 20 weights and 30 readings a day).", "hidden": False}
    assert crowded["review"]["go"] == "Import 26 weights and 35 readings"
    assert crowded["posted"] == [{"kind": "weights", "n": 21}, {"kind": "readings", "n": 30}]  # no request is refused for a full day
    assert crowded["result"] == "Added 21 weights and 30 readings."
    assert crowded["left"] == "10 more on 2 days were left out (the app keeps at most 20 weights and 30 readings a day)."
    assert crowded["weightsOnDay"] == 20 and crowded["firstTimes"] == ["06:00", "06:19"] and crowded["readingsOnDay"] == 30
    assert crowded["lists"] == [["weights", "2026-10-01", "2026-10-10"], ["readings", "2026-10-12", "2026-10-12"]]


def test_the_same_crowded_file_again_does_not_call_the_stored_rows_left_out(page):
    again = page["crowdedAgain"]
    assert again["result"] == "Added 0 weights and 0 readings; 51 were already here."  # the 20 weights of the day are already here, not "left out"
    assert again["left"] == "10 more on 2 days were left out (the app keeps at most 20 weights and 30 readings a day)."
    assert again["weightsOnDay"] == 20


def test_rows_the_person_typed_in_use_up_room_and_only_what_is_left_is_sent(page):
    manual = page["crowdedManual"]
    assert manual["imported"] == 17 and manual["total"] == 20 and manual["last"] == "06:16"  # three by hand + the file's earliest 17
    assert manual["result"] == "Added 18 weights and 30 readings."
    assert manual["left"] == "13 more on 2 days were left out (the app keeps at most 20 weights and 30 readings a day)."


def test_when_the_rows_already_here_cannot_be_read_only_the_limit_is_used_and_a_refusal_stops_the_import(page):
    unknown = page["crowdedUnknown"]
    assert unknown["lists"] == 2 and unknown["stored"] == 3  # both list routes failed
    assert unknown["problem"] == ["The import stopped: rows.18: too many weights for one day (max 20) (the row dated Oct 10, 2026)", "Nothing was added. Press Import to try again."]
    assert unknown["posted"] == [{"kind": "weights", "n": 21}] and unknown["go"]["disabled"] is False


def test_the_list_routes_are_asked_in_windows_of_366_days_and_only_where_the_file_has_rows(page):
    windows = page["windows"]["lists"]
    assert windows == [["weights", "2019-02-03", "2020-02-03"], ["readings", "2024-05-02", "2024-05-02"], ["weights", "2024-02-07", "2025-02-06"],
                       ["weights", "2026-02-08", "2026-10-20"]]
    assert page["windows"]["result"] == "Added 3 weights and 1 reading."


def test_a_refusal_in_the_middle_stops_with_the_servers_words_and_the_number_already_added(page):
    refused = page["refused"]
    assert refused["problem"] == ["The import stopped: rows.1: too many blood pressure readings for one day (max 30) (the row dated Oct 20, 2026)",
                                  "Added 3 weights and 0 readings before it stopped, and they are saved. Press Import to carry on: what is already here is skipped."]
    assert (refused["weightsStored"], refused["readingsStored"]) == (3, 0)
    assert refused["go"] == {"text": "Import 3 weights and 2 readings", "disabled": False, "hidden": False} and refused["cancel"] == "Cancel"
    assert refused["pickHidden"] is True and refused["reviewHidden"] is False  # the review stays, so it can be tried again
    assert refused["shown"] == ["trends"]  # the weights that were added are in Today and Trends
    again = page["refusedThenAgain"]
    assert again["result"] == "Added 0 weights and 2 readings; 3 were already here." and again["problem"] is None
    assert (again["weightsStored"], again["readingsStored"]) == (3, 2)


def test_a_refusal_after_the_first_batch_says_1000_were_added_and_names_the_day_of_the_row(page):
    many = page["manyRefused"]
    assert many["review"] == "Found 2,500 weights and 0 blood pressure readings. The app can keep 2,500 weights and 0 readings." and many["go"] == "Import 2,500 weights"
    assert many["problem"] == ["The import stopped: Too many imports of weights and readings. Try again later.",
                               "Added 1,000 weights and 0 readings before it stopped, and they are saved. Press Import to carry on: what is already here is skipped."]
    assert many["posted"] == [{"kind": "weights", "n": 1000}, {"kind": "weights", "n": 1000}] and many["stored"] == 1000
    assert page["rowNamed"]["problem"][0] == "The import stopped: rows.3.kg: Input should be greater than or equal to 20 (the row dated Jan 25, 2026)"
    assert page["rowNamed"]["problem"][1] == "Nothing was added. Press Import to try again."
    done = page["manyDone"]
    assert done["result"] == "Added 1,500 weights and 0 readings; 1,000 were already here." and done["stored"] == 2500


def test_a_gateway_error_stops_the_same_way_and_a_signed_out_answer_closes_the_sheet(page):
    assert page["gateway"]["problem"] == ["The import stopped: 502 Bad Gateway", "Nothing was added. Press Import to try again."]
    assert page["gateway"]["stored"] == 0 and page["gateway"]["go"]["disabled"] is False
    assert page["signedOut"]["open"] is False  # the sign-in screen needs the page


def test_cancel_while_reading_aborts_the_scan_and_cancels_the_stream(page):
    cancelled = page["cancelled"]
    assert cancelled["during"] == {"status": "Reading export.xml (0.1 MB) on this device…", "cancel": "Cancel", "pickHidden": True, "reviewHidden": True, "go": True}
    assert cancelled["after"]["status"] == "Cancelled. Nothing was read or saved." and cancelled["after"]["cancel"] == "Close"
    assert cancelled["after"]["pickHidden"] is False and cancelled["after"]["reviewHidden"] is True and cancelled["focused"] == "body-import-file"
    assert cancelled["streamCancelled"] == 1 and cancelled["pulls"] < cancelled["totalChunks"]  # it stopped reading
    assert cancelled["input"] == "" and cancelled["calls"] == 0
    closed = page["closedWhileReading"]
    assert closed == {"streamCancelled": 1, "reviewHidden": True, "status": "", "calls": 0}  # closing the sheet does the same


def test_stop_ends_an_import_after_the_request_in_flight_and_closing_the_sheet_says_so_in_a_message(page):
    stopped = page["stopped"]
    assert stopped["during"] == {"cancel": "Stop", "go": {"text": "Importing…", "disabled": True, "hidden": False}, "status": "Saving weights: 0 of 2,500…", "controlsDisabled": True}
    assert stopped["after"]["status"] == "Stopped. Added 1,000 weights and 0 readings so far. Press Import to carry on: what is already here is skipped."
    assert stopped["after"]["go"]["disabled"] is False and stopped["after"]["cancel"] == "Cancel" and stopped["after"]["problem"] is None
    assert stopped["posted"] == [{"kind": "weights", "n": 1000}] and stopped["stored"] == 1000 and stopped["shown"] == ["trends"]
    assert page["stoppedThenDone"] == {"result": "Added 1,500 weights and 0 readings; 1,000 were already here.", "stored": 2500}
    closed = page["closedWhileImporting"]
    assert closed["posted"] == [{"kind": "weights", "n": 1000}] and closed["stored"] == 1000 and closed["open"] is False and closed["reviewCleared"] == 0
    assert closed["toasts"] == [["Stopped. Added 1,000 weights and 0 readings so far. Press Import to carry on: what is already here is skipped.", ""]]


def test_a_file_with_nothing_the_app_keeps_says_so_and_offers_no_import(page):
    nothing = page["nothing"]
    assert nothing["headline"] == "No weights or blood pressure readings were found in this file."
    assert nothing["go"]["hidden"] is True and nothing["periods"] == 0 and nothing["cancel"] == "Cancel" and set(nothing["tags"]) <= {"div", "p"}
    assert page["nothingCancel"] == {"pickHidden": False, "reviewHidden": True}


def test_the_period_picker_is_left_out_when_all_of_the_file_is_recent_and_one_day_is_one_date(page):
    recent = page["allRecent"]
    assert recent["periods"] == 0 and recent["hint"] == "All of it is from the last 3 months." and recent["go"] == "Import 1 weight and 1 reading"
    assert recent["range"] == "Date in the file: Oct 20, 2026." and recent["watch"] is None
    assert page["sameDay"]["range"] == "Date in the file: Oct 20, 2026."


def test_trim_days_on_its_own(page):
    trim = page["trim"]
    assert trim["fits"] == 0 and trim["empty"] == {"keep": [], "leftOut": 0, "days": []} and trim["sameArrayWhenNothingDropped"] == 5
    assert len(trim["over"]["keep"]) == 20 and trim["over"]["keep"][0] == "2026-10-02-0" and trim["over"]["keep"][-1] == "2026-10-02-19"
    assert trim["over"]["leftOut"] == 5 and trim["over"]["days"] == ["2026-10-02"]
    assert trim["mixed"] == ["2026-10-02"]  # only the crowded day is named
    assert trim["keepOrder"] == ["2026-10-01-0", "2026-10-01-1", "2026-10-01-2", "2026-10-02-0"]  # the days that fit are kept whole, in order
    assert len(trim["withManual"]["keep"]) == 18 and trim["withManual"]["leftOut"] == 7  # two typed in by hand: room for 18
    assert len(trim["withImported"]["keep"]) == 20 and trim["withImported"]["leftOut"] == 5  # 20 stored from this file: sent again (skipped), the surplus is left out
    assert len(trim["importedAndManual"]["keep"]) == 15 and trim["importedAndManual"]["leftOut"] == 10  # 10 of the file stored + 5 by hand: 5 more of the file fit
    assert trim["fullDay"] == {"keep": [], "leftOut": 3, "days": ["2026-10-02"]}  # a day typed full takes none
    assert trim["editedImportedRowIsNotMatched"]["leftOut"] == 22 and trim["editedImportedRowIsNotMatched"]["keep"] == []  # an edited row counts as typed by hand
    assert trim["other_day_rows"]["leftOut"] == 5  # rows of other days do not take this day's room


def test_the_page_makes_no_network_call_of_its_own(page):
    assert page["network"] == []  # fetch, XMLHttpRequest, WebSocket and sendBeacon were all trapped; none was touched


# --------------------------------------------------------------------------- an export.zip


def test_an_export_zip_gives_the_same_review_as_the_export_xml_inside_it_and_reads_nothing_else_of_it(page):
    plain, zipped = page["review"], page["zipReview"]
    for key in ("headline", "range", "sources", "leftOut", "periods", "watch", "days", "go", "cancel", "status", "problem", "focused", "tags", "reviewHidden", "pickHidden"):
        assert zipped[key] == plain[key], key
    assert zipped["calls"] == 0 and zipped["lists"] == 0 and zipped["networkTrapped"] == 0  # nothing is sent while a .zip is read and reviewed
    # the archive was read through one stream (the export.xml), once, to its end; the encrypted file beside it was never selected
    assert page["zipRead"]["opened"] == 1 and page["zipRead"]["over"] == 1


def test_importing_from_an_export_zip_sends_the_same_rows_as_the_export_xml(page):
    plain, zipped = page["imported"], page["zipImported"]
    assert zipped["posted"] == plain["posted"] and zipped["weights"] == plain["weights"] and zipped["readings"] == plain["readings"]
    assert zipped["sources"] == ["apple_health"] and zipped["keys"] == plain["rowKeys"] and zipped["result"] == plain["result"] and zipped["shown"] == plain["shown"]
    # by type alone, and from a re-zipped folder with the macOS copy beside it
    assert page["zipByType"] == {"headline": page["review"]["headline"], "problem": None}


def test_each_way_an_export_zip_can_fail_is_told_in_plain_words_and_nothing_is_sent(page):
    zips = page["zips"]
    want = {
        "missing": f"This .zip has no export.xml in it. {FROM_THE_HEALTH_APP}",
        "cdaOnly": f"This .zip has the clinical documents file (export_cda.xml) but no export.xml. {FROM_THE_HEALTH_APP}",
        "twoExports": "This .zip holds more than one export.xml. In Files, tap the .zip to unzip it, then choose the one you want.",
        "damaged": ZIP_UNREADABLE,  # the checksum is wrong: told once the end is reached, no rows are shown
        "encrypted": ZIP_UNREADABLE,
        "cutOff": ZIP_UNREADABLE,
        "empty": ZIP_UNREADABLE,
    }
    for key, message in want.items():
        got = zips[key]
        assert got["problem"] == [message], key
        assert got["input"] == "" and got["pickHidden"] is False and got["reviewHidden"] is True and got["status"] == "" and got["cancel"] == "Close", key
        assert got["calls"] == 0 and got["lists"] == 0, key
    browser = zips["browser"]
    assert browser["problem"] == ["This browser cannot open a .zip here. In Files, tap export.zip to unzip it, then choose apple_health_export/export.xml."]
    assert browser["slices"] == 0 and browser["opened"] == 0 and browser["input"] == ""  # the archive was not even opened
    assert zips["afterwards"]["headline"] == page["review"]["headline"]


def test_cancel_while_an_export_zip_is_being_read_lets_go_of_the_file_and_the_name_is_text(page):
    cancelled = page["zipCancelled"]
    during = cancelled["during"]
    assert during["status"] == "Reading export.xml in <img src=x onerror=alert(1)>.zip (0.4 MB) on this device…" and during["imgs"] == 0
    assert during["cancel"] == "Cancel" and during["pickHidden"] is True and during["reviewHidden"] is True and during["go"] is True
    assert cancelled["after"] == {"status": "Cancelled. Nothing was read or saved.", "pickHidden": False, "reviewHidden": True, "problem": None, "focused": "body-import-file"}
    assert cancelled["opened"] == 1 and cancelled["over"] == 1  # its stream was cancelled (or had been read to the end): none is left open
    assert cancelled["input"] == "" and cancelled["calls"] == 0 and cancelled["lists"] == 0
    closed = page["zipClosedWhileReading"]
    assert closed["opened"] == 1 and closed["over"] == 1 and closed["reviewHidden"] is True and closed["status"] == "" and closed["calls"] == 0


def test_the_zip_path_of_the_view_opens_one_entry_and_tells_only_its_own_words():
    code = code_of(VIEW)
    assert "KH.zip.open(file)" in code and "zip.find(archive, zip.RULES.healthXml)" in code and "zip.list(archive, zip.RULES.healthCda)" in code
    assert "!KH.zip.supported()" in code  # an older browser gets the unzip advice, the archive is not opened
    # every message of the reading comes from a table of the page, never from the archive or the error
    reading = code_of(VIEW[VIEW.index("async function onPick"):VIEW.index("// The rows for a period")])
    assert "err.message" not in reading and "entry.name" not in reading and "ZIP_MESSAGE[err && err.code] || ZIP_UNREADABLE" in reading
    zip_words = VIEW[VIEW.index("const ZIP_MESSAGE"):VIEW.index("const isZipFile")]
    assert "Export from the Health app again, or unzip it in Files" in zip_words and "damaged or not finished downloading" in zip_words
