"""Today Symptoms must clear another day's entries before waiting for its own response."""
from pathlib import Path
import shutil
import subprocess


def test_symptom_day_loading():
    assert shutil.which("node"), "Node.js is required for the symptom-day loading regression"
    runner = Path(__file__).parent / "js" / "symptom_day_loading.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
