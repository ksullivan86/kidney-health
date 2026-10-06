"""Additives that matter for a kidney diet: E-number tiers and an ingredient-list scan (note 03 R5, F2).

Pure functions, no I/O. :func:`scan` turns a product's additive tags (Open Food Facts
``additives_tags`` such as ``en:e451i``), its ingredient list and its name into flags:

* ``phosphate_additive``: a phosphate salt used at percent levels (E338–E343, E450–E452, E541,
  E542, or a "phosphate" / "phosphoric" / "fosfato" word). Additive phosphorus is about 90–100 %
  absorbed, so the phosphorus warning is ``high`` whatever the number says (ARCHITECTURE.md
  "Per-serving thresholds").
* ``potassium_additive``: a potassium salt used at percent levels (salt replacers, curing brines,
  phosphate blends: E508 potassium chloride, E326 lactate, E332 citrates, …). Products listing one
  measured 750–1,100 mg potassium per 100 g (Parpia et al., J Ren Nutr 2018;28:83) and additive
  potassium is about 90 % absorbed (KDIGO 2024 Figure 33, from Picard 2021). See
  ``app/nutrients.py`` for the warning it gives (ARCHITECTURE.md v0.3 item 9).
* ``avoid_ckd``: the product **is** a salt substitute (potassium chloride is its first ingredient,
  or its name says so).

Trace uses (preservatives, sweeteners, flavour enhancers at parts per million, starch phosphates)
give a note only, never a flag. A missing additive is not proof of absence: 8 of 25 enhanced meat
products in Sherman & Mehta 2009 (CJASN 4:1370) did not list theirs.

Every piece of text is cleaned with :func:`app.textclean.clean_text` first (note 03 §9 B3), so a
zero-width space or soft hyphen inside "phos​phate" cannot hide the word from the scan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from .textclean import clean_label, clean_text

# --------------------------------------------------------------------------- #
# E-number tiers (note 03 R5). Codes are lower-case, without the "en:" prefix.
# --------------------------------------------------------------------------- #

PHOSPHATE: frozenset[str] = frozenset({"e338", "e339", "e340", "e341", "e343", "e450", "e451", "e452", "e541", "e542"})
PHOSPHATE_TRACE: frozenset[str] = frozenset({"e1410", "e1412", "e1413", "e1414", "e1442", "e442"})
POTASSIUM_BULK: frozenset[str] = frozenset({
    "e326", "e332", "e261", "e508", "e501", "e340", "e351", "e336", "e337", "e357",
    "e577", "e622", "e525", "e515", "e402", "e283", "e450v", "e451ii", "e452ii",
})
POTASSIUM_TRACE: frozenset[str] = frozenset({
    "e202", "e212", "e224", "e228", "e249", "e252", "e536", "e555", "e522", "e628",
    "e632", "e950", "e954iv",
})

# Names for the notes ("Contains potassium lactate (E326), a potassium additive").
E_NAMES: dict[str, str] = {
    "e338": "phosphoric acid", "e339": "sodium phosphates", "e340": "potassium phosphates",
    "e341": "calcium phosphates", "e343": "magnesium phosphates", "e450": "diphosphates",
    "e450v": "tetrapotassium diphosphate", "e451": "triphosphates", "e451ii": "pentapotassium triphosphate",
    "e452": "polyphosphates", "e452ii": "potassium polyphosphate", "e541": "sodium aluminium phosphate",
    "e542": "bone phosphate",
    "e1410": "monostarch phosphate", "e1412": "distarch phosphate", "e1413": "phosphated distarch phosphate",
    "e1414": "acetylated distarch phosphate", "e1442": "hydroxypropyl distarch phosphate",
    "e442": "ammonium phosphatides",
    "e326": "potassium lactate", "e332": "potassium citrates", "e261": "potassium acetates",
    "e508": "potassium chloride", "e501": "potassium carbonates", "e351": "potassium malate",
    "e336": "potassium tartrates (cream of tartar)", "e337": "sodium potassium tartrate",
    "e357": "potassium adipate", "e577": "potassium gluconate", "e622": "monopotassium glutamate",
    "e525": "potassium hydroxide", "e515": "potassium sulphates", "e402": "potassium alginate",
    "e283": "potassium propionate",
    "e202": "potassium sorbate", "e212": "potassium benzoate", "e224": "potassium metabisulphite",
    "e228": "potassium hydrogen sulphite", "e249": "potassium nitrite", "e252": "potassium nitrate",
    "e536": "potassium ferrocyanide", "e555": "potassium aluminium silicate",
    "e522": "aluminium potassium sulphate", "e628": "dipotassium guanylate", "e632": "dipotassium inosinate",
    "e950": "acesulfame K", "e954iv": "potassium saccharin",
}

Kind = Literal["phosphate", "phosphate_trace", "potassium", "potassium_trace"]
FLAG_ORDER: tuple[str, ...] = ("phosphate_additive", "potassium_additive", "avoid_ckd")

# Same wording as the builtin salt-substitute entries in data/foods.json (note 03 R5).
SALT_SUBSTITUTE_NOTE = (
    "AVOID with kidney disease: salt substitutes are potassium chloride and can push blood potassium to "
    "dangerous levels; use herbs, lemon or salt-free herb blends (check they are KCl-free)."
)

MAX_TAGS = 200  # an upstream list longer than this is truncated before scanning
MAX_INGREDIENTS_CHARS = 4000  # note 03 R3: ingredients_text is capped at 4,000 characters
MAX_NAME_CHARS = 200
MAX_ADDITIVES = 40  # entries kept in Food.additives (the reasons a flag was set)
MAX_PHRASE_CHARS = 80


@dataclass(frozen=True)
class Finding:
    """One additive found: its E-code (or ``None`` when only a word matched), a name, its tier."""

    code: str | None
    name: str
    kind: Kind
    source: Literal["tag", "text", "name"]


@dataclass(frozen=True)
class AdditiveResult:
    flags: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    kidney_notes: str | None = None  # set when the product is a salt substitute (avoid_ckd)

    @property
    def additives(self) -> list[str]:
        """Why a flag was set: E-codes (``"e326"``) and, for words without a code, the words."""
        out: list[str] = []
        for f in self.findings:
            if f.kind not in ("phosphate", "potassium"):
                continue
            item = f.code or f.name
            if item not in out:
                out.append(item)
        return out[:MAX_ADDITIVES]

    @property
    def notes(self) -> list[str]:
        """Human-readable notes, flagged additives first ("Contains potassium lactate (E326), a potassium
        additive."). An additive in two tiers (potassium phosphates, E340) gets one note."""
        kinds_by_label: dict[str, list[str]] = {}
        for f in self.findings:
            label = f"{f.name} ({display_code(f.code)})" if f.code else f.name
            kinds = kinds_by_label.setdefault(label, [])
            if f.kind not in kinds:
                kinds.append(f.kind)
        rank = {"potassium": 0, "phosphate": 1, "potassium_trace": 2, "phosphate_trace": 3}
        items = sorted(kinds_by_label.items(), key=lambda item: min(rank[k] for k in item[1]))
        out: list[str] = []
        for label, kinds in items:
            bulk = [k for k in ("potassium", "phosphate") if k in kinds]
            if bulk:
                out.append(f"Contains {label}, a {' and '.join(bulk)} additive.")
            elif "potassium_trace" in kinds:
                out.append(f"Contains {label}: a small amount of potassium (no warning).")
            else:
                out.append(f"Contains {label}: a small amount of phosphate (no warning).")
        return out


def display_code(code: str) -> str:
    """``e451ii`` → ``E451ii``."""
    return "E" + code[1:]


# --------------------------------------------------------------------------- #
# Codes from tags and from text
# --------------------------------------------------------------------------- #

_TAG = re.compile(r"^(?:[a-z]{2,3}:)?(e\d{3,4})([a-z]{0,4})$")


def split_code(code: str) -> tuple[str, str] | None:
    """``"e451i"`` → ``("e451", "e451i")`` (base, full); ``None`` for anything that is not an E-code."""
    m = _TAG.match(code.strip().lower())
    if not m:
        return None
    return m.group(1), m.group(1) + m.group(2)


def classify_code(code: str) -> list[Kind]:
    """The tiers an E-code belongs to. A tag matches its base code (``e451i`` → ``e451``), except the
    potassium sub-codes listed explicitly (``e450v``, ``e451ii``, ``e452ii``, ``e954iv``)."""
    parts = split_code(code)
    if parts is None:
        return []
    base, full = parts
    kinds: list[Kind] = []
    if base in PHOSPHATE or full in PHOSPHATE:
        kinds.append("phosphate")
    elif base in PHOSPHATE_TRACE:
        kinds.append("phosphate_trace")
    if full in POTASSIUM_BULK or base in POTASSIUM_BULK:
        kinds.append("potassium")
    elif full in POTASSIUM_TRACE or base in POTASSIUM_TRACE:
        kinds.append("potassium_trace")
    return kinds


def _code_name(base: str, full: str) -> str:
    return E_NAMES.get(full) or E_NAMES.get(base) or display_code(full)


# "E 450 (i)", "e451i", "E-340 ii", "E1442". The sub-code must be a roman numeral or a single letter a-f
# standing on its own, so "E330 and" does not read "and" as a sub-code.
_TEXT_E = re.compile(
    r"(?<![a-z0-9])e[\s\-]?(\d{3,4})(?:\s*\(?\s*(iii|ii|iv|ix|vii|vi|v|i|[a-f])\s*\)?)?(?![a-z0-9])"
)

# Phosphate words (note 03 R5), minus phospholipids and phosphatides (lecithin), plus the trace
# starch phosphates and vitamin phosphates that are removed before the scan.
_PHOSPHATE_WORD = re.compile(r"(?:phosph|fosf)(?:at|or|it|aat)")  # + Dutch/Finnish "fosfaat"
_PHOSPHATE_EXCLUDED = ("phosphatid", "phospholip", "fosfolip", "fosfatid")
_PHOSPHATE_TRACE_PHRASES = re.compile(
    r"(?:(?:hydroxypropyl(?:ated)?|acetylated|phosphated)\s+)*(?:di|mono)?[\s\-]?starch\s+phosphates?"
    r"|riboflavin(?:e)?[\s\-]*(?:5['’]?[\s\-]*)?(?:sodium\s+)?(?:phosphate|fosfato|phosphat)"
    r"|(?:magnesium\s+|sodium\s+)?ascorbyl\s+(?:phosphate|fosfato|phosphat)"
)

_K = r"(?:mono|di|tri|tetra|penta)?(?:potassium|kalium|potasio|potassio|potássio)"
_JOINERS = r"(?:\s+(?:sodium|hydrogen|dihydrogen|acid|di|mono|tri))*"
_BULK_STEMS = (  # English, German, Dutch spellings ("lactate", "Laktat", "lactaat")
    r"(?:chlorid|la[ck]ta{1,2}t|citra{1,2}t|(?:di)?aceta{1,2}t|(?:bi)?carbona{1,2}t|hydrogen\s*carbona{1,2}t"
    r"|(?:tripoly|poly|pyro|hexameta|meta|di|tri)?(?:phosph|fosf)a{1,2}t|mala{1,2}t|(?:bi)?tartra{1,2}t|glucona{1,2}t"
    r"|glutama{1,2}t|hydroxid|sulfa{1,2}t|sulpha{1,2}t|alginaa?t|propiona{1,2}t|adipa{1,2}t)"
)
_TRACE_STEMS = (
    r"(?:sorba{1,2}t|benzoa{1,2}t|metabisulf|metabisulph|bisulf|bisulph|sulfi|sulphi|nitri|nitra{1,2}t|iodid|iodat"
    r"|jodid|joda{1,2}t|ferrocyan|silica|guanyla|inosina|saccharin)"
)
# English and German/Dutch order: "potassium lactate", "dipotassium phosphate", "kaliumchlorid".
_K_BULK = re.compile(rf"(?<![a-z])({_K}{_JOINERS}[\s\-]*{_BULK_STEMS})[a-z]*")
_K_TRACE = re.compile(rf"(?<![a-z])({_K}{_JOINERS}[\s\-]*(?:aluminium\s+|aluminum\s+)?{_TRACE_STEMS})[a-z]*")
# French, Spanish, Italian and Portuguese order: "chlorure de potassium", "cloruro di potassio".
_ANION_FIRST_BULK = re.compile(
    r"(?<![a-z])((?:chlor|clor|lact|latt|citr|acet|acét|bicarbon|carbon|pyrophosph|pirofosf|polyphosph|polifosf"
    rf"|phosph|fosf|malat|tartr|glucon|glutam|hydrox|idross|hidróx|hidrox|sulfat|sulphat|solfat|algin|propion|adip)[a-zà-ÿ]*"
    rf"\s+(?:de|di|du|d['’]|of)\s*{_K})(?![a-z])"
)
_ANION_FIRST_TRACE = re.compile(
    r"(?<![a-z])((?:sorb|benzo|metabisulf|metabisolf|nitrit|nitrat|iodur|iodat|iodid|ferrocian|ferrocyan|sulfit|solfit"
    rf"|silic|guanil|guanyl|inosin)[a-zà-ÿ]*\s+(?:de|di|du|d['’]|of)\s*{_K})(?![a-z])"
)
_ALUMINIUM_BEFORE = re.compile(r"(?:aluminium|aluminum)\s*$")
_OTHER_BULK = re.compile(r"(?<![a-z])(cream of tartar|salt substitute)(?![a-z])")
_ACESULFAME = re.compile(r"(?<![a-z])(acesulfam(?:e)?(?:[\s\-]*(?:k|potassium))?)(?![a-z])")

# Potassium chloride as an ingredient name (any of the supported languages) or its E-number.
_KCL = re.compile(
    rf"^(?:{_K}[\s\-]*chlorid\w*|(?:chlorure|cloruro|cloreto)\s+(?:de|di)\s*{_K}|e[\s\-]?508|kcl)(?![a-z])"
)
# Product names that are salt substitutes (note 03 R5, plus LoSalt, the UK brand). "No salt added"
# is deliberately not matched: only the brand spellings NoSalt / No-Salt.
_SALT_SUBSTITUTE_NAME = re.compile(
    r"(?<![a-z])(?:salt\s+substitute|salt\s+replacer|lite\s+salt|no-?salt(?![\s\-]+added)|nu[\s\-]?salt|half\s+salt|lo-?salt)(?![a-z])"
)
_INGREDIENTS_PREFIX = re.compile(r"^\s*(?:ingredients?|ingrédients|ingredientes|ingredienti|zutaten|ingrediënten)\s*:\s*")
_CATIONS = re.compile(
    r"(?:(?:mono|di|tri|tetra|penta)?(?:sodium|potassium|calcium|magnesium|ammonium|aluminium|aluminum|ferric|zinc)"
    r"(?:\s+(?:aluminium|aluminum|acid))?)\s*$"
)


def _first_ingredient(text: str) -> str:
    """The first top-level item of an ingredient list (commas or semicolons outside brackets)."""
    text = _INGREDIENTS_PREFIX.sub("", text)
    depth = 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch in ",;\n" and depth == 0:
            return text[:i].strip(" .*_")
    return text.strip(" .*_")


def _phrase(text: str) -> str:
    return " ".join(text.split())[:MAX_PHRASE_CHARS]


def _scan_text(text: str) -> list[Finding]:
    found: list[Finding] = []

    def add(code: str | None, name: str, kind: Kind) -> None:
        found.append(Finding(code, _phrase(name), kind, "text"))

    # 1. E-numbers written in the list.
    for m in _TEXT_E.finditer(text):
        code = "e" + m.group(1) + (m.group(2) or "")
        parts = split_code(code)
        if parts is None:
            continue
        base, full = parts
        for kind in classify_code(code):
            add(full if (full in E_NAMES or base not in E_NAMES) else base, _code_name(base, full), kind)

    # 2. Trace phosphates by name (starch and vitamin phosphates), then blank them so step 3
    #    does not read their "phosphate" as a bulk additive.
    def trace(m: re.Match[str]) -> str:
        add(None, m.group(0), "phosphate_trace")
        return " " * len(m.group(0))

    remaining = _PHOSPHATE_TRACE_PHRASES.sub(trace, text)

    # 3. Phosphate words, except phospholipids and phosphatides.
    for m in _PHOSPHATE_WORD.finditer(remaining):
        start = m.start()
        while start > 0 and remaining[start - 1].isalpha():
            start -= 1  # the whole word ("tripolyphosphate", "fosfato")
        word_end = m.end()
        while word_end < len(remaining) and remaining[word_end].isalpha():
            word_end += 1
        word = remaining[start:word_end]
        if any(ex in word for ex in _PHOSPHATE_EXCLUDED):
            continue
        cation = _CATIONS.search(remaining[max(0, start - 40):start])
        add(None, (cation.group(0).strip() + " " + word) if cation else word, "phosphate")

    # 4. Potassium salts. Aluminium potassium sulphate (E522) is a trace use, not a sulphate salt.
    for m in _K_BULK.finditer(remaining):
        if _ALUMINIUM_BEFORE.search(remaining[: m.start()]):
            add("e522", E_NAMES["e522"], "potassium_trace")
        else:
            add(None, m.group(0), "potassium")
    for m in _ANION_FIRST_BULK.finditer(remaining):
        add(None, m.group(1), "potassium")
    for m in _OTHER_BULK.finditer(remaining):
        add("e336" if m.group(1) == "cream of tartar" else None, m.group(1), "potassium")
    for m in _K_TRACE.finditer(remaining):
        add(None, m.group(0), "potassium_trace")
    for m in _ANION_FIRST_TRACE.finditer(remaining):
        add(None, m.group(1), "potassium_trace")
    for m in _ACESULFAME.finditer(remaining):
        add("e950", "acesulfame K", "potassium_trace")
    return found


def _clean_tags(tags: Iterable[object] | None) -> list[str]:
    out: list[str] = []
    for tag in list(tags or [])[:MAX_TAGS]:
        cleaned = clean_label(tag, max_len=40)
        if cleaned:
            out.append(cleaned.casefold())
    return out


def scan(additives_tags: Iterable[object] | None, ingredients_text: object, name: object) -> AdditiveResult:
    """Flags (``phosphate_additive``, ``potassium_additive``, ``avoid_ckd``), the additives found and
    the notes, from additive tags, an ingredient list (any language the patterns know) and a name.

    Inputs are untrusted: non-strings are ignored, text is cleaned (NFKC, invisible and control
    characters removed) and capped before it is scanned.
    """
    findings: list[Finding] = []
    for tag in _clean_tags(additives_tags):
        parts = split_code(tag)
        if parts is None:
            continue
        base, full = parts
        for kind in classify_code(full):
            code = full if (full in E_NAMES or base not in E_NAMES) else base
            findings.append(Finding(code, _code_name(base, full), kind, "tag"))

    text = clean_text(ingredients_text, max_len=MAX_INGREDIENTS_CHARS, keep_newlines=True)
    lowered = text.casefold() if text else ""
    if lowered:
        findings.extend(_scan_text(lowered))

    product = (clean_label(name, max_len=MAX_NAME_CHARS) or "").casefold()
    salt_substitute = bool(product and _SALT_SUBSTITUTE_NAME.search(product))
    if lowered and _KCL.match(_first_ingredient(lowered)):
        salt_substitute = True
    if salt_substitute and not any(f.kind == "potassium" for f in findings):
        findings.append(Finding("e508", "potassium chloride (a salt substitute)", "potassium", "name"))

    # One finding per (code or name, kind): a tag and the same E-number in the text are one additive.
    unique: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for f in findings:
        key = (f.code or f.name, f.kind)
        if key not in seen:
            seen.add(key)
            unique.append(f)

    flags: list[str] = []
    if any(f.kind == "phosphate" for f in unique):
        flags.append("phosphate_additive")
    if any(f.kind == "potassium" for f in unique):
        flags.append("potassium_additive")
    if salt_substitute:
        flags.append("avoid_ckd")
    return AdditiveResult(
        flags=tuple(flags),
        findings=tuple(unique),
        kidney_notes=SALT_SUBSTITUTE_NOTE if salt_substitute else None,
    )
