#!/usr/bin/env python3
"""Generate tests/data/settings_vectors.json: parity vectors for the browser settings twin.

    python3 tests/data/gen_settings_vectors.py           # rewrite the file
    python3 tests/data/gen_settings_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code, ``app/settings_registry.py`` and ``app/settings_store.py``
(note 07 §4.11), and replayed on the JavaScript side by ``node tests/js/run_vectors.mjs`` against
``app/static/js/engine/settings.js`` (the registry table the Settings view and the demo API use):

* ``registry``: every key with its scope, default, env lock, label, help and type details (taken
  from the key's pydantic JSON schema, including a string key's ``pattern``), which the JS table
  must equal;
* ``validation_cases``: ``SettingDef.validate`` on good and bad JSON values (value or error text);
* ``precedence_cases``: a ``SettingsStore`` over a fresh schema-v3 database with the given env
  locks, instance rows and personal rows (some stored values deliberately invalid, which fall
  through to the next level), and the resulting ``user_view`` and ``admin_view``.

Standard library only (plus the app package on the path).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "settings_vectors.json"
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError  # noqa: E402

from app import db, settings_registry  # noqa: E402
from app.settings_store import SettingsStore  # noqa: E402

USER_ID = 1  # m003 creates user 1 (the first admin, pending setup) in every new database


def registry_vectors() -> list[dict]:
    out = []
    for d in settings_registry.all_settings():
        schema = d.adapter.json_schema()
        item: dict = {"key": d.key, "scope": d.scope, "default": d.to_python_json(d.default), "env": d.env, "label": d.label, "help": d.help}
        if "enum" in schema:
            item.update(type="choice", options=list(schema["enum"]))
        elif schema.get("type") == "boolean":
            item.update(type="bool")
        elif schema.get("type") == "integer":
            item.update(type="int", min=schema.get("minimum"), max=schema.get("maximum"))
        elif schema.get("type") == "string":
            item.update(type="str", minLength=schema.get("minLength"), maxLength=schema.get("maxLength"))
            if schema.get("pattern"):  # e.g. food.off_contact (it goes into a User-Agent header)
                item["pattern"] = schema["pattern"]
        else:  # an object setting (M2: ai, guidance): the JS table describes it itself
            item.update(type="object")
        out.append(item)
    return out


VALUES = {
    "bool": [True, False, 0, 1, 2, "yes", "off", "maybe", None, [], 1.5],
    "int": [0, 1, 7, 90, 91, -1, 5.0, 5.5, "12", "12.0", "1e2", " 30 ", True, None, "x"],
    "str": ["My server", "  padded name  ", "", "   ", "x" * 80, "x" * 81, 5, None],
    "choice": [None, 5, "nope"],
}
# Extra strings for a key with a pattern: the JS twin checks it after the length (as pydantic does).
PATTERN_VALUES = ["admin@example.org", "Mum's server, mum@example.org", "a(b)c", "back\\slash", "x\r\nX-Evil: 1",
                  "tab\there", "café@example.org", "  ab(  ", "ok@example.org\n"]


def validation_vectors() -> list[dict]:
    out = []
    for item in registry_vectors():
        d = settings_registry.get(item["key"])
        values = list(VALUES.get(item["type"], []))
        if item["type"] == "choice":
            values = [*item["options"], item["options"][0].upper(), *values]
        if item.get("pattern"):
            values += PATTERN_VALUES
        for value in values:
            try:
                out.append({"key": d.key, "input": value, "value": d.to_python_json(d.validate(value))})
            except ValidationError as exc:
                out.append({"key": d.key, "input": value, "error": "; ".join(e["msg"] for e in exc.errors(include_input=False))})
    return out


def _fresh_db():
    conn = db.connect(":memory:")
    db.migrate(conn)
    return conn


def precedence_case(name: str, env: dict, instance: dict, user: dict, raw_instance: dict | None = None, raw_user: dict | None = None) -> dict:
    conn = _fresh_db()
    writer = SettingsStore(env={})  # rows written before the env lock was set stay in the database
    for key, value in instance.items():
        writer.set_instance(conn, key, value)
    for key, value in user.items():
        writer.set_user(conn, USER_ID, key, value)
    store = SettingsStore(env=env)
    # Hand-edited rows that no longer validate: the store skips them (next level wins).
    for key, text in (raw_instance or {}).items():
        conn.execute("INSERT OR REPLACE INTO instance_settings (key, value_json, updated_at) VALUES (?, ?, '2026-01-01T00:00:00Z')", (key, text))
    for key, text in (raw_user or {}).items():
        conn.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value_json, updated_at) VALUES (?, ?, ?, '2026-01-01T00:00:00Z')", (USER_ID, key, text))
    store.invalidate()
    conn.commit()
    ctx_instance = {**instance, **{k: json.loads(t) for k, t in (raw_instance or {}).items()}}
    ctx_user = {**user, **{k: json.loads(t) for k, t in (raw_user or {}).items()}}
    case = {
        "name": name,
        "env": env,
        "instance": ctx_instance,
        "user": ctx_user,
        "user_view": store.user_view(conn, USER_ID),
        "admin_view": store.admin_view(conn),
    }
    conn.close()
    return case


def precedence_vectors() -> list[dict]:
    return [
        precedence_case("defaults", {}, {}, {}),
        precedence_case("instance values", {}, {"instance.name": "Family log", "registration.mode": "closed", "food.off_enabled": True,
                                                 "providers.usda.daily_limit_per_user": 0, "ui.theme": "dark"}, {}),
        precedence_case("a person's own values win over the admin default", {}, {"ui.theme": "dark"}, {"ui.theme": "light", "food.off_consent": True}),
        precedence_case("env locks win over everything", {"OFF_ENABLED": "false", "INSTANCE_NAME": "  Locked name ", "REGISTRATION_MODE": "open",
                                                          "USDA_SHARED_DAILY_LIMIT": "50", "AUDIT_RETENTION_DAYS": "30"},
                        {"food.off_enabled": True, "instance.name": "Ignored", "registration.mode": "closed"}, {"food.off_consent": True}),
        precedence_case("env bool spellings", {"OFF_ENABLED": "yes"}, {}, {}),
        precedence_case("blank env is not a lock", {"OFF_ENABLED": "  ", "INSTANCE_NAME": ""}, {"food.off_enabled": True}, {}),
        precedence_case("invalid stored values fall through", {}, {"registration.mode": "invite"},
                        {}, raw_instance={"food.off_enabled": '"maybe"', "registration.invite_ttl_days": "0", "ui.theme": '"purple"'},
                        raw_user={"ui.theme": '"neon"', "food.off_consent": "1"}),
    ]


def build() -> dict:
    settings_log = logging.getLogger("kidney_health.settings")
    was_disabled, settings_log.disabled = settings_log.disabled, True  # the invalid-row warnings are expected here
    try:
        return {
            "about": "Parity vectors for app/static/js/engine/settings.js, generated from app/settings_registry.py and "
                     "app/settings_store.py by tests/data/gen_settings_vectors.py. Do not edit by hand: change the registry, then regenerate.",
            "registry": registry_vectors(),
            "validation_cases": validation_vectors(),
            "precedence_cases": precedence_vectors(),
        }
    finally:
        settings_log.disabled = was_disabled


def dumps(doc: dict) -> str:
    """One vector per line, so a registry change shows up as a readable diff."""
    lines = ["{"]
    items = list(doc.items())
    for n, (key, value) in enumerate(items):
        comma = "," if n < len(items) - 1 else ""
        if isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(f"  {json.dumps(key)}: [")
            for m, item in enumerate(value):
                lines.append("    " + json.dumps(item, ensure_ascii=False, separators=(",", ":")) + ("," if m < len(value) - 1 else ""))
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = parser.parse_args(argv)
    text = dumps(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if json.loads(current or "null") != json.loads(text):
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_settings_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['registry'])} keys, {len(doc['validation_cases'])} validation cases, "
          f"{len(doc['precedence_cases'])} precedence cases ({len(text.encode()):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
