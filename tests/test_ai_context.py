"""Deferred AI answers must remain bound to the meal, date and recipe inputs they were checked for."""
from pathlib import Path
import shutil
import subprocess


def test_ai_result_context():
    assert shutil.which("node"), "Node.js is required for the AI context regressions"
    runner = Path(__file__).parent / "js" / "ai_context.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
