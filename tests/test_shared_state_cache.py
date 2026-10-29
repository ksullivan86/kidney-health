"""Shared Profile/saved-meal reads cannot undo completed writes or newer refreshes in browser state."""
from pathlib import Path
import shutil
import subprocess


def test_shared_state_cache_order():
    assert shutil.which("node"), "Node.js is required for the shared-state cache regressions"
    runner = Path(__file__).parent / "js" / "shared_state_cache.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
