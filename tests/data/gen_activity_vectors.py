#!/usr/bin/env python3
"""Generate tests/data/activity_vectors.json: parity vectors for the browser twin of the active-day calorie extra.

    python3 tests/data/gen_activity_vectors.py           # rewrite the file
    python3 tests/data/gen_activity_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/activity.py`` (design note 28 §4.2), and replayed by ``node tests/js/run_vectors.mjs``
against ``app/static/js/engine/activity.js``:

* ``constants``: the window, the minimum days, the percentile, the share and ceiling limits;
* ``quiet_cases``: a list of finished days' calories and the usual quiet-day level (or null);
* ``extra_cases``: a setting, a calorie target, the day's Whoop calories and the history, with what Today shows
  (``calorie_extra``) and the raised calorie target.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "activity_vectors.json"
sys.path.insert(0, str(ROOT))

from app import activity as A  # noqa: E402

QUIET = [2100, 2150, 2200, 2250, 2300, 2350, 2400, 2450, 2500, 2550, 2600, 2650, 2700, 2750]  # 14 days, quartile 2250


def quiet_cases() -> list[dict[str, Any]]:
    lists = {
        "none": [],
        "13 days: not enough": QUIET[:13],
        "14 days": QUIET,
        "14 days, unsorted": list(reversed(QUIET)),
        "28 days": QUIET + [v + 25 for v in QUIET],
        "15 days (rank rounds up)": QUIET + [1900],
        "zeros and gaps are not days": QUIET[:13] + [0, None, -5],
        "fractions are not whole kcal": QUIET[:13] + [2222.5],
        "true is not a number": QUIET[:13] + [True],
        "all the same": [2000] * 20,
    }
    return [{"name": k, "history": v, "quiet_kcal": A.quiet_level(v)} for k, v in lists.items()]


def extra_cases() -> list[dict[str, Any]]:
    on = {"enabled": True, "share_pct": 100, "ceiling_kcal": None}
    cases = [
        ("off: nothing", {**on, "enabled": False}, 2000, 3000, QUIET),
        ("on, an active day: all of it", on, 2000, 3000, QUIET),
        ("on, a quiet day: no extra", on, 2000, 2100, QUIET),
        ("on, exactly the quiet level", on, 2000, 2250, QUIET),
        ("half of it", {**on, "share_pct": 50}, 2000, 3000, QUIET),
        ("half, rounding half up to 10", {**on, "share_pct": 50}, 2000, 2260, QUIET),
        ("a third, rounding down", {**on, "share_pct": 33}, 2000, 2264, QUIET),
        ("ceiling", {**on, "ceiling_kcal": 400}, 2000, 3000, QUIET),
        ("ceiling not reached", {**on, "ceiling_kcal": 1000}, 2000, 3000, QUIET),
        ("10 percent and a ceiling", {**on, "share_pct": 10, "ceiling_kcal": 50}, 2000, 4000, QUIET),
        ("waiting for 14 days", on, 2000, 3000, QUIET[:13]),
        ("no Whoop figure", on, 2000, None, QUIET),
        ("a Whoop figure of 0", on, 2000, 0, QUIET),
        ("no calorie target", on, None, 3000, QUIET),
        ("a range target moves both ends", on, {"min": 1800, "max": 2200}, 3000, QUIET),
        ("a range with only a minimum", on, {"min": 1800, "max": None}, 3000, QUIET),
        ("a fractional target", on, 2012.5, 2600, QUIET),
        ("a 28-day history", on, 2000, 3300, QUIET + [v + 25 for v in QUIET]),
    ]
    out = []
    for name, setting, target, burned, history in cases:
        info = A.calorie_extra(setting, target, burned, history)
        out.append({"name": name, "setting": setting, "target": target, "burned": burned, "history": history,
                    "calorie_extra": info, "raised": A.raised(target, info["extra_kcal"]) if info else target})
    return out


def build() -> dict[str, Any]:
    return {
        "constants": {"window_days": A.QUIET_WINDOW_DAYS, "min_days": A.QUIET_MIN_DAYS, "percentile": A.QUIET_PERCENTILE,
                      "share_default": A.SHARE_DEFAULT, "share_min": A.SHARE_MIN, "share_max": A.SHARE_MAX,
                      "ceiling_min": A.CEILING_MIN, "ceiling_max": A.CEILING_MAX},
        "quiet_cases": quiet_cases(),
        "extra_cases": extra_cases(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("tests/data/activity_vectors.json is stale: run python3 tests/data/gen_activity_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
