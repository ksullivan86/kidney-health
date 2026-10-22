// A small zip writer for the page tests (tests/js/*_page.mjs): the archives a person would choose, built in memory.
//
//   makeZip([{ name, data, method, crcXor, flags }, ...]) -> Buffer
//
// data is a string (UTF-8) or bytes; method defaults to deflate; crcXor flips bits of the CRC-32 written in the directory (a damaged
// download); flags are the general purpose flag bits (1 = the entry says it is encrypted; its bytes are then whatever data holds).
// Names are UTF-8 (flag bit 11). Not a general writer: no zip64, no comment, no data descriptor. The reader's own tests, with every odd
// shape, are tests/test_zip_reader.py and tests/js/zip_reader.mjs; this one only makes ordinary archives for the screens.
import zlib from 'node:zlib';
import { setTimeout as sleep } from 'node:timers/promises';

const TABLE = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
export function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i += 1) c = TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

export function makeZip(entries) {
  const chunks = [];
  const directory = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, 'utf8');
    const raw = typeof entry.data === 'string' ? Buffer.from(entry.data, 'utf8') : Buffer.from(entry.data || []);
    const method = entry.method === 'store' ? 0 : 8;
    const body = method === 8 ? zlib.deflateRawSync(raw) : raw;
    const crc = (crc32(raw) ^ (entry.crcXor || 0)) >>> 0;
    const flags = 0x0800 | (entry.flags || 0);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(flags, 6); local.writeUInt16LE(method, 8);
    local.writeUInt16LE(0, 10); local.writeUInt16LE(0x2C41, 12); local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(body.length, 18); local.writeUInt32LE(raw.length, 22); local.writeUInt16LE(name.length, 26); local.writeUInt16LE(0, 28);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(flags, 8);
    central.writeUInt16LE(method, 10); central.writeUInt16LE(0, 12); central.writeUInt16LE(0x2C41, 14); central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(body.length, 20); central.writeUInt32LE(raw.length, 24); central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    chunks.push(local, name, body);
    directory.push(central, name);
    offset += local.length + name.length + body.length;
  }
  const dir = Buffer.concat(directory);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(dir.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...chunks, dir, end]);
}

// An export.zip as the file box hands it over: a File-like with name, type, size and slice(), whose streams log what is done with them
// (opened, cancelled, finished, and `over` = how many of the opened ones were cancelled or read to their end). `entries` are makeZip()
// entries, or raw bytes (a file that is not a zip). `chunk` and `delay` make its streams slow, so that Cancel can come while it is read.
export function zipFile(name, entries, { type = 'application/zip', chunk = 0, delay = 0 } = {}) {
  const bytes = Buffer.isBuffer(entries) ? entries : makeZip(entries);
  const blob = new Blob([bytes]);
  const file = { name, type, size: bytes.length, opened: 0, cancelled: 0, finished: 0, over: 0, pulls: 0, slices: [] };
  file.slice = (from, to) => {
    file.slices.push([from, to]);
    const part = blob.slice(from, to);
    return {
      arrayBuffer: () => part.arrayBuffer(),
      stream() {
        file.opened += 1;
        const reader = part.stream().getReader();
        let held = new Uint8Array(0);
        let over = false;
        const end = (what) => { file[what] += 1; if (!over) { over = true; file.over += 1; } };
        return new ReadableStream({
          async pull(controller) {
            file.pulls += 1;
            if (delay) await sleep(delay);
            if (held.length === 0) {
              const r = await reader.read();
              if (r.done) { end('finished'); controller.close(); return; }
              held = r.value;
            }
            const n = chunk > 0 ? chunk : held.length;
            controller.enqueue(held.subarray(0, n));
            held = held.subarray(n);
          },
          cancel(why) { end('cancelled'); return reader.cancel(why); },
        }, { highWaterMark: 0 });
      },
    };
  };
  return file;
}
