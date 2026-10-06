"""scripts/build_preview.py: the self-contained preview fragment (no network, no skeleton tags)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
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


def _index_assets() -> tuple[list[str], list[str], list[str]]:
    """(stylesheets, head scripts, body scripts kept for the preview) as index.html lists them."""
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    head, body = index.split("</head>", 1)
    styles = re.findall(r'<link rel="stylesheet" href="([^"]+)">', head)
    head_scripts = re.findall(r'<script src="([^"]+)"[^>]*>\s*</script\b[^>]*>', head, re.I)
    body_scripts = [src for src, extra in re.findall(r'<script src="([^"]+)"([^>]*)>\s*</script\b[^>]*>', body, re.I) if 'data-preview="omit"' not in extra]
    return styles, head_scripts, body_scripts


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
