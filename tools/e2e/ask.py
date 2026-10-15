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
* the demo (``/?mock=1#ask``) shows the tab with a note about the installed app and no input;
* saving from the chat (assistant step 2, part C), after the walk: by default a "log a banana" request is a confirm card
  and nothing is saved until Save as eaten (then Undo removes it; Cancel saves nothing); with "Trust it for this
  conversation" chosen the person trusts one conversation (a confirm card until then), the save is made at once with Undo,
  and New conversation ends the trust; with "Trust it always" the save is at once; in Settings the warning sheet opens
  first, "Keep asking me" changes nothing and "I understand, trust it" does.

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
        self.banana_id = 0  # set by the harness once the food list exists
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

    def reply(self, body: dict[str, Any]) -> dict[str, Any]:
        last = str(body["messages"][-1]["content"])
        if last.startswith("RESULT of log_food"):
            return {"answer": "Saved your banana for breakfast."}
        if "log a banana" in last:  # a save: the harness gives the food_id (an exact food, so nothing is ambiguous)
            return {"call": {"tool": "log_food", "arguments": {"items": [{"food": "banana", "food_id": self.banana_id, "amount": 1}],
                                                               "meal": "breakfast"}}}
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


def entries_today(admin: Any) -> list[dict[str, Any]]:
    return admin.json("GET", "/api/log")["entries"]


def send_text(page: Any, text: str) -> None:
    page.fill("#ask-input", text)
    page.press("#ask-input", "Enter")


def open_ask(page: Any) -> None:
    page.goto("/")
    page.wait_for_selector("#tab-ask:not([hidden])", timeout=15000)
    page.click("#tab-ask")
    page.wait_for_selector("#view-ask:not([hidden])")
    page.wait_for_function("() => document.querySelector('#ask-trust') && !document.querySelector('#ask-trust').hidden")


def saving(browser: Any, admin: Any, fake: FakeAi, base: str, out: Path, width: int, height: int, scheme: str) -> None:
    tag = f"save-{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    for entry in entries_today(admin):
        admin.call("DELETE", f"/api/log/{entry['id']}")
    admin.json("PATCH", "/api/me/ai", {"trust": "ask"})

    # --- the default: a card, nothing saved until Save ---------------------------------------------------------------
    open_ask(page)
    check(f"[{tag}] the default line: Ask asks first, and there is no trust button",
          "Ask asks you before it saves." in page.inner_text("#ask-trust-line") and page.locator("#ask-trust-actions .btn").count() == 0)
    check(f"[{tag}] the link to the choice is there", page.is_visible("#ask-trust-actions >> text=Change this in Settings"))
    send_text(page, "log a banana for breakfast")
    page.wait_for_selector(".ask-pending", timeout=20000)
    card = page.inner_text(".ask-pending")
    check(f"[{tag}] the confirm card names the food, the meal and the app's totals", "Banana" in card and "Breakfast" in card and "Potassium" in card, card[:300])
    check(f"[{tag}] the text says nothing is saved yet", "Nothing has been saved yet." in page.inner_text(".kind-confirm_save .ask-text"))
    check(f"[{tag}] the card has Save as eaten, Save as planned and Cancel",
          all(page.locator(".ask-pending").get_by_role("button", name=n).count() == 1 for n in ("Save as eaten", "Save as planned", "Cancel")))
    check(f"[{tag}] nothing is in the log before Save is pressed", entries_today(admin) == [])
    check(f"[{tag}] no sideways scroll with the confirm card", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"confirm-{tag}.png"))
    page.locator(".ask-pending").get_by_role("button", name="Save as eaten").click()
    page.wait_for_selector(".ask-saved")
    saved = entries_today(admin)
    check(f"[{tag}] Save as eaten saved exactly that", len(saved) == 1 and saved[0]["status"] == "eaten" and saved[0]["meal"] == "breakfast"
          and saved[0]["food_name"].startswith("Banana"), json.dumps(saved)[:200])
    check(f"[{tag}] the saved card says what was saved and has Undo", "Saved to your log" in page.inner_text(".ask-saved")
          and page.locator(".ask-saved").get_by_role("button", name="Undo").count() == 1)
    page.screenshot(path=str(out / "shots" / f"saved-{tag}.png"))
    page.locator(".ask-saved").get_by_role("button", name="Undo").click()
    page.wait_for_selector("text=Undone.")
    check(f"[{tag}] Undo removed it", entries_today(admin) == [])
    send_text(page, "log a banana for breakfast")
    page.wait_for_selector(".ask-pending:visible >> text=Cancel", timeout=20000)
    page.locator(".ask-pending").last.get_by_role("button", name="Cancel").click()
    check(f"[{tag}] Cancel saves nothing", page.locator(".ask-pending").count() == 0 and "Not saved." in page.inner_text("#ask-thread")
          and entries_today(admin) == [])
    check(f"[{tag}] the confirm flow made no console errors", not errors, "; ".join(errors[:3]))

    # --- trust for this conversation ---------------------------------------------------------------------------------
    admin.json("PATCH", "/api/me/ai", {"trust": "conversation"})
    open_ask(page)
    check(f"[{tag}] with 'this conversation' chosen the page offers it",
          page.is_visible("#ask-trust-actions >> text=Trust it for this conversation"))
    send_text(page, "log a banana for breakfast")
    page.wait_for_selector(".ask-pending", timeout=20000)
    check(f"[{tag}] until the person trusts the conversation it is still a card", entries_today(admin) == [])
    page.locator(".ask-pending").get_by_role("button", name="Cancel").click()
    page.click("#ask-trust-actions >> text=Trust it for this conversation")
    check(f"[{tag}] the line says this conversation is trusted", "Trusted for this conversation" in page.inner_text("#ask-trust-line")
          and page.is_visible("#ask-trust-actions >> text=Stop trusting"))
    send_text(page, "log a banana for breakfast")
    page.wait_for_selector(".ask-saved", timeout=20000)
    saved = entries_today(admin)
    check(f"[{tag}] trusted: saved at once, with the assistant's words and Undo", len(saved) == 1 and page.locator(".ask-pending").count() == 0
          and "Saved your banana for breakfast." in page.inner_text(".kind-answer .ask-text"), json.dumps(saved)[:200])
    check(f"[{tag}] no sideways scroll with the saved card", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"trusted-{tag}.png"))
    page.click("#tab-today")
    page.wait_for_selector("#view-today:not([hidden])")
    page.wait_for_function("() => document.querySelector('#view-today').innerText.includes('Banana')", timeout=10000)
    check(f"[{tag}] Today shows what Ask saved, without a reload", True)
    page.click("#tab-ask")
    page.wait_for_selector("#view-ask:not([hidden])")
    page.locator(".ask-saved").get_by_role("button", name="Undo").click()
    page.wait_for_selector("text=Undone.")
    check(f"[{tag}] Undo removed the trusted save", entries_today(admin) == [])
    page.click("#tab-today")
    page.wait_for_function("() => !document.querySelector('#view-today').innerText.includes('Banana')", timeout=10000)
    check(f"[{tag}] and Today no longer shows it", True)
    page.click("#tab-ask")
    page.wait_for_selector("#view-ask:not([hidden])")
    page.click("#ask-new")
    check(f"[{tag}] New conversation ends the trust", "Ask asks you before it saves." in page.inner_text("#ask-trust-line")
          and page.is_visible("#ask-trust-actions >> text=Trust it for this conversation"))
    send_text(page, "log a banana for breakfast")
    page.wait_for_selector(".ask-pending", timeout=20000)
    check(f"[{tag}] and the next request is a card again", entries_today(admin) == [])

    # --- trust always ------------------------------------------------------------------------------------------------
    admin.json("PATCH", "/api/me/ai", {"trust": "always"})
    open_ask(page)
    check(f"[{tag}] 'always' says so", "Trusted always" in page.inner_text("#ask-trust-line"))
    send_text(page, "log a banana for breakfast")
    page.wait_for_selector(".ask-saved", timeout=20000)
    check(f"[{tag}] always: saved at once", len(entries_today(admin)) == 1)
    page.locator(".ask-saved").get_by_role("button", name="Undo").click()
    page.wait_for_selector("text=Undone.")
    check(f"[{tag}] and undone", entries_today(admin) == [])

    # --- the warning sheet in Settings ---------------------------------------------------------------------------------
    admin.json("PATCH", "/api/me/ai", {"trust": "ask"})
    page.goto("/")
    page.wait_for_selector("#settings-open:not([hidden])", timeout=15000)
    page.click("#settings-open")
    page.wait_for_selector("#set-ai-trust", timeout=15000)
    check(f"[{tag}] three choices, the default marked recommended",
          page.locator("#set-ai-trust input[type=radio]").count() == 3 and "(recommended)" in page.inner_text("#set-ai-trust")
          and page.locator("#set-ai-trust input[value=ask]").is_checked())
    page.locator("#set-ai-trust label.check", has_text="Trust it always").click()
    page.wait_for_selector("#sheet-ai-trust[open]")
    sheet = page.inner_text("#sheet-ai-trust")
    check(f"[{tag}] the warning opens first", "The assistant will save food and recipes without asking you first." in sheet
          and "It can pick the wrong food or the wrong amount." in sheet and "undo each save" in sheet and "Photo and label readings" in sheet, sheet[:300])
    check(f"[{tag}] nothing is changed while the warning is open", admin.json("GET", "/api/me/ai")["settings"]["trust"] == "ask")
    try:  # the sheet moves the focus a moment after it opens
        page.wait_for_function("() => document.activeElement && document.activeElement.textContent === 'Keep asking me'", timeout=3000)
        focused = True
    except Exception:  # noqa: BLE001 - reported as a failed check
        focused = False
    check(f"[{tag}] the focus starts on 'Keep asking me'", focused)
    check(f"[{tag}] no sideways scroll in the sheet", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"warning-{tag}.png"))
    page.click("#sheet-ai-trust >> text=Keep asking me")
    page.wait_for_function("() => !document.querySelector('#sheet-ai-trust').open")
    check(f"[{tag}] 'Keep asking me' changes nothing", admin.json("GET", "/api/me/ai")["settings"]["trust"] == "ask"
          and page.locator("#set-ai-trust input[value=ask]").is_checked())
    page.locator("#set-ai-trust label.check", has_text="Trust it always").click()
    page.wait_for_selector("#sheet-ai-trust[open]")
    page.click("#sheet-ai-trust >> text=I understand, trust it")
    page.wait_for_function("() => document.querySelector('#set-ai-trust input[value=always]').checked")
    check(f"[{tag}] 'I understand, trust it' saves the choice", admin.json("GET", "/api/me/ai")["settings"]["trust"] == "always")
    events = [e for e in admin.json("GET", "/api/me/activity")["events"] if e["action"] == "ai.trust_changed"]
    check(f"[{tag}] the change is in the activity log", events and events[0]["details"] == {"old": "ask", "new": "always"}, json.dumps(events[:1]))
    page.locator("#set-ai-trust label.check", has_text="Ask me before every save").click()
    page.wait_for_function("() => document.querySelector('#set-ai-trust input[value=ask]').checked")
    check(f"[{tag}] going back to asking needs no warning", admin.json("GET", "/api/me/ai")["settings"]["trust"] == "ask"
          and not page.evaluate("() => document.querySelector('#sheet-ai-trust').open"))
    check(f"[{tag}] no console or page errors while saving", not errors, "; ".join(errors[:3]))
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
    env = {"AI_ENABLED": "true", "AI_CHAT_ENABLED": "true", "AI_ALLOW_TRUSTED_SAVES": "true", "AI_PROVIDER": "openai_compatible",
           "AI_PROVIDER_ROLE": "local",  # the fake AI is the local AI
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
        fake.banana_id = admin.json("GET", "/api/foods", params={"q": "Banana, raw"})["foods"][0]["id"]
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, admin, fake, base, out, width, height, scheme)
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    saving(browser, admin, fake, base, out, width, height, scheme)
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
