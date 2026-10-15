"""The routing frontend (``app/static/js/views/ai_routing.js``, its hooks in ``ai.js`` and ``settings.js``, ``css/ai.css``)
against the server contract: the file is in the shell and the service worker, nothing in it is an inline script, handler or
HTML string, every call it makes is a real route, and its behaviour (the table, the warning for a feature that goes to the
cloud, what Save sends, what a person reads) checked by running the file against a fake page in Node
(``tests/js/routing_page.mjs``)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from app import settings_registry

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ROUTING_JS = (STATIC / "js" / "views" / "ai_routing.js").read_text(encoding="utf-8")
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
SETTINGS_JS = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "ai.css").read_text(encoding="utf-8")


def test_the_file_is_in_the_shell_after_ai_js_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/ai.js") < scripts.index("js/views/ai_routing.js") < scripts.index("js/views/guidance.js")
    assert scripts.index("js/views/ai_routing.js") < scripts.index("js/main.js")
    assert "'/js/views/ai_routing.js'" in SW


def test_no_inline_script_handler_style_or_html_string_in_the_routing_pieces():
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE)
    for name, text in (("ai_routing.js", ROUTING_JS), ("ai.css", CSS)):
        assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\(|new Function", text, re.IGNORECASE), name
    assert not re.search(r"""\s(on[a-z]+|style)\s*:|['"]\s*(on[a-z]+|style)\s*['"]\s*:""", ROUTING_JS, re.IGNORECASE)
    assert not re.search(r"<\s*(script|img|iframe|style)\b", ROUTING_JS, re.IGNORECASE)


def test_every_routing_call_is_a_real_route_with_that_method(tmp_path, foods_json):
    from conftest import make_settings
    from app.main import create_app

    assert "routing: () => request('GET', '/api/admin/ai-routing')" in AI_JS
    assert "setRouting: (b) => request('PUT', '/api/admin/ai-routing', b)" in AI_JS
    app = create_app(make_settings(tmp_path, foods_json))
    assert {"GET", "PUT"} <= {m.upper() for m in app.openapi()["paths"]["/api/admin/ai-routing"]}
    assert "fetch(" not in ROUTING_JS and "request(" not in ROUTING_JS  # it reaches the server only through KH.ai.api


def test_the_server_settings_list_points_to_the_table_instead_of_six_rows():
    block = re.search(r"const GROUPS = \[(.*?)\n  \];", SETTINGS_JS, re.S).group(1)
    group = re.search(r"\['Which AI each feature uses', \[(.*?)\]\]", block, re.S)
    keys = set(re.findall(r"'(ai\.route\.[a-z_]+)'", group.group(1)))
    assert keys == {k for k in settings_registry.REGISTRY if k.startswith("ai.route.")}
    assert "title === ROUTING_GROUP" in SETTINGS_JS


def test_the_ai_view_uses_the_routing_pieces_and_a_feature_names_its_consent():
    assert "KH.aiRouting.adminPart(await api.routing(), refreshProviders)" in AI_JS
    assert "KH.aiRouting.personLines(me.routing)" in AI_JS
    assert "withConsent('text', () => api.parseMeal(payload()), () => api.parseMeal(payload(), true), btn, 'describe')" in AI_JS
    assert "const route = st && st.routes && st.routes[feature];" in AI_JS
    assert "the local AI" in ROUTING_JS and "outside your network" in ROUTING_JS


def test_the_classes_the_file_uses_are_styled():
    for cls in re.findall(r"class: '(ai-[a-z-]+)'", ROUTING_JS):
        assert f".{cls}" in CSS, cls


@pytest.fixture(scope="module")
def page():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "routing_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_table_offers_local_cloud_and_off_and_only_a_private_provider_can_be_local(page):
    r = page["routed"]
    assert r["header"] == ["Feature", "Local", "Cloud", "Off"]
    assert r["rows"] == ["Photos (labels and plates)", "Meal ideas", "Describe a meal", "Ask"]
    assert r["localOptions"] == ["0:None", "2:Ollama (ollama.lan:11434)"]  # the public providers are not offered
    assert r["cloudOptions"] == ["0:None", "1:OpenAI (api.openai.com)", "3:Spare cloud (api.example.com)"]
    assert r["anyRadio"] is False and r["asBeforeBanner"] is False and r["warningsAtStart"] == ""


def test_a_feature_pinned_to_the_cloud_shows_what_it_sends_and_where(page):
    assert page["afterCloud"] == ("Meal ideas: this sends your meal data (stage, targets, today's totals and the foods the rules offered) "
                                  "to api.openai.com, outside your network.")
    assert page["saved"] == [{"meal_ideas": "cloud"}]  # only what changed
    assert page["afterSave"]["forgot"] == 1 and page["afterSave"]["after"] == 1
    assert page["afterSave"]["toasts"] == [["ok", "Routing saved"]]
    assert page["nothingChanged"]["message"] == "Nothing changed."


def test_the_only_spare_provider_is_offered_as_the_cloud_ai_visibly(page):
    assert page["noCloudYet"]["before"] == "0"
    assert page["offered"]["cloudValue"] == "1" and "to api.openai.com, outside your network" in page["offered"]["warnings"]
    assert page["offeredSaved"] == {"chat": "cloud", "cloud_provider": 1}


def test_a_local_feature_without_a_local_ai_says_it_is_off(page):
    assert "Meal ideas: local, but no local AI is chosen, so it is off until you choose one." in page["noLocal"]["warnings"]
    assert page["noLocal"]["localOptions"] == ["0:None"] and page["noLocal"]["hint"] is True


def test_an_upgraded_server_sees_as_before_and_is_told_what_it_means(page):
    a = page["asBefore"]
    assert a["banner"] is True and a["header"][-1] == "As before" and a["anyEnabled"] is True
    assert "whichever shared provider each person chose, which may be a cloud AI outside your network" in a["warnings"]


def test_locked_and_read_only_controls_are_disabled(page):
    assert page["locked"] == {"disabled": True, "other": False, "note": True}
    assert page["readonly"] == {"radio": True, "select": True, "save": True, "note": True}
    assert page["envRole"] == {"localDisabled": True, "cloudDisabled": False, "text": True}


def test_a_refused_save_shows_the_servers_words(page):
    assert page["refused"] == "not a private host"


def test_a_person_reads_where_each_feature_runs(page):
    p = page["person"]
    assert "Photos (labels and plates): Runs on your local AI (ollama.lan:11434)." in p["lines"]
    assert "Ask: Runs on OpenAI (api.openai.com), a cloud AI outside your network." in p["lines"]
    assert "off for everyone, whatever provider they use" in p["lines"] and p["none"] is None
    assert "the server uses the provider chosen above, as before" in p["before"]


# --------------------------------------------------------------------------- #
# Privacy tier 3: "Local, then cloud"
# --------------------------------------------------------------------------- #


def test_local_then_cloud_is_offered_only_where_the_server_allows_it_with_the_one_line_rule(page):
    f = page["fallback"]
    assert f["header"] == ["Feature", "Local", "Cloud", "Off", "Local, then cloud"]
    assert f["meal"] == ["Meal ideas: Local", "Meal ideas: Cloud", "Meal ideas: Off", "Meal ideas: Local, then cloud"]
    assert f["ask"] == ["Ask: Local", "Ask: Cloud", "Ask: Off"] and f["askNotOffered"] == ["– Ask: Local, then cloud is not offered"]
    assert f["labsNotOffered"] == ["– Lab report photos: Cloud is not offered", "– Lab report photos: Local, then cloud is not offered"]
    assert page["noFallbackColumn"] == ["Feature", "Local", "Cloud", "Off"]  # a server that allows nothing more shows no extra column
    # the rule, in the server's own words
    from app.ai import config as K

    assert f["rule"].startswith("Local, then cloud: " + K.FALLBACK_RULE)
    assert "Ask and lab report photos cannot use it." in f["rule"]


def test_choosing_local_then_cloud_says_what_goes_to_the_cloud_and_when_and_saves_only_that(page):
    assert page["fallbackChosen"] == ("Meal ideas: local first. If the local AI's answer fails the app's checks, this sends your meal data "
                                      "(stage, targets, today's totals and the foods the rules offered) to api.openai.com, outside your network, "
                                      "for people who agreed to that.")
    assert page["fallbackSaved"] == {"meal_ideas": "local_then_cloud"}
    assert page["fallback"]["atStart"] == ""


def test_both_roles_are_needed_and_the_page_says_what_happens_without_one(page):
    roles = page["fallbackRoles"]
    assert roles["noCloud"] == ("Photos (labels and plates): local, then cloud, but no cloud AI is chosen, so it works as local: "
                                "the cloud AI is never asked.")
    assert "Describe a meal: local, then cloud, but no local AI is chosen, so it is off until you choose one." in roles["noLocal"]
    assert "this sends the meals you describe" not in roles["noLocal"]  # nothing leaves while the feature is off
    assert page["fallbackOffered"] == {"photos": "local_then_cloud", "cloud_provider": 1}  # the only spare provider is offered


def test_the_ui_rule_is_the_servers_rule_and_the_new_pieces_are_wired():
    from app.ai import config as K

    assert K.FALLBACK_RULE.replace("'", "\\'") in ROUTING_JS.replace("'\n    + '", "")
    for needle in ("function fallbackDryRun(f)", "dry.cloud_fallback ? fallbackDryRun(dry.cloud_fallback) : null",
                   "function fallbackNotes(answer)", "const f = answer && answer.cloud_fallback;", "consent.fallback",
                   "api.consent({ provider_id: fb.provider_id", "fallbackNotes, droppedNotes };"):
        assert needle in AI_JS, needle
    scan = (STATIC / "js" / "scan.js").read_text(encoding="utf-8")
    assert "KH.ai.fallbackNotes(answer)" in scan
    for cls in ("ai-dry-fallback", "ai-consent-fallback", "ai-fallback-line", "ai-route-rule"):
        assert f".{cls}" in CSS, cls


def test_settings_offers_to_agree_to_the_cloud_ai_later_only_where_the_person_has_not(page):
    a = page["agreeLater"]
    assert a["buttonCount"] == 1  # the photos line (agreed) and the Ask line (no fallback) have none
    assert a["button"] == "Allow the cloud AI (api.openai.com) as the fallback"
    assert ("You have not agreed to send this to api.openai.com, so the cloud AI is never asked."
            in a["before"][0]) and "never asked" not in a["before"][1] + a["before"][2]
    assert "hidden" not in a["declined"] and "never asked" in a["declined"]["line"]  # closing the sheet changes nothing
    assert a["asked"] == [[1, "api.openai.com", "text", True], [1, "api.openai.com", "text", True]]  # the server's own request
    assert a["after"]["hidden"] is True
    assert "Agreed: if the local AI's answer fails the app's checks, api.openai.com is asked." in a["after"]["line"]
    assert "never asked" not in a["after"]["line"]


def test_the_phone_layout_rules_of_the_routing_pieces_stay():
    """Found by tools/e2e/fallback.py at 375 px: a button naming a host ran past the screen, a table heading broke inside
    the word "Local", and `AI_PROVIDER_ROLE=local` overlapped the next column. The rules that fixed them stay in ai.css."""
    button_rule = re.search(r"\.ai-routing-lines \.btn[^{]*\{([^}]*)\}", CSS)
    assert button_rule and "white-space: normal" in button_rule.group(1) and "max-width: 100%" in button_rule.group(1)
    assert re.search(r"\.ai-routing-table thead th \{ overflow-wrap: break-word;", CSS)  # `anywhere` lets the table squeeze a column mid-word
    assert re.search(r"\.ai-routing \.form-grid \.hint \{ overflow-wrap: anywhere;", CSS)
    assert re.search(r"\.ai-routing \.form-grid \.field \{ min-width: 0;", CSS)
