#!/usr/bin/env python3
"""Build a self-contained preview of the web app: one HTML *fragment* with sample data.

Usage
=====

    python3 scripts/build_preview.py                 # writes build/kidney-diet-log.html (gitignored)
    python3 scripts/build_preview.py --out page.html  # anywhere else
    python3 scripts/build_preview.py --pages DIR      # the GitHub Pages demo: a static site in DIR (v0.3.1)
    python3 scripts/build_preview.py --device DIR     # the app packed inside the iPhone app (design note 38)
    python3 scripts/build_preview.py --device DIR --handbook SITE   # ... with the built handbook inside it (owner, 2026-11-26)

``--device`` writes the same static site for the iPhone app's web view, in **device mode**: no sample person, no demo
banner, and the data kept on the phone from the first start (``window.KDL_DEVICE``, js/mock/persist.js). The iPhone app
serves the folder under its own scheme with the same Content-Security-Policy; Learn links go to the published handbook,
which the app opens in Safari. It also writes ``ai-prompts.json``, the prompts the iPhone app gives Apple's on-device model, made
from ``app/ai/prompts.py`` so no prompt is written twice (:func:`ai_prompts`), and packs the vendored pdf.js so a lab report PDF can be
read on the phone.

``--handbook SITE`` (with ``--device``) packs a handbook built with ``mkdocs build`` (``handbook/mkdocs.yml``) into ``DIR/learn/`` so
Learn links open it in the app with no network (:func:`pack_handbook`). The iPhone app shows it in a sheet of its own. The theme's
inline scripts become files, every page gets a strict Content-Security-Policy, and what the app does not need is left out. Without
``--handbook`` Learn links go to the published handbook in Safari, as before.

``--pages`` writes the same app as a small static site instead of one fragment (``index.html``, the
stylesheets and scripts as files under their own paths, ``preview-flag.js``), because a public web page
should keep the app's Content-Security-Policy: ``index.html`` carries it as a ``<meta>`` element (Pages
cannot send headers), without ``frame-ancestors`` (ignored there), and holds no inline script; the food
database is an inline ``application/json`` block, which a browser never runs. The handbook's Pages workflow
builds it into ``site/demo/``.

The page needs no server and makes no network request. It inlines, in document order, every
``<link rel="stylesheet">`` and ``<script src>`` of ``app/static/index.html`` (the CSS files,
``theme-init.js`` and the ``js/`` modules), the body markup, and the whole builtin food database
``data/foods.json`` (as ``<script type="application/json" id="kdl-foods">``), and sets
``window.KDL_PREVIEW = true`` before the modules run, so the app runs against its in-page copy
of the server API (``js/mock/*``), seeded with a sample person ("Sam") and a month of meals.
Nothing is saved unless the person opts in (the demo's "Keep my data in this browser", docs/demo.md, which needs
IndexedDB and exists only where ``window.KDL_PREVIEW`` is set): otherwise reloading starts over.

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
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
FOODS_JSON = ROOT / "data" / "foods.json"
DEFAULT_OUT = ROOT / "build" / "kidney-diet-log.html"  # build/ is gitignored
MAX_BYTES = 16 * 1024 * 1024  # the preview host's page size limit

_HEAD_RE = re.compile(r"<head\b[^>]*>(.*?)</head\b[^>]*>", re.S | re.I)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body\b[^>]*>", re.S | re.I)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\b[^>]*>", re.S | re.I)
_DESCRIPTION_RE = re.compile(r"""<meta\s+name=["']description["']\s+content=["']([^"']*)["']\s*/?>""", re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# A <link ...> or a whole <script ...>...</script>, in document order.
_ASSET_RE = re.compile(r"<link\b[^>]*>|<script\b[^>]*>.*?</script\b[^>]*>", re.S | re.I)
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


def _assets(html: str, static_dir: Path, where: str, *, device: bool = False) -> list[tuple[str, Path]]:
    """[('style'|'script', file)] for the stylesheets and script files of `html`, in order. ``device``: a script marked
    ``data-device="keep"`` is kept although the demo leaves it out (Settings → Reminders, design note 35 §7)."""
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
        if attrs.get("data-preview") == "omit" and not (device and attrs.get("data-device") == "keep"):
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


PAGES_FLAG = "preview-flag.js"
# The demo sits in demo/ of the handbook's Pages site, so the published handbook is one level up.
PAGES_HANDBOOK = "../"
# Absolute paths of the served app and what they become in the demo: the in-app handbook (/learn/ and every page
# under it) is the published handbook; the proxy sign-in link and the "app did not start" Reload link stay in the demo.
PAGES_LINKS = {"/?reauth=1": "./?reauth=1", "/": "./"}
PAGES_PREFIXES = {"/learn/": PAGES_HANDBOOK}
SECURITY_PY = ROOT / "app" / "security.py"


def pages_flag_js() -> str:
    """``preview-flag.js``: the preview flag, and where the demo's Learn links go (js/mock/handbook.js answers
    ``GET /api/handbook`` like a server with a public handbook copy, with the server's own link table)."""
    sys.path.insert(0, str(ROOT))
    try:
        from app.guidance.topics import APP_LINKS  # pure data: the build needs no server packages
    finally:
        sys.path.pop(0)
    handbook = json.dumps({"url": PAGES_HANDBOOK, "links": APP_LINKS}, ensure_ascii=False, sort_keys=True)
    return (
        "/* Written by scripts/build_preview.py --pages: the GitHub Pages demo runs against the in-page demo API\n"
        "   (js/mock/*), and its Learn links go to the published handbook next to it. */\n"
        "window.KDL_PREVIEW = true;\n"
        f"window.KDL_DEMO_HANDBOOK = {handbook};\n"
    )


def pages_csp(security_py: Path = SECURITY_PY) -> str:
    """The app's Content-Security-Policy (``CSP_DIRECTIVES`` in app/security.py, read from the source so the build
    needs no server packages) as one ``<meta>`` value. ``frame-ancestors`` is ignored in a ``<meta>`` element (and
    logged), so it is left out; GitHub Pages sends no header of its own."""
    for node in ast.parse(security_py.read_text(encoding="utf-8")).body:
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets if isinstance(node, ast.Assign) else []
        if any(isinstance(t, ast.Name) and t.id == "CSP_DIRECTIVES" for t in targets) and node.value is not None:
            directives = ast.literal_eval(node.value)
            break
    else:
        raise SystemExit(f"{security_py}: CSP_DIRECTIVES not found")
    return "; ".join(d for d in directives if not d.startswith("frame-ancestors"))


DEVICE_FLAG = "device-flag.js"
# The published handbook, which the iPhone app opens in Safari (handbook/mkdocs.pages.yml site_url).
DEVICE_HANDBOOK = "https://ksullivan86.github.io/kidney-health/"


def device_flag_js(*, local_handbook: bool = False) -> str:
    """``device-flag.js``: device mode (design note 38), and where Learn links go: the handbook packed in the app
    (``learn/``, :func:`pack_handbook`), or else the published handbook, in Safari."""
    sys.path.insert(0, str(ROOT))
    try:
        from app.guidance.topics import APP_LINKS
    finally:
        sys.path.pop(0)
    where = {"url": f"{HANDBOOK_DIR}/", "local": True, "public": DEVICE_HANDBOOK} if local_handbook else {"url": DEVICE_HANDBOOK}
    handbook = json.dumps({**where, "links": APP_LINKS}, ensure_ascii=False, sort_keys=True)
    return (
        "/* Written by scripts/build_preview.py --device: the app inside the iPhone app runs against the in-page API\n"
        "   (js/mock/*) with no server, starts empty and keeps its data on the phone (design note 38). */\n"
        "window.KDL_PREVIEW = true;\n"
        "window.KDL_DEVICE = true;\n"
        f"window.KDL_DEMO_HANDBOOK = {handbook};\n"
    )


AI_PROMPTS = "ai-prompts.json"
AI_PROMPT_PLACEHOLDER = "{text}"
# The tasks the iPhone app's model does (design note 38 §5.6; note 39 §6.6): the bridge's task name -> (app/ai/prompts.py
# TASK_LINES key, the system message: "task" (TASK_SYSTEM_PROMPT), "meal" (the meal ideas rules) or "recipe" (the AI recipes
# rules without steps), a photo task). A photo task has no data block: the photo goes beside the message (iOS 27 only).
AI_DEVICE_TASKS = {
    "parse_meal": ("parse_meal", "task", False),
    "read_lab_report_text": ("lab_report_text", "task", False),
    "read_label": ("read_label", "task", True),
    "plate": ("plate", "task", True),
    "next_meal": ("ideas", "meal", False),
    "recipes": ("recipes_suggest", "recipe", False),
    "rerank": ("rerank", "meal", False),  # AI order, AI swaps and AI day plans (phone-ai-more2): the meal ideas rules
    "swap": ("swap", "meal", False),
    "plan": ("plan", "meal", False),
}
CONDITION = "[[CONDITION]]"
PDFJS = "vendor/pdfjs-dist-6.4.299"
PDFJS_FILES = ("pdf.min.mjs", "pdf.worker.min.mjs", "LICENSE")


def recipe_system_template(prompts) -> str:
    """``prompts.recipe_system_prompt(person, steps=False)`` with ``[[CONDITION]]`` left in (the phone never shows AI steps)."""
    text = prompts.RECIPE_SYSTEM_PROMPT
    for n in (3, 4, 6, 7, 8, 9):
        text = text.replace(f"[[RULE{n}]]", prompts._meal_rule(n))
    return text.replace("[[STEPS]]", prompts.RECIPE_NO_STEPS_RULE)


def ai_prompts() -> dict:
    """``ai-prompts.json``: what the iPhone app gives Apple's on-device model, taken from ``app/ai/prompts.py``.

    ``system`` is ``TASK_SYSTEM_PROMPT``; ``systems`` holds the meal ideas and AI recipes rules with ``[[CONDITION]]`` left in, and
    ``conditions`` every text ``prompts.condition_text`` can give, so the app only ever puts in one of those (the page names it).
    Each task's ``template`` is the user message ``prompts.user_message`` builds for a provider that enforces the answer's schema
    itself (mode ``json_schema``: no schema line, because guided generation enforces the shape), with the data block's JSON
    replaced by ``{text}``. The page sends that JSON, cleaned and escaped exactly as the server does (``KH.aiJudge.dataPayload``),
    so filling the template gives the server's message byte for byte. A photo task's template is the message alone."""
    sys.path.insert(0, str(ROOT))
    try:
        from app.ai import prompts
    finally:
        sys.path.pop(0)
    tasks = {}
    for task, (key, system, image) in AI_DEVICE_TASKS.items():
        if image:
            tasks[task] = {"template": prompts.user_message(key, None, mode="json_schema", schema={}), "system": system, "image": True}
            continue
        marker = {"marker": "x"}  # a data block whose JSON is found and replaced below
        message = prompts.user_message(key, marker, mode="json_schema", schema={})
        block = prompts.data_block(marker)
        if not message.endswith("\n" + block) or AI_PROMPT_PLACEHOLDER in message:
            raise SystemExit(f"app/ai/prompts.py: the {key} message is not a task line and one data block")
        template = message[: -len(block)] + "<data>\n" + AI_PROMPT_PLACEHOLDER + "\n</data>"
        tasks[task] = {"template": template, "system": system, "image": False}
    systems = {"meal": prompts.SYSTEM_PROMPT, "recipe": recipe_system_template(prompts)}
    for text in systems.values():
        if text.count(CONDITION) != 1:
            raise SystemExit("app/ai/prompts.py: the meal and recipe system messages must hold [[CONDITION]] once")
    conditions = sorted({prompts.condition_text({"ckd_stage": stage, "dialysis": dialysis, "diabetes": diabetes})
                         for stage in (None, *prompts.CKD_STAGES) for dialysis in (None, "none", *prompts.DIALYSIS_TEXT)
                         for diabetes in (None, "none", "other", *prompts.DIABETES_TEXT)})
    return {"system": prompts.TASK_SYSTEM_PROMPT, "systems": systems, "conditions": conditions, "tasks": tasks,
            "own_key": own_key_prompts()}


# The person's own AI key (owner, 2026-11-25; design note 39 §6.5): its prompts and schemas come from the server's code through
# scripts/gen_own_key_prompts.py, which needs the app's dependencies. This script runs with plain Python (the macOS jobs that pack
# the iPhone app install nothing), so it reads the generated file. tests/test_phone_own_key.py fails when that file is stale.
OWN_KEY_PROMPTS = ROOT / "app" / "ai" / "own_key_prompts.json"


def own_key_prompts() -> dict:
    """``own_key`` in ``ai-prompts.json``, read from ``app/ai/own_key_prompts.json`` (see :data:`OWN_KEY_PROMPTS`)."""
    return json.loads(OWN_KEY_PROMPTS.read_text(encoding="utf-8"))


# The handbook inside the iPhone app (owner, 2026-11-26): `pack_handbook` copies a built site into DIR/learn/.
HANDBOOK_DIR = "learn"
# The policy of every packed handbook page: its own files only, no inline script or style, nothing from the network.
HANDBOOK_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                "worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")
# What the app serves (ios/KidneyHealth/WebShell/WebAppFiles.swift mimeTypes); anything else in the site is left out.
HANDBOOK_TYPES = {".html", ".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff2", ".txt"}
# Left out: source maps, search for other languages (the handbook searches in English), the sitemap (only instant loading reads it,
# and that is turned off here) and the 404 page (the app never asks a server for a page).
HANDBOOK_SKIP = re.compile(r"(^|/)(assets/javascripts/lunr/|404\.html$|sitemap\.xml)|\.map$")
_INLINE_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\b[^>]*>", re.S | re.I)  # any end tag HTML accepts
_CONFIG_RE = re.compile(r'(<script id="__config" type="application/json">)(.*?)(</script\b[^>]*>)', re.S | re.I)
_CANONICAL_RE = re.compile(r'<link rel="canonical" href="[^"]*">\s*')
_CHARSET_RE = re.compile(r'<meta charset="utf-8">', re.I)
_REMOTE_RE = re.compile(r'''<(?:script|img|iframe|audio|video|source|embed|object)\b[^>]*\ssrc=["']?(?:https?:)?//|<link\b(?![^>]*rel="canonical")[^>]*href=["']?(?:https?:)?//''', re.I)


def _pack_page(html: str, page: str, inline_dir: str, scripts: dict[str, str]) -> str:
    """One handbook page for the app: each inline script as a file under ``inline_dir`` (same order, same content), no
    instant loading, no canonical link to the build host, and a ``<meta>`` Content-Security-Policy."""
    import hashlib
    import posixpath

    def config(m: re.Match) -> str:
        data = json.loads(m.group(2))
        data["features"] = [f for f in data.get("features", []) if not f.startswith("navigation.instant")]
        return m.group(1) + json.dumps(data, ensure_ascii=False) + m.group(3)

    html = _CONFIG_RE.sub(config, html)

    def script(m: re.Match) -> str:
        attrs = _attrs(f"<script{m.group(1)}>")
        if "src" in attrs or attrs.get("type", "text/javascript") not in ("text/javascript", "module", ""):
            return m.group(0)  # a file already, or data (application/json), which a browser never runs
        body = m.group(2)
        name = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16] + ".js"
        scripts[name] = body
        rel = posixpath.relpath(f"{inline_dir}/{name}", posixpath.dirname(page) or ".")
        kind = ' type="module"' if attrs.get("type") == "module" else ""
        return f'<script src="{rel}"{kind}></script>'

    html = _INLINE_SCRIPT_RE.sub(script, html)
    html = _CANONICAL_RE.sub("", html)
    if not _CHARSET_RE.search(html):
        raise SystemExit(f"handbook page {page}: no <meta charset>")
    html = _CHARSET_RE.sub(f'<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="{HANDBOOK_CSP}">', html, count=1)
    if re.search(r"\sstyle\s*=|<style\b", html, re.I):
        raise SystemExit(f"handbook page {page}: an inline style, which the app's policy forbids")
    if _REMOTE_RE.search(html):
        raise SystemExit(f"handbook page {page}: loads something from the network")
    return html


def pack_handbook(site: Path, out_dir: Path) -> list[Path]:
    """Copy the handbook built in ``site`` (``mkdocs build``, handbook/mkdocs.yml) into ``out_dir/learn/`` for the iPhone app.

    Every HTML page goes through :func:`_pack_page`; the theme's inline scripts (the same few on every page) are written once
    each to ``learn/assets/javascripts/inline/<sha-256>.js``. Only the types the app serves are copied, without source maps,
    other languages' search, the sitemap and the 404 page. Refuses a page with an inline style or anything from the network."""
    if not (site / "index.html").is_file():
        raise SystemExit(f"{site}: not a built handbook (no index.html); build it with mkdocs first")
    root = out_dir / HANDBOOK_DIR
    inline_dir = "assets/javascripts/inline"
    scripts: dict[str, str] = {}
    written: list[Path] = []
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        rel = path.relative_to(site).as_posix()
        if HANDBOOK_SKIP.search(rel) or path.suffix.lower() not in HANDBOOK_TYPES or any(part.startswith(".") for part in rel.split("/")):
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".html":
            target.write_text(_pack_page(path.read_text(encoding="utf-8"), rel, inline_dir, scripts), encoding="utf-8")
        else:
            target.write_bytes(path.read_bytes())
        written.append(target)
    for name, body in sorted(scripts.items()):
        target = root / inline_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        written.append(target)
    return written


def build_device(out_dir: Path, static_dir: Path = STATIC, foods_json: Path = FOODS_JSON, *, handbook: Path | None = None) -> list[Path]:
    """The static site of :func:`build_pages` in device mode, for the iPhone app (design note 38, steps 1 and 5), with
    ``ai-prompts.json`` and the vendored pdf.js (the page loads it from ``/vendor/...``, the root of the app's own scheme), and
    the built handbook in ``learn/`` when ``handbook`` names one (:func:`pack_handbook`)."""
    written = build_pages(out_dir, static_dir, foods_json, device=True)
    if handbook is not None:
        written += pack_handbook(handbook, out_dir)
        (out_dir / DEVICE_FLAG).write_text(device_flag_js(local_handbook=True), encoding="utf-8")
    for name in PDFJS_FILES:
        target = out_dir / PDFJS / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((static_dir / PDFJS / name).read_bytes())
        written.append(target)
    prompts_file = out_dir / AI_PROMPTS
    prompts_file.write_text(json.dumps(ai_prompts(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(prompts_file)
    return written


def build_pages(out_dir: Path, static_dir: Path = STATIC, foods_json: Path = FOODS_JSON, *, device: bool = False) -> list[Path]:
    """Write the demo as a static site into ``out_dir`` (created or emptied of the files it writes); returns the
    files written. Same app, same flags and sample data as the fragment; files instead of inline code. ``device``: the
    iPhone app's copy instead (:func:`build_device`)."""
    flag_name = DEVICE_FLAG if device else PAGES_FLAG
    prefixes = {"/learn/": DEVICE_HANDBOOK} if device else PAGES_PREFIXES
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

    written: list[Path] = []

    def copy(path: Path) -> str:
        rel = path.relative_to(static_dir).as_posix()
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        written.append(target)
        return rel

    # The app's icon (the installed-app tags stay out), so the browser does not ask the site root for /favicon.ico.
    head_tags = [f'<link rel="icon" href="{copy(static_dir / "icons" / "icon.svg")}" type="image/svg+xml">']
    for kind, path in _assets(head, static_dir, "head"):
        rel = copy(path)
        head_tags.append(f'<link rel="stylesheet" href="{rel}">' if kind == "style" else f'<script src="{rel}"></script>')
    body_scripts = _assets(body, static_dir, "body", device=device)
    markup = _ASSET_RE.sub("", body).strip()
    markup = re.sub(r"\n{3,}", "\n\n", markup)
    if re.search(r"<script\b", markup, re.I) or re.search(r"<link\b", markup, re.I):
        raise SystemExit("index.html: body still references external files")
    for app_path, pages_path in PAGES_LINKS.items():
        markup = markup.replace(f'href="{app_path}"', f'href="{pages_path}"')
    for app_prefix, pages_prefix in prefixes.items():
        markup = markup.replace(f'href="{app_prefix}', f'href="{pages_prefix}')
    leftover = re.findall(r'(?:href|src)="(/[^"]*)"', markup)
    if leftover:
        raise SystemExit(f"index.html: absolute paths the Pages demo cannot serve: {sorted(set(leftover))}")
    flag = out_dir / flag_name
    out_dir.mkdir(parents=True, exist_ok=True)
    flag.write_text(device_flag_js() if device else pages_flag_js(), encoding="utf-8")
    written.append(flag)
    body_tags = [f'<script src="{copy(path)}"></script>' for _kind, path in body_scripts]
    foods_text = _escape_json_for_script(json.dumps(foods, ensure_ascii=False, separators=(",", ":")))
    page = "\n".join(p for p in [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f'<meta http-equiv="Content-Security-Policy" content="{pages_csp()}">',
        '<meta name="referrer" content="no-referrer">',
        f"<title>{title}</title>" if device else f"<title>{title} (demo)</title>",
        f'<meta name="description" content="{description}">' if description else "",
        *head_tags,
        "</head>",
        "<body>",
        markup,
        f'<script type="application/json" id="kdl-foods">{foods_text}</script>',
        f'<script src="{flag_name}"></script>',
        *body_tags,
        "</body>",
        "</html>",
    ] if p) + "\n"
    index_out = out_dir / "index.html"
    index_out.write_text(page, encoding="utf-8")
    written.append(index_out)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output file (default: {DEFAULT_OUT})")
    parser.add_argument("--pages", type=Path, default=None, metavar="DIR",
                        help="write the GitHub Pages demo (a static site) into DIR instead of one fragment")
    parser.add_argument("--device", type=Path, default=None, metavar="DIR",
                        help="write the iPhone app's copy (device mode, design note 38) into DIR")
    parser.add_argument("--handbook", type=Path, default=None, metavar="SITE",
                        help="with --device: pack the handbook built in SITE (mkdocs build) into DIR/learn/")
    args = parser.parse_args(argv)
    if args.handbook is not None and args.device is None:
        parser.error("--handbook needs --device")
    if args.device is not None:
        files = build_device(args.device, handbook=args.handbook)
        total = sum(f.stat().st_size for f in files)
        print(f"wrote the iPhone app's copy to {args.device} ({len(files)} files, {total:,} bytes)")
        return 0
    if args.pages is not None:
        files = build_pages(args.pages)
        total = sum(f.stat().st_size for f in files)
        print(f"wrote the Pages demo to {args.pages} ({len(files)} files, {total:,} bytes)")
        return 0
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
