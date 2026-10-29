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
