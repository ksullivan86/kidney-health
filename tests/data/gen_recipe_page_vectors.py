#!/usr/bin/env python3
"""Generate tests/data/recipe_page_vectors.json: a recipe page read on the iPhone, as the server reads it (design note 30 §3).

    python3 tests/data/gen_recipe_page_vectors.py           # rewrite the file
    python3 tests/data/gen_recipe_page_vectors.py --check   # exit 1 when the committed file is stale

With no server, the iPhone app fetches the page itself (ios/KidneyHealth/Services/RecipePageFetcher.swift) and the page reads it.
Produced by the server's own code and replayed by:

* ``node tests/js/run_vectors.mjs`` against ``app/static/js/engine/recipe_import.js``: ``parse.ld_json_blocks`` (the page's
  ``application/ld+json`` blocks, read with Python's ``html.parser``), the first ``Recipe`` and what is kept of it, and the
  entities ``parse.text_of`` decodes;
* ``swift test --package-path ios/KidneyHealthCore`` against ``RecipePage.swift``: ``app.egress.classify_address`` (which
  addresses may be opened), the server's ``fetch.check_page_url`` with the phone's stricter rule (https only, plain ASCII, no
  user name, a plain host name or address), and the charset names ``fetch._charset`` looks at.

Every case gives the same answer on Python 3.12 to 3.15 (the CI's versions); ``tests/test_phone_recipe_import.py`` checks the file.
"""
from __future__ import annotations

import argparse
import html.entities
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "recipe_page_vectors.json"
sys.path.insert(0, str(ROOT))
os.environ.pop("KUBERNETES_SERVICE_HOST", None)  # classify_address also refuses the cluster's API address; not on a phone

from app import brand, egress  # noqa: E402
from app.recipe_import import api, fetch  # noqa: E402
from app.recipe_import import parse as P  # noqa: E402


def ld(body: str, kind: str = "application/ld+json") -> str:
    return f'<script type="{kind}">{body}</script>'


RECIPE = json.dumps({"@context": "https://schema.org", "@type": "Recipe", "name": "Rice &amp; peas", "recipeYield": "4 servings",
                     "recipeIngredient": ["1 cup white rice", "1 cup green peas", "1 tbsp olive oil"],
                     "recipeInstructions": [{"@type": "HowToStep", "text": "Cook the rice."},
                                            {"@type": "HowToStep", "text": "Stir in the peas and oil."}]})
GRAPH = json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "WebSite", "name": "A site"}, {"@type": "BreadcrumbList"},
    {"@type": ["Recipe", "NewsArticle"], "name": "Chicken &#39;n&#39; greens", "recipeYield": ["6", "6 bowls"],
     "recipeIngredient": ["1 lb chicken breast", "2 cups kale, chopped", "&frac12; tsp black pepper"],
     "recipeInstructions": [{"@type": "HowToSection", "name": "Cook", "itemListElement": [
         {"@type": "HowToStep", "text": "Brown the chicken.&nbsp;Add the kale."}, {"@type": "HowToStep", "name": "Serve hot."}]}]}]})
OTHER = json.dumps({"@type": "Organization", "name": "Not a recipe"})
EMOJI_STEP = " ".join(f"Stir 🥄 pot {i} well." for i in range(40))
EMOJI = json.dumps({"@type": "Recipe", "name": "🍋 " * 120 + "Lemon chicken", "recipeIngredient": ["🍋 " * 200 + "2 lemons"],
                    "recipeInstructions": [EMOJI_STEP]}, ensure_ascii=False)
PAGE_START = '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><title>Rice and peas</title>'

# name -> the page, written out (``html``) or built from pieces repeated (``build``: [[text, times], ...]) when it is large.
PAGES: list[tuple[str, dict[str, Any]]] = [
    ("a plain recipe page", {"html": PAGE_START + ld(RECIPE) + "</head><body><h1>Rice &amp; peas</h1></body></html>"}),
    ("the type in capitals with a charset", {"html": f'<script type="Application/LD+JSON; charset=utf-8">{RECIPE}</script>'}),
    ("single quotes and no quotes", {"html": f"<script type='application/ld+json'>{OTHER}</script><script type=application/ld+json>{RECIPE}</script>"}),
    ("a graph after another block", {"html": ld(OTHER) + ld(GRAPH)}),
    ("a block that is not JSON, then a recipe", {"html": ld("{not json") + ld(RECIPE)}),
    ("an empty block and a self-closing script", {"html": ld("") + '<script type="application/ld+json"/>' + ld(RECIPE)}),
    ("a recipe inside a comment is not read", {"html": "<!-- " + ld(RECIPE) + " -->" + ld(OTHER)}),
    ("the end tag in capitals with a space", {"html": f'<SCRIPT TYPE="application/ld+json">{RECIPE}</SCRIPT >'}),
    ("an ordinary script that mentions ld+json", {"html": "<script>var s = '" + ld(RECIPE).replace("</script>", "") + "';</script>" + ld(OTHER)}),
    ("a script end inside the JSON cuts the block", {"html": ld('{"@type": "Recipe", "name": "a </script> b"}') + ld(OTHER)}),
    ("almost an end tag stays inside", {"html": ld('{"@type": "Recipe", "name": "a </scripts b", "recipeIngredient": "1 egg"}')}),
    ("a block with no end is not read", {"html": ld(OTHER) + '<script type="application/ld+json">' + RECIPE}),
    ("title, textarea and style hold text, not tags", {"html": "<title>" + ld(RECIPE) + "</title><textarea>" + ld(RECIPE)
                                                       + "</textarea><style>" + ld(RECIPE) + "</style>" + ld(OTHER)}),
    ("everything after plaintext is text", {"html": "<plaintext>" + ld(RECIPE)}),
    ("noscript is read as ordinary markup", {"html": "<noscript>" + ld(RECIPE) + "</noscript>"}),
    ("an xml line, a declaration and odd comments", {"html": '<?xml version="1.0"?><!DOCTYPE html><! odd ><!-- a -- b --><!---->'
                                                     + "</ ><p>a < b, 3 <4 & 5 &amp; 6</p>" + ld(RECIPE)}),
    ("a numeric reference in the type", {"html": f'<script type="application/ld&#43;json">{RECIPE}</script>'}),
    ("other attributes and a second type", {"html": f'<script async data-x=\'1\' type="application/ld+json" type="text/plain" id=x>{RECIPE}</script>'}),
    ("a slash before the attribute", {"html": f'<script/type="application/ld+json">{RECIPE}</script>'}),
    ("spaces around the type", {"html": f'<script type="  application/ld+json  ">{RECIPE}</script>'}),
    ("the wrong type", {"html": ld(RECIPE, "application/json") + ld(RECIPE, "text/ld+json")}),
    ("NaN and Infinity in the JSON", {"html": ld('{"@type": "Recipe", "name": "Odd numbers", "recipeYield": NaN, "x": [Infinity, -Infinity], '
                                                 '"recipeIngredient": ["1 egg"]}')}),
    ("a byte order mark is not JSON", {"html": ld("﻿" + RECIPE) + ld(OTHER)}),
    ("white space around the JSON", {"html": ld(" \n " + RECIPE + " \t")}),
    ("only the first 20 scripts count", {"html": ld(OTHER) * 20 + ld(RECIPE)}),
    ("a block over 1 MiB is left out", {"build": [['<script type="application/ld+json">{"@type": "Recipe", "name": "Big", "x": "', 1],
                                                  ["0123456789abcdef", 65536], ['"}</script>', 1], [ld(OTHER), 1]]}),
    ("a block of exactly 1 MiB is read", {"build": [['<script type="application/ld+json">{"name": "', 1], ["x", 1048576 - 13],
                                                     ['"}</script>', 1]]}),
    ("emoji count as one character", {"html": ld(EMOJI)}),
    ("entities in the recipe text", {"html": ld(json.dumps({"@type": "Recipe", "name": "Caf&eacute; &ldquo;cr&egrave;me&rdquo; &AMP co",
                                                            "recipeIngredient": ["1&frac12; cups milk", "2 tbsp sugar &amp; spice",
                                                                                 "350&deg;F oven &#8211; 10&nbsp;min", "1 &notin; x &notit;",
                                                                                 "Bake at 180 &#x2103;", "&#128; &#0; &#xD800; &#x110000;"]}))}),
    ("a main entity on a web page", {"html": ld(json.dumps({"@type": "WebPage", "mainEntity": {"@type": "schema:Recipe", "name": "Main",
                                                                                                "recipeIngredient": "3 cups milk"}}))}),
    ("more than 60 lines and 20 steps", {"html": ld(json.dumps({"@type": "Recipe", "name": "Long",
                                                                 "recipeIngredient": [f"{i} g flour" for i in range(70)],
                                                                 "recipeInstructions": [f"Step {i}." for i in range(25)]}))}),
    ("text at the end with an ampersand", {"html": ld(RECIPE) + "<p>Salt & pepper &"}),
    ("a stray less-than sign at the end", {"html": ld(RECIPE) + "a <"}),
    ("an unfinished tag at the end", {"html": ld(RECIPE) + '<div class="x'}),
    ("an unfinished comment at the end", {"html": ld(RECIPE) + "<!-- never closed " + ld(OTHER)}),
    ("no page at all", {"html": ""}),
    ("a page with no recipe data", {"html": PAGE_START + "</head><body><p>Just words.</p></body></html>"}),
]

ADDRESSES = [
    "93.184.216.34", "8.8.8.8", "1.1.1.1", "203.0.114.1", "10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.255", "172.32.0.1",
    "192.168.1.20", "127.0.0.1", "127.255.255.254", "0.0.0.0", "0.1.2.3", "169.254.1.1", "169.254.169.254", "169.254.170.2",
    "100.64.0.1", "100.127.255.255", "100.100.100.200", "100.128.0.1", "192.0.0.1", "192.0.0.9", "192.0.2.1", "198.18.0.1",
    "198.51.100.7", "203.0.113.9", "224.0.0.1", "239.255.255.250", "240.0.0.1", "255.255.255.255", "2606:4700:4700::1111",
    "2001:4860:4860::8888", "::1", "::", "::ffff:8.8.8.8", "::ffff:192.168.1.1", "::ffff:127.0.0.1", "::ffff:169.254.169.254",
    "fe80::1", "fec0::1", "fc00::1", "fd12:3456::1", "fd00:ec2::254", "ff02::1", "2001:db8::1", "2002:c0a8:0101::1", "2002:0808:0808::1",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2", "2001:0:4136:e378:8000:63bf:f7f7:f7f7", "64:ff9b::808:808", "64:ff9b::c0a8:101",
    "64:ff9b:1::a00:1", "::8.8.8.8", "::10.0.0.1", "::2", "100::1", "2001:20::1", "3fff::1", "4000::1", "2600::1",
]

LINKS = [
    "https://www.example.com/recipes/rice", "https://example.com", "HTTPS://Example.COM/Path?x=1#top", "http://example.com/recipe",
    "https://example.com:443/r", "https://example.com:80/r", "https://example.com:8443/r", "https://example.com:0/", "https://example.com:/r",
    "https://user:pw@example.com/", "https://user@example.com/", "https://@example.com/", "ftp://example.com/", "javascript:alert(1)",
    "https:example.com", "https:///path", "https://exa mple.com/", "https://example.com/a b", "https://example.com/\u0007", "", "example.com",
    "https://bücher.example/kuchen", "https://xn--bcher-kva.example/kuchen", "https://[2606:4700:4700::1111]/", "https://[::1]/",
    "https://[not-an-address]/", "https://192.168.1.20/recipe", "https://exa$mple.com/", "https://example.com:99999/", "https://example.com:x/",
    "https://example.com/" + "a" * 900, "https://example.com/" + "a" * 880, "https://my_site.example/r", "https://-x.example/",
    "https://example.com./r", "https://example.com?q=1", "https://example.com#frag", "https://[fe80::1%25en0]/", "https://exa%41mple.com/",
    "https://[::1]x:443/", "https://[::1]:443/", "https://x[::1]/", "https://[1:2:3:4:5:6:7:8:9]/", "https://[::ffff:1.2.3.4]/",
    "https://1.2.3.04/", "https://example.com:0443/", "https://example.com:+443/", "https://example.com/a%20b", "https://a:b:443/",
]

CHARSETS = [
    ("text/html; charset=utf-8", ""), ('text/html; charset="ISO-8859-1"', ""), ("text/html", '<meta charset="windows-1252">'),
    ("text/html", "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=Shift_JIS\">"), ("text/html; charset=nope", "<meta charset=utf-8>"),
    ("", ""), ("text/html;charset=UTF-8", '<meta charset="latin1">'), ("text/html", "<META CHARSET='koi8-r'>"),
    ("text/html", " " * 4090 + '<meta charset="latin1">'),
]

_HOST = re.compile(r"[A-Za-z0-9._-]+")


def phone_link(url: str) -> str:
    """``ok`` when the iPhone opens the link (the server's rule and more), else ``bad_link``."""
    try:
        fetch.check_page_url(url)
    except fetch.PageError as exc:
        return exc.code
    parts = urlsplit(url)
    host = parts.netloc.rsplit(":", 1)[0] if not parts.netloc.endswith("]") else parts.netloc
    if not url.isascii() or parts.scheme.lower() != "https" or "@" in parts.netloc or "%" in parts.netloc:
        return "bad_link"
    if host.startswith("["):
        try:
            egress.ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return "bad_link"
    elif not _HOST.fullmatch(host):
        return "bad_link"
    return "ok"


def server_link(url: str) -> str:
    try:
        fetch.check_page_url(url)
    except fetch.PageError as exc:
        return exc.code
    return "ok"


def charset_names(content_type: str, head: str) -> list[str]:
    """The names ``fetch._charset`` tries, in its order (the header's, then a ``<meta>`` in the first 4096 bytes)."""
    names = []
    found = re.search(r"charset\s*=\s*\"?([A-Za-z0-9_\-:.]+)", content_type or "", re.IGNORECASE)
    if found:
        names.append(found.group(1))
    meta = fetch._META_CHARSET.search(head.encode("utf-8")[:4096])
    if meta:
        names.append(meta.group(1).decode("ascii"))
    return names


def page_of(spec: dict[str, Any]) -> str:
    return spec["html"] if "html" in spec else "".join(text * times for text, times in spec["build"])


def strict(value: Any) -> Any:
    """The blocks as plain JSON: NaN and Infinity as null (JavaScript reads them so), and a text over 1000 characters as
    ``{"long_text": its length}``."""
    def clean(v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if isinstance(v, str) and len(v) > 1000:
            return {"long_text": len(v)}
        if isinstance(v, list):
            return [clean(x) for x in v]
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        return v
    return clean(value)


def page_case(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    page = page_of(spec)
    blocks = P.ld_json_blocks(page)
    recipe = None
    for block in blocks:
        recipe = P.find_recipe(block)
        if recipe is not None:
            break
    return {"name": name, **({"html": spec["html"]} if "html" in spec else {"build": spec["build"]}), "blocks": strict(blocks),
            "recipe": None if recipe is None else P.recipe_from_jsonld(recipe)}


def entity_names() -> dict[str, str]:
    """Every entity the browser twin knows, with Python's value: the HTML 4 names, apos and the capital forms with ";", and the
    legacy names that work without one."""
    h5 = html.entities.html5
    names = set(html.entities.name2codepoint) | {"apos", "AMP", "COPY", "GT", "LT", "QUOT", "REG"}
    out = {f"{n};": h5[f"{n};"] for n in names}
    out.update({k: v for k, v in h5.items() if not k.endswith(";")})
    return dict(sorted(out.items()))


def build() -> dict[str, Any]:
    return {
        "about": "A recipe page read on the iPhone (design note 30 §3; tests/data/gen_recipe_page_vectors.py). Made from "
                 "app/recipe_import/parse.py, fetch.py and app/egress.py; replayed by tests/js/run_vectors.mjs and the Swift package.",
        "constants": {"max_redirects": fetch.MAX_REDIRECTS, "max_page_bytes": fetch.MAX_PAGE_BYTES, "deadline_s": fetch.DEADLINE_S,
                      "allowed_ports": list(fetch.ALLOWED_PORTS), "html_types": list(fetch.HTML_TYPES), "max_blocks": P.MAX_BLOCKS,
                      "max_block_chars": P.MAX_BLOCK_CHARS, "messages": fetch.MESSAGES, "no_recipe": api.NO_RECIPE_TEXT,
                      "no_lines": api.NO_LINES_TEXT, "user_agent": brand.USER_AGENT_RECIPES},
        "entities": entity_names(),
        "entity_cases": [{"value": f"&{name}", "text": P.text_of(f"x &{name} y")} for name in sorted(entity_names())],
        "page_cases": [page_case(name, spec) for name, spec in PAGES],
        "address_cases": [{"address": a, "class": egress.classify_address(a)} for a in ADDRESSES],
        "link_cases": [{"url": u, "server": server_link(u), "phone": phone_link(u)} for u in LINKS],
        "charset_cases": [{"content_type": c, "head": h, "names": charset_names(c, h)} for c, h in CHARSETS],
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed file is stale")
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run python3 tests/data/gen_recipe_page_vectors.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    data = build()
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['page_cases'])} pages, {len(data['address_cases'])} addresses, "
          f"{len(data['link_cases'])} links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
