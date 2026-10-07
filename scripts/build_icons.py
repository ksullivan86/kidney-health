#!/usr/bin/env python3
"""Render the app's PNG icons from their SVG sources (dev only; the PNGs are committed).

Usage
=====

    pip install -r requirements-tools.txt         # Playwright, not needed by the app or CI
    python3 scripts/build_icons.py                 # writes the five PNGs below
    CHROMIUM=/path/to/chrome python3 scripts/build_icons.py   # use an existing Chromium build
    python3 scripts/build_icons.py --check         # verify the committed PNGs, render nothing

Sources (note 02 R11): ``app/static/icons/icon.svg`` (the round badge on a transparent
background, ``purpose: any``) and ``app/static/icons/icon-maskable.svg`` (a full-bleed
#2e7d32 square with the same glyph, inside the 40 % maskable safe zone).

Outputs: ``icons/icon-192.png`` and ``icons/icon-512.png`` (RGBA), ``icons/icon-maskable-192.png``,
``icons/icon-maskable-512.png`` and ``apple-touch-icon.png`` (180 x 180) as opaque RGB: iOS fills
transparent areas of a home-screen icon and rounds the corners itself. Pillow cannot read SVG,
so Chromium renders a data-URI ``<img>`` at the exact size with device scale factor 1.

``CHROMIUM`` selects the browser binary when the installed Playwright package expects a
different revision (true in some cloud sandboxes); without it Playwright's own Chromium is
used (``python -m playwright install chromium`` once).
"""
from __future__ import annotations

import argparse
import base64
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ICONS = STATIC / "icons"

# (source SVG, output PNG, size in px, opaque)
OUTPUTS: tuple[tuple[Path, Path, int, bool], ...] = (
    (ICONS / "icon.svg", ICONS / "icon-192.png", 192, False),
    (ICONS / "icon.svg", ICONS / "icon-512.png", 512, False),
    (ICONS / "icon-maskable.svg", ICONS / "icon-maskable-192.png", 192, True),
    (ICONS / "icon-maskable.svg", ICONS / "icon-maskable-512.png", 512, True),
    (ICONS / "icon-maskable.svg", STATIC / "apple-touch-icon.png", 180, True),
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOUR_TYPES = {2: "RGB", 6: "RGBA"}


def png_info(data: bytes) -> tuple[int, int, int]:
    """(width, height, colour type) from a PNG's IHDR chunk, using only struct."""
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    width, height, _depth, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, colour


def check(outputs=OUTPUTS) -> list[str]:
    """Problems with the committed PNGs (empty when every icon has its size and colour type)."""
    problems = []
    for _src, out, size, opaque in outputs:
        rel = out.relative_to(ROOT)
        if not out.is_file():
            problems.append(f"{rel}: missing")
            continue
        try:
            width, height, colour = png_info(out.read_bytes())
        except ValueError as exc:
            problems.append(f"{rel}: {exc}")
            continue
        if (width, height) != (size, size):
            problems.append(f"{rel}: {width}x{height}, expected {size}x{size}")
        want = 2 if opaque else 6
        if colour != want:
            problems.append(f"{rel}: colour type {colour} ({COLOUR_TYPES.get(colour, '?')}), expected {want} ({COLOUR_TYPES[want]})")
    return problems


def render(outputs=OUTPUTS) -> None:
    from playwright.sync_api import sync_playwright  # dev-only dependency (requirements-tools.txt)

    chromium = os.environ.get("CHROMIUM") or None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium, headless=True)
        try:
            for src, out, size, opaque in outputs:
                svg = base64.b64encode(src.read_bytes()).decode("ascii")
                page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
                page.set_content(
                    "<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;background:transparent}"
                    "img{display:block}</style></head><body>"
                    f"<img alt='' width='{size}' height='{size}' src='data:image/svg+xml;base64,{svg}'></body></html>"
                )
                page.wait_for_function("() => document.images[0].complete && document.images[0].naturalWidth > 0")
                out.write_bytes(page.screenshot(clip={"x": 0, "y": 0, "width": size, "height": size}, omit_background=not opaque))
                page.close()
                print(f"wrote {out.relative_to(ROOT)} ({size}x{size}, {'opaque' if opaque else 'transparent'})")
        finally:
            browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="verify the committed PNGs instead of rendering")
    args = parser.parse_args(argv)
    if not args.check:
        render()
    problems = check()
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
