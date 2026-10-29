"""Recipe mutations and Undo stay attached to the recipe and result that were confirmed."""
from pathlib import Path
import shutil
import subprocess


def test_recipe_fit_context():
    assert shutil.which("node"), "Node.js is required for recipe Fit context regressions"
    runner = Path(__file__).parent / "js" / "recipe_fit_context.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
