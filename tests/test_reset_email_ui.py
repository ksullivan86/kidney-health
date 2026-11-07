"""Password reset by email in the page and in the demo (design note 34): the static parts of the sign-in screen and Settings, the
demo's routes (replayed through ``tests/js/demo_api.mjs``), and the parity vectors (``tests/data/email_vectors.json``)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
DATA = ROOT / "tests" / "data"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
AUTH_JS = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
SETTINGS_JS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
MOCK_AUTH_JS = (STATIC / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
BLOCK = SETTINGS_JS[SETTINGS_JS.index("// email block (begin)"):SETTINGS_JS.index("// email block (end)")]
DEMO = ROOT / "tests" / "js" / "demo_api.mjs"


def demo(requests: list[dict]) -> list[dict]:
    done = subprocess.run(["node", str(DEMO)], input=json.dumps(requests), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_sign_in_page_offers_it_only_when_the_server_does():
    assert 'id="login-forgot" hidden>Forgot your password?</button>' in INDEX
    assert 'data-screen="forgot"' in INDEX and 'id="forgot-username"' in INDEX and 'autocomplete="username"' in INDEX
    assert "there is no email reset" not in INDEX
    assert "status().email_reset" in AUTH_JS and "'/api/auth/forgot'" in AUTH_JS and "'/api/auth/email/confirm'" in AUTH_JS
    # The confirmation token leaves the address bar at once, like the reset and invite tokens.
    take = AUTH_JS[AUTH_JS.index("function takeConfirmToken()"):AUTH_JS.index("async function confirmEmail(")]
    assert "history.replaceState" in take and "TOKEN_RE.test" in take


def test_the_settings_block_never_builds_html_from_strings():
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "localStorage", "onclick="):
        assert sink not in BLOCK, sink
    assert "'/api/me/email'" in SETTINGS_JS and "'/api/admin/email/test'" in SETTINGS_JS
    assert "Email for password resets" in BLOCK and "Your admin does not see it." in BLOCK


def test_every_new_audit_action_has_a_label():
    from app.audit import ACTIONS, USER_VISIBLE_ACTIONS

    labels = SETTINGS_JS[SETTINGS_JS.index("const ACTION_LABEL = {"):SETTINGS_JS.index("};", SETTINGS_JS.index("const ACTION_LABEL = {"))]
    names = sorted(a for a in ACTIONS if a.startswith("email."))
    assert names == ["email.confirmed", "email.removed", "email.set"]
    for name in names:
        assert name in USER_VISIBLE_ACTIONS and f"'{name}':" in labels, name
        assert f"'{name}'" in MOCK_AUTH_JS, name


def test_the_demo_sends_nothing_and_says_so():
    answers = demo([
        {"method": "GET", "path": "/api/auth/status"},
        {"method": "POST", "path": "/api/auth/forgot", "body": {"username": "sam"}},
        {"method": "GET", "path": "/api/me/email"},
        {"method": "POST", "path": "/api/admin/email/test"},
        {"method": "PUT", "path": "/api/me/email", "body": {"email": "Sam@Example.org"}},
        {"method": "GET", "path": "/api/admin/users"},
        {"method": "POST", "path": "/api/admin/email/test"},
        {"method": "DELETE", "path": "/api/me/email"},
        {"method": "GET", "path": "/api/me/email"},
        {"method": "GET", "path": "/api/admin/about"},
    ])
    status, forgot, empty, no_address, saved, users, test, removed, gone, about = answers
    assert status["body"]["email_reset"] is True
    assert forgot["body"]["demo"] is True and forgot["body"]["detail"].startswith("If that account has a confirmed email")
    assert empty["body"] == {"available": True, "reason": None, "email": None, "confirmed": False, "confirmed_at": None}
    assert no_address["ok"] is False and no_address["status"] == 409
    assert saved["body"]["email"] == "sam@example.org" and saved["body"]["confirmed"] is True and saved["body"]["sent"] is False
    assert "Demo: no email was sent" in saved["body"]["message"]
    assert "sam@example.org" not in json.dumps(users["body"])
    assert {u["username"]: u["email_confirmed"] for u in users["body"]["users"]} == {"sam": True, "alex": False}
    assert test["body"] == {"sent": False, "to": "sam@example.org", "demo": True}
    assert removed == {"ok": True, "body": None} and gone["body"]["email"] is None
    assert about["body"]["email"]["enabled"] is True and "password" not in json.dumps(about["body"]["email"])


def _generator():
    spec = importlib.util.spec_from_file_location("gen_email_vectors", DATA / "gen_email_vectors.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_vectors_are_current():
    committed = json.loads((DATA / "email_vectors.json").read_text(encoding="utf-8"))
    assert committed == _generator().build(), (
        "tests/data/email_vectors.json is stale: run `python3 tests/data/gen_email_vectors.py`, then `node tests/js/run_vectors.mjs`, "
        "and update the demo's twin (app/static/js/mock/auth.js) until both agree."
    )


def test_the_node_runner_replays_the_email_vectors():
    assert shutil.which("node"), "Node.js 22 is needed for the JS parity vectors (CLAUDE.md, Parity)"
    proc = subprocess.run(["node", str(ROOT / "tests" / "js" / "run_vectors.mjs")], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"email vectors: \d+ checks passed", proc.stdout)
