#!/usr/bin/env python3
"""Print every number of the meal-guidance engine into docs/guidance.md, so the page cannot drift.

    python3 scripts/guidance_rules_doc.py           # rewrite the table between the markers
    python3 scripts/guidance_rules_doc.py --check   # exit 1 when docs/guidance.md is stale

The table comes from ``app.guidance.rules.rules_table()`` and ``rule_notes()`` — the same data
``GET /api/guidance/rules`` returns — and replaces the lines between ``<!-- rules-table:start -->``
and ``<!-- rules-table:end -->``. ``tests/guidance/test_docs.py`` runs the check.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.guidance import rules as R  # noqa: E402

DOC = ROOT / "docs" / "guidance.md"
START, END = "<!-- rules-table:start -->", "<!-- rules-table:end -->"


def value_text(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    return str(text).replace("|", "\\|")


def table() -> str:
    lines = [f"Rules version **{R.RULES_VERSION}** (hash `{R.rules_hash()}`).", "",
             "| Name | Value | Basis |", "|---|---|---|"]
    notes = R.rule_notes()
    for name, value in R.rules_table().items():
        lines.append(f"| `{name}` | `{value_text(value)}` | {notes[name]} |")
    return "\n".join(lines)


def render(text: str) -> str:
    if START not in text or END not in text:
        raise SystemExit(f"{DOC.relative_to(ROOT)} lacks the {START} … {END} markers")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{table()}\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if docs/guidance.md is stale")
    args = parser.parse_args(argv)
    current = DOC.read_text(encoding="utf-8")
    wanted = render(current)
    if args.check:
        if current != wanted:
            print(f"{DOC.relative_to(ROOT)} is stale: run python3 scripts/guidance_rules_doc.py", file=sys.stderr)
            return 1
        print(f"{DOC.relative_to(ROOT)} is up to date")
        return 0
    DOC.write_text(wanted, encoding="utf-8")
    print(f"wrote the rules table of {DOC.relative_to(ROOT)} ({len(R.rules_table())} rules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
