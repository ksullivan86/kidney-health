#!/usr/bin/env python3
"""Generate tests/data/meta_vectors.json: parity vectors for the demo's GET /api/meta (design note 14 change 4).

    python3 tests/data/gen_meta_vectors.py           # rewrite the file
    python3 tests/data/gen_meta_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code (``app/meta.py`` over ``app/nutrient_core.py`` and ``app/api_version.py``) from a fresh server with every
switch at its default and the first admin signed in, and replayed on the JavaScript side by ``node tests/js/run_vectors.mjs`` against the
demo API (``app/static/js/mock/meta.js``):

* ``api_version``: the integer; the demo carries its own copy;
* ``capability_keys``: the keys of ``capabilities`` in the server's order, and ``capabilities``: their values on that server (all false: nothing
  optional is switched on, which is also what the demo is);
* ``nutrients`` and ``meals``: the registry and the meal names exactly as the server lists them (the demo builds them from ``js/engine/rules.js``,
  so a nutrient added on one side only fails here).

``app_version`` is left out: it changes with every release and the demo reads it from Settings (``tests/test_settings_ui.py`` pins that copy).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "meta_vectors.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def build() -> dict[str, Any]:
    """The whole document (also what ``tests/test_meta.py`` compares the committed file with)."""
    from starlette.testclient import TestClient as BareClient

    from app.main import create_app
    from conftest import ADMIN_PASSWORD, ADMIN_USERNAME, CSRF_HEADERS, FIXTURE_FOODS, make_settings

    with tempfile.TemporaryDirectory() as tmp:
        foods = Path(tmp) / "foods.json"
        foods.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
        with BareClient(create_app(make_settings(Path(tmp), foods)), base_url="http://localhost", headers=dict(CSRF_HEADERS)) as client:
            r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
            assert r.status_code == 200, r.text
            answer = client.get("/api/meta")
            assert answer.status_code == 200, answer.text
    meta = answer.json()
    return {
        "about": "GET /api/meta on a fresh server, every switch at its default (design note 14 change 4); app_version is left out.",
        "api_version": meta["api_version"],
        "capability_keys": list(meta["capabilities"]),
        "capabilities": meta["capabilities"],
        "nutrients": meta["nutrients"],
        "meals": meta["meals"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_meta_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
