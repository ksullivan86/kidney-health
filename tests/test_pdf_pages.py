"""The browser module that draws the pages of a PDF lab report (``app/static/js/engine/pdf_pages.js``, ``KH.pdfPages``; design note 13 §4.2, §5).

Static checks on the source (the one Trusted Types policy and its single URL, the order of ``workerPort`` and ``getDocument``, the exact
option list, nothing that fetches, no HTML sink, the file is in the shell and the service worker) and a run of the real file in Node
against a fake pdf.js and fake browser globals (``tests/js/pdf_pages_page.mjs``, ``tests/js/fake_pdfjs.mjs``): the options handed to
``getDocument`` are exactly note 13 D3's, ``workerPort`` is set before ``getDocument`` and the worker is made by the module under its policy,
a pdf.js that ignores the port is refused, the scale rules, every error code, ``close()`` and Cancel.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
SOURCE = (STATIC / "js" / "engine" / "pdf_pages.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
PDFJS_URL = "/vendor/pdfjs-dist-6.4.299/pdf.min.mjs"
WORKER_URL = "/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs"


def code_of(text: str) -> str:
    """The source without its comments (so the header may name what the code must not do)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(?<![:'\"`])//.*$", "", line) for line in text.splitlines())


CODE = code_of(SOURCE)


@pytest.fixture(scope="module")
def ran() -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the browser code (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "pdf_pages_page.mjs")], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --------------------------------------------------------------------------- the source
def test_the_file_is_an_engine_in_the_shell_before_the_lab_report_view_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    engines = [s for s in scripts if s.startswith("js/engine/")]
    assert "js/engine/pdf_pages.js" in engines
    assert scripts.index("js/engine/pdf_pages.js") < scripts.index("js/core.js") < scripts.index("js/views/lab_photo.js")
    shell = re.search(r"const SHELL_URLS = \[(.*?)\];", SW, re.S).group(1)
    assert "'/js/engine/pdf_pages.js'," in shell
    assert "pdfjs-dist" not in shell and "pdfjs-dist" not in INDEX  # the library is imported on the first PDF, never a shell file


def test_the_urls_name_files_that_are_vendored_and_pinned():
    assert f"const PDFJS_URL = '{PDFJS_URL}';" in SOURCE and f"const WORKER_URL = '{WORKER_URL}';" in SOURCE
    for url in (PDFJS_URL, WORKER_URL):
        assert (STATIC / url.lstrip("/")).is_file(), url
    assert "import(PDFJS_URL)" in CODE and CODE.count("import(") == 1  # the one dynamic import; no static import, no other module


def test_the_only_trusted_types_policy_is_kh_pdf_and_it_passes_one_url():
    assert CODE.count("createPolicy(") == 1 and "tt.createPolicy('kh-pdf'" in CODE
    assert "createScriptURL: (url) => { if (url === WORKER_URL) return url; throw new TypeError('blocked worker URL'); }," in CODE
    assert "'default'" not in CODE and "allow-duplicates" not in CODE
    assert "createHTML" not in CODE and "createScript(" not in CODE  # only a script URL, never HTML or script text
    # the worker is made once, here, from the policy's output, as a module worker
    assert CODE.count("new root.Worker(") == 1 and "new root.Worker(workerUrl(), { type: 'module' })" in CODE
    assert not re.search(r"new\s+(?:Shared)?Worker\(", CODE.replace("new root.Worker(", ""))
    assert not re.search(r"(?<![A-Za-z])Blob\b|createObjectURL|blob:|[\x22\x27`]data:", CODE)


def test_the_port_is_set_before_getdocument_and_the_options_are_exactly_the_audited_list():
    assert CODE.index("lib.GlobalWorkerOptions.workerPort = worker;") < CODE.index("lib.getDocument(")
    call = CODE[CODE.index("lib.getDocument({"):]
    call = call[:call.index("});")]
    keys = re.findall(r"^\s+(\w+):", call, flags=re.M)
    assert keys == ["data", "isEvalSupported", "enableXfa", "disableAutoFetch", "disableStream", "disableRange", "stopAtErrors"]
    assert "isEvalSupported: false" in call and "enableXfa: false" in call and "stopAtErrors: false" in call
    assert all(f"{k}: true" in call for k in ("disableAutoFetch", "disableStream", "disableRange"))
    assert "data: bytes," in call
    # the things whose absence keeps pdf.js from requesting anything (note 13 D3)
    for unset in ("url", "cMapUrl", "standardFontDataUrl", "iccUrl", "wasmUrl", "httpHeaders", "withCredentials", "password", "range", "worker",
                  "ownerDocument", "enableScripting"):
        assert not re.search(rf"\b{unset}\s*:", call), unset
    assert "onPassword" not in CODE  # the app never asks for a password
    # a pdf.js that did not take the port is refused before its task is awaited
    assert CODE.index("if (posted === 0) throw fail('browser');") < CODE.index("await raceAbort(Promise.race([task.promise, dead]), signal)")


def test_the_render_call_draws_a_white_page_without_annotations():
    assert "page.render({ canvas, viewport, background: '#ffffff', annotationMode: lib.AnnotationMode.DISABLE })" in CODE
    assert "getTextContent" not in CODE and "TextLayer" not in CODE and "getAnnotations" not in CODE  # no text layer, no annotation layer
    assert "canvasToJpeg" in CODE and "'image/jpeg'" in CODE and "JPEG_QUALITY: 0.9" in CODE
    assert "page.cleanup()" in CODE and "canvas.width = 0" in CODE and "workerPort = null" in CODE and "worker.terminate()" in CODE


def test_nothing_in_the_module_touches_the_network_storage_or_html():
    assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|importScripts|FileReader|createObjectURL", CODE)
    assert not re.search(r"localStorage|sessionStorage|indexedDB|caches\.|document\.cookie", CODE)  # nothing about the PDF is stored
    assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function|setAttribute|srcdoc", CODE)
    assert not re.search(r"https?://", CODE)
    assert "KH.ai" not in CODE and "KH.request" not in CODE  # it only draws; sending is the view's business


def test_the_header_documents_every_option_and_every_error_code_and_limit():
    header = SOURCE[:SOURCE.index("(function (root)")]
    for word in ("isEvalSupported", "enableXfa", "disableAutoFetch", "disableStream", "disableRange", "stopAtErrors", "workerPort",
                 "cMapUrl", "standardFontDataUrl", "wasmUrl", "iccUrl", "kh-pdf", "AnnotationMode", "background", "fake worker",
                 "20 MiB", "50 pages", "2048", "4,000,000", "AbortError", "app/security.py"):
        assert word in header, word
    for code in ("too_big", "not_pdf", "password", "damaged", "too_many_pages", "browser"):
        assert re.search(rf"^\s+{code}\s", header, flags=re.M), code


@pytest.mark.parametrize("path", ["sw.js", "js/engine/pdf_pages.js", "js/views/lab_photo.js", "js/views/ai.js"])
def test_the_files_this_feature_touches_still_parse(path):
    """A comment that contained the two characters that end a comment once stopped the service worker from starting: it is parsed here."""
    assert shutil.which("node"), "Node.js 22 is needed to run the browser code (CLAUDE.md, Parity)"
    done = subprocess.run(["node", "--check", str(STATIC / path)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr


# --------------------------------------------------------------------------- the file run in Node
def test_exports_and_limits(ran):
    assert ran["exports"] == ["ERROR_CODES", "LIMITS", "PDFJS_URL", "WORKER_URL", "open", "planScale", "supported"]
    assert ran["limits"] == {"MAX_BYTES": 20 * 1024 * 1024, "MAX_PAGES": 50, "MAX_EDGE": 2048, "MAX_AREA": 4000000, "MIN_EDGE": 16, "MAX_SCALE": 4,
                             "JPEG_QUALITY": 0.9}
    assert ran["urls"] == {"pdfjs": PDFJS_URL, "worker": WORKER_URL}
    assert ran["codes"] == ["too_big", "not_pdf", "password", "damaged", "too_many_pages", "browser"]


def test_supported_needs_a_worker_promise_with_resolvers_and_a_canvas_that_makes_a_jpeg(ran):
    assert ran["supported"] == {"all": True, "noWorker": False, "noWithResolvers": False, "noCanvas": False}


def test_the_scale_keeps_every_page_inside_what_the_server_accepts(ran):
    scale = ran["scale"]
    assert (scale["letter"]["w"], scale["letter"]["h"]) == (1582, 2048)  # note 13 D5: about 1583 x 2048, 3.2 MP
    assert (scale["a4"]["w"], scale["a4"]["h"]) == (1448, 2048)
    assert (scale["landscape"]["w"], scale["landscape"]["h"]) == (2048, 1582)
    assert (scale["receipt"]["w"], scale["receipt"]["h"]) == (578, 2048)  # a long page, still under 4:1
    assert (scale["tiny"]["w"], scale["tiny"]["h"]) == (40, 40) and scale["tiny"]["scale"] == 4  # never blown up beyond 4x
    assert (scale["tinier"]["w"], scale["tinier"]["h"]) == (16, 16)  # raised to 16 px a side
    assert (scale["poster"]["w"], scale["poster"]["h"]) == (1462, 2048)  # a huge page is shrunk
    assert (scale["square"]["w"], scale["square"]["h"]) == (2000, 2000)  # 4 MP rather than 2048 x 2048
    assert (scale["small"]["w"], scale["small"]["h"]) == (400, 560)
    assert scale["zero"] == scale["letter"] and (scale["nan"]["w"], scale["nan"]["h"]) == (2048, 334)  # a page with no size is a Letter page / the default width
    assert ran["scaleGrid"]["cases"] >= 300 and ran["scaleGrid"]["bad"] == []


def test_getdocument_gets_exactly_the_audited_options_and_the_pdf_bytes_only(ran):
    opened = ran["open"]
    assert opened["options"] == {"isEvalSupported": False, "enableXfa": False, "disableAutoFetch": True, "disableStream": True, "disableRange": True,
                                 "stopAtErrors": False}
    assert opened["optionKeys"] == ["data", "disableAutoFetch", "disableRange", "disableStream", "enableXfa", "isEvalSupported", "stopAtErrors"]
    assert opened["dataIsArrayBuffer"] is True and opened["dataStartsWithPdf"] == "%PDF-"
    assert opened["asked"] == [PDFJS_URL] and opened["getDocumentCalls"] == 1 and opened["fileReads"] == 1
    assert opened["numPages"] == 2


def test_the_port_is_set_before_getdocument_and_the_worker_is_made_here_under_the_policy(ran):
    opened = ran["open"]
    assert opened["events"] == ["workerPort=set", "getDocument"]
    assert opened["worker"] == {"count": 1, "url": WORKER_URL, "options": {"type": "module"}, "posted": 1, "terminated": False}
    assert opened["policies"] == ["kh-pdf"]  # created once, with the name the CSP lists
    rules = ran["policyRules"]
    assert rules["keys"] == ["createScriptURL"]  # no createHTML, no createScript
    tries = rules["tries"]
    assert tries[WORKER_URL] == WORKER_URL
    assert all(value.startswith("throws TypeError") for url, value in tries.items() if url != WORKER_URL), tries
    assert len(tries) >= 10


def test_without_trusted_types_the_url_string_is_used(ran):
    assert ran["noTrustedTypes"] == {"url": WORKER_URL, "options": {"type": "module"}}


def test_a_page_is_drawn_white_without_annotations_then_released(ran):
    render = ran["render"]
    assert render["first"] == {"type": "image/jpeg", "quality": 0.9, "w": 1582, "h": 2048}
    assert render["second"] == {"type": "image/jpeg", "w": 1448, "h": 2048}
    for r, size in zip(render["renders"], ((1582, 2048), (1448, 2048)), strict=True):
        assert r["keys"] == ["annotationMode", "background", "canvas", "canvasHeight", "canvasWidth", "page", "viewport"]  # no canvasContext, no intent
        assert r["background"] == "#ffffff" and r["annotationMode"] == 0  # AnnotationMode.DISABLE
        assert (r["canvasW"], r["canvasH"]) == size
    assert render["contextOptions"] == [["2d", {"alpha": False}]] * 2  # no transparency: a JPEG would turn it black
    assert [fill[0] for fill in render["whiteFirst"]] == ["#ffffff", "#ffffff"]
    assert render["canvasesZeroed"] is True and render["cleanups"] == ["cleanup:1", "cleanup:2"]


def test_close_destroys_the_task_terminates_the_worker_clears_the_port_and_is_safe_twice(ran):
    closed = ran["closed"]
    assert closed["events"][-2:] == ["task.destroy", "workerPort=null"] and closed["terminated"] is True
    assert closed["renderAfter"]["error"] == "damaged"
    twice = ran["twice"]
    assert twice["firstTerminated"] is True and twice["secondOpen"] is True and twice["policies"] == 1  # the policy is created once


# (name in the run, code, did pdf.js get a task that must be destroyed)
REFUSALS = [
    ("tooBig", "too_big", False), ("notPdf", "not_pdf", False), ("notPdfShort", "not_pdf", False), ("emptyFile", "not_pdf", False),
    ("notAFile", "not_pdf", False), ("customLimits", "too_big", False),
    ("notSupported", "browser", False), ("importFails", "browser", False), ("policyRefused", "browser", False), ("workerThrows", "browser", False),
    ("password", "password", True), ("damaged", "damaged", True), ("noPages", "damaged", True), ("tooManyPages", "too_many_pages", True),
    ("customPages", "too_many_pages", True), ("fakeWorker", "browser", True), ("workerError", "browser", True),
]


@pytest.mark.parametrize("name,code,started", REFUSALS)
def test_each_refusal_has_its_code_and_leaves_nothing_behind(ran, name, code, started):
    result = ran[name]
    assert result["error"] == code, result
    assert result.get("terminated") in (True, None)  # a worker that was made is terminated
    assert result.get("destroyed", False) is started  # and a pdf.js task that was started is destroyed
    assert result.get("portCleared", True) is True


def test_the_size_check_comes_before_the_file_is_read_and_the_header_check_before_pdfjs_is_loaded(ran):
    assert ran["tooBig"]["fileReads"] == 0 and ran["tooBig"]["size"] == 21 * 1024 * 1024 and ran["tooBig"]["getDocumentCalls"] == 0
    assert ran["customLimits"]["fileReads"] == 0 and ran["customLimits"]["size"] == 3000
    for name in ("notPdf", "notPdfShort", "emptyFile"):
        assert ran[name]["workers"] == 0 and ran[name]["getDocumentCalls"] == 0, name
    assert ran["tooManyPages"]["numPages"] == 51


def test_exactly_the_limits_are_allowed(ran):
    assert ran["exactlyAtTheLimit"]["ok"] == {"numPages": 2}  # 20 MiB
    assert ran["fiftyPagesAreFine"]["ok"] == {"numPages": 50}


def test_a_pdfjs_that_ignores_our_worker_is_refused_before_it_gets_the_bytes(ran):
    fake = ran["fakeWorker"]
    assert fake["error"] == "browser" and fake["terminated"] is True and fake["destroyed"] is True and fake["getDocumentCalls"] == 1


def test_a_worker_that_fails_to_start_is_not_waited_for(ran):
    assert ran["workerError"] == {"error": "browser", "name": "Error", "terminated": True, "destroyed": True}


def test_cancel_stops_whatever_is_running_and_releases_it(ran):
    assert ran["abortBefore"] == {"error": "AbortError", "name": "AbortError", "workers": 0}
    assert ran["abortWhileOpening"] == {"error": "AbortError", "name": "AbortError", "terminated": True, "destroyed": True}
    assert ran["abortRenderBefore"] == {"error": "AbortError", "name": "AbortError", "rendersStarted": 0}
    assert ran["abortRenderDuring"]["error"] == "AbortError" and ran["abortRenderDuring"]["events"] == ["render.cancel", "cleanup:1"]
    assert ran["abortRenderDuring"]["zeroed"] is True
    assert ran["abortGetPage"]["error"] == "AbortError"


def test_a_page_that_cannot_be_drawn_leaves_the_document_usable(ran):
    assert ran["renderFails"]["error"] == "damaged" and ran["renderFails"]["cleanups"] == ["cleanup:1"] and ran["renderFails"]["zeroed"] is True
    assert ran["afterAFailedPage"] == {"ok": True}
    assert ran["noJpeg"]["error"] == "browser"
    assert ran["badPage"] == {"zero": "RangeError", "three": "RangeError", "fraction": "RangeError", "text": "RangeError"}


def test_pages_of_different_shapes_come_out_inside_the_limits(ran):
    assert ran["shapes"] == [[1582, 2048], [1448, 2048], [578, 2048], [40, 40], [2048, 1582]]
    assert all(w <= 2048 and h <= 2048 and w * h <= 4_000_000 for w, h in ran["shapes"])
