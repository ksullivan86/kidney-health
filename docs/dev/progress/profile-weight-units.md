Status: in progress

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

## Next
* e2e scripts (journey.py, regress.py, profile_reliability.py, sandbox.py, body.py) expect kg in #pf-weight; Chromium walk; docs; full pytest.
