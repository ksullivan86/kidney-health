#!/usr/bin/env python3
"""Build a self-contained preview of the web app: one HTML *fragment* with sample data.

Usage
=====

    python3 scripts/build_preview.py                 # writes build/kidney-diet-log.html (gitignored)
    python3 scripts/build_preview.py --out page.html  # anywhere else

The page needs no server and makes no network request. It inlines, in document order, every
``<link rel="stylesheet">`` and ``<script src>`` of ``app/static/index.html`` (the CSS files,
``theme-init.js`` and the ``js/`` modules), the body markup, and the whole builtin food database
``data/foods.json`` (as ``<script type="application/json" id="kdl-foods">``), and sets
``window.KDL_PREVIEW = true`` before the modules run, so the app runs against its in-page copy
of the server API (``js/mock/*``), seeded with a sample person ("Sam") and a month of meals.
Nothing is saved: reloading starts over.

Left out on purpose: the installed-app tags of ``<head>`` (manifest, icons, apple-touch-icon,
apple-mobile-web-app-title) and every script marked ``data-preview="omit"`` (``js/pwa.js``:
the preview never registers a service worker). ``index.html`` itself may hold no inline script
(the app's CSP forbids it); the builder refuses one.

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
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# A <link ...> or a whole <script ...>...</script>, in document order.
_ASSET_RE = re.compile(r"<link\b[^>]*>|<script\b[^>]*>.*?</script\s*>", re.S | re.I)
_ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")


def _escape_json_for_script(text: str) -> str:
    """JSON that cannot end its <script> element early (escapes stay valid JSON)."""
    return text.replace("<!--", "<\\u0021--").replace("</", "<\\/")


def _escape_js_for_script(text: str) -> str:
    """JavaScript that cannot end its <script> element early."""
    text = re.sub(r"</(script)", r"<\\/\1", text, flags=re.I)
    return text.replace("<!--", "<\\!--")


def _attrs(tag: str) -> dict[str, str]:
    """Attributes of an opening tag (names lower-cased; valueless attributes map to '')."""
    inner = re.match(r"<\s*\w+(.*?)/?>", tag, re.S)
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(inner.group(1) if inner else ""):
        out[m.group(1).lower()] = next((g for g in m.groups()[1:] if g is not None), "")
    return out


def _local_file(static_dir: Path, ref: str, what: str) -> Path:
    if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", ref, re.I):
        raise SystemExit(f"index.html: {what} {ref!r} is not a local file")
    path = (static_dir / ref.lstrip("/")).resolve()
    if static_dir.resolve() not in path.parents or not path.is_file():
        raise SystemExit(f"index.html: {what} {ref!r} not found under {static_dir}")
    return path


def _assets(html: str, static_dir: Path, where: str) -> list[tuple[str, Path]]:
    """[('style'|'script', file)] for the stylesheets and script files of `html`, in order."""
    out: list[tuple[str, Path]] = []
    for m in _ASSET_RE.finditer(html):
        tag = m.group(0)
        attrs = _attrs(tag.split(">", 1)[0] + ">")
        if tag.lower().startswith("<link"):
            if "stylesheet" in attrs.get("rel", "").lower().split():
                out.append(("style", _local_file(static_dir, attrs.get("href", ""), "stylesheet")))
            elif where == "body":
                raise SystemExit("index.html: a <link> in <body> (only stylesheets in <head> are inlined)")
            continue  # manifest, icons, apple-touch-icon: the installed app's, not the preview's
        if "src" not in attrs:
            raise SystemExit("index.html: inline <script> found; the CSP allows only script files")
        if attrs.get("data-preview") == "omit":
            continue
        out.append(("script", _local_file(static_dir, attrs["src"], "script")))
    return out


def build_fragment(static_dir: Path = STATIC, foods_json: Path = FOODS_JSON) -> str:
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    foods = json.loads(foods_json.read_text(encoding="utf-8"))
    if not isinstance(foods, dict) or not isinstance(foods.get("foods"), list):
        raise SystemExit(f"{foods_json}: expected {{version, source, foods: [...]}}")

    head_m, body_m = _HEAD_RE.search(index), _BODY_RE.search(index)
    if not head_m or not body_m:
        raise SystemExit("index.html: could not find <head> and <body>")
    head, body = _COMMENT_RE.sub("", head_m.group(1)), _COMMENT_RE.sub("", body_m.group(1))
    title_m = _TITLE_RE.search(head)
    title = title_m.group(1).strip() if title_m else "Kidney Diet Log"
    desc_m = _DESCRIPTION_RE.search(head)
    description = desc_m.group(1) if desc_m else ""

    head_parts: list[str] = []
    for kind, path in _assets(head, static_dir, "head"):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(static_dir).as_posix()
        if kind == "style":
            if re.search(r"</style", text, re.I):
                raise SystemExit(f"{rel} contains '</style'; it cannot be inlined as is")
            head_parts.append(f"<style>\n/* {rel} */\n{text.rstrip()}\n</style>")
        else:
            # Head scripts run before the host's page is fully set up (theme-init.js reads
            # localStorage): they must be safe where storage throws.
            if "try" not in text or "catch" not in text:
                raise SystemExit(f"{rel}: a <head> script must keep its storage access inside try/catch")
            head_parts.append(f"<script>\n{_escape_js_for_script(text).rstrip()}\n</script>")

    # Body markup without the tags that load files (the scripts are inlined below).
    body_scripts = _assets(body, static_dir, "body")
    markup = _ASSET_RE.sub("", body).strip()
    markup = re.sub(r"\n{3,}", "\n\n", markup)
    if re.search(r"<script\b", markup, re.I) or re.search(r"<link\b", markup, re.I):
        raise SystemExit("index.html: body still references external files")

    foods_text = _escape_json_for_script(json.dumps(foods, ensure_ascii=False, separators=(",", ":")))
    parts = [
        f"<title>{title}</title>",
        f'<meta name="description" content="{description}">' if description else "",
        *head_parts,
        markup,
        f'<script type="application/json" id="kdl-foods">{foods_text}</script>',
        "<script>window.KDL_PREVIEW = true;</script>",
        *(f"<script>\n/* {path.relative_to(static_dir).as_posix()} */\n{_escape_js_for_script(path.read_text(encoding='utf-8')).rstrip()}\n</script>"
          for _kind, path in body_scripts),
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
