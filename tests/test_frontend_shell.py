"""The static frontend shell: CSP-clean markup and scripts, the module layout, the service worker's
shell list, the web app manifest and the committed icons (notes 01 §5.5 and 02 R1–R4, R11).

Server-side PWA behaviour (/sw.js versioning, headers, public paths) is tested with app/pwa.py.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
HEAD, BODY = INDEX.split("</head>", 1)
SCRIPTS = sorted(p for p in STATIC.rglob("*.js") if "vendor" not in p.parts)


def _png(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    assert data[12:16] == b"IHDR"
    width, height, _depth, colour = struct.unpack(">IIBB", data[16:26])
    return width, height, colour


def _tags(html: str, name: str) -> list[str]:
    return re.findall(rf"<{name}\b[^>]*>", html, re.I)


def _local_refs() -> list[str]:
    """Every same-origin file index.html loads (stylesheets, scripts, icons, manifest)."""
    refs = re.findall(r'<(?:script|link)\b[^>]*\b(?:src|href)="([^"]+)"', INDEX)
    return [r for r in refs if not re.match(r"^(?:[a-z]+:|//)", r)]


# --------------------------------------------------------------------------- CSP
def test_index_has_no_inline_script_style_or_handlers() -> None:
    for tag in _tags(INDEX, "script"):
        assert re.search(r"\bsrc=", tag), f"inline script: {tag}"
    assert not re.search(r"<style\b", INDEX, re.I), "inline <style> element"
    assert not re.search(r"\sstyle\s*=", INDEX, re.I), "style attribute in index.html"
    assert not re.search(r"\son[a-z]+\s*=", INDEX, re.I), "inline event handler attribute"
    assert "javascript:" not in INDEX
    assert "data:image" not in INDEX, "data: favicon (img-src has no data:)"


def test_scripts_use_no_html_sinks() -> None:
    """Under `require-trusted-types-for 'script'` these throw; the app builds DOM with KH.h / textContent."""
    sinks = re.compile(r"\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function\s*\(|"
                       r"setAttribute\(\s*['\"](?:style|on\w+)['\"]|createContextualFragment|parseFromString|\.srcdoc\b|"
                       r"set(?:Timeout|Interval)\(\s*['\"`]")
    for path in SCRIPTS:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not sinks.search(line), f"{path.relative_to(ROOT)}:{n}: {line.strip()}"


def test_only_pwa_js_creates_a_trusted_types_policy_and_only_for_sw_js() -> None:
    owners = [p for p in SCRIPTS if "createPolicy" in p.read_text(encoding="utf-8")]
    assert owners == [STATIC / "js" / "pwa.js"]
    pwa = (STATIC / "js" / "pwa.js").read_text(encoding="utf-8")
    assert pwa.count("createPolicy(") == 1 and "createPolicy('kh-sw'" in pwa
    assert "'default'" not in pwa and "allow-duplicates" not in pwa
    assert "if (url === SW_URL) return url; throw new TypeError" in pwa
    assert "const SW_URL = '/sw.js';" in pwa
    # registered only in the installed app over a secure context, never in the demo / preview
    assert "!MOCK && window.isSecureContext === true && 'serviceWorker' in navigator" in pwa


# --------------------------------------------------------------------------- module layout
def test_module_layout_and_load_order() -> None:
    body_scripts = re.findall(r'<script src="([^"]+)"', BODY)
    # the engine twins (pure, no DOM) come first, then core.js
    engines = [s for s in body_scripts if s.startswith("js/engine/")]
    assert body_scripts[: len(engines) + 1] == [*engines, "js/core.js"]
    assert engines[:2] == ["js/engine/rules.js", "js/engine/targets.js"] and "js/engine/settings.js" in engines
    assert body_scripts[-2:] == ["js/pwa.js", "js/main.js"]
    mocks = [s for s in body_scripts if s.startswith("js/mock/")]
    views = [s for s in body_scripts if s.startswith("js/views/")]
    assert mocks[0] == "js/mock/core.js" and mocks[-1] == "js/mock/seed.js"
    assert body_scripts.index(mocks[-1]) < body_scripts.index(views[0])
    assert set(views) >= {f"js/views/{v}.js" for v in ("today", "add", "plan", "trends", "profile", "auth", "settings")}
    assert set(mocks) >= {"js/mock/auth.js", "js/mock/settings.js"}
    assert re.search(r'<script src="js/pwa.js" data-preview="omit"></script>', BODY)
    styles = re.findall(r'<link rel="stylesheet" href="([^"]+)">', HEAD)
    assert styles[0] == "css/base.css" and styles[-1] == "css/touch.css"
    assert re.findall(r'<script src="([^"]+)"', HEAD) == ["theme-init.js"]
    assert not (STATIC / "app.js").exists() and not (STATIC / "style.css").exists()
    for path in SCRIPTS:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(?:import|export)\s", text, re.M), f"{path.name}: plain scripts only (no ES modules)"


def test_every_referenced_file_exists() -> None:
    for ref in _local_refs():
        assert (STATIC / ref.lstrip("/")).is_file(), ref


def test_api_client_marks_writes_and_hands_401_to_auth() -> None:
    core = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
    assert "if (method !== 'GET' && method !== 'HEAD') headers['X-Requested-With'] = 'kidney-health';" in core
    # one error path for the server and the demo API (afterError): 401 → sign-in screen,
    # reauth_required → password prompt and one retry, password_change_required, setup_required
    assert "if (err.status === 401 && !opts.quiet401)" in core and "KH.auth.onUnauthorized(err)" in core
    assert "data.reauth_required && !opts.retried" in core and "KH.auth.reauth(err)" in core
    assert "return retry({ ...opts, retried: true });" in core
    assert "data.password_change_required" in core and "data.setup_required" in core
    assert core.count("return afterError(") >= 3  # fetch, demo API and download all use it


# --------------------------------------------------------------------------- PWA head, service worker, manifest, icons
def test_head_has_the_install_tags_and_not_the_deprecated_ones() -> None:
    assert '<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">' in HEAD
    assert '<link rel="icon" href="/icons/icon.svg" type="image/svg+xml">' in HEAD
    assert '<link rel="icon" href="/icons/icon-192.png" sizes="192x192" type="image/png">' in HEAD
    assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in HEAD
    assert '<meta name="apple-mobile-web-app-title" content="Kidney Log">' in HEAD
    assert len(re.findall(r'<meta name="theme-color"', HEAD)) == 2
    assert "viewport-fit=cover" in HEAD
    for deprecated in ("apple-mobile-web-app-capable", "mobile-web-app-capable", "apple-mobile-web-app-status-bar-style", "apple-touch-startup-image"):
        assert deprecated not in HEAD


def test_service_worker_template_caches_exactly_the_shell() -> None:
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "const VERSION = '__VERSION__';" in sw
    m = re.search(r"const SHELL_URLS = (\[.*?\]);", sw, re.S)
    assert m, "SHELL_URLS not found"
    shell = json.loads(m.group(1).replace("'", '"').replace(",\n]", "\n]"))
    expected = {"/"} | {"/" + r.lstrip("/") for r in _local_refs()}  # the page and everything it loads
    assert set(shell) == expected
    assert len(shell) == len(set(shell))
    for url in shell:
        assert url == "/" or (STATIC / url.lstrip("/")).is_file(), url
    # personal data never enters Cache Storage; navigations elsewhere are not answered with the shell
    assert "url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;" in sw
    assert "req.method !== 'GET'" in sw and "url.origin !== self.location.origin" in sw
    assert "if (url.pathname !== '/' && url.pathname !== '/index.html') return;" in sw
    assert "url.searchParams.has('reauth')" in sw
    # an update waits for the person's Reload: skipWaiting only on the page's SKIP_WAITING message
    assert sw.count("self.skipWaiting()") == 1 and "if (event.data === 'SKIP_WAITING') self.skipWaiting();" in sw


def test_manifest() -> None:
    m = json.loads((STATIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert m["id"] == m["start_url"] == m["scope"] == "/"
    assert m["display"] == "standalone"
    assert m["name"] == "Kidney Diet Log" and m["short_name"] == "Kidney Log"
    assert m["theme_color"] == m["background_color"] == "#f4f5f7"
    by_purpose: dict[str, set[int]] = {}
    for icon in m["icons"]:
        path = STATIC / icon["src"].lstrip("/")
        assert path.is_file(), icon["src"]
        if icon["type"] == "image/png":
            size = int(icon["sizes"].split("x")[0])
            assert icon["sizes"] == f"{size}x{size}"
            width, height, colour = _png(path)
            assert (width, height) == (size, size), icon["src"]
            if icon["purpose"] == "maskable":
                assert colour == 2, f"{icon['src']}: a maskable icon must be opaque RGB"
            by_purpose.setdefault(icon["purpose"], set()).add(size)
    assert by_purpose == {"any": {192, 512}, "maskable": {192, 512}}
    for shortcut in m["shortcuts"]:
        assert shortcut["url"] in ("/#add", "/#plan")


def test_apple_touch_icon_is_opaque_180() -> None:
    assert _png(STATIC / "apple-touch-icon.png") == (180, 180, 2)


def test_icon_sources_and_build_script_agree() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_icons", ROOT / "scripts" / "build_icons.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # importing needs no Playwright; only render() does
    assert module.check() == []
    for src in ("icon.svg", "icon-maskable.svg"):
        svg = (STATIC / "icons" / src).read_text(encoding="utf-8")
        assert svg.startswith("<svg") and "#2e7d32" in svg
    assert "playwright==" in (ROOT / "requirements-tools.txt").read_text(encoding="utf-8")
    assert "playwright" not in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").lower()
