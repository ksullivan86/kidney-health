"""MkDocs hook: where the menu days' "Add this day to my plan" links point (ROADMAP v0.4).

scripts/build_handbook.py writes each menu day's link with the placeholder ``@KH_APP@`` in front of the hash
(``@KH_APP@#plan-menu?items=...``), because the committed pages must not depend on where the handbook is built.
This hook, run by ``mkdocs build`` for every page, turns the placeholder into

* the app's address, when ``extra.app_link`` is set (the image build: ``HANDBOOK_APP_LINK=/``, so the link is
  ``/#plan-menu?items=...`` and the app, which serves the handbook at ``/learn/``, asks before it saves anything);
* else the demo's address, when ``extra.demo_link`` is set (the GitHub Pages build: ``demo/``, written relative to
  the page; the link text says "demo");
* else nothing: the paragraph is dropped (there is no app to open).

The link carries only built-in food numbers and servings; no script runs on the handbook side and the handbook never
sees the app's session. Plain standard library: no MkDocs import, so tests/test_menu_plan.py can call it directly.
"""
from __future__ import annotations

import re

TOKEN = "@KH_APP@"
DEMO_TEXT = "Try this day in the app’s demo"
_PARAGRAPH = re.compile(r'<p class="kh-plan-day">.*?</p>\s*', re.S)
_ANCHOR = re.compile(r'(<a class="kh-plan-link" href=")' + re.escape(TOKEN) + r'([^"]*">)[^<]*(</a>)')


def _up_to_site_root(page_url: str) -> str:
    """``../`` for every directory between the page and the site root (the browser resolves links from the page's folder)."""
    url = page_url or ""
    folder = url.rstrip("/") if (url.endswith("/") or not url) else url.rpartition("/")[0]
    return "../" * len([part for part in folder.split("/") if part])


def on_page_content(html: str, page=None, config=None, files=None) -> str:
    if TOKEN not in html:
        return html
    extra = (config or {}).get("extra") or {}
    app_link = str(extra.get("app_link") or "")
    demo_link = str(extra.get("demo_link") or "")
    if app_link:
        return html.replace(TOKEN, app_link)
    if demo_link:
        base = _up_to_site_root(getattr(page, "url", "")) + demo_link
        html = _ANCHOR.sub(lambda m: m.group(1) + base + m.group(2) + DEMO_TEXT + m.group(3), html)
        return html.replace(TOKEN, base)
    return _PARAGRAPH.sub(lambda m: "" if TOKEN in m.group(0) else m.group(0), html)
