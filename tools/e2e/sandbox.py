#!/usr/bin/env python3
"""Artifact-sandbox emulator + checker for the Kidney Diet Log preview fragment.

Emulates the claude.ai Artifact host as strictly as practical:

* wraps the FRAGMENT (preview.html next to this file, built by scripts/build_preview.py) in the
  host skeleton: doctype, <html> (optionally with data-theme set by the host), a <head> with only
  charset + viewport (viewport-fit=cover) and the host reset (color-scheme: light on :root,
  :root padded with env(safe-area-inset-*), body margin 0 + off-white background,
  [hidden]{display:none!important}); the fragment goes in <body> (or in <head> with --placement);
* serves it with the CSP  default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline';
  img-src data: blob:; font-src data:; connect-src 'none'
* loads it top level AND inside an outer page's <iframe sandbox="allow-scripts"> (opaque origin:
  storage throws, alert/confirm/prompt suppressed, downloads and form submission blocked, no
  query string reaches the page);
* walks the app (Today, Add, Plan, Trends, What fits now, a recorded barcode with the Open Food Facts
  agreement, Plan the rest of my day, Treating a low, Profile with the explained suggestion, Lab results,
  delete with in-page confirmation, banner) at
  375x812 (touch, safe-area insets 47/34) and 1280x800, prefers-color-scheme light/dark and host
  data-theme dark/light, and records console errors, CSP violations, page errors, network
  requests other than the documents, horizontal overflow, elements outside the viewport,
  contrast < 4.5:1, tap targets < 44 px on phone and clicks with no visible change.

Accounts (v0.3): in demo mode the person is a signed-in demo admin, so the walk also covers the
header gear, Settings (invite + Copy, own key, export, delete refused, disable a demo person) and
sign out / sign in with the demo account.

Usage:  python tools/e2e/sandbox.py [--only top-phone-light-none,...] [--no-sweep] [--workers 4]
                                    [--out DIR] [--preview FILE] [--port N]
Builds the fragment with scripts/build_preview.py into <out>/preview.html (or uses --preview),
writes <out>/results.json and screenshots in <out>/shots/. No app server is needed; the
emulated host server is stopped on exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from khserver import REPO, chromium_executable  # noqa: E402

# Read from the environment so the spawned worker processes see main()'s choices.
OUT = Path(os.environ.get("KH_SANDBOX_OUT") or Path(tempfile.gettempdir()) / "kidney-health-e2e" / "sandbox")
FRAGMENT_PATH = Path(os.environ.get("KH_SANDBOX_PREVIEW") or OUT / "preview.html")
SHOTS = OUT / "shots"
RESULTS = OUT / "results.json"
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
       "img-src data: blob:; font-src data:; connect-src 'none'")
CHROME = chromium_executable()

HOST_HEAD = """<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root { color-scheme: light; padding-top: env(safe-area-inset-top); padding-bottom: env(safe-area-inset-bottom); }
body { margin: 0; background: #faf9f5; }
[hidden] { display: none !important; }
</style>"""


def skeleton(fragment: str, theme: str, placement: str = "body") -> str:
    attrs = f' data-theme="{theme}"' if theme in ("dark", "light") else ""
    if placement == "head":  # fragment right after the host head: the parser decides where it lands
        return f"<!doctype html>\n<html lang=\"en\"{attrs}>\n<head>\n{HOST_HEAD}\n{fragment}\n</html>\n"
    return f"<!doctype html>\n<html lang=\"en\"{attrs}>\n<head>\n{HOST_HEAD}\n</head>\n<body>\n{fragment}\n</body>\n</html>\n"


def outer_page(theme: str, hash_: str, placement: str) -> str:
    src = f"/page/{theme}" + ("?placement=head" if placement == "head" else "") + (f"#{hash_}" if hash_ else "")
    # NB the query string above is only how this emulator picks a skeleton; the app only reads
    # location.search for ?mock=1/&hd=1, which it never sees here.
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Host</title><link rel="icon" href="data:,">
<style>html,body{{margin:0;height:100%;background:#7a7a7a}}iframe{{border:0;display:block;width:100vw;height:100vh}}
#clip{{position:fixed;left:-9999px;top:0;width:50px;height:20px}}</style></head>
<body><iframe id="app" title="Artifact" sandbox="allow-scripts" src="{src}"></iframe>
<textarea id="clip" aria-hidden="true"></textarea></body></html>"""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
class Server:
    def __init__(self, port: int = 0):
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        fragment = FRAGMENT_PATH.read_text(encoding="utf-8")
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                with srv.lock:
                    srv.requests.append({"path": self.path, "referer": self.headers.get("Referer"), "t": time.time()})
                m = re.fullmatch(r"/page/(none|dark|light)", u.path)
                if m:
                    body = skeleton(fragment, m.group(1), (q.get("placement") or ["body"])[0]).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Security-Policy", CSP)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                m = re.fullmatch(r"/outer/(none|dark|light)", u.path)
                if m:
                    body = outer_page(m.group(1), (q.get("hash") or [""])[0], (q.get("placement") or ["body"])[0]).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                with srv.lock:
                    srv.requests.append({"path": "POST " + self.path, "referer": self.headers.get("Referer"), "t": time.time()})
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ---------------------------------------------------------------------------
# In-page checks (run inside the app's frame)
# ---------------------------------------------------------------------------
CHECKS_JS = r"""
(opts) => {
  const out = {};
  const W = window.innerWidth, Hh = window.innerHeight;
  const se = document.scrollingElement || document.documentElement;
  out.scrollWidth = se.scrollWidth; out.innerWidth = W; out.overflowX = se.scrollWidth > W;
  const vis = (el) => el.checkVisibility ? el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true }) : true;
  const describe = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    if (cls.length) s += '.' + cls.join('.');
    const txt = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    if (txt) s += ` "${txt}"`;
    // nearest landmark-ish context
    const ctx = el.closest('dialog[open], section[id], .view');
    if (ctx && ctx !== el) s += ` in ${ctx.tagName.toLowerCase()}#${ctx.id || ''}`;
    return s;
  };
  // ---- elements outside the viewport horizontally ----
  const off = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('.sr-only, .skip-link, script, style, template, #chart-tip')) continue;
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (r.right <= W + 0.5 && r.left >= -0.5) continue;
    let clipped = false;
    for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.overflowX !== 'visible') {
        const ar = a.getBoundingClientRect();
        if (ar.right <= W + 0.5 && ar.left >= -0.5) { clipped = true; break; }
      }
    }
    if (clipped) continue;
    off.push(`${describe(el)} [left ${r.left.toFixed(0)}, right ${r.right.toFixed(0)}]`);
  }
  out.offscreen = off.slice(0, 30);
  // ---- tap targets ----
  if (opts.taps) {
    const small = [];
    const hits = [];
    const sel = 'button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [tabindex]:not([tabindex="-1"]), label';
    for (const el of document.querySelectorAll(sel)) {
      if (!vis(el)) continue;
      if (el.disabled) continue;
      if (el.closest('.sr-only, .skip-link')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const tag = el.tagName.toLowerCase();
      if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
        const lab = el.closest('label') || (el.id && document.querySelector(`label[for="${el.id}"]`));
        if (lab) continue; // the label is the target
      }
      if (tag === 'label') {
        const c = el.control;
        if (!c || !(c.type === 'checkbox' || c.type === 'radio')) continue; // a field caption, not a target
      }
      if (el instanceof SVGElement) {
        if (r.width < 44 || r.height < 44) hits.push(`${describe(el)} ${r.width.toFixed(0)}x${r.height.toFixed(0)}`);
        continue;
      }
      if (r.width < 43.5 || r.height < 43.5) small.push(`${describe(el)} ${r.width.toFixed(1)}x${r.height.toFixed(1)}`);
    }
    out.smallTaps = small.slice(0, 40);
    out.smallSvgHits = hits.slice(0, 3); out.smallSvgHitsCount = hits.length;
  }
  // ---- contrast ----
  if (opts.contrast) {
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
    const canvas = (() => {
      const rb = parse(getComputedStyle(document.documentElement).backgroundColor);
      if (rb && rb[3] > 0) return blend(rb, [255, 255, 255, 1]);
      const bb = parse(getComputedStyle(document.body).backgroundColor);
      return bb && bb[3] > 0 ? blend(bb, [255, 255, 255, 1]) : [255, 255, 255, 1];
    })();
    const bgOf = (el) => {
      const layers = [];
      let opacity = 1;
      for (let a = el; a && a.nodeType === 1; a = a.parentElement) {
        const cs = getComputedStyle(a);
        opacity *= Number(cs.opacity);
        if (cs.backgroundImage && cs.backgroundImage !== 'none') return { complex: true };
        const c = parse(cs.backgroundColor);
        if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
      }
      let base = canvas;
      if (layers.length && layers[layers.length - 1][3] >= 1) base = layers.pop();
      for (let i = layers.length - 1; i >= 0; i--) base = blend(layers[i], base);
      return { bg: base, opacity };
    };
    const seen = new Map();
    const tokens = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const els = new Set();
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!n.nodeValue.trim()) continue;
      const el = n.parentElement;
      if (!el || els.has(el)) continue;
      els.add(el);
    }
    for (const el of els) {
      if (el.closest('script, style, title, .sr-only, .skip-link, option, [aria-hidden="true"]:not(svg *)')) continue;
      if (el.closest('button:disabled, .btn[disabled], [aria-disabled="true"], .toast:not(.show)')) continue; // fading-out toast: mid-transition colours
      if (!vis(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const cs = getComputedStyle(el);
      let fg = parse(el instanceof SVGElement ? cs.fill : cs.color);
      if (!fg) continue;
      const b = bgOf(el);
      if (b.complex) continue;
      fg = [fg[0], fg[1], fg[2], fg[3] * b.opacity];
      const f2 = blend(fg, b.bg);
      const cr = ratio(f2, b.bg);
      const size = parseFloat(cs.fontSize), weight = Number(cs.fontWeight) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const need = large ? 3 : 4.5;
      if (cr + 0.005 < need) {
        const key = `${describe(el).replace(/ ".*$/, '')}|${f2.map(Math.round).slice(0, 3)}|${b.bg.map(Math.round).slice(0, 3)}`;
        if (!seen.has(key)) seen.set(key, { el: describe(el), fg: `rgb(${f2.map(Math.round).slice(0, 3)})`, bg: `rgb(${b.bg.map(Math.round).slice(0, 3)})`, ratio: Math.round(cr * 100) / 100, need, size });
      }
    }
    out.lowContrast = [...seen.values()].slice(0, 30);
  }
  return out;
}
"""

TOKENS_JS = r"""
() => {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  const hex = (h) => { if (!h) return null; h = h.replace('#', ''); if (h.length === 3) h = h.split('').map((c) => c + c).join(''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; };
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const pairs = [
    ['--text', '--bg'], ['--text', '--surface'], ['--text', '--surface-2'],
    ['--text-2', '--bg'], ['--text-2', '--surface'], ['--text-2', '--surface-2'], ['--text-2', '--surface-3'],
    ['--text-3', '--bg'], ['--text-3', '--surface'], ['--text-3', '--surface-2'],
    ['--accent', '--surface'], ['--accent', '--bg'], ['--accent', '--accent-tint'], ['--accent-text', '--accent'],
    ['--ok-text', '--ok-tint'], ['--caution-text', '--caution-tint'], ['--over-text', '--over-tint'],
    ['--ok-text', '--surface'], ['--over-text', '--surface'], ['--surface', '--over-text'],
    ['#ffffff', '--ok'], ['#ffffff', '--over'], ['--bg', '--text'], ['--caution-glyph', '--caution'],
  ];
  const out = [];
  for (const [a, b] of pairs) {
    const ca = hex(a.startsWith('#') ? a : v(a)), cb = hex(b.startsWith('#') ? b : v(b));
    if (!ca || !cb) continue;
    out.push({ fg: a, bg: b, fgv: a.startsWith('#') ? a : v(a), bgv: v(b), ratio: Math.round(ratio(ca, cb) * 100) / 100 });
  }
  return { scheme: getComputedStyle(document.documentElement).colorScheme, theme: document.documentElement.getAttribute('data-theme'), bodyBg: getComputedStyle(document.body).backgroundColor, pairs: out };
}
"""

FINGERPRINT_JS = r"""
() => {
  let h = 0; const s = document.body.innerHTML;
  for (let i = 0; i < s.length; i += 7) h = (h * 31 + s.charCodeAt(i)) | 0;
  const vals = [...document.querySelectorAll('input, select, textarea')].map((e) => e.type === 'checkbox' || e.type === 'radio' ? (e.checked ? 1 : 0) : (e.value || '').length).join('');
  return JSON.stringify({ h, n: s.length, y: Math.round(scrollY), vals, theme: document.documentElement.getAttribute('data-theme'),
    dlg: [...document.querySelectorAll('dialog[open]')].map((d) => d.id) });
}
"""


# ---------------------------------------------------------------------------
# One configuration
# ---------------------------------------------------------------------------
class Run:
    def __init__(self, port, ctx_kind, vp, scheme, host_theme, placement="body"):
        self.port, self.ctx_kind, self.vp, self.scheme, self.host_theme, self.placement = port, ctx_kind, vp, scheme, host_theme, placement
        self.name = f"{ctx_kind}-{vp}-{scheme}-{host_theme}" + ("-head" if placement == "head" else "")
        self.issues: list[dict] = []
        self.notes: list[str] = []
        self.console: list[str] = []
        self.requests: list[str] = []
        self.shots: list[str] = []
        self.phone = vp == "phone"
        self.expected_theme = host_theme if host_theme in ("dark", "light") else scheme

    # -- recording --
    def issue(self, area, title, evidence, severity="medium"):
        self.issues.append({"config": self.name, "area": area, "title": title, "evidence": evidence, "severity": severity})

    def note(self, msg):
        self.notes.append(msg)

    def shot(self, label, full=False):
        p = SHOTS / f"{self.name}-{label}.png"
        try:
            # scale="css" inside the iframe: a device-scale screenshot leaves Chromium's touch
            # mapping for the out-of-process frame halved (emulator artefact, see run()).
            self.page.screenshot(path=str(p), full_page=full and self.ctx_kind == "top", scale="css" if self.ctx_kind == "iframe" else "device")
            self.shots.append(str(p))
        except Exception as e:  # noqa: BLE001
            self.note(f"screenshot {label} failed: {e}")
        return str(p)

    def snap(self):
        return hashlib.sha1(self.page.screenshot(scale="css")).hexdigest()

    def fp(self):
        return self.F.evaluate(FINGERPRINT_JS)

    # -- interaction helpers --
    def press(self, selector, desc, *, wait=None, expect_change=True, timeout=5000, nth=None):
        loc = self.F.locator(selector)
        loc = loc.nth(nth) if nth is not None else loc.first
        loc.scroll_into_view_if_needed(timeout=timeout)
        self.page.wait_for_timeout(120)
        before, fbefore = self.snap(), self.fp()
        try:
            if self.phone:
                loc.tap(timeout=timeout)
            else:
                loc.click(timeout=timeout)
        except Exception as e:  # noqa: BLE001
            diag = loc.evaluate("""(el) => { const b = el.getBoundingClientRect(); const x = b.left + b.width / 2, y = b.top + b.height / 2;
                const hit = document.elementFromPoint(x, y);
                const d = (n) => n ? n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.className && n.className.baseVal === undefined ? '.' + String(n.className).split(' ').join('.') : '') : null;
                return { rect: [b.left, b.top, b.width, b.height].map(Math.round), hit: d(hit), hitInside: !!(hit && el.contains(hit)), scrollY, innerHeight,
                         chain: hit ? [...Array(6)].reduce((a, _, i) => { let n = hit; for (let k = 0; k < i && n; k++) n = n.parentElement; a.push(d(n)); return a; }, []) : [] }; }""")
            # Playwright's own actionability hit-test sometimes disagrees inside the sandboxed
            # frame; a raw touch / mouse event at the element's centre is what a person does.
            # If the app's elementFromPoint says the control is on top, fall back to that and only
            # report when the raw event then fails (the `wait` check below records it).
            box = loc.bounding_box()
            if diag["hitInside"] and box:
                self.note(f"{desc}: Playwright {'tap' if self.phone else 'click'} refused ({str(e).splitlines()[-1][:120]}), "
                          f"elementFromPoint hits the control; using a raw event at its centre")
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                if self.phone:
                    self.page.touchscreen.tap(cx, cy)
                else:
                    self.page.mouse.click(cx, cy)
            else:
                outer = self.page.evaluate("() => [scrollX, scrollY, document.scrollingElement.scrollHeight, innerHeight]")
                self.issue("interaction", f"{desc}: {'tap' if self.phone else 'click'} could not reach the control",
                           f"{str(e).splitlines()[0][:200]}; in-frame diagnostics {diag}; outer scroll {outer}", "high")
                loc.evaluate("(el) => el.click()")
        if wait:
            try:
                wait()
            except Exception as e:  # noqa: BLE001
                self.issue("interaction", f"{desc}: expected result did not appear", f"{type(e).__name__}: {str(e).splitlines()[0][:300]}", "high")
        self.page.wait_for_timeout(450)
        after, fafter = self.snap(), self.fp()
        if expect_change and before == after:
            self.issue("silent-noop", f"{desc}: click produced no visible change",
                       f"screenshot identical before/after; DOM {'changed' if fbefore != fafter else 'unchanged'}", "medium")
        return loc

    def wait_fn(self, js, arg=None, timeout=6000):
        return lambda: self.F.wait_for_function(js, arg=arg, timeout=timeout)

    def text(self, selector):
        return self.F.locator(selector).first.inner_text(timeout=3000)

    def count(self, selector):
        return self.F.locator(selector).count()

    def visible(self, selector):
        try:
            return self.F.locator(selector).first.is_visible()
        except Exception:  # noqa: BLE001
            return False

    def checks(self, step, contrast=False):
        try:
            r = self.F.evaluate(CHECKS_JS, {"taps": self.phone, "contrast": contrast})
        except Exception as e:  # noqa: BLE001
            self.note(f"checks at {step} failed: {e}")
            return
        if r["overflowX"]:
            self.issue("layout", f"Horizontal page scroll at {step}", f"scrollWidth {r['scrollWidth']} > innerWidth {r['innerWidth']}", "high")
        if r["offscreen"]:
            self.issue("layout", f"Elements outside the viewport at {step}", "; ".join(r["offscreen"][:8]), "medium")
        if self.phone and r.get("smallTaps"):
            self.issue("tap-targets", f"Tap targets under 44 px at {step}", "; ".join(r["smallTaps"][:12]), "low")
        if self.phone and r.get("smallSvgHitsCount"):
            self.note(f"{step}: {r['smallSvgHitsCount']} chart bar hit areas under 44 px, e.g. {r['smallSvgHits'][:1]}")
        if contrast and r.get("lowContrast"):
            self.issue("contrast", f"Text below WCAG contrast at {step}",
                       "; ".join(f"{x['el']} {x['fg']} on {x['bg']} = {x['ratio']}:1 (needs {x['need']}, {x['size']}px)" for x in r["lowContrast"][:10]), "medium")

    # -- main --
    def run(self, browser):
        from playwright.sync_api import TimeoutError as PWTimeout  # noqa: F401
        opts = dict(color_scheme=self.scheme, accept_downloads=False)
        if self.phone:
            opts.update(viewport={"width": 375, "height": 812}, device_scale_factor=2, is_mobile=True, has_touch=True)
        else:
            opts.update(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
        ctx = browser.new_context(**opts)
        origin = f"http://127.0.0.1:{self.port}"
        try:
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
        except Exception as e:  # noqa: BLE001
            self.note(f"grant clipboard failed: {e}")
        ctx.add_init_script("""
          document.addEventListener('securitypolicyviolation', (e) => {
            console.error('[CSP-VIOLATION] ' + e.violatedDirective + ' blocked ' + (e.blockedURI || '(inline)') + ' at ' + (e.sourceFile || '') + ':' + (e.lineNumber || ''));
          }, true);
        """)
        page = ctx.new_page()
        self.page = page
        if self.phone and self.ctx_kind == "top":
            # Safe-area insets only for the top-level page: env() is 0 inside an iframe anyway, and
            # this CDP override breaks touch coordinates in out-of-process frames (touches land at
            # half the position with device_scale_factor 2) - an emulator artefact, not an app bug.
            cdp = ctx.new_cdp_session(page)
            cdp.send("Emulation.setSafeAreaInsetsOverride", {"insets": {"top": 47, "bottom": 34, "left": 0, "right": 0}})
        page.on("console", lambda m: self.console.append(f"{m.type}: {m.text[:400]} @ {m.location.get('url', '')[-40:] if m.location else ''}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        page.on("dialog", lambda d: (self.console.append(f"dialog: {d.type} {d.message[:100]}"), d.dismiss()))
        page.on("download", lambda d: self.console.append(f"download: {d.suggested_filename}"))
        page.on("popup", lambda p: self.console.append(f"popup: {p.url}"))
        page.on("request", lambda r: self.requests.append(f"{r.method} {r.url} [{r.resource_type}]"))
        page.on("requestfailed", lambda r: self.console.append(f"requestfailed: {r.url} {r.failure}"))
        try:
            self.load(page)
            self.walk()
        except Exception as e:  # noqa: BLE001
            self.issue("harness", f"walk aborted: {type(e).__name__}", traceback.format_exc()[-1500:], "high")
            self.shot("abort")
        finally:
            self.finish()
            ctx.close()

    def app_url(self, hash_=""):
        pl = "?placement=head" if self.placement == "head" else ""
        if self.ctx_kind == "top":
            return f"http://127.0.0.1:{self.port}/page/{self.host_theme}{pl}" + (f"#{hash_}" if hash_ else "")
        q = f"?hash={hash_}" if hash_ else "?"
        q += "&placement=head" if self.placement == "head" else ""
        return f"http://127.0.0.1:{self.port}/outer/{self.host_theme}{q}"

    def load(self, page, hash_=""):
        t0 = time.time()
        page.goto(self.app_url(hash_), wait_until="load")
        if self.ctx_kind == "top":
            self.F = page.main_frame
        else:
            self.F = page.wait_for_selector("iframe#app").content_frame()
        self.F.wait_for_selector("#status-bars .stat, #view-plan:not([hidden]) .plan-day, #charts .chart-card, #view-profile:not([hidden]) #pf-weight, #food-results .row-btn, #view-settings:not([hidden]) #set-account-body .kv, #view-labs:not([hidden]) #labs-history .lab-row", timeout=10000)
        self.load_ms = int((time.time() - t0) * 1000)

    def finish(self):
        allowed = {"/page/", "/outer/"}
        for r in self.requests:
            url = r.split(" ")[1]
            p = urlparse(url)
            if p.scheme in ("data", "blob", "about"):
                continue
            if not any(p.path.startswith(a) for a in allowed) or "[document]" not in r:
                self.issue("network", "Network request other than the document", r, "high")
        bad = [c for c in self.console if not c.startswith("warning: [Violation]")]
        for c in bad:
            sev = "high" if ("CSP" in c or "Refused" in c or "pageerror" in c or "Uncaught" in c) else "medium"
            if c.startswith("dialog:") or c.startswith("download:") or c.startswith("popup:"):
                sev = "high"
            self.issue("console", "Console error/warning, page error or blocked action", c, sev)

    # -----------------------------------------------------------------------
    def walk(self):
        F = self.F
        exp = self.expected_theme
        # ---- load state ----
        tok = F.evaluate(TOKENS_JS)
        bg_expect = {"light": "rgb(244, 245, 247)", "dark": "rgb(17, 20, 23)"}[exp]
        if tok["bodyBg"] != bg_expect:
            self.issue("theme", f"Wrong theme on load (expected {exp})", f"body background {tok['bodyBg']}, data-theme={tok['theme']}, color-scheme={tok['scheme']}", "high")
        if tok["scheme"] != exp:
            self.issue("theme", "color-scheme does not follow the theme", f"computed color-scheme '{tok['scheme']}' with {exp} theme", "medium")
        for p in tok["pairs"]:
            if p["ratio"] < 4.5:
                self.note(f"token pair {p['fg']}({p['fgv']}) on {p['bg']}({p['bgv']}) = {p['ratio']}:1")
        self.token_pairs = tok["pairs"]
        title = F.evaluate("document.title")
        if title != "Kidney Diet Log":
            self.issue("host", "document.title wrong", f"title={title!r}", "medium")
        storage = F.evaluate("(() => { try { localStorage.setItem('x','1'); localStorage.removeItem('x'); return 'ok'; } catch (e) { return 'throws: ' + e.name; } })()")
        self.note(f"storage: {storage}; load {self.load_ms} ms")
        label = F.locator("#theme-toggle").get_attribute("aria-label")
        want = "Switch to light theme" if exp == "dark" else "Switch to dark theme"
        if label != want:
            self.issue("theme", "Theme toggle label does not match the effective theme", f"aria-label={label!r}, expected {want!r}", "low")
        if not self.visible("#preview-banner"):
            self.issue("preview", "Preview banner not visible on load", "#preview-banner hidden", "medium")
        if self.text("#brand-pill").strip().lower() != "preview":
            self.issue("preview", "Brand pill does not say Preview", self.text("#brand-pill"), "low")
        # safe-area layout on phone
        if self.phone:
            geo = F.evaluate("""() => { const t = document.querySelector('.topbar'), tb = document.querySelector('.tabs');
              const a = getComputedStyle(t), b = getComputedStyle(tb);
              return { pos: a.position, top: a.top, tabsPos: b.position, tabsPadB: b.paddingBottom, tabsBottom: tb.getBoundingClientRect().bottom,
                       rootPadTop: getComputedStyle(document.documentElement).paddingTop, ih: innerHeight }; }""")
            self.note(f"phone geometry: {geo}")
            if geo["pos"] not in ("sticky", "fixed"):
                self.issue("layout", "Header is not sticky/fixed", str(geo), "medium")
            if self.ctx_kind == "top" and (geo["top"] != "47px" or geo["tabsPadB"] != "34px"):
                self.issue("safe-area", "Header/tab bar do not use the safe-area insets", str(geo), "medium")
        self.shot("today", full=True)
        self.shot("today-viewport")
        self.checks("Today (load)", contrast=True)

        # ---- theme toggle round trip ----
        self.press("#theme-toggle", "Theme toggle", wait=self.wait_fn(
            "(exp) => { const t = document.documentElement.getAttribute('data-theme'); return t && t !== exp; }", exp))
        self.checks("Today (toggled theme)", contrast=True)
        self.shot("today-toggled")
        self.press("#theme-toggle", "Theme toggle back", wait=self.wait_fn(
            "(exp) => document.documentElement.getAttribute('data-theme') === exp", exp))

        # ---- Today: date navigation ----
        self.press("#date-prev", "Previous day", wait=self.wait_fn("() => /Yesterday/.test(document.querySelector('#date-label').textContent)"))
        self.press("#date-today", "Back to today", wait=self.wait_fn("() => /^Today/.test(document.querySelector('#date-label').textContent)"))
        self.press("#totals-details > summary", "Open all nutrient totals")

        # ---- Add: search, warnings before saving, save eaten ----
        self.press("#tab-add", "Add tab", wait=self.wait_fn("() => document.querySelectorAll('#food-results .row-btn').length > 0"))
        self.checks("Add", contrast=True)
        self.shot("add")
        F.locator("#food-search").fill("banana")
        F.wait_for_function("() => /banana/i.test(document.querySelector('#results-heading').textContent) && document.querySelectorAll('#food-results .row-btn').length > 0", timeout=5000)
        self.press("#food-results .row-btn", "Open food (banana)", wait=self.wait_fn("() => document.querySelector('#sheet-entry').open"))
        F.wait_for_timeout(200)
        w = F.evaluate("""() => { const box = document.querySelector('#entry-warnings'); const ws = [...box.querySelectorAll('.warning')];
          const body = document.querySelector('#sheet-entry .sheet-body').getBoundingClientRect();
          const foot = document.querySelector('#sheet-entry .sheet-foot').getBoundingClientRect();
          const first = ws[0] ? ws[0].getBoundingClientRect() : null;
          return { n: ws.length, levels: ws.map(x => x.className), text: ws.map(x => x.textContent.trim()).slice(0, 3),
                   firstTop: first && first.top, bodyBottom: body.bottom, footTop: foot.top, cta: document.querySelector('#entry-save').textContent.trim() }; }""")
        self.note(f"banana sheet: {w}")
        if not w["n"] or not any("level-over" in c or "level-caution" in c for c in w["levels"]):
            self.issue("add", "Food sheet shows no warning for banana before saving", str(w), "high")
        elif w["firstTop"] is not None and w["firstTop"] > w["footTop"] - 10:
            self.issue("add", "Warnings are below the fold of the food sheet (must scroll to see them before saving)",
                       f"first warning top {w['firstTop']:.0f}px, sheet footer top {w['footTop']:.0f}px", "low" if not self.phone else "medium")
        self.shot("add-sheet")
        self.checks("Add sheet (banana)", contrast=True)
        n_before = self.count("#meals .row-btn")
        self.press("#entry-save", "Save banana as eaten", wait=self.wait_fn(
            "() => !document.querySelector('#sheet-entry').open && !document.querySelector('#view-today').hidden && /Banana/i.test(document.querySelector('#meals').textContent)"))
        toast = self.text("#toast")
        if "Added" not in toast:
            self.issue("add", "No confirmation toast after saving a food", f"toast={toast!r}", "medium")
        self.shot("today-after-add")
        self.checks("Today after add (toast showing)", contrast=True)
        # planned
        self.press("#tab-add", "Add tab (2)", wait=self.wait_fn("() => document.querySelectorAll('#food-results .row-btn').length > 0"))
        F.locator("#food-search").fill("apple")
        F.wait_for_function("() => /apple/i.test(document.querySelector('#results-heading').textContent) && document.querySelectorAll('#food-results .row-btn').length > 0", timeout=5000)
        self.press("#food-results .row-btn", "Open food (apple)", wait=self.wait_fn("() => document.querySelector('#sheet-entry').open"))
        planned_before = self.count("#meals .row-btn.planned")
        self.press("label[for=status-planned]", "Choose Planned", wait=self.wait_fn("() => /^Plan for/.test(document.querySelector('#entry-save').textContent)"))
        self.press("#entry-save", "Save apple as planned", wait=self.wait_fn(
            "(n) => !document.querySelector('#sheet-entry').open && document.querySelectorAll('#meals .row-btn.planned').length > n", planned_before))
        if "Planned" not in self.text("#toast"):
            self.issue("add", "No 'Planned' toast after planning a food", self.text("#toast"), "low")

        # ---- Save as meal with Enter (implicit submission inside the sandbox) ----
        self.press("#meals .meal-actions .link-btn >> text=Save as meal", "Save as meal (breakfast)", wait=self.wait_fn("() => document.querySelector('#sheet-savemeal').open"))
        F.locator("#savemeal-name").fill("Enter-key meal")
        F.locator("#savemeal-name").press("Enter")
        try:
            F.wait_for_function("() => !document.querySelector('#sheet-savemeal').open", timeout=4000)
        except Exception:  # noqa: BLE001
            self.issue("forms", "Enter in the 'Save as meal' name field does not save", "sheet stayed open after Enter", "medium")
            F.locator("#sheet-savemeal [data-close]").first.click()

        # ---- Plan ----
        self.press("#tab-plan", "Plan tab", wait=self.wait_fn("() => document.querySelectorAll('#plan-grid .plan-day').length === 7 && document.querySelectorAll('#saved-meals li').length > 0"))
        self.shot("plan", full=True)
        self.shot("plan-viewport")
        self.checks("Plan", contrast=True)
        tomorrow_planned = F.evaluate("""() => { const b = [...document.querySelectorAll('.plan-day-open')].find(x => /^Tomorrow/.test(x.getAttribute('aria-label')));
            const m = b && b.getAttribute('aria-label').match(/(\\d+) planned/); return m ? Number(m[1]) : null; }""")
        self.press("#btn-copy-day", "Copy day…", wait=self.wait_fn("() => document.querySelector('#sheet-copy').open"))
        self.shot("copy-sheet")
        self.checks("Copy day sheet")
        self.press("#copy-save", "Copy (today → tomorrow)", wait=self.wait_fn("() => !document.querySelector('#sheet-copy').open && /Copied/.test(document.querySelector('#toast').textContent)"))
        F.wait_for_timeout(300)
        tomorrow_after = F.evaluate("""() => { const b = [...document.querySelectorAll('.plan-day-open')].find(x => /^Tomorrow/.test(x.getAttribute('aria-label')));
            const m = b && b.getAttribute('aria-label').match(/(\\d+) planned/); return m ? Number(m[1]) : null; }""")
        if tomorrow_planned is None or tomorrow_after is None or tomorrow_after <= tomorrow_planned:
            # tomorrow might be in next week (Sunday) — then it is not on the grid
            self.note(f"copy day: tomorrow planned {tomorrow_planned} -> {tomorrow_after}")
        # saved meal create
        self.press("#btn-new-meal", "New saved meal", wait=self.wait_fn("() => document.querySelector('#sheet-meal').open"))
        F.locator("#meal-name").fill("Sandbox test meal")
        F.locator("#meal-search").fill("rice")
        F.wait_for_function("() => document.querySelectorAll('#meal-search-results .row-btn').length > 0", timeout=4000)
        self.press("#meal-search-results .row-btn", "Add food to saved meal", wait=self.wait_fn("() => document.querySelectorAll('#meal-items .meal-item').length === 1"))
        self.shot("meal-editor")
        self.checks("Saved meal editor")
        self.press("#meal-save", "Save saved meal", wait=self.wait_fn(
            "() => !document.querySelector('#sheet-meal').open && /Sandbox test meal/.test(document.querySelector('#saved-meals').textContent)"))
        # apply
        li = "#saved-meals li.saved-meal:has-text('Sandbox test meal')"
        self.press(f"{li} .saved-meal-actions .btn", "Add saved meal to a day", wait=self.wait_fn("() => document.querySelector('#sheet-apply').open"))
        self.shot("apply-sheet")
        self.checks("Apply sheet")
        self.press("#apply-save", "Apply saved meal", wait=self.wait_fn("() => !document.querySelector('#sheet-apply').open && /(Planned|Added) Sandbox test meal/.test(document.querySelector('#toast').textContent)"))
        # delete with in-page confirmation
        self.press(f"{li} .danger-link", "Delete saved meal (ask)", wait=self.wait_fn("() => !!document.querySelector('#saved-meals .confirm-row')"))
        foc = F.evaluate("() => document.activeElement && document.activeElement.textContent.trim()")
        if foc != "Delete meal":
            self.issue("confirm", "Focus does not move to the confirm button", f"activeElement text {foc!r}", "low")
        self.shot("delete-confirm-meal")
        self.checks("Saved meal delete confirmation", contrast=True)
        self.press("#saved-meals .confirm-row .btn.danger-solid", "Confirm delete saved meal", wait=self.wait_fn(
            "() => !/Sandbox test meal/.test(document.querySelector('#saved-meals').textContent)"))
        # cancel path
        self.press("#saved-meals li.saved-meal .danger-link", "Delete saved meal (ask, then cancel)", wait=self.wait_fn("() => !!document.querySelector('#saved-meals .confirm-row')"))
        self.press("#saved-meals .confirm-row .btn.secondary", "Cancel delete", wait=self.wait_fn("() => !document.querySelector('#saved-meals .confirm-row')"))
        # shopping list
        n_shop = self.count("#shopping-list .shop-item")
        if not n_shop:
            self.issue("plan", "Shopping list empty although the week has planned foods", self.text("#shopping-list"), "medium")
        else:
            first_name = self.text("#shopping-list .shop-item .shop-name")
            self.press("#shopping-list .shop-item label", "Tick shopping item", wait=self.wait_fn("() => document.querySelector('#shopping-list .shop-item').classList.contains('done')"))
            self.shot("shopping")
            self.press("#week-next", "Next week", wait=self.wait_fn("() => /Next week/.test(document.querySelector('#week-label').textContent)"))
            self.press("#week-prev", "Back a week", wait=self.wait_fn("() => /This week/.test(document.querySelector('#week-label').textContent)"))
            F.wait_for_timeout(300)
            still = F.evaluate("(n) => { const li = [...document.querySelectorAll('#shopping-list .shop-item')].find(x => x.querySelector('.shop-name').textContent === n); return !!(li && li.querySelector('input').checked); }", first_name)
            if not still:
                st = F.evaluate("(() => { try { localStorage.length; return 'ok'; } catch (e) { return e.name; } })()")
                self.issue("plan", "Shopping-list ticks are lost when the Plan view reloads (storage unavailable)",
                           f"ticked '{first_name}', went to next week and back: unticked. storage={st}. "
                           "The hint says 'Checks are kept only on this device'.", "medium")
            if self.visible("#shopping-clear"):
                self.press("#shopping-clear", "Clear checks", wait=self.wait_fn("() => !document.querySelector('#shopping-list .shop-item.done')"))
        # plan day → Today
        self.press(".plan-day.today .plan-day-open", "Open today from the Plan grid", wait=self.wait_fn("() => !document.querySelector('#view-today').hidden"))

        # ---- Trends ----
        self.press("#tab-trends", "Trends tab", wait=self.wait_fn("() => document.querySelectorAll('#charts .chart-card').length > 0 && document.querySelector('#period-body .period-row')"))
        self.shot("trends", full=True)
        self.shot("trends-viewport")
        self.checks("Trends 14 d", contrast=True)
        for d in (7, 14, 30):  # 14 is the default: 7 first so that every button changes something
            self.press(f".seg[data-days='{d}']", f"Trends {d} days", wait=self.wait_fn(
                "(d) => document.querySelector('#trends-title').textContent === `Last ${d} days` && document.querySelector('#charts .chart-card svg').querySelectorAll('.hit').length === d", d))
            pressed = F.evaluate("(d) => document.querySelector(`.seg[data-days='${d}']`).getAttribute('aria-pressed')", d)
            if pressed != "true":
                self.issue("trends", f"{d} d button not marked pressed", f"aria-pressed={pressed}", "low")
            self.checks(f"Trends {d} d")
        self.shot("trends-30", full=True)
        # chart bar tap/hover
        hit = F.locator("#charts .chart-card .hit").nth(25)
        hit.scroll_into_view_if_needed()
        if self.phone:
            hit.tap()
        else:
            hit.hover()
        F.wait_for_timeout(300)
        tip = F.evaluate("() => { const t = document.querySelector('#chart-tip'); return { hidden: t.hidden, text: t.textContent }; }")
        if tip["hidden"]:
            self.issue("trends", "Tapping a chart bar shows no value" if self.phone else "Hovering a chart bar shows no tooltip",
                       f"#chart-tip hidden after {'tap' if self.phone else 'hover'} on a bar", "low")
        else:
            self.shot("chart-tip")
        page_tip_check = F.evaluate("() => { const t = document.querySelector('#chart-tip'); if (t.hidden) return null; const r = t.getBoundingClientRect(); return [r.left, r.right, innerWidth]; }")
        if page_tip_check and (page_tip_check[0] < 0 or page_tip_check[1] > page_tip_check[2]):
            self.issue("trends", "Chart tooltip outside the viewport", str(page_tip_check), "low")
        F.evaluate("() => { const t = document.querySelector('#chart-tip'); t.hidden = true; }")
        self.press("#charts .chart-card details > summary", "Show chart as table")
        # export CSV sheet
        self.press("#export-csv", "Export CSV", wait=self.wait_fn("() => document.querySelector('#sheet-csv').open && document.querySelector('#csv-text').value.length > 0"))
        csv = F.evaluate("() => ({ sub: document.querySelector('#sheet-csv-sub').textContent, head: document.querySelector('#csv-text').value.split(/\\r?\\n/)[0], rows: document.querySelector('#csv-text').value.split(/\\r?\\n/).filter(Boolean).length - 1, len: document.querySelector('#csv-text').value.length })")
        self.note(f"csv: {csv}")
        if not csv["head"].startswith("id,date,meal,status"):
            self.issue("trends", "CSV sheet header unexpected", csv["head"][:120], "high")
        m = re.search(r"(\d+) entr", csv["sub"])
        if not m or int(m.group(1)) != csv["rows"]:
            self.issue("trends", "CSV sheet entry count does not match the rows", str(csv), "medium")
        self.shot("csv")
        self.checks("CSV sheet", contrast=True)
        # clipboard: write a sentinel from the host side first
        sentinel = "SENTINEL-" + self.name
        self.set_clipboard(sentinel)
        self.press("#csv-copy", "Copy CSV", wait=self.wait_fn("() => document.querySelector('#csv-status').textContent.trim().length > 0"))
        status = self.text("#csv-status")
        clip = self.get_clipboard()
        full_csv = F.evaluate("() => document.querySelector('#csv-text').value")
        sel = F.evaluate("() => { const t = document.querySelector('#csv-text'); return [t.selectionStart, t.selectionEnd, t.value.length, document.activeElement === t]; }")
        self.note(f"copy csv: status={status!r} clipboard={'= csv' if clip == full_csv else (clip or '')[:40]!r} selection={sel}")
        if "copied" in status.lower() and clip is not None and clip != full_csv and clip.replace("\r\n", "\n") != full_csv.replace("\r\n", "\n"):
            self.issue("trends", "Copy CSV says 'copied' but the clipboard does not hold the CSV",
                       f"status {status!r}; clipboard starts {clip[:60]!r}", "high")
        if "copied" not in status.lower() and not (sel[0] == 0 and sel[1] == sel[2] and sel[3]):
            self.issue("trends", "Copy CSV fallback did not select the text", f"status {status!r}, selection {sel}", "medium")
        self.shot("csv-copied")
        self.press("#sheet-csv .sheet-foot [data-close]", "Close CSV sheet", wait=self.wait_fn("() => !document.querySelector('#sheet-csv').open"))

        # ---- Meal guidance and barcodes (v0.3): What fits now, a recorded barcode, Plan the rest, Treating a low ----
        self.press("#tab-add", "Add tab (What fits now)", wait=self.wait_fn("() => !document.querySelector('#view-add').hidden"))
        self.press("#guidance-fits-meal label[for=gfm-dinner]", "What fits dinner",
                   wait=self.wait_fn("() => document.querySelectorAll('#guidance-fits-body .g-food').length > 0"))
        self.shot("what-fits")
        self.checks("What fits now", contrast=True)
        self.press("#btn-scan", "Scan a barcode", wait=self.wait_fn("() => document.querySelector('#sheet-scan').open"))
        self.F.locator("#scan-code").fill("3017624010701")
        self.press("#scan-go", "Look up a recorded demo barcode",
                   wait=self.wait_fn("() => document.querySelector('#sheet-entry').open || /Open Food Facts/.test(document.querySelector('#scan-result').textContent)"))
        if not self.F.evaluate("document.querySelector('#sheet-entry').open"):
            self.shot("scan-consent")
            self.checks("Scan: the Open Food Facts agreement", contrast=True)
            self.press("#scan-result button.primary", "Agree and look up", wait=self.wait_fn("() => document.querySelector('#sheet-entry').open"))
        prov = self.text("#sheet-entry-provenance")
        if "Open Food Facts contributors, ODbL" not in prov:
            self.issue("barcode", "The scanned product does not show its ODbL attribution", prov[:200], "high")
        self.shot("scan-entry")
        self.checks("Entry sheet for a scanned product", contrast=True)
        self.press("#sheet-entry [data-close]", "Close the entry sheet", nth=0, wait=self.wait_fn("() => !document.querySelector('#sheet-entry').open"))
        self.press("#tab-today", "Today tab (Meal ideas)", wait=self.wait_fn("() => !!document.querySelector('#guidance-today-actions button')"))
        self.press("#guidance-today-actions button:has-text('Plan the rest of my day')", "Plan the rest of my day",
                   wait=self.wait_fn("() => document.querySelector('#sheet-guidance').open && !!document.querySelector('#g-plan-use')"))
        self.shot("plan-sheet")
        self.checks("Plan the rest of my day", contrast=True)
        self.press("#sheet-guidance [data-close]", "Close the plan", nth=0, wait=self.wait_fn("() => !document.querySelector('#sheet-guidance').open"))
        self.press("#guidance-today-actions button:has-text('Treating a low')", "Treating a low",
                   wait=self.wait_fn("() => document.querySelector('#sheet-guidance').open && /Treating a low/.test(document.querySelector('#sheet-guidance').textContent)"))
        self.shot("treating-a-low")
        self.checks("Treating a low", contrast=True)
        self.press("#sheet-guidance [data-close]", "Close Treating a low", nth=0, wait=self.wait_fn("() => !document.querySelector('#sheet-guidance').open"))

        # ---- Profile ----
        self.press("#tab-profile", "Profile tab", wait=self.wait_fn("() => document.querySelector('#pf-weight').value === '70'"))
        self.shot("profile", full=True)
        self.shot("profile-viewport")
        self.checks("Profile", contrast=True)
        self.press("#btn-suggest", "Suggest targets", wait=self.wait_fn("() => !document.querySelector('#suggest-notes').hidden"))
        self.shot("profile-suggest")
        self.press("#suggest-notes details.why > summary", "Why this number? (first target)", nth=0,
                   wait=self.wait_fn("() => document.querySelector('#suggest-notes details.why').open"))
        self.checks("Profile (suggestion explained)", contrast=True)

        # ---- Lab results (note 05 §4.8): entry with the conversion echo, what it changed, banner, delete ----
        self.press("#pf-open-labs", "Lab results", wait=self.wait_fn("() => !document.querySelector('#view-labs').hidden && document.querySelectorAll('#labs-history .lab-row').length > 0"))
        self.shot("labs", full=True)
        self.checks("Lab results", contrast=True)
        F.locator("#lab-analyte").select_option("phosphate")
        F.locator("#lab-unit").select_option("mmol/L")
        F.locator("#lab-value").fill("1.94")
        echo = self.text("#lab-echo")
        if "1.94 mmol/L = 6.0 mg/dL" not in echo:
            self.issue("labs", "The conversion is not echoed before saving", f"echo {echo!r}", "high")
        self.press("#lab-save", "Save phosphate result", wait=self.wait_fn("() => !document.querySelector('#labs-review').hidden"))
        self.shot("labs-review")
        self.checks("Lab results (what it changed)", contrast=True)
        F.locator("#lab-analyte").select_option("potassium")
        F.locator("#lab-value").fill("6.6")
        self.press("#lab-save", "Save potassium 6.6", wait=self.wait_fn("() => !!document.querySelector('#labs-alert .lab-alert.level-emergency')"))
        self.shot("labs-alert")
        self.checks("Lab results (emergency banner)", contrast=True)
        self.press("#labs-history .labs-group[aria-label='Potassium'] .lab-row-actions button", "Delete potassium result (ask)", nth=0,
                   wait=self.wait_fn("() => !!document.querySelector('#labs-history .confirm-row')"))
        self.press("#labs-history .confirm-row .btn.danger-solid", "Confirm delete result",
                   wait=self.wait_fn("() => !document.querySelector('#labs-alert .lab-alert.level-emergency')"))
        self.press("#labs-back", "Back to Profile", wait=self.wait_fn("() => !document.querySelector('#view-profile').hidden && document.querySelector('#pf-weight').value === '70'"))
        F.locator("#pf-dialysis").select_option("hemodialysis")
        F.wait_for_function("() => !document.querySelector('#pf-dialysis-days-field').hidden", timeout=3000)
        for i in (0, 2, 4):
            self.press(f"label[for=pf-dd-{i}]", f"Dialysis day {i}", wait=self.wait_fn("(i) => document.querySelector(`#pf-dd-${i}`).checked", i))
        self.shot("profile-hd")
        self.checks("Profile (hemodialysis days)", contrast=True)
        self.press("#btn-save-profile", "Save profile", wait=self.wait_fn("() => /Profile saved/.test(document.querySelector('#toast').textContent)"))
        self.press("#tab-today", "Today tab (after hemodialysis)", wait=self.wait_fn(
            "() => !!document.querySelector('#week-strip-body .interdialytic') && /Since last dialysis/.test(document.querySelector('#week-strip-body').textContent)"))
        F.locator("#week-strip").scroll_into_view_if_needed()
        F.wait_for_timeout(200)
        self.shot("today-hd")
        self.shot("today-hd-full", full=True)
        self.checks("Today (since last dialysis)", contrast=True)

        # ---- delete an entry with the in-page confirmation ----
        self.press("#meals .row-btn:has-text('Banana')", "Open banana entry", wait=self.wait_fn("() => document.querySelector('#sheet-entry').open && document.querySelector('#sheet-entry').dataset.mode === 'edit'"))
        self.press("#entry-delete", "Delete entry (ask)", wait=self.wait_fn("() => !!document.querySelector('#sheet-entry .confirm-row')"))
        conf = F.evaluate("""() => { const r = document.querySelector('#sheet-entry .confirm-row'); const rr = r.getBoundingClientRect();
          const foot = document.querySelector('#sheet-entry .sheet-foot:not(.confirm-row)');
          return { msg: r.querySelector('.confirm-msg').textContent, footHidden: foot.hidden, top: rr.top, bottom: rr.bottom, ih: innerHeight, focus: document.activeElement.textContent.trim() }; }""")
        self.note(f"entry delete confirm: {conf}")
        if conf["bottom"] > conf["ih"] + 1:
            self.issue("confirm", "Entry delete confirmation extends below the viewport", str(conf), "medium")
        self.shot("delete-confirm-entry")
        self.checks("Entry delete confirmation", contrast=True)
        F.locator("#sheet-entry .confirm-row").press("Escape")
        F.wait_for_timeout(200)
        esc = F.evaluate("() => ({ open: document.querySelector('#sheet-entry').open, confirm: !!document.querySelector('#sheet-entry .confirm-row') })")
        if esc["confirm"]:
            self.issue("confirm", "Escape does not dismiss the in-page confirmation", str(esc), "low")
        if not esc["open"]:
            # Escape closed the whole sheet; reopen to finish the delete
            self.press("#meals .row-btn:has-text('Banana')", "Re-open banana entry", wait=self.wait_fn("() => document.querySelector('#sheet-entry').open"))
        self.press("#entry-delete", "Delete entry (ask again)", wait=self.wait_fn("() => !!document.querySelector('#sheet-entry .confirm-row')"))
        self.press("#sheet-entry .confirm-row .btn.danger-solid", "Confirm delete entry", wait=self.wait_fn(
            "() => !document.querySelector('#sheet-entry').open && !/Banana/.test(document.querySelector('#meals').textContent)"))

        # ---- dismiss the preview banner ----
        F.evaluate("() => window.scrollTo(0, 0)")
        self.press("#preview-banner-close", "Dismiss preview banner", wait=self.wait_fn("() => document.querySelector('#preview-banner').hidden"))
        self.shot("banner-dismissed")
        self.checks("After banner dismissed")

        # ---- Settings (M1 sign-in + settings): gear, invite link, own key, demo sign-out / sign-in ----
        self.settings_walk()

        # ---- host switches data-theme while open ----
        other = "light" if exp == "dark" else "dark"
        F.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", other)
        F.wait_for_timeout(200)
        lab = F.locator("#theme-toggle").get_attribute("aria-label")
        if lab != ("Switch to light theme" if other == "dark" else "Switch to dark theme"):
            self.issue("theme", "Theme toggle label stale after the host changes data-theme", f"aria-label {lab!r} with data-theme={other}", "low")
        bg = F.evaluate("() => getComputedStyle(document.body).backgroundColor")
        if bg != {"light": "rgb(244, 245, 247)", "dark": "rgb(17, 20, 23)"}[other]:
            self.issue("theme", "Host data-theme switch not applied", f"body bg {bg} after data-theme={other}", "medium")

    def settings_walk(self):
        F = self.F
        F.evaluate("() => window.scrollTo(0, 0)")
        self.press("#settings-open", "Header gear (Settings)", wait=self.wait_fn(
            "() => !document.querySelector('#view-settings').hidden && !!document.querySelector('#set-account-body .kv') && !!document.querySelector('#set-people .user-list')"))
        F.wait_for_timeout(500)
        self.shot("settings")
        self.shot("settings-full", full=True)
        self.checks("Settings", contrast=True)
        who = self.text("#settings-who")
        if "sam" not in who:
            self.issue("settings", "Settings does not say who is signed in", who, "medium")
        users = self.text("#set-people .user-list")
        if "Sam" not in users or "Alex" not in users:
            self.issue("settings", "Demo admin list should show Sam and the sample invited user", users[:200], "medium")
        # invite link + Copy
        self.press("#set-invite-create", "Create invite link", wait=self.wait_fn("() => !!document.querySelector('#set-invite .link-input')"))
        link = F.evaluate("() => document.querySelector('#set-invite .link-input').value")
        if "/#/invite/" not in link or "example" not in link:
            self.issue("settings", "Demo invite link is not an obvious example", link, "medium")
        if "does not open anything" not in self.text("#set-invite .link-box"):
            self.issue("settings", "Demo invite link does not say it is an example", self.text("#set-invite .link-box")[:200], "low")
        self.press("#set-invite .link-box button", "Copy invite link", wait=self.wait_fn("() => document.querySelector('#toast').classList.contains('show')"))
        self.note(f"copy link toast: {self.text('#toast')!r}")
        self.shot("settings-invite")
        self.checks("Settings invite link", contrast=True)
        # own key (write-only)
        key = "DemoKey0123456789abcdefWXYZ"
        self.press("#set-food-body .key-actions button", "Add your own key", wait=self.wait_fn("() => !document.querySelector('#set-food-body .key-editor').hidden"))
        F.locator("#set-food-body .key-input").fill(key)
        self.press("#set-food-body .key-editor-actions .btn.secondary", "Save own key", wait=self.wait_fn(
            "() => /ends in WXYZ/.test(document.querySelector('#set-food-body .key-state').textContent)"))
        leak = F.evaluate("(k) => document.documentElement.outerHTML.includes(k) || [...document.querySelectorAll('input')].some((i) => i.value.includes(k))", key)
        if leak:
            self.issue("settings", "The saved key is still in the page", "found in DOM or an input", "high")
        self.shot("settings-key")
        # export (demo message), delete refused for the only admin
        self.press("#set-export", "Export my data (demo)", wait=self.wait_fn("() => /preview|nothing to download/.test(document.querySelector('#set-export-msg').textContent)"))
        self.press("#set-delete summary", "Open Delete my account", wait=self.wait_fn("() => document.querySelector('#set-delete').open"))
        F.locator("#set-delete-password").fill("any password here")
        F.locator("#set-delete-confirm").fill("DELETE")
        self.press("#set-delete-save", "Delete my account (demo, only admin)", wait=self.wait_fn(
            "() => /only admin/.test(document.querySelector('#set-delete .form-error').textContent)"))
        self.shot("settings-delete-refused")
        # disable the sample user with the in-page confirmation
        self.press("#user-2 > details.user-manage > summary", "Manage Alex", wait=self.wait_fn("() => document.querySelector('#user-2 details.user-manage').open"))
        self.press("#user-2 .btn.danger", "Disable Alex (ask)", wait=self.wait_fn("() => !!document.querySelector('#user-2 .confirm-row')"))
        self.press("#user-2 .confirm-row .btn.danger-solid", "Disable Alex (confirm)", wait=self.wait_fn(
            "() => /disabled/i.test(document.querySelector('#user-2 .user-badges').textContent)"))
        # sign out and back in (demo)
        F.locator("#set-signout").scroll_into_view_if_needed()
        self.press("#set-signout", "Sign out (demo)", wait=self.wait_fn("() => !document.querySelector('#form-login').hidden && !document.querySelector('#login-demo').hidden"))
        self.shot("signin")
        self.checks("Sign-in screen", contrast=True)
        if self.visible(".tabs"):
            self.issue("auth", "Tabs still visible on the sign-in screen", "", "medium")
        F.locator("#login-username").fill("sam")
        F.locator("#login-password").fill("short")
        self.press("#login-submit", "Sign in with a short password (demo)", wait=self.wait_fn("() => /incorrect/.test(document.querySelector('#auth-error').textContent)"))
        F.locator("#login-password").fill("any long demo password")
        self.press("#login-submit", "Sign in (demo)", wait=self.wait_fn("() => document.querySelector('#view-auth').hidden && !document.querySelector('#view-settings').hidden"))
        self.press("#tab-today", "Today after signing in again", wait=self.wait_fn("() => !!document.querySelector('#status-bars .stat')"))

    # -- clipboard helpers (host side) --
    def set_clipboard(self, text):
        try:
            self.page.main_frame.evaluate("(t) => navigator.clipboard.writeText(t)", text)
        except Exception as e:  # noqa: BLE001
            self.note(f"set clipboard failed: {str(e)[:100]}")

    def get_clipboard(self):
        try:
            return self.page.main_frame.evaluate("() => navigator.clipboard.readText()")
        except Exception as e:  # noqa: BLE001
            self.note(f"read clipboard failed: {str(e)[:100]}")
            return None


# ---------------------------------------------------------------------------
# Sweep: every visible button in every view, clicked on a fresh load
# ---------------------------------------------------------------------------
LIST_BUTTONS_JS = r"""
() => {
  const vis = (el) => el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true });
  return [...document.querySelectorAll('main button, main a[href], main summary, main [role=button], header button, .preview-banner button')]
    .filter((el) => vis(el) && !el.disabled && !el.closest('.tabs') && el.getAttribute('aria-pressed') !== 'true')
    .map((el, i) => { el.setAttribute('data-sweep', String(i)); return (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 50); });
}
"""


def sweep(port, ctx_kind, vp, scheme, host_theme):
    from playwright.sync_api import sync_playwright
    run = Run(port, ctx_kind, vp, scheme, host_theme)
    run.name = "sweep-" + run.name
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        opts = dict(color_scheme=scheme)
        if run.phone:
            opts.update(viewport={"width": 375, "height": 812}, device_scale_factor=1, is_mobile=True, has_touch=True)
        else:
            opts.update(viewport={"width": 1280, "height": 800})
        ctx = browser.new_context(**opts)
        page = ctx.new_page()
        run.page = page
        page.on("pageerror", lambda e: run.console.append(f"pageerror: {e}"))
        page.on("console", lambda m: run.console.append(f"{m.type}: {m.text[:300]}") if m.type == "error" else None)
        page.on("dialog", lambda d: (run.console.append(f"dialog: {d.type}"), d.dismiss()))
        clicked = 0
        try:
            for view in ("today", "add", "plan", "trends", "profile", "labs", "settings"):
                run.load(page, view)
                page.wait_for_timeout(400)
                labels = run.F.evaluate(LIST_BUTTONS_JS)
                for i, label in enumerate(labels):
                    if i:
                        run.load(page, view)
                        page.wait_for_timeout(350)
                        run.F.evaluate(LIST_BUTTONS_JS)
                    loc = run.F.locator(f"[data-sweep='{i}']")
                    if not loc.count():
                        continue
                    try:
                        loc.evaluate("(el) => el.scrollIntoView({ block: 'center' })")
                        page.wait_for_timeout(150)
                        before, fb = run.snap(), run.fp()
                        try:
                            if run.phone:
                                loc.tap(timeout=3000)
                            else:
                                loc.click(timeout=3000)
                        except Exception:  # noqa: BLE001  Playwright hit-test quirk in the sandboxed frame: raw event
                            box = loc.bounding_box()
                            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                            (page.touchscreen.tap if run.phone else page.mouse.click)(cx, cy)
                        page.wait_for_timeout(500)
                        after, fa = run.snap(), run.fp()
                        clicked += 1
                        if before == after:
                            run.issue("silent-noop", f"[{view}] '{label}' does nothing visible",
                                      f"sweep click on a fresh load: screenshot identical; DOM {'changed' if fa != fb else 'unchanged'}", "medium")
                    except Exception as e:  # noqa: BLE001
                        run.note(f"sweep [{view}] {label}: {str(e).splitlines()[0][:120]}")
        finally:
            ctx.close()
            browser.close()
    run.note(f"sweep clicked {clicked} controls")
    for c in run.console:
        run.issue("console", "Console error during sweep", c, "medium")
    return {"name": run.name, "issues": run.issues, "notes": run.notes, "console": run.console, "shots": []}


def probes(port):
    """Targeted checks outside the main walk (iframe, phone unless noted)."""
    from playwright.sync_api import sync_playwright
    out = {"name": "probes", "issues": [], "notes": [], "console": [], "shots": []}

    def issue(area, title, evidence, severity):
        out["issues"].append({"config": "probes", "area": area, "title": title, "evidence": evidence, "severity": severity})

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        try:
            for vp in ("phone", "desktop"):
                r = Run(port, "iframe", vp, "light", "none")
                r.name = f"probe-{vp}"
                opts = dict(color_scheme="light")
                if r.phone:
                    opts.update(viewport={"width": 375, "height": 812}, device_scale_factor=2, is_mobile=True, has_touch=True)
                else:
                    opts.update(viewport={"width": 1280, "height": 800})
                ctx = browser.new_context(**opts)
                page = ctx.new_page()
                r.page = page
                page.on("console", lambda m: out["console"].append(f"{m.type}: {m.text[:300]}") if m.type == "error" else None)
                page.on("pageerror", lambda e: out["console"].append(f"pageerror: {e}"))
                # 1. Suggest targets after switching to hemodialysis WITHOUT saving
                r.load(page, "profile")
                F = r.F
                F.wait_for_function("() => document.querySelector('#pf-weight').value === '70'", timeout=5000)
                F.locator("#pf-dialysis").select_option("hemodialysis")
                F.locator("#btn-suggest").click()
                page.wait_for_timeout(500)
                res = F.evaluate("""() => ({ notesHidden: document.querySelector('#suggest-notes').hidden,
                    notes: document.querySelector('#suggest-notes').textContent.slice(0, 600),
                    fluid: document.querySelector('#tg-fluid_ml').value, pmin: document.querySelector('#tg-protein_min').value,
                    pmax: document.querySelector('#tg-protein_max').value, k: document.querySelector('#tg-potassium_mg').value,
                    dialysis: document.querySelector('#pf-dialysis').value, toast: document.querySelector('#toast').textContent })""")
                out["notes"].append(f"[{vp}] suggest after unsaved switch to hemodialysis: {res}")
                if not res["notesHidden"] and res["fluid"] == "" and "hemodialysis" not in res["notes"]:
                    issue("profile", "Suggest targets silently ignores an unsaved dialysis change",
                          f"form shows Dialysis=Hemodialysis (not saved yet); Suggest filled non-dialysis targets: protein {res['pmin']}-{res['pmax']} g, "
                          f"potassium {res['k']} mg, fluid '{res['fluid']}' (blank); notes: {res['notes'][:200]!r}; toast {res['toast']!r}. "
                          "It only refuses when weight/height differ from the saved profile.", "medium")
                if vp == "phone":
                    page.screenshot(path=str(SHOTS / "probe-suggest-unsaved-hd.png"), scale="css")
                    out["shots"].append(str(SHOTS / "probe-suggest-unsaved-hd.png"))
                # 2. Escape closes a sheet and focus returns to the trigger
                r.load(page, "add")
                F = r.F
                F.wait_for_function("() => document.querySelectorAll('#food-results .row-btn').length > 0", timeout=5000)
                F.locator("#food-results .row-btn").first.click()
                F.wait_for_function("() => document.querySelector('#sheet-entry').open", timeout=3000)
                page.wait_for_timeout(100)
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                esc = F.evaluate("() => ({ open: document.querySelector('#sheet-entry').open, focus: document.activeElement && document.activeElement.className })")
                if esc["open"]:
                    issue("dialogs", "Escape does not close the food sheet", str(esc), "low")
                # 3. Today: the week strip with the since-last-dialysis block (element shot)
                r.load(page, "profile")
                F = r.F
                F.wait_for_function("() => document.querySelector('#pf-weight').value === '70'", timeout=5000)
                F.locator("#pf-dialysis").select_option("hemodialysis")
                for i in (0, 2, 4):
                    F.locator(f"label[for=pf-dd-{i}]").click()
                F.locator("#btn-save-profile").click()
                F.wait_for_function("() => /Profile saved/.test(document.querySelector('#toast').textContent)", timeout=3000)
                # (fixer) after a stage/dialysis change the Profile must say the targets were not changed and offer the suggestion
                stale = F.evaluate("() => ({ shown: !document.querySelector('#targets-stale').hidden, text: (document.querySelector('#targets-stale-msg') || {}).textContent || '' })")
                out["notes"].append(f"[{vp}] notice after saving hemodialysis: {stale}")
                if not stale["shown"] or "hemodialysis" not in stale["text"]:
                    issue("profile", "No notice that the targets were set for the previous stage/dialysis setting", str(stale), "high")
                F.locator("#tab-today").click()
                F.wait_for_function("() => !!document.querySelector('#week-strip-body .interdialytic')", timeout=5000)
                pth = SHOTS / f"probe-{vp}-week-strip-hd.png"
                F.locator("#week-strip").screenshot(path=str(pth), scale="css")
                out["shots"].append(str(pth))
                inter = F.evaluate("() => document.querySelector('#week-strip-body .interdialytic').textContent")
                out["notes"].append(f"[{vp}] since-last-dialysis block: {inter}")
                rows = F.evaluate("() => [...document.querySelectorAll('#week-strip-body .interdialytic .inter-label')].map((x) => x.textContent)")
                if "Fluid" not in rows:
                    issue("profile", "After switching to hemodialysis the targets stay non-dialysis: no Fluid in 'Since last dialysis', wrong limits",
                          f"Profile: Dialysis=Hemodialysis, Mon/Wed/Fri, Save profile (the preview banner's own instruction). Today's block rows: {rows}; "
                          f"text {inter[:160]!r}. Targets are still the stage-4 suggestion (potassium 3000 mg, protein 42-56 g, fluid untracked) "
                          "although hemodialysis suggests potassium 2500, protein 70-84 g, fluid 1500 mL; nothing tells the person to re-suggest.", "high")
                # dialysis badges on the Plan grid
                F.locator("#tab-plan").click()
                F.wait_for_function("() => document.querySelectorAll('#plan-grid .plan-day').length === 7", timeout=5000)
                badges = F.evaluate("() => document.querySelectorAll('#plan-grid .badge.dialysis').length")
                out["notes"].append(f"[{vp}] plan dialysis badges after HD save: {badges}")
                if badges != 3:
                    issue("plan", "Plan grid does not mark the three dialysis days", f"{badges} .badge.dialysis", "medium")
                # weekday chips: nested bordered box (".wd-check span" also matches the inner spans)
                F.locator("#tab-profile").click()
                F.wait_for_function("() => !document.querySelector('#pf-dialysis-days-field').hidden", timeout=5000)
                nested = F.evaluate("""() => { const outer = document.querySelector('label[for=pf-dd-0] > span'); const inner = outer.querySelector('span[aria-hidden]');
                    const a = getComputedStyle(outer), b = getComputedStyle(inner); const c = document.querySelector('#pf-dd-0').checked;
                    return { checked: c, outerBorder: a.borderTopWidth + ' ' + a.borderTopColor, outerBg: a.backgroundColor, outerColor: a.color,
                             innerBorder: b.borderTopWidth + ' ' + b.borderTopColor, innerBg: b.backgroundColor, innerColor: b.color,
                             innerSize: Math.round(inner.getBoundingClientRect().width) + 'x' + Math.round(inner.getBoundingClientRect().height) }; }""")
                if nested["innerBorder"].startswith("1px"):
                    pth = SHOTS / f"probe-{vp}-weekday-checks.png"
                    F.locator("#pf-dialysis-days-field").screenshot(path=str(pth), scale="css")
                    out["shots"].append(str(pth))
                    issue("profile", "Dialysis-day chips render a box inside a box; the selected state barely shows",
                          f"'.wd-check span' also styles the inner label span: {nested}", "medium")
                # re-suggest after saving hemodialysis, then the block gains Fluid (the working path)
                F.locator("#btn-suggest").click()
                F.wait_for_function("() => !document.querySelector('#suggest-notes').hidden", timeout=3000)
                fl = F.evaluate("() => [document.querySelector('#tg-fluid_ml').value, document.querySelector('#tg-potassium_mg').value]")
                out["notes"].append(f"[{vp}] suggest after saving hemodialysis: fluid {fl[0]}, potassium {fl[1]}")
                F.locator("#tab-today").click()
                # trends interdialytic block too
                F.locator("#tab-trends").click()
                F.wait_for_function("() => !document.querySelector('#period-interdialytic').hidden", timeout=5000)
                pth = SHOTS / f"probe-{vp}-period-hd.png"
                F.locator("#period-summary").screenshot(path=str(pth), scale="css")
                out["shots"].append(str(pth))
                ctx.close()
            # 4. contrast in states the walk does not scan: ticked shopping item, last week's past
            #    days, a hovered planned row (light and dark, top level desktop)
            for scheme in ("light", "dark"):
                ctx = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme=scheme)
                page = ctx.new_page()
                r = Run(port, "top", "desktop", scheme, "none")
                r.page = page
                r.load(page, "plan")
                F = r.F
                F.wait_for_function("() => document.querySelectorAll('#shopping-list .shop-item').length > 0", timeout=5000)
                F.locator("#shopping-list .shop-item label").first.click()
                F.locator("#shopping-list .shop-item").first.hover()
                low = F.evaluate(CHECKS_JS, {"taps": False, "contrast": True})["lowContrast"]
                F.locator("#week-prev").click()
                F.wait_for_function("() => /Last week/.test(document.querySelector('#week-label').textContent)", timeout=5000)
                page.wait_for_timeout(300)
                low += F.evaluate(CHECKS_JS, {"taps": False, "contrast": True})["lowContrast"]
                F.locator("#tab-today").click()
                F.wait_for_function("() => document.querySelectorAll('#meals .row-btn.planned').length > 0", timeout=5000)
                F.locator("#meals .row-btn.planned").first.hover()
                page.wait_for_timeout(200)
                low += F.evaluate(CHECKS_JS, {"taps": False, "contrast": True})["lowContrast"]
                if low:
                    issue("contrast", f"Text below 4.5:1 in extra states ({scheme})",
                          "; ".join(f"{x['el']} {x['fg']} on {x['bg']} = {x['ratio']}:1" for x in low[:8]), "low")
                ctx.close()
            # 5. desktop header: the tab icons must keep their 20 px size
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            r = Run(port, "iframe", "desktop", "light", "none")
            r.page = page
            r.load(page, "")
            icons = r.F.evaluate("""() => [...document.querySelectorAll('.tab')].map((t) => { const i = t.querySelector('.tab-icon').getBoundingClientRect();
                return [t.dataset.view, Math.round(i.width * 10) / 10, Math.round(i.height * 10) / 10]; })""")
            squashed = [x for x in icons if x[1] < x[2] - 0.5]
            if squashed:
                r.F.locator(".topbar").screenshot(path=str(SHOTS / "probe-desktop-topbar.png"))
                out["shots"].append(str(SHOTS / "probe-desktop-topbar.png"))
                issue("layout", "Desktop tab icons are squashed (svg shrinks in the flex row)",
                      "icon width x height at 1280 px: " + ", ".join(f"{v} {w}x{h}" for v, w, h in icons) + " (should be 20x20)", "low")
            ctx.close()
            # 6. 320 px wide phone (smallest common width) — overflow only
            r = Run(port, "iframe", "phone", "light", "none")
            ctx = browser.new_context(viewport={"width": 320, "height": 640}, is_mobile=True, has_touch=True, device_scale_factor=2)
            page = ctx.new_page()
            r.page = page
            for view in ("today", "add", "plan", "trends", "profile", "labs", "settings"):
                r.load(page, view)
                page.wait_for_timeout(500)
                c = r.F.evaluate(CHECKS_JS, {"taps": False, "contrast": False})
                if c["overflowX"] or c["offscreen"]:
                    issue("layout", f"320 px: overflow in {view}", f"scrollWidth {c['scrollWidth']}; {'; '.join(c['offscreen'][:5])}", "low")
            ctx.close()
        finally:
            browser.close()
    for c in out["console"]:
        issue("console", "Console error during probes", c, "medium")
    return out


def run_probes(args):
    return probes(*args)


def run_config(args):
    port, ctx_kind, vp, scheme, host_theme, placement = args
    from playwright.sync_api import sync_playwright
    r = Run(port, ctx_kind, vp, scheme, host_theme, placement)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        try:
            r.run(browser)
        finally:
            browser.close()
    return {"name": r.name, "issues": r.issues, "notes": r.notes, "console": r.console, "requests": r.requests,
            "shots": r.shots, "token_pairs": getattr(r, "token_pairs", None)}


def run_sweep(args):
    return sweep(*args)


def main():
    global OUT, FRAGMENT_PATH, SHOTS, RESULTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated config names, e.g. top-phone-light-none")
    ap.add_argument("--no-sweep", action="store_true")
    ap.add_argument("--no-walk", action="store_true")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=OUT, help=f"work directory for the fragment, results and screenshots (default {OUT})")
    ap.add_argument("--preview", type=Path, default=None, help="use this built fragment instead of building one")
    ap.add_argument("--port", type=int, default=0, help="port of the emulated host (default: any free port)")
    a = ap.parse_args()
    OUT = a.out.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    FRAGMENT_PATH, SHOTS, RESULTS = (a.preview.resolve() if a.preview else OUT / "preview.html"), OUT / "shots", OUT / "results.json"
    os.environ["KH_SANDBOX_OUT"] = str(OUT)
    os.environ["KH_SANDBOX_PREVIEW"] = str(FRAGMENT_PATH)
    if a.preview is None:
        subprocess.run([sys.executable, str(REPO / "scripts" / "build_preview.py"), "--out", str(FRAGMENT_PATH)], check=True)
    if not FRAGMENT_PATH.exists():
        sys.exit(f"{FRAGMENT_PATH} missing: python scripts/build_preview.py --out {FRAGMENT_PATH}")
    frag = FRAGMENT_PATH.read_text(encoding="utf-8")
    static = []
    if re.search(r"<(!doctype|html|head|body)[\s>]", frag, re.I):
        static.append({"config": "static", "area": "fragment", "title": "Skeleton tag in fragment", "evidence": "doctype/html/head/body found", "severity": "high"})
    if not frag.startswith("<title>"):
        static.append({"config": "static", "area": "fragment", "title": "Fragment does not start with <title>", "evidence": frag[:60], "severity": "medium"})
    size = len(frag.encode())
    if size > 16 * 1024 * 1024:
        static.append({"config": "static", "area": "fragment", "title": "Fragment over 16 MB", "evidence": str(size), "severity": "high"})
    ext = re.findall(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//[^"'\s>]+""", frag)
    if ext:
        static.append({"config": "static", "area": "fragment", "title": "External URL reference", "evidence": "; ".join(ext[:5]), "severity": "high"})
    SHOTS.mkdir(parents=True, exist_ok=True)
    server = Server(a.port).start()
    results = {"fragment_bytes": size, "static": static, "runs": [], "sweeps": [], "server_requests": None}
    try:
        configs = []
        for ctx_kind in ("top", "iframe"):
            for vp in ("phone", "desktop"):
                for scheme, host in (("light", "none"), ("dark", "none"), ("light", "dark"), ("dark", "light")):
                    configs.append((server.port, ctx_kind, vp, scheme, host, "body"))
        configs.append((server.port, "iframe", "phone", "light", "none", "head"))
        only = {x for x in a.only.split(",") if x}
        if only:
            configs = [c for c in configs if f"{c[1]}-{c[2]}-{c[3]}-{c[4]}" + ("-head" if c[5] == "head" else "") in only]
        sweeps = [] if a.no_sweep else [(server.port, "iframe", "phone", "light", "none"), (server.port, "iframe", "desktop", "dark", "none")]
        if a.no_walk:
            configs = []
        with mp.get_context("spawn").Pool(a.workers) as pool:
            jobs = [pool.apply_async(run_config, (c,)) for c in configs] + [pool.apply_async(run_sweep, (s,)) for s in sweeps]
            if not a.no_probes:
                jobs.append(pool.apply_async(run_probes, ((server.port,),)))
            for j in jobs:
                try:
                    res = j.get(timeout=1800)
                except Exception as e:  # noqa: BLE001
                    res = {"name": "job-error", "issues": [{"config": "harness", "area": "harness", "title": "job failed", "evidence": repr(e)[:800], "severity": "high"}],
                           "notes": [], "console": [], "shots": []}
                (results["sweeps"] if res["name"].startswith(("sweep-", "probes")) else results["runs"]).append(res)
                print(f"done {res['name']}: {len(res['issues'])} issues", flush=True)
        with server.lock:
            reqs = list(server.requests)
        odd = [r for r in reqs if not re.match(r"^/(page|outer)/(none|dark|light)(\?|$)", r["path"])]
        results["server_requests"] = {"total": len(reqs), "unexpected": odd}
        if odd:
            static.append({"config": "server", "area": "network", "title": "Server saw requests other than the documents",
                           "evidence": json.dumps(odd[:5]), "severity": "high"})
    finally:
        server.stop()
    RESULTS.write_text(json.dumps(results, indent=2))
    # summary
    allissues = static + [i for r in results["runs"] + results["sweeps"] for i in r["issues"]]
    groups: dict[tuple, list] = {}
    for i in allissues:
        groups.setdefault((i["severity"], i["area"], i["title"]), []).append(i)
    order = {"high": 0, "medium": 1, "low": 2}
    print(f"\nfragment {size:,} bytes; {len(results['runs'])} walks, {len(results['sweeps'])} sweeps; server requests {results['server_requests']['total']}, unexpected {len(results['server_requests']['unexpected'])}")
    for (sev, area, title), items in sorted(groups.items(), key=lambda kv: (order[kv[0][0]], kv[0][1], kv[0][2])):
        cfgs = sorted({x["config"] for x in items})
        print(f"[{sev}] {area}: {title}  ({len(items)}x; {', '.join(cfgs[:6])}{'…' if len(cfgs) > 6 else ''})")
        print(f"      e.g. {items[0]['evidence'][:400]}")
    print(f"\nresults: {RESULTS}\nshots: {SHOTS}")


if __name__ == "__main__":
    main()
