#!/usr/bin/env python3
"""Boot failure walk: "The app did not start" (index.html #boot-fail) in Chromium against a real server.

Every view stays hidden until the scripts boot. Over a VPN that drops large packets (a path MTU black hole) the page
arrives but the big script files do not, and the person used to see only the header. The notice needs no script:
CSS shows it after 8 seconds, and js/main.js hides it once a screen is showing.

1. **Scripts allowed.** Signed in (Today), signed out (the sign-in screen) and the demo (``/?mock=1``): the notice is
   hidden and stays hidden after the 8 seconds.
2. **The main script blocked** (a Playwright route aborts ``js/main.js``): the notice is invisible at first and visible
   after about 8 seconds, with the Reload link to ``/`` and the troubleshooting link. Again with reduced motion.
3. **A large script that never finishes** (the route holds ``js/views/settings.js``, the largest, without answering),
   which is what a black hole looks like: the notice shows after the delay.
4. **A script that throws** (``js/core.js`` replaced by one that throws): the notice shows at once, naming the error.

Service workers are blocked in every context, so the routes see every request.

    python3 tools/e2e/boot_fail.py                       # a real server on 127.0.0.1:8191; exit 1 on any failed check
    python3 tools/e2e/boot_fail.py --repo /path/to/old   # the same checks against another checkout (before a fix)
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
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "boot-fail"
PORT = 8191
DELAY_MS = 8000
RESULTS: list[dict[str, Any]] = []
VISIBLE = "() => { const n = document.getElementById('boot-fail'); return !!n && !n.hidden && getComputedStyle(n).visibility === 'visible'; }"


def check(name: str, ok: Any, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append({"check": name, "ok": ok, "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {detail}" if detail and not ok else ""), flush=True)
    return ok


def notice_state(page: Any) -> dict[str, Any]:
    return page.evaluate("""() => {
      const n = document.getElementById('boot-fail');
      const views = [...document.querySelectorAll('main > section')].filter((s) => s.id !== 'boot-fail' && !s.hidden).map((s) => s.id);
      const top = document.querySelector('header.topbar');
      const seen = { views, header: !!top && top.checkVisibility(), shown: document.body.innerText.replace(/\\s+/g, ' ').trim().slice(0, 120) };
      if (!n) return { present: false, ...seen };
      return { present: true, hidden: n.hidden, visibility: getComputedStyle(n).visibility, visible: n.checkVisibility({ visibilityProperty: true }),
               text: n.innerText, now: n.classList.contains('boot-fail-now'), at: Math.round(performance.now()), ...seen };
    }""")


def walk_started(ctx: Any, name: str, path: str, ready: str) -> None:
    page = ctx.new_page()
    page.goto(path)
    page.wait_for_selector(ready, timeout=20000)
    page.wait_for_timeout(DELAY_MS + 1500)
    st = notice_state(page)
    check(f"{name}: the notice is in the page", st.get("present"), json.dumps(st))
    check(f"{name}: the app started and the notice never shows", st.get("present") and st["hidden"] and not st["visible"], json.dumps(st))
    page.close()


def walk_blocked(ctx: Any, name: str, pattern: str, handler: Any = None, *, at_once: bool = False, says: str = "") -> None:
    """``handler`` None holds the request without an answer, the way a stalled download looks to the page."""
    page = ctx.new_page()
    held: list[Any] = []
    page.route(pattern, handler or (lambda route: held.append(route)))
    page.goto("/", wait_until="commit")
    page.wait_for_selector("header.topbar", timeout=20000)
    page.wait_for_timeout(2000)
    early = notice_state(page)
    if at_once:
        check(f"{name}: the notice shows at once, without waiting", early.get("present") and early["visible"] and early["now"], json.dumps(early))
    else:
        check(f"{name}: the notice is invisible at first", early.get("present") and not early["visible"]
              and early["visibility"] == "hidden", json.dumps(early))
        try:
            page.wait_for_function(VISIBLE, timeout=DELAY_MS + 6000, polling=100)
        except Exception:  # noqa: BLE001 - reported by the check below
            pass
    st = notice_state(page)
    shown = st.get("present") and st["visible"]
    check(f"{name}: the notice is visible", shown, json.dumps(st))
    if not at_once and shown:
        check(f"{name}: it shows after about 8 seconds", DELAY_MS - 500 <= st["at"] <= DELAY_MS + 4000, f"at {st['at']} ms")
    if shown:
        check(f"{name}: only the header and the notice show", st["header"] and st["views"] == [], json.dumps(st["views"]))
        check(f"{name}: it says what happened", says in st["text"], st["text"])
        check(f"{name}: it mentions the VPN", "NetBird, Tailscale or WireGuard" in st["text"], st["text"])
        links = page.evaluate("() => [...document.querySelectorAll('#boot-fail a')].map((a) => [a.textContent.trim(), a.getAttribute('href')])")
        check(f"{name}: a plain Reload link and the troubleshooting link", links == [
            ["Reload", "/"], ["What to change on the server", "/learn/self-hosting/troubleshooting/#only-the-header-shows-over-a-vpn"]],
            json.dumps(links))
    for route in held:
        try:
            route.abort()
        except Exception:  # noqa: BLE001 - the page may have given up on it already
            pass
    page.unroute_all(behavior="ignoreErrors")
    page.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--repo", type=Path, default=khserver.REPO, help="the checkout whose server and page to test")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    out = khserver.free_dir(args.out)
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
           "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env, repo=args.repo.resolve())
    try:
        server.start()
        ana = first_admin(server, "ana")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                def context(**kw: Any) -> Any:
                    return browser.new_context(viewport={"width": 390, "height": 844}, base_url=server.base, service_workers="block", **kw)

                signed_in = context()
                signed_in.add_cookies([{"name": k, "value": v, "url": server.base} for k, v in ana.cookies().items()])
                anonymous = context()
                reduced = context(reduced_motion="reduce")
                walks = [
                    ("Signed in", lambda: walk_started(signed_in, "Signed in", "/", "#view-today:not([hidden])")),
                    ("Signed out", lambda: walk_started(anonymous, "Signed out", "/", "#view-auth:not([hidden])")),
                    ("Demo", lambda: walk_started(anonymous, "Demo", "/?mock=1", "#view-today:not([hidden])")),
                    ("Main script blocked", lambda: walk_blocked(signed_in, "Main script blocked", "**/js/main.js",
                                                                 lambda route: route.abort(), says="did not finish loading")),
                    ("Reduced motion", lambda: walk_blocked(reduced, "Reduced motion", "**/js/main.js",
                                                            lambda route: route.abort(), says="did not finish loading")),
                    ("Large script stalls", lambda: walk_blocked(signed_in, "Large script stalls", "**/js/views/settings.js",
                                                                 says="did not finish loading")),
                    ("Script throws", lambda: walk_blocked(
                        signed_in, "Script throws", "**/js/core.js",
                        lambda route: route.fulfill(status=200, content_type="text/javascript", body="throw new Error('broken core');"),
                        at_once=True, says="The app could not start: Uncaught Error: broken core")),
                ]
                for name, walk in walks:
                    try:  # each step on its own page, so one failure does not hide the others
                        walk()
                    except Exception:
                        traceback.print_exc(limit=2)
                        check(f"{name}: the step ran to the end", False, traceback.format_exc(limit=2).strip().splitlines()[-1])
                for ctx in (signed_in, anonymous, reduced):
                    ctx.close()
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, traceback.format_exc(limit=3))
    finally:
        server.stop()
    failed = [r for r in RESULTS if not r["ok"]]
    (out / "report.json").write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed; report {out / 'report.json'}")
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
