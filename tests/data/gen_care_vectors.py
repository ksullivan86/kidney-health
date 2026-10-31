#!/usr/bin/env python3
"""Generate tests/data/care_vectors.json: parity vectors for the demo's twin of the full Care team (design note 29).

    python3 tests/data/gen_care_vectors.py           # rewrite the file
    python3 tests/data/gen_care_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/sharing.py`` and ``app/care_suggestions.py``, and replayed by
``node tests/js/run_vectors.mjs`` against ``app/static/js/mock/care.js`` (``KH.mock.care``):

* ``constants``: the switches, the roles and their presets, the suggestion limits, the words guidance never uses
  (``messages.BANNED_PATTERN``) and every fixed sentence the routes answer with;
* ``role_cases``: every mix of the four switches and the role it shows (``custom`` when it matches no preset);
* ``note_cases``: a suggestion's note and why it is refused (null when it may be sent), for a person named Ana.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "care_vectors.json"
sys.path.insert(0, str(ROOT))

from app import care_suggestions as C  # noqa: E402
from app import sharing as S  # noqa: E402
from app.guidance.messages import BANNED_PATTERN  # noqa: E402

NOTES = [
    None, "", "The low-sodium broth is in the pantry.", "Half a cup of rice, about 60 g.", "Try the low-fat yogurt",
    "Take 2 units of insulin first", "If you feel shaky have this", "This one is safe for you", "Not bad at all",
    "Your lab results said so", "Sugar was 3.2 earlier", "I'm low, eat this", "no need to count it", "Skip the binder today",
    "ｉｎｓｕｌｉｎ in full-width letters", "Dinner at 6 with Sam", "Good for dialysis days", "A correction for lunch",
]


def build() -> dict[str, Any]:
    roles = []
    for values in itertools.product([False, True], repeat=len(S.SWITCHES)):
        switches = dict(zip(S.SWITCHES, values))
        roles.append({"switches": switches, "role": S.role_of(switches)})
    return {
        "about": "Made by tests/data/gen_care_vectors.py from app/sharing.py and app/care_suggestions.py (design note 29).",
        "constants": {
            "switches": list(S.SWITCHES), "roles": list(S.ROLES), "presets": S.PRESETS, "areas": list(S.AREAS),
            "suggest_days": C.SUGGEST_DAYS, "max_open_per_share": C.MAX_OPEN_PER_SHARE, "max_per_day": C.MAX_PER_DAY,
            "max_note": C.MAX_NOTE, "max_items": C.MAX_ITEMS, "banned_pattern": BANNED_PATTERN.pattern,
            "texts": {"not_shared": S.NOT_SHARED, "low_treatment": S.LOW_TREATMENT.format("Ana"), "not_your_eaten": S.NOT_YOUR_EATEN,
                      "no_suggestion": C.NO_SUGGESTION, "none_left": C.NONE_LEFT, "too_many_open": C.TOO_MANY_OPEN.format("Ana"),
                      "too_many_today": C.TOO_MANY_TODAY, "low_food": C.LOW_FOOD.format("Glucose tablets", "Ana")},
        },
        "role_cases": roles,
        "note_cases": [{"note": note, "problem": C.note_problem(note, "Ana")} for note in NOTES],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("tests/data/care_vectors.json is stale: run python3 tests/data/gen_care_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
