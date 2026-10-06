---
title: Licences
description: The licence of the handbook text and code, the licences of the software and icons the site is built with, and how to credit the handbook.
slug: licences
audience: [patient, caregiver, clinician, app-user, self-hoster]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
sources: [CCBYNCSA, MATERIAL, MKDOCS, FDC, NIDDK-copyright]
---

# Licences

## This handbook and the app

| What | Licence |
|---|---|
| Handbook text (`handbook/docs`, `handbook/includes`, `handbook/data`) | CC BY-NC-SA 4.0 ([licence][CCBYNCSA]; full text in `handbook/LICENSE`) |
| The app, scripts, tests and the handbook's build configuration and theme overrides | PolyForm Noncommercial 1.0.0 (`LICENSE` at the repository root) |
| Food values (USDA FoodData Central, SR Legacy) | public domain ([USDA][FDC]) |
| NIDDK health information | mostly public domain; no NIH or NIDDK logos ([NIDDK][NIDDK-copyright]) |
| Guidelines and patient pages we cite | their own licences, listed for each source on the [sources page](sources.md). We cite and paraphrase, and quote at most one sentence |

## Software and files that ship with the site

The site is built with MkDocs and the Material for MkDocs theme. Only the files below reach your
browser; MkDocs itself runs only when the site is built.

| What | Licence | Where the notice is |
|---|---|---|
| Material for MkDocs theme (styles, scripts, templates) | MIT ([Material for MkDocs][MATERIAL]) | [material-LICENSE.txt](../assets/licences/material-LICENSE.txt) |
| clipboard.js and escape-html, inside the theme's script bundle | MIT | notices kept in the bundled file |
| lunr, the search engine (runs in your browser, no internet needed) | MIT | notices kept in the search worker file |
| lunr-languages: search support for other languages, shipped by the theme though this site searches in English only | Mozilla Public License 1.1 ([source](https://github.com/MihaiValentin/lunr-languages)) | notice at the top of each `lunr.*.min.js` file |
| TinySegmenter (Japanese word splitting for search) | BSD, by Taku Kudo | notice in `tinyseg.js` |
| wordcut (Thai word splitting for search) | GNU LGPL 3.0 ([source](https://github.com/veer66/wordcut)) | shipped unmodified as `wordcut.js` |
| Material Design Icons (the light and dark mode buttons) | Pictogrammers Free License | [material-design-icons-LICENSE.txt](../assets/licences/material-design-icons-LICENSE.txt) |
| Font Awesome Free (the GitHub icon in the footer) | icons under CC BY 4.0 | [fontawesome-LICENSE.txt](../assets/licences/fontawesome-LICENSE.txt) |
| MkDocs (build tool only, not shipped) | BSD-2-Clause ([MkDocs][MKDOCS]) | – |

The language files (lunr-languages, TinySegmenter, wordcut) are copied by the theme into every build.
This site does not load them, because its search is set to English. They are kept unmodified so their
licences are easy to follow.

## How to credit this handbook

You may copy, print, share and adapt the handbook text for **non-commercial** use, as long as you give
credit and share your changes under the same licence ([CC BY-NC-SA 4.0][CCBYNCSA]). A good credit
names the title, the authors, the source and the licence, and says what you changed. For example:

> "Get help now" from the Kidney Health Handbook, by the kidney-health project contributors,
> <https://github.com/ksullivan86/kidney-health>, licensed CC BY-NC-SA 4.0. Shortened and printed by
> [name of your clinic], October 2026.

When you print a page:

- keep the "Draft: not yet reviewed by a clinician" banner and the review line if they are on the page;
- keep the source list, so readers can check every number;
- do not add your own doses or targets to the handbook text. Put them on the
  [wallet cards](wallet-card.md), which are made for that;
- if you are not sure whether your use counts as non-commercial, read the licence deed and ask the
  project before you go ahead.

Logos and text from other organizations (KDIGO, ADA, NKF, AKF and others) are **not** covered by our
licence. They stay with their owners; we only link to them.

## Sources

- [CC BY-NC-SA 4.0][CCBYNCSA]; [Material for MkDocs][MATERIAL]; [MkDocs][MKDOCS].
- [USDA FoodData Central][FDC]; [NIDDK: copyright][NIDDK-copyright].
