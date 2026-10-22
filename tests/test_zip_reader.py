"""Reading a .zip in the browser (note 11, ``js/engine/zip.js``, ``KH.zip``): the reader, on archives built here.

Python builds every archive at test time in a temporary folder, so no binary is committed: with ``zipfile`` where it can, and with
the small byte builder below (:func:`build`) where ``zipfile`` cannot make the shape: a zip64 directory without 4 GB of data, a
lying size, a flipped CRC, a name that differs between the two headers, a fake end record, an encrypted or bzip2 entry. Then
``tests/js/zip_reader.mjs`` (Node 22) opens them with the module and prints what happened, and the tests below hold the expected
values, written here by hand or taken from Python's own ``zipfile``, so the module never grades itself. The numbers are the cases of
note 11 section 5.

* Archives the reader must read: 1 the app's own export, 2 stored/deflated/empty/UTF-8 and code page 437 names, 3 a data descriptor,
  4 zip64, 5 a comment that holds an end record, 6 a re-zipped folder with the macOS extras, 7 a Health-shaped archive with an
  encrypted entry nobody selects, 8 a large entry under a memory bound.
* Archives it must refuse, each with its code: 9 not_zip, 10 unsupported, 11 too_big, 12 damaged, 13 missing and ambiguous,
  14 abort, 15 browser.
"""
from __future__ import annotations

import datetime
import importlib.util
import io
import json
import random
import re
import shutil
import struct
import subprocess
import zipfile
import zlib
from pathlib import Path

import pytest
from conftest import DAY, FIXTURE_FOODS, find_food, make_settings, signed_in_client
from zip_support import (DEFLATE, MAX32, MiB, STORED, Item, Unseekable, build, central_entries, deflated, patch_eocd, raw_deflate, sha, stored,
                         zipfile_bytes)

from app import account, db

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
ENGINE_PATH = STATIC / "js" / "engine" / "zip.js"
ENGINE = ENGINE_PATH.read_text(encoding="utf-8")
NOTE = (ROOT / "docs" / "dev" / "research" / "11-reading-a-zip-in-the-browser.md").read_text(encoding="utf-8")
RUNNER = ROOT / "tests" / "js" / "zip_reader.mjs"

# --------------------------------------------------------------------------- what goes into the archives
JSON_DOC = ('{"format": "kidney-health-export", "version": 1, "log_entries": ['
            + ", ".join(f'{{"id": {i}, "note": "naïve café {i}"}}' for i in range(40)) + "]}").encode("utf-8")


def health_xml(records: int = 3000) -> str:
    """About 600 KB in the shape of the Health app's export.xml: a DTD, noise, weights in kg and lb, blood pressure, odd records."""
    rng = random.Random(11)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE HealthData [\n<!ELEMENT HealthData (ExportDate,Me,(Record)*)>\n<!ENTITY lol "lol">\n]>\n'
             '<HealthData locale="en_US">\n <ExportDate value="2026-10-20 09:00:00 -0400"/>\n']
    for i in range(records):
        day = datetime.date(2025, 1, 1) + datetime.timedelta(days=i % 400)
        stamp = f"{day.isoformat()} {7 + i % 12:02d}:{i % 60:02d}:00 -0500"
        if i % 9 == 0:
            if i % 18 == 0:
                parts.append(f' <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Zoë’s scale" unit="lb" startDate="{stamp}" value="{150 + (i % 70) / 10:.1f}"/>\n')
            else:
                parts.append(f' <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="{stamp}" value="{68 + (i % 90) / 10:.1f}"/>\n')
        elif i % 11 == 0:
            for kind, value in (("Systolic", 110 + i % 40), ("Diastolic", 70 + i % 25)):
                parts.append(f' <Record type="HKQuantityTypeIdentifierBloodPressure{kind}" sourceName="Cuff App" unit="mmHg" startDate="{stamp}" value="{value}"/>\n')
        elif i % 97 == 0:
            parts.append(f' <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="A &nbsp; B" unit="kg" startDate="{stamp}" value="70"/>\n')
        else:
            parts.append(f' <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min" startDate="{stamp}" value="{rng.randint(48, 150)}">\n'
                         f'  <MetadataEntry key="HKMetadataKeyHeartRateMotionContext" value="{i % 3}"/>\n </Record>\n')
    parts.append("</HealthData>\n")
    return "".join(parts)


CLINICAL = {
    "apple_health_export/clinical-records/Observation-1.json": b'{"resourceType": "Observation", "id": "1"}',
    "apple_health_export/clinical-records/Observation-2.json": b'{"resourceType": "Observation", "id": "2", "note": "caf\xc3\xa9"}',
    "apple_health_export/clinical-records/Patient-1.json": b'{"resourceType": "Patient"}',
}


def health_items(xml: bytes) -> list[Item]:
    return [
        deflated("apple_health_export/export.xml", xml),
        deflated("apple_health_export/export_cda.xml", b"<ClinicalDocument/>"),
        deflated("apple_health_export/clinical-records/Observation-1.json", CLINICAL["apple_health_export/clinical-records/Observation-1.json"]),
        stored("apple_health_export/clinical-records/Observation-2.json", CLINICAL["apple_health_export/clinical-records/Observation-2.json"]),
        deflated("apple_health_export/clinical-records/Patient-1.json", CLINICAL["apple_health_export/clinical-records/Patient-1.json"]),
        stored("apple_health_export/workout-routes/route_1.gpx", b"<gpx/>"),
        Item("apple_health_export/workout-routes/encrypted.gpx", bytes(range(50)), STORED, flags=1),
        Item("apple_health_export/workout-routes/bzip2.gpx", b"BZh91AY&SY not really bzip2", 12, size=300, crc=0),
        deflated("apple_health_export/electrocardiograms/ecg_1.csv", b"Name,Sam\nRecorded,2026-01-01\n" * 50),
    ]


RULE_NAMES = [
    "export.json", "a/export.json", "a/b/export.json", "Export.json", "export.json.bak", "my-export.json", "/export.json", "//x/export.json",
    "__MACOSX/export.json", "__MACOSX/a/export.json", "a/._export.json", "._export.json", "export.json/", "../export.json", "a/../export.json",
    "./export.json",
    "apple_health_export/export.xml", "apple_health_export/export_cda.xml", "export.xml", "a/b/export.xml",
    "apple_health_export/clinical-records/Observation-1.json", "clinical-records/Observation-2.json", "clinical-records/Observation-3.JSON",
    "clinical-records/sub/Observation-4.json", "x/apple_health_export/clinical-records/Observation-5.json", "Clinical-Records/Observation-6.json",
    "clinical-records/.json", "clinical-records/._Observation-7.json", "__MACOSX/clinical-records/Observation-8.json", "clinical-records/notes.txt",
    "clinical-records/",
]


def build_large(path: Path) -> dict:
    """An export.xml of about 64 MB (200,000 records, mostly ones the reader ignores) in a zip, written in pieces. Returns what is in it."""
    head = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE HealthData [\n<!ELEMENT HealthData (ExportDate,Me,(Record)*)>\n]>\n'
            '<HealthData locale="en_US">\n <ExportDate value="2026-10-20 09:00:00 -0400"/>\n')
    total, per_block = 200_000, 200
    expected = {"weights": 0, "kg_hundredths": 0, "readings": 0, "systolic_sum": 0}
    size = 0
    info = zipfile.ZipInfo("apple_health_export/export.xml", date_time=(2026, 10, 22, 9, 30, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive, archive.open(info, "w") as out:
        out.write(head.encode("ascii"))
        size += len(head)
        for first in range(0, total, per_block):
            lines = []
            for i in range(first, first + per_block):
                if i % 400 == 0:
                    k = i // 400
                    day = datetime.date(2020, 1, 1) + datetime.timedelta(days=k)
                    tenths = 600 + k % 300
                    lines.append(f' <Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Scale" unit="kg" startDate="{day.isoformat()} 07:30:00 -0500" value="{tenths / 10:.1f}"/>\n')
                    expected["weights"] += 1
                    expected["kg_hundredths"] += tenths * 10
                elif i % 650 == 1:
                    k = i // 650
                    day = datetime.date(2021, 1, 1) + datetime.timedelta(days=k)
                    systolic, diastolic = 100 + k % 60, 60 + k % 30
                    for kind, value in (("Systolic", systolic), ("Diastolic", diastolic)):
                        lines.append(f' <Record type="HKQuantityTypeIdentifierBloodPressure{kind}" sourceName="Cuff" unit="mmHg" startDate="{day.isoformat()} 08:00:00 -0500" value="{value}"/>\n')
                    expected["readings"] += 1
                    expected["systolic_sum"] += systolic
                else:
                    lines.append(f' <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" sourceVersion="10.1" unit="count/min" creationDate="2024-03-04 10:00:00 -0500" '
                                 f'startDate="2024-03-04 10:00:{i % 60:02d} -0500" endDate="2024-03-04 10:00:{i % 60:02d} -0500" value="{50 + i % 90}">\n'
                                 f'  <MetadataEntry key="HKMetadataKeyHeartRateMotionContext" value="{i % 3}"/>\n </Record>\n')
            block = "".join(lines)
            out.write(block.encode("ascii"))
            size += len(block)
        tail = "</HealthData>\n"
        out.write(tail.encode("ascii"))
        size += len(tail)
    return {**expected, "size": size}


def build_app_export(tmp: Path) -> bytes:
    """The archive the app itself writes (app.account.build_export) for a test user with a few hundred log entries and non-ASCII text."""
    foods = tmp / "foods.json"
    foods.write_text(json.dumps(FIXTURE_FOODS), encoding="utf-8")
    settings = make_settings(tmp, foods)
    with signed_in_client(settings) as client:
        banana = find_food(client, "banana")
        client.post("/api/foods", json={"name": "Crème brûlée — “fancy” 🍮", "serving_desc": "1 cup", "serving_g": 100, "nutrients": {"potassium_mg": 100}})
        for i in range(250):
            client.post("/api/log", json={"date": DAY, "meal": "lunch", "food_id": banana["id"], "note": f"été ☕ {i} " + "x" * 40})
        client.put("/api/profile", json={"name": "Zoë", "weight_kg": 70})
        conn = db.connect(settings.db_path)
        try:
            user_id = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()["id"]
            return account.build_export(conn, user_id, app_version="0.4.0")
        finally:
            conn.close()


# --------------------------------------------------------------------------- the archives and the run
def mixed_entries() -> list[tuple[str, bytes, int]]:
    rng = random.Random(1)
    return [
        ("stored.txt", b"stored bytes\n" * 100, zipfile.ZIP_STORED),
        ("deflated.txt", b"deflated bytes\n" * 400, zipfile.ZIP_DEFLATED),
        ("empty_stored.txt", b"", zipfile.ZIP_STORED),
        ("empty_deflated.txt", b"", zipfile.ZIP_DEFLATED),
        ("données/été-☕.txt", "bonjour — voilà\n".encode() * 20, zipfile.ZIP_DEFLATED),
        ("random.bin", rng.randbytes(70_000), zipfile.ZIP_DEFLATED),
        ("folder/", b"", zipfile.ZIP_STORED),
    ]


def descriptor_entries() -> list[tuple[str, bytes, int]]:
    return [("a.txt", b"first file\n" * 20000, zipfile.ZIP_DEFLATED), ("b.txt", b"second file\n" * 50, zipfile.ZIP_STORED),
            ("empty.txt", b"", zipfile.ZIP_DEFLATED)]


def zip64_items() -> list[Item]:
    return [
        deflated("all.txt", b"all three in the extra field\n" * 100, zip64=frozenset({"usize", "csize", "offset"})),
        stored("offset_only.txt", b"only the offset\n" * 10, zip64=frozenset({"offset"})),
        deflated("usize_only.txt", b"only the size\n" * 100, zip64=frozenset({"usize"})),
        stored("disk.txt", b"the disk number\n" * 10, zip64=frozenset({"disk"})),
        deflated("everything.txt", b"all four\n" * 100, zip64=frozenset({"usize", "csize", "offset", "disk"})),
        deflated("export.json", JSON_DOC),
    ]


def zip64_payloads() -> dict[str, bytes]:
    return {"all.txt": b"all three in the extra field\n" * 100, "offset_only.txt": b"only the offset\n" * 10, "usize_only.txt": b"only the size\n" * 100,
            "disk.txt": b"the disk number\n" * 10, "everything.txt": b"all four\n" * 100, "export.json": JSON_DOC}


def good_items() -> list[Item]:
    return [deflated("export.json", JSON_DOC), deflated("log.csv", b"a,b\n1,2\n")]


def archives(tmp: Path) -> dict[str, bytes]:
    """Every small archive the runner opens, by file name (without .zip)."""
    good = build(good_items())
    rows = (b'{"id": %d, "note": "%08x"}' % (i, i * 2654435761 % 2**32) for i in range(520_000))  # about 17.5 MiB; varied, so it does not pack small
    big_doc = b'{"format": "kidney-health-export", "log_entries": [' + b", ".join(rows) + b"]}"
    assert 17 * MiB <= len(big_doc) < 18 * MiB
    a: dict[str, bytes] = {}
    a["app_export"] = build_app_export(tmp)

    a["mixed"] = zipfile_bytes(mixed_entries())
    a["cp437"] = build([stored(b"caf\x82.txt", b"code page 437 name\n"), stored("plain.txt", b"plain\n")])
    sink = Unseekable()
    with zipfile.ZipFile(sink, "w") as archive:
        for name, payload, method in descriptor_entries():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 22, 9, 30, 0))
            info.compress_type = method
            archive.writestr(info, payload)
    a["descriptor"] = b"".join(sink.parts)
    a["zip64"] = build(zip64_items(), zip64_end="all")
    a["zip64_count_only"] = build(zip64_items(), zip64_end="count")
    fake = b"PK\x05\x06" + bytes(18)  # looks like an end record (its comment length is 0), in the middle of the comment
    a["comment"] = zipfile_bytes([("export.json", JSON_DOC, zipfile.ZIP_DEFLATED), ("log.csv", b"a,b\n", zipfile.ZIP_STORED)], comment=b"see " + fake + b" and more")
    a["comment_max"] = zipfile_bytes([("export.json", JSON_DOC, zipfile.ZIP_DEFLATED)], comment=fake + b"c" * (65535 - len(fake)))
    a["rezipped"] = zipfile_bytes([
        ("kidney-health-x/", b"", zipfile.ZIP_STORED), ("kidney-health-x/export.json", JSON_DOC, zipfile.ZIP_DEFLATED),
        ("kidney-health-x/log.csv", b"a,b\n", zipfile.ZIP_DEFLATED), ("kidney-health-x/._export.json", b"\x00\x05\x16\x07 AppleDouble", zipfile.ZIP_STORED),
        ("__MACOSX/", b"", zipfile.ZIP_STORED), ("__MACOSX/kidney-health-x/", b"", zipfile.ZIP_STORED),
        ("__MACOSX/kidney-health-x/._export.json", b"\x00\x05\x16\x07 AppleDouble", zipfile.ZIP_STORED),
        ("__MACOSX/kidney-health-x/export.json", b"not the export", zipfile.ZIP_STORED),
    ])
    xml = health_xml()
    (tmp / "health_export.xml").write_text(xml, encoding="utf-8")
    a["health"] = build(health_items(xml.encode("utf-8")))

    # 9 not_zip
    a["empty"] = b""
    a["text"] = b"hello world, this is text\n" * 50
    a["truncated"] = good[:-10]
    a["short"] = b"PK\x05\x06" + bytes(17)
    a["comment_too_long"] = good[:-2] + struct.pack("<H", 40)  # the comment length claims 40 bytes that are not there
    a["trailing_junk"] = good + b"JUNK"

    # 10 unsupported
    two = build([deflated("export.json", JSON_DOC), deflated("log.csv", b"a,b\n")])
    a["disk1"] = patch_eocd(two, disk=1)
    a["directory_disk1"] = patch_eocd(two, cd_disk=1)
    a["entries_split"] = patch_eocd(two, entries_disk=1)
    a["encrypted_selected"] = build([Item("export.json", bytes(range(40)), STORED, flags=0x0001), deflated("log.csv", b"a,b\n")])
    a["strong_encryption_selected"] = build([Item("export.json", bytes(range(40)), STORED, flags=0x0040)])
    a["method12_selected"] = build([Item("export.json", b"BZh91AY&SY pretend bzip2", 12, size=300, crc=0)])
    a["method99_selected"] = build([Item("export.json", bytes(range(60)), 99, size=300, crc=0, flags=0x0001)])
    a["other_disk_selected"] = build([stored("export.json", JSON_DOC, disk=1)])
    a["size_2_60"] = build([deflated("export.json", JSON_DOC, size=2**60, comp_size=2**60, zip64=frozenset({"usize", "csize"}))], zip64_end="all")
    a["offset_2_60"] = build(good_items(), zip64_end="all", z64={"cd_offset": 2**60})
    a["locator_two_disks"] = build(good_items(), zip64_end="all", z64={"locator_total": 2})
    a["directory_cap"] = build([], eocd={"cd_size": 33 * MiB})
    a["entries_cap"] = build(good_items(), zip64_end="all", z64={"entries": 200_001, "entries_disk": 200_001})
    a["many_entries"] = build([stored(f"f{i}", b"") for i in range(199_999)] + [deflated("export.json", JSON_DOC)], zip64_end="count")

    # 11 too_big
    a["big_json"] = zipfile_bytes([("export.json", big_doc, zipfile.ZIP_DEFLATED)])

    # 12 damaged
    junk = random.Random(7).randbytes(3000).hex().encode()
    a["short_entry"] = build([Item("export.json", raw_deflate(b"x" * 50), DEFLATE, size=100, crc=zlib.crc32(b"x" * 50))])
    a["bad_crc_deflated"] = build([deflated("export.json", JSON_DOC, crc=zlib.crc32(JSON_DOC) ^ 1)])
    a["bad_crc_stored"] = build([stored("export.json", JSON_DOC, crc=zlib.crc32(JSON_DOC) ^ 0x80000000)])
    flipped = bytearray(JSON_DOC)
    flipped[100] ^= 0x01
    a["bad_data_stored"] = build([Item("export.json", bytes(flipped), STORED, size=len(JSON_DOC), crc=zlib.crc32(JSON_DOC))])
    a["local_name"] = build([deflated("export.json", JSON_DOC, local_name=b"export.jsoN")])
    a["local_method"] = build([deflated("export.json", JSON_DOC, local_method=STORED)])
    a["local_signature"] = b"PK\x03\x05" + good[4:]
    a["offset_past"] = build([deflated("first.txt", b"first\n"), deflated("export.json", JSON_DOC, offset=10**6)])
    a["prefix"] = build(good_items(), prefix=b"MZ" + bytes(100))
    a["prefix_adjusted"] = build(good_items(), prefix=b"MZ" + bytes(100), adjust=True)
    overrun = bytearray(two)
    struct.pack_into("<H", overrun, central_entries(two)[-1] + 28, 0xFFFF)
    a["directory_overrun"] = bytes(overrun)
    cd_start = central_entries(two)[0]
    a["directory_shifted"] = patch_eocd(two, cd_offset=cd_start + 1, cd_size=len(two) - 22 - cd_start - 1)
    a["entries_fewer"] = patch_eocd(two, entries=1, entries_disk=1)
    a["entries_more"] = patch_eocd(two, entries=3, entries_disk=3)
    whole = raw_deflate(junk)
    a["deflate_cut"] = build([Item("export.json", whole[: len(whole) // 2], DEFLATE, size=len(junk), crc=zlib.crc32(junk))])
    a["deflate_garbage"] = build([Item("export.json", b"this is not deflate at all", DEFLATE, size=100, crc=0)])
    a["into_directory"] = build([deflated("export.json", JSON_DOC, comp_size=len(raw_deflate(JSON_DOC)) + 5000)])
    a["zip64_no_locator"] = patch_eocd(good, entries=0xFFFF, entries_disk=0xFFFF)
    broken = bytearray(good)
    struct.pack_into("<I", broken, central_entries(good)[0] + 24, MAX32)  # size says "see the extra field", which is not there
    a["zip64_no_extra"] = bytes(broken)
    a["zip64_extra_short"] = build([deflated("export.json", JSON_DOC, zip64=frozenset({"usize", "csize"}), trim=8)], zip64_end="all")
    a["zip64_record_misplaced"] = build(good_items(), zip64_end="all", z64={"rec_size": 54})
    a["empty_deflate_data"] = build([Item("export.json", b"", DEFLATE, size=0, crc=0)])
    a["bad_utf8"] = build([stored("export.json", b'{"a": "\xff\xfe"}')])
    zeros = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = b"".join(zeros.compress(bytes(MiB)) for _ in range(100)) + zeros.flush()  # 100 MiB of zeros, a few hundred KB packed
    a["bomb"] = build([Item("export.json", bomb, DEFLATE, size=1024, crc=zlib.crc32(bytes(1024)))])

    # 13 missing and ambiguous
    a["no_export"] = zipfile_bytes([("log.csv", b"a,b\n", zipfile.ZIP_DEFLATED), ("README.txt", b"hello", zipfile.ZIP_STORED)])
    a["two_exports"] = zipfile_bytes([("a/export.json", JSON_DOC, zipfile.ZIP_DEFLATED), ("b/export.json", JSON_DOC, zipfile.ZIP_DEFLATED)])
    a["depth_zero_and_one"] = zipfile_bytes([("export.json", JSON_DOC, zipfile.ZIP_DEFLATED), ("a/export.json", JSON_DOC, zipfile.ZIP_DEFLATED)])
    a["too_deep"] = zipfile_bytes([("a/b/export.json", JSON_DOC, zipfile.ZIP_DEFLATED)])
    a["only_macosx"] = zipfile_bytes([("__MACOSX/._export.json", b"x", zipfile.ZIP_STORED), ("__MACOSX/export.json", b"x", zipfile.ZIP_STORED),
                                      ("._export.json", b"x", zipfile.ZIP_STORED)])
    a["empty_archive"] = zipfile_bytes([])

    # 15 browser
    a["deflated_export"] = zipfile_bytes([("export.json", JSON_DOC, zipfile.ZIP_DEFLATED)])
    a["stored_export"] = zipfile_bytes([("export.json", JSON_DOC, zipfile.ZIP_STORED)])

    a["rules"] = build([stored(name, b"") for name in RULE_NAMES])
    return a


def run_node(*args: str, timeout: int) -> dict:
    assert shutil.which("node"), "Node.js 22 is needed to run the zip reader checks (CLAUDE.md, Parity): install it and run again"
    done = subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> dict:
    folder = tmp_path_factory.mktemp("zips")
    data = archives(folder)
    for name, content in data.items():
        (folder / f"{name}.zip").write_bytes(content)
    return {"dir": folder, "data": data}


@pytest.fixture(scope="module")
def seen(made) -> dict:
    """What the module did with each archive (about 10 seconds)."""
    return run_node(str(RUNNER), str(made["dir"]), timeout=300)


@pytest.fixture(scope="module")
def large(tmp_path_factory) -> dict:
    """The 64 MB export.xml in a zip, read under a memory bound, and the abort checks (about 10 seconds)."""
    folder = tmp_path_factory.mktemp("large")
    expected = build_large(folder / "large.zip")
    (folder / "big_json.zip").write_bytes(zipfile_bytes([("export.json", b'{"a": "' + b"x" * (20 * MiB) + b'"}', zipfile.ZIP_DEFLATED)]))
    return {"expected": expected, **run_node("--expose-gc", str(RUNNER), str(folder), "--large", timeout=300)}


# --------------------------------------------------------------------------- the module itself
def test_the_builder_makes_archives_python_reads_too(made) -> None:
    """The hand-written builder is checked against zipfile: the shapes it makes are valid zips (the odd entries aside)."""
    data = made["data"]
    with zipfile.ZipFile(io.BytesIO(data["health"])) as z:
        assert z.read("apple_health_export/export.xml") == (made["dir"] / "health_export.xml").read_bytes()
        assert z.read("apple_health_export/clinical-records/Observation-2.json") == CLINICAL["apple_health_export/clinical-records/Observation-2.json"]
        assert z.getinfo("apple_health_export/workout-routes/encrypted.gpx").flag_bits & 1
    for name, payload in zip64_payloads().items():
        for key in ("zip64", "zip64_count_only"):
            with zipfile.ZipFile(io.BytesIO(data[key])) as z:
                assert z.read(name) == payload, (key, name)
    with zipfile.ZipFile(io.BytesIO(data["many_entries"])) as z:
        assert len(z.namelist()) == 200_000 and z.namelist()[-1] == "export.json"
    with zipfile.ZipFile(io.BytesIO(data["cp437"])) as z:
        assert z.namelist()[0] == "café.txt"  # what a reader that honours code page 437 sees
    with zipfile.ZipFile(io.BytesIO(data["descriptor"])) as z:
        assert all(info.flag_bits & 0x08 for info in z.infolist())  # the data descriptor (bit 3) is really there
    with zipfile.ZipFile(io.BytesIO(data["mixed"])) as z:
        assert z.getinfo("données/été-☕.txt").flag_bits & 0x800  # the UTF-8 name flag (bit 11)
    assert zlib.crc32(JSON_DOC) == zipfile.ZipFile(io.BytesIO(data["deflated_export"])).getinfo("export.json").CRC


# --------------------------------------------------------------------------- archives it must read
def test_case_1_the_apps_own_export_is_read_to_the_same_text_the_server_wrote(seen, made) -> None:
    with zipfile.ZipFile(io.BytesIO(made["data"]["app_export"])) as z:
        names, wrote = z.namelist(), z.read("export.json").decode("utf-8")
    one = seen["case1"]
    assert one["names"] == names and one["found"] == "export.json" and names[0] == "export.json"
    assert one["text"] == wrote and one["size"] == len(wrote.encode("utf-8")) > 50_000
    doc = json.loads(one["text"])
    assert doc["format"] == "kidney-health-export" and len(doc["log_entries"]) == 250
    assert "Crème brûlée — “fancy” 🍮" in one["text"] and "été ☕ 7 " in one["text"]  # UTF-8 comes through, multi-byte characters intact


def test_case_2_stored_deflated_empty_and_non_ascii_entries(seen) -> None:
    rows = {row["name"]: row for row in seen["case2"]["mixed"]}
    expected = {name: payload for name, payload, _ in mixed_entries()}
    assert list(rows) == [name for name, _, _ in mixed_entries()]
    for name, payload in expected.items():
        assert rows[name].get("error") is None, name
        assert (rows[name]["bytes"], rows[name]["sha256"]) == (len(payload), sha(payload)), name
    assert rows["stored.txt"]["method"] == 0 and rows["deflated.txt"]["method"] == 8
    assert rows["empty_stored.txt"]["bytes"] == 0 and rows["empty_deflated.txt"]["bytes"] == 0
    assert rows["données/été-☕.txt"]["method"] == 8  # a name with the UTF-8 flag
    assert rows["random.bin"]["compressedSize"] >= 70_000  # incompressible data: deflate's stored blocks


def test_case_2_a_name_in_code_page_437_is_read_as_utf_8_without_failing(seen) -> None:
    rows = seen["case2"]["cp437"]
    assert [r["name"] for r in rows] == ["caf�.txt", "plain.txt"]  # the byte 0x82 is not UTF-8: a replacement character, no error
    assert rows[0]["sha256"] == sha(b"code page 437 name\n") and rows[1]["sha256"] == sha(b"plain\n")


def test_case_3_a_data_descriptor_is_not_needed_because_the_directory_has_the_real_sizes(seen) -> None:
    rows = {row["name"]: row for row in seen["case3"]["entries"]}
    for name, payload, _ in descriptor_entries():
        assert (rows[name]["size"], rows[name]["sha256"]) == (len(payload), sha(payload)), name


def test_case_4_zip64_values_in_the_extra_field_and_in_the_end_records(seen) -> None:
    for key in ("case4_zip64", "case4_zip64_count_only"):
        rows = {row["name"]: row for row in seen[key]["entries"]}
        assert set(rows) == set(zip64_payloads()), key
        for name, payload in zip64_payloads().items():
            assert rows[name].get("error") is None and (rows[name]["bytes"], rows[name]["sha256"]) == (len(payload), sha(payload)), (key, name)


def test_case_5_an_end_record_inside_the_comment_is_skipped(seen) -> None:
    rows = {row["name"]: row for row in seen["case5"]["entries"]}
    assert rows["export.json"]["sha256"] == sha(JSON_DOC) and rows["log.csv"]["sha256"] == sha(b"a,b\n")
    # and so is one inside the longest comment a zip can have (65,535 bytes), where the end record is 65,557 bytes from the end
    assert [(r["name"], r["sha256"]) for r in seen["case5"]["max"]] == [("export.json", sha(JSON_DOC))]


def test_case_6_a_re_zipped_folder_with_the_macos_extras(seen) -> None:
    six = seen["case6"]
    assert six["found"] == "kidney-health-x/export.json" and six["matches"] == ["kidney-health-x/export.json"]
    assert six["text"] == JSON_DOC.decode("utf-8") and len(six["names"]) == 8


def test_case_7_a_health_shaped_archive_with_an_encrypted_entry_that_nobody_selects(seen, made) -> None:
    seven = seen["case7"]
    xml = (made["dir"] / "health_export.xml").read_bytes()
    assert seven["xml"] == "apple_health_export/export.xml" and seven["xmlSize"] == len(xml) > 400_000
    assert seven["sameRows"] is True  # the same rows as the same text read by itself
    assert seven["weights"] > 100 and seven["readings"] > 100 and seven["chars"] == len(xml.decode("utf-8"))
    assert seven["summary"]["skipped"]["badEntity"] > 0 and seven["summary"]["sourceNames"] == ["Cuff App", "Health", "Zoë’s scale"]
    assert seven["cda"] == "apple_health_export/export_cda.xml"  # export_cda.xml is found by its own rule and is not export.xml
    assert seven["records"] == list(CLINICAL)  # in directory order, the clinical-records folder only
    assert seven["texts"] == {name: payload.decode("utf-8") for name, payload in CLINICAL.items()}
    # the encrypted file and the bzip2 file are refused when selected, and only then
    for label in ("encrypted", "bzip2"):
        for step in ("found", "stream", "text"):
            assert (seven["refused"][label][step]["code"], seven["refused"][label][step]["zip"]) == ("unsupported", True), (label, step)
    others = {row["name"]: row for row in seven["others"]}
    assert others["apple_health_export/workout-routes/route_1.gpx"]["sha256"] == sha(b"<gpx/>")
    assert others["apple_health_export/export.xml"]["sha256"] == sha(xml)
    assert "apple_health_export/workout-routes/encrypted.gpx" not in others


def test_case_8_a_64_mb_entry_is_read_in_pieces_with_exact_results_and_bounded_memory(large) -> None:
    eight, want = large["case8"], large["expected"]
    assert eight["size"] == want["size"] > 60 * MiB and eight["compressedSize"] < eight["size"] // 4
    assert (eight["weights"], eight["kgHundredths"], eight["readings"], eight["systolicSum"]) == (want["weights"], want["kg_hundredths"], want["readings"], want["systolic_sum"])
    assert eight["chars"] == want["size"]  # ASCII: every byte is a character, none lost between pieces
    assert eight["chunks"] > 1000  # it came in pieces (the inflater's chunks), not whole
    assert eight["gc"] is True
    # The whole entry is 64 MB. Held whole, the heap or the buffers would grow by more than that; they stay far under it.
    assert eight["peakHeapGrowthMb"] < 24, eight
    assert eight["peakBuffersGrowthMb"] < 24, eight
    assert eight["retainedHeapMb"] < 10, eight


def test_case_8_the_inflater_does_not_run_ahead_of_the_reader(large) -> None:
    back = large["case8b"]
    assert back["size"] > 60 * MiB
    # after three pieces were read and nobody read more for half a second, only a small amount more was inflated, not the 64 MB
    assert back["inflatedWhileIdle"] - back["consumed"] < 4 * MiB, back
    assert back["files"]["streams"] == 1 and back["files"]["left"] == 0  # and cancelling the reader let go of the file


# --------------------------------------------------------------------------- archives it must refuse
def test_case_9_not_a_zip(seen) -> None:
    for name, result in seen["case9"].items():
        assert (result["ok"], result["name"], result["code"], result["zip"]) == (False, "ZipError", "not_zip", True), name


@pytest.mark.parametrize("name", ["disk1", "directory_disk1", "entries_split", "locator_two_disks"])
def test_case_10_an_archive_split_over_several_files_is_unsupported_when_opened(seen, name) -> None:
    result = seen["case10"][name]
    assert (result["stage"], result["code"]) == ("open", "unsupported"), result
    assert "several files" in result["message"]


@pytest.mark.parametrize("name", ["encrypted_selected", "strong_encryption_selected", "method12_selected", "method99_selected", "other_disk_selected"])
def test_case_10_an_odd_entry_is_unsupported_when_a_rule_selects_it(seen, name) -> None:
    result = seen["case10"][name]
    assert (result["stage"], result["code"], result["zip"]) == ("find", "unsupported", True), result  # the archive itself opens


@pytest.mark.parametrize("name", ["size_2_60", "offset_2_60"])
def test_case_10_a_64_bit_value_above_two_to_the_53_is_unsupported(seen, name) -> None:
    result = seen["case10"][name]
    assert (result["stage"], result["code"]) == ("open", "unsupported"), result
    assert "too large" in result["message"]


def test_case_10_the_caps_on_the_directory_and_the_entry_count(seen) -> None:
    ten = seen["case10"]
    assert (ten["directory_cap"]["stage"], ten["directory_cap"]["code"]) == ("open", "unsupported") and "too many files" in ten["directory_cap"]["message"]
    assert (ten["entries_cap"]["stage"], ten["entries_cap"]["code"]) == ("open", "unsupported") and "too many files" in ten["entries_cap"]["message"]
    assert ten["constants"] == {"MAX_DIRECTORY_BYTES": 32 * MiB, "MAX_ENTRIES": 200_000, "DEFAULT_TEXT_BYTES": 16 * MiB}
    # 200,000 entries is allowed (and 65,536 or more needs the zip64 count, which this archive has)
    assert ten["many_entries"]["ok"] is True and ten["many_entries"]["text"] == JSON_DOC.decode("utf-8")


def test_case_11_too_big_is_refused_before_anything_is_read(seen) -> None:
    eleven = seen["case11"]
    assert eleven["size"] > 16 * MiB and eleven["size"] < 18 * MiB
    for key in ("refused", "refusedStream", "refusedDefault"):
        assert (eleven[key]["code"], eleven[key]["zip"]) == ("too_big", True), key
    assert eleven["slicesByRefusals"] == []  # not one range of the file was asked for
    # open() read only the end of the file (65,577 bytes at most) and the directory, never the data
    assert eleven["blobSize"] > 1 * MiB
    assert all(start >= eleven["blobSize"] - 65_577 and end <= eleven["blobSize"] for start, end in eleven["slicesByOpen"]), eleven["slicesByOpen"]
    assert eleven["allowed"]["ok"] is True and eleven["allowed"]["value"] > 16 * MiB // 2  # the same entry reads with a bigger cap


DAMAGED_WHY = {
    "short_entry": "smaller than the directory says",
    "bad_crc_deflated": "checksum", "bad_crc_stored": "checksum", "bad_data_stored": "checksum",
    "local_name": "does not match the directory", "local_method": "does not match the directory", "local_signature": "file header is missing",
    "offset_past": "outside the file", "prefix": "not where the end record says", "prefix_adjusted": "in front of the first file",
    "directory_overrun": "past the end of the directory", "directory_shifted": "broken entry", "entries_fewer": "holds more than the end record counts",
    "entries_more": "broken entry", "into_directory": "outside the file", "zip64_no_locator": "zip64 locator is missing",
    "zip64_no_extra": "zip64 extra field is missing", "zip64_extra_short": "zip64 extra field is too short",
    "zip64_record_misplaced": "wrong size",
}


@pytest.mark.parametrize("name", sorted(DAMAGED_WHY))
def test_case_12_each_kind_of_damage_is_refused_for_its_own_reason(seen, name) -> None:
    result = seen["case12"][name]
    assert (result["ok"], result["name"], result["code"], result["zip"]) == (False, "ZipError", "damaged", True), result
    assert DAMAGED_WHY[name] in result["message"], result["message"]
    assert result["stage"] == ("read" if name in {"short_entry", "bad_crc_deflated", "bad_crc_stored", "bad_data_stored", "local_name", "local_method", "local_signature"} else "open")


@pytest.mark.parametrize("name", ["deflate_cut", "deflate_garbage", "empty_deflate_data"])
def test_case_12_a_deflate_stream_that_is_cut_or_not_deflate_is_damaged_not_a_type_error(seen, name) -> None:
    result = seen["case12"][name]
    assert (result["stage"], result["name"], result["code"], result["zip"]) == ("read", "ZipError", "damaged", True), result


def test_case_12_an_entry_that_inflates_past_its_declared_size_is_stopped_after_the_first_chunk(seen) -> None:
    bomb = seen["case12"]["bomb"]
    assert (bomb["failure"]["code"], bomb["failure"]["zip"]) == ("damaged", True)
    assert bomb["declared"] == 1024 and bomb["compressed"] > 100_000  # a 100 MiB run of zeros, declared as 1 KiB
    assert bomb["received"] <= 1024  # the chunk that passed the declared size was not handed on
    assert bomb["inflated"] < 2 * MiB, bomb  # the inflater was stopped near the start, not run to 100 MiB
    assert bomb["files"]["streams"] == 1 and bomb["files"]["left"] == 0  # and the file's stream was let go of (cancelled, or already read to the end)
    assert (seen["case12"]["bomb_text"]["result"]["code"], seen["case12"]["bomb_text"]["inflated"] < 2 * MiB) == ("damaged", True)


def test_case_12_bytes_that_are_not_utf_8_are_damaged_for_text_but_not_for_stream(seen) -> None:
    result = seen["case12"]["bad_utf8"]
    assert result["text"]["code"] == "damaged" and result["stream"]["ok"] is True and result["stream"]["value"]["bytes"] == 11


def test_case_13_missing_and_ambiguous(seen) -> None:
    thirteen = seen["case13"]
    for name in ("no_export", "too_deep", "only_macosx", "empty_archive"):
        assert (thirteen[name]["stage"], thirteen[name]["code"]) == ("find", "missing"), name
    for name in ("two_exports", "depth_zero_and_one"):
        assert (thirteen[name]["stage"], thirteen[name]["code"]) == ("find", "ambiguous"), name


def test_case_14_an_abort_rejects_with_an_abort_error_and_cancels_the_file(large) -> None:
    fourteen = large["case14"]
    for key in ("between", "waiting"):
        nxt = fourteen[key]["next"]
        assert (nxt["ok"], nxt["name"], nxt["domException"]) == (False, "AbortError", True), key
    # the file is let go of: no stream of it is left open half-read (cancelled, or read to the end already)
    assert fourteen["between"]["files"]["streams"] == 1 and fourteen["between"]["files"]["left"] == 0
    assert fourteen["waiting"]["files"]["streams"] == 0  # aborted before the first byte was asked for: the file was not opened
    scan = fourteen["scan"]
    assert (scan["result"]["name"], scan["progressCalls"]) == ("AbortError", 2) and scan["files"]["streams"] == 1 and scan["files"]["left"] == 0
    assert (fourteen["before"]["result"]["name"], fourteen["before"]["slices"]) == ("AbortError", 0)  # an already aborted signal reads nothing
    assert fourteen["text"]["name"] == "AbortError"
    assert fourteen["cancel"]["files"]["streams"] == 1 and fourteen["cancel"]["files"]["left"] == 0


def test_case_15_without_decompressionstream_a_deflated_entry_is_browser_and_a_stored_one_still_reads(seen) -> None:
    fifteen = seen["case15"]
    assert fifteen["here"] is True and fifteen["restored"] is True
    assert fifteen["supported"] is False
    assert (fifteen["deflated"]["stage"], fifteen["deflated"]["code"]) == ("read", "browser")
    assert fifteen["stored"]["ok"] is True and fifteen["stored"]["text"] == JSON_DOC.decode("utf-8")
    # an older Safari has the constructor but not the format
    assert fifteen["oldSafari"]["supported"] is False and fifteen["oldSafari"]["deflated"]["code"] == "browser"


# --------------------------------------------------------------------------- choosing entries
def test_the_rules_choose_by_folder_depth_and_exact_name(seen) -> None:
    rules = seen["rules"]
    assert rules["names"] == RULE_NAMES
    assert rules["exportJson"] == ["export.json", "a/export.json", "/export.json", "//x/export.json"]
    assert rules["healthXml"] == ["apple_health_export/export.xml", "export.xml"]
    assert rules["healthCda"] == ["apple_health_export/export_cda.xml"]
    assert rules["clinicalRecords"] == ["apple_health_export/clinical-records/Observation-1.json", "clinical-records/Observation-2.json"]
    assert rules["frozen"] is True
    assert rules["badRule"] == "TypeError" and rules["foreignEntry"] == "TypeError"


# --------------------------------------------------------------------------- the file itself
def test_the_module_is_a_plain_script_with_no_network_dom_or_stream_iteration() -> None:
    code = re.sub(r"/\*.*?\*/", "", ENGINE, flags=re.S)
    code = re.sub(r"//.*", "", code)
    assert code.lstrip().startswith("(function (root) {") and "'use strict';" in code
    assert ENGINE.rstrip().endswith("})(typeof window !== 'undefined' ? window : globalThis);")
    for word in ("document", "window.", "innerHTML", "fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "importScripts", "eval(", "new Function",
                 "localStorage", "sessionStorage", "indexedDB", "console", "Worker("):
        assert word not in code, word
    assert "for await" not in code  # Safari cannot iterate a ReadableStream: getReader() loops only
    assert code.count("getReader()") >= 2
    assert "KH.zip = {" in code and "typeof window !== 'undefined'" in ENGINE


def test_the_limits_and_codes_in_the_header_are_the_notes() -> None:
    header = ENGINE[: ENGINE.index("(function (root)")]
    assert re.search(r"const MAX_DIRECTORY_BYTES = 32 \* 1024 \* 1024;", ENGINE) and re.search(r"const MAX_ENTRIES = 200000;", ENGINE)
    assert "MAX_DIRECTORY_BYTES (32 MiB)" in header and "MAX_ENTRIES (200,000)" in header and "DEFAULT_TEXT_BYTES, 16 MiB" in header
    table = NOTE[NOTE.index("`ZipError.code` is one of"):NOTE.index("### 4.2")]
    codes = re.findall(r"^\| `([a-z_]+)` \|", table, re.M)
    assert codes == ["not_zip", "unsupported", "missing", "ambiguous", "too_big", "damaged", "browser"]
    for code in codes:
        assert re.search(rf"^     {code}\s", header, re.M), code  # the header says what each code means
    for fact in ("PK\\x05\\x06", "getBigUint64", "Number.MAX_SAFE_INTEGER", "0x0001", "__MACOSX", "._", "CRC-32", "WITHOUT passing that chunk on",
                 "AbortError", "Safari cannot iterate a ReadableStream", "fatal: true"):
        assert fact in header, fact


def test_index_html_and_the_service_worker_list_it_before_the_three_views(tmp_path: Path) -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="([^"]+)"', index)
    at = scripts.index("js/engine/zip.js")
    for view in ("js/views/settings.js", "js/views/body_import.js", "js/views/lab_fhir.js"):
        assert at < scripts.index(view), view
    assert scripts.count("js/engine/zip.js") == 1 and at < scripts.index("js/core.js")  # it needs nothing, so it can sit with the other engines
    assert "'/js/engine/zip.js'," in (STATIC / "sw.js").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(builder)
    fragment = builder.build_fragment(static_dir=STATIC)
    assert "/* js/engine/zip.js */" in fragment and ENGINE.strip() in fragment and fragment.count("KH.zip = {") == 1
    site = tmp_path / "site"
    builder.build_pages(site, static_dir=STATIC)
    assert (site / "js" / "engine" / "zip.js").read_bytes() == ENGINE_PATH.read_bytes()
    page = (site / "index.html").read_text(encoding="utf-8")
    assert page.index('<script src="js/engine/zip.js">') < page.index('<script src="js/views/settings.js">')
