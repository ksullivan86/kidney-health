"""Import confirmation stays tied to the checked file until its write finishes."""
from pathlib import Path
import shutil
import subprocess


def test_account_import_lifecycle():
    assert shutil.which("node"), "Node.js is required for the account-import regression"
    runner = Path(__file__).parent / "js" / "account_import_lifecycle.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
