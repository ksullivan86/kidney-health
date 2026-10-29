"""Settings → Account → Sharing: only the newest load of the list draws, and a link just made stays on screen."""
from pathlib import Path
import shutil
import subprocess


def test_sharing_list_newest_load_wins_and_keeps_the_new_link():
    assert shutil.which("node"), "Node.js is required for the sharing list regressions"
    runner = Path(__file__).parent / "js" / "sharing_list_loading.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
