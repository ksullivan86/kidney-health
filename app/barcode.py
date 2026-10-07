"""``POST /api/foods/barcode``: a barcode becomes a food (note 03 R1, R4, R6, §9).

The phone decodes the barcode and sends only the digits. The lookup, in order:

1. **Normalise and classify** (:mod:`app.gtin`): a bad check digit, an in-store code for weighed food,
   a book, magazine or coupon answers 400 before anything else happens.
2. **The person's own data**: their own custom food with that barcode, then a shared Open Food Facts or
   USDA food they already scanned or imported. Answered as is (``refresh`` asks the providers again).
3. **Providers**, after the per-person limit (60 lookups an hour):

   * **Open Food Facts**, only when the admin turned it on (``food.off_enabled``, off by default) **and**
     the person agreed (``food.off_consent``). The instance-wide cache (``barcode_cache``) answers
     first; a found product is kept until a refresh (at most once per product per day), a miss for
     ``food.barcode_negative_ttl_hours``. A real request takes a token from the server-wide bucket
     (``food.off_rate_per_minute``); an empty bucket is a 429, never a silent queue.
   * **USDA FoodData Central Branded**, when a USDA key is available to the person
     (``food.usda_branded_barcode``) and Open Food Facts has no answer, has no nutrition facts, or lacks
     potassium or sodium for a US-labelled product. Up to three searches (12, 13 and 14 digits), an
     exact ``gtinUpc`` match, then the record (note 03 R4).
   * **Merge** when both answered: nutrients from USDA for US labels (manufacturer data), from Open Food
     Facts otherwise; a missing value is filled from the other source and says so; the flags are the
     union of both ingredient scans.

4. The result is stored as **one shared, read-only row** (an ``off`` row per barcode, or the ``usda``
   row of the record), linked to the person so it appears in their food search, and answered with
   its attribution.

**Privacy** (note 03 §9 B7, B8): a found product is always ``200`` whether it came from the cache or
not (no "someone else scanned this" signal); shared rows and cached products are given to a person
only when they could have fetched them themselves at that moment (provider on and usable for them)
or already have them; nobody else's custom food is ever matched. Which products a person scanned is
their ``user_food_links`` row; the cache holds only product data. What remains is a timing difference
between a cache hit and an upstream call, documented as accepted.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import weakref
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, Mapping

import httpx2
from fastapi import APIRouter, Depends, Request

from . import credentials, foods, off
from .auth import clock
from .auth.deps import CurrentUser, current_user
from .auth.errors import ApiProblem
from .auth.ratelimit import register_limit
from .db import get_db
from .foods import Provenance, UsdaError, UsdaMapped
from .gtin import GtinError, classify, normalize, off_code
from .models import BarcodeLookup, BarcodeResult
from .nutrients import NUTRIENT_KEYS

log = logging.getLogger("kidney_health.barcode")
router = APIRouter(prefix="/api/foods", tags=["barcode"], dependencies=[Depends(current_user)])

REFRESH_AFTER = timedelta(hours=24)  # a found product is asked again at most once a day (note 03 R3)
PURGE_EVERY = timedelta(hours=24)  # negative cache rows past their TTL are purged daily (§9 B11)
LOOKUPS_PER_HOUR = 60  # per person (note 03 R3)
MERGED_LICENSE = "CC0-1.0 AND ODbL-1.0"

register_limit(
    "barcode", LOOKUPS_PER_HOUR, 3600,
    "Too many barcode lookups this hour. Try again later, or enter the food from its label.",
)

CLASS_MESSAGES: dict[str, str] = {
    "restricted": "This is a store barcode for a weighed or in-store item (deli, meat, produce). It is only unique "
                  "inside one shop, so it is not looked up. Enter the food from its label instead.",
    "isbn": "This is a book's barcode (ISBN), not a food.",
    "issn": "This is a magazine's barcode (ISSN), not a food.",
    "coupon": "This is a coupon or receipt barcode, not a food.",
    "reserved": "This barcode uses a number range that is not given to products.",
}
NOT_FOUND = "No product with this barcode in {where}. Enter it from the label; the app keeps the barcode for next time."
SOURCE_NAMES = {"off": "Open Food Facts", "usda": "USDA FoodData Central"}
NO_NUTRITION = "Open Food Facts knows this product but has no nutrition facts for it. Enter them from the label."
NO_SERVING_WEIGHT = ("Open Food Facts lists this product's values per serving but not how much a serving weighs, so they "
                     "cannot be used. Enter them from the label.")
UNREACHABLE = "The food databases could not be reached just now. Try again in a minute, or enter the food from its label."
LOOKUPS_OFF = ("Barcode lookups are switched off on this server. Enter the food from its label, or ask your admin to "
               "turn on Open Food Facts lookups in Settings.")
CONSENT_REQUIRED = ("To look this barcode up, turn on “Send barcodes I scan to Open Food Facts” in Settings → "
                    "Food data. Or enter the food from its label.")


# --------------------------------------------------------------------------- #
# Hooks (tests replace them) and per-app state
# --------------------------------------------------------------------------- #


def off_transport() -> httpx2.BaseTransport | None:
    """The transport for Open Food Facts requests; ``None`` = the SSRF-checked network transport."""
    return None


def sleep(seconds: float) -> None:
    """Wait before the single retry after an Open Food Facts 503 (tests make it instant)."""
    time.sleep(seconds)


class Runtime:
    """Per-app state: the server-wide token bucket, per-barcode locks, the last purge."""

    def __init__(self, rate_per_minute: int) -> None:
        self.bucket = off.TokenBucket(rate_per_minute)
        self.last_purge: float = 0.0
        self._locks: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
        self._guard = threading.Lock()

    def lock_for(self, gtin14: str) -> threading.Lock:
        """One lock per barcode: two people scanning the same new product share one upstream call."""
        with self._guard:
            lock = self._locks.get(gtin14)
            if lock is None:
                lock = threading.Lock()
                self._locks[gtin14] = lock
            return lock


_runtime_guard = threading.Lock()


def runtime(request: Request, rate_per_minute: int) -> Runtime:
    with _runtime_guard:
        state = getattr(request.app.state, "barcode", None)
        if state is None:
            state = request.app.state.barcode = Runtime(rate_per_minute)
    if state.bucket.rate != rate_per_minute:
        state.bucket.set_rate(rate_per_minute)
    return state


# --------------------------------------------------------------------------- #
# The cache
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CacheRow:
    status: Literal["found", "not_found", "no_nutrition"]
    payload: dict[str, Any] | None
    fetched_at: str

    def age(self) -> timedelta:
        fetched = clock.parse(self.fetched_at)
        return clock.now() - fetched if fetched else timedelta.max


def cache_get(conn: sqlite3.Connection, gtin14: str, provider: str) -> CacheRow | None:
    row = conn.execute(
        "SELECT status, payload_json, fetched_at FROM barcode_cache WHERE gtin = ? AND provider = ?", (gtin14, provider)
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else None
    except json.JSONDecodeError:
        log.warning("barcode cache row for a %s product is unreadable; asking again", provider)
        return None
    return CacheRow(row["status"], payload if isinstance(payload, dict) else None, row["fetched_at"])


def cache_put(conn: sqlite3.Connection, gtin14: str, provider: str, status: str, payload: Mapping[str, Any] | None) -> str:
    fetched_at = clock.now_iso()
    conn.execute(
        """INSERT INTO barcode_cache (gtin, provider, status, payload_json, fetched_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (gtin, provider) DO UPDATE SET status = excluded.status, payload_json = excluded.payload_json,
             fetched_at = excluded.fetched_at""",
        (gtin14, provider, status, json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload else None, fetched_at),
    )
    return fetched_at


def purge_negative(conn: sqlite3.Connection, ttl_hours: int) -> int:
    """Delete ``not_found`` / ``no_nutrition`` rows older than the TTL (note 03 §9 B11); returns the count."""
    cutoff = clock.iso(clock.now() - timedelta(hours=ttl_hours))
    cur = conn.execute("DELETE FROM barcode_cache WHERE status != 'found' AND fetched_at < ?", (cutoff,))
    return cur.rowcount or 0


def _maybe_purge(conn: sqlite3.Connection, rt: Runtime, ttl_hours: int) -> None:
    now = clock.seconds()
    if now - rt.last_purge < PURGE_EVERY.total_seconds():
        return
    rt.last_purge = now
    removed = purge_negative(conn, ttl_hours)
    conn.commit()
    if removed:
        log.info("barcode cache: removed %d expired 'not found' entries", removed)


# --------------------------------------------------------------------------- #
# Provider steps
# --------------------------------------------------------------------------- #

OffStatus = Literal["found", "no_nutrition", "not_found", "disabled", "consent_required", "paced", "error"]
UsdaStatus = Literal["found", "not_found", "skipped", "disabled", "unavailable", "paced", "error"]


@dataclass
class OffOutcome:
    status: OffStatus
    mapped: off.Mapped | None = None
    fetched_at: str | None = None
    retry_after: int = 0


@dataclass
class UsdaOutcome:
    status: UsdaStatus
    fdc_id: int | None = None
    mapped: UsdaMapped | None = None
    fetched_at: str | None = None
    reason: str | None = None  # why USDA was unavailable (credential reasons) or the error detail
    retry_after: int = 0


def _off_status_of(mapped: off.Mapped) -> OffStatus:
    return "no_nutrition" if mapped.status == "no_nutrition" else "found"


def off_step(conn: sqlite3.Connection, ctx: "Ctx", gtin14: str) -> OffOutcome:
    if not ctx.off_enabled:
        return OffOutcome("disabled")
    if not ctx.off_consent:
        return OffOutcome("consent_required")
    cached = cache_get(conn, gtin14, "off")
    if cached is not None:
        may_refresh = ctx.refresh and cached.age() >= REFRESH_AFTER  # at most once a day per product
        if cached.status == "found" and cached.payload is not None and not may_refresh:
            mapped = off.map_product(cached.payload, gtin14)
            return OffOutcome(_off_status_of(mapped), mapped, cached.fetched_at)
        negative_fresh = cached.status != "found" and cached.age() < timedelta(hours=ctx.negative_ttl_hours)
        if negative_fresh and not may_refresh:
            if cached.status == "no_nutrition" and cached.payload:
                return OffOutcome("no_nutrition", off.map_product(cached.payload, gtin14), cached.fetched_at)
            return OffOutcome("not_found", fetched_at=cached.fetched_at)
    wait = ctx.runtime.bucket.take()
    if wait:
        return OffOutcome("paced", retry_after=wait)
    client = off.OffClient(
        ctx.off_base_url, ctx.app_version, ctx.off_contact, transport=off_transport(),
        allow_private=ctx.off_base_url.rstrip("/") != off.DEFAULT_BASE_URL, sleep=sleep,
    )
    try:
        result = client.fetch(off_code(gtin14))
    except off.OffError as exc:
        log.warning("Open Food Facts lookup failed: %s", exc.kind)
        if exc.kind == "rate_limited":
            ctx.runtime.bucket.pause(off.UPSTREAM_PAUSE_S)
            return OffOutcome("paced", retry_after=off.UPSTREAM_PAUSE_S)
        return OffOutcome("error")
    if result.status == "not_found":
        fetched_at = cache_put(conn, gtin14, "off", "not_found", None)
        return OffOutcome("not_found", fetched_at=fetched_at)
    trimmed = off.trim_product(result.product or {})
    mapped = off.map_product(trimmed, gtin14)
    fetched_at = cache_put(conn, gtin14, "off", mapped.status, trimmed)
    return OffOutcome(_off_status_of(mapped), mapped, fetched_at)


def usda_needed(off_outcome: OffOutcome) -> bool:
    """Note 03 R4: OFF missed, has no nutrition facts, or lacks potassium or sodium on a US label."""
    if off_outcome.status != "found" or off_outcome.mapped is None:
        return True
    m = off_outcome.mapped
    lacks = m.nutrients.get("potassium_mg") is None or m.nutrients.get("sodium_mg") is None
    return lacks and (m.us_label or not m.country_known)


def usda_unavailable_reason(conn: sqlite3.Connection, request: Request, user: Any) -> str | None:
    """Why this person has no USDA key to use, without counting a request (``None`` = a key is there)."""
    auth = request.app.state.auth
    store = auth.store
    keyring = auth.require_keyring()
    if store.get(conn, "providers.usda.user_keys_allowed"):
        own = credentials.secret_status(conn, keyring, "usda", owner_user_id=user.id)
        if own.get("set"):
            return "own_key_unreadable" if own.get("status") == "unreadable" else None
    shared = credentials.shared_status(conn, keyring, request.app.state.settings, "usda")
    if not shared.get("set") or shared.get("status") == "unreadable":
        return "not_configured"
    if not user.can_use_shared or not store.get(conn, "providers.usda.shared_enabled"):
        return "not_allowed"
    return None


def _trim_usda_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The cached copy of a FoodData Central record: only what :func:`app.foods.map_usda_record` reads."""
    keep = ("description", "brandOwner", "brandName", "foodCategory", "brandedFoodCategory", "gtinUpc", "ingredients",
            "servingSize", "servingSizeUnit", "householdServingFullText", "labelNutrients", "foodPortions", "dataType")
    out = {k: record[k] for k in keep if k in record}
    nutrients = []
    for item in record.get("foodNutrients") or []:
        if not isinstance(item, Mapping):
            continue
        nutrient = item.get("nutrient") if isinstance(item.get("nutrient"), Mapping) else {}
        numbers = {str(nutrient.get("number") or ""), str(nutrient.get("id") or ""), str(item.get("nutrientNumber") or ""),
                   str(item.get("nutrientId") or "")}
        if numbers & set(foods.USDA_NUTRIENT_NUMBERS):
            nutrients.append({"nutrient": {"number": nutrient.get("number"), "id": nutrient.get("id")},
                              "nutrientNumber": item.get("nutrientNumber"), "nutrientId": item.get("nutrientId"),
                              "amount": item.get("amount", item.get("value"))})
    out["foodNutrients"] = nutrients
    return out


def _cached_fdc_id(cached: CacheRow) -> int | None:
    """The FoodData Central id of a cached ``found`` record, or ``None`` when the row is unusable."""
    try:
        fdc_id = int((cached.payload or {}).get("fdc_id") or 0)
    except (TypeError, ValueError):
        return None
    return fdc_id if 0 < fdc_id < 2**63 and isinstance((cached.payload or {}).get("record"), dict) else None


def usda_step(conn: sqlite3.Connection, ctx: "Ctx", gtin14: str) -> UsdaOutcome:
    if not ctx.usda_branded:
        return UsdaOutcome("disabled")
    reason = usda_unavailable_reason(conn, ctx.request, ctx.user)
    if reason is not None:
        return UsdaOutcome("unavailable", reason=reason)
    cached = cache_get(conn, gtin14, "usda")
    if cached is not None:
        stale = ctx.refresh and cached.age() >= REFRESH_AFTER
        fdc_id = _cached_fdc_id(cached)
        if cached.status == "found" and fdc_id and not stale:
            record = cached.payload.get("record") or {}  # type: ignore[union-attr]
            return UsdaOutcome("found", fdc_id, foods.map_usda_record(record, fdc_id), cached.fetched_at)
        if cached.status == "not_found" and cached.age() < timedelta(hours=ctx.negative_ttl_hours) and not stale:
            return UsdaOutcome("not_found", fetched_at=cached.fetched_at)
    try:
        cred = foods.usda_credential(ctx.request, conn, ctx.user.id, ctx.user.can_use_shared)
    except ApiProblem as exc:
        if exc.status == 429:
            return UsdaOutcome("paced", reason="paused", retry_after=int(exc.headers.get("Retry-After", "60")))
        return UsdaOutcome("unavailable", reason=str(exc.extra.get("reason") or "not_configured"))
    try:
        hit = foods.usda_find_by_gtin(gtin14, cred.api_key, guard=foods.guard_id(cred, ctx.user.id), own_key=cred.scope == "own")
    except UsdaError as exc:
        log.warning("USDA branded lookup failed: HTTP %d", exc.status)
        if exc.status == 429:
            return UsdaOutcome("paced", reason="rate_limited", retry_after=3600)
        if exc.status == 503:
            return UsdaOutcome("unavailable", reason="rejected")
        return UsdaOutcome("error", reason="error")
    if hit is None:
        fetched_at = cache_put(conn, gtin14, "usda", "not_found", None)
        return UsdaOutcome("not_found", fetched_at=fetched_at)
    fdc_id, record = hit
    trimmed = _trim_usda_record(record)
    fetched_at = cache_put(conn, gtin14, "usda", "found", {"fdc_id": fdc_id, "record": trimmed})
    return UsdaOutcome("found", fdc_id, foods.map_usda_record(trimmed, fdc_id), fetched_at)


# --------------------------------------------------------------------------- #
# Merge (pure)
# --------------------------------------------------------------------------- #


@dataclass
class Assembled:
    """The food to store: which shared row, its values and provenance, and the attributions."""

    source: Literal["off", "usda"]
    kwargs: dict[str, Any]
    provenance: Provenance
    fdc_id: int | None = None
    attributions: list[dict[str, str]] = field(default_factory=list)


def off_attribution(gtin14: str) -> dict[str, str]:
    return {"text": off.ATTRIBUTION_TEXT, "url": off.product_page(gtin14), "license": off.LICENSE}


def usda_attribution() -> dict[str, str]:
    return {"text": foods.USDA_ATTRIBUTION_TEXT, "url": foods.USDA_HOME_URL, "license": foods.USDA_LICENSE}


def _unknown_codes(nutrients: Mapping[str, Any]) -> list[str]:
    return [k.split("_")[0] + "_unknown" for k in ("potassium_mg", "phosphorus_mg") if nutrients.get(k) is None]


def assemble(gtin14: str, off_outcome: OffOutcome, usda_outcome: UsdaOutcome) -> Assembled | None:
    """Combine the provider answers (note 03 R4). ``None`` when neither has a usable product."""
    om = off_outcome.mapped if off_outcome.status == "found" else None
    um = usda_outcome.mapped if usda_outcome.status == "found" else None
    if om is None and um is None:
        return None
    if um is None:
        assert om is not None
        return Assembled(
            "off", om.food_kwargs(),
            Provenance(gtin=gtin14, source_url=off.product_page(gtin14), source_license=off.LICENSE,
                       retrieved_at=off_outcome.fetched_at, ingredients_text=om.ingredients_text,
                       additives=tuple(om.additives), quality=tuple(om.quality)),
            attributions=[off_attribution(gtin14)],
        )
    if om is None:
        return Assembled(
            "usda", dict(um.kwargs),
            Provenance(gtin=gtin14, source_url=foods.USDA_HOME_URL, source_license=foods.USDA_LICENSE,
                       retrieved_at=usda_outcome.fetched_at, ingredients_text=um.ingredients_text,
                       additives=tuple(um.additives), quality=tuple(um.quality)),
            fdc_id=usda_outcome.fdc_id, attributions=[usda_attribution()],
        )

    usda_primary = om.us_label or not om.country_known
    primary, other = (dict(um.kwargs), om.food_kwargs()) if usda_primary else (om.food_kwargs(), dict(um.kwargs))
    other_name = "off" if usda_primary else "usda"
    primary_quality = [q for q in (um.quality if usda_primary else om.quality) if not q.endswith("_unknown")]
    nutrients = dict(primary["nutrients"])
    other_nutrients = other["nutrients"]
    fills: list[str] = []
    # Values are per serving of each source's own serving; fill through per-gram values, and never mix
    # "as prepared" values with "as sold" ones.
    prepared = "prepared_values" in om.quality
    if not prepared and primary["serving_g"] > 0 and other["serving_g"] > 0:
        ratio = primary["serving_g"] / other["serving_g"]
        for key in NUTRIENT_KEYS:
            if key == "fluid_ml":
                continue
            if nutrients.get(key) is None and other_nutrients.get(key) is not None:
                nutrients[key] = other_nutrients[key] * ratio
                fills.append(f"filled_from_{other_name}:{key}")
    flags = list(dict.fromkeys([*primary["flags"], *other["flags"]]))
    nutrients["fluid_ml"] = (nutrients.get("fluid_ml") or primary["serving_g"]) if "counts_as_fluid" in flags else 0.0
    notes = [n for n in (primary.get("kidney_notes"), other.get("kidney_notes")) if n]
    avoid = next((n for n in notes if n.startswith("AVOID")), None)
    kidney_notes = avoid or (notes[0] if notes else None)
    quality = primary_quality + fills
    if usda_primary and fills:
        quality.insert(0, "crowd_sourced")  # some values are Open Food Facts community data
    quality += _unknown_codes(nutrients)
    kwargs = {**primary, "nutrients": nutrients, "flags": flags, "kidney_notes": kidney_notes,
              "category": primary.get("category") or other.get("category"), "brand": primary.get("brand") or other.get("brand")}
    additives = list(dict.fromkeys([*(um.additives if usda_primary else om.additives), *(om.additives if usda_primary else um.additives)]))
    ingredients = (um.ingredients_text or om.ingredients_text) if usda_primary else (om.ingredients_text or um.ingredients_text)
    retrieved = max(filter(None, (off_outcome.fetched_at, usda_outcome.fetched_at)), default=None)
    attributions = [usda_attribution(), off_attribution(gtin14)] if usda_primary else [off_attribution(gtin14), usda_attribution()]
    return Assembled(
        "usda" if usda_primary else "off",
        kwargs,
        Provenance(gtin=gtin14, source_url=attributions[0]["url"], source_license=MERGED_LICENSE, retrieved_at=retrieved,
                   ingredients_text=ingredients, additives=tuple(additives), quality=tuple(dict.fromkeys(quality))),
        fdc_id=usda_outcome.fdc_id if usda_primary else None,
        attributions=attributions,
    )


# --------------------------------------------------------------------------- #
# Storing
# --------------------------------------------------------------------------- #


def store(conn: sqlite3.Connection, assembled: Assembled) -> int:
    """Upsert the one shared row: the ``off`` row for the barcode, or the ``usda`` row of the record."""
    if assembled.source == "usda":
        if not assembled.fdc_id:
            raise ValueError("a USDA product needs its FoodData Central id")
        return foods.upsert_usda_food(conn, assembled.fdc_id, assembled.kwargs, assembled.provenance)
    gtin14 = assembled.provenance.gtin
    existing = conn.execute("SELECT id FROM foods WHERE source = 'off' AND gtin = ?", (gtin14,)).fetchone()
    if existing is None:
        try:
            return foods.insert_food(conn, source="off", provenance=assembled.provenance, **assembled.kwargs)
        except sqlite3.IntegrityError:  # another request stored it a moment ago
            existing = conn.execute("SELECT id FROM foods WHERE source = 'off' AND gtin = ?", (gtin14,)).fetchone()
            if existing is None:
                raise
    foods.update_food_row(conn, existing["id"], hidden=False, provenance=assembled.provenance, **assembled.kwargs)
    return int(existing["id"])


# --------------------------------------------------------------------------- #
# The route
# --------------------------------------------------------------------------- #


@dataclass
class Ctx:
    request: Request
    user: Any
    runtime: Runtime
    off_enabled: bool
    off_consent: bool
    off_base_url: str
    off_contact: str
    app_version: str
    usda_branded: bool
    negative_ttl_hours: int
    refresh: bool


def _result(conn: sqlite3.Connection, food_id: int, gtin14: str, source: str, attributions: list[dict[str, str]]) -> dict[str, Any]:
    food = foods.row_to_food(foods.fetch_food(conn, food_id))
    return {"food": food, "gtin": gtin14, "source": source, "attribution": attributions[0] if attributions else None,
            "attributions": attributions, "quality": food["quality"]}


def _attributions_of_row(row: sqlite3.Row) -> list[dict[str, str]]:
    license_ = row["source_license"] or ""
    out: list[dict[str, str]] = []
    if "CC0-1.0" in license_ and row["source"] == "usda":
        out.append(usda_attribution())
    if "ODbL-1.0" in license_ and row["gtin"]:
        out.append(off_attribution(row["gtin"]))
    if "CC0-1.0" in license_ and row["source"] != "usda":
        out.append(usda_attribution())
    return out


def _local(conn: sqlite3.Connection, user_id: int, gtin14: str) -> tuple[sqlite3.Row | None, str]:
    """The person's own custom food with this barcode, else a shared food they already have (note 03 §9 B8)."""
    own = conn.execute(
        """SELECT * FROM foods WHERE source = 'custom' AND owner_user_id = ? AND gtin = ? AND hidden = 0
           ORDER BY updated_at DESC, id DESC LIMIT 1""",
        (int(user_id), gtin14),
    ).fetchone()
    if own is not None:
        return own, "local"
    linked = conn.execute(
        """SELECT f.* FROM foods f JOIN user_food_links l ON l.food_id = f.id AND l.user_id = ?
           WHERE f.gtin = ? AND f.source IN ('off', 'usda') AND f.owner_user_id IS NULL AND f.hidden = 0
           ORDER BY f.updated_at DESC, f.id DESC LIMIT 1""",
        (int(user_id), gtin14),
    ).fetchone()
    return (linked, linked["source"]) if linked is not None else (None, "")


def _checked(o: OffOutcome, u: UsdaOutcome) -> dict[str, str]:
    usda = u.reason if u.status == "unavailable" and u.reason else u.status
    return {"off": o.status, "usda": usda}


def not_found_message(checked: dict[str, str]) -> str:
    """The 404 sentence, naming only the databases that were really asked ("not found" from each)."""
    asked = [SOURCE_NAMES[k] for k in ("off", "usda") if checked.get(k) == "not_found"]
    return NOT_FOUND.format(where=" or ".join(asked) or "the food databases")


@router.post(
    "/barcode",
    response_model=BarcodeResult,
    responses={
        400: {"description": "Not a product barcode: reason check_digit | format | restricted | isbn | issn | coupon | reserved"},
        404: {"description": "Not found (or found without nutrition facts: name is set)"},
        429: {"description": "Lookup limits (per person, or the server-wide Open Food Facts budget); see Retry-After"},
        502: {"description": "A food database could not be reached or answered wrongly"},
        503: {"description": "No lookup source is switched on or usable for this person"},
    },
)
def lookup(body: BarcodeLookup, request: Request, user: CurrentUser, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    try:
        gtin14 = normalize(body.code, body.format)
    except GtinError as exc:
        raise ApiProblem(400, str(exc), reason=exc.reason) from None
    kind = classify(gtin14)
    if kind != "retail":
        raise ApiProblem(400, CLASS_MESSAGES[kind], reason=kind, gtin=gtin14)

    row, source = _local(conn, user.id, gtin14)
    if row is not None and (not body.refresh or source == "local"):
        return _result(conn, row["id"], gtin14, source, _attributions_of_row(row))

    request.app.state.auth.limits.take("barcode", user.id)
    store_ = request.app.state.settings_store
    rt = runtime(request, int(store_.get(conn, "food.off_rate_per_minute")))
    ttl = int(store_.get(conn, "food.barcode_negative_ttl_hours"))
    _maybe_purge(conn, rt, ttl)
    ctx = Ctx(
        request=request, user=user, runtime=rt,
        off_enabled=bool(store_.get(conn, "food.off_enabled")),
        off_consent=bool(store_.get(conn, "food.off_consent", user.id)),
        off_base_url=request.app.state.settings.off_base_url,
        off_contact=str(store_.get(conn, "food.off_contact")),
        app_version=request.app.version,
        usda_branded=bool(store_.get(conn, "food.usda_branded_barcode")),
        negative_ttl_hours=ttl,
        refresh=body.refresh,
    )
    with rt.lock_for(gtin14):
        off_outcome = off_step(conn, ctx, gtin14)
        usda_outcome = usda_step(conn, ctx, gtin14) if usda_needed(off_outcome) else UsdaOutcome("skipped")
        assembled = assemble(gtin14, off_outcome, usda_outcome)
        if assembled is not None:
            food_id = store(conn, assembled)
            foods.link_food(conn, user.id, food_id)
            conn.commit()
            return _result(conn, food_id, gtin14, assembled.source, assembled.attributions)
        conn.commit()  # the negative cache rows
    if row is not None:  # a refresh found nothing new: the food the person already has stands
        return _result(conn, row["id"], gtin14, source, _attributions_of_row(row))

    checked = _checked(off_outcome, usda_outcome)
    statuses = (off_outcome.status, usda_outcome.status)
    if "paced" in statuses:
        wait = max(off_outcome.retry_after, usda_outcome.retry_after, 1)
        raise ApiProblem(429, f"Too many barcode lookups on this server just now. Try again in {wait} seconds.",
                         headers={"Retry-After": str(wait)}, retry_after=wait, gtin=gtin14, checked=checked)
    if "error" in statuses:
        raise ApiProblem(502, UNREACHABLE, gtin=gtin14, checked=checked)
    asked = off_outcome.status in ("not_found", "no_nutrition") or usda_outcome.status == "not_found"
    if off_outcome.status == "consent_required":
        # Open Food Facts is on but this person has not agreed to it yet, and USDA (if usable) did not find the
        # product: offer Open Food Facts rather than claim it does not know the product (it was never asked).
        raise ApiProblem(503, CONSENT_REQUIRED, reason="off_consent_required", gtin=gtin14, checked=checked)
    if not asked:
        usda_reason = usda_outcome.reason if usda_outcome.status == "unavailable" else None
        if off_outcome.status == "disabled" and usda_reason in (None, "not_configured"):
            raise ApiProblem(503, LOOKUPS_OFF, reason="lookups_off", gtin=gtin14, checked=checked)
        detail = foods.USDA_UNAVAILABLE.get(usda_reason or "", LOOKUPS_OFF)
        raise ApiProblem(503, detail, reason=usda_reason or "lookups_off", gtin=gtin14, checked=checked)
    name = off_outcome.mapped.name if off_outcome.status == "no_nutrition" and off_outcome.mapped else None
    no_weight = name is not None and "serving_weight_unknown" in off_outcome.mapped.quality  # type: ignore[union-attr]
    raise ApiProblem(
        404, (NO_SERVING_WEIGHT if no_weight else NO_NUTRITION) if name else not_found_message(checked), gtin=gtin14,
        name=name, checked=checked,
        contribute_url=off.CONTRIBUTE_URL + off_code(gtin14),
    )


# --------------------------------------------------------------------------- #
# Maintenance (python -m app.admin remap-barcodes / purge-barcode-cache)
# --------------------------------------------------------------------------- #


def remap_cached(conn: sqlite3.Connection) -> dict[str, int]:
    """Re-run the current mapping over every cached product and update the shared rows, without the
    network (note 03 R3). Returns ``{"products": n, "updated": m}``. Commits."""
    gtins = [r["gtin"] for r in conn.execute("SELECT DISTINCT gtin FROM barcode_cache WHERE status != 'not_found' ORDER BY gtin")]
    updated = 0
    for gtin14 in gtins:
        off_row = cache_get(conn, gtin14, "off")
        usda_row = cache_get(conn, gtin14, "usda")
        off_outcome = OffOutcome("not_found")
        if off_row is not None and off_row.payload is not None and off_row.status != "not_found":
            mapped = off.map_product(off_row.payload, gtin14)
            off_outcome = OffOutcome(_off_status_of(mapped), mapped, off_row.fetched_at)
        usda_outcome = UsdaOutcome("not_found")
        fdc_id = _cached_fdc_id(usda_row) if usda_row is not None and usda_row.status == "found" else None
        if fdc_id:
            usda_outcome = UsdaOutcome("found", fdc_id, foods.map_usda_record(usda_row.payload["record"], fdc_id),  # type: ignore[index]
                                       usda_row.fetched_at)  # type: ignore[union-attr]
        assembled = assemble(gtin14, off_outcome, usda_outcome)
        if assembled is None:
            continue
        exists = conn.execute(
            "SELECT 1 FROM foods WHERE owner_user_id IS NULL AND ((source = 'off' AND gtin = ?) OR (source = 'usda' AND fdc_id = ?))",
            (gtin14, assembled.fdc_id or -1),
        ).fetchone()
        if exists is None:
            continue  # nobody has this product as a food row; nothing to update
        store(conn, assembled)
        updated += 1
    conn.commit()
    return {"products": len(gtins), "updated": updated}
