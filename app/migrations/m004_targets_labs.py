"""Step 4: personalised targets and lab results (note 05 §4.2, §4.6).

1. Adds the "About you" fields to ``user_profiles`` (the per-person profile since step 3; the
   frozen v0.2 ``profile`` table is never read and is left alone):
   ``birth_month`` ('YYYY-MM'), ``sex`` ('female' | 'male' | 'unspecified'), ``activity`` (NULL =
   not chosen yet, so the instance default ``targets.default_activity`` applies and the suggestion
   lists it in ``missing_inputs``), ``transplant_date`` ('YYYY-MM-DD'), ``frail_or_sarcopenic``,
   ``weight_6_months_ago_kg``, ``pregnant_or_breastfeeding``, ``hyperkalemia_history``,
   ``urine_output_ml``, ``pd_uf_ml`` and ``pd_dialysate_kcal``.
2. Creates ``lab_results``: one row per result, value in the analyte's canonical unit
   (:mod:`app.units`) plus what the person typed; ``user_id`` cascades with the account.

Idempotent: every column is added only when missing and the table and index use ``IF NOT EXISTS``.
"""
from __future__ import annotations

import sqlite3

from ..db import add_column_if_missing, execute_script

VERSION = 4
DESCRIPTION = "v0.3 personalised targets: profile fields and lab results"

SCHEMA = ""  # lab_results references users (created by step 3's migrate()), so everything runs below
ATOMIC = True

# (column, DDL) in the order of note 05 §4.6. NOT NULL columns carry a default so existing rows fill in.
PROFILE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("birth_month", "TEXT"),
    ("sex", "TEXT NOT NULL DEFAULT 'unspecified'"),
    ("activity", "TEXT"),
    ("transplant_date", "TEXT"),
    ("frail_or_sarcopenic", "INTEGER NOT NULL DEFAULT 0"),
    ("weight_6_months_ago_kg", "REAL"),
    ("pregnant_or_breastfeeding", "INTEGER NOT NULL DEFAULT 0"),
    ("hyperkalemia_history", "INTEGER NOT NULL DEFAULT 0"),
    ("urine_output_ml", "REAL"),
    ("pd_uf_ml", "REAL"),
    ("pd_dialysate_kcal", "REAL"),
)

LAB_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS lab_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  analyte TEXT NOT NULL,                 -- potassium|phosphate|albumin|bicarbonate|uacr|creatinine|cystatin_c|egfr|a1c
  value REAL NOT NULL,                   -- canonical unit (app/units.py)
  entered_value REAL NOT NULL,
  entered_unit TEXT NOT NULL,
  taken_on TEXT NOT NULL,                -- YYYY-MM-DD
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lab_results_lookup ON lab_results(user_id, analyte, taken_on DESC, id DESC);
"""


def migrate(conn: sqlite3.Connection) -> None:
    for column, ddl in PROFILE_COLUMNS:
        add_column_if_missing(conn, "user_profiles", column, ddl)
    execute_script(conn, LAB_RESULTS_DDL)
