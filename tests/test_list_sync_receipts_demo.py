"""The demo clears receipts for a changed list, key or address, as the server does."""
from pathlib import Path
import subprocess


def test_demo_list_receipts():
    runner = Path(__file__).parent / "js" / "list_sync_receipts.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
