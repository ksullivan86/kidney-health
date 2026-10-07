#!/usr/bin/env python3
"""Barcodes, label photos, AI cards and the offline outbox in a real browser (note 03 R7–R9, R11; note 02 R5, R7).

    python tools/e2e/device.py                                  # every section
    python tools/e2e/device.py --only outbox,live --port 8370 --ai-port 8371 --out /tmp/kh-device

Starts ``uvicorn app.main:app`` (khserver.Server) with a fresh DATA_DIR, AI switched on and an env provider that
points at a fake OpenAI-compatible server this harness runs on ``--ai-port`` (listed in ``AI_PRIVATE_HOSTS``), finishes
first-run setup through the API, and drives headless Chromium on ``http://localhost:<port>`` (a secure context, so
the service worker and the camera are allowed):

* ``photo``    a generated EAN-13 image through "Photo of a barcode" with the vendored WebAssembly decoder (Linux
               Chromium has no native BarcodeDetector): decoded on the page, looked up (the person's own food with
               that barcode), reviewed in the entry sheet (potassium additive warning, "not listed", provenance) and
               logged; the 1 MB reader came from /vendor/, nothing from another origin.
* ``native``   the same through the native-detector branch: a stand-in ``window.BarcodeDetector`` (it decodes with
               the vendored reader and answers like Chrome on Android: UPC-A as 12 digits, ``upc_a``).
* ``live``     live scanning with Chromium's fake camera (``--use-file-for-fake-video-capture`` with a generated
               .y4m showing an EAN-13): two identical reads, lookup, entry sheet, camera tracks stopped; then the
               4-second no-frame watchdog with a camera that delivers no frames; then the plain-HTTP note.
* ``outbox``   with the service worker in control: an entry logged with the network off (context.set_offline), a
               reload while offline (the app starts from this device's copies, the entry shows "waiting to sync"),
               reconnect, synced once; a lost batch response (the server got it, the page did not) synced again
               without a second row; an item the server refuses shown with Retry/Discard; sign-out asks first.
* ``ai``       Settings → AI ideas (opt in), AI meal ideas with consent and "What will be sent?", the cards labelled
               and next to the rule-based list, text only; Quick add's label photo beside the form, "Read the label
               for me": the browser sends a JPEG ≤ 1600 px without EXIF, fields marked "from photo", logged.
* ``demo``     ``/?mock=1``: the demo's three recorded products (consent, attribution link, quality notes), a
               barcode it does not know → "Enter from the label" with the number, the outbox against the demo API.
* ``firstvisit`` three fresh browser profiles opened straight at ``/#settings`` with the service worker allowed:
               while the first visit's worker takes control (js/pwa.js re-renders Settings → This device, possibly
               twice), the section is drawn once: one "Works offline" row that ends on "Yes", one "Entries waiting to
               sync" list, one "Clear offline data" button, no duplicate ids anywhere on the page.
* ``shots``    the new screens at 375×812 and 1280×800, light and dark (scan sheet, entry sheet with provenance,
               Quick add with the photo beside the form, Today with a waiting entry, Settings → This device) with
               layout checks (no horizontal overflow, 44 px tap targets).

Fails (exit status 1) on any ``securitypolicyviolation`` (CSP or Trusted Types), page error, console error, failed
request or request to another origin that a step did not expect, and on every failed check. Writes
``<out>/report.json`` and screenshots in ``<out>/shots/``; the server, the fake AI server and the browsers are always
stopped. What it cannot show: a real phone camera, iOS Safari, a real native BarcodeDetector, a live AI provider.
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import tempfile
import threading
import time
import traceback
import zlib
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

import khserver
from khserver import chromium_executable

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "device"
PORT = 8066
AI_PORT = 8067
TIMEOUT_MS = 20_000
SECTIONS = ("photo", "native", "live", "outbox", "firstvisit", "iostip", "ai", "demo", "shots")
RESULTS: list[dict[str, Any]] = []
TODAY = date.today().isoformat()

# The barcodes the harness prints (valid GS1 check digits; retail ranges).
CRACKERS = "4006381333931"  # a custom food with a potassium additive and no potassium value
COLA = "0049000028911"  # UPC-A 049000028911 as EAN-13; a native detector reports it as upc_a, 12 digits


def check(area: str, name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"area": area, "check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} [{area}] {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


# --------------------------------------------------------------------------- images: EAN-13, PNG, Y4M, JPEG

L_CODES = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")
G_CODES = ("0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111")
R_CODES = ("1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100")
PARITY = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")


def ean13_modules(code: str) -> str:
    """The 95 modules (1 = bar) of an EAN-13 symbol."""
    assert len(code) == 13 and code.isdigit()
    bits = "101"
    for digit, parity in zip(code[1:7], PARITY[int(code[0])]):
        bits += (L_CODES if parity == "L" else G_CODES)[int(digit)]
    bits += "01010"
    for digit in code[7:]:
        bits += R_CODES[int(digit)]
    return bits + "101"


def barcode_image(code: str, width: int, height: int, module: int) -> bytes:
    """A grayscale image (row-major bytes, white background) with the barcode in the middle."""
    bits = ean13_modules(code)
    bar_w = len(bits) * module
    left = (width - bar_w) // 2
    top, bottom = height // 4, height * 3 // 4
    row_bar = bytearray([255] * width)
    for i, bit in enumerate(bits):
        if bit == "1":
            row_bar[left + i * module:left + (i + 1) * module] = bytes([0] * module)
    blank = bytes([255] * width)
    return b"".join(bytes(row_bar) if top <= y < bottom else blank for y in range(height))


def png_gray(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + pixels[y * width:(y + 1) * width] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def y4m(width: int, height: int, pixels: bytes, frames: int = 20) -> bytes:
    """A YUV4MPEG2 4:2:0 video of a still grayscale image (Chromium's fake camera loops it)."""
    chroma = bytes([128] * ((width // 2) * (height // 2)))
    header = f"YUV4MPEG2 W{width} H{height} F15:1 Ip A1:1 C420jpeg\n".encode()
    return header + b"".join(b"FRAME\n" + pixels + chroma + chroma for _ in range(frames))


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first SOF0/1/2 segment of a JPEG."""
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + length
    return None


def jpeg_has_exif(data: bytes) -> bool:
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: no more metadata segments
            return False
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            return True
        i += 2 + length
    return False


def with_exif(jpeg: bytes) -> bytes:
    """``jpeg`` with an APP1 Exif segment (a GPS tag's bytes) right after SOI: what a phone camera writes."""
    payload = b"Exif\x00\x00" + b"MM\x00\x2a\x00\x00\x00\x08" + b"GPS 51.5007N 0.1246W".ljust(64, b"\x00")
    return jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + jpeg[2:]


# --------------------------------------------------------------------------- the fake OpenAI-compatible provider

class FakeAi:
    """``/v1/models`` and ``/v1/chat/completions``; answers by the task in the prompt; remembers what it got."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, obj: Any, status: int = 200) -> None:
                raw = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                if self.path.endswith("/models"):
                    self._send({"object": "list", "data": [{"id": "fake-text", "object": "model"}, {"id": "fake-vision", "object": "model"}]})
                else:
                    self._send({"error": {"message": "not found"}}, 404)

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.requests.append(body)
                content = json.dumps(outer.answer(body))
                if FakeAi.texts(body)[0].startswith("TASK: next_meal"):
                    # The v0.3.0 review's case (L4): dosing prose before the JSON. The card must stay clean and the
                    # AI activity must show this raw answer captioned, with the words masked.
                    content = "Sure! Take 6 units of insulin before this meal. " + content
                self._send({"id": "fake", "object": "chat.completion", "model": body.get("model"),
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 900, "completion_tokens": 60}})

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @staticmethod
    def texts(body: dict[str, Any]) -> tuple[str, list[str]]:
        """The user turn's text and its data: URLs (photos)."""
        content = body["messages"][-1]["content"]
        if isinstance(content, str):
            return content, []
        text = " ".join(part.get("text", "") for part in content if part.get("type") == "text")
        images = [part["image_url"]["url"] for part in content if part.get("type") == "image_url"]
        return text, images

    def answer(self, body: dict[str, Any]) -> dict[str, Any]:
        text, _images = self.texts(body)
        if text.startswith("Reply with the JSON object"):
            return {"ok": "yes"}
        if "What colour is this square" in text:
            return {"color": "red"}
        data: dict[str, Any] = {}
        if "<data>" in text:
            raw = text.split("<data>\n", 1)[1].split("\n</data>", 1)[0]
            data = json.loads(raw.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        if text.startswith("TASK: next_meal"):
            c = data.get("candidates") or []
            ideas = [{"theme": "light", "items": [{"food_id": c[0]["id"], "quarters": c[0]["portion_quarters"]}],
                      "reason_codes": ["low_potassium"], "handbook": []}] if c else []
            if len(c) > 2:
                ideas.append({"theme": "hearty", "items": [{"food_id": c[1]["id"], "quarters": c[1]["portion_quarters"]},
                                                            {"food_id": c[2]["id"], "quarters": c[2]["portion_quarters"]}],
                              "reason_codes": ["fits_carb_goal"], "handbook": []})
            return {"status": "ok", "refusal": "none", "ideas": ideas}
        if text.startswith("TASK: rerank"):
            # Two real refs in reverse order and one the rules never offered (left out: "not_a_candidate").
            refs = [c["ref"] for c in data.get("candidates") or []]
            return {"status": "ok", "refusal": "none",
                    "order": [{"ref": r, "reason_codes": ["low_potassium"]} for r in refs[:2][::-1]]
                    + [{"ref": "zz", "reason_codes": ["low_potassium"]}]}
        if text.startswith("TASK: identify_food"):
            return {"status": "ok", "items": [
                {"name": "banana", "search": "banana", "grams_estimate": 118, "confidence": "high"},
                {"name": "brown sauce", "search": "gravy", "grams_estimate": 30, "confidence": "low"}]}
        if text.startswith("TASK: read_label"):
            return {"status": "ok", "product_name": "Harness rye crackers", "serving_text": "5 crackers (30 g)", "serving_g": 30,
                    "basis": "per_serving",
                    "per_serving": {"calories_kcal": 140, "protein_g": 2, "fat_g": 6, "sat_fat_g": 1, "carbs_g": 19, "fiber_g": 1,
                                    "sugar_g": 2, "sodium_mg": 230, "potassium_mg": None, "phosphorus_mg": None, "calcium_mg": 20},
                    "salt_g": None, "percent_dv": {"sodium": 10, "potassium": None, "phosphorus": None, "calcium": 2},
                    "ingredients_text": "Rye flour, sunflower oil, salt, sodium acid pyrophosphate", "label_style": "us_nutrition_facts"}
        return {"status": "refused", "refusal": "outside_scope", "ideas": []}

    def __enter__(self) -> "FakeAi":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------- watching a browser context

WATCH_SCRIPT = """
document.addEventListener('securitypolicyviolation', (e) => {
  window.__khViolation({ directive: e.violatedDirective, blocked: e.blockedURI, source: e.sourceFile, line: e.lineNumber, sample: e.sample });
});
"""


class Watch:
    """Problems in one context: CSP/TT violations, page errors, console errors, failed or outside requests, HTTP errors
    a step did not ask for (``expect``), network failures while the step said the browser is offline (``offline``)."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.problems: list[str] = []
        self.expected: set[tuple[str, int]] = set()
        self.expected_failures: set[tuple[str, str]] = set()  # (path, failure) a step causes on purpose, once each
        self._offline = False
        self._online_since = 0.0

    @property
    def offline(self) -> bool:
        """True while a step has the browser offline, and for a few seconds after: a request started just
        before the switch reports its "disconnected" failure a moment later."""
        return self._offline or time.monotonic() - self._online_since < 3.0

    @offline.setter
    def offline(self, value: bool) -> None:
        if self._offline and not value:
            self._online_since = time.monotonic()
        self._offline = value

    def attach(self, context: Any) -> None:
        context.expose_binding("__khViolation", lambda _src, v: self.problems.append(f"CSP violation: {json.dumps(v)}"))
        context.add_init_script(WATCH_SCRIPT)
        context.on("request", self._request)
        context.on("requestfailed", self._failed)
        context.on("response", self._response)
        context.on("page", lambda page: (page.on("pageerror", lambda e: self.problems.append(f"page error: {e}")),
                                         page.on("console", self._console)))

    def expect(self, path: str, status: int) -> None:
        self.expected.add((path, status))

    def _console(self, message: Any) -> None:
        if message.type != "error":
            return
        if message.text.startswith("Failed to load resource"):
            return  # the response or requestfailed handler judges it
        self.problems.append(f"console error: {message.text}")

    def _request(self, request: Any) -> None:
        if urlsplit(request.url).scheme in ("data", "blob", "about", "chrome-extension"):
            return
        if not request.url.startswith(self.origin + "/"):
            self.problems.append(f"request to another origin: {request.url}")

    def _failed(self, request: Any) -> None:
        failure = request.failure or ""
        if self.offline and ("INTERNET_DISCONNECTED" in failure or "Failed to fetch" in failure):
            return
        if (urlsplit(request.url).path, failure) in self.expected_failures:
            self.expected_failures.discard((urlsplit(request.url).path, failure))
            return
        if "ERR_ABORTED" in failure and request.resource_type in ("media", "image"):
            return  # a <video>/<img> whose source the page replaced
        self.problems.append(f"request failed: {request.method} {request.url} ({failure})")

    def _response(self, response: Any) -> None:
        if response.status < 400:
            return
        path = urlsplit(response.url).path
        if (path, response.status) not in self.expected:
            self.problems.append(f"HTTP {response.status}: {response.request.method} {response.url}")

    def take(self) -> list[str]:
        out, self.problems = self.problems, []
        return out


class Harness:
    def __init__(self, browser: Any, server: khserver.Server, admin: khserver.Api, out: Path, base: str) -> None:
        self.browser = browser
        self.server = server
        self.admin = admin
        self.out = out
        self.shots = out / "shots"
        self.base = base  # http://localhost:<port>: a secure context

    def context(self, *, width: int = 1280, height: int = 800, scheme: str = "light", touch: bool = False, browser: Any = None,
                signed_in: bool = True, init: str | None = None, permissions: list[str] | None = None,
                service_workers: str = "block", user_agent: str | None = None) -> tuple[Any, Watch]:
        extra = {"user_agent": user_agent} if user_agent else {}
        ctx = (browser or self.browser).new_context(viewport={"width": width, "height": height}, color_scheme=scheme,
                                                    is_mobile=touch, has_touch=touch, service_workers=service_workers,
                                                    permissions=permissions or [], **extra)
        ctx.set_default_timeout(TIMEOUT_MS)
        watch = Watch(self.base)
        watch.attach(ctx)
        if init:
            ctx.add_init_script(init)
        if signed_in:
            ctx.add_cookies([{"name": k, "value": v, "url": self.base} for k, v in self.admin.cookies().items()])
        return ctx, watch

    def shot(self, page: Page, name: str, full: bool = False) -> None:
        page.screenshot(path=str(self.shots / f"{name}.png"), full_page=full)

    def api(self, method: str, path: str, body: Any = None) -> Any:
        return self.admin.json(method, path, body)

    def entries(self) -> list[dict[str, Any]]:
        return self.api("GET", f"/api/log?date={TODAY}")["entries"]


def wait_js(page: Page, expression: str, timeout: int = TIMEOUT_MS) -> Any:
    """Poll a JavaScript expression until it is truthy. (Playwright's wait_for_function evaluates strings with eval,
    which the app's CSP refuses; page.evaluate goes through the DevTools protocol, which the CSP does not govern.)"""
    deadline = time.monotonic() + timeout / 1000
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = page.evaluate(expression)
            if value:
                return value
        except Exception as exc:  # noqa: BLE001 - a navigation in between
            last = exc
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {expression}" + (f" ({last})" if last else ""))


def run_section(name: str, fn: Callable[[], None], page_getter: Callable[[], Page | None], shots: Path) -> None:
    try:
        fn()
    except Exception as exc:  # report and go on with the next section
        check(name, "section finished", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        page = page_getter()
        if page is not None:
            try:
                page.screenshot(path=str(shots / f"{name}-error.png"))
            except Exception:  # noqa: BLE001
                pass


def no_problems(area: str, watch: Watch) -> None:
    problems = watch.take()
    check(area, "no CSP/Trusted Types violations, page or console errors, failed or outside requests", not problems,
          "; ".join(problems[:15]))


def open_add(page: Page, base: str, hash_: str = "#add") -> None:
    page.goto(f"{base}/{hash_}")
    page.wait_for_selector("#view-add:not([hidden]) #btn-scan")


def search(page: Page, query: str) -> None:
    """Type a search and wait for its own answer (the list shown before it, for an empty query, may already
    hold a matching row; the search is debounced)."""
    with page.expect_response(lambda r: "/api/foods?" in r.url and f"q={query.replace(' ', '+')}" in r.url):
        page.fill("#food-search", query)
    page.wait_for_selector("#food-results .row-btn")


def scan_sheet(page: Page) -> None:
    page.click("#btn-scan")
    page.wait_for_selector("#sheet-scan[open]")


# --------------------------------------------------------------------------- sections

def section_photo(hx: Harness, state: dict[str, Any]) -> None:
    area = "photo (WebAssembly decoder)"
    hx.api("POST", "/api/foods", {"name": "Harness crackers", "serving_desc": "5 crackers (30 g)", "serving_g": 30,
                                  "nutrients": {"calories_kcal": 130, "carbs_g": 20, "sodium_mg": 180, "protein_g": 3},
                                  "gtin": CRACKERS, "ingredients_text": "wheat flour, sunflower oil, potassium chloride, salt"})
    image = hx.out / "ean13-crackers.png"
    image.write_bytes(png_gray(800, 500, barcode_image(CRACKERS, 800, 500, 4)))
    ctx, watch = hx.context(width=375, height=812, touch=True)
    page = ctx.new_page()
    state["page"] = page
    wasm: list[str] = []
    page.on("request", lambda r: wasm.append(r.url) if r.url.endswith(".wasm") else None)
    try:
        open_add(page, hx.base)
        check(area, "no native BarcodeDetector in this Chromium", page.evaluate("typeof window.BarcodeDetector") == "undefined")
        scan_sheet(page)
        page.set_input_files("#scan-file", str(image))
        page.wait_for_selector("#sheet-entry[open]")
        check(area, "the photo was decoded with the vendored WebAssembly reader", page.evaluate("KH.scan.decoder()") == "wasm")
        check(area, "the reader came from /vendor/zxing-wasm-3.1.3/", wasm == [f"{hx.base}/vendor/zxing-wasm-3.1.3/zxing_reader.wasm"], str(wasm))
        sheet = page.inner_text("#sheet-entry")
        check(area, "the entry sheet shows the scanned food", "Harness crackers" in sheet, sheet[:200])
        check(area, "the potassium additive warning is shown", "Contains a potassium additive; potassium not listed" in sheet, sheet[:400])
        check(area, "potassium reads 'not listed' in the numbers", "not listed" in page.inner_text("#entry-preview-key"))
        prov = page.inner_text("#sheet-entry-provenance")
        check(area, "the barcode and the additive behind the flag are shown", f"Barcode {CRACKERS}" in prov and "potassium chloride (E508)" in prov, prov)
        hx.shot(page, "photo-entry-375")
        page.click("#entry-save")
        page.wait_for_selector("#view-today:not([hidden])")
        names = [e["food_name"] for e in hx.entries()]
        check(area, "logged once on the server", names.count("Harness crackers") == 1, str(names))
        # A photo without a barcode: a clear sentence, no lookup.
        open_add(page, hx.base)
        scan_sheet(page)
        blank = hx.out / "blank.png"
        blank.write_bytes(png_gray(400, 300, bytes([255] * 400 * 300)))
        page.set_input_files("#scan-file", str(blank))
        wait_js(page, "document.querySelector('#scan-status').textContent.includes('No barcode was found')")
        check(area, "a photo without a barcode says so", True)
        # Typed digits: the check digit is caught on the device, the error sits under the field.
        page.fill("#scan-code", CRACKERS[:-1] + str((int(CRACKERS[-1]) + 1) % 10))
        page.click("#scan-go")
        page.wait_for_selector("#scan-code-error")
        described = page.get_attribute("#scan-code", "aria-describedby") or ""
        check(area, "a wrong check digit is explained under the field (aria-describedby, aria-invalid)",
              "scan-code-error" in described and page.get_attribute("#scan-code", "aria-invalid") == "true", described)
        page.fill("#scan-code", "2012345678903")  # an in-store code for weighed food
        page.click("#scan-go")
        wait_js(page, "document.querySelector('#scan-code-error').textContent.includes('store barcode')")
        check(area, "an in-store barcode is never looked up", True)
        page.keyboard.press("Escape")
    finally:
        no_problems(area, watch)
        ctx.close()


NATIVE_STANDIN = """
(() => {
  // A stand-in for Chrome-on-Android's BarcodeDetector: it decodes with the vendored reader and answers the way the
  // native one does (UPC-A as 12 digits with format upc_a; note 03 F5).
  class NativeBarcodeDetector {
    static async getSupportedFormats() { return ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'qr_code']; }
    constructor(options) { this.formats = (options && options.formats) || []; window.__nativeMade = (window.__nativeMade || 0) + 1; }
    async detect(source) {
      window.__nativeCalls = (window.__nativeCalls || 0) + 1;
      const API = window.BarcodeDetectionAPI;
      if (!this.inner) {
        await API.prepareZXingModule({ overrides: { locateFile: (p, pre) => (p.endsWith('.wasm') ? '/vendor/zxing-wasm-3.1.3/' + p : pre + p) }, fireImmediately: true });
        this.inner = new API.BarcodeDetector({ formats: ['ean_13'] });
      }
      const found = await this.inner.detect(source);
      return found.map((b) => (b.format === 'ean_13' && b.rawValue.startsWith('0') ? { ...b, format: 'upc_a', rawValue: b.rawValue.slice(1) } : b));
    }
  }
  Object.defineProperty(window, 'BarcodeDetector', { value: NativeBarcodeDetector, configurable: true, writable: true });
})();
"""


def ensure_cola(hx: Harness) -> None:
    """The person's own food with the cola's barcode (the server answers it locally, no provider needed)."""
    if not any(f["name"] == "Harness cola" for f in hx.api("GET", "/api/foods?q=harness%20cola")["foods"]):
        hx.api("POST", "/api/foods", {"name": "Harness cola", "serving_desc": "1 can (355 mL)", "serving_g": 355,
                                      "nutrients": {"calories_kcal": 0, "sodium_mg": 40}, "flags": ["counts_as_fluid"], "gtin": COLA})


def section_native(hx: Harness, state: dict[str, Any]) -> None:
    area = "photo (native detector branch)"
    ensure_cola(hx)
    image = hx.out / "ean13-cola.png"
    image.write_bytes(png_gray(800, 500, barcode_image(COLA, 800, 500, 4)))
    ctx, watch = hx.context(init=NATIVE_STANDIN)
    page = ctx.new_page()
    state["page"] = page
    try:
        open_add(page, hx.base)
        scan_sheet(page)
        page.set_input_files("#scan-file", str(image))
        page.wait_for_selector("#sheet-entry[open]")
        check(area, "the native detector was chosen (it reads EAN-13)", page.evaluate("KH.scan.decoder()") == "native")
        check(area, "the native detector decoded the photo", page.evaluate("window.__nativeCalls || 0") >= 1)
        check(area, "the 12-digit upc_a answer found the food (normalised on the server)", "Harness cola" in page.inner_text("#sheet-entry"))
        page.keyboard.press("Escape")
    finally:
        no_problems(area, watch)
        ctx.close()


# What the browser uploads to /api/vision/* (a Blob body: Chromium's DevTools does not report blob request bodies,
# so the harness keeps a reference to it before it is sent).
UPLOAD_SPY = """(() => {
  const original = window.fetch;
  window.__khUploads = [];
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.includes('/api/vision/') && !url.includes('dry_run') && init && init.body instanceof Blob) window.__khUploads.push(init.body);
    return original.apply(this, arguments);
  };
})();"""

NO_FRAMES = """
(() => {
  // A camera that starts and never shows a picture (WebKit bug 282327 in iOS home-screen apps).
  const real = navigator.mediaDevices && navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  if (real) navigator.mediaDevices.getUserMedia = async () => new MediaStream();
})();
"""
INSECURE = "Object.defineProperty(window, 'isSecureContext', { get: () => false });"


def section_live(hx: Harness, state: dict[str, Any], pw: Any) -> None:
    area = "live camera (fake device)"
    ensure_cola(hx)
    video = hx.out / "ean13-cola.y4m"
    video.write_bytes(y4m(640, 480, barcode_image(COLA, 640, 480, 3)))
    browser = pw.chromium.launch(executable_path=chromium_executable(), args=[
        "--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={video}"])
    try:
        ctx, watch = hx.context(browser=browser, width=375, height=812, touch=True, permissions=["camera"])
        page = ctx.new_page()
        state["page"] = page
        try:
            open_add(page, hx.base)
            # "Start the camera when I open Scan" is on by default (note 03 R10): opening the sheet starts it.
            scan_sheet(page)
            page.wait_for_selector("#scan-viewfinder:not([hidden])")
            check(area, "with 'Start the camera when I open Scan' on (the default), opening Scan starts the camera",
                  page.is_visible("#scan-camera-stop") and page.is_hidden("#scan-camera"))
            time.sleep(0.6)
            hx.shot(page, "live-viewfinder-375")
            page.wait_for_selector("#sheet-entry[open]")
            check(area, "two identical reads looked the code up and opened the entry sheet", "Harness cola" in page.inner_text("#sheet-entry"))
            stopped = page.evaluate("(() => { const v = document.querySelector('#scan-video'); return v.srcObject === null; })()")
            check(area, "every camera track stopped after the read", stopped)
            page.keyboard.press("Escape")
        finally:
            no_problems(area, watch)
            ctx.close()
        # The no-frame watchdog
        ctx, watch = hx.context(browser=browser, width=375, height=812, touch=True, permissions=["camera"], init=NO_FRAMES)
        page = ctx.new_page()
        state["page"] = page
        try:
            open_add(page, hx.base)
            scan_sheet(page)  # the camera starts by itself (the default)
            wait_js(page, "document.querySelector('#scan-status').textContent.includes('did not show a picture')", 9000)
            check(area, "a camera with no picture closes after 4 s and points to the photo button",
                  page.is_hidden("#scan-viewfinder") and page.evaluate("document.activeElement && document.activeElement.id") == "scan-file")
        finally:
            no_problems(area + " / watchdog", watch)
            ctx.close()
        # The setting off: Scan waits for a choice; the camera button starts it.
        hx.api("PATCH", "/api/me/settings", {"food.scan_prefer_camera": False})
        ctx, watch = hx.context(browser=browser, width=375, height=812, touch=True, permissions=["camera"])
        page = ctx.new_page()
        state["page"] = page
        try:
            open_add(page, hx.base)
            scan_sheet(page)
            page.wait_for_timeout(1500)
            check(area, "with the setting off, Scan opens on the choice: the camera button, no camera running",
                  page.is_visible("#scan-camera") and page.is_hidden("#scan-viewfinder")
                  and page.evaluate("document.querySelector('#scan-video').srcObject === null"))
            page.click("#scan-camera")
            page.wait_for_selector("#scan-viewfinder:not([hidden])")
            check(area, "... and 'Use the camera' starts it", page.is_visible("#scan-camera-stop"))
            page.keyboard.press("Escape")
        finally:
            hx.api("PATCH", "/api/me/settings", {"food.scan_prefer_camera": None})
            no_problems(area + " / setting off", watch)
            ctx.close()
        # Plain HTTP (emulated): no camera button, the reason instead.
        ctx, watch = hx.context(browser=browser, width=375, height=812, touch=True, init=INSECURE)
        page = ctx.new_page()
        state["page"] = page
        try:
            open_add(page, hx.base)
            scan_sheet(page)
            note = page.inner_text("#scan-live-note")
            check(area, "plain HTTP: no camera button, the reason and the photo route instead",
                  page.is_hidden("#scan-camera") and "needs HTTPS" in note and "photo of the barcode works" in note, note)
            hx.shot(page, "scan-insecure-375")
        finally:
            no_problems(area + " / plain HTTP", watch)
            ctx.close()
    finally:
        browser.close()


def wait_controlled(page: Page, base: str) -> None:
    page.goto(f"{base}/")
    wait_js(page, "navigator.serviceWorker && navigator.serviceWorker.ready.then(() => true)")
    for _ in range(3):
        if page.evaluate("!!navigator.serviceWorker.controller"):
            return
        page.reload()
        page.wait_for_selector("#view-today:not([hidden])")
    raise RuntimeError("the service worker never took control")


def idb(op: str, store: str, key: Any = None) -> str:
    """A JavaScript expression over this origin's offline database ``kdl`` (js/offline.js): get, all or delete."""
    call = {"get": f"s.get({json.dumps(key)})", "all": "s.getAll()", "delete": f"s.delete({json.dumps(key)})"}[op]
    mode = "readwrite" if op == "delete" else "readonly"
    return ("new Promise((res, rej) => { const o = indexedDB.open('kdl'); o.onerror = () => rej(o.error); o.onsuccess = () => {"
            f" const s = o.result.transaction({json.dumps(store)}, '{mode}').objectStore({json.dumps(store)}); const q = {call};"
            " q.onsuccess = () => res(q.result === undefined ? null : q.result); q.onerror = () => rej(q.error); }; })")


def section_outbox(hx: Harness, state: dict[str, Any]) -> None:
    area = "offline outbox"
    ctx, watch = hx.context(width=375, height=812, touch=True, service_workers="allow")
    page = ctx.new_page()
    state["page"] = page
    try:
        wait_controlled(page, hx.base)
        page.wait_for_selector("#view-today:not([hidden])")
        # Offline food search keeps the builtin list from GET /api/foods/builtin (note 02 §6 item 9, v0.3.0 review L9):
        # one download with its ETag, then 304 with no body while the list is unchanged.
        uid = page.evaluate("KH.state.me.id")
        wait_js(page, idb("get", "meta", f"builtin_etag:{uid}") + ".then((v) => !!(v && v.value))", 20000)
        kept = page.evaluate(idb("all", "foods"))
        builtin = hx.api("GET", "/api/foods/builtin")["foods"]
        check(area, "the device keeps the whole builtin list from one GET /api/foods/builtin",
              {f["id"] for f in builtin} <= {r["id"] for r in kept if r["user_id"] == uid and r["food"]["source"] == "builtin"})
        page.evaluate(idb("delete", "meta", f"foods_full_sync:{uid}"))
        with page.expect_response(lambda r: r.url.endswith("/api/foods/builtin"), timeout=20000) as again:
            page.reload()
        check(area, "the next daily refresh sends If-None-Match and gets 304 (no body) for an unchanged list",
              again.value.status == 304 and bool(again.value.request.headers.get("if-none-match")), str(again.value.status))
        wait_js(page, idb("get", "meta", f"foods_full_sync:{uid}") + ".then((v) => !!v)", 20000)  # the refresh finished
        open_add(page, hx.base)
        search(page, "apple raw")
        before = len(hx.entries())
        # 1. Log with the network off.
        watch.offline = True
        ctx.set_offline(True)
        page.click("#food-results .row-btn >> text=/apple/i >> nth=0")
        page.wait_for_selector("#sheet-entry[open]")
        food = page.inner_text(".sheet-food-name")
        page.click("#entry-save")
        page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
        check(area, "offline: the entry is kept on this device and shown 'waiting to sync'", food in page.inner_text("#meals"))
        badge = page.evaluate("[document.querySelector('#sync-badge-text').textContent, document.querySelector('#sync-badge-short').textContent,"
                              " document.querySelector('#sync-badge').getAttribute('aria-label')]")
        check(area, "the header badge says offline and 1 to sync (on a phone: '1', the full words for screen readers)",
              badge[0] == "Offline · 1 to sync" and page.inner_text("#sync-badge").strip() == "1"
              and badge[2].startswith("Your server cannot be reached. 1 entry is waiting to sync."), json.dumps(badge))
        # 2. Reload while offline: the service worker serves the app, the app starts from this device's copies.
        page.reload()
        page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
        check(area, "after an offline reload the waiting entry is still there", food in page.inner_text("#meals"))
        check(area, "Today says it shows this device's saved copy", "Offline: this is the copy this device saved" in page.inner_text("#alerts"))
        hx.shot(page, "outbox-offline-today-375")
        # An item the server will refuse (a food it does not know), queued too.
        page.evaluate(f"KH.api.addEntry({{ date: '{TODAY}', meal: 'snack', food_id: 987654, servings: 1 }})")
        # 3. Reconnect: synced exactly once; the refused one is kept as "not saved".
        watch.expect("/api/log/batch", 404)
        ctx.set_offline(False)
        watch.offline = False
        wait_js(page, "KH.offline.counts().pending === 0", TIMEOUT_MS)
        rows = [e for e in hx.entries() if e["food_name"] == food]
        check(area, "reconnected: synced once (one row on the server, with a client_id)",
              len(hx.entries()) == before + 1 and len(rows) == 1 and rows[0]["client_id"], json.dumps(rows)[:300])
        check(area, "the refused item stays, marked 'not saved'", page.evaluate("KH.offline.counts().failed") == 1)
        page.wait_for_selector("#sync-badge.failed")
        # 4. Settings → This device: Retry / Discard.
        page.click("#sync-badge")
        page.wait_for_selector("#set-outbox .outbox-item.failed")
        text = page.inner_text("#set-outbox")
        check(area, "Settings → This device lists it with the server's reason", "food 987654 not found" in text and "Retry" in text, text[:300])
        hx.shot(page, "outbox-settings-375", full=False)
        page.click("#set-outbox .outbox-item.failed .btn.danger")
        page.click("#set-outbox .confirm-row .btn.danger-solid")
        wait_js(page, "KH.offline.counts().failed === 0")
        check(area, "Discard removes it and the badge goes", page.is_hidden("#sync-badge"))
        # 5. A batch the server stored but whose answer was lost: sent again, still one row.
        open_add(page, hx.base)
        search(page, "blueberries")
        watch.offline = True
        ctx.set_offline(True)
        page.click("#food-results .row-btn >> text=/blueberr/i >> nth=0")
        page.wait_for_selector("#sheet-entry[open]")
        berries = page.inner_text(".sheet-food-name")
        page.click("#entry-save")
        page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
        lost = {"n": 0}

        def lose_answer(route: Any) -> None:
            lost["n"] += 1
            if lost["n"] == 1:
                route.fetch()  # the server gets it and stores the entry ...
                route.abort("connectionreset")  # ... the page never hears back
            else:
                route.continue_()
        page.route("**/api/log/batch", lose_answer)
        watch.expected_failures.add(("/api/log/batch", "net::ERR_CONNECTION_RESET"))
        ctx.set_offline(False)
        # (The route handler runs only while Playwright is called, so wait through Playwright, not time.sleep.)
        wait_js(page, "navigator.onLine")
        deadline = time.monotonic() + TIMEOUT_MS / 1000
        while lost["n"] < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        wait_js(page, "KH.offline.isOffline()")  # the sync took the lost answer for a dropped connection
        stored = [e for e in hx.entries() if e["food_name"] == berries]
        check(area, "the lost answer left the item waiting although the server has it", len(stored) == 1 and page.evaluate("KH.offline.counts().pending") == 1,
              f"rows {len(stored)}, waiting {page.evaluate('KH.offline.counts().pending')}")
        # What the 30-second timer does: try again.
        result = json.loads(page.evaluate("KH.offline.syncNow().then((r) => JSON.stringify(r))"))
        check(area, "the next sync sends it again and clears it", result.get("sent") == 1 and page.evaluate("KH.offline.counts().pending") == 0,
              json.dumps(result))
        stored = [e for e in hx.entries() if e["food_name"] == berries]
        check(area, "sent again, answered 'existing': still exactly one row", len(stored) == 1,
              json.dumps([(e["id"], e["client_id"], e["created_at"]) for e in stored]) + f" route calls {lost}")
        page.unroute("**/api/log/batch")
        watch.offline = False
        # 6. Sign-out asks while something waits.
        watch.offline = True
        ctx.set_offline(True)
        page.evaluate(f"KH.api.quick({{ date: '{TODAY}', meal: 'snack', name: 'Harness quick add', nutrients: {{ carbs_g: 12 }} }})")
        said = page.evaluate("KH.request('PUT', '/api/profile', { weight_kg: 71 }).then(() => 'saved?', (e) => e.message)")
        check(area, "a change that cannot wait (profile) says it needs a connection", "needs a connection" in said, said)
        page.goto(f"{hx.base}/#settings")
        page.wait_for_selector("#set-signout")
        page.click("#set-signout")
        page.wait_for_selector("#sheet-unsynced[open]")
        check(area, "sign-out with an unsynced entry asks first", "Harness quick add" in page.inner_text("#sheet-unsynced"))
        hx.shot(page, "outbox-signout-375")
        problems = layout_problems(page, "#sheet-unsynced")
        check(area, "the sign-out sheet fits a phone (no cut-off buttons, 44 px targets)", not problems, "; ".join(problems[:8]))
        page.click("#sheet-unsynced >> text=Stay signed in")
        wait_js(page, "!document.querySelector('#sheet-unsynced').open")
        check(area, "'Stay signed in' keeps the session", page.is_visible("#set-signout"))
        ctx.set_offline(False)
        watch.offline = False
        wait_js(page, "KH.offline.counts().pending === 0", TIMEOUT_MS)
        check(area, "the quick add synced through /api/log/quick", any(e["food_name"] == "Harness quick add" for e in hx.entries()))
    finally:
        no_problems(area, watch)
        ctx.close()


# Settings → This device as drawn on the page: rows, the outbox list, the button, and ids used more than once.
DEVICE_SECTION_JS = """() => {
  const body = document.querySelector('#set-device-body');
  const rows = [...body.querySelectorAll('dt')].filter((dt) => dt.textContent.trim() === 'Works offline')
    .map((dt) => (dt.nextElementSibling ? dt.nextElementSibling.textContent.trim() : ''));
  const seen = new Map();
  for (const el of document.querySelectorAll('[id]')) seen.set(el.id, (seen.get(el.id) || 0) + 1);
  return { offlineRows: rows, clearButtons: document.querySelectorAll('#set-clear-device').length,
           outboxes: document.querySelectorAll('#set-outbox').length, outboxHeads: document.querySelectorAll('#set-outbox-h').length,
           duplicateIds: [...seen].filter(([, n]) => n > 1).map(([id, n]) => `${id} ×${n}`) };
}"""


def section_firstvisit(hx: Harness, state: dict[str, Any]) -> None:
    """The review's repro (three out of three fresh profiles drew the section twice): open Settings first."""
    area = "first visit: Settings → This device"
    for attempt in range(1, 4):
        ctx, watch = hx.context(width=375, height=812, touch=True, service_workers="allow")
        page = ctx.new_page()
        state["page"] = page
        try:
            page.goto(f"{hx.base}/#settings")
            page.wait_for_selector("#view-settings:not([hidden]) #set-clear-device")
            # The worker installs, claims this page (controllerchange) and js/pwa.js asks Settings to draw again.
            wait_js(page, "!!(navigator.serviceWorker && navigator.serviceWorker.controller)")
            wait_js(page, "(document.querySelector('#set-device-body') || {}).textContent.includes('Yes: the app opens without a connection')")
            page.wait_for_timeout(1000)  # any render still waiting for IndexedDB or the storage estimate lands now
            got = page.evaluate(DEVICE_SECTION_JS)
            check(area, f"profile {attempt}: drawn once (one 'Works offline' row, now 'Yes'; one outbox list and heading; one Clear button)",
                  got["offlineRows"] == ["Yes: the app opens without a connection"] and got["clearButtons"] == 1
                  and got["outboxes"] == 1 and got["outboxHeads"] == 1, json.dumps(got))
            check(area, f"profile {attempt}: no id is used twice on the page", not got["duplicateIds"], ", ".join(got["duplicateIds"]))
            if attempt == 1:
                hx.shot(page, "firstvisit-device-375")
        finally:
            no_problems(f"{area} {attempt}", watch)
            ctx.close()


IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.6 Mobile/15E148 Safari/604.1")


def section_iostip(hx: Harness, state: dict[str, Any]) -> None:
    """Note 02 R10 (v0.3.0 review L12): on an iPhone in the browser, the Home Screen steps show once, as a
    dismissible tip, from the third signed-in visit; never on other devices; never again once shown."""
    area = "iOS Home Screen tip after the third visit"
    visible = "!document.querySelector('#install-tip').hidden"
    for label, ua in (("iPhone", IPHONE_UA), ("desktop", None)):
        ctx, watch = hx.context(width=375 if ua else 1280, height=812 if ua else 800, touch=bool(ua), user_agent=ua)
        page = ctx.new_page()
        state["page"] = page
        try:
            seen = []
            for visit in range(1, 5):
                if visit == 1:
                    page.goto(f"{hx.base}/#today")
                else:
                    page.reload()  # a new page load is a new visit (the same URL with a hash would not load again)
                page.wait_for_selector("#view-today:not([hidden])")
                wait_js(page, "localStorage.getItem('kdl-visits') === '%d'" % visit)
                page.wait_for_load_state("networkidle")  # the next reload must not cut off this visit's requests
                seen.append(page.evaluate(visible))
                if visit == 3 and seen[-1]:
                    tip = page.inner_text("#install-tip")
                    check(area, "iPhone: the tip gives the Add to Home Screen steps and where to find them again",
                          '"Add to Home Screen"' in tip and "Settings → This device" in tip, tip[:200])
                    problems = layout_problems(page, "#install-tip")
                    check(area, "iPhone: the tip lays out at 375 px (in the page, not over it)", not problems, "; ".join(problems[:6]))
                    hx.shot(page, "ios-tip-375")
                    page.click("#install-tip-close")
                    check(area, "iPhone: Dismiss hides it and focus moves to the page", page.evaluate(visible) is False
                          and page.evaluate("document.activeElement && document.activeElement.closest('#main') !== null"))
            want = [False, False, True, False] if ua else [False, False, False, False]
            check(area, f"{label}: shown only on the third visit, then never again", seen == want, json.dumps(seen))
        finally:
            no_problems(f"{area} ({label})", watch)
            ctx.close()


def section_ai(hx: Harness, state: dict[str, Any], fake: FakeAi) -> None:
    area = "AI cards and label photo (fake OpenAI-compatible server)"
    hx.api("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                "carbs_per_meal_g": 60, "protein_g": {"min": 42, "max": 56}}})
    ctx, watch = hx.context(width=1280, height=800, init=UPLOAD_SPY)
    page = ctx.new_page()
    state["page"] = page
    try:
        page.goto(f"{hx.base}/#settings")
        page.wait_for_selector("#set-ai-slot input[type=checkbox]")
        if not page.is_checked("#set-ai-slot input[type=checkbox] >> nth=0"):
            page.click("#set-ai-slot label.check >> nth=0")
        page.wait_for_selector("#set-ai-slot >> text=AI ideas are on for you.")
        check(area, "Settings → AI ideas: opted in", True)
        hx.shot(page, "ai-settings-1280")
        # AI meal ideas: consent once, cards labelled, next to the rule-based list.
        open_add(page, hx.base)
        page.wait_for_selector("#ai-add-slot:not([hidden]) >> text=AI meal ideas")
        page.click("#ai-add-slot >> text=AI meal ideas")
        page.wait_for_selector("#sheet-ai[open]")
        watch.expect("/api/ai/next-meal", 409)
        page.click("#sheet-ai >> text=Ask AI for ideas")
        page.wait_for_selector("#sheet-ai-consent[open]")
        hx.shot(page, "ai-consent-1280")
        page.click("#sheet-ai-consent >> text=Agree and send")
        page.wait_for_selector("#sheet-ai .ai-idea")
        cards = page.locator("#sheet-ai .ai-idea")
        label = cards.first.inner_text()
        check(area, "AI ideas are shown as cards labelled as AI and 'checked against your targets'",
              cards.count() >= 1 and "AI idea" in label and "checked against your targets" in label, label[:300])
        html_free = page.evaluate("[...document.querySelectorAll('#sheet-ai .ai-idea *')].every((el) => !/^(SCRIPT|IFRAME|OBJECT)$/.test(el.tagName))")
        check(area, "cards are plain text (no script, frame or object elements)", html_free)
        shown = page.inner_text("#sheet-ai").lower()
        check(area, "the provider's dosing prose never reaches the cards", "insulin" not in shown and "6 units" not in shown, shown[:200])
        hx.shot(page, "ai-ideas-1280")
        page.click("#sheet-ai >> text=What will be sent?")
        page.wait_for_selector("#sheet-ai-sent[open]")
        sent = page.inner_text("#sheet-ai-sent")
        check(area, "'What will be sent?' shows the destination and hides the key", f"127.0.0.1:{fake.port}" in sent, sent[:300])
        page.click("#sheet-ai-sent .sheet-foot >> text=Close")
        page.click("#sheet-ai .sheet-foot >> text=Close")
        page.wait_for_selector("#guidance-fits:not([hidden])")
        page.click("#guidance-fits-meal label >> nth=0")
        page.wait_for_selector("#guidance-fits-body .g-food")
        check(area, "the rule-based 'What fits now' list is still there, beside the AI button",
              page.locator("#guidance-fits-body .g-food").count() >= 1 and page.is_visible("#ai-add-slot"))
        # "AI order" (note 04 R9 step 4, G13; v0.3.0 review L10): its own "What will be sent?", and the picks the
        # rules left out are counted with the reason.
        prefs = (hx.api("GET", "/api/me/settings")["settings"]["guidance"] or {}).get("value") or {}
        hx.api("PATCH", "/api/me/settings", {"guidance": {**prefs, "ai_enrich": True}})
        open_add(page, hx.base)
        page.reload()  # the page keeps the person's guidance settings until it loads again
        page.wait_for_selector("#view-add:not([hidden]) #btn-scan")
        page.wait_for_selector("#guidance-fits:not([hidden])")
        page.click("#guidance-fits-meal label >> nth=0")
        page.wait_for_selector("#guidance-fits-body .g-ai-bar .g-ai-sent")
        page.click("#guidance-fits-body .g-ai-bar .g-ai-sent")
        page.wait_for_selector("#sheet-ai-sent[open]")
        sent = page.inner_text("#sheet-ai-sent")
        check(area, "'AI order' has its own 'What will be sent?' (the rerank request, destination shown, no key)",
              f"127.0.0.1:{fake.port}" in sent and "rerank" in sent, sent[:300])
        page.click("#sheet-ai-sent .sheet-foot >> text=Close")
        page.click("#guidance-fits-body .g-ai-toggle")
        page.wait_for_selector("#guidance-fits-body .g-ai-dropped")
        dropped = page.inner_text("#guidance-fits-body .g-ai-dropped")
        check(area, "'AI order' says how many picks the rules left out and why",
              dropped.startswith("1 AI pick was left out by the app's rules") and "had not offered" in dropped, dropped)
        hx.shot(page, "ai-order-dropped-1280")
        # Quick add: a large phone photo with EXIF, beside the form; AI reads it; the browser sends a small clean JPEG.
        big = hx.out / "label-big.jpg"
        jpeg_b64 = page.evaluate("""(() => { const c = document.createElement('canvas'); c.width = 3000; c.height = 2000;
          const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 3000, 2000); g.fillStyle = '#000';
          for (let y = 100; y < 1900; y += 90) g.fillRect(200, y, 2400, 30);
          return c.toDataURL('image/jpeg', 0.9).split(',')[1]; })()""")
        big.write_bytes(with_exif(base64.b64decode(jpeg_b64)))
        check(area, "the test photo has EXIF (as a phone's would)", jpeg_has_exif(big.read_bytes()))
        page.click("#btn-quick")
        page.wait_for_selector("#sheet-quick[open]")
        page.set_input_files("#q-photo", str(big))
        page.wait_for_selector("#q-photo-view:not([hidden])")
        page.wait_for_selector("#q-photo-ai >> text=Read the label for me (AI)")
        hx.shot(page, "ai-quick-photo-1280")
        watch.expect("/api/vision/label", 409)
        page.click("#q-photo-ai >> text=Read the label for me (AI)")
        page.wait_for_selector("#sheet-ai-consent[open]")
        page.click("#sheet-ai-consent >> text=Agree and send")
        wait_js(page, "document.querySelector('#q-name').value === 'Harness rye crackers'")
        tags = page.locator("#sheet-quick .ai-tag").count()
        check(area, "the label draft filled Quick add, fields marked 'from photo'", tags >= 5, str(tags))
        check(area, "the ingredient list flags the phosphate additive before saving", "Phosphate additives" in page.inner_text("#q-ingredients-scan"))
        sent_b64 = page.evaluate("""(async () => {
          const b = (window.__khUploads || []).at(-1); if (!b) return '';
          const bytes = new Uint8Array(await b.arrayBuffer()); let s = '';
          for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
          return btoa(s); })()""")
        sent_jpeg = base64.b64decode(sent_b64) if sent_b64 else b""
        size = jpeg_size(sent_jpeg) if sent_jpeg else None
        check(area, "the browser sent a JPEG with its long edge ≤ 1600 px", sent_jpeg[:3] == b"\xff\xd8\xff" and size and max(size) <= 1600, str(size))
        check(area, "the sent JPEG has no EXIF", sent_jpeg and not jpeg_has_exif(sent_jpeg))
        hx.shot(page, "ai-label-filled-1280")
        page.click("#quick-save")
        page.wait_for_selector("#view-today:not([hidden])")
        logged = [e for e in hx.entries() if e["food_name"] == "Harness rye crackers"]
        food = hx.api("GET", f"/api/foods/{logged[0]['food_id']}") if logged else {}
        check(area, "logged; the saved food carries the additive scan", logged and "phosphate_additive" in food.get("flags", []), json.dumps(food)[:300])
        # Plate photo (note 03 R9): the fixed banner, foods matched to the person's own list, the unsure one unticked,
        # "planned" by default, nothing logged until "Add selected".
        before = len(hx.entries())
        open_add(page, hx.base)
        page.wait_for_selector("#ai-add-slot >> text=Plate photo (AI)")
        page.click("#ai-add-slot >> text=Plate photo (AI)")
        page.wait_for_selector("#sheet-ai[open] .ai-plate-banner")
        check(area, "plate photo: the banner says portions are rough and not to dose insulin from it",
              "do not dose insulin" in page.inner_text("#sheet-ai .ai-plate-banner"))
        page.set_input_files("#sheet-ai input[type=file]", str(big))
        page.click("#sheet-ai >> text=Find the foods")
        try:
            page.wait_for_selector("#sheet-ai-consent[open], #sheet-ai .ai-parse-item", timeout=TIMEOUT_MS)
            if page.is_visible("#sheet-ai-consent[open]"):
                page.click("#sheet-ai-consent >> text=Agree and send")
        except Exception:  # noqa: BLE001 - the next wait reports it
            pass
        page.wait_for_selector("#sheet-ai .ai-parse-item")
        items = page.locator("#sheet-ai .ai-parse-item")
        ticks = [items.nth(i).locator("input[type=checkbox]").is_checked() for i in range(items.count())]
        names = items.all_inner_texts()
        check(area, "plate photo: foods matched to the food list, the unsure one starts unticked",
              len(ticks) == 2 and ticks[0] and not ticks[1] and "banana" in names[0].lower(), json.dumps([ticks, [n[:60] for n in names]]))
        check(area, "plate photo: entries are added as planned by default and nothing is logged yet",
              page.is_checked("#sheet-ai input[type=radio][value=planned]") and len(hx.entries()) == before)
        hx.shot(page, "ai-plate-1280")
        page.click("#sheet-ai .sheet-foot >> text=Close")
        # Settings → AI ideas: the activity lists both calls; a personal provider's key is write-only; a private
        # address is refused for a personal provider (only the admin's AI_PRIVATE_HOSTS may be private).
        page.goto(f"{hx.base}/#settings")
        activity = page.locator("#set-ai-slot summary", has_text="AI activity").locator("xpath=..")
        activity.locator("summary").first.click()
        page.wait_for_selector("#set-ai-slot .ai-event")
        rows = page.locator("#set-ai-slot .ai-event > summary").all_inner_texts()
        check(area, "AI activity lists the meal ideas, label and plate calls to the fake server",
              len(rows) >= 3 and all("127.0.0.1" in r for r in rows[:3]), json.dumps(rows[:4]))
        ideas_event = page.locator("#set-ai-slot .ai-event", has_text="Meal ideas").last
        ideas_event.locator("summary").first.click()
        raw = ideas_event.locator("pre").last.inner_text()
        caption = ideas_event.locator("p.hint").last.inner_text()
        check(area, "AI activity: the raw answer is captioned as unchecked and its dosing words read [hidden]",
              "before the app checked it" in caption and raw.startswith("Sure! Take 6 [hidden] of [hidden] before this meal.")
              and "insulin" not in raw.lower() and "units" not in raw.lower(), raw[:160])
        hx.shot(page, "ai-activity-raw-masked-1280")
        own = page.locator("#set-ai-slot summary", has_text="My own AI provider").locator("xpath=..")
        if not own.evaluate("(el) => el.open"):
            own.locator("summary").first.click()
        offered = own.locator("select").first.evaluate("(el) => [...el.options].map((o) => o.value)")
        check(area, "a person is offered public services only (no address of their own unless the admin allows it)",
              "openai" in offered and "openai_compatible" not in offered and "ollama" not in offered, json.dumps(offered))
        own.locator("select").first.select_option("openai")
        own.locator("button", has_text="Add your key").click()
        secret = "sk-harness-write-only-0123456789abcdef"
        own.locator("input[type=password]").fill(secret)
        own.locator(".key-widget").get_by_role("button", name="Save", exact=True).click()  # not "Test and save": no outside call
        page.wait_for_selector("#set-ai-slot .key-widget >> text=/Replace/")
        said = page.inner_text(".toast")
        check(area, "saving a key without the test makes no call (it says 'Key saved.')", said.strip() == "Key saved.", said)
        me_ai = json.dumps(hx.api("GET", "/api/me/ai"))
        check(area, "a personal key is write-only: never in the page or in GET /api/me/ai",
              secret not in page.content() and secret not in me_ai and secret[-8:] not in me_ai, me_ai[:300])
        hx.shot(page, "ai-own-provider-1280")
        own = page.locator("#set-ai-slot summary", has_text="My own AI provider").locator("xpath=..")
        if not own.evaluate("(el) => el.open"):
            own.locator("summary").first.click()
        own.locator("button", has_text="Remove my provider").click()
        page.click("#set-ai-slot .confirm-row .btn.danger-solid")
        page.wait_for_selector("#set-ai-slot button >> text=Save provider", state="attached")
        check(area, "'Remove my provider' removes it and its key", hx.api("GET", "/api/me/ai").get("own") is None)
    finally:
        no_problems(area, watch)
        ctx.close()


def section_demo(hx: Harness, state: dict[str, Any]) -> None:
    area = "demo (?mock=1)"
    ctx, watch = hx.context(width=375, height=812, touch=True, signed_in=False)
    page = ctx.new_page()
    state["page"] = page
    try:
        page.goto(f"{hx.base}/?mock=1#add")
        page.wait_for_selector("#view-add:not([hidden]) #btn-scan")
        scan_sheet(page)
        page.fill("#scan-code", "049000028911")
        page.click("#scan-go")
        page.wait_for_selector("#scan-result >> text=Look this up in Open Food Facts?")
        hx.shot(page, "demo-consent-375")
        problems = layout_problems(page, "#scan-result")
        check(area, "the consent panel fits a phone (no cut-off buttons, 44 px targets)", not problems, "; ".join(problems[:8]))
        page.click("#scan-result >> text=Send barcodes to Open Food Facts and look up")
        page.wait_for_selector("#sheet-entry[open]")
        link = page.locator("#sheet-entry-provenance a").first
        check(area, "a recorded product opens with its ODbL attribution linking to the product page",
              link.get_attribute("href") == "https://world.openfoodfacts.org/product/0049000028911"
              and link.get_attribute("rel") == "noopener noreferrer" and link.get_attribute("target") == "_blank")
        prov = page.inner_text("#sheet-entry-provenance")
        check(area, "quality notes are shown", "Potassium is not listed for this product" in prov, prov[:300])
        check(area, "potassium and phosphorus read 'not listed'", page.inner_text("#entry-preview-key").count("not listed") >= 2)
        hx.shot(page, "demo-entry-375")
        check(area, "a product with weight-based values offers grams", page.is_visible("#entry-grams"))
        page.keyboard.press("Escape")
        scan_sheet(page)
        page.fill("#scan-code", CRACKERS)
        page.click("#scan-go")
        page.wait_for_selector("#scan-result >> text=Enter from the label")
        check(area, "a barcode the demo does not know names the samples", "three sample products" in page.inner_text("#scan-result"))
        page.click("#scan-result >> text=Enter from the label")
        page.wait_for_selector("#sheet-quick[open]")
        try:
            wait_js(page, "document.activeElement && document.activeElement.id === 'q-photo'", 3000)
        except Exception:  # noqa: BLE001 - the check below reports it
            pass
        check(area, "'Enter from the label' opens Quick add with the barcode and the photo prompt",
              page.input_value("#q-gtin") == CRACKERS and page.evaluate("document.activeElement.id") == "q-photo",
              f"{page.input_value('#q-gtin')} focus {page.evaluate('document.activeElement.id')}")
        page.keyboard.press("Escape")
        # The outbox against the demo API.
        watch.offline = True
        ctx.set_offline(True)
        page.click("#btn-quick")
        page.fill("#q-name", "Demo offline snack")
        page.fill("#qn-carbs_g", "15")
        page.click("#quick-save")
        page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
        check(area, "offline in the demo: the quick add waits", "Demo offline snack" in page.inner_text("#meals"))
        ctx.set_offline(False)
        watch.offline = False
        wait_js(page, "KH.offline.counts().pending === 0")
        wait_js(page, "!document.querySelector('#meals .badge.pending')")
        check(area, "back online: synced into the demo's log", "Demo offline snack" in page.inner_text("#meals"))
        page.goto(f"{hx.base}/?mock=1#settings")
        page.wait_for_selector("#set-ai-body")
        check(area, "AI in the demo: 'in the installed app'", "installed app" in page.inner_text("#set-ai-body"))
        # Prepared values only (Kraft macaroni, recorded): logged in servings, the grams field gone and the reason given.
        page.goto(f"{hx.base}/?mock=1#add")
        page.wait_for_selector("#view-add:not([hidden]) #btn-scan")
        page.evaluate("KH.api.updateMySettings({ 'food.off_consent': true })")
        scan_sheet(page)
        page.fill("#scan-code", "0021000658831")
        page.click("#scan-go")
        page.wait_for_selector("#sheet-entry[open]")
        desc = page.inner_text("#entry-serving-desc")
        check(area, "a prepared-only product is logged in servings: no grams field, the reason under the servings",
              page.is_hidden("#entry-grams") and "Log it in servings" in desc and "as prepared" in desc, desc)
        hx.shot(page, "demo-entry-servings-only-375")
        food = page.inner_text(".sheet-food-name")
        page.click("#entry-save")
        page.wait_for_selector("#view-today:not([hidden])")
        logged = page.evaluate(f"KH.api.day(KH.util.todayStr()).then((d) => d.entries.filter((e) => e.food_name === {json.dumps(food)})"
                               ".map((e) => [e.servings, e.grams]))")
        check(area, "it was logged by servings (1 serving, no grams)", logged == [[1, None]], json.dumps(logged))
    finally:
        no_problems(area, watch)
        ctx.close()


def layout_problems(page: Page, root: str) -> list[str]:
    return page.evaluate("""(root) => {
      const out = [];
      const doc = document.documentElement;
      if (doc.scrollWidth > window.innerWidth + 1) out.push(`page scrolls sideways: ${doc.scrollWidth} > ${window.innerWidth}`);
      for (const el of document.querySelectorAll(`${root} button, ${root} a[href], ${root} input, ${root} select, ${root} textarea, ${root} summary`)) {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height || el.closest('[hidden]')) continue;
        const style = getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') continue;
        if (el.tagName === 'A' && getComputedStyle(el).display === 'inline') continue; // links in running text
        if (el.type === 'checkbox' || el.type === 'radio') continue; // their labels are the targets
        if (r.height < 43.5) out.push(`${el.tagName.toLowerCase()}#${el.id || ''}.${el.className || ''} is ${Math.round(r.height)} px tall`);
        if (el.tagName === 'BUTTON' && el.scrollWidth > el.clientWidth + 1) out.push(`button "${el.textContent.trim()}" is cut off (${el.scrollWidth} > ${el.clientWidth})`);
      }
      return out;
    }""", root)


def section_shots(hx: Harness, state: dict[str, Any]) -> None:
    """The new screens on the demo (``?mock=1``) and on the real server, signed in, at both sizes and themes."""
    ensure_cola(hx)
    for mode in ("demo", "server"):
        for width, height, touch in ((375, 812, True), (1280, 800, False)):
            for scheme in ("light", "dark"):
                walk(hx, state, mode, width, height, touch, scheme)


def walk(hx: Harness, state: dict[str, Any], mode: str, width: int, height: int, touch: bool, scheme: str) -> None:
    area = f"walk {mode} {width}x{height} {scheme}"
    demo = mode == "demo"
    ctx, watch = hx.context(width=width, height=height, touch=touch, scheme=scheme, signed_in=not demo)
    page = ctx.new_page()
    state["page"] = page
    tag = f"{mode}-{width}-{scheme}"
    try:
        page.goto(f"{hx.base}/{'?mock=1' if demo else ''}#add")
        page.wait_for_selector("#view-add:not([hidden]) #btn-scan")
        hx.shot(page, f"walk-add-{tag}")
        scan_sheet(page)
        hx.shot(page, f"walk-scan-{tag}")
        problems = layout_problems(page, "#sheet-scan")
        check(area, "scan sheet: no sideways scroll, 44 px targets", not problems, "; ".join(problems[:8]))
        if demo:
            page.evaluate("KH.api.updateMySettings({ 'food.off_consent': true })")
        page.fill("#scan-code", "3017624010701" if demo else COLA)
        page.click("#scan-go")
        page.wait_for_selector("#sheet-entry[open]")
        hx.shot(page, f"walk-entry-provenance-{tag}")
        problems = layout_problems(page, "#sheet-entry-provenance")
        check(area, "entry sheet provenance lays out", not problems, "; ".join(problems[:8]))
        page.keyboard.press("Escape")
        page.click("#btn-quick")
        page.wait_for_selector("#sheet-quick[open]")
        photo = hx.out / "label-walk.png"
        photo.write_bytes(png_gray(600, 800, barcode_image(CRACKERS, 600, 800, 3)))
        page.set_input_files("#q-photo", str(photo))
        page.wait_for_selector("#q-photo-view:not([hidden])")
        page.click("[data-zoom='2']")
        hx.shot(page, f"walk-quick-photo-{tag}")
        problems = layout_problems(page, "#sheet-quick")
        check(area, "Quick add with the photo: no sideways scroll, 44 px targets", not problems, "; ".join(problems[:8]))
        if width >= 900:
            beside = page.evaluate("(() => { const a = document.querySelector('#quick-photo').getBoundingClientRect();"
                                   " const b = document.querySelector('.quick-fields').getBoundingClientRect(); return a.right <= b.left + 1; })()")
            check(area, "the photo sits beside the fields on a wide screen", beside)
        page.keyboard.press("Escape")
        watch.offline = True
        ctx.set_offline(True)
        page.evaluate("KH.api.quick({ date: KH.util.todayStr(), meal: 'snack', name: 'Waiting snack', nutrients: { carbs_g: 10 } })"
                      ".then(() => KH.router.show('today'))")
        page.wait_for_selector("#view-today:not([hidden]) .badge.pending")
        hx.shot(page, f"walk-today-waiting-{tag}")
        problems = layout_problems(page, ".topbar")
        check(area, "header with the sync badge: no sideways scroll, 44 px targets", not problems, "; ".join(problems[:8]))
        page.click("#sync-badge")
        page.wait_for_selector("#set-outbox .outbox-item")
        wait_js(page, "document.activeElement && document.activeElement.id === 'set-outbox-h'", 5000)
        hx.shot(page, f"walk-device-{tag}")
        problems = layout_problems(page, "#set-device")
        check(area, "Settings → This device lays out (the badge took focus to the waiting list)", not problems, "; ".join(problems[:8]))
        ctx.set_offline(False)
        watch.offline = False
        wait_js(page, "KH.offline.counts().pending === 0")
    finally:
        no_problems(area, watch)
        ctx.close()


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT, help=f"uvicorn port (default {PORT})")
    ap.add_argument("--ai-port", type=int, default=AI_PORT, help=f"the fake OpenAI-compatible server's port (default {AI_PORT})")
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory: data, logs, report, screenshots (default {OUT})")
    ap.add_argument("--only", default="", help=f"comma-separated sections ({', '.join(SECTIONS)}); default all")
    ap.add_argument("--server-python", default=sys.executable, help="interpreter that runs the server (default: this one)")
    args = ap.parse_args(argv)
    only = [s for s in args.only.split(",") if s] or list(SECTIONS)
    unknown = [s for s in only if s not in SECTIONS]
    if unknown:
        ap.error(f"unknown section(s): {', '.join(unknown)}")
    for port in (args.port, args.ai_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"AI_ENABLED": "true", "AI_PROVIDER": "openai_compatible", "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1",
           "AI_MODEL": "fake-text", "AI_VISION_MODEL": "fake-vision", "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port}",
           "AI_SHARED_DAILY_LIMIT": "0", "AI_VISION_PLATE_ENABLED": "true",
           # No call may leave this machine: a proxy that does not exist for anything but the local servers.
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = khserver.Server(args.port, out / "data", log_path=out / "server.log", python=args.server_python, env=env)
    state: dict[str, Any] = {"page": None}
    try:
        with FakeAi(args.ai_port) as fake:
            server.start()
            admin = khserver.first_admin(server, "device")
            admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                            "carbs_per_meal_g": 60}})
            base = f"http://localhost:{args.port}"
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=chromium_executable(), args=["--no-sandbox"])
                hx = Harness(browser, server, admin, out, base)
                try:
                    steps: dict[str, Callable[[], None]] = {
                        "photo": lambda: section_photo(hx, state),
                        "native": lambda: section_native(hx, state),
                        "live": lambda: section_live(hx, state, pw),
                        "outbox": lambda: section_outbox(hx, state),
                        "firstvisit": lambda: section_firstvisit(hx, state),
                        "iostip": lambda: section_iostip(hx, state),
                        "ai": lambda: section_ai(hx, state, fake),
                        "demo": lambda: section_demo(hx, state),
                        "shots": lambda: section_shots(hx, state),
                    }
                    for name in only:
                        run_section(name, steps[name], lambda: state.get("page"), out / "shots")
                finally:
                    browser.close()
            admin.close()
    except Exception as exc:
        check("harness", "server, fake AI server and browser started", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        server.stop()
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps({"failed": len(failed), "results": RESULTS}, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}, screenshots {out / 'shots'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
