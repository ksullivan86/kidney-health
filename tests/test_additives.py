"""Additives → flags (note 03 R5, F2; §6 checklist item 4; §9 B3)."""
from __future__ import annotations

import pytest

from app import additives
from app.additives import POTASSIUM_BULK, POTASSIUM_TRACE, PHOSPHATE, PHOSPHATE_TRACE, scan


def flags_of(tags=(), text=None, name="Product") -> tuple[str, ...]:
    return scan(list(tags), text, name).flags


# --------------------------------------------------------------------------- #
# Every E-code of R5, as an OFF tag
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code", sorted(PHOSPHATE))
def test_every_phosphate_code_sets_phosphate_additive(code: str) -> None:
    assert "phosphate_additive" in flags_of([f"en:{code}"])


@pytest.mark.parametrize("code", sorted(PHOSPHATE_TRACE))
def test_trace_phosphates_give_a_note_and_no_flag(code: str) -> None:
    result = scan([f"en:{code}"], None, "x")
    assert result.flags == ()
    assert result.notes and "small amount of phosphate" in result.notes[0]


@pytest.mark.parametrize("code", sorted(POTASSIUM_BULK))
def test_every_bulk_potassium_code_sets_potassium_additive(code: str) -> None:
    assert "potassium_additive" in flags_of([f"en:{code}"])


@pytest.mark.parametrize("code", sorted(POTASSIUM_TRACE))
def test_trace_potassium_gives_a_note_and_no_flag(code: str) -> None:
    result = scan([f"en:{code}"], None, "x")
    assert "potassium_additive" not in result.flags
    assert any("small amount of potassium" in n for n in result.notes)


@pytest.mark.parametrize("tag, expected", [
    ("en:e451i", ("phosphate_additive",)),            # sodium triphosphate: base code e451
    ("en:e451ii", ("phosphate_additive", "potassium_additive")),  # pentapotassium triphosphate
    ("en:e450i", ("phosphate_additive",)),            # disodium diphosphate
    ("en:e450v", ("phosphate_additive", "potassium_additive")),  # tetrapotassium diphosphate
    ("en:e452i", ("phosphate_additive",)),
    ("en:e452ii", ("phosphate_additive", "potassium_additive")),
    ("en:e340ii", ("phosphate_additive", "potassium_additive")),  # every potassium phosphate
    ("en:e332i", ("potassium_additive",)),
    ("en:e954iv", ()),                                # potassium saccharin: trace
    ("en:e954i", ()),                                 # saccharin: nothing
    ("EN:E508", ("potassium_additive",)),             # case-insensitive
    ("e326", ("potassium_additive",)),                # without a language prefix
    ("en:e330", ()), ("en:e150d", ()), ("en:e160a", ()), ("", ()), ("en:", ()), ("phosphate", ()),
])
def test_sub_codes(tag: str, expected: tuple[str, ...]) -> None:
    assert flags_of([tag]) == expected


def test_diet_coke_tags() -> None:
    result = scan(["en:e150d", "en:e338", "en:e950", "en:e951", "en:e212"], None, "Diet Coke")
    assert result.flags == ("phosphate_additive",)
    assert result.additives == ["e338"]
    assert "Contains phosphoric acid (E338), a phosphate additive." in result.notes
    assert any("potassium benzoate (E212)" in n and "no warning" in n for n in result.notes)


def test_kraft_tags() -> None:
    result = scan(["en:e451", "en:e451i", "en:e339", "en:e341"], None, "Macaroni & Cheese")
    assert result.flags == ("phosphate_additive",)
    assert result.additives == ["e451", "e339", "e341"]


# --------------------------------------------------------------------------- #
# Ingredient lists (US names, E-numbers in text, exclusions, other languages)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [
    "chicken, water, sodium tripolyphosphate, salt",
    "milk, dipotassium phosphate",
    "flour, sodium acid pyrophosphate, baking soda",
    "carbonated water, caramel color, phosphoric acid",
    "cheese culture, sodium phosphate, salt",
    "calcium phosphate, vitamin d",
    "sodium aluminum phosphate",
    "sodium hexametaphosphate",
    "PHOSPHATE",
    "fosfato de sodio",  # Spanish
    "Natriumphosphat",  # German
    "natriumfosfaat",  # Dutch
    "contains e 450 (i) and E-451",
])
def test_phosphate_words_and_codes(text: str) -> None:
    assert "phosphate_additive" in flags_of(text=text)


@pytest.mark.parametrize("text", [
    "soy lecithin (phospholipids)",
    "phosphatidylserine",
    "lecitina di soia (fosfolipidi)",
    "fosfatidilserina",
    "ammonium phosphatides (e442)",
    "modified corn starch (hydroxypropyl distarch phosphate)",
    "acetylated distarch phosphate, distarch phosphate, phosphated distarch phosphate",
    "riboflavin-5'-phosphate (color)",
    "sugar, water, citric acid",
])
def test_phosphate_exclusions_and_trace(text: str) -> None:
    assert "phosphate_additive" not in flags_of(text=text)


def test_trace_starch_phosphate_does_not_hide_a_real_phosphate() -> None:
    assert flags_of(text="distarch phosphate, sodium phosphate") == ("phosphate_additive",)


@pytest.mark.parametrize("text, name", [
    ("water, potassium lactate, sodium diacetate", "potassium lactate"),
    ("dipotassium phosphate", "dipotassium phosphate"),
    ("potassium chloride", "potassium chloride"),
    ("cream of tartar", "e336"),
    ("potassium citrate", "potassium citrate"),
    ("potassium bicarbonate", "potassium bicarbonate"),
    ("potassium hydrogen carbonate", "potassium hydrogen carbonate"),
    ("potassium sodium tartrate", "potassium sodium tartrate"),
    ("tetrapotassium pyrophosphate", "tetrapotassium pyrophosphate"),
    ("monopotassium glutamate", "monopotassium glutamate"),
    ("potassium hydroxide", "potassium hydroxide"),
    ("potassium sulfate", "potassium sulfate"),
    ("potassium alginate", "potassium alginate"),
    ("potassium propionate", "potassium propionate"),
    ("salt substitute", "salt substitute"),
    ("Kaliumchlorid", "kaliumchlorid"),          # German
    ("kalium lactaat", "kalium lactaat"),        # Dutch
    ("kaliumfosfaat", "kaliumfosfaat"),          # Dutch, one word
    ("Kaliumlaktat", "kaliumlaktat"),            # German spelling with k
    ("chlorure de potassium", "chlorure de potassium"),  # French
    ("lactato de potasio", "lactato de potasio"),        # Spanish
    ("cloruro di potassio", "cloruro di potassio"),      # Italian
    ("citrato de potássio", "citrato de potássio"),      # Portuguese
    ("contains E326 and e508", None),
])
def test_potassium_salts_in_text(text: str, name: str | None) -> None:
    result = scan([], text, "x")
    assert "potassium_additive" in result.flags
    if name:
        # A known name is stored as its E-code (so a tag and the same name count once).
        assert additives.NAME_TO_CODE.get(name, name) in result.additives


@pytest.mark.parametrize("text", [
    "potassium sorbate (preservative)",
    "potassium benzoate",
    "potassium metabisulfite",
    "potassium iodide",
    "salt, potassium iodate",
    "potassium nitrite",
    "acesulfame potassium",
    "acesulfame k, sucralose",
    "aluminium potassium sulphate",
    "potassium aluminium silicate",
    "dipotassium inosinate, dipotassium guanylate",
    "sorbate de potassium",
    "Jodsalz (Speisesalz, Kaliumjodat)",
    "potassium",  # a bare word, no anion
    "potassium (as potassium iodide)",
])
def test_potassium_trace_is_a_note_only(text: str) -> None:
    result = scan([], text, "x")
    assert "potassium_additive" not in result.flags
    if text != "potassium":
        assert any("small amount of potassium" in n for n in result.notes), result.notes


def test_e_number_suffix_does_not_swallow_the_next_word() -> None:
    result = scan([], "acidity regulator e330 and e450 (v)", "x")
    assert "e450v" in result.additives
    assert flags_of(text="E340 in brine") == ("phosphate_additive", "potassium_additive")


# --------------------------------------------------------------------------- #
# Salt substitutes → avoid_ckd
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [
    "Potassium chloride, silicon dioxide",
    "Ingredients: potassium chloride (99%), anticaking agent",
    "E508, E551",
    "kaliumchlorid, zucker",
    "chlorure de potassium, iodure de potassium",
])
def test_potassium_chloride_first_is_avoid_ckd(text: str) -> None:
    result = scan([], text, "Seasoning")
    assert result.flags[-1] == "avoid_ckd" and "potassium_additive" in result.flags
    assert result.kidney_notes == additives.SALT_SUBSTITUTE_NOTE


def test_potassium_chloride_later_in_the_list_is_not_avoid_ckd() -> None:
    result = scan([], "turkey, water, salt, potassium chloride", "Deli turkey")
    assert result.flags == ("potassium_additive",)
    assert result.kidney_notes is None


@pytest.mark.parametrize("name", ["NoSalt Original", "No-Salt", "Nu-Salt", "Nu Salt", "Morton Lite Salt", "LoSalt",
                                  "Half Salt", "Salt Substitute", "Herb salt replacer"])
def test_salt_substitute_names(name: str) -> None:
    result = scan([], None, name)
    assert result.flags == ("potassium_additive", "avoid_ckd")
    assert result.kidney_notes == additives.SALT_SUBSTITUTE_NOTE


@pytest.mark.parametrize("name", ["No Salt Added Green Beans", "No-Salt-Added Diced Tomatoes", "Salted butter", "Halo salt crisps",
                                  "Sea salt chips"])
def test_names_that_are_not_salt_substitutes(name: str) -> None:
    assert "avoid_ckd" not in flags_of(name=name)


def test_salt_substitute_wording_matches_the_builtin_entries() -> None:
    import json
    from pathlib import Path

    foods = json.loads((Path(__file__).resolve().parents[1] / "data" / "foods.json").read_text(encoding="utf-8"))["foods"]
    builtin = next(f["kidney_notes"] for f in foods if f["name"].startswith("Salt substitute"))
    assert builtin.startswith("AVOID with kidney disease: salt substitutes are potassium chloride")
    assert additives.SALT_SUBSTITUTE_NOTE.startswith("AVOID with kidney disease: salt substitutes are potassium chloride")
    assert builtin.endswith("use herbs, lemon or salt-free herb blends (check they are KCl-free).")
    assert additives.SALT_SUBSTITUTE_NOTE.endswith("use herbs, lemon or salt-free herb blends (check they are KCl-free).")


# --------------------------------------------------------------------------- #
# Invisible characters (§9 B3) and untrusted input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("hidden", ["​", "­", "‍", "⁠", "﻿", "‮", "⁦"])
def test_invisible_characters_do_not_hide_additives(hidden: str) -> None:
    assert flags_of(text=f"sodium phos{hidden}phate") == ("phosphate_additive",)
    assert flags_of(text=f"potassium{hidden} chloride, water") == ("potassium_additive", "avoid_ckd")
    assert flags_of(text=f"water, potassium lac{hidden}tate") == ("potassium_additive",)
    assert flags_of(name=f"No{hidden}Salt") == ("potassium_additive", "avoid_ckd")
    assert flags_of(tags=[f"en:e3{hidden}38"]) == ("phosphate_additive",)


def test_full_width_text_is_scanned() -> None:
    assert flags_of(text="ＳＯＤＩＵＭ ＰＨＯＳＰＨＡＴＥ") == ("phosphate_additive",)


@pytest.mark.parametrize("tags, text, name", [
    (None, None, None), ([None, 5, {"a": 1}, ["e338"]], 12, 3.5), ("en:e338", b"phosphate", object()),
])
def test_non_string_input_is_ignored(tags, text, name) -> None:
    result = scan(tags, text, name)
    # A plain string of tags is iterated character by character and matches nothing.
    assert result.flags == ()


def test_huge_inputs_are_capped() -> None:
    text = "water, " * 2000 + "sodium phosphate"  # beyond the 4,000-character cap
    assert "phosphate_additive" not in flags_of(text=text)
    tags = ["en:e330"] * 500 + ["en:e338"]
    assert flags_of(tags=tags) == ()  # only the first 200 tags are read


def test_result_shape() -> None:
    result = scan(["en:e451i", "en:e326"], "water, sodium tripolyphosphate, potassium lactate", "Ham")
    assert result.flags == ("phosphate_additive", "potassium_additive")
    assert result.additives == ["e451", "e326"]  # the names in the list are the same two additives
    assert result.notes[0] == "Contains potassium lactate (E326), a potassium additive."
    assert all(len(a) <= additives.MAX_PHRASE_CHARS for a in result.additives)


def test_scan_time_is_bounded_on_adversarial_text() -> None:
    """The regexes must not backtrack badly on long hostile input (the list is capped at 4,000 chars)."""
    import time

    samples = [
        "potassium " * 400, "potassium sodium " * 250, "e" + " " * 3998 + "1", "phosph" * 660, "(" * 4000,
        "di starch " * 400, "chlorure de " * 330, "aluminium " * 400, "e450 (" * 650, "a" * 4000,
    ]
    start = time.perf_counter()
    for text in samples:
        scan([], text, text[:200])
    assert time.perf_counter() - start < 2.0


def test_names_and_tags_of_the_same_additive_count_once() -> None:
    result = scan(["en:e338", "en:e212"], "carbonated water, phosphoric acid, potassium benzoate", "Cola")
    assert result.additives == ["e338"]
    assert result.notes == ["Contains phosphoric acid (E338), a phosphate additive.",
                            "Contains potassium benzoate (E212): a small amount of potassium (no warning)."]


def test_unknown_names_are_kept_as_words() -> None:
    result = scan([], "pork, water, sodium erythorbate, potassium tripolyphosphate blend", "Ham")
    assert "e451ii" in result.additives
    result = scan([], "Kaliumchlorid, Zucker", "x")
    assert result.additives == ["kaliumchlorid"]
