"""The handbook inside the iPhone app (owner, 2026-11-26): ``scripts/build_preview.py --device DIR --handbook SITE``.

The built handbook (``mkdocs build``) is packed into ``DIR/learn/`` with no inline script, a strict Content-Security-Policy on every
page and nothing from the network; the app shows it in a sheet of its own (``ios/KidneyHealth/WebShell/HelpPages.swift``), and the
page's Learn links point there (``js/mock/handbook.js``). Without ``--handbook`` Learn links go to the published copy in Safari.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_preview  # noqa: E402

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="canonical" href="http://localhost/learn/eat/potassium/">
<link rel="stylesheet" href="../../assets/stylesheets/main.css">
<script>__md_scope=new URL("../..",location)</script>
</head>
<body>
<script>var palette=__md_get("__palette")</script>
<a href="https://kdigo.org/guidelines/">KDIGO</a>
<script id="__config" type="application/json">{"base": "../..", "features": ["navigation.instant", "navigation.instant.progress", "navigation.tabs"], "search": "assets/javascripts/workers/search.js"}</script>
<script src="../../assets/javascripts/bundle.js"></script>
</body>
</html>
"""


def site(tmp_path: Path, page: str = PAGE) -> Path:
    root = tmp_path / "site"
    for rel, text in {
        "index.html": page.replace("../..", "."),
        "eat/potassium/index.html": page,
        "404.html": page,
        "sitemap.xml": "<urlset/>",
        "sitemap.xml.gz": "x",
        "assets/javascripts/bundle.js": "1",
        "assets/javascripts/bundle.js.map": "{}",
        "assets/javascripts/lunr/min/lunr.de.min.js": "1",
        "assets/javascripts/workers/search.js": "1",
        "assets/stylesheets/main.css": "body{}",
        "search/search_index.json": "{}",
        "assets/licences/material-LICENSE.txt": "MIT",
        ".hidden.js": "1",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_the_handbook_is_packed_without_inline_scripts_and_with_a_strict_policy(tmp_path):
    out = tmp_path / "out"
    written = build_preview.pack_handbook(site(tmp_path), out)
    learn = out / "learn"
    names = sorted(p.relative_to(learn).as_posix() for p in written)
    assert "404.html" not in names and "sitemap.xml" not in names and "sitemap.xml.gz" not in names and ".hidden.js" not in names
    assert not any(n.endswith(".map") or "/lunr/" in n for n in names)
    assert {"index.html", "eat/potassium/index.html", "search/search_index.json", "assets/javascripts/workers/search.js",
            "assets/licences/material-LICENSE.txt"} <= set(names)
    page = (learn / "eat" / "potassium" / "index.html").read_text(encoding="utf-8")
    assert f'<meta http-equiv="Content-Security-Policy" content="{build_preview.HANDBOOK_CSP}">' in page
    assert "script-src 'self';" in build_preview.HANDBOOK_CSP and "unsafe" not in build_preview.HANDBOOK_CSP
    scripts = [s for s in page.split("<script")[1:]]
    assert all(s.lstrip().startswith(("src=", 'id="__config" type="application/json"')) for s in scripts), scripts
    assert '<script src="../../assets/javascripts/inline/' in page and "canonical" not in page
    config = json.loads(page.split('type="application/json">')[1].split("</script>")[0])
    assert config["features"] == ["navigation.tabs"]  # no instant loading: it reads the sitemap, which is not packed
    inline = sorted((learn / "assets" / "javascripts" / "inline").iterdir())
    bodies = {p.read_text(encoding="utf-8") for p in inline}
    assert 'var palette=__md_get("__palette")' in bodies and '__md_scope=new URL("../..",location)' in bodies
    assert '__md_scope=new URL(".",location)' in bodies  # the start page's own scope
    # the same script in the same order where it was
    top = (learn / "index.html").read_text(encoding="utf-8")
    assert top.index('src="assets/javascripts/inline/') < top.index('src="./assets/javascripts/bundle.js"')
    assert '<a href="https://kdigo.org/guidelines/">' in page  # a source link stays: the app opens it in Safari


@pytest.mark.parametrize("bad, why", [
    ('<p style="color:red">x</p>', "inline style"),
    ("<style>p{}</style>", "inline style"),
    ('<script src="https://cdn.example.com/x.js"></script>', "network"),
    ('<link rel="stylesheet" href="https://fonts.googleapis.com/css">', "network"),
    ('<img src="//example.com/x.png">', "network"),
])
def test_a_page_with_an_inline_style_or_a_network_file_is_refused(tmp_path, bad, why):
    with pytest.raises(SystemExit) as refused:
        build_preview.pack_handbook(site(tmp_path, PAGE.replace("</body>", bad + "</body>")), tmp_path / "out")
    assert why in str(refused.value)


def test_not_a_built_handbook_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        build_preview.pack_handbook(tmp_path, tmp_path / "out")


def test_the_flag_points_learn_links_at_the_packed_handbook_only_when_it_is_there():
    local = build_preview.device_flag_js(local_handbook=True)
    public = build_preview.device_flag_js()
    assert '"url": "learn/"' in local and '"local": true' in local and f'"public": "{build_preview.DEVICE_HANDBOOK}"' in local
    assert f'"url": "{build_preview.DEVICE_HANDBOOK}"' in public and '"local"' not in public


def test_the_device_build_packs_the_handbook_and_its_flag(tmp_path):
    out = tmp_path / "device"
    build_preview.build_device(out, handbook=site(tmp_path))
    assert (out / "learn" / "index.html").is_file() and (out / "index.html").is_file()
    assert '"local": true' in (out / build_preview.DEVICE_FLAG).read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        build_preview.main(["--handbook", str(tmp_path)])  # only with --device


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_answers_like_a_server_that_serves_the_handbook():
    script = """
import { loadDemo, newDemo } from './tests/js/demo_loader.mjs';
const links = { nutrients: {}, flags: {}, pages: { home: { path: '', title: 'Home' } } };
const out = {};
for (const [name, flag] of [['local', { url: 'learn/', local: true, public: 'https://example.org/hb/', links }], ['public', { url: 'https://example.org/hb/', links }]]) {
  const KH = loadDemo({ globals: { KDL_DEMO_HANDBOOK: flag } });
  const api = newDemo(KH);
  const r = api.handle('GET', '/api/handbook');
  out[name] = { available: r.available, url: r.url, public_url: r.public_url };
}
console.log(JSON.stringify(out));
"""
    got = json.loads(subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True,
                                    timeout=60).stdout)
    assert got["local"] == {"available": True, "url": "http://localhost/learn/", "public_url": "https://example.org/hb/"}
    assert got["public"] == {"available": False, "url": "https://example.org/hb/", "public_url": "https://example.org/hb/"}


def test_the_app_shows_help_pages_in_a_sheet_and_nothing_else():
    shell = ROOT / "ios" / "KidneyHealth" / "WebShell"
    help_pages = (shell / "HelpPages.swift").read_text(encoding="utf-8")
    view = (shell / "WebAppView.swift").read_text(encoding="utf-8")
    config = (shell / "WebShellConfig.swift").read_text(encoding="utf-8")
    assert 'static let helpFolder: String? = "learn"' in config
    intercept = view[view.index("if HelpPages.relativePath(for: url) != nil {"):]
    assert intercept.index("HelpPages.present(url)") < intercept.index("decisionHandler(.cancel)") < intercept.index("return")
    assert "configuration.websiteDataStore = .nonPersistent()" in help_pages
    assert "setURLSchemeHandler(HelpPagesSchemeHandler(), forURLScheme: WebShellConfig.scheme)" in help_pages
    assert 'if (url.scheme == "https" || url.scheme == "tel"), action.navigationType == .linkActivated {' in help_pages
    for word in ("URLSession", "Keychain", "UserDefaults", "evaluateJavaScript", "addScriptMessageHandler", "kidney", "Kidney"):
        assert word not in help_pages, word  # no network, no secrets, no messages from the pages; product-neutral


def test_the_ios_builds_pack_the_handbook():
    for workflow in ("ci.yml", "testflight.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        build = text.index('mkdocs build --strict -d "$RUNNER_TEMP/handbook"')
        assert '--require-hashes --only-binary=:all: -r "$RUNNER_TEMP/handbook.lock"' in text[:build], workflow  # the lock minus watchdog
        assert build < text.index('python scripts/build_preview.py --device ios/WebApp --handbook "$RUNNER_TEMP/handbook"'), workflow
