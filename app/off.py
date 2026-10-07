"""Open Food Facts client, pacing, payload trimming and mapping to the app's food model (note 03 R3).

This file is also the **ODbL §4.6 method file**: it is the public description of how the app changes
Open Food Facts data (field choice, unit conversion, per-serving scaling, quality checks, the
additive scan in :mod:`app.additives`). Settings → About links to it.

* **Request**: ``GET {OFF_BASE_URL}/api/v3.4/product/{code}?fields=…`` with the identifying
  ``User-Agent: KidneyHealth/<version> (<contact>)`` that Open Food Facts asks for, through the
  SSRF-checked transport (:mod:`app.egress`), 8 s timeout, no redirects, at most 1 MiB of decoded
  body (§9 B6). API 3.4 is pinned: from 3.5 the classic ``nutriments`` object is empty and the values
  move to ``nutrition.aggregated_set``; :func:`parse_nutrition_v35` reads that shape so moving to a
  newer version is a change of :data:`OFF_API_VERSION` (note 03 F1).
* **Pacing**: one server-wide token bucket (:class:`TokenBucket`, ``food.off_rate_per_minute``,
  default 10, at most 15 per minute as OFF allows 15 product reads per minute per IP); an empty
  bucket answers 429 with ``Retry-After``, never a silent queue. One retry after 2 s on 503; never a
  retry on 404.
* **Mapping** (:func:`map_product`): per-serving values from ``<n>_serving`` when the label is per
  serving, else ``<n>_100g`` scaled to the serving; prepared values only when no as-sold value
  exists; an absent value is ``None`` (unknown), never 0; quality notes for everything a person
  should know before trusting the numbers.

Everything except :class:`OffClient` is pure.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Mapping
from urllib.parse import urlsplit

import httpx2

from . import additives, egress
from .gtin import off_code
from .textclean import clean_label, clean_text

log = logging.getLogger("kidney_health.off")

OFF_API_VERSION = "3.4"
DEFAULT_BASE_URL = "https://world.openfoodfacts.org"
DEFAULT_CONTACT = "https://github.com/ksullivan86/kidney-health"
# The product page is built from this constant, never copied from a payload (note 03 §9 B4).
PRODUCT_PAGE_PREFIX = "https://world.openfoodfacts.org/product/"
LICENSE = "ODbL-1.0"
ATTRIBUTION_TEXT = "Product data © Open Food Facts contributors, ODbL"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
# "Add it to Open Food Facts" (checked 2026-10-06: answers "Add a product"; the older type=add form is 404).
CONTRIBUTE_URL = "https://world.openfoodfacts.org/cgi/product.pl?type=search_or_add&action=display&code="

FIELDS: tuple[str, ...] = (
    "code", "product_name", "product_name_en", "generic_name", "brands", "quantity", "serving_size",
    "serving_quantity", "serving_quantity_unit", "nutrition_data_per", "nutrition_data_prepared_per",
    "no_nutrition_data", "nutriments", "ingredients_text", "ingredients_text_en", "additives_tags",
    "categories_tags", "countries_tags", "nova_group", "lang", "last_modified_t",
)
FIELDS_V35 = ("nutrition",)  # the API 3.5+ nutrition object (requested only from that version on)

TIMEOUT_S = 8.0
MAX_RESPONSE_BYTES = 1024 * 1024  # decoded (note 03 §9 B6)
RETRY_503_AFTER_S = 2.0
UPSTREAM_PAUSE_S = 60  # after OFF answers 429, the bucket stays empty this long
MAX_RATE_PER_MINUTE = 15

MAX_NAME_CHARS = 200
MAX_SERVING_DESC_CHARS = 60
MAX_INGREDIENTS_CHARS = 4000
MAX_TAGS = 200
MAX_SERVING_G = 100_000.0
MAX_NUTRIENT_VALUE = 1_000_000.0  # app/models.py bound for a per-serving value

# App key → (OFF nutrient name, multiplier from OFF's standard unit). OFF stores weights in grams.
NUTRIENT_MAP: dict[str, tuple[str, float]] = {
    "protein_g": ("proteins", 1.0),
    "fat_g": ("fat", 1.0),
    "sat_fat_g": ("saturated-fat", 1.0),
    "fiber_g": ("fiber", 1.0),
    "sugar_g": ("sugars", 1.0),
    "potassium_mg": ("potassium", 1000.0),
    "phosphorus_mg": ("phosphorus", 1000.0),
    "calcium_mg": ("calcium", 1000.0),
}
KJ_PER_KCAL = 4.184
SALT_PER_SODIUM = 2.5  # OFF derives one from the other with this factor
# OFF nutrient names worth keeping in the cache (enough to re-run the mapping without the network).
KEPT_NUTRIENTS: tuple[str, ...] = (
    "energy-kcal", "energy-kj", "energy", "proteins", "fat", "saturated-fat", "carbohydrates",
    "carbohydrates-total", "fiber", "sugars", "sodium", "salt", "potassium", "phosphorus", "calcium",
)

# Ordered: the first entry whose tag the product carries wins (tags checked against the OFF
# categories taxonomy on 2026-10-06; "en:salts" is used only for the salt plausibility exception).
CATEGORY_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("en:beverages",), "Beverages"),
    (("en:dairies",), "Dairy & Alternatives"),
    (("en:meats", "en:eggs"), "Meat, Poultry & Eggs"),
    (("en:seafood", "en:fishes"), "Fish & Seafood"),
    (("en:breads", "en:breakfast-cereals", "en:pastas"), "Grains & Breads"),
    (("en:legumes", "en:nuts", "en:seeds"), "Legumes, Nuts & Seeds"),
    (("en:fruits",), "Fruits"),
    (("en:vegetables",), "Vegetables"),
    (("en:snacks", "en:desserts", "en:confectioneries"), "Sweets & Snacks"),
    (("en:condiments", "en:sauces"), "Condiments & Sauces"),
    (("en:meals", "en:pizzas"), "Prepared & Fast Food"),
)
SWEETENED_BEVERAGE_TAG = "en:sweetened-beverages"
HIGH_GI_MIN_SUGARS_PER_100 = 5.0  # g per 100 mL (note 03 R3)
# Beer, wine, spirits, ciders ...: flagged ``alcohol``, so meal guidance never suggests them (delayed lows with
# insulin; app/guidance/rules.py ALCOHOL_FLAG). Open Food Facts files alcohol-free beers under their own
# category, but a product tagged both ways is flagged anyway: leaving a drink out of suggestions is the safe side.
ALCOHOLIC_BEVERAGES_TAG = "en:alcoholic-beverages"
SALT_TAG = "en:salts"
US_CA_TAGS = ("en:united-states", "en:canada")

# Plausibility per 100 g / 100 mL (note 03 R3), plus physical limits: no food holds more than 100 g
# of a macronutrient per 100 g, or more energy than pure fat (about 900 kcal per 100 g).
MAX_PER_100: dict[str, float] = {
    "sodium_mg": 40_000.0, "potassium_mg": 10_000.0, "phosphorus_mg": 5_000.0, "calories_kcal": 950.0,
    "protein_g": 100.0, "fat_g": 100.0, "sat_fat_g": 100.0, "carbs_g": 100.0, "fiber_g": 100.0, "sugar_g": 100.0,
    "calcium_mg": 40_000.0,
}
ENERGY_MISMATCH_FRACTION = 0.25
ENERGY_MISMATCH_MIN_KCAL = 40.0

QualityCode = str
QUALITY_MESSAGES: dict[str, str] = {
    "crowd_sourced": "Community data from Open Food Facts. Check it against the package.",
    "potassium_unknown": "Potassium is not listed for this product: treat it as unknown, not zero.",
    "phosphorus_unknown": "Phosphorus is not listed for this product: treat it as unknown, not zero.",
    "sodium_from_salt": "Sodium was worked out from the salt figure (salt ÷ 2.5).",
    "carbs_available": "This label is not a US or Canadian one: its carbohydrate usually excludes fibre.",
    "prepared_values": "Only the values for the prepared product are listed (as made by the package directions).",
    "ml_as_g": "The serving is in millilitres; it is counted as grams (1 mL ≈ 1 g).",
    "no_serving": "No serving size is listed, so the values are for 100 g (or 100 mL).",
    "energy_mismatch": "The calories do not match the protein, fat and carbohydrate listed. One of them may be wrong.",
    "implausible": "A value was impossible for a food and was left out",
    "no_nutrition": "This product has no nutrition facts in Open Food Facts.",
    "filled_from_usda": "Missing values were filled in from USDA FoodData Central",
    "filled_from_off": "Missing values were filled in from Open Food Facts",
}

Status = Literal["found", "not_found", "no_nutrition"]


# --------------------------------------------------------------------------- #
# Configuration and the request
# --------------------------------------------------------------------------- #


def user_agent(app_version: str, contact: str) -> str:
    """``KidneyHealth/<version> (<contact>)``, the form Open Food Facts asks API users to send."""
    return f"KidneyHealth/{app_version} ({contact})"


def fields_for(api_version: str = OFF_API_VERSION) -> tuple[str, ...]:
    major, _, minor = api_version.partition(".")
    newer = (int(major), int(minor or 0)) >= (3, 5)
    return FIELDS + FIELDS_V35 if newer else FIELDS


def product_url(base_url: str, code: str, api_version: str = OFF_API_VERSION) -> str:
    """The product request URL (``code`` from :func:`app.gtin.off_code`: digits only)."""
    if not code.isdigit() or not code.isascii():
        raise ValueError("the product code must be digits")
    return f"{base_url.rstrip('/')}/api/v{api_version}/product/{code}?fields={','.join(fields_for(api_version))}"


def product_page(gtin14: str) -> str:
    """The public product page for attribution (built from a constant; digits only)."""
    return PRODUCT_PAGE_PREFIX + off_code(gtin14)


def check_base_url(raw: str) -> str:
    """Validate ``OFF_BASE_URL`` (env only, note 03 §9 B5): ``https://host[:port]``, or ``http://`` only for
    localhost; no credentials, path, query or fragment. Returns it without a trailing slash."""
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("https", "http") or not host:
        raise ValueError("must be an https:// address such as https://world.openfoodfacts.org")
    if parts.scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("plain http:// is allowed only for localhost; use https://")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError("must be just the scheme and host (and port), such as https://world.openfoodfacts.org")
    try:
        parts.port
    except ValueError:
        raise ValueError("has an invalid port") from None
    return raw.strip().rstrip("/")


# --------------------------------------------------------------------------- #
# Pacing
# --------------------------------------------------------------------------- #


class TokenBucket:
    """``rate_per_minute`` requests per minute for the whole server, refilled continuously.

    ``take()`` returns 0 when a request may go out now, else the seconds to wait (nothing taken).
    The clock is injectable (tests); the default follows :func:`app.auth.clock.seconds`.
    """

    def __init__(self, rate_per_minute: int, clock: Callable[[], float] | None = None) -> None:
        if not 1 <= rate_per_minute <= MAX_RATE_PER_MINUTE:
            raise ValueError(f"rate_per_minute must be 1 to {MAX_RATE_PER_MINUTE}")
        if clock is None:
            from .auth.clock import seconds as clock
        self._clock = clock
        self._lock = threading.Lock()
        self.rate = rate_per_minute
        self._tokens = float(rate_per_minute)
        self._updated = self._clock()
        self._paused_until = 0.0

    def set_rate(self, rate_per_minute: int) -> None:
        """Change the rate (an admin changed the setting); keeps the current tokens, capped."""
        with self._lock:
            self._refill()
            self.rate = max(1, min(MAX_RATE_PER_MINUTE, int(rate_per_minute)))
            self._tokens = min(self._tokens, float(self.rate))

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(float(self.rate), self._tokens + elapsed * self.rate / 60.0)
        self._updated = now

    def take(self) -> int:
        with self._lock:
            now = self._clock()
            if now < self._paused_until:
                return max(1, math.ceil(self._paused_until - now))
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0
            return max(1, math.ceil((1.0 - self._tokens) * 60.0 / self.rate))

    def pause(self, seconds: float) -> None:
        """Hold every request for ``seconds`` (Open Food Facts said 429)."""
        with self._lock:
            self._paused_until = max(self._paused_until, self._clock() + seconds)
            self._tokens = 0.0


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


class OffError(Exception):
    """A failed lookup. ``kind`` is a coarse category; upstream bodies are never echoed."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class FetchResult:
    status: Literal["found", "not_found"]
    product: dict[str, Any] | None = None


class OffClient:
    """Fetches one product. ``transport`` (tests) replaces the SSRF-checked network transport."""

    def __init__(
        self,
        base_url: str,
        app_version: str,
        contact: str,
        *,
        api_version: str = OFF_API_VERSION,
        transport: httpx2.BaseTransport | None = None,
        allow_private: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.user_agent = user_agent(app_version, contact)
        self._transport = transport
        self._allow_private = allow_private
        self._sleep = sleep
        self._timeout = timeout_s

    def _client(self) -> httpx2.Client:
        transport = self._transport or egress.CheckedTransport(allow_private=self._allow_private)
        return httpx2.Client(
            transport=transport,
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": self.user_agent, "Accept": "application/json", "Accept-Encoding": "gzip"},
        )

    def fetch(self, code: str) -> FetchResult:
        """``found`` with the product object, or ``not_found``; :class:`OffError` for anything else."""
        url = product_url(self.base_url, code, self.api_version)
        status, body = self._get(url)
        if status == 503:
            log.info("Open Food Facts answered 503; retrying once in %.0f s", RETRY_503_AFTER_S)
            self._sleep(RETRY_503_AFTER_S)
            status, body = self._get(url)
        if status == 429:
            raise OffError("rate_limited", "Open Food Facts asked us to slow down")
        if status in (301, 302, 303, 307, 308):
            raise OffError("redirect", f"Open Food Facts answered with a redirect (HTTP {status})")
        if status not in (200, 404):
            raise OffError(f"http_{status}", f"Open Food Facts answered HTTP {status}")
        if body is None:
            raise OffError("invalid_response", "Open Food Facts did not answer with JSON")
        try:
            doc = json.loads(body)
        except (UnicodeDecodeError, ValueError):
            raise OffError("invalid_response", "Open Food Facts answered with invalid JSON") from None
        if not isinstance(doc, dict):
            raise OffError("invalid_response", "Open Food Facts answered with an unexpected document")
        result = doc.get("result") if isinstance(doc.get("result"), dict) else {}
        if status == 404 or doc.get("status") == "failure":
            if result.get("id") == "product_not_found" or status == 404:
                return FetchResult("not_found")
            raise OffError("invalid_response", "Open Food Facts reported a failure")
        product = doc.get("product")
        if not isinstance(product, dict):
            raise OffError("invalid_response", "Open Food Facts answered without a product")
        return FetchResult("found", product)

    def _get(self, url: str) -> tuple[int, bytes | None]:
        try:
            with self._client() as client, client.stream("GET", url) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if response.status_code in (200, 404) and content_type != "application/json":
                    return response.status_code, None
                if response.status_code not in (200, 404):
                    return response.status_code, b""
                return response.status_code, egress.read_capped(response, MAX_RESPONSE_BYTES)
        except egress.ResponseTooLarge:
            raise OffError("too_large", "The Open Food Facts answer was too large") from None
        except egress.BlockedAddress as exc:
            raise OffError("blocked_address", str(exc).split(":", 1)[0]) from None
        except httpx2.TimeoutException:
            raise OffError("timeout", "Open Food Facts did not answer in time") from None
        except httpx2.HTTPError as exc:
            raise OffError("connect_failed", f"Could not reach Open Food Facts ({exc.__class__.__name__})") from None


# --------------------------------------------------------------------------- #
# Payload trimming (what the cache keeps)
# --------------------------------------------------------------------------- #


def _kept_nutriment_key(key: str) -> bool:
    for name in KEPT_NUTRIENTS:
        if key == name or key.startswith(name + "_"):
            rest = key[len(name):]
            return rest in ("", "_100g", "_serving", "_prepared", "_prepared_100g", "_prepared_serving", "_unit")
    return False


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _string_list(value: Any, limit: int = MAX_TAGS) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        cleaned = clean_label(item, max_len=100)
        if cleaned:
            out.append(cleaned.casefold())
    return out


def trim_product(product: Mapping[str, Any]) -> dict[str, Any]:
    """The cached copy of a product: the requested fields only, text cleaned and capped, numbers
    coerced, nutriments reduced to the nutrients the mapping reads. Enough to re-run
    :func:`map_product` later without the network (``python -m app.admin remap-barcodes``)."""
    out: dict[str, Any] = {}
    for key in ("code", "lang"):
        cleaned = clean_label(product.get(key), max_len=40)
        if cleaned:
            out[key] = cleaned
    for key in ("product_name", "product_name_en", "generic_name", "brands", "quantity"):
        cleaned = clean_label(product.get(key), max_len=MAX_NAME_CHARS)
        if cleaned:
            out[key] = cleaned
    serving_size = clean_label(product.get("serving_size"), max_len=MAX_NAME_CHARS)
    if serving_size:
        out["serving_size"] = serving_size
    for key in ("ingredients_text", "ingredients_text_en"):
        cleaned = clean_text(product.get(key), max_len=MAX_INGREDIENTS_CHARS, keep_newlines=True)
        if cleaned:
            out[key] = cleaned
    for key in ("serving_quantity", "nova_group", "last_modified_t"):
        number = _finite_number(product.get(key))
        if number is not None:
            out[key] = number
    for key in ("serving_quantity_unit", "nutrition_data_per", "nutrition_data_prepared_per", "no_nutrition_data"):
        cleaned = clean_label(product.get(key), max_len=20)
        if cleaned:
            out[key] = cleaned.casefold()
    for key in ("additives_tags", "categories_tags", "countries_tags"):
        tags = _string_list(product.get(key))
        if tags:
            out[key] = tags
    nutriments = product.get("nutriments")
    kept: dict[str, Any] = {}
    if isinstance(nutriments, Mapping):
        for key, value in nutriments.items():
            if not isinstance(key, str) or not _kept_nutriment_key(key):
                continue
            if key.endswith("_unit"):
                unit = clean_label(value, max_len=10)
                if unit:
                    kept[key] = unit
                continue
            number = _finite_number(value)
            if number is not None:
                kept[key] = number
    out["nutriments"] = kept
    nutrition = product.get("nutrition")
    if isinstance(nutrition, Mapping):
        aggregated = _trim_aggregated(nutrition.get("aggregated_set"))
        if aggregated:
            out["nutrition"] = {"aggregated_set": aggregated}
    return out


def _trim_aggregated(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    nutrients = value.get("nutrients")
    if not isinstance(nutrients, Mapping):
        return None
    kept: dict[str, Any] = {}
    for name in KEPT_NUTRIENTS:
        item = nutrients.get(name)
        if not isinstance(item, Mapping):
            continue
        number = _finite_number(item.get("value"))
        unit = clean_label(item.get("unit"), max_len=10)
        if number is not None and unit:
            kept[name] = {"value": number, "unit": unit}
    out: dict[str, Any] = {"nutrients": kept}
    for key in ("per", "preparation"):
        cleaned = clean_label(value.get(key), max_len=20)
        if cleaned:
            out[key] = cleaned.casefold()
    return out


# --------------------------------------------------------------------------- #
# API 3.5+ nutrition object
# --------------------------------------------------------------------------- #

# (multiply, divide) to grams; dividing by 1000 keeps 350 mg → 0.35 g exact in binary floating point.
_UNIT_TO_GRAMS: dict[str, tuple[float, float]] = {
    "g": (1.0, 1.0), "mg": (1.0, 1000.0), "µg": (1.0, 1e6), "μg": (1.0, 1e6), "mcg": (1.0, 1e6), "ug": (1.0, 1e6),
    "kg": (1000.0, 1.0),
}


def parse_nutrition_v35(product: Mapping[str, Any]) -> dict[str, float]:
    """Flat ``nutriments`` (``<name>_100g`` / ``<name>_serving``, OFF standard units) from the API 3.5+
    ``nutrition.aggregated_set`` (``per``: ``100g``, ``100ml`` or ``serving``; ``preparation``:
    ``as_sold`` or ``prepared``; each nutrient ``{value, unit}``). Unknown units are skipped."""
    nutrition = product.get("nutrition")
    aggregated = nutrition.get("aggregated_set") if isinstance(nutrition, Mapping) else None
    if not isinstance(aggregated, Mapping) or not isinstance(aggregated.get("nutrients"), Mapping):
        return {}
    per = str(aggregated.get("per") or "100g").lower()
    suffix = "_serving" if per == "serving" else "_100g"
    infix = "_prepared" if str(aggregated.get("preparation") or "as_sold").lower() == "prepared" else ""
    out: dict[str, float] = {}
    for name, item in aggregated["nutrients"].items():
        if name not in KEPT_NUTRIENTS or not isinstance(item, Mapping):
            continue
        value = _finite_number(item.get("value"))
        unit = str(item.get("unit") or "").strip()
        if value is None:
            continue
        if name.startswith("energy"):
            if unit.lower() == "kcal":
                key = "energy-kcal"
            elif unit.lower() == "kj":
                key = "energy-kj" if name != "energy" else "energy"
            else:
                continue
            out[f"{key}{infix}{suffix}"] = value
            continue
        factor = _UNIT_TO_GRAMS.get(unit) or _UNIT_TO_GRAMS.get(unit.lower())
        if factor is None:
            continue
        out[f"{name}{infix}{suffix}"] = value * factor[0] / factor[1]
    return out


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #


@dataclass
class Mapped:
    """A product mapped to ``insert_food`` arguments plus the barcode fields."""

    status: Status
    name: str
    brand: str | None = None
    category: str | None = None
    serving_desc: str = "100 g"
    serving_g: float = 100.0
    nutrients: dict[str, float | None] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    kidney_notes: str | None = None
    ingredients_text: str | None = None
    additives: list[str] = field(default_factory=list)
    # Quality codes in a stable order; "implausible:<key>" and "filled_from_<src>:<key>" name a nutrient.
    quality: list[str] = field(default_factory=list)
    us_label: bool = False  # the product is sold in the US or Canada (countries_tags)
    country_known: bool = False  # countries_tags was present at all

    def food_kwargs(self) -> dict[str, Any]:
        return {
            "name": self.name, "brand": self.brand, "category": self.category, "serving_desc": self.serving_desc,
            "serving_g": self.serving_g, "nutrients": self.nutrients, "flags": self.flags, "kidney_notes": self.kidney_notes,
        }


def _per_value(nutriments: Mapping[str, Any], name: str, infix: str, per_serving_label: bool, serving_g: float) -> float | None:
    """A per-serving value in OFF's standard unit, or ``None``."""
    if per_serving_label:
        direct = _finite_number(nutriments.get(f"{name}{infix}_serving"))
        if direct is not None:
            return direct
    per_100 = _finite_number(nutriments.get(f"{name}{infix}_100g"))
    if per_100 is None:
        return None
    return per_100 * serving_g / 100.0


def _has_any(nutriments: Mapping[str, Any], infix: str) -> bool:
    for name in KEPT_NUTRIENTS:
        for suffix in ("_100g", "_serving"):
            if _finite_number(nutriments.get(f"{name}{infix}{suffix}")) is not None:
                return True
    return False


def _category(tags: Iterable[str]) -> str | None:
    tag_set = set(tags)
    for keys, category in CATEGORY_MAP:
        if tag_set.intersection(keys):
            return category
    return None


def _serving(product: Mapping[str, Any], liquid: bool) -> tuple[float, str, list[str]]:
    quality: list[str] = []
    quantity = _finite_number(product.get("serving_quantity"))
    unit = str(product.get("serving_quantity_unit") or "").strip().casefold()
    if quantity is not None and 0 < quantity <= MAX_SERVING_G and unit in ("g", "ml"):
        if unit == "ml":
            quality.append("ml_as_g")
        text = clean_label(product.get("serving_size"), max_len=MAX_SERVING_DESC_CHARS)
        return quantity, text or f"{quantity:g} {'mL' if unit == 'ml' else 'g'}", quality
    quality.append("no_serving")
    return 100.0, ("100 mL" if liquid else "100 g"), quality


def map_product(product: Mapping[str, Any], gtin14: str) -> Mapped:
    """Map an Open Food Facts product (fresh or trimmed) to the app's food model (note 03 R3)."""
    product = trim_product(product)
    code = off_code(gtin14)
    name = (
        clean_label(product.get("product_name"), max_len=MAX_NAME_CHARS)
        or clean_label(product.get("product_name_en"), max_len=MAX_NAME_CHARS)
        or clean_label(product.get("generic_name"), max_len=MAX_NAME_CHARS)
        or f"Product {code}"
    )
    brands = product.get("brands") or ""
    brand = clean_label(brands.split(",")[0], max_len=MAX_NAME_CHARS) if isinstance(brands, str) else None
    categories = product.get("categories_tags") or []
    countries = product.get("countries_tags") or []
    us_label = any(tag in countries for tag in US_CA_TAGS)
    ingredients = product.get("ingredients_text_en") or product.get("ingredients_text")

    nutriments: dict[str, Any] = dict(product.get("nutriments") or {})
    if not _has_any(nutriments, "") and not _has_any(nutriments, "_prepared"):
        nutriments = parse_nutrition_v35(product)  # API 3.5+ shape (empty `nutriments`)

    unit = str(product.get("serving_quantity_unit") or "").casefold()
    liquid = unit == "ml" or str(product.get("nutrition_data_per") or "") == "100ml" or "en:beverages" in categories
    serving_g, serving_desc, quality = _serving(product, liquid)

    infix = ""
    if not _has_any(nutriments, "") and _has_any(nutriments, "_prepared"):
        infix = "_prepared"
        quality.append("prepared_values")
        serving_desc = f"{serving_desc[: MAX_SERVING_DESC_CHARS - len(' (prepared)')]} (prepared)"
    per_key = "nutrition_data_prepared_per" if infix else "nutrition_data_per"
    per_serving_label = str(product.get(per_key) or "") == "serving"

    def value(name: str) -> float | None:
        return _per_value(nutriments, name, infix, per_serving_label, serving_g)

    nutrients: dict[str, float | None] = {}
    kcal = value("energy-kcal")
    if kcal is None:
        kj = value("energy-kj")
        if kj is None:
            kj = value("energy")
        kcal = None if kj is None else kj / KJ_PER_KCAL
    nutrients["calories_kcal"] = kcal
    carbs_total = value("carbohydrates-total")
    nutrients["carbs_g"] = carbs_total if carbs_total is not None else value("carbohydrates")
    if carbs_total is None and nutrients["carbs_g"] is not None and not us_label:
        quality.append("carbs_available")
    for key, (off_name, factor) in NUTRIENT_MAP.items():
        raw = value(off_name)
        nutrients[key] = None if raw is None else raw * factor
    sodium = value("sodium")
    salt = value("salt")
    if sodium is not None:
        nutrients["sodium_mg"] = sodium * 1000.0
        # EU labels declare salt, not sodium (Regulation (EU) 1169/2011), and OFF then derives sodium as
        # salt / 2.5: say so when a non-US label carries both and they match that factor.
        if not us_label and salt is not None and abs(sodium * SALT_PER_SODIUM - salt) <= 0.01 * salt + 1e-9:
            quality.append("sodium_from_salt")
    else:
        nutrients["sodium_mg"] = None if salt is None else salt * 1000.0 / SALT_PER_SODIUM
        if salt is not None:
            quality.append("sodium_from_salt")

    # Plausibility (judged per 100 g or 100 mL), then the model bounds.
    implausible: list[str] = []
    is_salt = SALT_TAG in categories
    for key, limit in MAX_PER_100.items():
        v = nutrients.get(key)
        if v is None:
            continue
        per_100 = v * 100.0 / serving_g
        if v < 0 or v > MAX_NUTRIENT_VALUE or (per_100 > limit and not (key == "sodium_mg" and is_salt)):
            nutrients[key] = None
            implausible.append(key)
    quality.extend(f"implausible:{key}" for key in implausible)

    no_nutrition = str(product.get("no_nutrition_data") or "") == "on" or all(
        nutrients.get(k) is None for k in ("calories_kcal", "protein_g", "fat_g", "carbs_g")
    )

    energy_parts = [nutrients.get(k) for k in ("calories_kcal", "carbs_g", "protein_g", "fat_g")]
    if all(v is not None for v in energy_parts):
        kcal_100 = energy_parts[0] * 100.0 / serving_g  # type: ignore[operator]
        computed_100 = (4 * energy_parts[1] + 4 * energy_parts[2] + 9 * energy_parts[3]) * 100.0 / serving_g  # type: ignore[operator]
        diff = abs(kcal_100 - computed_100)
        if diff > ENERGY_MISMATCH_FRACTION * kcal_100 and diff > ENERGY_MISMATCH_MIN_KCAL:
            quality.append("energy_mismatch")

    scan = additives.scan(product.get("additives_tags"), ingredients, name)
    flags = list(scan.flags)
    if unit == "ml":
        flags.append("counts_as_fluid")
        nutrients["fluid_ml"] = serving_g
    else:
        nutrients["fluid_ml"] = 0.0
    if product.get("nova_group") == 4:
        flags.append("processed")
    sugars_100 = None if nutrients.get("sugar_g") is None else nutrients["sugar_g"] * 100.0 / serving_g  # type: ignore[operator]
    if SWEETENED_BEVERAGE_TAG in categories and sugars_100 is not None and sugars_100 >= HIGH_GI_MIN_SUGARS_PER_100:
        flags.append("high_gi")
    if ALCOHOLIC_BEVERAGES_TAG in categories:
        flags.append("alcohol")

    for key in ("potassium_mg", "phosphorus_mg"):
        if nutrients.get(key) is None:
            quality.append(key.split("_")[0] + "_unknown")
    quality.insert(0, "crowd_sourced")
    if no_nutrition:
        quality.append("no_nutrition")

    kidney_notes = scan.kidney_notes or (" ".join(scan.notes)[:1000] or None)
    return Mapped(
        status="no_nutrition" if no_nutrition else "found",
        name=name,
        brand=brand,
        category=_category(categories),
        serving_desc=serving_desc,
        serving_g=serving_g,
        nutrients=nutrients,
        flags=flags,
        kidney_notes=kidney_notes,
        ingredients_text=clean_text(ingredients, max_len=MAX_INGREDIENTS_CHARS, keep_newlines=True),
        additives=scan.additives,
        quality=list(dict.fromkeys(quality)),
        us_label=us_label,
        country_known=bool(countries),
    )


def quality_items(codes: Iterable[str]) -> list[dict[str, str]]:
    """``[{"code", "message"}]`` for the API, in the stored order. A stored code may name a nutrient
    after a colon (``implausible:sodium_mg``, ``filled_from_usda:potassium_mg``)."""
    from .nutrients import NUTRIENT_BY_KEY

    items: list[dict[str, str]] = []
    for stored in codes:
        code, _, key = str(stored).partition(":")
        message = QUALITY_MESSAGES.get(code)
        if message is None:
            continue  # a code from a newer version this one does not know
        if key:
            nutrient = NUTRIENT_BY_KEY.get(key)
            label = nutrient.label.lower() if nutrient else key
            message = f"{message}: {label}."
        elif code in ("implausible", "filled_from_usda", "filled_from_off"):
            message = f"{message}."
        items.append({"code": code, "message": message})
    return items
