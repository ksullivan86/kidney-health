"""Shared day views reject stale replies and retry the selected person and date."""
from pathlib import Path
import shutil
import subprocess


def test_shared_day_loading():
    assert shutil.which("node"), "Node.js is required for the shared-day regressions"
    runner = Path(__file__).parent / "js" / "shared_day_loading.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
