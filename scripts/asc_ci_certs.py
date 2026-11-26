#!/usr/bin/env python3
"""Remove the Apple Development certificates that the TestFlight workflow's Mac runners leave behind.

Why: each TestFlight run starts on a fresh Mac. To archive the app, Xcode signs in with the App Store Connect API key and makes
a new "Apple Development" certificate whose private key lives only on that Mac. The Mac is thrown away after the run, so the
certificate is useless, but it stays on the account. Apple allows only a few, and build 10 (2026-11-26) failed with "Your account
has reached the maximum number of certificates".

Two ways to run it (both need ASC_KEY_ID, ASC_ISSUER_ID and the path of the .p8 file in ASC_KEY_PATH):

  python scripts/asc_ci_certs.py this-run
      Removes the development certificates whose private key is in this Mac's keychains. The Mac is new for each run, so
      those are the ones this run made. The workflow runs it at the end of every run, whether the build worked or not.

  python scripts/asc_ci_certs.py old-runs
      Removes every development certificate the account lists as made through the API ("Created via API"). Only the TestFlight
      workflow makes those; their private keys were on Macs that no longer exist. Certificates made in Xcode on a person's own
      Mac carry that person's name and are never touched. Distribution certificates are never touched either, so builds already
      in TestFlight or the App Store keep working. The workflow runs this only when the person starting it ticks the box.

Standard library only (the runner has no project packages): the token is signed with the openssl command.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

API = "https://api.appstoreconnect.apple.com/v1"
DEV_TYPES = ("DEVELOPMENT", "IOS_DEVELOPMENT")
MADE_BY_API = "created via api"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_to_raw(der: bytes, size: int = 32) -> bytes:
    """An ECDSA signature from openssl (DER: SEQUENCE of two INTEGERs) as JWS wants it: r and s, each `size` bytes."""
    if len(der) < 8 or der[0] != 0x30:
        raise ValueError("not a DER signature")
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    parts = []
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("not a DER integer")
        n = der[i + 1]
        value = der[i + 2:i + 2 + n].lstrip(b"\x00")
        if len(value) > size:
            raise ValueError("integer too long")
        parts.append(value.rjust(size, b"\x00"))
        i += 2 + n
    return parts[0] + parts[1]


def token(key_id: str, issuer: str, key_path: str, now: int | None = None) -> str:
    now = int(time.time()) if now is None else now
    header = b64url(json.dumps({"alg": "ES256", "kid": key_id, "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps({"iss": issuer, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"},
                             separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path], input=signing_input,
                         capture_output=True, check=True).stdout
    return f"{header}.{body}.{b64url(der_to_raw(der))}"


def norm_serial(serial: str) -> str:
    return serial.strip().upper().lstrip("0") or "0"


def made_by_api(cert: dict) -> bool:
    attrs = cert.get("attributes") or {}
    names = f"{attrs.get('name') or ''} {attrs.get('displayName') or ''}".lower()
    return attrs.get("certificateType") in DEV_TYPES and MADE_BY_API in names


def pick(certs: list[dict], mode: str, local_serials: set[str]) -> list[dict]:
    """The certificates to remove. this-run: development ones whose private key is on this fresh Mac, so this run made them.
    old-runs: development ones the account lists as made through the API."""
    if mode == "this-run":
        return [c for c in certs if (c.get("attributes") or {}).get("certificateType") in DEV_TYPES
                and norm_serial((c.get("attributes") or {}).get("serialNumber") or "") in local_serials]
    return [c for c in certs if made_by_api(c)]


def local_serials() -> set[str]:
    """Serial numbers of the Apple Development certificates in this Mac's keychains."""
    out = subprocess.run(["security", "find-certificate", "-a", "-c", "Apple Development", "-p"],
                         capture_output=True, text=True, check=False).stdout
    serials = set()
    for pem in re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", out, flags=re.S):
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(pem + "\n")
        try:
            line = subprocess.run(["openssl", "x509", "-noout", "-serial", "-in", f.name],
                                  capture_output=True, text=True, check=True).stdout
        finally:
            os.unlink(f.name)
        serials.add(norm_serial(line.split("=", 1)[1]))
    return serials


def call(method: str, url: str, jwt: str) -> dict:
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {jwt}"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host above
        raw = resp.read()
    return json.loads(raw) if raw else {}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("this-run", "old-runs"):
        print(__doc__)
        return 2
    mode = argv[1]
    jwt = token(os.environ["ASC_KEY_ID"], os.environ["ASC_ISSUER_ID"], os.environ["ASC_KEY_PATH"])
    certs = call("GET", f"{API}/certificates?filter[certificateType]={','.join(DEV_TYPES)}&limit=200", jwt).get("data", [])
    serials = local_serials() if mode == "this-run" else set()
    chosen = pick(certs, mode, serials)
    for cert in chosen:
        call("DELETE", f"{API}/certificates/{cert['id']}", jwt)
    kept = len([c for c in certs if (c.get("attributes") or {}).get("certificateType") in DEV_TYPES]) - len(chosen)
    print(f"Removed {len(chosen)} development certificate(s) made by earlier runners; {kept} other development certificate(s) kept.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
