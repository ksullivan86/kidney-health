"""Barcodes, label photos and the offline outbox in the browser stay wired to the server they front.

Static checks of ``app/static`` (no browser) for ``js/scan.js`` (note 03 R7, R8 client side, R9, R11),
``js/offline.js`` (note 02 R5) and their demo twins: the page has a labelled control for every step,
the scripts load in the order they need, the code builds DOM without HTML sinks and loads nothing from
another origin, the outbox stores health data only in IndexedDB (or memory) and calls only routes the
server has, with the server's limits; the demo answers the barcode route and the sign-out hook asks
before entries waiting on this device are lost. Behaviour is checked in Chromium by
``tools/e2e/device.py`` (photo decode in the native and WASM paths, a fake camera, the outbox with
``context.set_offline``, AI cards and the label photo against a fake OpenAI-compatible server); the
numbers by ``tests/data/barcode_vectors.json`` (``node tests/js/run_vectors.mjs``).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app import barcode, foods, log, meals, models, profile, settings_registry
from app import handbook as handbook_module
from app.auth import me as me_module
from app.auth import routes as auth_routes

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SCAN = (STATIC / "js" / "scan.js").read_text(encoding="utf-8")
OFFLINE = (STATIC / "js" / "offline.js").read_text(encoding="utf-8")
CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
ADD = (STATIC / "js" / "views" / "add.js").read_text(encoding="utf-8")
AI_VIEW = (STATIC / "js" / "views" / "ai.js").read_text(encoding="utf-8")
AUTH_VIEW = (STATIC / "js" / "views" / "auth.js").read_text(encoding="utf-8")
SETTINGS_VIEW = (STATIC / "js" / "views" / "settings.js").read_text(encoding="utf-8")
TODAY_VIEW = (STATIC / "js" / "views" / "today.js").read_text(encoding="utf-8")
MOCK_BARCODE = (STATIC / "js" / "mock" / "barcode.js").read_text(encoding="utf-8")
SW = (STATIC / "sw.js").read_text(encoding="utf-8")
CSS = (STATIC / "css" / "device.css").read_text(encoding="utf-8")
ENGINE = {name: (STATIC / "js" / "engine" / f"{name}.js").read_text(encoding="utf-8")
          for name in ("textclean", "gtin", "additives", "off")}
MINE = {"js/scan.js": SCAN, "js/offline.js": OFFLINE, "js/mock/barcode.js": MOCK_BARCODE,
        **{f"js/engine/{k}.js": v for k, v in ENGINE.items()}}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}
        self.label_for: set[str] = set()
        self.scripts: list[dict[str, str]] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v if v is not None else "" for k, v in attrs}
        if a.get("id"):
            self.by_id[a["id"]] = {"tag": tag, **a}
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "script":
            self.scripts.append(a)
        if tag == "link" and a.get("rel") == "stylesheet":
            self.styles.append(a.get("href", ""))


PAGE = _Page()
PAGE.feed(INDEX)


def _js_number(source: str, name: str) -> float:
    m = re.search(rf"const {name} = ([0-9_.]+)[;,]", source)
    assert m, f"const {name} not found"
    return float(m.group(1).replace("_", ""))


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #


def test_scan_sheet_controls_are_labelled_and_announced() -> None:
    for slot in ("btn-scan", "sheet-scan", "scan-viewfinder", "scan-video", "scan-camera", "scan-camera-stop",
                 "scan-live-note", "scan-file", "scan-code", "scan-go", "scan-status", "scan-result"):
        assert slot in PAGE.by_id, f"#{slot} missing from index.html"
    assert PAGE.by_id["sheet-scan"]["tag"] == "dialog" and PAGE.by_id["sheet-scan"].get("aria-labelledby")
    for control in ("scan-file", "scan-code"):
        assert control in PAGE.label_for, f"#{control} has no <label for>"
        assert PAGE.by_id[control].get("aria-describedby") in PAGE.by_id, f"#{control} hint missing"
    assert PAGE.by_id["scan-file"]["type"] == "file" and PAGE.by_id["scan-file"]["accept"].startswith("image/")
    # No `capture`: iOS then offers the camera and the photo library (note 02 R7 step 4).
    assert "capture" not in PAGE.by_id["scan-file"] and "capture" not in PAGE.by_id["q-photo"]
    code = PAGE.by_id["scan-code"]
    assert code["inputmode"] == "numeric" and code.get("autocomplete") == "off"
    assert PAGE.by_id["scan-status"].get("role") == "status" and PAGE.by_id["scan-status"].get("aria-live") == "polite"
    # The camera view is muted and inline (iOS plays nothing full screen); the decoder never sees audio.
    video = PAGE.by_id["scan-video"]
    assert "muted" in video and "playsinline" in video
    # "Scan" comes first among the Add view's actions (note 03 R9).
    actions = INDEX[INDEX.index('class="add-actions"'):]
    assert actions.index('id="btn-scan"') < actions.index('id="btn-quick"')


def test_quick_add_has_photo_gtin_and_ingredients() -> None:
    for slot in ("quick-photo", "q-photo", "q-photo-view", "q-photo-frame", "q-photo-img", "q-photo-remove", "q-photo-ai",
                 "q-gtin", "q-ingredients", "q-ingredients-scan"):
        assert slot in PAGE.by_id, f"#{slot} missing from index.html"
    for control in ("q-photo", "q-gtin", "q-ingredients"):
        assert control in PAGE.label_for, f"#{control} has no <label for>"
        assert PAGE.by_id[control].get("aria-describedby"), f"#{control} has no hint"
    assert PAGE.by_id["q-ingredients"]["tag"] == "textarea"
    assert int(PAGE.by_id["q-ingredients"]["maxlength"]) == models.MAX_INGREDIENTS_CHARS
    # The photo is alt-texted, scrollable by keyboard, and the zoom buttons say what they do.
    assert PAGE.by_id["q-photo-img"].get("alt")
    assert PAGE.by_id["q-photo-frame"].get("tabindex") == "0"
    assert len(re.findall(r'data-zoom="[123]"', INDEX)) == 3
    assert PAGE.by_id["q-ingredients-scan"].get("aria-live") == "polite"


def test_header_badge_and_sign_out_sheet() -> None:
    badge = PAGE.by_id["sync-badge"]
    assert badge["tag"] == "button" and badge.get("type") == "button" and "hidden" in badge
    assert PAGE.by_id["sync-live"].get("role") == "status"
    assert PAGE.by_id["sync-badge-short"].get("aria-hidden") == "true"  # the aria-label says it in full
    assert "badge.setAttribute('aria-label'" in OFFLINE
    sheet = PAGE.by_id["sheet-unsynced"]
    assert sheet["tag"] == "dialog" and sheet["aria-labelledby"] == "sheet-unsynced-title"
    assert sheet["aria-describedby"] == "sheet-unsynced-sub"
    assert "sheet-entry-provenance" in PAGE.by_id


def test_script_and_style_order() -> None:
    srcs = [s["src"] for s in PAGE.scripts if s.get("src")]
    pos = {s: i for i, s in enumerate(srcs)}
    engine = [f"js/engine/{n}.js" for n in ("textclean", "gtin", "additives", "off")]
    assert [pos[e] for e in engine] == sorted(pos[e] for e in engine), "barcode engine files out of order"
    assert pos[engine[-1]] < pos["js/core.js"]
    assert pos["js/mock/foods.js"] < pos["js/mock/barcode.js"] < pos["js/mock/seed.js"]
    assert pos["js/core.js"] < pos["js/offline.js"] < pos["js/main.js"]
    ponyfill = "vendor/barcode-detector-3.2.2/ponyfill.iife.js"
    assert pos["js/views/add.js"] < pos[ponyfill] < pos["js/scan.js"] < pos["js/main.js"]
    tag = next(s for s in PAGE.scripts if s.get("src") == ponyfill)
    assert "defer" in tag and tag.get("data-preview") == "omit"  # the preview has no WASM decoder
    assert all(not s.get("src", "").startswith(("http:", "https:", "//")) for s in PAGE.scripts)
    assert not any(s for s in PAGE.scripts if not s.get("src")), "no inline scripts (CSP)"
    assert "css/device.css" in PAGE.styles and PAGE.styles.index("css/device.css") < PAGE.styles.index("css/touch.css")


def test_service_worker_caches_the_new_files_but_not_the_wasm() -> None:
    for path in ("/css/device.css", "/js/offline.js", "/js/scan.js", "/vendor/barcode-detector-3.2.2/ponyfill.iife.js",
                 "/js/engine/gtin.js", "/js/engine/additives.js", "/js/engine/textclean.js", "/js/engine/off.js",
                 "/js/mock/barcode.js"):
        assert f"'{path}'" in SW, f"sw.js SHELL_URLS lacks {path}"
    assert ".wasm'" not in SW.split("SHELL_URLS", 1)[1].split("];", 1)[0], "the 1 MB decoder is fetched when first needed"


# --------------------------------------------------------------------------- #
# The code
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", sorted(MINE))
def test_no_html_sinks_eval_or_other_origins(name: str) -> None:
    source = MINE[name]
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute('on",
                 "srcdoc", "javascript:"):
        assert sink not in source, f"{name} uses {sink}"
    for url in re.findall(r"['\"`](https?://[^'\"`\s]+)", source):
        if re.match(r"https?://[a-z.]+\.invalid$", url):
            continue  # a base for new URL(path, base), never requested (RFC 2606 reserves .invalid)
        # Only links shown to people (Open Food Facts, USDA, the method file); the browser fetches none of them.
        assert url.startswith("https://"), f"{name}: {url} is not https"
        assert re.match(r"https://(world\.openfoodfacts\.org|fdc\.nal\.usda\.gov|github\.com|opendatacommons\.org)(/|$)", url), url
    assert "fetch(" not in source or name == "js/scan.js", f"{name} fetches directly"


def test_scan_fetches_only_its_own_decoder() -> None:
    # The only direct fetch is the vendored WASM, same origin; lookups go through KH.request (CSRF header, 401s).
    for m in re.finditer(r"fetch\(([^)]*)\)", SCAN):
        assert "WASM_DIR" in m.group(1) or "wasm" in m.group(1).lower(), m.group(0)
    assert "const WASM_DIR = '/vendor/zxing-wasm-3.1.3/'" in SCAN
    assert "request('POST', '/api/foods/barcode'" in SCAN
    # Live camera only in a secure context; never in the static preview (note 03 R9, note 02 R7).
    assert "window.isSecureContext" in SCAN and "PREVIEW" in SCAN
    # Two identical reads before a live result, a watchdog for a camera that sends no frames.
    assert _js_number(SCAN, "READS_NEEDED") == 2
    assert _js_number(SCAN, "NO_FRAME_MS") == 4000
    for cleanup in ("pagehide", "visibilitychange", "track.stop()"):
        assert cleanup in SCAN, f"the camera is not released on {cleanup}"


def test_photos_are_downscaled_and_reencoded_before_upload() -> None:
    # Note 03 R8 (client side): long edge <= 1600 px, re-encoded through a canvas (which drops EXIF).
    assert _js_number(SCAN, "PHOTO_EDGE") == 1600
    assert _js_number(AI_VIEW, "PHOTO_EDGE") == 1600
    assert "canvas.toBlob(" in AI_VIEW and "'image/jpeg'" in AI_VIEW
    assert "imageOrientation: 'from-image'" in AI_VIEW
    # The label photo shown beside Quick add stays on the device: an object URL, revoked when dropped.
    assert "URL.createObjectURL" in SCAN and "URL.revokeObjectURL" in SCAN
    assert "KH.ai.prepareJpeg" in SCAN and "KH.ai.withConsent('photos'" in SCAN


def test_attribution_links_are_https_and_open_safely() -> None:
    assert "KH.off.safeHttpsUrl" in SCAN
    # The preview's sandboxed frame cannot open windows: there the address is text, not a dead link.
    assert "if (PREVIEW) return h('span', { class: 'ext-text' }" in SCAN and "KH.scan.newTab(href, text)" in SETTINGS_VIEW
    assert "rel: 'noopener noreferrer'" in SCAN and "target: '_blank'" in SCAN
    assert "if (u.protocol !== 'https:') return null" in ENGINE["off"] or "protocol === 'https:'" in ENGINE["off"]


def _server_paths() -> list[re.Pattern[str]]:
    out = []
    routers = [barcode.router, foods.router, log.router, profile.router, meals.router, meals.plan_router,
               handbook_module.router, me_module.router, auth_routes.router]
    for router in routers:
        for r in router.routes:
            out.append(re.compile("^" + re.sub(r"\\\{[a-z_]+\\\}", "[^/]+", re.escape(r.path)) + "$"))
    return out


def test_offline_and_scan_call_only_routes_the_server_has() -> None:
    paths = _server_paths()
    called = set(re.findall(r"'(/api/[a-z/\-]+)'", OFFLINE + SCAN)) | set(re.findall(r"`(/api/[a-z/\-]+)", OFFLINE + SCAN))
    assert {"/api/log/batch", "/api/foods/barcode", "/api/log"} <= called
    for p in called:
        assert any(rx.match(p) for rx in paths), f"{p} is not a server route"
    kinds = dict(re.findall(r"'POST (/api/[a-z/\-]+)': '([a-z]+)'", OFFLINE))
    assert kinds == {"/api/log": "entry", "/api/log/quick": "quick", "/api/log/mark-eaten": "mark"}
    for p in kinds:
        assert any(rx.match(p) for rx in paths), f"queued {p} is not a server route"


def test_outbox_limits_match_the_server() -> None:
    assert _js_number(OFFLINE, "BATCH_MAX") == models.MAX_LOG_BATCH
    assert _js_number(OFFLINE, "FAST_MS") == 6000  # note 02 R5: a write gives up and queues after 6 s
    assert "client_id" in models.LogCreate.model_fields and "client_id" in models.QuickAdd.model_fields
    # A v4 UUID: the server's validate_client_id accepts it (crypto.randomUUID or getRandomValues).
    assert "crypto.randomUUID" in OFFLINE and "getRandomValues" in OFFLINE
    assert models.validate_client_id("3f2b8c1e-7a4d-4e6b-9c2a-1d5e8f0a7b3c") == "3f2b8c1e-7a4d-4e6b-9c2a-1d5e8f0a7b3c"
    # The batch failure index the server writes ("entries[3]: …", "entries.3.servings") is the one parsed.
    assert r"/entries(?:\.|\[)(\d+)/" in OFFLINE


def test_health_data_lives_in_indexeddb_or_memory_only() -> None:
    for storage in ("localStorage", "sessionStorage", "document.cookie", "caches."):
        assert storage not in OFFLINE, f"js/offline.js uses {storage}"
        assert storage not in SCAN, f"js/scan.js uses {storage}"
    assert "window.indexedDB.open(DB_NAME" in OFFLINE and "const DB_NAME = 'kdl'" in OFFLINE
    # Per person: every outbox item and snapshot carries the signed-in user's id; another person's are never sent.
    assert "i.user_id === uid" in OFFLINE
    # Sign-out asks first and then wipes this device's copies; the server also sends Clear-Site-Data.
    assert "KH.offline.beforeSignOut" in AUTH_VIEW and "KH.offline.purge" in AUTH_VIEW
    assert AUTH_VIEW.index("KH.offline.beforeSignOut") < AUTH_VIEW.index("KH.offline.purge")
    # One sync at a time (Web Locks across tabs); the guard is cleared whatever the outcome.
    assert "navigator.locks.request('kdl-sync'" in OFFLINE and "p.then(done, done)" in OFFLINE


def test_waiting_entries_are_shown_as_waiting() -> None:
    assert "waiting to sync" in TODAY_VIEW and "not saved" in TODAY_VIEW
    assert "KH.offline.servedOffline" in TODAY_VIEW  # "this is the copy this device saved at …"
    assert "Saved on this device" in ADD


def test_settings_lists_the_food_data_keys_and_the_device_section() -> None:
    for key in ("food.off_enabled", "food.off_contact", "food.off_rate_per_minute", "food.barcode_negative_ttl_hours",
                "food.usda_branded_barcode"):
        if key in settings_registry.REGISTRY:
            assert f"'{key}'" in SETTINGS_VIEW, f"Admin → Server settings does not group {key}"
    assert "KH.offline.renderDevice" in SETTINGS_VIEW
    assert "Open Food Facts" in SETTINGS_VIEW and "ODbL" in SETTINGS_VIEW  # About → data sources (note 03 R11)


def _function_body(source: str, signature: str) -> str:
    """The text of a top-level function inside a view's IIFE (two-space indent), up to its closing brace."""
    start = source.index(signature)
    end = source.index("\n  }\n", start)
    return source[start:end]


def test_settings_device_section_is_drawn_once_when_renders_overlap() -> None:
    """Review finding (v0.3.0): on a first visit js/pwa.js asks Settings → This device to draw again while the first
    draw still waits for the device state, and both appended a full copy (two Clear buttons, duplicate ids). Each
    draw now builds into a detached fragment and only the newest replaces the section after its last await
    (tools/e2e/device.py ``firstvisit`` checks it in Chromium on fresh profiles)."""
    body = _function_body(SETTINGS_VIEW, "async function renderDevice()")
    assert "document.createDocumentFragment()" in body
    assert "body.append(" not in body and "clear(body)" not in body, "renderDevice must not write to the page before its awaits end"
    assert "ticket !== deviceRender" in body and body.count("body.replaceChildren(out)") == 1
    assert "stops.push(await KH.offline.renderDevice(out))" in body  # the outbox list goes into the same fragment
    outbox = _function_body(OFFLINE, "async function renderDevice(container)")
    assert "ticket !== drawn" in outbox and "box.replaceChildren(...parts)" in outbox
    assert "box.append(" not in outbox and "clear(box)" not in outbox, "the outbox list must be replaced in one step"
    assert "return stop;" in outbox  # Settings stops a replaced list's live updates


# --------------------------------------------------------------------------- #
# The demo
# --------------------------------------------------------------------------- #


def test_the_demo_answers_the_barcode_route_with_the_servers_reasons() -> None:
    assert "route('POST', '/api/foods/barcode'" in MOCK_BARCODE
    server = (ROOT / "app" / "barcode.py").read_text(encoding="utf-8")
    for reason in set(re.findall(r"reason['\"]?\s*[:=]\s*['\"]([a-z_]+)['\"]", MOCK_BARCODE)):
        assert reason in server, f"the demo answers reason {reason!r}, the server never does"
    assert "off_consent_required" in MOCK_BARCODE
    # Every recorded product carries the ODbL licence and an https product page.
    block = MOCK_BARCODE.split("DEMO_PRODUCTS:BEGIN", 1)[1].split("DEMO_PRODUCTS:END", 1)[0]
    assert block.count("ODbL-1.0") >= 3 and "http://" not in block


def test_css_keeps_targets_and_motion_preferences() -> None:
    assert "min-height: var(--tap)" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "!important" not in CSS


def test_ios_home_screen_tip_shows_once_after_the_third_visit() -> None:
    """Note 02 R10 (v0.3.0 review L12): besides Settings → This device, iPhone and iPad users get the Add to Home
    Screen steps once, as a dismissible tip, after the third signed-in visit; it never blocks the page, and a
    browser that refuses storage simply never shows it. tools/e2e/device.py --only iostip checks it in Chromium
    with an iPhone user agent (shown on visit 3 only; never on a desktop)."""
    pwa = (STATIC / "js" / "pwa.js").read_text(encoding="utf-8")
    main = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
    tip = re.search(r'<aside class="install-tip" id="install-tip" ([^>]*)>', INDEX)
    assert tip and 'aria-labelledby="install-tip-title"' in tip.group(1) and tip.group(1).rstrip().endswith("hidden")
    assert 'id="install-tip-close" aria-label="Dismiss the Home Screen tip"' in INDEX
    assert "role=\"dialog\"" not in INDEX.split('id="install-tip"', 1)[1].split("</aside>", 1)[0]
    body = _function_body(pwa, "function countVisit()")
    assert "if (MOCK) return;" in body and "platform() !== 'ios'" in body and "isStandalone()" in body
    assert "visits < TIP_AFTER_VISITS" in body and "const TIP_AFTER_VISITS = 3;" in pwa
    assert "store(TIP_KEY, 'shown');" in body  # once: never offered again
    assert "try { return window.localStorage.getItem(key); } catch (e) { return null; }" in pwa
    assert "steps(...IOS_STEPS)" in body and "body.append(steps(...IOS_STEPS));" in pwa  # the Settings panel's own steps
    assert "countVisit };" in pwa
    start = _function_body(main, "async function start(view)")
    assert start.index("router.show(") < start.index("KH.pwa.countVisit()")  # a signed-in visit, after the view shows
