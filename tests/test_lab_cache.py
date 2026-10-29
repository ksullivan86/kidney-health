"""Lab saves/profile changes invalidate both cached data and reads already in flight."""
from pathlib import Path
import shutil
import subprocess


def test_lab_cache_invalidation():
    assert shutil.which("node"), "Node.js is required for the lab-cache regressions"
    runner = Path(__file__).parent / "js" / "lab_cache.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
