"""Late food-entry writes and reads must preserve the current draft and offline behavior."""
from pathlib import Path
import shutil
import subprocess


def test_food_entry_lifecycle():
    assert shutil.which("node"), "Node.js is required for the food-entry lifecycle regression"
    runner = Path(__file__).parent / "js" / "food_entry_lifecycle.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
