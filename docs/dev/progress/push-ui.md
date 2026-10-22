Status: complete (role push-ui; the UI step of design note 12)

# push-ui: Settings → Phone shortcuts, "from a shortcut (name)", the demo's twin, the handbook recipe

Spec: `docs/dev/research/12-phone-push-tokens.md` §4.4, §4.5, §4.6 and the UI bullets of §6. The server half is done and integrated
(`docs/dev/progress/push-server.md`, `docs/push.md`). Base of this work: 7fea9ac (main + zip reader + server half + PDF labs + weight/BP Part B).

## Plan

1. `js/views/settings.js`: the Phone shortcuts block (Your data), the admin People button ("Revoke tokens"), activity labels.
2. Body screens: "from a shortcut (name)" where the source is shown (`js/views/body.js`, `body_trends.js`, `engine/body_ui.js`, visit prep).
3. The demo: `js/mock/auth.js` answers the device family (empty, switched off) and refuses to make a token.
4. Handbook: "From a phone shortcut" on `weight-and-blood-pressure.md`, `PUSH_ENABLED` row in `self-hosting/configuration.md`, a `REVIEW.md` row.
5. Tests: a Node page test of the block, source-text tests in `tests/test_settings_ui.py`, a browser walk `tools/e2e/push.py`.
6. Docs: ARCHITECTURE, `docs/push.md`, `docs/body.md`, CHANGELOG, ROADMAP.

## Done

* Settings block, body-screen origin text, admin People ("Revoke tokens (n)" from `assistant_tokens + device_tokens`), activity labels, the
  demo's token routes, the `family` in the self-revoke audit row (071e3d3). Verified by `tests/test_push_ui.py` (runs `tests/js/push_page.mjs`
  against a fake DOM), `tests/test_settings_ui.py`, `tests/test_body_ui.py`.
* Handbook: "From a phone shortcut" section, `PUSH_ENABLED` row (new "Phone shortcuts" section of `configuration.md`), `settings-and-keys.md`,
  sources `NOTE12` and `APPLE-SHORTCUTS`, the owner's real-iPhone checklist in `handbook/REVIEW.md`. `python scripts/build_handbook.py --check`
  and `tests/test_handbook_content.py` pass.
* `tools/e2e/push.py` (port 8088): 97 checks, all PASS (real Chromium at 375x812 light and 1280x800 dark, the admin, a second and third
  person, the demo). Listed in `tools/e2e/README.md` and `tests/test_e2e_tools.py`.
* `tools/e2e/parity.py` section 10 compares both token families, the 400 for another family, the 404 for an unknown id and the refusal to make
  a token (13 checks in the section, all matching; `--sections 10`).

## Final checks (all green at the last commit)

* `python -m pytest -q -p no:cacheprovider -x`: exit 0 (5,584 tests collected), no network.
* `node tests/js/run_vectors.mjs`, `ruff check .`, `python scripts/build_handbook.py --check`: pass.
* `tools/e2e/push.py`: 97 PASS, 0 FAIL. `tools/e2e/parity.py --sections 10`: 13 of 13 in section 10.
* Left for the owner: the handbook's Shortcut recipe on a real iPhone (`handbook/REVIEW.md`, `docs/maintainers.md` release checklist).

## Decisions

* The block sits in Settings → Account → Your data (after the Apple Health import block), so the handbook says "Settings → Account → Your
  data → Phone shortcuts".
* The demo block makes no request at all (the preview text); the mock routes exist for parity and the replay test.
* `originText` words the Health-app and file origins too ("from the Health app", "from a file"); the Part B screens showed no origin before.
* Visit prep shows no per-row sources, so it is unchanged.
* The Trends tables get a "From" column only while some row in the period has an origin.
* A token that has ended (revoked or expired) still offers "Delete what it sent" while it has rows: the lost-phone order is Revoke, then Delete.
* The self-revoke audit row now carries `family`, so the activity list can say "Phone shortcut token revoked" (a small server change).
* `tests/test_body_ui.py::test_the_apple_health_button_exists_only_when_another_module_provides_the_import` was already failing at the base
  (it expected `KH.bodyImport.open()`; the code calls `open(btn)`). Fixed the stale expectation.

## Commands that reproduce the checks

    python -m pytest -q                      # run in the background
    node tests/js/run_vectors.mjs
    ruff check .
    python scripts/build_handbook.py --check
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/push.py
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/parity.py --sections 10
