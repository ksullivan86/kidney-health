#!/usr/bin/env python3
"""Generate tests/data/email_vectors.json: parity vectors for password reset by email in the demo (design note 34).

    python3 tests/data/gen_email_vectors.py           # rewrite the file
    python3 tests/data/gen_email_vectors.py --check   # exit 1 when the committed file is stale

Produced by the server's own code and replayed by ``node tests/js/run_vectors.mjs`` against the demo (``app/static/js/mock/auth.js``):

* ``address_cases``: typed addresses and what :func:`app.mail.check_address` makes of them (the stored form, or the sentence);
* ``texts``: the fixed sentences the demo repeats (the answer of "Forgot your password?", a link that is not valid, the admin's
  test email without a confirmed address, an address already confirmed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "email_vectors.json"
sys.path.insert(0, str(ROOT))

ADDRESSES = [
    "sam@example.org", "  Sam.Smith+kidney@Example.ORG ", "o'brien@mail.example.co.uk", "a@b.co", "x-y_z@sub-domain.example.org",
    "", "   ", "sam", "sam@", "@example.org", "sam@example", "sam smith@example.org", "sam@example.org\r\nBcc: x@y.org",
    "sam@@example.org", "säm@example.org", "sam@exämple.org", "sam..x@example.org", ".sam@example.org", "sam.@example.org",
    "sam@-example.org", "sam@example-.org", "sam@example.123", "sam@example.org.", "a" * 64 + "@example.org", "a" * 65 + "@example.org",
    "sam@" + "a" * 63 + ".org", "sam@" + "a" * 64 + ".org", "sam@" + ("a" * 60 + ".") * 5 + "org", "x" * 321,
    "<sam@example.org>", "Sam <sam@example.org>", "sam@[127.0.0.1]",
]


def build() -> dict[str, Any]:
    from app import mail
    from app.auth import email_api

    cases = []
    for raw in ADDRESSES:
        try:
            cases.append({"input": raw, "ok": True, "value": mail.check_address(raw)})
        except mail.AddressRejected as exc:
            cases.append({"input": raw, "ok": False, "detail": str(exc)})
    return {
        "about": "app.mail.check_address and the fixed sentences of app/auth/email_api.py (design note 34).",
        "address_cases": cases,
        "texts": {
            "forgot": email_api.FORGOT_SENT,
            "confirm_invalid": email_api.CONFIRM_INVALID,
            "address_help": mail.ADDRESS_HELP,
            "address_long": mail.ADDRESS_TOO_LONG,
            "admin_no_email": email_api.ADMIN_NO_EMAIL,
            "already": email_api.ALREADY_CONFIRMED,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8")) != json.loads(text):
            print(f"{OUT} is stale: run python3 tests/data/gen_email_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
