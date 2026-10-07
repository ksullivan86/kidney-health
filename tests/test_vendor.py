"""The vendored barcode decoder (note 03 R7, §6 item 12, §9 B9; app/static/vendor/README.md).

Offline checks: every file matches the SHA-256 pinned in scripts/vendor_barcode.py, the ponyfill expects
exactly this WASM (its own ZXING_WASM_SHA256 constant) and version, the generated README is current,
the licences are present, the page loads the ponyfill with a static deferred script (Trusted Types forbid
injected script tags) that the preview build leaves out, the service worker never pre-caches the 1 MB
WASM, the ponyfill contains no eval-like construct and no CDN fallback is reachable from the app.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "app" / "static"
VENDOR = STATIC / "vendor"


def _script():
    spec = importlib.util.spec_from_file_location("vendor_barcode", REPO / "scripts" / "vendor_barcode.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # its dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


VB = _script()


@pytest.mark.parametrize("vf", VB.all_files(), ids=lambda vf: vf.dest)
def test_vendored_file_matches_its_pin(vf):
    data = (VENDOR / vf.dest).read_bytes()
    assert len(data) == vf.size
    assert hashlib.sha256(data).hexdigest() == vf.sha256


def test_pins_are_the_ones_the_spec_recorded():
    # note 03 R7 / note 02 F7: the hashes measured when the decoder was chosen.
    assert VB.PONYFILL.sha256 == "e3aa2057178b8ea71dd97003270331bbcb46499197b68bc0c7dd18e40c0863ea"
    assert VB.WASM.sha256 == "2ebda08a93eea3efcd8399cda6b276e6a0b1de4fec60b4d8988a047de4c6d1ba"
    assert [(p.name, p.version) for p in VB.PACKAGES] == [("barcode-detector", "3.2.2"), ("zxing-wasm", "3.1.3")]


def test_ponyfill_expects_this_wasm_build():
    consts = VB.ponyfill_constants((VENDOR / VB.PONYFILL.dest).read_text(encoding="utf-8"))
    assert consts["ZXING_WASM_SHA256"] == hashlib.sha256((VENDOR / VB.WASM.dest).read_bytes()).hexdigest()
    assert consts["ZXING_WASM_VERSION"] == "3.1.3"
    assert consts["ZXING_CPP_COMMIT"] == VB.ZXING_CPP_COMMIT


def test_check_mode_passes_and_readme_is_generated():
    assert VB.main(["--check"]) == 0
    assert (VENDOR / "README.md").read_text(encoding="utf-8") == VB.readme()
    readme = VB.readme()
    for vf in VB.all_files():
        assert vf.sha256 in readme and vf.dest in readme


def test_check_mode_refuses_a_changed_file(tmp_path, monkeypatch):
    files = VB.read_vendored()
    files[VB.WASM.dest] = files[VB.WASM.dest][:-1] + b"\x00"
    with pytest.raises(SystemExit, match="zxing_reader.wasm"):
        VB.check_files(files)


def test_integrity_check_compares_the_npm_sha512():
    blob = b"tarball bytes"
    good = "sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode()
    VB.check_integrity(blob, good, "pkg")
    with pytest.raises(SystemExit, match="dist.integrity"):
        VB.check_integrity(blob + b"!", good, "pkg")
    with pytest.raises(SystemExit, match="integrity format"):
        VB.check_integrity(blob, "sha1-abc", "pkg")


def test_downloads_are_https_only():
    with pytest.raises(SystemExit, match="non-https"):
        VB._get("http://registry.npmjs.org/barcode-detector")


def test_licences_are_vendored():
    assert "MIT License" in (VENDOR / "barcode-detector-3.2.2" / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in (VENDOR / "zxing-wasm-3.1.3" / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in (VENDOR / "zxing-wasm-3.1.3" / "LICENSE.zxing-cpp").read_text(encoding="utf-8")


def test_ponyfill_has_no_eval_workers_or_script_injection():
    text = (VENDOR / VB.PONYFILL.dest).read_text(encoding="utf-8")
    for bad in ("eval(", "new Function", "importScripts", "new Worker", "createElement(`script`", 'createElement("script"', "innerHTML"):
        assert bad not in text, bad


def test_index_loads_the_ponyfill_statically_and_the_preview_omits_it():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    tags = re.findall(r"<script\b[^>]*vendor/barcode-detector-3\.2\.2/ponyfill\.iife\.js[^>]*>", index)
    assert len(tags) == 1, "index.html must load the ponyfill exactly once with a static <script>"
    assert " defer" in tags[0] and 'data-preview="omit"' in tags[0]
    # js/scan.js points the ponyfill at the vendored WASM, never at its CDN default.
    scan = (STATIC / "js" / "scan.js").read_text(encoding="utf-8")
    assert "/vendor/zxing-wasm-3.1.3/" in scan
    assert "jsdelivr" not in scan


def test_service_worker_does_not_precache_the_wasm():
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"const SHELL_URLS = \[(.*?)\];", sw, re.S)
    assert shell
    assert ".wasm" not in shell.group(1)
    assert "'/vendor/barcode-detector-3.2.2/ponyfill.iife.js'" in shell.group(1)
