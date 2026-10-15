#!/usr/bin/env python3
"""Generate tests/data/symptoms_vectors.json: parity vectors for the browser twin of the symptoms log.

    python3 tests/data/gen_symptoms_vectors.py           # rewrite the file
    python3 tests/data/gen_symptoms_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/symptoms.py`` and the ``SymptomCreate`` model of ``app/models.py``, and replayed on
the JavaScript side by ``node tests/js/run_vectors.mjs`` against ``app/static/js/engine/symptoms.js`` (the list, the
severities, the handbook red flags, the API shape) and the demo API ``app/static/js/mock/symptoms.js``:

* ``symptoms``, ``severity_labels``, ``limits``, ``red_flags``: the tables the twin must equal;
* ``row_cases``: a stored row and the API shape the server gives it;
* ``script``: one list of requests, run in order against a fresh server (here) and a fresh demo (there), with the answers
  the server gave: every route, every refusal and its exact text. A ``{{today:N}}`` in a path or a body is the date N days
  from today (negative: earlier), so the "not in the future" rule is checked on both sides at today's date; ``created_at``
  is written as ``<ts>``;
* ``summarise_cases``: the Trends grouping (``KH.symptomRules.summarise``), which has no server twin because only the
  browser draws it; written by hand and checked by ``node tests/js/run_vectors.mjs`` and ``tests/test_symptoms_vectors.py``.

Needs the app's dependencies (it starts the app against a temporary database).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "symptoms_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import symptoms as S  # noqa: E402
from app.models import MAX_SYMPTOM_LABEL, MAX_SYMPTOM_NOTE, MAX_SYMPTOMS_PER_DAY  # noqa: E402

D1, D2, D3, D4, D5 = "2025-03-03", "2025-03-04", "2025-03-05", "2025-03-10", "2025-03-11"
TODAY = re.compile(r"\{\{today:(-?\d+)\}\}")
MARKER_RANGE = range(-45, 6)
POST, PUT, GET, DELETE = "POST", "PUT", "GET", "DELETE"


def sym(when: str, symptom: str = "tiredness", severity: Any = 2, **extra: Any) -> dict[str, Any]:
    return {"date": when, "symptom": symptom, "severity": severity, **extra}


def script() -> list[dict[str, Any]]:
    """The requests, in order: ``{name, method, path, body?}``."""
    steps: list[dict[str, Any]] = []

    def add(name: str, method: str, path: str, *body: Any) -> None:
        step = {"name": name, "method": method, "path": path}
        if body:
            step["body"] = body[0]
        steps.append(step)

    c = "/api/symptoms"
    # --- recording, and what the answer says
    add("a mild tiredness with a note", POST, c, sym(D1, "tiredness", 1, note="after dialysis"))
    add("severe swelling is a red flag and prominent", POST, c, sym(D1, "swelling", 3))
    add("mild swelling is a red flag, not prominent", POST, c, sym(D2, "swelling", 1))
    add("moderate breathlessness is a red flag", POST, c, sym(D2, "breathlessness", 2))
    add("other with a label, stripped", POST, c, sym(D3, "other", 2, label="  Dry mouth ", note=" kept  "))
    add("itching with a null label and note", POST, c, sym(D3, "itching", 1, label=None, note=None))
    add("nausea with a line break in the note", POST, c, sym(D3, "nausea", 3, note="line one\nline two\tand a tab"))
    add("poor appetite", POST, c, sym(D3, "poor_appetite", 2))
    add("cramps", POST, c, sym(D3, "cramps", 1))
    add("severity as text", POST, c, sym(D3, "cramps", "2"))
    add("severity as a whole float", POST, c, sym(D3, "cramps", 3.0))
    add("surrounding spaces in the date", POST, c, sym(" " + D3 + " ", "tiredness", 1))
    add("a label of the longest length", POST, c, sym(D3, "other", 1, label="é" * MAX_SYMPTOM_LABEL))
    add("a note of the longest length (counted in characters)", POST, c, sym(D3, "tiredness", 1, note="😀" * MAX_SYMPTOM_NOTE))
    # --- listing
    add("list the first three days", GET, f"{c}?start={D1}&end={D3}")
    add("list one day", GET, f"{c}?start={D2}&end={D2}")
    add("list a day with one entry", GET, f"{c}?start={D1}&end={D1}")
    add("list days with nothing", GET, f"{c}?start=2024-01-01&end=2024-01-31")
    add("list needs a start", GET, c)
    add("list needs an end", GET, f"{c}?start={D1}")
    add("list: a start that is not a date", GET, f"{c}?start=soon&end={D3}")
    add("list: an end that is not a real date", GET, f"{c}?start={D1}&end=2025-02-30")
    add("list: end before start", GET, f"{c}?start={D3}&end={D1}")
    add("list: more than a year", GET, f"{c}?start=2024-01-01&end=2025-03-05")
    add("list: exactly the longest range", GET, f"{c}?start=2024-03-05&end=2025-03-05")
    add("list: an empty start", GET, f"{c}?start=&end={D3}")
    # --- changing and deleting
    add("update to nausea, severe, another day, empty note", PUT, f"{c}/1", sym(D3, "nausea", 3, note=""))
    add("update to an other with a label", PUT, f"{c}/2", sym(D1, "other", 1, label="Itchy eyes"))
    add("update to breathlessness, severe", PUT, f"{c}/2", sym(D1, "breathlessness", 3))
    add("update of a symptom that is not there", PUT, f"{c}/99", sym(D1))
    add("update of a symptom that is not there, with a bad body", PUT, f"{c}/99", sym(D1, "headache"))
    add("list after the changes", GET, f"{c}?start={D1}&end={D3}")
    add("delete", DELETE, f"{c}/3")
    add("delete again", DELETE, f"{c}/3")
    add("update after the delete", PUT, f"{c}/3", sym(D1))
    add("list after the delete", GET, f"{c}?start={D1}&end={D3}")
    for odd in ("0", "-1", "+99", "9_9", "99.0", "99999999999999999999"):
        add(f"delete with the id {odd}", DELETE, f"{c}/{odd}")
        add(f"update with the id {odd}", PUT, f"{c}/{odd}", sym(D1))
    for odd in ("abc", "1.5"):
        add(f"delete with the id {odd!r}", DELETE, f"{c}/{odd}")
    add("update with an id that is not a number", PUT, f"{c}/abc", sym(D1))
    add("update with an id that is not a number and a bad body", PUT, f"{c}/abc", sym(D1, "headache", 9))
    # --- refusals, with their exact texts
    bad: list[tuple[str, Any]] = [
        ("an unknown symptom", sym(D1, "headache")),
        ("a symptom in capitals", sym(D1, "OTHER", 1, label="x")),
        ("a null symptom", sym(D1, None)),
        ("a symptom that is a number", sym(D1, 7)),
        ("severity 0", sym(D1, "tiredness", 0)),
        ("severity 4", sym(D1, "tiredness", 4)),
        ("severity high", sym(D1, "tiredness", "high")),
        ("severity 2.5", sym(D1, "tiredness", 2.5)),
        ("severity null", sym(D1, "tiredness", None)),
        ("severity true", sym(D1, "tiredness", True)),
        ("severity a list", sym(D1, "tiredness", [2])),
        ("severity as text with spaces", sym(D1, "tiredness", " 2 ")),
        ("severity as 2.0 in text", sym(D1, "tiredness", "2.0")),
        ("severity as 2.5 in text", sym(D1, "tiredness", "2.5")),
        ("severity as 1e0 in text", sym(D1, "tiredness", "1e0")),
        ("a date in the future", sym("2999-01-01")),
        ("a date long ago", sym("1899-12-31")),
        ("a date in the wrong form", sym("10/05/2026")),
        ("a date that is not on the calendar", sym("2026-02-30")),
        ("a date that is a number", sym(20261005)),
        ("a date that is empty", sym("")),
        ("a note that is too long", sym(D1, "tiredness", 1, note="n" * (MAX_SYMPTOM_NOTE + 1))),
        ("a note of too many emoji", sym(D1, "tiredness", 1, note="😀" * (MAX_SYMPTOM_NOTE + 1))),
        ("a note with a control character", sym(D1, "tiredness", 1, note="bad\u0000note")),
        ("a note with a bell", sym(D1, "tiredness", 1, note="bad\u0007note")),
        ("a note that is a number", sym(D1, "tiredness", 1, note=5)),
        ("a label on a symptom that is not other", sym(D1, "tiredness", 1, label="Dry mouth")),
        ("other without a label", sym(D1, "other", 1)),
        ("other with an empty label", sym(D1, "other", 1, label="")),
        ("other with a label of spaces", sym(D1, "other", 1, label="   ")),
        ("a label that is too long", sym(D1, "other", 1, label="l" * (MAX_SYMPTOM_LABEL + 1))),
        ("a label of two lines", sym(D1, "other", 1, label="two\nlines")),
        ("a label with a tab inside", sym(D1, "other", 1, label="a\tb")),
        ("a label that is a list", sym(D1, "other", 1, label=["x"])),
        ("an unknown field", {**sym(D1), "surprise": 1}),
        ("an id in the body", {**sym(D1), "id": 7}),
        ("a user_id in the body", {**sym(D1), "user_id": 2}),
        ("several problems at once, in the model's order", {"symptom": "x", "severity": 9, "date": "bad", "note": 5, "label": 1, "extra": 1, "more": 2}),
        ("nothing", {}),
        ("a list", [sym(D1)]),
        ("a string", "tiredness"),
        ("a number", 7),
    ]
    for name, payload in bad:
        add(f"POST: {name}", POST, c, payload)
    add("POST with no body", POST, c)
    for name, payload in bad[:6] + bad[15:17] + bad[26:28]:
        add(f"PUT: {name}", PUT, f"{c}/4", payload)
    add("PUT with no body", PUT, f"{c}/4")
    add("PUT with a body that is a list", PUT, f"{c}/4", [sym(D1)])
    add("nothing was stored by the refusals", GET, f"{c}?start={D1}&end={D3}")
    # --- a day holds a bounded number
    for n in range(MAX_SYMPTOMS_PER_DAY):
        add(f"fill the day, {n + 1}", POST, c, sym(D4, "tiredness", 1 + n % 3))
    add("the day is full", POST, c, sym(D4, "cramps", 1))
    add("an entry on another day is fine", POST, c, sym(D5, "cramps", 1))
    # ids: the first fill is 18 (17 were made before it), so the day holds 18-47 and the entry on the other day is 48
    add("moving it into the full day is refused", PUT, f"{c}/48", sym(D4, "cramps", 1))
    add("editing inside the full day is fine", PUT, f"{c}/19", sym(D4, "tiredness", 3))
    add("list the full day", GET, f"{c}?start={D4}&end={D4}")
    # --- today's date, which only the clock can say
    add("today", POST, c, sym("{{today:0}}", "swelling", 2))
    add("yesterday", POST, c, sym("{{today:-1}}", "swelling", 3))
    add("tomorrow is allowed (the person's clock may be ahead)", POST, c, sym("{{today:1}}", "tiredness", 1))
    add("the day after tomorrow is not", POST, c, sym("{{today:2}}", "tiredness", 1))
    add("the list ends at today", GET, f"{c}?start={{{{today:-3}}}}&end={{{{today:0}}}}")
    add("the list can end tomorrow", GET, f"{c}?start={{{{today:-1}}}}&end={{{{today:1}}}}")
    return steps


def with_dates(value: Any, today: date) -> Any:
    """Replace ``{{today:N}}`` in strings by the date."""
    if isinstance(value, str):
        return TODAY.sub(lambda m: (today + timedelta(days=int(m.group(1)))).isoformat(), value)
    if isinstance(value, list):
        return [with_dates(v, today) for v in value]
    if isinstance(value, dict):
        return {k: with_dates(v, today) for k, v in value.items()}
    return value


def as_markers(value: Any, today: date) -> Any:
    """The reverse for an answer: a date within the marker range becomes ``{{today:N}}``; ``created_at`` becomes ``<ts>``."""
    by_date = {(today + timedelta(days=n)).isoformat(): f"{{{{today:{n}}}}}" for n in MARKER_RANGE}
    if isinstance(value, str):
        return by_date.get(value, value)
    if isinstance(value, list):
        return [as_markers(v, today) for v in value]
    if isinstance(value, dict):
        return {k: ("<ts>" if k == "created_at" and isinstance(v, str) else as_markers(v, today)) for k, v in value.items()}
    return value


def run_script(client: Any, steps: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for step in steps:
        kwargs: dict[str, Any] = {}
        if "body" in step:
            kwargs["json"] = with_dates(step["body"], today)
        r = client.request(step["method"], with_dates(step["path"], today), **kwargs)
        if r.status_code >= 400:
            answers.append({"ok": False, "status": r.status_code, "detail": r.json()["detail"]})
        else:
            answers.append({"ok": True, "body": r.json() if r.content else None})
    return [as_markers(a, today) for a in answers]


def row_cases() -> list[dict[str, Any]]:
    cases = []
    stamp = "2026-10-05T12:30:00.000000Z"
    for key, _ in S.SYMPTOMS:
        for severity in (1, 2, 3):
            row = {"id": len(cases) + 1, "date": D1, "symptom": key, "label": "Dry mouth" if key == "other" else "", "severity": severity,
                   "note": "", "created_at": stamp}
            cases.append({"row": row, "symptom": S.row_to_symptom(row)})
    cases.append({"row": {"id": 99, "date": D2, "symptom": "tiredness", "label": "", "severity": 2, "note": "a note", "created_at": stamp},
                  "symptom": S.row_to_symptom({"id": 99, "date": D2, "symptom": "tiredness", "label": "", "severity": 2,
                                               "note": "a note", "created_at": stamp})})
    return cases


def summarise_cases() -> list[dict[str, Any]]:
    """Written by hand: the Trends grouping has no server twin."""

    def s(when: str, key: str, severity: int, label: str = "") -> dict[str, Any]:
        row = {"id": 1, "date": when, "symptom": key, "label": label, "severity": severity, "note": "", "created_at": "2026-10-05T12:30:00.000000Z"}
        return S.row_to_symptom(row)

    swelling_flag = S.red_flag("swelling", 1)
    breath_flag = S.red_flag("breathlessness", 3)
    return [
        {"name": "nothing recorded", "symptoms": [], "groups": []},
        {
            "name": "groups, highest severity per day, most days first, then by name",
            "symptoms": [
                s(D1, "tiredness", 1), s(D1, "tiredness", 3), s(D2, "tiredness", 2), s(D2, "swelling", 1),
                s(D1, "other", 2, "Dry mouth"), s(D3, "other", 1, "dry MOUTH"), s(D2, "other", 3, "Itchy eyes"),
            ],
            "groups": [
                {"key": "other:dry mouth", "symptom": "other", "name": "Dry mouth", "days": [{"date": D1, "severity": 2}, {"date": D3, "severity": 1}],
                 "dayCount": 2, "worst": 2, "worst_label": "Moderate", "red_flag": None},
                {"key": "tiredness", "symptom": "tiredness", "name": "Tiredness", "days": [{"date": D1, "severity": 3}, {"date": D2, "severity": 2}],
                 "dayCount": 2, "worst": 3, "worst_label": "Severe", "red_flag": None},
                {"key": "other:itchy eyes", "symptom": "other", "name": "Itchy eyes", "days": [{"date": D2, "severity": 3}],
                 "dayCount": 1, "worst": 3, "worst_label": "Severe", "red_flag": None},
                {"key": "swelling", "symptom": "swelling", "name": "Swelling", "days": [{"date": D2, "severity": 1}],
                 "dayCount": 1, "worst": 1, "worst_label": "Mild", "red_flag": swelling_flag},
            ],
        },
        {
            "name": "the red flag follows the worst day; days come out oldest first whatever the order given",
            "symptoms": [s(D3, "breathlessness", 1), s(D1, "breathlessness", 3), s(D2, "breathlessness", 2)],
            "groups": [
                {"key": "breathlessness", "symptom": "breathlessness", "name": "Breathlessness",
                 "days": [{"date": D1, "severity": 3}, {"date": D2, "severity": 2}, {"date": D3, "severity": 1}],
                 "dayCount": 3, "worst": 3, "worst_label": "Severe", "red_flag": breath_flag},
            ],
        },
    ]


def build() -> dict[str, Any]:
    """The whole document (also what ``tests/test_symptoms_vectors.py`` compares the committed file with)."""
    from starlette.testclient import TestClient as BareClient

    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, FIXTURE_FOODS, make_settings

    today = date.today()
    steps = script()
    with tempfile.TemporaryDirectory() as tmp:
        foods = Path(tmp) / "foods.json"
        foods.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
        with BareClient(create_app(make_settings(Path(tmp), foods)), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text
            answers = run_script(client, steps, today)
    doc = {
        "symptoms": [list(item) for item in S.SYMPTOMS],
        "severity_labels": {str(k): v for k, v in S.SEVERITY_LABELS.items()},
        "limits": {"max_label": MAX_SYMPTOM_LABEL, "max_note": MAX_SYMPTOM_NOTE, "max_per_day": MAX_SYMPTOMS_PER_DAY},
        "href": S.GET_HELP_NOW_HREF,
        "link_text": S.GET_HELP_NOW_LINK_TEXT,
        "red_flags": {key: {"level": e["level"], "text": e["text"]} for key, e in S.RED_FLAGS.items()},
        "row_cases": row_cases(),
        "script": [{**step, "answer": answer} for step, answer in zip(steps, answers)],
        "summarise_cases": summarise_cases(),
    }
    return json.loads(json.dumps(doc))  # the same JSON round trip as the file (3.0 becomes 3.0, tuples become lists)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_symptoms_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
