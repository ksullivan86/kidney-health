# 11 · Reading a .zip in the browser (the app's own export, the Health app's export.zip)

| | |
|---|---|
| Status | Decided 2026-10-22 (§7), to be built in one part. |
| Date researched | 2026-10-22, against `main` at `1e1ca32` plus the import sheet of note 10 Part C |
| Scope | One small zip reader that runs in the page (`js/engine/zip.js`, `KH.zip`). It lets three imports take the archive itself, so nobody has to unzip it first: **Import from a file** (`export.json` from this app's own export), **Weights and blood pressure from the Health app** (`export.xml`, note 10 §4.8), and **Lab results from Apple Health clinical records** (`clinical-records/*.json`, `js/views/lab_fhir.js`). |
| Out of scope | Writing zips in the browser (the demo's export stays `export.json`); reading zips on the server (the server never takes an archive; least trust); any other archive format (`.tar`, `.gz`, `.7z`, `.rar`); encrypted zips; archives split over several files; the Health app's other files (workout routes, ECGs, `export_cda.xml`). |
| Builds on | `app/account.py` `build_export` (Python `zipfile`, deflate, no comment), `js/views/settings.js` `importBlock`, `js/views/body_import.js`, `js/engine/apple_health.js` (`scan` takes a stream of text), `js/views/lab_fhir.js`, the ROADMAP item "Let Import from a file take the export .zip itself". |
| Re-verify | Pick a real iPhone `export.zip` in Safari on an iPhone and in a desktop browser (the owner; the tests build their archives with Python's `zipfile` and by hand, with no real Health export). |

---

## 1. Context

Today all three imports refuse a `.zip` and say how to open it first:

* Settings → Import from a file: "That is the whole export. Open the .zip on your device and choose the export.json inside it."
* The Health app import sheet: "That is the whole export. In Files, tap export.zip to unzip it, then choose apple_health_export/export.xml."
* Labs → Import from Apple Health (clinical records): the handbook tells the person to unzip, open `apple_health_export/clinical-records/` and choose the files.

Unzipping on a phone works, but it is a step people get stuck on. On an iPhone the unzipped Health export is a second copy of a file that can be gigabytes. The page can read the archive itself with what browsers already have (`Blob.slice`, `Blob.stream`, `DecompressionStream('deflate-raw')`), with no library and no network.

## 2. Facts used

| # | Fact | Source |
|---|---|---|
| Z1 | A zip ends with an "end of central directory" record (signature `PK\x05\x06`, 22 bytes plus a comment of up to 65,535 bytes). It gives the number of entries and where the central directory starts and how long it is. Each central-directory entry gives the name, the method, the flags, the CRC-32, the compressed and uncompressed sizes and where the entry's local header is. The local header (`PK\x03\x04`, 30 bytes plus name and extra field) comes right before the entry's data. If flag bit 3 is set, the sizes in the local header are zero and a data descriptor follows the data. The central directory always holds the real sizes. | PKWARE APPNOTE.TXT 6.3.10, §4.3.6, 4.3.7, 4.3.9, 4.3.12, 4.3.16, 4.4.4 |
| Z2 | Zip64: when a count, size or offset does not fit (`0xFFFF` / `0xFFFFFFFF`), a zip64 end-of-central-directory record and its locator (`PK\x06\x06`, `PK\x06\x07`, 20 bytes, right before the end record) hold the 64-bit values. Each such entry has an extra field with header id `0x0001` that holds, in this order, only the values that overflowed: uncompressed size, compressed size, local header offset, disk number. | APPNOTE §4.3.14, 4.3.15, 4.5.3 |
| Z3 | Methods: 0 is stored, 8 is deflate. Flag bit 0 means encrypted. Bit 11 means the name is UTF-8; otherwise it is IBM code page 437. | APPNOTE §4.4.4, 4.4.5, Appendix D |
| Z4 | `DecompressionStream('deflate-raw')` inflates raw deflate (no zlib header), which is what method 8 holds. It is in Chrome 103, Safari 16.4 and Firefox 113, and in Node 21.2 or later. A stream that is cut short or damaged makes the readable side error. | WHATWG Compression Standard §5; MDN "DecompressionStream" browser compatibility |
| Z5 | Python's `zipfile` (this app's export) writes deflate, a data descriptor only when the output cannot seek, and zip64 only when a value overflows (or with `force_zip64`). macOS "Compress" adds `__MACOSX/` entries holding `._name` AppleDouble files. | CPython `Lib/zipfile/__init__.py`; Apple's Archive Utility behaviour (re-verify with a real archive) |
| Z6 | The Health app's "Export All Health Data" gives `export.zip`. Inside is a folder `apple_health_export/` with `export.xml`, `export_cda.xml` and, when the person linked a health system, `clinical-records/*.json`. Some exports also have `workout-routes/` and `electrocardiograms/`. | Note 10 §4.8 and F-series; `js/views/lab_fhir.js` header (re-verify with a real export) |

## 3. Goals

1. Each of the three imports accepts the archive as well as the file it holds. Whatever comes out of the archive goes through the same code as a file picked by itself.
2. Nothing leaves the device that did not already leave it: the archive is read here, and only what each import already sends is sent (the parsed `export.json`, the rows the person keeps).
3. The archive is not trusted:
   * memory stays bounded whatever the archive claims;
   * no size, offset or name is believed until it has been checked;
   * a file that inflates past its declared size (a "zip bomb"), or whose CRC-32 does not match, is refused while it is being read, not afterwards;
   * an archive the reader does not fully understand is refused with a plain reason, never half-read.
4. A browser without `DecompressionStream('deflate-raw')` gets the old "open the .zip first" advice instead of an error.

## 4. Design

### 4.1 `js/engine/zip.js` (`KH.zip`; a plain script, no DOM; runs in the page and under Node 22 for the tests)

```
KH.zip.supported()                       -> true when DecompressionStream('deflate-raw') can be made (try/catch)
KH.zip.open(blob)                        -> Promise<Archive>   reads only the tail and the central directory
KH.zip.find(archive, rule)               -> Entry               exactly one match, or ZipError 'missing' / 'ambiguous'
KH.zip.list(archive, rule)               -> Entry[]             every match (clinical records), in central-directory order
KH.zip.stream(archive, entry, opts)      -> ReadableStream<Uint8Array>   the inflated bytes, checked as they come out
KH.zip.text(archive, entry, opts)        -> Promise<string>     stream + TextDecoder('utf-8', {fatal: true}); for small entries
class KH.zip.ZipError extends Error { code }   codes below
Archive = { blob, entries: Entry[] }     Entry = { name, size, compressedSize, method, crc32, dataStart }  (dataStart filled lazily)
rule    = { basename, maxDepth, under?, suffix? }  (§4.3)
opts    = { maxBytes, signal }
```

`ZipError.code` is one of:

| Code | Meaning |
|---|---|
| `not_zip` | No valid end record. |
| `unsupported` | Spans several disks, an entry is encrypted, a method other than 0 or 8, or a 64-bit value above `Number.MAX_SAFE_INTEGER`. |
| `missing` | No entry matches the rule. |
| `ambiguous` | More than one entry matches the rule. |
| `too_big` | The declared size is above `maxBytes`. |
| `damaged` | Any inconsistency: offsets outside the file, a local header that does not match its central-directory entry, inflated bytes above or below the declared size, a CRC-32 mismatch, a deflate error. |
| `browser` | `DecompressionStream('deflate-raw')` is missing. |

### 4.2 Reading the directory (`open`)

1. **Find the end record.**
   * If `blob.size < 22`, the error is `not_zip`.
   * Read the last `min(size, 22 + 65,535 + 20)` bytes with one `blob.slice().arrayBuffer()`.
   * Search backwards for `PK\x05\x06`. Take the first match, nearest the end, whose comment length reaches exactly the end of the file. No match is `not_zip`. This also skips a fake end record hidden in a comment.
2. **Read the end record.**
   * Disk number and central-directory disk must both be 0, and "entries on this disk" must equal "total entries". Otherwise the error is `unsupported`.
   * If any field is at its maximum (`0xFFFF` or `0xFFFFFFFF`), read the zip64 locator 20 bytes before the end record, then the zip64 end record it points to (signature `PK\x06\x06`). If the locator is missing, the error is `damaged`.
   * Read 64-bit values with `getBigUint64`. A value above `Number.MAX_SAFE_INTEGER` is `unsupported`.
3. **Bound the central directory.**
   * The directory must end exactly where the end record (or the zip64 end record) starts: `cdOffset + cdSize`. Data before the first entry, as in a self-extracting archive, is `damaged`.
   * `cdSize` may be at most 32 MiB (`MAX_DIRECTORY_BYTES`). The entry count may be at most 200,000 (`MAX_ENTRIES`). Over either limit is `unsupported`.
   * Both caps bound memory. A Health export with many years of workout routes has a few thousand entries of about 100 bytes each.
4. **Read the directory** in one slice and parse it entry by entry.
   * Each entry: signature `PK\x01\x02`, fixed 46 bytes, then name, extra field and comment, all inside `cdSize`. Anything that runs past `cdSize` is `damaged`. The count parsed must equal the declared count.
   * Read the zip64 extra field (id `0x0001`) for the values that overflowed, in APPNOTE order (Z2).
   * Decode the name as UTF-8 (`fatal: false`). Flag 11 does not matter here: every name the rules look for is ASCII, and a CP437 byte above `0x7F` cannot make an ASCII match.
   * Encrypted entries, unknown methods and disk numbers other than 0 are not refused here. They are recorded, and they are refused only if a rule selects them. A Health export with one odd file in `workout-routes/` still imports its weights.
   * Bound checks, with `size` the archive's byte length:
     * `localHeaderOffset + 30 <= cdOffset`
     * `compressedSize <= cdOffset`
     * method 0 means `compressedSize === size` (the entry's uncompressed size).
5. **Nothing more is read** until an entry is streamed. Opening a 2 GB archive reads tens of kilobytes.

### 4.3 Choosing entries (rules)

A rule matches on the name split at `/`. Empty segments are dropped, so a leading `/` or `//` counts for nothing. The name is never used as a path: nothing is written anywhere, and `..` is just text that never matches.

Each rule allows a **depth**: the number of folders above the file, with 0 meaning the file sits at the top of the archive.

Every rule also ignores:
* any entry whose first segment is `__MACOSX` (Z5);
* any name whose last segment starts with `._`;
* directory entries (a name ending in `/`).

| Import | Rule | More than one match |
|---|---|---|
| Import from a file | basename exactly `export.json`, depth at most 1 (the app's archive has it at the top; a re-zipped folder has it one level down) | `ambiguous`: "This .zip holds more than one export.json. Open it and choose the one you want." |
| Weights and blood pressure | basename exactly `export.xml`, depth at most 1 (`apple_health_export/export.xml`); `export_cda.xml` does not match | `ambiguous`, same kind of message |
| Clinical records | parent folder exactly `clinical-records`, basename ending `.json` (case-sensitive, as the folder the person picks today), depth at most 2 | Every match is a file, as with today's multi-file pick (up to 2,000, 1 MB each, the same caps as `lab_fhir.js`; above 2,000 is today's refusal) |

### 4.4 Streaming an entry (`stream`)

1. **Check the declared size.** If `entry.size > opts.maxBytes`, the error is `too_big`, and nothing is read.
2. **Find the data.**
   * Read the local header: 30 bytes at `localHeaderOffset`, signature `PK\x03\x04`.
   * Its name bytes must equal the central-directory name bytes. Its method must equal the directory's method. Anything else is `damaged`.
   * `dataStart` is `localHeaderOffset + 30 + nameLength + extraLength`, and `dataStart + compressedSize <= cdOffset` must hold, or the error is `damaged`.
   * The local header's sizes and CRC are not used, because they are zero when bit 3 is set (Z1). Use the directory's.
3. **Read the bytes.**
   * Start from `blob.slice(dataStart, dataStart + compressedSize).stream()`.
   * Method 8 pipes it through `DecompressionStream('deflate-raw')`. Method 0 does not.
   * Then pipe it through a checking `TransformStream`. It counts the bytes and keeps a running CRC-32 (table-based, about 1 KB of table). It errors with `damaged` the moment the count passes `entry.size`, without forwarding that chunk. At the end, a count other than `entry.size` or a CRC that does not match `entry.crc32` is also `damaged`.
   * This last check is what stops a zip bomb. An archive that claims 1 KB and inflates to 10 GB is stopped after the first chunk above 1 KB. The inflater's output is read chunk by chunk and never held whole.
4. **Cancellation.**
   * `opts.signal` aborting cancels the source stream. The reader rejects with an `AbortError`, the same as the Health import's Cancel today.
   * A deflate error from `DecompressionStream` (a `TypeError`) is turned into `damaged`.
5. **Text.** `text()` collects the stream for small entries (`export.json` at most 16 MiB, clinical records 1 MB each) and decodes it with `fatal: true`. Bytes that are not valid UTF-8 are `damaged`. `export.xml` is not read with `text()`: the sheet pipes `stream()` through `TextDecoderStream` into `KH.appleHealth.scan`, which already reads text as a stream.

### 4.5 The three screens (wording follows the app's plain style; every message is set with `textContent`)

**Settings → Import from a file** (`importBlock`)
* The file box takes `.zip,.json,application/zip,application/json`. Its label becomes "Your export (.zip or export.json)".
* The paragraph above it becomes: "Moving to another server, or starting again? Choose the .zip from an export of yours, or the export.json inside it. You see what would be added before anything is changed."
* A `.zip` (by name or type, as today's check) goes through `open`, `find` and `text` with `maxBytes: IMPORT_MAX_BYTES`, then into the same `JSON.parse` path as a picked `export.json`.

| Error | Message |
|---|---|
| `missing` | "This .zip has no export.json in it, so it is not an export from this app." |
| `too_big` | the existing size message, for the `export.json` inside |
| `damaged`, `not_zip`, `unsupported` | "This .zip could not be read (it may be damaged or not finished downloading). Download the export again, or open it on your device and choose the export.json inside it." |
| `browser` | the old advice: "This browser cannot open a .zip here. Open the .zip on your device and choose the export.json inside it." |

* The online demo's local import uses the same block, so it takes a `.zip` too. The demo's own export stays `export.json`.

**Weights and blood pressure from the Health app** (`body_import.js`)
* The picker takes `.zip`, `.xml` and their types. The intro says to choose `export.zip`, or `export.xml` if the export was already unzipped.
* For a `.zip`, the sheet runs `open` and `find` (export.xml rule), then `stream(...).pipeThrough(new TextDecoderStream())` into `AH.scan`. The progress line uses `entry.size` (the unzipped size) for "of N MB". Cancel aborts the same `AbortController`.
* A `.zip` with no `export.xml` but with `export_cda.xml` gets the existing CDA message.

| Error | Message |
|---|---|
| `missing` | "This .zip has no export.xml in it. Choose the export.zip from Health → your picture → Export All Health Data." |
| `damaged` and the rest | the same idea as for the export: may be damaged or not finished downloading |
| `browser` | today's unzip advice |

**Labs → Import from Apple Health clinical records** (`lab_fhir.js`)
* The picker also takes one `.zip`. Its entries under `clinical-records/` go through the same loop as picked files: the same 2,000-file and 1 MB caps, each read with `text()` (`maxBytes` 1 MB), handed to `KH.fhirLabs` and let go of.
* A file over 1 MB is skipped and counted, as today. A `damaged` entry is counted as unreadable, and the import goes on.
* If the `.zip` has no `clinical-records/` folder: "This .zip has no clinical-records folder. It is there only if you linked your health system in the Health app."

### 4.6 What does not change

* **No server code**, no route, no migration, no setting, nothing new in the export. The server never sees an archive: the same JSON or rows reach the same routes.
* **No new vendored file.** `DecompressionStream` is the browser's own. CSP is unchanged (no inline script, no `wasm-unsafe-eval`).
* **No twin or parity vectors.** There is no server logic to match. The reader's own tests pin it (§5).
* **The service worker** precaches `js/engine/zip.js` like every engine file (`sw.js` list, `index.html` script tag before the three views).

## 5. Tests (`python -m pytest`, no network; Node 22 under `tests/js/`)

`tests/js/zip_reader.mjs` is run by `tests/test_zip_reader.py`, as the other `.mjs` checks are run. Python builds every archive at test time in `tmp_path`, so no binary is committed. It uses `zipfile` where it can, and a small hand-written builder where `zipfile` cannot produce the shape (a zip64 central directory without 4 GB of data, a fake end record in the comment, a lying size, a flipped CRC). Archives the reader must read:

1. The app's own export (`app/account.py build_export` for a test user): `find` export.json, then `text`, equal to the JSON the server wrote.
2. Stored and deflated entries; an empty entry; a name with UTF-8 (flag 11) and one without.
3. A data descriptor (bit 3): written by `zipfile` to an unseekable stream.
4. A hand-built zip64: a zip64 end record and locator, entries whose sizes and offset are in the `0x0001` extra field.
5. A comment that holds `PK\x05\x06`: the real end record is still found.
6. The re-zipped folder shape: `kidney-health-x/export.json` with `__MACOSX/kidney-health-x/._export.json`. `find` returns the real one.
7. A Health-shaped archive: `apple_health_export/export.xml`, `export_cda.xml`, `clinical-records/Observation-1.json` and so on, plus one encrypted entry in `workout-routes/`. `export.xml` streams, and `scan` gives the same rows as the same text picked by itself. `list` gives the clinical records. The encrypted entry is ignored, because no rule selects it.
8. A large entry (an `export.xml` of about 64 MB of repeated records): the stream never holds more than one chunk past the reader. Memory is checked as in `tests/js/apple_health_large.mjs`.

Archives the reader must refuse, each with its code:
9. `not_zip`: an empty file, a text file, a truncated tail.
10. `unsupported`: a "disk 1 of 2" end record; an encrypted entry that is selected; method 12 (bzip2) that is selected; a 64-bit size above 2^53.
11. `too_big`: an honest `export.json` of 17 MiB. Nothing is read (the test checks that no slice past the directory was made).
12. `damaged`, each one:
    * an entry that inflates past its declared size (a 100 MiB run of zeros declared as 1 KiB): the error arrives after at most one chunk past 1 KiB;
    * an entry shorter than declared;
    * a flipped CRC;
    * a local header whose name differs from the directory's;
    * an offset past the directory;
    * data before the first entry;
    * a central directory that runs past its stated size;
    * a deflate stream cut in half.
13. `missing` and `ambiguous`: no `export.json`; two `export.json` at depth 1.
14. Abort: `signal.abort()` part-way rejects with `AbortError`.
15. `browser`: with `DecompressionStream` removed from the global, `supported()` is false and `stream` of a deflated entry is `browser` (a stored entry still reads).

Screens:
* `tests/js/import_page.mjs` and `tests/test_data_import_ui.py` cover a `.zip` pick reaching the same dry run, each message above, and the accept list.
* `tests/js/body_import_page.mjs` and `tests/test_body_import_ui.py` cover a `.zip` pick reaching the review with the same rows as `export.xml`, and the messages.
* The lab FHIR page test covers a `.zip` pick reaching the same table as picking the files.

Browser walks, in real Chromium:
* `tools/e2e/import_walk.py` chooses the downloaded `.zip` itself.
* `tools/e2e/body_import.py` chooses an `export.zip` built from its sample `export.xml`.

## 6. Risks

| Risk | Answer |
|---|---|
| A crafted archive makes the page use lots of memory or time | The directory is capped (32 MiB, 200,000 entries). Each entry is inflated as a stream, checked against its declared size chunk by chunk, and refused the moment it passes it. A selected entry's declared size is checked against the import's own cap before reading. |
| A file inside the archive is not what its name says | Every one goes through the same parser as a file picked by itself, which already treats it as untrusted (note 10 §4.8, `data_import.py`, `fhir_labs.js`). |
| Real Health exports use something this reader refuses (an odd method, zip64 shapes) | Refusals are plain and give the old unzip advice. The owner checks with a real `export.zip` (Re-verify above). Only the selected entries need to be readable. |
| Safari before 16.4 (iOS 16.3 and older) | `supported()` is false, so the old advice is shown. The `.json` and `.xml` picks still work. |
| CRC-32 over a multi-gigabyte `export.xml` costs time on a phone | A table CRC is a few hundred MB/s, small next to the text scan. Keeping it is what tells a damaged download from a real export. |

## 7. Decisions (2026-10-22, the owner's standing "recommended least-trust choice" for this run)

1. **Read in the browser only.** The server never takes an archive (smaller attack surface, nothing new in the API).
2. **Strict reading.** Data before the first entry, a directory that does not end at the end record, a local header that disagrees with the directory, a size or CRC mismatch: each is a refusal, not a best effort.
3. **Check sizes and CRC while reading**, not afterwards.
4. **Include clinical records.** They are in the same archive, use the same reader, and are a few lines in `lab_fhir.js`, so all three Health app imports lose the unzip step together.
5. **No zip writing.** The demo's export stays `export.json`: nobody asked for it, and it would add code that runs on the person's data.
