"""``app/imagecheck.py`` (note 04 §9 A4, note 03 §9 B1): JPEG only, metadata and trailing bytes removed,
16–2048 px per side, aspect ≤ 4:1, ≤ 4 megapixels, one frame. The fixtures are drawn by
``tests/fixtures/ai/make_images.py``; the bad cases are built from them byte by byte."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from app.imagecheck import ImageRejected, check_jpeg

IMAGES = Path(__file__).resolve().parent / "fixtures" / "ai" / "images"
LIMIT = 4 * 1024 * 1024


def load(name: str) -> bytes:
    return (IMAGES / name).read_bytes()


def markers(data: bytes) -> list[int]:
    """Marker bytes in segment order (stops at SOS: the scan data is not walked here)."""
    out, pos = [], 2
    while pos < len(data):
        assert data[pos] == 0xFF
        marker = data[pos + 1]
        out.append(marker)
        if marker == 0xDA:
            break
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        pos += 2 + length
    return out


def sof_offset(data: bytes) -> int:
    pos = 2
    while True:
        marker = data[pos + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return pos
        pos += 2 + struct.unpack(">H", data[pos + 2:pos + 4])[0]


def with_size(data: bytes, width: int, height: int) -> bytes:
    at = sof_offset(data) + 5  # FF Cx, length (2), precision (1), then height, width
    return data[:at] + struct.pack(">HH", height, width) + data[at + 4:]


def reject(data: bytes, status: int, reason: str, limit: int = LIMIT) -> None:
    with pytest.raises(ImageRejected) as info:
        check_jpeg(data, max_bytes=limit)
    assert (info.value.status, info.value.reason) == (status, reason), str(info.value)


def test_metadata_is_removed_and_the_picture_kept():
    data = load("label.jpg")
    assert 0xE1 in markers(data) and 0xFE in markers(data) and b"FixtureCam" in data and b"secret comment" in data
    checked = check_jpeg(data, max_bytes=LIMIT)
    assert (checked.width, checked.height) == (320, 240) and checked.removed_segments == 2
    assert 0xE1 not in markers(checked.data) and 0xFE not in markers(checked.data)
    assert b"FixtureCam" not in checked.data and b"secret comment" not in checked.data and b"Exif" not in checked.data
    assert checked.data.startswith(b"\xff\xd8") and checked.data.endswith(b"\xff\xd9")
    assert len(checked.sha256) == 64 and checked.audit_copy() == {"image_sha256": checked.sha256, "bytes": len(checked.data),
                                                                   "width": 320, "height": 240}
    assert check_jpeg(checked.data, max_bytes=LIMIT).data == checked.data  # idempotent


@pytest.mark.parametrize("name, size", [("progressive.jpg", (200, 150)), ("gray.jpg", (64, 64))])
def test_progressive_and_greyscale_photos_pass_unchanged(name, size):
    data = load(name)
    checked = check_jpeg(data, max_bytes=LIMIT)
    assert (checked.width, checked.height) == size and checked.data == data


def test_trailing_bytes_after_the_end_marker_are_dropped():
    data = load("gray.jpg") + b"PK\x03\x04 hidden zip appended"
    checked = check_jpeg(data, max_bytes=LIMIT)
    assert checked.data.endswith(b"\xff\xd9") and b"hidden" not in checked.data


def test_every_appn_segment_is_removed():
    data = load("gray.jpg")
    extra = b"".join(bytes([0xFF, m]) + struct.pack(">H", 6) + b"XXXX" for m in range(0xE1, 0xF0))
    checked = check_jpeg(data[:2] + extra + data[2:], max_bytes=LIMIT)
    assert checked.removed_segments == 15 and checked.data == data


def test_restart_markers_stuffed_bytes_and_fill_bytes_are_kept():
    data = load("gray.jpg")
    sos = data.index(b"\xff\xda")
    length = struct.unpack(">H", data[sos + 2:sos + 4])[0]
    scan_start = sos + 2 + length
    patched = data[:scan_start] + b"\x12\xff\x00\x34\xff\xd0\x56" + data[scan_start:]
    patched = patched[:sos] + b"\xff" + patched[sos:]  # a fill byte before the SOS marker
    checked = check_jpeg(patched, max_bytes=LIMIT)
    assert b"\x12\xff\x00\x34\xff\xd0\x56" in checked.data


def test_size_cap():
    data = load("label.jpg")
    reject(data, 413, "too_large", limit=len(data) - 1)


@pytest.mark.parametrize("data", [
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
    b"GIF89a" + b"\x00" * 100,
    b"RIFF\x00\x00\x00\x00WEBPVP8 ",
    b"\xff\xd8",                       # too short for the magic
    b"",
    b"<svg xmlns='http://www.w3.org/2000/svg'/>",
])
def test_only_jpeg(data):
    reject(data, 415, "not_jpeg")


@pytest.mark.parametrize("width, height", [(15, 100), (100, 15), (2049, 100), (100, 2049), (52800, 44), (65535, 65535)])
def test_dimension_limits(width, height):
    reject(with_size(load("gray.jpg"), width, height), 422, "dimensions")


def test_aspect_ratio_and_megapixels():
    reject(with_size(load("gray.jpg"), 1000, 200), 422, "dimensions")  # 5:1
    check_jpeg(with_size(load("gray.jpg"), 800, 200), max_bytes=LIMIT)  # exactly 4:1 is fine
    reject(with_size(load("gray.jpg"), 2048, 2048), 422, "dimensions")  # 4.19 MP
    check_jpeg(with_size(load("gray.jpg"), 2000, 2000), max_bytes=LIMIT)  # 4.0 MP
    reject(with_size(load("gray.jpg"), 0, 64), 422, "dimensions")


def test_frame_rules():
    data = load("gray.jpg")
    sof = sof_offset(data)
    lossless = data[:sof + 1] + b"\xc3" + data[sof + 2:]
    reject(lossless, 422, "unsupported")
    twelve_bit = data[:sof + 4] + b"\x0c" + data[sof + 5:]
    reject(twelve_bit, 422, "unsupported")
    length = struct.unpack(">H", data[sof + 2:sof + 4])[0]
    segment = data[sof:sof + 2 + length]
    reject(data[:sof] + segment + data[sof:], 422, "malformed")  # two frames
    cmyk = bytearray(data)
    cmyk[sof + 9] = 4
    reject(bytes(cmyk), 422, "unsupported")
    short = data[:sof + 2] + struct.pack(">H", 5) + data[sof + 4:sof + 7] + data[sof + 2 + length:]
    reject(short, 422, "malformed")


def test_structure_errors():
    data = load("gray.jpg")
    reject(data[:-2], 422, "truncated")  # no end marker
    reject(data[: len(data) // 2], 422, "truncated")
    reject(data[:2] + b"\xff\xdc\x00\x04\x00\x40" + data[2:], 422, "unsupported")  # DNL
    reject(data[:2] + b"\xff\xcc\x00\x04\x00\x00" + data[2:], 422, "unsupported")  # arithmetic conditioning
    reject(data[:2] + b"\xff\xd8" + data[2:], 422, "malformed")  # a second SOI
    reject(data[:2] + b"\x00\x00" + data[2:], 415, "not_jpeg")  # the magic is FF D8 FF
    sof = sof_offset(data)
    reject(data[:sof] + b"\x00" + data[sof:], 422, "malformed")  # garbage between segments
    reject(data[:2] + b"\xff\xe1\x00\x01" + data[2:], 422, "truncated")  # length below 2
    reject(data[:2] + b"\xff\xe1\xff\xff" + data[2:], 422, "truncated")  # length beyond the end
    sos = data.index(b"\xff\xda")
    length = struct.unpack(">H", data[sof + 2:sof + 4])[0]
    no_frame = data[:sof] + data[sof + 2 + length:]
    reject(no_frame, 422, "malformed")  # scan before (without) a frame
    assert sos > sof
    reject(b"\xff\xd8\xff\xd9", 422, "malformed")  # no picture at all
