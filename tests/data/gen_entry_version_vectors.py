#!/usr/bin/env python3
"""Generate tests/data/entry_version_vectors.json: parity vectors for the browser twin of entry versions and If-Match.

    python3 tests/data/gen_entry_version_vectors.py           # rewrite the file
    python3 tests/data/gen_entry_version_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code (``app/log.py``: ``entry_version``, ``version_matches`` and the ``PUT`` / ``DELETE``
routes of ``/api/log/{id}``) and replayed on the JavaScript side by ``node tests/js/run_vectors.mjs`` against the demo API
(``app/static/js/mock/log.js``: ``entryVersion``, ``versionMatches`` and the same routes):

* ``cases``: an entry's content and the version the server gives it (text with accents and emoji, whole and fractional
  numbers, unknown nutrients, every status and purpose);
* ``match_cases``: an ``If-Match`` header, an entry version and whether the header allows the change;
* ``script``: one list of requests, run in order against a fresh server (here) and a fresh demo (there), with the answers
  the server gave: a version that matches, one that does not (412 with the current entry), no header, ``*``, a list, a
  weak tag, an empty header, a bad body with a stale version (400), a missing entry (404) and a delete with and without a
  match. A ``{{version:N}}`` in a header is the ``version`` of step N's answer (``{{version:N.I}}``: of entry I of
  its ``entries``). Entries are shown without ``food_id`` and the timestamps (they differ between the two sides).

Needs the app's dependencies (it starts the app against a temporary database).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "entry_version_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import log as food_log  # noqa: E402
from app.nutrients import NUTRIENT_KEYS  # noqa: E402

D = "2026-10-05"
PLACEHOLDER = re.compile(r"\{\{version:(\d+)(?:\.(\d+))?\}\}")
SHOWN = ("id", "date", "meal", "food_name", "servings", "grams", "note", "status", "purpose", "kidney_rating", "version", "nutrients")
HEX16 = "0000000000000000"


def nutrients(**given: Any) -> dict[str, Any]:
    return {key: given.get(key) for key in NUTRIENT_KEYS}


def entry(**given: Any) -> dict[str, Any]:
    base = {"date": D, "meal": "lunch", "food_name": "Banana, raw", "servings": 1, "grams": None, "note": None, "status": "eaten",
            "purpose": None, "nutrients": nutrients(calories_kcal=105, potassium_mg=422, carbs_g=27)}
    return {**base, **given}


def cases() -> list[dict[str, Any]]:
    named: list[tuple[str, dict[str, Any]]] = [
        ("a plain entry", entry()),
        ("another day", entry(date="2026-10-06")),
        ("another meal", entry(meal="dinner")),
        ("another name", entry(food_name="Apple, raw, with skin")),
        ("a fractional amount", entry(servings=0.333)),
        ("a whole amount as a float", entry(servings=2.0)),
        ("the same amount as an integer", entry(servings=2)),
        ("by weight", entry(servings=2.542, grams=300.0)),
        ("by weight with a fraction", entry(servings=0.5, grams=42.5)),
        ("a note", entry(note="with breakfast")),
        ("an empty note", entry(note="")),
        ("a note with accents", entry(note="très bon, crème fraîche")),
        ("a note with emoji", entry(note="🍌 for the road 😀")),
        ("a note with a line break and quotes", entry(note='line one\nline "two"\ttabbed')),
        ("planned", entry(status="planned")),
        ("treated a low", entry(purpose="hypo", food_name="Glucose tablets")),
        ("a name with accents", entry(food_name="Crème brûlée 🍮")),
        ("unknown nutrients", entry(nutrients=nutrients())),
        ("a nutrient of zero", entry(nutrients=nutrients(calories_kcal=0, potassium_mg=0, fluid_ml=0))),
        ("fractional nutrients", entry(nutrients=nutrients(protein_g=1.3, fat_g=0.4, carbs_g=26.9, fiber_g=3.1, sugar_g=14.4))),
        ("every nutrient", entry(nutrients={key: 10 * (i + 1) + 0.5 * (i % 2) for i, key in enumerate(NUTRIENT_KEYS)})),
        ("a large amount", entry(servings=1000, grams=100000.0, nutrients=nutrients(calories_kcal=105000, sodium_mg=1000))),
        ("a tiny amount", entry(servings=0.001, grams=0.1)),
    ]
    return [{"name": name, "entry": e, "version": food_log.entry_version(e)} for name, e in named]


def match_cases() -> list[dict[str, Any]]:
    v = food_log.entry_version(entry())
    other = HEX16
    rows: list[tuple[str, str | None]] = [
        ("no header", None),
        ("the version, quoted", f'"{v}"'),
        ("the version, unquoted", v),
        ("another version", f'"{other}"'),
        ("a star", "*"),
        ("a star with spaces", "  *  "),
        ("a weak tag of the version", f'W/"{v}"'),
        ("a weak tag in lower case", f'w/"{v}"'),
        ("a list with the version second", f'"{other}", "{v}"'),
        ("a list with the version first", f'"{v}","{other}"'),
        ("a list without it", f'"{other}", "ffffffffffffffff"'),
        ("a weak tag then the version", f'W/"{v}", "{v}"'),
        ("an empty header", ""),
        ("only spaces", "   "),
        ("a comma", ","),
        ("the version with a trailing quote only", f'{v}"'),
        ("the version in capitals", f'"{v.upper()}"'),
        ("the version with spaces inside the quotes", f'" {v} "'),
        ("text that is not a tag", "garbage"),
    ]
    return [{"name": name, "header": header, "version": v, "expected": food_log.version_matches(header, v)} for name, header in rows]


def shown(value: Any) -> Any:
    """An entry as the vectors keep it: the parts that are the same on the server and in the demo."""
    if isinstance(value, dict) and "version" in value and "nutrients" in value:
        return {k: value[k] for k in SHOWN if k in value}
    return value


def script() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    def add(name: str, method: str, path: str, body: Any = None, if_match: str | None = None, *, has_body: bool = True) -> None:
        step: dict[str, Any] = {"name": name, "method": method, "path": path}
        if has_body and body is not None:
            step["body"] = body
        if if_match is not None:
            step["if_match"] = if_match
        steps.append(step)

    def quick(step_name: str, **extra: Any) -> None:
        add(step_name, "POST", "/api/log/quick", {"date": D, "meal": "lunch", "name": "Oat bar", "serving_desc": "1 bar", "serving_g": 40,
                                             "nutrients": {"calories_kcal": 160, "protein_g": 3, "carbs_g": 24, "potassium_mg": 150,
                                                           "phosphorus_mg": 80, "sodium_mg": 90}, "servings": 1, **extra})

    e = "/api/log"
    quick("log an oat bar")                                                                                                   # 0 -> id 1
    quick("log a planned food with accents", name="Crème fraîche 😀", meal="dinner", status="planned", servings=0.5, note="très bon")  # 1 -> id 2
    add("read the day", "GET", f"{e}?date={D}")                                                                               # 2
    add("PUT with the matching version", "PUT", f"{e}/1", {"servings": 2}, '"{{version:0}}"')                                  # 3
    add("PUT with the version it had before (412)", "PUT", f"{e}/1", {"servings": 9, "meal": "dinner"}, '"{{version:0}}"')     # 4
    add("PUT without the header", "PUT", f"{e}/1", {"note": "late"})                                                          # 5
    add("PUT with a weak tag (412)", "PUT", f"{e}/1", {"note": "weak"}, 'W/"{{version:5}}"')                                   # 6
    add("PUT with a star", "PUT", f"{e}/1", {"note": "star"}, "*")                                                            # 7
    add("PUT with a list", "PUT", f"{e}/1", {"note": "list"}, '"zzzzzzzzzzzzzzzz", "{{version:7}}"')                           # 8
    add("PUT with an unquoted version", "PUT", f"{e}/1", {"note": "bare"}, "{{version:8}}")                                    # 9
    add("PUT with an empty header (412)", "PUT", f"{e}/1", {"note": "empty"}, "")                                              # 10
    add("PUT with a bad body and an old version (400)", "PUT", f"{e}/1", {"servings": -1}, '"{{version:0}}"')                  # 11
    add("PUT of an entry that is not there (404)", "PUT", f"{e}/99", {"servings": 2}, '"{{version:9}}"')                       # 12
    add("PUT that changes the date and the status", "PUT", f"{e}/1", {"date": "2026-10-06", "status": "planned"}, '"{{version:9}}"')  # 13
    add("PUT that puts them back: the first version again", "PUT", f"{e}/1", {"date": D, "status": "eaten", "note": None, "servings": 1},
        '"{{version:13}}"')                                                                                                    # 14
    add("PUT with the grams of a food that has a weight", "PUT", f"{e}/1", {"grams": 80}, '"{{version:14}}"')                  # 15
    add("DELETE with a version that is not the entry's (412)", "DELETE", f"{e}/2", None, f'"{HEX16}"')                           # 16
    add("mark everything planned as eaten", "POST", f"{e}/mark-eaten", {"date": D})                                           # 17
    add("DELETE with the version from before mark-eaten (412)", "DELETE", f"{e}/2", None, '"{{version:2.1}}"')                  # 18
    add("read the day again", "GET", f"{e}?date={D}")                                                                         # 19
    add("PUT back to planned without the header: the same content, the same version", "PUT", f"{e}/2", {"status": "planned"})  # 20
    add("DELETE with the matching version", "DELETE", f"{e}/2", None, '"{{version:20}}"')                                      # 21
    add("DELETE again (404)", "DELETE", f"{e}/2", None, '"{{version:20}}"')                                                    # 22
    add("DELETE with a star", "DELETE", f"{e}/1", None, "*")                                                                  # 23
    quick("a low treatment", name="Glucose tablets", flags=["hypo_treatment"], servings=4, nutrients={"carbs_g": 16, "sugar_g": 16})  # 24 -> id 3
    add("a low treatment is edited like any other", "PUT", f"{e}/3", {"servings": 2, "note": "3.4 mmol/L"}, '"{{version:24}}"')  # 25
    add("a low treatment is deleted like any other", "DELETE", f"{e}/3", None, '"{{version:25}}"')                              # 26
    add("nothing is left", "GET", f"{e}?date={D}")                                                                            # 27
    return steps


def resolve(text: str, answers: list[dict[str, Any]]) -> str:
    def version(match: re.Match[str]) -> str:
        body = answers[int(match.group(1))]["body"]
        return (body["entries"][int(match.group(2))] if match.group(2) is not None else body)["version"]

    return PLACEHOLDER.sub(version, text)


def run_script(client: Any, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    full: list[dict[str, Any]] = []  # the raw bodies, for the placeholders
    for step in steps:
        kwargs: dict[str, Any] = {}
        if "body" in step:
            kwargs["json"] = step["body"]
        if "if_match" in step:
            kwargs["headers"] = {"If-Match": resolve(step["if_match"], full)}
        r = client.request(step["method"], step["path"], **kwargs)
        raw = r.json() if r.content else None
        full.append({"body": raw})
        if r.status_code >= 400:
            answer: dict[str, Any] = {"ok": False, "status": r.status_code, "detail": raw["detail"]}
            if "current" in raw:
                answer["current"] = shown(raw["current"])
        else:
            if isinstance(raw, dict) and "entries" in raw:
                body: Any = {**{k: v for k, v in raw.items() if k != "entries"}, "entries": [shown(x) for x in raw["entries"]]}
                body = {k: v for k, v in body.items() if k in ("date", "entries", "counts")}
            else:
                body = shown(raw)
            answer = {"ok": True, "body": body}
        answers.append(answer)
    return answers


def build() -> dict[str, Any]:
    """The whole document (also what ``tests/test_entry_version_vectors.py`` compares the committed file with)."""
    from starlette.testclient import TestClient as BareClient

    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, FIXTURE_FOODS, make_settings

    steps = script()
    with tempfile.TemporaryDirectory() as tmp:
        foods = Path(tmp) / "foods.json"
        foods.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
        with BareClient(create_app(make_settings(Path(tmp), foods)), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text
            answers = run_script(client, steps)
    doc = {
        "fields": list(food_log.VERSION_FIELDS),
        "cases": cases(),
        "match_cases": match_cases(),
        "script": [{**step, "answer": answer} for step, answer in zip(steps, answers)],
    }
    return json.loads(json.dumps(doc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_entry_version_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
