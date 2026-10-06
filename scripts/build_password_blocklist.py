#!/usr/bin/env python3
"""Build ``app/auth/password-blocklist.txt.gz`` (note 07 §4.6, NIST SP 800-63B-4 §3.1.1.2).

Source: the UK NCSC top-100k list from Have I Been Pwned, via SecLists (MIT licence),
``Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt``. The list is in frequency
order. We keep, in that order, the first :data:`KEEP` entries that are at least 8 characters long
after NFC normalisation and casefolding (8 is the lowest ``PASSWORD_MIN_LENGTH`` allowed), one per
line, gzipped deterministically.

Why not all 46,483 such entries: NIST asks for a blocklist "of sufficient size to prevent
subscribers from choosing passwords that attackers are likely to guess before reaching the attempt
limit", and the attempt limit here is 100 consecutive failures with growing delays (§4.9). The most
common 10,000 cover that by two orders of magnitude while keeping the file small (about 40 KB).

Usage (needs network once; the result is committed):

    python scripts/build_password_blocklist.py            # verify the source hash, write the file
    python scripts/build_password_blocklist.py --print-hash
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import sys
import unicodedata
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/danielmiessler/SecLists/master/"
    "Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt"
)
# SHA-256 of the source file used for the committed blocklist (downloaded 2026-10-06).
SOURCE_SHA256 = "c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0"
MIN_LENGTH = 8
KEEP = 10_000
OUTPUT = Path(__file__).resolve().parent.parent / "app" / "auth" / "password-blocklist.txt.gz"


def build(raw: bytes) -> bytes:
    seen: set[str] = set()
    kept: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        entry = unicodedata.normalize("NFC", line.strip()).casefold()
        if len(entry) < MIN_LENGTH or entry in seen:
            continue
        seen.add(entry)
        kept.append(entry)
        if len(kept) >= KEEP:
            break
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as gz:
        gz.write(("\n".join(kept) + "\n").encode("utf-8"))
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="read the list from this file instead of downloading it")
    parser.add_argument("--print-hash", action="store_true", help="print the source SHA-256 and exit")
    args = parser.parse_args(argv)
    if args.source:
        raw = Path(args.source).read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as response:  # noqa: S310 (fixed https URL)
            raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if args.print_hash:
        print(digest)
        return 0
    if digest != SOURCE_SHA256:
        print(f"source SHA-256 {digest} differs from the recorded {SOURCE_SHA256}; review the change and update "
              "SOURCE_SHA256 in this script", file=sys.stderr)
        return 1
    data = build(raw)
    OUTPUT.write_bytes(data)
    print(f"wrote {OUTPUT} ({len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
