"""Check every internal link and anchor in a built handbook site (stdlib only, no network).

Usage (after `mkdocs build --strict`, from the repository root):

    python3 handbook/tools/check_links.py handbook/site            # internal links and #anchors
    python3 handbook/tools/check_links.py handbook/site --external # also list external URLs
    python3 handbook/tools/check_links.py site --allow /           # the image build: "/" is the app

Relative links are resolved against the page that contains them; a directory resolves to its
index.html. Absolute paths must stay under --base (default /learn/, where the app serves the site),
except the exact paths given with --allow (repeatable): the build the image serves links "Back to the
food log" to "/", the app itself (HANDBOOK_APP_LINK=/).
Exits 1 if any link points at a missing file or a missing #anchor. External links are not fetched
(the weekly handbook-links workflow does that).
"""
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        if tag == "link" and a.get("rel") == "canonical":
            return  # canonical URLs point at site_url, not at the local copy
        for key in ("href", "src"):
            if a.get(key):
                self.links.append(a[key])

    handle_startendtag = handle_starttag


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    site = Path(argv[0]).resolve()
    base = argv[argv.index("--base") + 1] if "--base" in argv else "/learn/"
    allowed = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--allow"}
    pages: dict[Path, _Page] = {}
    for f in site.rglob("*.html"):
        p = _Page()
        p.feed(f.read_text("utf-8", errors="replace"))
        pages[f.resolve()] = p

    broken: list[str] = []
    external: set[str] = set()
    checked = 0
    for f, p in pages.items():
        rel = f.relative_to(site)
        for url in p.links:
            if url.startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            u = urlsplit(url)
            if u.scheme or u.netloc:
                external.add(url)
                continue
            checked += 1
            path = unquote(u.path)
            if path.startswith("/"):
                if path in allowed and not path.startswith(base):
                    continue
                if not path.startswith(base):
                    broken.append(f"{rel}: {url} (absolute path outside {base})")
                    continue
                target = site / path[len(base):]
            else:
                target = f if path == "" else f.parent / path
            target = target.resolve()
            if target.is_dir():
                target = target / "index.html"
            if site not in target.parents and target != site:
                broken.append(f"{rel}: {url} (leaves the site)")
            elif not target.exists():
                broken.append(f"{rel}: {url} (missing)")
            elif u.fragment and target.suffix == ".html" and target in pages and u.fragment not in pages[target].ids:
                broken.append(f"{rel}: {url} (no such anchor)")

    print(f"{len(pages)} pages, {checked} internal links, {len(broken)} broken, {len(external)} external URLs")
    for line in broken:
        print("BROKEN", line)
    if "--external" in argv:
        for url in sorted(external):
            print("EXTERNAL", url)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
