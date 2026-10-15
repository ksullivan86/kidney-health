"""Static checks of "Keep my data in this browser" (the Pages demo keeps its data in IndexedDB when the person chooses):
the wording of the opt-in sheet, no inline script or style, and that the mode can only be reached in the demo build.
The storage layer itself is run against a fake IndexedDB by ``tests/js/demo_local_storage.mjs`` (tests/test_demo_local_storage.py)
and the import by the vectors (tests/test_import_vectors.py); the browser walk is ``tools/e2e/demo_local.py``."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "demo_local.js").read_text(encoding="utf-8")
PERSIST = (STATIC / "js" / "mock" / "persist.js").read_text(encoding="utf-8")
EXPORT = (STATIC / "js" / "mock" / "export.js").read_text(encoding="utf-8")
IMPORT = (STATIC / "js" / "mock" / "import.js").read_text(encoding="utf-8")
MAIN = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
SETTINGS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
SHEET = INDEX[INDEX.index('<dialog id="sheet-demo-local"'):INDEX.index("</dialog>", INDEX.index('<dialog id="sheet-demo-local"'))]
BODY_SCRIPTS = re.findall(r'<script src="([^"]+)"', INDEX)


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# --------------------------------------------------------------------------- the sheet says it plainly, and asks first
def test_the_sheet_says_where_the_data_lives_and_how_it_can_be_lost():
    said = text_of(SHEET)
    for sentence in (
        "Your data stays only in this browser, on this device. Nothing is sent anywhere.",
        "Clearing site data, private browsing, or the browser deciding to free up space can delete it.",
        "Export it regularly",
        "On a shared device, other people who use this browser can see it.",
        "For real use, run your own server",
        "I understand",
        "Stop keeping data here",
    ):
        assert sentence in said, sentence
    assert "Keep my data in this browser" in said


def test_nothing_is_on_by_default_and_turning_it_on_needs_i_understand():
    assert re.search(r'<input type="checkbox" id="dl-understand">', SHEET)  # not checked
    assert re.search(r'<button class="btn primary" type="button" id="dl-enable" disabled>', SHEET)  # disabled until it is ticked
    assert "enableBtn.disabled = busy || !understand.checked" in VIEW
    assert "if (busy || !understand.checked) return;" in VIEW  # and the handler checks again
    assert 'id="preview-banner-keep" hidden>' in INDEX  # the banner button shows only in the demo build
    # the stop button asks in the page first (no browser dialog) and says what happens
    assert "KH.confirm.inline(foot, stopBtn" in VIEW and "window.confirm" not in VIEW and "confirm(" not in VIEW.replace("KH.confirm.inline(", "")
    assert "cannot be undone" in VIEW and "starts again with its sample data" in VIEW
    assert "navigator.storage.persist" in PERSIST  # persistent storage is asked for when it is turned on, and the answer is shown
    assert "PERSIST_TEXT" in VIEW and "has not agreed to keep this data for good" in VIEW


def test_a_browser_without_storage_is_told_so_and_the_demo_stays_in_memory():
    assert "This browser does not let this page store data" in PERSIST and "The demo stays in memory: nothing is saved." in PERSIST
    assert "problem.textContent = why;" in VIEW and "!!s.unavailable" in VIEW  # the button is off while storage is unavailable


# --------------------------------------------------------------------------- CSP: no inline script or style, text only
def test_no_inline_script_style_or_handler_in_the_new_markup():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)  # the page's only scripts are files
    assert not re.search(r"\sstyle\s*=", SHEET, re.IGNORECASE) and not re.search(r"<style", INDEX, re.IGNORECASE)
    assert not re.search(r"\son[a-z]+\s*=", SHEET, re.IGNORECASE)
    assert not re.search(r"javascript:", SHEET, re.IGNORECASE)
    banner = INDEX[INDEX.index('<div class="preview-banner"'):INDEX.index("</div>", INDEX.index('<div class="preview-banner"'))]
    assert not re.search(r"\sstyle\s*=|\son[a-z]+\s*=", banner, re.IGNORECASE)


def test_text_from_storage_or_a_file_is_drawn_as_text_only():
    for name, code in (("views/demo_local.js", VIEW), ("mock/persist.js", PERSIST)):
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on", "localStorage", "sessionStorage",
                       "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "importScripts", "document.cookie"):
            assert banned not in code, f"{name}: {banned}"
    assert "textContent" in VIEW and "indexedDB" not in VIEW  # the view draws; the storage is persist.js only


# --------------------------------------------------------------------------- the mode is reachable only in the demo build
def test_only_the_storage_file_opens_a_database_for_this():
    stores = {path.relative_to(STATIC).as_posix() for path in (STATIC / "js").rglob("*.js") if "indexedDB" in path.read_text(encoding="utf-8")}
    assert stores == {"js/offline.js", "js/pwa.js", "js/mock/persist.js"}
    assert "indexedDB" not in EXPORT and "indexedDB" not in IMPORT and "indexedDB" not in SETTINGS and "indexedDB" not in MAIN


def test_the_mode_is_off_unless_this_is_the_demo_build():
    # the gate: the flag the Pages build and the preview set, never ?mock=1 on a development server and never the installed app
    assert re.search(r"function allowed\(\) \{ return !!\(KH\.flags && KH\.flags\.PREVIEW === true && M\.instance\); \}", PERSIST)
    for fn in ("boot", "probe", "enable"):
        assert re.search(rf"async function {fn}\([^)]*\) \{{\s*(?:\n\s*)?if \(!allowed\(\)\)", PERSIST), fn
    assert "M.onWrite = (api, method, path) => { if (st.on && api === M.instance && !ASKS_ONLY.test(path)) scheduleSave(); };" in PERSIST  # only while the mode is on
    assert "if (!flags.MOCK || flags.PREVIEW !== true || !L) {" in VIEW and "KH.demoLocal = { init() {}, on: () => false" in VIEW
    # main.js starts it inside the demo branch only
    assert "if (MOCK && KH.mock.local) await KH.mock.local.boot();" in MAIN and "if (MOCK && KH.demoLocal) KH.demoLocal.init();" in MAIN
    # the Settings entry point exists only for the online demo
    assert "if (MOCK && PREVIEW && KH.demoLocal && KH.demoLocal.open) {" in SETTINGS
    # the demo API, not the real one, is what the mode saves: the hook lives in the mock's request()
    core = (STATIC / "js" / "mock" / "core.js").read_text(encoding="utf-8")
    assert "KH.mock.onWrite(this, method, path)" in core and "KH.mock.onWrite" not in (STATIC / "js" / "core.js").read_text(encoding="utf-8")


def test_the_scripts_load_in_an_order_that_works_and_the_service_worker_lists_them():
    pos = {src: BODY_SCRIPTS.index(src) for src in BODY_SCRIPTS}
    assert pos["js/mock/ai.js"] < pos["js/mock/export.js"] < pos["js/mock/import.js"] < pos["js/mock/persist.js"] < pos["js/mock/seed.js"]
    assert pos["js/views/settings.js"] < pos["js/views/demo_local.js"] < pos["js/main.js"]
    assert pos["js/mock/seed.js"] < pos["js/views/demo_local.js"]  # KH.mock.local exists when the view loads
    for url in ("/css/demo-local.css", "/js/mock/export.js", "/js/mock/import.js", "/js/mock/persist.js", "/js/views/demo_local.js"):
        assert f"'{url}'," in SW, url
    assert '<link rel="stylesheet" href="css/demo-local.css">' in INDEX


def test_the_preview_build_carries_the_sheet_and_the_scripts_and_still_makes_no_request():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_preview
    finally:
        sys.path.pop(0)
    fragment = build_preview.build_fragment()
    assert 'id="sheet-demo-local"' in fragment and "KH.mock.local" in fragment and "KH.demoLocal" in fragment
    assert not re.search(r"<script[^>]*\ssrc\s*=", fragment, re.IGNORECASE)  # every script is inlined: nothing is fetched


# --------------------------------------------------------------------------- the data stays what the server's export is
def test_the_harness_lists_the_servers_export_keys():
    import ast
    import inspect

    from app import account

    tree = ast.parse(inspect.getsource(account.export_data))
    returned = next(node for node in ast.walk(tree) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict))
    server_keys = [key.value for key in returned.value.keys if isinstance(key, ast.Constant)]
    harness = (ROOT / "tools" / "e2e" / "demo_local.py").read_text(encoding="utf-8")
    listed = re.search(r"EXPORT_KEYS = \[(.*?)\]", harness, re.S)
    assert listed and re.findall(r'"([a-z_]+)"', listed.group(1)) == server_keys


def test_the_export_route_and_the_download_name():
    assert "route('GET', '/api/me/export.json'" in EXPORT and "kidney-health-export" in EXPORT
    assert "const FILE_NAME = 'export.json';" in VIEW and "type: 'application/json'" in VIEW
    assert "route('POST', '/api/me/import'" in IMPORT
    # settings: the export and the import are the mode's, the zip stays the installed app's
    assert "if (MOCK && keptHere()) {" in SETTINGS and "if (MOCK && !(KH.demoLocal && KH.demoLocal.on())) {" in SETTINGS
