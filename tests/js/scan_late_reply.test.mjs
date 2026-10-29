// Runs the real js/scan.js on a fake page: a barcode lookup or an AI label reading that answers late must not act on a sheet the
// person has already left, or overwrite what they typed since.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/scan.js', import.meta.url), 'utf8');

function setup({ slowJpeg = false } = {}) {
  const page = makePage();
  const { $ } = page;
  const lookups = [];
  const uploads = [];
  const jpegs = [];
  const opened = [];
  const toasts = [];
  const KH = {
    h: page.h, s: page.h, $, $$: page.$$, clear: page.clear, state: {}, flags: { MOCK: false, PREVIEW: false },
    request: (method, path, body) => { const d = deferred(); lookups.push({ method, path, body, ...d }); return d.promise; },
    toast: (msg) => toasts.push(msg), toastError: (e) => toasts.push(`error: ${e.message}`),
    sheets: { setup() {}, onSubmit() {}, open(dlg) { dlg.open = true; } },
    ui: {}, rules: { NUT: { potassium_mg: {}, sodium_mg: {}, fluid_ml: {} } },
    forms: { clearFieldErrors() {}, fieldError() {} },
    off: { safeHttpsUrl: () => null },
    views: { add: { openEntrySheet: (mode, opts) => opened.push(opts.food.name), openQuick() {} } },
    ai: {
      status: async () => ({ enabled: true, available: true, features: { label: true }, provider: { label: 'Test AI' } }),
      prepareJpeg: (file) => {
        if (!slowJpeg) return Promise.resolve(`jpeg of ${file.name}`);
        const d = deferred(); jpegs.push({ file, ...d }); return d.promise;
      },
      withConsent: (purpose, run) => run(),
      uploadPhoto: (kind, blob) => { const d = deferred(); uploads.push({ blob, ...d }); return d.promise; },
      showSent: async () => {},
    },
  };
  const window = { KH, isSecureContext: false, addEventListener() {} };
  const context = vm.createContext({ window, document: page.document, navigator: {}, console, setTimeout, clearTimeout, Event: page.Event,
    URL: { createObjectURL: (f) => `blob:${f.name}`, revokeObjectURL() {} } });
  vm.runInContext(source, context, { filename: 'scan.js' });
  const quickDlg = $('#sheet-quick');
  const choosePhoto = async (name) => { $('#q-photo').files = [{ name }]; $('#q-photo').fire('change'); await settle(); };
  const openQuick = () => { KH.scan.quickOpened(); quickDlg.open = true; $('#q-name').value = ''; $('#qn-potassium_mg').value = ''; };
  const readLabel = async () => { page.button($('#q-photo-ai'), 'Read the label for me (AI)').click(); await settle(); };
  const answer = (name, potassium) => ({ status: 'ok', draft: { name, serving_desc: '1 cup', serving_g: 240, nutrients: { potassium_mg: potassium } },
    from_photo: ['name', 'potassium_mg'], estimated: [], checks: [], needs: [] });
  return { page, $, KH, lookups, uploads, jpegs, opened, toasts, quickDlg, choosePhoto, openQuick, readLabel, answer, scanDlg: $('#sheet-scan') };
}
const food = (name) => ({ food: { id: 1, name, nutrients: {} } });

test('a barcode answer that comes after the Scan sheet was closed opens nothing', async () => {
  const s = setup();
  s.KH.scan.open({});
  const pending = s.KH.scan.lookup('0012345678905', 'ean_13');
  s.scanDlg.close(); // the person gave up waiting
  s.lookups[0].resolve(food('Old product'));
  await pending;
  assert.deepEqual(s.opened, []);
});

test('a slow first lookup cannot replace the answer to a newer one', async () => {
  const s = setup();
  s.KH.scan.open({});
  const first = s.KH.scan.lookup('0012345678905', 'ean_13');
  const second = s.KH.scan.lookup('0098765432109', 'ean_13', { typed: true });
  s.lookups[0].reject(Object.assign(new Error('The food databases did not answer'), { status: 502, data: {} }));
  await first;
  assert.doesNotMatch(s.page.text(s.$('#scan-result')), /did not answer/);
  s.lookups[1].resolve(food('New product'));
  await second;
  assert.deepEqual(s.opened, ['New product']);
});

test('a lookup that answers while the sheet is open still opens the entry sheet', async () => {
  const s = setup();
  s.KH.scan.open({});
  const pending = s.KH.scan.lookup('0012345678905', 'ean_13');
  s.lookups[0].resolve(food('Apple juice'));
  await pending;
  assert.deepEqual(s.opened, ['Apple juice']);
});

test('an AI label reading that arrives after the photo was removed does not overwrite typed values', async () => {
  const s = setup();
  s.openQuick();
  await s.choosePhoto('label-a.jpg');
  await s.readLabel();
  assert.equal(s.uploads.length, 1);
  s.$('#q-photo-remove').click();
  s.$('#q-name').value = 'Typed by hand';
  s.$('#qn-potassium_mg').value = '120';
  s.uploads[0].resolve(s.answer('Photo A product', 999));
  await settle();
  assert.equal(s.$('#q-name').value, 'Typed by hand');
  assert.equal(s.$('#qn-potassium_mg').value, '120');
  assert.ok(!s.toasts.some((t) => /filled from your photo/.test(t)));
});

test('an AI label reading from a closed Quick add does not fill the next Quick add', async () => {
  const s = setup();
  s.openQuick();
  await s.choosePhoto('label-a.jpg');
  await s.readLabel();
  s.quickDlg.close();
  s.openQuick();
  await s.choosePhoto('label-b.jpg');
  s.uploads[0].resolve(s.answer('Photo A product', 999));
  await settle();
  assert.equal(s.$('#q-name').value, '');
  assert.equal(s.$('#qn-potassium_mg').value, '');
});

test('the current photo is the one sent, even when a new photo is chosen while the old one is being prepared', async () => {
  const s = setup({ slowJpeg: true });
  s.openQuick();
  await s.choosePhoto('label-a.jpg');
  await s.readLabel();
  await s.choosePhoto('label-b.jpg');
  s.jpegs[0].resolve('jpeg of label-a.jpg');
  await settle();
  assert.equal(s.uploads.length, 0, 'the old photo is not sent once a new one was chosen');
  await s.readLabel();
  s.jpegs[1].resolve('jpeg of label-b.jpg');
  await settle();
  assert.deepEqual(s.uploads.map((u) => u.blob), ['jpeg of label-b.jpg']);
  s.uploads[0].resolve(s.answer('Photo B product', 300));
  await settle();
  assert.equal(s.$('#q-name').value, 'Photo B product');
  assert.equal(s.$('#qn-potassium_mg').value, '300');
});

test('a reading of the current photo still fills the form', async () => {
  const s = setup();
  s.openQuick();
  await s.choosePhoto('label-a.jpg');
  await s.readLabel();
  s.uploads[0].resolve(s.answer('Photo A product', 250));
  await settle();
  assert.equal(s.$('#q-name').value, 'Photo A product');
  assert.equal(s.$('#qn-potassium_mg').value, '250');
});
