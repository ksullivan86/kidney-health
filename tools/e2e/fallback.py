#!/usr/bin/env python3
"""Privacy tier 3, "local first, cloud only when the local answer fails", in Chromium against a real server and two fake providers.

    python tools/e2e/fallback.py                         # ports 8082 (app), 8083 (local AI), 8084 (cloud AI)
    python tools/e2e/fallback.py --port 8082 --ai-port 8083 --cloud-port 8084 --out /tmp/kh-fallback

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED``, a local AI (a fake OpenAI-compatible server this
script runs, listed in ``AI_PRIVATE_HOSTS`` and holding the role ``local``) and a second shared provider (another fake) that
holds the role ``cloud``; meal ideas, describe a meal and photos are set to ``local_then_cloud``. The fakes count the requests
they get; the local one can be told to answer with something that is not JSON. Then, at 375x812 light and 1280x800 dark:

* the admin table offers "Local, then cloud" for photos, meal ideas and describe a meal with the one-line rule, and for Ask and
  lab report photos shows that it is not offered;
* Settings → AI ideas reads "Runs on your local AI (host); if its answer fails the app's checks, on the cloud AI (host)." for
  the three features and the plain local line for Ask;
* the first AI meal ideas request opens the consent sheet, which names both hosts, says the cloud one is used only if the local
  AI's answer fails the app's checks and has its own tick box; nothing reaches either AI before "Agree and send";
* with the tick box left off and a local answer that is not JSON, the page shows the local failure and the line "The cloud AI
  (host) was not asked because you have not agreed to send this there.", the cloud AI got **no** request, and "Allow the cloud AI
  (host) as the fallback" opens the sheet for the cloud host alone; after agreeing, the same failure sends one request to the
  cloud AI and the page says "... so the cloud AI (host) answered." with the ideas it returned;
* "What will be sent?" shows the local request and, under it, that a second request may go to the cloud host only if the local
  answer fails the checks;
* a good local answer never reaches the cloud AI; AI activity lists both calls of a fallback with the line that links them; no
  sideways scroll, no console errors.

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes ``<out>/report.json`` and
screenshots in ``<out>/shots/``; exit status 1 on any failure. The server and the fakes are always stopped.
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

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "fallback"
PORT, AI_PORT, CLOUD_PORT = 8082, 8083, 8084
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class FakeAi:
    """``/v1/models`` and ``/v1/chat/completions``; answers meal ideas from the candidates it is sent; remembers every request.
    With ``broken`` set it answers with something that is not JSON (what a small local model sometimes does)."""

    def __init__(self, port: int, name: str) -> None:
        self.name, self.port, self.broken = name, port, False
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
                self._send({"object": "list", "data": [{"id": "fake-text", "object": "model"}, {"id": "fake-vision", "object": "model"}]})

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.requests.append(body)
                text = str(body["messages"][-1]["content"])
                probe = text.startswith("Reply with the JSON object") or "What colour is this square" in text  # a connection test
                # (the repair turn the app sends after a bad answer is not a "TASK:" either, so it gets the same non-JSON back)
                content = "I would suggest something light." if outer.broken and not probe else json.dumps(outer.reply(text))
                self._send({"id": "fake", "object": "chat.completion", "model": body.get("model"),
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 900, "completion_tokens": 60}})

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def task_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if str(r["messages"][-1]["content"]).startswith("TASK:")]

    def reply(self, text: str) -> dict[str, Any]:
        if text.startswith("Reply with the JSON object"):
            return {"ok": "yes"}
        if "What colour is this square" in text:
            return {"color": "red"}
        if text.startswith("TASK: next_meal"):
            raw = text.split("<data>\n", 1)[1].split("\n</data>", 1)[0]
            data = json.loads(raw.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
            c = data.get("candidates") or []
            ideas = [{"theme": "light", "items": [{"food_id": c[0]["id"], "quarters": c[0]["portion_quarters"]}],
                      "reason_codes": ["low_potassium"], "handbook": []}] if c else []
            return {"status": "ok", "refusal": "none", "ideas": ideas}
        return {"status": "refused", "refusal": "outside_scope", "ideas": []}

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def close_sheets(page: Any) -> None:
    page.evaluate("() => document.querySelectorAll('dialog[open]').forEach((d) => d.close())")


def ask_for_ideas(page: Any) -> None:
    """Open the AI meal ideas sheet from the Add view and press Ask AI for ideas."""
    page.goto("/#add")
    page.wait_for_selector("#ai-add-slot:not([hidden]) >> text=AI meal ideas", timeout=15000)
    page.click("#ai-add-slot >> text=AI meal ideas")
    page.wait_for_selector("#sheet-ai[open]")
    page.click("#sheet-ai >> text=Ask AI for ideas")


def walk(browser: Any, admin: Any, local: FakeAi, cloud: FakeAi, ids: dict[str, int], base: str, out: Path, width: int, height: int,
         scheme: str) -> None:
    tag = f"{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    # the consent step's 409 is the app's own answer, and the browser logs every 4xx as a console error
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    # a fresh start for this walk: no consent to either host, nothing kept, both fakes quiet
    for pid in (ids["local"], ids["cloud"]):
        for purpose in ("text", "photos"):
            admin.call("DELETE", f"/api/ai/consent/{pid}", params={"purpose": purpose})
    admin.call("DELETE", "/api/ai/audit")
    local.requests.clear(), cloud.requests.clear()
    local.broken = True
    cloud_host, local_host = f"127.0.0.1:{cloud.port}", f"127.0.0.1:{local.port}"

    # 1. Server administration: the table. Settings: the per-person lines.
    page.goto("/#admin")
    page.wait_for_selector("#ai-routing table", state="attached", timeout=15000)
    header = [t.strip() for t in page.locator("#ai-routing thead th").all_inner_texts()]
    check(f"[{tag}] the admin table has the column Local, then cloud", header == ["Feature", "Local", "Cloud", "Off", "Local, then cloud"], str(header))
    rule = page.inner_text("#ai-routing .ai-route-rule")
    check(f"[{tag}] the one-line rule is under the table",
          "The cloud AI is asked only if the local AI's answer fails the app's checks." in rule
          and "is not asked when the local AI cannot be reached, takes too long, is over its limit or declines the question" in rule, rule)
    ask_row = page.locator("#ai-routing tbody tr", has_text="Ask").first
    check(f"[{tag}] Ask is not offered Local, then cloud", ask_row.locator("input").count() == 3 and ask_row.locator(".ai-route-na").count() == 1)
    check(f"[{tag}] meal ideas, describe and photos are on Local, then cloud",
          all(page.is_checked(f'#ai-routing input[aria-label="{label}: Local, then cloud"]')
              for label in ("Meal ideas", "Describe a meal", "Photos (labels and plates)")))
    page.screenshot(path=str(out / "shots" / f"admin-{tag}.png"), full_page=True)
    page.goto("/#settings")
    page.wait_for_selector("#set-ai-slot .ai-routing-lines", timeout=15000)
    lines = page.inner_text(".ai-routing-lines")
    expected = f"Runs on your local AI ({local_host}); if its answer fails the app's checks, on the cloud AI ({cloud_host})."
    check(f"[{tag}] Settings reads the local-then-cloud line for meal ideas", f"Meal ideas: {expected}" in lines, lines[:400])
    check(f"[{tag}] Ask keeps the plain local line", f"Ask: Runs on your local AI ({local_host})." in lines, lines[:400])
    check(f"[{tag}] Settings offers to agree to the cloud AI for meal ideas",
          page.locator(".ai-routing-lines li", has_text="Meal ideas").locator("button", has_text="Allow the cloud AI").count() == 1)
    page.screenshot(path=str(out / "shots" / f"settings-{tag}.png"), full_page=True)

    # 2. The first request: the sheet names both hosts, says when the cloud one is used, and nothing is sent before Agree.
    ask_for_ideas(page)
    page.wait_for_selector("#sheet-ai-consent[open]")
    sheet = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the consent sheet names the local host and the cloud host", local_host in sheet and cloud_host in sheet, sheet[:400])
    check(f"[{tag}] it says the cloud AI is used only if the local answer fails the app's checks",
          "Only if the local AI's answer fails the app's checks, the same request goes a second time to" in sheet
          and "The cloud AI is asked only if the local AI's answer fails the app's checks." in sheet, sheet[:600])
    check(f"[{tag}] it has its own tick box for the cloud AI, off by default",
          page.locator("#sheet-ai-consent label", has_text=f"Also allow the cloud AI ({cloud_host}) as the fallback").count() == 1
          and not page.is_checked("#sheet-ai-consent input[id^=ai-cloud-fallback]"))
    check(f"[{tag}] nothing was sent to either AI before Agree", not local.task_requests and not cloud.task_requests)
    check(f"[{tag}] no sideways scroll with the sheet", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"consent-{tag}.png"))
    page.click("#sheet-ai-consent >> text=Agree and send")

    # 3. The local answer is not JSON and the person did not agree to the cloud: the failure, the line, no cloud request.
    page.wait_for_selector("#sheet-ai .ai-fallback-line", timeout=30000)
    line = page.inner_text("#sheet-ai .ai-fallback-line")
    check(f"[{tag}] the page says the cloud AI was not asked, and why",
          line == f"The local AI's answer did not pass the app's checks. The cloud AI ({cloud_host}) was not asked because you have not agreed to send this there.", line)
    check(f"[{tag}] the cloud AI got no request", not cloud.requests, str(len(cloud.requests)))
    check(f"[{tag}] the local AI was asked (its answer and one repair turn)", len(local.task_requests) >= 1)
    page.screenshot(path=str(out / "shots" / f"not-asked-{tag}.png"))

    # 4. Agree to the cloud AI from the answer; the same failure now sends one request there.
    page.click("#sheet-ai >> text=Allow the cloud AI")
    page.wait_for_selector("#sheet-ai-consent[open]")
    allow = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the sheet for the cloud AI alone says it is the fallback", cloud_host in allow and "set as the fallback" in allow, allow[:400])
    page.click("#sheet-ai-consent >> text=Agree and send")
    page.wait_for_function("() => !document.querySelector('#sheet-ai-consent').open")
    local_before = len(local.task_requests)
    page.click("#sheet-ai >> text=Ask AI for ideas")
    page.wait_for_selector("#sheet-ai .ai-idea", timeout=30000)
    line = page.inner_text("#sheet-ai .ai-fallback-line")
    check(f"[{tag}] after agreeing, the cloud AI answered and the page says so",
          line == f"The local AI's answer did not pass the app's checks, so the cloud AI ({cloud_host}) answered.", line)
    check(f"[{tag}] the cloud AI got exactly one request and the local AI was asked first",
          len(cloud.task_requests) == 1 and len(local.task_requests) > local_before, f"cloud {len(cloud.task_requests)}")
    card = page.inner_text("#sheet-ai .ai-idea")
    check(f"[{tag}] the idea card is labelled as the cloud AI's", "AI idea" in card and "checked against your targets" in card, card[:300])
    check(f"[{tag}] no sideways scroll with the answer", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"cloud-answered-{tag}.png"))

    # 5. What will be sent? shows the local request and the second one that may go to the cloud.
    page.click("#sheet-ai >> text=What will be sent?")
    page.wait_for_selector("#sheet-ai-sent[open]")
    sent = page.inner_text("#sheet-ai-sent")
    check(f"[{tag}] What will be sent? shows the local request first", local_host in sent.split("Only if the local AI's answer fails")[0], sent[:300])
    check(f"[{tag}] and says a second request may go to the cloud host only if the local answer fails the checks",
          f"A second request with the same content may go to {cloud_host}, but only if the local AI's answer fails the app's checks." in sent, sent[:800])
    page.screenshot(path=str(out / "shots" / f"what-will-be-sent-{tag}.png"))
    close_sheets(page)

    # 6. AI activity lists both calls of a fallback.
    page.goto("/#settings")
    page.wait_for_selector("#set-ai-slot summary:has-text('AI activity')")
    page.click("#set-ai-slot summary:has-text('AI activity')")
    page.wait_for_selector("#set-ai-slot .ai-event")
    activity = page.inner_text("#set-ai-slot .ai-activity")
    check(f"[{tag}] AI activity names both hosts", local_host in activity and cloud_host in activity, activity[:400])
    for summary in page.locator("#set-ai-slot .ai-event summary").all():
        summary.click()
    rows = page.inner_text("#set-ai-slot .ai-activity")
    check(f"[{tag}] the cloud call's row says it was sent because the local answer failed",
          "A second request, sent because the local AI's answer did not pass the app's checks." in rows, rows[:600])
    # 7. A good local answer never reaches the cloud AI.
    local.broken = False
    admin.call("DELETE", "/api/ai/audit")  # forgets the cloud answer kept for ten minutes
    before = len(cloud.requests)
    ask_for_ideas(page)
    page.wait_for_selector("#sheet-ai .ai-idea", timeout=30000)
    check(f"[{tag}] a good local answer has no fallback line", page.locator("#sheet-ai .ai-fallback-line").count() == 0)
    check(f"[{tag}] and the cloud AI got no new request", len(cloud.requests) == before, f"{len(cloud.requests)} vs {before}")
    close_sheets(page)

    check(f"[{tag}] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--ai-port", type=int, default=AI_PORT, help="the local AI (a fake OpenAI-compatible server)")
    ap.add_argument("--cloud-port", type=int, default=CLOUD_PORT, help="the cloud AI (a second fake)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    for port in (args.port, args.ai_port, args.cloud_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port / --cloud-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"AI_ENABLED": "true", "AI_PROVIDER": "openai_compatible", "AI_PROVIDER_ROLE": "local",  # the first fake is the local AI
           "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1", "AI_MODEL": "fake-text", "AI_VISION_MODEL": "fake-vision",
           "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port},127.0.0.1:{args.cloud_port}", "AI_SHARED_DAILY_LIMIT": "0",
           # No call may leave this machine: a proxy that does not exist for anything but the local servers.
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    local, cloud = FakeAi(args.ai_port, "local"), FakeAi(args.cloud_port, "cloud")
    try:
        server.start()
        admin = first_admin(server, "fallback")
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                        "carbs_per_meal_g": 60}})
        admin.json("PATCH", "/api/me/ai", {"opt_in": True})
        # The second shared provider: another fake, holding the role "cloud" (a role needs no private host; the fake is listed
        # in AI_PRIVATE_HOSTS only because it runs on this machine).
        made = admin.json("POST", "/api/admin/ai-providers", {"preset": "ollama", "model": "fake-text", "vision_model": "fake-vision",
                                                              "base_url": f"http://127.0.0.1:{args.cloud_port}/v1"})
        providers = admin.json("GET", "/api/admin/ai-providers")["providers"]
        local_id = next(p["id"] for p in providers if p["locked"])
        ids = {"local": local_id, "cloud": int(made["id"])}
        admin.json("PUT", "/api/admin/ai-routing", {"cloud_provider": ids["cloud"], "photos": "local_then_cloud",
                                                    "meal_ideas": "local_then_cloud", "describe": "local_then_cloud"})
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, admin, local, cloud, ids, base, out, width, height, scheme)
            finally:
                browser.close()
        admin.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        server.stop()
        local.stop()
        cloud.stop()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
