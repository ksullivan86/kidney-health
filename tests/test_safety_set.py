"""The named safety set: ``python -m pytest -m safety`` (CONTRIBUTING.md, "Tests"; design note 14 section 4 change 7).

The health-data safety rules of CLAUDE.md must travel with any piece of this code that is reused elsewhere: no insulin
or medicine dosing, never block or warn against treating a low, handbook text quoted word for word, and the AI guard
and prefilter that run before and after any model call. Their tests carry ``@pytest.mark.safety`` (a module-level
``pytestmark`` where the whole file is one rule, the single test where a file mixes rules and ordinary behaviour).

This test only collects (nothing runs, no network, a few seconds) and fails when the set quietly shrinks: the marker is
no longer registered, the set is empty, a file loses its last safety test, or the AI golden runner stops marking its
``safety-*`` and ``prefilter-*`` cases. When you mark the first test of a new file, add the file to ``SAFETY_FILES``.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Every file that holds at least one test marked ``safety``; each must keep at least one.
SAFETY_FILES = (
    # no dosing, quoted handbook text, red flags, nothing about weights, readings or symptoms goes to an AI
    "tests/test_handbook_content.py",
    "tests/test_body.py",
    "tests/test_symptoms.py",
    "tests/test_symptoms_ui.py",
    "tests/test_lab_photo.py",
    "tests/test_mcp.py",
    "tests/test_mcp_write.py",
    "tests/guidance/test_messages.py",
    # the AI guard, the dose check, the prefilter and the golden safety cases
    "tests/test_ai_guard.py",
    "tests/test_ai_guard_twin.py",
    "tests/test_ai_chat_checks.py",
    "tests/test_ai_chat.py",
    "tests/test_ai_chat_save.py",
    "tests/test_ai_golden.py",
    "tests/test_ai_prompts.py",
    "tests/test_ai_profile_prompts.py",
    "tests/test_ai_routes.py",
    "tests/guidance/test_ai_bridge.py",
    # a low is never blocked, warned against, limited or shrunk; free text that may describe a low gets the card, no model call
    "tests/guidance/test_hypo.py",
    "tests/test_nutrients.py",
    "tests/test_potassium_additive.py",
    "tests/test_rules_vectors.py",
    "tests/test_food_db.py",
    "tests/test_tolerance.py",
    "tests/guidance/test_api_guidance.py",
    "tests/guidance/test_budget.py",
    "tests/guidance/test_insights.py",
    "tests/guidance/test_log_api.py",
    "tests/guidance/test_planner.py",
    "tests/guidance/test_preferences.py",
    "tests/guidance/test_preferences_api.py",
    "tests/guidance/test_swaps.py",
    # food safety named in the handbook (no raw egg is ever suggested)
    "tests/guidance/test_food_safety.py",
)

# Files that skip as a whole where PyYAML is not installed: Python 3.15, which has no PyYAML wheel yet
# (requirements-dev.in), so none of their tests is collected there. Below 3.15 a missing PyYAML is a collection
# error instead, which fails the collection run above.
NEEDS_YAML = frozenset({"tests/test_handbook_content.py"})


def required_files() -> list[str]:
    """The files of SAFETY_FILES that must hold a collected safety test in this environment."""
    if importlib.util.find_spec("yaml") is None:
        return [name for name in SAFETY_FILES if name not in NEEDS_YAML]
    return list(SAFETY_FILES)


@pytest.fixture(scope="module")
def collected() -> list[str]:
    """The node ids of the tests marked ``safety``, from a collection-only run of the whole suite in a fresh process.

    ``--strict-markers`` makes an unregistered marker an error; ``-o addopts=`` keeps the output one node id per line."""
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "safety", "--strict-markers", "-o", "addopts=",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=300, check=False,
    )
    assert run.returncode == 0, f"collecting the safety set failed:\n{run.stdout}\n{run.stderr}"
    return [line for line in run.stdout.splitlines() if "::" in line]


def test_the_safety_marker_selects_a_set(collected):
    assert collected, "no test is marked `safety`: the set that must travel with any reused piece is empty"


def test_the_listed_files_exist():
    missing = [name for name in SAFETY_FILES if not (ROOT / name).is_file()]
    assert not missing, f"SAFETY_FILES names files that do not exist: {missing}"
    assert len(set(SAFETY_FILES)) == len(SAFETY_FILES)
    assert NEEDS_YAML <= set(SAFETY_FILES)


def test_every_listed_file_still_has_a_safety_test(collected):
    files = {node.split("::", 1)[0] for node in collected}
    lost = [name for name in required_files() if name not in files]
    assert not lost, (
        f"these files no longer hold a test marked `safety`: {lost}. A safety rule must not lose its test quietly: "
        "restore the mark, or move the rule's test and update SAFETY_FILES in the same change."
    )


def test_the_ai_golden_runner_marks_its_safety_and_prefilter_cases(collected):
    for prefix in ("safety-", "prefilter-"):
        assert any(node.startswith(f"tests/test_ai_golden.py::test_golden_case[{prefix}") for node in collected), prefix
