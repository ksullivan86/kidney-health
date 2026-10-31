"""Settings → Your data → Phone shortcuts and the places that show where a weight or reading came from (design note 12 §4.4 and §4.6;
``app/static/js/views/settings.js``, ``js/engine/body_ui.js``, ``js/views/body.js``, ``js/views/body_trends.js``, the demo's
``js/mock/auth.js``).

The block's behaviour is run in Node against a tiny fake page and a fake server (``tests/js/push_page.mjs``): the demo's words, the
switch off and on, the token shown once with its address and Copy, the list, Revoke, "Delete what it sent" with its count, a name that
looks like markup, a closed password prompt, a list that cannot be loaded after a token was made. The rest is the source of the files:
no HTML sink, no inline handler, no storage, the requests the block makes. The demo's token routes are replayed through
``tests/js/demo_api.mjs``. A real browser walk of the same story is ``tools/e2e/push.py``.
"""
from __future__ import annotations

import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
SETTINGS_JS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
BODY_JS = (STATIC / "js" / "views" / "body.js").read_text(encoding="utf-8")
TRENDS_JS = (STATIC / "js" / "views" / "body_trends.js").read_text(encoding="utf-8")
BODY_UI_JS = (STATIC / "js" / "engine" / "body_ui.js").read_text(encoding="utf-8")
BLOCK = SETTINGS_JS[SETTINGS_JS.index("// push block (begin)"):SETTINGS_JS.index("// push block (end)")]
PAGE = ROOT / "tests" / "js" / "push_page.mjs"
DEMO = ROOT / "tests" / "js" / "demo_api.mjs"
TOKEN = "khd_SECRETSECRETSECRETSECRETSECRETSECRETSECRET1"


@lru_cache(maxsize=1)
def page() -> dict:
    done = subprocess.run(["node", str(PAGE)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def demo(requests: list[dict]) -> list[dict]:
    done = subprocess.run(["node", str(DEMO)], input=json.dumps(requests), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --------------------------------------------------------------------------- the block, run in Node


def test_the_demo_says_the_preview_has_no_server_and_asks_for_nothing():
    d = page()["demo"]
    assert "The preview has no server to send readings to." in d["text"]
    assert "A shortcut on your iPhone can send your latest weight and blood pressure here. Its token can only add readings: it cannot see your log." in d["text"]
    assert d["calls"] == 0 and d["form"] is False and d["create"] is False


def test_while_the_admin_switch_is_off_the_section_says_so_and_still_lists_revokes_and_deletes():
    off = page()["off"]
    assert "Your admin has not turned this on." in off["text"] and "Turned off on this server" in off["text"]
    assert off["form"] is False and off["create"] is False and off["calls"] == ["deviceTokens"] and off["admin"] is False
    with_tokens = page()["offWithTokens"]
    assert "Your admin has not turned this on." in with_tokens["text"]
    assert "Your tokens do not work while phone shortcuts are off. You can still revoke them and delete what they sent." in with_tokens["text"]
    assert with_tokens["admin"] is True and "PUSH_ENABLED" in with_tokens["text"]  # only an admin is told where the switch is
    assert with_tokens["form"] is False and with_tokens["revoke"] == 1 and with_tokens["deletes"] == 2  # a revoked token's rows can still be deleted


def test_the_block_says_what_it_does_and_offers_a_name_and_an_expiry_but_no_scopes():
    on = page()["on"]
    assert "A shortcut on your iPhone can send your latest weight and blood pressure here. Its token can only add readings: it cannot see your log." in on["text"]
    assert on["name"] == {"type": "text", "maxlength": "60"}
    assert on["expiry"] == {"value": "90", "options": [["30", "30 days"], ["90", "90 days"], ["365", "1 year"]]}
    assert on["canLog"] is False and "Can also save" not in on["text"]  # a device token's one scope is not a choice
    assert "Make token" in on["text"] and "No tokens yet." in on["text"] and on["admin"] is False
    assert "Weight and blood pressure, From a phone shortcut" in on["recipe"] and on["recipeLink"] == 0  # no handbook served: the plain words


def test_the_handbook_recipe_is_a_link_where_the_handbook_is_served():
    link = page()["recipeLink"]
    assert link == {"href": "/learn/app/weight-and-blood-pressure/#from-a-phone-shortcut", "target": "_blank", "rel": "noopener",
                    "text": "How to make the shortcut (opens in a new tab)"}


def test_a_token_needs_a_name_and_is_made_as_a_device_token_with_nothing_else_chosen():
    assert page()["emptyName"] == {"calls": 0, "message": "Give the token a name, for example “Morning weight”.", "focused": "set-push-name"}
    made = page()["created"]
    assert made["calls"][0] == ["createToken", {"name": "Morning weight", "expires_in_days": 365, "family": "device"}]  # trimmed; no scopes, no can_log
    assert made["calls"][1] == ["deviceTokens"]  # then the list is read again


def test_the_new_token_is_shown_once_with_its_address_and_copy_buttons():
    made = page()["created"]
    assert made["token"] == [TOKEN] and made["address"] == ["https://food.example.org/push/v1/body"]  # location.origin + the route
    assert "It is shown only now. Paste it into your shortcut." in made["tokenText"] and "It is not shown again. Revoke it here if it is lost." in made["tokenText"]
    assert "Token for “Morning weight” (shown only now)" in made["tokenText"]
    assert made["copyButtons"] == [1, 1]
    assert page()["copied"]["copied"] == [TOKEN, "https://food.example.org/push/v1/body"]
    assert page()["copied"]["toasts"] == [["ok", "Token copied"], ["ok", "Address copied"]]
    assert TOKEN not in made["list"]  # the list never carries it
    revoked = page()["revoked"]  # the next draw: the token is gone from the page
    assert revoked["tokenStillShown"] is False and revoked["boxes"] == 0


def test_the_new_token_comes_with_a_qr_code_for_the_iphone_app():
    pair = page()["pair"]
    assert pair["order"] == ["New token", "Address to send to", "Pair the iPhone app"]
    assert pair["qr"] == [["kidneyhealthsync://pair?v=1&server=https%3A%2F%2Ffood.example.org&token=" + TOKEN,  # the server's link, as it came
                           "QR code to scan with the iPhone Camera"]]
    assert pair["svg"] == 1 and "Point the iPhone Camera at this code and tap the link. The app asks you before it saves anything." in pair["text"]
    other = page()["pairless"]
    assert other["noLinkSvg"] == 0 and "The iPhone app needs this server at an https:// address." in other["noLink"]
    for words in (other["failed"], other["missing"]):
        assert "The QR code could not be drawn here. Type the address and paste the token in the app instead." in words
    two_step = (STATIC / "js" / "views" / "two_step.js").read_text(encoding="utf-8")
    assert "KH.twoStep = { block, groupKey, codesFile, qrPath, qrSvg, leftText, QR_URL };" in two_step  # drawn on the page, no other site


def test_the_list_names_each_token_with_its_prefix_dates_last_use_and_what_it_sent():
    rows = page()["list"]["rows"]
    assert [r["buttons"] for r in rows] == [["Revoke", "Delete what it sent"], ["Revoke", "Delete what it sent"], ["Revoke"], ["Delete what it sent"]]
    assert rows[0]["sub"] == ("khd_AbCd1234… · created d(2026-10-22T07:00:00Z) · last used r(2026-10-23T07:00:00Z) · expires d(2027-01-20T07:00:00Z)"
                              " · sent 2 weights and 1 blood pressure reading")
    assert "never used" in rows[1]["sub"] and "sent 1 blood pressure reading" in rows[1]["sub"]
    assert "nothing sent that is still in your log" in rows[2]["sub"]  # no "Delete what it sent" for a token with nothing to delete
    assert "expired d(2027-01-20T07:00:00Z)" in rows[3]["sub"] and rows[3]["buttons"] == ["Delete what it sent"]  # an ended token has no Revoke


def test_a_name_that_looks_like_markup_is_text():
    listing = page()["list"]
    assert listing["rows"][0]["title"] == '<img src=x onerror=alert(1)> & "quotes"'
    assert listing["tags"] == ["button", "div", "li", "span", "ul"]  # no img, no a, nothing the name could have made
    assert not [a for a in listing["attrs"] if a.startswith("on") or a in ("style", "srcdoc", "href", "src")]


def test_revoke_asks_first_then_revokes_and_draws_again():
    ask = page()["revokeAsk"]
    assert ask["message"] == "Revoke “Morning weight”? A shortcut using it stops working at once. What it already sent stays in your log until you delete it."
    assert (ask["confirmText"], ask["host"], ask["trigger"]) == ("Revoke", "token-actions", "Revoke")
    done = page()["revoked"]
    assert done["done"] is True and done["calls"] == [["revokeToken", 7], ["deviceTokens"]] and done["toast"] == ["ok", "Revoked Morning weight"]
    assert "revoked d(2026-10-22T08:00:00Z)" in done["text"]


def test_delete_what_it_sent_names_the_count_and_forgets_what_today_and_trends_loaded():
    ask = page()["deleteAsk"]
    assert ask["message"].startswith("Delete the 2 weights and 1 blood pressure reading that “")
    assert ask["message"].endswith("sent? Weights and readings you typed or imported yourself stay. This cannot be undone.")
    assert ask["confirmText"] == "Delete" and ask["calls"] == 0  # nothing is deleted by pressing the first button
    done = page()["deleted"]
    assert done["done"] is True and done["calls"] == [["deleteTokenRows", 1]]
    assert done["toast"] == ["ok", "Deleted 2 weights and 1 blood pressure reading"]
    assert done["state"] == {"dayLoadedFor": None, "trends": None, "summary": None, "plan": {"keep": True}}  # only the body caches


def test_five_active_tokens_hide_the_form_and_say_why():
    full = page()["full"]
    assert full == {"text": "You have 5 active phone shortcut tokens, the most allowed. Revoke one to make another.", "form": False}


def test_a_closed_password_prompt_is_quiet_a_refusal_is_shown_and_a_new_token_survives_a_failed_list():
    assert page()["cancelled"] == {"calls": ["deviceTokens", "createToken"], "errors": 0, "tokenShown": False}
    assert page()["refused"]["errors"] == ["You have 5 active tokens, the most allowed. Revoke one first."]
    text = page()["listFailsAfterCreate"]["text"]
    assert "Could not load this: The server could not answer." in text and "Token for “Morning weight” (shown only now)" in text  # never lost


def test_counts_in_words():
    assert page()["counts"] == ["", "1 weight", "1 blood pressure reading", "2 weights and 3 blood pressure readings", "", ""]


# --------------------------------------------------------------------------- the source of the block


def test_the_block_draws_everything_through_h_and_keeps_nothing_in_the_browser():
    for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "onclick", "javascript:", "style:", "style=", "setAttribute('style'",
                 "localStorage", "sessionStorage", "indexedDB", "eval(", "new Function"):
        assert word not in BLOCK, word
    assert "console.warn" in BLOCK and BLOCK.count("console.") == 1  # the one place a failed first draw is reported, never a value
    assert BLOCK.count("made.token") == 2 and "unshownDevice = null; return made" in BLOCK  # read by the check and the one box; forgotten at once
    assert "const pushAddress = () => `${window.location.origin}${PUSH_PATH}`;" in BLOCK and "const PUSH_PATH = '/push/v1/body';" in BLOCK
    assert "A.createToken({ name: text, expires_in_days: expiryValue(expiry), family: 'device' })" in BLOCK  # scopes are not the person's choice
    assert "can_log" not in BLOCK and "scopes" not in BLOCK
    assert "Your admin has not turned this on." in BLOCK and "The preview has no server to send readings to." in BLOCK
    assert BLOCK.index("if (MOCK) {") < BLOCK.index("await A.deviceTokens()")  # the demo never asks the server
    assert "confirm.inline(actions, revoke" in BLOCK and "confirm.inline(actions, del" in BLOCK
    assert "state.dayLoadedFor = null; state.trends = null; state.summary = null;" in BLOCK
    assert "a password prompt opens here when it is needed" in BLOCK  # re-auth is the request wrapper's, as for the assistant token


def test_the_requests_and_where_the_block_sits():
    assert "deviceTokens: () => request('GET', '/api/me/tokens?family=device')" in SETTINGS_JS
    assert "deleteTokenRows: (id) => request('DELETE', `/api/me/tokens/${encodeURIComponent(id)}/body-rows`)" in SETTINGS_JS
    data = SETTINGS_JS[SETTINGS_JS.index("function dataBlock(me)"):SETTINGS_JS.index("// Delete the account (not in AUTH_MODE=none")]
    assert data.index("wrap.append(bodyImportBlock());") < data.index("wrap.append(pushBlock());")  # Your data → Phone shortcuts
    assert "id: 'set-push-create'" in BLOCK and "id: 'set-push-name'" in BLOCK
    assert ("Phone shortcuts", "push.enabled") == re.search(r"\['(Phone shortcuts)', \['(push\.enabled)'\]\]", SETTINGS_JS).groups()  # the admin's switch


def test_the_activity_list_has_words_for_a_phone_shortcut_token_and_for_deleting_what_it_sent():
    assert "'body.token_rows_deleted': 'Phone shortcut data deleted'" in SETTINGS_JS
    assert "'api_token.created': 'Phone shortcut token created', 'api_token.revoked': 'Phone shortcut token revoked'" in SETTINGS_JS
    assert "if (d.family === 'device' && DEVICE_ACTION_LABEL[ev.action]) return DEVICE_ACTION_LABEL[ev.action];" in SETTINGS_JS
    assert "if (ev.action === 'api_token.revoked' && d.count != null) return 'Tokens revoked';" in SETTINGS_JS  # one press ended both families
    assert SETTINGS_JS.count("actionLabel(ev)") == 3  # the function, the person's own activity and the admin's log
    assert "ev.action === 'body.token_rows_deleted') return pushCountsText(" in SETTINGS_JS


# --------------------------------------------------------------------------- the demo


def test_the_demo_lists_no_tokens_and_refuses_to_make_one_with_the_previews_words():
    answers = demo([
        {"method": "GET", "path": "/api/me/tokens?family=device"},
        {"method": "GET", "path": "/api/me/tokens"},
        {"method": "GET", "path": "/api/me/tokens?family=phone"},
        {"method": "POST", "path": "/api/me/tokens", "body": {"name": "Morning weight", "family": "device"}},
        {"method": "DELETE", "path": "/api/me/tokens/1"},
        {"method": "DELETE", "path": "/api/me/tokens/1/body-rows"},
        {"method": "GET", "path": "/api/admin/users"},
    ])
    empty = {"enabled": False, "max_active": 5, "expiry_days": [30, 90, 365, "never"], "default_expiry_days": 90, "never_allowed": True, "tokens": []}
    assert answers[0] == {"ok": True, "body": {"family": "device", **empty}}
    assert answers[1] == {"ok": True, "body": {"family": "assistant", **empty}}
    assert answers[2] == {"ok": False, "status": 400, "detail": "family must be one of: assistant, device."}
    assert answers[3]["ok"] is False and answers[3]["status"] == 409 and answers[3]["detail"].startswith("The preview has no server to send readings to")
    assert answers[4] == {"ok": False, "status": 404, "detail": "token not found"}
    assert answers[5] == {"ok": False, "status": 404, "detail": "token not found"}
    assert all(u["assistant_tokens"] == 0 and u["device_tokens"] == 0 for u in answers[6]["body"]["users"])


# --------------------------------------------------------------------------- where a row came from


@pytest.mark.parametrize("row, text", [
    ({"source": "shortcut", "via": "Morning weight"}, "from a shortcut (Morning weight)"),
    ({"source": "shortcut", "via": None}, "from a shortcut"),
    ({"source": "shortcut", "via": ""}, "from a shortcut"),
    ({"source": "shortcut"}, "from a shortcut"),
    ({"source": "apple_health", "via": None}, "from the Health app"),
    ({"source": "import", "via": None}, "from a file"),
    ({"source": "manual", "via": None}, ""),
    ({"source": "withings"}, ""),
    ({}, ""),
])
def test_origin_text_for_a_row(row, text):
    script = ("globalThis.window = globalThis; const fs = require('node:fs'); const vm = require('node:vm');"
              "for (const f of ['rules', 'body', 'body_ui']) vm.runInThisContext(fs.readFileSync(process.argv[1] + '/js/engine/' + f + '.js', 'utf8'));"
              "console.log(JSON.stringify(KH.bodyUi.originText(JSON.parse(process.argv[2]))));")
    done = subprocess.run(["node", "-e", script, str(STATIC), json.dumps(row)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == text


def test_the_rows_of_the_trends_tables_carry_the_origin_and_the_screens_draw_it_as_text():
    assert "origin: originText(w)" in BODY_UI_JS and "origin: originText(r)" in BODY_UI_JS
    assert "const originEl = (row) => { const text = U.originText(row); return text ? h('span', { class: 'body-when body-origin' }, text) : null; };" in BODY_JS
    assert BODY_JS.count("originEl(") == 2  # the weight line and the reading line
    assert "const from = rows.some((r) => r.origin);" in TRENDS_JS and TRENDS_JS.count("...(from ? [['From']] : [])") == 2
    assert "[r.origin || '—']" in TRENDS_JS
    for code in (BODY_JS, TRENDS_JS, BODY_UI_JS):
        assert "innerHTML" not in code
