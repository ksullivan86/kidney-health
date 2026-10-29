"""The recipe apply sheet converts chosen servings to the unchanged API's pot multiplier."""
from pathlib import Path
import shutil
import subprocess


def test_recipe_apply_servings():
    assert shutil.which("node"), "Node.js is required for recipe apply serving regressions"
    runner = Path(__file__).parent / "js" / "recipe_apply_servings.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
