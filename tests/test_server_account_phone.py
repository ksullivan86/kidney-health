"""Design note 39 step 8 on the phone: saved meals both ways, and the profile, targets, account settings and food preferences that
come from the person's server (``js/mock/server_changes.js``, ``js/mock/server_account.js``, ``js/views/server_review.js``).

``tests/js/server_account.mjs --relay`` runs the page; this test carries each request of the iPhone app's bridge to the real routes
with a both-ways token and nothing else, and only when it is on the app's allow-list (``ServerAPI.swift``, with its ``{food_id}``
segments), and plays the web app (cookie session): a Care team's target, the web's saved meals, edits on both sides."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from test_app_gateway import make_sync, switches
from test_server_changes_phone import ROOT, STATIC, App

ID_SEGMENT = re.compile(r"/\d{1,18}(?=/|$)")


class StepEightApp(App):
    """The app's allow-list matches a ``{food_id}`` segment as digits (ServerAPI.Route.matches)."""

    def bridge(self, req: dict[str, Any]) -> dict[str, Any]:
        if req.get("kind") == "serverApi":
            plain = req["path"].split("?", 1)[0]
            if (req["method"], plain) not in self.allowed and (req["method"], ID_SEGMENT.sub("/{food_id}", plain)) in self.allowed:
                self.carried.append(f"{req['method']} {ID_SEGMENT.sub('/{food_id}', plain)}")
                self.allowed = self.allowed | {(req["method"], plain)}
        return super().bridge(req)


def run(admin: Any, app: App) -> str:
    proc = subprocess.Popen(["node", str(ROOT / "tests" / "js" / "server_account.mjs"), "--relay"], stdin=subprocess.PIPE,
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
    return "".join(out)


def test_the_page_takes_the_servers_profile_settings_and_saved_meals(https_client):
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    switches(https_client)
    app = StepEightApp(https_client, {"first": make_sync(https_client)["token"]})
    out = run(https_client, app)
    assert "server account (real server):" in out and "checks passed" in out
    for route in ("GET /push/v1/api/profile", "PUT /push/v1/api/profile", "GET /push/v1/api/me/settings", "PATCH /push/v1/api/me/settings",
                  "GET /push/v1/api/guidance/preferences", "PUT /push/v1/api/guidance/preferences/{food_id}",
                  "DELETE /push/v1/api/guidance/preferences/{food_id}", "GET /push/v1/changes", "POST /push/v1/changes"):
        assert route in app.carried, route


def test_without_a_server_nothing_changes():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "server_account.mjs")], capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server account:" in done.stdout and "checks passed" in done.stdout


def test_the_modules_are_device_mode_only_and_have_no_network_of_their_own():
    for rel in ("js/mock/server_account.js", "js/views/server_review.js"):
        code = (STATIC / rel).read_text(encoding="utf-8")
        assert "KH.flags.DEVICE !== true" in code, rel
        for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "Authorization", "khd_", "localStorage", "indexedDB", "hypo"):
            assert word not in code, (rel, word)
    code = (STATIC / "js" / "mock" / "server_account.js").read_text(encoding="utf-8")
    assert "M.serverApi.call(" in code
    # only the account keys go to the server; the theme and the camera are this iPhone's own
    assert "const ACCOUNT_KEYS = ['user.units.labs', 'user.units.weight', 'body.weight_alarm', 'body.bp_goal', 'guidance'];" in code
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="js/mock/guidance.js"') < html.index('src="js/mock/server_changes.js"') < html.index('src="js/mock/server_account.js"')
    assert html.index('src="js/views/settings.js"') < html.index('src="js/views/server_review.js"')
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "'/js/mock/server_account.js'," in sw and "'/js/views/server_review.js'," in sw
