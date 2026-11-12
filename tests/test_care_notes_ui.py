"""The screens of notes from the Care team (design note 37; ``js/views/notes.js``, ``js/views/sharing.js``).

Static checks of the page (the Notes view, the Today card, the Visit prep line, the Write a note sheet and buttons, the script and
the offline list), the words the person reads where they choose the Clinician role, and the Node run of the view itself
(``tests/js/notes_ui.test.mjs``) and of the demo's twin (``tests/js/care_demo.mjs`` covers the routes).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
NOTES = (STATIC / "js" / "views" / "notes.js").read_text(encoding="utf-8")
SHARING = (STATIC / "js" / "views" / "sharing.js").read_text(encoding="utf-8")


def test_the_page_has_the_notes_view_the_today_card_the_visit_line_and_the_sheet():
    for needle in ('<section id="view-notes"', 'id="today-notes"', 'id="visit-notes-line"', 'id="visit-note-actions"',
                   'id="trends-note-actions"', '<dialog id="sheet-note"', 'id="note-body"', 'maxlength="1000"', 'id="note-send"'):
        assert needle in INDEX, needle
    scripts = [line.split('"')[1] for line in INDEX.splitlines() if line.startswith("<script src=")]
    assert scripts.index("js/views/suggestions.js") < scripts.index("js/views/notes.js") < scripts.index("js/main.js")
    assert "'/js/views/notes.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")
    assert "'visit', 'notes', 'admin'" in (STATIC / "js" / "core.js").read_text(encoding="utf-8")
    # the Today card sits under the day's alerts: it moves nothing above it
    assert INDEX.index('id="projected-alerts"') < INDEX.index('id="today-notes"') < INDEX.index('id="status-heading"')
    # notes are never printed
    css = (STATIC / "css" / "visit.css").read_text(encoding="utf-8")
    assert ".note-actions, .visit-notes-line, .today-notes, #view-notes { display: none !important; }" in css


def test_notes_are_plain_text_and_never_reach_the_ai():
    assert "innerHTML" not in NOTES and "insertAdjacentHTML" not in NOTES
    assert "/api/ai" not in NOTES and "KH.ai" not in NOTES
    assert "noQueue: true" in NOTES  # never queued offline


def test_the_clinician_choice_says_what_a_note_is_not():
    assert "clinician: 'Clinician'" in SHARING
    assert ("'Notes are messages for you. They are not a medical record and never change your targets, labs or medicines. '\n"
            "    + 'The app does not check who someone is.'") in SHARING
    assert "may_note: 'Write notes for me'" in SHARING
    assert "Keep your own record as your clinic requires." in SHARING


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_notes_view_in_node():
    runner = Path(__file__).parent / "js" / "notes_ui.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_demo_twin_in_node():
    runner = Path(__file__).parent / "js" / "care_notes_demo.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
