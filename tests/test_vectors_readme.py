"""``tests/data/README.md`` keeps up with the vector files it describes (design note 14, change 6).

The README is for anyone replaying the JSON vectors in another client. These tests keep it honest without reading its prose:

* every ``tests/data/*_vectors.json`` file has a ``## <file name>`` section, and every such section names a file that exists;
* every generator path the README mentions exists, and every generator that exists is mentioned;
* every repository path the README mentions exists;
* the "Top-level keys:" list of a section names exactly the top-level keys of its file.

The convention the README follows, so a person editing it knows what is read: a section is a ``## <name>_vectors.json`` heading, and it
holds one line ``Top-level keys:`` followed by a list whose items each start with the key in backticks (``* `cases`: ...``). A line
indented under an item continues it. The list ends at the first line that is blank or not part of it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
README = DATA / "README.md"

VECTOR_FILES = sorted(p.name for p in DATA.glob("*_vectors.json"))
KEYS_LINE = "Top-level keys:"
GENERATOR = re.compile(r"(?<![\w/.-])tests/(?:data|js)/gen_\w+_vectors\.(?:py|mjs)\b")
REPO_PATH = re.compile(r"(?<![\w/.-])(?:app|tests|docs|scripts|data)/[\w./-]*\w\.(?:py|js|mjs|json|md)\b")


def sections() -> dict[str, str]:
    """The text under each ``## <name>_vectors.json`` heading, by file name."""
    found: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in README.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"## (.+?)\s*$", line)
        if heading:
            if name is not None:
                found[name] = "\n".join(lines)
            name = heading.group(1) if heading.group(1).endswith("_vectors.json") else None
            lines = []
        elif name is not None:
            lines.append(line)
    if name is not None:
        found[name] = "\n".join(lines)
    return found


def listed_keys(section: str) -> list[str]:
    """The keys under the section's one ``Top-level keys:`` line, in the order written."""
    lines = section.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == KEYS_LINE]
    assert len(starts) == 1, f'a section needs exactly one "{KEYS_LINE}" line, found {len(starts)}'
    keys: list[str] = []
    i = starts[0] + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines):
        item = re.match(r"\* `([^`]+)`", lines[i])
        if item:
            keys.append(item.group(1))
        elif not (lines[i].startswith(" ") and lines[i].strip()):
            break
        i += 1
    return keys


def test_there_are_vector_files_to_describe():
    assert len(VECTOR_FILES) >= 17, VECTOR_FILES
    assert README.is_file()


def test_every_vector_file_has_a_section_and_every_section_has_a_file():
    names = set(sections())
    assert set(VECTOR_FILES) - names == set(), "vector files with no `## <file name>` section in tests/data/README.md"
    assert names - set(VECTOR_FILES) == set(), "sections in tests/data/README.md that name a file which does not exist"


def test_every_section_name_is_unique():
    headings = re.findall(r"^## (.+?)\s*$", README.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert len(headings) == len(set(headings)), "a heading appears twice in tests/data/README.md"


@pytest.mark.parametrize("name", VECTOR_FILES)
def test_the_listed_top_level_keys_are_the_files_keys(name):
    section = sections().get(name)
    assert section is not None, f"tests/data/README.md has no section for {name}"
    listed = listed_keys(section)
    assert len(listed) == len(set(listed)), f"{name}: a key is listed twice"
    actual = json.loads((DATA / name).read_text(encoding="utf-8"))
    assert isinstance(actual, dict), name
    assert set(listed) - set(actual) == set(), f"{name}: the README lists keys the file does not have"
    assert set(actual) - set(listed) == set(), f"{name}: the file has keys the README does not list"


def test_every_generator_path_in_the_readme_exists_and_every_generator_is_in_the_readme():
    text = README.read_text(encoding="utf-8")
    mentioned = set(GENERATOR.findall(text))
    assert mentioned, "the README names no generator"
    missing = sorted(path for path in mentioned if not (ROOT / path).is_file())
    assert missing == [], f"generators in tests/data/README.md that do not exist: {missing}"
    existing = {p.relative_to(ROOT).as_posix() for folder in (DATA, ROOT / "tests" / "js") for p in folder.glob("gen_*_vectors.*")}
    assert existing - mentioned == set(), "generators that tests/data/README.md does not mention"


def test_every_repository_path_in_the_readme_exists():
    text = README.read_text(encoding="utf-8")
    paths = set(REPO_PATH.findall(text))
    assert len(paths) > 20, "the path pattern found almost nothing, so it no longer checks anything"
    missing = sorted(path for path in paths if not (ROOT / path).exists())
    assert missing == [], f"paths in tests/data/README.md that do not exist: {missing}"


def test_the_readme_names_the_two_commands_that_check_the_vectors():
    text = README.read_text(encoding="utf-8")
    assert "python -m pytest" in text
    assert "node tests/js/run_vectors.mjs" in text
    assert (ROOT / "tests" / "js" / "run_vectors.mjs").is_file()
