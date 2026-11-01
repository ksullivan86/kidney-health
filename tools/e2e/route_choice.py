#!/usr/bin/env python3
"""A person picks the server's local or cloud AI per feature (design note 32), in Chromium against a real server and two fake providers.

    python tools/e2e/route_choice.py                     # ports 8085 (app), 8086 (local AI), 8087 (cloud AI)
    python tools/e2e/route_choice.py --port 8085 --ai-port 8086 --cloud-port 8087 --out /tmp/kh-route-choice

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED``, ``AI_PERSON_ROUTE_CHOICE_ENABLED``, a local AI (a fake
OpenAI-compatible server this script runs, holding the role ``local``) and a second shared provider (another fake) holding the role
``cloud``. Every feature stays on the admin's default, ``local``. Then, at 375x812 light and 1280x800 dark:

* Server administration → Users: the admin's own Manage panel has the tick box "May choose the server's local or cloud AI", off,
  with the hint that says what it does; ticking it saves;
* Settings → AI features: "Choose which AI each feature uses" lists photos, meal ideas, describe a meal, Ask and recipes (never lab
  report photos), each on "Server default", with both AIs offered by host;
* choosing "The server's cloud AI" for meal ideas: the line for meal ideas ends "You chose this.", the first AI meal ideas request
  opens the consent sheet for the cloud host, nothing reaches either AI before "Agree and send", and then only the cloud AI gets the
  request;
* back to "Server default": the request goes to the local AI again; unticking the person (through the API) removes the choice from
  Settings at once; no sideways scroll, no console errors.

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes ``<out>/report.json`` and
screenshots in ``<out>/shots/``; exit status 1 on any failure. The server and the fakes are always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import khserver
from fallback import FakeAi, ask_for_ideas, close_sheets, overflow
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "route-choice"
PORT, AI_PORT, CLOUD_PORT = 8085, 8086, 8087
RESULTS: list[dict[str, Any]] = []
TICK = "May choose the server's local or cloud AI"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def settings_choice(page: Any) -> None:
    page.goto("/#settings")
    page.wait_for_selector("#set-ai-route-choice", timeout=15000)


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
    # a fresh start for this walk: no tick, no choice, no consent to the cloud AI, nothing kept, both fakes quiet
    admin.json("PATCH", f"/api/admin/users/{ids['me']}", {"can_choose_ai": False})
    admin.call("DELETE", f"/api/ai/consent/{ids['cloud']}", params={"purpose": "text"})
    admin.call("DELETE", "/api/ai/audit")
    local.requests.clear(), cloud.requests.clear()
    cloud_host, local_host = f"127.0.0.1:{cloud.port}", f"127.0.0.1:{local.port}"

    # 1. Server administration → Users: the tick box, off, with its hint; ticking it saves.
    page.goto("/#admin")
    row = f"#user-{ids['me']}"
    page.wait_for_selector(f"{row} summary", timeout=15000)
    page.click(f"{row} summary")
    box = page.locator(f"{row} label.check", has_text=TICK)
    check(f"[{tag}] the Manage panel has the tick box, off", box.count() == 1 and not box.locator("input").is_checked())
    hint = page.inner_text(f"{row} .user-manage-body")
    check(f"[{tag}] its hint says what it does", "Settings → AI features" in hint and "lab report photos always stay local" in hint, hint[:500])
    check(f"[{tag}] Server administration has no sideways scroll", not overflow(page))
    page.locator(f"{row} .user-manage-body").screenshot(path=str(out / "shots" / f"admin-users-{tag}.png"))
    box.locator("input").check()
    page.wait_for_function("() => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('may choose the server'))", timeout=15000)
    users = admin.json("GET", "/api/admin/users")["users"]
    check(f"[{tag}] the tick was saved", next(u for u in users if u["id"] == ids["me"])["can_choose_ai"] is True)

    # 2. Settings → AI features: the choice, five features, never lab report photos, both AIs by host.
    settings_choice(page)
    part = page.inner_text("#set-ai-route-choice")
    labels = [t.strip() for t in page.locator("#set-ai-route-choice .field label").all_inner_texts()]
    check(f"[{tag}] Settings lists the five features and not lab report photos",
          labels == ["Photos (labels and plates)", "Meal ideas", "Describe a meal", "Ask", "Recipes"], str(labels))
    check(f"[{tag}] it says lab report photos always stay on the local AI", "Lab report photos always stay on the local AI." in part, part[:600])
    selects = page.locator("#set-ai-route-choice select")
    check(f"[{tag}] every feature starts on Server default", all(selects.nth(i).input_value() == "default" for i in range(selects.count())))
    options = page.locator("#set-ai-route-choice select").first.locator("option").all_inner_texts()
    check(f"[{tag}] both AIs are offered by host",
          options == ["Server default", f"The server's local AI ({local_host})", f"The server's cloud AI ({cloud_host})"], str(options))
    check(f"[{tag}] Settings has no sideways scroll", not overflow(page))
    page.locator("#set-ai-route-choice").screenshot(path=str(out / "shots" / f"settings-choice-{tag}.png"))

    # 3. Meal ideas on the cloud AI: the line, the consent sheet, nothing sent before Agree, then only the cloud AI.
    meal = page.locator("#set-ai-route-choice .field", has_text="Meal ideas").locator("select")
    meal.select_option("cloud")
    page.wait_for_selector("#set-ai-route-choice", timeout=15000)
    page.wait_for_function("() => [...document.querySelectorAll('.ai-routing-lines li')].some((li) => li.textContent.startsWith('Meal ideas:') && li.textContent.endsWith('You chose this.'))",
                           timeout=15000)
    lines = page.inner_text(".ai-routing-lines")
    check(f"[{tag}] the meal ideas line names the cloud AI and ends You chose this.",
          cloud_host in lines.split("Meal ideas:", 1)[1].split("\n", 1)[0], lines[:500])
    check(f"[{tag}] the choice was saved", admin.json("GET", "/api/me/ai")["route_choice"]["choices"]["meal_ideas"] == "cloud")
    ask_for_ideas(page)
    page.wait_for_selector("#sheet-ai-consent[open]")
    sheet = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the consent sheet names the cloud host", cloud_host in sheet and local_host not in sheet, sheet[:400])
    check(f"[{tag}] nothing was sent to either AI before Agree", not local.task_requests and not cloud.task_requests)
    page.screenshot(path=str(out / "shots" / f"consent-{tag}.png"))
    page.click("#sheet-ai-consent >> text=Agree and send")
    page.wait_for_selector("#sheet-ai .ai-idea", timeout=30000)
    check(f"[{tag}] only the cloud AI got the request", len(cloud.task_requests) == 1 and not local.task_requests,
          f"cloud {len(cloud.task_requests)}, local {len(local.task_requests)}")
    close_sheets(page)

    # 4. Back to Server default: the local AI again. Then the tick goes, and so does the choice.
    settings_choice(page)
    page.locator("#set-ai-route-choice .field", has_text="Meal ideas").locator("select").select_option("default")
    page.wait_for_function("() => ![...document.querySelectorAll('.ai-routing-lines li')].some((li) => li.textContent.endsWith('You chose this.'))",
                           timeout=15000)
    admin.call("DELETE", "/api/ai/audit")  # forgets the answer kept for ten minutes
    ask_for_ideas(page)
    page.wait_for_selector("#sheet-ai .ai-idea", timeout=30000)  # agreed to the local AI before the walk: no sheet
    check(f"[{tag}] Server default sends meal ideas to the local AI again", len(local.task_requests) == 1 and len(cloud.task_requests) == 1,
          f"cloud {len(cloud.task_requests)}, local {len(local.task_requests)}")
    close_sheets(page)
    admin.json("PATCH", f"/api/admin/users/{ids['me']}", {"can_choose_ai": False})
    page.goto("/#settings")
    page.reload()  # the next time Settings is loaded (the server stopped using the choice at once)
    page.wait_for_selector("#set-ai-slot .ai-routing-lines", timeout=15000)
    check(f"[{tag}] without the tick, Settings has no choice", page.locator("#set-ai-route-choice").count() == 0)

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
    env = {"AI_ENABLED": "true", "AI_PERSON_ROUTE_CHOICE_ENABLED": "true",
           "AI_PROVIDER": "openai_compatible", "AI_PROVIDER_ROLE": "local",  # the first fake is the local AI
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
        admin = first_admin(server, "chooser")
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                        "carbs_per_meal_g": 60}})
        admin.json("PATCH", "/api/me/ai", {"opt_in": True})
        made = admin.json("POST", "/api/admin/ai-providers", {"preset": "ollama", "model": "fake-text", "vision_model": "fake-vision",
                                                              "base_url": f"http://127.0.0.1:{args.cloud_port}/v1"})
        providers = admin.json("GET", "/api/admin/ai-providers")["providers"]
        ids = {"local": next(p["id"] for p in providers if p["locked"]), "cloud": int(made["id"]),
               "me": next(u["id"] for u in admin.json("GET", "/api/admin/users")["users"] if u["username"] == "chooser")}
        admin.json("PUT", "/api/admin/ai-routing", {"cloud_provider": ids["cloud"]})
        admin.json("POST", "/api/ai/consent", {"provider_id": ids["local"], "purpose": "text", "skip_preview": True})
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
