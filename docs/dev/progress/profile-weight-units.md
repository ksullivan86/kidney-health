Status: complete

# profile-weight-units: Profile's two weight boxes in the person's unit (user.units.weight, kg | lb, default lb)

Owner, 2026-11-26: "Should the weight fields in Profile use lb, like height?" — "yes".

## Plan (follows height-units: c3317ba b1552d3 f8c21c5)
* Engine js/engine/body.js: weightBoxText, weightBoxKg, weightBoxRange (reuse KG_PER_LB, shownWeight, lbToKg).
* profile.js: weight block (weightUnit, fillWeight, readWeightKg, setWeightUnit, loadWeightUnit, showWeightUnit) after the
  body-hints block; untouched box keeps saved kg; "Use this" keeps the log's exact kg.
* The unit is changed in Settings → Weight and blood pressure (views/body.js renderSettings, #set-body-unit): call
  KH.views.profile.setWeightUnit there. No select in Preferences.
* Conflict card PROFILE_LABEL in views/settings.js: weight in the person's unit.
* Decision: pounds typed convert to kg stored to 0.01 kg (lbToKg, same rule as every logged weight); every 0.1 lb comes back the same.

## Done
* Engine body.js: weightBoxText, weightBoxKg, weightBoxRange (KG_PER_LB reused). body_ui.profileWeightHint now names the weight in
  the person's unit only (test_body_ui_numbers.py updated).
* index.html: labels "Weight (lb)" / "Weight 6 months ago (lb)" (new id pf-weight-6mo-label), lb ranges 44.1–661.3 / 44.1–881.8.
* profile.js: weight block; "Use this" fills the log's exact kg; toast names the unit. body.js renderSettings calls setWeightUnit.
* settings.js conflict card: weight lines in the person's unit (state.weightUnit, else cache.mySettings), kg shown if they round equal.
* Tests: tests/js/weight_units.test.mjs (8 pass), tests/test_profile_weight_units.py; test_targets_ui.py label check updated.
  run_vectors exit 0. ruff clean.

* e2e: journey.py fills 150 lb, regress.py 154.3 lb (= 69.99 kg), sandbox.py waits for 154.3, body.py compares in the unit
  (same_weight). profile_reliability.py weight_walk: 22/22 pass. body.py: 414 pass. device_mode.py: my new check passes in both
  passes; the run stops later in the reminders walk another agent (phone-reminders) has in progress in the working tree, not mine.
  device_mode.py was committed with only my hunk (git apply --cached), since that file holds another agent's uncommitted work.
* Docs: handbook first-setup.md (Profile table), settings-and-keys.md (new Weight and blood pressure row), weight-and-blood-pressure.md,
  ARCHITECTURE "Weight units in Profile" (after "Height units"), docs/body.md, docs/targets-and-labs.md, CHANGELOG Unreleased → Changed.

* Fixed two older tests that read profile.js: test_body_ui.py (hint block ends at "let weightUnit ="; Use this calls fillWeight) and
  tests/js/profile_suggestion_context.test.mjs (context has readWeightKg and weightUnit).
* Targeted pytest (17 files touching Profile, Body, Settings, gateway, iPhone app) pass, except
  test_settings_ui.py::test_only_the_reminders_block_talks_about_reminders, which fails on js/mock/phone_reminders.js, another
  agent's file in progress. Full suite not run: the orchestrator runs it once for everyone (disk space).

## Next
* Nothing.

## Commands
* `node tests/js/weight_units.test.mjs`; `node tests/js/run_vectors.mjs`
* `$VENV/bin/python -m pytest -q tests/test_profile_weight_units.py tests/test_body_ui_numbers.py tests/test_targets_ui.py tests/test_height_units.py`
* `cd tools/e2e && python profile_reliability.py --port 8191` (and body.py, device_mode.py)
