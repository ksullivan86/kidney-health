"""The phone side of sending to a server (design note 38 §5.5, step 4; ``app/static/js/mock/server_sync.js``).

``tests/js/server_sync.mjs`` checks the page's queue against a stand-in for the iPhone app: client IDs, batches within the
server's limits, the food references, that the sample data is never sent, and each answer (200 with skipped rows, 400 naming a
row, 401, 413, 429, offline). Here it runs, and one request body the page built goes to the real ``POST /push/v1/sync``, so the
page and the server agree on every field.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from test_app_sync import admin, app_token, counts, ok  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def _page_body(tmp_path: Path) -> dict:
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    out = tmp_path / "body.json"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "server_sync.mjs"), "--dump", str(out)], capture_output=True, text=True,
                          timeout=300, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server sync:" in done.stdout and "checks passed" in done.stdout
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_page_body_is_taken_by_the_server_once(admin, app_token, tmp_path):  # noqa: F811
    body = _page_body(tmp_path)
    assert list(body) == ["foods", "entries", "labs", "symptoms", "weights", "readings"]
    first = ok(admin.app, app_token, body)
    # The own food and the USDA food this server does not hold (kept as the person's own copy), three entries (an own food, a
    # built-in food by fdc_id, the USDA food), and one of each other kind.
    assert first["added"] == counts(foods=2, entries=3, labs=1, symptoms=1, weights=1, readings=1)
    assert first["skipped"] == {"food_not_found": 0, "day_full": 0}
    again = ok(admin.app, app_token, body)
    assert again["added"] == counts()
    assert again["already_there"] == counts(foods=2, entries=3, labs=1, symptoms=1, weights=1, readings=1)
    builtin = next(e for e in body["entries"] if "builtin" in e["food"])
    log = admin.get("/api/log", params={"date": builtin["date"]}).json()
    rows = log["entries"] if isinstance(log, dict) else log
    names = {r["food_name"] for r in rows}
    assert builtin["food"]["builtin"]["name"] in names  # the server's own built-in food, found by fdc_id
    assert "Grandma's rice pudding" in names and "Diet Coke" in names


def test_the_module_is_device_mode_only_and_has_no_network_of_its_own():
    code = (STATIC / "js" / "mock" / "server_sync.js").read_text(encoding="utf-8")
    assert "KH.flags.DEVICE !== true" in code  # nothing exists outside device mode
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "Authorization", "khd_", "localStorage", "indexedDB"):
        assert word not in code, word
    assert "window.webkit.messageHandlers.bridge" in code  # the app carries the request
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="js/mock/device.js"') < html.index('src="js/mock/server_sync.js"') < html.index('src="js/mock/seed.js"')
    assert "'/js/mock/server_sync.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")
