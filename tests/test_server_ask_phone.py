"""Ask and photos of a meal on the iPhone app (design note 39; ``app/static/js/mock/ai.js``, ``views/ask.js``, ``views/ai.js``).

``tests/js/server_ask.mjs`` runs the page against a stand-in for the iPhone app and a fake gateway: why Ask or a meal photo
cannot run for each kind of pairing, the chat through the server with ``trust: "ask"``, the card's foods named by the phone's
ids, Save once through the phone's own routes, a food the phone lacks as a question, the low and emergency answers untouched.
With ``--relay`` the same page talks to the real server through the real gateway, with a fake AI: a person who trusts the
assistant "always" still gets a card on the phone, the server saves nothing until the phone's Save is synced, and then holds the
entry once. ``tests/js/ask_phone.test.mjs`` runs the real Ask screen as the phone. The rest are static checks of what the phone
must never do.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ai_support import FakeProvider, attach
from conftest import DAY, HTTPS_URL, TestClient
from test_ai_chat import become_ready, step_call
from test_ai_routes import ai_settings, enable
from test_app_gateway import make_sync, switches
from test_push import bare
from test_server_changes_phone import allow_list
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def run_node(*args: str) -> subprocess.CompletedProcess[str]:
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    return subprocess.run(["node", *args], capture_output=True, text=True, timeout=300, check=False, cwd=ROOT)


def test_the_page_runs_ask_and_meal_photos_by_the_notes_rules():
    done = run_node(str(ROOT / "tests" / "js" / "server_ask.mjs"))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server ask:" in done.stdout and "checks passed" in done.stdout


def test_the_ask_screen_on_the_phone():
    done = run_node("--test", str(ROOT / "tests" / "js" / "ask_phone.test.mjs"))
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.fixture
def server(tmp_path, foods_json):
    """Ask on, trusted saves allowed, the person trusts it always; the gateway on, one both-ways token."""
    with TestClient(create_app(ai_settings(tmp_path, foods_json)), base_url=HTTPS_URL) as c:
        from conftest import sign_in
        sign_in(c)
        enable(c, **{"ai.chat_enabled": True, "ai.allow_trusted_saves": True})
        become_ready(c)
        assert c.patch("/api/me/ai", json={"trust": "always"}).status_code == 200
        switches(c)
        yield c, make_sync(c)["token"]


def test_the_real_chat_request_through_the_real_gateway_saves_once_through_the_phone(server):
    c, token = server
    allowed = allow_list()
    carried: list[str] = []

    def bridge(req: dict[str, Any]) -> dict[str, Any]:
        auth = {"Authorization": f"Bearer {token}"}
        kind = req.get("kind")
        if kind == "serverInfo":
            return {"ok": True, "paired": True, "server": "localhost"}
        if kind == "serverSyncCheck":
            r = bare(c.app).get("/push/v1/sync", headers=auth)
        elif kind == "serverSync":
            r = bare(c.app).post("/push/v1/sync", content=req["body"], headers={**auth, "Content-Type": "application/json"})
        elif kind == "serverApi":
            method, path = req["method"], req["path"]
            if (method, path.split("?", 1)[0]) not in allowed:
                return {"error": "refused"}
            carried.append(f"{method} {path.split('?', 1)[0]}")
            headers = {**auth, **({"Content-Type": "application/json"} if req.get("body") is not None else {})}
            r = bare(c.app).request(method, path, content=req.get("body"), headers=headers)
        else:
            return {"error": "bad_request"}  # no aiStatus: this iPhone has no AI of its own
        out: dict[str, Any] = {"ok": True, "status": r.status_code, "json": r.text}
        if r.headers.get("retry-after"):
            out["retryAfter"] = int(r.headers["retry-after"])
        return out

    script = [step_call("log_food", items=[{"food": "banana", "amount": 1}], meal="breakfast", date=DAY, status="eaten")]
    out: list[str] = []
    with attach(c.app, FakeProvider(script)):
        proc = subprocess.Popen(["node", str(ROOT / "tests" / "js" / "server_ask.mjs"), "--relay"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, cwd=ROOT)
        try:
            assert proc.stdout is not None and proc.stdin is not None
            for line in proc.stdout:
                if not line.startswith("@@ "):
                    out.append(line)
                    continue
                msg = json.loads(line[3:])
                if "count" in msg:
                    answer: dict[str, Any] = {"entries": len(c.get("/api/log", params={"date": DAY}).json()["entries"])}
                else:
                    answer = bridge(msg["bridge"])
                proc.stdin.write(json.dumps(answer) + "\n")
                proc.stdin.flush()
            proc.wait(timeout=300)
        finally:
            if proc.poll() is None:
                proc.kill()
    err = proc.stderr.read() if proc.stderr else ""
    assert proc.returncode == 0, "".join(out) + err
    assert "server ask (real server):" in "".join(out) and "checks passed" in "".join(out)
    assert "POST /push/v1/api/ai/chat" in carried
    [entry] = c.get("/api/log", params={"date": DAY}).json()["entries"]
    assert entry["food_name"] == "Banana, raw" and entry["status"] == "eaten"


def test_the_phone_never_shows_the_demo_text_and_says_why_ask_is_off():
    ask = (STATIC / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "if (MOCK && !DEVICE) { notice(DEMO_TEXT); return; }" in ask  # the demo's text only outside the phone
    assert ask.count("DEMO_TEXT") == 2  # its definition and that one use
    for reason in ("not_paired", "not_both_ways", "offline", "device_only", "not_synced", "not_opted_in", "server_off"):
        assert re.search(rf"\n    {reason}: `\$\{{ASK_NEEDS\}} ", ask), reason
    assert "Settings → This device → Apple Health and server" in ask
    ai = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
    for reason in ("not_paired", "not_both_ways", "offline", "device_only", "not_synced", "not_opted_in", "server_off"):
        assert re.search(rf"\n    {reason}: `\$\{{PHOTO_NEEDS\}} ", ai), reason
    assert "A photo of your meal or of a label needs your Kidney Health server\\'s AI, your own AI key with photos turned on, or Apple\\'s on-device AI on iOS 27." in ai


def test_ask_on_the_phone_uses_only_the_servers_chat_route_and_never_trusts():
    code = (STATIC / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
    chat = code[code.index("route('POST', '/api/ai/chat'"):code.index("const NOT_HERE")]
    assert "{ ...body, trust: 'ask' }" in chat
    assert "viaServer(this, 'chat', 'POST', `/api/ai/chat${query(qp)}`" in chat
    assert "lookup(" not in chat and "ask(" not in chat.replace("ask'", "")  # the iPhone's own model is never asked
    assert "features.voice = false;" in code
    # the server's low and emergency answers are passed on untouched
    assert "answer.kind === 'treat_low' || answer.kind === 'get_help_now') return answer;" in code
    # the iPhone's model reads a plate or label photo only through photoOnDevice (iOS 27, note 39 §6.6), never a lab photo
    assert "photo" not in code[code.index("async function ask(task, text"):code.index("function extraKeys")]
    on_device = code[code.index("async function photoOnDevice"):code.index("// Ask (app/ai/routes.py chat)")]
    assert re.search(r"\blab", on_device) is None
    from app.app_gateway import ALLOWED
    assert ("POST", "/api/ai/chat") in ALLOWED and ("POST", "/api/vision/plate") in ALLOWED
    assert ("POST", "/push/v1/api/ai/chat") in allow_list()
    stripped = re.sub(r"/\*.*?\*/|//[^\n]*", "", code, flags=re.S).lower()
    for word in ("insulin", "bolus", "dosing"):
        assert word not in stripped, word
