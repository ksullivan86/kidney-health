Status: complete

# height-units: Profile height in feet and inches, with centimetres as an option

Owner, 2026-11-25: "for the About you (height) it should be in feet inches with the option to use cm".

## Done
* Setting `user.units.height` (`ft_in` | `cm`, default `ft_in`, `user_default`, env `HEIGHT_UNITS`): app/settings_registry.py, JS twin
  app/static/js/engine/settings.js (sorted before user.units.labs), tests/data/settings_vectors.json regenerated.
* IMPORTED_SETTINGS (app/data_import.py, js/mock/import.js), gateway BODY_KEYS (app/app_gateway.py) + Swift allow-list
  (ServerAPI.swift), js/mock/server_account.js ACCOUNT_KEYS; tests pinned (test_app_gateway, test_ios_app, test_server_account_phone).
  gen_import_vectors.py: full settings file has `user.units.height: cm`, plus a bad-value case; import_vectors.json regenerated.
* Engine: KH.bodyRules.{CM_PER_INCH, HEIGHT_UNITS, feetInchesToCm, cmToFeetInches, formatHeight} in js/engine/body.js.
* Profile: index.html has `#pf-height-ftin-field` (fieldset, sr-only legend "Height", `#pf-height-ft` "Height (feet)" 3–8,
  `#pf-height-in` "inches" 0–11.5 step 0.5) and `#pf-height-cm-field` (today's box, hidden by default). profile.js: fillHeight,
  readHeightCm (untouched boxes keep the saved cm, so no false "changed"), setHeightUnit, loadHeightUnit on route show.
* Settings: Preferences select `#set-height-units` (renderHeightUnits, calls KH.views.profile.setHeightUnit); admin "Default for
  everyone" + CHOICE_LABEL; conflict card PROFILE_LABEL height shown in the person's unit.
* e2e scripts journey.py / regress.py fill feet and inches now (175 → 5 ft 9 in = 175.5 cm in regress).
* Tests: tests/js/height_units.test.mjs, tests/test_height_units.py.
* Docs: handbook first-setup.md (Profile table), settings-and-keys.md (Preferences), self-hosting/configuration.md and
  docs/deployment.md (HEIGHT_UNITS), docs/push.md (gateway keys), ARCHITECTURE (settings, import list, gateway, server_account,
  new "Height units" section), CHANGELOG 0.25.0 Added.
* Chromium: tools/e2e/profile_reliability.py has height_walk (13/13 pass). tools/e2e/regress.py --only 375-light: the profile
  checks pass (175.5 cm); its two failures are a GET /api/shared 404 with sharing off, not from this change.
* ruff clean; run_vectors clean; targeted pytest files pass.

## Next
* Nothing. Full pytest run: exit 0, no failures (100%).

## Findings for the report
* Profile's weight boxes (#pf-weight "Weight (kg)", #pf-weight-6mo "Weight 6 months ago (kg)") are kilograms only; user.units.weight
  only adds "(x lb)" to the "Latest in your log" hint (body_ui.profileWeightHint). Not changed.

## Commands
* `node tests/js/run_vectors.mjs`; `node tests/js/height_units.test.mjs`
* `$VENV/bin/python -m pytest -q tests/test_height_units.py tests/test_app_gateway.py tests/test_ios_app.py tests/test_server_account_phone.py`
