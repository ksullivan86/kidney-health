#!/usr/bin/env python3
"""Labs -> **Read a lab report photo or PDF**, reading a PDF page's own text, in Chromium against a real server and a fake local AI
(design note 36).

    python tools/e2e/lab_pdf_text.py                              # ports 8261 (app), 8262 (fake local AI)
    python tools/e2e/lab_pdf_text.py --port 8261 --ai-port 8262 --out /tmp/kh-lab-pdf-text

``tests/js/pdf_text.test.mjs`` and ``tests/js/lab_photo_page.mjs`` run the code against fakes in Node; this drives the real thing together:
the vendored pdf.js reading the text of a real PDF in its worker, ``js/engine/pdf_text.js`` rebuilding the lines, the strict CSP,
``POST /api/ai/read-lab-report-text`` with its consent and its check that each value is written in the text, the picture path for a page
without text, and ``POST /api/labs/import``.

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED`` and a fake OpenAI-compatible server this script runs as the local
AI (listed in ``AI_PRIVATE_HOSTS``). For the text of a page it copies the potassium, phosphate and creatinine lines it is sent and makes up
one more row (an albumin that is not on the page); for a picture it answers one eGFR row. The PDF is written by the tiny PDF writer of
``lab_pdf.py``: page 1 has real text, with a line that names a made-up patient; page 2 has no text (a scan). Then, on 375x812 light and
1280x800 dark:

* choosing the PDF lists "Page 1 (has text)" and "Page 2 (picture only)" and "Read the text" is chosen, with the line about text; nothing
  is sent by choosing it;
* "Read the report" opens the consent sheet (withdrawn first, so it shows), which carries the line about text; "Agree and send" reads page
  1 as text and page 2 as a picture: the fake AI got one text request (no image, the potassium line in it, the patient's name, date of
  birth and record number not in it) and one request with one JPEG; the browser posted page 1 as JSON and nothing that starts with %PDF-;
* one table: three rows "read from its text" and one "read from a picture of it", every row unticked; the made-up albumin is not there and a
  line says one value was left out because it is not written in the page's text; a line says one line that may name the person was left out;
* Save sends the ticked rows through ``POST /api/labs/import`` (the labs list through the API equals them); the AI activity list holds no
  line of the report's text;
* the browser asked no other host and nothing outside the app's own files and the two pdf.js files; no CSP or Trusted Types violation,
  console error, dialog or sideways scroll.

What it cannot show: a real lab's PDF and a real model reading its text (``scripts/ai_eval.py --lab-text`` measures a model on made-up
pages), a real phone's file picker, Safari. Those stay in the manual device matrix (docs/maintainers.md).

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots
in ``<out>/shots/``; exit status 1 on any failure. The server, the fake AI and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

import khserver
from device import FakeAi, Harness, wait_js
from khserver import Server, first_admin
from lab_pdf import SPY, Recorder, card_shot, make_pdf, overflow, pick, rows_of, text_of

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "lab_pdf_text"
PORT, AI_PORT = 8261, 8262
RESULTS: list[dict[str, Any]] = []
PDFJS_FILES = {"/vendor/pdfjs-dist-6.4.299/pdf.min.mjs", "/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs"}
TEXT_LINE = ("Pages with text are sent as text, without the lines that may show your name, date of birth or record numbers. "
             "Other pages are drawn on this device and sent as pictures. The PDF file itself is not sent.")
# A made-up report (no real person). Page 2 has no text at all: pdf.js finds nothing on it, so it goes as a picture.
REPORT = make_pdf([
    ["Harness Valley Laboratory", "Patient: Jane Example DOB: 01/02/1961 MRN 00012345", "Collected: 2026-10-07",
     "Potassium 5.4 mmol/L 3.5-5.1", "Phosphate 1.2 mmol/L 0.8-1.5", "Creatinine 88 umol/L 59-104", "Sodium 139 mmol/L 136-145"],
    [],
])
IDENTITY = ("Jane", "Example", "1961", "00012345", "MRN", "Patient")


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class TextAi(FakeAi):
    """The fake OpenAI-compatible server of device.py, plus: the text of a lab report page is copied (with one made-up row), a lab report
    picture gets one eGFR row; what each request carried is kept."""

    COPY = re.compile(r"^(Potassium|Phosphate|Creatinine) (\d+(?:\.\d+)?) (\S+)")

    def __init__(self, port: int) -> None:
        super().__init__(port)
        self.text_requests: list[dict[str, Any]] = []
        self.picture_requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def reset(self) -> None:
        self.text_requests.clear()
        self.picture_requests.clear()

    def answer(self, body: dict[str, Any]) -> dict[str, Any]:
        text, images = self.texts(body)
        if text.startswith("TASK: read_lab_report_text"):
            lines = json.loads(text.split("<data>\n", 1)[1].split("\n</data>", 1)[0])["lines"]
            with self._lock:
                self.text_requests.append({"lines": lines, "images": len(images), "body": json.dumps(body)})
            rows = []
            for line in lines:
                found = self.COPY.match(line)
                if found:
                    rows.append({"analyte": found.group(1).lower(), "value": float(found.group(2)), "unit": found.group(3), "taken_on": "2026-10-07"})
            rows.append({"analyte": "albumin", "value": 41, "unit": "g/L", "taken_on": "2026-10-07"})  # not on the page: the app drops it
            return {"status": "ok", "rows": rows}
        if text.startswith("TASK: read_lab_report."):
            with self._lock:
                self.picture_requests.append({"images": len(images), "jpeg": [u.startswith("data:image/jpeg;base64,") for u in images]})
            return {"status": "ok", "rows": [{"analyte": "egfr", "value": 58, "unit": "mL/min/1.73m2", "taken_on": "2026-10-07"}]}
        return super().answer(body)


def walk(hx: Harness, ai: TextAi, provider_id: int, tag: str, width: int, height: int, scheme: str) -> None:
    ctx, watch = hx.context(width=width, height=height, scheme=scheme, init=SPY)
    page: Page = ctx.new_page()
    rec = Recorder(ctx, page)
    dialogs: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    watch.expect("/api/ai/read-lab-report-text", 409)  # the consent sheet's first answer
    hx.admin.call("DELETE", f"/api/ai/consent/{provider_id}", params={"purpose": "labs"})
    for item in hx.admin.json("GET", "/api/labs").get("labs", []):
        hx.admin.call("DELETE", f"/api/labs/{item['id']}")
    ai.reset()
    try:
        page.goto(f"{hx.base}/#labs")
        wait_js(page, "!!document.querySelector('#lab-photo') && !document.querySelector('#lab-photo').hidden && !document.querySelector('#lab-photo-controls').hidden")
        card = text_of(page, "#lab-photo")
        check(f"[{tag}] the card says a page with text is read as text", "A page with its own text is read as text" in card, card[:300])

        # 1. Choose the PDF: its text is read here, the pages say which have text, "Read the text" is chosen
        pick(page, "lab-report.pdf", REPORT)
        wait_js(page, "document.querySelectorAll('#lab-photo-pages input[type=checkbox]').length === 2")
        listed = text_of(page, "#lab-photo-pages")
        check(f"[{tag}] page 1 has text, page 2 is a picture only", "Page 1 (has text)" in listed and "Page 2 (picture only)" in listed, listed)
        check(f"[{tag}] 'Read the text' is chosen and 'Read pictures of the pages' is offered",
              page.is_checked("#lab-photo-mode-text") and not page.is_checked("#lab-photo-mode-picture"))
        check(f"[{tag}] the list says what leaves the device for text", TEXT_LINE in listed, listed)
        check(f"[{tag}] choosing the PDF sent nothing", not ai.text_requests and not ai.picture_requests
              and not [r for r in rec.requests if r[0] == "POST" and r[1].startswith("/api/ai/")])
        check(f"[{tag}] the page list has no sideways scroll", not overflow(page))
        card_shot(hx, page, f"pages-{tag}")

        # 2. Read: the consent sheet, then page 1 as text and page 2 as a picture
        page.click("#lab-photo-read")
        page.wait_for_selector("#sheet-ai-consent[open]")
        sheet = text_of(page, "#sheet-ai-consent")
        check(f"[{tag}] the consent sheet is the lab report one and carries the line about text", TEXT_LINE in sheet and "date of birth" in sheet, sheet)
        check(f"[{tag}] nothing was sent before 'Agree and send'", not ai.text_requests and not ai.picture_requests)
        hx.shot(page, f"consent-{tag}")
        page.click("#sheet-ai-consent >> text=Agree and send")
        wait_js(page, "!!document.querySelector('#lab-photo-results .lab-photo-list')", 40000)
        sent_lines = ai.text_requests[0]["lines"] if ai.text_requests else []
        check(f"[{tag}] one text request for page 1, no image in it, the results' lines in it", len(ai.text_requests) == 1
              and ai.text_requests[0]["images"] == 0 and "image_url" not in ai.text_requests[0]["body"]
              and "Potassium 5.4 mmol/L 3.5-5.1" in sent_lines and "Collected: 2026-10-07" in sent_lines, json.dumps(sent_lines))
        check(f"[{tag}] the line naming the patient, the date of birth and the record number was not sent",
              not any(word in ai.text_requests[0]["body"] for word in IDENTITY) if ai.text_requests else False, json.dumps(sent_lines))
        check(f"[{tag}] one picture request for page 2, one JPEG", ai.picture_requests == [{"images": 1, "jpeg": [True]}], json.dumps(ai.picture_requests))
        posts = [r for r in rec.requests if r[0] == "POST" and r[1].startswith("/api/ai/read-lab-report")]
        check(f"[{tag}] the browser posted page 1 as JSON and page 2 as a JPEG",
              ("POST", "/api/ai/read-lab-report-text", "application/json") in posts and ("POST", "/api/ai/read-lab-report", "image/jpeg") in posts, str(posts))
        bodies = page.evaluate("window.__khBodies")
        check(f"[{tag}] nothing the page sent starts with %PDF- or has the PDF's type", bodies and not any(b["pdf"] for b in bodies), json.dumps(bodies)[:400])

        # 3. One table: where each row came from, the made-up row dropped, every row unticked
        rows = rows_of(page)
        from_text = [r for r in rows if "read from its text" in r]
        from_picture = [r for r in rows if "read from a picture of it" in r]
        check(f"[{tag}] three rows read from the text of page 1 and one from the picture of page 2",
              len(rows) == 4 and len(from_text) == 3 and len(from_picture) == 1 and "page 2 of your PDF" in from_picture[0], str(rows))
        check(f"[{tag}] the made-up albumin is not shown", not any("Albumin" in r for r in rows), str(rows))
        results = text_of(page, "#lab-photo-results")
        check(f"[{tag}] a line says the value not written in the page's text was left out",
              "Page 1: 1 line was left out because its number is not written in the page's text." in results, results[:600])
        check(f"[{tag}] a line says the line that may name the person was left out before sending",
              "Before sending, 1 line that may show your name, date of birth or record numbers was left out." in results, results[:600])
        check(f"[{tag}] the notice says the rows were read from the text where there was text",
              "from their text where they have it" in results, results[:300])
        ticked = page.evaluate("[...document.querySelectorAll('#lab-photo-results .lab-photo-list input[type=checkbox]')].map((c) => c.checked)")
        check(f"[{tag}] every row starts unticked", ticked == [False] * 4, str(ticked))
        check(f"[{tag}] the results have no sideways scroll", not overflow(page))
        card_shot(hx, page, f"results-{tag}")

        # 4. Save the ticked rows through the ordinary import; the activity list keeps none of the text
        for index in range(4):
            page.check(f"#lab-photo-row-{index}")
        page.click("#lab-photo-save")
        wait_js(page, "document.querySelector('#lab-photo-results').textContent.includes('Saved 4 results')")
        saved = hx.admin.json("GET", "/api/labs").get("labs", [])
        check(f"[{tag}] the server holds exactly the four ticked results",
              sorted(s["analyte"] for s in saved) == ["creatinine", "egfr", "phosphate", "potassium"], json.dumps([(s["analyte"], s["value"]) for s in saved]))
        audit = json.dumps(hx.admin.json("GET", "/api/ai/audit"))
        check(f"[{tag}] the AI activity list holds no line of the report's text", "read_lab_report_text" in audit
              and not any(word in audit for word in ("Potassium 5.4", "Harness Valley", "Collected", "Jane")), audit[:400])
        card_shot(hx, page, f"saved-{tag}")
        check(f"[{tag}] pdf.js asked for its library and worker only, nothing else under /vendor/pdfjs-dist-6.4.299/",
              rec.pdfjs_paths() == PDFJS_FILES, str(rec.pdfjs_paths()))
        check(f"[{tag}] every pdf.js worker was closed", rec.workers and all(w["closed"] for w in rec.workers), str(rec.workers))
        check(f"[{tag}] no dialog was shown", not dialogs, str(dialogs))
    finally:
        problems = watch.take()
        check(f"[{tag}] no CSP or Trusted Types violation, console or page error, failed request or request to another host", not problems,
              "; ".join(problems[:6]))
        ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT, help=f"uvicorn port (default {PORT})")
    ap.add_argument("--ai-port", type=int, default=AI_PORT, help=f"the fake local AI's port (default {AI_PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory: data, logs, report, screenshots (default {OUT})")
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs the server (default: this one)")
    args = ap.parse_args(argv)
    for port in (args.port, args.ai_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"AI_ENABLED": "true", "AI_PROVIDER": "openai_compatible", "AI_PROVIDER_ROLE": "local",  # the fake AI is the local AI
           "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1", "AI_MODEL": "fake-text", "AI_VISION_MODEL": "fake-vision",
           "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port}", "AI_SHARED_DAILY_LIMIT": "0",
           # No call may leave this machine: a proxy that does not exist for anything but the local server.
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", python=args.server_python, env=env)
    try:
        with TextAi(args.ai_port) as ai:
            server.start()
            admin = first_admin(server, "labtext")
            admin.json("PATCH", "/api/me/ai", {"opt_in": True})
            provider_id = next(p["id"] for p in admin.json("GET", "/api/admin/ai-providers")["providers"] if p["locked"])
            base = f"http://localhost:{args.port}"
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
                hx = Harness(browser, server, admin, out, base)
                try:
                    for tag, width, height, scheme in (("375-light", 375, 812, "light"), ("1280-dark", 1280, 800, "dark")):
                        try:
                            walk(hx, ai, provider_id, tag, width, height, scheme)
                        except Exception as exc:  # report and go on with the next screen
                            check(f"[{tag}] the walk finished", False, f"{type(exc).__name__}: {exc}")
                            traceback.print_exc()
                finally:
                    browser.close()
            admin.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        server.stop()
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps({"failed": len(failed), "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}, screenshots {out / 'shots'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
