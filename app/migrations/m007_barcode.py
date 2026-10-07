"""Step 7: barcodes, Open Food Facts and USDA branded foods (note 03 R6, §9).

1. ``foods`` gains the barcode and provenance columns:

   * ``gtin``: the GTIN-14 (14 digits) a barcode lookup or a hand-entered product found it by;
   * ``source_url``: the public page for attribution, always built by the server from a constant
     (``https://world.openfoodfacts.org/product/<code>`` or the FoodData Central home), never copied
     from a provider's payload (note 03 §9 B4);
   * ``source_license``: ``ODbL-1.0`` (Open Food Facts), ``CC0-1.0`` (FoodData Central),
     ``CC0-1.0 AND ODbL-1.0`` (a USDA product completed with Open Food Facts data) or NULL;
   * ``retrieved_at``: when the provider data was fetched;
   * ``ingredients_text``: the cleaned ingredient list the additive scan read;
   * ``additives_json``: why an additive flag was set (``["e326", "e451"]``), default ``'[]'``;
   * ``quality_json``: quality codes shown as notes (``["crowd_sourced", "potassium_unknown"]``),
     default ``'[]'``, so every existing row reads as "no notes".

   ``foods.source`` gains the value ``'off'`` (the column has no CHECK constraint; the list lives in
   ``app/nutrients.py`` ``FOOD_SOURCES``). Index ``foods_gtin`` serves the lookup; the partial unique
   index ``foods_off_gtin`` keeps one shared Open Food Facts row per GTIN, so two people scanning the
   same product at once cannot create two rows.
2. ``barcode_cache``: the instance-wide provider cache, one row per (GTIN, provider) with the trimmed
   upstream payload (enough to re-run a newer mapping without the network, ``python -m app.admin
   remap-barcodes``). ``found`` rows are kept until someone refreshes the product; ``not_found`` and
   ``no_nutrition`` rows expire after ``food.barcode_negative_ttl_hours`` and are purged daily (§9 B11).
   Which products a person scanned is personal and is **not** stored here: that is the person's
   ``user_food_links`` row, deleted with the account.

Idempotent: columns are added only when missing; the table and indexes use ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 7
DESCRIPTION = "v0.3 barcodes: food gtin and provenance columns, barcode_cache"

SCHEMA = ""  # the indexes name columns this step adds, so everything runs in migrate() (ordering gotcha)
ATOMIC = True

FOOD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("gtin", "TEXT"),
    ("source_url", "TEXT"),
    ("source_license", "TEXT"),
    ("retrieved_at", "TEXT"),
    ("ingredients_text", "TEXT"),
    ("additives_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("quality_json", "TEXT NOT NULL DEFAULT '[]'"),
)

DDL = """
CREATE INDEX IF NOT EXISTS foods_gtin ON foods(gtin) WHERE gtin IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS foods_off_gtin ON foods(gtin) WHERE source = 'off' AND gtin IS NOT NULL;

CREATE TABLE IF NOT EXISTS barcode_cache (
  gtin TEXT NOT NULL CHECK (length(gtin) = 14),
  provider TEXT NOT NULL CHECK (provider IN ('off', 'usda')),
  status TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'no_nutrition')),
  payload_json TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (gtin, provider)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS barcode_cache_negative ON barcode_cache(fetched_at) WHERE status != 'found';
"""


def migrate(conn: sqlite3.Connection) -> None:
    for column, ddl in FOOD_COLUMNS:
        add_column_if_missing(conn, "foods", column, ddl)
    execute_script(conn, DDL)
