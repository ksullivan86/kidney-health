#!/usr/bin/env python3
"""Generate tests/data/ai_device_vectors.json: parity vectors for the browser twins of the AI checks (design note 38 §5.6).

    python3 tests/data/gen_ai_device_vectors.py           # rewrite the file
    python3 tests/data/gen_ai_device_vectors.py --check   # exit 1 when the committed file is stale

In device mode the iPhone app's own model answers "Describe a meal" and "Read a lab report's text", and the page runs the
server's checks on the answer itself: ``js/engine/aijudge.js`` and ``js/engine/lab_report.js``. This file is made by the
server's own code and replayed by ``node tests/js/run_vectors.mjs``:

* ``prefilter_cases``: ``features.prefilter`` (with ``red_flag``, ``medicine_question``, ``chat.dose_reason`` and ``chat.lab_words``);
* ``name_policy_cases``: ``guard.name_policy``;
* ``serving_quantity_cases`` and ``servings_for_cases``: ``features.serving_quantity`` and ``servings_for``;
* ``payload_cases``: the escaped JSON of the data block ``prompts.user_message`` builds for ``parse_meal`` (``prompts.clean``)
  and ``lab_report_text`` (``features.lab_text_lines``), and the whole message;
* ``parse_meal_cases``: the describe-a-meal judge of ``features.prepare_parse_meal``, with a fixed food search;
* ``printed_date_cases``, ``numbers_in_cases``, ``lab_judge_cases`` and ``lab_text_cases``: ``app/ai/lab_report.py``;
* ``extract_json_cases``, ``label_cases`` and ``plate_cases`` (the person's own AI key, design note 39 §6.5): ``client.extract_json``,
  ``features.label_draft`` and the plate judge of ``features.prepare_plate``.

No date in a case is near today, so the cases do not depend on the day they are replayed. Deterministic (seeded); no network.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "ai_device_vectors.json"
sys.path.insert(0, str(ROOT))

from app.ai import chat, features, guard, lab_report, prompts, schemas  # noqa: E402

SEED = 20261121
ZW = "​"
SHY = "­"

PREFILTER_TEXTS = [
    "2 eggs and toast with butter", "chicken and rice, half a cup of each", "my sugar is 55, need juice", "I'm low, 3.2",
    "glucose 61 mg/dL and a banana", "how much insulin for this pasta", "should I skip my binder with dinner",
    "how many vitamin D capsules with breakfast", "is my creatinine ok after steak", "can you diagnose this rash",
    "chest pain after lunch", "felt faint, had crackers", "sevelamer with my lunch", "6 units with rice",
    "if I'm low should I avoid orange juice", "low-fat yogurt and berries", "60 mg sodium crackers", "pumpkin soup",
    "I take my insulin dose", "ins​ulin with oats", "іnsulin and toast", "Ｃｈｅｓｔ ｐａｉｎ", "ACR results and eggs",
    "increase your insulin", "forget to take my pills at lunch", "blood sugar is too low, don't eat yet", "",
    "Extra virgin olive oil on salad", "half a sandwich and tea", "basal rice", "eGFR", "I am at 58 now",
]
NAME_TEXTS = [
    "Pumpkin soup", "Masala dosa", "Basil chicken", "take 2 extra pills", "www.example.com", "visit food.com now",
    "mail me at a@b.co", "<b>rice</b>", "rice {x}", "  Chicken   breast  ", "", "   ", "ins​ulin", "іnsulin", "bοlus rice",
    "Extra virgin olive oil", "it's fine to eat", "Skippy peanut butter", "Glucose tablets", "Ｒｉｃｅ", "a" * 100,
    "Café au lait", "Penne arrabbiata", "double your rice", "unit of rice", "rice|beans", "pasta`s", "naïve salad‮",
    "fish \\ chips", "eggs [2]",
]
SERVING_DESCS = [
    "1 cup (240 ml)", "1/2 cup (79 g)", "½ cup (79 g)", "2 slices", "1 medium (118 g)", "1.5 oz", "100 g", "1 tbsp (15 ml)",
    "3 tsp", "1 piece", "1 fl oz", "250 ml", "one cup", "0 cup", "0/2 cup", "1 / 2 cup", "  2 large eggs", "¼ tsp", "⅓ cup",
    "⅔ cup", "¾ cup", "2/0 cup", "12 fl. oz", "1 each", "1 whole", "", "1\tcup",
]
UNITS = list(schemas.UNITS)


def _texts_with_noise(rng: random.Random, base: list[str], n: int) -> list[str]:
    noise = [ZW, SHY, "‮", "  ", "\t", " ", "ı", "Ｏ", "́"]
    out = []
    for _ in range(n):
        text = rng.choice([t for t in base if t])
        pos = rng.randrange(len(text) + 1)
        out.append(text[:pos] + rng.choice(noise) + text[pos:])
    return out


def prefilter_cases(rng: random.Random) -> list[dict[str, Any]]:
    cases = []
    for text in PREFILTER_TEXTS + _texts_with_noise(rng, PREFILTER_TEXTS, 30):
        cases.append({
            "text": text, "dose_g": 15,
            "red_flag": features.red_flag(text), "dose_reason": chat.dose_reason(text) if text else None,
            "lab_words": chat.lab_words(text), "medicine_question": features.medicine_question(text),
            "output": features.prefilter(text, 15),
        })
    return cases


def name_policy_cases(rng: random.Random) -> list[dict[str, Any]]:
    cases = [{"text": t, "limit": 80, "output": list(guard.name_policy(t, 80))} for t in NAME_TEXTS + _texts_with_noise(rng, NAME_TEXTS, 30)]
    cases.append({"text": None, "limit": 80, "output": list(guard.name_policy(None, 80))})
    cases.append({"text": "Rice with beans and peas", "limit": 9, "output": list(guard.name_policy("Rice with beans and peas", 9))})
    return cases


def serving_cases(rng: random.Random) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sq = []
    for desc in SERVING_DESCS:
        got = features.serving_quantity(desc)
        sq.append({"desc": desc, "output": None if got is None else list(got)})
    sf = []
    foods = [{"serving_desc": d, "serving_g": g} for d in SERVING_DESCS for g in (0, 15.0, 79.0, 240.0)]
    foods.append({"serving_desc": None, "serving_g": None})
    for _ in range(300):
        food = rng.choice(foods)
        amount = rng.choice([None, 0, -1, 0.25, 0.5, 1, 1.5, 2, 3, 10, 50, 100, 250, 1000, 0.01, 2.5, 0.375])
        unit = rng.choice(UNITS)
        sf.append({"amount": amount, "unit": unit, "food": food, "output": features.servings_for(amount, unit, food)})
    for unit, amount, food in [("serving", 2.5, foods[0]), ("serving", 0.625, foods[0]), ("serving", 0.125, foods[0]),
                               ("g", 1.0, {"serving_desc": "x", "serving_g": 8}), ("serving", 20, foods[0]), ("serving", 21, foods[0])]:
        sf.append({"amount": amount, "unit": unit, "food": food, "output": features.servings_for(amount, unit, food)})
    return sq, sf


def payload_cases() -> list[dict[str, Any]]:
    out = []
    schema = schemas.parse_meal_schema()
    for text in ["2 eggs, toast with butter", "chicken & rice <b>", 'a "quote" and \\ back', "  spaced   out\ttext ", "x" * 400,
                 "Café ｆｏｏ​", "line\nbreak"]:
        data = prompts.parse_meal_data(text)
        block = prompts.data_block(data)
        out.append({"task": "parse_meal", "text": text, "payload": block[len("<data>\n"):-len("\n</data>")],
                    "message": prompts.user_message("parse_meal", data, mode="json_schema", schema=schema)})
    schema = schemas.lab_report_schema()
    for text in ["Potassium 4.6 mmol/L\nCreatinine 1.2 mg/dL\n\nCollected 2025-10-07", "a\r\nb\rc d\x0be\x1cf\n",
                 "  Name: <x> & y  \n\t\n", "K​ 4.6"]:
        lines = features.lab_text_lines(text)
        data = {"lines": lines}
        block = prompts.data_block(data)
        out.append({"task": "lab_report_text", "text": text, "lines": lines, "payload": block[len("<data>\n"):-len("\n</data>")],
                    "message": prompts.user_message("lab_report_text", data, mode="json_schema", schema=schema)})
    return out


FOODS = [
    {"id": 1, "name": "Egg, whole, boiled", "serving_desc": "1 large (50 g)", "serving_g": 50.0},
    {"id": 2, "name": "Rice, white, cooked", "serving_desc": "1 cup (158 g)", "serving_g": 158.0},
    {"id": 3, "name": "Toast, white bread", "serving_desc": "1 slice (25 g)", "serving_g": 25.0},
    {"id": 4, "name": "Butter", "serving_desc": "1 tbsp (14 g)", "serving_g": 14.0},
    {"id": 5, "name": "Milk, 2%", "serving_desc": "1 cup (244 g)", "serving_g": 244.0},
    {"id": 6, "name": "Chicken breast, roasted", "serving_desc": "3 oz (85 g)", "serving_g": 85.0},
]


def search(query: str) -> list[dict[str, Any]]:
    """The fixed food search of the parse-meal cases: foods whose name holds every word of the query (run_vectors.mjs has the same)."""
    words = query.lower().split()
    return [f for f in FOODS if all(w in f["name"].lower() for w in words)]


def parse_meal_cases() -> list[dict[str, Any]]:
    def item(text: str, search_term: str, amount: Any, unit: str) -> dict[str, Any]:
        return {"text": text, "search": search_term, "amount": amount, "unit": unit}

    answers = [
        {"status": "ok", "items": [item("2 eggs", "egg", 2, "piece"), item("toast with butter", "toast", 1, "slice"),
                                   item("butter", "butter", 1, "tbsp")]},
        {"status": "ok", "items": [item("half a cup of rice", "rice", 0.5, "cup"), item("chicken", "chicken", 100, "g"),
                                   item("milk", "milk", 8, "fl_oz"), item("milk", "milk", None, "none")]},
        {"status": "ok", "items": [item("6 units of insulin", "insulin", 6, "none"), item("www.x.com", "rice", 1, "cup"),
                                   item("rice", "<script>", 1, "cup"), item("  ", "rice", 1, "cup"), item("Ｒｉｃｅ", "ｒｉｃｅ", 1, "cup")]},
        {"status": "refused", "items": []},
        {"status": "refused", "items": [item("eggs", "egg", 2, "piece")]},
        {"status": "ok", "items": []},
        {"status": "ok", "items": [item("rice", "rice", 400, "g"), item("rice", "rice", 1, "serving"), item("pizza", "pizza", 1, "slice"),
                                   item("egg", "egg", 3, "serving"), item("ins​ulin pen", "pen", 1, "piece")]},
    ]
    out = []
    real = features.build_body
    features.build_body = lambda *args, **kwargs: {}  # the request body is not what these cases check
    try:
        cfg = SimpleNamespace(structured="json_schema")
        prep = features.prepare_parse_meal(cfg, "x", search=search)  # type: ignore[arg-type]
    finally:
        features.build_body = real
    for answer in answers:
        parsed = schemas.ParseMealAnswer.model_validate(answer)
        out.append({"answer": answer, "output": prep.judge(parsed)})
    return out


PRINTED_DATES = [
    "2025-10-07", "2025/10/07", "2025.10.07", "7 Oct 2025", "Oct 7, 2025", "October 7th, 2025", "7th October 2025", "07/10/2025",
    "13/10/2025", "10/13/2025", "05/05/2025", "13/13/2025", "2025-02-30", "2024-02-29", "2023-02-29", "1899-12-31", "1900-01-01",
    "2999-01-01", "25/10/07", "Collected: 2025-10-07 08:30", "2025-10-07T08:30", "07-Oct-2025", "Sept 3, 2025", "Smarch 3, 2025",
    "", "  ", None, "see report", "http://x.com/2025", "1 2 3 4 5 6 7 8 9", "Oct. 7, 2025", "3 May 2025", "May 3 2025",
    "٢٠٢٥-١٠-٠٧", "２０２５-１０-０７", "0000-01-01", "2025-1-7", "1/2/2025", "31/12/2024 am", "x" * 60,
]


def printed_date_cases() -> list[dict[str, Any]]:
    return [{"text": t, "clean": lab_report.clean_printed_date(t), "parse": list(lab_report.parse_printed_date(t))} for t in PRINTED_DATES]


def numbers_in_cases(rng: random.Random) -> list[dict[str, Any]]:
    texts = ["Potassium 4.6 mmol/L (3.5-5.1)", "eGFR 1,250 and 1,2 and 1.2.3 and 12,345.6", "a1c 7.1% 2025-10-07", "no numbers",
             "x5.4y 0.9 88 .5 5.", "١٢٫٣ and ٤,٥", "1,2,3"]
    for _ in range(20):
        parts = [rng.choice(["K", "Cr", " ", ",", ".", "-", "/"]) + str(rng.choice([0, 1, 12, 4.6, 1250, 0.05, 1000000]))
                 + rng.choice(["", ",5", ".25", ",000", " mg"]) for _ in range(rng.randint(1, 5))]
        texts.append(" ".join(parts))
    return [{"text": t, "numbers": sorted(lab_report.numbers_in(t))} for t in texts]


def _row(analyte: str, value: float, unit: str, taken_on: str | None) -> dict[str, Any]:
    return {"analyte": analyte, "value": value, "unit": unit, "taken_on": taken_on}


LAB_ANSWERS = [
    {"status": "ok", "rows": [_row("potassium", 4.6, "mmol/L", "2025-10-07"), _row("phosphate", 3.4, "mg/dL", "07 Oct 2025"),
                              _row("egfr", 61, "mL/min/1.73 m²", "Oct 7, 2025")]},
    {"status": "ok", "rows": [_row("sodium", 140, "mmol/L", None), _row("other", 1, "x", None), _row(" Potassium ", 4.1, "meq/l", None),
                              _row("potassium", 4.1, "mg", None), _row("potassium", 40, "mmol/L", None), _row("potassium", -1, "mmol/L", None),
                              _row("creatinine", 106, "umol/L", "03/04/2025"), _row("creatinine", 106, "µmol/L", "03/04/2025")]},
    {"status": "ok", "rows": [_row("a1c", 7.1, "%", "2999-01-01"), _row("a1c", 7.1, "%", "1899-01-01"), _row("uacr", 30, "mg/g", "see report"),
                              _row("albumin", 40, "g/L", "13/10/2025"), _row("bicarbonate", 24, "mEq/L", None), _row("cystatin_c", 1.1, "mg/L", None)]},
    {"status": "not_a_lab_report", "rows": []},
    {"status": "unreadable", "rows": [_row("potassium", 4.6, "mmol/L", None)]},
    {"status": "ok", "rows": []},
    {"status": "ok", "rows": [_row("potassium", 2000000, "mmol/L", None), _row("uacr", 3, "mg/mmol", "2025-10-07")]},
]
LAB_TEXTS = [
    "Potassium 4.6 mmol/L 2025-10-07\nPhosphate 3.4 mg/dL 07   oct 2025\neGFR 61 mL/min/1.73 m² Oct 7, 2025",
    "Na 140 K 4,1 Creatinine 106 umol/L 03/04/2025",
    "HbA1c 7.1 % ACR 30 Albumin 40 g/L Bicarb 24 Cystatin C 1.1",
    "nothing here",
    "Potassium 4.6",
    "",
    "K 2,000,000 uACR 3 mg/mmol",
]


def lab_cases() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    judged = []
    texted = []
    for answer, text in zip(LAB_ANSWERS, LAB_TEXTS):
        parsed = schemas.LabReportAnswer.model_validate(answer)
        judged.append({"answer": answer, "output": lab_report.judge(parsed)})
        texted.append({"answer": answer, "text": text, "output": lab_report.judge_text(parsed, text)})
    # Every answer against a text that holds none of its numbers, and one with every number but no dates.
    for answer in LAB_ANSWERS[:3]:
        parsed = schemas.LabReportAnswer.model_validate(answer)
        texted.append({"answer": answer, "text": "Results: see attached", "output": lab_report.judge_text(parsed, "Results: see attached")})
        numbers = " ".join(str(r["value"]) for r in answer["rows"])
        texted.append({"answer": answer, "text": numbers, "output": lab_report.judge_text(parsed, numbers)})
    return judged, texted


# The person's own AI key (design note 39 §6.5): a company's model answers as text, so the page reads the JSON out of it
# (client.extract_json) and checks label and plate photos (features.label_draft, prepare_plate's judge).
EXTRACT_TEXTS = [
    '{"status":"ok","items":[]}', '  {"a": 1}  ', "﻿{\"a\": 1}", '```json\n{"a": {"b": "}"}}\n```', '```\n{"a": 2}```',
    'Here you go: {"a": "x\\"}"} and more {"b": 1}', '{"a": 1', '{bad} {"ok": true}', "", "   ", "no json here", "```", "[1, 2]",
    '{"a": "\\u00e9"}', 'text {"nested": {"deep": [1, {"x": 2}]}} tail', '{"a": 1}}', '}{"a": 3}',
]


def extract_json_cases() -> list[dict[str, Any]]:
    from app.ai import client

    out = []
    for text in EXTRACT_TEXTS:
        try:
            value = client.extract_json(text)
        except client.JsonNotFound:
            value = None
        out.append({"text": text, "output": value})
    return out


def _label(**over: Any) -> dict[str, Any]:
    base = {"status": "ok", "product_name": "Crackers", "serving_text": "5 crackers (30 g)", "serving_g": 30.0, "basis": "per_serving",
            "per_serving": {k: None for k in schemas.LABEL_NUTRIENTS}, "salt_g": None,
            "percent_dv": {k: None for k in schemas.PERCENT_DV_KEYS}, "ingredients_text": None, "label_style": "us_nutrition_facts"}
    for key, value in over.items():
        if key in ("per_serving", "percent_dv"):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def label_cases() -> list[dict[str, Any]]:
    answers = [
        _label(per_serving={"calories_kcal": 130, "fat_g": 4.5, "carbs_g": 21, "protein_g": 2, "sodium_mg": 210, "potassium_mg": 35}),
        _label(per_serving={"calories_kcal": 500, "fat_g": 4.5, "carbs_g": 21, "protein_g": 2, "fiber_g": 1}),
        _label(basis="per_100g", serving_g=45.0, per_serving={"calories_kcal": 450, "sodium_mg": None, "phosphorus_mg": 120.05},
               salt_g=1.25),
        _label(basis="per_100ml", serving_g=None, serving_text=None, per_serving={"calories_kcal": 42, "carbs_g": 10.6}, salt_g=0.1),
        _label(percent_dv={"sodium": 10, "potassium": 4, "phosphorus": 8, "calcium": 2.5}),
        _label(per_serving={"sodium_mg": 12000, "potassium_mg": 7000, "fat_g": 20, "carbs_g": 20, "protein_g": 1}),
        _label(product_name="  Cola​  ", ingredients_text="Carbonated water, sugar, phosphoric acid, caramel color,\n\n"
               "natural flavors, potassium benzoate", per_serving={"calories_kcal": 140, "carbs_g": 39, "sodium_mg": 45}),
        _label(product_name=None, serving_g=None, serving_text=None, per_serving={"calories_kcal": 90}),
        _label(product_name="Lo Salt", ingredients_text="Potassium chloride, sodium chloride"),
        {**_label(), "status": "not_a_label"},
        {**_label(), "status": "unreadable"},
        _label(serving_g=28.35, serving_text=None, per_serving={"calories_kcal": 160, "fat_g": 10, "carbs_g": 15, "protein_g": 2}),
    ]
    return [{"answer": a, "output": features.label_draft(schemas.LabelAnswer.model_validate(a))} for a in answers]


def plate_cases() -> list[dict[str, Any]]:
    def item(name: str, term: str, grams: Any, confidence: str) -> dict[str, Any]:
        return {"name": name, "search": term, "grams_estimate": grams, "confidence": confidence}

    answers = [
        {"status": "ok", "items": [item("Boiled eggs", "egg", 100, "high"), item("White rice", "rice", 150.5, "medium"),
                                   item("Butter", "butter", None, "low"), item("Toast", "toast", 0, "medium")]},
        {"status": "ok", "items": [item("insulin pen", "pen", 10, "high"), item("rice", "www.rice.com", 50, "high"),
                                   item("Chicken", "chicken", 2.5, "high"), item("Milk", "milk", 3.5, "low")]},
        {"status": "no_food", "items": []},
        {"status": "unsure", "items": [item("rice", "rice", 100, "low")]},
        {"status": "ok", "items": []},
    ]
    real = features.build_body
    features.build_body = lambda *args, **kwargs: {}  # the request body is not what these cases check
    try:
        prep = features.prepare_plate(SimpleNamespace(structured="json_schema"), SimpleNamespace(data=b""), search=search)  # type: ignore[arg-type]
    finally:
        features.build_body = real
    return [{"answer": a, "output": prep.judge(schemas.PlateAnswer.model_validate(a))} for a in answers]


def build() -> dict[str, Any]:
    rng = random.Random(SEED)
    sq, sf = serving_cases(rng)
    judged, texted = lab_cases()
    return {
        "about": "Made by tests/data/gen_ai_device_vectors.py from app/ai (features, guard, chat, prompts, lab_report); "
                 "replayed against js/engine/aijudge.js and js/engine/lab_report.js by tests/js/run_vectors.mjs.",
        "constants": {"refused_text": guard.REFUSED_TEXT, "prompt_version": prompts.PROMPT_VERSION,
                      "parse_text_chars": prompts.PARSE_TEXT_CHARS, "units": list(schemas.UNITS),
                      "max_parse_items": schemas.MAX_PARSE_ITEMS, "max_lab_rows": schemas.MAX_LAB_ROWS},
        "foods": FOODS,
        "prefilter_cases": prefilter_cases(rng),
        "name_policy_cases": name_policy_cases(rng),
        "serving_quantity_cases": sq,
        "servings_for_cases": sf,
        "payload_cases": payload_cases(),
        "parse_meal_cases": parse_meal_cases(),
        "printed_date_cases": printed_date_cases(),
        "numbers_in_cases": numbers_in_cases(rng),
        "lab_judge_cases": judged,
        "lab_text_cases": texted,
        "extract_json_cases": extract_json_cases(),
        "label_cases": label_cases(),
        "plate_cases": plate_cases(),
    }


def dump(doc: dict[str, Any]) -> str:
    # One case per line; ASCII escapes keep invisible characters visible in diffs.
    lines = ["{"]
    keys = list(doc)
    for n, key in enumerate(keys):
        value = doc[key]
        comma = "," if n < len(keys) - 1 else ""
        if isinstance(value, list):
            lines.append(f"  {json.dumps(key)}: [")
            for m, item in enumerate(value):
                lines.append("    " + json.dumps(item, separators=(",", ":"), allow_nan=False) + ("," if m < len(value) - 1 else ""))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = dump(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_ai_device_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
