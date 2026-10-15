#!/usr/bin/env python3
"""Voice for the Ask screen (the microphone and read aloud) in Chromium, against a real server, a fake OpenAI-compatible
provider and a fake speech-to-text server, both run by this script.

    python tools/e2e/ask_voice.py                    # ports 8076 (app), 8077 (fake AI) and 8078 (fake speech to text)
    python tools/e2e/ask_voice.py --port 8076 --ai-port 8077 --stt-port 8078 --out /tmp/kh-ask-voice

Starts ``uvicorn app.main:app`` with ``AI_ENABLED``, ``AI_CHAT_ENABLED`` and ``STT_BASE_URL`` pointed at the fake transcription
server (a private host, so ``AI_PRIVATE_HOSTS`` lists it, exactly as an operator would), switches voice on in Server
administration (``ai.voice_enabled``), then
drives the page with Chromium's fake audio device (a generated tone) at 375x812 light and 1280x800 dark:

* the microphone button is there only while voice is on (switching it off in Server administration removes it);
* the first tap opens the consent sheet ("Your recording is sent to <host> to turn it into text, then deleted. Nothing
  is kept."), and nothing is recorded or sent before "Agree and record";
* while recording the page shows a "Recording" row with the time, the microphone button reads "Stop recording", and the
  row has Discard; a second tap sends the clip, which reaches the transcription server as multipart with the model and
  the app's own file name;
* the words land in the question box, after anything already typed, and NOTHING reaches the AI until the person presses
  Send (the chat consent sheet then appears, and the fake AI has seen no request);
* Discard, leaving the tab, and the 60-second limit end a recording without sending it, and the microphone is released
  (every track ended); a refused microphone and a browser without MediaRecorder get one plain line;
* read aloud: the switch appears only when the device has a voice with ``localService === true`` (a stubbed engine with
  one online and one on-device voice), speaks the answer with the on-device voice and without links, survives a reload;
  with only an online voice the switch is hidden and a note says why;
* the demo (``/?mock=1#ask``) has no microphone and no read-aloud switch; no sideways scroll, no console errors.

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes ``<out>/report.json``
and screenshots in ``<out>/shots/``; exit status 1 on any failure. The servers are always stopped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import khserver
from ask import FakeAi
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "ask-voice"
PORT, AI_PORT, STT_PORT = 8076, 8077, 8078
RESULTS: list[dict[str, Any]] = []
TRANSCRIPT = "How much potassium can I have today?"

# Chromium's fake device gives a tone; a stubbed speech engine stands in for the operating system's voices, because a
# headless Chromium has none. One online voice (localService false) and one on-device voice.
SPEECH_STUB = """
(() => {
  const voices = [
    { name: 'Online Voice', lang: 'en-US', localService: false, default: true, voiceURI: 'online' },
    { name: 'Device Voice', lang: 'en-US', localService: true, default: false, voiceURI: 'device' },
  ];
  const spoken = [];
  window.__spoken = spoken;
  window.SpeechSynthesisUtterance = function (text) { this.text = text; this.voice = null; this.lang = ''; };
  const listeners = {};
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
    speaking: false,
    getVoices: () => (window.__voices || voices),
    speak(u) { spoken.push({ text: u.text, voice: u.voice && u.voice.name, local: u.voice && u.voice.localService, lang: u.lang }); },
    cancel() { window.__cancelled = (window.__cancelled || 0) + 1; },
    addEventListener(name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
  } });
})();
"""
ONLY_ONLINE_VOICES = "window.__voices = [{ name: 'Online Voice', lang: 'en-US', localService: false, default: true, voiceURI: 'online' }];"
# Every stream the page opens, so the test can see that the microphone was released.
TRACK_STUB = """
(() => {
  const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  window.__streams = [];
  navigator.mediaDevices.getUserMedia = async (c) => { const s = await real(c); window.__streams.push(s); return s; };
})();
"""
DENIED_STUB = """
navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Permission denied', 'NotAllowedError'); };
"""
NO_RECORDER_STUB = "delete window.MediaRecorder;"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class FakeStt:
    """``POST /v1/audio/transcriptions``: parses the multipart form and answers ``{"text": ...}``; remembers every request."""

    def __init__(self, port: int) -> None:
        self.requests: list[dict[str, Any]] = []
        self.text = TRANSCRIPT
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                boundary = (self.headers.get("Content-Type") or "").split("boundary=", 1)[-1].encode()
                fields: dict[str, Any] = {}
                for part in raw.split(b"--" + boundary):
                    head, _, body = part.partition(b"\r\n\r\n")
                    match = re.search(rb'name="([^"]+)"', head)
                    if not match:
                        continue
                    name = match.group(1).decode()
                    body = body[:-2] if body.endswith(b"\r\n") else body
                    if name == "file":
                        filename = re.search(rb'filename="([^"]+)"', head)
                        ctype = re.search(rb"Content-Type: ([^\r\n]+)", head)
                        fields["file"] = {"filename": filename.group(1).decode() if filename else None,
                                          "content_type": ctype.group(1).decode() if ctype else None, "bytes": len(body), "head": body[:4].hex()}
                    else:
                        fields[name] = body.decode()
                outer.requests.append({"path": self.path, "fields": fields, "auth": self.headers.get("Authorization")})
                out = json.dumps({"text": outer.text}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def streams_ended(page: Any) -> bool:
    return bool(page.evaluate("() => (window.__streams || []).length > 0 && window.__streams.every((s) => s.getTracks().every((t) => t.readyState === 'ended'))"))


def new_page(browser: Any, admin: Any, base: str, width: int, height: int, scheme: str, scripts: tuple[str, ...] = ()) -> tuple[Any, Any, list[str]]:
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base, permissions=["microphone"])
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    # a 409 at the consent step is the app's own answer, and the browser logs every 4xx as a console error
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    for script in scripts:
        page.add_init_script(script)
    return ctx, page, errors


def open_ask(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#tab-ask:not([hidden])", timeout=15000)
    page.click("#tab-ask")
    page.wait_for_selector("#view-ask:not([hidden])")


def walk(browser: Any, admin: Any, fake: FakeAi, stt: FakeStt, base: str, out: Path, width: int, height: int, scheme: str) -> None:
    tag = f"{width}-{scheme}"
    status = admin.json("GET", "/api/ai/status")
    for purpose in ("voice", "chat"):
        if status["consent"].get(purpose):
            admin.call("DELETE", f"/api/ai/consent/{status['provider']['id']}", params={"purpose": purpose})
    fake.requests.clear()
    stt.requests.clear()
    ctx, page, errors = new_page(browser, admin, base, width, height, scheme, (TRACK_STUB,))
    open_ask(page)
    mic = page.locator("#ask-mic")
    check(f"[{tag}] the microphone button is in the question row", mic.is_visible() and mic.get_attribute("aria-label") == "Record your question")
    box = page.locator("#ask-mic").bounding_box()
    check(f"[{tag}] it is a full-size tap target", box and box["width"] >= 40 and box["height"] >= 40, str(box))
    check(f"[{tag}] no sideways scroll with the microphone", not overflow(page))

    # --- consent before anything is recorded
    page.click("#ask-mic")
    page.wait_for_selector("#sheet-ai-consent[open]")
    sheet = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the first tap asks for consent with the voice text",
          "Before your recording is sent" in sheet and f"Your recording is sent to 127.0.0.1:{STT_PORT} to turn it into text, then deleted. Nothing is kept." in sheet
          and "Nothing but the recording is sent" in sheet, sheet[:300])
    check(f"[{tag}] there is no 'show me the request' choice for a recording, and no stray text", "Show me the request" not in sheet and "null" not in sheet)
    check(f"[{tag}] nothing was recorded or sent before agreeing", not stt.requests and page.evaluate("() => (window.__streams || []).length") == 0)
    page.screenshot(path=str(out / "shots" / f"voice-consent-{tag}.png"))
    page.click("#sheet-ai-consent >> text=Agree and record")
    page.wait_for_selector(".ask-mic.recording", timeout=15000)
    check(f"[{tag}] recording shows the row, the time and a stop button",
          page.is_visible(".ask-voice-bar") and "Recording" in page.inner_text(".ask-voice-bar")
          and mic.get_attribute("aria-label") == "Stop recording")
    page.wait_for_function("() => document.querySelector('.ask-rec-time').textContent.startsWith('0:01')", timeout=8000)
    timer = page.inner_text(".ask-rec-time")
    check(f"[{tag}] the time runs ({timer})", re.fullmatch(r"0:0[1-9] of 1:00", timer) is not None, timer)
    check(f"[{tag}] no sideways scroll while recording", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"voice-recording-{tag}.png"))
    check(f"[{tag}] the recording is not sent while it runs", not stt.requests)
    mic.click()
    page.wait_for_function("() => document.querySelector('#ask-input').value.length > 0", timeout=20000)
    value = page.input_value("#ask-input")
    check(f"[{tag}] the words are in the question box", value == TRANSCRIPT, value)
    check(f"[{tag}] the page says to check them and that nothing was sent to the AI", "Nothing has been sent to the AI." in page.inner_text("#ask-voice-line"))
    check(f"[{tag}] the microphone is released", streams_ended(page))
    check(f"[{tag}] the row is gone and the button is back", not page.is_visible(".ask-voice-bar") and mic.get_attribute("aria-label") == "Record your question")
    sent = stt.requests[-1] if stt.requests else {}
    clip = (sent.get("fields") or {}).get("file") or {}
    check(f"[{tag}] one clip reached the transcription server as multipart with the model",
          len(stt.requests) == 1 and sent["path"] == "/v1/audio/transcriptions" and sent["fields"].get("model") == "fake-whisper"
          and sent["fields"].get("response_format") == "json" and clip.get("filename", "").startswith("recording.") and clip.get("bytes", 0) > 400,
          json.dumps(sent)[:300])
    check(f"[{tag}] the clip is webm, ogg or mp4 audio with its own magic bytes",
          clip.get("head", "").startswith(("1a45dfa3", "4f676753")) or clip.get("head", "")[8:16] == "66747970", str(clip))
    check(f"[{tag}] nothing went to the AI and nothing is in the conversation", not fake.requests and page.locator(".ask-msg").count() == 0)
    check(f"[{tag}] no sideways scroll with the words in the box", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"voice-words-{tag}.png"))

    # --- the person sends: only now does the AI come into it, and the chat has its own consent
    page.fill("#ask-input", TRANSCRIPT + " (edited)")
    page.click("#ask-send")
    page.wait_for_selector("#sheet-ai-consent[open]")
    check(f"[{tag}] Send is what leads to the AI: the chat's own consent sheet opens", "your messages in this conversation" in page.inner_text("#sheet-ai-consent"))
    check(f"[{tag}] the AI has seen nothing yet", not fake.chat_requests)
    page.click("#sheet-ai-consent >> text=Not now")
    page.wait_for_function("() => !document.querySelector('#sheet-ai-consent').open")

    # --- a second recording is added after what is already typed
    page.fill("#ask-input", "Also,")
    mic.click()
    page.wait_for_selector(".ask-mic.recording", timeout=15000)
    page.wait_for_timeout(1200)
    mic.click()
    page.wait_for_function("() => document.querySelector('#ask-input').value.length > 6", timeout=20000)
    check(f"[{tag}] new words follow what was already typed", page.input_value("#ask-input") == f"Also, {TRANSCRIPT}", page.input_value("#ask-input"))
    check(f"[{tag}] consent was asked once, not again", len(stt.requests) == 2 and "Agree and record" not in page.inner_text("#sheet-ai-consent"))

    # --- Discard, leaving the tab, Escape: nothing is sent and the microphone is released
    before = len(stt.requests)
    page.fill("#ask-input", "")
    mic.click()
    page.wait_for_selector(".ask-mic.recording", timeout=15000)
    page.click(".ask-voice-cancel")
    page.wait_for_function("() => !document.querySelector('.ask-mic').classList.contains('recording')")
    page.wait_for_timeout(300)
    check(f"[{tag}] Discard sends nothing, keeps nothing and releases the microphone",
          len(stt.requests) == before and page.input_value("#ask-input") == "" and streams_ended(page) and "Nothing was kept." in page.inner_text("#ask-voice-line"))
    mic.click()
    page.wait_for_selector(".ask-mic.recording", timeout=15000)
    page.click("#tab-today")
    page.wait_for_function("() => !document.querySelector('.ask-mic').classList.contains('recording')")
    page.wait_for_timeout(300)
    check(f"[{tag}] leaving the Ask tab ends the recording without sending it", len(stt.requests) == before and streams_ended(page))
    page.click("#tab-ask")
    page.wait_for_selector("#view-ask:not([hidden])")
    mic.click()
    page.wait_for_selector(".ask-mic.recording", timeout=15000)
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.querySelector('.ask-mic').classList.contains('recording')")
    check(f"[{tag}] Escape ends a recording without sending it", len(stt.requests) == before)
    check(f"[{tag}] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def sixty_seconds(browser: Any, admin: Any, stt: FakeStt, base: str) -> None:
    """The recording stops by itself at 60 seconds (the page's clock is moved forward; the clip itself is a second or two)."""
    ctx, page, errors = new_page(browser, admin, base, 375, 812, "light", (TRACK_STUB,))
    stt.requests.clear()
    page.clock.install()
    open_ask(page)
    page.click("#ask-mic")
    page.wait_for_selector(".ask-mic.recording", timeout=15000)
    page.wait_for_timeout(1500)
    page.clock.fast_forward(61000)
    page.wait_for_function("() => document.querySelector('#ask-input').value.length > 0", timeout=20000)
    check("[60 s] the recording stops by itself at the limit and is sent", len(stt.requests) == 1 and streams_ended(page))
    check("[60 s] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def refusals(browser: Any, admin: Any, stt: FakeStt, base: str) -> None:
    stt.requests.clear()
    ctx, page, errors = new_page(browser, admin, base, 375, 812, "light", (DENIED_STUB,))
    open_ask(page)
    page.click("#ask-mic")
    page.wait_for_function("() => document.querySelector('#ask-voice-line') && document.querySelector('#ask-voice-line').textContent.length > 0")
    line = page.inner_text("#ask-voice-line")
    check("[refused] a blocked microphone gets one plain line and nothing is sent",
          line == "The microphone is blocked for this site. Allow it in your browser's settings, or type your question." and not stt.requests, line)
    check("[refused] the person can still type and the button is usable again", page.is_enabled("#ask-input") and page.is_enabled("#ask-mic") and not overflow(page))
    ctx.close()
    ctx, page, errors = new_page(browser, admin, base, 375, 812, "light", (NO_RECORDER_STUB,))
    open_ask(page)
    page.wait_for_function("() => document.querySelector('#ask-voice-line') && document.querySelector('#ask-voice-line').textContent.length > 0")
    line = page.inner_text("#ask-voice-line")
    check("[no MediaRecorder] one line explains it and the button is off",
          line == "This browser cannot record audio. Type your question instead." and page.is_disabled("#ask-mic") and not stt.requests, line)
    check("[no MediaRecorder] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def read_aloud(browser: Any, admin: Any, fake: FakeAi, base: str, out: Path) -> None:
    status = admin.json("GET", "/api/ai/status")
    if not status["consent"]["chat"]:
        admin.json("POST", "/api/ai/consent", {"provider_id": status["provider"]["id"], "purpose": "chat", "skip_preview": True})
    original = FakeAi.reply

    def with_links(self: FakeAi, body: dict[str, Any]) -> dict[str, Any]:
        answer = original(self, body)
        if "answer" in answer:
            answer["answer"] += " See /learn/potassium and https://example.com/more for details."
        return answer

    FakeAi.reply = with_links  # type: ignore[method-assign]
    try:
        ctx, page, errors = new_page(browser, admin, base, 375, 812, "light", (SPEECH_STUB,))
        open_ask(page)
        check("[read aloud] the switch is there when the device has its own voice", page.is_visible("#ask-read-aloud") and not page.is_visible(".ask-read-note"))
        check("[read aloud] it is off by default", not page.is_checked("#ask-read-aloud"))
        page.fill("#ask-input", "How much potassium can I have?")
        page.click("#ask-send")
        page.wait_for_selector(".ask-msg.assistant.kind-answer", timeout=20000)
        check("[read aloud] nothing is spoken while the switch is off", page.evaluate("() => window.__spoken.length") == 0)
        page.check("#ask-read-aloud")
        page.fill("#ask-input", "How much potassium can I have, again?")
        page.click("#ask-send")
        page.wait_for_function("() => window.__spoken.length === 1", timeout=20000)
        spoken = page.evaluate("() => window.__spoken[0]")
        check("[read aloud] the answer is spoken with the on-device voice", spoken["voice"] == "Device Voice" and spoken["local"] is True and spoken["lang"] == "en-US", json.dumps(spoken))
        check("[read aloud] the spoken text is the answer without links, handbook paths or cards",
              "potassium limit is 2,500 mg" in spoken["text"] and "/learn" not in spoken["text"] and "http" not in spoken["text"] and "From the app" not in spoken["text"], spoken["text"])
        check("[read aloud] a Stop reading button is offered while speaking", page.is_visible(".ask-stop-reading"))
        page.click(".ask-stop-reading")
        check("[read aloud] it cancels the speech", page.evaluate("() => window.__cancelled || 0") >= 1 and not page.is_visible(".ask-stop-reading"))
        page.screenshot(path=str(out / "shots" / "read-aloud.png"))
        page.reload()
        page.wait_for_selector("#tab-ask:not([hidden])")
        page.click("#tab-ask")
        page.wait_for_selector("#ask-read-aloud")
        check("[read aloud] the choice is remembered on this device", page.is_checked("#ask-read-aloud"))
        page.uncheck("#ask-read-aloud")
        check("[read aloud] switching it off forgets it", page.evaluate("() => localStorage.getItem('kh.ask.readAloud')") is None)
        check("[read aloud] no console or page errors", not errors, "; ".join(errors[:3]))
        ctx.close()
        ctx, page, errors = new_page(browser, admin, base, 375, 812, "light", (SPEECH_STUB, ONLY_ONLINE_VOICES))
        open_ask(page)
        page.wait_for_selector(".ask-read-note:not([hidden])", timeout=8000)
        check("[read aloud] with only an online voice the switch is hidden and a note says why",
              not page.is_visible("#ask-read-aloud") and "no voice of its own" in page.inner_text(".ask-read-note"))
        page.screenshot(path=str(out / "shots" / "read-aloud-no-voice.png"))
        check("[read aloud] no console or page errors without a device voice", not errors, "; ".join(errors[:3]))
        ctx.close()
    finally:
        FakeAi.reply = original  # type: ignore[method-assign]


def switches(browser: Any, admin: Any, base: str) -> None:
    admin.json("PATCH", "/api/admin/settings", {"ai.voice_enabled": False})
    ctx, page, errors = new_page(browser, admin, base, 375, 812, "light")
    open_ask(page)
    page.wait_for_timeout(500)
    check("[switch off] no microphone button while voice is switched off", not page.is_visible("#ask-mic"))
    check("[switch off] the status says so", admin.json("GET", "/api/ai/status")["features"]["voice"] is False)
    resp = admin.call("POST", "/api/ai/transcribe", content=b"x" * 100, headers={"Content-Type": "audio/webm"})
    check("[switch off] the route is a 404", resp.status_code == 404, str(resp.status_code))
    ctx.close()
    admin.json("PATCH", "/api/admin/settings", {"ai.voice_enabled": True})


def admin_view(browser: Any, admin: Any, stt: FakeStt, base: str, out: Path) -> None:
    ctx, page, errors = new_page(browser, admin, base, 1280, 800, "dark")
    page.goto("/#admin")
    page.wait_for_selector("#view-admin:not([hidden])", timeout=20000)
    page.wait_for_selector(".ai-voice-admin", timeout=20000)
    page.click(".ai-voice-admin > summary")
    text = page.inner_text(".ai-voice-admin")
    check("[admin] the transcription server is shown read-only with its model and limits",
          f"127.0.0.1:{STT_PORT}" in text and "fake-whisper" in text and "60 seconds per recording" in text and "never shown" not in text.replace("set (never shown)", ""), text[:300])
    check("[admin] the key is not shown", "fake-key" not in page.content())
    stt.requests.clear()
    page.click("text=Test transcription")
    page.wait_for_function("() => document.querySelector('.ai-voice-admin .status-msg').textContent.length > 0", timeout=20000)
    result = page.inner_text(".ai-voice-admin .status-msg")
    check("[admin] Test transcription sends one second of silence and reports that the server answered",
          "answered a test recording" in result and len(stt.requests) == 1 and stt.requests[0]["fields"]["file"]["head"] == "52494646", result)
    page.screenshot(path=str(out / "shots" / "admin-voice.png"))
    page.goto("/#settings")
    page.wait_for_selector("#view-settings:not([hidden])", timeout=20000)
    page.wait_for_function("() => document.body.innerText.includes('What you agreed to send')", timeout=20000)
    consents = page.inner_text("body")
    check("[admin] the voice consent is listed as Speech to text with its host", "Voice recordings → Speech to text" in consents and f"127.0.0.1:{STT_PORT}" in consents)
    check("[admin] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def demo(browser: Any, base: str, out: Path) -> None:
    ctx = browser.new_context(viewport={"width": 375, "height": 640}, base_url=base, is_mobile=True, has_touch=True, permissions=["microphone"])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(SPEECH_STUB)
    page.goto("/?mock=1#ask")
    page.wait_for_selector("#view-ask:not([hidden])", timeout=15000)
    page.wait_for_timeout(500)
    check("[demo] no microphone, no read-aloud switch, no recording row",
          page.locator("#ask-mic").count() == 0 and page.locator("#ask-read-aloud").count() == 0 and page.locator(".ask-voice-bar").count() == 0)
    check("[demo] no sideways scroll and no page errors", not overflow(page) and not errors, "; ".join(errors))
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    global STT_PORT
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--ai-port", type=int, default=AI_PORT)
    ap.add_argument("--stt-port", type=int, default=STT_PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    STT_PORT = args.stt_port
    for port in (args.port, args.ai_port, args.stt_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port / --stt-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    key_file = out / "stt_key"
    key_file.write_text("fake-key-0123456789abcdef\n", encoding="utf-8")
    env = {"AI_ENABLED": "true", "AI_CHAT_ENABLED": "true", "AI_PROVIDER": "openai_compatible",
           "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1", "AI_MODEL": "fake-text",
           "STT_BASE_URL": f"http://127.0.0.1:{args.stt_port}/v1", "STT_MODEL": "fake-whisper", "STT_API_KEY_FILE": str(key_file),
           "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port},127.0.0.1:{args.stt_port}", "AI_SHARED_DAILY_LIMIT": "0",
           # No call may leave this machine: a proxy that does not exist for anything but the local servers.
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    fake = FakeAi(args.ai_port)
    stt = FakeStt(args.stt_port)
    try:
        server.start()
        admin = first_admin(server, "voice")
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000}})
        admin.json("PATCH", "/api/me/ai", {"opt_in": True})
        admin.json("PATCH", "/api/admin/settings", {"ai.voice_enabled": True})  # not an env lock, so the checks can switch it off
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(),
                                         args=["--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, admin, fake, stt, base, out, width, height, scheme)
                sixty_seconds(browser, admin, stt, base)
                refusals(browser, admin, stt, base)
                read_aloud(browser, admin, fake, base, out)
                switches(browser, admin, base)
                admin_view(browser, admin, stt, base, out)
                demo(browser, base, out)
            finally:
                browser.close()
        log = server.log()
        check("the server log holds neither the transcript nor the key", TRANSCRIPT not in log and "fake-key-0123456789abcdef" not in log)
        check("the transcription server was sent the key as a bearer token only", all(r["auth"] == "Bearer fake-key-0123456789abcdef" for r in stt.requests))
        admin.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        server.stop()
        fake.stop()
        stt.stop()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
