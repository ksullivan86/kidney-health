"""Symptom writes must preserve newer drafts and their errors."""
from pathlib import Path
import shutil
import subprocess


def test_symptom_editor_lifecycle():
    assert shutil.which("node"), "Node.js is required for the symptom editor lifecycle regression"
    runner = Path(__file__).parent / "js" / "symptom_editor_lifecycle.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
