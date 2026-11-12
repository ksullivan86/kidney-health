#!/usr/bin/env python3
"""Generate tests/data/care_vectors.json: parity vectors for the demo's twin of the full Care team (design note 29).

    python3 tests/data/gen_care_vectors.py           # rewrite the file
    python3 tests/data/gen_care_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/sharing.py`` and ``app/care_suggestions.py``, and replayed by
``node tests/js/run_vectors.mjs`` against ``app/static/js/mock/care.js`` (``KH.mock.care``):

* ``constants``: the switches, the roles and their presets, the suggestion limits, the words guidance never uses
  (``messages.BANNED_PATTERN``) and every fixed sentence the routes answer with;
* ``role_cases``: every mix of the four switches and the role it shows (``custom`` when it matches no preset);
* ``note_cases``: a suggestion's note and why it is refused (null when it may be sent), for a person named Ana;
* ``care_notes``: notes from the Care team (design note 37, ``app/care_notes.py``): the limits, the fixed sentences, the dosing
  words, ``text_cases`` (a note's text and why it is refused) and ``day_cases`` (a note's day against a fixed today).
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

from app import care_notes as N  # noqa: E402
from app import care_suggestions as C  # noqa: E402
from app import sharing as S  # noqa: E402
from app.guidance.messages import BANNED_PATTERN  # noqa: E402

NOTES = [
    None, "", "The low-sodium broth is in the pantry.", "Half a cup of rice, about 60 g.", "Try the low-fat yogurt",
    "Take 2 units of insulin first", "If you feel shaky have this", "This one is safe for you", "Not bad at all",
    "Your lab results said so", "Sugar was 3.2 earlier", "I'm low, eat this", "no need to count it", "Skip the binder today",
    "ｉｎｓｕｌｉｎ in full-width letters", "Dinner at 6 with Sam", "Good for dialysis days", "A correction for lunch",
]
NOTE_TEXTS = [
    None, "", "   ", "Your potassium was lower on the days you swapped the potato for rice. Keep that up.",
    "Your lab results look steadier. Let's talk about supplements at the visit.", "This snack is safe on dialysis days.",
    "Low-sodium soup is a good swap.", "Take 2 units before lunch", "Your insulin to carb ratio", "One dose of the binder",
    "If you feel shaky, treat it first", "I'm low", "Sugar was 3.2 earlier", "Dosing is for your diabetes team",
    "A bolus before meals", "Basal rates", "Your pump settings", "A correction at night", "ｉｎｓｕｌｉｎ in full-width letters",
    "  Trimmed at both ends  ", "a" * 1000, "a" * 1001, " " + "b" * 1000 + " ", "Line one\r\nLine two",
    "Phosphorus 5.8 last month, down from 6.4", "Community units for meals",
]
DAY_TODAY = "2026-11-12"
DAYS = [None, "2026-11-12", "2026-11-13", "2026-11-14", "2025-11-12", "2025-11-11", "2026-01-01"]


def build() -> dict[str, Any]:
    roles = []
    for values in itertools.product([False, True], repeat=len(S.SWITCHES)):
        switches = dict(zip(S.SWITCHES, values))
        roles.append({"switches": switches, "role": S.role_of(switches)})
    return {
        "about": "Made by tests/data/gen_care_vectors.py from app/sharing.py, app/care_suggestions.py and app/care_notes.py (design notes 29 and 37).",
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
        "care_notes": {
            "constants": {"max_body": N.MAX_BODY, "max_per_day": N.MAX_PER_DAY, "max_kept": N.MAX_KEPT, "max_page": N.MAX_PAGE,
                          "max_days_back": N.MAX_DAYS_BACK, "dosing_pattern": N.DOSING_PATTERN.pattern,
                          "texts": {"refused": N.NOTE_REFUSED.format("Ana"), "empty": N.EMPTY, "too_long": N.TOO_LONG,
                                    "too_many_today": N.TOO_MANY_TODAY.format("Ana"), "too_many_kept": N.TOO_MANY_KEPT.format("Ana"),
                                    "already_read": N.ALREADY_READ.format("Ana"), "area_not_shared": N.AREA_NOT_SHARED.format("Ana"),
                                    "bad_day": N.BAD_DAY, "no_note": N.NO_NOTE, "changed": N.CHANGED, "send_version": N.SEND_VERSION,
                                    "notes_off": S.NOTES_OFF}},
            "text_cases": [{"text": t, "clean": N.clean_body(t), "problem": N.note_problem(t, "Ana")} for t in NOTE_TEXTS],
            "day_cases": [{"today": DAY_TODAY, "date": d, "problem": N.day_problem(d, DAY_TODAY)} for d in DAYS],
        },
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
