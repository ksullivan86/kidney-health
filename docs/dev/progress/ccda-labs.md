Status: complete (2026-10-15; the caller integrates the branch; nothing pushed, no PR opened)

# ccda-labs: lab results from a patient-portal C-CDA file (XML parsed in the browser)

Base: `805744e` (Apple Health FHIR import, `KH.fhirLabs`) plus the CodeQL test fixes `a24dd71`/`be67d7b`, then the base branch
`claude/adoring-sagan-th5swr` merged again (`07a4ca7`: offline edits; origin's squashed copy `609c5f7` of the FHIR import has the identical
tree, recorded with `merge -s ours` so that the real merge had a sane base). Branch `worktree-agent-aa3be302c7984d43b`.
Commit trailers: as the brief gives them (Co-Authored-By: Claude Opus 5.5 / Claude-Session).

## Plan (sub-steps), all done
1. Share: from `fhir_labs.js` export `collector`, `dayOf`, `shown`, `quote`, `num`, `plural`, `MAX_TEXT` without changing FHIR behaviour (its vectors stay green).
2. Engine `app/static/js/engine/ccda_labs.js` (`KH.ccdaLabs`) taking an injected `parseXml(text) -> Document` (default: `DOMParser`).
3. Dev-only XML parser for Node tests `tests/js/mini_xml.mjs`; vectors `tests/data/ccda_labs_vectors.json` (generator `tests/js/gen_ccda_labs_vectors.mjs`), section 7c in `tests/js/run_vectors.mjs`.
4. Page `app/static/js/views/lab_ccda.js` (`KH.labCcda`), card `#lab-ccda` in `index.html`, `sw.js`, `KH.labFhir.review` got an id `prefix` and `emptyHint`.
5. Python tests `tests/test_ccda_labs.py`, `tests/test_ccda_labs_ui.py` + `tests/js/ccda_labs_page.mjs`.
6. Chromium walk in `tools/e2e/regress.py` (step 2c-iii, after Apple Health).
7. Docs: targets-and-labs.md, privacy.md, security.md, ARCHITECTURE.md, CHANGELOG.md, ROADMAP.md, maintainers.md, handbook targets-and-warnings.md, e2e README.
8. Full suite in 4 shards, vectors.

## Decisions (and why)
* Parse in the browser with `DOMParser` (`application/xml`), not `defusedxml` on the server: least trust, nothing uploaded, no new dependency,
  no XML parser on the server. A document with `<!DOCTYPE`/`<!ENTITY` is refused before parsing (a real C-CDA has no DTD).
* **CSP change (found by the Chromium walk, not by the Node tests):** the app's CSP has `require-trusted-types-for 'script'`, and
  `DOMParser.parseFromString` is a Trusted Types sink for XML too (a string throws "requires TrustedHTML"). So `app/security.py` is now
  `trusted-types kh-sw kh-xml`; `kh-xml` is created once in `ccda_labs.js`, its `createHTML` accepts only a string with no DOCTYPE/ENTITY.
  Guard tests changed on purpose: `tests/test_security.py` (CSP pinned), `tests/test_frontend_shell.py` (exactly two files create a policy, one
  `parseFromString` call, exempted by exact line). The preview test forbids the words `kh-sw` in inlined scripts, so the engine comment says
  "the CSP's trusted-types list". If the owner does not want a second policy, the feature cannot parse XML (there is no other non-sink parser).
* Chromium builds an error document with inline styles for a malformed file; the CSP refuses them: 4 console messages for 2 broken sample
  files. The walk asserts that is all and removes them before its "no console errors" check.
* OIDs verified 2026-10-15 against HL7 sources (see docs/targets-and-labs.md): Results Section entries required `2.16.840.1.113883.10.20.22.2.3.1`
  (hl7.org/cda/us/ccda/StructureDefinition-ResultsSection.html and the HL7 CDA-Examples IG), Result Observation `...4.2` and Result Organizer `...4.1`
  (same IG pages and example), LOINC code system `2.16.840.1.113883.6.1`, section code 30954-2. **Not verified from a primary page:** the "entries
  optional" template `...2.3` (the R2.1 draft pages are gone); it is used as a templateId in the HL7 CDA-Examples results example and named
  "Results section (entries optional)" by Aidbox's docs.
* A throw from the parser (not a `parsererror` document) counts the file as "could not be read" (it means the parser was not allowed to parse).
* No fallback to the organizer's `effectiveTime` when the observation has none (documented as not built).
* CodeQL (integrator's notes): Python tests never test a host name with `in` (hosts are compared as exact sets with `==`, via urlparse); every regex
  that looks for an HTML tag has `re.IGNORECASE`.

## Done (how it was checked)
* Engine, vectors (31 hand-written picks, 33 checks) and the shared-collector refactor: `node tests/js/run_vectors.mjs` exit 0 (the FHIR vectors
  are unchanged and pass).
* `python -m pytest -q -p no:cacheprovider tests/test_ccda_labs.py tests/test_ccda_labs_ui.py tests/test_fhir_labs.py tests/test_fhir_labs_ui.py
  tests/test_frontend_shell.py tests/test_security.py tests/test_preview_build.py` pass.
* Chromium: `cd tools/e2e && python regress.py --no-pytest --no-probes --only 375-light --port 8071 --out <fresh dir>` passes (142 checks, the
  C-CDA ones included: the real `DOMParser` through the `kh-xml` policy reads a hand-written summary; DOCTYPE file refused; truncated and text
  files are "not valid XML"); the screenshot `03e-labs-patient-portal` was looked at (375 px, no overflow).
* Chromium, all four configs on the merged head: `cd tools/e2e && python regress.py --no-pytest --no-probes --port 8081 --out <fresh dir>` exit 0
  (557 checks: 375 and 1280 px, light and dark).
* Full suite in 4 parallel shards (`timeout 900 python -m pytest -q -x -p no:cacheprovider <files>`, files split by size) on the merged head
  `af28822`: all four exit 0. `node tests/js/run_vectors.mjs` exit 0.

## Not done / for the owner
* A run on a real portal export (MyChart and at least one other); the hand-written samples may differ from real files (codes, units, results only
  on the organizer's `effectiveTime`).
* Safari/iOS: the `kh-xml` policy is exercised only by Chromium here.

## Reproduce
`node tests/js/run_vectors.mjs`; `node tests/js/gen_ccda_labs_vectors.mjs` (regenerates the vectors, stops if the module disagrees);
`python -m pytest -q -p no:cacheprovider tests/test_ccda_labs.py tests/test_ccda_labs_ui.py tests/test_fhir_labs.py tests/test_fhir_labs_ui.py`.
