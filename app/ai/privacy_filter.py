"""The privacy filter (ROADMAP "Privacy tiers", tier 2; design note 31): names, places, dates and other identifiers out of
every request to a **cloud** AI, and back into its reply.

* :class:`Shield` holds one request's labels (``[PERSON_1]``, ``[PLACE_1]``, ``[DATE_1]``, ``[PHONE_1]``, ``[EMAIL_1]``,
  ``[URL_1]``, ``[ID_1]``, ``[ADDRESS_1]``) and the words they stand for. It lives in memory for one call and is then
  dropped: the words are never stored, logged or sent.
* :meth:`Shield.filter_body` replaces identifiers in every text part of a Chat Completions body (system, user and assistant
  messages); :meth:`Shield.restore` puts the words back into the parsed reply.
* :func:`shield_for` is None for a provider pinned to the private network (``cfg.local_only``): requests to the local AI
  are never changed. Every other provider counts as cloud.
* :func:`known_terms` reads the account's own names (user name, display name, e-mail) and its Care team's names.

It is rule-based and uses the standard library only. Every pattern is linear on its input (single character classes,
bounded repeats, no nested or overlapping open-ended quantifiers) and each text part is capped at :data:`MAX_TEXT_CHARS`
before any regex runs: a longer part is refused (:class:`FilterLimit`), never sent unfiltered.

What it keeps: medical content and amounts ("potassium 5.8", "2 cups", "150 mg"), any number with a unit after it, times of
day, relative words (today, yesterday), weekdays, a bare month or year, and numbers inside the app's own compact JSON (right
after ``:``, ``,`` or ``[``), so a data block stays valid JSON. Labels contain only ``[A-Z0-9_]`` and brackets, so a
replacement inside a JSON string keeps it valid.
"""
from __future__ import annotations

import copy
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping

MAX_TEXT_CHARS = 200_000  # one message part; the app's prompts are far below this
MAX_TERMS = 200
MAX_TERM_CHARS = 80
KINDS: tuple[str, ...] = ("PERSON", "PLACE", "ADDRESS", "DATE", "PHONE", "EMAIL", "URL", "ID")


class FilterLimit(ValueError):
    """A text part is longer than :data:`MAX_TEXT_CHARS`: the request is not sent."""


# --------------------------------------------------------------------------- #
# Words that are never names
# --------------------------------------------------------------------------- #

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
                "december")
# Capitalised words that start sentences or name app things, never a person or a place.
STOP_WORDS = frozenset((
    "i", "i'm", "im", "the", "a", "an", "and", "or", "but", "my", "our", "your", "his", "her", "their", "this", "that", "these",
    "those", "it", "its", "we", "you", "he", "she", "they", "is", "was", "am", "are", "be", "been", "not", "no", "yes", "ok", "okay",
    "so", "to", "of", "in", "on", "at", "for", "with", "from", "about", "by", "as", "if", "then", "when", "what", "how", "why", "who",
    "where", "which", "there", "here", "again", "also", "just", "still", "now", "all", "any", "some", "every", "each", "both",
    "today", "tomorrow", "yesterday", "tonight", "morning", "evening", "afternoon", "night", "week", "weekend", "month", "year",
    "breakfast", "lunch", "dinner", "supper", "snack", "snacks", "meal", "meals", "christmas", "easter", "thanksgiving", "ramadan",
    "diwali", "hanukkah", "eid", "new", "ai", "ask", "app", "settings", "plan", "help", "please", "thanks", "thank", "sorry",
    "hello", "hi", "hey", "dear", "dr", "doctor", "mr", "mrs", "ms", "miss", "mx", "prof", "professor", "nurse", "sister", "st",
    "saint", "type", "stage", "ckd", "t1d", "t2d", "egfr", "gfr", "dialysis", "kidney", "kidneys", "renal", "diabetes", "insulin",
    "potassium", "sodium", "phosphorus", "phosphate", "protein", "calcium", "fluid", "glucose", "sugar", "carbs", "low", "high",
    "everyone", "everybody", "someone", "somebody", "nobody", "sure", "great", "good", "bad", "well", "fine", "can", "could",
    "would", "should", "will", "did", "do", "does", "had", "has", "have", "got", "get", "let", "lets", "let's", "admin", "user",
    "test", "demo", "guest", "root", "owner", "family", "home", "me", "patient", "person", "people", "mum", "mom", "dad", "mother",
    "father", "wife", "husband", "son", "daughter", "friend", "partner", "baby", "kids", "children", "team", "care", "carer",
    *_WEEKDAYS, *_MONTH_NAMES,
))
# Brand names that start with a title (kept: they are foods, not people).
KEPT_PHRASES = frozenset(("dr pepper", "dr. pepper", "dr oetker", "dr. oetker", "dr praeger's", "dr. praeger's", "dr mcdougall's",
                          "dr. mcdougall's"))
# Words before "called" or "named" that mean the next words are a food, not a person.
FOOD_BEFORE_CUE = frozenset(("dish", "recipe", "food", "meal", "soup", "drink", "snack", "brand", "product", "sauce", "cereal", "bar",
                             "bread", "cake", "pie", "salad", "stew", "curry", "app", "something", "thing", "tea", "juice", "biscuit",
                             "cookie", "cheese", "spread", "pasta", "noodles", "rice", "candy", "sweet", "dessert", "milk", "shake"))
# Words before "called" or "named" that mean the next words are a place.
PLACE_BEFORE_CUE = frozenset(("restaurant", "cafe", "café", "place", "shop", "store", "town", "city", "village", "street", "road",
                              "hospital", "clinic", "pub", "bar", "diner", "market", "supermarket", "takeaway", "hotel", "centre",
                              "center", "unit", "area", "suburb", "county", "state"))
# Units: a number followed by one of these is an amount and is never touched.
UNITS = frozenset((
    "mg", "g", "gram", "grams", "kg", "kilo", "kilos", "mcg", "µg", "ug", "ml", "millilitre", "milliliter", "millilitres", "milliliters",
    "l", "litre", "liter", "litres", "liters", "dl", "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds", "cup", "cups", "tbsp",
    "tsp", "tablespoon", "tablespoons", "teaspoon", "teaspoons", "kcal", "cal", "calorie", "calories", "kj", "mmol", "mmol/l",
    "mg/dl", "mg/dL", "meq", "iu", "units", "unit", "steps", "step", "servings", "serving", "portion", "portions", "slice", "slices",
    "piece", "pieces", "%", "percent", "bpm", "mmhg", "min", "mins", "minutes", "hours", "hrs", "h", "days", "weeks", "km", "mi",
    "miles", "m", "cm", "mm", "ft", "feet", "in", "inch", "inches", "x", "times", "people",
))

# --------------------------------------------------------------------------- #
# Patterns (each linear on its input; see the module docstring)
# --------------------------------------------------------------------------- #

_NAME = r"(?:[A-Z][a-zA-Z'’\-]{1,30}|[A-Z]\.)"
_NAMES = rf"{_NAME}(?:[ ]{_NAME}){{0,2}}"
_RELATIONS = ("wife|husband|partner|son|daughter|mother|mum|mom|mommy|mummy|father|dad|daddy|brother|sister|friend|boyfriend|"
              "girlfriend|fiance|fiancé|fiancée|grandson|granddaughter|grandmother|grandma|granny|nan|nana|nanny|grandfather|grandpa|"
              "grandad|granddad|aunt|auntie|aunty|uncle|cousin|niece|nephew|neighbour|neighbor|carer|caregiver|colleague|boss|child|"
              "kid|baby|doctor|nurse|dietitian|dietician|consultant|specialist|gp|pharmacist|therapist|coach|stepson|stepdaughter|"
              "stepmother|stepfather|stepmom|stepdad|flatmate|roommate|housemate|landlord|landlady|vet|dentist|teacher|pastor|priest|"
              "rabbi|imam|sponsor|buddy|mate|pal")
_TITLES = ("dr|doctor|prof|professor|mr|mrs|ms|miss|mx|nurse|sister|dietitian|dietician|nephrologist|endocrinologist|consultant|"
           "surgeon|physician|pharmacist|gp|therapist|coach|matron|midwife|dear|hi|hello|hey|thanks|cheers|signed|regards|"
           "sincerely|named|called")
PERSON_CUE = re.compile(
    rf"(?<![\w])(?:(?i:{_TITLES})\.?|(?i:my|our|his|her|their)\s(?i:{_RELATIONS}))[ ,:]{{1,3}}(?P<name>{_NAMES})")
OWN_NAME_CUE = re.compile(r"(?<![\w])(?i:my name is|my name's|i am called|i'm called|name:)\s(?P<name>[A-Za-z][A-Za-z'’\-]{1,30}"
                          rf"(?:[ ]{_NAME})?)")
_PLACE_CUES = ("i am in|i'm in|we are in|we're in|i was in|we were in|live in|living in|lives in|lived in|moved to|moving to|move to|moved from|trip to|holiday in|holidays in|vacation in|"
               "visiting|visited|staying in|stay in|stayed in|born in|grew up in|based in|i'm from|i am from|we're from|we are from|"
               "he's from|she's from|near|flying to|flew to|fly to|travelling to|traveling to|travel to|driving to|drove to|"
               "town of|city of|village of|county of|state of|work in|works in|working in|study in|school in")
PLACE_CUE = re.compile(rf"(?<![\w])(?i:{_PLACE_CUES})\s(?P<name>{_NAMES})")
_VENUES = ("Hospital|Hospitals|Clinic|Medical Center|Medical Centre|Health Center|Health Centre|Infirmary|Pharmacy|Dialysis Unit|"
           "Dialysis Center|Dialysis Centre|Renal Unit|Renal Centre|Renal Center|Kidney Center|Kidney Centre|Health System|"
           "Medical Group|Healthcare|Care Home|Nursing Home|University|College|School|Church|Mosque|Synagogue|Temple")
VENUE = re.compile(rf"(?<![\w])(?:(?:St\.?|Saint)\s)?(?:[A-Z][\w'’&\-]{{0,30}}\s){{1,4}}(?:{_VENUES})(?![\w])")
_STREETS = ("street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd|court|ct|close|way|place|pl|terrace|crescent|square|sq|"
            "highway|hwy|parkway|pkwy|circle|cir|gardens|grove|row|mews|walk|hill|park|trail|parade")
_CITY = r"(?:,\s[A-Z][a-zA-Z\-]{1,25}(?:\s[A-Z][a-zA-Z\-]{1,25})?)"  # ", London", ", San Diego" after a street or before a state
STREET = re.compile(rf"(?<![\w.])\d{{1,5}}[A-Za-z]?,?\s(?:[A-Z][a-zA-Z'’\-]{{0,25}}\s){{1,3}}(?i:{_STREETS})(?![\w])\.?{_CITY}?")
# A street named with no house number: full street words only, capitalised ("Elm Street", "Oxford Road").
STREET_NAME = re.compile(r"(?<![\w])(?:[A-Z][a-zA-Z'’\-]{1,25}\s){1,2}(?:Street|Road|Avenue|Lane|Boulevard|Terrace|Crescent|Parkway|Highway)(?![\w])")
UNIT_ADDRESS = re.compile(r"(?<![\w])(?:(?i:apt|apartment|flat|suite)\.?\s?#?\d{1,5}[A-Za-z]?|(?i:p\.?\s?o\.?\s?box)\s?\d{1,6})(?![\w])")
UK_POSTCODE = re.compile(r"(?<![\w])[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}(?![\w])")
CA_POSTCODE = re.compile(r"(?<![\w])[A-Z]\d[A-Z]\s?\d[A-Z]\d(?![\w])")
ZIP4 = re.compile(r"(?<![\w.])\d{5}-\d{4}(?![\w])")
_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|"
           "SD|TN|TX|UT|VT|VA|WA|WV|WI|WY")
STATE_ZIP = re.compile(rf"(?<![\w])(?P<zip>(?:[A-Z][a-zA-Z\-]{{1,25}}(?:\s[A-Z][a-zA-Z\-]{{1,25}})?,\s)?(?:{_STATES})\s\d{{5}})(?![\w])")
ZIP_CUE = re.compile(r"(?<![\w])(?i:zip|zip code|zipcode|postcode|post code|postal code)[:\s]{1,3}(?P<zip>[A-Za-z0-9]{3,4}\s?[A-Za-z0-9]{3,4}|\d{5})(?![\w])")
EMAIL_LOCAL = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")
EMAIL_DOMAIN = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
URL = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>\"'\\\[\]{}|^`]{1,2048}", re.IGNORECASE)
_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December|"
           "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
DATE_NUMERIC = re.compile(r"(?<![\w./-])(?:(?P<y>\d{4})(?P<s1>[-/.])(?P<m>\d{1,2})(?P=s1)(?P<d>\d{1,2})"
                          r"|(?P<a>\d{1,2})(?P<s2>[-/.])(?P<b>\d{1,2})(?P=s2)(?P<yy>\d{4}|\d{2}))(?!\d)(?![/.-]\d)")
DATE_WORDS = re.compile(
    rf"(?<![\w])(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s(?:of\s)?(?:{_MONTHS})\.?(?:,?\s\d{{4}})?"
    rf"|(?:{_MONTHS})\.?\s(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s\d{{4}})?"
    rf"|(?:{_MONTHS})\.?,?\s(?:19|20)\d{{2}})(?![\w])")
BIRTH_YEAR = re.compile(r"(?<![\w])(?i:born|born in|dob|d\.o\.b\.|date of birth|birth year|year of birth|birthday)[:\s]{1,3}(?:in\s)?"
                        r"(?P<year>(?:19|20)\d{2})(?![\w])")
DIGIT_CLUSTER = re.compile(r"(?<![\w.+])\+?\(?\d[\d ().\-]{5,24}\d(?![\w])")
SSN = re.compile(r"(?<![\w-])\d{3}-\d{2}-\d{4}(?![\w-])")
LONG_DIGITS = re.compile(r"(?<![\w.])\d{7,64}")
_ID_LABELS = ("mrn|nhs no|nhs number|nhs num|nhs|chi number|chi no|medical record number|medical record|record number|record no|"
              "record num|record|patient id|patient number|patient no|hospital number|hospital no|account number|account no|account|"
              "member id|member number|member no|policy number|policy no|insurance id|insurance number|insurance no|ssn|"
              "social security number|social security|case number|case no|reference number|reference no|reference|ref no|ref|"
              "medicare number|medicare no|medicare|medicaid id|medicaid number|medicaid|id number|id no|id|"
              "health card|health card number|passport number|passport no|passport|licence number|license number")
ID_LABELLED = re.compile(rf"(?<![\w])(?i:{_ID_LABELS})(?![\w])\.?\s?(?i:is\s)?[:#]?\s?(?P<v>[A-Za-z0-9][A-Za-z0-9\-]{{2,24}}"
                         r"(?:\s\d{3,4}){0,2})(?![\w])")
PLACEHOLDER = re.compile(r"\[?(?<![A-Za-z0-9_])(?i:(PERSON|PLACE|ADDRESS|DATE|PHONE|EMAIL|URL|ID))_(\d{1,6})(?![A-Za-z0-9_])\]?")
EXISTING = re.compile(r"\[(PERSON|PLACE|ADDRESS|DATE|PHONE|EMAIL|URL|ID)_(\d{1,6})\]")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]{0,40}")
_SPACE_SEPARATED_SHAPES = frozenset(((3, 3, 4), (3, 4, 4), (4, 3, 4), (4, 4, 3), (5, 6), (5, 3, 3), (2, 4, 4), (4, 6), (3, 8),
                                     (2, 2, 2, 2, 2), (1, 3, 3, 4), (1, 3, 3, 3)))


def _fold(text: str) -> str:
    return " ".join(text.split()).casefold()


def _app_words() -> frozenset[str]:
    """Every word of the app's own prompts and the nutrient names: a known name that is one of these is not replaced
    everywhere, or the app's own instructions would change."""
    global _APP_WORDS
    if _APP_WORDS is None:
        from ..nutrients import NUTRIENT_BY_KEY
        from . import prompts

        words: set[str] = set(STOP_WORDS)

        def take(value: Any) -> None:
            if isinstance(value, str):
                words.update(w.casefold() for w in _WORD.findall(value[:MAX_TEXT_CHARS]))
            elif isinstance(value, Mapping):
                for k, v in value.items():
                    take(k)
                    take(v)
            elif isinstance(value, (list, tuple, frozenset, set)):
                for v in value:
                    take(v)

        for value in vars(prompts).values():
            take(value)
        for key in NUTRIENT_BY_KEY:
            take(key.replace("_", " "))
        _APP_WORDS = frozenset(words)
    return _APP_WORDS


_APP_WORDS: frozenset[str] | None = None


# --------------------------------------------------------------------------- #
# The account's known names
# --------------------------------------------------------------------------- #


def _term_variants(value: Any) -> list[str]:
    """A name as stored, and each word of it (the display name "Ann Marie Smith" also gives "Ann", "Marie", "Smith")."""
    if not isinstance(value, str):
        return []
    text = " ".join(value.split())[:MAX_TERM_CHARS]
    if not text:
        return []
    out = [text]
    if "@" in text:  # an e-mail: the whole address, its local part and the local part's words
        local = text.split("@", 1)[0]
        out.append(local)
        out += [p for p in re.split(r"[._+\-]", local) if p]
    else:
        out += text.split(" ")
        out += [p for p in re.split(r"[._\-]", text) if p and p != text]
    return out


def expand_terms(values: Iterable[Any]) -> tuple[str, ...]:
    """Names as stored → the terms the filter looks for: each name, each word of it and an e-mail's local part, without
    repeats, without common words (:func:`usable_term`), at most :data:`MAX_TERMS`."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for term in _term_variants(value):
            key = _fold(term)
            if key not in seen and usable_term(term):
                seen.add(key)
                out.append(term)
            if len(out) >= MAX_TERMS:
                return tuple(out)
    return tuple(out)


def usable_term(term: str) -> bool:
    """A known name is replaced everywhere only when it is at least two letters, is not a number, and is not a word the
    app's own prompts use (one-word names) or a common word (:data:`STOP_WORDS`)."""
    folded = _fold(term)
    if len(folded) < 2 or folded.isdigit() or '"' in term or "\\" in term:
        return False
    if not any(ch.isalpha() for ch in folded):
        return False
    if " " not in folded and folded in _app_words():
        return False
    return True


def known_terms(conn: sqlite3.Connection, user_id: int) -> tuple[str, ...]:
    """The account's user name, display name and e-mail (sign-in links), and the user and display names of its Care team
    (people it shares with, people who share with it, open invites it sent). Read-only."""
    raw: list[Any] = []

    def rows(sql: str, args: tuple[Any, ...]) -> list[sqlite3.Row]:
        try:
            return list(conn.execute(sql, args).fetchall())
        except sqlite3.OperationalError:  # an older database without that table
            return []

    for row in rows("SELECT username, display_name FROM users WHERE id = ?", (user_id,)):
        raw += [row[0], row[1]]
    for row in rows("SELECT email FROM oidc_links WHERE user_id = ? AND email IS NOT NULL", (user_id,)):
        raw.append(row[0])
    for row in rows(
        "SELECT u.username, u.display_name FROM shares s JOIN users u ON u.id = CASE WHEN s.owner_user_id = ? "
        "THEN s.grantee_user_id ELSE s.owner_user_id END WHERE (s.owner_user_id = ? OR s.grantee_user_id = ?) "
        "AND s.ended_at IS NULL AND s.grantee_user_id IS NOT NULL LIMIT 100", (user_id, user_id, user_id)):
        raw += [row[0], row[1]]
    for row in rows("SELECT username FROM care_invites WHERE owner_user_id = ? AND answered_at IS NULL LIMIT 50", (user_id,)):
        raw.append(row[0])
    return expand_terms(raw)


# --------------------------------------------------------------------------- #
# Finding spans
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str


def _next_word(text: str, end: int) -> str:
    i = end
    n = len(text)
    while i < n and text[i] == " ":
        i += 1
    j = i
    while j < n and j - i < 12 and not text[j].isspace() and text[j] not in ",;:!?)\"'":
        j += 1
    return text[i:j].rstrip(".").casefold()


def _prev_word(text: str, start: int) -> str:
    i = start
    while i > 0 and text[i - 1] == " ":
        i -= 1
    j = i
    while j > 0 and i - j < 20 and (text[j - 1].isalpha() or text[j - 1] in "'’"):
        j -= 1
    return text[j:i].casefold()


def _is_amount(text: str, end: int) -> bool:
    """Is the number ending at ``end`` an amount (a unit follows, or it is the whole part of a decimal)?"""
    if end < len(text) and text[end] in "%":
        return True
    if end + 1 < len(text) and text[end] == "." and text[end + 1].isdigit():
        return True
    return _next_word(text, end) in UNITS


def _json_number(text: str, start: int) -> bool:
    """A number right after ``:``, ``,`` or ``[`` (no space) is a number in the app's compact JSON, not something typed."""
    return start > 0 and text[start - 1] in ":,["


def _trim_names(text: str, start: int, end: int, *, venue: bool = False) -> tuple[int, int] | None:
    """The name inside a run of capitalised words: leading common words ("The") are skipped, the run stops at the next common
    word ("Monday", "And") or all-capitals word, and a trailing "'s" is dropped. For a hospital or clinic (``venue``) only
    the leading common words are skipped ("St" stays)."""
    words = [(m.start() + start, m.end() + start) for m in re.finditer(r"\S+", text[start:end])]

    def common(i: int) -> bool:
        word = text[words[i][0]:words[i][1]]
        folded = _fold(word).rstrip(".")
        if venue and folded in ("st", "saint"):
            return False
        return folded in STOP_WORDS or (len(word) > 1 and word.isupper() and not venue)

    first = 0
    while first < len(words) and common(first):
        first += 1
    if first == len(words):
        return None
    last = first
    if venue:
        last = len(words) - 1
    else:
        while last + 1 < len(words) and not common(last + 1):
            last += 1
    s, e = words[first][0], words[last][1]
    if text[e - 2:e] in ("'s", "’s") and e - 2 > s:
        e -= 2
    return s, e


def _cue_matches(pattern: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """Like ``finditer``, but a match whose name part was only common words ("Hi. My") does not hide a cue inside it ("My
    friend Ann"): the search goes on from the start of the name part. Every step moves forward, so it stays linear."""
    pos = 0
    while pos <= len(text):
        match = pattern.search(text, pos)
        if match is None:
            return
        yield match
        pos = match.start("name") if _trim_names(text, match.start("name"), match.end("name")) is None else match.end()


def _names(text: str) -> Iterator[Span]:
    """Names after a cue (Dr, my wife, named, ...), places after a cue (live in, near, ...) and named hospitals and clinics."""
    for match in _cue_matches(PERSON_CUE, text):
        cue = _fold(text[match.start():match.start("name")])
        phrase = _fold(text[match.start():match.end("name")])
        if any(phrase.startswith(p) or (" " + p) in phrase for p in KEPT_PHRASES):
            continue
        kind = "PERSON"
        if cue.rstrip(" ,:") in ("called", "named"):
            before = _prev_word(text, match.start())
            if before in FOOD_BEFORE_CUE:
                continue
            if before in PLACE_BEFORE_CUE:
                kind = "PLACE"
        trimmed = _trim_names(text, match.start("name"), match.end("name"))
        if trimmed:
            yield Span(trimmed[0], trimmed[1], kind)
    for match in _cue_matches(OWN_NAME_CUE, text):
        trimmed = _trim_names(text, match.start("name"), match.end("name"))
        if trimmed:
            yield Span(trimmed[0], trimmed[1], "PERSON")
    for match in _cue_matches(PLACE_CUE, text):
        trimmed = _trim_names(text, match.start("name"), match.end("name"))
        if trimmed:
            yield Span(trimmed[0], trimmed[1], "PLACE")
    for match in VENUE.finditer(text):
        trimmed = _trim_names(text, match.start(), match.end(), venue=True)
        if trimmed:
            yield Span(trimmed[0], trimmed[1], "PLACE")


def _emails(text: str) -> Iterator[Span]:
    """Every ``local@domain.tld``, found by scanning around each ``@`` (plain string code, no regex)."""
    n = len(text)
    at = text.find("@")
    while at != -1:
        s = at
        while s > 0 and at - s < 64 and text[s - 1] in EMAIL_LOCAL:
            s -= 1
        e = at + 1
        while e < n and e - at < 255 and text[e] in EMAIL_DOMAIN:
            e += 1
        while e > at + 1 and text[e - 1] in ".-":
            e -= 1
        domain = text[at + 1:e]
        if s < at and "." in domain and not domain.startswith("."):
            yield Span(s, e, "EMAIL")
        at = text.find("@", max(e, at + 1))


def _urls(text: str) -> Iterator[Span]:
    for match in URL.finditer(text):
        s, e = match.start(), match.end()
        while e > s and text[e - 1] in ".,;:!?)":
            e -= 1
        url = text[s:e]
        if any(ch in url for ch in "?#@") or re.search(r"\d{5}", url):
            yield Span(s, e, "URL")


def _dates(text: str) -> Iterator[Span]:
    for match in DATE_NUMERIC.finditer(text):
        if match.group("y"):
            y, m, d = int(match.group("y")), int(match.group("m")), int(match.group("d"))
            ok = 1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31
        else:
            a, b, yy = int(match.group("a")), int(match.group("b")), match.group("yy")
            year_ok = len(yy) == 2 or 1900 <= int(yy) <= 2100
            ok = year_ok and a >= 1 and b >= 1 and ((a <= 31 and b <= 12) or (a <= 12 and b <= 31))
            if ok and match.group("s2") == "." and len(yy) == 2:  # "4.5.10" reads as numbers more often than a date
                ok = a > 12 or b > 12 or (_prev_word(text, match.start()) in ("on", "dob", "born", "date", "dated"))
        if ok:
            yield Span(match.start(), match.end(), "DATE")
    for match in DATE_WORDS.finditer(text):
        day = match.group("d1") or match.group("d2")
        if day is None or 1 <= int(day) <= 31:
            yield Span(match.start(), match.end(), "DATE")
    for match in BIRTH_YEAR.finditer(text):
        yield Span(match.start("year"), match.end("year"), "DATE")


def _phone_shape(value: str) -> bool:
    digits = sum(ch.isdigit() for ch in value)
    plus = value.startswith("+")
    groups = [g for g in re.split(r"[ ().\-]", value.lstrip("+")) if g]
    sizes = tuple(len(g) for g in groups)
    if not all(g.isdigit() for g in groups):
        return False
    separators = {ch for ch in value if ch in "().-"}
    if digits == 7 and sizes == (3, 4) and separators == {"-"}:
        return True
    if not 10 <= digits <= 15:
        return False
    if len(groups) == 1:
        return value.startswith("0") or plus
    if plus or "(" in separators:
        return all(len(g) >= 2 for g in groups[1:])
    if separators:
        return all(2 <= len(g) <= 5 for g in groups) and len(groups) <= 5
    return sizes in _SPACE_SEPARATED_SHAPES


def _numbers(text: str) -> Iterator[Span]:
    for match in DIGIT_CLUSTER.finditer(text):
        s, e = match.start(), match.end()
        value = text[s:e]
        if value.count("(") != value.count(")"):  # "(555) 123" fine; a stray bracket belongs to the sentence
            if value.startswith("(") and ")" not in value:
                s += 1
                value = value[1:]
            elif value.endswith(")"):
                e -= 1
                value = value[:-1]
        if _json_number(text, s) or _is_amount(text, e):
            continue
        if _phone_shape(value):
            yield Span(s, e, "PHONE")
    for match in SSN.finditer(text):
        yield Span(match.start(), match.end(), "ID")
    for match in LONG_DIGITS.finditer(text):
        s, e = match.start(), match.end()
        while e < len(text) and text[e].isdigit():  # a run longer than the pattern's bound: take all of it
            e += 1
        if (e < len(text) and (text[e].isalpha() or text[e] == "_")) or _json_number(text, s) or _is_amount(text, e):
            continue
        yield Span(s, e, "ID")
    for match in ID_LABELLED.finditer(text):
        value = match.group("v")
        if sum(ch.isdigit() for ch in value) >= 4 and not _is_amount(text, match.end("v")):
            yield Span(match.start("v"), match.end("v"), "ID")


def _addresses(text: str) -> Iterator[Span]:
    for pattern in (STREET, STREET_NAME, UNIT_ADDRESS, UK_POSTCODE, CA_POSTCODE, ZIP4):
        for match in pattern.finditer(text):
            yield Span(match.start(), match.end(), "ADDRESS")
    for pattern in (STATE_ZIP, ZIP_CUE):
        for match in pattern.finditer(text):
            yield Span(match.start("zip"), match.end("zip"), "ADDRESS")


def _terms_pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    words = sorted({_fold(t) for t in terms if t}, key=len, reverse=True)
    if not words:
        return None
    alternatives = "|".join(r"\s+".join(re.escape(part) for part in w.split(" ")) for w in words)
    return re.compile(rf"(?<![\w@])(?:{alternatives})(?![\w@])", re.IGNORECASE)


def find_spans(text: str, terms: re.Pattern[str] | None = None) -> list[Span]:
    """Every identifier in ``text``. Overlapping finds are joined into one span (the kind of the one that starts first), so a
    street, its town and its ZIP code become one address."""
    if len(text) > MAX_TEXT_CHARS:
        raise FilterLimit(f"a text part is longer than {MAX_TEXT_CHARS} characters")
    found: list[Span] = []
    found += _emails(text)
    found += _urls(text)
    found += _addresses(text)
    found += _dates(text)
    found += _numbers(text)
    found += _names(text)
    if terms is not None:
        found += (Span(m.start(), m.end(), "PERSON") for m in terms.finditer(text))
    found.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[Span] = []
    for span in found:
        if span.end <= span.start:
            continue
        if out and span.start < out[-1].end:
            if span.end > out[-1].end:
                out[-1] = Span(out[-1].start, span.end, out[-1].kind)
            continue
        out.append(span)
    return out


# --------------------------------------------------------------------------- #
# One request's labels
# --------------------------------------------------------------------------- #


@dataclass
class Shield:
    """The labels of one request. Kept in memory for that request only; :meth:`restore` uses it on the reply."""

    terms: tuple[str, ...] = ()
    _labels: dict[str, str] = field(default_factory=dict, repr=False)
    _words: dict[str, str] = field(default_factory=dict, repr=False)
    _counts: dict[str, int] = field(default_factory=dict, repr=False)
    _taken: set[str] = field(default_factory=set, repr=False)
    _learned: dict[str, str] = field(default_factory=dict, repr=False)
    replaced: int = 0  # how many details were replaced in the last body filtered (never which)

    def __repr__(self) -> str:  # never show the words
        return f"Shield(labels={len(self._labels)}, replaced={self.replaced})"

    def _label(self, kind: str, original: str) -> str:
        """The label of ``original``: the same words (any case, any spacing) always get the same label in one request."""
        key = _fold(original)
        label = self._labels.get(key)
        if label is None:
            n = self._counts.get(kind, 0)
            while True:
                n += 1
                label = f"[{kind}_{n}]"
                if label not in self._taken:
                    break
            self._counts[kind] = n
            self._labels[key] = label
            self._words[label] = original
        return label

    def learn(self, texts: Iterable[str]) -> None:
        """Note the labels already in the text (so a new one never reuses them) and the names found after a cue, so the same
        name is replaced everywhere in the request, not only where the cue is."""
        for text in texts:
            if len(text) > MAX_TEXT_CHARS:
                raise FilterLimit(f"a text part is longer than {MAX_TEXT_CHARS} characters")
            self._taken.update(m.group(0) for m in EXISTING.finditer(text))
            for span in _names(text):
                word = text[span.start:span.end]
                if usable_term(word) and _fold(word) not in self._learned:
                    self._learned[_fold(word)] = span.kind

    def _pattern(self) -> re.Pattern[str] | None:
        return _terms_pattern([*self.terms, *self._learned])

    def redact(self, text: str, pattern: re.Pattern[str] | None = None) -> tuple[str, int]:
        """``text`` with every identifier replaced by its label, and how many were replaced."""
        spans = find_spans(text, pattern if pattern is not None else self._pattern())
        if not spans:
            return text, 0
        parts: list[str] = []
        last = 0
        for span in spans:
            original = text[span.start:span.end]
            kind = span.kind
            if kind == "PERSON" and self._learned.get(_fold(original)) == "PLACE":
                kind = "PLACE"
            parts.append(text[last:span.start])
            parts.append(self._label(kind, original))
            last = span.end
        parts.append(text[last:])
        return "".join(parts), len(spans)

    def filter_body(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """A copy of a Chat Completions body with every text part of every message filtered (images are left as they are)."""
        out = copy.deepcopy(dict(body))
        messages = out.get("messages")
        if not isinstance(messages, list):
            self.replaced = 0
            return out
        self.learn(_texts(messages))
        pattern = self._pattern()
        replaced = 0
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                message["content"], n = self.redact(content, pattern)
                replaced += n
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                        part["text"], n = self.redact(part["text"], pattern)
                        replaced += n
        self.replaced = replaced
        return out

    def restore_text(self, text: str) -> str:
        if not self._words or not text:
            return text

        def put_back(match: re.Match[str]) -> str:
            label = f"[{match.group(1).upper()}_{int(match.group(2))}]"
            return self._words.get(label, match.group(0))

        return PLACEHOLDER.sub(put_back, text[:MAX_TEXT_CHARS]) + text[MAX_TEXT_CHARS:]

    def restore(self, value: Any) -> Any:
        """The parsed reply with every label put back into the words it stands for (strings only; keys are left alone)."""
        if isinstance(value, str):
            return self.restore_text(value)
        if isinstance(value, list):
            return [self.restore(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore(v) for k, v in value.items()}
        return value


def _texts(messages: list[Any]) -> Iterator[str]:
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                    yield part["text"]


def applies(cfg: Any) -> bool:
    """The filter runs for every provider that is not pinned to the private network (the local AI)."""
    return not bool(getattr(cfg, "local_only", False))


def shield_for(cfg: Any) -> Shield | None:
    """A fresh :class:`Shield` for one request to ``cfg``, or None for the local AI (its requests are never changed)."""
    if not applies(cfg):
        return None
    return Shield(terms=tuple(getattr(cfg, "privacy_terms", ()) or ()))


def preview(cfg: Any, body: Mapping[str, Any]) -> tuple[dict[str, Any], int | None]:
    """What a request to ``cfg`` sends: the filtered body and how many details were replaced, or the body unchanged and None
    for the local AI. "What will be sent?" and the AI activity copy use this, so they show exactly what leaves."""
    shield = shield_for(cfg)
    if shield is None:
        return copy.deepcopy(dict(body)), None
    out = shield.filter_body(body)
    return out, shield.replaced


def filter_text(text: str, terms: Iterable[str] = ()) -> str:
    """One text, filtered on its own (the test set and the design note's examples)."""
    shield = Shield(terms=expand_terms(terms))
    shield.learn([text])
    return shield.redact(text)[0]
