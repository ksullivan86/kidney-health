"""The screens of two-step sign-in (design note 17 §7): static checks of the page, and the pure helpers of js/views/two_step.js run in Node.

The flow itself (QR code, first code, recovery codes, sign-in with a code, the admin's removal, a reset link, the demo) is walked in
Chromium against a real server by ``tools/e2e/two_step.py``, which also decodes the drawn QR code with the vendored barcode reader.
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
VIEW = STATIC / "js" / "views" / "two_step.js"


def test_the_sign_in_form_has_a_hidden_code_field_that_phones_fill_from_the_app():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    form = html[html.index('<form id="form-login"'):html.index("</form>", html.index('<form id="form-login"'))]
    field = re.search(r'<div class="field" id="login-code-field" hidden>.*?</div>', form, re.S)
    assert field, "the code field is part of the sign-in form and hidden until the server asks"
    tag = re.search(r"<input id=\"login-code\"[^>]*>", field.group(0)).group(0)
    for attr in ('name="code"', 'autocomplete="one-time-code"', 'inputmode="numeric"', 'maxlength="32"', 'aria-describedby="login-code-hint"'):
        assert attr in tag, attr
    assert "recovery codes" in field.group(0)


def test_the_view_is_loaded_after_settings_and_kept_offline():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', html)
    assert scripts.index("js/views/two_step.js") == scripts.index("js/views/settings.js") + 1
    assert "'/js/views/two_step.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_view_draws_with_elements_and_loads_the_vendored_qr_module_only():
    text = VIEW.read_text(encoding="utf-8")
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "createSvgTag" not in text
    assert re.findall(r"import\(([^)]+)\)", text) == ["QR_URL"]
    url = re.search(r"const QR_URL = '([^']+)'", text).group(1)
    assert (STATIC / url.lstrip("/")).is_file(), url
    assert "/api/me/totp" in text and "/api/admin" not in text


def test_settings_shows_the_block_only_for_a_password_account_and_the_admin_can_remove_it():
    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "if (hasLocalPassword() && KH.twoStep) body.append(KH.twoStep.block());" in settings
    assert "removeUserTwoStep: (id) => request('DELETE', `/api/admin/users/${id}/totp`)" in settings
    assert "if (u.two_step)" in settings and "'Remove two-step sign-in'" in settings


def test_the_demo_answers_the_routes_as_a_server_without_two_step_sign_in():
    mock = (STATIC / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
    assert "route('GET', '/api/me/totp', function () { this._currentUser(); return { available: false, enabled: false, enabled_at: null, recovery_codes_left: 0 }; });" in mock
    for path in ("'/api/me/totp/setup'", "'/api/me/totp/enable'", "'/api/me/totp/recovery-codes'", "['DELETE', '/api/me/totp']"):
        assert path in mock, path
    assert "route('DELETE', userIdRoute('/totp')" in mock and "two_step: false" in mock


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_pure_helpers():
    script = f"""
      const window = {{ KH: {{ h() {{}}, s() {{}}, $() {{}}, clear() {{}}, request() {{}}, toast() {{}}, toastError() {{}}, confirm: {{}}, flags: {{ MOCK: false }} }} }};
      globalThis.window = window;
      require('vm').runInThisContext(require('fs').readFileSync({json.dumps(str(VIEW))}, 'utf8'));
      const T = window.KH.twoStep;
      const dark = new Set(['0,0', '1,2']);
      console.log(JSON.stringify({{
        group: T.groupKey('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'),
        path: T.qrPath(3, (r, c) => dark.has(`${{r}},${{c}}`)),
        file: T.codesFile(['aaaaa-bbbbb', 'ccccc-ddddd'], {{ account: 'ana', server: 'Home' }}),
        left: [T.leftText(0), T.leftText(1), T.leftText(7)],
      }}));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=60).stdout
    got = json.loads(out)
    assert got["group"] == "ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567"
    assert got["path"] == "M4 4h1v1h-1zM6 5h1v1h-1z"  # row 0 col 0, row 1 col 2, plus the 4-module quiet zone
    assert got["file"].splitlines() == ["Recovery codes for ana on Home.", "Each code works once, in place of the code from your authenticator app.",
                                        "Keep them somewhere safe, away from your phone.", "", "aaaaa-bbbbb", "ccccc-ddddd"]
    assert got["left"] == ["No recovery codes left. Make new ones now.", "1 recovery code left.", "7 recovery codes left."]


def test_the_activity_list_names_every_two_step_event_in_words():
    from app.audit import ACTIONS, USER_VISIBLE_ACTIONS

    settings = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    labels = settings[settings.index("const ACTION_LABEL = {"):settings.index("};", settings.index("const ACTION_LABEL = {"))]
    two_step = sorted(a for a in ACTIONS if a.startswith("totp."))
    assert two_step == ["totp.disabled", "totp.enabled", "totp.recovery_code_used", "totp.recovery_codes_renewed"]
    for action in two_step:
        assert action in USER_VISIBLE_ACTIONS and f"'{action}':" in labels, action
    assert "if (ev.action === 'login.failed' && d.via === 'code') return 'Wrong sign-in code entered';" in settings
