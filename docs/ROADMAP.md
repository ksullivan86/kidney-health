# Roadmap: work the specifications defer to a later version

One line per item, with the specification that defers it. Items leave this list when they ship (move
them to CHANGELOG.md) or when the owner drops them. Each feature owner appends its own section.

## Personalised targets and labs (note 05)

* Clinical review of every rule marked opinion in `app/target_rules.py`, the K-5 alert wording, the 0.6 g/kg lower bound without diabetes (fact-check M6) and the one-step potassium relaxation on hemodialysis (fact-check L15); record reviewer and date in note 05's header — note 05 §7 C10. Until then `targets.lab_rules_enabled` stays off on public demo servers.
* Re-verify the sources when they change: KDIGO 2026 diabetes-in-CKD (final text), ADA Standards 2027, KDOQI nutrition updates, NASEM DRIs; read the GLIM and ISRNM primary tables before release — note 05 §7 C11 and §8.
* EKFC eGFR equation (needs regional Q values) as an alternative to CKD-EPI — note 05 §3.5 ("later option").
* Disease-specific resting-energy equations on dialysis (MHDE) — note 05 §3.2 option D and §6 ("kept as a later option").
* Frailty and sarcopenia screens (SARC-F, FRAIL) instead of the checkbox — note 05 F12 ("a later option. v0.3 uses a checkbox").

## Patient handbook at `/learn` (note 08)

* Offline handbook pages: a runtime cache in the service worker (v0.3 leaves `/learn` to the network) — note 08 §4.6 "Service worker" (v0.4).
* "Add this menu day to my plan": turn a generated handbook menu day into planned entries (menus use builtin `fdc_id`s) — note 08 §4.10 "Idea for v0.4".
* A "finerenone" profile flag that warns on grapefruit, as the Kerendia label says — note 08 §4.10 "Idea for v0.4".
* Spanish and other languages (page structure and slugs are language-neutral) — note 08 §6 risk 13 (v0.4, with Zensical or `mkdocs-static-i18n`).
* Migrate from MkDocs + Material to Zensical once a Zensical ≥ 0.1 release passes the CI canary (`handbook-zensical`) and the `/learn` browser check, before Material's security fixes end (November 2026 at the earliest) — note 08 §4.1 and §6 risk 2.
* Owner decisions before publishing: enable GitHub Pages (`HANDBOOK_PAGES=true`, needs a public repository or GitHub Pro/Team), then set `HANDBOOK_PUBLIC_URL` and the image's documentation label to the Pages URL — note 08 §4.8 "Owner setup", §7 Phase 0 and Phase 4.
* Clinical sign-off of every handbook page by the named reviewers (draft banners stay until then) — note 08 §4.9 and §7 Phase 4; ARCHITECTURE.md v0.3 decision 11.
