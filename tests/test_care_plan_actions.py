"""Care team clearing confirms fixed dates and an uncertain plan send cannot be replayed."""
from pathlib import Path
import subprocess


def test_care_plan_actions():
    runner = Path(__file__).parent / "js" / "care_plan_actions.test.mjs"
    result = subprocess.run(["node", "--test", str(runner)], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
