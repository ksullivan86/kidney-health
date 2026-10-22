#!/usr/bin/env node
// Runs app/static/js/engine/pdf_pages.js (KH.pdfPages) in a Node vm context with fake browser globals (Worker, Trusted Types, a canvas)
// and a fake pdf.js module (tests/js/fake_pdfjs.mjs) in place of the vendored one, and prints what happened as JSON, so pytest
// (tests/test_pdf_pages.py) can check: the options handed to getDocument are exactly note 13 D3's; workerPort is set before getDocument; the
// worker is made by the module itself under a Trusted Types policy that passes one URL; a pdf.js that ignores the port is refused; the
// scale rules for Letter, A4, a receipt-shaped page and a tiny page; every error code; close() terminates the worker; Cancel.
// `import()` in the page code is answered by a resolve hook (node:module registerHooks) that maps the vendored URL to the fake module.
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';
import * as fake from './fake_pdfjs.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..');
const SOURCE = readFileSync(join(ROOT, 'app', 'static', 'js', 'engine', 'pdf_pages.js'), 'utf8');
const PDFJS_URL = '/vendor/pdfjs-dist-6.4.299/pdf.min.mjs';
const WORKER_URL = '/vendor/pdfjs-dist-6.4.299/pdf.worker.min.mjs';

const hook = { importFails: false, asked: [] };
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === PDFJS_URL) {
      hook.asked.push(specifier);
      if (hook.importFails) throw new Error('404');
      return { url: pathToFileURL(join(HERE, 'fake_pdfjs.mjs')).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});

const MB = 1024 * 1024;
const pdfBytes = (text = '%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n') => new TextEncoder().encode(text).buffer;
class FakeFile {
  constructor(buffer, size = buffer.byteLength) { this.buffer = buffer; this.size = size; this.reads = 0; }
  async arrayBuffer() { this.reads += 1; return this.buffer; }
}

// A browser: Worker, Trusted Types (enforced like the page's CSP: only the listed policy name, no duplicates, a Worker takes only a
// TrustedScriptURL), a canvas. `opts` take pieces away.
function makeEnv(opts = {}) {
  const log = { policies: [], workers: [], canvases: [], contexts: [] };
  class FakeWorker {
    constructor(url, options) {
      if (opts.workerThrows) throw new Error('module workers are not supported');
      if (!opts.noTrustedTypes && !(url && url.trustedScriptURL)) throw new TypeError('This document requires TrustedScriptURL assignment.');
      this.url = opts.noTrustedTypes ? String(url) : url.value;
      this.options = options;
      this.terminated = false;
      this.posted = [];
      this.listeners = {};
      log.workers.push(this);
    }
    postMessage(message) { this.posted.push(message); }
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
    terminate() { this.terminated = true; }
    emit(type) { for (const fn of this.listeners[type] || []) fn({ type }); }
  }
  class FakeCanvas {
    constructor() { this.width = 300; this.height = 150; log.canvases.push(this); }
    getContext(kind, options) {
      const ctx = { kind, options, fills: [], fillStyle: null, fillRect(...a) { this.fills.push([this.fillStyle, ...a]); } };
      log.contexts.push(ctx);
      return ctx;
    }
    toBlob(callback, type, quality) {
      callback(opts.noBlob ? null : { type, quality, size: this.width * this.height, width: this.width, height: this.height });
    }
  }
  class HTMLCanvasElement extends FakeCanvas {}
  if (opts.noCanvas) HTMLCanvasElement.prototype.toBlob = undefined;
  const sandbox = {
    console,
    document: { createElement: (tag) => (tag === 'canvas' ? new HTMLCanvasElement() : null) },
    HTMLCanvasElement,
    DOMException,
  };
  if (!opts.noWorker) sandbox.Worker = FakeWorker;
  if (!opts.noTrustedTypes) {
    sandbox.trustedTypes = {
      createPolicy(name, rules) {
        if (opts.policyThrows || name !== 'kh-pdf' || log.policies.some((p) => p.name === name)) throw new TypeError(`Policy ${name} disallowed.`);
        log.policies.push({ name, rules });
        return { createScriptURL: (url) => ({ trustedScriptURL: true, value: rules.createScriptURL(url) }) };
      },
    };
  }
  const context = vm.createContext(sandbox);
  if (opts.noWithResolvers) vm.runInContext('delete Promise.withResolvers', context);
  new vm.Script(SOURCE, { filename: 'js/engine/pdf_pages.js', importModuleDynamically: vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER }).runInContext(context);
  return { KH: context.KH, log, context };
}

// What a promise did: its value or the error's code / name.
async function outcome(promise) {
  try { return { ok: await promise }; } catch (e) { return { error: e.name === 'AbortError' ? 'AbortError' : e.code || e.name, name: e.name, size: e.size, numPages: e.numPages }; }
}
const events = () => [...fake.control.events];
const reset = () => { fake.control.reset(); hook.importFails = false; hook.asked = []; };
const out = {};

// 0. The file asks for what the page needs: exported names and limits.
{
  reset();
  const { KH } = makeEnv();
  out.exports = Object.keys(KH.pdfPages).sort();
  out.limits = { ...KH.pdfPages.LIMITS };
  out.urls = { pdfjs: KH.pdfPages.PDFJS_URL, worker: KH.pdfPages.WORKER_URL };
  out.codes = [...KH.pdfPages.ERROR_CODES];
}

// 1. supported(): needs Worker, Promise.withResolvers and a canvas that makes a JPEG.
{
  reset();
  out.supported = {
    all: makeEnv().KH.pdfPages.supported(),
    noWorker: makeEnv({ noWorker: true }).KH.pdfPages.supported(),
    noWithResolvers: makeEnv({ noWithResolvers: true }).KH.pdfPages.supported(),
    noCanvas: makeEnv({ noCanvas: true }).KH.pdfPages.supported(),
  };
}

// 2. The scale: the longer side at most 2048 px, the area at most 4 MP, at least 16 px a side, at most 4× the size in points.
{
  const { KH } = makeEnv();
  const plan = (w, h) => { const p = KH.pdfPages.planScale(w, h); return { w: p.width, h: p.height, scale: Math.round(p.scale * 1e4) / 1e4 }; };
  out.scale = {
    letter: plan(612, 792), a4: plan(595.28, 841.89), landscape: plan(792, 612), receipt: plan(226, 800), tiny: plan(10, 10),
    tinier: plan(3, 3), poster: plan(5000, 7000), square: plan(1000, 1000), thin: plan(5, 2000), small: plan(100, 140),
    zero: plan(0, 0), nan: plan(NaN, 100),
  };
  // every size in a grid stays inside the server's limits; at most 4× unless a side would be under 16 px; at least 16 px a side unless
  // the page is so long that 16 px would break the 2048 px limit (the server then refuses it by its aspect ratio)
  const sizes = [1, 3, 7, 10, 16, 50, 100, 226, 300, 612, 595.28, 792, 841.89, 1000, 1500, 2000, 5000, 14400];
  const bad = [];
  let cases = 0;
  for (const w of sizes) {
    for (const h of sizes) {
      const p = KH.pdfPages.planScale(w, h);
      cases += 1;
      const inside = p.width <= 2048 && p.height <= 2048 && p.width * p.height <= 4000000 && p.width >= 1 && p.height >= 1;
      const short = Math.min(p.width, p.height);
      const upscaled = p.scale > 4 + 1e-9 && Math.min(w, h) * 4 >= 16; // beyond 4× only to reach 16 px on a thin page
      const tooSmall = short < 16 && Math.max(p.width, p.height) < 2047 && p.width * p.height < 3900000; // 16 px was reachable
      if (!inside || upscaled || tooSmall) bad.push([w, h, p.width, p.height, p.scale]);
    }
  }
  out.scaleGrid = { cases, bad };
}

// 3. A good PDF: the options of getDocument, the order, the worker, the pages, close().
{
  reset();
  const { KH, log } = makeEnv();
  const file = new FakeFile(pdfBytes());
  const doc = await KH.pdfPages.open(file);
  const call = fake.control.getDocumentCalls[0];
  const { data, ...options } = call;
  out.open = {
    numPages: doc.numPages,
    asked: [...hook.asked],
    getDocumentCalls: fake.control.getDocumentCalls.length,
    options,
    dataIsArrayBuffer: data instanceof ArrayBuffer || Object.prototype.toString.call(data) === '[object ArrayBuffer]',
    dataStartsWithPdf: new TextDecoder().decode(new Uint8Array(data, 0, 5)),
    optionKeys: Object.keys(call).sort(),
    events: events(),
    worker: { count: log.workers.length, url: log.workers[0].url, options: log.workers[0].options, posted: log.workers[0].posted.length, terminated: log.workers[0].terminated },
    policies: log.policies.map((p) => p.name),
    portIsOurWorker: undefined,
    fileReads: file.reads,
  };
  // the policy passes the worker URL and nothing else
  const rules = log.policies[0].rules;
  const tries = {};
  for (const url of [WORKER_URL, '/sw.js', 'https://evil.example/x.js', `${WORKER_URL}?x=1`, `${WORKER_URL}/`, '', '/vendor/pdfjs-dist-6.4.299/pdf.min.mjs', 'blob:https://x/abc', 'data:text/javascript,1', null, undefined, 5]) {
    try { tries[String(url)] = rules.createScriptURL(url); } catch (e) { tries[String(url)] = `throws ${e.name}`; }
  }
  out.policyRules = { keys: Object.keys(rules).sort(), tries };
  // render page 1 (Letter) and page 2 (A4)
  const first = await doc.render(1);
  const second = await doc.render(2);
  out.render = {
    first: { type: first.type, quality: first.quality, w: first.width, h: first.height },
    second: { type: second.type, w: second.width, h: second.height },
    renders: fake.control.renders.map((r) => ({
      keys: Object.keys(r).sort(), background: r.background, annotationMode: r.annotationMode, scale: Math.round(r.viewport.scale * 1e4) / 1e4,
      canvasW: r.canvasWidth, canvasH: r.canvasHeight, page: r.page,
    })),
    contextOptions: log.contexts.map((c) => [c.kind, c.options]),
    whiteFirst: log.contexts.map((c) => c.fills[0]),
    canvasesZeroed: log.canvases.every((c) => c.width === 0 && c.height === 0),
    cleanups: fake.control.events.filter((e) => e.startsWith('cleanup')),
  };
  doc.close();
  doc.close(); // twice is fine
  out.closed = {
    events: events(), terminated: log.workers[0].terminated,
    renderAfter: await outcome(doc.render(1)),
  };
  // a second open: a new worker, the policy is not created again, the first document is closed by it
  reset();
  const again1 = await KH.pdfPages.open(new FakeFile(pdfBytes()));
  const w1 = log.workers.length;
  const again2 = await KH.pdfPages.open(new FakeFile(pdfBytes()));
  out.twice = { workers: log.workers.length, firstTerminated: log.workers[w1 - 1].terminated, policies: log.policies.length, secondOpen: !log.workers[w1].terminated, w1 };
  again2.close(); again1.close();
}

// 4. Without Trusted Types (an older browser): the URL string is used as it is.
{
  reset();
  const { KH, log } = makeEnv({ noTrustedTypes: true });
  const doc = await KH.pdfPages.open(new FakeFile(pdfBytes()));
  out.noTrustedTypes = { url: log.workers[0].url, options: log.workers[0].options };
  doc.close();
}

// 5. The refusals, each with its code, and nothing left behind (worker terminated, task destroyed, port cleared).
async function refused(name, env, file, openOpts = {}, setup = () => {}) {
  reset();
  setup();
  const e = makeEnv(env);
  const result = await outcome(e.KH.pdfPages.open(file, openOpts));
  const last = e.log.workers[e.log.workers.length - 1];
  out[name] = {
    ...result,
    workers: e.log.workers.length,
    terminated: last ? last.terminated : null,
    destroyed: fake.control.events.includes('task.destroy'),
    portCleared: ![...fake.control.events].reverse().find((x) => x.startsWith('workerPort='))?.endsWith('=set'),
    getDocumentCalls: fake.control.getDocumentCalls.length,
    fileReads: file.reads,
  };
}
await refused('tooBig', {}, new FakeFile(pdfBytes(), 21 * MB));
await refused('exactlyAtTheLimit', {}, new FakeFile(pdfBytes(), 20 * MB));
await refused('notPdf', {}, new FakeFile(new TextEncoder().encode('hello world, not a pdf').buffer));
await refused('notPdfShort', {}, new FakeFile(new TextEncoder().encode('%PDF').buffer));
await refused('emptyFile', {}, new FakeFile(new ArrayBuffer(0)));
await refused('notAFile', {}, { size: 10 });
await refused('password', {}, new FakeFile(pdfBytes()), {}, () => { fake.control.mode = 'password'; });
await refused('damaged', {}, new FakeFile(pdfBytes()), {}, () => { fake.control.mode = 'damaged'; });
await refused('noPages', {}, new FakeFile(pdfBytes()), {}, () => { fake.control.pages = []; });
await refused('tooManyPages', {}, new FakeFile(pdfBytes()), {}, () => { fake.control.pages = Array.from({ length: 51 }, () => [612, 792]); });
await refused('fiftyPagesAreFine', {}, new FakeFile(pdfBytes()), {}, () => { fake.control.pages = Array.from({ length: 50 }, () => [612, 792]); });
await refused('customLimits', {}, new FakeFile(pdfBytes(), 3000), { maxBytes: 2000 });
await refused('customPages', {}, new FakeFile(pdfBytes()), { maxPages: 1 });
await refused('notSupported', { noWorker: true }, new FakeFile(pdfBytes()));
await refused('importFails', {}, new FakeFile(pdfBytes()), {}, () => { hook.importFails = true; });
await refused('policyRefused', { policyThrows: true }, new FakeFile(pdfBytes()));
await refused('workerThrows', { workerThrows: true }, new FakeFile(pdfBytes()));
// pdf.js ignores the port (it would set up a fake worker on the main thread): refused before the bytes can be handed over
await refused('fakeWorker', {}, new FakeFile(pdfBytes()), {}, () => { fake.control.mode = 'noport'; });

// 6. A worker that cannot start fires `error`: refused, nothing waits for pdf.js forever.
{
  reset();
  fake.control.mode = 'hang';
  const e = makeEnv();
  const pending = outcome(e.KH.pdfPages.open(new FakeFile(pdfBytes())));
  await new Promise((resolve) => setTimeout(resolve, 20));
  e.log.workers[0].emit('error');
  out.workerError = { ...(await pending), terminated: e.log.workers[0].terminated, destroyed: fake.control.events.includes('task.destroy') };
}

// 7. Cancel.
{
  reset();
  let e = makeEnv();
  const early = new AbortController(); early.abort();
  out.abortBefore = { ...(await outcome(e.KH.pdfPages.open(new FakeFile(pdfBytes()), { signal: early.signal }))), workers: e.log.workers.length };

  reset();
  fake.control.mode = 'hang';
  e = makeEnv();
  const during = new AbortController();
  const pending = outcome(e.KH.pdfPages.open(new FakeFile(pdfBytes()), { signal: during.signal }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  during.abort();
  out.abortWhileOpening = { ...(await pending), terminated: e.log.workers[0].terminated, destroyed: fake.control.events.includes('task.destroy') };

  reset();
  e = makeEnv();
  const doc = await e.KH.pdfPages.open(new FakeFile(pdfBytes()));
  const preAborted = new AbortController(); preAborted.abort();
  const before = fake.control.renders.length;
  out.abortRenderBefore = { ...(await outcome(doc.render(1, { signal: preAborted.signal }))), rendersStarted: fake.control.renders.length - before };
  fake.control.renderMode = 'hang';
  const mid = new AbortController();
  const rendering = outcome(doc.render(1, { signal: mid.signal }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  mid.abort();
  out.abortRenderDuring = { ...(await rendering), events: events().filter((x) => x === 'render.cancel' || x.startsWith('cleanup')), zeroed: e.log.canvases.every((c) => c.width === 0) };
  fake.control.renderMode = 'ok';
  fake.control.getPageHang = true;
  const waitPage = new AbortController();
  const gettingPage = outcome(doc.render(2, { signal: waitPage.signal }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  waitPage.abort();
  out.abortGetPage = await gettingPage;
  fake.control.getPageHang = false;
  doc.close();
}

// 8. A page that cannot be drawn, a canvas that cannot make a JPEG, a page number that is not there.
{
  reset();
  let e = makeEnv();
  let doc = await e.KH.pdfPages.open(new FakeFile(pdfBytes()));
  fake.control.renderMode = 'fail';
  out.renderFails = { ...(await outcome(doc.render(1))), cleanups: events().filter((x) => x.startsWith('cleanup')), zeroed: e.log.canvases.every((c) => c.width === 0) };
  fake.control.renderMode = 'ok';
  out.afterAFailedPage = { ok: (await outcome(doc.render(2))).ok !== undefined };
  out.badPage = {
    zero: (await outcome(doc.render(0))).name, three: (await outcome(doc.render(3))).name, fraction: (await outcome(doc.render(1.5))).name,
    text: (await outcome(doc.render('1'))).name,
  };
  doc.close();

  reset();
  e = makeEnv({ noBlob: true });
  doc = await e.KH.pdfPages.open(new FakeFile(pdfBytes()));
  out.noJpeg = await outcome(doc.render(1));
  doc.close();
}

// 9. Page shapes through the real render path: Letter, A4, a long receipt, a tiny page; the canvas the page was drawn on.
{
  reset();
  fake.control.pages = [[612, 792], [595.28, 841.89], [226, 800], [10, 10], [792, 612]];
  const e = makeEnv();
  const doc = await e.KH.pdfPages.open(new FakeFile(pdfBytes()));
  const sizes = [];
  for (let n = 1; n <= 5; n++) { const blob = await doc.render(n); sizes.push([blob.width, blob.height]); }
  out.shapes = sizes;
  doc.close();
}

console.log(JSON.stringify(out));
