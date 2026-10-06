"""HTTP half of the container smoke test (.github/scripts/smoke-test.sh), stdlib only.

    python3 .github/scripts/smoke_http.py http://127.0.0.1:18001

Waits for /healthz, then checks what a person needs from a fresh install running with
AUTH_MODE=none: the food list loads and a meal can be logged (POST /api/log -> 201), which proves
the read-only root filesystem leaves /data writable for SQLite. Proxies from the environment are
ignored, like app/healthcheck.py does. Exit status 0 on success, 1 with a message otherwise.
"""
from __future__ import annotations

import json
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
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1].rstrip("/")))
