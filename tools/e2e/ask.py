#!/usr/bin/env python3
"""The Ask screen (the in-app chat) in Chromium, against a real server and a fake OpenAI-compatible provider.

    python tools/e2e/ask.py                          # ports 8074 (app) and 8075 (fake provider)
    python tools/e2e/ask.py --port 8074 --ai-port 8075 --out /tmp/kh-ask

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED`` and ``AI_CHAT_ENABLED``, its AI provider
pointed at a fake server this script runs (the fake answers the chat's step protocol: a ``get_today`` call, then an
answer built from the tool result; a question containing "withhold" gets an answer about insulin doses), finishes
first-run setup, sets targets and opts the person in, then drives the page at 375x812 light and 1280x800 dark:

* the Ask tab is shown (six tabs fit) and Enter / Shift+Enter behave (a new line sends nothing);
* the first send opens the consent sheet with the chat's own text, and nothing reaches the provider before "Agree";
* the answer is shown as text with "From the app" figures, after two model calls for one question;
* "I feel shaky and low" gets the Treating a low card and the line under it without any call to the provider;
* an answer about insulin doses is withheld (the notice, never the text), "New conversation" clears the list, the arrow
  keys move between the visible tabs, no sideways scroll at any step, no console errors;
* the demo (``/?mock=1#ask``) shows the tab with a note about the installed app and no input.

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes
``<out>/report.json`` and screenshots in ``<out>/shots/``; exit status 1 on any failure. The server and the fake
provider are always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "ask"
PORT, AI_PORT = 8074, 8075
RESULTS: list[dict[str, Any]] = []
NOTE = "Answers come from an AI model; every number is the app's own. Not medical advice."


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class FakeAi:
    """``/v1/models`` and ``/v1/chat/completions``; remembers every request."""

    def __init__(self, port: int) -> None:
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
                self._send({"object": "list", "data": [{"id": "fake-text", "object": "model"}]})

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.requests.append(body)
                content = json.dumps(outer.reply(body))
                self._send({"id": "fake", "object": "chat.completion", "model": body.get("model"),
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 900, "completion_tokens": 60}})

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def chat_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if 'You are "Ask"' in str(r["messages"][0]["content"])]

    @staticmethod
    def reply(body: dict[str, Any]) -> dict[str, Any]:
        last = str(body["messages"][-1]["content"])
        if last.startswith("RESULT of get_today"):
            data = json.loads(last.split("<data>\n", 1)[1].split("\n</data>", 1)[0].replace("\\u003c", "<"))
            limit = data["nutrients"]["potassium_mg"]["target"]["max"]
            return {"answer": f"Your potassium limit is {limit:,} mg today, and a plain slice of white bread fits."}
        if "withhold" in last:
            return {"answer": "Take 4 units of insulin before you eat that."}
        return {"call": {"tool": "get_today", "arguments": {}}}

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def walk(browser: Any, admin: Any, fake: FakeAi, base: str, out: Path, width: int, height: int, scheme: str) -> None:
    tag = f"{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    # the consent step's 409 is the app's own answer, and the browser logs every 4xx as a console error
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    status = admin.json("GET", "/api/ai/status")
    if status["consent"]["chat"]:
        admin.call("DELETE", f"/api/ai/consent/{status['provider']['id']}", params={"purpose": "chat"})
    fake.requests.clear()
    page.goto("/")
    page.wait_for_selector("#tab-ask:not([hidden])", timeout=15000)
    check(f"[{tag}] the Ask tab is shown with the chat on and the tab bar fits ({page.locator('.tab:visible').count()} tabs)",
          not overflow(page))
    page.click("#tab-ask")
    page.wait_for_selector("#view-ask:not([hidden])")
    check(f"[{tag}] the line under the input", page.inner_text("#ask-note") == NOTE)
    page.fill("#ask-input", "first line")
    page.press("#ask-input", "Shift+Enter")
    page.keyboard.type("second line")
    check(f"[{tag}] Shift+Enter is a new line and sends nothing",
          page.input_value("#ask-input") == "first line\nsecond line" and not fake.chat_requests)
    page.fill("#ask-input", "How much potassium can I have?")
    page.press("#ask-input", "Enter")
    page.wait_for_selector("#sheet-ai-consent[open]")
    sheet = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the first send asks for consent with the chat's own text",
          "your messages in this conversation" in sheet and "Never sent: your name" in sheet, sheet[:200])
    check(f"[{tag}] nothing was sent before agreeing", not fake.chat_requests)
    page.screenshot(path=str(out / "shots" / f"consent-{tag}.png"))
    page.click("#sheet-ai-consent >> text=Agree and send")
    page.wait_for_selector(".ask-msg.assistant.kind-answer", timeout=20000)
    answer = page.inner_text(".ask-msg.assistant.kind-answer .ask-text")
    figures = page.inner_text(".ask-numbers")
    check(f"[{tag}] the answer is shown", "potassium limit is 2,500 mg" in answer, answer)
    check(f"[{tag}] From the app shows the app's own figures", "From the app" in figures and "Potassium" in figures and "2,500" in figures, figures[:200])
    check(f"[{tag}] one question took two model calls", len(fake.chat_requests) == 2, str(len(fake.chat_requests)))
    check(f"[{tag}] the question is in the list as text", page.inner_text(".ask-msg.user").strip().endswith("How much potassium can I have?"))
    check(f"[{tag}] no sideways scroll with an answer", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"answer-{tag}.png"))
    calls = len(fake.chat_requests)
    page.fill("#ask-input", "I feel shaky and low")
    page.click("#ask-send")
    page.wait_for_selector(".ask-msg.assistant.kind-treat_low")
    low = page.inner_text(".ask-msg.kind-treat_low")
    check(f"[{tag}] a low gets the card and the line without any call to the provider",
          "Treating a low" in low and "Treat the low first. When you feel better, ask again." in low and len(fake.chat_requests) == calls, low[:200])
    check(f"[{tag}] no sideways scroll with the card", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"low-{tag}.png"))
    page.fill("#ask-input", "withhold this please")
    page.click("#ask-send")
    page.wait_for_selector(".ask-msg.assistant.kind-withheld")
    withheld = page.inner_text(".ask-msg.kind-withheld")
    check(f"[{tag}] an answer about doses is withheld and its text never shown",
          "This answer was not shown because it touched on medicine or insulin doses." in withheld and "insulin before" not in withheld, withheld)
    check(f"[{tag}] New conversation is offered and clears the list", page.is_visible("#ask-new"))
    page.click("#ask-new")
    check(f"[{tag}] the list is empty again", page.locator(".ask-msg").count() == 0 and page.is_visible("#ask-intro"))
    page.focus("#tab-ask")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("document.activeElement && document.activeElement.id === 'tab-profile'")
    check(f"[{tag}] the arrow keys move between the visible tabs", True)
    check(f"[{tag}] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def demo(browser: Any, base: str, out: Path) -> None:
    for width, scheme in ((320, "light"), (375, "dark")):
        ctx = browser.new_context(viewport={"width": width, "height": 640}, color_scheme=scheme, base_url=base, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("/?mock=1#ask")
        page.wait_for_selector("#view-ask:not([hidden])", timeout=15000)
        note = page.inner_text("#ask-demo")
        tag = f"demo-{width}-{scheme}"
        check(f"[{tag}] the tab and the note", page.is_visible("#tab-ask") and "installed app" in note and "AI provider" in note, note)
        check(f"[{tag}] no input, no sideways scroll, no page errors",
              not page.is_visible("#ask-input") and not page.is_visible("#ask-send") and not overflow(page) and not errors, "; ".join(errors))
        page.screenshot(path=str(out / "shots" / f"{tag}.png"))
        ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--ai-port", type=int, default=AI_PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    for port in (args.port, args.ai_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"AI_ENABLED": "true", "AI_CHAT_ENABLED": "true", "AI_PROVIDER": "openai_compatible",
           "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1", "AI_MODEL": "fake-text",
           "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port}", "AI_SHARED_DAILY_LIMIT": "0",
           # No call may leave this machine: a proxy that does not exist for anything but the local servers.
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    fake = FakeAi(args.ai_port)
    try:
        server.start()
        admin = first_admin(server, "ask")
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000}})
        admin.json("PATCH", "/api/me/ai", {"opt_in": True})
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, admin, fake, base, out, width, height, scheme)
                demo(browser, base, out)
            finally:
                browser.close()
        admin.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        server.stop()
        fake.stop()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
