#!/usr/bin/env python3
"""The screenshots on the README, taken from the demo.

    python tools/e2e/readme_shots.py                 # writes docs/screenshots/*.png
    python tools/e2e/readme_shots.py --out /tmp/shots

Builds the GitHub Pages demo (``scripts/build_preview.py --pages``), serves it on localhost and takes four phone-sized
screenshots (390x844 at 2x) of the sample person "Sam": Today, What fits now, Trends and the lab results (in dark mode).
The preview banner is closed first so the screens look like the installed app. If Pillow is installed, each PNG is reduced
to 256 colours to keep the repository small; without it the files are saved as Chromium writes them.

Nothing leaves the machine. Run it again after a change to these screens and commit the new files.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import khserver
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "screenshots"
WIDTH, HEIGHT = 390, 844
HEADER = 64  # the sticky top bar, so a section scrolled to the top is not hidden under it


def serve(site: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://localhost:{httpd.server_address[1]}"


def open_demo(browser: Any, base: str, scheme: str) -> Any:
    ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2, color_scheme=scheme, base_url=base)
    page = ctx.new_page()
    page.goto("/")
    page.wait_for_selector("#preview-banner-close")
    page.click("#preview-banner-close")
    page.wait_for_timeout(400)
    return page


def scroll_to(page: Any, locator: Any) -> None:
    locator.first.evaluate(f"(el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - {HEADER})")
    page.wait_for_timeout(400)


def shrink(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    with Image.open(path) as image:
        small = image.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    small.save(path, optimize=True)


def take(out: Path, browser: Any, base: str) -> list[Path]:
    shots = []
    page = open_demo(browser, base, "light")
    page.wait_for_timeout(800)
    shots.append(out / "today.png")
    page.screenshot(path=str(shots[-1]))

    page.click("#tab-add")
    page.click("label[for=gfm-dinner]")
    page.wait_for_selector("#guidance-fits-body button:has-text('Add')")
    page.wait_for_timeout(400)
    shots.append(out / "what-fits.png")
    page.screenshot(path=str(shots[-1]))

    page.click("#tab-trends")
    page.wait_for_timeout(800)
    scroll_to(page, page.locator("#body-trends"))
    shots.append(out / "trends.png")
    page.screenshot(path=str(shots[-1]))
    page.context.close()

    page = open_demo(browser, base, "dark")
    page.click("#tab-profile")
    page.wait_for_timeout(800)
    scroll_to(page, page.locator("#view-profile").get_by_text("Blood and urine tests", exact=True))
    shots.append(out / "labs-dark.png")
    page.screenshot(path=str(shots[-1]))
    page.context.close()
    return shots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"where to write the PNG files (default {OUT.relative_to(REPO)})")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "demo"
        subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--pages", str(site)], check=True, capture_output=True)
        httpd, base = serve(site)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
                try:
                    shots = take(args.out, browser, base)
                finally:
                    browser.close()
        finally:
            httpd.shutdown()
    for path in shots:
        shrink(path)
        print(f"{path} ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
