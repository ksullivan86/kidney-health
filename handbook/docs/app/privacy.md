---
title: Privacy and your data
description: "What the app stores, who can see it, what leaves the server, and how to export or delete your data."
slug: privacy
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-06
sources: [NOTE01, NOTE02, NOTE03, NOTE04, NOTE07, ARCH, GDPR]
---

# Privacy and your data

Your food log is health information. The app keeps it on one server that your admin runs, not in a
company's cloud, and it sends nothing out unless a feature that needs the internet is switched on
([design note 07][NOTE07]). This page says what is stored, who can see it, and how to take it with you
or delete it.

## What is stored, and where

| What | Where | Notes |
|---|---|---|
| Your account: user name, display name, password **hash** | server | the password itself is never stored |
| Profile and targets; from v0.3 lab results | server | |
| Every log entry, your own foods, saved meals | server | |
| Settings, and your own API keys **encrypted** | server | keys are write-only ([Settings and keys](settings-and-keys.md)) |
| Your activity: sign-ins, password and key changes, exports | server | kept for 365 days by default |
| AI requests and answers, if you use AI | server | kept for 30 days by default; you can delete them ([Optional AI](ai.md)) |
| The app's own files | your phone | for opening without a connection |
| From v0.3: the last 14 days, your foods, and entries waiting to sync | your phone | removed when you sign out ([design note 02][NOTE02]) |

## Who can see it

- **You**, after signing in.
- **Other people on the same server cannot.** Every request is checked against your account, and asking
  for someone else's entry gives "not found" ([architecture contract][ARCH]).
- **The admin** manages accounts but has **no screen to read your log** and cannot "become" you in the
  app ([design note 07][NOTE07]). Two honest limits:
    - The admin runs the server, so they can technically open the database file and any backup. Use a
      server run by someone you trust.
    - An admin can issue a password-reset link for your account. If that happens, your other devices are
      signed out, you see "Your password was reset by an admin on …" when you next sign in, and it shows
      in your activity.
- **Backups** made by the admin contain everyone's data until they expire.

!!! warning "If the app says \"No sign-in\""
    A red banner, "No sign-in: anyone who can open this page can see and change this data", means the
    server runs without accounts. That is meant for one person on a trusted home network only. Do not
    share that server with anyone else ([design note 07][NOTE07]).

## What leaves the server

Nothing, unless your admin switches a feature on ([design note 01][NOTE01]):

| Feature | What is sent | To |
|---|---|---|
| USDA search | your search words | USDA FoodData Central |
| Barcode lookups | the barcode digits only | Open Food Facts, then USDA ([design note 03][NOTE03]) |
| AI ideas (you must also opt in) | stage, targets, today's totals, candidate foods; never your name, weight or exact age | the AI provider your admin set up ([design note 04][NOTE04]) |
| Breached-password check | 5 characters of a scrambled form of your new password, never the password | Have I Been Pwned |

The handbook (**Learn**) loads nothing from the internet either.

## Take your data with you

- **Today:** **Trends → Export CSV** saves every entry for the days on screen
  ([Reports for your care team](reports-for-your-team.md)).
- **Coming in v0.3:** **Settings → Account → Your data → Export** downloads one `.zip` file with
  everything: profile, settings, every entry, your foods, saved meals, labs, AI history and activity, as
  JSON and CSV, plus a `README.txt`. No passwords or keys are included. You may need to enter your
  password again first ([design note 07][NOTE07]).

## Delete your account (coming in v0.3)

1. Export your data first if you may want it later.
2. **Settings → Account → Your data → Delete account**.
3. Read the list of what will be deleted, enter your password and type `DELETE`.
4. Everything linked to your account is removed from the live database at once, including AI history.

Limits: the last admin cannot delete their own account until someone else is an admin. Copies in the
admin's backups remain until those backups expire. The automatic backup made when a server upgrades to
v0.3 is deleted 30 days after the upgrade ([design note 07][NOTE07]).

## Signing out

**Sign out** ends your session and clears the app's stored data on that device. If entries are still
waiting to sync (v0.3), the app warns you first, because they would be lost ([design note 02][NOTE02]).

## What to do

- [ ] Use a long password that you use nowhere else (a password manager helps).
- [ ] Lock your phone with a code or fingerprint; the installed app stays signed in for up to 30 days.
- [ ] Sign out on shared or borrowed devices.
- [ ] Check **Settings → Account → Signed-in devices** now and then.
- [ ] Ask your admin how backups are kept and encrypted.

## Privacy law, in short

In the EU, data protection law (GDPR) does not apply to a purely personal or household activity, such as
a family running a server for itself. A server offered to other people is different: health data is a
special category there, and people have rights to see, export and erase their data
([GDPR][GDPR], Articles 2, 9, 15, 17 and 20). The export and delete features are built with that in mind.
This is not legal advice.

## Related pages

- [Settings and keys](settings-and-keys.md) · [Optional AI](ai.md) · [Install the app](install.md)
- For admins: [Security](../self-hosting/security.md) · [Backups](../self-hosting/backups.md)

## Sources

- [Design note 07: accounts, settings and secrets][NOTE07], sections 4.5, 4.13–4.15 and the security review.
- [Design note 01][NOTE01] (outbound traffic); [design note 02][NOTE02] (data on the phone);
  [design note 03][NOTE03] (barcodes); [design note 04][NOTE04] (AI payload).
- [Project architecture contract][ARCH]: every query scoped to the signed-in person.
- [EU General Data Protection Regulation][GDPR].
