"""The screens of passkeys (design note 18 §6): static checks of the page, and the pure helpers of js/views/passkeys.js run in Node.

Adding a passkey and signing in with it are walked in Chromium with a virtual authenticator against a real server by
``tools/e2e/passkeys.py``.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
VIEW = STATIC / "js" / "views" / "passkeys.js"


def test_the_sign_in_form_has_a_hidden_passkey_button():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    form = html[html.index('<form id="form-login"'):html.index("</form>", html.index('<form id="form-login"'))]
    block = re.search(r'<div class="auth-passkey" id="login-passkey" hidden>.*?</div>', form, re.S)
    assert block, "the passkey button is part of the sign-in form and hidden until the server and browser allow it"
    assert 'type="button" id="login-passkey-btn">Sign in with a passkey</button>' in block.group(0)
    auth = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
    assert "$('#login-passkey').hidden = !(st.passkeys && KH.passkeys && KH.passkeys.supported());" in auth
    assert "await KH.passkeys.signIn();" in auth


def test_the_view_is_loaded_after_two_step_and_kept_offline():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts.index("js/views/passkeys.js") == scripts.index("js/views/two_step.js") + 1
    assert "'/js/views/passkeys.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_view_draws_with_elements_and_calls_only_its_routes():
    text = VIEW.read_text(encoding="utf-8")
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "import(" not in text
    assert set(re.findall(r"'(/api/[^'`$]+)", text)) == {"/api/me/passkeys", "/api/me/passkeys/options", "/api/auth/passkey/options",
                                                          "/api/auth/passkey", "/api/auth/reauth/passkey/options",
                                                          "/api/auth/reauth/passkey"}
    assert "/api/admin" not in text


def test_settings_shows_the_block_for_a_password_account_and_the_admin_can_remove_them():
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "if (hasLocalPassword() && KH.passkeys) body.append(KH.passkeys.block());" in settings
    assert "removeUserPasskeys: (id) => request('DELETE', `/api/admin/users/${id}/passkeys`)" in settings
    assert "if (u.passkeys)" in settings and "'Remove passkeys'" in settings


def test_the_demo_answers_as_a_server_without_passkeys():
    mock = (STATIC / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
    assert "route('GET', '/api/me/passkeys', function () { this._currentUser(); return { available: false, usable: false, reason: null, passkeys: [], max: 10 }; });" in mock
    assert "passkeys: false," in mock and "passkeys: 0," in mock
    assert "route('DELETE', userIdRoute('/passkeys')" in mock


def test_the_activity_list_names_every_passkey_event_in_words():
    from app.audit import ACTIONS, USER_VISIBLE_ACTIONS

    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    labels = settings[settings.index("const ACTION_LABEL = {"):settings.index("};", settings.index("const ACTION_LABEL = {"))]
    actions = sorted(a for a in ACTIONS if a.startswith("passkey."))
    assert actions == ["passkey.added", "passkey.counter_went_back", "passkey.removed"]
    for action in actions:
        assert action in USER_VISIBLE_ACTIONS and f"'{action}':" in labels, action
    assert "if (ev.action === 'login.succeeded' && d.via === 'passkey') return 'Signed in with a passkey';" in settings


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_pure_helpers():
    script = f"""
      const window = {{ KH: {{ h() {{}}, $() {{}}, clear() {{}}, request() {{}}, toast() {{}}, toastError() {{}}, confirm: {{}}, flags: {{ MOCK: false }} }} }};
      globalThis.window = window;
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(VIEW))}, 'utf8'));
      const P = window.KH.passkeys;
      const bytes = new Uint8Array([0, 1, 250, 251, 252, 253, 254, 255]);
      const created = P.creationOptions({{ challenge: 'AAEC', rp: {{ id: 'x' }}, user: {{ id: '_-8', name: 'ana' }},
        excludeCredentials: [{{ type: 'public-key', id: 'AQ' }}], attestation: 'none' }});
      const asked = P.requestOptions({{ challenge: 'AAEC', rpId: 'x', allowCredentials: [] }});
      const buf = (a) => new Uint8Array(a).buffer;
      const reg = P.registrationJSON({{ id: 'AQ', rawId: buf([1]), type: 'public-key',
        response: {{ clientDataJSON: buf([123]), attestationObject: buf([160]), getTransports: () => ['internal'] }} }});
      const asr = P.assertionJSON({{ id: 'AQ', rawId: buf([1]), type: 'public-key',
        response: {{ clientDataJSON: buf([123]), authenticatorData: buf([9]), signature: buf([48]), userHandle: buf([]) }} }});
      console.log(JSON.stringify({{
        b64: P.toB64url(bytes), back: Array.from(P.fromB64url(P.toB64url(bytes))),
        created: {{ challenge: Array.from(created.challenge), user: Array.from(created.user.id), name: created.user.name,
                   exclude: Array.from(created.excludeCredentials[0].id), attestation: created.attestation }},
        asked: {{ challenge: Array.from(asked.challenge), rpId: asked.rpId }},
        reg, asr,
        msg: [P.deviceMessage({{ name: 'NotAllowedError' }}, false), P.deviceMessage({{ name: 'InvalidStateError' }}, true),
              P.deviceMessage({{ name: 'NotAllowedError' }}, true)],
        line: P.itemLine({{ created_at: null, last_used_at: null, backed_up: true }}),
      }}));
    """
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout)
    assert got["b64"] == "AAH6-_z9_v8" and got["back"] == [0, 1, 250, 251, 252, 253, 254, 255]
    assert got["created"] == {"challenge": [0, 1, 2], "user": [255, 239], "name": "ana", "exclude": [1], "attestation": "none"}
    assert got["asked"] == {"challenge": [0, 1, 2], "rpId": "x"}
    assert got["reg"] == {"id": "AQ", "rawId": "AQ", "type": "public-key",
                          "response": {"clientDataJSON": "ew", "attestationObject": "oA", "transports": ["internal"]}}
    assert got["asr"]["response"] == {"clientDataJSON": "ew", "authenticatorData": "CQ", "signature": "MA", "userHandle": None}
    assert got["msg"] == ["No passkey was used. Try again, or sign in with your password.",
                          "This device already has a passkey for your account.",
                          "No passkey was saved. The request was cancelled or took too long."]
    assert got["line"].endswith("not used yet · synced to your account in the cloud.")


def test_the_password_sheet_offers_a_passkey_instead():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    sheet = html[html.index('<dialog id="sheet-reauth"'):html.index("</dialog>", html.index('<dialog id="sheet-reauth"'))]
    assert '<div class="reauth-passkey" id="reauth-passkey" hidden>' in sheet
    assert 'type="button" id="reauth-passkey-btn">Use a passkey instead</button>' in sheet
    auth = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
    assert "KH.passkeys.reauthAvailable().then(" in auth and "await KH.passkeys.reauth();" in auth
    view = VIEW.read_text(encoding="utf-8")
    assert "if (MOCK || !supported()) return false;" in view  # the demo never offers it
