"""The "How well each AI is doing" screen (``app/static/js/views/ai_quality.js``, its hook in ``ai.js``, ``css/ai.css``) against the
server contract: the file is in the shell and the service worker, nothing in it is an inline script, handler, style or HTML string,
the one call it makes is a real admin route, the demo never reaches it, and its behaviour (a row per feature, a caution for a
warning, a quiet line for a pass, the reports folder line, text from the server staying text, "Check again") checked by running
the file against a fake page in Node (``tests/js/quality_page.mjs``)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
QUALITY_JS = (STATIC / "js" / "views" / "ai_quality.js").read_text(encoding="utf-8")
AI_JS = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "ai.css").read_text(encoding="utf-8")
MOCK_AI = (STATIC / "js" / "mock" / "ai.js").read_text(encoding="utf-8")


def test_the_file_is_in_the_shell_after_the_routing_table_and_in_the_service_worker():
    scripts = re.findall(r'<script src="([^"]+)"', INDEX)
    assert scripts.index("js/views/ai_routing.js") < scripts.index("js/views/ai_quality.js") < scripts.index("js/main.js")
    assert "'/js/views/ai_quality.js'" in SW


def test_no_inline_script_handler_style_or_html_string_in_the_screen():
    for name, text in (("ai_quality.js", QUALITY_JS),):
        assert not re.search(r"\.(innerHTML|outerHTML)\b|insertAdjacentHTML|document\.write|\beval\(|new Function", text, re.IGNORECASE), name
    assert not re.search(r"""[{,]\s*(on[a-z]+|style)\s*:|['"]\s*(on[a-z]+|style)\s*['"]\s*:""", QUALITY_JS, re.IGNORECASE)  # an attribute: onclick, style
    assert not re.search(r"<\s*(script|img|iframe|style)\b", QUALITY_JS, re.IGNORECASE)
    assert "fetch(" not in QUALITY_JS and "request(" not in QUALITY_JS  # it reaches the server only through the loader it is given
    assert not re.search(r"https?://", QUALITY_JS)  # nothing from the network, nothing to a CDN


def test_the_one_call_is_a_real_admin_route_and_the_admin_screen_mounts_it_after_the_routing_table(tmp_path, foods_json):
    from conftest import make_settings
    from app.main import create_app

    assert "quality: () => request('GET', '/api/admin/ai-quality')," in AI_JS
    assert "KH.aiQuality.adminPart(await api.quality(), api.quality)" in AI_JS
    assert AI_JS.index("KH.aiRouting.adminPart(await api.routing(), refreshProviders)") < AI_JS.index("KH.aiQuality.adminPart(await api.quality(), api.quality)")
    app = create_app(make_settings(tmp_path, foods_json))
    assert {m.upper() for m in app.openapi()["paths"]["/api/admin/ai-quality"]} == {"GET"}


def test_the_demo_and_preview_never_ask_the_server_for_it():
    """``renderAdmin`` answers with a note in the demo and preview and never builds the admin part; the mock has no admin AI routes."""
    assert re.search(r"if \(MOCK\) \{\s*clear\(body\)\.append\(h\('p', \{\}, `AI providers are set up in the installed app", AI_JS)
    assert "ai-quality" not in MOCK_AI and "ai-routing" not in MOCK_AI


def test_the_classes_the_file_uses_are_styled():
    for cls in re.findall(r"class: '(ai-quality[a-z-]*)'", QUALITY_JS):
        assert f".{cls}" in CSS, cls
    assert ".ai-quality .settings-actions .btn { min-height: var(--tap); }" in CSS  # a tap target of 44 px
    assert re.search(r"--tap:\s*44px", (STATIC / "css" / "base.css").read_text(encoding="utf-8"))
    assert "overflow-wrap: anywhere" in CSS[CSS.index("/* How well each AI is doing"):]  # a long model name wraps instead of running off a phone


@pytest.fixture(scope="module")
def page():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "quality_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_row_for_every_feature_it_is_given(page):
    assert page["heading"] == "How well each AI is doing" and page["rows"] == ["meal_ideas", "describe", "labs"]
    assert page["meal"]["text"].startswith("Meal ideas LiteLLM (litellm:4000) · kidney-text In use Last 10 calls in 14 days:")
    assert "Counts only" in page["intro"] and "nobody's questions or answers are shown" in page["intro"]


def test_a_warning_is_a_caution_and_the_rest_is_quiet(page):
    warning = ("Meal ideas: 9 of the last 10 calls to kidney-text had no usable idea (8 'nothing fits', 1 invalid). The app showed the rule results "
               "instead. Check this model with scripts/ai_eval.py, or route meal ideas to another AI.")
    failed = "Failed ai_eval on 2026-10-27: meal-idea cases with at least one idea that passed the checks: 3 % (needs 80 % or more)."
    assert page["meal"]["cautions"] == [warning, failed] == page["both"]  # two separate notes, live first
    assert page["describe"]["cautions"] == [] and "Passed ai_eval on 2026-10-27" in page["describe"]["text"]  # a pass is shown quietly
    assert page["labs"]["cautions"] == [] and "Not covered by ai_eval" in page["labs"]["text"]
    assert set(page["noteRoles"]) == {"note"}


def test_the_reports_folder_line(page):
    folder = page["folder"]
    assert "No reports folder is set" in folder["unset"] and "AI_EVAL_REPORTS_DIR" in folder["unset"]
    assert folder["unreadable"] == ["The reports folder (AI_EVAL_REPORTS_DIR) cannot be read, so the evaluations below cannot be checked."]
    assert folder["read"] == "2 reports read from the reports folder."
    assert folder["left"] == "1 report read from the reports folder. 2 files were not usable and left out."
    assert folder["one"] == "1 report read from the reports folder. 1 file was not usable and left out."


def test_ai_off_and_no_feature_on(page):
    assert page["off"].endswith("AI is switched off, so there is nothing to rate yet.") and page["offRows"] == 0
    assert "reports read" not in page["off"] and "reports folder" not in page["off"]  # with AI off the folder is not read
    assert page["empty"].endswith("No feature is on with an AI behind it yet. Choose one in the table above.")


def test_text_from_the_server_stays_text(page):
    evil = page["evil"]
    assert "<img src=x onerror=alert(1)>" in evil["text"] and "<script>alert(1)</script>" in evil["text"] and "<a href=//evil>x</a>" in evil["text"]
    assert evil["elements"] == [] and evil["attrs"] == []  # no element or attribute the server could make


def test_check_again_fetches_the_numbers_again_and_says_when_it_could_not(page):
    assert page["button"] == {"label": "Check again", "type": "button", "class": "btn secondary", "rowsBefore": ["meal_ideas"]}
    assert page["noButton"] == 0  # no loader, no button
    assert page["again"] == {"calls": 1, "rows": ["describe"], "disabled": False, "status": ""}
    assert page["failed"] == {"calls": 2, "rows": ["describe"], "disabled": False, "status": "Could not check again: Admins only"}
