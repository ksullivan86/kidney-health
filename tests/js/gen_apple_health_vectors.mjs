#!/usr/bin/env node
// Writes tests/data/apple_health_vectors.json: what js/engine/apple_health.js (weights and blood pressure readings from the iPhone Health
// app's export.xml, read on the device as a stream of text; docs/dev/research/10-weight-and-blood-pressure.md section 4.8) answers for each
// case below. The reader has no Python twin (the file is read in the browser; the server only sees the rows the person keeps), so the file
// pins its behaviour. Every case carries the rows and counts that are written BY HAND here (dates, times, kilograms, contexts, the exact text
// each source_key is made of, and the skip counts that are not zero); only the source_key itself is computed, once, by node:crypto from that
// hand-written text, and the first and last date and the source names are derived unless a case writes them out. The script stops when the
// module disagrees, and runs every case at chunk sizes 1, 7, 64 and whole (plus the explicit chunk lists a case gives), so the pinned answers
// are not just a copy of what the module said. All records are invented (made-up sources and values; no real person's data).
// tests/test_apple_health.py recomputes every source_key with hashlib; node tests/js/run_vectors.mjs replays the cases.
//
//   node tests/js/gen_apple_health_vectors.mjs
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const ENGINE = ['rules', 'apple_health'].map((p) => `app/static/js/engine/${p}.js`);
const OUT = join(ROOT, 'tests', 'data', 'apple_health_vectors.json');

const context = vm.createContext({ console, crypto: globalThis.crypto, TextEncoder });
for (const rel of ENGINE) vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
const A = vm.runInContext('globalThis.KH.appleHealth', context);
const plain = (v) => JSON.parse(JSON.stringify(v));
const sha32 = (text) => createHash('sha256').update(text, 'utf8').digest('hex').slice(0, 32);

const W = 'HKQuantityTypeIdentifierBodyMass';
const S = 'HKQuantityTypeIdentifierBloodPressureSystolic';
const D = 'HKQuantityTypeIdentifierBloodPressureDiastolic';
const SIZES = [1, 7, 64, 'whole'];

// ---- xml pieces ------------------------------------------------------------------------------------------------------------------------
// A long text is stored as a recipe {repeat: {text, count}} so the file stays small; expand() makes the text.
const rep = (text, count) => ({ repeat: { text, count } });
const expand = (xml) => (typeof xml === 'string' ? xml : xml.map((p) => (typeof p === 'string' ? p : p.repeat.text.repeat(p.repeat.count))).join(''));
const join_ = (items) => {
  const parts = [];
  for (const item of items) {
    if (typeof item === 'string' && typeof parts[parts.length - 1] === 'string') parts[parts.length - 1] += item;
    else parts.push(item);
  }
  return parts.length === 1 && typeof parts[0] === 'string' ? parts[0] : parts;
};

const PROLOG = '<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="en_US">\n <ExportDate value="2026-10-20 09:00:00 -0400"/>\n';
const EPILOG = '</HealthData>\n';
// An item is a string (one line) or an array of strings and recipes (one line made of several parts, for the long tags).
const lines = (items) => items.flatMap((i) => [...(Array.isArray(i) ? i : [i]), '\n']);
const doc = (...items) => join_([PROLOG, ...lines(items), EPILOG]);

// What an iPhone writes at the top: the XML line and the internal DTD (the element list as Health's own export has it), then the root.
const DTD = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE HealthData [
<!-- HealthKit Export Version: 14 -->
<!ELEMENT HealthData (ExportDate,Me,(Record|Correlation|Workout|ActivitySummary|ClinicalRecord)*)>
<!ATTLIST HealthData
  locale CDATA #REQUIRED
>
<!ELEMENT ExportDate EMPTY>
<!ATTLIST ExportDate
  value CDATA #REQUIRED
>
<!ELEMENT Me EMPTY>
<!ATTLIST Me
  HKCharacteristicTypeIdentifierDateOfBirth CDATA #REQUIRED
  HKCharacteristicTypeIdentifierBiologicalSex CDATA #REQUIRED
>
<!ELEMENT Record ((MetadataEntry|HeartRateVariabilityMetadataList)*)>
<!ATTLIST Record
  type          CDATA #REQUIRED
  unit          CDATA #IMPLIED
  value         CDATA #IMPLIED
  sourceName    CDATA #REQUIRED
  sourceVersion CDATA #IMPLIED
  device        CDATA #IMPLIED
  creationDate  CDATA #IMPLIED
  startDate     CDATA #REQUIRED
  endDate       CDATA #REQUIRED
>
<!ELEMENT Correlation ((MetadataEntry|Record)*)>
<!ATTLIST Correlation
  type          CDATA #REQUIRED
  sourceName    CDATA #REQUIRED
  startDate     CDATA #REQUIRED
  endDate       CDATA #REQUIRED
>
<!ELEMENT MetadataEntry EMPTY>
<!ATTLIST MetadataEntry
  key   CDATA #REQUIRED
  value CDATA #REQUIRED
>
`;
const ROOT_TAG = ']>\n<HealthData locale="en_US">\n <ExportDate value="2026-10-20 09:00:00 -0400"/>\n <Me HKCharacteristicTypeIdentifierDateOfBirth="1980-01-01" HKCharacteristicTypeIdentifierBiologicalSex="HKBiologicalSexNotSet"/>\n';
const docDtd = (extraDecls, ...items) => join_([DTD, extraDecls, ROOT_TAG, ...lines(items), EPILOG]);

// A <Record> start tag as Health writes it. `source` goes in as written (an entity stays an entity).
const rec = (type, unit, start, value, source = 'Health') =>
  `<Record type="${type}" sourceName="${source}" sourceVersion="17.5" unit="${unit}" creationDate="${start}" startDate="${start}" endDate="${start}" value="${value}"/>`;
const wt = (start, value, unit = 'kg', source = 'Health') => rec(W, unit, start, value, source);
const sys = (start, value, source = 'Cuff App') => rec(S, 'mmHg', start, value, source);
const dia = (start, value, source = 'Cuff App') => rec(D, 'mmHg', start, value, source);
const pair = (start, s, d, source = 'Cuff App') => `${sys(start, s, source)}\n${dia(start, d, source)}`;

// ---- hand-written expectations -----------------------------------------------------------------------------------------------------------
// A weight: when `start` is the startDate as written; date and time are what a person reads on the clock when they stepped on the scale.
const w = (date, time, kg, context, start, value, source = 'Health') => ({ date, time, kg, context, key_input: `${W}|${start}|${value}|${source}`, sourceName: source });
const r = (date, time, systolic, diastolic, context, start, sValue, dValue, source = 'Cuff App') =>
  ({ date, time, systolic, diastolic, context, key_input: `BloodPressure|${start}|${sValue}/${dValue}|${source}`, sourceName: source });

// ---- the cases -----------------------------------------------------------------------------------------------------------------------------
const cases = [];
const add = (name, xml, want, options = {}) => cases.push({ name, xml, want, options });
const addChunks = (name, marked, want, options = {}) => cases.push({ name, chunks: marked.split('¦'), want, options });

add('a weight in kilograms', doc(wt('2026-10-19 07:15:00 -0400', '70.5')), {
  weights: [w('2026-10-19', '07:15', 70.5, 'morning', '2026-10-19 07:15:00 -0400', '70.5')],
});

add('weights in pounds: x 0.45359237, rounded half up to 0.01 kg', doc(
  wt('2026-10-01 07:00:00 -0400', '154.3', 'lb'), wt('2026-10-02 07:00:00 -0400', '100', 'lb'), wt('2026-10-03 07:00:00 -0400', '176.4', 'lb'),
  wt('2026-10-04 07:00:00 -0400', '220.46', 'lb'), wt('2026-10-05 07:00:00 -0400', '45.3', 'lb'), wt('2026-10-06 07:00:00 -0400', '200', 'lb'),
  wt('2026-10-07 07:00:00 -0400', '88.2', 'lb'), wt('2026-10-08 07:00:00 -0400', '154.25', 'lb'),
), {
  weights: [
    w('2026-10-01', '07:00', 69.99, 'morning', '2026-10-01 07:00:00 -0400', '154.3'), // 69.989302691
    w('2026-10-02', '07:00', 45.36, 'morning', '2026-10-02 07:00:00 -0400', '100'), // 45.359237
    w('2026-10-03', '07:00', 80.01, 'morning', '2026-10-03 07:00:00 -0400', '176.4'), // 80.013694068
    w('2026-10-04', '07:00', 100, 'morning', '2026-10-04 07:00:00 -0400', '220.46'), // 99.9989738902
    w('2026-10-05', '07:00', 20.55, 'morning', '2026-10-05 07:00:00 -0400', '45.3'), // 20.547734361
    w('2026-10-06', '07:00', 90.72, 'morning', '2026-10-06 07:00:00 -0400', '200'), // 90.718474
    w('2026-10-07', '07:00', 40.01, 'morning', '2026-10-07 07:00:00 -0400', '88.2'), // 40.006847034
    w('2026-10-08', '07:00', 69.97, 'morning', '2026-10-08 07:00:00 -0400', '154.25'), // 69.9666230725
  ],
});

add('kilograms are rounded half up on their decimal digits', doc(
  wt('2026-11-01 07:00:00 -0500', '70.005'), wt('2026-11-02 07:00:00 -0500', '70.015'), wt('2026-11-03 07:00:00 -0500', '70.004'),
  wt('2026-11-04 07:00:00 -0500', '70.995'), wt('2026-11-05 07:00:00 -0500', '80.125'), wt('2026-11-06 07:00:00 -0500', '99.994'),
  wt('2026-11-07 07:00:00 -0500', '99.995'), wt('2026-11-08 07:00:00 -0500', '70.5000'),
), {
  weights: [
    w('2026-11-01', '07:00', 70.01, 'morning', '2026-11-01 07:00:00 -0500', '70.005'), // Math.round(70.005 * 100) / 100 would give 70
    w('2026-11-02', '07:00', 70.02, 'morning', '2026-11-02 07:00:00 -0500', '70.015'),
    w('2026-11-03', '07:00', 70, 'morning', '2026-11-03 07:00:00 -0500', '70.004'),
    w('2026-11-04', '07:00', 71, 'morning', '2026-11-04 07:00:00 -0500', '70.995'),
    w('2026-11-05', '07:00', 80.13, 'morning', '2026-11-05 07:00:00 -0500', '80.125'),
    w('2026-11-06', '07:00', 99.99, 'morning', '2026-11-06 07:00:00 -0500', '99.994'),
    w('2026-11-07', '07:00', 100, 'morning', '2026-11-07 07:00:00 -0500', '99.995'),
    w('2026-11-08', '07:00', 70.5, 'morning', '2026-11-08 07:00:00 -0500', '70.5000'), // the key keeps the text as written
  ],
});

add('a weight is "morning" from 04:00 to 10:59 and "other" at every other hour', doc(
  wt('2026-09-01 03:59:00 -0400', '70.1'), wt('2026-09-02 04:00:00 -0400', '70.2'), wt('2026-09-03 10:59:00 -0400', '70.3'),
  wt('2026-09-04 11:00:00 -0400', '70.4'), wt('2026-09-05 23:59:00 -0400', '70.5'), wt('2026-09-06 00:00:00 -0400', '70.6'),
  wt('2026-09-07 17:00:00 -0400', '70.7'),
), {
  weights: [
    w('2026-09-01', '03:59', 70.1, 'other', '2026-09-01 03:59:00 -0400', '70.1'),
    w('2026-09-02', '04:00', 70.2, 'morning', '2026-09-02 04:00:00 -0400', '70.2'),
    w('2026-09-03', '10:59', 70.3, 'morning', '2026-09-03 10:59:00 -0400', '70.3'),
    w('2026-09-04', '11:00', 70.4, 'other', '2026-09-04 11:00:00 -0400', '70.4'),
    w('2026-09-05', '23:59', 70.5, 'other', '2026-09-05 23:59:00 -0400', '70.5'),
    w('2026-09-06', '00:00', 70.6, 'other', '2026-09-06 00:00:00 -0400', '70.6'),
    w('2026-09-07', '17:00', 70.7, 'other', '2026-09-07 17:00:00 -0400', '70.7'), // a weight has no "evening"
  ],
});

add('a blood pressure reading is "morning" 04:00-10:59, "evening" 17:00-23:59 and "other" between', doc(
  pair('2026-09-01 00:00:00 -0400', '118', '76'), pair('2026-09-02 03:59:00 -0400', '119', '77'), pair('2026-09-03 04:00:00 -0400', '120', '78'),
  pair('2026-09-04 10:59:00 -0400', '121', '79'), pair('2026-09-05 11:00:00 -0400', '122', '80'), pair('2026-09-06 16:59:00 -0400', '123', '81'),
  pair('2026-09-07 17:00:00 -0400', '124', '82'), pair('2026-09-08 23:59:00 -0400', '125', '83'),
), {
  readings: [
    r('2026-09-01', '00:00', 118, 76, 'other', '2026-09-01 00:00:00 -0400', '118', '76'),
    r('2026-09-02', '03:59', 119, 77, 'other', '2026-09-02 03:59:00 -0400', '119', '77'),
    r('2026-09-03', '04:00', 120, 78, 'morning', '2026-09-03 04:00:00 -0400', '120', '78'),
    r('2026-09-04', '10:59', 121, 79, 'morning', '2026-09-04 10:59:00 -0400', '121', '79'),
    r('2026-09-05', '11:00', 122, 80, 'other', '2026-09-05 11:00:00 -0400', '122', '80'),
    r('2026-09-06', '16:59', 123, 81, 'other', '2026-09-06 16:59:00 -0400', '123', '81'),
    r('2026-09-07', '17:00', 124, 82, 'evening', '2026-09-07 17:00:00 -0400', '124', '82'),
    r('2026-09-08', '23:59', 125, 83, 'evening', '2026-09-08 23:59:00 -0400', '125', '83'),
  ],
});

add('a reading inside a Correlation and again loose is counted once', doc(
  `<Correlation type="HKCorrelationTypeIdentifierBloodPressure" sourceName="Cuff App" sourceVersion="3.1" startDate="2026-10-18 08:05:00 -0400" endDate="2026-10-18 08:05:00 -0400">
  <MetadataEntry key="HKWasUserEntered" value="0"/>
  ${sys('2026-10-18 08:05:00 -0400', '122')}
  ${dia('2026-10-18 08:05:00 -0400', '78')}
 </Correlation>`,
  `<Record type="${S}" sourceName="Cuff App" sourceVersion="3.1" unit="mmHg" creationDate="2026-10-18 08:05:09 -0400" startDate="2026-10-18 08:05:00 -0400" endDate="2026-10-18 08:05:00 -0400" value="122"/>`,
  `<Record type="${D}" sourceName="Cuff App" sourceVersion="3.1" unit="mmHg" creationDate="2026-10-18 08:05:09 -0400" startDate="2026-10-18 08:05:00 -0400" endDate="2026-10-18 08:05:00 -0400" value="78"/>`,
), {
  readings: [r('2026-10-18', '08:05', 122, 78, 'morning', '2026-10-18 08:05:00 -0400', '122', '78')],
  skipped: { duplicate: 2 },
});

add('a pair outside a Correlation, diastolic first, is a reading', doc(dia('2026-10-17 19:30:00 -0400', '85'), sys('2026-10-17 19:30:00 -0400', '135')), {
  readings: [r('2026-10-17', '19:30', 135, 85, 'evening', '2026-10-17 19:30:00 -0400', '135', '85')],
});

add('half a pair is skipped and counted: alone, from another source, a second apart, or in another time zone', doc(
  sys('2026-10-01 08:00:00 -0400', '130'),
  dia('2026-10-02 09:00:00 -0400', '85'),
  sys('2026-10-03 10:00:00 -0400', '128', 'Cuff App'), dia('2026-10-03 10:00:00 -0400', '82', 'Other Cuff'),
  sys('2026-10-04 11:00:00 -0400', '126'), dia('2026-10-04 11:00:01 -0400', '80'),
  sys('2026-10-05 12:00:00 -0400', '124'), dia('2026-10-05 12:00:00 -0500', '79'),
  pair('2026-10-06 18:00:00 -0400', '118', '76'),
), {
  readings: [r('2026-10-06', '18:00', 118, 76, 'evening', '2026-10-06 18:00:00 -0400', '118', '76')],
  skipped: { halfPair: 8 },
});

add('two different systolic values at one instant cannot be paired: every half of the group is skipped', doc(
  sys('2026-10-10 08:00:00 -0400', '120'), sys('2026-10-10 08:00:00 -0400', '125'), dia('2026-10-10 08:00:00 -0400', '80'),
  sys('2026-10-10 08:00:00 -0400', '120'), // the same record again
  pair('2026-10-11 08:00:00 -0400', '121', '79'),
), {
  readings: [r('2026-10-11', '08:00', 121, 79, 'morning', '2026-10-11 08:00:00 -0400', '121', '79')],
  skipped: { halfPair: 3, duplicate: 1 },
});

add('two sources reading at the same instant are two readings', doc(
  pair('2026-10-12 07:00:00 -0400', '130', '84', 'Cuff B'), pair('2026-10-12 07:00:00 -0400', '128', '82', 'Cuff A'),
), {
  readings: [
    r('2026-10-12', '07:00', 128, 82, 'morning', '2026-10-12 07:00:00 -0400', '128', '82', 'Cuff A'),
    r('2026-10-12', '07:00', 130, 84, 'morning', '2026-10-12 07:00:00 -0400', '130', '84', 'Cuff B'),
  ],
});

add('a weight outside 20-400 kg is skipped and counted (pounds are checked after conversion)', doc(
  wt('2026-08-01 07:00:00 -0400', '19.99'), wt('2026-08-02 07:00:00 -0400', '20'), wt('2026-08-03 07:00:00 -0400', '400'),
  wt('2026-08-04 07:00:00 -0400', '400.01'), wt('2026-08-05 07:00:00 -0400', '44.0', 'lb'), wt('2026-08-06 07:00:00 -0400', '44.1', 'lb'),
  wt('2026-08-07 07:00:00 -0400', '880', 'lb'), wt('2026-08-08 07:00:00 -0400', '882', 'lb'), wt('2026-08-09 07:00:00 -0400', '0'),
  wt('2026-08-10 07:00:00 -0400', '1000'), wt('2026-08-11 07:00:00 -0400', '70'),
), {
  weights: [
    w('2026-08-02', '07:00', 20, 'morning', '2026-08-02 07:00:00 -0400', '20'),
    w('2026-08-03', '07:00', 400, 'morning', '2026-08-03 07:00:00 -0400', '400'),
    w('2026-08-06', '07:00', 20, 'morning', '2026-08-06 07:00:00 -0400', '44.1'), // 20.003423517
    w('2026-08-07', '07:00', 399.16, 'morning', '2026-08-07 07:00:00 -0400', '880'), // 399.1612856
    w('2026-08-11', '07:00', 70, 'morning', '2026-08-11 07:00:00 -0400', '70'),
  ],
  found: { weights: 11, readings: 0 },
  skipped: { outOfRange: 6 }, // 19.99, 400.01, 44.0 lb (19.96 kg), 882 lb (400.07 kg), 0 and 1000
});

add('a reading outside 50-300 over 20-200, or with the top number not above the bottom, is skipped and counted', doc(
  pair('2026-07-01 08:00:00 -0400', '50', '20'), pair('2026-07-02 08:00:00 -0400', '49', '20'), pair('2026-07-03 08:00:00 -0400', '300', '200'),
  pair('2026-07-04 08:00:00 -0400', '301', '200'), pair('2026-07-05 08:00:00 -0400', '300', '201'), pair('2026-07-06 08:00:00 -0400', '120', '120'),
  pair('2026-07-07 08:00:00 -0400', '80', '120'), pair('2026-07-08 08:00:00 -0400', '51', '50'), pair('2026-07-09 08:00:00 -0400', '50', '49'),
  pair('2026-07-10 08:00:00 -0400', '119.5', '79.5'), pair('2026-07-11 08:00:00 -0400', '119.4', '79.4'),
  pair('2026-07-12 08:00:00 -0400', '49.5', '30'), pair('2026-07-13 08:00:00 -0400', '49.4', '30'),
), {
  readings: [
    r('2026-07-01', '08:00', 50, 20, 'morning', '2026-07-01 08:00:00 -0400', '50', '20'),
    r('2026-07-03', '08:00', 300, 200, 'morning', '2026-07-03 08:00:00 -0400', '300', '200'),
    r('2026-07-08', '08:00', 51, 50, 'morning', '2026-07-08 08:00:00 -0400', '51', '50'),
    r('2026-07-09', '08:00', 50, 49, 'morning', '2026-07-09 08:00:00 -0400', '50', '49'),
    r('2026-07-10', '08:00', 120, 80, 'morning', '2026-07-10 08:00:00 -0400', '119.5', '79.5'), // whole mmHg, half up
    r('2026-07-11', '08:00', 119, 79, 'morning', '2026-07-11 08:00:00 -0400', '119.4', '79.4'),
    r('2026-07-12', '08:00', 50, 30, 'morning', '2026-07-12 08:00:00 -0400', '49.5', '30'),
  ],
  found: { weights: 0, readings: 13 },
  skipped: { outOfRange: 6 }, // 49/20, 301/200, 300/201, 120/120, 80/120, 49.4/30
});

add('a unit the reader does not know is skipped and counted', doc(
  wt('2026-06-01 08:00:00 -0400', '70500', 'g'),
  '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" startDate="2026-06-02 08:00:00 -0400" value="70"/>',
  wt('2026-06-03 08:00:00 -0400', '11', 'st'),
  wt('2026-06-04 08:00:00 -0400', '70', 'KG'),
  rec(S, 'kPa', '2026-06-05 08:00:00 -0400', '16', 'Cuff App'), rec(D, 'kPa', '2026-06-05 08:00:00 -0400', '10.6', 'Cuff App'),
  '<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="Cuff App" startDate="2026-06-06 08:00:00 -0400" value="120"/>',
  pair('2026-06-07 08:00:00 -0400', '120', '80'),
  wt('2026-06-08 08:00:00 -0400', '70'),
), {
  weights: [w('2026-06-08', '08:00', 70, 'morning', '2026-06-08 08:00:00 -0400', '70')],
  readings: [r('2026-06-07', '08:00', 120, 80, 'morning', '2026-06-07 08:00:00 -0400', '120', '80')],
  skipped: { unknownUnit: 7 }, // g, none, st, KG (the unit is compared as written), kPa x2, none
});

add('attributes in any order, with single or double quotes, spaces, tabs and line breaks, self-closing or not', doc(
  '<Record value="70.1" unit="kg" startDate="2026-05-01 07:00:00 -0400" sourceName="Health" type="HKQuantityTypeIdentifierBodyMass"/>',
  "<Record type='HKQuantityTypeIdentifierBodyMass' sourceName='Health' unit='kg' startDate='2026-05-02 07:00:00 -0400' value='70.2'/>",
  `<Record type="HKQuantityTypeIdentifierBodyMass" sourceName='Joe"s Scale' unit='kg' startDate="2026-05-03 07:00:00 -0400" value="70.3"/>`,
  `<Record
\ttype = "HKQuantityTypeIdentifierBodyMass"
\tsourceName = "Health"
\tunit = "kg"
\tstartDate = "2026-05-04 07:00:00 -0400"
\tvalue = "70.4"
/>`,
  `<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-05-05 07:00:00 -0400" value="70.5">
  <MetadataEntry key="HKWasUserEntered" value="1"/>
  <MetadataEntry key="HKExternalUUID" value="999"/>
 </Record>`,
  `<Record\ttype="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-05-06 07:00:00 -0400" value="70.6"/>`,
  `<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" sourceVersion="17.5" device="&lt;&lt;HKDevice: 0x300001, name:Scale, manufacturer:Acme, model:S1&gt;&gt;" unit="kg" creationDate="2026-05-07 07:00:03 -0400" startDate="2026-05-07 07:00:00 -0400" endDate="2026-05-07 07:00:00 -0400" value="70.7"/>`,
  `<Record endDate="2026-05-08 07:30:00 -0400" value="124" startDate="2026-05-08 07:30:00 -0400" unit="mmHg" sourceName="Cuff App" type="${S}"/>`,
  `<Record type='${D}' sourceName='Cuff App' unit='mmHg' startDate='2026-05-08 07:30:00 -0400' value='81'/>`,
), {
  weights: [
    w('2026-05-01', '07:00', 70.1, 'morning', '2026-05-01 07:00:00 -0400', '70.1'),
    w('2026-05-02', '07:00', 70.2, 'morning', '2026-05-02 07:00:00 -0400', '70.2'),
    w('2026-05-03', '07:00', 70.3, 'morning', '2026-05-03 07:00:00 -0400', '70.3', 'Joe"s Scale'),
    w('2026-05-04', '07:00', 70.4, 'morning', '2026-05-04 07:00:00 -0400', '70.4'),
    w('2026-05-05', '07:00', 70.5, 'morning', '2026-05-05 07:00:00 -0400', '70.5'),
    w('2026-05-06', '07:00', 70.6, 'morning', '2026-05-06 07:00:00 -0400', '70.6'),
    w('2026-05-07', '07:00', 70.7, 'morning', '2026-05-07 07:00:00 -0400', '70.7'),
  ],
  readings: [r('2026-05-08', '07:30', 124, 81, 'morning', '2026-05-08 07:30:00 -0400', '124', '81')],
});

add('the five XML entities and numeric references are decoded, once, in the source name, the value and the date', doc(
  wt('2026-04-01 07:00:00 -0400', '70.1', 'kg', 'Dr. A &amp; B Clinic'),
  wt('2026-04-02 07:00:00 -0400', '70.2', 'kg', 'Joe&#x2019;s Scale'),
  wt('2026-04-03 07:00:00 -0400', '70.3', 'kg', 'Joe&#8217;s Scale'),
  wt('2026-04-04 07:00:00 -0400', '70.4', 'kg', '&lt;Scale&gt;'),
  wt('2026-04-05 07:00:00 -0400', '70.5', 'kg', 'Say &quot;hi&quot; &amp; &apos;bye&apos;'),
  wt('2026-04-06 07:00:00 -0400', '70.6', 'kg', '&amp;amp;'),
  wt('2026-04-07 07:00:00 -0400', '70.7', 'kg', '&#38;lt;'),
  wt('2026-04-08 07:00:00 -0400', '70.8', 'kg', 'Scale &#x1F600;'),
  wt('2026-04-09 07:00:00 -0400', '70.9', 'kg', 'Tab&#9;Scale'),
  wt('2026-04-10 07:00:00 -0400', '71.0', 'kg', 'Caf&#xe9; &#233;'),
  wt('2026-04-11 07:00:00 -0400', '71.1', 'kg', '&#x0000041;'),
  '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-04-1&#50; 07:00:00 -0400" value="7&#49;.2"/>',
), {
  weights: [
    w('2026-04-01', '07:00', 70.1, 'morning', '2026-04-01 07:00:00 -0400', '70.1', 'Dr. A & B Clinic'),
    w('2026-04-02', '07:00', 70.2, 'morning', '2026-04-02 07:00:00 -0400', '70.2', 'Joe’s Scale'),
    w('2026-04-03', '07:00', 70.3, 'morning', '2026-04-03 07:00:00 -0400', '70.3', 'Joe’s Scale'),
    w('2026-04-04', '07:00', 70.4, 'morning', '2026-04-04 07:00:00 -0400', '70.4', '<Scale>'),
    w('2026-04-05', '07:00', 70.5, 'morning', '2026-04-05 07:00:00 -0400', '70.5', 'Say "hi" & \'bye\''),
    w('2026-04-06', '07:00', 70.6, 'morning', '2026-04-06 07:00:00 -0400', '70.6', '&amp;'), // &amp;amp; is the text "&amp;"
    w('2026-04-07', '07:00', 70.7, 'morning', '2026-04-07 07:00:00 -0400', '70.7', '&lt;'), // &#38;lt; is the text "&lt;", not "<"
    w('2026-04-08', '07:00', 70.8, 'morning', '2026-04-08 07:00:00 -0400', '70.8', 'Scale 😀'),
    w('2026-04-09', '07:00', 70.9, 'morning', '2026-04-09 07:00:00 -0400', '70.9', 'Tab\tScale'),
    w('2026-04-10', '07:00', 71, 'morning', '2026-04-10 07:00:00 -0400', '71.0', 'Café é'),
    w('2026-04-11', '07:00', 71.1, 'morning', '2026-04-11 07:00:00 -0400', '71.1', 'A'),
    w('2026-04-12', '07:00', 71.2, 'morning', '2026-04-12 07:00:00 -0400', '71.2'), // startDate and value written with references
  ],
  sourceNames: ['&amp;', '&lt;', '<Scale>', 'A', 'Café é', 'Dr. A & B Clinic', 'Health', 'Joe’s Scale', 'Say "hi" & \'bye\'', 'Scale 😀', 'Tab\tScale'],
});

add('any other & skips the record and is counted; nothing is expanded; entities in attributes that are not read do not matter', docDtd(
  '<!ENTITY lol "ha">\n<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">\n',
  wt('2026-03-01 07:00:00 -0500', '70', 'kg', 'A &nbsp; B'),
  wt('2026-03-02 07:00:00 -0500', '70', 'kg', 'Lol &lol;'),
  wt('2026-03-03 07:00:00 -0500', '70', 'kg', 'Lol &lol2;'),
  wt('2026-03-04 07:00:00 -0500', '70', 'kg', 'AT&T'),
  wt('2026-03-05 07:00:00 -0500', '70', 'kg', 'AT&amp'),
  wt('2026-03-06 07:00:00 -0500', '70', 'kg', 'NUL &#0;'),
  wt('2026-03-07 07:00:00 -0500', '70', 'kg', 'Surrogate &#xD800;'),
  wt('2026-03-08 07:00:00 -0500', '70', 'kg', 'Too big &#x110000;'),
  wt('2026-03-09 07:00:00 -0500', '70', 'kg', 'Control &#1;'),
  wt('2026-03-10 07:00:00 -0500', '70', 'kg', 'Empty &#x;'),
  wt('2026-03-11 07:00:00 -0500', '70', 'kg', 'Empty &;'),
  wt('2026-03-12 07:00:00 -0500', '70', 'kg', 'Long &#12345678901;'),
  wt('2026-03-13 07:00:00 -0500', '70', 'kg', 'Upper &AMP;'),
  wt('2026-03-14 07:00:00 -0500', '70', 'kg', 'Upper &#X41;'),
  wt('2026-03-15 07:00:00 -0500', '70', 'kg', 'Mixed &amp;&bogus;'),
  '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" device="&bogus;" unit="kg" startDate="2026-03-16 07:00:00 -0500" value="70.1"/>',
  '<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch &bogus;" unit="count/min" startDate="2026-03-17 07:00:00 -0500" value="60"/>',
  '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="k&#103;" startDate="2026-03-18 07:00:00 -0500" value="70.2"/>',
  '<Record type="HKQuantityTypeIdentifier&#66;odyMass" sourceName="Health" unit="kg" startDate="2026-03-19 07:00:00 -0500" value="70.3"/>',
  sys('2026-03-20 07:00:00 -0500', '120', 'Cuff &bogus;'), dia('2026-03-20 07:00:00 -0500', '80', 'Cuff App'),
), {
  weights: [w('2026-03-16', '07:00', 70.1, 'morning', '2026-03-16 07:00:00 -0500', '70.1')],
  skipped: { badEntity: 16, unknownUnit: 1, halfPair: 1 }, // 15 weights and the systolic with &bogus;; &#103; in a unit is not decoded; the diastolic is alone
});

add('a Record inside the DTD, a comment or a CDATA block is read like any other text', docDtd(
  `<!ENTITY rec '<Record type="${W}" sourceName="In the DTD" unit="kg" startDate="2026-01-01 08:00:00 +0000" value="70.1"/>'>\n`,
  `<!-- <Record type="${W}" sourceName="In a comment" unit="kg" startDate="2026-01-02 08:00:00 +0000" value="70.2"/> -->`,
  `<![CDATA[ <Record type="${W}" sourceName="In a CDATA block" unit="kg" startDate="2026-01-03 08:00:00 +0000" value="70.3"/> ]]>`,
), {
  weights: [
    w('2026-01-01', '08:00', 70.1, 'morning', '2026-01-01 08:00:00 +0000', '70.1', 'In the DTD'),
    w('2026-01-02', '08:00', 70.2, 'morning', '2026-01-02 08:00:00 +0000', '70.2', 'In a comment'),
    w('2026-01-03', '08:00', 70.3, 'morning', '2026-01-03 08:00:00 +0000', '70.3', 'In a CDATA block'),
  ],
});

add('Health\'s own prolog: the XML line, the internal DTD and the root are skipped as text', docDtd('', wt('2026-10-19 07:15:00 -0400', '154.3', 'lb'), pair('2026-10-19 07:20:00 -0400', '122', '78')), {
  weights: [w('2026-10-19', '07:15', 69.99, 'morning', '2026-10-19 07:15:00 -0400', '154.3')],
  readings: [r('2026-10-19', '07:20', 122, 78, 'morning', '2026-10-19 07:20:00 -0400', '122', '78')],
});

// start tags at and around the 8 KiB limit
const PAD_BASE = `<Record type="${W}" sourceName="Health" unit="kg" startDate="2026-02-01 08:00:00 -0500" value="70" device="`;
const padTag = (total, tail = '"/>') => {
  const n = total - PAD_BASE.length - tail.length;
  if (n < 1) throw new Error('tag too short');
  return [PAD_BASE, rep('x', n), tail];
};
const OK_AFTER = wt('2026-02-02 08:00:00 -0500', '70.2');
const KEPT_AFTER = w('2026-02-02', '08:00', 70.2, 'morning', '2026-02-02 08:00:00 -0500', '70.2');
add('a start tag of exactly 8,192 characters is read', doc(padTag(8192), OK_AFTER), {
  weights: [w('2026-02-01', '08:00', 70, 'morning', '2026-02-01 08:00:00 -0500', '70'), KEPT_AFTER],
});
add('a start tag of 8,193 characters is skipped and counted, and the next record is read', doc(padTag(8193), OK_AFTER), {
  weights: [KEPT_AFTER],
  skipped: { tagTooLong: 1 },
});
add('a ">" inside a quoted value of a too-long tag does not end it', doc(padTag(9000, '> still inside the value"/>'), OK_AFTER), {
  weights: [KEPT_AFTER],
  skipped: { tagTooLong: 1 },
});
add('a too-long tag whose quote never closes ends at the next "<"', doc([PAD_BASE, rep('x', 9000)], OK_AFTER), {
  weights: [KEPT_AFTER],
  skipped: { tagTooLong: 1 },
});
add('a too-long tag of a type the reader ignores is counted too; a long tag that is not a Record is not', doc(
  ['<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min" startDate="2026-02-01 08:00:00 -0500" value="60" device="', rep('y', 9000), '"/>'],
  ['<Workout workoutActivityType="HKWorkoutActivityTypeWalking" device="', rep('z', 20000), '"/>'],
  OK_AFTER,
), {
  weights: [KEPT_AFTER],
  skipped: { tagTooLong: 1 },
});

add('other records are ignored without being read: heart rate, steps, glucose, insulin, body mass index, lean mass and look-alike types', doc(
  rec('HKQuantityTypeIdentifierHeartRate', 'count/min', '2026-10-19 07:10:00 -0400', '64', 'Sam’s Apple Watch'),
  rec('HKQuantityTypeIdentifierStepCount', 'count', '2026-10-19 07:11:00 -0400', '120', 'Sam’s iPhone'),
  rec('HKQuantityTypeIdentifierActiveEnergyBurned', 'kcal', '2026-10-19 07:12:00 -0400', '5.2', 'Sam’s Apple Watch'),
  rec('HKQuantityTypeIdentifierBloodGlucose', 'mg/dL', '2026-10-19 07:13:00 -0400', '112', 'Glucose App'),
  rec('HKQuantityTypeIdentifierBloodGlucose', 'mg/dL', '2026-10-19 07:13:00 -0400', '9&#99;', 'Glucose &bogus;'),
  rec('HKQuantityTypeIdentifierInsulinDelivery', 'IU', '2026-10-19 07:14:00 -0400', '4', 'Pump App'),
  wt('2026-10-19 07:15:00 -0400', '70.5'),
  rec('HKQuantityTypeIdentifierBodyMassIndex', 'count', '2026-10-19 07:15:00 -0400', '23.4'),
  rec('HKQuantityTypeIdentifierLeanBodyMass', 'kg', '2026-10-19 07:15:00 -0400', '55'),
  rec('HKQuantityTypeIdentifierBodyFatPercentage', '%', '2026-10-19 07:15:00 -0400', '0.21'),
  rec('HKQuantityTypeIdentifierBloodPressureSystolicExtra', 'mmHg', '2026-10-19 07:16:00 -0400', '120'),
  rec('HKQuantityTypeIdentifierBloodPressureDiastolicExtra', 'mmHg', '2026-10-19 07:16:00 -0400', '80'),
  rec('HKQuantityTypeIdentifierOxygenSaturation', '%', '2026-10-19 07:17:00 -0400', '0.97'),
  rec('HKCategoryTypeIdentifierSleepAnalysis', '', '2026-10-19 07:18:00 -0400', 'HKCategoryValueSleepAnalysisAsleep'),
  '<Correlation type="HKCorrelationTypeIdentifierFood" sourceName="Food App" startDate="2026-10-19 07:19:00 -0400" endDate="2026-10-19 07:19:00 -0400"><MetadataEntry key="HKFoodType" value="Toast"/></Correlation>',
  '<ActivitySummary dateComponents="2026-10-19" activeEnergyBurned="400" appleExerciseTime="30" appleStandHours="10"/>',
  '<ClinicalRecord type="Observation" identifier="example-obs-1" sourceName="Example Hospital" sourceURL="https://example.invalid/fhir/Observation/1" fhirVersion="4.0.1" receivedDate="2026-10-19 07:00:00 -0400" resourceFilePath="/clinical-records/Observation-example-obs-1.json"/>',
), {
  weights: [w('2026-10-19', '07:15', 70.5, 'morning', '2026-10-19 07:15:00 -0400', '70.5')],
});

add('sources are kept on the rows and listed, sorted', doc(
  wt('2026-05-01 07:00:00 -0400', '70.1', 'kg', 'Health'),
  wt('2026-05-02 07:00:00 -0400', '70.2', 'kg', 'Sam’s iPhone'),
  pair('2026-05-03 19:00:00 -0400', '124', '80', 'Sam’s Apple Watch'),
  pair('2026-05-04 07:30:00 -0400', '126', '82', 'Cuff App'),
), {
  weights: [
    w('2026-05-01', '07:00', 70.1, 'morning', '2026-05-01 07:00:00 -0400', '70.1', 'Health'),
    w('2026-05-02', '07:00', 70.2, 'morning', '2026-05-02 07:00:00 -0400', '70.2', 'Sam’s iPhone'),
  ],
  readings: [
    r('2026-05-03', '19:00', 124, 80, 'evening', '2026-05-03 19:00:00 -0400', '124', '80', 'Sam’s Apple Watch'),
    r('2026-05-04', '07:30', 126, 82, 'morning', '2026-05-04 07:30:00 -0400', '126', '82', 'Cuff App'),
  ],
  firstDate: '2026-05-01',
  lastDate: '2026-05-04',
  sourceNames: ['Cuff App', 'Health', 'Sam’s Apple Watch', 'Sam’s iPhone'],
});

add('date and time are the startDate as written, not converted to UTC; dates the calendar does not have are unreadable', doc(
  wt('2024-02-29 08:00:00 +0100', '70.1'), wt('2026-10-19 23:30:00 +0900', '70.2'), wt('2026-10-20 00:15:00 -0800', '70.3'),
  wt('1900-01-01 12:00:00 +0000', '70.4'),
  '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" value="70.5"/>',
  wt('2026-10-19T08:00:00Z', '70.6'), wt('2026-13-01 08:00:00 -0400', '70.7'), wt('2025-02-29 08:00:00 -0400', '70.8'),
  wt('1899-12-31 08:00:00 -0400', '70.9'), wt('2026-10-19 25:00:00 -0400', '71.0'), wt('2026-10-19 08:60:00 -0400', '71.1'),
  wt('2026-10-19 08:00:60 -0400', '71.2'), wt('2026-10-19 08:00:00 -2500', '71.3'), wt('2026-10-19 08:00:00 -0460', '71.4'),
  wt('2026-10-19 08:00:00', '71.5'), wt('2026-10-19  08:00:00 -0400', '71.6'), wt('', '71.7'), wt('2026-4-19 08:00:00 -0400', '71.8'),
), {
  weights: [
    w('1900-01-01', '12:00', 70.4, 'other', '1900-01-01 12:00:00 +0000', '70.4'),
    w('2024-02-29', '08:00', 70.1, 'morning', '2024-02-29 08:00:00 +0100', '70.1'), // the 29th of a leap year
    w('2026-10-19', '23:30', 70.2, 'other', '2026-10-19 23:30:00 +0900', '70.2'), // 14:30 UTC, still 23:30 on the person's clock
    w('2026-10-20', '00:15', 70.3, 'other', '2026-10-20 00:15:00 -0800', '70.3'), // 08:15 UTC
  ],
  skipped: { unreadable: 14 },
});

const FUTURE_XML = doc(
  wt('2026-10-20 12:00:00 -0400', '70.1'), wt('2026-10-21 08:00:00 -0400', '70.2'), wt('2026-10-22 08:00:00 -0400', '70.3'), wt('2027-01-01 08:00:00 -0400', '70.4'),
  pair('2026-10-23 08:00:00 -0400', '120', '80'),
);
add('with opts.today, a day more than one day after it is unreadable (the server allows one day of time-zone slack)', FUTURE_XML, {
  weights: [
    w('2026-10-20', '12:00', 70.1, 'other', '2026-10-20 12:00:00 -0400', '70.1'),
    w('2026-10-21', '08:00', 70.2, 'morning', '2026-10-21 08:00:00 -0400', '70.2'),
  ],
  skipped: { unreadable: 4 }, // two weights and the two halves of the reading
}, { today: '2026-10-20' });
add('without opts.today, no date is called a future date', FUTURE_XML, {
  weights: [
    w('2026-10-20', '12:00', 70.1, 'other', '2026-10-20 12:00:00 -0400', '70.1'),
    w('2026-10-21', '08:00', 70.2, 'morning', '2026-10-21 08:00:00 -0400', '70.2'),
    w('2026-10-22', '08:00', 70.3, 'morning', '2026-10-22 08:00:00 -0400', '70.3'),
    w('2027-01-01', '08:00', 70.4, 'morning', '2027-01-01 08:00:00 -0400', '70.4'),
  ],
  readings: [r('2026-10-23', '08:00', 120, 80, 'morning', '2026-10-23 08:00:00 -0400', '120', '80')],
});

add('a value that is not a plain number is unreadable; a missing source name is unreadable', doc(
  wt('2026-02-01 07:00:00 -0500', ''), wt('2026-02-02 07:00:00 -0500', 'abc'), wt('2026-02-03 07:00:00 -0500', '-70'), wt('2026-02-04 07:00:00 -0500', '7e1'),
  wt('2026-02-05 07:00:00 -0500', '70,5'), '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-02-06 07:00:00 -0500"/>',
  wt('2026-02-07 07:00:00 -0500', ' 70.5'), wt('2026-02-08 07:00:00 -0500', '70.'), wt('2026-02-09 07:00:00 -0500', '.5'),
  wt('2026-02-10 07:00:00 -0500', '1e999'), wt('2026-02-11 07:00:00 -0500', '123456789012345678'),
  '<Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" startDate="2026-02-12 07:00:00 -0500" value="70"/>',
  wt('2026-02-13 07:00:00 -0500', '070.5'), wt('2026-02-14 07:00:00 -0500', '0.0'),
  sys('2026-02-15 07:00:00 -0500', 'abc'), dia('2026-02-15 07:00:00 -0500', '80'),
), {
  weights: [w('2026-02-13', '07:00', 70.5, 'morning', '2026-02-13 07:00:00 -0500', '070.5')],
  found: { weights: 2, readings: 0 },
  skipped: { unreadable: 13, outOfRange: 1, halfPair: 1 }, // 11 values, a source name, and the systolic "abc"; 0.0 kg; the diastolic left alone
});

add('a file with a prolog and no records, and tags that only look like a Record', docDtd('', '<HealthData/>', '<RecordX type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-01-01 07:00:00 -0500" value="70"/>',
  '<Records type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-01-02 07:00:00 -0500" value="70"/>',
  '<Record/>', '<Record>', '</Record>',
  '<record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-01-03 07:00:00 -0500" value="70"/>',
  '< Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-01-04 07:00:00 -0500" value="70"/>',
  '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-01-05 07:00:00 -0500" value="70"/>'), {});
add('an empty file', '', {});

add('a file that ends inside a tag counts that tag as unreadable', `${doc(wt('2026-01-01 07:00:00 -0500', '70'))}<Record type="${W}" sourceName="Health" unit="kg" start`, {
  weights: [w('2026-01-01', '07:00', 70, 'morning', '2026-01-01 07:00:00 -0500', '70')],
  skipped: { unreadable: 1 },
});
add('a file that ends in the first letters of a tag does not', `${doc(wt('2026-01-01 07:00:00 -0500', '70'))}<Reco`, {
  weights: [w('2026-01-01', '07:00', 70, 'morning', '2026-01-01 07:00:00 -0500', '70')],
});
add('a file that ends inside a too-long tag counts it once, as too long', join_([doc(wt('2026-01-01 07:00:00 -0500', '70')), PAD_BASE, rep('x', 9000)]), {
  weights: [w('2026-01-01', '07:00', 70, 'morning', '2026-01-01 07:00:00 -0500', '70')],
  skipped: { tagTooLong: 1 },
});

add('a ">" inside a quoted value does not end the tag', doc(
  wt('2026-01-01 07:00:00 -0500', '70.1', 'kg', 'Left > Right'),
  `<Record type="${W}" sourceName='say "hi" > bye' unit="kg" startDate="2026-01-02 07:00:00 -0500" value="70.2"/>`,
  `<Record type="${W}" sourceName="Joe's > Scale" unit="kg" startDate="2026-01-03 07:00:00 -0500" value="70.3"/>`,
  `<Record type="${W}" sourceName="Health" device="a>b" unit="kg" startDate="2026-01-04 07:00:00 -0500" value="70.4"/>`,
), {
  weights: [
    w('2026-01-01', '07:00', 70.1, 'morning', '2026-01-01 07:00:00 -0500', '70.1', 'Left > Right'),
    w('2026-01-02', '07:00', 70.2, 'morning', '2026-01-02 07:00:00 -0500', '70.2', 'say "hi" > bye'),
    w('2026-01-03', '07:00', 70.3, 'morning', '2026-01-03 07:00:00 -0500', '70.3', 'Joe\'s > Scale'),
    w('2026-01-04', '07:00', 70.4, 'morning', '2026-01-04 07:00:00 -0500', '70.4'),
  ],
});

add('a tag cut short by another "<" is unreadable, and scanning goes on at that "<"', doc(
  `<Record type="${W}" sourceName="Health" ${wt('2026-02-01 07:00:00 -0500', '70.1')}`,
  `<Record type="${W}" sourceName="a<b" unit="kg" startDate="2026-02-02 07:00:00 -0500" value="70.2"/>`,
  `<Record type="${W}" sourceName="Health" unit="kg" startDate="2026-02-03 07:00:00 -0500" value="70.3" </Record>`,
), {
  weights: [w('2026-02-01', '07:00', 70.1, 'morning', '2026-02-01 07:00:00 -0500', '70.1')],
  skipped: { unreadable: 3 },
});

add('the first of a repeated attribute wins', doc(
  `<Record type="${W}" sourceName="Health" unit="kg" startDate="2026-01-05 07:00:00 -0400" value="70.1" value="99"/>`,
  `<Record type="HKQuantityTypeIdentifierHeartRate" type="${W}" sourceName="Health" unit="kg" startDate="2026-01-06 07:00:00 -0400" value="70.2"/>`,
), {
  weights: [w('2026-01-05', '07:00', 70.1, 'morning', '2026-01-05 07:00:00 -0400', '70.1')],
});

add('rows come out sorted by date, time and source whatever the file order', doc(
  wt('2026-03-03 07:00:00 -0500', '70.3'), wt('2026-03-01 19:00:00 -0500', '70.1'), wt('2026-03-01 07:00:00 -0500', '70.0'),
  pair('2026-03-02 21:00:00 -0500', '132', '86'), pair('2026-03-01 08:00:00 -0500', '128', '82', 'Cuff B'), pair('2026-03-01 08:00:00 -0500', '126', '80', 'Cuff A'),
), {
  weights: [
    w('2026-03-01', '07:00', 70, 'morning', '2026-03-01 07:00:00 -0500', '70.0'),
    w('2026-03-01', '19:00', 70.1, 'other', '2026-03-01 19:00:00 -0500', '70.1'),
    w('2026-03-03', '07:00', 70.3, 'morning', '2026-03-03 07:00:00 -0500', '70.3'),
  ],
  readings: [
    r('2026-03-01', '08:00', 126, 80, 'morning', '2026-03-01 08:00:00 -0500', '126', '80', 'Cuff A'),
    r('2026-03-01', '08:00', 128, 82, 'morning', '2026-03-01 08:00:00 -0500', '128', '82', 'Cuff B'),
    r('2026-03-02', '21:00', 132, 86, 'evening', '2026-03-02 21:00:00 -0500', '132', '86'),
  ],
  firstDate: '2026-03-01',
  lastDate: '2026-03-03',
  sourceNames: ['Cuff A', 'Cuff App', 'Cuff B', 'Health'],
});

add('the same record again is counted once; the key is made of the type, startDate, value and source only', doc(
  wt('2026-04-01 07:00:00 -0400', '70.5'), wt('2026-04-01 07:00:00 -0400', '70.5'), wt('2026-04-01 07:00:00 -0400', '70.5'),
  `<Record type="${W}" sourceName="Health" unit="kg" creationDate="2026-04-02 09:00:00 -0400" startDate="2026-04-01 07:00:00 -0400" endDate="2026-04-01 07:00:30 -0400" value="70.5"/>`,
  wt('2026-04-01 07:00:00 -0400', '70.5', 'kg', 'Scale App'),
  wt('2026-04-01 07:00:00 -0400', '70.50'),
), {
  weights: [
    w('2026-04-01', '07:00', 70.5, 'morning', '2026-04-01 07:00:00 -0400', '70.50'),
    w('2026-04-01', '07:00', 70.5, 'morning', '2026-04-01 07:00:00 -0400', '70.5'),
    w('2026-04-01', '07:00', 70.5, 'morning', '2026-04-01 07:00:00 -0400', '70.5', 'Scale App'),
  ],
  skipped: { duplicate: 3 },
});

add('a byte order mark and Windows line endings', `﻿${doc(wt('2026-01-01 07:00:00 -0500', '70'), pair('2026-01-02 07:00:00 -0500', '120', '80')).replace(/\n/g, '\r\n')}`, {
  weights: [w('2026-01-01', '07:00', 70, 'morning', '2026-01-01 07:00:00 -0500', '70')],
  readings: [r('2026-01-02', '07:00', 120, 80, 'morning', '2026-01-02 07:00:00 -0500', '120', '80')],
});

add('characters outside the Basic Multilingual Plane written as themselves', doc(wt('2026-01-01 07:00:00 -0500', '70', 'kg', 'Zoë’s Scale 😀 体重')), {
  weights: [w('2026-01-01', '07:00', 70, 'morning', '2026-01-01 07:00:00 -0500', '70', 'Zoë’s Scale 😀 体重')],
});

// Explicit chunks: "¦" marks where one chunk ends and the next begins.
addChunks('chunks that split a tag start, an attribute name, "=", a value, an entity and the end of the tag',
  [
    '<?xml version="1.0"?>\n<¦Rec¦ord¦ type="HKQuantityTypeIdentifierBodyMass" source¦Name¦=¦"Smith &¦amp¦; Sons" unit="kg" startDate="2026-10-19 07:15:00 -0400" value="70.5"/¦>\n',
    '<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="Cuff &#x¦2019¦;s App" unit="mmHg" startDate="2026-10-19 07:20:00 -0400" value="122"/>\n',
    '<Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" sourceName="Cuff &#¦8217;s App" unit="mmHg" startDate="2026-10-19 07:20:00 -0400" value="78"¦ />\n',
    '<Record type="HKQuantityTypeIdentifierBodyMass" sourceName="Left >¦ Right" unit="kg" startDate="2026-10-19 08:15:00 -0400" value="71"¦/¦>',
    '<', '¦', '<Record', '¦', ' type="HKQuantityTypeIdentifierBodyMass" sourceName="Health" unit="kg" startDate="2026-10-19 09:15:00 -0400" value="72"/>',
  ].join(''),
  {
    weights: [
      w('2026-10-19', '07:15', 70.5, 'morning', '2026-10-19 07:15:00 -0400', '70.5', 'Smith & Sons'),
      w('2026-10-19', '08:15', 71, 'morning', '2026-10-19 08:15:00 -0400', '71', 'Left > Right'),
      w('2026-10-19', '09:15', 72, 'morning', '2026-10-19 09:15:00 -0400', '72'),
    ],
    readings: [r('2026-10-19', '07:20', 122, 78, 'morning', '2026-10-19 07:20:00 -0400', '122', '78', 'Cuff ’s App')],
    sourceNames: ['Cuff ’s App', 'Health', 'Left > Right', 'Smith & Sons'],
  });

addChunks('chunks that end on the first letters of a tag that is not one',
  `<Record¦s type="${W}" sourceName="Health" unit="kg" startDate="2026-01-01 07:00:00 -0500" value="70"/><Rec¦ord/><¦Record¦>x</Record¦><Record¦ type="${W}"/>${wt('2026-01-02 07:00:00 -0500', '70.2')}<Recor¦`,
  { weights: [w('2026-01-02', '07:00', 70.2, 'morning', '2026-01-02 07:00:00 -0500', '70.2')] });

// ---- assemble, check with the module at every chunk size, and write ---------------------------------------------------------------------
const chunked = (text, size) => {
  if (size === 'whole') return [text];
  const out = [];
  for (let at = 0; at < text.length; at += size) out.push(text.slice(at, at + size));
  return out;
};
const nonzero = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== 0));
const problems = [];
const output = [];
for (const c of cases) {
  const text = c.chunks ? c.chunks.join('') : expand(c.xml);
  const weights = (c.want.weights || []).map((row) => ({ ...row, source_key: sha32(row.key_input) }));
  const readings = (c.want.readings || []).map((row) => ({ ...row, source_key: sha32(row.key_input) }));
  const keys = [...weights, ...readings].map((row) => row.source_key);
  if (new Set(keys).size !== keys.length) problems.push(`${c.name}: two rows have the same source_key`);
  const rows = [...weights, ...readings];
  const dates = rows.map((row) => row.date).sort();
  const summary = {
    found: c.want.found || { weights: weights.length, readings: readings.length },
    kept: { weights: weights.length, readings: readings.length },
    skipped: { unknownUnit: 0, halfPair: 0, outOfRange: 0, badEntity: 0, tagTooLong: 0, duplicate: 0, unreadable: 0, ...(c.want.skipped || {}) },
    firstDate: c.want.firstDate !== undefined ? c.want.firstDate : dates.length ? dates[0] : null,
    lastDate: c.want.lastDate !== undefined ? c.want.lastDate : dates.length ? dates[dates.length - 1] : null,
    sourceNames: c.want.sourceNames || [...new Set(rows.map((row) => row.sourceName))].sort(),
  };
  const expected = { weights, readings, summary };
  const strip = (list) => list.map(({ key_input, ...row }) => row);
  const wantForModule = { weights: strip(weights), readings: strip(readings), summary };
  const runs = SIZES.map((size) => ({ label: `size ${size}`, chunks: chunked(text, size) }));
  if (c.chunks) runs.push({ label: 'the case\'s own chunks', chunks: c.chunks });
  for (const run of runs) {
    let got;
    try {
      got = plain(await A.scan(run.chunks, c.options));
    } catch (e) {
      problems.push(`${c.name} (${run.label}): ${e && e.stack ? e.stack : e}`);
      continue;
    }
    const gotComparable = { weights: got.weights, readings: got.readings, summary: got.summary };
    if (!isDeepStrictEqual(gotComparable, wantForModule)) {
      problems.push(`${c.name} (${run.label}): the module disagrees\n   got  ${JSON.stringify(gotComparable)}\n   want ${JSON.stringify(wantForModule)}`);
    }
    if (got.stats.maxCarry > A.MAX_TAG) problems.push(`${c.name} (${run.label}): carry-over of ${got.stats.maxCarry} characters`);
    if (got.stats.chars !== text.length) problems.push(`${c.name} (${run.label}): read ${got.stats.chars} of ${text.length} characters`);
  }
  const entry = { name: c.name };
  if (c.chunks) entry.chunks = c.chunks;
  else entry.xml = c.xml;
  if (Object.keys(c.options).length) entry.options = c.options;
  entry.expected = expected;
  output.push(entry);
}

// the tag-length cases really are 8,192 and 8,193 characters
const tagLength = (parts) => expand(parts).length;
if (tagLength(padTag(8192)) !== 8192 || tagLength(padTag(8193)) !== 8193) problems.push('the padded tags are not 8192 and 8193 characters');

// ---- the helpers' vectors, written by hand -----------------------------------------------------------------------------------------------
const defaultSince = [
  ['2026-10-22', '2026-07-22'], ['2026-05-31', '2026-02-28'], ['2024-05-31', '2024-02-29'], ['2026-01-31', '2025-10-31'],
  ['2026-03-31', '2025-12-31'], ['2026-02-28', '2025-11-28'], ['2026-12-31', '2026-09-30'], ['2026-11-30', '2026-08-30'],
  ['2026-08-31', '2026-05-31'], ['2026-03-01', '2025-12-01'], ['2026-01-01', '2025-10-01'], ['2026-06-30', '2026-03-30'],
  ['2028-05-29', '2028-02-29'], ['1900-04-30', '1900-01-30'],
].map(([today, since]) => ({ today, since }));
const defaultSinceErrors = ['2026-13-01', '2026-02-30', 'yesterday', '', '2026-10-2', null, 20261022];

const dayList = ['2026-07-20', '2026-07-21', '2026-07-22', '2026-07-23', '2026-10-22'];
const filterSince = [
  { name: 'the day itself is kept', since: '2026-07-22', expected: ['2026-07-22', '2026-07-23', '2026-10-22'] },
  { name: 'the day before is not', since: '2026-07-23', expected: ['2026-07-23', '2026-10-22'] },
  { name: 'everything: no date', since: null, expected: dayList },
  { name: 'everything: empty text', since: '', expected: dayList },
  { name: 'a date after the last row', since: '2027-01-01', expected: [] },
  { name: 'a date before the first', since: '1900-01-01', expected: dayList },
];
const filterSinceErrors = ['2026-7-22', 'last week', '2026-02-30', 20260722];

const batchCases = [
  { count: 0, size: 1000, sizes: [] }, { count: 1, size: 1000, sizes: [1] }, { count: 999, size: 1000, sizes: [999] },
  { count: 1000, size: 1000, sizes: [1000] }, { count: 1001, size: 1000, sizes: [1000, 1] }, { count: 2000, size: 1000, sizes: [1000, 1000] },
  { count: 2500, size: 1000, sizes: [1000, 1000, 500] }, { count: 7, size: 3, sizes: [3, 3, 1] },
];
const batchErrors = [0, -1, 1.5, '1000', null];

const watch = [
  ['Sam’s Apple Watch', true], ['Apple Watch', true], ['WATCH', true], ['watchOS Health', true], ['Smart Scale (Watch band)', true],
  ['Health', false], ['Cuff App', false], ['Sam’s iPhone', false], ['', false], ['Wa tch', false], [null, false],
];

const upload = [
  {
    row: { date: '2026-10-19', time: '07:15', kg: 69.99, context: 'morning', source_key: 'bbce80906ef88e6c11ae1515374f8027', sourceName: 'Health' },
    expected: { date: '2026-10-19', time: '07:15', kg: 69.99, context: 'morning', source_key: 'bbce80906ef88e6c11ae1515374f8027' },
  },
  {
    row: { date: '2026-10-19', time: '07:20', systolic: 122, diastolic: 78, context: 'morning', source_key: '679aa49edce839d69e31cce6ef39f2e5', sourceName: 'Omron & Co' },
    expected: { date: '2026-10-19', time: '07:20', systolic: 122, diastolic: 78, context: 'morning', source_key: '679aa49edce839d69e31cce6ef39f2e5' },
  },
];

// SHA-256 (FIPS 180-4 / NIST examples); the long ones are a recipe
const sha256 = [
  { name: 'the empty text', text: '', digest: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' },
  { name: 'abc', text: 'abc', digest: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' },
  { name: 'the 448-bit message', text: 'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq', digest: '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1' },
  { name: 'a million times "a"', repeat: { text: 'a', count: 1000000 }, digest: 'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0' },
  { name: 'a weight key', text: 'HKQuantityTypeIdentifierBodyMass|2026-10-19 07:15:00 -0400|154.3|Health', digest: 'bbce80906ef88e6c11ae1515374f8027' },
  { name: 'a blood pressure key', text: 'BloodPressure|2026-10-19 07:20:00 -0400|122/78|Omron & Co', digest: '679aa49edce839d69e31cce6ef39f2e5' },
];
for (const s of sha256) {
  const text = s.repeat ? s.repeat.text.repeat(s.repeat.count) : s.text;
  const full = createHash('sha256').update(text, 'utf8').digest('hex');
  if (!full.startsWith(s.digest)) problems.push(`sha256 "${s.name}": node says ${full}, the vector says ${s.digest}`);
}

if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}

const doc_ = {
  about: 'js/engine/apple_health.js answers (weights and blood pressure readings from the iPhone Health app\'s export.xml, read on the device as a stream of text); generated by tests/js/gen_apple_health_vectors.mjs from hand-written export.xml fragments and hand-written expectations (the script stops if the module disagrees; only each source_key is computed, from the hand-written key_input text), replayed at chunk sizes 1, 7, 64 and whole by tests/js/run_vectors.mjs, source_keys recomputed with hashlib by tests/test_apple_health.py',
  limits: {
    max_tag: A.MAX_TAG, batch_size: A.BATCH_SIZE, progress_step: A.PROGRESS_STEP, kg_per_lb: A.KG_PER_LB, ranges: plain(A.RANGES),
    types: { weight: A.TYPE_WEIGHT, systolic: A.TYPE_SYSTOLIC, diastolic: A.TYPE_DIASTOLIC },
  },
  chunk_sizes: SIZES,
  cases: output,
  default_since: defaultSince,
  default_since_errors: defaultSinceErrors,
  filter_since: filterSince,
  filter_since_errors: filterSinceErrors,
  batches: batchCases,
  batch_errors: batchErrors,
  watch,
  upload,
  sha256,
};
writeFileSync(OUT, `${JSON.stringify(doc_, null, 1)}\n`);
console.log(`wrote ${OUT}: ${output.length} cases x ${SIZES.length} chunk sizes, ${defaultSince.length} default_since, ${sha256.length} sha256`);
