"""Run the real saved-meal sheets with held search, load and write replies."""
from pathlib import Path
import shutil
import subprocess


def test_saved_meal_lifecycle():
    assert shutil.which("node"), "Node.js is required for the saved-meal regression"
    runner = Path(__file__).parent / "js" / "saved_meal_lifecycle.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
