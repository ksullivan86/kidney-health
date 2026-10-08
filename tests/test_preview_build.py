"""scripts/build_preview.py: the self-contained preview fragment (no network, no skeleton tags), and the GitHub
Pages demo (``--pages``, v0.3.1): the same app as a small static site that keeps the app's CSP."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _AssetLister(HTMLParser):
    """Collects stylesheet links and script sources in document order, split at </head>."""

    def __init__(self) -> None:
        super().__init__()
        self.in_head = True
        self.styles: list[str] = []
        self.head_scripts: list[str] = []
        self.body_scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "body":
            self.in_head = False
        elif tag == "link" and a.get("rel") == "stylesheet" and a.get("href"):
            self.styles.append(a["href"])
        elif tag == "script" and a.get("src"):
            if self.in_head:
                self.head_scripts.append(a["src"])
            elif a.get("data-preview") != "omit":
                self.body_scripts.append(a["src"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False


def _index_assets() -> tuple[list[str], list[str], list[str]]:
    """(stylesheets, head scripts, body scripts kept for the preview) as index.html lists them."""
    lister = _AssetLister()
    lister.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    lister.close()
    return lister.styles, lister.head_scripts, lister.body_scripts


@pytest.fixture(scope="module")
def fragment(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("preview") / "kidney-diet-log.html"
    assert _load_builder().main(["--out", str(out)]) == 0
    assert out.stat().st_size < 16 * 1024 * 1024
    return out.read_text(encoding="utf-8")


def test_preview_fragment(tmp_path: Path, capsys) -> None:
    out = tmp_path / "preview" / "kidney-diet-log.html"
    assert _load_builder().main(["--out", str(out)]) == 0
    assert str(out) in capsys.readouterr().out  # prints where it wrote (and the size)
    html = out.read_text(encoding="utf-8")

    # A fragment: the host page supplies the skeleton.
    assert html.startswith("<title>")
    for tag in ("!doctype", "html", "/html", "head", "/head", "body", "/body"):
        assert not re.search(rf"<{tag}[\s>]", html, re.I), f"<{tag}> found"

    # The whole food database, parseable from its script element.
    m = re.search(r'<script type="application/json" id="kdl-foods">(.*?)</script>', html, re.S)
    assert m, "embedded food database missing"
    foods = json.loads(m.group(1))
    assert len(foods["foods"]) == 395
    assert foods == json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))

    assert "window.KDL_PREVIEW = true" in html
    # No network: nothing loads from http(s) URLs and no file is referenced.
    assert not re.search(r"""\b(?:src|href)\s*=\s*["']?\s*https?://""", html, re.I)
    assert not re.search(r"<script\b[^>]*\bsrc\s*=", html, re.I)
    assert not re.search(r"<link\b", html, re.I)
    # One script element per file: theme-init, the food data, the flag, then every module.
    _styles, head_scripts, body_scripts = _index_assets()
    assert len(re.findall(r"<script\b", html, re.I)) == len(head_scripts) + 2 + len(body_scripts)


def test_preview_inlines_stylesheets_and_scripts_in_document_order(fragment: str) -> None:
    styles, head_scripts, body_scripts = _index_assets()
    assert styles and styles[-1] == "css/touch.css", "touch.css must stay the last stylesheet"
    assert head_scripts == ["theme-init.js"]
    assert body_scripts[0] == "js/engine/rules.js" and body_scripts[-1] == "js/main.js"
    pos = -1
    for rel in [*styles, *head_scripts]:
        p = fragment.find(f"/* {rel} */") if rel.endswith(".css") else fragment.find((STATIC / rel).read_text(encoding="utf-8").strip()[:200])
        assert p > pos, f"{rel} missing or out of order"
        pos = p
    markup = fragment.find('<header class="topbar">')
    assert markup > pos, "the markup follows the stylesheets and the theme script"
    flag = fragment.find("window.KDL_PREVIEW = true")
    data = fragment.find('id="kdl-foods"')
    assert markup < data < flag, "the food data and the preview flag come before the modules run"
    pos = flag
    for rel in body_scripts:
        p = fragment.find(f"/* {rel} */")
        assert p > pos, f"{rel} missing or out of order"
        pos = p
    # Every inlined file is complete (modulo the </script escape, which none of them needs).
    for rel in [*head_scripts, *body_scripts]:
        assert (STATIC / rel).read_text(encoding="utf-8").strip() in fragment, f"{rel} not inlined verbatim"
    for rel in styles:
        assert (STATIC / rel).read_text(encoding="utf-8").strip() in fragment, f"{rel} not inlined verbatim"


def test_preview_is_not_an_installable_app(fragment: str) -> None:
    """Note 02 R3: the preview emits no manifest or icon tags and never registers a service worker."""
    for needle in ('rel="manifest"', "apple-touch-icon", "apple-mobile-web-app", 'rel="icon"', "/sw.js", "serviceWorker", "kh-sw"):
        assert needle not in fragment, f"{needle!r} in the preview"
    assert "/* js/pwa.js */" not in fragment and "KH.pwa = " not in fragment
    # The PWA panel and the update toast stay in the markup, hidden, with nothing to show them.
    assert re.search(r'id="install-panel"[^>]*\bhidden\b', fragment)
    assert re.search(r'id="update-toast"[^>]*\bhidden\b', fragment)


def test_preview_refuses_an_inline_script(tmp_path: Path) -> None:
    static = tmp_path / "static"
    shutil.copytree(STATIC, static)
    index = static / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("</body>", "<script>alert(1)</script>\n</body>"), encoding="utf-8")
    with pytest.raises(SystemExit, match="inline <script>"):
        _load_builder().build_fragment(static_dir=static)


def test_preview_default_output_is_inside_the_repo() -> None:
    builder = _load_builder()
    assert builder.DEFAULT_OUT == ROOT / "build" / "kidney-diet-log.html"
    assert "build/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


# --------------------------------------------------------------------------- the GitHub Pages demo (v0.3.1)


class _TagLister(HTMLParser):
    def __init__(self, tag: str) -> None:
        super().__init__()
        self.tag = tag
        self.found: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == self.tag:
            self.found.append(dict(attrs))


def _tags(html: str, tag: str) -> list[dict[str, str | None]]:
    lister = _TagLister(tag)
    lister.feed(html)
    lister.close()
    return lister.found


@pytest.fixture(scope="module")
def pages_demo(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("pages") / "demo"
    assert _load_builder().main(["--pages", str(out)]) == 0
    return out


def test_pages_demo_keeps_the_app_csp_and_runs_no_inline_script(pages_demo: Path) -> None:
    from app.security import CSP_DIRECTIVES

    html = (pages_demo / "index.html").read_text(encoding="utf-8")
    assert html.startswith('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">')
    policies = [m["content"] for m in _tags(html, "meta") if m.get("http-equiv") == "Content-Security-Policy"]
    # The app's policy, less frame-ancestors (ignored in a <meta> element); before anything it governs.
    assert policies == ["; ".join(d for d in CSP_DIRECTIVES if not d.startswith("frame-ancestors"))]
    assert "require-trusted-types-for 'script'" in policies[0] and "frame-ancestors" not in policies[0]
    assert html.index("Content-Security-Policy") < min(html.index("<link"), html.index("<script"))
    # Every script is a file, except the food data, which is JSON (a browser never runs it).
    assert [s for s in _tags(html, "script") if not s.get("src")] == [{"type": "application/json", "id": "kdl-foods"}]
    assert _load_builder().pages_csp() == policies[0]  # read from app/security.py without importing the server


def test_pages_demo_is_the_app_as_files_under_a_sub_path(pages_demo: Path) -> None:
    html = (pages_demo / "index.html").read_text(encoding="utf-8")
    styles, head_scripts, body_scripts = _index_assets()
    assert [s["src"] for s in _tags(html, "script") if s.get("src")] == [*head_scripts, "preview-flag.js", *body_scripts]
    assert [link["href"] for link in _tags(html, "link") if link.get("rel") == "stylesheet"] == styles
    for rel in [*styles, *head_scripts, *body_scripts, "icons/icon.svg"]:
        assert (pages_demo / rel).read_bytes() == (STATIC / rel).read_bytes(), rel
    # Not an installable app: no manifest, no service worker.
    assert not (pages_demo / "js" / "pwa.js").exists()
    for needle in ('rel="manifest"', "apple-touch-icon", "/sw.js"):
        assert needle not in html, needle
    m = re.search(r'<script type="application/json" id="kdl-foods">(.*?)</script>', html, re.S)
    assert m and json.loads(m.group(1)) == json.loads((ROOT / "data" / "foods.json").read_text(encoding="utf-8"))
    # Nothing absolute: the demo lives at /<repo>/demo/ and loads nothing from anywhere else.
    assert not re.search(r"""\b(?:src|href)\s*=\s*["']?\s*(?:/|https?:)""", html, re.I)
    assert re.search(r'<a id="learn-link"[^>]*href="\.\./"', html)  # the published handbook, one level up
    assert 'href="./?reauth=1"' in html


def test_pages_demo_links_into_the_published_handbook(pages_demo: Path) -> None:
    from app.handbook import LINKS

    flag = (pages_demo / "preview-flag.js").read_text(encoding="utf-8")
    assert "\nwindow.KDL_PREVIEW = true;\n" in flag
    m = re.search(r"^window\.KDL_DEMO_HANDBOOK = (\{.*\});$", flag, re.M)
    assert m and json.loads(m.group(1)) == {"url": "../", "links": LINKS}  # the server's own table
    mock = (STATIC / "js" / "mock" / "handbook.js").read_text(encoding="utf-8")
    assert "window.KDL_DEMO_HANDBOOK" in mock and "new URL(d.url, window.location.href).href" in mock
    # The fragment preview sets no handbook: there, the demo shows no Learn links.
    assert "window.KDL_DEMO_HANDBOOK = " not in _load_builder().build_fragment()


def test_pages_demo_refuses_an_absolute_path(tmp_path: Path) -> None:
    static = tmp_path / "static"
    shutil.copytree(STATIC, static)
    index = static / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("</main>", '<a href="/api/export">x</a>\n</main>'), encoding="utf-8")
    with pytest.raises(SystemExit, match="absolute paths"):
        _load_builder().build_pages(tmp_path / "out", static_dir=static)
