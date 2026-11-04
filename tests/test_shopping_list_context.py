"""Late shopping previews and send results stay with the sheet that requested them."""
from pathlib import Path
import shutil
import subprocess


def test_shopping_list_request_context():
    assert shutil.which("node"), "Node.js is required for the shopping list regressions"
    runner = Path(__file__).parent / "js" / "shopping_list_context.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
