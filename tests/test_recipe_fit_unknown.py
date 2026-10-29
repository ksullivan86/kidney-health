"""Recipe fit rows must distinguish known zero from missing or partial nutrient values."""
from pathlib import Path
import shutil
import subprocess


def test_recipe_fit_unknown():
    assert shutil.which("node"), "Node.js is required for the recipe fit regressions"
    runner = Path(__file__).parent / "js" / "recipe_fit_unknown.test.mjs"
    result = subprocess.run(["node", str(runner)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
