#!/usr/bin/env python3
"""The handbook's "Add this day to my plan" link (v0.4) in Chromium, against a real server and the demo.

    python tools/e2e/menuplan.py                       # port 8076
    python tools/e2e/menuplan.py --port 8076 --out /tmp/kh-menuplan
    python tools/e2e/menuplan.py --site handbook/site  # also follow the link from a built handbook (HANDBOOK_APP_LINK=/)

Starts ``uvicorn app.main:app`` on a fresh ``DATA_DIR``, finishes first-run setup, invites a second person who owns a
custom food, takes the first menu day of ``handbook/docs/eat/menus/g3.md`` (the link the handbook really contains) and
adds entries for things that must be refused. Then, at 375x812 light and 1280x800 dark:

* opening ``/#plan-menu?items=...`` shows the confirmation sheet and writes nothing (no POST, no entry on the server);
  the foods are the app's own, the date is tomorrow, a custom food of another person, an unknown meal letter and a
  repeated food are listed under "Not added" and that person's food name appears nowhere;
* unticking one food and pressing "Add to plan" twice quickly sends one ``POST /api/log/batch``; the server then holds
  exactly the ticked foods as planned entries; the same body sent again answers 200 and adds nothing;
* signed out, the sign-in screen shows (the list is gone from the address bar and from storage), and after signing in
  the sheet opens with the next date that has no plan; Cancel writes nothing;
* a link with another parameter, with markup or with 41 foods is refused in the sheet (no Add button) with no dialog,
  no injected element and no page error;
* with ``--site``: the real handbook page ``/learn/eat/menus/g3/`` served by the app, its first "Add this day to my plan"
  link points at ``/#plan-menu?items=...`` and clicking it opens the sheet with that day's foods;
* the Pages demo (``scripts/build_preview.py --pages``, served statically) shows the sheet and adds the planned entries to its own data;
* no sideways scroll, no console error.

Nothing leaves the machine. Prints PASS / FAIL lines, writes ``<out>/report.json`` and screenshots in
``<out>/shots/``; exit status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import khserver
from khserver import DEFAULT_PASSWORD, Server, first_admin, invite_user
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "menuplan"
PORT = 8076
RESULTS: list[dict[str, Any]] = []
USER = "menu"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def overflow(page: Any) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1"))


def handbook_link() -> str:
    """The first menu day's link as the handbook page contains it (the placeholder is the app's address)."""
    text = (REPO / "handbook" / "docs" / "eat" / "menus" / "g3.md").read_text(encoding="utf-8")
    match = re.search(r'<a class="kh-plan-link" href="@KH_APP@(#plan-menu\?items=[^"]+)"', text)
    assert match, "no menu link in g3.md; run python scripts/build_handbook.py"
    return match.group(1)


def tokens_of(link: str) -> list[str]:
    return link.split("items=", 1)[1].split(",")


def parse_token(token: str) -> tuple[str, int, float]:
    meal = {"b": "breakfast", "l": "lunch", "d": "dinner", "s": "snack"}[token[0]]
    fdc, servings = token[1:].split("x")
    return meal, int(fdc), float(servings)


class Watch:
    """Requests, dialogs, console errors and page errors of one page."""

    def __init__(self, page: Any) -> None:
        self.requests: list[tuple[str, str]] = []
        self.bodies: list[Any] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        page.on("request", self._request)
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("dialog", self._dialog)

    def _dialog(self, dialog: Any) -> None:
        self.dialogs.append(dialog.message)
        dialog.dismiss()

    def _request(self, r: Any) -> None:
        parts = urlsplit(r.url)
        self.requests.append((r.method, parts.path))
        if r.method == "POST" and parts.path == "/api/log/batch":
            self.bodies.append(r.post_data_json)

    def posts(self, path: str = "") -> list[tuple[str, str]]:
        return [q for q in self.requests if q[0] == "POST" and (not path or q[1] == path)]


def planned_on(admin: Any, date: str) -> list[dict[str, Any]]:
    return [e for e in admin.json("GET", "/api/log", params={"date": date})["entries"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--site", type=Path, default=None, help="a built handbook (mkdocs build with HANDBOOK_APP_LINK=/): checks the link from /learn/")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    if args.site:
        env["HANDBOOK_DIR"] = str(args.site.resolve())
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    try:
        server.start()
        admin = first_admin(server, USER)
        admin.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                       "protein_g": {"min": 50, "max": 70}, "carbs_g": 220}})
        sam = invite_user(server, admin, "sam")
        stew = sam.json("POST", "/api/foods", {"name": "Sam's secret stew", "serving_desc": "1 bowl", "serving_g": 300,
                                               "nutrients": {"potassium_mg": 900, "sodium_mg": 1200}})
        builtin = {f["fdc_id"]: f for f in admin.json("GET", "/api/foods/builtin")["foods"]}
        day = handbook_link()
        day_tokens = tokens_of(day)
        extras = [f"s{stew['id']}x1", "z173905x1", day_tokens[0]]  # another person's food id, an unknown meal, a repeat
        link = day + "," + ",".join(extras)
        check("the handbook's own link names built-in foods only", all(parse_token(t)[1] in builtin for t in day_tokens),
              str([t for t in day_tokens if parse_token(t)[1] not in builtin]))
        base = f"http://localhost:{args.port}"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    signed_in(browser, admin, base, out, width, height, scheme, link, day_tokens, builtin, stew)
                    if width == 375:
                        signed_out(browser, admin, base, out, link, day_tokens)
                        refused(browser, admin, base, out)
                if args.site:
                    from_handbook(browser, admin, base, out, day, day_tokens)
                demo(browser, out, day_tokens)
            finally:
                browser.close()
        admin.close()
        sam.close()
    except Exception as exc:  # noqa: BLE001 - report and fail
        check("harness", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        server.stop()
    (out / "report.json").write_text(json.dumps(RESULTS, indent=1) + "\n", encoding="utf-8")
    failed = [r["check"] for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report: {out / 'report.json'}")
    return 1 if failed else 0


def signed_in(browser: Any, admin: Any, base: str, out: Path, width: int, height: int, scheme: str, link: str,
              day_tokens: list[str], builtin: dict[int, Any], stew: dict[str, Any]) -> None:
    tag = f"{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/" + link)
    page.wait_for_selector("#sheet-menuplan[open]", timeout=20000)
    page.wait_for_selector("#menuplan-lines li", timeout=20000)
    tomorrow = page.evaluate("KH.util.addDays(KH.util.todayStr(), 1)")
    # Earlier passes may have planned days: the sheet offers tomorrow or the next day with no plan.
    date = page.input_value("#menuplan-date")
    check(f"[{tag}] the sheet opens from the link, with one box per food", page.locator("#menuplan-groups input[type=checkbox]").count() == len(day_tokens),
          f"{page.locator('#menuplan-groups input[type=checkbox]').count()} of {len(day_tokens)}")
    check(f"[{tag}] the date is tomorrow, or the next day with nothing planned", date >= tomorrow, f"{date} vs {tomorrow}")
    skipped = page.inner_text("#menuplan-skipped-list")
    check(f"[{tag}] other person's food, unknown meal and repeat are listed under Not added with reasons",
          f"food {stew['id']}" in skipped and "z173905x1" in skipped and "listed twice" in skipped and "not one of the app's built-in foods" in skipped, skipped)
    check(f"[{tag}] the other person's food name appears nowhere", "secret stew" not in page.inner_text("body").lower())
    check(f"[{tag}] nothing was written to open the sheet (no POST, no entry)", not watch.posts() and not planned_on(admin, date),
          str(watch.posts()))
    names = page.locator("#menuplan-groups .mp-name").all_inner_texts()
    first = builtin[parse_token(day_tokens[0])[1]]
    check(f"[{tag}] the foods shown are the app's own names", first["name"] in names[0], names[0])
    check(f"[{tag}] projected totals are shown", page.locator("#menuplan-lines li").count() >= 1 and page.locator("#menuplan-key .kn").count() == 5,
          page.inner_text("#menuplan-lines"))
    check(f"[{tag}] no sideways scroll, no console error so far", not overflow(page) and not watch.errors, "; ".join(watch.errors))
    page.screenshot(path=str(out / "shots" / f"sheet-{tag}.png"))
    page.evaluate("() => { document.querySelector('#sheet-menuplan .sheet-body').scrollTop = 1e6; }")
    page.screenshot(path=str(out / "shots" / f"sheet-bottom-{tag}.png"))
    page.locator("#menuplan-groups input[type=checkbox]").first.uncheck()
    expected = [parse_token(t) for t in day_tokens[1:]]
    check(f"[{tag}] unticking a food updates the count", page.inner_text("#menuplan-count").startswith(f"{len(expected)} of"), page.inner_text("#menuplan-count"))
    page.dblclick("#menuplan-save")
    page.wait_for_selector("#sheet-menuplan", state="hidden", timeout=20000)
    page.wait_for_selector("#view-plan:not([hidden])", timeout=20000)
    check(f"[{tag}] two quick presses send one POST /api/log/batch", len(watch.posts("/api/log/batch")) == 1, str(watch.posts()))
    got = sorted((e["meal"], builtin_fdc(builtin, e["food_id"], admin), round(float(e["servings"]), 3), e["status"]) for e in planned_on(admin, date))
    want = sorted((m, f, round(s, 3), "planned") for m, f, s in expected)
    check(f"[{tag}] the server holds exactly the ticked foods, as planned", got == want,
          f"{len(got)} vs {len(want)}; only on the server {[g for g in got if g not in want][:3]}; only expected {[w for w in want if w not in got][:3]}")
    body = watch.bodies[0]
    check(f"[{tag}] the posted batch is the confirmed list, one client_id each",
          len(body["entries"]) == len(expected) and len({e["client_id"] for e in body["entries"]}) == len(expected)
          and all(e["status"] == "planned" and e["date"] == date for e in body["entries"]), str(body)[:300])
    again = admin.call("POST", "/api/log/batch", body)
    check(f"[{tag}] the same body again adds nothing (200, every item existing)",
          again.status_code == 200 and all(r["result"] == "existing" for r in again.json()["results"]) and len(planned_on(admin, date)) == len(expected),
          f"{again.status_code} {again.text[:200]}")
    check(f"[{tag}] no console error, no dialog, no sideways scroll", not watch.errors and not watch.dialogs and not overflow(page), "; ".join(watch.errors))
    page.screenshot(path=str(out / "shots" / f"plan-{tag}.png"))
    ctx.close()
    # leave the days free for the next pass: delete what this pass planned
    for e in planned_on(admin, date):
        admin.call("DELETE", f"/api/log/{e['id']}")


def builtin_fdc(builtin: dict[int, Any], food_id: int, admin: Any) -> int | None:
    for fdc, f in builtin.items():
        if f["id"] == food_id:
            return fdc
    return None


def signed_out(browser: Any, admin: Any, base: str, out: Path, link: str, day_tokens: list[str]) -> None:
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, base_url=base)
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/" + link)
    page.wait_for_selector("#login-username", state="visible", timeout=20000)
    check("[signed out] the sign-in screen shows and the sheet does not", not page.is_visible("#sheet-menuplan"))
    stored = page.evaluate("() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])")
    check("[signed out] the list is gone from the address bar and is in no storage",
          "plan-menu" not in page.evaluate("location.href") and "plan-menu" not in stored and str(parse_token(day_tokens[0])[1]) not in stored,
          page.evaluate("location.href"))
    before = len(watch.requests)
    page.fill("#login-username", USER)
    page.fill("#login-password", DEFAULT_PASSWORD)
    page.click("#login-submit")
    page.wait_for_selector("#sheet-menuplan[open]", timeout=20000)
    page.wait_for_selector("#menuplan-lines li", timeout=20000)
    check("[signed out] after signing in the sheet opens with the foods", page.locator("#menuplan-groups input[type=checkbox]").count() == len(day_tokens))
    date = page.input_value("#menuplan-date")
    page.screenshot(path=str(out / "shots" / "signed-out-375.png"))
    page.click("#menuplan-close")
    page.wait_for_selector("#sheet-menuplan", state="hidden")
    check("[signed out] Cancel writes nothing", not watch.posts("/api/log/batch") and not planned_on(admin, date), str(watch.requests[before:]))
    check("[signed out] no console error", not [e for e in watch.errors if "401" not in e], "; ".join(watch.errors))
    ctx.close()


def refused(browser: Any, admin: Any, base: str, out: Path) -> None:
    many = "#plan-menu?items=" + ",".join(f"b{n}x1" for n in range(1, 42))
    for name, link in (("another parameter", "#plan-menu?items=b173905x1&date=2026-10-20"),
                       ("markup", "#plan-menu?items=<img src=x onerror=alert(1)>"),
                       ("41 foods", many)):
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, base_url=base)
        ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
        page = ctx.new_page()
        watch = Watch(page)
        page.goto("/" + link)
        page.wait_for_selector("#sheet-menuplan[open]", timeout=20000)
        check(f"[refused: {name}] the sheet says why and offers no Add",
              page.is_visible("#menuplan-error") and page.is_disabled("#menuplan-save") and page.locator("#menuplan-groups input").count() == 0,
              page.inner_text("#menuplan-error"))
        check(f"[refused: {name}] no dialog, no injected element, no page error, nothing posted",
              not watch.dialogs and page.locator("img[src='x']").count() == 0 and not watch.errors and not watch.posts(), "; ".join(watch.errors))
        ctx.close()


def from_handbook(browser: Any, admin: Any, base: str, out: Path, day: str, day_tokens: list[str]) -> None:
    """The link as a reader meets it: on the handbook page the app serves, then one click."""
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, base_url=base)
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in admin.cookies().items()])
    page = ctx.new_page()
    watch = Watch(page)
    page.goto("/learn/eat/menus/g3/")
    links = page.locator("a.kh-plan-link")
    check("[handbook] the page has one link per day, 7 in all", links.count() == 7, str(links.count()))
    href = links.first.get_attribute("href") or ""
    check("[handbook] the first link points at the app (same origin) with the day's foods", href in ("/" + day, base + "/" + day), href[:120])
    check("[handbook] the page has no script of its own for it and no placeholder left",
          "@KH_APP@" not in page.content() and page.locator("p.kh-plan-day script").count() == 0)
    links.first.scroll_into_view_if_needed()
    page.screenshot(path=str(out / "shots" / "handbook-375.png"))
    links.first.click()
    page.wait_for_selector("#sheet-menuplan[open]", timeout=20000)
    page.wait_for_selector("#menuplan-lines li", timeout=20000)
    check("[handbook] one click opens the app's sheet with that day", page.locator("#menuplan-groups input[type=checkbox]").count() == len(day_tokens))
    check("[handbook] following it wrote nothing and raised no error", not watch.posts() and not watch.errors, "; ".join(watch.errors))
    ctx.close()


def demo(browser: Any, out: Path, day_tokens: list[str]) -> None:
    """The Pages demo (scripts/build_preview.py --pages: the whole food list, the app's mock API) served by a static server."""
    site = out / "demo-site"
    subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--pages", str(site)], check=True, capture_output=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(site))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://localhost:{httpd.server_address[1]}"
    try:
        link = "#plan-menu?items=" + ",".join(day_tokens[:6])
        ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", base_url=base)
        page = ctx.new_page()
        watch = Watch(page)
        page.goto("/" + link)
        page.wait_for_selector("#sheet-menuplan[open]", timeout=20000)
        page.wait_for_selector("#menuplan-lines li", timeout=20000)
        count = page.locator("#menuplan-groups input[type=checkbox]").count()
        check("[demo] the sheet opens in the demo with the foods", count == 6, str(count))
        date = page.input_value("#menuplan-date")
        page.screenshot(path=str(out / "shots" / "demo-375.png"))
        page.click("#menuplan-save")
        page.wait_for_selector("#sheet-menuplan", state="hidden", timeout=20000)
        planned = page.evaluate("async (d) => (await KH.api.day(d)).entries.filter((e) => e.status === 'planned').length", date)
        check("[demo] Add to plan puts the planned entries in the demo's own data", planned == 6, str(planned))
        others = [q for q in watch.requests if urlsplit(f"{q[1]}").path.startswith("/api/")]
        check("[demo] no request to any /api route, no error", not others and not watch.errors, f"{others} {watch.errors}")
        ctx.close()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
