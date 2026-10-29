"""Add tab: a failed search shows in place of the old results, with Retry, under the new search."""
from pathlib import Path
import shutil
import subprocess


def test_failed_food_search_replaces_old_results():
    assert shutil.which("node"), "Node.js is required for the food search regressions"
    runner = Path(__file__).parent / "js" / "food_search_failed.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
