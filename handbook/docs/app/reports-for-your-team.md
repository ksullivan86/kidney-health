---
title: Reports for your care team
description: "Use Trends, the period summary and the CSV export to show your dietitian and doctors what you really eat."
slug: reports-for-your-team
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [ARCH, NOTE03, NOTE06, NOTE07, Q20, DG28a, DG53]
---

# Reports for your care team

Your dietitian can help far more with a week of real numbers than with "I try to eat well". The app
gives you three things to bring: the **Trends** charts, the **period summary**, and a **CSV file** with
every entry ([architecture contract][ARCH]).

## What to bring

| Report | Where | Best for |
|---|---|---|
| Period summary | **Trends** (top card) | a one-screen answer to "how was your week?" |
| Charts for 7, 14 or 30 days | **Trends** | spotting patterns: weekends, dialysis days, a food that keeps coming back |
| Export CSV | **Trends** → **Export CSV** | the dietitian's own analysis in a spreadsheet |
| Last 7 days strip | bottom of **Today** | a quick look between visits |

## The period summary

For each nutrient with a target, the card shows:

- the **average per logged day** against your target, colored ok, near limit or over;
- how many days were **over**, and the highest day;
- the **change** from the period before (for example "−7 %");
- how it is judged: potassium, sodium, fluid and carbohydrate **day by day**; phosphorus, protein,
  calories and calcium on the **weekly average** ([KDOQI 2020][Q20]).

Days with nothing logged are left out of the averages, and the card says how many days you logged. A
half-logged day pulls averages down, so log whole days.

On hemodialysis with your dialysis days set, the card adds the **since-last-session** totals, for
example "Since dialysis on Friday: potassium 7,200 mg of 7,500 mg for 3 days". Deaths and hospital
stays are more common after the long weekend gap ([Foley 2011][DG53]), and large weight gains between
sessions are linked to heart problems ([Cabrera 2015][DG28a]; [Dialysis days](../eat/dialysis-days.md)).

## The CSV export

**Trends → Export CSV** downloads a file for the days on screen (7, 14 or 30). It has one row per entry
and opens in Excel, Google Sheets, Numbers or LibreOffice.

| Columns | Meaning |
|---|---|
| `date`, `meal`, `status` | the day, breakfast/lunch/dinner/snack, and eaten or planned |
| `food_name`, `servings`, `grams`, `note` | what and how much, plus your note |
| `calories_kcal` … `fluid_ml` | the 12 nutrients for that entry, already multiplied by the servings |
| `id`, `food_id`, `created_at`, `updated_at` | for the app; your dietitian can ignore them |
| `purpose` | `hypo` when the entry treated a low (its carbohydrate is not part of a meal) |
| `source`, `source_license` | where the food's numbers came from (builtin, custom, USDA, Open Food Facts) and their licence; Open Food Facts data is under the Open Database License, which the file must keep if you share it |

To make a daily total in a spreadsheet, filter `status` to **eaten** and add up by `date`. Planned rows
are food you had not eaten when you exported.

Text (food names, notes) that starts with `=`, `+`, `-`, `@`, a tab or a line break gets a leading
apostrophe in the file, so a spreadsheet does not run it as a formula ([architecture contract][ARCH];
[design note 03][NOTE03]).

## What to do before a visit

- [ ] Ask your dietitian which days they want to see, and how they want the file (printed, on your
      phone, or through the clinic's patient portal).
- [ ] Log those days **completely**: drinks, sauces, snacks and low treatments too.
- [ ] Delete planned entries you did not eat, and tap **Eaten** on the ones you did.
- [ ] Open **Trends**, pick the range and take a screenshot of the period summary.
- [ ] Export the CSV for the same range.
- [ ] Bring your lab results and your medicine list ([Your medicine list](../medicines/your-medicine-list.md)).

## Questions to ask

1. "Which nutrient should I work on first?"
2. "My potassium is over on weekends. Which foods would you change?"
3. "Is my protein high enough on dialysis days?" (or "not too high", before dialysis)
4. "Are my targets in the app still right after my latest labs?"
5. "Do my carbohydrate amounts per meal look steady enough?"

More: [Questions to ask](../reference/questions-to-ask.md) and [Appointments](../living/appointments.md).

## Insights and the full export

- **Insights** on **Trends** sum up the days you chose in plain words with numbers, such as
  "Potassium was over your limit on 2 of 7 days (Sat, Sun). The main sources were potatoes and orange
  juice." **Today** shows the same for a single day once breakfast, lunch and dinner are logged, or after
  7 pm ([Meal guidance](guidance.md); [design note 06][NOTE06]). Low treatments are left out of the
  carbohydrate insights.
- **Settings → Account → Your data → Export my data (.zip)** downloads everything in one file (JSON and
  CSV, lab results included), for your own records or to move to another server
  ([design note 07][NOTE07]; [Privacy and your data](privacy.md)). For your dietitian, the CSV above is
  easier.

## If something goes wrong

- **The averages look too low.** Check that you logged every meal on the days shown. Unknown values in
  Quick add foods also make totals low.
- **The file opens as one long column.** Open it with your spreadsheet's import, and choose "comma" as the
  separator.
- **Nothing downloads in the preview or demo version.** The demo shows the CSV text to copy instead; the
  installed app downloads a `.csv` file.

## Related pages

- [Targets and warnings](targets-and-warnings.md) · [Planning meals](planning-and-menus.md) · [Privacy and your data](privacy.md)
- [Appointments](../living/appointments.md) · [Questions to ask](../reference/questions-to-ask.md)

## Sources

- [Project architecture contract][ARCH]: Trends, period summary, CSV export columns.
- [KDOQI 2020 nutrition guideline][Q20]: why phosphorus and protein are judged over weeks.
- [Foley 2011][DG53]: the long interdialytic interval; [Cabrera 2015][DG28a]: weight gain between sessions.
- [Design note 03][NOTE03] (CSV formula escaping); [design note 06][NOTE06] (insights); [design note 07][NOTE07] (full export).
