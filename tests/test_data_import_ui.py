"""Settings → Your data → "Import from a file" (js/views/settings.js, app/data_import.py): static checks of the page
code, that it agrees with the server, and the block run against a fake page (``tests/js/import_page.mjs``, Node.js).
A real browser walk of the screen is still by hand (``tools/e2e`` has no import step yet)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from app import data_import
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = (ROOT / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
MOCK_AUTH_JS = (ROOT / "app" / "static" / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
BLOCK = SETTINGS_JS[SETTINGS_JS.index("// Import from a file (POST /api/me/import"):SETTINGS_JS.index("const ACTION_LABEL = {")]


def test_the_page_checks_with_a_dry_run_first_and_only_then_offers_import() -> None:
    assert "request('POST', `/api/me/import?" in SETTINGS_JS and "['dry_run', 'merge', 'replace_profile']" in SETTINGS_JS
    assert BLOCK.index("dry_run: true") < BLOCK.index("dry_run: false")
    assert "accept: '.json,application/json'" in BLOCK and "type: 'file'" in BLOCK
    assert "go.disabled = !res.can_import" in BLOCK  # a filled account cannot be imported without the choice
    assert "'Add to my existing data'" in BLOCK and "'Also replace my profile, targets and settings'" in BLOCK
    # both choices start off, and a new file starts over
    assert BLOCK.count("options.merge = false; options.replace_profile = false") >= 1
    assert "const options = { merge: false, replace_profile: false }" in BLOCK
    # the recent-password sheet is the app's own (request() asks for it on a 403 reauth_required)
    assert "reauth_required" not in BLOCK and "KH.auth.reauth" not in BLOCK


def test_the_page_agrees_with_the_server_on_what_is_never_sent_and_how_big_a_file_may_be() -> None:
    sent = re.search(r"const IMPORT_NEVER_SENT = \[([^\]]*)\]", BLOCK)
    assert sent and re.findall(r"'([a-z_]+)'", sent.group(1)) == list(data_import.SKIPPED_SECTIONS)
    size = re.search(r"const IMPORT_MAX_BYTES = (\d+) \* 1024 \* 1024;", BLOCK)
    assert size and int(size.group(1)) * 1024 * 1024 == Settings.__dataclass_fields__["max_import_bytes"].default
    shown = {k for k, _, _ in re.findall(r"\['([a-z_]+)', '([^']+)', '([^']+)'\]", BLOCK[BLOCK.index("const IMPORT_KINDS"):BLOCK.index("const IMPORT_SKIP_WHAT")])}
    assert shown == {"log_entries", "custom_foods", "shared_foods_kept_as_own", "shared_foods_linked", "meal_templates",
                     "lab_results", "food_preferences", "settings"}


def test_the_page_never_keeps_the_file_or_builds_html_from_it() -> None:
    for word in ("localStorage", "sessionStorage", "indexedDB", "innerHTML", "console", "postMessage"):
        assert word not in BLOCK, word
    assert "payload = null" in BLOCK  # forgotten when the person finishes or cancels
    # what the server answers (names of foods from the file) is shown as text only
    assert "textContent" in BLOCK or "h('li', {}, t)" in BLOCK


def test_the_preview_has_no_server_and_says_so() -> None:
    demo = BLOCK[BLOCK.index("if (MOCK) {"):BLOCK.index("const fileId")]
    assert "The preview has no server to import into. In the installed app" in demo
    assert "input" not in demo and "request(" not in demo and "A.importData" not in demo


def test_the_activity_list_and_the_preview_know_the_new_event() -> None:
    assert "'data.imported': 'Data imported'" in SETTINGS_JS and "ev.action === 'data.imported'" in SETTINGS_JS
    assert "'data.imported'" in MOCK_AUTH_JS


def _page() -> dict:
    """tests/js/import_page.mjs: the block of settings.js run against a fake page and fake server answers."""
    assert shutil.which("node"), "Node.js 22 is needed to run the page harness (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "import_page.mjs")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_block_reads_the_file_here_and_sends_only_what_the_server_imports() -> None:
    page = _page()
    assert page["input"] == {"type": "file", "accept": ".json,application/json"}
    # a zip, a file that is too big, text that is not JSON and JSON that is not an object never reach the server
    for key in ("zip", "tooBig", "notJson", "notObject"):
        assert page[key]["calls"] == 0 and page[key]["message"], key
    assert "export.json inside it" in page["zip"]["message"]
    first = page["first"]
    assert first["options"] == {"merge": False, "replace_profile": False, "dry_run": True}  # the check comes first, with both choices off
    assert first["keys"] == ["format", "version", "log_entries"]  # user, AI and activity sections are not sent
    assert first["focused"] == "set-import-title" and first["importDisabled"] is False
    assert first["merge"] is False and first["profile"] is False
    assert "Will be added: 2 log entries 1 food of yours 1 saved meal" in first["text"]
    assert "Already here, so left out: 1 log entry" in first["text"]
    assert "Log entry “2026-10-05 lunch: Ghost pie”: its food is not in the file." in first["text"]
    assert "Not imported, because you did not choose it: your profile and targets." in first["text"]
    assert "What is never imported" in first["text"] and "How duplicates are handled" in first["text"]
    assert "null" not in first["text"] and "undefined" not in first["text"]


def test_each_choice_checks_again_and_keeps_the_focus_where_it_was() -> None:
    page = _page()
    assert page["merged"] == {"options": {"merge": True, "replace_profile": False, "dry_run": True}, "focused": "set-import-merge"}
    assert page["profileChosen"] == {"options": {"merge": True, "replace_profile": True, "dry_run": True}, "focused": "set-import-profile"}
    blocked = page["blocked"]
    assert blocked["importDisabled"] is True and "This account already has data (3 log entries, 1 food of yours, 0 saved meals, 0 lab results)" in blocked["text"]
    assert "Will be added" not in blocked["text"]  # nothing is promised while it is refused
    assert "Nothing new to add." in page["nothingNew"] and "null" not in page["nothingNew"]


def test_import_sends_the_checked_choices_then_forgets_the_file_and_the_stale_views() -> None:
    done = _page()["imported"]
    assert done["options"] == {"merge": True, "replace_profile": True, "dry_run": False}
    assert done["message"] == "Imported 2 log entries, 1 food of yours, 2 settings, your profile and targets."
    assert done["toast"] == ["ok", done["message"]] and done["result"] == 0 and done["fileInput"] == ""
    assert all(value is None for value in done["state"].values())  # Today, Plan, Trends, shopping and saved meals reload
    assert done["labsInvalidated"] == 1 and done["profileLoaded"] == 1


def test_a_refusal_is_shown_in_the_page_a_closed_password_prompt_is_not_an_error_and_cancel_forgets() -> None:
    page = _page()
    assert page["refused"]["text"] == "The file was not imported. log_entries[3].servings: must be greater than 0"
    assert page["cancelled"] == {"text": "", "message": "Not checked: the password prompt was closed."}
    assert page["cancel"] == {"message": "Nothing was imported.", "result": 0}
    assert page["demo"]["hasInput"] is False and page["demo"]["calls"] == 0 and "no server to import into" in page["demo"]["text"]
