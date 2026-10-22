#!/usr/bin/env python3
"""Labs -> **Read a lab report photo or PDF**, with a PDF, in Chromium against a real server and a fake local AI (design note 13 §5).

    python tools/e2e/lab_pdf.py                              # ports 8089 (app), 8090 (fake local AI)
    python tools/e2e/lab_pdf.py --port 8089 --ai-port 8090 --out /tmp/kh-lab-pdf

``tests/js/pdf_pages_page.mjs`` and ``tests/js/lab_photo_page.mjs`` run the code against fakes in Node; this drives the real thing
together: the vendored pdf.js 6.4.299 in a module Worker the page makes under the Trusted Types policy ``kh-pdf``, the strict CSP, the
service worker, ``POST /api/ai/read-lab-report`` and the consent for it (``app/ai/``), and ``POST /api/labs/import``.

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED`` and a fake OpenAI-compatible server this script runs as the
local AI (listed in ``AI_PRIVATE_HOSTS``; it answers lab report photos with scripted rows, one answer per page, and remembers what it
was sent). The PDFs are written by a tiny PDF writer in this file (no library): a two-page report, an encrypted one (RC4, user
password), a damaged one, a 51-page one and a 21 MB one. Then, on 375x812 light (no service worker) and 1280x800 dark (service worker
allowed, so the module, the worker and their cache take the installed app's path):

* the card says a PDF works too and the file input accepts it; choosing the report lists "Page 1" and "Page 2", both ticked, with the
  line that each page is drawn here and sent as a picture; nothing is sent by choosing it;
* "Read the report" opens the consent sheet (withdrawn first, so it shows), which says the same line; "Agree and send" reads page by page
  ("Reading page 2 of 2…"); the fake AI got exactly two requests, each one JPEG of a page (no EXIF, within 2048 px, drawn: dark pixels
  in it, the two different), the browser sent nothing but those JPEGs (no body starts with %PDF-), and the server never saw a PDF;
* one table of rows with the page of each, the repeated row shown once, every row unticked, a row without a date waits for one; the
  date is entered and Save sends the ticked rows through ``POST /api/labs/import`` (the labs list through the API equals them);
  the page list, the PDF and its worker are gone (the worker closed, the file input empty);
* Cancel while page 2 is being read: the request is aborted, the table holds page 1's rows and says it stopped, Cancel hides, the
  worker is closed, and the AI's slot is free again before the next step;
* a file that cannot be used says why, in the app's words, and sends nothing: not a PDF, damaged, a password (pdf.js's real
  PasswordException), 51 pages, 21 MB;
* the browser asked no other host, requested from ``/vendor/pdfjs-dist-6.4.299/`` only the library and its worker (nothing else:
  no CMaps, fonts or WebAssembly), made exactly one Worker per reading with the vendored worker's address and closed it; there is no
  CSP or Trusted Types violation, console error, dialog or sideways scroll; with the service worker, both vendored files are in its
  ``/vendor/`` cache afterwards.

What it cannot show: a real phone's file picker (the harness hands the file to the input), a real lab's PDF and a real model reading
it (the fake AI is scripted; ``scripts/ai_eval.py`` is where a PDF page is measured against a vision model), Safari. Those stay in
the manual device matrix (docs/maintainers.md).

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes ``<out>/report.json`` and
screenshots in ``<out>/shots/``; exit status 1 on any failure. The server, the fake AI and the browser are always stopped.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

import khserver
from device import FakeAi, Harness, jpeg_has_exif, wait_js
from khserver import Server, first_admin

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "lab_pdf"
PORT, AI_PORT = 8089, 8090
RESULTS: list[dict[str, Any]] = []
PDFJS_DIR = "/vendor/pdfjs-dist-6.4.299/"
PDFJS_FILES = {PDFJS_DIR + "pdf.min.mjs", PDFJS_DIR + "pdf.worker.min.mjs"}
PDF_LINE = "Each page you tick is drawn on this device and sent as a picture; the PDF file itself is not sent."
MB = 1024 * 1024


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


# --------------------------------------------------------------------------- a tiny PDF writer (no library)

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")  # the standard security handler's padding string


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def page_content(lines: Sequence[str]) -> bytes:
    """A heading, then lines of text each with a rule under it: the rules are dark pixels even where a machine has no font."""
    ops = ["0 g"]
    y = 720
    for i, text in enumerate(lines):
        size = 16 if i == 0 else 11
        ops.append(f"BT /F1 {size} Tf 72 {y} Td ({_escape(text)}) Tj ET")
        ops.append(f"72 {y - 7} 468 1.2 re f")
        y -= 30
    return "\n".join(ops).encode("latin-1")


def make_pdf(pages: Sequence[Sequence[str]], *, size: tuple[int, int] = (612, 792), user_password: str | None = None) -> bytes:
    """A PDF 1.4 file with Helvetica text on each page. With ``user_password`` it is encrypted (standard security handler, revision 2,
    40-bit RC4): the streams are encrypted, an empty password does not open it."""
    doc_id = hashlib.md5(b"kidney-health lab_pdf.py").digest()
    n_pages = len(pages)
    page_ids = [4 + 2 * i for i in range(n_pages)]
    encrypt_id = 4 + 2 * n_pages
    key = b""
    encrypt_dict = b""
    if user_password is not None:
        up = (user_password.encode("latin-1") + _PAD)[:32]
        owner = hashlib.md5((b"owner-only secret" + _PAD)[:32]).digest()[:5]
        o_value = _rc4(owner, up)
        p_value = -44
        key = hashlib.md5(up + o_value + struct.pack("<i", p_value) + doc_id).digest()[:5]
        u_value = _rc4(key, _PAD)
        encrypt_dict = (f"<< /Filter /Standard /V 1 /R 2 /O <{o_value.hex()}> /U <{u_value.hex()}> /P {p_value} >>").encode("ascii")
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: ("<< /Type /Pages /Count %d /Kids [%s] >>" % (n_pages, " ".join(f"{i} 0 R" for i in page_ids))).encode("ascii"),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for lines, page_id in zip(pages, page_ids, strict=True):
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] /Resources << /Font << /F1 3 0 R >> >> "
                            f"/Contents {page_id + 1} 0 R >>").encode("ascii")
        data = page_content(lines) if lines else b""
        if user_password is not None:
            data = _rc4(hashlib.md5(key + struct.pack("<I", page_id + 1)[:3] + b"\x00\x00").digest()[:10], data)
        objects[page_id + 1] = b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"
    if user_password is not None:
        objects[encrypt_id] = encrypt_dict
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"
    xref = len(out)
    top = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % top
    for number in range(1, top):
        out += b"%010d 00000 n \n" % offsets[number]
    trailer = f"trailer\n<< /Size {top} /Root 1 0 R /ID [<{doc_id.hex()}> <{doc_id.hex()}>]"
    if user_password is not None:
        trailer += f" /Encrypt {encrypt_id} 0 R"
    out += (trailer + f" >>\nstartxref\n{xref}\n%%EOF\n").encode("ascii")
    return bytes(out)


REPORT = make_pdf([
    ["Harness Clinic Laboratory", "Potassium   5.4 mmol/L   2026-10-07", "Phosphate   1.2 mmol/L   2026-10-07", "Sodium 139 mmol/L", "Chloride 101 mmol/L"],
    ["Harness Clinic Laboratory, page 2", "eGFR   58 mL/min/1.73m2   2026-10-07", "Creatinine   88 umol/L", "Potassium   5.4 mmol/L   2026-10-07"],
])
ENCRYPTED = make_pdf([["Protected report", "Potassium 5.4 mmol/L"]], user_password="secret")
FIFTY_ONE = make_pdf([[] for _ in range(51)], size=(200, 200))
DAMAGED = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R\n"  # cut off: no pages, no trailer
NOT_A_PDF = b"This is a text file that was named .pdf by mistake.\n"
TOO_BIG = b"%PDF-1.4\n" + b"0" * (21 * MB)


# --------------------------------------------------------------------------- the fake local AI: scripted answers for lab report photos

def jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        if marker in (0xD9, 0xDA):
            return None
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def row(analyte: str, value: float, unit: str, taken_on: str | None = "2026-10-07") -> dict[str, Any]:
    return {"analyte": analyte, "value": value, "unit": unit, "taken_on": taken_on}


PAGE_ONE = {"status": "ok", "rows": [row("potassium", 5.4, "mmol/L"), row("phosphate", 1.2, "mmol/L")]}
# page two repeats page one's potassium; its creatinine has no date on the report
PAGE_TWO = {"status": "ok", "rows": [row("potassium", 5.4, "mmol/L"), row("egfr", 58, "mL/min/1.73m2"), row("creatinine", 88, "umol/L", None)]}


class LabAi(FakeAi):
    """The fake OpenAI-compatible server of device.py, plus: the n-th lab report request gets ``queue[n]`` (after ``delays[n]`` seconds),
    and what each one was sent is kept (the JPEGs' size, EXIF, and a hash)."""

    def __init__(self, port: int) -> None:
        super().__init__(port)
        self.lab_requests: list[dict[str, Any]] = []
        self.queue: list[dict[str, Any]] = []
        self.delays: dict[int, float] = {}
        self.inflight = 0
        self._lock = threading.Lock()

    def reset(self, *answers: dict[str, Any], delays: dict[int, float] | None = None) -> None:
        self.lab_requests.clear()
        self.queue = list(answers)
        self.delays = dict(delays or {})

    def answer(self, body: dict[str, Any]) -> dict[str, Any]:
        text, images = self.texts(body)
        if not text.startswith("TASK: read_lab_report"):
            return super().answer(body)
        pictures = [base64.b64decode(url.split(",", 1)[1]) for url in images]
        with self._lock:
            n = len(self.lab_requests)
            self.lab_requests.append({"images": len(pictures), "sizes": [jpeg_size(p) for p in pictures], "exif": [jpeg_has_exif(p) for p in pictures],
                                      "jpeg": [p[:3] == b"\xff\xd8\xff" for p in pictures], "sha": [hashlib.sha256(p).hexdigest() for p in pictures],
                                      "bytes": [len(p) for p in pictures]})
            self.inflight += 1
        try:
            time.sleep(self.delays.get(n, 0))
            return self.queue[n] if n < len(self.queue) else {"status": "unreadable", "rows": []}
        finally:
            with self._lock:
                self.inflight -= 1

    def idle(self, timeout: float = 20) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.inflight == 0:
                return True
            time.sleep(0.1)
        return False


# --------------------------------------------------------------------------- what the page sent (kept by a script in the page)

SPY = """(() => {
  // Every body the page hands to fetch, XMLHttpRequest and sendBeacon: whether it starts with "%PDF-"; and the JPEG Blobs of the lab report route.
  window.__khBodies = []; window.__khLabUploads = [];
  const note = (url, body) => {
    let kind = body === undefined || body === null ? 'none' : (body instanceof Blob ? 'blob' : (typeof body === 'string' ? 'string' : (body instanceof ArrayBuffer || ArrayBuffer.isView(body) ? 'bytes' : typeof body)));
    const entry = { url: String(url), kind, size: body && (body.size || body.byteLength || body.length) || 0, pdf: false };
    const head = (bytes) => { try { return new TextDecoder().decode(bytes.slice(0, 5)) === '%PDF-'; } catch (e) { return false; } };
    if (kind === 'string') entry.pdf = body.startsWith('%PDF-');
    else if (kind === 'bytes') entry.pdf = head(new Uint8Array(body.buffer || body));
    else if (kind === 'blob') entry.pdf = body.type === 'application/pdf';
    window.__khBodies.push(entry);
  };
  const original = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    note(url, init && init.body);
    if (url.includes('/api/ai/read-lab-report') && !url.includes('dry_run') && init && init.body instanceof Blob) window.__khLabUploads.push(init.body);
    return original.apply(this, arguments);
  };
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (body) { note('xhr', body); return send.apply(this, arguments); };
  if (navigator.sendBeacon) { const beacon = navigator.sendBeacon.bind(navigator); navigator.sendBeacon = (url, data) => { note(url, data); return beacon(url, data); }; }
})();"""

ANALYSE = """async () => Promise.all(window.__khLabUploads.map(async (b) => {
  const bytes = new Uint8Array(await b.arrayBuffer());
  const bmp = await createImageBitmap(b);
  const c = document.createElement('canvas'); c.width = bmp.width; c.height = bmp.height;
  const g = c.getContext('2d'); g.drawImage(bmp, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let dark = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 110) dark += 1;
  return { type: b.type, size: b.size, w: bmp.width, h: bmp.height, dark: dark / (c.width * c.height), head: Array.from(bytes.slice(0, 3)),
           pdf: new TextDecoder().decode(bytes.slice(0, 5)) === '%PDF-' };
}))"""


# --------------------------------------------------------------------------- the walk

def overflow(page: Page) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def text_of(page: Page, selector: str) -> str:
    return " ".join(page.inner_text(selector).split())


def pick(page: Page, name: str, data: bytes, mime: str = "application/pdf") -> None:
    page.set_input_files("#lab-photo-file", {"name": name, "mimeType": mime, "buffer": data})


def card_shot(hx: Harness, page: Page, name: str) -> None:
    """A picture of the card (the page itself would show only the top of Labs)."""
    card = page.locator("#lab-photo")
    card.scroll_into_view_if_needed()
    card.screenshot(path=str(hx.shots / f"{name}.png"))


def rows_of(page: Page) -> list[str]:
    return [" ".join(t.split()) for t in page.locator("#lab-photo-results .lab-photo-list > li").all_inner_texts()]


class Recorder:
    """What the page asked the network for, and the Workers it made."""

    def __init__(self, ctx: Any, page: Page) -> None:
        self.requests: list[tuple[str, str, str]] = []
        self.workers: list[dict[str, Any]] = []
        ctx.on("request", lambda r: self.requests.append((r.method, urlsplit(r.url).path, r.headers.get("content-type", ""))))
        page.on("worker", self._worker)

    def _worker(self, worker: Any) -> None:
        entry = {"url": urlsplit(worker.url).path, "closed": False}
        self.workers.append(entry)
        worker.on("close", lambda _w=None: entry.update(closed=True))

    def pdfjs_paths(self) -> set[str]:
        return {path for _m, path, _t in self.requests if path.startswith(PDFJS_DIR)}

    def lab_posts(self) -> list[tuple[str, str, str]]:
        return [r for r in self.requests if r[0] == "POST" and r[1] == "/api/ai/read-lab-report"]


def walk(hx: Harness, ai: LabAi, provider_id: int, tag: str, width: int, height: int, scheme: str, sw: bool) -> None:
    ctx, watch = hx.context(width=width, height=height, scheme=scheme, service_workers="allow" if sw else "block", init=SPY)
    page = ctx.new_page()
    rec = Recorder(ctx, page)
    dialogs: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    watch.expect("/api/ai/read-lab-report", 409)  # the consent sheet's first answer
    # a fresh start for this walk: no consent to the local AI for lab reports, nothing saved, the fake quiet
    hx.admin.call("DELETE", f"/api/ai/consent/{provider_id}", params={"purpose": "labs"})
    for item in hx.admin.json("GET", "/api/labs").get("labs", []):
        hx.admin.call("DELETE", f"/api/labs/{item['id']}")
    ai.reset()
    try:
        page.goto(f"{hx.base}/#labs")
        wait_js(page, "!!document.querySelector('#lab-photo') && !document.querySelector('#lab-photo').hidden && !document.querySelector('#lab-photo-controls').hidden")
        if sw:
            try:
                wait_js(page, "!!navigator.serviceWorker && !!navigator.serviceWorker.controller", 8000)
            except TimeoutError:
                page.reload()  # the worker installed on the first visit controls the page from the next one
                wait_js(page, "!!navigator.serviceWorker && !!navigator.serviceWorker.controller", 15000)
                wait_js(page, "!document.querySelector('#lab-photo').hidden && !document.querySelector('#lab-photo-controls').hidden")
            check(f"[{tag}] the service worker controls the page", True)

        # 1. The card
        card = text_of(page, "#lab-photo")
        check(f"[{tag}] the card says a PDF works too", "Read a lab report photo or PDF" in card and "choose the PDF from your lab's website" in card, card[:300])
        check(f"[{tag}] the file input takes images and PDFs", page.get_attribute("#lab-photo-file", "accept") == "image/*,application/pdf,.pdf")
        check(f"[{tag}] before a file is chosen there is no page list and no Cancel", page.is_hidden("#lab-photo-pages") and page.is_hidden("#lab-photo-cancel"))

        # 2. Choose the report: its pages are listed here, nothing is sent
        before = len(rec.lab_posts())
        pick(page, "lab-report.pdf", REPORT)
        wait_js(page, "document.querySelectorAll('#lab-photo-pages input[type=checkbox]').length === 2")
        listed = text_of(page, "#lab-photo-pages")
        ticks = page.evaluate("[...document.querySelectorAll('#lab-photo-pages input[type=checkbox]')].map((c) => c.checked)")
        check(f"[{tag}] choosing the PDF lists Page 1 and Page 2, both ticked", ticks == [True, True] and "Page 1" in listed and "Page 2" in listed
              and "this PDF has 2 pages" in listed, listed)
        check(f"[{tag}] the list says each page is drawn here and sent as a picture, the PDF is not sent", PDF_LINE in listed
              and "Reading a page takes a while on your own AI; choose the pages with results." in listed, listed)
        check(f"[{tag}] choosing a PDF sent nothing to the server or the AI", len(rec.lab_posts()) == before and not ai.lab_requests)
        check(f"[{tag}] pdf.js and its worker came from /vendor/ and nothing else was fetched for it", rec.pdfjs_paths() == PDFJS_FILES, str(rec.pdfjs_paths()))
        check(f"[{tag}] the page list is open on this device only: one worker, the vendored one",
              [w["url"] for w in rec.workers] == [PDFJS_DIR + "pdf.worker.min.mjs"], str(rec.workers))
        check(f"[{tag}] the page list has no sideways scroll and stays inside the screen", not overflow(page)
              and page.evaluate("document.querySelector('#lab-photo-pages').getBoundingClientRect().right <= window.innerWidth"))
        card_shot(hx, page, f"pages-{tag}")

        # 3. Read: the consent sheet, then page by page
        page.click("#lab-photo-read")
        page.wait_for_selector("#sheet-ai-consent[open]")
        sheet = text_of(page, "#sheet-ai-consent")
        check(f"[{tag}] the consent sheet is the lab report one and adds the line about the pages", PDF_LINE in sheet and "date of birth and record numbers" in sheet and "Crop the photo to the results table" in sheet, sheet)
        check(f"[{tag}] nothing was sent before 'Agree and send'", not ai.lab_requests)
        hx.shot(page, f"consent-{tag}")
        ai.reset(PAGE_ONE, PAGE_TWO)
        page.click("#sheet-ai-consent >> text=Agree and send")
        wait_js(page, "!!document.querySelector('#lab-photo-results .lab-photo-list')", 40000)
        check(f"[{tag}] the AI got one request per ticked page, each with one JPEG", len(ai.lab_requests) == 2
              and all(r["images"] == 1 and r["jpeg"] == [True] for r in ai.lab_requests), json.dumps(ai.lab_requests)[:400])
        sizes = [r["sizes"][0] for r in ai.lab_requests if r["sizes"] and r["sizes"][0]]
        check(f"[{tag}] each picture is a page: within 2048 px, the page's proportions (Letter), no camera data",
              len(sizes) == 2 and all(max(w, h) <= 2048 and abs(w / h - 612 / 792) < 0.01 for w, h in sizes)
              and all(not any(r["exif"]) for r in ai.lab_requests), f"{sizes} {[r['exif'] for r in ai.lab_requests]}")
        check(f"[{tag}] the two pictures are different", ai.lab_requests[0]["sha"] != ai.lab_requests[1]["sha"])
        pictures = page.evaluate(ANALYSE)
        distinct = {(p["size"], p["w"], p["h"]) for p in pictures}
        check(f"[{tag}] the pages were really drawn (dark text and rules on white), as JPEGs, not the PDF",
              len(distinct) == 2 and all(p["type"] == "image/jpeg" and p["head"] == [255, 216, 255] and not p["pdf"] and 0.002 < p["dark"] < 0.5 for p in pictures),
              json.dumps(pictures)[:500])
        bodies = page.evaluate("window.__khBodies")
        check(f"[{tag}] nothing the page sent starts with %PDF- or has the PDF's type", not any(b["pdf"] for b in bodies) and bodies, json.dumps(bodies)[:400])
        check(f"[{tag}] every request to the lab report route was a JPEG", all(t == "image/jpeg" for _m, _p, t in rec.lab_posts()), str(rec.lab_posts()))
        check(f"[{tag}] the reading's worker is closed once the run ended", rec.workers and all(w["closed"] for w in rec.workers), str(rec.workers))

        # 4. One table: page numbers, the repeat shown once, unticked, a row without a date waits for one
        rows = rows_of(page)
        check(f"[{tag}] four rows: potassium and phosphate from page 1, eGFR and creatinine from page 2 (page 2's potassium was the same as page 1's)",
              len(rows) == 4 and "Potassium" in rows[0] and "page 1 of your PDF" in rows[0] and "Phosphate" in rows[1] and "page 1 of your PDF" in rows[1]
              and "page 2 of your PDF" in rows[2] and "page 2 of your PDF" in rows[3], str(rows))
        summary = text_of(page, "#lab-photo-results .lab-import-summary")
        notes = text_of(page, "#lab-photo-results")
        check(f"[{tag}] the summary and the notice say PDF, none is ticked, the repeat is explained",
              summary.startswith("4 results read from your PDF. None is ticked") and "Read by AI from the pages of your PDF that you ticked." in notes
              and "1 result was the same as one already shown, so it is shown once." in notes, summary + " | " + notes[:300])
        ticked = page.evaluate("[...document.querySelectorAll('#lab-photo-results .lab-photo-list input[type=checkbox]')].map((c) => c.checked)")
        check(f"[{tag}] every row starts unticked, the row without a date cannot be ticked yet",
              ticked == [False] * 4 and page.is_disabled("#lab-photo-row-3") and "Date needed" in rows[3], str(ticked))
        check(f"[{tag}] the results have no sideways scroll", not overflow(page))
        card_shot(hx, page, f"results-{tag}")

        # 5. The date, the ticks, Save: the ordinary labs import saves what was ticked
        page.fill("#lab-photo-row-3-date", "2026-10-07")
        for index in range(4):
            page.check(f"#lab-photo-row-{index}")
        check(f"[{tag}] Save counts the four ticked rows", page.inner_text("#lab-photo-save") == "Save 4 results")
        page.click("#lab-photo-save")
        wait_js(page, "document.querySelector('#lab-photo-results').textContent.includes('Saved 4 results')")
        saved = hx.admin.json("GET", "/api/labs").get("labs", [])
        by = {s["analyte"]: s for s in saved}
        check(f"[{tag}] the server holds exactly those four results", sorted(by) == ["creatinine", "egfr", "phosphate", "potassium"] and len(saved) == 4,
              json.dumps([(s["analyte"], s["value"], s["taken_on"]) for s in saved]))
        check(f"[{tag}] after Save the page list is gone and the file is forgotten",
              page.is_hidden("#lab-photo-pages") and page.evaluate("document.querySelector('#lab-photo-file').value === ''"))
        card_shot(hx, page, f"saved-{tag}")

        # 6. Cancel while page 2 is being read: the request is aborted, page 1's rows stay
        for item in hx.admin.json("GET", "/api/labs").get("labs", []):
            hx.admin.call("DELETE", f"/api/labs/{item['id']}")
        ai.reset(PAGE_ONE, PAGE_TWO, delays={1: 6})
        pick(page, "lab-report.pdf", REPORT)
        wait_js(page, "document.querySelectorAll('#lab-photo-pages input[type=checkbox]').length === 2")
        page.click("#lab-photo-read")
        wait_js(page, "document.querySelector('#lab-photo-progress').textContent.startsWith('Reading page 2 of 2')", 40000)
        deadline = time.monotonic() + 15
        while len(ai.lab_requests) < 2 and time.monotonic() < deadline:
            time.sleep(0.1)
        check(f"[{tag}] while page 2 is read, Cancel is shown and the page boxes are locked",
              page.is_visible("#lab-photo-cancel") and page.is_disabled("#lab-photo-read")
              and page.evaluate("[...document.querySelectorAll('#lab-photo-pages input[type=checkbox]')].every((c) => c.disabled)"))
        watch.expected_failures.add(("/api/ai/read-lab-report", "net::ERR_ABORTED"))
        page.click("#lab-photo-cancel")
        wait_js(page, "document.querySelector('#lab-photo-results').textContent.includes('Stopped.')")
        stopped = text_of(page, "#lab-photo-results")
        check(f"[{tag}] Cancel stopped between pages and kept page 1's rows",
              "Stopped. These results are from 1 page read before you pressed Cancel." in stopped and len(rows_of(page)) == 2
              and "page 1 of your PDF" in rows_of(page)[0], stopped[:300])
        check(f"[{tag}] after Cancel: Cancel hidden, the button back, the worker closed", page.is_hidden("#lab-photo-cancel")
              and page.inner_text("#lab-photo-read") == "Read the report" and not page.is_disabled("#lab-photo-read")
              and all(w["closed"] for w in rec.workers), str(rec.workers))
        check(f"[{tag}] the AI had been asked for page 2 (its answer comes late and nobody waits for it)", len(ai.lab_requests) == 2)
        check(f"[{tag}] the fake AI's slot is free again", ai.idle(20))
        time.sleep(0.5)
        card_shot(hx, page, f"cancelled-{tag}")
        page.click("#lab-photo-discard")
        check(f"[{tag}] Discard lets the file and the list go", page.is_hidden("#lab-photo-pages") and page.evaluate("document.querySelector('#lab-photo-file').value === ''"))

        # 7. Files that cannot be used
        sent = len(ai.lab_requests)
        refusals = [
            ("not a PDF", "notes.pdf", NOT_A_PDF, "That file is not a PDF."),
            ("damaged", "damaged.pdf", DAMAGED, "This PDF could not be read. Download it again, or take a screenshot of each page."),
            ("password-protected", "protected.pdf", ENCRYPTED, "This PDF has a password. Open it on your device and take a screenshot of each page instead."),
            ("51 pages", "long.pdf", FIFTY_ONE, "This PDF has more than 50 pages. Take screenshots of the pages with your results."),
            ("21 MB", "huge.pdf", TOO_BIG, "That PDF is 21.0 MB; the largest this app reads is 20 MB."),
        ]
        for label, name, data, message in refusals:
            pick(page, name, data)
            try:
                wait_js(page, "document.querySelector('#lab-photo-error').textContent.trim().length > 0")
            except TimeoutError:
                pass
            shown = text_of(page, "#lab-photo-error")
            check(f"[{tag}] a {label} file: {message}", shown == message, shown)
            check(f"[{tag}] a {label} file: no page list, the choice forgotten", page.is_hidden("#lab-photo-pages")
                  and page.evaluate("document.querySelector('#lab-photo-file').value === ''"))
            if label == "damaged":
                card_shot(hx, page, f"refused-{tag}")
        check(f"[{tag}] none of them sent anything to the AI", len(ai.lab_requests) == sent)
        check(f"[{tag}] every worker made was closed", all(w["closed"] for w in rec.workers), str(rec.workers))
        check(f"[{tag}] the refusals have no sideways scroll", not overflow(page))

        # 8. The whole walk
        check(f"[{tag}] pdf.js asked for its library and its worker and for nothing else under /vendor/pdfjs-dist-6.4.299/",
              rec.pdfjs_paths() == PDFJS_FILES, str(rec.pdfjs_paths()))
        others = sorted({path for _m, path, _t in rec.requests if "wasm" in path or "cmap" in path.lower() or "standard_fonts" in path or path.endswith((".pfb", ".ttf", ".woff", ".woff2"))})
        check(f"[{tag}] no WebAssembly, CMap or font file was requested", not others, str(others))
        check(f"[{tag}] one Worker for each of the three runs that opened the PDF (choose, then each Read), each the vendored worker, all closed",
              rec.workers and all(w["url"] == PDFJS_DIR + "pdf.worker.min.mjs" and w["closed"] for w in rec.workers), str(rec.workers))
        if sw:
            keys = page.evaluate("caches.keys().then((ks) => ks.filter((k) => k.startsWith('kdl-vendor-')))")
            cached = page.evaluate("""async () => { const out = []; for (const k of await caches.keys()) { if (!k.startsWith('kdl-vendor-')) continue;
                const c = await caches.open(k); for (const r of await c.keys()) out.push(new URL(r.url).pathname); } return out; }""")
            check(f"[{tag}] the service worker kept pdf.js and its worker in its /vendor/ cache", keys and PDFJS_FILES <= set(cached), f"{keys} {cached}")
        check(f"[{tag}] no dialog was shown", not dialogs, str(dialogs))
    finally:
        problems = watch.take()
        check(f"[{tag}] no CSP or Trusted Types violation, console or page error, failed request or request to another host", not problems, "; ".join(problems[:6]))
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
        with LabAi(args.ai_port) as ai:
            server.start()
            admin = first_admin(server, "labpdf")
            admin.json("PATCH", "/api/me/ai", {"opt_in": True})
            provider_id = next(p["id"] for p in admin.json("GET", "/api/admin/ai-providers")["providers"] if p["locked"])
            base = f"http://localhost:{args.port}"
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
                hx = Harness(browser, server, admin, out, base)
                try:
                    for tag, width, height, scheme, sw in (("375-light", 375, 812, "light", False), ("1280-dark-sw", 1280, 800, "dark", True)):
                        try:
                            walk(hx, ai, provider_id, tag, width, height, scheme, sw)
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
