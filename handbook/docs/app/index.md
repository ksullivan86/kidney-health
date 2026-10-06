---
title: Using the app
description: "What the kidney-health food log does and does not do, how its screens fit together, and how it keeps your data private."
slug: app
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
fact_checked: 2026-10-05
sources: [README, ARCH, NOTE02, NOTE04, NOTE06, NOTE07, A26-6]
---

# Using the app

The app is a food log for people who live with chronic kidney disease (CKD) and type 1 diabetes. You
write down what you eat, and it adds up the nutrients your care team asked you to watch: potassium,
phosphorus, sodium, protein, fluid and carbohydrate ([project README][README]).

It runs on a small server at home or at your clinic, not in a company's cloud. The person who runs
that server is called the **admin** in these pages.

## What it does

| You want to… | Use | Page |
|---|---|---|
| Put the app on your phone's Home Screen | your browser's Share or Install menu | [Install the app](install.md) |
| Sign in, set your stage and get starting targets | **Profile** → **Suggest targets** | [First setup](first-setup.md) |
| See why a food is red, yellow or green | the warnings on every food | [Targets and warnings](targets-and-warnings.md) |
| Log a meal, a snack or a drink | **Add** | [Logging food](logging.md) |
| Scan a barcode or use a photo of a label | **Add** → scan or photo | [Barcodes and label photos](barcode-and-photo.md) |
| Plan the week, reuse meals, make a shopping list | **Plan** | [Planning meals and using the menus](planning-and-menus.md) |
| Ask "what fits in my dinner?" | meal guidance | [Meal guidance](guidance.md) |
| Get optional AI ideas | settings for AI ideas | [Optional AI](ai.md) |
| Add your own USDA or AI key | **Settings** | [Settings and keys](settings-and-keys.md) |
| Take numbers to your dietitian | **Trends** → **Export CSV** | [Reports for your care team](reports-for-your-team.md) |
| See, export or delete your data | **Settings** → **Account** | [Privacy and your data](privacy.md) |

The screens at the bottom of the app are **Today**, **Add**, **Plan**, **Trends** and **Profile**
([architecture contract][ARCH]). This handbook opens from the **Learn** entry (the book icon) at the top of
the app and from **Settings → About & privacy**, at `/learn/` on the same server; warnings and notes in the
app link to the page that explains them.

## What it does not do

The app is a logging aid. It is **not a medical device** and it gives no medical advice
([project README][README]). In practice that means:

- **No insulin or medicine doses.** It shows carbohydrate in grams. It never turns grams into units,
  never suggests a dose and never tells you to change one ([architecture contract][ARCH]).
- **It never blocks or warns against treating a low.** Foods marked as low treatments (glucose
  tablets, gel, measured juice or clear regular soda) get no carbohydrate warning. Treat a low first and
  log it later
  ([ADA 2026][A26-6], section 6; [Treating a low](../t1d/treating-a-low.md)).
- **Its targets are starting points.** "Suggest targets" fills in numbers from guidelines, labeled
  "discuss with your care team". The numbers your nephrologist, diabetes team or renal dietitian give
  you always win.
- **It does not read your lab results for you.** You can type in a few lab values (**Profile → Lab
  results**) so the starting targets fit you better ([First setup](first-setup.md)). Your team explains
  what the results mean.
- **It is not for emergencies.** It does not watch your glucose and it cannot call for help.

!!! danger "Call 911 (or your local emergency number)"
    If you have chest pain, trouble breathing, a low you cannot treat by mouth, confusion or a
    seizure, call for help first. Do not open the app. The full list of warning signs is on
    [Get help now](../get-help-now.md).

## What to do first

- [ ] Ask the admin for **the address you will keep using**, for example
      `https://food.home.example.net`. Install the app from that address ([Install the app](install.md)).
- [ ] Sign in with the invite link or the account the admin made for you ([First setup](first-setup.md)).
- [ ] In **Profile**, enter your weight, height, CKD stage, dialysis and diabetes type.
- [ ] Copy in the targets your care team gave you. If you have none yet, tap **Suggest targets**, save,
      and take the numbers to your next visit.
- [ ] Log one full day, including drinks and low treatments, then look at **Today**.

## Privacy in short

- Your log lives in one database on your admin's server. Your phone keeps only a copy for offline
  use ([design note 02][NOTE02]).
- Each person has their own account. Other people on the same server cannot see your log, and the
  admin's screens have no way to read it. The admin can still reach the database file itself, so pick
  an admin you trust ([design note 07][NOTE07]).
- Nothing leaves the server until the admin turns on a feature that needs the internet: USDA search,
  barcode lookups or AI. AI is also off for you until you switch it on ([design note 04][NOTE04]).
- You can download everything you logged, and you can delete your account
  ([Privacy and your data](privacy.md)).

## Features coming in v0.3

Version 0.3 is being built now. Pages mark each feature that is not in your app yet with
**"coming in v0.3"**. They are:

- sign-in with accounts, invites and the **Settings** screen ([design note 07][NOTE07]);
- logging while offline, synced when you are back on Wi-Fi ([design note 02][NOTE02]);
- barcode scanning and label photos ([Barcodes and label photos](barcode-and-photo.md));
- meal guidance: "what fits now", swaps, "plan the rest of my day" and insights ([design note 06][NOTE06]);
- optional AI ideas ([Optional AI](ai.md)).

## If something goes wrong

- **A number looks wrong.** Check the serving size and the amount you entered. Builtin foods come from
  USDA data; foods you or others typed in can have mistakes ([Logging food](logging.md)).
- **The app will not open away from home.** Most home servers are reachable only on your home Wi-Fi
  or through a VPN. Ask your admin.
- **You forgot your password.** Ask the admin for a reset link. There is no email reset
  ([Privacy and your data](privacy.md)).

## Related pages

- [Start here](../index.md) · [Get help now](../get-help-now.md) · [Questions to ask](../reference/questions-to-ask.md)
- [About this handbook](../reference/about.md) · [Self-hosting](../self-hosting/index.md) (for admins)

## Sources

- [Project README][README]: what the app is and is not.
- [Project architecture contract][ARCH]: screens, warnings, the no-dosing rule.
- [Design note 02][NOTE02] (install and offline), [design note 04][NOTE04] (optional AI),
  [design note 06][NOTE06] (meal guidance), [design note 07][NOTE07] (accounts and privacy).
- [ADA Standards of Care 2026, section 6][A26-6]: treating a low.
