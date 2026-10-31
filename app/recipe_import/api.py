"""``/api/recipe-import``: a recipe from a web page or from pasted ingredients (design note 30 §3, §5).

* ``GET /api/recipe-import``: always ``200``; whether pages can be read here (``recipes.import_enabled``) and the limits.
* ``POST /api/recipe-import/page`` ``{url}``: the server reads the page (:mod:`.fetch`), takes its schema.org ``Recipe`` data
  (:mod:`.parse`) and returns a draft. ``404`` while the switch is off; at most 20 pages an hour per person.
* ``POST /api/recipe-import/text`` ``{text, name?, servings?}``: the same draft from pasted ingredient lines; no network.

A draft is never saved here: each ingredient line comes back with up to three foods from the person's own food search and the
servings worked out from the line's amount, or ``null`` when the food's serving does not allow it (never a guess, never 0). The
person checks every line, then saves with the ordinary ``POST /api/meals``, where every rule of saved meals runs again. The page
itself is never stored.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth.context import auth_context
from ..auth.deps import CurrentUser
from ..auth.errors import ApiProblem
from ..auth.ratelimit import register_limit
from ..db import get_db
from ..foods import search_foods
from ..models import MAX_RECIPE_SERVINGS, Number, SOURCE_URL_MAX
from . import parse as P
from .fetch import MESSAGES, PageError, RecipeFetcher, check_page_url

router = APIRouter(prefix="/api/recipe-import", tags=["recipes"])

SWITCH = "recipes.import_enabled"
MATCHES_PER_LINE = 3
MAX_PASTE_CHARS = 20_000
PAGES_PER_HOUR = 20
register_limit("recipe_page", PAGES_PER_HOUR, 3600, "You have read many recipe pages this hour. Try again later, or paste the ingredients.")

CHECK_TEXT = "Check each food the app chose, and fix it if it is wrong. Nothing is saved until you press Save."
ESTIMATE_TEXT = ("These numbers are estimates. Recipe sites rarely list potassium or phosphorus, so the app works them out from its "
                 "own food list. Cooking, soaking and draining change what ends up on the plate, and the app does not count that.")
NO_RECIPE_TEXT = "This page has no recipe data the app can read. Paste the ingredients instead."
NO_LINES_TEXT = "No ingredient lines were found. Paste one ingredient on each line."
FOOD_KEYS = ("id", "name", "brand", "category", "source", "serving_desc", "serving_g", "nutrients", "flags", "warnings",
             "kidney_rating", "hidden")


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class PageIn(BaseModel):
    url: str = Field(min_length=1, max_length=SOURCE_URL_MAX)


class TextIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_PASTE_CHARS)
    name: str | None = Field(default=None, max_length=P.MAX_NAME_CHARS)
    servings: float | None = Field(default=None, gt=0, le=MAX_RECIPE_SERVINGS, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def _empty_name(cls, v: str | None) -> str | None:
        return v or None


class MatchFood(BaseModel):
    id: int
    name: str
    brand: str | None = None
    category: str | None = None
    source: str
    serving_desc: str
    serving_g: Number
    nutrients: dict[str, Number | None]
    flags: list[str]
    warnings: list[dict[str, Any]]
    kidney_rating: str
    hidden: bool


class Match(BaseModel):
    food: MatchFood
    servings: Number | None  # null: the amount cannot be worked out for this food; the person types it


class Line(BaseModel):
    text: str
    amount: Number | None
    unit: str | None
    food_text: str
    note: str | None
    matches: list[Match]


class Draft(BaseModel):
    name: str | None
    servings_made: Number | None
    steps: list[str]
    steps_cut: bool  # the page had more than 20 steps; the rest were left out
    lines_cut: bool  # more than 60 ingredient lines; the rest were left out
    source_url: str | None
    lines: list[Line]
    notice: str
    estimate: str


class ImportInfo(BaseModel):
    web: bool  # the server reads recipe pages (RECIPE_IMPORT_ENABLED)
    max_lines: int
    estimate: str


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def web_enabled(request: Request, conn: sqlite3.Connection) -> bool:
    return bool(auth_context(request).store.get(conn, SWITCH))


def fetcher_of(request: Request) -> RecipeFetcher:
    fetcher = getattr(request.app.state, "recipe_fetcher", None)
    if fetcher is None:
        fetcher = request.app.state.recipe_fetcher = RecipeFetcher()
    return fetcher


def match_line(conn: sqlite3.Connection, user_id: int, parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to three foods for one ingredient line: the first of :func:`parse.search_terms` that finds any, the person's own food
    search (visible foods only)."""
    for query in P.search_terms(parsed["food_text"]):
        foods = search_foods(conn, user_id, query, limit=MATCHES_PER_LINE)
        if foods:
            return [{"food": {k: f.get(k) for k in FOOD_KEYS},
                     "servings": P.recipe_servings(parsed["amount"], parsed["unit"], f["serving_desc"], f["serving_g"])}
                    for f in foods]
    return []


def draft(conn: sqlite3.Connection, user_id: int, recipe: dict[str, Any], source_url: str | None) -> dict[str, Any]:
    lines = []
    for text in recipe["lines"]:
        parsed = P.parse_line(text)
        if not parsed["text"]:
            continue
        lines.append({**parsed, "matches": match_line(conn, user_id, parsed)})
    if not lines:
        raise ApiProblem(422, NO_LINES_TEXT, code="no_lines")
    return {"name": recipe.get("name"), "servings_made": recipe.get("servings_made"), "steps": recipe.get("steps") or [],
            "steps_cut": bool(recipe.get("steps_cut")), "lines_cut": bool(recipe.get("lines_cut")), "source_url": source_url,
            "lines": lines, "notice": CHECK_TEXT, "estimate": ESTIMATE_TEXT}


def is_heading(line: str) -> bool:
    """"For the sauce:" is a heading, not an ingredient."""
    return line.endswith(":") and not any(ch.isdigit() for ch in line)


def lines_of_text(text: str) -> tuple[list[str], bool]:
    lines = [P.normalise_line(raw)[:P.MAX_LINE_CHARS] for raw in text.splitlines()]
    lines = [line for line in lines if line and not is_heading(line)]
    return lines[:P.MAX_LINES], len(lines) > P.MAX_LINES


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("", response_model=ImportInfo)
def info(request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"web": web_enabled(request, conn), "max_lines": P.MAX_LINES, "estimate": ESTIMATE_TEXT}


@router.post("/page", response_model=Draft)
def from_page(body: PageIn, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    if not web_enabled(request, conn):
        raise HTTPException(status_code=404, detail="Not Found")
    url = body.url.strip()
    try:
        check_page_url(url)
    except PageError as exc:
        raise ApiProblem(400, MESSAGES[exc.code], code=exc.code) from None
    auth_context(request).limits.take("recipe_page", user.id)
    if conn.in_transaction:
        conn.commit()  # no write is held open while the page loads
    try:
        page = fetcher_of(request).fetch(url)
    except PageError as exc:
        raise ApiProblem(422, MESSAGES[exc.code], code=exc.code) from None
    recipe = None
    for block in P.ld_json_blocks(page):
        recipe = P.find_recipe(block)
        if recipe is not None:
            break
    del page  # never kept
    if recipe is None:
        raise ApiProblem(422, NO_RECIPE_TEXT, code="no_recipe")
    return draft(conn, user.id, P.recipe_from_jsonld(recipe), url)


@router.post("/text", response_model=Draft)
def from_text(body: TextIn, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    lines, cut = lines_of_text(body.text)
    recipe = {"name": body.name, "servings_made": body.servings, "steps": [], "steps_cut": False, "lines": lines, "lines_cut": cut}
    return draft(conn, user.id, recipe, None)
