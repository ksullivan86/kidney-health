""""The app did not start" (index.html #boot-fail): every view stays hidden until the scripts boot, so a script that never
arrives (a VPN dropping large packets) or throws used to leave only the header. The notice needs no script to show: CSS
reveals it after 8 seconds, and js/main.js hides it once a screen shows, or shows it at once with the reason.

tests/js/boot_fail.test.mjs runs main.js itself; tools/e2e/boot_fail.py checks it in Chromium with the main script blocked.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
BASE_CSS = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
THEME_INIT = (STATIC / "theme-init.js").read_text(encoding="utf-8")
ANCHOR = "only-the-header-shows-over-a-vpn"


def _notice() -> str:
    m = re.search(r'<section class="boot-fail" id="boot-fail"[^>]*>.*?</section>', INDEX, re.S)
    assert m, "index.html has no #boot-fail section"
    return m.group(0)


def _rule(selector: str) -> str:
    m = re.search(rf"(?m)^{re.escape(selector)} \{{(.*?)\}}", BASE_CSS, re.S)
    assert m, f"base.css has no rule for {selector}"
    return m.group(1)


def test_the_notice_is_in_the_page_before_any_view_and_needs_no_script():
    notice = _notice()
    opening = notice.split(">", 1)[0]
    assert " hidden" not in opening, "the hidden attribute would keep it hidden without script; CSS hides it at first"
    main = INDEX.index('<main id="main"')
    assert main < INDEX.index('id="boot-fail"') < INDEX.index('id="view-auth"') < INDEX.index("<script src=\"js/")
    assert 'aria-labelledby="boot-fail-title"' in opening and '<h2 id="boot-fail-title">The app did not start</h2>' in notice
    assert "<p id=\"boot-fail-reason\">The app's files did not finish loading. Try reloading.</p>" in notice
    assert "NetBird, Tailscale or WireGuard" in notice and "dropping large files" in notice
    # A plain link reloads (no script), and one explains what to change on the server.
    assert '<a class="btn primary" id="boot-fail-reload" href="/">Reload</a>' in notice
    assert f'href="/learn/self-hosting/troubleshooting/#{ANCHOR}"' in notice
    assert not re.search(r"<(?:script|button)\b|\son[a-z]+\s*=", notice)


def test_css_hides_it_at_first_and_shows_it_after_8_seconds_without_a_fade():
    rule = _rule(".boot-fail")
    assert "visibility: hidden;" in rule
    # A zero-length animation after an 8 s delay that holds its end: a step. !important beats the reduced-motion rule.
    assert "animation: kh-boot-fail-show 0s linear 8s forwards !important;" in rule
    assert re.search(r"@media \(prefers-reduced-motion: reduce\) \{\s*\* \{[^}]*animation: none !important;", BASE_CSS)
    keyframes = re.search(r"@keyframes kh-boot-fail-show \{(.*?)\}\s*$", BASE_CSS, re.S | re.M)
    assert keyframes and keyframes.group(1).strip() == "to { visibility: visible; }"
    assert "opacity" not in rule and "transition" not in rule and "display" not in rule  # [hidden] still wins
    now = _rule(".boot-fail.boot-fail-now")
    assert "visibility: visible;" in now and "animation: none !important;" in now
    assert "[hidden] { display: none !important; }" in BASE_CSS


def test_boot_hides_it_once_a_screen_shows_and_shows_the_reason_when_boot_fails():
    assert "const notice = document.getElementById('boot-fail');" in MAIN_JS
    booted = MAIN_JS[MAIN_JS.index("function booted()"):MAIN_JS.index("function bootFailed(")]
    assert "notice.hidden = true;" in booted
    failed = MAIN_JS[MAIN_JS.index("function bootFailed("):MAIN_JS.index("  try {")]
    assert "The app could not start: ${reason}. Try reloading." in failed
    assert "notice.classList.add('boot-fail-now');" in failed and "notice.hidden = false;" in failed
    assert "window.KDL_BOOT_ERROR" in failed and "textContent" in failed and "innerHTML" not in failed
    # The whole boot is guarded, and boot's result decides: both the sign-in screen and the first view count as started.
    assert "init().then(booted, bootFailed);" in MAIN_JS
    assert MAIN_JS.rstrip().endswith("} catch (err) {\n    bootFailed(err);\n  }\n})();")
    assert "if (!KH || !KH.flags || !KH.auth) throw new Error(" in MAIN_JS
    # The first script error of the page is kept from the start (theme-init.js runs in <head>, before any other script).
    assert "window.addEventListener('error'" in THEME_INIT and "window.KDL_BOOT_ERROR = String(e.message)" in THEME_INIT


def test_the_pages_demo_keeps_both_links_relative(tmp_path):
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.build_pages(tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<a class="btn primary" id="boot-fail-reload" href="./">Reload</a>' in html
    assert f'href="../self-hosting/troubleshooting/#{ANCHOR}"' in html
    fragment = builder.build_fragment()
    assert 'id="boot-fail"' in fragment and "kh-boot-fail-show" in fragment


def test_the_troubleshooting_pages_explain_the_vpn_case():
    guide = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
    section = guide[guide.index("### Only the header shows over a VPN"):]
    script = re.search(r"https://<address>(/js/[\w/]+\.js)", section)
    assert script, "the guide's curl check names a script file"
    assert (STATIC / script.group(1).lstrip("/")).stat().st_size > 100_000, "check with a large file"
    assert "--clamp-mss-to-pmtu" in section and "maxseg size set rt mtu" in section and "netbird up --mtu" in section
    assert "ALLOWED_HOSTS" in section and "Clear offline data on this device" in section
    page = (ROOT / "handbook" / "docs" / "self-hosting" / "troubleshooting.md").read_text(encoding="utf-8")
    assert "## Only the header shows over a VPN" in page
    assert f"docs/deployment.md#{ANCHOR}" in page
    assert "iptables" not in page and "curl " not in page  # commands live in the guide
