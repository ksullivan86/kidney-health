#!/usr/bin/env python3
"""Live check of the Open Food Facts mapping against the real service (developer / scheduled CI tool).

    python3 scripts/check_off_live.py                  # staging: https://world.openfoodfacts.net
    python3 scripts/check_off_live.py --live           # production: https://world.openfoodfacts.org

Tests never use the network; this script is the early warning that they cannot give: it asks Open Food
Facts for the products recorded in ``tests/fixtures/off/`` with the app's own request
(:func:`app.off.product_url`, the identifying User-Agent) and checks what note 03 §5 calls the main
risk, "OFF changes the schema again":

* the pinned API (``app.off.OFF_API_VERSION``) still returns a flat, non-empty ``nutriments`` object
  for products that have nutrition facts;
* the newest API's ``nutrition.aggregated_set`` still parses (:func:`app.off.parse_nutrition_v35`) to
  the same per-100 g values as the pinned API;
* every product still maps (:func:`app.off.map_product`) to a food with energy and sodium.

Exit status 0 when all checks pass, 1 otherwise (meant as a warn-only scheduled job). Staging needs the
HTTP Basic login ``off``/``off`` that Open Food Facts publishes for it. The script waits 6 s between
requests (OFF allows 15 product reads per minute) and honours ``HTTPS_PROXY``.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx2  # noqa: E402

from app import off  # noqa: E402
from app.gtin import normalize, off_code  # noqa: E402

STAGING = "https://world.openfoodfacts.net"
STAGING_AUTH = ("off", "off")  # published by Open Food Facts for its staging server
NEWEST_API = "3.6"
PAUSE_S = 6.0
# (barcode, has nutrition facts) for the recorded products (tests/fixtures/off/README.md).
PRODUCTS = (("0049000028911", True), ("0021000658831", True), ("0028400090858", True), ("3017624010701", True))
COMPARED = ("energy-kcal", "proteins", "fat", "carbohydrates", "sugars", "sodium", "salt", "potassium")


def app_version() -> str:
    match = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / "app" / "main.py").read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else "dev"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--live", action="store_true", help="ask world.openfoodfacts.org instead of staging")
    parser.add_argument("--contact", default=off.DEFAULT_CONTACT)
    args = parser.parse_args(argv)
    base = off.DEFAULT_BASE_URL if args.live else STAGING
    auth = None if args.live else STAGING_AUTH
    headers = {"User-Agent": off.user_agent(app_version(), args.contact), "Accept": "application/json"}
    problems: list[str] = []
    with httpx2.Client(timeout=20, headers=headers, auth=auth, follow_redirects=False) as client:
        first = True
        for code, has_nutrition in PRODUCTS:
            gtin14 = normalize(code, "unknown")
            answers = {}
            for version in (off.OFF_API_VERSION, NEWEST_API):
                if not first:
                    time.sleep(PAUSE_S)
                first = False
                url = off.product_url(base, off_code(gtin14), version)
                response = client.get(url)
                if response.status_code != 200:
                    problems.append(f"{code} API {version}: HTTP {response.status_code}")
                    continue
                answers[version] = response.json().get("product") or {}
            pinned = answers.get(off.OFF_API_VERSION)
            if pinned is None:
                continue
            if has_nutrition and not pinned.get("nutriments"):
                problems.append(f"{code}: API {off.OFF_API_VERSION} returned empty nutriments (the schema changed again)")
            mapped = off.map_product(pinned, gtin14)
            if has_nutrition and (mapped.nutrients.get("calories_kcal") is None or mapped.nutrients.get("sodium_mg") is None):
                problems.append(f"{code}: the mapping lost energy or sodium ({mapped.quality})")
            newest = answers.get(NEWEST_API)
            if newest is not None and has_nutrition:
                parsed = off.parse_nutrition_v35(newest)
                flat = pinned.get("nutriments") or {}
                for name in COMPARED:
                    for suffix in ("_100g", "_prepared_100g"):
                        a, b = flat.get(name + suffix), parsed.get(name + suffix)
                        if a is not None and (b is None or abs(float(a) - float(b)) > 1e-6 * max(1.0, abs(float(a)))):
                            problems.append(f"{code}: API {NEWEST_API} {name}{suffix} = {b}, API {off.OFF_API_VERSION} = {a}")
            print(f"{code}: checked ({mapped.name})")
    for problem in problems:
        print(f"PROBLEM {problem}", file=sys.stderr)
    print(f"{len(problems)} problem(s) against {base}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
