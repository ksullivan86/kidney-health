#!/usr/bin/env python3
"""Accessibility walk: the automated part of the release check on real phones (docs/maintainers.md, step 2).

Against a real server with a person who has targets, food on several days, a saved meal, a weight and a blood
pressure reading, in Chromium at 375×812 and 1280×800, light and dark, it visits Today, Add, Plan, Trends,
Profile and Settings and opens the main sheets (a food entry, a new saved meal, a weight, a blood pressure
reading and Scan, which opens without a camera). On each:

1. **Keyboard only.** Tab from the top of the page to the end. Every button, link and field can be reached
   (a tab bar and a radio group count once: the arrow keys move inside them), each one shows a focus outline
   (computed style, at least 2 px, 3:1 against the colour behind it) and is not hidden under the header or the
   tab bar, and Tab never gets stuck. A sheet opened with Enter moves focus into it, Tab stays inside it,
   Escape closes it and so does its close button, and focus goes back to the button that opened it.
2. **Names.** Every button, link, field, tab and image has an accessible name (Chromium's accessibility tree,
   through the DevTools protocol). Every field has a label, not only a placeholder. The places where the app
   announces things are live regions.
3. **Large text.** With the root font size at 200 % (also at 320 px wide), the page does not scroll sideways,
   no text is cut off or spills out of a box, and buttons stay at least 44×44 px.
4. **Contrast.** Visible text against what is behind it, and placeholders: at least 4.5:1, or 3:1 for large text
   (WCAG AA), in both themes.

Findings that need a design decision are listed in ``OPEN_QUESTIONS``: they are reported under "open" in the
report and do not fail the run. Everything else does.

    python3 tools/e2e/a11y.py                       # a real server on 127.0.0.1:8099, Chromium; exit 1 on any failed check
    python3 tools/e2e/a11y.py --only 375-light      # one configuration (375-light, 375-dark, 1280-light, 1280-dark, 320-large)
    python3 tools/e2e/a11y.py --parts keyboard,names   # some of: keyboard, names, large, contrast
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import khserver
from khserver import Server, first_admin
from playwright.sync_api import sync_playwright

OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "a11y"
PORT = 8099
CONFIGS = {  # name: (width, height, colour scheme, parts this configuration runs)
    "375-light": (375, 812, "light", ("keyboard", "names", "large", "contrast")),
    "375-dark": (375, 812, "dark", ("keyboard", "names", "large", "contrast")),
    "1280-light": (1280, 800, "light", ("keyboard", "names", "large", "contrast")),
    "1280-dark": (1280, 800, "dark", ("keyboard", "names", "large", "contrast")),
    "320-large": (320, 640, "light", ("large",)),
}
SCREENS = ("today", "add", "plan", "trends", "profile", "settings")

# Findings that need a design decision (see the report). A finding whose text matches a pattern is reported under
# "open" with the reason, and does not fail the run. Keep this list short: each entry is a question for a person.
OPEN_QUESTIONS: list[tuple[str, str, str]] = [
    # (check kind, regular expression on the finding, the question)
    ("target", r"^\(with a mouse\)",
     "With a mouse, some buttons and links stay 24 to 43 px tall at 200 % text. The 44 px minimum applies on touch screens "
     "and phone widths (touch.css). Should it apply with a mouse too? It makes the desktop screens taller."),
    ("grow", r"^\(chart label\)",
     "The labels inside the Trends and weight charts are 11 px in the drawing and do not grow with the text size. "
     "Bigger labels need a new chart layout; the same numbers are in 'Show as table', whose text does grow."),
    ("spill", r'^span "\w+" in nav (spills out of button#tab-|runs off the window)',
     "At 320 px wide with 200 % text, the words under the icons of the bottom tab bar (Today, Trends, Profile) are wider "
     "than their tabs, and the first and last run a few pixels off the screen. Break the words, keep the tab words smaller "
     "than the rest of the text, or show only the icons at that size?"),
]

RESULTS: list[dict[str, Any]] = []
OPEN: list[dict[str, Any]] = []


def check(name: str, items: list[str] | bool, kind: str = "") -> bool:
    """Record a check. ``items`` lists what is wrong (empty: passed); a bool is a plain pass or fail."""
    if isinstance(items, bool):
        found = [] if items else ["failed"]
    else:
        found = list(dict.fromkeys(items))  # once each, in order
    left: list[str] = []
    for item in found:
        question = next((q for k, pat, q in OPEN_QUESTIONS if (not k or k == kind) and re.search(pat, item)), None)
        if question:
            OPEN.append({"check": name, "kind": kind, "finding": item, "question": question})
        else:
            left.append(item)
    ok = not left
    RESULTS.append({"check": name, "kind": kind, "ok": ok, "findings": left[:40], "count": len(left)})
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" :: {len(left)}: " + " | ".join(left[:4]) if left else ""), flush=True)
    return ok


# ------------------------------------------------------------------------------------------------ in-page helpers
# Installed once per page: ids for elements (a WeakMap, so the page's DOM is not changed), a short description,
# visibility, colour parsing and the background behind an element.
HELPERS_JS = r"""
() => {
  if (window.__a11y) return;
  const ids = new WeakMap(); let n = 0;
  const id = (el) => { if (!ids.has(el)) ids.set(el, ++n); return ids.get(el); };
  const vis = (el) => el.checkVisibility ? el.checkVisibility({ opacityProperty: false, visibilityProperty: true }) : true;
  const describe = (el) => {
    if (!el || el.nodeType !== 1) return String(el);
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (cls.length) s += '.' + cls.join('.');
    const txt = (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    if (txt) s += ` "${txt}"`;
    const ctx = el.closest('dialog[open], section[id], header, nav');
    if (ctx && ctx !== el) s += ` in ${ctx.tagName.toLowerCase()}${ctx.id ? '#' + ctx.id : ''}`;
    return s;
  };
  const parse = (c) => {
    if (!c) return null;
    let m = c.match(/rgba?\(([^)]+)\)/);
    if (m) { const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = c.match(/color\(srgb ([^)]+)\)/);
    if (m) { const p = m[1].split(/[ \/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1]; }
    return null;
  };
  const blend = (t, b) => [t[0] * t[3] + b[0] * (1 - t[3]), t[1] * t[3] + b[1] * (1 - t[3]), t[2] * t[3] + b[2] * (1 - t[3]), 1];
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const canvas = () => {
    const bb = parse(getComputedStyle(document.body).backgroundColor);
    return bb && bb[3] > 0 ? blend(bb, [255, 255, 255, 1]) : [255, 255, 255, 1];
  };
  // The colour behind `el`: its own and its ancestors' backgrounds, blended; {complex} over an image or gradient.
  const bgOf = (el) => {
    const layers = []; let opacity = 1;
    for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
      const cs = getComputedStyle(a);
      opacity *= Number(cs.opacity);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return { complex: true };
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
      if (a.tagName === 'DIALOG' && a.open) break;
    }
    let base = canvas();
    if (layers.length && layers[layers.length - 1][3] >= 1) base = layers.pop();
    for (let i = layers.length - 1; i >= 0; i--) base = blend(layers[i], base);
    return { bg: base, opacity };
  };
  const hiddenText = (el) => !!el.closest('script, style, template, title, .sr-only, .skip-link:not(:focus), option')
    || (() => { for (let a = el; a && a.nodeType === 1; a = a.parentElement) { const cs = getComputedStyle(a); if (cs.clip && cs.clip !== 'auto') return true; if (cs.clipPath && cs.clipPath !== 'none') return true; } return false; })();
  const INTERACTIVE = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex="-1"]), [role=button], [role=link], [role=tab], [role=checkbox], [role=radio], [role=switch], [contenteditable="true"]';
  const inScope = (el, scope) => !scope || scope.contains(el);
  window.__a11y = { id, vis, describe, parse, blend, ratio, bgOf, hiddenText, INTERACTIVE, inScope };
}
"""

# Every visible interactive element in the scope, with how it is reached.
INTERACTIVE_JS = r"""
(scopeSel) => {
  const A = window.__a11y;
  const scope = scopeSel ? document.querySelector(scopeSel) : null;
  const out = [];
  for (const el of (scope || document).querySelectorAll(A.INTERACTIVE)) {
    if (!A.vis(el) || el.disabled || el.closest('[inert]')) continue;
    if (!scope && el.closest('dialog')) continue;
    const r = el.getBoundingClientRect();
    if ((r.width < 1 || r.height < 1) && !(el.type === 'radio' || el.type === 'checkbox' || el.type === 'file')) continue;
    let group = '';
    if (el.type === 'radio' && el.name) group = 'radio:' + el.name;
    else if (el.getAttribute('role') === 'tab') group = 'tablist:' + (el.closest('[role=tablist]') ? A.id(el.closest('[role=tablist]')) : '');
    out.push({ id: A.id(el), desc: A.describe(el), tabbable: el.tabIndex >= 0, group });
  }
  return out;
}
"""

# What has focus now, and whether it can be seen.
FOCUS_JS = r"""
(scopeSel) => {
  const A = window.__a11y;
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return { body: true };
  const scope = scopeSel ? document.querySelector(scopeSel) : null;
  let ring = el;
  const r0 = el.getBoundingClientRect();
  const cs0 = getComputedStyle(el);
  if ((el.type === 'radio' || el.type === 'checkbox' || el.type === 'file') && (r0.width < 4 || r0.height < 4 || cs0.opacity === '0') && el.labels && el.labels[0]) ring = el.labels[0];
  const cs = getComputedStyle(ring);
  const width = parseFloat(cs.outlineWidth) || 0;
  const color = A.parse(cs.outlineColor);
  const outline = cs.outlineStyle !== 'none' && width >= 2 && color && color[3] > 0;
  // A chart bar (SVG) draws its ring with a stroke.
  const stroke = ring instanceof SVGElement && cs.stroke !== 'none' && (parseFloat(cs.strokeWidth) || 0) >= 2 && (A.parse(cs.stroke) || [0, 0, 0, 0])[3] > 0;
  const shadow = stroke || (cs.boxShadow && cs.boxShadow !== 'none');
  let ringContrast = null;
  if (outline) {
    const offset = parseFloat(cs.outlineOffset) || 0;
    const b = A.bgOf(offset >= 0 && ring.parentElement ? ring.parentElement : ring);
    if (!b.complex) ringContrast = A.ratio(A.blend(color, b.bg), b.bg);
  }
  const r = ring.getBoundingClientRect();
  const cx = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), cy = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
  let obscured = '';
  if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) obscured = 'outside the window';
  else {
    const hit = document.elementFromPoint(cx, cy);
    if (hit && hit !== ring && !ring.contains(hit) && !hit.contains(ring) && hit !== el && !el.contains(hit) && !(el.labels && [...el.labels].some((l) => l.contains(hit))))
      obscured = 'under ' + A.describe(hit);
  }
  return { id: A.id(el), desc: A.describe(el), inScope: !scope || scope.contains(el), outline, shadow, width, ringContrast, obscured };
}
"""

FORMS_JS = r"""
(scopeSel) => {
  const A = window.__a11y;
  const scope = scopeSel ? document.querySelector(scopeSel) : document;
  const unlabelled = [], images = [];
  for (const el of scope.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=reset]), select, textarea')) {
    if (!scopeSel && el.closest('dialog')) continue;
    if (el.closest('[hidden]') || !(A.vis(el) || (el.labels && [...el.labels].some(A.vis)))) continue;
    const by = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map((i) => document.getElementById(i)).filter(Boolean);
    const named = (el.labels && [...el.labels].some((l) => l.textContent.trim())) || by.some((e) => e.textContent.trim()) || (el.getAttribute('aria-label') || '').trim();
    if (!named) unlabelled.push(A.describe(el) + (el.placeholder ? ' (only a placeholder)' : ''));
  }
  for (const img of scope.querySelectorAll('img')) {
    if (!scopeSel && img.closest('dialog')) continue;
    if (A.vis(img) && !img.hasAttribute('alt')) images.push(A.describe(img) + ' ' + (img.getAttribute('src') || '').slice(0, 60));
  }
  return { unlabelled, images };
}
"""

LIVE_JS = r"""
() => {
  const A = window.__a11y;
  const live = (el) => !!el.closest('[aria-live], [role=status], [role=alert], [role=log], output');
  const missing = [];
  const want = ['#toast', '#sync-live'];
  for (const sel of want) { const el = document.querySelector(sel); if (!el) missing.push(sel + ' is missing'); else if (!live(el)) missing.push(sel + ' is not a live region'); }
  for (const el of document.querySelectorAll('.status-msg, .form-error, .auth-error, [id$="-status"], [id$="-live"]'))
    if (!el.matches('.segmented, fieldset, [role=radiogroup], [role=group]') && !el.querySelector('input, button, select') && !live(el)) missing.push(A.describe(el) + ' shows messages but is not a live region');
  const count = document.querySelectorAll('[aria-live], [role=status], [role=alert]').length;
  return { missing, count };
}
"""

CONTRAST_JS = r"""
(scopeSel) => {
  const A = window.__a11y;
  const scope = scopeSel ? document.querySelector(scopeSel) : document.body;
  const seen = new Map();
  const els = new Set();
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (el && (scopeSel || !el.closest('dialog'))) els.add(el);
  }
  const add = (el, fg, bg, cr, need, size, what) => {
    const key = `${A.describe(el).replace(/ ".*$/, '')}|${what}|${fg.map(Math.round).slice(0, 3)}|${bg.map(Math.round).slice(0, 3)}`;
    if (!seen.has(key)) seen.set(key, `${A.describe(el)}${what} ${Math.round(cr * 100) / 100}:1 < ${need}:1 (rgb(${fg.map(Math.round).slice(0, 3)}) on rgb(${bg.map(Math.round).slice(0, 3)}), ${size}px)`);
  };
  for (const el of els) {
    if (A.hiddenText(el) || el.closest('[aria-hidden="true"]:not(svg *)')) continue;
    if (el.closest('button:disabled, .btn[disabled], [aria-disabled="true"], fieldset:disabled, .toast:not(.show), input:disabled, select:disabled')) continue; // disabled controls are exempt
    if (!A.vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el);
    let fg = A.parse(el instanceof SVGElement ? cs.fill : cs.color);
    if (!fg) continue;
    const b = A.bgOf(el);
    if (b.complex) continue;
    fg = [fg[0], fg[1], fg[2], fg[3] * b.opacity];
    const f2 = A.blend(fg, b.bg);
    const cr = A.ratio(f2, b.bg);
    const size = parseFloat(cs.fontSize), weight = Number(cs.fontWeight) || 400;
    const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    if (cr + 0.005 < need) add(el, f2, b.bg, cr, need, size, '');
  }
  for (const el of scope.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if (!scopeSel && el.closest('dialog')) continue;
    if (!A.vis(el) || el.value || el.disabled || !el.placeholder) continue;
    const cs = getComputedStyle(el, '::placeholder');
    const fg = A.parse(cs.color); const b = A.bgOf(el);
    if (!fg || b.complex) continue;
    const f2 = A.blend(fg, b.bg); const cr = A.ratio(f2, b.bg);
    const size = parseFloat(getComputedStyle(el).fontSize);
    const need = size >= 24 ? 3 : 4.5;
    if (cr + 0.005 < need) add(el, f2, b.bg, cr, need, size, ' placeholder');
  }
  return [...seen.values()];
}
"""

LAYOUT_JS = r"""
([scopeSel, minimum]) => {
  const A = window.__a11y;
  const scope = scopeSel ? document.querySelector(scopeSel) : document.body;
  const se = document.scrollingElement || document.documentElement;
  const out = { hscroll: '', clipped: [], spill: [], small: [] };
  if (!scopeSel && se.scrollWidth > innerWidth + 1) {
    // Name the widest boxes that start the overflow: they stick out while their parent does not.
    const culprits = [];
    for (const el of document.body.querySelectorAll('*')) {
      if (culprits.length >= 3 || el.closest('dialog') || !A.vis(el)) continue;
      const r = el.getBoundingClientRect(), p = el.parentElement.getBoundingClientRect();
      if (r.right > innerWidth + 1 && p.right <= innerWidth + 1 && r.width > 0) culprits.push(`${A.describe(el)} to ${Math.round(r.right)} px`);
    }
    out.hscroll = `the page is ${se.scrollWidth} px wide in a ${innerWidth} px window: ${culprits.join('; ')}`;
  }
  if (scopeSel && scope.scrollWidth > scope.clientWidth + 1) out.hscroll = `${A.describe(scope)} is ${scope.scrollWidth} px wide in ${scope.clientWidth} px`;
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  const seenC = new Set(), seenS = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || (!scopeSel && el.closest('dialog')) || A.hiddenText(el) || !A.vis(el)) continue;
    if (el.closest('.toast:not(.show), #chart-tip, svg')) continue;
    range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter((q) => q.width > 0 && q.height > 0);
    if (!rects.length) continue;
    const t = { left: Math.min(...rects.map((q) => q.left)), right: Math.max(...rects.map((q) => q.right)), top: Math.min(...rects.map((q) => q.top)), bottom: Math.max(...rects.map((q) => q.bottom)) };
    let block = null, scroller = false;
    // A glyph's box is taller than its font size: with line-height 1 it pokes out of a fitting box by a few pixels and that is not a fault.
    const tolY = Math.max(1, 0.15 * parseFloat(getComputedStyle(el).fontSize));
    for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === 'inline' || cs.display === 'contents') continue;
      const ar = a.getBoundingClientRect();
      const ox = cs.overflowX, oy = cs.overflowY;
      if (ox === 'auto' || ox === 'scroll' || oy === 'auto' || oy === 'scroll' || a.tagName === 'DIALOG') {
        // A scroll box: the text can be scrolled to; it is cut only where the box itself has no room for one line.
        scroller = true;
        break;
      }
      const outX = t.right > ar.right + 1 || t.left < ar.left - 1, outY = t.bottom > ar.bottom + tolY || t.top < ar.top - tolY;
      if (((ox === 'hidden' || ox === 'clip') && outX) || ((oy === 'hidden' || oy === 'clip') && outY)) {
        const d = `${A.describe(el)} cut off by ${A.describe(a)}`;
        if (!seenC.has(d)) { seenC.add(d); out.clipped.push(d); }
        break;
      }
      if (!block) {
        block = a;
        if ((outX || outY) && cs.position !== 'absolute') {
          const d = `${A.describe(el)} spills out of ${A.describe(a)} (${outX ? 'sideways' : 'downwards'})`;
          if (!seenS.has(d)) { seenS.add(d); out.spill.push(d); }
        }
      }
    }
    // Words that stick out of their button or link, or out of the window (a fixed bar does not make the page scroll).
    const control = el.closest('button, a, summary, label, [role=button], [role=tab]');
    if (control && control !== block) {
      const cr = control.getBoundingClientRect();
      if (t.right > cr.right + 1 || t.left < cr.left - 1) {
        const d = `${A.describe(el)} spills out of ${A.describe(control)} (sideways)`;
        if (!seenS.has(d)) { seenS.add(d); out.spill.push(d); }
      }
    }
    if (!scroller && (t.right > innerWidth + 1 || t.left < -1)) {
      const d = `${A.describe(el)} runs off the window (${Math.round(t.left)} to ${Math.round(t.right)} px)`;
      if (!seenS.has(d)) { seenS.add(d); out.spill.push(d); }
    }
  }
  // The words inside a field (a date field keeps its own width).
  for (const el of scope.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]):not([type=range])')) {
    if ((!scopeSel && el.closest('dialog')) || !A.vis(el)) continue;
    if (el.scrollWidth > el.clientWidth + 1 && !(el.value && el.value.length > 20)) out.clipped.push(`${A.describe(el)} shows ${el.clientWidth} of ${el.scrollWidth} px`);
  }
  const sel = 'button, [role=button], [role=tab], a.btn, a.icon-btn, summary, select, input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]), label';
  for (const el of scope.querySelectorAll(sel)) {
    if ((!scopeSel && el.closest('dialog')) || !A.vis(el) || el.disabled || A.hiddenText(el)) continue;
    if (el.tagName === 'LABEL') { const c = el.control; if (!c || !(c.type === 'checkbox' || c.type === 'radio')) continue; }
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (r.width < 43.5 || r.height < 43.5) {
      // With a mouse (wide window, no touch) WCAG AA asks for 24 px; smaller than 44 there is reported as a question.
      const mouse = minimum < 44 && r.width >= minimum - 0.5 && r.height >= minimum - 0.5;
      out.small.push(`${mouse ? '(with a mouse) ' : ''}${A.describe(el)} ${r.width.toFixed(0)}×${r.height.toFixed(0)}`);
    }
  }
  return out;
}
"""

# Font sizes before the root goes to 200 %, then the text that did not grow (a size in px ignores the person's setting).
SIZES_JS = r"""
(scopeSel) => {
  const A = window.__a11y;
  const scope = scopeSel ? document.querySelector(scopeSel) : document.body;
  A.sizes = new Map();
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
  const els = new Set(scope.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea'));
  for (let n = walker.nextNode(); n; n = walker.nextNode()) if (n.nodeValue.trim() && n.parentElement) els.add(n.parentElement);
  for (const el of els) {
    if ((!scopeSel && el.closest('dialog')) || A.hiddenText(el) || !A.vis(el)) continue;
    A.sizes.set(el, parseFloat(getComputedStyle(el).fontSize));
  }
}
"""

GROW_JS = r"""
() => {
  const A = window.__a11y;
  const out = [];
  for (const [el, before] of A.sizes || []) {
    if (!el.isConnected || !A.vis(el)) continue;
    const after = parseFloat(getComputedStyle(el).fontSize);
    if (after < before * 1.5) out.push(`${el.closest('svg') ? '(chart label) ' : ''}${A.describe(el)} stays ${after}px`);
  }
  return out;
}
"""

NEED_NAME = {"button", "link", "textbox", "searchbox", "combobox", "listbox", "checkbox", "radio", "switch", "spinbutton",
             "slider", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "image", "img", "dialog", "alertdialog"}


# ------------------------------------------------------------------------------------------------ the checks
class Walk:
    def __init__(self, page: Any, cfg: str, minimum: int = 44) -> None:
        self.page = page
        self.cfg = cfg
        self.minimum = minimum  # the smallest button: 44 px on a phone, 24 px with a mouse (WCAG 2.5.8)
        self.cdp = page.context.new_cdp_session(page)

    def record(self, scope: str | None) -> None:
        self.helpers()
        self.page.evaluate(SIZES_JS, scope)

    def helpers(self) -> None:
        self.page.evaluate(HELPERS_JS)

    # ---- names
    def unnamed(self) -> list[str]:
        tree = self.cdp.send("Accessibility.getFullAXTree")["nodes"]
        out = []
        for node in tree:
            if node.get("ignored"):
                continue
            role = (node.get("role") or {}).get("value", "")
            if role not in NEED_NAME:
                continue
            if ((node.get("name") or {}).get("value") or "").strip():
                continue
            backend = node.get("backendDOMNodeId")
            desc = role
            if backend:
                try:
                    obj = self.cdp.send("DOM.resolveNode", {"backendNodeId": backend})["object"]
                    desc = self.cdp.send("Runtime.callFunctionOn", {
                        "objectId": obj["objectId"], "returnByValue": True,
                        "functionDeclaration": "function () { const A = window.__a11y; return A.vis(this) && !this.closest('[inert]') ? A.describe(this) : ''; }",
                    })["result"].get("value", desc)
                except Exception:  # noqa: BLE001 - a node that went away: describe it by role
                    pass
            if desc:
                out.append(f"{role} with no name: {desc}")
        return out

    def names(self, where: str, scope: str | None) -> None:
        self.helpers()
        forms = self.page.evaluate(FORMS_JS, scope)
        check(f"{self.cfg} {where}: every button, link, field and image has a name", self.unnamed(), "names")
        check(f"{self.cfg} {where}: every field has a label", forms["unlabelled"], "labels")
        check(f"{self.cfg} {where}: every image has alt text", forms["images"], "images")

    # ---- contrast
    def contrast(self, where: str, scope: str | None) -> None:
        self.helpers()
        check(f"{self.cfg} {where}: text contrast meets WCAG AA", self.page.evaluate(CONTRAST_JS, scope), "contrast")

    # ---- keyboard
    def tab_walk(self, where: str, scope: str | None, *, start_top: bool) -> list[dict]:
        page = self.page
        self.helpers()
        targets = page.evaluate(INTERACTIVE_JS, scope)
        limit = 2 * len(targets) + 30  # a date field takes four presses (day, month, year, the calendar button)
        seen: list[dict] = []
        first = None
        if start_top:
            page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); }")
        else:  # a sheet: start from where opening it put the focus
            info = page.evaluate(FOCUS_JS, scope)
            if not info.get("body"):
                first = info["id"]
                seen.append(info)
        wrapped = False
        last = first
        for _ in range(limit):
            page.keyboard.press("Tab")
            info = page.evaluate(FOCUS_JS, scope)
            if info.get("body"):  # past the end of the page (the browser's own controls); the next Tab starts again at the top
                last = None
                continue
            if first is None:
                first = info["id"]
            elif info["id"] == first and last != first:
                wrapped = True
                break
            last = info["id"]
            seen.append(info)
        reached = {s["id"] for s in seen}
        groups_reached = {t["group"] for t in targets if t["id"] in reached and t["group"]}
        missing = [t["desc"] for t in targets if t["id"] not in reached and not (t["group"] and t["group"] in groups_reached)]
        check(f"{self.cfg} {where}: every control can be reached with Tab", missing, "reach")
        check(f"{self.cfg} {where}: every focused control shows a focus outline",
              [f"{s['desc']} (outline {s['width']} px)" for s in seen if not s["outline"] and not s["shadow"]], "focus-visible")
        check(f"{self.cfg} {where}: the focus outline stands out (3:1)",
              [f"{s['desc']} {s['ringContrast']:.2f}:1" for s in seen if s["ringContrast"] is not None and s["ringContrast"] < 3], "focus-contrast")
        check(f"{self.cfg} {where}: a focused control is not hidden under the header or tab bar",
              [f"{s['desc']} {s['obscured']}" for s in seen if s["obscured"]], "focus-obscured")
        if scope:
            check(f"{self.cfg} {where}: Tab stays inside the open sheet", [s["desc"] for s in seen if not s["inScope"]], "modal")
        else:
            check(f"{self.cfg} {where}: Tab reaches the end of the page (no focus trap)",
                  [] if wrapped else [f"after {limit} presses Tab had not come back round; last: {seen[-1]['desc'] if seen else '-'}"], "trap")
        return seen

    def tablist(self) -> None:
        page = self.page
        page.focus("#tab-today")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(150)
        moved = page.evaluate("() => document.activeElement && document.activeElement.id")
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(150)
        back = page.evaluate("() => document.activeElement && document.activeElement.id")
        check(f"{self.cfg} tab bar: the arrow keys move between the tabs", moved == "tab-add" and back == "tab-today", "reach")

    # ---- large text
    def large(self, where: str, scope: str | None) -> None:
        """Measure at 200 % text; call ``record`` before the text is made bigger."""
        self.helpers()
        check(f"{self.cfg} {where} at 200 % text: the text grows", self.page.evaluate(GROW_JS), "grow")
        out = self.page.evaluate(LAYOUT_JS, [scope, self.minimum])
        check(f"{self.cfg} {where} at 200 % text: no sideways scrolling", [out["hscroll"]] if out["hscroll"] else [], "reflow")
        check(f"{self.cfg} {where} at 200 % text: no text cut off", out["clipped"], "clipped")
        check(f"{self.cfg} {where} at 200 % text: no text spills out of its box", out["spill"], "spill")
        check(f"{self.cfg} {where} at 200 % text: buttons are at least 44×44 px", out["small"], "target")


# ------------------------------------------------------------------------------------------------ screens and sheets
def show(page: Any, base: str, view: str) -> None:
    page.goto("about:blank")
    page.goto(f"{base}/#{view}")
    page.wait_for_selector(f"#view-{view}:not([hidden])", timeout=20000)
    ready = {
        "today": "#status-bars > *", "add": "#food-search", "plan": "#saved-meals li", "trends": "#view-trends .card",
        "profile": "#view-profile input", "settings": "#view-settings .card",
    }[view]
    page.wait_for_selector(ready, timeout=20000)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:  # noqa: BLE001 - a long poll is fine
        pass
    page.wait_for_timeout(400)


def big_text(page: Any) -> None:
    page.evaluate("() => { document.documentElement.style.fontSize = '200%'; }")  # CSSOM, which the CSP allows
    page.wait_for_timeout(250)


def open_entry(page: Any, base: str) -> str:
    show(page, base, "add")
    page.fill("#food-search", "apple")
    page.wait_for_selector("#food-results .row-btn", timeout=15000)
    page.wait_for_timeout(300)
    page.focus("#food-results .row-btn >> nth=0")
    return "#food-results .row-btn >> nth=0"


def opener(view: str, sel: str) -> Callable[[Any, str], str]:
    def go(page: Any, base: str) -> str:
        show(page, base, view)
        page.focus(sel)
        return sel
    return go


SHEETS = (  # name, dialog id, how to get to its opener (returns the opener's selector, focused)
    ("entry sheet", "sheet-entry", open_entry),
    ("saved meal sheet", "sheet-meal", opener("plan", "#btn-new-meal")),
    ("weight sheet", "sheet-weight", opener("today", "#body-add-weight")),
    ("blood pressure sheet", "sheet-bp", opener("today", "#body-add-bp")),
    ("Scan sheet", "sheet-scan", opener("add", "#btn-scan")),
)


def sheet_keyboard(w: Walk, base: str, name: str, dlg: str, go: Callable[[Any, str], str], parts: tuple[str, ...]) -> None:
    page = w.page
    w.helpers()
    sel = go(page, base)
    w.helpers()
    opener_id = page.evaluate("() => window.__a11y.id(document.activeElement)")
    page.keyboard.press("Enter")
    page.wait_for_selector(f"#{dlg}[open]", timeout=15000)
    page.wait_for_timeout(250)
    inside = page.evaluate(f"() => document.getElementById('{dlg}').contains(document.activeElement)")
    check(f"{w.cfg} {name}: opening it with Enter moves focus into it", inside, "sheet-focus")
    if "names" in parts:
        w.names(name, f"#{dlg}")
    if "contrast" in parts:
        w.contrast(name, f"#{dlg}")
    if "keyboard" in parts:
        w.tab_walk(name, f"#{dlg}", start_top=False)
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    closed = page.evaluate(f"() => !document.getElementById('{dlg}').open")
    back = page.evaluate(f"() => window.__a11y.id(document.activeElement) === {opener_id}")
    check(f"{w.cfg} {name}: Escape closes it", closed, "sheet-close")
    check(f"{w.cfg} {name}: after Escape, focus goes back to the button that opened it", back, "sheet-return")
    # again, with the close button, pressed with the keyboard
    page.focus(sel)
    page.keyboard.press("Enter")
    page.wait_for_selector(f"#{dlg}[open]", timeout=15000)
    page.wait_for_timeout(250)
    close = page.evaluate(f"""() => {{ const b = [...document.querySelectorAll('#{dlg} [data-close]')].find((x) => window.__a11y.vis(x));
                                       if (b) b.focus(); return !!b && document.activeElement === b; }}""")
    if close:
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)
    closed = page.evaluate(f"() => !document.getElementById('{dlg}').open")
    back = page.evaluate(f"() => window.__a11y.id(document.activeElement) === {opener_id}")
    check(f"{w.cfg} {name}: its close button closes it", close and closed, "sheet-close")
    check(f"{w.cfg} {name}: after the close button, focus goes back to the button that opened it", back, "sheet-return")


def sheet_large(w: Walk, base: str, name: str, dlg: str, go: Callable[[Any, str], str]) -> None:
    page = w.page
    go(page, base)
    page.keyboard.press("Enter")
    page.wait_for_selector(f"#{dlg}[open]", timeout=15000)
    page.wait_for_timeout(300)
    w.record(f"#{dlg}")
    big_text(page)
    w.large(name, f"#{dlg}")
    page.keyboard.press("Escape")


def run_config(browser: Any, base: str, cookies: dict[str, str], cfg: str, parts: tuple[str, ...], shots: Path | None) -> None:
    width, height, scheme, own = CONFIGS[cfg]
    parts = tuple(p for p in own if p in parts)
    if not parts:
        return
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, base_url=base,
                              has_touch=width < 720, service_workers="block")
    ctx.add_cookies([{"name": k, "value": v, "url": base} for k, v in cookies.items()])
    page = ctx.new_page()
    page.set_default_timeout(15000)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    w = Walk(page, cfg, 44 if width < 720 else 24)

    def step(label: str, fn: Callable[[], None]) -> None:
        try:  # each step on its own, so one fault does not hide the others
            fn()
        except Exception:
            check(f"{cfg} {label}: the step ran to the end", False, "harness")
            print(traceback.format_exc(limit=3), file=sys.stderr)
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass

    try:
        for view in SCREENS:
            def screen(view: str = view) -> None:
                show(page, base, view)
                w.helpers()
                if "names" in parts:
                    w.names(view.capitalize(), None)
                if "contrast" in parts:
                    w.contrast(view.capitalize(), None)
                if "keyboard" in parts:
                    w.tab_walk(view.capitalize(), None, start_top=True)
                if "large" in parts:
                    w.record(None)
                    big_text(page)
                    w.large(view.capitalize(), None)
                    if shots:  # for a person to look at; a very tall page can be too big to capture whole
                        try:
                            page.screenshot(path=str(shots / f"{cfg}-{view}-200.png"),
                                            full_page=page.evaluate("document.documentElement.scrollHeight") < 12000)
                        except Exception as exc:  # noqa: BLE001
                            print(f"(no screenshot of {cfg} {view}: {str(exc).splitlines()[0]})", file=sys.stderr)
            step(view, screen)
        if "keyboard" in parts:
            step("tab bar", lambda: (show(page, base, "today"), w.tablist()))
        if "names" in parts:
            def live() -> None:
                show(page, base, "today")
                w.helpers()
                out = page.evaluate(LIVE_JS)
                check(f"{cfg}: the places that announce messages are live regions", out["missing"], "live")
            step("live regions", live)
        for name, dlg, go in SHEETS:
            if {"keyboard", "names", "contrast"} & set(parts):
                step(name, lambda name=name, dlg=dlg, go=go: sheet_keyboard(w, base, name, dlg, go, parts))
            if "large" in parts:
                step(name + " (large text)", lambda name=name, dlg=dlg, go=go: sheet_large(w, base, name, dlg, go))
        check(f"{cfg}: no script errors on the page", errors, "errors")
    finally:
        ctx.close()


def seed(server: Server) -> dict[str, str]:
    ana = first_admin(server, "ana", display_name="Ana")
    ana.json("PUT", "/api/profile", {"weight_kg": 70, "targets": {"potassium_mg": 2500, "phosphorus_mg": 1000, "sodium_mg": 2000,
                                                                  "protein_g": 60, "fluid_ml": 1500, "carbs_per_meal_g": 60}})
    foods = {q: ana.json("GET", "/api/foods", params={"q": q})["foods"][0]["id"] for q in ("banana", "apple", "white rice", "chicken")}
    today = date.today()
    for back in range(5):
        day = (today - timedelta(days=back)).isoformat()
        ana.json("POST", "/api/log", {"date": day, "meal": "breakfast", "food_id": foods["banana"], "servings": 1})
        ana.json("POST", "/api/log", {"date": day, "meal": "lunch", "food_id": foods["white rice"], "servings": 1.5})
        ana.json("POST", "/api/log", {"date": day, "meal": "dinner", "food_id": foods["chicken"], "servings": 1})
        ana.json("POST", "/api/body/weights", {"date": day, "time": "07:15", "kg": 70.0 + back * 0.1, "context": "morning"})
        ana.json("POST", "/api/body/blood-pressure", {"date": day, "time": "07:20", "systolic": 126 + back, "diastolic": 78, "pulse": 64, "context": "morning"})
    ana.json("POST", "/api/log", {"date": today.isoformat(), "meal": "snack", "food_id": foods["apple"], "servings": 1, "status": "planned"})
    ana.json("POST", "/api/meals", {"name": "Rice and chicken", "items": [{"food_id": foods["white rice"], "servings": 1}, {"food_id": foods["chicken"], "servings": 1}]})
    return ana.cookies()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", default="", help="comma-separated configurations: " + ", ".join(CONFIGS))
    ap.add_argument("--parts", default="keyboard,names,large,contrast")
    ap.add_argument("--shots", action="store_true", help="save a screenshot of each screen at 200 %% text")
    args = ap.parse_args(argv)
    if khserver.port_in_use(args.port):
        print(f"port {args.port} is in use; pick another with --port", file=sys.stderr)
        return 2
    configs = [c for c in (args.only.split(",") if args.only else CONFIGS) if c]
    unknown = [c for c in configs if c not in CONFIGS]
    if unknown:
        print(f"unknown configuration {unknown}; pick from {list(CONFIGS)}", file=sys.stderr)
        return 2
    parts = tuple(p.strip() for p in args.parts.split(",") if p.strip())
    out = khserver.free_dir(args.out)
    shots = out / "screenshots" if args.shots else None
    if shots:
        shots.mkdir()
    env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
           "HANDBOOK_DIR": str(out / "no-handbook")}
    server = Server(args.port, out / "data", log_path=out / "server.log", env=env)
    started = time.time()
    try:
        server.start()
        cookies = seed(server)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for cfg in configs:
                    run_config(browser, server.base, cookies, cfg, parts, shots)
            finally:
                browser.close()
    except Exception:
        traceback.print_exc()
        check("the walk ran to the end", False, "harness")
    finally:
        server.stop()
    failed = [r for r in RESULTS if not r["ok"]]
    kinds: dict[str, int] = {}
    for r in failed:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + r["count"]
    report = {"configs": configs, "parts": list(parts), "seconds": round(time.time() - started), "passed": len(RESULTS) - len(failed),
              "failed": len(failed), "findings_by_kind": kinds, "results": RESULTS, "open": OPEN}
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed, {len(OPEN)} open questions; report {out / 'report.json'}")
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
