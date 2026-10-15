---
title: Privacy and your data
description: "What the app stores, who can see it, what leaves the server, and how to export or delete your data."
slug: privacy
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-15
fact_checked: 2026-10-05
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
| Profile, targets and lab results | server | |
| Symptoms you write down (the symptom, the date, how bad, your note) | server | in your export; never sent to an AI provider or to an assistant |
| Every log entry, your own foods, saved meals, foods you marked "Not for me" | server | |
| Settings, and your own API keys **encrypted** | server | keys are write-only ([Settings and keys](settings-and-keys.md)) |
| Your activity: sign-ins, password and key changes, exports | server | kept for 365 days by default |
| AI requests and answers, if you use AI | server | kept for 30 days by default; you can delete them ([Optional AI](ai.md)) |
| The app's own files, and the handbook pages you opened | your phone | for opening without a connection; the same for everyone, so signing out keeps them and **Clear offline data on this device** removes them |
| A copy of your recent days, your profile, the foods this phone has seen, and entries and changes waiting to sync | your phone (only for you) | removed when you sign out or tap **Clear offline data on this device** ([design note 02][NOTE02]) |
| Photos of a barcode or a label | your phone only | a barcode photo is read on the phone and never uploaded; a label photo is sent only if you ask AI to read it, and the server never keeps it ([Barcodes and label photos](barcode-and-photo.md)) |

## Who can see it

- **You**, after signing in.
- **Other people on the same server cannot.** Every request is checked against your account, and asking
  for someone else's entry gives "not found" ([architecture contract][ARCH]).
- **The admin** manages accounts but has **no screen to read your log** and no button to "become" you
  in the app ([design note 07][NOTE07]). Two honest limits:
    - The admin runs the server, so they can technically open the database file and any backup. Use a
      server run by someone you trust.
    - An admin can issue a password-reset link for your account and so could sign in as you. It cannot
      be done quietly: your devices are signed out, you see "Your password was reset by an admin on …"
      when you next sign in, and it shows in your activity.
- **Backups** made by the admin contain everyone's data until they expire.

!!! warning "If the app says “No sign-in”"
    A red banner, "No sign-in: anyone who can open this page can see and change this data", means the
    server runs without accounts. That is meant for one person on a trusted home network only. Do not
    share that server with anyone else ([design note 07][NOTE07]).

## What leaves the server

Nothing, unless a feature that needs the internet is switched on: by your admin for the server, or by
you when you add your own USDA or AI key ([design note 01][NOTE01]):

| Feature | What is sent | To |
|---|---|---|
| USDA search | your search words | USDA FoodData Central |
| Barcode lookups | the barcode digits only; Open Food Facts only after **you** agreed in **Settings → Food data** | Open Food Facts and USDA ([design note 03][NOTE03]) |
| AI ideas and photos (you must opt in and agree to each destination) | stage, targets, today's totals, candidate foods, the text or photo you send; never your name, weight or exact age | the AI provider your admin set up, or your own ([design note 04][NOTE04]) |
| Breached-password check | 5 characters of a scrambled form of your new password, never the password | Have I Been Pwned |

The handbook (**Learn**) loads nothing from the internet either.

## Take your data with you

- **Trends → Export CSV** saves every entry for the days on screen, for your dietitian
  ([Reports for your care team](reports-for-your-team.md)).
- **Settings → Account → Your data → Export my data (.zip)** downloads one file with everything you
  entered: profile, settings, every entry, your foods, saved meals, lab results, symptoms, "Not for me" foods, AI
  history and activity, as JSON and CSV, plus a `README.txt` that explains the files. No passwords,
  sessions or keys are included. You may need to enter your password again first
  ([design note 07][NOTE07]).
- **Settings → Account → Your data → Import from a file** brings an export back into your account, for
  example on a new server. See the next section.

## Move to another server

1. On the old server, press **Export my data (.zip)** and open the `.zip` on your device. The file you need
   is `export.json`; the CSV files are for reading in a spreadsheet.
2. On the new server, sign in (you need an account there first), then go to **Settings → Account → Your
   data → Import from a file** and choose `export.json`. Your password is asked for again.
3. The app first shows what would happen and changes nothing: what would be added, what is already there
   and left out, and any items it cannot match (each listed with the reason). A food that is not in the
   file and is not one of the app's built-in foods is listed, never guessed. A saved meal that loses a
   food this way says so in its note, so its totals do not look complete.
4. Press **Import**. Everything is added, or nothing is.

What comes across: your log entries, the foods you made, saved meals, lab results, symptoms and "Not for me" foods,
and the USDA and Open Food Facts foods you used (kept as your own copies if the new server does not have
them, with their licence note). The numbers of an entry are worked out again from its food and amount, as
for any entry you log.

What does not come across, even if a file has it: your password and sign-in sessions, assistant tokens and
every key, your AI history and the AI providers you agreed to, and your Open Food Facts choice. You agree
to those again on the new server.

Two boxes, both off at first:

- **Add to my existing data.** A new account is empty, so you do not need it. If the account already has
  entries, foods, saved meals, lab results or symptoms, the import is refused unless you tick it; then anything that
  is already there is left out, so importing the same file twice adds nothing.
- **Also replace my profile, targets and settings.** Your profile, food targets and meal-guidance
  settings are replaced by the ones in the file. They stay off by default because targets are best set
  with your kidney team, and you may already have set them on this server. Check them in **Profile**
  afterwards.

An import is limited to 16 MiB (years of entries) and to 20 tries an hour. It adds one line, "Data
imported", to your activity list.

## Delete your account

1. Export your data first if you may want it later.
2. **Settings → Account → Your data → Delete my account**.
3. Read the list of what will be deleted, enter your password and type `DELETE`.
4. Everything linked to your account is removed from the live database at once, including AI history.

Limits: the last admin cannot delete their own account until someone else is an admin. Copies in the
admin's backups remain until those backups expire. The automatic backup made when a server upgrades to
v0.3 is deleted 30 days after the upgrade ([design note 07][NOTE07]).

## Signing out

**Sign out** ends your session and clears the app's stored data on that device. If entries are still
waiting to sync, the app asks first (**Try to sync now**, **Stay signed in** or **Sign out and lose
them**), because they would be lost ([design note 02][NOTE02]).

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
