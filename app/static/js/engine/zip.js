/* Kidney Diet Log — reading a .zip in the browser (docs/dev/research/11-reading-a-zip-in-the-browser.md). Three imports take the archive
   itself, so that nobody has to unzip it first: Import from a file (export.json inside this app's own export .zip), Weights and blood
   pressure from the Health app (export.xml inside the Health app's export.zip) and Lab results from Apple Health clinical records
   (clinical-records/*.json inside the same file). This module reads the archive HERE, on the device, with what the browser already has
   (Blob.slice, Blob.stream, DecompressionStream('deflate-raw')). No library, no network, nothing is written anywhere, no DOM.

   The archive is not trusted. Memory stays bounded whatever it claims, no size, offset or name is believed until it has been checked, an
   entry that inflates past its declared size or whose CRC-32 does not match is refused WHILE it is being read, and an archive the reader
   does not fully understand is refused with a plain reason, never half-read.

   What is read, and when
   * open(blob) reads only the last 65,577 bytes (the end record and its comment, with room for the zip64 locator) and the central
     directory. Opening a 2 GB archive reads tens of kilobytes. Nothing else is read until an entry is streamed.
   * The end record ("PK\x05\x06") is searched backwards; the one taken is the nearest the end whose comment length reaches exactly the
     end of the file, so a copy of it hidden in a comment is skipped. Disk numbers must be 0 and the entries on this disk must be all
     the entries (an archive split over several files is refused). A field at its maximum (0xFFFF, 0xFFFFFFFF) is read from the zip64 end
     record, which the zip64 locator 20 bytes before the end record points to; a missing locator or record is damaged. 64-bit values are
     read with getBigUint64 and a value above Number.MAX_SAFE_INTEGER is refused.
   * The central directory must end exactly where the end record (or the zip64 end record) starts, so a self-extracting archive, or
     anything else in front of the first entry, is damaged (the lowest local header offset must be 0). It may be at most
     MAX_DIRECTORY_BYTES (32 MiB) long and hold at most MAX_ENTRIES (200,000) entries. Both caps bound memory.
   * Each directory entry ("PK\x01\x02", 46 bytes, then name, extra field and comment) must lie inside the directory; the entries must
     fill it exactly, and their number must be the declared one. The zip64 extra field (id 0x0001) holds, in APPNOTE order, only the
     values that overflowed: uncompressed size, compressed size, local header offset, disk number. Names are decoded as UTF-8 without
     failing: every name a rule looks for is ASCII, and bytes above 0x7F (IBM code page 437 when bit 11 is clear) cannot make an ASCII match.
   * Checks on every entry: localHeaderOffset + 30 <= directory start; compressedSize <= directory start; a stored entry (method 0) has
     compressedSize equal to its size. An encrypted entry (flag bit 0, 6 or 13), a method other than 0 (stored) or 8 (deflate) and an
     entry on another disk are recorded, not refused: they are refused ('unsupported') only when a rule selects them, so a Health export
     with one odd file in workout-routes/ still imports its weights.

   Choosing entries (RULES): a rule matches on the name split at "/" with empty segments dropped, so a leading "/" counts for nothing. The
   name is never used as a path; a name with a "." or ".." segment never matches. Depth is the number of folders above the file (0 = the top
   of the archive). Always ignored: names that end in "/" (folders), a first segment __MACOSX, a last segment starting with "._" (the
   AppleDouble files macOS adds). The basename is compared exactly (case-sensitive).
     RULES.exportJson      export.json, depth 0 or 1 (this app's archive has it at the top; a re-zipped folder one level down)
     RULES.healthXml       export.xml, depth 0 or 1 (apple_health_export/export.xml); export_cda.xml is a different name
     RULES.healthCda       export_cda.xml, depth 0 or 1 (only to tell the person it is the wrong file)
     RULES.clinicalRecords a name ending in .json whose folder is exactly clinical-records, depth 1 or 2
   find() wants exactly one match ('missing' for none, 'ambiguous' for several); list() gives every match, in directory order.

   Reading an entry, stream(archive, entry, {maxBytes, signal}), checked as the bytes come out
   * The declared size is compared with maxBytes first ('too_big'); nothing is read. A selected encrypted entry, odd method or other disk
     is 'unsupported'; a deflated entry without DecompressionStream is 'browser'. These three are thrown at once, before any reading.
   * The local header ("PK\x03\x04") is read: its signature, its name bytes and its method must match the directory's, and the data
     (dataStart = offset + 30 + name + extra field) must end before the directory. Its sizes and CRC are not used (they are zero when
     bit 3 is set, and a data descriptor follows the data); the directory's are. Anything else is 'damaged'.
   * The bytes come from blob.slice(dataStart, dataStart + compressedSize).stream(). A deflated entry is cut into pieces of 16 KiB and
     piped through DecompressionStream('deflate-raw') (the pieces keep a browser that inflates a whole input chunk before it hands any
     out from holding more than 16 MiB at once). Last comes a checking TransformStream that counts the bytes and keeps a running table
     CRC-32 (a 1 KiB table). It fails with 'damaged' the moment the count passes the declared size, WITHOUT passing that chunk on (an
     entry that claims 1 KB and inflates to 10 GB is stopped after the first chunk above 1 KB); at the end a count other than the
     declared size, or a CRC-32 other than the directory's, fails too. A TypeError (or any other error that is not a ZipError, an
     AbortError or an I/O DOMException) from the inflater is 'damaged'.
   * opts.signal aborting cancels the source and rejects the read with a DOMException named AbortError (the Cancel of the Health import).
   * The result is read with getReader() loops, never "for await": Safari cannot iterate a ReadableStream.
   * text() collects a small entry (opts.maxBytes defaults to DEFAULT_TEXT_BYTES, 16 MiB) into one buffer of exactly its declared size and
     decodes it with TextDecoder('utf-8', {fatal: true}); bytes that are not UTF-8 are 'damaged'. A byte order mark is dropped. The big
     export.xml is never read with text(): the import sheet pipes stream() through TextDecoderStream into KH.appleHealth.scan.

   ZipError.code, one of
     not_zip      no valid end record
     unsupported  several disks, an encrypted entry, a method other than 0 or 8 (when selected), a 64-bit value above 2^53 - 1, a
                  directory above 32 MiB or above 200,000 entries
     missing      no entry matches the rule
     ambiguous    more than one entry matches the rule
     too_big      the declared size is above maxBytes
     damaged      any inconsistency: offsets outside the file, a local header that does not match the directory, inflated bytes above or
                  below the declared size, a CRC-32 mismatch, a deflate error, a name that is not UTF-8 in text()
     browser      DecompressionStream('deflate-raw') is missing (supported() is false)

   Plain script: no other module is needed; runs in the page (window.KH.zip) and under Node 22 (tests/js/zip_reader.mjs, with
   globalThis.KH). No DOM. Only the names the archive holds can reach the page's text, and the views set them with textContent. */
(function (root) {
  'use strict';
  const KH = root.KH || (root.KH = {});

  const MAX_DIRECTORY_BYTES = 32 * 1024 * 1024; // the central directory
  const MAX_ENTRIES = 200000;
  const DEFAULT_TEXT_BYTES = 16 * 1024 * 1024; // text() without opts.maxBytes
  const INFLATE_PIECE = 16 * 1024; // bytes of compressed data handed to the inflater at a time

  const SIG_EOCD = 0x06054b50; // PK\x05\x06, the end record
  const SIG_ZIP64_EOCD = 0x06064b50; // PK\x06\x06
  const SIG_ZIP64_LOCATOR = 0x07064b50; // PK\x06\x07
  const SIG_CENTRAL = 0x02014b50; // PK\x01\x02
  const SIG_LOCAL = 0x04034b50; // PK\x03\x04
  const EOCD_SIZE = 22;
  const LOCATOR_SIZE = 20;
  const ZIP64_EOCD_MIN = 56;
  const CENTRAL_SIZE = 46;
  const LOCAL_SIZE = 30;
  const MAX_COMMENT = 0xFFFF;
  const MAX16 = 0xFFFF;
  const MAX32 = 0xFFFFFFFF;
  const EXTRA_ZIP64 = 0x0001;
  const METHOD_STORED = 0;
  const METHOD_DEFLATE = 8;
  const FLAG_ENCRYPTED = 0x0001 | 0x0040 | 0x2000; // encrypted, strong encryption, masked local header

  const REASON = {
    not_zip: 'This is not a .zip file.',
    unsupported: 'This .zip uses something this reader does not handle.',
    missing: 'The .zip has no such file.',
    ambiguous: 'The .zip has more than one such file.',
    too_big: 'The file in the .zip is bigger than this import takes.',
    damaged: 'The .zip is damaged.',
    browser: 'This browser cannot open a .zip.',
  };

  class ZipError extends Error {
    constructor(code, message) {
      super(message || REASON[code] || code);
      this.name = 'ZipError';
      this.code = code;
    }
  }
  const fail = (code, detail) => new ZipError(code, detail ? `${REASON[code]} (${detail})` : REASON[code]);

  const abortError = () => {
    const message = 'The reading was cancelled.';
    return typeof root.DOMException === 'function' ? new root.DOMException(message, 'AbortError') : Object.assign(new Error(message), { name: 'AbortError' });
  };

  /* Entries are matched by these (see "Choosing entries" above). Frozen: the three views share them. */
  const RULES = Object.freeze({
    exportJson: Object.freeze({ basename: 'export.json', maxDepth: 1 }),
    healthXml: Object.freeze({ basename: 'export.xml', maxDepth: 1 }),
    healthCda: Object.freeze({ basename: 'export_cda.xml', maxDepth: 1 }),
    clinicalRecords: Object.freeze({ under: 'clinical-records', suffix: '.json', maxDepth: 2 }),
  });

  // True when this browser can inflate a deflated entry. A stored entry does not need it.
  function supported() {
    try {
      if (typeof root.DecompressionStream !== 'function' || typeof root.TransformStream !== 'function') return false;
      new root.DecompressionStream('deflate-raw');
      return true;
    } catch (e) {
      return false;
    }
  }

  // ---------------------------------------------------------------------------
  // CRC-32 (IEEE, the zip one), a byte at a time with a 256-entry table
  // ---------------------------------------------------------------------------
  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    return table;
  })();
  function crcUpdate(crc, bytes) {
    for (let i = 0; i < bytes.length; i += 1) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return crc;
  }

  // ---------------------------------------------------------------------------
  // Reading the directory
  // ---------------------------------------------------------------------------
  // A 64-bit little-endian value as a number, or 'unsupported' above Number.MAX_SAFE_INTEGER.
  function u64(view, at) {
    const value = view.getBigUint64(at, true);
    if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw fail('unsupported', 'a size or offset is too large');
    return Number(value);
  }

  // The bytes [from, to) of the archive, or 'damaged' when the file is shorter than that (it changed while it was being read).
  async function readBytes(blob, from, to) {
    const buffer = await blob.slice(from, to).arrayBuffer();
    if (buffer.byteLength !== to - from) throw fail('damaged', 'the file ended early');
    return buffer;
  }

  // Where the zip64 values of a central-directory entry are: the data of the first extra field with id 0x0001, or null.
  function zip64Extra(view, from, to) {
    let at = from;
    while (at + 4 <= to) {
      const id = view.getUint16(at, true);
      const size = view.getUint16(at + 2, true);
      if (at + 4 + size > to) throw fail('damaged', 'an extra field is cut short');
      if (id === EXTRA_ZIP64) return { from: at + 4, to: at + 4 + size };
      at += 4 + size;
    }
    return null;
  }

  async function open(blob) {
    if (!blob || typeof blob.size !== 'number' || typeof blob.slice !== 'function') throw new TypeError('open() takes a File or a Blob');
    const size = blob.size;
    if (size < EOCD_SIZE) throw fail('not_zip', 'the file is too short');

    // 1. The end record: the nearest the end whose comment reaches exactly the end of the file.
    const tailLength = Math.min(size, EOCD_SIZE + MAX_COMMENT + LOCATOR_SIZE);
    const tailStart = size - tailLength;
    const tail = new DataView(await readBytes(blob, tailStart, size));
    let at = -1;
    for (let i = tailLength - EOCD_SIZE; i >= 0; i -= 1) {
      if (tail.getUint8(i) === 0x50 && tail.getUint32(i, true) === SIG_EOCD && i + EOCD_SIZE + tail.getUint16(i + 20, true) === tailLength) { at = i; break; }
    }
    if (at < 0) throw fail('not_zip', 'no end record');

    // 2. Its fields. A field at its maximum is read from the zip64 end record.
    let diskNumber = tail.getUint16(at + 4, true);
    let directoryDisk = tail.getUint16(at + 6, true);
    let entriesOnDisk = tail.getUint16(at + 8, true);
    let entryCount = tail.getUint16(at + 10, true);
    let directorySize = tail.getUint32(at + 12, true);
    let directoryStart = tail.getUint32(at + 16, true);
    let endStart = tailStart + at; // where the directory must end
    if ([diskNumber, directoryDisk, entriesOnDisk, entryCount].includes(MAX16) || directorySize === MAX32 || directoryStart === MAX32) {
      const locator = at - LOCATOR_SIZE;
      if (locator < 0 || tail.getUint32(locator, true) !== SIG_ZIP64_LOCATOR) throw fail('damaged', 'the zip64 locator is missing');
      if (tail.getUint32(locator + 4, true) !== 0 || tail.getUint32(locator + 16, true) !== 1) throw fail('unsupported', 'the .zip is split over several files');
      const recordAt = u64(tail, locator + 8);
      const locatorAt = tailStart + locator;
      if (recordAt + ZIP64_EOCD_MIN > locatorAt) throw fail('damaged', 'the zip64 end record is out of place');
      const record = new DataView(await readBytes(blob, recordAt, recordAt + ZIP64_EOCD_MIN));
      if (record.getUint32(0, true) !== SIG_ZIP64_EOCD) throw fail('damaged', 'the zip64 end record is missing');
      const recordSize = u64(record, 4); // the bytes after the first 12
      if (recordSize < ZIP64_EOCD_MIN - 12 || recordAt + 12 + recordSize !== locatorAt) throw fail('damaged', 'the zip64 end record is the wrong size');
      if (diskNumber === MAX16) diskNumber = record.getUint32(16, true);
      if (directoryDisk === MAX16) directoryDisk = record.getUint32(20, true);
      if (entriesOnDisk === MAX16) entriesOnDisk = u64(record, 24);
      if (entryCount === MAX16) entryCount = u64(record, 32);
      if (directorySize === MAX32) directorySize = u64(record, 40);
      if (directoryStart === MAX32) directoryStart = u64(record, 48);
      endStart = recordAt;
    }
    if (diskNumber !== 0 || directoryDisk !== 0 || entriesOnDisk !== entryCount) throw fail('unsupported', 'the .zip is split over several files');

    // 3. Bound the directory.
    if (entryCount > MAX_ENTRIES || directorySize > MAX_DIRECTORY_BYTES) throw fail('unsupported', 'the .zip holds too many files');
    if (directoryStart + directorySize !== endStart) throw fail('damaged', 'the directory is not where the end record says, or something is in front of the first file');

    // 4. Read it and parse it entry by entry.
    const bytes = new Uint8Array(await readBytes(blob, directoryStart, directoryStart + directorySize));
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const names = new root.TextDecoder('utf-8', { fatal: false });
    const entries = [];
    let pos = 0;
    let lowest = Infinity;
    for (let index = 0; index < entryCount; index += 1) {
      if (pos + CENTRAL_SIZE > directorySize || view.getUint32(pos, true) !== SIG_CENTRAL) throw fail('damaged', 'the directory is cut short or has a broken entry');
      const flags = view.getUint16(pos + 8, true);
      const method = view.getUint16(pos + 10, true);
      const crc32 = view.getUint32(pos + 16, true);
      let compressedSize = view.getUint32(pos + 20, true);
      let entrySize = view.getUint32(pos + 24, true);
      const nameLength = view.getUint16(pos + 28, true);
      const extraLength = view.getUint16(pos + 30, true);
      const commentLength = view.getUint16(pos + 32, true);
      let disk = view.getUint16(pos + 34, true);
      let offset = view.getUint32(pos + 42, true);
      const nameAt = pos + CENTRAL_SIZE;
      const extraAt = nameAt + nameLength;
      const next = extraAt + extraLength + commentLength;
      if (next > directorySize) throw fail('damaged', 'an entry runs past the end of the directory');
      if (entrySize === MAX32 || compressedSize === MAX32 || offset === MAX32 || disk === MAX16) {
        const extra = zip64Extra(view, extraAt, extraAt + extraLength);
        if (!extra) throw fail('damaged', 'a zip64 extra field is missing');
        let p = extra.from;
        const take = (width) => {
          if (p + width > extra.to) throw fail('damaged', 'a zip64 extra field is too short');
          const at64 = p;
          p += width;
          return at64;
        };
        if (entrySize === MAX32) entrySize = u64(view, take(8));
        if (compressedSize === MAX32) compressedSize = u64(view, take(8));
        if (offset === MAX32) offset = u64(view, take(8));
        if (disk === MAX16) disk = view.getUint32(take(4), true);
      }
      if (offset + LOCAL_SIZE > directoryStart || compressedSize > directoryStart) throw fail('damaged', 'an entry points outside the file');
      if (method === METHOD_STORED && compressedSize !== entrySize) throw fail('damaged', 'a stored entry has two different sizes');
      if (offset < lowest) lowest = offset;
      entries.push({
        index, name: names.decode(bytes.subarray(nameAt, extraAt)), size: entrySize, compressedSize, method, crc32, dataStart: null,
        flags, offset, disk, encrypted: (flags & FLAG_ENCRYPTED) !== 0, nameAt, nameLength,
      });
      pos = next;
    }
    if (pos !== directorySize) throw fail('damaged', 'the directory holds more than the end record counts');
    if (entries.length && lowest !== 0) throw fail('damaged', 'something is in front of the first file');

    // 5. Nothing more is read until an entry is streamed.
    return { blob, size, entries, directoryStart, directory: bytes };
  }

  // ---------------------------------------------------------------------------
  // Choosing entries
  // ---------------------------------------------------------------------------
  function matches(entry, rule) {
    const name = entry.name;
    if (name.endsWith('/')) return false; // a folder
    const parts = name.split('/').filter(Boolean);
    if (!parts.length || parts[0] === '__MACOSX') return false;
    const base = parts[parts.length - 1];
    if (base.startsWith('._') || parts.includes('.') || parts.includes('..')) return false;
    const depth = parts.length - 1;
    if (depth > rule.maxDepth) return false;
    if (rule.basename !== undefined && base !== rule.basename) return false;
    if (rule.suffix !== undefined && !(base.length > rule.suffix.length && base.endsWith(rule.suffix))) return false;
    if (rule.under !== undefined && !(depth >= 1 && parts[depth - 1] === rule.under)) return false;
    return true;
  }

  function checkArchive(archive, entry) {
    if (!archive || !Array.isArray(archive.entries) || !archive.blob) throw new TypeError('the first argument must be an archive from open()');
    if (entry !== undefined && !(entry && archive.entries[entry.index] === entry)) throw new TypeError('that entry is not from this archive');
  }
  function checkRule(rule) {
    if (!rule || !Number.isInteger(rule.maxDepth) || rule.maxDepth < 0) throw new TypeError('a rule needs a maxDepth');
  }

  // Why an entry cannot be read, or '' when it can.
  function whyNot(entry) {
    if (entry.encrypted) return 'an entry is encrypted';
    if (entry.method !== METHOD_STORED && entry.method !== METHOD_DEFLATE) return `an entry uses compression method ${entry.method}`;
    if (entry.disk !== 0) return 'an entry is on another disk';
    return '';
  }

  // Every entry the rule matches, in directory order (an odd one is refused when it is read).
  function list(archive, rule) {
    checkArchive(archive);
    checkRule(rule);
    return archive.entries.filter((entry) => matches(entry, rule));
  }

  // The one entry the rule matches.
  function find(archive, rule) {
    const found = list(archive, rule);
    if (!found.length) throw fail('missing', rule.basename || rule.under || 'no match');
    if (found.length > 1) throw fail('ambiguous', `${found.length} matches`);
    const why = whyNot(found[0]);
    if (why) throw fail('unsupported', why);
    return found[0];
  }

  // ---------------------------------------------------------------------------
  // Reading an entry
  // ---------------------------------------------------------------------------
  // Finds where an entry's data starts, after checking its local header against the directory.
  async function locate(archive, entry) {
    const head = await readBytes(archive.blob, entry.offset, entry.offset + LOCAL_SIZE + entry.nameLength);
    const view = new DataView(head);
    if (view.getUint32(0, true) !== SIG_LOCAL) throw fail('damaged', 'a file header is missing');
    if (view.getUint16(8, true) !== entry.method || (view.getUint16(6, true) & FLAG_ENCRYPTED) !== 0) throw fail('damaged', 'a file header does not match the directory');
    const nameLength = view.getUint16(26, true);
    if (nameLength !== entry.nameLength) throw fail('damaged', 'a file header does not match the directory');
    const local = new Uint8Array(head, LOCAL_SIZE, nameLength);
    const listed = archive.directory.subarray(entry.nameAt, entry.nameAt + nameLength);
    for (let i = 0; i < nameLength; i += 1) if (local[i] !== listed[i]) throw fail('damaged', 'a file header does not match the directory');
    const dataStart = entry.offset + LOCAL_SIZE + nameLength + view.getUint16(28, true);
    if (dataStart + entry.compressedSize > archive.directoryStart) throw fail('damaged', 'the data of a file runs into the directory');
    entry.dataStart = dataStart;
    return dataStart;
  }

  // Compressed bytes in pieces of at most `max`.
  function pieces(max) {
    return new root.TransformStream({
      transform(chunk, controller) {
        for (let from = 0; from < chunk.length; from += max) controller.enqueue(chunk.subarray(from, Math.min(from + max, chunk.length)));
      },
    });
  }

  // Passes the bytes on while counting them and keeping their CRC-32; fails the moment they pass the declared size, and at the end if the
  // count or the CRC is not the directory's.
  function checking(entry) {
    let count = 0;
    let crc = 0xFFFFFFFF;
    return new root.TransformStream({
      transform(chunk, controller) {
        count += chunk.length;
        if (count > entry.size) throw fail('damaged', 'a file is bigger than the directory says');
        crc = crcUpdate(crc, chunk);
        controller.enqueue(chunk);
      },
      flush() {
        if (count !== entry.size) throw fail('damaged', 'a file is smaller than the directory says');
        if (((crc ^ 0xFFFFFFFF) >>> 0) !== entry.crc32) throw fail('damaged', 'a file does not match its checksum');
      },
    });
  }

  /* The compressed bytes of the file as a stream, and a way to cancel the file's own stream by hand. A cancel at the end of a chain of pipes
     reaches the file only if every engine in between passes it on, and not every one does (Node's DecompressionStream does not). */
  function fileStream(blob) {
    const reader = blob.stream().getReader();
    const readable = new root.ReadableStream({
      async pull(controller) {
        const { done, value } = await reader.read();
        if (done) controller.close(); else controller.enqueue(value);
      },
      cancel(reason) { return reader.cancel(reason); },
    }, { highWaterMark: 0 });
    return { readable, cancel: (reason) => reader.cancel(reason).catch(() => {}) };
  }

  // The checked, inflated stream of an entry, and how to let go of the file it reads.
  async function pipeline(archive, entry) {
    const dataStart = await locate(archive, entry);
    const file = fileStream(archive.blob.slice(dataStart, dataStart + entry.compressedSize));
    let source = file.readable;
    if (entry.method === METHOD_DEFLATE) source = source.pipeThrough(pieces(INFLATE_PIECE)).pipeThrough(new root.DecompressionStream('deflate-raw'));
    return { readable: source.pipeThrough(checking(entry)), cancelFile: file.cancel };
  }

  // What a reader of the stream sees: ours stay as they are, an I/O error (a DOMException) too; the rest is the inflater's.
  function readError(e) {
    if (e instanceof ZipError || (e && e.name === 'AbortError')) return e;
    if (typeof root.DOMException === 'function' && e instanceof root.DOMException) return e;
    return fail('damaged', 'the data is not valid');
  }

  /* stream(archive, entry, {maxBytes, signal}) -> ReadableStream of Uint8Array: the inflated bytes. Read it with getReader(). The checks that
     need no reading are thrown at once; the rest fails the stream while it is read. Nothing is read until the first read. */
  function stream(archive, entry, opts) {
    opts = opts || {};
    checkArchive(archive, entry);
    const why = whyNot(entry);
    if (why) throw fail('unsupported', why);
    if (opts.maxBytes !== undefined && !(opts.maxBytes >= 0)) throw new TypeError('maxBytes must be a number of bytes');
    if (opts.maxBytes !== undefined && entry.size > opts.maxBytes) throw fail('too_big', `${entry.size} bytes, the most is ${opts.maxBytes}`);
    if (entry.method === METHOD_DEFLATE && !supported()) throw fail('browser');
    const signal = opts.signal;
    if (signal && signal.aborted) throw abortError();

    let made = null; // the checked pipeline: {reader, cancelFile}, made at the first read
    let ended = false; // finished, cancelled, aborted or failed: nothing more is read
    let onAbort = null;
    const release = () => {
      ended = true;
      if (signal && onAbort) signal.removeEventListener('abort', onAbort);
      onAbort = null;
    };
    const stop = (reason) => {
      if (!made) return undefined;
      made.cancelFile(reason);
      return made.reader.cancel(reason).catch(() => {});
    };
    return new root.ReadableStream({
      start(controller) {
        if (!signal) return;
        onAbort = () => {
          const error = abortError();
          release();
          controller.error(error);
          stop(error);
        };
        signal.addEventListener('abort', onAbort, { once: true });
      },
      async pull(controller) {
        try {
          if (!made) {
            const built = await pipeline(archive, entry);
            made = { reader: built.readable.getReader(), cancelFile: built.cancelFile };
            if (ended) { stop(); return; } // aborted while the header was being read
          }
          const { done, value } = await made.reader.read();
          if (ended) return;
          if (done) { release(); controller.close(); } else controller.enqueue(value);
        } catch (e) {
          if (ended) return; // aborted: the stream already failed with the AbortError
          release();
          stop(e);
          throw readError(e);
        }
      },
      cancel(reason) {
        release();
        return stop(reason);
      },
    }, { highWaterMark: 0 });
  }

  /* text(archive, entry, {maxBytes, signal}) -> Promise of the entry as a string (UTF-8, byte order mark dropped). For small entries:
     maxBytes defaults to 16 MiB, and a bigger entry is 'too_big' before anything is read. */
  async function text(archive, entry, opts) {
    opts = opts || {};
    const readable = stream(archive, entry, { ...opts, maxBytes: opts.maxBytes === undefined ? DEFAULT_TEXT_BYTES : opts.maxBytes });
    const bytes = new Uint8Array(entry.size); // the checking stream lets through no more than this
    let filled = 0;
    const reader = readable.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        bytes.set(value, filled);
        filled += value.length;
      }
    } catch (e) {
      try { await reader.cancel(e); } catch (ignored) { /* the stream is already broken */ }
      throw e;
    } finally {
      reader.releaseLock();
    }
    try {
      return new root.TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (e) {
      throw fail('damaged', 'the text is not UTF-8');
    }
  }

  KH.zip = { MAX_DIRECTORY_BYTES, MAX_ENTRIES, DEFAULT_TEXT_BYTES, RULES, supported, open, find, list, stream, text, ZipError };
})(typeof window !== 'undefined' ? window : globalThis);
