"""The phone and the person's server in step both ways (design note 39 steps 6 and 7; ``app/static/js/mock/server_changes.js``).

``tests/js/server_changes.mjs`` checks the page against a small fake of the change feed (conflicts, the first sync's review, 410,
a different account, offline, 429). Here the same page talks to the real server: with ``--relay`` it writes each request of the
iPhone app's bridge as one line, and this test carries it to the real routes (``GET /push/v1/about``, ``POST /push/v1/sync``, ``GET``
and ``POST /push/v1/changes``, ``POST /push/v1/match``) with a both-ways token and nothing else, as the app does. Only requests on
the app's allow-list (``ServerAPI.swift``) are carried. The test also plays the web app (cookie session), so the page meets the
web's edits, deletes and conflicts, and must work out the very versions the server does.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from conftest import add_user
from test_app_gateway import make_sync, switches
from test_push import bare

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
SWIFT = ROOT / "ios" / "KidneyHealthCore" / "Sources" / "KidneyHealthCore" / "ServerAPI.swift"


def allow_list() -> set[tuple[str, str]]:
    return set(re.findall(r'Route\("(GET|POST|PUT|PATCH|DELETE)", "([^"]+)"', SWIFT.read_text(encoding="utf-8")))


class App:
    """The iPhone app's side of the bridge (ios/KidneyHealth/Services/ServerSync.swift), carried to the real server."""

    def __init__(self, admin: Any, tokens: dict[str, str]) -> None:
        self.admin = admin
        self.tokens = tokens
        self.token = tokens["first"]
        self.allowed = allow_list()
        self.carried: list[str] = []

    def _answer(self, r: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "status": r.status_code, "json": r.text}
        if r.headers.get("retry-after"):
            out["retryAfter"] = int(r.headers["retry-after"])
        return out

    def bridge(self, req: dict[str, Any]) -> dict[str, Any]:
        auth = {"Authorization": f"Bearer {self.token}"}
        kind = req.get("kind")
        if kind == "serverInfo":
            return {"ok": True, "paired": True, "server": "localhost"}
        if kind == "serverSyncCheck":
            return self._answer(bare(self.admin.app).get("/push/v1/sync", headers=auth))
        if kind == "serverSync":
            return self._answer(bare(self.admin.app).post("/push/v1/sync", content=req["body"], headers={**auth, "Content-Type": "application/json"}))
        if kind != "serverApi":
            return {"error": "bad_request"}
        method, path = req["method"], req["path"]
        plain = path.split("?", 1)[0]
        if (method, plain) not in self.allowed:
            return {"error": "refused"}
        self.carried.append(f"{method} {plain}")
        headers = dict(auth)
        body = req.get("body")
        if body is not None:
            headers["Content-Type"] = "application/json"
        return self._answer(bare(self.admin.app).request(method, path, content=body, headers=headers))

    def handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        if "bridge" in msg:
            return self.bridge(msg["bridge"])
        if "web" in msg:
            w = msg["web"]
            r = self.admin.request(w["method"], w["path"], json=w.get("json"))
            return {"status": r.status_code, "json": r.json() if r.content else None}
        if "token" in msg:
            self.token = self.tokens[msg["token"]]
            return {"ok": True}
        if "count" in msg:
            r = bare(self.admin.app).get("/push/v1/changes", headers={"Authorization": f"Bearer {self.tokens[msg['count']]}"})
            return {"entries": sum(1 for c in r.json()["changes"] if c["kind"] == "entry")}
        return {"ok": True}


def test_the_page_syncs_both_ways_with_the_real_server(https_client):
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    admin = https_client
    switches(admin)
    sam = add_user(admin)
    app = App(admin, {"first": make_sync(admin)["token"], "second": make_sync(sam)["token"]})
    proc = subprocess.Popen(["node", str(ROOT / "tests" / "js" / "server_changes.mjs"), "--relay"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    out: list[str] = []
    try:
        assert proc.stdout is not None and proc.stdin is not None
        for line in proc.stdout:
            if not line.startswith("@@ "):
                out.append(line)
                continue
            answer = app.handle(json.loads(line[3:]))
            proc.stdin.write(json.dumps(answer) + "\n")
            proc.stdin.flush()
        proc.wait(timeout=300)
    finally:
        if proc.poll() is None:
            proc.kill()
    err = proc.stderr.read() if proc.stderr else ""
    assert proc.returncode == 0, "".join(out) + err
    assert "server changes (real server):" in "".join(out) and "checks passed" in "".join(out)
    # the page used the sync routes, through the allow-list only
    for route in ("GET /push/v1/about", "GET /push/v1/changes", "POST /push/v1/changes"):
        assert route in app.carried, route


def test_the_module_is_device_mode_only_and_has_no_network_of_its_own():
    code = (STATIC / "js" / "mock" / "server_changes.js").read_text(encoding="utf-8")
    assert "KH.flags.DEVICE !== true" in code
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "Authorization", "khd_", "localStorage", "indexedDB"):
        assert word not in code, word
    assert "M.serverApi.call(" in code  # the app carries every request
    # nothing in sync looks at what an entry was for (a low treatment is synced like any entry), and nothing warns about it
    assert "hypo" not in re.sub(r"purpose === 'hypo' \? 'hypo' : (null|'none')", "", code)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="js/mock/server_sync.js"') < html.index('src="js/mock/server_changes.js"') < html.index('src="js/mock/seed.js"')
    assert "'/js/mock/server_changes.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_fake_server_checks_pass():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "server_changes.mjs")], capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server changes:" in done.stdout and "checks passed" in done.stdout
