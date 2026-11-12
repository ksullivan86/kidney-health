// The lines of a PDF page's own text (app/static/js/engine/pdf_text.js, KH.pdfText; design note 36 §4.1, §4.2). Runs the real file in
// a fresh context: lines rebuilt from pdf.js text items in any order, words joined by their gaps, the "has text" test, the lines that
// may say who the person is, and the page limit. Run with `node --test tests/js/pdf_text.test.mjs`.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = readFileSync(new URL('../../app/static/js/engine/pdf_text.js', import.meta.url), 'utf8');

function load() {
  const ctx = { KH: {} };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  return ctx.KH.pdfText;
}
const T = load();

// One pdf.js text item: `str` at (x, y) in points, `size` high, as wide as a Helvetica-ish 0.5 em a character.
function item(str, x, y, size = 10, width = null) {
  return { str, transform: [size, 0, 0, size, x, y], width: width === null ? str.length * size * 0.5 : width, height: size, hasEOL: false };
}
const plain = (value) => JSON.parse(JSON.stringify(value));

// A results table as a portal prints it: label, value, unit and range in columns, each its own item.
const TABLE = [
  item('Harbor Valley Clinical Laboratory', 72, 740, 14),
  item('Collected:', 72, 712), item('2026-10-07', 130, 712),
  item('Potassium', 72, 690), item('5.4', 220, 690), item('mmol/L', 260, 690), item('3.5-5.1', 340, 690),
  item('Creatinine', 72, 676), item('1.62', 220, 676), item('mg/dL', 260, 676),
  item('eGFR', 72, 662), item('38', 220, 662), item('mL/min/1.73m2', 260, 662),
];
const LINES = [
  'Harbor Valley Clinical Laboratory',
  'Collected: 2026-10-07',
  'Potassium 5.4 mmol/L 3.5-5.1',
  'Creatinine 1.62 mg/dL',
  'eGFR 38 mL/min/1.73m2',
];

test('a table becomes one line a row, top to bottom and left to right', () => {
  assert.deepEqual(plain(T.buildLines(TABLE)), LINES);
});

test('the content stream order does not matter', () => {
  const shuffled = [...TABLE].reverse();
  const interleaved = TABLE.filter((_, i) => i % 2).concat(TABLE.filter((_, i) => !(i % 2)));
  assert.deepEqual(plain(T.buildLines(shuffled)), LINES);
  assert.deepEqual(plain(T.buildLines(interleaved)), LINES);
});

test('items a little above or below the line stay on it; a new row starts a new line', () => {
  const lines = T.buildLines([item('Phosphorus', 72, 700), item('4.1', 220, 701.5), item('mg/dL', 260, 699.2), item('Sodium', 72, 686)]);
  assert.deepEqual(plain(lines), ['Phosphorus 4.1 mg/dL', 'Sodium']);
});

test('pieces of one word are joined without a space, words with a gap get one', () => {
  // "Potas" + "sium" touch; "5" + ".4" touch; a gap before the unit
  const lines = T.buildLines([item('Potas', 72, 700, 10, 25), item('sium', 97, 700, 10, 20), item('5', 200, 700, 10, 5), item('.4', 205, 700, 10, 7),
    item('mmol/L', 230, 700)]);
  assert.deepEqual(plain(lines), ['Potassium 5.4 mmol/L']);
});

test('empty and space-only items, odd values and spaces inside items are handled', () => {
  const lines = T.buildLines([item('  ', 10, 700), item('', 20, 700), { str: 'A1c   7.2  %', transform: [10, 0, 0, 10, 72, 650], width: 60, height: 10 },
    null, { str: 42 }, { str: 'No transform' }]);
  assert.deepEqual(plain(lines), ['A1c 7.2 %', 'No transform']);
  assert.deepEqual(plain(T.buildLines(null)), []);
  assert.deepEqual(plain(T.buildLines([])), []);
});

test('the same items always give the same lines (ties keep the original order)', () => {
  const same = [item('B', 100, 700), item('A', 100, 700)]; // two items at the same place
  assert.deepEqual(plain(T.buildLines(same)), ['BA']);
  assert.deepEqual(plain(T.buildLines(same)), plain(T.buildLines(same.map((x) => ({ ...x })))));
});

test('at most 400 lines a page', () => {
  const many = Array.from({ length: 450 }, (_, i) => item(`Line ${i}`, 72, 10000 - i * 20));
  const lines = T.buildLines(many);
  assert.equal(lines.length, T.LIMITS.MAX_LINES);
  assert.equal(lines[0], 'Line 0');
});

test('a page has text with enough letters and digits on at least two lines with a number', () => {
  assert.equal(T.hasText(LINES), true);
  assert.equal(T.hasText([]), false);
  assert.equal(T.hasText(['Scanned by the clinic']), false); // a header over a picture
  assert.equal(T.hasText(['Potassium 5.4 mmol/L reference range three point five to five']), false); // one numbered line
  assert.equal(T.hasText(['1', '2']), false); // too little text
});

test('lines that may say who the person is are left out, results stay', () => {
  const lines = [
    'Patient: Jane Example', 'Name: EXAMPLE, JANE', 'DOB: 01/02/1961', 'D.O.B. 01/02/1961', 'Date of Birth 1961-01-02',
    'MRN 00012345', 'Medical Record No. 555', 'Account # 991', 'Acct 77', 'Member ID: XJ12', 'ID # 4471', 'SSN ***-**-1234',
    'Address: 1 Example Street', 'Phone: 555-0100', 'Fax 555-0101', 'Insurance: Example Health', 'Guarantor: Self',
    'reports@example.org', 'Test Name Result Units Reference',
    'Potassium 5.4 mmol/L 3.5-5.1', 'Collected: 2026-10-07', 'eGFR 38 mL/min/1.73m2', 'Hemoglobin A1c 7.2 %', 'Albumin 4.0 g/dL',
    'Microalbumin/Creatinine Ratio 1,250 mg/g',
  ];
  const { lines: kept, removed } = T.stripIdentity(lines);
  assert.deepEqual(plain(kept), ['Potassium 5.4 mmol/L 3.5-5.1', 'Collected: 2026-10-07', 'eGFR 38 mL/min/1.73m2', 'Hemoglobin A1c 7.2 %',
    'Albumin 4.0 g/dL', 'Microalbumin/Creatinine Ratio 1,250 mg/g']);
  assert.equal(removed, lines.length - kept.length);
});

test('pageText puts it together and flags a page that is too long to send', () => {
  const page = T.pageText([item('Patient: Jane Example', 72, 760), ...TABLE]);
  assert.deepEqual(plain(page.lines), LINES);
  assert.equal(page.removed, 1);
  assert.equal(page.text, LINES.join('\n'));
  assert.equal(page.chars, page.text.length);
  assert.equal(page.hasText, true);
  assert.equal(page.tooLong, false);
  const long = T.pageText(Array.from({ length: 300 }, (_, i) => item(`Potassium 5.4 mmol/L ${'x'.repeat(60)} ${i}`, 72, 10000 - i * 20)));
  assert.equal(long.tooLong, true);
  const scanned = T.pageText([]);
  assert.equal(scanned.hasText, false);
  assert.equal(scanned.text, '');
});
