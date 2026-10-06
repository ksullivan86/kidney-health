"""The patient handbook at ``/learn`` (note 08 §4.6 and §4.10).

The handbook is a static MkDocs site (``handbook/``), built in the image's ``handbook`` stage into
``HANDBOOK_DIR`` (``/app/learn`` in the image; ``<repo>/handbook/site`` when run from source). This
module:

* loads it once at start-up (:func:`load`). The site is served only when ``HANDBOOK_DIR/index.html``
  exists; otherwise ``/learn`` answers 404 and the app's Learn links go to ``HANDBOOK_PUBLIC_URL``
  (the GitHub Pages copy) when that is set, or are hidden;
* hashes every inline ``<script>`` of every page it serves and builds the ``/learn``
  Content-Security-Policy from those hashes (:func:`handbook_csp`). Material for MkDocs needs a few
  small inline scripts per page (note 08 F3), so ``/learn`` allows exactly those, plus ``data:``
  images for the theme's icons, and no Trusted Types (the theme's search worker and instant
  navigation are not Trusted-Types clean). Never ``'unsafe-inline'``. The hashes are computed from
  the files actually served, so a theme update cannot leave the policy stale. The app's own strict
  policy stays unchanged on every other path (:func:`app.security.install` takes this one as a path
  policy for ``/learn`` only);
* mounts the site read-only before the ``/`` mount (:func:`mount`), with cache headers:
  fingerprinted theme assets (``assets/…/<name>.<8 hex>.min.js|css``) are ``immutable`` for a year,
  everything else is ``no-cache`` (revalidated with the ETag);
* answers ``GET /api/handbook`` for a signed-in person: whether this server has the handbook, where
  the Learn entry points, and the handbook pages the app's warnings, alerts and notes link to.

The handbook holds no personal data, so like the app shell it needs no sign-in (note 07 §4.10).
``StaticFiles`` never lists a directory (it serves ``index.html`` or the site's ``404.html`` with
status 404), and a path that leaves ``HANDBOOK_DIR`` (``..``, an absolute path, a symlink pointing
outside) answers 404.

Restart the app after rebuilding the site in place: the hashes are computed once, at start-up.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel
from starlette.requests import Request as StarletteRequest
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .auth.deps import current_user
from .config import Settings
from .guidance.topics import NUTRIENT_TOPIC, TOPIC_PAGES

log = logging.getLogger("kidney_health.handbook")

LEARN_PATH = "/learn"
LEARN_PREFIX = LEARN_PATH + "/"
# Material 9.7 has 4 inline scripts per page and one variant per directory depth (about 8 hashes for
# this site). Far more means something other than the theme put scripts into the pages.
MAX_INLINE_SCRIPTS = 64
IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"
# Material's fingerprinted bundles: assets/javascripts/bundle.79ae519e.min.js,
# assets/stylesheets/main.484c7ddc.min.css, assets/javascripts/workers/search.2c215733.min.js.
FINGERPRINTED = re.compile(r"^/learn/assets/(?:[^/]+/)*[^/]+\.[0-9a-f]{8}\.min\.(?:js|css)$")

# Script types a browser executes (HTML "JavaScript MIME type essence match", plus module) and the
# other inline script types that script-src also governs (import maps, speculation rules). Any other
# type, such as Material's <script id="__config" type="application/json">, is data, not code.
_JS_MIME_TYPES = frozenset(
    {
        "application/ecmascript", "application/javascript", "application/x-ecmascript",
        "application/x-javascript", "text/ecmascript", "text/javascript", "text/javascript1.0",
        "text/javascript1.1", "text/javascript1.2", "text/javascript1.3", "text/javascript1.4",
        "text/javascript1.5", "text/jscript", "text/livescript", "text/x-ecmascript", "text/x-javascript",
    }
)
_POLICED_TYPES = _JS_MIME_TYPES | {"module", "importmap", "speculationrules"}


class HandbookError(Exception):
    """The built handbook cannot be served safely (unreadable page, too many inline scripts)."""


# --------------------------------------------------------------------------- #
# Inline-script hashes and the /learn policy
# --------------------------------------------------------------------------- #


def _policed(script_type: str | None) -> bool:
    """True when the browser applies ``script-src`` to an inline script with this ``type``."""
    if script_type is None:
        return True
    essence = script_type.split(";", 1)[0].strip().lower()
    return essence == "" or essence in _POLICED_TYPES


class _InlineScripts(HTMLParser):
    """Collects the text of every inline script the browser would run (no ``src``, a script type)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)  # script text is raw; never decode it
        self.scripts: list[str] = []
        self._buffer: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        names = {name.lower(): value for name, value in attrs}
        self._buffer = [] if ("src" not in names and _policed(names.get("type"))) else None

    def handle_data(self, data: str) -> None:
        if self._buffer is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._buffer is not None:
            self.scripts.append("".join(self._buffer))
            self._buffer = None


def script_hash(text: str) -> str:
    """CSP source expression for one inline script: ``'sha256-<base64>'``.

    Browsers hash the script element's text after normalising line breaks to ``\\n`` (HTML input
    stream preprocessing), so the same is done here.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    digest = hashlib.sha256(normalised.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


# Candidate script elements: a cheap scan so that only these fragments go through the HTML parser
# (about 20 times faster than parsing every page). A match inside a comment only adds a harmless hash.
_SCRIPT_ELEMENT = re.compile(r"<script\b.*?</script\s*>", re.S | re.I)


def inline_scripts(html: str) -> list[str]:
    """The inline scripts of one HTML document that ``script-src`` governs."""
    scripts: list[str] = []
    for element in _SCRIPT_ELEMENT.findall(html):
        parser = _InlineScripts()
        parser.feed(element)
        parser.close()
        scripts.extend(parser.scripts)
    return scripts


def html_pages(site: Path) -> list[Path]:
    """Every ``*.html`` file the ``/learn`` mount can serve, in a stable order.

    Symlinks are not followed into directories, and a file whose real path is outside ``site`` is
    skipped: ``StaticFiles`` refuses to serve it, so its scripts must not be allowed either.
    """
    root = site.resolve()
    pages: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):  # followlinks=False
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith(".html"):
                continue
            path = Path(dirpath) / name
            real = path.resolve()
            if not real.is_relative_to(root) or not real.is_file():
                continue
            pages.append(path)
    return pages


def inline_script_hashes(site: Path, limit: int = MAX_INLINE_SCRIPTS) -> tuple[str, ...]:
    """Sorted, distinct hashes of the inline scripts of every served page of ``site``.

    Raises :class:`HandbookError` when a page cannot be read as UTF-8 or when there are more than
    ``limit`` distinct scripts (a sign that something other than the theme added scripts).
    """
    hashes: set[str] = set()
    for page in html_pages(site):
        try:
            text = page.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HandbookError(f"{page} is not UTF-8 text") from None
        except OSError as exc:
            raise HandbookError(f"cannot read {page}: {exc.strerror or exc}") from None
        hashes.update(script_hash(script) for script in inline_scripts(text))
        if len(hashes) > limit:
            raise HandbookError(
                f"more than {limit} different inline scripts (found while reading {page.relative_to(site.resolve())}); "
                "refusing to build a Content-Security-Policy that allows them all. Rebuild the handbook from "
                "handbook/ with the locked toolchain (handbook/requirements.lock)."
            )
    return tuple(sorted(hashes))


def handbook_csp(hashes: tuple[str, ...] | list[str]) -> str:
    """The ``/learn`` Content-Security-Policy (note 08 §3.3, F3): the app's policy minus Trusted
    Types, plus the theme's inline scripts by hash and ``data:`` images (the theme's icons)."""
    script_src = " ".join(("'self'", *hashes))
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src {script_src}",
            "style-src 'self'",
            "img-src 'self' data:",
            "font-src 'self'",
            "connect-src 'self'",
            "worker-src 'self'",
            "manifest-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


# --------------------------------------------------------------------------- #
# Loading and mounting
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HandbookSite:
    """A built handbook that passed the start-up checks."""

    directory: Path
    pages: int
    hashes: tuple[str, ...]
    csp: str


def load(settings: Settings) -> HandbookSite | None:
    """The built handbook at ``HANDBOOK_DIR``, or None when there is none to serve (``/learn`` is then 404).

    Problems are logged, never raised: the food log must start even when the handbook is broken.
    """
    directory = settings.handbook_dir
    if directory is None:
        return None
    fallback = (
        f"; the app's Learn links go to HANDBOOK_PUBLIC_URL ({settings.handbook_public_url})"
        if settings.handbook_public_url
        else "; the app hides its Learn links (set HANDBOOK_PUBLIC_URL to link to a published copy)"
    )
    if not (directory / "index.html").is_file():
        if directory.exists():
            log.warning("HANDBOOK_DIR %s has no index.html, so /learn answers 404%s", directory, fallback)
        else:
            log.info(
                "no built handbook at %s, so /learn answers 404%s. Build it with: cd handbook && mkdocs build "
                "(docs: handbook/README.md)",
                directory,
                fallback,
            )
        return None
    try:
        pages = html_pages(directory)
        hashes = inline_script_hashes(directory)
    except (HandbookError, OSError) as exc:
        log.error("the handbook at %s is not served, so /learn answers 404%s: %s", directory, fallback, exc)
        return None
    site = HandbookSite(directory=directory.resolve(), pages=len(pages), hashes=hashes, csp=handbook_csp(hashes))
    log.info("handbook: serving %d pages from %s at /learn/ (%d inline-script hashes)", site.pages, site.directory, len(hashes))
    return site


def csp_policies(site: HandbookSite | None) -> tuple[tuple[str, str], ...]:
    """``path_policies`` for :func:`app.security.install`: the ``/learn`` policy when the site is served."""
    return ((LEARN_PATH, site.csp),) if site is not None else ()


def cache_control_for(path: str, status_code: int) -> str:
    """``Cache-Control`` for a ``/learn`` response."""
    if status_code in (200, 304) and FINGERPRINTED.match(path):
        return IMMUTABLE
    return NO_CACHE


class HandbookStaticFiles(StaticFiles):
    """``StaticFiles`` for the handbook with its cache headers."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        url_path = scope.get("path", "")
        response.headers["Cache-Control"] = cache_control_for(url_path, response.status_code)
        if url_path.endswith(".gz") and response.status_code == 200:
            # sitemap.xml.gz: Python guesses application/xml + gzip encoding; it is a gzip file.
            response.headers["Content-Type"] = "application/gzip"
        return response


async def _to_learn_index(request: StarletteRequest) -> Response:
    """``/learn`` → ``/learn/`` (the mount itself only matches paths below ``/learn/``)."""
    query = request.url.query
    response = RedirectResponse(LEARN_PREFIX + (f"?{query}" if query else ""), status_code=308)
    response.headers["Cache-Control"] = NO_CACHE
    return response


def mount(app: FastAPI, site: HandbookSite | None) -> bool:
    """Serve ``site`` at ``/learn`` (call before the ``/`` static mount, which would otherwise win)."""
    if site is None:
        return False
    if any(isinstance(route, Mount) and route.path == "" for route in app.router.routes):
        raise RuntimeError("mount the handbook before the '/' static mount")
    app.router.add_route(LEARN_PATH, _to_learn_index, methods=["GET", "HEAD"], include_in_schema=False)
    app.mount(LEARN_PATH, HandbookStaticFiles(directory=str(site.directory), html=True), name="learn")
    return True


def setup(app: FastAPI, settings: Settings) -> HandbookSite | None:
    """Load the handbook and keep it on ``app.state.handbook`` (None when there is none)."""
    site = load(settings)
    app.state.handbook = site
    return site


# --------------------------------------------------------------------------- #
# GET /api/handbook
# --------------------------------------------------------------------------- #


def _topic(slug: str) -> dict[str, str]:
    page = TOPIC_PAGES[slug]
    return {"path": page["url"].removeprefix(LEARN_PREFIX), "title": page["title"]}


def _page(path: str, title: str) -> dict[str, str]:
    return {"path": path, "title": title}


# What the app links to, as paths under the handbook's base URL (note 08 §4.10). Nutrient pages come
# from app/guidance/topics.py, the one slug table; tests/test_learn_links.py checks every path.
LINKS: dict[str, dict[str, dict[str, str]]] = {
    # Per-serving warnings and daily alerts, by nutrient key (app/nutrients.py).
    "nutrients": {nutrient: _topic(slug) for nutrient, slug in NUTRIENT_TOPIC.items()},
    # Food flags that cause or change a warning (app/nutrients.py FLAGS; potassium_additive: ARCHITECTURE
    # v0.3 decision 9).
    "flags": {
        "avoid_ckd": _page("eat/food-lists/", "Food lists"),
        "phosphate_additive": _topic("phosphate-additives"),
        "potassium_additive": _topic("label-reading"),
        "high_gi": _topic("carb-counting"),
        "hypo_treatment": _topic("treating-a-low"),
    },
    # Pages the app links to by name.
    "pages": {
        "home": _page("", "Kidney Health Handbook"),
        "targets": _topic("targets-and-warnings"),
        "first_setup": _page("app/first-setup/", "First setup"),
        "get_help_now": _topic("get-help-now"),
        "blood_potassium": _topic("blood-potassium"),
        "treating_a_low": _topic("treating-a-low"),
    },
}


class HandbookLink(BaseModel):
    path: str  # relative to ``url``, ending in "/" ("" is the start page)
    title: str


class HandbookInfo(BaseModel):
    available: bool  # this server serves the built handbook at /learn/
    url: str | None  # where the Learn entry points: "/learn/", HANDBOOK_PUBLIC_URL, or None (hide it)
    public_url: str | None  # HANDBOOK_PUBLIC_URL (always ends in "/"), shown in Settings → About
    links: dict[str, dict[str, HandbookLink]]


def info(site: HandbookSite | None, settings: Settings) -> dict[str, Any]:
    """The ``GET /api/handbook`` body."""
    public = settings.handbook_public_url
    return {
        "available": site is not None,
        "url": LEARN_PREFIX if site is not None else public,
        "public_url": public,
        "links": LINKS,
    }


router = APIRouter(prefix="/api/handbook", tags=["handbook"], dependencies=[Depends(current_user)])


@router.get("", response_model=HandbookInfo)
def handbook_info(request: Request) -> dict[str, Any]:
    """Where the app's Learn links go, and the pages warnings, alerts and notes link to."""
    return info(getattr(request.app.state, "handbook", None), request.app.state.settings)


# --------------------------------------------------------------------------- #
# python -m app.handbook csp DIR
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    """Print the Content-Security-Policy for a built handbook.

    For operators who serve the handbook from its own host name (docs/security.md): their reverse
    proxy sends this header there, so the handbook keeps the same policy as at ``/learn``.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m app.handbook", description=main.__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    csp = sub.add_parser("csp", help="print the Content-Security-Policy header value for a built handbook")
    csp.add_argument("site", type=Path, nargs="?", default=None,
                     help="the built site (default: HANDBOOK_DIR, else <repo>/handbook/site)")
    args = parser.parse_args(argv)
    if args.site is None:
        from .config import DEFAULT_HANDBOOK_DIR

        args.site = Path(os.environ.get("HANDBOOK_DIR") or DEFAULT_HANDBOOK_DIR)
    if not (args.site / "index.html").is_file():
        print(f"{args.site} is not a built handbook (no index.html); build it with: cd handbook && mkdocs build", file=sys.stderr)
        return 2
    try:
        hashes = inline_script_hashes(args.site)
    except HandbookError as exc:
        print(f"cannot build a policy for {args.site}: {exc}", file=sys.stderr)
        return 1
    print(handbook_csp(hashes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
