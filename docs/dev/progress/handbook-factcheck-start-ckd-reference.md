Status: complete

# Handbook fact-check: Start here, Get help now, ckd/, reference/

Role: adversarial clinical fact-checker for `handbook/docs/index.md`, `get-help-now.md`, `ckd/*`,
`reference/glossary.md`, `reference/wallet-card.md`, `reference/questions-to-ask.md` and the shared
card `handbook/includes/help-card.md`. Task says: do not git commit.

## Done (verified)

- Read all pages in the section, spec 08 §4.9/§5.1/§5.2/§5.10/§5.13, ARCHITECTURE v0.3 contract.
- Checked every KDIGO 2024 statement number cited in the section against the guideline text
  (scratchpad `handbook/pdf/k24.txt`): PP 1.1.1.1–2, Rec 1.1.2.1, PP 1.2.2.4, PP 1.3.1.1, Table 16,
  PP 2.1.1–2.1.5, Rec 2.2.1, PP 2.2.1–2.2.4, PP 3.3.2, Rec 3.4.1, Rec 3.6.3, PP 3.6.2–3.6.7,
  Rec 3.15.1.1–3, section 3.15 text, PP 4.1.3–4.1.4, PP 4.2.1, PP 4.3.2–4.3.3, PP 5.2.2.1, Table 38,
  PP 5.3.1–5.3.2, PP 5.4.3, Table 28, Table 41, research recommendations (T1D understudied).
- KDIGO 2022 (k22.txt): Rec 1.2.1, 1.5.1, 2.2.1, 3.1.1, 3.1.2, 3.2.1; PP 2.1.2, 2.1.3; nephrotic
  footnote; SGLT2i/T1D passage.
- KDIGO 2026 anaemia thresholds (k26a.txt). Kerendia label 9/2026 (ker.txt) + Bayer approval news.
- ADA 2026 §11 recs 11.1a–11.12b and text (PMC12690176 via WebFetch); ADA 2026 §6 (glucagon 6.16,
  hypo levels, CGM goals, ketone checks, blood vs urine ketones, SGLT2i DKA 5–17x, BHB 0.8 → 3.2x).
- TIR19 older/high-risk targets incl. renal disease; HC24 criteria and Table 4 (ESKD lower BHB).
- FINE-ONE abstract (PubMed efetch PMID 41780000). MHRA dapagliflozin DSU (Dec 2021). MHRA
  icodextrin DSU; Extraneal label (local DailyMed copy). NHS DKA; ADA DKA page; NIDDK DKD, CKD,
  hypo, transplant; CDC sepsis; KDIGO diabetes-CKD 2026 update still a draft; sotagliflozin still
  not approved (CRL Dec 2024, resubmission expected Q4 2026).

- Fixes applied (3 medium, 16 low; none high), `fact_checked: 2026-10-05` on all 8 pages, new
  source `MHRA-DAPA` and an MHRA note in `handbook/sources.yml`, generated includes refreshed.
- Findings and clinician items appended to `handbook/REVIEW.md` under
  "Fact-check: Start here, Get help now, ckd/, reference/ (2026-10-05)".
- Verified: `scripts/build_handbook.py --check` up to date; `pytest --noconftest
  tests/test_handbook_content.py` 583 passed, 1 skipped; `mkdocs build --strict` exit 0.
- Not committed (task instruction: do not git commit).
