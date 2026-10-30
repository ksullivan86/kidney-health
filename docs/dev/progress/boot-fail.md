Status: in progress

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

## Next
* Tests: static (index + CSS + main.js + preview), e2e harness `tools/e2e/boot_fail.py` (README + test_e2e_tools).
* CHANGELOG, ARCHITECTURE.
* Run: frontend shell, layout, security, preview build, deploy, handbook, e2e-tool tests; `node --test tests/js/*.test.mjs`; ruff.

## Commands
* venv: `/tmp/claude-0/-home-user-kidney-health/8a6bc573-c86c-5a92-a072-0545790bf9a4/scratchpad/venv312/bin/python`
