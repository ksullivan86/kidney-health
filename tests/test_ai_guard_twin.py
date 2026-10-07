"""The AI activity list hides the words the guard never shows, with the server's own blocklist (v0.3.0 review L4).

Settings → AI activity lists each call's raw answer ("What came back", note 04 R9 step 5). The guard dropped any
dosing or medicine text before a card was shown, but the raw copy was printed as it came, without a caption. Now
the view captions it as the provider's unchecked answer and shows it through ``KH.aiguard.maskForDisplay``, the
browser twin of ``app/ai/guard.py`` (``fold`` + ``BLOCKLIST``). The stored row and the export keep the full text.
This test checks the twin's pattern and look-alike table against the server's, runs both on the guard's own test
texts, and checks the masked copy of the review's example.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.ai import guard as G
from test_ai_guard import BLOCKED_TERMS

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "aiguard_twin.mjs"
AI_JS = ROOT / "app" / "static" / "js" / "views" / "ai.js"

OBFUSCATED = ["ins​ulin", "ins­ulin", "іnsulin", "INSULIN", "Ｉｎｓｕｌｉｎ",
              "s‮afe to eat", "bοlus"]
ORDINARY = ["Pumpkin soup", "Masala dosa", "Basil chicken", "Unity loaf", "Rationed rice", "Pasta with lentils", "7-grain bread",
            "Supper salad", "Extra virgin olive oil", "Extra-lean ground beef", "Extra sharp cheddar", "Penne arrabbiata",
            "Skippy peanut butter", "Glucose tablets", "Double chocolate cookie", "Fine sea salt", "Shortbread",
            "Pending order of rice"]
# The review's reproduction: a fake provider put dosing prose before its JSON.
RAW = 'Sure! Take 6 units of insulin before this meal.\n{"ideas": [{"name": "Rice with extra virgin olive oil",\n  "why": "it\'s fine, no need to bolus"}]}'


def _twin(texts: list[str]) -> dict[str, Any]:
    assert shutil.which("node"), "Node.js 22 is needed to run the browser twin (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(RUNNER)], input=json.dumps(texts), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_twin_uses_the_servers_pattern_and_lookalikes() -> None:
    out = _twin([])
    assert out["source"] == G.BLOCKLIST.pattern
    assert out["confusables"] == {chr(k): v for k, v in G._CONFUSABLES.items()}


def test_the_twin_blocks_what_the_server_blocks() -> None:
    texts = [f"Rice with {t} please" for t in BLOCKED_TERMS] + OBFUSCATED + ORDINARY + [RAW]
    out = _twin(texts)
    assert out["blocked"] == [G.blocked(t) for t in texts]
    assert all(b is not None for b in out["blocked"][: len(BLOCKED_TERMS) + len(OBFUSCATED)])
    assert all(b is None for b in out["blocked"][len(BLOCKED_TERMS) + len(OBFUSCATED):-1])


def test_the_raw_answer_is_shown_masked_and_still_readable() -> None:
    out = _twin([RAW] + ORDINARY)
    masked, mask = out["masked"][0], out["mask"]
    assert G.blocked(masked) is None, masked  # nothing the guard would stop is left
    assert masked.count(mask) == 5  # "units", "insulin", "it's fine", "no need to", "bolus"
    assert masked.splitlines()[0] == f"Sure! Take 6 {mask} of {mask} before this meal."
    assert "extra virgin olive oil" in masked and len(masked.splitlines()) == 3  # food words and line breaks stay
    assert out["masked"][1:] == ORDINARY  # ordinary food text is unchanged


def test_ai_activity_captions_and_masks_the_raw_answer() -> None:
    js = AI_JS.read_text(encoding="utf-8")
    row = js.split("function activityRow(ev)", 1)[1].split("\n  }\n", 1)[0]
    assert "pre(ev.response_text)" not in row
    assert "KH.aiguard.maskForDisplay(ev.response_text)" in row and "rawCaption()" in row
    caption = js.split("function rawCaption()", 1)[1].split("\n  }\n", 1)[0]
    assert "before the app checked it" in caption and "export keeps the full text" in caption
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert html.index('<script src="js/engine/aiguard.js">') < html.index('<script src="js/views/ai.js">')
