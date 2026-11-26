#!/usr/bin/env node
// Parity of the export archive built in the page (app/static/js/mock/export.js, M.exportZip) with the server's
// (app/account.py build_export), against tests/data/export_vectors.json (tests/data/gen_export_vectors.py).
//
//   node tests/js/export_vectors.mjs      # exit 0 when every file matches, 1 otherwise
//
// 1. Every CSV file and README.txt rebuilt from the server's export.json document is the server's text, byte for byte.
// 2. The archive's file name (account.export_filename).
// 3. The zip the page writes opens with the app's own reader (js/engine/zip.js) and with the checks of a strict reader here:
//    the order of the files, STORE, every CRC-32, and the text of every file.
// 4. A fresh demo account (the iPhone app's engine) builds its archive end to end: the audit row, the name, export.json first.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inflateRawSync } from 'node:zlib';
import { loadDemo, newDemo } from './demo_loader.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const V = JSON.parse(readFileSync(join(ROOT, 'tests', 'data', 'export_vectors.json'), 'utf8'));
const failures = [];
let checks = 0;
const expect = (label, got, want) => {
  checks += 1;
  if (JSON.stringify(got) !== JSON.stringify(want)) failures.push({ label, got, want });
};

// A strict reader of what zip() writes: local headers in order, then the directory and the end record.
function readZip(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const dec = new TextDecoder();
  const out = [];
  let at = 0;
  while (view.getUint32(at, true) === 0x04034b50) {
    const method = view.getUint16(at + 8, true);
    const crc = view.getUint32(at + 14, true);
    const size = view.getUint32(at + 18, true);
    const nameLen = view.getUint16(at + 26, true);
    const extraLen = view.getUint16(at + 28, true);
    const name = dec.decode(bytes.subarray(at + 30, at + 30 + nameLen));
    const start = at + 30 + nameLen + extraLen;
    const data = bytes.subarray(start, start + view.getUint32(at + 22, true));
    out.push({ name, method, crc, size, text: dec.decode(method === 8 ? inflateRawSync(data) : data) });
    at = start + data.length;
  }
  const endAt = bytes.length - 22;
  if (view.getUint32(endAt, true) !== 0x06054b50) throw new Error('no end record at the end');
  if (view.getUint16(endAt + 10, true) !== out.length) throw new Error('the end record counts other files');
  if (view.getUint32(endAt + 16, true) !== at) throw new Error('the directory does not start after the files');
  if (view.getUint32(endAt + 12, true) !== endAt - at) throw new Error('the directory size is wrong');
  return out;
}

const KH = loadDemo({ globals: { Blob, ReadableStream, TransformStream, DecompressionStream, TextDecoder } });
const Z = KH.mock.exportZip;
const sources = (id) => V.food_sources[String(id)] || null;
const built = Z.csvFiles(V.doc, sources);
expect('the files, in order', ['export.json', ...built.map(([n]) => n), 'README.txt'], V.names);
for (const [name, text] of built) expect(name, text, V.files[name]);
expect('README.txt', Z.readme(V.readme_brand.name, V.readme_brand.export_format), V.files['README.txt']);
expect('README.txt with the page\'s brand', Z.readme(), V.files['README.txt']);
expect('the file name', Z.filename(V.filename.username, new Date(`${V.filename.day}T12:00:00Z`)), V.filename.name);
for (const c of V.filename_cases) expect(`the file name for ${JSON.stringify(c.username)}`, Z.filename(c.username, new Date('2026-11-26T00:00:00Z')),
  `${KH.brand.slug}-${c.safe}-2026-11-26.zip`);
expect('CRC-32 of "123456789"', Z.crc32(new TextEncoder().encode('123456789')), 0xCBF43926);
expect('CRC-32 of nothing', Z.crc32(new Uint8Array(0)), 0);

// The archive of the server's data, read back two ways.
const files = [['export.json', JSON.stringify(V.doc, null, 2)], ...built, ['README.txt', Z.readme()]];
const bytes = Z.zip(files, new Date('2026-11-26T10:20:31Z'));
const read = readZip(bytes);
expect('read back: names', read.map((f) => f.name), V.names);
expect('read back: every file is stored', read.every((f) => f.method === 0), true);
expect('read back: texts', read.map((f) => f.text), files.map(([, t]) => t));
expect('read back: CRC-32', read.map((f) => f.crc), files.map(([, t]) => Z.crc32(new TextEncoder().encode(t))));

async function viaAppReader() {
  const zip = KH.zip;
  const archive = await zip.open(new Blob([bytes]));
  const entry = zip.find(archive, zip.RULES.exportJson);
  const text = await zip.text(archive, entry);
  expect('the app\'s own reader finds export.json and reads it whole', JSON.parse(text), V.doc);
}

// A fresh account of the iPhone app's engine, end to end.
async function demoArchive() {
  const api = newDemo(KH);
  const before = api._authState().events.length;
  const res = api._exportArchive(new Date('2026-11-26T08:00:00Z'));
  const back = readZip(res.bytes);
  expect('demo: the name', /^kidney-health-[^/]+-2026-11-26\.zip$/.test(res.name), true);
  expect('demo: the names', back.map((f) => f.name), V.names);
  expect('demo: export.json is the document', Object.keys(JSON.parse(back[0].text)).slice(0, 3), ['format', 'version', 'exported_at']);
  expect('demo: log.csv has a line per entry', back[1].text.split('\r\n').length - 2, JSON.parse(back[0].text).log_entries.length);
  const ev = api._authState().events;
  expect('demo: the export is in Activity', ev.length === before + 1 && ev[ev.length - 1].action === 'export.created', true);
}

async function main() {
  try { await viaAppReader(); } catch (e) { failures.push({ label: 'the app\'s own reader', got: String(e && e.stack), want: 'no error' }); checks += 1; }
  await demoArchive();
  if (failures.length) {
    for (const f of failures.slice(0, 20)) console.error(`MISMATCH ${f.label}\n   js:     ${JSON.stringify(f.got)}\n   python: ${JSON.stringify(f.want)}`);
    console.error(`\n${failures.length} of ${checks} checks failed (tests/data/export_vectors.json vs app/static/js/mock/export.js)`);
    process.exitCode = 1;
    return;
  }
  console.log(`export vectors: ${checks} checks passed (${built.length + 1} files)`);
}
await main();
