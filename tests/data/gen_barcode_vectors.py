#!/usr/bin/env python3
"""Generate tests/data/barcode_vectors.json: parity vectors for the browser barcode twins.

    python3 tests/data/gen_barcode_vectors.py           # rewrite the file
    python3 tests/data/gen_barcode_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code and replayed on the JavaScript side by ``node tests/js/run_vectors.mjs``:

* ``gtin_cases`` / ``check_digit_cases``: ``app.gtin`` normalize (GTIN-14 or the error reason and
  message), classify, off_code and usda_candidates, against ``js/engine/gtin.js``;
* ``textclean_cases``: ``app.textclean.clean_text`` against ``js/engine/textclean.js``;
* ``additive_cases``: ``app.additives.scan`` (flags, findings, notes, additives, kidney notes) against
  ``js/engine/additives.js``: the inputs of tests/test_additives.py, every recorded Open Food Facts and USDA
  fixture's tags and ingredient list, and a seeded set of generated ingredient lists (multilingual names,
  E-number spellings, invisible characters, case and width variants);
* ``quality_cases``: ``app.off.quality_items`` against ``js/engine/off.js``;
* ``demo_products``: the three recorded Open Food Facts products the demo answers ``POST /api/foods/barcode``
  with (``js/mock/barcode.js``). Each has the stored row (``row``, what the demo embeds between its
  ``DEMO_PRODUCTS`` markers; tests/test_barcode_vectors.py keeps the two equal) and the server's answer
  (``result``, food id removed), produced by the real route over the recorded fixtures with Open Food Facts
  on and agreed to; the JS runner rebuilds the answer from the row with the browser rules and compares;
* ``off_map_cases``: ``app.off.trim_product`` and ``map_product`` (and the row ``barcode.assemble`` builds from it)
  over every recorded product, hand-made edge cases and seeded variants, against ``KH.off.trimProduct``,
  ``mapProduct`` and ``row`` (device mode, design note 38 §5.3). Each product is kept as JSON text, as the
  iPhone app hands it to the page.

Deterministic (seeded; no clock in the output). Needs the app's requirements (it runs the app in-process
with the fixtures; no network).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import random
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "barcode_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import additives, gtin, off, textclean  # noqa: E402
from app.nutrients import NUTRIENT_KEYS  # noqa: E402

SEED = 20261006
DEMO_FIXTURES = (  # (fixture, code as a phone's decoder reports it, format)
    ("diet_coke_v3.4", "049000028911", "upc_a"),
    ("kraft_mac_cheese_v3.4", "021000658831", "upc_a"),
    ("nutella_v3.4", "3017624010701", "ean_13"),
)
ROW_FIELDS = ("name", "brand", "category", "source", "serving_desc", "serving_g", "kidney_notes", "gtin", "source_url",
              "source_license", "ingredients_text")

# --------------------------------------------------------------------------- #
# GTINs
# --------------------------------------------------------------------------- #

GTIN_HAND = [
    "049000028911", "0049000028911", "00049000028911", "49000028911", "0 49000 02891 1", "0-49000-02891-1",
    " 0490 0002 8911 ", "+049000028911", "0490000.28911", "04900002891a", "0490000289１1", "٠٤٩٠٠٠٠٢٨٩١١",
    "049000028912", "0049000028910", "00049000028919", "3017624010701", "3017624010702", "96385074", "96385075",
    "01234565", "01234531", "01234543", "11234562", "012345000065", "012300000451", "012340000053", "112345000062",
    "04252614", "042100005264", "9780306406157", "", "   ", "abc", "1234", "1234567", "123456789", "1234567890",
    "12345678901", "123456789012345", "021000658831", "0021000658831", "2012345678906", "4012345678901",
    "0412345678903", "0512345678900", "9771234567003", "9791234567896", "9812345678902", "9912345678900",
    "00000000000000", "﻿049000028911", "049000028911\n", " 049000028911", "049\u0085000028911",
    "049\u001c000028911", "0490000 28911", "049000028911​",
]
FORMATS = list(gtin.FORMATS)


def gtin_case(code: str, fmt: str) -> dict:
    case: dict = {"code": code, "format": fmt}
    try:
        g14 = gtin.normalize(code, fmt)
    except gtin.GtinError as exc:
        case["error"] = {"reason": exc.reason, "message": str(exc)}
        return case
    case.update(normalize=g14, classify=gtin.classify(g14), off_code=gtin.off_code(g14), usda_candidates=gtin.usda_candidates(g14))
    return case


def with_check(body: str) -> str:
    return body + str(gtin.check_digit(body))


def gtin_vectors(rng: random.Random) -> list[dict]:
    cases = [gtin_case(c, f) for c in GTIN_HAND for f in ("unknown", "upc_e")]
    cases += [gtin_case(c, f) for c in ("01234565", "11234562", "01234531", "01234543", "21234562") for f in FORMATS]
    for _ in range(240):
        length = rng.choice([7, 8, 8, 11, 12, 12, 13, 13, 13, 14, 15])
        body = "".join(rng.choice("0123456789") for _ in range(length - 1))
        prefix = rng.choice(["", "0", "02", "04", "05", "2", "97", "978", "98", "99", "9", "00000", "000000", "300"])
        body = (prefix + body)[: length - 1] if length > 1 else body
        code = with_check(body) if rng.random() < 0.8 else body + rng.choice("0123456789")
        if rng.random() < 0.25:
            pos = rng.randrange(1, len(code))
            code = code[:pos] + rng.choice([" ", "-", "  ", " - ", "\t"]) + code[pos:]
        cases.append(gtin_case(code, rng.choice(FORMATS)))
    # every GS1-8 and GTIN-13 prefix boundary the classifier knows
    for prefix in range(0, 1000, 1):
        if prefix % 10 in (0, 9) or prefix in (20, 29, 40, 49, 50, 59, 200, 299, 977, 978, 979, 980):
            cases.append(gtin_case(with_check(f"{prefix:03d}123456789"), "ean_13"))
            cases.append(gtin_case(with_check(f"{prefix:03d}1234"), "ean_8"))
    cases.append(gtin_case(with_check("9" + "0012345678901"[:12]), "unknown"))
    return cases


# --------------------------------------------------------------------------- #
# Text cleaning
# --------------------------------------------------------------------------- #

CHAR_POOL = (
    list("abcdefghij XYZ,.-()0123456789") + ["é", "ü", "ß", "ẞ", "İ", "ς", "ﬁ", "½", "²", "Ｐ", "ｈ", "™", "℃", "Å", "é", "ﾊﾟ"]
    + ["​", "­", "‍", "⁠", "﻿", "‮", "⁦", "⁩", "؜"]  # Cf
    + ["\x00", "\x07", "\x1b", "\x7f", "\x9b", "\x1c", "\x1f"]  # Cc
    + ["\n", "\r", "\r\n", " ", " ", "\x0b", "\x0c", "\x85", "\t"]  # line breaks and tab
    + [" ", " ", " ", "　", " ", "  "]  # spaces
    + ["\ud800", "\udfff"]  # lone surrogates
    + ["😀", "𝐀", "𝟙", "🇫🇷", "\U0002070e"]  # astral
)
TEXT_HAND = [
    "sodium phos​phate", "‮ananab‬", "Diet\x00 Coke", "Cola\ud800 Zero", "ＰＨＯＳＰＨＡＴＥ",
    "line one\r\n\r\n  line two  \n\n\nthree", "  ", "", "​​​", "\x00\x01", "ﬁsh ½ cup",
    "a b c", "x" * 50, "😀" * 30, "é​e", "Kalium­chlorid",
]


def textclean_vectors(rng: random.Random) -> list[dict]:
    cases = []
    for value in TEXT_HAND:
        for keep in (False, True):
            for max_len in (1, 5, 20, 200):
                cases.append({"value": value, "max_len": max_len, "keep_newlines": keep,
                              "result": textclean.clean_text(value, max_len=max_len, keep_newlines=keep)})
    for _ in range(400):
        value = "".join(rng.choice(CHAR_POOL) for _ in range(rng.randrange(0, 40)))
        max_len, keep = rng.choice([1, 3, 10, 25, 4000]), rng.random() < 0.5
        cases.append({"value": value, "max_len": max_len, "keep_newlines": keep,
                      "result": textclean.clean_text(value, max_len=max_len, keep_newlines=keep)})
    return cases


# --------------------------------------------------------------------------- #
# Additive scan
# --------------------------------------------------------------------------- #

ADDITIVE_HAND = [  # (tags, text, name): the inputs of tests/test_additives.py and more
    # v0.3.0 review: the element named in nutrition text is not an additive; its acid is.
    ([], "Milk, vitamin D3. Phosphorus 250 mg per serving", "Milk"), ([], "lait, phosphore 120 mg", "x"),
    ([], "Phosphor: 300 mg", "x"), ([], "fosforo 90 mg, fosfato di sodio", "x"), ([], "water, phosphorous acid", "x"),
    ([], "Phosphorsäure, Wasser", "x"),
    ([], "chicken, water, sodium tripolyphosphate, salt", "x"), ([], "milk, dipotassium phosphate", "x"),
    ([], "flour, sodium acid pyrophosphate, baking soda", "x"), ([], "carbonated water, caramel color, phosphoric acid", "x"),
    ([], "cheese culture, sodium phosphate, salt", "x"), ([], "calcium phosphate, vitamin d", "x"),
    ([], "sodium aluminum phosphate", "x"), ([], "sodium hexametaphosphate", "x"), ([], "PHOSPHATE", "x"),
    ([], "fosfato de sodio", "x"), ([], "Natriumphosphat", "x"), ([], "natriumfosfaat", "x"), ([], "contains e 450 (i) and E-451", "x"),
    ([], "soy lecithin (phospholipids)", "x"), ([], "phosphatidylserine", "x"), ([], "lecitina di soia (fosfolipidi)", "x"),
    ([], "fosfatidilserina", "x"), ([], "ammonium phosphatides (e442)", "x"),
    ([], "modified corn starch (hydroxypropyl distarch phosphate)", "x"),
    ([], "acetylated distarch phosphate, distarch phosphate, phosphated distarch phosphate", "x"),
    ([], "riboflavin-5'-phosphate (color)", "x"), ([], "sugar, water, citric acid", "x"), ([], "distarch phosphate, sodium phosphate", "x"),
    ([], "water, potassium lactate, sodium diacetate", "x"), ([], "dipotassium phosphate", "x"), ([], "potassium chloride", "x"),
    ([], "cream of tartar", "x"), ([], "potassium citrate", "x"), ([], "potassium bicarbonate", "x"),
    ([], "potassium hydrogen carbonate", "x"), ([], "potassium sodium tartrate", "x"), ([], "tetrapotassium pyrophosphate", "x"),
    ([], "monopotassium glutamate", "x"), ([], "potassium hydroxide", "x"), ([], "potassium sulfate", "x"),
    ([], "potassium alginate", "x"), ([], "potassium propionate", "x"), ([], "salt substitute", "x"), ([], "Kaliumchlorid", "x"),
    ([], "kalium lactaat", "x"), ([], "kaliumfosfaat", "x"), ([], "Kaliumlaktat", "x"), ([], "chlorure de potassium", "x"),
    ([], "lactato de potasio", "x"), ([], "cloruro di potassio", "x"), ([], "citrato de potássio", "x"), ([], "contains E326 and e508", "x"),
    ([], "potassium sorbate (preservative)", "x"), ([], "potassium benzoate", "x"), ([], "potassium metabisulfite", "x"),
    ([], "potassium iodide", "x"), ([], "salt, potassium iodate", "x"), ([], "potassium nitrite", "x"), ([], "acesulfame potassium", "x"),
    ([], "acesulfame k, sucralose", "x"), ([], "aluminium potassium sulphate", "x"), ([], "potassium aluminium silicate", "x"),
    ([], "dipotassium inosinate, dipotassium guanylate", "x"), ([], "sorbate de potassium", "x"), ([], "Jodsalz (Speisesalz, Kaliumjodat)", "x"),
    ([], "potassium", "x"), ([], "potassium (as potassium iodide)", "x"), ([], "acidity regulator e330 and e450 (v)", "x"),
    ([], "E340 in brine", "x"), ([], "Potassium chloride, silicon dioxide", "Seasoning"),
    ([], "Ingredients: potassium chloride (99%), anticaking agent", "Seasoning"), ([], "E508, E551", "Seasoning"),
    ([], "kaliumchlorid, zucker", "Seasoning"), ([], "chlorure de potassium, iodure de potassium", "Seasoning"),
    ([], "turkey, water, salt, potassium chloride", "Deli turkey"),
    *[([], None, n) for n in ("NoSalt Original", "No-Salt", "Nu-Salt", "Nu Salt", "Morton Lite Salt", "LoSalt", "Half Salt",
                              "Salt Substitute", "Herb salt replacer", "No Salt Added Green Beans", "No-Salt-Added Diced Tomatoes",
                              "Salted butter", "Halo salt crisps", "Sea salt chips")],
    *[([], f"sodium phos{h}phate", "x") for h in ("​", "­", "‍", "⁠", "﻿", "‮", "⁦")],
    *[([], f"potassium{h} chloride, water", "x") for h in ("​", "­", "‮")],
    *[([], None, f"No{h}Salt") for h in ("​", "­")],
    *[([f"en:e3{h}38"], None, "x") for h in ("​", "­")],
    ([], "ＳＯＤＩＵＭ ＰＨＯＳＰＨＡＴＥ", "x"), (None, None, None), ([None, 5, {"a": 1}, ["e338"]], 12, 3.5),
    ([], "water, " * 700 + "sodium phosphate", "x"), (["en:e330"] * 220 + ["en:e338"], None, "x"),
    (["en:e451i", "en:e326"], "water, sodium tripolyphosphate, potassium lactate", "Ham"),
    (["en:e150d", "en:e338", "en:e950", "en:e951", "en:e212"], None, "Diet Coke"),
    (["en:e451", "en:e451i", "en:e339", "en:e341"], None, "Macaroni & Cheese"),
    *[([f"en:{c}"], None, "x") for c in sorted(additives.PHOSPHATE | additives.PHOSPHATE_TRACE | additives.POTASSIUM_BULK | additives.POTASSIUM_TRACE)],
    *[([t], None, "x") for t in ("en:e451i", "en:e451ii", "en:e450i", "en:e450v", "en:e452i", "en:e452ii", "en:e340ii", "en:e332i",
                                 "en:e954iv", "en:e954i", "EN:E508", "e326", "en:e330", "en:e150d", "en:e160a", "", "en:", "phosphate",
                                 "fr:e451", "eng:e339", " en:e338 ", "en:e3381", "en:e33")],
    ([], "Weißer Zucker, Süßmolkenpulver, Kaliumphosphat, ẞ", "Süßes"), ([], "ς phosphate", "x"),
    ([], "Natriumphosphatßalz, KALIUMPHOSPHATẞ, phosphatς, ϕosphate", "x"),
    ([], "phosphoric\nacid", "x"), ([], "phosphorique acide", "x"), ([], "acide phosphorique", "x"), ([], "fosfórico acid", "x"),
    ([], "trisodium\nphosphate", "x"), ([], "😀phosphate", "x"), ([], "𝐚phosphate", "x"), ([], "e451 i", "x"), ([], "e451(ii)", "x"),
    ([], "e 4 5 1", "x"), ([], "e-1442", "x"), ([], "sodium, potassium phosphate", "x"),
]
INGREDIENT_WORDS = [
    "water", "sugar", "salt", "flour", "milk", "cheese", "chicken", "beef", "corn syrup", "citric acid", "natural flavor", "spices",
    "vitamin c", "soy lecithin", "caramel color", "yeast", "vinegar", "sunflower oil", "cocoa", "hazelnuts",
    *additives.NAME_TO_CODE.keys(), *additives.E_NAMES.values(),
    "fosfato disódico", "phosphate de sodium", "Natriumcitrat", "kaliumsorbat", "sorbato de potasio", "lattato di potassio",
    "difosfati", "polyphosphates de sodium", "salt substitute", "lite salt", "kcl", "potassium iodide", "kaliumjodat",
    "hydroxypropyl distarch phosphate", "riboflavin 5'-phosphate", "magnesium ascorbyl phosphate", "phosphatidylcholine",
]
E_SPELLINGS = ["E{c}", "e{c}", "E {c}", "E-{c}", "e{c} i", "E{c} (ii)", "E{c}(v)", "E {c} iv"]
INVISIBLE = ["​", "­", "⁠", "﻿", "‮"]


def generated_lists(rng: random.Random, n: int) -> list[tuple]:
    out = []
    codes = sorted({c[1:] for c in additives.E_NAMES} | {"330", "150d", "951", "160a", "1400"})
    for _ in range(n):
        parts = []
        for _ in range(rng.randrange(1, 9)):
            if rng.random() < 0.2:
                code = rng.choice(codes)
                parts.append(rng.choice(E_SPELLINGS).format(c=code.rstrip("iv") if rng.random() < 0.5 else code))
            else:
                word = rng.choice(INGREDIENT_WORDS)
                style = rng.random()
                if style < 0.15:
                    word = word.upper()
                elif style < 0.3:
                    word = word.title()
                if rng.random() < 0.1:
                    pos = rng.randrange(0, len(word) + 1)
                    word = word[:pos] + rng.choice(INVISIBLE) + word[pos:]
                if rng.random() < 0.05:
                    word = "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in word)  # full width
                parts.append(word)
        sep = rng.choice([", ", ",", "; ", "\n", " (", ", and "])
        text = sep.join(parts)
        if rng.random() < 0.2:
            text = rng.choice(["Ingredients: ", "INGREDIENTS : ", "Zutaten: ", "ingrédients: "]) + text
        tags = [f"en:e{rng.choice(codes)}" for _ in range(rng.randrange(0, 4))] if rng.random() < 0.3 else []
        name = rng.choice(["Product", "Sea salt chips", "NoSalt", "Lite Salt", "Ham", "x", "Nu-Salt blend"])
        out.append((tags, text, name))
    return out


def fixture_inputs() -> list[tuple]:
    out = []
    for path in sorted((ROOT / "tests" / "fixtures" / "off").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8")).get("body") or {}
        product = body.get("product") or {}
        out.append((product.get("additives_tags") or [], product.get("ingredients_text"), product.get("product_name")))
    for path in sorted((ROOT / "tests" / "fixtures" / "usda").glob("food_*.json")):
        body = json.loads(path.read_text(encoding="utf-8")).get("body") or {}
        out.append(([], body.get("ingredients"), body.get("description")))
    return out


def scan_result(tags, text, name) -> dict:
    r = additives.scan(tags, text, name)
    return {"flags": list(r.flags), "findings": [{"code": f.code, "name": f.name, "kind": f.kind, "source": f.source} for f in r.findings],
            "kidney_notes": r.kidney_notes, "additives": r.additives, "notes": r.notes}


def additive_vectors(rng: random.Random) -> list[dict]:
    inputs = ADDITIVE_HAND + fixture_inputs() + generated_lists(rng, 500)
    return [{"tags": t, "text": x, "name": n, "result": scan_result(t, x, n)} for t, x, n in inputs]


def quality_vectors() -> list[dict]:
    lists = [[], list(off.QUALITY_MESSAGES), ["implausible:sodium_mg", "filled_from_usda:potassium_mg", "filled_from_off:phosphorus_mg"],
             ["implausible", "filled_from_usda", "unknown_code", "crowd_sourced", "implausible:not_a_key"], ["potassium_unknown"]]
    return [{"codes": codes, "items": off.quality_items(codes)} for codes in lists]


# --------------------------------------------------------------------------- #
# Open Food Facts mapping (device mode, design note 38 §5.3)
# --------------------------------------------------------------------------- #

# Each case keeps the product as JSON text: that is what the iPhone app hands the page, and it carries what a
# parsed object cannot (1e400, which JSON readers turn into infinity).
OFF_HAND: list[tuple[str, str, object]] = [  # (id, GTIN-14, product: a dict or raw JSON text)
    ("empty", "00049000028911", {}),
    ("no_nutrients", "00049000028911", {"product_name": "Plain water", "serving_quantity": 250, "serving_quantity_unit": "ml"}),
    ("salt_no_sodium_eu", "03017624010701", {"product_name": "Crisps", "countries_tags": ["en:france"],
                                             "nutriments": {"energy-kcal_100g": 530, "fat_100g": 33, "carbohydrates_100g": 50,
                                                            "proteins_100g": 6, "salt_100g": 1.2}}),
    ("salt_and_sodium_match", "03017624010701", {"countries_tags": ["en:germany"], "serving_quantity": 30, "serving_quantity_unit": "g",
                                                 "nutriments": {"energy-kcal_100g": 500, "salt_100g": 1.25, "sodium_100g": 0.5,
                                                                "proteins_100g": 5, "fat_100g": 30, "carbohydrates_100g": 50}}),
    ("salt_and_sodium_us", "00049000028911", {"countries_tags": ["en:united-states"], "nutriments": {"salt_100g": 1.25, "sodium_100g": 0.5}}),
    ("per_serving_only", "00049000028911", {"product_name": "Bar", "nutrition_data_per": "serving", "serving_quantity": "40",
                                           "serving_quantity_unit": "g", "serving_size": "1 bar (40 g)",
                                           "nutriments": {"energy-kcal_serving": 190, "proteins_serving": 3, "fat_serving": 8,
                                                          "carbohydrates_serving": 27, "sodium_serving": 0.09, "potassium_serving": 0.11,
                                                          "energy-kcal_100g": 475}}),
    ("per_serving_no_weight", "00049000028911", {"product_name": "Mystery", "nutrition_data_per": "serving",
                                                "nutriments": {"energy-kcal_serving": 190, "proteins_serving": 3}}),
    ("liquid_per_100ml", "00049000028911", {"product_name": "Juice", "nutrition_data_per": "100ml",
                                           "categories_tags": ["en:sweetened-beverages"], "nutriments": {"energy-kcal_100g": 45,
                                           "sugars_100g": 10, "carbohydrates_100g": 11, "potassium_100g": 0.2}}),
    ("drink_powder", "00049000028911", {"product_name": "Cocoa mix", "categories_tags": ["en:beverages", "en:instant-beverages"],
                                        "nutriments": {"energy-kcal_100g": 400, "carbohydrates_100g": 80}}),
    ("alcohol", "00049000028911", {"product_name": "Ale", "categories_tags": ["en:beverages", "en:alcoholic-beverages"],
                                   "serving_quantity": 330, "serving_quantity_unit": "mL", "nutriments": {"energy-kcal_100g": 43}}),
    ("prepared_only", "00021000658831", {"product_name": "Box dinner", "serving_quantity": 70.9, "serving_quantity_unit": "g",
                                         "serving_size": "2.5 oz (70.9 g) makes about 1 cup, a serving size written out long enough to be cut",
                                         "nutrition_data_prepared_per": "serving",
                                         "nutriments": {"energy-kcal_prepared_serving": 350, "proteins_prepared_serving": 10,
                                                        "fat_prepared_serving": 13, "carbohydrates_prepared_serving": 48}}),
    ("kj_only", "00049000028911", {"nutriments": {"energy-kj_100g": 1000, "proteins_100g": 10}}),
    ("energy_only", "00049000028911", {"nutriments": {"energy_100g": "2 000,5", "proteins_100g": "1_0"}}),
    ("energy_mismatch", "00049000028911", {"nutriments": {"energy-kcal_100g": 100, "proteins_100g": 30, "fat_100g": 30,
                                                          "carbohydrates_100g": 30}}),
    ("implausible", "00049000028911", {"nutriments": {"energy-kcal_100g": 2000, "sodium_100g": 50, "proteins_100g": -1,
                                                      "potassium_100g": 70, "phosphorus_100g": 31, "fat_100g": 101}}),
    ("salt_product", "00049000028911", {"categories_tags": ["en:salts"], "nutriments": {"sodium_100g": 39, "salt_100g": 97.5}}),
    ("carbs_total", "03017624010701", {"countries_tags": ["en:united-kingdom"], "nutriments": {"carbohydrates-total_100g": 20,
                                                                                             "carbohydrates_100g": 17}}),
    ("non_finite_text", "00049000028911", '{"serving_quantity": "NaN", "nutriments": {"energy-kcal_100g": "Infinity", '
                                          '"proteins_100g": "-inf", "fat_100g": "nan", "sugars_100g": 1e400, '
                                          '"carbohydrates_100g": "1e400", "fiber_100g": "  3 ", "salt_100g": true}}'),
    ("odd_numbers", "00049000028911", {"serving_quantity": " ١٢ ", "serving_quantity_unit": " G ",
                                       "nutriments": {"energy-kcal_100g": "1__0", "proteins_100g": "0x10", "fat_100g": "+.5e1",
                                                      "carbohydrates_100g": "5.", "fiber_100g": " 2 ", "sugars_100g": "1e",
                                                      "sodium_100g": [1], "potassium_100g": {"v": 1}, "calcium_100g": None}}),
    ("long_text", "00049000028911", {"product_name": "Crunchy " * 60, "brands": "Brand " * 50 + ", Other",
                                     "ingredients_text": "water, " * 700 + "sodium phosphate", "serving_size": "x" * 80,
                                     "serving_quantity": 25, "serving_quantity_unit": "g", "nutriments": {"proteins_100g": 1}}),
    ("invisible_text", "00049000028911", {"product_name": "​‮", "product_name_en": "Diet­ Cola", "brands": "​Acme",
                                          "ingredients_text_en": "sodium phos​phate, potassium­ chloride",
                                          "nutriments": {"energy-kcal_100g": 1}}),
    ("generic_name_only", "00000096385074", {"generic_name": "Rice cakes", "brands": 5, "nova_group": "4",
                                             "nutriments": {"energy-kcal_100g": 380}}),
    ("nova_4", "00049000028911", {"nova_group": 4, "nutriments": {"energy-kcal_100g": 380}}),
    ("no_nutrition_flag", "00049000028911", {"no_nutrition_data": "on", "nutriments": {"energy-kcal_100g": 380}}),
    ("salt_substitute", "00049000028911", {"product_name": "NoSalt Original", "ingredients_text": "potassium chloride, fumaric acid",
                                           "nutriments": {"potassium_100g": 50, "sodium_100g": 0}}),
    ("serving_too_big", "00049000028911", {"serving_quantity": 200000, "serving_quantity_unit": "g", "nutriments": {"proteins_100g": 1}}),
    ("serving_ounces", "00049000028911", {"serving_quantity": 2, "serving_quantity_unit": "oz", "nutriments": {"proteins_100g": 1}}),
    ("serving_g_tie", "00049000028911", {"serving_quantity": 10000.25, "serving_quantity_unit": "g", "nutriments": {"proteins_100g": 1}}),
    ("not_a_dict_parts", "00049000028911", {"nutriments": ["energy-kcal_100g"], "categories_tags": "en:beverages",
                                            "countries_tags": [None, 5, "EN:United-States"], "nutrition": {"aggregated_set": []}}),
    ("v35_per_serving", "00049000028911", {"serving_quantity": 30, "serving_quantity_unit": "g", "nutriments": {},
                                           "nutrition": {"aggregated_set": {"per": "SERVING", "preparation": "as_sold", "nutrients": {
                                               "energy-kcal": {"value": 150, "unit": "kcal"}, "energy": {"value": 600, "unit": "kJ"},
                                               "proteins": {"value": 2000, "unit": "mg"}, "sodium": {"value": 120000, "unit": "µg"},
                                               "potassium": {"value": "0,2", "unit": "G"}, "fat": {"value": 5, "unit": "oz"},
                                               "phosphorus": {"value": 0.0001, "unit": "kg"}, "sugars": {"value": 1}}}}}),
    ("v35_prepared_100ml", "00049000028911", {"nutrition": {"aggregated_set": {"per": "100ml", "preparation": "prepared", "nutrients": {
        "energy": {"value": 200, "unit": "kJ"}, "carbohydrates": {"value": 10, "unit": "g"}, "calcium": {"value": 120, "unit": "mg"}}}}}),
    ("v35_no_serving_per_serving", "00049000028911", {"nutrition": {"aggregated_set": {"per": "serving", "nutrients": {
        "energy-kj": {"value": 400, "unit": "kcal"}, "proteins": {"value": 3, "unit": "g"}}}}}),
    ("float_text_numbers", "00049000028911", '{"serving_quantity": 30.0, "serving_quantity_unit": "g", "nova_group": 4.0, '
                                             '"nutriments": {"energy-kcal_100g": 100.0, "proteins_100g": -0.0, "fat_100g": 1E2}}'),
]
OFF_TAGS = ["en:beverages", "en:sweetened-beverages", "en:alcoholic-beverages", "en:dairies", "en:meats", "en:snacks", "en:salts",
            "en:dried-products-to-be-rehydrated", "en:pizzas", "en:fruits", "EN:Sauces", "en:dehydrated-beverages"]
OFF_NUMBER_FORMS = [lambda v: v, lambda v: str(v), lambda v: str(v).replace(".", ","), lambda v: f" {v} ", lambda v: "abc",
                    lambda v: None, lambda v: -v, lambda v: v * 1000, lambda v: "NaN", lambda v: True]


def _mutate_off(rng: random.Random, product: dict) -> dict:
    p = json.loads(json.dumps(product))
    nutriments = p.get("nutriments") if isinstance(p.get("nutriments"), dict) else {}
    for key in list(nutriments):
        r = rng.random()
        if r < 0.2:
            del nutriments[key]
        elif r < 0.3 and isinstance(nutriments[key], (int, float)) and not isinstance(nutriments[key], bool):
            nutriments[key] = rng.choice(OFF_NUMBER_FORMS)(nutriments[key])
    if rng.random() < 0.3:
        p["nutrition_data_per"] = rng.choice(["serving", "100g", "100ml", None, "SERVING"])
    if rng.random() < 0.3:
        p["serving_quantity"] = rng.choice([None, 0, -5, "30", 30, 200000, "1e3", 354.9, "12,5", True])
    if rng.random() < 0.3:
        p["serving_quantity_unit"] = rng.choice(["g", "ml", "ML", " g ", "oz", None, ""])
    if rng.random() < 0.3:
        p["countries_tags"] = rng.choice([[], ["en:united-states"], ["en:france"], None, ["en:canada", "en:france"]])
    if rng.random() < 0.4:
        p["categories_tags"] = rng.sample(OFF_TAGS, rng.randrange(0, 4))
    if rng.random() < 0.2:
        p["nova_group"] = rng.choice([4, "4", 3, None])
    if rng.random() < 0.2:
        p["product_name"] = rng.choice([None, "", "x" * 250, "Cola​ Zero", 12])
    if rng.random() < 0.2:
        p["brands"] = rng.choice(["A, B", 5, None, " ,B"])
    if rng.random() < 0.1:
        p["no_nutrition_data"] = rng.choice(["on", "off", "ON"])
    if rng.random() < 0.2:
        p["additives_tags"] = rng.sample(["en:e338", "en:e451i", "en:e508", "en:e330", "en:e212", "bad"], rng.randrange(0, 4))
    return p


def _off_case(case_id: str, gtin14: str, product_json: str) -> dict:
    from app import barcode

    product = json.loads(product_json)
    case: dict = {"id": case_id, "gtin14": gtin14, "json": product_json}
    try:
        mapped = off.map_product(product, gtin14)
    except Exception as exc:  # the twin must fail where the server fails
        case["error"] = type(exc).__name__
        return case
    case["trimmed"] = off.trim_product(product)
    case["mapped"] = dataclasses.asdict(mapped)
    if mapped.status == "found":
        assembled = barcode.assemble(gtin14, barcode.OffOutcome("found", mapped), barcode.UsdaOutcome("skipped"))
        assert assembled is not None
        p = assembled.provenance
        case["row"] = {**assembled.kwargs, "source": assembled.source, "gtin": p.gtin, "source_url": p.source_url,
                       "source_license": p.source_license, "ingredients_text": p.ingredients_text,
                       "additives": list(p.additives), "quality": list(p.quality)}
    return case


def off_map_vectors() -> list[dict]:
    """``off.map_product`` (and ``trim_product``) over every recorded product, hand-made edge cases and seeded
    variants of the recorded products, against ``KH.off.mapProduct`` / ``trimProduct`` / ``row``."""
    rng = random.Random(SEED + 38)  # its own stream: the other groups stay as they were
    cases = []
    recorded = []
    for path in sorted((ROOT / "tests" / "fixtures" / "off").glob("*.json")):
        product = (json.loads(path.read_text(encoding="utf-8")).get("body") or {}).get("product")
        if not isinstance(product, dict):
            continue
        gtin14 = str(product["code"]).zfill(14)
        recorded.append((path.stem, gtin14, product))
        cases.append(_off_case(f"fixture:{path.stem}", gtin14, json.dumps(product, ensure_ascii=False)))
        cases.append(_off_case(f"fixture-trimmed:{path.stem}", gtin14, json.dumps(off.trim_product(product), ensure_ascii=False)))
    for case_id, gtin14, product in OFF_HAND:
        text = product if isinstance(product, str) else json.dumps(product, ensure_ascii=False)
        cases.append(_off_case(case_id, gtin14, text))
    for n in range(150):
        stem, gtin14, product = rng.choice(recorded)
        cases.append(_off_case(f"variant:{n}:{stem}", gtin14, json.dumps(_mutate_off(rng, product), ensure_ascii=False)))
    return cases


# --------------------------------------------------------------------------- #
# The demo's three products (the real route over the recorded fixtures)
# --------------------------------------------------------------------------- #


def demo_products() -> list[dict]:
    from app import barcode
    from barcode_support import Replay, load
    from conftest import HTTPS_URL, make_settings, signed_in_client

    logging.disable(logging.CRITICAL)
    replay = Replay(*(load("off", name) for name, _code, _fmt in DEMO_FIXTURES))
    saved = barcode.off_transport, barcode.sleep
    barcode.off_transport, barcode.sleep = (lambda: replay), (lambda seconds: None)
    out = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            foods_json = tmp_path / "foods.json"
            foods_json.write_text((ROOT / "data" / "foods.json").read_text(encoding="utf-8"), encoding="utf-8")
            settings = make_settings(tmp_path, foods_json)
            with signed_in_client(settings, base_url=HTTPS_URL) as client:
                assert client.patch("/api/admin/settings", json={"food.off_enabled": True}).status_code == 200
                assert client.patch("/api/me/settings", json={"food.off_consent": True}).status_code == 200
                for name, code, fmt in DEMO_FIXTURES:
                    res = client.post("/api/foods/barcode", json={"code": code, "format": fmt})
                    assert res.status_code == 200, (name, res.text)
                    result = res.json()
                    food_id = result["food"].pop("id")
                    conn = sqlite3.connect(settings.data_dir / "kidney.db")
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
                    conn.close()
                    stored = {k: row[k] for k in ROW_FIELDS}
                    stored["nutrients"] = {k: row[k] for k in NUTRIENT_KEYS}
                    stored["flags"] = json.loads(row["flags_json"])
                    stored["additives"] = json.loads(row["additives_json"])
                    stored["quality"] = json.loads(row["quality_json"])
                    out.append({"fixture": name, "code": code, "format": fmt, "row": stored, "result": result})
    finally:
        barcode.off_transport, barcode.sleep = saved
        logging.disable(logging.NOTSET)
    return out


def build() -> dict:
    rng = random.Random(SEED)
    return {
        "about": "Generated by tests/data/gen_barcode_vectors.py from app/gtin.py, app/textclean.py, app/additives.py, "
                 "app/off.py and the barcode route; replayed by tests/js/run_vectors.mjs.",
        "check_digit_cases": [{"body": b, "digit": gtin.check_digit(b)} for b in ("04900002891", "301762401070", "9638507", "0", "1234567890123")],
        "gtin_cases": gtin_vectors(rng),
        "textclean_cases": textclean_vectors(rng),
        "additive_cases": additive_vectors(rng),
        "quality_cases": quality_vectors(),
        "demo_products": demo_products(),
        "off_map_cases": off_map_vectors(),
    }


def dump(doc: dict) -> str:
    # ASCII escapes keep lone surrogates and invisible characters intact and visible in diffs.
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
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_barcode_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
