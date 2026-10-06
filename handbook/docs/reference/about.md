---
title: About this handbook
description: Who writes the handbook, how pages are sourced and reviewed, how to suggest a correction, and the licence of the text.
slug: about
audience: [patient, caregiver, clinician, app-user, self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
sources: [K24, PEMAT, CCI, NIDDK-copyright, CCBYNCSA]
---

# About this handbook

## Please read this first

This handbook and the kidney-health app **support** your care team; they never **replace** it. The
nephrologist, the diabetes team and the renal dietitian set the real targets for potassium,
phosphorus, sodium, protein, fluid and blood glucose from your own blood tests, urine output,
medicines and insulin plan, and they change them as your labs change. Every guideline cited here says
this; KDIGO 2024 asks clinicians to "use renal dietitians or accredited nutrition providers" to tailor
sodium, phosphorus, potassium and protein "to their individual needs" ([KDIGO 2024][K24], practice
point 3.3.2). The numbers in the handbook are *starting points* that your care team should overwrite
in the app. **Nothing here changes an insulin or medicine dose.** It is education, not medical advice,
and not a medical device.

## Editorial policy

- **Sources.** Every clinical statement cites a source from the [bibliography](sources.md), and every
  medical page lists at least three. Guidelines (KDIGO, KDOQI, ADA, ISPD) come first, then government
  and charity patient pages, then studies.
- **Numbers.** Every number has a unit and a source. Lab ranges come with "your lab's range wins".
  Food values come from USDA FoodData Central through the app's food list; menus, grocery lists and
  target tables are generated from the same data the app uses, so the handbook and the app agree.
- **No doses.** The handbook never gives an insulin or medicine dose or a dose change, and never tells
  anyone to stop a medicine. It says "ask your team whether to pause X when you are ill, and get it in
  writing". A build check rejects dose-like text on the diabetes and medicine pages.
- **Lows first.** Treating low blood glucose is never delayed or warned against.
- **Specialist care.** Pregnancy and children are referred to specialists.
- **Plain words.** Pages aim for a US grade 8 reading level and are checked for understandability and
  actionability with AHRQ's PEMAT ([PEMAT][PEMAT]) and the CDC Clear Communication Index ([CCI][CCI]).
  KDIGO terms are used ("kidney failure", "kidney replacement therapy"); "ESRD" appears only as
  Medicare's legal name.
- **Copyright.** We paraphrase; we do not copy text, tables or recipes from NKF, AKF, DaVita or the
  ADA, or adapt KDIGO tables and figures (KDIGO guidelines are CC BY-NC-ND). We quote at most one
  sentence, with attribution. NIDDK material is mostly in the public domain ([NIDDK][NIDDK-copyright]).

## Clinical review

Every page shows a **draft** banner until a named reviewer signs it off in the page's front matter
(`status: reviewed`, `reviewed_by`, `reviewed_on`).

| Section | Reviewer |
|---|---|
| Eating well | renal dietitian (RDN, ideally board-certified in renal nutrition) |
| Stages, lab results, medicines, preparing for treatment, get help now | nephrologist or nephrology nurse practitioner or physician assistant |
| Type 1 diabetes | diabetes specialist or CDCES |
| Living well | nephrologist or nephrology nurse practitioner or physician assistant; ideally a kidney social worker for work, costs and benefits |
| Using the app | the project maintainer, plus a renal dietitian for targets and warnings |
| Self-hosting | the project maintainer |
| Every patient page | one patient or caregiver, for clarity |

Pages are reviewed every 12 months; each December after the new ADA Standards and any new KDIGO
guideline; within 30 days of an FDA approval or safety notice that touches a page; and each November
for Medicare amounts.

## Review log

| Date | Pages | Reviewer | Notes |
|---|---|---|---|
| 2026-10-05 | all | – | First draft; structure and the eating pages migrated from the original diet guide. Not yet clinically reviewed. |
| 2026-10-06 | Start here, Get help now, Wallet cards, Questions to ask, Understanding CKD (3 pages), Glossary, Units, Licences | – | Written and fact-checked against primary sources (KDIGO 2024 and 2022, ADA 2026, the 2024 hyperglycemic crises consensus, the Kerendia label and FINE-ONE, NIDDK, CDC, NHS). Not yet clinically reviewed. |
| 2026-10-06 | Stages, lab results, eating well, type 1 diabetes, medicines, using the app, self-hosting | – | Fact-checked section by section against primary sources. Preparing for treatment and Living well have not yet had an independent fact-check. Not yet clinically reviewed. |
| 2026-10-06 | all | – | Consistency pass: the same numbers and terms on every page, US spelling, every abbreviation in the glossary, cross-links, layout fixes for phones. Not yet clinically reviewed. |

## Questions for clinical reviewers

Points where sources differ or where the handbook made a judgment call. Reviewers, please confirm or
correct them first.

| Page | Point | What the handbook says now |
|---|---|---|
| Get help now | Blood ketones 1.6–2.9 mmol/L: the NHS says speak to your diabetes team; the ADA says seek emergency care | Call the diabetes team **now**; go to the emergency department if they cannot be reached quickly or if vomiting |
| Get help now | Fever after a transplant: the spec put "fever with chills" in the 911 tier; NIDDK says call the transplant center for a fever over 100 °F | 911 for signs of sepsis (fever or shivering with confusion, fast heartbeat, breathlessness); transplant center the same day for fever over 100 °F |
| Get help now | Fistula or graft bleeding | 911 if heavy or spurting, or not stopped after 10–15 minutes of firm pressure (AKF) |
| Get help now | Peritonitis: "keep the bag" | Taken from the content plan's reading of the ISPD 2022 guideline; its full text was not open to re-check |
| Using the app | The `potassium_additive` warning (ARCHITECTURE.md v0.3 item 9) | A medium warning, "contains a potassium additive; potassium not listed", when potassium is unknown |

## Suggest a correction

Open an issue at <https://github.com/ksullivan86/kidney-health/issues> with the page, the sentence, and
the source that shows the correct fact. Clinicians are especially welcome. Never post your own health
information in an issue.

## Licence

The handbook text is licensed **CC BY-NC-SA 4.0** ([Creative Commons][CCBYNCSA]): you may copy, print
and adapt it for non-commercial use with credit, and share adaptations under the same licence. The app's
code is licensed PolyForm Noncommercial 1.0.0. Third-party material keeps its own licence; see
[Licences](licences.md) and the licence column of the [sources](sources.md).

## Sources

- [KDIGO 2024 CKD guideline][K24]: practice point 3.3.2.
- [AHRQ: PEMAT][PEMAT]; [CDC Clear Communication Index][CCI].
- [NIDDK: copyright][NIDDK-copyright].
- [CC BY-NC-SA 4.0][CCBYNCSA].
