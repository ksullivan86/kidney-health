"""Recipe import replies and searches remain attached to their own draft and ingredient."""
from pathlib import Path
import shutil
import subprocess


def test_recipe_import_context():
    assert shutil.which("node"), "Node.js is required for recipe import regression tests"
    runner = Path(__file__).parent / "js" / "recipe_import_context.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
