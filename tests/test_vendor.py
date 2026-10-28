"""The vendored files: the barcode decoder (note 03 R7, §6 item 12, §9 B9) and the PDF reader (note 13 §4.1); app/static/vendor/README.md.

Offline checks: every file matches the SHA-256 pinned in scripts/vendor_barcode.py, the ponyfill expects
exactly this WASM (its own ZXING_WASM_SHA256 constant) and version, the generated README is current,
the licences are present, the page loads the ponyfill with a static deferred script (Trusted Types forbid
injected script tags) that the preview build leaves out, the service worker never pre-caches the 1 MB
WASM, the ponyfill contains no eval-like construct and no CDN fallback is reachable from the app.
PDF reader: the three pdf.js files are the pinned legacy build of 6.4.299 (main file and worker name the same
version), neither has an eval, a source map or a URL it fetches, the library still takes every option
js/engine/pdf_pages.js passes (and no longer has isEvalSupported), nothing loads them with a script tag or the
service worker's shell list, and the script's `--only pdfjs` fetch downloads nothing else (run against a fake registry).
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import re
import sys
import tarfile
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
    assert [(p.name, p.version) for p in VB.PACKAGES] == [("barcode-detector", "3.2.2"), ("zxing-wasm", "3.1.3"), ("pdfjs-dist", "6.4.299"),
                                                          ("qrcode-generator", "2.0.4")]
    assert [(p.name, p.group) for p in VB.PACKAGES] == [("barcode-detector", "barcode"), ("zxing-wasm", "barcode"), ("pdfjs-dist", "pdfjs"),
                                                        ("qrcode-generator", "qrcode")]


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


# --------------------------------------------------------------------------- the PDF reader (note 13 §4.1)
PDFJS_DIR = VENDOR / "pdfjs-dist-6.4.299"
PDFJS_MAIN = (PDFJS_DIR / "pdf.min.mjs").read_text(encoding="utf-8")
PDFJS_WORKER = (PDFJS_DIR / "pdf.worker.min.mjs").read_text(encoding="utf-8")


def test_the_pdf_reader_pins_are_the_ones_recorded_when_it_was_vendored():
    # sha256 of legacy/build/pdf.min.mjs, legacy/build/pdf.worker.min.mjs and LICENSE of pdfjs-dist 6.4.299 (npm tarball
    # sha512-AVl138zALtfaAPvADulE0PZThbYzCBS79nL4pOSL/6Sm/4AH5A21BD9VHt97OlCuzJuCpmeZtAtkinisF4Vb1g==, published 2026-10-03).
    assert {f.dest: f.sha256 for f in VB.PDFJS_PACKAGES[0].files} == {
        "pdfjs-dist-6.4.299/pdf.min.mjs": "bccc24ea711db8e44503629519904a5292d73b9daaa214bbe7cdcc282b0f4259",
        "pdfjs-dist-6.4.299/pdf.worker.min.mjs": "145d2dd3ab0c86151011dba95acfa2d5336e2accd59388ea43dbee0efddaaec6",
        "pdfjs-dist-6.4.299/LICENSE": "0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594",
    }
    # the legacy build, not the default one (README "Which build"): the member paths say so
    assert [f.member for f in VB.PDFJS_PACKAGES[0].files] == [
        "package/legacy/build/pdf.min.mjs", "package/legacy/build/pdf.worker.min.mjs", "package/LICENSE"]
    assert VB.PDFJS_VERSION == "6.4.299" and VB.PDFJS_PACKAGES[0].licence == "Apache-2.0"


def test_the_readme_has_the_pdf_section_with_the_build_evidence():
    readme = (VENDOR / "README.md").read_text(encoding="utf-8")
    assert readme == VB.readme()
    section = readme[readme.index("## PDF reader (note 13)"):readme.index("## Updating")]
    for vf in VB.PDFJS_PACKAGES[0].files:
        assert vf.sha256 in section and vf.dest in section
    assert "legacy/build" in section and "Safari 18+" in section and "intended for *the latest* browsers" in section
    assert "Promise.withResolvers" in section and "Promise.try" in section  # why the default build is not used
    assert "isEvalSupported" in section and "kh-pdf" in section
    assert "--only pdfjs" in readme


def test_the_main_file_and_the_worker_name_the_same_version_and_a_mismatch_is_refused():
    assert '"6.4.299"' in PDFJS_MAIN and '"6.4.299"' in PDFJS_WORKER
    files = VB.read_vendored()
    other = dict(files)
    other[VB.PDFJS_WORKER.dest] = files[VB.PDFJS_WORKER.dest].replace(b'"6.4.299"', b'"6.4.300"')
    with pytest.raises(SystemExit, match="pdf.worker.min.mjs"):
        VB.check_files(other, groups=("pdfjs",))  # (the hash pin catches it first; the version check is the second line of defence)
    changed = dict(files)
    changed[VB.PDFJS_MAIN.dest] = files[VB.PDFJS_MAIN.dest] + b"\n"
    with pytest.raises(SystemExit, match="pdf.min.mjs"):
        VB.check_files(changed)


def test_the_licence_is_apache_2():
    text = (PDFJS_DIR / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text and "Version 2.0" in text


def test_pdfjs_has_no_eval_no_source_map_and_no_url_it_fetches():
    for name, text in (("pdf.min.mjs", PDFJS_MAIN), ("pdf.worker.min.mjs", PDFJS_WORKER)):
        assert not re.search(r"\beval\s*\(|new\s+Function\s*\(", text), name
        assert "sourceMappingURL" not in text, name
        # core-js's last-resort way to find the global object, never reached where globalThis exists (and refused by the CSP anyway)
        calls = re.findall(r"(?<![\w$.])Function\s*\(([^)]*)\)", text)
        assert calls == ['"return this"'], (name, calls)
        assert not re.search(r"importScripts|new\s+SharedWorker|navigator\.sendBeacon|new\s+WebSocket|new\s+EventSource", text), name
        hosts = set(re.findall(r"https?://([A-Za-z0-9.-]*)", text))
        # licence notices, XML namespaces, the library's own test strings: written down, fetched by nothing
        assert hosts <= {"", "a", "x", "foo.bar", "example.com", "github.com", "www.apache.org", "www.w3.org", "www.xfa.org", "ns.adobe.com"}, (name, hosts)


def test_the_library_still_takes_every_option_the_page_passes_and_no_longer_has_the_eval_switch():
    """note 13 D3 against the 6.4.299 source: these are the options of getDocument/GlobalWorkerOptions/render that js/engine/pdf_pages.js uses."""
    for option in ("data", "enableXfa", "disableAutoFetch", "disableStream", "disableRange", "stopAtErrors", "workerPort"):
        assert re.search(rf"[.\"']{option}\b", PDFJS_MAIN), option
    for option in ("canvas", "viewport", "background", "annotationMode"):
        assert re.search(rf"\b{option}\b", PDFJS_MAIN), option
    assert "AnnotationMode" in PDFJS_MAIN and "PasswordException" in PDFJS_MAIN and "getViewport" in PDFJS_MAIN
    # 6.4 removed the eval code path with its switch. If an update brings isEvalSupported back, pass `isEvalSupported: false`
    # (js/engine/pdf_pages.js already does, harmlessly) and say so in vendor/README.md.
    assert "isEvalSupported" not in PDFJS_MAIN and "isEvalSupported" not in PDFJS_WORKER


def test_pdfjs_is_loaded_by_import_and_a_module_worker_never_by_a_script_tag_or_the_shell_list():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "pdfjs-dist" not in index
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"const SHELL_URLS = \[(.*?)\];", sw, re.S)
    assert shell and "pdfjs-dist" not in shell.group(1)  # about 1.8 MB: fetched on the first PDF, kept by the /vendor/ cache
    assert "'/js/engine/pdf_pages.js'," in shell.group(1)
    # the existing runtime rule for /vendor/ (cache-first, kept per release) covers it; no second rule was added
    assert sw.count("url.pathname.startsWith('/vendor/')") == 1
    assert "const VENDOR = `kdl-vendor-${VERSION}`;" in sw


def _fake_registry(monkeypatch, tarball: bytes, *, tarball_url: str | None = None, integrity: str | None = None):
    """Stand in for the network: records every URL asked for, answers the registry's version document and the tarball."""
    asked: list[str] = []
    url = tarball_url or "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz"
    good = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode()

    def fake_get(address: str, limit: int = 0) -> bytes:
        asked.append(address)
        if address == "https://registry.npmjs.org/pdfjs-dist/6.4.299":
            return json.dumps({"dist": {"tarball": url, "integrity": integrity or good}}).encode()
        if address == url:
            return tarball
        raise AssertionError(f"unexpected download: {address}")

    monkeypatch.setattr(VB, "_get", fake_get)
    return asked


def _pdfjs_tarball(*, replace: dict[str, bytes] | None = None) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        members = {f.member: (PDFJS_DIR / f.dest.split("/", 1)[1]).read_bytes() for f in VB.PDFJS_PACKAGES[0].files}
        members.update(replace or {})
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_only_pdfjs_downloads_the_one_package_and_nothing_else(monkeypatch):
    asked = _fake_registry(monkeypatch, _pdfjs_tarball())
    files = VB.fetch(groups=("pdfjs",))
    assert sorted(files) == sorted(f.dest for f in VB.PDFJS_PACKAGES[0].files)
    assert asked == ["https://registry.npmjs.org/pdfjs-dist/6.4.299", "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz"]
    assert VB.packages_of(("pdfjs",)) == VB.PDFJS_PACKAGES and VB.all_files(("pdfjs",)) == VB.PDFJS_PACKAGES[0].files
    assert VB.ZXING_CPP_LICENCE not in VB.all_files(("pdfjs",)) and VB.ZXING_CPP_LICENCE in VB.all_files()


def test_a_tarball_that_does_not_match_the_registry_is_refused_before_a_file_is_read(monkeypatch):
    _fake_registry(monkeypatch, _pdfjs_tarball(), integrity="sha512-" + base64.b64encode(b"x" * 64).decode())
    with pytest.raises(SystemExit, match="dist.integrity"):
        VB.fetch(groups=("pdfjs",))


def test_a_registry_that_points_at_another_tarball_address_is_refused(monkeypatch):
    _fake_registry(monkeypatch, _pdfjs_tarball(), tarball_url="https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.300.tgz")
    with pytest.raises(SystemExit, match="expected https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.4.299.tgz"):
        VB.fetch(groups=("pdfjs",))


def test_a_tarball_with_a_changed_file_fails_its_pin_and_nothing_is_written(monkeypatch, tmp_path):
    _fake_registry(monkeypatch, _pdfjs_tarball(replace={"package/legacy/build/pdf.min.mjs": b"export {};"}))
    monkeypatch.setattr(VB, "VENDOR", tmp_path)
    with pytest.raises(SystemExit, match="pdf.min.mjs"):
        VB.fetch(groups=("pdfjs",))
    assert list(tmp_path.iterdir()) == []


def test_the_download_cap_fits_the_pdfjs_tarball_and_stays_small_for_the_others():
    assert VB.PDFJS_PACKAGES[0].max_download >= 8_539_589 * 2  # the 6.4.299 tarball is 8,539,589 bytes
    assert all(p.max_download == VB.MAX_DOWNLOAD for p in VB.BARCODE_PACKAGES)


def test_check_mode_can_be_limited_to_one_group():
    assert VB.main(["--check", "--only", "pdfjs"]) == 0
    assert VB.main(["--check", "--only", "barcode"]) == 0
    assert VB.main(["--check", "--only", "qrcode"]) == 0


def test_the_qr_code_module_draws_nothing_itself_and_fetches_nothing():
    """note 17 §7: the QR code of the secret is drawn in the page; the module must not touch the DOM, eval or fetch."""
    text = (VENDOR / VB.QRCODE_PACKAGES[0].files[0].dest).read_text(encoding="utf-8")
    assert "export default qrcode;" in text
    for bad in (r"\beval\(", r"\bFunction\(", r"\bdocument\.", r"\bwindow\.", r"\bfetch\(", "XMLHttpRequest", r"\bimport\(", "importScripts"):
        assert not re.search(bad, text), bad
    urls = set(re.findall(r"https?://[^\s'\"]+", text))
    assert urls <= {"http://www.d-project.com/", "http://www.denso-wave.com/qrcode/faqpatent-e.html",
                    "http://www.opensource.org/licenses/mit-license.php", "http://www.w3.org/2000/svg"}
    licence = (VENDOR / VB.QRCODE_LICENCE.dest).read_text(encoding="utf-8")
    assert licence.startswith("MIT License") and "Kazuhiko Arase" in licence
    assert VB.QRCODE_LICENCE in VB.all_files(("qrcode",)) and VB.QRCODE_LICENCE not in VB.all_files(("pdfjs",))
