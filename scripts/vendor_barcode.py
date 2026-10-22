#!/usr/bin/env python3
"""Vendor the third-party browser code the app serves itself: the barcode decoder (note 03 R7, note 02 R7) and the PDF reader (note 13).

The app loads nothing from a CDN, so what the browser needs is copied into ``app/static/vendor/`` from pinned npm
packages. Two groups:

* ``barcode``: the decoder the browser falls back to. The app decodes barcodes on the phone. Browsers with a native
  ``BarcodeDetector`` (Chrome on Android, macOS and ChromeOS) need nothing; every other browser, iPhones included, uses the
  ``barcode-detector`` ponyfill over ZXing-C++ compiled to WebAssembly (note 03 R7, §6 item 12, §9 B9).
* ``pdfjs``: ``pdfjs-dist``, Mozilla's PDF reader, which draws the pages of a lab report PDF on the device before they are read
  like photos (note 13 §4.1). Only the ``legacy/build`` main file, its worker and the licence are taken.

What this script does (standard library only; dev time, never at runtime):

1. Asks the npm registry for each pinned package version and downloads its tarball.
2. Checks the tarball against the registry's ``dist.integrity`` (SHA-512) **before** reading it (§9 B9).
3. Takes only the listed files out of the tarball (read in memory, never extracted to disk, nothing in it is run), and checks
   each against the SHA-256 pinned below. Barcode group: the ponyfill's own ``ZXING_WASM_SHA256`` constant must equal the WASM's
   hash, and its ``ZXING_CPP_COMMIT`` names the ZXing-C++ commit whose Apache-2.0 licence is fetched from
   raw.githubusercontent.com and checked against its pin too. PDF group: the main file and the worker must name the same
   pdf.js version (the library refuses a worker of another version).
4. Writes the files under ``app/static/vendor/`` and regenerates ``app/static/vendor/README.md``.

Usage::

    python3 scripts/vendor_barcode.py                # download, verify, write, both groups (needs the network)
    python3 scripts/vendor_barcode.py --only pdfjs   # the same for one group only (barcode | pdfjs); downloads nothing else
    python3 scripts/vendor_barcode.py --check        # verify the committed files against the pins (offline)
    python3 scripts/vendor_barcode.py --check-latest # warn when npm has newer versions (exit 0; CI, weekly)
    python3 scripts/vendor_barcode.py --print-hashes # download and verify integrity, print SHA-256 (updating)

Updating: read the new versions' changelogs, change ``PACKAGES`` (version, and for the barcode group keep the ponyfill's
``zxing-wasm`` dependency and the WASM version equal: the 3.1.4 WASM does not fit the 3.1.3 glue), run ``--print-hashes``
(with ``--only`` for one group), review, paste the new hashes, run without ``--print-hashes``, then run the browser checks
(``tools/e2e/device.py`` for photo decoding through the WASM path, ``tools/e2e/lab_pdf.py`` for a PDF lab report) before
committing. A new package release must be at least 7 days old (the project's cooldown) unless it fixes a security advisory.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "app" / "static" / "vendor"
REGISTRY = "https://registry.npmjs.org"
ZXING_CPP_RAW = "https://raw.githubusercontent.com/zxing-cpp/zxing-cpp/{commit}/LICENSE"
TIMEOUT_S = 60
MAX_DOWNLOAD = 8 * 1024 * 1024  # the barcode tarballs are about 1.7 MB at most
GROUPS = ("barcode", "pdfjs")


@dataclass(frozen=True)
class VendoredFile:
    member: str  # path inside the npm tarball
    dest: str  # path under app/static/vendor/
    sha256: str
    size: int
    what: str


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    licence: str
    homepage: str
    files: tuple[VendoredFile, ...]
    group: str = "barcode"
    max_download: int = MAX_DOWNLOAD


BARCODE_PACKAGES: tuple[Package, ...] = (
    Package(
        name="barcode-detector",
        version="3.2.2",
        licence="MIT",
        homepage="https://github.com/Sec-ant/barcode-detector",
        files=(
            VendoredFile("package/dist/iife/ponyfill.js", "barcode-detector-3.2.2/ponyfill.iife.js",
                         "e3aa2057178b8ea71dd97003270331bbcb46499197b68bc0c7dd18e40c0863ea", 43933,
                         "the ponyfill (window.BarcodeDetectionAPI), loaded by a static <script defer> in index.html"),
            VendoredFile("package/LICENSE", "barcode-detector-3.2.2/LICENSE",
                         "fb506e4ade12d7a9efa67c9d76a9a28c8e15d347ca49a69e48e29b40b34ad2ab", 1068, "MIT licence"),
        ),
    ),
    Package(
        name="zxing-wasm",
        version="3.1.3",
        licence="MIT (wraps ZXing-C++, Apache-2.0)",
        homepage="https://github.com/Sec-ant/zxing-wasm",
        files=(
            VendoredFile("package/dist/reader/zxing_reader.wasm", "zxing-wasm-3.1.3/zxing_reader.wasm",
                         "2ebda08a93eea3efcd8399cda6b276e6a0b1de4fec60b4d8988a047de4c6d1ba", 1093289,
                         "the ZXing-C++ reader, fetched by the ponyfill on the first scan without a native detector"),
            VendoredFile("package/LICENSE", "zxing-wasm-3.1.3/LICENSE",
                         "fb506e4ade12d7a9efa67c9d76a9a28c8e15d347ca49a69e48e29b40b34ad2ab", 1068, "MIT licence"),
        ),
    ),
)
# The PDF reader (note 13 §4.1). The tarball is 8.5 MB (the whole library with maps, CMaps and fonts); three files are taken.
PDFJS_VERSION = "6.4.299"
PDFJS_DIR = f"pdfjs-dist-{PDFJS_VERSION}"
PDFJS_PACKAGES: tuple[Package, ...] = (
    Package(
        name="pdfjs-dist",
        version=PDFJS_VERSION,
        licence="Apache-2.0",
        homepage="https://github.com/mozilla/pdf.js",
        group="pdfjs",
        max_download=24 * 1024 * 1024,
        files=(
            VendoredFile("package/legacy/build/pdf.min.mjs", f"{PDFJS_DIR}/pdf.min.mjs",
                         "bccc24ea711db8e44503629519904a5292d73b9daaa214bbe7cdcc282b0f4259", 523774,
                         "the library (ES module, legacy build), loaded by js/engine/pdf_pages.js with a dynamic import() on the first PDF"),
            VendoredFile("package/legacy/build/pdf.worker.min.mjs", f"{PDFJS_DIR}/pdf.worker.min.mjs",
                         "145d2dd3ab0c86151011dba95acfa2d5336e2accd59388ea43dbee0efddaaec6", 1321307,
                         "the parser and decoders; started as a module Worker by js/engine/pdf_pages.js under the Trusted Types policy kh-pdf"),
            VendoredFile("package/LICENSE", f"{PDFJS_DIR}/LICENSE",
                         "0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594", 10174, "Apache License 2.0"),
        ),
    ),
)
PACKAGES: tuple[Package, ...] = BARCODE_PACKAGES + PDFJS_PACKAGES
PDFJS_MAIN, PDFJS_WORKER = PDFJS_PACKAGES[0].files[0], PDFJS_PACKAGES[0].files[1]
ZXING_CPP_COMMIT = "a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f"
ZXING_CPP_LICENCE = VendoredFile("LICENSE", "zxing-wasm-3.1.3/LICENSE.zxing-cpp",
                                 "c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08", 11358,
                                 "ZXing-C++ Apache License 2.0, at the commit the WASM was built from")
PONYFILL = BARCODE_PACKAGES[0].files[0]
WASM = BARCODE_PACKAGES[1].files[0]
# The constants the ponyfill exports (minified as `name=\`value\``).
_CONST = re.compile(r"\b(\w{1,3})=`([0-9a-f.]{5,64})`")


class VendorError(SystemExit):
    """A failed check: the message says what differs; nothing is written."""


def _get(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    if not url.startswith("https://"):
        raise VendorError(f"refusing a non-https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "kidney-health vendor_barcode.py", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:  # noqa: S310 - https only, checked above
        data = res.read(limit + 1)
    if len(data) > limit:
        raise VendorError(f"{url}: larger than {limit} bytes")
    return data


def registry_meta(name: str, version: str | None = None) -> dict:
    path = f"{REGISTRY}/{name}" + (f"/{version}" if version else "")
    return json.loads(_get(path))


def check_integrity(blob: bytes, integrity: str, what: str) -> None:
    """Compare a download with an npm ``dist.integrity`` string (``sha512-<base64>``)."""
    algo, _, expected = integrity.partition("-")
    if algo != "sha512" or not expected:
        raise VendorError(f"{what}: unexpected integrity format {integrity!r} (expected sha512-…)")
    got = base64.b64encode(hashlib.sha512(blob).digest()).decode()
    if got != expected:
        raise VendorError(f"{what}: the tarball does not match the registry's dist.integrity (got sha512-{got})")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ponyfill_constants(text: str) -> dict[str, str]:
    """``ZXING_WASM_SHA256``, ``ZXING_CPP_COMMIT`` and ``ZXING_WASM_VERSION`` as the ponyfill exports them."""
    values = dict(_CONST.findall(text))
    out: dict[str, str] = {}
    for export in ("ZXING_WASM_SHA256", "ZXING_CPP_COMMIT", "ZXING_WASM_VERSION"):
        m = re.search(rf"\.{export}=(\w+)\b", text)
        if m and m.group(1) in values:
            out[export] = values[m.group(1)]
    return out


def packages_of(groups: tuple[str, ...]) -> tuple[Package, ...]:
    return tuple(pkg for pkg in PACKAGES if pkg.group in groups)


def fetch(print_only: bool = False, groups: tuple[str, ...] = GROUPS) -> dict[str, bytes]:
    """Download the packages of ``groups``, verify integrity and pins, return {dest: bytes}."""
    files: dict[str, bytes] = {}
    computed: list[tuple[str, str, int]] = []
    for pkg in packages_of(groups):
        meta = registry_meta(pkg.name, pkg.version)
        dist = meta.get("dist") or {}
        tarball_url = str(dist.get("tarball", ""))
        expected_url = f"{REGISTRY}/{pkg.name}/-/{pkg.name}-{pkg.version}.tgz"
        if tarball_url != expected_url:
            raise VendorError(f"{pkg.name}@{pkg.version}: the registry names the tarball {tarball_url!r}, expected {expected_url}")
        tarball = _get(tarball_url, pkg.max_download)
        check_integrity(tarball, str(dist.get("integrity", "")), f"{pkg.name}@{pkg.version}")
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            for vf in pkg.files:
                member = tar.getmember(vf.member)
                if not member.isfile():
                    raise VendorError(f"{pkg.name}: {vf.member} is not a regular file")
                handle = tar.extractfile(member)
                assert handle is not None
                data = handle.read()
                computed.append((vf.dest, sha256(data), len(data)))
                files[vf.dest] = data
    consts: dict[str, str] | None = None
    commit = ""
    if "barcode" in groups:
        consts = ponyfill_constants(files[PONYFILL.dest].decode("utf-8"))
        commit = consts.get("ZXING_CPP_COMMIT", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise VendorError("the ponyfill does not export ZXING_CPP_COMMIT")
        licence = _get(ZXING_CPP_RAW.format(commit=commit))
        computed.append((ZXING_CPP_LICENCE.dest, sha256(licence), len(licence)))
        files[ZXING_CPP_LICENCE.dest] = licence
    if print_only:
        if commit:
            print(f"ZXING_CPP_COMMIT = {commit!r}")
        for dest, digest, size in computed:
            print(f"{dest}: sha256 {digest}  {size} bytes")
        return files
    check_files(files, consts, groups)
    if "barcode" in groups and commit != ZXING_CPP_COMMIT:
        raise VendorError(f"the ponyfill names ZXing-C++ {commit}, the pin is {ZXING_CPP_COMMIT}")
    return files


def all_files(groups: tuple[str, ...] = GROUPS) -> tuple[VendoredFile, ...]:
    out = tuple(f for pkg in packages_of(groups) for f in pkg.files)
    return out + ((ZXING_CPP_LICENCE,) if "barcode" in groups else ())


def check_files(files: dict[str, bytes], consts: dict[str, str] | None = None, groups: tuple[str, ...] = GROUPS) -> None:
    """Every vendored file has its pinned hash and size; the ponyfill names this WASM and version; pdf.js and its worker are one version."""
    for vf in all_files(groups):
        data = files.get(vf.dest)
        if data is None:
            raise VendorError(f"missing app/static/vendor/{vf.dest}")
        if sha256(data) != vf.sha256 or len(data) != vf.size:
            raise VendorError(f"app/static/vendor/{vf.dest}: sha256 {sha256(data)} ({len(data)} bytes), "
                              f"pinned {vf.sha256} ({vf.size} bytes)")
    if "barcode" in groups:
        consts = consts if consts is not None else ponyfill_constants(files[PONYFILL.dest].decode("utf-8"))
        if consts.get("ZXING_WASM_SHA256") != WASM.sha256:
            raise VendorError(f"the ponyfill expects WASM {consts.get('ZXING_WASM_SHA256')}, the vendored one is {WASM.sha256}")
        wasm_pkg = BARCODE_PACKAGES[1]
        if consts.get("ZXING_WASM_VERSION") != wasm_pkg.version:
            raise VendorError(f"the ponyfill was built for zxing-wasm {consts.get('ZXING_WASM_VERSION')}, vendored {wasm_pkg.version}")
    if "pdfjs" in groups:
        # The library refuses a worker of another version ("The API version ... does not match the Worker version").
        quoted = f'"{PDFJS_VERSION}"'.encode()
        for vf in (PDFJS_MAIN, PDFJS_WORKER):
            if quoted not in files[vf.dest]:
                raise VendorError(f"app/static/vendor/{vf.dest} does not name pdf.js {PDFJS_VERSION}")


def _files_table(rows: list[str]) -> list[str]:
    return ["| File | From | Bytes | SHA-256 |", "|---|---|---|---|", *rows]


def _file_rows(packages: tuple[Package, ...]) -> list[str]:
    return [f"| `{vf.dest}` | {pkg.name} {pkg.version} `{vf.member.removeprefix('package/')}` | {vf.size:,} | `{vf.sha256}` |"
            for pkg in packages for vf in pkg.files]


def _package_row(p: Package) -> str:
    return (f"| `{p.name}` | {p.version} | {p.licence} | [{p.homepage.removeprefix('https://')}]({p.homepage}), "
            f"npm `{REGISTRY}/{p.name}/-/{p.name}-{p.version}.tgz` |")


def readme() -> str:
    """app/static/vendor/README.md (generated: the test compares it with this function)."""
    vf = ZXING_CPP_LICENCE
    barcode_rows = _file_rows(BARCODE_PACKAGES) + [
        f"| `{vf.dest}` | ZXing-C++ `LICENSE` at `{ZXING_CPP_COMMIT[:12]}` | {vf.size:,} | `{vf.sha256}` |"]
    lines = [
        "# Vendored files",
        "",
        "The app loads nothing from a CDN (ARCHITECTURE.md \"Stack\"). Third-party code the browser needs is",
        "copied here, pinned by SHA-256 and served by the app itself. **Generated by",
        "`scripts/vendor_barcode.py`; do not edit by hand.** `tests/test_vendor.py` checks every file against this",
        "table and the pins in the script.",
        "",
        "## Barcode decoder (note 03 R7, note 02 R7)",
        "",
        "Used only when the browser has no native `BarcodeDetector` that reads EAN-13 (every iPhone and iPad,",
        "Firefox, desktop Chrome on Windows and Linux). `js/scan.js` picks the decoder; the ponyfill is a static",
        "`<script defer>` in `index.html` (Trusted Types forbid injecting script tags), and its WebAssembly reader",
        "is fetched from `/vendor/zxing-wasm-3.1.3/` on the first scan that needs it (the service worker then keeps",
        "it). The page's CSP allows WebAssembly with `'wasm-unsafe-eval'`; the ponyfill has no `eval`, no",
        "`new Function`, no workers and injects no scripts.",
        "",
        *_files_table(barcode_rows),
        "",
        "| Package | Version | Licence | Source |",
        "|---|---|---|---|",
        *(_package_row(p) for p in BARCODE_PACKAGES),
        f"| ZXing-C++ | `{ZXING_CPP_COMMIT}` | Apache-2.0 | [github.com/zxing-cpp/zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) |",
        "",
        "Checks made when the files were vendored: each npm tarball matched the registry's `dist.integrity`",
        "(SHA-512) before it was read; the ponyfill's own `ZXING_WASM_SHA256` constant equals the WASM's hash and",
        "its `ZXING_WASM_VERSION` the vendored `zxing-wasm` version (the 3.1.4 WASM does not fit the 3.1.3 glue);",
        "its `ZXING_CPP_COMMIT` names the ZXing-C++ commit whose licence is copied here.",
        "",
        "## PDF reader (note 13)",
        "",
        "Used only when a person picks a PDF in Labs → Read a lab report. `js/engine/pdf_pages.js` (`KH.pdfPages`)",
        f"loads `{PDFJS_DIR}/pdf.min.mjs` with a dynamic `import()` on the first PDF and starts",
        "`pdf.worker.min.mjs` as a module Worker itself, under the Trusted Types policy `kh-pdf`, which passes exactly",
        "that one URL; pdf.js never makes a worker of its own, so it has no fake worker on the main thread to fall back to.",
        "Neither file is in the service worker's shell list (about 1.8 MB together): the first PDF fetches them and",
        "the `/vendor/` runtime cache keeps them. The document is opened from bytes only (no URL, no `cMapUrl`,",
        "`standardFontDataUrl`, `iccUrl` or `wasmUrl`), with XFA, scripting, annotations and automatic fetching off, so",
        "the library requests nothing; no WebAssembly decoder is vendored, so JPEG 2000 and JBIG2 images and ICC",
        "profiles are not decoded. Only the three files below are taken from the tarball; the CMaps, standard fonts,",
        "viewer, sandbox, image decoders and source maps are not.",
        "",
        *_files_table(_file_rows(PDFJS_PACKAGES)),
        "",
        "| Package | Version | Licence | Source |",
        "|---|---|---|---|",
        *(_package_row(p) for p in PDFJS_PACKAGES),
        "",
        "Which build: `legacy/build` (read 2026-10-22). pdf.js's own statement (its wiki, \"Frequently Asked Questions\",",
        "\"Which browsers/environments are supported?\"): the default build is a non-translated, non-polyfilled build",
        "\"intended for *the latest* browsers\" and lists only Firefox and Chrome; the `legacy` build, for older",
        "browsers, lists Firefox ESR+, Chrome 125+, Safari 18+ (\"mostly\") and Node.js 22+. The app supports Safari 16.4",
        "and later (note 02). In the 6.4.299 sources the default build calls `Promise.try` (Safari 18.2),",
        "`Math.sumPrecise`, `Uint8Array.fromBase64` and the `Map` `getOrInsert` methods with no polyfill, and the legacy",
        "build bundles core-js for exactly those; so by note 13 §4.1 (\"if the modern build needs more ... take",
        "`legacy/build/`\") it is the legacy build. It still calls `Promise.withResolvers` natively (Safari 17.4), so",
        "`KH.pdfPages.supported()` asks for it and an older browser is sent to screenshots; below Safari 18 the",
        "library's own statement makes no promise.",
        "",
        "Checks made when the files were vendored: the npm tarball matched the registry's `dist.integrity` (SHA-512)",
        "before it was read and nothing in it was run; the main file and the worker both name `6.4.299` (the library",
        "refuses a worker of another version); neither file has an `eval` or a source-map comment, the only `Function(`",
        "call in each is core-js's last-resort `Function(\"return this\")` for finding the global object (never reached",
        "where `globalThis` exists, and the page's CSP has no `'unsafe-eval'` anyway), and the only URLs in them are",
        "licence, XML-namespace and test strings that nothing fetches; in the 6.4.299 source `getDocument` still takes",
        "`data`, `enableXfa`, `disableAutoFetch`, `disableStream`, `disableRange` and `stopAtErrors`,",
        "`GlobalWorkerOptions.workerPort` exists, `isEvalSupported` no longer exists (the eval code path was removed),",
        "and `render()` takes `canvas`, `viewport`, `background` and `annotationMode`.",
        "",
        "## Updating",
        "",
        "1. `python3 scripts/vendor_barcode.py --check-latest` (CI runs it weekly, warn only) says when npm has",
        "   newer versions. Read their changelogs. A new release must be at least 7 days old (the project's",
        "   cooldown) unless it fixes a security advisory (a pdf.js advisory is such a reason: write why in the PR).",
        "2. Change the versions in `PACKAGES` in `scripts/vendor_barcode.py`, run it with `--print-hashes` (and",
        "   `--only barcode` or `--only pdfjs`), review the new hashes and paste them over the old pins (also the",
        "   paths in `js/scan.js`, `index.html`, `sw.js` and `tests/test_vendor.py` for the barcode decoder, and",
        "   `PDFJS_URL` / `WORKER_URL` in `js/engine/pdf_pages.js` and the tests that name them for the PDF reader,",
        "   which name the versioned folders). Re-read the options of `getDocument` in the new source:",
        "   `js/engine/pdf_pages.js` lists every one it passes.",
        "3. Run `python3 scripts/vendor_barcode.py` (`--only pdfjs` for one group), then `python -m pytest tests/test_vendor.py",
        "   tests/test_pdf_pages.py tests/test_lab_photo_ui.py` and the browser checks: the photo decoding check of",
        "   `tools/e2e/device.py` (it decodes a generated EAN-13 through the WASM path) and `tools/e2e/lab_pdf.py` (a",
        "   two-page PDF read through the lab report route).",
        "",
    ]
    return "\n".join(lines)


def read_vendored(groups: tuple[str, ...] = GROUPS) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for vf in all_files(groups):
        path = VENDOR / vf.dest
        if path.is_file():
            out[vf.dest] = path.read_bytes()
    return out


def write(files: dict[str, bytes]) -> None:
    for dest, data in files.items():
        path = VENDOR / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (VENDOR / "README.md").write_text(readme(), encoding="utf-8")


def check_latest() -> int:
    """Warn (exit 0) when npm has a newer ponyfill or pdf.js, or when the newest ponyfill builds on another WASM.

    ``zxing-wasm`` is judged through the ponyfill: its glue and the WASM must stay the same version, so a
    newer ``zxing-wasm`` alone is reported but needs no action until a ``barcode-detector`` release uses it.
    Network errors are warnings too (a weekly report, never a failing build).
    """
    ponyfill, wasm = BARCODE_PACKAGES
    try:
        meta = registry_meta(ponyfill.name)
        latest = str(meta.get("dist-tags", {}).get("latest", ""))
        wanted = str((meta.get("versions", {}).get(latest, {}).get("dependencies") or {}).get(wasm.name, "")).lstrip("^~=")
        wasm_latest = str(registry_meta(wasm.name).get("dist-tags", {}).get("latest", ""))
    except Exception as exc:  # noqa: BLE001 - a weekly warn-only report
        print(f"::warning::could not ask npm about {ponyfill.name} / {wasm.name}: {exc}")
    else:
        if latest and latest != ponyfill.version:
            print(f"::warning::{ponyfill.name} {latest} is out (vendored {ponyfill.version}, it uses {wasm.name} {wanted or '?'}); "
                  "see app/static/vendor/README.md \"Updating\"")
        else:
            print(f"{ponyfill.name} {ponyfill.version} is the latest release")
        if wanted and wanted != wasm.version:
            print(f"::warning::{ponyfill.name} {latest} builds on {wasm.name} {wanted} (vendored {wasm.version})")
        elif wasm_latest and wasm_latest != wasm.version:
            print(f"{wasm.name} {wasm_latest} is out, but {ponyfill.name} {latest} still uses {wasm.version}: nothing to do")
        else:
            print(f"{wasm.name} {wasm.version} is the latest release")
    check_latest_pdfjs()
    return 0


def check_latest_pdfjs() -> None:
    """Warn when npm has a newer ``pdfjs-dist`` (the small dist-tags document, not the whole package listing)."""
    pdfjs = PDFJS_PACKAGES[0]
    try:
        latest = str(json.loads(_get(f"{REGISTRY}/-/package/{pdfjs.name}/dist-tags")).get("latest", ""))
    except Exception as exc:  # noqa: BLE001 - a weekly warn-only report
        print(f"::warning::could not ask npm about {pdfjs.name}: {exc}")
        return
    if latest and latest != pdfjs.version:
        print(f"::warning::{pdfjs.name} {latest} is out (vendored {pdfjs.version}); read its release notes and see "
              "app/static/vendor/README.md \"Updating\" (a pdf.js security advisory is a reason to update inside the 7-day cooldown)")
    else:
        print(f"{pdfjs.name} {pdfjs.version} is the latest release")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the committed files against the pins (offline)")
    group.add_argument("--check-latest", action="store_true", help="warn when npm has newer versions (always exit 0)")
    group.add_argument("--print-hashes", action="store_true", help="download, verify integrity, print hashes, write nothing")
    ap.add_argument("--only", choices=GROUPS, help="work on one group of files only (default: both); downloads nothing of the other")
    args = ap.parse_args(argv)
    groups = (args.only,) if args.only else GROUPS
    if args.check_latest:
        return check_latest()
    if args.check:
        check_files(read_vendored(groups), groups=groups)
        current = (VENDOR / "README.md").read_text(encoding="utf-8") if (VENDOR / "README.md").is_file() else ""
        if current != readme():
            raise VendorError("app/static/vendor/README.md is stale: run python3 scripts/vendor_barcode.py")
        print("vendored files match their pins")
        return 0
    files = fetch(print_only=args.print_hashes, groups=groups)
    if not args.print_hashes:
        write(files)
        print(f"wrote {len(files)} files and README.md under {VENDOR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
