"""Photo uploads are checked and rewritten before they go anywhere (note 04 §9 A4, note 03 §9 B1, note 01
§10 S5). Pure: bytes in, bytes out; nothing is decoded, written to disk or logged.

The server never decodes a photo, but the vision backend does, in C/C++ (Ollama, llama.cpp, the model
behind Hermes): a 52800×44 image overflowed llama.cpp's ``clip.cpp`` stack in a public proof of
concept, and a 4 MiB JPEG can declare 65535×65535 pixels. The phone re-encodes photos (EXIF and GPS
gone), but any signed-in person can call the route directly, so the server enforces its own rules:

* **JPEG only**: ``Content-Type: image/jpeg`` and the ``FF D8 FF`` start; at most ``MAX_IMAGE_BYTES``
  (checked from ``Content-Length`` before reading and counted while reading, in :mod:`app.vision`);
* a **marker walk** that accepts only the segments a plain photo needs: ``APP0`` (JFIF), ``DQT``,
  ``DHT``, ``DRI``, exactly **one** ``SOF0``/``SOF1``/``SOF2`` frame (8-bit, 1 or 3 components), one
  or more ``SOS`` scans with their entropy-coded data, and ``EOI``;
* **16–2048 px** per side, aspect ratio at most **4:1**, at most **4 megapixels**;
* **removes** every ``APP1``–``APP15`` segment (EXIF, XMP, ICC, maker notes, GPS), every ``COM`` and
  every byte after ``EOI``; the rewritten bytes are what is forwarded (:class:`CheckedImage`).

Anything else (a truncated file, arithmetic or lossless coding, a second frame, an unknown marker,
``DNL``) is refused with a reason code the route turns into 413, 415 or 422.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

MIN_SIDE = 16
MAX_SIDE = 2048
MAX_ASPECT = 4.0
MAX_PIXELS = 4_000_000
JPEG_MAGIC = b"\xff\xd8\xff"

SOI, EOI, SOS, DQT, DHT, DRI, APP0, COM = 0xD8, 0xD9, 0xDA, 0xDB, 0xC4, 0xDD, 0xE0, 0xFE
SOF_ALLOWED = frozenset({0xC0, 0xC1, 0xC2})  # baseline, extended sequential, progressive (Huffman)
KEEP = frozenset({APP0, DQT, DHT, DRI})
STRIP = frozenset(range(0xE1, 0xF0)) | {COM}  # APP1–APP15 and comments
RST = frozenset(range(0xD0, 0xD8))


class ImageRejected(ValueError):
    """The upload is not a photo the server forwards. ``status`` is 413, 415 or 422; ``reason`` a code."""

    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class CheckedImage:
    data: bytes  # the rewritten JPEG (metadata and trailing bytes removed)
    width: int
    height: int
    removed_segments: int
    original_bytes: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def audit_copy(self) -> dict[str, object]:
        """What the AI activity log keeps instead of the photo (note 04 R4 "Images are not stored")."""
        return {"image_sha256": self.sha256, "bytes": len(self.data), "width": self.width, "height": self.height}


def _bad(reason: str, message: str) -> ImageRejected:
    return ImageRejected(422, reason, message)


def _check_frame(payload: bytes) -> tuple[int, int]:
    if len(payload) < 6:
        raise _bad("malformed", "The photo's frame header is cut short.")
    precision, height, width, components = struct.unpack(">BHHB", payload[:6])
    if precision != 8:
        raise _bad("unsupported", "Only 8-bit JPEG photos are accepted.")
    if components not in (1, 3) or len(payload) < 6 + 3 * components:
        raise _bad("unsupported", "Only greyscale or colour (YCbCr) JPEG photos are accepted.")
    if height == 0 or width == 0:
        raise _bad("dimensions", "The photo does not say how big it is.")
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise _bad("dimensions", f"The photo must be {MIN_SIDE} to {MAX_SIDE} pixels on each side (it is {width}×{height}).")
    if max(width, height) > MAX_ASPECT * min(width, height):
        raise _bad("dimensions", "The photo is too long and thin (more than 4:1).")
    if width * height > MAX_PIXELS:
        raise _bad("dimensions", "The photo has more than 4 megapixels; take it again or let the app shrink it.")
    return width, height


def _entropy_end(data: bytes, pos: int) -> int:
    """Index of the marker that ends the entropy-coded data starting at ``pos`` (stuffed ``FF 00``,
    restart markers and fill bytes are part of the data)."""
    n = len(data)
    while True:
        i = data.find(b"\xff", pos)
        if i == -1 or i + 1 >= n:
            raise _bad("truncated", "The photo ends in the middle of the picture data.")
        nxt = data[i + 1]
        if nxt == 0x00 or nxt in RST:
            pos = i + 2
            continue
        if nxt == 0xFF:
            pos = i + 1
            continue
        return i


def check_jpeg(data: bytes, *, max_bytes: int) -> CheckedImage:
    """Check ``data`` and return the rewritten JPEG (:class:`ImageRejected` otherwise)."""
    if len(data) > max_bytes:
        raise ImageRejected(413, "too_large", f"The photo is larger than {max_bytes // 1024} KiB.")
    if not data.startswith(JPEG_MAGIC):
        raise ImageRejected(415, "not_jpeg", "Send the photo as a JPEG (image/jpeg).")
    out = bytearray(b"\xff\xd8")
    pos = 2
    n = len(data)
    frame: tuple[int, int] | None = None
    scans = 0
    removed = 0
    while True:
        if pos >= n:
            raise _bad("truncated", "The photo ends before its end marker.")
        if data[pos] != 0xFF:
            raise _bad("malformed", "The photo's structure is not valid JPEG.")
        while pos < n and data[pos] == 0xFF:  # fill bytes before a marker
            pos += 1
        if pos >= n:
            raise _bad("truncated", "The photo ends before its end marker.")
        marker = data[pos]
        pos += 1
        if marker == EOI:
            if frame is None or scans == 0:
                raise _bad("malformed", "The photo has no picture data.")
            out += b"\xff\xd9"
            if pos < n:
                removed += 1  # bytes after the end marker (appended data) are dropped
            break
        if marker == SOI or marker in RST or marker == 0x01:
            raise _bad("malformed", "The photo's structure is not valid JPEG.")
        if pos + 2 > n:
            raise _bad("truncated", "The photo ends in the middle of a segment.")
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > n:
            raise _bad("truncated", "The photo ends in the middle of a segment.")
        segment = data[pos - 2:pos + length]  # FF xx + length + payload
        payload = data[pos + 2:pos + length]
        pos += length
        if marker in STRIP:
            removed += 1
            continue
        if marker in SOF_ALLOWED:
            if frame is not None:
                raise _bad("malformed", "The photo holds more than one picture.")
            frame = _check_frame(payload)
            out += segment
            continue
        if marker == SOS:
            if frame is None:
                raise _bad("malformed", "The photo's picture data comes before its frame header.")
            end = _entropy_end(data, pos)
            out += segment + data[pos:end]
            pos = end
            scans += 1
            continue
        if marker in KEEP:
            out += segment
            continue
        raise _bad("unsupported", "The photo uses a JPEG feature this app does not accept; take it again with the camera app.")
    assert frame is not None
    return CheckedImage(bytes(out), frame[0], frame[1], removed, len(data))
