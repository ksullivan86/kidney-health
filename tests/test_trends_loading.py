"""The Trends screen clears the last person's data while a new read is pending or fails."""
from pathlib import Path
import shutil
import subprocess


def test_trends_loading_and_source_changes():
    assert shutil.which("node"), "Node.js is required for the Trends loading regressions"
    runner = Path(__file__).parent / "js" / "trends_loading.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
