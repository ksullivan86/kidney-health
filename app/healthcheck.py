"""Container health check: ``python -m app.healthcheck`` exits 0 when ``/healthz`` answers 200.

Standard library only (the runtime image has no curl or shell), and it **bypasses**
``HTTP(S)_PROXY`` so an egress-proxy setting can never break the probe. It calls
``http://127.0.0.1:$PORT/healthz`` (``PORT`` defaults to 8000); an IP literal always passes the
Host allowlist.
"""
from __future__ import annotations

import os
import sys
import urllib.request
from typing import Mapping, Sequence

TIMEOUT_S = 4


def check(port: str | int, timeout: float = TIMEOUT_S) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        url = f"http://127.0.0.1:{int(port)}/healthz"
        with opener.open(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    return 0 if check(env.get("PORT") or "8000") else 1


if __name__ == "__main__":
    sys.exit(main())
