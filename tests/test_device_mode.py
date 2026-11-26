"""Device mode (design note 38, step 1): the web app packed inside the iPhone app.

``scripts/build_preview.py --device`` writes the Pages demo's static site with ``device-flag.js`` instead of the demo's flag. The
app then starts empty, keeps its data on the phone from the first start, has one person who is not an admin, shows no demo
banner, and hands the iPhone app a safety copy after each save. ``tests/js/device_mode.mjs`` runs the engine side against a fake
IndexedDB; this file checks the build and runs that script.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    return builder


def test_the_engine_in_device_mode():
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "device_mode.mjs")], capture_output=True, text=True, timeout=180, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "device mode:" in done.stdout and "checks passed" in done.stdout


def test_the_device_build_is_the_pages_site_in_device_mode(tmp_path):
    builder = _builder()
    files = builder.build_device(tmp_path)
    names = {f.relative_to(tmp_path).as_posix() for f in files}
    assert "device-flag.js" in names and "preview-flag.js" not in names and "index.html" in names
    flag = (tmp_path / "device-flag.js").read_text(encoding="utf-8")
    assert "window.KDL_PREVIEW = true;" in flag and "window.KDL_DEVICE = true;" in flag
    assert '"url": "https://ksullivan86.github.io/kidney-health/"' in flag
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "(demo)</title>" not in page
    assert page.index('<script src="device-flag.js">') < page.index('<script src="js/core.js">')
    # the app's own CSP, as in the Pages demo, and no inline script: every <script> has a src, or is the food list's JSON
    assert '<meta http-equiv="Content-Security-Policy" content="' in page and "connect-src 'self'" in page
    for tag in re.findall(r"<script\b[^>]*>", page, flags=re.I):  # any case: browsers read <SCRIPT> too
        assert "src=" in tag or 'type="application/json"' in tag, tag
    # Learn links leave the app for the published handbook (opened in Safari); nothing points at a server path
    assert 'href="/learn/' not in page and 'href="https://ksullivan86.github.io/kidney-health/' in page
    assert not re.findall(r'(?:href|src)="/[^"]*"', page)


def test_device_mode_is_wired_only_where_it_should_be():
    static = ROOT / "app" / "static" / "js"
    core = (static / "core.js").read_text(encoding="utf-8")
    assert "const DEVICE = PREVIEW && window.KDL_DEVICE === true;" in core  # never on a real server's page
    main = (static / "main.js").read_text(encoding="utf-8")
    assert "if (MOCK && !DEVICE) {" in main and "KH.mock.start({ hemodialysis: MOCK_HD, seed: !DEVICE })" in main
    persist = (static / "mock" / "persist.js").read_text(encoding="utf-8")
    assert "window.webkit.messageHandlers.safetyCopy" in persist and "fetch(" not in persist
    demo = (static / "views" / "demo_local.js").read_text(encoding="utf-8")
    assert "if (flags.DEVICE) return;" in demo


def test_the_first_start_setup_and_the_tidy_settings_are_device_only():
    """The owner's feedback on TestFlight build 5 (2026-11-21): a simple setup at the first start, with the optional server; the
    sample data only as a choice; and Settings without the parts that need a server."""
    static = ROOT / "app" / "static"
    welcome = (static / "js" / "views" / "welcome.js").read_text(encoding="utf-8")
    assert "if (!flags.DEVICE) {" in welcome and "innerHTML" not in welcome
    for step in ("Welcome to Kidney Health", "About you", "Your own server (optional)", "You are set"):
        assert step in welcome, step
    assert "KH.mock.local.restart({ sample: true })" in welcome  # the sample data is a choice, never the default
    # Owner, 2026-11-21 and 2026-11-25: the server step says what a server adds (the log both ways, the server's AI and keys),
    # all of it built since note 39, and nothing is promised as "coming later".
    server = welcome[welcome.index("function stepServer()"):welcome.index("function stepDone()")]
    assert "Your log on all your devices." in server and "Your server\\'s AI, and the keys" in server
    assert "later:" not in server.lower() and "coming later" not in server.lower()
    assert 'Make a token for "The iPhone app, both ways"' in server and "scan its QR code" in server
    index = (static / "index.html").read_text(encoding="utf-8")
    assert '<dialog id="sheet-welcome"' in index and '<script src="js/views/welcome.js"></script>' in index
    assert "'/js/views/welcome.js'," in (static / "sw.js").read_text(encoding="utf-8")
    main = (static / "js" / "main.js").read_text(encoding="utf-8")
    assert "if (DEVICE && KH.welcome) KH.welcome.maybeShow()" in main and "classList.add('device-mode')" in main
    css = (static / "css" / "base.css").read_text(encoding="utf-8")
    hidden = css[css.index(".device-mode #set-care"):]
    for section in ("#set-care", "#set-connected", "#set-lists", "#set-assistant", "#set-push", "#install-panel"):
        assert f".device-mode {section}" in hidden, section
    assert ".device-mode #set-reminders" not in css  # the iPhone's own notifications (design note 35 §7)
    settings = (static / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "if (sec.hidden || DEVICE_LEFT_OUT.has(sec.id)) continue;" in settings
    assert "id: 'set-start-empty'" in settings and "id: 'set-start-sample'" in settings and "id: 'set-run-setup'" in settings
