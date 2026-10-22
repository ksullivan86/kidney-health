#!/usr/bin/env node
// The Apple Health export.xml reader (app/static/js/engine/apple_health.js) on a file far larger than the memory it may use.
//
//   node --expose-gc tests/js/apple_health_large.mjs [--mb 200]
//
// Part 1: a synthetic export of about 200 MB (--mb), generated and read as a stream, never held in memory: a real export's prolog and
// DTD, then mostly records the reader must not keep (heart rate with metadata children, steps, energy, glucose, insulin, workouts, activity
// summaries) with a few thousand weights and blood pressure readings spread through it, and every kind of record it must skip (lone halves,
// out-of-range values, a unit it does not know, a bad entity, tags over 8 KiB and one of 1 MiB, repeats). The expected counts come from the
// generator's own bookkeeping, not from the reader; the kilograms are summed in integer hundredths with exact integer arithmetic. The bytes
// go through TextDecoderStream, cut where a multi-byte character falls across two chunks, like file.stream() in a browser.
// The heap is sampled while it runs: heapUsed must never be more than 100 MB above where it started, and after the scan (and a garbage
// collection, with --expose-gc) it must be back within 20 MB.
// Part 2: hostile shapes of 16 to 64 MB, each of which would make a careless scanner quadratic or unbounded: start tags made of nothing but
// the filter text, tags full of "&", a million "<Record " with no ">", text with no tag at all, and one tag of 40 MB. Each has an exact
// expected count and a time limit; the carry-over buffer must never pass 8,192 characters.
//
// Prints a summary on stderr and one JSON line on stdout; exits 1 when anything is off. tests/test_apple_health.py runs it.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
for (const rel of ['app/static/js/engine/rules.js', 'app/static/js/engine/apple_health.js']) {
  vm.runInThisContext(readFileSync(join(ROOT, rel), 'utf8'), { filename: rel });
}
const A = globalThis.KH.appleHealth;

const argAt = process.argv.indexOf('--mb');
const MB = argAt >= 0 ? Number(process.argv[argAt + 1]) : 200;
if (!(MB >= 1)) { console.error('--mb needs a number of megabytes'); process.exit(2); }
const TARGET_CHARS = Math.round(MB * 1024 * 1024);
const HEAP_LIMIT_MB = 100; // heapUsed above where it started, while reading
const RETAINED_LIMIT_MB = 20; // and after, once garbage is collected
const SHAPE_SECONDS = 20; // each hostile shape; a linear scanner needs well under one
const mb = (bytes) => bytes / 1048576;
const gc = () => { if (typeof globalThis.gc === 'function') { globalThis.gc(); globalThis.gc(); } };
const problems = [];
const check = (label, got, want) => {
  if (JSON.stringify(got) !== JSON.stringify(want)) problems.push(`${label}: got ${JSON.stringify(got)}, wanted ${JSON.stringify(want)}`);
};
const log = (line) => process.stderr.write(`${line}\n`);

// ---- the synthetic export ---------------------------------------------------------------------------------------------------------------------
function mulberry32(seed) {
  let a = seed;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pad2 = (n) => String(n).padStart(2, '0');
const dayFrom = (y, m, d, plus) => new Date(Date.UTC(y, m - 1, d + plus)).toISOString().slice(0, 10);

const PROLOG = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!-- HealthKit Export Version: 14 -->
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout|ActivitySummary|ClinicalRecord)*)>
<!ATTLIST HealthData locale CDATA #REQUIRED>
<!ELEMENT Record ((MetadataEntry|HeartRateVariabilityMetadataList)*)>
<!ATTLIST Record type CDATA #REQUIRED unit CDATA #IMPLIED value CDATA #IMPLIED sourceName CDATA #REQUIRED sourceVersion CDATA #IMPLIED device CDATA #IMPLIED creationDate CDATA #IMPLIED startDate CDATA #REQUIRED endDate CDATA #REQUIRED>
<!ENTITY lol "lol">
<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<HealthData locale="en_US">
 <ExportDate value="2026-10-20 09:00:00 -0400"/>
 <Me HKCharacteristicTypeIdentifierDateOfBirth="1980-01-01" HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexNotSet"/>
`;
const EPILOG = '</HealthData>\n';
const W = 'HKQuantityTypeIdentifierBodyMass';
const S = 'HKQuantityTypeIdentifierBloodPressureSystolic';
const D = 'HKQuantityTypeIdentifierBloodPressureDiastolic';
const rec = (type, unit, start, value, source, extra = '') =>
  ` <Record type="${type}" sourceName="${source}" sourceVersion="17.5" unit="${unit}" creationDate="${start}" startDate="${start}" endDate="${start}" value="${value}"${extra}/>\n`;
const DEVICE = 'device="&lt;&lt;HKDevice: 0x280b1c000, name:Apple Watch, manufacturer:Apple Inc., model:Watch, hardware:Watch6,2, software:10.1&gt;&gt;"';
const WATCH = 'Zoë’s Apple Watch';
const SCALE = 'Bathroom Scale App';
const CUFF = 'Cuff App';

// What the generator put in the file (its own bookkeeping; the reader is checked against it).
function makeExport(targetChars) {
  const rand = mulberry32(20261022);
  const est = Math.floor(targetChars / 500); // records the file will hold, about (they average 490 characters)
  const every = (n) => Math.max(8, Math.floor(est / n)); // one special record in every this many, for n of them in the file
  const P = { weight: every(3000), reading: every(2000), lone: every(50), lowKg: every(25), lowBp: every(25), gram: every(25), entity: every(25), longTag: every(8), repeat: 100 };
  const sent = {
    chars: 0, records: 0,
    weights: 0, kgHundredths: 0, weightDates: [], lbWeights: 0,
    readings: 0, systolicSum: 0, diastolicSum: 0, watchReadings: 0,
    lowKg: 0, lowBp: 0, gram: 0, entity: 0, longTag: 0, lone: 0, duplicate: 0,
    first: null, last: null, sources: new Set(),
  };
  const touch = (date, source) => { if (sent.first === null || date < sent.first) sent.first = date; if (sent.last === null || date > sent.last) sent.last = date; sent.sources.add(source); };
  let k = { weight: 0, reading: 0, lone: 0, lowKg: 0, lowBp: 0, gram: 0, entity: 0, longTag: 0 };
  let idx = 0;

  function irrelevant() {
    const pick = rand();
    const sec = pad2(idx % 60);
    const start = `2024-03-04 10:${pad2(Math.floor(idx / 60) % 60)}:${sec} -0500`;
    if (pick < 0.62) {
      const children = 1 + (idx % 3);
      let kids = '';
      for (let c = 0; c < children; c += 1) kids += `  <MetadataEntry key="HKMetadataKeyHeartRateMotionContext" value="${c}"/>\n`;
      return ` <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="${WATCH}" sourceVersion="10.1" ${DEVICE} unit="count/min" creationDate="${start}" startDate="${start}" endDate="${start}" value="${50 + Math.floor(rand() * 90)}">\n${kids} </Record>\n`;
    }
    if (pick < 0.78) return rec('HKQuantityTypeIdentifierStepCount', 'count', start, String(Math.floor(rand() * 90)), 'Sam’s iPhone', ` ${DEVICE}`);
    if (pick < 0.88) return rec('HKQuantityTypeIdentifierActiveEnergyBurned', 'kcal', start, (rand() * 12).toFixed(3), WATCH, ` ${DEVICE}`);
    if (pick < 0.92) return rec('HKQuantityTypeIdentifierBloodGlucose', 'mg/dL', start, String(70 + Math.floor(rand() * 120)), 'Glucose App');
    if (pick < 0.94) return rec('HKQuantityTypeIdentifierInsulinDelivery', 'IU', start, (rand() * 6).toFixed(1), 'Pump App');
    if (pick < 0.97) return rec('HKQuantityTypeIdentifierBodyMassIndex', 'count', start, (20 + rand() * 6).toFixed(2), 'Health');
    if (pick < 0.985) return ` <Workout workoutActivityType="HKWorkoutActivityTypeWalking" duration="31.5" durationUnit="min" sourceName="${WATCH}" ${DEVICE} creationDate="${start}" startDate="${start}" endDate="${start}">\n  <WorkoutEvent type="HKWorkoutEventTypePause" date="${start}"/>\n  <WorkoutStatistics type="HKQuantityTypeIdentifierStepCount" sum="3100" unit="count"/>\n </Workout>\n`;
    return ` <ActivitySummary dateComponents="2024-03-04" activeEnergyBurned="${Math.floor(rand() * 600)}" appleExerciseTime="${Math.floor(rand() * 60)}" appleStandHours="${Math.floor(rand() * 14)}"/>\n`;
  }

  // One slot of the file: a special record when the schedule says so, else something to ignore.
  function slot() {
    idx += 1;
    sent.records += 1;
    if (idx % P.weight === 0) {
      const n = k.weight; k.weight += 1;
      const date = dayFrom(2016, 1, 1, n);
      const start = `${date} 07:${pad2(15 + (n % 30))}:00 -0500`;
      const source = n % 7 === 0 ? 'Health' : SCALE;
      let text;
      if (n % 2 === 0) {
        const tenths = 1500 + Math.floor(rand() * 500); // 150.0 to 199.9 lb
        text = rec(W, 'lb', start, (tenths / 10).toFixed(1), source);
        sent.kgHundredths += Math.floor((tenths * 45359237 + 5000000) / 10000000); // exactly: tenths/10 lb x 0.45359237, in hundredths of a kg, half up
        sent.lbWeights += 1;
      } else {
        const tenths = 680 + Math.floor(rand() * 240); // 68.0 to 91.9 kg
        text = rec(W, 'kg', start, (tenths / 10).toFixed(1), source);
        sent.kgHundredths += tenths * 10;
      }
      sent.weights += 1;
      touch(date, source);
      if (n % P.repeat === 5) { sent.duplicate += 1; text += text; } // the same record again
      return text;
    }
    if (idx % P.reading === 1) {
      const n = k.reading; k.reading += 1;
      const date = dayFrom(2018, 1, 1, Math.floor(n / 2));
      const start = `${date} ${n % 2 ? '19' : '07'}:30:00 -0500`;
      const source = n % 5 === 0 ? WATCH : CUFF;
      const sy = 105 + Math.floor(rand() * 60);
      const di = 60 + Math.floor(rand() * 35);
      const s = rec(S, 'mmHg', start, String(sy), source);
      const d = rec(D, 'mmHg', start, String(di), source);
      sent.readings += 1; sent.systolicSum += sy; sent.diastolicSum += di;
      if (source === WATCH) sent.watchReadings += 1;
      touch(date, source);
      const form = n % 3;
      if (form === 0) return `${s}${d}`;
      const corr = ` <Correlation type="HKCorrelationTypeIdentifierBloodPressure" sourceName="${source}" startDate="${start}" endDate="${start}">\n${s}${d} </Correlation>\n`;
      if (form === 1) return corr;
      sent.duplicate += 2; // inside the Correlation and again loose
      return `${corr}${s}${d}`;
    }
    if (idx % P.lone === 2) { const n = k.lone; k.lone += 1; sent.lone += 1; return rec(S, 'mmHg', `${dayFrom(2011, 1, 1, n)} 08:00:00 -0500`, '130', CUFF); }
    if (idx % P.lowKg === 3) { const n = k.lowKg; k.lowKg += 1; sent.lowKg += 1; return rec(W, 'kg', `${dayFrom(2012, 1, 1, n)} 08:00:00 -0500`, '19', SCALE); }
    if (idx % P.lowBp === 4) {
      const n = k.lowBp; k.lowBp += 1; sent.lowBp += 1;
      const start = `${dayFrom(2013, 1, 1, n)} 08:00:00 -0500`;
      return `${rec(S, 'mmHg', start, '80', CUFF)}${rec(D, 'mmHg', start, '90', CUFF)}`; // top number below the bottom one
    }
    if (idx % P.gram === 5) { const n = k.gram; k.gram += 1; sent.gram += 1; return rec(W, 'g', `${dayFrom(2014, 1, 1, n)} 08:00:00 -0500`, '70500', SCALE); }
    if (idx % P.entity === 6) { const n = k.entity; k.entity += 1; sent.entity += 1; return rec(W, 'kg', `${dayFrom(2015, 1, 1, n)} 08:00:00 -0500`, '70', 'A &nbsp; B'); }
    if (idx % P.longTag === 7) {
      const n = k.longTag; k.longTag += 1; sent.longTag += 1;
      const size = n === 2 ? 1024 * 1024 : 20000 + n * 1000; // one tag of 1 MiB, the others about 20 KiB
      return ` <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="${WATCH}" unit="count/min" startDate="2024-03-04 11:00:00 -0500" value="70" device="${'d'.repeat(size)}"/>\n`;
    }
    return irrelevant();
  }

  // The text, a block at a time, and then the end of the file.
  let started = false;
  let finished = false;
  function nextBlock() {
    if (finished) return null;
    let text = '';
    if (!started) { started = true; text = PROLOG; }
    while (text.length < 24000 && sent.chars + text.length < targetChars) text += slot();
    if (sent.chars + text.length >= targetChars) { text += EPILOG; finished = true; }
    sent.chars += text.length;
    return text;
  }
  return { nextBlock, sent };
}

// The text as a stream of bytes: blocks are encoded, cut every 64 KiB plus a few bytes (so a multi-byte character is sometimes split
// across two chunks), and decoded again by TextDecoderStream, like file.stream().pipeThrough(new TextDecoderStream()).
function byteStream(source, onChunk) {
  const encoder = new TextEncoder();
  let pending = new Uint8Array(0);
  let chunks = 0;
  return new ReadableStream({
    pull(controller) {
      while (pending.length < 65600) {
        const block = source.nextBlock();
        if (block === null) break;
        const bytes = encoder.encode(block);
        const joined = new Uint8Array(pending.length + bytes.length);
        joined.set(pending);
        joined.set(bytes, pending.length);
        pending = joined;
      }
      if (pending.length === 0) { controller.close(); return; }
      const size = Math.min(pending.length, 65536 + (chunks % 7) * 3);
      controller.enqueue(pending.slice(0, size));
      pending = pending.slice(size);
      chunks += 1;
      if (onChunk) onChunk(chunks);
    },
  }).pipeThrough(new TextDecoderStream());
}

// ---- part 1: the 200 MB export ------------------------------------------------------------------------------------------------------------------
log(`Part 1: a synthetic export of about ${MB} MB, streamed${typeof globalThis.gc === 'function' ? '' : ' (no --expose-gc: heap figures include garbage)'}`);
gc();
const heapStart = process.memoryUsage().heapUsed;
let heapPeak = heapStart;
let otherPeak = 0; // typed arrays and other memory outside the JavaScript heap
const sample = () => {
  const u = process.memoryUsage();
  if (u.heapUsed > heapPeak) heapPeak = u.heapUsed;
  if (u.external + u.arrayBuffers > otherPeak) otherPeak = u.external + u.arrayBuffers;
};
const gen = makeExport(TARGET_CHARS);
const t0 = performance.now();
let progressCalls = 0;
const result = await A.scan(byteStream(gen, (n) => { if (n % 64 === 0) sample(); }), { progressEvery: 10 * 1024 * 1024, onProgress: () => { progressCalls += 1; sample(); } });
const seconds = (performance.now() - t0) / 1000;
sample();
const heapGrowthMb = mb(heapPeak - heapStart);
const sent = gen.sent;
const rowsKg = result.weights.reduce((sum, r) => sum + Math.round(r.kg * 100), 0);
const sy = result.readings.reduce((sum, r) => sum + r.systolic, 0);
const di = result.readings.reduce((sum, r) => sum + r.diastolic, 0);
const sk = result.summary.skipped;
check('weights kept', result.weights.length, sent.weights);
check('readings kept', result.readings.length, sent.readings);
check('found', result.summary.found, { weights: sent.weights + sent.lowKg, readings: sent.readings + sent.lowBp });
check('kilograms, in hundredths, summed', rowsKg, sent.kgHundredths);
check('systolic summed', sy, sent.systolicSum);
check('diastolic summed', di, sent.diastolicSum);
check('skipped', sk, { unknownUnit: sent.gram, halfPair: sent.lone, outOfRange: sent.lowKg + sent.lowBp, badEntity: sent.entity, tagTooLong: sent.longTag, duplicate: sent.duplicate, unreadable: 0 });
check('first and last date', [result.summary.firstDate, result.summary.lastDate], [sent.first, sent.last]);
check('source names', result.summary.sourceNames, [...sent.sources].sort());
check('watch readings', result.readings.filter((r) => A.isWatchSource(r.sourceName)).length, sent.watchReadings);
check('every source_key is different', new Set([...result.weights, ...result.readings].map((r) => r.source_key)).size, sent.weights + sent.readings);
check('every source_key is 32 hex characters', [...result.weights, ...result.readings].every((r) => /^[0-9a-f]{32}$/.test(r.source_key)), true);
check('characters read', result.stats.chars, sent.chars);
if (result.stats.maxCarry > A.MAX_TAG) problems.push(`the carry-over buffer reached ${result.stats.maxCarry} characters`);
if (sent.chars < TARGET_CHARS) problems.push(`the export is ${sent.chars} characters, wanted ${TARGET_CHARS}`);
if (!(sent.weights >= 1000 && sent.readings >= 1000 && sent.longTag >= 5)) problems.push(`too few special records: ${sent.weights} weights, ${sent.readings} readings, ${sent.longTag} long tags`);
if (progressCalls < Math.floor(sent.chars / (10 * 1024 * 1024)) - 1) problems.push(`onProgress was called ${progressCalls} times`);
if (heapGrowthMb > HEAP_LIMIT_MB) problems.push(`the heap grew by ${heapGrowthMb.toFixed(1)} MB while reading (limit ${HEAP_LIMIT_MB} MB)`);
gc();
const retainedMb = mb(process.memoryUsage().heapUsed - heapStart);
if (typeof globalThis.gc === 'function' && retainedMb > RETAINED_LIMIT_MB) problems.push(`${retainedMb.toFixed(1)} MB of the heap is still in use after the scan (limit ${RETAINED_LIMIT_MB} MB)`);
log(`  ${mb(sent.chars).toFixed(1)} MB (${sent.records.toLocaleString('en-US')} records) in ${seconds.toFixed(1)} s = ${(mb(sent.chars) / seconds).toFixed(0)} MB/s`);
log(`  kept ${result.weights.length} weights and ${result.readings.length} readings; skipped ${JSON.stringify(sk)}`);
log(`  heap: started ${mb(heapStart).toFixed(1)} MB, peak +${heapGrowthMb.toFixed(1)} MB, after the scan +${retainedMb.toFixed(1)} MB; buffers outside the heap peaked at ${mb(otherPeak).toFixed(1)} MB; carry-over at most ${result.stats.maxCarry} characters`);

// ---- part 2: hostile shapes --------------------------------------------------------------------------------------------------------------------
async function* repeated(text, times, per = 4096) {
  let left = times;
  while (left > 0) {
    const n = Math.min(per, left);
    yield text.repeat(n);
    left -= n;
  }
}
async function* concat(...parts) { for (const p of parts) yield* p; }
const shapes = [];
async function shape(name, make, expectOf) {
  const t = performance.now();
  const r = await A.scan(make());
  const secs = (performance.now() - t) / 1000;
  shapes.push({ name, mb: Number(mb(r.stats.chars).toFixed(1)), seconds: Number(secs.toFixed(2)), maxCarry: r.stats.maxCarry });
  if (secs > SHAPE_SECONDS) problems.push(`${name}: took ${secs.toFixed(1)} s (limit ${SHAPE_SECONDS} s)`);
  if (r.stats.maxCarry > A.MAX_TAG) problems.push(`${name}: the carry-over buffer reached ${r.stats.maxCarry} characters`);
  const want = expectOf(r);
  check(name, want.got, want.want);
  log(`  ${name}: ${mb(r.stats.chars).toFixed(0)} MB in ${secs.toFixed(2)} s, carry-over at most ${r.stats.maxCarry}`);
}
log('Part 2: hostile shapes');
const KEEP = `<Record type="${W}" sourceName="Health" unit="kg" startDate="2026-01-01 08:00:00 +0000" value="70"/>`;
{
  const tag = `<Record HKQuantityTypeIdentifierB${'a'.repeat(8000)}>\n`;
  const n = Math.floor((24 * 1024 * 1024) / tag.length);
  await shape('start tags that hold the filter text and no attribute', () => concat(repeated(tag, n, 64), [KEEP]), (r) => ({ got: [r.summary.kept.weights, r.summary.skipped], want: [1, { unknownUnit: 0, halfPair: 0, outOfRange: 0, badEntity: 0, tagTooLong: 0, duplicate: 0, unreadable: 0 }] }));
}
{
  const tag = `<Record type="${W}" sourceName="${'&a'.repeat(3500)}" unit="kg" startDate="2026-01-01 08:00:00 +0000" value="70"/>\n`;
  const n = Math.floor((24 * 1024 * 1024) / tag.length);
  await shape('start tags whose source name is all "&"', () => repeated(tag, n, 64), (r) => ({ got: [r.summary.kept.weights, r.summary.skipped.badEntity], want: [0, n] }));
}
{
  const n = 3 * 1024 * 1024;
  await shape('three million "<Record " that never end', () => repeated('<Record ', n), (r) => ({ got: r.summary.skipped.unreadable, want: n }));
}
{
  const chunk = `${'x'.repeat(65530)}<Reco`;
  const times = Math.floor((64 * 1024 * 1024) / chunk.length);
  await shape('64 MB with no tag in it, only the start of one at every chunk end', () => repeated(chunk, times, 1), (r) => ({ got: [r.summary.kept, r.summary.skipped], want: [{ weights: 0, readings: 0 }, { unknownUnit: 0, halfPair: 0, outOfRange: 0, badEntity: 0, tagTooLong: 0, duplicate: 0, unreadable: 0 }] }));
}
{
  const head = `<Record type="${W}" sourceName="Health" unit="kg" startDate="2026-01-01 08:00:00 +0000" value="70" device="`;
  await shape('one start tag of 40 MB', () => concat([head], repeated('x'.repeat(65536), 640, 1), ['"/>\n', `${KEEP.replace('08:00:00', '09:00:00')}\n`]), (r) => ({ got: [r.summary.skipped.tagTooLong, r.summary.kept.weights], want: [1, 1] }));
}

if (problems.length) {
  process.stderr.write(`\nFAILED:\n${problems.join('\n')}\n`);
  process.exit(1);
}
log('ok');
process.stdout.write(`${JSON.stringify({
  ok: true, mb: Number(mb(sent.chars).toFixed(1)), seconds: Number(seconds.toFixed(1)), records: sent.records,
  weights: result.weights.length, readings: result.readings.length, skipped: sk,
  heap: { start_mb: Number(mb(heapStart).toFixed(1)), peak_growth_mb: Number(heapGrowthMb.toFixed(1)), retained_mb: Number(retainedMb.toFixed(1)), buffers_peak_mb: Number(mb(otherPeak).toFixed(1)) },
  max_carry: result.stats.maxCarry, shapes,
})}\n`);
