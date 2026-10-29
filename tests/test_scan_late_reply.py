"""A late barcode lookup or AI label reading does not act on a Scan or Quick add sheet the person has left."""
from pathlib import Path
import shutil
import subprocess


def test_scan_and_label_photo_late_replies():
    assert shutil.which("node"), "Node.js is required for the scan late-reply regressions"
    runner = Path(__file__).parent / "js" / "scan_late_reply.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
