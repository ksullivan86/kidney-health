"""The phone side of design note 39, steps 3 and 4: the server's food services and AI from the iPhone app
(``app/static/js/mock/server_api.js``, ``foods.js``, ``barcode.js``, ``ai.js``).

``tests/js/server_services.mjs`` runs the page against a stand-in for the iPhone app and a fake of the server's gateway: the two
kinds of token, food lookups through the server and the phone's own keys when it cannot help, the AI's choice (the server, then
the iPhone's own, then none), that only an unreachable server or a 503/404 moves on, that a safety answer is never asked again
elsewhere, that lab text goes only to the lab routes, and that the server's food ids become the phone's. Here it runs, and the
module is checked for what it must never do.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_the_page_uses_the_servers_services_by_the_notes_rules():
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "server_services.mjs")], capture_output=True, text=True, timeout=300,
                          check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server services:" in done.stdout and "checks passed" in done.stdout


def test_the_module_is_device_mode_only_and_has_no_network_of_its_own():
    code = (STATIC / "js" / "mock" / "server_api.js").read_text(encoding="utf-8")
    assert "KH.flags.DEVICE !== true" in code
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "Authorization", "khd_", "localStorage", "indexedDB", "api_key"):
        assert word not in code, word
    assert "window.webkit.messageHandlers.bridge" in code and "kind: 'serverApi'" in code
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="js/mock/device.js"') < html.index('src="js/mock/server_api.js"') < html.index('src="js/mock/seed.js"')
    assert "'/js/mock/server_api.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_only_a_failure_moves_the_ai_on_and_never_to_a_cloud_model():
    """Note 39 D2 and D3: the next step of the choice runs only when the server could not be reached or answered 503 or 404; lab
    text goes to the server's lab route or the iPhone's own model, nothing else; the AI is never given a dosing task."""
    ai = (STATIC / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
    via = ai[ai.index("async function viaServer("):ai.index("// A body for the server")]
    assert "if (res.offline || res.error) { forgetServer(); return { skip: 'unreachable' }; }" in via
    assert "if (res.status === 503 || res.status === 404) { forgetServer(); return { skip: 'not_available' }; }" in via
    assert "return KH.mock.serverApi.failWith(res);" in via  # every other answer is the server's, shown as it is
    assert len(re.findall(r"skip: '", via)) == 3
    # the lab text has one way to the server: its lab route
    assert ai.count("read-lab-report-text") == 4  # two comments, the route, and the one request to the server
    assert "'labs', 'POST', `/api/ai/read-lab-report-text${query(qp)}`, { body: { text: body.text, page } }" in ai
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", ai, flags=re.S).lower()
    for word in ("insulin", "bolus", "dosing"):
        assert word not in code, word
    # nothing warns against or blocks a low: the safety answers are passed on untouched
    api = (STATIC / "js" / "mock" / "server_api.js").read_text(encoding="utf-8")
    assert "if (isDict(answer) && SAFETY.has(answer.status)) return answer;" in api


def test_recipe_pages_instacart_and_the_list_app_go_through_the_server_only_when_it_offers_them():
    """Note 39 §7, step 9 (``tests/js/server_lists.mjs``): off with no server both ways, as on a server with them off; through the
    gateway when the server offers them; a page's lines matched with the phone's foods; the server's food ids shown as the phone's
    and sent back as the server's; the list app never set up from the phone; pasted ingredients stay on the phone."""
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "server_lists.mjs")], capture_output=True, text=True, timeout=300,
                          check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "server lists:" in done.stdout and "checks passed" in done.stdout
    code = (STATIC / "js" / "mock" / "lists.js").read_text(encoding="utf-8")
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "Authorization", "khd_", "localStorage", "indexedDB"):
        assert word not in code, word
    # the device-mode branch asks only routes on the server's gateway list, and never the list app's set-up or pasted text
    from app.app_gateway import ALLOWED

    asked = set(re.findall(r"(?:viaServer|serverStatus)\('\w+', (?:'(GET|POST)', )?'(/api/[^']+)'", code))
    assert len(asked) == 8 and {(m or "GET", p) for m, p in asked} <= ALLOWED
    assert "/api/recipe-import/text" not in {p for _, p in asked}
