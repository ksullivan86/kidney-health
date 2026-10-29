"""Settings → Signed-in devices: only the newest load draws, so a signed-out device does not come back."""
from pathlib import Path
import shutil
import subprocess


def test_signed_in_devices_newest_load_wins():
    assert shutil.which("node"), "Node.js is required for the signed-in devices regressions"
    runner = Path(__file__).parent / "js" / "devices_loading.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
