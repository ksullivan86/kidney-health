---
title: Settings and keys
description: "The Settings menu, shared and private API keys, daily limits, and settings that the server locks."
slug: settings-and-keys
audience: [app-user, patient, caregiver]
applies_to: [all]
status: draft
reviewed_by: ""
reviewed_on: null
last_checked: 2026-10-07
fact_checked: 2026-10-05
sources: [NOTE07, NOTE03, NOTE04, NOTE06, NOTE02, FDC-API]
---

# Settings and keys

**Settings** (the gear icon at the top, or **Profile → Open Settings**) holds everything that is not about your body or your targets; those stay in **Profile**.
Some features need a **key**: a password-like code from an outside service such as USDA or OpenAI. Keys
can be shared by your admin or added by you ([design note 07][NOTE07]).

## What is in Settings

| Section | What you find there |
|---|---|
| **Account** | your name, user name, **Change password**, **Signed-in devices**, **Your data** (export, delete account), your recent sign-in activity, **Sign out** |
| **Preferences** | theme (match device, light, dark), the day your week starts on, **Units for lab results** (US or SI: the unit offered first) |
| **Meal guidance** | on or off, carbohydrate tolerance, low-treatment amount, foods to leave out, your "Not for me" foods ([Meal guidance](guidance.md)) |
| **Food data** | your own USDA key, the shared key's status and today's remaining lookups, **Send barcodes I scan to Open Food Facts** ([Barcodes and label photos](barcode-and-photo.md)) |
| **AI ideas** | opt in, provider, your own AI provider and key, what you agreed to send, AI activity ([Optional AI](ai.md)) |
| **This device** | installed or not, "Offline ready", storage used, entries waiting to sync with **Sync now**, **Retry** and **Discard**, **Clear offline data on this device** ([Install the app](install.md)) |
| **Admin** (admins only) | users and invites, sign-in and registration, shared keys, usage, activity, about this server |
| **About & privacy** | what is stored, who can see it, disclaimers, **Learn** (this handbook), data sources and licences ([Privacy and your data](privacy.md)) |

## Shared keys and your own keys

| | Shared key (from your admin) | Your own key |
|---|---|---|
| Who pays or signs up | the admin | you |
| Daily limit in the app | yes: by default 200 USDA lookups and 30 AI calls per person per day | no app limit (the service's own limit still applies) |
| Who can read it back in the app | nobody, once saved | nobody, once saved, the admin included |
| If it stops working | ask the admin | replace it; the app **never** switches you to the shared key without asking |

The app uses **your own key first**. If you have none, it uses the shared key while your admin allows it
and today's limit is not used up. Otherwise the feature says what to do: "Add your own key in Settings →
Food data", or "Today's shared lookups are used up" ([design note 07][NOTE07]).

For AI, a failing own key is never replaced by the shared provider, because that would send your data
somewhere you did not agree to ([design note 04][NOTE04]).

## Add your own USDA key

A USDA FoodData Central key is free. It allows 1,000 requests an hour; USDA's public `DEMO_KEY` allows
only 30 an hour and 50 a day ([USDA API guide][FDC-API]).

1. Sign up at the USDA "Get an API key" page (linked from the [API guide][FDC-API]) with your email.
2. Copy the key from the email.
3. In the app: **Settings → Food data → USDA key → Replace** (or **Add**).
4. Paste the key, tap **Test**, then **Save**. The app asks for your password again if you have not
   entered it in the last 10 minutes.

## How keys are shown

Keys are **write-only**: after you save one, the app never shows it again, to you or anyone else.

- **Set**: "Set · ends in 9xQz · updated 3 Oct", with **Replace** and **Remove**.
- **Replacing**: an empty box (never pre-filled), **Test** and **Save**.
- **Set by the server**: the admin fixed it in the server's configuration. You see no buttons and
  cannot change it.
- **"Please enter your key again"**: the server can no longer read the stored key (for example after a
  restore without its encryption key). Add it again.

Keys are stored encrypted on the server. They are not included in your data export or in log files.

## Settings the server locks

Each setting comes from the first of these that has a value ([design note 07][NOTE07]):

1. **The server's configuration** (an environment variable). Shown as "Set by the server" and read-only.
2. **Your own choice**, for settings you are allowed to change.
3. **The admin's choice** for everyone on this server.
4. **The app's default.**

So if a switch is grayed out with "Set by the server", only the person who runs the server can change it
([Configuration](../self-hosting/configuration.md)).

## Password and devices

- **Change password**: needs your current password; at least 15 characters (unless your admin chose
  another minimum). Your other devices are signed out.
- **Signed-in devices**: lists your sessions. **Sign out** one you do not recognize, or
  **Sign out everywhere else**.
- Sensitive actions (changing a password or key, exporting, deleting your account) ask for your password
  again if you entered it more than 10 minutes ago.

## What to do

- [ ] Check **Food data**: do you have shared lookups, or do you need your own USDA key?
- [ ] Look at **Signed-in devices** after you get a new phone, and sign out the old one.
- [ ] Never send a key by text message or email to anyone; paste it only into the app.

## If something goes wrong

- **"Key rejected" after Test.** Copy it again, without spaces, and check you used the right service.
- **"Today's shared lookups are used up."** Wait until tomorrow, use the builtin foods and Quick add, or
  add your own key.
- **"Please enter your password again."** This is normal for sensitive actions; enter it and the app
  carries on.

## Related pages

- [Privacy and your data](privacy.md) · [Optional AI](ai.md) · [Logging food](logging.md)
- For admins: [Users and keys](../self-hosting/users-and-keys.md) · [Configuration](../self-hosting/configuration.md)

## Sources

- [Design note 07: accounts, settings and secrets][NOTE07], sections 4.11, 4.12 and 4.17.
- [Design note 02][NOTE02] (This device); [design note 03][NOTE03] (barcode settings); [design note 04][NOTE04] (AI keys);
  [design note 06][NOTE06] (guidance settings).
- [USDA FoodData Central API guide][FDC-API]: free keys and rate limits.
