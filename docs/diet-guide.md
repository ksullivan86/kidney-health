# Kidney-friendly eating with type 1 diabetes: moved to the handbook

This guide is now the **Eating well** section of the patient handbook, split into pages, extended and
kept up to date there with its sources ([design note 08](dev/research/08-handbook-site.md) §4.11):

* **In the app:** open **Learn** (the book icon), or go to `/learn/eat/` on your server.
* **Source:** [`handbook/docs/eat/`](../handbook/docs/eat/index.md); the bibliography is
  [`handbook/sources.yml`](../handbook/sources.yml), where every source of this guide keeps its old
  number in the `dg` field (`DG<n>`).

The text as it stood before the move is in the git history: `git show 331f1b1:docs/diet-guide.md`.
Code comments, tests and data files that cite "docs/diet-guide.md section N" (or "diet-guide §N") refer to
that text; this is where each section lives now:

| Section of the old guide | Handbook page (`/learn/…` in the app) |
|---|---|
| "Please read this first" | [`reference/about`](../handbook/docs/reference/about.md), and the note on [`eat/`](../handbook/docs/eat/index.md) |
| §1 The short version | [`eat/`](../handbook/docs/eat/index.md) ("In short") |
| §2 The five numbers and the sixth | [`eat/potassium`](../handbook/docs/eat/potassium.md), [`eat/phosphorus`](../handbook/docs/eat/phosphorus.md), [`eat/sodium`](../handbook/docs/eat/sodium.md), [`eat/protein`](../handbook/docs/eat/protein.md), [`eat/fluid`](../handbook/docs/eat/fluid.md), [`eat/carb-counting`](../handbook/docs/eat/carb-counting.md) |
| §2 Typical daily targets by stage | [`eat/`](../handbook/docs/eat/index.md) (the generated targets table) |
| §2 Day by day, or weekly average? | [`app/targets-and-warnings`](../handbook/docs/app/targets-and-warnings.md) |
| §3 What to eat, limit and avoid | [`eat/food-lists`](../handbook/docs/eat/food-lists.md) |
| §4 Carb counting with renal swaps | [`eat/carb-counting`](../handbook/docs/eat/carb-counting.md) |
| §4 Treating a low on a kidney diet | [`t1d/treating-a-low`](../handbook/docs/t1d/treating-a-low.md) |
| §4 For the clinician; CGM and A1c | [`t1d/`](../handbook/docs/t1d/index.md); [`labs/a1c`](../handbook/docs/labs/a1c.md), [`labs/cgm-metrics`](../handbook/docs/labs/cgm-metrics.md) |
| §5 Labels, additives, leaching, eating out | [`eat/label-reading`](../handbook/docs/eat/label-reading.md), [`eat/phosphate-additives`](../handbook/docs/eat/phosphate-additives.md), [`eat/potassium-leaching`](../handbook/docs/eat/potassium-leaching.md), [`eat/eating-out`](../handbook/docs/eat/eating-out.md) |
| §5 Salt substitutes, supplements and over-the-counter products | [`eat/sodium`](../handbook/docs/eat/sodium.md), [`medicines/supplements`](../handbook/docs/medicines/supplements.md), [`medicines/avoid`](../handbook/docs/medicines/avoid.md) |
| §6 A sample day | [`eat/menus/`](../handbook/docs/eat/menus/index.md) ("The original sample day", with its per-meal numbers) |
| §7 How the app uses this | [`app/targets-and-warnings`](../handbook/docs/app/targets-and-warnings.md) |
| §8 Sources | [`reference/sources`](../handbook/docs/reference/sources.md), generated from `handbook/sources.yml` |

The research behind it stays in [`docs/research/`](research/) for contributors.
