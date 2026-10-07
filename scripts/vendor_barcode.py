#!/usr/bin/env python3
"""Vendor the barcode decoder the browser falls back to (note 03 R7, §6 item 12, §9 B9; note 02 R7).

The app decodes barcodes on the phone. Browsers with a native ``BarcodeDetector`` (Chrome on Android,
macOS and ChromeOS) need nothing; every other browser, iPhones included, uses the ``barcode-detector``
ponyfill over ZXing-C++ compiled to WebAssembly. Both files are served from ``app/static/vendor/``,
because the app loads nothing from a CDN.

What this script does (standard library only; dev time, never at runtime):

1. Asks the npm registry for each pinned package version and downloads its tarball.
2. Checks the tarball against the registry's ``dist.integrity`` (SHA-512) **before** reading it (§9 B9).
3. Takes only the listed files out of the tarball (read in memory, never extracted to disk), and checks
   each against the SHA-256 pinned below; the ponyfill's own ``ZXING_WASM_SHA256`` constant must equal
   the WASM's hash, and its ``ZXING_CPP_COMMIT`` names the ZXing-C++ commit whose Apache-2.0 licence is
   fetched from raw.githubusercontent.com and checked against its pin too.
4. Writes the files under ``app/static/vendor/`` and regenerates ``app/static/vendor/README.md``.

Usage::

    python3 scripts/vendor_barcode.py                # download, verify, write (needs the network)
    python3 scripts/vendor_barcode.py --check        # verify the committed files against the pins (offline)
    python3 scripts/vendor_barcode.py --check-latest # warn when npm has newer versions (exit 0; CI, weekly)
    python3 scripts/vendor_barcode.py --print-hashes # download and verify integrity, print SHA-256 (updating)

Updating: read the new versions' changelogs, change ``PACKAGES`` (version, and keep the ponyfill's
``zxing-wasm`` dependency and the WASM version equal: the 3.1.4 WASM does not fit the 3.1.3 glue), run
``--print-hashes``, review, paste the new hashes, run without options, then run the browser checks in
``tools/e2e/device.py`` (photo decoding through the WASM path) before committing.
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
MAX_DOWNLOAD = 8 * 1024 * 1024  # the zxing-wasm tarball is about 1.7 MB


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


PACKAGES: tuple[Package, ...] = (
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
ZXING_CPP_COMMIT = "a17fd9dc65d6aa0dd2f660fdfca7a6a6613d938f"
ZXING_CPP_LICENCE = VendoredFile("LICENSE", "zxing-wasm-3.1.3/LICENSE.zxing-cpp",
                                 "c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08", 11358,
                                 "ZXing-C++ Apache License 2.0, at the commit the WASM was built from")
PONYFILL = PACKAGES[0].files[0]
WASM = PACKAGES[1].files[0]
# The constants the ponyfill exports (minified as `name=\`value\``).
_CONST = re.compile(r"\b(\w{1,3})=`([0-9a-f.]{5,64})`")


class VendorError(SystemExit):
    """A failed check: the message says what differs; nothing is written."""


def _get(url: str) -> bytes:
    if not url.startswith("https://"):
        raise VendorError(f"refusing a non-https URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "kidney-health vendor_barcode.py", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:  # noqa: S310 - https only, checked above
        data = res.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise VendorError(f"{url}: larger than {MAX_DOWNLOAD} bytes")
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


def fetch(print_only: bool = False) -> dict[str, bytes]:
    """Download every package, verify integrity and pins, return {dest: bytes}."""
    files: dict[str, bytes] = {}
    computed: list[tuple[str, str, int]] = []
    for pkg in PACKAGES:
        meta = registry_meta(pkg.name, pkg.version)
        dist = meta.get("dist") or {}
        tarball = _get(str(dist.get("tarball", "")))
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
    consts = ponyfill_constants(files[PONYFILL.dest].decode("utf-8"))
    commit = consts.get("ZXING_CPP_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise VendorError("the ponyfill does not export ZXING_CPP_COMMIT")
    licence = _get(ZXING_CPP_RAW.format(commit=commit))
    computed.append((ZXING_CPP_LICENCE.dest, sha256(licence), len(licence)))
    files[ZXING_CPP_LICENCE.dest] = licence
    if print_only:
        print(f"ZXING_CPP_COMMIT = {commit!r}")
        for dest, digest, size in computed:
            print(f"{dest}: sha256 {digest}  {size} bytes")
        return files
    check_files(files, consts)
    if commit != ZXING_CPP_COMMIT:
        raise VendorError(f"the ponyfill names ZXing-C++ {commit}, the pin is {ZXING_CPP_COMMIT}")
    return files


def all_files() -> tuple[VendoredFile, ...]:
    return tuple(f for pkg in PACKAGES for f in pkg.files) + (ZXING_CPP_LICENCE,)


def check_files(files: dict[str, bytes], consts: dict[str, str] | None = None) -> None:
    """Every vendored file has its pinned hash and size; the ponyfill names this WASM and version."""
    for vf in all_files():
        data = files.get(vf.dest)
        if data is None:
            raise VendorError(f"missing app/static/vendor/{vf.dest}")
        if sha256(data) != vf.sha256 or len(data) != vf.size:
            raise VendorError(f"app/static/vendor/{vf.dest}: sha256 {sha256(data)} ({len(data)} bytes), "
                              f"pinned {vf.sha256} ({vf.size} bytes)")
    consts = consts if consts is not None else ponyfill_constants(files[PONYFILL.dest].decode("utf-8"))
    if consts.get("ZXING_WASM_SHA256") != WASM.sha256:
        raise VendorError(f"the ponyfill expects WASM {consts.get('ZXING_WASM_SHA256')}, the vendored one is {WASM.sha256}")
    wasm_pkg = PACKAGES[1]
    if consts.get("ZXING_WASM_VERSION") != wasm_pkg.version:
        raise VendorError(f"the ponyfill was built for zxing-wasm {consts.get('ZXING_WASM_VERSION')}, vendored {wasm_pkg.version}")


def readme() -> str:
    """app/static/vendor/README.md (generated: the test compares it with this function)."""
    rows = []
    for pkg in PACKAGES:
        for vf in pkg.files:
            rows.append(f"| `{vf.dest}` | {pkg.name} {pkg.version} `{vf.member.removeprefix('package/')}` | {vf.size:,} | `{vf.sha256}` |")
    vf = ZXING_CPP_LICENCE
    rows.append(f"| `{vf.dest}` | ZXing-C++ `LICENSE` at `{ZXING_CPP_COMMIT[:12]}` | {vf.size:,} | `{vf.sha256}` |")
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
        "| File | From | Bytes | SHA-256 |",
        "|---|---|---|---|",
        *rows,
        "",
        "| Package | Version | Licence | Source |",
        "|---|---|---|---|",
        *(f"| `{p.name}` | {p.version} | {p.licence} | [{p.homepage.removeprefix('https://')}]({p.homepage}), "
          f"npm `{REGISTRY}/{p.name}/-/{p.name}-{p.version}.tgz` |" for p in PACKAGES),
        f"| ZXing-C++ | `{ZXING_CPP_COMMIT}` | Apache-2.0 | [github.com/zxing-cpp/zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) |",
        "",
        "Checks made when the files were vendored: each npm tarball matched the registry's `dist.integrity`",
        "(SHA-512) before it was read; the ponyfill's own `ZXING_WASM_SHA256` constant equals the WASM's hash and",
        "its `ZXING_WASM_VERSION` the vendored `zxing-wasm` version (the 3.1.4 WASM does not fit the 3.1.3 glue);",
        "its `ZXING_CPP_COMMIT` names the ZXing-C++ commit whose licence is copied here.",
        "",
        "## Updating",
        "",
        "1. `python3 scripts/vendor_barcode.py --check-latest` (CI runs it weekly, warn only) says when npm has",
        "   newer versions. Read their changelogs.",
        "2. Change the versions in `PACKAGES` in `scripts/vendor_barcode.py`, run it with `--print-hashes`, review",
        "   the new hashes and paste them over the old pins (also the paths in `js/scan.js`, `index.html`, `sw.js`",
        "   and `tests/test_vendor.py`, which name the versioned folders).",
        "3. Run `python3 scripts/vendor_barcode.py`, then `python -m pytest tests/test_vendor.py` and the photo",
        "   decoding check of `tools/e2e/device.py` (it decodes a generated EAN-13 through the WASM path).",
        "",
    ]
    return "\n".join(lines)


def read_vendored() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for vf in all_files():
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
    """Warn (exit 0) when npm has a newer ponyfill, or when the newest ponyfill builds on another WASM.

    ``zxing-wasm`` is judged through the ponyfill: its glue and the WASM must stay the same version, so a
    newer ``zxing-wasm`` alone is reported but needs no action until a ``barcode-detector`` release uses it.
    Network errors are warnings too (a weekly report, never a failing build).
    """
    ponyfill, wasm = PACKAGES
    try:
        meta = registry_meta(ponyfill.name)
        latest = str(meta.get("dist-tags", {}).get("latest", ""))
        wanted = str((meta.get("versions", {}).get(latest, {}).get("dependencies") or {}).get(wasm.name, "")).lstrip("^~=")
        wasm_latest = str(registry_meta(wasm.name).get("dist-tags", {}).get("latest", ""))
    except Exception as exc:  # noqa: BLE001 - a weekly warn-only report
        print(f"::warning::could not ask npm about {ponyfill.name} / {wasm.name}: {exc}")
        return 0
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
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="verify the committed files against the pins (offline)")
    group.add_argument("--check-latest", action="store_true", help="warn when npm has newer versions (always exit 0)")
    group.add_argument("--print-hashes", action="store_true", help="download, verify integrity, print hashes, write nothing")
    args = ap.parse_args(argv)
    if args.check_latest:
        return check_latest()
    if args.check:
        check_files(read_vendored())
        current = (VENDOR / "README.md").read_text(encoding="utf-8") if (VENDOR / "README.md").is_file() else ""
        if current != readme():
            raise VendorError("app/static/vendor/README.md is stale: run python3 scripts/vendor_barcode.py")
        print("vendored files match their pins")
        return 0
    files = fetch(print_only=args.print_hashes)
    if not args.print_hashes:
        write(files)
        print(f"wrote {len(files)} files and README.md under {VENDOR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
