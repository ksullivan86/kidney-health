"""Two overlapping Server administration loads build each part of the page once."""
from pathlib import Path
import shutil
import subprocess


def test_admin_frame_overlapping_loads():
    assert shutil.which("node"), "Node.js is required for the Server administration regressions"
    runner = Path(__file__).parent / "js" / "admin_frame.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
