"""Barcode numbers (GTINs): normalisation, validation and classification (note 03 R2, F6).

Pure functions, no I/O. The same product reaches the server as 12, 13 or 8 digits depending on the
decoder (note 03 F5: a native detector reports UPC-A ``049000028911``, ZXing reports
``0049000028911``, and UPC-E ``01234565`` arrives already expanded as ``0012345000065``), so every
code is normalised here, in one place, to a **GTIN-14** (14 digits, zero-padded), the key the
database stores.

GS1 facts used here (GS1 General Specifications; GS1 prefix list, https://www.gs1.org/prefixes):

* The check digit is mod 10 with weights 3, 1, 3, … counted from the right (excluding the check
  digit itself).
* UPC-E is a zero-suppressed UPC-A; it is expanded by a fixed table on its six middle digits. An
  8-digit code is UPC-E only when the decoder says so: otherwise it is an EAN-8.
* A GTIN-8 sits in the 14-digit field as ``000000`` + its 8 digits; in 13-digit form every code
  starting ``00000`` is in the GTIN-8 range and is classified by its **GS1-8 prefix** (the first
  three digits of the GTIN-8): 000–099 and 200–299 are restricted-circulation numbers, 977–999 are
  reserved, the rest are product codes.
* GTIN-13 prefixes 020–029, 040–049 and 200–299 are restricted-circulation numbers (in-store codes
  for weighed deli, meat and produce, unique only inside one store or company): looking one up would
  return a stranger's product, so they are never looked up. 977 is ISSN (periodicals), 978–979 ISBN
  (books), 050–059 are reserved by GS1 US (formerly UPC coupons), 980–999 are refund receipts and
  coupons.
* A GTIN-14 whose indicator digit is 9 identifies a variable-measure trade item (weighed): restricted.
"""
from __future__ import annotations

import re
from typing import Literal

GtinClass = Literal["retail", "restricted", "isbn", "issn", "coupon", "reserved"]
# Formats a client may report (the BarcodeDetector names; "unknown" for typed digits).
FORMATS: tuple[str, ...] = ("ean_13", "ean_8", "upc_a", "upc_e", "unknown")

_ALLOWED_LENGTHS = (8, 12, 13, 14)
# Typed codes are often grouped ("4 006381 333931", "0-49000-02891-1"): spaces and hyphens are
# separators; any other non-digit makes the code invalid.
_SEPARATORS = re.compile(r"[\s\-]+")
_DIGITS = re.compile(r"^[0-9]+$")


class GtinError(ValueError):
    """A code that cannot be a GTIN. ``reason`` is ``"format"`` or ``"check_digit"``."""

    def __init__(self, reason: Literal["format", "check_digit"], message: str) -> None:
        super().__init__(message)
        self.reason = reason


def check_digit(body: str) -> int:
    """The GS1 mod-10 check digit for ``body`` (all digits except the check digit)."""
    if not body or not _DIGITS.match(body):
        raise ValueError("body must be a non-empty string of digits")
    total = 0
    for position, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if position % 2 == 0 else 1)
    return (10 - total % 10) % 10


def has_valid_check_digit(code: str) -> bool:
    """True when the last digit of ``code`` is the GS1 check digit of the others."""
    return len(code) >= 2 and _DIGITS.match(code) is not None and check_digit(code[:-1]) == int(code[-1])


def expand_upce(code: str) -> str:
    """Expand an 8-digit UPC-E (number system, six digits, check digit) to the 12-digit UPC-A.

    The check digit is carried over unchanged (it is the UPC-A's check digit); validate it after
    expanding. Only number systems 0 and 1 exist for UPC-E.
    """
    if len(code) != 8 or not _DIGITS.match(code):
        raise GtinError("format", "A UPC-E code has 8 digits.")
    system, d, check = code[0], code[1:7], code[7]
    if system not in "01":
        raise GtinError("format", "A UPC-E code starts with 0 or 1.")
    last = d[5]
    if last in "012":
        middle = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        middle = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        middle = d[0:4] + "00000" + d[4]
    else:  # 5-9
        middle = d[0:5] + "0000" + last
    return system + middle + check


def normalize(code: str, fmt: str | None = None) -> str:
    """Return the GTIN-14 for ``code`` or raise :class:`GtinError`.

    * Spaces and hyphens are ignored; any other non-digit, or a length outside 8, 12, 13 and 14,
      is ``format``.
    * 8 digits with ``fmt == "upc_e"``: expanded to UPC-A first. 8 digits otherwise: EAN-8.
      12: UPC-A. 13: EAN-13. 14: GTIN-14.
    * The GS1 check digit must match (``check_digit``).
    * Zero-padded to 14 digits.
    """
    if not isinstance(code, str):
        raise GtinError("format", "The barcode must be text made of digits.")
    digits = _SEPARATORS.sub("", code)
    if not digits or not _DIGITS.match(digits) or not digits.isascii():
        raise GtinError("format", "A barcode is made of digits only.")
    if len(digits) not in _ALLOWED_LENGTHS:
        raise GtinError("format", "A product barcode has 8, 12, 13 or 14 digits.")
    if len(digits) == 8 and fmt == "upc_e":
        digits = expand_upce(digits)
    if not has_valid_check_digit(digits):
        raise GtinError("check_digit", "The last digit of this barcode does not match the others. Check the number and try again.")
    return digits.zfill(14)


def is_gtin8(gtin14: str) -> bool:
    """True when the GTIN-14 holds a GTIN-8 (six leading zeros)."""
    return gtin14.startswith("000000")


def classify(gtin14: str) -> GtinClass:
    """``retail`` for a product code that may be looked up; otherwise why not."""
    if len(gtin14) != 14 or not _DIGITS.match(gtin14):
        raise ValueError("classify() takes a GTIN-14")
    if gtin14[0] == "9":
        return "restricted"  # variable-measure trade item
    gtin13 = gtin14[1:]
    if gtin13.startswith("00000"):  # the GTIN-8 range: judge by the GS1-8 prefix
        prefix8 = int(gtin13[5:8])
        if prefix8 <= 99 or 200 <= prefix8 <= 299:
            return "restricted"
        if prefix8 >= 977:
            return "reserved"
        return "retail"
    prefix = int(gtin13[:3])
    if 20 <= prefix <= 29 or 40 <= prefix <= 49 or 200 <= prefix <= 299:
        return "restricted"
    if 50 <= prefix <= 59:
        return "coupon"  # reserved by GS1 US (formerly UPC coupons)
    if prefix == 977:
        return "issn"
    if prefix in (978, 979):
        return "isbn"
    if prefix >= 980:
        return "coupon"  # 980 refund receipts, 981-984 and 99x coupons
    return "retail"


def off_code(gtin14: str) -> str:
    """The code Open Food Facts uses: 8 digits for a GTIN-8, 13 for EAN-13/UPC-A, 14 otherwise.

    OFF pads codes of 9–12 digits to 13 and keeps EAN-8 at 8 (its barcode normalisation rules), so
    UPC-A ``049000028911`` is product ``0049000028911`` there.
    """
    if is_gtin8(gtin14):
        return gtin14[6:]
    return gtin14[1:] if gtin14[0] == "0" else gtin14


def usda_candidates(gtin14: str) -> list[str]:
    """The forms to try in a FoodData Central search: 12-digit UPC-A (when it starts ``00``), 13, 14."""
    forms: list[str] = []
    if gtin14.startswith("00"):
        forms.append(gtin14[2:])
    if gtin14.startswith("0"):
        forms.append(gtin14[1:])
    forms.append(gtin14)
    return forms


def loose_gtin14(value: object) -> str | None:
    """A provider's barcode field (FoodData Central ``gtinUpc``) as a 14-digit string, or ``None``.

    Upstream values are not validated (no check digit test); they are only compared for exact
    equality with a GTIN-14 that :func:`normalize` produced. Non-digits other than spaces and
    hyphens, an empty value or more than 14 digits give ``None``.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    digits = _SEPARATORS.sub("", value)
    if not digits or len(digits) > 14 or not _DIGITS.match(digits) or not digits.isascii():
        return None
    return digits.zfill(14)
