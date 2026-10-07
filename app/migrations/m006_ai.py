"""Step 6: optional AI (note 04 R4, R9 and its §9 security review; ARCHITECTURE "M2 API: AI and photos").

Everything the settings registry does not cover. The person's AI preferences (opt-in, provider
choice, preferences text, ``share_age_sex``) and the instance switches (``ai.*``) are registry keys
(``app/settings_registry.py``); what needs rows of its own lives here:

1. ``ai_providers``: shared providers (an admin's, or the one ``AI_PROVIDER`` defines, ``locked = 1``)
   and at most one provider per person (``scope = 'user'``). ``api_key_enc`` is a
   :class:`app.crypto.Keyring` token sealed with ``purpose = "ai_provider:<id>"`` and ``owner =
   owner_user_id`` (note 07 §4.12; ``app.crypto.ENCRYPTED_COLUMNS`` already lists the column, so key
   rotation re-encrypts it). The env provider's key is never stored: it is read from ``AI_API_KEY``
   at call time. ``api_key_hint`` holds the last four characters of keys of 20 characters or more
   (the write-only view). ``CHECK ((scope = 'shared') = (owner_user_id IS NULL))`` as on ``secrets``.
   ``AUTOINCREMENT`` so a deleted provider's id is never reused by another one (usage rows and audit
   rows keep the id).
2. ``ai_consents``: the person agreed to send data to a provider's **destination host** under the
   policy version they saw (``purpose`` ``text`` for next-meal and describe-a-meal, ``photos`` for
   label and plate photos, note 03 R10). Both foreign keys cascade; changing a provider's host
   deletes its consents, so everyone is asked again (note 04 R9).
3. ``ai_usage``: requests and tokens per person, day and provider (``key_scope`` ``shared`` counts
   toward ``ai.shared_daily_limit``). Probes and photo calls count too (note 04 §9 A4, A5).
4. ``ai_audit``: what was sent and received, per call, for the person's own "AI activity" page;
   bodies are cleared after ``ai.audit_retention_days`` (images are never stored, only their
   SHA-256, size and dimensions).

Every ``user_id`` / ``owner_user_id`` references ``users`` with ``ON DELETE CASCADE``, so deleting an
account erases its provider, key, consents, usage and AI history (§9 A8). Idempotent: ``IF NOT
EXISTS`` everywhere.
"""
from __future__ import annotations

import sqlite3

from ..db import execute_script

VERSION = 6
DESCRIPTION = "v0.3 optional AI: providers, consents, usage and AI activity"

SCHEMA = ""  # every table references users (created by step 3's migrate()), so everything runs below
ATOMIC = True
FOREIGN_KEY_CHECK = True

DDL = """
CREATE TABLE IF NOT EXISTS ai_providers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL CHECK (scope IN ('shared','user')),
  owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  preset TEXT NOT NULL,
  label TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key_enc BLOB,
  api_key_hint TEXT,
  model TEXT NOT NULL,
  vision_model TEXT,
  timeout_s REAL,
  max_tokens INTEGER,
  context_tokens INTEGER,
  structured TEXT NOT NULL DEFAULT 'auto' CHECK (structured IN ('auto','json_schema','json_object','prompt')),
  reasoning_effort TEXT,
  extra_json TEXT NOT NULL DEFAULT '{}',
  locked INTEGER NOT NULL DEFAULT 0 CHECK (locked IN (0,1)),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  disabled_reason TEXT,
  probe_json TEXT,
  probed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  CHECK ((scope = 'shared') = (owner_user_id IS NULL)),
  CHECK (locked = 0 OR scope = 'shared')
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_providers_one_per_user ON ai_providers(owner_user_id) WHERE scope = 'user';
CREATE UNIQUE INDEX IF NOT EXISTS ai_providers_one_env ON ai_providers(locked) WHERE locked = 1;

CREATE TABLE IF NOT EXISTS ai_consents (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider_id INTEGER NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL CHECK (purpose IN ('text','photos')),
  host TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  skip_preview INTEGER NOT NULL DEFAULT 0 CHECK (skip_preview IN (0,1)),
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, provider_id, purpose)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ai_consents_provider ON ai_consents(provider_id);

CREATE TABLE IF NOT EXISTS ai_usage (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  provider_id INTEGER NOT NULL,
  key_scope TEXT NOT NULL CHECK (key_scope IN ('shared','own')),
  requests INTEGER NOT NULL DEFAULT 0,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day, provider_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ai_usage_day ON ai_usage(day);

CREATE TABLE IF NOT EXISTS ai_audit (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  feature TEXT NOT NULL,
  provider_id INTEGER,
  model TEXT,
  destination_host TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  request_json TEXT,
  response_text TEXT,
  verdict_json TEXT NOT NULL,
  latency_ms INTEGER,
  status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_audit_user ON ai_audit(user_id, id);
CREATE INDEX IF NOT EXISTS ai_audit_created ON ai_audit(created_at);
"""


def migrate(conn: sqlite3.Connection) -> None:
    execute_script(conn, DDL)
