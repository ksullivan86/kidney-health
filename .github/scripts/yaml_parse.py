"""Parse every YAML file in the repository (CI "lint" job). Needs PyYAML (.github/requirements-lint.txt).

    python .github/scripts/yaml_parse.py [ROOT]

Unknown tags (MkDocs' !!python/name: and !ENV, GitHub's none) are accepted as plain values: the
goal is to catch syntax errors and duplicate keys, not to run any constructor. Duplicate mapping
keys are an error because YAML loaders silently keep the last one (a classic way to lose a
securityContext field). Exit 1 on the first broken file, listing every problem found.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

SKIP_DIRS = {".git", "node_modules", "site", ".cache", "__pycache__", ".venv", "venv"}


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that tolerates unknown tags and rejects duplicate keys."""

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError:
                continue
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _any_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


StrictLoader.add_multi_constructor("", _any_tag)
StrictLoader.add_multi_constructor("tag:yaml.org,2002:python/", _any_tag)


def files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.suffix in {".yml", ".yaml"} and path.is_file() and not SKIP_DIRS.intersection(path.relative_to(root).parts):
            yield path


def main(root: Path) -> int:
    problems = 0
    count = 0
    for path in files(root):
        count += 1
        try:
            with path.open(encoding="utf-8") as handle:
                list(yaml.load_all(handle, Loader=StrictLoader))  # noqa: S506 - StrictLoader is a SafeLoader
        except yaml.YAMLError as exc:
            problems += 1
            print(f"FAIL {path.relative_to(root)}: {exc}")
    print(f"{count} YAML files parsed, {problems} with problems")
    return 1 if problems or not count else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
