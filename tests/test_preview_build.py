"""scripts/build_preview.py: the self-contained preview fragment (no network, no skeleton tags)."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    # Exactly the four script elements: theme, data, flag, app.
    assert len(re.findall(r"<script\b", html, re.I)) == 4
    assert out.stat().st_size < 16 * 1024 * 1024


def test_preview_default_output_is_inside_the_repo() -> None:
    builder = _load_builder()
    assert builder.DEFAULT_OUT == ROOT / "build" / "kidney-diet-log.html"
    assert "build/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
