"""The screens of sign-in with a provider (design note 24): static checks of the page and the pure helpers of js/views/oidc.js
run in Node. The whole trip (button, provider, back) is walked in Chromium against a fake provider by ``tools/e2e/oidc.py``."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = STATIC / "js" / "views" / "oidc.js"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def _form(form_id: str) -> str:
    start = HTML.index(f'<form id="{form_id}"')
    return HTML[start:HTML.index("</form>", start)]


def test_the_sign_in_button_is_a_plain_hidden_link():
    block = re.search(r'<div class="auth-passkey" id="login-oidc" hidden>.*?</div>', _form("form-login"), re.S)
    assert block, "the provider's button is part of the sign-in form and hidden until the server says it is on"
    assert '<a class="btn secondary auth-passkey-btn" id="login-oidc-btn" href="api/auth/oidc/start">' in block.group(0)
    assert re.search(r'<div class="auth-passkey" id="register-oidc" hidden>', _form("form-register"))
    assert '<div class="reauth-passkey" id="reauth-oidc" hidden>' in HTML


def test_no_inline_script_and_the_view_is_kept_offline():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", HTML, re.IGNORECASE), "the CSP allows no inline script"
    assert "onclick=" not in HTML.lower()
    scripts = re.findall(r'<script src="([^"]+)"', HTML)
    assert scripts.index("js/views/oidc.js") == scripts.index("js/views/sharing.js") + 1
    assert scripts.index("js/views/oidc.js") < scripts.index("js/main.js")
    assert "'/js/views/oidc.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_view_draws_with_elements_and_calls_only_its_routes():
    text = VIEW.read_text(encoding="utf-8")
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "import(" not in text and "fetch(" not in text
    assert set(re.findall(r"'(/api/[^'`$]+)", text)) | set(re.findall(r"`(/api/[^`$]+)", text)) == {
        "/api/me/oidc", "/api/me/oidc/link", "/api/me/oidc/", "/api/auth/oidc/invite", "/api/auth/reauth/oidc"}
    assert "/api/admin" not in text


def test_settings_auth_and_the_demo_use_it():
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "if (hasLocalPassword() && KH.oidc) body.append(KH.oidc.block());" in settings
    assert "removeUserOidc: (id) => request('DELETE', `/api/admin/users/${id}/oidc`)" in settings
    assert "if (u.oidc_links)" in settings and "'Remove linked sign-in'" in settings
    auth = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
    assert "if (KH.oidc) KH.oidc.applyStatus();" in auth and "await KH.oidc.reauth(btn.dataset.provider || null);" in auth
    assert "KH.oidc.startInvite(linkToken.token, btn.dataset.provider || null)" in auth and "applyPasswordMode();" in auth
    mock = (STATIC / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
    assert "oidc: { enabled: false, label: null, providers: [], only: false, password: 'on' }," in mock and "oidc_links: 0," in mock
    assert "route('GET', '/api/me/oidc', function () {" in mock and "route('DELETE', userIdRoute('/oidc')" in mock


def test_the_activity_list_names_the_link_events():
    from app.audit import ACTIONS, USER_VISIBLE_ACTIONS

    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    labels = settings[settings.index("const ACTION_LABEL = {"):settings.index("};", settings.index("const ACTION_LABEL = {"))]
    actions = sorted(a for a in ACTIONS if a.startswith("oidc."))
    assert actions == ["oidc.linked", "oidc.unlinked"]
    for action in actions:
        assert action in USER_VISIBLE_ACTIONS and f"'{action}':" in labels, action


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_pure_helpers():
    from app.auth.oidc import RESULTS

    script = f"""
      const window = {{ KH: {{ h() {{}}, $() {{ return null; }}, clear() {{}}, request() {{}}, toast() {{}}, toastError() {{}}, confirm: {{}},
                          state: {{ authStatus: {{ oidc: {{ enabled: true, label: 'Sign in with Authentik' }} }} }} }} }};
      globalThis.window = window;
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(VIEW))}, 'utf8'));
      const O = window.KH.oidc;
      const words = {json.dumps(list(RESULTS))};
      console.log(JSON.stringify({{
        all: words.every((w) => O.message(w, 'Sign in with Google').length > 10),
        unknown: O.message('nope', 'x'),
        failed: O.message('failed', 'Sign in with Google'),
        linked: O.message('linked', 'Sign in with Authentik'),
        plain: O.shortLabel('Sign in with single sign-on'),
        odd: O.shortLabel('Family login'),
        parsed: O.parseResult('#/oidc/no_account'),
        ok: O.parseResult('#/oidc/linked'),
        named: O.parseResult('#/oidc/failed/google'),
        bad: [O.parseResult('#/oidc/<script>'), O.parseResult('#/oidc/unknown'), O.parseResult('#/oidc/linked/X'),
              O.parseResult('#/oidc/linked/google/x'), O.parseResult('#/oidc/linked/g')],
        enabled: O.enabled(),
        old: O.providers(),
        mode: O.passwordMode(),
      }}));
      window.KH.state.authStatus.oidc = {{ enabled: true, label: 'Sign in with Authentik', only: true, password: 'test_accounts',
        providers: [{{ id: 'authentik', label: 'Sign in with Authentik' }}, {{ id: 'google', label: 'Sign in with Google' }}] }};
      console.log(JSON.stringify({{ two: O.providers().map((p) => p.id), google: O.labelOf('google'), unknown: O.labelOf('nope'),
        first: O.labelOf(null), mode: O.passwordMode() }}));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout
    got, several = (json.loads(line) for line in out.strip().splitlines())
    assert got["all"] is True and got["unknown"] == ""
    assert got["failed"].startswith("Signing in with Google did not work.")
    assert got["linked"] == "Linked. You can now sign in with Authentik."
    assert got["plain"] == "single sign-on" and got["odd"] == "Family login"
    assert got["parsed"] == {"word": "no_account", "ok": False, "provider": None}
    assert got["ok"] == {"word": "linked", "ok": True, "provider": None}
    assert got["named"] == {"word": "failed", "ok": False, "provider": "google"}
    assert got["bad"] == [None] * 5 and got["enabled"] is True
    # A server from before several providers sends only the label: one provider, passwords on.
    assert got["old"] == [{"id": "default", "label": "Sign in with Authentik"}] and got["mode"] == "on"
    assert several == {"two": ["authentik", "google"], "google": "Sign in with Google", "unknown": "Sign in with Authentik",
                       "first": "Sign in with Authentik", "mode": "test_accounts"}
