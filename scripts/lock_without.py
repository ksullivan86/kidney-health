#!/usr/bin/env python3
"""Copy a hash-locked requirements file without some packages.

The iPhone app's CI and TestFlight jobs build the handbook on a Mac with Python 3.14, and the locked watchdog (6.0.0) has
no macOS wheel for 3.14. `mkdocs build` never imports watchdog (only `mkdocs serve` does), and the install runs with
--no-deps, so those jobs leave it out:

    python scripts/lock_without.py handbook/requirements.lock "$RUNNER_TEMP/handbook.lock" watchdog

Every other line, hash included, is copied as it is.
"""

from __future__ import annotations

import re
import sys


def without(lines: list[str], names: set[str]) -> list[str]:
    out, skip = [], False
    for line in lines:
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==", line)
        if m:
            skip = m.group(1).lower().replace("_", "-") in names
        elif not line.startswith((" ", "\t")):
            skip = False  # a comment or a blank line ends the package's block
        if not skip:
            out.append(line)
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    src, dst, names = argv[1], argv[2], {n.lower().replace("_", "-") for n in argv[3:]}
    with open(src, encoding="utf-8") as f:
        lines = f.readlines()
    kept = without(lines, names)
    found = {m.group(1).lower() for line in lines if (m := re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==", line))}
    missing = names - found
    if missing:
        print(f"Not in {src}: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1
    with open(dst, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
