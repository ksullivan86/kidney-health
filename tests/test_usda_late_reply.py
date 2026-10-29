"""USDA searches and imports that answer late do not mix lists or open the entry sheet after the USDA sheet was left."""
from pathlib import Path
import shutil
import subprocess


def test_usda_sheet_late_replies():
    assert shutil.which("node"), "Node.js is required for the USDA late-reply regressions"
    runner = Path(__file__).parent / "js" / "usda_late_reply.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
