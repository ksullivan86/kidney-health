#!/usr/bin/env node
// The zip reader (app/static/js/engine/zip.js, KH.zip) on archives that tests/test_zip_reader.py builds in a temporary folder.
//
//   node tests/js/zip_reader.mjs <folder>                 every case of docs/dev/research/11-reading-a-zip-in-the-browser.md section 5 except 8
//   node --expose-gc tests/js/zip_reader.mjs <folder> --large   case 8 (an export.xml of about 64 MB) and the abort-while-reading checks
//
// This script only OBSERVES: it opens, finds and reads what is in the folder and prints what happened as one JSON object on stdout.
// The expected values are in the pytest file (hand-written there, or taken from Python's own zipfile), so the module under test never
// grades itself. Where a read goes wrong the observation says at which step (open, find, read), the code and the message.
//
// To see how far a hostile entry gets, the script wraps three things the reader uses and the page has too: Blob.slice (a duck-typed
// blob that logs every range asked for and every stream it cancels), the global DecompressionStream (a stand-in that counts the bytes the
// real one inflates) and, for the large file, a file-backed Blob (fs.openAsBlob), so the 64 MB is never in memory.
import { openAsBlob, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
for (const rel of ['app/static/js/engine/rules.js', 'app/static/js/engine/apple_health.js', 'app/static/js/engine/zip.js']) {
  vm.runInThisContext(readFileSync(join(ROOT, rel), 'utf8'), { filename: rel });
}
const Z = globalThis.KH.zip;
const AH = globalThis.KH.appleHealth;

const dir = process.argv[2];
if (!dir) { console.error('usage: zip_reader.mjs <folder> [--large]'); process.exit(2); }
const MiB = 1024 * 1024;
const TODAY = '2026-10-22';
const blobOf = (name) => new Blob([readFileSync(join(dir, name))]);

// ---- helpers ------------------------------------------------------------------------------------------------------------------------------
const describe = (e) => ({
  ok: false, name: e && e.name, code: e && e.code !== undefined ? e.code : null, zip: e instanceof Z.ZipError,
  domException: typeof DOMException === 'function' && e instanceof DOMException, message: String(e && e.message),
});
async function attempt(fn) {
  try { return { ok: true, value: await fn() }; } catch (e) { return describe(e); }
}
// Reads a stream to its end with getReader(), as the page does (Safari cannot "for await" a ReadableStream).
async function drain(readable) {
  const hash = createHash('sha256');
  let bytes = 0; let chunks = 0; let biggest = 0;
  const reader = readable.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    hash.update(value); bytes += value.length; chunks += 1; biggest = Math.max(biggest, value.length);
  }
  return { bytes, sha256: hash.digest('hex'), chunks, biggest };
}
// open, find, text: the step that failed, or the text.
async function walk(name, rule = Z.RULES.exportJson, maxBytes = 16 * MiB, blob = blobOf(name)) {
  let archive;
  try { archive = await Z.open(blob); } catch (e) { return { stage: 'open', ...describe(e) }; }
  let entry;
  try { entry = Z.find(archive, rule); } catch (e) { return { stage: 'find', ...describe(e) }; }
  try { return { stage: null, ok: true, text: await Z.text(archive, entry, { maxBytes }) }; } catch (e) { return { stage: 'read', ...describe(e) }; }
}
// Every entry of an archive (that `keep` accepts), read through stream(): its name, sizes and the SHA-256 of what came out.
async function readEntries(archive, keep = () => true) {
  const out = [];
  for (const entry of archive.entries.filter(keep)) {
    const row = { name: entry.name, size: entry.size, compressedSize: entry.compressedSize, method: entry.method, encrypted: entry.encrypted };
    try { Object.assign(row, await drain(Z.stream(archive, entry))); } catch (e) { row.error = describe(e); }
    out.push(row);
  }
  return out;
}

// A blob that logs what is asked of it: every range sliced, every stream made, every stream cancelled. Its streams hand out pieces of
// 4 KiB, as a big file's would, so that the stream is still open when a reader gives up.
function spy(blob, log, piece = 4096) {
  return {
    size: blob.size,
    slice(from, to) {
      log.slices.push([from, to]);
      const part = blob.slice(from, to);
      return {
        arrayBuffer: () => part.arrayBuffer(),
        stream() {
          log.streams += 1;
          const reader = part.stream().getReader();
          let held = new Uint8Array(0);
          let over = false; // this stream was cancelled or read to its end: the first of the two counts
          const end = (what) => { log[what] += 1; if (!over) { over = true; log.over += 1; } };
          return new ReadableStream({
            async pull(controller) {
              if (held.length === 0) {
                const r = await reader.read();
                if (r.done) { end('finished'); controller.close(); return; }
                held = r.value;
              }
              controller.enqueue(held.subarray(0, piece));
              held = held.subarray(piece);
            },
            cancel(why) { end('cancelled'); return reader.cancel(why); },
          }, { highWaterMark: 0 });
        },
      };
    },
  };
}
const newLog = () => ({ slices: [], streams: 0, cancelled: 0, finished: 0, over: 0 });
// What was done with the file's streams: how many were made, cancelled, read to the end, and so how many are left open half-read.
const files = (log) => ({ streams: log.streams, cancelled: log.cancelled, finished: log.finished, left: log.streams - log.over });

// A DecompressionStream that counts what the real one inflates.
const RealDS = globalThis.DecompressionStream;
const meter = { inflated: 0 };
class CountingDS {
  constructor(format) {
    const inner = new RealDS(format);
    this.writable = inner.writable;
    this.readable = inner.readable.pipeThrough(new TransformStream({ transform(chunk, controller) { meter.inflated += chunk.length; controller.enqueue(chunk); } }));
  }
}
function counting(on) { meter.inflated = 0; globalThis.DecompressionStream = on ? CountingDS : RealDS; }

const out = {};

if (!process.argv.includes('--large')) {
  // ---- 1. the app's own export ---------------------------------------------------------------------------------------------------------------
  {
    const archive = await Z.open(blobOf('app_export.zip'));
    const entry = Z.find(archive, Z.RULES.exportJson);
    out.case1 = { names: archive.entries.map((e) => e.name), found: entry.name, size: entry.size, text: await Z.text(archive, entry, { maxBytes: 16 * MiB }) };
  }

  // ---- 2. stored and deflated, empty, UTF-8 and code page 437 names -------------------------------------------------------------------------
  out.case2 = { mixed: await readEntries(await Z.open(blobOf('mixed.zip'))), cp437: await readEntries(await Z.open(blobOf('cp437.zip'))) };

  // ---- 3. a data descriptor ----------------------------------------------------------------------------------------------------------------
  out.case3 = { entries: await readEntries(await Z.open(blobOf('descriptor.zip'))) };

  // ---- 4. zip64 -----------------------------------------------------------------------------------------------------------------------------
  for (const name of ['zip64', 'zip64_count_only']) {
    const archive = await Z.open(blobOf(`${name}.zip`));
    out[`case4_${name}`] = { entries: await readEntries(archive), directoryStart: archive.directoryStart };
  }

  // ---- 5. a comment that holds an end record -----------------------------------------------------------------------------------------------
  out.case5 = { entries: await readEntries(await Z.open(blobOf('comment.zip'))), max: await readEntries(await Z.open(blobOf('comment_max.zip'))) };

  // ---- 6. a re-zipped folder with the macOS extras -----------------------------------------------------------------------------------------
  {
    const archive = await Z.open(blobOf('rezipped.zip'));
    const entry = Z.find(archive, Z.RULES.exportJson);
    out.case6 = { names: archive.entries.map((e) => e.name), found: entry.name, text: await Z.text(archive, entry, { maxBytes: 16 * MiB }), matches: Z.list(archive, Z.RULES.exportJson).map((e) => e.name) };
  }

  // ---- 7. a Health-shaped archive -----------------------------------------------------------------------------------------------------------
  {
    const archive = await Z.open(blobOf('health.zip'));
    const xmlEntry = Z.find(archive, Z.RULES.healthXml);
    const viaZip = await AH.scan(Z.stream(archive, xmlEntry).pipeThrough(new TextDecoderStream()), { today: TODAY });
    const viaFile = await AH.scan(readFileSync(join(dir, 'health_export.xml'), 'utf8'), { today: TODAY });
    const records = Z.list(archive, Z.RULES.clinicalRecords);
    const texts = {};
    for (const entry of records) texts[entry.name] = await Z.text(archive, entry, { maxBytes: 1 * MiB });
    const refused = {};
    for (const [label, name] of [['encrypted', 'encrypted.gpx'], ['bzip2', 'bzip2.gpx']]) {
      const rule = { basename: name, maxDepth: 2 };
      const [entry] = Z.list(archive, rule);
      refused[label] = { found: await attempt(() => Z.find(archive, rule)), stream: await attempt(() => Z.stream(archive, entry)), text: await attempt(() => Z.text(archive, entry)) };
    }
    out.case7 = {
      names: archive.entries.map((e) => e.name), xml: xmlEntry.name, xmlSize: xmlEntry.size, sameRows: JSON.stringify([viaZip.weights, viaZip.readings, viaZip.summary, viaZip.stats.chars]) === JSON.stringify([viaFile.weights, viaFile.readings, viaFile.summary, viaFile.stats.chars]),
      weights: viaZip.weights.length, readings: viaZip.readings.length, summary: viaZip.summary, chars: viaZip.stats.chars,
      cda: Z.find(archive, Z.RULES.healthCda).name, records: records.map((e) => e.name), texts, refused,
      others: await readEntries(archive, (e) => !e.encrypted && (e.method === 0 || e.method === 8)),
    };
  }

  // ---- 9. not a zip --------------------------------------------------------------------------------------------------------------------------
  out.case9 = {};
  for (const name of ['empty', 'text', 'truncated', 'short', 'comment_too_long', 'trailing_junk']) out.case9[name] = await attempt(() => Z.open(blobOf(`${name}.zip`)));

  // ---- 10. unsupported -----------------------------------------------------------------------------------------------------------------------
  out.case10 = {};
  for (const name of ['disk1', 'directory_disk1', 'entries_split', 'encrypted_selected', 'strong_encryption_selected', 'method12_selected', 'method99_selected', 'other_disk_selected',
    'size_2_60', 'offset_2_60', 'locator_two_disks', 'directory_cap', 'entries_cap', 'many_entries']) {
    out.case10[name] = await walk(`${name}.zip`);
  }
  // 200,000 entries are allowed (many_entries), one more is not (entries_cap)
  out.case10.constants = { MAX_DIRECTORY_BYTES: Z.MAX_DIRECTORY_BYTES, MAX_ENTRIES: Z.MAX_ENTRIES, DEFAULT_TEXT_BYTES: Z.DEFAULT_TEXT_BYTES };

  // ---- 11. too big: an honest 17 MiB export.json, and nothing is read ---------------------------------------------------------------------------
  {
    const log = newLog();
    const archive = await Z.open(spy(blobOf('big_json.zip'), log));
    const entry = Z.find(archive, Z.RULES.exportJson);
    const slicesByOpen = log.slices.slice();
    const refused = await attempt(() => Z.text(archive, entry, { maxBytes: 16 * MiB }));
    const refusedStream = await attempt(() => Z.stream(archive, entry, { maxBytes: 16 * MiB }));
    const refusedDefault = await attempt(() => Z.text(archive, entry)); // the default cap is 16 MiB
    const slicesByRefusals = log.slices.slice(slicesByOpen.length);
    const allowed = await attempt(async () => (await Z.text(archive, entry, { maxBytes: 32 * MiB })).length);
    out.case11 = {
      size: entry.size, directoryStart: archive.directoryStart, blobSize: archive.size, slicesByOpen, slicesByRefusals, refused, refusedStream, refusedDefault, allowed,
    };
  }

  // ---- 12. damaged -----------------------------------------------------------------------------------------------------------------------------
  out.case12 = {};
  for (const name of ['short_entry', 'bad_crc_deflated', 'bad_crc_stored', 'bad_data_stored', 'local_name', 'local_method', 'local_signature', 'offset_past', 'prefix', 'prefix_adjusted',
    'directory_overrun', 'directory_shifted', 'entries_fewer', 'entries_more', 'deflate_cut', 'deflate_garbage', 'into_directory', 'zip64_no_locator', 'zip64_no_extra',
    'zip64_extra_short', 'zip64_record_misplaced', 'empty_deflate_data']) {
    out.case12[name] = await walk(`${name}.zip`);
  }
  {
    const archive = await Z.open(blobOf('bad_utf8.zip'));
    const entry = Z.find(archive, Z.RULES.exportJson);
    out.case12.bad_utf8 = { text: await attempt(() => Z.text(archive, entry, { maxBytes: 1024 })), stream: await attempt(() => drain(Z.stream(archive, entry))) };
  }
  // an entry that inflates past its declared size: how far does it get?
  {
    counting(true);
    const log = newLog();
    const archive = await Z.open(spy(blobOf('bomb.zip'), log));
    const entry = Z.find(archive, Z.RULES.exportJson);
    let received = 0; let failure = null;
    try {
      const reader = Z.stream(archive, entry, { maxBytes: 16 * MiB }).getReader();
      for (;;) { const { done, value } = await reader.read(); if (done) break; received += value.length; }
    } catch (e) { failure = describe(e); }
    await sleep(50);
    out.case12.bomb = { failure, declared: entry.size, compressed: entry.compressedSize, received, inflated: meter.inflated, files: files(log) };
    counting(false);
  }
  // a bomb read with text(): the same
  {
    counting(true);
    const archive = await Z.open(blobOf('bomb.zip'));
    const result = await attempt(() => Z.text(archive, Z.find(archive, Z.RULES.exportJson), { maxBytes: 16 * MiB }));
    out.case12.bomb_text = { result, inflated: meter.inflated };
    counting(false);
  }

  // ---- 13. missing and ambiguous ---------------------------------------------------------------------------------------------------------------
  out.case13 = {};
  for (const name of ['no_export', 'two_exports', 'depth_zero_and_one', 'too_deep', 'only_macosx', 'empty_archive']) out.case13[name] = await walk(`${name}.zip`);

  // ---- 15. a browser without DecompressionStream ----------------------------------------------------------------------------------------------
  {
    const here = Z.supported();
    delete globalThis.DecompressionStream;
    const gone = { supported: Z.supported(), deflated: await walk('deflated_export.zip'), stored: await walk('stored_export.zip') };
    globalThis.DecompressionStream = class { constructor(format) { if (format === 'deflate-raw') throw new TypeError('unsupported format'); } }; // an older Safari
    gone.oldSafari = { supported: Z.supported(), deflated: await walk('deflated_export.zip') };
    globalThis.DecompressionStream = RealDS;
    out.case15 = { here, ...gone, restored: Z.supported() };
  }

  // ---- rules ---------------------------------------------------------------------------------------------------------------------------------
  {
    const archive = await Z.open(blobOf('rules.zip'));
    out.rules = { names: archive.entries.map((e) => e.name) };
    for (const [key, rule] of Object.entries(Z.RULES)) out.rules[key] = Z.list(archive, rule).map((e) => e.name);
    out.rules.frozen = Object.isFrozen(Z.RULES) && Object.values(Z.RULES).every(Object.isFrozen);
    out.rules.badRule = (await attempt(() => Z.list(archive, { basename: 'x' }))).name;
    out.rules.foreignEntry = (await attempt(() => Z.stream(archive, { ...archive.entries[0] }))).name;
  }
}

if (process.argv.includes('--large')) {
  const mb = (bytes) => bytes / MiB;
  const gc = () => { if (typeof globalThis.gc === 'function') { globalThis.gc(); globalThis.gc(); } };
  const path = join(dir, 'large.zip');

  // ---- 8. a large entry: the stream is read in pieces and memory stays bounded ---------------------------------------------------------------
  {
    const blob = await openAsBlob(path);
    const archive = await Z.open(blob);
    const entry = Z.find(archive, Z.RULES.healthXml);
    gc();
    const start = process.memoryUsage();
    let peakHeap = start.heapUsed; let peakOther = start.external + start.arrayBuffers; let pulled = 0;
    const sample = () => {
      const u = process.memoryUsage();
      if (u.heapUsed > peakHeap) peakHeap = u.heapUsed;
      if (u.external + u.arrayBuffers > peakOther) peakOther = u.external + u.arrayBuffers;
    };
    const watched = Z.stream(archive, entry).pipeThrough(new TransformStream({
      transform(chunk, controller) { pulled += 1; if (pulled % 16 === 0) sample(); controller.enqueue(chunk); },
    }));
    const t0 = performance.now();
    const result = await AH.scan(watched.pipeThrough(new TextDecoderStream()), { today: TODAY, progressEvery: 2 * MiB, onProgress: sample });
    const seconds = (performance.now() - t0) / 1000;
    sample();
    gc();
    const after = process.memoryUsage();
    out.case8 = {
      size: entry.size, compressedSize: entry.compressedSize, chunks: pulled, seconds: Number(seconds.toFixed(1)),
      weights: result.weights.length, readings: result.readings.length, kgHundredths: result.weights.reduce((sum, r) => sum + Math.round(r.kg * 100), 0),
      systolicSum: result.readings.reduce((sum, r) => sum + r.systolic, 0), chars: result.stats.chars, skipped: result.summary.skipped,
      firstDate: result.summary.firstDate, lastDate: result.summary.lastDate,
      peakHeapGrowthMb: Number(mb(peakHeap - start.heapUsed).toFixed(1)), peakBuffersGrowthMb: Number(mb(peakOther - start.external - start.arrayBuffers).toFixed(1)),
      retainedHeapMb: Number(mb(after.heapUsed - start.heapUsed).toFixed(1)), gc: typeof globalThis.gc === 'function',
    };
  }

  // ---- 8b. backpressure: with nobody reading, the inflater does not run ahead ------------------------------------------------------------------
  {
    counting(true);
    const log = newLog();
    const archive = await Z.open(spy(await openAsBlob(path), log));
    const entry = Z.find(archive, Z.RULES.healthXml);
    const reader = Z.stream(archive, entry).getReader();
    let consumed = 0;
    for (let i = 0; i < 3; i += 1) consumed += (await reader.read()).value.length;
    await sleep(500);
    const inflatedWhileIdle = meter.inflated;
    await reader.cancel('enough');
    await sleep(100);
    out.case8b = { size: entry.size, consumed, inflatedWhileIdle, files: files(log) };
    counting(false);
  }

  // ---- 14. abort -------------------------------------------------------------------------------------------------------------------------------
  {
    out.case14 = {};
    const make = async () => {
      const log = newLog();
      const archive = await Z.open(spy(await openAsBlob(path), log));
      return { log, archive, entry: Z.find(archive, Z.RULES.healthXml) };
    };
    { // between two reads
      const { log, archive, entry } = await make();
      const ctrl = new AbortController();
      const reader = Z.stream(archive, entry, { signal: ctrl.signal }).getReader();
      const first = await reader.read();
      ctrl.abort();
      const next = await attempt(() => reader.read());
      await sleep(100);
      out.case14.between = { firstBytes: first.value.length, next, files: files(log) };
    }
    { // while a read is waiting
      const { log, archive, entry } = await make();
      const ctrl = new AbortController();
      const reader = Z.stream(archive, entry, { signal: ctrl.signal }).getReader();
      const waiting = reader.read();
      ctrl.abort();
      const next = await attempt(() => waiting);
      await sleep(100);
      out.case14.waiting = { next, files: files(log) };
    }
    { // through the Health scan, as the import sheet does it
      const { log, archive, entry } = await make();
      const ctrl = new AbortController();
      let calls = 0;
      const run = attempt(() => AH.scan(Z.stream(archive, entry, { signal: ctrl.signal }).pipeThrough(new TextDecoderStream()), {
        today: TODAY, signal: ctrl.signal, progressEvery: 1 * MiB, onProgress: () => { calls += 1; if (calls === 2) ctrl.abort(); },
      }));
      const result = await run;
      await sleep(100);
      out.case14.scan = { result, progressCalls: calls, files: files(log) };
    }
    { // already aborted: nothing is read
      const { log, archive, entry } = await make();
      const ctrl = new AbortController();
      ctrl.abort();
      const before = log.slices.length;
      out.case14.before = { result: await attempt(() => Z.stream(archive, entry, { signal: ctrl.signal })), slices: log.slices.length - before };
    }
    { // text()
      const log = newLog();
      const archive = await Z.open(spy(blobOf('big_json.zip'), log));
      const entry = Z.find(archive, Z.RULES.exportJson);
      const ctrl = new AbortController();
      const reading = Z.text(archive, entry, { maxBytes: 64 * MiB, signal: ctrl.signal });
      ctrl.abort();
      out.case14.text = await attempt(() => reading);
    }
    { // cancelling the reader (no signal) lets go of the source
      const { log, archive, entry } = await make();
      const reader = Z.stream(archive, entry).getReader();
      await reader.read();
      await reader.cancel('done');
      await sleep(100);
      out.case14.cancel = { files: files(log) };
    }
  }
}

process.stdout.write(`${JSON.stringify(out)}\n`);
