"""Every link the app makes into the handbook resolves to a page (note 08 §4.10).

The links come from three places, and all of them are checked here:

* ``/learn/...`` written anywhere in ``app/static`` (HTML, JS, CSS) or in any Python module of ``app``
  (guidance messages and tips, target notes, docstrings): a scan of the source text;
* ``app/guidance/topics.py`` ``TOPIC_PAGES`` (the slug table) and ``app/handbook.py`` ``LINKS`` (what
  warnings, alerts and notes link to), imported.

A link resolves when ``handbook/docs`` has the page MkDocs builds at that URL (``<path>.md`` or
``<path>/index.md``, not excluded by ``mkdocs.yml``) and, for ``#anchor`` links, a heading or element
with that id. When ``HANDBOOK_BUILT_SITE`` names a built site (CI's handbook job), each link must also
exist there as built HTML, anchors included. Builders who add views or messages with handbook links
need nothing else: their links are picked up by the scan.
"""
from __future__ import annotations

import os
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app import handbook, nutrients
from app.guidance import topics

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "handbook" / "docs"
BUILT = Path(os.environ["HANDBOOK_BUILT_SITE"]) if os.environ.get("HANDBOOK_BUILT_SITE") else None

LEARN_LINK = re.compile(r"/learn/([A-Za-z0-9._~%/-]*)(#[A-Za-z0-9_-]+)?")
# app/handbook.py is checked through its LINKS table (its source also holds the cache-header regex).
SCANNED = sorted(
    [p for p in (REPO / "app" / "static").rglob("*") if p.suffix in (".html", ".js", ".css", ".webmanifest") and "vendor" not in p.parts]
    + [p for p in (REPO / "app").rglob("*.py") if "__pycache__" not in p.parts and p != REPO / "app" / "handbook.py"]
)


def scanned_links() -> dict[str, list[str]]:
    """``"<path>#<anchor>"`` (path relative to /learn/) → the files that contain it."""
    found: dict[str, list[str]] = {}
    for path in SCANNED:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in LEARN_LINK.finditer(text):
            if "..." in m.group(1):
                continue  # a placeholder in prose ("/learn/..."), not a link
            found.setdefault(m.group(1) + (m.group(2) or ""), []).append(str(path.relative_to(REPO)))
    return found


def table_links() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for slug, page in topics.TOPIC_PAGES.items():
        assert page["url"].startswith("/learn/"), (slug, page)
        found.setdefault(page["url"].removeprefix("/learn/"), []).append(f"app/guidance/topics.py:{slug}")
    for group, entries in handbook.LINKS.items():
        for key, entry in entries.items():
            found.setdefault(entry["path"], []).append(f"app/handbook.py LINKS[{group}][{key}]")
    return found


ALL_LINKS = {**scanned_links()}
for _target, _where in table_links().items():
    ALL_LINKS.setdefault(_target, []).extend(_where)


# --------------------------------------------------------------------------- resolving a link
_EXCLUDED = (re.compile(r"(^|/)_drafts/"), re.compile(r"(^|/)_[^/]*\.md$"))  # mkdocs.yml exclude_docs


def _slugify(text: str) -> str:
    """Python-Markdown's toc slugify (the default MkDocs uses for heading ids)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\[[^\]]*\]", lambda m: m.group(1) or m.group(2) or "", text)
    text = re.sub(r"<[^>]+>|[*_`]", "", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def source_ids(page: Path) -> set[str]:
    """Heading ids (explicit ``{#id}`` or slugified text, de-duplicated like the toc does) and HTML ids."""
    ids: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*(\{[^}]*\})?\s*#*\s*$", line)
        if m:
            explicit = re.search(r"#([\w-]+)", m.group(2) or "")
            slug = explicit.group(1) if explicit else _slugify(m.group(1))
            n = counts.get(slug, 0)
            counts[slug] = n + 1
            ids.add(slug if n == 0 else f"{slug}_{n}")
        ids.update(re.findall(r"""\bid=["']([\w-]+)["']""", line))
        ids.update(re.findall(r"\{[^}]*#([\w-]+)[^}]*\}", line))
    return ids


def source_page(path: str) -> Path | None:
    """The Markdown file MkDocs builds at ``/learn/<path>`` (use_directory_urls), or None."""
    if path == "":
        candidates = [DOCS / "index.md"]
    elif path.endswith("/"):
        stem = path[:-1]
        candidates = [DOCS / f"{stem}.md", DOCS / stem / "index.md"]
    else:
        candidates = [DOCS / path]  # an asset (icon, PDF, wallet card); pages must end with "/"
    for c in candidates:
        rel = c.relative_to(DOCS).as_posix()
        if c.is_file() and not any(p.search(rel) for p in _EXCLUDED):
            return c
    return None


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("id", "name") and value:
                self.ids.add(value)


def check(target: str) -> list[str]:
    """Problems with one link target (empty when it resolves)."""
    path, _, anchor = target.partition("#")
    problems: list[str] = []
    if ".." in path.split("/") or path.startswith("/"):
        return [f"/learn/{target} leaves the handbook"]
    page = source_page(path)
    if page is None:
        hint = " (page links must end with '/')" if path and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1] else ""
        return [f"/learn/{target}: no page in handbook/docs builds at /learn/{path}{hint}"]
    if anchor and page.suffix == ".md" and anchor not in source_ids(page):
        problems.append(f"/learn/{target}: {page.relative_to(REPO)} has no heading or element with id {anchor!r}")
    if BUILT is not None:
        built = BUILT / path / "index.html" if (path == "" or path.endswith("/")) else BUILT / path
        if not built.is_file():
            problems.append(f"/learn/{target}: not in the built site ({built})")
        elif anchor and built.suffix == ".html":
            parser = _Ids()
            parser.feed(built.read_text(encoding="utf-8"))
            if anchor not in parser.ids:
                problems.append(f"/learn/{target}: the built page has no id {anchor!r}")
    return problems


# --------------------------------------------------------------------------- the tests
@pytest.mark.parametrize("target", sorted(ALL_LINKS), ids=lambda t: t or "(start page)")
def test_every_learn_link_resolves(target: str) -> None:
    problems = check(target)
    assert not problems, "; ".join(problems) + f" — linked from {', '.join(sorted(set(ALL_LINKS[target])))}"


def test_the_scan_sees_the_known_links() -> None:
    """Guards the scan itself: links written in Python messages and the topic table are found."""
    scanned = scanned_links()
    assert "t1d/treating-a-low/" in scanned  # app/guidance/messages.py, the treating-a-low card
    assert "" in scanned  # the Learn entry in index.html (/learn/)
    tables = table_links()
    for slug in ("potassium", "phosphate-additives", "get-help-now", "blood-potassium", "targets-and-warnings"):
        assert topics.TOPIC_PAGES[slug]["url"].removeprefix("/learn/") in tables, slug


def test_checker_rejects_what_would_break() -> None:
    assert check("eat/potassium/") == []
    assert check("eat/potassium/#in-short") == []  # "## In short"
    assert check("eat/potassium/#get-help-now-if") == []  # "## Get help now if…" (punctuation dropped)
    assert check("eat/no-such-page/")
    assert check("eat/potassium")  # no trailing slash: a redirect at best
    assert check("eat/_targets-table/")  # an excluded snippet is not a page
    assert check("eat/potassium/#no-such-heading")
    assert check("../app/config.py")


def test_warnings_alerts_and_flags_have_a_handbook_page() -> None:
    links = handbook.LINKS
    for key in nutrients.WARNING_ORDER:
        assert key in links["nutrients"], f"per-serving warnings on {key} have no handbook page"
    for key, slug in topics.NUTRIENT_TOPIC.items():
        assert links["nutrients"][key]["path"] == topics.TOPIC_PAGES[slug]["url"].removeprefix("/learn/")
    for flag in ("avoid_ckd", "phosphate_additive", "high_gi", "hypo_treatment"):
        assert flag in nutrients.FLAGS and flag in links["flags"], flag
    assert set(links["pages"]) >= {"home", "targets", "get_help_now"}


def test_titles_match_the_pages() -> None:
    """The link text ("Learn: <title>") is the page's own title, so it never promises another page."""
    for group, entries in handbook.LINKS.items():
        for key, entry in entries.items():
            page = source_page(entry["path"])
            assert page is not None, (group, key)
            title = re.search(r"^title:\s*\"?(.+?)\"?\s*$", page.read_text(encoding="utf-8"), re.M)
            if key == "home":
                continue  # the start page's title is "Start here"; the link names the whole handbook
            assert title and title.group(1) == entry["title"], (group, key, title and title.group(1), entry["title"])
