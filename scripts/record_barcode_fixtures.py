#!/usr/bin/env python3
"""Record the barcode test fixtures from the live services (developer tool; tests never use the network).

    python3 scripts/record_barcode_fixtures.py off            # Open Food Facts (no key needed)
    USDA_API_KEY=... python3 scripts/record_barcode_fixtures.py usda   # FoodData Central (DEMO_KEY if unset)

Writes ``tests/fixtures/off/*.json`` and ``tests/fixtures/usda/*.json``: one file per HTTP exchange
with the request URL, the status, the response ``Content-Type`` and the JSON body exactly as the
service sent it. ``tests/test_off_mapping.py`` and ``tests/test_barcode_api.py`` replay them through
``httpx2.MockTransport``. The requests are built by the app's own code (:func:`app.off.product_url`,
:func:`app.off.user_agent`, :func:`app.gtin.usda_candidates`), so the fixtures show what the app asks.

Be polite: Open Food Facts allows 15 product reads per minute per IP, so the script waits 6 s between
calls and sends the project's identifying User-Agent. The USDA key is sent in the ``X-Api-Key``
header and never written to a fixture. This script honours ``HTTPS_PROXY`` (a development machine
behind a proxy); the app itself goes through :mod:`app.egress`.

Open Food Facts data is under the Open Database License; the recorded single products are
insubstantial extracts used for testing (tests/fixtures/off/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx2  # noqa: E402

from app import off  # noqa: E402
from app.gtin import normalize, off_code, usda_candidates  # noqa: E402

def app_version() -> str:
    """``APP_VERSION`` from app/main.py, read as text (importing app.main would build the app)."""
    import re

    match = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / "app" / "main.py").read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else "dev"


APP_VERSION = app_version()

OFF_DIR = ROOT / "tests" / "fixtures" / "off"
USDA_DIR = ROOT / "tests" / "fixtures" / "usda"
USDA_BASE = "https://api.nal.usda.gov/fdc/v1"
PAUSE_S = 6.0

# (fixture name, barcode as printed, decoder format, API version). Note 03 R12 / §6 item 6.
OFF_PRODUCTS = (
    ("diet_coke_v3.4", "049000028911", "upc_a", "3.4"),        # US, mL serving, E338, potassium not listed
    ("kraft_mac_cheese_v3.4", "0021000658831", "ean_13", "3.4"),  # prepared values only, E451
    ("lays_classic_v3.4", "0028400090858", "ean_13", "3.4"),     # US, potassium listed
    ("nutella_v3.4", "3017624010701", "ean_13", "3.4"),          # EU label: salt, no serving size
    ("nutella_v3.6", "3017624010701", "ean_13", "3.6"),          # API 3.6: empty nutriments, nutrition object
    ("not_found_v3.4", "0099999999990", "ean_13", "3.4"),        # a valid code nobody has added: 404
    ("lays_1oz_v3.4", "028400421584", "upc_a", "3.4"),          # in OFF without nutrition facts; in FDC branded
    ("lays_1125oz_v3.4", "0028400161909", "ean_13", "3.4"),     # in OFF and in FDC (stored there as GTIN-14)
)
# FoodData Central branded search by barcode: one product with a hit, one without (note 03 F3).
USDA_SEARCHES = (
    ("lays_1oz", "028400421584"),      # FDC stores it as a 12-digit UPC-A: the first form hits
    ("lays_1125oz", "0028400161909"),  # FDC stores it as a GTIN-14: only the third form hits
    ("diet_coke", "049000028911"),     # not found in any form (note 03 F3)
)


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save(path: Path, url: str, response: httpx2.Response) -> None:
    content_type = response.headers.get("Content-Type", "")
    try:
        body = response.json()
    except ValueError:
        body = None
    doc = {
        "recorded_at": stamp(),
        "request": {"method": "GET", "url": url},
        "status": response.status_code,
        "content_type": content_type,
        "body": body,
    }
    if body is None:
        doc["text"] = response.text[:2000]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{path.relative_to(ROOT)}: HTTP {response.status_code} ({len(response.content):,} bytes)")


def record_off(contact: str) -> None:
    headers = {"User-Agent": off.user_agent(APP_VERSION, contact), "Accept": "application/json"}
    with httpx2.Client(timeout=20, headers=headers, follow_redirects=False) as client:
        for n, (name, code, fmt, version) in enumerate(OFF_PRODUCTS):
            if n:
                time.sleep(PAUSE_S)
            url = off.product_url(off.DEFAULT_BASE_URL, off_code(normalize(code, fmt)), version)
            save(OFF_DIR / f"{name}.json", url, client.get(url))


def record_usda(api_key: str) -> None:
    """Every barcode form of :data:`USDA_SEARCHES` (``search_<form>.json``) and each exact hit's record
    (``food_<fdcId>.json``). A 429 (``DEMO_KEY`` is limited to a few calls) is saved as
    ``rate_limited.json`` and stops the run."""
    with httpx2.Client(timeout=20, headers={"X-Api-Key": api_key, "User-Agent": f"kidney-health/{APP_VERSION}"}) as client:
        for _name, code in USDA_SEARCHES:
            gtin14 = normalize(code, "unknown")
            hit = None
            for form in usda_candidates(gtin14):
                url = f"{USDA_BASE}/foods/search?query={form}&dataType=Branded&pageSize=10"
                response = client.get(url)
                if response.status_code == 429:
                    save(USDA_DIR / "rate_limited.json", url, response)
                    print("  stopped: the key is over its rate limit", file=sys.stderr)
                    return
                save(USDA_DIR / f"search_{form}.json", url, response)
                time.sleep(2)
                for item in (response.json().get("foods") or []) if response.status_code == 200 else []:
                    if str(item.get("gtinUpc") or "").zfill(14) == gtin14:
                        hit = item.get("fdcId")
                        break
                if hit:
                    break
            if hit:
                url = f"{USDA_BASE}/food/{hit}"
                save(USDA_DIR / f"food_{hit}.json", url, client.get(url))
                time.sleep(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("service", choices=("off", "usda"))
    parser.add_argument("--contact", default=os.environ.get("OFF_CONTACT", off.DEFAULT_CONTACT),
                        help="contact for the Open Food Facts User-Agent (default: the project URL)")
    args = parser.parse_args(argv)
    if args.service == "off":
        record_off(args.contact)
    else:
        key = os.environ.get("USDA_API_KEY") or "DEMO_KEY"
        record_usda(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
