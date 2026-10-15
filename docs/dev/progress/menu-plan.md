Status: complete

# menu-plan: "Add this day to my plan" (ROADMAP v0.4, note 08 §4.10)

Branch `worktree-agent-a4770ae9b9a797e1f`. Not pushed, no PR (the caller does that). The ROADMAP item is removed
(the file's rule: shipped items move to CHANGELOG); the contract is ARCHITECTURE.md "Menu days in the app".

## Design (decided)

* Handbook: every generated menu day gets a plain link `@KH_APP@#plan-menu?items=b173905x1,...`
  (`<meal letter><fdc_id>x<servings>`; b l d s). Raw HTML paragraph written by
  `scripts/build_handbook.py` (`menu_plan_paragraph`); `handbook/tools/menu_links.py` (MkDocs hook, `hooks:` in
  `mkdocs.yml`) turns the token into the app (`HANDBOOK_APP_LINK`), the Pages demo (`demo_link`, relative path,
  text "Try this day in the app's demo") or drops the paragraph. No script on the handbook side.
* App: `js/engine/menu_link.js` (pure reader, strict) + `js/views/menuplan.js` (sheet `#sheet-menuplan` in
  `index.html`). Foods come from `GET /api/foods/builtin` (no new server route, no schema change), only
  `source: builtin` rows resolve. The sheet writes nothing; only "Add to plan" posts `POST /api/log/batch`
  (planned, one `client_id` per food made when the sheet opens). Signed out: the link is kept in memory only
  (never stored) while signing in; `main.js start()` and `auth.js enterApp` call `KH.menuPlan.openPending()`.
  A reload or an outside sign-in page forgets it: open the link again.
* Limits: link <= 1500 chars, <= 40 entries (the batch limit), servings > 0 and <= 1000 with <= 4 decimals.
  The build fails a day that does not fit (`_check_plan_link`).
* Why `auth.js` has `.catch(() => null)`: `tests/test_settings_ui.py` keeps `console` out of `auth.js` (tokens are
  never logged).

## Done (how verified)

* Engine + vectors: `node tests/js/run_vectors.mjs` (section "menu link", 39 checks).
* Build: `python scripts/build_handbook.py --check`; 42 menu days carry a link; `tests/test_menu_plan.py` (18 tests).
* Handbook build (venv from `handbook/requirements.lock`): LAN build `HANDBOOK_APP_LINK=/` gives `/#plan-menu?...`
  and `check_links.py --allow /` is clean; Pages build gives `../../../demo/#plan-menu?...`; `tools/e2e/learn.py`
  against the built site passes (72 checks).
* Browser: `python tools/e2e/menuplan.py --site <built site>` (real server, the handbook page, Pages demo; 375 light /
  1280 dark): 48 checks pass.
* Full suite once: `python -m pytest -q -x -p no:cacheprovider` exit 0.

## Commands that reproduce the checks

    python -m pytest tests/test_menu_plan.py -q -p no:cacheprovider
    node tests/js/run_vectors.mjs
    python scripts/build_handbook.py --check
    cd handbook && NO_MKDOCS_2_WARNING=true HANDBOOK_SITE_URL=http://localhost/learn/ HANDBOOK_APP_LINK=/ mkdocs build --strict -d /tmp/kh-site
    python handbook/tools/check_links.py /tmp/kh-site --allow /
    python tools/e2e/menuplan.py --site /tmp/kh-site    # needs Chromium (PLAYWRIGHT_CHROMIUM or /opt/pw-browsers)

## Left open

* Clinical review of the handbook text stays with the existing sign-off (the menu pages are drafts).
* The `?mock=1` page of a live server has 24 foods, so most foods of a menu day are listed as not added there; the
  preview build and the Pages demo have the whole list.
