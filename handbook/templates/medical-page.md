---
# Front matter: every key is required (tests/test_handbook_content.py checks it).
title: Potassium                       # page title; also the nav label and the H1
description: How much potassium is in common foods, when to limit it, and what high blood potassium feels like.
slug: potassium                        # = file name without .md (folder name for index.md); unique; the app links by slug
audience: [patient, caregiver]         # patient | caregiver | clinician | app-user | self-hoster
applies_to: [G3a, G3b, G4, G5, HD, PD] # G1-G2 | G3a | G3b | G4 | G5 | HD | HHD | PD | Tx | all
status: draft                          # draft | reviewed (reviewed needs reviewed_by and reviewed_on)
reviewed_by: ""                        # e.g. "J. Doe, RDN, CSR"; the draft banner shows until this is set
reviewed_on: null                      # ISO date of the clinical review, e.g. 2027-01-15
last_checked: 2026-10-05               # ISO date the numbers were last checked against the sources
sources: [K24, DG5, DG46a]             # every id cited on the page, from handbook/sources.yml
# figures_as_of: 2026-10-05            # required on pages with prices, benefit amounts or laws
---

# Potassium

<!-- Medical page template (docs/dev/research/08-handbook-site.md §4.9). Keep the sections in this
     order. Plain words (aim for US grade 8), the reason behind every rule, every number with a unit
     and a source, "your lab's range wins". Never a medicine or insulin dose; lows are always treated
     first. Pages under t1d/ and medicines/ include the no-dosing box below the H1:
     --8<-- "includes/no-dosing.md" -->

## In short

Three to five sentences: what this is, why it matters with kidney disease and type 1 diabetes, and
the one thing to do.

## Your numbers

--8<-- "includes/starting-points.md"

=== "US units"

    | | Typical |
    |---|---|
    | Blood potassium | 3.5–5.0 mEq/L |

=== "International"

    | | Typical |
    |---|---|
    | Blood potassium | 3.5–5.0 mmol/L |

## What to do

- [ ] A checklist item a person can do today.
- [ ] Another one, with the reason: "because …".

## Examples

Real foods and servings from USDA FoodData Central (the app's food list), or a worked case.

## Ask your care team

1. Three to six specific questions.

## Get help now if…

- The red flags for this topic, then: see [Get help now](../get-help-now.md).

## Sources

- [KDIGO 2024 CKD guideline][K24], practice point 3.11.5.1.
- [NKF: potassium and your CKD diet][DG5].
- [AKF potassium food guide][DG46a].
