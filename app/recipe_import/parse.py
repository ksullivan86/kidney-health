"""Reading a recipe: schema.org ``Recipe`` data, ingredient lines, search words and amounts (design note 30 §3). Pure.

* :func:`ld_json_blocks`: the ``<script type="application/ld+json">`` blocks of a page, read with the standard library's
  ``html.parser`` (nothing on the page runs). Server only: the demo has no page to read.
* :func:`find_recipe`: the first ``Recipe`` in those blocks (a plain object, an array, an ``@graph`` or a ``mainEntity``).
* :func:`recipe_from_jsonld`: its name, the servings it makes, its steps (within the saved-meal limits) and its ingredient lines.
  The page's own ``nutrition`` is ignored (it rarely lists potassium or phosphorus).
* :func:`parse_line`: one ingredient line → amount, unit, food words and the note after a comma.
* :func:`search_terms`: the food words → the searches to try, best first.
* :func:`recipe_servings`: an amount and unit → servings of one food, only where the food's serving allows it; else ``None``.
* :func:`lines_of_text`: pasted ingredients → lines (headings such as "For the sauce:" left out).

Every function but :func:`ld_json_blocks` has a JavaScript twin, ``app/static/js/engine/recipe_import.js``, pinned by
``tests/data/recipe_import_vectors.json`` (``tests/data/gen_recipe_import_vectors.py``).
"""
from __future__ import annotations

import html
import json
import math
import re
from html.parser import HTMLParser
from typing import Any

MAX_LINES = 60  # ingredient lines read from a page or a paste
MAX_LINE_CHARS = 300
MAX_NAME_CHARS = 200  # a saved meal's name (app/models.py)
MAX_STEPS = 20  # the saved-meal limits (app/models.py MAX_RECIPE_STEPS, MAX_RECIPE_STEP_CHARS)
MAX_STEP_CHARS = 500
MAX_TEXT_CHARS = 4000  # one text value read from the page, before cleaning
MAX_DEPTH = 6
MAX_SERVINGS_MADE = 100
MAX_BLOCKS = 20
MAX_BLOCK_CHARS = 1_048_576

# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #

_TAG = re.compile(r"<[^<>]*>")  # [^<>] keeps it linear on text full of "<"
_SPACE = re.compile(r"\s+")
_SPACE_BEFORE_MARK = re.compile(r" ([.,;:!?)])")
_CONTROL = re.compile(r"[\u0000-\u001f\u007f-\u009f]")


def text_of(value: Any) -> str:
    """Plain text of a page value: tags and entities removed, spaces collapsed. Not a string → empty."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = str(value)[:MAX_TEXT_CHARS]
    text = html.unescape(_TAG.sub(" ", text))
    text = _CONTROL.sub(" ", text)
    return _SPACE_BEFORE_MARK.sub(r"\1", _SPACE.sub(" ", text)).strip()


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #


class _LdJson(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._buf: list[str] | None = None
        self._size = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script" or len(self.blocks) >= MAX_BLOCKS:
            return
        kind = next((v or "" for k, v in attrs if k == "type"), "")
        if kind.split(";", 1)[0].strip().lower() == "application/ld+json":
            self._buf, self._size = [], 0

    def handle_data(self, data: str) -> None:
        if self._buf is not None and self._size <= MAX_BLOCK_CHARS:
            self._buf.append(data)
            self._size += len(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._buf is not None:
            if self._size <= MAX_BLOCK_CHARS:
                self.blocks.append("".join(self._buf))
            self._buf = None


def ld_json_blocks(page: str) -> list[Any]:
    """The JSON values of the page's ``application/ld+json`` scripts; a block that is not JSON is skipped."""
    parser = _LdJson()
    try:
        parser.feed(page)
        parser.close()
    except Exception:  # html.parser is lenient; anything it still refuses means no recipe
        pass
    out: list[Any] = []
    for block in parser.blocks:
        try:
            out.append(json.loads(block.strip()))
        except (ValueError, RecursionError):
            continue
    return out


def is_recipe(node: Any) -> bool:
    kind = node.get("@type") if isinstance(node, dict) else None
    kinds = kind if isinstance(kind, list) else [kind]
    return any(isinstance(k, str) and k.rsplit("/", 1)[-1].rsplit(":", 1)[-1] == "Recipe" for k in kinds)


def find_recipe(node: Any, depth: int = 0) -> dict[str, Any] | None:
    """The first ``Recipe`` object in ``node`` (depth-first: the object, its ``@graph``, its ``mainEntity``, list items)."""
    if depth > MAX_DEPTH:
        return None
    if isinstance(node, list):
        for item in node[:200]:
            found = find_recipe(item, depth + 1)
            if found is not None:
                return found
        return None
    if not isinstance(node, dict):
        return None
    if is_recipe(node):
        return node
    for key in ("@graph", "mainEntity"):
        if key in node:
            found = find_recipe(node[key], depth + 1)
            if found is not None:
                return found
    return None


_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def yield_of(value: Any) -> float | None:
    """How many servings: the first number in ``recipeYield`` ("4 servings", ["4", "4 servings"], 6), 0 < n <= 100."""
    if isinstance(value, list):
        for item in value[:10]:
            got = yield_of(item)
            if got is not None:
                return got
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = _NUMBER.search(value[:200])
        if not match:
            return None
        number = float(match.group(0))
    else:
        return None
    if not math.isfinite(number) or not 0 < number <= MAX_SERVINGS_MADE:
        return None
    return number


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_step(text: str) -> list[str]:
    """A step of at most :data:`MAX_STEP_CHARS`, or several: split at sentence ends, a sentence that is still too long at a space."""
    if len(text) <= MAX_STEP_CHARS:
        return [text]
    out: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > MAX_STEP_CHARS:
            cut = sentence.rfind(" ", 0, MAX_STEP_CHARS + 1)
            cut = cut if cut > 0 else MAX_STEP_CHARS
            if current:
                out.append(current)
                current = ""
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) <= MAX_STEP_CHARS:
            current = f"{current} {sentence}"
        else:
            if current:
                out.append(current)
            current = sentence
    if current:
        out.append(current)
    return [s for s in out if s]


def _step_texts(node: Any, depth: int, out: list[str]) -> None:
    if depth > MAX_DEPTH or len(out) > 200:
        return
    if isinstance(node, str):
        for part in node.split("\n"):
            text = text_of(part)
            if text:
                out.append(text)
        return
    if isinstance(node, list):
        for item in node[:200]:
            _step_texts(item, depth + 1, out)
        return
    if not isinstance(node, dict):
        return
    if "itemListElement" in node:  # HowToSection (or an ItemList of steps)
        _step_texts(node["itemListElement"], depth + 1, out)
        return
    text = text_of(node.get("text")) or text_of(node.get("name"))
    if text:
        out.append(text)


def steps_of(value: Any) -> tuple[list[str], bool]:
    """``(steps, cut)``: the instructions as at most 20 steps of at most 500 characters; ``cut`` when some were left out."""
    texts: list[str] = []
    _step_texts(value, 0, texts)
    steps: list[str] = []
    for text in texts:
        steps.extend(split_step(text))
    return steps[:MAX_STEPS], len(steps) > MAX_STEPS


def ingredient_lines(value: Any) -> tuple[list[str], bool]:
    """``(lines, cut)``: the ingredient lines as plain text, at most :data:`MAX_LINES` of :data:`MAX_LINE_CHARS`."""
    items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    lines: list[str] = []
    for item in items[:500]:
        text = text_of(item)
        if text:
            lines.append(text[:MAX_LINE_CHARS])
    return lines[:MAX_LINES], len(lines) > MAX_LINES


def is_heading(line: str) -> bool:
    """"For the sauce:" is a heading, not an ingredient."""
    return line.endswith(":") and not any(ch in "0123456789" for ch in line)


def lines_of_text(text: str) -> tuple[list[str], bool]:
    """``(lines, cut)``: pasted ingredients, one a line; empty lines and headings left out; at most :data:`MAX_LINES`."""
    lines = [normalise_line(raw)[:MAX_LINE_CHARS] for raw in (text or "").split("\n")]
    lines = [line for line in lines if line and not is_heading(line)]
    return lines[:MAX_LINES], len(lines) > MAX_LINES


def recipe_from_jsonld(recipe: dict[str, Any]) -> dict[str, Any]:
    """What the app keeps of a schema.org ``Recipe``: name, servings made, steps and ingredient lines."""
    name = text_of(recipe.get("name"))[:MAX_NAME_CHARS].strip() or None
    raw_lines = recipe.get("recipeIngredient")
    if raw_lines is None:
        raw_lines = recipe.get("ingredients")
    lines, lines_cut = ingredient_lines(raw_lines)
    steps, steps_cut = steps_of(recipe.get("recipeInstructions"))
    return {"name": name, "servings_made": yield_of(recipe.get("recipeYield")), "steps": steps, "steps_cut": steps_cut,
            "lines": lines, "lines_cut": lines_cut}


# --------------------------------------------------------------------------- #
# Ingredient lines
# --------------------------------------------------------------------------- #

FRACTION_CHARS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5",
                  "⅙": "1/6", "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}
_FRACTION_RE = re.compile(r"([0-9]?)([" + "".join(FRACTION_CHARS) + r"])")
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "eleven": 11, "twelve": 12, "half": 0.5}
ARTICLE_WORDS = ("a", "an")  # "a pinch": 1, only before a unit
# Canonical unit → the words that name it (longest first when matching).
UNITS: dict[str, tuple[str, ...]] = {
    "fl_oz": ("fluid ounces", "fluid ounce", "fl. oz", "fl oz", "floz"),
    "g": ("grams", "gram", "gms", "gm", "gr", "g"),
    "kg": ("kilograms", "kilogram", "kgs", "kg"),
    "oz": ("ounces", "ounce", "oz"),
    "lb": ("pounds", "pound", "lbs", "lb"),
    "ml": ("millilitres", "milliliters", "millilitre", "milliliter", "mls", "ml"),
    "l": ("litres", "liters", "litre", "liter", "l"),
    "cup": ("cups", "cup", "c"),
    "tbsp": ("tablespoons", "tablespoon", "tbsps", "tbsp", "tbs", "tbl"),
    "tsp": ("teaspoons", "teaspoon", "tsps", "tsp"),
    "pinch": ("pinches", "pinch"),
    "dash": ("dashes", "dash"),
    "clove": ("cloves", "clove"),
    "slice": ("slices", "slice"),
    "piece": ("pieces", "piece"),
    "can": ("cans", "can", "tins", "tin"),
}
_UNIT_WORDS = sorted(((w, u) for u, ws in UNITS.items() for w in ws), key=lambda p: (-len(p[0]), p[0]))
CONTAINERS = ("cans", "can", "tins", "tin", "packages", "package", "pkgs", "pkg", "jars", "jar", "bags", "bag", "boxes", "box",
              "cartons", "carton", "bottles", "bottle", "packets", "packet", "containers", "container")
MASS_G = {"g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237}
VOLUME_ML = {"ml": 1.0, "l": 1000.0, "cup": 236.5882365, "tbsp": 14.78676478125, "tsp": 4.92892159375, "fl_oz": 29.5735295625}
COUNT_UNITS = ("piece", "slice", "clove", "can")

_NUM = r"[0-9]{1,3}(?:,[0-9]{3})+(?![0-9])|[0-9]+(?:\.[0-9]+|,[0-9]{1,2}(?![0-9]))?"  # "1,000", "1.5", "1,5"
_THOUSANDS = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+")
_QTY = re.compile(r"(?:([0-9]+)\s+([0-9]+)\s*/\s*([0-9]+)|([0-9]+)\s*/\s*([0-9]+)|(" + _NUM + r"))")
_RANGE_WORDS = ("-", "–", "—", "to", "or")
_LETTERS = re.compile(r"[A-Za-z]+")
_PARENS = re.compile(r"\([^()]*\)")  # [^()] keeps it linear on text full of "("


def _range_end(rest: str) -> int | None:
    """Where the second number of a range starts ("2 to 3", "2-3"), or ``None``. Written without a regex so a line full of
    spaces cannot make it slow."""
    s = rest.lstrip()
    start = len(rest) - len(s)
    for sep in _RANGE_WORDS:
        if s.startswith(sep):
            after = s[len(sep):]
            tail = after.lstrip()
            if tail[:1] in "0123456789" and tail[:1]:
                return start + len(sep) + len(after) - len(tail)
    return None


def _leading_word(text: str) -> tuple[str, int] | None:
    """``(word, end)`` for ASCII letters at the start of ``text`` followed by a word break, ``end`` past the spaces after it."""
    match = _LETTERS.match(text)
    if match is None:
        return None
    end = match.end()
    if end < len(text) and (text[end].isalnum() or text[end] == "_"):
        return None  # no word break after the letters
    after = text[end:]
    return match.group(0), end + len(after) - len(after.lstrip())
_BULLET = re.compile(r"^[\s\-*•▢□☐·]+")


def normalise_line(raw: str) -> str:
    """A line with its bullet gone, fractions as ``1/2`` (``1½`` → ``1 1/2``), the fraction slash as ``/``, spaces collapsed."""
    text = _SPACE.sub(" ", _CONTROL.sub(" ", raw or "")).strip()
    text = _BULLET.sub("", text)
    text = _FRACTION_RE.sub(lambda m: (m.group(1) + " " if m.group(1) else "") + FRACTION_CHARS[m.group(2)], text)
    return _SPACE.sub(" ", text.replace("⁄", "/")).strip()


def _number(match: re.Match[str]) -> float | None:
    if match.group(1) is not None:
        den = int(match.group(3))
        return int(match.group(1)) + int(match.group(2)) / den if den else None
    if match.group(4) is not None:
        den = int(match.group(5))
        return int(match.group(4)) / den if den else None
    raw = match.group(6)
    return float(raw.replace(",", "") if _THOUSANDS.fullmatch(raw) else raw.replace(",", "."))


def take_quantity(text: str) -> tuple[float | None, str]:
    """``(number, rest)`` for a number at the start of ``text`` (a range keeps its first number); ``(None, text)`` otherwise."""
    match = _QTY.match(text)
    if match is None:
        return None, text
    value = _number(match)
    rest = text[match.end():]
    ranged = _range_end(rest)
    if ranged is not None:
        second = _QTY.match(rest[ranged:])
        if second is not None:
            rest = rest[ranged + second.end():]
    return value, rest.lstrip()


def take_unit(text: str) -> tuple[str | None, str]:
    """``(unit, rest)`` for a unit word at the start of ``text`` (an optional full stop and "of" after it)."""
    low = text.lower()
    for word, unit in _UNIT_WORDS:
        if low.startswith(word):
            after = low[len(word):]
            if after.startswith("."):
                after = after[1:]
            if after == "" or after[0] in " ,;)/":
                rest = text[len(text) - len(after):].lstrip()
                if rest.lower().startswith("of "):
                    rest = rest[3:].lstrip()
                return unit, rest
    return None, text


def _word_number(text: str) -> tuple[float | None, str, bool]:
    found = _leading_word(text)
    if found is None:
        return None, text, False
    word, end = found[0].lower(), found[1]
    if word in NUMBER_WORDS:
        return float(NUMBER_WORDS[word]), text[end:], False
    if word in ARTICLE_WORDS:
        return 1.0, text[end:], True
    return None, text, False


def _package(text: str) -> tuple[float, str, str] | None:
    """``(size, unit, rest)`` for a package size before a container: ``(14.5 oz) can …`` or ``15-ounce cans …``."""
    match = _PARENS.match(text)
    inner, rest = (match.group(0)[1:-1].strip(), text[match.end():].lstrip()) if match else (text, "")
    size, after = take_quantity(inner)
    if size is None:
        return None
    after = after[1:].lstrip() if after.startswith("-") else after
    unit, after = take_unit(after)
    if unit is None or (unit not in MASS_G and unit not in VOLUME_ML):
        return None
    if match is None:
        rest = after
    elif after.strip():
        return None
    word = _leading_word(rest)
    if word is None or word[0].lower() not in CONTAINERS:
        return None
    return size, unit, rest[word[1]:]


def parse_line(raw: str) -> dict[str, Any]:
    """One ingredient line → ``{text, amount, unit, food_text, note}``. ``amount`` is ``None`` when the line has no number."""
    text = normalise_line(raw)[:MAX_LINE_CHARS]
    amount, rest = take_quantity(text)
    article = False
    if amount is None:
        amount, rest, article = _word_number(text)
    unit: str | None = None
    if amount is not None:
        package = _package(rest)
        if package is not None:
            size, unit, rest = package
            amount = amount * size
        else:
            unit, rest = take_unit(rest)
            if unit is None and article:  # "a few sprigs": not a number after all
                amount, rest = None, text
            elif unit is not None and rest.startswith("/"):  # "350 g/12 oz flour": the second measure says the same
                other, after = take_quantity(rest[1:].lstrip())
                other_unit, after = take_unit(after) if other is not None else (None, after)
                if other_unit is not None:
                    rest = after
    else:
        unit, rest = None, text
    head, _, tail = rest.partition(",")
    food = _SPACE.sub(" ", _PARENS.sub(" ", head)).strip(" .;:-")
    note = tail.strip() or None
    if not food and note:
        food, note = note, None
    return {"text": text, "amount": amount, "unit": unit, "food_text": food, "note": note}


# --------------------------------------------------------------------------- #
# Search words
# --------------------------------------------------------------------------- #

DROP_PHRASES = ("to taste", "for serving", "for garnish", "for frying", "as needed", "if desired", "plus more", "at room temperature",
                "or more", "optional", "divided")
STOP_WORDS = frozenset((
    "of", "and", "the", "a", "an", "with", "without", "into", "in", "for", "to", "about", "plus", "more", "taste", "some",
    "fresh", "freshly", "large", "medium", "small", "extra", "big", "chopped", "diced", "minced", "sliced", "grated", "shredded",
    "peeled", "crushed", "finely", "roughly", "coarsely", "thinly", "thickly", "cut", "cubed", "cubes", "pieces", "piece",
    "halved", "quartered", "trimmed", "rinsed", "drained", "packed", "softened", "melted", "beaten", "boneless", "skinless",
    "uncooked", "raw", "organic", "ripe", "clove", "cloves", "sprig", "sprigs", "handful", "pinch", "dash", "heaping", "level",
    "generous", "good", "quality", "can", "cans", "package", "jar", "bunch", "head", "stalk", "stalks", "inch", "inches", "few",
    "dried", "virgin", "lean", "bone", "skin",
))
_WORD = re.compile(r"[a-zà-ÿ]+")


def stem(word: str) -> str:
    """A plural made singular enough for a substring search ("berries" → "berr", "tomatoes" → "tomato", "eggs" → "egg")."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3]
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def search_terms(food_text: str) -> list[str]:
    """The searches to try for an ingredient's food words, best first: all words, the last two, the last one, the first one."""
    text = (food_text or "").lower()
    text = _PARENS.sub(" ", text)
    text = text.split(",", 1)[0].split("/", 1)[0]
    text = re.split(r"\bor\b", text, maxsplit=1)[0]
    for phrase in DROP_PHRASES:
        text = text.replace(phrase, " ")
    words: list[str] = []
    for word in _WORD.findall(text):
        if word in STOP_WORDS or len(word) < 2:
            continue
        word = stem(word)
        if word not in words:
            words.append(word)
    words = words[-5:]
    if not words:
        return []
    out: list[str] = []
    for query in (" ".join(words), " ".join(words[-2:]), words[-1], words[0]):
        if query not in out:
            out.append(query)
    return out


# --------------------------------------------------------------------------- #
# Amounts
# --------------------------------------------------------------------------- #

_SERVING_VOLUME = (("fl oz", "fl_oz"), ("fluid ounce", "fl_oz"), ("cups", "cup"), ("cup", "cup"), ("tablespoon", "tbsp"),
                   ("tbsp", "tbsp"), ("teaspoon", "tsp"), ("tsp", "tsp"), ("ml", "ml"))
_MASS_WORDS = ("oz", "ounce", "g", "gram", "grams", "lb", "pound", "kg")


def serving_quantity(serving_desc: str) -> tuple[float, str] | None:
    """``"1/2 cup (79 g)"`` → ``(0.5, "cup (79 g)")``; None when it does not start with a number."""
    qty, rest = take_quantity(normalise_line(serving_desc or ""))
    if qty is None or qty <= 0:
        return None
    return qty, rest.lower()


def _round2(value: float) -> float:
    return math.floor(value * 100 + 0.5) / 100


def recipe_servings(amount: float | None, unit: str | None, serving_desc: str, serving_g: float | None) -> float | None:
    """Servings of a food for an ingredient's amount and unit, or ``None`` when the food's serving does not allow it (never a
    guess): weight through the gram weight, volume through a volume serving, a count through a count serving."""
    if amount is None or not amount > 0 or not math.isfinite(amount):
        return None
    servings: float | None = None
    if unit in MASS_G:
        grams = float(serving_g or 0)
        if grams > 0:
            servings = amount * MASS_G[unit] / grams
    elif unit in VOLUME_ML:
        quantity = serving_quantity(serving_desc)
        if quantity is not None:
            qty, rest = quantity
            serving_unit = next((u for word, u in _SERVING_VOLUME if rest.startswith(word)), None)
            if serving_unit is not None:
                servings = amount * VOLUME_ML[unit] / (qty * VOLUME_ML[serving_unit])
    elif unit is None or unit in COUNT_UNITS:
        quantity = serving_quantity(serving_desc)
        if quantity is not None:
            qty, rest = quantity
            match = _WORD.match(rest)
            word = match.group(0) if match else ""
            if unit is None:
                fits = bool(word) and word not in _MASS_WORDS and not any(rest.startswith(w) for w, _ in _SERVING_VOLUME)
            else:
                fits = stem(word) == unit
            if fits:
                servings = amount / qty
    if servings is None:
        return None
    rounded = _round2(servings)
    return rounded if 0.01 <= rounded <= 1000 else None
