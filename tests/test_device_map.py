"""The page's reading of Withings and Whoop answers (owner, 2026-11-26: Withings and Whoop set up from the phone with no server).

The twin is ``app/static/js/engine/device_map.js``; ``node tests/js/run_vectors.mjs`` replays ``tests/data/device_map_vectors.json``
against it. Here: the vectors are what the server gives now, and the page loads the twin.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_the_vectors_are_current() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "data" / "gen_device_map_vectors.py"), "--check"], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def test_the_page_and_the_offline_copy_load_the_twin() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<script src="js/engine/device_map.js"></script>' in index
    assert index.index("js/engine/device_map.js") < index.index("js/mock/devices.js")
    assert "'/js/engine/device_map.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_twin_reaches_no_network_and_keeps_nothing() -> None:
    js = (STATIC / "js" / "engine" / "device_map.js").read_text(encoding="utf-8")
    for word in ("fetch(", "XMLHttpRequest", "localStorage", "indexedDB", "postMessage", "document."):
        assert word not in js, word
