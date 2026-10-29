"""Saved-meal cards distinguish unknown nutrient values from listed zero."""
from pathlib import Path
import shutil
import subprocess


def test_saved_meal_nutrient_numbers():
    assert shutil.which("node"), "Node.js is required for the saved-meal screen regressions"
    runner = Path(__file__).parent / "js" / "saved_meal_numbers.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
