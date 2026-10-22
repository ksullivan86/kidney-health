Status: in progress (role push-ui; the UI step of design note 12)

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

(nothing yet)

## Decisions

(none yet)

## Commands that reproduce the checks

    python -m pytest -q                      # run in the background
    node tests/js/run_vectors.mjs
    ruff check .
    python scripts/build_handbook.py --check
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python tools/e2e/push.py
