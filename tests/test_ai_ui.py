"""The AI frontend (``app/static/js/views/ai.js``, ``css/ai.css``, ``js/mock/ai.js``) against the server
contract: the sheets and the Add view slot exist, every API call it makes is a real route with that
method, the demo answer for ``GET /api/me/ai`` has the server's keys, model text is never put into
the page as HTML, and the photo is redrawn on the device before upload. Browser behaviour itself was
checked by hand in Chromium (see docs/dev/progress/ai.md); these tests keep the contract from
drifting."""
from __future__ import annotations

import re
from pathlib import Path

from conftest import HTTPS_URL, TestClient, make_settings, sign_in
from app.config import AiEnv
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
MOCK_JS = (STATIC / "js" / "mock" / "ai.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_the_sheets_the_add_slot_and_the_files_are_in_the_shell():
    for element in ('id="sheet-ai"', 'id="sheet-ai-consent"', 'id="sheet-ai-sent"', 'id="ai-add-slot"'):
        assert element in INDEX, element
    assert '<link rel="stylesheet" href="css/ai.css">' in INDEX
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/ai.js") > scripts.index("js/views/settings.js")  # uses KH.views.settings.keyWidget
    assert scripts.index("js/mock/ai.js") < scripts.index("js/mock/seed.js")
    settings_js = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "h('div', { id: 'set-ai-slot' })" in settings_js and "body.dataset.filled" in settings_js  # the slot ai.js fills


def _calls() -> set[tuple[str, str]]:
    """(method, path template) of every request ai.js makes."""
    raw = re.findall(r"request\('(GET|POST|PUT|PATCH|DELETE)', `([^`]+)`", AI_JS)
    raw += re.findall(r"request\('(GET|POST|PUT|PATCH|DELETE)', '([^']+)'", AI_JS)
    calls = set()
    for method, path in raw:
        path = re.sub(r"\$\{dry[^}]*\}", "", path).split("?")[0]  # the ?dry_run=true suffix
        calls.add((method, re.sub(r"\$\{[^}]+\}", "{id}", path)))
    if "fetch(`/api/vision/${kind}" in AI_JS:  # photos: the raw JPEG upload
        calls |= {("POST", "/api/vision/label"), ("POST", "/api/vision/plate")}
    return calls


def test_every_call_is_a_real_route(tmp_path, foods_json):
    app = create_app(make_settings(tmp_path, foods_json))
    routes = {}
    for path, item in app.openapi()["paths"].items():
        routes[re.sub(r"\{[^}]+\}", "{id}", path)] = {m.upper() for m in item}
    calls = _calls()
    assert len(calls) >= 20
    for method, path in sorted(calls):
        assert path in routes and method in routes[path], (method, path)


def test_the_demo_answer_has_the_servers_keys(tmp_path, foods_json):
    settings = make_settings(tmp_path, foods_json, ai=AiEnv(provider="openai", api_key="sk-env-0123456789abcdefghijklmn", model="gpt-6-luna"))
    with TestClient(create_app(settings), base_url=HTTPS_URL) as c:
        sign_in(c)
        server = c.get("/api/me/ai").json()
    block = MOCK_JS[MOCK_JS.index("route('GET', '/api/me/ai'"):]
    block = block[block.index("return {") + len("return {"):block.index("    };")]
    mock_keys = set(re.findall(r"^\s{6}([a-z_]+):", block, re.M))
    assert mock_keys == set(server), (mock_keys ^ set(server))
    assert "enabled: false" in block  # the demo is a server with AI off
    settings_keys = set(re.findall(r"([a-z_]+):", block[block.index("settings: {"):block.index("},", block.index("settings: {"))]))
    assert settings_keys - {"settings"} == set(server["settings"])


def test_model_text_reaches_the_page_as_text_only():
    # The shell test bans HTML sinks everywhere; here: no URL from an answer becomes a link unless the
    # handbook module checked it (KH.learn.href), and links open safely.
    assert "innerHTML" not in AI_JS and "insertAdjacentHTML" not in AI_JS
    for href in re.findall(r"href: ([^,}]+)", AI_JS):
        assert href.strip() in ("target",), href
    assert "KH.learn.href(page.url)" in AI_JS and "rel: 'noopener'" in AI_JS


def test_photos_are_redrawn_on_the_device_before_upload():
    assert "PHOTO_EDGE = 1600" in AI_JS and "PHOTO_QUALITY = 0.85" in AI_JS
    assert "toBlob(" in AI_JS and "'image/jpeg'" in AI_JS
    assert "'Content-Type': 'image/jpeg'" in AI_JS and "'X-Requested-With': 'kidney-health'" in AI_JS
    assert "URL.revokeObjectURL" in AI_JS  # the preview's object URL is released


def test_consent_and_preview_flow_is_wired():
    # 409 consent_required → the consent sheet → POST /api/ai/consent → one retry; skip_preview false → preview first.
    assert "err.status === 409 && err.data && err.data.consent_required" in AI_JS
    assert "skip_preview: !showEach.checked" in AI_JS and "!given.skip_preview" in AI_JS
    # nothing is logged without a tap: every write goes through the ordinary routes from a button handler
    assert AI_JS.count("api.logBatch(") >= 3 and "api.createFood(" in AI_JS


def test_ai_activity_names_every_status_the_server_records() -> None:
    """AI activity printed the raw word for a status it had no text for; ``cached`` (the same question within 10
    minutes answered without a new call, app/ai/routes.py) is the newest. ``error:<code>`` reads "failed (…)"."""
    routes = (ROOT / "app" / "ai" / "routes.py").read_text(encoding="utf-8")
    recorded = set(re.findall(r'\bstatus\s*=\s*"([a-z_]+)"', routes)) - {"error"}
    texts = re.search(r"const STATUS_TEXT = \{(.*?)\};", AI_JS, re.S)
    assert texts, "STATUS_TEXT not found"
    known = set(re.findall(r"(\w+):", texts.group(1)))
    assert recorded and recorded <= known, recorded - known
    assert "cached: 'reused (the same question within 10 minutes; no new AI call)'" in AI_JS
