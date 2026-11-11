"""Execute the real menu-plan sheet with held requests in Node."""
import shutil
import subprocess
from pathlib import Path


def test_menu_plan_lifecycle():
    assert shutil.which("node"), "Node is required for the menu-plan lifecycle checks"
    result = subprocess.run(["node", str(Path(__file__).parent / "js" / "menu_plan_lifecycle.test.mjs")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
