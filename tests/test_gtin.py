"""GTIN normalisation, validation and classification (note 03 R2, F5, F6; §6 checklist item 3)."""
from __future__ import annotations

import pytest

from app import gtin
from app.gtin import GtinError, classify, normalize, off_code, usda_candidates


def ref_check(body: str) -> str:
    """Independent GS1 mod-10: weight 3 on the digit next to the check digit, alternating leftwards."""
    total = sum(int(d) * (3 if (len(body) - i) % 2 == 1 else 1) for i, d in enumerate(body))
    return str((10 - total % 10) % 10)


def with_check(body: str) -> str:
    return body + ref_check(body)


# --------------------------------------------------------------------------- #
# The measured decoder outputs (note 03 F5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code, fmt",
    [
        ("049000028911", "upc_a"),  # native BarcodeDetector style: 12-digit UPC-A
        ("0049000028911", "ean_13"),  # ZXing (zxing-wasm 3.1.3) reports UPC-A as EAN-13
        ("00049000028911", "unknown"),  # GTIN-14 typed by hand
        ("049000028911", None),
        ("0 49000 02891 1", "unknown"),  # typed with the grouping printed under the bars
        ("0-49000-02891-1", "unknown"),
    ],
)
def test_diet_coke_in_every_shape_normalises_to_one_gtin14(code: str, fmt: str | None) -> None:
    assert normalize(code, fmt) == "00049000028911"


def test_upce_measured_shapes_normalise_to_the_same_gtin14() -> None:
    # UPC-E 01234565 as a native detector reports it (8 digits) and as ZXing does (expanded, 13 digits).
    assert normalize("01234565", "upc_e") == "00012345000065"
    assert normalize("0012345000065", "ean_13") == "00012345000065"
    assert normalize("012345000065", "upc_a") == "00012345000065"


@pytest.mark.parametrize(
    "upce, upca",
    [
        ("04252614", "042100005264"),  # last data digit 0-2: manufacturer d1 d2 d6 00, product 00 d3 d4 d5
        ("01234531", "012300000451"),  # last digit 3: d1 d2 d3 00, product 000 d4 d5
        ("01234543", "012340000053"),  # last digit 4: d1 d2 d3 d4 0, product 0000 d5
        ("01234565", "012345000065"),  # last digit 5-9: d1..d5, product 0000 d6
        ("11234562", "112345000062"),  # number system 1
    ],
)
def test_upce_expansion_all_four_cases(upce: str, upca: str) -> None:
    assert gtin.expand_upce(upce) == upca
    assert ref_check(upca[:-1]) == upca[-1]
    assert normalize(upce, "upc_e") == upca.zfill(14)


def test_eight_digits_are_ean8_unless_the_decoder_says_upc_e() -> None:
    assert normalize("96385074", "ean_8") == "00000096385074"
    assert normalize("96385074", "unknown") == "00000096385074"
    assert normalize("96385074", None) == "00000096385074"
    # The same digits read as UPC-E expand to another product (and here fail the check digit).
    with pytest.raises(GtinError) as info:
        normalize("96385074", "upc_e")
    assert info.value.reason == "format"  # UPC-E number system must be 0 or 1


def test_upce_with_a_bad_check_digit_is_refused() -> None:
    with pytest.raises(GtinError) as info:
        normalize("01234566", "upc_e")
    assert info.value.reason == "check_digit"


# --------------------------------------------------------------------------- #
# Check digit and format
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code", ["049000028912", "0049000028910", "3017624010702", "96385075", "00049000028919"])
def test_bad_check_digit(code: str) -> None:
    with pytest.raises(GtinError) as info:
        normalize(code, "unknown")
    assert info.value.reason == "check_digit"


@pytest.mark.parametrize(
    "code",
    ["", "   ", "abc", "04900002891a", "1234567", "123456789", "1234567890", "12345678901",
     "123456789012345", "٠٤٩٠٠٠٠٢٨٩١١", "0490000289１1", "0490000.28911", "+049000028911"],
)
def test_format_errors(code: str) -> None:
    with pytest.raises(GtinError) as info:
        normalize(code, "unknown")
    assert info.value.reason == "format"


def test_non_string_is_a_format_error() -> None:
    with pytest.raises(GtinError) as info:
        normalize(49000028911, "upc_a")  # type: ignore[arg-type]
    assert info.value.reason == "format"


def test_check_digit_matches_the_reference_on_many_bodies() -> None:
    import random

    rnd = random.Random(20261006)
    for _ in range(2000):
        n = rnd.choice([7, 11, 12, 13])
        body = "".join(rnd.choice("0123456789") for _ in range(n))
        assert str(gtin.check_digit(body)) == ref_check(body)
        assert gtin.has_valid_check_digit(body + ref_check(body))


def test_check_digit_rejects_non_digits() -> None:
    with pytest.raises(ValueError):
        gtin.check_digit("12a")
    with pytest.raises(ValueError):
        gtin.check_digit("")


# --------------------------------------------------------------------------- #
# Prefixes (note 03 F6)
# --------------------------------------------------------------------------- #


def g14(body12: str) -> str:
    """A valid GTIN-14 for a 12-digit GTIN-13 body (leading 0 indicator)."""
    return "0" + with_check(body12)


@pytest.mark.parametrize("prefix", ["020", "025", "029", "040", "045", "049", "200", "250", "299"])
def test_restricted_circulation_prefixes(prefix: str) -> None:
    assert classify(g14(prefix + "123456789")) == "restricted"


def test_us_in_store_upc_a_codes_are_restricted() -> None:
    # UPC-A number systems 2 (random-weight) and 4 (in-store) are GTIN-13 prefixes 02x and 04x.
    assert classify(normalize(with_check("21234500000"), "upc_a")) == "restricted"
    assert classify(normalize(with_check("41234500000"), "upc_a")) == "restricted"


@pytest.mark.parametrize("prefix, expected", [
    ("977", "issn"), ("978", "isbn"), ("979", "isbn"),
    ("050", "coupon"), ("055", "coupon"), ("059", "coupon"),
    ("980", "coupon"), ("981", "coupon"), ("984", "coupon"), ("990", "coupon"), ("999", "coupon"),
])
def test_special_prefixes(prefix: str, expected: str) -> None:
    assert classify(g14(prefix + "123456789")) == expected


def test_real_book_is_isbn() -> None:
    assert classify(normalize("9780306406157", "ean_13")) == "isbn"


@pytest.mark.parametrize("prefix", ["001", "019", "030", "039", "060", "099", "300", "301", "400", "500", "690", "760", "890", "976"])
def test_retail_prefixes(prefix: str) -> None:
    assert classify(g14(prefix + "123456789")) == "retail"


def test_retail_examples() -> None:
    assert classify(normalize("049000028911", "upc_a")) == "retail"  # Diet Coke (GS1 US)
    assert classify(normalize("3017624010701", "ean_13")) == "retail"  # Nutella (GS1 France)
    assert classify(normalize("96385074", "ean_8")) == "retail"


@pytest.mark.parametrize("gs1_8, expected", [
    ("000", "restricted"), ("050", "restricted"), ("099", "restricted"),
    ("100", "retail"), ("199", "retail"),
    ("200", "restricted"), ("299", "restricted"),
    ("300", "retail"), ("963", "retail"), ("976", "retail"),
    ("977", "reserved"), ("999", "reserved"),
])
def test_gtin8_classified_by_gs1_8_prefix(gs1_8: str, expected: str) -> None:
    code = with_check(gs1_8 + "1234")
    assert classify(normalize(code, "ean_8")) == expected


def test_variable_measure_gtin14_is_restricted() -> None:
    # Indicator digit 9: a variable-measure trade item (sold by weight).
    assert classify(normalize(with_check("9004900002891"), "unknown")) == "restricted"


def test_classify_takes_a_gtin14() -> None:
    with pytest.raises(ValueError):
        classify("049000028911")


# --------------------------------------------------------------------------- #
# Provider forms
# --------------------------------------------------------------------------- #


def test_off_code() -> None:
    assert off_code("00049000028911") == "0049000028911"  # UPC-A → 13 digits, as OFF stores it
    assert off_code("03017624010701") == "3017624010701"
    assert off_code("00000096385074") == "96385074"  # EAN-8 stays 8
    assert off_code("10049000028918") == "10049000028918"  # a case GTIN-14 stays 14


def test_usda_candidates() -> None:
    assert usda_candidates("00049000028911") == ["049000028911", "0049000028911", "00049000028911"]
    assert usda_candidates("03017624010701") == ["3017624010701", "03017624010701"]
    assert usda_candidates("10049000028918") == ["10049000028918"]


@pytest.mark.parametrize("value, expected", [
    ("049000028911", "00049000028911"), ("0049000028911", "00049000028911"), ("00049000028911", "00049000028911"),
    (49000028911, "00049000028911"), ("49000028911", "00049000028911"), (" 0490 0002 8911 ", "00049000028911"),
    ("", None), (None, None), ("abc", None), ("123456789012345", None), (True, None), (["049000028911"], None),
])
def test_loose_gtin14(value: object, expected: str | None) -> None:
    assert gtin.loose_gtin14(value) == expected
