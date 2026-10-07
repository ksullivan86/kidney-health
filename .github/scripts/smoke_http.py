"""HTTP half of the container smoke test (.github/scripts/smoke-test.sh), stdlib only.

    python3 .github/scripts/smoke_http.py http://127.0.0.1:18001

Waits for /healthz, then checks what a person needs from a fresh install running with
AUTH_MODE=none: the food list loads and a meal can be logged (POST /api/log -> 201), which proves
the read-only root filesystem leaves /data writable for SQLite. Then the handbook the image built
(note 08 §4.7): /learn/ and a topic page answer 200 with the handbook's own Content-Security-Policy
(inline-script hashes, no Trusted Types), the app keeps its strict policy, a fingerprinted theme
asset is cached as immutable, the search index loads, and an unknown page is a 404. Proxies from the
environment are ignored, like app/healthcheck.py does. Exit status 0 on success, 1 with a message
otherwise.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
HEADERS = {"Accept": "application/json", "X-Requested-With": "kidney-health"}


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    headers = dict(HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with OPENER.open(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode(errors="replace")[:500]}


def fetch(url: str) -> tuple[int, dict[str, str], str]:
    """GET ``url``: status, headers (lower-case names) and the body as text."""
    request = urllib.request.Request(url, headers={"Accept": "*/*", "Accept-Encoding": "identity"})
    try:
        with OPENER.open(request, timeout=10) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read().decode("utf-8", "replace")


def check_handbook(base: str) -> int:
    """The built handbook at /learn (app/handbook.py) and the policy split between /learn and the app."""
    status, headers, page = fetch(f"{base}/learn/")
    csp = headers.get("content-security-policy", "")
    if status != 200 or "Kidney Health Handbook" not in page:
        print(f"FAIL: GET /learn/ -> {status}; the image has no built handbook in /app/learn", file=sys.stderr)
        return 1
    if "'sha256-" not in csp or "img-src 'self' data:" not in csp or "trusted-types" in csp or "unsafe-inline" in csp:
        print(f"FAIL: /learn/ Content-Security-Policy is not the handbook's: {csp}", file=sys.stderr)
        return 1
    print(f"ok   GET /learn/ -> 200, CSP with {csp.count('sha256-')} script hashes")
    _, app_headers, _ = fetch(f"{base}/")
    if "require-trusted-types-for 'script'" not in app_headers.get("content-security-policy", ""):
        print("FAIL: the app's own CSP lost Trusted Types", file=sys.stderr)
        return 1
    print("ok   GET / keeps the app's strict CSP")
    for path, want in (("/learn/eat/potassium/", 200), ("/learn/search/search_index.json", 200), ("/learn/no-such-page/", 404)):
        status, _, _ = fetch(base + path)
        if status != want:
            print(f"FAIL: GET {path} -> {status}, want {want}", file=sys.stderr)
            return 1
        print(f"ok   GET {path} -> {status}")
    bundle = re.search(r'src="(assets/javascripts/bundle\.[0-9a-f]{8}\.min\.js)"', page)
    if not bundle:
        print("FAIL: /learn/ does not load a fingerprinted theme bundle", file=sys.stderr)
        return 1
    status, headers, _ = fetch(f"{base}/learn/{bundle.group(1)}")
    if status != 200 or "immutable" not in headers.get("cache-control", ""):
        print(f"FAIL: GET /learn/{bundle.group(1)} -> {status}, Cache-Control {headers.get('cache-control')}", file=sys.stderr)
        return 1
    print(f"ok   GET /learn/{bundle.group(1)} -> 200, immutable")
    return 0


def main(base: str) -> int:
    deadline = time.monotonic() + 90
    while True:
        try:
            status, health = call("GET", f"{base}/healthz")
            if status == 200:
                break
        except OSError:
            pass
        if time.monotonic() > deadline:
            print(f"FAIL: {base}/healthz did not answer 200 within 90 s", file=sys.stderr)
            return 1
        time.sleep(1)
    if health.get("status") != "ok" or not health.get("foods"):
        print(f"FAIL: unexpected /healthz body {health}", file=sys.stderr)
        return 1
    print(f"ok   GET /healthz -> {health}")

    status, found = call("GET", f"{base}/api/foods?q=apple&limit=5")
    foods = found.get("foods") or []
    if status != 200 or not foods:
        print(f"FAIL: GET /api/foods -> {status} {found}", file=sys.stderr)
        return 1
    print(f"ok   GET /api/foods -> {len(foods)} foods")

    entry = {"date": time.strftime("%Y-%m-%d"), "meal": "lunch", "food_id": foods[0]["id"], "servings": 1}
    status, created = call("POST", f"{base}/api/log", entry)
    if status != 201:
        print(f"FAIL: POST /api/log -> {status} {created}", file=sys.stderr)
        return 1
    print(f"ok   POST /api/log -> 201 (entry {created.get('id')})")

    status, day = call("GET", f"{base}/api/log?date={entry['date']}")
    if status != 200 or not day.get("entries"):
        print(f"FAIL: GET /api/log -> {status} {day}", file=sys.stderr)
        return 1
    print(f"ok   GET /api/log -> {len(day['entries'])} entries")
    return check_handbook(base)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1].rstrip("/")))
