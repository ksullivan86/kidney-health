"""A change made to a waiting entry while the outbox is sending it is never lost (tests/js/outbox_inflight.test.mjs)."""
from pathlib import Path
import shutil
import subprocess


def test_changes_made_while_a_send_is_on_its_way_reach_the_server():
    assert shutil.which("node"), "Node.js is required for the outbox checks"
    runner = Path(__file__).parent / "js" / "outbox_inflight.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks passed" in result.stdout


def test_discard_and_sign_out_say_what_happens_to_an_entry_that_may_be_on_the_server():
    """Discard while sending deletes the entry on the server; the sign-out sheet names what it could not delete."""
    source = (Path(__file__).parent.parent / "app" / "static" / "js" / "offline.js").read_text(encoding="utf-8")
    assert "It may have reached your server already. If so, it is deleted there." in source
    assert "An entry that may have reached your server already is deleted there first." in source
    assert "could not be deleted there. Stay signed in and try again later, or sign out and delete" in source
    assert "'Sign out anyway'" in source
    assert "await loseAll()" in source
    # A sheet saved after its entry reached the server goes to the server's entry, never as a second entry.
    assert "return reachedServer(clientId, 'PUT', body, opts);" in source
    assert "return reachedServer(clientId, 'DELETE', undefined, opts);" in source
