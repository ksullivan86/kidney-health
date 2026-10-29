"""Today must not show another day's measurements while its weight/BP reads are pending."""
from pathlib import Path
import shutil
import subprocess


def test_body_day_loading():
    assert shutil.which("node"), "Node.js is required for the body-day loading regression"
    runner = Path(__file__).parent / "js" / "body_day_loading.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
