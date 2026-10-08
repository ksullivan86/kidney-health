"""Offline handbook pages (docs/ROADMAP.md "Offline handbook pages", note 08 §4.6, note 02 R4).

The service worker answers /learn network-first and keeps a copy of every plain 200 answer in its own cache,
``kdl-learn-<version>``, so pages opened before can be read offline; a page never opened answers offline with a
short note. These checks run the real ``app/static/sw.js`` in Node with a fake network and Cache Storage;
``tools/e2e/learn.py`` checks the same in Chromium (step 6, "offline").
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SW = ROOT / "app" / "static" / "sw.js"

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[2], 'utf8').replace(/__VERSION__/g, 'v2');
const ORIGIN = 'https://kh.example';

// Cache Storage: named caches of URL -> response, matched like the real one (ignoreSearch, cacheName).
const store = new Map();
function cacheFor(name) {
  if (!store.has(name)) store.set(name, new Map());
  const entries = store.get(name);
  return {
    put: async (req, res) => { entries.set(typeof req === 'string' ? new URL(req, ORIGIN).href : req.url, res); },
    match: async (req, opts = {}) => {
      const want = new URL(typeof req === 'string' ? req : req.url, ORIGIN);
      for (const [key, res] of entries) {
        const have = new URL(key);
        if (opts.ignoreSearch ? have.origin + have.pathname === want.origin + want.pathname : key === want.href) return res;
      }
      return undefined;
    },
    addAll: async () => {},
  };
}
const caches = {
  open: async (name) => cacheFor(name),
  match: async (req, opts = {}) => (opts.cacheName ? (store.has(opts.cacheName) ? cacheFor(opts.cacheName).match(req, opts) : undefined) : undefined),
  keys: async () => [...store.keys()],
  delete: async (name) => store.delete(name),
};

// The network: online answers from `site`, offline throws like fetch() does.
let online = true;
const site = new Map();
const fetched = [];
function answer(path, { status = 200, type = 'basic', redirected = false, body = `page ${path}` } = {}) {
  site.set(path, { status, type, redirected, body });
}
async function fakeFetch(req) {
  fetched.push(req.url);
  if (!online) throw new TypeError('Failed to fetch');
  const url = new URL(req.url);
  const a = site.get(url.pathname) || { status: 404, type: 'basic', redirected: false, body: 'not found' };
  const make = () => ({ ...a, url: req.url, clone: make, text: async () => a.body, headers: new Map() });
  return make();
}

const handlers = {};
const self = { location: { origin: ORIGIN }, addEventListener: (type, fn) => { handlers[type] = fn; }, clients: { claim: async () => {} }, skipWaiting: () => {} };
vm.runInNewContext(source, { self, caches, fetch: fakeFetch, Response, Request, URL, console });

async function dispatch(path, { mode = 'navigate', method = 'GET' } = {}) {
  const request = { url: new URL(path, ORIGIN).href, mode, method };
  const waits = [];
  let responded = null;
  handlers.fetch({ request, respondWith: (p) => { responded = Promise.resolve(p); }, waitUntil: (p) => waits.push(p) });
  if (!responded) return { intercepted: false };
  let res;
  let error = null;
  try { res = await responded; } catch (e) { error = String(e); }
  await Promise.all(waits);
  if (error) return { intercepted: true, error };
  const headers = {};
  if (res.headers && typeof res.headers.forEach === 'function') res.headers.forEach((v, k) => { headers[k.toLowerCase()] = v; });
  return { intercepted: true, status: res.status, body: await res.text(), headers };
}
const kept = () => [...(store.get('kdl-learn-v2') || new Map()).keys()].map((u) => new URL(u).pathname + new URL(u).search);

(async () => {
  const out = {};
  answer('/learn/eat/potassium/');
  answer('/learn/assets/javascripts/bundle.79ae519e.min.js', { body: 'js' });
  answer('/learn/search/search_index.json', { body: '{"docs":[]}' });
  answer('/learn/old/', { redirected: true });
  answer('/learn/elsewhere/', { status: 0, type: 'opaqueredirect' });
  answer('/learn/cors/', { type: 'cors' });
  answer('/learn/partial/', { status: 206 });
  out.online = await dispatch('/learn/eat/potassium/');
  out.asset = await dispatch('/learn/assets/javascripts/bundle.79ae519e.min.js', { mode: 'no-cors' });
  out.index = await dispatch('/learn/search/search_index.json', { mode: 'cors' });
  out.missing = await dispatch('/learn/missing/');
  for (const p of ['/learn/old/', '/learn/elsewhere/', '/learn/cors/', '/learn/partial/']) await dispatch(p, { mode: 'cors' });
  out.keptOnline = kept();
  online = false;
  out.offline = await dispatch('/learn/eat/potassium/');
  out.offlineHighlight = await dispatch('/learn/eat/potassium/?h=potassium');
  out.offlineAsset = await dispatch('/learn/assets/javascripts/bundle.79ae519e.min.js', { mode: 'no-cors' });
  out.offlineAssetQuery = await dispatch('/learn/assets/javascripts/bundle.79ae519e.min.js?x=1', { mode: 'no-cors' });
  out.notOpened = await dispatch('/learn/eat/sodium/');
  out.notOpenedAsset = await dispatch('/learn/assets/images/favicon.svg', { mode: 'no-cors' });
  online = true;
  out.api = await dispatch('/api/handbook', { mode: 'cors' });
  out.post = await dispatch('/learn/eat/potassium/', { method: 'POST' });
  out.lookalike = await dispatch('/learnmore/');
  out.bare = await dispatch('/learn');
  // A new release starts with an empty copy: activate removes the old version's caches.
  store.set('kdl-learn-v1', new Map([['https://kh.example/learn/', {}]]));
  const waits = [];
  handlers.activate({ waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
  out.cachesAfterActivate = [...store.keys()].sort();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> dict:
    node = shutil.which("node")
    assert node, "Node.js 22 is needed for the JavaScript checks (CLAUDE.md, Parity)"
    harness = tmp_path_factory.mktemp("sw") / "learn_offline_harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    done = subprocess.run([node, str(harness), str(SW)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_online_the_network_answers_and_a_copy_is_kept(run):
    assert run["online"] == {"intercepted": True, "status": 200, "body": "page /learn/eat/potassium/", "headers": {}}
    assert run["asset"]["body"] == "js" and run["index"]["status"] == 200
    assert run["missing"]["status"] == 404  # passed on as the server answered
    # Only plain 200 answers from this server: no 404, redirect, other-origin or partial answer.
    assert run["keptOnline"] == ["/learn/eat/potassium/", "/learn/assets/javascripts/bundle.79ae519e.min.js",
                                 "/learn/search/search_index.json"]


def test_offline_pages_opened_before_are_read_from_the_copy(run):
    assert run["offline"]["status"] == 200 and run["offline"]["body"] == "page /learn/eat/potassium/"
    assert run["offlineHighlight"]["body"] == "page /learn/eat/potassium/"  # a search result's ?h= link
    assert run["offlineAsset"]["body"] == "js"
    assert run["offlineAssetQuery"] == {"intercepted": True, "error": "TypeError: Failed to fetch"}  # files match exactly


def test_offline_a_page_never_opened_answers_with_a_short_note(run):
    note = run["notOpened"]
    assert note["status"] == 503
    assert "This handbook page is not saved on this device" in note["body"]
    assert '<a href="/learn/">Handbook start page</a>' in note["body"] and '<a href="/">Back to the food log</a>' in note["body"]
    assert "<script" not in note["body"] and "style" not in note["body"].replace("color-scheme", "")
    assert note["headers"]["content-security-policy"].startswith("default-src 'none'")
    assert note["headers"]["cache-control"] == "no-store"
    # A file (not a page) that was never kept fails like the network did.
    assert run["notOpenedAsset"] == {"intercepted": True, "error": "TypeError: Failed to fetch"}


def test_only_the_handbook_is_handled_this_way(run):
    assert run["api"] == {"intercepted": False}
    assert run["post"] == {"intercepted": False}
    assert run["lookalike"] == {"intercepted": False}  # /learnmore is not the handbook
    assert run["bare"]["intercepted"] is True and run["bare"]["status"] == 404  # /learn itself is the handbook's


def test_a_new_release_starts_with_an_empty_copy(run):
    assert "kdl-learn-v1" not in run["cachesAfterActivate"] and "kdl-learn-v2" in run["cachesAfterActivate"]


def test_the_worker_names_its_handbook_cache_and_says_what_it_keeps():
    sw = SW.read_text(encoding="utf-8")
    assert "const LEARN = `kdl-learn-${VERSION}`;" in sw
    assert "if (res.status === 200 && res.type === 'basic' && !res.redirected)" in sw
    # Settings → About tells the person what this device keeps.
    settings = (ROOT / "app" / "static" / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "This device keeps the app itself and the handbook pages you have opened, and, for offline use," in settings
