#!/usr/bin/env python3
"""Build a self-contained preview of the web app: one HTML *fragment* with sample data.

Usage
=====

    python3 scripts/build_preview.py                 # writes build/kidney-diet-log.html (gitignored)
    python3 scripts/build_preview.py --out page.html  # anywhere else

The page needs no server and makes no network request. It inlines ``app/static/style.css``,
the body markup of ``app/static/index.html``, the whole builtin food database
``data/foods.json`` (as ``<script type="application/json" id="kdl-foods">``) and
``app/static/app.js``, and sets ``window.KDL_PREVIEW = true`` so the app runs against its
in-page copy of the server API, seeded with a sample person ("Sam") and a month of meals.
Nothing is saved: reloading starts over.

The output is a fragment meant for a host page that supplies the document skeleton (doctype,
``<html>``, ``<head>`` with charset and viewport, ``<body>``): it starts with ``<title>`` and
``<style>`` and contains no doctype, html, head or body tags. To open it directly in a browser,
wrap it in a minimal skeleton first. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
FOODS_JSON = ROOT / "data" / "foods.json"
DEFAULT_OUT = ROOT / "build" / "kidney-diet-log.html"  # build/ is gitignored
MAX_BYTES = 16 * 1024 * 1024  # the preview host's page size limit

_HEAD_RE = re.compile(r"<head\b[^>]*>(.*?)</head\s*>", re.S | re.I)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body\s*>", re.S | re.I)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_DESCRIPTION_RE = re.compile(r"""<meta\s+name=["']description["']\s+content=["']([^"']*)["']\s*/?>""", re.I)
_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>.*?</script\s*>", re.S | re.I)
_FILE_SCRIPT_RE = re.compile(r"\s*<script\b[^>]*\bsrc\s*=[^>]*>\s*</script\s*>", re.S | re.I)
_LINK_RE = re.compile(r"\s*<link\b[^>]*>", re.I)


def _escape_json_for_script(text: str) -> str:
    """JSON that cannot end its <script> element early (escapes stay valid JSON)."""
    return text.replace("<!--", "<\\u0021--").replace("</", "<\\/")


def _escape_js_for_script(text: str) -> str:
    """JavaScript that cannot end its <script> element early."""
    text = re.sub(r"</(script)", r"<\\/\1", text, flags=re.I)
    return text.replace("<!--", "<\\!--")


def build_fragment(static_dir: Path = STATIC, foods_json: Path = FOODS_JSON) -> str:
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    css = (static_dir / "style.css").read_text(encoding="utf-8")
    js = (static_dir / "app.js").read_text(encoding="utf-8")
    foods = json.loads(foods_json.read_text(encoding="utf-8"))
    if not isinstance(foods, dict) or not isinstance(foods.get("foods"), list):
        raise SystemExit(f"{foods_json}: expected {{version, source, foods: [...]}}")

    head_m, body_m = _HEAD_RE.search(index), _BODY_RE.search(index)
    if not head_m or not body_m:
        raise SystemExit("index.html: could not find <head> and <body>")
    head, body = head_m.group(1), body_m.group(1)
    title_m = _TITLE_RE.search(head)
    title = title_m.group(1).strip() if title_m else "Kidney Diet Log"
    desc_m = _DESCRIPTION_RE.search(head)
    description = desc_m.group(1) if desc_m else ""
    # The small inline theme script (applies a stored light/dark choice before first paint; its
    # storage access is already inside try/catch). Everything else in <head> belongs to the host.
    theme_scripts = _INLINE_SCRIPT_RE.findall(head)
    for script in theme_scripts:
        if "try" not in script or "catch" not in script:
            raise SystemExit("index.html: an inline <head> script is not try/catch-safe")

    # Body markup without the tags that load files (app.js is inlined below).
    markup = _LINK_RE.sub("", _FILE_SCRIPT_RE.sub("", body)).strip()
    if re.search(r"<script\b[^>]*\bsrc\s*=", markup, re.I) or re.search(r"<link\b", markup, re.I):
        raise SystemExit("index.html: body still references external files")
    if re.search(r"</style", css, re.I):
        raise SystemExit("style.css contains '</style'; it cannot be inlined as is")

    foods_text = _escape_json_for_script(json.dumps(foods, ensure_ascii=False, separators=(",", ":")))
    parts = [
        f"<title>{title}</title>",
        f'<meta name="description" content="{description}">' if description else "",
        f"<style>\n{css.rstrip()}\n</style>",
        *(s.strip() for s in theme_scripts),
        markup,
        f'<script type="application/json" id="kdl-foods">{foods_text}</script>',
        "<script>window.KDL_PREVIEW = true;</script>",
        f"<script>\n{_escape_js_for_script(js).rstrip()}\n</script>",
    ]
    return "\n".join(p for p in parts if p) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output file (default: {DEFAULT_OUT})")
    args = parser.parse_args(argv)
    fragment = build_fragment()
    data = fragment.encode("utf-8")
    if len(data) > MAX_BYTES:
        print(f"error: the preview is {len(data):,} bytes, over the {MAX_BYTES:,}-byte limit", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    print(f"wrote {args.out} ({len(data):,} bytes, {len(data) / 1024:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
