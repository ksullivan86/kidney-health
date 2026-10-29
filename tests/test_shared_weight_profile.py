"""Shared weight charts cannot fall back to their viewer's dry-weight reference."""
from pathlib import Path
import shutil
import subprocess


def test_shared_weight_profile_isolation():
    assert shutil.which("node"), "Node.js is required for the shared weight chart regressions"
    runner = Path(__file__).parent / "js" / "shared_weight_profile.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
