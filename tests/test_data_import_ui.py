"""Settings → Your data → "Import from a file" (js/views/settings.js, app/data_import.py): static checks of the page
code, that it agrees with the server, and the block run against a fake page (``tests/js/import_page.mjs``, Node.js).
It takes the export .zip itself or the export.json inside it (``js/engine/zip.js``, note 11): the archives for the .zip picks are built here.
The real browser walk of the screen is ``tools/e2e/import_walk.py``."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest
from zip_support import STORED, Item, build, deflated, zipfile_bytes

from app import data_import
from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = (ROOT / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
MOCK_AUTH_JS = (ROOT / "app" / "static" / "js" / "mock" / "auth.js").read_text(encoding="utf-8")
BLOCK = SETTINGS_JS[SETTINGS_JS.index("// Import from a file (POST /api/me/import"):SETTINGS_JS.index("const ACTION_LABEL = {")]


def test_the_page_checks_with_a_dry_run_first_and_only_then_offers_import() -> None:
    assert "request('POST', `/api/me/import?" in SETTINGS_JS and "['dry_run', 'merge', 'replace_profile']" in SETTINGS_JS
    assert BLOCK.index("dry_run: true") < BLOCK.index("dry_run: false")
    assert "accept: '.zip,.json,application/zip,application/json'" in BLOCK and "type: 'file'" in BLOCK
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
                     "lab_results", "symptoms", "food_preferences", "settings"}


def test_the_page_never_keeps_the_file_or_builds_html_from_it() -> None:
    for word in ("localStorage", "sessionStorage", "indexedDB", "innerHTML", "console", "postMessage"):
        assert word not in BLOCK, word
    assert "payload = null" in BLOCK  # forgotten when the person finishes or cancels
    # what the server answers (names of foods from the file) is shown as text only
    assert "textContent" in BLOCK or "h('li', {}, t)" in BLOCK


def test_the_preview_has_no_server_and_says_so() -> None:
    demo = BLOCK[BLOCK.index("if (MOCK && !(KH.demoLocal && KH.demoLocal.on())) {"):BLOCK.index("const fileId")]
    assert "The preview has no server to import into. In the installed app" in demo
    assert "input" not in demo and "request(" not in demo and "A.importData" not in demo


def test_the_activity_list_and_the_preview_know_the_new_event() -> None:
    assert "'data.imported': 'Data imported'" in SETTINGS_JS and "ev.action === 'data.imported'" in SETTINGS_JS
    assert "'data.imported'" in MOCK_AUTH_JS


# --------------------------------------------------------------------------- the block, run against a fake page
DOC = {"format": "kidney-health-export", "version": 1, "user": {"username": "sam"}, "ai_audit": [{"prompt": "x"}], "activity": [], "ai_usage": [],
       "ai_consents": [], "ai_provider": {"api_key": "secret"}, "log_entries": []}
BIG = 17 * 1024 * 1024


def build_zips(folder: Path) -> None:
    """The archives the .zip picks use, by file name: what an export of this app looks like, and every way it can go wrong."""
    doc = json.dumps(DOC).encode()
    deflate, plain = zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED
    files = {
        "export_ok.zip": zipfile_bytes([("export.json", doc, deflate), ("log.csv", b"a,b\n", deflate), ("README.txt", b"hello", plain)]),
        "rezipped.zip": zipfile_bytes([("kidney-health-sam/", b"", plain), ("kidney-health-sam/export.json", doc, deflate),
                                       ("__MACOSX/kidney-health-sam/._export.json", b"\x00\x05\x16\x07", plain)]),
        "no_export.zip": zipfile_bytes([("log.csv", b"a,b\n", deflate), ("README.txt", b"hello", plain)]),
        "two_exports.zip": zipfile_bytes([("one/export.json", doc, deflate), ("two/export.json", doc, deflate)]),
        "damaged.zip": build([deflated("export.json", doc, crc=zlib.crc32(doc) ^ 1)]),
        "encrypted.zip": build([Item("export.json", bytes(40), STORED, flags=1)]),
        "not_json.zip": zipfile_bytes([("export.json", b"not json", deflate)]),
        "array.zip": zipfile_bytes([("export.json", b"[1, 2]", deflate)]),
        "not_a_zip.zip": b"PK\x03\x04 this only starts like a zip",
        "too_big.zip": zipfile_bytes([("export.json", b'{"padding": "' + b"x" * BIG + b'"}', deflate)]),
    }
    for name, content in files.items():
        (folder / name).write_bytes(content)
    (folder / "sizes.json").write_text(json.dumps({"too_big": BIG + len(b'{"padding": ""}')}), encoding="utf-8")


@pytest.fixture(scope="module")
def page(tmp_path_factory) -> dict:
    """tests/js/import_page.mjs: the block of settings.js run against a fake page and fake server answers."""
    assert shutil.which("node"), "Node.js 22 is needed to run the page harness (CLAUDE.md, Parity)"
    folder = tmp_path_factory.mktemp("import_zips")
    build_zips(folder)
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "import_page.mjs"), str(folder)], capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_block_reads_the_file_here_and_sends_only_what_the_server_imports(page) -> None:
    assert page["input"] == {"type": "file", "accept": ".zip,.json,application/zip,application/json"}
    assert "Your export (.zip or export.json)" in page["block"]
    assert ("Moving to another server, or starting again? Choose the .zip from an export of yours, or the export.json inside it. "
            "You see what would be added before anything is changed.") in page["block"]
    assert "open the .zip first" not in page["block"]
    # a file that is not a zip at all, one that is too big, text that is not JSON and JSON that is not an object never reach the server
    for key in ("zip", "tooBig", "notJson", "notObject"):
        assert page[key]["calls"] == 0 and page[key]["message"], key
    assert "could not be read" in page["zip"]["message"] and "export.json inside it" in page["zip"]["message"]
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


def test_each_choice_checks_again_and_keeps_the_focus_where_it_was(page) -> None:
    assert page["merged"] == {"options": {"merge": True, "replace_profile": False, "dry_run": True}, "focused": "set-import-merge"}
    assert page["profileChosen"] == {"options": {"merge": True, "replace_profile": True, "dry_run": True}, "focused": "set-import-profile"}
    blocked = page["blocked"]
    assert blocked["importDisabled"] is True and "This account already has data (3 log entries, 1 food of yours, 0 saved meals, 0 lab results, 0 symptoms)" in blocked["text"]
    assert "Will be added" not in blocked["text"]  # nothing is promised while it is refused
    assert "Nothing new to add." in page["nothingNew"] and "null" not in page["nothingNew"]


def test_import_sends_the_checked_choices_then_forgets_the_file_and_the_stale_views(page) -> None:
    done = page["imported"]
    assert done["options"] == {"merge": True, "replace_profile": True, "dry_run": False}
    assert done["message"] == "Imported 2 log entries, 1 food of yours, 2 settings, your profile and targets."
    assert done["toast"] == ["ok", done["message"]] and done["result"] == 0 and done["fileInput"] == ""
    assert all(value is None for value in done["state"].values())  # Today, Plan, Trends, shopping and saved meals reload
    assert done["labsInvalidated"] == 1 and done["profileLoaded"] == 1


def test_a_refusal_is_shown_in_the_page_a_closed_password_prompt_is_not_an_error_and_cancel_forgets(page) -> None:
    assert page["refused"]["text"] == "The file was not imported. log_entries[3].servings: must be greater than 0"
    # the file box is emptied, so choosing the same file again checks it again (a browser fires no `change` otherwise)
    assert page["cancelled"] == {"text": "", "message": "Not checked: the password prompt was closed.", "fileInput": ""}
    assert page["cancel"] == {"message": "Nothing was imported.", "result": 0}
    assert page["demo"]["hasInput"] is False and page["demo"]["calls"] == 0 and "no server to import into" in page["demo"]["text"]
    assert "the export .zip or the export.json here" in page["demo"]["text"]


# --------------------------------------------------------------------------- a .zip pick
UNREADABLE = ("This .zip could not be read (it may be damaged or not finished downloading). Download the export again, or open it on your "
              "device and choose the export.json inside it.")


def test_a_zip_is_opened_on_the_device_and_reaches_the_same_check_as_the_export_json_inside_it(page) -> None:
    zips = page["zips"]
    same = zips["json"]
    assert same["calls"] == 1 and same["keys"] == ["format", "version", "log_entries"]
    # by name, by type alone (a name without .zip), by a capital name alone (no type), and from a re-zipped folder with the macOS extras
    for key in ("plain", "rezipped", "byType", "byNameOnly"):
        got = zips[key]
        assert got["calls"] == 1, key
        assert got["options"] == {"merge": False, "replace_profile": False, "dry_run": True}, key  # the dry run comes first, as for a json
        assert got["keys"] == ["format", "version", "log_entries"], key  # the sections the import never reads are not sent, from a zip either
        assert got["text"] == same["text"] and got["focused"] == "set-import-title" and got["importDisabled"] is False and got["message"] == "", key


def test_each_way_a_zip_can_fail_says_so_in_plain_words_and_sends_nothing(page) -> None:
    zips = page["zips"]
    want = {
        "missing": "This .zip has no export.json in it, so it is not an export from this app.",
        "ambiguous": "This .zip holds more than one export.json. Open it and choose the one you want.",
        "damaged": UNREADABLE,  # a checksum that does not match
        "encrypted": UNREADABLE,
        "notZip": UNREADABLE,
        "tooBig": f"The export.json in that .zip is {zips['sizes']['too_big']} B; the largest this app imports is {16 * 1024 * 1024} B.",
        "notJson": "This is not an export.json file (it is not JSON). Choose the export.json from your export.",
        "notObject": "This is not an export.json file (it is not JSON). Choose the export.json from your export.",
        "browser": "This browser cannot open a .zip here. Open the .zip on your device and choose the export.json inside it.",
    }
    for key, message in want.items():
        assert zips[key]["message"] == message, key
        assert zips[key]["calls"] == 0 and zips[key]["result"] == 0, key


def test_choosing_again_while_a_zip_is_being_read_checks_only_the_second_choice_and_cancel_forgets_a_zip(page) -> None:
    race = page["zips"]["race"]
    assert race["calls"] == 1 and race["keys"] == ["format,version,log_entries,second"] and race["message"] == ""
    assert page["zips"]["cancel"] == {"message": "Nothing was imported.", "result": 0, "fileInput": ""}
    assert page["zips"]["nothing"] == {"message": "", "result": 0}


def test_the_zip_path_uses_the_reader_and_nothing_else_of_the_archive() -> None:
    zip_part = BLOCK[BLOCK.index("async function textFromZip"):BLOCK.index("input.addEventListener('change'")]
    assert "zip.open(file)" in zip_part and "zip.find(archive, zip.RULES.exportJson)" in zip_part
    assert "zip.text(archive, entry, { maxBytes: IMPORT_MAX_BYTES, signal: ctrl.signal })" in zip_part  # only the export.json, capped, abortable
    assert "zip.supported()" in zip_part and "IMPORT_ZIP_MESSAGE.browser" in zip_part
    for word in ("innerHTML", "localStorage", "indexedDB", "fetch(", "XMLHttpRequest"):
        assert word not in zip_part, word
    # every message is a constant of the page: the archive's own words never reach it
    assert "err.message" not in zip_part and "entry.name" not in zip_part
