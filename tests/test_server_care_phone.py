"""Notes and suggestions from the Care team on the phone (design notes 37 and 29; owner, 2026-11-26; ``js/mock/server_care.js``).

``tests/js/server_care.mjs --relay`` runs the page; this test carries each request of the iPhone app's bridge to the real routes with
a both-ways token and nothing else, only when it is on the app's allow-list (``ServerAPI.swift``, with its ``{note_id}`` and
``{suggestion_id}`` segments) and with the ``If-Match`` the page sends, and plays the person's Clinician, Dee, in her own web app:
she writes and edits notes and suggests meals. The plain run checks the page against a stand-in."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from conftest import TestClient, add_user, find_food
from test_app_gateway import make_sync, switches
from test_care_notes import notes_switch
from test_care_team import join
from test_push import bare
from test_server_changes_phone import ROOT, STATIC, App
from test_sharing import switch

ID_SEGMENT = re.compile(r"/\d{1,18}(?=/|$)")
PLACEHOLDERS = ("{food_id}", "{note_id}", "{suggestion_id}")


class CareApp(App):
    """The app's allow-list with its id segments (ServerAPI.Route.matches), ``If-Match`` carried as the app does, and Dee."""

    def __init__(self, admin: TestClient, tokens: dict[str, str], dee: TestClient, share_id: int) -> None:
        super().__init__(admin, tokens)
        self.dee = dee
        self.share_id = share_id

    def bridge(self, req: dict[str, Any]) -> dict[str, Any]:
        if req.get("kind") != "serverApi":
            return super().bridge(req)
        method, plain = req["method"], req["path"].split("?", 1)[0]
        template = next((ID_SEGMENT.sub(f"/{p}", plain) for p in PLACEHOLDERS if (method, ID_SEGMENT.sub(f"/{p}", plain)) in self.allowed), plain)
        if (method, template) not in self.allowed:
            return {"error": "refused"}
        self.carried.append(f"{method} {template}")
        headers = {"Authorization": f"Bearer {self.token}"}
        if req.get("ifMatch"):
            headers["If-Match"] = req["ifMatch"]
        if req.get("body") is not None:
            headers["Content-Type"] = "application/json"
        return self._answer(bare(self.admin.app).request(method, req["path"], content=req.get("body"), headers=headers))

    def handle(self, msg: dict[str, Any]) -> dict[str, Any]:
        if "care" not in msg:
            return super().handle(msg)
        c, sid = msg["care"], self.share_id
        if c["what"] == "note":
            r = self.dee.post(f"/api/shared/{sid}/notes", json={k: c[k] for k in ("body", "area") if k in c})
        elif c["what"] == "edit":
            r = self.dee.put(f"/api/shared/{sid}/notes/{c['id']}", json={"body": c["body"]}, headers={"If-Match": '"1"'})
        elif c["what"] == "list":
            r = self.dee.get(f"/api/shared/{sid}/notes")
        elif c["what"] == "suggest":
            food = find_food(self.admin, c["query"])
            r = self.dee.post(f"/api/shared/{sid}/suggestions", json={"date": "2026-12-01", "meal": "dinner",
                                                                       "items": [{"food_id": food["id"], "servings": 1}]})
        else:
            r = self.dee.get(f"/api/shared/{sid}/suggestions")
        assert r.status_code < 300, r.text
        return {"status": r.status_code, "json": r.json()}


def run(app: App) -> str:
    proc = subprocess.Popen(["node", str(ROOT / "tests" / "js" / "server_care.mjs"), "--relay"], stdin=subprocess.PIPE,
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


def test_the_page_shows_the_servers_notes_and_suggestions(https_client):
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    admin = https_client
    switches(admin)
    switch(admin)
    notes_switch(admin)
    dee = add_user(admin, "Dee")
    sid = join(admin, dee, username="Dee", role="clinician", areas=["food", "labs"])
    assert admin.put(f"/api/me/shares/{sid}/switches", json={"may_suggest": True}).status_code == 200
    app = CareApp(admin, {"first": make_sync(admin)["token"]}, dee, sid)
    out = run(app)
    assert "server care (real server):" in out and "checks passed" in out
    for route in ("GET /push/v1/about", "GET /push/v1/api/me/notes", "POST /push/v1/api/me/notes/{note_id}/read",
                  "DELETE /push/v1/api/me/notes/{note_id}", "GET /push/v1/api/me/suggestions",
                  "POST /push/v1/api/me/suggestions/{suggestion_id}/accept", "POST /push/v1/api/me/suggestions/{suggestion_id}/decline",
                  "GET /push/v1/changes"):
        assert route in app.carried, route
    # the person's entry, added on the server, is their own
    planned = admin.get("/api/log", params={"date": "2026-12-01"}).json()["entries"]
    assert [(e["status"], e["added_by"]) for e in planned] == [("planned", None)]


def test_with_a_stand_in_and_with_no_server():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "server_care.mjs")], capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server care:" in done.stdout and "checks passed" in done.stdout


def test_the_module_is_device_mode_only_and_keeps_nothing():
    code = (STATIC / "js" / "mock" / "server_care.js").read_text(encoding="utf-8")
    assert "KH.flags.DEVICE !== true" in code
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "Authorization", "khd_", "localStorage", "indexedDB", "innerHTML"):
        assert word not in code, word
    care = (STATIC / "js" / "mock" / "care.js").read_text(encoding="utf-8")
    for route in ("'GET', '/api/me/suggestions'", "'GET', '/api/me/notes'"):
        assert f"mineRoute({route}" in care, route
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="js/mock/care.js"') < html.index('src="js/mock/server_api.js"') < html.index('src="js/mock/server_care.js"')
    assert "'/js/mock/server_care.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")
    # Settings → Care team in the iPhone app is read-only: no request that changes sharing
    sharing = (STATIC / "js" / "views" / "sharing.js").read_text(encoding="utf-8")
    block = sharing[sharing.index("async function deviceBlock()"):sharing.index("// A link followed while the app is already open")]
    assert "request('GET', '/api/device/care-team')" in block
    for word in ("'POST'", "'PUT'", "'DELETE'", "A.end", "A.invite"):
        assert word not in block, word
