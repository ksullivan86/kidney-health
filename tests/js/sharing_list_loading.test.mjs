// Runs the real js/views/sharing.js on a fake page: Settings → Care team. Two loads of the list that overlap (Remove
// someone, then Make a link at once) must draw only the newest answer, and a link just made must stay on screen while it is
// still unused, through later loads of the list.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import { makePage, deferred, settle } from './fake_page.mjs';

const source = readFileSync(new URL('../../app/static/js/views/sharing.js', import.meta.url), 'utf8');
const LINK = 'https://kidney.example/#/share/0123456789abcdef.' + 'x'.repeat(43);
const bo = { id: 7, name: 'Bo', username: 'bo', areas: ['food'], since: '2026-10-01', until: null, last_viewed_at: null };
const oldCode = { id: 8, areas: ['labs'], days: null, expires_at: '2026-11-02T00:00:00Z' };
const newCode = { id: 9, areas: ['food', 'labs', 'body', 'symptoms'], days: null, expires_at: '2026-11-05T00:00:00Z' };
const mine = (sharing, codes) => ({ enabled: true, max: 10, sharing, codes });

function setup() {
  const page = makePage();
  const requests = [];
  const KH = {
    h: page.h, $: page.$, clear: page.clear, state: {}, flags: { MOCK: false }, util: {}, views: {},
    request: (method, path, body) => { const d = deferred(); requests.push({ method, path, body, ...d }); return d.promise; },
    toast() {}, toastError() {},
    confirm: { inline: (_box, _btn, opts) => opts.onConfirm() },
    sheets: { setup() {}, open() {}, onSubmit: (form, fn) => form.addEventListener('submit', fn) },
  };
  const context = vm.createContext({ window: { KH, addEventListener() {} }, document: page.document, location: { hash: '', pathname: '/', search: '' },
    history: { replaceState() {} }, navigator: {}, console, setTimeout, clearTimeout });
  vm.runInContext(source, context, { filename: 'sharing.js' });
  page.root.append(KH.sharing.block());
  const body = page.$('#set-sharing');
  // The oldest request for `method path` that has not been answered yet.
  const next = (method, path) => {
    const r = requests.find((x) => !x.done && x.method === method && x.path === path);
    assert.ok(r, `a ${method} ${path} is waiting`);
    r.done = true;
    return r;
  };
  const answerList = async (m, people = []) => { next('GET', '/api/me/shares').resolve(m); await settle(); next('GET', '/api/shared').resolve({ people }); await settle(); };
  const link = () => { const el = page.find(body, (e) => e.id === 'set-share-link')[0]; return el ? { value: el.value || el.attrs.value } : null; };
  const button = (label) => page.find(body, (e) => e.tag === 'button' && (e.attrs['aria-label'] || page.text(e)) === label)[0];
  const makeLink = async () => { page.find(body, (e) => e.tag === 'form' && e.id === 'set-share-form')[0].fire('submit'); await settle(); };
  return { page, body, requests, next, answerList, link, button, makeLink };
}

for (const order of ['newest first', 'oldest first']) {
  test(`Remove someone, then Make a link at once: the new link stays when the lists answer ${order}`, async () => {
    const s = setup();
    await s.answerList(mine([bo], []));
    s.button('Remove Bo (bo) from your Care team').click();
    await settle();
    s.next('DELETE', '/api/me/shares/7').resolve(null);
    await settle(); // load 1 waits for the list
    await s.makeLink();
    s.next('POST', '/api/me/shares').resolve({ code: newCode, link: LINK });
    await settle(); // load 2 waits for the list
    const [one, two] = s.requests.filter((r) => r.path === '/api/me/shares' && r.method === 'GET' && !r.done);
    one.done = true; two.done = true;
    const answer = async (r, m) => { r.resolve(m); await settle(); const p = s.requests.find((x) => !x.done && x.path === '/api/shared'); if (p) { p.done = true; p.resolve({ people: [] }); await settle(); } };
    if (order === 'newest first') { await answer(two, mine([], [newCode])); await answer(one, mine([], [])); }
    else { await answer(one, mine([], [])); await answer(two, mine([], [newCode])); }
    assert.ok(s.link(), 'the new link is on screen');
    assert.equal(s.link().value, LINK);
    assert.ok(s.page.find(s.body, (e) => e.id === 'set-sharing-codes').length === 1, 'the list is the newest answer, with the new link in it');
    assert.equal(s.page.find(s.body, (e) => e.id === 'set-share-link').length, 1, 'the link shows once');
  });
}

test('a link just made stays on screen when the list loads again for another reason', async () => {
  const s = setup();
  await s.answerList(mine([], [oldCode]));
  await s.makeLink();
  s.next('POST', '/api/me/shares').resolve({ code: newCode, link: LINK });
  await settle();
  await s.answerList(mine([], [oldCode, newCode]));
  assert.equal(s.link().value, LINK);
  s.button('Cancel the link for your lab results').click(); // the older link
  await settle();
  s.next('DELETE', '/api/me/shares/8').resolve(null);
  await settle();
  await s.answerList(mine([], [newCode]));
  assert.ok(s.link(), 'the new link is still on screen');
  assert.equal(s.link().value, LINK);
  await new Promise((r) => setTimeout(r, 60));
  assert.equal(s.page.document.activeElement.id, 'set-sharing-make', 'the link shown again does not take the focus');
});

test('a link just made gets the focus', async () => {
  const s = setup();
  await s.answerList(mine([], []));
  await s.makeLink();
  s.next('POST', '/api/me/shares').resolve({ code: newCode, link: LINK });
  await settle();
  await s.answerList(mine([], [newCode]));
  await new Promise((r) => setTimeout(r, 60));
  assert.equal(s.page.document.activeElement.id, 'set-share-link');
});

test('a link just made stays on screen when the next load of the list fails', async () => {
  const s = setup();
  await s.answerList(mine([], [oldCode]));
  await s.makeLink();
  s.next('POST', '/api/me/shares').resolve({ code: newCode, link: LINK });
  await settle();
  await s.answerList(mine([], [oldCode, newCode]));
  s.button('Cancel the link for your lab results').click();
  await settle();
  s.next('DELETE', '/api/me/shares/8').resolve(null);
  await settle();
  s.next('GET', '/api/me/shares').reject(Object.assign(new Error('Network down'), { status: 0 }));
  await settle();
  assert.match(s.page.text(s.body), /Could not load this: Network down/);
  assert.equal(s.link().value, LINK);
});

test('the link goes away once it is cancelled', async () => {
  const s = setup();
  await s.answerList(mine([], []));
  await s.makeLink();
  s.next('POST', '/api/me/shares').resolve({ code: newCode, link: LINK });
  await settle();
  await s.answerList(mine([], [newCode]));
  assert.ok(s.link());
  s.button('Cancel the link for your food log, lab results, weight and blood pressure and symptoms').click();
  await settle();
  s.next('DELETE', '/api/me/shares/9').resolve(null);
  await settle();
  await s.answerList(mine([], []));
  assert.equal(s.link(), null);
});

test('an older load that fails after a newer one drew does not replace the list', async () => {
  const s = setup();
  await s.answerList(mine([bo], []));
  s.button('Remove Bo (bo) from your Care team').click();
  await settle();
  s.next('DELETE', '/api/me/shares/7').resolve(null);
  await settle();
  await s.makeLink();
  s.next('POST', '/api/me/shares').resolve({ code: newCode, link: LINK });
  await settle();
  const [one, two] = s.requests.filter((r) => r.path === '/api/me/shares' && r.method === 'GET' && !r.done);
  one.done = true; two.done = true;
  two.resolve(mine([], [newCode]));
  await settle();
  s.next('GET', '/api/shared').resolve({ people: [] });
  await settle();
  one.reject(Object.assign(new Error('Timed out'), { status: 504 }));
  await settle();
  assert.doesNotMatch(s.page.text(s.body), /Could not load/);
  assert.equal(s.page.find(s.body, (e) => e.id === 'set-sharing-codes').length, 1);
  assert.equal(s.link().value, LINK);
});
