#!/usr/bin/env python3
"""A local AI and a cloud AI, both from the environment (docs/ai.md), in Chromium against a real server and two fake providers.

    python tools/e2e/cloud_env.py                        # ports 8087 (app), 8088 (local AI), 8089 (cloud AI)
    python tools/e2e/cloud_env.py --port 8087 --ai-port 8088 --cloud-port 8089 --out /tmp/kh-cloud-env

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED``, a LiteLLM-style local AI (``AI_PROVIDER`` with
``AI_PROVIDER_ROLE=local`` and its own key file) and a LiteLLM-style cloud AI (``AI_CLOUD_PROVIDER`` with ``AI_CLOUD_UPSTREAM=Anthropic``
and another key file), both listed in ``AI_PRIVATE_HOSTS``, with every ``AI_ROUTE_*`` set in the environment (photos and lab reports
local, meal ideas, describe a meal and Ask in the cloud). The two fakes remember every request and the key it came with. Then, at
375x812 light and 1280x800 dark:

* Server administration → AI providers lists both providers as "Set by the server" with no Edit and no Delete, the cloud one with the
  line "Goes through your admin's LiteLLM proxy to Anthropic ...", and the local one with the line it always had;
* the roles in "Which AI does each feature use?" are fixed: both selects are disabled, the cloud one says it is set by
  ``AI_CLOUD_PROVIDER``, every route is locked by its ``AI_ROUTE_*`` variable, and the lab report row offers local or off only;
* Settings → AI ideas reads "Runs on your local AI (host)" for photos and lab reports and "Runs on LiteLLM proxy (host), a cloud AI
  outside your network" for meal ideas, describe a meal and Ask;
* the first AI meal ideas request opens a consent sheet that carries the proxy line, nothing reaches either fake before "Agree and
  send", then the cloud fake gets exactly one request, with the cloud key, and the local fake none;
* no sideways scroll and no console errors.

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

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "cloud-env"
PORT, AI_PORT, CLOUD_PORT = 8087, 8088, 8089
LOCAL_KEY, CLOUD_KEY = "sk-local-0123456789abcdefghijklmn", "sk-cloud-9876543210zyxwvutsrqponm"
PROXY_LINE = ("Goes through your admin's LiteLLM proxy to Anthropic. Anthropic receives what is sent, under its own terms; "
              "your admin can read it too.")
LOCAL_LINE = "Runs on your admin's hardware; your admin can read what is sent."
RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class FakeAi:
    """``/v1/models`` and ``/v1/chat/completions`` of a LiteLLM-style proxy: answers meal ideas from the candidates it is sent, and
    remembers every request with the key it carried."""

    def __init__(self, port: int, name: str) -> None:
        self.name, self.port = name, port
        self.requests: list[dict[str, Any]] = []  # {"key": the bearer value, "body": the JSON body} of every chat request
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
                self._send({"object": "list", "data": [{"id": "fake-model", "object": "model"}]})

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                key = str(self.headers.get("Authorization") or "").removeprefix("Bearer ")
                outer.requests.append({"key": key, "body": body})
                content = json.dumps(outer.reply(str(body["messages"][-1]["content"])))
                self._send({"id": "fake", "object": "chat.completion", "model": body.get("model"),
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 900, "completion_tokens": 60}})

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def task_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if str(r["body"]["messages"][-1]["content"]).startswith("TASK:")]

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
    for pid in ids.values():  # a fresh start for this walk: no consent to either host, nothing kept, both fakes quiet
        for purpose in ("text", "photos"):
            admin.call("DELETE", f"/api/ai/consent/{pid}", params={"purpose": purpose})
    admin.call("DELETE", "/api/ai/audit")
    local.requests.clear(), cloud.requests.clear()
    local_host, cloud_host = f"127.0.0.1:{local.port}", f"127.0.0.1:{cloud.port}"

    # 1. Server administration: the providers and the routing table.
    page.goto("/#admin")
    page.wait_for_selector("#ai-routing table", state="attached", timeout=15000)
    rows = page.locator(".setting-item", has=page.locator(".badge", has_text="Set by the server"))
    check(f"[{tag}] both providers are listed as set by the server", rows.count() == 2, str(rows.count()))
    check(f"[{tag}] neither has an Edit or a Delete", all(rows.nth(i).locator("summary:has-text('Edit'), button:has-text('Delete')").count() == 0
                                                          for i in range(rows.count())))
    texts = [rows.nth(i).inner_text() for i in range(rows.count())]
    check(f"[{tag}] the cloud provider shows the line that names the company", any(PROXY_LINE in t and cloud_host in t for t in texts), str(texts)[:400])
    check(f"[{tag}] the local provider does not", any(local_host in t and PROXY_LINE not in t for t in texts))
    check(f"[{tag}] both roles are fixed",
          page.evaluate("() => [...document.querySelectorAll('#ai-routing select')].length === 2 && [...document.querySelectorAll('#ai-routing select')].every((s) => s.disabled)"))
    text = page.inner_text("#ai-routing")
    check(f"[{tag}] the cloud role says it is set by AI_CLOUD_PROVIDER", "The server's own cloud provider (AI_CLOUD_PROVIDER)" in text, text[:300])
    check(f"[{tag}] the local role says it is set by AI_PROVIDER_ROLE", "The server's own provider (AI_PROVIDER_ROLE=local)" in text)
    check(f"[{tag}] every route is locked by its variable",
          page.evaluate("() => [...document.querySelectorAll('#ai-routing tbody input[type=radio]')].every((i) => i.disabled)")
          and all(f"Set by the server (AI_ROUTE_{n})" in text for n in ("PHOTOS", "MEAL_IDEAS", "DESCRIBE", "CHAT", "LABS")))
    labs = page.locator("#ai-routing tbody tr", has_text="Lab report photos").first
    check(f"[{tag}] lab report photos offer local or off only", labs.locator("input").count() == 2 and "never sent to a cloud AI" in labs.inner_text())
    check(f"[{tag}] Server administration has no sideways scroll", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"admin-{tag}.png"), full_page=True)

    # 2. Settings: where each feature runs.
    page.goto("/#settings")
    page.wait_for_selector("#set-ai-slot .ai-routing-lines", timeout=15000)
    lines = page.inner_text(".ai-routing-lines")
    cloud_line = f"Runs on LiteLLM proxy ({cloud_host}), a cloud AI outside your network."
    check(f"[{tag}] photos and lab reports run on the local AI",
          f"Photos (labels and plates): Runs on your local AI ({local_host})." in lines
          and f"Lab report photos: Runs on your local AI ({local_host})." in lines, lines[:500])
    check(f"[{tag}] meal ideas, describe a meal and Ask run on the cloud AI",
          all(f"{name}: {cloud_line}" in lines for name in ("Meal ideas", "Describe a meal", "Ask")), lines[:500])
    check(f"[{tag}] Settings has no sideways scroll", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"settings-{tag}.png"), full_page=True)

    # 3. The first request: the sheet carries the proxy line; nothing is sent before Agree.
    ask_for_ideas(page)
    page.wait_for_selector("#sheet-ai-consent[open]")
    sheet = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the consent sheet names the cloud host and the company", cloud_host in sheet and PROXY_LINE in sheet, sheet[:500])
    check(f"[{tag}] it does not say the request runs on the admin's hardware", LOCAL_LINE not in sheet)
    check(f"[{tag}] nothing was sent to either AI before Agree", not local.requests and not cloud.requests)
    check(f"[{tag}] no sideways scroll with the sheet", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"consent-{tag}.png"))
    page.click("#sheet-ai-consent >> text=Agree and send")
    page.wait_for_selector("#sheet-ai .ai-idea", timeout=30000)
    check(f"[{tag}] the cloud AI got one request, with the cloud key", len(cloud.task_requests) == 1 and cloud.task_requests[0]["key"] == CLOUD_KEY,
          str([r["key"][:8] for r in cloud.requests]))
    check(f"[{tag}] the local AI got none", not local.requests, str(len(local.requests)))
    check(f"[{tag}] no sideways scroll with the answer", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"answered-{tag}.png"))
    close_sheets(page)
    check(f"[{tag}] no console errors", not errors, "; ".join(errors)[:400])
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--ai-port", type=int, default=AI_PORT, help="the local AI (a fake LiteLLM-style server)")
    ap.add_argument("--cloud-port", type=int, default=CLOUD_PORT, help="the cloud AI (a second fake)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    for port in (args.port, args.ai_port, args.cloud_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port / --cloud-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    (out / "local.key").write_text(LOCAL_KEY + "\n")
    (out / "cloud.key").write_text(CLOUD_KEY + "\n")
    env = {"AI_ENABLED": "true", "AI_SHARED_DAILY_LIMIT": "0", "AI_CHAT_ENABLED": "true",
           "AI_PROVIDER": "litellm", "AI_PROVIDER_ROLE": "local", "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1",
           "AI_MODEL": "fake-local", "AI_VISION_MODEL": "fake-local", "AI_API_KEY_FILE": str(out / "local.key"),
           "AI_CLOUD_PROVIDER": "litellm", "AI_CLOUD_BASE_URL": f"http://127.0.0.1:{args.cloud_port}/v1",
           "AI_CLOUD_MODEL": "fake-cloud", "AI_CLOUD_VISION_MODEL": "fake-cloud", "AI_CLOUD_UPSTREAM": "Anthropic",
           "AI_CLOUD_API_KEY_FILE": str(out / "cloud.key"),
           "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port},127.0.0.1:{args.cloud_port}",
           "AI_ROUTE_PHOTOS": "local", "AI_ROUTE_LABS": "local", "AI_ROUTE_MEAL_IDEAS": "cloud", "AI_ROUTE_DESCRIBE": "cloud",
           "AI_ROUTE_CHAT": "cloud",
           # No call may leave this machine: a proxy that does not exist for anything but the local servers.
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    local, cloud = FakeAi(args.ai_port, "local"), FakeAi(args.cloud_port, "cloud")
    try:
        server.start()
        admin = first_admin(server, "cloudenv")
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                        "carbs_per_meal_g": 60}})
        admin.json("PATCH", "/api/me/ai", {"opt_in": True})
        providers = admin.json("GET", "/api/admin/ai-providers")["providers"]
        ids = {p["env"]: int(p["id"]) for p in providers}
        check("the server lists two providers, one for each variable", set(ids) == {"AI_PROVIDER", "AI_CLOUD_PROVIDER"}, str(ids))
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, admin, local, cloud, {"local": ids["AI_PROVIDER"], "cloud": ids["AI_CLOUD_PROVIDER"]}, base, out, width, height, scheme)
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
