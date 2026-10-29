"""Shared symptom/weight cards clear old data before loading another person or period."""
from pathlib import Path
import shutil
import subprocess


def test_shared_health_loading():
    assert shutil.which("node"), "Node.js is required for the shared health loading regressions"
    runner = Path(__file__).parent / "js" / "shared_health_loading.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
