"""Offline edits and deletes of log entries in the browser (ARCHITECTURE.md "Offline edits and deletes").

Static checks of ``app/static`` (no browser) for ``js/offline.js``, ``js/core.js``, ``js/views/today.js``,
``js/views/add.js`` and the demo twin ``js/mock/log.js``: an edit or delete of an entry is queueable, the profile and the
targets are not, the request carries ``If-Match`` with the version the person saw, the conflict card says what the
ROADMAP promised and builds its text as text, nothing is inline. The queue logic itself is run in Node by
``tests/js/outbox_changes.mjs`` (below), the card and the whole offline round trip in Chromium by ``tools/e2e/device.py``.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI

from app import log as food_log

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
OFFLINE = (STATIC / "js" / "offline.js").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
ADD = (STATIC / "js" / "views" / "add.js").read_text(encoding="utf-8")
TODAY = (STATIC / "js" / "views" / "today.js").read_text(encoding="utf-8")
MOCK_LOG = (STATIC / "js" / "mock" / "log.js").read_text(encoding="utf-8")
MOCK_CORE = (STATIC / "js" / "mock" / "core.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "device.css").read_text(encoding="utf-8")


def function_source(source: str, name: str) -> str:
    """The text of ``function name(...) {`` up to its closing brace at the same indent."""
    match = re.search(rf"^( *)(?:async )?function {name}\(", source, flags=re.MULTILINE)
    assert match, f"function {name} not found"
    indent = match.group(1)
    end = re.search(rf"^{indent}\}}$", source[match.start():], flags=re.MULTILINE)
    assert end, f"end of {name} not found"
    return source[match.start():match.start() + end.end()]


# --------------------------------------------------------------------------- what is queueable


def test_edits_and_deletes_of_entries_are_queueable_and_nothing_else_new_is() -> None:
    # The existing queueable creates are untouched ...
    assert dict(re.findall(r"'POST (/api/[a-z/\-]+)': '([a-z]+)'", OFFLINE)) == {
        "/api/log": "entry", "/api/log/quick": "quick", "/api/log/mark-eaten": "mark"}
    # ... and the new kinds are only PUT / DELETE of one log entry by its number (or a waiting one by its pending id).
    assert r"const ENTRY_PATH = /^\/api\/log\/(\d+)$/;" in OFFLINE
    assert r"const WAITING_PATH = /^\/api\/log\/pending:([0-9a-f-]{36})$/i;" in OFFLINE
    kind = function_source(OFFLINE, "kindOf")
    assert "method === 'PUT' ? 'edit' : method === 'DELETE' ? 'delete' : null" in kind
    # The profile, targets, labs, foods, meals and settings are not in any queue pattern (least trust: a care team's
    # targets must never be overwritten by a stale offline copy).
    queue_patterns = "\n".join(re.findall(r"^\s*const (?:KINDS|ENTRY_PATH|WAITING_PATH) = .*$", OFFLINE, flags=re.MULTILINE))
    for name in ("profile", "labs", "foods", "meals", "settings", "targets", "me"):
        assert f"/api/{name}" not in queue_patterns, name
    assert "needs a connection" in OFFLINE  # the message of every change that cannot wait is still there
    assert not re.search(r"enqueue\w*\([^)]*profile", OFFLINE)


def test_the_entry_pattern_is_the_servers_route() -> None:
    assert "/api/log/{entry_id}" in {route.path for route in food_log.router.routes}
    app = FastAPI()
    app.include_router(food_log.router)
    schema = app.openapi()["paths"]["/api/log/{entry_id}"]
    for verb in ("put", "delete"):
        assert any(p["name"].lower() == "if-match" and p["in"] == "header" and not p.get("required") for p in schema[verb]["parameters"]), verb
        assert "412" in schema[verb]["responses"], verb


def test_the_fields_compared_after_a_412_are_the_ones_the_version_is_made_of() -> None:
    match = re.search(r"const SAME_FIELDS = \[([^\]]*)\];", OFFLINE)
    assert match
    assert re.findall(r"'([a-z_]+)'", match.group(1)) == list(food_log.VERSION_FIELDS)
    twin = re.search(r"const VERSION_FIELDS = \[([^\]]*)\];", MOCK_LOG)
    assert twin and re.findall(r"'([a-z_]+)'", twin.group(1)) == list(food_log.VERSION_FIELDS)


# --------------------------------------------------------------------------- the request


def test_an_edit_or_delete_sends_the_version_it_was_made_on_as_if_match() -> None:
    assert "const VERSION_TEXT = /^[0-9a-f]{1,64}$/i;" in CORE  # only a version-shaped value ever reaches a header
    assert "{ 'If-Match': `\"${opts.ifMatch}\"` }" in CORE
    assert "mock.request(method, path, body, conditional || undefined)" in CORE  # the demo reads it too
    assert "request('PUT', `/api/log/${id}`, b, conditionOn(base))" in CORE
    assert "request('DELETE', `/api/log/${id}`, undefined, conditionOn(base))" in CORE
    assert "{ ifMatch: base.version, base } : { base }" in CORE  # an old saved copy has no version: handed on without If-Match
    # Every place that changes an entry says which entry (and so which version) the person saw.
    assert "api.updateEntry(sheet.entry.id, body, sheet.entry)" in ADD
    assert "api.deleteEntry(entry.id, entry)" in ADD
    assert "api.updateEntry(e.id, { status: 'eaten' }, e)" in TODAY
    # The outbox sends the stored version with the stored body and never lets a 412 be retried blindly.
    send = function_source(OFFLINE, "sendChange")
    assert "item.version ? { ifMatch: item.version } : {}" in send
    assert "err.status === 412" in send and "err.status === 404" in send
    assert "!item.rebased && sameContent(item.base, current)" in send  # at most one silent resend, and only for our own change
    assert "item.state = 'conflict'" in send
    # Only what the person changed is queued, so "Use mine" never rewrites a field they did not touch.
    assert "changedFields(base, body)" in function_source(OFFLINE, "enqueueChange")
    assert "changedFields(opts.base" in function_source(OFFLINE, "onConflict")
    # A change with no version (a copy saved before versions) is checked against the server first, never sent unchecked.
    assert "!item.version && item.base" in send and "if (!day.ok) { await markFailed(item, day.error); return { failed: 1 }; }" in send
    # Replay is in the order queued and stops at the first network error (the existing rules).
    assert "const r = await sendChange(head);" in OFFLINE and "if (r === STOP) return" in OFFLINE


def test_the_demo_twin_reads_the_header_and_answers_412() -> None:
    assert "async request(method, path, body, headers)" in MOCK_CORE and "header })" in MOCK_CORE
    assert "versionMatches(header('If-Match'), current.version)" in MOCK_LOG
    assert "fail(412, 'This entry was changed on another device', { current })" in MOCK_LOG
    assert "view.version = entryVersion(view);" in MOCK_LOG


# --------------------------------------------------------------------------- what the person sees


def test_the_conflict_card_says_what_the_roadmap_promised() -> None:
    card = function_source(OFFLINE, "conflictCard")
    for text in ("This entry was changed on another device while you were offline", "Keep the saved one", "Use mine",
                 "Saved on your server", "Your change"):
        assert text in card, text
    assert "keepSaved" in card and "useMine" in card
    assert "This entry no longer exists" in OFFLINE
    assert "to review" in OFFLINE  # the header badge counts conflicts
    for text in ("needs review", "waiting to sync", "not saved"):
        assert text in TODAY, text


def test_all_text_of_the_card_goes_in_as_text() -> None:
    # `h()` appends strings as text nodes, so a note with markup is shown as typed (core.js appendChildren).
    assert "document.createTextNode(String(c))" in CORE
    code = function_source(OFFLINE, "conflictCard") + function_source(OFFLINE, "conflictSide") + function_source(OFFLINE, "summaryLines")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "srcdoc", "setAttribute('on", ".style", "setAttribute('style"):
        assert sink not in code, sink
    whole = OFFLINE + CORE + ADD + TODAY
    for sink in ("innerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in whole, sink


def test_nothing_inline_and_the_card_is_styled_from_the_stylesheet() -> None:
    assert not re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", INDEX, re.IGNORECASE), "no inline scripts (CSP)"
    assert not re.search(r"\sstyle\s*=", INDEX, re.IGNORECASE), "no inline style attributes (CSP)"
    for name in ("outbox-item.conflict", "conflict-sides", "conflict-side", "conflict-lines"):
        assert f".{name}" in CSS or name in CSS, name
    assert "!important" not in CSS


def test_a_waiting_entry_is_edited_like_any_other_and_a_conflicting_one_opens_the_device_list() -> None:
    assert "const needsReview = (e) => !!(e.conflict || (e.pending && e.failed));" in TODAY
    assert "if (!needsReview(e)) { views().add.openEntrySheet('edit', { entry: e, trigger: btn }); return; }" in TODAY
    assert "needsReview(e) ? null : eatenButton(e)" in TODAY
    assert "err.conflict" in ADD and "err.conflict" in TODAY


def test_a_low_treatment_gets_no_special_case_in_the_outbox() -> None:
    assert not re.search(r"hypo", function_source(OFFLINE, "enqueueChange"))
    assert not re.search(r"hypo", function_source(OFFLINE, "sendChange"))
    queue_code = function_source(OFFLINE, "intercept") + function_source(OFFLINE, "onConflict")
    assert "hypo" not in queue_code and "warn" not in queue_code.lower()


# --------------------------------------------------------------------------- the queue logic, run in Node


def test_the_node_runner_replays_the_outbox_change_scenarios() -> None:
    assert shutil.which("node"), "Node.js 22 is needed for the JS checks (CLAUDE.md, Parity): install it and run again"
    proc = subprocess.run(["node", str(ROOT / "tests" / "js" / "outbox_changes.mjs")], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "outbox changes:" in proc.stdout and "checks passed" in proc.stdout
