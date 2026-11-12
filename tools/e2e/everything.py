"""Every new feature on at once, on one real server, in Chromium (0.22 integration run).

    python3 tools/e2e/everything.py                   # port 8116
    python3 tools/e2e/everything.py --only 375-light  # one configuration

Each feature's own harness turns on only that feature. This one starts the real app (``instacart_app:app``: Instacart answered
by a fake inside the process) with the Care team, connected devices (Withings, with a placeholder client), list sync, recipe
import, Instacart, test accounts, the per-person AI choice, reminders and Care team notes all switched on, the way a family
server might run. Two people:
``mum`` (the admin, with a planned week) and ``dad`` (her Caregiver, every switch on). For each of 375x812 and 1280x800, light and
dark, both people open every screen they can reach, and mum opens the shopping list and the Instacart sheet. Each page must load
with no console error, no failed request (4xx or 5xx), no CSP violation, no browser dialog, no sideways scroll and no other host.

Nothing leaves the machine and nothing is sent: the walk only opens sheets. Prints PASS / FAIL lines, writes ``<out>/report.json``
and screenshots in ``<out>/shots/``; exit status 1 on any failure. The server is always stopped.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import khserver
from instacart_app import KEY
from khserver import Api, Server, first_admin, invite_user
from playwright.sync_api import sync_playwright
from sharing import RESULTS, Pass, check

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "everything"
PORT = 8116
CONFIGS = [(375, 812, "light"), (375, 812, "dark"), (1280, 800, "light"), (1280, 800, "dark")]
SCREENS = ["today", "add", "plan", "trends", "profile", "labs", "visit", "settings"]


class Watched(Pass):
    """A Pass that also counts any answer of 400 or more (a quiet failure the page may not show)."""

    def __init__(self, *args: Any, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.failed: list[str] = []
        self.page.on("response", lambda r: self.failed.append(f"{r.status} {r.request.method} {r.url.split('?')[0]}")
                     if r.status >= 400 and "/api/" in r.url else None)


def open_screen(p: Watched, name: str) -> None:
    page = p.page
    page.goto(f"/#{name}")
    page.wait_for_selector(f"#view-{name}:not([hidden])", timeout=30000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)
    p.no_overflow(name)


def walk(p: Watched, screens: list[str], shopping: bool) -> None:
    for name in screens:
        try:
            open_screen(p, name)
        except Exception as exc:  # one screen that does not open must not hide the others
            check(f"[{p.tag}] {name} opens", False, str(exc).splitlines()[0])
            continue
        if name in ("plan", "settings", "admin"):
            p.shot(name)
        if name == "plan" and shopping:
            page = p.page
            page.wait_for_selector("#shopping-instacart:not([hidden])", timeout=30000)
            page.click("#shopping-instacart")
            page.wait_for_selector("#instacart-items li", timeout=20000)
            check(f"[{p.tag}] the Instacart sheet lists the planned foods", page.locator("#instacart-items li").count() >= 2)
            p.no_overflow("instacart sheet")
            p.shot("instacart", "#sheet-instacart")
            page.click("#instacart-cancel")
    check(f"[{p.tag}] no request failed", not p.failed, "; ".join(p.failed[:8]))
    p.finish(refused=list(p.watch.refused))


def seed(server: Server) -> tuple[Api, Api]:
    mum = first_admin(server, "mum")
    dad = invite_user(server, mum, "dad")
    monday = date.today() - timedelta(days=date.today().weekday())
    for i, (query, servings) in enumerate((("banana", 2), ("rice white", 1), ("apple", 1))):
        food = mum.json("GET", "/api/foods", params={"q": query, "limit": 1})["foods"][0]
        mum.json("POST", "/api/log", {"date": (monday + timedelta(days=i)).isoformat(), "meal": "lunch", "food_id": food["id"],
                                      "servings": servings, "status": "planned"})
    food = mum.json("GET", "/api/foods", params={"q": "banana", "limit": 1})["foods"][0]
    mum.json("POST", "/api/log", {"date": date.today().isoformat(), "meal": "breakfast", "food_id": food["id"], "servings": 1})
    mum.json("POST", "/api/me/shares/invite", {"username": "dad", "areas": ["food", "labs", "body", "symptoms", "activity"],
                                               "days": None, "role": "caregiver"})
    invite = dad.json("GET", "/api/shared")["invites"][0]
    dad.json("POST", f"/api/shared/invites/{invite['id']}/accept")
    return mum, dad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="", help="for example 375-light")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    (out / "shots").mkdir()
    secrets = out / "secrets"
    secrets.mkdir()
    for name, value in (("instacart", KEY), ("withings", "placeholder-withings-secret-0123456789")):
        (secrets / name).write_text(value + "\n", encoding="utf-8")
        (secrets / name).chmod(0o600)
    proxy = "http://127.0.0.1:9"  # nothing may leave the machine
    env = {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "ALL_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy, "all_proxy": proxy,
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "HANDBOOK_DIR": str(out / "no-handbook"),
           "SHARING_ENABLED": "true", "LIST_SYNC_ENABLED": "true", "RECIPE_IMPORT_ENABLED": "true",
           "INSTACART_ENABLED": "true", "INSTACART_API_KEY_FILE": str(secrets / "instacart"),
           "INSTACART_BASE_URL": "https://connect.dev.instacart.tools",
           "DEVICES_ENABLED": "true", "WITHINGS_ENABLED": "true", "WITHINGS_CLIENT_ID": "kh-e2e-client",
           "WITHINGS_CLIENT_SECRET_FILE": str(secrets / "withings"),
           "TEST_ACCOUNT_ENABLED": "true", "AI_PERSON_ROUTE_CHOICE_ENABLED": "true", "PUBLIC_URL": f"http://127.0.0.1:{args.port}",
           "REMINDERS_ENABLED": "true", "VAPID_SUBJECT": "mailto:admin@example.org", "CARE_NOTES_ENABLED": "true"}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env, app_spec="instacart_app:app")
    try:
        server.start()
        mum, dad = seed(server)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in CONFIGS:
                    tag = f"{width}-{scheme}"
                    if args.only and args.only != tag:
                        continue
                    walk(Watched(browser, server.base, out, width, height, scheme, f"mum-{tag}", mum.cookies()),
                         SCREENS + ["admin"], shopping=True)
                    walk(Watched(browser, server.base, out, width, height, scheme, f"dad-{tag}", dad.cookies()),
                         SCREENS, shopping=False)
            finally:
                browser.close()
        log = server.log()
        check("the server log has no traceback", "Traceback" not in log, log[log.find("Traceback"):][:600] if "Traceback" in log else "")
        check("the server log never holds a secret", KEY not in log and "placeholder-withings-secret" not in log)
        check("nothing was sent to Instacart", "instacart fake: " not in log)
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
