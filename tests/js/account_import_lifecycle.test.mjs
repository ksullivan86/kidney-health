import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/settings.js', import.meta.url), 'utf8');
const start = source.indexOf('  const IMPORT_MAX_BYTES');
const end = source.indexOf('  const ACTION_LABEL = {', start);
assert.ok(start > 0 && end > start);
const reply = { can_import: true, file: { records: { log_entries: 1, profile: 1 } }, counts: { log_entries: 1 }, skipped: { total: 0 }, not_imported: [] };

function setup() {
  const page = makePage(), calls = [], toasts = [];
  const state = {};
  const context = vm.createContext({ ...page, MOCK: false, state, AbortController,
    A: { importData(body, options) { const d = deferred(); calls.push({ body, options, ...d }); return d.promise; } },
    action(label, cls, fn, attrs) {
      const btn = page.h('button', { type: 'button', class: cls, ...attrs }, label);
      btn.addEventListener('click', async () => {
        if (btn.disabled) return; btn.disabled = true;
        try { await fn(btn); } catch (e) { if (!e.handled) toasts.push(e.message); } finally { btn.disabled = false; }
      }); return btn;
    },
    KH: { invalidateSharedCaches() {}, loadProfile: async () => {} }, toast: (m) => toasts.push(m),
    subtitle: (t) => page.h('h3', {}, t), statusMsg: (id) => page.h('p', { id }), note: (_kind, ...kids) => page.h('div', {}, kids),
    fmtBytes: String, fmtDate: String,
  });
  vm.runInContext(source.slice(start, end) + '\nglobalThis.block = importBlock();', context);
  page.root.append(context.block);
  const pick = async (name = 'first.json') => {
    const doc = { format: 'kidney-health-export', version: 1, chosen_file: name };
    page.$('#set-import-file').files = [{ name, size: 50, text: async () => JSON.stringify(doc) }];
    page.$('#set-import-file').fire('change'); await settle();
  };
  const ready = async () => { await pick(); calls.at(-1).resolve(reply); await settle(); };
  return { ...page, calls, toasts, pick, ready, last: () => calls.at(-1) };
}

test('the checked file and choices cannot change or be cancelled while an import writes', async () => {
  const s = setup(); await s.ready(); s.$('#set-import-go').click(); await settle();
  assert.equal(s.last().options.dry_run, false);
  for (const id of ['file', 'merge', 'profile', 'cancel']) assert.equal(s.$(`#set-import-${id}`).disabled, true, id);
  s.$('#set-import-cancel').click(); assert.doesNotMatch(s.text(s.$('#set-import-msg')), /Nothing was imported/);
  assert.equal(s.last().body.chosen_file, 'first.json');
  s.last().resolve({ ...reply, imported: true }); await settle();
  assert.equal(s.$('#set-import-file').disabled, false); assert.match(s.text(s.$('#set-import-msg')), /Imported/);
});
test('an old Import button is disabled while changed choices are being checked', async () => {
  const s = setup(); await s.ready(); const old = s.$('#set-import-go');
  s.$('#set-import-profile').checked = true; s.$('#set-import-profile').fire('change'); await settle();
  assert.equal(old.disabled, true); old.click(); await settle();
  assert.equal(s.calls.length, 2); assert.equal(s.last().options.dry_run, true);
  s.last().resolve(reply); await settle(); assert.equal(s.$('#set-import-go').disabled, false);
});
test('even a detached prior Import action cannot submit the newly selected file', async () => {
  const s = setup(); await s.ready(); const old = s.$('#set-import-go');
  await s.pick('second.json'); s.last().resolve(reply); await settle(); old.click(); await settle();
  assert.equal(s.calls.length, 2);
});
test('a failed import restores the reviewed choices and can be retried', async () => {
  const s = setup(); await s.ready(); s.$('#set-import-go').click(); await settle();
  s.last().reject(new Error('Import failed')); await settle();
  assert.equal(s.$('#set-import-file').disabled, false); assert.equal(s.$('#set-import-cancel').disabled, false);
  assert.equal(s.$('#set-import-profile').disabled, false); assert.equal(s.$('#set-import-go').disabled, false);
  s.$('#set-import-go').click(); await settle();
  assert.equal(s.calls.length, 3); assert.equal(s.last().body.chosen_file, 'first.json');
  s.last().resolve({ ...reply, imported: true }); await settle();
});
test('Cancel still forgets a preview and ignores its outstanding check', async () => {
  const s = setup(); await s.ready();
  s.$('#set-import-profile').checked = true; s.$('#set-import-profile').fire('change'); await settle();
  const check = s.last(); s.$('#set-import-cancel').click(); await settle(); check.resolve(reply); await settle();
  assert.equal(s.text(s.$('#set-import-result')), ''); assert.match(s.text(s.$('#set-import-msg')), /Nothing was imported/);
});
