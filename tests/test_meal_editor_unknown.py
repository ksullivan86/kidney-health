"""Saved-meal editor previews keep missing nutrients distinct from zero while ingredients change."""
from pathlib import Path
import shutil
import subprocess


def test_meal_editor_unknown():
    assert shutil.which("node"), "Node.js is required for the saved-meal editor regression"
    runner = Path(__file__).parent / "js" / "meal_editor_unknown.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
