"""Versions for every synced kind, and ``If-Match`` for their ``PUT`` and ``DELETE`` routes (design note 39 §8.3; note 02 R5).

Note 02 gave food log entries a version: a 64-bit FNV-1a hash of the canonical text of what the person sees
(:func:`app.log.entry_version`). The same content has the same version on every device, so a phone can tell whether the row it
changed is still the row on the server. This module extends it to the person's own foods, saved meals, lab results, symptoms,
weights and blood pressure readings, each with its own field list (:data:`FIELDS`).

* The input is the row as the API or the export shows it (the two agree on every field used here), so the server, the change feed
  and the browser twin (``js/engine/row_versions.js``, checked by ``tests/data/row_version_vectors.json``) all hash the same text.
* An ``entry`` is :func:`app.log.entry_version` unchanged. Every other kind starts its text with the kind's name, so two kinds never
  share a version by chance.
* A list (a saved meal's items or steps, a food's flags) is its length as a number, then each element.
* :func:`check_if_match` is the 412 of every route: ``{"detail": "This … was changed on another device", "current": <row>}`` with
  the row as stored and its ``version``. Without the header the routes behave as before.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable, Mapping

from fastapi import Header

from .auth.errors import ApiProblem
from .nutrients import NUTRIENT_KEYS

# The same constants and pieces as app/log.py's entry version (imported lazily there: app/log.py imports the food routes, which
# import this module).
_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_FNV_MASK = 0xFFFFFFFFFFFFFFFF

IfMatch = Annotated[str | None, Header(description='The row\'s `version`, quoted: "<version>". When it is not the row\'s version '
                                                  "now the answer is 412 and nothing changes.")]


def precondition_failed(what: str) -> dict[int | str, dict[str, Any]]:
    """The 412 of a route's OpenAPI description."""
    return {412: {"description": f"If-Match is not the {what}'s version now: it was changed since the client read it. The body is "
                                 "{detail, current: <the row as stored, with its version>}; nothing was changed."}}


def _version_piece(value: Any) -> str:
    from .log import _version_piece as piece

    return piece(value)


def version_matches(header: str | None, version: str) -> bool:
    from .log import version_matches as matches

    return matches(header, version)

KINDS: tuple[str, ...] = ("food", "entry", "meal", "lab", "symptom", "weight", "reading")

# What a person sees and edits of each kind, in this order (``entry``: :data:`app.log.VERSION_FIELDS` and the nutrients).
FIELDS: dict[str, tuple[str, ...]] = {
    "food": ("name", "brand", "category", "serving_desc", "serving_g", "gtin", "kidney_notes", "ingredients_text", "hidden", "flags"),
    "meal": ("name", "note", "meal_hint", "servings_made", "source_url", "steps", "items"),
    "lab": ("analyte", "entered_value", "entered_unit", "taken_on", "note"),
    "symptom": ("date", "symptom", "label", "severity", "note"),
    "weight": ("date", "time", "kg", "context", "note"),
    "reading": ("date", "time", "systolic", "diastolic", "pulse", "context", "note"),
}
ITEM_FIELDS: tuple[str, ...] = ("food_name", "servings")  # a saved meal's item: the food's name (ids differ between servers)

WHAT: dict[str, str] = {"food": "food", "entry": "entry", "meal": "saved meal", "lab": "lab result", "symptom": "symptom",
                        "weight": "weight", "reading": "blood pressure reading"}


def _piece(value: Any) -> str:
    """:func:`app.log._version_piece`, with ``true``/``false`` as the numbers 1 and 0 and a list as its length then its elements."""
    if isinstance(value, bool):
        return _version_piece(1 if value else 0)
    if isinstance(value, (list, tuple)):
        return _version_piece(len(value)) + "".join(_piece(v) for v in value)
    return _version_piece(value)


def _text_value(value: Any) -> Any:
    """An empty note and a missing one are the same to the person (the API shows ``""`` for both)."""
    return "" if value is None else value


def canonical_text(kind: str, row: Mapping[str, Any]) -> str:
    """The text a version hashes (not for an ``entry``, whose text is :func:`app.log.entry_version`'s)."""
    text = _piece(kind)
    for name in FIELDS[kind]:
        value = row.get(name)
        if name == "note" and kind in ("lab", "symptom", "weight", "reading"):
            value = _text_value(value)
        elif name == "label":
            value = _text_value(value)
        elif name == "flags":
            value = sorted(str(f) for f in (value or []))
        elif name == "steps":
            value = [str(s) for s in (value or [])]
        elif name == "items":
            value = [[item.get(f) for f in ITEM_FIELDS] for item in (value or [])]
        text += _piece(value)
    if kind == "food":
        nutrients = row.get("nutrients") or {}
        text += "".join(_version_piece(nutrients.get(key)) for key in NUTRIENT_KEYS)
    return text


def _fnv(text: str) -> str:
    digest = _FNV_OFFSET
    for byte in text.encode("utf-8"):
        digest = ((digest ^ byte) * _FNV_PRIME) & _FNV_MASK
    return f"{digest:016x}"


def row_version(kind: str, row: Mapping[str, Any]) -> str:
    """The version of a row of ``kind`` (16 hex digits)."""
    if kind == "entry":
        from .log import entry_version

        return entry_version(row)
    if kind not in FIELDS:
        raise ValueError(f"unknown kind {kind!r}")
    return _fnv(canonical_text(kind, row))


def with_version(kind: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {**row, "version": row_version(kind, row)}


def conflict(kind: str, row: Mapping[str, Any]) -> ApiProblem:
    """412: the row changed since the client read it. ``current`` is the row as stored now, with its version."""
    return ApiProblem(412, f"This {WHAT[kind]} was changed on another device", current=with_version(kind, row))


def check_if_match(kind: str, if_match: str | None, load: Callable[[], Mapping[str, Any]]) -> None:
    """Raise :func:`conflict` when ``if_match`` is given and is not the row's version now (call it after the 404 check, inside the
    write's transaction, so another person's row is a 404 whatever the header says and the check and the write see the same row)."""
    if if_match is None:
        return
    row = load()
    if not version_matches(if_match, row_version(kind, row)):
        raise conflict(kind, row)


__all__ = ["FIELDS", "ITEM_FIELDS", "IfMatch", "KINDS", "canonical_text", "check_if_match", "conflict", "precondition_failed",
           "row_version", "version_matches", "with_version"]
