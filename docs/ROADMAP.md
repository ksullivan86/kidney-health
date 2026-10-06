# Roadmap: work the specifications defer to a later version

One line per item, with the specification that defers it. Items leave this list when they ship (move
them to CHANGELOG.md) or when the owner drops them. Each feature owner appends its own section.

## Personalised targets and labs (note 05)

* Clinical review of every rule marked opinion in `app/target_rules.py`, the K-5 alert wording, the 0.6 g/kg lower bound without diabetes (fact-check M6) and the one-step potassium relaxation on hemodialysis (fact-check L15); record reviewer and date in note 05's header — note 05 §7 C10. Until then `targets.lab_rules_enabled` stays off on public demo servers.
* Re-verify the sources when they change: KDIGO 2026 diabetes-in-CKD (final text), ADA Standards 2027, KDOQI nutrition updates, NASEM DRIs; read the GLIM and ISRNM primary tables before release — note 05 §7 C11 and §8.
* EKFC eGFR equation (needs regional Q values) as an alternative to CKD-EPI — note 05 §3.5 ("later option").
* Disease-specific resting-energy equations on dialysis (MHDE) — note 05 §3.2 option D and §6 ("kept as a later option").
* Frailty and sarcopenia screens (SARC-F, FRAIL) instead of the checkbox — note 05 F12 ("a later option. v0.3 uses a checkbox").
