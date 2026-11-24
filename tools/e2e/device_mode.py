#!/usr/bin/env python3
"""The web app as the iPhone app packs it (design note 38, step 1: device mode) in Chromium.

    python tools/e2e/device_mode.py                    # no server: the copy is built and served statically
    python tools/e2e/device_mode.py --out /tmp/kh-device

Builds the iPhone app's copy (``scripts/build_preview.py --device``), serves it from a throw-away static server on localhost, and
stands in for the iPhone app's message handlers. At 375x812 light and 1280x800 dark, each in a fresh browser profile:

* there is no demo pill, no demo banner and no "Keep my data in this browser" button; the log starts empty with no sample person;
* the one person is not an admin, and Settings has no sign-out button and no signed-in devices list; This device says the data is
  kept on this iPhone and offers "Apple Health and server", which asks the app to open its settings;
* an entry is added, the page reloaded: the entry is still on Today; after the save the app was handed the safety copy, which holds it;
* This device → Your server: Sync now hands the new entry to the stand-in app once, and the section names the server and says
  that changes are sent too with a token both ways;
* the iPhone's own AI (step 5), with a stand-in for the app's model: Settings → AI features has one switch; once it is on, Add offers
  Describe a meal, which sends the server's cleaned data to the app and shows the matches and the server's notice; a low gets the
  Treating a low card and the model is not asked;
* no request to any other host, no console or page error (CSP violations included), no sideways scroll.
* paired with a token both ways (design note 39, steps 3 and 4; 375x812 light), with a stand-in for the server's gateway: This
  device says the token works both ways, Food data says the server's food services are used, Settings → AI features lists Describe
  a meal on the server's AI and offers "Use only this iPhone's AI"; Describe a meal goes to the server and its answer is shown with
  its food named by the phone's own id; with "Use only this iPhone's AI" on, the iPhone's model answers and the server is not asked.
* sync both ways (design note 39, steps 6 and 7; 375x812 light), with a stand-in for the change feed: Sync now brings an entry made
  on the server to Today; the phone's edit of an entry also changed on the server shows the conflict card with "Keep the saved one"
  and "Use mine"; "Use mine" sends the edit again on the server's version; Settings says it syncs both ways.

Nothing leaves the machine. Prints PASS / FAIL lines and writes ``<out>/report.json``; exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import khserver
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(tempfile.gettempdir()) / "kidney-health-e2e" / "device-mode"
RESULTS: list[dict] = []
# The app's side of sending to a server (step 4): a paired server whose POST /push/v1/sync takes every row it is sent.
STUB = ("window.__kh = { copies: [], phone: [], sync: [], ai: [] };"
        "window.__kh.answer = (text) => { const b = JSON.parse(text); window.__kh.sync.push(b);"
        " const n = (k) => (b[k] || []).length; const kinds = ['foods', 'entries', 'labs', 'symptoms', 'weights', 'readings'];"
        " const added = Object.fromEntries(kinds.map((k) => [k, n(k)])); const none = Object.fromEntries(kinds.map((k) => [k, 0]));"
        " return { ok: true, status: 200, json: JSON.stringify({ added, already_there: none, skipped: { food_not_found: 0, day_full: 0 } }) }; };"
        "window.webkit = { messageHandlers: { safetyCopy: { postMessage: (t) => window.__kh.copies.push(String(t)) },"
        " phone: { postMessage: (m) => window.__kh.phone.push(String(m)) },"
        " bridge: { postMessage: async (r) => r.kind === 'services' ? { ok: true, off: false, usda: false, scan: true }"
        " : r.kind === 'scanBarcode' ? { ok: true, code: '3017624010701', format: 'ean_13' }"
        " : r.kind === 'serverInfo' ? { ok: true, paired: true, server: 'food.example.org' }"
        " : r.kind === 'serverSyncCheck' ? { ok: true, status: 200, json: '{\"ok\": true}' }"
        " : r.kind === 'serverSync' ? window.__kh.answer(r.body)"
        " : r.kind === 'aiStatus' ? { ok: true, available: true, reason: null }"
        " : r.kind === 'ai' ? (window.__kh.ai.push(r), { ok: true, answer: { status: 'ok', items: ["
        "   { text: '2 eggs', search: 'egg', amount: 2, unit: 'serving' }] } })"
        " : { error: 'off_off', message: 'off' } } } };")


# Design note 39: the same app paired with a token both ways. The stand-in gateway answers GET /push/v1/about, the server's AI status
# (describe a meal available) and its parse-meal, whose match is a built-in food under the server's own id.
BOTH_WAYS = ("window.__kh = { copies: [], phone: [], api: [], ai: [] };"
             "window.__kh.status = { enabled: true, opted_in: true, available: true, reason: null, message: null, provider: { label: 'Home AI', host: 'ai.home.lan' },"
             " consent: { text: { host: 'ai.home.lan', skip_preview: true }, photos: null, chat: null, labs: null, voice: null }, routing: { mode: 'routed' },"
             " routes: { describe: { feature: 'describe', label: 'Describe a meal', available: true, consent: { host: 'ai.home.lan', skip_preview: true } } },"
             " features: { parse_meal: true }, daily_limit: null, remaining_today: null };"
             "window.__kh.parse = () => { const api = KH.mock.instance; const f = api._foods.find((x) => x.source === 'builtin' && /egg/i.test(x.name));"
             " const food = { ...api._foodView(f), id: 999999 }; return { status: 'ok', feature: 'parse_meal', provider: { label: 'Home AI' },"
             " items: [{ text: '2 eggs', search: 'egg', amount: 2, unit: 'serving', matches: [{ food, servings: 2 }] }], dropped: [],"
             " notice: 'Checked by your server. Nothing is logged until you add it.' }; };"
             "window.__kh.gateway = (r) => { window.__kh.api.push({ method: r.method, path: r.path });"
             " const reply = (json) => ({ ok: true, status: 200, json: JSON.stringify(json) });"
             " if (r.path === '/push/v1/about') return reply({ account: 'acct-1', api_version: 1 });"
             " if (r.path === '/push/v1/api/ai/status') return reply(window.__kh.status);"
             " if (r.path.startsWith('/push/v1/api/ai/parse-meal')) return reply(window.__kh.parse());"
             " return { ok: true, status: 404, json: '{\"detail\": \"Not Found\"}' }; };"
             "window.webkit = { messageHandlers: { safetyCopy: { postMessage: (t) => window.__kh.copies.push(String(t)) },"
             " phone: { postMessage: (m) => window.__kh.phone.push(String(m)) },"
             " bridge: { postMessage: async (r) => r.kind === 'services' ? { ok: true, off: false, usda: false, scan: false }"
             " : r.kind === 'serverInfo' ? { ok: true, paired: true, server: 'food.example.org' }"
             " : r.kind === 'serverSyncCheck' ? { ok: true, status: 200, json: '{\"ok\": true}' }"
             " : r.kind === 'serverApi' ? window.__kh.gateway(r)"
             " : r.kind === 'aiStatus' ? { ok: true, available: true, reason: null }"
             " : r.kind === 'ai' ? (window.__kh.ai.push(r), { ok: true, answer: { status: 'ok', items: ["
             "   { text: '2 eggs', search: 'egg', amount: 2, unit: 'serving' }] } })"
             " : { error: 'off_off', message: 'off' } } } };")


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail and not ok else ""))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # the walk prints its own lines
        pass


def walk(browser, base: str, width: int, height: int, scheme: str) -> None:
    tag = f"{width}-{scheme}"
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    ctx.add_init_script(STUB)
    page = ctx.new_page()
    errors: list[str] = []
    others: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: others.append(r.url) if not r.url.startswith(base) else None)
    page.goto(f"{base}/index.html#today")
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] no demo pill or banner", page.locator("#brand-pill").is_hidden() and page.locator("#preview-banner").is_hidden())
    check(f"[{tag}] no Keep my data button", page.locator("#preview-banner-keep").is_hidden())
    # The first-start setup (js/views/welcome.js): an empty log of one's own, the profile basics, the optional server, done.
    page.wait_for_selector("#sheet-welcome[open]", timeout=10000)
    check(f"[{tag}] the setup opens at the first start", page.locator("#welcome-title").inner_text() == "Welcome to Kidney Health")
    page.click("#welcome-next")
    page.fill("#welcome-name", "Kim")
    page.select_option("#welcome-stage", "4")
    page.select_option("#welcome-diabetes", "type1")
    page.click("#welcome-about-next")
    page.wait_for_selector("#welcome-server-next")
    page.click("#welcome-server")
    check(f"[{tag}] the server step opens the phone settings", page.evaluate("window.__kh.phone") == ["settings"])
    page.click("#welcome-server-next")
    page.click("#welcome-done")
    page.wait_for_timeout(300)
    profile = page.evaluate("KH.request('GET', '/api/profile')")
    check(f"[{tag}] the setup saved the profile", profile.get("name") == "Kim" and profile.get("ckd_stage") == "4" and profile.get("diabetes_chosen") is True)
    check(f"[{tag}] the setup is closed", not page.locator("#sheet-welcome[open]").count())
    page.evaluate("window.__kh.phone.length = 0")
    start = page.evaluate("KH.request('GET', '/api/log?date=' + KH.state.date)")
    check(f"[{tag}] the log starts empty", len(start.get("entries", [])) == 0)
    me = page.evaluate("KH.request('GET', '/api/auth/status')")
    user = me.get("user") or {}
    check(f"[{tag}] one person, not an admin", user.get("username") == "me" and user.get("role") == "user", json.dumps(user)[:120])
    page.goto(f"{base}/index.html#settings")
    page.wait_for_selector("#view-settings:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] no sign-out and no device list", page.locator("#set-signout").count() == 0 and page.locator("#set-devices").count() == 0)
    body = page.locator("#set-device-body").inner_text()
    check(f"[{tag}] This device says the data is on this iPhone", "kept on this iPhone" in body, body[:120])
    page.click("#set-phone-settings")
    check(f"[{tag}] Apple Health and server asks the app", page.evaluate("window.__kh.phone") == ["settings"])
    food = page.evaluate("KH.request('GET', '/api/foods?q=banana&limit=1')")["foods"][0]
    page.evaluate(f"KH.request('POST', '/api/log', {{ date: KH.state.date, meal: 'lunch', food_id: {food['id']}, servings: 1 }})")
    for _ in range(100):  # the page's CSP forbids the string evaluation wait_for_function uses
        if page.evaluate("window.__kh.copies.length"):
            break
        page.wait_for_timeout(100)
    copy = json.loads(page.evaluate("window.__kh.copies[window.__kh.copies.length - 1]"))
    check(f"[{tag}] the safety copy holds the entry", len(copy.get("log_entries", [])) == 1 and copy.get("format") == "kidney-health-export")
    # Your server (step 4): Sync now hands the new entry to the app for the paired server, and the section says so.
    page.click("#set-server-sync-now")
    for _ in range(100):
        if page.evaluate("window.__kh.sync.length") and "Nothing" in page.locator("#set-server-sync").inner_text():
            break
        page.wait_for_timeout(100)
    sent = page.evaluate("window.__kh.sync")
    entries = [e for b in sent for e in b.get("entries", [])]
    check(f"[{tag}] Sync now sends the new entry once", len(entries) == 1 and "builtin" in entries[0]["food"], json.dumps(sent)[:160])
    text = page.locator("#set-device-body").inner_text()
    shows_host = any(word == "food.example.org" for word in re.split(r"[\s,;:()]+", text))  # a whole word on screen, not a URL check
    check(f"[{tag}] the section says what was sent and what is not", shows_host and "Waiting to be sent" in text
          and "your changes and deletions are sent too" in text, text[:200])
    page.click("#set-server-sync-now")
    page.wait_for_timeout(600)
    check(f"[{tag}] a row is sent once", len([e for b in page.evaluate("window.__kh.sync") for e in b.get("entries", [])]) == 1)
    # The native barcode scanner (owner, 2026-11-21): the Scan sheet offers Apple's scanner, and its code goes to the usual look-up.
    page.goto(f"{base}/index.html#add")
    page.wait_for_selector("#view-add:not([hidden])", timeout=30000)
    page.evaluate("KH.scan.open()")
    page.wait_for_selector("#scan-camera:not([hidden])", timeout=10000)
    check(f"[{tag}] Scan offers the iPhone's own scanner", page.locator("#scan-camera").inner_text() == "Scan with the camera")
    page.wait_for_timeout(1500)
    check(f"[{tag}] the scanned code goes to the usual look-up", page.locator("#scan-code").input_value() == "3017624010701",
          page.locator("#scan-status").inner_text()[:120])
    page.keyboard.press("Escape")
    page.goto(f"{base}/index.html#today")
    page.reload()
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    check(f"[{tag}] the entry survives a reload", food["name"].split(",")[0].lower() in page.locator("#view-today").inner_text().lower())
    check(f"[{tag}] the setup does not come back once finished", not page.locator("#sheet-welcome[open]").count())
    ai_walk(page, base, tag)
    over = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    check(f"[{tag}] no sideways scroll", not over)
    check(f"[{tag}] no request to another host", not others, "; ".join(others[:3]))
    check(f"[{tag}] no console or page error", not errors, "; ".join(errors[:3]))
    ctx.close()


def ai_walk(page, base: str, tag: str) -> None:
    """Design note 38 §5.6: describe a meal on the iPhone's own model (a stand-in answers for it)."""
    page.goto(f"{base}/index.html#settings")
    page.wait_for_selector("#view-settings:not([hidden])", timeout=30000)
    page.wait_for_selector("#set-ai-slot input[type=checkbox]", timeout=30000)
    text = page.locator("#set-ai-slot").inner_text()
    check(f"[{tag}] AI settings say it runs on this iPhone", "runs on this iPhone" in text, text[:160])
    page.locator("#set-ai-slot input[type=checkbox]").check()
    page.wait_for_timeout(500)
    page.goto(f"{base}/index.html#add")
    page.wait_for_selector("#view-add:not([hidden])", timeout=30000)
    button = page.get_by_role("button", name="Describe a meal (AI)")
    button.wait_for(timeout=30000)
    button.click()
    page.wait_for_selector("#sheet-ai[open] textarea", timeout=10000)
    page.fill("#sheet-ai textarea", "2 eggs, scrambled")
    page.get_by_role("button", name="Find foods").click()
    page.wait_for_selector("#sheet-ai .ai-parse-item", timeout=10000)
    results = page.locator("#sheet-ai .ai-results").inner_text()
    sent = page.evaluate("window.__kh.ai")
    check(f"[{tag}] describe a meal asks the app with the server's data",
          sent[-1:] == [{"kind": "ai", "task": "parse_meal", "text": '{"text":"2 eggs, scrambled"}'}], json.dumps(sent)[:160])
    check(f"[{tag}] the matches and the server's notice are shown",
          "egg" in results.lower() and "Nothing is logged until you add it" in results, results[:160])
    page.fill("#sheet-ai textarea", "my sugar is 55")
    page.get_by_role("button", name="Find foods").click()
    page.wait_for_selector("#sheet-ai .ai-card-alert", timeout=10000)
    check(f"[{tag}] a low gets the Treating a low card, and the model is not asked",
          "Treating a low" in page.locator("#sheet-ai .ai-results").inner_text() and len(page.evaluate("window.__kh.ai")) == len(sent))
    page.keyboard.press("Escape")


def both_ways_walk(browser, base: str) -> None:
    """Design note 39, steps 3 and 4: the server's food services and AI from the phone, and the choice of AI."""
    tag = "both-ways"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light")
    ctx.add_init_script(BOTH_WAYS)
    page = ctx.new_page()
    errors: list[str] = []
    others: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: others.append(r.url) if not r.url.startswith(base) else None)
    page.goto(f"{base}/index.html#today")
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    page.evaluate("KH.request('PUT', '/api/device/setup', { done: true }).then(() => KH.mock.local.flush())")  # past the first-start setup
    page.goto(f"{base}/index.html#settings")
    page.reload()
    page.wait_for_selector("#view-settings:not([hidden])", timeout=30000)
    page.wait_for_selector("#set-ai-where", timeout=30000)
    device = page.locator("#set-device-body").inner_text()
    for _ in range(50):
        if "Both ways" in device:
            break
        page.wait_for_timeout(100)
        device = page.locator("#set-device-body").inner_text()
    check(f"[{tag}] This device says the token works both ways", "Both ways" in device, device[:200])
    food = page.locator("#set-food-using").inner_text() if page.locator("#set-food-using").count() else ""
    check(f"[{tag}] Food data says the server's food services are used", "server's food services" in food, food[:120])
    ai = page.locator("#set-ai-slot").inner_text()
    check(f"[{tag}] AI settings list Describe a meal on the server's AI", "Describe a meal: your server's AI" in ai, ai[:240])
    check(f"[{tag}] and offer Use only this iPhone's AI", "Use only this iPhone's AI" in ai)
    page.goto(f"{base}/index.html#add")
    page.wait_for_selector("#view-add:not([hidden])", timeout=30000)
    button = page.get_by_role("button", name="Describe a meal (AI)")
    button.wait_for(timeout=30000)
    button.click()
    page.wait_for_selector("#sheet-ai[open] textarea", timeout=10000)
    page.fill("#sheet-ai textarea", "2 eggs")
    page.get_by_role("button", name="Find foods").click()
    page.wait_for_selector("#sheet-ai .ai-parse-item", timeout=10000)
    results = page.locator("#sheet-ai .ai-results").inner_text()
    asked = [r["path"] for r in page.evaluate("window.__kh.api")]
    check(f"[{tag}] describe a meal goes to the server", "/push/v1/api/ai/parse-meal" in asked and not page.evaluate("window.__kh.ai"),
          json.dumps(asked)[:200])
    check(f"[{tag}] the server's answer is shown", "Checked by your server" in results and "egg" in results.lower(), results[:160])
    page.keyboard.press("Escape")
    got = page.evaluate("KH.request('POST', '/api/ai/parse-meal', { text: '2 eggs', meal: 'lunch' })"
                        ".then((a) => [a.items[0].matches[0].food.id, KH.mock.instance._food(a.items[0].matches[0].food.id).source])")
    check(f"[{tag}] its food is named by the phone's own id", got[0] != 999999 and got[1] == "builtin", json.dumps(got))
    page.evaluate("KH.mock.aiDevice.setOnly(true)")
    page.evaluate("KH.request('PATCH', '/api/me/ai', { opt_in: true })")
    before = len(page.evaluate("window.__kh.api"))
    answer = page.evaluate("KH.request('POST', '/api/ai/parse-meal', { text: '2 eggs', meal: 'lunch' })")
    check(f"[{tag}] with Use only this iPhone's AI, the iPhone answers",
          answer.get("provider", {}).get("label") == "Apple's on-device model" and len(page.evaluate("window.__kh.ai")) == 1)
    paths = [r["path"] for r in page.evaluate("window.__kh.api")[before:]]
    check(f"[{tag}] and the server's AI is not asked", not any("/api/ai/" in x for x in paths), json.dumps(paths)[:160])
    check(f"[{tag}] no request to another host", not others, "; ".join(others[:3]))
    check(f"[{tag}] no console or page error", not errors, "; ".join(errors[:3]))
    ctx.close()


# Design note 39, steps 6 and 7: a stand-in for the change feed. The first read brings one entry made on the server (a built-in food,
# with the version the page's own twin works out); POST /push/v1/changes answers what `window.__kh.next` says, else "done".
SYNC = ("window.__kh = { copies: [], phone: [], api: [], sent: [], feed: [], next: null, seq: 0 };"
        "window.__kh.entry = (extra) => { const api = KH.mock.instance; const f = api._foods.find((x) => x.source === 'builtin' && /banana/i.test(x.name));"
        " const row = { id: 7, date: KH.state.date, meal: 'lunch', food_id: 7, food_name: f.name, servings: 1, grams: null, note: null, status: 'eaten',"
        " nutrients: api._foodView(f).nutrients, purpose: null, client_id: '0f8fad5b-d9cb-469f-a165-70867728950e', created_at: '2026-11-20T08:00:00Z',"
        " updated_at: '2026-11-20T08:00:00Z', food: { builtin: { fdc_id: f.fdc_id, name: f.name } }, ...(extra || {}) };"
        " return { kind: 'entry', id: row.client_id, op: 'put', version: KH.rowVersions.version('entry', row), row }; };"
        "window.__kh.gateway = (r) => { window.__kh.api.push({ method: r.method, path: r.path });"
        " const reply = (json) => ({ ok: true, status: 200, json: JSON.stringify(json) });"
        " if (r.path === '/push/v1/about') return reply({ account: 'acct-1', api_version: 1, sync: { gateway: true, changes: true } });"
        " if (r.path.startsWith('/push/v1/changes') && r.method === 'GET') { const changes = window.__kh.feed.splice(0);"
        "   window.__kh.seq += changes.length; return reply({ changes, foods: [], next: String(window.__kh.seq), more: false }); }"
        " if (r.path === '/push/v1/changes') { const body = JSON.parse(r.body); window.__kh.sent.push(body); const next = window.__kh.next; window.__kh.next = null;"
        "   return reply({ results: body.changes.map((c) => next ? { kind: c.kind, id: c.id, ...next } : { kind: c.kind, id: c.id, status: 'done', version: c.version }) }); }"
        " if (r.path === '/push/v1/match') return reply({ known: {}, unknown: {} });"
        " return { ok: true, status: 404, json: '{\"detail\": \"Not Found\"}' }; };"
        "window.webkit = { messageHandlers: { safetyCopy: { postMessage: (t) => window.__kh.copies.push(String(t)) },"
        " phone: { postMessage: (m) => window.__kh.phone.push(String(m)) },"
        " bridge: { postMessage: async (r) => r.kind === 'services' ? { ok: true, off: false, usda: false, scan: false }"
        " : r.kind === 'serverInfo' ? { ok: true, paired: true, server: 'food.example.org' }"
        " : r.kind === 'serverSyncCheck' ? { ok: true, status: 200, json: '{\"ok\": true}' }"
        " : r.kind === 'serverApi' ? window.__kh.gateway(r)"
        " : { error: 'off_off', message: 'off' } } } };")


def sync_walk(browser, base: str) -> None:
    """Design note 39, steps 6 and 7: an entry made on the server reaches Today; a conflict shows note 02's card; "Use mine"."""
    tag = "sync"
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, color_scheme="light")
    ctx.add_init_script(SYNC)
    page = ctx.new_page()
    errors: list[str] = []
    others: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: others.append(r.url) if not r.url.startswith(base) else None)
    page.goto(f"{base}/index.html#today")
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    page.evaluate("KH.request('PUT', '/api/device/setup', { done: true }).then(() => KH.mock.local.flush())")  # past the first-start setup
    page.reload()
    page.wait_for_selector("#view-today:not([hidden])", timeout=30000)
    page.wait_for_timeout(800)
    page.evaluate("window.__kh.feed.push(window.__kh.entry())")
    page.evaluate("KH.mock.serverApi.forget(); KH.mock.serverSync.sendNow()")
    for _ in range(100):
        if page.evaluate("KH.mock.instance._entries.length"):
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(500)
    today = page.locator("#view-today").inner_text().lower()
    check(f"[{tag}] an entry made on the server shows on Today", "banana" in today, today[:200])
    # the phone changes it, and so did the server: the conflict card, and nothing overwritten
    entry_id = page.evaluate("KH.mock.instance._entries[0].id")
    page.evaluate(f"KH.request('PUT', '/api/log/{entry_id}', {{ servings: 2 }})")
    page.evaluate("window.__kh.next = { status: 'conflict', version: window.__kh.entry({ note: 'from the web' }).version,"
                  " row: window.__kh.entry({ note: 'from the web' }).row }")
    page.goto(f"{base}/index.html#settings")
    page.wait_for_selector("#set-server-sync-now", timeout=30000)
    page.click("#set-server-sync-now")
    page.wait_for_selector("#set-server-review .conflict", timeout=10000)
    card = page.locator("#set-server-review").inner_text()
    check(f"[{tag}] the conflict card shows both copies", "changed on another device" in card and "from the web" in card
          and "2 servings" in card, card[:240])
    check(f"[{tag}] with note 02's two answers", page.get_by_role("button", name=re.compile("^Keep the saved one")).count() == 1
          and page.get_by_role("button", name=re.compile("^Use mine")).count() == 1)
    first = page.evaluate("window.__kh.sent[window.__kh.sent.length - 1].changes[0]")
    page.get_by_role("button", name=re.compile("^Use mine")).click()
    page.wait_for_timeout(300)
    page.click("#set-server-sync-now")
    for _ in range(50):
        if len(page.evaluate("window.__kh.sent")) >= 2:
            break
        page.wait_for_timeout(100)
    again = page.evaluate("window.__kh.sent[window.__kh.sent.length - 1].changes[0]")
    server_version = page.evaluate("window.__kh.entry({ note: 'from the web' }).version")
    check(f"[{tag}] Use mine sends the edit again on the server's version", again["base"] == server_version and again["fields"]["servings"] == 2
          and first["base"] != server_version, json.dumps([first, again])[:240])
    page.wait_for_timeout(500)
    text = page.locator("#set-device-body").inner_text()
    check(f"[{tag}] Settings says it syncs both ways, with nothing left to review", "Both ways" in text and page.locator("#set-server-review").count() == 0,
          text[:240])
    over = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    check(f"[{tag}] no sideways scroll", not over)
    check(f"[{tag}] no request to another host", not others, "; ".join(others[:3]))
    check(f"[{tag}] no console or page error", not errors, "; ".join(errors[:3]))
    ctx.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    out = khserver.free_dir(args.out)
    site = out / "site"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_preview.py"), "--device", str(site)], check=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=khserver.chromium_executable(), args=["--no-sandbox"])
            try:
                for width, height, scheme in ((375, 812, "light"), (1280, 800, "dark")):
                    walk(browser, base, width, height, scheme)
                both_ways_walk(browser, base)
                sync_walk(browser, base)
            finally:
                browser.close()
    finally:
        server.shutdown()
    failed = any(not r["ok"] for r in RESULTS)
    (out / "report.json").write_text(json.dumps({"results": RESULTS, "failed": failed}, indent=2), encoding="utf-8")
    print(f"{sum(r['ok'] for r in RESULTS)} passed, {sum(not r['ok'] for r in RESULTS)} failed; report {out / 'report.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
