"""A small zip writer for the tests of the zip reader (``js/engine/zip.js``, note 11): archives built at test time, never committed.

Python's ``zipfile`` writes the ordinary shapes (see :func:`zipfile_bytes`, :class:`Unseekable` for a data descriptor). :func:`build`
writes the ones ``zipfile`` cannot: a zip64 directory without 4 GB of data, a lying size, a flipped CRC, a name that differs between the
local header and the directory, a fake or misplaced end record, an encrypted or bzip2 entry, a prefix in front of the first entry."""
from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib
from dataclasses import dataclass, field, replace

MiB = 1024 * 1024
MAX32 = 0xFFFFFFFF
STORED, DEFLATE = 0, 8


@dataclass
class Item:
    """One entry. ``data`` is what the archive holds after the header: raw deflate, stored bytes, or whatever a lie needs."""

    name: bytes | str
    data: bytes = b""
    method: int = STORED
    size: int | None = None  # declared uncompressed size (default: len(data))
    crc: int | None = None  # declared CRC-32 (default: crc32(data))
    comp_size: int | None = None  # declared compressed size (default: len(data))
    flags: int = 0
    disk: int = 0
    zip64: frozenset = field(default_factory=frozenset)  # which values go in the 0x0001 extra field: usize, csize, offset, disk
    trim: int = 0  # bytes cut from the end of that extra field's data
    local_name: bytes | None = None  # a different name in the local header
    local_method: int | None = None  # a different method in the local header
    offset: int | None = None  # a different local header offset in the directory


def raw_deflate(data: bytes) -> bytes:
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    return packer.compress(data) + packer.flush()


def stored(name: bytes | str, payload: bytes, **kw) -> Item:
    return replace(Item(name, payload, STORED, len(payload), zlib.crc32(payload)), **kw)


def deflated(name: bytes | str, payload: bytes, **kw) -> Item:
    return replace(Item(name, raw_deflate(payload), DEFLATE, len(payload), zlib.crc32(payload)), **kw)


def build(items: list[Item], *, comment: bytes = b"", zip64_end: str | None = None, prefix: bytes = b"", adjust: bool = False,
          eocd: dict | None = None, z64: dict | None = None) -> bytes:
    """An archive from items. ``zip64_end`` is "all" (every end-record field at its maximum) or "count" (only the entry count, as
    Python's zipfile does past 65,535 entries); ``prefix`` goes in front of the first entry (``adjust`` says whether the offsets
    count it, as a self-extracting archive's tool may); ``eocd`` and ``z64`` replace fields of the end records."""
    eocd, z64 = eocd or {}, z64 or {}
    out = bytearray(prefix)
    base = len(prefix) if adjust else 0

    def here() -> int:
        return len(out) - len(prefix) + base

    central = bytearray()
    for item in items:
        name = item.name.encode("utf-8") if isinstance(item.name, str) else item.name
        size = len(item.data) if item.size is None else item.size
        crc = zlib.crc32(item.data) if item.crc is None else item.crc
        comp = len(item.data) if item.comp_size is None else item.comp_size
        where = here()
        local_name = name if item.local_name is None else item.local_name
        local_method = item.method if item.local_method is None else item.local_method
        out += struct.pack("<4sHHHHHIIIHH", b"PK\x03\x04", 45 if item.zip64 else 20, item.flags, local_method, 0, 0x2C41, crc,
                           min(comp, MAX32), min(size, MAX32), len(local_name), 0)
        out += local_name + item.data
        c_size, c_comp, c_disk = size, comp, item.disk
        c_off = where if item.offset is None else item.offset
        values = b""
        if "usize" in item.zip64:
            c_size, values = MAX32, values + struct.pack("<Q", size)
        if "csize" in item.zip64:
            c_comp, values = MAX32, values + struct.pack("<Q", comp)
        if "offset" in item.zip64:
            values, c_off = values + struct.pack("<Q", c_off), MAX32
        if "disk" in item.zip64:
            values, c_disk = values + struct.pack("<I", item.disk), 0xFFFF
        values = values[: len(values) - item.trim] if item.trim else values
        extra = struct.pack("<HH", 1, len(values)) + values if item.zip64 else b""
        central += struct.pack("<4sHHHHHHIIIHHHHHII", b"PK\x01\x02", 45, 45 if item.zip64 else 20, item.flags, item.method, 0, 0x2C41,
                               crc, min(c_comp, MAX32), min(c_size, MAX32), len(name), len(extra), 0, c_disk, 0, 0, c_off)
        central += name + extra
    cd_offset = here()
    out += central
    n = len(items)
    fields = {"disk": 0, "cd_disk": 0, "entries_disk": n, "entries": n, "cd_size": len(central), "cd_offset": cd_offset}
    if zip64_end:
        z64_at = here()
        rec = {**fields, **{k: v for k, v in z64.items() if k in fields}}
        out += struct.pack("<4sQHHIIQQQQ", b"PK\x06\x06", z64.get("rec_size", 44), 45, 45, rec["disk"], rec["cd_disk"], rec["entries_disk"],
                           rec["entries"], rec["cd_size"], rec["cd_offset"])
        out += struct.pack("<4sIQI", b"PK\x06\x07", z64.get("locator_disk", 0), z64.get("locator_offset", z64_at), z64.get("locator_total", 1))
        fields["entries_disk"] = fields["entries"] = 0xFFFF
        if zip64_end == "all":
            fields["cd_size"] = fields["cd_offset"] = MAX32
    fields.update(eocd)
    out += struct.pack("<4s4H2IH", b"PK\x05\x06", fields["disk"], fields["cd_disk"], fields["entries_disk"], fields["entries"],
                       fields["cd_size"], fields["cd_offset"], len(comment)) + comment
    return bytes(out)


def eocd_at(data: bytes) -> int:
    return data.rindex(b"PK\x05\x06")


def patch_eocd(data: bytes, **changes: int) -> bytes:
    """An archive with fields of its (comment-less) end record replaced."""
    at = eocd_at(data)
    names = ("disk", "cd_disk", "entries_disk", "entries", "cd_size", "cd_offset")
    sig, *values, comment_length = struct.unpack_from("<4s4H2IH", data, at)
    fields = {**dict(zip(names, values)), **changes}
    return data[:at] + struct.pack("<4s4H2IH", sig, *(fields[k] for k in names), comment_length) + data[at + 22:]


def central_entries(data: bytes) -> list[int]:
    """Where each directory entry starts."""
    _, _, _, _, count, _, start, _ = struct.unpack_from("<4s4H2IH", data, eocd_at(data))
    found, pos = [], start
    for _ in range(count):
        found.append(pos)
        name, extra, comment = struct.unpack_from("<HHH", data, pos + 28)
        pos += 46 + name + extra + comment
    return found


def zipfile_bytes(entries: list[tuple[str, bytes, int]], comment: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload, method in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 22, 9, 30, 0))
            info.compress_type = method
            archive.writestr(info, payload)
        archive.comment = comment
    return buffer.getvalue()


class Unseekable(io.RawIOBase):
    """A write-only stream with no tell() or seek(), like a pipe: zipfile then writes a data descriptor (flag bit 3) after each entry."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # noqa: ANN001
        self.parts.append(bytes(data))
        return len(data)

    def tell(self) -> int:
        raise OSError("not seekable")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
