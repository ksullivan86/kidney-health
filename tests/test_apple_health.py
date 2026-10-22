"""Weights and blood pressure readings from the iPhone Health app's export.xml (note 10 section 4.8, Part C), the engine side.

The browser reads ``export.xml`` as a stream of text (``js/engine/apple_health.js``, ``KH.appleHealth``): no XML parser, a bounded
carry-over buffer, three record types kept, nothing uploaded by the reader. It has no Python twin, so ``tests/data/apple_health_vectors.json``
(``tests/js/gen_apple_health_vectors.mjs``: hand-written export.xml fragments and hand-written expectations) pins it for
``node tests/js/run_vectors.mjs``, and ``tests/js/apple_health_large.mjs`` reads a generated 200 MB file under a memory bound. This file checks
what Node cannot check about itself: that every ``source_key`` is the SHA-256 of its key text (recomputed here with ``hashlib``, not by the module
or by the generator), that the contexts and roundings in the vectors follow the note's rules written out again in Python, that the numbers the
module uses are the note's, and that the node scripts pass.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ENGINE_PATH = STATIC / "js" / "engine" / "apple_health.js"
ENGINE = ENGINE_PATH.read_text(encoding="utf-8")
NOTE = (ROOT / "docs" / "dev" / "research" / "10-weight-and-blood-pressure.md").read_text(encoding="utf-8")
VECTORS = json.loads((ROOT / "tests" / "data" / "apple_health_vectors.json").read_text(encoding="utf-8"))
CASES = VECTORS["cases"]
STAMP = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4}"


def rows(kind: str) -> list[tuple[str, dict]]:
    return [(c["name"], row) for c in CASES for row in c["expected"][kind]]


def case(fragment: str) -> dict:
    found = [c for c in CASES if fragment in c["name"]]
    assert len(found) == 1, fragment
    return found[0]


def half_up(text: str, places: str) -> Decimal:
    return Decimal(text).quantize(Decimal(places), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- source_key


def test_every_source_key_is_the_sha256_of_its_key_text():
    all_rows = rows("weights") + rows("readings")
    assert len(all_rows) > 80
    for name, row in all_rows:
        assert re.fullmatch(r"[0-9a-f]{32}", row["source_key"]), (name, row)
        assert row["source_key"] == hashlib.sha256(row["key_input"].encode("utf-8")).hexdigest()[:32], (name, row["key_input"])


def test_a_weights_key_text_is_type_startdate_value_sourcename():
    for name, row in rows("weights"):
        m = re.fullmatch(rf"HKQuantityTypeIdentifierBodyMass\|({STAMP})\|(\d+(?:\.\d+)?)\|(.*)", row["key_input"], re.S)
        assert m, (name, row["key_input"])
        start, _value, source = m.groups()
        # date and time are the startDate as written, not converted to another time zone
        assert (row["date"], row["time"]) == (start[:10], start[11:16]), (name, row)
        assert source == row["sourceName"], (name, row)


def test_a_readings_key_text_is_bloodpressure_startdate_systolic_over_diastolic_sourcename():
    for name, row in rows("readings"):
        m = re.fullmatch(rf"BloodPressure\|({STAMP})\|(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\|(.*)", row["key_input"], re.S)
        assert m, (name, row["key_input"])
        start, systolic, diastolic, source = m.groups()
        assert (row["date"], row["time"]) == (start[:10], start[11:16]), (name, row)
        assert source == row["sourceName"], (name, row)
        # whole mmHg, rounded half up from what the file says
        assert (row["systolic"], row["diastolic"]) == (int(half_up(systolic, "1")), int(half_up(diastolic, "1"))), (name, row)
        assert 50 <= row["systolic"] <= 300 and 20 <= row["diastolic"] <= 200 and row["systolic"] > row["diastolic"], (name, row)


def test_no_two_rows_of_a_case_share_a_key():
    for c in CASES:
        keys = [r["source_key"] for r in c["expected"]["weights"] + c["expected"]["readings"]]
        assert len(keys) == len(set(keys)), c["name"]


# --------------------------------------------------------------------------- the rules of the note, written out again


def context_of(kind: str, time: str) -> str:
    minutes = int(time[:2]) * 60 + int(time[3:])
    if 4 * 60 <= minutes <= 10 * 60 + 59:
        return "morning"
    if kind == "reading" and 17 * 60 <= minutes <= 23 * 60 + 59:
        return "evening"
    return "other"


def test_every_context_follows_the_notes_time_windows():
    for name, row in rows("weights"):
        assert row["context"] == context_of("weight", row["time"]), (name, row)
    for name, row in rows("readings"):
        assert row["context"] == context_of("reading", row["time"]), (name, row)


def test_the_windows_edges_are_all_in_the_vectors():
    weights = {(r["time"], r["context"]) for _, r in rows("weights")}
    readings = {(r["time"], r["context"]) for _, r in rows("readings")}
    assert {("03:59", "other"), ("04:00", "morning"), ("10:59", "morning"), ("11:00", "other"), ("23:59", "other")} <= weights
    assert {("03:59", "other"), ("04:00", "morning"), ("10:59", "morning"), ("11:00", "other"), ("16:59", "other"), ("17:00", "evening"),
            ("23:59", "evening")} <= readings


def test_kilograms_are_pounds_times_0_45359237_rounded_half_up_to_hundredths():
    pounds = case("weights in pounds")
    assert len(pounds["expected"]["weights"]) >= 8
    for row in pounds["expected"]["weights"]:
        value = row["key_input"].split("|")[2]
        assert Decimal(str(row["kg"])) == half_up(str(Decimal(value) * Decimal("0.45359237")), "0.01"), row
    for row in case("kilograms are rounded half up")["expected"]["weights"]:
        value = row["key_input"].split("|")[2]
        assert Decimal(str(row["kg"])) == half_up(value, "0.01"), row
    assert VECTORS["limits"]["kg_per_lb"] == 0.45359237


def test_the_plausibility_ranges_and_limits_are_the_notes():
    ranges = VECTORS["limits"]["ranges"]
    assert re.search(r"`kg` 20–400", NOTE) and ranges["kg"] == [20, 400]
    assert re.search(r"`systolic` 50–300, `diastolic` 20–200", NOTE) and ranges["systolic"] == [50, 300] and ranges["diastolic"] == [20, 200]
    assert "1 lb = 0.45359237 kg exactly" in NOTE
    assert re.search(r"longer than 8 KiB is skipped", NOTE) and VECTORS["limits"]["max_tag"] == 8 * 1024
    assert re.search(r"batches of 1,000", NOTE) and VECTORS["limits"]["batch_size"] == 1000
    assert "progress line every 10 MB" in NOTE and VECTORS["limits"]["progress_step"] == 10 * 1024 * 1024
    # and the module says so too
    assert "const MAX_TAG = 8192;" in ENGINE and "const BATCH_SIZE = 1000;" in ENGINE and "const KG_PER_LB = 0.45359237;" in ENGINE
    assert "RANGES = { kg: [20, 400], systolic: [50, 300], diastolic: [20, 200] }" in ENGINE


def test_the_vectors_cover_what_part_c_asks_for():
    names = "\n".join(c["name"] for c in CASES)
    for fragment in ("a weight in kilograms", "weights in pounds", "inside a Correlation and again loose", "a pair outside a Correlation", "half a pair",
                     "attributes in any order", "single or double quotes", "five XML entities", "any other &", "8,193 characters",
                     "Health's own prolog", "chunks that split", "a unit the reader does not know", "other records are ignored",
                     "sources are kept", "04:00 to 10:59", "04:00-10:59", "outside 20-400 kg", "outside 50-300", "not converted to UTC"):
        assert fragment in names, fragment
    assert VECTORS["chunk_sizes"] == [1, 7, 64, "whole"]
    # the "g" unit really is a g record, and glucose and insulin really are in the file that is ignored
    units = case("a unit the reader does not know")
    assert 'unit="g"' in units["xml"] and units["expected"]["summary"]["skipped"]["unknownUnit"] == 7
    ignored = case("other records are ignored")
    xml = ignored["xml"]
    assert "HKQuantityTypeIdentifierBloodGlucose" in xml and "HKQuantityTypeIdentifierInsulinDelivery" in xml and "HKQuantityTypeIdentifierHeartRate" in xml
    assert ignored["expected"]["summary"]["skipped"] == dict.fromkeys(ignored["expected"]["summary"]["skipped"], 0)
    assert len(ignored["expected"]["weights"]) == 1 and ignored["expected"]["readings"] == []
    # a DTD, with an entity declaration that must never be expanded
    entities = case("any other &")
    assert "<!DOCTYPE HealthData [" in entities["xml"] and '<!ENTITY lol "ha">' in entities["xml"]
    # the over-long tag really is over 8 KiB and the one before it really is exactly 8 KiB
    def text(c):
        return "".join(p if isinstance(p, str) else p["repeat"]["text"] * p["repeat"]["count"] for p in c["xml"])
    def start_tag(c):
        return text(c)[text(c).index('<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-02-01'):].split("\n")[0]
    assert len(start_tag(case("exactly 8,192 characters"))) == 8192
    assert len(start_tag(case("of 8,193 characters"))) == 8193


# --------------------------------------------------------------------------- the module


def test_the_module_reads_no_xml_with_a_parser_and_touches_no_network_or_storage():
    assert not re.search(r"DOMParser|parseFromString|createPolicy|XMLHttpRequest|\bfetch\s*\(|sendBeacon|WebSocket|EventSource|importScripts|"
                         r"localStorage|sessionStorage|indexedDB|document\.|\.innerHTML|\beval\s*\(|new\s+Function", ENGINE)
    assert "KH.appleHealth = {" in ENGINE
    # the exact formats of the key texts are in the header comment, as the note's spec asks
    header = ENGINE[: ENGINE.index("(function (root)")]
    assert "HKQuantityTypeIdentifierBodyMass|<startDate>|<value>|<sourceName>" in header
    assert "BloodPressure|<startDate>|<systolic>/<diastolic>|<sourceName>" in header
    assert "first 32 hex characters of the SHA-256" in header


def test_the_builder_of_the_demo_inlines_the_module_once_index_html_lists_it(tmp_path: Path):
    """index.html does not list the file yet (the import sheet adds it, with sw.js), so the builder is run on a copy that does."""
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    static = tmp_path / "static"
    shutil.copytree(STATIC, static)
    index = static / "index.html"
    html = index.read_text(encoding="utf-8")
    anchor = '<script src="js/engine/rules.js"></script>'
    assert html.count(anchor) == 1
    index.write_text(html.replace(anchor, anchor + '\n<script src="js/engine/apple_health.js"></script>'), encoding="utf-8")
    fragment = builder.build_fragment(static_dir=static)
    assert "/* js/engine/apple_health.js */" in fragment and ENGINE.strip() in fragment
    assert fragment.index("/* js/engine/rules.js */") < fragment.index("/* js/engine/apple_health.js */")
    assert fragment.count("KH.appleHealth = {") == 1
    # the GitHub Pages demo gets it as a file of its own, after rules.js (which it needs for halfUp)
    site = tmp_path / "site"
    builder.build_pages(site, static_dir=static)
    assert (site / "js" / "engine" / "apple_health.js").read_bytes() == ENGINE_PATH.read_bytes()
    page = (site / "index.html").read_text(encoding="utf-8")
    assert page.index('<script src="js/engine/rules.js">') < page.index('<script src="js/engine/apple_health.js">')


# --------------------------------------------------------------------------- node


def run_node(*args: str, timeout: int) -> subprocess.CompletedProcess:
    assert shutil.which("node"), "Node.js 22 is needed for the JS parity vectors and the large-file test (CLAUDE.md, Parity): install it and run again"
    return subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)


def test_the_committed_vectors_are_what_the_generator_writes():
    done = run_node(str(ROOT / "tests" / "js" / "gen_apple_health_vectors.mjs"), "--check", timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_node_runner_replays_the_apple_health_vectors():
    done = run_node(str(ROOT / "tests" / "js" / "run_vectors.mjs"), timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "apple health vectors:" in done.stdout and "checks passed" in done.stdout


@pytest.fixture(scope="module")
def large():
    """A generated export of about 200 MB streamed through the reader, then the hostile shapes (about 6 seconds in all)."""
    done = run_node("--expose-gc", str(ROOT / "tests" / "js" / "apple_health_large.mjs"), "--mb", "200", timeout=300)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_200_mb_export_is_read_with_exact_counts_and_a_bounded_heap(large):
    assert large["ok"] is True
    assert large["mb"] >= 200 and large["records"] > 300_000
    assert large["weights"] >= 1000 and large["readings"] >= 1000  # a few thousand each
    assert large["heap"]["peak_growth_mb"] < 100  # heapUsed while reading, above where it started
    assert large["heap"]["retained_mb"] < 20  # and after the scan, once collected
    assert large["max_carry"] <= 8192
    assert large["skipped"]["tagTooLong"] >= 5 and large["skipped"]["badEntity"] > 0 and large["skipped"]["halfPair"] > 0


def test_hostile_shapes_are_read_in_linear_time_with_a_bounded_buffer(large):
    assert len(large["shapes"]) == 5
    for shape in large["shapes"]:
        assert shape["seconds"] < 20, shape
        assert shape["maxCarry"] <= 8192, shape
