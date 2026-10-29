"""Run the Today screen's loading/failure/race regressions against its real JavaScript module."""
from pathlib import Path
import shutil
import subprocess


def test_today_loading_and_retry():
    assert shutil.which("node"), "Node.js is required for the Today screen regressions"
    runner = Path(__file__).parent / "js" / "today_loading.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
