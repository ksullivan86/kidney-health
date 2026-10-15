"""The in-app Ask chat (assistant step 2, part A): the step protocol's loop, the checks on the model's answer
and the "From the app" numbers. ``docs/dev/plans/assistant-step2.md``; ARCHITECTURE.md "Ask chat".

The chat is the one AI feature whose model writes free text for the person, so the answer is checked in code
before it is shown (the chat's V6, the way :mod:`app.ai.guard` checks the meal features):

1. **Text policy**: NFKC, control and format characters removed, links and e-mail addresses removed except the
   app's own ``/learn/...`` paths, at most :data:`MAX_ANSWER_CHARS` characters, cut at a sentence end.
2. **Dose check**: insulin, bolus, basal, correction and carbohydrate ratios, dose/dosing, the binder names of
   :data:`app.ai.guard.MEDICINE_NAMES`, advice to skip, delay or change insulin or medicine, and advice to wait,
   skip or avoid something while treating a low, withhold the answer.
3. **Number check**: every number that has a nutrient or energy unit next to it must equal, at the precision
   shown, a number in this message's tool results or in the person's own messages.
4. Lab words add a fixed note. The tools' own figures are shown under every answer ("From the app").

Saving (part C): the model may also call ``log_food`` and ``save_recipe``. What happens to such a call is the
route's decision, made by the ``run_save`` callback (:mod:`app.ai.chat_save`): in **ask** mode nothing is saved, the
loop ends with ``kind: "confirm_save"`` and the card the person presses Save on; in a **trusted** mode the save runs at
once (the MCP tools' own code) and the model is told the result. ``safety_check`` is never offered.

Pure apart from the callbacks :func:`converse` is given: no database, no network, no clock. The route
(:mod:`app.ai.routes`) supplies the quota, the model call, the tools and the activity log.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

from ..guidance import hypo
from ..nutrients import NUTRIENT_BY_KEY
from ..textclean import clean_text
from . import features as F
from . import guard, prompts, schemas
from .client import CallResult

MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 2000
MAX_TOOL_CALLS = 6
MAX_ANSWER_CHARS = 1200
CHAT_TOOLS: tuple[str, ...] = ("get_today", "search_foods", "check_meal")  # read-only
SAVE_TOOLS: tuple[str, ...] = ("log_food", "save_recipe")  # saving: run only through ``run_save`` (never safety_check)
OFFERED_TOOLS: tuple[str, ...] = CHAT_TOOLS + SAVE_TOOLS
MAX_SAVES = 2  # save calls the model may make for one message
MAX_NUMBER_GROUPS = 4
MAX_FOODS_SHOWN = 5
SHOWN_NUTRIENTS = ("calories_kcal", "protein_g", "carbs_g", "potassium_mg", "phosphorus_mg", "sodium_mg", "fluid_ml")

TREAT_LOW_TEXT = "Treat the low first. When you feel better, ask again."
GET_HELP_TEXT = "Get help now first. When you are safe, ask again."
WITHHELD_DOSE_TEXT = ("This answer was not shown because it touched on medicine or insulin doses. "
                      "Ask your care team about doses.")
WITHHELD_NUMBER_TEXT = ("The assistant's answer had a number the app did not work out, so it is not shown. "
                        "Here are the app's own numbers.")
UNFINISHED_TEXT = "The assistant could not finish; here are the app's numbers."
CONFIRM_TEXT = "Nothing has been saved yet. Check this, then press a Save button, or Cancel."
SAVE_LIMIT_ERROR = (f"At most {MAX_SAVES} saves can be made for one message. Tell the person what was saved and answer.")
SAVES_CLOSED_ERROR = "This message's save was already made once. Tell the person what was saved and answer; do not save again."
EMPTY_TEXT = "The assistant's answer could not be used."
LAB_NOTE = "Lab results are for your care team to interpret."
NOTICE = "AI answer · {label} · {model} · every number checked by the app · not medical advice"

# --------------------------------------------------------------------------- #
# The conversation sent to the model
# --------------------------------------------------------------------------- #


def is_safety_text(text: str) -> bool:
    """Words the app's rules answer without a model: a possible low (the Treating a low card) or an emergency."""
    return hypo.mentions_low(text) or F.red_flag(text)


def history_messages(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """The conversation as the model gets it: each text cleaned, a message that matches a safety rule left out
    together with the answer that followed it (low talk never reaches a provider, on any turn), neighbours of
    the same role joined, and the first message from the person."""
    out: list[dict[str, str]] = []
    skip_reply = False
    for item in messages:
        role = "user" if item.get("role") == "user" else "assistant"
        raw = item.get("text") or ""
        if role == "user":
            skip_reply = is_safety_text(raw)
            if skip_reply:
                continue
        elif skip_reply:
            skip_reply = False
            continue
        text = prompts.clean(raw, MAX_MESSAGE_CHARS)
        if not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + text
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def fit_history(history: list[dict[str, str]], fits: Callable[[list[dict[str, str]]], bool]) -> list[dict[str, str]] | None:
    """The newest part of ``history`` that ``fits`` the provider's prompt budget (always the last message), starting
    with a message from the person; ``None`` when not even the last message fits."""
    window = list(history)
    while window and not fits(window):
        window.pop(0)
        while window and window[0]["role"] != "user":
            window.pop(0)
    return window or None


def tools_text(tools: Mapping[str, Mapping[str, Any]]) -> str:
    """``- name: note`` and its argument schema, for the system prompt. ``tools`` maps a name to its input schema. The
    saving tools' ``request_key`` is left out: the app makes the key for each save, the model never chooses one."""
    lines = []
    for name in OFFERED_TOOLS:
        schema = _plain_schema(tools[name])
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            schema["properties"].pop("request_key", None)
        lines.append(f"- {name}: {prompts.CHAT_TOOL_NOTES[name]}")
        lines.append("  arguments: " + json.dumps(schema, sort_keys=True, separators=(",", ":")))
    return "\n".join(lines)


def _plain_schema(schema: Any) -> Any:
    """A tool's input schema without the prose (``description``, ``default``, ``title``): the tools' own wording is
    written for an outside assistant and names tools the chat does not have; the chat's notes replace it."""
    if isinstance(schema, Mapping):
        return {k: _plain_schema(v) for k, v in schema.items() if k not in ("description", "default", "title")}
    if isinstance(schema, list):
        return [_plain_schema(v) for v in schema]
    return schema


def tool_result_message(tool: str, result: Mapping[str, Any], left: int) -> dict[str, str]:
    """What the model is told after a tool ran: the result as a data block (untrusted text cleaned, ``<``, ``>`` and
    ``&`` escaped), and how many calls are left."""
    shown = {k: v for k, v in result.items() if k not in ("source", "reminder")}
    text = prompts.CHAT_TOOL_RESULT.format(tool=tool, left=left, data=prompts.data_block(prompts.scrub(shown)))
    if left <= 0:
        text += " " + prompts.CHAT_NO_CALLS_LEFT
    return {"role": "user", "content": text}


def tool_error_message(tool: str, message: str, left: int) -> dict[str, str]:
    text = prompts.CHAT_TOOL_ERROR.format(tool=prompts.clean(tool, 40), message=prompts.clean(message, 300), left=left)
    if left <= 0:
        text += " " + prompts.CHAT_NO_CALLS_LEFT
    return {"role": "user", "content": text}


def step_message(step: schemas.ChatStep) -> dict[str, str]:
    """The model's own call, put back into the conversation in the form the protocol asks for."""
    assert step.call is not None
    call = {"call": {"tool": step.call.tool, "arguments": step.call.arguments}}
    return {"role": "assistant", "content": json.dumps(call, separators=(",", ":"), ensure_ascii=False)}


# --------------------------------------------------------------------------- #
# Numbers: what the answer may say
# --------------------------------------------------------------------------- #

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"
_NUM_RE = re.compile(_NUM)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Counts and ids are not figures an answer may quote: a made-up "5 g" must not pass because a result has "id": 5.
_NOT_FIGURES = frozenset({"id", "food_id", "fdc_id", "not_listed_by", "limit", "found", "entry_id", "entry_ids", "meal_id"})
_UNIT = (r"(?:mg|mcg|µg|μg|ug|g|grams?|milligrams?|micrograms?|ml|millilit(?:re|er)s?|l|lit(?:re|er)s?|kcal|"
         r"kilocalories?|calories?|cal|kj|kilojoules?|%|percent)")
_QUANTITY = re.compile(rf"(?<![\w.])(?P<a>{_NUM})(?:\s*(?:-|–|—|to|and|or)\s*(?P<b>{_NUM}))?\s*(?P<unit>{_UNIT})(?![A-Za-z])",
                       re.IGNORECASE)
_PER_BASIS = re.compile(r"\bper\s*$", re.IGNORECASE)


def to_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def collect_numbers(value: Any, out: set[Decimal], key: str | None = None) -> None:
    """Every figure in ``value`` (a tool result, or the person's text): numbers, and the numbers written inside strings."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if key in _NOT_FIGURES or (isinstance(value, float) and not math.isfinite(value)):
            return
        out.add(Decimal(repr(value)) if isinstance(value, float) else Decimal(value))
    elif isinstance(value, str):
        for match in _NUM_RE.finditer(_DATE_RE.sub(" ", value)):
            number = to_decimal(match.group(0))
            if number is not None:
                out.add(number)
    elif isinstance(value, Mapping):
        for k, v in value.items():
            collect_numbers(v, out, str(k))
    elif isinstance(value, (list, tuple)):
        for v in value:
            collect_numbers(v, out, key)


class NumberPool:
    """The figures an answer may use. ``has(value, decimals)``: equal to one of them, or equal to one of them rounded to
    ``decimals`` places (half up or half even), so 1234.6 may be shown as 1235 or 1,235 and 1234 as 1234.0."""

    def __init__(self, numbers: Iterable[Decimal]) -> None:
        self.exact = set(numbers)
        self._rounded: dict[int, set[Decimal]] = {}

    def has(self, value: Decimal, decimals: int) -> bool:
        if value in self.exact:
            return True
        rounded = self._rounded.get(decimals)
        if rounded is None:
            places = Decimal(1).scaleb(-decimals)
            rounded = set()
            for number in self.exact:
                for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN):
                    try:
                        rounded.add(number.quantize(places, rounding=mode))
                    except InvalidOperation:
                        continue
            self._rounded[decimals] = rounded
        return value in rounded


def pool_for(results: Iterable[Mapping[str, Any]], person_texts: Iterable[str]) -> NumberPool:
    numbers: set[Decimal] = set()
    for result in results:
        collect_numbers(result, numbers)
    for text in person_texts:
        collect_numbers(text, numbers)
    return NumberPool(numbers)


def quantities(text: str) -> list[tuple[str, Decimal, int]]:
    """``(as written, value, decimals shown)`` for every number with a nutrient or energy unit next to it. A range
    ("1,500-2,000 mg") gives both ends; "per 100 g" names a basis, not an amount."""
    found: list[tuple[str, Decimal, int]] = []
    for match in _QUANTITY.finditer(text):
        for group in ("a", "b"):
            token = match.group(group)
            if token is None:
                continue
            value = to_decimal(token)
            if value is None:
                continue
            if group == "a" and value == 100 and _PER_BASIS.search(text[:match.start()]):
                continue
            decimals = len(token.partition(".")[2]) if "." in token else 0
            found.append((token, value, decimals))
    return found


def unmatched_number(text: str, pool: NumberPool) -> str | None:
    """The first number with a unit that is not in ``pool``, as written, else ``None``."""
    for token, value, decimals in quantities(text):
        if not pool.has(value, decimals):
            return token
    return None


# --------------------------------------------------------------------------- #
# The dose check
# --------------------------------------------------------------------------- #

_I = re.IGNORECASE
_INSULIN = re.compile(
    r"\b(?:insulin\w*|bolus\w*|basal\w*|inject\w*|syringes?|sliding scale|correction (?:factor|dose|bolus|insulin|ratio)|"
    r"sensitivity factor|(?:carb(?:ohydrate)?s?|insulin)\s*(?:to|:|/)\s*(?:carb(?:ohydrate)?s?|insulin)|"
    r"(?:carb(?:ohydrate)?|insulin)s?[- ]ratios?|i:?c ratio|icr|isf)\b", _I)
_DOSE = re.compile(r"\b(?:dos(?:e|es|ed|ing|age)|overdos\w*)\b|\b\d+(?:\.\d+)?\s*(?:units|iu)\b", _I)
_MEDICINE_NAME = re.compile(rf"\b(?:{guard.MEDICINE_NAMES})\b", _I)
_SKIP_MEDICINE = re.compile(
    r"\b(?:skip|skipp(?:ing|ed)|miss(?:ing|ed)?|delay(?:ing|ed)?|postpon(?:e|ing|ed)|hold(?:ing)? off(?: on)?|put(?:ting)? off|"
    r"withhold(?:ing)?|forget(?:ting)? to take)\b(?:\W+\w+){0,3}?\W+"
    r"(?:insulin|medicines?|medications?|meds|binders?|pills?|tablets?|doses?|shots?|injections?|treatment)\b", _I)
_CHANGE_MEDICINE = re.compile(
    r"\b(?:adjust|chang|increas|decreas|reduc|rais|lower|doubl|halv|stop|start|titrat)\w*\s+(?:taking\s+)?(?:your|the)\s+"
    r"(?:insulin|medicines?|medications?|meds|binders?|pills?|tablets?)\b", _I)
# A sentence about a low blood sugar that also restricts, delays or questions something: advice to wait, skip or
# avoid a low treatment (including "because of potassium") is never shown. A sentence that merely says what to do
# ("if you are low, treat it with glucose tablets") passes.
_LOW_CONTEXT = re.compile(
    r"\b(?:hypo\w*|low[- ]blood[- ](?:sugar|glucose)|low[- ]glucose|"
    r"(?:blood[- ])?(?:sugar|glucose)(?:\s+(?:is|are|was|gets?|goes|go|drops?|falls?|being|running|stays?))*\s+"
    r"(?:too |very |a bit |really |getting )?low|"
    r"treat\w*\s+(?:a |an |your |the |that |this )?(?:low|hypo)s?|"
    r"(?:you|i|they|he|she)(?:'re|\s+are|\s+am|\s+feel|\s+felt|\s+went|\s+go|\s+get)\s+(?:a bit |very |too |really )?low"
    r"(?!\s+(?:on|in|of)\b))\b", _I)
_RESTRICT = re.compile(
    r"\b(?:avoid\w*|don'?t|do not|doesn'?t|never|skip\w*|delay\w*|wait\w*|hold(?:ing)? off|postpon\w*|instead of|rather than|"
    r"stay away|not (?:advised|recommended|safe|allowed|ok|okay|wise|a good idea|worth)|too (?:high|much)|limit\w*|"
    r"careful\w*|caution\w*|no need|only (?:if|after|when)|unless|without|before (?:you |eating|drinking|having|treating)|"
    r"check with|ask (?:your|the) (?:care|doctor|nurse|team)|first (?:check|ask|call))\b", _I)
_SENTENCE = re.compile(r"[^.!?;\n]+")


def _matchable(text: str) -> str:
    return guard.fold(text).replace("’", "'").replace("‘", "'")


def dose_reason(text: str) -> str | None:
    """Why ``text`` talks about insulin or medicine doses (a short code), else ``None``. Narrower than the names
    blocklist: ordinary words such as "more", "extra", "unit", "supplement" or "pills" alone do not count."""
    folded = _matchable(text)
    for code, pattern in (("insulin", _INSULIN), ("dose", _DOSE), ("medicine_name", _MEDICINE_NAME),
                          ("skip_medicine", _SKIP_MEDICINE), ("change_medicine", _CHANGE_MEDICINE)):
        if pattern.search(folded):
            return code
    for sentence in _SENTENCE.findall(folded):
        if _LOW_CONTEXT.search(sentence) and _RESTRICT.search(sentence):
            return "low_treatment"
    return None


# --------------------------------------------------------------------------- #
# Text policy, lab words
# --------------------------------------------------------------------------- #

_LEARN_PATH = re.compile(r"(?<![\w/])/learn/[A-Za-z0-9_\-/#.]*[A-Za-z0-9_\-/#]")
_LINK = re.compile(
    r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ru|cn|xyz|info|biz|app|dev|me|gov|edu|co|uk|de|fr)\b(?:/\S*)?",
    _I)
_EMAIL_ADDRESS = re.compile(r"\b[^\s@]+@[^\s@]+\.[a-z]{2,}\b", _I)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_LAB_WORDS = re.compile(
    r"\b(?:e?gfr|creatinine|a1c|hba1c|(?:glyc(?:at)?ed )?h(?:a)?emoglobin a1c|blood potassium|serum potassium|"
    r"lab results?|lab values?|lab tests?|labs|blood tests?|blood work|bloodwork|urine tests?|acr|uacr)\b", _I)


def text_policy(text: str) -> str:
    """V6 for the chat: NFKC, control and format characters out (line breaks kept), links and e-mail addresses out
    except the app's own ``/learn/...`` paths, then cut to :data:`MAX_ANSWER_CHARS` at a sentence end."""
    cleaned = clean_text(unicodedata.normalize("NFKC", text or ""), max_len=schemas.MAX_CHAT_ANSWER, keep_newlines=True) or ""
    kept: list[str] = []

    def keep(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return f"{len(kept) - 1}"

    cleaned = _LEARN_PATH.sub(keep, cleaned)
    cleaned = _LINK.sub("", _EMAIL_ADDRESS.sub("", cleaned))  # addresses first: "me@example.com" is not a link with "me@" left over
    cleaned = re.sub(r"(\d+)", lambda m: kept[int(m.group(1))], cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", _SPACE_BEFORE_PUNCT.sub(r"\1", cleaned)).strip()
    return cut_at_sentence(cleaned, MAX_ANSWER_CHARS)


def cut_at_sentence(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", head)]
    if ends:
        return head[:ends[-1]].strip()
    return head.rsplit(" ", 1)[0].rstrip(",;: ") + "…"


def lab_words(text: str) -> bool:
    return bool(_LAB_WORDS.search(guard.fold(text)))


# --------------------------------------------------------------------------- #
# The checked answer
# --------------------------------------------------------------------------- #


@dataclass
class Verdict:
    kind: str  # answer | withheld | error
    text: str
    notes: list[str] = field(default_factory=list)
    reason: str | None = None  # why it was withheld (a code for the activity log, never shown)


def check_answer(raw: str, results: Sequence[Mapping[str, Any]], person_texts: Sequence[str], newest: str) -> Verdict:
    """The chat's V6 on the model's answer (see the module doc). A withheld answer keeps the tools' numbers."""
    notes = [LAB_NOTE] if lab_words(raw) or lab_words(newest) else []
    text = text_policy(raw)
    if not text:
        return Verdict("error", EMPTY_TEXT, notes, "empty")
    code = dose_reason(text)
    if code:
        return Verdict("withheld", WITHHELD_DOSE_TEXT, notes, f"dose:{code}")
    if unmatched_number(text, pool_for(results, person_texts)) is not None:
        return Verdict("withheld", WITHHELD_NUMBER_TEXT, notes, "number")
    return Verdict("answer", text, notes)


# --------------------------------------------------------------------------- #
# "From the app": the tools' own figures, shaped for the screen
# --------------------------------------------------------------------------- #


def fmt(value: Any) -> str:
    """A figure as the screen shows it: thousands separators, no trailing ``.0``."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, (int, float)) else str(value)


def amount_text(amount: Any, unit: str) -> str:
    """A total as ``{"value", "not_listed_by"}``: unknown is shown as unknown, never as 0."""
    if not isinstance(amount, Mapping):
        return "not listed"
    value, missing = amount.get("value"), int(amount.get("not_listed_by") or 0)
    if value is None:
        return "not listed"
    text = f"{fmt(value)} {unit}".strip()
    return f"{text} or more" if missing else text


def target_text(target: Mapping[str, Any], unit: str) -> str:
    kind = str(target.get("kind") or "target")
    low, high = target.get("min"), target.get("max")
    if low is not None and high is not None:
        return f"{kind} {fmt(low)}–{fmt(high)} {unit}".strip()
    if high is not None:
        return f"{kind} {fmt(high)} {unit}".strip()
    if low is not None:
        return f"at least {fmt(low)} {unit}".strip()
    return ""


def _judged_parts(view: Mapping[str, Any], unit: str) -> list[str]:
    parts = []
    if view.get("over_by") is not None:
        parts.append(f"{fmt(view['over_by'])} {unit} over".replace("  ", " "))
    elif view.get("left") is not None:
        parts.append(f"{fmt(view['left'])} {unit} left".replace("  ", " "))
    return parts


def _today_group(result: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for nutrient in (result.get("nutrients") or {}).values():
        if not isinstance(nutrient, Mapping):
            continue
        unit = str(nutrient.get("unit") or "")
        target = nutrient.get("target")
        eaten = nutrient.get("eaten") or {}
        if target is None and not eaten.get("value"):
            continue
        parts = [target_text(target, unit)] if isinstance(target, Mapping) else []
        parts += _judged_parts(nutrient.get("eaten_vs_target") or {}, unit)
        planned = nutrient.get("planned") or {}
        if planned.get("value"):
            parts.append(f"{fmt(planned['value'])} {unit} planned".replace("  ", " "))
        rows.append({"label": str(nutrient.get("name") or ""), "value": amount_text(eaten, unit),
                     "detail": " · ".join(p for p in parts if p)})
    day = str(result.get("date") or "")
    return {"title": "Today so far" if result.get("is_today") else f"The day {day}", "rows": rows}


def totals_rows(totals: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The shown nutrients of a totals object (``{key: {"value", "not_listed_by"}}``) as screen rows; unknown is unknown."""
    rows = []
    for key in SHOWN_NUTRIENTS:
        meta = NUTRIENT_BY_KEY.get(key)
        amount = totals.get(key)
        if meta is None or not isinstance(amount, Mapping):
            continue
        if amount.get("value") is None and not amount.get("not_listed_by"):
            continue
        rows.append({"label": meta.label, "value": amount_text(amount, meta.unit), "detail": ""})
    return rows


def _meal_groups(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = []
    totals = result.get("totals")
    if isinstance(totals, Mapping):
        groups.append({"title": "This meal", "rows": totals_rows(totals)})
    day = result.get("day_with_these_items")
    if isinstance(day, Mapping):
        rows = []
        for nutrient in day.values():
            if not isinstance(nutrient, Mapping) or not isinstance(nutrient.get("target"), Mapping):
                continue
            unit = str(nutrient.get("unit") or "")
            parts = [target_text(nutrient["target"], unit)] + _judged_parts(nutrient, unit)
            rows.append({"label": str(nutrient.get("name") or ""), "value": amount_text(nutrient.get("total"), unit),
                         "detail": " · ".join(p for p in parts if p)})
        groups.append({"title": "The day with this meal", "rows": rows})
    return groups


def _foods_group(result: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for food in list(result.get("results") or [])[:MAX_FOODS_SHOWN]:
        if not isinstance(food, Mapping):
            continue
        per = food.get("nutrients_per_serving") or {}
        serving = food.get("serving") or {}
        parts = []
        for key in ("potassium_mg", "phosphorus_mg", "sodium_mg"):
            meta = NUTRIENT_BY_KEY.get(key)
            if meta is not None:
                value = per.get(key)
                parts.append(f"{meta.label.lower()} {fmt(value)} {meta.unit}" if value is not None else f"{meta.label.lower()} not listed")
        name = str(food.get("name") or "")
        brand = food.get("brand")
        rows.append({"label": f"{name} ({brand})" if brand else name, "value": str(serving.get("description") or ""),
                     "detail": " · ".join(parts) + " per serving"})
    return {"title": "Foods found", "rows": rows}


def numbers_view(runs: Sequence["ToolRun"]) -> list[dict[str, Any]]:
    """What this message's tools returned, for the screen: the day's figures, a checked meal and the day with it, and
    foods found. One group per look-up (the latest of each kind of look-up for the same day or search), at most
    :data:`MAX_NUMBER_GROUPS`, formatted here so the screen shows the app's own words."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        if run.result is None:
            continue
        if run.tool == "get_today":
            groups[("get_today", str(run.result.get("date")))] = [_today_group(run.result)]
        elif run.tool == "check_meal":
            groups[("check_meal", str(run.result.get("date")))] = _meal_groups(run.result)
        elif run.tool == "log_food" and isinstance(run.result.get("day"), Mapping):  # after a save: the day as it is now
            groups[("get_today", str(run.result["day"].get("date")))] = [_today_group(run.result["day"])]
        elif run.tool == "search_foods":
            groups[("search_foods", str(run.result.get("query")))] = [_foods_group(run.result)]
    flat = [g for value in groups.values() for g in value if g["rows"]]
    return flat[-MAX_NUMBER_GROUPS:]


# --------------------------------------------------------------------------- #
# Rule-based answers (no model call)
# --------------------------------------------------------------------------- #


def safety_outcome(result: Mapping[str, Any]) -> tuple[str, str, list[dict[str, Any]]] | None:
    """``(kind, text, cards)`` from the ``safety_check`` tool's result, or ``None`` when no rule matched. Emergency
    wording gives ``get_help_now``; a message with low wording also keeps the Treating a low card."""
    action = result.get("action")
    if action not in ("get_help_now", "treat_low_first"):
        return None
    cards = [{k: v for k, v in card.items() if k != "full_url"} for card in result.get("cards") or []]
    if action == "get_help_now":
        return "get_help_now", GET_HELP_TEXT, cards
    return "treat_low", TREAT_LOW_TEXT, cards


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


@dataclass
class ToolRun:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None  # None when the tool did not run or failed
    error: str | None = None


@dataclass
class Outcome:
    kind: str  # answer | withheld | unfinished | error | confirm_save
    text: str | None
    notes: list[str] = field(default_factory=list)
    runs: list[ToolRun] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    reason: str | None = None  # a code for the activity log: why withheld, unfinished or failed
    error: str | None = None  # a provider error category (app.ai.routes.ERROR_TEXT), kind "error" only
    refused: bool = False
    audit_id: int | None = None
    pending: dict[str, Any] | None = None  # ask mode: the save the person is asked to confirm (kind "confirm_save")
    saves: list[dict[str, Any]] = field(default_factory=list)  # trusted mode: what was saved (each with its undo)
    questions: list[dict[str, Any]] = field(default_factory=list)  # what the app could not place, in its own words
    save_calls: int = 0


@dataclass
class SaveStep:
    """What :func:`converse` gets back from ``run_save`` for one save call of the model. ``result`` is the tool's
    answer for the model (or ``error``, a short message for it). ``pending``: ask mode, nothing was saved, this is
    the card to confirm: the loop ends. ``saved``: trusted mode, what was saved. ``questions``: what could not be
    placed (``[]`` clears earlier ones)."""

    result: dict[str, Any] | None = None
    error: str | None = None
    pending: dict[str, Any] | None = None
    saved: dict[str, Any] | None = None
    questions: list[dict[str, Any]] | None = None
    closes: bool = False  # a repeat of an earlier save: no further save in this message


class StopLoop(Exception):
    """Raised by the model-call callback when the loop must end now (the quota ran out after the first call)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


Complete = Callable[[dict[str, Any], int], Awaitable[CallResult]]
RunTool = Callable[[str, dict[str, Any]], Awaitable[tuple[dict[str, Any] | None, str | None]]]
Record = Callable[[CallResult, dict[str, Any]], Awaitable[int]]
RunSave = Callable[[str, dict[str, Any], int], Awaitable[SaveStep]]


async def converse(base_body: dict[str, Any], *, person_texts: Sequence[str], newest: str, complete: Complete,
                   run_tool: RunTool, record: Record, fits: Callable[[dict[str, Any]], bool],
                   run_save: RunSave | None = None) -> Outcome:
    """Run the step protocol for one message from the person.

    ``complete(body, index)`` makes one model call (the route takes the quota first); ``run_tool(name, arguments)``
    runs an allowed tool for this person and returns ``(result, error)``; ``record(call result, info)`` writes the
    activity row (``info``: step, tool, outcome; never message text) and returns its id. Each model call is
    validated as a :class:`~app.ai.schemas.ChatStep`. At most :data:`MAX_TOOL_CALLS` tools run; after the last
    result the model is told to answer, and a call after that ends the loop as ``unfinished``.

    ``run_save(name, arguments, n)`` handles the model's ``n``-th (1-based) call of a saving tool (at most
    :data:`MAX_SAVES` per message); without it the saving tools are not offered. A :class:`SaveStep` with ``pending``
    ends the loop at once with ``kind: "confirm_save"`` and the fixed :data:`CONFIRM_TEXT` (the model's words are
    not used: nothing was saved, and the card says exactly what would be)."""
    messages = list(base_body["messages"])
    runs: list[ToolRun] = []
    out = Outcome(kind="unfinished", text=UNFINISHED_TEXT, runs=runs)
    closed = False  # a repeat of an earlier save was answered: no more saves in this message

    def unfinished(reason: str) -> Outcome:
        out.reason = reason
        out.notes = [LAB_NOTE] if lab_words(newest) else []
        return out

    while True:
        body = {**base_body, "messages": list(messages)}
        index = out.model_calls
        if index > 0 and not fits(body):
            return unfinished("context")
        try:
            result = await complete(body, index)
        except StopLoop as stop:
            return unfinished(stop.reason)
        out.model_calls += 1
        if result.status != "ok":
            info = {"step": index, "tool": None, "outcome": result.status}
            out.audit_id = await record(result, info)
            out.kind, out.text, out.reason = "error", None, result.error or result.status
            out.error = result.error or result.status
            out.refused = result.status == "refused"
            out.notes = [LAB_NOTE] if lab_words(newest) else []
            return out
        step: schemas.ChatStep = result.parsed
        if step.answer is not None:
            verdict = check_answer(step.answer, [r.result for r in runs if r.result is not None], person_texts, newest)
            out.audit_id = await record(result, {"step": index, "tool": None, "outcome": verdict.kind, "reason": verdict.reason})
            out.kind, out.text, out.notes, out.reason = verdict.kind, verdict.text, verdict.notes, verdict.reason
            if verdict.kind == "error":
                out.error = "empty"
            return out
        assert step.call is not None
        name, arguments = step.call.tool, step.call.arguments
        if out.tool_calls >= MAX_TOOL_CALLS:
            out.audit_id = await record(result, {"step": index, "tool": None, "outcome": "unfinished", "reason": "step_limit"})
            return unfinished("step_limit")
        out.tool_calls += 1
        left = MAX_TOOL_CALLS - out.tool_calls
        run = ToolRun(tool=name, arguments=arguments)
        offered = OFFERED_TOOLS if run_save is not None else CHAT_TOOLS
        saving = name in SAVE_TOOLS and run_save is not None
        if name not in offered:
            run.error = prompts.CHAT_UNKNOWN_TOOL.format(name=prompts.clean(name, 40), names=", ".join(offered))
        elif saving:
            assert run_save is not None
            if out.save_calls >= MAX_SAVES:
                run.error = SAVE_LIMIT_ERROR
            elif closed:
                run.error = SAVES_CLOSED_ERROR
            else:
                out.save_calls += 1
                taken = await run_save(name, arguments, out.save_calls)
                run.result, run.error = taken.result, taken.error
                closed = closed or taken.closes
                if taken.saved is not None:
                    out.saves.append(taken.saved)
                if taken.questions is not None:
                    out.questions = taken.questions
                if taken.pending is not None:  # ask mode: nothing saved; the person confirms on the card
                    run.result = None
                    runs.append(run)
                    out.pending = taken.pending
                    out.audit_id = await record(result, {"step": index, "tool": name, "outcome": "confirm_save"})
                    out.kind, out.text, out.reason = "confirm_save", CONFIRM_TEXT, None
                    out.notes = [LAB_NOTE] if lab_words(newest) else []
                    return out
        else:
            run.result, run.error = await run_tool(name, arguments)
        runs.append(run)
        out.audit_id = await record(result, {"step": index, "tool": name if name in offered else "unknown", "outcome": "call",
                                             "tool_ok": run.result is not None})
        messages.append(step_message(step))
        messages.append(tool_result_message(name, run.result, left) if run.result is not None
                        else tool_error_message(name, run.error or prompts.CHAT_TOOL_FAILED, left))
