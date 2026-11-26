"""A recipe page read on the iPhone with no server (owner, 2026-11-26; design note 30 §3; ARCHITECTURE.md "Device mode").

The iPhone app fetches the page the person typed (``ios/KidneyHealth/Services/RecipePageFetcher.swift``, bridge kind
``fetchRecipePage``) with the server's checks (``KidneyHealthCore/RecipePage.swift``), and the page reads the recipe with the twin of
the server's parser (``js/engine/recipe_import.js`` ``pageRecipe``). ``tests/data/recipe_page_vectors.json`` pins both to the server;
``tests/js/phone_recipe_page.mjs`` runs the page side; the Swift package's tests replay the address and link rules on Linux in CI.
This file checks the vectors are current, runs the page side, and pins the app's code to the server's rules.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app import brand
from app.models import SOURCE_URL_MAX
from app.recipe_import import api, fetch

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"
STATIC = ROOT / "app" / "static"
FETCHER = (IOS / "KidneyHealth" / "Services" / "RecipePageFetcher.swift").read_text(encoding="utf-8")
FETCHER_CODE = re.sub(r"//[^\n]*", "", FETCHER)
CORE = (IOS / "KidneyHealthCore" / "Sources" / "KidneyHealthCore" / "RecipePage.swift").read_text(encoding="utf-8")
SERVICES = re.sub(r"//[^\n]*", "", (IOS / "KidneyHealth" / "Services" / "FoodServices.swift").read_text(encoding="utf-8"))
LISTS = (STATIC / "js" / "mock" / "lists.js").read_text(encoding="utf-8")
ENGINE = (STATIC / "js" / "engine" / "recipe_import.js").read_text(encoding="utf-8")
VIEW = (STATIC / "js" / "views" / "recipe_import.js").read_text(encoding="utf-8")
VECTORS = json.loads((ROOT / "tests" / "data" / "recipe_page_vectors.json").read_text(encoding="utf-8"))


def test_the_vectors_are_what_the_server_gives_now():
    done = subprocess.run([sys.executable, str(ROOT / "tests" / "data" / "gen_recipe_page_vectors.py"), "--check"], capture_output=True,
                          text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_page_side_in_node():
    assert shutil.which("node"), "Node.js 22 is needed (CLAUDE.md, Parity)"
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "phone_recipe_page.mjs")], capture_output=True, text=True, timeout=180,
                          check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "checks passed" in done.stdout


def _swift_int(name: str) -> int:
    found = re.search(rf"static let {name}(?:: \w+)? = ([0-9 *_]+)\n", CORE)
    assert found, name
    return eval(found.group(1).replace("_", ""), {})  # noqa: S307 - digits and "*" from our own source


def test_the_phones_limits_are_the_servers():
    assert _swift_int("maxRedirects") == fetch.MAX_REDIRECTS
    assert _swift_int("maxPageBytes") == fetch.MAX_PAGE_BYTES
    assert _swift_int("deadline") == fetch.DEADLINE_S
    assert _swift_int("maxLinkLength") == SOURCE_URL_MAX
    assert _swift_int("pagesPerHour") == api.PAGES_PER_HOUR
    assert "allowedPorts: Set<Int> = [80, 443]" in CORE and tuple(fetch.ALLOWED_PORTS) == (80, 443)
    assert 'htmlTypes: Set<String> = ["text/html", "application/xhtml+xml"]' in CORE and fetch.HTML_TYPES == ("text/html", "application/xhtml+xml")
    assert f'userAgent = "{brand.USER_AGENT_RECIPES}"' in FETCHER
    assert VECTORS["constants"]["user_agent"] == brand.USER_AGENT_RECIPES


def test_the_app_fetches_only_the_checked_link_with_no_cookies_cache_or_redirects():
    code = FETCHER_CODE
    # the link: the phone's rule, checked again for every redirect, and the URL must name the host that was checked
    assert "RecipePage.checkLink(url)" in code and "RecipePage.checkLink(next)" in code and "sameHost(url, link)" in code
    assert 'url.scheme?.lowercased() == "https"' in code
    assert "for _ in 0...RecipePage.maxRedirects" in code and 'RecipePageError("too_many_redirects")' in code
    # every address of the host is checked before the request, and the address the connection used after it
    assert "getaddrinfo(" in code and 'addresses.allSatisfy({ RecipePage.classify($0) == .global })' in code
    assert "m.remoteAddress" in code and "RecipePage.classify(bytes) != .global" in code and 'result = .failure(.init("blocked"))' in code
    # no cookies, no cache, no stored credentials, no redirect followed, a plain User-Agent, the whole fetch within 15 seconds
    for text in ("configuration.httpCookieStorage = nil", "configuration.httpShouldSetCookies = false", "configuration.urlCache = nil",
                 "configuration.urlCredentialStorage = nil", "request.httpShouldHandleCookies = false", "completionHandler(nil)",
                 ".reloadIgnoringLocalAndRemoteCacheData", "withDeadline(RecipePage.deadline", "data.count > RecipePage.maxPageBytes",
                 "RecipePage.isHTML(type)", '"User-Agent": RecipePageFetcher.userAgent'):
        assert text in code, text
    assert "URLSessionConfiguration.ephemeral" in code and ".shared" not in code.replace("RecipePageFetcher.shared", "")
    # nothing is kept or logged, and nothing about the person is read
    for word in ("print(", "NSLog", "os_log", "Logger(", "debugPrint", "dump(", "UserDefaults", "FileManager", ".write(to:", "Keychain",
                 "HealthKit", "Authorization"):
        assert word not in code, word
    # what goes back to the page: the page's text or a code
    assert set(re.findall(r'\["(\w+)": ', code)) <= {"ok", "error", "User-Agent"}
    assert '["ok": true, "html": html]' in code


def test_the_bridge_offers_the_kind_and_says_so():
    assert 'case "fetchRecipePage":' in SERVICES and "RecipePageFetcher.shared.answer(request)" in SERVICES
    assert '"recipePage": true' in SERVICES
    assert "kind: 'fetchRecipePage', url" in LISTS and "services.recipePage === true" in LISTS


def test_the_page_is_only_ever_text():
    """Nothing from the page goes into a document: no DOMParser, no innerHTML, no script runs. The engine reads the JSON-LD blocks
    from the string with a port of Python's html.parser, and JSON.parse."""
    for text, name in ((ENGINE, "engine"), (LISTS, "lists.js")):
        for word in ("DOMParser", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.", "createElement", "eval(", "new Function"):
            assert word not in text, (name, word)
    assert "function ldJsonBlocks(page)" in ENGINE and "JSON.parse(text)" in ENGINE


def test_the_screen_says_where_the_page_was_read():
    assert "This iPhone opens the page and reads its recipe data. Only the link goes to that site." in VIEW
    assert "Read on this iPhone. Only the link went to that site, and nothing else left the phone." in VIEW
    assert "read_on: 'phone'" in LISTS


def test_the_messages_are_the_servers():
    assert VECTORS["constants"]["messages"] == fetch.MESSAGES
    for code, words in fetch.MESSAGES.items():
        assert json.dumps(words).strip('"').replace("'", "\\'") in LISTS, code


@pytest.mark.parametrize("case", [c for c in VECTORS["link_cases"] if c["phone"] == "ok"], ids=lambda c: c["url"][:40])
def test_the_phone_never_opens_a_link_the_server_refuses(case):
    assert case["server"] == "ok"
