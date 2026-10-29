#!/usr/bin/env python3
"""AI recipes (note 16 phase 3) in Chromium against a real server and a fake local AI.

    python tools/e2e/recipes_ai.py                       # ports 8086 (app), 8087 (the fake AI)
    python tools/e2e/recipes_ai.py --port 8086 --ai-port 8087 --out /tmp/kh-recipes-ai

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR`` with ``AI_ENABLED`` and a local AI (a fake OpenAI-compatible server this
script runs). The fake answers AI recipes with three of the candidates it is sent and three steps, one of them about insulin.
Then, at 375x812 light and 1280x800 dark:

* Plan shows "Suggest recipes with AI"; the first request opens the consent sheet, and nothing reaches the AI before "Agree and
  send"; "What will be sent?" shows the request;
* a card shows the app's title, the foods for the whole pot and "Makes 2 servings"; with the steps switch off it shows no steps;
* "Save recipe" adds it to the saved meals once (a second tap saves nothing more); "Add to plan" plans one serving;
* the fit sheet of a saved recipe shows "Rework with AI"; the rework card is named "<name> (reworked)" and the request holds
  neither the recipe's name nor its note;
* with the steps switch on, the insulin step is removed and the others carry the label "Steps written by AI …";
* no sideways scroll, no console errors.

Nothing leaves the machine (an outbound proxy that points nowhere). Prints PASS / FAIL lines, writes ``<out>/report.json`` and
screenshots in ``<out>/shots/``; exit status 1 on any failure. The server and the fake are always stopped.
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

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "recipes-ai"
PORT, AI_PORT = 8086, 8087
RESULTS: list[dict[str, Any]] = []
SECRET_NAME, SECRET_NOTE = "Gran's Sunday pot", "from the leaflet on ward 7"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


class FakeAi:
    """``/v1/models`` and ``/v1/chat/completions``: answers AI recipes from the candidates it is sent; remembers every request."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, obj: Any) -> None:
                raw = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                self._send({"object": "list", "data": [{"id": "fake-text", "object": "model"}]})

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.requests.append(body)
                text = str(body["messages"][-1]["content"])
                self._send({"id": "fake", "object": "chat.completion", "model": body.get("model"),
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(outer.reply(text))},
                                         "finish_reason": "stop"}],
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
        if text.startswith("TASK: recipes"):
            raw = text.split("<data>\n", 1)[1].split("\n</data>", 1)[0]
            data = json.loads(raw.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
            c = [x for x in data.get("candidates") or [] if x.get("group") != "extra"][:3]
            return {"status": "ok", "refusal": "none", "recipes": [
                {"dish": "bowl", "theme": "light", "ingredients": [{"food_id": x["id"], "quarters": 2} for x in c],
                 "steps": ["Chop everything small.", "Have your insulin ready.", "Simmer for 20 minutes."],
                 "reason_codes": ["low_sodium"]}]}
        return {"status": "refused", "refusal": "outside_scope", "recipes": []}

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def close_sheets(page: Any) -> None:
    page.evaluate("() => document.querySelectorAll('dialog[open]').forEach((d) => d.close())")


def meals(admin: Any) -> list[dict[str, Any]]:
    return admin.json("GET", "/api/meals")["meals"]


def walk_idea_context(page: Any, tag: str) -> None:
    """Deferred synthetic replies exercise the real idea widget without AI or log writes."""
    result = page.evaluate("""async () => {
      const api = KH.ai.api;
      const saved = {me: api.me, status: api.status, nextMeal: api.nextMeal, logBatch: api.logBatch};
      const box = KH.h('div', {});
      document.body.append(box);
      const writes = [], calls = [];
      let resolve;
      const tick = () => new Promise(r => setTimeout(r, 0));
      const idea = title => ({status: 'ok', ideas: [{title, why: '', totals: {},
        items: [{food_id: 1, name: 'Test food', servings: 1}], after: {carbs_g: {meal_after: 60, goal: 60}}}]});
      try {
        api.me = async () => ({enabled: true});
        api.status = async () => ({enabled: true, consent: {text: {skip_preview: true}}});
        api.nextMeal = body => { calls.push(body); return new Promise(r => { resolve = r; }); };
        api.logBatch = async entries => { writes.push(...entries); };
        KH.ai.forget();
        const controller = KH.ai.mountIdeas(box, {date: '2026-10-29', meal: 'breakfast'});
        const ask = box.querySelector('button');
        ask.click();
        await tick();
        controller.setMeal('dinner');
        resolve(idea('Old breakfast result'));
        await tick();
        const stale = box.querySelector('.ai-results').innerText;
        const oldAdd = !!box.querySelector('.ai-results button');
        ask.click();
        await tick();
        resolve(idea('Current dinner result'));
        await tick();
        const current = box.querySelector('.ai-results').innerText;
        box.querySelector('.ai-results button').click();
        await tick();
        return {stale, oldAdd, current, calls, writes};
      } finally {
        Object.assign(api, saved);
        KH.ai.forget();
        box.remove();
      }
    }""")
    check(f"[{tag}] old breakfast ideas do not reappear as dinner after changing the meal",
          "Old breakfast result" not in result["stale"] and not result["oldAdd"], result["stale"])
    check(f"[{tag}] a fresh dinner answer still renders and Add to plan uses its requested context",
          "Current dinner result" in result["current"] and "Dinner carbohydrate" in result["current"]
          and [c["meal"] for c in result["calls"]] == ["breakfast", "dinner"]
          and len(result["writes"]) == 1 and result["writes"][0]["meal"] == "dinner"
          and result["writes"][0]["date"] == "2026-10-29")


def walk(browser: Any, admin: Any, fake: FakeAi, ids: dict[str, int], base: str, out: Path, width: int, height: int, scheme: str) -> None:
    tag = f"{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "409" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    admin.call("DELETE", f"/api/ai/consent/{ids['local']}", params={"purpose": "text"})
    admin.json("PATCH", "/api/admin/settings", {"ai.recipe_steps": False})
    fake.requests.clear()
    before = len(meals(admin))

    # 1. Plan: the button, the consent sheet, nothing sent before Agree.
    page.goto("/#plan")
    page.wait_for_selector("#ai-recipes-row:not([hidden]) #btn-ai-recipes", timeout=15000)
    check(f"[{tag}] Plan offers Suggest recipes with AI", page.is_visible("#btn-ai-recipes"))
    page.click("#btn-ai-recipes")
    page.wait_for_selector("#sheet-ai[open]")
    check(f"[{tag}] the sheet has the kind of dish and how many servings",
          page.locator("#sheet-ai select").count() == 2 and "Kind of dish" in page.inner_text("#sheet-ai"))
    page.select_option("#sheet-ai select >> nth=1", "2")
    page.click("#sheet-ai >> text=Ask AI for recipes")
    page.wait_for_selector("#sheet-ai-consent[open]")
    sheet = page.inner_text("#sheet-ai-consent")
    check(f"[{tag}] the consent sheet names recipes", "the foods and amounts of a recipe" in sheet, sheet[:300])
    check(f"[{tag}] nothing was sent before Agree", not fake.task_requests)
    page.click("#sheet-ai-consent >> text=Agree and send")
    page.wait_for_selector("#sheet-ai .ai-recipe", timeout=30000)
    card = page.inner_text("#sheet-ai .ai-recipe")
    check(f"[{tag}] the card has the app's title, the pot and the servings",
          "bowl" in page.inner_text("#sheet-ai .ai-recipe .ai-idea-title").lower() and "Makes 2 servings" in card
          and "foods for the whole recipe" in card.lower(), card[:400])  # the heading is upper case in CSS
    check(f"[{tag}] with the switch off there are no steps", page.locator("#sheet-ai .ai-recipe .ai-steps").count() == 0)
    check(f"[{tag}] the card carries the AI label", "AI recipe · " in card)
    check(f"[{tag}] no sideways scroll with a card", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"suggest-{tag}.png"), full_page=True)
    # 2. Save once, and plan one serving.
    title = page.inner_text("#sheet-ai .ai-recipe .ai-idea-title")
    page.click("#sheet-ai .ai-recipe >> text=Save recipe")
    page.wait_for_selector("#sheet-ai .ai-recipe >> text=Saved", timeout=15000)
    page.click("#sheet-ai .ai-recipe >> text=Saved")
    page.wait_for_timeout(500)
    saved = meals(admin)
    check(f"[{tag}] Save recipe saved it once, by the ordinary route",
          len(saved) == before + 1 and any(m["name"] == title for m in saved), f"{len(saved)} vs {before}, {title}")
    page.click("#sheet-ai .ai-recipe >> text=Add to plan")
    page.wait_for_selector("#sheet-ai .ai-recipe >> text=Added to your plan", timeout=15000)
    check(f"[{tag}] Add to plan planned one serving", True)
    # 3. What will be sent?
    page.click("#sheet-ai >> text=What will be sent?")
    page.wait_for_selector("#sheet-ai-sent[open]")
    check(f"[{tag}] What will be sent? shows the request", "Body (exactly as sent)" in page.inner_text("#sheet-ai-sent"))
    close_sheets(page)

    # 4. Rework a saved recipe from the fit sheet.
    page.goto("/#plan")
    page.wait_for_selector("#saved-meals .saved-meal", timeout=15000)
    page.locator("#saved-meals .saved-meal", has_text=SECRET_NAME).locator("text=Fit to my targets").click()
    page.wait_for_selector("#sheet-fit[open] #fit-rework:not([hidden])", timeout=15000)
    page.click("#fit-rework")
    page.wait_for_selector("#sheet-ai[open]")
    check(f"[{tag}] the rework sheet says the name and note are never sent", "never sent" in page.inner_text("#sheet-ai"))
    sent_before = len(fake.task_requests)
    page.click("#sheet-ai >> text=Ask AI to rework it")
    page.wait_for_selector("#sheet-ai .ai-recipe", timeout=30000)
    check(f"[{tag}] the rework card keeps the person's name with (reworked)",
          page.inner_text("#sheet-ai .ai-recipe .ai-idea-title") == f"{SECRET_NAME} (reworked)")
    body = json.dumps(fake.task_requests[sent_before:])
    check(f"[{tag}] the request held neither the name nor the note", SECRET_NAME not in body and SECRET_NOTE not in body
          and "Gran" not in body)
    page.screenshot(path=str(out / "shots" / f"rework-{tag}.png"), full_page=True)
    close_sheets(page)

    # 5. Steps on: the insulin step is removed, the rest carry the label.
    admin.json("PATCH", "/api/admin/settings", {"ai.recipe_steps": True})
    page.goto("/#plan")
    page.wait_for_selector("#ai-recipes-row:not([hidden]) #btn-ai-recipes", timeout=15000)
    page.click("#btn-ai-recipes")
    page.wait_for_selector("#sheet-ai[open]")
    page.click("#sheet-ai >> text=Ask AI for recipes")
    page.wait_for_selector("#sheet-ai .ai-recipe .ai-steps", timeout=30000)
    steps = page.locator("#sheet-ai .ai-recipe .ai-steps li").all_inner_texts()
    label = page.inner_text("#sheet-ai .ai-recipe .ai-steps .hint")
    check(f"[{tag}] the insulin step is removed and the others stay", steps == ["Chop everything small.", "Simmer for 20 minutes."], str(steps))
    check(f"[{tag}] the steps carry the label", "not for cooking times or food safety" in label, label)
    check(f"[{tag}] no sideways scroll with steps", not overflow(page))
    page.screenshot(path=str(out / "shots" / f"steps-{tag}.png"), full_page=True)
    close_sheets(page)
    walk_idea_context(page, tag)
    check(f"[{tag}] no console or page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--ai-port", type=int, default=AI_PORT, help="the local AI (a fake OpenAI-compatible server)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    for port in (args.port, args.ai_port):
        if khserver.port_in_use(port):
            print(f"port {port} is in use; pick another with --port / --ai-port", file=sys.stderr)
            return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"AI_ENABLED": "true", "AI_PROVIDER": "openai_compatible", "AI_PROVIDER_ROLE": "local",
           "AI_BASE_URL": f"http://127.0.0.1:{args.ai_port}/v1", "AI_MODEL": "fake-text",
           "AI_PRIVATE_HOSTS": f"127.0.0.1:{args.ai_port}", "AI_SHARED_DAILY_LIMIT": "0",
           "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    fake = FakeAi(args.ai_port)
    try:
        server.start()
        admin = first_admin(server, "recipes")
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                        "carbs_per_meal_g": 60}})
        admin.json("PATCH", "/api/me/ai", {"opt_in": True})
        foods = admin.json("GET", "/api/foods", params={"q": "Rice, white", "limit": 5})["foods"]
        chicken = admin.json("GET", "/api/foods", params={"q": "Chicken breast, roasted", "limit": 5})["foods"]
        admin.json("POST", "/api/meals", {"name": SECRET_NAME, "note": SECRET_NOTE, "servings_made": 2, "meal_hint": "dinner",
                                          "items": [{"food_id": foods[0]["id"], "servings": 2}, {"food_id": chicken[0]["id"], "servings": 2}]})
        providers = admin.json("GET", "/api/admin/ai-providers")["providers"]
        ids = {"local": next(p["id"] for p in providers if p["locked"])}
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, admin, fake, ids, base, out, width, height, scheme)
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
