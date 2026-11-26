"""Withings and Whoop from the iPhone app (owner, 2026-11-26: "Should Withings and Whoop be set up from the phone?" "yes").

``tests/js/phone_devices.mjs`` runs the page's side (``js/mock/devices.js`` and ``activity.js`` in device mode) against a stand-in
app. Here: it passes, and the screens, the app's Swift side and the relay page keep their rules.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_the_page_side_against_a_stand_in_app() -> None:
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "phone_devices.mjs")], capture_output=True, text=True, timeout=300,
                          cwd=ROOT)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["ok"] is True and out["checks"] >= 40


def test_connected_devices_shows_on_the_phone() -> None:
    css = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    assert ".device-mode #set-connected" not in css
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    left_out = settings[settings.index("const DEVICE_LEFT_OUT"):settings.index("function renderNav()")]
    assert "set-connected" not in left_out


def test_the_screen_says_where_each_company_is_connected() -> None:
    view = (STATIC / "js" / "views" / "devices.js").read_text(encoding="utf-8")
    assert "' On this iPhone.' : ' Through your server.'" in view
    assert "if (out.url) { window.location.assign(out.url); return; }" in view  # the web app still goes to the company
    assert "'Open your server'" in view and "Press Done to come back." in view
    assert "with your own developer app" in view and "Keys and services" in view
    # the server's own page opened by the app: #/devices/open/<provider> opens Settings here, with no toast
    assert "m[1] === 'open'" in view and "if (word === 'open')" in view
    mock = (STATIC / "js" / "mock" / "devices.js").read_text(encoding="utf-8")
    for kind in ("deviceStatus", "deviceConnect", "deviceFetch", "deviceDisconnect", "serverPage"):
        assert f"kind: '{kind}'" in mock, kind
    # the page never asks for a secret or a token: the app keeps them
    for word in ("client_secret", "access_token", "refresh_token"):
        assert word not in mock, word


SWIFT = ROOT / "ios"


def _code(rel: str) -> str:
    import re

    return re.sub(r"^\s*//[^\n]*", "", (SWIFT / rel).read_text(encoding="utf-8"), flags=re.M)  # whole-line comments


def test_the_app_signs_in_with_apples_sheet_and_checks_the_state() -> None:
    app = _code("KidneyHealth/Services/Devices.swift")
    core = _code("KidneyHealthCore/Sources/KidneyHealthCore/DeviceLinks.swift")
    assert "ASWebAuthenticationSession(url: url, callbackURLScheme: DeviceLinks.callbackScheme)" in app
    assert "sheet.prefersEphemeralWebBrowserSession = true" in app
    assert "SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)" in app and "count: 32" in app
    assert "DeviceLinks.back(back, expectedState: state)" in app
    assert "constantTimeEqual(state, expectedState)" in core
    # the relay page is https on the handbook's site; the app's scheme is not registered for other apps to open
    assert 'relayURL = "https://ksullivan86.github.io/kidney-health/oauth/"' in core
    assert 'callbackScheme = "kidneyhealth-devices"' in core
    assert "kidneyhealth-devices" not in (SWIFT / "KidneyHealth-Info.plist").read_text(encoding="utf-8")
    # only the server's scopes: never a profile or body measurements
    assert '"offline read:cycles read:recovery read:sleep read:workout"' in core and '"user.metrics"' in core
    assert "read:profile" not in core and "body_measurement" not in core


def test_the_app_talks_only_to_the_companies_fixed_hosts_and_keeps_secrets_in_the_keychain() -> None:
    app = _code("KidneyHealth/Services/Devices.swift")
    core = _code("KidneyHealthCore/Sources/KidneyHealthCore/DeviceLinks.swift")
    assert 'url.scheme == "https", url.host == company.apiHost' in app and "http.url?.host == company.apiHost" in app
    assert "NoRedirects()" in app and "httpCookieStorage = nil" in app and "urlCache = nil" in app
    assert "timeoutIntervalForRequest = 15" in app and "maxAnswer = 2 * 1024 * 1024" in app
    assert '"wbsapi.withings.net"' in core and '"api.prod.whoop.com"' in core
    assert "Keychain.save(data, as: Self.appItem(company))" in app and "Keychain.save(data, as: Self.tokenItem(company))" in app
    for word in ("print(", "NSLog", "os_log", "Logger(", "UserDefaults"):
        assert word not in app, word
    # the page gets the companies' answers, never a secret or a token
    status = app[app.index('if kind == "deviceStatus"'):app.index("guard let name = request")]
    assert '"app": apps.contains(company), "connected": connected.contains(company)' in status
    for word in ("secret", "access", "refresh"):
        assert word not in status, word
    # a refused refresh means connect again; the tokens are deleted before the company is asked to end the access
    assert "case .failure(.auth):\n            forget(company)" in app
    disconnect = app[app.index("private func disconnect"):app.index("private func revokeWhoop")]
    assert disconnect.index("forget(company)") < disconnect.index("revokeWithings")
    keys = _code("KidneyHealth/Services/KeysView.swift")
    assert "SecureField(devices.apps.contains(company)" in keys and "DeviceLinks.relayURL" in keys
    bridge = _code("KidneyHealth/Services/FoodServices.swift")
    assert 'case "deviceStatus", "deviceConnect", "deviceFetch", "deviceDisconnect", "serverPage":' in bridge


def test_the_servers_page_opens_in_safaris_sheet_on_the_paired_server_only() -> None:
    app = _code("KidneyHealth/Services/Devices.swift")
    assert "SFSafariViewController(url: url)" in app and "DeviceLinks.serverPage(address, company: company)" in app
    assert 'Keychain.read(.token) != nil' in app
    core = _code("KidneyHealthCore/Sources/KidneyHealthCore/DeviceLinks.swift")
    assert 'parts.fragment = "/devices/open/\\(company.rawValue)"' in core and "Settings.appURL(address)" in core


def test_the_relay_page_only_hands_the_sign_in_back_to_the_app() -> None:
    import re

    folder = ROOT / "handbook" / "oauth"
    page = (folder / "index.html").read_text(encoding="utf-8")
    assert re.findall(r"<script[^>]*>", page) == ['<script src="relay.js">']  # no inline script
    assert "<style" not in page and " style=" not in page and re.search(r"<[^>]+\son\w+=", page) is None  # no inline style or handler
    assert "default-src 'none'; script-src 'self'; style-src 'self'; base-uri 'none'; form-action 'none'" in page
    assert '<meta name="referrer" content="no-referrer">' in page and "http" not in re.sub(r"<!--.*?-->", "", page, flags=re.S).replace(
        "http-equiv", "")
    js = (folder / "relay.js").read_text(encoding="utf-8")
    assert "for (const name of ['code', 'state', 'error'])" in js
    assert "`kidneyhealth-devices://callback?${out.toString()}`" in js and "history.replaceState" in js
    for word in ("fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "indexedDB", "document.cookie", "console."):
        assert word not in js, word
    workflow = (ROOT / ".github" / "workflows" / "handbook-pages.yml").read_text(encoding="utf-8")
    assert 'cp oauth/index.html oauth/relay.js oauth/relay.css "$RUNNER_TEMP/site/oauth/"' in workflow
    # the app's relay address is that page on the handbook's site
    from urllib.parse import urlsplit

    core = (ROOT / "ios" / "KidneyHealthCore" / "Sources" / "KidneyHealthCore" / "DeviceLinks.swift").read_text(encoding="utf-8")
    relay = re.search(r'relayURL = "([^"]+)"', core).group(1)
    assert urlsplit(relay).scheme == "https" and urlsplit(relay).path.endswith("/oauth/")


def test_one_token_refresh_per_company_at_a_time() -> None:
    """Audit, 2026-11-26: a refresh token works once. Sync now during a background sync must not start a second refresh, which
    the company would refuse and the app would read as "connect again"."""
    app = _code("KidneyHealth/Services/Devices.swift")
    assert "private var refreshing: [DeviceCompany: Task<String, Error>] = [:]" in app
    access = app[app.index("private func access("):app.index("private func refreshNow(")]
    assert access.index("if let pending = refreshing[company] { return try await pending.value }") < access.index("refreshing[company] = task")
    assert "defer { refreshing[company] = nil }" in access
