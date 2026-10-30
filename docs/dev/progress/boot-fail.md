Status: complete

# "The app did not start" notice and the VPN troubleshooting section

Task: over NetBird only the header shows (v0.10). Every view in `index.html` is `hidden` until the scripts boot, so a
script that never arrives or throws leaves the header and nothing else. Commit locally only (no push, no PR).

## Done
* `app/static/index.html`: `<section id="boot-fail">` first in `<main>`, with `#boot-fail-reason`, a Reload link to `/`
  and a link to `/learn/self-hosting/troubleshooting/#only-the-header-shows-over-a-vpn`.
* `css/base.css`: `.boot-fail` is `visibility: hidden` and a zero-length animation with an 8 s delay makes it visible
  (`!important` so the reduced-motion `* { animation: none !important }` does not cancel it). `.boot-fail-now` shows it
  at once. No CSS at all: the section shows unstyled, which is also fine.
* `js/main.js`: the whole boot sits in try/catch; `init().then(booted, bootFailed)`. `booted` sets `hidden`;
  `bootFailed` writes "The app could not start: <reason>. Try reloading." and adds `.boot-fail-now`. `KH.pwa.init()` has
  its own try/catch (a PWA failure must not stop the app).
* `theme-init.js`: keeps the first `error` event message in `window.KDL_BOOT_ERROR` (the reason preferred by bootFailed).
* `scripts/build_preview.py`: Pages demo maps `href="/"` to `./` and every `href="/learn/…"` to `../…` (prefix).
* Docs: `docs/deployment.md` "### Only the header shows over a VPN"; handbook self-hosting troubleshooting section of the
  same name (prose only, links to the guide for commands); sources NETBIRD-CLI, NETBIRD-ROUTES in `handbook/sources.yml`
  (regenerated with `scripts/build_handbook.py --write`). NetBird facts checked on docs.netbird.io 2026-10-30
  (`netbird up --mtu`, default 1280; routing peers: forward chain, masquerade). nftables rule from the nftables wiki.

* Tests: `tests/test_boot_fail.py` (markup, CSS reveal, boot hide, Pages links, docs), `tests/js/boot_fail.test.mjs`
  (runs main.js with a stub KH), `tools/e2e/boot_fail.py` (listed in tools/e2e/README.md and tests/test_e2e_tools.py).
* CHANGELOG (Unreleased, for people using the app) and ARCHITECTURE (the js/main.js boot, the Pages link mapping).

## Verified (2026-10-30, after the restart)
* pytest: test_boot_fail, deploy, e2e_tools, frontend_shell, handbook_content, handbook_serving, layout_ui,
  preview_build, security, admin_about_security, device_ui, offline_edits_ui, demo_local_ui, pdf_pages: all pass.
* `node --test tests/js/*.test.mjs` 172 pass; `node tests/js/run_vectors.mjs` passes; ruff clean.
* `python3 tools/e2e/boot_fail.py` on this tree: 33 passed, 0 failed. Against 95e2097 (before the notice, exported with
  `git archive` into the scratchpad, `--repo DIR --port 8192`): 0 passed, 14 failed, the page shows only the header.

## Commands
* venv: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
* `python3 tools/e2e/boot_fail.py --out <scratch>/e2e` (port 8191); before: `git archive 95e2097 | tar -x -C <dir>` then
  `--repo <dir> --port 8192`.
* pytest: `<venv>/bin/python -m pytest -q -p no:cacheprovider --basetemp=<scratch>/bt tests/test_boot_fail.py ...`
