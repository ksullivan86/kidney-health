#!/usr/bin/env node
// Runs app/static/js/views/ai_quality.js against a tiny fake page and fake server answers, and prints what happened as JSON, so
// pytest (tests/test_ai_quality_ui.py) can check the behaviour without a browser: a row for every feature, the caution style for a
// warning and the quiet style for a pass, the folder line, the states with nothing to show, and the "Check again" button. The
// helpers the file takes from KH (h, clear) are stand-ins with the contract of js/core.js: a string child is a text node, so
// nothing the server sends is ever read as HTML.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const source = readFileSync(join(ROOT, 'app', 'static', 'js', 'views', 'ai_quality.js'), 'utf8');

class Text { constructor(t) { this.nodeType = 3; this.t = t; } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.children = []; this.handlers = {}; this.textContent = ''; this.disabled = false; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { for (const k of kids) if (k != null && k !== false) this.children.push(typeof k === 'object' && k.nodeType ? k : new Text(String(k))); }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  async fire(type) { for (const fn of this.handlers[type] || []) await fn({}); await new Promise((r) => setTimeout(r, 0)); }
}
const h = (tag, attrs, ...kids) => {
  const el = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    el.setAttribute(k, v === true ? '' : String(v));
  }
  const add = (k) => { if (k == null || k === false) return; if (Array.isArray(k)) { k.forEach(add); return; } el.append(k.nodeType ? k : new Text(String(k))); };
  kids.forEach(add);
  return el;
};
const clear = (el) => { el.children = []; return el; };
const text = (el) => (el.nodeType === 3 ? el.t : [el.textContent, ...el.children.map(text)].filter(Boolean).join(' ')).replace(/\s+/g, ' ').trim();
const find = (el, pred, out = []) => { if (el.nodeType === 1) { if (pred(el)) out.push(el); el.children.forEach((c) => find(c, pred, out)); } return out; };
const cls = (name) => (e) => (e.attrs.class || '').split(' ').includes(name);

const KH = { h, clear };
const context = vm.createContext({ window: { KH }, document: { contains: () => true }, console });
vm.runInContext(source, context, { filename: 'ai_quality.js' });
const Q = context.window.KH.aiQuality;

const COUNTS = { usable: 0, no_fit: 0, unread: 0, refused: 0, dropped: 0, invalid: 0, error: 0 };
const evaluation = (state, message, warn = false) => ({ state, warn, message, date: null, prompt_version: null, file: null, failed: [], role: null, upstream: null });
const feature = (name, label, extra = {}) => ({
  feature: name, label, route: 'local',
  provider: { id: 2, label: 'LiteLLM', preset: 'litellm', host: 'litellm:4000', model: 'kidney-text' },
  live: { calls: 0, window_days: 14, counts: { ...COUNTS }, unusable: 0, warn: false, summary: 'No calls in the last 14 days.', message: null },
  evaluation: evaluation('none', 'No ai_eval report for this model and prompt version. Run scripts/ai_eval.py with this model and put the report in the reports folder.', true),
  ...extra,
});
const reports = (extra = {}) => ({ configured: true, readable: true, files: 2, reports: 2, ignored: { malformed: 0, too_big: 0, outside_folder: 0, unreadable: 0, over_limit: 0 }, ...extra });
const data = (features, extra = {}) => ({ enabled: true, window_days: 14, last_calls: 20, min_calls: 8, warn_percent: 70, prompt_version: '2026-10-21.1', reports: reports(), features, ...extra });

const WARNING = "Meal ideas: 9 of the last 10 calls to kidney-text had no usable idea (8 'nothing fits', 1 invalid). The app showed the rule results instead. "
  + 'Check this model with scripts/ai_eval.py, or route meal ideas to another AI.';
const meal = feature('meal_ideas', 'Meal ideas', {
  live: { calls: 10, window_days: 14, counts: { ...COUNTS, usable: 1, no_fit: 8, invalid: 1 }, unusable: 9, warn: true,
    summary: "Last 10 calls in 14 days: 1 usable, 8 'nothing fits', 1 invalid.", message: WARNING },
  evaluation: evaluation('failed', 'Failed ai_eval on 2026-10-27: meal-idea cases with at least one idea that passed the checks: 3 % (needs 80 % or more).', true),
});
const describe = feature('describe', 'Describe a meal', {
  live: { calls: 3, window_days: 14, counts: { ...COUNTS, usable: 3 }, unusable: 0, warn: false, summary: 'Last 3 calls in 14 days: 3 usable. Too few calls to judge (8 are needed).', message: null },
  evaluation: evaluation('passed', 'Passed ai_eval on 2026-10-27 (prompt version 2026-10-21.1).'),
});
const labs = feature('labs', 'Lab report photos', { evaluation: evaluation('not_covered', 'Not covered by ai_eval; check a real report by hand (docs/maintainers.md).') });

const rowOf = (root, name) => find(root, (e) => e.attrs['data-feature'] === name)[0];
const cautions = (el) => find(el, cls('caution')).map(text);
const out = {};

// 1. A row for each feature, in the order given; the warning is a caution, the pass is quiet, "not covered" is quiet.
{
  const root = Q.adminPart(data([meal, describe, labs]), null);
  out.rows = find(root, cls('ai-quality-row')).map((r) => r.attrs['data-feature']);
  out.heading = text(find(root, (e) => e.tag === 'h3')[0]);
  out.intro = text(find(root, cls('hint'))[0]);
  out.meal = { text: text(rowOf(root, 'meal_ideas')), cautions: cautions(rowOf(root, 'meal_ideas')) };
  out.describe = { text: text(rowOf(root, 'describe')), cautions: cautions(rowOf(root, 'describe')) };
  out.labs = { text: text(rowOf(root, 'labs')), cautions: cautions(rowOf(root, 'labs')) };
  out.noButton = find(root, (e) => e.tag === 'button').length;
  out.noteRoles = find(root, cls('settings-note')).map((e) => e.attrs.role);
}

// 2. Both signals can warn on one row, and the two cautions are separate.
{
  const root = Q.adminPart(data([meal]), null);
  out.both = cautions(rowOf(root, 'meal_ideas'));
}

// 3. The folder line: not set, set but unreadable, read (with files left out).
{
  out.folder = {
    unset: text(Q.adminPart(data([describe], { reports: reports({ configured: false, readable: false, files: 0, reports: 0 }) }), null)),
    unreadable: cautions(Q.adminPart(data([describe], { reports: reports({ readable: false }) }), null)),
    read: text(find(Q.adminPart(data([describe]), null), cls('ai-quality-folder'))[0]),
    left: text(find(Q.adminPart(data([describe], { reports: reports({ reports: 1, ignored: { malformed: 1, too_big: 1, outside_folder: 0, unreadable: 0, over_limit: 0 } }) }), null), cls('ai-quality-folder'))[0]),
    one: text(find(Q.adminPart(data([describe], { reports: reports({ reports: 1, ignored: { malformed: 1, too_big: 0, outside_folder: 0, unreadable: 0, over_limit: 0 } }) }), null), cls('ai-quality-folder'))[0]),
  };
}

// 4. Nothing to show: AI off, or no feature on.
{
  out.off = text(Q.adminPart(data([], { enabled: false }), null));
  out.empty = text(Q.adminPart(data([]), null));
  out.offRows = find(Q.adminPart(data([], { enabled: false }), null), cls('ai-quality-row')).length;
}

// 5. Text from the server is text: markup in a label or a message stays characters.
{
  const evil = feature('describe', '<img src=x onerror=alert(1)>', {
    provider: { id: 1, label: '<b>x</b>', preset: 'p', host: 'h:1', model: '<script>' },
    live: { calls: 8, window_days: 14, counts: COUNTS, unusable: 8, warn: true, summary: '<i>s</i>', message: '<script>alert(1)</script>' },
    evaluation: evaluation('failed', '<a href=//evil>x</a>', true),
  });
  const root = Q.adminPart(data([evil]), null);
  out.evil = {
    text: text(root),
    elements: find(root, () => true).map((e) => e.tag).filter((t) => !['div', 'h3', 'h4', 'p', 'b'].includes(t)),
    attrs: find(root, () => true).flatMap((e) => Object.keys(e.attrs)).filter((k) => !['class', 'role', 'id', 'data-feature', 'aria-live'].includes(k)),
  };
}

// 6. "Check again" fetches the numbers again and redraws; a failure is said in words; the button is back afterwards.
{
  let calls = 0;
  let fail = false;
  const load = async () => { calls += 1; if (fail) throw Object.assign(new Error('x'), { detail: 'Admins only' }); return data([describe]); };
  const root = Q.adminPart(data([meal]), load);
  const button = find(root, (e) => e.tag === 'button')[0];
  out.button = { label: text(button), type: button.attrs.type, class: button.attrs.class, rowsBefore: find(root, cls('ai-quality-row')).map((r) => r.attrs['data-feature']) };
  await button.fire('click');
  out.again = { calls, rows: find(root, cls('ai-quality-row')).map((r) => r.attrs['data-feature']), disabled: button.disabled, status: text(find(root, (e) => e.attrs.role === 'status')[0]) };
  fail = true;
  await button.fire('click');
  out.failed = { calls, rows: find(root, cls('ai-quality-row')).map((r) => r.attrs['data-feature']), disabled: button.disabled, status: text(find(root, (e) => e.attrs.role === 'status')[0]) };
}

console.log(JSON.stringify(out));
