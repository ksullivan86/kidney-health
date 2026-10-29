"""A chat question that gets no answer goes back into the box without wiping what was typed while waiting."""
from pathlib import Path
import shutil
import subprocess


def test_ask_failed_send_keeps_typing():
    assert shutil.which("node"), "Node.js is required for the Ask regressions"
    runner = Path(__file__).parent / "js" / "ask_late_reply.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
