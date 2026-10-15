#!/usr/bin/env node
// Writes tests/data/fhir_labs_vectors.json: what js/engine/fhir_labs.js (Lab results → "Import from Apple Health", clinical
// records as FHIR JSON files read on the device) answers for each case below. The reader has no Python twin (the files are read
// in the browser; the server only sees the rows the person keeps), so the file pins its behaviour. Every case carries a `want` that
// is written BY HAND here (the counts that are not zero, the rows newest first, a part of each refusal's words): this script stops
// when the module disagrees, so the pinned answers are not just a copy of what the module said. All resources are invented
// (made-up names, ids and values; no real person's data). tests/test_fhir_labs.py checks every converted value against
// app/units.py and sends every importable row to POST /api/labs/import; node tests/js/run_vectors.mjs replays the cases.
//
//   node tests/js/gen_fhir_labs_vectors.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const ENGINE = ['rules', 'kidney_function', 'fhir_labs'].map((p) => `app/static/js/engine/${p}.js`);
const OUT = join(ROOT, 'tests', 'data', 'fhir_labs_vectors.json');

const context = vm.createContext({ console });
for (const rel of ENGINE) vm.runInContext(readFileSync(join(ROOT, rel), 'utf8'), context, { filename: rel });
const F = vm.runInContext('globalThis.KH.fhirLabs', context);
const plain = (v) => JSON.parse(JSON.stringify(v));

const TODAY = '2026-10-15';
const LOINC = 'http://loinc.org';
const UCUM = 'http://unitsofmeasure.org';
const opts = (extra = {}) => ({ today: TODAY, tzOffsetMinutes: 0, ...extra });

// ---- hand-written resources --------------------------------------------------------------------------------------------------
// subject/performer carry a made-up name and id on purpose: the reader never looks at them, so they appear in no answer.
const SUBJECT = { reference: 'Patient/example-0001', display: 'Sam Example' };
const CATEGORY = [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'laboratory', display: 'Laboratory' }] }];
let serial = 0;
function observation(code, value, unit, ucum, date, extra = {}) {
  serial += 1;
  const o = {
    resourceType: 'Observation',
    id: `example-obs-${serial}`,
    status: 'final',
    category: CATEGORY,
    code: { coding: [{ system: 'http://example.org/local-lab-codes', code: `L${serial}` }, { system: LOINC, code }], text: `test ${code}` },
    subject: SUBJECT,
    performer: [{ reference: 'Practitioner/example-0002', display: 'Dr Example' }],
    effectiveDateTime: date,
    valueQuantity: { value, unit, system: UCUM, code: ucum },
  };
  return { ...o, ...extra };
}
const file = (name, resource) => ({ name, text: JSON.stringify(resource) });
const bundle = (...resources) => ({ resourceType: 'Bundle', type: 'collection', entry: resources.map((resource) => ({ fullUrl: `urn:uuid:${resource.id || 'x'}`, resource })) });

// Every code in the table: [value as the lab printed it, the unit text, the UCUM code].
const SAMPLE = {
  '2823-3': [4.6, 'mmol/L', 'mmol/L'],
  '77142-8': [4.8, 'mmol/L', 'mmol/L'],
  '2777-1': [4.1, 'mg/dL', 'mg/dL'],
  '14879-1': [1.3, 'mmol/L', 'mmol/L'],
  '1751-7': [3.9, 'g/dL', 'g/dL'],
  '61151-7': [4.0, 'g/dL', 'g/dL'],
  '61152-5': [3.7, 'g/dL', 'g/dL'],
  '77148-5': [38, 'g/L', 'g/L'],
  '1963-8': [23, 'mmol/L', 'mmol/L'],
  '2028-9': [24, 'meq/L', 'meq/L'],
  '9318-7': [24, 'mg/g', 'ug/mg{creat}'],
  '14959-1': [18, 'mg/g creat', 'mg/g{creat}'],
  '32294-1': [2.1, 'mg/mmol creat', 'mg/mmol{creat}'],
  '30000-4': [3.4, 'mg/mmol', 'mg/mmol{creat}'],
  '2160-0': [1.7, 'mg/dL', 'mg/dL'],
  '14682-9': [150, 'umol/L', 'umol/L'],
  '77140-2': [162, 'µmol/L', 'umol/L'],
  '33863-2': [1.45, 'mg/L', 'mg/L'],
  '98979-8': [41, 'mL/min/1.73m*2', 'mL/min/{1.73_m2}'],
  '98980-6': [44, 'mL/min/{1.73_m2}', 'mL/min/{1.73_m2}'],
  '62238-1': [52, 'mL/min/1.73m2', 'mL/min/{1.73_m2}'],
  '94677-2': [47, 'mL/min/1.73 sq m', 'mL/min/{1.73_m2}'],
  '50210-4': [49, 'mL/min/1.73m^2', 'mL/min/{1.73_m2}'],
  '4548-4': [7.1, '%', '%'],
  '17856-6': [6.8, '%', '%'],
  '4549-2': [53, 'mmol/mol', 'mmol/mol'],
};
const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
const everyCode = F.LOINC_LIST.map(([, code], i) => {
  const [value, unit, ucum] = SAMPLE[code];
  return file(`Observation-${code}.json`, observation(code, value, unit, ucum, addDays('2026-03-01', i * 3)));
});

// Files a pick can hold (a Health export has many more kinds than lab results).
const patient = { resourceType: 'Patient', id: 'example-0001', name: [{ family: 'Example', given: ['Sam'] }], birthDate: '1970-01-01' };
const condition = { resourceType: 'Condition', id: 'example-cond', code: { coding: [{ system: 'http://snomed.info/sct', code: '709044004', display: 'Chronic kidney disease' }] } };
const immunization = { resourceType: 'Immunization', id: 'example-imm', status: 'completed', vaccineCode: { text: 'Influenza' } };
const bp = observation('85354-9', 128, 'mm[Hg]', 'mm[Hg]', '2026-09-20'); // a blood pressure panel code: not a test the app keeps

const CASES = [
  // ---- the table ------------------------------------------------------------------------------------------------------------
  ['every code in the table, one file each, with the unit LOINC gives', everyCode, opts(), {
    counts: { files: 26, read: 26, observations: 26, found: 26 },
    rowCount: 26,
    firstRows: ['2026-05-15 a1c 53 mmol/mol = 7.0 %', '2026-05-12 a1c 6.8 %', '2026-05-09 a1c 7.1 %'],
  }],
  ['units written in the several ways real exports use all reach the same canonical value', [
    file('a.json', observation('2160-0', 1.7, 'mg/dL', 'mg/dL', '2026-09-01')),
    file('b.json', observation('14682-9', 150.28, 'µmol/L', 'umol/L', '2026-09-02')),
    file('c.json', observation('2777-1', 3.9, 'mg/dL', undefined, '2026-09-03')),
    file('d.json', observation('14879-1', 1.3, 'mmol/L', undefined, '2026-09-04')),
    file('e.json', observation('4548-4', 53, 'mmol/mol', 'mmol/mol', '2026-09-05')),
    file('f.json', observation('1751-7', 40, 'g/L', 'g/L', '2026-09-06')),
    file('g.json', observation('9318-7', 3.4, 'mg/mmol', 'mg/mmol', '2026-09-07')),
    file('h.json', observation('2823-3', 4.7, 'mEq/L', 'meq/L', '2026-09-08')),
    file('i.json', observation('62238-1', 38, 'mL/min/1.73m*2', 'mL/min/{1.73_m2}', '2026-09-09')),
  ], opts(), {
    counts: { files: 9, read: 9, observations: 9, found: 9 },
    rows: [
      '2026-09-09 egfr 38 mL/min/1.73 m²', '2026-09-08 potassium 4.7 mEq/L = 4.7 mmol/L', '2026-09-07 uacr 3.4 mg/mmol = 30.1 mg/g',
      '2026-09-06 albumin 40 g/L = 4.0 g/dL', '2026-09-05 a1c 53 mmol/mol = 7.0 %', '2026-09-04 phosphate 1.3 mmol/L = 4.0 mg/dL',
      '2026-09-03 phosphate 3.9 mg/dL', '2026-09-02 creatinine 150.28 µmol/L = 1.70 mg/dL', '2026-09-01 creatinine 1.70 mg/dL',
    ],
  }],
  // ---- shapes ---------------------------------------------------------------------------------------------------------------
  ['a Bundle of Observations, with a Patient and a Condition in it, is read entry by entry', [
    file('Bundle-labs.json', bundle(patient, observation('2823-3', 5.2, 'mmol/L', 'mmol/L', '2026-08-10'), condition,
      observation('2160-0', 1.9, 'mg/dL', 'mg/dL', '2026-08-10'), observation('33863-2', 1.6, 'mg/L', 'mg/L', '2026-08-10'))),
  ], opts(), {
    counts: { files: 1, read: 1, observations: 3, notLab: 2, found: 3 },
    rows: ['2026-08-10 potassium 5.2 mmol/L', '2026-08-10 creatinine 1.90 mg/dL', '2026-08-10 cystatin_c 1.60 mg/L'],
  }],
  ['records that are not Observations are counted as not lab results and nothing else', [
    file('Patient.json', patient), file('Condition.json', condition), file('Immunization.json', immunization),
    file('Bundle-no-labs.json', bundle(patient, condition)),
    file('Nested.json', bundle({ resourceType: 'Bundle', type: 'collection', entry: [{ resource: observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-08-10') }] })),
    file('NoType.json', { id: 'x', status: 'final' }), file('Array.json', [1, 2, 3]), file('Number.json', 42),
  ], opts(), { counts: { files: 8, read: 8, notLab: 9 }, rows: [] }],
  ['an Observation that is not a lab test (a blood pressure, an unknown LOINC code) is skipped and counted', [
    file('bp.json', bp),
    file('cmp.json', observation('24323-8', 1, 'x', 'x', '2026-09-01')), // a comprehensive metabolic panel: a group, not one test
    file('urine-k.json', observation('2828-2', 40, 'mmol/L', 'mmol/L', '2026-09-01')), // potassium in URINE
    file('urine-cr.json', observation('2161-8', 120, 'mg/dL', 'mg/dL', '2026-09-01')), // creatinine in URINE
    file('blood-gas-k.json', observation('6298-4', 6.1, 'mmol/L', 'mmol/L', '2026-09-01')), // whole blood: not read
    file('mdrd.json', observation('48642-3', 60, 'mL/min/1.73m2', 'mL/min/{1.73_m2}', '2026-09-01')), // race-specific MDRD: not read
    file('glucose.json', observation('2345-7', 99, 'mg/dL', 'mg/dL', '2026-09-01')),
    file('same-number-other-system.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', '2026-09-01', { code: { coding: [{ system: 'http://snomed.info/sct', code: '2823-3' }] } })),
    file('no-code.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', '2026-09-01', { code: { text: 'Potassium' } })),
    file('two-tests.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', '2026-09-01', { code: { coding: [{ system: LOINC, code: '2823-3' }, { system: LOINC, code: '2160-0' }] } })),
  ], opts(), { counts: { files: 10, read: 10, observations: 10, unknownCode: 10 }, rows: [] }],
  ['only final, amended and corrected results are read', [
    file('final.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-01')),
    file('amended.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', '2026-09-02', { status: 'amended' })),
    file('corrected.json', observation('2823-3', 4.7, 'mmol/L', 'mmol/L', '2026-09-03', { status: 'corrected' })),
    file('preliminary.json', observation('2823-3', 4.8, 'mmol/L', 'mmol/L', '2026-09-04', { status: 'preliminary' })),
    file('registered.json', observation('2823-3', 4.9, 'mmol/L', 'mmol/L', '2026-09-05', { status: 'registered' })),
    file('cancelled.json', observation('2823-3', 5.0, 'mmol/L', 'mmol/L', '2026-09-06', { status: 'cancelled' })),
    file('error.json', observation('2823-3', 5.1, 'mmol/L', 'mmol/L', '2026-09-07', { status: 'entered-in-error' })),
    file('unknown.json', observation('2823-3', 5.2, 'mmol/L', 'mmol/L', '2026-09-08', { status: 'unknown' })),
    file('no-status.json', observation('2823-3', 5.3, 'mmol/L', 'mmol/L', '2026-09-09', { status: undefined })),
    file('odd-status.json', observation('2823-3', 5.4, 'mmol/L', 'mmol/L', '2026-09-10', { status: ['final'] })),
  ], opts(), {
    counts: { files: 10, read: 10, observations: 10, wrongStatus: 7, found: 3 },
    rows: ['2026-09-03 potassium 4.7 mmol/L', '2026-09-02 potassium 4.6 mmol/L', '2026-09-01 potassium 4.5 mmol/L'],
  }],
  // ---- the value and its unit ------------------------------------------------------------------------------------------------
  ['a unit the app does not know for that test is refused and counted, never guessed', [
    file('k-mgdl.json', observation('2823-3', 18, 'mg/dL', 'mg/dL', '2026-09-01')),
    file('cr-mgl.json', observation('2160-0', 12, 'mg/L', 'mg/L', '2026-09-01')),
    file('no-unit.json', observation('2823-3', 4.5, undefined, undefined, '2026-09-01', { valueQuantity: { value: 4.5 } })),
    file('empty-unit.json', observation('2823-3', 4.5, '', '', '2026-09-02')),
    file('egfr-no-bsa.json', observation('98979-8', 60, 'mL/min', 'mL/min', '2026-09-01')),
    file('weird.json', observation('2823-3', 4.5, 'x'.repeat(200), 'x'.repeat(200), '2026-09-01')),
    file('conflict.json', observation('2160-0', 150, 'µmol/L', 'mg/dL', '2026-09-03')),
    file('other-system.json', observation('2823-3', 4.5, 'mmol/L', 'mg/dL', '2026-09-04', { valueQuantity: { value: 4.5, unit: 'mmol/L', system: 'http://example.org/units', code: 'mg/dL' } })),
  ], opts(), {
    counts: { files: 8, read: 8, observations: 8, badUnit: 7, found: 1 },
    rows: ['2026-09-04 potassium 4.5 mmol/L'],
    problemsInclude: ['the app cannot convert the unit “mg/dL” for Potassium', 'the app cannot convert the unit “mg/L” for Creatinine (blood)', 'no unit is given',
      'the app cannot convert the unit “mL/min” for eGFR (reported by the lab)', 'the unit is written two ways (“mg/dL” and “µmol/L”)', 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx…'],
  }],
  ['a value that is not a single number is listed, never turned into one', [
    file('lt.json', observation('2160-0', 0.5, 'mg/dL', 'mg/dL', '2026-09-01', { valueQuantity: { value: 0.5, comparator: '<', unit: 'mg/dL', system: UCUM, code: 'mg/dL' } })),
    file('gt.json', observation('98979-8', 90, 'mL/min/1.73m2', 'mL/min/{1.73_m2}', '2026-09-02', { valueQuantity: { value: 90, comparator: '>=', unit: 'mL/min/1.73m2', system: UCUM, code: 'mL/min/{1.73_m2}' } })),
    file('string.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-03', { valueQuantity: undefined, valueString: 'Hemolyzed' })),
    file('string-number.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-03', { valueQuantity: { value: '4.5', unit: 'mmol/L' } })),
    file('null.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-04', { valueQuantity: { value: null, unit: 'mmol/L' } })),
    file('absent.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-04', { valueQuantity: undefined, dataAbsentReason: { text: 'not performed' } })),
    file('equals.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-05', { valueQuantity: { value: 4.4, comparator: '=', unit: 'mmol/L', system: UCUM, code: 'mmol/L' } })),
  ], opts(), {
    counts: { files: 7, read: 7, observations: 7, noValue: 4, notExact: 2, found: 1 },
    rows: ['2026-09-05 potassium 4.4 mmol/L'],
    problemsInclude: ['“<0.5” is not a single number', '“>=90” is not a single number', 'the result is not a single number'],
  }],
  ['the plausible-range check is the one the CSV import uses', [
    file('k15.json', observation('2823-3', 15, 'mmol/L', 'mmol/L', '2026-09-01')),
    file('cr150.json', observation('2160-0', 150, 'mg/dL', 'mg/dL', '2026-09-01')),
    file('negative.json', observation('2823-3', -4, 'mmol/L', 'mmol/L', '2026-09-01')),
    file('zero.json', observation('2823-3', 0, 'mmol/L', 'mmol/L', '2026-09-02')),
    file('a1c-low.json', observation('4548-4', 1.2, '%', '%', '2026-09-02')),
    file('fine.json', observation('2823-3', 6.1, 'mmol/L', 'mmol/L', '2026-09-03')),
  ], opts(), {
    counts: { files: 6, read: 6, observations: 6, refused: 5, found: 1 },
    rows: ['2026-09-03 potassium 6.1 mmol/L'],
    problemsInclude: ['Potassium 15.0 mmol/L is outside the plausible range 1.5–9 mmol/L', 'Creatinine (blood) 150.00 mg/dL is outside the plausible range 0.1–25 mg/dL', 'Potassium must be a non-negative number'],
  }],
  // ---- the day ---------------------------------------------------------------------------------------------------------------
  ['the day: effectiveDateTime, then effectiveInstant, effectivePeriod.start and issued', [
    file('a.json', observation('2823-3', 4.1, 'mmol/L', 'mmol/L', '2026-09-01')),
    file('b.json', observation('2823-3', 4.2, 'mmol/L', 'mmol/L', undefined, { effectiveInstant: '2026-09-02T10:00:00Z' })),
    file('c.json', observation('2823-3', 4.3, 'mmol/L', 'mmol/L', undefined, { effectivePeriod: { start: '2026-09-03T08:15:00-05:00', end: '2026-09-03T08:20:00-05:00' } })),
    file('d.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', undefined, { issued: '2026-09-04T12:00:00Z' })),
    file('e.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-05', { issued: '2026-09-09T12:00:00Z' })),
    file('f.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', undefined)),
  ], opts(), {
    counts: { files: 6, read: 6, observations: 6, badDate: 1, found: 5 },
    rows: ['2026-09-05 potassium 4.5 mmol/L', '2026-09-04 potassium 4.4 mmol/L', '2026-09-03 potassium 4.3 mmol/L', '2026-09-02 potassium 4.2 mmol/L', '2026-09-01 potassium 4.1 mmol/L'],
    problemsInclude: ['no date'],
  }],
  ['an instant with a time zone is the calendar day on this device; a day alone or a time without a zone is used as written', [
    file('evening-utc.json', observation('2823-3', 4.1, 'mmol/L', 'mmol/L', '2026-09-02T03:30:00Z')),
    file('evening-offset.json', observation('2823-3', 4.2, 'mmol/L', 'mmol/L', '2026-09-03T22:30:00-07:00')),
    file('day-only.json', observation('2823-3', 4.3, 'mmol/L', 'mmol/L', '2026-09-04')),
    file('no-zone.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-05T23:59:00')),
    file('fraction.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-06T00:10:00.123+02:00')),
  ], opts({ tzOffsetMinutes: -420 }), { // a device seven hours behind UTC (summer time on the US west coast)
    counts: { files: 5, read: 5, observations: 5, found: 5 },
    rows: ['2026-09-05 potassium 4.4 mmol/L', '2026-09-05 potassium 4.5 mmol/L', '2026-09-04 potassium 4.3 mmol/L', '2026-09-03 potassium 4.2 mmol/L', '2026-09-01 potassium 4.1 mmol/L'],
  }],
  ['a device ahead of UTC sees the next day', [
    file('evening-utc.json', observation('2823-3', 4.1, 'mmol/L', 'mmol/L', '2026-09-02T20:30:00Z')),
  ], opts({ tzOffsetMinutes: 600 }), { counts: { files: 1, read: 1, observations: 1, found: 1 }, rows: ['2026-09-03 potassium 4.1 mmol/L'] }],
  ['future days, days before 1900 and days that are not days are refused', [
    file('today.json', observation('2823-3', 4.1, 'mmol/L', 'mmol/L', '2026-10-15')),
    file('tomorrow.json', observation('2823-3', 4.2, 'mmol/L', 'mmol/L', '2026-10-16')),
    file('day-after.json', observation('2823-3', 4.3, 'mmol/L', 'mmol/L', '2026-10-17')),
    file('far.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2099-01-01T00:00:00Z')),
    file('old.json', observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '1899-12-31')),
    file('month.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', '2026-09')),
    file('year.json', observation('2823-3', 4.7, 'mmol/L', 'mmol/L', '2026')),
    file('feb30.json', observation('2823-3', 4.8, 'mmol/L', 'mmol/L', '2026-02-30')),
    file('words.json', observation('2823-3', 4.9, 'mmol/L', 'mmol/L', 'last Tuesday')),
    file('hour25.json', observation('2823-3', 5.0, 'mmol/L', 'mmol/L', '2026-09-01T25:00:00Z')),
  ], opts(), {
    counts: { files: 10, read: 10, observations: 10, badDate: 8, found: 2 },
    rows: ['2026-10-16 potassium 4.2 mmol/L', '2026-10-15 potassium 4.1 mmol/L'],
    problemsInclude: ['in the future', 'is before 1900', 'has no day', 'is not a real date', 'is not a date the app can read', 'is not a real time'],
  }],
  ['without a today the future is not checked (the page always gives one)', [
    file('far.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2099-01-01')),
  ], { tzOffsetMinutes: 0 }, { counts: { files: 1, read: 1, observations: 1, found: 1 }, rows: ['2099-01-01 potassium 4.4 mmol/L'] }],
  // ---- repeats and what is already saved -------------------------------------------------------------------------------------
  ['the same result in a file and in a Bundle, or under two codes, is one row', [
    file('one.json', observation('2160-0', 1.7, 'mg/dL', 'mg/dL', '2026-09-01')),
    file('bundle.json', bundle(observation('2160-0', 1.7, 'mg/dL', 'mg/dL', '2026-09-01'), observation('14682-9', 150.3, 'umol/L', 'umol/L', '2026-09-01'))),
    file('other-day.json', observation('2160-0', 1.7, 'mg/dL', 'mg/dL', '2026-09-02')),
  ], opts(), { counts: { files: 3, read: 3, observations: 4, duplicates: 2, found: 2 }, rows: ['2026-09-02 creatinine 1.70 mg/dL', '2026-09-01 creatinine 1.70 mg/dL'] }],
  ['a result the person already has is marked saved', [
    file('k.json', observation('2823-3', 4.6, 'mmol/L', 'mmol/L', '2026-09-01')),
    file('cr.json', observation('2160-0', 1.7, 'mg/dL', 'mg/dL', '2026-09-01')),
  ], opts({ existing: [{ analyte: 'potassium', taken_on: '2026-09-01', value: 4.6 }, { analyte: 'creatinine', taken_on: '2026-09-02', value: 1.7 }, { analyte: 'nonsense', taken_on: '2026-09-01', value: 1 }] }), {
    counts: { files: 2, read: 2, observations: 2, found: 2, saved: 1 },
    rows: ['2026-09-01 potassium 4.6 mmol/L', '2026-09-01 creatinine 1.70 mg/dL'], savedRows: [true, false],
  }],
  // ---- bad files -------------------------------------------------------------------------------------------------------------
  ['files that are not JSON, empty, truncated or a byte order mark first', [
    { name: 'notes.json', text: 'Potassium 4.5 on Sept 1' },
    { name: 'empty.json', text: '' },
    { name: 'cut.json', text: '{"resourceType": "Observation", "status": "final"' },
    { name: 'html.json', text: '<html><script>alert(1)</script></html>' },
    { name: 'bom.json', text: `﻿${JSON.stringify(observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-01'))}` },
    { name: 'null.json', text: 'null' },
  ], opts(), { counts: { files: 6, read: 2, notJson: 4, observations: 1, notLab: 1, found: 1 }, rows: ['2026-09-01 potassium 4.4 mmol/L'] }],
  ['a file the page could not read, and a file over 1 MB that is never read', [
    { name: 'unreadable.json', unreadable: true },
    { name: 'huge.json', size: 2000000 },
    { name: 'just-over.json', size: 1048577, text: JSON.stringify(observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-01')) },
    { name: 'exactly-1mb.json', size: 1048576, text: JSON.stringify(observation('2823-3', 4.5, 'mmol/L', 'mmol/L', '2026-09-02')) },
    { name: 'no-text.json', size: 10 },
  ], opts(), { counts: { files: 5, read: 1, tooBig: 2, unreadable: 2, observations: 1, found: 1 }, rows: ['2026-09-02 potassium 4.5 mmol/L'] }],
  ['a file whose text is over 1 MB is skipped even when the page gave no size', [
    { name: 'long.json', repeat: { prefix: '[', item: '1', separator: ',', count: 600000, suffix: ']' } },
  ], opts(), { counts: { files: 1, tooBig: 1 }, rows: [] }],
  ['a file nested too deeply or with too many values is skipped, not walked', [
    { name: 'deep.json', text: `${'['.repeat(41)}${']'.repeat(41)}` },
    { name: 'deep-ok.json', text: `${'['.repeat(40)}${']'.repeat(40)}` },
    { name: 'wide.json', repeat: { prefix: '[', item: '1', separator: ',', count: 300001, suffix: ']' } },
    { name: 'deep-observation.json', text: JSON.stringify(observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-01', { extension: JSON.parse(`${'{"a":'.repeat(45)}1${'}'.repeat(45)}`) })) },
  ], opts(), { counts: { files: 4, read: 1, tooComplex: 3, notLab: 1 }, rows: [] }],
  ['hostile text in a file is only ever quoted, shortened, and never an element', [
    file('x.json', observation('2823-3', 4.4, '<img src=x onerror=alert(1)>', '<b>mg/dL</b>', '2026-09-01')),
    file('y.json', observation('2160-0', 4.4, 'mg/dL', 'mg/dL', '<script>alert(1)</script>')),
    file('z.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-01', { valueQuantity: { value: 4.4, comparator: '‮<', unit: 'mmol/L' } })),
  ], opts(), { counts: { files: 3, read: 3, observations: 3, badUnit: 1, badDate: 1, notExact: 1 }, rows: [] }],
  ['the identity in a file is never read: a name, an id and a provider appear in no answer', [
    file('who.json', observation('2823-3', 4.4, 'mmol/L', 'mmol/L', '2026-09-01', { subject: { display: 'Sam Example', reference: 'Patient/example-0001' }, performer: [{ display: 'Dr Example' }], note: [{ text: 'Sam Example called back' }] })),
  ], opts(), { counts: { files: 1, read: 1, observations: 1, found: 1 }, rows: ['2026-09-01 potassium 4.4 mmol/L'] }],
  ['a pick of many kinds of record, as the Health export has them', [
    ...everyCode.slice(0, 3), file('Patient.json', patient), file('Condition.json', condition), file('Immunization.json', immunization),
    file('bp.json', bp), { name: 'readme.json', text: 'not json' },
    file('prelim.json', observation('2823-3', 5.9, 'mmol/L', 'mmol/L', '2026-09-20', { status: 'preliminary' })),
    file('k-mgdl.json', observation('2823-3', 18, 'mg/dL', 'mg/dL', '2026-09-20')),
  ], opts(), { counts: { files: 10, read: 9, notJson: 1, observations: 6, notLab: 3, unknownCode: 1, wrongStatus: 1, badUnit: 1, found: 3 }, rowCount: 3 }],
  ['no files', [], opts(), { problem: 'No files were chosen.', counts: {}, rows: [] }],
];

// The "pick" limits that need their own list of files.
const manyFiles = Array.from({ length: F.MAX_FILES + 1 }, (_, i) => ({ name: `Observation-${i}.json`, text: '{}' }));
CASES.push(['more than 2,000 files are refused as a pick, before any is read', manyFiles, opts(), { problem: 'You chose 2,001 files; the app reads up to 2,000 at a time. Choose fewer files, for example only the Observation files.', counts: { files: 2001 }, rows: [] }]);

// ---- build the file and check each `want` ----------------------------------------------------------------------------------------
const expandFile = (f) => {
  if (!f.repeat) return f;
  const { prefix, item, separator, count, suffix } = f.repeat;
  return { name: f.name, text: prefix + Array.from({ length: count }, () => item).join(separator) + suffix };
};
const rowText = (r) => `${r.taken_on} ${r.analyte} ${r.display}`;
const problems = [];
const cases = CASES.map(([name, files, options, want]) => {
  const expected = plain(F.analyse(files.map(expandFile), options));
  // The hand-written expectation: every count that is not zero is listed, every other count is zero.
  const zero = plain(F.start({}).counts);
  const wantCounts = { ...zero, ...want.counts };
  if (!isDeepStrictEqual(expected.counts, wantCounts)) problems.push(`${name}: counts\n   got  ${JSON.stringify(expected.counts)}\n   want ${JSON.stringify(wantCounts)}`);
  const rows = expected.results.map(rowText);
  if (want.rows && !isDeepStrictEqual(rows, want.rows)) problems.push(`${name}: rows\n   got  ${JSON.stringify(rows)}\n   want ${JSON.stringify(want.rows)}`);
  if (want.rowCount !== undefined && rows.length !== want.rowCount) problems.push(`${name}: ${rows.length} rows, want ${want.rowCount}`);
  if (want.firstRows && !isDeepStrictEqual(rows.slice(0, want.firstRows.length), want.firstRows)) problems.push(`${name}: first rows\n   got  ${JSON.stringify(rows.slice(0, want.firstRows.length))}\n   want ${JSON.stringify(want.firstRows)}`);
  if (want.savedRows && !isDeepStrictEqual(expected.results.map((r) => r.saved), want.savedRows)) problems.push(`${name}: saved flags ${JSON.stringify(expected.results.map((r) => r.saved))}`);
  for (const part of want.problemsInclude || []) {
    if (!expected.problems.some((p) => p.problem.includes(part))) problems.push(`${name}: no refusal says ${JSON.stringify(part)}: ${JSON.stringify(expected.problems.map((p) => p.problem))}`);
  }
  if ((want.problem || null) !== expected.problem) problems.push(`${name}: problem ${JSON.stringify(expected.problem)}, want ${JSON.stringify(want.problem || null)}`);
  if (JSON.stringify(expected).includes('Sam Example') || JSON.stringify(expected).includes('Dr Example') || JSON.stringify(expected).includes('example-0001')) problems.push(`${name}: a name or id from a file is in the answer`);
  // The files are stored as written, except that a repeated text is stored as its recipe (and 2,001 files as one recipe).
  const stored = files.length > F.MAX_FILES ? { repeat_file: { name: 'Observation-{n}.json', text: '{}', count: files.length } } : files.map((f) => (f.repeat ? { name: f.name, repeat: f.repeat } : f));
  return { name, files: stored, options, expected };
});
if (problems.length) {
  console.error(problems.join('\n'));
  process.exit(1);
}

const doc = {
  about: 'js/engine/fhir_labs.js answers (Lab results → Import from Apple Health, FHIR clinical records read on the device); generated by tests/js/gen_fhir_labs_vectors.mjs from hand-written resources and hand-written expectations (the script stops if the module disagrees), replayed by tests/js/run_vectors.mjs, cross-checked against app/units.py by tests/test_fhir_labs.py',
  limits: {
    max_files: F.MAX_FILES, max_file_bytes: F.MAX_FILE_BYTES, max_depth: F.MAX_DEPTH, max_nodes: F.MAX_NODES, max_bundle_entries: F.MAX_BUNDLE_ENTRIES,
    max_records: F.MAX_RECORDS, max_collect: F.MAX_COLLECT, max_results: F.MAX_RESULTS, max_problems: F.MAX_PROBLEMS,
  },
  loinc: F.LOINC_LIST.map(([analyte, code, name, ucum]) => ({ code, analyte, name, ucum, unit: F.mapUnit(analyte, ucum), url: F.loincUrl(code) })),
  unit_aliases: plain(F.UNIT_ALIASES),
  cases,
};
writeFileSync(OUT, `${JSON.stringify(doc, null, 1)}\n`);
console.log(`wrote ${OUT}: ${cases.length} cases, ${doc.loinc.length} LOINC codes`);
