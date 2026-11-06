"""Measurement writes must preserve newer drafts and their displayed units."""
from pathlib import Path
import shutil
import subprocess


def test_body_editor_lifecycle():
    assert shutil.which("node"), "Node.js is required for the body editor lifecycle regression"
    runner = Path(__file__).parent / "js" / "body_editor_lifecycle.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
